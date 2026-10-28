"""Bounded file access and path containment."""
from __future__ import annotations
import datetime as dt
import errno
import hashlib
import mimetypes
import os
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator

from .models import Media

TEXT_LIMIT = 2 * 1024 * 1024
HASH_LIMIT = 64 * 1024 * 1024
CHUNK_SIZE = 64 * 1024
TRASH = ".Trash"          # the Finder's Trash of the home volume
VOLUME_TRASHES = ".Trashes"   # on another volume: <volume>/.Trashes/<uid>/
WINDOWS = os.name == "nt"
# Flags Windows does not have are 0 there; the explicit is_link() checks below
# keep refusing links where O_NOFOLLOW was the guard on macOS.
NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
NONBLOCK = getattr(os, "O_NONBLOCK", 0)
BINARY = getattr(os, "O_BINARY", 0)    # Windows: no newline or Ctrl-Z translation
LINK_TAGS = {getattr(stat, "IO_REPARSE_TAG_SYMLINK", 0xA000000C),
             getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003)}
# Shell file operation (Windows Recycle Bin)
FO_DELETE = 3
FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 0x4, 0x10, 0x40, 0x400

# Windows takes MIME types from the registry, where .js is sometimes text/plain and
# browsers then refuse the UI's scripts (nosniff). Pin what the Mac answers.
WINDOWS_TYPES = {".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css",
                 ".html": "text/html", ".svg": "image/svg+xml", ".json": "application/json",
                 ".webp": "image/webp", ".woff2": "font/woff2", ".png": "image/png",
                 ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
                 ".heic": "image/heic", ".mp4": "video/mp4", ".mov": "video/quicktime",
                 ".m4v": "video/x-m4v", ".webm": "video/webm", ".mkv": "video/x-matroska",
                 ".ico": "image/x-icon", ".webmanifest": "application/manifest+json"}


def pin_mime_types(windows: bool = WINDOWS) -> None:
    if windows:
        mimetypes.init()
        for suffix, kind in WINDOWS_TYPES.items():
            mimetypes.add_type(kind, suffix)


pin_mime_types()


class FileError(ValueError):
    """A source path cannot safely be accessed."""


def is_link(path: Path) -> bool:
    """A symbolic link, or on Windows a symlink or junction (OneDrive placeholders are fine)."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(info.st_mode):
        return True
    return getattr(info, "st_reparse_tag", 0) in LINK_TAGS


def write_atomic(path: Path, text: str) -> None:
    """Write a text file so that readers see the old file or the new one, never half."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def free_name(folder: Path, name: str, directory: bool) -> Path:
    """<name> in folder, else <stem> 2<suffix>, <stem> 3<suffix>… — the first not taken."""
    stem, suffix = (name, "") if directory else os.path.splitext(name)
    candidate = folder / name
    number = 2
    while os.path.lexists(candidate):
        candidate = folder / f"{stem} {number}{suffix}"
        number += 1
    return candidate


def volume_root(path: Path) -> Path:
    """The top folder of the volume `path` is on (where its .Trashes lives)."""
    current = Path(os.path.abspath(path)).parent
    device = os.stat(current).st_dev
    while current.parent != current and os.stat(current.parent).st_dev == device:
        current = current.parent
    return current


def file_operation(path: Path) -> tuple[object, object]:
    """SHFILEOPSTRUCTW sending `path` to the Recycle Bin, and the buffer it points at.

    pFrom is a list of paths ending in two NULs; the buffer has to outlive the call.
    """
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _pack_ = 1 if ctypes.sizeof(ctypes.c_void_p) == 4 else 8   # shellapi.h: pshpack1 on Win32
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT),
                    ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                    ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

    buffer = ctypes.create_unicode_buffer(os.path.abspath(path) + "\0")   # + the buffer's own NUL
    operation = SHFILEOPSTRUCTW()
    operation.wFunc = FO_DELETE
    operation.pFrom = ctypes.cast(buffer, wintypes.LPCWSTR)
    operation.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
    return operation, buffer


def recycle(path: Path, shell32: object | None = None) -> Path:
    """Windows: send a file or folder to the Recycle Bin. Returns the original path
    (the bin keeps it under that name); raises FileError when the shell refuses."""
    import ctypes
    operation, buffer = file_operation(path)
    shell32 = shell32 if shell32 is not None else ctypes.windll.shell32   # type: ignore[attr-defined]
    result = shell32.SHFileOperationW(ctypes.byref(operation))
    del buffer
    if result != 0 or operation.fAnyOperationsAborted:
        raise FileError(f"放不进回收站：错误代码 {result:#x}" if result else "放不进回收站：操作被取消")
    if os.path.lexists(path):
        raise FileError("放不进回收站：文件还在原处")
    return Path(path)


