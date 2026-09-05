"""
database.py — Lapisan database GovScribe (SQLite)

Modul ini menggantikan seluruh logika database yang sebelumnya tersebar di
notelensi_pemerintah.py. Tidak ada dependensi ke Streamlit atau PIL, sehingga
bisa diuji dan dijalankan terpisah dari UI.

Perubahan utama dibanding versi lama:
  1. Absensi hanya punya satu sumber data (tabel `attendance`).
     File log_absensi_encrypted.csv tidak lagi ditulis setiap absen.
     Versi terenkripsinya dibuat on-demand lewat ekspor_absensi_terenkripsi().
  2. Tabel baru `notulensi`  -> draf notulensi tidak lagi hilang saat refresh.
  3. Tabel baru `otp_reset`  -> kode OTP punya masa berlaku dan tahan refresh.
  4. Password pakai PBKDF2-SHA256 bersalt. Hash SHA-256 lama tetap bisa login
     dan otomatis di-upgrade saat login berhasil.
  5. Skema punya nomor versi (PRAGMA user_version), jadi database lama ikut
     ternaikkan otomatis tanpa perlu dihapus.

Cara pakai minimal:
    import database as db
    db.init_db()
    db.seed_default_data()
"""

import os
import csv
import hmac
import sqlite3
import hashlib
import secrets
from datetime import datetime, timedelta
from contextlib import contextmanager

from cryptography.fernet import Fernet, InvalidToken

# ==========================================================
# KONFIGURASI
# ==========================================================

DB_FILE = os.getenv("GOVSCRIBE_DB", "govscribe.db")
KEY_FILE = os.getenv("GOVSCRIBE_KEY_FILE", "secret.key")

SKEMA_VERSI = 3          # naikkan angka ini setiap kali skema berubah
PBKDF2_ITERASI = 260_000

OTP_MASA_BERLAKU_MENIT = 10   # kode hangus setelah ini
OTP_MAKS_PERCOBAAN = 5        # salah 5x, kode dianggap hangus
OTP_MAKS_PER_JAM = 5          # maksimal permintaan kode per akun per jam
PASSWORD_MIN_PANJANG = 8


# ==========================================================
# KUNCI ENKRIPSI
# ==========================================================

def _muat_kunci():
    """
    Urutan pencarian kunci:
      1. Environment variable GOVSCRIBE_KEY  (dipakai saat deploy)
      2. File secret.key                     (dipakai saat lokal)
      3. Dibuat baru kalau dua-duanya tidak ada

    PENTING: kalau kunci hilang dan dibuat ulang, semua data yang sudah
    terenkripsi (transkrip notulensi, ekspor absensi) tidak bisa dibuka lagi.
    Saat deploy ke hosting dengan filesystem sementara, WAJIB pakai
    environment variable, jangan mengandalkan file.
    """
    kunci_env = os.getenv("GOVSCRIBE_KEY")
    if kunci_env:
        return kunci_env.encode()

    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "rb") as f:
            return f.read().strip()

    kunci_baru = Fernet.generate_key()
    with open(KEY_FILE, "wb") as f:
        f.write(kunci_baru)
    return kunci_baru


_fernet = Fernet(_muat_kunci())


def enkripsi_teks(teks):
    if teks is None:
        return None
    return _fernet.encrypt(str(teks).encode()).decode()


def dekripsi_teks(teks_terenkripsi):
    if teks_terenkripsi is None:
        return None
    try:
        return _fernet.decrypt(str(teks_terenkripsi).encode()).decode()
    except (InvalidToken, ValueError):
        return "[Gagal Dekripsi / Kunci Tidak Cocok]"


# ==========================================================
# KONEKSI
# ==========================================================

def get_db_connection():
    """Koneksi mentah. Dipertahankan agar kode lama tetap jalan."""
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def db():
    """
    Context manager yang otomatis commit, rollback saat error, dan close.

        with db() as conn:
            conn.execute("INSERT ...")
    """
    conn = get_db_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _kolom_tabel(conn, tabel):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({tabel})")}


# ==========================================================
# SKEMA
# ==========================================================

