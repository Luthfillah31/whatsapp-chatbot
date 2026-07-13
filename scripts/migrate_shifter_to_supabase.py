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
from sqlalchemy.exc import IntegrityError

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
        if len(raw_date) == 8:
            dt_str = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
        else:
            continue

        text = html.unescape(re.sub(r'<[^>]+>', '\n', notas))
        current_court_id = 1

        for line in text.split('\n'):
            line_clean = line.strip()
            if not line_clean:
                continue

            upper_line = line_clean.upper()
            if 'LAP B' in upper_line or 'LAPANGAN B' in upper_line or upper_line == 'B' or upper_line == 'LAP B':
                current_court_id = 2
                continue
            elif 'LAP A' in upper_line or 'LAPANGAN A' in upper_line or upper_line == 'A' or upper_line == 'LAP A':
                current_court_id = 1
                continue

            m = re.search(r'^(\d{1,2}\s*[-:]?\s*\d{0,2}\s*[APap][Mm]|\d{1,2}\s*[-:]\s*\d{1,2})[:\s\-]+(.*)$', line_clean)
            if m:
                slot_str = m.group(1).upper().replace(' ', '')
                customer = m.group(2).strip('- :')
                if customer and len(customer) > 1 and not customer.upper().startswith('LAP'):
                    start_t, end_t = parse_time_slot(slot_str)
                    if start_t and end_t:
                        parsed_bookings.append({
                            "booking_date": dt_str,
                            "court_id": current_court_id,
                            "start_time": start_t,
                            "end_time": end_t,
                            "customer_name": customer,
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

    # Deduplicate within memory first
    unique_bookings = []
    seen = set()
    for b in bookings_to_migrate:
        key = (b["court_id"], b["booking_date"], b["start_time"])
        if key not in seen:
            seen.add(key)
            unique_bookings.append(b)

    print(f"Setelah menghapus duplikasi internal: {len(unique_bookings)} sesi unik siap diimpor.")

    if dry_run:
        print("\n[DRY-RUN MODE] Contoh 10 data yang siap dimigrasi:")
        for b in unique_bookings[:10]:
            court_name = "Court 1 (A)" if b['court_id'] == 1 else "Court 2 (B)"
            print(f"  [{b['booking_date']}] {court_name} | {b['start_time']}-{b['end_time']} | {b['customer_name']}")
        print(f"\n[DRY-RUN MODE] Total {len(unique_bookings)} sesi siap diimpor. Tidak ada perubahan pada database Supabase.")
        return True

    db = SessionLocal()
    success_count = 0
    skip_count = 0

    for item in unique_bookings:
        try:
            # Check if booking already exists
            existing = db.query(Booking).filter_by(
                court_id=item["court_id"],
                booking_date=item["booking_date"],
                start_time=item["start_time"]
            ).first()

            if existing:
                skip_count += 1
                continue

            new_booking = Booking(
                court_id=item["court_id"],
                customer_phone=item["customer_phone"],
                customer_name=item["customer_name"],
                booking_date=item["booking_date"],
                start_time=item["start_time"],
                end_time=item["end_time"],
                status=item["status"],
                payment_status=item["payment_status"],
                google_event_id=item["google_event_id"]
            )
            db.add(new_booking)
            db.commit()
            success_count += 1
        except IntegrityError:
            db.rollback()
            skip_count += 1
        except Exception as e:
            db.rollback()
            print(f"Peringatan untuk {item['booking_date']} {item['start_time']}: {e}")

    db.close()
    print(f"Migrasi Selesai! Berhasil menyimpan {success_count} sesi reservasi nyata ke Supabase (Dilewati duplikat: {skip_count}).")
    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate Shifter data to Supabase PostgreSQL")
    parser.add_argument("--dry-run", action="store_true", help="Run in dry-run mode without saving to DB")
    args = parser.parse_args()

    success = run_migration(dry_run=args.dry_run)
    sys.exit(0 if success else 1)
