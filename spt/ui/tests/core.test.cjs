'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const ui = require('../spt.js');

test('only same-origin work media endpoints are accepted', () => {
  assert.equal(ui.safeLocalURL('/api/works/one/cover'), '/api/works/one/cover');
  assert.equal(ui.safeLocalURL('/api/works/one/file?path=V1%2F01.png'), '/api/works/one/file?path=V1%2F01.png');
  for (const url of ['https://example.com/image.png', '//example.com/api/works/one/cover', 'javascript:alert(1)', '/api/accounts', '/api/works/one/../../accounts']) {
    assert.equal(ui.safeLocalURL(url), '');
  }
});

test('file URLs encode Chinese names and cannot escape the endpoint', () => {
  assert.equal(ui.fileURL('一/二', { path: 'V3/01_编号图 #1.png' }), '/api/works/%E4%B8%80%2F%E4%BA%8C/file?path=V3%2F01_%E7%BC%96%E5%8F%B7%E5%9B%BE%20%231.png');
  assert.equal(ui.fileURL('one', { path: '成片.mp4', url: 'javascript:alert(1)' }), '/api/works/one/file?path=%E6%88%90%E7%89%87.mp4');
  assert.equal(ui.fileURL('one', { path: '成片.mp4', url: '/api/works/one/file?path=final.mp4' }), '/api/works/one/file?path=final.mp4');
});

test('historical and withdrawn records do not appear as current publication', () => {
  const records = [
    { url: 'current', current: true, state: 'current' },
    { url: 'withdrawn', current: false, state: 'withdrawn' },
    { url: 'history', state: 'history' },
    { url: 'legacy', is_current: false },
  ];
  const grouped = ui.splitRecords(records);
  assert.deepEqual(grouped.current.map((item) => item.url), ['current']);
  assert.deepEqual(grouped.historical.map((item) => item.url), ['withdrawn', 'history', 'legacy']);
});

test('adopted version does not follow highest edit number; no versions means no label', () => {
  assert.equal(ui.versionLabel({ current_version: 'V3', latest_version: 'V6' }), '定稿：V3');
  assert.equal(ui.versionLabel({ current_version: null, latest_version: 'V3' }), '最新改到 V3');
  assert.equal(ui.versionLabel({ current_version: 'Motion V10', latest_version: null }), '定稿：Motion V10');
  assert.equal(ui.versionLabel({ current_version: null, latest_version: null }), '');
  assert.equal(ui.versionLabel({}), '');
});

test('cards keep only the media mismatch warning; the publication check lives in the detail', () => {
  const work = { id: 'w1', title: '三道菜', client: 'AK', category: '运营', date: '2026-10-22', status: 'published', verified: false, media_match: 'not_applicable' };
  const card = ui.cardHTML(work);
  assert.doesNotMatch(card, /work-warning|还没核对|verified/);
  assert.doesNotMatch(card, /work-version|还没有版本/, 'a work without versions shows no version line');
  assert.match(card, /<span class="work-subtitle"><span>AK<\/span><span>2026-10-22<\/span><\/span>/, 'without a tag the subtitle shows the code');
  assert.match(card, /<span class="status published">已发布<\/span>/);
  const tagged = ui.cardHTML({ ...work, current_version: 'V4' }, '<span class="client-tag">Sample Studio</span>');
  assert.match(tagged, /<span class="work-subtitle"><span class="client-tag">Sample Studio<\/span><span>2026-10-22<\/span><\/span>/);
  assert.match(tagged, /<span class="work-version">定稿：V4<\/span>/);
  const mismatch = ui.cardHTML({ ...work, media_match: 'mismatch' });
  assert.match(mismatch, /<span class="work-warning">[^]*本地成片和发布记录里的不一样/);
  assert.equal(ui.mismatchNote(work), '');
  assert.equal(ui.mismatchNote({ media_match: 'mismatch' }), '本地成片和发布记录里的不一样');
  const row = ui.listRowHTML(work, '<span class="client-tag">Sample Studio</span>');
  assert.doesNotMatch(row, /work-warning|table-version/);
  assert.match(row, /<td><span class="client-tag">Sample Studio<\/span><\/td><td>2026-10-22<\/td>/);
  assert.match(ui.listRowHTML({ ...work, media_match: 'mismatch', latest_version: 'V2' }), /<span class="table-version">最新改到 V2<\/span><span class="work-warning">本地成片和发布记录里的不一样<\/span>/);
  assert.match(ui.listRowHTML(work), /<td>AK<\/td>/);
});

