"""工作区/客户.md → health clients; items carry the client of the work they came from."""
from __future__ import annotations
import contextlib
import csv
import http.client
import io
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

from .. import agent, cli
from ..api import Server
from ..clients import (PREAMBLE, Clients, client_groups, client_summary, parse_clients,
                       save_clients)
from ..exporter import export
from ..files import FileError
from ..indexer import Indexer
from ..mcp_server import TOOLS, call
from .support import fixture_config, populate, snapshot, write

TABLE = ("# 客户\n\n"
         "| 简称 | 名字 | 类型 | 颜色 |\n"
         "|---|---|---|---|\n"
         "| 自家 | 自家 | 自己 | |\n"
         "| 示例创作者 | 示例创作者 | 自己 | #d6a4ff |\n"
         "| AK | Sample Studio | 客户 | #f0b35c |\n")


class ParseTests(unittest.TestCase):
    def test_the_documented_table(self) -> None:
        rows, issues = parse_clients(TABLE)
        self.assertEqual(issues, [])
        self.assertEqual(rows, [
            {"code": "自家", "name": "自家", "kind": "own", "color": None, "group": "自己"},
            {"code": "示例创作者", "name": "示例创作者", "kind": "own", "color": "#d6a4ff", "group": "自己"},
            {"code": "AK", "name": "Sample Studio", "kind": "client", "color": "#f0b35c",
             "group": "客户"}])
        self.assertEqual(client_groups(rows), ["自己", "客户"])

    def test_columns_are_found_by_name_not_position(self) -> None:
        text = ("﻿  | 备注 | 颜色 | 类型 | 简称 |  \n"
                "  |:--|:--:|---|--:|\n"
                "  | 老客户 | #ABCDEF | 客户 | AK |\n"
                "| 无名字列 |  |  | 新客 \n")           # no trailing pipe, no 名字 column
        rows, issues = parse_clients(text)
        self.assertEqual(issues, [])
        self.assertEqual(rows, [
            {"code": "AK", "name": "AK", "kind": "client", "color": "#abcdef", "group": "客户"},
            {"code": "新客", "name": "新客", "kind": "client", "color": None, "group": "客户"}])

    def test_kind_defaults_and_colour_validation(self) -> None:
        text = ("| 简称 | 类型 | 颜色 |\n|---|---|---|\n"
                "| 自家 | 客户 | |\n"              # 自家 is own whatever the file says
                "| A | 朋友 | #12345 |\n"          # any group name; short colour dropped
                "| B | | red |\n"
                "| C | 自己 | #00FF00 |\n")
        rows, issues = parse_clients(text)
        self.assertEqual([(row["code"], row["kind"], row["color"]) for row in rows],
                         [("自家", "own", None), ("A", "client", None),
                          ("B", "client", None), ("C", "own", "#00ff00")])
        self.assertEqual([row["group"] for row in rows], ["客户", "朋友", "客户", "自己"])
        self.assertEqual(client_groups(rows), ["客户", "朋友", "自己"])
        self.assertEqual(len(issues), 2)
        self.assertTrue(all("颜色" in issue and "客户.md 第" in issue for issue in issues))

    def test_groups_are_free_text_and_unlisted_codes_join_a_group(self) -> None:
        self.assertEqual(client_groups([]), ["自己", "客户"])
        rows, _ = parse_clients("| 简称 | 类型 |\n|---|---|\n| 自家 | 自己 |\n| AK | 餐厅 |\n"
                                "| Lemon | 客户 |\n| Pear | 餐厅 |\n")
        self.assertEqual(client_groups(rows), ["自己", "餐厅", "客户"])
        summary = client_summary(rows, {"Apple": 1})
        self.assertEqual(summary[-1]["group"], "客户")          # 客户 exists: unlisted go there
        rows, _ = parse_clients("| 简称 | 类型 |\n|---|---|\n| AK | 餐厅 |\n| Pear | 品牌 |\n")
        summary = client_summary(rows, {"Apple": 1, "自家": 2})
        by_code = {entry["code"]: entry for entry in summary}
        self.assertEqual(by_code["Apple"]["group"], "品牌")      # no 客户 group: the last one
        self.assertEqual((by_code["自家"]["group"], by_code["自家"]["kind"]), ("餐厅", "own"))
        self.assertEqual([entry["code"] for entry in summary], ["AK", "Pear", "自家", "Apple"])

    def test_broken_rows_become_issues_and_the_rest_is_kept(self) -> None:
        text = ("| 简称 | 名字 |\n|---|---|\n"
                "| AK | Sample Studio |\n"
                "| | 没有简称 |\n"
                "| AK | 重复 |\n"
                "|---|---|\n"                       # a stray rule line is skipped quietly
                "| Lemon | 柠檬 |\n"
                "\n"
                "| 表格外 | 不算 |\n")
        rows, issues = parse_clients(text)
        self.assertEqual([row["code"] for row in rows], ["AK", "Lemon"])
        self.assertEqual(issues, ["客户.md 第 4 行看不懂",
                                  "客户.md 第 5 行：简称「AK」重复，已忽略"])

    def test_nothing_usable_never_raises(self) -> None:
        for text in ("", "   \n", "# 客户\n只有标题", "| 名字 | 类型 |\n|---|---|\n| x | y |\n",
                     "| 简称 |\n", "\x00\xff|||\n|-|\n"):
            with self.subTest(text=text):
                rows, issues = parse_clients(text)
                self.assertEqual(rows, [])
                self.assertEqual(len(issues), 0 if not text.strip() else 1)

    def test_summary_order_and_counts(self) -> None:
        rows, _ = parse_clients(TABLE)
        summary = client_summary(rows, {"AK": 59, "Lemon": 2, "自家": 4, "Apple": 1})
        self.assertEqual([(entry["code"], entry["works"], entry["kind"]) for entry in summary],
                         [("自家", 4, "own"), ("示例创作者", 0, "own"), ("AK", 59, "client"),
                          ("Apple", 1, "client"), ("Lemon", 2, "client")])
        unlisted = client_summary([], {"Lemon": 1, "自家": 2, "AK": 3})
        self.assertEqual([entry["code"] for entry in unlisted], ["自家", "AK", "Lemon"])
        self.assertEqual(unlisted[0], {"code": "自家", "name": "自家", "kind": "own",
                                       "color": None, "works": 2, "group": "自己"})
        self.assertEqual([entry["group"] for entry in unlisted], ["自己", "客户", "客户"])


