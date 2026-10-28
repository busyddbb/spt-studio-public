"""Historical metrics keep their identity, cohort and source boundaries."""
from __future__ import annotations
import csv
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ..dashboard import dashboard_snapshot
from ..dashboard_accounts import account_snapshot, attach_snapshots
from ..dashboard_io import number
from ..dashboard_parenting import parenting_posts, parenting_snapshot
from ..dashboard_posts import normalize_posts
from ..schema import SCHEMA


class DashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.ak = self.root / "ak"
        self.parenting = self.root / "parenting"
        self.data = self.ak / "系统（不用看）/数据"
        self.write_projects()
        registry = {"platforms": [{"id": "instagram",
                                  "account_identity": "test_kitchen"}],
                    "current_management_targets": [
                        "instagram", "facebook", "tiktok",
                        "google_business_profile", "yelp"]}
        self.write(self.ak / "系统（不用看）/总控/平台登记.json",
                   json.dumps(registry))
        self.csv("account_daily.csv", [self.account_row()])
        self.csv("content_performance.csv", [])
        self.csv("trend_inbox.csv", [])
        self.write(self.parenting / "10-数据复盘/当前账号数据.md", "")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def csv(self, name: str, rows: list[dict[str, str]]) -> None:
        output = io.StringIO()
        names = list(dict.fromkeys(key for row in rows for key in row))
        writer = csv.DictWriter(output, fieldnames=names or ["empty"])
        writer.writeheader()
        writer.writerows(rows)
        self.write(self.data / name, output.getvalue())

    def write_projects(self) -> None:
        projects = [{"id": "parenting", "name": "示例创作者",
                     "kind": "account", "channels": ["xiaohongshu"],
                     "root_path": str(self.parenting)},
                    {"id": "demo-brand", "name": "Sample Studio",
                     "kind": "account", "channels": ["instagram"],
                     "root_path": str(self.ak)}]
        self.write(self.root / "app/projects.json", json.dumps(projects))

    def account_row(self, **updates: str) -> dict[str, str]:
        row = {"date": "2026-10-06", "platform": "instagram",
               "window_start": "2026-09-08", "window_end": "2026-10-05",
               "followers": "15", "views": "5555", "likes": "",
               "link_clicks": "0", "source": "Source", "notes": ""}
        row.update(updates)
        return row

    def post_row(self, **updates: str) -> dict[str, str]:
        row = {"content_id": "film", "platform": "instagram",
               "url": "https://www.instagram.com/reel/current/",
               "published_at": "2026-10-01", "status": "published",
               "caption_opener": "Only an opener.", "views_24h": "12"}
        row.update(updates)
        return row

    def test_six_targets_do_not_claim_login_or_live_metrics(self) -> None:
        result = dashboard_snapshot(self.root)
        self.assertEqual(len(result["accounts"]), 6)
        self.assertFalse(result["accounts"][-1]["readonly"])   # 2026-10-24: the app reads these pages itself
        self.assertFalse(result["capabilities"]["live_metrics"])
        self.assertEqual(result["accounts"][1]["metrics"]["views"], 5555)
        self.assertEqual(result["accounts"][1]["metrics"]["link_clicks"], 0)
        self.assertIsNone(result["accounts"][1]["metrics"]["likes"])
        self.assertTrue(all(account["login_state"] == "not_checked"
                            for account in result["accounts"]))

    def test_rounded_unknown_is_not_backfilled_from_older_data(self) -> None:
        old = self.account_row(platform="facebook", date="2026-10-01",
                               views="4236")
        new = self.account_row(platform="facebook", views="",
                               notes="Views=4.8K ; Viewers=4.1K")
        snapshot = account_snapshot(new, self.data)
        self.assertIsNone(snapshot["metrics"]["views"])
        self.assertEqual(snapshot["display_metrics"]["views"], "4.8K")
        result = dashboard_snapshot(self.root)
        attach_snapshots(result["accounts"], [old, new], self.data)
        item = next(a for a in result["accounts"]
                    if a["platform"] == "facebook")
        self.assertIsNone(item["metrics"]["views"])
        self.assertEqual(len(item["history"]), 2)

    def test_generic_instagram_combined_reach_stays_unknown(self) -> None:
        row = self.account_row(reach="", notes="Reach=5.2K rounded; "
                               "generic combined-platform Results")
        snapshot = account_snapshot(row, self.data)
        self.assertIsNone(snapshot["metrics"]["reach"])
        self.assertNotIn("reach", snapshot["display_metrics"])

    def test_same_post_cohorts_are_preserved_without_summing(self) -> None:
        first = self.post_row(notes="observed_at=2026-10-02T01:00:00Z")
        second = self.post_row(views_24h="", views_72h="37",
                               notes="observed_at=2026-10-04T01:00:00Z")
        posts = normalize_posts([first, second], self.data)
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["metrics_by_window"]["D1"]["views"], 12)
        self.assertEqual(posts[0]["metrics_by_window"]["D3"]["views"], 37)
        self.assertEqual(posts[0]["metrics"]["views"], 37)
        self.assertEqual(posts[0]["metric_window"], "D3")
        self.assertEqual(len(posts[0]["history"]), 2)
        self.assertFalse(posts[0]["caption_complete"])

    def test_new_partial_cohort_does_not_fill_older_fields(self) -> None:
        old = self.post_row(notes="observed_at=2026-10-02T01:00:00Z")
        new = self.post_row(views_24h="", likes_24h="2",
                           notes="observed_at=2026-10-02T03:00:00Z")
        post = normalize_posts([old, new], self.data)[0]
        self.assertIsNone(post["metrics"]["views"])
        self.assertEqual(post["metrics"]["likes"], 2)
        self.assertEqual(post["observed_at"], "2026-10-02T03:00:00Z")

    def test_unchecked_media_is_not_current_post_video(self) -> None:
        from ..dashboard_links import preview_url
        for state in ("mismatch", "not_applicable", "not_checked"):
            with self.subTest(state=state):
                self.assertIsNone(preview_url(self.root,
                                             {"media_match": state}))

    def test_withdrawn_url_does_not_merge_with_replacement(self) -> None:
        old = self.post_row(status="withdrawn",
                            url="https://www.instagram.com/reel/old/")
        current = self.post_row()
        posts = normalize_posts([old, current], self.data)
        self.assertEqual(len(posts), 2)
        self.assertEqual(sum(post["current"] for post in posts), 1)
        removed = self.post_row(status="deleted_user_confirmed", notes="")
        earlier = self.post_row(notes="observed_at=2026-10-04T01:00:00Z")
        self.assertFalse(normalize_posts([earlier, removed],
                                         self.data)[0]["current"])

    def test_parenting_keeps_original_observation_and_age(self) -> None:
        text = ("本地接收2026-10-20。最近已报账号：199粉、11关注、"
                "赞藏圆整显示1.7K，原观察2026-10-18 03:32:41 PDT\n"
                "| 52 D1 | 37 | 2 | 0 | 0 | 0 | 10/18 20:16:49 | "
                "26.7017h，迟2.7017h |")
        snapshot = parenting_snapshot(text, self.root)
        self.assertEqual(snapshot["observed_at"],
                         "2026-10-18T03:32:41-07:00")
        self.assertEqual(snapshot["metrics"]["followers"], 199)
        post = parenting_posts(text, self.root)[0]
        self.assertEqual(post["source_kind"], "metric_node")
        self.assertIsNone(post["published_at"])
        self.assertIsNone(post["caption"])
        self.assertEqual(post["history"][0]["age_note"],
                         "26.7017h，迟2.7017h")

    def test_unknown_and_zero_are_distinct(self) -> None:
        self.assertIsNone(number(""))
        self.assertIsNone(number("4.8K"))
        self.assertIsNone(number("unknown"))
        self.assertIsNone(number("9" * 500))
        self.assertEqual(number("0"), 0)
        self.assertEqual(number("1,250"), 1250)
        self.assertEqual(number("9.8"), 9.8)

    def test_missing_sources_are_local_errors_not_demo_fallback(self) -> None:
        (self.data / "account_daily.csv").unlink()
        result = dashboard_snapshot(self.root)
        self.assertEqual(len(result["accounts"]), 6)
        self.assertIsNone(result["accounts"][1]["metrics"]["views"])
        self.assertEqual(result["posts"], [])
        self.assertEqual(len(result["issues"]), 1)
        self.assertFalse(result["intelligence"]["live"])

    def test_current_work_url_can_supply_full_caption_readonly(self) -> None:
        self.csv("content_performance.csv", [self.post_row()])
        path = self.root / "spt/server/.cache/index.sqlite3"
        path.parent.mkdir(parents=True)
        with sqlite3.connect(path) as connection:
            connection.executescript(SCHEMA)
            connection.execute("INSERT INTO works "
                               "(id,title,media_match,cover_source) "
                               "VALUES('work','轮播','match','封面.jpg')")
            connection.execute("INSERT INTO publish_records "
                               "(work_id,position,platform,url,state) "
                               "VALUES('work',0,'instagram',?,'current')",
                               (self.post_row()["url"],))
            connection.execute("INSERT INTO package_sections "
                               "VALUES('work','instagram','Full caption.\n')")
        before = path.read_bytes()
        post = dashboard_snapshot(self.root)["posts"][0]
        self.assertTrue(post["caption_complete"])
        self.assertEqual(post["caption"], "Full caption.\n")
        self.assertEqual(post["work_id"], "work")
        self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
