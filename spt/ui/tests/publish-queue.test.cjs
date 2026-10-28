'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function boot({ hash = '#publish?view=queue', responses = {}, native = false, fetchImpl } = {}) {
  const calls = [];
  const host = { innerHTML: '', querySelectorAll: () => [], querySelector: () => null };
  const context = {
    location: { hash },
    document: { querySelector: () => host },
    fetch: fetchImpl || (async (url) => { calls.push(String(url)); const key = String(url).split('?')[0]; const body = responses[key] ?? (key.endsWith('/queue') ? { jobs: [], accounts: [], max_uploads: 2 } : { work: { title: '作品' } }); return { ok: true, json: async () => body }; }),
    window: native ? { webkit: { messageHandlers: { runPublishingQueue: { postMessage: (value) => calls.push({ native: value }) } } } } : {},
    setTimeout, clearTimeout, encodeURIComponent, URLSearchParams, Date, console
  };
  vm.runInNewContext(fs.readFileSync(require.resolve('../publish-queue.js'), 'utf8'), context);
  return { api: context.window.SPTPublishQueue, host, calls, context };
}

test('空队列首次渲染只请求一次，不在 render/loadQueue 间循环', async () => {
  const { api, host, calls } = boot();
  api.render(host);
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(calls.filter((value) => value === '/api/publishing/queue').length, 1);
});

test('切换 work_id 会清掉旧预览并重新读取新作品', async () => {
  const { api, host, calls, context } = boot({ hash: '#publish?work_id=old' });
  api.render(host);
  await new Promise((resolve) => setImmediate(resolve));
  context.location.hash = '#publish?work_id=new';
  api.render(host);
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(calls.filter((value) => value.startsWith('/api/publishing/work?')).map((value) => decodeURIComponent(value.split('=')[1])), ['old', 'new']);
});

test('离开队列页后，异步队列返回不会重绘当前资产页或启动轮询', async () => {
  let resolveQueue;
  const { api, host, context } = boot({
    fetchImpl: async (url) => {
      if (String(url).endsWith('/queue')) return new Promise((resolve) => { resolveQueue = resolve; });
      return { ok: true, json: async () => ({ work: { title: '作品' } }) };
    }
  });
  api.render(host);
  host.innerHTML = '<main>资产库</main>';
  context.location.hash = '#works';
  resolveQueue({ ok: true, json: async () => ({ jobs: [{ state: 'queued' }], accounts: [], max_uploads: 2 }) });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(host.innerHTML, '<main>资产库</main>');
});

test('队列协议使用原生 runPublishingQueue message handler，且页面声明只本地队列', () => {
  const source = fs.readFileSync(require.resolve('../publish-queue.js'), 'utf8');
  assert.match(source, /messageHandlers\?\.runPublishingQueue/);
  assert.match(source, /仅本地队列/);
});

test('排期和 submit_enabled 使用持久状态，不从重绘后的默认控件强制覆盖', () => {
  const source = fs.readFileSync(require.resolve('../publish-queue.js'), 'utf8');
  assert.match(source, /scheduledMode/);
  assert.match(source, /submitEnabled/);
  assert.match(source, /submit_enabled:state\.submitEnabled/);
});

