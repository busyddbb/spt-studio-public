'use strict';
// 发布 tools in a plain browser (Windows, or a Mac browser tab): no SPT app bridge, so the
// platform buttons are links to the official backends and the app-only actions are gone.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const deskPath = path.join(__dirname, '..', 'app', 'static', 'desk.js');
const ACCOUNTS = [
  { id: 'rn', name: '示例创作者', platform: 'xiaohongshu', handle: 'busy' },
  { id: 'ig', name: 'AK', platform: 'instagram', handle: 'ak' },
];

async function loadDesk(bridge = {}) {
  const window = {
    ...bridge,
    setTimeout, clearTimeout, URL, console,
    addEventListener() {},
    dispatchEvent() {},
    fetch: async (url) => ({ ok: true, status: 200, json: async () => (String(url).includes('/api/publishing') ? { platforms: [], accounts: [], upload_jobs: [] } : { accounts: ACCOUNTS, drafts: [], projects: [], receipts: [], media: [] }) }),
  };
  const document = { addEventListener() {}, querySelectorAll: () => [], querySelector: () => null, getElementById: () => null };
  window.window = window;
  window.document = document;
  const context = vm.createContext(window);
  vm.runInContext(fs.readFileSync(deskPath, 'utf8'), context, { filename: deskPath });
  window.MediaDesk.mount();
  await new Promise((resolve) => setTimeout(resolve, 10));
  return window.MediaDesk;
}

test('in a browser the platform button opens the official backend in a new tab', async () => {
  const desk = await loadDesk();
  assert.equal(desk.browserMode(), true);
  const html = desk.publishingButton('rn', 'draft1', '打开平台');
  assert.match(html, /^<a class="button primary" href="https:\/\/creator\.rednote\.com\/new\/note-manager" target="_blank" rel="noopener noreferrer">/);
  assert.doesNotMatch(html, /data-desk|disabled/);
  assert.equal(desk.publishingUrl('meta_suite'), 'https://business.facebook.com/latest/home');
  assert.equal(desk.publishingButton('missing'), '', 'an account without an official backend shows nothing');
  desk.unmount();
});

test('the SPT app keeps its built-in publishing window', async () => {
  const desk = await loadDesk({ mediaNativeAvailable: true, mediaPublishingNativeAvailable: true, webkit: { messageHandlers: { openPublishing: { postMessage() {} } } } });
  assert.equal(desk.browserMode(), false);
  assert.match(desk.publishingButton('rn', '', '打开平台'), /^<button type="button" class="button " data-desk="open-publishing" data-account="rn"/);
  desk.unmount();
});
