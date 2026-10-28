"""Public-DOM browser fixtures, never real platform sessions or private APIs."""
from __future__ import annotations
import asyncio
import datetime as dt
import os
from pathlib import Path
import unittest

from windows.metrics_worker import MetricsWorker, PlatformReader, permitted

ROOT=Path(__file__).resolve().parents[1]


class MetricsValidationTests(unittest.TestCase):
    def test_navigation_allowlist(self):
        self.assertTrue(permitted('https://creator.rednote.com/new/note-manager','xiaohongshu'))
        for url in ('file:///private','http://creator.rednote.com/','https://creator.rednote.com.evil.test/','https://u:p@creator.rednote.com/','https://creator.rednote.com:8443/'):
            self.assertFalse(permitted(url,'xiaohongshu'))


class MetricsBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        try:
            from playwright.async_api import async_playwright
        except ImportError: self.skipTest('Install requirements-windows.txt for browser fixture tests')
        self.pw=await async_playwright().start()
        try:
            self.browser=await self.pw.chromium.launch(headless=True,**({'executable_path':os.environ['SPT_TEST_BROWSER']} if os.environ.get('SPT_TEST_BROWSER') else {}))
        except Exception as error:
            await self.pw.stop();self.skipTest('Chromium fixture browser unavailable: '+str(error).splitlines()[0])
        self.context=await self.browser.new_context()
        self.page=await self.context.new_page()

    async def asyncTearDown(self):
        if hasattr(self,'browser'):
            await self.browser.close();await self.pw.stop()

    async def fixture(self,html,url):
        await self.page.route('**/*',lambda route:route.fulfill(status=200,content_type='text/html; charset=utf-8',body=html))
        await self.page.goto(url)

    async def test_rednote_reader_captures_exact_dom_text_and_profile(self):
        numbers=''.join('<div><svg></svg><span>'+x+'</span></div>' for x in ('48','0','3','2','0'))
        note='<div class="note"><span>示例短片</span><span>2020-01-01 12:00</span>'+numbers+'<a href="/publish/update?id=0123456789abcdef01234567">编辑</a></div>'
        notes='<header>示例账号</header><div>笔记管理</div>'+note
        profile='<div class="user"><span>示例账号</span><div class="data"><span class="count">11</span><span>关注</span><span class="count">200</span><span>粉丝</span><span class="count">1.7K</span><span>获赞与收藏</span></div></div>'
        async def fixture(route):
            await route.fulfill(status=200,content_type='text/html; charset=utf-8',body=profile if '/user/profile/' in route.request.url else notes)
        await self.context.route('**/*',fixture)
        result=await PlatformReader(self.page,ROOT,'xiaohongshu','0123456789abcdef01234567',interval=.01).read()
        self.assertEqual(result['status'],'done')
        self.assertEqual(result['notes'][0]['numbers'],['48','0','3','2','0'])
        self.assertEqual(result['notes'][0]['note_id'],'0123456789abcdef01234567')
        self.assertEqual(result['profile']['followers'],'200')

    async def test_tiktok_reader_preserves_rounded_values_and_private_state(self):
        html='''<header>@example_creator</header><div>Posts (Created on)</div><div>Privacy</div><div>Views</div><div>Likes</div><div>Comments</div><div class="row"><div><a href="https://www.tiktok.com/@example_creator/video/7000000000000000001">Example short</a><span>Jan 1, 2020, 11:59 PM</span></div><div><button>Only me</button></div><div><span>1.2K 2 1</span></div><div><button></button></div></div>'''
        await self.context.route('**/*',lambda route:route.fulfill(status=200,content_type='text/html; charset=utf-8',body=html))
        result=await PlatformReader(self.page,ROOT,'tiktok',interval=.01).read()
        self.assertEqual(result['status'],'done')
        self.assertEqual(result['notes'][0]['metrics']['views'],'1.2K')
        self.assertEqual(result['notes'][0]['state'],'仅自己可见')

    async def test_meta_redirect_and_login_detection(self):
        await self.fixture('<a href="/latest/home?business_id=1&asset_id=2">Home</a><div>Loading</div>','https://business.facebook.com/latest/home')
        script=(ROOT/'native/MetricsReaderDOM.js').read_text()
        result=await self.page.evaluate('a=>('+script+')(a)',{'phase':'notes','platform':'facebook'})
        self.assertEqual(result['status'],'navigate')
        self.assertIn('/latest/posts/published_posts/',result['url'])
        await self.page.unroute('**/*')
        await self.fixture('<form><input name="email"><input name="pass"></form>','https://www.facebook.com/login/')
        result=await PlatformReader(self.page,ROOT,'facebook',interval=.01).phase('notes',1)
        self.assertEqual(result['status'],'login')

    async def test_both_meta_platforms_read_their_own_detail_metrics(self):
        date=dt.datetime.now()-dt.timedelta(days=1)
        shown=date.strftime('%b ')+str(date.day)+date.strftime(', %I:%M %p')
        for platform in ('facebook','instagram'):
            with self.subTest(platform=platform):
                list_path='/latest/posts/published_posts/' if platform=='facebook' else '/latest/insights/content/'
                detail='https://business.facebook.com/latest/insights/object_insights/?business_id=1&asset_id=2&content_id=70000000000000001'
                home='<a href="/latest/home?business_id=1&asset_id=2">Home</a>'
                rows='''<header>Example Brand</header><table><tr><th>Title</th><th>Date published</th><th>Views</th></tr><tr><td><img alt="Instagram"><img alt="Facebook"><span onclick="location.href='%s'">A detailed example caption for the creator short video</span><span>Reel</span><span>Example Brand, example_creator</span></td><td>%s</td><td>999</td></tr></table>''' % (detail.replace('&','&amp;'),shown)
                title=platform.capitalize()
                values=(('Views','212'),('Reach','150'),('Likes and reactions','3'),('Comments','0'),('Shares','—'),('Saves','1'))
                contents='<header>Example Brand</header><div role="tab" aria-selected="true">'+title+'</div><h2>Example creator short video</h2>'+''.join('<div><span>'+label+'</span><span>'+value+'</span></div>' for label,value in values)
                async def fixture(route):
                    url=route.request.url
                    await route.fulfill(status=200,content_type='text/html; charset=utf-8',body=contents if 'object_insights' in url else rows if list_path in url else home)
                await self.context.route('**/*',fixture)
                result=await PlatformReader(self.page,ROOT,platform,interval=.03).read()
                self.assertEqual(result['status'],'done')
                self.assertEqual(len(result['notes']),1)
                self.assertEqual(result['notes'][0]['detail_id'],'70000000000000001')
                self.assertEqual(result['notes'][0]['metrics']['views'],'212')
                self.assertEqual(result['notes'][0]['metrics']['shares'],'')
                await self.context.unroute('**/*',fixture)


class MetricsCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_account_list_finishes_claim_without_inventing_results(self):
        calls=[]
        class API:
            async def get(self,path):return {'accounts':[]}
            async def post(self,path,value):calls.append((path,value));return {'task':{'id':'demo-run'}} if path.endswith('/claim') else {}
        worker=MetricsWorker(None,API(),ROOT)
        await worker.tick();await worker.task
        self.assertEqual([c[0].split('/')[-1] for c in calls],['claim','finish'])
        self.assertEqual(calls[-1][1]['id'],'demo-run')


if __name__=='__main__':unittest.main()