SKEMA = """
CREATE TABLE IF NOT EXISTS employees (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    nip           TEXT UNIQUE NOT NULL,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    email         TEXT,
    foto_path     TEXT,
    nama          TEXT,
    jabatan       TEXT,
    role          TEXT NOT NULL DEFAULT 'pns',
    aktif         INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at    TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS attendance (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    nip        TEXT NOT NULL,
    kegiatan   TEXT,
    metode     TEXT,
    status     TEXT,
    arah       TEXT NOT NULL DEFAULT 'masuk',   -- 'masuk' | 'keluar'
    waktu      TEXT NOT NULL,
    foto_path  TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS notulensi (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    judul             TEXT NOT NULL,
    lokasi            TEXT,
    tanggal_rapat     TEXT,
    transkrip_enc     TEXT,          -- disimpan terenkripsi
    poin_utama        TEXT,
    status            TEXT NOT NULL DEFAULT 'draft',  -- draft | final | published
    dibuat_oleh       TEXT,
    durasi_audio_detik INTEGER,
    created_at        TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at        TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS published_news (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    notulensi_id        INTEGER REFERENCES notulensi(id) ON DELETE SET NULL,
    judul               TEXT NOT NULL,
    lokasi              TEXT,
    waktu_rilis         TEXT,
    poin_utama          TEXT,
    isi_artikel         TEXT,
    dipublikasikan_oleh TEXT,
    created_at          TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS otp_reset (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    username   TEXT NOT NULL,
    otp_hash   TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used       INTEGER NOT NULL DEFAULT 0,
    percobaan  INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_attendance_nip   ON attendance(nip);
CREATE INDEX IF NOT EXISTS idx_attendance_waktu ON attendance(waktu DESC);
CREATE INDEX IF NOT EXISTS idx_notulensi_status ON notulensi(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_news_created     ON published_news(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_otp_username     ON otp_reset(username, used);
"""


def init_db():
    """Buat skema kalau belum ada, lalu naikkan database lama ke versi terbaru."""
    with db() as conn:
        conn.executescript(SKEMA)
        versi = conn.execute("PRAGMA user_version").fetchone()[0]

        if versi < 2:
            # Database dari versi lama: tambahkan kolom yang belum ada.
            kolom_emp = _kolom_tabel(conn, "employees")
            for nama_kolom, definisi in [
                ("jabatan",    "TEXT"),
                ("role",       "TEXT NOT NULL DEFAULT 'pns'"),
                ("aktif",      "INTEGER NOT NULL DEFAULT 1"),
                ("updated_at", "TEXT"),
            ]:
                if nama_kolom not in kolom_emp:
                    conn.execute(f"ALTER TABLE employees ADD COLUMN {nama_kolom} {definisi}")

            kolom_att = _kolom_tabel(conn, "attendance")
            if "arah" not in kolom_att:
                conn.execute("ALTER TABLE attendance ADD COLUMN arah TEXT NOT NULL DEFAULT 'masuk'")

            kolom_news = _kolom_tabel(conn, "published_news")
            if "notulensi_id" not in kolom_news:
                conn.execute("ALTER TABLE published_news ADD COLUMN notulensi_id INTEGER")

            conn.execute("UPDATE employees SET role = 'admin' WHERE username LIKE 'admin%'")

        if versi < 3:
            if "percobaan" not in _kolom_tabel(conn, "otp_reset"):
                conn.execute("ALTER TABLE otp_reset ADD COLUMN percobaan INTEGER NOT NULL DEFAULT 0")

        conn.execute(f"PRAGMA user_version = {SKEMA_VERSI}")


# ==========================================================
# PASSWORD
# ==========================================================

def hash_password(password):
    """Format: pbkdf2_sha256$<iterasi>$<salt_hex>$<hash_hex>"""
    salt = secrets.token_bytes(16)
    turunan = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERASI)
    return f"pbkdf2_sha256${PBKDF2_ITERASI}${salt.hex()}${turunan.hex()}"


def cek_password(password, hash_tersimpan):
    """
    Mendukung dua format:
      - pbkdf2_sha256$...  (format baru)
      - 64 karakter hex    (SHA-256 polos dari versi lama)
    Mengembalikan (cocok, perlu_upgrade).
    """
    if not hash_tersimpan:
        return False, False

    if hash_tersimpan.startswith("pbkdf2_sha256$"):
        try:
            _, iterasi, salt_hex, hash_hex = hash_tersimpan.split("$")
            turunan = hashlib.pbkdf2_hmac(
                "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterasi)
            )
            return hmac.compare_digest(turunan.hex(), hash_hex), False
        except (ValueError, TypeError):
            return False, False

    # Format lama tanpa salt.
    lama = hashlib.sha256(password.encode()).hexdigest()
    cocok = hmac.compare_digest(lama, hash_tersimpan)
    return cocok, cocok


