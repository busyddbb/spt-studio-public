'use strict';
// Fixtures are written in Pacific time; pin the zone so local-time output is the same everywhere.
process.env.TZ = 'America/Los_Angeles';
const test = require('node:test');
const assert = require('node:assert/strict');
const ui = require('../spt.js');
const dashboard = require('../dashboard.js');
const deps = {
  esc: ui.esc,
  icon: () => '',
  safeLocalURL: ui.safeLocalURL,
  safeExternalURL: ui.safeExternalURL,
  platformName: (platform) => platform,
  cardHTML: () => '',
};

test('canonical API paths stay on the configured same-origin mount', () => {
  const path = '/api/works/one/file?path=V3%2F成片.mp4';
  assert.equal(ui.apiURL(path, '/api'), path);
  assert.equal(ui.apiURL(path, '/api/spt'), '/api/spt/works/one/file?path=V3%2F成片.mp4');
  assert.equal(ui.apiURL('/api/events', '/api/spt'), '/api/spt/events');
  assert.equal(ui.apiURL('/api/dashboard', '/api/spt/'), '/api/spt/dashboard');
});

test('missing metrics remain unknown and rounded source text is not counted', () => {
  const post = { metrics: { views: null, likes: 0, saves: '12' }, display_metrics: { views: '4.8K' } };
  assert.equal(dashboard.metricValue(post, 'views'), null);
  assert.equal(dashboard.metricText(post, 'views'), '—');
  assert.equal(dashboard.metricValue(post, 'likes'), 0);
  assert.equal(dashboard.metricText(post, 'likes'), '0');
  assert.equal(dashboard.metricValue(post, 'saves'), null);
  assert.equal(dashboard.metricValue({ metrics: { views: Infinity } }, 'views'), null);
  const singleWindow = { metric_window: 'D7', metrics: { views: 70 } };
  assert.equal(dashboard.metricValue(singleWindow, 'views', 'D1'), null);
  assert.equal(dashboard.metricValue(singleWindow, 'views', 'D7'), 70);
});

test('history charts keep each D1/D3/D7 cohort separate and require sample dates', () => {
  const post = {
    metric_window: 'D3',
    history: [
      { observed_at: '2026-10-01', metrics_by_window: { D1: { views: 10 }, D3: { views: 30 } } },
      { observed_at: '2026-10-03', metrics_by_window: { D1: { views: 12 }, D3: { views: 35 } } },
      { observed_at: null, metrics_by_window: { D3: { views: 999 } } },
      { observed_at: '2026-10-04', metrics_by_window: { D7: { views: 100 } } },
    ],
  };
  assert.deepEqual(dashboard.historySeries(post).map((point) => point.value), [30, 35]);
  assert.deepEqual(dashboard.historySeries(post, 'D1').map((point) => point.value), [10, 12]);
  assert.deepEqual(dashboard.historySeries(post, 'D7').map((point) => point.value), [100]);
  assert.deepEqual(dashboard.historySeries({ history: post.history }), []);
});

test('account content excludes withdrawn history and never selects another account post', () => {
  const data = {
    accounts: [{ id: 'one', platform: 'instagram', brand_id: 'brand' }, { id: 'two', platform: 'rednote', brand_id: 'brand' }],
    posts: [
      { id: 'new', account_id: 'one', current: true, caption_complete: true, cover: '/api/works/work/cover' },
      { id: 'known', account_id: 'one', current: true, metrics: { views: 20 } },
      { id: 'withdrawn', account_id: 'one', current: false },
      { id: 'deleted', account_id: 'one', status: 'deleted' },
      { id: 'other', account_id: 'two', current: true },
    ],
  };
  assert.deepEqual(dashboard.accountPosts(data, 'one').map((post) => post.id), ['new', 'known']);
  assert.equal(dashboard.selectedItems({ dashboard: data, brand: 'all', accountId: 'one', postId: 'other' }).post.id, 'known', 'falls back to a post that has numbers');
  assert.equal(dashboard.selectedItems({ dashboard: data, brand: 'all', accountId: 'one', postId: 'new' }).post.id, 'new');
});

test('the post card opens on the newest post with numbers, newest first', () => {
  const data = {
    accounts: [{ id: 'one', platform: 'instagram', brand_id: 'brand' }],
    posts: [
      { id: 'old-data', account_id: 'one', current: true, published_at: '2026-09-29', metrics_by_window: { D1: { views: 13 } }, metric_window: 'D1', metrics: { views: 13 } },
      { id: 'fresh', account_id: 'one', current: true, published_at: '2026-10-21' },
      { id: 'd7', account_id: 'one', current: true, published_at: '2026-09-20', metrics_by_window: { D7: { views: 70 } } },
      { id: 'mid-data', account_id: 'one', current: true, published_at: '2026-10-05', metrics_by_window: { D3: { views: 40 } }, metric_window: 'D3', metrics: { views: 40 } },
    ],
  };
  const pick = (window) => dashboard.selectedItems({ dashboard: data, brand: 'all', accountId: 'one', window });
  assert.deepEqual(pick('latest').posts.map((post) => post.id), ['fresh', 'mid-data', 'old-data', 'd7']);
  assert.equal(pick('latest').post.id, 'mid-data');
  assert.equal(pick('D7').post.id, 'd7', 'the window in use decides which numbers count');
  assert.equal(pick('D1').post.id, 'old-data');
  assert.equal(dashboard.selectedItems({ dashboard: { ...data, posts: [data.posts[1]] }, brand: 'all', accountId: 'one', window: 'latest' }).post.id, 'fresh', 'without any numbers the newest post');
});

test('source identifiers become readable titles while raw evidence remains in expanded details', () => {
  const post = { id: 'one', title: 'unknown_official_menu_identity', content_id: 'AKV017', source: '项目/原始数据.csv', caption: '<保留原文>\n正文', caption_complete: false };
  assert.equal(dashboard.postTitle(post), '菜品待核对');
  assert.equal(dashboard.postTitle({ title: '2026-10-10_品牌宣传片' }), '品牌宣传片');
  const html = dashboard.postDialogHTML(post, {}, { window: 'latest' }, deps);
  assert.match(html, /<h2 id="post-dialog-title">菜品待核对<\/h2>/);
  assert.match(html, /<details class="post-source"><summary>来源与采样<\/summary>/);
  assert.match(html, /原始标题：unknown_official_menu_identity/);
  assert.match(html, /&lt;保留原文&gt;\n正文/);
  assert.equal(post.caption, '<保留原文>\n正文');
});

test('selected metrics use their own sample date instead of the default cohort date', () => {
  const post = {
    id: 'dates', title: '不同节点记录', metric_window: 'D7', observed_at: '2026-10-08',
    metric_observed_at_by_window: { D1: '2026-10-02', D3: '2026-10-04', D7: '2026-10-08' },
    metrics_by_window: { D1: { views: 10 }, D3: { views: 20 }, D7: { views: 30 } },
  };
  assert.deepEqual(dashboard.metricContext(post, 'D1'), { cohort: 'D1', at: '2026-10-02' });
  assert.deepEqual(dashboard.metricContext(post, 'latest'), { cohort: 'D7', at: '2026-10-08' });
  const html = dashboard.postDialogHTML(post, {}, { window: 'D3' }, deps);
  assert.match(html, /当前节点：D3/);
  assert.match(html, /采样：2026-10-04/);
  assert.doesNotMatch(html, /2026-10-08/);
  assert.equal(dashboard.metricContext({ metric_window: 'D7', observed_at: '2026-10-08' }, 'D1').at, null);
  assert.equal(dashboard.metricContext({ metric_window: 'D7', observed_at: '2026-10-08' }, 'latest').at, '2026-10-08');
  assert.equal(dashboard.metricContext({ ...post, metric_observed_at_by_window: {} }, 'D7').at, null);
});

