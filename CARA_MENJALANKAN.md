# Cara Menjalankan GovScribe

Panduan ini ditulis untuk PyCharm Community Edition. Kalau pakai VS Code,
langkahnya sama, bedanya hanya di cara membuka terminal.

---

## Langkah 1 — Buka folder di PyCharm

File > Open, pilih folder ini, lalu klik OK.

PyCharm akan mendeteksi `requirements.txt` dan menampilkan notifikasi kuning
di bagian atas: **"Install requirements"**. Klik notifikasi itu, lalu klik OK
pada jendela yang muncul.

Proses ini memakan waktu 5 sampai 15 menit karena `openai-whisper` berukuran
besar. Tunggu sampai bilah progres di bawah selesai.

Kalau notifikasinya tidak muncul, buka terminal (Alt+F12) dan ketik:

```
pip install -r requirements.txt
```

---

## Langkah 2 — Install FFmpeg

Whisper butuh FFmpeg untuk membaca file audio. Ini program terpisah, tidak
bisa diinstal lewat pip.

**Windows**, buka PowerShell sebagai Administrator:

```powershell
winget install ffmpeg
```

**macOS**:

```bash
brew install ffmpeg
```

Tutup lalu buka lagi PyCharm setelah instalasi selesai, supaya FFmpeg terbaca.

Cek berhasil dengan mengetik `ffmpeg -version` di terminal.

---

## Langkah 3 — Jalankan

Buka terminal PyCharm (Alt+F12) dan ketik:

```
streamlit run notelensi_pemerintah.py
```

Browser akan terbuka otomatis di `http://localhost:8501`.

Untuk menghentikannya, tekan Ctrl+C di terminal.

### Supaya tombol Run hijau berfungsi

Aplikasi Streamlit tidak bisa dijalankan dengan tombol Run biasa. Kalau kamu
ingin tombol hijau itu berfungsi:

1. Run > Edit Configurations
2. Klik tanda **+** di kiri atas, pilih **Python**
3. Di kolom paling atas, ganti dropdown dari **Script path** menjadi **Module name**
4. Isi Module name dengan: `streamlit`
5. Isi Parameters dengan: `run notelensi_pemerintah.py`
6. Klik OK

Setelah itu tombol hijau langsung membuka aplikasinya.

---

## Akun untuk mencoba

| NIP / Username | Password |
|---|---|
| admin_setda | admin123 |
| pns_19850110 | pns_pass_123 |
| 220235253 | password123 |

Login lewat tombol **"Login sebagai pegawai"** di kanan atas, lalu tab
**Absensi Manual**.

Ganti password akun-akun ini sebelum dipakai sungguhan.

---

## Langkah 4 — Aktifkan email OTP (opsional)

Aplikasi tetap jalan tanpa langkah ini. Yang tidak berfungsi hanya fitur
"Lupa kata sandi", dan pesannya akan bilang kredensial belum diatur.

**Siapkan App Password Gmail.** Password Gmail biasa akan selalu ditolak.

1. Buka myaccount.google.com > Security
2. Aktifkan **Verifikasi 2 Langkah** dulu, wajib
3. Cari menu **Sandi aplikasi** (App passwords), buat baru dengan nama bebas
4. Salin 16 digit yang muncul

**Masukkan ke aplikasi.** Di folder `.streamlit`, ganti nama file
`secrets.toml.contoh` menjadi `secrets.toml`, lalu isi:

```toml
SMTP_EMAIL = "emailbot_kamu@gmail.com"
SMTP_PASSWORD = "16digitdariGoogle"
NAMA_INSTANSI = "Sekretariat Daerah Kabupaten X"
```

**Uji tanpa membuka aplikasi:**

```
python email_service.py --pratinjau
```

Perintah itu membuat `pratinjau_email.html`. Buka di browser untuk melihat
tampilan emailnya.

Untuk mengirim email uji sungguhan, jalankan aplikasi, klik "Lupa kata sandi",
masukkan NIP, dan periksa kotak masuk.

---

## Kalau ada masalah

**`'streamlit' is not recognized`**
Dependensi belum terinstal. Ulangi Langkah 1.

**`ModuleNotFoundError: No module named 'whisper'`**
Aplikasi tetap terbuka, hanya fitur transkripsi yang mati. Jalankan
`pip install openai-whisper` di terminal.

**`FileNotFoundError: [WinError 2]` saat memproses audio**
FFmpeg belum terpasang atau PyCharm belum di-restart. Ulangi Langkah 2.

**`Login SMTP ditolak`**
Yang dipakai masih password Gmail biasa. Harus App Password 16 digit.

**Transkripsi berjalan sangat lama**
Normal pada percobaan pertama. Whisper mengunduh model sekitar 150 MB, lalu
memprosesnya dengan CPU. Percobaan berikutnya lebih cepat.

**Ingin mulai dari nol**
Hapus file `govscribe.db` dan `secret.key`, lalu jalankan ulang. Semua data
akan hilang dan akun default kembali seperti semula.

---

## Isi folder

| File | Fungsi |
|---|---|
| `notelensi_pemerintah.py` | Aplikasi utama, yang dijalankan |
| `database.py` | Semua penyimpanan data (SQLite) |
| `email_service.py` | Pengiriman email OTP |
| `reset_password_ui.py` | Halaman lupa kata sandi |
| `migrasi_csv_ke_db.py` | Hanya untuk memindahkan data versi lama, jalankan sekali |
| `.streamlit/secrets.toml` | Kredensial rahasia, tidak boleh di-upload |

File `govscribe.db`, `secret.key`, dan isi `registered_faces/` dibuat otomatis
saat aplikasi pertama dijalankan. Ketiganya sudah masuk `.gitignore` supaya
tidak ikut ter-upload ke GitHub.
