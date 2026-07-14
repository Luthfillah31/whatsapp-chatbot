import os
import datetime
import re
import logging
from typing import Optional, List, Dict, Any, cast, Tuple
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.config import settings
from app.models.db_models import Booking
from app.models.schemas import (
    CourtAvailabilityResponse,
    BookingResponse,
    ScheduleSlot,
    DailyScheduleResponse
)
from app.services import payment_service

logger = logging.getLogger(__name__)

WIB_TZ = datetime.timezone(datetime.timedelta(hours=7))


def get_wib_now() -> datetime.datetime:
    """Returns current datetime in WIB (Asia/Jakarta, UTC+7)."""
    return datetime.datetime.now(WIB_TZ)


def get_wib_today() -> datetime.date:
    """Returns current date in WIB (Asia/Jakarta, UTC+7)."""
    return get_wib_now().date()


INDONESIAN_DAYS = {
    "Monday": "Senin",
    "Tuesday": "Selasa",
    "Wednesday": "Rabu",
    "Thursday": "Kamis",
    "Friday": "Jumat",
    "Saturday": "Sabtu",
    "Sunday": "Minggu"
}


def get_indonesian_day_name(dt: datetime.date) -> str:
    return INDONESIAN_DAYS.get(dt.strftime("%A"), dt.strftime("%A"))


def get_slot_hourly_rate(time_slot: str) -> int:
    """Return hourly rate based on start time slot (05:00-17:00 = 75.000, 17:00-23:00 = 80.000)."""
    try:
        hour = int(time_slot.split(":")[0])
        if hour >= 17:
            return getattr(settings, "HOURLY_RATE_EVENING_IDR", 80000)
        else:
            return getattr(settings, "HOURLY_RATE_DAYTIME_IDR", 75000)
    except Exception:
        return settings.HOURLY_RATE_IDR


def calculate_total_booking_price(start_time: str, duration_hours: int) -> int:
    """Calculate total price summing up hourly rate for each hour."""
    total = 0
    try:
        start_h = int(start_time.split(":")[0])
        for offset in range(duration_hours):
            h = start_h + offset
            if h >= 17:
                total += getattr(settings, "HOURLY_RATE_EVENING_IDR", 80000)
            else:
                total += getattr(settings, "HOURLY_RATE_DAYTIME_IDR", 75000)
        return total
    except Exception:
        return duration_hours * settings.HOURLY_RATE_IDR


def get_booking_price_breakdown(start_time: str, duration_hours: int) -> Tuple[int, str]:
    """Calculate total price and detailed hourly breakdown string for multi-hour bookings."""
    total = 0
    parts = []
    try:
        start_h = int(start_time.split(":")[0])
        for offset in range(duration_hours):
            h = start_h + offset
            h_str = f"{h:02d}:00"
            next_h_str = f"{h + 1:02d}:00"
            if h >= 17:
                rate = getattr(settings, "HOURLY_RATE_EVENING_IDR", 80000)
            else:
                rate = getattr(settings, "HOURLY_RATE_DAYTIME_IDR", 75000)
            total += rate
            rate_formatted = f"Rp {rate:,}".replace(",", ".")
            parts.append(f"{h_str}-{next_h_str} {rate_formatted}")
        breakdown_str = " + ".join(parts)
        total_formatted = f"Rp {total:,}".replace(",", ".")
        if duration_hours > 1:
            end_h_str = f"{start_h + duration_hours:02d}:00"
            summary_str = f"Total {total_formatted} untuk {duration_hours} jam ({start_time}-{end_h_str}: {breakdown_str})"
        else:
            summary_str = f"{total_formatted}/jam"
        return total, summary_str
    except Exception:
        total = calculate_total_booking_price(start_time, duration_hours)
        total_formatted = f"Rp {total:,}".replace(",", ".")
        return total, f"Total {total_formatted}"


# Try importing Google API client libraries
try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    GOOGLE_API_AVAILABLE = True
except ImportError:
    GOOGLE_API_AVAILABLE = False


def get_google_calendar_service():
    """Initializes and returns the Google Calendar API service if credentials are configured."""
    if not GOOGLE_API_AVAILABLE:
        return None
    
    key_file = settings.GOOGLE_SERVICE_ACCOUNT_FILE
    if not key_file or not os.path.exists(key_file):
        return None

    try:
        scopes = ['https://www.googleapis.com/auth/calendar']
        creds = service_account.Credentials.from_service_account_file(key_file, scopes=scopes)
        service = build('calendar', 'v3', credentials=creds)
        return service
    except Exception as e:
        logger.error(f"Failed to initialize Google Calendar API: {e}")
        return None


def calculate_end_time(start_time: str, duration_hours: int = 1) -> str:
    """Calculates end time in HH:MM format given start time and duration."""
    try:
        t = datetime.datetime.strptime(start_time, "%H:%M")
        end_t = t + datetime.timedelta(hours=duration_hours)
        return end_t.strftime("%H:%M")
    except ValueError:
        # Fallback if time format is unexpected
        parts = start_time.split(":")
        hour = int(parts[0]) + duration_hours
        return f"{hour:02d}:{parts[1] if len(parts) > 1 else '00'}"