# ==========================================================
# PEGAWAI / AUTENTIKASI
# ==========================================================

def simpan_pegawai(username, password, nip=None, nama=None, email=None,
                   foto_path=None, jabatan=None, role="pns"):
    """
    Daftar pegawai baru atau perbarui yang sudah ada.
    foto_path adalah string path, bukan bytes. Penyimpanan file gambar
    tetap ditangani simpan_foto_buffer() di file utama.
    """
    init_db()
    with db() as conn:
        conn.execute(
            """
            INSERT INTO employees (nip, username, password_hash, email, foto_path,
                                   nama, jabatan, role, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(username) DO UPDATE SET
                password_hash = excluded.password_hash,
                email         = COALESCE(excluded.email, employees.email),
                foto_path     = COALESCE(excluded.foto_path, employees.foto_path),
                nama          = COALESCE(excluded.nama, employees.nama),
                jabatan       = COALESCE(excluded.jabatan, employees.jabatan),
                updated_at    = CURRENT_TIMESTAMP
            """,
            (nip or username, username, hash_password(password), email or f"{username}@local",
             foto_path, nama or username, jabatan, role)
        )


# Nama lama, dipertahankan supaya pemanggilan di UI tidak perlu diubah.
def save_user_to_db(username, password, foto_path=None):
    simpan_pegawai(username, password, foto_path=foto_path)


def verifikasi_login(username, password):
    """Cek login. Hash SHA-256 lama otomatis di-upgrade ke PBKDF2 saat berhasil."""
    init_db()
    with db() as conn:
        row = conn.execute(
            "SELECT username, password_hash, aktif FROM employees WHERE username = ? OR nip = ?",
            (username, username)
        ).fetchone()

        if row is None or not row["aktif"]:
            return False

        cocok, perlu_upgrade = cek_password(password, row["password_hash"])
        if cocok and perlu_upgrade:
            conn.execute(
                "UPDATE employees SET password_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE username = ?",
                (hash_password(password), row["username"])
            )
        return cocok


def update_user_password(username, password_baru):
    init_db()
    with db() as conn:
        conn.execute(
            "UPDATE employees SET password_hash = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE username = ? OR nip = ?",
            (hash_password(password_baru), username, username)
        )


def ambil_pegawai(username):
    init_db()
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM employees WHERE username = ? OR nip = ?", (username, username)
        ).fetchone()
        return dict(row) if row else None


def daftar_pegawai():
    init_db()
    with db() as conn:
        rows = conn.execute(
            "SELECT id, nip, username, nama, email, jabatan, role, aktif, foto_path "
            "FROM employees ORDER BY nama"
        ).fetchall()
        return [dict(r) for r in rows]


def load_users_db():
    """Kompatibilitas dengan kode lama. Jangan dipakai untuk verifikasi login."""
    return {p["username"]: p["nip"] for p in daftar_pegawai()}


# ==========================================================
# ABSENSI
# ==========================================================

def catat_absensi(nip_username, kegiatan="Kehadiran Rapat", metode="Manual Input",
                  status="Hadir (Tervalidasi)", foto_path=None, is_logout=False):
    """
    Satu-satunya jalur pencatatan absensi. Tidak lagi menulis CSV paralel.
    Mengembalikan id baris yang dibuat.
    """
    init_db()
    waktu = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO attendance (nip, kegiatan, metode, status, arah, waktu, foto_path) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (nip_username, kegiatan, metode, status,
             "keluar" if is_logout else "masuk", waktu, foto_path)
        )
        return cur.lastrowid


# Nama lama dipertahankan.
catat_absensi_terenkripsi = catat_absensi


def riwayat_absensi(nip=None, limit=200):
    init_db()
    sql = "SELECT * FROM attendance"
    params = []
    if nip:
        sql += " WHERE nip = ?"
        params.append(nip)
    sql += " ORDER BY waktu DESC"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)

    with db() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def absensi_terakhir(nip):
    """Berguna untuk fitur peringatan 'belum absen keluar'."""
    hasil = riwayat_absensi(nip=nip, limit=1)
    return hasil[0] if hasil else None