test('a latest snapshot outside D1/D3/D7 shows the day it was recorded', () => {
  const post = {
    id: 'csv', account_id: 'ak:instagram', current: true, title: '导入的内容', published_at: '2026-10-01T10:00:00-07:00',
    metric_window: null, observed_at: '2026-10-20T09:00:00-07:00', metrics: { views: 300, likes: 12 },
    metrics_by_window: { D1: { views: null }, D3: { views: null }, D7: { views: null } },
    metric_observed_at_by_window: { D1: null, D3: null, D7: null },
  };
  assert.deepEqual(dashboard.metricContext(post, 'latest'), { cohort: null, at: '2026-10-20T09:00:00-07:00' });
  assert.equal(dashboard.metricContext(post, 'D7').at, null, 'a named window without a date stays undated');
  const html = dashboard.renderOverview(desk({ dashboard: { accounts: akAccounts, posts: [post], intelligence: {} } }), deps);
  assert.match(html, /<p class="metric-period">10\/20 记录<\/p>/);
  assert.doesNotMatch(html, /记录日期不详/);
  assert.match(dashboard.postDialogHTML(post, {}, { window: 'latest' }, deps), /采样：2026-10-20T09:00:00-07:00/);
});

test('parenting history samples use the named window without mixing different cohorts', () => {
  const post = { metric_window: 'D7', history: [
    { window: 'D1', observed_at: '2026-10-02', metrics: { views: 11 } },
    { window: 'D7', observed_at: '2026-10-08', metrics: { views: 70 } },
    { window: 'D7', observed_at: '2026-10-09', metrics: { views: 77 } },
  ] };
  assert.deepEqual(dashboard.historySeries(post).map((point) => point.value), [70, 77]);
  assert.deepEqual(dashboard.historySeries(post, 'D1').map((point) => point.value), [11]);
});

test('official account opening uses only the existing native identity', () => {
  const calls = [];
  const host = { mediaPublishingNativeAvailable: true, webkit: { messageHandlers: { openPublishing: { postMessage: (payload) => calls.push(payload) } } } };
  const account = { id: 'parenting:rednote', legacy_account_id: 'fixture_native_account', profile_url: 'https://example.com/profile' };
  assert.deepEqual(ui.requestAccountOpen(account, host), { opening: true });
  assert.deepEqual(calls, [{ account_id: 'fixture_native_account' }]);
  assert.equal(ui.hasAccountBridge(host), true);
  assert.equal(ui.hasAccountBridge({ ...host, mediaPublishingNativeAvailable: false }), false);
  assert.match(ui.requestAccountOpen(account, { ...host, mediaPublishingNativeAvailable: false }).error, /SPT 应用/);
  assert.match(ui.requestAccountOpen({ id: 'unbound' }, host).error, /关联/);
  assert.match(ui.requestAccountOpen({ legacy_account_id: '../other-account' }, host).error, /关联/);
  assert.equal(calls.length, 1);
});

test('native opening failures stay recoverable and opening is not a login or data-sync result', () => {
  const broken = { mediaPublishingNativeAvailable: true, webkit: { messageHandlers: { openPublishing: { postMessage: () => { throw new Error('offline'); } } } } };
  assert.match(ui.requestAccountOpen({ legacy_account_id: 'existing' }, broken).error, /未能打开/);
  assert.deepEqual(ui.accountOpenResult({ ok: true, opened: true }), { opened: true, message: '官方后台已打开' });
  assert.deepEqual(ui.accountOpenResult({ ok: false, error: '账号不存在' }), { opened: false, message: '账号不存在' });
  assert.equal(ui.accountOpenResult({ status: 'opened' }).opened, false);
  assert.doesNotMatch(ui.accountOpenResult({ ok: true, opened: true }).message, /已登录|已同步|成功发布/);
});

test('selected account exposes the official backend with an explicit browser-preview fallback', () => {
  const account = { id: 'parenting:rednote', brand: '示例创作者', platform_label: 'rednote', legacy_account_id: 'native_existing' };
  const native = dashboard.accountBackendHTML(account, {}, { ...deps, nativeAvailable: () => true });
  assert.match(native, /data-open-account="parenting:rednote"/);
  assert.match(native, />官方后台<\/button>/);
  assert.doesNotMatch(native, /native_existing/);
  const preview = dashboard.accountBackendHTML(account, {}, { ...deps, nativeAvailable: () => false });
  assert.match(preview, /在 SPT 应用中打开/);
  assert.match(dashboard.accountBackendHTML(account, { openingAccountId: account.id }, deps), /disabled aria-busy="true"/);
  assert.equal(dashboard.accountBackendHTML({ id: 'not-linked' }, {}, deps), '');
});

test('a client with Instagram or Facebook gets one Meta Business Suite entry that opens the shared session', () => {
  const accounts = [
    { id: 'ak:instagram', brand: 'AK', platform: 'instagram', legacy_account_id: 'ig1' },
    { id: 'ak:facebook', brand: 'AK', platform: 'facebook', legacy_account_id: null },
    { id: 'ak:tiktok', brand: 'AK', platform: 'tiktok', legacy_account_id: 'tk1' },
  ];
  assert.equal(dashboard.metaSuiteAccount(accounts).id, 'ak:instagram', 'Facebook has no session yet, so Instagram\'s is used');
  assert.equal(dashboard.metaSuiteAccount([accounts[2]]), null);
  const html = dashboard.metaSuiteHTML(accounts, {}, deps, true);
  assert.match(html, /data-open-account="ak:instagram"/);
  assert.match(html, /data-open-target="meta_suite"/);
  const sent = [];
  const host = { mediaPublishingNativeAvailable: true, webkit: { messageHandlers: { openPublishing: { postMessage: (body) => sent.push(body) } } } };
  assert.deepEqual(ui.requestAccountOpen({ legacy_account_id: 'ig1' }, host, 'meta_suite'), { opening: true });
  assert.deepEqual(sent, [{ account_id: 'ig1', target: 'meta_suite' }]);
  assert.match(ui.requestAccountOpen({ legacy_account_id: 'ig1' }, host, 'elsewhere').error, /未知/);
  assert.deepEqual(ui.requestAccountOpen({ legacy_account_id: 'ig1' }, host), { opening: true });
  assert.deepEqual(sent[1], { account_id: 'ig1' });
});

const desk = (overrides = {}) => ({
  dashboard: { accounts: [], posts: [], intelligence: {} },
  brand: 'all', window: 'latest', accountMetric: 'followers', intelTab: 'news', intelPageTab: 'news',
  allWorks: [], notes: null, health: { workspace_ready: true }, today: '2026-10-22',
  ...overrides,
});
const akAccounts = [
  { id: 'ak:instagram', brand_id: 'ak', brand: 'AK', platform: 'instagram', platform_label: 'Instagram', as_of: '2026-10-06T07:41:03.169Z', metrics: { followers: 15 }, history: [{ date: '2026-10-06', metrics: { followers: 15 } }] },
  { id: 'ak:tiktok', brand_id: 'ak', brand: 'AK', platform: 'tiktok', platform_label: 'TikTok', metrics: {}, history: [] },
];

