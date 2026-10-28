'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const ui = require('../spt.js');
const notes = require('../notes.js');
const deps = { esc: ui.esc, icon: (name) => `<i data-icon="${name}"></i>` };

const snapshot = {
  folder: '工作区/便签', ready: true,
  ropes: [
    { name: '随手记', notes: [
      { id: '20261021-120000-aaaa', rope: '随手记', text: 'AK 下周三拍菜单\n带三脚架', color: 'mint', date: '2026-10-28', created: '2026-10-21', updated_at: '2026-10-21T12:00:00+08:00' },
      { id: '20261021-130000-bbbb', rope: '随手记', text: '<b>别</b>', color: 'nope', date: '', created: '2026-10-21', updated_at: '2026-10-21T13:00:00+08:00' },
    ] },
    { name: 'AK', notes: [] },
  ],
};

test('tilt is small and stable for the same note', () => {
  const angle = notes.tilt('20261021-120000-aaaa');
  assert.equal(angle, notes.tilt('20261021-120000-aaaa'));
  assert.ok(Math.abs(angle) <= 2);
});

test('drop position follows the pointer row by row on the board', () => {
  // two rows of three, 100px wide, 150px tall
  const boxes = [0, 120, 240, 0, 120, 240].map((left, index) => ({ left, top: index < 3 ? 0 : 180, width: 100, height: 150 }));
  assert.equal(notes.dropIndex(boxes, 10, 50), 0);
  assert.equal(notes.dropIndex(boxes, 160, 50), 1);
  assert.equal(notes.dropIndex(boxes, 400, 50), 3);   // right of the first row: end of that row
  assert.equal(notes.dropIndex(boxes, 10, 250), 3);
  assert.equal(notes.dropIndex(boxes, 400, 900), 6);  // below everything: last
  assert.equal(notes.dropIndex(boxes, 30, 160), 0);   // in the gap: nearest row
  assert.equal(notes.dropIndex([], 10, 10), 0);
});

test('a note sits on its own date, otherwise on the day it was written', () => {
  assert.equal(notes.dayOf(snapshot.ropes[0].notes[0]), '2026-10-28');
  assert.equal(notes.dayOf(snapshot.ropes[0].notes[1]), '2026-10-21');
  assert.equal(notes.dayOf({}), '');
});

test('months start on Monday, fill whole weeks and step across years', () => {
  const days = notes.monthDays('2026-10');
  assert.equal(days.length % 7, 0);
  assert.equal(days[0].date, '2026-09-28');   // 2026-10-01 is a Thursday
  assert.equal(days.find((day) => day.inMonth).date, '2026-10-01');
  assert.equal(days.filter((day) => day.inMonth).length, 31);
  assert.equal(notes.shiftMonth('2026-12', 1), '2027-01');
  assert.equal(notes.shiftMonth('2026-01', -1), '2025-12');
});

test('the board draws one group per folder with no rope, escapes text and falls back to lilac', () => {
  const html = notes.pageHTML(snapshot, false, '', deps);
  assert.equal((html.match(/class="note-group(?: is-empty)?"/g) || []).length, 2);
  assert.doesNotMatch(html, /rope-line/);
  assert.match(html, /note-tape/);
  assert.doesNotMatch(html, /page-sub|工作区\/便签|notes-foot|拖动便签/, 'nothing under the title (groups carry their counts) and no footnote under the board');
  assert.match(html, /<span class="note-group-tag">随手记<\/span><small>2 张<\/small>/);
  assert.match(html, /note note-mint/);
  assert.match(html, /note note-lilac/);
  assert.match(html, /&lt;b&gt;别&lt;\/b&gt;/);
  assert.doesNotMatch(html, /<b>别<\/b>/);
  assert.match(html, /data-note-new="AK"/);
  assert.match(html, /data-notes-view="board" aria-pressed="true"/);
});

