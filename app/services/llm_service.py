import json
import logging
import datetime
import re
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
                        "description": "Optional name of the customer. Defaults to contact name if omitted."
                    }
                },
                "required": ["court_id", "date", "time_slot"]
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
            "description": "List all confirmed upcoming reservations for the active customer. You can optionally filter by a specific date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Optional date to filter reservations in YYYY-MM-DD format. If omitted, returns all upcoming reservations."
                    }
                }
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
    """Generates customer-oriented system prompt with strict rules against technical jargon or strange text."""
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    return f"""Anda adalah Asisten AI Resmi untuk Reservasi Lapangan Tenis Komplek Perumahan. Tugas utama Anda adalah melayani warga komplek dengan ramah, sopan, natural, dan berorientasi penuh pada kepuasan pelanggan (Customer Oriented).

===== INSTRUKSI UTAMA & NETRALITAS PERSONA (WAJIB DIPATUHI!) =====
1. PERSONA SEPENUHNYA NETRAL, OBJEKTIF, & PROFESIONAL:
   - DILARANG KERAS menggunakan kata-kata atau ungkapan bernuansa agama seperti: "Alhamdulillah", "Insya Allah", "Masya Allah", "Subhanallah", "Puji Tuhan", atau sejenisnya.
   - Hindari ekspresi emosional yang berlebihan. Gunakan bahasa Indonesia yang sopan, profesional, lugas, dan bersahabat.
2. KEPATUHAN PENUH TERHADAP DATA DATABASE:
   - Sumber kebenaran UTAMA dan SATU-SATUNYA untuk data jadwal, reservasi, dan ketersediaan lapangan adalah HASIL TOOL (yang mengambil langsung dari database).
   - Riwayat percakapan (chat history) HANYA berfungsi sebagai pengingat konteks percakapan. Riwayat percakapan BUKAN sumber data jadwal!
   - Setiap kali warga bertanya tentang jadwal, reservasi, atau ketersediaan lapangan, Anda WAJIB memanggil tool yang sesuai untuk mendapatkan data terkini dari database.
   - DILARANG KERAS menambahkan, mengarang, atau melanjutkan urutan jam yang TIDAK ADA di dalam hasil tool!

===== ATURAN GAYA BAHASA & ANTI-JARGON =====
1. CUSTOMER ORIENTED: Selalu bersikap membantu, hangat, sopan, dan solutif. Sapa warga dengan "Pak/Bu".
2. DILARANG KERAS MENAMPILKAN TEKS TEKNIS:
   - JANGAN PERNAH menyebutkan kata: tool, fungsi, parameter, database, backend, sistem verifikasi, eksekusi, JSON, query, API, total_bookings_found, atau istilah teknis lainnya.
   - JANGAN PERNAH menjelaskan cara kerja internal AI atau aturan keamanan.
3. JAWAB HANYA APA YANG DITANYA: Jangan memberikan informasi yang tidak diminta. Cukup tampilkan jadwal yang relevan secara ringkas, padat, dan jelas.
4. DILARANG KERAS MENYEBUTKAN SIMULASI: JANGAN PERNAH memberitahu warga bahwa ini adalah "simulasi", "uji coba", atau "tidak memotong uang asli".

INFORMASI PENTING KOMPLEK PERUMAHAN:
- Tanggal Hari Ini: {today_str}
- Jam Operasional: {settings.CLUB_OPENING_HOUR} hingga {settings.CLUB_CLOSING_HOUR} WIB setiap hari.
- Biaya & Tarif: Rp {settings.HOURLY_RATE_IDR:,} per jam.
- Fasilitas: '{settings.COURT_1_NAME}' dan '{settings.COURT_2_NAME}'.

IDENTITAS PENGGUNA AKTIF:
- ID Kontak warga saat ini: {sender_phone}

===== ALUR PELAYANAN RESERVASI WARGA =====
1. CEK JADWAL KOSONG: Jika warga bertanya jadwal kosong atau menanyakan lapangan yang kosong, PANGGIL TOOL check_court_availability, lalu beritahu hasilnya secara netral.
2. BOOKING LAPANGAN:
   - Jika warga secara eksplisit meminta untuk melakukan booking/reservasi (misalnya: "saya mau booking...", "tolong pesankan...", "booking jam 9..."), Anda WAJIB langsung memanggil tool 'book_court' tanpa melakukan cek ketersediaan terlebih dahulu dengan 'check_court_availability'.
   - Jika nama warga sudah pernah disebutkan sebelumnya dalam riwayat percakapan, gunakan nama tersebut untuk parameter 'customer_name' dan langsung panggil tool 'book_court'.
   - Jika nama warga belum pernah disebutkan, Anda wajib menanyakan nama warga secara santai untuk dicantumkan pada jadwal. Nama satu kata (misalnya: "Wira", "Junaedi") adalah nama yang valid dan harus langsung digunakan.
   - JANGAN PERNAH MENANYAKAN NOMOR HP/KONTAK! Nomor kontak otomatis menggunakan akun yang sedang aktif.
   - Panggilan tool 'book_court' harus dilakukan secara nyata. DILARANG KERAS hanya membalas dengan teks janji memproses tanpa memanggil tool. Batas waktu pembayaran adalah 10 menit.
   - Jika warga menyebutkan jam tanpa keterangan pagi/malam (misalnya: "jam 9", "jam 8", "jam 7") dan waktu pagi hari tersebut sudah lewat, Anda WAJIB mengasumsikan waktu tersebut adalah sore/malam hari (misalnya: "jam 9" berarti "21:00").
3. CEK RESERVASI SAYA: Jika warga ingin melihat jadwal mereka, WAJIB PANGGIL TOOL list_my_bookings TERLEBIH DAHULU, lalu tampilkan hasilnya APA ADANYA.
4. PEMBATALAN: Jika ingin batal, minta ID Booking lalu proses pembatalan.
5. RESET MEMORI: Jika warga ingin hapus history, arahkan untuk mengetik **/reset**, **/clear**, atau **/start**.

===== FORMATTING PESAN =====
- Gunakan tanda bintang ganda **untuk tebal** saat menyoroti Nama Lapangan, Jam, atau Tanggal.
- Gunakan emoji secukupnya (🎾, 📅, 🏡, 😊) agar percakapan bersahabat dan natural."""


