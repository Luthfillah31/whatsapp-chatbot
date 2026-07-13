import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.db_models import Base
from app.services import calendar_service


@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        yield db
    finally:
        db.close()


def test_double_booking_prevention(test_db):
    """Test that booking the same court at the same time fails with clean message."""
    # First booking should succeed
    res1 = calendar_service.create_booking(
        db=test_db,
        court_id=1,
        date="2026-08-15",
        time_slot="14:00",
        customer_name="Alice",
        customer_phone="111"
    )
    assert res1.success is True
    assert res1.booking_id == 1

    # Attempting to book Court 1 at 14:00 again should fail!
    res2 = calendar_service.create_booking(
        db=test_db,
        court_id=1,
        date="2026-08-15",
        time_slot="14:00",
        customer_name="Bob",
        customer_phone="222"
    )
    assert res2.success is False
    assert ("already booked" in res2.message.lower() or "sudah terisi" in res2.message.lower())

    # But Court 2 at 14:00 should succeed!
    res3 = calendar_service.create_booking(
        db=test_db,
        court_id=2,
        date="2026-08-15",
        time_slot="14:00",
        customer_name="Bob",
        customer_phone="222"
    )
    assert res3.success is True
    assert res3.booking_id == 2


def test_cancellation_flow(test_db):
    """Test cancelling an existing reservation and freeing up the court."""
    res = calendar_service.create_booking(
        db=test_db,
        court_id=1,
        date="2026-08-15",
        time_slot="10:00",
        customer_name="Charlie",
        customer_phone="333"
    )
    booking_id = res.booking_id
    assert booking_id is not None

    # Cancel booking
    cancel_res = calendar_service.cancel_booking(test_db, booking_id, "333")
    assert cancel_res["success"] is True

    # Check availability - court should be free again!
    avail = calendar_service.check_court_availability(test_db, "2026-08-15", "10:00", court_id=1)
    assert avail.court_1_available is True


def test_daily_schedule_grid(test_db):
    """Test generating hourly grid for the web dashboard."""
    res = calendar_service.create_booking(
        db=test_db,
        court_id=1,
        date="2026-09-01",
        time_slot="09:00",
        customer_name="David",
        customer_phone="444"
    )
    assert res.booking_id is not None
    calendar_service.confirm_payment(test_db, res.booking_id)
    
    grid = calendar_service.get_daily_schedule(test_db, "2026-09-01")
    assert grid.date == "2026-09-01"
    assert len(grid.slots) > 0

    # Find the 09:00 slot
    slot_09 = next((s for s in grid.slots if s.time == "09:00"), None)
    assert slot_09 is not None
    assert slot_09.court_1_status == "Booked"
    assert slot_09.court_1_customer == "David"
    assert slot_09.court_1_phone == "444"
    assert slot_09.court_2_status == "Available"