def move_to_trash(path: Path, trash_dir: Path | None = None) -> Path:
    """Move a file or folder into the system Trash and return where it went.

    Nothing is ever deleted: the Finder's Trash keeps it until the person empties
    it. A name already in the Trash gets ` 2`, ` 3`… before its suffix. A symbolic
    link is moved as the link itself; what it points to is never followed or
    touched. When the file lives on another volume (os.rename answers EXDEV) it
    goes to that volume's own .Trashes/<uid>/, as the Finder does. `trash_dir`
    is for tests only: it stands in for ~/.Trash. On Windows it goes to the
    Recycle Bin instead (see recycle()).
    """
    source = Path(path)
    if not os.path.lexists(source):
        raise FileNotFoundError(source)
    if WINDOWS and trash_dir is None:
        return recycle(source)
    directory = source.is_dir() and not source.is_symlink()
    trash = trash_dir if trash_dir is not None else Path.home() / TRASH
    try:
        trash.mkdir(mode=0o700, parents=True, exist_ok=True)
        target = free_name(trash, source.name, directory)
        os.rename(source, target)
        return target
    except OSError as error:
        if error.errno != errno.EXDEV:
            raise FileError(f"放不进废纸篓：{error.strerror or error}") from error
    try:
        trash = volume_root(source) / VOLUME_TRASHES / str(os.getuid())   # type: ignore[attr-defined]
        trash.mkdir(mode=0o700, parents=True, exist_ok=True)
        target = free_name(trash, source.name, directory)
        os.rename(source, target)
        return target
    except OSError as error:
        raise FileError(f"放不进废纸篓：{error.strerror or error}") from error


def contained(root: Path, value: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute() or "\x00" in value or ".." in candidate.parts:
        raise FileError("文件路径必须是作品内的相对路径")
    resolved = (root / candidate).resolve(strict=True)
    if not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
        raise FileError("文件不在当前作品目录内")
    return resolved


def safe_files(root: Path, recursive: bool = False) -> list[Path]:
    iterator = root.rglob("*") if recursive else root.iterdir()
    result = []
    for path in iterator:
        hidden = any(part.startswith(".")
                     for part in path.relative_to(root).parts)
        if hidden or path.is_symlink():
            continue
        if path.is_file() and path.resolve().is_relative_to(root.resolve()):
            result.append(path)
    return sorted(result, key=lambda path: path.name.casefold())


def timestamp(path: Path) -> str:
    return dt.datetime.fromtimestamp(path.stat().st_mtime,
                                     dt.timezone.utc).isoformat()


def read_text(path: Path) -> str:
    if path.stat().st_size > TEXT_LIMIT:
        raise FileError("文本超过2MiB，未将其读入索引")
    with path.open("rb") as source:
        content = source.read(TEXT_LIMIT + 1)
    if len(content) > TEXT_LIMIT:
        raise FileError("文本在读取期间增长，索引已停止")
    return content.decode("utf-8-sig", errors="replace")


def media_fact(path: Path, work: Path, role: str,
               order: int = 0, version: str = "") -> Media:
    return Media(path.name, path.relative_to(work).as_posix(), role,
                 mimetypes.guess_type(path.name)[0] or
                 "application/octet-stream", path.stat().st_size,
                 timestamp(path), order, version)


def digest(path: Path) -> str | None:
    if path.stat().st_size > HASH_LIMIT:
        return None
    checksum = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(CHUNK_SIZE), b""):
            checksum.update(block)
    return checksum.hexdigest()


def stream_slice(source: BinaryIO, target: BinaryIO,
                 remaining: int) -> None:
    while remaining:
        block = source.read(min(CHUNK_SIZE, remaining))
        if not block:
            break
        target.write(block)
        remaining -= len(block)


def open_descriptor(root: Path, path: Path) -> int:
    relative = path.relative_to(root)
    if not relative.parts or ".." in relative.parts:
        raise FileError("文件路径越界")
    if not DIR_FD:
        return open_checked(root, relative)
    flags = os.O_RDONLY | NOFOLLOW
    directory = os.open(root, flags | os.O_DIRECTORY)
    try:
        for part in relative.parts[:-1]:
            child = os.open(part, flags | os.O_DIRECTORY, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(relative.parts[-1], flags | NONBLOCK,
                             dir_fd=directory)
    finally:
        os.close(directory)
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise FileError("只允许读取普通作品文件")
    return descriptor


# Opening each folder relative to the last one (no link can be swapped in on the
# way) needs dir_fd and O_DIRECTORY; Windows has neither.
DIR_FD = hasattr(os, "O_DIRECTORY") and os.open in os.supports_dir_fd


def open_checked(root: Path, relative: Path) -> int:
    """open_descriptor without dir_fd: every step from root down is checked to be
    no link, then the file is opened and must still be a plain file inside root."""
    current = Path(root)
    for part in ("",) + relative.parts:
        current = current / part if part else current
        if is_link(current):
            raise FileError("文件路径包含符号链接")
    descriptor = os.open(current, os.O_RDONLY | BINARY)
    try:
        inside = Path(os.path.realpath(current)).is_relative_to(Path(os.path.realpath(root)))
        if not inside or not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise FileError("只允许读取普通作品文件")
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


@contextmanager
def open_source(root: Path, path: Path) -> Iterator[BinaryIO]:
    try:
        descriptor = open_descriptor(root, path)
    except FileNotFoundError:
        raise
    except (OSError, ValueError) as error:
        raise FileError("文件路径已变化或包含不可访问的符号链接") from error
    with os.fdopen(descriptor, "rb") as source:
        yield source
