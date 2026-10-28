"""Mount the new workbench on the native app's existing trusted origin."""
from __future__ import annotations

import json
import mimetypes
import sqlite3
import sys
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spt.server.api import Handler as WorkspaceHandler
from spt.server.config import default_config
from spt.server.files import FileError, contained, read_text
from spt.server.indexer import Indexer
from spt.server.watcher import Watcher
from spt.server.security import allowed_host, allowed_origin

if __package__:
    from . import legacy_metrics
else:
    import legacy_metrics

UI = ROOT / "spt" / "ui"
LEGACY = ROOT / "app" / "static"
_INDEX_LOCK = threading.Lock()


@dataclass
class MountedServer:
    indexer: Indexer
    server_port: int


class MountedRequest(WorkspaceHandler):
    """Reuse SPT routes without opening another listener or socket."""

    def __init__(self, owner: BaseHTTPRequestHandler, indexer: Indexer) -> None:
        self.__dict__.update(owner.__dict__)
        self.server = MountedServer(indexer, owner.server.server_port)
        self.path = owner.path.replace("/api/spt/", "/api/", 1)
        self.protocol_version = owner.protocol_version

    def api_route(self, path: str, query: dict[str, list[str]],
                  head: bool) -> None:
        if path == "/api/dashboard":
            self.send_json(200, dashboard_context(self.server.indexer), head)
        else:
            super().api_route(path, query, head)


def legacy_accounts() -> list[dict[str, str]]:
    """Read public account identity columns plus the display name and brand.

    Nothing else of the payload (notes, status) leaves the database.
    """
    if __package__:
        from . import core
    else:
        import core

    named = ("CASE WHEN json_valid(payload) THEN json_extract(payload,'$.%s')"
             " END")
    query = ("SELECT id,platform,handle," + named % "name" + ","
             + named % "brand" + " FROM accounts")
    return [dict(zip(("id", "platform", "handle", "name", "brand"), row))
            for row in legacy_metrics.read_rows(core.DB.resolve(), query)]


# Dashboard platform ids → the ids 账号档案 stores.
LEGACY_PLATFORMS = legacy_metrics.LEGACY_PLATFORMS
normalized_platform = legacy_metrics.legacy_platform


def dashboard_context(indexer: Indexer | None = None) -> dict[str, Any]:
    from spt.server.dashboard import dashboard_snapshot
    from spt.server.dashboard_links import enrich_posts
    from spt.server.metrics_dashboard import merge_workspace_metrics

    snapshot = dashboard_snapshot()
    if indexer is not None:
        # the works' own 数据记录 (工作区/<专业>/<作品>/数据, 工作区/数据/账号)
        merge_workspace_metrics(snapshot, indexer.store,
                                indexer.clients.read(indexer.workspace)[0])
    identities = legacy_accounts()
    accounts = snapshot.setdefault("accounts", [])
    matched: set[str] = set()
    for account in accounts:
        handles = {account.get("handle"), account.get("profile_url")}
        platform = normalized_platform(account.get("platform", ""))
        matches = [item for item in identities
                   if item["platform"] == platform
                   and item["handle"] in handles]
        if not matches and not account.get("handle"):
            # 没有公开 handle 的平台（Google 商家资料、Yelp）按客户名对上，
            # 否则同一客户在平台入口里会出现第二组（用户 2026-10-23）。
            brand = str(account.get("brand") or "").strip().lower()
            matches = [item for item in identities
                       if item["platform"] == platform and item["id"] not in matched
                       and brand and str(item.get("brand") or "").strip().lower() == brand]
        account["legacy_account_id"] = (matches[0]["id"]
                                        if len(matches) == 1 else None)
        matched.update(item["id"] for item in matches)
    # 账号档案 entries that no project source describes still get a card.
    accounts.extend(legacy_metrics.registry_account(item)
                    for item in identities if item["id"] not in matched)
    # CSV imports and 发布记录 numbers from the legacy DB, read-only.
    imported = legacy_metrics.merge(snapshot, identities)
    if imported:
        enrich_posts(imported, ROOT)
    snapshot.setdefault("capabilities", {}).update({
        "legacy_publishing": True, "legacy_base": "/legacy/"})
    return snapshot


def workspace_indexer(owner: BaseHTTPRequestHandler) -> Indexer:
    with _INDEX_LOCK:
        indexer = getattr(owner.server, "workspace_indexer", None)
        if indexer is None:
            indexer = Indexer(default_config(owner.server.server_port))
            indexer.reindex()
            owner.server.workspace_indexer = indexer
            owner.server.workspace_watcher = Watcher(indexer).start()
        return indexer


