"""便签: 撤下 and 放回, saves that would overwrite an outside edit, honest limits."""
from __future__ import annotations
import datetime as dt
import http.client
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from ..api import Server
from ..files import FileError
from ..indexer import Indexer
from ..notes import CONFLICT, GONE, OCCUPIED, NoteConflict, Notes, stamp
from .support import fixture_config, write

NOTE_KEYS = {"id", "rope", "text", "color", "date", "created", "updated_at"}


def note_file(text: str, shade: str = "lilac") -> str:
    return f"---\n颜色: {shade}\n---\n{text}\n"


class NotesTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.workspace = Path(self.folder.name) / "工作区"
        self.workspace.mkdir()
        self.notes = Notes(self.workspace)

    def tearDown(self) -> None:
        self.folder.cleanup()

    def ropes(self) -> dict[str, dict]:
        return {rope["name"]: rope for rope in self.notes.snapshot()["ropes"]}

    def ids(self, rope: str = "随手记") -> list[str]:
        return [note["id"] for note in self.ropes()[rope]["notes"]]

    def path(self, identifier: str, rope: str = "随手记") -> Path:
        return self.workspace / "便签" / rope / f"{identifier}.md"


class UndoTests(NotesTestCase):
    def test_take_down_says_where_the_note_hung_and_restore_puts_it_back(self):
        for text in ("一", "二", "三"):
            self.notes.save({"text": text, "color": "mint"})
        before = self.ids()
        opened = self.ropes()["随手记"]["notes"][1]
        result = self.notes.take_down({"id": before[1], "rope": "随手记"})
        self.assertEqual(result, {"id": before[1], "rope": "随手记", "index": 1,
                                  "kept_in": "便签/.已撤下/随手记"})
        snapshot = self.notes.snapshot()
        self.assertEqual([note["id"] for note in snapshot["ropes"][0]["notes"]],
                         [before[0], before[2]])
        [kept] = snapshot["shelf"]
        self.assertEqual(set(kept), {"id", "rope", "text", "color", "updated_at", "taken_down_at"})
        self.assertEqual((kept["id"], kept["rope"], kept["text"], kept["color"]),
                         (before[1], "随手记", "二", "mint"))
        self.assertEqual(kept["updated_at"], opened["updated_at"])
        restored = self.notes.restore({"id": before[1], "rope": "随手记", "index": result["index"]})
        self.assertEqual(restored, opened)   # same shape, and moving kept the edit time
        self.assertEqual(self.ids(), before)
        self.assertEqual(self.notes.snapshot()["shelf"], [])
        self.assertTrue(self.path(before[1]).is_file())
        self.assertFalse((self.workspace / "便签/.已撤下/随手记" / f"{before[1]}.md").exists())

    def test_restore_position_is_kept_inside_the_group(self):
        ids = [self.notes.save({"text": text})["id"] for text in ("甲", "乙", "丙")]
        cases = ((ids[0], 99, [ids[1], ids[2], ids[0]]),     # past the end: last
                 (ids[0], -3, [ids[0], ids[1], ids[2]]),     # before the start: first
                 (ids[1], None, [ids[0], ids[2], ids[1]]),   # no index: last
                 (ids[1], True, [ids[0], ids[2], ids[1]]),   # not a number: last
                 (ids[2], "0", [ids[0], ids[1], ids[2]]))
        for identifier, index, expected in cases:
            with self.subTest(index=index):
                self.notes.take_down({"id": identifier, "rope": "随手记"})
                value = {"id": identifier, "rope": "随手记"}
                if index is not None:
                    value["index"] = index
                self.notes.restore(value)
                self.assertEqual(self.ids(), expected)

    def test_restore_refuses_politely(self):
        note = self.notes.save({"text": "会被撤下"})
        with self.assertRaises(ValueError) as caught:   # still on the board, not taken down
            self.notes.restore({"id": note["id"], "rope": "随手记"})
        self.assertEqual(str(caught.exception), GONE)
        self.notes.take_down({"id": note["id"], "rope": "随手记"})
        write(self.path(note["id"]), note_file("同名的新便签"))
        with self.assertRaises(ValueError) as caught:
            self.notes.restore({"id": note["id"], "rope": "随手记"})
        self.assertEqual(str(caught.exception), OCCUPIED)
        self.assertIn("同名的新便签", self.path(note["id"]).read_text(encoding="utf-8"))
        self.assertTrue((self.workspace / "便签/.已撤下/随手记" / f"{note['id']}.md").is_file())
        for bad in ({"id": "../x", "rope": "随手记"}, {"id": note["id"], "rope": "../外面"},
                    {"id": note["id"], "rope": ".已撤下"}):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                self.notes.restore(bad)

    def test_restore_brings_back_a_group_that_was_put_away(self):
        self.notes.rope({"action": "create", "name": "灵感"})
        note = self.notes.save({"text": "夜景的灵感", "rope": "灵感"})
        self.notes.take_down({"id": note["id"], "rope": "灵感"})
        self.notes.rope({"action": "remove", "name": "灵感"})
        self.assertNotIn("灵感", self.ropes())
        restored = self.notes.restore({"id": note["id"], "rope": "灵感", "index": 0})
        self.assertEqual((restored["rope"], restored["text"]), ("灵感", "夜景的灵感"))
        self.assertEqual(self.ids("灵感"), [note["id"]])

    def test_restore_never_follows_links(self):
        identifier = "20261022-100000-abcd"
        outside = Path(self.folder.name) / "outside"
        write(outside / f"{identifier}.md", "外面的文件")
        base = self.workspace / "便签/.已撤下"
        base.mkdir(parents=True)
        (base / "随手记").symlink_to(outside, target_is_directory=True)
        (base / "灵感").mkdir()
        (base / "灵感" / f"{identifier}.md").symlink_to(outside / f"{identifier}.md")
        for rope in ("随手记", "灵感"):
            with self.subTest(rope=rope), self.assertRaises(FileError):
                self.notes.restore({"id": identifier, "rope": rope})
            self.assertFalse((self.workspace / "便签" / rope).exists())
        self.assertEqual((outside / f"{identifier}.md").read_text(encoding="utf-8"), "外面的文件")
        self.assertEqual(self.notes.snapshot()["shelf"], [])   # links are not offered either

    def test_shelf_lists_the_newest_thirty_first(self):
        ids = [f"20261022-1000{index:02d}-ab{index:02d}" for index in range(32)]
        for identifier in ids:
            write(self.path(identifier), note_file("长" * 300, "pink"))
        for identifier in ids:   # taken down in this order: the last one is the newest
            self.notes.take_down({"id": identifier, "rope": "随手记"})
        shelf = self.notes.snapshot()["shelf"]
        self.assertEqual([entry["id"] for entry in shelf], ids[::-1][:30])
        self.assertEqual(len(shelf[0]["text"]), 200)
        self.assertEqual(shelf[0]["color"], "pink")
        self.assertEqual(self.ropes()["随手记"]["notes"], [])   # never mixed into the groups

    def test_old_edits_taken_down_recently_come_first(self):
        old, new = "20261001-090000-aaaa", "20261020-090000-bbbb"
        for identifier in (old, new):
            write(self.path(identifier), note_file(identifier))
        long_ago = self.path(old).stat().st_mtime - 30 * 86400
        os.utime(self.path(old), (long_ago, long_ago))
        self.notes.take_down({"id": new, "rope": "随手记"})
        self.notes.take_down({"id": old, "rope": "随手记"})
        self.assertEqual([entry["id"] for entry in self.notes.snapshot()["shelf"]], [old, new])


