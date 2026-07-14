import streamlit as st
import streamlit.components.v1 as components
import datetime
import pandas as pd
from app.models.db_models import SessionLocal
from app.services.calendar_service import get_daily_schedule
from app.config import settings

# Page config with modern title and icon
st.set_page_config(
    page_title="Sistem Reservasi Lapangan Tennis GBM - Admin Dashboard",
    page_icon="🎾",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Custom CSS for Premium Glassmorphism and Modern Aesthetics
st.markdown("""
<style>
    /* Main Background & Typography */
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&family=Inter:wght@400;500;600&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    
    h1, h2, h3 {
        font-family: 'Outfit', sans-serif !important;
        font-weight: 700 !important;
    }
    
    /* Premium Header Banner */
    .header-banner {
        background: linear-gradient(135deg, #065f46 0%, #059669 50%, #10b981 100%);
        padding: 2.5rem;
        border-radius: 16px;
        color: white;
        margin-bottom: 2rem;
        box-shadow: 0 10px 25px -5px rgba(16, 185, 129, 0.4);
        position: relative;
        overflow: hidden;
    }
    .header-banner::after {
        content: "🏡";
        font-size: 8rem;
        position: absolute;
        right: -20px;
        bottom: -20px;
        opacity: 0.15;
        transform: rotate(-15deg);
    }
    .header-title {
        font-size: 2.5rem;
        font-weight: 700;
        margin: 0;
        letter-spacing: -0.5px;
    }
    .header-subtitle {
        font-size: 1.1rem;
        opacity: 0.9;
        margin-top: 0.5rem;
    }
    
    /* KPI Cards Glassmorphic Styling */
    .kpi-card {
        background: rgba(255, 255, 255, 0.05);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 12px;
        padding: 1.5rem;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        backdrop-filter: blur(10px);
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    .kpi-card:hover {
        transform: translateY(-3px);
        box-shadow: 0 12px 20px -5px rgba(0, 0, 0, 0.2);
    }
    .kpi-label {
        font-size: 0.9rem;
        color: #94a3b8;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        font-weight: 600;
    }
    .kpi-value {
        font-size: 2.2rem;
        font-weight: 700;
        color: #f8fafc;
        margin-top: 0.5rem;
    }
    
    /* Table Styling */
    .stDataFrame {
        border-radius: 12px;
        overflow: hidden;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
    }
    
    /* Date Input Box Enlargement */
    div[data-testid="stDateInput"] div[data-baseweb="input"] {
        min-height: 56px !important;
        font-size: 1.35rem !important;
        border-radius: 12px !important;
        border: 2px solid #10b981 !important;
        background-color: rgba(16, 185, 129, 0.1) !important;
        padding-left: 12px !important;
    }
    div[data-testid="stDateInput"] input {
        font-size: 1.35rem !important;
        font-weight: 700 !important;
        color: #10b981 !important;
    }

    /* Premium Custom HTML Table & Glassmorphic Badges */
    .custom-table-container {
        background: rgba(15, 23, 42, 0.6);
        backdrop-filter: blur(16px);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 16px;
        overflow: hidden;
        margin-top: 1.5rem;
        box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3);
    }
    .custom-table {
        width: 100%;
        border-collapse: collapse;
        text-align: left;
        color: #f3f4f6;
    }
    .custom-table th {
        background: rgba(30, 41, 59, 0.9);
        padding: 18px 24px;
        font-weight: 600;
        font-size: 0.85rem;
        text-transform: uppercase;
        letter-spacing: 1px;
        color: #94a3b8;
        border-bottom: 2px solid rgba(255, 255, 255, 0.05);
    }
    .custom-table td {
        padding: 18px 24px;
        font-size: 0.95rem;
        border-bottom: 1px solid rgba(255, 255, 255, 0.05);
        vertical-align: middle;
    }
    .custom-table tr:hover {
        background: rgba(255, 255, 255, 0.02);
    }
    .custom-table tr:last-child td {
        border-bottom: none;
    }
    .time-slot-badge {
        font-family: 'Outfit', sans-serif;
        font-weight: 700;
        font-size: 1rem;
        color: #60a5fa;
        background: rgba(96, 165, 250, 0.1);
        padding: 6px 12px;
        border-radius: 8px;
        border: 1px solid rgba(96, 165, 250, 0.2);
        display: inline-block;
    }
    .status-badge {
        display: inline-flex;
        align-items: center;
        font-weight: 700;
        font-size: 0.75rem;
        padding: 6px 14px;
        border-radius: 20px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .status-available {
        background: rgba(16, 185, 129, 0.1);
        color: #10b981;
        border: 1px solid rgba(16, 185, 129, 0.2);
    }
    .status-pending {
        background: rgba(245, 158, 11, 0.1);
        color: #f59e0b;
        border: 1px solid rgba(245, 158, 11, 0.2);
        box-shadow: 0 0 10px rgba(245, 158, 11, 0.15);
    }
    .status-booked {
        background: rgba(239, 68, 68, 0.1);
        color: #ef4444;
        border: 1px solid rgba(239, 68, 68, 0.2);
    }
    .customer-name-text {
        font-weight: 600;
        color: #f1f5f9;
    }
    .customer-empty-text {
        color: #64748b;
        font-style: italic;
    }
</style>

""", unsafe_allow_html=True)

# Header Section
st.markdown("""
<div class="header-banner">
    <div class="header-title">🎾 Sistem Reservasi Lapangan Tennis GBM</div>
</div>
""", unsafe_allow_html=True)

# Control Panel directly on main dashboard
ctrl_col1, ctrl_col2 = st.columns([1, 1])

with ctrl_col1:
    st.markdown("### 📅 Pilih Tanggal Operasional:")
    selected_date = st.date_input(
        "📅 Pilih Tanggal Operasional",
        value=datetime.date.today(),
        label_visibility="collapsed",
        help="Pilih tanggal untuk memuat jadwal ketersediaan lapangan real-time dari database."
    )
    date_str = selected_date.strftime("%Y-%m-%d")

with ctrl_col2:
    st.markdown("### ℹ️ Info Operasional Lapangan:")
    st.write(f"**Jam Operasional**: {settings.CLUB_OPENING_HOUR} - {settings.CLUB_CLOSING_HOUR} WIB setiap hari")
    st.write(f"**📍 Lokasi Google Maps**: [Buka Peta ({settings.CLUB_LOCATION_URL})]({settings.CLUB_LOCATION_URL})")

st.markdown("---")

# Handle Drag & Drop / Direct Actions triggered via query parameters
action = st.query_params.get("action")
if action in ["move", "delete"]:
    db_act = SessionLocal()
    try:
        from app.models.db_models import Booking
        if action == "move":
            booking_id = int(st.query_params.get("id", 0))
            new_court = int(st.query_params.get("court", 1))
            new_time = st.query_params.get("time", "07:00") or "07:00"
            end_h = int(new_time.split(":")[0]) + 1
            new_end = f"{end_h:02d}:00"
            b = db_act.query(Booking).filter(Booking.id == booking_id).first()
            if b:
                b.court_id = new_court
                b.start_time = new_time
                b.end_time = new_end
                db_act.commit()
                st.toast(f"✅ Jadwal {b.customer_name} berhasil dipindahkan ke Lapangan {new_court} ({new_time})!")
        elif action == "delete":
            booking_id = int(st.query_params.get("id", 0))
            b = db_act.query(Booking).filter(Booking.id == booking_id).first()
            if b:
                db_act.delete(b)
                db_act.commit()
                st.toast("🗑️ Reservasi berhasil dihapus!")
    finally:
        db_act.close()
        st.query_params.clear()
        st.rerun()

# Fetch Schedule Data from Local Database
db = SessionLocal()
try:
    schedule_data = get_daily_schedule(db, date_str)
finally:
    db.close()

slots = schedule_data.slots

# Calculate Owner KPI Metrics
total_slots = len(slots) * 2
booked_c1 = sum(1 for s in slots if s.court_1_status != "Available")
booked_c2 = sum(1 for s in slots if s.court_2_status != "Available")
total_booked = booked_c1 + booked_c2
total_avail = total_slots - total_booked
occupancy_rate = (total_booked / total_slots * 100) if total_slots > 0 else 0.0

# KPI Cards Section
col1, col2, col3 = st.columns(3)

with col1:
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-label">Tingkat Okupansi</div>
        <div class="kpi-value">{occupancy_rate:.1f}%</div>
    </div>
    """, unsafe_allow_html=True)

with col2:
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-label">Total Jam Terpesan</div>
        <div class="kpi-value">{total_booked} <span style="font-size:1.2rem; color:#94a3b8;">/ {total_slots} jam</span></div>
    </div>
    """, unsafe_allow_html=True)

