"""Бодит localhost HTTP сервер дээрх API ба аюулгүй байдлын тест (Лаб 5-ын TC01–TC24)."""
import http.client
import json
import secrets
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path

from src.app import STATIC_DIR, initialize, make_server, verify_password

USERS = ("nomin", "bat", "empty", "worker")


class Client:
    def __init__(self, port):
        self.port = port
        self.cookie = None
        self.csrf = None

    def request(self, method, path, payload=None, raw=None, csrf=True):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Content-Type": "application/json"}
        if self.cookie:
            headers["Cookie"] = self.cookie
        if csrf and self.csrf:
            headers["X-CSRF-Token"] = self.csrf
        body = raw if raw is not None else (json.dumps(payload).encode() if payload is not None else None)
        conn.request(method, path, body=body, headers=headers)
        res = conn.getresponse()
        text = res.read().decode()
        cookie = res.getheader("Set-Cookie")
        if cookie:
            self.cookie = cookie.split(";")[0]
        conn.close()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = text
        return res.status, data, res

    def login(self, username, password):
        status, data, _ = self.request("POST", "/api/login", {"username": username, "password": password})
        if status == 200:
            self.csrf = data["csrf"]
        return status, data


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db_path = str(Path(cls.tmp.name) / "test.db")
        cls.passwords = {name: secrets.token_urlsafe(12) for name in USERS}
        initialize(cls.db_path, cls.passwords)
        cls.server = make_server(cls.db_path, port=0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def client(self, username=None):
        c = Client(self.port)
        if username:
            status, _ = c.login(username, self.passwords[username])
            self.assertEqual(status, 200)
        return c

    # TC01
    def test_tc01_login_success(self):
        status, data = Client(self.port).login("nomin", self.passwords["nomin"])
        self.assertEqual(status, 200)
        self.assertEqual(data["role"], "customer")
        self.assertTrue(data["csrf"])

    # TC02 — AC-05-1
    def test_tc02_own_order_fields(self):
        status, data, _ = self.client("nomin").request("GET", "/api/orders/1")
        self.assertEqual(status, 200)
        self.assertEqual(data["number"], "HC-0001")
        for key in ("items", "status", "ready_at", "updated_at", "history"):
            self.assertIn(key, data)
        self.assertEqual(data["items"][0]["garment"], "Пальто")

    # TC03
    def test_tc03_empty_orders(self):
        status, data, _ = self.client("empty").request("GET", "/api/orders")
        self.assertEqual(status, 200)
        self.assertEqual(data["orders"], [])

    # TC04 — AC-05-4
    def test_tc04_other_customer_order(self):
        status, data, _ = self.client("nomin").request("GET", "/api/orders/2")
        self.assertEqual(status, 404)
        self.assertNotIn("HC-0002", json.dumps(data, ensure_ascii=False))

    # TC05
    def test_tc05_empty_login_input(self):
        status, _ = Client(self.port).login("", "")
        self.assertEqual(status, 400)

    # TC06
    def test_tc06_bad_order_id(self):
        c = self.client("nomin")
        for raw in ("abc", "0", "-1", "1%20OR%201=1", "1;DROP"):
            status, _, _ = c.request("GET", "/api/orders/" + raw)
            self.assertEqual(status, 400, raw)

    # TC07
    def test_tc07_not_logged_in(self):
        status, _, _ = Client(self.port).request("GET", "/api/orders")
        self.assertEqual(status, 401)

    # TC08
    def test_tc08_wrong_password(self):
        status, _ = Client(self.port).login("nomin", "wrong-password-123")
        self.assertEqual(status, 401)

    # TC09 — AC-05-2
    def test_tc09_confirmed_ready_at(self):
        _, data, _ = self.client("nomin").request("GET", "/api/orders/1")
        self.assertEqual(data["ready_at"], "2026-10-16T18:00:00+08:00")

    # TC10 — AC-05-2
    def test_tc10_unconfirmed_ready_at(self):
        _, data, _ = self.client("nomin").request("GET", "/api/orders/3")
        self.assertIsNone(data["ready_at"])

    # TC11 — AC-05-3 (TC18-тай давхцахгүйн тулд захиалга 2 дээр)
    def test_tc11_update_then_view(self):
        worker = self.client("worker")
        status, upd, _ = worker.request("POST", "/api/orders/2/status", {"status": "quality_check"})
        self.assertEqual(status, 200)
        bat = self.client("bat")
        _, data, _ = bat.request("GET", "/api/orders/2")
        self.assertEqual(data["status"], "quality_check")
        self.assertEqual(data["updated_at"], upd["updated_at"])
        self.assertEqual(data["history"][-1]["status"], "quality_check")
        # буцааж анхны төлөвт оруулна
        worker.request("POST", "/api/orders/2/status", {"status": "cleaning", "reason": "Тест буцаалт"})

    # TC12
    def test_tc12_customer_cannot_update(self):
        status, _, _ = self.client("nomin").request("POST", "/api/orders/1/status", {"status": "cleaning"})
        self.assertEqual(status, 403)

    # TC13
    def test_tc13_skipped_transition(self):
        status, _, _ = self.client("worker").request("POST", "/api/orders/1/status", {"status": "ready"})
        self.assertEqual(status, 400)

    # TC14
    def test_tc14_bad_csrf(self):
        worker = self.client("worker")
        worker.csrf = "invalid"
        status, _, _ = worker.request("POST", "/api/orders/1/status", {"status": "cleaning"})
        self.assertEqual(status, 403)

    # TC15
    def test_tc15_password_storage(self):
        db = sqlite3.connect(self.db_path)
        rows = db.execute("SELECT username, password_hash FROM users").fetchall()
        db.close()
        salts = set()
        for name, stored in rows:
            self.assertNotIn(self.passwords[name], stored)
            algo, iterations, salt, _ = stored.split("$")
            self.assertEqual(algo, "pbkdf2_sha256")
            self.assertGreaterEqual(int(iterations), 260000)
            salts.add(salt)
            self.assertTrue(verify_password(self.passwords[name], stored))
        self.assertEqual(len(salts), len(rows))

    # TC16
    def test_tc16_login_sql_injection(self):
        status, _ = Client(self.port).login("nomin' OR '1'='1", "x")
        self.assertEqual(status, 400)

    # TC17
    def test_tc17_after_logout(self):
        c = self.client("nomin")
        old_cookie = c.cookie
        status, _, _ = c.request("POST", "/api/logout", {})
        self.assertEqual(status, 200)
        c.cookie = old_cookie  # хуучин token-ийг сервер хүчингүй болгосон эсэх
        status, _, _ = c.request("GET", "/api/orders")
        self.assertEqual(status, 401)

    # TC18
    def test_tc18_return_requires_reason(self):
        worker = self.client("worker")
        self.assertEqual(worker.request("POST", "/api/orders/1/status", {"status": "cleaning"})[0], 200)
        self.assertEqual(worker.request("POST", "/api/orders/1/status", {"status": "quality_check"})[0], 200)
        self.assertEqual(worker.request("POST", "/api/orders/1/status", {"status": "cleaning", "reason": ""})[0], 400)
        status, _, _ = worker.request("POST", "/api/orders/1/status", {"status": "cleaning", "reason": "Толбо үлдсэн"})
        self.assertEqual(status, 200)
        _, data, _ = worker.request("GET", "/api/orders/1")
        self.assertEqual(data["history"][-1]["reason"], "Толбо үлдсэн")
        # анхны төлөвт буцаахгүй: history-д бодит дараалал үлдэнэ

    # TC19
    def test_tc19_same_404_for_missing_and_foreign(self):
        c = self.client("nomin")
        s1, d1, _ = c.request("GET", "/api/orders/2")
        s2, d2, _ = c.request("GET", "/api/orders/999")
        self.assertEqual((s1, d1), (s2, d2))
        self.assertEqual(s1, 404)

    # TC20
    def test_tc20_own_list_only(self):
        _, data, _ = self.client("nomin").request("GET", "/api/orders")
        self.assertEqual([o["id"] for o in data["orders"]], [1, 3])

    # TC21
    def test_tc21_session_expiry(self):
        c = self.client("nomin")
        token = c.cookie.split("=", 1)[1]
        with self.server.lock:
            self.server.sessions[token]["expires"] = time.time() - 1
        status, _, _ = c.request("GET", "/api/orders")
        self.assertEqual(status, 401)

    # TC22
    def test_tc22_csp_and_dom(self):
        status, _, res = Client(self.port).request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("script-src 'self'", res.getheader("Content-Security-Policy"))
        js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn("textContent", js)
        self.assertNotIn(".innerHTML", js)

    # TC23
    def test_tc23_non_object_json(self):
        c = Client(self.port)
        for raw in (b"[1,2]", b"\"text\"", b"{bad json"):
            status, _, _ = c.request("POST", "/api/login", raw=raw)
            self.assertEqual(status, 400)

    # TC24
    def test_tc24_no_internal_details(self):
        c = Client(self.port)
        status, data, _ = c.request("POST", "/api/login", raw=b"{bad json")
        text = json.dumps(data, ensure_ascii=False)
        for secret in ("Traceback", "sqlite", self.db_path, "password_hash"):
            self.assertNotIn(secret, text)
        status, data, _ = c.request("GET", "/static/../app.py")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
