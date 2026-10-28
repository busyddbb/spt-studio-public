"""Local media queue and opt-in, bounded-memory Postiz uploads.

Registering or receiving a file never contacts a provider. Only start/retry can
queue an outbound transfer. Provider credentials are kept outside the API data.
"""
from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import stat
import threading
import time
import uuid
from urllib.parse import urlsplit
from contextlib import contextmanager

if __package__:
    from . import core
else:
    import core

ENDPOINT = 'https://api.postiz.com/public/v1/upload'
CHUNK_BYTES = 256 * 1024
MAX_CHUNK_BYTES = 4 * 1024 * 1024
MAX_LOCAL_BYTES = 10 * 1024 ** 3
MAX_IMAGE_BYTES = 10 * 1024 ** 2
MAX_VIDEO_BYTES = 1024 ** 3
DISK_RESERVE_BYTES = 256 * 1024 ** 2
TYPES = {'.mp4': 'video/mp4', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
         '.png': 'image/png', '.gif': 'image/gif', '.webp': 'image/webp',
         '.avif': 'image/avif', '.bmp': 'image/bmp', '.tif': 'image/tiff',
         '.tiff': 'image/tiff', '.mov': 'video/quicktime'}
ERROR_MESSAGES = {
    'credentials_required': '已保存在本地；连接 Postiz 后可手动开始上传。',
    'unsupported_provider_format': 'MOV 已保存在本地；Postiz 上传需要先转为 MP4。',
    'provider_size_limit': '超过 Postiz 限制：图片最多 10 MiB，MP4 最多 1 GiB；本地文件仍保留。',
    'file_changed': '文件已变更，请重新添加当前文件。',
    'file_missing': '原文件无法读取，请恢复原文件或重新添加。',
    'network_error': '网络连接中断；未自动重试，可手动重试完整文件。',
    'provider_rejected': '服务拒绝了上传，请检查授权、格式或账户状态后手动重试。',
    'invalid_provider_response': '服务响应未包含有效文件结果，未确认上传成功。',
    'interrupted': '上次传输被中断；不支持断点续传，可手动从头重试。',
    'cancelled': '已取消本机传输；原文件仍保留。若传输已开始，服务端可能已收到数据，取消不会删除服务端文件。',
}
_worker_lock = threading.RLock()
_local_lock = threading.RLock()
_wake = threading.Event()
_worker = None
_active = None


def _db_path():
    return Path(core.DB).resolve()


