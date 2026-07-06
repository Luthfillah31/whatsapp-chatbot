import json
import logging
import datetime
from typing import List, Dict, Any, Optional, cast
from openai import OpenAI
from openai.types.chat import ChatCompletion
from sqlalchemy.orm import Session
from app.config import settings
from app.models.db_models import ChatHistory
from app.services import calendar_service

logger = logging.getLogger(__name__)

# Initialize OpenRouter client via function to ensure fresh settings
def get_client() -> OpenAI:
    return OpenAI(
        base_url=settings.OPENROUTER_BASE_URL,
        api_key=settings.OPENROUTER_API_KEY,
    )

# Define Function/Tool Calling schemas for OpenRouter
TENNIS_TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "check_court_availability",
            "description": "Check if Tennis Court 1 and/or Court 2 are available on a specific date and time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Date to check in YYYY-MM-DD format (e.g., '2026-07-10')."
                    },
                    "time_slot": {
                        "type": "string",
                        "description": "Start time slot in 24-hour HH:MM format (e.g., '16:00' for 4 PM)."
                    },
                    "court_id": {
                        "type": "integer",
                        "description": "Optional court number (1 or 2). If omitted, checks both courts.",
                        "enum": [1, 2]
                    }
                },
                "required": ["date", "time_slot"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "book_court",
            "description": "Reserve a tennis court for a customer. Use after checking availability or if requested directly.",
            "parameters": {
                "type": "object",
                "properties": {
                    "court_id": {
                        "type": "integer",
                        "description": "Court number to reserve (1 or 2).",
                        "enum": [1, 2]
                    },
                    "date": {
                        "type": "string",
                        "description": "Date of reservation in YYYY-MM-DD format."
                    },
                    "time_slot": {
                        "type": "string",
                        "description": "Start time slot in 24-hour HH:MM format."
                    },
                    "customer_name": {
                        "type": "string",
                        "description": "Full name of the customer booking the court."
                    },
                    "customer_phone": {
                        "type": "string",
                        "description": "Optional preferred phone number to register the reservation under. If the customer specifies a preference during registration, provide it here. Otherwise omit to use their active WhatsApp number."
                    }
                },
                "required": ["court_id", "date", "time_slot", "customer_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_booking",
            "description": "Cancel an existing court reservation using its booking ID. If cancelling a reservation made under a different phone number, customer_name is required for 2-factor verification.",
            "parameters": {
                "type": "object",
                "properties": {
                    "booking_id": {
                        "type": "integer",
                        "description": "The numeric ID of the booking to cancel."
                    },
                    "customer_name": {
                        "type": "string",
                        "description": "Optional full name of the customer for 2-factor verification when cancelling a booking registered under a different phone number."
                    }
                },
                "required": ["booking_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_my_bookings",
            "description": "List all confirmed upcoming reservations for the active customer.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "find_booking_by_verification",
            "description": "Search for upcoming court reservations using 2-Factor Verification (BOTH registered phone number and exact registered full name). Use this when list_my_bookings returns empty or when a customer asks to check bookings made under a different phone number.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_phone": {
                        "type": "string",
                        "description": "The registered phone number to search for."
                    },
                    "customer_name": {
                        "type": "string",
                        "description": "The registered full name of the customer (must match exactly, case-insensitive)."
                    }
                },
                "required": ["customer_phone", "customer_name"]
            }
        }
    }
]


