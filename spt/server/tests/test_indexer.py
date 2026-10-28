"""Filesystem truth, normalized storage and repeatable rebuilds."""
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from ..files import FileError, contained, digest
from ..indexer import Indexer
from ..parsing import parse_records, record_verified, result_sections
from .support import fixture_config, populate, snapshot, write


class IndexerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.config = fixture_config(self.root)
        self.paths = populate(self.config.workspace)
        self.indexer = Indexer(self.config)
        self.indexer.reindex()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def details(self) -> dict[str, dict[str, Any]]:
        return {work["title"]: self.indexer.store.detail(work["id"])
                for work in self.indexer.store.list_works()}

    def test_real_conventions_and_current_selection(self) -> None:
        details = self.details()
        self.assertEqual(len(details), 4)
        self.assertEqual(details["火光"]["work"]["status"], "cut")
        self.assertEqual(details["环绕"]["work"]["status"], "wip")
        fire = details["火光"]
        self.assertEqual(fire["work"]["latest_version"], "V3")
        self.assertIsNone(fire["work"]["current_version"])
        self.assertEqual(fire["versions"][0]["returns"], [])
        self.assertEqual(len(fire["versions"][1]["returns"]), 1)
        self.assertEqual(len(fire["versions"][0]["references"]), 1)
        self.assertTrue(fire["finals"][0]["name"].endswith("1080p.mp4"))

    def test_publication_keeps_history_and_media_conflict(self) -> None:
        rice = self.details()["炒饭"]
        self.assertEqual(rice["work"]["status"], "published")
        self.assertEqual(rice["work"]["current_version"], "V3")
        self.assertEqual(rice["work"]["media_match"], "mismatch")
        self.assertFalse(rice["work"]["verified"])
        self.assertEqual(sum(row["current"] for row in rice["records"]), 1)
        self.assertEqual(sum(row["state"] == "withdrawn"
                             for row in rice["records"]), 2)
        self.assertTrue(rice["records"][0]["verified"])
        self.assertEqual(rice["records"][0]["verification_source"], "file")

    def test_package_has_no_invented_version_or_caption_results(self) -> None:
        carousel = self.details()["轮播"]
        self.assertEqual(carousel["versions"], [])
        self.assertEqual(carousel["work"]["current_version"], "V10")
        self.assertEqual(carousel["work"]["media_match"], "match")
        self.assertEqual(carousel["package"]["instagram"], "Caption only.")
        self.assertNotIn("SHA-256", carousel["package"]["google_business"])
        google = next(row for row in carousel["records"]
                      if row["platform"] == "google_business")
        self.assertIsNone(google["published_at"])
        self.assertEqual(carousel["archive_links"],
                         ["/Users/External/archive/brief.md"])

    def test_rebuild_is_repeatable_and_sources_unchanged(self) -> None:
        before = snapshot(self.config.workspace)
        first = self.details()
        self.config.database.unlink()
        self.indexer.reindex()
        self.assertEqual(first, self.details())
        self.assertEqual(before, snapshot(self.config.workspace))
        with self.indexer.store.connect() as connection:
            tables = connection.execute(
                "SELECT name,sql FROM sqlite_master WHERE type='table'")
            schemas = list(tables)
        self.assertGreater(len(schemas), 7)
        self.assertFalse(any("payload" in sql.lower() for _, sql in schemas))

    def test_prompt_search_and_source_only_verification(self) -> None:
        works = self.indexer.store.list_works(query="保持原样")
        self.assertEqual([work["title"] for work in works], ["环绕"])
        self.assertFalse(record_verified("Facebook: url", "Instagram已核验"))
        self.assertTrue(record_verified("Facebook: 已核验", "Instagram未核验"))
        self.assertFalse(record_verified("Facebook: 平台未核", "四平台已核验"))
        records = parse_records("# 记录\n源记录称已发、平台未核\n"
                                "- Instagram: https://instagram.com/reel/a/",
                                "发布记录.md", False)
        self.assertFalse(records[0].verified)

    def test_history_without_withdrawal_is_not_fabricated(self) -> None:
        sections = result_sections("# 当前采用V2\n当前记录\n# V1\n历史", False)
        self.assertEqual([item[2] for item in sections],
                         ["current", "history"])

    def test_ready_requires_real_final_and_package(self) -> None:
        write(self.paths["火光"] / "发布包.md", "待整理的平台文案")
        self.indexer.reindex()
        fire = self.details()["火光"]
        self.assertEqual(fire["work"]["status"], "ready")
        self.assertEqual(fire["records"], [])
        self.assertFalse(fire["work"]["verified"])

    def test_bounds_and_oversize_hash(self) -> None:
        root = self.paths["火光"]
        write(self.root / "private.txt", "outside")
        (root / "escape.txt").symlink_to(self.root / "private.txt")
        for value in ("../private.txt", str((self.root / "private.txt").resolve()), "escape.txt"):
            with self.subTest(value=value), self.assertRaises(FileError):
                contained(root, value)
        with patch("spt.server.files.HASH_LIMIT", 1):
            self.assertIsNone(digest(root / "火光-发布版-1080p.mp4"))

    def test_optional_yaml_is_read_only_and_bounded(self) -> None:
        work = self.paths["环绕"]
        write(work / "spt.yaml", "title: 人工标题\ncategory: 自定义\n")
        before = snapshot(self.config.workspace)
        self.indexer.reindex()
        self.assertEqual(len(self.indexer.store.list_works(category="自定义")), 1)
        self.assertEqual(before, snapshot(self.config.workspace))
        write(work / "spt.yaml", "[invalid")
        self.indexer.reindex()
        self.assertTrue(self.details()["环绕"]["work"]["issues"])


if __name__ == "__main__":
    unittest.main()