def ekspor_absensi_terenkripsi(path_output="log_absensi_encrypted.csv", nip=None):
    """
    Membuat arsip absensi terenkripsi dari isi database, dipanggil hanya saat
    dibutuhkan. Ini menggantikan penulisan CSV di setiap absen.
    """
    baris = riwayat_absensi(nip=nip, limit=None)
    with open(path_output, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Waktu_Encrypted", "NIP_Username_Encrypted", "Kegiatan_Encrypted",
            "Metode_Encrypted", "Status_Encrypted"
        ])
        for b in baris:
            writer.writerow([
                enkripsi_teks(b["waktu"]),
                enkripsi_teks(b["nip"]),
                enkripsi_teks(b["kegiatan"]),
                enkripsi_teks(b["metode"]),
                enkripsi_teks(b["status"]),
            ])
    return path_output, len(baris)


# ==========================================================
# NOTULENSI
# ==========================================================

def simpan_notulensi(judul, transkrip, lokasi=None, poin_utama=None,
                     dibuat_oleh=None, tanggal_rapat=None, status="draft"):
    """Simpan draf notulensi. Transkrip disimpan dalam bentuk terenkripsi."""
    init_db()
    with db() as conn:
        cur = conn.execute(
            """
            INSERT INTO notulensi (judul, lokasi, tanggal_rapat, transkrip_enc,
                                   poin_utama, status, dibuat_oleh)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (judul, lokasi,
             tanggal_rapat or datetime.now().strftime("%Y-%m-%d"),
             enkripsi_teks(transkrip), poin_utama, status, dibuat_oleh)
        )
        return cur.lastrowid


def update_notulensi(notulensi_id, judul=None, transkrip=None, poin_utama=None,
                     lokasi=None, status=None):
    init_db()
    field, params = [], []
    for kolom, nilai in [
        ("judul", judul),
        ("lokasi", lokasi),
        ("poin_utama", poin_utama),
        ("status", status),
        ("transkrip_enc", enkripsi_teks(transkrip) if transkrip is not None else None),
    ]:
        if nilai is not None:
            field.append(f"{kolom} = ?")
            params.append(nilai)

    if not field:
        return False

    field.append("updated_at = CURRENT_TIMESTAMP")
    params.append(notulensi_id)
    with db() as conn:
        conn.execute(f"UPDATE notulensi SET {', '.join(field)} WHERE id = ?", params)
    return True


def ambil_notulensi(notulensi_id):
    """Ambil satu notulensi dengan transkrip yang sudah didekripsi."""
    init_db()
    with db() as conn:
        row = conn.execute("SELECT * FROM notulensi WHERE id = ?", (notulensi_id,)).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["transkrip"] = dekripsi_teks(data.pop("transkrip_enc"))
        return data


def daftar_notulensi(dibuat_oleh=None, status=None, limit=50):
    """Daftar ringkas untuk ditampilkan di tabel. Transkrip tidak ikut dimuat."""
    init_db()
    sql = ("SELECT id, judul, lokasi, tanggal_rapat, poin_utama, status, "
           "dibuat_oleh, created_at, updated_at FROM notulensi WHERE 1=1")
    params = []
    if dibuat_oleh:
        sql += " AND dibuat_oleh = ?"
        params.append(dibuat_oleh)
    if status:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    with db() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def hapus_notulensi(notulensi_id):
    init_db()
    with db() as conn:
        conn.execute("DELETE FROM notulensi WHERE id = ?", (notulensi_id,))


# ==========================================================
# BERITA PUBLIK
# ==========================================================

def publish_notulensi(judul, lokasi, poin_utama, isi_artikel, publisher, notulensi_id=None):
    init_db()
    with db() as conn:
        cur = conn.execute(
            """
            INSERT INTO published_news (notulensi_id, judul, lokasi, waktu_rilis,
                                        poin_utama, isi_artikel, dipublikasikan_oleh)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (notulensi_id, judul, lokasi,
             datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
             poin_utama, isi_artikel, publisher)
        )
        if notulensi_id:
            conn.execute("UPDATE notulensi SET status = 'published' WHERE id = ?", (notulensi_id,))
        return cur.lastrowid


