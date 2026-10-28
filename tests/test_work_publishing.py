from contextlib import closing
import os
import json
import tempfile
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app import core, work_publishing
from spt.server.parsing import parse_records


class WorkPublishingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="work-publishing-")
        self.root = Path(self.tmp.name)
        self.db = self.root / "media.sqlite3"
        self.old_db = os.environ.get("MEDIA_DB")
        self.old_ws = os.environ.get("SPT_WORKSPACE")
        self.old_core_db = core.DB
        os.environ["MEDIA_DB"] = str(self.db)
        os.environ["SPT_WORKSPACE"] = str(self.root)
        core.DB = self.db
        self.accounts = [core.create_account({"platform": "xiaohongshu", "handle": f"{i+1:024x}", "name": f"A{i}"})["account"] for i in range(3)]
        self.ig = core.create_account({"platform": "instagram", "handle": "ig", "name": "IG"})["account"]

    def tearDown(self):
        if self.old_db is None:
            os.environ.pop("MEDIA_DB", None)
        else:
            os.environ["MEDIA_DB"] = self.old_db
        if self.old_ws is None:
            os.environ.pop("SPT_WORKSPACE", None)
        else:
            os.environ["SPT_WORKSPACE"] = self.old_ws
        core.DB = self.old_core_db
        self.tmp.cleanup()

    def work(self, video=False):
        root = self.root / ("2026-10-23-X-测试视频" if video else "2026-10-23-X-测试")
        version = root / "V1"
        version.mkdir(parents=True)
        (root / "发布标题.txt").write_text("标题原样\n", encoding="utf-8")
        (root / "发布正文.txt").write_text("正文第一行\n正文第二行\n", encoding="utf-8")
        (root / "发布话题.txt").write_text("爸爸带娃\n带娃日常\n", encoding="utf-8")
        (version / ("01.mp4" if video else "01.jpg")).write_bytes(b"media")
        return str(root)

    def test_preview_reads_exact_content_and_media(self):
        result = work_publishing.preview(self.work())
        self.assertEqual(result["title"], "标题原样")
        self.assertIn("正文第一行", result["body"])
        self.assertEqual(result["media"][0]["kind"], "image")
        self.assertFalse(result["issues"])

    def test_manifest_missing_media_blocks_without_fallback(self):
        work_id = self.work()
        (Path(work_id) / "资料").mkdir()
        (Path(work_id) / "资料" / "manifest.json").write_text('{"images_in_order":[{"path":"V1/01.jpg"},{"path":"V1/02-missing.jpg"}]}', encoding="utf-8")
        result = work_publishing.preview(work_id)
        self.assertTrue(any("媒体缺失" in issue for issue in result["issues"]))
        self.assertEqual(result["media"], [])

    def test_reference_and_hidden_media_are_excluded(self):
        work_id = self.work()
        version = Path(work_id) / "V1"
        (version / "参考-构图.png").write_bytes(b"reference")
        (version / ".hidden.png").write_bytes(b"hidden")
        result = work_publishing.preview(work_id)
        self.assertEqual([m["name"] for m in result["media"]], ["01.jpg"])

    def test_manifest_path_escape_blocks(self):
        work_id = self.work()
        (Path(work_id) / "资料").mkdir()
        (Path(work_id) / "资料" / "manifest.json").write_text('{"images_in_order":[{"path":"../outside.jpg"}]}', encoding="utf-8")
        result = work_publishing.preview(work_id)
        self.assertTrue(any("越界" in issue for issue in result["issues"]))

    def test_three_accounts_claims_at_most_two_and_serializes_same_account(self):
        jobs = work_publishing.enqueue_work({"work_id": self.work(), "account_ids": [a["id"] for a in self.accounts]})["jobs"]
        claimed = work_publishing.claim({"executor_id": "e1"})["tasks"]
        self.assertEqual(len(claimed), 2)
        self.assertEqual(len({t["job"]["account_id"] for t in claimed}), 2)
        claimed_again = work_publishing.claim({"executor_id": "e2"})["tasks"]
        self.assertEqual(len(claimed_again), 0)

    def test_concurrent_claimers_respect_two_slots(self):
        work_id = self.work()
        work_publishing.enqueue_work({"work_id": work_id, "account_ids": [a["id"] for a in self.accounts]})
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda i: work_publishing.claim({"executor_id": f"parallel-{i}"})["tasks"], range(3)))
        claimed = [task for group in results for task in group]
        self.assertLessEqual(len(claimed), 2)
        self.assertEqual(len({task["job"]["account_id"] for task in claimed}), len(claimed))

    def test_duplicate_enqueue_is_idempotent_without_new_job(self):
        args = {"work_id": self.work(), "account_ids": [self.accounts[0]["id"]]}
        first = work_publishing.enqueue_work(args)["jobs"]
        second = work_publishing.enqueue_work(args)["jobs"]
        self.assertEqual(first[0]["id"], second[0]["id"])
        self.assertEqual(len(work_publishing.snapshot()["jobs"]), 1)

    def test_changed_fingerprint_cannot_bypass_existing_account_task(self):
        work_id = self.work()
        work_publishing.enqueue_work({"work_id": work_id, "account_ids": [self.accounts[0]["id"]]})
        (Path(work_id) / "发布正文.txt").write_text("正文被改动\n", encoding="utf-8")
        with self.assertRaises(core.ValidationError):
            work_publishing.enqueue_work({"work_id": work_id, "account_ids": [self.accounts[0]["id"]]})

    def test_receipt_account_mapping_allows_other_account(self):
        work_id = self.work()
        url = "https://www.rednote.com/discovery/item/000000000000000000000065"
        receipt_dir = Path(work_id) / "资料" / "发布记录"
        receipt_dir.mkdir(parents=True)
        (receipt_dir / "old-回执.json").write_text(json.dumps({"url": url, "account_id": self.accounts[0]["id"]}), encoding="utf-8")
        detail = {"work": {"id": work_id, "title": "测试"}, "records": [{"url": url, "account": ""}], "versions": [], "finals": []}
        with patch("app.work_publishing._work", return_value=(Path(work_id), detail)):
            jobs = work_publishing.enqueue_work({"work_id": work_id, "account_ids": [self.accounts[1]["id"]]})["jobs"]
        self.assertEqual(jobs[0]["account_id"], self.accounts[1]["id"])

    def test_video_is_a_single_media_item(self):
        result = work_publishing.preview(self.work(video=True))
        self.assertEqual([m["kind"] for m in result["media"]], ["video"])

    def test_submit_intent_is_once_and_unknown_cannot_cancel(self):
        job = work_publishing.enqueue_work({"work_id": self.work(), "account_ids": [self.accounts[0]["id"]], "submit_enabled": True})["jobs"][0]
        work_publishing.claim({"executor_id": "local"})
        proof = {"identity_verified": True, "account_profile_id": self.accounts[0]["handle"], "duplicate_checked": True, "upload_complete": True, "media_count": 1, "media_order": ["01.jpg"], "title": "标题原样", "body": "正文第一行\n正文第二行\n", "topics": ["爸爸带娃", "带娃日常"], "topics_complete": True, "settings": {"allow_body_copy": False, "scheduled": False, "visibility": "public"}, "settings_verified": True}
        work_publishing.event({"id": job["id"], "event": "preflight", "executor_id": "local", "evidence": proof})
        work_publishing.event({"id": job["id"], "event": "submit_intent", "executor_id": "local"})
        again = work_publishing.event({"id": job["id"], "event": "submit_intent", "executor_id": "local"})["job"]
        self.assertTrue(again["submit_intent"]["once"])
        work_publishing.event({"id": job["id"], "event": "unknown", "executor_id": "local"})
        with self.assertRaises(core.ValidationError):
            work_publishing.cancel({"id": job["id"]})

    def test_retry_only_before_upload(self):
        job = work_publishing.enqueue_work({"work_id": self.work(), "account_ids": [self.accounts[0]["id"]], "submit_enabled": True})["jobs"][0]
        work_publishing.claim({"executor_id": "local"})
        work_publishing.event({"id": job["id"], "event": "needs_attention", "executor_id": "local", "message": "账号栏无法确认"})
        again = work_publishing.retry({"id": job["id"]})["job"]
        self.assertEqual(again["state"], "queued")
        self.assertIsNone(again["executor_id"])
        self.assertEqual(len(work_publishing.claim({"executor_id": "local2"})["tasks"]), 1)
        work_publishing.event({"id": job["id"], "event": "uploading", "executor_id": "local2"})
        work_publishing.event({"id": job["id"], "event": "needs_attention", "executor_id": "local2"})
        self.assertEqual(work_publishing.retry({"id": job["id"]})["job"]["state"], "queued")
        work_publishing.claim({"executor_id": "local3"})
        work_publishing.event({"id": job["id"], "event": "processing", "executor_id": "local3"})
        work_publishing.event({"id": job["id"], "event": "needs_attention", "executor_id": "local3"})
        with self.assertRaises(core.ValidationError):
            work_publishing.retry({"id": job["id"]})

    def test_retry_after_a_tagged_pre_click_stop_only(self):
        job = work_publishing.enqueue_work({"work_id": self.work(), "account_ids": [self.accounts[0]["id"]], "submit_enabled": True})["jobs"][0]
        work_publishing.claim({"executor_id": "local"})
        proof = {"identity_verified": True, "account_profile_id": self.accounts[0]["handle"], "duplicate_checked": True, "upload_complete": True, "media_count": 1, "media_order": ["01.jpg"], "title": "标题原样", "body": "正文第一行\n正文第二行\n", "topics": ["爸爸带娃", "带娃日常"], "topics_complete": True, "settings": {"allow_body_copy": False, "scheduled": False, "visibility": "public"}, "settings_verified": True}
        work_publishing.event({"id": job["id"], "event": "preflight", "executor_id": "local", "evidence": proof})
        work_publishing.event({"id": job["id"], "event": "submit_intent", "executor_id": "local"})
        work_publishing.event({"id": job["id"], "event": "needs_attention", "executor_id": "local", "message": "结果不明"})
        with self.assertRaises(core.ValidationError):
            work_publishing.retry({"id": job["id"]})
        work_publishing.event({"id": job["id"], "event": "needs_attention", "executor_id": "local", "message": "[未点击] 发布前核对未通过：按钮没找到"})
        again = work_publishing.retry({"id": job["id"]})["job"]
        self.assertEqual(again["state"], "queued")
        self.assertIsNone(again["submit_intent"])

    def test_void_needs_backstage_check_and_frees_a_new_task(self):
        work = self.work()
        job = work_publishing.enqueue_work({"work_id": work, "account_ids": [self.accounts[0]["id"]], "submit_enabled": True})["jobs"][0]
        work_publishing.claim({"executor_id": "local"})
        work_publishing.event({"id": job["id"], "event": "needs_attention", "executor_id": "local", "message": "停住"})
        with self.assertRaises(core.ValidationError):
            work_publishing.void({"id": job["id"], "message": "后台无此笔记"})
        voided = work_publishing.void({"id": job["id"], "checked_backstage": True, "message": "后台无此笔记"})["job"]
        self.assertEqual(voided["state"], "failed")
        with self.assertRaises(core.ValidationError):
            work_publishing.void({"id": job["id"], "checked_backstage": True, "message": "再来"})
        fresh = work_publishing.enqueue_work({"work_id": work, "account_ids": [self.accounts[0]["id"]], "submit_enabled": True})["jobs"][0]
        self.assertNotEqual(fresh["id"], job["id"])
        self.assertEqual(fresh["state"], "queued")

    def test_hide_removes_a_stopped_task_from_the_list_only(self):
        job = work_publishing.enqueue_work({"work_id": self.work(), "account_ids": [self.accounts[0]["id"]]})["jobs"][0]
        with self.assertRaises(core.ValidationError):
            work_publishing.hide({"id": job["id"]})
        work_publishing.cancel({"id": job["id"]})
        work_publishing.hide({"id": job["id"], "message": "已发完"})
        self.assertNotIn(job["id"], [j["id"] for j in work_publishing.snapshot()["jobs"]])
        with work_publishing._db() as c:
            self.assertEqual(c.execute("SELECT state FROM publishing_queue WHERE id=?", (job["id"],)).fetchone()[0], "cancelled")

    def test_unsupported_platform_is_explicit(self):
        with self.assertRaises(core.ValidationError):
            work_publishing.enqueue_work({"work_id": self.work(), "account_ids": [self.ig["id"]]})

    def test_defaults_are_scoped_per_account_and_claim_options_are_explicit(self):
        work_id = self.work()
        work_publishing.save_defaults({"account_id": self.accounts[0]["id"], "defaults": {"allow_body_copy": True, "topics": ["A"]}})
        work_publishing.save_defaults({"account_id": self.accounts[1]["id"], "defaults": {"allow_body_copy": False, "topics": ["B"]}})
        jobs = work_publishing.enqueue_work({"work_id": work_id, "account_ids": [self.accounts[0]["id"], self.accounts[1]["id"]], "submit_enabled": True})["jobs"]
        self.assertEqual(jobs[0]["options"]["topics"], ["A"])
        self.assertEqual(jobs[1]["options"]["topics"], ["B"])
        task = work_publishing.claim({"executor_id": "defaults"})["tasks"][0]
        self.assertIn("expected_name", task["options"])
        self.assertIn("allow_body_copy", task["options"])
        self.assertEqual(task["options"]["topics"], jobs[0]["topics"])
        self.assertEqual(task["options"]["expected_profile_id"], jobs[0]["options"]["expected_profile_id"])
        snap = work_publishing.snapshot()
        by_id = {a["id"]: a for a in snap["accounts"]}
        self.assertEqual(by_id[self.accounts[0]["id"]]["defaults"]["topics"], ["A"])
        self.assertEqual(by_id[self.accounts[1]["id"]]["defaults"]["topics"], ["B"])

    def test_partial_defaults_update_preserves_existing_fields(self):
        aid = self.accounts[0]["id"]
        work_publishing.save_defaults({"account_id": aid, "defaults": {"topics": ["A", "A"], "visibility": "public", "allow_body_copy": True}})
        updated = work_publishing.save_defaults({"account_id": aid, "defaults": {"visibility": "private"}})["defaults"]
        self.assertEqual(updated["topics"], ["A"])
        self.assertTrue(updated["allow_body_copy"])
        self.assertEqual(updated["visibility"], "private")

    def test_empty_work_topics_use_isolated_account_defaults_and_empty_is_legal(self):
        work_id = self.work()
        (Path(work_id) / "发布话题.txt").unlink()
        work_publishing.save_defaults({"account_id": self.accounts[0]["id"], "defaults": {"topics": ["A"]}})
        work_publishing.save_defaults({"account_id": self.accounts[1]["id"], "defaults": {"topics": ["B"]}})
        jobs = work_publishing.enqueue_work({"work_id": work_id, "account_ids": [self.accounts[0]["id"], self.accounts[1]["id"]], "submit_enabled": True})["jobs"]
        self.assertEqual(jobs[0]["topics"], ["A"])
        self.assertEqual(jobs[1]["topics"], ["B"])
        # A third account with no default is allowed to publish with zero topics.
        empty = work_publishing.enqueue_work({"work_id": work_id, "account_ids": [self.accounts[2]["id"]], "submit_enabled": True})["jobs"][0]
        self.assertEqual(empty["topics"], [])

    def test_unclaimed_final_event_is_rejected(self):
        job = work_publishing.enqueue_work({"work_id": self.work(), "account_ids": [self.accounts[0]["id"]], "submit_enabled": True})["jobs"][0]
        with self.assertRaises(core.ValidationError):
            work_publishing.event({"id": job["id"], "event": "published", "executor_id": "forged", "note_id": "000000000000000000000065", "url": "https://www.rednote.com/explore/000000000000000000000065", "evidence": {}})

    def test_legacy_record_without_account_identity_blocks_enqueue(self):
        work_id = self.work()
        (Path(work_id) / "发布记录.md").write_text(
            "作品链接：https://www.rednote.com/discovery/item/000000000000000000000065\n", encoding="utf-8")
        with patch("app.work_publishing._work", return_value=(Path(work_id), {"work": {"id": work_id, "title": "测试"}, "records": [{"url": "https://www.rednote.com/discovery/item/000000000000000000000065", "account": ""}], "versions": [], "finals": []})):
            with self.assertRaises(core.ValidationError):
                work_publishing.enqueue_work({"work_id": work_id, "account_ids": [self.accounts[0]["id"]]})

    def test_schedule_without_timezone_is_rejected(self):
        with self.assertRaises(core.ValidationError):
            work_publishing.enqueue_work({"work_id": self.work(), "account_ids": [self.accounts[0]["id"]], "scheduled_at": "2030-01-01T12:00:00"})

    def test_mtime_change_blocks_submit_intent(self):
        work_id = self.work()
        job = work_publishing.enqueue_work({"work_id": work_id, "account_ids": [self.accounts[0]["id"]], "submit_enabled": True})["jobs"][0]
        work_publishing.claim({"executor_id": "mtime"})
        media = Path(work_id) / "V1" / "01.jpg"
        media.write_bytes(b"changed")
        work_publishing.event({"id": job["id"], "event": "preflight", "executor_id": "mtime", "evidence": {"identity_verified": True, "account_profile_id": self.accounts[0]["handle"], "duplicate_checked": True, "upload_complete": True, "media_count": 1, "media_order": ["01.jpg"], "title": "标题原样", "body": "正文第一行\n正文第二行\n", "topics": ["爸爸带娃", "带娃日常"], "topics_complete": True, "settings": {"allow_body_copy": False, "scheduled": False, "visibility": "public"}, "settings_verified": True}})
        with self.assertRaises(core.ValidationError):
            work_publishing.event({"id": job["id"], "event": "submit_intent", "evidence": {"identity_verified": True, "duplicate_checked": True, "upload_complete": True, "topics_complete": True, "settings_verified": True}})

    def test_unknown_locks_same_account(self):
        first = work_publishing.enqueue_work({"work_id": self.work(), "account_ids": [self.accounts[0]["id"]]})["jobs"][0]
        work_publishing.claim({"executor_id": "locked"})
        work_publishing.event({"id": first["id"], "event": "unknown", "executor_id": "locked"})
        second = work_publishing.enqueue_work({"work_id": self.work(video=True), "account_ids": [self.accounts[0]["id"]]})["jobs"][0]
        self.assertEqual(work_publishing.claim({"executor_id": "locked"})["tasks"], [])

    def test_published_requires_real_result_and_archive_is_repeat_safe(self):
        job = work_publishing.enqueue_work({"work_id": self.work(), "account_ids": [self.accounts[0]["id"]], "submit_enabled": True})["jobs"][0]
        work_publishing.claim({"executor_id": "result"})
        work_publishing.event({"id": job["id"], "event": "preflight", "executor_id": "result", "evidence": {"identity_verified": True, "account_profile_id": self.accounts[0]["handle"], "duplicate_checked": True, "upload_complete": True, "media_count": 1, "media_order": ["01.jpg"], "title": "标题原样", "body": "正文第一行\n正文第二行\n", "topics": ["爸爸带娃", "带娃日常"], "topics_complete": True, "settings": {"allow_body_copy": False, "scheduled": False, "visibility": "public"}, "settings_verified": True}})
        evidence = {"identity_verified": True, "duplicate_checked": True, "upload_complete": True, "topics_complete": True, "settings_verified": True}
        work_publishing.event({"id": job["id"], "event": "submit_intent", "executor_id": "result", "evidence": evidence})
        with self.assertRaises(core.ValidationError):
            work_publishing.event({"id": job["id"], "event": "published", "executor_id": "result"})
        nid = "000000000000000000000065"
        review_evidence = {"content_verified": True, "result_status": "under_review", "account_profile_id": self.accounts[0]["handle"], "title": "标题原样", "body": "正文第一行\n正文第二行\n", "topics": ["爸爸带娃", "带娃日常"], "media_count": 1}
        review_url = "https://www.rednote.com/explore/" + nid
        work_publishing.event({"id": job["id"], "event": "under_review", "executor_id": "result", "note_id": nid, "url": review_url, "evidence": review_evidence})
        review_records = parse_records((Path(job["work_id"]) / "发布记录.md").read_text(encoding="utf-8"), "发布记录.md", False)
        self.assertFalse(review_records)
        work_publishing.event({"id": job["id"], "event": "under_review", "executor_id": "result", "note_id": nid, "url": review_url, "evidence": review_evidence})
        result_evidence = {"content_verified": True, "result_status": "published", "account_profile_id": self.accounts[0]["handle"], "title": "标题原样", "body": "正文第一行\n正文第二行\n", "topics": ["爸爸带娃", "带娃日常"], "media_count": 1}
        done = work_publishing.event({"id": job["id"], "event": "published", "executor_id": "result", "note_id": nid, "url": "https://www.rednote.com/explore/" + nid, "published_at": "2026-10-23T01:00:00+00:00", "basis": "click_proxy", "evidence": result_evidence})["job"]
        published_records = parse_records((Path(job["work_id"]) / "发布记录.md").read_text(encoding="utf-8"), "发布记录.md", False)
        self.assertEqual(len(published_records), 1)
        self.assertEqual(published_records[0].url, review_url)
        self.assertTrue(any(record.verified for record in published_records))
        again = work_publishing.event({"id": job["id"], "event": "published", "executor_id": "result"})["job"]
        self.assertEqual(done["id"], again["id"])
        self.assertEqual(len(list((Path(done["work_id"]) / "资料" / "发布记录").glob("*-回执.json"))), 1)

    def test_screenshot_is_saved_by_path_and_base64_never_persisted(self):
        import base64, sqlite3
        job = work_publishing.enqueue_work({"work_id": self.work(), "account_ids": [self.accounts[0]["id"]], "submit_enabled": True})["jobs"][0]
        work_publishing.claim({"executor_id": "screen"})
        proof = {"identity_verified": True, "account_profile_id": self.accounts[0]["handle"], "duplicate_checked": True, "upload_complete": True, "media_count": 1, "media_order": ["01.jpg"], "title": "标题原样", "body": "正文第一行\n正文第二行\n", "topics": ["爸爸带娃", "带娃日常"], "topics_complete": True, "settings": {"allow_body_copy": False, "scheduled": False, "visibility": "public"}, "settings_verified": True, "png_base64": base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()}
        work_publishing.event({"id": job["id"], "event": "preflight", "executor_id": "screen", "evidence": proof})
        with closing(sqlite3.connect(self.db)) as db, db:
            raw = db.execute("SELECT payload FROM publishing_queue WHERE id=?", (job["id"],)).fetchone()[0]
        self.assertNotIn("png_base64", raw)
        self.assertTrue(json.loads(raw)["evidence"]["screenshot_path"].endswith("-evidence.png"))


if __name__ == "__main__":
    unittest.main()
