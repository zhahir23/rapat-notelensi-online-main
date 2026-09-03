import os
import wave
import sqlite3
import hashlib
import json
import io
import random
import string
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import pandas as pd
from datetime import datetime
import streamlit as st

try:
    import whisper
except ModuleNotFoundError:
    whisper = None

from cryptography.fernet import Fernet
from PIL import Image
from docx import Document
from audio_recorder_streamlit import audio_recorder
import numpy as np
from scipy.signal import butter, lfilter

# ==========================================
# KONFIGURASI EMAIL SMTP GMAIL (BOT PENGIRIM)
# ==========================================
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

# Satu email kamu/sistem sebagai BOT pengirim
SENDER_EMAIL = "email_bot_sistem@gmail.com" 

# 16 Digit App Password dari akun Google pengirim (Tanpa Spasi)
SENDER_PASSWORD = "abcdefghijklmnop" 

def kirim_email_otp(target_email, otp_code, username):
    """Mengirimkan email OTP ke EMAIL MASING-MASING PENGGUNA (Dinamis)"""
    try:
        msg = MIMEMultipart()
        msg['From'] = f"GovScribe System <{SENDER_EMAIL}>"
        msg['To'] = target_email  # <- Email tujuan sesuai yang diinput pengguna
        msg['Subject'] = f"[{otp_code}] Kode OTP Reset Password"

        body = f"""Halo {username},

Berikut adalah Kode OTP verifikasi Anda untuk reset password:

==============================
KODE OTP: {otp_code}
==============================

Jangan berikan kode ini kepada siapa pun.
"""
        msg.attach(MIMEText(body, 'plain'))

        # Proses pengiriman ke email masing-masing
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=10)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD.replace(" ", "")) 
        server.sendmail(SENDER_EMAIL, target_email, msg.as_string())
        server.quit()
        return True, "Email berhasil dikirim!"
    except Exception as e:
        return False, str(e)

# ==========================================
# SETUP & INTEGRASI SISTEM KEAMANAN (AES-256)
# ==========================================
KEY_FILE = "secret.key"
FACESHOT_DIR = "registered_faces"
PUBLISHED_FILE = "published_notulensi.json"

if not os.path.exists(FACESHOT_DIR):
    os.makedirs(FACESHOT_DIR)

def load_or_generate_key():
    if not os.path.exists(KEY_FILE):
        key = Fernet.generate_key()
        with open(KEY_FILE, "wb") as key_file:
            key_file.write(key)
    else:
        with open(KEY_FILE, "rb") as key_file:
            key = key_file.read()
    return key

SECURITY_KEY = load_or_generate_key()
fernet = Fernet(SECURITY_KEY)

def enkripsi_teks(teks):
    return fernet.encrypt(teks.encode()).decode()

def dekripsi_teks(teks_terenkripsi):
    try:
        return fernet.decrypt(teks_terenkripsi.encode()).decode()
    except Exception:
        return "[Gagal Dekripsi / Kunci Tidak Cocok]"

def simpan_foto_buffer(username, foto_bytes, prefix=""):
    if foto_bytes is not None:
        try:
            foto_bytes.seek(0)
            image = Image.open(foto_bytes)
            if image.mode in ("RGBA", "P"):
                image = image.convert("RGB")
            file_name = f"{prefix}_{username}.jpg" if prefix else f"{username}.jpg"
            foto_path = os.path.join(FACESHOT_DIR, file_name)
            image.save(foto_path, "JPEG", quality=95)
            return foto_path
        except Exception as e:
            st.error(f"Gagal menyimpan foto: {e}")
    return None

# ==========================================
# DATABASE AKUN KARYAWAN & ABSENSI ENKRIPSI
# ==========================================
DB_FILE = "govscribe.db"
USERS_DB_FILE = "users_db.json"
ABSENSI_ENCRYPTED_FILE = "log_absensi_encrypted.csv"


def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nip TEXT UNIQUE NOT NULL,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            email TEXT,
            foto_path TEXT,
            nama TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nip TEXT NOT NULL,
            kegiatan TEXT,
            metode TEXT,
            status TEXT,
            waktu TEXT,
            foto_path TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS published_news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            judul TEXT NOT NULL,
            lokasi TEXT,
            waktu_rilis TEXT,
            poin_utama TEXT,
            isi_artikel TEXT,
            dipublikasikan_oleh TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def seed_default_data():
    init_db()
    conn = get_db_connection()
    existing = conn.execute("SELECT username FROM employees WHERE username = 'admin_setda'").fetchone()
    if existing is None:
        conn.execute(
            "INSERT INTO employees (nip, username, password_hash, email, nama) VALUES (?, ?, ?, ?, ?)",
            (
                "admin_setda",
                "admin_setda",
                hashlib.sha256("admin123".encode()).hexdigest(),
                "admin@setda.local",
                "Administrator Setda"
            )
        )
        conn.execute(
            "INSERT INTO employees (nip, username, password_hash, email, nama) VALUES (?, ?, ?, ?, ?)",
            (
                "pns_19850110",
                "pns_19850110",
                hashlib.sha256("pns_pass_123".encode()).hexdigest(),
                "pns_19850110@gmail.com",
                "Pegawai 19850110"
            )
        )
        conn.execute(
            "INSERT INTO employees (nip, username, password_hash, email, nama) VALUES (?, ?, ?, ?, ?)",
            (
                "pns_19920315",
                "pns_19920315",
                hashlib.sha256("pns_pass_456".encode()).hexdigest(),
                "pns_19920315@gmail.com",
                "Pegawai 19920315"
            )
        )
        conn.execute(
            "INSERT INTO employees (nip, username, password_hash, email, nama) VALUES (?, ?, ?, ?, ?)",
            (
                "220235253",
                "220235253",
                hashlib.sha256("password123".encode()).hexdigest(),
                "220235253@gmail.com",
                "Pegawai 220235253"
            )
        )

    if conn.execute("SELECT COUNT(*) FROM published_news").fetchone()[0] == 0:
        sampel = """# Berita Pemerintah Kabupaten

Dalam kegiatan koordinasi yang berlangsung hari ini, pemerintah menegaskan komitmen untuk mempercepat pelayanan publik dan meningkatkan transparansi data. Kegiatan ini melibatkan seluruh perangkat daerah serta perwakilan stakeholder penting terkait program strategis di wilayah kami.

Poin utama yang dihasilkan adalah peningkatan koordinasi antar satuan kerja, efisiensi pelayanan masyarakat, dan komitmen meningkatkan kualitas tata kelola pemerintahan yang lebih cepat dan akuntabel.
"""
        conn.execute(
            "INSERT INTO published_news (judul, lokasi, waktu_rilis, poin_utama, isi_artikel, dipublikasikan_oleh) VALUES (?, ?, ?, ?, ?, ?)",
            (
                "Evaluasi Pelayanan Publik Daerah",
                "Kantor Setda",
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "• Peningkatan koordinasi antar unit kerja\n• Percepatan pelayanan publik\n• Transparansi data dan dokumen",
                sampel,
                "admin_setda"
            )
        )
    conn.commit()
    conn.close()


