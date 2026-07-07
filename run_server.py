# -*- coding: utf-8 -*-
"""
IPmanager — Windows ishga tushiruvchi (launcher).

Bu fayl .exe ning kirish nuqtasi (entry point). Vazifalari:
  1. config.ini ni o'qiydi (exe yonida) — ma'lumot, log, backup papkalari.
  2. IPMANAGER_DATA_DIR muhit o'zgaruvchisini o'rnatadi (app.py shuni o'qiydi).
  3. Log fayllarini sozlaydi (aylanma / rotating — juda katta bo'lib ketmasin).
  4. Kunlik avtomatik backup (zaxira) ipini (thread) ishga tushiradi.
  5. Waitress WSGI serveri bilan Flask ilovani xizmat qiladi (Gunicorn Windows'da
     ishlamaydi — uning o'rniga Waitress, u sof Windows uchun mo'ljallangan).
  6. Standart brauzerni avtomatik ochadi.
"""
import os
import sys
import time
import shutil
import sqlite3
import logging
import threading
import webbrowser
import subprocess
import configparser
from logging.handlers import RotatingFileHandler


# ---------------------------------------------------------------------------
# 1) Asosiy papkani aniqlash (exe yoni yoki script yoni)
# ---------------------------------------------------------------------------
def app_base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)   # .exe joylashgan papka
    return os.path.dirname(os.path.abspath(__file__))


BASE = app_base_dir()


# ---------------------------------------------------------------------------
# 2) config.ini ni o'qish (yo'q bo'lsa — standart qiymatlar)
# ---------------------------------------------------------------------------
def load_config():
    cfg = configparser.ConfigParser()
    ini_path = os.path.join(BASE, "config.ini")

    # Standart qiymatlar — exe yonidagi papkalar
    defaults = {
        "data_dir": os.path.join(BASE, "data"),
        "log_dir": os.path.join(BASE, "logs"),
        "backup_dir": os.path.join(BASE, "backups"),
        "host": "127.0.0.1",
        "port": "5000",
        "backup_keep_days": "30",
        # ui_mode: qanday ochilsin?
        #   auto    = avval mustaqil oyna (pywebview), bo'lmasa standart brauzer
        #   browser = to'g'ridan-to'g'ri kompyuterdagi standart brauzer
        #   window  = faqat mustaqil oyna (pywebview)
        "ui_mode": "auto",
    }

    if os.path.exists(ini_path):
        cfg.read(ini_path, encoding="utf-8")
        if cfg.has_section("paths"):
            for k in ("data_dir", "log_dir", "backup_dir"):
                if cfg.has_option("paths", k):
                    defaults[k] = cfg.get("paths", k)
        if cfg.has_section("server"):
            for k in ("host", "port", "ui_mode"):
                if cfg.has_option("server", k):
                    defaults[k] = cfg.get("server", k)
        if cfg.has_section("backup"):
            if cfg.has_option("backup", "keep_days"):
                defaults["backup_keep_days"] = cfg.get("backup", "keep_days")

    # Papkalarni yaratamiz (yo'q bo'lsa)
    for k in ("data_dir", "log_dir", "backup_dir"):
        os.makedirs(defaults[k], exist_ok=True)

    return defaults


CONFIG = load_config()

# app.py ma'lumot bazasini shu papkaga yozishi uchun env o'zgaruvchi.
# MUHIM: bu 'import app' dan OLDIN o'rnatilishi shart.
os.environ["IPMANAGER_DATA_DIR"] = CONFIG["data_dir"]