with col3:
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-label">Slot Tersedia</div>
        <div class="kpi-value">{total_avail} <span style="font-size:1.2rem; color:#94a3b8;">jam</span></div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# Dialog Konfirmasi Hapus
@st.dialog("⚠️ Konfirmasi Hapus Reservasi")
def show_delete_dialog(booking_id: int, customer: str, court_name: str, time_slot: str):
    st.write("Apakah Anda yakin ingin menghapus / membatalkan reservasi berikut?")
    st.markdown(f"""
    - **ID Booking**: `#{booking_id}`
    - **Pemesan**: **{customer}**
    - **Lapangan**: **{court_name}**
    - **Jam**: **{time_slot}**
    """)
    st.warning("Tindakan ini akan membatalkan reservasi secara permanen.")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("❌ Batal", use_container_width=True):
            st.rerun()
    with col2:
        if st.button("🗑️ Ya, Hapus Reservasi", type="primary", use_container_width=True):
            db_del = SessionLocal()
            try:
                from app.models.db_models import Booking
                b = db_del.query(Booking).filter(Booking.id == booking_id).first()
                if b:
                    db_del.delete(b)
                    db_del.commit()
            finally:
                db_del.close()
            st.success("Reservasi berhasil dihapus!")
            st.rerun()

# Dialog Konfirmasi Pindah Jadwal
@st.dialog("↔️ Pindahkan Jadwal Reservasi")
def show_move_dialog(booking_id: int, customer: str, old_court_id: int, old_time: str, date_str: str):
    st.write("Pilih jadwal & lapangan baru untuk memindahkan reservasi ini:")
    st.markdown(f"**Pemesan**: **{customer}** | **Jadwal Lama**: Lapangan {'A' if old_court_id == 1 else 'B'} ({old_time})")

    new_court = st.selectbox(
        "🎾 Pilih Lapangan Tujuan:",
        options=[1, 2],
        format_func=lambda x: settings.COURT_1_NAME if x == 1 else settings.COURT_2_NAME
    )
    all_hours = [f"{h:02d}:00" for h in range(5, 23)]
    new_time = st.selectbox("⏰ Pilih Jam Mulai Baru:", options=all_hours, index=all_hours.index(old_time) if old_time in all_hours else 0)

    st.warning(f"Konfirmasi Pindah: Dari Lapangan {'A' if old_court_id==1 else 'B'} ({old_time}) ➔ Lapangan {'A' if new_court==1 else 'B'} ({new_time})")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("❌ Batal", key="cancel_move", use_container_width=True):
            st.rerun()
    with col2:
        if st.button("✅ Ya, Pindahkan Sekarang", type="primary", key="confirm_move", use_container_width=True):
            db_mov = SessionLocal()
            try:
                from app.models.db_models import Booking
                safe_time = str(new_time or "07:00")
                end_h = int(safe_time.split(":")[0]) + 1
                new_end = f"{end_h:02d}:00"

                existing = db_mov.query(Booking).filter(
                    Booking.booking_date == date_str,
                    Booking.court_id == new_court,
                    Booking.start_time == new_time,
                    Booking.id != booking_id
                ).first()

                if existing:
                    st.error(f"Gagal memindahkan: Lapangan dan jam tersebut sudah terisi oleh {existing.customer_name}!")
                else:
                    b = db_mov.query(Booking).filter(Booking.id == booking_id).first()
                    if b:
                        b.court_id = new_court
                        b.start_time = new_time
                        b.end_time = new_end
                        db_mov.commit()
                        st.success("Jadwal berhasil dipindahkan!")
                        st.rerun()
            finally:
                db_mov.close()

