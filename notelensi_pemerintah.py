import os
import io
import base64
import wave
import sqlite3
import hashlib
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

try:
    import cv2  
except ModuleNotFoundError:
    cv2 = None

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


def load_email_setting(name):
    value = os.getenv(name)
    if value:
        return value
    try:
        return st.secrets.get(name, "")
    except Exception:
        return ""


SENDER_EMAIL = load_email_setting("SENDER_EMAIL")
SENDER_PASSWORD = load_email_setting("SENDER_PASSWORD")


def kirim_email_otp(target_email, otp_code, nama_penerima, tujuan="reset"):
    """Mengirimkan email OTP ke EMAIL MASING-MASING PENGGUNA (Dinamis).
    tujuan: 'reset' untuk reset password, 'registrasi' untuk verifikasi email pendaftaran."""
    if not SENDER_EMAIL or not SENDER_PASSWORD:
        return False, "Konfigurasi SENDER_EMAIL dan SENDER_PASSWORD belum diatur."
    try:
        msg = MIMEMultipart()
        msg['From'] = f"GovScribe System <{SENDER_EMAIL}>"
        msg['To'] = target_email

        if tujuan == "registrasi":
            msg['Subject'] = f"[{otp_code}] Verifikasi Email Pendaftaran GovScribe"
            body = f"""Halo {nama_penerima},

Terima kasih telah mendaftar di GovScribe. Berikut adalah Kode OTP untuk memverifikasi
alamat email Anda dan menyelesaikan proses pendaftaran akun:

==============================
KODE OTP: {otp_code}
==============================

Masukkan kode ini pada halaman pendaftaran GovScribe.
Jangan berikan kode ini kepada siapa pun.
"""
        else:
            msg['Subject'] = f"[{otp_code}] Kode OTP Reset Password"
            body = f"""Halo {nama_penerima},

Berikut adalah Kode OTP untuk mereset kata sandi akun GovScribe Anda:

==============================
KODE OTP: {otp_code}
==============================

Jangan berikan kode ini kepada siapa pun.
"""

        msg.attach(MIMEText(body, 'plain'))

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

if not os.path.exists(FACESHOT_DIR):
    os.makedirs(FACESHOT_DIR)


def load_or_generate_key():
    configured_key = load_email_setting("FERNET_KEY")
    if configured_key:
        key = configured_key.encode("ascii")
    elif os.path.exists(KEY_FILE):
        with open(KEY_FILE, "rb") as key_file:
            key = key_file.read().strip()
    else:
        key = Fernet.generate_key()

    try:
        Fernet(key)
    except (ValueError, TypeError):
        key = Fernet.generate_key()

    with open(KEY_FILE, "wb") as key_file:
        key_file.write(key)
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
            if hasattr(foto_bytes, "seek"):
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


def deteksi_wajah_valid(foto_bytes):
    """Mengembalikan True jika minimal satu wajah manusia terdeteksi jelas pada foto.
    Jika modul opencv tidak tersedia di environment, validasi dilewati (selalu True)."""
    if cv2 is None:
        return True
    try:
        if hasattr(foto_bytes, "seek"):
            foto_bytes.seek(0)
        image = Image.open(foto_bytes).convert("RGB")
        img_array = np.array(image)
        gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        face_cascade = cv2.CascadeClassifier(cascade_path)
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6, minSize=(80, 80))
        if hasattr(foto_bytes, "seek"):
            foto_bytes.seek(0)
        return len(faces) > 0
    except Exception:
        return True