def load_published_data(limit=50):
    init_db()
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM published_news ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def update_berita(berita_id, judul=None, poin_utama=None, isi_artikel=None):
    init_db()
    field, params = [], []
    for kolom, nilai in [("judul", judul), ("poin_utama", poin_utama), ("isi_artikel", isi_artikel)]:
        if nilai is not None:
            field.append(f"{kolom} = ?")
            params.append(nilai)
    if not field:
        return False
    params.append(berita_id)
    with db() as conn:
        conn.execute(f"UPDATE published_news SET {', '.join(field)} WHERE id = ?", params)
    return True


def hapus_berita(berita_id):
    init_db()
    with db() as conn:
        conn.execute("DELETE FROM published_news WHERE id = ?", (berita_id,))


# ==========================================================
# OTP RESET PASSWORD
# ==========================================================

def _hash_otp(kode):
    return hashlib.sha256(str(kode).encode()).hexdigest()


def buat_otp(username):
    """
    Membuat OTP 6 digit dan menyimpan HASH-nya saja. Kode asli hanya
    dikembalikan sekali di sini untuk langsung dikirim lewat email.

    Mengembalikan (kode, pesan_error).
    Kalau kuota per jam habis, kode = None dan pesan_error terisi.
    """
    init_db()
    sejam_lalu = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")

    with db() as conn:
        jumlah = conn.execute(
            "SELECT COUNT(*) FROM otp_reset WHERE username = ? AND created_at > ?",
            (username, sejam_lalu)
        ).fetchone()[0]

        if jumlah >= OTP_MAKS_PER_JAM:
            return None, (f"Permintaan kode terlalu sering. Maksimal {OTP_MAKS_PER_JAM} kali "
                          f"per jam. Silakan coba lagi nanti.")

        kode = f"{secrets.randbelow(1_000_000):06d}"
        kadaluarsa = (datetime.now() + timedelta(minutes=OTP_MASA_BERLAKU_MENIT)) \
            .strftime("%Y-%m-%d %H:%M:%S")

        # Kode lama yang belum terpakai langsung dihanguskan.
        conn.execute("UPDATE otp_reset SET used = 1 WHERE username = ? AND used = 0", (username,))
        conn.execute(
            "INSERT INTO otp_reset (username, otp_hash, expires_at) VALUES (?, ?, ?)",
            (username, _hash_otp(kode), kadaluarsa)
        )

    return kode, None


def verifikasi_otp(username, kode):
    """
    Sekali pakai. Mengembalikan (berhasil, pesan).
    Salah 5 kali membuat kode hangus dan pengguna harus minta kode baru.
    """
    init_db()
    sekarang = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with db() as conn:
        row = conn.execute(
            "SELECT id, otp_hash, percobaan FROM otp_reset "
            "WHERE username = ? AND used = 0 ORDER BY id DESC LIMIT 1",
            (username,)
        ).fetchone()

        if row is None:
            return False, "Tidak ada kode aktif. Silakan minta kode baru."

        kadaluarsa = conn.execute(
            "SELECT expires_at FROM otp_reset WHERE id = ?", (row["id"],)
        ).fetchone()[0]

        if kadaluarsa <= sekarang:
            conn.execute("UPDATE otp_reset SET used = 1 WHERE id = ?", (row["id"],))
            return False, "Kode sudah kadaluarsa. Silakan minta kode baru."

        if not hmac.compare_digest(_hash_otp(kode), row["otp_hash"]):
            sisa = OTP_MAKS_PERCOBAAN - (row["percobaan"] + 1)
            if sisa <= 0:
                conn.execute("UPDATE otp_reset SET used = 1, percobaan = percobaan + 1 WHERE id = ?",
                             (row["id"],))
                return False, "Terlalu banyak percobaan salah. Kode dihanguskan, minta kode baru."
            conn.execute("UPDATE otp_reset SET percobaan = percobaan + 1 WHERE id = ?", (row["id"],))
            return False, f"Kode salah. Sisa percobaan: {sisa}."

        conn.execute("UPDATE otp_reset SET used = 1 WHERE id = ?", (row["id"],))
        return True, "Kode terverifikasi."


def validasi_password(password):
    """Aturan minimum. Mengembalikan (valid, pesan)."""
    if len(password) < PASSWORD_MIN_PANJANG:
        return False, f"Kata sandi minimal {PASSWORD_MIN_PANJANG} karakter."
    if password.isdigit() or password.isalpha():
        return False, "Kata sandi harus mengandung kombinasi huruf dan angka."
    if password.lower() in {"password", "12345678", "qwerty123", "admin123"}:
        return False, "Kata sandi terlalu umum, gunakan yang lain."
    return True, "Kata sandi memenuhi syarat."