test('the desk is called 运营 and uses listboxes instead of native selects', () => {
  const html = dashboard.renderOverview(desk({ dashboard: { accounts: akAccounts, posts: [], intelligence: {} } }), deps);
  // The title stands alone: no sentence under it, no 本机快照 footnote under the accounts.
  assert.match(html, /<header class="page-heading[^"]*">.*<h1[^>]*tabindex="-1"[^>]*>运营<\/h1>/);
  assert.doesNotMatch(html, /page-sub|account-foot|本机快照|不是实时/);
  for (const id of ['brand-filter', 'account-metric']) assert.match(html, new RegExp(`<input type="hidden" id="${id}" value=`));
  assert.doesNotMatch(html, /<select/);
  const post = { id: 'p', account_id: 'ak:instagram', current: true, title: '扬州炒饭', published_at: '2026-10-01', metric_window: 'D3', metrics: { views: 40 }, metrics_by_window: { D3: { views: 40 } } };
  const withPost = dashboard.renderOverview(desk({ dashboard: { accounts: akAccounts, posts: [post], intelligence: {} } }), deps);
  const header = withPost.slice(0, withPost.indexOf('</header>'));
  assert.doesNotMatch(header, /metric-window/, 'the D1/D3/D7 picker belongs to the post card, not the page');
  assert.match(withPost, /<section class="panel post-panel[^"]*"[^>]*>(?:(?!<\/section>).)*<div class="post-metrics-head"><div class="listbox metric-window" data-listbox><span class="listbox-label" id="metric-window-label">数据<\/span><input type="hidden" id="metric-window" value="latest">/);
  assert.match(html, /<div class="overview-layout"><div class="overview-main">.*<div class="overview-side">/);
  assert.match(html, /<button type="button" class="button" data-note-new>写便签<\/button>/);
});

test('the today strip lists only things that have data', () => {
  assert.doesNotMatch(dashboard.renderOverview(desk(), deps), /today-strip/);
  const notes = { ropes: [{ name: '随手记', notes: [
    { id: 'a', rope: '随手记', text: '今天', date: '2026-10-22' },
    { id: 'b', rope: '随手记', text: '前天', date: '2026-10-20' },
    { id: 'c', rope: '随手记', text: '没日期', date: '' },
  ] }] };
  const works = [{ id: 'w1', status: 'ready', title: '甲' }, { id: 'w5', status: 'ready', title: '乙' }, { id: 'w2', status: 'cut', title: '四季豆牛肉' }, { id: 'w3', status: 'published' }, { id: 'w4', status: 'wip' }];
  const intelligence = {
    news: [{ title: '新', published_at: '2026-10-19' }, { title: '旧', published_at: '2026-09-01' }],
    candidates: [{ title: 'live', status: 'candidate', expires_at: '2026-10-30' }, { title: 'gone', status: 'candidate', expires_at: '2026-10-01' }],
  };
  const html = dashboard.renderOverview(desk({ notes, allWorks: works, dashboard: { accounts: akAccounts, posts: [], intelligence } }), deps);
  const start = html.indexOf('<section class="today-strip"');
  const strip = html.slice(start, html.indexOf('</section>', start));
  assert.match(strip, /<h2 id="today-title" class="today-title">今天 <span class="today-date">10月22日 周四<\/span><\/h2>/);
  assert.match(strip, /href="#notes"><span class="today-value">1<\/span><span class="today-label">张便签今天到期<\/span>/);
  assert.match(strip, /<span class="today-value">1<\/span><span class="today-label">张便签过了日期还没撤下<\/span>/);
  assert.match(strip, /<a class="today-item" href="#works\?status=ready"><span class="today-value">2<\/span><span class="today-label">件待发布<\/span><\/a>/, 'several works open the library filtered to them');
  assert.match(strip, /<button type="button" class="today-item" data-work="w2"><span class="today-value">1<\/span><span class="today-label">件已成片还没发布<\/span><span class="today-detail">四季豆牛肉<\/span><\/button>/, 'a single work opens directly');
  assert.match(strip, /href="#analytics"><span class="today-value">10\/06<\/span><span class="today-label">最近一次记录数据<\/span><span class="chip" data-tone="warn">16 天没更新<\/span>/);
  assert.match(strip, /<a class="today-item" href="#intelligence\?tab=news" data-intel-page-tab="news"><span class="today-value">2<\/span><span class="today-label">条新情报<\/span><span class="today-detail">官方动态 1 · 市场线索 1<\/span><\/a>/);
  const research = dashboard.todayHTML(desk({ dashboard: { accounts: [], intelligence: { research: [{ title: 'a', published_at: '2026-10-19' }, { title: 'b', published_at: '2026-10-19' }] } } }), deps);
  assert.match(research, /href="#intelligence\?tab=research" data-intel-page-tab="research"><span class="today-value">2<\/span><span class="today-label">条新研究资料<\/span>/, 'one kind of news links straight to its tab');
  const fresh = dashboard.todayHTML(desk({ today: '2026-10-08', dashboard: { accounts: akAccounts } }), deps);
  assert.match(fresh, /最近一次记录数据/);
  assert.doesNotMatch(fresh, /data-tone="warn"/);
  assert.doesNotMatch(fresh, /便签|成片|情报/);
});

test('最近作品 draws each work with the shared card, so the client tag comes along', () => {
  const works = [{ id: 'w1', client: 'AK', status: 'published' }, { id: 'w2', client: '自家', status: 'wip' }, { id: 'w3', client: 'AK', status: 'wip' }, { id: 'w4', client: '示例创作者', status: 'wip' }, { id: 'w5', client: 'AK', status: 'wip' }];
  const seen = [];
  const tagged = { ...deps, cardHTML: (work) => { seen.push(work.id); return `<article class="work-card" data-id="${work.id}"><span class="client-tag">${work.client}</span></article>`; } };
  const html = dashboard.workPreviewHTML(desk({ allWorks: works }), tagged);
  assert.deepEqual(seen, ['w1', 'w2', 'w3', 'w4'], 'the newest four, each handed to the card alone');
  assert.match(html, /<div class="works-grid"><article class="work-card" data-id="w1"><span class="client-tag">AK<\/span><\/article>/);
  assert.match(html, /<h2 class="panel-title" id="recent-works-title">最近作品<\/h2>/);
});

