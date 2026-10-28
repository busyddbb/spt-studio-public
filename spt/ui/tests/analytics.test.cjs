'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const ui = require('../spt.js');
const analytics = require('../analytics.js');
const deps = { esc: ui.esc, icon: () => '', safeLocalURL: ui.safeLocalURL, safeExternalURL: ui.safeExternalURL, platformName: (platform) => platform, cardHTML: () => '' };

const snapshot = (date, metrics, status = 'partial') => ({ date, status, window_start: null, window_end: null, metrics });
const instagram = {
  id: 'ak:instagram', brand_id: 'ak', brand: 'AK', platform: 'instagram', platform_label: 'Instagram', metrics: { followers: 15, views: 5555 }, as_of: '2026-10-06',
  history: [
    snapshot('2026-09-20', { followers: 10, views: 500, reach: 480, interactions: 1 }),
    snapshot('2026-09-27', { followers: null, views: 545, reach: 524, interactions: 1 }),
    snapshot('2026-09-27', { followers: 10, views: 545, reach: 524, interactions: 1 }),
    snapshot('2026-10-06', { followers: 15, views: 5555, reach: null, interactions: 51 }, 'captured'),
  ],
};
const tiktok = { id: 'ak:tiktok', brand_id: 'ak', brand: 'AK', platform: 'tiktok', platform_label: 'TikTok', metrics: {}, history: [] };
const posts = [
  { id: 'p1', account_id: 'ak:instagram', title: '扬州炒饭', format: 'reel', published_at: '2026-10-01', current: true, metrics: { views: 40, interactions: 3 }, metric_window: 'D3', metrics_by_window: { D1: { views: 13 }, D3: { views: 40 } } },
  { id: 'p2', account_id: 'ak:instagram', title: '<b>x</b>', format: 'reel', published_at: '2026-10-02', current: true, metrics: { views: 90 }, metric_window: 'D1', metrics_by_window: { D1: { views: 90 } } },
  { id: 'p3', account_id: 'ak:instagram', title: '无数据', format: 'reel', current: true, metrics: { views: null }, metrics_by_window: {} },
  { id: 'n1', account_id: 'ak:instagram', source_kind: 'metric_node', current: true, metrics: { views: 999 } },
];
const state = { dashboard: { accounts: [instagram, tiktok], posts }, brand: 'all', window: 'latest', analyticsMetric: 'views', analyticsPlatform: 'all', analyticsRange: 'all', today: '2026-10-22' };
const daily = (from, days, value = (index) => 100 + index, status = 'partial') => Array.from({ length: days }, (_, index) => ({ date: new Date(Date.parse(`${from}T00:00:00Z`) + index * 86400000).toISOString().slice(0, 10), value: value(index), status }));

test('series drops unknown values, dedupes dates and keeps order', () => {
  const followers = analytics.series(instagram, 'followers');
  assert.deepEqual(followers.map((point) => [point.date, point.value]), [['2026-09-20', 10], ['2026-09-27', 10], ['2026-10-06', 15]]);
  assert.equal(analytics.series(instagram, 'reach').length, 2);
  assert.deepEqual(analytics.series(tiktok, 'views'), []);
});

test('delta compares with the nearest snapshot at least seven days earlier', () => {
  const change = analytics.delta(analytics.series(instagram, 'views'));
  assert.equal(change.since, '2026-09-27');
  assert.equal(change.diff, 5010);
  assert.equal(change.from, 545);
  assert.equal(change.to, 5555);
  assert.equal(analytics.delta([{ date: '2026-10-06', value: 1 }]), null);
});

test('change labels: small bases show the difference only, big jumps ask for a check, neither is red or green', () => {
  const change = (from, to) => analytics.changeInfo({ diff: to - from, from, to, since: '2026-09-29' });
  assert.deepEqual(change(10, 15), { tone: 'neutral', text: '+5' }, 'under 100 a percentage says nothing');
  assert.deepEqual(change(3000, 3300), { tone: 'up', text: '+300 (+10.0%)' });
  assert.deepEqual(change(4479, 4236), { tone: 'down', text: '-243 (-5.4%)' });
  assert.deepEqual(change(646, 5555), { tone: 'check', text: '+4,909', flag: '变化很大，先核对' });
  assert.equal(change(4000, 1000).tone, 'check', 'a drop to under a third is flagged too');
  assert.equal(change(0, 60).tone, 'check');
  assert.deepEqual(change(0, 10), { tone: 'neutral', text: '+10' });
  assert.deepEqual(change(2, 7), { tone: 'neutral', text: '+5' }, 'tiny numbers are never flagged');
  assert.equal(change(7, 7).text, '持平');
  assert.equal(analytics.changeInfo(null), null);
});

