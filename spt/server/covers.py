"""Generate bounded thumbnails outside all source work directories.

Covers are shrunk to 640 px so the asset grid stays light. ffmpeg is used when it is
installed; otherwise the tools every Mac has: sips for images, Quick Look for videos.
Other systems (Windows) use ffmpeg for both, else Pillow for pictures if it is
installed, else no cover.

Library items (素材 pictures and videos, prompt preview images) get the same small
picture in .cache/item-thumbs/. It is made the first time a card asks for it, not
while indexing, so a big library never slows a rebuild down.
"""
from __future__ import annotations
import hashlib
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable

from .models import Item, Work
from .cache import safe_cache_path
from .files import contained

IMAGES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic"}
VIDEOS = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}
SMALL_COVER = 200_000   # bytes; covers this small are served as they are
SIDE = "640"
ITEM_THUMBS = "item-thumbs"
_MAKING = threading.BoundedSemaphore(2)   # item thumbnails made at once; other cards wait
_FAILED: set[str] = set()                 # could not be made this run; show the file instead
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)   # Windows: no console flashing up for ffmpeg


def thumbnail(work: Work, cache: Path) -> None:
    rule = None
    if work.cover_source:
        source = Path(work.path) / work.cover_source
        if source.suffix.lower() not in IMAGES or source.stat().st_size <= SMALL_COVER:
            return
    elif work.finals:
        # no picture anywhere in the work: a frame from the first 成片
        source = Path(work.path) / work.finals[0].path
        rule = "视频抽帧"
    else:
        return
    stat = source.stat()
    identity = f"{work.id}:{source.name}:{stat.st_size}:{stat.st_mtime_ns}"
    # PNG keeps its transparency; everything else becomes JPEG
    suffix = ".png" if source.suffix.lower() == ".png" else ".jpg"
    filename = hashlib.sha256(identity.encode()).hexdigest() + suffix
    target = safe_cache_path(cache, cache / "thumbs" / filename)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.is_file():
        build(source, target, work, cache)
    if target.is_file():
        work.cover_cache = str(target)
        work.cover_rule = work.cover_rule or rule


def on_mac() -> bool:
    return sys.platform == "darwin"


def pillow() -> bool:
    return importlib.util.find_spec("PIL") is not None


def bundled_ffmpeg() -> str | None:
    try:
        import imageio_ffmpeg
        binary = imageio_ffmpeg.get_ffmpeg_exe()
        return binary if Path(binary).is_file() else None
    except (ImportError, OSError, RuntimeError):
        return None


def build(source: Path, target: Path, owner: Any, cache: Path) -> None:
    """Make target from source with the tools this computer has; problems go to owner.issues.

    A video gets a frame from ffmpeg; on a Mac, if that fails, Quick Look tries
    before giving up. sips and Quick Look are only looked for on a Mac.
    """
    mac = on_mac()
    binary = shutil.which("ffmpeg") or bundled_ffmpeg()
    sips = mac and bool(shutil.which("sips"))
    quick = sips and bool(shutil.which("qlmanage"))
    video = source.suffix.lower() in VIDEOS
    if video and binary:
        before = len(owner.issues)
        generate(binary, source, target, owner, cache)
        if not target.is_file() and quick:
            quick_look(source, target, owner, cache)
            if target.is_file():
                del owner.issues[before:]   # Quick Look managed after all
    elif not video and sips:
        shrink(source, target, owner, cache)
    elif video and quick:
        quick_look(source, target, owner, cache)
    elif binary:
        generate(binary, source, target, owner, cache)
    elif not video and not mac and pillow():
        pillow_shrink(source, target, owner, cache)
    elif video:
        owner.issues.append("未找到ffmpeg，封面缓存暂不可用")


def item_thumb(source: Path) -> tuple[str, bool] | None:
    """(cache file name, shown as it is) for an item's picture or video; None otherwise.

    The name changes whenever the file does, so it also versions the URL.
    Pictures no bigger than SMALL_COVER are their own thumbnail and never copied.
    """
    suffix = source.suffix.lower()
    if suffix not in IMAGES | VIDEOS:
        return None
    stat = source.stat()
    identity = f"item:{source}:{stat.st_size}:{stat.st_mtime_ns}"
    name = hashlib.sha256(identity.encode()).hexdigest() + (".png" if suffix == ".png" else ".jpg")
    return name, suffix in IMAGES and stat.st_size <= SMALL_COVER


def item_thumbs(root: Path, items: Iterable[Item]) -> dict[str, tuple[str, bool]]:
    """At index time: the cache name of every picture or video item, by item id."""
    found = {}
    for item in items:
        if not item.file or Path(item.file).suffix.lower() not in IMAGES | VIDEOS:
            continue
        try:
            entry = item_thumb(contained(root, item.file))
        except (OSError, ValueError):
            continue
        if entry:
            found[item.id] = entry
    return found