test('first run shows a welcome card with steps checked from real data until dismissed or data arrives', () => {
  const html = dashboard.renderOverview(desk({ allWorks: [{ id: 'w', status: 'wip' }] }), deps);
  assert.match(html, /<section class="welcome-card" aria-labelledby="welcome-title">/);
  assert.match(html, /<button type="button" class="text-action" data-action="dismiss-welcome">先不用<\/button>/);
  const step = (title) => html.match(new RegExp(`<li class="welcome-step" data-done="(true|false)">(?:(?!</li>).)*${title}</strong></div><(?:a|button)[^>]*?(?: href="([^"]*)")?>`));
  assert.equal(step('选好工作区')?.[1], 'true');
  assert.equal(step('收进第一件作品')?.[1], 'true');
  // Accounts and data are added from 设置 › 账号与数据: their nav entries stay hidden until there is something behind them.
  assert.deepEqual(step('写下要管理的账号')?.slice(1), ['false', '#settings?section=accounts']);
  assert.deepEqual(step('导入平台数据')?.slice(1), ['false', '#settings?section=accounts']);
  assert.doesNotMatch(html, /welcome-step(?:(?!<\/li>).)*#tools\?name=/, 'no step opens a tool page directly');
  assert.match(html, /<a class="button small primary" href="#settings\?section=accounts">/, 'the first step still to do is the main action');
  assert.match(html, /<span class="sr-only">已完成：<\/span>选好工作区/);
  assert.match(html, /<li class="welcome-step" data-done="false">(?:(?!<\/li>).)*data-note-new>写便签<\/button><\/li>/);
  // Each step is its title and its button; the card has no intro sentence.
  assert.match(html, /<div class="welcome-step-text"><strong>写下要管理的账号<\/strong><\/div><a class="button small primary" href="#settings\?section=accounts">账号与数据<\/a>/);
  assert.match(html, /<h2 id="welcome-title">从这几步开始<\/h2><ol class="welcome-steps">/);
  assert.match(html, /class="ghost-mark"/);
  assert.doesNotMatch(dashboard.renderOverview(desk({ welcomeDismissed: true }), deps), /welcome-card/);
  assert.doesNotMatch(dashboard.renderOverview(desk({ dashboard: { accounts: akAccounts, posts: [], intelligence: {} } }), deps), /welcome-card/);
  assert.match(dashboard.renderOverview(desk({ dashboard: { accounts: [akAccounts[1]], posts: [], intelligence: {} } }), deps), /welcome-card/, 'accounts without any data still need the import step');
  assert.doesNotMatch(dashboard.renderOverview(desk({ dashboard: null, dashboardError: '读不到' }), deps), /welcome-card/);
});

test('empty desk panels say what is missing in one line and offer one action', () => {
  const html = dashboard.renderOverview(desk({ welcomeDismissed: true }), deps);
  assert.match(html, /<strong>还没有账号<\/strong><a class="button primary" href="#tools\?name=accounts">添加账号<\/a>/);
  assert.match(html, /<strong>工作区里还没有作品<\/strong><a class="button primary" href="#works">打开资产库<\/a>/);
  assert.match(html, /<div class="panel-head"><h2 class="panel-title" id="recent-works-title">最近作品<\/h2><\/div>/, 'no 工作区 · N 件 caption under the panel title');
  assert.doesNotMatch(html, /intelligence-rail|核对日期未知/, 'no intel at all: the rail steps aside instead of offering a refresh that cannot help');
  assert.match(dashboard.renderIntelligence(desk(), deps), /<strong>还没有官方动态<\/strong><button type="button" class="button small" data-action="refresh">刷新<\/button>/, 'the 情报 page names what is missing and offers a refresh');
  assert.match(dashboard.renderOverview(desk({ welcomeDismissed: true, loading: true }), deps), /正在读取作品/);
  const noPosts = dashboard.renderOverview(desk({ dashboard: { accounts: akAccounts, posts: [], intelligence: {} } }), deps);
  assert.match(noPosts, /<strong>AK Instagram 还没有内容记录<\/strong><a class="button primary" href="#tools\?name=data">导入数据<\/a>/);
  assert.match(dashboard.renderOverview(desk({ dashboardLoading: true, dashboard: null }), deps), /aria-busy="true".*skeleton/);
});

test('intel puts new and active items first, names platforms and saves any item as a note', () => {
  const intelligence = {
    as_of: '2026-10-20',
    news: [
      { title: '旧闻', source: 'Meta', published_at: '2026-09-01', url: 'https://example.com/old' },
      { title: '新闻', source: 'Meta', published_at: '2026-10-19', summary: '摘要 <b>', url: 'https://example.com/new' },
    ],
    candidates: [
      { title: 'old_lead', platform: 'cross_platform', status: 'expired', captured_at: '2026-09-01', expires_at: '2026-09-02' },
      { title: 'fresh_lead', platform: 'youtube', status: 'candidate', captured_at: '2026-10-20', expires_at: '2026-10-30', notes: '可用' },
    ],
  };
  const page = dashboard.renderIntelligence(desk({ dashboard: { accounts: [], intelligence } }), deps);
  assert.match(page, /<h1 tabindex="-1">情报<\/h1><\/div>/, 'no sub-line: only old material earns a chip');
  assert.doesNotMatch(page, /page-sub|不是实时/);
  assert.ok(page.indexOf('新闻') < page.indexOf('旧闻'), 'newest first');
  assert.match(page, /<span class="chip" data-tone="accent">新<\/span><span>Meta · 10\/19<\/span>/);
  assert.match(page, /<button type="button" class="text-action" data-note-new data-note-text="新闻\n摘要 &lt;b&gt;\nhttps:\/\/example.com\/new">存为便签<\/button>/);
  assert.match(page, /data-intel-page-tab="candidates" aria-pressed="false">市场线索<span class="nav-count">2<\/span>/);
  assert.doesNotMatch(page, /资料停在/);
  assert.match(dashboard.renderIntelligence(desk({ today: '2026-11-01', dashboard: { accounts: [], intelligence } }), deps), /<span class="chip" data-tone="warn">资料停在 10\/20<\/span>/);
  const leads = dashboard.renderIntelligence(desk({ intelPageTab: 'candidates', dashboard: { accounts: [], intelligence } }), deps);
  assert.ok(leads.indexOf('fresh lead') < leads.indexOf('old lead'), 'active leads first');
  assert.match(leads, /<span class="chip" data-tone="ok">有效至 10\/30<\/span><span>YouTube · 10\/20<\/span>/);
  assert.match(leads, /<details class="intel-archive"><summary>1 条已失效的线索<\/summary>.*已过期<\/span><span>多平台 · 09\/01<\/span>/);
  const stale = dashboard.renderIntelligence(desk({ intelPageTab: 'candidates', dashboard: { accounts: [], intelligence: { candidates: [intelligence.candidates[0]] } } }), deps);
  assert.match(stale, /<strong>现在没有有效线索<\/strong><button type="button" class="button small" data-action="refresh">刷新<\/button><\/div><details class="intel-archive"><summary>1 条已失效的线索<\/summary>/, 'the expired lead (with its date) is right below');
  const rail = dashboard.renderOverview(desk({ dashboard: { accounts: [], posts: [], intelligence } }), deps);
  assert.doesNotMatch(rail, /不是实时订阅|intel-stale/, 'fresh material: no line under the rail');
  assert.match(dashboard.renderOverview(desk({ today: '2026-11-01', dashboard: { accounts: [], posts: [], intelligence } }), deps), /<p class="intel-stale"><span class="chip" data-tone="warn">资料停在 10\/20<\/span><\/p>/);
  assert.match(rail, /<strong>1 条有效线索<\/strong><small>共 2 条记录<\/small>/);
  assert.match(rail, /<a class="text-action" href="#intelligence\?tab=candidates" data-intel-page-tab="candidates">查看线索 <\/a>/, 'the leads card lands on the 市场线索 tab');
  assert.match(rail, /<a class="text-action" href="#intelligence\?tab=news" data-intel-page-tab="news">全部 <\/a>/);
  assert.match(rail, /<a href="https:\/\/example.com\/new" target="_blank" rel="noopener noreferrer" title="在浏览器打开">新闻<span class="sr-only">（在浏览器打开）<\/span>/, 'browser links say they leave SPT');
});

test('raw intel states read as plain Chinese', () => {
  assert.equal(dashboard.intelStateText('此前已核官方资料'), '对照过官方原文');
  assert.equal(dashboard.intelStateText('待用'), '还没用上');
  assert.equal(dashboard.intelStateText('已用'), '用过了');
  assert.equal(dashboard.intelStateText('观察中'), '观察中');
  const page = dashboard.renderIntelligence(desk({ dashboard: { accounts: [], intelligence: { news: [{ title: '旧闻', source: 'Meta', published_at: '2026-10-13', state: '此前已核官方资料' }] } } }), deps);
  assert.match(page, /<span>Meta · 10\/13 · 对照过官方原文<\/span>/);
  assert.doesNotMatch(page, /此前已核官方资料/);
});

test('platform names and chart series come from one helper each', () => {
  assert.equal(dashboard.platformLabel('google_business_profile', deps), 'Google 商家资料');
  assert.equal(dashboard.platformLabel('xiaohongshu', deps), 'rednote');
  assert.equal(dashboard.platformLabel('cross_platform', deps), '多平台');
  assert.equal(dashboard.platformLabel('some_new_site', deps), 'some new site');
  assert.equal(dashboard.platformLabel('', deps), '');
  assert.equal(dashboard.seriesKey('xiaohongshu'), 'rednote');
  assert.equal(dashboard.seriesKey('google_business_profile'), 'google');
  assert.equal(dashboard.seriesKey('Instagram'), 'instagram');
  assert.equal(dashboard.seriesKey('mastodon'), 'other');
  assert.equal(dashboard.seriesKey(undefined), 'other');
  assert.equal(dashboard.staleDays('2026-10-15', '2026-10-22'), 7, 'a week since the last record is due');
  assert.equal(dashboard.staleDays('2026-10-16', '2026-10-22'), 0, 'six days is not');
  assert.equal(dashboard.latestSample(akAccounts), '2026-10-06');
});

test('dates that are not dates never reach the page unescaped', () => {
  const accounts = [{ id: 'x:instagram', brand_id: 'x', brand: 'X', platform: 'instagram', platform_label: 'Instagram', as_of: '<img src=x onerror=alert(1)>', metrics: { followers: 1 }, history: [] }];
  const posts = [
    { id: 'p', account_id: 'x:instagram', current: true, title: '一', published_at: '<i>p</i>' },
    { id: 'q', account_id: 'x:instagram', current: true, title: '二', published_at: '<i>q</i>' },
  ];
  const html = dashboard.renderOverview(desk({ dashboard: { accounts, posts, intelligence: {} } }), deps);
  assert.doesNotMatch(html, /<img src=x|<i>p<\/i>|<i>q<\/i>/);
  assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/);
});

