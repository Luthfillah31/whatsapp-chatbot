import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.models.db_models import SessionLocal, Booking

def clean_dummy_data():
    print("=== FASE 2: MEMBERSIHKAN DATA DUMMY DI TABEL 'bookings' SUPABASE ===")
    db = SessionLocal()
    try:
        count = db.query(Booking).delete()
        db.commit()
        print(f"Berhasil membersihkan {count} baris data dummy dari tabel 'bookings'.")
        return True
    except Exception as e:
        db.rollback()
        print(f"Gagal membersihkan data: {e}")
        return False
    finally:
        db.close()

if __name__ == "__main__":
    success = clean_dummy_data()
    sys.exit(0 if success else 1)
