"""Local media references, review invalidation, and honest export boundaries.

Fixtures are tiny files with an MP4 signature, not playable videos. These tests
check registration and draft references only; they do not claim video decoding
or remote platform upload/publishing verification.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import core, media_uploads


class MediaDraftBindingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="media-draft-binding-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        replacement = patch.object(core, "DB", self.root / "data" / "media.sqlite3")
        replacement.start()
        self.addCleanup(replacement.stop)

    def register_media(self, name="clip.mp4"):
        source = self.root / name
        source.write_bytes(
            b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2avc1mp41"
            + name.encode("utf-8")
        )
        media_uploads.register_files([str(source)])
        return next(
            job for job in media_uploads.snapshot()["jobs"]
            if job["path"] == str(source)
        )

    def make_draft(self, **changes):
        values = {"title": "本地素材草稿", "body": "待审核的发布正文", "platforms": ["instagram"]}
        values.update(changes)
        return core.create_draft(values)["draft"]

    def saved_draft(self, identifier):
        return next(d for d in core.state()["drafts"] if d["id"] == identifier)

    def approve(self, draft):
        core.update_draft(draft["id"], {"status": "review"})
        return core.update_draft(draft["id"], {"status": "approved"})["draft"]

    def test_new_and_legacy_drafts_default_to_no_media(self):
        draft = self.make_draft()
        self.assertEqual(draft["media_ids"], [])
        legacy = dict(draft)
        legacy.pop("media_ids")
        legacy["status"] = "review"
        with core.connection() as connection:
            connection.execute(
                "UPDATE drafts SET payload=? WHERE id=?",
                (json.dumps(legacy), draft["id"]),
            )
        self.assertEqual(self.saved_draft(draft["id"])["media_ids"], [])
        # Adding the compatibility default is not an edit requiring new review.
        approved = core.update_draft(draft["id"], {"status": "approved"})["draft"]
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(core.export_drafts()["media_assets"], [])

    def test_one_registered_file_is_reused_by_multiple_accounts_and_drafts(self):
        media = self.register_media()
        accounts = [
            core.create_account({"platform": "instagram", "handle": name, "name": name})["account"]
            for name in ("studio_a", "studio_b")
        ]
        first = self.make_draft(
            account_ids=[account["id"] for account in accounts], media_ids=[media["id"]]
        )
        second = self.make_draft(account_ids=[accounts[1]["id"]], media_ids=[media["id"]])
        self.assertEqual(first["media_ids"], second["media_ids"])
        self.assertEqual(len(media_uploads.snapshot()["jobs"]), 1)
        self.assertEqual(list(self.root.rglob("*.mp4")), [Path(media["path"])])
        self.assertEqual(
            {d["id"] for d in core.state(account_id=accounts[1]["id"])["drafts"]},
            {first["id"], second["id"]},
        )

    def test_media_ids_require_known_nonempty_string_ids_without_partial_save(self):
        media = self.register_media()
        draft = self.make_draft(media_ids=[media["id"]])
        for invalid in (None, media["id"], {}, [None], [1], [""], ["  "], ["missing"]):
            with self.subTest(media_ids=invalid):
                with self.assertRaises(core.ValidationError):
                    self.make_draft(media_ids=invalid)
                with self.assertRaises(core.ValidationError):
                    core.update_draft(draft["id"], {"media_ids": invalid})
                self.assertEqual(self.saved_draft(draft["id"])["media_ids"], [media["id"]])
        self.assertEqual(len(core.state()["drafts"]), 1)

    def test_duplicate_references_keep_first_order(self):
        first = self.register_media("first.mp4")
        second = self.register_media("second.mp4")
        draft = self.make_draft(media_ids=[second["id"], first["id"], second["id"]])
        self.assertEqual(draft["media_ids"], [second["id"], first["id"]])
        self.assertEqual(self.saved_draft(draft["id"])["media_ids"], draft["media_ids"])

    def test_replacing_or_removing_approved_media_withdraws_approval(self):
        first = self.register_media("first.mp4")
        second = self.register_media("second.mp4")
        for replacement in ([second["id"]], []):
            with self.subTest(replacement=replacement):
                draft = self.approve(self.make_draft(media_ids=[first["id"]]))
                updated = core.update_draft(draft["id"], {"media_ids": replacement})["draft"]
                self.assertEqual(updated["status"], "draft")
                self.assertEqual(updated["media_ids"], replacement)
                self.assertEqual(updated["delivery"], "local_only")

    def test_reviewed_media_cannot_be_replaced_and_approved_in_one_request(self):
        first = self.register_media("first.mp4")
        second = self.register_media("second.mp4")
        draft = self.make_draft(media_ids=[first["id"]])
        core.update_draft(draft["id"], {"status": "review"})
        with self.assertRaises(core.ValidationError):
            core.update_draft(draft["id"], {"media_ids": [second["id"]], "status": "approved"})
        saved = self.saved_draft(draft["id"])
        self.assertEqual(saved["status"], "review")
        self.assertEqual(saved["media_ids"], [first["id"]])

    def test_export_contains_only_referenced_assets_once_and_stays_local(self):
        first = self.register_media("first.mp4")
        second = self.register_media("second.mp4")
        unrelated = self.register_media("unrelated.mp4")
        self.approve(self.make_draft(media_ids=[first["id"], second["id"]]))
        self.make_draft(media_ids=[first["id"]])
        exported = core.export_drafts()
        self.assertEqual({a["id"] for a in exported["media_assets"]}, {first["id"], second["id"]})
        self.assertEqual(len(exported["media_assets"]), 2)
        self.assertNotIn(unrelated["id"], [a["id"] for a in exported["media_assets"]])
        keys = {"id", "name", "path", "size", "status", "provider_id", "provider_path"}
        for asset in exported["media_assets"]:
            self.assertEqual(set(asset), keys)
            self.assertEqual(asset["size"], Path(asset["path"]).stat().st_size)
        self.assertIs(exported["published"], False)
        self.assertEqual(exported["delivery"], "local_only")
        self.assertTrue(all("media_ids" in draft for draft in exported["drafts"]))

    def test_export_rejects_unresolved_asset_reference_instead_of_incomplete_package(self):
        draft = self.make_draft()
        draft["media_ids"] = ["deleted-or-missing-asset"]
        with core.connection() as connection:
            connection.execute(
                "UPDATE drafts SET payload=? WHERE id=?",
                (json.dumps(draft), draft["id"]),
            )
        with self.assertRaises(core.ValidationError):
            core.export_drafts()

    def test_cli_export_resolves_same_database_without_browser_or_package_path(self):
        media = self.register_media()
        self.make_draft(media_ids=[media["id"]])
        result = subprocess.run(
            [sys.executable, str(Path(core.__file__).parent / "cli.py"), "export_drafts"],
            cwd=self.root,
            env={**os.environ, "MEDIA_DB": str(core.DB)},
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        exported = json.loads(result.stdout)
        self.assertEqual([asset["id"] for asset in exported["media_assets"]], [media["id"]])
        self.assertIs(exported["published"], False)


if __name__ == "__main__":
    unittest.main()