def check_calendar_date(date: str) -> Dict[str, Any]:
    """Checks exact Day of the Week and whether the date is past/today/future."""
    today = get_wib_today()
    try:
        dt = datetime.date.fromisoformat(date)
        day_name = get_indonesian_day_name(dt)
        if dt < today:
            summary = f"[PERINGATAN KRISIAL: Tanggal {date} ({day_name}) SUDAH LEWAT / MASA LALU!] Anda WAJIB memberi tahu pengguna bahwa tanggal {date} sudah lewat dan tidak bisa dicek atau dipesan. DILARANG menanyakan jam main!"
            is_past = True
        elif dt == today:
            summary = f"KALENDER RESMI: Tanggal {date} adalah HARI INI ({day_name.upper()})."
            is_past = False
        else:
            summary = f"KALENDER RESMI: Tanggal {date} adalah HARI {day_name.upper()}."
            is_past = False
        return {
            "date": date,
            "day_name": day_name,
            "is_past": is_past,
            "summary_text": summary
        }
    except Exception:
        return {
            "date": date,
            "day_name": "Unknown",
            "is_past": False,
            "summary_text": f"Format tanggal {date} tidak valid (Gunakan YYYY-MM-DD)."
        }


def check_court_availability(
    db: Session, 
    date: str, 
    time_slot: str, 
    court_id: Optional[int] = None,
    exclude_booking_id: Optional[int] = None,
    duration_hours: int = 1
) -> CourtAvailabilityResponse:
    """
    Checks if Court 1 and/or Court 2 are available on the specified date and time slot.
    Queries the local SQL database as the primary source of truth, and verifies against Google Calendar if configured.
    """
    # Validate: reject past dates entirely
    today = get_wib_today()
    try:
        booking_date = datetime.date.fromisoformat(date)
    except (ValueError, TypeError):
        return CourtAvailabilityResponse(
            date=date,
            time_slot=time_slot,
            court_1_available=False,
            court_2_available=False,
            summary_text=f"Format tanggal '{date}' tidak valid. Gunakan format YYYY-MM-DD."
        )

    if booking_date < today:
        day_name = get_indonesian_day_name(booking_date)
        return CourtAvailabilityResponse(
            date=date,
            time_slot=time_slot or "",
            court_1_available=False,
            court_2_available=False,
            summary_text=f"[PERINGATAN KRISIAL: Tanggal {date} ({day_name}) SUDAH LEWAT / MASA LALU!] Mohon maaf, tanggal {date} sudah lewat. Anda WAJIB menolak permintaan ini dan DILARANG menanyakan jam main untuk tanggal yang sudah lewat."
        )

    day_name = get_indonesian_day_name(booking_date)
    cal_alert = f"[PENGINGAT KALENDER RESMI: Tanggal {date} adalah HARI {day_name.upper()}! Jika pengguna menyebut nama hari lain (seperti Senin/Selasa), Anda WAJIB langsung memberi tahu bahwa {date} adalah Hari {day_name}.]\n"

    if not time_slot or time_slot.strip() == "" or time_slot.lower() in ["all_day", "none", "null"]:
        return CourtAvailabilityResponse(
            date=date,
            time_slot="ALL_DAY",
            court_1_available=True,
            court_2_available=True,
            summary_text=f"{cal_alert}Tanggal {date} jatuh pada Hari {day_name}. Jam operasional kompleks: 05:00 - 23:00 WIB. Silakan tanyakan kepada warga ingin menyewa mulai jam berapa."
        )

    # Validate: reject past time slots for today
    try:
        req_h = int(time_slot.split(":")[0])
        req_m = int(time_slot.split(":")[1]) if ":" in time_slot else 0
        if booking_date == today:
            now = get_wib_now()
            if req_h < now.hour or (req_h == now.hour and req_m <= now.minute):
                return CourtAvailabilityResponse(
                    date=date,
                    time_slot=time_slot,
                    court_1_available=False,
                    court_2_available=False,
                    summary_text=f"Mohon maaf, jam {time_slot} sudah lewat untuk hari ini. Silakan pilih jam yang lebih sore."
                )
    except (ValueError, IndexError):
        pass

    # Validate: reject non-hourly time slots (minutes != 0)
    try:
        parts = time_slot.split(":")
        req_m = int(parts[1]) if len(parts) > 1 else 0
        if req_m != 0:
            return CourtAvailabilityResponse(
                date=date,
                time_slot=time_slot,
                court_1_available=False,
                court_2_available=False,
                summary_text=f"Mohon maaf, penyewaan lapangan hanya tersedia per blok 1 jam bulat (misal: 08:00, 09:00, 10:00). Format jam dengan menit pecahan '{time_slot}' tidak tersedia."
            )
    except Exception:
        pass

    # Validate operating hours
    try:
        start_h = int(settings.CLUB_OPENING_HOUR.split(":")[0])
        end_h = int(settings.CLUB_CLOSING_HOUR.split(":")[0])
        req_h = int(time_slot.split(":")[0])
        if req_h < start_h or req_h >= end_h:
            msg = f"Mohon maaf, jam {time_slot} berada di luar jam operasional lapangan ({settings.CLUB_OPENING_HOUR} - {settings.CLUB_CLOSING_HOUR} WIB)."
            return CourtAvailabilityResponse(
                date=date,
                time_slot=time_slot,
                court_1_available=False,
                court_2_available=False,
                summary_text=msg
            )
    except Exception:
        pass

    try:
        duration_hours = max(1, duration_hours)
    except (ValueError, TypeError):
        duration_hours = 1
    req_end_time = calculate_end_time(time_slot, duration_hours)

    query = db.query(Booking).filter(
        Booking.booking_date == date,
        Booking.start_time < req_end_time,
        Booking.end_time > time_slot,
        Booking.status.in_(["confirmed", "pending_payment"])
    )
    if exclude_booking_id is not None:
        query = query.filter(Booking.id != exclude_booking_id)
    all_bookings = query.all()

    booked_court_ids = set()
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    for b in all_bookings:
        if b.status == "confirmed":
            booked_court_ids.add(b.court_id)
        elif b.status == "pending_payment":
            created_utc = b.created_at
            if created_utc.tzinfo is None:
                created_utc = created_utc.replace(tzinfo=datetime.timezone.utc)
            if now_utc - created_utc < datetime.timedelta(minutes=10):
                booked_court_ids.add(b.court_id)
            else:
                # Release/expire booking
                b.status = "cancelled"
                b.payment_status = "expired"
                db.commit()

    # Check Google Calendar if configured
    g_service = get_google_calendar_service()
    if g_service:
        try:
            start_dt = f"{date}T{time_slot}:00Z"
            end_time_slot = calculate_end_time(time_slot)
            end_dt = f"{date}T{end_time_slot}:00Z"

            for c_id, cal_id in [(1, settings.GOOGLE_CALENDAR_ID_COURT_1), (2, settings.GOOGLE_CALENDAR_ID_COURT_2)]:
                if cal_id and c_id not in booked_court_ids:
                    events_result = cast(Any, g_service).events().list(
                        calendarId=cal_id,
                        timeMin=start_dt,
                        timeMax=end_dt,
                        singleEvents=True
                    ).execute()
                    if events_result.get('items'):
                        booked_court_ids.add(c_id)
        except Exception as e:
            logger.error(f"Error checking Google Calendar availability: {e}")

    c1_avail = 1 not in booked_court_ids
    c2_avail = 2 not in booked_court_ids

    # If specific court was requested, adjust summary text
    day_name = get_indonesian_day_name(booking_date)
    total_price, price_info = get_booking_price_breakdown(time_slot, duration_hours)
    end_slot = calculate_end_time(time_slot, duration_hours)
    if duration_hours > 1:
        time_display = f"{time_slot}-{end_slot} ({duration_hours} jam)"
    else:
        time_display = time_slot

    cal_alert = f"[PENGINGAT KALENDER: Tanggal {date} adalah HARI {day_name.upper()}. Jika pengguna menyebut hari lain seperti Senin/Selasa, Anda WAJIB memberi tahu bahwa {date} adalah Hari {day_name}.]\n"
    if court_id == 1:
        status_text = f"tersedia ({price_info})" if c1_avail else "SUDAH TERISI"
        summary = f"{cal_alert}Hari {day_name}, {date} jam {time_display}: {settings.COURT_1_NAME} {status_text}."
    elif court_id == 2:
        status_text = f"tersedia ({price_info})" if c2_avail else "SUDAH TERISI"
        summary = f"{cal_alert}Hari {day_name}, {date} jam {time_display}: {settings.COURT_2_NAME} {status_text}."
    else:
        c1_str = f"Tersedia ({price_info})" if c1_avail else "Sudah Terisi"
        c2_str = f"Tersedia ({price_info})" if c2_avail else "Sudah Terisi"
        summary = f"{cal_alert}Hari {day_name}, {date} jam {time_display}:\n- {settings.COURT_1_NAME}: {c1_str}\n- {settings.COURT_2_NAME}: {c2_str}"

    return CourtAvailabilityResponse(
        date=date,
        time_slot=time_slot,
        court_1_available=c1_avail,
        court_2_available=c2_avail,
        summary_text=summary
    )