def load_users_db():
    init_db()
    conn = get_db_connection()
    rows = conn.execute("SELECT username, password_hash FROM employees").fetchall()
    data = {row["username"]: row["password_hash"] for row in rows}
    conn.close()
    return data


def save_user_to_db(username, password, foto_bytes=None):
    init_db()
    hashed_pwd = hashlib.sha256(password.encode()).hexdigest()
    foto_path = None
    if foto_bytes is not None:
        foto_path = simpan_foto_buffer(username, foto_bytes)

    conn = get_db_connection()
    conn.execute(
        """
        INSERT INTO employees (nip, username, password_hash, email, foto_path, nama)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(username) DO UPDATE SET
            password_hash = excluded.password_hash,
            foto_path = COALESCE(excluded.foto_path, employees.foto_path)
        """,
        (username, username, hashed_pwd, f"{username}@local", foto_path, username)
    )
    conn.commit()
    conn.close()


def update_user_password(username, new_password):
    init_db()
    conn = get_db_connection()
    conn.execute(
        "UPDATE employees SET password_hash = ? WHERE username = ? OR nip = ?",
        (hashlib.sha256(new_password.encode()).hexdigest(), username, username)
    )
    conn.commit()
    conn.close()


def verifikasi_login(username, password):
    users = load_users_db()
    hashed_pwd = hashlib.sha256(password.encode()).hexdigest()
    return users.get(username) == hashed_pwd


def catat_absensi_terenkripsi(nip_username, kegiatan="Kehadiran Rapat", metode="Manual Input", status="Hadir (Tervalidasi)", foto_bytes=None, is_logout=False):
    init_db()
    waktu_sekarang = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    foto_path = None
    if foto_bytes is not None:
        prefix = "out" if is_logout else "in"
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        foto_path = simpan_foto_buffer(f"{nip_username}_{timestamp_str}", foto_bytes, prefix=prefix)

    conn = get_db_connection()
    conn.execute(
        "INSERT INTO attendance (nip, kegiatan, metode, status, waktu, foto_path) VALUES (?, ?, ?, ?, ?, ?)",
        (nip_username, kegiatan, metode, status, waktu_sekarang, foto_path)
    )
    conn.commit()
    conn.close()

    waktu_enc = enkripsi_teks(waktu_sekarang)
    nip_enc = enkripsi_teks(nip_username)
    kegiatan_enc = enkripsi_teks(kegiatan)
    metode_enc = enkripsi_teks(metode)
    status_enc = enkripsi_teks(status)

    data_baru = pd.DataFrame([{
        "Waktu_Encrypted": waktu_enc,
        "NIP_Username_Encrypted": nip_enc,
        "Kegiatan_Encrypted": kegiatan_enc,
        "Metode_Encrypted": metode_enc,
        "Status_Encrypted": status_enc
    }])

    if not os.path.exists(ABSENSI_ENCRYPTED_FILE):
        data_baru.to_csv(ABSENSI_ENCRYPTED_FILE, index=False)
    else:
        data_baru.to_csv(ABSENSI_ENCRYPTED_FILE, mode='a', header=False, index=False)

# ==========================================
# MANAGEMENT PUBLIKASI NOTULENSI
# ==========================================
def load_published_data():
    init_db()
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT * FROM published_news ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def publish_notulensi(judul, lokasi, poin_utama, isi_artikel, publisher):
    init_db()
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO published_news (judul, lokasi, waktu_rilis, poin_utama, isi_artikel, dipublikasikan_oleh) VALUES (?, ?, ?, ?, ?, ?)",
        (
            judul,
            lokasi,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            poin_utama,
            isi_artikel,
            publisher
        )
    )
    conn.commit()
    conn.close()

