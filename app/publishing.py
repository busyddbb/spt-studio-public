"""User-operated official publishing workspaces with stable local profiles.

Profiles identify WebKit stores; their existence is never evidence of a login.
This module neither sends media to platforms nor handles website credentials.
"""
from __future__ import annotations

import json
import uuid

if __package__:
    from . import core, operations
else:
    import core, operations


PLATFORMS = [
    {'id': 'xiaohongshu', 'name': 'rednote',
     'publish_url': 'https://creator.rednote.com/new/note-manager',
     'allowed_domains': ['rednote.com', 'xiaohongshu.com', 'xhslink.com'],
     'login_note': '确认登录的是本次要操作的账号。'},
    {'id': 'instagram', 'name': 'Instagram',
     'publish_url': 'https://www.instagram.com/',
     'allowed_domains': ['instagram.com', 'facebook.com', 'fb.com', 'meta.com'],
     'login_note': '用 Meta Business Suite 时，确认选中的是对的主页和 Instagram。'},
    {'id': 'facebook', 'name': 'Facebook',
     'publish_url': 'https://business.facebook.com/',
     'allowed_domains': ['facebook.com', 'instagram.com', 'fb.com', 'meta.com'],
     'login_note': '登录后选你有管理权限的主页（Page）。'},
    {'id': 'tiktok', 'name': 'TikTok',
     'publish_url': 'https://www.tiktok.com/tiktokstudio/upload',
     'allowed_domains': ['tiktok.com'],
     'login_note': 'Google 等第三方账号可能登不上，改用邮箱或手机号。'},
    {'id': 'youtube', 'name': 'YouTube',
     'publish_url': 'https://studio.youtube.com/',
     'allowed_domains': ['youtube.com'],
     'login_note': 'Google 不允许在 SPT 的窗口里登录，请在浏览器里操作。'},
    {'id': 'google_business', 'name': 'Google Business Profile',
     'publish_url': 'https://business.google.com/',
     'allowed_domains': ['business.google.com', 'mybusiness.google.com', 'www.google.com', 'accounts.google.com', 'myaccount.google.com', 'accounts.youtube.com'],
     'login_note': '用 Google 账号密码登录；如果 Google 要求额外验证，按手机上的提示确认。'},
    {'id': 'yelp', 'name': 'Yelp',
     'publish_url': 'https://biz.yelp.com/',
     'allowed_domains': ['yelp.com'],
     'login_note': '用邮箱密码登录商家后台；选 Google 登录会被 Google 拦下。'},
]


def _account(identifier):
    if not isinstance(identifier, str) or not identifier or len(identifier) > 200:
        raise core.ValidationError('请选择已登记的本地账号')
    account = next((a for a in core.state()['accounts'] if a['id'] == identifier), None)
    if account is None:
        raise core.ValidationError('账号档案不存在，请先添加准确的账号身份')
    if account['platform'] not in {p['id'] for p in PLATFORMS}:
        raise core.ValidationError('这个账号不属于内容发布平台')
    return account


def _profiles(create_for=None):
    with core.connection() as connection:
        connection.execute('''CREATE TABLE IF NOT EXISTS publish_web_profiles (
            account_id TEXT PRIMARY KEY, profile_id TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL)''')
        if create_for:
            connection.execute('INSERT OR IGNORE INTO publish_web_profiles VALUES(?,?,?)',
                               (create_for, str(uuid.uuid4()), core.now()))
        return {row['account_id']: dict(row) for row in connection.execute(
            'SELECT * FROM publish_web_profiles')}


def snapshot():
    profiles = _profiles()
    supported = {p['id'] for p in PLATFORMS}
    accounts = []
    for account in core.state()['accounts']:
        if account['platform'] not in supported:
            continue
        profile = profiles.get(account['id'])
        accounts.append({**account, 'profile_id': profile['profile_id'] if profile else None,
                         'session_saved': bool(profile),
                         'session_label': '在这台电脑上登录过；现在是否还登着，请在官方页确认' if profile
                         else '还没在这台电脑上登录过；第一次打开时会单独准备一个登录窗口'})
    return {'mode': 'official_web', 'accounts': accounts, 'platforms': PLATFORMS,
            'upload_jobs': _upload_jobs(),
            'requires_native': True, 'publishing_is_user_operated': True,
            'automatic_platform_confirmation': False,
            'credential_storage': '登录状态由 macOS 按账号分开保存；SPT 不读取、不导出密码和 Cookie',
            'session_backup_included': False}


META_SUITE = {'id': 'meta_suite', 'name': 'Meta Business Suite',
              'publish_url': 'https://business.facebook.com/latest/home',
              'allowed_domains': ['facebook.com', 'instagram.com', 'fb.com', 'meta.com'],
              'login_note': 'Instagram 和 Facebook 在 Meta Business Suite 里一起管理，登录一次即可。进入后请核对左上角选中的是哪个 Page / Instagram 账号。'}
