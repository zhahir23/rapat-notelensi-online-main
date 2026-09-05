"""
email_service.py — Pengiriman email OTP dan notifikasi keamanan GovScribe

Template HTML-nya mengikuti pola email verifikasi yang dipakai layanan besar:
kartu gelap, logo di atas, kode besar dan mudah dibaca, peringatan jangan
diteruskan ke siapa pun, lalu footer instansi.

KONFIGURASI (jangan hardcode di file ini)

  Lokal, lewat environment variable:
      export SMTP_EMAIL="akunbot@gmail.com"
      export SMTP_PASSWORD="xxxxxxxxxxxxxxxx"   # App Password 16 digit

  Streamlit Cloud, lewat .streamlit/secrets.toml:
      SMTP_EMAIL = "akunbot@gmail.com"
      SMTP_PASSWORD = "xxxxxxxxxxxxxxxx"

  Lalu di awal notelensi_pemerintah.py, sebelum import modul ini:
      import os, streamlit as st
      for k in ("SMTP_EMAIL", "SMTP_PASSWORD", "GOVSCRIBE_KEY"):
          if k in st.secrets:
              os.environ[k] = st.secrets[k]

CATATAN GMAIL
  Password akun biasa tidak akan diterima. Wajib App Password:
  Google Account > Security > 2-Step Verification > App passwords.

Uji konfigurasi tanpa menyentuh aplikasi:
    python email_service.py --tes email_tujuan@gmail.com
Buat pratinjau tampilan tanpa mengirim apa pun:
    python email_service.py --pratinjau
"""

import os
import re
import ssl
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr, formatdate, make_msgid

# ==========================================================
# KONFIGURASI
# ==========================================================

SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_EMAIL = os.getenv("SMTP_EMAIL", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_TIMEOUT = int(os.getenv("SMTP_TIMEOUT", "20"))

# Identitas yang tampil di email
NAMA_APLIKASI = os.getenv("NAMA_APLIKASI", "GovScribe")
NAMA_INSTANSI = os.getenv("NAMA_INSTANSI", "Sekretariat Daerah")
ALAMAT_INSTANSI = os.getenv("ALAMAT_INSTANSI", "Jl. Raya Pemerintahan No. 1, Indonesia")
TAHUN = os.getenv("TAHUN_COPYRIGHT", "2026")

# Warna template
WARNA_LATAR = "#0B0B0B"
WARNA_AKSEN = "#FFB300"
WARNA_TEKS = "#FFFFFF"
WARNA_TEKS_REDUP = "#8A8A8A"

POLA_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$")


def konfigurasi_siap():
    """Cek apakah kredensial SMTP sudah diisi. Mengembalikan (siap, pesan)."""
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        return False, ("Kredensial SMTP belum diatur. Isi SMTP_EMAIL dan SMTP_PASSWORD "
                       "lewat environment variable atau st.secrets.")
    if not POLA_EMAIL.match(SMTP_EMAIL):
        return False, f"SMTP_EMAIL tidak valid: {SMTP_EMAIL}"
    return True, "Konfigurasi siap."


def email_valid(alamat):
    return bool(alamat) and bool(POLA_EMAIL.match(str(alamat).strip()))


def samarkan_email(alamat):
    """budi.santoso@gmail.com -> bu*********@gmail.com

    Dipakai di layar UI supaya alamat lengkap tidak bocor ke orang yang
    kebetulan melihat layar, tapi pemilik akun tetap mengenalinya."""
    if not email_valid(alamat):
        return "email tidak diketahui"
    nama, domain = alamat.split("@", 1)
    if len(nama) <= 2:
        return f"{nama[0]}***@{domain}"
    return f"{nama[:2]}{'*' * (len(nama) - 2)}@{domain}"


# ==========================================================
# TEMPLATE HTML
# ==========================================================

def _kerangka(isi_html):
    """Pembungkus kartu gelap. Semua CSS inline supaya aman di klien email."""
    return f"""<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{NAMA_APLIKASI}</title>
</head>
<body style="margin:0;padding:0;background-color:#F4F4F4;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
       style="background-color:#F4F4F4;padding:24px 12px;">
  <tr>
    <td align="center">
      <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0"
             style="max-width:600px;width:100%;background-color:{WARNA_LATAR};">
        <tr>
          <td style="padding:44px 44px 8px 44px;">
            <table role="presentation" cellpadding="0" cellspacing="0" border="0">
              <tr>
                <td width="64" height="64" align="center" valign="middle"
                    style="background-color:{WARNA_AKSEN};border-radius:14px;
                           font-family:Arial,Helvetica,sans-serif;font-size:26px;
                           font-weight:bold;color:#111111;letter-spacing:-1px;">
                  GS
                </td>
              </tr>
            </table>
          </td>
        </tr>
{isi_html}
        <tr>
          <td style="padding:0 44px;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
              <tr><td style="border-top:1px solid #3A3A3A;font-size:0;line-height:0;">&nbsp;</td></tr>
            </table>
          </td>
        </tr>
        <tr>
          <td style="padding:22px 44px 44px 44px;font-family:Arial,Helvetica,sans-serif;
                     font-size:12px;line-height:19px;color:{WARNA_TEKS_REDUP};">
            Email administratif ini dikirim otomatis oleh sistem {NAMA_APLIKASI},
            {NAMA_INSTANSI}, {ALAMAT_INSTANSI}. Mohon tidak membalas email ini
            karena kotak masuknya tidak dipantau.
            <br><br>
            &copy; {TAHUN} {NAMA_INSTANSI}. Seluruh hak cipta dilindungi.
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>
</body>
</html>"""


def template_otp(kode, nama_pengguna, masa_berlaku_menit=10):
    isi = f"""
        <tr>
          <td style="padding:34px 44px 0 44px;font-family:Arial,Helvetica,sans-serif;">
            <div style="font-size:25px;font-weight:bold;color:{WARNA_TEKS};line-height:32px;">
              Kode Verifikasi Email
            </div>
          </td>
        </tr>
        <tr>
          <td style="padding:18px 44px 0 44px;font-family:Arial,Helvetica,sans-serif;
                     font-size:16px;line-height:25px;color:{WARNA_TEKS};">
            Halo <strong>{nama_pengguna}</strong>, masukkan kode berikut pada layar
            verifikasi identitas:
          </td>
        </tr>
        <tr>
          <td style="padding:26px 44px 0 44px;font-family:'Courier New',Courier,monospace;
                     font-size:42px;font-weight:bold;letter-spacing:7px;color:{WARNA_TEKS};">
            {kode}
          </td>
        </tr>
        <tr>
          <td style="padding:26px 44px 0 44px;font-family:Arial,Helvetica,sans-serif;
                     font-size:16px;line-height:25px;color:{WARNA_TEKS};">
            Kode ini berlaku selama {masa_berlaku_menit} menit. Jika layar verifikasi
            sudah tertutup, silakan ulangi proses lupa kata sandi dari awal.
          </td>
        </tr>
        <tr>
          <td style="padding:22px 44px 34px 44px;font-family:Arial,Helvetica,sans-serif;
                     font-size:16px;line-height:25px;color:{WARNA_TEKS};">
            Jangan teruskan atau berikan kode ini kepada siapa pun, termasuk kepada
            pihak yang mengaku sebagai petugas. Jika Anda tidak meminta kode ini,
            abaikan email ini dan segera ganti kata sandi akun Anda.
          </td>
        </tr>
"""
    teks = f"""{NAMA_APLIKASI} - Kode Verifikasi Email

Halo {nama_pengguna},

Masukkan kode berikut pada layar verifikasi identitas:

    {kode}

Kode ini berlaku selama {masa_berlaku_menit} menit.

Jangan teruskan atau berikan kode ini kepada siapa pun, termasuk kepada pihak
yang mengaku sebagai petugas. Jika Anda tidak meminta kode ini, abaikan email
ini dan segera ganti kata sandi akun Anda.

--
{NAMA_APLIKASI}, {NAMA_INSTANSI}
Email ini dikirim otomatis, mohon tidak dibalas.
"""
    return _kerangka(isi), teks


def template_konfirmasi_reset(nama_pengguna, waktu):
    isi = f"""
        <tr>
          <td style="padding:34px 44px 0 44px;font-family:Arial,Helvetica,sans-serif;">
            <div style="font-size:25px;font-weight:bold;color:{WARNA_TEKS};line-height:32px;">
              Kata Sandi Berhasil Diubah
            </div>
          </td>
        </tr>
        <tr>
          <td style="padding:18px 44px 0 44px;font-family:Arial,Helvetica,sans-serif;
                     font-size:16px;line-height:25px;color:{WARNA_TEKS};">
            Halo <strong>{nama_pengguna}</strong>, kata sandi akun {NAMA_APLIKASI} Anda
            berhasil diubah pada <strong>{waktu} WIB</strong>.
          </td>
        </tr>
        <tr>
          <td style="padding:26px 44px 34px 44px;font-family:Arial,Helvetica,sans-serif;
                     font-size:16px;line-height:25px;color:{WARNA_TEKS};">
            Jika perubahan ini bukan Anda yang melakukan, segera hubungi administrator
            sistem di instansi Anda. Akun kemungkinan telah diakses pihak lain.
          </td>
        </tr>
"""
    teks = f"""{NAMA_APLIKASI} - Kata Sandi Berhasil Diubah

Halo {nama_pengguna},

Kata sandi akun {NAMA_APLIKASI} Anda berhasil diubah pada {waktu} WIB.

Jika perubahan ini bukan Anda yang melakukan, segera hubungi administrator
sistem di instansi Anda.

--
{NAMA_APLIKASI}, {NAMA_INSTANSI}
Email ini dikirim otomatis, mohon tidak dibalas.
"""
    return _kerangka(isi), teks


# ==========================================================
# PENGIRIMAN
# ==========================================================

def _kirim(email_tujuan, subjek, html, teks):
    """Pengirim internal. Mengembalikan (berhasil, pesan)."""
    siap, pesan = konfigurasi_siap()
    if not siap:
        return False, pesan

    if not email_valid(email_tujuan):
        return False, f"Alamat email tujuan tidak valid: {email_tujuan}"

    pesan_email = MIMEMultipart("alternative")
    pesan_email["Subject"] = subjek
    pesan_email["From"] = formataddr((f"{NAMA_APLIKASI} System", SMTP_EMAIL))
    pesan_email["To"] = email_tujuan
    pesan_email["Date"] = formatdate(localtime=True)
    pesan_email["Message-ID"] = make_msgid()
    pesan_email["Auto-Submitted"] = "auto-generated"

    # Bagian teks harus lebih dulu, HTML terakhir. Klien email menampilkan
    # bagian terakhir yang bisa dirender.
    pesan_email.attach(MIMEText(teks, "plain", "utf-8"))
    pesan_email.attach(MIMEText(html, "html", "utf-8"))

    try:
        konteks = ssl.create_default_context()
        if SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=SMTP_TIMEOUT, context=konteks)
        else:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=SMTP_TIMEOUT)
            server.starttls(context=konteks)

        with server:
            server.login(SMTP_EMAIL, SMTP_PASSWORD.replace(" ", ""))
            server.sendmail(SMTP_EMAIL, email_tujuan, pesan_email.as_string())

        return True, "Email berhasil dikirim."

    except smtplib.SMTPAuthenticationError:
        return False, ("Login SMTP ditolak. Untuk Gmail, gunakan App Password 16 digit, "
                       "bukan kata sandi akun biasa.")
    except smtplib.SMTPRecipientsRefused:
        return False, f"Alamat tujuan ditolak server: {email_tujuan}"
    except smtplib.SMTPServerDisconnected:
        return False, "Koneksi ke server email terputus. Coba lagi."
    except (TimeoutError, OSError) as e:
        return False, f"Tidak bisa terhubung ke server email: {e}"
    except smtplib.SMTPException as e:
        return False, f"Gagal mengirim email: {e}"


