"""Real Chromium fixtures for the local-only Windows UI bridge (no platform login)."""
from __future__ import annotations
import os
from pathlib import Path
import unittest

from windows.bridge import arguments, install, local_page

ROOT = Path(__file__).resolve().parents[1]


class BridgeValidationTests(unittest.TestCase):
    def test_rejects_external_origins_and_arbitrary_payloads(self):
        self.assertTrue(local_page('http://127.0.0.1:8766/workspace/'))
        for url in ('http://127.0.0.1:8767/workspace/','https://127.0.0.1:8766/','http://localhost:8766/','http://127.0.0.1:8766/evil','http://u:p@127.0.0.1:8766/'):
            self.assertFalse(local_page(url))
        for payload in ({'account_id':'x','path':'C:/private'},{'account_id':'https://example.com'},{'account_id':'x','target':'file:///x'}):
            with self.assertRaises(ValueError): arguments('openPublishing',payload)
        self.assertEqual(arguments('previewPublishingQueue',{'queue_id':'queue_123'}),{'queue_id':'queue_123'})
        self.assertEqual(arguments('runPublishingQueue',{'queue_id':None,'jobs':[{'path':'C:/never-use-this'}]}),{})


class BridgeBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            self.skipTest('Install requirements-windows.txt for browser fixture tests')
        self.playwright = await async_playwright().start()
        try:
            self.browser = await self.playwright.chromium.launch(headless=True,**({'executable_path':os.environ['SPT_TEST_BROWSER']} if os.environ.get('SPT_TEST_BROWSER') else {}))
        except Exception as error:
            await self.playwright.stop()
            self.skipTest('Chromium fixture browser unavailable: '+str(error).splitlines()[0])
        self.context = await self.browser.new_context()
        self.page = await self.context.new_page()
        await self.context.route('**/*',lambda route:route.fulfill(status=200,content_type='text/html; charset=utf-8',body='<html><body>fixture</body></html>'))
        self.calls=[]
        outer=self
        class Runtime:
            async def dispatch(self,command,payload):
                outer.calls.append((command,payload))
                return {'ok':True}
        await install(self.page,Runtime())

    async def asyncTearDown(self):
        if hasattr(self,'browser'):
            await self.browser.close()
            await self.playwright.stop()

    async def test_bridge_works_on_local_page_and_same_origin_tool(self):
        await self.page.goto('http://127.0.0.1:8766/workspace/')
        await self.page.evaluate('''async () => {
          window.result = null;
          window.mediaPublishingOpenResult = v => window.result=v;
          await window.webkit.messageHandlers.openPublishing.postMessage({account_id:'demo'});
        }''')
        self.assertEqual(self.calls,[('openPublishing',{'account_id':'demo'})])
        self.assertTrue(await self.page.evaluate('window.result.opened'))
        await self.page.evaluate('() => {const f=document.createElement("iframe"); f.src="http://127.0.0.1:8766/?embed=1";document.body.append(f)}')
        await self.page.wait_for_function('document.querySelector("iframe")?.contentWindow?.mediaNativeAvailable===true')
        await self.page.frames[1].evaluate('window.webkit.messageHandlers.runPublishingQueue.postMessage({queue_id:undefined,jobs:[{path:"C:/never-use-this"}]})')
        self.assertEqual(self.calls[-1],('runPublishingQueue',{}))

    async def test_external_page_has_no_bridge_and_raw_binding_is_rejected(self):
        await self.page.goto('https://example.com/')
        self.assertFalse(await self.page.evaluate('!!window.mediaNativeAvailable'))
        with self.assertRaises(Exception):
            await self.page.evaluate('window.sptWindowsBridge("runPublishingQueue",{})')
        self.assertEqual(self.calls,[])

    async def test_external_iframe_cannot_use_parent_bridge(self):
        await self.page.goto('http://127.0.0.1:8766/workspace/')
        await self.page.evaluate('() => {const f=document.createElement("iframe");f.src="https://example.com/";document.body.append(f)}')
        await self.page.wait_for_function('document.querySelector("iframe")?.contentWindow!==null')
        frame=await (await self.page.query_selector('iframe')).content_frame()
        await frame.wait_for_url('https://example.com/')
        self.assertFalse(await frame.evaluate('!!window.mediaNativeAvailable'))
        with self.assertRaises(Exception):
            await frame.evaluate('window.sptWindowsBridge("runPublishingQueue",{})')
        self.assertEqual(self.calls,[])


if __name__=='__main__': unittest.main()