def make_item_thumb(source: Path, name: str, cache: Path) -> bool:
    """Make .cache/item-thumbs/<name> from source unless it is there; True when it is.

    Runs when a card first asks, at most two at a time, so a full grid never
    starts dozens of sips or ffmpeg processes together.
    """
    folder = safe_cache_path(cache, cache / ITEM_THUMBS)
    target = safe_cache_path(cache, folder / name)
    if target.is_file():
        return True
    if name in _FAILED:
        return False
    folder.mkdir(parents=True, exist_ok=True)
    with _MAKING:
        if not target.is_file():
            build(source, target, SimpleNamespace(issues=[]), cache)
        if not target.is_file():
            _FAILED.add(name)
    return target.is_file()


def run(command: list[str]) -> None:
    subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, check=True, timeout=20, creationflags=NO_WINDOW)


def store(data: bytes, target: Path, cache: Path) -> None:
    """Write through a descriptor held inside the cache, then move into place.

    The file is closed before the move: Windows cannot rename an open file.
    """
    safe_cache_path(cache, target)
    with tempfile.NamedTemporaryFile(dir=target.parent, suffix=target.suffix,
                                     delete=False) as output:
        temporary = Path(output.name)
    try:
        with temporary.open("wb") as writer:
            writer.write(data)
        safe_cache_path(cache, temporary)
        safe_cache_path(cache, target)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def shrink(source: Path, target: Path, work: Any, cache: Path) -> None:
    kind = "png" if target.suffix == ".png" else "jpeg"
    with tempfile.TemporaryDirectory() as folder:
        output = Path(folder) / ("thumb" + target.suffix)
        try:
            run(["sips", "-s", "format", kind, "-Z", SIDE, str(source), "--out", str(output)])
            store(output.read_bytes(), target, cache)
        except (OSError, subprocess.SubprocessError):
            work.issues.append("封面缩略图生成失败；原图未修改")


def pillow_shrink(source: Path, target: Path, work: Any, cache: Path) -> None:
    """Pictures without sips or ffmpeg (Windows with Pillow installed)."""
    try:
        from PIL import Image
        with Image.open(source) as picture:
            picture.thumbnail((int(SIDE), int(SIDE)))
            data = io.BytesIO()
            if target.suffix == ".png":
                picture.save(data, "PNG")
            else:
                picture.convert("RGB").save(data, "JPEG", quality=85)
        store(data.getvalue(), target, cache)
    except Exception:   # Pillow raises its own errors for odd files (HEIC, decompression bombs)
        work.issues.append("封面缩略图生成失败；原图未修改")


def quick_look(source: Path, target: Path, work: Any, cache: Path) -> None:
    with tempfile.TemporaryDirectory() as folder:
        frame = Path(folder) / (source.name + ".png")
        output = Path(folder) / "thumb.jpg"
        try:
            run(["qlmanage", "-t", "-s", SIDE, "-o", folder, str(source)])
            run(["sips", "-s", "format", "jpeg", str(frame), "--out", str(output)])
            store(output.read_bytes(), target, cache)
        except (OSError, subprocess.SubprocessError):
            work.issues.append("封面抽帧失败；原视频未修改")


def generate(binary: str, source: Path, target: Path, work: Any,
             cache: Path) -> None:
    safe_cache_path(cache, target)
    command = [binary, "-nostdin", "-hide_banner", "-loglevel", "error"]
    if source.suffix.lower() in {".mp4", ".mov", ".m4v", ".mkv", ".webm"}:
        command += ["-ss", "0.5"]
    codec = "png" if target.suffix == ".png" else "mjpeg"   # a .png cover keeps its transparency
    command += ["-i", str(source), "-frames:v", "1", "-vf",
                "scale=640:640:force_original_aspect_ratio=decrease",
                "-f", "image2pipe", "-vcodec", codec, "pipe:1"]
    if codec == "mjpeg":
        command[-1:-1] = ["-pix_fmt", "yuvj420p"]
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, suffix=target.suffix,
                                         delete=False) as output:
            temporary = Path(output.name)
            subprocess.run(command, stdin=subprocess.DEVNULL, stdout=output,
                           stderr=subprocess.DEVNULL, check=True, timeout=15,
                           creationflags=NO_WINDOW)
            output.flush()
            if os.fstat(output.fileno()).st_size == 0 and "-ss" in command:
                first_frame = list(command)
                seek = first_frame.index("-ss")
                del first_frame[seek:seek + 2]
                output.seek(0)
                output.truncate()
                subprocess.run(first_frame, stdin=subprocess.DEVNULL, stdout=output,
                               stderr=subprocess.DEVNULL, check=True, timeout=15,
                               creationflags=NO_WINDOW)
                output.flush()
            if os.fstat(output.fileno()).st_size == 0:   # e.g. a clip shorter than the seek
                raise subprocess.SubprocessError("ffmpeg 没有抽出画面")
        # closed before the move: Windows cannot rename an open file
        safe_cache_path(cache, temporary)
        safe_cache_path(cache, target)
        temporary.replace(target)
    except (OSError, subprocess.SubprocessError):
        work.issues.append("封面抽帧失败；原视频未修改")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