def test_2factor_verification_flow(test_db):
    """Test 2-factor verification (Phone + Name) for listing and cancellation."""
    # 1. Create a booking registered under preferred phone 08123456789 and name Luthfi
    res = calendar_service.create_booking(
        db=test_db,
        court_id=1,
        date="2026-10-10",
        time_slot="15:00",
        customer_name="Luthfi Akhtar",
        customer_phone="08123456789"
    )
    assert res.success is True
    booking_id = res.booking_id
    assert booking_id is not None

    # 2. Check get_user_bookings from sender phone +15550000 -> should be 0 results (isolated)
    my_bookings = calendar_service.get_user_bookings(test_db, "+15550000")
    assert len(my_bookings) == 0

    # 3. Check get_user_bookings_by_verification with correct phone and name (case-insensitive test)
    verified = calendar_service.get_user_bookings_by_verification(
        db=test_db,
        customer_phone="08123456789",
        customer_name="luthfi akhtar"
    )
    assert len(verified) == 1
    assert verified[0]["booking_id"] == booking_id
    assert verified[0]["registered_name"] == "Luthfi Akhtar"

    # 4. Check get_user_bookings_by_verification with wrong name -> should be 0 results!
    wrong_name = calendar_service.get_user_bookings_by_verification(
        db=test_db,
        customer_phone="08123456789",
        customer_name="Budi"
    )
    assert len(wrong_name) == 0

    # 5. Attempt to cancel from sender phone +15550000 without name verification -> should fail!
    fail_cancel = calendar_service.cancel_booking(
        db=test_db,
        booking_id=booking_id,
        customer_phone="+15550000"
    )
    assert fail_cancel["success"] is False

    # 6. Attempt to cancel from sender phone +15550000 WITH wrong name -> should fail!
    fail_cancel2 = calendar_service.cancel_booking(
        db=test_db,
        booking_id=booking_id,
        customer_phone="+15550000",
        customer_name="Budi"
    )
    assert fail_cancel2["success"] is False

    # 7. Attempt to cancel from sender phone +15550000 WITH correct name verification -> should succeed!
    success_cancel = calendar_service.cancel_booking(
        db=test_db,
        booking_id=booking_id,
        customer_phone="+15550000",
        customer_name="Luthfi Akhtar"
    )
    assert success_cancel["success"] is True

    # Verify booking status is cancelled
    verified_after = calendar_service.get_user_bookings_by_verification(test_db, "08123456789", "Luthfi Akhtar")
    assert len(verified_after) == 0


def test_reject_non_hourly_fractional_minutes(test_db):
    """Verify check_court_availability and create_booking reject non-hourly slots (e.g. 09:35 or 12:35)."""
    avail = calendar_service.check_court_availability(test_db, "2026-08-20", "09:35", court_id=1)
    assert avail.court_1_available is False
    assert "bulat" in avail.summary_text.lower()

    book_res = calendar_service.create_booking(
        db=test_db,
        court_id=1,
        date="2026-08-20",
        time_slot="12:35",
        customer_name="Daffa",
        customer_phone="08123"
    )
    assert book_res.success is False
    assert "bulat" in book_res.message.lower()


def test_multi_hour_booking(test_db):
    """Verify booking multiple consecutive hours (e.g. 06:00 to 10:00 = 4 hours)."""
    book_res = calendar_service.create_booking(
        db=test_db,
        court_id=1,
        date="2026-08-25",
        time_slot="06:00",
        customer_name="Daffa Multi",
        customer_phone="0812345",
        duration_hours=4
    )
    assert book_res.success is True
    assert book_res.start_time == "06:00"
    assert book_res.end_time == "10:00"

    avail07 = calendar_service.check_court_availability(test_db, "2026-08-25", "07:00", court_id=1)
    assert avail07.court_1_available is False


def test_check_calendar_date_and_optional_time_slot(test_db):
    """Verify check_calendar_date returns exact Indonesian day and check_court_availability handles empty slot."""
    cal_res = calendar_service.check_calendar_date("2026-07-26")
    assert cal_res["day_name"] == "Minggu"
    assert "MINGGU" in cal_res["summary_text"]

    avail_empty = calendar_service.check_court_availability(test_db, "2026-07-26", time_slot="")
    assert avail_empty.time_slot == "ALL_DAY"
    assert "MINGGU" in avail_empty.summary_text


def test_past_date_rejection_in_tools(test_db):
    """Verify check_calendar_date and check_court_availability warn strongly on past dates."""
    past_date = "2020-01-01"
    cal_res = calendar_service.check_calendar_date(past_date)
    assert cal_res["is_past"] is True
    assert "SUDAH LEWAT" in cal_res["summary_text"]

    avail_res = calendar_service.check_court_availability(test_db, past_date, time_slot="")
    assert avail_res.court_1_available is False
    assert "SUDAH LEWAT" in avail_res.summary_text


