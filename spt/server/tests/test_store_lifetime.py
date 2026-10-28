"""Connections release handles on every path, including Windows file ownership."""
from __future__ import annotations
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ..store import Store


class StoreLifetimeTests(unittest.TestCase):
    def test_committed_connection_is_closed_before_caller_continues(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / "index.sqlite3")
            with store.connect() as connection:
                connection.execute("CREATE TABLE fixture (value TEXT)")
                connection.execute("INSERT INTO fixture VALUES ('saved')")
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute("SELECT 1")
            with store.connect() as check:
                self.assertEqual(check.execute("SELECT value FROM fixture").fetchone()[0], "saved")
            # Immediate rename/unlink detects leaked handles on Windows.
            moved = store.database.with_name("moved.sqlite3")
            store.database.rename(moved)
            moved.unlink()

    def test_failed_transaction_rolls_back_and_closes(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / "index.sqlite3")
            with store.connect() as connection:
                connection.execute("CREATE TABLE fixture (value TEXT)")
            with self.assertRaisesRegex(RuntimeError, "stop"):
                with store.connect() as failing:
                    failing.execute("INSERT INTO fixture VALUES ('uncommitted')")
                    raise RuntimeError("stop")
            with self.assertRaises(sqlite3.ProgrammingError):
                failing.execute("SELECT 1")
            with store.connect() as check:
                self.assertEqual(check.execute("SELECT COUNT(*) FROM fixture").fetchone()[0], 0)

    def test_setup_failure_closes_the_raw_connection(self):
        class BrokenConnection:
            closed = False
            row_factory = None
            def execute(self, sql):
                raise sqlite3.OperationalError("fixture initialization failure")
            def close(self):
                self.closed = True
        with tempfile.TemporaryDirectory() as folder:
            store = object.__new__(Store)
            store.database = Path(folder) / "index.sqlite3"
            broken = BrokenConnection()
            with patch("spt.server.store.sqlite3.connect", return_value=broken):
                with self.assertRaises(sqlite3.OperationalError):
                    with store.connect():
                        self.fail("failed setup must not yield a connection")
            self.assertTrue(broken.closed)


if __name__ == "__main__":
    unittest.main()
