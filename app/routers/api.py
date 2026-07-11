import datetime
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from app.config import settings
from app.models.db_models import get_db
from app.models.schemas import (
    DailyScheduleResponse,
    BookingRequest,
    BookingResponse,
    CancelBookingRequest,
    RescheduleBookingRequest
)
from app.services import calendar_service

router = APIRouter(prefix="/api", tags=["API & Schedule"])


@router.get("/schedule", response_model=DailyScheduleResponse)
def get_daily_schedule(
    date: str = Query(default_factory=lambda: calendar_service.get_wib_today().strftime("%Y-%m-%d")),
    db: Session = Depends(get_db)
):
    """Returns the hourly availability grid for Tennis Court 1 and Court 2 on a given date."""
    return calendar_service.get_daily_schedule(db, date)


@router.post("/bookings", response_model=BookingResponse)
def create_manual_booking(req: BookingRequest, db: Session = Depends(get_db)):
    """Creates a new tennis court booking directly via REST API."""
    return calendar_service.create_booking(
        db=db,
        court_id=req.court_id,
        date=req.date,
        time_slot=req.time_slot,
        customer_name=req.customer_name,
        customer_phone=req.customer_phone
    )


@router.post("/bookings/cancel")
def cancel_manual_booking(req: CancelBookingRequest, db: Session = Depends(get_db)):
    """Cancels an existing booking by booking ID and customer phone."""
    res = calendar_service.cancel_booking(db, req.booking_id, req.customer_phone)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res


@router.post("/bookings/reschedule", response_model=BookingResponse)
def reschedule_manual_booking(req: RescheduleBookingRequest, db: Session = Depends(get_db)):
    """Reschedules an existing booking without requiring a new payment."""
    res = calendar_service.reschedule_booking(
        db=db,
        booking_id=req.booking_id,
        new_date=req.new_date,
        new_time_slot=req.new_time_slot,
        customer_phone=req.customer_phone,
        new_court_id=req.new_court_id,
        duration_hours=req.duration_hours,
        customer_name=req.customer_name
    )
    if not res.success:
        raise HTTPException(status_code=400, detail=res.message)
    return res



@router.get("/bookings/{phone}")
def get_customer_bookings(phone: str, db: Session = Depends(get_db)):
    """Retrieves all confirmed reservations for a customer's phone number."""
    return calendar_service.get_user_bookings(db, phone)


@router.get("/config")
def get_public_config():
    """Returns frontend display configuration and sync status."""
    g_service = calendar_service.get_google_calendar_service()
    return {
        "court_1_name": settings.COURT_1_NAME,
        "court_2_name": settings.COURT_2_NAME,
        "opening_hour": settings.CLUB_OPENING_HOUR,
        "closing_hour": settings.CLUB_CLOSING_HOUR,
        "hourly_rate_usd": settings.HOURLY_RATE_USD,
        "google_calendar_synced": g_service is not None,
        "llm_model": settings.OPENROUTER_MODEL
    }
