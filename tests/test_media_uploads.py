"""Isolated local queue/streaming tests. Never calls a real provider or real DB."""
from __future__ import annotations

import email.parser
import email.policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import core, media_uploads as uploads


class LocalProvider:
    def __init__(self, *, status=200, response=None, slow=False):
        self.status = status
        self.response = response if response is not None else {'id': 'provider-file-1', 'path': 'https://cdn.example.test/video.mp4'}
        self.slow = slow
        self.headers = None
        self.body = bytearray()
        self.received = 0
        self.started = threading.Event()
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                owner.headers = self.headers
                owner.started.set()
                remaining = int(self.headers['Content-Length'])
                while remaining:
                    block = self.rfile.read(min(65536, remaining))
                    if not block:
                        return
                    owner.received += len(block)
                    if not owner.slow:
                        owner.body.extend(block)
                    remaining -= len(block)
                    if owner.slow:
                        time.sleep(.02)
                result = json.dumps(owner.response).encode()
                try:
                    self.send_response(owner.status)
                    self.send_header('Content-Length', str(len(result)))
                    self.end_headers()
                    self.wfile.write(result)
                except (BrokenPipeError, ConnectionResetError):
                    pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.endpoint = f'http://127.0.0.1:{self.server.server_port}/public/v1/upload'
    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)


class UploadTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='media-uploads-test-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        replacement = patch.object(core, 'DB', self.root/'media.sqlite3')
        replacement.start()
        self.addCleanup(replacement.stop)
    def make_file(self, name='sample.mp4', content=b'video-data'):
        p = self.root/name
        p.write_bytes(content)
        return p
    def register(self, path=None):
        return uploads.register_files([str(path or self.make_file())])['jobs'][0]
    def job(self, identifier):
        return next(j for j in uploads.snapshot()['jobs'] if j['id'] == identifier)
    def provider(self, **kwargs):
        server = LocalProvider(**kwargs)
        self.addCleanup(server.close)
        return server
    def queue(self, path=None):
        job = self.register(path)
        uploads.configure('test-private-api-key')
        uploads.job_action(job['id'], 'start')
        return job

    def test_database_connection_closes_after_context(self):
        with uploads._connect() as connection:
            self.assertEqual(connection.execute('SELECT 1').fetchone()[0], 1)
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute('SELECT 1')

    def test_register_references_original_without_copy_or_outbound_request(self):
        source = self.make_file()
        with patch.object(uploads.http.client, 'HTTPSConnection', side_effect=AssertionError('unexpected network')):
            result = self.register(source)
            state = uploads.snapshot()
        self.assertEqual(result['path'], str(source))
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['size'], source.stat().st_size)
        self.assertFalse((self.root/'uploads').exists())
        self.assertFalse(state['provider']['configured'])
        self.assertFalse(state['remote_publishing_enabled'])

    def test_register_validation_is_atomic(self):
        good = self.make_file()
        with self.assertRaises(core.ValidationError):
            uploads.register_files([str(good), str(self.root/'missing.mp4')])
        self.assertEqual(uploads.snapshot()['jobs'], [])
        link = self.root/'link.mp4'
        link.symlink_to(good)
        for invalid in ['relative.mp4', str(link), str(self.root), str(self.make_file('bad.exe'))]:
            with self.subTest(path=invalid), self.assertRaises(core.ValidationError):
                uploads.register_files([invalid])

    def test_same_path_and_fingerprint_reuses_job_without_status_change(self):
        path = self.make_file()
        first = self.register(path)
        uploads.job_action(first['id'], 'start')
        again = self.register(path)
        self.assertEqual(again['id'], first['id'])
        self.assertEqual(again['status'], 'waiting_credentials')
        self.assertEqual(len(uploads.snapshot()['jobs']), 1)
        path.write_bytes(b'changed-content')
        changed = self.register(path)
        self.assertNotEqual(changed['id'], first['id'])
        self.assertEqual(changed['status'], 'ready')

    def test_credentials_private_and_no_secret_in_api(self):
        result = uploads.configure('test-private-api-key')
        self.assertTrue(result['provider']['configured'])
        self.assertEqual(stat.S_IMODE((self.root/'provider.json').stat().st_mode), 0o600)
        self.assertNotIn('test-private-api-key', json.dumps(uploads.snapshot()))
        self.assertEqual(result['provider']['endpoint'], uploads.ENDPOINT)
        uploads.configure('')
        self.assertFalse((self.root/'provider.json').exists())
        self.assertFalse(uploads.snapshot()['provider']['configured'])
        with self.assertRaises(core.ValidationError):
            uploads.configure('bad\r\nAuthorization: injected')

    def test_clearing_credentials_requests_cross_process_cancellation(self):
        job = self.queue()
        uploads._update(core.DB, job['id'], status='uploading')
        uploads.configure('')
        with uploads._connect() as connection:
            row = connection.execute('SELECT status,cancel_requested FROM media_upload_jobs WHERE id=?', (job['id'],)).fetchone()
        self.assertEqual(row['status'], 'cancelling')
        self.assertEqual(row['cancel_requested'], 1)
        self.assertFalse(uploads.snapshot()['provider']['configured'])

    def test_no_credentials_waits_and_configure_does_not_start(self):
        job = self.register()
        result = uploads.job_action(job['id'], 'start')['job']
        self.assertEqual(result['status'], 'waiting_credentials')
        self.assertEqual(result['attempt_count'], 0)
        uploads.configure('test-private-api-key')
        self.assertFalse(uploads._process_one())
        self.assertEqual(self.job(job['id'])['status'], 'waiting_credentials')

    def test_provider_format_and_size_are_separate_from_local_limits(self):
        mov = self.register(self.make_file('local.mov'))
        self.assertFalse(mov['provider_supported'])
        self.assertEqual(uploads.job_action(mov['id'], 'start')['job']['error_code'], 'unsupported_provider_format')
        image = self.make_file('large.png')
        with image.open('wb') as f:
            f.truncate(uploads.MAX_IMAGE_BYTES + 1)
        large = self.register(image)
        self.assertEqual(uploads.job_action(large['id'], 'start')['job']['error_code'], 'provider_size_limit')
        self.assertEqual(self.job(large['id'])['status'], 'ready')

    def test_changed_file_is_rejected_before_network(self):
        path = self.make_file()
        job = self.queue(path)
        path.write_bytes(b'changed-content')
        with patch.object(uploads.http.client, 'HTTPSConnection', side_effect=AssertionError('unexpected network')):
            self.assertTrue(uploads._process_one())
        result = self.job(job['id'])
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['error_code'], 'file_changed')
        self.assertEqual(result['progress_bytes'], 0)

    def test_real_multipart_streaming_exact_payload_and_progress(self):
        payload = bytes(range(256)) * 4097
        job = self.queue(self.make_file('中文视频.mp4', payload))
        server = self.provider()
        real_read = uploads.os.read
        reads = []
        def read(fd, count):
            reads.append(count)
            return real_read(fd, count)
        with patch.object(uploads.os, 'read', side_effect=read):
            self.assertTrue(uploads._process_one(endpoint=server.endpoint))
        parsed = email.parser.BytesParser(policy=email.policy.default).parsebytes(
            ('Content-Type: '+server.headers['Content-Type']+'\r\nMIME-Version: 1.0\r\n\r\n').encode()+bytes(server.body))
        parts = list(parsed.iter_parts())
        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0].get_param('name', header='Content-Disposition'), 'file')
        self.assertEqual(parts[0].get_payload(decode=True), payload)
        self.assertEqual(server.headers['Authorization'], 'test-private-api-key')
        self.assertLessEqual(max(reads), uploads.CHUNK_BYTES)
        result = self.job(job['id'])
        self.assertEqual(result['status'], 'uploaded_to_provider')
        self.assertEqual(result['progress_bytes'], len(payload))
        self.assertEqual(result['progress'], 100)
        self.assertEqual(result['provider_id'], 'provider-file-1')

    def test_invalid_response_and_remote_errors_never_leak_raw_body(self):
        for kwargs, expected in [
            ({'response': {'id': 'x'}}, 'invalid_provider_response'),
            ({'response': {'id': 'x', 'path': 'javascript:bad'}}, 'invalid_provider_response'),
            ({'response': {'id': 'test-private-api-key', 'path': 'https://cdn.example.test/f'}}, 'invalid_provider_response'),
            ({'status': 401, 'response': {'message': 'test-private-api-key'}}, 'provider_rejected'),
        ]:
            with self.subTest(kwargs=kwargs):
                job = self.queue(self.make_file(f'file-{len(uploads.snapshot()["jobs"])}.mp4'))
                server = self.provider(**kwargs)
                uploads._process_one(endpoint=server.endpoint)
                result = self.job(job['id'])
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(result['error_code'], expected)
                self.assertNotIn('test-private-api-key', json.dumps(result))
                self.assertFalse(uploads._process_one(endpoint=server.endpoint))

    def test_network_failure_does_not_automatically_retry(self):
        job = self.queue()
        with patch.object(uploads.http.client, 'HTTPSConnection', side_effect=OSError('test-private-api-key')):
            uploads._process_one()
        result = self.job(job['id'])
        self.assertEqual(result['error_code'], 'network_error')
        self.assertEqual(result['attempt_count'], 1)
        self.assertFalse(uploads._process_one())
        self.assertEqual(uploads.job_action(job['id'], 'retry')['job']['status'], 'queued')

    def test_restart_turns_active_into_interrupted_and_requires_manual_retry(self):
        job = self.queue()
        uploads._update(core.DB, job['id'], status='uploading', progress_bytes=4)
        uploads._recover_interrupted()
        result = self.job(job['id'])
        self.assertEqual(result['status'], 'interrupted')
        self.assertEqual(result['progress_bytes'], 4)
        self.assertFalse(uploads._process_one())
        retried = uploads.job_action(job['id'], 'retry')['job']
        self.assertEqual(retried['status'], 'queued')
        self.assertEqual(retried['progress_bytes'], 0)

    def test_cancel_queued_does_not_send(self):
        job = self.queue()
        result = uploads.job_action(job['id'], 'cancel')['job']
        self.assertEqual(result['status'], 'cancelled')
        self.assertFalse(uploads._process_one())

    def test_cancel_between_flag_check_and_send_never_reconnects(self):
        job = self.queue(self.make_file(content=b'x' * (uploads.CHUNK_BYTES * 2)))
        server = self.provider()
        base = uploads.http.client.HTTPConnection
        calls = []
        class RaceConnection(base):
            cancelled = False
            def connect(connection):
                calls.append('connect')
                return super().connect()
            def send(connection, data):
                if isinstance(data, bytes) and data.startswith(b'--MediaDesk') and not connection.cancelled:
                    connection.cancelled = True
                    uploads._cancel_active(uploads._active)
                return super().send(data)
        with patch.object(uploads.http.client, 'HTTPConnection', RaceConnection):
            uploads._process_one(endpoint=server.endpoint)
        self.assertEqual(calls, ['connect'], 'a cancelled connection must never auto-reopen')
        self.assertEqual(self.job(job['id'])['status'], 'cancelled')

    def test_payload_timeout_checks_cancel_and_keeps_exact_partial_count(self):
        job = self.register()
        active = {'db_path':core.DB,'id':job['id'],'cancel':threading.Event(),'sent':0,
                  'last_progress':time.monotonic(),'last_write':time.monotonic()}
        class FakeSocket:
            calls = 0
            def send(sock, data):
                sock.calls += 1
                if sock.calls == 1:
                    return 3
                active['cancel'].set()
                raise uploads.socket.timeout()
        connection = type('Connection', (), {'sock':FakeSocket()})()
        with self.assertRaisesRegex(uploads._TransferError, 'cancelled'):
            uploads._send_payload(connection, b'abcdefgh', active)
        self.assertEqual(active['sent'], 3)
        self.assertEqual(connection.sock.calls, 2)
        # A real stall without cancellation must remain a failure, not cancelled.
        active['cancel'].clear()
        active['last_progress'] = time.monotonic() - 31
        class StalledSocket:
            def send(sock, data):
                raise uploads.socket.timeout()
        connection.sock = StalledSocket()
        with self.assertRaisesRegex(uploads._TransferError, 'network_error'):
            uploads._send_payload(connection, b'abcdefgh', active)

    def test_cross_process_cancel_closes_active_stream(self):
        path = self.make_file()
        with path.open('wb') as f:
            f.truncate(32 * 1024 * 1024)
        job = self.queue(path)
        server = self.provider(slow=True)
        thread = threading.Thread(target=uploads._process_one, kwargs={'endpoint':server.endpoint})
        thread.start()
        self.assertTrue(server.started.wait(3))
        # A different process has no access to _active; only the DB flag changes.
        uploads._update(core.DB, job['id'], status='cancelling', cancel_requested=1)
        thread.join(4)
        self.assertFalse(thread.is_alive(), 'cancel must stop a blocked socket upload')
        result = self.job(job['id'])
        self.assertEqual(result['status'], 'cancelled')
        self.assertLess(result['progress_bytes'], result['size'])
        self.assertLess(server.received, result['size'])
        self.assertTrue(path.exists())

    def test_chunk_idempotency_finish_and_no_outbound(self):
        session = uploads.init_local_upload('素材.mov', 9)
        identifier = session['upload_id']
        first = uploads.append_chunk(identifier, 0, b'abcd')
        self.assertEqual(first['received'], 4)
        self.assertEqual(uploads.append_chunk(identifier, 0, b'abcd')['received'], 4)
        for offset, content in [(0,b'xxxx'),(2,b'cdef'),(7,b'x'),(4,b'012345')]:
            with self.subTest(offset=offset), self.assertRaises(core.ValidationError):
                uploads.append_chunk(identifier, offset, content)
        with self.assertRaises(core.ValidationError):
            uploads.finish_local_upload(identifier)
        uploads.append_chunk(identifier, 4, b'efghi')
        result = uploads.finish_local_upload(identifier)['job']
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['name'], '素材.mov')
        self.assertEqual(Path(result['path']).read_bytes(), b'abcdefghi')
        self.assertEqual(uploads.finish_local_upload(identifier)['job']['id'], result['id'])
        self.assertEqual(len(uploads.snapshot()['jobs']), 1)

    def test_incomplete_local_uploads_visible_until_discarded(self):
        session = uploads.init_local_upload('unfinished.mp4', 8)
        uploads.append_chunk(session['upload_id'], 0, b'abcd')
        visible = uploads.snapshot()['local_uploads']
        self.assertEqual(len(visible), 1)
        self.assertEqual(visible[0]['upload_id'], session['upload_id'])
        self.assertEqual(visible[0]['received'], 4)
        self.assertEqual(visible[0]['size'], 8)
        self.assertEqual(set(visible[0]), {'upload_id','name','size','received','created_at'})
        uploads.discard_local_upload(session['upload_id'])
        self.assertEqual(uploads.snapshot()['local_uploads'], [])
        self.assertEqual(uploads.snapshot()['jobs'], [])

    def test_chunks_reject_path_traversal_oversized_and_empty_requests(self):
        for name in ('../x.mp4','/tmp/x.mp4','x\\y.mp4','x\n.mp4'):
            with self.subTest(name=name), self.assertRaises(core.ValidationError):
                uploads.init_local_upload(name, 1)
        for size in (0,-1,uploads.MAX_LOCAL_BYTES+1,True):
            with self.subTest(size=size), self.assertRaises(core.ValidationError):
                uploads.init_local_upload('x.mp4',size)
        session = uploads.init_local_upload('x.mp4',uploads.MAX_CHUNK_BYTES+1)
        for data in (b'',b'x'*(uploads.MAX_CHUNK_BYTES+1)):
            with self.assertRaises(core.ValidationError):
                uploads.append_chunk(session['upload_id'],0,data)
        with self.assertRaises(core.ValidationError):
            uploads.discard_local_upload('../../x')

    def test_finish_checks_actual_file_length_and_discard_cleans_staging(self):
        session = uploads.init_local_upload('x.mp4',4)
        identifier = session['upload_id']
        uploads.append_chunk(identifier,0,b'abcd')
        uploads._staging_path(identifier).write_bytes(b'x')
        with self.assertRaises(core.ValidationError):
            uploads.finish_local_upload(identifier)
        self.assertTrue(uploads.discard_local_upload(identifier)['discarded'])
        self.assertFalse(uploads._staging_path(identifier).exists())
        self.assertTrue(uploads.discard_local_upload(identifier)['discarded'])
        self.assertEqual(uploads.snapshot()['jobs'],[])

    def test_staging_limits_disk_and_session_count(self):
        with patch.object(uploads.shutil,'disk_usage',return_value=type('Usage',(),{'free':1})()):
            with self.assertRaises(core.ValidationError):
                uploads.init_local_upload('x.mp4',4)
        for i in range(8):
            uploads.init_local_upload(f'{i}.mp4',4)
        with self.assertRaises(core.ValidationError):
            uploads.init_local_upload('overflow.mp4',4)


if __name__ == '__main__':
    unittest.main()
