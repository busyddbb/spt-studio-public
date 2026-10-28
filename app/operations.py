"""Offline project handoff, human publication receipts and portable exports.

Nothing in this module contacts a social platform. A receipt describes what a
person entered; it is never a platform confirmation or a scheduled publication.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import tempfile
import uuid
import zipfile
from urllib.parse import urlsplit

if __package__:
    from . import core, media_uploads
else:
    import core, media_uploads

PROJECTS_CONFIG = Path(__file__).with_name('projects.json')
MAX_PACKAGE_BYTES = 20 * 1024 ** 3
MAX_BACKUP_BYTES = 2 * 1024 ** 3
METRIC_FIELDS = ('views', 'reach', 'likes', 'comments', 'shares', 'saves', 'clicks')
CONTENT_FIELDS = ('title', 'body', 'platforms', 'account_ids', 'media_ids', 'platform_variants', 'scheduled_at')
MANUAL_LABEL = '人工填报 · 未向平台自动核验'


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


@contextmanager
def _connect():
    with core.connection() as connection:
        connection.executescript('''
          CREATE TABLE IF NOT EXISTS ops_projects (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS ops_bindings (draft_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS ops_receipts (
            id TEXT PRIMARY KEY, draft_id TEXT NOT NULL, account_id TEXT NOT NULL,
            url TEXT NOT NULL, voided INTEGER NOT NULL DEFAULT 0, payload TEXT NOT NULL);
          CREATE UNIQUE INDEX IF NOT EXISTS ops_receipt_active
            ON ops_receipts(draft_id, account_id, url) WHERE voided=0;
          CREATE TABLE IF NOT EXISTS ops_metrics (
            id TEXT PRIMARY KEY, receipt_id TEXT NOT NULL, observed_at TEXT NOT NULL,
            payload TEXT NOT NULL, UNIQUE(receipt_id, observed_at));
        ''')
        yield connection

def _text(value, field, required=False, limit=4000):
    if value is None and not required:
        return ''
    if not isinstance(value, str):
        raise core.ValidationError(f'{field} 必须是文本')
    value = value.strip()
    if required and not value:
        raise core.ValidationError(f'{field} 不能为空')
    if len(value) > limit or any(ord(ch) < 32 and ch not in '\n\r\t' for ch in value):
        raise core.ValidationError(f'{field} 过长或包含无效字符')
    return value


def _list_text(value, field, limit=30):
    if not isinstance(value, list) or len(value) > limit:
        raise core.ValidationError(f'{field} 必须是最多 {limit} 项的文本列表')
    return [_text(item, field, required=True, limit=2000) for item in value]


def _project_values(data, previous=None):
    if not isinstance(data, dict):
        raise core.ValidationError('project 必须是对象')
    result = dict(previous or {})
    for key in ('id', 'name', 'kind', 'root_path', 'entry_path', 'delivery_path',
                'summary', 'boundary', 'checked_at', 'workflow', 'channels'):
        if key in data:
            result[key] = data[key]
    for key in ('id', 'name', 'kind', 'root_path'):
        result[key] = _text(result.get(key), key, required=True, limit=4000 if key == 'root_path' else 200)
    if not Path(result['root_path']).is_absolute():
        raise core.ValidationError('项目根目录必须是绝对路径')
    for key in ('entry_path', 'delivery_path', 'summary', 'boundary', 'checked_at'):
        result[key] = _text(result.get(key), key)
    root = Path(result['root_path']).resolve()
    result['root_path'] = str(root)
    for key in ('entry_path', 'delivery_path'):
        if result[key]:
            target = Path(result[key])
            target = (root / target).resolve() if not target.is_absolute() else target.resolve()
            if not target.is_relative_to(root):
                raise core.ValidationError(f'{key} 必须在项目根目录内')
            result[key] = str(target)
    for key in ('workflow', 'channels'):
        result[key] = _list_text(result.get(key, []), key)
    return result


def _projects(connection):
    defaults = []
    if PROJECTS_CONFIG.is_file():
        try:
            data = json.loads(PROJECTS_CONFIG.read_text(encoding='utf-8'))
            defaults = data.get('projects', []) if isinstance(data, dict) else data
            if not isinstance(defaults, list):
                raise ValueError('projects 不是列表')
        except (OSError, ValueError, TypeError) as error:
            raise core.ValidationError('项目配置无法读取，请检查 app/projects.json') from error
    projects = {}
    for value in defaults:
        project = _project_values(value)
        if project['id'] in projects:
            raise core.ValidationError('项目配置包含重复 ID')
        projects[project['id']] = project
    for row in connection.execute('SELECT payload FROM ops_projects ORDER BY rowid'):
        project = json.loads(row['payload'])
        projects[project['id']] = project
    return list(projects.values())


def _project_public(project):
    project = dict(project)
    root = Path(project['root_path'])
    project['root_exists'] = root.is_dir()
    for field in ('entry_path', 'delivery_path'):
        path = project.get(field, '')
        target = (root / path) if path and not Path(path).is_absolute() else Path(path) if path else None
        project[field.replace('_path', '_exists')] = bool(target and target.exists())
    return project


def save_project(data):
    value = data.get('project', data) if isinstance(data, dict) else data
    if not isinstance(value, dict):
        raise core.ValidationError('project 必须是对象')
    value = dict(value)
    if not value.get('id'):
        value['id'] = 'project-' + uuid.uuid4().hex[:16]
    with _connect() as connection:
        previous = next((p for p in _projects(connection) if p['id'] == value.get('id')), None)
        project = _project_values(value, previous)
        project['updated_at'] = core.now()
        connection.execute('INSERT OR REPLACE INTO ops_projects VALUES(?,?)', (project['id'], _json(project)))
        core.audit(connection, 'save_project', {'id': project['id']})
    return {'project': _project_public(project)}


def _draft(connection, identifier):
    identifier = _text(identifier, 'draft_id', required=True, limit=200)
    row = connection.execute('SELECT payload FROM drafts WHERE id=?', (identifier,)).fetchone()
    if not row:
        raise core.ValidationError('草稿不存在')
    return json.loads(row['payload'])


def _fingerprint(draft):
    return hashlib.sha256(_json({field: draft.get(field, [] if field.endswith('_ids') else {} if field == 'platform_variants' else '')
                               for field in CONTENT_FIELDS}).encode()).hexdigest()


def _binding_public(binding, draft):
    result = dict(binding)
    media_issues = _draft_media_issues(draft)
    result['needs_recheck'] = result.get('checked_fingerprint') != _fingerprint(draft) or bool(media_issues)
    result['media_issues'] = media_issues
    checks = result.get('checklist', {})
    result['checklist'] = {key: bool(checks.get(key) is True and not result['needs_recheck'])
                           for key in ('content', 'media', 'account')}
    return result


def _draft_media_issues(draft):
    identifiers = draft.get('media_ids', [])
    if not identifiers:
        return []
    with media_uploads._connect() as connection:
        rows = {row['id']: dict(row) for row in connection.execute('SELECT * FROM media_upload_jobs')}
    issues = []
    for identifier in identifiers:
        row = rows.get(identifier)
        if row is None:
            issues.append('素材登记不存在')
        else:
            check = _asset_check(row)
            if check['issue']:
                issues.append(f'{row["name"]}：{check["issue"]}')
    return issues


def bind_draft(data):
    with _connect() as connection:
        draft = _draft(connection, data.get('draft_id'))
        project_id = _text(data.get('project_id'), 'project_id', limit=200)
        if project_id and not any(p['id'] == project_id for p in _projects(connection)):
            raise core.ValidationError('项目不存在')
        row = connection.execute('SELECT payload FROM ops_bindings WHERE draft_id=?', (draft['id'],)).fetchone()
        binding = json.loads(row['payload']) if row else {'created_at': core.now()}
        binding.update(draft_id=draft['id'], project_id=project_id, updated_at=core.now())
        for field in ('format', 'brief'):
            if field in data or field not in binding:
                binding[field] = _text(data.get(field), field)
        if 'checklist' in data or 'checklist' not in binding:
            checklist = data.get('checklist', {})
            if not isinstance(checklist, dict) or any(not isinstance(value, bool) for value in checklist.values()):
                raise core.ValidationError('checklist 必须是核对项与布尔值组成的对象')
            binding['checklist'] = {key: checklist.get(key, False) is True for key in ('content', 'media', 'account')}
            binding['checked_fingerprint'] = _fingerprint(draft)
        connection.execute('INSERT OR REPLACE INTO ops_bindings VALUES(?,?)', (draft['id'], _json(binding)))
        core.audit(connection, 'bind_project', {'draft_id': draft['id'], 'project_id': project_id})
    return {'binding': _binding_public(binding, draft)}


def _url(value):
    value = _text(value, '作品链接', True)
    try:
        parts = urlsplit(value)
        if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password or any(ch.isspace() for ch in value):
            raise ValueError()
        parts.port
    except (ValueError, UnicodeError):
        raise core.ValidationError('请填写完整的 http(s) 作品链接') from None
    return value


def _past_time(value, field):
    if not isinstance(value, str) or not value.strip():
        raise core.ValidationError(f'{field} 不能为空')
    normalized = core.iso(value, field)
    if datetime.fromisoformat(normalized) > datetime.now(timezone.utc):
        raise core.ValidationError(f'{field} 不能是未来时间')
    return normalized


def _receipt_public(receipt, draft=None, metrics=None):
    result = dict(receipt)
    result.update(source='manual', source_label=MANUAL_LABEL,
                  stale=bool(draft is None or receipt['fingerprint'] != _fingerprint(draft)),
                  metrics=metrics)
    return result


def save_receipt(data):
    # core.state also includes accounts created by a real CSV import.
    accounts = {a['id']: a for a in core.state('real')['accounts']}
    account_id = _text(data.get('account_id'), 'account_id', True, 200)
    url = _url(data.get('url'))
    published_at = _past_time(data.get('published_at'), '实际发布时间')
    note = _text(data.get('note'), '发布备注')
    with _connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        draft = _draft(connection, data.get('draft_id'))
        account = accounts.get(account_id)
        if not account or account_id not in draft.get('account_ids', []) or account['platform'] == 'google_ads':
            raise core.ValidationError('只能为草稿已选择的真实目标账号登记发布')
        if draft.get('status') != 'approved':
            raise core.ValidationError('请先完成内容审核，再登记实际发布')
        binding_row = connection.execute('SELECT payload FROM ops_bindings WHERE draft_id=?', (draft['id'],)).fetchone()
        binding = _binding_public(json.loads(binding_row['payload']), draft) if binding_row else None
        if not binding or not all(binding['checklist'].values()):
            raise core.ValidationError('请先核对当前版本的内容、素材与目标账号')
        existing = connection.execute('SELECT payload FROM ops_receipts WHERE draft_id=? AND account_id=? AND url=? AND voided=0',
                                      (draft['id'], account_id, url)).fetchone()
        if existing:
            return {'receipt': _receipt_public(json.loads(existing['payload']), draft)}
        if connection.execute('SELECT 1 FROM ops_receipts WHERE draft_id=? AND account_id=? AND voided=0',
                              (draft['id'], account_id)).fetchone():
            raise core.ValidationError('此账号已有有效发布记录；误记请先作废，另一个作品请建立独立草稿')
        receipt = {'id': uuid.uuid4().hex, 'draft_id': draft['id'], 'account_id': account_id,
                   'account_name': account['name'], 'account_handle': account['handle'],
                   'platform': account['platform'], 'url': url, 'published_at': published_at,
                   'note': note, 'recorded_at': core.now(), 'source': 'manual', 'source_label': MANUAL_LABEL,
                   'title': draft['title'],
                   'body': draft.get('platform_variants', {}).get(account['platform']) or draft['body'],
                   'fingerprint': _fingerprint(draft), 'draft_snapshot': {key: draft.get(key) for key in CONTENT_FIELDS},
                   'voided': False}
        connection.execute('INSERT INTO ops_receipts VALUES(?,?,?,?,0,?)',
                           (receipt['id'], draft['id'], account_id, url, _json(receipt)))
        core.audit(connection, 'manual_publication_receipt', {'id': receipt['id'], 'draft_id': draft['id'], 'account_id': account_id})
    return {'receipt': _receipt_public(receipt, draft)}


def void_receipt(data):
    identifier = _text(data.get('id'), 'id', True, 200)
    reason = _text(data.get('reason'), '作废原因', True)
    with _connect() as connection:
        row = connection.execute('SELECT payload FROM ops_receipts WHERE id=?', (identifier,)).fetchone()
        if not row:
            raise core.ValidationError('发布记录不存在')
        receipt = json.loads(row['payload'])
        if not receipt.get('voided'):
            receipt.update(voided=True, voided_at=core.now(), void_reason=reason)
            connection.execute('UPDATE ops_receipts SET voided=1,payload=? WHERE id=?', (_json(receipt), identifier))
            # History remains in ops_metrics. Invalidated observations must not
            # keep contributing to the current analytics overview.
            connection.execute('DELETE FROM observations WHERE json_extract(payload,\'$.receipt_id\')=? AND json_extract(payload,\'$.source_type\')=\'manual_receipt\'', (identifier,))
            core.audit(connection, 'void_publication_receipt', {'id': identifier, 'reason': reason})
        draft = _draft(connection, receipt['draft_id'])
    return {'receipt': _receipt_public(receipt, draft)}


def record_metrics(data):
    identifier = _text(data.get('receipt_id'), 'receipt_id', True, 200)
    observed_at = _past_time(data.get('observed_at'), '数据采集时间')
    values = {field: core.number(data.get(field), field) for field in METRIC_FIELDS}
    if not any(value is not None for value in values.values()):
        raise core.ValidationError('请至少填写一项真实指标；未知项留空')
    with _connect() as connection:
        row = connection.execute('SELECT payload FROM ops_receipts WHERE id=?', (identifier,)).fetchone()
        if not row:
            raise core.ValidationError('发布记录不存在')
        receipt = json.loads(row['payload'])
        if receipt.get('voided'):
            raise core.ValidationError('已作废的发布记录不能填写指标')
        if observed_at < receipt['published_at']:
            raise core.ValidationError('数据采集时间不能早于实际发布时间')
        source = {'platform': receipt['platform'], 'account': receipt['account_handle'],
                  'post_id': receipt['url'], 'url': receipt['url'], 'title': receipt['title'],
                  'published_at': receipt['published_at'], 'observed_at': observed_at, **values}
        # core's CSV parser treats falsey numeric zero as empty; feed textual
        # values just like an actual CSV so known zero remains known zero.
        observation, natural, observed = core.clean_record(
            {key: str(value) if value is not None else '' for key, value in source.items()}, 'social', MANUAL_LABEL)
        observation.update(source_type='manual_receipt', source_id='manual:' + identifier,
                           receipt_id=identifier, imported_at=core.now())
        connection.execute('INSERT OR REPLACE INTO observations VALUES(?,?,?,?,?,?)',
                           (observation['id'], 'social', 'real', natural, observed, _json(observation)))
        metric_id = hashlib.sha256((identifier + '|' + observed_at).encode()).hexdigest()[:24]
        metric = {'id': metric_id, 'receipt_id': identifier, 'observed_at': observed_at,
                  'recorded_at': core.now(), 'source': 'manual', **values}
        connection.execute('INSERT OR REPLACE INTO ops_metrics VALUES(?,?,?,?)',
                           (metric_id, identifier, observed_at, _json(metric)))
        core.audit(connection, 'manual_publication_metrics', {'receipt_id': identifier, 'observation_id': observation['id']})
        draft = _draft(connection, receipt['draft_id'])
    return {'observation': observation, 'receipt': _receipt_public(receipt, draft, metric)}


def snapshot():
    state = core.state('real')
    with _connect() as connection:
        projects = [_project_public(p) for p in _projects(connection)]
        raw_bindings = [json.loads(row['payload']) for row in connection.execute('SELECT payload FROM ops_bindings')]
        raw_receipts = [json.loads(row['payload']) for row in connection.execute('SELECT payload FROM ops_receipts ORDER BY rowid DESC')]
        latest = {}
        for row in connection.execute('SELECT receipt_id,payload FROM ops_metrics ORDER BY observed_at,rowid'):
            latest[row['receipt_id']] = json.loads(row['payload'])
    draft_map = {d['id']: d for d in state['drafts']}
    bindings = [_binding_public(b, draft_map[b['draft_id']]) for b in raw_bindings if b['draft_id'] in draft_map]
    receipts = [_receipt_public(r, draft_map.get(r['draft_id']), latest.get(r['id'])) for r in raw_receipts]
    binding_map = {b['draft_id']: b for b in bindings}
    for draft in state['drafts']:
        bound = binding_map.get(draft['id'])
        linked = [r for r in receipts if r['draft_id'] == draft['id']]
        active = [r for r in linked if not r['voided']]
        current = {r['account_id'] for r in active if not r['stale']}
        targets = set(draft.get('account_ids', []))
        draft.update(binding=bound, project_id=bound['project_id'] if bound else '', receipts=linked,
                     publication_status='complete' if targets and targets <= current else 'partial' if active else 'unpublished')
    media = media_uploads.snapshot()['jobs']
    with media_uploads._connect() as connection:
        raw_media = {row['id']: dict(row) for row in connection.execute('SELECT * FROM media_upload_jobs')}
    for item in media:
        check = _asset_check(raw_media[item['id']])
        item.update(available=check['readable'], changed=not check['unchanged'], issue=check['issue'])
    return {'projects': projects, 'drafts': state['drafts'], 'accounts': state['accounts'],
            'receipts': receipts, 'media': media, 'bindings': bindings,
            'stats': {'projects': len(projects), 'drafts': len(state['drafts']),
                      'approved': sum(d.get('status') == 'approved' for d in state['drafts']),
                      'receipts': sum(not r['voided'] for r in receipts),
                      'published_drafts': sum(d['publication_status'] == 'complete' for d in state['drafts'])},
            'source_label': MANUAL_LABEL, 'remote_publishing_enabled': False,
            'updated_at': core.now()}


def _safe_filename(value, fallback):
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', str(value)).strip('. ')[:120]
    return value or fallback


def _asset_check(row):
    result = {'readable': False, 'unchanged': False, 'issue': ''}
    try:
        path, info = media_uploads._file_info(row['path'])
        result['unchanged'] = media_uploads._fingerprint(info) == tuple(row[key] for key in ('size', 'mtime_ns', 'device', 'inode'))
        if not result['unchanged']:
            result['issue'] = '原文件已变更，请重新加入素材并审核'
        else:
            with path.open('rb') as stream:
                stream.read(1)
            result['readable'] = True
    except (OSError, core.ValidationError):
        result['issue'] = '原文件不存在、无法读取或已被替换'
    return result


def package_manifest(draft_id):
    state = snapshot()
    draft = next((d for d in state['drafts'] if d['id'] == draft_id), None)
    if not draft:
        raise core.ValidationError('草稿不存在')
    accounts = {a['id']: a for a in state['accounts']}
    targets = []
    for index, identifier in enumerate(draft.get('account_ids', []), 1):
        account = accounts.get(identifier)
        if not account:
            raise core.ValidationError('部分目标账号不存在，请重新选择')
        targets.append({'account_id': identifier, 'platform': account['platform'],
                        'name': account['name'], 'handle': account['handle'],
                        'title': draft['title'],
                        'body': draft.get('platform_variants', {}).get(account['platform']) or draft['body'],
                        'text_file': f'文案/{index:02d}-{_safe_filename(account["name"], "账号")}.txt'})
    with media_uploads._connect() as connection:
        rows = {row['id']: dict(row) for row in connection.execute('SELECT * FROM media_upload_jobs')}
    assets = []
    for index, identifier in enumerate(draft.get('media_ids', []), 1):
        row = rows.get(identifier)
        if not row:
            assets.append({'id': identifier, 'order': index, 'readable': False, 'unchanged': False, 'issue': '素材登记不存在'})
            continue
        assets.append({'id': identifier, 'order': index, 'name': row['name'], 'path': row['path'],
                       'size': row['size'], 'mime_type': row['mime_type'],
                       'archive_path': f'素材/{index:02d}-{_safe_filename(row["name"], "素材")}',
                       'fingerprint': {key: row[key] for key in ('size', 'mtime_ns', 'device', 'inode')},
                       **_asset_check(row)})
    project = next((p for p in state['projects'] if p['id'] == draft['project_id']), None)
    issues = [f'素材 {asset["order"]}：{asset["issue"]}' for asset in assets if asset.get('issue')]
    if draft['status'] != 'approved':
        issues.append('草稿尚未审核批准')
    if not targets:
        issues.append('尚未选择真实目标账号')
    total_bytes = sum(a.get('size', 0) for a in assets)
    if total_bytes > MAX_PACKAGE_BYTES:
        issues.append('素材合计超过 20 GiB，请拆分发布包')
    return {'schema_version': 1, 'exported_at': core.now(), 'delivery': 'manual',
            'published': False, 'source_label': MANUAL_LABEL, 'draft': draft,
            'fingerprint': _fingerprint(draft), 'project': project, 'binding': draft.get('binding'),
            'accounts': targets, 'media': assets, 'total_media_bytes': total_bytes,
            'ready': not issues, 'issues': issues,
            'instructions': '解压后按素材编号上传，复制对应账号文案；在平台确认成功后回到工作台填写作品链接。此文件包不会自动发布。'}


def _temporary_zip(prefix):
    descriptor, name = tempfile.mkstemp(prefix=prefix, suffix='.zip')
    os.close(descriptor)
    return Path(name)


def prepare_package(draft_id):
    manifest = package_manifest(draft_id)
    if not manifest['ready']:
        raise core.ValidationError('不能导出完整发布包：' + '；'.join(manifest['issues']))
    if shutil.disk_usage(tempfile.gettempdir()).free < manifest['total_media_bytes'] + 256 * 1024 ** 2:
        raise core.ValidationError('临时磁盘空间不足，无法生成完整发布包')
    path = _temporary_zip('media-publication-')
    try:
        with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
            notes = [f'# {manifest["draft"]["title"]}', '', manifest['instructions'], '',
                     '审核状态：已批准。发布时间为本地计划，不触发自动发布。',
                     '已有发布记录均为人工填报，可在 manifest.json 查看；本次导出不改变发布状态。', '',
                     '## 发布顺序', '1. 打开相应平台并核对账号。', '2. 按“素材”文件夹编号选择图片或视频。',
                     '3. 复制“文案”文件夹内相应账号的标题和正文。',
                     '4. 核对封面、顺序与话题，在平台完成发布。', '5. 将作品链接和实际时间登记回 SPT。', '',
                     '素材源文件不会移动或删除。项目规则与入口保留在 manifest.json，原始项目目录不打入本包。']
            archive.writestr('发布说明.md', '\n'.join(notes))
            archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
            for account in manifest['accounts']:
                text = f'目标账号：{account["name"]}（{account["handle"]}）\n平台：{account["platform"]}\n\n标题：{account["title"]}\n\n{account["body"]}\n'
                archive.writestr(account['text_file'], text)
            for asset in manifest['media']:
                # Open once, reject symlinks/replacements, then stream that exact
                # descriptor so ZIP creation never reads a whole video into RAM.
                descriptor = os.open(asset['path'], os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0))
                with os.fdopen(descriptor, 'rb') as source:
                    before = os.fstat(source.fileno())
                    expected = tuple(asset['fingerprint'][key] for key in ('size', 'mtime_ns', 'device', 'inode'))
                    if not stat.S_ISREG(before.st_mode) or media_uploads._fingerprint(before) != expected:
                        raise core.ValidationError('生成发布包时素材已变更，请重新审核')
                    with archive.open(asset['archive_path'], 'w', force_zip64=True) as destination:
                        shutil.copyfileobj(source, destination, length=1024 * 1024)
                    if media_uploads._fingerprint(os.fstat(source.fileno())) != expected:
                        raise core.ValidationError('生成发布包时素材已变更，请重新审核')
        return path
    except Exception:
        path.unlink(missing_ok=True)
        raise


def backup():
    """An SQLite-consistent work-data backup, excluding keys and original media."""
    path = _temporary_zip('media-workdata-')
    try:
        with tempfile.TemporaryDirectory(prefix='media-backup-db-') as directory:
            db_copy = Path(directory) / 'media.sqlite3'
            with _connect() as source:
                with closing(sqlite3.connect(db_copy)) as target, target:
                    source.backup(target)
                project_config = _projects(source)
            candidates = []
            imports = Path(core.DB).parent / 'imports'
            if imports.is_dir():
                for candidate in sorted(imports.iterdir()):
                    if candidate.is_symlink() or not candidate.is_file() or candidate.suffix.lower() not in ('.csv', '.json'):
                        continue
                    candidates.append(candidate)
            if db_copy.stat().st_size + sum(p.stat().st_size for p in candidates) > MAX_BACKUP_BYTES:
                raise core.ValidationError('工作数据备份超过 2 GiB，请先整理原始导入表')
            with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
                archive.write(db_copy, 'data/media.sqlite3')
                archive.writestr('app/projects.json', json.dumps({'projects': project_config}, ensure_ascii=False, indent=2))
                for candidate in candidates:
                    archive.write(candidate, 'data/imports/' + candidate.name)
                archive.writestr('备份说明.md', '# SPT 工作数据备份\n\n包含一致性数据库快照、项目配置和原始 CSV/JSON 导入表。\n不包含原始图片视频、上传副本、Postiz 密钥、其他项目文件或软件安装包。\n素材路径仍指向原位置；恢复时保留或重新关联原素材。关闭多媒体服务后，用相应目录中的文件恢复到同版本软件。\n备份中的发布记录是人工填报，不是平台核验结果。\n')
        return path
    except Exception:
        path.unlink(missing_ok=True)
        raise


def dispatch(action, args=None):
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise core.ValidationError('arguments 必须是对象')
    actions = {'save_project': save_project, 'bind_draft': bind_draft,
               'save_receipt': save_receipt, 'void_receipt': void_receipt,
               'record_metrics': record_metrics}
    if action == 'snapshot':
        return snapshot()
    if action == 'package_manifest':
        return package_manifest(args.get('draft_id'))
    if action in actions:
        return actions[action](args)
    raise core.ValidationError(f'未知运营操作：{action}')
