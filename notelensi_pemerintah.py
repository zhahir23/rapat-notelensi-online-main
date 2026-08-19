import os
import wave
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
import whisper
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
USERS_DB_FILE = "users_db.json"
ABSENSI_ENCRYPTED_FILE = "log_absensi_encrypted.csv"

def load_users_db():
    if not os.path.exists(USERS_DB_FILE):
        default_users = {
            "admin_setda": hashlib.sha256("admin123".encode()).hexdigest(),
            "pns_19850110": hashlib.sha256("pns_pass_123".encode()).hexdigest(),
            "pns_19920315": hashlib.sha256("pns_pass_456".encode()).hexdigest(),
            "220235253": hashlib.sha256("password123".encode()).hexdigest()
        }
        with open(USERS_DB_FILE, "w") as f:
            json.dump(default_users, f)
        return default_users
    else:
        with open(USERS_DB_FILE, "r") as f:
            return json.load(f)

def save_user_to_db(username, password, foto_bytes=None):
    users = load_users_db()
    hashed_pwd = hashlib.sha256(password.encode()).hexdigest()
    users[username] = hashed_pwd
    with open(USERS_DB_FILE, "w") as f:
        json.dump(users, f)
    if foto_bytes is not None:
        simpan_foto_buffer(username, foto_bytes)

def update_user_password(username, new_password):
    users = load_users_db()
    users[username] = hashlib.sha256(new_password.encode()).hexdigest()
    with open(USERS_DB_FILE, "w") as f:
        json.dump(users, f)

def verifikasi_login(username, password):
    users = load_users_db()
    hashed_pwd = hashlib.sha256(password.encode()).hexdigest()
    return users.get(username) == hashed_pwd

def catat_absensi_terenkripsi(nip_username, kegiatan="Kehadiran Rapat", metode="Manual Input", status="Hadir (Tervalidasi)", foto_bytes=None, is_logout=False):
    waktu_sekarang = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if foto_bytes is not None:
        prefix = "out" if is_logout else "in"
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        simpan_foto_buffer(f"{nip_username}_{timestamp_str}", foto_bytes, prefix=prefix)

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
    if not os.path.exists(PUBLISHED_FILE):
        return []
    try:
        with open(PUBLISHED_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []

def publish_notulensi(judul, lokasi, poin_utama, isi_artikel, publisher):
    data = load_published_data()
    item_baru = {
        "id": len(data) + 1,
        "judul": judul,
        "lokasi": lokasi,
        "waktu_rilis": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "poin_utama": poin_utama,
        "isi_artikel": isi_artikel,
        "dipublikasikan_oleh": publisher
    }
    data.insert(0, item_baru)
    with open(PUBLISHED_FILE, "w") as f:
        json.dump(data, f, indent=4)

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
st.set_page_config(page_title="GovScribe - Aplikasi Notulensi Rapat Digital", layout="wide")

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

# ------------------------------------------
# HALAMAN LOGIN, ABSENSI & PENDAFTARAN PNS
# ------------------------------------------
if not st.session_state["logged_in"]:
    st.title("🔒 Portal Absensi Digital PNS")
    # st.caption("Sistem Keamanan Tingkat Tinggi - Proteksi Enkripsi Otomatis AES-256")
    
    # ----------------------------------------------------
    # FITUR RESET PASSWORD VIA EMAIL GMAIL ASLI
    # ----------------------------------------------------
    if st.session_state["show_forgot_pass"]:
        st.subheader("🔑 Reset Password via Kirim OTP ke Gmail")
        
        # LANGKAH 1: Minta Email / NIP & Kirim OTP ke Gmail
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
                        # Generasi Kode OTP Acak 6 Digit
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

        # LANGKAH 2: Masukkan Kode OTP dari Gmail
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

        # LANGKAH 3: Form Reset Password Baru
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

    # ----------------------------------------------------
    # TAMPILAN LOGIN UTAMA DAN REGISTRASI
    # ----------------------------------------------------
    else:
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
            
            # Membagi tampilan menjadi 2 kolom seimbang
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
            
            # Tombol pendaftaran dibuat menonjol di bagian bawah
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
                    # Simpan data user ke database
                    save_user_to_db(reg_nip, reg_pass, reg_photo)
                    st.success(f"🎉 Pendaftaran Berhasil! NIP {reg_nip} telah terdaftar ke dalam sistem.")

# ------------------------------------------
# HALAMAN DASHBOARD UTAMA (SETELAH LOGIN)
# ------------------------------------------
else:
    st.sidebar.title(f"👤 Pengguna: {st.session_state['username']}")
    
    if st.sidebar.button("Logout / Absen Keluar"):
        modal_logout()
        
    st.title("🎙️ GovScribe-Pipeline: Aplikasi Notulensi Berbasis Digital")
    
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
                        st.markdown(item['isi_artikel'][:220] + "...")
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