def create_booking(
    db: Session,
    court_id: int,
    date: str,
    time_slot: str,
    customer_name: str,
    customer_phone: str,
    duration_hours: int = 1
) -> BookingResponse:
    """
    Creates a new tennis court reservation in the SQL database and optionally syncs with Google Calendar.
    Prevents double-booking with strict conflict validation across all requested duration hours.
    """
    if court_id not in [1, 2]:
        return BookingResponse(
            success=False,
            court_id=court_id,
            court_name=f"Lapangan {court_id}",
            date=date,
            start_time=time_slot,
            end_time=time_slot,
            status="failed",
            message=f"Pilihan lapangan tidak valid. Silakan pilih {settings.COURT_1_NAME} (1) atau {settings.COURT_2_NAME} (2)."
        )

    if "-" in time_slot:
        try:
            parts = [p.strip() for p in time_slot.split("-")]
            sh = int(parts[0].split(":")[0])
            eh = int(parts[1].split(":")[0])
            if duration_hours <= 1 and eh > sh:
                duration_hours = max(1, min(18, eh - sh))
            time_slot = parts[0]
        except Exception:
            pass

    if not isinstance(duration_hours, int):
        try:
            duration_hours = int(duration_hours)
        except (ValueError, TypeError):
            duration_hours = 1
    if duration_hours < 1:
        duration_hours = 1
    if duration_hours > 18:
        return BookingResponse(
            success=False,
            court_id=court_id,
            court_name=f"Court {court_id}",
            date=date,
            start_time=time_slot,
            end_time=time_slot,
            status="failed",
            message="Mohon maaf, durasi maksimal reservasi dalam satu booking adalah 18 jam."
        )

    court_name = settings.COURT_1_NAME if court_id == 1 else settings.COURT_2_NAME

    # Check availability across all requested consecutive hours
    for h_offset in range(duration_hours):
        try:
            slot_dt = datetime.datetime.strptime(time_slot, "%H:%M") + datetime.timedelta(hours=h_offset)
            slot_str = slot_dt.strftime("%H:%M")
        except Exception:
            slot_str = time_slot
        avail = check_court_availability(db, date, slot_str, court_id)
        is_free = avail.court_1_available if court_id == 1 else avail.court_2_available
        if not is_free:
            return BookingResponse(
                success=False,
                court_id=court_id,
                court_name=court_name,
                date=date,
                start_time=time_slot,
                end_time=calculate_end_time(time_slot, duration_hours),
                status="failed",
                message=f"Mohon maaf, untuk jam {slot_str} pada tanggal {date} {court_name} tidak tersedia ({avail.summary_text})."
            )

    end_time = calculate_end_time(time_slot, duration_hours)

    # Create database record in pending_payment status (Do not sync with Google Calendar yet)
    new_booking = Booking(
        court_id=court_id,
        customer_phone=customer_phone,
        customer_name=customer_name,
        booking_date=date,
        start_time=time_slot,
        end_time=end_time,
        status="pending_payment",
        payment_status="pending",
        google_event_id=None
    )
    db.add(new_booking)
    try:
        db.commit()
        db.refresh(new_booking)
    except IntegrityError:
        db.rollback()
        return BookingResponse(
            success=False,
            court_id=court_id,
            court_name=court_name,
            date=date,
            start_time=time_slot,
            end_time=end_time,
            status="failed",
            message=f"Mohon maaf, {court_name} pada tanggal {date} jam {time_slot} baru saja diproses atau sudah dibooking oleh warga lain. Silakan pilih waktu/lapangan lain."
        )

    # Generate payment transaction details
    bid = cast(int, new_booking.id)
    total_amount = calculate_total_booking_price(time_slot, duration_hours)
    payment_info = payment_service.create_midtrans_transaction(
        booking_id=bid,
        amount=total_amount,
        customer_name=customer_name,
        customer_phone=customer_phone
    )

    # Update payment link in DB
    redirect_url = payment_info.get("redirect_url")
    token = payment_info.get("token")
    new_booking.payment_url = cast(Any, redirect_url if redirect_url is not None else "")
    new_booking.payment_token = cast(Any, token if token is not None else "")
    db.commit()

    p_url = str(new_booking.payment_url) if new_booking.payment_url else None

    return BookingResponse(
        success=True,
        booking_id=bid,
        court_id=court_id,
        court_name=court_name,
        date=date,
        start_time=time_slot,
        end_time=end_time,
        status="pending_payment",
        payment_url=p_url,
        payment_status="pending",
        total_amount=total_amount,
        message=f"Reservasi berhasil dibuat! Silakan lakukan pembayaran Rp {total_amount:,} melalui link ini untuk konfirmasi: {p_url}. Batas waktu pembayaran 10 menit. 📍 Lokasi Lapangan: {settings.CLUB_LOCATION_URL}"
    )


