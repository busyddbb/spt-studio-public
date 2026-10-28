"""Business invariants for imported evidence and local-only publication drafts.

Every test replaces core.DB with a temporary database. Running this file never
reads or changes the workbench's real data directory.
"""
from __future__ import annotations

import csv
import io
import sqlite3
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import core


def social_row(**changes):
    row = dict.fromkeys(core.SOCIAL_FIELDS, "")
    row.update(
        platform="instagram", account="创作账号 A", post_id="post-1",
        title="同一内容的真实记录", url="https://example.com/posts/1",
        published_at="2026-10-15T10:00:00Z",
        observed_at="2026-10-16T07:00:00Z",
        views="100", likes="10", comments="0", shares="0", saves="0",
    )
    row.update(changes)
    return row


def ads_row(**changes):
    row = dict.fromkeys(core.ADS_FIELDS, "")
    row.update(
        platform="google_ads", account="广告账号 A", campaign="作品集引流",
        date="2026-10-15", impressions="1000", clicks="10",
        spend="12.50", conversions="1", currency="USD",
    )
    row.update(changes)
    return row


def csv_text(kind, rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream, fieldnames=core.SOCIAL_FIELDS if kind == "social" else core.ADS_FIELDS
    )
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


class IsolatedCoreTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="media-core-test-")
        self.addCleanup(temp.cleanup)
        self.temp_root = Path(temp.name)
        replacement = patch.object(core, "DB", self.temp_root / "media.sqlite3")
        replacement.start()
        self.addCleanup(replacement.stop)

    def import_social(self, *rows, filename="social.csv"):
        return core.import_csv("social", csv_text("social", rows), filename)

    def import_ads(self, *rows, filename="ads.csv"):
        return core.import_csv("ads", csv_text("ads", rows), filename)

    def row_counts(self):
        with core.connection() as connection:
            return {
                name: connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                for name in ("observations", "imports", "audit", "drafts", "accounts")
            }

    def make_draft(self, **changes):
        values = {
            "title": "可审阅内容",
            "body": "这是一条待发布的正文。",
            "platforms": ["instagram"],
        }
        values.update(changes)
        return core.create_draft(values)["draft"]

    def approve(self, draft):
        core.update_draft(draft["id"], {"status": "review"})
        return core.update_draft(draft["id"], {"status": "approved"})["draft"]

    def saved_draft(self, identifier):
        return next(d for d in core.state("real")["drafts"] if d["id"] == identifier)


class ConnectionLifetimeTests(IsolatedCoreTest):
    def test_transaction_commits_then_releases_the_database(self):
        with core.connection() as connection:
            connection.execute("INSERT INTO audit VALUES (?,?,?,?)",
                               ("saved", "2026-10-27T00:00:00Z", "test", "{}"))
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")
        with core.connection() as reopened:
            self.assertEqual(reopened.execute("SELECT id FROM audit").fetchone()[0],
                             "saved")

    def test_failed_transaction_rolls_back_and_releases_the_database(self):
        with self.assertRaisesRegex(ValueError, "cancelled"):
            with core.connection() as connection:
                connection.execute("INSERT INTO audit VALUES (?,?,?,?)",
                                   ("discarded", "2026-10-27T00:00:00Z", "test", "{}"))
                raise ValueError("cancelled")
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")
        with core.connection() as reopened:
            self.assertEqual(reopened.execute("SELECT COUNT(*) FROM audit").fetchone()[0], 0)

    def test_initialization_failure_also_releases_the_database(self):
        class BrokenPragma(sqlite3.Connection):
            def execute(self, sql, *arguments):
                if sql.startswith("PRAGMA journal_mode"):
                    raise sqlite3.OperationalError("cannot initialize")
                return super().execute(sql, *arguments)

        connection = sqlite3.connect(":memory:", factory=BrokenPragma)
        with patch.object(core.sqlite3, "connect", return_value=connection):
            with self.assertRaisesRegex(sqlite3.OperationalError, "cannot initialize"):
                core.connect()
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")


