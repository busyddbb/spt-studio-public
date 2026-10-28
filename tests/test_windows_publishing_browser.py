"""Actual Chromium + public DOM publishing fixtures, with no real account/network.

All official URLs are fulfilled by local HTML. The only uploaded file is a PNG
created in TemporaryDirectory. This is browser coverage, not a live platform run.
"""
from __future__ import annotations

import base64
import copy
import importlib.util
import os
from pathlib import Path
import tempfile
import time
import unittest

from windows.runtime import BrowserManager
from windows.publishing_worker import PublishingSession, PublishingWorker

ROOT = Path(__file__).resolve().parents[1]
PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
PROFILE = "0123456789abcdef01234567"


def fixture():
    return '''<!doctype html><meta charset="utf-8">
      <style>html,body{display:block;width:1200px;min-height:850px}.upload-list{display:block}img{width:24px;height:24px}</style>
      <header><span data-testid="account">Fixture creator</span><a href="/profile/''' + PROFILE + '''">Account</a></header>
      <input placeholder="填写标题会有更多赞哦" value="">
      <div class="ProseMirror" contenteditable="true"></div>
      <label>允许正文复制<input type="checkbox"></label><label>定时发布<input type="checkbox"></label>
      <button>公开可见</button><div class="upload-list"><img data-filename="first.png" src="data:image/png;base64,''' + PNG + '''"></div>
      <input type="file" class="upload-input" accept="image/png,image/jpeg" multiple>
      <button id="publish" onclick="window.__publishClicks=(window.__publishClicks||0)+1">发布</button>
      <button>全部笔记</button><button>草稿箱</button><div role="status">暂无内容</div>
      <script>window.__publishClicks=0;
      const ed=document.querySelector('.ProseMirror');
      ed.addEventListener('input',()=>{
        // Tiptap/ProseMirror normalizes insertText into paragraph nodes.
        if(Array.from(ed.childNodes).every(n=>n.nodeType===1 && n.tagName==='P'))return;
        const lines=ed.innerText.split('\\n');
        ed.replaceChildren(...lines.map(line=>{const p=document.createElement('p');p.textContent=line;return p;}));
      });</script>'''


class LocalFixtureAPI:
    def __init__(self, task, grant=True):
        self.task, self.grant, self.events = task, grant, []

    async def get(self, path, params=None):
        if path.endswith("/upload"):
            return copy.deepcopy(self.task)
        return {"jobs": []}

    async def action(self, action, args):
        if action == "queue_event":
            self.events.append(copy.deepcopy(args))
            if args["event"] == "preflight":
                proof = args["evidence"]
                assert proof["identity_verified"] is True
                assert proof["media_count"] == 1 and proof["media_order"] == ["first.png"]
                assert proof["title"] == "测试标题" and proof["body"] == "正文\n第二段"
                assert proof["account_profile_id"] == PROFILE
                assert proof["settings"] == {"allow_body_copy": False, "scheduled": False, "visibility": "public"}
                assert proof["png_base64"].startswith("iVBORw0KGgo")
            return {"job": {"state": args["event"]}, "submit_granted": self.grant if args["event"] == "submit_intent" else False}
        return {"job": self.task["job"]}