def kirim_otp(email_tujuan, kode, nama_pengguna, masa_berlaku_menit=10):
    """Kirim kode OTP. Mengembalikan (berhasil, pesan)."""
    html, teks = template_otp(kode, nama_pengguna, masa_berlaku_menit)
    return _kirim(email_tujuan, f"[{kode}] Kode Verifikasi {NAMA_APLIKASI}", html, teks)


def kirim_konfirmasi_reset(email_tujuan, nama_pengguna, waktu):
    """
    Dikirim setelah kata sandi berhasil diubah. Ini yang membuat pemilik akun
    tahu kalau ada orang lain yang berhasil menguasai akunnya.
    """
    html, teks = template_konfirmasi_reset(nama_pengguna, waktu)
    return _kirim(email_tujuan, f"Kata Sandi {NAMA_APLIKASI} Berhasil Diubah", html, teks)


# ==========================================================
# UTILITAS PENGEMBANGAN
# ==========================================================

def pratinjau(path="pratinjau_email.html"):
    """Tulis contoh kedua template ke satu file HTML untuk dilihat di browser."""
    html_otp, _ = template_otp("143077", "Budi Santoso")
    html_reset, _ = template_konfirmasi_reset("Budi Santoso", "02 September 2026 20:34")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html_otp)
        f.write("\n<hr style='margin:40px 0;border:0;border-top:2px dashed #CCC;'>\n")
        f.write(html_reset)
    return path


if __name__ == "__main__":
    import sys

    if "--pratinjau" in sys.argv:
        print("Pratinjau tersimpan di:", pratinjau())

    elif "--tes" in sys.argv:
        tujuan = sys.argv[sys.argv.index("--tes") + 1]
        siap, pesan = konfigurasi_siap()
        print("Konfigurasi:", pesan)
        if siap:
            ok, pesan = kirim_otp(tujuan, "123456", "Uji Coba")
            print("Hasil:", pesan)

    else:
        print(__doc__)
