"""Read the same public DOM as the Mac reader, in each user's local profile.

The server owns due times, matching, exact-number checks and append-only writes.
This worker does not inspect browser credentials or call private platform APIs.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import re
import time
from pathlib import Path
from urllib.parse import urlsplit


PLATFORMS = {
    'xiaohongshu': ('rednote', 'https://creator.rednote.com/new/note-manager', ('rednote.com','xiaohongshu.com','xhscdn.com','xhslink.com')),
    'tiktok': ('tiktok', 'https://www.tiktok.com/tiktokstudio/content', ('tiktok.com','tiktokcdn.com','tiktokv.com','ttwstatic.com','byteoversea.com')),
    'instagram': ('instagram', 'https://business.facebook.com/latest/home', ('facebook.com','fbcdn.net','fbsbx.com','instagram.com','meta.com')),
    'facebook': ('facebook', 'https://business.facebook.com/latest/home', ('facebook.com','fbcdn.net','fbsbx.com','instagram.com','meta.com')),
}


def permitted(url: str, platform: str) -> bool:
    try:
        value = urlsplit(url)
        return (value.scheme == 'https' and value.username is None and value.password is None
                and value.port in (None, 443) and any(value.hostname == domain or (value.hostname or '').endswith('.'+domain)
                    for domain in PLATFORMS[platform][2]))
    except (ValueError, KeyError, TypeError):
        return False


class PlatformReader:
    def __init__(self, page, root: Path, platform: str, handle: str = '', *, seconds=90, interval=1.5):
        self.page, self.platform = page, platform
        self.script = (Path(root) / 'native/MetricsReaderDOM.js').read_text(encoding='utf-8')
        self.handle, self.seconds, self.interval = handle, seconds, interval

    async def read(self) -> dict:
        async def navigation(route):
            request = route.request
            if request.is_navigation_request() and request.frame == self.page.main_frame and not permitted(request.url, self.platform):
                await route.abort()
            else:
                await route.fallback()
        await self.page.route('**/*', navigation)
        try:
            width = 3000 if self.platform in ('instagram','facebook') else 1280
            await self.page.set_viewport_size({'width':width,'height':900})
            await self.page.goto(PLATFORMS[self.platform][1], wait_until='domcontentloaded', timeout=60000)
            # A read starts with fresh DOM progress, while browser login stays local.
            await self.page.evaluate('() => { delete window.__sptMetricsRead; try { sessionStorage.removeItem("sptIG"); } catch (_) {} }')
            result = await self.phase('notes', self.seconds)
            if result.get('status') != 'done':
                return result
            result['observed_at'] = dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
            if self.platform == 'xiaohongshu' and (match := re.search(r'(?<![0-9a-f])[0-9a-f]{24}(?![0-9a-f])', self.handle)):
                try:
                    await self.page.goto('https://www.rednote.com/user/profile/'+match.group(),wait_until='domcontentloaded',timeout=30000)
                    profile = await self.phase('profile',30)
                    if profile.get('status') == 'done':
                        result['profile'] = {'followers':profile.get('followers')}
                except Exception:
                    pass  # Notes remain valid when the optional public profile is unavailable.
            return result
        except asyncio.CancelledError:
            raise
        except Exception:
            return {'status':'attention','reason':'平台页面未读出，请在 SPT 打开该账号核对登录与网络后重试'}
        finally:
            await self.page.unroute('**/*', navigation)

    async def phase(self, phase: str, seconds: float) -> dict:
        deadline, navigations, last_wait = time.monotonic()+seconds, 0, ''
        while time.monotonic() < deadline:
            if not permitted(self.page.url, self.platform):
                return {'status':'attention','reason':'平台跳转到允许范围之外，已停止读取'}
            args = {'phase':phase,'platform':PLATFORMS[self.platform][0],'days':14,'now':time.time()*1000}
            try:
                value = await self.page.evaluate('args => ('+self.script+')(args)',args)
            except Exception:
                await asyncio.sleep(self.interval)
                continue
            if not isinstance(value,dict):
                value = {}
            status = value.get('status')
            if status in ('done','login','attention'):
                return value
            if status == 'navigate':
                target = value.get('url')
                if navigations >= 3 or not permitted(target,self.platform):
                    return {'status':'attention','reason':'列表要求跳转到不允许的地址，已停止读取'}
                navigations += 1
                await self.page.goto(target,wait_until='domcontentloaded',timeout=60000)
                deadline = time.monotonic()+75
            elif status == 'wait':
                last_wait = str(value.get('reason') or '')[:120]
                if last_wait.startswith(('读完一篇','打开帖子详情')):
                    deadline = max(deadline,time.monotonic()+45)
            await asyncio.sleep(self.interval)
        return {'status':'attention','reason':'列表页面没有读出来：'+last_wait}


class MetricsWorker:
    def __init__(self, manager, api, root: Path):
        self.manager, self.api, self.root = manager, api, Path(root)
        self.task = None
        self.last_poll = float('-inf')

    async def tick(self):
        if self.task and not self.task.done():
            return
        if self.task:
            try:
                self.task.result()
            except (Exception, asyncio.CancelledError):
                pass
            self.task = None
        if time.monotonic()-self.last_poll < 10:
            return
        self.last_poll = time.monotonic()
        response = await self.api.post('/api/spt/metrics/capture/claim',{'auto':True})
        task = response.get('task')
        if isinstance(task,dict) and task.get('id'):
            self.task = asyncio.create_task(self.run(task['id']))

    async def run(self, identifier: str):
        reason = '还没有在 SPT 打开过支持读数的账号：先在 发布 → 平台入口 登录一次'
        try:
            snapshot = await self.api.get('/api/publishing')
            accounts = [a for a in snapshot.get('accounts',[]) if a.get('platform') in PLATFORMS and a.get('session_saved') is True]
            for account in accounts:
                platform = account['platform']
                profiles = [account]
                if platform in ('instagram','facebook'):
                    profiles += [a for a in accounts if a['id'] != account['id'] and a['platform'] in ('instagram','facebook') and a.get('brand') == account.get('brand')]
                outcome = {'status':'login'}
                for profile in profiles:
                    try:
                        page = await self.manager.page_for(profile['id'],profile['platform'],purpose='metrics-'+platform)
                        outcome = await asyncio.wait_for(PlatformReader(page,self.root,platform,str(account.get('handle') or '')).read(),timeout=540)
                    except asyncio.TimeoutError:
                        outcome = {'status':'attention','reason':'本次平台读取超时，请核对官方页面后重试'}
                    except Exception:
                        outcome = {'status':'attention','reason':'该账号的官方页面未读出，请核对登录后重试'}
                    if outcome.get('status') != 'login':
                        break
                outcome['id'] = identifier
                outcome['account'] = {k:account.get(k,'') for k in ('id','name','brand','platform','handle')}
                await self.api.post('/api/spt/metrics/capture/result',outcome)
        except asyncio.CancelledError:
            reason = 'Windows 执行器已停止，本次未完成的数据不会冒充成功'
            raise
        except Exception:
            reason = 'Windows 读数中断：请检查本地服务与平台账号后重试'
        finally:
            await self.api.post('/api/spt/metrics/capture/finish',{'id':identifier,'reason':reason})

    async def stop(self):
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except (Exception, asyncio.CancelledError):
                pass