const igPost = (id, day, metrics = null, extra = {}) => ({ id, account_id: 'ak:instagram', current: true, title: `内容${id}`, published_at: day, ...(metrics ? { metric_window: 'D1', metrics, metrics_by_window: { D1: metrics } } : {}), ...extra });

test('a number on its own reads as a menu number, not as part of a ranking', () => {
  assert.equal(dashboard.postTitle({ title: '046' }), '编号 046');
  assert.equal(dashboard.postTitle({ title: '扬州炒饭' }), '扬州炒饭');
});

test('a post without numbers says in one line when they can be recorded', () => {
  assert.equal(dashboard.captureHint({ published_at: '2026-10-21' }, '2026-10-22'), '还没有记录数据。D1 今天记；D3 在 10/24，D7 在 10/28。');
  assert.equal(dashboard.captureHint({ published_at: '2026-10-20' }, '2026-10-22'), '还没有记录数据。D1（10/21）已经过了；D3 在 10/23，D7 在 10/27。');
  assert.equal(dashboard.captureHint({ published_at: '2026-10-15' }, '2026-10-22'), '还没有记录数据。D1、D3 已经过了；D7 今天记。');
  assert.match(dashboard.captureHint({ published_at: '2026-10-01' }, '2026-10-22'), /超过 7 天/);
  assert.match(dashboard.captureHint({ published_at: '<i>x</i>' }, '2026-10-22'), /发布日期不详/);
  const html = dashboard.renderOverview(desk({ dashboard: { accounts: akAccounts, posts: [igPost('a', '2026-10-21')], intelligence: {} } }), deps);
  assert.match(html, /<p class="metric-empty">还没有记录数据。D1 今天记；D3 在 10\/24，D7 在 10\/28。<\/p>/);
  assert.doesNotMatch(html, /class="post-metrics"|metric-window/, 'no grid of dashes and no window picker without numbers');
  const otherWindow = dashboard.renderOverview(desk({ window: 'D7', dashboard: { accounts: akAccounts, posts: [igPost('b', '2026-10-01', { views: 13 })], intelligence: {} } }), deps);
  assert.match(otherWindow, /<p class="metric-empty">D7 没有记下数字。D1 有，换过去看。<\/p>/);
});

test('the post list shows at most six rows, keeps the open post in it and marks it', () => {
  const posts = Array.from({ length: 9 }, (_, index) => igPost(`p${index}`, `2026-10-${String(20 - index).padStart(2, '0')}`, index === 7 ? { views: 50 } : null));
  const html = dashboard.renderOverview(desk({ dashboard: { accounts: akAccounts, posts, intelligence: {} } }), deps);
  const list = html.slice(html.indexOf('<ul class="post-list"'), html.indexOf('</ul>', html.indexOf('<ul class="post-list"')));
  assert.equal((list.match(/<li>/g) || []).length, 6);
  assert.match(list, /^<ul class="post-list" aria-label="AK Instagram的内容">/);
  assert.match(list, /<button type="button" class="post-select" data-post="p7" aria-current="true"><span>内容p7<\/span><small>10\/13<\/small><span class="post-current">正在看<\/span><\/button><\/li>$/, 'the post with numbers is open by default and takes the last row');
  assert.equal((list.match(/aria-current/g) || []).length, 1);
  assert.doesNotMatch(list, /data-post="p5"/);
  assert.match(html, /<div class="post-list-foot"><span class="source-caption">共 9 条<\/span><a class="text-action" href="#analytics" data-analytics-platform="instagram">全部 <\/a><\/div>/);
  assert.doesNotMatch(html, /条来源记录|最近 6 条/);
  const top = dashboard.renderOverview(desk({ postId: 'p1', dashboard: { accounts: akAccounts, posts, intelligence: {} } }), deps);
  assert.match(top, /data-post="p1" aria-current="true"/);
  assert.match(top, /data-post="p5">/, 'a post near the top leaves the six newest in place');
  const few = dashboard.renderOverview(desk({ dashboard: { accounts: akAccounts, posts: posts.slice(0, 3), intelligence: {} } }), deps);
  assert.match(few, /<ul class="post-list"/);
  assert.doesNotMatch(few, /post-list-foot/, 'everything is listed: no count and no 全部 link');
});

test('platforms without data fold into one line under their client, Meta Business Suite stays on the client row', () => {
  const accounts = [
    { ...akAccounts[0], legacy_account_id: 'ig' },
    { ...akAccounts[1] },
    { id: 'ak:yelp', brand_id: 'ak', brand: 'AK', platform: 'yelp', platform_label: 'Yelp', readonly: true, metrics: {}, history: [] },
  ];
  const html = dashboard.renderOverview(desk({ dashboard: { accounts, posts: [], intelligence: {} } }), deps);
  assert.match(html, /<div class="account-group-header"><div class="client-text"><span class="client-name">AK<\/span><span class="client-meta">3 个平台 · 10\/06<\/span><\/div><button type="button" class="meta-suite-link"[^>]*><span class="meta-mark" aria-hidden="true"><\/span>Meta<span class="meta-suite-more"> Business Suite<\/span><\/button><\/div>/);
  assert.match(html, /<details class="account-empty" data-fold="ak"><summary><span class="account-empty-marks" aria-hidden="true">(?:(?!<\/summary>).)*<span class="account-empty-text">TikTok、Yelp<\/span><small>还没有数据<\/small><\/summary><div class="account-list">(?:(?!<\/details>).)*data-account="ak:tiktok"(?:(?!<\/details>).)*data-account="ak:yelp"/);
  assert.equal((html.match(/data-account="ak:instagram"/g) || []).length, 1);
  assert.ok(html.indexOf('data-account="ak:instagram"') < html.indexOf('<details class="account-empty"'), 'accounts with data stay on top');
  const open = dashboard.renderOverview(desk({ accountId: 'ak:tiktok', dashboard: { accounts, posts: [], intelligence: {} } }), deps);
  assert.match(open, /<details class="account-empty" data-fold="ak" open>/, 'opened while one of its accounts is selected');
});

