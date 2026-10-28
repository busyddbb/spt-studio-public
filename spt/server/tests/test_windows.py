"""The Windows branches, exercised on any system with the platform checks patched.

Nothing here touches a real Recycle Bin, registry or console: ctypes' shell32,
subprocess and the platform flags are stand-ins.
"""
from __future__ import annotations
import ctypes
import datetime as dt
import mimetypes
import os
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .. import covers, files, intake, share, timezones
from ..files import FileError, move_to_trash, open_source
from ..indexer import Indexer
from .support import fixture_config, write


class FakeShell32:
    """Records the SHFILEOPSTRUCTW it is handed; moves the file aside like the bin would."""

    def __init__(self, result: int = 0, aborted: bool = False) -> None:
        self.result, self.aborted, self.seen = result, aborted, None

    def SHFileOperationW(self, reference):   # noqa: N802 (Windows API name)
        operation = reference._obj
        kind = type(operation)
        address = ctypes.c_void_p.from_buffer(operation, kind.pFrom.offset).value
        path = operation.pFrom
        self.seen = {"wFunc": operation.wFunc, "fFlags": operation.fFlags,
                     "pFrom": ctypes.wstring_at(address, len(path) + 2), "pTo": operation.pTo}
        if self.result == 0 and not self.aborted:
            target = Path(path)
            (target.parent / ".bin").mkdir(exist_ok=True)
            os.rename(target, target.parent / ".bin" / target.name)
        operation.fAnyOperationsAborted = self.aborted
        return self.result


class RecycleBinTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_the_shell_gets_a_double_nul_path_and_undoable_silent_flags(self) -> None:
        write(self.root / "便签" / "a.md", "第一")
        shell = FakeShell32()
        moved = files.recycle(self.root / "便签" / "a.md", shell32=shell)
        self.assertEqual(moved, self.root / "便签" / "a.md")
        self.assertEqual(shell.seen["wFunc"], 3)                       # FO_DELETE
        self.assertEqual(shell.seen["fFlags"], 0x40 | 0x10 | 0x4 | 0x400)
        self.assertEqual(shell.seen["pFrom"], os.path.abspath(self.root / "便签" / "a.md") + "\0\0")
        self.assertIsNone(shell.seen["pTo"])
        self.assertFalse((self.root / "便签" / "a.md").exists())

    def test_a_refusal_or_cancel_is_an_error_and_the_file_stays(self) -> None:
        write(self.root / "x.txt", "x")
        with self.assertRaises(FileError) as caught:
            files.recycle(self.root / "x.txt", shell32=FakeShell32(result=0x78))
        self.assertTrue(str(caught.exception).startswith("放不进回收站："))
        with self.assertRaises(FileError):
            files.recycle(self.root / "x.txt", shell32=FakeShell32(aborted=True))
        self.assertTrue((self.root / "x.txt").is_file())

    def test_move_to_trash_uses_the_recycle_bin_only_on_windows_without_a_test_trash(self) -> None:
        write(self.root / "作品" / "V1" / "正文.txt", "提示词")
        with patch.object(files, "WINDOWS", True), \
                patch.object(files, "recycle", side_effect=lambda path: path) as recycle:
            self.assertEqual(move_to_trash(self.root / "作品"), self.root / "作品")
            recycle.assert_called_once_with(self.root / "作品")
            moved = move_to_trash(self.root / "作品", trash_dir=self.root / "Trash")   # tests' own trash
            self.assertEqual(moved, self.root / "Trash" / "作品")
            self.assertEqual(recycle.call_count, 1)
        with patch.object(files, "recycle") as recycle:
            write(self.root / "b.md", "b")
            move_to_trash(self.root / "b.md", trash_dir=self.root / "Trash")
            recycle.assert_not_called()


