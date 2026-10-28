"""Platform-specific draft copy and its review boundary, on temporary databases."""
from __future__ import annotations
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import core, planning


class DraftVariantTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='media-draft-variants-test-')
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'media.sqlite3'
        replacement = patch.object(core, 'DB', self.path)
        replacement.start()
        self.addCleanup(replacement.stop)

    def create(self, **changes):
        values = {'title': '一个真实主题', 'body': '所有平台共用的主稿。', 'platforms': ['instagram']}
        values.update(changes)
        return core.create_draft(values)['draft']

    def saved(self, identifier):
        return next(draft for draft in core.state()['drafts'] if draft['id'] == identifier)

    def approve(self, draft):
        core.update_draft(draft['id'], {'status': 'review'})
        return core.update_draft(draft['id'], {'status': 'approved'})['draft']

    def test_legacy_sqlite_migrates_payload_once_without_changing_content_or_approval(self):
        original = {'id': 'legacy', 'title': '旧标题', 'body': '已认可的原正文', 'platforms': ['instagram'],
                    'account_ids': [], 'media_ids': [], 'scheduled_at': '', 'status': 'approved',
                    'created_at': '2026-10-01T00:00:00+00:00', 'updated_at': '2026-10-02T00:00:00+00:00',
                    'delivery': 'local_only'}
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute('CREATE TABLE drafts(id TEXT PRIMARY KEY,payload TEXT NOT NULL)')
            connection.execute('INSERT INTO drafts VALUES(?,?)', ('legacy', json.dumps(original)))
        expected = {**original, 'platform_variants': {}}
        self.assertEqual(self.saved('legacy'), expected)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            self.assertEqual(json.loads(connection.execute('SELECT payload FROM drafts').fetchone()[0]), expected)
            first = connection.execute('SELECT * FROM core_schema_migrations').fetchall()
        self.assertEqual(self.saved('legacy'), expected)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            self.assertEqual(connection.execute('SELECT * FROM core_schema_migrations').fetchall(), first)
        self.assertEqual(len(first), 1)
        self.assertEqual(core.export_drafts()['drafts'][0]['platform_variants'], {})

    def test_new_draft_defaults_to_independent_empty_mapping(self):
        first, second = self.create(), self.create()
        self.assertEqual(first['platform_variants'], {})
        first['platform_variants']['instagram'] = '只修改返回值'
        self.assertEqual(self.saved(first['id'])['platform_variants'], {})
        self.assertEqual(second['platform_variants'], {})

    def test_create_update_read_and_export_keep_shared_body_and_unselected_platform(self):
        draft = self.create(platform_variants={'instagram': '图片平台正文', 'tiktok': '短视频平台正文'})
        self.assertEqual(draft['platforms'], ['instagram'])
        updated = core.update_draft(draft['id'], {'platform_variants': {'instagram': '更新后正文', 'youtube': '视频说明'}})['draft']
        self.assertEqual(updated['body'], '所有平台共用的主稿。')
        self.assertEqual(updated['platform_variants'], {'instagram': '更新后正文', 'youtube': '视频说明'})
        self.assertEqual(self.saved(draft['id'])['platform_variants'], updated['platform_variants'])
        exported = core.export_drafts()
        self.assertEqual(exported['drafts'][0]['platform_variants'], updated['platform_variants'])
        self.assertFalse(exported['published'])

    def test_omitted_mapping_is_preserved_and_empty_mapping_explicitly_removes_variants(self):
        draft = self.create(platform_variants={'instagram': '已保存改写'})
        updated = core.update_draft(draft['id'], {'body': '新的主稿'})['draft']
        self.assertEqual(updated['platform_variants'], {'instagram': '已保存改写'})
        cleared = core.update_draft(draft['id'], {'platform_variants': {}})['draft']
        self.assertEqual(cleared['platform_variants'], {})

    def test_empty_variant_is_preserved_as_shared_body_fallback(self):
        draft = self.create(platform_variants={'instagram': '   ', 'tiktok': ''})
        self.assertEqual(draft['platform_variants'], {'instagram': '', 'tiktok': ''})
        self.assertEqual(draft['body'], '所有平台共用的主稿。')

    def test_editing_variant_revokes_approved_to_review(self):
        for explicit_status in (None, 'draft', 'review'):
            with self.subTest(explicit_status=explicit_status):
                draft = self.approve(self.create(platform_variants={'instagram': '已审改写'}))
                change = {'platform_variants': {'instagram': '待审改写'}}
                if explicit_status is not None:
                    change['status'] = explicit_status
                updated = core.update_draft(draft['id'], change)['draft']
                self.assertEqual(updated['status'], 'review')
                self.assertEqual(self.saved(draft['id'])['status'], 'review')
                self.assertEqual(core.update_draft(draft['id'], {'status': 'approved'})['draft']['status'], 'approved')

    def test_removing_variant_also_requires_fresh_review(self):
        draft = self.approve(self.create(platform_variants={'instagram': '已审改写'}))
        self.assertEqual(core.update_draft(draft['id'], {'platform_variants': {}})['draft']['status'], 'review')

    def test_unchanged_variants_do_not_revoke_approval(self):
        draft = self.approve(self.create(platform_variants={'instagram': '已审改写'}))
        updated = core.update_draft(draft['id'], {'platform_variants': {'instagram': '  已审改写  '}})['draft']
        self.assertEqual(updated['status'], 'approved')
        self.assertEqual(updated['platform_variants'], draft['platform_variants'])

    def test_changed_variant_cannot_be_approved_in_same_request(self):
        for status in ('draft', 'review', 'approved'):
            with self.subTest(status=status):
                draft = self.create(platform_variants={'instagram': '原文'})
                if status in ('review', 'approved'):
                    core.update_draft(draft['id'], {'status': 'review'})
                if status == 'approved':
                    core.update_draft(draft['id'], {'status': 'approved'})
                with self.assertRaises(core.ValidationError):
                    core.update_draft(draft['id'], {'platform_variants': {'instagram': '新文'}, 'status': 'approved'})
                saved = self.saved(draft['id'])
                self.assertEqual(saved['platform_variants'], {'instagram': '原文'})
                self.assertEqual(saved['status'], status)

    def test_invalid_mapping_keys_values_rejected_without_mutating_approved_draft(self):
        draft = self.approve(self.create(platform_variants={'instagram': '已审改写'}))
        cases = [None, [], '', 1, {'google_ads': '广告文案'}, {'unknown': '正文'}, {'ig': '别名不是ID'},
                 {'Instagram': '大小写不是ID'}, {42: '错误键'}, {'instagram': None},
                 {'instagram': ['正文']}, {'instagram': {'body': '正文'}}, {'instagram': False},
                 {'instagram': 3.14}, {'instagram': '文' * 30001}]
        for value in cases:
            with self.subTest(value_type=type(value).__name__), self.assertRaises(core.ValidationError):
                core.update_draft(draft['id'], {'platform_variants': value})
            saved = self.saved(draft['id'])
            self.assertEqual(saved['status'], 'approved')
            self.assertEqual(saved['platform_variants'], {'instagram': '已审改写'})

    def test_maximum_variant_length_and_all_social_platforms_supported(self):
        variants = {platform['id']: '文' * 30000 for platform in core.PLATFORMS if platform['kind'] == 'social'}
        draft = self.create(platform_variants=variants)
        self.assertEqual(draft['platform_variants'], variants)
        self.assertNotIn('google_ads', draft['platform_variants'])

    def test_planning_transfer_still_creates_default_empty_variants(self):
        account = core.create_account({'platform': 'instagram', 'handle': 'isolated', 'name': '隔离账号'})['account']
        common = {'account_id': account['id']}
        planning.save_strategy({**common, 'audience': '创作者', 'scenario': '记录过程', 'problem': '难以说明步骤',
                                'materials': '真实记录', 'pillars': ['方法', '案例', '过程']})
        planning.add_question({**common, 'question': '怎样说明一个步骤？', 'context': '制作记录',
                               'materials': '本人笔记', 'material_ready': True})
        card = planning.create_batch(common)['batch']['cards'][0]
        planning.update_plan_item({**common, 'id': card['id'], 'body': '本人确认的正文'})
        draft = planning.create_plan_draft({**common, 'id': card['id']})['draft']
        self.assertEqual(draft['platform_variants'], {})
        self.assertEqual(draft['status'], 'draft')


if __name__ == '__main__':
    unittest.main()
