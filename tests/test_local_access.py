"""Local file access is restricted to records, with source identity preserved."""
from __future__ import annotations
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import core, local_access, media_uploads


class LocalAccessTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.database = patch.object(core, 'DB', self.root / 'media.sqlite3')
        self.database.start()
        self.image = self.root / '图.png'
        self.image.write_bytes(b'local-test-image')
        self.asset = media_uploads.register_files([str(self.image)])['jobs'][0]

    def tearDown(self):
        self.database.stop()
        self.directory.cleanup()

    def test_image_resolves_only_registered_identity(self):
        path, mime = local_access.preview_image(self.asset['id'])
        self.assertEqual(path, self.image)
        self.assertEqual(mime, 'image/png')
        with self.assertRaises(core.ValidationError):
            local_access.preview_image(str(self.image))

    def test_changed_source_cannot_be_previewed_as_approved_asset(self):
        self.image.write_bytes(b'changed-image')
        with self.assertRaisesRegex(core.ValidationError, '变化'):
            local_access.preview_image(self.asset['id'])

    def test_symlink_replacement_is_rejected(self):
        other = self.root / 'other.png'
        other.write_bytes(self.image.read_bytes())
        self.image.unlink()
        self.image.symlink_to(other)
        with self.assertRaises(core.ValidationError):
            local_access.media_path(self.asset['id'])

    def test_open_does_not_accept_arbitrary_path(self):
        with patch('subprocess.run') as run:
            with self.assertRaises(core.ValidationError):
                local_access.open_local({'kind': 'path', 'id': str(self.image)})
            run.assert_not_called()

    def test_project_entry_cannot_escape_registered_root(self):
        project = {'id': 'test', 'root_path': str(self.root), 'entry_path': '/etc/hosts'}
        with patch.object(local_access.operations, 'snapshot', return_value={'projects': [project]}):
            with patch('subprocess.run') as run:
                with self.assertRaises(core.ValidationError):
                    local_access.open_local({'kind': 'entry', 'id': 'test'})
                run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