test('the 资产库 address carries client, 专业 and status, and only the keys it names come back', () => {
  const filters = { client: 'AK', category: '运营', status: 'published' };
  const hash = ui.worksHash(filters);
  assert.match(hash, /^#works\?client=AK&category=[^&]+&status=published$/);
  assert.deepEqual(ui.worksParams(new URLSearchParams(hash.split('?')[1])), filters);
  assert.equal(ui.worksHash({}), '#works');
  assert.equal(ui.worksHash({ client: '自家' }), `#works?client=${encodeURIComponent('自家')}`);
  assert.equal(ui.worksHash({ status: 'bogus' }), '#works', 'an unknown status is not written');
  assert.deepEqual(ui.worksParams(new URLSearchParams('status=wip')), { status: 'wip' }, 'absent keys are absent, not empty');
  assert.deepEqual(ui.worksParams(new URLSearchParams('client=&category=')), { client: '', category: '' }, 'an empty key clears that filter');
  assert.deepEqual(ui.worksParams(new URLSearchParams('status=nope&client=%00AK')), { status: '', client: 'AK' });
  assert.equal(ui.worksParams(new URLSearchParams(`client=${'x'.repeat(80)}`)).client.length, 60);
});

test('⌘K subtitles name the client', () => {
  const clients = [{ code: 'AK', name: 'Sample Studio', kind: 'client' }, { code: '自家', name: '自家', kind: 'own' }];
  assert.equal(ui.paletteHint({ client: 'AK', category: '运营', date: '2026-10-22' }, clients), 'Sample Studio · 2026-10-22');
  assert.equal(ui.paletteHint({ client: '新客', category: '运营', date: '2026-10-22' }, clients), '新客 · 2026-10-22', 'an unlisted code is shown as is');
  assert.equal(ui.paletteHint({ category: '电影', date: '2026-10-01' }, clients), '电影 · 2026-10-01');
  assert.equal(ui.paletteHint({ client: 'AK', section: '运营' }, clients, 'item'), 'Sample Studio · 运营');
  assert.equal(ui.paletteHint({ client: null, section: '场景' }, clients, 'item'), '场景');
  assert.equal(ui.paletteHint({}, clients, 'item'), '');
});

test('one name per destination: pages and tools', () => {
  assert.deepEqual(Object.values(ui.PAGE_NAMES), ['运营', '资产库', '便签', '数据', '情报', '发布', '设置']);
  assert.equal(ui.TOOL_NAMES.uploads, '上传素材');
  assert.equal(ui.TOOL_NAMES.studio, '编辑内容');
  assert.equal(ui.TOOL_NAMES.connections, '发布设置');
  assert.equal(ui.TOOL_NAMES.planning, '内容计划', '内容计划 keeps its name though it left the tab strip');
  // 导入数据总览 is retired: 数据 keeps only 数据导入.
  assert.equal(Object.keys(ui.TOOL_NAMES).length, 8);
  assert.equal(ui.TOOL_NAMES.overview, undefined);
  assert.deepEqual(ui.DATA_TOOLS, ['data']);
});

test('发布 sub-tabs are 平台入口 and 账号档案; the open ⋯ tool joins at the end', () => {
  // '' is 平台入口 (the official back-office entrances).
  const fixed = ['', 'accounts'];
  assert.deepEqual(ui.publishTabs(''), fixed);
  assert.deepEqual(ui.publishTabs('accounts'), fixed);
  // A tool from the ⋯ menu (and 发布设置) shows as the selected tab after 账号档案; 数据导入 belongs to 数据.
  for (const tool of ui.PUBLISH_TOOLS) assert.deepEqual(ui.publishTabs(tool), [...fixed, tool], tool);
  assert.deepEqual(ui.publishTabs('connections'), [...fixed, 'connections']);
  assert.deepEqual(ui.publishTabs('data'), fixed);
  assert.deepEqual(ui.publishTabs('overview'), fixed);
  assert.deepEqual(ui.publishTabs('nope'), fixed);
});

test('the ⋯ menu holds the editing tools 用户 does not use day to day; a shared copy has none', () => {
  assert.deepEqual(ui.PUBLISH_TOOLS, ['publish', 'studio', 'planner', 'uploads', 'planning']);
  assert.deepEqual(ui.publishMore(), ui.PUBLISH_TOOLS);
  assert.deepEqual(ui.publishMore(false), ui.PUBLISH_TOOLS);
  assert.deepEqual(ui.publishMore(true), []);
  assert.ok(!ui.publishMore().includes('accounts') && !ui.publishMore().includes('data'));
  // share comes from GET /api/health; anything but true (or no field at all) is 用户's own copy.
  assert.equal(ui.isShare({ share: true }), true);
  for (const health of [{ share: false }, { share: 'true' }, {}, null, undefined]) assert.equal(ui.isShare(health), false);
});

test('#publish opens 平台入口 itself; only the retired 导入数据总览 is redirected', () => {
  assert.equal(ui.ENTRIES_HASH, '#publish');
  assert.equal(ui.routeRedirect('publish'), '');
  assert.equal(ui.routeRedirect('publish?view=entries'), '', 'an old 平台入口 address still shows it');
  assert.equal(ui.routeRedirect(''), '', 'an empty address is 运营');
  assert.equal(ui.routeRedirect('tools?name=overview'), '#tools?name=data');
  for (const raw of ['tools?name=publish', 'tools?name=data', 'works', 'notes', 'settings']) assert.equal(ui.routeRedirect(raw), '', raw);
});

test('数据, 情报 and 发布 are listed only once the snapshot shows something behind them', () => {
  assert.deepEqual(ui.DATA_ROUTES, ['analytics', 'intelligence', 'publish']);
  assert.deepEqual(ui.hiddenRoutes(null), [], 'before the dashboard loads every entry shows');
  assert.deepEqual(ui.hiddenRoutes(undefined, { counts: {} }), []);
  const empty = { accounts: [], posts: [], intelligence: {} };
  assert.deepEqual(ui.hiddenRoutes(empty), ['analytics', 'intelligence', 'publish']);
  assert.deepEqual(ui.hiddenRoutes({}), ['analytics', 'intelligence', 'publish']);
  const bare = { id: 'a', history: [] };
  assert.deepEqual(ui.hiddenRoutes({ ...empty, accounts: [bare] }), ['analytics', 'intelligence'], 'an account without numbers opens 发布 only');
  assert.deepEqual(ui.hiddenRoutes({ ...empty, accounts: [{ ...bare, history: [{ date: '2026-10-06' }] }] }), ['intelligence']);
  assert.deepEqual(ui.hiddenRoutes({ ...empty, accounts: [{ ...bare, as_of: '2026-10-06T07:41:03Z' }] }), ['intelligence']);
  assert.deepEqual(ui.hiddenRoutes({ ...empty, posts: [{ id: 'p' }] }), ['intelligence', 'publish']);
  assert.deepEqual(ui.hiddenRoutes({ ...empty, history_posts: [{ id: 'p' }] }), ['intelligence', 'publish']);
  assert.deepEqual(ui.hiddenRoutes(empty, { counts: { imports: 2 } }), ['intelligence', 'publish']);
  assert.deepEqual(ui.hiddenRoutes(empty, { counts: { imports: 0, works: 6 } }), ['analytics', 'intelligence', 'publish']);
  for (const key of ['news', 'research', 'candidates']) assert.deepEqual(ui.hiddenRoutes({ ...empty, intelligence: { [key]: [{ title: 'x' }] } }), ['analytics', 'publish'], key);
  assert.deepEqual(ui.hiddenRoutes({ ...empty, intelligence: { news: [], candidate_count: 26 } }), ['analytics', 'intelligence', 'publish'], 'counts alone are not items');
  assert.deepEqual(ui.hiddenRoutes({ accounts: [{ ...bare, as_of: '2026-10-06' }], posts: [{ id: 'p' }], intelligence: { news: [{ title: 'x' }] } }), []);
});

test('the sidebar entry and the title follow the page: tools under 发布, Skills under 设置', () => {
  assert.equal(ui.navRoute('tools', 'publish'), 'publish');
  assert.equal(ui.navRoute('tools', 'planning'), 'publish');
  assert.equal(ui.navRoute('tools', 'data'), 'analytics');
  assert.equal(ui.navRoute('publish'), 'publish', '平台入口 stays under 发布');
  assert.equal(ui.navRoute('works', '', true), 'settings', 'the Skills page belongs to 设置');
  assert.equal(ui.navRoute('works'), 'works');
  assert.equal(ui.SKILLS_HASH, '#works?kind=skill');
  assert.equal(ui.pageTitle('publish', '', 'entries'), '平台入口 · SPT');
  assert.equal(ui.pageTitle('publish'), '平台入口 · SPT');
  assert.equal(ui.pageTitle('tools', 'publish'), '发布记录 · SPT');
  assert.equal(ui.pageTitle('tools', 'overview'), '发布 · SPT');
  assert.equal(ui.pageTitle('works', '', 'skills'), 'Skills · SPT');
  assert.equal(ui.pageTitle('works'), '资产库 · SPT');
  assert.equal(ui.pageTitle('nope'), '运营 · SPT');
});

test('palette matching ranks prefix over substring over letters in order', () => {
  assert.equal(ui.matchScore('', '资产库'), 1);
  assert.equal(ui.matchScore('资产', '资产库'), 3);
  assert.equal(ui.matchScore('产库', '资产库'), 2);
  assert.equal(ui.matchScore('works', '资产库', 'works library'), 2);
  assert.equal(ui.matchScore('发设', '发布设置'), 1);
  assert.equal(ui.matchScore('天气', '资产库', 'works'), 0);
  assert.equal(ui.matchScore('SETT', 'settings'), 3);
});

test('toasts stay 4s, 8s with an action or an error, or as asked', () => {
  assert.equal(ui.toastDuration('info', false), 4000);
  assert.equal(ui.toastDuration('success', true), 8000);
  assert.equal(ui.toastDuration('error', false), 0, 'errors stay until closed');
  assert.equal(ui.toastDuration('info', false, 1200), 1200);
});

test('roving tabs wrap with arrows and jump with Home and End', () => {
  assert.equal(ui.rovingIndex('ArrowRight', 0, 4), 1);
  assert.equal(ui.rovingIndex('ArrowRight', 3, 4), 0);
  assert.equal(ui.rovingIndex('ArrowLeft', 0, 4), 3);
  assert.equal(ui.rovingIndex('Home', 2, 4), 0);
  assert.equal(ui.rovingIndex('End', 0, 4), 3);
  assert.equal(ui.rovingIndex('ArrowDown', 0, 4), -1);
  assert.equal(ui.rovingIndex('ArrowDown', 0, 4, true), 1);
  assert.equal(ui.rovingIndex('ArrowRight', 0, 0), -1);
});

test('detail stepping finds neighbours in the current list', () => {
  assert.deepEqual(ui.neighborIds(['a', 'b', 'c'], 'b'), { prev: 'a', next: 'c' });
  assert.deepEqual(ui.neighborIds(['a', 'b', 'c'], 'a'), { prev: '', next: 'b' });
  assert.deepEqual(ui.neighborIds(['a'], 'z'), { prev: '', next: '' });
});

test('restoring a note sends its old index only when the server gave one', () => {
  assert.deepEqual(ui.restoreRequest({ id: '20261021-175746-da49', rope: 'AK', index: 2, kept_in: '便签/.已撤下/AK' }), { id: '20261021-175746-da49', rope: 'AK', index: 2 });
  assert.deepEqual(ui.restoreRequest({ id: '20261021-175746-da49', rope: 'AK', text: '…', taken_down_at: 'x' }), { id: '20261021-175746-da49', rope: 'AK' });
  assert.deepEqual(ui.restoreRequest({ id: '20261021-175746-da49', rope: 'AK', index: '2' }), { id: '20261021-175746-da49', rope: 'AK' });
});

test('reconnect backoff doubles from 5s and stops at 30s; themes resolve', () => {
  assert.equal(ui.nextDelay(5000), 10000);
  assert.equal(ui.nextDelay(20000), 30000);
  assert.equal(ui.nextDelay(30000), 30000);
  assert.equal(ui.nextDelay(0), 5000);
  assert.equal(ui.resolveTheme('light', true), 'light');
  assert.equal(ui.resolveTheme('system', false), 'light');
  assert.equal(ui.resolveTheme('system', true), 'dark');
  assert.equal(ui.resolveTheme('nonsense', false), 'dark');
});

test('source text is escaped without changing copy source', () => {
  assert.equal(ui.esc('<script>"&\'\n正文'), '&lt;script&gt;&quot;&amp;&#39;\n正文');
  assert.equal(ui.safeExternalURL('javascript:alert(1)'), '');
  assert.equal(ui.safeExternalURL('https://www.xiaohongshu.com/explore/123'), 'https://www.xiaohongshu.com/explore/123');
  assert.equal(ui.isVideo({ name: '成片.MP4' }), true);
  assert.equal(ui.isImage({ name: '封面.jpg' }), true);
});