# ---------------------------------------------------------------------------
# 3) Loglarni sozlash (aylanma fayl — max 2MB, 5 ta nusxa saqlanadi)
# ---------------------------------------------------------------------------
def setup_logging(log_dir):
    log_file = os.path.join(log_dir, "ipmanager.log")
    handler = RotatingFileHandler(
        log_file, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    # Konsolga ham chiqaramiz (agar oyna ko'rinsa)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)
    return logging.getLogger("ipmanager")


log = setup_logging(CONFIG["log_dir"])


# ---------------------------------------------------------------------------
# 4) Kunlik avtomatik backup (zaxira nusxa)
# ---------------------------------------------------------------------------
def make_backup():
    """ipmanager.db ning xavfsiz (online) nusxasini backup papkasiga oladi."""
    src = os.path.join(CONFIG["data_dir"], "ipmanager.db")
    if not os.path.exists(src):
        return
    stamp = time.strftime("%Y-%m-%d_%H%M%S")
    dest = os.path.join(CONFIG["backup_dir"], f"ipmanager_{stamp}.db")
    try:
        # sqlite3 .backup — baza ishlab turgan paytda ham buzilmasdan nusxalaydi
        con = sqlite3.connect(src)
        bck = sqlite3.connect(dest)
        with bck:
            con.backup(bck)
        bck.close()
        con.close()
        log.info("Zaxira nusxa olindi: %s", dest)
        prune_old_backups()
    except Exception as e:
        log.error("Zaxira olishda xato: %s", e)


def prune_old_backups():
    """keep_days dan eski zaxiralarni o'chiradi."""
    try:
        keep = int(CONFIG["backup_keep_days"])
    except ValueError:
        keep = 30
    cutoff = time.time() - keep * 86400
    for name in os.listdir(CONFIG["backup_dir"]):
        if name.startswith("ipmanager_") and name.endswith(".db"):
            p = os.path.join(CONFIG["backup_dir"], name)
            if os.path.getmtime(p) < cutoff:
                try:
                    os.remove(p)
                    log.info("Eski zaxira o'chirildi: %s", name)
                except OSError:
                    pass


def backup_loop():
    """Har 24 soatda bir marta backup oladi. Ishga tushganda ham bitta oladi."""
    # Dastur ishga tushgach 30 soniya kutib, birinchi backup
    time.sleep(30)
    make_backup()
    while True:
        time.sleep(24 * 3600)   # 24 soat
        make_backup()


# ---------------------------------------------------------------------------
# 5) Serverni fon rejimida ishga tushirish (Waitress)
# ---------------------------------------------------------------------------
def run_server(application, host, port):
    """Waitress serverni ishga tushiradi. Bu alohida ipda (thread) chaqiriladi,
    chunki asosiy ip (main thread) dastur oynasi (GUI) uchun band bo'ladi."""
    from waitress import serve
    serve(application, host=host, port=port, threads=8)


def wait_for_server(url, timeout=10):
    """Server javob bera boshlaguncha kutamiz (oyna ochilishidan oldin)."""
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except Exception:
            time.sleep(0.3)
    return False


# ---------------------------------------------------------------------------
# 6) Foydalanuvchi interfeysini ochish — 3 bosqichli, ishonchli
# ---------------------------------------------------------------------------
def default_browser_exe():
    """
    Windows registridan foydalanuvchining STANDART (default) brauzerini aniqlaydi.
    Shunda dastur aynan Edge'ni emas, kompyuterda o'rnatilgan/tanlangan brauzerni
    (Chrome, Edge, Yandex, Firefox — qaysi biri bo'lsa) ishlatadi.
    """
    try:
        import winreg
    except ImportError:
        return None      # Windows emas (masalan, sinov Linux'da)
    try:
        # https havolalari uchun foydalanuvchi tanlagan brauzerning ProgID si
        assoc = r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, assoc) as k:
            progid, _ = winreg.QueryValueEx(k, "ProgId")
        # ProgID -> ochish buyrug'i (masalan: "C:\...\chrome.exe" --single-argument %1)
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT,
                            progid + r"\shell\open\command") as k:
            cmd, _ = winreg.QueryValueEx(k, "")
        import shlex
        parts = shlex.split(cmd, posix=False)
        exe = parts[0].strip('"') if parts else None
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass
    return None


def is_chromium(exe):
    """Brauzer Chromium asoslimi? (Chrome/Edge/Brave/Yandex/Opera/Vivaldi)
    Faqat ular '--app=' rejimini (tabsiz alohida oyna) qo'llab-quvvatlaydi."""
    name = os.path.basename(exe).lower()
    return any(x in name for x in
               ("chrome", "msedge", "edge", "brave", "vivaldi", "opera", "yandex"))


