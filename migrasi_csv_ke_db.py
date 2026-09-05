"""
migrasi_csv_ke_db.py — Jalankan SEKALI SAJA.

Memindahkan isi log_absensi_encrypted.csv (versi lama) ke tabel `attendance`,
lalu mengarsipkan file CSV-nya. Baris yang sudah ada di database dilewati,
jadi aman kalau tidak sengaja dijalankan dua kali.

Cara pakai:
    python migrasi_csv_ke_db.py

Syarat: secret.key harus file yang SAMA dengan yang dipakai saat CSV dibuat.
Kalau kuncinya beda, isi CSV tidak bisa didekripsi dan skrip akan bilang.
"""

import os
import csv
import shutil
from datetime import datetime

import database as db

CSV_LAMA = "log_absensi_encrypted.csv"


def sudah_ada(conn, nip, waktu):
    return conn.execute(
        "SELECT 1 FROM attendance WHERE nip = ? AND waktu = ? LIMIT 1", (nip, waktu)
    ).fetchone() is not None


def main():
    db.init_db()

    if not os.path.exists(CSV_LAMA):
        print(f"Tidak ada file {CSV_LAMA}. Tidak ada yang perlu dimigrasi.")
        return

    with open(CSV_LAMA, newline="", encoding="utf-8") as f:
        baris = list(csv.DictReader(f))

    if not baris:
        print(f"{CSV_LAMA} kosong.")
        return

    masuk = dilewati = gagal = 0

    with db.db() as conn:
        for r in baris:
            waktu    = db.dekripsi_teks(r.get("Waktu_Encrypted"))
            nip      = db.dekripsi_teks(r.get("NIP_Username_Encrypted"))
            kegiatan = db.dekripsi_teks(r.get("Kegiatan_Encrypted"))
            metode   = db.dekripsi_teks(r.get("Metode_Encrypted"))
            status   = db.dekripsi_teks(r.get("Status_Encrypted"))

            if not nip or "Gagal Dekripsi" in str(nip):
                gagal += 1
                continue

            if sudah_ada(conn, nip, waktu):
                dilewati += 1
                continue

            conn.execute(
                "INSERT INTO attendance (nip, kegiatan, metode, status, arah, waktu) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (nip, kegiatan, metode, status,
                 "keluar" if status and "keluar" in str(status).lower() else "masuk",
                 waktu)
            )
            masuk += 1

    print(f"Total baris di CSV : {len(baris)}")
    print(f"  Dipindahkan      : {masuk}")
    print(f"  Sudah ada        : {dilewati}")
    print(f"  Gagal didekripsi : {gagal}")

    if gagal == len(baris):
        print("\nSemua baris gagal didekripsi. Kemungkinan secret.key sudah berganti.")
        print("File CSV tidak diarsipkan supaya kamu bisa coba lagi dengan kunci yang benar.")
        return

    arsip = f"{CSV_LAMA}.migrated-{datetime.now():%Y%m%d_%H%M%S}"
    shutil.move(CSV_LAMA, arsip)
    print(f"\nSelesai. File lama diarsipkan sebagai: {arsip}")


if __name__ == "__main__":
    main()