# Schedule Table Header & Control
st.subheader(f"📋 Jadwal Rinci & Nama Pemesan - {selected_date.strftime('%d %B %Y')}")

st.markdown("""
<style>
/* Gigantic Full-Width Toggle Banner Box */
div[data-testid="stToggle"] {
    background: linear-gradient(135deg, rgba(37, 99, 235, 0.45), rgba(30, 58, 138, 0.85)) !important;
    border: 5px solid #60a5fa !important;
    border-radius: 28px !important;
    padding: 50px 60px !important;
    margin: 30px 0 40px 0 !important;
    box-shadow: 0 16px 50px rgba(59, 130, 246, 0.6) !important;
    width: 100% !important;
    min-height: 160px !important;
}
div[data-testid="stToggle"] label {
    display: flex !important;
    align-items: center !important;
    gap: 40px !important;
    width: 100% !important;
}
/* 64px Gigantic Label Text */
div[data-testid="stToggle"] label p,
div[data-testid="stToggle"] label span,
div[data-testid="stToggle"] label div {
    font-size: 64px !important;
    font-weight: 900 !important;
    color: #ffffff !important;
    line-height: 1.25 !important;
}
/* 4.0x Scaled Gigantic Toggle Switch */
div[data-testid="stToggle"] input + div {
    transform: scale(4.0) !important;
    transform-origin: left center !important;
    margin-right: 60px !important;
    flex-shrink: 0 !important;
}
</style>
""", unsafe_allow_html=True)

