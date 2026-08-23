from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

import app


class LocalServerSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tempdir = tempfile.TemporaryDirectory()
        app.CONFIG_DIR = Path(cls.tempdir.name)
        app.CONFIG_FILE = app.CONFIG_DIR / "config.json"
        app.DEV_DOWNLOADS = app.CONFIG_DIR / "downloads"
        app.DEV_DOWNLOADS.mkdir()
        cls.server = app.ThreadingHTTPServer((app.HOST, 0), app.Handler)
        cls.server.daemon_threads = True
        app.PORT = cls.server.server_address[1]
        app.APP_ORIGIN = f"http://{app.HOST}:{app.PORT}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls.tempdir.cleanup()

    def request(self, method: str, path: str, body: dict | None = None, headers: dict | None = None):
        connection = http.client.HTTPConnection(app.HOST, app.PORT, timeout=3)
        payload = json.dumps(body).encode() if body is not None else None
        request_headers = dict(headers or {})
        if payload is not None:
            request_headers.setdefault("Content-Type", "application/json")
            request_headers.setdefault("Content-Length", str(len(payload)))
        connection.request(method, path, body=payload, headers=request_headers)
        response = connection.getresponse()
        data = response.read()
        result = response.status, response.headers, data
        connection.close()
        return result

    def session_cookie(self) -> str:
        status, headers, _ = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("default-src 'self'", headers.get("Content-Security-Policy", ""))
        return headers["Set-Cookie"].split(";", 1)[0]

    def test_api_requires_session(self) -> None:
        status, _, _ = self.request("GET", "/api/settings")
        self.assertEqual(status, 403)

    def test_same_origin_session_can_read_settings(self) -> None:
        status, _, _ = self.request("GET", "/api/settings", headers={"Cookie": self.session_cookie()})
        self.assertEqual(status, 200)

    def test_cross_origin_post_is_rejected(self) -> None:
        status, _, _ = self.request(
            "POST",
            "/api/download",
            {"url": "https://example.com/video"},
            {"Cookie": self.session_cookie(), "Origin": "https://evil.example"},
        )
        self.assertEqual(status, 403)

    def test_private_network_download_is_rejected(self) -> None:
        status, _, _ = self.request(
            "POST",
            "/api/download",
            {"url": "http://127.0.0.1/private"},
            {"Cookie": self.session_cookie(), "Origin": app.APP_ORIGIN},
        )
        self.assertEqual(status, 400)

    def test_wrong_host_is_rejected(self) -> None:
        status, _, _ = self.request("GET", "/", headers={"Host": "evil.example"})
        self.assertEqual(status, 421)

    def test_bilibili_headers_require_real_domain_boundary(self) -> None:
        self.assertIn("Origin", app.request_headers("https://www.bilibili.com/video/BV1"))
        self.assertIn("Origin", app.request_headers("https://b23.tv/example"))
        self.assertNotIn("Origin", app.request_headers("https://evilbilibili.com/video"))
        self.assertNotIn("Origin", app.request_headers("https://b23.tv.evil.example/video"))


if __name__ == "__main__":
    unittest.main()
