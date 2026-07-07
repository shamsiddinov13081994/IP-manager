# -*- coding: utf-8 -*-
"""
Kiberxavfsizlik Departamenti - IP Manzillar Hisobini Yuritish Dasturi
Backend: Flask + SQLite. To'liq offline, lokal tarmoqda ishlaydi.

Ishga tushirish:
    pip install -r requirements.txt
    python app.py
Standart manzil: http://0.0.0.0:5000
"""
import os
import sys
import re
import time
import sqlite3
import secrets
import ipaddress
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, g, request, jsonify, session, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash


# ---------------------------------------------------------------------------
# Yo'llar (paths) — Windows .exe va oddiy Python uchun moslashuvchan
# ---------------------------------------------------------------------------
# Ikki xil papka bor va ular FARQ qiladi:
#   1) RESURS papkasi (static/templates) — o'zgarmas, faqat o'qiladi.
#      PyInstaller bilan .exe qilinganda bu fayllar vaqtinchalik _MEIPASS
#      papkasiga ochiladi (yozib bo'lmaydi!). Shuning uchun uni alohida topamiz.
#   2) MA'LUMOT papkasi (ipmanager.db, secret.key) — yoziladi, doimiy saqlanadi.
#      Bu papkani o'rnatuvchi (installer) tanlaydi va IPMANAGER_DATA_DIR
#      muhit o'zgaruvchisi (environment variable) orqali uzatadi.
def _resource_dir():
    # PyInstaller bilan "muzlatilgan" (frozen) bo'lsa — resurslar _MEIPASS da
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def _data_dir():
    # Ma'lumot yoziladigan papka. Ustuvorlik: env o'zgaruvchi -> exe yonidagi
    # 'data' papka (frozen) -> script papkasi (oddiy Python / dev)
    d = os.environ.get("IPMANAGER_DATA_DIR")
    if not d:
        if getattr(sys, "frozen", False):
            base = os.path.dirname(sys.executable)
        else:
            base = os.path.dirname(os.path.abspath(__file__))
        d = os.path.join(base, "data")
    os.makedirs(d, exist_ok=True)
    return d


RES_DIR = _resource_dir()
DATA_DIR = _data_dir()
DB_PATH = os.path.join(DATA_DIR, "ipmanager.db")
SECRET_KEY_PATH = os.path.join(DATA_DIR, "secret.key")

app = Flask(
    __name__,
    static_folder=os.path.join(RES_DIR, "static"),
    template_folder=os.path.join(RES_DIR, "templates"),
)

# ---------------------------------------------------------------------------
# Doimiy SECRET_KEY
# ---------------------------------------------------------------------------
if os.path.exists(SECRET_KEY_PATH):
    with open(SECRET_KEY_PATH, "r") as f:
        app.secret_key = f.read().strip()
else:
    key = secrets.token_hex(32)
    with open(SECRET_KEY_PATH, "w") as f:
        f.write(key)
    app.secret_key = key

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,       # cookie'ni JS o'qiy olmaydi (XSS himoyasi)
    SESSION_COOKIE_SAMESITE="Lax",      # boshqa saytdan yuborilgan so'rovlarda cookie cheklanadi
    PERMANENT_SESSION_LIFETIME=timedelta(hours=4),  # sessiya 4 soatdan keyin tugaydi
)

# ---------------------------------------------------------------------------
# Konstantalar
# ---------------------------------------------------------------------------
ROLE_LABEL = {"superadmin": "Superadmin", "admin": "Admin", "user": "Foydalanuvchi"}
VALID_ROLES = ("superadmin", "admin", "user")
VALID_CATEGORIES = ("users", "devices")
MIN_PASSWORD_LEN = 8

# Brute-force himoyasi
LOGIN_MAX_ATTEMPTS = 5          # necha marta noto'g'ri urinishdan keyin
LOGIN_WINDOW_SEC = 15 * 60      # necha soniyalik oynada
LOGIN_LOCK_SEC = 15 * 60        # blok muddati
_login_attempts = {}           # {username: [timestamp, ...]}

# Diff (o'zgarishlarni loglash) uchun ustun nomlari
USERS_FIELD_LABELS = {
    "ip": "IP", "department": "BO'LIM", "position": "LAVOZIM",
    "full_name": "F.I.O.", "room": "XONA", "phone": "TELEFON",
}
DEVICE_FIELD_LABELS = {
    "ip": "IP", "mask": "MASKA", "okrug": "OKRUG", "harbiy_qism": "HARBIY QISM",
    "hostname": "HOSTNAME", "device_model": "MODEL", "mac": "MAC",
}