GROUPS = [{"name": "自己", "clients": [{"code": "自家", "name": "自家", "color": ""},
                                     {"code": "示例创作者", "name": "示例创作者", "color": "#D6A4FF"}]},
          {"name": "餐厅", "clients": [{"code": "AK", "name": "Sample Studio", "color": "#f0b35c"}]},
          {"name": "客户", "clients": [{"code": "Lemon", "name": "", "color": None}]}]


class SaveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name) / "工作区"
        self.workspace.mkdir()
        self.path = self.workspace / "客户.md"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_round_trip_keeps_group_order_and_the_text_around_the_table(self) -> None:
        self.assertEqual(save_clients(self.workspace, GROUPS, {"AK": 4, "自家": 1}),
                         ["自己", "餐厅", "客户"])
        text = self.path.read_text(encoding="utf-8")
        self.assertTrue(text.startswith(PREAMBLE))              # no file before: the standard note
        rows, issues = parse_clients(text)
        self.assertEqual(issues, [])
        self.assertEqual([(row["code"], row["name"], row["group"], row["color"]) for row in rows],
                         [("自家", "自家", "自己", None), ("示例创作者", "示例创作者", "自己", "#d6a4ff"),
                          ("AK", "Sample Studio", "餐厅", "#f0b35c"), ("Lemon", "Lemon", "客户", None)])
        self.assertEqual(client_groups(rows), ["自己", "餐厅", "客户"])
        # a rearrangement rewrites the table only; 用户's own words stay where they were
        write(self.path, "# 我的客户\n\n开头的说明。\n\n" + TABLE + "\n表格下面的备注。\n")
        reordered = [GROUPS[2], GROUPS[1], {"name": "新组", "clients": []}, GROUPS[0]]
        save_clients(self.workspace, reordered, {})
        text = self.path.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# 我的客户\n\n开头的说明。\n\n# 客户\n\n| 简称 | 名字 | 类型 | 颜色 |\n"))
        self.assertTrue(text.endswith("| 示例创作者 | 示例创作者 | 自己 | #d6a4ff |\n\n表格下面的备注。\n"))
        rows, _ = parse_clients(text)
        self.assertEqual(client_groups(rows), ["客户", "餐厅", "自己"])   # an empty group leaves no row
        self.assertEqual([row["code"] for row in rows], ["Lemon", "AK", "自家", "示例创作者"])
        self.assertEqual([name for name in os.listdir(self.workspace) if name.startswith(".tmp")], [])

    def test_a_file_without_a_table_gets_one_after_its_text(self) -> None:
        write(self.path, "# 客户\n只有标题")
        save_clients(self.workspace, GROUPS[:1], {})
        text = self.path.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# 客户\n只有标题\n\n| 简称 |"))
        self.assertEqual([row["code"] for row in parse_clients(text)[0]], ["自家", "示例创作者"])

    def test_validation_messages(self) -> None:
        def group(name: str, *codes: str) -> dict:
            return {"name": name, "clients": [{"code": code} for code in codes]}
        cases = (([], {}, "至少要有一个分组"),
                 ([group(" ")], {}, "分组名不能为空"),
                 ([group("a|b")], {}, "分组名「a|b」不能有 | 或换行"),
                 ([group("甲"), group("甲")], {}, "分组「甲」重复了"),
                 ([group(str(index)) for index in range(13)], {}, "最多 12 个分组"),
                 ([group("甲", "")], {}, "简称不能为空"),
                 ([group("甲", "A/B")], {}, "简称「A/B」不能有 | / - 或换行"),
                 ([group("甲", "2026-AK")], {}, "简称「2026-AK」不能有 | / - 或换行"),
                 ([group("甲", "AK"), group("乙", "AK")], {}, "简称「AK」重复了"),
                 ([{"name": "甲", "clients": [{"code": "AK", "name": "A|K"}]}], {},
                  "名字「A|K」不能有 | 或换行"),
                 ([{"name": "甲", "clients": [{"code": "AK", "color": "red"}]}], {},
                  "「AK」的颜色要写成 #rrggbb"),
                 ([group("甲", *(f"C{index}" for index in range(201)))], {}, "最多 200 个客户"),
                 ([group("甲", "Lemon")], {"AK": 59, "Lemon": 1}, "「AK」还有 59 件作品，不能删"),
                 ([group("甲", "AK")], {"AK": 59, "自家": 2}, "「自家」还有 2 件作品，不能删"),
                 ("not a list", {}, "至少要有一个分组"),
                 ([group("甲"), "x"], {}, "分组格式不正确"))
        for groups, counts, message in cases:
            with self.subTest(message=message), self.assertRaises(ValueError) as caught:
                save_clients(self.workspace, groups, counts)
            self.assertEqual(str(caught.exception), message)
        self.assertFalse(self.path.exists())                   # nothing was written
        save_clients(self.workspace, [group("甲", "AK")], {"AK": 59, "Pear": 0})   # 0 works: free to drop

    def test_missing_workspace_and_links_are_refused(self) -> None:
        with self.assertRaises(FileError):
            save_clients(Path(self.temporary.name) / "没有", GROUPS, {})
        outside = Path(self.temporary.name) / "outside.md"
        write(outside, TABLE)
        self.path.symlink_to(outside)
        with self.assertRaises(FileError):
            save_clients(self.workspace, GROUPS, {})
        self.assertEqual(outside.read_text(encoding="utf-8"), TABLE)

    def test_clients_save_forgets_the_cache(self) -> None:
        clients = Clients()
        write(self.path, TABLE)
        self.assertEqual([row["code"] for row in clients.read(self.workspace)[0]], ["自家", "示例创作者", "AK"])
        clients.save(self.workspace, GROUPS, {})
        self.assertIsNone(clients.cached)
        self.assertEqual([row["code"] for row in clients.read(self.workspace)[0]],
                         ["自家", "示例创作者", "AK", "Lemon"])
        with self.assertRaises(ValueError):
            clients.save(self.workspace, [], {})
        self.assertIsNone(clients.cached)


