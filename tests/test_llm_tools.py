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
    assert len(TENNIS_TOOLS) == 8

    tool_names = [str(t.get("function", {}).get("name")) for t in TENNIS_TOOLS if isinstance(t, dict) and isinstance(t.get("function"), dict)]
    assert "check_court_availability" in tool_names
    assert "search_available_slots" in tool_names
    assert "check_calendar_date" in tool_names
    assert "book_court" in tool_names
    assert "cancel_booking" in tool_names
    assert "reschedule_booking" in tool_names
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
        arguments={"date": "2026-10-10", "time_slot": "16:00"},
        default_phone="+15550192"
    )
    assert res["date"] == "2026-10-10"
    assert res["court_1_available"] is True
    assert res["court_2_available"] is True
    assert ("available" in res["summary_text"].lower() or "tersedia" in res["summary_text"].lower())


def test_execute_tool_call_booking_and_listing(test_db):
    """Test executing book_court tool and then listing bookings."""
    # 1. Book Court 1
    book_res = execute_tool_call(
        db=test_db,
        tool_name="book_court",
        arguments={
            "court_id": 1,
            "date": "2026-10-10",
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
        arguments={"date": "2026-10-10", "time_slot": "16:00"},
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


def test_enforce_neutral_tone():
    """Test enforce_neutral_tone strips non-neutral/religious expressions."""
    from app.services.llm_service import enforce_neutral_tone
    sample1 = "Alhamdulillah, untuk jam 22:00 malam ini, Lapangan 1 masih kosong."
    assert enforce_neutral_tone(sample1) == "Untuk jam 22:00 malam ini, Lapangan 1 masih kosong."

    sample2 = "Insya Allah jadwal Bapak sudah terdaftar."
    assert enforce_neutral_tone(sample2) == "Jadwal Bapak sudah terdaftar."


def test_dsml_parsing_and_stripping():
    """Verify that models emitting text-format XML/DSML tool calls are parsed and stripped properly."""
    from app.services.llm_service import extract_dsml_tool_calls, strip_dsml_tags
    raw_text = (
        "Saya cek dulu ketersediaan Lapangan 1 jam 20:00.\n\n"
        "<｜DSML｜tool_calls>\n"
        "<｜DSML｜invoke name=\"check_court_availability\">\n"
        "<｜DSML｜parameter name=\"court_id\" string=\"true\">1</｜DSML｜parameter>\n"
        "<｜DSML｜parameter name=\"date\" string=\"true\">2026-07-10</｜DSML｜parameter>\n"
        "<｜DSML｜parameter name=\"time_slot\" string=\"true\">20:00</｜DSML｜parameter>\n"
        "</｜DSML｜invoke>\n"
        "</｜DSML｜tool_calls>"
    )
    calls = extract_dsml_tool_calls(raw_text)
    assert len(calls) == 1
    fn_name, fn_args = calls[0]
    assert fn_name == "check_court_availability"
    assert fn_args == {"court_id": 1, "date": "2026-07-10", "time_slot": "20:00"}

    stripped = strip_dsml_tags(raw_text)
    assert "<｜DSML｜" not in stripped
    assert "check_court_availability" not in stripped
    assert "Saya cek dulu ketersediaan Lapangan 1 jam 20:00." in stripped


def test_alias_tool_parameter_names(test_db):
    """Verify execute_tool_call accepts alias parameters like start_time or time for time_slot."""
    from app.services.llm_service import execute_tool_call
    res = execute_tool_call(
        db=test_db,
        tool_name="book_court",
        arguments={
            "customer_name": "Luthfi",
            "court_id": "1",
            "date": "2026-07-15",
            "start_time": "08:00",
            "end_time": "09:00"
        },
        default_phone="+628123456"
    )
    assert res["court_id"] == 1
    assert res["start_time"] == "08:00"
    assert res["status"] == "pending_payment"


def test_extract_slot_default_empty():
    """Verify missing time slot returns empty string without defaulting to 08:00."""
    from app.services.llm_service import _extract_slot
    assert _extract_slot({}) == ""
    assert _extract_slot({"time_slot": "10:00"}) == "10:00"


def test_reschedule_booking_tool(test_db):
    """Verify reschedule_booking moves booking to new slot/court without extra payment."""
    from app.services.llm_service import execute_tool_call
    # 1. Create initial booking
    book_res = execute_tool_call(
        db=test_db,
        tool_name="book_court",
        arguments={
            "customer_name": "Luthfi",
            "court_id": 1,
            "date": "2026-07-20",
            "time_slot": "18:00",
            "duration_hours": 2
        },
        default_phone="+628123456"
    )
    assert book_res["success"] is True
    booking_id = book_res["booking_id"]

    # 2. Reschedule to court 2 at 19:00 - 21:00
    resched_res = execute_tool_call(
        db=test_db,
        tool_name="reschedule_booking",
        arguments={
            "booking_id": booking_id,
            "new_date": "2026-07-20",
            "new_time_slot": "19:00",
            "new_court_id": 2
        },
        default_phone="+628123456"
    )
    assert resched_res["success"] is True
    assert resched_res["booking_id"] == booking_id
    assert resched_res["court_id"] == 2
    assert resched_res["start_time"] == "19:00"
    assert resched_res["end_time"] == "21:00"
    assert resched_res["status"] == "confirmed"
    assert resched_res["payment_status"] == "paid"
    assert resched_res["payment_url"] is None
    assert resched_res["total_amount"] == 0


def test_reschedule_booking_partial_args(test_db):
    """Verify reschedule_booking works with only booking_id and new_court_id (e.g. 'Id 40 ke tennis court 1')."""
    from app.services.llm_service import execute_tool_call
    book_res = execute_tool_call(
        db=test_db,
        tool_name="book_court",
        arguments={
            "customer_name": "Luthfi",
            "court_id": 2,
            "date": "2026-07-28",
            "time_slot": "19:00",
            "duration_hours": 2
        },
        default_phone="+628123456"
    )
    assert book_res["success"] is True
    booking_id = book_res["booking_id"]

    resched_res = execute_tool_call(
        db=test_db,
        tool_name="reschedule_booking",
        arguments={
            "booking_id": booking_id,
            "new_court_id": 1
        },
        default_phone="+628123456"
    )
    assert resched_res["success"] is True
    assert resched_res["booking_id"] == booking_id
    assert resched_res["court_id"] == 1
    assert resched_res["date"] == "2026-07-28"
    assert resched_res["start_time"] == "19:00"
    assert resched_res["end_time"] == "21:00"
    assert resched_res["status"] == "confirmed"
    assert resched_res["payment_status"] == "paid"
    assert resched_res["payment_url"] is None
    assert resched_res["total_amount"] == 0


def test_search_available_slots(test_db):
    res = execute_tool_call(
        db=test_db,
        tool_name="search_available_slots",
        arguments={
            "start_date": "2026-07-20",
            "end_date": "2026-07-22",
            "min_hour": 17,
            "max_hour": 21
        },
        default_phone="+628123456"
    )
    assert res["status"] == "success"
    assert len(res["days"]) == 3
    assert "Daftar Jadwal Kosong" in res["summary"]
    assert "17:00" in res["days"][0]["lapangan_A_free_slots"]




