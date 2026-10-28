"""Allow the local SPT page to request ID-based desktop operations.

Platform pages never receive this bridge. No path, URL, script, password or
browser session supplied by page JavaScript is accepted as a command argument.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import urlsplit


COMMANDS = {
    'openPublishing': ('account_id', 'draft_id', 'target'),
    'runPublishingQueue': (),
    'previewPublishingQueue': ('queue_id',),
    'startRednoteUpload': ('account_id', 'draft_id'),
    'cancelRednoteUpload': ('job_id', 'id'),
    'previewRednoteUpload': ('job_id', 'id'),
    'chooseWorkspace': (), 'chooseMedia': (),
}


def local_page(url: str) -> bool:
    try:
        value = urlsplit(url)
        return (value.scheme == 'http' and value.hostname == '127.0.0.1'
                and value.port == 8766 and value.username is None
                and value.password is None
                and (value.path == '/' or value.path.startswith('/workspace/')))
    except (ValueError, TypeError):
        return False


def arguments(command: str, payload: object) -> dict:
    if command not in COMMANDS or not isinstance(payload, dict):
        raise ValueError('未知的本地操作')
    # The existing queue UI sends {queue_id, jobs}; these are only a wake-up
    # hint. As on Mac, claim persisted tasks afresh and never trust UI job data.
    if command == 'runPublishingQueue':
        return {}
    allowed = COMMANDS[command]
    if set(payload) - set(allowed):
        raise ValueError('此操作只接受任务或账号 ID')
    result = {}
    for key, value in payload.items():
        if not isinstance(value, str) or len(value) > 200 or any(ord(c) < 32 for c in value):
            raise ValueError('任务或账号 ID 无效')
        if key == 'target':
            if value not in ('', 'meta_suite'):
                raise ValueError('未知的平台打开目标')
        elif not value or any(c in value for c in ('/', '\\', ':')):
            raise ValueError('任务或账号 ID 无效')
        result[key] = value
    required = {'openPublishing': ('account_id',),
                'previewPublishingQueue': ('queue_id',),
                'startRednoteUpload': ('account_id', 'draft_id')}.get(command, ())
    if any(not result.get(key) for key in required):
        raise ValueError('缺少任务或账号 ID')
    if command in ('cancelRednoteUpload', 'previewRednoteUpload') and not (result.get('job_id') or result.get('id')):
        raise ValueError('缺少上传任务 ID')
    return result


def choose(kind: str):
    """A user-operated system dialog; arbitrary web-supplied paths are rejected."""
    import tkinter
    from tkinter import filedialog
    root = tkinter.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    try:
        if kind == 'chooseWorkspace':
            return filedialog.askdirectory(parent=root, title='选择工作区文件夹') or None
        return list(filedialog.askopenfilenames(parent=root, title='选择本地视频或图片',
                    filetypes=[('视频或图片', '*.mp4 *.mov *.m4v *.webm *.jpg *.jpeg *.png *.gif *.webp *.avif *.bmp *.tif *.tiff')]))
    finally:
        root.destroy()


async def install(page, runtime) -> None:
    """Install once on the one local UI Page, including safe iframe forwarding."""
    async def callback(source, command, payload=None):
        if (source.get('page') is not page or source.get('frame') is not page.main_frame
                or not local_page(page.url) or not local_page(source['frame'].url)):
            raise ValueError('外部网页不能操作本地 SPT')
        body = arguments(command, {} if payload is None else payload)
        if command in ('chooseWorkspace', 'chooseMedia'):
            value = await asyncio.to_thread(choose, command)
            # The page could have navigated while the user chose a file.
            if not local_page(page.url):
                return {'ok': False}
            name = 'sptWorkspaceChosen' if command == 'chooseWorkspace' else 'mediaUploaderNativeFiles'
            if value is not None:
                await page.evaluate('(v) => { const fn=window[v.name]; if(typeof fn==="function")fn(v.value); }', {'name':name,'value':value})
            return {'ok':True}
        result = await runtime.dispatch(command, body)
        if command == 'openPublishing' and local_page(page.url):
            await page.evaluate('(v)=>window.mediaPublishingOpenResult?.(v)', {'ok':True,'opened':True})
        return result if isinstance(result, dict) else {'ok':True}

    await page.expose_binding('sptWindowsBridge', callback)
    script = (Path(__file__).parent / 'bridge.js').read_text(encoding='utf-8')
    await page.add_init_script(script=script)
    if local_page(page.url):
        await page.evaluate(script)