def build(root: Path) -> None:
    populate(root)                                               # four AK works
    write(root / "运营/2026-10-21-自家-夜景/V1/正文.txt", "城市夜景")
    write(root / "运营/2026-10-21-自家-夜景/记录.md", "# 记录\n自家的记录")
    write(root / "电影/2026-10-19-Lemon-柠檬/提示词.md", "柠檬的提示词")
    write(root / "提示词/场景/晨雾.md", "---\n标题: 晨雾\n---\n清晨的薄雾")
    write(root / "记录/2026-10-21-复盘.md", "# 复盘\n今天的结论")


class HealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.config = fixture_config(Path(self.temporary.name))
        self.workspace = self.config.workspace
        build(self.workspace)
        self.indexer = Indexer(self.config)
        self.indexer.reindex()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def clients(self) -> list[tuple]:
        return [(entry["code"], entry["kind"], entry["works"])
                for entry in self.indexer.health()["clients"]]

    def test_without_the_file_only_codes_from_works_are_listed(self) -> None:
        self.assertEqual(self.clients(), [("自家", "own", 1), ("AK", "client", 4),
                                          ("Lemon", "client", 1)])
        health = self.indexer.health()
        self.assertEqual(health["issues"], [])
        self.assertEqual(health["client_groups"], ["自己", "客户"])
        self.assertEqual([entry["group"] for entry in health["clients"]], ["自己", "客户", "客户"])

    def test_file_rows_come_first_and_changes_show_without_reindex(self) -> None:
        write(self.workspace / "客户.md", TABLE)
        health = self.indexer.health()
        self.assertEqual([(entry["code"], entry["kind"], entry["works"]) for entry in health["clients"]],
                         [("自家", "own", 1), ("示例创作者", "own", 0), ("AK", "client", 4),
                          ("Lemon", "client", 1)])
        self.assertEqual(health["clients"][2]["name"], "Sample Studio")
        self.assertEqual(health["clients"][2]["color"], "#f0b35c")
        self.assertEqual(health["clients"][3], {"code": "Lemon", "name": "Lemon", "kind": "client",
                                                "color": None, "works": 1, "group": "客户"})
        self.assertEqual(health["client_groups"], ["自己", "客户"])
        write(self.workspace / "客户.md", TABLE + "| Lemon | 柠檬工作室 | 品牌 | #ffee00 |\n")
        health = self.indexer.health()
        self.assertEqual(health["clients"][3]["name"], "柠檬工作室")
        self.assertEqual(health["client_groups"], ["自己", "客户", "品牌"])
        (self.workspace / "客户.md").unlink()
        self.assertEqual(len(self.indexer.health()["clients"]), 3)

    def test_saving_through_the_indexer_shows_at_once(self) -> None:
        self.indexer.clients.save(self.workspace, GROUPS, self.indexer.store.client_counts())
        health = self.indexer.health()
        self.assertEqual(health["client_groups"], ["自己", "餐厅", "客户"])
        self.assertEqual([(entry["code"], entry["group"], entry["works"]) for entry in health["clients"]],
                         [("自家", "自己", 1), ("示例创作者", "自己", 0), ("AK", "餐厅", 4), ("Lemon", "客户", 1)])
        with self.assertRaises(ValueError) as caught:
            self.indexer.clients.save(self.workspace, GROUPS[:2], self.indexer.store.client_counts())
        self.assertEqual(str(caught.exception), "「Lemon」还有 1 件作品，不能删")
        self.assertEqual(self.indexer.health()["client_groups"], ["自己", "餐厅", "客户"])

    def test_a_broken_file_reports_once_and_keeps_the_good_rows(self) -> None:
        write(self.workspace / "客户.md", TABLE + "| | 空的 | | |\n")
        for _ in range(2):                                  # no duplicate after a rebuild
            self.indexer.reindex()
            health = self.indexer.health()
            self.assertEqual(health["issues"], ["客户.md 第 8 行看不懂"])
            self.assertEqual([entry["code"] for entry in health["clients"]][:3],
                             ["自家", "示例创作者", "AK"])
        self.assertIn("客户.md 第 8 行看不懂", self.indexer.reindex()["issues"])

    def test_the_root_file_is_not_an_item_or_a_profession(self) -> None:
        before = snapshot(self.workspace)
        plain = self.indexer.health()["counts"]
        write(self.workspace / "客户.md", TABLE)
        self.indexer.reindex()
        self.assertEqual(self.indexer.health()["counts"], plain)
        self.assertFalse(any(item["path"] == "客户.md" for item in self.indexer.store.list_items()))
        self.assertNotIn("客户", {work["category"] for work in self.indexer.store.list_works()})
        self.assertNotIn("客户", {item["section"] for item in self.indexer.store.list_items()})
        self.assertEqual({key: value for key, value in snapshot(self.workspace).items()
                          if key != "客户.md"}, before)


class ItemClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.config = fixture_config(Path(cls.temporary.name))
        build(cls.config.workspace)
        write(cls.config.workspace / "客户.md", TABLE)
        cls.indexer = Indexer(cls.config)
        cls.indexer.reindex()
        cls.store = cls.indexer.store
        cls.server = Server(cls.indexer)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)
        cls.temporary.cleanup()

    def get(self, path: str) -> dict:
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        connection.request("GET", path)
        response = connection.getresponse()
        status, body = response.status, response.read()
        connection.close()
        self.assertEqual(status, 200, path)
        return json.loads(body)

    def test_items_from_works_carry_the_client_and_others_null(self) -> None:
        by_title = {item["title"]: item for item in self.store.list_items()}
        self.assertEqual(by_title["夜景 · V1"]["client"], "自家")
        self.assertEqual(by_title["夜景 · 记录"]["client"], "自家")
        self.assertEqual(by_title["柠檬 · 提示词"]["client"], "Lemon")
        self.assertEqual(by_title["环绕 · V1"]["client"], "AK")
        self.assertIsNone(by_title["晨雾"]["client"])
        self.assertIsNone(by_title["复盘"]["client"])
        self.assertIsNone(self.store.get_item(by_title["晨雾"]["id"])["client"])
        self.assertEqual(self.store.get_item(by_title["夜景 · V1"]["id"])["client"], "自家")

    def test_filtering_by_client_in_store_http_and_agents(self) -> None:
        self.assertEqual({item["title"] for item in self.store.list_items(client="自家")},
                         {"夜景 · V1", "夜景 · 记录"})
        self.assertEqual({item["title"] for item in self.store.list_items("prompt", client="Lemon")},
                         {"柠檬 · 提示词"})
        self.assertEqual(self.store.list_items(client="Nobody"), [])
        self.assertEqual([work["title"] for work in self.store.list_works(client="Lemon")], ["柠檬"])
        items = self.get("/api/items?client=" + quote("自家"))["items"]
        self.assertEqual({item["title"] for item in items}, {"夜景 · V1", "夜景 · 记录"})
        self.assertTrue(all(item["client"] == "自家" for item in items))
        self.assertIsNone(self.get("/api/items?kind=record&section=" + quote("未分类"))["items"][0]["client"])
        self.assertEqual([work["title"] for work in self.get("/api/works?client=Lemon")["works"]], ["柠檬"])
        self.assertEqual(len(self.get("/api/works")["works"]), 6)
        health = self.get("/api/health")
        self.assertEqual([(entry["code"], entry["works"]) for entry in health["clients"]],
                         [("自家", 1), ("示例创作者", 0), ("AK", 4), ("Lemon", 1)])
        found = agent.search(self.indexer, client="自家")
        self.assertEqual({(entry["kind"], entry["title"]) for entry in found},
                         {("work", "夜景"), ("prompt", "夜景 · V1"), ("record", "夜景 · 记录")})
        self.assertEqual(next(entry for entry in found if entry["kind"] == "prompt")["client"], "自家")
        self.assertNotIn("client", agent.brief_item(self.store.list_items("prompt", section="场景")[0]))
        with patch.object(agent, "open_indexer", return_value=self.indexer):
            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                self.assertEqual(cli.main(["search", "--client", "Lemon"]), 0)
            self.assertEqual({entry["title"] for entry in json.loads(printed.getvalue())},
                             {"柠檬", "柠檬 · 提示词"})
            self.assertEqual({entry["title"] for entry in call("spt_search", {"client": "AK", "kind": "prompt"})},
                             {"环绕 · V1", "火光 · V3", "炒饭 · V3"})
        search = next(tool for tool in TOOLS if tool["name"] == "spt_search")
        self.assertEqual(search["inputSchema"]["properties"]["client"], {"type": "string"})

    def test_export_fills_the_client_column_once(self) -> None:
        data, _, _ = export(self.store, "csv")
        rows = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
        self.assertEqual(rows[0].keys().__len__(), len(set(rows[0].keys())))
        by_title = {row["标题"]: row for row in rows}
        self.assertEqual(by_title["夜景 · V1"]["客户"], "自家")
        self.assertEqual(by_title["夜景"]["客户"], "自家")
        self.assertEqual(by_title["晨雾"]["客户"], "")


if __name__ == "__main__":
    unittest.main()
