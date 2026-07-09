import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.db_models import Base, Booking, init_db
from app.services import calendar_service


@pytest.fixture
def test_db():
    # Use SQLite memory database
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    # Run creation using our init_db flow which sets up raw SQL index as well
    # Bind to this test engine by replacing the global engine or calling create_all manually
    Base.metadata.create_all(bind=engine)
    
    # Run the SQL migration query manually on the test in-memory db
    import sqlite3
    from sqlalchemy import text
    with engine.connect() as conn:
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_active_booking ON bookings (court_id, booking_date, start_time) WHERE status IN ('confirmed', 'pending_payment')"
        ))
        conn.commit()

    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        yield db
    finally:
        db.close()


def test_concurrent_booking_conflict(test_db):
    """Test that two bookings for the same court, date, and hour fail on the second attempt."""
    # First booking should succeed (in pending_payment status)
    res1 = calendar_service.create_booking(
        db=test_db,
        court_id=1,
        date="2026-08-20",
        time_slot="10:00",
        customer_name="Alice",
        customer_phone="111"
    )
    assert res1.success is True
    assert res1.status == "pending_payment"

    # Second booking for the exact same slot should fail via IntegrityError check
    from unittest.mock import patch
    from app.models.schemas import CourtAvailabilityResponse
    
    mock_avail = CourtAvailabilityResponse(
        date="2026-08-20",
        time_slot="10:00",
        court_1_available=True,
        court_2_available=True,
        summary_text="Mocked available"
    )
    
    with patch("app.services.calendar_service.check_court_availability", return_value=mock_avail):
        res2 = calendar_service.create_booking(
            db=test_db,
            court_id=1,
            date="2026-08-20",
            time_slot="10:00",
            customer_name="Bob",
            customer_phone="222"
        )
        
    assert res2.success is False
    assert "baru saja diproses" in res2.message.lower() or "sudah dibooking" in res2.message.lower()


def test_booking_after_cancellation(test_db):
    """Test that after a booking is cancelled, a new booking for the same slot is allowed."""
    res1 = calendar_service.create_booking(
        db=test_db,
        court_id=1,
        date="2026-08-20",
        time_slot="11:00",
        customer_name="Alice",
        customer_phone="111"
    )
    assert res1.success is True
    assert res1.booking_id is not None

    # Cancel the first booking
    cancel_res = calendar_service.cancel_booking(test_db, res1.booking_id, "111")
    assert cancel_res["success"] is True

    # Attempting to book the slot again should succeed because cancelled bookings are excluded from the unique index!
    res2 = calendar_service.create_booking(
        db=test_db,
        court_id=1,
        date="2026-08-20",
        time_slot="11:00",
        customer_name="Bob",
        customer_phone="222"
    )
    assert res2.success is True
    assert res2.status == "pending_payment"