def cancel_booking(db: Session, booking_id: Any, customer_phone: str, customer_name: Optional[str] = None) -> Dict[str, Any]:
    """Cancels an existing reservation by numeric booking ID and customer phone suffix (or verified customer name)."""
    bid_digits = re.findall(r'\d+', str(booking_id))
    if not bid_digits:
        return {
            "success": False,
            "message": f"ID reservasi tidak valid: {booking_id}"
        }
    numeric_id = int(bid_digits[0])

    candidate = db.query(Booking).filter(
        Booking.id == numeric_id,
        Booking.status.in_(["confirmed", "pending_payment"])
    ).first()

    def _phone_match(p1: str, p2: str) -> bool:
        d1 = re.sub(r'\D', '', p1 or '')
        d2 = re.sub(r'\D', '', p2 or '')
        if not d1 or not d2:
            return False
        return d1[-9:] == d2[-9:]

    booking = None
    if candidate:
        if _phone_match(candidate.customer_phone, customer_phone):
            booking = candidate
        elif customer_name and candidate.customer_name.strip().lower() == customer_name.strip().lower():
            booking = candidate
            logger.info(f"SECURITY: Booking #{numeric_id} cancelled via 2-Factor Verification (Name: '{customer_name}').")

    if not booking:
        other_booking = db.query(Booking).filter(
            Booking.id == numeric_id,
            Booking.status.in_(["confirmed", "pending_payment"])
        ).first()
        if other_booking:
            logger.warning(
                f"SECURITY: Phone {customer_phone} attempted to cancel booking #{numeric_id} "
                f"without valid name verification. Access denied."
            )
        return {
            "success": False,
            "message": f"Tidak ditemukan reservasi aktif dengan ID #{numeric_id} pada nomor Anda atau verifikasi nama tidak cocok."
        }

    # Cancel in local database
    booking.status = "cancelled"
    booking.payment_status = "cancelled"
    db.commit()

    # Remove from Google Calendar if present
    if booking.google_event_id:
        g_service = get_google_calendar_service()
        cal_id = settings.GOOGLE_CALENDAR_ID_COURT_1 if booking.court_id == 1 else settings.GOOGLE_CALENDAR_ID_COURT_2
        if g_service and cal_id:
            try:
                cast(Any, g_service).events().delete(calendarId=cal_id, eventId=booking.google_event_id).execute()
            except Exception as e:
                logger.error(f"Failed to delete event from Google Calendar: {e}")

    court_name = settings.COURT_1_NAME if booking.court_id == 1 else settings.COURT_2_NAME
    return {
        "success": True,
        "booking_id": numeric_id,
        "status": "cancelled",
        "message": f"✅ Reservasi #{numeric_id} untuk {court_name} pada tanggal {booking.booking_date} jam {booking.start_time} - {booking.end_time} berhasil dibatalkan."
    }


