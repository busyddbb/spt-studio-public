"""Windows branches of the app server, run anywhere with the platform modules stood in."""
from __future__ import annotations
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app import core, local_access, planning


class FakeMsvcrt:
    LK_LOCK, LK_UNLCK = 1, 0

    def __init__(self, busy: int = 0) -> None:
        self.busy, self.calls = busy, []

    def locking(self, descriptor, mode, length):
        self.calls.append((mode, length))
        if mode == self.LK_LOCK and self.busy:
            self.busy -= 1
            raise OSError(36, 'Resource deadlock avoided')   # LK_LOCK gave up after ~10 s


class DraftLockTests(unittest.TestCase):
    def test_windows_locks_byte_zero_and_keeps_waiting_like_flock(self):
        fake = FakeMsvcrt(busy=2)
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(planning, 'fcntl', None), patch.object(planning, 'msvcrt', fake), \
                patch.object(core, 'DB', Path(folder) / 'media.sqlite3'):
            with planning._draft_creation_lock():
                self.assertEqual(fake.calls, [(1, 1)] * 3)
            self.assertEqual(fake.calls[-1], (0, 1))
            self.assertTrue((Path(folder) / 'media.planning-draft.lock').is_file())

    def test_the_handle_is_rewound_before_locking_and_unlocking(self):
        fake, seeks = FakeMsvcrt(), []
        handle = SimpleNamespace(seek=seeks.append, fileno=lambda: 7)
        with patch.object(planning, 'fcntl', None), patch.object(planning, 'msvcrt', fake):
            planning._lock_file(handle)
            planning._unlock_file(handle)
        self.assertEqual((seeks, fake.calls), ([0, 0], [(1, 1), (0, 1)]))


class ExplorerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        (self.root / '项目').mkdir()
        (self.root / '项目' / '说明.md').write_text('x', encoding='utf-8')

    def tearDown(self):
        self.directory.cleanup()

    def open(self, kind, path):
        project = {'id': 'p', 'root_path': str(self.root / '项目'), 'entry_path': str(path), 'delivery_path': str(path)}
        with patch.object(local_access.operations, 'snapshot', return_value={'projects': [project]}):
            return local_access.open_local({'kind': kind, 'id': 'p'})

    def test_windows_selects_files_and_opens_folders_in_explorer(self):
        with patch.object(local_access, '_system', return_value='windows'), \
                patch('subprocess.run') as run, \
                patch.object(local_access.os, 'startfile', create=True) as startfile:
            result = self.open('entry', self.root / '项目' / '说明.md')
            run.assert_called_once()
            self.assertEqual(run.call_args.args[0], ['explorer', '/select,', str(self.root / '项目' / '说明.md')])
            self.assertTrue(result['revealed'])
            self.open('delivery', self.root / '项目')
            startfile.assert_called_once_with(str(self.root / '项目'))
            self.assertEqual(run.call_count, 1)

    def test_other_systems_say_so_and_the_mac_still_uses_open(self):
        with patch.object(local_access, '_system', return_value='other'), patch('subprocess.run') as run:
            with self.assertRaisesRegex(core.ValidationError, 'macOS 或 Windows'):
                self.open('entry', self.root / '项目' / '说明.md')
            run.assert_not_called()
        with patch.object(local_access, '_system', return_value='mac'), patch('subprocess.run') as run:
            run.return_value.returncode = 0
            self.open('entry', self.root / '项目' / '说明.md')
            self.assertEqual(run.call_args.args[0][:2], ['/usr/bin/open', '-R'])


if __name__ == '__main__':
    unittest.main()
