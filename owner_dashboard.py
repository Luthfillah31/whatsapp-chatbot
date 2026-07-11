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
    <div class="header-title">🎾 Sistem Reservasi Lapangan Tenis Warga</div>
    <div class="header-subtitle">Dashboard Pengurus & Monitoring Jadwal Lapangan Warga Komplek Perumahan</div>
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

# Schedule Table Section
st.subheader(f"📋 Jadwal Rinci & Nama Pemesan - {selected_date.strftime('%d %B %Y')}")

# Construct Custom HTML Table
html_table = f"""
<div class="custom-table-container">
    <table class="custom-table">
        <thead>
            <tr>
                <th style="width: 15%">⏰ Slot Waktu</th>
                <th style="width: 20%">🎾 {settings.COURT_1_NAME}</th>
                <th style="width: 25%">👤 Pemesan Lap. 1</th>
                <th style="width: 20%">🎾 {settings.COURT_2_NAME}</th>
                <th style="width: 25%">👤 Pemesan Lap. 2</th>
            </tr>
        </thead>
        <tbody>
"""

for s in slots:
    # Court 1 Status Badge
    if s.court_1_status == "Available":
        c1_badge = '<span class="status-badge status-available">Tersedia</span>'
        c1_name = '<span class="customer-empty-text">-</span>'
    elif s.court_1_status == "Pending Payment":
        c1_badge = '<span class="status-badge status-pending">Pending</span>'
        c1_name = f'<span class="customer-name-text">{s.court_1_customer}</span>'
    else:
        c1_badge = '<span class="status-badge status-booked">Terpesan</span>'
        c1_name = f'<span class="customer-name-text">{s.court_1_customer}</span>'

    # Court 2 Status Badge
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

# Render premium custom HTML table
# We strip newlines and carriage returns to prevent Markdown from interpreting indented HTML as preformatted code blocks.
st.markdown(html_table.replace("\n", "").replace("\r", "").strip(), unsafe_allow_html=True)