test('today keeps one data item: the last sample, flagged after a week, opening 数据导入 when the server has it', () => {
  // Per-post numbers come from a weekly pipeline: a post due for D1 today is not asked for by hand.
  const tracked = igPost('old', '2026-10-01', { views: 10 });
  const data = { accounts: akAccounts, posts: [tracked, igPost('d1', '2026-10-21', null, { work_id: 'w1' }), igPost('d7', '2026-10-15')] };
  const strip = dashboard.todayHTML(desk({ dashboard: data }), deps);
  assert.equal(dashboard.dueCaptures, undefined);
  assert.doesNotMatch(strip, /该记|D1|D7/);
  assert.equal((strip.match(/today-item/g) || []).length, 1);
  assert.match(strip, /<a class="today-item" href="#analytics"><span class="today-value">10\/06<\/span><span class="today-label">最近一次记录数据<\/span><span class="chip" data-tone="warn">16 天没更新<\/span><\/a>/, 'without the import tool the item opens 数据');
  const withTool = { ...deps, dataURL: () => '#tools?name=data' };
  assert.match(dashboard.todayHTML(desk({ dashboard: data }), withTool), /<a class="today-item" href="#tools\?name=data"><span class="today-value">10\/06<\/span>/);
  assert.equal(dashboard.CAPTURE_WEEK_DAYS, 7);
  const chip = (today) => dashboard.todayHTML(desk({ today, dashboard: { accounts: akAccounts } }), deps).match(/<span class="chip" data-tone="warn">([^<]*)<\/span>/)?.[1] || '';
  assert.equal(chip('2026-10-09'), '', '3 days: the weekly pipeline is on time');
  assert.equal(chip('2026-10-12'), '', '6 days');
  assert.equal(chip('2026-10-13'), '7 天没更新');
  assert.equal(chip('2026-10-20'), '14 天没更新');
});

test('an empty workspace leads with the welcome card and leaves out empty panels', () => {
  const html = dashboard.renderOverview(desk(), deps);
  assert.match(html, /<section class="welcome-card"/);
  assert.match(html, /<div class="overview-layout is-sparse">/);
  assert.doesNotMatch(html, /accounts-panel|works-preview|intelligence-rail|核对日期未知|data-action="refresh"/);
  const withWork = dashboard.renderOverview(desk({ allWorks: [{ id: 'w', status: 'wip', title: '作品' }] }), deps);
  assert.match(withWork, /works-preview/, 'panels with something in them stay');
});

// ---- 工作区记的数据（作品文件夹里的 数据/）----
const rednoteA = { id: 'parenting:rednote', brand_id: 'parenting', brand: '示例创作者', name: '示例创作者', platform: 'rednote', platform_label: 'rednote', handle: 'https://www.rednote.com/user/profile/example', data_state: 'workspace', as_of: '2026-10-21T21:35:00-07:00', posts_count: 1, metrics: {}, history: [] };
const rednoteB = { id: 'parenting:rednote:小幽灵', brand_id: 'parenting', brand: '示例创作者', name: '小幽灵', platform: 'rednote', platform_label: 'rednote', handle: '小幽灵', data_state: 'workspace', as_of: '2026-10-20', metrics: {}, history: [] };
const wsPost = {
  id: 'ws1', account_id: 'parenting:rednote', work_id: 'w-ws', client: '示例创作者', title: '小车先停好', current: true, source_kind: 'workspace_metrics',
  published_at: '2026-09-08T20:00:00-07:00', metric_window: 'D7', observed_at: '2026-09-15T21:35:00-07:00',
  metrics: { views: 92, likes: 8, comments: 2, saves: 1, shares: 1, completion_rate: 63, ctr: 12.5, avg_watch_sec: null, reach: null },
  metrics_by_window: { D1: { views: 72, likes: 8, comments: 1, saves: 1, shares: 1 }, D3: { views: 82, likes: 8, comments: 2, saves: 1, shares: 1, completion_rate: 58.4 }, D7: { views: 92, likes: 8, comments: 2, saves: 1, shares: 1, completion_rate: 63, ctr: 12.5 } },
  metric_observed_at_by_window: { D1: '2026-09-09T20:30:00-07:00', D3: '2026-09-11T21:35:00-07:00', D7: '2026-09-15T21:35:00-07:00' },
  history: [
    { window: 'D1', observed_at: '2026-09-09T20:30:00-07:00', age_hours: 24.5, metrics: { views: 72, likes: 8, comments: 1, saves: 1, shares: 1 } },
    { window: 'D3', observed_at: '2026-09-11T21:35:00-07:00', age_hours: 76.2, metrics: { views: 82, likes: 8, comments: 2, saves: 1, shares: 1, completion_rate: 58.4 } },
    { window: null, observed_at: '2026-09-13', age_hours: 112, metrics: { views: 88 } },
    { window: 'D7', observed_at: '2026-09-15T21:35:00-07:00', age_hours: 169.6, metrics: { views: 92, likes: 8, comments: 2, saves: 1, shares: 1, completion_rate: 63, ctr: 12.5 } },
  ],
  retention: [{ at: '2026-09-15T21:35:00-07:00', platform: 'rednote', account: '示例创作者', points: [[0, 100], [3, 71.5], [10, 40], [20, 22]] }],
  analyses: [
    { path: '数据/分析/2026-09-11-D3.md', date: '2026-09-11', platform: 'rednote', account: '示例创作者', node: 'D3', conclusion: '开头 3 秒没有冲突，封面和标题重复', tags: ['开头弱', '封面'] },
    { path: '数据/分析/2026-09-16-D7.md', date: '2026-09-16', platform: 'rednote', node: 'D7', conclusion: '结尾没有引导 <b>', tags: ['结尾无引导'] },
  ],
};

test('percent values read as 63% or 12.5%, seconds as 4.5s, unknown as —', () => {
  assert.equal(dashboard.percent(63), '63%');
  assert.equal(dashboard.percent(12.5), '12.5%');
  assert.equal(dashboard.percent(null), '—');
  assert.equal(dashboard.metricText(wsPost, 'completion_rate'), '63%');
  assert.equal(dashboard.metricText(wsPost, 'ctr'), '12.5%');
  assert.equal(dashboard.metricText(wsPost, 'completion_rate', 'D3'), '58.4%');
  assert.equal(dashboard.metricText(wsPost, 'completion_rate', 'D1'), '—');
  assert.equal(dashboard.metricText(wsPost, 'avg_watch_sec'), '—');
  assert.equal(dashboard.metricText({ metrics: { avg_watch_sec: 4.5, three_sec_rate: 70 } }, 'avg_watch_sec'), '4.5s');
  assert.equal(dashboard.metricText({ metrics: { three_sec_rate: 70 } }, 'three_sec_rate'), '70%');
  const local = new Date('2026-09-12T04:35:00Z'); const two = (n) => String(n).padStart(2, '0');
  assert.equal(dashboard.shortTime('2026-09-12T04:35:00+00:00'), `${two(local.getMonth() + 1)}/${two(local.getDate())} ${two(local.getHours())}:${two(local.getMinutes())}`, 'times with a zone are shown in local time');
  assert.equal(dashboard.shortTime('2026-09-11 21:35'), '09/11 21:35', 'a time without a zone is shown as written');
  assert.equal(dashboard.shortTime('2026-09-13'), '09/13');
  assert.equal(dashboard.shortTime(''), '—');
});

test('two accounts of one client on the same platform carry the handle in their label; one alone keeps the platform name', () => {
  const both = [rednoteA, rednoteB, akAccounts[0]];
  assert.equal(dashboard.accountLabel(rednoteA, both, deps), 'rednote · 示例创作者', 'a profile-link handle falls back to the account name');
  assert.equal(dashboard.accountLabel(rednoteB, both, deps), 'rednote · 小幽灵');
  assert.equal(dashboard.accountLabel(rednoteA, [rednoteA, akAccounts[0]], deps), 'rednote');
  assert.equal(dashboard.accountLabel(akAccounts[0], both, deps), 'Instagram');
  assert.equal(dashboard.accountLabel(rednoteA, [], deps), 'rednote');
  assert.equal(dashboard.accountLabel({ platform: 'douyin' }, [], deps), '抖音');
  const state = desk({ accountId: 'parenting:rednote', dashboard: { accounts: both, posts: [wsPost], intelligence: {} } });
  const html = dashboard.renderOverview(state, deps);
  assert.match(html, /aria-label="查看示例创作者 rednote · 示例创作者的内容"/);
  assert.match(html, /aria-label="查看示例创作者 rednote · 小幽灵的内容"/);
  assert.match(html, /<span class="account-platform">rednote · 示例创作者<\/span>/);
  assert.match(html, /<span class="account-platform">Instagram<\/span>/, 'the lone Instagram account is just Instagram');
  assert.match(html, /<div class="source-caption">rednote · 示例创作者 · 09\/08<\/div>/, 'the post card names the account the same way');
  assert.match(dashboard.accountBackendHTML({ ...rednoteA, legacy_account_id: 'rn1' }, state, deps, true), /aria-label="在 SPT 应用中打开：示例创作者 rednote · 示例创作者"/);
  assert.match(dashboard.accountBackendHTML({ ...rednoteA, legacy_account_id: 'rn1' }, state, deps), /aria-label="打开示例创作者 rednote · 示例创作者官方后台"/);
  const dialog = dashboard.postDialogHTML(wsPost, rednoteA, state, deps);
  assert.match(dialog, /<div class="detail-meta">示例创作者 · rednote · 示例创作者 · \d{2}\/\d{2} \d{2}:\d{2}<\/div>/);
});