def reschedule_booking(
    db: Session,
    booking_id: Any,
    new_date: Optional[str] = None,
    new_time_slot: Optional[str] = None,
    customer_phone: str = "",
    new_court_id: Optional[int] = None,
    duration_hours: Optional[int] = None,
    customer_name: Optional[str] = None
) -> BookingResponse:
    """
    Reschedules an existing booking to a new date, time slot, or court without requiring a new payment.
    Ensures that the new schedule is available and maintains the booking ID and confirmed status.
    """
    bid_digits = re.findall(r'\d+', str(booking_id))
    if not bid_digits:
        return BookingResponse(
            success=False,
            court_id=new_court_id or 1,
            court_name="Court 1",
            date=new_date or "",
            start_time=new_time_slot or "",
            end_time=new_time_slot or "",
            status="failed",
            message=f"ID reservasi tidak valid: {booking_id}"
        )
    numeric_id = int(bid_digits[0])

    candidate = db.query(Booking).filter(
        Booking.id == numeric_id,
        Booking.status.in_(["confirmed", "pending_payment"])
    ).first()

    def _phone_match(p1: str, p2: str) -> bool:
        d1 = re.sub(r'\D', '', p1 or '')
        d2 = re.sub(r'\D', '', p2 or '')
        if not d1 or not d2:
            return False
        return d1[-9:] == d2[-9:]

    booking = None
    if candidate:
        if _phone_match(candidate.customer_phone, customer_phone):
            booking = candidate
        elif customer_name and candidate.customer_name.strip().lower() == customer_name.strip().lower():
            booking = candidate
            logger.info(f"SECURITY: Booking #{numeric_id} rescheduled via 2-Factor Verification (Name: '{customer_name}').")

    if not booking:
        return BookingResponse(
            success=False,
            court_id=new_court_id or 1,
            court_name="Court 1",
            date=new_date or "",
            start_time=new_time_slot or "",
            end_time=new_time_slot or "",
            status="failed",
            message=f"Tidak ditemukan reservasi aktif dengan ID #{numeric_id} pada nomor Anda atau verifikasi nama tidak cocok."
        )

    target_court_id = new_court_id if new_court_id in [1, 2] else booking.court_id
    court_name = settings.COURT_1_NAME if target_court_id == 1 else settings.COURT_2_NAME
    target_date = new_date.strip() if (new_date and new_date.strip()) else booking.booking_date
    target_slot = new_time_slot.strip() if (new_time_slot and new_time_slot.strip()) else booking.start_time

    # Validate target date format and prevent past date booking
    today = get_wib_today()
    try:
        booking_date = datetime.date.fromisoformat(target_date)
    except (ValueError, TypeError):
        return BookingResponse(
            success=False,
            booking_id=booking.id,
            court_id=target_court_id,
            court_name=court_name,
            date=target_date,
            start_time=str(target_slot),
            end_time=str(target_slot),
            status="failed",
            message=f"Format tanggal '{target_date}' tidak valid. Gunakan format YYYY-MM-DD."
        )

    if booking_date < today:
        day_name = get_indonesian_day_name(booking_date)
        return BookingResponse(
            success=False,
            booking_id=booking.id,
            court_id=target_court_id,
            court_name=court_name,
            date=target_date,
            start_time=str(target_slot),
            end_time=str(target_slot),
            status="failed",
            message=f"Mohon maaf, tanggal {target_date} ({day_name}) sudah lewat. Pemindahan jadwal tidak dapat dilakukan ke tanggal masa lalu."
        )

    # Determine start time and duration
    time_slot_str = str(target_slot).strip()
    parsed_duration = None
    if "-" in time_slot_str:
        try:
            parts = [p.strip() for p in time_slot_str.split("-")]
            sh = int(parts[0].split(":")[0])
            eh = int(parts[1].split(":")[0])
            if eh > sh:
                parsed_duration = max(1, min(18, eh - sh))
            time_slot_str = parts[0]
        except Exception:
            pass

    old_duration = 1
    try:
        sh_old = int(booking.start_time.split(":")[0])
        eh_old = int(booking.end_time.split(":")[0])
        if eh_old > sh_old:
            old_duration = max(1, min(18, eh_old - sh_old))
    except Exception:
        pass

    final_duration = duration_hours if (isinstance(duration_hours, int) and 1 <= duration_hours <= 18) else (parsed_duration or old_duration)
    new_end_time = calculate_end_time(time_slot_str, final_duration)

    # Check availability across consecutive hours excluding current booking
    for h_offset in range(final_duration):
        try:
            slot_dt = datetime.datetime.strptime(time_slot_str, "%H:%M") + datetime.timedelta(hours=h_offset)
            slot_str = slot_dt.strftime("%H:%M")
        except Exception:
            slot_str = time_slot_str
        avail = check_court_availability(db, target_date, slot_str, target_court_id, exclude_booking_id=booking.id)
        is_free = avail.court_1_available if target_court_id == 1 else avail.court_2_available
        if not is_free:
            return BookingResponse(
                success=False,
                booking_id=booking.id,
                court_id=target_court_id,
                court_name=court_name,
                date=target_date,
                start_time=time_slot_str,
                end_time=new_end_time,
                status="failed",
                message=f"Mohon maaf, untuk jam {slot_str} pada tanggal {target_date} {court_name} tidak tersedia ({avail.summary_text})."
            )

    old_court_id = booking.court_id
    booking.court_id = target_court_id
    booking.booking_date = target_date
    booking.start_time = time_slot_str
    booking.end_time = new_end_time
    booking.status = "confirmed"
    booking.payment_status = "paid"
    booking.payment_url = None

    if booking.google_event_id:
        g_service = get_google_calendar_service()
        old_cal_id = settings.GOOGLE_CALENDAR_ID_COURT_1 if old_court_id == 1 else settings.GOOGLE_CALENDAR_ID_COURT_2
        if g_service and old_cal_id:
            try:
                cast(Any, g_service).events().delete(calendarId=old_cal_id, eventId=booking.google_event_id).execute()
            except Exception as e:
                logger.error(f"Failed to delete old event from Google Calendar during reschedule: {e}")
            booking.google_event_id = None

    g_service = get_google_calendar_service()
    cal_id = settings.GOOGLE_CALENDAR_ID_COURT_1 if target_court_id == 1 else settings.GOOGLE_CALENDAR_ID_COURT_2
    if g_service and cal_id:
        try:
            event_body = {
                'summary': f"🎾 {court_name} - {booking.customer_name}",
                'description': f"Reserved via WhatsApp Bot (Rescheduled).\nCustomer: {booking.customer_name}\nPhone: {booking.customer_phone}\nPayment Status: Paid",
                'start': {'dateTime': f"{target_date}T{time_slot_str}:00", 'timeZone': 'UTC'},
                'end': {'dateTime': f"{target_date}T{new_end_time}:00", 'timeZone': 'UTC'},
            }
            created_event = cast(Any, g_service).events().insert(calendarId=cal_id, body=event_body).execute()
            booking.google_event_id = created_event.get('id')
        except Exception as e:
            logger.error(f"Failed to insert event into Google Calendar during reschedule: {e}")

    try:
        db.commit()
        db.refresh(booking)
    except IntegrityError:
        db.rollback()
        return BookingResponse(
            success=False,
            booking_id=booking.id,
            court_id=target_court_id,
            court_name=court_name,
            date=target_date,
            start_time=time_slot_str,
            end_time=new_end_time,
            status="failed",
            message=f"Mohon maaf, {court_name} pada tanggal {target_date} jam {time_slot_str} baru saja diproses atau sudah dibooking oleh warga lain."
        )

    return BookingResponse(
        success=True,
        booking_id=booking.id,
        court_id=target_court_id,
        court_name=court_name,
        date=target_date,
        start_time=time_slot_str,
        end_time=new_end_time,
        status="confirmed",
        payment_url=None,
        payment_status="paid",
        total_amount=0,
        message=f"✅ Jadwal reservasi #{booking.id} berhasil dipindahkan ke {court_name} pada tanggal {target_date} jam {time_slot_str} - {new_end_time} tanpa biaya tambahan (Status: Konfirmasi ✅)."
    )



