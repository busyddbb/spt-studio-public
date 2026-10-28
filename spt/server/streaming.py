"""Single-range file streaming from a retained, safely opened descriptor."""
from __future__ import annotations
import mimetypes
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .files import open_source, stream_slice


class RangeError(ValueError):
    """An HTTP byte range cannot be satisfied."""


def byte_range(header: str | None, size: int) -> tuple[int, int, bool]:
    if header is None:
        return 0, max(size - 1, -1), False
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", header.strip())
    if not match or not any(match.groups()) or size == 0:
        raise RangeError("不支持该文件字节范围")
    first, last = match.groups()
    if not first:
        length = int(last)
        if length == 0:
            raise RangeError("文件范围长度必须大于零")
        return max(0, size - length), size - 1, True
    start, end = int(first), min(int(last), size - 1) if last else size - 1
    if start >= size or end < start:
        raise RangeError("文件字节范围超出文件大小")
    return start, end, True


def file_headers(handler: Any, path: Path, start: int, end: int, size: int,
                 partial: bool, source_file: bool, cache_seconds: int = 0) -> None:
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    handler.send_response(206 if partial else 200)
    handler.send_header("Content-Type", mime)
    handler.send_header("Content-Length", str(max(end - start + 1, 0)))
    handler.send_header("Accept-Ranges", "bytes")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Cache-Control", f"private, max-age={cache_seconds}, immutable"
                        if cache_seconds else "no-store")
    if source_file:
        safe_types = ("image/", "video/", "audio/",
                      "text/plain", "text/markdown")
        disposition = "inline" if mime.startswith(safe_types) else "attachment"
        filename = "; filename*=UTF-8''" + quote(path.name)
        handler.send_header("Content-Disposition", disposition + filename)
        handler.send_header("Content-Security-Policy",
                            "sandbox; default-src 'none'")
    if partial:
        handler.send_header("Content-Range", f"bytes {start}-{end}/{size}")
    handler.end_headers()


def send_file(handler: Any, path: Path, head: bool = False,
              source_file: bool = False, anchor: Path | None = None,
              cache_seconds: int = 0) -> None:
    with open_source(anchor or path.parent, path) as source:
        size = os.fstat(source.fileno()).st_size
        try:
            start, end, partial = byte_range(handler.headers.get("Range"),
                                             size)
        except RangeError as error:
            handler.send_json(416, {"error": str(error)}, head,
                              {"Content-Range": f"bytes */{size}"})
            return
        file_headers(handler, path, start, end, size, partial, source_file,
                     cache_seconds)
        if not head:
            source.seek(start)
            stream_slice(source, handler.wfile, max(end - start + 1, 0))
