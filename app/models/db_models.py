import datetime
from sqlalchemy import Column, Integer, String, DateTime, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from app.config import settings

Base = declarative_base()


class Booking(Base):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True)
    court_id = Column(Integer, nullable=False, index=True)  # 1 or 2
    customer_phone = Column(String, nullable=False, index=True)
    customer_name = Column(String, nullable=False)
    booking_date = Column(String, nullable=False, index=True)  # YYYY-MM-DD
    start_time = Column(String, nullable=False)  # HH:MM
    end_time = Column(String, nullable=False)    # HH:MM
    status = Column(String, default="confirmed")  # "confirmed" or "cancelled"
    google_event_id = Column(String, nullable=True) # ID from Google Calendar API
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))


class ChatHistory(Base):
    __tablename__ = "chat_history"

    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String, nullable=False, index=True)
    role = Column(String, nullable=False)  # 'user', 'assistant', 'system'
    content = Column(String, nullable=False)
    timestamp = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))


# Create engine and session factory
db_url = settings.DATABASE_URL
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}
engine = create_engine(db_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Create all database tables if they do not exist."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """Dependency generator that yields a SQLAlchemy database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
