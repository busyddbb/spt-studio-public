from __future__ import annotations
import tempfile
import unittest
from pathlib import Path

from ..config import Config
from ..indexer import Indexer
from ..intake import IntakeError, add_work, secret
from .support import snapshot, write


class IntakeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        root = Path(self.folder.name)
        self.workspace = root / "工作区"
        self.workspace.mkdir()
        self.project = root / "电影创作"
        write(self.project / "4-影片/雨夜/雨夜-final.mp4", b"video")
        write(self.project / "4-影片/雨夜/still.jpg", b"jpeg")
        write(self.project / "4-影片/雨夜/提示词.txt", "雨夜重逢，霓虹倒影")
        write(self.project / "4-影片/雨夜/制作记录.md", "# 雨夜\n第二版换了镜头")
        write(self.project / "work/v1/正文.txt", "第一版提示词")
        write(self.project / "work/v1/01_人物.jpg", b"ref")
        write(self.project / "work/v1/.DS_Store", b"x")
        write(self.project / "work/v1/cookies.txt", "session=1")
        write(self.project / "work/v2/正文.txt", "第二版提示词")
        self.ui = root / "ui"
        write(self.ui / "index.html", "<!doctype html>")
        self.cache = root / "cache"

    def tearDown(self) -> None:
        self.folder.cleanup()

    def add(self, **values):
        shot = self.project / "4-影片/雨夜"
        options = dict(field="电影", client="自家", topic="雨夜重逢", date="2026-10-20",
                       title="雨夜重逢", tags="短片, 雨夜", tool="Seedance", source=str(shot),
                       finals=[shot / "雨夜-final.mp4", shot / "still.jpg"],
                       prompts=[shot / "提示词.txt"], records=[shot / "制作记录.md"],
                       versions=[self.project / "work/v1", self.project / "work/v2"])
        options.update(values)
        return add_work(self.workspace, **options)

    def test_a_finished_piece_becomes_a_work_spt_can_read(self):
        before = snapshot(self.project)
        result = self.add()
        work = self.workspace / "电影/2026-10-20-自家-雨夜重逢"
        self.assertTrue(result["created"])
        for name in ("成片_雨夜-final.mp4", "still.jpg", "封面.jpg", "提示词.txt", "记录.md",
                     "V1/正文.txt", "V1/01_人物.jpg", "V2/正文.txt", "说明.md"):
            self.assertTrue((work / name).is_file(), name)
        self.assertFalse((work / "V1/.DS_Store").exists())
        self.assertFalse((work / "V1/cookies.txt").exists())   # never copies login files
        self.assertIn("来源: ", (work / "说明.md").read_text(encoding="utf-8"))
        self.assertEqual(before, snapshot(self.project))       # source untouched
        indexer = Indexer(Config(self.workspace, self.cache, self.ui, 0, ()))
        indexer.reindex()
        [found] = indexer.store.list_works()
        self.assertEqual(found["title"], "雨夜重逢")
        self.assertEqual(found["tool"], "Seedance")
        self.assertIsNotNone(found["cover"])

    def test_running_again_adds_nothing_and_never_overwrites(self):
        self.add()
        again = self.add(versions=[])
        self.assertEqual(again["copied"], [])
        self.assertIn("记录.md", again["skipped"])
        record = self.workspace / "电影/2026-10-20-自家-雨夜重逢/记录.md"
        record.write_text("用户 改过的记录", encoding="utf-8")
        third = self.add(versions=[])
        self.assertEqual(record.read_text(encoding="utf-8"), "用户 改过的记录")
        self.assertEqual(third["conflicts"], [{"kept": "记录.md", "new": "记录-收录2.md"}])
        # new versions go after the existing ones
        later = self.add(finals=[], prompts=[], records=[], versions=[self.project / "work/v2"])
        self.assertTrue(any(path.startswith("V3/") for path in later["copied"]))

    def test_dry_run_writes_nothing(self):
        result = self.add(dry_run=True)
        self.assertIn("V1/正文.txt", result["copied"])
        self.assertEqual(list(self.workspace.iterdir()), [])

    def test_names_follow_the_library_rules(self):
        for values in ({"field": "素材"}, {"field": "../外面"}, {"client": "A-K"},
                       {"date": "2026-13-01"}, {"topic": ""}, {"finals": [Path("/nope.mp4")]}):
            with self.subTest(values=values), self.assertRaises(IntakeError):
                self.add(**values)
        self.assertEqual(list(self.workspace.iterdir()), [])


if __name__ == "__main__":
    unittest.main()


class SecretPathTests(unittest.TestCase):
    def test_a_folder_named_账号_is_a_container_not_an_account_file(self) -> None:
        self.assertFalse(secret(Path("02-运营/账号/育儿/图/1.png")))
        self.assertFalse(secret(Path("02-运营/账号")))
        self.assertTrue(secret(Path("02-运营/账号/育儿/账号信息.md")))
        self.assertTrue(secret(Path("02-运营/账号/AK/cookie.txt")))
        self.assertTrue(secret(Path("a/账号备份/x.png")))