# ==========================================
# DIALOG MODAL LOGOUT & ABSEN OUT
# ==========================================
@st.dialog("🚪Absen Keluar")
def modal_logout():
    st.write("Silakan verifikasi akun, ambil foto bukti absensi, dan pilih jenis absensi sebelum keluar:")
    
    logout_nip = st.text_input("NIP / Username PNS", value=st.session_state.get("username", ""), key="logout_nip_val")
    logout_pass = st.text_input("Kata Sandi / Password Akun", type="password", key="logout_pass_val")
    opsi_logout = st.radio("PILIH ABSEN KELUAR:", ["Jam ISHOMA", "Jam Pulang"], key="opsi_logout_val")
    
    st.write("📸 **Ambil Foto Bukti Absen Keluar:**")
    logout_photo = st.camera_input("Ambil foto untuk bukti absen keluar", key="logout_cam")
    
    if st.button("Konfirmasi Out & Logout", use_container_width=True):
        if not logout_nip or not logout_pass:
            st.error("NIP dan Password wajib diisi!")
        elif logout_photo is None:
            st.warning("Silakan ambil foto bukti absen keluar terlebih dahulu!")
        elif verifikasi_login(logout_nip, logout_pass):
            status_absen = f"Keluar ({opsi_logout})"
            catat_absensi_terenkripsi(
                nip_username=logout_nip,
                kegiatan="Selesai Tugas / Istirahat",
                metode="Manual Out Form + Camera",
                status=status_absen,
                foto_bytes=logout_photo,
                is_logout=True
            )
            st.session_state["logged_in"] = False
            st.session_state["username"] = ""
            st.success("Absensi Out dan Foto berhasil dicatat! Mengalihkan...")
            st.rerun()
        else:
            st.error("Password salah! Gagal mencatat absensi keluar.")

@st.dialog("Detail Berita Publik", width="large")
def modal_berita(item):
    st.subheader(item['judul'])
    st.markdown(f"*{item['waktu_rilis']}* | **Lokasi:** {item['lokasi']} | **Publisher:** {item['dipublikasikan_oleh']}")
    st.markdown("---")
    st.markdown(item['isi_artikel'])
    if st.button("Tutup Berita"):
        st.session_state[f"show_modal_{item['id']}"] = False
        st.rerun()

# ==========================================
# MODUL PEMBERSIH NOISE & WHISPER AI
# ==========================================
@st.cache_resource
def load_whisper_model():
    if whisper is None:
        raise ModuleNotFoundError("Modul 'whisper' belum terinstal. Jalankan: pip install openai-whisper")
    return whisper.load_model("base")

def terapkan_filter_noise(file_input_path, file_output_path):
    try:
        with wave.open(file_input_path, 'rb') as wf:
            params = wf.getparams()
            nchannels, sampwidth, framerate, nframes = params[:4]
            data = wf.readframes(nframes)
            
        audio_data = np.frombuffer(data, dtype=np.int16)
        lowcut = 300.0
        highcut = 3400.0
        nyq = 0.5 * framerate
        low = lowcut / nyq
        high = highcut / nyq
        b, a = butter(1, [low, high], btype='band')
        filtered_audio = lfilter(b, a, audio_data).astype(np.int16)
        
        with wave.open(file_output_path, 'wb') as wf:
            wf.setparams(params)
            wf.writeframes(filtered_audio.tobytes())
        return file_output_path
    except Exception:
        return file_input_path

def transkripsi_audio(file_path):
    model = load_whisper_model() 
    result = model.transcribe(file_path, language="id", fp16=False)
    return result["text"]

def buat_dokumen_word(judul, isi_teks):
    doc = Document()
    doc.add_heading("NOTULENSI DAN TRANSKRIPSI RAPAT DINAS", level=1)
    doc.add_paragraph(f"Tanggal / Waktu: {datetime.now().strftime('%d %B %Y %H:%M WIB')}")
    doc.add_paragraph(f"Topik / Judul: {judul}")
    doc.add_heading("Hasil Transkripsi Suara:", level=2)
    doc.add_paragraph(isi_teks)
    
    bio = io.BytesIO()
    doc.save(bio)
    bio.seek(0)
    return bio

def ekstrak_poin_masyarakat(teks_notulensi):
    kalimat_list = teks_notulensi.split(". ")
    poin_publik = []
    kata_kunci = ["disetujui", "diputuskan", "sepakat", "diberlakukan", "anggaran", "pelaksanaan", "pembangunan", "resmi"]
    
    for kalimat in kalimat_list:
        if any(kw in kalimat.lower() for kw in kata_kunci):
            poin_publik.append(f"• {kalimat.strip()}")
            
    if not poin_publik:
        poin_publik.append("• Hasil rapat bersifat internal atau belum memuat keputusan publik secara langsung.")
        
    return "\n".join(poin_publik)

def generate_artikel_berita(judul_rapat, lokasi, teks_transkrip, poin_utama):
    waktu_rilis = datetime.now().strftime("%A, %d %B %Y | %H:%M WIB")
    return f"""# {judul_rapat.upper()}

**{lokasi.upper()}** - {waktu_rilis}

Rapat koordinasi resmi mengenai {judul_rapat} telah selesai dilaksanakan dengan menghasilkan sejumlah keputusan strategis yang berdampak pada pelayanan publik.

---
### Poin-Poin Utama Keputusan
{poin_utama}
---
### Laporan Lengkap
Dalam kesempatan tersebut, pimpinan rapat menegaskan arahan utama:
"{teks_transkrip[:500]}..."

Langkah ini diharapkan dapat segera diimplementasikan untuk mendorong efisiensi tata kelola administrasi secara berkelanjutan.
"""

# ==========================================
# ANTARMUKA UTAMA (STREAMLIT DASHBOARD)
# ==========================================
seed_default_data()

