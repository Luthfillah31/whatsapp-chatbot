import os
import sys
import json
import sqlite3
import datetime

# Ensure stdout uses UTF-8 on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.models.db_models import SessionLocal, Booking

def backup_dummy_data():
    print("=== FASE 1: MEMULAI BACKUP DATA DUMMY DARI SUPABASE POSTGRESQL ===")
    
    os.makedirs(os.path.join(PROJECT_ROOT, "backups"), exist_ok=True)
    sqlite_backup_path = os.path.join(PROJECT_ROOT, "backups", "dummy_bookings_backup.db")
    json_backup_path = os.path.join(PROJECT_ROOT, "backups", "dummy_bookings.json")

    db = SessionLocal()
    try:
        bookings = db.query(Booking).all()
        print(f"Ditemukan {len(bookings)} baris data dummy pada tabel 'bookings' Supabase.")

        rows_dict = []
        for b in bookings:
            rows_dict.append({
                "id": b.id,
                "court_id": b.court_id,
                "customer_phone": b.customer_phone,
                "customer_name": b.customer_name,
                "booking_date": b.booking_date,
                "start_time": b.start_time,
                "end_time": b.end_time,
                "status": b.status,
                "google_event_id": b.google_event_id,
                "payment_status": b.payment_status,
                "payment_url": b.payment_url,
                "payment_token": b.payment_token,
                "created_at": b.created_at.isoformat() if b.created_at else None
            })

        # 1. Save to JSON backup
        with open(json_backup_path, "w", encoding="utf-8") as f:
            json.dump(rows_dict, f, indent=2, ensure_ascii=False)
        print(f"Backup JSON berhasil disimpan: {json_backup_path}")

        # 2. Save to SQLite database
        conn = sqlite3.connect(sqlite_backup_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dummy_bookings_archive (
                id INTEGER PRIMARY KEY,
                court_id INTEGER,
                customer_phone TEXT,
                customer_name TEXT,
                booking_date TEXT,
                start_time TEXT,
                end_time TEXT,
                status TEXT,
                google_event_id TEXT,
                payment_status TEXT,
                payment_url TEXT,
                payment_token TEXT,
                created_at TEXT
            )
        """)
        cursor.execute("DELETE FROM dummy_bookings_archive")  # Replace with latest snapshot

        for row in rows_dict:
            cursor.execute("""
                INSERT INTO dummy_bookings_archive (
                    id, court_id, customer_phone, customer_name, booking_date,
                    start_time, end_time, status, google_event_id, payment_status,
                    payment_url, payment_token, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                row["id"], row["court_id"], row["customer_phone"], row["customer_name"],
                row["booking_date"], row["start_time"], row["end_time"], row["status"],
                row["google_event_id"], row["payment_status"], row["payment_url"],
                row["payment_token"], row["created_at"]
            ))

        conn.commit()
        archive_count = cursor.execute("SELECT COUNT(*) FROM dummy_bookings_archive").fetchone()[0]
        conn.close()

        print(f"Backup SQLite berhasil disimpan: {sqlite_backup_path} ({archive_count} baris diarsipkan)")
        print("=== BACKUP SELESAI 100% AMAN ===")
        return True
    except Exception as e:
        print(f"Terjadi kesalahan saat melakukan backup: {e}")
        return False
    finally:
        db.close()

if __name__ == "__main__":
    success = backup_dummy_data()
    sys.exit(0 if success else 1)
