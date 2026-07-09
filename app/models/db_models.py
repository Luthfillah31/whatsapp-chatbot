import datetime
from sqlalchemy import Column, Integer, String, DateTime, create_engine, Index
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
    status = Column(String, default="pending_payment")  # "pending_payment", "confirmed", "cancelled"
    google_event_id = Column(String, nullable=True) # ID from Google Calendar API
    payment_status = Column(String, default="pending")  # "pending", "paid", "expired", "failed"
    payment_url = Column(String, nullable=True)
    payment_token = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))

    __table_args__ = (
        Index(
            'idx_unique_active_booking',
            'court_id', 'booking_date', 'start_time',
            unique=True,
            sqlite_where=(status.in_(["confirmed", "pending_payment"])),
            postgresql_where=(status.in_(["confirmed", "pending_payment"]))
        ),
    )


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
    """Create all database tables if they do not exist and apply migrations."""
    Base.metadata.create_all(bind=engine)
    
    # Run auto-migrations to add payment columns if they do not exist
    if db_url.startswith("sqlite"):
        import sqlite3
        db_path = db_url.replace("sqlite:///", "")
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(bookings)")
            columns = [row[1] for row in cursor.fetchall()]
            if "payment_status" not in columns:
                cursor.execute("ALTER TABLE bookings ADD COLUMN payment_status VARCHAR DEFAULT 'pending'")
            if "payment_url" not in columns:
                cursor.execute("ALTER TABLE bookings ADD COLUMN payment_url VARCHAR")
            if "payment_token" not in columns:
                cursor.execute("ALTER TABLE bookings ADD COLUMN payment_token VARCHAR")
            
            # Create partial unique index to prevent duplicate concurrent active bookings
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_active_booking ON bookings (court_id, booking_date, start_time) WHERE status IN ('confirmed', 'pending_payment')")
            
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"SQLite Auto-Migration failed: {e}")
    elif db_url.startswith("postgresql") or db_url.startswith("postgres"):
        try:
            from sqlalchemy import text
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE bookings ADD COLUMN IF NOT EXISTS payment_status VARCHAR DEFAULT 'pending'"))
                conn.execute(text("ALTER TABLE bookings ADD COLUMN IF NOT EXISTS payment_url VARCHAR"))
                conn.execute(text("ALTER TABLE bookings ADD COLUMN IF NOT EXISTS payment_token VARCHAR"))
                conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_active_booking ON bookings (court_id, booking_date, start_time) WHERE status IN ('confirmed', 'pending_payment')"))
                conn.commit()
        except Exception as e:
            print(f"Postgres Auto-Migration failed: {e}")


def get_db():
    """Dependency generator that yields a SQLAlchemy database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