META_PLATFORMS = {'instagram', 'facebook'}


def workspace(account_id, draft_id=None, target=None):
    account = _account(account_id)
    platform = next(p for p in PLATFORMS if p['id'] == account['platform'])
    if target == 'meta_suite':
        if account['platform'] not in META_PLATFORMS:
            raise core.ValidationError('只有 Instagram 和 Facebook 账号能打开 Meta Business Suite')
        if draft_id:
            raise core.ValidationError('带内容发布请打开平台本身的页面')
        platform = META_SUITE
    elif target:
        raise core.ValidationError('未知的打开目标')
    draft, media, receipts, issues = None, [], [], []
    if draft_id:
        manifest = operations.package_manifest(draft_id)
        full_draft = manifest['draft']
        target = next((a for a in manifest['accounts'] if a['account_id'] == account_id), None)
        if target is None:
            raise core.ValidationError('这条内容没有选择该账号，请在编辑器核对目标账号')
        draft = {'id': draft_id, 'title': target['title'], 'body': target['body'],
                 'status': full_draft['status'], 'fingerprint': manifest['fingerprint']}
        media = [{'name': '素材登记缺失', 'path': '', 'size': 0,
                  'mime_type': 'application/octet-stream', **asset,
                  'available': bool(asset.get('readable') and asset.get('unchanged'))}
                 for asset in manifest['media']]
        receipts = [r for r in full_draft['receipts'] if r['account_id'] == account_id]
        issues.extend(manifest['issues'])
        binding = manifest.get('binding') or {}
        if not all(binding.get('checklist', {}).get(key) is True for key in ('content', 'media', 'account')):
            issues.append('请在发布中心保存当前版本的文案、素材和账号核对')
        if any(not r['voided'] for r in receipts):
            issues.append('这个账号已有本条内容的发布记录，请先核对原帖，避免重复发布')
        if not media:
            issues.append('本条内容没有关联媒体；可在官方页面手动准备纯文字内容')
    else:
        issues.append('当前为账号登录与管理；选定并核对内容后可带入本条素材')
    profile = _profiles(create_for=account_id)[account_id]
    return {'account': account, 'platform': platform, 'profile_id': profile['profile_id'],
            'draft': draft, 'media': media, 'receipts': receipts,
            'can_upload_current': bool(draft and media and not issues),
            'issues': list(dict.fromkeys(issues)), 'mode': 'official_web',
            'session_label': '登录状态只存在这台电脑上；平台让它过期后要重新登录',
            'publishing_is_user_operated': True, 'automatic_platform_confirmation': False}


UPLOAD_STATES = {'prepared', 'checking_login', 'selecting_media', 'uploading',
                 'awaiting_review', 'needs_login', 'needs_attention', 'failed',
                 'cancelled', 'interrupted'}
ACTIVE_UPLOAD_STATES = {'prepared', 'checking_login', 'selecting_media', 'uploading'}
FINISHED_UPLOAD_STATES = {'cancelled', 'failed', 'interrupted', 'recorded'}


def _upload_table(connection):
    connection.execute('''CREATE TABLE IF NOT EXISTS native_upload_jobs (
        id TEXT PRIMARY KEY, account_id TEXT NOT NULL, draft_id TEXT NOT NULL,
        payload TEXT NOT NULL)''')


def _with_receipts(connection, jobs):
    """An explicit human receipt closes local work, without claiming API verification.

    This is a projection: voiding the receipt restores the original pending job.
    """
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ops_receipts'").fetchone():
        return jobs
    receipts = { (r['draft_id'], r['account_id'], r['fingerprint']): r
        for row in connection.execute('SELECT payload FROM ops_receipts WHERE voided=0')
        for r in [json.loads(row['payload'])] }
    result = []
    for job in jobs:
        receipt = receipts.get((job['draft_id'], job['account_id'], job['fingerprint']))
        if receipt:
            job = {**job, 'upload_state': job['state'], 'state': 'recorded',
                   'receipt_id': receipt['id'], 'receipt_source': 'manual',
                   'message': '已人工登记发布结果', 'published': False}
        result.append(job)
    return result


def _upload_jobs():
    with core.connection() as connection:
        _upload_table(connection)
        return _with_receipts(connection, [json.loads(row['payload']) for row in connection.execute(
            'SELECT payload FROM native_upload_jobs ORDER BY rowid DESC LIMIT 100')])


def _job(identifier):
    if not isinstance(identifier, str) or not identifier or len(identifier) > 100:
        raise core.ValidationError('上传任务ID无效')
    with core.connection() as connection:
        _upload_table(connection)
        row = connection.execute('SELECT payload FROM native_upload_jobs WHERE id=?', (identifier,)).fetchone()
        if row is None:
            raise core.ValidationError('上传任务不存在')
        return _with_receipts(connection, [json.loads(row['payload'])])[0]