def get_user_bookings(db: Session, customer_phone: str, date: Optional[str] = None) -> List[Dict[str, Any]]:
    """Returns all confirmed upcoming bookings for a specific customer phone number."""
    today_str = get_wib_today().strftime("%Y-%m-%d")
    all_active = db.query(Booking).filter(
        Booking.status.in_(["confirmed", "pending_payment"])
    )
    if date and date.strip():
        all_active = all_active.filter(Booking.booking_date == date.strip())
    else:
        all_active = all_active.filter(Booking.booking_date >= today_str)

    bookings = []
    d_input = re.sub(r'\D', '', customer_phone or '')
    for b in all_active.order_by(Booking.booking_date, Booking.start_time).all():
        d_db = re.sub(r'\D', '', str(b.customer_phone or ''))
        if d_input and d_db and d_input[-9:] == d_db[-9:]:
            bookings.append(b)

    results = []
    for b in bookings:
        c_name = settings.COURT_1_NAME if b.court_id == 1 else settings.COURT_2_NAME
        results.append({
            "booking_id": b.id,
            "court_name": c_name,
            "date": b.booking_date,
            "start_time": b.start_time,
            "end_time": b.end_time,
            "customer_name": b.customer_name,
            "status": b.status
        })
    return results


def get_user_bookings_by_verification(db: Session, customer_phone: str, customer_name: str, date: Optional[str] = None) -> List[Dict[str, Any]]:
    """Returns upcoming bookings matching BOTH phone number and customer name (2-Factor Verification).
    
    SECURITY: Both parameters must match (case-insensitive name match) to prevent unauthorized inspection.
    """
    today_str = get_wib_today().strftime("%Y-%m-%d")
    query = db.query(Booking).filter(
        Booking.customer_phone == customer_phone,
        Booking.status.in_(["confirmed", "pending_payment"])
    )
    if date and date.strip():
        query = query.filter(Booking.booking_date == date.strip())
    else:
        query = query.filter(Booking.booking_date >= today_str)

    bookings = query.order_by(Booking.booking_date, Booking.start_time).all()

    # Case-insensitive check in python
    matched = [
        b for b in bookings
        if b.customer_name.strip().lower() == customer_name.strip().lower()
    ]

    results = []
    for b in matched:
        c_name = settings.COURT_1_NAME if b.court_id == 1 else settings.COURT_2_NAME
        results.append({
            "booking_id": b.id,
            "court_name": c_name,
            "date": b.booking_date,
            "start_time": b.start_time,
            "end_time": b.end_time,
            "status": b.status,
            "registered_name": b.customer_name,
            "registered_phone": b.customer_phone
        })
    return results


