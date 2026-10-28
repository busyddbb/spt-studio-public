"""Notice changes in 工作区 and rebuild the index, so the UI updates without 刷新.

No third-party watcher: every few seconds the workspace tree is walked and a cheap
signature (paths, sizes, modification times) is compared with the previous one. A
change that is still settling (a file being copied in) is waited out: the index is
rebuilt only once two consecutive looks agree.
"""
from __future__ import annotations
import os
import threading
import time
import zlib
from pathlib import Path

INTERVAL = 2.0
ENTRY_LIMIT = 200_000


def signature(root: Path) -> int:
    """Checksum of every visible path with its size and mtime. Symlinks and dotfiles are skipped."""
    total = 0
    count = 0
    for folder, folders, files in os.walk(root, followlinks=False):
        folders[:] = sorted(name for name in folders if not name.startswith("."))
        for name in files:
            if name.startswith("."):
                continue
            try:
                status = os.lstat(os.path.join(folder, name))
            except OSError:
                continue
            key = f"{folder}/{name}:{status.st_size}:{status.st_mtime_ns}".encode()
            total = (total + zlib.crc32(key)) & 0xFFFFFFFF
            count += 1
            if count >= ENTRY_LIMIT:
                return total
    return total


class Watcher:
    def __init__(self, indexer, interval: float = INTERVAL) -> None:
        self.indexer = indexer
        self.interval = interval
        self.stop = threading.Event()
        self.last_seen: int | None = None
        self.pending: int | None = None
        self.indexed_at = 0.0

    def start(self) -> "Watcher":
        thread = threading.Thread(target=self.run, name="spt-watcher", daemon=True)
        thread.start()
        return self

    def check(self) -> bool:
        """One look. Returns True when the index was rebuilt."""
        try:
            current = signature(self.indexer.workspace)
        except OSError:
            return False
        if self.last_seen is None:
            self.last_seen = current
            return False
        if current == self.last_seen:
            self.pending = None
            return False
        if self.pending != current:          # still changing: look again next time
            self.pending = current
            return False
        try:
            self.indexer.reindex()
        except RuntimeError:                 # a manual reindex is running; retry later
            return False
        self.last_seen = current
        self.pending = None
        self.indexed_at = time.time()
        return True

    def run(self) -> None:
        while not self.stop.wait(self.interval):
            self.check()
