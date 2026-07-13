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
    # Interactive HTML5 Drag and Drop Schedule Board
    st.info("🛠️ **Mode Edit Owner Aktif (Drag & Drop Interaktif)**: Tekan & tahan kartu reservasi, geser (drag), lalu lepas (drop) ke slot waktu/lapangan yang diinginkan. Anda juga dapat menekan tombol **🗑️ Hapus**.")

    import json
    slots_json = []
    for s in slots:
        slots_json.append({
            "time": s.time,
            "c1_status": s.court_1_status,
            "c1_id": s.court_1_booking_id,
            "c1_customer": s.court_1_customer or "Customer",
            "c2_status": s.court_2_status,
            "c2_id": s.court_2_booking_id,
            "c2_customer": s.court_2_customer or "Customer",
        })

    dnd_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
      body {{
        font-family: 'Inter', sans-serif;
        background: #0f172a;
        color: #f1f5f9;
        margin: 0;
        padding: 0;
      }}
      .board-table {{
        width: 100%;
        border-collapse: collapse;
      }}
      .board-table th {{
        background: #1e293b;
        padding: 14px;
        font-size: 0.85rem;
        text-transform: uppercase;
        color: #94a3b8;
        border-bottom: 2px solid rgba(255,255,255,0.1);
        text-align: left;
      }}
      .board-table td {{
        padding: 12px;
        border-bottom: 1px solid rgba(255,255,255,0.05);
        vertical-align: middle;
      }}
      .time-badge {{
        background: rgba(96,165,250,0.15);
        color: #60a5fa;
        padding: 6px 12px;
        border-radius: 6px;
        font-weight: 700;
        font-size: 0.95rem;
      }}
      .drop-zone {{
        min-height: 48px;
        border: 2px dashed rgba(255,255,255,0.1);
        border-radius: 8px;
        display: flex;
        align-items: center;
        justify-content: center;
        color: #10b981;
        background: rgba(16,185,129,0.05);
        font-size: 0.85rem;
        font-weight: 600;
        transition: all 0.2s;
      }}
      .drop-zone.drag-over {{
        border-color: #60a5fa;
        background: rgba(96,165,250,0.2);
        transform: scale(1.02);
      }}
      .drag-card {{
        background: linear-gradient(135deg, #1e293b, #334155);
        border: 1px solid #475569;
        border-radius: 8px;
        padding: 10px 14px;
        cursor: grab;
        display: flex;
        justify-content: space-between;
        align-items: center;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
        transition: transform 0.15s;
      }}
      .drag-card:active {{
        cursor: grabbing;
      }}
      .drag-card:hover {{
        border-color: #60a5fa;
      }}
      .card-info {{
        font-weight: 600;
        font-size: 0.95rem;
        color: #f8fafc;
      }}
      .drag-hint {{
        font-size: 0.75rem;
        color: #94a3b8;
        display: block;
      }}
      .btn-del {{
        background: rgba(239,68,68,0.2);
        color: #ef4444;
        border: 1px solid rgba(239,68,68,0.3);
        padding: 6px 10px;
        border-radius: 6px;
        font-weight: 600;
        cursor: pointer;
      }}
      .btn-del:hover {{
        background: #ef4444;
        color: white;
      }}
      .modal-overlay {{
        position: fixed;
        top: 0; left: 0; right: 0; bottom: 0;
        background: rgba(0,0,0,0.75);
        display: none;
        align-items: center;
        justify-content: center;
        z-index: 9999;
      }}
      .modal-box {{
        background: #1e293b;
        border: 1px solid #475569;
        border-radius: 12px;
        padding: 24px;
        max-width: 420px;
        width: 90%;
        box-shadow: 0 10px 25px rgba(0,0,0,0.5);
      }}
      .modal-box h3 {{
        margin-top: 0;
        color: #60a5fa;
      }}
      .modal-buttons {{
        display: flex;
        gap: 12px;
        margin-top: 20px;
      }}
      .btn-confirm {{
        flex: 1;
        background: #3b82f6;
        color: white;
        border: none;
        padding: 10px;
        border-radius: 8px;
        font-weight: 600;
        cursor: pointer;
      }}
      .btn-cancel {{
        flex: 1;
        background: #334155;
        color: #cbd5e1;
        border: none;
        padding: 10px;
        border-radius: 8px;
        font-weight: 600;
        cursor: pointer;
      }}
    </style>
    </head>
    <body>
      <table class="board-table">
        <thead>
          <tr>
            <th style="width: 14%">⏰ Slot Waktu</th>
            <th style="width: 43%">🎾 {settings.COURT_1_NAME}</th>
            <th style="width: 43%">🎾 {settings.COURT_2_NAME}</th>
          </tr>
        </thead>
        <tbody id="boardBody"></tbody>
      </table>

      <!-- Modal -->
      <div id="modalOverlay" class="modal-overlay">
        <div class="modal-box">
          <h3 id="modalTitle">Konfirmasi Pindah Jadwal</h3>
          <p id="modalDesc"></p>
          <div class="modal-buttons">
            <button class="btn-cancel" onclick="closeModal()">❌ Batal</button>
            <button id="btnConfirm" class="btn-confirm">✅ Ya, Pindahkan</button>
          </div>
        </div>
      </div>

      <script>
        const slots = {json.dumps(slots_json)};
        let activeAction = null;

        function renderBoard() {{
          const tbody = document.getElementById("boardBody");
          tbody.innerHTML = "";
          slots.forEach(s => {{
            const tr = document.createElement("tr");
            tr.innerHTML = `<td><span class="time-badge">${{s.time}}</span></td>`;

            const td1 = document.createElement("td");
            td1.appendChild(renderCell(s.c1_status, s.c1_id, s.c1_customer, 1, s.time));
            tr.appendChild(td1);

            const td2 = document.createElement("td");
            td2.appendChild(renderCell(s.c2_status, s.c2_id, s.c2_customer, 2, s.time));
            tr.appendChild(td2);

            tbody.appendChild(tr);
          }});
        }}

        function renderCell(status, id, customer, courtId, time) {{
          if (status !== "Available" && id) {{
            const card = document.createElement("div");
            card.className = "drag-card";
            card.draggable = true;
            card.ondragstart = (e) => dragStart(e, id, customer, courtId, time);
            card.innerHTML = `
              <div>
                <span class="card-info">👤 ${{customer}}</span>
                <span class="drag-hint">✋ Tekan & geser untuk pindah</span>
              </div>
              <button class="btn-del" onclick="showDeleteModal(${{id}}, '${{customer}}', ${{courtId}}, '${{time}}')">🗑️ Hapus</button>
            `;
            return card;
          }} else {{
            const zone = document.createElement("div");
            zone.className = "drop-zone";
            zone.ondragover = (e) => dragOver(e, zone);
            zone.ondragleave = (e) => dragLeave(e, zone);
            zone.ondrop = (e) => dropSlot(e, zone, courtId, time);
            zone.innerHTML = "🟢 Tersedia (Lepas di sini)";
            return zone;
          }}
        }}

        let draggedData = null;

        function dragStart(e, id, customer, oldCourt, oldTime) {{
          draggedData = {{ id, customer, oldCourt, oldTime }};
          e.dataTransfer.effectAllowed = "move";
        }}

        function dragOver(e, el) {{
          e.preventDefault();
          el.classList.add("drag-over");
        }}

        function dragLeave(e, el) {{
          el.classList.remove("drag-over");
        }}

        function dropSlot(e, el, newCourt, newTime) {{
          e.preventDefault();
          el.classList.remove("drag-over");
          if (!draggedData) return;
          if (draggedData.oldCourt === newCourt && draggedData.oldTime === newTime) return;

          activeAction = {{
            type: "move",
            id: draggedData.id,
            newCourt: newCourt,
            newTime: newTime
          }};

          const courtName = newCourt === 1 ? "Lap. A" : "Lap. B";
          const oldCourtName = draggedData.oldCourt === 1 ? "Lap. A" : "Lap. B";
          document.getElementById("modalTitle").innerText = "↔️ Konfirmasi Pindah Jadwal";
          document.getElementById("modalDesc").innerHTML = `
            Apakah Anda yakin ingin memindahkan reservasi ini?<br><br>
            👤 <b>Pemesan</b>: ${{draggedData.customer}}<br>
            📍 <b>Dari</b>: ${{oldCourtName}} (${{draggedData.oldTime}})<br>
            🎯 <b>Ke</b>: ${{courtName}} (${{newTime}})
          `;
          document.getElementById("btnConfirm").innerText = "✅ Ya, Pindahkan";
          document.getElementById("modalOverlay").style.display = "flex";
        }}

        function showDeleteModal(id, customer, courtId, time) {{
          const courtName = courtId === 1 ? "Lap. A" : "Lap. B";
          activeAction = {{ type: "delete", id: id }};
          document.getElementById("modalTitle").innerText = "⚠️ Konfirmasi Hapus Reservasi";
          document.getElementById("modalDesc").innerHTML = `
            Apakah Anda yakin ingin menghapus reservasi ini secara permanen?<br><br>
            👤 <b>Pemesan</b>: ${{customer}}<br>
            📍 <b>Jadwal</b>: ${{courtName}} (${{time}})
          `;
          document.getElementById("btnConfirm").innerText = "🗑️ Ya, Hapus";
          document.getElementById("modalOverlay").style.display = "flex";
        }}

        function closeModal() {{
          document.getElementById("modalOverlay").style.display = "none";
          activeAction = null;
        }}

        document.getElementById("btnConfirm").onclick = function() {{
          if (!activeAction) return;
          if (activeAction.type === "move") {{
            window.parent.location.search = "?action=move&id=" + activeAction.id + "&court=" + activeAction.newCourt + "&time=" + activeAction.newTime;
          }} else if (activeAction.type === "delete") {{
            window.parent.location.search = "?action=delete&id=" + activeAction.id;
          }}
        }};

        renderBoard();
      </script>
    </body>
    </html>
    """

    components.html(dnd_html, height=750, scrolling=True)


