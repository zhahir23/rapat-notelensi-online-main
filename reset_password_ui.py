"""
reset_password_ui.py — Alur "Lupa Kata Sandi" untuk GovScribe

Menggantikan blok lupa password di notelensi_pemerintah.py (baris 671-745).
Cukup panggil satu fungsi:

    import reset_password_ui
    ...
    if st.session_state.get("show_forgot_pass"):
        reset_password_ui.render()
        st.stop()

Tiga tahap:
    1. minta      -> masukkan NIP/username, sistem kirim kode ke email terdaftar
    2. verifikasi -> masukkan 6 digit kode
    3. sandi_baru -> tentukan kata sandi baru

Semua state disimpan dengan awalan "rp_" supaya tidak bentrok dengan
session_state yang sudah ada di file utama.
"""

import time
from datetime import datetime

import streamlit as st

import database as db
import email_service as mail

# Kalau True, sistem tidak memberi tahu apakah sebuah NIP terdaftar atau
# tidak. Ini mencegah orang luar menebak-nebak daftar pegawai. Ubah ke
# False kalau kamu lebih mengutamakan kemudahan saat uji coba.
SEMBUNYIKAN_KEBERADAAN_AKUN = True

JEDA_KIRIM_ULANG_DETIK = 60


# ==========================================================
# STATE
# ==========================================================

def _init_state():
    default = {
        "rp_tahap": "minta",
        "rp_username": "",
        "rp_email_samar": "",
        "rp_terverifikasi": False,
        "rp_waktu_kirim": 0.0,
        "rp_pesan": None,      # (jenis, teks) -> jenis: info | sukses | error
    }
    for kunci, nilai in default.items():
        st.session_state.setdefault(kunci, nilai)


def reset_state():
    for kunci in list(st.session_state.keys()):
        if kunci.startswith("rp_"):
            del st.session_state[kunci]


def _pesan(jenis, teks):
    st.session_state["rp_pesan"] = (jenis, teks)


def _tampilkan_pesan():
    data = st.session_state.get("rp_pesan")
    if not data:
        return
    jenis, teks = data
    {"sukses": st.success, "error": st.error}.get(jenis, st.info)(teks)
    st.session_state["rp_pesan"] = None


# ==========================================================
# LOGIKA
# ==========================================================

def _kirim_kode(username):
    """Cari akun, buat OTP, kirim email. Mengembalikan (lanjut, email_samar)."""
    pegawai = db.ambil_pegawai(username)

    pesan_netral = ("Jika NIP atau username tersebut terdaftar, kode verifikasi "
                    "sudah dikirim ke email yang terhubung dengan akun.")

    if pegawai is None:
        if SEMBUNYIKAN_KEBERADAAN_AKUN:
            _pesan("info", pesan_netral)
            return True, ""
        _pesan("error", "NIP atau username tidak terdaftar.")
        return False, ""

    email_tujuan = pegawai.get("email")
    if not mail.email_valid(email_tujuan):
        _pesan("error", "Akun ini belum punya alamat email yang valid. "
                        "Hubungi administrator untuk memperbarui data Anda.")
        return False, ""

    kode, error = db.buat_otp(pegawai["username"])
    if kode is None:
        _pesan("error", error)
        return False, ""

    terkirim, info = mail.kirim_otp(
        email_tujuan,
        kode,
        pegawai.get("nama") or pegawai["username"],
        masa_berlaku_menit=db.OTP_MASA_BERLAKU_MENIT,
    )

    if not terkirim:
        _pesan("error", f"Kode gagal dikirim. {info}")
        return False, ""

    st.session_state["rp_waktu_kirim"] = time.time()
    _pesan("sukses", pesan_netral if SEMBUNYIKAN_KEBERADAAN_AKUN
           else f"Kode dikirim ke {mail.samarkan_email(email_tujuan)}.")
    return True, mail.samarkan_email(email_tujuan)


def _sisa_jeda():
    berlalu = time.time() - st.session_state.get("rp_waktu_kirim", 0)
    return max(0, int(JEDA_KIRIM_ULANG_DETIK - berlalu))


# ==========================================================
# TAMPILAN
# ==========================================================

def _tahap_minta():
    st.subheader("Lupa Kata Sandi")
    st.caption("Masukkan NIP atau username Anda. Kami akan mengirimkan kode "
               "verifikasi ke email yang terdaftar pada akun tersebut.")

    username = st.text_input("NIP / Username", key="rp_input_username",
                             placeholder="contoh: pns_19850110")

    kolom_kirim, kolom_batal = st.columns(2)

    with kolom_kirim:
        if st.button("Kirim Kode Verifikasi", type="primary", use_container_width=True):
            if not username.strip():
                _pesan("error", "NIP atau username wajib diisi.")
            else:
                lanjut, email_samar = _kirim_kode(username.strip())
                if lanjut:
                    st.session_state["rp_username"] = username.strip()
                    st.session_state["rp_email_samar"] = email_samar
                    st.session_state["rp_tahap"] = "verifikasi"
            st.rerun()

    with kolom_batal:
        if st.button("Kembali ke Login", use_container_width=True):
            reset_state()
            st.session_state["show_forgot_pass"] = False
            st.rerun()


