import logging
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session
from app.models.db_models import get_db, Booking
from app.services import calendar_service, payment_service, telegram_service, whatsapp_service
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/payments", tags=["Payments & Webhooks"])


async def send_payment_receipt(phone_number: str, receipt_text: str):
    """Sends the payment receipt to the customer based on contact channel."""
    try:
        if phone_number.startswith("tg_"):
            logger.info(f"Sending Telegram receipt to chat {phone_number}")
            await telegram_service.send_telegram_message(phone_number, receipt_text)
        elif phone_number == "simulator":
            logger.info(f"Simulator payment receipt:\n{receipt_text}")
        else:
            logger.info(f"Sending WhatsApp receipt to {phone_number}")
            await whatsapp_service.send_whatsapp_message(phone_number, receipt_text)
    except Exception as e:
        logger.error(f"Failed to send receipt to {phone_number}: {e}", exc_info=True)


@router.post("/midtrans-webhook")
def handle_midtrans_notification(
    payload: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
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
        
        # Send receipt/confirmation to customer
        booking = db.query(Booking).filter(Booking.id == booking_id).first()
        if booking:
            try:
                sh = int(str(booking.start_time).split(":")[0])
                eh = int(str(booking.end_time).split(":")[0])
                dur = max(1, eh - sh)
            except Exception:
                dur = 1
            total_amount = calendar_service.calculate_total_booking_price(str(booking.start_time), dur)

            receipt_text = (
                f"🧾 *KUITANSI PEMBAYARAN RESMI* 🧾\n\n"
                f"Reservasi Anda telah dikonfirmasi!\n"
                f"-----------------------------------\n"
                f"ID Booking: #{booking.id}\n"
                f"Nama: {booking.customer_name}\n"
                f"Lapangan: {settings.COURT_1_NAME if booking.court_id == 1 else settings.COURT_2_NAME}\n"
                f"Tanggal: {booking.booking_date}\n"
                f"Jam: {booking.start_time} - {booking.end_time} WIB\n"
                f"Biaya: Rp {total_amount:,}\n"
                f"Status: *LUNAS* (Diterima oleh Midtrans)\n"
                f"📍 Lokasi: {settings.CLUB_LOCATION_URL}\n"
                f"-----------------------------------\n"
                f"Selamat bermain! 🎾🏡"
            )
            background_tasks.add_task(send_payment_receipt, booking.customer_phone, receipt_text)

    elif transaction_status in ["expire", "cancel", "deny"]:
        # Find booking and release slot
        booking = db.query(Booking).filter(Booking.id == booking_id).first()
        if booking:
            booking.status = "cancelled"
            booking.payment_status = "expired" if transaction_status == "expire" else "failed"
            db.commit()
            logger.info(f"Released expired or failed booking #{booking_id}")

    return {"status": "ok", "message": "Payment status processed successfully."}
