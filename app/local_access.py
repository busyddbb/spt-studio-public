"""Open registered local sources; never accept paths supplied by the page."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

if __package__:
    from . import core, media_uploads, operations
else:
    import core, media_uploads, operations


def media_path(identifier: str) -> tuple[Path, str]:
    """Resolve an unchanged, registered local media file."""
    if not isinstance(identifier, str) or not identifier:
        raise core.ValidationError('请选择已登记素材')
    with media_uploads._connect() as connection:
        row = connection.execute(
            'SELECT * FROM media_upload_jobs WHERE id=?', (identifier,)
        ).fetchone()
    if not row:
        raise core.ValidationError('素材未登记')
    path = Path(row['path'])
    try:
        if path.is_symlink() or not path.is_file():
            raise OSError()
        info = path.stat()
        expected = tuple(row[key] for key in ('size', 'mtime_ns', 'device', 'inode'))
        actual = (info.st_size, info.st_mtime_ns, info.st_dev, info.st_ino)
        if actual != expected:
            raise core.ValidationError('素材已变化，请重新加入素材库并重新审核')
    except OSError:
        raise core.ValidationError('找不到原素材，请恢复原文件或重新加入素材库')
    return path, row['mime_type']


def preview_image(identifier: str) -> tuple[Path, str]:
    path, mime = media_path(identifier)
    if mime not in ('image/jpeg', 'image/png', 'image/webp', 'image/gif'):
        raise core.ValidationError('这里只预览图片；视频请在 Finder 中打开')
    if path.stat().st_size > 25 * 1024 * 1024:
        raise core.ValidationError('图片超过 25 MiB，请在本机查看原文件')
    return path, mime


def open_local(arguments: dict) -> dict:
    if not isinstance(arguments, dict):
        raise core.ValidationError('本地打开参数必须是对象')
    kind, identifier = arguments.get('kind'), arguments.get('id')
    reveal = kind == 'media'
    if reveal:
        path, _ = media_path(identifier)
    else:
        keys = {'project': 'root_path', 'entry': 'entry_path', 'delivery': 'delivery_path'}
        if kind not in keys:
            raise core.ValidationError('不支持此本地入口')
        project = next((p for p in operations.snapshot()['projects'] if p['id'] == identifier), None)
        if not project or not project.get(keys[kind]):
            raise core.ValidationError('项目还没有登记这个入口')
        path = Path(project[keys[kind]])
        root = Path(project['root_path']).resolve()
        if not path.is_absolute() or not path.resolve().is_relative_to(root):
            raise core.ValidationError('入口必须在已登记的项目目录内')
        if not path.exists():
            raise core.ValidationError('入口已移动或不存在，请更新项目路径')
        # Reveal documents so a Markdown file's associated app cannot affect
        # this app's navigation; folders open directly in Finder.
        reveal = path.is_file()
    system = _system()
    if system == 'mac':
        command = ['/usr/bin/open'] + (['-R'] if reveal else []) + [str(path)]
        result = subprocess.run(command, capture_output=True, timeout=10, check=False)
        if result.returncode:
            raise core.ValidationError('Finder 未能打开入口，请检查路径和系统权限')
    elif system == 'windows':
        _open_in_explorer(path, reveal)
    else:
        raise core.ValidationError('在文件夹中打开需要 macOS 或 Windows')
    return {'opened': True, 'revealed': reveal, 'path': str(path)}


def _system() -> str:
    return 'mac' if sys.platform == 'darwin' else 'windows' if os.name == 'nt' else 'other'


def _open_in_explorer(path: Path, reveal: bool) -> None:
    """Windows: select the file in File Explorer, or open the folder.

    explorer.exe answers 1 even when it worked, so its exit code is not checked.
    """
    try:
        if reveal:
            subprocess.run(['explorer', '/select,', str(path)], timeout=10, check=False)
        else:
            os.startfile(str(path))   # type: ignore[attr-defined]
    except (OSError, subprocess.SubprocessError):
        raise core.ValidationError('文件资源管理器未能打开入口，请检查路径')