@contextmanager
def _connect(db_path=None):
    path = Path(db_path or _db_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL')
    c.executescript('''
      CREATE TABLE IF NOT EXISTS media_upload_jobs (
        id TEXT PRIMARY KEY, path TEXT NOT NULL, name TEXT NOT NULL,
        size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, device INTEGER NOT NULL,
        inode INTEGER NOT NULL, mime_type TEXT NOT NULL, status TEXT NOT NULL,
        progress_bytes INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL, provider_id TEXT, provider_path TEXT,
        error_code TEXT, attempt_count INTEGER NOT NULL DEFAULT 0,
        cancel_requested INTEGER NOT NULL DEFAULT 0);
      CREATE INDEX IF NOT EXISTS media_upload_status ON media_upload_jobs(status, created_at);
      CREATE TABLE IF NOT EXISTS media_local_uploads (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, size INTEGER NOT NULL,
        received INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL,
        created_at TEXT NOT NULL, job_id TEXT);
    ''')
    try:
        with c:
            yield c
    finally:
        c.close()


def _provider(db_path=None):
    return {'name': 'Postiz', 'configured': bool(_read_key(db_path)), 'endpoint': ENDPOINT,
            'supported_types': sorted(set(TYPES.values()) - {'video/quicktime'}),
            'max_image_bytes': MAX_IMAGE_BYTES, 'max_video_bytes': MAX_VIDEO_BYTES,
            'local_max_bytes': MAX_LOCAL_BYTES, 'resume_supported': False}


def _read_key(db_path=None):
    path = Path(db_path or _db_path()).parent / 'provider.json'
    try:
        if path.is_symlink() or path.stat().st_size > 16_384:
            return ''
        data = json.loads(path.read_text(encoding='utf-8'))
        value = data.get('api_key', '') if isinstance(data, dict) else ''
        return value if isinstance(value, str) and value and '\r' not in value and '\n' not in value else ''
    except (OSError, ValueError):
        return ''


def configure(api_key):
    if not isinstance(api_key, str) or len(api_key) > 8192 or '\r' in api_key or '\n' in api_key:
        raise core.ValidationError('API key 格式无效')
    key = api_key.strip()
    try:
        key.encode('latin-1')
    except UnicodeEncodeError:
        raise core.ValidationError('API key 格式无效') from None
    path = _db_path().parent / 'provider.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    if key:
        temp = path.with_name('.provider-' + uuid.uuid4().hex + '.tmp')
        try:
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump({'api_key': key}, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, path)
            os.chmod(path, 0o600)
        finally:
            temp.unlink(missing_ok=True)
    else:
        path.unlink(missing_ok=True)
        with _connect() as c:
            c.execute("UPDATE media_upload_jobs SET status='waiting_credentials',error_code='credentials_required',updated_at=? WHERE status='queued'", (core.now(),))
            c.execute("UPDATE media_upload_jobs SET status='cancelling',cancel_requested=1,error_code='cancelled',updated_at=? WHERE status IN ('uploading','cancelling')", (core.now(),))
        with _worker_lock:
            active = _active
            if active and active['db_path'] == _db_path():
                _cancel_active(active)
    return {'provider': _provider()}


def _public(row):
    d = dict(row)
    result = {k: d[k] for k in ('id', 'path', 'name', 'size', 'mime_type', 'status',
              'progress_bytes', 'created_at', 'updated_at', 'provider_id', 'provider_path',
              'error_code', 'attempt_count')}
    result['progress'] = round(100 * d['progress_bytes'] / d['size'], 2) if d['size'] else 0
    result['provider_supported'] = d['mime_type'] != 'video/quicktime'
    result['status_message'] = ERROR_MESSAGES.get(d['error_code'], '')
    return result


def snapshot():
    with _connect() as c:
        jobs = [_public(r) for r in c.execute('SELECT * FROM media_upload_jobs ORDER BY created_at DESC,rowid DESC')]
        local_uploads = [dict(r) for r in c.execute(
            "SELECT id AS upload_id,name,size,received,created_at FROM media_local_uploads WHERE status='receiving' ORDER BY created_at,rowid")]
    return {'jobs': jobs, 'local_uploads': local_uploads, 'provider': _provider(), 'remote_publishing_enabled': False}


def _check_name(name):
    if not isinstance(name, str) or not name or len(name) > 200 or name in ('.', '..') or any(ch in name for ch in '/\\') or any(ord(ch) < 32 for ch in name):
        raise core.ValidationError('文件名无效；只填写文件名，不要包含路径')
    if Path(name).suffix.lower() not in TYPES:
        raise core.ValidationError('支持 MP4、MOV 和 JPEG、PNG、GIF、WebP、AVIF、BMP、TIFF 图片')
    return name


def _file_info(path):
    if not isinstance(path, str) or not Path(path).is_absolute():
        raise core.ValidationError('请选择本机文件的绝对路径')
    p = Path(path)
    _check_name(p.name)
    try:
        info = p.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise core.ValidationError('只能添加普通文件，不能添加文件夹或符号链接')
        if not 0 < info.st_size <= MAX_LOCAL_BYTES:
            raise core.ValidationError('本地文件需大于 0 字节且不超过 10 GiB')
        return p, info
    except OSError:
        raise core.ValidationError('文件不存在或无法读取') from None


def _insert_job(c, path, info, name=None):
    existing = c.execute('''SELECT * FROM media_upload_jobs
        WHERE path=? AND size=? AND mtime_ns=? AND device=? AND inode=?
        ORDER BY rowid DESC LIMIT 1''',
        (str(path),info.st_size,info.st_mtime_ns,info.st_dev,info.st_ino)).fetchone()
    if existing:
        return _public(existing)
    name = name or path.name
    identifier = uuid.uuid4().hex
    stamp = core.now()
    c.execute('''INSERT INTO media_upload_jobs
      (id,path,name,size,mtime_ns,device,inode,mime_type,status,created_at,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
      (identifier,str(path),name,info.st_size,info.st_mtime_ns,info.st_dev,info.st_ino,
       TYPES[Path(name).suffix.lower()],'ready',stamp,stamp))
    return _public(c.execute('SELECT * FROM media_upload_jobs WHERE id=?', (identifier,)).fetchone())


def register_files(paths):
    if not isinstance(paths, list) or not 1 <= len(paths) <= 100:
        raise core.ValidationError('每次请选择 1–100 个本地文件')
    files = [_file_info(path) for path in paths]
    with _connect() as c:
        jobs = [_insert_job(c, p, info) for p, info in files]
    return {'jobs': jobs}


def _cancel_active(active):
    active['cancel'].set()
    connection = active.get('connection')
    if connection:
        try:
            if connection.sock:
                connection.sock.shutdown(socket.SHUT_RDWR)
        except (OSError, AttributeError):
            pass
        try:
            connection.close()
        except OSError:
            pass
    _wake.set()


def job_action(identifier, action):
    if action not in ('start', 'cancel', 'retry'):
        raise core.ValidationError('不支持的队列操作')
    db_path = _db_path()
    with _connect(db_path) as c:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute('SELECT * FROM media_upload_jobs WHERE id=?', (identifier,)).fetchone()
        if row is None:
            raise core.ValidationError('队列文件不存在')
        status = row['status']
        if action == 'cancel':
            if status == 'uploaded_to_provider':
                raise core.ValidationError('此文件已上传，取消不能撤回服务端文件')
            new = 'cancelling' if status in ('uploading', 'cancelling') else 'cancelled'
            c.execute('UPDATE media_upload_jobs SET status=?,cancel_requested=1,error_code=?,updated_at=? WHERE id=?',
                      (new,'cancelled',core.now(),identifier))
        else:
            if status in ('uploading', 'cancelling', 'queued', 'uploaded_to_provider'):
                raise core.ValidationError('当前状态不能再次开始上传')
            if action == 'start' and status not in ('ready', 'waiting_credentials'):
                raise core.ValidationError('请使用重试重新开始此文件')
            if row['mime_type'] == 'video/quicktime':
                new, error = 'ready', 'unsupported_provider_format'
            elif row['size'] > (MAX_VIDEO_BYTES if row['mime_type'] == 'video/mp4' else MAX_IMAGE_BYTES):
                new, error = 'ready', 'provider_size_limit'
            elif not _read_key(db_path):
                new, error = 'waiting_credentials', 'credentials_required'
            else:
                new, error = 'queued', None
            c.execute('UPDATE media_upload_jobs SET status=?,error_code=?,cancel_requested=0,progress_bytes=0,updated_at=? WHERE id=?',
                      (new,error,core.now(),identifier))
        result = _public(c.execute('SELECT * FROM media_upload_jobs WHERE id=?', (identifier,)).fetchone())
    if action == 'cancel':
        with _worker_lock:
            if _active and _active['db_path'] == db_path and _active['id'] == identifier:
                _cancel_active(_active)
    _wake.set()
    return {'job': result}


class _TransferError(Exception):
    pass


def _update(db_path, identifier, **changes):
    changes['updated_at'] = core.now()
    with _connect(db_path) as c:
        c.execute('UPDATE media_upload_jobs SET ' + ','.join(k+'=?' for k in changes) + ' WHERE id=?', (*changes.values(), identifier))


def _fingerprint(info):
    return (info.st_size, info.st_mtime_ns, info.st_dev, info.st_ino)


def _send_payload(connection, chunk, active):
    # sendall loses the partial-byte count and, on some platforms, a close from
    # another thread does not wake it promptly. A bounded socket.send loop both
    # counts confirmed writes and gives cancellation a deterministic check point.
    sock = connection.sock
    if sock is None:
        raise _TransferError('cancelled' if active['cancel'].is_set() else 'network_error')
    view = memoryview(chunk)
    offset = 0
    while offset < len(view):
        if active['cancel'].is_set():
            raise _TransferError('cancelled')
        try:
            written = sock.send(view[offset:])
        except socket.timeout:
            if active['cancel'].is_set():
                raise _TransferError('cancelled') from None
            if time.monotonic() - active['last_progress'] >= 30:
                raise _TransferError('network_error') from None
            continue
        if not written:
            raise _TransferError('network_error')
        offset += written
        active['sent'] += written
        current = time.monotonic()
        active['last_progress'] = current
        if current - active['last_write'] >= .25:
            _update(active['db_path'],active['id'],progress_bytes=active['sent'])
            active['last_write'] = current


def _transfer(row, key, active, endpoint=ENDPOINT):
    # endpoint is internal test injection only; public APIs never accept a URL.
    db_path, identifier = active['db_path'], row['id']
    path = Path(row['path'])
    expected = tuple(row[k] for k in ('size', 'mtime_ns', 'device', 'inode'))
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0))
    except OSError:
        raise _TransferError('file_missing') from None
    conn = None
    try:
        initial = os.fstat(fd)
        if not stat.S_ISREG(initial.st_mode) or _fingerprint(initial) != expected:
            raise _TransferError('file_changed')
        if active['cancel'].is_set():
            raise _TransferError('cancelled')
        u = urlsplit(endpoint)
        conn_type = http.client.HTTPSConnection if u.scheme == 'https' else http.client.HTTPConnection
        conn = conn_type(u.hostname, u.port, timeout=5)
        # HTTPConnection.send otherwise reconnects automatically after close().
        # A cancellation between checking the flag and send must never reopen it.
        conn.auto_open = 0
        with _worker_lock:
            active['connection'] = conn
        conn.connect()
        if active['cancel'].is_set():
            raise _TransferError('cancelled')
        boundary = 'MediaDesk' + uuid.uuid4().hex
        escaped = row['name'].replace('"', '_')
        prefix = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{escaped}"\r\n'
                  f'Content-Type: {row["mime_type"]}\r\n\r\n').encode('utf-8')
        suffix = f'\r\n--{boundary}--\r\n'.encode('ascii')
        target = u.path + ('?' + u.query if u.query else '')
        conn.putrequest('POST', target)
        conn.putheader('Authorization', key)
        conn.putheader('Content-Type', 'multipart/form-data; boundary=' + boundary)
        conn.putheader('Content-Length', str(len(prefix) + row['size'] + len(suffix)))
        conn.endheaders()
        if active['cancel'].is_set():
            raise _TransferError('cancelled')
        conn.send(prefix)
        conn.sock.settimeout(2)
        active['last_progress'] = active['last_write'] = time.monotonic()
        while active['sent'] < row['size']:
            if active['cancel'].is_set():
                raise _TransferError('cancelled')
            chunk = os.read(fd, min(CHUNK_BYTES, row['size'] - active['sent']))
            if not chunk:
                raise _TransferError('file_changed')
            _send_payload(conn, chunk, active)
        _update(db_path, identifier, progress_bytes=active['sent'])
        try:
            if _fingerprint(os.fstat(fd)) != expected or _fingerprint(path.stat()) != expected or os.read(fd, 1):
                raise _TransferError('file_changed')
        except OSError:
            raise _TransferError('file_changed') from None
        if active['cancel'].is_set():
            raise _TransferError('cancelled')
        if conn.sock is None:
            raise _TransferError('cancelled' if active['cancel'].is_set() else 'network_error')
        conn.sock.settimeout(5)
        conn.send(suffix)
        response = conn.getresponse()
        body = response.read(65537)
        if active['cancel'].is_set():
            raise _TransferError('cancelled')
        if not 200 <= response.status < 300:
            raise _TransferError('provider_rejected')
        if len(body) > 65536:
            raise _TransferError('invalid_provider_response')
        try:
            result = json.loads(body)
            provider_id, provider_path = result['id'], result['path']
            if not isinstance(provider_id, (str, int)) or isinstance(provider_id, bool) or not str(provider_id).strip() or len(str(provider_id)) > 300:
                raise ValueError()
            if not isinstance(provider_path, str) or len(provider_path) > 4096 or any(ord(ch) < 32 for ch in provider_path):
                raise ValueError()
            parsed = urlsplit(provider_path)
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or key in provider_path or key in str(provider_id):
                raise ValueError()
        except (ValueError, TypeError, KeyError):
            raise _TransferError('invalid_provider_response') from None
        return str(provider_id), provider_path
    finally:
        os.close(fd)
        if conn:
            conn.close()


def _process_one(db_path=None, *, endpoint=ENDPOINT):
    """Claim and process one queued item. Internal endpoint override supports mocks."""
    global _active
    db_path = Path(db_path or _db_path())
    with _connect(db_path) as c:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute("SELECT * FROM media_upload_jobs WHERE status='queued' ORDER BY created_at,rowid LIMIT 1").fetchone()
        if row is None:
            return False
        key = _read_key(db_path)
        if not key:
            c.execute("UPDATE media_upload_jobs SET status='waiting_credentials',error_code='credentials_required',updated_at=? WHERE id=?", (core.now(),row['id']))
            return True
        c.execute("UPDATE media_upload_jobs SET status='uploading',attempt_count=attempt_count+1,error_code=NULL,progress_bytes=0,updated_at=? WHERE id=?", (core.now(),row['id']))
        row = dict(row)
    active = {'db_path': db_path, 'id': row['id'], 'cancel': threading.Event(), 'done': threading.Event(), 'connection': None, 'sent': 0}
    with _worker_lock:
        _active = active
    def watch_cancel():
        while not active['done'].wait(.25):
            try:
                with _connect(db_path) as c:
                    cancelled = c.execute('SELECT cancel_requested FROM media_upload_jobs WHERE id=?', (row['id'],)).fetchone()[0]
                if cancelled:
                    _cancel_active(active)
                    return
            except sqlite3.Error:
                continue
    monitor = threading.Thread(target=watch_cancel,name='media-upload-cancel-watch',daemon=True)
    monitor.start()
    try:
        with _connect(db_path) as c:
            if c.execute('SELECT cancel_requested FROM media_upload_jobs WHERE id=?', (row['id'],)).fetchone()[0]:
                active['cancel'].set()
        provider_id, provider_path = _transfer(row, key, active, endpoint)
        with _worker_lock:
            if active['cancel'].is_set():
                raise _TransferError('cancelled')
            with _connect(db_path) as c:
                c.execute('BEGIN IMMEDIATE')
                cancelled = c.execute('SELECT cancel_requested FROM media_upload_jobs WHERE id=?', (row['id'],)).fetchone()[0]
                if cancelled:
                    raise _TransferError('cancelled')
                c.execute("UPDATE media_upload_jobs SET status='uploaded_to_provider',provider_id=?,provider_path=?,progress_bytes=?,error_code=NULL,updated_at=? WHERE id=?",
                          (provider_id,provider_path,row['size'],core.now(),row['id']))
    except Exception as exc:
        code = 'cancelled' if active['cancel'].is_set() else (str(exc) if isinstance(exc, _TransferError) else 'network_error')
        if code not in ERROR_MESSAGES:
            code = 'network_error'
        _update(db_path,row['id'],status='cancelled' if code == 'cancelled' else 'failed',
                error_code=code,progress_bytes=active['sent'])
    finally:
        active['done'].set()
        monitor.join(timeout=1)
        with _worker_lock:
            if _active is active:
                _active = None
    return True


def _recover_interrupted(db_path=None):
    with _connect(db_path) as c:
        c.execute("UPDATE media_upload_jobs SET status='interrupted',error_code='interrupted',cancel_requested=0,updated_at=? WHERE status IN ('uploading','cancelling')", (core.now(),))


def start_worker():
    global _worker
    with _worker_lock:
        if _worker is not None and _worker.is_alive():
            return
        db_path = _db_path()
        _recover_interrupted(db_path)
        def run():
            while True:
                try:
                    if _process_one(db_path):
                        continue
                except Exception:
                    # Do not print remote errors or credentials. DB failure is retried.
                    pass
                _wake.wait(1)
                _wake.clear()
        _worker = threading.Thread(target=run,name='media-upload-worker',daemon=True)
        _worker.start()


def _session_id(identifier):
    if not isinstance(identifier, str) or len(identifier) != 32 or any(c not in '0123456789abcdef' for c in identifier):
        raise core.ValidationError('本地上传标识无效')
    return identifier


def _staging_path(identifier):
    return _db_path().parent / 'uploads' / 'staging' / (_session_id(identifier) + '.part')


def init_local_upload(name, size):
    _check_name(name)
    if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= MAX_LOCAL_BYTES:
        raise core.ValidationError('本地文件需大于 0 字节且不超过 10 GiB')
    with _local_lock, _connect() as c:
        c.execute('BEGIN IMMEDIATE')
        count, reserved = c.execute("SELECT COUNT(*),COALESCE(SUM(size-received),0) FROM media_local_uploads WHERE status='receiving'").fetchone()
        if count >= 8 or reserved + size > 20 * 1024 ** 3:
            raise core.ValidationError('待接收文件过多，请完成或取消已有上传')
        if shutil.disk_usage(_db_path().parent).free < reserved + size + DISK_RESERVE_BYTES:
            raise core.ValidationError('本机剩余磁盘空间不足，请先释放空间')
        identifier = uuid.uuid4().hex
        path = _staging_path(identifier)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), 0o600)
        os.close(fd)
        try:
            c.execute('INSERT INTO media_local_uploads(id,name,size,status,created_at) VALUES(?,?,?,?,?)',
                      (identifier,name,size,'receiving',core.now()))
        except Exception:
            path.unlink(missing_ok=True)
            raise
    return {'upload_id':identifier,'received':0,'size':size}


def append_chunk(upload_id, offset, data):
    _session_id(upload_id)
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise core.ValidationError('分块位置无效')
    if not isinstance(data, (bytes, bytearray, memoryview)) or not 0 < len(data) <= MAX_CHUNK_BYTES:
        raise core.ValidationError('每块需大于 0 字节且不超过 4 MiB')
    with _local_lock, _connect() as c:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute('SELECT * FROM media_local_uploads WHERE id=?', (upload_id,)).fetchone()
        if row is None or row['status'] != 'receiving':
            raise core.ValidationError('本地上传不存在或已结束')
        if offset > row['received'] or offset + len(data) > row['size']:
            raise core.ValidationError('分块位置或长度不匹配')
        path = _staging_path(upload_id)
        try:
            fd = os.open(path, os.O_RDWR | getattr(os,'O_NOFOLLOW',0) | getattr(os, 'O_BINARY', 0))
            with os.fdopen(fd,'r+b',buffering=0) as f:
                if not stat.S_ISREG(os.fstat(f.fileno()).st_mode) or os.fstat(f.fileno()).st_size < row['received']:
                    raise core.ValidationError('本地临时文件长度异常，请取消后重新添加')
                if offset < row['received']:
                    if offset + len(data) > row['received']:
                        raise core.ValidationError('分块位置不匹配')
                    f.seek(offset)
                    if f.read(len(data)) != data:
                        raise core.ValidationError('重传分块内容不一致')
                    return {'received':row['received'],'size':row['size']}
                if shutil.disk_usage(path.parent).free < len(data) + DISK_RESERVE_BYTES:
                    raise core.ValidationError('本机剩余磁盘空间不足')
                f.seek(offset)
                f.write(data)
                f.truncate(offset + len(data))
                os.fsync(f.fileno())
        except OSError:
            raise core.ValidationError('本地文件写入失败，请检查磁盘空间') from None
        received = offset + len(data)
        c.execute('UPDATE media_local_uploads SET received=? WHERE id=?', (received,upload_id))
    return {'received':received,'size':row['size']}


def finish_local_upload(upload_id):
    _session_id(upload_id)
    with _local_lock, _connect() as c:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute('SELECT * FROM media_local_uploads WHERE id=?',(upload_id,)).fetchone()
        if row is None or row['status'] == 'discarded':
            raise core.ValidationError('本地上传不存在或已取消')
        if row['status'] == 'finished':
            return {'job':_public(c.execute('SELECT * FROM media_upload_jobs WHERE id=?',(row['job_id'],)).fetchone())}
        if row['received'] != row['size']:
            raise core.ValidationError('文件尚未接收完整')
        stage = _staging_path(upload_id)
        target = _db_path().parent / 'uploads' / 'files' / (upload_id + Path(row['name']).suffix.lower())
        source = stage if stage.exists() else target
        try:
            info = source.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_size != row['size']:
                raise core.ValidationError('本地文件长度不匹配，请取消后重新添加')
            target.parent.mkdir(parents=True,exist_ok=True)
            if source == stage:
                os.replace(stage,target)
            info = target.stat()
        except OSError:
            raise core.ValidationError('本地文件无法完成保存') from None
        job = _insert_job(c,target,info,row['name'])
        c.execute("UPDATE media_local_uploads SET status='finished',job_id=? WHERE id=?",(job['id'],upload_id))
    return {'job':job}


def discard_local_upload(upload_id):
    _session_id(upload_id)
    with _local_lock, _connect() as c:
        row = c.execute('SELECT * FROM media_local_uploads WHERE id=?',(upload_id,)).fetchone()
        if row is None:
            raise core.ValidationError('本地上传不存在')
        if row['status'] == 'finished':
            raise core.ValidationError('文件已加入队列，不能按临时上传删除')
        _staging_path(upload_id).unlink(missing_ok=True)
        c.execute("UPDATE media_local_uploads SET status='discarded' WHERE id=?",(upload_id,))
    return {'discarded':True,'upload_id':upload_id}