# ==========================================
# DATABASE AKUN KARYAWAN & ABSENSI ENKRIPSI
# ==========================================
DB_FILE = "govscribe.db"
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
            ("admin_setda", "admin_setda", hashlib.sha256("admin123".encode()).hexdigest(), "admin@setda.local", "Administrator Setda")
        )
        conn.execute(
            "INSERT INTO employees (nip, username, password_hash, email, nama) VALUES (?, ?, ?, ?, ?)",
            ("pns_19850110", "pns_19850110", hashlib.sha256("pns_pass_123".encode()).hexdigest(), "pns_19850110@gmail.com", "Pegawai 19850110")
        )
        conn.execute(
            "INSERT INTO employees (nip, username, password_hash, email, nama) VALUES (?, ?, ?, ?, ?)",
            ("pns_19920315", "pns_19920315", hashlib.sha256("pns_pass_456".encode()).hexdigest(), "pns_19920315@gmail.com", "Pegawai 19920315")
        )
        conn.execute(
            "INSERT INTO employees (nip, username, password_hash, email, nama) VALUES (?, ?, ?, ?, ?)",
            ("220235253", "220235253", hashlib.sha256("password123".encode()).hexdigest(), "220235253@gmail.com", "Pegawai 220235253")
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


def save_user_to_db(nip, username, password, email, nama, foto_bytes=None):
    """Menyimpan / memperbarui akun karyawan baru (dipanggil setelah OTP email terverifikasi)."""
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
            foto_path = COALESCE(excluded.foto_path, employees.foto_path),
            nama = excluded.nama,
            email = excluded.email
        """,
        (nip, username, hashed_pwd, email, foto_path, nama)
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


def update_profile(identifier, nama=None, email=None, username=None, foto_bytes=None):
    """Memperbarui data profil pegawai yang sedang login."""
    init_db()
    updates, params = [], []
    if nama:
        updates.append("nama = ?"); params.append(nama)
    if email:
        updates.append("email = ?"); params.append(email)
    if username:
        updates.append("username = ?"); params.append(username)
    if foto_bytes is not None:
        foto_path = simpan_foto_buffer(identifier, foto_bytes, prefix="profile")
        if foto_path:
            updates.append("foto_path = ?"); params.append(foto_path)
    if not updates:
        return
    params.extend([identifier, identifier])
    conn = get_db_connection()
    conn.execute(f"UPDATE employees SET {', '.join(updates)} WHERE nip = ? OR username = ?", params)
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
# MANAGEMENT PUBLIKASI NOTULENSI (CRUD BERITA)
# ==========================================
def load_published_data():
    init_db()
    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM published_news ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(row) for row in rows]


def publish_notulensi(judul, lokasi, poin_utama, isi_artikel, publisher):
    init_db()
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO published_news (judul, lokasi, waktu_rilis, poin_utama, isi_artikel, dipublikasikan_oleh) VALUES (?, ?, ?, ?, ?, ?)",
        (judul, lokasi, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), poin_utama, isi_artikel, publisher)
    )
    conn.commit()
    conn.close()


def update_news(news_id, judul, lokasi, isi_artikel):
    init_db()
    conn = get_db_connection()
    conn.execute(
        "UPDATE published_news SET judul = ?, lokasi = ?, isi_artikel = ? WHERE id = ?",
        (judul, lokasi, isi_artikel, news_id)
    )
    conn.commit()
    conn.close()


def delete_news(news_id):
    init_db()
    conn = get_db_connection()
    conn.execute("DELETE FROM published_news WHERE id = ?", (news_id,))
    conn.commit()
    conn.close()


# ==========================================
# DIALOG MODAL (LOGOUT, BERITA, VERIFIKASI FOTO)
# ==========================================
@st.dialog("🚪 Absen Keluar")
def modal_logout():
    st.write("Silakan verifikasi akun, ambil foto bukti absensi, dan pilih jenis absensi sebelum keluar:")

    logout_nip = st.text_input("NIP / Username PNS", value=st.session_state.get("username", ""), key="logout_nip_val")
    logout_pass = st.text_input("Kata Sandi / Password Akun", type="password", key="logout_pass_val")
    opsi_logout = st.radio("Pilih absen keluar", ["Jam ISHOMA", "Jam Pulang"], key="opsi_logout_val")

    st.write("📸 **Ambil Foto Bukti Absen Keluar:**")
    logout_photo = st.camera_input("Ambil foto untuk bukti absen keluar", key="logout_cam")

    if st.button("Konfirmasi Out & Logout", use_container_width=True, type="primary"):
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
    st.markdown(f"<span class='pill-tag'>{item['lokasi']}</span>", unsafe_allow_html=True)
    st.subheader(item['judul'])
    st.caption(f"🕒 {item['waktu_rilis']}  ·  ✍️ {item['dipublikasikan_oleh']}")
    st.markdown("---")
    st.markdown(item['isi_artikel'])
    if st.button("Tutup Berita"):
        st.session_state[f"show_modal_{item['id']}"] = False
        st.rerun()


@st.dialog("Verifikasi Foto")
def modal_status_foto(valid, after_ok_rerun=True):
    if valid:
        st.success("✅ Foto berhasil diverifikasi! Wajah terlihat jelas dan foto siap digunakan.")
    else:
        st.error("❌ Foto tidak valid. Wajah tidak terlihat jelas pada foto yang diambil. Silakan ulangi dengan pencahayaan yang cukup dan posisikan wajah tepat di tengah kamera.")
    if st.button("Tutup", use_container_width=True, type="primary"):
        if after_ok_rerun:
            st.rerun()


@st.dialog("Edit Berita")
def modal_edit_berita(item):
    st.caption("Perbarui informasi berita yang sudah dipublikasikan.")
    e_judul = st.text_input("Judul Berita", value=item["judul"], key=f"edit_judul_{item['id']}")
    e_lokasi = st.text_input("Lokasi", value=item["lokasi"], key=f"edit_lokasi_{item['id']}")
    e_isi = st.text_area("Isi Artikel", value=item["isi_artikel"], height=220, key=f"edit_isi_{item['id']}")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Batal", use_container_width=True, key=f"batal_edit_{item['id']}"):
            st.rerun()
    with col2:
        if st.button("Simpan Perubahan", type="primary", use_container_width=True, key=f"simpan_edit_{item['id']}"):
            update_news(item["id"], e_judul, e_lokasi, e_isi)
            st.success("Berita berhasil diperbarui!")
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
# ANTARMUKA UTAMA (STREAMLIT DASHBOARD) — REDESIGN v3 (biru-navy)
# ==========================================
seed_default_data()

st.set_page_config(page_title="GovScribe - Aplikasi Notulensi Rapat Digital", layout="wide", page_icon="🏛️")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap');

:root {
  --navy:#0f1c33;
  --navy-2:#16264a;
  --blue:#2f6fed;
  --blue-dark:#1e56cf;
  --blue-soft:#eaf1ff;
  --orange:#ef8a54;
  --orange-dark:#e06c2d;
  --ink:#101828;
  --muted:#66748c;
  --line:#e3e8f0;
  --paper:#ffffff;
  --wash:#f2f5fa;
  --good:#1a9d5c;
  --good-soft:#e5f7ee;
  --bad:#e0562f;
}

html, body, [class*="css"] { font-family:'DM Sans', sans-serif; color:var(--ink); }
[data-testid="stAppViewContainer"] { background:var(--wash); }
[data-testid="stAppViewContainer"] h1,
[data-testid="stAppViewContainer"] h2,
[data-testid="stAppViewContainer"] h3,
[data-testid="stAppViewContainer"] h4,
[data-testid="stAppViewContainer"] p,
[data-testid="stAppViewContainer"] label,
[data-testid="stAppViewContainer"] span { color:var(--ink); }
h1, h2, h3, h4 { font-family:'Space Grotesk', sans-serif; letter-spacing:0; color:var(--ink); }
.block-container { padding-top:2rem !important; }

/* ---------- SIDEBAR ---------- */
[data-testid="stSidebar"] { background:var(--navy); border-right:0; }
[data-testid="stSidebar"] * { color:#dbe4f2; }
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p { color:#8494ae; }
[data-testid="stSidebar"] [role="radiogroup"] { gap:2px; display:flex; flex-direction:column; }
[data-testid="stSidebar"] [role="radiogroup"] label {
  padding:10px 12px; border-radius:10px; margin-bottom:2px; font-weight:600; font-size:14px;
  transition:background .15s ease;
}
[data-testid="stSidebar"] [role="radiogroup"] label:hover { background:rgba(255,255,255,.07); }
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {
  background:var(--blue) !important; box-shadow:0 4px 12px rgba(47,111,237,.35);
}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p { color:white !important; }
[data-testid="stSidebar"] [role="radiogroup"] label > div:first-child { display:none; }
[data-testid="stSidebar"] .stButton button {
  background:transparent; border:1.5px solid rgba(255,255,255,.18); color:#dbe4f2; border-radius:10px; font-weight:600;
}
[data-testid="stSidebar"] .stButton button:hover { border-color:var(--orange); color:var(--orange); }

.brand { display:flex; align-items:center; gap:12px; padding:6px 0 26px; }
.brand-mark {
  width:42px; height:42px; display:grid; place-items:center; border-radius:12px;
  background:var(--orange); color:white; font:700 20px 'Space Grotesk';
  box-shadow:0 6px 14px rgba(239,138,84,.35);
}
.brand-name { font:700 19px 'Space Grotesk'; color:white; line-height:1.1; }
.brand-sub { font-size:11px; color:#7b8bab; margin-top:2px; letter-spacing:.3px; }
.side-eyebrow { color:#5f6f8f; font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:1.4px; margin:14px 0 6px 4px; }

/* ---------- FIX KONTRAS WIDGET (tema browser dark tidak lagi bikin kotak hitam) ---------- */
[data-testid="stAppViewContainer"] [data-testid="stTextInput"] input,
[data-testid="stAppViewContainer"] [data-testid="stNumberInput"] input,
[data-testid="stAppViewContainer"] [data-testid="stTextArea"] textarea,
[data-testid="stAppViewContainer"] [data-baseweb="select"] > div,
[data-testid="stAppViewContainer"] [data-baseweb="base-input"] {
  background:var(--paper) !important; color:var(--ink) !important;
  border:1.5px solid var(--line) !important; border-radius:10px !important;
}
[data-testid="stAppViewContainer"] [data-testid="stTextInput"] input::placeholder,
[data-testid="stAppViewContainer"] [data-testid="stTextArea"] textarea::placeholder { color:#9fb0ba !important; }
[data-testid="stAppViewContainer"] [data-baseweb="select"] span { color:var(--ink) !important; }
[data-testid="stAppViewContainer"] label p { color:var(--ink) !important; font-weight:600; font-size:13.5px; }

[data-testid="stAppViewContainer"] .stButton button {
  background:var(--paper) !important; color:var(--navy) !important;
  border:1.5px solid var(--line) !important; border-radius:10px !important; font-weight:600 !important;
}
[data-testid="stAppViewContainer"] .stButton button:hover { border-color:var(--blue) !important; color:var(--blue-dark) !important; }
[data-testid="stAppViewContainer"] button[kind="primary"],
[data-testid="stAppViewContainer"] button[kind="primaryFormSubmit"] {
  background:var(--blue) !important; color:white !important; border-color:var(--blue) !important;
}
[data-testid="stAppViewContainer"] button[kind="primary"]:hover { background:var(--blue-dark) !important; border-color:var(--blue-dark) !important; }

[data-testid="stAppViewContainer"] [data-testid="stTabs"] button[role="tab"] { color:var(--muted) !important; font-weight:600; }
[data-testid="stAppViewContainer"] [data-testid="stTabs"] button[aria-selected="true"] { color:var(--blue-dark) !important; }
[data-testid="stAppViewContainer"] [data-testid="stTabs"] [data-baseweb="tab-highlight"] { background-color:var(--blue) !important; }

[data-testid="stAppViewContainer"] [data-testid="stCameraInput"],
[data-testid="stAppViewContainer"] [data-testid="stFileUploaderDropzone"] {
  background:var(--paper) !important; border:1.5px dashed var(--line) !important; border-radius:12px !important;
}
[data-testid="stAppViewContainer"] [data-testid="stVerticalBlockBorderWrapper"] {
  background:var(--paper) !important; border:1px solid var(--line) !important;
  border-radius:14px !important; box-shadow:0 3px 12px rgba(20,28,43,.05);
}
[data-testid="stAppViewContainer"] .stChart,
[data-testid="stAppViewContainer"] [data-testid^="stArrowVegaLite"],
[data-testid="stAppViewContainer"] [data-testid^="stVegaLite"] {
  background:var(--paper) !important; border-radius:12px !important; padding:6px;
}

/* ---------- TOPBAR ---------- */
.topbar2 {
  display:flex; justify-content:space-between; align-items:center;
  padding:16px 22px; margin-bottom:22px; background:var(--paper);
  border:1px solid var(--line); border-radius:14px;
  box-shadow:0 2px 10px rgba(20,28,43,.04);
}
.eyebrow { color:var(--blue-dark); font-size:11.5px; font-weight:700; text-transform:uppercase; letter-spacing:1.4px; }
.topbar-title { font:600 22px 'Space Grotesk'; color:var(--ink); margin-top:2px; }
.topbar-sub { color:var(--muted); font-size:12.5px; margin-top:2px; }
.topbar-right { display:flex; align-items:center; gap:14px; }
.bell { position:relative; font-size:19px; color:var(--muted); }
.bell-dot { position:absolute; top:-2px; right:-2px; width:8px; height:8px; border-radius:50%; background:var(--blue); border:2px solid white; }
.avatar-img { width:38px; height:38px; border-radius:50%; object-fit:cover; }
.avatar-fallback { width:38px; height:38px; border-radius:50%; background:var(--blue-soft); color:var(--blue-dark); display:grid; place-items:center; font:700 13px 'Space Grotesk'; }
.user-meta { line-height:1.2; }
.user-name { font-weight:700; font-size:13.5px; color:var(--ink); }
.user-role { font-size:11.5px; color:var(--muted); }
.chevron { color:var(--muted); font-size:11px; }

/* ---------- PUBLIC HEADER ---------- */
.public-header {
  display:flex; justify-content:space-between; align-items:center;
  padding:16px 22px; margin-bottom:22px; background:var(--paper);
  border:1px solid var(--line); border-radius:14px; box-shadow:0 2px 10px rgba(20,28,43,.04);
}
.public-brand { display:flex; align-items:center; gap:10px; font:700 20px 'Space Grotesk'; color:var(--navy); }
.public-mark { width:38px; height:38px; display:grid; place-items:center; border-radius:10px; background:var(--orange); color:white; font:700 18px 'Space Grotesk'; }
.public-kicker { color:var(--muted); font-size:12.5px; margin-top:2px; }

/* ---------- HERO WELCOME (dashboard) ---------- */
.hero2 { display:flex; align-items:center; gap:18px; background:linear-gradient(120deg,#e7effc,#eef4ff);
  border:1px solid #dbe6fb; border-radius:16px; padding:22px 26px; margin-bottom:22px; }
.hero2-icon { width:64px; height:64px; border-radius:16px; background:white; display:grid; place-items:center;
  font-size:30px; box-shadow:0 4px 10px rgba(37,99,235,.15); flex-shrink:0; }
.hero2-text h3 { margin:0 0 4px; font-size:19px; }
.hero2-text p { margin:0; color:var(--muted); font-size:13.5px; max-width:540px; }
.hero2-date { margin-left:auto; background:white; border-radius:12px; padding:10px 16px; font-size:12.5px;
  font-weight:600; color:var(--navy); box-shadow:0 4px 10px rgba(20,28,43,.06); white-space:nowrap; }

/* ---------- KPI CARDS v2 ---------- */
.kpi-card2 { background:var(--paper); border:1px solid var(--line); border-radius:14px; padding:18px;
  box-shadow:0 3px 12px rgba(20,28,43,.05); }
.kpi2-top { display:flex; align-items:center; gap:14px; margin-bottom:10px; }
.kpi2-icon { width:46px; height:46px; border-radius:12px; display:grid; place-items:center; font-size:20px; flex-shrink:0; }
.kpi2-label { font-size:12px; color:var(--muted); font-weight:600; }
.kpi2-value { font:700 24px 'Space Grotesk'; color:var(--ink); margin-top:2px; }
.kpi2-note { font-size:12px; font-weight:600; color:var(--good); }

/* ---------- ACTIVITY FEED ---------- */
.feed-item { display:flex; align-items:center; gap:12px; padding:10px 0; border-bottom:1px solid var(--line); }
.feed-item:last-child { border-bottom:0; }
.feed-icon { width:36px; height:36px; border-radius:10px; display:grid; place-items:center; font-size:16px; flex-shrink:0; }
.feed-title { font-weight:700; font-size:13px; }
.feed-sub { font-size:11.5px; color:var(--muted); }
.feed-time { margin-left:auto; font-size:11.5px; color:var(--muted); white-space:nowrap; }
.feed-check { color:var(--good); margin-left:8px; }

/* ---------- GENERIC CARDS ---------- */
.section-card { background:var(--paper); border:1px solid var(--line); border-radius:14px; padding:20px; }
.pill-tag { display:inline-block; background:#fde8db; color:var(--orange-dark); font-size:11.5px;
  font-weight:700; padding:4px 10px; border-radius:20px; margin-bottom:8px; letter-spacing:.3px; }
.pill-tag.blue { background:var(--blue-soft); color:var(--blue-dark); }

/* ---------- STEPPER (workspace) ---------- */
.stepper-row { display:flex; align-items:flex-start; background:var(--paper); border:1px solid var(--line);
  border-radius:14px; padding:18px 26px; margin-bottom:20px; }
.stepper-item { display:flex; flex-direction:column; align-items:center; min-width:70px; }
.stepper-circle { width:34px; height:34px; border-radius:50%; display:grid; place-items:center;
  font:700 13px 'Space Grotesk'; margin-bottom:6px; }
.stepper-label { font-size:11.5px; font-weight:600; text-align:center; max-width:100px; }
.stepper-line { flex:1; height:2px; background:var(--line); margin:17px 6px 0; }

/* ---------- LOGIN ---------- */
.login-shell-outer { max-width:960px; margin:10px auto 0; }
.login-aside { border-radius:20px 0 0 20px; background:linear-gradient(150deg,var(--navy),var(--blue) 150%);
  color:white; padding:34px 30px; position:relative; overflow:hidden; min-height:560px; }
.login-aside:after { content:""; position:absolute; left:-40px; bottom:-50px; width:200px; height:200px;
  border-radius:50%; background:rgba(239,138,84,.18); z-index:0; }
.login-aside > * { position:relative; z-index:1; }
.login-aside h3 { color:white; font-size:22px; margin:18px 0 2px; }
.login-aside .lasub { color:#a9c1e6; font-size:13px; margin-bottom:14px; }
.login-aside p.desc { color:#cfe0e8; font-size:13.5px; line-height:1.6; }
.login-aside .li-mark { width:44px; height:44px; border-radius:12px; background:var(--orange); display:grid; place-items:center; font:700 20px 'Space Grotesk'; }
.feature-row { display:flex; align-items:flex-start; gap:12px; margin-top:16px; }
.feature-icon { width:34px; height:34px; border-radius:50%; background:rgba(255,255,255,.12);
  display:grid; place-items:center; font-size:15px; flex-shrink:0; }
.feature-title { font-weight:700; font-size:13px; color:white; }
.feature-sub { font-size:11.5px; color:#a9c1e6; }
.login-quote { margin-top:26px; padding-top:16px; border-top:1px solid rgba(255,255,255,.14); font-size:12.5px; color:#cfe0e8; font-style:italic; }

.auth-toggle { display:flex; gap:8px; margin-bottom:18px; }
.login-note { padding:12px 14px; border-left:3px solid var(--blue); background:var(--blue-soft); color:var(--muted);
  font-size:12.5px; margin:0 0 16px; border-radius:0 8px 8px 0; }

/* ---------- PROFILE ---------- */
.profile-banner { display:flex; align-items:center; gap:20px; padding:22px 26px; border-radius:16px;
  background:linear-gradient(120deg,var(--navy),var(--blue)); color:white; margin-bottom:20px;
  box-shadow:0 14px 30px rgba(20,28,43,.14); }
.profile-avatar { width:64px; height:64px; border-radius:50%; background:var(--orange); color:white;
  font:700 25px 'Space Grotesk'; display:grid; place-items:center; flex-shrink:0; overflow:hidden;
  box-shadow:0 6px 16px rgba(239,138,84,.4); }
.profile-avatar img { width:100%; height:100%; object-fit:cover; }
.profile-banner h2 { color:white; margin:0 0 3px; }
.profile-banner p { color:#cfe0e8; margin:0; font-size:13.5px; }

/* ---------- MISC ---------- */
div[data-testid="stMetric"] { background:var(--paper); border:1px solid var(--line); border-radius:12px; padding:12px; }
hr { border-color:var(--line) !important; }
</style>
""", unsafe_allow_html=True)

