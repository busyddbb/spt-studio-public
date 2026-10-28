"""Atomic, repeatable indexing of an explicitly configured directory."""
from __future__ import annotations
import datetime as dt
import dataclasses
import json
import sys
import threading
from pathlib import Path
from typing import Any

from .config import DEFAULT_WORKSPACE, Config, share_mode, workspace_source
from .cache import safe_cache_path
from .clients import Clients, client_groups, client_summary
from .covers import ITEM_THUMBS, item_thumbs, thumbnail
from .events import Events
from .facts import infer_status
from .files import WINDOWS, FileError, move_to_trash
from .library import scan_library, work_items
from .metrics import scan_accounts
from .models import Work
from .notes import Notes
from .scan import choose_cover, scan_work, scan_works
from .store import Store

SPT_ROOT = Path(__file__).resolve().parents[1]
GUIDE_TEMPLATE = SPT_ROOT / "templates" / "工作区-README.md"
GUIDE_LIMIT = 512 * 1024


class Indexer:
    def __init__(self, config: Config, events: Events | None = None) -> None:
        self.config = config
        self.workspace = config.resolved_workspace
        if config.cache.resolve().is_relative_to(self.workspace):
            raise ValueError("缓存目录不能放在作品工作区内")
        safe_cache_path(config.cache, config.database)
        self.store = Store(config.database, config.cache / ITEM_THUMBS)
        self.events = events or Events()
        self.lock = threading.Lock()
        self.clients = Clients()   # 工作区/客户.md, re-read when it changes

    @property
    def notes(self) -> Notes:
        return Notes(self.workspace)

    def set_workspace(self, path: Path) -> dict[str, Any]:
        """Point the index at another folder (already validated) and rebuild."""
        config = dataclasses.replace(self.config, workspace=path)
        if config.cache.resolve().is_relative_to(config.resolved_workspace):
            raise ValueError("缓存目录不能放在作品工作区内")
        with self.lock:
            self.config = config
            self.workspace = config.resolved_workspace
        return self.reindex()

    def reindex(self) -> dict[str, Any]:
        if not self.lock.acquire(blocking=False):
            raise RuntimeError("索引正在重建，请稍后再试")
        try:
            issues: list[str] = []
            works = scan_works(self.workspace, issues)
            for work in works:
                self.prepare(work)
            items = scan_library(self.workspace, self.config.skill_roots,
                                 issues)
            # names only; the thumbnails themselves are made when a card asks
            thumbs = item_thumbs(self.workspace, items + [
                item for work in works for item in work.items])
            # account-level 数据记录: 工作区/数据/账号/<平台>-<账号>/
            accounts = scan_accounts(self.workspace, issues)
            indexed_at = dt.datetime.now(dt.timezone.utc).isoformat()
            self.store.replace(works, indexed_at, items, issues, thumbs, accounts)
            # 客户.md problems are not stored: health reads that file live
            client_issues = self.clients.read(self.workspace)[1]
            result = {"indexed_at": indexed_at, "count": len(works),
                      "items": len(items) + sum(len(work.items)
                                                for work in works),
                      "issues": (issues + client_issues)[:50],
                      "workspace_ready": self.workspace.is_dir()}
            self.events.publish(result)
            return result
        finally:
            self.lock.release()

    def prepare(self, work: Work) -> None:
        """What every scanned work gets before it is stored."""
        infer_status(work)
        choose_cover(work)
        thumbnail(work, self.config.cache)
        work.items = work_items(work, self.workspace)

    # ---- 数据记录: refresh only what a write touched -----------------------------
    def refresh_work(self, identifier: str) -> dict[str, Any]:
        """Re-read one work's folder after a file was added to it; the rest of the
        index stays. Falls back to a full rebuild when the folder is not as indexed."""
        location = self.store.work_location(identifier)
        if location is None:
            return self.reindex()
        if not self.lock.acquire(timeout=10):
            raise RuntimeError("索引正在重建，请稍后再试")
        try:
            try:
                folder = self.work_folder({"relative_path": location["relative_path"],
                                           "path": location["path"]})
            except (FileError, OSError):
                folder = None
            work = scan_work(folder, location["category"], self.workspace) if folder else None
            if work is None or work.id != identifier:
                work = None
            else:
                self.prepare(work)
                self.store.replace_work(work, item_thumbs(self.workspace, work.items))
        finally:
            self.lock.release()
        if work is None:
            return self.reindex()
        result = {"indexed_at": self.store.metadata().get("indexed_at"),
                  "refreshed": identifier, "issues": work.issues[:50]}
        self.events.publish(result)
        return result

    def refresh_accounts(self) -> dict[str, Any]:
        """Re-read 工作区/数据/账号 after an account-level row was written."""
        if not self.lock.acquire(timeout=10):
            raise RuntimeError("索引正在重建，请稍后再试")
        try:
            issues: list[str] = []
            self.store.replace_accounts(*scan_accounts(self.workspace, issues))
        finally:
            self.lock.release()
        result = {"indexed_at": self.store.metadata().get("indexed_at"),
                  "refreshed": "accounts", "issues": issues[:50]}
        self.events.publish(result)
        return result
    # ---- end 数据记录 ------------------------------------------------------------

    def work_folder(self, work: dict[str, Any]) -> Path:
        """The folder of an indexed work, checked to still be what the index saw."""
        workspace = self.workspace
        relative = Path(work["relative_path"])
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise FileError("作品目录不在当前工作区内")
        current = workspace
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise FileError("作品目录已变为符号链接，请核对源目录")
        resolved = current.resolve(strict=True)
        if (str(resolved) != work["path"] or not resolved.is_dir()
                or not resolved.is_relative_to(workspace.resolve())):
            raise FileError("作品根目录与索引记录不一致，请刷新索引")
        return resolved

    def trash_work(self, identifier: str) -> dict[str, Any] | None:
        """Move a work's folder to the system Trash and take it out of the index.

        None when the index does not know the id. Subscribers get the same
        index_updated event a rebuild sends, so open pages refresh at once.
        """
        if not self.lock.acquire(blocking=False):
            raise RuntimeError("索引正在重建，请稍后再试")
        try:
            detail = self.store.detail(identifier)
            if detail is None:
                return None
            trashed = move_to_trash(self.work_folder(detail["work"]))
            self.store.delete_work(identifier)
            library, metadata = self.store.library(all_versions=True), self.store.metadata()
            self.events.publish({
                "indexed_at": metadata.get("indexed_at"), "count": library["works"],
                "items": sum(kind["count"] for kind in library["kinds"].values()),
                "issues": json.loads(metadata.get("issues") or "[]")[:50],
                "workspace_ready": self.workspace.is_dir(), "trashed": identifier})
            return {"id": identifier, "trashed": trashed.name}
        finally:
            self.lock.release()

    def guide(self) -> dict[str, Any]:
        """The storage guide people read: 工作区/README.md, else the bundled template."""
        for path, shown in ((self.workspace / "README.md", "工作区/README.md"),
                            (GUIDE_TEMPLATE, "spt/templates/工作区-README.md")):
            try:
                if path.is_symlink() or not path.is_file() or path.stat().st_size > GUIDE_LIMIT:
                    continue
                return {"markdown": path.read_text(encoding="utf-8"), "path": shown}
            except (OSError, UnicodeDecodeError):
                continue
        return {"markdown": "", "path": None}

    def health(self) -> dict[str, Any]:
        library = self.store.library()
        metadata = self.store.metadata()
        clients, client_issues = self.clients.read(self.workspace)
        return {"app": "spt", "version": "0.2.0",
            "workspace_path": str(self.config.workspace),
            "workspace_resolved": str(self.workspace),
            "workspace_ready": self.workspace.is_dir(),
            "workspace_source": workspace_source(),
            "workspace_default": str(DEFAULT_WORKSPACE),
            # true only in a copy made by 打包分享 (spt/settings.share.json)
            "share": share_mode(),
            "indexed_at": metadata.get("indexed_at"),
            "issues": json.loads(metadata.get("issues") or "[]") + client_issues,
            "counts": {"works": library["works"], **{
                kind: entry["count"] for kind, entry in library["kinds"].items()}},
            # 工作区/客户.md rows in file order, then client codes only works know;
            # the groups (类型 column) in file order, 自己/客户 when the file has none
            "clients": client_summary(clients, self.store.client_counts()),
            "client_groups": client_groups(clients),
            "skill_roots": [str(path) for _, path in self.config.skill_roots],
            "spt_root": str(SPT_ROOT),
            # 设置 › Agent 接入 shows Windows commands (py -3 -m …) instead of spt/bin/*
            "platform": "windows" if WINDOWS else "mac" if sys.platform == "darwin" else "other",
            "capabilities": {"index": True, "readonly": True, "publish": False,
                             "library": True, "export": True, "guide": True, "watch": True,
                             "notes": True, "workspace_setting": True,
                             "metrics": True, "agents": False,
                             "account_login": False}}