edit_mode = st.toggle(
    "🛠️ KLIK DI SINI — AKTIFKAN MODE EDIT OWNER (DRAG & DROP JADWAL)",
    value=False,
    help="Aktifkan sakelar ini untuk memindahkan jadwal dengan Drag & Drop atau menghapus reservasi."
)

if not edit_mode:
    # Construct Custom HTML Table (Read-Only Mode)
    html_table = f"""
    <div class="custom-table-container">
        <table class="custom-table">
            <thead>
                <tr>
                    <th style="width: 15%">⏰ Slot Waktu</th>
                    <th style="width: 20%">🎾 {settings.COURT_1_NAME}</th>
                    <th style="width: 25%">👤 Pemesan Lap. A</th>
                    <th style="width: 20%">🎾 {settings.COURT_2_NAME}</th>
                    <th style="width: 25%">👤 Pemesan Lap. B</th>
                </tr>
            </thead>
            <tbody>
    """

    for s in slots:
        if s.court_1_status == "Available":
            c1_badge = '<span class="status-badge status-available">Tersedia</span>'
            c1_name = '<span class="customer-empty-text">-</span>'
        elif s.court_1_status == "Pending Payment":
            c1_badge = '<span class="status-badge status-pending">Pending</span>'
            c1_name = f'<span class="customer-name-text">{s.court_1_customer}</span>'
        else:
            c1_badge = '<span class="status-badge status-booked">Terpesan</span>'
            c1_name = f'<span class="customer-name-text">{s.court_1_customer}</span>'

        if s.court_2_status == "Available":
            c2_badge = '<span class="status-badge status-available">Tersedia</span>'
            c2_name = '<span class="customer-empty-text">-</span>'
        elif s.court_2_status == "Pending Payment":
            c2_badge = '<span class="status-badge status-pending">Pending</span>'
            c2_name = f'<span class="customer-name-text">{s.court_2_customer}</span>'
        else:
            c2_badge = '<span class="status-badge status-booked">Terpesan</span>'
            c2_name = f'<span class="customer-name-text">{s.court_2_customer}</span>'

        html_table += f"""
                <tr>
                    <td><span class="time-slot-badge">{s.time}</span></td>
                    <td>{c1_badge}</td>
                    <td>{c1_name}</td>
                    <td>{c2_badge}</td>
                    <td>{c2_name}</td>
                </tr>
        """

    html_table += """
            </tbody>
        </table>
    </div>
    """
    st.markdown(html_table.replace("\n", "").replace("\r", "").strip(), unsafe_allow_html=True)