# ------------------------------------------
# SESSION STATE DEFAULTS
# ------------------------------------------
_defaults = {
    "logged_in": False,
    "username": "",
    "show_forgot_pass": False,
    "login_failed": False,
    "otp_code": None,
    "otp_verified": False,
    "target_reset_nip": "",
    "show_employee_login": False,
    "auth_view": "login",
    "reg_stage": "form",
    "reg_pending": {},
    "reg_otp_code": None,
    "internal_page": "Dashboard",
}
for _k, _v in _defaults.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


def get_current_user():
    conn = get_db_connection()
    row = conn.execute(
        "SELECT * FROM employees WHERE username = ? OR nip = ?",
        (st.session_state.get("username", ""), st.session_state.get("username", ""))
    ).fetchone()
    conn.close()
    return dict(row) if row else {"username": st.session_state.get("username", ""), "nama": "Pegawai GovScribe", "nip": "-", "email": "-"}


def render_brand():
    st.sidebar.markdown(
        "<div class='brand'><div class='brand-mark'>G</div>"
        "<div><div class='brand-name'>GovScribe</div><div class='brand-sub'>Smart meeting system</div></div></div>",
        unsafe_allow_html=True
    )


def _avatar_html(user, size_class="avatar-img"):
    foto = user.get("foto_path")
    if foto and os.path.exists(foto):
        with open(foto, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        return f"<img src='data:image/jpeg;base64,{b64}' class='{size_class}'/>"
    initial = (user.get("nama") or user.get("username") or "G")[:2].upper()
    fallback_class = "avatar-fallback" if size_class == "avatar-img" else "profile-avatar-fallback"
    return f"<div class='{fallback_class if fallback_class=='avatar-fallback' else 'avatar-fallback'}'>{initial}</div>"


def render_topbar(title, subtitle="", section="PORTAL DIGITAL PEMERINTAH"):
    user = get_current_user()
    avatar_html = _avatar_html(user)
    st.markdown(f"""
    <div class='topbar2'>
      <div>
        <div class='eyebrow'>{section}</div>
        <div class='topbar-title'>{title}</div>
        {f"<div class='topbar-sub'>{subtitle}</div>" if subtitle else ""}
      </div>
      <div class='topbar-right'>
        <div class='bell'>🔔<span class='bell-dot'></span></div>
        {avatar_html}
        <div class='user-meta'><div class='user-name'>{user.get('nama') or user.get('username')}</div><div class='user-role'>Pegawai</div></div>
        <div class='chevron'>▾</div>
      </div>
    </div>
    """, unsafe_allow_html=True)


def render_public_header():
    header_col, login_col = st.columns([4, 1])
    with header_col:
        st.markdown(
            "<div class='public-header'><div><div class='public-brand'>"
            "<div class='public-mark'>G</div>GovScribe</div>"
            "<div class='public-kicker'>Portal informasi rapat pemerintah daerah</div></div></div>",
            unsafe_allow_html=True
        )
    with login_col:
        st.write("")
        if st.button("🔐 Login pegawai", type="primary", use_container_width=True):
            st.session_state["show_employee_login"] = True
            st.rerun()


def kpi_card2(icon, icon_bg, icon_color, label, value, note):
    st.markdown(f"""<div class='kpi-card2'>
        <div class='kpi2-top'>
            <div class='kpi2-icon' style='background:{icon_bg};color:{icon_color};'>{icon}</div>
            <div>
                <div class='kpi2-label'>{label}</div>
                <div class='kpi2-value'>{value}</div>
            </div>
        </div>
        <div class='kpi2-note'>↑ {note}</div>
        </div>""", unsafe_allow_html=True)


def render_stepper(active_step, labels):
    items = ""
    n = len(labels)
    for i, label in enumerate(labels, start=1):
        active = i == active_step
        done = i < active_step
        circle_bg = "var(--blue)" if (active or done) else "#e3e8f0"
        circle_color = "white" if (active or done) else "var(--muted)"
        label_color = "var(--blue-dark)" if active else ("var(--ink)" if done else "var(--muted)")
        connector = "" if i == n else "<div class='stepper-line'></div>"
        items += f"""<div class='stepper-item'>
            <div class='stepper-circle' style='background:{circle_bg};color:{circle_color};'>{i}</div>
            <div class='stepper-label' style='color:{label_color};'>{label}</div>
        </div>{connector}"""
    st.markdown(f"<div class='stepper-row'>{items}</div>", unsafe_allow_html=True)


def render_dashboard():
    user = get_current_user()
    render_topbar("Dashboard", "Ringkasan aktivitas sistem secara umum", "DASHBOARD")

    tanggal = datetime.now().strftime("%A, %d %B %Y | %H:%M WIB")
    st.markdown(f"""<div class='hero2'>
        <div class='hero2-icon'>🖥️</div>
        <div class='hero2-text'>
            <h3>Selamat datang, {user.get('nama') or user.get('username')}!</h3>
            <p>Kelola rapat, absensi, dan publikasi informasi pemerintah dengan lebih efisien dalam satu platform terintegrasi.</p>
        </div>
        <div class='hero2-date'>📅 {tanggal}</div>
    </div>""", unsafe_allow_html=True)

    conn = get_db_connection()
    total_absen = conn.execute("SELECT COUNT(*) FROM attendance").fetchone()[0]
    total_berita = conn.execute("SELECT COUNT(*) FROM published_news").fetchone()[0]
    total_pegawai = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
    conn.close()

    kcols = st.columns(3)
    with kcols[0]:
        kpi_card2("📋", "var(--good-soft)", "var(--good)", "TOTAL AKTIVITAS ABSENSI", total_absen, "Log absensi tercatat")
    with kcols[1]:
        kpi_card2("📰", "var(--blue-soft)", "var(--blue-dark)", "JUMLAH BERITA TERBIT", total_berita, "Berita dipublikasikan")
    with kcols[2]:
        kpi_card2("👥", "#f3e9fb", "#8b3fd1", "PEGAWAI TERDAFTAR", total_pegawai, "Akun aktif dalam sistem")

    st.write("")
    left, right = st.columns([1.6, 1], gap="large")
    with left:
        with st.container(border=True):
            st.markdown("#### Jumlah Kegiatan Keseluruhan")
            st.caption("Rapat, berita, dan aktivitas lainnya (6 bulan terakhir)")
            activity = pd.DataFrame({"Bulan": ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun"], "Aktivitas": [8, 12, 10, 18, 16, max(20, total_absen)]})
            st.bar_chart(activity.set_index("Bulan"), color="#2f6fed", height=260)
            total_6bln = int(activity["Aktivitas"].sum())
            st.markdown(f"<div class='login-note'>📊 Total <b>{total_6bln}</b> aktivitas dalam 6 bulan terakhir</div>", unsafe_allow_html=True)

    with right:
        with st.container(border=True):
            st.markdown("#### Aktivitas Terbaru")
            st.caption("Ringkasan pekerjaan yang telah diselesaikan")

            feed = []
            conn = get_db_connection()
            for row in conn.execute("SELECT * FROM attendance ORDER BY id DESC LIMIT 3").fetchall():
                feed.append(("📋", "var(--good-soft)", "var(--good)", row["kegiatan"] or "Absensi", row["status"] or "", row["waktu"][11:16] if row["waktu"] else ""))
            for row in conn.execute("SELECT * FROM published_news ORDER BY id DESC LIMIT 3").fetchall():
                feed.append(("📰", "var(--blue-soft)", "var(--blue-dark)", "Berita dipublikasikan", row["judul"], row["waktu_rilis"][11:16] if row["waktu_rilis"] else ""))
            conn.close()

            if not feed:
                st.info("Belum ada aktivitas tercatat.")
            else:
                html = ""
                for icon, bg, color, title, sub, jam in feed[:6]:
                    html += f"""<div class='feed-item'>
                        <div class='feed-icon' style='background:{bg};color:{color};'>{icon}</div>
                        <div><div class='feed-title'>{title}</div><div class='feed-sub'>{sub}</div></div>
                        <div class='feed-time'>{jam}</div><div class='feed-check'>✓</div>
                    </div>"""
                st.markdown(html, unsafe_allow_html=True)

            if st.button("Buka workspace rapat →", type="primary", use_container_width=True):
                st.session_state["internal_page"] = "Workspace Rapat"
                st.rerun()


def render_profile():
    user = get_current_user()
    render_topbar("Profil pegawai", "Kelola informasi akun Anda", "AKUN SAYA")

    avatar_html = _avatar_html(user, size_class="profile-avatar-img")
    initials = (user.get("nama") or user.get("username") or "G")[:1].upper()
    foto = user.get("foto_path")
    if foto and os.path.exists(foto):
        with open(foto, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        avatar_inner = f"<img src='data:image/jpeg;base64,{b64}'/>"
    else:
        avatar_inner = initials
    st.markdown(
        f"<div class='profile-banner'><div class='profile-avatar'>{avatar_inner}</div>"
        f"<div><h2>{user.get('nama') or 'Pegawai GovScribe'}</h2>"
        f"<p>{user.get('email') or 'Email belum diatur'} · Akun terverifikasi</p></div></div>",
        unsafe_allow_html=True
    )

    col_photo, col_form = st.columns([1, 2], gap="large")
    with col_photo:
        with st.container(border=True):
            if foto and os.path.exists(foto):
                st.image(foto, use_container_width=True)
            else:
                st.info("Belum ada foto profil.")
            with st.expander("🔄 Ubah Foto"):
                new_photo = st.camera_input("Ambil foto wajah baru", key="profile_cam")
                if new_photo is not None and st.button("Simpan Foto Baru", type="primary", use_container_width=True):
                    valid = deteksi_wajah_valid(new_photo)
                    if valid:
                        update_profile(user.get("nip") or user.get("username"), foto_bytes=new_photo)
                        modal_status_foto(True)
                    else:
                        modal_status_foto(False, after_ok_rerun=False)

        st.markdown(f"""<div class='section-card' style='margin-top:14px;'>
            <div style='font-weight:700;margin-bottom:6px;'>Informasi Akun</div>
            <div style='color:var(--muted);font-size:12.5px;'>Terdaftar sejak</div>
            <div style='font-weight:700;'>{(user.get('created_at') or '-')[:10]}</div>
        </div>""", unsafe_allow_html=True)

    with col_form:
        with st.container(border=True):
            p_nip = st.text_input("NIP", value=user.get("nip") or "", disabled=True)
            p_nama = st.text_input("Nama Lengkap", value=user.get("nama") or "")
            p_email = st.text_input("Email Dinas", value=user.get("email") or "")
            p_username = st.text_input("Username", value=user.get("username") or "")

            if st.button("Simpan Perubahan", type="primary", use_container_width=True):
                update_profile(
                    user.get("nip") or user.get("username"),
                    nama=p_nama, email=p_email, username=p_username
                )
                if p_username and p_username != user.get("username"):
                    st.session_state["username"] = p_username
                st.success("✅ Profil berhasil diperbarui!")
                st.rerun()


def render_attendance_page():
    render_topbar("Absensi & Keamanan", "Riwayat absensi dan proteksi data", "ADMINISTRASI")
    st.markdown("<span class='pill-tag blue'>🛡️ DATA TERENKRIPSI (AES-256)</span>", unsafe_allow_html=True)
    st.caption("Seluruh log absensi tersimpan dalam bentuk terenkripsi dan hanya dapat dibaca oleh sistem.")
    if os.path.exists(ABSENSI_ENCRYPTED_FILE):
        df_encrypted = pd.read_csv(ABSENSI_ENCRYPTED_FILE)
        df_decrypted = df_encrypted.copy()
        df_decrypted["Waktu_Asli"] = df_encrypted["Waktu_Encrypted"].apply(dekripsi_teks)
        df_decrypted["NIP_Username_Asli"] = df_encrypted["NIP_Username_Encrypted"].apply(dekripsi_teks)
        df_decrypted["Kegiatan_Asli"] = df_encrypted["Kegiatan_Encrypted"].apply(dekripsi_teks)
        df_decrypted["Metode_Asli"] = df_encrypted["Metode_Encrypted"].apply(dekripsi_teks)
        df_decrypted["Status_Asli"] = df_encrypted["Status_Encrypted"].apply(dekripsi_teks)
        with st.container(border=True):
            st.dataframe(df_decrypted[["Waktu_Asli", "NIP_Username_Asli", "Kegiatan_Asli", "Metode_Asli", "Status_Asli"]], use_container_width=True)
    else:
        st.info("Belum ada log absensi terenkripsi yang tercatat.")


def _paginate(items, page_key, page_size=3):
    total_pages = max(1, (len(items) + page_size - 1) // page_size)
    if page_key not in st.session_state:
        st.session_state[page_key] = 1
    page = min(st.session_state[page_key], total_pages)
    start = (page - 1) * page_size
    chunk = items[start:start + page_size]

    if total_pages > 1:
        cols = st.columns([1] + [1] * min(total_pages, 5) + [1])
        with cols[0]:
            if st.button("‹", key=f"{page_key}_prev", disabled=page <= 1):
                st.session_state[page_key] = max(1, page - 1)
                st.rerun()
        for i in range(min(total_pages, 5)):
            pnum = i + 1
            with cols[i + 1]:
                if st.button(str(pnum), key=f"{page_key}_p{pnum}", type="primary" if pnum == page else "secondary"):
                    st.session_state[page_key] = pnum
                    st.rerun()
        with cols[-1]:
            if st.button("›", key=f"{page_key}_next", disabled=page >= total_pages):
                st.session_state[page_key] = min(total_pages, page + 1)
                st.rerun()
    return chunk


def render_public_portal(admin_mode=False):
    if not admin_mode:
        render_public_header()
    st.title("Portal Berita Publik")
    st.caption("Berita dan kegiatan resmi yang dipublikasikan oleh pegawai dan perangkat daerah.")

    published_items = load_published_data()
    if not published_items:
        st.info("Belum ada berita yang dipublikasikan untuk umum.")
        return

    page_key = "news_page_admin" if admin_mode else "news_page_public"
    chunk = _paginate(published_items, page_key, page_size=3)

    for item in chunk:
        with st.container(border=True):
            st.markdown(f"<span class='pill-tag'>{item['lokasi']}</span>", unsafe_allow_html=True)
            st.markdown(f"### {item['judul']}")
            st.caption(f"🕒 {item['waktu_rilis']}  ·  ✍️ {item['dipublikasikan_oleh']}")
            st.markdown((item['isi_artikel'] or '')[:400] + "...")

            if admin_mode:
                c1, c2, c3 = st.columns(3)
                with c1:
                    if st.button("👁️ Lihat Berita", key=f"lihat_{item['id']}", type="primary", use_container_width=True):
                        st.session_state[f"public_modal_{item['id']}"] = True
                with c2:
                    if st.button("✏️ Edit Berita", key=f"edit_{item['id']}", use_container_width=True):
                        modal_edit_berita(item)
                with c3:
                    if st.button("🗑️ Hapus Berita", key=f"hapus_{item['id']}", use_container_width=True):
                        delete_news(item["id"])
                        st.success("Berita dihapus.")
                        st.rerun()
            else:
                if st.button(f"Baca Selengkapnya", key=f"public_{item['id']}"):
                    st.session_state[f"public_modal_{item['id']}"] = True

        if st.session_state.get(f"public_modal_{item['id']}"):
            modal_berita(item)


def render_login_page():
    outer = st.container()
    with outer:
        st.markdown("<div class='login-shell-outer'>", unsafe_allow_html=True)
        with st.container(border=True):
            aside_col, main_col = st.columns([1, 1.55], gap="small")

            with aside_col:
                st.markdown(
                    """<div class='login-aside'>
                    <div class='li-mark'>G</div>
                    <h3>GovScribe</h3>
                    <div class='lasub'>Smart Meeting System</div>
                    <p class='desc'>Sistem notulensi &amp; absensi digital untuk mendukung tata kelola rapat pemerintah daerah yang cepat, aman, dan transparan.</p>
                    <div class='feature-row'>
                        <div class='feature-icon'>🤖</div>
                        <div><div class='feature-title'>Transkripsi Rapat Otomatis berbasis AI</div>
                        <div class='feature-sub'>Ubah suara menjadi notulen akurat secara instan.</div></div>
                    </div>
                    <div class='feature-row'>
                        <div class='feature-icon'>🛡️</div>
                        <div><div class='feature-title'>Absensi Terenkripsi AES-256</div>
                        <div class='feature-sub'>Keamanan data terjamin dengan enkripsi tingkat tinggi.</div></div>
                    </div>
                    <div class='feature-row'>
                        <div class='feature-icon'>📰</div>
                        <div><div class='feature-title'>Publikasi Berita Resmi ke Masyarakat</div>
                        <div class='feature-sub'>Sampaikan informasi dan kegiatan resmi dengan mudah.</div></div>
                    </div>
                    <div class='login-quote'>&ldquo;Wujudkan rapat efektif, absensi akurat, dan informasi publik yang terpercaya.&rdquo;</div>
                    </div>""",
                    unsafe_allow_html=True
                )

            with main_col:
                st.write("")
                _render_auth_main()

        st.markdown("</div>", unsafe_allow_html=True)


def _render_auth_main():
    # --- Alur lupa password (dipicu dari link di halaman login) ---
    if st.session_state["show_forgot_pass"]:
        st.markdown("### 🔑 Reset Password via Kirim OTP ke Gmail")

        if not st.session_state["otp_code"]:
            st.info("Masukkan NIP dan alamat Gmail Anda yang aktif untuk menerima Kode OTP.")
            reset_nip = st.text_input("Masukkan NIP / Username", value=st.session_state.get("target_reset_nip", ""))
            user_email = st.text_input("Masukkan Email Gmail Anda (contoh: user@gmail.com)")

            col_b1, col_b2 = st.columns([1, 1])
            with col_b1:
                if st.button("📧 Kirim OTP ke Gmail", type="primary", use_container_width=True):
                    users_db = load_users_db()
                    if not reset_nip or not user_email:
                        st.warning("NIP dan Email wajib diisi!")
                    elif reset_nip not in users_db:
                        st.error("NIP/Username tidak terdaftar dalam database!")
                    else:
                        generated_otp = "".join(random.choices(string.digits, k=6))
                        with st.spinner("Mengirimkan email OTP via Gmail..."):
                            sukses, pesan = kirim_email_otp(user_email, generated_otp, reset_nip, tujuan="reset")
                        if sukses:
                            st.session_state["otp_code"] = generated_otp
                            st.session_state["target_reset_nip"] = reset_nip
                            st.success(f"✅ Kode OTP berhasil dikirimkan ke **{user_email}**! Silakan periksa Kotak Masuk / Spam Gmail Anda.")
                            st.rerun()
                        else:
                            st.error(f"Gagal mengirim email OTP: {pesan}")
                            st.caption("💡 Pastikan SENDER_EMAIL & SENDER_PASSWORD (App Password) di kode Python sudah dikonfigurasi dengan benar.")
            with col_b2:
                if st.button("Kembali ke Login", use_container_width=True):
                    st.session_state["show_forgot_pass"] = False
                    st.session_state["login_failed"] = False
                    st.rerun()

        elif st.session_state["otp_code"] and not st.session_state["otp_verified"]:
            st.info(f"Kode OTP telah dikirimkan. Masukkan 6-digit Kode OTP yang Anda terima di Gmail untuk NIP **{st.session_state['target_reset_nip']}**.")
            input_otp = st.text_input("Masukkan Kode OTP dari Gmail", max_chars=6)

            col_o1, col_o2 = st.columns([1, 1])
            with col_o1:
                if st.button("Verifikasi OTP", type="primary", use_container_width=True):
                    if input_otp == st.session_state["otp_code"]:
                        st.session_state["otp_verified"] = True
                        st.success("Kode OTP Cocok! Silakan atur kata sandi baru Anda.")
                        st.rerun()
                    else:
                        st.error("Kode OTP salah atau tidak sesuai!")
            with col_o2:
                if st.button("Batal / Kirim Ulang", use_container_width=True):
                    st.session_state["otp_code"] = None
                    st.rerun()

        elif st.session_state["otp_verified"]:
            st.success(f"🔓 Verifikasi Berhasil untuk NIP: **{st.session_state['target_reset_nip']}**")
            st.markdown("#### Buat Password Baru")

            new_pass = st.text_input("Masukkan Password / PIN Baru", type="password")
            confirm_new_pass = st.text_input("Konfirmasi Password / PIN Baru", type="password")

            if st.button("Simpan Password Baru", type="primary", use_container_width=True):
                if not new_pass:
                    st.warning("Password baru tidak boleh kosong!")
                elif new_pass != confirm_new_pass:
                    st.error("Konfirmasi password tidak cocok!")
                else:
                    update_user_password(st.session_state["target_reset_nip"], new_pass)
                    st.success("🎉 Password berhasil diperbarui! Silakan login dengan password baru Anda.")
                    st.session_state["show_forgot_pass"] = False
                    st.session_state["login_failed"] = False
                    st.session_state["otp_code"] = None
                    st.session_state["otp_verified"] = False
                    st.session_state["target_reset_nip"] = ""
                    st.rerun()
        return

    # --- Toggle Login / Daftar ---
    t1, t2 = st.columns(2)
    with t1:
        if st.button("⌨️ Login Pegawai", type="primary" if st.session_state["auth_view"] == "login" else "secondary", use_container_width=True):
            st.session_state["auth_view"] = "login"
            st.rerun()
    with t2:
        if st.button("📝 Daftar Karyawan Baru", type="primary" if st.session_state["auth_view"] == "daftar" else "secondary", use_container_width=True):
            st.session_state["auth_view"] = "daftar"
            st.session_state["reg_stage"] = "form"
            st.rerun()

    if st.session_state["auth_view"] == "login":
        st.markdown("## Login Pegawai")
        st.caption("Gunakan NIP atau username dinas untuk mengakses sistem.")

        nip_input = st.text_input("NIP / Username", key="manual_nip", placeholder="Masukkan NIP atau username")
        password_input = st.text_input("Password", type="password", key="manual_pass", placeholder="Masukkan password")
        kegiatan_manual = st.selectbox("Agenda / Kegiatan", ["Rapat Internal Setda", "Pelayanan Publik", "Rapat Pleno Daerah"], key="keg_manual")

        c1, c2 = st.columns([1, 1])
        with c1:
            st.checkbox("Ingat saya", key="ingat_saya")
        with c2:
            st.markdown("<div style='text-align:right;'>", unsafe_allow_html=True)
            if st.button("Lupa password?", key="lupa_pw_link"):
                st.session_state["show_forgot_pass"] = True
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

        if st.button("Masuk", type="primary", use_container_width=True):
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
            if st.button("🔑 Lupa Password? Reset via Email Gmail"):
                st.session_state["show_forgot_pass"] = True
                st.rerun()

    else:
        st.markdown("## Pendaftaran Karyawan Baru")
        st.caption("Lengkapi data berikut untuk membuat akun baru.")

        if st.session_state["reg_stage"] == "form":
            col_r1, col_r2 = st.columns(2, gap="large")
            with col_r1:
                reg_nip = st.text_input("NIP", key="reg_nip", placeholder="Masukkan NIP")
                reg_nama = st.text_input("Nama Lengkap", key="reg_nama", placeholder="Masukkan nama lengkap")
                reg_email = st.text_input("Email Dinas", key="reg_email", placeholder="nama@domain.go.id")
            with col_r2:
                reg_username = st.text_input("Username", key="reg_username", placeholder="Buat username")
                reg_pass = st.text_input("Password", type="password", key="reg_pass", placeholder="Buat password")
                reg_pass_confirm = st.text_input("Konfirmasi Password", type="password", key="reg_pass_confirm", placeholder="Konfirmasi password")

            st.markdown("**Upload Foto (Wajib)**")
            st.caption("Arahkan kamera ke wajah Anda, pastikan wajah terlihat jelas.")
            reg_photo = st.camera_input("Ambil foto wajah untuk verifikasi pendaftaran", key="reg_cam")

            st.divider()
            cb1, cb2, cb3 = st.columns([3, 1, 1])
            with cb2:
                if st.button("Batal", use_container_width=True):
                    st.session_state["auth_view"] = "login"
                    st.rerun()
            with cb3:
                if st.button("Daftar", type="primary", use_container_width=True):
                    users_db = load_users_db()
                    if not all([reg_nip, reg_nama, reg_email, reg_username, reg_pass]):
                        st.warning("⚠️ Semua kolom wajib diisi!")
                    elif reg_username in users_db:
                        st.error("❌ Username ini sudah terdaftar dalam sistem!")
                    elif "@" not in reg_email or "." not in reg_email.split("@")[-1]:
                        st.error("❌ Format email tidak valid!")
                    elif reg_pass != reg_pass_confirm:
                        st.error("❌ Konfirmasi password tidak cocok!")
                    elif reg_photo is None:
                        st.warning("📷 Silakan ambil foto wajah terlebih dahulu!")
                    else:
                        wajah_valid = deteksi_wajah_valid(reg_photo)
                        if not wajah_valid:
                            modal_status_foto(False, after_ok_rerun=False)
                        else:
                            generated_otp = "".join(random.choices(string.digits, k=6))
                            with st.spinner("Mengirimkan kode verifikasi ke email Anda..."):
                                sukses, pesan = kirim_email_otp(reg_email, generated_otp, reg_nama, tujuan="registrasi")
                            if sukses:
                                st.session_state["reg_otp_code"] = generated_otp
                                st.session_state["reg_pending"] = {
                                    "nip": reg_nip, "username": reg_username, "nama": reg_nama,
                                    "email": reg_email, "password": reg_pass,
                                    "foto_bytes": reg_photo.getvalue()
                                }
                                st.session_state["reg_stage"] = "otp"
                                modal_status_foto(True)
                            else:
                                st.error(f"Gagal mengirim OTP verifikasi: {pesan}")

        else:  # reg_stage == "otp"
            pending = st.session_state["reg_pending"]
            st.markdown(f"<div class='login-note'>📧 Kode OTP verifikasi telah dikirim ke <b>{pending.get('email','-')}</b>. Masukkan kode tersebut untuk menyelesaikan pendaftaran dan memverifikasi email Anda.</div>", unsafe_allow_html=True)
            otp_input = st.text_input("Kode OTP Verifikasi Email", max_chars=6, key="reg_otp_input")

            c1, c2 = st.columns(2)
            with c1:
                if st.button("Verifikasi & Selesaikan Pendaftaran", type="primary", use_container_width=True):
                    if otp_input == st.session_state["reg_otp_code"]:
                        p = st.session_state["reg_pending"]
                        foto_io = io.BytesIO(p["foto_bytes"])
                        save_user_to_db(p["nip"], p["username"], p["password"], p["email"], p["nama"], foto_io)
                        st.session_state["reg_stage"] = "form"
                        st.session_state["reg_pending"] = {}
                        st.session_state["reg_otp_code"] = None
                        st.session_state["auth_view"] = "login"
                        st.success(f"🎉 Registrasi berhasil! Email {p['email']} telah terverifikasi. Silakan login.")
                        st.rerun()
                    else:
                        st.error("Kode OTP salah! Silakan periksa email Anda kembali.")
            with c2:
                if st.button("Batal / Kirim Ulang", use_container_width=True):
                    st.session_state["reg_stage"] = "form"
                    st.session_state["reg_pending"] = {}
                    st.session_state["reg_otp_code"] = None
                    st.rerun()


# ------------------------------------------
# ROUTING HALAMAN
# ------------------------------------------
if not st.session_state["logged_in"]:
    if st.session_state["show_employee_login"]:
        render_login_page()
        back_col, _ = st.columns([1, 4])
        with back_col:
            if st.button("← Kembali ke portal berita"):
                st.session_state["show_employee_login"] = False
                st.session_state["show_forgot_pass"] = False
                st.session_state["auth_view"] = "login"
                st.rerun()
    else:
        render_public_portal(admin_mode=False)
else:
    render_brand()

    st.sidebar.markdown("<div class='side-eyebrow'>MENU UTAMA</div>", unsafe_allow_html=True)
    menu_items = ["Dashboard", "Workspace Rapat", "Portal Berita", "Absensi & Keamanan", "Profil"]
    menu_icons = {"Dashboard": "🏠", "Workspace Rapat": "🎙️", "Portal Berita": "📰", "Absensi & Keamanan": "🛡️", "Profil": "👤"}
    internal_page = st.sidebar.radio(
        "Navigasi internal",
        menu_items,
        format_func=lambda x: f"{menu_icons[x]}  {x}",
        index=menu_items.index(st.session_state["internal_page"]),
        label_visibility="collapsed"
    )
    st.session_state["internal_page"] = internal_page

    st.sidebar.divider()
    if st.sidebar.button("🚪 Keluar dan absen", use_container_width=True):
        modal_logout()

    if internal_page == "Dashboard":
        render_dashboard()
        st.stop()
    if internal_page == "Profil":
        render_profile()
        st.stop()
    if internal_page == "Portal Berita":
        render_public_portal(admin_mode=True)
        st.stop()
    if internal_page == "Absensi & Keamanan":
        render_attendance_page()
        st.stop()

    render_topbar("Workspace rapat dan publikasi", "Rekam, transkripsi, dan terbitkan hasil rapat", "WORKSPACE")
    st.title("Notulensi rapat digital")

    tab1, tab2, tab3, tab4 = st.tabs([
        "1. Audio & Transkripsi (Perekam Langsung)",
        "2. Poin Masyarakat & Berita",
        "3. Portal Berita Publik",
        "4. Keamanan Database Absensi PNS"
    ])

    with tab1:
        render_stepper(1, ["Rekam / Upload Audio", "Transkripsi Otomatis", "Poin & Notulensi", "Publikasi"])
        st.header("Perekam Suara & Transkripsi Otomatis")
        col_rec1, col_rec2 = st.columns(2)

        with col_rec1:
            st.write("🎙️ **Klik ikon mikrofon di bawah untuk mulai/berhenti merekam:**")
            audio_bytes = audio_recorder(
                text="Klik untuk rekam",
                recording_color="#e0562f",
                neutral_color="#2f6fed",
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

            if st.button("⚡ Proses & Deteksi Teks (Reduksi Noise)", type="primary"):
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
        render_stepper(3, ["Rekam / Upload Audio", "Transkripsi Otomatis", "Poin & Notulensi", "Publikasi"])
        st.header("Ekstraksi Poin Publik & Artikel Berita")
        if "transkrip_raw" not in st.session_state:
            st.warning("Lakukan perekaman di Tab 1 terlebih dahulu.")
        else:
            col_a, col_b = st.columns(2)
            with col_a:
                judul_rapat = st.text_input("Judul/Topik Rapat", "Evaluasi Layanan Publik Pemko")
                lokasi_rapat = st.text_input("Lokasi Rapat", "Kantor Wali Kota")

            if st.button("Generate Poin Publik & Berita", type="primary"):
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
        render_public_portal(admin_mode=True)

    with tab4:
        render_attendance_page()