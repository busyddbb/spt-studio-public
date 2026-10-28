from __future__ import annotations
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import uuid

from app import core, media_uploads, operations, publishing


class PublishingWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patch = patch.object(core, 'DB', self.root / 'media.sqlite3')
        self.patch.start()
        self.account = core.create_account({'platform': 'instagram', 'handle': 'only-local-qa',
                                            'name': '仅隔离验收'})['account']
        self.image = self.root / '01.png'
        self.image.write_bytes(b'local-only-test')
        self.asset = media_uploads.register_files([str(self.image)])['jobs'][0]
        self.draft = core.create_draft({'title': '仅验收', 'body': 'IG主稿',
            'platforms': ['instagram'], 'account_ids': [self.account['id']],
            'media_ids': [self.asset['id']], 'platform_variants': {'instagram': 'IG独立文案'}})['draft']

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def approve(self):
        core.update_draft(self.draft['id'], {'status': 'review'})
        core.update_draft(self.draft['id'], {'status': 'approved'})
        operations.bind_draft({'draft_id': self.draft['id'], 'project_id': '',
                              'checklist': {'content': True, 'media': True, 'account': True}})

    def test_meta_suite_target_reuses_the_account_session_for_instagram_and_facebook(self):
        meta = publishing.workspace(self.account['id'], target='meta_suite')
        plain = publishing.workspace(self.account['id'])
        self.assertEqual(meta['platform']['id'], 'meta_suite')
        self.assertEqual(meta['platform']['publish_url'], 'https://business.facebook.com/latest/home')
        self.assertEqual(meta['profile_id'], plain['profile_id'], 'same login container')
        tiktok = core.create_account({'platform': 'tiktok', 'handle': 'tk-qa', 'name': 'TikTok'})['account']
        with self.assertRaises(core.ValidationError):
            publishing.workspace(tiktok['id'], target='meta_suite')
        with self.assertRaises(core.ValidationError):
            publishing.workspace(self.account['id'], target='elsewhere')
        with self.assertRaises(core.ValidationError):
            publishing.workspace(self.account['id'], self.draft['id'], target='meta_suite')

    def test_profile_is_stable_and_different_accounts_are_isolated(self):
        one = publishing.workspace(self.account['id'])
        two = publishing.workspace(self.account['id'])
        self.assertEqual(one['profile_id'], two['profile_id'])
        self.assertIsInstance(uuid.UUID(one['profile_id']), uuid.UUID)
        other = core.create_account({'platform': 'instagram', 'handle': 'second-local-qa', 'name': '第二账号'})['account']
        self.assertNotEqual(one['profile_id'], publishing.workspace(other['id'])['profile_id'])
        self.assertFalse(publishing.snapshot()['automatic_platform_confirmation'])

    def test_opening_profile_does_not_imply_login_or_create_receipt(self):
        self.assertFalse(publishing.snapshot()['accounts'][0]['session_saved'])
        publishing.workspace(self.account['id'])
        snapshot = publishing.snapshot()
        self.assertTrue(snapshot['accounts'][0]['session_saved'])
        self.assertIn('请在官方页确认', snapshot['accounts'][0]['session_label'])
        self.assertEqual(operations.snapshot()['receipts'], [])

    def test_upload_requires_approval_and_current_checks(self):
        blocked = publishing.workspace(self.account['id'], self.draft['id'])
        self.assertFalse(blocked['can_upload_current'])
        self.approve()
        ready = publishing.workspace(self.account['id'], self.draft['id'])
        self.assertTrue(ready['can_upload_current'])
        self.assertEqual(ready['draft']['body'], 'IG独立文案')
        self.assertEqual(ready['media'][0]['path'], str(self.image))

    def test_changed_media_or_text_invalidates_upload(self):
        self.approve()
        self.image.write_bytes(b'source-was-changed')
        result = publishing.workspace(self.account['id'], self.draft['id'])
        self.assertFalse(result['can_upload_current'])
        self.assertFalse(result['media'][0]['available'])
        self.assertTrue(result['issues'])

    def test_target_mismatch_and_unknown_accounts_are_rejected(self):
        other = core.create_account({'platform': 'tiktok', 'handle': 'other-local-qa', 'name': '仅验收二'})['account']
        with self.assertRaises(core.ValidationError):
            publishing.workspace(other['id'], self.draft['id'])
        with self.assertRaises(core.ValidationError):
            publishing.workspace('https://arbitrary-site.test/')

    def rednote_draft(self):
        account = core.create_account({'platform': 'xiaohongshu', 'handle': 'rednote-qa', 'name': '隔离rednote'})['account']
        core.update_draft(self.draft['id'], {'account_ids': [account['id']]})
        self.approve()
        return account

    def test_background_upload_is_explicit_and_blocks_duplicate_or_false_publish(self):
        account = self.rednote_draft()
        result = publishing.prepare_upload({'account_id': account['id'], 'draft_id': self.draft['id']})
        self.assertEqual(result['job']['target'], 'image')
        self.assertFalse(result['job']['published'])
        with self.assertRaises(core.ValidationError):
            publishing.prepare_upload({'account_id': account['id'], 'draft_id': self.draft['id']})
        with self.assertRaises(core.ValidationError):
            publishing.update_upload({'id': result['job']['id'], 'state': 'published', 'message': 'bad'})
        self.assertEqual(operations.snapshot()['receipts'], [])

    def test_login_resume_keeps_job_and_cancel_cannot_be_overwritten(self):
        account = self.rednote_draft()
        args = {'account_id': account['id'], 'draft_id': self.draft['id']}
        job = publishing.prepare_upload(args)['job']
        publishing.update_upload({'id': job['id'], 'state': 'needs_login', 'message': '请登录'})
        self.assertEqual(publishing.prepare_upload(args)['job']['id'], job['id'])
        publishing.dispatch('cancel_upload', {'id': job['id']})
        with self.assertRaises(core.ValidationError):
            publishing.update_upload({'id': job['id'], 'state': 'uploading', 'message': 'late'})
        self.assertNotEqual(publishing.prepare_upload(args)['job']['id'], job['id'])

    def test_upload_context_rereads_source_integrity(self):
        account = self.rednote_draft()
        job = publishing.prepare_upload({'account_id': account['id'], 'draft_id': self.draft['id']})['job']
        self.image.write_bytes(b'changed since upload prepared')
        self.assertFalse(publishing.upload_context(job['id'])['workspace']['can_upload_current'])

    def test_human_receipt_releases_account_without_claiming_automatic_publish(self):
        account = self.rednote_draft()
        args = {'account_id': account['id'], 'draft_id': self.draft['id']}
        job = publishing.prepare_upload(args)['job']
        publishing.update_upload({'id': job['id'], 'state': 'awaiting_review', 'message': '待核对'})
        receipt = operations.save_receipt({**args, 'url': 'https://www.rednote.com/explore/local-qa',
            'published_at': '2026-10-01T10:00:00Z'})['receipt']
        closed = publishing.upload_context(job['id'])['job']
        self.assertEqual(closed['state'], 'recorded')
        self.assertEqual(closed['receipt_source'], 'manual')
        self.assertFalse(closed['published'])
        with self.assertRaises(core.ValidationError):
            publishing.prepare_upload(args)
        next_draft = core.create_draft({'title': '下一条', 'body': '下一篇正文',
            'account_ids': [account['id']], 'media_ids': [self.asset['id']]})['draft']
        core.update_draft(next_draft['id'], {'status': 'review'})
        core.update_draft(next_draft['id'], {'status': 'approved'})
        operations.bind_draft({'draft_id': next_draft['id'], 'project_id': '',
            'checklist': {'content': True, 'media': True, 'account': True}})
        next_args = {'account_id': account['id'], 'draft_id': next_draft['id']}
        next_job = publishing.prepare_upload(next_args)['job']
        self.assertNotEqual(next_job['id'], job['id'])
        publishing.dispatch('cancel_upload', {'id': next_job['id']})
        operations.void_receipt({'id': receipt['id'], 'reason': '隔离验收纠错'})
        self.assertEqual(publishing.upload_context(job['id'])['job']['state'], 'awaiting_review')
        with self.assertRaises(core.ValidationError):
            publishing.prepare_upload(next_args)


if __name__ == '__main__':
    unittest.main()
