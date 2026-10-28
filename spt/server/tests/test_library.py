"""Library sections, work-level notes, export, agent surfaces."""
from __future__ import annotations
import csv
import datetime as dt
import http.client
import io
import json
import sqlite3
from contextlib import closing
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import quote

from ..api import Server
from ..config import Config
from ..exporter import export
from ..indexer import Indexer
from ..library import split_frontmatter
from ..mcp_server import respond
from .support import fixture_config, populate, snapshot, write

TABLE = """# 衣服库

| 编号 | 大类 | 即梦写法 | 色系 | 来源 |
|---|---|---|---|---|
| Y001 | 冬日·叙事 | 奶白色毛线帽，燕麦色大衣 | 奶白+燕麦 | 电影节 |
| Y002 | 夜店 | 黑色皮夹克 | 黑 ｜不采用 2026-10-01 | 电影节 |
"""
PROMPT = """---
标题: 色面棚拍
标签: [菜品, 棚拍]
工具: 即梦
---
# 色面棚拍
为餐厅做一张无字底图。
"""


def library(root: Path, skills: Path) -> None:
    write(root / "素材/衣服.md", TABLE)
    write(root / "素材/角色.md", "# 角色\n常驻角色档案。")
    write(root / "素材/角色/Kaia/脸.png", b"png")
    write(root / "素材/角色/Kaia/脸.md", "---\n说明: 主参考脸\n---\n")
    write(root / "素材/README.md", "# 不收录")
    write(root / "提示词/菜品/色面棚拍.md", PROMPT)
    write(root / "提示词/菜品/色面棚拍.jpg", b"jpg")
    write(root / "记录/2026-10-21-复盘.md", "# 复盘\n今天的结论。")
    write(root / "skills/spt-library/SKILL.md",
          "---\nname: spt-library\ndescription: 资产库\n---\n正文")
    write(skills / "codex-one/SKILL.md",
          "---\nname: codex-one\ndescription: 已安装\n---\n")
    (skills / "linked").symlink_to(root / "skills/spt-library")
    work = root / "运营/2026-10-20-AK-环绕"
    write(work / "说明.md", "---\n标题: 定格环绕\n标签: 餐厅\n工具: 即梦\n---\n补充")
    write(work / "记录.md", "# 记录\n## 当前采用：V9\n- Instagram: https://x.test/a\n")
    write(work / "提示词-1.md", "第一张图的提示词")


class LibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        base = fixture_config(cls.root)
        populate(base.workspace)
        skills = cls.root / "installed"
        library(base.workspace, skills)
        cls.config = Config(base.workspace, base.cache, base.ui, 0,
                            (("Codex", skills),))
        cls.before = snapshot(base.workspace)
        cls.indexer = Indexer(cls.config)
        cls.result = cls.indexer.reindex()
        cls.store = cls.indexer.store
        cls.server = Server(cls.indexer)
        cls.thread = threading.Thread(target=cls.server.serve_forever,
                                      daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)
        cls.temporary.cleanup()

    def request(self, path: str) -> tuple[int, dict[str, str], bytes]:
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.server.server_port, timeout=3)
        connection.request("GET", path)
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def items(self, kind: str, **filters: str) -> list[dict]:
        return self.store.list_items(kind, **filters)

    def test_indexing_never_writes_into_the_workspace(self) -> None:
        self.assertEqual(snapshot(self.config.workspace), self.before)
        self.assertEqual(self.result["issues"], [])

    def test_reserved_sections_are_not_works(self) -> None:
        categories = {work["category"] for work in self.store.list_works()}
        self.assertEqual(categories, {"运营"})

    def test_material_table_rows_become_copyable_items(self) -> None:
        rows = {item["code"]: item for item in self.items("material",
                                                          section="衣服")}
        self.assertEqual(rows["Y001"]["title"], "冬日·叙事")
        self.assertEqual(rows["Y001"]["text"], "奶白色毛线帽，燕麦色大衣")
        self.assertEqual(rows["Y001"]["tags"], "奶白+燕麦")
        self.assertEqual(rows["Y001"]["note"], "电影节")
        self.assertEqual(rows["Y002"]["status"], "不采用")

    def test_media_and_documents_share_a_section(self) -> None:
        group = {item["title"]: item for item in self.items(
            "material", section="角色")}
        self.assertEqual(set(group), {"角色", "脸"})
        self.assertEqual(group["脸"]["file"], "素材/角色/Kaia/脸.png")
        self.assertEqual(group["脸"]["note"], "主参考脸")
        self.assertEqual(group["脸"]["tags"], "Kaia")
        self.assertFalse(any("README" in item["path"]
                             for item in self.items("material")))

    def test_prompt_frontmatter_preview_and_heading(self) -> None:
        prompt = self.items("prompt", section="菜品")[0]
        self.assertEqual(prompt["title"], "色面棚拍")
        self.assertEqual(prompt["tags"], "菜品, 棚拍")
        self.assertEqual(prompt["tool"], "即梦")
        self.assertEqual(prompt["text"], "为餐厅做一张无字底图。")
        self.assertEqual(prompt["file"], "提示词/菜品/色面棚拍.jpg")

    def test_work_prompts_records_and_note(self) -> None:
        work = next(work for work in self.store.list_works()
                    if work["relative_path"].endswith("环绕"))
        self.assertEqual((work["title"], work["tags"], work["tool"]),
                         ("定格环绕", "餐厅", "即梦"))
        derived = [item for item in self.items("prompt")
                   if item["work_id"] == work["id"]]
        self.assertEqual({item["title"] for item in derived},
                         {"定格环绕 · V1", "定格环绕 · 提示词-1"})
        version = next(item for item in derived if "V1" in item["title"])
        self.assertTrue(version["file"].endswith("V1/01_菜品.jpg"))
        records = [item for item in self.items("record")
                   if item["work_id"] == work["id"]]
        self.assertEqual(len(records), 1)

    def test_work_record_does_not_change_publication_state(self) -> None:
        work = next(work for work in self.store.list_works()
                    if work["relative_path"].endswith("环绕"))
        self.assertIsNone(work["current_version"])
        self.assertEqual(work["platforms"], [])

    def test_skills_from_library_and_installed_roots_are_deduplicated(self):
        skills = self.items("skill")
        self.assertEqual(sorted(item["title"] for item in skills),
                         ["codex-one", "spt-library"])
        sections = {item["title"]: item["section"] for item in skills}
        self.assertEqual(sections["spt-library"], "库内")
        self.assertEqual(sections["codex-one"], "Codex 已安装")

    def test_search_covers_text_tags_and_codes(self) -> None:
        self.assertEqual(len(self.store.list_items(query="燕麦")), 1)
        self.assertEqual(len(self.store.list_items(query="y002")), 1)
        self.assertEqual(len(self.store.list_items("prompt", query="棚拍")), 1)

    def test_csv_export_has_bom_and_every_kind(self) -> None:
        data, mime, name = export(self.store, "csv")
        self.assertTrue(data.startswith("﻿".encode()))
        self.assertTrue(name.endswith(".csv") and mime.startswith("text/csv"))
        rows = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
        self.assertEqual({row["类型"] for row in rows},
                         {"作品", "提示词", "素材", "记录", "Skills"})
        material = next(row for row in rows if row["编号"] == "Y001")
        self.assertEqual(material["提示词/正文"], "奶白色毛线帽，燕麦色大衣")

    def test_xlsx_export_has_sheet_per_kind(self) -> None:
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl 未安装")
        data, _, _ = export(self.store, "xlsx", "material")
        book = openpyxl.load_workbook(io.BytesIO(data))
        self.assertEqual(book.sheetnames, ["全部", "素材"])
        self.assertEqual(book["素材"].freeze_panes, "A2")

    def test_markdown_export_escapes_cells(self) -> None:
        data, _, _ = export(self.store, "md", "material")
        text = data.decode()
        self.assertIn("## 素材", text)
        self.assertNotIn("\n| Y001 | 冬日·叙事 | 奶白色毛线帽，燕麦色大衣 |\n|", text)

    def test_unknown_export_is_rejected(self) -> None:
        status, _, _ = self.request("/api/export?format=exe")
        self.assertEqual(status, 400)
        status, _, _ = self.request("/api/export?format=csv&kind=secret")
        self.assertEqual(status, 400)

    def test_http_library_items_and_files(self) -> None:
        status, _, body = self.request("/api/library")
        self.assertEqual(status, 200)
        summary = json.loads(body)
        self.assertEqual(summary["kinds"]["material"]["count"], 4)
        section = quote("角色")
        _, _, body = self.request(f"/api/items?kind=material&section={section}")
        face = next(item for item in json.loads(body)["items"]
                    if item["file"])
        self.assertNotIn("body", face)
        status, headers, content = self.request(face["file_url"])
        self.assertEqual((status, content), (200, b"png"))
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        status, _, body = self.request(f"/api/items/{face['id']}")
        self.assertEqual(json.loads(body)["item"]["note"], "主参考脸")

    def test_items_without_files_and_unknown_ids(self) -> None:
        record = self.items("record")[0]
        status, _, _ = self.request(f"/api/items/{record['id']}/file")
        self.assertEqual(status, 404)
        status, _, _ = self.request("/api/items/" + "0" * 20)
        self.assertEqual(status, 404)
        status, _, _ = self.request("/api/items/../../etc/passwd")
        self.assertEqual(status, 404)

    def test_http_export_is_an_attachment(self) -> None:
        status, headers, body = self.request("/api/export?format=csv")
        self.assertEqual(status, 200)
        self.assertIn("attachment;", headers["Content-Disposition"])
        self.assertIn("filename*=UTF-8''SPT-", headers["Content-Disposition"])
        self.assertTrue(body.startswith("﻿".encode()))

    def test_export_file_names_carry_the_kind_and_the_day(self) -> None:
        day = dt.date(2026, 10, 22)
        self.assertEqual(export(self.store, "csv", day=day)[2], "SPT-资产-2026-10-22.csv")
        self.assertEqual(export(self.store, "md", "prompt", day)[2], "SPT-提示词-2026-10-22.md")
        self.assertEqual(export(self.store, "csv", "skill", day)[2], "SPT-Skills-2026-10-22.csv")

    def test_http_export_name_uses_rfc_5987(self) -> None:
        for query, label, suffix in (("format=csv", "资产", "csv"),
                                     ("format=md&kind=prompt", "提示词", "md")):
            with self.subTest(query=query):
                days = {dt.date.today().isoformat()}
                status, headers, _ = self.request("/api/export?" + query)
                days.add(dt.date.today().isoformat())   # in case midnight passed meanwhile
                self.assertEqual(status, 200)
                self.assertIn(headers["Content-Disposition"], {
                    f"attachment; filename=\"SPT-export-{day}.{suffix}\"; filename*=UTF-8''"
                    + quote(f"SPT-{label}-{day}.{suffix}", safe="") for day in days})

    def test_guide_falls_back_to_the_bundled_storage_guide(self) -> None:
        status, _, body = self.request("/api/guide")
        guide = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(guide["path"], "spt/templates/工作区-README.md")
        self.assertIn("# 存放说明", guide["markdown"])

    def test_mcp_lists_tools_and_answers_unknown_methods(self) -> None:
        tools = respond({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        names = {tool["name"] for tool in tools["result"]["tools"]}
        self.assertIn("spt_search", names)
        self.assertNotIn("spt_write", names)
        missing = respond({"jsonrpc": "2.0", "id": 2, "method": "nope"})
        self.assertEqual(missing["error"]["code"], -32601)
        self.assertIsNone(respond({"jsonrpc": "2.0",
                                   "method": "notifications/initialized"}))

    def test_frontmatter_errors_fall_back_to_plain_text(self) -> None:
        values, body = split_frontmatter("---\n: [broken\n---\n正文")
        self.assertEqual(values, {})
        self.assertTrue(body.startswith("---"))


class SearchTests(unittest.TestCase):
    """Several words: every one must appear (any order, any field, case ignored)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        config = fixture_config(Path(cls.temporary.name))
        root = config.workspace
        populate(root)
        write(root / "提示词/场景/夜景篝火.md", "---\n标题: 夜景篝火\n---\n夜景里，篝火的火光映在脸上")
        write(root / "提示词/场景/夜景城市.md", "---\n标题: 夜景城市\n---\n城市夜景，霓虹灯")
        write(root / "素材/场景.md", "| 编号 | 名称 | 写法 |\n|---|---|---|\n"
                                     "| S01 | 雪夜 | 雪地里点着火光 |\n| S02 | 夜景 | 海边夜景 |\n")
        write(root / "运营/2026-10-21-自家-夜景/V1/正文.txt", "城市夜景，远处有火光")
        write(root / "提示词/场景/只在文件名里.md", "---\n标题: 晨雾\n---\n清晨的薄雾")
        cls.indexer = Indexer(config)
        cls.indexer.reindex()
        cls.store = cls.indexer.store

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def items(self, query: str, kind: str = "") -> list[str]:
        return sorted(item["title"] for item in self.store.list_items(kind, query=query))

    def works(self, query: str) -> list[str]:
        return sorted(work["title"] for work in self.store.list_works(query=query))

    def test_items_need_every_word(self) -> None:
        both = ["夜景 · V1", "夜景篝火"]
        self.assertEqual(self.items("夜景 火光"), both)
        self.assertEqual(self.items("火光 夜景"), both)
        self.assertEqual(self.items("夜景　火光"), both)          # full-width space
        self.assertEqual(self.items("  夜景 \t 霓虹  "), ["夜景城市"])
        self.assertEqual(self.items("s02 海边"), ["夜景"])            # code, case ignored
        self.assertEqual(self.items("夜景 不存在"), [])
        self.assertEqual(self.items("夜景火光"), [])                  # one word stays one word
        self.assertEqual(self.items("夜景 火光", "material"), [])
        self.assertEqual(len(self.store.list_items(query=" 　 ")), len(self.store.list_items()))

    def test_works_need_every_word(self) -> None:
        self.assertEqual(self.works("火光"), ["夜景", "火光"])
        self.assertEqual(self.works("夜景 火光"), ["夜景"])           # title + prompt
        self.assertEqual(self.works("ak 火光"), ["火光"])             # client, case ignored
        self.assertEqual(self.works("火光　v3提示词"), ["火光"])
        self.assertEqual(self.works("夜景 炒饭"), [])
        self.assertEqual(len(self.store.list_works(query="  ")), 5)

    def test_path_is_not_searched(self) -> None:
        # A word only in the file or folder name is no match (提示词/ would match every prompt).
        self.assertEqual(self.items("晨雾"), ["晨雾"])
        self.assertEqual(self.items("只在文件名里"), [])
        self.assertEqual(self.items("md"), [])

    def test_agents_search_the_same_way(self) -> None:
        from ..agent import search
        found = {(entry["kind"], entry["title"]) for entry in search(self.indexer, "夜景 火光")}
        self.assertEqual(found, {("work", "夜景"), ("prompt", "夜景 · V1"), ("prompt", "夜景篝火")})


class SourceTests(unittest.TestCase):
    def test_external_sources_are_read_in_place_and_accounts_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = fixture_config(root)
            outside = root / "lemonade"
            write(outside / "01-专业/CAD/SKILL.md",
                  "---\nname: CAD\ndescription: 画图\n---\n")
            write(outside / "01-专业/CAD/prompts/报价.md", "# 报价\n先问尺寸")
            write(outside / "02-运营/prompts/选题.md", "一周选题")
            write(outside / "02-运营/账号/密码.md", "secret")
            write(outside / "02-运营/prompts/账号/备份.md", "secret")
            write(config.workspace / "SPT.yaml", (
                "skills:\n  - 名称: 专业库\n"
                f"    路径: {outside / '01-专业'}\n    提示词: true\n"
                "prompts:\n  - 名称: 运营\n"
                f"    路径: {outside / '02-运营/prompts'}\n"
                "records:\n  - 名称: 账号\n"
                f"    路径: {outside / '02-运营/账号'}\n"))
            before = snapshot(outside)
            indexer = Indexer(config)
            result = indexer.reindex()
            items = indexer.store.list_items()
            self.assertEqual(snapshot(outside), before)
            titles = {(item["kind"], item["title"]) for item in items}
            self.assertIn(("skill", "CAD"), titles)
            self.assertIn(("prompt", "报价"), titles)
            self.assertIn(("prompt", "选题"), titles)
            self.assertFalse(any("secret" in (item["text"] or "")
                                 for item in items))
            self.assertTrue(any("跳过" in issue for issue in result["issues"]))
            quote_prompt = next(item for item in items if item["title"] == "报价")
            self.assertEqual(quote_prompt["section"], "CAD")
            self.assertEqual(quote_prompt["text"], "先问尺寸")
            self.assertIsNone(quote_prompt["file"])


class MigrationTests(unittest.TestCase):
    def test_old_cache_schema_is_rebuilt(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            config = fixture_config(Path(folder))
            populate(config.workspace)
            config.cache.mkdir(parents=True)
            with closing(sqlite3.connect(config.database)) as connection, connection:
                connection.execute("CREATE TABLE works (id TEXT PRIMARY KEY, "
                                   "title TEXT)")
            indexer = Indexer(config)
            indexer.reindex()
            self.assertEqual(len(indexer.store.list_works()), 4)
            with closing(sqlite3.connect(config.database)) as connection, connection:
                version = connection.execute("PRAGMA user_version").fetchone()
                columns = {row[1] for row in connection.execute(
                    "PRAGMA table_info(works)")}
            self.assertEqual(version[0], 4)
            self.assertIn("note", columns)
            self.assertIn("cover_rule", columns)
            with closing(sqlite3.connect(config.database)) as connection, connection:
                tables = {row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("metric_observations", tables)
            self.assertIn("account_observations", tables)


if __name__ == "__main__":
    unittest.main()


class ShareTests(unittest.TestCase):
    def test_share_package_carries_an_empty_workspace_only(self):
        from spt.server import share
        flag = share.ROOT / "spt/settings.share.json"
        original_flag = flag.read_bytes() if flag.exists() else None
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "SPT"
            target.mkdir()
            share.stage(target)
            files = sorted(path.relative_to(target / "工作区").as_posix()
                           for path in (target / "工作区").rglob("*"))
            self.assertEqual(files, ["AGENTS.md", "README.md", "skills",
                                     "便签", "提示词", "素材", "记录"])
            self.assertFalse((target / "spt/settings.local.json").exists())
            # the copy is marked as shared; the owner's own folder never is
            self.assertEqual(json.loads((target / "spt/settings.share.json")
                                        .read_text(encoding="utf-8")), {"share": False})
            self.assertEqual(flag.read_bytes() if flag.exists() else None, original_flag)
            self.assertFalse((target / "data").exists())
            self.assertEqual((target / "app/projects.json").read_text(), "[]\n")
            self.assertFalse(list(target.rglob("*.sqlite3")))
            self.assertFalse(list(target.rglob("__pycache__")))
            self.assertFalse((target / "spt/server/.cache").exists())
            self.assertFalse((target / "spt/docs/一键迁移提示词.md").exists())


class ShareFlagTests(unittest.TestCase):
    def test_health_reports_share_mode_only_when_the_flag_file_exists(self):
        from unittest import mock
        from spt.server import config as settings
        with tempfile.TemporaryDirectory() as folder:
            base = fixture_config(Path(folder))
            populate(base.workspace)
            indexer = Indexer(Config(base.workspace, base.cache, base.ui, 0, ()))
            indexer.reindex()
            flag = Path(folder) / "settings.share.json"
            with mock.patch.object(settings, "SHARE_SETTINGS", flag):
                self.assertIs(indexer.health()["share"], False)      # no file: the owner's copy
                write(flag, '{"share": true}\n')
                self.assertIs(indexer.health()["share"], True)
                for content in ('{"share": "yes"}', "[1]", "{broken"):
                    write(flag, content)
                    self.assertIs(indexer.health()["share"], False)


class WatcherTests(unittest.TestCase):
    def test_watcher_reindexes_after_the_workspace_settles(self):
        from spt.server.watcher import Watcher
        with tempfile.TemporaryDirectory() as folder:
            base = fixture_config(Path(folder))
            populate(base.workspace)
            indexer = Indexer(Config(base.workspace, base.cache, base.ui, 0, ()))
            indexer.reindex()
            watcher = Watcher(indexer)
            self.assertFalse(watcher.check())            # first look only records
            self.assertFalse(watcher.check())            # nothing changed
            write(base.workspace / "记录" / "2026-10-21-新记录.md", "# 新记录\n学到的东西")
            self.assertFalse(watcher.check())            # seen once: wait for it to settle
            self.assertTrue(watcher.check())             # unchanged since: reindex
            titles = {item["title"] for item in indexer.store.list_items("record")}
            self.assertIn("新记录", titles)
            self.assertFalse(watcher.check())


class NotesTests(unittest.TestCase):
    def test_notes_hang_on_ropes_and_are_never_deleted(self):
        from spt.server.notes import Notes
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder) / "工作区"
            workspace.mkdir()
            notes = Notes(workspace)
            self.assertEqual(notes.snapshot()["ropes"], [])
            first = notes.save({"text": "AK 下周三拍菜单", "color": "mint"})
            self.assertEqual(first["rope"], "随手记")
            second = notes.save({"text": "第二张", "rope": "随手记"})
            notes.rope({"action": "create", "name": "灵感"})
            ropes = notes.snapshot()["ropes"]
            self.assertEqual([rope["name"] for rope in ropes], ["随手记", "灵感"])
            self.assertEqual([note["text"] for note in ropes[0]["notes"]], ["AK 下周三拍菜单", "第二张"])
            self.assertEqual(ropes[0]["notes"][0]["color"], "mint")
            notes.move({"id": second["id"], "rope": "随手记", "to": "随手记", "index": 0})
            self.assertEqual(notes.snapshot()["ropes"][0]["notes"][0]["id"], second["id"])
            notes.move({"id": first["id"], "rope": "随手记", "to": "灵感", "index": 0})
            self.assertTrue((workspace / "便签/灵感" / f"{first['id']}.md").is_file())
            notes.save({"id": first["id"], "rope": "灵感", "text": "改过了", "color": "pink"})
            self.assertEqual(notes.snapshot()["ropes"][1]["notes"][0]["text"], "改过了")
            with self.assertRaises(ValueError):
                notes.rope({"action": "remove", "name": "灵感"})
            notes.take_down({"id": first["id"], "rope": "灵感"})
            self.assertTrue((workspace / "便签/.已撤下/灵感" / f"{first['id']}.md").is_file())
            notes.rope({"action": "remove", "name": "灵感"})
            self.assertEqual([rope["name"] for rope in notes.snapshot()["ropes"]], ["随手记"])
            self.assertTrue(list((workspace / "便签/.已撤下").glob("灵感-*")))

    def test_notes_keep_an_optional_date_for_the_calendar(self):
        from spt.server.notes import Notes
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder) / "工作区"
            workspace.mkdir()
            notes = Notes(workspace)
            saved = notes.save({"text": "拍菜单", "date": "2026-10-28"})
            path = workspace / "便签/随手记" / f"{saved['id']}.md"
            self.assertIn("日期: 2026-10-28", path.read_text(encoding="utf-8"))
            note = notes.snapshot()["ropes"][0]["notes"][0]
            self.assertEqual(note["date"], "2026-10-28")
            self.assertEqual(note["created"], f"{saved['id'][:4]}-{saved['id'][4:6]}-{saved['id'][6:8]}")
            # an edit that does not send the date keeps it; an empty date clears it
            notes.save({"id": saved["id"], "rope": "随手记", "text": "拍菜单，带三脚架"})
            self.assertEqual(notes.snapshot()["ropes"][0]["notes"][0]["date"], "2026-10-28")
            notes.save({"id": saved["id"], "rope": "随手记", "text": "拍菜单", "date": ""})
            self.assertEqual(notes.snapshot()["ropes"][0]["notes"][0]["date"], "")
            self.assertNotIn("日期", path.read_text(encoding="utf-8"))
            for bad in ("2026-13-01", "10/28", "2026-1-5"):
                with self.assertRaises(ValueError):
                    notes.save({"text": "x", "date": bad})

    def test_names_and_ids_cannot_escape_the_folder(self):
        from spt.server.notes import Notes
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder) / "工作区"
            workspace.mkdir()
            notes = Notes(workspace)
            for rope in ("../外面", ".hidden", "a/b", ""):
                with self.assertRaises(ValueError):
                    notes.rope({"action": "create", "name": rope})
            with self.assertRaises(ValueError):
                notes.save({"id": "../../x", "rope": "随手记", "text": "x"})
            with self.assertRaises(ValueError):
                notes.save({"text": "   "})

    def test_notes_are_searchable_and_not_works(self):
        with tempfile.TemporaryDirectory() as folder:
            config = fixture_config(Path(folder))
            populate(config.workspace)
            from spt.server.notes import Notes
            Notes(config.workspace).save({"text": "记得给 AK 回消息\n周五前"})
            indexer = Indexer(config)
            indexer.reindex()
            self.assertEqual(len(indexer.store.list_works()), 4)
            notes = indexer.store.list_items("note")
            self.assertEqual([note["title"] for note in notes], ["记得给 AK 回消息"])
            self.assertEqual(notes[0]["section"], "随手记")


class SkillFilterTests(unittest.TestCase):
    def test_claude_built_in_skills_are_left_out(self):
        import json
        from spt.server.library import skill_items
        with tempfile.TemporaryDirectory() as folder:
            claude = Path(folder) / "claude"
            write(claude / "mine" / "SKILL.md", "---\nname: mine\n---\n我的")
            bucket = claude / "synced" / "bucket"
            write(bucket / "pdf" / "SKILL.md", "---\nname: pdf\n---\nx")
            write(bucket / "uploaded" / "SKILL.md", "---\nname: uploaded\n---\nx")
            write(bucket / "manifest.json", json.dumps({"skills": [
                {"skillId": "pdf", "source": "anthropic"},
                {"skillId": "uploaded", "source": "user"}]}))
            codex = Path(folder) / "codex"
            write(codex / ".system" / "imagegen" / "SKILL.md", "---\nname: imagegen\n---\nx")
            write(codex / "ads" / "SKILL.md", "---\nname: ads\n---\nx")
            workspace = Path(folder) / "工作区"
            workspace.mkdir()
            names = sorted(item.title for item in skill_items(
                workspace, (("Claude", claude), ("Codex", codex)), []))
            self.assertEqual(names, ["ads", "mine", "uploaded"])


class WorkspaceSettingTests(unittest.TestCase):
    def test_custom_workspace_is_checked_saved_and_switched(self):
        from unittest import mock
        from spt.server import config as settings
        with tempfile.TemporaryDirectory(prefix="spt-workspace-test-", dir=Path.cwd()) as folder:
            base = fixture_config(Path(folder))
            populate(base.workspace)
            other = Path(folder) / "另一个工作区"
            write(other / "记录" / "2026-10-21-换了.md", "# 换了\n新的位置")
            stored = Path(folder) / "settings.local.json"
            with mock.patch.object(settings, "SETTINGS", stored):
                for bad in ("相对路径", str(Path(folder) / "不存在"), str(Path.home())):
                    with self.assertRaises(ValueError):
                        settings.save_workspace(bad)
                self.assertEqual(settings.save_workspace(str(other)), other)
                self.assertEqual(settings.custom_workspace(), other)
                indexer = Indexer(Config(base.workspace, base.cache, base.ui, 0, ()))
                indexer.reindex()
                self.assertEqual(len(indexer.store.list_works()), 4)
                indexer.set_workspace(other)
                self.assertEqual(indexer.store.list_works(), [])
                self.assertIn("换了", {item["title"] for item in indexer.store.list_items("record")})
                self.assertEqual(settings.save_workspace(""), settings.DEFAULT_WORKSPACE)
                self.assertIsNone(settings.custom_workspace())
