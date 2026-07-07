import pytest
from app.services.telegram_service import parse_telegram_webhook


def test_parse_telegram_webhook_standard_text():
    payload = {
        "update_id": 100001,
        "message": {
            "message_id": 456,
            "from": {
                "id": 99887766,
                "is_bot": False,
                "first_name": "Luthfillah",
                "last_name": "Akhtar"
            },
            "chat": {
                "id": 99887766,
                "type": "private"
            },
            "date": 1600000000,
            "text": "Halo bot, apakah lapangan 1 kosong besok jam 16:00?"
        }
    }
    
    msgs = parse_telegram_webhook(payload)
    assert len(msgs) == 1
    assert msgs[0].sender_phone == "tg_99887766"
    assert msgs[0].sender_name == "Luthfillah Akhtar"
    assert msgs[0].message_text == "Halo bot, apakah lapangan 1 kosong besok jam 16:00?"
    assert msgs[0].message_id == "456"


def test_parse_telegram_webhook_empty_or_non_text():
    payload = {
        "update_id": 100002,
        "message": {
            "message_id": 457,
            "from": {"id": 12345, "first_name": "Test"},
            "chat": {"id": 12345},
            "photo": [{"file_id": "xxx"}]
        }
    }
    msgs = parse_telegram_webhook(payload)
    assert len(msgs) == 0