test('the calendar puts notes on their days and offers each day for a new note', () => {
  const html = notes.pageHTML(snapshot, false, '', deps, { mode: 'calendar', month: '2026-10', today: '2026-10-21' });
  assert.match(html, /2026 年 10 月/);
  assert.match(html, /data-notes-view="calendar" aria-pressed="true"/);
  const day = (date) => html.slice(html.indexOf(`data-date="${date}"`), html.indexOf('</div></div>', html.indexOf(`data-date="${date}"`)));
  assert.match(day('2026-10-28'), /20261021-120000-aaaa/);
  assert.match(day('2026-10-21'), /20261021-130000-bbbb/);
  assert.match(html, /class="cal-day cal-today" data-date="2026-10-21"/);
  assert.match(html, /data-cal-new="2026-10-05"/);
  assert.doesNotMatch(html, /<b>别<\/b>/);
  assert.doesNotMatch(html, /notes-foot|写了日期的便签/, 'the calendar explains itself: no footnote');
});

test('a busy day folds into “还有 N 张” and opens a day sheet', () => {
  const busy = { ropes: [{ name: 'A', notes: Array.from({ length: 5 }, (_, index) => ({ id: `20261021-12000${index}-aaaa`, rope: 'A', text: `n${index}`, created: '2026-10-21' })) }] };
  const html = notes.calendarHTML(busy, '2026-10', '2026-10-21', deps);
  assert.match(html, /还有 2 张/);
  assert.equal((notes.dayHTML(busy, '2026-10-21', deps).match(/class="day-note/g) || []).length, 5);
  assert.match(notes.dayHTML(busy, '2026-10-21', deps), /<div class="note-editor day-sheet" data-day="2026-10-21">.*data-day="2026-10-21"><span>n0/);
});

test('empty, missing workspace and error states are one line and one action', () => {
  const empty = notes.pageHTML({ ropes: [], ready: true }, false, '', deps);
  assert.match(empty, /<h2>这里空空的<\/h2><button type="button" class="button primary" data-note-new="">/);
  assert.match(empty, /贴第一张/);
  assert.match(notes.pageHTML({ ropes: [], ready: false }, false, '', deps), /<h2>还没有工作区<\/h2><a class="button primary" href="#settings">去设置<\/a>/);
  assert.match(notes.pageHTML(null, false, '读不到', deps), /读不到/);
  assert.doesNotMatch(notes.pageHTML(null, true, '', deps), /page-sub/, 'while loading the spinner speaks, not a sub-line');
});

test('the editor keeps the note, its group, colour and date; new notes take the chosen group and day', () => {
  const note = snapshot.ropes[0].notes[0];
  const edit = notes.editorHTML(note, snapshot.ropes, '', deps);
  assert.match(edit, /note-editor note-mint/);
  assert.match(edit, /value="mint" checked/);
  assert.match(edit, /data-note-remove="20261021-120000-aaaa"/);
  // The group picker is a listbox now: its hidden input carries the chosen group.
  assert.match(edit, /<input type="hidden" id="note-rope" value="随手记">/);
  assert.doesNotMatch(edit, /<select/);
  assert.match(edit, /id="note-date" value="2026-10-28"/);
  const fresh = notes.editorHTML(null, snapshot.ropes, 'AK', deps, '2026-11-02');
  assert.match(fresh, /<input type="hidden" id="note-rope" value="AK">/);
  assert.match(fresh, /id="note-rope-opt-1" data-value="AK" aria-selected="true"/);
  assert.match(fresh, /id="note-date" value="2026-11-02"/);
  assert.doesNotMatch(fresh, /data-note-remove/);
});

test('the overview rail puts this week\'s dated notes first, then the latest', () => {
  const thisWeek = notes.railHTML(snapshot, { ...deps, today: '2026-10-21' });
  assert.ok(thisWeek.indexOf('20261021-120000-aaaa') < thisWeek.indexOf('20261021-130000-bbbb'));
  assert.match(thisWeek, /<h2 class="panel-title">今天和这周<\/h2>/);
  assert.match(thisWeek, /· 10月28日<\/small>/);
  const later = notes.railHTML(snapshot, { ...deps, today: '2026-12-01' });
  assert.ok(later.indexOf('20261021-130000-bbbb') < later.indexOf('20261021-120000-aaaa'));
  assert.match(later, /<h2 class="panel-title">便签<\/h2>/);
  assert.match(notes.railHTML({ ropes: [] }, deps), /还没有便签/);
});

test('board notes are reachable by keyboard and expose their shortcuts without a hint line', () => {
  const html = notes.pageHTML(snapshot, false, '', deps);
  const cards = html.match(/<article class="note [^>]*>/g);
  assert.equal(cards.length, 2);
  for (const card of cards) {
    assert.match(card, /tabindex="0"/);
    assert.doesNotMatch(card, /role="button"/);
    assert.match(card, /data-note="2026/);
    assert.match(card, /aria-keyshortcuts="Meta\+C Alt\+ArrowUp Alt\+ArrowDown"/);
    assert.doesNotMatch(card, /aria-describedby/);
  }
  assert.match(cards[0], /aria-label="便签：AK 下周三拍菜单，10月28日"/);
  // 设置 › 快捷键 is the one place that lists shortcuts.
  assert.doesNotMatch(html, /notes-kbd-hint|⌥↑/);
  assert.match(html, /note-tape/);
  assert.match(html, /style="--tilt:-?[\d.]+deg"/);
});

test('the notes header has a search field with a live count, only when there are notes', () => {
  const html = notes.pageHTML(snapshot, false, '', deps, { query: '<AK>' });
  assert.match(html, /<header class="page-heading"><div><h1 tabindex="-1">便签<\/h1><p class="result-count" id="notes-count" aria-live="polite"><\/p><\/div>/);
  assert.match(html, /<div class="search notes-search"><i data-icon="magnifying-glass"><\/i><label class="sr-only" for="notes-search">搜索便签<\/label><input id="notes-search" type="search" placeholder="搜索便签" autocomplete="off" value="&lt;AK&gt;"><\/div>/);
  assert.match(html, /<button type="button" class="button primary" data-note-new="">/, 'the header button implies no group, so the last-used one can apply');
  assert.match(notes.pageHTML(snapshot, false, '', deps, { mode: 'calendar', month: '2026-10', today: '2026-10-21' }), /id="notes-search"/);
  const empty = notes.pageHTML({ ropes: [], ready: true }, false, '', deps);
  assert.doesNotMatch(empty, /notes-search|notes-count/);
});

test('the editor keeps the version it opened, a copy action, and hidden discard and conflict bars', () => {
  const note = snapshot.ropes[0].notes[0];
  const edit = notes.editorHTML(note, snapshot.ropes, '', deps);
  assert.match(edit, /<input type="hidden" id="note-updated" value="2026-10-21T12:00:00\+08:00">/);
  assert.match(edit, /<input type="hidden" id="note-id" value="20261021-120000-aaaa"><input type="hidden" id="note-from" value="随手记">/);
  assert.match(edit, /<button type="button" class="text-action" data-note-copy>复制文字<\/button>/);
  assert.match(edit, /<div class="note-discard" id="note-discard" role="alert" hidden><p>这张便签还没保存。<\/p><div class="note-bar-actions"><button type="button" class="button small" data-note-discard-keep>继续编辑<\/button><button type="button" class="button small danger" data-note-discard>不保存<\/button><button type="submit" class="button small primary">保存<\/button><\/div><\/div>/);
  assert.match(edit, /<div class="note-conflict" id="note-conflict" role="alert" hidden><p>这张便签刚被改过（可能是 Claude 或 Codex）。<\/p><blockquote class="note-conflict-text"><\/blockquote><div class="note-bar-actions"><button type="button" class="button small" data-note-conflict-load>换成新内容<\/button><button type="button" class="button small primary" data-note-conflict-keep>保留我的<\/button><\/div><\/div>/);
  assert.ok(edit.indexOf('id="note-discard"') < edit.indexOf('class="note-editor-foot"') && edit.indexOf('id="note-conflict"') < edit.indexOf('class="note-editor-foot"'), 'bars sit above the footer');
  assert.doesNotMatch(edit, /⌘↩/, 'no shortcut hint in the footer');
  assert.match(edit, /<span class="note-hint"><\/span><button type="button" class="button" data-action="close-note">取消<\/button><button type="submit" class="button primary" aria-keyshortcuts="Meta\+Enter">保存<\/button>/);
  assert.match(edit, /<span class="listbox-label" id="note-rope-label">分组<\/span>/);
  const fresh = notes.editorHTML(null, snapshot.ropes, 'AK', deps);
  assert.doesNotMatch(fresh, /data-note-copy/);
  assert.match(fresh, /id="note-updated" value=""/);
  assert.doesNotMatch(fresh, /data-day-back/);
  const fromDay = notes.editorHTML(note, snapshot.ropes, '', deps, '', '2026-10-22');
  assert.match(fromDay, /^<form class="note-editor note-mint" id="note-form" method="dialog"><button type="button" class="text-action note-back" data-day-back="2026-10-22"><i data-icon="caret-left"><\/i>10月22日<\/button><header/);
  assert.doesNotMatch(notes.editorHTML(note, snapshot.ropes, '', deps, '', '"><b>x'), /data-day-back/);
});

test('taken-down notes wait on a shelf at the bottom, hidden when there are none', () => {
  assert.doesNotMatch(notes.pageHTML(snapshot, false, '', deps), /notes-shelf/);
  assert.doesNotMatch(notes.pageHTML({ ...snapshot, shelf: [] }, false, '', deps), /notes-shelf/);
  const shelf = [{ id: '20261020-090000-cccc', rope: '随手记', text: '<旧>待办\n第二行', color: 'pink', updated_at: '2026-10-20T09:00:00+08:00', taken_down_at: '2026-10-20T18:00:00+08:00' }];
  const html = notes.pageHTML({ ...snapshot, shelf }, false, '', deps);
  assert.match(html, /<details class="notes-shelf"><summary>已撤下 <span class="nav-count">1<\/span><\/summary><div class="shelf-bar"><button type="button" class="button small danger" data-shelf-clear="1">清空<\/button><\/div><ul class="shelf-list">/);
  assert.match(html, /<li class="shelf-item" data-color="pink"><p class="shelf-text">&lt;旧&gt;待办\n第二行<\/p><span class="shelf-meta">随手记 · 10\/20 撤下<\/span><span class="shelf-actions"><button type="button" class="button small" data-note-restore="20261020-090000-cccc" data-note-rope="随手记" aria-label="放回：&lt;旧&gt;待办">放回<\/button><button type="button" class="button small danger" data-note-delete="20261020-090000-cccc" data-note-rope="随手记" data-shelf-item aria-label="移到废纸篓：&lt;旧&gt;待办">删除<\/button><\/span><\/li>/);
  assert.doesNotMatch(html, /<summary>[^]*<button[^]*<\/summary>/, 'no button inside the summary');
  assert.ok(html.lastIndexOf('notes-shelf') > html.lastIndexOf('note-group'), 'the shelf is at the bottom');
  assert.match(notes.pageHTML({ ropes: [], ready: true, shelf }, false, '', deps), /data-note-restore/, 'with every group gone the way back is still there');
  assert.match(notes.pageHTML({ ...snapshot, shelf }, false, '', deps, { mode: 'calendar', month: '2026-10', today: '2026-10-21' }), /notes-shelf/);
});

test('calendar days with notes carry a count for the phone badge', () => {
  const html = notes.calendarHTML(snapshot, '2026-10', '2026-10-21', deps);
  assert.match(html, /<div class="cal-day" data-date="2026-10-28" data-count="1">/);
  assert.match(html, /<div class="cal-day cal-today" data-date="2026-10-21" data-count="1">/);
  assert.match(html, /<div class="cal-day" data-date="2026-10-05">/);
  assert.doesNotMatch(html, /data-count="0"/);
});

test('a group with more notes than the board shows says so quietly', () => {
  const html = notes.pageHTML({ ropes: [{ name: '多', notes: [], hidden: 3 }], ready: true }, false, '', deps);
  assert.match(html, /还有 3 张没显示/);
  assert.match(html, /data-note-new="多" data-note-rope="多"/);
  assert.doesNotMatch(notes.pageHTML(snapshot, false, '', deps), /张没显示/);
});

test('a day with notes opens its list; an empty day starts a note; undated chips are marked', () => {
  const html = notes.pageHTML(snapshot, false, '', deps, { mode: 'calendar', month: '2026-10', today: '2026-10-21' });
  assert.match(html, /<button type="button" class="cal-num" data-cal-day="2026-10-28" aria-label="10月28日，1 张便签，打开这天">/);
  assert.match(html, /<button type="button" class="cal-num" data-cal-new="2026-10-05" aria-label="10月5日，在这天写一张">/);
  assert.match(html, /class="cal-add" data-cal-new="2026-10-05" tabindex="-1"/);
  assert.match(html, /class="cal-chip note-[a-z]+ is-undated"[^>]*data-note="20261021-130000-bbbb"/);
  assert.match(html, /aria-label="随手记 · AK 下周三拍菜单"/);
});

test('cards show the first line as a title and keep the copy button out of the Tab order', () => {
  const html = notes.pageHTML(snapshot, false, '', deps);
  assert.match(html, /<p class="note-text"><span class="note-title">[^<]+<\/span>/);
  assert.match(html, /<button type="button" class="note-copy" data-note-copy-card="20261021-120000-aaaa" data-rope="[^"]+" tabindex="-1" aria-label="复制这张便签的文字"/);
  assert.match(html, /<time class="note-day" datetime="2026-10-28" title="放在这天">10月28日<\/time>/);
  assert.match(html, /<time class="note-written" datetime="2026-10-21">写于 10月21日<\/time>/);
});

test('the editor can start a new group; the date field carries only its label', () => {
  const html = notes.editorHTML(null, snapshot.ropes, 'AK', deps, '', '');
  assert.match(html, new RegExp(`data-value="${notes.NEW_ROPE}"[^>]*><span class="listbox-option-label">＋ 新分组…`));
  assert.match(html, /<label class="note-pick note-rope-new" hidden>/);
  assert.match(html, /<label class="note-pick"><span>放到哪天<\/span><input type="date" id="note-date" value=""><\/label>/);
  assert.doesNotMatch(html, /note-date-help|不填就放在/);
});

test('a saved note can be deleted from the editor (⌘⌫ too); a new one cannot; the shelf clears as a whole', () => {
  const note = snapshot.ropes[0].notes[0];
  const edit = notes.editorHTML(note, snapshot.ropes, '', deps);
  assert.match(edit, /<button type="button" class="button danger" data-note-remove="20261021-120000-aaaa" data-rope="随手记">撤下<\/button><button type="button" class="button danger" data-note-delete="20261021-120000-aaaa" data-rope="随手记" aria-keyshortcuts="Meta\+Backspace">删除<\/button><span class="note-hint"><\/span>/);
  assert.doesNotMatch(edit, /data-shelf-item/, 'the editor deletes the live note, not a shelf copy');
  assert.doesNotMatch(edit, /废纸篓/, 'the confirm says 移到废纸篓; the button is just 删除');
  assert.doesNotMatch(notes.editorHTML(null, snapshot.ropes, 'AK', deps), /data-note-delete/);
  const shelf = [{ id: '20261020-090000-cccc', rope: '随手记', text: '一' }, { id: '20261020-090100-dddd', rope: 'AK', text: '二' }];
  const html = notes.shelfHTML({ shelf }, deps);
  assert.equal((html.match(/data-note-delete=/g) || []).length, 2);
  assert.equal((html.match(/data-shelf-item/g) || []).length, 2);
  assert.match(html, /data-shelf-clear="2">清空<\/button>/);
  assert.equal(notes.shelfHTML({ shelf: [] }, deps), '', 'nothing to clear, no shelf');
});

test('a group that still holds notes says why it cannot be removed, in one short line', () => {
  const full = notes.ropeFormHTML('AK', false, deps);
  assert.match(full, /data-rope-remove="AK" disabled aria-describedby="rope-remove-why">移除这个分组<\/button><span class="note-hint" id="rope-remove-why">分组里还有便签<\/span>/);
  assert.match(notes.ropeFormHTML('AK', true, deps), /data-rope-remove="AK" >移除这个分组<\/button><span class="note-hint" id="rope-remove-why"><\/span>/);
});

// 发布日历里排好的发布：只读，空心框 + 「发布」图标，点开去发布日历，不能拖。
const local = (month, day, hour, minute = 0) => new Date(2026, month - 1, day, hour, minute).toISOString();
const plannerDeps = { ...deps, plannerURL: () => '#tools?name=planner' };
const legacyState = {
  platforms: [{ id: 'instagram', name: 'Instagram' }, { id: 'xiaohongshu', name: 'rednote' }],
  drafts: [
    { id: 'd-late', title: '秋季菜单', platforms: ['instagram'], scheduled_at: local(10, 24, 14), status: 'review' },
    { id: 'd-early', title: '  ', platforms: ['tiktok', 'xiaohongshu'], scheduled_at: local(10, 24, 9, 30), status: 'draft' },
    { id: 'd-none', title: '没排时间', platforms: ['instagram'], scheduled_at: '' },
    { id: 'd-bad', title: '坏时间', scheduled_at: 'next week' },
    { id: 'd-other', title: '<b>下月</b>', platforms: [], scheduled_at: local(11, 2, 18), status: 'approved' },
  ],
};
const posts = notes.scheduledPosts(legacyState, (id) => ({ tiktok: 'TikTok' })[id] || id);

test('scheduled drafts become read-only posts on their local day and time, in time order', () => {
  assert.deepEqual(posts.map((post) => [post.id, post.day, post.time]), [['d-early', '2026-10-24', '09:30'], ['d-late', '2026-10-24', '14:00'], ['d-other', '2026-11-02', '18:00']]);
  assert.equal(posts[0].title, '未命名内容');
  assert.deepEqual(posts[0].platforms, ['TikTok', 'rednote'], 'names from /api/state first, then the shell’s own labels');
  assert.deepEqual([posts[0].status, posts[1].status, posts[2].status], ['草稿', '待审核', '已批准']);
  assert.equal(notes.postLabel(posts[1]), '计划发布：秋季菜单，10月24日 14:00，Instagram');
  assert.equal(notes.postLabel(posts[2]), '计划发布：<b>下月</b>，11月2日 18:00', 'no platforms, no trailing comma');
  assert.deepEqual(notes.scheduledPosts(null), []);
  assert.deepEqual(notes.scheduledPosts({ drafts: 'nope' }), []);
});

test('posts sit in the calendar as outlined links to 发布日历, apart from the notes and never draggable', () => {
  const html = notes.calendarHTML(snapshot, '2026-10', '2026-10-21', plannerDeps, posts);
  const cell = html.slice(html.indexOf('data-date="2026-10-24"'), html.indexOf('data-date="2026-10-25"'));
  assert.match(cell, /^data-date="2026-10-24" data-posts="2">/, 'the phone marker counts posts apart from notes');
  assert.doesNotMatch(cell, /data-count=/);
  assert.match(cell, /<button type="button" class="cal-num" data-cal-day="2026-10-24" aria-label="10月24日，2 条计划发布，打开这天">/, 'a day with only posts opens its sheet');
  assert.match(cell, /<div class="cal-chips"><\/div><div class="cal-posts"><a class="cal-post" href="#tools\?name=planner" data-cal-post="d-early"[^>]*draggable="false" aria-label="计划发布：未命名内容，10月24日 09:30，TikTok、rednote"><i data-icon="arrow-square-out"><\/i><time datetime="2026-10-24T09:30">09:30<\/time><span class="cal-post-title">未命名内容<\/span><\/a>/);
  assert.match(cell, /<span class="cal-post-mark" aria-hidden="true"><\/span>/);
  assert.doesNotMatch(cell, /draggable="true"|class="cal-chip /);
  assert.match(html, /<small>2 张 · 2 条计划发布<\/small>/, 'only this month’s posts are counted');
  // A day with notes and posts keeps both counts apart.
  const both = notes.calendarHTML(snapshot, '2026-10', '2026-10-21', plannerDeps, [{ ...posts[1], day: '2026-10-28' }]);
  assert.match(both, /data-date="2026-10-28" data-count="1" data-posts="1">/);
  assert.match(both, /aria-label="10月28日，1 张便签，1 条计划发布，打开这天"/);
  // Escaped titles, and a busy day folds into 还有 N 条发布.
  const busy = Array.from({ length: 4 }, (_, index) => ({ ...posts[2], id: `p${index}` }));
  const november = notes.calendarHTML({ ropes: [] }, '2026-11', '2026-10-21', plannerDeps, busy);
  assert.match(november, /&lt;b&gt;下月&lt;\/b&gt;/);
  assert.doesNotMatch(november, /<b>下月<\/b>/);
  assert.equal((november.match(/class="cal-post"/g) || []).length, 2);
  assert.match(november, /<button type="button" class="cal-more" data-cal-day="2026-11-02">还有 2 条发布<\/button>/);
});

test('without posts (none, unread or no 发布 tools) the calendar is exactly as before', () => {
  const before = notes.calendarHTML(snapshot, '2026-10', '2026-10-21', deps);
  assert.equal(notes.calendarHTML(snapshot, '2026-10', '2026-10-21', plannerDeps, []), before);
  assert.equal(notes.calendarHTML(snapshot, '2026-10', '2026-10-21', deps, null), before);
  assert.doesNotMatch(before, /cal-post|data-posts|计划发布/);
  const view = { mode: 'calendar', month: '2026-10', today: '2026-10-21' };
  assert.equal(notes.pageHTML(snapshot, false, '', plannerDeps, { ...view, posts: [] }), notes.pageHTML(snapshot, false, '', deps, view));
  assert.equal(notes.dayHTML(snapshot, '2026-10-28', plannerDeps, []), notes.dayHTML(snapshot, '2026-10-28', deps));
  assert.match(notes.pageHTML(snapshot, false, '', plannerDeps, { ...view, posts }), /data-cal-post="d-late"/);
  assert.doesNotMatch(notes.pageHTML(snapshot, false, '', plannerDeps, { mode: 'board', posts }), /cal-post/, 'the board never shows posts');
});

test('the day sheet lists 排好的发布 after that day’s notes, with platforms and review status', () => {
  const sheet = notes.dayHTML(snapshot, '2026-10-24', plannerDeps, posts);
  assert.match(sheet, /<p class="small-empty">这天没有便签。<\/p><section class="day-posts" aria-labelledby="day-posts-title"><h3 class="day-posts-title" id="day-posts-title"><i data-icon="arrow-square-out"><\/i>排好的发布<\/h3>/);
  assert.equal((sheet.match(/class="day-post"/g) || []).length, 2);
  assert.match(sheet, /<a class="day-post" href="#tools\?name=planner" data-day-post="d-late"[^>]*aria-label="计划发布：秋季菜单，10月24日 14:00，Instagram，待审核">/);
  assert.match(sheet, /<small>Instagram · 待审核<\/small>/);
  assert.match(sheet, /data-cal-new="2026-10-24"/, 'a note can still be written that day');
  const mixed = notes.dayHTML(snapshot, '2026-10-28', plannerDeps, [{ ...posts[1], day: '2026-10-28' }]);
  assert.ok(mixed.indexOf('class="day-note') < mixed.indexOf('class="day-posts"'), 'notes first, then posts');
  // No address for 发布日历 (no tools here): the post is plain text with the same accessible name.
  const plain = notes.dayHTML(snapshot, '2026-10-24', deps, posts);
  assert.doesNotMatch(plain, /<a class="day-post"/);
  assert.match(plain, /<span class="day-post" data-day-post="d-late"[^>]*><span class="sr-only">计划发布：秋季菜单，10月24日 14:00，Instagram，待审核<\/span><span class="day-post-body" aria-hidden="true">/);
});
