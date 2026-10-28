from __future__ import annotations
import http.client
import shutil
import struct
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ..api import Server
from ..covers import build, generate, item_thumb
from ..indexer import Indexer
from ..scan import natural_key
from ..store import cover_url, thumb_url
from .support import fixture_config, populate, snapshot, write


def bitmap(path: Path, width: int, height: int) -> None:
    """A plain 24-bit BMP, enough for sips to turn into a real JPEG."""
    row = (width * 3 + 3) & ~3
    body = b"".join(b"".join(bytes((x % 256, y % 256, 160)) for x in range(width)).ljust(row, b"\0")
                    for y in range(height))
    header = struct.pack("<2sIHHI", b"BM", 54 + len(body), 0, 0, 54)
    info = struct.pack("<IiiHHIIiiII", 40, width, height, 1, 24, 0, len(body), 2835, 2835, 0, 0)
    path.write_bytes(header + info + body)


def size_of(path: Path) -> tuple[int, int]:
    output = subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
                            capture_output=True, text=True, check=True).stdout
    values = [int(line.split(":")[1]) for line in output.splitlines() if "pixel" in line]
    return values[0], values[1]


class CoverTests(unittest.TestCase):
    def test_cover_urls_change_with_the_thumbnail(self):
        self.assertEqual(cover_url("abc", None), "/api/works/abc/cover")
        self.assertEqual(cover_url("abc", "/cache/thumbs/0123456789abcdef.jpg"),
                         "/api/works/abc/cover?v=0123456789ab")

    @unittest.skipUnless(shutil.which("sips"), "needs the macOS sips tool")
    def test_large_covers_get_a_small_thumbnail_and_sources_stay_untouched(self):
        with tempfile.TemporaryDirectory() as folder:
            config = fixture_config(Path(folder))
            paths = populate(config.workspace)
            source = Path(folder) / "big.bmp"
            bitmap(source, 1200, 900)
            cover = paths["环绕"] / "封面.jpg"
            subprocess.run(["sips", "-s", "format", "jpeg", str(source), "--out", str(cover)],
                           capture_output=True, check=True)
            before = snapshot(config.workspace)
            with patch("spt.server.covers.SMALL_COVER", 0):
                indexer = Indexer(config)
                indexer.reindex()
            work = next(work for work in indexer.store.list_works() if work["title"] == "环绕")
            self.assertRegex(work["cover"], r"^/api/works/[a-f0-9]{20}/cover\?v=[a-f0-9]{12}$")
            thumbs = list((config.cache / "thumbs").glob("*.jpg"))
            self.assertEqual(len(thumbs), 1)
            self.assertEqual(max(size_of(thumbs[0])), 640)
            self.assertEqual(before, snapshot(config.workspace))

    def test_quick_look_steps_in_when_ffmpeg_makes_no_frame(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "thumbs" / "x.jpg"
            target.parent.mkdir()
            owner = SimpleNamespace(issues=[])

            def no_frame(binary, source, target, work, cache):
                work.issues.append("封面抽帧失败；原视频未修改")

            def frame(source, target, work, cache):
                target.write_bytes(b"frame")

            with patch("spt.server.covers.shutil.which", lambda name: "/usr/bin/" + name), \
                    patch("spt.server.covers.generate", side_effect=no_frame) as ffmpeg, \
                    patch("spt.server.covers.quick_look", side_effect=frame) as quick:
                build(Path("clip.mp4"), target, owner, Path(folder))
            self.assertTrue(ffmpeg.called and quick.called)
            self.assertEqual(target.read_bytes(), b"frame")
            self.assertEqual(owner.issues, [])   # fixed by the fallback, so not a problem

    def test_an_empty_frame_is_never_kept(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "thumbs" / "x.jpg"
            target.parent.mkdir()
            owner = SimpleNamespace(issues=[])
            with patch("spt.server.covers.subprocess.run"):   # ffmpeg "succeeds" with no output
                generate("ffmpeg", Path("clip.mp4"), target, owner, Path(folder))
            self.assertEqual(list(target.parent.iterdir()), [])
            self.assertEqual(len(owner.issues), 1)


class ItemThumbTests(unittest.TestCase):
    """Library cards ask /api/items/<id>/thumb instead of loading the original file."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.config = fixture_config(self.root)
        self.workspace = self.config.workspace
        write(self.workspace / "素材/场景/小图.png", b"\x89PNG small picture")
        write(self.workspace / "提示词/菜品/色面.md", "为餐厅做一张无字底图。")
        write(self.workspace / "提示词/菜品/色面.jpg", b"small preview")
        write(self.workspace / "记录/2026-10-22-笔记.md", "# 笔记\n没有图")
        self.server = None

    def tearDown(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=3)
        self.temporary.cleanup()

    def serve(self) -> Indexer:
        indexer = Indexer(self.config)
        indexer.reindex()
        self.server = Server(indexer)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return indexer

    def request(self, path: str) -> tuple[int, dict[str, str], bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        connection.request("GET", path)
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    @staticmethod
    def item(indexer: Indexer, title: str) -> dict:
        return next(item for item in indexer.store.list_items() if item["title"] == title)

    def test_thumb_urls_change_with_the_thumbnail(self):
        self.assertEqual(thumb_url("abc", None), "/api/items/abc/thumb")
        self.assertEqual(thumb_url("abc", "0123456789abcdef.jpg"), "/api/items/abc/thumb?v=0123456789ab")
        picture = self.workspace / "素材/场景/小图.png"
        name, as_is = item_thumb(picture)
        self.assertTrue(as_is)
        self.assertRegex(name, r"^[a-f0-9]{64}\.png$")
        write(picture, b"\x89PNG changed")
        self.assertNotEqual(item_thumb(picture)[0], name)
        self.assertIsNone(item_thumb(self.workspace / "提示词/菜品/色面.md"))

    @unittest.skipUnless(shutil.which("sips"), "needs the macOS sips tool")
    def test_big_pictures_get_a_cached_thumbnail_on_first_request(self):
        source = self.root / "big.bmp"
        bitmap(source, 1200, 900)
        big = self.workspace / "素材/场景/大图.jpg"
        subprocess.run(["sips", "-s", "format", "jpeg", str(source), "--out", str(big)],
                       capture_output=True, check=True)
        before = snapshot(self.workspace)
        with patch("spt.server.covers.SMALL_COVER", 0):
            indexer = self.serve()
            item = self.item(indexer, "大图")
            self.assertEqual(item["file_url"], f"/api/items/{item['id']}/file")
            self.assertEqual(item["thumb_url"], f"/api/items/{item['id']}/thumb")   # not made yet
            status, headers, body = self.request(item["thumb_url"])
            self.assertEqual((status, headers["Content-Type"], headers["Cache-Control"]),
                             (200, "image/jpeg", "no-store"))
            [made] = list((self.config.cache / "item-thumbs").iterdir())
            self.assertEqual(made.read_bytes(), body)
            self.assertEqual(max(size_of(made)), 640)
            again = self.item(indexer, "大图")
            self.assertEqual(again["thumb_url"],
                             f"/api/items/{item['id']}/thumb?v={made.stem[:12]}")
            self.assertEqual(indexer.store.get_item(item["id"])["thumb_url"], again["thumb_url"])
            status, headers, cached = self.request(again["thumb_url"])
            self.assertEqual((status, cached), (200, body))
            self.assertEqual(headers["Cache-Control"], "private, max-age=31536000, immutable")
        self.assertEqual(before, snapshot(self.workspace))

    def test_small_pictures_are_their_own_thumbnail(self):
        indexer = self.serve()
        for title, content in (("小图", b"\x89PNG small picture"), ("色面", b"small preview")):
            with self.subTest(title=title):
                item = self.item(indexer, title)
                self.assertRegex(item["thumb_url"], rf"^/api/items/{item['id']}/thumb\?v=[a-f0-9]{{12}}$")
                status, headers, body = self.request(item["thumb_url"])
                self.assertEqual((status, body), (200, content))
                self.assertEqual(headers["Cache-Control"], "private, max-age=31536000, immutable")
        self.assertFalse((self.config.cache / "item-thumbs").exists())

    def test_the_file_itself_is_sent_when_no_thumbnail_can_be_made(self):
        broken = b"not really a jpeg" * 20_000
        write(self.workspace / "素材/场景/坏图.jpg", broken)
        indexer = self.serve()
        item = self.item(indexer, "坏图")
        with patch("spt.server.covers.build") as maker:   # makes nothing
            status, headers, body = self.request(item["thumb_url"])
            self.assertEqual((status, body), (200, broken))
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertEqual(self.request(item["thumb_url"])[2], broken)
        self.assertEqual(maker.call_count, 1)   # a failure is remembered, not retried per card
        self.assertEqual(self.item(indexer, "坏图")["thumb_url"], f"/api/items/{item['id']}/thumb")

    def test_items_without_a_picture_have_no_thumbnail(self):
        indexer = self.serve()
        record = self.item(indexer, "笔记")
        self.assertIsNone(record["thumb_url"])
        self.assertEqual(self.request(f"/api/items/{record['id']}/thumb")[0], 404)
        self.assertEqual(self.request("/api/items/" + "0" * 20 + "/thumb")[0], 404)
        self.assertEqual(self.request(f"/api/items/{record['id']}/other")[0], 404)

    @unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg to make a test clip")
    def test_videos_get_a_poster_frame(self):
        clip = self.workspace / "素材/场景/片段.mp4"
        subprocess.run([shutil.which("ffmpeg"), "-nostdin", "-loglevel", "error", "-f", "lavfi",
                        "-i", "testsrc=size=960x540:rate=10", "-t", "1.5", "-pix_fmt", "yuv420p",
                        str(clip)], capture_output=True, check=True)
        indexer = self.serve()
        item = self.item(indexer, "片段")
        self.assertEqual(item["thumb_url"], f"/api/items/{item['id']}/thumb")
        status, headers, body = self.request(item["thumb_url"])
        self.assertEqual((status, headers["Content-Type"]), (200, "image/jpeg"))
        self.assertTrue(body.startswith(b"\xff\xd8"))   # a JPEG frame, not the video
        self.assertRegex(self.item(indexer, "片段")["thumb_url"], r"\?v=[a-f0-9]{12}$")


def cover_workspace(root: Path) -> None:
    named = root / "运营/2026-10-01-AK-有封面"
    write(named / "封面.png", b"named")
    write(named / "01.png", b"root picture")
    write(named / "V1/01_x.jpg", b"version picture")
    natural = root / "运营/2026-10-02-AK-版本图"
    for name in ("10_c.jpg", "2_a.jpg", "9_b.jpg", "参考_z.jpg"):
        write(natural / "V1" / name, name.encode())
    write(natural / "V1/回片1.mp4", b"video")
    write(natural / "V1/正文.txt", "词")
    adopted = root / "运营/2026-10-03-AK-定稿"
    write(adopted / "V1/01_first.jpg", b"v1")
    write(adopted / "V2/01_second.jpg", b"v2")
    write(adopted / "发布包.md", "# 发布包 · 定稿 V1\n")
    newest = root / "运营/2026-10-04-AK-最新"
    write(newest / "V1/01_first.jpg", b"v1")
    write(newest / "V2/01_second.jpg", b"v2")
    # the newest version has no picture: the root is next, not an older version
    root_picture = root / "运营/2026-10-05-AK-根目录"
    write(root_picture / "V1/01_old.jpg", b"old")
    write(root_picture / "V2/正文.txt", "只有词")
    write(root_picture / "成图_10.png", b"ten")
    write(root_picture / "成图_2.png", b"two")
    write(root_picture / ".hidden_1.png", b"hidden")
    write(root_picture / "成片.mp4", b"video")          # a root picture beats a video frame
    none = root / "运营/2026-10-06-示例创作者-没有图"
    write(none / "记录.md", "# 记录")
    write(none / "资料/支持资料/图.png", b"not in the root")
    write(root / "运营/2026-10-07-AK-只有视频/成片.mp4", b"video")


class CoverFallbackTests(unittest.TestCase):
    """封面.* first; else a picture of the version that stands for the work; else one
    from the root; videos still give a frame. Which rule applied is cover_rule."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.config = fixture_config(Path(cls.temporary.name))
        cover_workspace(cls.config.workspace)
        cls.before = snapshot(cls.config.workspace)
        cls.indexer = Indexer(cls.config)

        def frame(source, target, owner, cache):           # stands in for ffmpeg
            target.write_bytes(b"frame of " + source.name.encode())
        with patch("spt.server.covers.build", side_effect=frame) as cls.maker:
            cls.indexer.reindex()
        cls.works = {work["title"]: work for work in cls.indexer.store.list_works()}
        cls.server = Server(cls.indexer)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)
        cls.temporary.cleanup()

    def request(self, path: str) -> tuple[int, bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        connection.request("GET", path)
        response = connection.getresponse()
        result = response.status, response.read()
        connection.close()
        return result

    def test_natural_order(self) -> None:
        names = ["10_c.jpg", "9_b.jpg", "2_a.jpg", "01_x.jpg", "1_y.jpg", "B.png", "a.png"]
        self.assertEqual(sorted(names, key=natural_key),
                         ["01_x.jpg", "1_y.jpg", "2_a.jpg", "9_b.jpg", "10_c.jpg", "a.png", "B.png"])

    def test_which_rule_found_each_cover(self) -> None:
        found = {title: (work["cover_source"], work["cover_rule"])
                 for title, work in self.works.items()}
        self.assertEqual(found, {
            "有封面": ("封面.png", "封面"),
            "版本图": ("V1/2_a.jpg", "版本图"),
            "定稿": ("V1/01_first.jpg", "版本图"),
            "最新": ("V2/01_second.jpg", "版本图"),
            "根目录": ("成图_2.png", "根目录图"),
            "没有图": (None, None),
            "只有视频": (None, "视频抽帧")})
        self.assertEqual(self.works["定稿"]["current_version"], "V1")
        self.assertIsNone(self.works["没有图"]["cover"])
        self.assertEqual(self.works["没有图"]["issues"], [])
        self.assertRegex(self.works["只有视频"]["cover"], r"/cover\?v=[a-f0-9]{12}$")
        self.assertEqual(self.maker.call_count, 1)        # only the video needed a tool
        self.assertEqual(snapshot(self.config.workspace), self.before)

    def test_fallback_covers_are_served_and_exported(self) -> None:
        status, body = self.request(self.works["版本图"]["cover"])
        self.assertEqual((status, body), (200, b"2_a.jpg"))
        status, body = self.request(self.works["根目录"]["cover"])
        self.assertEqual((status, body), (200, b"two"))
        status, body = self.request(self.works["只有视频"]["cover"])
        self.assertEqual((status, body), (200, "frame of 成片.mp4".encode()))
        self.assertEqual(self.request(f"/api/works/{self.works['没有图']['id']}/cover")[0], 404)
        detail = self.indexer.store.detail(self.works["版本图"]["id"])["work"]
        self.assertEqual(detail["cover_rule"], "版本图")
        rows = self.indexer.store.export_works()
        self.assertEqual(next(row["cover_source"] for row in rows if row["title"] == "版本图"),
                         "V1/2_a.jpg")

    @unittest.skipUnless(shutil.which("sips"), "needs the macOS sips tool")
    def test_a_big_fallback_picture_gets_the_same_thumbnail(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            config = fixture_config(Path(folder))
            work = config.workspace / "运营/2026-10-08-AK-大图"
            source = Path(folder) / "big.bmp"
            bitmap(source, 1200, 900)
            (work / "V1").mkdir(parents=True)
            subprocess.run(["sips", "-s", "format", "jpeg", str(source), "--out",
                            str(work / "V1/01_big.jpg")], capture_output=True, check=True)
            before = snapshot(config.workspace)
            with patch("spt.server.covers.SMALL_COVER", 0):
                indexer = Indexer(config)
                indexer.reindex()
            [work_row] = indexer.store.list_works()
            self.assertEqual((work_row["cover_source"], work_row["cover_rule"]),
                             ("V1/01_big.jpg", "版本图"))
            self.assertRegex(work_row["cover"], r"/cover\?v=[a-f0-9]{12}$")
            [thumb] = list((config.cache / "thumbs").glob("*.jpg"))
            self.assertEqual(max(size_of(thumb)), 640)
            self.assertEqual(before, snapshot(config.workspace))

    def test_spt_yaml_cover_stays_in_charge(self) -> None:
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("PyYAML 未安装")
        with tempfile.TemporaryDirectory() as folder:
            config = fixture_config(Path(folder))
            work = config.workspace / "运营/2026-10-09-AK-指定"
            write(work / "封面.png", b"named")
            write(work / "V1/01_x.jpg", b"chosen")
            write(work / "spt.yaml", "cover: V1/01_x.jpg\n")
            indexer = Indexer(config)
            indexer.reindex()
            [row] = indexer.store.list_works()
            self.assertEqual((row["cover_source"], row["cover_rule"]), ("V1/01_x.jpg", "spt.yaml"))


if __name__ == "__main__":
    unittest.main()
