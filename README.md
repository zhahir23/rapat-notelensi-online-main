> UNTUK PEMERINTAH YANG BERBASIS NOTELENSI

- FITUR YANG ADA DI SINI
1. generate Rekam suara ke text 
2. Upload suara
3. Rekam suara
4. edit notelensi
5. kirim notelensi ke publik/user
6. edit berita untuk ke uuser
7. Riwayat absensi 
8. Sandi bersifat enyrip dan ke simpan .key
9. regis face juga pas daftar pas regis maupun out ke simpan
10. akan ada peringatan kalo lagi log out dan tidak foto sebelum balik

- FITUR YANG BELUM DAN BARU
1. kode otp ketika lupa password bisa melalui Gmail atau ga no wa
2. benerin berita jangan di gabung ama pns tapi bisa ke publish ke website user, kalo bisa mah ad website berita untuk user gitu
3. kalo keburu dan opsional pake sistem face track langsung ke diteksi si biodata pns nya
4. memperbagus UI nya lebih enak di liat    

## Konfigurasi Email OTP

Email tujuan dapat berupa alamat apa pun. Gmail digunakan sebagai akun pengirim
yang terautentikasi melalui App Password.

Atur variabel berikut sebelum menjalankan aplikasi:

```powershell
$env:SENDER_EMAIL = "akun-pengirim@gmail.com"
$env:SENDER_PASSWORD = "app-password-16-karakter"
streamlit run notelensi_pemerintah.py
```

`SENDER_PASSWORD` harus berupa App Password Google, bukan password login Gmail biasa.