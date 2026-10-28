"""Same-origin, read-only HTTP surface for the filesystem index."""
from __future__ import annotations
import json
import queue
import re
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from .files import FileError, contained
from .cache import safe_cache_path
from .covers import ITEM_THUMBS, item_thumb, make_item_thumb
from .indexer import Indexer
from .notes import NoteConflict
from .security import allowed_host, allowed_origin
from .streaming import send_file

YEAR = 31_536_000   # seconds a browser may keep a versioned thumbnail


def wants_all_versions(query: dict[str, list[str]]) -> bool:
    """?all_versions=1: lists and counts also carry works' superseded prompts."""
    return query.get("all_versions", [""])[0].lower() in {"1", "true", "yes"}


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, indexer: Indexer) -> None:
        self.indexer = indexer
        super().__init__(("127.0.0.1", indexer.config.port), Handler)


class Handler(BaseHTTPRequestHandler):
    server: Server
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        self.dispatch()

    def do_HEAD(self) -> None:
        self.dispatch(head=True)

    def do_POST(self) -> None:
        self.dispatch(post=True)

    def do_OPTIONS(self) -> None:
        self.dispatch(unsupported=True)

    def do_PUT(self) -> None:
        self.dispatch(unsupported=True)

    def do_DELETE(self) -> None:
        self.dispatch(unsupported=True)

    def do_PATCH(self) -> None:
        self.dispatch(unsupported=True)

    def dispatch(self, head: bool = False, post: bool = False,
                 unsupported: bool = False) -> None:
        try:
            if not self.check_authority(head):
                return
            if unsupported:
                self.close_connection = True
                self.send_json(405, {"error": "本阶段未实现该操作"}, head)
                return
            target = urlsplit(self.path)
            if target.scheme or target.netloc:
                raise FileError("不支持代理形式的请求地址")
            query = parse_qs(target.query, max_num_fields=20)
            path = unquote(target.path)
            if post:
                self.post_route(path, head)
            elif path.startswith("/api/"):
                self.api_route(path, query, head)
            else:
                self.static_route(path, head)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except FileNotFoundError:
            self.send_json(404, {"error": "文件或作品不存在"}, head)
        except FileError as error:
            self.send_json(403, {"error": str(error)}, head)
        except ValueError:
            self.send_json(400, {"error": "请求参数格式不正确"}, head)
        except RuntimeError as error:
            self.send_json(409, {"error": str(error)}, head)
        except (OSError, sqlite3.Error):
            self.send_json(500, {"error": "本地索引暂不可用，请刷新索引"}, head)

    def check_authority(self, head: bool) -> bool:
        port = self.server.server_port
        if (not allowed_host(self.headers.get("Host"), port)
                or not allowed_origin(self.headers.get("Origin"), port)
                or self.headers.get("Sec-Fetch-Site") == "cross-site"):
            self.close_connection = True
            self.send_json(403, {"error": "只允许本机同源访问"}, head)
            return False
        return True

    def send_json(self, status: int, value: Any, head: bool = False,
                  headers: dict[str, str] | None = None) -> None:
        data = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, content in (headers or {}).items():
            self.send_header(name, content)
        self.end_headers()
        if not head:
            self.wfile.write(data)

    def api_route(self, path: str, query: dict[str, list[str]],
                  head: bool) -> None:
        indexer = self.server.indexer
        if path == "/api/health":
            self.send_json(200, indexer.health(), head)
        elif path == "/api/dashboard":
            from .dashboard import dashboard_snapshot
            from .metrics_dashboard import merge_workspace_metrics
            # the project CSVs' snapshot plus the works' own 数据记录
            snapshot = dashboard_snapshot()
            merge_workspace_metrics(snapshot, indexer.store,
                                    indexer.clients.read(indexer.workspace)[0])
            self.send_json(200, snapshot, head)
        elif path == "/api/works":
            keys = [query.get(key, [""])[0]
                    for key in ("category", "status", "q", "client")]
            result = {"works": indexer.store.list_works(*keys)}
            self.send_json(200, result, head)
        elif path == "/api/library":
            summary = indexer.store.library(wants_all_versions(query))
            self.send_json(200, summary, head)
        elif path == "/api/guide":
            self.send_json(200, indexer.guide(), head)
        elif path == "/api/notes":
            self.send_json(200, indexer.notes.snapshot(), head)
        elif path == "/api/items":
            keys = [query.get(key, [""])[0]
                    for key in ("kind", "section", "q", "source")]
            items = indexer.store.list_items(
                *keys, all_versions=wants_all_versions(query),
                client=query.get("client", [""])[0])
            self.send_json(200, {"items": items}, head)
        elif match := re.fullmatch(
                r"/api/items/([a-f0-9]{20})(?:/(file|thumb))?", path):
            self.item_route(match.group(1), match.group(2), query, head)
        elif path == "/api/export":
            self.export_route(query, head)
        elif path in {"/api/accounts", "/api/jobs", "/api/agents"}:
            self.send_json(200, {path.rsplit("/", 1)[1]: []}, head)
        # ---- 数据记录 reads (metrics.py) ----
        elif path == "/api/metrics":
            self.metrics_route(query, head)
        elif path == "/api/metrics/capture":
            from .metrics_capture import queue_for
            self.send_json(200, queue_for(indexer).status(), head)
        elif match := re.fullmatch(r"/api/works/([a-f0-9]{20})/metrics", path):
            if indexer.store.work_location(match.group(1)) is None:
                self.send_json(404, {"error": "作品不存在，请刷新索引"}, head)
            else:
                self.send_json(200, indexer.store.work_metrics(match.group(1)), head)
        # ---- end 数据记录 reads ----
        elif path == "/api/events":
            self.event_stream(head)
        elif match := re.fullmatch(
                r"/api/works/([a-f0-9]{20})(?:/(cover|file))?", path):
            self.work_route(match.group(1), match.group(2), query, head)
        else:
            self.send_json(404, {"error": "接口不存在或尚未接入"}, head)

    WRITES = {"/api/notes/save": "save", "/api/notes/move": "move",
              "/api/notes/remove": "take_down", "/api/notes/restore": "restore",
              "/api/notes/rope": "rope",
              # deletes go to the system Trash (notes.delete / notes.clear_shelf)
              "/api/notes/delete": "delete", "/api/notes/shelf/clear": "clear_shelf"}
    # JSON writes beyond the notes map: (path pattern, Handler method). The method
    # takes (match, value, head) and answers itself; ValueError there is a 400.
    POST_ROUTES = ((re.compile(r"/api/clients/save"), "clients_save_route"),
                   (re.compile(r"/api/works/([a-f0-9]{20})/trash"), "work_trash_route"),
                   # 数据记录 writes, append only (metrics_write.py)
                   (re.compile(r"/api/metrics/(add|retention|analyse|account)"),
                    "metrics_write_route"),
                   # SPT 读数据: requests, the Mac app's claim and what it read
                   (re.compile(r"/api/metrics/capture/(request|claim|result|finish)"),
                    "metrics_capture_route"))

    def post_handler(self, path: str) -> tuple[Any, re.Match[str]] | None:
        for pattern, name in self.POST_ROUTES:
            match = pattern.fullmatch(path)
            if match:
                return getattr(self, name), match
        return None

    def post_route(self, path: str, head: bool) -> None:
        size = int(self.headers.get("Content-Length", "0"))
        limit = 4096 if path == "/api/reindex" else 128 * 1024
        if size < 0 or size > limit or self.headers.get("Transfer-Encoding"):
            self.close_connection = True
            self.send_json(413, {"error": "请求过大"}, head)
            return
        body = self.rfile.read(size) if size else b""
        indexer = self.server.indexer
        if path == "/api/reindex":
            self.send_json(200, indexer.reindex(), head)
            return
        if (path not in self.WRITES and path != "/api/settings/workspace"
                and self.post_handler(path) is None):
            self.send_json(409, {"error": "该写操作尚未接入"}, head)
            return
        # Writes take JSON only: a cross-site form cannot send it without a preflight.
        if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
            self.send_json(415, {"error": "只接受 JSON"}, head)
            return
        value = json.loads(body.decode("utf-8") or "{}")
        if not isinstance(value, dict):
            raise ValueError("请求格式不正确")
        if path == "/api/settings/workspace":
            from .config import save_workspace, workspace_source
            if workspace_source() == "env":
                self.send_json(409, {"error": "工作区由启动参数指定，这里不能改"}, head)
                return
            try:
                folder = save_workspace(value.get("path"))
            except ValueError as error:
                self.send_json(400, {"error": str(error)}, head)
                return
            result = indexer.set_workspace(folder)
            self.send_json(200, {**result, "health": indexer.health()}, head)
            return
        handler = self.post_handler(path)
        try:
            if handler is not None:
                handler[0](handler[1], value, head)
                return
            result = getattr(indexer.notes, self.WRITES[path])(value)
        except NoteConflict as conflict:
            self.send_json(409, {"error": str(conflict), "conflict": True,
                                 "note": conflict.note}, head)
            return
        except ValueError as error:
            self.send_json(400, {"error": str(error)}, head)
            return
        self.send_json(200, result, head)

    # ---- 整理客户 and deletes to the system Trash (POST_ROUTES handlers) ----------
    def clients_save_route(self, match: re.Match[str], value: dict[str, Any],
                           head: bool) -> None:
        """POST /api/clients/save {groups: [{name, clients: [{code, name, color}]}]}.

        Rewrites 工作区/客户.md and answers with the directory as /api/health
        now shows it. A ValueError (bad name, a code that still has works…)
        becomes a 400 with the message in post_route.
        """
        indexer = self.server.indexer
        indexer.clients.save(indexer.workspace, value.get("groups"),
                             indexer.store.client_counts())
        health = indexer.health()
        self.send_json(200, {"clients": health["clients"],
                             "client_groups": health["client_groups"]}, head)

    def work_trash_route(self, match: re.Match[str], value: dict[str, Any],
                         head: bool) -> None:
        """POST /api/works/<id>/trash: the work's folder goes to the Trash, the work out of the index."""
        result = self.server.indexer.trash_work(match.group(1))
        if result is None:
            self.send_json(404, {"error": "作品不存在，请刷新索引"}, head)
            return
        self.send_json(200, result, head)
    # ---- end 整理客户 / Trash ------------------------------------------------------

    # ---- 数据记录 (metrics.py / metrics_write.py) ----------------------------------
    def metrics_route(self, query: dict[str, list[str]], head: bool) -> None:
        """GET /api/metrics?client=&platform=&account=&since=&until=&tag=&q=
        → {posts, tags, accounts}. client takes the 客户.md code or name."""
        from .metrics import client_code
        indexer = self.server.indexer
        filters = {key: query.get(key, [""])[0] for key in
                   ("client", "platform", "account", "since", "until", "tag", "q")}
        filters["client"] = client_code(filters["client"],
                                        indexer.clients.read(indexer.workspace)[0])
        store = indexer.store
        try:
            result = {"posts": store.metrics_posts(**filters),
                      "tags": store.metrics_tags(**filters),
                      "accounts": store.account_metrics(filters["platform"],
                                                        filters["account"])}
        except ValueError as error:
            self.send_json(400, {"error": str(error)}, head)
            return
        self.send_json(200, result, head)

    def metrics_write_route(self, match: re.Match[str], value: dict[str, Any],
                            head: bool) -> None:
        """POST /api/metrics/{add,retention,analyse,account}: append a row or add an
        analysis file (never overwriting), then refresh that work in the index.
        A MetricsError is a 400 (post_route), an unknown or ambiguous work a 404."""
        from . import metrics_write
        writer = {"add": metrics_write.record_observation,
                  "retention": metrics_write.record_retention,
                  "analyse": metrics_write.record_analysis,
                  "account": metrics_write.record_account}[match.group(1)]
        try:
            result = writer(self.server.indexer, value)
        except metrics_write.WorkLookup as error:
            self.send_json(404, {"error": str(error)}, head)
            return
        self.send_json(200, result, head)
    def metrics_capture_route(self, match: re.Match[str], value: dict[str, Any],
                              head: bool) -> None:
        """POST /api/metrics/capture/{request,claim,result,finish} (metrics_capture.py).

        request: the 数据 page or `spt metrics capture` asks for a read.
        claim / result / finish: the Mac app takes the read, posts what each
        account's page showed (written to 表现.csv here), then closes it."""
        from .metrics_capture import queue_for
        queue = queue_for(self.server.indexer)
        action = match.group(1)
        if action == "request":
            result: Any = {"run": queue.request(str(value.get("reason") or "手动")[:20])}
        elif action == "claim":
            result = {"task": queue.claim(auto=value.get("auto") is True,
                                          store=self.server.indexer.store)}
        elif action == "result":
            result = queue.report(self.server.indexer, value)
        else:
            result = queue.finish(value)
        self.send_json(200, result, head)
    # ---- end 数据记录 ----------------------------------------------------------------

    def item_route(self, identifier: str, action: str | None,
                   query: dict[str, list[str]], head: bool) -> None:
        indexer = self.server.indexer
        item = indexer.store.get_item(identifier)
        if item is None:
            self.send_json(404, {"error": "条目不存在，请刷新索引"}, head)
        elif not action:
            self.send_json(200, {"item": item}, head)
        elif not item.get("file"):
            self.send_json(404, {"error": "该条目没有可预览文件"}, head)
        elif action == "thumb":
            self.thumb_route(item, head, versioned="v" in query)
        else:
            send_file(self, contained(indexer.workspace, item["file"]), head,
                      source_file=True, anchor=indexer.workspace)

    def thumb_route(self, item: dict[str, Any], head: bool,
                    versioned: bool = False) -> None:
        """A card-sized picture of an item's file, made on first request and cached.

        Small pictures are their own thumbnail. When no thumbnail can be made the
        file itself is sent, and the browser is told not to keep it.
        """
        indexer = self.server.indexer
        source = contained(indexer.workspace, item["file"])
        found = item_thumb(source)
        if found is None:
            self.send_json(404, {"error": "该条目没有可显示的图片或视频"}, head)
            return
        name, as_is = found
        keep = YEAR if versioned else 0
        if not as_is:
            cache = indexer.config.cache
            try:
                made = make_item_thumb(source, name, cache)
            except (RuntimeError, OSError):
                made = False
            if made:
                try:
                    folder = safe_cache_path(cache, cache / ITEM_THUMBS)
                    send_file(self, contained(folder, name), head,
                              anchor=cache.resolve(), cache_seconds=keep)
                    return
                except (FileNotFoundError, FileError, RuntimeError):
                    pass
        send_file(self, source, head, source_file=True, anchor=indexer.workspace,
                  cache_seconds=keep if as_is else 0)

    def export_route(self, query: dict[str, list[str]], head: bool) -> None:
        import datetime as dt
        from urllib.parse import quote
        from .exporter import ExportError, export
        format_name = query.get("format", ["xlsx"])[0]
        kind = query.get("kind", [""])[0]
        day = dt.date.today()
        try:
            data, mime, name = export(self.server.indexer.store,
                                      format_name, kind, day,
                                      wants_all_versions(query))
        except ExportError as error:
            self.send_json(400, {"error": str(error)}, head)
            return
        # plain-ASCII name for old clients; everyone else reads filename*
        fallback = f"SPT-export-{day.isoformat()}.{name.rsplit('.', 1)[-1]}"
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Disposition",
                         f"attachment; filename=\"{fallback}\"; "
                         f"filename*=UTF-8''{quote(name, safe='')}")
        self.end_headers()
        if not head:
            self.wfile.write(data)

    def work_route(self, identifier: str, action: str | None,
                   query: dict[str, list[str]], head: bool) -> None:
        indexer = self.server.indexer
        detail = indexer.store.detail(identifier)
        if detail is None:
            self.send_json(404, {"error": "作品不存在，请刷新索引"}, head)
            return
        if action is None:
            self.send_json(200, detail, head)
            return
        root = self.work_root(detail["work"])
        if action == "file":
            value = query.get("path", [""])[0]
            send_file(self, contained(root, value), head, source_file=True,
                      anchor=indexer.workspace)
        else:
            self.cover_route(identifier, root, head, versioned="v" in query)

    def work_root(self, work: dict[str, Any]) -> Path:
        workspace = self.server.indexer.workspace
        root = workspace / work["relative_path"]
        if not root.is_relative_to(workspace):
            raise FileError("作品目录不在当前工作区内")
        current = workspace
        for part in root.relative_to(workspace).parts:
            current = current / part
            if current.is_symlink():
                raise FileError("作品目录已变为符号链接，请核对源目录")
        resolved = root.resolve(strict=True)
        if str(resolved) != work["path"] or not resolved.is_dir():
            raise FileError("作品根目录与索引记录不一致，请刷新索引")
        return resolved

    def cover_route(self, identifier: str, root: Path, head: bool,
                    versioned: bool = False) -> None:
        indexer = self.server.indexer
        with indexer.store.connect() as connection:
            row = connection.execute(
                "SELECT cover_source,cover_cache FROM works WHERE id=?",
                (identifier,)).fetchone()
        if row[1]:
            # the small thumbnail; its name changes with the source, so a
            # versioned URL may be kept by the browser
            cache = safe_cache_path(indexer.config.cache,
                                    indexer.config.cache / "thumbs")
            try:
                send_file(self, contained(cache, Path(row[1]).name), head,
                          anchor=indexer.config.cache.resolve(),
                          cache_seconds=YEAR if versioned else 0)
                return
            except (FileNotFoundError, FileError):
                if not row[0]:
                    raise
        if row[0]:
            send_file(self, contained(root, row[0]), head, source_file=True,
                      anchor=indexer.workspace)
        else:
            self.send_json(404, {"error": "当前作品没有可用封面"}, head)

    def static_route(self, path: str, head: bool) -> None:
        relative = path.lstrip("/") or "index.html"
        if relative.startswith("spt/ui/"):
            relative = relative[len("spt/ui/"):]
        root = self.server.indexer.config.ui.resolve()
        send_file(self, contained(root, relative), head, anchor=root)

    def event_stream(self, head: bool) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        self.close_connection = True
        if head:
            return
        events = self.server.indexer.events
        subscriber = events.subscribe()
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                try:
                    data = subscriber.get(timeout=15)
                    text = json.dumps(data, ensure_ascii=False)
                    message = (f"event: index_updated\n"
                               f"data: {text}\n\n").encode()
                except queue.Empty:
                    message = b": heartbeat\n\n"
                self.wfile.write(message)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            events.unsubscribe(subscriber)

    def send_error(self, code: int, message: str | None = None,
                   explain: str | None = None) -> None:
        self.send_json(code, {"error": "请求无法处理"}, self.command == "HEAD")

    def log_message(self, format: str, *args: Any) -> None:
        return
