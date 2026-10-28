"""Editorial planning invariants; every test uses an isolated temporary database."""
from __future__ import annotations
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import importlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import core, media_uploads, planning


class PlanningTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='media-planning-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        replacement = patch.object(core, 'DB', self.root / 'media.sqlite3')
        replacement.start()
        self.addCleanup(replacement.stop)
        self.a = core.create_account({'platform': 'instagram', 'handle': 'test_a', 'name': '测试 A'})['account']['id']
        self.b = core.create_account({'platform': 'instagram', 'handle': 'test_b', 'name': '测试 B'})['account']['id']

    def call(self, action, account=None, **values):
        return planning.dispatch(action, {'account_id': account or self.a, **values})

    def strategy(self, account=None, **changes):
        return self.call('save_strategy', account, audience='独立内容创作者', scenario='第一次准备发布作品',
                         problem='不知道怎么展示过程', materials='本人制作记录和原始工程',
                         pillars=['实操方法', '真实案例', '制作日记'], **changes)['strategy']

    def question(self, text='怎样展示一次真实制作过程？', account=None, **changes):
        values = {'question': text, 'context': '创作时真实遇到的问题', 'source_type': 'work_record',
                  'materials': '本人的制作笔记', 'material_ready': True}
        values.update(changes)
        return self.call('add_question', account, **values)['question']

    def batch(self, count=1, account=None):
        self.strategy(account)
        for index in range(count):
            self.question(f'真实问题 {index + 1} 怎么处理？', account)
        return self.call('create_batch', account)['batch']

    def observe(self, card, hours=24, account=None, **changes):
        published = datetime(2026, 10, 10, 0, 0, tzinfo=timezone.utc)
        values = {'id': card['id'], 'post_url': 'https://example.com/my-post',
                  'published_at': published.isoformat(), 'observed_at': (published + timedelta(hours=hours)).isoformat()}
        values.update(changes)
        return self.call('observe_plan_item', account, **values)['observation']

    def test_accounts_isolated_in_all_workspace_collections(self):
        batch = self.batch(2)
        self.observe(batch['cards'][0], views=12)
        other = planning.get_workspace(self.b)
        self.assertIsNone(other['strategy'])
        for field in ('questions', 'batches', 'observations'):
            self.assertEqual(other[field], [])
        self.assertEqual(other['ai_mode'], 'structured_local')
        self.assertFalse(other['remote_publishing_enabled'])

    def test_unknown_and_demo_account_rejected(self):
        with self.assertRaises(core.ValidationError):
            planning.get_workspace('demo-account')
        with self.assertRaises(core.ValidationError):
            self.call('save_strategy', 'unknown')

    def test_strategy_requires_three_distinct_pillars_and_persists(self):
        values = {'account_id': self.a, 'audience': '读者', 'scenario': '场景', 'problem': '问题', 'materials': '本人记录'}
        for pillars in (['一', '二'], ['一', '一', '三'], ['一', '', '三'], ['A', 'a', 'B']):
            with self.subTest(pillars=pillars), self.assertRaises(core.ValidationError):
                planning.save_strategy({**values, 'pillars': pillars})
        saved = self.strategy()
        importlib.reload(planning)
        self.assertEqual(planning.get_workspace(self.a)['strategy'], saved)

    def test_batch_requires_strategy(self):
        with self.assertRaises(core.ValidationError):
            self.call('create_batch')

    def test_empty_batch_has_twelve_empty_cards_and_prescribed_mix(self):
        batch = self.batch(0)
        self.assertEqual(len(batch['cards']), 12)
        self.assertEqual(Counter(c['content_type'] for c in batch['cards']), {'method': 3, 'case': 4, 'process': 3, 'template': 2})
        self.assertEqual(Counter(c['group'] for c in batch['cards']), {1: 4, 2: 4, 3: 4})
        self.assertEqual([c['position'] for c in batch['cards']], list(range(1, 13)))
        for card in batch['cards']:
            self.assertEqual((card['question'], card['title'], card['body'], card['material_plan']), ('', '', '', ''))
            self.assertIsNone(card['question_id'])
            self.assertEqual(card['status'], 'needs_question')

    def test_questions_ready_first_priority_next_no_duplicates_or_fabrication(self):
        self.strategy()
        slow = self.question('没有材料的问题', material_ready=False, priority=1)
        second = self.question('材料齐全但普通问题', priority=3)
        first = self.question('材料齐全且优先问题', priority=1)
        self.question('材料齐全且优先问题', priority=2)
        self.question('搁置的问题', status='parked')
        cards = self.call('create_batch')['batch']['cards']
        self.assertEqual([c['question_id'] for c in cards[:3]], [first['id'], second['id'], slow['id']])
        self.assertTrue(all(c['question_id'] is None and c['title'] == '' for c in cards[3:]))

    def test_next_batch_excludes_selected_but_explicit_reuse_allowed(self):
        batch = self.batch(1)
        identifier = batch['cards'][0]['question_id']
        self.assertEqual(planning.get_workspace(self.a)['questions'][0]['status'], 'selected')
        next_batch = self.call('create_batch')['batch']
        self.assertTrue(all(c['question_id'] is None for c in next_batch['cards']))
        explicit = self.call('create_batch', question_ids=[identifier])['batch']
        self.assertEqual(explicit['cards'][0]['question_id'], identifier)

    def test_question_edits_preserve_existing_card_snapshot(self):
        batch = self.batch(1)
        card = batch['cards'][0]
        self.call('update_question', id=card['question_id'], question='后来重新描述的问题')
        preserved = planning.get_workspace(self.a)['batches'][0]['cards'][0]
        self.assertEqual(preserved['question'], card['question'])
        self.assertEqual(preserved['title'], card['title'])

    def test_cross_account_actions_and_export_rejected(self):
        batch = self.batch(1)
        card = batch['cards'][0]
        observation = self.observe(card, reader_question='真实追问', next_answer='后续回答', next_materials='待补材料')
        attempts = [('update_question', {'id': card['question_id'], 'question': '改动'}),
                    ('create_batch', {'question_ids': [card['question_id']]}),
                    ('update_plan_item', {'id': card['id'], 'title': '改动'}),
                    ('create_plan_draft', {'id': card['id']}),
                    ('observe_plan_item', {'id': card['id'], 'published_at': '2026-10-10T00:00:00Z', 'observed_at': '2026-10-11T00:00:00Z'}),
                    ('review_batch', {'batch_id': batch['id'], 'group': 1}),
                    ('promote_feedback', {'observation_id': observation['id']}),
                    ('export_plan', {'batch_id': batch['id']})]
        self.strategy(self.b)
        for action, values in attempts:
            with self.subTest(action=action), self.assertRaises(core.ValidationError):
                self.call(action, self.b, **values)
        with self.assertRaises(core.ValidationError):
            planning.export_plan(batch['id'], self.b)

    def test_card_rejects_cross_account_question_duplicate_and_unknown_media(self):
        batch = self.batch(1)
        other = self.question('另一个账号的问题', self.b)
        empty = batch['cards'][1]
        for changes in ({'question_id': other['id']}, {'question_id': batch['cards'][0]['question_id']}, {'media_ids': ['missing']}):
            with self.subTest(changes=changes), self.assertRaises(core.ValidationError):
                self.call('update_plan_item', id=empty['id'], **changes)

    def test_required_material_text_does_not_claim_material_is_ready(self):
        self.strategy()
        self.question('有问题但需要补拍', materials='需要补拍过程', material_ready=False)
        card = self.call('create_batch')['batch']['cards'][0]
        self.assertEqual(card['status'], 'needs_material')
        self.assertTrue(card['material_gap'])
        saved = self.call('update_plan_item', id=card['id'], material_ready=True)['card']
        self.assertEqual(saved['status'], 'ready_to_write')
        self.assertFalse(saved['material_gap'])
        with self.assertRaises(core.ValidationError):
            self.call('update_plan_item', id=card['id'], material_ready='yes')

    def test_valid_media_and_draft_idempotence_edit_does_not_override(self):
        batch = self.batch(1)
        card = batch['cards'][0]
        file = self.root / 'my-record.mp4'
        file.write_bytes(b'local media fixture')
        media_id = media_uploads.register_files([str(file)])['jobs'][0]['id']
        self.call('update_plan_item', id=card['id'], body='本人提供并确认的正文。', media_ids=[media_id])
        first = self.call('create_plan_draft', id=card['id'])
        self.assertEqual(first['draft']['media_ids'], [media_id])
        self.assertEqual(first['draft']['account_ids'], [self.a])
        self.assertEqual(first['draft_sync_status'], 'synced')
        second = self.call('create_plan_draft', id=card['id'])
        self.assertTrue(second['reused'])
        self.assertEqual(first['draft']['id'], second['draft']['id'])
        changed = self.call('update_plan_item', id=card['id'], body='新的正文尚未进入草稿。')['card']
        self.assertEqual(changed['draft_sync_status'], 'changed')
        third = self.call('create_plan_draft', id=card['id'])
        self.assertEqual(third['draft']['body'], '本人提供并确认的正文。')
        self.assertEqual(len(core.state()['drafts']), 1)

    def test_concurrent_draft_transfer_creates_one_draft(self):
        card = self.batch(1)['cards'][0]
        self.call('update_plan_item', id=card['id'], body='真实正文')
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: self.call('create_plan_draft', id=card['id']), range(2)))
        self.assertEqual(len({r['draft']['id'] for r in results}), 1)
        self.assertEqual(len(core.state()['drafts']), 1)

    def test_draft_requires_question_material_and_body(self):
        batch = self.batch(0)
        card = batch['cards'][0]
        for changes in ({}, {'title': '手填题', 'body': '手填正文', 'material_plan': '手填材料'}):
            self.call('update_plan_item', id=card['id'], **changes)
            with self.assertRaises(core.ValidationError):
                self.call('create_plan_draft', id=card['id'])
        question = self.question('真实问题', materials='')
        self.call('update_plan_item', id=card['id'], question_id=question['id'], material_plan='')
        with self.assertRaises(core.ValidationError):
            self.call('create_plan_draft', id=card['id'])

    def test_observation_null_zero_and_views_impressions_kept_separate(self):
        card = self.batch(1)['cards'][0]
        observation = self.observe(card, views=0, impressions=1000, saves=0, comments='', follows=None, production_minutes=12.5)
        self.assertEqual((observation['views'], observation['impressions'], observation['saves']), (0, 1000, 0))
        self.assertIsNone(observation['comments'])
        self.assertIsNone(observation['follows'])
        self.assertEqual(observation['production_minutes'], 12.5)
        review = self.call('review_batch', batch_id=card['batch_id'], group=1)
        self.assertIsNone(review['items'][0]['save_rate_percent'])
        self.assertEqual(review['missing_positions'], [2, 3, 4])

    def test_observation_invalid_values_dates_and_link_rejected(self):
        card = self.batch(1)['cards'][0]
        for changes in ({'views': -1}, {'views': 1.5}, {'views': True}, {'views': float('nan')},
                        {'production_minutes': float('inf')}, {'observed_at': 'bad'},
                        {'observed_at': '2026-10-09T00:00:00Z'}, {'post_url': 'javascript:alert(1)'}):
            with self.subTest(changes=changes), self.assertRaises(core.ValidationError):
                self.observe(card, **changes)

    def test_review_uses_latest_timestamp_keeps_history_no_ranking_for_mixed_windows(self):
        batch = self.batch(4)
        first, second, third, fourth = batch['cards'][:4]
        self.observe(first, 48, views=200, saves=10)
        self.observe(first, 12, views=20, saves=1)  # Late entry of an older observation.
        self.observe(second, 24, views=100, saves=2)
        self.observe(third, 24, impressions=300, saves=9)
        self.observe(fourth, 24, views=100, saves=0)
        review = self.call('review_batch', batch_id=batch['id'], group=1)
        self.assertEqual(review['observed_count'], 4)
        self.assertFalse(review['windows_comparable'])
        self.assertEqual(review['ranking'], [])
        self.assertEqual(review['items'][0]['window_hours'], 48)
        self.assertEqual(review['items'][0]['save_rate_percent'], 5)
        self.assertIsNone(review['items'][2]['save_rate_percent'])
        self.assertEqual(review['items'][3]['save_rate_percent'], 0)
        self.assertEqual(len(planning.get_workspace(self.a)['observations']), 5)

    def test_same_observed_timestamp_latest_record_wins_and_tolerance_inclusive(self):
        batch = self.batch(2)
        self.observe(batch['cards'][0], 24, views=10)
        self.observe(batch['cards'][0], 24, views=11)
        self.observe(batch['cards'][1], 25, views=20)
        review = self.call('review_batch', batch_id=batch['id'], group=1)
        self.assertTrue(review['windows_comparable'])
        self.assertEqual(review['items'][0]['observation']['views'], 11)
        self.assertEqual(review['observed_count'], 2)

    def test_feedback_requires_three_fields_and_promotion_is_idempotent(self):
        card = self.batch(1)['cards'][0]
        incomplete = self.observe(card, reader_question='追问')
        with self.assertRaises(core.ValidationError):
            self.call('promote_feedback', observation_id=incomplete['id'])
        observation = self.observe(card, reader_question='实际读者追问？', next_answer='下一篇要回答的具体内容', next_materials='另一次真实记录')
        result = self.call('promote_feedback', observation_id=observation['id'])
        repeated = self.call('promote_feedback', observation_id=observation['id'])
        question = result['question']
        self.assertEqual(question['question'], observation['reader_question'])
        self.assertEqual(question['original_question'], card['question'])
        self.assertEqual(question['provenance']['observation_id'], observation['id'])
        self.assertEqual(question['next_answer'], observation['next_answer'])
        self.assertEqual(question['required_materials'], observation['next_materials'])
        self.assertFalse(question['material_ready'])
        self.assertEqual(question['status'], 'inbox')
        self.assertTrue(repeated['reused'])
        self.assertEqual(question['id'], repeated['question']['id'])
        self.assertEqual(len(planning.get_workspace(self.a)['questions']), 2)
        next_cards = self.call('create_batch')['batch']['cards']
        self.assertEqual(next_cards[0]['question_id'], question['id'])

    def test_export_keeps_sources_current_strategy_and_batch_snapshot(self):
        batch = self.batch(1)
        self.observe(batch['cards'][0], views=9)
        exported = planning.export_plan(batch['id'], self.a)
        self.assertEqual(exported['delivery'], 'local_only')
        self.assertFalse(exported['published'])
        self.assertEqual(len(exported['cards']), 12)
        self.assertEqual(len(exported['observations']), 1)
        self.assertEqual(exported['batch']['strategy_snapshot'], exported['strategy'])
        self.assertTrue(exported['source_reference']['url'].startswith('https://x.com/'))

    def test_payload_shape_validation(self):
        for args in ([], 'text', 12):
            with self.assertRaises(core.ValidationError):
                planning.dispatch('create_batch', args)
        for changes in ({'priority': True}, {'material_ready': 'yes'}, {'status': 'fake'}, {'source_type': 'platform_api'}):
            with self.subTest(changes=changes), self.assertRaises(core.ValidationError):
                self.question(**changes)


if __name__ == '__main__':
    unittest.main()
