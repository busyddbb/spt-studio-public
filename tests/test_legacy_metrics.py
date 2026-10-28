"""Legacy DB numbers reach the dashboard read-only, once, in LA dates.

Every test points core.DB at a temporary database; the workbench's real data
directory is never read or changed.
"""
from __future__ import annotations
from contextlib import closing

import copy
import csv
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import core, legacy_metrics, operations, studio_bridge

URL = "https://www.instagram.com/p/abc123/"
REDNOTE = "https://www.rednote.com/user/profile/000000000000000000000001"


def social_row(**changes: str) -> dict[str, str]:
    row = dict.fromkeys(core.SOCIAL_FIELDS, "")
    row.update(platform="instagram", account="sample_studio",
               post_id="abc123", title="三道菜", url=URL,
               published_at="2026-10-15T10:00:00Z",
               observed_at="2026-10-16T17:00:00Z", views="100")
    row.update(changes)
    return row


def ads_row(**changes: str) -> dict[str, str]:
    row = dict.fromkeys(core.ADS_FIELDS, "")
    row.update(platform="google_ads", account="广告账户", campaign="到店引流",
               date="2026-10-15", impressions="1000", clicks="10",
               spend="12.5", conversions="1", currency="USD")
    row.update(changes)
    return row


def csv_text(kind: str, rows: list[dict[str, str]]) -> str:
    stream = io.StringIO(newline="")
    fields = core.SOCIAL_FIELDS if kind == "social" else core.ADS_FIELDS
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def account(brand: str, channel: str, handle: str | None,
            profile_url: str | None) -> dict[str, object]:
    return {"id": brand + ":" + channel, "brand_id": brand, "brand": brand,
            "platform": channel, "platform_label": channel, "handle": handle,
            "profile_url": profile_url, "metrics": {}, "history": [],
            "posts_count": 0}


def ak_post() -> dict[str, object]:
    windows = {label: dict.fromkeys(("views", "likes")) for label in
               ("D1", "D3", "D7")}
    windows["D7"]["views"] = 190
    return {"id": "ak-post", "account_id": "demo-brand:instagram",
            "content_id": "2026-09-24_水晶虾饺", "title": "水晶虾饺",
            "url": URL, "published_at": "2026-09-24T01:47:00-07:00",
            "status": "published", "current": True,
            "source_kind": "post_record",
            "observed_at": "2026-10-01T08:47:25+00:00",
            "metrics": windows["D7"], "metric_window": "D7",
            "metrics_by_window": windows,
            "metric_observed_at_by_window": {
                "D1": None, "D3": None, "D7": "2026-10-01T08:47:25+00:00"},
            "history": [{"observed_at": "2026-10-01T08:47:25+00:00",
                         "metrics_by_window": windows}],
            "source": "content_performance.csv", "issues": []}


def fixture() -> dict[str, object]:
    return {"accounts": [
                account("demo-brand", "instagram", "sample_studio",
                        "https://www.instagram.com/sample_studio/"),
                account("parenting", "rednote", REDNOTE, REDNOTE)],
            "posts": [ak_post()], "history_posts": [],
            "capabilities": {"readonly_metrics": True}}


class LegacyMetricsTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="legacy-metrics-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.db = self.root / "data" / "media.sqlite3"
        config = self.root / "projects.json"
        config.write_text(json.dumps({"projects": []}), encoding="utf-8")
        for target, name, value in ((core, "DB", self.db),
                                    (operations, "PROJECTS_CONFIG", config)):
            replacement = patch.object(target, name, value)
            replacement.start()
            self.addCleanup(replacement.stop)

    def import_social(self, *rows: dict[str, str]) -> None:
        core.import_csv("social", csv_text("social", list(rows)), "社媒.csv")

    def import_ads(self, *rows: dict[str, str]) -> None:
        core.import_csv("ads", csv_text("ads", list(rows)), "广告.csv")

    def merged(self, snapshot: dict[str, object] | None = None,
               identities: list[dict[str, str]] | None = None
               ) -> dict[str, object]:
        snapshot = snapshot if snapshot is not None else fixture()
        legacy_metrics.merge(snapshot, identities)
        return snapshot

    def receipt(self, url: str = "https://www.instagram.com/p/receipt1/",
                published_at: str = "2026-10-01T10:00:00Z") -> dict[str, object]:
        handle = core.create_account({"platform": "instagram",
                                      "handle": "sample_studio",
                                      "name": "AK"})["account"]
        draft = core.create_draft({"title": "发布记录里的作品", "body": "正文",
                                   "account_ids": [handle["id"]],
                                   "media_ids": []})["draft"]
        core.update_draft(draft["id"], {"status": "review"})
        core.update_draft(draft["id"], {"status": "approved"})
        operations.bind_draft({"draft_id": draft["id"], "project_id": "",
                               "format": "图文", "brief": "目标",
                               "checklist": {"content": True, "media": True,
                                             "account": True}})
        return operations.save_receipt({
            "draft_id": draft["id"], "account_id": handle["id"], "url": url,
            "published_at": published_at, "note": ""})["receipt"]

    def test_social_rows_become_posts_with_windows_in_local_dates(self) -> None:
        self.import_social(
            social_row(account="someone", likes="10", clicks="3"),
            social_row(account="someone", observed_at="2026-10-18T17:00:00Z",
                       views="300"),
            social_row(account="someone", observed_at="2026-10-25T17:00:00Z",
                       views="900", saves="4"),
            # 23:30Z is still 10-15 in Los Angeles: one calendar day → D1.
            social_row(account="someone", post_id="late", url="",
                       published_at="2026-10-15T23:30:00Z",
                       observed_at="2026-10-17T02:00:00Z", views="7"))
        snapshot = self.merged({"accounts": [], "posts": [],
                                "history_posts": []})
        posts = {post["content_id"]: post for post in snapshot["posts"]}
        post = posts["abc123"]
        self.assertEqual(post["published_at"], "2026-10-15T03:00:00-07:00")
        self.assertEqual(post["title"], "三道菜")
        self.assertEqual(post["url"], URL)
        windows = post["metrics_by_window"]
        self.assertEqual((windows["D1"]["views"], windows["D1"]["clicks"],
                          windows["D1"]["interactions"]), (100, 3, None))
        self.assertEqual(windows["D3"]["views"], 300)
        self.assertFalse(any(value is not None
                             for value in windows["D7"].values()))
        self.assertEqual(post["metric_observed_at_by_window"],
                         {"D1": "2026-10-16T10:00:00-07:00",
                          "D3": "2026-10-18T10:00:00-07:00", "D7": None})
        # Latest = the most recent snapshot, even outside every window.
        self.assertIsNone(post["metric_window"])
        self.assertEqual((post["metrics"]["views"], post["metrics"]["saves"]),
                         (900, 4))
        self.assertEqual(post["observed_at"], "2026-10-25T10:00:00-07:00")
        self.assertEqual([item["window"] for item in post["history"]],
                         ["D1", "D3", None])
        self.assertEqual(post["history"][0]["source_type"], "csv")
        self.assertEqual(post["source"], "社媒.csv")
        self.assertEqual(posts["late"]["metric_window"], "D1")
        self.assertEqual(posts["late"]["published_at"],
                         "2026-10-15T16:30:00-07:00")
        self.assertEqual(len(snapshot["accounts"]), 1)
        self.assertEqual(snapshot["accounts"][0]["posts_count"], 2)
        self.assertEqual(post["account_id"], snapshot["accounts"][0]["id"])

    def test_posts_attach_to_dashboard_accounts_by_platform_and_handle(self) -> None:
        self.import_social(
            social_row(account="SAMPLE_STUDIO", post_id="ig1", url=""),
            social_row(platform="xiaohongshu", account=REDNOTE, post_id="n54",
                       url=""))
        snapshot = self.merged()
        by_id = {post["content_id"]: post["account_id"]
                 for post in snapshot["posts"]}
        self.assertEqual(by_id["ig1"], "demo-brand:instagram")
        self.assertEqual(by_id["n54"], "parenting:rednote")
        self.assertEqual([item["id"] for item in snapshot["accounts"]],
                         ["demo-brand:instagram", "parenting:rednote"])
        self.assertEqual([item["posts_count"] for item in snapshot["accounts"]],
                         [2, 1])
        self.assertEqual(snapshot["posts"][0]["content_id"], "ig1",
                         "newest first, like the dashboard sorts")

    def test_unknown_handles_get_an_import_only_account(self) -> None:
        self.import_social(
            social_row(platform="google_business", account="Sample Studio SF",
                       post_id="gb1", url=""),
            social_row(platform="youtube", account="Sample Studio SF",
                       post_id="yt1", url=""))
        identities = [{"id": "gb-id", "platform": "google_business",
                       "handle": "sample studio sf"}]
        snapshot = self.merged(identities=identities)
        added = snapshot["accounts"][2:]
        self.assertEqual([item["platform"] for item in added],
                         ["google_business_profile", "youtube"])
        self.assertEqual([item["platform_label"] for item in added],
                         ["Google 商家资料", "YouTube"])
        business = added[0]
        self.assertTrue(business["id"].startswith("import:"))
        self.assertEqual(business["brand_id"], added[1]["brand_id"],
                         "one handle on two platforms is one brand group")
        self.assertEqual((business["brand"], business["handle"]),
                         ("Sample Studio SF", "Sample Studio SF"))
        self.assertEqual(business["legacy_account_id"], "gb-id")
        self.assertIsNone(added[1]["legacy_account_id"])
        self.assertEqual(business["posts_count"], 1)
        self.assertEqual(business["origin"], "csv_import")
        self.assertIsNone(business["metrics"]["followers"],
                          "account metrics are never derived from posts")
        self.assertIsNone(business["as_of"])
        post = next(post for post in snapshot["posts"]
                    if post["content_id"] == "gb1")
        self.assertEqual(post["account_id"], business["id"])

    def test_a_csv_account_spelled_like_a_brand_joins_that_brand(self) -> None:
        self.import_social(
            social_row(platform="youtube", account="Demo-Brand",
                       post_id="yt1", url=""))
        snapshot = self.merged()
        added = snapshot["accounts"][2]
        self.assertTrue(added["id"].startswith("import:"),
                        "its own id: never collides with a dashboard account")
        self.assertEqual((added["brand_id"], added["brand"], added["handle"]),
                         ("demo-brand", "demo-brand", "Demo-Brand"))
        self.assertEqual(added["origin"], "csv_import")

    def test_matching_posts_are_not_counted_twice_and_own_windows_win(self) -> None:
        self.import_social(
            social_row(post_id="ignored-id", published_at="2026-09-24T08:47:00Z",
                       observed_at="2026-09-25T15:00:00Z", views="120"),
            social_row(post_id="ignored-id", published_at="2026-09-24T08:47:00Z",
                       observed_at="2026-10-01T15:00:00Z", views="500"))
        snapshot = self.merged()
        self.assertEqual(len(snapshot["posts"]), 1)
        post = snapshot["posts"][0]
        self.assertEqual(post["id"], "ak-post")
        self.assertEqual(post["title"], "水晶虾饺")
        self.assertEqual(post["metrics_by_window"]["D7"]["views"], 190,
                         "the dashboard's own D7 stays whole")
        self.assertEqual(post["metrics_by_window"]["D1"]["views"], 120)
        self.assertEqual(post["metric_observed_at_by_window"]["D1"],
                         "2026-09-25T08:00:00-07:00")
        self.assertEqual(post["metric_window"], "D7")
        self.assertEqual(post["metrics"]["views"], 190)
        self.assertEqual(post["observed_at"], "2026-10-01T08:47:25+00:00")
        self.assertEqual(len(post["history"]), 3)
        self.assertEqual(snapshot["accounts"][0]["posts_count"], 0,
                         "nothing new was added, counts are left alone")
        self.import_social(
            social_row(post_id="ignored-id", published_at="2026-09-24T08:47:00Z",
                       observed_at="2026-10-14T15:00:00Z", views="800"))
        later = self.merged()["posts"][0]
        self.assertIsNone(later["metric_window"])
        self.assertEqual(later["metrics"]["views"], 800)
        self.assertEqual(later["observed_at"], "2026-10-14T08:00:00-07:00")
        self.assertEqual(later["metrics_by_window"]["D7"]["views"], 190)

    def test_receipt_numbers_beat_csv_rows_in_the_same_window(self) -> None:
        receipt = self.receipt()
        operations.record_metrics({"receipt_id": receipt["id"],
                                   "observed_at": "2026-10-04T10:00:00Z",
                                   "views": 50, "likes": 5})
        self.import_social(
            social_row(post_id="r1", url=receipt["url"],
                       published_at="2026-10-01T10:00:00Z",
                       observed_at="2026-10-02T20:00:00Z", views="20"),
            social_row(post_id="r1", url=receipt["url"],
                       published_at="2026-10-01T10:00:00Z",
                       observed_at="2026-10-04T20:00:00Z", views="55"))
        snapshot = self.merged()
        added = [post for post in snapshot["posts"] if post["id"] != "ak-post"]
        self.assertEqual(len(added), 1, "receipt URL and CSV rows are one post")
        post = added[0]
        self.assertEqual(post["account_id"], "demo-brand:instagram")
        self.assertEqual(post["title"], "发布记录里的作品")
        self.assertEqual(post["url"], receipt["url"])
        self.assertEqual((post["metrics_by_window"]["D3"]["views"],
                          post["metrics_by_window"]["D3"]["likes"]), (50, 5))
        self.assertEqual(post["metric_observed_at_by_window"]["D3"],
                         "2026-10-04T03:00:00-07:00")
        self.assertEqual(post["metrics_by_window"]["D1"]["views"], 20)
        self.assertEqual(post["metric_window"], "D3")
        self.assertEqual(post["metrics"]["views"], 50,
                         "the newer CSV row does not split the window")
        self.assertEqual({item["source_type"] for item in post["history"]},
                         {"manual_receipt", "csv"})
        self.assertEqual(len(post["history"]), 3)

    def test_voided_receipt_numbers_do_not_come_back(self) -> None:
        receipt = self.receipt()
        operations.record_metrics({"receipt_id": receipt["id"],
                                   "observed_at": "2026-10-02T10:00:00Z",
                                   "views": 40})
        self.assertEqual(len(self.merged()["posts"]), 2)
        operations.void_receipt({"id": receipt["id"], "reason": "链接选错"})
        with closing(sqlite3.connect(self.db)) as connection, connection:
            kept = connection.execute("SELECT COUNT(*) FROM ops_metrics")
            self.assertEqual(kept.fetchone()[0], 1, "history stays in ops_metrics")
        self.assertEqual([post["id"] for post in self.merged()["posts"]],
                         ["ak-post"])

    def test_ads_rows_become_campaign_days(self) -> None:
        self.assertNotIn("ads", self.merged())
        self.import_ads(ads_row(), ads_row(date="2026-10-16", clicks="12"),
                        ads_row(campaign="品牌", currency="CAD", spend="3"))
        self.import_ads(ads_row(clicks="11"))
        snapshot = self.merged()
        self.assertEqual(snapshot["ads"], {"campaigns": [
            {"platform": "google_ads", "account": "广告账户", "campaign": "到店引流",
             "currency": "USD", "days": [
                 {"date": "2026-10-15", "impressions": 1000, "clicks": 11,
                  "spend": 12.5, "conversions": 1},
                 {"date": "2026-10-16", "impressions": 1000, "clicks": 12,
                  "spend": 12.5, "conversions": 1}]},
            {"platform": "google_ads", "account": "广告账户", "campaign": "品牌",
             "currency": "CAD", "days": [
                 {"date": "2026-10-15", "impressions": 1000, "clicks": 10,
                  "spend": 3, "conversions": 1}]}]})
        self.assertEqual(len(snapshot["posts"]), 1)

    def test_without_legacy_rows_the_snapshot_is_unchanged(self) -> None:
        before = fixture()
        self.assertEqual(legacy_metrics.merge(copy.deepcopy(before)), [])
        self.assertFalse(self.db.exists())
        core.connect().close()
        empty = fixture()
        legacy_metrics.merge(empty)
        self.assertEqual(empty, before)
        self.assertNotIn("ads", empty)
        other = self.root / "accounts-only.sqlite3"
        with closing(sqlite3.connect(other)) as connection, connection:
            connection.execute("CREATE TABLE accounts (id,platform,handle,payload)")
        with patch.object(core, "DB", other):
            partial = fixture()
            legacy_metrics.merge(partial)
        self.assertEqual(partial, before)

    def test_reading_never_writes_the_database(self) -> None:
        self.import_social(social_row(post_id="fresh", url=""))
        self.import_ads(ads_row())
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        before = self.db.read_bytes()
        snapshot = self.merged()
        self.assertEqual(len(snapshot["posts"]), 2)
        self.assertIn("ads", snapshot)
        self.assertEqual(self.db.read_bytes(), before)

    def test_a_wal_database_without_its_side_files_is_still_read(self) -> None:
        self.import_social(social_row(post_id="wal", url=""))
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        for suffix in ("-wal", "-shm"):
            side = self.db.with_name(self.db.name + suffix)
            if side.exists():
                side.unlink()
        posts = self.merged()["posts"]
        self.assertIn("wal", [post["content_id"] for post in posts])
        self.assertEqual(legacy_metrics.read_rows(self.db, "SELECT 1 FROM nowhere"), [])

    def test_accounts_known_only_to_the_legacy_db_get_a_card_once(self) -> None:
        core.create_account({"platform": "instagram", "handle": "sample_studio",
                             "name": "AK 官方", "brand": "Sample Studio"})
        own = core.create_account({"platform": "xiaohongshu", "handle": "busy_dad",
                                   "name": "本人账号", "brand": "客户B"})["account"]
        self.import_social(social_row(platform="xiaohongshu", account="busy_dad",
                                      post_id="mine", url=""))
        with patch("spt.server.dashboard.dashboard_snapshot",
                   return_value=fixture()):
            context = studio_bridge.dashboard_context()
        ids = [item["id"] for item in context["accounts"]]
        self.assertEqual(ids, ["demo-brand:instagram", "parenting:rednote",
                               "legacy:" + own["id"]],
                         "the matched row is not repeated; the other appears once")
        self.assertIsNotNone(context["accounts"][0]["legacy_account_id"])
        added = context["accounts"][2]
        self.assertEqual((added["platform"], added["platform_label"]),
                         ("rednote", "rednote"))
        self.assertEqual((added["brand"], added["name"], added["handle"]),
                         ("客户B", "本人账号", "busy_dad"))
        self.assertEqual(added["legacy_account_id"], own["id"])
        self.assertEqual((added["history"], added["as_of"]), ([], None))
        self.assertEqual(added["origin"], "legacy_accounts")
        self.assertEqual(added["posts_count"], 1, "the CSV post lands on it")
        post = next(post for post in context["posts"] if post["content_id"] == "mine")
        self.assertEqual(post["account_id"], added["id"])
        with patch("spt.server.dashboard.dashboard_snapshot",
                   return_value=fixture()):
            again = studio_bridge.dashboard_context()
        self.assertEqual([item["id"] for item in again["accounts"]], ids)

    def test_dashboard_context_merges_legacy_numbers(self) -> None:
        self.import_social(social_row(post_id="ctx", url=""))
        with patch("spt.server.dashboard.dashboard_snapshot",
                   return_value=fixture()):
            context = studio_bridge.dashboard_context()
        ids = [post["content_id"] for post in context["posts"]]
        self.assertEqual(ids, ["ctx", "2026-09-24_水晶虾饺"])
        self.assertTrue(context["capabilities"]["legacy_publishing"])
        self.assertNotIn("ads", context)
        self.assertIsNone(context["accounts"][0]["legacy_account_id"])


if __name__ == "__main__":
    unittest.main()
