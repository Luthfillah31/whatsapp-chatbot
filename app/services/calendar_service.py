import os
import datetime
import logging
from typing import Optional, List, Dict, Any, cast
from sqlalchemy.orm import Session
from app.config import settings
from app.models.db_models import Booking
from app.models.schemas import (
    CourtAvailabilityResponse,
    BookingResponse,
    ScheduleSlot,
    DailyScheduleResponse
)

logger = logging.getLogger(__name__)

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
    today = datetime.date.today()
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
        return CourtAvailabilityResponse(
            date=date,
            time_slot=time_slot,
            court_1_available=False,
            court_2_available=False,
            summary_text=f"Mohon maaf, tanggal {date} sudah lewat. Silakan pilih tanggal hari ini atau yang akan datang."
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

    # Query local database for confirmed bookings at this date and time
    existing_bookings = db.query(Booking).filter(
        Booking.booking_date == date,
        Booking.start_time == time_slot,
        Booking.status == "confirmed"
    ).all()

    booked_court_ids = {b.court_id for b in existing_bookings}

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
    rate = settings.HOURLY_RATE_USD
    if court_id == 1:
        status_text = f"available (${rate}/hr)" if c1_avail else "already BOOKED"
        summary = f"On {date} at {time_slot}, {settings.COURT_1_NAME} is {status_text}."
    elif court_id == 2:
        status_text = f"available (${rate}/hr)" if c2_avail else "already BOOKED"
        summary = f"On {date} at {time_slot}, {settings.COURT_2_NAME} is {status_text}."
    else:
        c1_str = f"Available (${rate}/hr)" if c1_avail else "Booked"
        c2_str = f"Available (${rate}/hr)" if c2_avail else "Booked"
        summary = f"On {date} at {time_slot}:\n- {settings.COURT_1_NAME}: {c1_str}\n- {settings.COURT_2_NAME}: {c2_str}"

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
    customer_phone: str
) -> BookingResponse:
    """
    Creates a new tennis court reservation in the SQL database and optionally syncs with Google Calendar.
    Prevents double-booking with strict conflict validation.
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

    # Check availability
    avail = check_court_availability(db, date, time_slot, court_id)
    is_free = avail.court_1_available if court_id == 1 else avail.court_2_available
    court_name = settings.COURT_1_NAME if court_id == 1 else settings.COURT_2_NAME

    if not is_free:
        msg = avail.summary_text if "operasional" in avail.summary_text.lower() else f"Sorry! {court_name} is already booked on {date} at {time_slot}. Please choose another time or check the other court."
        return BookingResponse(
            success=False,
            court_id=court_id,
            court_name=court_name,
            date=date,
            start_time=time_slot,
            end_time=calculate_end_time(time_slot),
            status="failed",
            message=msg
        )

    end_time = calculate_end_time(time_slot)
    google_event_id = None

    # Sync to Google Calendar if configured
    g_service = get_google_calendar_service()
    cal_id = settings.GOOGLE_CALENDAR_ID_COURT_1 if court_id == 1 else settings.GOOGLE_CALENDAR_ID_COURT_2
    if g_service and cal_id:
        try:
            event_body = {
                'summary': f"🎾 {court_name} - {customer_name}",
                'description': f"Reserved via WhatsApp Bot.\nCustomer: {customer_name}\nPhone: {customer_phone}",
                'start': {'dateTime': f"{date}T{time_slot}:00", 'timeZone': 'UTC'},
                'end': {'dateTime': f"{date}T{end_time}:00", 'timeZone': 'UTC'},
            }
            created_event = cast(Any, g_service).events().insert(calendarId=cal_id, body=event_body).execute()
            google_event_id = created_event.get('id')
        except Exception as e:
            logger.error(f"Failed to insert event into Google Calendar: {e}")

    # Create database record
    new_booking = Booking(
        court_id=court_id,
        customer_phone=customer_phone,
        customer_name=customer_name,
        booking_date=date,
        start_time=time_slot,
        end_time=end_time,
        status="confirmed",
        google_event_id=google_event_id
    )
    db.add(new_booking)
    db.commit()
    db.refresh(new_booking)

    bid = cast(int, new_booking.id)
    return BookingResponse(
        success=True,
        booking_id=bid,
        court_id=court_id,
        court_name=court_name,
        date=date,
        start_time=time_slot,
        end_time=end_time,
        status="confirmed",
        message=f"🎉 Reservation confirmed! {court_name} is booked for {customer_name} on {date} from {time_slot} to {end_time}. Booking ID: #{bid}."
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
        Booking.status == "confirmed"
    ).first()

    # If not found by direct phone match, check 2-factor verification (name match)
    if not booking and customer_name:
        candidate = db.query(Booking).filter(
            Booking.id == booking_id,
            Booking.status == "confirmed"
        ).first()
        if candidate and candidate.customer_name.strip().lower() == customer_name.strip().lower():
            booking = candidate
            logger.info(f"SECURITY: Booking #{booking_id} cancelled via 2-Factor Verification (Name: '{customer_name}').")

    if not booking:
        # Check if the booking exists under a different phone (for security logging only)
        other_booking = db.query(Booking).filter(
            Booking.id == booking_id,
            Booking.status == "confirmed"
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
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    query = db.query(Booking).filter(
        Booking.customer_phone == customer_phone,
        Booking.status == "confirmed"
    )
    if date and str(date).strip():
        query = query.filter(Booking.booking_date == str(date).strip())
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
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    query = db.query(Booking).filter(
        Booking.customer_phone == customer_phone,
        Booking.status == "confirmed"
    )
    if date and str(date).strip():
        query = query.filter(Booking.booking_date == str(date).strip())
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

    bookings = db.query(Booking).filter(
        Booking.booking_date == date,
        Booking.status == "confirmed"
    ).all()

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

        slots.append(ScheduleSlot(
            time=time_str,
            court_1_status="Booked" if b1 else "Available",
            court_1_booking_id=b1.id if b1 else None,
            court_1_customer=b1.customer_name if b1 else None,
            court_1_phone=b1.customer_phone if b1 else None,
            court_2_status="Booked" if b2 else "Available",
            court_2_booking_id=b2.id if b2 else None,
            court_2_customer=b2.customer_name if b2 else None,
            court_2_phone=b2.customer_phone if b2 else None,
        ))

    return DailyScheduleResponse(date=date, slots=slots)