def reset_password_dengan_otp(username, kode, password_baru):
    """
    Satu pintu untuk keseluruhan proses reset: verifikasi kode, cek kekuatan
    sandi, pastikan tidak sama dengan yang lama, lalu simpan.
    Mengembalikan (berhasil, pesan).
    """
    ok, pesan = verifikasi_otp(username, kode)
    if not ok:
        return False, pesan

    valid, pesan_valid = validasi_password(password_baru)
    if not valid:
        return False, pesan_valid

    pegawai = ambil_pegawai(username)
    if pegawai is None:
        return False, "Akun tidak ditemukan."

    sama, _ = cek_password(password_baru, pegawai["password_hash"])
    if sama:
        return False, "Kata sandi baru tidak boleh sama dengan yang lama."

    update_user_password(username, password_baru)

    # Hanguskan semua kode lain milik akun ini.
    with db() as conn:
        conn.execute("UPDATE otp_reset SET used = 1 WHERE username = ?", (username,))

    return True, "Kata sandi berhasil diperbarui."


# ==========================================================
# STATISTIK DASHBOARD
# ==========================================================

def statistik_dashboard():
    init_db()
    with db() as conn:
        return {
            "total_pegawai":  conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0],
            "total_absensi":  conn.execute("SELECT COUNT(*) FROM attendance").fetchone()[0],
            "total_notulensi": conn.execute("SELECT COUNT(*) FROM notulensi").fetchone()[0],
            "total_berita":   conn.execute("SELECT COUNT(*) FROM published_news").fetchone()[0],
            "absensi_hari_ini": conn.execute(
                "SELECT COUNT(*) FROM attendance WHERE date(waktu) = date('now', 'localtime')"
            ).fetchone()[0],
        }


# ==========================================================
# DATA AWAL
# ==========================================================

def seed_default_data():
    """Isi akun default dan satu contoh berita. Aman dipanggil berulang kali."""
    init_db()

    akun_default = [
        ("admin_setda",  "admin123",      "Administrator Setda", "admin@setda.local",     "admin"),
        ("pns_19850110", "pns_pass_123",  "Pegawai 19850110",    "pns_19850110@gmail.com", "pns"),
        ("pns_19920315", "pns_pass_456",  "Pegawai 19920315",    "pns_19920315@gmail.com", "pns"),
        ("220235253",    "password123",   "Pegawai 220235253",   "220235253@gmail.com",    "pns"),
    ]

    with db() as conn:
        sudah_ada = conn.execute(
            "SELECT COUNT(*) FROM employees WHERE username = 'admin_setda'"
        ).fetchone()[0]

    if not sudah_ada:
        for username, password, nama, email, role in akun_default:
            simpan_pegawai(username, password, nip=username, nama=nama, email=email, role=role)

    with db() as conn:
        kosong = conn.execute("SELECT COUNT(*) FROM published_news").fetchone()[0] == 0

    if kosong:
        publish_notulensi(
            judul="Evaluasi Pelayanan Publik Daerah",
            lokasi="Kantor Setda",
            poin_utama=("• Peningkatan koordinasi antar unit kerja\n"
                        "• Percepatan pelayanan publik\n"
                        "• Transparansi data dan dokumen"),
            isi_artikel=(
                "# Berita Pemerintah Kabupaten\n\n"
                "Dalam kegiatan koordinasi yang berlangsung hari ini, pemerintah menegaskan "
                "komitmen untuk mempercepat pelayanan publik dan meningkatkan transparansi data. "
                "Kegiatan ini melibatkan seluruh perangkat daerah serta perwakilan stakeholder "
                "penting terkait program strategis di wilayah kami.\n\n"
                "Poin utama yang dihasilkan adalah peningkatan koordinasi antar satuan kerja, "
                "efisiensi pelayanan masyarakat, dan komitmen meningkatkan kualitas tata kelola "
                "pemerintahan yang lebih cepat dan akuntabel.\n"
            ),
            publisher="admin_setda",
        )


if __name__ == "__main__":
    init_db()
    seed_default_data()
    print(f"Database siap: {os.path.abspath(DB_FILE)}")
    for kunci, nilai in statistik_dashboard().items():
        print(f"  {kunci:20s}: {nilai}")
