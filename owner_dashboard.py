import streamlit as st
import datetime
import pandas as pd
from app.models.db_models import SessionLocal
from app.services.calendar_service import get_daily_schedule
from app.config import settings

# Page config with modern title and icon
st.set_page_config(
    page_title="Sistem Reservasi Lapangan Warga - Admin Dashboard",
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
</style>
""", unsafe_allow_html=True)

# Header Section
st.markdown("""
<div class="header-banner">
    <div class="header-title">🎾 Sistem Reservasi Lapangan Tenis Warga</div>
    <div class="header-subtitle">Dashboard Pengurus & Monitoring Jadwal Lapangan Warga Komplek Perumahan</div>
</div>
""", unsafe_allow_html=True)

# Control Panel directly on main dashboard
ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([2, 2, 1])

with ctrl_col1:
    selected_date = st.date_input(
        "📅 Pilih Tanggal Operasional",
        value=datetime.date.today(),
        help="Pilih tanggal untuk memuat jadwal ketersediaan lapangan real-time dari database."
    )
    date_str = selected_date.strftime("%Y-%m-%d")

with ctrl_col2:
    st.markdown("#### ℹ️ Info Operasional Lapangan")
    st.write(f"**Tarif**: GRATIS 100% (Khusus Warga) &nbsp;|&nbsp; **Jam Buka**: {settings.CLUB_OPENING_HOUR} - {settings.CLUB_CLOSING_HOUR} WIB")

with ctrl_col3:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("↻ Segarkan Data", width="stretch", type="primary"):
        st.rerun()

st.markdown("---")

# Fetch Schedule Data from Local Database
db = SessionLocal()
try:
    schedule_data = get_daily_schedule(db, date_str)
finally:
    db.close()

slots = schedule_data.slots

# Calculate Owner KPI Metrics
total_slots = len(slots) * 2
booked_c1 = sum(1 for s in slots if s.court_1_status == "Booked")
booked_c2 = sum(1 for s in slots if s.court_2_status == "Booked")
total_booked = booked_c1 + booked_c2
total_avail = total_slots - total_booked
occupancy_rate = (total_booked / total_slots * 100) if total_slots > 0 else 0.0

# KPI Cards Section
col1, col2, col3, col4 = st.columns(4)

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

with col4:
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-label">Status Fasilitas</div>
        <div class="kpi-value">GRATIS <span style="font-size:1.2rem; color:#34d399;">100%</span></div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# Schedule Table Section
st.subheader(f"📋 Jadwal Rinci & Kontak Pemesan - {selected_date.strftime('%d %B %Y')}")

table_rows = []
for s in slots:
    # Format Court 1 info
    c1_status = "🟢 Tersedia" if s.court_1_status == "Available" else "🔴 Terpesan"
    c1_name = s.court_1_customer if s.court_1_status == "Booked" and s.court_1_customer else "-"
    c1_phone = s.court_1_phone if s.court_1_status == "Booked" and s.court_1_phone else "-"
    
    # Format Court 2 info
    c2_status = "🟢 Tersedia" if s.court_2_status == "Available" else "🔴 Terpesan"
    c2_name = s.court_2_customer if s.court_2_status == "Booked" and s.court_2_customer else "-"
    c2_phone = s.court_2_phone if s.court_2_status == "Booked" and s.court_2_phone else "-"
    
    table_rows.append({
        "⏰ Slot Waktu": s.time,
        f"🎾 {settings.COURT_1_NAME}": c1_status,
        "👤 Pemesan Lap. 1": c1_name,
        "📱 Kontak Lap. 1": c1_phone,
        f"🎾 {settings.COURT_2_NAME}": c2_status,
        "👤 Pemesan Lap. 2": c2_name,
        "📱 Kontak Lap. 2": c2_phone
    })

df_schedule = pd.DataFrame(table_rows)

# Display interactive dataframe with custom styling
st.dataframe(
    df_schedule,
    width="stretch",
    hide_index=True,
    height=550
)

# Footer info
st.markdown("---")
st.caption("🔒 Dashboard Pengurus Komplek - Sistem Reservasi Lapangan Tenis Warga. Data bersumber langsung dari Database SQL waktu nyata.")
