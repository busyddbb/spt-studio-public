"""Windows executor for the same durable publishing protocol used by the Mac.

Files enter the official browser's file control once. A durable submit grant and
full preflight proof are required before the sole publish click. Exceptions after
that point become unknown; they never cause a second upload or submit.
"""
from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
import logging
from pathlib import Path
import re
import time
from urllib.parse import urlencode, urlsplit
import uuid

from .runtime import DOMAINS, official_url

LOG = logging.getLogger("spt.windows.publisher")
MANAGER_URL = "https://creator.rednote.com/new/note-manager"
STOPPED = {"needs_attention", "needs_login", "unknown", "failed", "cancelled", "published", "under_review"}


def iso_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Attention(RuntimeError):
    def __init__(self, message, before_click=False):
        super().__init__(message)
        self.before_click = before_click


class PublishingSession:
    def __init__(self, worker, task, queue_mode=True):
        self.worker, self.api, self.manager = worker, worker.api, worker.manager
        self.job = task["job"]
        self.workspace = task["workspace"]
        self.queue_id = task.get("queue_id")
        self.options = dict(task.get("options") or {})
        self.queue_mode = queue_mode
        self.key = self.queue_id or self.job["id"]
        self.phase = "start"
        self.page = None
        self.stopped = self.busy = False
        self.upload_delivered = self.intent_sent = self.click_attempted = False
        self.duplicate_checked = self.identity_verified = False
        self.result_record = None
        self.legacy_finished = False
        self.click_at = None
        self.started = time.monotonic()
        self.last_heartbeat = self.started
        self.last_result_navigation = 0
        self.media = sorted(self.workspace.get("media", []), key=lambda m: m.get("order", 0))
        self.media_names = [m["name"] for m in self.media]
        draft = self.workspace.get("draft") or {}
        self.title = self.options.get("title", draft.get("title", ""))
        self.body = self.options.get("body", draft.get("body", ""))
        if self.workspace["account"]["platform"] != "xiaohongshu" or self.job["target"] not in {"image", "video"}:
            raise Attention("后台自动发布当前仅支持 rednote 图文和单视频。")

    async def event(self, state, message, evidence=None, **fields):
        if self.queue_mode:
            args = {"id": self.queue_id, "executor_id": self.worker.executor_id,
                    "event": state, "message": message, **fields}
            if evidence is not None:
                args["evidence"] = evidence
                for field in ("published_at", "verified_at", "basis"):
                    if field in evidence:
                        args[field] = evidence[field]
            result = await self.api.action("queue_event", args)
            actual = result.get("job", {}).get("state")
            if actual in STOPPED and actual != state:
                self.stopped = True
                raise Attention("任务已由队列停止，未继续操作平台。")
            return result
        allowed = {"checking_login", "uploading", "needs_login", "needs_attention", "failed", "cancelled", "awaiting_review"}
        legacy_state = state if state in allowed else "uploading"
        return await self.api.action("update_upload", {"id": self.job["id"], "state": legacy_state, "message": message})

    async def revalidate(self):
        current = await self.api.get("/api/publishing/upload", {"id": self.job["id"]})
        job, work = current["job"], current["workspace"]
        keys = ("id", "account_id", "draft_id", "fingerprint", "target")
        if job.get("state") == "cancelled":
            self.stopped = True
            raise Attention("本条上传任务已取消。")
        if (any(job.get(k) != self.job.get(k) for k in keys)
                or work.get("account", {}).get("id") != self.workspace["account"]["id"]
                or work.get("profile_id") != self.workspace.get("profile_id")
                or not work.get("can_upload_current")
                or (work.get("draft") or {}).get("fingerprint") != self.job.get("fingerprint")
                or [m.get("id") for m in work.get("media", [])] != [m.get("id") for m in self.workspace.get("media", [])]
                or not all(m.get("available") for m in work.get("media", []))):
            raise Attention("内容、素材或账号核对已变化，请回工作台重新核对。")
        return work

    async def navigate(self, address):
        if not official_url(address, DOMAINS["xiaohongshu"]):
            raise Attention("平台回查地址不在官方 HTTPS 页面范围。")
        await self.page.goto(address, wait_until="domcontentloaded", timeout=45000)

    async def screenshot(self, proof):
        proof = dict(proof)
        try:
            image = await self.page.screenshot(type="png", timeout=10000)
            if len(image) < 4_000_000:
                proof["png_base64"] = base64.b64encode(image).decode("ascii")
        except Exception:
            pass  # Screenshot is supplemental; all structured DOM evidence is mandatory.
        return proof

    def step_options(self):
        result = dict(self.options, duplicate_checked=self.duplicate_checked)
        if self.identity_verified:
            result["identity_proof"] = {"profile_id": self.options.get("expected_profile_id")}
        if self.result_record:
            result["result_record"] = self.result_record
        return result

    async def dom(self, phase):
        if not official_url(self.page.url, DOMAINS["xiaohongshu"]):
            raise Attention("页面已离开官方后台，自动操作已停止。")
        return await self.page.evaluate(self.worker.queue_dom, {
            "options": self.step_options(), "title": self.title, "body": self.body,
            "mediaNames": self.media_names, "phase": phase,
        })

    async def stop_attention(self, message, before_click=False):
        self.stopped = True
        if before_click and not message.startswith("[未点击]"):
            message = "[未点击] " + message
        state = "unknown" if self.intent_sent and not before_click else "needs_attention"
        try:
            await self.event(state, message)
            await self.api.action("update_upload", {"id": self.job["id"], "state": "needs_attention", "message": message})
        except Exception:
            LOG.error("任务 %s 的停止回执未保存；禁止自动重试", self.key)

    async def finish_legacy(self):
        try:
            await self.api.action("update_upload", {"id": self.job["id"], "state": "cancelled", "message": "队列终态已记录，平台结果以队列回查为准。"})
            self.legacy_finished = True
        except Exception:
            LOG.error("任务 %s 终态已保存；旧上传状态待下次本机回写", self.key)

    async def advance(self):
        if self.stopped or self.busy:
            return
        self.busy = True
        try:
            if time.monotonic() - self.started > 1800:
                raise Attention("平台处理超时，请打开原任务核对；不会自动重传。")
            if self.phase == "start":
                await self.revalidate()
                self.page = await self.manager.page_for(self.job["account_id"], "xiaohongshu", "upload:" + self.key)
                self.manager.task_pages[self.key] = self.page
                await self.event("checking_login", "正在核对官方账号会话与已有笔记。")
                self.phase = "duplicate" if self.queue_mode else "input"
                await self.navigate(MANAGER_URL if self.queue_mode else self.publish_url())
                return
            if self.page.is_closed():
                raise Attention("原任务页面已关闭，请先核对后台，软件不会重传。")
            if time.monotonic() - self.last_heartbeat >= 20:
                await self.revalidate()
                await self.event("checking_result" if self.intent_sent else "processing" if self.phase == "preflight" else "uploading" if self.upload_delivered else "checking_login",
                                 "后台任务仍在运行（" + self.phase + "）。")
                self.last_heartbeat = time.monotonic()
            if self.phase in {"input", "fill"}:
                result = await self.page.evaluate(self.worker.upload_dom, {
                    "phase": self.phase, "target": self.job["target"], "title": self.title, "body": self.body,
                })
            else:
                if self.phase == "click":
                    if not self.intent_sent:
                        raise Attention("没有单次提交授权，未点击发布。", before_click=True)
                    self.click_at = iso_now()
                result = await self.dom(self.phase)
            await self.handle(result or {})
        except asyncio.CancelledError:
            raise
        except Attention as exc:
            if not self.stopped:
                await self.stop_attention(str(exc), before_click=exc.before_click)
        except Exception:
            # Never expose webpage/login text or exception URLs in shared logs.
            LOG.error("任务 %s 在 %s 阶段中断", self.key, self.phase)
            await self.stop_attention("平台步骤未能完成，请打开原任务核对；不会自动重传或重复提交。")
        finally:
            self.busy = False

    def publish_url(self):
        return "https://creator.rednote.com/publish/publish?" + urlencode({"from": "menu", "target": self.job["target"]})

    async def handle(self, result):
        status = result.get("status")
        if status in {"wait", "processing"}:
            if self.phase == "result" and self.click_at and time.monotonic() - self.last_result_navigation > 30:
                if "note-manager" not in urlsplit(self.page.url).path:
                    await self.navigate(MANAGER_URL)
                self.last_result_navigation = time.monotonic()
            return
        if status == "media_processing":
            await self.event("processing", "媒体已上传，等待官方处理完成。")
            return
        if status == "login":
            if self.upload_delivered:
                raise Attention("媒体交给平台后登录失效，请核对原草稿，软件不会重传。")
            await self.event("needs_login", "请在此账号的官方页面登录，再对原任务点重试。")
            await self.api.action("update_upload", {"id": self.job["id"], "state": "needs_login", "message": "请登录此账号后重试原任务"})
            self.stopped = True
            await self.page.bring_to_front()
            return
        if status == "identity_opening" and self.phase == "duplicate":
            self.phase = "identity_open"
            return
        if status in {"identity_note", "identity_profile"}:
            address = result.get("url", "")
            parsed = urlsplit(address)
            expected_path = ("/user/profile/" + str(self.options.get("expected_profile_id"))) if status == "identity_profile" else ("/discovery/item/" + str(result.get("note_id")))
            if parsed.path != expected_path or parsed.query or parsed.fragment:
                raise Attention("账号身份核验链接不完整，已停止。")
            self.phase = "identity_verify"
            await self.navigate(address)
            return
        if status == "identity_verified" and self.phase == "identity_verify":
            if str(result.get("account_profile_id", "")).lower() != str(self.options.get("expected_profile_id", "")).lower():
                raise Attention("官方作者身份与目标账号不一致。")
            self.identity_verified = True
            self.phase = "duplicate"
            await self.navigate(MANAGER_URL)
            return
        if status == "duplicate":
            raise Attention("该账号已有同标题笔记或草稿，已停止防止重复。")
        if status == "clear" and self.phase == "duplicate":
            self.duplicate_checked = True
            self.identity_verified = True
            self.phase = "input"
            await self.navigate(self.publish_url())
            return
        if status == "ready" and self.phase == "input":
            if self.upload_delivered:
                raise Attention("素材已交给平台，禁止再次上传。")
            await self.revalidate()
            paths = [str(Path(m["path"]).resolve()) for m in self.media]
            if not paths or any(not Path(p).is_file() for p in paths):
                raise Attention("原媒体文件不可用，未开始上传。")
            await self.event("uploading", "正在把本条原媒体交给官方上传控件。")
            # Mark before the browser call: a lost callback must never resend files.
            self.upload_delivered = True
            await self.page.locator('input.upload-input[type="file"]').nth(result["index"]).set_input_files(paths, timeout=30000)
            self.phase = "fill"
            return
        if status == "filled" and self.phase == "fill":
            if self.queue_mode:
                self.phase = "preflight"
            else:
                await self.event("awaiting_review", "媒体与文案已准备，请核对官方预览后发布。")
                self.stopped = True
                await self.page.bring_to_front()
            return
        if status == "proof" and self.phase == "preflight":
            proof = result.get("evidence")
            if not isinstance(proof, dict):
                raise Attention("预检证据缺失。")
            await self.event("preflight", "账号、媒体顺序、完整文案、结构化话题与设置已核齐。", await self.screenshot(proof))
            if not self.options.get("submit_enabled"):
                raise Attention("草稿已准备并核对；此任务未授权自动提交。")
            await self.revalidate()
            try:
                response = await self.event("submit_intent", "请求保存本任务单次提交意图。")
            except Exception:
                raise Attention("提交授权回执未确认，未点击发布。", before_click=True) from None
            if response.get("submit_granted") is not True:
                raise Attention("提交意图未获确认，未点击发布。", before_click=True)
            self.intent_sent = True
            self.phase = "click"
            return
        if self.phase == "click":
            if status == "clicked":
                self.click_attempted = True
                self.last_result_navigation = time.monotonic()
                await self.event("checking_result", "已点击一次发布，正在核对官方真实结果。")
                self.phase = "result"
                return
            raise Attention("发布前核对未通过：" + str(result.get("reason") or status), before_click=True)
        if status == "result_card" and self.phase == "result":
            address = result.get("edit_url", "")
            if urlsplit(address).path != "/publish/update":
                raise Attention("官方结果回查链接无效。")
            self.result_record = result
            self.phase = "result_verify"
            await self.navigate(address)
            return
        if status == "result" and self.phase == "result_verify":
            state = result.get("result_status")
            proof = result.get("evidence") or {}
            note_id, address = result.get("note_id"), result.get("url", "")
            if state not in {"published", "under_review"} or proof.get("content_verified") is not True or not re.fullmatch(r"[a-fA-F0-9]{24}", str(note_id)) or not official_url(address, DOMAINS["xiaohongshu"]):
                raise Attention("官方结果证据不完整，请核对原笔记。")
            proof = await self.screenshot(proof)
            proof.update(published_at=self.click_at, verified_at=iso_now(), basis="click_proxy")
            await self.event(state, "官方后台与内容回查确认" + ("已发布。" if state == "published" else "审核中。"), proof,
                             note_id=note_id, url=address)
            self.stopped = True
            await self.finish_legacy()
            return
        errors = {"ambiguous": "平台控件不唯一，已停止。", "too_long": "标题超过平台当前上限。",
                  "existing_content": "官方编辑器已有其他内容，已停止避免覆盖。", "editor_rejected": "官方编辑器未完整接收文案。"}
        raise Attention(errors.get(status, result.get("reason") or "官方页面控件无法核准，已停止。"))


