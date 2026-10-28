from __future__ import annotations
import base64
import importlib.util
import ntpath
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_launcher():
    spec = importlib.util.spec_from_file_location("spt_launcher", ROOT / "启动.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DesktopLinkTest(unittest.TestCase):
    """桌面上的「工作区」快捷方式：缺了就建，坏了就修，别人的不动。"""

    def setUp(self) -> None:
        self.launcher = load_launcher()
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.target = base / "软件" / "工作区"
        self.target.mkdir(parents=True)
        self.link = base / "Desktop" / "工作区"
        self.link.parent.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_missing_link_is_created(self) -> None:
        note = self.launcher.desktop_link(self.link, self.target)
        self.assertIn("建好", note)
        self.assertTrue(self.link.is_symlink())
        self.assertEqual(self.link.resolve(), self.target.resolve())
        self.assertEqual(self.launcher.desktop_link(self.link, self.target), "")

    def test_broken_link_is_repaired(self) -> None:
        self.link.symlink_to(self.target.parent / "不存在了")
        note = self.launcher.desktop_link(self.link, self.target)
        self.assertIn("修好", note)
        self.assertEqual(self.link.resolve(), self.target.resolve())

    def test_link_to_another_folder_is_left_alone(self) -> None:
        other = self.target.parent / "别的"
        other.mkdir()
        self.link.symlink_to(other)
        note = self.launcher.desktop_link(self.link, self.target)
        self.assertIn("不是 SPT 的工作区", note)
        self.assertEqual(self.link.resolve(), other.resolve())

    def test_real_folder_is_left_alone(self) -> None:
        self.link.mkdir()
        (self.link / "自己的.txt").write_text("x", encoding="utf-8")
        note = self.launcher.desktop_link(self.link, self.target)
        self.assertIn("普通文件夹", note)
        self.assertFalse(self.link.is_symlink())
        self.assertTrue((self.link / "自己的.txt").is_file())

    def test_shared_copy_creates_nothing_on_the_desktop(self) -> None:
        self.assertEqual(self.launcher.desktop_link(self.link, self.target, create=False), "")
        self.assertFalse(self.link.exists())
        self.link.symlink_to(self.target.parent / "不存在了")
        self.assertEqual(self.launcher.desktop_link(self.link, self.target, create=False), "")
        self.assertTrue(self.link.is_symlink())
        self.assertFalse(self.link.exists(), "a broken link that is not ours stays as it was")

    def test_missing_target_or_same_path_does_nothing(self) -> None:
        self.assertEqual(self.launcher.desktop_link(self.link, self.target.parent / "没有"), "")
        self.assertFalse(self.link.exists())
        self.assertEqual(self.launcher.desktop_link(self.target, self.target), "")



class WindowsLauncherTest(unittest.TestCase):
    """Windows: server without a console, SPT in its own Edge/Chrome app window, one desktop icon."""

    def setUp(self) -> None:
        self.launcher = load_launcher()
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_no_desktop_symlink_on_windows(self) -> None:
        target, link = self.base / "工作区", self.base / "Desktop" / "工作区"
        target.mkdir()
        link.parent.mkdir()
        with patch.object(self.launcher, "WINDOWS", True):
            self.assertEqual(self.launcher.desktop_link(link, target), "")
        self.assertFalse(link.exists() or link.is_symlink())

    def test_server_runs_with_pythonw_in_its_own_group(self) -> None:
        python = self.base / "python.exe"
        python.write_text("", encoding="utf-8")
        command, extra = self.launcher.server_command(windows=True, executable=str(python))
        self.assertEqual(command[0], str(python))                      # no pythonw.exe: python, no window
        self.assertEqual(extra["creationflags"], 0x200 | 0x08000000)
        self.assertEqual((extra["env"]["PYTHONUTF8"], extra["stdin"]), ("1", subprocess.DEVNULL))
        (self.base / "pythonw.exe").write_text("", encoding="utf-8")
        command, extra = self.launcher.server_command(windows=True, executable=str(python))
        self.assertEqual(command[0], str(self.base / "pythonw.exe"))
        self.assertEqual(command[1:], [str(self.launcher.ROOT / "app" / "server.py"), "--port", "8766"])
        self.assertEqual(extra["creationflags"], 0x200 | 0x8)          # detached: closing the cmd window keeps it
        mac_command, mac_extra = self.launcher.server_command(windows=False, executable="/usr/bin/python3")
        self.assertEqual((mac_command[0], mac_extra), ("/usr/bin/python3", {"start_new_session": True}))

    def test_edge_first_then_chrome_install_places_before_path(self) -> None:
        env = {"ProgramFiles(x86)": r"C:\Program Files (x86)", "ProgramFiles": r"C:\Program Files",
               "LocalAppData": r"C:\Users\小明\AppData\Local"}
        edge_x86 = ntpath.join(env["ProgramFiles(x86)"], "Microsoft", "Edge", "Application", "msedge.exe")
        edge_user = ntpath.join(env["LocalAppData"], "Microsoft", "Edge", "Application", "msedge.exe")
        chrome = ntpath.join(env["ProgramFiles"], "Google", "Chrome", "Application", "chrome.exe")
        find = lambda present, which=lambda name: None: self.launcher.app_browser(   # noqa: E731
            env, exists=lambda path: path in present, which=which)
        self.assertEqual(find({edge_x86, chrome}), (edge_x86, "edge-profile"))
        self.assertEqual(find({edge_user, chrome}), (edge_user, "edge-profile"))
        self.assertEqual(find(set(), which=lambda name: {"msedge": r"D:\Edge\msedge.exe"}.get(name)),
                         (r"D:\Edge\msedge.exe", "edge-profile"))
        self.assertEqual(find({chrome}), (chrome, "chrome-profile"))
        self.assertEqual(find(set(), which=lambda name: {"chrome": "chrome.exe"}.get(name)), ("chrome.exe", "chrome-profile"))
        self.assertIsNone(find(set()))
        self.assertIsNone(self.launcher.app_browser({}, exists=lambda path: True, which=lambda name: None),
                          "no environment variables: nothing to look in")

    def test_app_window_command_and_browser_fallback(self) -> None:
        address = "http://127.0.0.1:8766/workspace/"
        command = self.launcher.app_window_command(r"C:\Edge\msedge.exe", "edge-profile", address)
        self.assertEqual(command[:2], [r"C:\Edge\msedge.exe", "--app=" + address])
        self.assertEqual(command[2], "--user-data-dir=" + str(self.launcher.ROOT / "data" / "edge-profile"))
        self.assertIn("--window-size=1280,860", command)
        started, opened = [], []
        result = self.launcher.open_window(address, find=lambda: ("msedge.exe", "edge-profile"),
                                           popen=lambda command, **options: started.append(command),
                                           fallback=opened.append)
        self.assertEqual((result, opened, started[0][1]), ("app", [], "--app=" + address))

        def broken(command, **options):
            raise FileNotFoundError(command[0])

        self.assertEqual(self.launcher.open_window(address, find=lambda: ("gone.exe", "edge-profile"),
                                                   popen=broken, fallback=opened.append), "browser")
        self.assertEqual(self.launcher.open_window(address, find=lambda: None, popen=broken,
                                                   fallback=opened.append), "browser")
        self.assertEqual(opened, [address, address])

    def test_desktop_icon_is_made_once_with_the_spt_icon(self) -> None:
        python = self.base / "python.exe"
        python.write_text("", encoding="utf-8")
        (self.base / "pythonw.exe").write_text("", encoding="utf-8")
        marker = self.base / "data" / ".desktop-shortcut"
        calls = []
        made = self.launcher.desktop_shortcut(executable=str(python), marker=marker,
                                              run=lambda command, **options: calls.append((command, options)))
        self.assertTrue(made)
        command, options = calls[0]
        self.assertEqual(command[:2], ["powershell", "-NoProfile"])
        script = base64.b64decode(command[command.index("-EncodedCommand") + 1]).decode("utf-16-le")
        self.assertIn("Join-Path $desktop 'SPT.lnk'", script)
        self.assertIn("if(-not (Test-Path -LiteralPath $path))", script)
        self.assertIn("$link.TargetPath='" + str(self.base / "pythonw.exe") + "'", script)
        self.assertIn(str(self.launcher.ROOT / "启动.py"), script)
        self.assertIn("$link.IconLocation='" + str(self.launcher.ROOT / "native" / "SPT.ico") + ",0'", script)
        self.assertEqual(options["creationflags"], 0x08000000)
        self.assertTrue(marker.is_file())
        self.assertFalse(self.launcher.desktop_shortcut(executable=str(python), marker=marker,
                                                        run=lambda *a, **k: calls.append(a)))
        self.assertEqual(len(calls), 1, "only the first run makes the icon")
        self.assertTrue((self.launcher.ROOT / "native" / "SPT.ico").is_file())

    def test_a_failed_shortcut_is_quiet_and_tried_again_next_time(self) -> None:
        marker = self.base / "data" / ".desktop-shortcut"

        def fail(command, **options):
            raise subprocess.CalledProcessError(1, command)

        self.assertFalse(self.launcher.desktop_shortcut(executable=str(self.base / "python.exe"), marker=marker, run=fail))
        self.assertFalse(marker.exists())
        self.assertIn("O''Brien", self.launcher.shortcut_script("SPT.lnk", r"C:\O'Brien\pythonw.exe", "", "C:\\", "x.ico"))

    def test_no_mac_app_is_looked_for_off_a_mac(self) -> None:
        with patch.object(self.launcher, "MAC", False):
            self.assertIsNone(self.launcher.native_app())


if __name__ == "__main__":
    unittest.main()
