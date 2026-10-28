'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const lib = require('../library.js');
const { esc, apiURL } = require('../spt.js');

const deps = { esc, icon: (name) => `<i data-icon="${name}"></i>`, apiURL: (path) => apiURL(path, '/api/spt'), readableTime: (value) => value };

test('markdown renderer escapes HTML and only links http(s)', () => {
  const html = lib.markdownHTML('# 标题\n<img src=x onerror=alert(1)>\n[坏](javascript:alert(1)) [好](https://example.com/a?b=1&c=2)\n\n```\n<script>x</script>\n```', esc);
  assert.doesNotMatch(html, /<img|<script|href="javascript/);
  assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.match(html, /<span class="md-link" title="javascript:alert\(1">坏<\/span>/);
  assert.match(html, /<a href="https:\/\/example.com\/a\?b=1&amp;c=2" target="_blank" rel="noopener noreferrer">好<\/a>/);
  assert.match(html, /<pre class="md-code"><code>&lt;script&gt;x&lt;\/script&gt;<\/code><\/pre>/);
});

test('markdown renderer keeps lists, quotes, tables and headings', () => {
  const html = lib.markdownHTML('## 小节\n- 一\n- **二**\n1. 甲\n> 引用\n\n| 编号 | 写法 |\n|---|---|\n| Y1 | `毛衣` |', esc);
  assert.match(html, /<h4 class="md-heading">小节<\/h4>/);
  assert.match(html, /<ul><li>一<\/li><li><strong>二<\/strong><\/li><\/ul><ol><li>甲<\/li><\/ol>/);
  assert.match(html, /<blockquote>引用<\/blockquote>/);
  assert.match(html, /<th>编号<\/th>.*<td><code>毛衣<\/code><\/td>/s);
});

test('item files only resolve to the item file endpoint on the mount', () => {
  assert.equal(lib.itemFileURL({ file_url: '/api/items/0123456789abcdef0123/file' }, deps.apiURL), '/api/spt/items/0123456789abcdef0123/file');
  for (const value of ['//evil.test/x', '/api/items/../works/x/file', 'https://evil.test/api/items/0123456789abcdef0123/file', '/api/items/0123456789abcdef0123/file?path=/etc/passwd', null]) {
    assert.equal(lib.itemFileURL({ file_url: value }, deps.apiURL), '');
  }
});

test('copy uses prompt text, but paths for skills and bare media', () => {
  assert.equal(lib.copyText({ kind: 'prompt', text: '正文', path: 'a.md' }), '正文');
  assert.equal(lib.copyText({ kind: 'skill', text: '描述', path: '~/.codex/skills/x/SKILL.md' }), '~/.codex/skills/x/SKILL.md');
  assert.equal(lib.copyText({ kind: 'material', text: '', file: '素材/a.png', path: '素材/a.png' }), '素材/a.png');
  assert.equal(lib.copyLabel({ kind: 'material', text: '写法' }), '复制写法');
});

test('cards escape titles and disable copy when there is nothing to copy', () => {
  const card = lib.itemCardHTML({ id: 'a'.repeat(20), kind: 'record', title: '<b>x</b>', text: '', section: '记录' }, deps);
  assert.match(card, /&lt;b&gt;x&lt;\/b&gt;/);
  assert.match(card, /class="item-copy"[^>]*disabled/);
});

test('export menu links stay on the same-origin mount and scope by kind', () => {
  const menu = lib.exportMenuHTML('prompt', deps);
  assert.match(menu, /href="\/api\/spt\/export\?format=xlsx"/);
  assert.match(menu, /href="\/api\/spt\/export\?format=csv&amp;kind=prompt"/);
  assert.doesNotMatch(lib.exportMenuHTML('bogus', deps), /kind=bogus/);
});

test('detail shows the document once and links back to its work', () => {
  const html = lib.itemDetailHTML({ id: 'b'.repeat(20), kind: 'prompt', title: '提示词-1', text: '第一段', body: '第一段', note: '第一段', path: '运营/w/提示词-1.md', source: '作品', work_id: 'c'.repeat(20), section: '运营' }, deps);
  assert.doesNotMatch(html, /class="item-note"/);
  assert.match(html, /data-work="c{20}"/);
});

test('kind tabs are a real tablist with a roving tabindex and a count on every tab', () => {
  const html = lib.kindTabsHTML('prompt', { work: 4, prompt: 4, material: 0, record: 1, skill: 165 }, deps);
  assert.match(html, /^<div class="kind-tabs" role="tablist" aria-label="资产类型">/);
  const tabs = html.match(/<button[^>]*role="tab"[^>]*>/g);
  assert.equal(tabs.length, lib.KINDS.length);
  assert.equal(tabs.filter((tab) => /tabindex="0"/.test(tab)).length, 1);
  assert.equal(tabs.filter((tab) => /tabindex="-1"/.test(tab)).length, lib.KINDS.length - 1);
  assert.match(html, /class="kind-tab selected" role="tab" id="kind-tab-prompt" aria-selected="true" aria-controls="work-results" tabindex="0" data-kind="prompt"/);
  assert.match(html, /class="kind-tab" role="tab" id="kind-tab-work" aria-selected="false" aria-controls="work-results" tabindex="-1" data-kind="work"/);
  assert.equal((html.match(/<span class="nav-count">\d+<\/span>/g) || []).length, lib.KINDS.length);
  assert.match(html, /<span>素材<\/span><span class="nav-count">0<\/span>/);
  assert.match(lib.kindTabsHTML('work', {}, deps, 'item-panel'), /aria-controls="item-panel"/);
  const unknown = lib.kindTabsHTML('note', {}, deps);
  assert.equal((unknown.match(/tabindex="0"/g) || []).length, 1, 'an unknown kind still leaves one tab reachable');
  assert.doesNotMatch(unknown, /nav-count/, 'no made-up counts');
});

test('Skills left the 资产库 tabs for 设置: no tab, no jump button, but still a label and a scoped export', () => {
  assert.deepEqual(lib.KINDS.map((kind) => kind.key), ['work', 'prompt', 'material', 'record']);
  assert.equal(lib.isKind('skill'), false);
  assert.equal(lib.KIND_LABEL.skill, 'Skills', 'the Skills page and item details still name the kind');
  const tabs = lib.kindTabsHTML('work', { work: 4, prompt: 4, material: 0, record: 1, skill: 165 }, deps);
  assert.doesNotMatch(tabs, /data-kind="skill"|Skills|165/);
  assert.doesNotMatch(lib.kindTabsHTML('skill', {}, deps), /data-kind="skill"/);
  const empty = lib.emptyHTML('prompt', true, deps, 'spt', [{ key: 'skill', label: 'Skills', count: 1 }, { key: 'record', label: '记录', count: 2 }]);
  assert.doesNotMatch(empty, /data-kind="skill"|看Skills/);
  assert.match(empty, /data-kind="record">看记录（2）/);
  assert.match(lib.emptyHTML('skill', false, deps), /<h2>还没有Skills<\/h2>/);
  const menu = lib.exportMenuHTML('skill', deps);
  assert.match(menu, /只导出Skills/);
  assert.match(menu, /href="\/api\/spt\/export\?format=md&amp;kind=skill"/);
});

test('设置 › Skills lists each source with its count and folder: installed first, then 库内, then outside folders', () => {
  const roots = ['/Users/example/.claude/skills', '/Users/example/.codex/skills'];
  assert.deepEqual(lib.skillGroups([{ name: 'Claude 已安装', count: 2 }, { name: 'Codex 已安装', count: 163 }], roots, '/w'), [
    { name: 'Claude 已安装', count: 2, path: '/Users/example/.claude/skills' },
    { name: 'Codex 已安装', count: 163, path: '/Users/example/.codex/skills' },
  ]);
  // An installed folder that holds none of your own skills still gets its row; outside folders have no path to show.
  assert.deepEqual(lib.skillGroups([{ name: '外部收藏', count: 4 }, { name: '库内', count: 3 }, { name: 'Codex 已安装', count: 1 }], roots, '/Users/example/工作区'), [
    { name: 'Codex 已安装', count: 1, path: '/Users/example/.codex/skills' },
    { name: 'Claude 已安装', count: 0, path: '/Users/example/.claude/skills' },
    { name: '库内', count: 3, path: '/Users/example/工作区/skills' },
    { name: '外部收藏', count: 4, path: '' },
  ]);
  assert.deepEqual(lib.skillGroups(null, [], ''), []);
  assert.deepEqual(lib.skillGroups([{ name: '' }, null], ['/tmp/other'], ''), [], 'unnamed sections and unknown roots are skipped');
});

test('detail dialogs get previous, next and back controls only when asked', () => {
  const item = { id: 'd'.repeat(20), kind: 'prompt', title: '提示词', text: '正文', path: '提示词/a.md' };
  assert.doesNotMatch(lib.itemDetailHTML(item, deps), /detail-step|detail-back/);
  const first = lib.itemDetailHTML(item, deps, { prev: false, next: true, back: false });
  assert.match(first, /<button type="button" class="icon-button detail-step" data-detail-step="-1" aria-label="上一个" disabled><i data-icon="caret-left"><\/i><\/button>/);
  assert.match(first, /<button type="button" class="icon-button detail-step" data-detail-step="1" aria-label="下一个"><i data-icon="caret-right"><\/i><\/button>/);
  assert.doesNotMatch(first, /detail-back/);
  const deep = lib.itemDetailHTML(item, deps, { prev: true, next: true, back: true });
  assert.match(deep, /^<header class="detail-header"><button type="button" class="icon-button detail-back" data-detail-back aria-label="返回上一个">/);
  assert.ok(deep.indexOf('data-detail-step="1"') < deep.indexOf('data-action="close-detail"'), 'close stays last');
});

test('empty and no-result states always offer a way forward', () => {
  // One line and one action: where things go is the 存放说明's job, not a paragraph here.
  const none = lib.emptyHTML('prompt', false, deps);
  assert.match(none, /<h2>还没有提示词<\/h2><button type="button" class="button primary" data-action="open-guide"><i data-icon="info"><\/i>看存放说明<\/button>/);
  assert.doesNotMatch(none, /<p>/);
  for (const kind of lib.KINDS) assert.match(lib.emptyHTML(kind.key, false, deps), /data-action="open-guide"/);
  const searched = lib.emptyHTML('material', true, deps, '<毛衣>');
  assert.match(searched, /<h2>素材里没有“&lt;毛衣&gt;”<\/h2><div class="empty-actions">/);
  assert.doesNotMatch(searched, /<p>|换个关键词/);
  assert.match(searched, /<button type="button" class="button primary" data-action="clear-filters">清除筛选<\/button>/);
  assert.match(lib.emptyHTML('record', true, deps), /<h2>没有符合筛选的记录<\/h2>/);
  // Hits in other kinds get a button each; clearing the filter stays, but is no longer the primary action.
  const elsewhere = lib.emptyHTML('material', true, deps, '夜景', [{ key: 'prompt', label: '提示词', count: 2 }, { key: 'record', label: '记录', count: 0 }, { key: 'material', label: '素材', count: 0 }]);
  assert.match(elsewhere, /<button type="button" class="button" data-kind="prompt">看提示词（2）<\/button>/);
  assert.doesNotMatch(elsewhere, /data-kind="record"|data-kind="material"/);
  assert.match(elsewhere, /<button type="button" class="button" data-action="clear-filters">清除筛选<\/button>/);
});

test('search helpers: words split like the server, results narrow locally, counts and groups follow kinds', () => {
  assert.deepEqual(lib.searchWords('  夜景　火光 \tAK '), ['夜景', '火光', 'ak']);
  assert.deepEqual(lib.searchWords(''), []);
  const results = {
    works: [{ id: 'w1', title: '夜景', client: 'AK' }, { id: 'w2', title: '火光', client: '自家' }],
    items: [
      { id: 'p1', kind: 'prompt', title: '城市', text: '城市夜景', path: '提示词/夜景/城市.md' },
      { id: 'p2', kind: 'prompt', title: '夜景篝火', text: '火光' },
      { id: 'n1', kind: 'note', title: '买夜景灯', path: '便签/AK/20261022-101500-ab12.md', section: 'AK' },
      { id: 's1', kind: 'skill', title: 'spt-library', note: '查资产库' },
      { id: 'x1', kind: 'mystery', title: '夜景' },
    ],
  };
  assert.deepEqual(lib.countKinds(results), { work: 2, prompt: 2, material: 0, record: 0, note: 1, skill: 1 });
  assert.deepEqual(lib.countKinds(null), { work: 0, prompt: 0, material: 0, record: 0, note: 0, skill: 0 });
  const narrowed = lib.narrowResults(results, '夜景');
  assert.deepEqual(narrowed.works.map((work) => work.id), ['w1']);
  assert.deepEqual(narrowed.items.map((item) => item.id), ['p1', 'p2', 'n1', 'x1'], 'the path is not searched, as on the server');
  assert.deepEqual(lib.narrowResults(results, 'ak 夜景').works.map((work) => work.id), ['w1']);
  const groups = lib.groupResults(results, '夜景', 1);
  assert.deepEqual(groups.map((group) => [group.key, group.total, group.entries.length]), [['work', 2, 1], ['prompt', 2, 1], ['note', 1, 1], ['skill', 1, 1]]);
  assert.equal(groups[1].entries[0].id, 'p2', 'a title that starts with the query comes first');
  assert.equal(groups[0].entries[0].kind, 'work');
  assert.deepEqual(lib.groupResults({ works: [], items: [] }, 'x'), []);
});

test('notes found by search point back to their card; only prompt-like items offer 复制', () => {
  assert.deepEqual(lib.noteRef({ kind: 'note', path: '便签/AK/20261022-101500-ab12.md', section: 'AK' }), { id: '20261022-101500-ab12', rope: 'AK' });
  assert.equal(lib.noteRef({ kind: 'note', path: '便签/AK/说明.md' }), null);
  assert.equal(lib.noteRef({ kind: 'prompt', path: '便签/AK/20261022-101500-ab12.md' }), null);
  assert.equal(lib.promptLike({ kind: 'prompt', text: '正文' }), true);
  assert.equal(lib.promptLike({ kind: 'material', text: '写法' }), true);
  assert.equal(lib.promptLike({ kind: 'material', text: '', file: '素材/a.png' }), false);
  assert.equal(lib.promptLike({ kind: 'prompt', text: '  ' }), false);
  assert.equal(lib.promptLike({ kind: 'skill', text: '说明' }), false);
  assert.equal(lib.promptLike({ kind: 'record', text: '正文' }), false);
  assert.equal(lib.fullPath('提示词/a.md', '/Users/example/工作区/'), '/Users/example/工作区/提示词/a.md');
  assert.equal(lib.fullPath('~/.codex/skills/x/SKILL.md', '/Users/example/工作区'), '~/.codex/skills/x/SKILL.md');
  assert.equal(lib.fullPath('提示词/a.md'), '提示词/a.md');
  assert.equal(lib.fullPath(''), '');
});

test('the work card copy takes the adopted prompt, never a different version, then documents, then a caption', () => {
  const versions = [{ name: 'V1', prompt: '一' }, { name: 'V2', prompt: '' , is_current: true }, { name: 'V3', prompt: '三' }];
  assert.deepEqual(lib.workCopy({ work: { current_version: 'V1' }, versions }), { text: '一', label: '定稿 V1 的提示词' });
  assert.deepEqual(lib.workCopy({ work: { latest_version: 'V3' }, versions: [versions[0], versions[2]] }), { text: '三', label: '最新 V3 的提示词' });
  const documents = [{ name: '提示词-1.md', text: '---\n标题: 一\n---\n文档正文' }];
  assert.deepEqual(lib.workCopy({ work: { current_version: 'V2' }, versions, source_documents: documents }), { text: '文档正文', label: '提示词-1' }, 'an adopted version without a prompt is not replaced by another version');
  assert.deepEqual(lib.workCopy({ work: {}, versions: [], package: { instagram: { caption: '文案' } } }, (name) => name.toUpperCase()), { text: '文案', label: 'INSTAGRAM 文案' });
  assert.deepEqual(lib.workCopy({ work: {}, versions: [], package: { tiktok: '短文案' } }), { text: '短文案', label: 'tiktok 文案' });
  assert.deepEqual(lib.workCopy({}), { text: '', label: '' });
});

test('library chrome: group chips are toggles, one group hides the row, menus say what they hold', () => {
  const chips = lib.sectionNavHTML([{ name: '运营', count: 3 }, { name: '<电影>', count: 1 }], '运营', 4, deps);
  assert.match(chips, /<button type="button" class="category-link" data-section="" aria-pressed="false"><i data-icon="folder-open"><\/i>全部<span class="nav-count">4<\/span><\/button>/);
  assert.match(chips, /data-section="运营" aria-pressed="true"/);
  assert.match(chips, /&lt;电影&gt;/);
  assert.doesNotMatch(chips, /aria-current|工作区/);
  assert.equal(lib.showsGroups([{ name: '运营', count: 4 }], ''), false);
  assert.equal(lib.showsGroups([{ name: '运营', count: 4 }], '运营'), true, 'a chosen group stays visible so it can be cleared');
  assert.equal(lib.showsGroups([{ name: 'a' }, { name: 'b' }], ''), true);
  assert.equal(lib.showsGroups(undefined, ''), false);
  const more = lib.exportMenuHTML('prompt', deps, { guide: true });
  assert.match(more, /<summary class="icon-button more-button" aria-label="存放说明和导出" title="存放说明和导出">/);
  assert.match(more, /data-action="open-guide"/);
  assert.doesNotMatch(lib.exportMenuHTML('prompt', deps), /open-guide/);
  const display = lib.displayMenuHTML('portrait', deps);
  assert.match(display, /role="group" aria-label="封面比例"/);
  assert.equal((display.match(/aria-pressed="true"/g) || []).length, 1);
  assert.match(display, /data-cover-mode="portrait" aria-pressed="true"/);
  assert.match(lib.displayMenuHTML('bogus', deps), /data-cover-mode="square" aria-pressed="true"/);
});

test('kind tabs show match counts while searching and dim kinds with none', () => {
  const html = lib.kindTabsHTML('work', { work: 0, prompt: 2, material: 0, record: 0, skill: 1 }, deps, 'work-results', { matching: true });
  assert.match(html, /^<div class="kind-tabs is-matching"/);
  assert.match(html, /class="kind-tab is-empty" role="tab" id="kind-tab-material"/);
  assert.match(html, /class="kind-tab selected is-empty" role="tab" id="kind-tab-work"/);
  assert.match(html, /<span>提示词<\/span><span class="nav-count">2<span class="sr-only">个匹配<\/span><\/span>/);
  assert.doesNotMatch(lib.kindTabsHTML('work', {}, deps), /is-empty/, 'unknown counts are not zero');
});

test('skills group by section; Codex starts folded and remembers what was opened or closed', () => {
  const items = [
    { id: '1'.repeat(20), kind: 'skill', title: 'spt-library', section: '库内', note: '说明', path: 'skills/spt-library/SKILL.md' },
    { id: '2'.repeat(20), kind: 'skill', title: 'imagegen', section: 'Codex', note: '说明', path: '~/.codex/skills/imagegen/SKILL.md' },
  ];
  const html = lib.itemsHTML(items, 'grid', deps, { grouped: true });
  assert.match(html, /<details class="item-group" data-group="库内" open><summary class="item-group-head" data-group-toggle="库内">/);
  assert.match(html, /<details class="item-group" data-group="Codex"><summary/);
  const opened = lib.itemsHTML(items, 'grid', deps, { grouped: true, open: new Set(['Codex']), closed: new Set(['库内']) });
  assert.match(opened, /data-group="Codex" open>/);
  assert.match(opened, /data-group="库内">/);
  assert.doesNotMatch(lib.itemsHTML(items, 'grid', deps), /<details/, 'search results and single kinds stay flat');
  // Under a group heading the card does not repeat the group's name; a flat list still shows it.
  assert.doesNotMatch(html, /<span class="item-meta"><span>库内<\/span>/);
  assert.match(lib.itemsHTML(items, 'grid', deps), /<span class="item-meta"><span>库内<\/span><\/span>/);
  assert.equal(lib.collapsedByDefault('Codex'), true);
  assert.equal(lib.collapsedByDefault('Claude'), false);
  assert.match(lib.itemCardHTML(items[0], deps), /<span class="item-title" title="spt-library">spt-library<\/span>/);
});

test('the item path is plain text with a 复制路径 button that copies the full path', () => {
  const item = { id: 'a'.repeat(20), kind: 'prompt', title: '提示词', text: '正文', path: '提示词/场景/a.md' };
  const html = lib.itemDetailHTML(item, { ...deps, workspace: () => '/Users/example/工作区' });
  assert.match(html, /<div class="item-path"><span class="item-path-text" title="\/Users\/example\/工作区\/提示词\/场景\/a.md">/);
  assert.match(html, /<button type="button" class="button small" data-copy-text="\/Users\/example\/工作区\/提示词\/场景\/a.md" aria-label="复制路径：提示词\/场景\/a.md"><i data-icon="copy"><\/i>复制路径<\/button>/);
  const skill = lib.itemDetailHTML({ ...item, kind: 'skill', path: '~/.codex/skills/x/SKILL.md' }, deps);
  assert.equal((skill.match(/复制路径/g) || []).length, 1, 'the main copy button already copies the path');
});

test('cards prefer the small thumbnail, the detail keeps the full file', () => {
  const id = 'e'.repeat(20);
  const item = { id, kind: 'material', title: '图', file: '素材/a.png', file_url: `/api/items/${id}/file`, thumb_url: `/api/items/${id}/thumb?v=0123456789ab`, path: '素材/a.png', width: 640, height: 480 };
  assert.match(lib.itemCardHTML(item, deps), /<span class="item-thumb" data-media="image"><img src="\/api\/spt\/items\/e{20}\/thumb\?v=0123456789ab" alt="" loading="lazy" decoding="async" width="640" height="480">/);
  assert.match(lib.itemDetailHTML(item, deps), /<img src="\/api\/spt\/items\/e{20}\/file" alt="图"/);
  for (const thumb of ['https://evil.test/x.png', `/api/items/${id}/thumb?v=xyz`, `/api/items/${id}/thumb?path=/etc/passwd`]) {
    assert.match(lib.itemCardHTML({ ...item, thumb_url: thumb }, deps), /src="\/api\/spt\/items\/e{20}\/file"/);
  }
  const video = { ...item, file: '素材/a.mp4', path: '素材/a.mp4' };
  assert.match(lib.itemCardHTML(video, deps), /data-media="video"><img src="\/api\/spt\/items\/e{20}\/thumb/);
  assert.match(lib.itemCardHTML({ ...video, thumb_url: null }, deps), /<video muted preload="metadata"/);
  assert.match(lib.itemDetailHTML(video, deps), /<video controls preload="metadata"/);
});

test('the clients directory follows health.clients, else the works: 自家 is own, 自家 first, then by code', () => {
  const health = { clients: [{ code: '自家', name: '自家', kind: 'own', color: null, works: 4 }, { code: 'B创作者', name: 'B创作者', kind: 'own' }, { code: 'AK', name: 'Sample Studio', kind: 'client', color: '#F0B35C' }, { code: ' ', name: 'blank' }, null] };
  const works = [{ client: 'AK' }, { client: '新客' }, { client: '' }, {}];
  assert.deepEqual(lib.clientDirectory(health, works), [
    { code: '自家', name: '自家', kind: 'own', color: null, index: 1 },
    { code: 'B创作者', name: 'B创作者', kind: 'own', color: null, index: 2 },
    { code: 'AK', name: 'Sample Studio', kind: 'client', color: '#f0b35c', index: 3 },
    { code: '新客', name: '新客', kind: 'client', color: null, index: 4 },
  ], 'the file order, then codes the works add; a colour must be #rrggbb');
  assert.deepEqual(lib.clientDirectory({ clients: [{ code: 'AK', color: 'red', kind: 'owner' }] }, []), [{ code: 'AK', name: 'AK', kind: 'client', color: null, index: 1 }], 'an unknown kind is a client');
  assert.deepEqual(lib.clientDirectory(null, [{ client: 'AK' }, { client: 'B创作者' }, { client: '自家' }, { client: 'AK' }]).map((entry) => [entry.code, entry.kind, entry.index]), [['自家', 'own', 1], ['AK', 'client', 2], ['B创作者', 'client', 3]], 'without health.clients only 自家 is own');
  assert.deepEqual(lib.clientDirectory({ counts: {} }, []), []);
  const clients = lib.clientDirectory(health, works);
  assert.equal(lib.clientName(clients, 'AK'), 'Sample Studio');
  assert.equal(lib.clientName(clients, '路人'), '路人');
  assert.equal(lib.clientName(clients, null), '');
  assert.equal(lib.swatchStyle(clients[2]), ' style="--series:#f0b35c"', 'the client\'s own colour wins');
  assert.equal(lib.swatchStyle(clients[0]), ' style="--series:var(--client-1)"');
  assert.equal(lib.swatchStyle({ index: 9 }), ' style="--series:var(--client-1)"', 'eight slots wrap');
  assert.equal(lib.swatchStyle(null), '', 'an unlisted code keeps the default swatch');
});

test('client chips: 全部, then the 自己 and 客户 clusters as named groups; hidden when 自家 is the only one', () => {
  const clients = lib.clientDirectory({ clients: [{ code: '自家', kind: 'own' }, { code: 'B创作者', kind: 'own' }, { code: 'AK', name: 'Sample Studio', kind: 'client', color: '#f0b35c' }] }, []);
  const groups = lib.clientChips(clients, { '自家': 4, 'B创作者': 44, AK: 59, '新客': 1 }, 'AK');
  assert.deepEqual(groups.map((group) => [group.key, group.name, group.chips.map(({ entry, count }) => `${entry.code}:${count}`)]), [['own', '自己', ['自家:4', 'B创作者:44']], ['client', '客户', ['AK:59', '新客:1']]], 'a code the directory lacks joins 客户 at the end');
  const html = lib.clientChipsHTML(groups, 'AK', 108, deps);
  assert.match(html, /^<div class="chip-row client-chips"><button type="button" class="category-link" data-client="" aria-pressed="false"><i data-icon="folder-open"><\/i>全部<span class="nav-count">108<\/span><\/button>/);
  assert.match(html, /<span class="chip-group" role="group" aria-label="自己"><span class="chip-group-name" aria-hidden="true">自己<\/span><button type="button" class="category-link client-chip" data-client="自家" aria-pressed="false"><i class="swatch" aria-hidden="true" style="--series:var\(--client-1\)"><\/i>自家<span class="nav-count">4<\/span><\/button>/);
  assert.match(html, /<span class="chip-group" role="group" aria-label="客户"><span class="chip-group-name" aria-hidden="true">客户<\/span><button type="button" class="category-link client-chip selected" data-client="AK" aria-pressed="true"><i class="swatch" aria-hidden="true" style="--series:#f0b35c"><\/i>Sample Studio<span class="nav-count">59<\/span><\/button>/);
  assert.equal((html.match(/aria-pressed="true"/g) || []).length, 1);
  assert.doesNotMatch(html, /title=/);
  // Without health.clients the directory comes from the works and B创作者 is a client; 全部 is pressed when nothing is chosen.
  const derived = lib.clientDirectory(null, [{ client: 'AK' }, { client: 'B创作者' }, { client: '自家' }]);
  const flat = lib.clientChips(derived, { AK: 59, 'B创作者': 44, '自家': 4 }, '');
  assert.deepEqual(flat.map((group) => group.chips.map(({ entry }) => entry.code)), [['自家'], ['AK', 'B创作者']]);
  assert.match(lib.clientChipsHTML(flat, '', 107, deps), /data-client="" aria-pressed="true"/);
  // One client only: 自家 alone is not worth a row (unless it is chosen); a lone real client still is.
  assert.deepEqual(lib.clientChips(derived, { '自家': 4 }, ''), []);
  assert.equal(lib.clientChips(derived, { '自家': 4 }, '自家').length, 1);
  assert.equal(lib.clientChips(derived, { AK: 4 }, '').length, 1);
  assert.deepEqual(lib.clientChips(derived, {}, ''), []);
  assert.equal(lib.clientChipsHTML([], '', 0, deps), '');
  // A chosen client with nothing of this kind keeps its chip (count 0) so it can be cleared; a cluster with no members is not drawn.
  const only = lib.clientChips(derived, { AK: 3 }, 'B创作者');
  assert.deepEqual(only.map((group) => [group.name, group.chips.map(({ entry, count }) => `${entry.code}:${count}`)]), [['客户', ['AK:3', 'B创作者:0']]]);
  // Items: no client is 通用, first in 自己.
  const items = lib.clientChips(derived, { [lib.GENERAL_CLIENT]: 190, '自家': 3, AK: 4 }, '', { general: true });
  assert.deepEqual(items.map((group) => group.chips.map(({ entry }) => entry.code)), [['通用', '自家'], ['AK']]);
  assert.deepEqual(lib.clientChips(derived, { [lib.GENERAL_CLIENT]: 190 }, '', { general: true }), [], 'only 通用 is the same as only 自家');
  assert.deepEqual(lib.clientChips(derived, { [lib.GENERAL_CLIENT]: 190 }, ''), [], 'a works row never shows 通用');
});

test('the overview groups by client, 自己 before 客户, keeps the first ten and skips empty clients', () => {
  const clients = lib.clientDirectory({ clients: [{ code: '自家', kind: 'own' }, { code: 'B创作者', kind: 'own' }, { code: 'AK', name: 'Sample Studio', kind: 'client' }, { code: '餐厅D', kind: 'client' }] }, []);
  const works = [...Array.from({ length: 12 }, (_, index) => ({ id: `ak${index}`, client: 'AK' })), { id: 'z1', client: '自家' }, { id: 'x1', client: '新客' }, { id: 'n1', client: '' }, { id: 'n2' }];
  const tiers = lib.groupByClient(works, clients);
  assert.deepEqual(tiers.map((tier) => [tier.key, tier.name, tier.blocks.map((block) => [block.client.code, block.total, block.entries.length])]), [
    ['own', '自己', [['自家', 1, 1]]],
    ['client', '客户', [['AK', 12, 10], ['新客', 1, 1]]],
  ], 'B创作者 and 餐厅D have nothing: no block; works without a client are left out');
  assert.deepEqual(tiers[1].blocks[0].entries.map((work) => work.id), works.slice(0, 10).map((work) => work.id), 'the first ten in list order (newest first)');
  assert.equal(lib.groupByClient(works, clients, { limit: 3 })[1].blocks[0].entries.length, 3);
  assert.deepEqual(lib.groupByClient([{ id: 'ak1', client: 'AK' }], clients).map((tier) => tier.key), ['client'], 'an empty tier is not drawn');
  assert.deepEqual(lib.groupByClient([], clients), []);
  // Items: no client is 通用, the first block under 自己.
  const items = lib.groupByClient([{ id: 'p1', client: null }, { id: 'p2', client: 'AK' }, { id: 'p3' }], clients, { general: true });
  assert.deepEqual(items.map((tier) => tier.blocks.map((block) => [block.client.code, block.client.kind, block.total])), [[['通用', 'own', 2]], [['AK', 'client', 1]]]);
  const html = lib.clientBlocksHTML(tiers, (list) => `<p>${list.map((work) => work.id).join(',')}</p>`, deps, { closed: new Set(['client:AK']) });
  assert.match(html, /^<section class="client-tier" aria-labelledby="client-tier-own"><h2 class="client-tier-name" id="client-tier-own">自己<\/h2><div class="client-block"><details class="item-group" data-group="client:自家" open><summary class="item-group-head client-block-head" data-group-toggle="client:自家"><span class="icon i-caret-right item-group-caret" aria-hidden="true"><\/span><i class="swatch" aria-hidden="true" style="--series:var\(--client-1\)"><\/i><span class="item-group-name">自家<\/span><span class="nav-count">1<\/span><\/summary><p>z1<\/p><\/details><button type="button" class="button small client-block-all" data-client="自家" aria-label="自家：全部 1">全部 1<\/button><\/div><\/section>/);
  assert.match(html, /<details class="item-group" data-group="client:AK"><summary[^>]*><span[^>]*><\/span><i class="swatch" aria-hidden="true" style="--series:var\(--client-3\)"><\/i><span class="item-group-name">Sample Studio<\/span><span class="nav-count">12<\/span><\/summary><p>ak0,ak1,ak2,ak3,ak4,ak5,ak6,ak7,ak8,ak9<\/p><\/details><button type="button" class="button small client-block-all" data-client="AK" aria-label="Sample Studio：全部 12">全部 12<\/button>/, 'a folded block stays folded; 全部 N selects the client');
  assert.match(html, /data-group="client:新客" open><summary[^>]*><span[^>]*><\/span><i class="swatch" aria-hidden="true"><\/i>/, 'an unlisted client keeps the default swatch');
  assert.doesNotMatch(html, /<p>[^<]*<\/p><\/section>/, 'no helper sentences');
});

test('item cards and rows carry a client tag when the item has a client; the overview groups them by client', () => {
  const clients = lib.clientDirectory({ clients: [{ code: '自家', kind: 'own' }, { code: 'AK', name: 'Sample Studio', kind: 'client' }] }, []);
  const ak = { id: 'a'.repeat(20), kind: 'prompt', title: '三道菜', text: '正文', section: '运营', client: 'AK' };
  const none = { id: 'b'.repeat(20), kind: 'prompt', title: '模板', text: '正文', section: '场景', client: null };
  assert.match(lib.itemCardHTML(ak, deps, false, clients), /<span class="item-meta"><span class="client-tag"><i class="swatch" aria-hidden="true" style="--series:var\(--client-2\)"><\/i><span>Sample Studio<\/span><\/span><span>运营<\/span><\/span>/);
  assert.match(lib.itemCardHTML(none, deps, false, clients), /<span class="item-meta"><span>场景<\/span><\/span>/, 'no client, no tag (and no 通用 on the card)');
  assert.doesNotMatch(lib.itemCardHTML(ak, deps), /client-tag/, 'without a directory the card is as before');
  assert.match(lib.itemRowHTML(ak, deps, clients), /<td><span class="client-tag"><i class="swatch" aria-hidden="true" style="--series:var\(--client-2\)"><\/i><span>Sample Studio<\/span><\/span>运营<\/td>/);
  assert.match(lib.itemRowHTML(none, deps, clients), /<td>场景<\/td>/);
  assert.equal(lib.clientTagHTML('', clients, deps), '');
  assert.match(lib.clientTagHTML('路人', clients, deps), /^<span class="client-tag"><i class="swatch" aria-hidden="true"><\/i><span>路人<\/span><\/span>$/);
  const overview = lib.itemsHTML([none, ak], 'grid', deps, { clients, byClient: { limit: 10 } });
  assert.match(overview, /^<section class="client-tier" aria-labelledby="client-tier-own"><h2 class="client-tier-name" id="client-tier-own">自己<\/h2><div class="client-block"><details class="item-group" data-group="client:通用" open>/);
  assert.match(overview, /data-group="client:AK" open>[^]*<div class="items-grid"><article class="item-card">[^]*data-item="a{20}"/);
  assert.match(lib.itemsHTML([none, ak], 'list', deps, { clients, byClient: { limit: 10 } }), /<details class="item-group" data-group="client:通用" open><summary[^]*<\/summary><div class="table-wrap"><table class="data-table items-table">/);
  assert.doesNotMatch(lib.itemsHTML([none, ak], 'grid', deps, { clients }), /client-tier|<details/, 'flat unless asked');
});

test('clients cluster by their group: file order from client_groups, custom names, kind as the fallback', () => {
  const health = {
    client_groups: ['餐厅', '自己', '品牌'],
    clients: [{ code: '自家', kind: 'own', group: '自己', works: 4 }, { code: 'AK', name: 'Sample Studio', kind: 'client', group: '餐厅', works: 59 }, { code: 'B创作者', kind: 'own', group: '品牌', works: 44 }, { code: '新客', kind: 'client' }],
  };
  const clients = lib.clientDirectory(health, [{ client: '路人' }]);
  assert.deepEqual(clients.map((entry) => [entry.code, entry.group ?? null]), [['自家', '自己'], ['AK', '餐厅'], ['B创作者', '品牌'], ['新客', null], ['路人', null]], 'group only when the service gave one');
  assert.deepEqual(lib.clientGroupNames(health, clients), ['餐厅', '自己', '品牌', '客户'], 'the file order, then the fallback group a listed-without-group client needs');
  assert.deepEqual(lib.clientGroupNames(null, lib.clientDirectory(null, [{ client: 'AK' }])), ['自己', '客户']);
  assert.deepEqual(lib.clientGroupNames({ client_groups: [' 餐厅 ', '', '餐厅', null] }, []), ['餐厅']);
  const groups = lib.clientGroupNames(health, clients);
  const chips = lib.clientChips(clients, { '自家': 4, AK: 59, 'B创作者': 44, '新客': 1, '路人': 2 }, '', { groups });
  assert.deepEqual(chips.map((group) => [group.key, group.name, group.chips.map(({ entry }) => entry.code)]), [
    ['group-0', '餐厅', ['AK']], ['own', '自己', ['自家']], ['group-2', '品牌', ['B创作者']], ['client', '客户', ['新客', '路人']],
  ], 'one cluster per group in order; a client without a group falls back by kind; the label is the group name');
  assert.deepEqual(lib.clientChips(clients, { AK: 59, '新客': 1 }, '', { groups }).map((group) => group.name), ['餐厅', '客户'], 'empty groups are not drawn');
  const html = lib.clientChipsHTML(chips, '', 110, deps);
  assert.match(html, /<span class="chip-group" role="group" aria-label="餐厅"><span class="chip-group-name" aria-hidden="true">餐厅<\/span><button[^>]*data-client="AK"/);
  assert.ok(html.indexOf('aria-label="餐厅"') < html.indexOf('aria-label="自己"') && html.indexOf('aria-label="自己"') < html.indexOf('aria-label="品牌"'));
  // Without groups the row is exactly the old two clusters (fallback by kind).
  const plain = lib.clientDirectory({ clients: [{ code: '自家', kind: 'own' }, { code: 'AK', kind: 'client' }] }, []);
  assert.deepEqual(lib.clientChips(plain, { '自家': 1, AK: 2 }, '').map((group) => [group.key, group.name]), [['own', '自己'], ['client', '客户']]);
  // A renamed 自己 (no group called 自己 any more) still clusters 通用 under 自己, appended after the file's groups.
  const renamed = lib.clientChips(clients, { [lib.GENERAL_CLIENT]: 3, AK: 1 }, '', { general: true, groups: ['餐厅'] });
  assert.deepEqual(renamed.map((group) => [group.name, group.chips.map(({ entry }) => entry.code)]), [['餐厅', ['AK']], ['自己', ['通用']]]);
  // The overview follows the same order and skips groups with nothing in them.
  const works = [{ id: 'w1', client: 'B创作者' }, { id: 'w2', client: 'AK' }, { id: 'w3', client: '路人' }];
  const tiers = lib.groupByClient(works, clients, { groups });
  assert.deepEqual(tiers.map((tier) => [tier.key, tier.name, tier.blocks.map((block) => block.client.code)]), [['group-0', '餐厅', ['AK']], ['group-2', '品牌', ['B创作者']], ['client', '客户', ['路人']]]);
  const blocks = lib.clientBlocksHTML(tiers, () => '', deps);
  assert.match(blocks, /<section class="client-tier" aria-labelledby="client-tier-group-0"><h2 class="client-tier-name" id="client-tier-group-0">餐厅<\/h2>/);
  assert.deepEqual(lib.groupByClient(works, clients).map((tier) => tier.name), ['客户', '餐厅', '品牌'], 'no order given: 自己 and 客户 lead, the groups the clients carry follow as met');
  const byKind = lib.clientDirectory({ clients: [{ code: '自家', kind: 'own' }, { code: 'B创作者', kind: 'own' }, { code: 'AK', kind: 'client' }] }, []);
  assert.deepEqual(lib.groupByClient(works, byKind).map((tier) => [tier.name, tier.blocks.map((block) => block.client.code)]), [['自己', ['B创作者']], ['客户', ['AK', '路人']]], 'no groups anywhere: 自己 then 客户, by kind');
  // A client whose colour is one of the eight slots draws with the theme token, so it adapts to light mode.
  assert.equal(lib.swatchStyle({ color: lib.PALETTE_HEX[2], index: 1 }), ' style="--series:var(--client-3)"');
  assert.equal(lib.swatchStyle({ color: '#F0B35C', index: 1 }), ' style="--series:#F0B35C"');
});

test('整理客户: the dialog lists every group in order, deletes only what has no works, and picks colours from nine dots', () => {
  const health = { client_groups: ['自己', '餐厅'], clients: [{ code: '自家', kind: 'own', group: '自己', works: 4 }, { code: 'AK', name: 'Sample Studio', kind: 'client', group: '餐厅', color: lib.PALETTE_HEX[3], works: 59 }, { code: '旧客', kind: 'client', group: '餐厅', works: 0 }] };
  const clients = lib.clientDirectory(health, [{ client: '新客' }]);
  const groups = lib.clientGroupsFor(health, clients, { '新客': 2, '旧客': 0 });
  assert.deepEqual(groups, [
    { name: '自己', clients: [{ code: '自家', name: '', color: null, works: 4 }] },
    { name: '餐厅', clients: [{ code: 'AK', name: 'Sample Studio', color: lib.PALETTE_HEX[3], works: 59 }, { code: '旧客', name: '', color: null, works: 0 }] },
    { name: '客户', clients: [{ code: '新客', name: '', color: null, works: 2 }] },
  ], 'a name equal to the code is left blank (the field\'s placeholder is the code); a code seen only in works counts its works');
  groups.push({ name: '新牌子', clients: [] });
  const html = lib.clientsDialogHTML(groups, deps, { editing: 3 });
  assert.match(html, /^<header class="detail-header"><div class="detail-heading"><h2 id="clients-title">整理客户<\/h2><\/div><button type="button" class="icon-button" data-action="close-clients" aria-label="关闭">/);
  const sections = html.match(/<section class="clients-group[^"]*" data-group-section="\d+" aria-label="[^"]+">/g);
  assert.deepEqual(sections, [
    '<section class="clients-group" data-group-section="0" aria-label="自己">', '<section class="clients-group" data-group-section="1" aria-label="餐厅">',
    '<section class="clients-group" data-group-section="2" aria-label="客户">', '<section class="clients-group is-empty" data-group-section="3" aria-label="新牌子">',
  ], 'groups in order, empty ones kept as drop targets');
  assert.match(html, /<button type="button" class="clients-group-name" id="clients-group-1" data-group-rename="1" aria-label="改名：餐厅">餐厅<\/button><span class="nav-count">2<\/span><\/header>/);
  assert.match(html, /<input class="clients-group-input" data-group-input="3" value="新牌子" maxlength="30" autocomplete="off" aria-label="分组名">/, 'the group being renamed shows a field');
  assert.equal((html.match(/data-group-remove="/g) || []).length, 1, '删除分组 only on the empty group');
  assert.match(html, /data-group-remove="3"/);
  assert.match(html, /<button type="button" class="button clients-add-group" data-group-add>/);
  // Rows: handle, swatch, code, name field, count or 删除, 移到….
  const rows = html.match(/<li class="client-row" draggable="true" data-client-row="([^"]+)" data-group-index="(\d+)" data-client-index="(\d+)">/g);
  assert.deepEqual(rows.map((row) => row.match(/data-client-row="([^"]+)" data-group-index="(\d+)" data-client-index="(\d+)"/).slice(1).join(':')), ['自家:0:0', 'AK:1:0', '旧客:1:1', '新客:2:0']);
  assert.match(html, /<button type="button" class="client-handle" data-client-handle="AK" aria-label="拖动排序：Sample Studio" aria-keyshortcuts="Alt\+ArrowUp Alt\+ArrowDown">/);
  assert.match(html, /<span class="client-code">AK<\/span><input class="client-name" data-client-name="AK" value="Sample Studio" placeholder="AK" maxlength="40" autocomplete="off" aria-label="名字：AK"><span class="client-works">59 件<\/span>/);
  assert.match(html, /data-client-name="自家" value="" placeholder="自家"/);
  assert.equal((html.match(/data-client-delete="/g) || []).length, 1, '删除 only when works === 0');
  assert.match(html, /<button type="button" class="button small danger" data-client-delete="旧客">删除<\/button>/);
  assert.doesNotMatch(html, /data-client-delete="AK"|data-client-delete="新客"/);
  // The swatch shows the chosen slot (AK: slot 4) or the positional default; the popover has eight slots and 无.
  assert.match(html, /<summary class="swatch-pick" aria-label="颜色：Sample Studio"><i class="swatch" aria-hidden="true" style="--series:var\(--client-4\)"><\/i><\/summary><div class="swatch-options" role="group" aria-label="颜色">/);
  assert.match(html, /<summary class="swatch-pick" aria-label="颜色：自家"><i class="swatch" aria-hidden="true" style="--series:var\(--client-1\)"><\/i><\/summary>/, 'no colour: the slot its position would get');
  const ak = html.slice(html.indexOf('data-client-row="AK"'), html.indexOf('data-client-row="旧客"'));
  assert.equal((ak.match(/class="swatch-option"/g) || []).length, 8);
  assert.equal((ak.match(/class="swatch-option swatch-none"/g) || []).length, 1);
  assert.match(ak, /<button type="button" class="swatch-option" data-client-color="AK" data-color="4" aria-pressed="true" aria-label="颜色 4"><i class="swatch" aria-hidden="true" style="--series:var\(--client-4\)"><\/i><\/button>/);
  assert.match(ak, /<button type="button" class="swatch-option swatch-none" data-client-color="AK" data-color="" aria-pressed="false" aria-label="无"><i class="swatch" aria-hidden="true"><\/i><\/button>/);
  assert.equal((ak.match(/aria-pressed="true"/g) || []).length, 1);
  assert.match(html, /data-client-color="自家" data-color="" aria-pressed="true"/, 'no colour: 无 is pressed');
  // 移到… is a listbox (no native select) that names every group, the row's own group selected.
  assert.doesNotMatch(html, /<select/);
  assert.match(ak, /<input type="hidden" id="client-move-AK" value="1">/);
  assert.match(ak, /id="client-move-AK-opt-3" data-value="3" aria-selected="false"[^>]*><span class="listbox-option-label">新牌子<\/span>/);
  assert.match(ak, /<span class="listbox-label sr-only" id="client-move-AK-label">移到…：Sample Studio<\/span>/);
  // The footer and the unsaved bar, no helper copy.
  assert.match(html, /<div class="note-discard" id="clients-discard" role="alert" hidden><p>还没保存。<\/p><div class="note-bar-actions"><button type="button" class="button small" data-clients-discard-keep>继续整理<\/button><button type="button" class="button small danger" data-clients-discard>不保存<\/button><button type="submit" class="button small primary">保存<\/button><\/div><\/div>/);
  assert.match(html, /<footer class="note-editor-foot clients-foot"><button type="button" class="button" data-action="close-clients">取消<\/button><button type="submit" class="button primary" aria-keyshortcuts="Meta\+Enter">保存<\/button><\/footer><\/form>$/);
  assert.doesNotMatch(html, /<p class="(?!confirm)[^"]*">(?!还没保存)/, 'no captions or helper lines');
  assert.doesNotMatch(lib.clientsDialogHTML([{ name: '<b>', clients: [{ code: '<x>', name: '"y"', works: 1 }] }], deps), /<b>|<x>|"y"/);
  // An unnamed new group is still pickable as 新分组.
  assert.match(lib.clientsDialogHTML([{ name: '自己', clients: [{ code: '自家', works: 1 }] }, { name: '', clients: [] }], deps), /data-value="1" aria-selected="false"[^>]*><span class="listbox-option-label">新分组<\/span>/);
});

test('整理客户: the save payload trims names, falls back to the code, keeps only #rrggbb, and flags what the server would reject', () => {
  const groups = [
    { name: ' 自己 ', clients: [{ code: '自家', name: '  ', color: null, works: 4 }] },
    { name: '餐厅', clients: [{ code: 'AK', name: ' Sample Studio ', color: '#F0B35C', works: 59 }, { code: '旧客', name: '', color: 'red', works: 0 }] },
    { name: '', clients: [] },
    { name: '品牌', clients: [] },
  ];
  assert.deepEqual(lib.clientsSavePayload(groups), { groups: [
    { name: '自己', clients: [{ code: '自家', name: '自家', color: null }] },
    { name: '餐厅', clients: [{ code: 'AK', name: 'Sample Studio', color: '#f0b35c' }, { code: '旧客', name: '旧客', color: null }] },
    { name: '品牌', clients: [] },
  ] }, 'an unnamed empty group is dropped; a named empty one is sent');
  assert.deepEqual(lib.clientsSavePayload(null), { groups: [] });
  assert.equal(lib.clientsSaveError(groups), '');
  assert.equal(lib.clientsSaveError([{ name: '', clients: [{ code: 'AK' }] }]), '分组要有名字');
  assert.equal(lib.clientsSaveError([{ name: '餐厅', clients: [] }, { name: ' 餐厅', clients: [] }]), '有两个「餐厅」');
  // The ⋯ menu offers 整理客户 above 存放说明 when the service knows groups.
  const menu = lib.exportMenuHTML('work', deps, { guide: true, clients: true });
  assert.match(menu, /aria-label="整理客户、存放说明和导出"/);
  assert.ok(menu.indexOf('data-action="organize-clients"') < menu.indexOf('data-action="open-guide"'));
  assert.match(menu, /<button type="button" class="export-option menu-action" data-action="organize-clients"><i data-icon="pencil"><\/i><span>整理客户<\/span><\/button>/);
  assert.doesNotMatch(lib.exportMenuHTML('work', deps, { guide: true }), /organize-clients/);
  assert.match(lib.exportMenuHTML('work', deps, { clients: true }), /aria-label="整理客户和导出"/);
});

test('tables scroll inside a table-wrap, copy buttons say what they copy, and the export list is not a fake menu', () => {
  const items = [{ id: 'f'.repeat(20), kind: 'prompt', title: '提示词A', text: '正文', section: '运营' }];
  const list = lib.itemsHTML(items, 'list', deps);
  assert.match(list, /^<div class="table-wrap"><table class="data-table items-table">/);
  assert.match(list, /aria-label="复制提示词：提示词A"/);
  assert.match(lib.itemCardHTML(items[0], deps), /aria-label="复制提示词：提示词A"/);
  assert.match(lib.markdownHTML('| a | b |\n|---|---|\n| 1 | 2 |', esc), /^<div class="table-wrap md-table"><table>/);
  assert.doesNotMatch(lib.exportMenuHTML('prompt', deps), /role="menu"/);
});