test('近 30/90 天 count back from today, not from the latest snapshot', () => {
  const points = analytics.series(instagram, 'views');
  assert.equal(analytics.rangeStart('30', '2026-10-22'), '2026-09-22');
  assert.equal(analytics.rangeStart('all', '2026-10-22'), null);
  assert.equal(analytics.clip(points, '30', '2026-10-22').length, 2);
  assert.equal(analytics.clip(points, '7', '2026-10-22').length, 0, 'nothing in the last week');
  assert.equal(analytics.clip(points, '30', '2026-10-06').length, 3);
  assert.equal(analytics.clip(points, 'all', '2026-10-22').length, 3);
  assert.equal(analytics.latestDate([instagram, tiktok]), '2026-10-06');
});

test('axis maxima use finer nice steps and the ticks divide them evenly', () => {
  assert.equal(analytics.niceMax(5555 * 1.08), 6000);
  assert.equal(analytics.niceMax(17), 20);
  assert.equal(analytics.niceMax(11), 12);
  assert.equal(analytics.niceMax(1300), 1500);
  assert.equal(analytics.niceMax(2100), 2500);
  assert.equal(analytics.niceMax(7), 8);
  assert.equal(analytics.niceMax(10), 10);
  assert.equal(analytics.niceMax(1.3), 2, 'counts stay whole numbers');
  assert.equal(analytics.niceMax(0.4), 1);
  assert.deepEqual(analytics.axisTicks(6000), [0, 2000, 4000, 6000]);
  assert.deepEqual(analytics.axisTicks(10000), [0, 2000, 4000, 6000, 8000, 10000]);
  assert.deepEqual(analytics.axisTicks(1200), [0, 200, 400, 600, 800, 1000, 1200]);
  assert.deepEqual(analytics.axisTicks(1500), [0, 500, 1000, 1500]);
  assert.deepEqual(analytics.axisTicks(8), [0, 2, 4, 6, 8]);
  assert.deepEqual(analytics.axisTicks(10), [0, 2, 4, 6, 8, 10]);
  assert.deepEqual(analytics.axisTicks(2), [0, 1, 2]);
  assert.deepEqual(analytics.axisTicks(1), [0, 1]);
  for (let value = 1; value < 50000; value = Math.ceil(value * 1.07)) {
    const max = analytics.niceMax(value);
    const ticks = analytics.axisTicks(max);
    assert.ok(max >= value && Number.isInteger(max), `niceMax(${value})`);
    assert.equal(ticks[0], 0);
    assert.equal(ticks[ticks.length - 1], max, `ticks end at ${max}`);
    assert.ok(ticks.length >= 2 && ticks.length <= 7, `${ticks.length} ticks for ${max}`);
    assert.ok(ticks.every((tick, index) => Number.isInteger(tick) && (index === 0 || tick - ticks[index - 1] === ticks[1])), `even whole steps for ${max}`);
  }
  assert.equal(analytics.compact(5555), '5,555');
  assert.equal(analytics.compact(123456), '123.5K');
  assert.equal(analytics.compact(999), '999');
  assert.equal(analytics.compact(null), '—');
});

