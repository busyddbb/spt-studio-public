"""Reject cache redirection before SQLite or thumbnail writes."""
from __future__ import annotations
from pathlib import Path


def safe_cache_path(root: Path, target: Path) -> Path:
    root = root.absolute()
    target = target.absolute()
    if not target.is_relative_to(root):
        raise RuntimeError("缓存目标不在指定缓存目录内")
    paths = [root]
    current = root
    for part in target.relative_to(root).parts:
        current = current / part
        paths.append(current)
    for path in paths:
        if path.is_symlink():
            raise RuntimeError("缓存目录或目标存在符号链接，已停止写入")
        if path.exists() and path.is_file() and path.stat().st_nlink > 1:
            raise RuntimeError("缓存目标存在硬链接，已停止写入")
    if not target.resolve().is_relative_to(root.resolve()):
        raise RuntimeError("缓存目标解析后越界，已停止写入")
    return target


def safe_database(database: Path) -> None:
    for suffix in ("", "-journal", "-wal", "-shm"):
        safe_cache_path(database.parent,
                        database.with_name(database.name + suffix))