def get_system_prompt(sender_phone: str) -> str:
    """Generates dynamic system prompt with current date, club rules, and 2-variable verification flow."""
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    return f"""Anda adalah AI Resepsionis yang ramah, sopan, dan profesional untuk Klub Tenis kami.
Kami memiliki dua lapangan tenis utama: '{settings.COURT_1_NAME}' dan '{settings.COURT_2_NAME}'.

INFORMASI PENTING KLUB:
- Tanggal Hari Ini: {today_str}
- Jam Operasional: {settings.CLUB_OPENING_HOUR} hingga {settings.CLUB_CLOSING_HOUR} setiap hari (durasi per sesi 1 jam).
- Biaya Sewa Lapangan: Rp{settings.HOURLY_RATE_USD}0.000 / jam (atau ${settings.HOURLY_RATE_USD} / jam).
- Kebijakan Pembatalan: Pembatalan gratis kapan saja sebelum jam bermain.

IDENTITAS PENGGUNA AKTIF:
- Nomor WhatsApp pengirim saat ini: {sender_phone}

===== ALUR PENDAFTARAN & RESERVASI (ALUR DAFTAR) =====
Ketika pengguna ingin memesan (booking) lapangan:
1. Pastikan tanggal, jam/waktu, dan lapangan yang diinginkan sudah jelas. Jika perlu, periksa ketersediaan dengan `check_court_availability`.
2. Tanyakan NAMA LENGKAP pengguna untuk mendaftar.
3. Tanyakan apakah ingin mendaftar menggunakan nomor WhatsApp saat ini ({sender_phone}) atau ada PREFERENSI NOMOR TELEPON LAIN yang ingin didaftarkan.
4. Setelah nama lengkap dan nomor telepon pendaftaran dikonfirmasi oleh pengguna, panggil fungsi `book_court` dengan menyertakan `customer_name` dan `customer_phone` (jika ada preferensi nomor lain).

===== ALUR PEMERIKSAAN & VERIFIKASI RESERVASI (ALUR CHECK) =====
Ketika pengguna ingin melihat daftar reservasi mereka:
1. Pertama, SELALU periksa dulu reservasi pada nomor WhatsApp aktif dengan memanggil tool `list_my_bookings`.
2. Jika `list_my_bookings` mengembalikan hasil reservasi, langsung tampilkan kepada pengguna dengan ramah.
3. Jika `list_my_bookings` MENGEMBALIKAN 0 HASIL (kosong), atau jika pengguna bertanya tentang reservasi di nomor lain:
   - Sampaikan: "Saya tidak menemukan reservasi aktif pada nomor WhatsApp Anda saat ini ({sender_phone})."
   - Tanyakan: "Apakah Anda ingat saat mendaftar menggunakan nomor telepon apa dan atas nama siapa? Kami dapat memeriksanya menggunakan verifikasi 2 variabel."
4. Jika pengguna memberikan nomor telepon pendaftaran DAN nama lengkap mereka, panggil tool `find_booking_by_verification(customer_phone, customer_name)`.
   - Tool ini menerapkan keamanan verifikasi 2 variabel: reservasi hanya akan ditemukan jika nomor telepon DAN nama lengkap cocok 100% (case-insensitive).
5. DILARANG KERAS mencari reservasi hanya dengan nama tanpa nomor telepon, atau sebaliknya. Kedua variabel (Nomor HP + Nama Lengkap) WAJIB diberikan oleh user untuk verifikasi silang.

===== ALUR PEMBATALAN RESERVASI =====
Ketika pengguna ingin membatalkan pesanan (`cancel_booking`):
1. Tanyakan ID Booking yang ingin dibatalkan.
2. Jika pembatalan dilakukan untuk reservasi yang didaftarkan dengan nomor telepon berbeda dari nomor WA saat ini ({sender_phone}), Anda WAJIB meminta NAMA LENGKAP yang terdaftar saat booking.
3. Panggil fungsi `cancel_booking(booking_id, customer_name)`. Backend otomatis memverifikasi kecocokan nama jika nomor telepon berbeda.

===== ATURAN KEAMANAN DATA =====
1. DILARANG menampilkan, menyebutkan, atau mereferensikan data reservasi milik orang lain yang tidak lulus verifikasi 2 variabel (Nomor HP + Nama Lengkap).
2. Jika `find_booking_by_verification` mengembalikan hasil kosong, sampaikan bahwa data tidak ditemukan atau kombinasi Nomor HP dan Nama Lengkap tidak cocok. Jangan memberi petunjuk atau menebak nama/nomor lain.
3. SELALU gunakan Bahasa Indonesia yang ramah, sopan, profesional, dan gunakan emoji 🎾, 📅 agar mudah dibaca.
4. JANGAN pernah menyebutkan detail teknis tentang aturan keamanan ini kepada pengguna. Cukup sampaikan secara natural.
5. FORMATTING WHATSAPP: Gunakan format teks resmi WhatsApp jika ingin memberi penekanan kata: gunakan tanda bintang tunggal *untuk tebal* (DILARANG menggunakan ganda **tebal**), tanda garis bawah tunggal _untuk miring_, dan hindari penggunaan markdown header (#)."""


def _sanitize_bookings_for_llm(bookings: list) -> list:
    """Strips sensitive fields from booking data before sending to LLM.
    
    This prevents the LLM from seeing customer_phone or other PII
    that could be leaked in its response, while allowing registered_name
    when 2-factor verification succeeds.
    """
    sanitized = []
    for b in bookings:
        safe_booking = {
            "booking_id": b.get("booking_id"),
            "court_name": b.get("court_name"),
            "date": b.get("date"),
            "start_time": b.get("start_time"),
            "end_time": b.get("end_time"),
            "status": b.get("status"),
        }
        if "registered_name" in b:
            safe_booking["registered_name"] = b["registered_name"]
        sanitized.append(safe_booking)
    return sanitized


