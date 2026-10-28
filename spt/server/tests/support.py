"""Small synthetic source trees for the read-only index contract."""
from __future__ import annotations
import hashlib
from pathlib import Path

from ..config import Config


def write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


def fixture_config(root: Path) -> Config:
    workspace, ui = root / "source", root / "ui"
    write(ui / "index.html", "<!doctype html><title>多媒体</title>")
    return Config(workspace, root / "cache", ui, 0)


def make_work(root: Path, title: str) -> Path:
    work = root / "运营" / ("2026-10-20-AK-" + title)
    write(work / "封面.jpg", b"fixture cover")
    return work


def populate(root: Path) -> dict[str, Path]:
    paths = {title: make_work(root, title)
             for title in ("轮播", "炒饭", "火光", "环绕")}
    write(paths["环绕"] / "V1/正文.txt", "定格环绕\n保持原样")
    write(paths["环绕"] / "V1/01_菜品.jpg", b"image")
    for version in ("V2", "V3"):
        write(paths["火光"] / version / "正文.txt", version + "提示词")
        write(paths["火光"] / version / "01_菜品.jpg", b"image")
    write(paths["火光"] / "V2/回片1.mp4", b"return")
    write(paths["火光"] / "V3/参考_原片.mp4", b"reference")
    write(paths["火光"] / "火光-发布版-1080p.mp4", b"0123456789")
    write(paths["炒饭"] / "成片_动效版.mp4", b"withdrawn video")
    write(paths["炒饭"] / "V3/正文.txt", "青暖V3制作提示")
    write(paths["炒饭"] / "发布记录.md", rice_record())
    video = b"current carousel video"
    write(paths["轮播"] / "成片_motion_V10.mp4", video)
    write(paths["轮播"] / "发布包.md", carousel_package(video))
    return paths


def rice_record() -> str:
    return ("# 当前采用：青暖调色V3（2026-10-18）\n"
            "此前原版四平台均已撤下；当前四平台公开全文已核对。\n"
            "- Instagram: https://www.instagram.com/reel/current/\n"
            "本版SHA256：" + "0" * 64 + "\n---\n"
            "# 当前更正：13秒版\n"
            "- Instagram: https://www.instagram.com/reel/corrected/\n"
            "---\n# 旧版发布记录\n"
            "- Instagram: https://www.instagram.com/reel/old/\n")


def carousel_package(video: bytes) -> str:
    checksum = hashlib.sha256(video).hexdigest()
    return ("# 发布包 · 四道菜 motion V10\n"
            "## Instagram\nCaption only.\n\n## Google 商家资料\nLocal caption.\n"
            "## 2026-10-20 实际发布结果与归档凭证\n"
            f"SHA-256 `{checksum}`\n"
            "- Instagram: https://www.instagram.com/reel/carousel/；"
            "2026-10-20 00:17 PDT，公开正文与定稿一致。\n"
            "- Google: https://share.google/current；公开正文与定稿一致；"
            "精确发布时间 unknown（约00:24）。\n"
            "归档：`/Users/External/archive/brief.md`\n")


def snapshot(root: Path) -> dict[str, tuple[int, int, str]]:
    return {str(path.relative_to(root)): (
        path.stat().st_size, path.stat().st_mtime_ns,
        hashlib.sha256(path.read_bytes()).hexdigest())
        for path in root.rglob("*") if path.is_file()}