def get_daily_schedule(db: Session, date: str) -> DailyScheduleResponse:
    """Generates a complete hourly grid of court availability for the web dashboard."""
    start_h = int(settings.CLUB_OPENING_HOUR.split(":")[0])
    end_h = int(settings.CLUB_CLOSING_HOUR.split(":")[0])

    all_bookings = db.query(Booking).filter(
        Booking.booking_date == date,
        Booking.status.in_(["confirmed", "pending_payment"])
    ).all()

    bookings = []
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    for b in all_bookings:
        if b.status == "confirmed":
            bookings.append(b)
        elif b.status == "pending_payment":
            created_utc = b.created_at
            if created_utc.tzinfo is None:
                created_utc = created_utc.replace(tzinfo=datetime.timezone.utc)
            if now_utc - created_utc < datetime.timedelta(minutes=10):
                bookings.append(b)
            else:
                b.status = "cancelled"
                b.payment_status = "expired"
                db.commit()

    c1_map = {}
    c2_map = {}
    for b in bookings:
        try:
            sh = int(str(b.start_time).split(":")[0])
            eh = int(str(b.end_time).split(":")[0])
            for h in range(sh, max(sh + 1, eh)):
                t_str = f"{h:02d}:00"
                if b.court_id == 1:
                    c1_map[t_str] = b
                elif b.court_id == 2:
                    c2_map[t_str] = b
        except Exception:
            if b.court_id == 1:
                c1_map[b.start_time] = b
            elif b.court_id == 2:
                c2_map[b.start_time] = b

    slots = []
    for hour in range(start_h, end_h):
        time_str = f"{hour:02d}:00"
        b1 = c1_map.get(time_str)
        b2 = c2_map.get(time_str)

        # Status text "Booked" or "Pending Payment" or "Available"
        status_1 = "Available"
        if b1:
            status_1 = "Booked" if b1.status == "confirmed" else "Pending Payment"
            
        status_2 = "Available"
        if b2:
            status_2 = "Booked" if b2.status == "confirmed" else "Pending Payment"

        slots.append(ScheduleSlot(
            time=time_str,
            court_1_status=status_1,
            court_1_booking_id=b1.id if b1 else None,
            court_1_customer=b1.customer_name if b1 else None,
            court_1_phone=b1.customer_phone if b1 else None,
            court_2_status=status_2,
            court_2_booking_id=b2.id if b2 else None,
            court_2_customer=b2.customer_name if b2 else None,
            court_2_phone=b2.customer_phone if b2 else None,
        ))

    return DailyScheduleResponse(date=date, slots=slots)