class DeleteTests(NotesTestCase):
    """Deleting moves files to the system Trash; a temporary home stands in for ~."""

    def setUp(self) -> None:
        super().setUp()
        self.home = Path(self.folder.name) / "home"
        self.home.mkdir()
        patcher = patch.object(Path, "home", return_value=self.home)
        patcher.start()
        self.addCleanup(patcher.stop)
        # the stand-in ~/.Trash, also on Windows (never the real Recycle Bin)
        windows = patch("spt.server.files.WINDOWS", False)
        windows.start()
        self.addCleanup(windows.stop)

    def trash(self) -> list[str]:
        folder = self.home / ".Trash"
        return sorted(path.name for path in folder.iterdir()) if folder.is_dir() else []

    def test_delete_moves_a_board_note_to_the_trash_and_out_of_the_layout(self):
        ids = [self.notes.save({"text": text})["id"] for text in ("一", "二", "三")]
        result = self.notes.delete({"id": ids[1], "rope": "随手记"})
        self.assertEqual(result, {"id": ids[1], "rope": "随手记", "trashed": f"{ids[1]}.md"})
        self.assertEqual(self.ids(), [ids[0], ids[2]])
        self.assertEqual(self.notes.layout()["order"]["随手记"], [ids[0], ids[2]])
        self.assertFalse(self.path(ids[1]).exists())
        self.assertEqual(self.trash(), [f"{ids[1]}.md"])
        self.assertIn("二", (self.home / ".Trash" / f"{ids[1]}.md").read_text(encoding="utf-8"))
        self.assertEqual(self.notes.snapshot()["shelf"], [])     # deleted, not taken down
        with self.assertRaises(FileNotFoundError):
            self.notes.delete({"id": ids[1], "rope": "随手记"})
        for bad in ({"id": "../x", "rope": "随手记"}, {"id": ids[0], "rope": "../外面"},
                    {"id": ids[0], "rope": ".已撤下"}):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                self.notes.delete(bad)
        self.assertEqual(self.ids(), [ids[0], ids[2]])

    def test_delete_from_the_shelf(self):
        note = self.notes.save({"text": "撤下再删"})
        self.notes.take_down({"id": note["id"], "rope": "随手记"})
        with self.assertRaises(FileNotFoundError):            # not on the board any more
            self.notes.delete({"id": note["id"], "rope": "随手记"})
        result = self.notes.delete({"id": note["id"], "rope": "随手记", "shelf": True})
        self.assertEqual(result, {"id": note["id"], "rope": "随手记", "trashed": f"{note['id']}.md"})
        self.assertEqual(self.notes.snapshot()["shelf"], [])
        self.assertFalse((self.workspace / "便签/.已撤下/随手记" / f"{note['id']}.md").exists())
        self.assertEqual(self.trash(), [f"{note['id']}.md"])
        with self.assertRaises(ValueError) as caught:
            self.notes.delete({"id": note["id"], "rope": "随手记", "shelf": True})
        self.assertEqual(str(caught.exception), GONE)

    def test_the_same_name_in_the_trash_gets_a_number(self):
        identifier = "20261022-120000-abcd"
        for text in ("第一次", "第二次", "第三次"):
            write(self.path(identifier), note_file(text))
            self.notes.delete({"id": identifier, "rope": "随手记"})
        self.assertEqual(self.trash(), [f"{identifier} 2.md", f"{identifier} 3.md", f"{identifier}.md"])
        self.assertIn("第三次", (self.home / ".Trash" / f"{identifier} 3.md").read_text(encoding="utf-8"))

    def test_clear_shelf_takes_every_group_whole_and_leaves_nothing_behind(self):
        ids = [self.notes.save({"text": text})["id"] for text in ("甲", "乙")]
        for identifier in ids:
            self.notes.take_down({"id": identifier, "rope": "随手记"})
        self.notes.rope({"action": "create", "name": "灵感"})
        kept = self.notes.save({"text": "灵感的", "rope": "灵感"})
        self.notes.take_down({"id": kept["id"], "rope": "灵感"})
        self.notes.rope({"action": "remove", "name": "灵感"})   # the emptied folder is put away whole
        shelf = self.workspace / "便签/.已撤下"
        self.assertEqual(len(list(shelf.iterdir())), 3)
        self.assertEqual(self.notes.clear_shelf(), {"trashed": 3})
        self.assertEqual(list(shelf.iterdir()), [])
        self.assertEqual(self.notes.snapshot()["shelf"], [])
        names = self.trash()
        self.assertIn("随手记", names)
        self.assertIn("灵感", names)
        self.assertEqual(len(names), 3)
        self.assertEqual(sorted(path.name for path in (self.home / ".Trash/随手记").iterdir()),
                         sorted(f"{identifier}.md" for identifier in ids))
        self.assertEqual((self.home / ".Trash/灵感" / f"{kept['id']}.md").is_file(), True)
        self.assertEqual(self.notes.clear_shelf(), {"trashed": 0})
        self.assertIn("随手记", self.ropes())                     # the board is untouched

    def test_clear_shelf_moves_links_without_following_them(self):
        outside = Path(self.folder.name) / "outside"
        write(outside / "20261022-100000-abcd.md", "外面的文件")
        base = self.workspace / "便签/.已撤下"
        base.mkdir(parents=True)
        (base / "随手记").symlink_to(outside, target_is_directory=True)
        self.assertEqual(self.notes.clear_shelf(), {"trashed": 1})
        self.assertTrue((self.home / ".Trash/随手记").is_symlink())
        self.assertEqual((outside / "20261022-100000-abcd.md").read_text(encoding="utf-8"), "外面的文件")
        self.assertEqual(list(base.iterdir()), [])


