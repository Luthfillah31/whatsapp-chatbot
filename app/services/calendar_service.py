import os
import datetime
import logging
from typing import Optional, List, Dict, Any, cast
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
    court_id: Optional[int] = None
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
            now = datetime.datetime.now()
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

    # Query local database for confirmed and pending bookings that overlap this time slot
    all_bookings = db.query(Booking).filter(
        Booking.booking_date == date,
        Booking.start_time <= time_slot,
        Booking.end_time > time_slot,
        Booking.status.in_(["confirmed", "pending_payment"])
    ).all()

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
    rate = settings.HOURLY_RATE_IDR
    cal_alert = f"[PENGINGAT KALENDER: Tanggal {date} adalah HARI {day_name.upper()}. Jika pengguna menyebut hari lain seperti Senin/Selasa, Anda WAJIB memberi tahu bahwa {date} adalah Hari {day_name}.]\n"
    if court_id == 1:
        status_text = f"tersedia (Rp {rate:,}/jam)" if c1_avail else "SUDAH TERISI"
        summary = f"{cal_alert}Hari {day_name}, {date} jam {time_slot}: {settings.COURT_1_NAME} {status_text}."
    elif court_id == 2:
        status_text = f"tersedia (Rp {rate:,}/jam)" if c2_avail else "SUDAH TERISI"
        summary = f"{cal_alert}Hari {day_name}, {date} jam {time_slot}: {settings.COURT_2_NAME} {status_text}."
    else:
        c1_str = f"Tersedia (Rp {rate:,}/jam)" if c1_avail else "Sudah Terisi"
        c2_str = f"Tersedia (Rp {rate:,}/jam)" if c2_avail else "Sudah Terisi"
        summary = f"{cal_alert}Hari {day_name}, {date} jam {time_slot}:\n- {settings.COURT_1_NAME}: {c1_str}\n- {settings.COURT_2_NAME}: {c2_str}"

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
            court_name=f"Court {court_id}",
            date=date,
            start_time=time_slot,
            end_time=time_slot,
            status="failed",
            message="Invalid court number. Please select Court 1 or Court 2."
        )

    if not isinstance(duration_hours, int):
        try:
            duration_hours = int(duration_hours)
        except (ValueError, TypeError):
            duration_hours = 1
    if duration_hours < 1:
        duration_hours = 1
    if duration_hours > 6:
        return BookingResponse(
            success=False,
            court_id=court_id,
            court_name=f"Court {court_id}",
            date=date,
            start_time=time_slot,
            end_time=time_slot,
            status="failed",
            message="Mohon maaf, durasi maksimal reservasi dalam satu booking adalah 6 jam."
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
    total_amount = duration_hours * settings.HOURLY_RATE_IDR
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
        message=f"Reservasi berhasil dibuat! Silakan lakukan pembayaran Rp {settings.HOURLY_RATE_IDR:,} melalui link ini untuk konfirmasi: {p_url}. Batas waktu pembayaran 10 menit."
    )


def cancel_booking(db: Session, booking_id: int, customer_phone: str, customer_name: Optional[str] = None) -> Dict[str, Any]:
    """Cancels an existing reservation by booking ID and customer phone (or verified customer name).
    
    SECURITY: Only bookings belonging to `customer_phone` can be cancelled directly.
    If `customer_name` is provided for 2-factor verification, a booking made under a different
    phone can be cancelled IF AND ONLY IF the registered name exactly matches (case-insensitive).
    """
    booking = db.query(Booking).filter(
        Booking.id == booking_id,
        Booking.customer_phone == customer_phone,
        Booking.status.in_(["confirmed", "pending_payment"])
    ).first()

    # If not found by direct phone match, check 2-factor verification (name match)
    if not booking and customer_name:
        candidate = db.query(Booking).filter(
            Booking.id == booking_id,
            Booking.status.in_(["confirmed", "pending_payment"])
        ).first()
        if candidate and candidate.customer_name.strip().lower() == customer_name.strip().lower():
            booking = candidate
            logger.info(f"SECURITY: Booking #{booking_id} cancelled via 2-Factor Verification (Name: '{customer_name}').")

    if not booking:
        # Check if the booking exists under a different phone (for security logging only)
        other_booking = db.query(Booking).filter(
            Booking.id == booking_id,
            Booking.status.in_(["confirmed", "pending_payment"])
        ).first()
        if other_booking and other_booking.customer_phone != customer_phone:
            logger.warning(
                f"SECURITY: Phone {customer_phone} attempted to cancel booking #{booking_id} "
                f"without valid name verification. Access denied."
            )
        return {
            "success": False,
            "message": f"Tidak ditemukan reservasi aktif dengan ID #{booking_id} pada nomor Anda atau verifikasi nama tidak cocok."
        }

    # Cancel in local database
    booking.status = "cancelled"
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
        "message": f"✅ Your reservation #{booking_id} for {court_name} on {booking.booking_date} at {booking.start_time} has been successfully cancelled."
    }


def get_user_bookings(db: Session, customer_phone: str, date: Optional[str] = None) -> List[Dict[str, Any]]:
    """Returns all confirmed upcoming bookings for a specific customer phone number.
    
    Optionally filters by a specific date. If omitted, returns bookings from today onwards.
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
