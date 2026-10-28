"""Deletes go to the system Trash: move_to_trash, the work trash route, 整理客户 over HTTP.

A temporary folder stands in for the home folder, so the real ~/.Trash is never touched.
"""
from __future__ import annotations
import errno
import http.client
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from ..api import Server
from ..files import FileError, move_to_trash
from ..indexer import Indexer
from .support import fixture_config, populate, write
from .test_clients import GROUPS, TABLE


class MoveToTrashTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.trash = self.root / "Trash"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def names(self) -> list[str]:
        return sorted(path.name for path in self.trash.iterdir()) if self.trash.is_dir() else []

    def test_files_and_folders_move_whole_and_same_names_get_numbers(self) -> None:
        write(self.root / "a.md", "第一")
        self.assertEqual(move_to_trash(self.root / "a.md", trash_dir=self.trash), self.trash / "a.md")
        write(self.root / "a.md", "第二")
        self.assertEqual(move_to_trash(self.root / "a.md", trash_dir=self.trash).name, "a 2.md")
        write(self.root / "a.md", "第三")
        self.assertEqual(move_to_trash(self.root / "a.md", trash_dir=self.trash).name, "a 3.md")
        self.assertEqual((self.trash / "a.md").read_text(encoding="utf-8"), "第一")
        self.assertEqual((self.trash / "a 3.md").read_text(encoding="utf-8"), "第三")
        work = self.root / "2026-10-20-AK-轮播.v2"
        write(work / "V1/正文.txt", "提示词")
        write(work / "封面.jpg", b"cover")
        moved = move_to_trash(work, trash_dir=self.trash)
        self.assertEqual(moved.name, "2026-10-20-AK-轮播.v2")      # a folder's name is not split at a dot
        self.assertEqual((moved / "V1/正文.txt").read_text(encoding="utf-8"), "提示词")
        self.assertEqual((moved / "封面.jpg").read_bytes(), b"cover")
        work.mkdir()
        self.assertEqual(move_to_trash(work, trash_dir=self.trash).name, "2026-10-20-AK-轮播.v2 2")
        self.assertFalse((self.root / "a.md").exists())
        self.assertFalse(work.exists())
        self.assertEqual(self.names(), ["2026-10-20-AK-轮播.v2", "2026-10-20-AK-轮播.v2 2",
                                        "a 2.md", "a 3.md", "a.md"])

    def test_links_move_as_links_and_missing_paths_are_not_found(self) -> None:
        write(self.root / "target.txt", "原件")
        (self.root / "link").symlink_to(self.root / "target.txt")
        (self.root / "dangling").symlink_to(self.root / "nowhere")
        moved = move_to_trash(self.root / "link", trash_dir=self.trash)
        self.assertTrue(moved.is_symlink())
        self.assertEqual((self.root / "target.txt").read_text(encoding="utf-8"), "原件")
        self.assertTrue(move_to_trash(self.root / "dangling", trash_dir=self.trash).is_symlink())
        with self.assertRaises(FileNotFoundError):
            move_to_trash(self.root / "missing", trash_dir=self.trash)
        self.assertEqual(self.names(), ["dangling", "link"])

    @unittest.skipUnless(hasattr(os, "getuid"), "macOS volumes: .Trashes/<uid>")
    def test_another_volume_uses_its_own_trashes_folder(self) -> None:
        write(self.root / "外置.txt", "外置盘上的文件")
        volume = self.root / "volume"
        real_rename = os.rename

        def rename(source, target):
            if str(target).startswith(str(self.trash)):
                raise OSError(errno.EXDEV, "Cross-device link")
            real_rename(source, target)

        with patch("spt.server.files.volume_root", return_value=volume), patch("os.rename", rename):
            moved = move_to_trash(self.root / "外置.txt", trash_dir=self.trash)
        self.assertEqual(moved, volume / ".Trashes" / str(os.getuid()) / "外置.txt")
        self.assertEqual(moved.read_text(encoding="utf-8"), "外置盘上的文件")
        self.assertEqual(self.names(), [])

        def refuse(source, target):
            raise OSError(errno.EXDEV, "Cross-device link")

        write(self.root / "再来.txt", "x")
        with patch("spt.server.files.volume_root", return_value=volume), patch("os.rename", refuse):
            with self.assertRaises(FileError) as caught:
                move_to_trash(self.root / "再来.txt", trash_dir=self.trash)
        self.assertEqual(str(caught.exception), "放不进废纸篓：Cross-device link")
        self.assertTrue((self.root / "再来.txt").is_file())

    def test_other_errors_are_reported_not_hidden(self) -> None:
        write(self.root / "x.txt", "x")

        def refuse(source, target):
            raise PermissionError(errno.EACCES, "Permission denied")

        with patch("os.rename", refuse), self.assertRaises(FileError) as caught:
            move_to_trash(self.root / "x.txt", trash_dir=self.trash)
        self.assertEqual(str(caught.exception), "放不进废纸篓：Permission denied")
        self.assertTrue((self.root / "x.txt").is_file())


class TrashRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.config = fixture_config(root)
        self.paths = populate(self.config.workspace)
        write(self.config.workspace / "客户.md", TABLE)
        self.home = root / "home"
        self.home.mkdir()
        patcher = patch.object(Path, "home", return_value=self.home)
        patcher.start()
        self.addCleanup(patcher.stop)
        # the stand-in ~/.Trash, also on Windows (never the real Recycle Bin)
        windows = patch("spt.server.files.WINDOWS", False)
        windows.start()
        self.addCleanup(windows.stop)
        self.indexer = Indexer(self.config)
        self.indexer.reindex()
        self.server = Server(self.indexer)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.temporary.cleanup()

    def call(self, method: str, path: str, value: object | None = None,
             content_type: str = "application/json") -> tuple[int, dict]:
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        if value is None:
            connection.request(method, path)
        else:
            connection.request(method, path, body=json.dumps(value).encode(),
                               headers={"Content-Type": content_type})
        response = connection.getresponse()
        result = response.status, json.loads(response.read() or b"{}")
        connection.close()
        return result

    def work_id(self, title: str) -> str:
        return next(work["id"] for work in self.indexer.store.list_works() if work["title"] == title)

    def trash_names(self) -> list[str]:
        folder = self.home / ".Trash"
        return sorted(path.name for path in folder.iterdir()) if folder.is_dir() else []

    def test_trashing_a_work_moves_the_folder_and_drops_it_from_the_index(self) -> None:
        identifier = self.work_id("火光")
        folder = self.paths["火光"]
        store = self.indexer.store
        its_items = {item["id"] for item in store.list_items(all_versions=True)
                     if item["work_id"] == identifier}
        self.assertTrue(its_items)
        subscriber = self.indexer.events.subscribe()
        status, result = self.call("POST", f"/api/works/{identifier}/trash", {})
        self.assertEqual((status, result), (200, {"id": identifier, "trashed": "2026-10-20-AK-火光"}))
        self.assertFalse(folder.exists())
        moved = self.home / ".Trash/2026-10-20-AK-火光"
        self.assertEqual((moved / "V3/正文.txt").read_text(encoding="utf-8"), "V3提示词")
        self.assertEqual((moved / "火光-发布版-1080p.mp4").read_bytes(), b"0123456789")
        self.assertEqual(self.trash_names(), ["2026-10-20-AK-火光"])
        self.assertEqual(self.call("GET", f"/api/works/{identifier}")[0], 404)
        self.assertEqual(len(self.call("GET", "/api/works")[1]["works"]), 3)
        remaining = {item["id"] for item in store.list_items(all_versions=True)}
        self.assertFalse(its_items & remaining)
        with store.connect() as connection:
            for table in ("versions", "media", "publish_records", "timeline", "documents", "evidence"):
                count = connection.execute(f"SELECT COUNT(*) FROM {table} WHERE work_id=?",
                                           (identifier,)).fetchone()[0]
                self.assertEqual(count, 0, table)
            thumbs = [row[0] for row in connection.execute("SELECT item_id FROM item_thumbs")]
            self.assertFalse(its_items & set(thumbs))
        event = subscriber.get(timeout=3)                       # open pages refresh at once
        self.assertEqual((event["count"], event["trashed"]), (3, identifier))
        health = self.call("GET", "/api/health")[1]
        self.assertEqual(health["counts"]["works"], 3)
        self.assertEqual(next(entry for entry in health["clients"] if entry["code"] == "AK")["works"], 3)
        self.assertEqual(self.call("POST", f"/api/works/{identifier}/trash", {})[0], 404)
        self.indexer.reindex()                                  # a rebuild agrees with the folder
        self.assertEqual(len(store.list_works()), 3)

    def test_unknown_ids_links_and_other_requests_are_refused(self) -> None:
        self.assertEqual(self.call("POST", "/api/works/" + "0" * 20 + "/trash", {})[0], 404)
        self.assertEqual(self.call("POST", "/api/works/abc/trash", {})[0], 409)
        identifier = self.work_id("环绕")
        self.assertEqual(self.call("POST", f"/api/works/{identifier}/trash", {}, "text/plain")[0], 415)
        self.assertEqual(self.call("GET", f"/api/works/{identifier}/trash")[0], 404)
        folder = self.paths["环绕"]
        outside = Path(self.temporary.name) / "outside"
        os.rename(folder, outside)
        folder.symlink_to(outside, target_is_directory=True)   # the folder is a link now: not followed
        status, error = self.call("POST", f"/api/works/{identifier}/trash", {})
        self.assertEqual(status, 400)
        self.assertIn("符号链接", error["error"])
        self.assertTrue(folder.is_symlink())
        self.assertTrue((outside / "封面.jpg").is_file())
        self.assertEqual(self.trash_names(), [])
        self.assertEqual(len(self.indexer.store.list_works()), 4)   # nothing was dropped

    def test_clients_save_route_rewrites_the_file_and_answers_with_health(self) -> None:
        status, body = self.call("POST", "/api/clients/save", {"groups": GROUPS})
        self.assertEqual(status, 200)
        self.assertEqual(set(body), {"clients", "client_groups"})
        self.assertEqual(body["client_groups"], ["自己", "餐厅", "客户"])
        self.assertEqual([(entry["code"], entry["group"], entry["works"]) for entry in body["clients"]],
                         [("自家", "自己", 0), ("示例创作者", "自己", 0), ("AK", "餐厅", 4), ("Lemon", "客户", 0)])
        self.assertEqual(body["clients"][1]["color"], "#d6a4ff")
        text = (self.config.workspace / "客户.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# 客户\n\n| 简称 | 名字 | 类型 | 颜色 |\n"))
        self.assertIn("| AK | Sample Studio | 餐厅 | #f0b35c |\n", text)
        status, error = self.call("POST", "/api/clients/save",
                                  {"groups": [{"name": "自己", "clients": [{"code": "自家"}]}]})
        self.assertEqual((status, error), (400, {"error": "「AK」还有 4 件作品，不能删"}))
        self.assertEqual(self.call("GET", "/api/health")[1]["client_groups"], ["自己", "餐厅", "客户"])
        self.assertEqual(self.call("POST", "/api/clients/save", {}), (400, {"error": "至少要有一个分组"}))
        self.assertEqual(self.call("POST", "/api/clients/save", {"groups": GROUPS}, "text/plain")[0], 415)


if __name__ == "__main__":
    unittest.main()
