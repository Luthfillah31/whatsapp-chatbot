import pytest
import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.db_models import Base, Booking
from app.services import calendar_service, payment_service


from sqlalchemy.pool import StaticPool


@pytest.fixture
def test_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        yield db
    finally:
        db.close()


def test_booking_creation_status_pending(test_db):
    """Test that a newly created booking is in pending_payment status."""
    res = calendar_service.create_booking(
        db=test_db,
        court_id=1,
        date="2026-08-15",
        time_slot="14:00",
        customer_name="Alice",
        customer_phone="111"
    )
    assert res.success is True
    assert res.status == "pending_payment"
    assert res.payment_status == "pending"
    assert res.payment_url is not None
    
    # Verify in DB
    booking = test_db.query(Booking).filter(Booking.id == res.booking_id).first()
    assert booking.status == "pending_payment"
    assert booking.payment_status == "pending"


def test_payment_confirmation(test_db):
    """Test that confirm_payment changes status to confirmed."""
    res = calendar_service.create_booking(
        db=test_db,
        court_id=1,
        date="2026-08-15",
        time_slot="14:00",
        customer_name="Alice",
        customer_phone="111"
    )
    
    # Confirm payment
    assert res.booking_id is not None
    success = calendar_service.confirm_payment(test_db, res.booking_id)
    assert success is True
    
    # Verify in DB
    booking = test_db.query(Booking).filter(Booking.id == res.booking_id).first()
    assert booking.status == "confirmed"
    assert booking.payment_status == "paid"


def test_signature_verification():
    """Test verification of mock signatures."""
    # Under mock settings, verify_midtrans_signature should accept 'mock-signature'
    is_valid = payment_service.verify_midtrans_signature(
        order_id="booking-1",
        status_code="200",
        gross_amount="50000.00",
        signature_key="mock-signature"
    )
    assert is_valid is True


def test_pending_payment_expiry(test_db):
    """Test that check_court_availability expires pending bookings older than 10 mins."""
    res = calendar_service.create_booking(
        db=test_db,
        court_id=1,
        date="2026-08-15",
        time_slot="14:00",
        customer_name="Alice",
        customer_phone="111"
    )
    
    # Artificially set creation time to 15 minutes ago
    booking = test_db.query(Booking).filter(Booking.id == res.booking_id).first()
    booking.created_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=15)
    test_db.commit()
    
    # Check availability - court should be available again because booking has expired
    avail = calendar_service.check_court_availability(
        db=test_db,
        date="2026-08-15",
        time_slot="14:00",
        court_id=1
    )
    assert avail.court_1_available is True
    
    # Check that booking status was updated to cancelled/expired in DB
    test_db.refresh(booking)
    assert booking.status == "cancelled"
    assert booking.payment_status == "expired"


def test_webhook_receipt_delivery(test_db):
    """Test that the webhook confirms payment and triggers a receipt background task."""
    from fastapi.testclient import TestClient
    from app.main import app
    
    # Create booking
    res = calendar_service.create_booking(
        db=test_db,
        court_id=1,
        date="2026-08-15",
        time_slot="14:00",
        customer_name="Alice",
        customer_phone="tg_123456" # Use Telegram contact
    )
    
    # We mock get_db to return our in-memory test_db session
    from app.models.db_models import get_db
    app.dependency_overrides[get_db] = lambda: test_db
    
    from unittest.mock import patch
    client = TestClient(app)
    
    # We patch the send_payment_receipt helper
    assert res.booking_id is not None
    with patch("app.routers.payment_notification.send_payment_receipt") as mock_send_receipt:
        payload = {
            "order_id": f"booking-{res.booking_id}",
            "transaction_status": "settlement",
            "gross_amount": "50000.00",
            "status_code": "200",
            "signature_key": "mock-signature"
        }
        response = client.post("/api/payments/midtrans-webhook", json=payload)
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        
        # Verify database booking status is confirmed
        booking = test_db.query(Booking).filter(Booking.id == res.booking_id).first()
        assert booking.status == "confirmed"
        assert booking.payment_status == "paid"
        
        # Verify receipt sending was triggered in background tasks
        mock_send_receipt.assert_called_once()
        args, _ = mock_send_receipt.call_args
        assert args[0] == "tg_123456"
        assert "KUITANSI PEMBAYARAN RESMI" in args[1] or "KUITANSI PEMBAYARAN RESMI" in args[1].upper()

    app.dependency_overrides.clear()


def test_multihour_receipt_amount(test_db):
    """Verify multihour booking creates correct total amount and receipt calculates multi-hour fee."""
    res = calendar_service.create_booking(
        db=test_db,
        court_id=1,
        date="2026-07-20",
        time_slot="09:00",
        customer_name="Luthfi",
        customer_phone="+628123",
        duration_hours=2
    )
    assert res.total_amount == 150000
    assert "150,000" in res.message

