"""Loopback HTTP boundaries and bounded range delivery."""
from __future__ import annotations
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import quote

from ..api import Server
from ..indexer import Indexer
from ..streaming import RangeError, byte_range
from .support import fixture_config, populate, write


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.config = fixture_config(cls.root)
        cls.paths = populate(cls.config.workspace)
        cls.indexer = Indexer(cls.config)
        cls.indexer.reindex()
        cls.server = Server(cls.indexer)
        cls.port = cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever,
                                      daemon=True)
        cls.thread.start()
        cls.identifier = next(work["id"]
                              for work in cls.indexer.store.list_works()
                              if work["title"] == "火光")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)
        cls.temporary.cleanup()

    def request(self, path: str, method: str = "GET",
                headers: dict[str, str] | None = None
                ) -> tuple[int, dict[str, str], bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port,
                                                timeout=3)
        connection.request(method, path, headers=headers or {})
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def file_url(self, path: str = "火光-发布版-1080p.mp4") -> str:
        base = f"/api/works/{self.identifier}/file?path="
        return base + quote(path, safe="")

    def test_health_and_truthful_empty_integrations(self) -> None:
        status, _, body = self.request("/api/health")
        health = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(health["app"], "spt")
        self.assertFalse(health["capabilities"]["publish"])
        for route in ("accounts", "jobs", "agents"):
            body = self.request("/api/" + route)[2]
            self.assertEqual(json.loads(body), {route: []})
        self.assertIn(b"doctype", self.request("/")[2])

    def test_get_head_ranges_and_unsatisfiable_range(self) -> None:
        status, headers, body = self.request(self.file_url(),
                                             headers={"Range": "bytes=2-5"})
        self.assertEqual((status, body), (206, b"2345"))
        self.assertEqual(headers["Content-Range"], "bytes 2-5/10")
        status, headers, body = self.request(self.file_url(), "HEAD")
        self.assertEqual((status, body), (200, b""))
        self.assertEqual(headers["Content-Length"], "10")
        self.assertEqual(self.request(self.file_url(),
                         headers={"Range": "bytes=-3"})[2], b"789")
        status, headers, body = self.request(self.file_url(),
                                             headers={"Range": "bytes=50-"})
        self.assertEqual(status, 416)
        self.assertEqual(headers["Content-Range"], "bytes */10")
        self.assertIn("error", json.loads(body))

    def test_host_origin_and_mutation_fail_closed(self) -> None:
        for headers in ({"Host": "evil.example"},
                        {"Origin": "https://evil.example"},
                        {"Origin": f"http://localhost:{self.port + 1}"},
                        {"Sec-Fetch-Site": "cross-site"}):
            with self.subTest(headers=headers):
                status = self.request("/api/health", headers=headers)[0]
                self.assertEqual(status, 403)
        good = {"Origin": f"http://localhost:{self.port}"}
        self.assertEqual(self.request("/api/health", headers=good)[0], 200)
        self.assertEqual(self.request("/api/jobs", "POST")[0], 409)
        self.assertEqual(self.request("/api/reindex", "PUT")[0], 405)

    def post_json(self, path: str, value: object, content_type: str = "application/json",
                  origin: str | None = None) -> tuple[int, dict]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        headers = {"Content-Type": content_type}
        if origin:
            headers["Origin"] = origin
        connection.request("POST", path, body=json.dumps(value).encode(), headers=headers)
        response = connection.getresponse()
        result = response.status, json.loads(response.read() or b"{}")
        connection.close()
        return result

    def test_notes_write_only_through_json_from_this_origin(self) -> None:
        status, saved = self.post_json("/api/notes/save", {"text": "测试便签", "color": "sky"})
        self.assertEqual(status, 200)
        notes = json.loads(self.request("/api/notes")[2])
        self.assertEqual(notes["ropes"][0]["notes"][0]["id"], saved["id"])
        self.assertEqual(self.post_json("/api/notes/save", {"text": "x"}, "text/plain")[0], 415)
        self.assertEqual(self.post_json("/api/notes/save", {"text": "x"},
                                        origin="https://evil.example")[0], 403)
        self.assertEqual(self.post_json("/api/notes/save", {"text": ""})[0], 400)
        self.assertEqual(self.post_json("/api/notes/rope", {"action": "create", "name": "../x"})[0], 400)
        status, _ = self.post_json("/api/notes/remove", {"id": saved["id"], "rope": saved["rope"]})
        self.assertEqual(status, 200)

    def test_workspace_setting_rejects_unsafe_folders(self) -> None:
        for path in ("relative", "/", str(Path.home())):
            with self.subTest(path=path):
                self.assertEqual(self.post_json("/api/settings/workspace", {"path": path})[0], 400)

    def test_traversal_and_external_links_are_denied(self) -> None:
        root = self.paths["火光"]
        write(self.root / "private.txt", "private")
        (root / "outside.txt").symlink_to(self.root / "private.txt")
        for path in ("../private.txt", "/etc/passwd", "outside.txt"):
            self.assertEqual(self.request(self.file_url(path))[0], 403)
        self.assertEqual(self.request("/../server/config.py")[0], 403)
        self.assertEqual(self.request("/api/missing")[0], 404)

    def test_sse_only_publishes_named_index_events(self) -> None:
        connection = http.client.HTTPConnection("127.0.0.1", self.port,
                                                timeout=3)
        connection.request("GET", "/api/events")
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.readline(), b": connected\n")
        self.assertEqual(response.readline(), b"\n")
        self.assertEqual(self.request("/api/reindex", "POST")[0], 200)
        self.assertEqual(response.readline(), b"event: index_updated\n")
        self.assertTrue(response.readline().startswith(b"data: "))
        response.close()
        connection.close()

    def test_single_range_parser(self) -> None:
        self.assertEqual(byte_range("bytes=4-", 10), (4, 9, True))
        self.assertEqual(byte_range("bytes=-50", 10), (0, 9, True))
        self.assertEqual(byte_range(None, 0), (0, -1, False))
        for value in ("bytes=", "bytes=2-1", "bytes=0-2,4-6", "bytes=-0"):
            with self.subTest(value=value), self.assertRaises(RangeError):
                byte_range(value, 10)


if __name__ == "__main__":
    unittest.main()