@unittest.skipUnless(importlib.util.find_spec("playwright"), "Playwright is not installed")
class ChromiumPublishingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from playwright.async_api import async_playwright
        self.scratch = tempfile.TemporaryDirectory()
        self.root = Path(self.scratch.name)
        self.media = self.root / "first.png"
        self.media.write_bytes(base64.b64decode(PNG))
        self.playwright = await async_playwright().start()
        self.manager = BrowserManager(self.root, self.playwright, headless=True, channel=None,
                                      executable_path=os.environ.get("SPT_TEST_BROWSER"), downloads=self.root / "Downloads")
        self.page = await self.manager.page_for("fixture-account", "xiaohongshu", "upload:fixture-queue")
        await self.page.route("https://**/*", lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8", body=fixture()))
        self.task = {
            "queue_id": "fixture-queue", "job": {"id": "fixture-upload", "account_id": "fixture-account", "draft_id": "fixture-draft", "fingerprint": "fixture-fingerprint", "target": "image", "state": "prepared"},
            "workspace": {"account": {"id": "fixture-account", "platform": "xiaohongshu"}, "profile_id": "fixture-profile", "can_upload_current": True,
                          "draft": {"fingerprint": "fixture-fingerprint", "title": "测试标题", "body": "正文\n第二段"},
                          "media": [{"id": "fixture-media", "name": "first.png", "path": str(self.media), "order": 0, "available": True}]},
            "options": {"submit_enabled": True, "topics": [], "title": "测试标题", "body": "正文\n第二段", "expected_profile_id": PROFILE, "expected_name": "Fixture creator", "allow_body_copy": False, "visibility": "public"},
        }

    async def asyncTearDown(self):
        await self.manager.close()
        await self.playwright.stop()
        self.scratch.cleanup()

    def session(self, grant=True):
        api = LocalFixtureAPI(self.task, grant=grant)
        worker = PublishingWorker(self.manager, api, ROOT, executor_id="fixture-browser-executor")
        return PublishingSession(worker, self.task), api

    async def reach_prepared(self, session):
        # Follow actual duplicate scanning, navigation, input control, editor fill
        # and preflight instead of assigning intermediate success states.
        for _ in range(25):
            await session.advance()
            if session.stopped or session.phase == "click":
                break
        self.assertTrue(session.upload_delivered)
        selected = await self.page.locator('input[type="file"]').evaluate("el=>Array.from(el.files).map(f=>({name:f.name,size:f.size}))")
        self.assertEqual(selected, [{"name": "first.png", "size": self.media.stat().st_size}])
        self.assertEqual(await self.page.locator('input[placeholder="填写标题会有更多赞哦"]').input_value(), "测试标题")

    async def test_real_file_input_and_preflight_grant_denial_never_click(self):
        session, api = self.session(grant=False)
        await self.reach_prepared(session)
        self.assertTrue(session.stopped)
        self.assertEqual(await self.page.evaluate("window.__publishClicks"), 0)
        self.assertEqual([e["event"] for e in api.events][-3:], ["preflight", "submit_intent", "needs_attention"])

    async def test_real_click_once_then_unknown_does_not_click_or_upload_again(self):
        session, api = self.session()
        await self.reach_prepared(session)
        self.assertEqual(session.phase, "click")
        await session.advance()
        self.assertEqual(await self.page.evaluate("window.__publishClicks"), 1)
        self.assertEqual(session.phase, "result")
        for _ in range(4):
            await session.advance()
        self.assertEqual(await self.page.evaluate("window.__publishClicks"), 1)
        session.started = time.monotonic() - 1801
        await session.advance()
        await session.advance()
        self.assertTrue(session.stopped)
        self.assertEqual(api.events[-1]["event"], "unknown")
        self.assertEqual(await self.page.evaluate("window.__publishClicks"), 1)

    async def test_platform_dom_itself_rejects_second_click(self):
        session, api = self.session()
        await self.reach_prepared(session)
        await session.advance()
        second = await session.dom("click")
        self.assertEqual(second["status"], "attention")
        self.assertEqual(await self.page.evaluate("window.__publishClicks"), 1)

    async def test_wrong_account_profile_stops_before_any_file_handoff(self):
        self.task["options"]["expected_profile_id"] = "fedcba9876543210fedcba98"
        session, api = self.session()
        for _ in range(4):
            await session.advance()
        self.assertTrue(session.stopped)
        self.assertFalse(session.upload_delivered)
        self.assertEqual(api.events[-1]["event"], "needs_attention")
        self.assertEqual(await self.page.locator('input[type="file"]').evaluate("el=>el.files.length"), 0)


if __name__ == "__main__":
    unittest.main()
