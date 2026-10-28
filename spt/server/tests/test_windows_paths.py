"""Windows rooted/drive-relative paths must never become work-relative reads."""
from __future__ import annotations
from pathlib import Path, PureWindowsPath
import unittest
from unittest.mock import patch

from ..files import FileError, contained


class WindowsPathBoundaryTests(unittest.TestCase):
    def test_rooted_and_drive_relative_paths_are_rejected_before_filesystem_access(self):
        # Exercise Windows path parsing on every CI host. PureWindowsPath has no
        # filesystem methods: a bypass cannot silently inspect a real location.
        with patch("spt.server.files.Path", PureWindowsPath):
            for value in (r"\Windows\system.ini", r"C:relative.txt", r"C:\Windows\system.ini", r"\\server\share\file.txt", "/etc/passwd"):
                with self.subTest(value=value), self.assertRaises(FileError):
                    contained(Path("fixture-work"), value)


if __name__ == "__main__":
    unittest.main()
