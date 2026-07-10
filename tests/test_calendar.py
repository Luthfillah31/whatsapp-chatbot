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
