# IPmanager — Windows `.exe` yasash qo'llanmasi

Bu qo'llanma manba fayllardan **IPmanager-Setup.exe** o'rnatuvchisini yasashni bosqichma-bosqich tushuntiradi.

> **MUHIM:** `.exe` faylni **Windows kompyuterda** yasash shart. PyInstaller cross-compiler emas — Linux'da Windows dasturi yasay olmaydi. Barcha qadamlar Windows'da bajariladi.

---

## 0. Nima uchun Windows versiyasi boshqacha? (Linux serverdan farqi)

| Jihat | Linux server (192.168.202.51) | Windows `.exe` |
|---|---|---|
| WSGI server | Gunicorn | **Waitress** (Gunicorn Windows'da ishlamaydi — u faqat Unix uchun) |
| Ishga tushirish | systemd xizmati | `.exe` ni ikki marta bosish |
| Reverse proxy / TLS | Nginx + HTTPS | Yo'q (bitta kompyuterda mahalliy, `127.0.0.1` — tarmoqqa chiqmaydi) |
| Paketlash | venv + kod fayllar | Hammasi bitta `.exe` ichida (Python o'rnatish shart emas) |
| Ma'lumot joyi | `/opt/ipmanager` | O'rnatishda tanlangan papka (`config.ini`) |

Bitta kompyuterda, mahalliy ishlagani uchun Nginx/TLS shart emas — barcha aloqa kompyuterning ichida (`127.0.0.1`) qoladi.

---

## 1. Kerakli dasturlar (Windows'ga bir marta o'rnatiladi)

| Dastur | Yuklab olish | Vazifasi |
|---|---|---|
| **Python 3.11+** | python.org/downloads | Dasturni ishga tushirish va yig'ish uchun |
| **Inno Setup 6** | jrsoftware.org/isdl.php | `Setup.exe` o'rnatuvchini yasash uchun |

> Python o'rnatishda **"Add Python to PATH"** katagini albatta belgilang.

Internet faqat shu bosqichda (kutubxonalar yuklab olish) kerak. Yasab bo'lgach, `.exe` internetsiz ishlaydi.

---

## 2. Loyihani tayyorlash

Ushbu `ipmanager-windows` papkasini Windows kompyuterga ko'chiring (masalan `C:\build\ipmanager-windows`). Papka ichida quyidagilar bo'lishi kerak:

```
ipmanager-windows\
├── app.py                    (asosiy Flask ilova)
├── run_server.py             (ishga tushiruvchi — .exe kirish nuqtasi)
├── config.ini                (standart sozlamalar)
├── requirements-windows.txt  (kutubxonalar ro'yxati)
├── ipmanager.spec            (PyInstaller sozlamasi)
├── installer.iss             (Inno Setup skripti)
├── icon.ico                  (dastur belgisi)
├── static\                   (CSS, JS, vendor kutubxonalar)
└── templates\                (index.html)
```

---

## 3. Kutubxonalarni o'rnatish

Papkada **Command Prompt** (cmd) yoki PowerShell oching (papkada Shift+O'ng tugma → "Open in Terminal"):

```bat
cd C:\build\ipmanager-windows
pip install -r requirements-windows.txt
```

Bu Flask, Werkzeug, Waitress va PyInstaller ni o'rnatadi.

---

## 4. Yasashdan OLDIN sinab ko'rish (muhim qadam)

`.exe` yasashdan oldin, dastur oddiy holatda ishlashiga ishonch hosil qiling:

```bat
python run_server.py
```

Kutilgan natija: brauzer avtomatik ochilib, `http://127.0.0.1:5000` da setup sahifasi chiqadi. Agar ishlasa — `Ctrl+C` bilan to'xtatib, yasashga o'tamiz. Ishlamasa — xatoni yozib oling.

> Bu sinovda ma'lumot `config.ini` dagi `data_dir` (standart `C:\IPmanager\data`) ga yoziladi. Sinov uchun uni papka yonidagi joyga o'zgartirsangiz ham bo'ladi.

---

## 5. `.exe` yasash (PyInstaller)

```bat
pyinstaller ipmanager.spec
```

Bu bir necha daqiqa davom etadi. Tugagach, natija `dist\IPmanager\` papkasida bo'ladi:

```
dist\IPmanager\
├── IPmanager.exe        ← asosiy dastur
├── _internal\           ← kerakli kutubxonalar (avtomatik)
└── ...
```

**`.exe` ni sinab ko'ring:**

```bat
dist\IPmanager\IPmanager.exe
```

Brauzer ochilib, dastur ishga tushishi kerak. Ishlagach yopishingiz mumkin.

> **Maslahat:** Agar `.exe` ishlamay, sababi ko'rinmasa — `ipmanager.spec` faylida `console=False` ni `console=True` ga o'zgartirib, qayta yasang. Shunda qora oyna ochilib, xato matni ko'rinadi. Muammo hal bo'lgach, `console=False` ga qaytaring.

---

## 6. O'rnatuvchi (`Setup.exe`) yasash (Inno Setup)

1. **Inno Setup Compiler** dasturini oching.
2. `File → Open` orqali `installer.iss` faylini tanlang.
3. `Build → Compile` (yoki **F9**) bosing.
4. Natija: papkada **`Output\IPmanager-Setup.exe`** yaratiladi.

Ana shu `IPmanager-Setup.exe` — yakuniy, tarqatiladigan fayl.

---

## 7. O'rnatish (istalgan kompyuterda)

`IPmanager-Setup.exe` ni ishga tushiring. O'rnatuvchi ketma-ket so'raydi:

| Qadam | Nima so'raladi | Standart |
|---|---|---|
| 1 | **Dastur qayerga o'rnatilsin** | `C:\Program Files\IPmanager` |
| 2 | **Ma'lumot/log/backup papkasi** | `C:\IPmanager-data` |
| 3 | Ish stoli yorlig'i kerakmi | (ixtiyoriy) |

O'rnatuvchi avtomatik ravishda:
- Dasturni tanlangan joyga ko'chiradi
- `data`, `logs`, `backups` papkalarini yaratadi
- `config.ini` ni tanlangan yo'llar bilan to'ldiradi
- Start menyu va ish stoli yorliqlarini yaratadi

---

## 8. Foydalanish

- Ish stoli yoki Start menyudagi **IPmanager** yorlig'ini bosing.
- Dastur **o'z oynasida** (native window, brauzer emas) ochiladi — xuddi oddiy Windows dasturi kabi.
- Birinchi marta — **Superadmin** hisobini yarating.
- Barcha adminlar shu kompyuterga kelib, o'z login-paroli bilan kiradi.

> **Native oyna qanday ishlaydi?** Dastur `pywebview` orqali Windows'ning ichki
> **Edge WebView2** dvigatelidan foydalanib, HTML'ni o'z oynasida ko'rsatadi.
> WebView2 Runtime Windows 10/11 da oldindan o'rnatilgan (Edge bilan birga keladi).
> Agar biror sabab bilan native oyna ochilmasa, dastur **avtomatik ravishda**
> Edge app-rejimiga, keyin oddiy brauzerga o'tadi — ya'ni har doim ishlaydi.

| Nima | Qayerda (standart) |
|---|---|
| Ma'lumot bazasi | `C:\IPmanager-data\data\ipmanager.db` |
| Loglar | `C:\IPmanager-data\logs\ipmanager.log` |
| Zaxiralar (kunlik) | `C:\IPmanager-data\backups\` |

Backup avtomatik: dastur ochiq turgan vaqtda har 24 soatda bir marta, va ochilganda bir marta zaxira oladi. 30 kundan eskilari avtomatik o'chiriladi (`config.ini` da o'zgartirish mumkin).

---

## 9. Ko'p uchraydigan savollar / muammolar

| Muammo | Sabab va yechim |
|---|---|
| Antivirus `.exe` ni "shubhali" deydi | PyInstaller dasturlarida keng tarqalgan **soxta signal** (false positive). Dasturni "istisno" (exception) ro'yxatiga qo'shing yoki korporativ antivirus siyosatida ruxsat bering |
| Native oyna emas, brauzer ochildi | Demak pywebview yig'ilmagan yoki WebView2 Runtime yo'q. Dastur baribir ishlaydi (avtomatik brauzerga o'tdi). Native oyna uchun: (1) `pip install pywebview` bajarilganini tekshiring, (2) yig'ishda `pyinstaller --collect-all webview ipmanager.spec` deb urinib ko'ring, (3) WebView2 Runtime ni o'rnating (developer.microsoft.com dan "Evergreen Standalone Installer") |
| Brauzer ochilmadi | `config.ini` dagi `port` band bo'lishi mumkin (masalan, boshqa dastur 5000 ni ishlatyapti). `port = 5001` ga o'zgartiring |
| Boshqa kompyuterlar ham kirsin | `config.ini` da `host = 0.0.0.0` qiling + Windows Firewall'da 5000-portga ruxsat bering. **Diqqat:** bunda TLS yo'q, parollar shifrsiz ketadi — faqat ishonchli ichki tarmoqda |
| Dasturni yangilash | Yangi `.exe` ni qayta yasang, `IPmanager-Setup.exe` ni qayta ishga tushiring. **Ma'lumot papkasi (`C:\IPmanager-data`) o'zgarmaydi** — ma'lumotlar saqlanadi |
| Dasturni o'chirish | Windows "Programs & Features" orqali. **Ma'lumot papkasi o'chmaydi** — uni qo'lda o'chirasiz (agar kerak bo'lsa) |
| Zaxiradan tiklash | Dasturni yoping → `backups\` dan kerakli `.db` faylni `data\ipmanager.db` ustiga nusxalang → qayta oching |

---

## 10. Xulosa — yasash oqimi (qisqacha)

```
1. pip install -r requirements-windows.txt   (kutubxonalar)
2. python run_server.py                       (sinov)
3. pyinstaller ipmanager.spec                 (.exe yasash)
4. Inno Setup'da installer.iss → Compile (F9) (Setup.exe yasash)
5. IPmanager-Setup.exe                         (o'rnatish)
```

Savol yoki muammo chiqsa — qaysi qadamda ekanini va xato matnini yozib yuboring.