class SnapshotImportTests(IsolatedCoreTest):
    def test_reimport_same_snapshot_never_doubles_metrics(self):
        first = self.import_social(social_row())
        second = self.import_social(social_row())
        self.assertEqual((first["imported"], first["updated"]), (1, 0))
        self.assertEqual((second["imported"], second["updated"]), (0, 1))
        result = core.state()
        self.assertEqual(len(result["posts"]), 1)
        self.assertEqual(result["summary"]["views"], 100)
        self.assertEqual(self.row_counts()["observations"], 1)

    def test_corrected_values_replace_same_snapshot(self):
        self.import_social(social_row(views="100"))
        self.import_social(social_row(views="125"), filename="corrected.csv")
        result = core.state()
        self.assertEqual(len(result["posts"]), 1)
        self.assertEqual(result["summary"]["views"], 125)
        self.assertEqual(result["posts"][0]["source"], "corrected.csv")

    def test_latest_observation_wins_even_if_older_file_arrives_last(self):
        self.import_social(social_row(views="250", observed_at="2026-10-16T07:00:00Z"))
        # This local time is 06:30 UTC, not later merely because it was imported last.
        self.import_social(social_row(views="80", observed_at="2026-10-15T23:30:00-07:00"))
        result = core.state()
        self.assertEqual(result["summary"]["views"], 250)
        self.assertEqual(result["posts"][0]["observed_at"], "2026-10-16T07:00:00+00:00")
        self.assertEqual(self.row_counts()["observations"], 2)

    def test_same_post_id_in_different_accounts_is_not_merged(self):
        self.import_social(
            social_row(account="账号 A", views="100"),
            social_row(account="账号 B", views="200"),
        )
        result = core.state()
        self.assertEqual({p["account"] for p in result["posts"]}, {"账号 A", "账号 B"})
        self.assertEqual(len({p["id"] for p in result["posts"]}), 2)
        self.assertEqual(result["summary"]["views"], 300)

    def test_same_account_and_post_id_on_different_platforms_remain_separate(self):
        self.import_social(
            social_row(platform="instagram"),
            social_row(platform="xiaohongshu"),
        )
        self.assertEqual(len(core.state()["posts"]), 2)

    def test_delimiters_in_account_and_post_identifiers_do_not_collide(self):
        self.import_social(
            social_row(account="studio|campaign", post_id="post", views="10"),
            social_row(account="studio", post_id="campaign|post", views="20"),
        )
        result = core.state()
        self.assertEqual(len(result["posts"]), 2)
        self.assertEqual(result["summary"]["views"], 30)

    def test_delimiters_in_ads_identity_do_not_overwrite_another_account(self):
        self.import_ads(
            ads_row(account="studio|campaign", campaign="launch", spend="5"),
            ads_row(account="studio", campaign="campaign|launch", spend="15"),
        )
        self.assertEqual(len(core.state()["ads"]), 2)
        self.assertEqual(core.state()["summary"]["ad_spend"], 20.0)

    def test_invalid_later_row_leaves_existing_metrics_and_audit_unchanged(self):
        self.import_social(social_row(views="100"))
        counts_before = self.row_counts()
        # The first row would replace saved evidence if validation were not atomic.
        with self.assertRaises(core.ValidationError):
            self.import_social(
                social_row(views="999"),
                social_row(post_id="post-2", views="-1"),
            )
        self.assertEqual(self.row_counts(), counts_before)
        self.assertEqual(core.state()["summary"]["views"], 100)

    def test_invalid_ads_row_does_not_partially_save_valid_spend(self):
        self.import_ads(ads_row())
        counts_before = self.row_counts()
        with self.assertRaises(core.ValidationError):
            self.import_ads(
                ads_row(campaign="new valid campaign", spend="200"),
                ads_row(campaign="bad date", date="2026-13-40"),
            )
        self.assertEqual(self.row_counts(), counts_before)
        self.assertEqual(core.state()["summary"]["ad_spend"], 12.5)

    def test_duplicate_alias_columns_and_extra_cells_are_rejected(self):
        for text in (
            "platform,平台,account\ninstagram,instagram,账号 A\n",
            csv_text("social", [social_row()]).rstrip("\r\n") + ",extra\n",
        ):
            with self.subTest(csv=text), self.assertRaises(core.ValidationError):
                core.import_csv("social", text)
        self.assertEqual(self.row_counts()["observations"], 0)

    def test_impossible_snapshot_date_is_rejected(self):
        with self.assertRaises(core.ValidationError):
            self.import_social(social_row(observed_at="2026-10-14T10:00:00Z"))
        self.assertEqual(self.row_counts()["observations"], 0)

    def test_demo_is_separate_from_real_records_and_drafts(self):
        self.import_social(social_row(views="321"))
        self.make_draft()
        counts_before = self.row_counts()
        demo = core.state("demo")
        self.assertTrue(demo["posts"])
        self.assertEqual(demo["drafts"], [])
        self.assertEqual(demo["imports"], [])
        self.assertEqual(core.state("real")["summary"]["views"], 321)
        self.assertEqual(self.row_counts(), counts_before)


