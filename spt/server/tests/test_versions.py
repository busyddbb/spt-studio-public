"""One prompt per work in lists, search and counts; every version in the detail."""
from __future__ import annotations
import contextlib
import csv
import http.client
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote, urlencode

from .. import agent, cli
from ..api import Server
from ..exporter import export
from ..indexer import Indexer
from ..mcp_server import TOOLS, call
from .support import fixture_config, write


def build(root: Path) -> None:
    # V2 + V3, no 发布记录: the newest version stands for the work
    fire = root / "运营/2026-10-20-AK-火光"
    write(fire / "V2/正文.txt", "篝火 旧词 火光第二版")
    write(fire / "V2/01_菜品.jpg", b"image")
    write(fire / "V3/正文.txt", "篝火 火光第三版")
    write(fire / "提示词.md", "火光的根提示词")           # not versioned: always listed
    # 发布包 names V2: V2 stands for the work, the later V3 was not adopted
    rice = root / "运营/2026-10-21-AK-炒饭"
    write(rice / "V2/正文.txt", "炒饭定稿 锅气")
    write(rice / "V3/正文.txt", "炒饭没采用 锅气")
    write(rice / "发布包.md", "# 发布包 · 定稿 V2\n## Instagram\n文案\n")
    # the named 定稿 was never saved here: the newest saved version stands in
    noodle = root / "运营/2026-10-23-AK-汤面"
    write(noodle / "V1/正文.txt", "汤面第一版")
    write(noodle / "V2/正文.txt", "汤面第二版")
    write(noodle / "发布记录.md", "# 当前采用：V5\n- Instagram: https://www.instagram.com/reel/noodle/\n")
    # the 定稿 has no 正文.txt: no other version takes its place
    sweet = root / "运营/2026-10-24-AK-甜品"
    write(sweet / "V1/正文.txt", "甜品第一版")
    write(sweet / "V2/01_图.jpg", b"image")
    write(sweet / "发布包.md", "# 发布包 · 定稿 V2\n")
    # 段 folders are parts of one long film, not versions
    film = root / "电影/2026-10-22-自家-长片"
    write(film / "段01/正文.txt", "第一段")
    write(film / "段02/正文.txt", "第二段")
    write(root / "提示词/场景/晨雾.md", "---\n标题: 晨雾\n---\n清晨的薄雾")
    write(root / "素材/衣服.md", "| 编号 | 名称 | 写法 |\n|---|---|---|\n"
                                 "| Y001 | 毛衣 | 奶白毛衣 |\n| Y002 | 大衣 | 燕麦大衣 |\n")
    write(root / "记录/2026-10-21-复盘.md", "# 复盘\n今天的结论")


LISTED = {"火光 · V3", "火光 · 提示词", "炒饭 · V2", "汤面 · V2",
          "长片 · 段01", "长片 · 段02", "晨雾"}
SUPERSEDED = {"火光 · V2", "炒饭 · V3", "汤面 · V1", "甜品 · V1"}


class VersionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.config = fixture_config(Path(cls.temporary.name))
        build(cls.config.workspace)
        cls.indexer = Indexer(cls.config)
        cls.indexer.reindex()
        cls.store = cls.indexer.store
        cls.server = Server(cls.indexer)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.works = {work["title"]: work for work in cls.store.list_works()}

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

    def prompts(self, work: str = "", **filters) -> dict[str, dict]:
        items = self.store.list_items("prompt", **filters)
        return {item["title"]: item for item in items
                if not work or item["work_id"] == self.works[work]["id"]}

    def test_without_publish_records_the_newest_version_is_listed(self) -> None:
        listed = self.prompts("火光")
        self.assertEqual(set(listed), {"火光 · V3", "火光 · 提示词"})
        newest = listed["火光 · V3"]
        self.assertEqual((newest["version"], newest["superseded"], newest["adopted"]),
                         ("V3", False, False))
        root = listed["火光 · 提示词"]
        self.assertEqual((root["version"], root["superseded"]), (None, False))

    def test_publish_package_picks_the_listed_version(self) -> None:
        self.assertEqual(self.works["炒饭"]["current_version"], "V2")
        listed = self.prompts("炒饭")
        self.assertEqual(set(listed), {"炒饭 · V2"})
        self.assertEqual((listed["炒饭 · V2"]["adopted"], listed["炒饭 · V2"]["superseded"]),
                         (True, False))

    def test_all_versions_lists_both(self) -> None:
        every = self.prompts("火光", all_versions=True)
        self.assertEqual(set(every), {"火光 · V2", "火光 · V3", "火光 · 提示词"})
        older = every["火光 · V2"]
        self.assertEqual((older["version"], older["superseded"], older["adopted"]),
                         ("V2", True, False))
        self.assertEqual(set(self.prompts("炒饭", all_versions=True)), {"炒饭 · V2", "炒饭 · V3"})
        titles = set(self.prompts(all_versions=True))
        self.assertEqual(titles, LISTED | SUPERSEDED)
        self.assertEqual({title for title, item in self.prompts(all_versions=True).items()
                          if item["superseded"]}, SUPERSEDED)

    def test_edge_cases_segments_missing_and_promptless_final(self) -> None:
        self.assertEqual(set(self.prompts("长片")), {"长片 · 段01", "长片 · 段02"})
        self.assertEqual(self.works["汤面"]["current_version"], "V5")
        self.assertEqual(set(self.prompts("汤面")), {"汤面 · V2"})
        self.assertFalse(self.prompts("汤面")["汤面 · V2"]["adopted"])
        self.assertEqual(self.prompts("甜品"), {})
        self.assertEqual(set(self.prompts("甜品", all_versions=True)), {"甜品 · V1"})
        self.assertEqual(set(self.prompts()), LISTED)

    def test_counts_match_the_list(self) -> None:
        for every in (False, True):
            summary = self.store.library(every)
            for kind, entry in summary["kinds"].items():
                with self.subTest(kind=kind, all_versions=every):
                    self.assertEqual(entry["count"], len(self.store.list_items(
                        kind, all_versions=every)))
                    for section in entry["sections"]:
                        self.assertEqual(section["count"], len(self.store.list_items(
                            kind, section["name"], all_versions=every)))
            self.assertEqual(summary["kinds"]["prompt"]["superseded"], len(SUPERSEDED))
        self.assertEqual(self.store.library()["kinds"]["prompt"]["count"], len(LISTED))
        self.assertEqual(self.indexer.health()["counts"]["prompt"], len(LISTED))
        self.assertEqual(self.store.library()["kinds"]["material"]["superseded"], 0)

    def test_http_lists_counts_and_palette_search(self) -> None:
        for extra in ({}, {"all_versions": "1"}):
            with self.subTest(extra=extra):
                items = self.get("/api/items?" + urlencode({"kind": "prompt", **extra}))["items"]
                summary = self.get("/api/library?" + urlencode(extra))
                self.assertEqual(summary["kinds"]["prompt"]["count"], len(items))
                grouped = self.get("/api/items?" + urlencode(
                    {"kind": "prompt", "section": "运营", **extra}))["items"]
                counted = {entry["name"]: entry["count"]
                           for entry in summary["kinds"]["prompt"]["sections"]}
                self.assertEqual(counted["运营"], len(grouped))
        self.assertEqual(len(self.get("/api/items?kind=prompt")["items"]), len(LISTED))
        # the ⌘K palette asks /api/items?q= (no kind) next to /api/works?q=
        word = quote("旧词")
        self.assertEqual(self.get(f"/api/items?q={word}")["items"], [])
        found = self.get(f"/api/items?q={word}&all_versions=1")["items"]
        self.assertEqual([item["title"] for item in found], ["火光 · V2"])
        self.assertEqual([work["title"] for work in self.get(f"/api/works?q={word}")["works"]],
                         ["火光"])
        older = self.get(f"/api/items/{found[0]['id']}")["item"]
        self.assertEqual((older["superseded"], older["version"], older["body"]),
                         (True, "V2", "篝火 旧词 火光第二版"))
        self.assertEqual(self.get("/api/health")["counts"]["prompt"], len(LISTED))

    def test_work_detail_still_has_every_version(self) -> None:
        for title, names, current in (("火光", {"V2", "V3"}, None), ("炒饭", {"V2", "V3"}, "V2"),
                                      ("甜品", {"V1", "V2"}, "V2")):
            with self.subTest(work=title):
                identifier = self.works[title]["id"]
                for detail in (self.store.detail(identifier),
                               self.get(f"/api/works/{identifier}")):
                    versions = {version["name"]: version for version in detail["versions"]}
                    self.assertEqual(set(versions), names)
                    self.assertEqual({name for name, version in versions.items()
                                      if version["is_current"]}, {current} - {None})
        fire = self.get(f"/api/works/{self.works['火光']['id']}")
        self.assertEqual({version["name"]: version["prompt"] for version in fire["versions"]},
                         {"V2": "篝火 旧词 火光第二版", "V3": "篝火 火光第三版"})
        self.assertIn("提示词.md", {doc["name"] for doc in fire["source_documents"]})

    def test_agents_search_the_listed_version_unless_asked(self) -> None:
        def titles(results: list[dict]) -> set[str]:
            return {entry["title"] for entry in results}
        self.assertEqual(titles(agent.search(self.indexer, "篝火", "prompt")), {"火光 · V3"})
        found = agent.search(self.indexer, "篝火", "prompt", all_versions=True)
        self.assertEqual(titles(found), {"火光 · V2", "火光 · V3"})
        self.assertEqual({entry["title"] for entry in found if entry.get("superseded")},
                         {"火光 · V2"})
        self.assertEqual(next(entry for entry in found if entry["title"] == "火光 · V3")["version"],
                         "V3")
        with patch.object(agent, "open_indexer", return_value=self.indexer):
            for argv, expected in ((["search", "锅气", "--kind", "prompt"], {"炒饭 · V2"}),
                                   (["search", "锅气", "--kind", "prompt", "--all-versions"],
                                    {"炒饭 · V2", "炒饭 · V3"})):
                printed = io.StringIO()
                with contextlib.redirect_stdout(printed):
                    self.assertEqual(cli.main(argv), 0)
                self.assertEqual(titles(json.loads(printed.getvalue())), expected)
            # without a kind the work itself comes too (its search reads every version)
            self.assertEqual(titles(call("spt_search", {"query": "锅气"})), {"炒饭", "炒饭 · V2"})
            self.assertEqual(titles(call("spt_search", {"query": "锅气", "kind": "prompt",
                                                        "all_versions": True})),
                             {"炒饭 · V2", "炒饭 · V3"})
        search = next(tool for tool in TOOLS if tool["name"] == "spt_search")
        self.assertEqual(search["inputSchema"]["properties"]["all_versions"], {"type": "boolean"})

    def test_export_matches_the_list_unless_asked(self) -> None:
        def rows(**options) -> dict[str, dict]:
            data, _, _ = export(self.store, "csv", "prompt", **options)
            table = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
            return {row["标题"]: row for row in table}
        self.assertEqual(set(rows()), LISTED)
        self.assertEqual(rows()["火光 · V3"]["版本"], "V3")
        self.assertEqual(set(rows(all_versions=True)), LISTED | SUPERSEDED)