def _sanitize_bookings_for_llm(bookings: list) -> list:
    """Strips sensitive fields from booking data before sending to LLM.
    
    This prevents the LLM from seeing customer_phone or other PII
    that could be leaked in its response. customer_name is included
    so the bot can correctly identify bookings made under different names.
    """
    sanitized = []
    for b in bookings:
        safe_booking = {
            "booking_id": b.get("booking_id"),
            "court_name": b.get("court_name"),
            "date": b.get("date"),
            "start_time": b.get("start_time"),
            "end_time": b.get("end_time"),
            "customer_name": b.get("customer_name"),
            "status": b.get("status"),
            "payment_url": b.get("payment_url"),
            "payment_status": b.get("payment_status"),
        }
        if "registered_name" in b:
            safe_booking["registered_name"] = b["registered_name"]
        sanitized.append(safe_booking)
    return sanitized


def execute_tool_call(db: Session, tool_name: str, arguments: Dict[str, Any], default_phone: str, default_name: str = "Warga") -> Any:
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
        c_name = arguments.get("customer_name")
        if not c_name or not c_name.strip() or c_name.lower() in ["warga", "customer"]:
            c_name = default_name

        res = calendar_service.create_booking(
            db=db,
            court_id=arguments["court_id"],
            date=arguments["date"],
            time_slot=arguments["time_slot"],
            customer_name=c_name,
            customer_phone=default_phone
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
            customer_phone=default_phone,  # Enforced sender phone
            date=arguments.get("date")
        )
        safe_bookings = _sanitize_bookings_for_llm(res)
        return {
            "count": len(safe_bookings),
            "total_bookings_found": len(safe_bookings),
            "bookings": safe_bookings,
            "message": f"Ditemukan tepat {len(safe_bookings)} jadwal reservasi terdaftar pada akun ini."
        }

    elif tool_name == "find_booking_by_verification":
        res = calendar_service.get_user_bookings_by_verification(
            db=db,
            customer_phone=str(arguments.get("customer_phone", "")).strip(),
            customer_name=str(arguments.get("customer_name", "")).strip(),
            date=arguments.get("date")
        )
        safe_bookings = _sanitize_bookings_for_llm(res)
        return {
            "count": len(safe_bookings),
            "total_bookings_found": len(safe_bookings),
            "bookings": safe_bookings,
            "verification_status": "success" if safe_bookings else "not_found",
            "message": f"Ditemukan tepat {len(safe_bookings)} jadwal reservasi berdasarkan verifikasi 2 variabel."
        }

    else:
        return {"error": f"Unknown tool name: {tool_name}"}



