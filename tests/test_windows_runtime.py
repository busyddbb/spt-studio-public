"""Real executor decision tests: all browser/network inputs are explicit fakes.

No installed profile, website login, personal workspace or production API is used.
"""
from __future__ import annotations
import asyncio
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock

from windows.runtime import BrowserManager, LocalAPI, official_url
from windows.publishing_worker import Attention, PublishingSession, PublishingWorker

ROOT = Path(__file__).resolve().parents[1]


def context(path):
    return {"queue_id": "q1", "job": {"id": "u1", "account_id": "a1", "draft_id": "d1", "fingerprint": "fixed", "target": "image", "state": "prepared"},
            "workspace": {"account": {"id": "a1", "platform": "xiaohongshu"}, "profile_id": "profile-1", "can_upload_current": True,
                          "draft": {"fingerprint": "fixed", "title": "Fixture title", "body": "Fixture body"},
                          "media": [{"id": "m1", "name": "first.png", "path": str(path), "order": 0, "available": True}]},
            "options": {"submit_enabled": True, "topics": [], "title": "Fixture title", "body": "Fixture body", "expected_profile_id": "a" * 24}}


class API:
    def __init__(self, task, grant=True):
        self.task, self.grant, self.calls, self.state = task, grant, [], "checking_login"

    async def get(self, path, params=None):
        if path.endswith("/upload"):
            return copy.deepcopy(self.task)
        return {"jobs": [{"id": "q1", "state": self.state}]}

    async def action(self, name, args=None):
        self.calls.append((name, copy.deepcopy(args)))
        if name == "queue_event":
            self.state = args["event"]
            return {"job": {"state": self.state}, "submit_granted": self.grant if self.state == "submit_intent" else False}
        if name == "queue_claim":
            return {"tasks": []}
        return {"job": self.task["job"]}


class Page:
    def __init__(self):
        self.url = "https://creator.rednote.com/publish/publish"
        self.results, self.evaluations, self.files = [], [], []
        self.error = None

    def is_closed(self):
        return False

    async def goto(self, url, **options):
        self.url = url

    async def bring_to_front(self):
        pass

    async def screenshot(self, **options):
        return b"\x89PNG\r\n\x1a\nfixture"

    async def evaluate(self, script, args=None):
        self.evaluations.append(args["phase"])
        if self.error:
            raise self.error
        return self.results.pop(0) if self.results else {"status": "wait"}

    def locator(self, selector):
        return self

    def nth(self, index):
        return self

    async def set_input_files(self, paths, **options):
        self.files.append(paths)
        if self.error:
            raise self.error


class Manager:
    def __init__(self):
        self.page, self.task_pages = Page(), {}

    async def page_for(self, *args):
        return self.page

    async def preview(self, key):
        return self.task_pages[key]


class PublishingProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / "first.png"
        self.path.write_bytes(b"fixture")
        self.task = context(self.path)
        self.api, self.manager = API(self.task), Manager()
        self.worker = PublishingWorker(self.manager, self.api, ROOT, executor_id="fixture-executor")
        self.session = PublishingSession(self.worker, self.task)
        self.session.page = self.manager.page

    async def asyncTearDown(self):
        self.folder.cleanup()

    async def test_no_submit_grant_never_evaluates_click(self):
        self.api.grant = False
        self.session.phase = "preflight"
        self.manager.page.results = [{"status": "proof", "evidence": {"fixture": True}}]
        await self.session.advance()
        await self.session.advance()
        self.assertTrue(self.session.stopped)
        self.assertEqual(self.manager.page.evaluations, ["preflight"])
        events = [args["event"] for name, args in self.api.calls if name == "queue_event"]
        self.assertEqual(events, ["preflight", "submit_intent", "needs_attention"])

    async def test_submit_evidence_is_durable_before_one_click(self):
        self.session.phase = "preflight"
        self.manager.page.results = [{"status": "proof", "evidence": {"fixture": True}}, {"status": "clicked"}, {"status": "wait"}]
        await self.session.advance()
        events = [a["event"] for n, a in self.api.calls if n == "queue_event"]
        self.assertEqual(events, ["preflight", "submit_intent"])
        self.assertEqual(self.session.phase, "click")
        await self.session.advance()
        await self.session.advance()
        self.assertEqual(self.manager.page.evaluations.count("click"), 1)
        self.assertEqual(self.session.phase, "result")
        self.assertIsNotNone(self.session.click_at)

    async def test_lost_click_callback_is_unknown_and_not_retried(self):
        self.session.phase, self.session.intent_sent = "click", True
        self.manager.page.error = RuntimeError("callback lost after click")
        await self.session.advance()
        await self.session.advance()
        self.assertEqual(self.manager.page.evaluations, ["click"])
        self.assertTrue(self.session.stopped)
        events = [a["event"] for n, a in self.api.calls if n == "queue_event"]
        self.assertEqual(events, ["unknown"])

    async def test_unapproved_draft_prepares_but_never_requests_submit(self):
        self.session.options["submit_enabled"] = False
        self.session.phase = "preflight"
        self.manager.page.results = [{"status": "proof", "evidence": {}}]
        await self.session.advance()
        self.assertTrue(self.session.stopped)
        self.assertNotIn("submit_intent", [a["event"] for n, a in self.api.calls if n == "queue_event"])

    async def test_changed_fingerprint_prevents_media_handoff(self):
        self.session.phase = "input"
        self.api.task["job"]["fingerprint"] = "changed"
        self.manager.page.results = [{"status": "ready", "index": 0}]
        await self.session.advance()
        self.assertEqual(self.manager.page.files, [])
        self.assertTrue(self.session.stopped)

    async def test_media_control_never_receives_files_twice(self):
        self.session.phase = "input"
        await self.session.handle({"status": "ready", "index": 0})
        self.assertEqual(self.manager.page.files, [[str(self.path.resolve())]])
        self.session.phase = "input"
        with self.assertRaises(Attention):
            await self.session.handle({"status": "ready", "index": 0})
        self.assertEqual(len(self.manager.page.files), 1)

    async def test_lost_media_callback_does_not_resend_files(self):
        self.session.phase = "input"
        self.manager.page.results = [{"status": "ready", "index": 0}]
        self.manager.page.set_input_files = AsyncMock(side_effect=RuntimeError("callback lost"))
        await self.session.advance()
        await self.session.advance()
        self.assertTrue(self.session.upload_delivered)
        self.assertTrue(self.session.stopped)
        self.assertEqual(self.manager.page.set_input_files.await_count, 1)

    async def test_login_after_upload_stops_without_reupload(self):
        self.session.upload_delivered = True
        self.session.phase = "fill"
        self.manager.page.results = [{"status": "login"}]
        await self.session.advance()
        self.assertTrue(self.session.stopped)
        self.assertEqual(self.manager.page.files, [])
        self.assertEqual(self.api.state, "needs_attention")

    async def test_cancel_refusal_preserves_active_session(self):
        self.worker.sessions["q1"] = self.session
        original = self.api.action
        async def refusing(name, args=None):
            if name == "queue_cancel":
                raise RuntimeError("already submitted")
            return await original(name, args)
        self.api.action = refusing
        with self.assertRaises(RuntimeError):
            await self.worker.cancel("q1")
        self.assertFalse(self.session.stopped)

    async def test_result_requires_official_content_evidence(self):
        self.session.phase, self.session.intent_sent = "result_verify", True
        self.manager.page.results = [{"status": "result", "result_status": "published", "note_id": "b" * 24, "url": "https://www.rednote.com/discovery/item/" + "b" * 24, "evidence": {"content_verified": False}}]
        await self.session.advance()
        self.assertEqual(self.api.state, "unknown")
        self.assertNotIn("published", [a["event"] for n, a in self.api.calls if n == "queue_event"])


class BrowserBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def test_profile_paths_are_isolated_and_cannot_escape(self):
        manager = BrowserManager(Path("/tmp/spt-fixture"), None)
        paths = {manager.profile_path("../../private", "xiaohongshu"), manager.profile_path("a2", "xiaohongshu"), manager.profile_path("../../private", "instagram")}
        self.assertEqual(len(paths), 3)
        for path in paths:
            self.assertTrue(path.is_relative_to(manager.root / "data/windows/browser-profiles"))
            self.assertEqual(len(path.name), 64)

    def test_official_urls_reject_lookalikes_local_and_credentials(self):
        allowed = ("rednote.com",)
        self.assertTrue(official_url("https://creator.rednote.com/publish/publish", allowed))
        for value in ("http://creator.rednote.com/", "https://rednote.com.evil.invalid/", "https://127.0.0.1/", "file:///private/file", "https://user:pass@rednote.com/", "https://rednote.com:8443/"):
            self.assertFalse(official_url(value, allowed), value)
        with self.assertRaises(ValueError):
            LocalAPI("https://example.invalid")

    async def test_download_survives_context_close_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "Downloads"
            target.mkdir()
            (target / "report.csv").write_text("old")
            class Download:
                suggested_filename = "report.csv"
                async def save_as(self, name):
                    Path(name).write_text("new")
            manager = BrowserManager(folder, None, downloads=target)
            await manager._save_download(Download())
            self.assertEqual((target / "report.csv").read_text(), "old")
            self.assertEqual((target / "report-1.csv").read_text(), "new")


if __name__ == "__main__":
    unittest.main()