class MetricMeaningTests(IsolatedCoreTest):
    def test_unknown_values_stay_unknown_in_records_and_summary(self):
        self.import_social(social_row(views="", likes="", comments="", shares="", saves=""))
        result = core.state()
        for field in ("views", "likes", "comments", "shares", "saves"):
            self.assertIsNone(result["posts"][0][field])
        for field in ("views", "engagements", "engagement_rate"):
            self.assertIsNone(result["summary"][field])
        self.assertEqual(result["summary"]["engagement_sample_count"], 0)

    def test_measured_zero_is_zero_and_never_causes_division_by_zero(self):
        self.import_social(social_row(views="0", likes="0", comments="0", shares="0", saves="0"))
        result = core.state()
        self.assertEqual(result["posts"][0]["views"], 0)
        self.assertEqual(result["summary"]["views"], 0)
        self.assertEqual(result["summary"]["engagements"], 0)
        self.assertIsNone(result["summary"]["engagement_rate"])

    def test_engagement_rate_uses_only_paired_complete_observations(self):
        self.import_social(
            social_row(post_id="complete-a", views="100", likes="10"),
            social_row(post_id="complete-b", views="900", likes="0"),
            social_row(post_id="missing-save", views="9000", likes="1000", saves=""),
            social_row(post_id="missing-views", views="", likes="40"),
        )
        result = core.state()["summary"]
        self.assertEqual(result["views"], 10000)
        self.assertEqual(result["engagements"], 50)
        self.assertEqual(result["engagement_sample_count"], 2)
        self.assertAlmostEqual(result["engagement_rate"], 1.0)

    def test_missing_metric_is_not_silently_replaced_with_zero(self):
        self.import_social(social_row(likes="10", saves=""))
        self.assertIsNone(core.state()["summary"]["engagement_rate"])
        self.import_social(social_row(likes="10", saves="0"))
        self.assertEqual(core.state()["summary"]["engagement_rate"], 10.0)

    def test_currencies_are_separate_and_no_mixed_total_is_reported(self):
        self.import_ads(
            ads_row(spend="12.50", currency="USD"),
            ads_row(spend="20", currency="EUR"),
            ads_row(campaign="second USD campaign", spend="7.50", currency="usd"),
        )
        result = core.state()
        self.assertEqual(len(result["ads"]), 3)
        self.assertEqual(result["summary"]["spend_by_currency"], {"EUR": 20.0, "USD": 20.0})
        self.assertIsNone(result["summary"]["ad_spend"])
        self.assertIsNone(result["summary"]["currency"])

    def test_ads_reimport_does_not_double_daily_spend(self):
        self.import_ads(ads_row())
        self.import_ads(ads_row())
        result = core.state()
        self.assertEqual(len(result["ads"]), 1)
        self.assertEqual(result["summary"]["ad_spend"], 12.5)

    def test_cpc_ignores_rows_without_matching_click_or_spend_evidence(self):
        self.import_ads(
            ads_row(campaign="paired", spend="20", clicks="10"),
            ads_row(campaign="unknown clicks", spend="80", clicks=""),
            ads_row(campaign="unknown spend", spend="", clicks="90"),
        )
        findings = core.analyze()["findings"]
        ads_finding = next(f for f in findings if f["title"] == "Google Ads · USD")
        self.assertIn("2.00 USD", ads_finding["detail"])
        self.assertIn("1 行", ads_finding["detail"])


