"""Regression tests for source writes through cache and root replacement."""
from __future__ import annotations
import io
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from ..api import Handler
from ..config import Config
from ..covers import generate
from ..files import FileError, contained
from ..indexer import Indexer
from ..streaming import send_file
from ..scan import scan_works
from .support import fixture_config, populate, snapshot, write


class CacheSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.config = fixture_config(self.root)
        self.paths = populate(self.config.workspace)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_database_and_sidecars_cannot_redirect_to_source(self) -> None:
        self.config.cache.mkdir()
        protected = self.paths["环绕"] / "source.sqlite3"
        write(protected, b"")
        before = snapshot(self.config.workspace)
        for suffix in ("", "-journal", "-wal", "-shm"):
            target = self.config.database.with_name("index.sqlite3" + suffix)
            target.symlink_to(protected)
            with self.subTest(suffix=suffix), self.assertRaises(RuntimeError):
                Indexer(self.config)
            target.unlink()
        self.assertEqual(before, snapshot(self.config.workspace))

    def test_thumbnail_directory_cannot_redirect_to_source(self) -> None:
        indexer = Indexer(self.config)
        indexer.reindex()
        (self.paths["火光"] / "封面.jpg").unlink()
        (self.config.cache / "thumbs").symlink_to(self.paths["火光"])
        before = snapshot(self.config.workspace)
        # every cover goes through the thumbs folder, the fallback V3 picture too
        with patch("spt.server.covers.SMALL_COVER", 0), self.assertRaises(RuntimeError):
            indexer.reindex()
        self.assertEqual(before, snapshot(self.config.workspace))

    def test_workspace_root_link_is_explicitly_supported(self) -> None:
        link = self.root / "workspace-link"
        link.symlink_to(self.config.workspace, target_is_directory=True)
        config = Config(link, self.config.cache, self.config.ui, 0)
        indexer = Indexer(config)
        self.assertEqual(indexer.reindex()["count"], 4)
        self.assertEqual(indexer.workspace, self.config.workspace.resolve())

    def test_work_root_replaced_with_internal_link_is_rejected(self) -> None:
        indexer = Indexer(self.config)
        indexer.reindex()
        work = next(work for work in indexer.store.list_works()
                    if work["title"] == "环绕")
        original = self.paths["环绕"]
        original.rename(original.with_name("source-backup"))
        original.symlink_to(self.paths["火光"], target_is_directory=True)
        handler = object.__new__(Handler)
        handler.server = type("FixtureServer", (), {"indexer": indexer})()
        with self.assertRaises(FileError):
            handler.work_root(work)

    def test_stream_retains_descriptor_after_name_change(self) -> None:
        source = self.paths["环绕"] / "note.txt"
        outside = self.root / "outside.txt"
        write(source, b"original content")
        write(outside, b"OUTSIDE")
        handler = SwappingHandler(source, outside)
        path = contained(source.parent, source.name)
        send_file(handler, path, anchor=self.config.resolved_workspace)
        self.assertEqual(handler.wfile.getvalue(), b"original content")

    def test_thumbnail_writes_to_held_descriptor_only(self) -> None:
        work = next(work for work in scan_works(self.config.resolved_workspace)
                    if work.title == "火光")
        target = self.config.cache / "thumbs" / "cover.jpg"
        target.parent.mkdir(parents=True)
        protected = self.paths["环绕"] / "protected.jpg"
        write(protected, b"untouched")

        def replace_name(*args: Any, **kwargs: Any) -> None:
            output = kwargs["stdout"]
            temporary = Path(output.name)
            temporary.unlink()
            temporary.symlink_to(protected)
            output.write(b"new image")

        source = Path(work.path) / work.finals[0].path
        with patch("spt.server.covers.subprocess.run", replace_name):
            with self.assertRaises(RuntimeError):
                generate("ffmpeg", source, target, work, self.config.cache)
        self.assertEqual(protected.read_bytes(), b"untouched")
        self.assertEqual(list(target.parent.iterdir()), [])


class SwappingHandler:
    def __init__(self, source: Path, outside: Path) -> None:
        self.headers: dict[str, str] = {}
        self.wfile = io.BytesIO()
        self.source = source
        self.outside = outside

    def send_response(self, status: int) -> None:
        self.status = status

    def send_header(self, name: str, content: str) -> None:
        return

    def end_headers(self) -> None:
        self.source.unlink()
        self.source.symlink_to(self.outside)


if __name__ == "__main__":
    unittest.main()