def test_wib_timezone_helpers():
    """Verify get_wib_now and get_wib_today return dates in UTC+7 (WIB)."""
    wib_now = calendar_service.get_wib_now()
    assert wib_now.tzinfo is not None
    assert calendar_service.get_wib_today() == wib_now.date()


def test_create_booking_time_range_inference(test_db):
    """Verify create_booking automatically infers duration and start_time when time_slot is a range string."""
    res = calendar_service.create_booking(
        db=test_db,
        court_id=2,
        date="2026-07-22",
        time_slot="15:00 - 18:00",
        customer_name="Luthfi",
        customer_phone="+62812345",
        duration_hours=1
    )
    assert res.success is True
    assert res.start_time == "15:00"
    assert res.end_time == "18:00"
    assert res.total_amount == 230000


def test_cancel_booking_flexible_id_and_phone(test_db):
    """Verify cancel_booking works even if booking_id is passed as a string with text prefix and phone number has format variations."""
    res = calendar_service.create_booking(
        db=test_db,
        court_id=2,
        date="2026-07-25",
        time_slot="15:00",
        customer_name="Luthfi",
        customer_phone="+62 813-9547-0202",
        duration_hours=3
    )
    assert res.success is True
    assert res.booking_id is not None

    # Cancel passing string "ID <id>" and phone without spacing/prefix "+62"
    cancel_res = calendar_service.cancel_booking(
        db=test_db,
        booking_id=f"ID {res.booking_id}",
        customer_phone="081395470202"
    )
    assert cancel_res["success"] is True

    # Check list_my_bookings does not return the cancelled booking
    my_bookings = calendar_service.get_user_bookings(test_db, customer_phone="6281395470202")
    assert not any(b["booking_id"] == res.booking_id for b in my_bookings)


def test_multihour_daily_schedule_grid(test_db):
    """Verify get_daily_schedule marks every hour of a multi-hour booking as booked."""
    res = calendar_service.create_booking(
        db=test_db,
        court_id=1,
        date="2026-07-28",
        time_slot="18:00",
        customer_name="Luthfi",
        customer_phone="+628123456",
        duration_hours=2
    )
    assert res.success is True

    sched = calendar_service.get_daily_schedule(test_db, "2026-07-28")
    slot_map = {s.time: s for s in sched.slots}
    assert slot_map["18:00"].court_1_status in ["Pending Payment", "Booked"]
    assert slot_map["19:00"].court_1_status in ["Pending Payment", "Booked"]
    assert slot_map["18:00"].court_1_customer == "Luthfi"
    assert slot_map["19:00"].court_1_customer == "Luthfi"


def test_reschedule_booking_service(test_db):
    """Verify reschedule_booking service function behaves correctly across courts and slots without extra charge."""
    res = calendar_service.create_booking(
        db=test_db,
        court_id=1,
        date="2026-07-30",
        time_slot="18:00",
        customer_name="Luthfi",
        customer_phone="+6281395470202",
        duration_hours=2
    )
    assert res.success is True
    booking_id = res.booking_id

    # 1. Reschedule to Court 2, 19:00 - 21:00
    resched = calendar_service.reschedule_booking(
        db=test_db,
        booking_id=booking_id,
        new_date="2026-07-30",
        new_time_slot="19:00",
        customer_phone="+6281395470202",
        new_court_id=2
    )
    assert resched.success is True
    assert resched.booking_id == booking_id
    assert resched.court_id == 2
    assert resched.start_time == "19:00"
    assert resched.end_time == "21:00"
    assert resched.status == "confirmed"
    assert resched.payment_status == "paid"
    assert resched.payment_url is None
    assert resched.total_amount == 0

    # 2. Verify schedule grid reflects movement
    sched = calendar_service.get_daily_schedule(test_db, "2026-07-30")
    slot_map = {s.time: s for s in sched.slots}
    assert slot_map["18:00"].court_1_status == "Available"
    assert slot_map["19:00"].court_2_status == "Booked"
    assert slot_map["20:00"].court_2_status == "Booked"