def prepare_upload(arguments):
    context = workspace(arguments.get('account_id'), arguments.get('draft_id'))
    if context['account']['platform'] != 'xiaohongshu':
        raise core.ValidationError('后台上传当前只接rednote；其他账号可在软件内官方页面操作')
    if not context['can_upload_current']:
        raise core.ValidationError('暂不能后台上传：' + '；'.join(context['issues']))
    kinds = {asset['mime_type'].split('/')[0] for asset in context['media']}
    if kinds not in ({'image'}, {'video'}) or (kinds == {'video'} and len(context['media']) != 1):
        raise core.ValidationError('rednote每条请选择一组图片或一个视频')
    if kinds == {'image'} and any(asset['mime_type'] not in ('image/jpeg', 'image/png') for asset in context['media']):
        raise core.ValidationError('rednote内置上传请使用JPG或PNG图片')
    for previous in _upload_jobs():
        if previous['account_id'] == context['account']['id'] and previous['state'] not in FINISHED_UPLOAD_STATES:
            if (previous['state'] == 'needs_login' and previous['draft_id'] == context['draft']['id']
                    and previous['fingerprint'] == context['draft']['fingerprint']):
                return {'job': previous, 'workspace': context}
            raise core.ValidationError('该账号已有上传任务，请先打开核对或停止旧任务，避免重复上传')
    job = {'id': uuid.uuid4().hex, 'account_id': context['account']['id'],
           'draft_id': context['draft']['id'], 'fingerprint': context['draft']['fingerprint'],
           'target': 'image' if kinds == {'image'} else 'video', 'state': 'prepared',
           'message': '等待开始上传', 'created_at': core.now(), 'updated_at': core.now(),
           'source': 'native_official_web', 'published': False}
    with core.connection() as connection:
        _upload_table(connection)
        # Serialize the check and insert so double-clicks cannot start two jobs.
        connection.execute('BEGIN IMMEDIATE')
        active = _with_receipts(connection, [json.loads(row['payload']) for row in connection.execute(
            'SELECT payload FROM native_upload_jobs WHERE account_id=?', (job['account_id'],))])
        if any(j['state'] not in FINISHED_UPLOAD_STATES for j in active):
            raise core.ValidationError('该账号已有上传任务，请先核对旧任务')
        connection.execute('INSERT INTO native_upload_jobs VALUES(?,?,?,?)',
                           (job['id'], job['account_id'], job['draft_id'], json.dumps(job, ensure_ascii=False)))
        core.audit(connection, 'prepare_native_upload', {'id': job['id'], 'draft_id': job['draft_id']})
    return {'job': job, 'workspace': context}


def upload_context(identifier):
    job = _job(identifier)
    return {'job': job, 'workspace': workspace(job['account_id'], job['draft_id'])}


def update_upload(arguments):
    identifier, state = arguments.get('id'), arguments.get('state')
    if state not in UPLOAD_STATES:
        raise core.ValidationError('不支持这个上传状态；上传任务不能自动标记公开发布')
    message = arguments.get('message', '')
    if not isinstance(message, str):
        raise core.ValidationError('上传进度说明无效')
    message = message[:1000]   # a long diagnostic is kept, cut, rather than lost
    with core.connection() as connection:
        _upload_table(connection)
        connection.execute('BEGIN IMMEDIATE')
        row = connection.execute('SELECT payload FROM native_upload_jobs WHERE id=?', (identifier,)).fetchone()
        if row is None:
            raise core.ValidationError('上传任务不存在')
        job = json.loads(row['payload'])
        if job['state'] == 'cancelled' and state != 'cancelled':
            raise core.ValidationError('该任务已停止，不再继续上传')
        job.update(state=state, message=message, updated_at=core.now())
        connection.execute('UPDATE native_upload_jobs SET payload=? WHERE id=?',
                           (json.dumps(job, ensure_ascii=False), identifier))
        core.audit(connection, 'native_upload_state', {'id': identifier, 'state': state})
    return {'job': job}


def dispatch(action, arguments):
    if not isinstance(arguments, dict):
        raise core.ValidationError('上传操作参数必须是对象')
    queue_actions = {'enqueue_work': 'enqueue_work', 'queue_claim': 'claim',
                     'queue_event': 'event', 'queue_cancel': 'cancel', 'queue_retry': 'retry', 'queue_void': 'void', 'queue_confirm': 'confirm', 'queue_hide': 'hide',
                     'account_defaults': 'save_defaults'}
    if action in queue_actions:
        if __package__:
            from . import work_publishing
        else:
            import work_publishing
        return work_publishing.dispatch(queue_actions[action], arguments)
    if action == 'prepare_upload':
        return prepare_upload(arguments)
    if action == 'update_upload':
        return update_upload(arguments)
    if action == 'cancel_upload':
        return update_upload({'id': arguments.get('id'), 'state': 'cancelled',
                              'message': '已停止本机任务；已交给平台的媒体不会因此删除，请先核对平台草稿'})
    raise core.ValidationError('没有这个上传操作')
