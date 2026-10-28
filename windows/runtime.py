"""Local Windows browser host. Website sessions stay in isolated browser profiles.

The host never reads, exports or transfers website credentials. It uses Playwright's
public page controls; only the SPT localhost window receives the desktop bridge.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
import queue
import time
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
import urllib.request
import uuid

LOG = logging.getLogger("spt.windows")
DEFAULT_URL = "http://127.0.0.1:8766"
DOMAINS = {
    "xiaohongshu": ("rednote.com", "xiaohongshu.com", "xhslink.com"),
    "instagram": ("instagram.com", "facebook.com", "fb.com", "meta.com"),
    "facebook": ("facebook.com", "instagram.com", "fb.com", "meta.com"),
    "tiktok": ("tiktok.com",),
    "youtube": ("youtube.com", "google.com"),
    "google_business": ("google.com", "youtube.com"),
    "yelp": ("yelp.com",),
}
PUBLISH_URLS = {
    "xiaohongshu": "https://creator.rednote.com/new/note-manager",
    "instagram": "https://www.instagram.com/",
    "facebook": "https://business.facebook.com/",
    "tiktok": "https://www.tiktok.com/tiktokstudio/upload",
    "youtube": "https://studio.youtube.com/",
    "google_business": "https://business.google.com/",
    "yelp": "https://biz.yelp.com/",
}


def official_url(value, domains):
    """Allow only HTTPS platform pages, never local/network/file or credential URLs."""
    try:
        u = urlsplit(value)
        host = (u.hostname or "").lower()
        return bool(u.scheme == "https" and not u.username and not u.password
                    and u.port in (None, 443) and host
                    and any(host == d or host.endswith("." + d) for d in domains))
    except (ValueError, TypeError):
        return False


class LocalAPIError(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise LocalAPIError("本机 API 不允许跳转到其他地址")


class LocalAPI:
    def __init__(self, base_url=DEFAULT_URL):
        if base_url.rstrip("/") != DEFAULT_URL:
            raise ValueError("Windows host only connects to SPT at 127.0.0.1:8766")
        self.base_url = DEFAULT_URL
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    async def get(self, path, params=None):
        return await self._request(path + (("?" + urlencode(params)) if params else ""))

    async def post(self, path, payload):
        return await self._request(path, payload)

    async def action(self, name, args=None):
        return await self.post("/api/publishing/action", {"action": name, "arguments": args or {}})

    async def _request(self, path, payload=None):
        if not isinstance(path, str) or not path.startswith("/api/") or "\\" in path or "#" in path:
            raise LocalAPIError("无效的本机 API 地址")
        def run():
            data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(self.base_url + path, data=data,
                                         headers={"Content-Type": "application/json", "Origin": self.base_url})
            try:
                with self.opener.open(req, timeout=25) as response:
                    return json.load(response)
            except HTTPError as exc:
                try:
                    message = json.load(exc).get("error", "本机 API 拒绝了操作")
                except (ValueError, AttributeError):
                    message = "本机 API 暂时不可用"
                raise LocalAPIError(message) from None
        return await asyncio.to_thread(run)


class BrowserManager:
    def __init__(self, root, playwright, *, headless=False, channel="msedge", executable_path=None, downloads=None):
        self.root, self.playwright = Path(root).resolve(), playwright
        self.headless, self.channel, self.executable_path = headless, channel, executable_path
        self.download_dir = Path(downloads) if downloads else Path.home() / "Downloads"
        self.download_tasks = set()
        self.download_reservations = set()
        self.attached_pages = set()
        self.contexts, self.pages, self.task_pages = {}, {}, {}
        self.context_locks = {}
        self.local_page = None

    def profile_path(self, account_id, platform):
        # Names, handles and platform IDs never become folder names.
        key = hashlib.sha256((platform + "\0" + str(account_id)).encode()).hexdigest()
        return self.root / "data" / "windows" / "browser-profiles" / key

    async def _context(self, account_id, platform):
        key = (platform, str(account_id))
        lock = self.context_locks.setdefault(key, asyncio.Lock())
        async with lock:
            if key in self.contexts:
                return self.contexts[key]
            folder = self.profile_path(account_id, platform)
            folder.mkdir(parents=True, exist_ok=True)
            args = ["--no-first-run", "--no-default-browser-check", "--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding"]
            if platform == "spt":
                args += ["--app=" + DEFAULT_URL + "/workspace/"]
            errors = []
            context = None
            # Edge is normally present on Windows; downloaded Chromium is the offline fallback.
            for channel in ([self.channel, None] if self.channel else [None]):
                try:
                    options = {"headless": self.headless, "args": args, "viewport": {"width": 1280, "height": 860},
                               "accept_downloads": True}
                    if channel:
                        options["channel"] = channel
                    if self.executable_path:
                        options["executable_path"] = self.executable_path
                        options.pop("channel", None)
                    context = await self.playwright.chromium.launch_persistent_context(str(folder), **options)
                    break
                except Exception as exc:
                    errors.append(type(exc).__name__)
            if context is None:
                raise RuntimeError("无法启动浏览器。请运行安装Windows.bat 安装 Playwright 和 Chromium。")
            if platform != "spt":
                allowed = DOMAINS[platform]
                async def guard(route):
                    request = route.request
                    try:
                        top = request.frame.parent_frame is None
                    except Exception:
                        top = False
                    if request.is_navigation_request() and top and not official_url(request.url, allowed):
                        await route.abort()
                    else:
                        await route.continue_()
                await context.route("**/*", guard)
            context.on("page", self._attach_page)
            context.on("close", lambda *_: self.contexts.pop(key, None))
            for page in context.pages:
                self._attach_page(page)
            self.contexts[key] = context
            return context

    async def page_for(self, account_id, platform="xiaohongshu", purpose="platform"):
        platform = "xiaohongshu" if platform == "rednote" else platform
        if platform not in DOMAINS:
            raise ValueError("未支持的平台")
        key = (platform, str(account_id), purpose)
        old = self.pages.get(key)
        if old is not None and not old.is_closed():
            return old
        context = await self._context(account_id, platform)
        page = await context.new_page()
        self.pages[key] = page
        return page

    def _attach_page(self, page):
        if page in self.attached_pages:
            return
        self.attached_pages.add(page)
        def downloaded(download):
            task = asyncio.create_task(self._save_download(download))
            self.download_tasks.add(task)
            task.add_done_callback(self.download_tasks.discard)
        page.on("download", downloaded)

    async def _save_download(self, download):
        import re
        self.download_dir.mkdir(parents=True, exist_ok=True)
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", Path(download.suggested_filename).name).strip(" .") or "SPT-download"
        target = self.download_dir / name
        suffix = 1
        while target.exists() or target in self.download_reservations:
            target = self.download_dir / (Path(name).stem + "-" + str(suffix) + Path(name).suffix)
            suffix += 1
        self.download_reservations.add(target)
        try:
            await download.save_as(str(target))
        except Exception:
            LOG.error("导出下载未能保存到 Downloads，请重新导出")
        finally:
            self.download_reservations.discard(target)

    async def local_window(self):
        if self.local_page is not None and not self.local_page.is_closed():
            await self.local_page.bring_to_front()
            return self.local_page
        context = await self._context("local-ui", "spt")
        self.local_page = context.pages[0] if context.pages else await context.new_page()
        # Installing the bridge precedes navigation in Runtime.run.
        return self.local_page

    async def open_account(self, account_id, platform="xiaohongshu", url=None):
        platform = "xiaohongshu" if platform == "rednote" else platform
        if platform not in PUBLISH_URLS:
            raise ValueError("未支持的平台")
        address = url or PUBLISH_URLS[platform]
        if not official_url(address, DOMAINS[platform]):
            raise ValueError("只允许打开该平台的官方 HTTPS 页面")
        page = await self.page_for(account_id, platform)
        await page.goto(address, wait_until="domcontentloaded", timeout=45000)
        await page.bring_to_front()
        return page

    async def open_workspace(self, workspace, purpose="platform"):
        account = workspace["account"]
        platform = account["platform"]
        page = await self.page_for(account["id"], platform, purpose)
        address = workspace["platform"]["publish_url"]
        if not official_url(address, DOMAINS[platform]):
            raise ValueError("官方后台地址不在允许范围")
        await page.goto(address, wait_until="domcontentloaded", timeout=45000)
        await page.bring_to_front()
        return page

    async def preview(self, queue_id):
        page = self.task_pages.get(queue_id)
        if page is None or page.is_closed():
            raise RuntimeError("原任务页面不在当前进程。请核对平台记录，勿直接重传。")
        await page.bring_to_front()
        return page

    async def close(self):
        if self.download_tasks:
            await asyncio.gather(*self.download_tasks, return_exceptions=True)
        for context in list(self.contexts.values()):
            try:
                await context.close()
            except Exception:
                pass
        self.contexts.clear()


class Runtime:
    def __init__(self, root, api=None):
        self.root = Path(root).resolve()
        self.api = api or LocalAPI()
        self.commands = queue.Queue()
        self.manager = self.publisher = self.metrics = None
        self.stopping = False
        self.last_metrics = 0
        self.bridged_pages = set()
        self.executor_id = "windows-" + uuid.uuid4().hex

    def enqueue(self, command, payload=None):
        self.commands.put((command, payload or {}))

    async def dispatch(self, command, payload=None):
        payload = payload or {}
        queue_id = payload.get("queue_id") or payload.get("queueID") or payload.get("id")
        if command in {"open_account", "openPlatform", "open_workspace", "openPublishing", "publishingWorkspace"}:
            account = payload.get("account_id") or payload.get("accountID")
            params = {"account_id": account}
            for source, target in (("draft_id", "draft_id"), ("draftID", "draft_id"), ("target", "target")):
                if payload.get(source):
                    params[target] = payload[source]
            workspace = await self.api.get("/api/publishing/workspace", params)
            await self.manager.open_workspace(workspace)
            return {"ok": True, "workspace": workspace}
        if command in {"queue_preview", "previewQueue", "previewPublishingQueue"}:
            await self.manager.preview(queue_id)
            return {"ok": True}
        if command in {"previewRednoteUpload", "preview_upload"}:
            await self.publisher.preview_upload(payload.get("job_id") or payload.get("jobID") or payload.get("id"))
            return {"ok": True}
        if command in {"queue_cancel", "cancelQueue", "cancelPublishingQueue"}:
            return await self.publisher.cancel(queue_id)
        if command in {"startRednoteUpload", "start_upload"}:
            return await self.publisher.start_upload(payload)
        if command == "cancelRednoteUpload":
            return await self.publisher.cancel_upload(payload.get("job_id") or payload.get("jobID") or payload.get("id"))
        if command in {"runPublishingQueue", "run_queue"}:
            await self.publisher.tick()
            return {"ok": True}
        if command in {"metrics_capture", "captureMetrics"}:
            if self.metrics is not None:
                await self.metrics.tick()
            return {"ok": True}
        if command in {"show", "open"}:
            page = await self.manager.local_window()
            if page not in self.bridged_pages:
                from . import bridge
                await bridge.install(page, self)
                self.bridged_pages.add(page)
                await page.goto(DEFAULT_URL + "/workspace/")
            return {"ok": True}
        if command == "stop":
            self.stopping = True
            return {"ok": True}
        raise ValueError("未知 Windows 窗口命令")

    def read_handoff_commands(self):
        commands = self.root / "data" / "windows" / "commands"
        if not commands.is_dir():
            return
        for path in commands.glob("*.json"):
            if path.is_symlink() or path.stat().st_size > 1024:
                continue
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                if value.get("command") in {"show", "stop"}:
                    self.enqueue(value["command"])
                path.unlink()
            except (OSError, ValueError, AttributeError):
                LOG.error("桌面启动请求无法读取")

    async def run(self):
        from playwright.async_api import async_playwright
        from .publishing_worker import PublishingWorker
        from .metrics_worker import MetricsWorker
        from . import bridge
        async with async_playwright() as playwright:
            self.manager = BrowserManager(self.root, playwright)
            self.publisher = PublishingWorker(self.manager, self.api, self.root, executor_id=self.executor_id)
            self.metrics = MetricsWorker(self.manager, self.api, self.root)
            page = await self.manager.local_window()
            await bridge.install(page, self)
            self.bridged_pages.add(page)
            await page.goto(DEFAULT_URL + "/workspace/", wait_until="domcontentloaded")
            try:
                while not self.stopping:
                    self.read_handoff_commands()
                    while not self.commands.empty():
                        command, payload = self.commands.get_nowait()
                        try:
                            await self.dispatch(command, payload)
                        except Exception:
                            LOG.error("桌面窗口操作未完成，请在原页面核对")
                    try:
                        await self.publisher.tick()
                        if time.monotonic() - self.last_metrics >= 10:
                            await self.metrics.tick()
                            self.last_metrics = time.monotonic()
                    except Exception:
                        LOG.error("后台轮询暂时未完成，将等待本机服务恢复")
                    await asyncio.sleep(0.8)
            finally:
                await self.publisher.stop()
                await self.metrics.stop()
                await self.manager.close()


class SingleInstance:
    """A held file lock prevents a second executor from owning the same profiles."""
    def __init__(self, path):
        self.path = Path(path)
        self.file = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("a+b")
        self.file.seek(0, 2)
        if self.file.tell() == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            self.file.close()
            self.file = None
            return False

    def close(self):
        if self.file:
            self.file.close()
            self.file = None


def main():
    parser = argparse.ArgumentParser(description="SPT Windows 独立窗口与本机后台执行器")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--stop", action="store_true", help="停止 Windows 窗口后台；保留所有记录")
    args = parser.parse_args()
    (args.root / "data").mkdir(exist_ok=True)
    logging.basicConfig(filename=args.root / "data" / "windows-runtime.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    lock = SingleInstance(args.root / "data" / "windows-runtime.lock")
    if args.stop:
        if lock.acquire():
            lock.close()
            return 0
        commands = args.root / "data" / "windows" / "commands"
        commands.mkdir(parents=True, exist_ok=True)
        (commands / (uuid.uuid4().hex + ".json")).write_text('{"command":"stop","payload":{}}', encoding="utf-8")
        return 0
    if not lock.acquire():
        # The existing host keeps running after its window is closed. A new local
        # UI may still use the same host via the request handoff directory.
        commands = args.root / "data" / "windows" / "commands"
        commands.mkdir(parents=True, exist_ok=True)
        (commands / (uuid.uuid4().hex + ".json")).write_text('{"command":"show","payload":{}}', encoding="utf-8")
        return 0
    runtime = Runtime(args.root)
    try:
        asyncio.run(runtime.run())
    except KeyboardInterrupt:
        return 0
    finally:
        lock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