class LimitTests(NotesTestCase):
    def test_groups_say_how_many_notes_are_not_shown(self):
        ids = [f"20261022-1100{index:02d}-cd{index:02d}" for index in range(5)]
        for index, identifier in enumerate(ids):
            write(self.path(identifier), note_file(f"第{index}张"))
        self.notes.rope({"action": "create", "name": "灵感"})
        with patch("spt.server.notes.NOTE_LIMIT", 3):
            ropes = self.ropes()
            self.assertEqual([note["id"] for note in ropes["随手记"]["notes"]], ids[:3])
            self.assertEqual(ropes["随手记"]["hidden"], 2)
            self.assertEqual(ropes["灵感"]["hidden"], 0)
            # writers keep the whole order, hidden notes included
            self.notes.move({"id": ids[4], "rope": "随手记", "to": "随手记", "index": 0})
            self.assertEqual(self.notes.layout()["order"]["随手记"], [ids[4]] + ids[:4])
            self.assertEqual(self.notes.take_down({"id": ids[3], "rope": "随手记"})["index"], 4)
        self.assertEqual(self.ropes()["随手记"]["hidden"], 0)


class ConflictTests(NotesTestCase):
    def outside_edit(self, identifier: str, text: str, seconds: float) -> None:
        path = self.path(identifier)
        later = path.stat().st_mtime + seconds
        path.write_text(note_file(text, "sky"), encoding="utf-8")
        os.utime(path, (later, later))

    def test_saving_over_an_outside_edit_is_refused(self):
        saved = self.notes.save({"text": "原来的内容"})
        self.assertEqual(set(saved), NOTE_KEYS)
        self.assertEqual(saved["updated_at"], stamp(self.path(saved["id"]).stat().st_mtime))
        self.outside_edit(saved["id"], "Claude 改过的内容", 5)
        with self.assertRaises(NoteConflict) as caught:
            self.notes.save({"id": saved["id"], "rope": "随手记", "text": "我的修改",
                             "updated_at": saved["updated_at"]})
        self.assertEqual(str(caught.exception), CONFLICT)
        current = caught.exception.note
        self.assertEqual((current["text"], current["color"]), ("Claude 改过的内容", "sky"))
        self.assertIn("Claude 改过的内容", self.path(saved["id"]).read_text(encoding="utf-8"))
        # with the time the note has now, the save goes through
        again = self.notes.save({"id": saved["id"], "rope": "随手记", "text": "我的修改",
                                 "updated_at": current["updated_at"]})
        self.assertEqual(again["text"], "我的修改")
        self.assertEqual(again["updated_at"], stamp(self.path(saved["id"]).stat().st_mtime))

    def test_saves_without_a_time_and_new_notes_never_conflict(self):
        saved = self.notes.save({"text": "旧客户端"})
        self.outside_edit(saved["id"], "外面改的", 60)
        for value in ({}, {"updated_at": None}, {"updated_at": ""}):
            with self.subTest(value=value):
                self.notes.save({"id": saved["id"], "rope": "随手记", "text": "照样能存", **value})
        self.assertIn("照样能存", self.path(saved["id"]).read_text(encoding="utf-8"))
        fresh = self.notes.save({"text": "新的一张", "updated_at": "2000-01-01T00:00:00+00:00"})
        self.assertEqual(fresh["text"], "新的一张")

    def test_the_same_moment_written_another_way_is_not_a_conflict(self):
        saved = self.notes.save({"text": "时区"})
        path = self.path(saved["id"])
        moment = dt.datetime(2026, 10, 22, 9, 30, 15, tzinfo=dt.timezone.utc)
        utc = moment.timestamp() + 0.4   # the fraction of a second is not shown, so it never counts
        written = (stamp(utc), moment.isoformat(), moment.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                   moment.astimezone(dt.timezone(dt.timedelta(hours=9))).isoformat())
        for value in written:
            with self.subTest(updated_at=value):
                os.utime(path, (utc, utc))
                self.notes.save({"id": saved["id"], "rope": "随手记", "text": "时区",
                                 "updated_at": value})
        for value in ("昨天", "2026-10-22T09:30:14+00:00", 12345):
            with self.subTest(updated_at=value), self.assertRaises(NoteConflict):
                os.utime(path, (utc, utc))
                self.notes.save({"id": saved["id"], "rope": "随手记", "text": "时区",
                                 "updated_at": value})


class NotesHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.config = fixture_config(Path(cls.temporary.name))
        cls.config.workspace.mkdir(parents=True)
        cls.indexer = Indexer(cls.config)
        cls.indexer.reindex()
        cls.server = Server(cls.indexer)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)
        cls.temporary.cleanup()

    def call(self, path: str, value: object | None = None) -> tuple[int, dict]:
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        if value is None:
            connection.request("GET", path)
        else:
            connection.request("POST", path, body=json.dumps(value).encode(),
                               headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        result = response.status, json.loads(response.read() or b"{}")
        connection.close()
        return result

    def test_take_down_and_restore(self):
        status, saved = self.call("/api/notes/save", {"text": "接口便签", "rope": "接口"})
        self.assertEqual((status, set(saved)), (200, NOTE_KEYS))
        status, removed = self.call("/api/notes/remove", {"id": saved["id"], "rope": "接口"})
        self.assertEqual((status, removed["rope"], removed["index"]), (200, "接口", 0))
        status, notes = self.call("/api/notes")
        self.assertEqual(notes["shelf"][0]["id"], saved["id"])
        self.assertEqual({rope["name"]: rope["hidden"] for rope in notes["ropes"]}["接口"], 0)
        status, restored = self.call("/api/notes/restore", {"id": saved["id"], "rope": "接口",
                                                            "index": removed["index"]})
        self.assertEqual((status, restored), (200, saved))
        status, error = self.call("/api/notes/restore", {"id": saved["id"], "rope": "接口"})
        self.assertEqual((status, error), (400, {"error": GONE}))

    def test_delete_and_clear_shelf_go_to_the_trash(self):
        home = Path(self.temporary.name) / "home"
        home.mkdir(exist_ok=True)
        with patch.object(Path, "home", return_value=home), patch("spt.server.files.WINDOWS", False):
            status, saved = self.call("/api/notes/save", {"text": "要删的", "rope": "删除"})
            status, gone = self.call("/api/notes/delete", {"id": saved["id"], "rope": "删除"})
            self.assertEqual((status, gone), (200, {"id": saved["id"], "rope": "删除",
                                                    "trashed": f"{saved['id']}.md"}))
            self.assertTrue((home / ".Trash" / f"{saved['id']}.md").is_file())
            self.assertEqual(self.call("/api/notes/delete", {"id": saved["id"], "rope": "删除"})[0], 404)
            status, second = self.call("/api/notes/save", {"text": "撤下后清空", "rope": "删除"})
            self.call("/api/notes/remove", {"id": second["id"], "rope": "删除"})
            self.assertEqual(self.call("/api/notes")[1]["shelf"][0]["id"], second["id"])
            status, cleared = self.call("/api/notes/shelf/clear", {})
            self.assertEqual((status, cleared), (200, {"trashed": 1}))
            self.assertEqual(self.call("/api/notes")[1]["shelf"], [])
            self.assertTrue((home / ".Trash/删除" / f"{second['id']}.md").is_file())
            self.assertEqual(self.call("/api/notes/shelf/clear", {})[1], {"trashed": 0})

    def test_a_stale_save_answers_409_with_the_current_note(self):
        status, saved = self.call("/api/notes/save", {"text": "第一版", "rope": "冲突"})
        path = self.config.workspace / "便签/冲突" / f"{saved['id']}.md"
        later = path.stat().st_mtime + 5
        path.write_text(note_file("Codex 改的", "butter"), encoding="utf-8")
        os.utime(path, (later, later))
        status, body = self.call("/api/notes/save", {"id": saved["id"], "rope": "冲突", "text": "第二版",
                                                     "updated_at": saved["updated_at"]})
        self.assertEqual(status, 409)
        self.assertEqual((body["error"], body["conflict"]), (CONFLICT, True))
        self.assertEqual(set(body["note"]), NOTE_KEYS)
        self.assertEqual((body["note"]["text"], body["note"]["color"]), ("Codex 改的", "butter"))
        self.assertIn("Codex 改的", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