def _tahap_verifikasi():
    st.subheader("Verifikasi Identitas")

    tujuan = st.session_state.get("rp_email_samar")
    if tujuan:
        st.caption(f"Kode 6 digit telah dikirim ke {tujuan}. "
                   f"Berlaku {db.OTP_MASA_BERLAKU_MENIT} menit.")
    else:
        st.caption(f"Masukkan kode 6 digit yang dikirim ke email Anda. "
                   f"Berlaku {db.OTP_MASA_BERLAKU_MENIT} menit.")

    st.info("Jangan berikan kode ini kepada siapa pun, termasuk kepada pihak "
            "yang mengaku sebagai petugas.", icon="🔒")

    kode = st.text_input("Kode Verifikasi", max_chars=6, key="rp_input_kode",
                         placeholder="000000")

    kolom_cek, kolom_ulang = st.columns(2)

    with kolom_cek:
        if st.button("Verifikasi", type="primary", use_container_width=True):
            if len(kode.strip()) != 6 or not kode.strip().isdigit():
                _pesan("error", "Kode harus berupa 6 angka.")
            else:
                berhasil, info = db.verifikasi_otp(st.session_state["rp_username"], kode.strip())
                if berhasil:
                    st.session_state["rp_terverifikasi"] = True
                    st.session_state["rp_tahap"] = "sandi_baru"
                    _pesan("sukses", "Identitas terverifikasi. Silakan buat kata sandi baru.")
                else:
                    _pesan("error", info)
            st.rerun()

    with kolom_ulang:
        sisa = _sisa_jeda()
        if sisa > 0:
            st.button(f"Kirim Ulang ({sisa}s)", disabled=True, use_container_width=True)
        elif st.button("Kirim Ulang Kode", use_container_width=True):
            _kirim_kode(st.session_state["rp_username"])
            st.rerun()

    if st.button("Batalkan"):
        reset_state()
        st.session_state["show_forgot_pass"] = False
        st.rerun()


def _tahap_sandi_baru():
    st.subheader("Buat Kata Sandi Baru")
    st.caption(f"Minimal {db.PASSWORD_MIN_PANJANG} karakter, kombinasi huruf dan angka.")

    sandi = st.text_input("Kata Sandi Baru", type="password", key="rp_sandi1")
    ulangi = st.text_input("Ulangi Kata Sandi", type="password", key="rp_sandi2")

    if sandi:
        valid, catatan = db.validasi_password(sandi)
        (st.success if valid else st.warning)(catatan)

    if st.button("Simpan Kata Sandi", type="primary", use_container_width=True):
        if not st.session_state.get("rp_terverifikasi"):
            _pesan("error", "Sesi verifikasi tidak valid. Silakan ulangi dari awal.")
            st.session_state["rp_tahap"] = "minta"
            st.rerun()

        if sandi != ulangi:
            _pesan("error", "Konfirmasi kata sandi tidak cocok.")
            st.rerun()

        valid, catatan = db.validasi_password(sandi)
        if not valid:
            _pesan("error", catatan)
            st.rerun()

        username = st.session_state["rp_username"]
        pegawai = db.ambil_pegawai(username)

        sama, _ = db.cek_password(sandi, pegawai["password_hash"])
        if sama:
            _pesan("error", "Kata sandi baru tidak boleh sama dengan yang lama.")
            st.rerun()

        db.update_user_password(username, sandi)

        # Beri tahu pemilik akun bahwa sandinya baru saja diubah.
        if mail.email_valid(pegawai.get("email")):
            mail.kirim_konfirmasi_reset(
                pegawai["email"],
                pegawai.get("nama") or username,
                datetime.now().strftime("%d %B %Y %H:%M"),
            )

        reset_state()
        st.session_state["show_forgot_pass"] = False
        st.session_state["rp_pesan"] = ("sukses", "Kata sandi berhasil diperbarui. "
                                                  "Silakan login dengan kata sandi baru.")
        st.rerun()


def render():
    """Titik masuk tunggal. Panggil ini menggantikan blok lupa password lama."""
    _init_state()
    _tampilkan_pesan()

    tahap = st.session_state["rp_tahap"]
    urutan = {"minta": 1, "verifikasi": 2, "sandi_baru": 3}
    st.progress(urutan[tahap] / 3, text=f"Langkah {urutan[tahap]} dari 3")

    if tahap == "minta":
        _tahap_minta()
    elif tahap == "verifikasi":
        _tahap_verifikasi()
    else:
        _tahap_sandi_baru()
