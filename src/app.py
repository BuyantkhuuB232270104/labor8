"""Хими цэвэрлэгээний үйлчилгээний систем — веб сервер ба API.

US-05: үйлчлүүлэгч өөрийн захиалгын явц, хугацааг харна.
US-04: цэвэрлэгээний ажилтан захиалгын төлөвийг шинэчилнэ.
Зөвхөн Python стандарт сан ашиглана.
"""
import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from src.workflow import STATUS_LABELS, TransitionError, allowed_next, progress_percent, validate_transition

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DEFAULT_DB = BASE_DIR.parent / "data" / "himi.db"

MAX_BODY = 8192
SESSION_TTL = 3600
PBKDF2_ITERATIONS = 260_000
USERNAME_RE = re.compile(r"^[a-z0-9_]{3,32}$")
ORDER_ID_RE = re.compile(r"^[1-9][0-9]{0,8}$")
WORK_STATUSES = ("received", "cleaning", "quality_check")

CSP = "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"
STATIC_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('customer', 'cleaner'))
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY,
    number TEXT UNIQUE NOT NULL,
    customer_id INTEGER NOT NULL REFERENCES users(id),
    status TEXT NOT NULL,
    ready_at TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    garment TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0)
);
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    status TEXT NOT NULL,
    actor_id INTEGER NOT NULL REFERENCES users(id),
    changed_at TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT ''
);
"""


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password, stored):
    try:
        algo, iterations, salt, expected = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, AttributeError):
        return False


def connect(db_path):
    db = sqlite3.connect(db_path, isolation_level=None, timeout=5)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def initialize(db_path, passwords):
    """Хүснэгт үүсгэж зохиомол туршилтын өгөгдөл оруулна.

    passwords: {"nomin": ..., "bat": ..., "empty": ..., "worker": ...}
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    db = connect(db_path)
    try:
        db.executescript(SCHEMA)
        if db.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            return
        stamp = now()
        db.execute("BEGIN")
        users = [("nomin", "customer"), ("bat", "customer"), ("empty", "customer"), ("worker", "cleaner")]
        ids = {}
        for name, role in users:
            cur = db.execute("INSERT INTO users(username, password_hash, role) VALUES (?, ?, ?)",
                             (name, password_hash(passwords[name]), role))
            ids[name] = cur.lastrowid
        orders = [
            (1, "HC-0001", ids["nomin"], "received", "2026-10-16T18:00:00+08:00"),
            (2, "HC-0002", ids["bat"], "cleaning", "2026-10-17T12:00:00+08:00"),
            (3, "HC-0003", ids["nomin"], "requested", None),
        ]
        for oid, number, customer, status, ready_at in orders:
            db.execute("INSERT INTO orders(id, number, customer_id, status, ready_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                       (oid, number, customer, status, ready_at, stamp))
            db.execute("INSERT INTO history(order_id, status, actor_id, changed_at, reason) VALUES (?, ?, ?, ?, '')",
                       (oid, status, ids["worker"] if status != "requested" else customer, stamp))
        items = [(1, "Пальто", 1), (1, "Цамц", 2), (2, "Костюм", 1), (3, "Даашинз", 1)]
        db.executemany("INSERT INTO items(order_id, garment, quantity) VALUES (?, ?, ?)", items)
        db.execute("COMMIT")
    finally:
        db.close()


class Handler(BaseHTTPRequestHandler):
    server_version = "HimiServer"
    sys_version = ""

    def log_message(self, fmt, *args):  # тест, CI log-ийг цэвэр байлгана
        if os.environ.get("HIMI_ACCESS_LOG"):
            super().log_message(fmt, *args)

    # ---------- туслах ----------
    def send_json(self, status, payload, headers=None):
        data = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ApiError(400, "Хүсэлт буруу байна.")
        if length <= 0 or length > MAX_BODY:
            raise ApiError(400, "Хүсэлтийн хэмжээ буруу байна.")
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ApiError(400, "JSON буруу байна.")
        if not isinstance(data, dict):
            raise ApiError(400, "JSON object илгээнэ үү.")
        return data

    def cookie_token(self):
        for part in self.headers.get("Cookie", "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == "sid":
                return value
        return None

    def identity(self, db, require_csrf=False):
        token = self.cookie_token()
        sessions = self.server.sessions
        with self.server.lock:
            session = sessions.get(token) if token else None
            if session and session["expires"] < time.time():
                sessions.pop(token, None)
                session = None
        if not session:
            raise ApiError(401, "Нэвтрэх шаардлагатай.")
        if require_csrf and not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), session["csrf"]):
            raise ApiError(403, "Хүсэлтийн баталгаажуулалт буруу.")
        user = db.execute("SELECT id, username, role FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        if not user:
            raise ApiError(401, "Нэвтрэх шаардлагатай.")
        return user, token

    # ---------- HTTP ----------
    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def dispatch(self, method):
        path = urlsplit(self.path).path
        db = None
        try:
            if method == "GET" and not path.startswith("/api/"):
                return self.static(path)
            db = connect(self.server.db_path)
            parts = path.strip("/").split("/")
            if method == "POST" and path == "/api/login":
                return self.login(db)
            if method == "POST" and path == "/api/logout":
                return self.logout(db)
            if method == "GET" and path == "/api/orders":
                return self.list_orders(db)
            if len(parts) == 3 and parts[:2] == ["api", "orders"] and method == "GET":
                return self.order_detail(db, parts[2])
            if len(parts) == 4 and parts[:2] == ["api", "orders"] and parts[3] == "status" and method == "POST":
                return self.update_status(db, parts[2])
            raise ApiError(404, "Хаяг олдсонгүй.")
        except ApiError as err:
            self.send_json(err.status, {"error": err.message})
        except Exception:  # дотоод мэдээллийг хэрэглэгчид задруулахгүй
            self.send_json(500, {"error": "Дотоод алдаа гарлаа."})
        finally:
            if db is not None:
                db.close()

    def static(self, path):
        if path in ("/", "/index.html"):
            name = "index.html"
        elif path.startswith("/static/"):
            name = path[len("/static/"):]
        else:
            name = ""
        if not name or "/" in name or "\\" in name or name.startswith("."):
            raise ApiError(404, "Хаяг олдсонгүй.")
        file = STATIC_DIR / name
        if file.suffix not in STATIC_TYPES or not file.is_file():
            raise ApiError(404, "Хаяг олдсонгүй.")
        data = file.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", STATIC_TYPES[file.suffix])
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def login(self, db):
        data = self.body()
        username, password = data.get("username"), data.get("password")
        if not isinstance(username, str) or not isinstance(password, str) or not USERNAME_RE.match(username) \
                or not 1 <= len(password) <= 128:
            raise ApiError(400, "Нэвтрэх нэр эсвэл нууц үгийн формат буруу.")
        user = db.execute("SELECT id, role, password_hash FROM users WHERE username = ?", (username,)).fetchone()
        if not user or not verify_password(password, user["password_hash"]):
            raise ApiError(401, "Нэвтрэх нэр эсвэл нууц үг буруу.")
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.server.lock:
            self.server.sessions[token] = {"user_id": user["id"], "csrf": csrf, "expires": time.time() + self.server.ttl}
        cookie = f"sid={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={self.server.ttl}"
        self.send_json(200, {"username": username, "role": user["role"], "csrf": csrf}, {"Set-Cookie": cookie})

    def logout(self, db):
        _, token = self.identity(db, require_csrf=True)
        with self.server.lock:
            self.server.sessions.pop(token, None)
        self.send_json(200, {"ok": True}, {"Set-Cookie": "sid=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"})

    def list_orders(self, db):
        user, _ = self.identity(db)
        if user["role"] == "customer":
            rows = db.execute("SELECT id, number, status, ready_at, updated_at FROM orders WHERE customer_id = ? ORDER BY id",
                              (user["id"],)).fetchall()
        else:
            rows = db.execute("SELECT id, number, status, ready_at, updated_at FROM orders WHERE status IN (?, ?, ?) ORDER BY id",
                              WORK_STATUSES).fetchall()
        orders = []
        for row in rows:
            item = dict(row)
            item["status_label"] = STATUS_LABELS[row["status"]]
            if user["role"] == "cleaner":
                item["next"] = allowed_next(row["status"])
            orders.append(item)
        self.send_json(200, {"role": user["role"], "orders": orders})

    def load_order(self, db, raw_id, user):
        if not ORDER_ID_RE.match(raw_id):
            raise ApiError(400, "Захиалгын дугаар буруу.")
        order = db.execute("SELECT * FROM orders WHERE id = ?", (int(raw_id),)).fetchone()
        if not order or (user["role"] == "customer" and order["customer_id"] != user["id"]):
            raise ApiError(404, "Захиалга олдсонгүй эсвэл хандах эрхгүй.")
        return order

    def order_detail(self, db, raw_id):
        user, _ = self.identity(db)
        order = self.load_order(db, raw_id, user)
        oid = order["id"]
        result = {k: order[k] for k in ("id", "number", "status", "ready_at", "updated_at")}
        result["status_label"] = STATUS_LABELS[order["status"]]
        result["progress"] = progress_percent(order["status"])
        result["items"] = [dict(r) for r in db.execute("SELECT garment, quantity FROM items WHERE order_id = ? ORDER BY id", (oid,))]
        result["history"] = [dict(r) for r in db.execute(
            "SELECT status, changed_at, reason FROM history WHERE order_id = ? ORDER BY id", (oid,))]
        self.send_json(200, result)

    def update_status(self, db, raw_id):
        user, _ = self.identity(db, require_csrf=True)
        if user["role"] != "cleaner":
            raise ApiError(403, "Төлөв өөрчлөх эрхгүй.")
        data = self.body()
        new_status = data.get("status")
        reason = data.get("reason", "")
        if not ORDER_ID_RE.match(raw_id):
            raise ApiError(400, "Захиалгын дугаар буруу.")
        oid = int(raw_id)
        db.execute("BEGIN IMMEDIATE")
        try:
            order = db.execute("SELECT status FROM orders WHERE id = ?", (oid,)).fetchone()
            if not order:
                raise ApiError(404, "Захиалга олдсонгүй эсвэл хандах эрхгүй.")
            try:
                reason = validate_transition(order["status"], new_status, reason)
            except TransitionError as err:
                raise ApiError(400, str(err))
            stamp = now()
            db.execute("UPDATE orders SET status = ?, updated_at = ? WHERE id = ?", (new_status, stamp, oid))
            db.execute("INSERT INTO history(order_id, status, actor_id, changed_at, reason) VALUES (?, ?, ?, ?, ?)",
                       (oid, new_status, user["id"], stamp, reason))
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
        self.send_json(200, {"id": oid, "status": new_status, "updated_at": stamp})


def make_server(db_path, host="127.0.0.1", port=8000, ttl=SESSION_TTL):
    server = ThreadingHTTPServer((host, port), Handler)
    server.db_path = str(db_path)
    server.sessions = {}
    server.lock = threading.Lock()
    server.ttl = ttl
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description="Хими цэвэрлэгээний систем")
    parser.add_argument("--init", action="store_true", help="өгөгдлийн сан үүсгэж туршилтын өгөгдөл оруулах")
    parser.add_argument("--db", default=os.environ.get("HIMI_DB", str(DEFAULT_DB)))
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    if args.init:
        demo = os.environ.get("LAB5_DEMO_PASSWORD", "")
        if len(demo) < 10:
            print("LAB5_DEMO_PASSWORD орчны хувьсагчид 10-аас доошгүй тэмдэгттэй нууц үг тохируулна уу.", file=sys.stderr)
            return 2
        initialize(args.db, {name: demo for name in ("nomin", "bat", "empty", "worker")})
        print(f"Өгөгдлийн сан бэлэн: {args.db}")
        return 0
    if not Path(args.db).exists():
        print("Эхлээд `python -m src.app --init` ажиллуулна уу.", file=sys.stderr)
        return 2
    server = make_server(args.db, port=args.port)
    print(f"http://127.0.0.1:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