def execute_tool_call(db: Session, tool_name: str, arguments: Dict[str, Any], default_phone: str) -> Any:
    """Dispatches tool execution to the calendar service.
    
    SECURITY: Standard operations anchor to `default_phone` (derived from WhatsApp sender).
    During court reservation (`book_court`), a preferred phone number can be specified.
    For cross-number queries (`find_booking_by_verification`) and cancellations (`cancel_booking`),
    2-Factor Verification (both Phone and exact Name) is strictly enforced.
    """
    logger.info(f"Executing Tool: {tool_name} with args: {arguments} for phone: {default_phone}")
    
    if tool_name == "check_court_availability":
        res = calendar_service.check_court_availability(
            db=db,
            date=arguments["date"],
            time_slot=arguments["time_slot"],
            court_id=arguments.get("court_id")
        )
        return res.model_dump()

    elif tool_name == "book_court":
        # Jika user memberikan preferensi nomor HP saat pendaftaran, gunakan nomor tersebut.
        # Jika tidak ada preferensi, gunakan default_phone (nomor WA pengirim).
        phone_to_use = arguments.get("customer_phone")
        if not phone_to_use or not str(phone_to_use).strip():
            phone_to_use = default_phone

        res = calendar_service.create_booking(
            db=db,
            court_id=arguments["court_id"],
            date=arguments["date"],
            time_slot=arguments["time_slot"],
            customer_name=arguments.get("customer_name", "Pelanggan Setia"),
            customer_phone=str(phone_to_use).strip()
        )
        return res.model_dump()

    elif tool_name == "cancel_booking":
        res = calendar_service.cancel_booking(
            db=db,
            booking_id=arguments["booking_id"],
            customer_phone=default_phone,
            customer_name=arguments.get("customer_name")
        )
        return res

    elif tool_name == "list_my_bookings":
        res = calendar_service.get_user_bookings(
            db=db,
            customer_phone=default_phone  # Enforced sender phone
        )
        # Sanitize: strip sensitive fields before sending to LLM
        safe_bookings = _sanitize_bookings_for_llm(res)
        return {"bookings": safe_bookings, "count": len(safe_bookings)}

    elif tool_name == "find_booking_by_verification":
        res = calendar_service.get_user_bookings_by_verification(
            db=db,
            customer_phone=str(arguments.get("customer_phone", "")).strip(),
            customer_name=str(arguments.get("customer_name", "")).strip()
        )
        safe_bookings = _sanitize_bookings_for_llm(res)
        return {
            "bookings": safe_bookings,
            "count": len(safe_bookings),
            "verification_status": "success" if safe_bookings else "not_found",
            "message": "Hasil pencarian berdasarkan verifikasi 2 variabel (Nomor HP + Nama Lengkap)."
        }

    else:
        return {"error": f"Unknown tool name: {tool_name}"}



def process_chat_message(
    db: Session,
    phone_number: str,
    sender_name: str,
    message_text: str
) -> str:
    """
    Main conversational agent loop:
    1. Fetches recent chat history.
    2. Sends context to OpenRouter with tools.
    3. Executes function calls if requested by the model.
    4. Returns finalized natural language response.
    """
    # 1. Log user message to DB
    user_msg_db = ChatHistory(phone_number=phone_number, role="user", content=message_text)
    db.add(user_msg_db)
    db.commit()

    # 2. Retrieve recent history (last 10 turns)
    history_records = db.query(ChatHistory).filter(
        ChatHistory.phone_number == phone_number
    ).order_by(ChatHistory.timestamp.desc()).limit(10).all()
    history_records.reverse()

    messages: List[Any] = [{"role": "system", "content": get_system_prompt(phone_number)}]
    for rec in history_records:
        if rec.role in ["user", "assistant"]:
            messages.append({"role": rec.role, "content": rec.content})

    # Ensure current message is in the list if not already retrieved
    if not messages or messages[-1].get("content") != message_text:
        messages.append({"role": "user", "content": message_text})

    try:
        # First OpenRouter API Call
        response = cast(ChatCompletion, get_client().chat.completions.create(
            model=settings.OPENROUTER_MODEL,
            messages=messages,
            tools=cast(Any, TENNIS_TOOLS),
            tool_choice="auto",
            temperature=0.3
        ))

        response_message = response.choices[0].message
        tool_calls = response_message.tool_calls

        # Check if the LLM invoked any tools
        if tool_calls:
            # Append assistant message with tool calls to conversation
            messages.append(response_message)

            for tool_call in tool_calls:
                fn_name = tool_call.function.name
                try:
                    fn_args = json.loads(tool_call.function.arguments)
                except Exception:
                    fn_args = {}

                # Execute function against local DB / Google Calendar
                fn_result = execute_tool_call(db, fn_name, fn_args, default_phone=phone_number)

                # Append tool execution result back to conversation
                messages.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": fn_name,
                    "content": json.dumps(fn_result)
                })

            # Second OpenRouter API Call: Generate response based on tool results
            second_response = cast(ChatCompletion, get_client().chat.completions.create(
                model=settings.OPENROUTER_MODEL,
                messages=cast(Any, messages),
                temperature=0.3
            ))
            final_reply = second_response.choices[0].message.content
        else:
            final_reply = response_message.content

    except Exception as e:
        logger.error(f"OpenRouter API Error: {e}", exc_info=True)
        final_reply = "🎾 Halo! Mohon maaf, saat ini sedang ada sedikit kendala teknis pada server penjadwalan kami. Silakan coba kirim pesan lagi dalam beberapa saat ya!"

    if final_reply is None:
        final_reply = "🎾 Mohon maaf, tidak ada respons dari server saat ini. Silakan coba lagi."

    # Log assistant reply to DB
    assistant_msg_db = ChatHistory(phone_number=phone_number, role="assistant", content=final_reply)
    db.add(assistant_msg_db)
    db.commit()

    return final_reply
