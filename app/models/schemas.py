from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class IncomingChatMessage(BaseModel):
    """Standardized representation of an incoming chat message from WhatsApp or Simulator."""
    sender_phone: str = Field(..., description="Phone number of the sender (e.g. '15550192')")
    sender_name: str = Field(..., description="Display name of the sender")
    message_text: str = Field(..., description="Text content of the incoming message")
    message_id: Optional[str] = None


class CourtAvailabilityQuery(BaseModel):
    date: str = Field(..., description="Date in YYYY-MM-DD format")
    time_slot: str = Field(..., description="Time slot in HH:MM format (e.g., '16:00')")
    court_id: Optional[int] = Field(None, description="Court ID (1 or 2). If None, checks both courts.")


class CourtAvailabilityResponse(BaseModel):
    date: str
    time_slot: str
    court_1_available: bool
    court_2_available: bool
    summary_text: str


class BookingRequest(BaseModel):
    court_id: int = Field(..., description="Court number (1 or 2)")
    date: str = Field(..., description="Date in YYYY-MM-DD format")
    time_slot: str = Field(..., description="Start time in HH:MM format (e.g. '14:00')")
    customer_name: str = Field(..., description="Name of the customer reserving the court")
    customer_phone: str = Field(..., description="Phone number of the customer")


class BookingResponse(BaseModel):
    success: bool
    booking_id: Optional[int] = None
    court_id: int
    court_name: str
    date: str
    start_time: str
    end_time: str
    status: str
    message: str
    payment_url: Optional[str] = None
    payment_status: Optional[str] = None


class CancelBookingRequest(BaseModel):
    booking_id: int
    customer_phone: str


class ScheduleSlot(BaseModel):
    time: str
    court_1_status: str  # "Available" or "Booked"
    court_1_booking_id: Optional[int] = None
    court_1_customer: Optional[str] = None
    court_1_phone: Optional[str] = None
    court_2_status: str  # "Available" or "Booked"
    court_2_booking_id: Optional[int] = None
    court_2_customer: Optional[str] = None
    court_2_phone: Optional[str] = None


class DailyScheduleResponse(BaseModel):
    date: str
    slots: List[ScheduleSlot]
