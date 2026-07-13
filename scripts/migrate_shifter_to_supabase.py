import os
import sys
import re
import html
import sqlite3
import argparse
import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.models.db_models import SessionLocal, Booking

def parse_time_slot(slot_str):
    clean = slot_str.upper().replace(" ", "").replace("-", "")
    m = re.match(r"^(\d+)([AP]M)$", clean)
    if not m:
        return None, None
    digits = m.group(1)
    ampm = m.group(2)

    start_h = None
    end_h = None

    if len(digits) == 2:
        start_h = int(digits[0])
        end_h = int(digits[1])
    elif len(digits) == 3:
        if digits.startswith("810"):
            start_h, end_h = 8, 10
        elif digits.startswith("911"):
            start_h, end_h = 9, 11
        elif digits.startswith("710"):
            start_h, end_h = 7, 10
        elif digits.startswith("610"):
            start_h, end_h = 6, 10
        else:
            start_h = int(digits[:1])
            end_h = int(digits[1:])
    elif len(digits) == 4:
        start_h = int(digits[:2])
        end_h = int(digits[2:])

    if start_h is None or end_h is None:
        return None, None

    if ampm == "PM":
        if start_h < 12:
            start_h += 12
        if end_h < 12:
            end_h += 12
    elif ampm == "AM":
        if start_h == 12:
            start_h = 0
        if end_h == 12:
            end_h = 0

    return f"{start_h:02d}:00", f"{end_h:02d}:00"

def extract_bookings_from_shifter(db_path="Unnamed.Shifter"):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT fecha, notas FROM dias WHERE fecha > 0 AND notas IS NOT NULL AND notas != '';")
    rows = cursor.fetchall()
    conn.close()

    parsed_bookings = []
    for fecha, notas in rows:
        raw_date = str(int(fecha))
        if len(raw_date) != 8:
            continue
        dt_str = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"

        text = html.unescape(re.sub(r'<[^>]+>', '\n', notas))
        current_court = 1
        current_period = "AM"

        for line in text.split('\n'):
            line_clean = line.strip()
            if not line_clean:
                continue
            up = line_clean.upper()

            if up in ['LAP B', 'LAPANGAN B', 'COURT 2', 'COURT B', 'B']:
                current_court = 2
                continue
            if up in ['LAP A', 'LAPANGAN A', 'COURT 1', 'COURT A', 'A']:
                current_court = 1
                continue
            if up == 'PM-A':
                current_court = 1
                current_period = "PM"
                continue
            if up == 'PM-B':
                current_court = 2
                current_period = "PM"
                continue
            if up in ['AM', 'PAGI']:
                current_period = "AM"
                continue
            if up in ['PM', 'SORE', 'MALAM']:
                current_period = "PM"
                continue

            m1 = re.search(r'^(\d{1,2}\s*[-:]?\s*\d{1,2})\s*([APap][Mm])[:\s\-]+(.*)$', line_clean)
            if m1:
                digits = m1.group(1).replace(" ", "").replace("-", "")
                ampm = m1.group(2).upper()
                name = m1.group(3).strip('- :')
                if name:
                    start_t, end_t = parse_time_slot(digits + ampm)
                    if start_t and end_t:
                        parsed_bookings.append({
                            "booking_date": dt_str,
                            "court_id": current_court,
                            "start_time": start_t,
                            "end_time": end_t,
                            "customer_name": name,
                            "customer_phone": "0800-MIGRATED-SHIFTER",
                            "status": "confirmed",
                            "payment_status": "paid",
                            "google_event_id": "MIGRATED_FROM_SHIFTER"
                        })
                continue

            m2 = re.search(r'^([ABab]-)?(\d{2,4})[-:\s]+([A-Za-z].*)$', line_clean)
            if m2:
                court_pref = m2.group(1)
                digits = m2.group(2)
                name = m2.group(3).strip('- :')
                court_to_use = 2 if (court_pref and 'B' in court_pref.upper()) else current_court
                start_t, end_t = parse_time_slot(digits + current_period)
                if start_t and end_t:
                    parsed_bookings.append({
                        "booking_date": dt_str,
                        "court_id": court_to_use,
                        "start_time": start_t,
                        "end_time": end_t,
                        "customer_name": name,
                        "customer_phone": "0800-MIGRATED-SHIFTER",
                        "status": "confirmed",
                        "payment_status": "paid",
                        "google_event_id": "MIGRATED_FROM_SHIFTER"
                    })

    return parsed_bookings

def run_migration(dry_run=False):
    print("=== FASE 3: EKSTRAKSI & MIGRASI DATA NYATA SHIFTER KE SUPABASE ===")
    shifter_path = os.path.join(PROJECT_ROOT, "Unnamed.Shifter")
    bookings_to_migrate = extract_bookings_from_shifter(shifter_path)
    print(f"Berhasil memparsing {len(bookings_to_migrate)} sesi reservasi dari Unnamed.Shifter.")

    unique_bookings = []
    seen = set()
    for b in bookings_to_migrate:
        key = (b["court_id"], b["booking_date"], b["start_time"])
        if key not in seen:
            seen.add(key)
            unique_bookings.append(b)

    print(f"Setelah menghapus duplikasi internal: {len(unique_bookings)} sesi unik siap diimpor.")

    if dry_run:
        return True

    db = SessionLocal()
    try:
        # Fetch existing keys in ONE query
        existing_rows = db.query(Booking.court_id, Booking.booking_date, Booking.start_time).all()
        existing_keys = set(existing_rows)

        to_insert = []
        for item in unique_bookings:
            k = (item["court_id"], item["booking_date"], item["start_time"])
            if k not in existing_keys:
                to_insert.append(Booking(
                    court_id=item["court_id"],
                    customer_phone=item["customer_phone"],
                    customer_name=item["customer_name"],
                    booking_date=item["booking_date"],
                    start_time=item["start_time"],
                    end_time=item["end_time"],
                    status=item["status"],
                    payment_status=item["payment_status"],
                    google_event_id=item["google_event_id"]
                ))

        if to_insert:
            db.bulk_save_objects(to_insert)
            db.commit()
        print(f"Migrasi Selesai! Berhasil menyimpan {len(to_insert)} sesi baru ke Supabase.")
        return True
    except Exception as e:
        db.rollback()
        print(f"Terjadi kesalahan saat migrasi: {e}")
        return False
    finally:
        db.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate Shifter data to Supabase PostgreSQL")
    parser.add_argument("--dry-run", action="store_true", help="Run in dry-run mode without saving to DB")
    args = parser.parse_args()

    success = run_migration(dry_run=args.dry_run)
    sys.exit(0 if success else 1)