else:
    # Native Streamlit Interactive Edit Table (100% Reliable on Mobile HP & Desktop PC)
    st.info("🛠️ **Mode Edit Owner Aktif**: Klik tombol **↔️ Pindah Jadwal** atau **🗑️ Hapus** langsung pada jadwal reservasi yang ingin dikelola. Mode ini 100% didukung penuh di layar HP (Mobile/Touchscreen) maupun Laptop/PC!")

    col_h1, col_h2, col_h3, col_h4, col_h5 = st.columns([1.1, 1.2, 2.7, 1.2, 2.7])
    col_h1.markdown("**⏰ Slot Waktu**")
    col_h2.markdown(f"**🎾 {settings.COURT_1_NAME}**")
    col_h3.markdown("**👤 Pemesan & Aksi Lap. A**")
    col_h4.markdown(f"**🎾 {settings.COURT_2_NAME}**")
    col_h5.markdown("**👤 Pemesan & Aksi Lap. B**")
    st.markdown("---")

    for s in slots:
        c1, c2, c3, c4, c5 = st.columns([1.1, 1.2, 2.7, 1.2, 2.7])
        c1.markdown(f"`{s.time}`")

        # Court 1 Status Badge
        status_c1_label = "🟢 Tersedia" if s.court_1_status == "Available" else ("🟡 Pending" if s.court_1_status == "Pending Payment" else "🔴 Terpesan")
        c2.markdown(status_c1_label)

        # Court 1 Pemesan & Action Buttons inside cell
        with c3:
            if s.court_1_status != "Available" and s.court_1_booking_id:
                st.markdown(f"**👤 {s.court_1_customer}**")
                b1, b2 = st.columns(2)
                if b1.button("↔️ Pindah Jadwal", key=f"mov_c1_{s.time}_{s.court_1_booking_id}", use_container_width=True):
                    show_move_dialog(s.court_1_booking_id, s.court_1_customer or "Customer", 1, s.time, date_str)
                if b2.button("🗑️ Hapus", key=f"del_c1_{s.time}_{s.court_1_booking_id}", use_container_width=True):
                    show_delete_dialog(s.court_1_booking_id, s.court_1_customer or "Customer", settings.COURT_1_NAME, s.time)
            else:
                st.markdown("*-*")

        # Court 2 Status Badge
        status_c2_label = "🟢 Tersedia" if s.court_2_status == "Available" else ("🟡 Pending" if s.court_2_status == "Pending Payment" else "🔴 Terpesan")
        c4.markdown(status_c2_label)

        # Court 2 Pemesan & Action Buttons inside cell
        with c5:
            if s.court_2_status != "Available" and s.court_2_booking_id:
                st.markdown(f"**👤 {s.court_2_customer}**")
                b3, b4 = st.columns(2)
                if b3.button("↔️ Pindah Jadwal", key=f"mov_c2_{s.time}_{s.court_2_booking_id}", use_container_width=True):
                    show_move_dialog(s.court_2_booking_id, s.court_2_customer or "Customer", 2, s.time, date_str)
                if b4.button("🗑️ Hapus", key=f"del_c2_{s.time}_{s.court_2_booking_id}", use_container_width=True):
                    show_delete_dialog(s.court_2_booking_id, s.court_2_customer or "Customer", settings.COURT_2_NAME, s.time)
            else:
                st.markdown("*-*")

        st.markdown("<hr style='margin: 6px 0; border-color: rgba(255,255,255,0.08);'>", unsafe_allow_html=True)