test('workspace accounts with a recorded date sit with the other accounts and show their numbers', () => {
  const html = dashboard.renderOverview(desk({ accountId: 'parenting:rednote', dashboard: { accounts: [rednoteA, akAccounts[1]], posts: [wsPost], intelligence: {} } }), deps);
  assert.ok(html.indexOf('data-account="parenting:rednote"') < html.indexOf('<details class="account-empty"'), 'not folded under 还没有数据');
  assert.match(html, /data-account="parenting:rednote"(?:(?!<\/button>).)*<small>10\/21<\/small>/, 'its as_of date, not 未采集');
  assert.match(html, /<details class="account-empty" data-fold="ak">(?:(?!<\/details>).)*data-account="ak:tiktok"/);
  assert.match(html, /<span class="metric-label">浏览<\/span><strong class="metric-value">92<\/strong>/);
  assert.match(html, /<span class="metric-label">完播率<\/span><strong class="metric-value">63%<\/strong>/);
  assert.match(html, /<span class="metric-label">点击率<\/span><strong class="metric-value">12.5%<\/strong>/);
  assert.doesNotMatch(html, /平均观看秒|触达/, 'unrecorded extras stay out of the grid');
  assert.match(html, /<p class="metric-period">D7 · 09\/15 记录<\/p>/);
  const d1 = dashboard.renderOverview(desk({ window: 'D1', accountId: 'parenting:rednote', dashboard: { accounts: [rednoteA], posts: [wsPost], intelligence: {} } }), deps);
  assert.match(d1, /<span class="metric-label">浏览<\/span><strong class="metric-value">72<\/strong>/);
  assert.doesNotMatch(d1, /完播率/, 'D1 recorded no rate');
});

test('今天 takes the newest record across all accounts, workspace ones included', () => {
  assert.equal(dashboard.latestSample([akAccounts[0], rednoteA]), '2026-10-21');
  assert.equal(dashboard.latestSample([rednoteB, akAccounts[0]]), '2026-10-20');
  const strip = dashboard.todayHTML(desk({ dashboard: { accounts: [akAccounts[0], rednoteA], posts: [] } }), deps);
  assert.match(strip, /<span class="today-value">10\/21<\/span><span class="today-label">最近一次记录数据<\/span>/);
  assert.doesNotMatch(strip, /天没更新/, 'a day old is not stale');
});

