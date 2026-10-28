"""Account-scoped editorial planning from user-supplied evidence.

This module fills editable structures, not AI-written content or platform data.
All publication observations are manually entered and keep their history.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sqlite3
import threading
import uuid
from urllib.parse import urlsplit

try:
    import fcntl
    msvcrt = None
except ImportError:   # Windows: lock one byte with msvcrt instead of flock
    fcntl = None
    import msvcrt

if __package__:
    from . import core, media_uploads
else:
    import core
    import media_uploads

SOURCE_REFERENCE = {
    'url': 'https://x.com/JessiCao_JC/status/2110614414890283326',
    'title': '账号定位 → 真实问题 → 12 篇内容 → 每 4 篇复盘 → 追问变选题',
    'note': '参考公开帖的方法结构，标题和正文由本账号的真实问题与用户输入形成。',
}
CONTENT_SEQUENCE = ('method', 'case', 'process', 'template', 'method', 'case',
                    'process', 'case', 'method', 'case', 'process', 'template')
QUESTION_TYPES = ('search', 'comment', 'work_record', 'other')
CARD_TEXT_FIELDS = ('title', 'material_plan', 'reader_action', 'expected_feedback', 'variable', 'body')
OBSERVATION_METRICS = ('views', 'impressions', 'saves', 'comments', 'follows', 'production_minutes')
WINDOW_RULE = '各篇观察时长 = 采集时间 − 发布时间；至少 2 篇有记录且最大时长差 ≤ 1 小时，才视为窗口接近。始终按计划顺序展示，不据此推断因果。'
_draft_lock = threading.RLock()


def _dump(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


@contextmanager
def _connect():
    path = Path(core.DB)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA journal_mode=WAL')
    connection.executescript('''
      CREATE TABLE IF NOT EXISTS planning_strategies (
        account_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS planning_questions (
        id TEXT PRIMARY KEY, account_id TEXT NOT NULL, payload TEXT NOT NULL);
      CREATE INDEX IF NOT EXISTS planning_question_account ON planning_questions(account_id);
      CREATE TABLE IF NOT EXISTS planning_batches (
        id TEXT PRIMARY KEY, account_id TEXT NOT NULL, payload TEXT NOT NULL);
      CREATE INDEX IF NOT EXISTS planning_batch_account ON planning_batches(account_id);
      CREATE TABLE IF NOT EXISTS planning_items (
        id TEXT PRIMARY KEY, account_id TEXT NOT NULL, batch_id TEXT NOT NULL, payload TEXT NOT NULL);
      CREATE INDEX IF NOT EXISTS planning_item_batch ON planning_items(account_id, batch_id);
      CREATE TABLE IF NOT EXISTS planning_observations (
        id TEXT PRIMARY KEY, account_id TEXT NOT NULL, item_id TEXT NOT NULL,
        batch_id TEXT NOT NULL, payload TEXT NOT NULL);
      CREATE INDEX IF NOT EXISTS planning_observation_item ON planning_observations(account_id, item_id);
    ''')
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _text(value, field, *, required=False, limit=4000):
    if value is None and not required:
        return ''
    if not isinstance(value, str):
        raise core.ValidationError(f'{field} 必须是文本')
    value = value.strip()
    if required and not value:
        raise core.ValidationError(f'{field} 不能为空')
    if len(value) > limit:
        raise core.ValidationError(f'{field} 最多 {limit} 字')
    return value


def _account(account_id):
    account_id = _text(account_id, 'account_id', required=True, limit=100)
    account = next((a for a in core.state('real')['accounts'] if a['id'] == account_id), None)
    if not account:
        raise core.ValidationError('请先选择一个真实的本地账号档案')
    return account


def _url(value, field):
    value = _text(value, field, limit=4000)
    if value:
        try:
            parts = urlsplit(value)
            if parts.scheme not in ('https', 'http') or not parts.netloc or parts.username or parts.password:
                raise ValueError()
        except ValueError:
            raise core.ValidationError(f'{field} 必须是有效的 http/https 链接') from None
    return value


def _owned(connection, table, identifier, account_id, label):
    # table is selected only by module code, never from external input.
    identifier = _text(identifier, 'id', required=True, limit=100)
    row = connection.execute(f'SELECT payload FROM {table} WHERE id=? AND account_id=?',
                             (identifier, account_id)).fetchone()
    if not row:
        raise core.ValidationError(f'{label}不存在或不属于当前账号')
    return json.loads(row['payload'])


def _strategy(connection, account_id):
    row = connection.execute('SELECT payload FROM planning_strategies WHERE account_id=?',
                             (account_id,)).fetchone()
    return json.loads(row['payload']) if row else None


def _list(connection, table, account_id):
    return [json.loads(row['payload']) for row in connection.execute(
        f'SELECT payload FROM {table} WHERE account_id=? ORDER BY rowid', (account_id,))]


def _save(connection, table, item):
    connection.execute(f'UPDATE {table} SET payload=? WHERE id=? AND account_id=?',
                       (_dump(item), item['id'], item['account_id']))


def _touch_batch(connection, batch_id, account_id):
    batch = _owned(connection, 'planning_batches', batch_id, account_id, '批次')
    batch['updated_at'] = core.now()
    _save(connection, 'planning_batches', batch)


def _card_public(card, drafts):
    result = dict(card)
    result['material_gap'] = not card.get('material_ready', False) or not card.get('material_plan')
    draft = drafts.get(card.get('draft_id'))
    if not card.get('question_id'):
        result['status'] = 'needs_question'
    elif result['material_gap']:
        result['status'] = 'needs_material'
    else:
        result['status'] = 'ready_to_write'
    if card.get('draft_id'):
        result['status'] = 'draft_created'
        equal = bool(draft) and all(draft.get(field) == card.get(field) for field in ('title', 'body', 'media_ids'))
        equal = equal and draft.get('account_ids') == [card['account_id']]
        equal = equal and card.get('draft_revision') == card.get('revision', 0)
        result['draft_sync_status'] = 'missing' if not draft else ('synced' if equal else 'changed')
    else:
        result['draft_sync_status'] = 'none'
    return result


def _drafts(account_id):
    return {draft['id']: draft for draft in core.state('real', account_id)['drafts']}


def get_workspace(account_id):
    _account(account_id)
    drafts = _drafts(account_id)
    with _connect() as connection:
        strategy = _strategy(connection, account_id)
        questions = _list(connection, 'planning_questions', account_id)
        batches = _list(connection, 'planning_batches', account_id)
        cards = _list(connection, 'planning_items', account_id)
        observations = _list(connection, 'planning_observations', account_id)
    for batch in batches:
        batch['cards'] = [_card_public(card, drafts) for card in sorted(cards, key=lambda c: c['position'])
                          if card['batch_id'] == batch['id']]
    return {'account_id': account_id, 'strategy': strategy, 'questions': questions,
            'batches': list(reversed(batches)), 'observations': observations,
            'source_reference': dict(SOURCE_REFERENCE), 'ai_mode': 'structured_local',
            'remote_publishing_enabled': False}


def save_strategy(data):
    account_id = _account(data.get('account_id'))['id']
    pillars = data.get('pillars')
    if not isinstance(pillars, list) or len(pillars) != 3:
        raise core.ValidationError('请填写 3 个不同的固定栏目')
    pillars = [_text(p, '栏目', required=True, limit=100) for p in pillars]
    if len({p.casefold() for p in pillars}) != 3:
        raise core.ValidationError('3 个栏目不能重复')
    strategy = {'account_id': account_id, 'pillars': pillars, 'updated_at': core.now()}
    for field in ('audience', 'scenario', 'problem', 'materials'):
        strategy[field] = _text(data.get(field), field, required=True)
    with _connect() as connection:
        connection.execute('INSERT INTO planning_strategies VALUES(?,?) ON CONFLICT(account_id) DO UPDATE SET payload=excluded.payload',
                           (account_id, _dump(strategy)))
    return {'strategy': strategy}


def _question_values(data, previous=None):
    question = dict(previous or {})
    for field in ('question', 'context', 'source_note', 'pillar', 'materials'):
        if field in data or previous is None:
            question[field] = _text(data.get(field), field, required=(field == 'question'))
    if 'source_url' in data or previous is None:
        question['source_url'] = _url(data.get('source_url'), 'source_url')
    if 'source_type' in data or previous is None:
        kind = data.get('source_type', 'other')
        if kind not in QUESTION_TYPES:
            raise core.ValidationError('问题来源需为 search、comment、work_record 或 other')
        question['source_type'] = kind
    if 'material_ready' in data or previous is None:
        value = data.get('material_ready', False)
        if not isinstance(value, bool):
            raise core.ValidationError('material_ready 必须是 true 或 false')
        question['material_ready'] = value
    if 'priority' in data or previous is None:
        priority = data.get('priority', 2)
        if isinstance(priority, bool) or not isinstance(priority, int) or priority not in (1, 2, 3):
            raise core.ValidationError('优先级为 1（高）、2（中）或 3（低）')
        question['priority'] = priority
    if 'status' in data or previous is None:
        status = data.get('status', 'inbox')
        if status not in ('inbox', 'selected', 'parked'):
            raise core.ValidationError('问题状态为 inbox、selected 或 parked')
        question['status'] = status
    question['updated_at'] = core.now()
    return question


def _check_pillar(connection, account_id, pillar):
    strategy = _strategy(connection, account_id)
    if pillar and strategy and pillar not in strategy['pillars']:
        raise core.ValidationError('请选择当前账号定位中的栏目')


def add_question(data):
    account_id = _account(data.get('account_id'))['id']
    question = _question_values(data)
    question.update(id=uuid.uuid4().hex, account_id=account_id, created_at=core.now(), provenance=None)
    with _connect() as connection:
        _check_pillar(connection, account_id, question['pillar'])
        connection.execute('INSERT INTO planning_questions VALUES(?,?,?)',
                           (question['id'], account_id, _dump(question)))
    return {'question': question}


def update_question(data):
    account_id = _account(data.get('account_id'))['id']
    with _connect() as connection:
        previous = _owned(connection, 'planning_questions', data.get('id'), account_id, '问题')
        question = _question_values(data, previous)
        _check_pillar(connection, account_id, question['pillar'])
        _save(connection, 'planning_questions', question)
    return {'question': question}


def create_batch(data):
    account_id = _account(data.get('account_id'))['id']
    name = _text(data.get('name'), 'name', limit=200) or '12 篇内容计划'
    question_ids = data.get('question_ids', [])
    if not isinstance(question_ids, list) or any(not isinstance(q, str) or not q for q in question_ids):
        raise core.ValidationError('question_ids 必须是问题 ID 列表')
    with _connect() as connection:
        strategy = _strategy(connection, account_id)
        if not strategy:
            raise core.ValidationError('先保存账号定位，再生成 12 篇框架')
        if question_ids:
            candidates = [_owned(connection, 'planning_questions', identifier, account_id, '问题')
                          for identifier in dict.fromkeys(question_ids)]
            if any(q['status'] == 'parked' for q in candidates):
                raise core.ValidationError('请先恢复已搁置问题，再用于内容计划')
        else:
            candidates = [q for q in _list(connection, 'planning_questions', account_id) if q['status'] == 'inbox']
            used_questions = {' '.join(card.get('question', '').split()).casefold()
                              for card in _list(connection, 'planning_items', account_id) if card.get('question_id')}
            candidates = [q for q in candidates if ' '.join(q['question'].split()).casefold() not in used_questions]
        candidates.sort(key=lambda q: (not q['material_ready'], q['priority'], q['created_at'], q['id']))
        questions, seen = [], set()
        for question in candidates:
            signature = ' '.join(question['question'].split()).casefold()
            if signature not in seen:
                questions.append(question)
                seen.add(signature)
        batch = {'id': uuid.uuid4().hex, 'account_id': account_id, 'name': name,
                 'created_at': core.now(), 'updated_at': core.now(), 'strategy_snapshot': strategy,
                 'generation_mode': 'structured_local', 'source_reference': dict(SOURCE_REFERENCE)}
        connection.execute('INSERT INTO planning_batches VALUES(?,?,?)', (batch['id'], account_id, _dump(batch)))
        cards = []
        for index, content_type in enumerate(CONTENT_SEQUENCE):
            question = questions[index] if index < len(questions) else None
            if question:
                question['status'] = 'selected'
                question['updated_at'] = core.now()
                _save(connection, 'planning_questions', question)
            card = {'id': uuid.uuid4().hex, 'batch_id': batch['id'], 'account_id': account_id,
                    'position': index + 1, 'group': index // 4 + 1, 'content_type': content_type,
                    'pillar': (question['pillar'] if question and question['pillar'] in strategy['pillars'] else strategy['pillars'][index % 3]),
                    'question_id': question['id'] if question else None,
                    'question': question['question'] if question else '',
                    'title': question['question'][:300] if question else '',
                    'material_plan': question['materials'] if question else '',
                    'material_ready': question['material_ready'] if question else False,
                    'reader_action': '', 'expected_feedback': '', 'variable': '', 'body': '',
                    'media_ids': [], 'draft_id': None, 'revision': 0, 'draft_revision': None,
                    'created_at': core.now(), 'updated_at': core.now()}
            connection.execute('INSERT INTO planning_items VALUES(?,?,?,?)',
                               (card['id'], account_id, batch['id'], _dump(card)))
            cards.append(_card_public(card, {}))
    batch['cards'] = cards
    return {'batch': batch}


def _media_ids(value):
    if not isinstance(value, list) or any(not isinstance(v, str) or not v.strip() for v in value):
        raise core.ValidationError('media_ids 必须是素材 ID 列表')
    value = list(dict.fromkeys(value))
    if value:
        available = {job['id'] for job in media_uploads.snapshot()['jobs']}
        if any(identifier not in available for identifier in value):
            raise core.ValidationError('部分素材不存在，请重新选择')
    return value


def update_plan_item(data):
    account_id = _account(data.get('account_id'))['id']
    fields = data.get('fields', data)
    if not isinstance(fields, dict):
        raise core.ValidationError('fields 必须是对象')
    # Validate media outside the write transaction; media storage uses its own connection.
    media_ids = _media_ids(fields['media_ids']) if 'media_ids' in fields else None
    with _connect() as connection:
        card = _owned(connection, 'planning_items', data.get('id'), account_id, '计划卡')
        before = dict(card)
        for field in CARD_TEXT_FIELDS:
            if field in fields:
                card[field] = _text(fields[field], field, limit=30000 if field == 'body' else (300 if field == 'title' else 4000))
        if 'content_type' in fields:
            if fields['content_type'] not in CONTENT_SEQUENCE:
                raise core.ValidationError('内容类型必须为 method、case、process 或 template')
            card['content_type'] = fields['content_type']
        if 'material_ready' in fields:
            if not isinstance(fields['material_ready'], bool):
                raise core.ValidationError('material_ready 必须是 true 或 false')
            card['material_ready'] = fields['material_ready']
        if 'pillar' in fields:
            card['pillar'] = _text(fields['pillar'], 'pillar', limit=100)
            _check_pillar(connection, account_id, card['pillar'])
        if 'question_id' in fields:
            identifier = fields['question_id']
            if identifier is not None and not isinstance(identifier, str):
                raise core.ValidationError('question_id 必须是问题 ID 或 null')
            question = _owned(connection, 'planning_questions', identifier, account_id, '问题') if identifier else None
            if question:
                for other in _list(connection, 'planning_items', account_id):
                    if other['batch_id'] == card['batch_id'] and other['id'] != card['id']:
                        same_text = ' '.join(other.get('question', '').split()).casefold() == ' '.join(question['question'].split()).casefold()
                        if other.get('question_id') == identifier or same_text:
                            raise core.ValidationError('同一批次不能重复使用同一个问题')
                if question['status'] == 'parked':
                    raise core.ValidationError('请先恢复已搁置问题，再用于内容计划')
                question['status'] = 'selected'
                question['updated_at'] = core.now()
                _save(connection, 'planning_questions', question)
            card['question_id'] = question['id'] if question else None
            card['question'] = question['question'] if question else ''
            if card['question_id'] != before.get('question_id') and 'material_ready' not in fields:
                card['material_ready'] = False
        if media_ids is not None:
            card['media_ids'] = media_ids
        if card != before:
            card['revision'] = card.get('revision', 0) + 1
            card['updated_at'] = core.now()
            _save(connection, 'planning_items', card)
            _touch_batch(connection, card['batch_id'], account_id)
    return {'card': _card_public(card, _drafts(account_id))}


@contextmanager
def _draft_creation_lock():
    # CLI, HTTP and MCP can run in separate processes: protect the shared link too.
    path = Path(core.DB).with_suffix('.planning-draft.lock')
    path.parent.mkdir(parents=True, exist_ok=True)
    with _draft_lock, path.open('a') as lockfile:
        _lock_file(lockfile)
        try:
            yield
        finally:
            _unlock_file(lockfile)


def _lock_file(handle):
    """An exclusive lock other processes wait for: flock, or on Windows byte 0 via msvcrt."""
    if fcntl is not None:
        fcntl.flock(handle, fcntl.LOCK_EX)
        return
    handle.seek(0)
    while True:
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            return
        except OSError:
            continue   # LK_LOCK gives up after about 10 s; keep waiting like flock does


def _unlock_file(handle):
    if fcntl is not None:
        fcntl.flock(handle, fcntl.LOCK_UN)
        return
    handle.seek(0)
    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def create_plan_draft(data):
    account_id = _account(data.get('account_id'))['id']
    with _draft_creation_lock():
        with _connect() as connection:
            card = _owned(connection, 'planning_items', data.get('id'), account_id, '计划卡')
        drafts = _drafts(account_id)
        if card.get('draft_id'):
            draft = drafts.get(card['draft_id'])
            if not draft:
                raise core.ValidationError('关联草稿已不存在，请先检查草稿记录，避免重复创建')
            public = _card_public(card, drafts)
            return {'card': public, 'draft': draft, 'reused': True,
                    'draft_sync_status': public['draft_sync_status']}
        _text(card.get('title'), 'title', required=True, limit=300)
        _text(card.get('body'), 'body', required=True, limit=30000)
        if not card.get('question_id'):
            raise core.ValidationError('先为计划卡关联真实问题，再转入草稿')
        _text(card.get('material_plan'), 'material_plan', required=True)
        draft = core.create_draft({'title': card['title'], 'body': card['body'],
                                   'account_ids': [account_id], 'media_ids': card['media_ids']})['draft']
        with _connect() as connection:
            current = _owned(connection, 'planning_items', card['id'], account_id, '计划卡')
            current['draft_id'] = draft['id']
            current['draft_revision'] = card['revision']
            current['updated_at'] = core.now()
            _save(connection, 'planning_items', current)
            _touch_batch(connection, card['batch_id'], account_id)
        public = _card_public(current, {draft['id']: draft})
    return {'card': public, 'draft': draft, 'reused': False, 'draft_sync_status': public['draft_sync_status']}


def _metric(value, field):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool) or not isinstance(value, (str, float, int)):
        raise core.ValidationError(f'{field} 必须是非负数字，留空表示未知')
    try:
        number = float(value)
        if not math.isfinite(number) or not 0 <= number < 1e15:
            raise ValueError()
        if field != 'production_minutes' and number != int(number):
            raise ValueError()
    except (ValueError, OverflowError):
        raise core.ValidationError(f'{field} 必须是非负数字，留空表示未知') from None
    return number if field == 'production_minutes' else int(number)


def observe_plan_item(data):
    account_id = _account(data.get('account_id'))['id']
    published_at = core.iso(_text(data.get('published_at'), 'published_at', required=True), 'published_at')
    observed_at = core.iso(_text(data.get('observed_at'), 'observed_at', required=True), 'observed_at')
    if observed_at < published_at:
        raise core.ValidationError('采集时间不能早于发布时间')
    values = {field: _metric(data.get(field), field) for field in OBSERVATION_METRICS}
    values.update({field: _text(data.get(field), field) for field in
                   ('reader_question', 'next_answer', 'next_materials', 'note')})
    values.update(post_url=_url(data.get('post_url'), 'post_url'), published_at=published_at,
                  observed_at=observed_at, source='manual', created_at=datetime.now(timezone.utc).isoformat(timespec='microseconds'),
                  id=uuid.uuid4().hex, account_id=account_id, promoted_question_id=None)
    with _connect() as connection:
        card = _owned(connection, 'planning_items', data.get('id'), account_id, '计划卡')
        values.update(item_id=card['id'], batch_id=card['batch_id'],
                      original_question=card['question'], original_question_id=card['question_id'],
                      original_pillar=card['pillar'], original_title=card['title'])
        connection.execute('INSERT INTO planning_observations VALUES(?,?,?,?,?)',
                           (values['id'], account_id, card['id'], card['batch_id'], _dump(values)))
        _touch_batch(connection, card['batch_id'], account_id)
    return {'observation': values}


def review_batch(data):
    account_id = _account(data.get('account_id'))['id']
    group = data.get('group')
    if isinstance(group, bool) or not isinstance(group, int) or group not in (1, 2, 3):
        raise core.ValidationError('group 为 1、2 或 3')
    workspace = get_workspace(account_id)
    batch = next((batch for batch in workspace['batches'] if batch['id'] == data.get('batch_id')), None)
    if not batch:
        raise core.ValidationError('批次不存在或不属于当前账号')
    items, missing, windows = [], [], []
    for card in batch['cards']:
        if card['group'] != group:
            continue
        records = [o for o in workspace['observations'] if o['item_id'] == card['id']]
        observation = max(records, key=lambda o: (o['observed_at'], o['created_at'], o['id'])) if records else None
        window, save_rate = None, None
        if observation:
            window = (datetime.fromisoformat(observation['observed_at']) - datetime.fromisoformat(observation['published_at'])).total_seconds() / 3600
            windows.append(window)
            if observation['views'] is not None and observation['views'] > 0 and observation['saves'] is not None:
                save_rate = round(observation['saves'] / observation['views'] * 100, 3)
        else:
            missing.append(card['position'])
        items.append({'card': card, 'observation': observation,
                      'window_hours': round(window, 3) if window is not None else None,
                      'save_rate_percent': save_rate})
    comparable = len(windows) >= 2 and max(windows) - min(windows) <= 1
    limitations = ['数据由用户人工录入，未连接平台实时数据。', '阅读/播放量与曝光量分别保留；未知值不当作 0。',
                   '收藏率仅在阅读/播放量大于 0 且收藏数已知时计算。', '按计划顺序展示，不自动排名，也不据小样本推断因果。']
    if len(windows) < 4:
        limitations.append(f'本组只有 {len(windows)}/4 篇有观察记录，可以先记录判断，暂无完整组结果。')
    if len(windows) >= 2 and not comparable:
        limitations.append('采集窗口相差超过 1 小时，不直接判断哪篇更好。')
    return {'batch_id': batch['id'], 'account_id': account_id, 'group': group, 'items': items,
            'observed_count': len(windows), 'missing_positions': missing,
            'windows_comparable': comparable, 'comparison_rule': WINDOW_RULE,
            'ranking': [], 'limitations': limitations}


def promote_feedback(data):
    account_id = _account(data.get('account_id'))['id']
    with _connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        observation = _owned(connection, 'planning_observations', data.get('observation_id'), account_id, '观察记录')
        if observation.get('promoted_question_id'):
            question = _owned(connection, 'planning_questions', observation['promoted_question_id'], account_id, '问题')
            return {'question': question, 'observation': observation, 'reused': True}
        for field in ('reader_question', 'next_answer', 'next_materials'):
            _text(observation.get(field), field, required=True)
        card = _owned(connection, 'planning_items', observation['item_id'], account_id, '计划卡')
        question = _question_values({'question': observation['reader_question'],
            'context': observation['next_answer'], 'source_type': 'comment',
            'source_url': observation['post_url'], 'source_note': '由人工复盘中的读者追问转入',
            'pillar': observation['original_pillar'], 'materials': observation['next_materials'],
            'material_ready': False, 'priority': 1})
        question.update(id=uuid.uuid4().hex, account_id=account_id, created_at=core.now(),
            original_question=observation['original_question'], reader_question=observation['reader_question'],
            next_answer=observation['next_answer'], required_materials=observation['next_materials'],
            provenance={'type': 'manual_observation', 'observation_id': observation['id'],
                        'item_id': card['id'], 'batch_id': card['batch_id'], 'post_url': observation['post_url'],
                        'observed_at': observation['observed_at']})
        connection.execute('INSERT INTO planning_questions VALUES(?,?,?)', (question['id'], account_id, _dump(question)))
        observation['promoted_question_id'] = question['id']
        _save(connection, 'planning_observations', observation)
    return {'question': question, 'observation': observation, 'reused': False}


def export_plan(batch_id, account_id=None):
    if account_id is None:
        with _connect() as connection:
            row = connection.execute('SELECT account_id FROM planning_batches WHERE id=?', (batch_id,)).fetchone()
        if not row:
            raise core.ValidationError('批次不存在')
        account_id = row['account_id']
    workspace = get_workspace(account_id)
    batch = next((b for b in workspace['batches'] if b['id'] == batch_id), None)
    if not batch:
        raise core.ValidationError('批次不存在或不属于当前账号')
    return {'schema_version': 1, 'account_id': account_id, 'exported_at': core.now(),
            'strategy': workspace['strategy'], 'questions': workspace['questions'],
            'batch': {k: v for k, v in batch.items() if k != 'cards'}, 'cards': batch['cards'],
            'observations': [o for o in workspace['observations'] if o['batch_id'] == batch_id],
            'source_reference': dict(SOURCE_REFERENCE), 'delivery': 'local_only',
            'published': False, 'ai_mode': 'structured_local', 'remote_publishing_enabled': False}


def dispatch(action, args=None):
    args = {} if args is None else args
    if not isinstance(args, dict):
        raise core.ValidationError('arguments 必须是对象')
    if not isinstance(action, str):
        raise core.ValidationError('action 必须是动作名称')
    if action == 'planning_workspace':
        return get_workspace(args.get('account_id'))
    if action == 'export_plan':
        _account(args.get('account_id'))
        return export_plan(args.get('batch_id'), args['account_id'])
    actions = {'save_strategy': save_strategy, 'add_question': add_question,
               'update_question': update_question, 'create_batch': create_batch,
               'update_plan_item': update_plan_item, 'create_plan_draft': create_plan_draft,
               'observe_plan_item': observe_plan_item, 'review_batch': review_batch,
               'promote_feedback': promote_feedback}
    if action not in actions:
        raise core.ValidationError('未知的内容计划动作')
    return actions[action](args)
