import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.db_models import Base
from app.services.llm_service import TENNIS_TOOLS, execute_tool_call


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


def test_tools_schema_validity():
    """Verify that all tools defined for OpenRouter follow the required schema format."""
    assert isinstance(TENNIS_TOOLS, list)
    assert len(TENNIS_TOOLS) == 5

    tool_names = [str(t.get("function", {}).get("name")) for t in TENNIS_TOOLS if isinstance(t, dict) and isinstance(t.get("function"), dict)]
    assert "check_court_availability" in tool_names
    assert "book_court" in tool_names
    assert "cancel_booking" in tool_names
    assert "list_my_bookings" in tool_names
    assert "find_booking_by_verification" in tool_names

    for tool in TENNIS_TOOLS:
        assert isinstance(tool, dict)
        assert tool.get("type") == "function"
        func = tool.get("function")
        assert isinstance(func, dict)
        assert "description" in func
        assert "parameters" in func
        params = func.get("parameters")
        assert isinstance(params, dict)
        assert params.get("type") == "object"


def test_execute_tool_call_availability(test_db):
    """Test executing check_court_availability tool."""
    res = execute_tool_call(
        db=test_db,
        tool_name="check_court_availability",
        arguments={"date": "2026-07-10", "time_slot": "16:00"},
        default_phone="+15550192"
    )
    assert res["date"] == "2026-07-10"
    assert res["court_1_available"] is True
    assert res["court_2_available"] is True
    assert "available" in res["summary_text"].toLowerCase() if hasattr(res["summary_text"], "toLowerCase") else "available" in res["summary_text"].lower()


def test_execute_tool_call_booking_and_listing(test_db):
    """Test executing book_court tool and then listing bookings."""
    # 1. Book Court 1
    book_res = execute_tool_call(
        db=test_db,
        tool_name="book_court",
        arguments={
            "court_id": 1,
            "date": "2026-07-10",
            "time_slot": "16:00",
            "customer_name": "John Doe",
            "customer_phone": "+15550000"
        },
        default_phone="+15550000"
    )
    assert book_res["success"] is True
    assert book_res["booking_id"] == 1
    assert book_res["court_id"] == 1

    # 2. Check availability again (Court 1 should now be booked, Court 2 available)
    avail_res = execute_tool_call(
        db=test_db,
        tool_name="check_court_availability",
        arguments={"date": "2026-07-10", "time_slot": "16:00"},
        default_phone="+15550000"
    )
    assert avail_res["court_1_available"] is False
    assert avail_res["court_2_available"] is True

    # 3. List bookings for +15550000
    list_res = execute_tool_call(
        db=test_db,
        tool_name="list_my_bookings",
        arguments={"customer_phone": "+15550000"},
        default_phone="+15550000"
    )
    assert list_res["count"] == 1
    assert list_res["bookings"][0]["booking_id"] == 1


def test_execute_tool_call_2factor_verification(test_db):
    """Test executing book_court and find_booking_by_verification tool."""
    # 1. Book Court 2 under default_phone +15550000
    book_res = execute_tool_call(
        db=test_db,
        tool_name="book_court",
        arguments={
            "court_id": 2,
            "date": "2026-11-11",
            "time_slot": "10:00",
            "customer_name": "Sarah Connor"
        },
        default_phone="+15550000"
    )
    assert book_res["success"] is True

    # 2. List bookings for default_phone (+15550000) -> should be 1
    list_res = execute_tool_call(
        db=test_db,
        tool_name="list_my_bookings",
        arguments={},
        default_phone="+15550000"
    )
    assert list_res["count"] == 1

    # 3. Find booking by verification (matching phone + exact name)
    verify_res = execute_tool_call(
        db=test_db,
        tool_name="find_booking_by_verification",
        arguments={
            "customer_phone": "+15550000",
            "customer_name": "sarah connor"
        },
        default_phone="+15550000"
    )
    assert verify_res["verification_status"] == "success"
    assert verify_res["count"] == 1
    assert verify_res["bookings"][0]["registered_name"] == "Sarah Connor"

    # 4. Find booking by verification with wrong name -> not_found
    verify_res_fail = execute_tool_call(
        db=test_db,
        tool_name="find_booking_by_verification",
        arguments={
            "customer_phone": "+15550000",
            "customer_name": "John Connor"
        },
        default_phone="+15550000"
    )
    assert verify_res_fail["verification_status"] == "not_found"
    assert verify_res_fail["count"] == 0
