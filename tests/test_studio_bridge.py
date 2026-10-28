"""Native-origin mount: new data and existing publishing stay independent."""
from __future__ import annotations

import http.client
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import quote

from app import core, server, studio_bridge
from spt.server.indexer import Indexer
from spt.server.tests.support import fixture_config, populate, write


class WorkbenchMountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.config = fixture_config(cls.root)
        cls.paths = populate(cls.config.workspace)
        write(cls.config.ui / "index.html", '<!doctype html><body '
              'data-api-base="/api" data-legacy-base=""></body>')
        cls.indexer = Indexer(cls.config)
        cls.indexer.reindex()
        cls.http = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.http.workspace_indexer = cls.indexer
        cls.port = cls.http.server_port
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join(timeout=3)
        cls.temporary.cleanup()

    def request(self, path: str, method: str = "GET",
                headers: dict[str, str] | None = None,
                body: bytes | None = None
                ) -> tuple[int, dict[str, str], bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port,
                                                timeout=3)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def test_native_health_and_new_health_are_distinct(self) -> None:
        old = json.loads(self.request("/api/health")[2])
        new = json.loads(self.request("/api/spt/health")[2])
        self.assertEqual(old["app"], "media-workspace")
        self.assertEqual(new["app"], "spt")

    def test_workspace_root_redirect_and_configured_same_origin(self) -> None:
        self.assertEqual(self.request("/")[0], 302)
        self.assertEqual(self.request("/")[1]["Location"], "/workspace/")
        with patch.object(studio_bridge, "UI", self.config.ui):
            status, headers, body = self.request("/workspace/")
            self.assertEqual(status, 200)
            self.assertIn(b'data-api-base="/api/spt"', body)
            self.assertIn(b'data-legacy-base="/legacy/"', body)
            self.assertIn("script-src 'self'", headers["Content-Security-Policy"])
            self.assertEqual(self.request("/workspace/", "HEAD")[2], b"")
            self.assertEqual(self.request("/workspace/../outside.txt")[0], 403)

    def test_old_editor_and_new_file_range_still_work(self) -> None:
        self.assertIn(b"/static/desk.js", self.request("/legacy/")[2])
        self.assertIn(b"/workspace/", self.request("/legacy/")[2])
        works = json.loads(self.request("/api/spt/works")[2])["works"]
        work = next(item for item in works if item["title"] == "火光")
        path = quote("火光-发布版-1080p.mp4", safe="")
        url = f"/api/spt/works/{work['id']}/file?path={path}"
        status, headers, body = self.request(url, headers={"Range": "bytes=2-5"})
        self.assertEqual((status, body), (206, b"2345"))
        self.assertEqual(headers["Content-Range"], "bytes 2-5/10")
        self.assertEqual(self.request(url, "HEAD")[2], b"")

    def test_mount_blocks_cross_origin_and_has_truthful_dashboard(self) -> None:
        with patch.object(studio_bridge, "dashboard_context",
                          return_value={"accounts": [], "posts": []}):
            body = self.request("/api/spt/dashboard")[2]
            self.assertEqual(json.loads(body), {"accounts": [], "posts": []})
        for headers in ({"Origin": "https://example.org"},
                        {"Sec-Fetch-Site": "cross-site"}):
            self.assertEqual(self.request("/api/spt/health", headers=headers)[0], 403)
        self.assertEqual(self.request("/api/spt/reindex", "POST")[0], 200)

    def test_legacy_identity_read_is_readonly_and_excludes_payload(self) -> None:
        database = self.root / "identities.sqlite3"
        with sqlite3.connect(database) as db:
            db.execute("CREATE TABLE accounts (id,platform,handle,payload)")
            db.execute("INSERT INTO accounts VALUES (?,?,?,?)",
                       ("identity", "instagram", "local", "PRIVATE"))
            db.execute("INSERT INTO accounts VALUES (?,?,?,?)",
                       ("named", "tiktok", "other", json.dumps(
                           {"name": "本人", "brand": "客户", "notes": "secret-note",
                            "status": "本地账号档案"})))
        before = database.read_bytes()
        with patch.object(core, "DB", database):
            result = studio_bridge.legacy_accounts()
        self.assertEqual(result, [
            {"id": "identity", "platform": "instagram", "handle": "local",
             "name": None, "brand": None},
            {"id": "named", "platform": "tiktok", "handle": "other",
             "name": "本人", "brand": "客户"}])
        self.assertNotIn("secret-note", json.dumps(result, ensure_ascii=False))
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.assertEqual(database.read_bytes(), before)

    def test_legacy_identities_survive_a_wal_database_without_side_files(self) -> None:
        database = self.root / "wal" / "media.sqlite3"
        with patch.object(core, "DB", database):
            core.create_account({"platform": "tiktok", "handle": "walled",
                                 "name": "本人", "brand": "客户"})
            with sqlite3.connect(database) as db:
                db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            for suffix in ("-wal", "-shm"):
                side = database.with_name(database.name + suffix)
                if side.exists():
                    side.unlink()
            result = studio_bridge.legacy_accounts()
        self.assertEqual([(item["platform"], item["handle"], item["brand"])
                          for item in result], [("tiktok", "walled", "客户")])


if __name__ == "__main__":
    unittest.main()
