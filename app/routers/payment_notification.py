import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.models.db_models import get_db, Booking
from app.services import calendar_service, payment_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/payments", tags=["Payments & Webhooks"])


@router.post("/midtrans-webhook")
def handle_midtrans_notification(payload: dict, db: Session = Depends(get_db)):
    """
    HTTP POST Webhook notification endpoint for Midtrans.
    Receives real-time payment updates and confirms or releases reservations.
    """
    order_id = payload.get("order_id")
    transaction_status = payload.get("transaction_status")
    gross_amount = payload.get("gross_amount")
    signature_key = payload.get("signature_key")
    status_code = payload.get("status_code")

    if not order_id or not transaction_status or not signature_key:
        logger.error("Missing mandatory fields in Midtrans notification payload")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing mandatory payment parameters."
        )

    # Verify signature key
    is_valid = payment_service.verify_midtrans_signature(
        order_id=order_id,
        status_code=str(status_code),
        gross_amount=str(gross_amount),
        signature_key=signature_key
    )

    if not is_valid:
        logger.error(f"Invalid signature received for transaction {order_id}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Signature key verification failed."
        )

    # Extract booking ID from order_id (format: "booking-<id>")
    try:
        parts = order_id.split("-")
        booking_id = int(parts[1])
    except (IndexError, ValueError) as e:
        logger.error(f"Failed to parse booking ID from order_id {order_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid order_id format."
        )

    logger.info(f"Received payment status '{transaction_status}' for Booking #{booking_id}")

    # Process status
    if transaction_status in ["settlement", "capture"]:
        success = calendar_service.confirm_payment(db, booking_id)
        if not success:
            logger.error(f"Failed to confirm payment for Booking #{booking_id}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Booking not found or not pending payment."
            )
    elif transaction_status in ["expire", "cancel", "deny"]:
        # Find booking and release slot
        booking = db.query(Booking).filter(Booking.id == booking_id).first()
        if booking:
            booking.status = "cancelled"
            booking.payment_status = "expired" if transaction_status == "expire" else "failed"
            db.commit()
            logger.info(f"Released expired or failed booking #{booking_id}")

    return {"status": "ok", "message": "Payment status processed successfully."}