class DraftReviewTests(IsolatedCoreTest):
    def test_new_draft_cannot_claim_approval_or_publication(self):
        draft = self.make_draft(status="published")
        self.assertEqual(draft["status"], "draft")
        self.assertEqual(draft["delivery"], "local_only")
        self.assertFalse(core.state()["remote_publishing_enabled"])

    def test_null_draft_text_is_rejected_without_creating_a_placeholder(self):
        for field in ("title", "body"):
            with self.subTest(field=field), self.assertRaises(core.ValidationError):
                self.make_draft(**{field: None})
        self.assertEqual(self.row_counts()["drafts"], 0)

    def test_null_text_update_leaves_approved_draft_unchanged(self):
        draft = self.approve(self.make_draft())
        for field in ("title", "body"):
            with self.subTest(field=field), self.assertRaises(core.ValidationError):
                core.update_draft(draft["id"], {field: None})
        saved = self.saved_draft(draft["id"])
        self.assertEqual(saved["status"], "approved")
        self.assertEqual(saved["title"], draft["title"])
        self.assertEqual(saved["body"], draft["body"])

    def test_body_accepts_declared_thirty_thousand_character_limit(self):
        draft = self.make_draft(body="文" * 30000)
        self.assertEqual(len(draft["body"]), 30000)
        with self.assertRaises(core.ValidationError):
            core.update_draft(draft["id"], {"body": "文" * 30001})
        self.assertEqual(len(self.saved_draft(draft["id"])["body"]), 30000)

    def test_approval_requires_review_and_valid_transition_persists(self):
        draft = self.make_draft()
        with self.assertRaises(core.ValidationError):
            core.update_draft(draft["id"], {"status": "approved"})
        self.assertEqual(self.saved_draft(draft["id"])["status"], "draft")
        approved = self.approve(draft)
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(self.saved_draft(draft["id"])["status"], "approved")

    def test_editing_approved_content_returns_it_to_draft(self):
        for change in (
            {"title": "改过的标题"},
            {"body": "改过的正文"},
            {"platforms": ["facebook"]},
            {"scheduled_at": "2026-10-20T12:00:00-07:00"},
        ):
            with self.subTest(change=change):
                draft = self.approve(self.make_draft())
                changed = core.update_draft(draft["id"], change)["draft"]
                self.assertEqual(changed["status"], "draft")
                self.assertEqual(changed["delivery"], "local_only")

    def test_content_cannot_be_changed_and_approved_in_one_step(self):
        draft = self.make_draft()
        core.update_draft(draft["id"], {"status": "review"})
        with self.assertRaises(core.ValidationError):
            core.update_draft(draft["id"], {"body": "未经审核的新正文", "status": "approved"})
        saved = self.saved_draft(draft["id"])
        self.assertEqual(saved["body"], draft["body"])
        self.assertEqual(saved["status"], "review")

    def test_no_local_transition_can_claim_published(self):
        draft = self.approve(self.make_draft())
        with self.assertRaises(core.ValidationError):
            core.update_draft(draft["id"], {"status": "published"})
        self.assertEqual(self.saved_draft(draft["id"])["status"], "approved")
        exported = core.export_drafts()
        self.assertIs(exported["published"], False)
        self.assertEqual(exported["delivery"], "local_only")

    def test_google_ads_cannot_be_a_posting_destination(self):
        with self.assertRaises(core.ValidationError):
            self.make_draft(platforms=["google_ads"])
        draft = self.make_draft()
        with self.assertRaises(core.ValidationError):
            core.update_draft(draft["id"], {"platforms": ["instagram", "google_ads"]})
        self.assertEqual(self.saved_draft(draft["id"])["platforms"], ["instagram"])
        self.assertEqual(len(core.state()["drafts"]), 1)