def json_error(owner: BaseHTTPRequestHandler, status: int, text: str) -> None:
    body = json.dumps({"error": text}, ensure_ascii=False).encode("utf-8")
    send_bytes(owner, status, body, "application/json; charset=utf-8")


def send_bytes(owner: BaseHTTPRequestHandler, status: int, body: bytes,
               mime: str) -> None:
    owner.send_response(status)
    owner.send_header("Content-Type", mime)
    owner.send_header("Content-Length", str(len(body)))
    owner.send_header("Cache-Control", "no-store")
    owner.send_header("X-Content-Type-Options", "nosniff")
    owner.send_header("Content-Security-Policy", "default-src 'self'; "
                      "script-src 'self'; style-src 'self' 'unsafe-inline'; "
                      "img-src 'self' data:; media-src 'self'; "
                      "connect-src 'self'; base-uri 'self'; "
                      "frame-ancestors 'self'; form-action 'self'")
    owner.end_headers()
    if owner.command != "HEAD":
        owner.wfile.write(body)


def redirect(owner: BaseHTTPRequestHandler, target: str) -> None:
    owner.send_response(302)
    owner.send_header("Location", target)
    owner.send_header("Content-Length", "0")
    owner.send_header("Cache-Control", "no-store")
    owner.end_headers()


def workspace_asset(owner: BaseHTTPRequestHandler, path: str) -> None:
    relative = path.removeprefix("/workspace/") or "index.html"
    target = contained(UI, relative)
    if target.suffix == ".html":
        text = read_text(target)
        text = text.replace('data-api-base="/api"',
                            'data-api-base="/api/spt"')
        text = text.replace('data-legacy-base=""',
                            'data-legacy-base="/legacy/"')
        body = text.encode("utf-8")
    else:
        if target.stat().st_size > 2 * 1024 * 1024:
            raise FileError("界面资源超过本地读取限制")
        body = target.read_bytes()
    mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    if mime.startswith("text/") or mime in {"application/javascript"}:
        mime += "; charset=utf-8"
    send_bytes(owner, 200, body, mime)


def mount_api(owner: BaseHTTPRequestHandler) -> None:
    request = MountedRequest(owner, workspace_indexer(owner))
    try:
        request.dispatch(head=owner.command == "HEAD",
                         post=owner.command == "POST",
                         unsupported=owner.command not in
                         {"GET", "HEAD", "POST"})
    finally:
        owner.close_connection = request.close_connection


def handle(owner: BaseHTTPRequestHandler) -> bool:
    path = urlsplit(owner.path).path
    if not (path in {"/", "/index.html", "/workspace", "/legacy"}
            or path.startswith(("/workspace/", "/api/spt/", "/legacy/"))):
        return False
    port = owner.server.server_port
    if (not allowed_host(owner.headers.get("Host"), port)
            or not allowed_origin(owner.headers.get("Origin"), port)
            or owner.headers.get("Sec-Fetch-Site") == "cross-site"):
        json_error(owner, 403, "只允许本机同源访问")
        return True
    try:
        if path.startswith("/api/spt/"):
            mount_api(owner)
        elif owner.command not in {"GET", "HEAD"}:
            json_error(owner, 405, "界面资源只接受读取请求")
        elif path in {"/", "/index.html", "/workspace"}:
            redirect(owner, "/workspace/")
        elif path == "/legacy":
            redirect(owner, "/legacy/")
        elif path.startswith("/legacy/"):
            legacy_asset(owner, path)
        else:
            workspace_asset(owner, path)
    except (BrokenPipeError, ConnectionResetError):
        owner.close_connection = True
    except (FileError, ValueError):
        json_error(owner, 403, "文件路径不在工作台范围内")
    except FileNotFoundError:
        json_error(owner, 404, "页面或文件不存在")
    except (OSError, sqlite3.Error, RuntimeError, ImportError):
        json_error(owner, 503, "工作台暂不可用，可从原发布入口继续操作")
    return True


def legacy_asset(owner: BaseHTTPRequestHandler, path: str) -> None:
    relative = path.removeprefix("/legacy/") or "index.html"
    target = contained(LEGACY, relative)
    if target.stat().st_size > 2 * 1024 * 1024:
        raise FileError("界面资源超过本地读取限制")
    mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    if mime.startswith("text/") or mime == "application/javascript":
        mime += "; charset=utf-8"
    send_bytes(owner, 200, target.read_bytes(), mime)