class OpenWithoutDirFdTests(unittest.TestCase):
    """Windows has no dir_fd / O_DIRECTORY: every step is checked for links instead."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "作品"
        write(self.root / "V1" / "成片.mp4", b"video")
        patcher = patch.object(files, "DIR_FD", False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_plain_files_open_and_links_on_the_way_are_refused(self) -> None:
        with open_source(self.root, self.root / "V1" / "成片.mp4") as source:
            self.assertEqual(source.read(), b"video")
        outside = Path(self.temporary.name) / "outside"
        write(outside / "secret.txt", "no")
        (self.root / "link").symlink_to(outside, target_is_directory=True)
        (self.root / "file-link.txt").symlink_to(outside / "secret.txt")
        for path in (self.root / "link" / "secret.txt", self.root / "file-link.txt"):
            with self.assertRaises(FileError):
                with open_source(self.root, path):
                    pass
        with self.assertRaises(FileNotFoundError):
            with open_source(self.root, self.root / "V1" / "没有.mp4"):
                pass
        with self.assertRaises(FileError):
            with open_source(self.root, self.root / "V1"):   # a folder is not a work file
                pass

    def test_is_link_knows_windows_symlink_and_junction_tags(self) -> None:
        plain = os.lstat(self.root / "V1" / "成片.mp4")
        for tag, expected in ((0xA000000C, True), (0xA0000003, True), (0x9000001A, False), (0, False)):
            fake = SimpleNamespace(st_mode=plain.st_mode, st_reparse_tag=tag)
            with patch.object(files.os, "lstat", return_value=fake):
                self.assertEqual(files.is_link(self.root / "x"), expected, hex(tag))


class IntakeCopyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_off_a_mac_files_are_copied_into_new_files_only(self) -> None:
        write(self.root / "原件" / "成片.mp4", b"new video")
        target = self.root / "工作区" / "作品" / "成片.mp4"
        with patch.object(intake, "sys", SimpleNamespace(platform="win32")), \
                patch.object(intake.subprocess, "run") as run:
            intake.clone(self.root / "原件" / "成片.mp4", target)
            run.assert_not_called()
            self.assertEqual(target.read_bytes(), b"new video")
            self.assertEqual(target.stat().st_mtime, (self.root / "原件" / "成片.mp4").stat().st_mtime)
            target.write_bytes(b"already here")
            intake.clone(self.root / "原件" / "成片.mp4", target)   # never overwrites
            self.assertEqual(target.read_bytes(), b"already here")

    def test_a_mac_without_cp_falls_back_to_the_same_copy(self) -> None:
        write(self.root / "a.jpg", b"jpg")
        with patch.object(intake, "sys", SimpleNamespace(platform="darwin")), \
                patch.object(intake.subprocess, "run", side_effect=FileNotFoundError("cp")):
            intake.clone(self.root / "a.jpg", self.root / "out" / "a.jpg")
        self.assertEqual((self.root / "out" / "a.jpg").read_bytes(), b"jpg")


class CoverToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.cache = Path(self.temporary.name)
        (self.cache / "thumbs").mkdir()
        self.owner = SimpleNamespace(issues=[])

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def build(self, source: str, target: str = "x.jpg", which=None, pillow=True):
        calls = []
        record = lambda name: (lambda *args: calls.append(name))   # noqa: E731
        with patch.object(covers, "on_mac", return_value=False), \
                patch.object(covers, "bundled_ffmpeg", return_value=None), \
                patch.object(covers, "pillow", return_value=pillow), \
                patch.object(covers.shutil, "which", which or (lambda name: None)), \
                patch.object(covers, "generate", side_effect=record("ffmpeg")), \
                patch.object(covers, "shrink", side_effect=record("sips")), \
                patch.object(covers, "quick_look", side_effect=record("quicklook")), \
                patch.object(covers, "pillow_shrink", side_effect=record("pillow")):
            covers.build(Path(source), self.cache / "thumbs" / target, self.owner, self.cache)
        return calls

    def test_off_a_mac_sips_and_quick_look_are_never_used(self) -> None:
        everything = lambda name: "C:/tools/" + name   # noqa: E731  (even if a sips.exe existed)
        self.assertEqual(self.build("a.jpg", which=everything), ["ffmpeg"])
        self.assertEqual(self.build("clip.mp4", which=everything), ["ffmpeg"])
        self.assertEqual(self.build("a.jpg"), ["pillow"])                      # no ffmpeg: Pillow
        self.assertEqual(self.build("a.jpg", pillow=False), [])                # neither: no cover
        self.assertEqual(self.owner.issues, [])
        self.assertEqual(self.build("clip.mp4"), [])
        self.assertEqual(self.owner.issues, ["未找到ffmpeg，封面缓存暂不可用"])

    def test_pillow_makes_a_640_jpeg_and_keeps_png_as_png(self) -> None:
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow is not installed")
        source = self.cache / "大图.png"
        Image.new("RGBA", (1600, 900), (200, 80, 40, 128)).save(source)
        covers.pillow_shrink(source, self.cache / "thumbs" / "a.jpg", self.owner, self.cache)
        covers.pillow_shrink(source, self.cache / "thumbs" / "b.png", self.owner, self.cache)
        with Image.open(self.cache / "thumbs" / "a.jpg") as picture:
            self.assertEqual((picture.format, picture.size), ("JPEG", (640, 360)))
        with Image.open(self.cache / "thumbs" / "b.png") as picture:
            self.assertEqual((picture.format, picture.mode), ("PNG", "RGBA"))
        broken = self.cache / "坏.jpg"
        broken.write_bytes(b"not a picture")
        covers.pillow_shrink(broken, self.cache / "thumbs" / "c.jpg", self.owner, self.cache)
        self.assertEqual(self.owner.issues, ["封面缩略图生成失败；原图未修改"])
        self.assertEqual(sorted(path.name for path in (self.cache / "thumbs").iterdir()), ["a.jpg", "b.png"])

    def test_ffmpeg_runs_without_a_console_window_on_windows(self) -> None:
        seen = {}

        def run(command, **options):
            seen.update(options, command=command)
            options["stdout"].write(b"png")

        with patch.object(covers, "NO_WINDOW", 0x08000000), patch.object(covers.subprocess, "run", run):
            covers.generate("ffmpeg", Path("a.png"), self.cache / "thumbs" / "a.png", self.owner, self.cache)
        self.assertEqual(seen["creationflags"], 0x08000000)
        self.assertEqual(seen["command"][seen["command"].index("-vcodec") + 1], "png")
        self.assertEqual((self.cache / "thumbs" / "a.png").read_bytes(), b"png")
        self.assertEqual([path.name for path in (self.cache / "thumbs").iterdir()], ["a.png"])


class PacificTimeTests(unittest.TestCase):
    def test_built_in_rules_match_the_database_hour_by_hour(self) -> None:
        try:
            database = ZoneInfo("America/Los_Angeles")
        except ZoneInfoNotFoundError:
            self.skipTest("no time zone database on this computer")
        rules = timezones.USPacific()
        moment = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
        while moment.year < 2028:
            ours, theirs = moment.astimezone(rules), moment.astimezone(database)
            self.assertEqual((ours.replace(tzinfo=None), ours.fold, ours.utcoffset()),
                             (theirs.replace(tzinfo=None), theirs.fold, theirs.utcoffset()), moment)
            for fold in (0, 1):   # wall clock → offset, including the gap and the repeated hour
                wall = theirs.replace(tzinfo=None, fold=fold)
                self.assertEqual(wall.replace(tzinfo=rules).utcoffset(),
                                 wall.replace(tzinfo=database).utcoffset(), (wall, fold))
            moment += dt.timedelta(minutes=30)

    def test_without_a_database_the_rules_take_over(self) -> None:
        with patch.object(timezones, "ZoneInfo", side_effect=ZoneInfoNotFoundError("none")):
            zone = timezones.pacific()
        self.assertIsInstance(zone, timezones.USPacific)
        self.assertEqual(dt.datetime(2026, 7, 1, 12, tzinfo=zone).utcoffset(), dt.timedelta(hours=-7))
        self.assertEqual(dt.datetime(2026, 12, 1, 12, tzinfo=zone).tzname(), "PST")


class ShareZipTests(unittest.TestCase):
    def test_names_are_utf8_modes_and_links_are_kept(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "SPT"
            write(target / "启动SPT.bat", "@echo off\r\n")
            write(target / "启动SPT.command", "#!/bin/zsh\n")
            (target / "启动SPT.command").chmod(0o755)
            write(target / "SPT.app" / "Contents" / "MacOS" / "SPT", b"binary")
            (target / "SPT.app" / "Current").symlink_to("Contents")
            (target / "工作区" / "便签").mkdir(parents=True)
            share.write_zip(target, Path(folder) / "SPT.zip")
            with zipfile.ZipFile(Path(folder) / "SPT.zip") as archive:
                infos = {info.filename: info for info in archive.infolist()}
            self.assertIn("SPT/启动SPT.bat", infos)
            self.assertIn("SPT/工作区/便签/", infos)
            self.assertTrue(all(info.flag_bits & 0x800 for name, info in infos.items() if not name.isascii()))
            self.assertFalse(any(name.startswith("__MACOSX") for name in infos))
            self.assertEqual(infos["SPT/启动SPT.command"].external_attr >> 16 & 0o777, 0o755)
            self.assertTrue(stat.S_ISLNK(infos["SPT/SPT.app/Current"].external_attr >> 16))
        self.assertIn(Path("启动SPT.bat"), [Path(name) for name in share.INCLUDE])
        self.assertIn(Path("spt/docs/验收图片"), share.SKIP_FILES)


class SmallWindowsBitsTests(unittest.TestCase):
    def test_mime_types_are_pinned_on_windows(self) -> None:
        with patch.object(mimetypes, "add_type") as add, patch.object(mimetypes, "init"):
            files.pin_mime_types(windows=True)
        self.assertIn(("text/javascript", ".js"), [call.args for call in add.call_args_list])
        with patch.object(mimetypes, "add_type") as add:
            files.pin_mime_types(windows=False)
        add.assert_not_called()

    def test_health_names_the_platform_for_the_agent_commands(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            config = fixture_config(Path(folder))
            config.workspace.mkdir(parents=True, exist_ok=True)
            indexer = Indexer(config)
            indexer.reindex()
            expected = "windows" if os.name == "nt" else "mac" if os.uname().sysname == "Darwin" else "other"
            self.assertEqual(indexer.health()["platform"], expected)
            with patch("spt.server.indexer.WINDOWS", True):
                self.assertEqual(indexer.health()["platform"], "windows")

    def test_flags_windows_lacks_are_zero_there(self) -> None:
        for name in ("O_NOFOLLOW", "O_NONBLOCK", "O_BINARY"):
            self.assertEqual(getattr(files, name.replace("O_", "")), getattr(os, name, 0))


if __name__ == "__main__":
    unittest.main()
