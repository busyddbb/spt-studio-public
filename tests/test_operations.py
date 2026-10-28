"""Human publishing and self-contained recovery, using isolated work data."""
from __future__ import annotations
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import core, media_uploads, operations


class OperationsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='media-operations-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.db = self.root / 'data' / 'media.sqlite3'
        self.config = self.root / 'projects.json'
        self.project_root = self.root / 'source-project'
        self.project_root.mkdir()
        (self.project_root / '开始这里.md').write_text('原项目独立保留', encoding='utf-8')
        self.config.write_text(json.dumps({'projects': [{'id': 'parenting', 'name': '育儿知识卡',
            'kind': '图文', 'root_path': str(self.project_root), 'entry_path': '开始这里.md',
            'delivery_path': 'outputs', 'summary': '真实资料', 'workflow': ['选题', '制作', '发布'],
            'channels': ['xiaohongshu'], 'boundary': '沿原项目规则', 'checked_at': '2026-10-20'}]}, ensure_ascii=False), encoding='utf-8')
        for target, attribute, value in ((core, 'DB', self.db), (operations, 'PROJECTS_CONFIG', self.config)):
            replacement = patch.object(target, attribute, value)
            replacement.start()
            self.addCleanup(replacement.stop)
        self.account = core.create_account({'platform': 'xiaohongshu', 'handle': 'real-handle', 'name': '本人账号'})['account']
        self.account_b = core.create_account({'platform': 'instagram', 'handle': 'second-real-handle', 'name': '英文账号'})['account']

    def create(self, approved=True, media_ids=None):
        draft = core.create_draft({'title': '同一个真实作品', 'body': '保留认可的中文主稿',
            'account_ids': [self.account['id'], self.account_b['id']],
            'platform_variants': {'instagram': 'The approved English version.'},
            'media_ids': media_ids or []})['draft']
        if approved:
            core.update_draft(draft['id'], {'status': 'review'})
            draft = core.update_draft(draft['id'], {'status': 'approved'})['draft']
        return draft

    def check(self, draft, **changes):
        values = {'draft_id': draft['id'], 'project_id': 'parenting', 'format': '图文',
                  'brief': '本次发布的目标', 'checklist': {'content': True, 'media': True, 'account': True}}
        values.update(changes)
        return operations.dispatch('bind_draft', values)['binding']

    def receipt(self, draft, **changes):
        values = {'draft_id': draft['id'], 'account_id': self.account['id'],
                  'url': 'https://www.xiaohongshu.com/explore/real-post',
                  'published_at': '2026-10-01T10:00:00Z', 'note': '本人在平台完成发布后填入'}
        values.update(changes)
        return operations.dispatch('save_receipt', values)['receipt']

    def media(self, directory='media-a', name='封面.jpg', content=b'first-image'):
        folder = self.root / directory
        folder.mkdir(exist_ok=True)
        path = folder / name
        path.write_bytes(content)
        return path, media_uploads.register_files([str(path)])['jobs'][0]

    def test_project_defaults_and_local_override_do_not_edit_source_files(self):
        first = operations.snapshot()['projects'][0]
        self.assertTrue(first['root_exists'])
        self.assertTrue(first['entry_exists'])
        self.assertFalse(first['delivery_exists'])
        result = operations.dispatch('save_project', {'project': {'id': 'parenting', 'summary': '新的用途说明'}})['project']
        self.assertEqual(result['name'], '育儿知识卡')
        self.assertEqual(operations.snapshot()['projects'][0]['summary'], '新的用途说明')
        self.assertEqual(json.loads(self.config.read_text())['projects'][0]['summary'], '真实资料')
        self.assertEqual((self.project_root / '开始这里.md').read_text(), '原项目独立保留')
        for changes in ({'root_path': 'relative'}, {'entry_path': '../outside.md'}, {'delivery_path': str(self.root)}):
            with self.subTest(changes=changes), self.assertRaises(core.ValidationError):
                operations.save_project({'id': 'parenting', **changes})
        added = operations.save_project({'name': '新项目', 'kind': '内容创作', 'root_path': str(self.project_root),
                                         'entry_path': '开始这里.md'})['project']
        self.assertTrue(added['id'].startswith('project-'))
        self.assertEqual(added['entry_path'], str((self.project_root / '开始这里.md').resolve()))

    def test_unbound_project_keeps_brief_and_checks_and_changed_draft_requires_fresh_check(self):
        draft = self.create()
        self.check(draft)
        unbound = operations.bind_draft({'draft_id': draft['id'], 'project_id': ''})['binding']
        self.assertEqual(unbound['brief'], '本次发布的目标')
        self.assertTrue(all(unbound['checklist'].values()))
        self.assertEqual(unbound['project_id'], '')
        core.update_draft(draft['id'], {'body': '修改后的主稿'})
        binding = operations.snapshot()['bindings'][0]
        self.assertTrue(binding['needs_recheck'])
        self.assertFalse(any(binding['checklist'].values()))
        core.update_draft(draft['id'], {'status': 'review'})
        core.update_draft(draft['id'], {'status': 'approved'})
        with self.assertRaises(core.ValidationError):
            self.receipt(draft)
        self.check(draft, project_id='')
        self.assertFalse(self.receipt(draft)['stale'])

    def test_only_approved_checked_version_and_real_target_can_get_manual_receipt(self):
        draft = self.create(approved=False)
        self.check(draft)
        with self.assertRaises(core.ValidationError):
            self.receipt(draft)
        core.update_draft(draft['id'], {'status': 'review'})
        core.update_draft(draft['id'], {'status': 'approved'})
        for account_id in ('invented', core.create_account({'platform': 'tiktok', 'handle': 'unselected', 'name': '未选账号'})['account']['id']):
            with self.subTest(account_id=account_id), self.assertRaises(core.ValidationError):
                self.receipt(draft, account_id=account_id)
        for checks in ({'content': True, 'media': False, 'account': True}, {}):
            self.check(draft, checklist=checks)
            with self.assertRaises(core.ValidationError):
                self.receipt(draft)
        with self.assertRaises(core.ValidationError):
            self.check(draft, checklist={'content': 'true', 'media': True, 'account': True})

    def test_receipts_are_idempotent_per_target_and_keep_platform_copy_and_audit(self):
        draft = self.create()
        self.check(draft)
        first = self.receipt(draft)
        self.assertEqual(first['source'], 'manual')
        self.assertIn('未向平台自动核验', first['source_label'])
        self.assertEqual(self.receipt(draft)['id'], first['id'])
        with self.assertRaises(core.ValidationError):
            self.receipt(draft, url='https://www.xiaohongshu.com/explore/different')
        self.assertEqual(operations.snapshot()['drafts'][0]['publication_status'], 'partial')
        other = self.receipt(draft, account_id=self.account_b['id'], url='https://www.instagram.com/p/real-post/')
        self.assertEqual(other['body'], 'The approved English version.')
        self.assertEqual(operations.snapshot()['drafts'][0]['publication_status'], 'complete')
        self.assertEqual(core.state()['drafts'][0]['status'], 'approved')
        core.update_draft(draft['id'], {'platform_variants': {'instagram': 'A later version.'}})
        current = operations.snapshot()
        self.assertTrue(all(r['stale'] for r in current['receipts']))
        self.assertEqual(next(r for r in current['receipts'] if r['id'] == other['id'])['body'], 'The approved English version.')
        self.assertEqual(current['stats']['published_drafts'], 0)

    def test_url_and_nonfuture_time_validation_never_creates_partial_receipt(self):
        draft = self.create()
        self.check(draft)
        for url in ('file:///private/file', 'javascript:alert(1)', 'https://', 'https://user:secret@example.com/p', 'https://example.com/a b', 'https://example.com:bad/p'):
            with self.subTest(url=url), self.assertRaises(core.ValidationError):
                self.receipt(draft, url=url)
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        with self.assertRaises(core.ValidationError):
            self.receipt(draft, published_at=tomorrow)
        self.assertEqual(operations.snapshot()['receipts'], [])

    def test_metrics_keep_unknown_and_known_zero_and_void_excludes_them_from_summary(self):
        draft = self.create()
        self.check(draft)
        receipt = self.receipt(draft)
        first = operations.record_metrics({'receipt_id': receipt['id'], 'observed_at': '2026-10-02T10:00:00Z',
                                          'views': 100, 'saves': 0, 'likes': 0})['observation']
        self.assertEqual(first['saves'], 0)
        self.assertIsNone(first['comments'])
        self.assertEqual(first['post_id'], receipt['url'])
        self.assertEqual(core.state()['summary']['views'], 100)
        self.assertIsNone(core.state()['summary']['engagement_rate'])
        operations.record_metrics({'receipt_id': receipt['id'], 'observed_at': '2026-10-03T10:00:00Z', 'views': 120, 'comments': 2})
        self.assertEqual(core.state()['summary']['views'], 120)
        self.assertEqual(operations.snapshot()['receipts'][0]['metrics']['views'], 120)
        voided = operations.void_receipt({'id': receipt['id'], 'reason': '误选作品链接'})['receipt']
        self.assertTrue(voided['voided'])
        self.assertEqual(core.state()['summary']['post_count'], 0)
        with closing(sqlite3.connect(self.db)) as connection, connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM ops_metrics').fetchone()[0], 2)
        with self.assertRaises(core.ValidationError):
            operations.record_metrics({'receipt_id': receipt['id'], 'observed_at': '2026-10-03T11:00:00Z', 'views': 1})
        replacement = self.receipt(draft, url='https://www.xiaohongshu.com/explore/corrected')
        self.assertNotEqual(replacement['id'], receipt['id'])

    def test_metrics_dates_values_and_empty_measurement_rejected(self):
        draft = self.create()
        self.check(draft)
        receipt = self.receipt(draft)
        for fields in ({}, {'views': -1}, {'views': 1.5}, {'views': float('nan')}, {'views': 1, 'observed_at': '2026-09-01T00:00:00Z'},
                       {'views': 1, 'observed_at': (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()}):
            values = {'receipt_id': receipt['id'], 'observed_at': '2026-10-02T10:00:00Z', **fields}
            with self.subTest(fields=fields), self.assertRaises(core.ValidationError):
                operations.record_metrics(values)
        self.assertEqual(core.state()['posts'], [])

    def test_portable_zip_has_ordered_duplicate_names_all_bytes_and_each_account_copy(self):
        path_a, media_a = self.media(content=b'first-image')
        path_b, media_b = self.media(directory='media-b', content=b'second-image')
        draft = self.create(media_ids=[media_b['id'], media_a['id']])
        self.check(draft)
        archive_path = operations.prepare_package(draft['id'])
        self.addCleanup(archive_path.unlink, missing_ok=True)
        with zipfile.ZipFile(archive_path) as archive:
            manifest = json.loads(archive.read('manifest.json'))
            self.assertTrue(manifest['ready'])
            self.assertFalse(manifest['published'])
            self.assertEqual(manifest['project']['id'], 'parenting')
            self.assertEqual(archive.read('素材/01-封面.jpg'), path_b.read_bytes())
            self.assertEqual(archive.read('素材/02-封面.jpg'), path_a.read_bytes())
            self.assertIn('The approved English version.', archive.read(manifest['accounts'][1]['text_file']).decode())
            self.assertIn('不会自动发布', archive.read('发布说明.md').decode())
            self.assertTrue(all(i.compress_type == zipfile.ZIP_STORED for i in archive.infolist()))
        self.assertEqual(operations.snapshot()['receipts'], [])

    def test_media_changes_missing_and_draft_approval_block_complete_package(self):
        path, media = self.media()
        draft = self.create(media_ids=[media['id']])
        self.check(draft)
        path.write_bytes(b'a changed file at same source location')
        manifest = operations.package_manifest(draft['id'])
        self.assertFalse(manifest['ready'])
        self.assertIn('已变更', manifest['media'][0]['issue'])
        self.assertTrue(operations.snapshot()['media'][0]['changed'])
        self.assertTrue(operations.snapshot()['bindings'][0]['needs_recheck'])
        with self.assertRaises(core.ValidationError):
            self.receipt(draft)
        with self.assertRaises(core.ValidationError):
            operations.prepare_package(draft['id'])
        path.unlink()
        self.assertFalse(operations.snapshot()['media'][0]['available'])
        with self.assertRaises(core.ValidationError):
            operations.prepare_package(draft['id'])
        unapproved = self.create(approved=False)
        with self.assertRaises(core.ValidationError):
            operations.prepare_package(unapproved['id'])

    def test_total_size_limit_checked_before_writing_zip(self):
        _, media = self.media(content=b'1234567890')
        draft = self.create(media_ids=[media['id']])
        with patch.object(operations, 'MAX_PACKAGE_BYTES', 5), self.assertRaises(core.ValidationError):
            operations.prepare_package(draft['id'])

    def test_work_data_backup_is_recoverable_without_keys_media_or_source_project(self):
        source, media = self.media(content=b'original-large-file-should-stay-out')
        draft = self.create(media_ids=[media['id']])
        self.check(draft)
        receipt = self.receipt(draft)
        (self.db.parent / 'provider.json').write_text('{"api_key":"never-in-backup"}')
        imports = self.db.parent / 'imports'
        imports.mkdir()
        (imports / 'original.csv').write_text('原始导入表')
        (imports / 'receipt.json').write_text('{"source":"manual"}')
        (imports / 'ignore.mp4').write_bytes(b'do-not-backup')
        archive_path = operations.backup()
        self.addCleanup(archive_path.unlink, missing_ok=True)
        with zipfile.ZipFile(archive_path) as archive:
            self.assertEqual(set(archive.namelist()), {'data/media.sqlite3', 'app/projects.json',
                'data/imports/original.csv', 'data/imports/receipt.json', '备份说明.md'})
            target = self.root / 'restored.sqlite3'
            target.write_bytes(archive.read('data/media.sqlite3'))
            with closing(sqlite3.connect(target)) as connection, connection:
                self.assertEqual(connection.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                self.assertEqual(connection.execute('SELECT id FROM ops_receipts').fetchone()[0], receipt['id'])
                self.assertEqual(connection.execute('SELECT COUNT(*) FROM drafts').fetchone()[0], 1)
            self.assertEqual(json.loads(archive.read('app/projects.json'))['projects'][0]['id'], 'parenting')
            self.assertIn('不包含原始图片视频', archive.read('备份说明.md').decode())
        self.assertTrue(source.exists())


if __name__ == '__main__':
    unittest.main()