class RebuildTests(unittest.TestCase):
    def test_a_new_version_takes_over_and_old_spt_rebuilds_leave_no_stale_flags(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            config = fixture_config(Path(folder))
            build(config.workspace)
            indexer = Indexer(config)
            indexer.reindex()
            write(config.workspace / "运营/2026-10-20-AK-火光/V4/正文.txt", "火光第四版")
            indexer.reindex()
            fire = {item["title"]: item for item in indexer.store.list_items("prompt", all_versions=True)
                    if item["title"].startswith("火光 · V")}
            self.assertEqual({title for title, item in fire.items() if not item["superseded"]},
                             {"火光 · V4"})
            # An SPT that predates item_versions shares this file: its rebuild empties and
            # refills items only. The flags go with the rows, so every version shows (as it
            # did before) rather than stale flags, until this SPT rebuilds.
            with indexer.store.connect() as connection:
                rows = [tuple(row) for row in connection.execute("SELECT * FROM items")]
                connection.execute("DELETE FROM items")
                connection.executemany("INSERT INTO items VALUES(" + ",".join("?" * len(rows[0]))
                                       + ")", rows)
                self.assertEqual(connection.execute(
                    "SELECT COUNT(*) FROM item_versions").fetchone()[0], 0)
            self.assertEqual(len(indexer.store.list_items("prompt")),
                             len(indexer.store.list_items("prompt", all_versions=True)))
            indexer.reindex()
            self.assertEqual(len(indexer.store.list_items("prompt")), len(LISTED))


if __name__ == "__main__":
    unittest.main()
