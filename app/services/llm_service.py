import json
import logging
import datetime
import re
from typing import List, Dict, Any, Optional, cast, Tuple
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
            "description": "Check if Lapangan A (court_id=1) and/or Lapangan B (court_id=2) are available on a specific date, start time slot, and duration. ALWAYS pass duration_hours when checking multi-hour availability (e.g. '16:00 to 18:00' -> duration_hours=2).",
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
                    "duration_hours": {
                        "type": "integer",
                        "description": "Number of consecutive hours requested (1 to 18 hours). MUST pass if customer mentions playing duration or end time (e.g., 2 for 16:00-18:00). Defaults to 1."
                    },
                    "court_id": {
                        "type": "integer",
                        "description": "Optional court number (1 or 2). If omitted, checks both courts.",
                        "enum": [1, 2]
                    }
                },
                "required": ["date"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_available_slots",
            "description": "Search and list all available time slots and hours across one date or a date range (e.g. minggu ini, minggu depan, bulan ini). ALWAYS use this tool when the user asks questions like 'kapan saja yang kosong minggu depan?', 'hari apa saja yang kosong di atas jam 5?', 'besok jam berapa aja yang kosong?', or searching availability across multiple hours or days.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {
                        "type": "string",
                        "description": "Start date to search in YYYY-MM-DD format (e.g., '2026-07-14')."
                    },
                    "end_date": {
                        "type": "string",
                        "description": "Optional end date in YYYY-MM-DD format for searching across multiple days/weeks (e.g., '2026-07-20'). Defaults to start_date if omitted."
                    },
                    "min_hour": {
                        "type": "integer",
                        "description": "Minimum hour filter in 24-hour format (0-23). E.g., for 'di atas jam 5 sore / malam', pass 17. Defaults to 5 (05:00)."
                    },
                    "max_hour": {
                        "type": "integer",
                        "description": "Maximum hour filter in 24-hour format (0-23). Defaults to 22 (22:00)."
                    },
                    "court_id": {
                        "type": "integer",
                        "description": "Optional court filter (1 for Lapangan A, 2 for Lapangan B). Omit to check both courts."
                    }
                },
                "required": ["start_date"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_calendar_date",
            "description": "Checks the exact official day of the week (e.g. Senin, Selasa, Minggu) for any date in YYYY-MM-DD format.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Date to verify in YYYY-MM-DD format (e.g. '2026-07-26')."
                    }
                },
                "required": ["date"]
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
                    },
                    "duration_hours": {
                        "type": "integer",
                        "description": "Number of consecutive hours to book (1 to 18 hours). Must match agreed duration."
                    }
                },
                "required": ["court_id", "date", "time_slot", "duration_hours"]
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
            "name": "reschedule_booking",
            "description": "Reschedule or move an existing reservation ('pindah jadwal', switch court, change time/date) directly WITHOUT requiring a new payment or cancellation. ALWAYS use this tool when a customer wants to move/reschedule an existing booking (e.g. 'Id 40 ke tennis court 1', 'pindah ke jam 7 malam'). NEVER cancel and book again.",
            "parameters": {
                "type": "object",
                "properties": {
                    "booking_id": {
                        "type": "integer",
                        "description": "The numeric ID of the booking to reschedule."
                    },
                    "new_date": {
                        "type": "string",
                        "description": "Optional new target date in YYYY-MM-DD format. If omitted, keeps existing booking date."
                    },
                    "new_time_slot": {
                        "type": "string",
                        "description": "Optional new start time slot in 24-hour HH:MM format (e.g., '19:00'). If omitted, keeps existing booking time."
                    },
                    "new_court_id": {
                        "type": "integer",
                        "description": "Optional new court number (1 or 2). Defaults to existing booking court if omitted.",
                        "enum": [1, 2]
                    },
                    "customer_name": {
                        "type": "string",
                        "description": "Optional full name of the customer for 2-factor verification when rescheduling a booking registered under a different phone number."
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
    today_dt = calendar_service.get_wib_today()
    indonesian_days = {
        "Monday": "Senin", "Tuesday": "Selasa", "Wednesday": "Rabu",
        "Thursday": "Kamis", "Friday": "Jumat", "Saturday": "Sabtu", "Sunday": "Minggu"
    }
    today_day = indonesian_days.get(today_dt.strftime("%A"), today_dt.strftime("%A"))
    today_str = today_dt.strftime("%Y-%m-%d")
    return f"""Anda adalah Asisten AI Resmi untuk Sistem Reservasi Lapangan Tennis GBM. Tugas utama Anda adalah melayani warga dengan ramah, sopan, natural, dan berorientasi penuh pada kepuasan pelanggan (Customer Oriented).

===== INSTRUKSI UTAMA & NETRALITAS PERSONA (WAJIB DIPATUHI!) =====
1. PERSONA SEPENUHNYA NETRAL, OBJEKTIF, & PROFESIONAL:
   - DILARANG KERAS menggunakan kata-kata atau ungkapan bernuansa agama seperti: "Alhamdulillah", "Insya Allah", "Masya Allah", "Subhanallah", "Puji Tuhan", atau sejenisnya.
   - Hindari ekspresi emosional yang berlebihan. Gunakan bahasa Indonesia yang sopan, profesional, lugas, dan bersahabat.
2. KEPATUHAN PENUH TERHADAP DATA DATABASE:
   - Sumber kebenaran UTAMA dan SATU-SATUNYA untuk data jadwal, reservasi, dan ketersediaan lapangan adalah HASIL TOOL (yang mengambil langsung dari database).
   - Riwayat percakapan (chat history) HANYA berfungsi sebagai pengingat konteks percakapan. Riwayat percakapan BUKAN sumber data jadwal!
   - Setiap kali warga bertanya tentang jadwal, reservasi, atau ketersediaan lapangan, Anda WAJIB memanggil tool yang sesuai untuk mendapatkan data terkini dari database.
   - DILARANG KERAS menambahkan, mengarang, atau melanjutkan urutan jam yang TIDAK ADA di dalam hasil tool!

===== ATURAN KETAT VALIDASI HARI, TANGGAL & DURASI (WAJIB DIPATUHI!) =====
1. VALIDASI HARI DAN TANGGAL DALAM KALENDER (ANTI-HALUSINASI HARI):
   - JANGAN PERNAH menebak atau mengarang hari untuk suatu tanggal dari ingatan/asumsi Anda sendiri!
   - Setiap kali warga menanyakan hari atau menyebutkan kombinasi tanggal dan hari (misal "26 Juli hari Senin"), Anda WAJIB memanggil tool 'check_calendar_date' atau 'check_court_availability' untuk memeriksa kalender resmi.
   - Jika warga menyebutkan nama hari yang TIDAK COCOK dengan tanggalnya (misalnya warga berkata "Senin 26 Juli 2026" padahal 26 Juli 2026 adalah Hari Minggu), Anda WAJIB langsung memberi tahu koreksi harinya dengan sopan!
2. ATURAN DURASI DAN ANTI-ASUMSI JAM MAIN:
   - Jika warga TIDAK MENYEBUTKAN jam mulai bermain (misalnya hanya berkata "Lapang 1 2 jam"), Anda DILARANG KERAS menebak, mengasumsikan, atau mengambil jam dari contoh teks sebelumnya (seperti jam 08:00).
   - Anda WAJIB menanyakan jam mulai bermain terlebih dahulu: "Baik Pak/Bu, ingin bermain mulai jam berapa?"
   - JANGAN PERNAH memproses booking jika jam mulai belum disebutkan secara jelas oleh warga!
   - Penyewaan lapangan HANYA TERSEDIA per blok 1 jam penuh tepat pada jam bulat (misal: 08:00 - 09:00, 09:00 - 10:00) dengan durasi 1 hingga maksimal 18 jam per sesi. DILARANG memproses durasi menit pecahan.
3. TOLAK TANGGAL MASA LALU / SUDAH LEWAT:
   - Hari Ini adalah Hari {today_day}, {today_str}.
   - Jika warga menanyakan atau menyebutkan tanggal yang SUDAH LEWAT (sebelum hari ini), Anda WAJIB LANGSUNG MENOLAK dengan sopan dan menjelaskan bahwa tanggal tersebut sudah lewat.
   - DILARANG KERAS menawarkan cek ketersediaan atau menanyakan jam bermain untuk tanggal masa lalu!

===== INFORMASI OPERASIONAL & LOKASI LAPANGAN =====
- Nama Lapangan: {settings.CLUB_LOCATION_NAME}
- Lokasi / Google Maps: {settings.CLUB_LOCATION_URL}
- Jam Operasional: {settings.CLUB_OPENING_HOUR} - {settings.CLUB_CLOSING_HOUR} WIB setiap hari
- Jika warga menanyakan lokasi, alamat, atau share loc lapangan tenis, berikan informasi nama lapangan dan tautan Google Maps ({settings.CLUB_LOCATION_URL}) tersebut dengan ramah.

===== ATURAN GAYA BAHASA & ANTI-JARGON =====
1. CUSTOMER ORIENTED: Selalu bersikap membantu, hangat, sopan, dan solutif. Sapa warga dengan "Pak/Bu".
2. DILARANG KERAS MENAMPILKAN TEKS TEKNIS:
   - JANGAN PERNAH menyebutkan kata: tool, fungsi, parameter, database, backend, sistem verifikasi, eksekusi, JSON, query, API, total_bookings_found, atau istilah teknis lainnya.
   - JANGAN PERNAH menjelaskan cara kerja internal AI atau aturan keamanan.
3. JAWAB HANYA APA YANG DITANYA: Jangan memberikan informasi yang tidak diminta. Cukup tampilkan jadwal yang relevan secara ringkas, padat, dan jelas.
4. DILARANG KERAS MENYEBUTKAN SIMULASI: JANGAN PERNAH memberitahu warga bahwa ini adalah "simulasi", "uji coba", atau "tidak memotong uang asli".

INFORMASI PENTING KOMPLEK PERUMAHAN:
- Hari & Tanggal Hari Ini: Hari {today_day}, {today_str}
- Jam Operasional: {settings.CLUB_OPENING_HOUR} hingga {settings.CLUB_CLOSING_HOUR} WIB setiap hari.
- Biaya & Tarif Sewa Lapangan:
  * Jam Pagi - Sore (05:00 - 17:00 WIB): Rp 75.000 / jam
  * Jam Malam (17:00 - 23:00 WIB): Rp 80.000 / jam
  * PERHITUNGAN BIAYA LINTAS WAKTU (CROSS CALCULATION / LEWAT JAM 17:00):
    - Tarif dihitung PER JAM berdasarkan posisi masing-masing jam bermain. Mulai tepat pukul 17:00 sudah masuk tarif malam (Rp 80.000/jam).
    - CONTOH 1 (SANGAT PENTING): Booking jam 16:00 - 18:00 (durasi 2 jam):
      • Jam 16:00 - 17:00 (1 jam Pagi-Sore) = Rp 75.000
      • Jam 17:00 - 18:00 (1 jam Malam) = Rp 80.000
      • TOTAL BIAYA = Rp 155.000 (DILARANG KERAS MENGHITUNG Rp 150.000!).
    - CONTOH 2: Booking jam 15:00 - 18:00 (durasi 3 jam):
      • Jam 15:00 - 17:00 (2 jam Pagi-Sore) = 2 x Rp 75.000 = Rp 150.000
      • Jam 17:00 - 18:00 (1 jam Malam) = Rp 80.000
      • TOTAL BIAYA = Rp 230.000.
    - Anda WAJIB memeriksa apakah jam bermain melewati pukul 17:00 dan menghitung total biaya secara teliti jam per jam!
- Fasilitas: '{settings.COURT_1_NAME}' (ID sistem: 1) dan '{settings.COURT_2_NAME}' (ID sistem: 2). PERINGATAN: Gunakan sebutan alami "Lapangan A" dan "Lapangan B" saja saat menjawab warga. DILARANG KERAS menuliskan teks "(court_id=1)" atau "(court_id=2)" dalam pesan kepada warga!

IDENTITAS PENGGUNA AKTIF:
- ID Kontak warga saat ini: {sender_phone}

===== ATURAN KRISIAL ANTI-HALUSINASI LINK PEMBAYARAN (WAJIB DIPATUHI!) =====
1. DILARANG KERAS MENGARANG / MENULIS LINK PEMBAYARAN SENDIRI DI DALAM TEKS!
   - Anda TIDAK BOLEH menulis URL / link pembayaran palsu (seperti /payments/mock?order_id=...) di dalam teks jawaban Anda.
   - Link pembayaran resmi HANYA didapatkan dari hasil eksekusi tool 'book_court'.
2. JIKA WARGA SETUJU PESAN / BOOKING, WAJIB EKSEKUSI TOOL 'book_court':
   - Setiap kali warga menyatakan setuju untuk booking (misal: "ya setuju boleh", "oke pesan", "lanjutkan booking"), Anda WAJIB memanggil tool 'book_court' secara nyata.
   - DILARANG KERAS memberikan link pembayaran tanpa menjalankan tool 'book_court'.
===== PRINSIP WAJIB: SELALU MINTA KONFIRMASI SEBELUM EKSEKUSI (BOOKING / CANCEL / RESCHEDULE) =====
Sebelum Anda mengeksekusi aksi yang membuat, mengubah, atau membatalkan pesanan (book_court, cancel_booking, reschedule_booking), Anda WAJIB menampilkan ringkasan detail pesanan dan meminta konfirmasi persetujuan terlebih dahulu kepada warga, KECUALI warga sudah secara eksplisit membalas pesan konfirmasi Anda ("ya lanjutkan", "oke setuju", "ya batalkan", "betul").

===== ALUR PELAYANAN RESERVASI WARGA =====
1. CEK JADWAL KOSONG & PENCARIAN KETERSEDIAAN:
   - Jika warga menanyakan ketersediaan pada tanggal & jam spesifik (misal "besok jam 16:00 sampai 18:00 kosong?"), panggil tool 'check_court_availability'.
   - JIKA WARGA BERTANYA PENCARIAN ATAU MENCARI JADWAL KOSONG (misal "besok jam berapa aja yang kosong?", "minggu depan hari apa yang kosong?", "bulan ini di atas jam 5 sore yang kosong hari apa?"):
     Anda WAJIB memanggil tool 'search_available_slots'. Tool ini akan mengembalikan daftar lengkap tanggal DAN jam spesifik yang kosong di Lapangan A dan Lapangan B.
     SAAT MENJAWAB WARGA DARI HASIL 'search_available_slots', Anda WAJIB MENYEBUTKAN HARI, TANGGAL, LAPANGAN, DAN DAFTAR JAM SPESIFIK YANG KOSONG (misal: "Rabu 15 Juli: Lapangan B kosong jam 17:00, 19:00, 20:00"). DILARANG KERAS hanya menyebutkan nama hari/lapangan tanpa menyertakan jamnya!
   - SAAT MENJAWAB INFORMASI KETERSEDIAAN UNTUK DURASI LEBIH DARI 1 JAM (>1 jam):
     Anda WAJIB MENCANTUMKAN TOTAL BIAYA SELURUH DURASI DAN RINCIAN TARIFNYA SESUAI HASIL TOOL (contoh: "Total Rp 155.000 untuk 2 jam (16:00-17:00 Rp 75.000 + 17:00-18:00 Rp 80.000)").
     DILARANG KERAS hanya menuliskan tarif 1 jam pertama (seperti "Rp 75.000/jam") jika warga memesan 2 jam atau lebih karena sangat menyesatkan!
2. BOOKING LAPANGAN ('book_court'):
   - Saat warga mengajukan pesanan baru (misal: "mau pesan lap A besok jam 16-18 atas nama Luthfi"), JANGAN langsung memanggil tool 'book_court' pada permintaan awal!
   - Tampilkan ringkasan lengkap pesanan: *Lapangan*, *Hari & Tanggal*, *Jam & Durasi*, *Total Biaya*, dan *Nama Reservasi*, lalu tanyakan konfirmasi: "Apakah detail reservasi di atas sudah sesuai dan ingin saya proses sekarang?"
   - BARU panggil tool 'book_court' secara nyata setelah warga membalas setuju ("ya sesuai", "oke proses", "betul", "ya setuju boleh").
   - Jika nama warga belum pernah disebutkan, Anda wajib menanyakan nama warga secara santai untuk dicantumkan pada jadwal. Nama satu kata (misalnya: "Wira", "Junaedi") adalah nama yang valid dan harus langsung digunakan.
   - JANGAN PERNAH MENANYAKAN NOMOR HP/KONTAK! Nomor kontak otomatis menggunakan akun yang sedang aktif.
   - Panggilan tool 'book_court' harus dilakukan secara nyata. DILARANG KERAS hanya membalas dengan teks janji memproses tanpa memanggil tool. Batas waktu pembayaran adalah 10 menit.
   - Jika warga menyebutkan jam tanpa keterangan pagi/malam (misalnya: "jam 9", "jam 8", "jam 7") dan waktu pagi hari tersebut sudah lewat, Anda WAJIB mengasumsikan waktu tersebut adalah sore/malam hari (misalnya: "jam 9" berarti "21:00").
3. CEK RESERVASI SAYA: Jika warga ingin melihat jadwal mereka, WAJIB PANGGIL TOOL list_my_bookings TERLEBIH DAHULU, lalu tampilkan hasilnya APA ADANYA.
4. PEMINDAHAN JADWAL / PINDAH LAPANGAN / RESCHEDULE ('reschedule_booking'):
   - Jika warga meminta memindahkan jadwal, pindah lapangan, atau ganti jam (misalnya: "pindah ke court 1", "mau pindah jam 7 malam"):
     a) JANGAN langsung mengeksekusi tool 'reschedule_booking' pada permintaan pertama! Tampilkan detail perubahan dari jadwal lama ke jadwal baru dan minta konfirmasi persetujuan warga terlebih dahulu.
     b) BARU panggil tool 'reschedule_booking' setelah warga menyetujui ("ya pindahkan", "setuju", "oke").
   - DILARANG KERAS menawarkan atau melakukan pembatalan ('cancel_booking') + pembuatan reservasi baru ('book_court') karena akan membuat tagihan bayar baru!
   - Cukup panggil tool 'reschedule_booking'. Jika warga hanya meminta pindah lapangan tanpa menyebut tanggal/jam baru, cukup isi 'booking_id' dan 'new_court_id' (parameter new_date dan new_time_slot opsional). Sistem otomatis memindahkan jadwal gratis tanpa bayar lagi!
5. PEMBATALAN ('cancel_booking'):
   - Jika warga meminta membatalkan pesanan ("tolong batalkan reservasi saya", "cancel pesanan saya"):
     a) JANGAN langsung mengeksekusi tool 'cancel_booking'!
     b) Jika ID Booking belum disebutkan, panggil tool 'list_my_bookings' terlebih dahulu untuk mengecek daftar pesanan warga.
     c) Tampilkan detail pesanan yang akan dibatalkan (*ID Booking*, *Lapangan*, *Tanggal*, *Jam*) dan tanyakan konfirmasi: "Apakah Bapak/Ibu yakin ingin membatalkan reservasi tersebut?"
     d) BARU panggil tool 'cancel_booking' setelah warga membalas yakin/setuju untuk membatalkan ("ya batalkan", "yakin", "iya batal").
6. RESET MEMORI: Jika warga ingin hapus history, arahkan untuk mengetik **/reset**, **/clear**, atau **/start**.

===== FORMATTING PESAN UNTUK WHATSAPP (WAJIB DIPATUHI!) =====
- DILARANG KERAS menggunakan tabel Markdown (seperti | Waktu | Tarif |) karena pesan dikirim via WhatsApp dan tabel Markdown tidak dapat dibaca di HP.
- Selalu gunakan format daftar/bullet points (• atau -) yang rapi, bersih, bersahabat, dan mudah dibaca di layar HP WhatsApp.
- Gunakan tanda bintang *untuk tebal* saat menonjolkan informasi penting seperti Nama Lapangan, Jam, Tarif, atau Tanggal.
- Gunakan emoji secukupnya (🎾, 📅, 📋, 😊) agar percakapan bersahabat dan natural."""


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


def _extract_slot(args: Dict[str, Any], default: str = "") -> str:
    slot = (
        args.get("new_time_slot")
        or args.get("time_slot")
        or args.get("new_start_time")
        or args.get("start_time")
        or args.get("time")
    )

    if not slot:
        return default
    s = str(slot).strip()
    if "-" in s:
        s = s.split("-")[0].strip()
    return s


def _extract_court_id(val: Any, default: Optional[int] = None) -> Optional[int]:
    if val is None:
        return default
    if isinstance(val, int) and val in [1, 2]:
        return val
    s = str(val).upper().strip()
    if any(k in s for k in ['B', '2', 'SECOND', 'DUA']):
        return 2
    if any(k in s for k in ['A', '1', 'FIRST', 'SATU']):
        return 1
    digits = re.findall(r'\d+', s)
    if digits and int(digits[0]) in [1, 2]:
        return int(digits[0])
    return default


def _extract_duration_hours(args: Dict[str, Any], slot: str, default: Any = 1) -> Any:
    dur = (
        args.get("duration_hours")
        or args.get("duration")
        or args.get("hours")
        or args.get("durasi")
        or args.get("lama_sewa")
    )
    if dur is not None:
        try:
            return max(1, min(18, int(dur)))
        except (ValueError, TypeError):
            pass
    end_time = args.get("end_time") or args.get("end_slot") or args.get("end_time_slot")
    if end_time:
        try:
            sh = int(slot.split(":")[0])
            eh = int(str(end_time).split(":")[0])
            if eh > sh:
                return max(1, min(18, eh - sh))
        except Exception:
            pass
    raw_slot = str(args.get("new_time_slot") or args.get("time_slot") or args.get("start_time") or "")
    if "-" in raw_slot:
        try:
            parts = [p.strip() for p in raw_slot.split("-")]
            sh = int(parts[0].split(":")[0])
            eh = int(parts[1].split(":")[0])
            if eh > sh:
                return max(1, min(18, eh - sh))
        except Exception:
            pass
    return default


def execute_tool_call(db: Session, tool_name: str, arguments: Dict[str, Any], default_phone: str, default_name: str = "Warga") -> Any:
    """Dispatches tool execution to the calendar service.
    
    SECURITY: Standard operations anchor to `default_phone` (derived from WhatsApp sender).
    During court reservation (`book_court`), a preferred phone number can be specified.
    For cross-number queries (`find_booking_by_verification`) and cancellations (`cancel_booking`),
    2-Factor Verification (both Phone and exact Name) is strictly enforced.
    """
    logger.info(f"Executing Tool: {tool_name} with args: {arguments} for phone: {default_phone}")
    
    if tool_name == "check_calendar_date":
        return calendar_service.check_calendar_date(arguments["date"])

    elif tool_name == "check_court_availability":
        slot = _extract_slot(arguments)
        dur = _extract_duration_hours(arguments, slot, default=1)
        court_id = _extract_court_id(arguments.get("court_id"), default=None)
        res = calendar_service.check_court_availability(
            db=db,
            date=arguments["date"],
            time_slot=slot,
            court_id=court_id,
            duration_hours=dur
        )
        return res.model_dump()

    elif tool_name == "search_available_slots":
        c_id = _extract_court_id(arguments.get("court_id"), default=None)
        return calendar_service.search_available_slots(
            db=db,
            start_date=arguments["start_date"],
            end_date=arguments.get("end_date"),
            min_hour=int(arguments.get("min_hour", 5)),
            max_hour=int(arguments.get("max_hour", 22)),
            court_id=c_id
        )

    elif tool_name == "book_court":
        slot = _extract_slot(arguments)
        dur = _extract_duration_hours(arguments, slot)
        court_id = _extract_court_id(arguments.get("court_id"), default=1)
        c_name = arguments.get("customer_name")
        if not c_name or not c_name.strip() or c_name.lower() in ["warga", "customer"]:
            c_name = default_name

        res = calendar_service.create_booking(
            db=db,
            court_id=court_id or 1,
            date=arguments["date"],
            time_slot=slot,
            customer_name=c_name,
            customer_phone=default_phone,
            duration_hours=dur
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

    elif tool_name == "reschedule_booking":
        slot = _extract_slot(arguments)
        dur = _extract_duration_hours(arguments, slot, default=None)
        new_court_id = _extract_court_id(
            arguments.get("new_court_id") if "new_court_id" in arguments else arguments.get("court_id"),
            default=None
        )
        new_date = arguments.get("new_date") or arguments.get("date")
        c_name = arguments.get("customer_name")
        res = calendar_service.reschedule_booking(
            db=db,
            booking_id=arguments["booking_id"],
            new_date=new_date,
            new_time_slot=slot,
            customer_phone=default_phone,
            new_court_id=new_court_id,
            duration_hours=dur,
            customer_name=c_name
        )
        return res.model_dump()


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



def strip_dsml_tags(text: Optional[str]) -> str:
    """Removes raw DSML / XML tool call markup that some models leak into text content."""
    if not text:
        return ""
    cleaned = re.sub(r'<(?:[\|\uff5c]DSML[\|\uff5c])?tool_calls>[\s\S]*?</(?:[\|\uff5c]DSML[\|\uff5c])?tool_calls>', '', text)
    cleaned = re.sub(r'<(?:[\|\uff5c]DSML[\|\uff5c])?invoke[\s\S]*?</(?:[\|\uff5c]DSML[\|\uff5c])?invoke>', '', cleaned)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned).strip()
    return cleaned


def extract_dsml_tool_calls(content: str) -> List[Tuple[str, Dict[str, Any]]]:
    """Parses text-based DSML/XML tool calls emitted by models like DeepSeek / Ling."""
    if not content:
        return []
    invoke_pattern = r'<(?:[\|\uff5c]DSML[\|\uff5c])?invoke\s+name="([^"]+)">([\s\S]*?)</(?:[\|\uff5c]DSML[\|\uff5c])?invoke>'
    param_pattern = r'<(?:[\|\uff5c]DSML[\|\uff5c])?parameter\s+name="([^"]+)"[^>]*>([\s\S]*?)</(?:[\|\uff5c]DSML[\|\uff5c])?parameter>'
    found = []
    for match in re.finditer(invoke_pattern, content):
        fn_name = match.group(1).strip()
        params_str = match.group(2)
        args = {}
        for p_match in re.finditer(param_pattern, params_str):
            p_name = p_match.group(1).strip()
            p_val = p_match.group(2).strip()
            if p_val.isdigit():
                args[p_name] = int(p_val)
            else:
                args[p_name] = p_val
        found.append((fn_name, args))
    return found


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
        return "🎾 **Halo Pak/Bu! Selamat datang di Sistem Reservasi Lapangan Tennis GBM.**\n\nAda jadwal lapangan yang ingin dicek atau dibooking hari ini?"

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
                   "2. GAYA BAHASA HARUS NETRAL & PROFESIONAL: DILARANG KERAS menggunakan kata-kata bernuansa agama (seperti: Alhamdulillah, Insya Allah, Masya Allah, Puji Tuhan, dll) atau opini/ekspresi berlebihan. Gunakan bahasa Indonesia yang sopan, netral, objektif, dan profesional.\n"
                   "3. ANTI-HALUSINASI TOOL: Setelah memanggil tool (seperti cancel_booking atau book_court), periksa field 'success' pada hasil tool. Jika 'success' bernilai false, sampaikan pesan error sesuai hasil tool dan JANGAN PERNAH mengatakan reservasi berhasil dibuat atau dibatalkan!\n"
                   "4. FORMAT WHATSAPP: DILARANG KERAS menggunakan tabel Markdown (| ... |). Gunakan format daftar/bullet point (• atau -) yang rapi dan mudah dibaca di layar HP WhatsApp."
    })

    # Ensure current message is in the list if not already retrieved
    if not messages or messages[-1].get("content") != message_text:
        messages.append({"role": "user", "content": message_text})

    book_court_called = False
    try:
        max_turns = 3
        current_turn = 0
        final_reply = None

        while current_turn < max_turns:
            current_turn += 1
            response = cast(ChatCompletion, get_client().chat.completions.create(
                model=settings.OPENROUTER_MODEL,
                messages=messages,
                tools=cast(Any, TENNIS_TOOLS),
                tool_choice="auto",
                temperature=0.3
            ))

            msg = response.choices[0].message
            tool_calls = msg.tool_calls
            parsed_dsml_calls = []
            if not tool_calls and msg.content:
                parsed_dsml_calls = extract_dsml_tool_calls(msg.content)

            if tool_calls:
                messages.append(msg)
                for tool_call in tool_calls:
                    fn_name = tool_call.function.name
                    if fn_name == "book_court":
                        book_court_called = True
                    try:
                        fn_args = json.loads(tool_call.function.arguments)
                    except Exception:
                        fn_args = {}

                    fn_result = execute_tool_call(db, fn_name, fn_args, default_phone=phone_number, default_name=sender_name)
                    messages.append({
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": fn_name,
                        "content": json.dumps(fn_result)
                    })
                continue
            elif parsed_dsml_calls:
                messages.append({"role": "assistant", "content": strip_dsml_tags(msg.content) or "Memeriksa jadwal..."})
                for fn_name, fn_args in parsed_dsml_calls:
                    if fn_name == "book_court":
                        book_court_called = True
                    fn_result = execute_tool_call(db, fn_name, fn_args, default_phone=phone_number, default_name=sender_name)
                    messages.append({
                        "role": "user",
                        "content": f"[Hasil Tool {fn_name}]: {json.dumps(fn_result, ensure_ascii=False)}"
                    })
                continue
            else:
                text_content = msg.content or ""
                # Detect hallucinated payment link without book_court execution
                if not book_court_called and ("payments/mock" in text_content or "order_id=booking-" in text_content):
                    logger.warning("Detected hallucinated payment link without book_court call. Intercepting and prompting tool execution...")
                    messages.append({"role": "assistant", "content": text_content})
                    messages.append({
                        "role": "user",
                        "content": "SISTEM PERINGATAN: Anda menuliskan link pembayaran di teks tanpa memanggil tool 'book_court'. Anda WAJIB memanggil tool 'book_court' sekarang juga untuk mendaftarkan reservasi resmi ke database!"
                    })
                    continue
                final_reply = text_content
                break

    except Exception as e:
        logger.error(f"OpenRouter API Error: {e}", exc_info=True)
        final_reply = "🎾 Halo! Mohon maaf, saat ini sedang ada sedikit kendala teknis pada server penjadwalan kami. Silakan coba kirim pesan lagi dalam beberapa saat ya!"

    if final_reply is None:
        final_reply = "🎾 Mohon maaf, tidak ada respons dari server saat ini. Silakan coba lagi."

    if not book_court_called and final_reply and ("payments/mock" in final_reply or "order_id=booking-" in final_reply):
        final_reply = "🎾 Mohon konfirmasi sekali lagi detail pesanan Anda (Tanggal, Jam, dan Lapangan) agar saya dapat memproses pendaftaran booking resminya ke database sekarang."

    final_reply = strip_dsml_tags(final_reply)
    final_reply = enforce_neutral_tone(final_reply)

    # Log assistant reply to DB
    assistant_msg_db = ChatHistory(phone_number=phone_number, role="assistant", content=final_reply)
    db.add(assistant_msg_db)
    db.commit()

    return final_reply