def enforce_neutral_tone(text: str) -> str:
    """Removes non-neutral interjections or religious expressions to maintain a strictly professional persona."""
    if not text:
        return ""
    patterns = [
        r'\b[Aa]lhamdulillah[,\s]*',
        r'\b[Ii]nsya\s*[Aa]llah[,\s]*',
        r'\b[Mm]asya\s*[Aa]llah[,\s]*',
        r'\b[Ss]ubhanallah[,\s]*',
        r'\b[Pp]uji\s*[Tt]uhan[,\s]*',
        r'\b[Ww]allahu\s*[Aa]lam[,\s]*'
    ]
    cleaned = text
    for p in patterns:
        cleaned = re.sub(p, '', cleaned)
    cleaned = cleaned.strip()
    if cleaned and cleaned[0].islower():
        cleaned = cleaned[0].upper() + cleaned[1:]
    return cleaned


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
    # 0. Check for reset/clear/start commands to wipe memory
    clean_text = message_text.strip().lower()
    if (
        clean_text in ["/start", "/reset", "/clear", "/hapus", "reset", "hapus history", "mulai dari awal", "restart"]
        or clean_text.startswith("/start")
        or clean_text.startswith("/reset")
        or clean_text.startswith("/clear")
        or clean_text.startswith("/hapus")
    ):
        db.query(ChatHistory).filter(ChatHistory.phone_number == phone_number).delete(synchronize_session=False)
        db.commit()
        return "🎾 **Halo Pak/Bu! Selamat datang di Sistem Reservasi Lapangan Tenis Warga.**\n\nAda jadwal lapangan yang ingin dicek atau dibooking hari ini?"

    # 1. Log user message to DB
    user_msg_db = ChatHistory(phone_number=phone_number, role="user", content=message_text)
    db.add(user_msg_db)
    db.commit()

    # 2. Retrieve recent history (last 20 messages as conversational context)
    history_records = db.query(ChatHistory).filter(
        ChatHistory.phone_number == phone_number
    ).order_by(ChatHistory.timestamp.desc()).limit(20).all()
    history_records.reverse()

    messages: List[Any] = [{"role": "system", "content": get_system_prompt(phone_number)}]
    for rec in history_records:
        if rec.role in ["user", "assistant"]:
            messages.append({"role": rec.role, "content": rec.content})

    # Inject a reminder that chat history is context only, DB is the authority
    messages.append({
        "role": "system",
        "content": "PENGINGAT PENTING:\n"
                   "1. Untuk pertanyaan soal jadwal atau reservasi, Anda WAJIB memanggil tool untuk mengambil data terkini dari database. Hasil tool adalah SATU-SATUNYA SUMBER KEBENARAN.\n"
                   "2. GAYA BAHASA HARUS NETRAL & PROFESIONAL: DILARANG KERAS menggunakan kata-kata bernuansa agama (seperti: Alhamdulillah, Insya Allah, Masya Allah, Puji Tuhan, dll) atau opini/ekspresi berlebihan. Gunakan bahasa Indonesia yang sopan, netral, objektif, dan profesional."
    })

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
                fn_result = execute_tool_call(db, fn_name, fn_args, default_phone=phone_number, default_name=sender_name)

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

    final_reply = enforce_neutral_tone(final_reply)

    # Log assistant reply to DB
    assistant_msg_db = ChatHistory(phone_number=phone_number, role="assistant", content=final_reply)
    db.add(assistant_msg_db)
    db.commit()

    return final_reply
