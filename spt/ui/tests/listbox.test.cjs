'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { listboxHTML } = require('../listbox.js');

const options = [{ value: '', label: '全部状态' }, { value: 'published', label: '已发布', hint: '平台已核' }, { value: 'wip', label: '制作中', disabled: true }];
const selected = (html) => [...html.matchAll(/<li role="option"[^>]*data-value="([^"]*)"[^>]*aria-selected="true"/g)].map((match) => match[1]);

test('a hidden input keeps the old id and carries the value', () => {
  const html = listboxHTML({ id: 'status-filter', label: '作品状态', value: 'published', options });
  assert.match(html, /<input type="hidden" id="status-filter" value="published">/);
  assert.match(html, /id="status-filter-button" role="combobox" aria-haspopup="listbox" aria-expanded="false" aria-controls="status-filter-list" aria-labelledby="status-filter-label"/);
  assert.match(html, /<span class="listbox-value">已发布<\/span>/);
});

test('only the chosen option is aria-selected', () => {
  const html = listboxHTML({ id: 'status-filter', label: '作品状态', value: 'published', options });
  assert.deepEqual(selected(html), ['published']);
  assert.equal((html.match(/aria-selected="false"/g) || []).length, 2);
  assert.match(html, /data-value="wip" aria-selected="false" aria-disabled="true"/);
  assert.match(html, /<span class="listbox-hint">平台已核<\/span>/);
});

test('array options work like objects', () => {
  const html = listboxHTML({ id: 'cover-ratio', label: '封面显示方式', value: 'portrait', options: [['square', '统一方形'], ['portrait', '竖版 3:4']] });
  assert.deepEqual(selected(html), ['portrait']);
  assert.match(html, /<input type="hidden" id="cover-ratio" value="portrait">/);
  assert.match(html, /<span class="listbox-value">竖版 3:4<\/span>/);
});

test('an unknown value falls back to the first option', () => {
  const html = listboxHTML({ id: 'cover-ratio', label: '封面', value: 'nope', options: [['square', '统一方形'], ['original', '原始比例']] });
  assert.deepEqual(selected(html), ['square']);
  assert.match(html, /<input type="hidden" id="cover-ratio" value="square">/);
});

test('labels, values and ids are escaped', () => {
  const html = listboxHTML({ id: 'x"><b', label: '<script>', value: 'a"b', options: [{ value: 'a"b', label: '<img src=x onerror=1>' }, { value: "c'd", label: '&' }] });
  assert.doesNotMatch(html, /<script>|<img|id="x">|<b>/);
  assert.match(html, /id="x&quot;&gt;&lt;b"/);
  assert.match(html, /value="a&quot;b"/);
  assert.match(html, /data-value="c&#39;d"/);
  assert.match(html, /&lt;img src=x onerror=1&gt;/);
  assert.match(html, /<span class="listbox-option-label">&amp;<\/span>/);
});

test('label is visually hidden unless asked; disabled reaches the button', () => {
  assert.match(listboxHTML({ id: 'a', label: '分组', options }), /class="listbox-label sr-only"/);
  assert.match(listboxHTML({ id: 'a', label: '分组', options, showLabel: true }), /class="listbox-label" id="a-label"/);
  assert.match(listboxHTML({ id: 'a', label: '分组', options, disabled: true }), /aria-labelledby="a-label" disabled>/);
  assert.match(listboxHTML({ id: 'a', label: '分组', options, className: 'wide' }), /<div class="listbox wide" data-listbox>/);
  assert.match(listboxHTML({ id: 'a', label: '分组', options: [] }), /<input type="hidden" id="a" value="">/);
});

test('form name and extra attributes go on the hidden input', () => {
  const html = listboxHTML({ id: 'planning-pillar', name: 'pillar', label: '所属栏目', value: '2', options: [['', '待补栏目'], ['2', '方法']], attrs: { 'data-mc-filter': 'status', 'data-planning-batch': true, 'data-off': false } });
  assert.match(html, /<input type="hidden" id="planning-pillar" name="pillar" value="2" data-mc-filter="status" data-planning-batch>/);
  assert.doesNotMatch(html, /data-off/);
});

test('a disabled listbox keeps its value out of FormData, like a disabled select', () => {
  const html = listboxHTML({ id: 'account-platform', name: 'platform', label: '平台', value: 'tiktok', disabled: true, options: [['instagram', 'Instagram'], ['tiktok', 'TikTok']] });
  assert.match(html, /<input type="hidden" id="account-platform" name="platform" value="tiktok" disabled>/);
  assert.match(html, /id="account-platform-button"[^>]* disabled>/);
});

test('attribute names and values are escaped', () => {
  const html = listboxHTML({ id: 'x', label: 'x', options: [['a', 'A']], attrs: { 'data-x': '"><script>' } });
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /data-x="&quot;&gt;&lt;script&gt;"/);
});