st.set_page_config(page_title="GovScribe - Aplikasi Notulensi Rapat Digital", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap');
:root { --navy:#12304a; --blue:#2167a5; --teal:#168a91; --ink:#1d2b36; --muted:#6b7b87; --line:#dce7ed; --paper:#ffffff; --wash:#f3f7f9; }
html, body, [class*="css"] { font-family:'DM Sans', sans-serif; color:var(--ink); }
[data-testid="stAppViewContainer"] { background:var(--wash); }
[data-testid="stAppViewContainer"] h1,
[data-testid="stAppViewContainer"] h2,
[data-testid="stAppViewContainer"] h3,
[data-testid="stAppViewContainer"] h4,
[data-testid="stAppViewContainer"] p,
[data-testid="stAppViewContainer"] label,
[data-testid="stAppViewContainer"] span { color:#111111; }
[data-testid="stSidebar"] { background:var(--navy); border-right:0; }
[data-testid="stSidebar"] * { color:#edf6f8; }
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p { color:#b9d1da; }
[data-testid="stSidebar"] .stRadio label { padding:9px 12px; border-radius:8px; }
[data-testid="stSidebar"] .stRadio label:hover { background:rgba(255,255,255,.10); }
h1, h2, h3, h4 { font-family:'Space Grotesk', sans-serif; letter-spacing:0; color:#111111; }
.brand { display:flex; align-items:center; gap:12px; padding:4px 0 24px; }
.brand-mark { width:42px; height:42px; display:grid; place-items:center; border-radius:12px; background:#ef8a54; color:white; font:700 22px 'Space Grotesk'; }
.brand-name { font:700 20px 'Space Grotesk'; color:white; }
.brand-sub { font-size:11px; color:#b9d1da; margin-top:2px; }
.topbar { display:flex; justify-content:space-between; align-items:center; padding:18px 22px; margin-bottom:22px; background:var(--paper); border:1px solid var(--line); border-radius:12px; }
.eyebrow { color:var(--teal); font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:1.2px; }
.topbar-title { font:600 22px 'Space Grotesk'; color:#111111; margin-top:3px; }
.user-chip { padding:8px 13px; background:#edf6f7; border-radius:20px; color:var(--navy); font-weight:600; font-size:13px; }
.public-header { display:flex; justify-content:space-between; align-items:center; padding:16px 22px; margin-bottom:24px; background:var(--paper); border-bottom:1px solid var(--line); }
.public-brand { display:flex; align-items:center; gap:10px; font:700 20px 'Space Grotesk'; color:var(--navy); }
.public-mark { width:36px; height:36px; display:grid; place-items:center; border-radius:10px; background:#ef8a54; color:white; font:700 19px 'Space Grotesk'; }
.public-kicker { color:var(--muted); font-size:12px; margin-top:2px; }
.login-panel { max-width:720px; margin:12px auto 0; padding:30px 34px 34px; background:var(--paper); border:1px solid var(--line); border-radius:16px; box-shadow:0 18px 45px rgba(18,48,74,.10); }
.login-panel .stTextInput input, .login-panel .stSelectbox [data-baseweb="select"] { background:#f8fbfc; }
.login-note { padding:12px 14px; border-left:3px solid var(--teal); background:#edf7f7; color:var(--muted); font-size:13px; margin:12px 0 18px; }
.hero { padding:26px 28px; border-radius:14px; background:linear-gradient(115deg,#12304a,#2167a5); color:white; margin-bottom:20px; box-shadow:0 12px 28px rgba(18,48,74,.14); }
.hero h2 { color:white; margin:0 0 7px; font-size:26px; }
.hero p { color:#dcecf1; margin:0; max-width:650px; }
.kpi { background:var(--paper); border:1px solid var(--line); border-radius:12px; padding:18px; min-height:112px; box-shadow:0 3px 10px rgba(31,65,83,.04); }
.kpi-label { color:#111111; font-size:12px; font-weight:600; }
.kpi-value { color:#111111; font:700 30px 'Space Grotesk'; margin:8px 0 3px; }
.kpi-note { color:var(--teal); font-size:12px; font-weight:600; }
.section-card { background:var(--paper); border:1px solid var(--line); border-radius:12px; padding:20px; }
.login-shell { max-width:760px; margin:30px auto 0; padding:34px; background:var(--paper); border:1px solid var(--line); border-radius:16px; box-shadow:0 18px 45px rgba(18,48,74,.10); }
.login-head { text-align:center; padding-bottom:14px; }
.login-head h1 { margin:8px 0 5px; font-size:32px; }
.login-head p { color:var(--muted); margin:0; }
.profile-banner { display:flex; align-items:center; gap:18px; padding:24px; border-radius:14px; background:var(--navy); color:white; margin-bottom:18px; }
.profile-avatar { width:68px; height:68px; display:grid; place-items:center; border-radius:50%; background:#ef8a54; color:white; font:700 25px 'Space Grotesk'; }
.profile-banner h2 { color:white; margin:0 0 3px; }
.profile-banner p { color:#c4dce3; margin:0; }
div[data-testid="stMetric"] { background:var(--paper); border:1px solid var(--line); border-radius:12px; padding:12px; }
button[kind="primary"] { background:var(--blue); border-color:var(--blue); }
</style>
""", unsafe_allow_html=True)

if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
if "username" not in st.session_state:
    st.session_state["username"] = ""

# Session States Reset Password & OTP
if "show_forgot_pass" not in st.session_state:
    st.session_state["show_forgot_pass"] = False
if "login_failed" not in st.session_state:
    st.session_state["login_failed"] = False
if "otp_code" not in st.session_state:
    st.session_state["otp_code"] = None
if "otp_verified" not in st.session_state:
    st.session_state["otp_verified"] = False
if "target_reset_nip" not in st.session_state:
    st.session_state["target_reset_nip"] = ""
if "show_employee_login" not in st.session_state:
    st.session_state["show_employee_login"] = False

def get_current_user():
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM employees WHERE username = ? OR nip = ?", (st.session_state.get("username", ""), st.session_state.get("username", ""))).fetchone()
    conn.close()
    return dict(row) if row else {"username": st.session_state.get("username", ""), "nama": "Pegawai GovScribe", "nip": "-", "email": "-"}

def render_brand():
    st.sidebar.markdown("<div class='brand'><div class='brand-mark'>G</div><div><div class='brand-name'>GovScribe</div><div class='brand-sub'>Smart meeting system</div></div></div>", unsafe_allow_html=True)

def render_topbar(title, section="PORTAL DIGITAL PEMERINTAH"):
    user = get_current_user()
    st.markdown(f"<div class='topbar'><div><div class='eyebrow'>{section}</div><div class='topbar-title'>{title}</div></div><div class='user-chip'>● {user.get('nama') or user.get('username')}</div></div>", unsafe_allow_html=True)

def render_public_header():
    header_col, login_col = st.columns([4, 1])
    with header_col:
        st.markdown("<div class='public-header'><div><div class='public-brand'><div class='public-mark'>G</div>GovScribe</div><div class='public-kicker'>Portal informasi rapat pemerintah daerah</div></div></div>", unsafe_allow_html=True)
    with login_col:
        if st.button("Login sebagai pegawai", type="primary", use_container_width=True):
            st.session_state["show_employee_login"] = True
            st.rerun()

def render_dashboard():
    render_topbar("Ringkasan aktivitas rapat", "DASHBOARD")
    st.markdown("<div class='hero'><h2>GovScribe Smart Meeting System</h2><p>Kelola rapat, transkripsi AI, absensi, dan publikasi informasi pemerintah dalam satu ruang kerja terintegrasi.</p></div>", unsafe_allow_html=True)
    conn = get_db_connection()
    total_rapat = conn.execute("SELECT COUNT(*) FROM attendance").fetchone()[0]
    total_berita = conn.execute("SELECT COUNT(*) FROM published_news").fetchone()[0]
    total_pegawai = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
    conn.close()
    kpis = [("Total Aktivitas", total_rapat, "Log absensi tercatat"), ("Berita Terbit", total_berita, "Publikasi resmi"), ("Pegawai Terdaftar", total_pegawai, "Akun aktif"), ("Status Sistem", "Aktif", "Database terlindungi")]
    cols = st.columns(4)
    for col, (label, value, note) in zip(cols, kpis):
        with col:
            st.markdown(f"<div class='kpi'><div class='kpi-label'>{label}</div><div class='kpi-value'>{value}</div><div class='kpi-note'>{note}</div></div>", unsafe_allow_html=True)
    st.markdown("### Aktivitas terbaru")
    left, right = st.columns([1.5, 1], gap="large")
    with left:
        activity = pd.DataFrame({"Bulan": ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun"], "Aktivitas": [8, 12, 10, 18, 16, max(20, total_rapat)]})
        st.bar_chart(activity.set_index("Bulan"), color="#2167a5", height=260)
    with right:
        st.markdown("<div class='section-card'><div class='eyebrow'>AKSI CEPAT</div><h3>Mulai pekerjaan</h3>", unsafe_allow_html=True)
        st.write("Gunakan workspace untuk merekam audio, membuat notulensi, dan menerbitkan hasil rapat.")
        if st.button("Buka workspace rapat", type="primary", use_container_width=True):
            st.session_state["internal_page"] = "Workspace Rapat"
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

def render_profile():
    user = get_current_user()
    render_topbar("Profil pegawai", "AKUN SAYA")
    initials = (user.get("nama") or user.get("username") or "G")[:1].upper()
    st.markdown(f"<div class='profile-banner'><div class='profile-avatar'>{initials}</div><div><h2>{user.get('nama') or 'Pegawai GovScribe'}</h2><p>{user.get('email') or 'Email belum diatur'} · Akun terverifikasi</p></div></div>", unsafe_allow_html=True)
    st.markdown("### Informasi identitas")
    with st.container(border=True):
        col1, col2 = st.columns(2)
        col1.text_input("Nama lengkap", value=user.get("nama") or "", disabled=True)
        col2.text_input("NIP / Username", value=user.get("nip") or user.get("username") or "", disabled=True)
        col1.text_input("Email dinas", value=user.get("email") or "", disabled=True)
        col2.text_input("Peran", value="Administrator / Pegawai", disabled=True)

def render_attendance_page():
    render_topbar("Riwayat absensi dan keamanan", "ADMINISTRASI")
    st.title("Proteksi database absensi")
    st.caption("Seluruh log absensi tersimpan dalam bentuk terenkripsi.")
    if os.path.exists(ABSENSI_ENCRYPTED_FILE):
        df_encrypted = pd.read_csv(ABSENSI_ENCRYPTED_FILE)
        df_decrypted = df_encrypted.copy()
        df_decrypted["Waktu_Asli"] = df_encrypted["Waktu_Encrypted"].apply(dekripsi_teks)
        df_decrypted["NIP_Username_Asli"] = df_encrypted["NIP_Username_Encrypted"].apply(dekripsi_teks)
        df_decrypted["Kegiatan_Asli"] = df_encrypted["Kegiatan_Encrypted"].apply(dekripsi_teks)
        df_decrypted["Metode_Asli"] = df_encrypted["Metode_Encrypted"].apply(dekripsi_teks)
        df_decrypted["Status_Asli"] = df_encrypted["Status_Encrypted"].apply(dekripsi_teks)
        st.dataframe(df_decrypted[["Waktu_Asli", "NIP_Username_Asli", "Kegiatan_Asli", "Metode_Asli", "Status_Asli"]], use_container_width=True)
    else:
        st.info("Belum ada log absensi terenkripsi yang tercatat.")

def render_public_portal():
    render_public_header()
    st.title("Portal Berita Publik")
    st.caption("Berita dan kegiatan resmi yang dipublikasikan oleh pegawai dan perangkat daerah.")

    published_items = load_published_data()
    if not published_items:
        st.info("Belum ada berita yang dipublikasikan untuk umum.")
        return

    for item in published_items:
        with st.container(border=True):
            st.markdown(f"## {item['judul']}")
            st.caption(f"📍 {item['lokasi']} | 🕒 {item['waktu_rilis']} | 👤 {item['dipublikasikan_oleh']}")
            st.markdown((item['isi_artikel'] or '')[:500] + "...")
            if st.button(f"Baca Selengkapnya - {item['judul']}", key=f"public_{item['id']}"):
                st.session_state[f"public_modal_{item['id']}"] = True

        if st.session_state.get(f"public_modal_{item['id']}"):
            modal_berita(item)


def render_login_page():
    st.markdown("<div class='login-panel'><div class='login-head'><div class='brand-mark' style='margin:auto'>G</div><h1>Login pegawai</h1><p>Government meeting management system</p></div></div>", unsafe_allow_html=True)
    st.markdown("<div class='login-note'>Gunakan NIP atau username dinas untuk mengakses ruang kerja rapat dan absensi digital.</div>", unsafe_allow_html=True)
    st.caption("Masuk untuk mengelola rapat, transkripsi, absensi, dan publikasi informasi resmi.")

    if st.session_state["show_forgot_pass"]:
        st.subheader("🔑 Reset Password via Kirim OTP ke Gmail")

        if not st.session_state["otp_code"]:
            st.info("Masukkan NIP dan alamat Gmail Anda yang aktif untuk menerima Kode OTP.")
            reset_nip = st.text_input("Masukkan NIP / Username", value=st.session_state.get("target_reset_nip", ""))
            user_email = st.text_input("Masukkan Email Gmail Anda (contoh: user@gmail.com)")

            col_b1, col_b2 = st.columns([1, 4])
            with col_b1:
                if st.button("📧 Kirim OTP ke Gmail", type="primary"):
                    users_db = load_users_db()
                    if not reset_nip or not user_email:
                        st.warning("NIP dan Email wajib diisi!")
                    elif reset_nip not in users_db:
                        st.error("NIP/Username tidak terdaftar dalam database!")
                    else:
                        generated_otp = "".join(random.choices(string.digits, k=6))

                        with st.spinner("Mengirimkan email OTP via Gmail..."):
                            sukses, pesan = kirim_email_otp(user_email, generated_otp, reset_nip)

                        if sukses:
                            st.session_state["otp_code"] = generated_otp
                            st.session_state["target_reset_nip"] = reset_nip
                            st.success(f"✅ Kode OTP berhasil dikirimkan ke **{user_email}**! Silakan periksa Kotak Masuk / Spam Gmail Anda.")
                            st.rerun()
                        else:
                            st.error(f"Gagal mengirim email OTP: {pesan}")
                            st.caption("💡 Pastikan SENDER_EMAIL & SENDER_PASSWORD (App Password) di kode Python sudah dikonfigurasi dengan benar.")

            with col_b2:
                if st.button("Kembali ke Login"):
                    st.session_state["show_forgot_pass"] = False
                    st.session_state["login_failed"] = False
                    st.rerun()

        elif st.session_state["otp_code"] and not st.session_state["otp_verified"]:
            st.info(f"Kode OTP telah dikirimkan. Masukkan 6-digit Kode OTP yang Anda terima di Gmail untuk NIP **{st.session_state['target_reset_nip']}**.")
            input_otp = st.text_input("Masukkan Kode OTP dari Gmail", max_chars=6)

            col_o1, col_o2 = st.columns([1, 4])
            with col_o1:
                if st.button("Verifikasi OTP", type="primary"):
                    if input_otp == st.session_state["otp_code"]:
                        st.session_state["otp_verified"] = True
                        st.success("Kode OTP Cocok! Silakan atur kata sandi baru Anda.")
                        st.rerun()
                    else:
                        st.error("Kode OTP salah atau tidak sesuai!")
            with col_o2:
                if st.button("Batal / Kirim Ulang"):
                    st.session_state["otp_code"] = None
                    st.rerun()

        elif st.session_state["otp_verified"]:
            st.success(f"🔓 Verifikasi Berhasil untuk NIP: **{st.session_state['target_reset_nip']}**")
            st.subheader("Buat Password Baru")

            new_pass = st.text_input("Masukkan Password / PIN Baru", type="password")
            confirm_new_pass = st.text_input("Konfirmasi Password / PIN Baru", type="password")

            if st.button("Simpan Password Baru", type="primary", use_container_width=True):
                if not new_pass:
                    st.warning("Password baru tidak boleh kosong!")
                elif new_pass != confirm_new_pass:
                    st.error("Konfirmasi password tidak cocok!")
                else:
                    update_user_password(st.session_state["target_reset_nip"], new_pass)
                    st.success("🎉 Password berhasil diperbarui! Mengalihkan ke halaman login utama...")

                    st.session_state["show_forgot_pass"] = False
                    st.session_state["login_failed"] = False
                    st.session_state["otp_code"] = None
                    st.session_state["otp_verified"] = False
                    st.session_state["target_reset_nip"] = ""
                    st.rerun()

        return

    tab_manual, tab_register = st.tabs([
        "⌨️ Absensi Manual",
        "📝 Pendaftaran Karyawan Baru"
    ])

    with tab_manual:
        st.subheader("Absensi Manual (NIP & Password)")

        col_m1, col_m2 = st.columns(2)
        with col_m1:
            nip_input = st.text_input("NIP / Username PNS", key="manual_nip")
            password_input = st.text_input("Password / PIN", type="password", key="manual_pass")
            kegiatan_manual = st.selectbox("Agenda / Kegiatan", ["Rapat Internal Setda", "Pelayanan Publik", "Rapat Pleno Daerah"], key="keg_manual")

            if st.button("Submit Absensi Manual"):
                users_db = load_users_db()
                if nip_input in users_db:
                    if verifikasi_login(nip_input, password_input):
                        catat_absensi_terenkripsi(nip_input, kegiatan_manual, metode="Manual Input", status="Hadir (Tervalidasi)")
                        st.session_state["logged_in"] = True
                        st.session_state["username"] = nip_input
                        st.session_state["login_failed"] = False
                        st.success("Absensi Manual Berhasil! Data Anda telah DIENKRIPSI.")
                        st.rerun()
                    else:
                        st.session_state["login_failed"] = True
                        st.session_state["target_reset_nip"] = nip_input
                else:
                    st.error("NIP/Username tidak terdaftar! Silakan mendaftar terlebih dahulu.")

            if st.session_state["login_failed"]:
                st.error("Password/PIN salah!")
                if st.button("🔑 Lupa Password? Klik di sini untuk Reset Password via Email Gmail"):
                    st.session_state["show_forgot_pass"] = True
                    st.rerun()

    with tab_register:
        st.subheader("Formulir Registrasi Karyawan PNS Baru")
        st.caption("Lengkapi data identitas dan verifikasi wajah untuk membuat akun baru.")

        col_r1, col_r2 = st.columns([1, 1], gap="large")

        with col_r1:
            st.markdown("### 📋 Data Akses & Identitas")
            reg_nip = st.text_input("NIP / Username PNS Baru", key="reg_nip", placeholder="Contoh: 19950101...")
            reg_email = st.text_input("Alamat Email Gmail Aktif", key="reg_email", placeholder="nama@gmail.com")
            reg_pass = st.text_input("Buat Password / PIN Baru", type="password", key="reg_pass")
            reg_pass_confirm = st.text_input("Konfirmasi Password / PIN", type="password", key="reg_pass_confirm")

        with col_r2:
            st.markdown("### 📸 Verifikasi Wajah")
            st.caption("Pastikan wajah terlihat jelas dan berada di area terang.")
            reg_photo = st.camera_input("Ambil foto wajah untuk verifikasi pendaftaran", key="reg_cam")

        st.divider()

        if st.button("✨ Daftar Karyawan Baru", type="primary", use_container_width=True):
            users_db = load_users_db()
            if not reg_nip or not reg_pass or not reg_email:
                st.warning("⚠️ NIP, Email, dan Password wajib diisi!")
            elif reg_nip in users_db:
                st.error("❌ NIP/Username ini sudah terdaftar dalam sistem!")
            elif reg_pass != reg_pass_confirm:
                st.error("❌ Konfirmasi password tidak cocok!")
            elif reg_photo is None:
                st.warning("📷 Silakan ambil foto wajah terlebih dahulu!")
            else:
                save_user_to_db(reg_nip, reg_pass, reg_photo)
                st.success(f"🎉 Pendaftaran Berhasil! NIP {reg_nip} telah terdaftar ke dalam sistem.")

# ------------------------------------------
# ROUTING HALAMAN:
# 1. Publik tanpa login melihat portal berita
# 2. Pegawai/admin masuk ke login internal
# ------------------------------------------
if not st.session_state["logged_in"]:
    if st.session_state["show_employee_login"]:
        render_login_page()
        back_col, _ = st.columns([1, 4])
        with back_col:
            if st.button("Kembali ke portal berita"):
                st.session_state["show_employee_login"] = False
                st.session_state["show_forgot_pass"] = False
                st.rerun()
    else:
        render_public_portal()
else:
    render_brand()
    if "internal_page" not in st.session_state:
        st.session_state["internal_page"] = "Dashboard"
    st.sidebar.markdown("<div class='eyebrow' style='color:#8fd0d0'>MENU UTAMA</div>", unsafe_allow_html=True)
    internal_page = st.sidebar.radio(
        "Navigasi internal",
        ["Dashboard", "Workspace Rapat", "Portal Berita", "Absensi & Keamanan", "Profil"],
        index=["Dashboard", "Workspace Rapat", "Portal Berita", "Absensi & Keamanan", "Profil"].index(st.session_state["internal_page"]),
        label_visibility="collapsed"
    )
    st.session_state["internal_page"] = internal_page

    st.sidebar.divider()
    if st.sidebar.button("Keluar dan absen", use_container_width=True):
        modal_logout()

    if internal_page == "Dashboard":
        render_dashboard()
        st.stop()
    if internal_page == "Profil":
        render_profile()
        st.stop()
    if internal_page == "Portal Berita":
        render_public_portal()
        st.stop()
    if internal_page == "Absensi & Keamanan":
        render_attendance_page()
        st.stop()

    render_topbar("Workspace rapat dan publikasi", "WORKSPACE")
    st.title("Notulensi rapat digital")
    
    tab1, tab2, tab3, tab4 = st.tabs([
        "1. Audio & Transkripsi (Perekam Langsung)", 
        "2. Poin Masyarakat & Berita", 
        "3. Portal Berita Publik",
        "4. Keamanan Database Absensi PNS"
    ])
    
    with tab1:
        st.header("Perekam Suara & Transkripsi Otomatis")
        col_rec1, col_rec2 = st.columns(2)
        
        with col_rec1:
            st.write("🎙️ **Klik ikon mikrofon di bawah untuk mulai/berhenti merekam:**")
            audio_bytes = audio_recorder(
                text="Klik untuk rekam",
                recording_color="#e84c3d",
                neutral_color="#6aa84f",
                icon_name="microphone",
                icon_size="2x",
            )
            
        with col_rec2:
            st.write("📁 **Atau unggah file audio jika sudah ada:**")
            uploaded_file = st.file_uploader("Unggah File Audio (.wav / .mp3)", type=["wav", "mp3"])

        active_audio_bytes = None
        file_extension = "wav"

        if audio_bytes:
            active_audio_bytes = audio_bytes
        elif uploaded_file is not None:
            active_audio_bytes = uploaded_file.read()
            file_extension = uploaded_file.name.split(".")[-1]

        if active_audio_bytes:
            temp_raw_path = f"temp_raw.{file_extension}"
            temp_filtered_path = "temp_clean.wav"

            with open(temp_raw_path, "wb") as f:
                f.write(active_audio_bytes)

            st.audio(active_audio_bytes, format="audio/wav")

            if st.button("⚡ Proses & Deteksi Teks (Reduksi Noise)"):
                with st.spinner("Pembersihan noise & transkripsi suara..."):
                    if file_extension == "wav":
                        clean_audio_path = terapkan_filter_noise(temp_raw_path, temp_filtered_path)
                    else:
                        clean_audio_path = temp_raw_path

                    transkrip_raw = transkripsi_audio(clean_audio_path)
                    st.session_state["transkrip_raw"] = transkrip_raw
                    st.session_state["transkrip_encrypted"] = enkripsi_teks(transkrip_raw)
                    st.session_state["audio_bytes"] = active_audio_bytes
                    st.success("Transkripsi Selesai!")

                    if os.path.exists(temp_raw_path): 
                        os.remove(temp_raw_path)
                    if os.path.exists(temp_filtered_path): 
                        os.remove(temp_filtered_path)

        if "transkrip_raw" in st.session_state:
            st.divider()
            st.subheader("📝 Hasil Transkripsi Teks Rapat:")
            st.text_area("Hasil Teks Deteksi", st.session_state["transkrip_raw"], height=200)

            col_d1, col_d2, col_d3 = st.columns(3)
            with col_d1:
                st.download_button("📄 Unduh Teks (.txt)", data=st.session_state["transkrip_raw"], file_name="Transkrip.txt", mime="text/plain")
            with col_d2:
                docx_file = buat_dokumen_word("Rapat Dinas PNS", st.session_state["transkrip_raw"])
                st.download_button("📝 Unduh Word (.docx)", data=docx_file, file_name="Notulensi.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            with col_d3:
                if "audio_bytes" in st.session_state:
                    st.download_button("🎵 Unduh Audio (.wav)", data=st.session_state["audio_bytes"], file_name="Rekaman.wav", mime="audio/wav")

    with tab2:
        st.header("Ekstraksi Poin Publik & Artikel Berita")
        if "transkrip_raw" not in st.session_state:
            st.warning("Lakukan perekaman di Tab 1 terlebih dahulu.")
        else:
            col_a, col_b = st.columns(2)
            with col_a:
                judul_rapat = st.text_input("Judul/Topik Rapat", "Evaluasi Layanan Publik Pemko")
                lokasi_rapat = st.text_input("Lokasi Rapat", "Kantor Wali Kota")
                
            if st.button("Generate Poin Publik & Berita"):
                teks_raw = st.session_state["transkrip_raw"]
                poin_publik = ekstrak_poin_masyarakat(teks_raw)
                st.session_state["poin_publik"] = poin_publik
                st.session_state["judul_rapat"] = judul_rapat
                st.session_state["lokasi_rapat"] = lokasi_rapat
                st.session_state["artikel_berita"] = generate_artikel_berita(judul_rapat, lokasi_rapat, teks_raw, poin_publik)

            if "poin_publik" in st.session_state:
                edit_poin = st.text_area("Edit Poin Keputusan", st.session_state["poin_publik"], height=120)
                edit_artikel = st.text_area("Edit Artikel Berita", st.session_state["artikel_berita"], height=250)
                
                if st.button("📢 Publish Notulensi ke Masyarakat Now", type="primary", use_container_width=True):
                    publish_notulensi(
                        judul=st.session_state.get("judul_rapat", "Rapat Dinas"),
                        lokasi=st.session_state.get("lokasi_rapat", "Kantor Pusat"),
                        poin_utama=edit_poin,
                        isi_artikel=edit_artikel,
                        publisher=st.session_state.get("username", "Admin")
                    )
                    st.balloons()
                    st.success("🎉 Notulensi Berhasil Dipublikasikan ke Portal Berita Masyarakat!")

    with tab3:
        st.header("📰 PORTAL BERITA RESMI")
        published_items = load_published_data()
        if not published_items:
            st.info("Belum ada berita yang dipublikasikan.")
        else:
            for item in published_items:
                with st.container(border=True):
                    col_b1, col_b2 = st.columns([1, 3])
                    with col_b1:
                        st.image("https://via.placeholder.com/300x200?text=GovNews+Official", use_container_width=True)
                        st.caption(f"📅 {item['waktu_rilis']}")
                    with col_b2:
                        st.subheader(item['judul'])
                        st.write(f"**Lokasi:** {item['lokasi']} | **Reporter:** {item['dipublikasikan_oleh']}")
                        st.markdown((item['isi_artikel'] or '')[:220] + "...")
                        if st.button("Baca Selengkapnya", key=f"btn_{item['id']}"):
                            st.session_state[f"show_modal_{item['id']}"] = True

                if st.session_state.get(f"show_modal_{item['id']}"):
                    modal_berita(item)

    with tab4:
        st.header("🛡️ Proteksi Database Absensi PNS")
        if os.path.exists(ABSENSI_ENCRYPTED_FILE):
            df_encrypted = pd.read_csv(ABSENSI_ENCRYPTED_FILE)
            df_decrypted = df_encrypted.copy()
            df_decrypted["Waktu_Asli"] = df_encrypted["Waktu_Encrypted"].apply(dekripsi_teks)
            df_decrypted["NIP_Username_Asli"] = df_encrypted["NIP_Username_Encrypted"].apply(dekripsi_teks)
            df_decrypted["Kegiatan_Asli"] = df_encrypted["Kegiatan_Encrypted"].apply(dekripsi_teks)
            df_decrypted["Metode_Asli"] = df_encrypted["Metode_Encrypted"].apply(dekripsi_teks)
            df_decrypted["Status_Asli"] = df_encrypted["Status_Encrypted"].apply(dekripsi_teks)
            
            st.dataframe(df_decrypted[["Waktu_Asli", "NIP_Username_Asli", "Kegiatan_Asli", "Metode_Asli", "Status_Asli"]], use_container_width=True)
        else:
            st.info("Belum ada log absensi terenkripsi yang tercatat.")