test('the line chart is drawn at its pixel width, labels each line at its end and keeps colours in CSS', () => {
  const svg = analytics.lineChartSVG([
    { label: 'Instagram', platform: 'instagram', points: analytics.series(instagram, 'views') },
    { label: 'TikTok', platform: 'tiktok', points: [] },
  ], 'views', deps, { width: 720 });
  assert.match(svg, /^<svg class="line-chart" viewBox="0 0 720 259"/);
  assert.match(analytics.lineChartSVG([{ label: 'Instagram', platform: 'instagram', points: analytics.series(instagram, 'views') }], 'views', deps, { width: 390 }), /viewBox="0 0 390 200"/, 'one viewBox unit is one screen pixel');
  assert.equal((svg.match(/<path class="line"/g) || []).length, 1);
  assert.equal((svg.match(/<g class="series series-instagram">/g) || []).length, 1);
  assert.match(svg, /<path class="dot" d="[^"]+"><title>Instagram · 10\/06：5,555<\/title>/, 'a fully recorded day is a filled marker');
  assert.match(svg, /<path class="dot partial" d="[^"]+"><title>Instagram · 09\/20：500<\/title>/, 'a partly recorded day is hollow');
  assert.match(svg, /<text class="axis-label"[^>]*text-anchor="end">6,000<\/text>/, 'y-axis ticks');
  assert.match(svg, /<text class="axis-label"[^>]*text-anchor="end">0<\/text>/);
  assert.match(svg, /<text class="axis-label"[^>]*>09\/20<\/text>/, 'x-axis dates');
  assert.match(svg, /<text class="axis-label"[^>]*>10\/06<\/text>/);
  assert.match(svg, /<g class="series series-instagram end-label">(?:(?!<\/g>).)*<text class="end-name"[^>]*>Instagram<\/text><text class="end-value"[^>]*>5,555<\/text>/, 'platform name sits with the end value');
  assert.doesNotMatch(svg, /#[0-9a-f]{3,6}\b|stroke="|fill="|style=/i);
  assert.equal(analytics.lineChartSVG([{ label: 'TikTok', platform: 'tiktok', points: [] }], 'views', deps), '');
});

test('a line that stops early says so, crowded points keep only the end marker, and the empty stretch to today is shaded', () => {
  const list = [
    { label: 'Instagram', platform: 'instagram', points: daily('2026-09-01', 36) },
    { label: 'Facebook', platform: 'facebook', points: daily('2026-09-01', 31, (index) => 300 + index) },
  ];
  const wide = analytics.lineChartSVG(list, 'views', deps, { width: 1000, from: '2026-09-01', to: '2026-10-22', gapFrom: '2026-10-06' });
  assert.match(wide, /<text class="end-date"[^>]*>截至 10\/01<\/text>/);
  assert.equal((wide.match(/截至/g) || []).length, 1, 'only the line that ends before the others');
  assert.match(wide, /<rect class="gap-band" /);
  assert.match(wide, /<text class="axis-label"[^>]*text-anchor="end">10\/22<\/text>/, 'the axis runs to today');
  assert.ok((wide.match(/<path class="dot partial"/g) || []).length > 30, 'every point is marked when there is room');
  const narrow = analytics.lineChartSVG(list, 'views', deps, { width: 320 });
  assert.equal((narrow.match(/<g class="series series-instagram">(?:(?!<\/g>).)*<\/g>/)[0].match(/class="dot/g) || []).length, 1, 'only the last point when they would touch');
  const ends = [...narrow.matchAll(/<g class="series series-(\w+) end-label">(?:(?!<\/g>).)*?<text class="end-name" x="[\d.]+" y="([\d.]+)"/g)].map((match) => +match[2]);
  assert.equal(ends.length, 2);
  assert.ok(Math.abs(ends[0] - ends[1]) >= 28, 'end labels never sit on top of each other');
});

test('each platform has its own marker shape, and the legend shows the same line and marker', () => {
  const points = analytics.series(instagram, 'views');
  const svg = analytics.lineChartSVG([
    { label: 'rednote', platform: 'xiaohongshu', points },
    { label: 'Google', platform: 'google_business_profile', points },
    { label: '别处', platform: 'mastodon', points },
  ], 'views', deps);
  assert.match(svg, /<g class="series series-rednote">/);
  assert.match(svg, /<g class="series series-google">/);
  assert.match(svg, /<g class="series series-other">/);
  const legend = analytics.legendHTML([{ label: 'Instagram', platform: 'instagram', points }, { label: 'Facebook', platform: 'facebook', points }, { label: 'rednote', platform: 'rednote', points }], deps, true);
  const marks = [...legend.matchAll(/<path class="dot" d="([^"]+)"/g)].map((match) => match[1]);
  assert.equal(marks.length, 3);
  assert.equal(new Set(marks).size, 3, 'circle, square and diamond');
  assert.match(legend, /<span class="series series-facebook"><svg class="legend-key"[^>]*><line class="line"/);
  assert.match(legend, /空心点：那天只记了一部分数字/);
  assert.doesNotMatch(analytics.legendHTML([{ label: 'Instagram', platform: 'instagram', points }], deps, false), /空心点/, 'the note only shows when hollow markers are drawn');
  assert.match(analytics.sparklineSVG(points, 'xiaohongshu'), /^<svg class="sparkline series series-rednote"[^>]*preserveAspectRatio="none"[^>]*><path class="area" d="[^"]+"\/><path class="line" d="[^"]+"\/><\/svg>$/);
  assert.equal(analytics.sparklineSVG(points.slice(0, 1), 'instagram'), '');
});

test('the page renders KPIs, trend, platform cards and a D3 content ranking without metric nodes', () => {
  const html = analytics.renderAnalytics(state, deps);
  assert.match(html, /kpi-card/);
  assert.match(html, /<div class="chart-box" data-chart="trend" data-width="720"><div class="chart-legend">/);
  assert.match(html, /<svg class="line-chart"/);
  assert.match(html, /<section class="panel platform-card empty">(?:(?!<\/section>).)*<p class="small-empty">还没有数据<\/p><a class="text-action" href="#tools\?name=data">导入数据<\/a>/);
  // The pressed D3 button and the D3 浏览 column say which window ranks the list: no caption repeats it.
  assert.match(html, /data-analytics-window="D3" aria-pressed="true" title="发布后 72 小时">D3<\/button>/, 'D3 by default, even when the desk shows the latest numbers');
  assert.match(html, /<div class="panel-head"><h2 class="panel-title" id="content-title">内容表现<\/h2><div class="segmented"/);
  assert.match(html, /<div class="panel-head"><h2 class="panel-title" id="trend-title">趋势<\/h2>/);
  assert.doesNotMatch(html, /浏览排名 ·|每个点是那天记下的数|变化和大约 7 天前比|本机快照|不是实时/);
  assert.doesNotMatch(html, /data-analytics-window="latest"/);
  const start = html.indexOf('<table class="data-table rank-table">');
  const table = html.slice(start, html.indexOf('</table>', start));
  assert.equal((table.match(/<tr>/g) || []).length, 2, 'header + the one post with a D3 number');
  assert.match(table, /<th scope="col">D3 浏览<\/th><th scope="col" class="num extra">D1<\/th><\/tr>/, 'empty D7 and 互动 columns are left out');
  const d1 = analytics.renderAnalytics({ ...state, window: 'D1' }, deps);
  assert.ok(d1.indexOf('data-post-open="p2"') < d1.indexOf('data-post-open="p1"'), 'ranked by views');
  assert.match(d1, /&lt;b&gt;x&lt;\/b&gt;/);
  assert.doesNotMatch(d1, /<b>x<\/b>/);
  assert.match(d1, /10\/02 · Reels/, 'formats read in Chinese or as the platform names them');
});

test('ranking rows show a cover when the post or its work has one', () => {
  const withCover = posts.map((post) => post.id === 'p1' ? { ...post, work_id: 'w1' } : post);
  const html = analytics.renderAnalytics({ ...state, dashboard: { accounts: [instagram, tiktok], posts: withCover }, allWorks: [{ id: 'w1', cover: '/api/works/w1/cover' }] }, deps);
  assert.match(html, /<span class="rank-thumb"><img src="\/api\/works\/w1\/cover" alt="" loading="lazy" decoding="async"><\/span>/);
});

test('an unknown client or an empty dashboard degrades to a message', () => {
  const empty = analytics.renderAnalytics({ ...state, dashboard: { accounts: [], posts: [] } }, deps);
  assert.match(empty, /还没有账号资料/);
  assert.match(empty, /<a class="button primary" href="#tools\?name=accounts">添加账号<\/a>/);
  assert.doesNotMatch(empty, /<p>/, 'one line and the action');
  const other = analytics.renderAnalytics({ ...state, brand: 'nobody' }, deps);
  assert.match(other, /<strong class="kpi-value">—<\/strong><\/section>/, 'the dash alone says there is nothing yet');
  const older = analytics.renderAnalytics({ ...state, analyticsRange: '30', today: '2026-12-20' }, deps);
  assert.match(older, /<strong class="kpi-value">—<\/strong><small>最近一次 10\/06<\/small>/, 'older records outside the range are dated');
});

test('the page is called 数据, uses listboxes, links to the data import, flags stale data and folds empty platforms', () => {
  const html = analytics.renderAnalytics(state, deps);
  // One date under the title; old data turns it into the warning chip.
  assert.match(html, /<header class="page-heading"><div><h1 tabindex="-1">数据<\/h1><p class="page-sub"><span class="chip" data-tone="warn">数据停在 10\/06<\/span><\/p><\/div>/);
  for (const id of ['brand-filter', 'analytics-range', 'analytics-metric']) assert.match(html, new RegExp(`<input type="hidden" id="${id}" value=`));
  assert.doesNotMatch(html, /<select/);
  assert.match(html, /<a class="button" href="#tools\?name=data">导入数据<\/a>/);
  const fresh = analytics.renderAnalytics({ ...state, today: '2026-10-08' }, deps);
  assert.doesNotMatch(fresh, /数据停在/);
  assert.match(fresh, /<h1 tabindex="-1">数据<\/h1><p class="page-sub">截至 10\/06<\/p><\/div>/);
  assert.match(html, /<details class="platform-empty"><summary>1 个平台还没有数据<\/summary>/, 'collapsed while another platform has data');
  assert.match(html, /<section class="panel platform-card series series-instagram">/);
  // Platforms without data get no chip, and are counted once (at the bottom), not again beside the chips.
  assert.match(html, /<button type="button" class="series series-instagram" data-analytics-platform="instagram" aria-pressed="false"><i class="swatch"><\/i>Instagram<\/button><\/div><\/div>/, 'platforms without data get no chip');
  assert.doesNotMatch(html, /chips-note|另外 1 个平台/);
  assert.doesNotMatch(html, /data-analytics-platform="tiktok"/);
  assert.match(html, /<div class="segmented" role="group" aria-label="显示方式"><button type="button" data-analytics-view="chart" aria-pressed="true">图表<\/button><button type="button" data-analytics-view="table" aria-pressed="false">表格<\/button><\/div>/);
  assert.match(html, /<td class="bar-cell series series-instagram"><span class="rank-bar" style="--bar-size:100.0%"><\/span>/);
  assert.equal((html.match(/<div class="table-wrap"><table/g) || []).length, (html.match(/<table/g) || []).length, 'every table scrolls inside its own wrapper');
  assert.doesNotMatch(html, /#[0-9a-f]{6}\b|--bar-color|chip-dot/i);
  const onlyEmpty = analytics.renderAnalytics({ ...state, analyticsPlatform: 'tiktok' }, deps);
  assert.match(onlyEmpty, /data-analytics-platform="tiktok" aria-pressed="true"/, 'the platform being looked at keeps its chip');
  assert.match(onlyEmpty, /<details class="platform-empty" open>/, 'open when nothing else has data');
  assert.match(onlyEmpty, /还没有浏览的记录.*href="#tools\?name=data">导入数据/);
});

test('近 30 天 runs the axis to today and shades the days without data', () => {
  const html = analytics.renderAnalytics({ ...state, analyticsRange: '30' }, deps);
  assert.match(html, /<rect class="gap-band" /);
  assert.doesNotMatch(html, /chart-note|阴影部分/, 'the shaded days explain themselves');
  assert.doesNotMatch(analytics.renderAnalytics({ ...state, analyticsRange: '30', today: '2026-10-07' }, deps), /gap-band/, 'a day without data is not a gap yet');
  const week = analytics.renderAnalytics({ ...state, analyticsRange: '30', today: '2026-11-20' }, deps);
  assert.match(week, /近 30 天没有浏览的记录<\/strong><div class="empty-actions"><button type="button" class="button primary" data-analytics-range="all">看全部时间<\/button><a class="button" href="#tools\?name=data">导入数据<\/a><\/div>/, 'older records: one button widens the range');
});

test('the table view shows the same numbers as the chart, newest first', () => {
  const html = analytics.renderAnalytics({ ...state, analyticsView: 'table' }, deps);
  assert.match(html, /data-analytics-view="table" aria-pressed="true"/);
  assert.doesNotMatch(html, /<svg class="line-chart"/);
  const start = html.indexOf('<table class="data-table">');
  const table = html.slice(start, html.indexOf('</table>', start));
  assert.match(table, /<caption class="sr-only">浏览：每次记下的数<\/caption>/);
  assert.match(table, /<th scope="col" class="num"><span class="series series-instagram"><i class="swatch"><\/i>Instagram<\/span><\/th>/);
  assert.match(table, /<th scope="row">2026-10-06<\/th><td class="num">5,555<\/td>/);
  assert.match(table, /<th scope="row">2026-09-20<\/th><td class="num">500<\/td>/);
  assert.ok(table.indexOf('2026-10-06') < table.indexOf('2026-09-20'));
  assert.doesNotMatch(table, /TikTok/, 'platforms without samples stay out of the table');
});

test('KPI cards only add up numbers from the same day; an older platform row is muted and dated instead of explained', () => {
  const facebook = { id: 'ak:facebook', brand_id: 'ak', brand: 'AK', platform: 'facebook', platform_label: 'Facebook', history: [snapshot('2026-10-06', { followers: 7, views: 4236 }), snapshot('2026-10-01', { views: 4000 })] };
  const html = analytics.renderAnalytics({ ...state, dashboard: { accounts: [instagram, facebook, tiktok], posts } }, deps);
  const cards = html.split('<section class="panel kpi-card').slice(1).map((part) => part.slice(0, part.indexOf('</section>')));
  assert.match(cards[0], /<strong class="kpi-value">22<\/strong>/);
  assert.match(cards[0], /<li class="series series-instagram"><i class="swatch"><\/i><span>Instagram<\/span><span class="num">15<\/span><\/li>/);
  assert.match(cards[0], /<li class="series series-facebook"><i class="swatch"><\/i><span>Facebook<\/span><span class="num">7<\/span><\/li><\/ul>$/, 'same-day rows need no caption under them');
  assert.doesNotMatch(html, /相加|只算|只加|没算进去/);
  const older = { ...facebook, history: [snapshot('2026-10-01', { followers: 7 })] };
  const mixed = analytics.renderAnalytics({ ...state, dashboard: { accounts: [instagram, older, tiktok], posts } }, deps);
  const followers = mixed.slice(mixed.indexOf('<section class="panel kpi-card'), mixed.indexOf('</section>', mixed.indexOf('<section class="panel kpi-card')));
  assert.match(followers, /<strong class="kpi-value">15<\/strong>/, 'the 10/01 number is not added to the 10/06 one');
  assert.match(followers, /<li class="series series-facebook older" title="10\/01 的数，没算进合计"><i class="swatch"><\/i><span>Facebook<\/span><small>10\/01<span class="sr-only">，没算进合计<\/span><\/small><span class="num">7<\/span><\/li><\/ul>$/);
  const single = analytics.renderAnalytics(state, deps);
  const tile = single.slice(single.indexOf('<section class="panel kpi-card'), single.indexOf('</section>', single.indexOf('<section class="panel kpi-card')));
  assert.match(tile, /<span class="metric-label">粉丝<\/span><\/div><strong class="kpi-value">15<\/strong><svg class="sparkline series series-instagram"/, 'the sparkline sits under the number, not beside the label');
  assert.match(tile, /<p class="kpi-change"><span class="kpi-delta neutral">\+5<\/span> 较 09\/27<\/p><small>Instagram<\/small>$/, 'the page date covers it: no date repeated');
  const views = single.split('<section class="panel kpi-card')[2];
  assert.match(views, /<span class="kpi-delta check">\+5,010<\/span> 较 09\/27 <span class="chip" data-tone="warn">变化很大，先核对<\/span>/);
  assert.match(views, /<small>28 天累计<\/small>/);
  const reach = single.split('<section class="panel kpi-card')[3];
  assert.match(reach, /<small>Instagram · 09\/27<\/small><\/section>/, 'a metric last recorded before the page date says when');
  // The platform card dates itself only when it is behind the page date, and its changes say what they compare with.
  assert.doesNotMatch(single, /<section class="panel platform-card series series-instagram">(?:(?!<\/section>).)*截至/);
  assert.match(single, /<small class="check" title="较 09\/27">\+5,010 · 先核对<\/small>/);
  const behind = analytics.renderAnalytics({ ...state, dashboard: { accounts: [instagram, { ...older, platform_label: 'Facebook' }], posts } }, deps);
  assert.match(behind, /<section class="panel platform-card series series-facebook">(?:(?!<\/section>).)*<p class="source-caption">截至 10\/01<\/p><\/section>/);
});

test('a window without data offers the windows that have some instead of a dead end', () => {
  const html = analytics.renderAnalytics({ ...state, window: 'D7' }, deps);
  assert.match(html, /<strong>D7 还没有浏览数据<\/strong>.*<button type="button" class="button" data-analytics-window="D1">看 D1<\/button><button type="button" class="button" data-analytics-window="D3">看 D3<\/button>/);
  assert.equal(analytics.rankWindow({ window: 'latest' }), 'D3');
  assert.equal(analytics.rankWindow({ window: 'D7' }), 'D7');
});

test('without any D1/D3/D7 numbers the ranking uses the latest snapshot and has no window buttons', () => {
  const latestOnly = [
    { id: 'c1', account_id: 'ak:instagram', title: '甲', published_at: '2026-10-01', current: true, metric_window: null, observed_at: '2026-10-20', metrics: { views: 120, interactions: 9 }, metrics_by_window: { D1: {}, D3: {}, D7: {} } },
    { id: 'c2', account_id: 'ak:instagram', title: '乙', published_at: '2026-10-02', current: true, metric_window: null, observed_at: '2026-10-21', metrics: { views: 340 }, metrics_by_window: {} },
  ];
  const html = analytics.renderAnalytics({ ...state, window: 'D7', dashboard: { accounts: [instagram, tiktok], posts: latestOnly } }, deps);
  assert.match(html, /<div class="panel-head"><h2 class="panel-title" id="content-title">内容表现<\/h2><\/div>/, 'nothing to switch between');
  assert.doesNotMatch(html, /data-analytics-window=|还没有浏览数据/);
  assert.match(html, /<caption class="sr-only">按 最新一次 浏览排名的内容<\/caption><thead><tr><th scope="col" class="num">#<\/th><th scope="col">内容<\/th><th scope="col">最新 浏览<\/th><th scope="col" class="num extra">最新 互动<\/th><\/tr>/);
  assert.ok(html.indexOf('data-post-open="c2"') < html.indexOf('data-post-open="c1"'), 'ranked by the latest views');
  assert.match(html, /<td class="num extra">9<\/td>/);
  const mixed = analytics.renderAnalytics({ ...state, dashboard: { accounts: [instagram, tiktok], posts: [...posts, ...latestOnly] } }, deps);
  assert.match(mixed, /data-analytics-window="D3" aria-pressed="true"/, 'the D1/D3/D7 buttons stay while any post has those numbers');
  assert.match(mixed, /<th scope="col">D3 浏览<\/th>/);
  assert.doesNotMatch(mixed, /最新 浏览/);
  const none = analytics.renderAnalytics({ ...state, dashboard: { accounts: [instagram, tiktok], posts: [posts[2]] } }, deps);
  assert.match(none, /<strong>还没有内容的浏览数据<\/strong>/);
});

test('snapshots without a real calendar date are left out of every chart and label', () => {
  const odd = { ...instagram, history: [...instagram.history, snapshot('<b>soon</b>', { views: 1 })] };
  assert.equal(analytics.series(odd, 'views').length, 3);
  assert.equal(analytics.latestDate([odd]), '2026-10-06');
  assert.doesNotMatch(analytics.renderAnalytics({ ...state, dashboard: { accounts: [odd, tiktok], posts } }, deps), /<b>soon<\/b>/);
});

// ---- 工作区记的数据：排名里的比率列、原因标签 ----
const rednoteA = { id: 'parenting:rednote', brand_id: 'parenting', brand: '示例创作者', name: '示例创作者', platform: 'rednote', platform_label: 'rednote', handle: 'https://www.rednote.com/user/profile/example', data_state: 'workspace', as_of: '2026-10-21T21:35:00-07:00', metrics: {}, history: [] };
const rednoteB = { ...rednoteA, id: 'parenting:rednote:小幽灵', name: '小幽灵', handle: '小幽灵', as_of: '2026-10-20' };
const wsPost = {
  id: 'ws1', account_id: 'parenting:rednote', work_id: 'w-ws', title: '小车先停好', current: true, source_kind: 'workspace_metrics', published_at: '2026-09-08T20:00:00-07:00', metric_window: 'D7', observed_at: '2026-09-15T21:35:00-07:00',
  metrics: { views: 92, likes: 8, completion_rate: 63, ctr: 12.5 },
  metrics_by_window: { D1: { views: 72 }, D3: { views: 82, completion_rate: 58.4 }, D7: { views: 92, completion_rate: 63, ctr: 12.5 } },
  history: [{ window: 'D1', observed_at: '2026-09-09T20:30:00-07:00', age_hours: 24.5, metrics: { views: 72 } }, { window: 'D7', observed_at: '2026-09-15T21:35:00-07:00', age_hours: 169.6, metrics: { views: 92 } }],
  retention: [], analyses: [{ date: '2026-09-11', node: 'D3', conclusion: '开头 3 秒没有冲突', tags: ['开头弱', '封面'] }, { date: '2026-09-16', node: 'D7', conclusion: '结尾没有引导', tags: ['结尾无引导'] }],
};
const wsPost2 = { ...wsPost, id: 'ws2', account_id: rednoteB.id, title: '第二篇', metrics_by_window: { D3: { views: 10 } }, metrics: { views: 10 }, history: [], analyses: [{ date: '2026-10-01', node: 'D1', conclusion: '封面太暗', tags: ['封面'] }] };

test('内容排名 adds 完播率 / 点击率 columns only when a shown post recorded them', () => {
  const data = { accounts: [instagram, tiktok, rednoteA], posts: [...posts, wsPost] };
  const html = analytics.renderAnalytics({ ...state, dashboard: data }, deps);
  assert.match(html, /<th scope="col" class="num extra">D1<\/th><th scope="col" class="num extra">D7<\/th><th scope="col" class="num extra">完播率<\/th><\/tr>/, 'D3: the rate recorded at D3, nothing else');
  assert.doesNotMatch(html, /点击率|平均观看秒/);
  assert.match(html, /<td class="num extra">58.4%<\/td><\/tr>/);
  assert.match(html, /<td class="num extra">—<\/td><\/tr>/, 'a post without the rate shows a dash');
  assert.ok(html.indexOf('data-post-open="ws1"') < html.indexOf('data-post-open="p1"'), 'ranked by D3 views across platforms');
  assert.match(html, /09\/08 · rednote<\/span>/, 'one rednote account: the platform name alone');
  const d7 = analytics.renderAnalytics({ ...state, window: 'D7', dashboard: data }, deps);
  assert.match(d7, /<th scope="col" class="num extra">D3<\/th><th scope="col" class="num extra">完播率<\/th><th scope="col" class="num extra">点击率<\/th><\/tr>/);
  assert.match(d7, /<td class="num extra">63%<\/td><td class="num extra">12.5%<\/td><\/tr>/);
  assert.doesNotMatch(analytics.renderAnalytics(state, deps), /完播率|点击率/, 'imported posts without rates: no column');
  assert.equal(analytics.latestDate([rednoteA], [wsPost]), '2026-09-15', 'the page date counts workspace records');
  assert.equal(analytics.latestDate([instagram], [wsPost]), '2026-10-06', 'but only for the accounts being looked at');
  assert.match(analytics.renderAnalytics({ ...state, brand: 'parenting', dashboard: data }, deps), /<p class="page-sub"><span class="chip" data-tone="warn">数据停在 09\/15<\/span><\/p>/);
});

test('原因标签 lists each tag with its count and the posts carrying it, within the account filter, and narrows to one tag', () => {
  const data = { accounts: [instagram, rednoteA, rednoteB], posts: [...posts, wsPost, wsPost2], snapshot: { analysis_tags: [{ tag: '封面', count: 2, post_ids: ['ws1', 'ws2'] }, { tag: '开头弱', count: 1, post_ids: ['ws1'] }, { tag: '结尾无引导', count: 1, post_ids: ['ws1'] }] } };
  const base = { ...state, dashboard: data };
  const rank = analytics.renderAnalytics(base, deps);
  assert.match(rank, /<h2 class="panel-title" id="content-title">内容表现<\/h2><div class="segmented" role="group" aria-label="内容怎么看"><button type="button" data-analytics-content="rank" aria-pressed="true">排名<\/button><button type="button" data-analytics-content="tags" aria-pressed="false">原因标签<\/button><\/div><div class="segmented" role="group" aria-label="按哪一次排名">/);
  assert.doesNotMatch(analytics.renderAnalytics(state, deps), /data-analytics-content/, 'no analyses anywhere: nothing to switch to');
  assert.match(rank, /09\/08 · rednote · 示例创作者<\/span>/, 'two rednote accounts: the handle tells them apart');
  const html = analytics.renderAnalytics({ ...base, analyticsContent: 'tags' }, deps);
  assert.match(html, /data-analytics-content="tags" aria-pressed="true"/);
  assert.doesNotMatch(html, /rank-table|data-analytics-window/);
  const start = html.indexOf('<table class="data-table tag-table">');
  const table = html.slice(start, html.indexOf('</table>', start));
  assert.match(table, /<thead><tr><th scope="col">原因<\/th><th scope="col" class="num">内容数<\/th><th scope="col">内容<\/th><\/tr><\/thead>/);
  assert.deepEqual([...table.matchAll(/data-analytics-tag="([^"]+)"/g)].map((match) => match[1]), ['封面', '开头弱', '结尾无引导'], 'most common first, ties in the order they came');
  assert.match(table, /<tr><th scope="row"><button type="button" class="chip tag-chip" data-analytics-tag="封面" aria-pressed="false">封面<\/button><\/th><td class="num">2<\/td><td class="tag-posts"><div class="chip-row"><button type="button" class="chip tag-post" data-post-open="ws1" title="rednote · 示例创作者 · 09\/08">小车先停好<\/button><button type="button" class="chip tag-post" data-post-open="ws2" title="rednote · 小幽灵 · 09\/08">第二篇<\/button><\/div><\/td><\/tr>/);
  assert.doesNotMatch(html, /<select/);
  assert.equal((html.match(/<div class="table-wrap"><table/g) || []).length, (html.match(/<table/g) || []).length, 'every table scrolls inside its own wrapper');
  assert.match(analytics.renderAnalytics({ ...base, analyticsContent: 'tags', brand: 'ak' }, deps), /<div class="empty-state compact"><strong>还没有分析<\/strong><\/div>/, 'another client: one line');
  assert.match(analytics.renderAnalytics({ ...base, analyticsContent: 'tags', brand: 'ak' }, deps), /data-analytics-content="tags" aria-pressed="true"/, 'the switch stays so there is a way back');
  const one = analytics.renderAnalytics({ ...base, analyticsContent: 'tags', analyticsTag: '开头弱' }, deps);
  assert.equal((one.match(/<tr><th scope="row">/g) || []).length, 1);
  assert.match(one, /data-analytics-tag="开头弱" aria-pressed="true"/);
  assert.match(one, /<div class="post-list-foot"><span class="source-caption">共 3 个原因<\/span><button type="button" class="text-action" data-analytics-tag="">全部 <\/button><\/div>/);
  assert.match(analytics.renderAnalytics({ ...base, analyticsContent: 'tags', analyticsTag: '节奏慢' }, deps), /<strong>还没有「节奏慢」的分析<\/strong><button type="button" class="button" data-analytics-tag="">全部原因<\/button>/);
  const derived = analytics.analysisTags({}, [wsPost, wsPost2]);
  assert.deepEqual(derived.map((row) => [row.tag, row.count]), [['封面', 2], ['开头弱', 1], ['结尾无引导', 1]], 'without the snapshot index the posts’ own analyses are counted');
  assert.deepEqual(analytics.analysisTags({ snapshot: { analysis_tags: [{ tag: '封面', post_ids: ['nope'] }] } }, [wsPost]).map((row) => row.tag), ['开头弱', '封面', '结尾无引导'], 'ids outside the scope do not count');
});

test('读数据 shows only in the Mac app and turns busy while reading', () => {
  assert.equal(analytics.readButtonHTML({ metricsReader: false }), '');
  assert.match(analytics.readButtonHTML({ metricsReader: true }), /data-action="read-metrics"[^>]*>读数据</);
  const busy = analytics.readButtonHTML({ metricsReader: true, metricsReading: true });
  assert.match(busy, /disabled/);
  assert.doesNotMatch(busy, /data-action/);
});