class AccountRegistryTests(IsolatedCoreTest):
    def register(self, handle="studio_a", **changes):
        values = {"platform": "instagram", "handle": handle, "name": "工作室 A", "brand": "品牌 A"}
        values.update(changes)
        return core.create_account(values)["account"]

    def test_registered_profile_merges_matching_imports_without_duplicate_account(self):
        account = self.register()
        self.import_social(social_row(account="studio_a", views="123"))
        result = core.state()
        self.assertEqual(len(result["accounts"]), 1)
        self.assertEqual(result["accounts"][0]["id"], account["id"])
        self.assertEqual(result["accounts"][0]["name"], "工作室 A")
        self.assertEqual(result["posts"][0]["account_id"], account["id"])
        self.assertEqual(result["accounts"][0]["metric_count"], 1)
        self.assertEqual(core.state()["accounts"][0]["metric_count"], 1)

    def test_duplicate_platform_handle_is_rejected_but_other_platform_is_distinct(self):
        instagram = self.register()
        with self.assertRaises(core.ValidationError):
            self.register(name="另一显示名")
        facebook = self.register(platform="facebook")
        self.assertNotEqual(instagram["id"], facebook["id"])
        self.assertEqual(len(core.state()["accounts"]), 2)

    def test_existing_csv_account_can_later_receive_a_profile(self):
        self.import_social(social_row(account="studio_a"))
        inferred_id = core.state()["accounts"][0]["id"]
        registered = self.register()
        self.assertEqual(registered["id"], inferred_id)
        self.assertEqual(len(core.state()["accounts"]), 1)
        self.assertEqual(core.state()["accounts"][0]["name"], "工作室 A")

    def test_csv_inferred_profile_can_be_updated_without_inflating_metric_count(self):
        self.import_social(social_row(account="studio_a"))
        inferred = core.state()["accounts"][0]
        core.update_account(inferred["id"], {"name": "正式显示名", "brand": "正式品牌"})
        result = core.state()
        self.assertEqual(len(result["accounts"]), 1)
        self.assertEqual(result["accounts"][0]["name"], "正式显示名")
        self.assertEqual(result["accounts"][0]["metric_count"], 1)
        self.assertEqual(core.state()["accounts"][0]["metric_count"], 1)
        self.assertEqual(len(result["posts"]), 1)

    def test_invalid_update_of_inferred_profile_leaves_registry_and_evidence_unchanged(self):
        self.import_social(social_row(account="studio_a"))
        account = core.state()["accounts"][0]
        counts_before = self.row_counts()
        with self.assertRaises(core.ValidationError):
            core.update_account(account["id"], {"name": None})
        self.assertEqual(self.row_counts(), counts_before)
        self.assertEqual(core.state()["accounts"][0]["metric_count"], 1)

    def test_account_filter_limits_metrics_drafts_and_analysis(self):
        account_a = self.register("studio_a")
        account_b = self.register("studio_b", name="工作室 B")
        self.import_social(
            social_row(account="studio_a", views="100", title="A 的作品"),
            social_row(account="studio_b", views="900", title="B 的作品"),
        )
        draft_a = self.make_draft(account_ids=[account_a["id"]])
        self.make_draft(account_ids=[account_b["id"]])
        self.make_draft()  # An unassigned platform-only draft is not owned by A.
        selected = core.state("real", account_a["id"])
        self.assertEqual([p["account"] for p in selected["posts"]], ["studio_a"])
        self.assertEqual(selected["summary"]["views"], 100)
        self.assertEqual([d["id"] for d in selected["drafts"]], [draft_a["id"]])
        analysis = core.analyze("real", account_a["id"])
        self.assertEqual(analysis["summary"]["views"], 100)
        self.assertIn("A 的作品", analysis["findings"][0]["detail"])
        self.assertNotIn("B 的作品", analysis["findings"][0]["detail"])

    def test_account_filter_does_not_include_another_ads_account_spend(self):
        selected_account = self.register("ads_a", platform="google_ads")
        self.register("ads_b", platform="google_ads", name="广告账号 B")
        self.import_ads(ads_row(account="ads_a", spend="5"), ads_row(account="ads_b", spend="95"))
        selected = core.state("real", selected_account["id"])
        self.assertEqual(len(selected["ads"]), 1)
        self.assertEqual(selected["summary"]["ad_spend"], 5.0)

    def test_profile_update_preserves_account_identity_and_attached_evidence(self):
        account = self.register()
        self.import_social(social_row(account="studio_a"))
        updated = core.update_account(account["id"], {"name": "新名字", "brand": "新品牌"})["account"]
        self.assertEqual(updated["id"], account["id"])
        self.assertEqual(updated["handle"], "studio_a")
        selected = core.state("real", account["id"])
        self.assertEqual(selected["summary"]["views"], 100)
        self.assertEqual(selected["accounts"][0]["name"], "新名字")

    def test_unknown_account_id_is_rejected_in_filter_and_draft(self):
        with self.assertRaises(core.ValidationError):
            core.state("real", "does-not-exist")
        with self.assertRaises(core.ValidationError):
            self.make_draft(account_ids=["does-not-exist"])
        self.assertEqual(self.row_counts()["drafts"], 0)

    def test_target_accounts_set_platforms_and_are_deduplicated(self):
        account = self.register(platform="xiaohongshu")
        draft = self.make_draft(account_ids=[account["id"], account["id"]])
        self.assertEqual(draft["account_ids"], [account["id"]])
        self.assertEqual(draft["platforms"], ["xiaohongshu"])

    def test_switching_approved_target_account_requires_fresh_review(self):
        account_a = self.register("studio_a")
        account_b = self.register("studio_b")
        draft = self.approve(self.make_draft(account_ids=[account_a["id"]]))
        updated = core.update_draft(draft["id"], {"account_ids": [account_b["id"]]})["draft"]
        self.assertEqual(updated["status"], "draft")
        self.assertEqual(updated["platforms"], ["instagram"])
        self.assertEqual(core.state("real", account_a["id"])["drafts"], [])
        self.assertEqual(len(core.state("real", account_b["id"])["drafts"]), 1)

    def test_google_ads_profile_cannot_be_a_draft_target(self):
        account = self.register(platform="google_ads")
        with self.assertRaises(core.ValidationError):
            self.make_draft(account_ids=[account["id"]])

    def test_null_required_account_values_are_not_saved_as_literal_none(self):
        for field in ("handle", "name"):
            with self.subTest(field=field), self.assertRaises(core.ValidationError):
                self.register(**{field: None})
        self.assertEqual(self.row_counts()["accounts"], 0)

    def test_invalid_account_id_collection_gives_validation_error_not_type_error(self):
        for value in ("one-id", None, [{}], [[]], [None], [42]):
            with self.subTest(value=value), self.assertRaises(core.ValidationError):
                self.make_draft(account_ids=value)
        self.assertEqual(self.row_counts()["drafts"], 0)

    def test_null_profile_name_update_is_rejected_and_keeps_previous_value(self):
        account = self.register()
        with self.assertRaises(core.ValidationError):
            core.update_account(account["id"], {"name": None})
        self.assertEqual(core.state()["accounts"][0]["name"], "工作室 A")


if __name__ == "__main__":
    unittest.main()