def open_in_default_browser(url):
    """Kompyuterdagi standart brauzerni ochadi. Chromium bo'lsa — 'app' rejimida
    (tabsiz, alohida oyna); aks holda (masalan Firefox) — oddiy oynada."""
    exe = default_browser_exe()
    if exe:
        try:
            if is_chromium(exe):
                subprocess.Popen([exe, f"--app={url}"])
                log.info("Standart brauzer app-rejimida ochildi: %s", exe)
                return "app-mode"
            else:
                subprocess.Popen([exe, url])
                log.info("Standart brauzer ochildi: %s", exe)
                return "default-browser"
        except Exception as e:
            log.warning("Standart brauzer ishlamadi (%s): %s", exe, e)
    # Registrdan topilmasa — Python'ning webbrowser moduli (baribir standartni ochadi)
    log.info("webbrowser moduli orqali ochilmoqda")
    webbrowser.open(url)
    return "browser"


def open_ui(url, mode="auto", title="IPmanager"):
    """
    Dastur oynasini ochadi. ui_mode ga qarab:
      auto    : avval pywebview (mustaqil oyna), bo'lmasa standart brauzer
      window  : faqat pywebview
      browser : to'g'ridan-to'g'ri standart brauzer (oynasiz, tez)
    """
    # browser rejimi — pywebview'ni umuman sinamaymiz
    if mode == "browser":
        return open_in_default_browser(url)

    # --- pywebview: chinakam mustaqil oyna (eng chiroyli) ---
    try:
        import webview
        webview.create_window(title, url, width=1280, height=820,
                              min_size=(1024, 700))
        log.info("Oyna pywebview orqali ochilmoqda (native window)")
        webview.start()          # oyna yopilguncha shu yerda "bloklanadi"
        return "webview"
    except Exception as e:
        if mode == "window":
            log.error("pywebview ishlamadi (%s), 'window' rejimi tanlangan.", e)
            # window majburiy edi, lekin baribir foydalanuvchi ko'rsin
        log.warning("pywebview ishlamadi (%s). Standart brauzerga o'tamiz.", e)

    # --- standart brauzer (kompyuterda qaysi bo'lsa) ---
    return open_in_default_browser(url)


# ---------------------------------------------------------------------------
# 7) Asosiy funksiya
# ---------------------------------------------------------------------------
def main():
    host = CONFIG["host"]
    try:
        port = int(CONFIG["port"])
    except ValueError:
        port = 5000

    log.info("=" * 60)
    log.info("IPmanager ishga tushmoqda")
    log.info("Ma'lumot papkasi : %s", CONFIG["data_dir"])
    log.info("Log papkasi      : %s", CONFIG["log_dir"])
    log.info("Backup papkasi   : %s", CONFIG["backup_dir"])
    log.info("Manzil           : http://%s:%s", host, port)
    log.info("=" * 60)

    # app ni ENDI import qilamiz (env o'zgaruvchi allaqachon o'rnatilgan)
    import app as flask_app_module
    application = flask_app_module.app

    # Backup ipini fon rejimida ishga tushiramiz
    threading.Thread(target=backup_loop, daemon=True).start()

    # Serverni fon ipida ishga tushiramiz (asosiy ip oyna uchun kerak)
    threading.Thread(
        target=run_server, args=(application, host, port), daemon=True
    ).start()

    # Server tayyor bo'lguncha kutamiz, keyin oynani ochamiz
    url = f"http://{host}:{port}"
    wait_for_server(url, timeout=10)

    mode = open_ui(url, mode=CONFIG.get("ui_mode", "auto"))

    # Agar pywebview ishlatilgan bo'lsa — oyna yopilganda dastur ham yopiladi.
    # Aks holda (app-rejimi/brauzer) — serverni tirik saqlash uchun kutamiz.
    if mode != "webview":
        log.info("Server ishlab turibdi. Yopish uchun bu oynani/jarayonni to'xtating.")
        while True:
            time.sleep(3600)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.exception("Fatal xato: %s", e)
        # Oyna darhol yopilib ketmasligi uchun (foydalanuvchi xatoni ko'rsin)
        input("Xato yuz berdi. Chiqish uchun Enter bosing...")