# ---------------------------------------------------------------------------
# Prefiks -> maska jadvali (/8 dan /32 gacha)
# ---------------------------------------------------------------------------
def prefix_to_mask(prefix):
    mask_int = (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF
    return ".".join(str((mask_int >> s) & 0xFF) for s in (24, 16, 8, 0))

MASK_OPTIONS = [{"prefix": p, "mask": prefix_to_mask(p)} for p in range(8, 33)]
VALID_MASKS = {opt["mask"] for opt in MASK_OPTIONS}


# ---------------------------------------------------------------------------
# DATABASE
# ---------------------------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _table_columns(db, table):
    # PRAGMA table_info ustunlari: (cid, name, type, notnull, dflt_value, pk)
    # init_db ulanishida row_factory yo'q, shuning uchun indeks (r[1]) ishlatamiz.
    return {r[1] for r in db.execute(f"PRAGMA table_info({table})").fetchall()}


def _ensure_column(db, table, column, coltype="TEXT DEFAULT ''"):
    """Ustun mavjud bo'lmasa qo'shadi (migratsiya - 11-punkt talabi)."""
    if column not in _table_columns(db, table):
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            full_name TEXT NOT NULL,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS networks (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'users',
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ip_records (
            id TEXT PRIMARY KEY,
            network_id TEXT NOT NULL REFERENCES networks(id) ON DELETE CASCADE,
            ip TEXT NOT NULL,
            department TEXT DEFAULT '',
            position TEXT DEFAULT '',
            full_name TEXT DEFAULT '',
            room TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            mask TEXT DEFAULT '',
            okrug TEXT DEFAULT '',
            harbiy_qism TEXT DEFAULT '',
            hostname TEXT DEFAULT '',
            device_model TEXT DEFAULT '',
            mac TEXT DEFAULT '',
            date TEXT DEFAULT '',
            admin TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ip_network ON ip_records(network_id);
        CREATE UNIQUE INDEX IF NOT EXISTS uq_ip_per_network ON ip_records(network_id, ip);
        CREATE TABLE IF NOT EXISTS logs (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            user_label TEXT NOT NULL,
            action TEXT NOT NULL,
            details TEXT NOT NULL,
            network_id TEXT,
            category TEXT
        );
        """
    )
    db.commit()

    # --- Migratsiya: eski bazaga yangi ustunlarni qo'shish ---
    _ensure_column(db, "networks", "category", "TEXT NOT NULL DEFAULT 'users'")
    for col in ("mask", "okrug", "harbiy_qism", "hostname", "device_model", "mac"):
        _ensure_column(db, "ip_records", col, "TEXT DEFAULT ''")
    _ensure_column(db, "logs", "network_id", "TEXT")
    _ensure_column(db, "logs", "category", "TEXT")
    db.commit()
    db.close()


def new_id():
    return secrets.token_hex(8)


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def today_str():
    return datetime.now().strftime("%Y-%m-%d")


def add_log(user_label, action, details, network_id=None, category=None):
    db = get_db()
    db.execute(
        "INSERT INTO logs (id, timestamp, user_label, action, details, network_id, category) "
        "VALUES (?,?,?,?,?,?,?)",
        (new_id(), now_iso(), user_label, action, details, network_id, category),
    )
    db.commit()


# ---------------------------------------------------------------------------
# VALIDATION
# ---------------------------------------------------------------------------
def is_valid_ipv4(value):
    if not isinstance(value, str):
        return False
    value = value.strip()
    if not re.match(r"^\d{1,3}(\.\d{1,3}){3}$", value):
        return False
    for p in value.split("."):
        if len(p) > 1 and p[0] == "0":
            return False
        if not (0 <= int(p) <= 255):
            return False
    try:
        ipaddress.IPv4Address(value)
    except ValueError:
        return False
    return True


def normalize_mac(value):
    """MAC formatini tekshiradi va AA:BB:CC:DD:EE:FF ko'rinishiga keltiradi."""
    if not value:
        return ""  # ixtiyoriy maydon
    v = value.strip().upper().replace("-", ":").replace(".", ":")
    if not re.match(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$", v):
        return None  # noto'g'ri format
    return v


def ip_to_int(ip):
    return int(ipaddress.IPv4Address(ip.strip()))


def int_to_ip(n):
    return str(ipaddress.IPv4Address(n))


# ---------------------------------------------------------------------------
# AUTH HELPERS
# ---------------------------------------------------------------------------
def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    db = get_db()
    row = db.execute("SELECT id, full_name, username, role FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        return None
    return {"id": row["id"], "fullName": row["full_name"], "username": row["username"], "role": row["role"]}


def user_label(u):
    return f"{u['fullName']} ({u['username']})"


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        u = current_user()
        if not u:
            return jsonify({"error": "Tizimga kirilmagan. Iltimos qayta kiring."}), 401
        g.current_user = u
        return fn(*args, **kwargs)
    return wrapper


def role_required(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if g.current_user["role"] not in roles:
                return jsonify({"error": "Bu amal uchun sizda yetarli huquq yo'q."}), 403
            return fn(*args, **kwargs)
        return wrapper
    return deco


# ---------------------------------------------------------------------------
# XAVFSIZLIK: CSRF token va HTTP header'lar
# ---------------------------------------------------------------------------
CSRF_EXEMPT = {"/api/login", "/api/setup"}


@app.before_request
def csrf_protect():
    """O'zgartiruvchi so'rovlarda (POST/PUT/DELETE) CSRF tokenni tekshiradi."""
    if request.method in ("POST", "PUT", "DELETE"):
        if request.path in CSRF_EXEMPT:
            return
        token = request.headers.get("X-CSRFToken", "")
        if not token or token != session.get("csrf"):
            return jsonify({"error": "Xavfsizlik tokeni noto'g'ri yoki sessiya tugagan. Sahifani yangilang (F5)."}), 403


@app.after_request
def security_headers(resp):
    """Har bir javobga xavfsizlik header'larini qo'shadi."""
    resp.headers["X-Content-Type-Options"] = "nosniff"     # MIME-sniffing hujumidan himoya
    resp.headers["X-Frame-Options"] = "DENY"               # clickjacking (iframe) himoyasi
    resp.headers["Referrer-Policy"] = "same-origin"
    resp.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:"
    return resp


def issue_csrf():
    token = secrets.token_hex(32)
    session["csrf"] = token
    return token


# ---------------------------------------------------------------------------
# Serializatsiya
# ---------------------------------------------------------------------------
def network_summary(row):
    db = get_db()
    count = db.execute("SELECT COUNT(*) c FROM ip_records WHERE network_id=?", (row["id"],)).fetchone()["c"]
    return {
        "id": row["id"], "name": row["name"], "category": row["category"],
        "createdBy": row["created_by"], "createdAt": row["created_at"], "ipCount": count,
    }


def ip_row_to_dict(row):
    return {
        "id": row["id"], "ip": row["ip"], "admin": row["admin"], "date": row["date"],
        "department": row["department"], "position": row["position"], "fullName": row["full_name"],
        "room": row["room"], "phone": row["phone"],
        "mask": row["mask"], "okrug": row["okrug"], "harbiyQism": row["harbiy_qism"],
        "hostname": row["hostname"], "deviceModel": row["device_model"], "mac": row["mac"],
    }


# ---------------------------------------------------------------------------
# STATIC
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return send_from_directory(app.template_folder, "index.html")


# ---------------------------------------------------------------------------
# BOOTSTRAP / AUTH
# ---------------------------------------------------------------------------
@app.route("/api/bootstrap")
def api_bootstrap():
    db = get_db()
    user_count = db.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    u = current_user()
    csrf = session.get("csrf")
    if u and not csrf:
        csrf = issue_csrf()
    return jsonify({
        "setupNeeded": user_count == 0,
        "user": u,
        "csrf": csrf,
        "maskOptions": MASK_OPTIONS,
    })


@app.route("/api/setup", methods=["POST"])
def api_setup():
    db = get_db()
    if db.execute("SELECT COUNT(*) c FROM users").fetchone()["c"] > 0:
        return jsonify({"error": "Tizim allaqachon ishga tushirilgan."}), 400
    data = request.get_json(force=True) or {}
    full_name = (data.get("fullName") or "").strip()
    username = (data.get("username") or "").strip().lower()
    password = data.get("password") or ""
    if not full_name or not username:
        return jsonify({"error": "Barcha maydonlarni to'ldiring."}), 400
    if len(password) < MIN_PASSWORD_LEN:
        return jsonify({"error": f"Parol kamida {MIN_PASSWORD_LEN} ta belgi bo'lishi kerak."}), 400
    uid = new_id()
    db.execute(
        "INSERT INTO users (id, full_name, username, password_hash, role, created_at) VALUES (?,?,?,?,?,?)",
        (uid, full_name, username, generate_password_hash(password), "superadmin", now_iso()),
    )
    db.commit()
    session.clear()
    session["user_id"] = uid
    session.permanent = True
    csrf = issue_csrf()
    add_log(f"{full_name} ({username})", "TIZIM", "Birinchi Superadmin hisobi yaratildi")
    return jsonify({"user": {"id": uid, "fullName": full_name, "username": username, "role": "superadmin"}, "csrf": csrf})


def _login_locked(username):
    now = time.time()
    attempts = [t for t in _login_attempts.get(username, []) if now - t < LOGIN_WINDOW_SEC]
    _login_attempts[username] = attempts
    if len(attempts) >= LOGIN_MAX_ATTEMPTS:
        wait = int((LOGIN_LOCK_SEC - (now - attempts[-1])) / 60) + 1
        return wait
    return 0


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(force=True) or {}
    username = (data.get("username") or "").strip().lower()
    password = data.get("password") or ""

    wait = _login_locked(username)
    if wait:
        return jsonify({"error": f"Juda ko'p noto'g'ri urinish. Iltimos ~{wait} daqiqadan so'ng qayta urinib ko'ring."}), 429

    db = get_db()
    row = db.execute("SELECT * FROM users WHERE lower(username)=?", (username,)).fetchone()
    if not row or not check_password_hash(row["password_hash"], password):
        _login_attempts.setdefault(username, []).append(time.time())
        add_log(f"noma'lum ({username})", "LOGIN XATO",
                f"Muvaffaqiyatsiz kirish urinishi. Manba IP: {request.remote_addr}")
        return jsonify({"error": "Login yoki parol noto'g'ri."}), 401

    _login_attempts.pop(username, None)
    session.clear()
    session["user_id"] = row["id"]
    session.permanent = True
    csrf = issue_csrf()
    u = {"id": row["id"], "fullName": row["full_name"], "username": row["username"], "role": row["role"]}
    return jsonify({"user": u, "csrf": csrf})


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/me/password", methods=["PUT"])
@login_required
def api_change_own_password():
    data = request.get_json(force=True) or {}
    current = data.get("current") or ""
    new = data.get("new") or ""
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id=?", (g.current_user["id"],)).fetchone()
    if not check_password_hash(row["password_hash"], current):
        return jsonify({"error": "Joriy parol noto'g'ri."}), 400
    if len(new) < MIN_PASSWORD_LEN:
        return jsonify({"error": f"Yangi parol kamida {MIN_PASSWORD_LEN} ta belgi bo'lishi kerak."}), 400
    db.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(new), row["id"]))
    db.commit()
    add_log(user_label(g.current_user), "PAROL O'ZGARTIRILDI", f"{g.current_user['fullName']} o'z parolini yangiladi")
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# NETWORKS
# ---------------------------------------------------------------------------
@app.route("/api/networks", methods=["GET"])
@login_required
def api_list_networks():
    db = get_db()
    rows = db.execute("SELECT * FROM networks ORDER BY name COLLATE NOCASE").fetchall()
    return jsonify({"networks": [network_summary(r) for r in rows]})


@app.route("/api/networks", methods=["POST"])
@login_required
@role_required("superadmin")
def api_add_network():
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()
    category = (data.get("category") or "users").strip()
    if category not in VALID_CATEGORIES:
        return jsonify({"error": "Noto'g'ri kategoriya."}), 400
    if not name:
        return jsonify({"error": "Tarmoq nomini kiriting."}), 400
    db = get_db()
    exists = db.execute("SELECT 1 FROM networks WHERE lower(name)=? AND category=?", (name.lower(), category)).fetchone()
    if exists:
        return jsonify({"error": "Bu nomdagi tarmoq ushbu bo'limda allaqachon mavjud."}), 409
    nid = new_id()
    db.execute(
        "INSERT INTO networks (id, name, category, created_by, created_at) VALUES (?,?,?,?,?)",
        (nid, name, category, g.current_user["fullName"], now_iso()),
    )
    db.commit()
    cat_label = "Tarmoq qurilmalari" if category == "devices" else "Foydalanuvchilar"
    add_log(user_label(g.current_user), "TARMOQ QO'SHILDI",
            f'"{name}" ({cat_label}) nomli yangi tarmoq yaratildi', network_id=nid, category=category)
    row = db.execute("SELECT * FROM networks WHERE id=?", (nid,)).fetchone()
    return jsonify({"network": network_summary(row)})


@app.route("/api/networks/<net_id>", methods=["DELETE"])
@login_required
@role_required("superadmin")
def api_delete_network(net_id):
    db = get_db()
    row = db.execute("SELECT * FROM networks WHERE id=?", (net_id,)).fetchone()
    if not row:
        return jsonify({"error": "Tarmoq topilmadi."}), 404
    db.execute("DELETE FROM ip_records WHERE network_id=?", (net_id,))
    db.execute("DELETE FROM networks WHERE id=?", (net_id,))
    db.commit()
    add_log(user_label(g.current_user), "TARMOQ O'CHIRILDI",
            f'"{row["name"]}" tarmog\'i va uning barcha IP manzillari o\'chirildi',
            network_id=None, category=row["category"])
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# IP RECORDS
# ---------------------------------------------------------------------------
def get_network_or_none(net_id):
    return get_db().execute("SELECT * FROM networks WHERE id=?", (net_id,)).fetchone()


def _collect_fields(data, category):
    """So'rovdan kategoriya bo'yicha kerakli maydonlarni yig'adi va tekshiradi.
       Muvaffaqiyatda (fields_dict, None), xatoda (None, error_msg) qaytaradi."""
    ip = (data.get("ip") or "").strip()
    if not is_valid_ipv4(ip):
        return None, f'"{ip}" - noto\'g\'ri IP manzil formati. Masalan: 192.168.1.10'

    if category == "devices":
        mask = (data.get("mask") or "").strip()
        if mask and mask not in VALID_MASKS:
            return None, f'"{mask}" - noto\'g\'ri maska.'
        mac = normalize_mac(data.get("mac") or "")
        if mac is None:
            return None, "MAC manzil formati noto'g'ri. Masalan: AA:BB:CC:DD:EE:FF"
        fields = {
            "ip": ip, "mask": mask, "okrug": (data.get("okrug") or "").strip(),
            "harbiy_qism": (data.get("harbiyQism") or "").strip(),
            "hostname": (data.get("hostname") or "").strip(),
            "device_model": (data.get("deviceModel") or "").strip(),
            "mac": mac,
            "department": "", "position": "", "full_name": "", "room": "", "phone": "",
        }
    else:
        fields = {
            "ip": ip,
            "department": (data.get("department") or "").strip(),
            "position": (data.get("position") or "").strip(),
            "full_name": (data.get("fullName") or "").strip(),
            "room": (data.get("room") or "").strip(),
            "phone": (data.get("phone") or "").strip(),
            "mask": "", "okrug": "", "harbiy_qism": "", "hostname": "", "device_model": "", "mac": "",
        }
    return fields, None


@app.route("/api/networks/<net_id>/ips", methods=["GET"])
@login_required
def api_list_ips(net_id):
    net = get_network_or_none(net_id)
    if not net:
        return jsonify({"error": "Tarmoq topilmadi."}), 404
    rows = get_db().execute("SELECT * FROM ip_records WHERE network_id=?", (net_id,)).fetchall()
    items = [ip_row_to_dict(r) for r in rows]
    items.sort(key=lambda r: ip_to_int(r["ip"]))
    return jsonify({"ips": items, "category": net["category"]})


@app.route("/api/networks/<net_id>/ips", methods=["POST"])
@login_required
@role_required("superadmin", "admin")
def api_add_ip(net_id):
    net = get_network_or_none(net_id)
    if not net:
        return jsonify({"error": "Tarmoq topilmadi."}), 404
    data = request.get_json(force=True) or {}
    fields, err = _collect_fields(data, net["category"])
    if err:
        return jsonify({"error": err}), 400

    db = get_db()
    dup = db.execute("SELECT * FROM ip_records WHERE network_id=? AND ip=?", (net_id, fields["ip"])).fetchone()
    if dup:
        if net["category"] == "devices":
            info = f"{dup['hostname'] or '(hostname yo’q)'} - {dup['device_model'] or 'model yo’q'}"
        else:
            info = f"{dup['full_name'] or '(ism yo’q)'} - {dup['department'] or 'bo’lim yo’q'} ({dup['room'] or 'xona yo’q'})"
        return jsonify({"error": f"Bu IP manzil ({fields['ip']}) allaqachon mavjud: {info}. IP konflikti oldini olish uchun qo'shish bloklandi."}), 409

    warning = None
    if net["category"] == "users" and fields["full_name"]:
        same = db.execute("SELECT ip FROM ip_records WHERE network_id=? AND lower(full_name)=?",
                          (net_id, fields["full_name"].lower())).fetchall()
        if same:
            warning = f'Diqqat: "{fields["full_name"]}" nomida ushbu tarmoqda allaqachon {len(same)} ta IP mavjud ({", ".join(r["ip"] for r in same)}).'

    rid = new_id()
    today = today_str()  # SANA avtomatik (4-punkt)
    db.execute(
        """INSERT INTO ip_records (id, network_id, ip, department, position, full_name, room, phone,
           mask, okrug, harbiy_qism, hostname, device_model, mac, date, admin, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (rid, net_id, fields["ip"], fields["department"], fields["position"], fields["full_name"],
         fields["room"], fields["phone"], fields["mask"], fields["okrug"], fields["harbiy_qism"],
         fields["hostname"], fields["device_model"], fields["mac"], today,
         g.current_user["fullName"], now_iso(), now_iso()),
    )
    db.commit()
    add_log(user_label(g.current_user), "IP QO'SHILDI",
            f"{net['name']} tarmog'iga {fields['ip']} qo'shildi", network_id=net_id, category=net["category"])
    row = db.execute("SELECT * FROM ip_records WHERE id=?", (rid,)).fetchone()
    return jsonify({"record": ip_row_to_dict(row), "warning": warning})


@app.route("/api/networks/<net_id>/ips/bulk", methods=["POST"])
@login_required
@role_required("superadmin", "admin")
def api_bulk_add_ips(net_id):
    net = get_network_or_none(net_id)
    if not net:
        return jsonify({"error": "Tarmoq topilmadi."}), 404
    data = request.get_json(force=True) or {}
    start_ip = (data.get("startIp") or "").strip()
    end_ip = (data.get("endIp") or "").strip()
    if not is_valid_ipv4(start_ip) or not is_valid_ipv4(end_ip):
        return jsonify({"error": "Boshlang'ich va oxirgi IP manzillarni to'g'ri kiriting."}), 400
    s, e = ip_to_int(start_ip), ip_to_int(end_ip)
    if s > e:
        s, e = e, s
    if e - s + 1 > 2000:
        return jsonify({"error": "Diapazon juda katta (maksimum 2000 ta IP)."}), 400
    ip_list = [int_to_ip(n) for n in range(s, e + 1)]

    db = get_db()
    existing = {r["ip"] for r in db.execute("SELECT ip FROM ip_records WHERE network_id=?", (net_id,)).fetchall()}
    conflicts = [ip for ip in ip_list if ip in existing]
    if conflicts:
        preview = ", ".join(conflicts[:8]) + ("..." if len(conflicts) > 8 else "")
        return jsonify({"error": f"Diapazonda {len(conflicts)} ta IP allaqachon mavjud ({preview}). Konflikt tufayli butun partiya qo'shilmadi.",
                        "conflicts": conflicts}), 409

    # umumiy maydonlar (kategoriya bo'yicha)
    if net["category"] == "devices":
        mask = (data.get("mask") or "").strip()
        if mask and mask not in VALID_MASKS:
            return jsonify({"error": "Noto'g'ri maska."}), 400
        common = {"mask": mask, "okrug": (data.get("okrug") or "").strip(),
                  "harbiy_qism": (data.get("harbiyQism") or "").strip(),
                  "device_model": (data.get("deviceModel") or "").strip()}
    else:
        common = {"department": (data.get("department") or "").strip(),
                  "position": (data.get("position") or "").strip()}

    today = today_str()
    rows = []
    for ip in ip_list:
        rid = new_id()
        rows.append((
            rid, net_id, ip,
            common.get("department", ""), common.get("position", ""), "", "", "",
            common.get("mask", ""), common.get("okrug", ""), common.get("harbiy_qism", ""),
            "", common.get("device_model", ""), "", today, g.current_user["fullName"], now_iso(), now_iso()
        ))
    db.executemany(
        """INSERT INTO ip_records (id, network_id, ip, department, position, full_name, room, phone,
           mask, okrug, harbiy_qism, hostname, device_model, mac, date, admin, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
    db.commit()
    add_log(user_label(g.current_user), "BULK IP QO'SHILDI",
            f"{net['name']} tarmog'iga {len(rows)} ta IP qo'shildi ({start_ip} - {end_ip})",
            network_id=net_id, category=net["category"])
    return jsonify({"added": len(rows)})


@app.route("/api/networks/<net_id>/ips/<ip_id>", methods=["PUT"])
@login_required
@role_required("superadmin", "admin")
def api_edit_ip(net_id, ip_id):
    net = get_network_or_none(net_id)
    if not net:
        return jsonify({"error": "Tarmoq topilmadi."}), 404
    db = get_db()
    before = db.execute("SELECT * FROM ip_records WHERE id=? AND network_id=?", (ip_id, net_id)).fetchone()
    if not before:
        return jsonify({"error": "Yozuv topilmadi."}), 404
    data = request.get_json(force=True) or {}
    fields, err = _collect_fields(data, net["category"])
    if err:
        return jsonify({"error": err}), 400

    dup = db.execute("SELECT * FROM ip_records WHERE network_id=? AND ip=? AND id!=?",
                     (net_id, fields["ip"], ip_id)).fetchone()
    if dup:
        return jsonify({"error": f"Bu IP manzil ({fields['ip']}) boshqa yozuvda allaqachon band."}), 409

    # 5-punkt: aniq nima o'zgarganini aniqlash
    labels = DEVICE_FIELD_LABELS if net["category"] == "devices" else USERS_FIELD_LABELS
    changes = []
    for col, label in labels.items():
        old_v = before[col] or ""
        new_v = fields[col] or ""
        if old_v != new_v:
            changes.append(f"{label}: '{old_v or '-'}' \u2192 '{new_v or '-'}'")
    change_str = "; ".join(changes) if changes else "o'zgarish kiritilmadi"

    db.execute(
        """UPDATE ip_records SET ip=?, department=?, position=?, full_name=?, room=?, phone=?,
           mask=?, okrug=?, harbiy_qism=?, hostname=?, device_model=?, mac=?,
           admin=?, updated_at=? WHERE id=?""",
        (fields["ip"], fields["department"], fields["position"], fields["full_name"], fields["room"],
         fields["phone"], fields["mask"], fields["okrug"], fields["harbiy_qism"], fields["hostname"],
         fields["device_model"], fields["mac"], g.current_user["fullName"], now_iso(), ip_id),
    )
    db.commit()
    add_log(user_label(g.current_user), "IP TAHRIRLANDI",
            f"{before['ip']} yozuvi tahrirlandi. O'zgarishlar: {change_str}",
            network_id=net_id, category=net["category"])
    row = db.execute("SELECT * FROM ip_records WHERE id=?", (ip_id,)).fetchone()
    return jsonify({"record": ip_row_to_dict(row)})


@app.route("/api/networks/<net_id>/ips/<ip_id>", methods=["DELETE"])
@login_required
@role_required("superadmin", "admin")
def api_delete_ip(net_id, ip_id):
    net = get_network_or_none(net_id)
    if not net:
        return jsonify({"error": "Tarmoq topilmadi."}), 404
    db = get_db()
    row = db.execute("SELECT * FROM ip_records WHERE id=? AND network_id=?", (ip_id, net_id)).fetchone()
    if not row:
        return jsonify({"error": "Yozuv topilmadi."}), 404
    db.execute("DELETE FROM ip_records WHERE id=?", (ip_id,))
    db.commit()
    add_log(user_label(g.current_user), "IP O'CHIRILDI",
            f"{row['ip']} manzili {net['name']} tarmog'idan o'chirildi", network_id=net_id, category=net["category"])
    return jsonify({"ok": True})


@app.route("/api/networks/<net_id>/ips/delete-batch", methods=["POST"])
@login_required
@role_required("superadmin", "admin")
def api_delete_batch(net_id):
    """9-punkt: belgilangan bir nechta qatorni o'chirish."""
    net = get_network_or_none(net_id)
    if not net:
        return jsonify({"error": "Tarmoq topilmadi."}), 404
    data = request.get_json(force=True) or {}
    ids = data.get("ids") or []
    if not ids:
        return jsonify({"error": "Hech qanday qator belgilanmagan."}), 400
    db = get_db()
    placeholders = ",".join("?" for _ in ids)
    rows = db.execute(f"SELECT ip FROM ip_records WHERE network_id=? AND id IN ({placeholders})",
                      [net_id, *ids]).fetchall()
    deleted_ips = [r["ip"] for r in rows]
    db.execute(f"DELETE FROM ip_records WHERE network_id=? AND id IN ({placeholders})", [net_id, *ids])
    db.commit()
    preview = ", ".join(deleted_ips[:10]) + ("..." if len(deleted_ips) > 10 else "")
    add_log(user_label(g.current_user), "GURUHLI O'CHIRISH",
            f"{net['name']} tarmog'idan {len(deleted_ips)} ta IP o'chirildi ({preview})",
            network_id=net_id, category=net["category"])
    return jsonify({"deleted": len(deleted_ips)})


@app.route("/api/networks/<net_id>/import", methods=["POST"])
@login_required
@role_required("superadmin", "admin")
def api_import_ips(net_id):
    """11-punkt: sarlavha nomi bo'yicha moslashuvchan import.
       Ustunlar tartibi/soni farq qilsa ham nomiga qarab moslaydi; yetishmagani bo'sh qoladi."""
    net = get_network_or_none(net_id)
    if not net:
        return jsonify({"error": "Tarmoq topilmadi."}), 404
    data = request.get_json(force=True) or {}
    rows_in = data.get("rows") or []
    db = get_db()
    existing = {r["ip"] for r in db.execute("SELECT ip FROM ip_records WHERE network_id=?", (net_id,)).fetchall()}
    added, skipped = [], []
    today = today_str()

    for raw in rows_in:
        ip = str(raw.get("ip", "")).strip()
        if not is_valid_ipv4(ip):
            skipped.append({"ip": ip, "reason": "noto'g'ri IP format"})
            continue
        if ip in existing:
            skipped.append({"ip": ip, "reason": "jadvalda allaqachon mavjud"})
            continue
        if net["category"] == "devices":
            mac = normalize_mac(str(raw.get("mac", "")).strip())
            if mac is None:
                mac = ""  # import tolerant - noto'g'ri MAC bo'sh qoladi
            mask = str(raw.get("mask", "")).strip()
            if mask and mask not in VALID_MASKS:
                mask = ""
            fields = {"ip": ip, "mask": mask, "okrug": str(raw.get("okrug", "")).strip(),
                      "harbiy_qism": str(raw.get("harbiyQism", "")).strip(),
                      "hostname": str(raw.get("hostname", "")).strip(),
                      "device_model": str(raw.get("deviceModel", "")).strip(), "mac": mac,
                      "department": "", "position": "", "full_name": "", "room": "", "phone": ""}
        else:
            fields = {"ip": ip, "department": str(raw.get("department", "")).strip(),
                      "position": str(raw.get("position", "")).strip(),
                      "full_name": str(raw.get("fullName", "")).strip(),
                      "room": str(raw.get("room", "")).strip(), "phone": str(raw.get("phone", "")).strip(),
                      "mask": "", "okrug": "", "harbiy_qism": "", "hostname": "", "device_model": "", "mac": ""}
        existing.add(ip)
        rid = new_id()
        db.execute(
            """INSERT INTO ip_records (id, network_id, ip, department, position, full_name, room, phone,
               mask, okrug, harbiy_qism, hostname, device_model, mac, date, admin, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (rid, net_id, fields["ip"], fields["department"], fields["position"], fields["full_name"],
             fields["room"], fields["phone"], fields["mask"], fields["okrug"], fields["harbiy_qism"],
             fields["hostname"], fields["device_model"], fields["mac"], today,
             g.current_user["fullName"], now_iso(), now_iso()))
        added.append(ip)
    db.commit()
    add_log(user_label(g.current_user), "IMPORT",
            f"{net['name']} tarmog'iga {len(added)} ta IP import qilindi, {len(skipped)} ta o'tkazildi",
            network_id=net_id, category=net["category"])
    return jsonify({"added": added, "skipped": skipped})


# ---------------------------------------------------------------------------
# LOGS
# ---------------------------------------------------------------------------
@app.route("/api/logs", methods=["GET"])
@login_required
def api_list_logs():
    db = get_db()
    rows = db.execute("SELECT * FROM logs ORDER BY timestamp DESC LIMIT 5000").fetchall()
    items = [{"id": r["id"], "timestamp": r["timestamp"], "userLabel": r["user_label"],
              "action": r["action"], "details": r["details"],
              "networkId": r["network_id"], "category": r["category"]} for r in rows]
    return jsonify({"logs": items})


# ---------------------------------------------------------------------------
# USERS
# ---------------------------------------------------------------------------
def user_to_dict(row):
    return {"id": row["id"], "fullName": row["full_name"], "username": row["username"], "role": row["role"]}


@app.route("/api/users", methods=["GET"])
@login_required
@role_required("superadmin")
def api_list_users():
    rows = get_db().execute("SELECT * FROM users ORDER BY full_name COLLATE NOCASE").fetchall()
    return jsonify({"users": [user_to_dict(r) for r in rows]})


@app.route("/api/users", methods=["POST"])
@login_required
@role_required("superadmin")
def api_add_user():
    data = request.get_json(force=True) or {}
    full_name = (data.get("fullName") or "").strip()
    username = (data.get("username") or "").strip().lower()
    role = data.get("role") or "user"
    password = data.get("password") or ""
    if role not in VALID_ROLES:
        return jsonify({"error": "Noto'g'ri rol."}), 400
    if not full_name or not username:
        return jsonify({"error": "Barcha maydonlarni to'ldiring."}), 400
    if len(password) < MIN_PASSWORD_LEN:
        return jsonify({"error": f"Parol kamida {MIN_PASSWORD_LEN} ta belgi bo'lishi kerak."}), 400
    db = get_db()
    if db.execute("SELECT 1 FROM users WHERE lower(username)=?", (username,)).fetchone():
        return jsonify({"error": "Bu login band."}), 409
    uid = new_id()
    db.execute("INSERT INTO users (id, full_name, username, password_hash, role, created_at) VALUES (?,?,?,?,?,?)",
               (uid, full_name, username, generate_password_hash(password), role, now_iso()))
    db.commit()
    add_log(user_label(g.current_user), "FOYDALANUVCHI QO'SHILDI", f"{full_name} (@{username}) - rol: {ROLE_LABEL[role]}")
    row = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    return jsonify({"user": user_to_dict(row)})


@app.route("/api/users/<uid>", methods=["PUT"])
@login_required
@role_required("superadmin")
def api_edit_user(uid):
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        return jsonify({"error": "Foydalanuvchi topilmadi."}), 404
    data = request.get_json(force=True) or {}
    full_name = (data.get("fullName") or "").strip()
    role = data.get("role") or row["role"]
    password = data.get("password") or ""
    if role not in VALID_ROLES:
        return jsonify({"error": "Noto'g'ri rol."}), 400
    if not full_name:
        return jsonify({"error": "Ismni kiriting."}), 400
    if row["role"] == "superadmin" and role != "superadmin":
        cnt = db.execute("SELECT COUNT(*) c FROM users WHERE role='superadmin'").fetchone()["c"]
        if cnt <= 1:
            return jsonify({"error": "Tizimda kamida bitta Superadmin qolishi kerak."}), 400
    if password:
        if len(password) < MIN_PASSWORD_LEN:
            return jsonify({"error": f"Parol kamida {MIN_PASSWORD_LEN} ta belgi bo'lishi kerak."}), 400
        db.execute("UPDATE users SET full_name=?, role=?, password_hash=? WHERE id=?",
                   (full_name, role, generate_password_hash(password), uid))
    else:
        db.execute("UPDATE users SET full_name=?, role=? WHERE id=?", (full_name, role, uid))
    db.commit()
    add_log(user_label(g.current_user), "FOYDALANUVCHI TAHRIRLANDI", f"{full_name} (@{row['username']}) profili yangilandi")
    row2 = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    return jsonify({"user": user_to_dict(row2)})


@app.route("/api/users/<uid>", methods=["DELETE"])
@login_required
@role_required("superadmin")
def api_delete_user(uid):
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        return jsonify({"error": "Foydalanuvchi topilmadi."}), 404
    if uid == g.current_user["id"]:
        return jsonify({"error": "O'zingizni o'chira olmaysiz."}), 400
    if row["role"] == "superadmin":
        cnt = db.execute("SELECT COUNT(*) c FROM users WHERE role='superadmin'").fetchone()["c"]
        if cnt <= 1:
            return jsonify({"error": "Tizimda kamida bitta Superadmin qolishi kerak."}), 400
    db.execute("DELETE FROM users WHERE id=?", (uid,))
    db.commit()
    add_log(user_label(g.current_user), "FOYDALANUVCHI O'CHIRILDI", f"{row['full_name']} (@{row['username']}) hisobi o'chirildi")
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# init_db() ni modul darajasida chaqiramiz. Shunda ma'lumotlar bazasi ham
# `python app.py` bilan, ham Gunicorn/uWSGI orqali (ular `app:app` ni import
# qiladi, `__main__` blokini ishga tushirmaydi) yaratiladi va migratsiyalar
# (yangi ustunlar) avtomatik qo'llaniladi. init_db o'zining alohida
# sqlite ulanishini ochadi, shuning uchun Flask konteksti talab qilinmaydi.
init_db()

if __name__ == "__main__":
    print("=" * 70)
    print(" Kiberxavfsizlik Departamenti - IP Manzillar Hisobi")
    print(" Server manzili: http://0.0.0.0:5000")
    print(" LAN'dagi boshqa kompyuterlar: http://<bu-serverning-IP-manzili>:5000")
    print("=" * 70)
    app.run(host="0.0.0.0", port=5000, debug=False)