class PublishingWorker:
    def __init__(self, manager, api, root, executor_id=None):
        self.manager, self.api, self.root = manager, api, Path(root)
        self.executor_id = executor_id or "windows-" + uuid.uuid4().hex
        self.queue_dom = (self.root / "native" / "PublishingQueueDOM.js").read_text(encoding="utf-8")
        self.upload_dom = (self.root / "windows" / "upload_dom.js").read_text(encoding="utf-8")
        self.sessions, self.tasks = {}, {}
        self.last_claim = self.last_snapshot = -float("inf")
        self.claiming = False

    async def tick(self):
        if not self.claiming and time.monotonic() - self.last_claim >= 2:
            self.claiming = True
            try:
                result = await self.api.action("queue_claim", {"executor_id": self.executor_id})
                for task in result.get("tasks", []):
                    key = task["queue_id"]
                    old = self.tasks.get(key)
                    if old is not None and not old.done():
                        old.cancel()
                        await asyncio.gather(old, return_exceptions=True)
                    try:
                        self.sessions[key] = PublishingSession(self, task)
                    except Attention as exc:
                        await self.api.action("queue_event", {"id": key, "executor_id": self.executor_id, "event": "needs_attention", "message": str(exc)})
                self.last_claim = time.monotonic()
            finally:
                self.claiming = False
        if time.monotonic() - self.last_snapshot >= 5:
            snapshot = await self.api.get("/api/publishing/queue")
            states = {j["id"]: j["state"] for j in snapshot.get("jobs", [])}
            for key, session in self.sessions.items():
                if session.queue_mode and states.get(key) in STOPPED:
                    session.stopped = True
                    if states.get(key) in {"published", "under_review"} and not session.legacy_finished:
                        await session.finish_legacy()
            self.last_snapshot = time.monotonic()
        for key, session in list(self.sessions.items()):
            current = self.tasks.get(key)
            if not session.stopped and (current is None or current.done()):
                self.tasks[key] = asyncio.create_task(session.advance())

    async def cancel(self, queue_id):
        result = await self.api.action("queue_cancel", {"id": queue_id, "executor_id": self.executor_id})
        session = self.sessions.get(queue_id)
        if session:
            session.stopped = True
            pending = self.tasks.get(queue_id)
            if pending and not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
            await self.api.action("update_upload", {"id": session.job["id"], "state": "cancelled", "message": "本机任务已停止，请先核对平台草稿。"})
        return result

    async def start_upload(self, payload):
        account = payload.get("account_id") or payload.get("accountID")
        draft = payload.get("draft_id") or payload.get("draftID")
        task = await self.api.action("prepare_upload", {"account_id": account, "draft_id": draft})
        key = task["job"]["id"]
        old = self.sessions.get(key)
        if old and not old.stopped:
            await self.manager.preview(key)
            return {"job": old.job}
        self.sessions[key] = PublishingSession(self, task, queue_mode=False)
        await self.sessions[key].advance()
        return {"job": task["job"]}

    async def preview_upload(self, job_id):
        session = next((s for s in self.sessions.values() if s.job["id"] == job_id), None)
        if session is None:
            raise RuntimeError("原上传页面不在当前进程。请核对后台草稿，勿重传。")
        return await self.manager.preview(session.key)

    async def cancel_upload(self, job_id):
        session = next((s for s in self.sessions.values() if s.job["id"] == job_id), None)
        if session and session.queue_mode:
            return await self.cancel(session.queue_id)
        result = await self.api.action("update_upload", {"id": job_id, "state": "cancelled", "message": "本机任务已停止，请核对平台草稿。"})
        if session:
            session.stopped = True
        return result

    async def stop(self):
        for task in self.tasks.values():
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)
        for session in self.sessions.values():
            if not session.stopped:
                await session.stop_attention("SPT 后台已退出，请核对原任务后继续。")