test('the post dialog lays out every observation, the latest retention curve and the analyses with tag links', () => {
  const html = dashboard.postDialogHTML(wsPost, rednoteA, desk({ dashboard: { accounts: [rednoteA], posts: [wsPost] } }), deps);
  assert.match(html, /<div class="table-wrap"><table class="data-table metric-timeline">/, 'scrolls inside its wrapper on a phone');
  const start = html.indexOf('<table class="data-table metric-timeline">');
  const table = html.slice(start, html.indexOf('</table>', start));
  assert.match(table, /<thead><tr><th scope="col">记录时间<\/th><th scope="col" class="num">距发布<\/th><th scope="col" class="num">浏览<\/th><th scope="col" class="num">赞<\/th><th scope="col" class="num">评论<\/th><th scope="col" class="num">收藏<\/th><th scope="col" class="num">分享<\/th><th scope="col" class="num">完播率<\/th><th scope="col">节点<\/th><\/tr><\/thead>/);
  assert.equal((table.slice(table.indexOf('<tbody>')).match(/<tr>/g) || []).length, 4);
  assert.match(table, /<th scope="row">09\/09 20:30<\/th><td class="num">25 h<\/td><td class="num">72<\/td><td class="num">8<\/td><td class="num">1<\/td><td class="num">1<\/td><td class="num">1<\/td><td class="num">—<\/td><td><span class="chip node-chip" data-tone="accent">D1<\/span><\/td>/, 'half an hour is not late');
  assert.match(table, /<th scope="row">09\/11 21:35<\/th><td class="num">76 h<\/td>(?:(?!<\/tr>).)*<td class="num">58.4%<\/td><td><span class="chip node-chip" data-tone="warn">D3 晚 4h<\/span><\/td>/);
  assert.match(table, /<th scope="row">09\/13<\/th><td class="num">112 h<\/td><td class="num">88<\/td>(?:<td class="num">—<\/td>){5}<td><\/td>/, 'a record between nodes has no badge');
  assert.match(table, /D7 晚 2h/);
  assert.ok(table.indexOf('09/09') < table.indexOf('09/15'), 'oldest first, like a timeline');
  assert.match(html, /<section class="retention"><h3>留存<span class="verification"> 09\/15<\/span><\/h3><svg class="retention-chart series series-rednote" viewBox="0 0 320 110" preserveAspectRatio="none" role="img" aria-label="留存：0 秒 100%，3 秒 71.5%，10 秒 40%，20 秒 22%">/);
  assert.match(html, /<circle class="dot"[^>]*><title>3 秒：71.5%<\/title><\/circle>/);
  assert.match(html, /<div class="chart-labels"><span>0s 100%<\/span><span>3s 71.5%<\/span><span>10s 40%<\/span><span>20s 22%<\/span><\/div>/);
  assert.doesNotMatch(html, /#[0-9a-f]{6}\b|stroke="|fill="|style="/i, 'colours stay in CSS');
  assert.match(html, /<section class="analyses"><h3>分析<span class="verification"> 2<\/span><\/h3><ul class="analysis-list">/);
  const href = ui.esc(dashboard.tagHash('开头弱'));
  assert.equal(dashboard.tagHash('开头弱'), `#analytics?view=tags&tag=${encodeURIComponent('开头弱')}`);
  assert.ok(html.includes(`<li class="analysis-item"><div class="analysis-meta">09/11 · D3</div><p>开头 3 秒没有冲突，封面和标题重复</p><div class="chip-row"><a class="chip tag-chip" href="${href}" data-analysis-tag="开头弱">开头弱</a><a class="chip tag-chip" href="${ui.esc(dashboard.tagHash('封面'))}" data-analysis-tag="封面">封面</a></div></li>`));
  assert.match(html, /结尾没有引导 &lt;b&gt;/);
  assert.ok(html.indexOf('metric-timeline') < html.indexOf('class="retention"') && html.indexOf('class="retention"') < html.indexOf('class="analyses"') && html.indexOf('class="analyses"') < html.indexOf('post-source'), 'numbers, curve, analyses, then the source details');
  assert.match(html, /<details class="post-source"><summary>来源与采样<\/summary>/, 'the source details stay');
  const legacy = dashboard.postDialogHTML({ id: 'l', title: 'x', metric_window: 'D3', metrics: { views: 1 }, history: [{ window: 'D3', observed_at: '2026-10-02', metrics: { views: 1 } }] }, {}, { window: 'latest' }, deps);
  assert.doesNotMatch(legacy, /metric-timeline|class="retention"|class="analyses"/, 'imported posts keep their old dialog');
  assert.equal(dashboard.retentionHTML([{ at: '2026-10-01', points: [[0, 100]] }], 'rednote', deps), '', 'one point is not a curve');
  assert.equal(dashboard.analysesHTML([], deps), '');
});

test('the work dialog 数据 block: latest numbers, D1/D3/D7 cells (— when missing) and the analyses', () => {
  const metrics = {
    observations: [
      { at: '2026-09-09T20:30:00-07:00', age_hours: 24.5, platform: 'rednote', account: '示例创作者', metrics: { views: 72, likes: 8, comments: 1, saves: 1, shares: 1 }, source: '原始快照/a.json', note: '' },
      { at: '2026-09-11T21:35:00-07:00', age_hours: 76.2, platform: 'rednote', account: '示例创作者', metrics: { views: 82, likes: 8, comments: 2, saves: 1, shares: 1, completion_rate: 58.4 }, source: '', note: 'D3 晚到 4.2 小时' },
    ],
    nodes: { D1: { at: '2026-09-09T20:30:00-07:00', age_hours: 24.5, late_hours: 0.5, metrics: { views: 72 } }, D3: { at: '2026-09-11T21:35:00-07:00', age_hours: 76.2, late_hours: 4.2, metrics: { views: 82 } }, D7: null },
    latest: { at: '2026-09-11T21:35:00-07:00', age_hours: 76.2, metrics: { views: 82, likes: 8, comments: 2, saves: 1, shares: 1, completion_rate: 58.4 } },
    retention: [],
    analyses: [{ path: '数据/分析/2026-09-11-D3.md', date: '2026-09-11', node: 'D3', conclusion: '开头弱', tags: ['开头弱'], body: '## 现象\n…' }],
  };
  const html = dashboard.workMetricsHTML(metrics, deps);
  assert.match(html, /^<div class="work-metrics"><div class="post-metrics"><div><span class="metric-label">浏览<\/span><strong class="metric-value">82<\/strong><\/div>/);
  assert.match(html, /<span class="metric-label">完播率<\/span><strong class="metric-value">58.4%<\/strong><\/div><\/div><p class="metric-period">09\/11 21:35 记录 · 发布后 76 h<\/p>/);
  assert.match(html, /<div class="node-cells"><div class="node-cell"><span class="metric-label">D1<\/span><strong>72<\/strong><small>09\/09<\/small><\/div><div class="node-cell"><span class="metric-label">D3<\/span><strong>82<\/strong><small>09\/11 · 晚 4h<\/small><\/div><div class="node-cell empty"><span class="metric-label">D7<\/span><strong>—<\/strong><\/div><\/div>/);
  assert.match(html, /<table class="data-table metric-timeline">/, 'two or more records: the timeline too');
  assert.ok(html.includes(`<section class="analyses"><h3>分析<span class="verification"> 1</span></h3><ul class="analysis-list"><li class="analysis-item"><div class="analysis-meta">09/11 · D3</div><p>开头弱</p><div class="chip-row"><a class="chip tag-chip" href="${ui.esc(dashboard.tagHash('开头弱'))}" data-analysis-tag="开头弱">开头弱</a></div></li></ul></section>`));
  assert.doesNotMatch(html, /## 现象/, 'bodies stay in the file');
  assert.equal(dashboard.workMetricsHTML(null, deps), '<p class="small-empty">这件作品还没有记录数据。</p>');
  assert.equal(dashboard.workMetricsHTML({ observations: [], nodes: {}, latest: null, analyses: [] }, deps), '<p class="small-empty">这件作品还没有记录数据。</p>');
  const one = dashboard.workMetricsHTML({ observations: [metrics.observations[0]], nodes: { D1: metrics.nodes.D1 }, latest: null, analyses: [] }, deps);
  assert.match(one, /<strong class="metric-value">72<\/strong>/, 'without a latest block the last observation stands in');
  assert.doesNotMatch(one, /metric-timeline/, 'a single record needs no timeline');
  assert.equal(dashboard.lateHours('D3', 76.2), 4);
  assert.equal(dashboard.lateHours('D1', 24.5), 0);
  assert.equal(dashboard.lateHours('D7', 169.6, 1.6), 2);
  assert.equal(dashboard.lateHours('D7', null), 0);
  assert.equal(dashboard.lateHours('周', 300), 0);
});

test('a plain browser (no SPT app bridge) opens the official backends in a new tab instead', () => {
  assert.equal(ui.inBrowser({}), true);
  assert.equal(ui.inBrowser({ mediaNativeAvailable: true }), false);
  assert.equal(ui.inBrowser({ webkit: { messageHandlers: {} } }), false, 'an older SPT app keeps its buttons');
  assert.equal(ui.officialURL('rednote'), 'https://creator.rednote.com/new/note-manager');
  assert.equal(ui.officialURL('meta_suite'), 'https://business.facebook.com/latest/home');
  assert.equal(ui.officialURL('yelp'), 'https://biz.yelp.com/');
  assert.equal(ui.officialURL('__proto__'), '');
  const browser = { ...deps, browser: () => true, officialURL: ui.officialURL, nativeAvailable: () => false };
  const rednote = { id: 'parenting:rednote', brand: '示例创作者', platform: 'rednote', platform_label: 'rednote', legacy_account_id: 'rn1' };
  const full = dashboard.accountBackendHTML(rednote, {}, browser);
  assert.match(full, /^<a class="button small" href="https:\/\/creator\.rednote\.com\/new\/note-manager" target="_blank" rel="noopener noreferrer"/);
  assert.match(full, />官方后台<\/a>$/);
  assert.doesNotMatch(full, /data-open-account|在 SPT 应用中打开|rn1/);
  const compact = dashboard.accountBackendHTML(rednote, {}, browser, true);
  assert.match(compact, /^<a class="account-open" href="https:\/\/creator\.rednote\.com/);
  assert.equal(dashboard.accountBackendHTML({ ...rednote, platform: 'not_supported' }, {}, browser), '', 'no official backend: nothing to click');
  const meta = dashboard.metaSuiteHTML([{ id: 'ak:instagram', brand: 'AK', platform: 'instagram', legacy_account_id: 'ig1' }], {}, browser);
  assert.match(meta, /^<a class="button small" href="https:\/\/business\.facebook\.com\/latest\/home" target="_blank" rel="noopener noreferrer"/);
  assert.doesNotMatch(meta, /data-open-account/);
  // the SPT app itself is unchanged
  assert.match(dashboard.accountBackendHTML(rednote, {}, { ...deps, browser: () => false, nativeAvailable: () => true }), />官方后台<\/button>/);
});

test('设置 › Agent 接入 shows python -m commands on Windows and spt/bin on a Mac', () => {
  const mac = ui.agentCommands('/Users/a/SPT/spt', 'mac');
  assert.equal(mac.cli, '/Users/a/SPT/spt/bin/spt search 关键词');
  assert.equal(mac.mcp, 'claude mcp add spt -s user -- /Users/a/SPT/spt/bin/spt-mcp');
  assert.deepEqual(ui.agentCommands('/Users/a/SPT/spt', undefined), mac, 'an older server without platform: Mac commands');
  const base = String.raw`C:\Users\小明\SPT`;
  const python = base + String.raw`\.venv\Scripts\python.exe`;
  const windows = ui.agentCommands(base + String.raw`\spt`, 'windows');
  assert.equal(windows.cli, `cd /d "${base}" && "${python}" -m spt.server.cli search 关键词`);
  assert.equal(windows.mcp, `claude mcp add spt -s user -e PYTHONPATH="${base}" -- "${python}" -m spt.server.mcp_server`);
  assert.ok(windows.codex.includes(`command = ${JSON.stringify(python)}`));
  assert.ok(windows.codex.includes('args = ["-m", "spt.server.mcp_server"]'));
  assert.doesNotMatch(windows.cli + windows.mcp + windows.codex, /bin\/spt/);
});