def confirm_payment(db: Session, booking_id: int) -> bool:
    """
    Confirms a booking's payment status, updates status to 'confirmed',
    and synchronizes it with Google Calendar.
    """
    booking = db.query(Booking).filter(
        Booking.id == booking_id,
        Booking.status == "pending_payment"
    ).first()
    if not booking:
        logger.warning(f"Booking #{booking_id} not found or not pending payment.")
        return False
        
    booking.status = "confirmed"
    booking.payment_status = "paid"
    
    # Sync to Google Calendar
    g_service = get_google_calendar_service()
    court_name = settings.COURT_1_NAME if booking.court_id == 1 else settings.COURT_2_NAME
    cal_id = settings.GOOGLE_CALENDAR_ID_COURT_1 if booking.court_id == 1 else settings.GOOGLE_CALENDAR_ID_COURT_2
    if g_service and cal_id:
        try:
            event_body = {
                'summary': f"🎾 {court_name} - {booking.customer_name}",
                'description': f"Reserved via WhatsApp Bot.\nCustomer: {booking.customer_name}\nPhone: {booking.customer_phone}\nPayment Status: Paid",
                'start': {'dateTime': f"{booking.booking_date}T{booking.start_time}:00", 'timeZone': 'UTC'},
                'end': {'dateTime': f"{booking.booking_date}T{booking.end_time}:00", 'timeZone': 'UTC'},
            }
            created_event = cast(Any, g_service).events().insert(calendarId=cal_id, body=event_body).execute()
            booking.google_event_id = created_event.get('id')
        except Exception as e:
            logger.error(f"Failed to insert event into Google Calendar: {e}")
            
    db.commit()
    logger.info(f"Payment confirmed for Booking #{booking_id}")
    return True


def search_available_slots(
    db: Session,
    start_date: str,
    end_date: Optional[str] = None,
    min_hour: int = 5,
    max_hour: int = 22,
    court_id: Optional[int] = None
) -> Dict[str, Any]:
    """Scans and returns all free hours for Lapangan A and Lapangan B across one or multiple dates."""
    if not end_date:
        end_date = start_date

    try:
        dt_start = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
        dt_end = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()
    except Exception:
        return {
            "status": "error",
            "message": "Format tanggal salah. Gunakan YYYY-MM-DD."
        }

    if dt_end < dt_start:
        dt_end = dt_start

    days_count = (dt_end - dt_start).days + 1
    if days_count > 14:
        dt_end = dt_start + datetime.timedelta(days=13)

    min_h = max(0, min(23, min_hour))
    max_h = max(min_h, min(23, max_hour))

    results = []
    curr = dt_start
    while curr <= dt_end:
        date_str = curr.strftime("%Y-%m-%d")
        day_name = get_indonesian_day_name(curr)

        bookings = db.query(Booking).filter(
            Booking.booking_date == date_str,
            Booking.status.in_(["confirmed", "pending_payment"])
        ).all()

        c1_booked_hours = set()
        c2_booked_hours = set()

        for b in bookings:
            try:
                sh = int(b.start_time.split(":")[0])
                eh = int(b.end_time.split(":")[0])
                for h in range(sh, max(sh + 1, eh)):
                    if b.court_id == 1:
                        c1_booked_hours.add(h)
                    elif b.court_id == 2:
                        c2_booked_hours.add(h)
            except Exception:
                pass

        c1_free = []
        c2_free = []
        for h in range(min_h, max_h + 1):
            slot_str = f"{h:02d}:00"
            if h not in c1_booked_hours and (court_id is None or court_id == 1):
                c1_free.append(slot_str)
            if h not in c2_booked_hours and (court_id is None or court_id == 2):
                c2_free.append(slot_str)

        results.append({
            "date": date_str,
            "day_name": day_name,
            "lapangan_A_free_slots": c1_free if (court_id is None or court_id == 1) else None,
            "lapangan_B_free_slots": c2_free if (court_id is None or court_id == 2) else None
        })

        curr += datetime.timedelta(days=1)

    lines = [f"Daftar Jadwal Kosong dari {start_date} s/d {dt_end.strftime('%Y-%m-%d')} (Rentang jam {min_h:02d}:00 - {max_h:02d}:00):\n"]
    for r in results:
        lines.append(f"📅 *{r['day_name']}, {r['date']}*:")
        if r['lapangan_A_free_slots'] is not None:
            a_slots = ", ".join(r['lapangan_A_free_slots']) if r['lapangan_A_free_slots'] else "Penuh"
            lines.append(f"  - Lapangan A: {a_slots}")
        if r['lapangan_B_free_slots'] is not None:
            b_slots = ", ".join(r['lapangan_B_free_slots']) if r['lapangan_B_free_slots'] else "Penuh"
            lines.append(f"  - Lapangan B: {b_slots}")
        lines.append("")

    summary_text = "\n".join(lines)

    return {
        "status": "success",
        "search_range": f"{start_date} to {dt_end.strftime('%Y-%m-%d')}",
        "min_hour": f"{min_h:02d}:00",
        "max_hour": f"{max_h:02d}:00",
        "days": results,
        "summary": summary_text
    }
