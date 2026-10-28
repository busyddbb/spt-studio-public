// SPT 读数据: reads what a creator center shows, the way a person sees it.
// It never clicks, types or submits; on a list it only scrolls to load older posts.
// Platforms: rednote (笔记管理 + public profile), tiktok (TikTok Studio content list),
// facebook / instagram (Meta Business Suite tables). The workspace copy of this file wins over the
// bundled one, so a page fix needs no rebuild. It also runs in the offline test.
(function (args) {
  'use strict';
  const {phase, platform = 'rednote', days = 14, now = Date.now()} = args || {};
  const all = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const clean = v => String(v ?? '').replace(/[​‌‍﻿]/g, '').replace(/ /g, ' ').replace(/\s+/g, ' ').trim();
  // innerText is what a person sees; off-screen or collapsed cells still carry textContent or an aria-label.
  const text = n => clean(n?.innerText) || clean(n?.textContent) || clean(n?.getAttribute?.('aria-label'));
  const leaves = root => all('*', root).filter(n => n.children.length === 0 && text(n) && !/^(SCRIPT|STYLE|NOSCRIPT)$/.test(n.tagName));
  const TIME = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/;
  const NUMBER = /^\d[\d,]*(?:\.\d+)?\s*(?:万|w|W|k|K)?$/;
  const STATE = /^(置顶|已发布|审核中|未通过|仅自己可见|已删除|违规|私密)$/;
  // 「Oct 23, 11:59 PM」 (TikTok), 「Fri Oct 23, 11:53pm」 (Meta), with or without a year.
  const US_TIME = /^(?:[A-Z][a-z]{2},?\s+)?[A-Z][a-z]{2}[a-z]*\.?\s+\d{1,2}(?:,\s*\d{4})?(?:,?\s+\d{1,2}:\d{2}\s*[AaPp][Mm])?$/;
  const state = window.__sptMetricsRead = window.__sptMetricsRead || {scrolls: 0, stable: 0, count: -1};

  // Short texts along the top of the page: the account name sits there. @handles anywhere count too.
  function header() {
    const roots = all('header,[role="banner"],[role="navigation"],[class*="header"],[class*="Header"],[class*="user-info"],[class*="account"],[class*="avatar"],[class*="profile"]');
    const top = leaves(document.body).filter(n => { const r = n.getBoundingClientRect(); return r.height > 0 && r.top < 90; });
    const handles = leaves(document.body).map(text).filter(t => /^@[\w.]{2,40}$/.test(t));
    const found = [...roots.flatMap(leaves), ...top].map(text).filter(t => t.length <= 40).concat(handles, [document.title.slice(0, 80)]);
    return [...new Set(found)].slice(0, 80);
  }

  function scroller(node) {
    for (let n = node; n && n !== document.body; n = n.parentElement) {
      const style = getComputedStyle(n);
      if (/(auto|scroll)/.test(style.overflowY) && n.scrollHeight > n.clientHeight + 10) return n;
    }
    return document.scrollingElement || document.documentElement;
  }

  // Load older rows by scrolling; true while it is still worth waiting for more.
  function loadMore(found, oldest, cutoff, limit = 15) {
    state.stable = found.length === state.count ? state.stable + 1 : 0;
    state.count = found.length;
    if (oldest > cutoff && state.scrolls < limit && state.stable < 4) {
      const last = found[found.length - 1].node, box = scroller(last);
      box.scrollTop = box.scrollHeight;
      box.dispatchEvent(new Event('scroll', {bubbles: true}));
      window.dispatchEvent(new Event('scroll'));
      state.scrolls++;
      return true;
    }
    return false;
  }

  function usTime(value) {
    const t = Date.parse(value.replace(/^[A-Z][a-z]{2},?\s+/, '').replace(/(\d)(?:,)?\s+(\d{1,2}:\d{2})/, `$1, ${new Date(now).getFullYear()} $2`));
    return Number.isFinite(t) ? t : NaN;
  }

  const strip = o => { const {node, ...rest} = o; return rest; };

  // ---------------------------------------------------------------- 小红书 笔记管理
  function rednoteCards() {
    const times = leaves(document.body).filter(n => TIME.test(text(n)));
    const result = [];
    for (const time of times) {
      let node = time.parentElement, card = null;
      while (node && node !== document.body) {
        const inside = leaves(node);
        if (inside.filter(n => TIME.test(text(n))).length > 1) break;
        const after = inside.slice(inside.indexOf(time) + 1).filter(n => NUMBER.test(text(n)));
        if (after.length >= 5) { card = node; break; }
        node = node.parentElement;
      }
      if (!card) continue;
      const inside = leaves(card), at = inside.indexOf(time);
      const before = inside.slice(0, at).map(text);
      const title = [...before].reverse().find(t => !STATE.test(t) && !NUMBER.test(t)) || '';
      const numbers = inside.slice(at + 1).map(text).filter(t => NUMBER.test(t)).slice(0, 5);
      const states = inside.map(text).filter(t => STATE.test(t) && t !== '置顶');
      const ids = [card, ...all('[href],[data-note-id],[data-id],[data-noteid]', card)].flatMap(n =>
        ['data-note-id', 'data-noteid', 'data-id', 'href'].map(a => n.getAttribute && n.getAttribute(a)).filter(Boolean));
      const noteID = ids.map(v => String(v).match(/(?:^|[/?=&])([a-f\d]{24})(?:$|[/?&#])/i)?.[1]).find(Boolean) || null;
      result.push({title, time: text(time), numbers, state: states.join(' '), note_id: noteID, pinned: before.includes('置顶'), node: card});
    }
    return result;
  }

  function rednote() {
    if (/\/login(?:\/|$)/.test(location.pathname) || all('input[placeholder="手机号"],input[placeholder="验证码"]').length) return {status: 'login'};
    if (phase === 'notes') {
      if (!/note-manager/.test(location.pathname)) return {status: 'wait', reason: '等待笔记管理'};
      const found = rednoteCards();
      if (!found.length) {
        const empty = leaves(document.body).some(n => /暂无笔记|还没有发布|没有笔记/.test(text(n)));
        return empty ? {status: 'done', header: header(), notes: []} : {status: 'wait', reason: '等待笔记列表'};
      }
      const cutoff = now - days * 86400000;
      const dated = found.filter(c => !c.pinned).map(c => Date.parse(c.time.replace(' ', 'T') + ':00+08:00')).filter(Number.isFinite);
      const oldest = dated.length ? Math.min(...dated) : now;
      if (loadMore(found, oldest, cutoff)) return {status: 'wait', reason: '加载更早的笔记'};
      return {status: 'done', header: header(), notes: found.map(({node, pinned, ...card}) => card)};
    }
    if (phase === 'profile') {
      const items = leaves(document.body).map(text);
      const before = label => { const i = items.findIndex(t => t === label); return i > 0 && NUMBER.test(items[i - 1]) ? items[i - 1] : null; };
      const inline = label => items.map(t => t.match(new RegExp('^(\\d[\\d,.]*\\s*(?:万|w|k|K)?)\\s*' + label + '$'))?.[1]).find(Boolean) || null;
      const followers = before('粉丝') || inline('粉丝');
      if (!followers) return {status: 'wait', reason: '等待主页'};
      return {status: 'done', followers, following: before('关注') || inline('关注')};
    }
    return {status: 'attention', reason: '未知步骤'};
  }

  // ---------------------------------------------------------------- TikTok Studio · Content
  // Each row: a link to the video (its text is the caption), the publish time, the privacy
  // setting and the Views / Likes / Comments numbers as the column header orders them.
  function tiktokRows() {
    const links = all('a[href*="/video/"]').filter(a => /\/video\/(\d{15,})/.test(a.getAttribute('href') || ''));
    const seen = new Set(), result = [];
    for (const link of links) {
      const id = link.getAttribute('href').match(/\/video\/(\d{15,})/)[1];
      if (seen.has(id)) continue;
      let node = link.parentElement, row = null;
      while (node && node !== document.body) {
        const inside = leaves(node);
        if (all('a[href*="/video/"]', node).filter(a => !a.getAttribute('href').includes(id)).length) break;
        const time = inside.find(n => US_TIME.test(text(n)));
        const privacy = inside.some(n => /^(Everyone|Friends|Only me|Followers|公开|仅自己|好友)$/i.test(text(n)));
        if (time && privacy) { row = node; break; }
        node = node.parentElement;
      }
      if (!row) continue;
      seen.add(id);
      const inside = leaves(row);
      const time = inside.find(n => US_TIME.test(text(n)));
      // The caption carries numbers of its own (addresses, hours); the stats sit outside the link, after the time.
      const tokens = nodes => nodes.filter(n => n !== link && n !== time && !link.contains(n) && !/\d{1,2}:\d{2}/.test(text(n)))
        .flatMap(n => text(n).split(' ')).filter(t => NUMBER.test(t) && !/,$/.test(t));
      let after = tokens(inside.slice(inside.indexOf(time) + 1)).slice(0, 3);
      if (after.length < 3) after = [];
      const debug = result.length ? undefined : {row: inside.filter(n => n !== link && !link.contains(n)).map(text).slice(0, 16)};
      const privacy = inside.map(text).find(t => /^(Everyone|Friends|Only me|Followers|公开|仅自己|好友)$/i.test(t)) || '';
      result.push({title: text(link) || text(row).slice(0, 120), time: text(time), note_id: id, url: link.getAttribute('href'),
        metrics: {views: after[0] ?? null, likes: after[1] ?? null, comments: after[2] ?? null},
        state: /only me|仅自己/i.test(privacy) ? '仅自己可见' : privacy, node: row, ...(debug ? {debug} : {})});
    }
    return result;
  }

  function tiktok() {
    if (/\/login(?:\/|$)/.test(location.pathname) || all('input[name="username"],input[name="password"]').length) return {status: 'login'};
    if (phase !== 'notes') return {status: 'done'};
    if (!/\/tiktokstudio\/content/.test(location.pathname)) return {status: 'wait', reason: '等待 TikTok Studio 内容页 ' + location.pathname};
    const found = tiktokRows();
    if (!found.length && !state.rows) {
      const empty = leaves(document.body).some(n => /No posts yet|还没有作品|No content/i.test(text(n)));
      if (empty) return {status: 'done', header: header(), notes: []};
      const seen = all('a[href*="/video/"]').length;
      return {status: 'wait', reason: `等待作品列表（视频链接 ${seen} 个）`};
    }
    // The list only keeps the rows on screen: remember every row seen while scrolling.
    state.rows = state.rows || {};
    const complete = row => Object.values(row.metrics).every(v => v !== null);
    for (const row of found) {
      const known = state.rows[row.note_id];
      if (!known || complete(row) || !complete(known)) state.rows[row.note_id] = strip(row);
    }
    state.waits = state.waits || 0;
    const pending = found.find(r => !complete(r));
    if (pending && state.waits++ < 10) {
      // The stats cells fill in once a row has been on screen: bring the first bare row into view.
      pending.node.scrollIntoView({block: 'center'});
      return {status: 'wait', reason: '等待作品数字'};
    }
    const kept = Object.values(state.rows);
    const cutoff = now - days * 86400000;
    const dated = kept.map(c => usTime(c.time)).filter(Number.isFinite);
    const oldest = dated.length ? Math.min(...dated) : now;
    if (found.length && loadMore(found, oldest, cutoff, 8)) return {status: 'wait', reason: '加载更早的作品'};
    return {status: 'done', header: header(), notes: kept, page: location.href};
  }

  // ---------------------------------------------------------------- Meta Business Suite
  // Facebook: 发布的帖子 table (/latest/posts/published_posts). Instagram: the Content table
  // (/latest/insights/content). Both carry a header row naming the columns; a row's first cell
  // holds the platform marks, the caption and the format, the second the publish time.
  const META_FIELDS = [['views', /^Views$/i], ['reach', /^Reach$/i], ['likes', /^Likes(?: and reactions)?$/i],
    ['comments', /^Comments$/i], ['shares', /^Shares$/i], ['saves', /^Saves$/i]];
  const META_NOISE = /^(Boost|Open Dropdown|Reel|Post|Video|Photo|Story|Crossposted|Not currently boosted|Not a crosspost|Instagram|Facebook|\d{1,2}:\d{2})$/i;

  function metaIDs() {
    const search = new URLSearchParams(location.search);
    const fromLink = key => all('a[href*="' + key + '="]').map(a => (a.getAttribute('href').match(new RegExp(key + '=(\\d+)')) || [])[1]).find(Boolean);
    return {asset: search.get('asset_id') || fromLink('asset_id'), business: search.get('business_id') || fromLink('business_id')};
  }

  function metaTable() {
    for (const table of all('table')) {
      const rows = all('tr', table);
      const head = rows.find(r => all('th,td', r).some(c => /^Date published$/i.test(text(c))));
      if (!head) continue;
      const columns = all('th,td', head).map(text);
      return {table, columns, rows: rows.filter(r => r !== head && all('td,th', r).length >= columns.length - 1)};
    }
    return null;
  }

  function metaRows() {
    const found = metaTable();
    if (!found) return null;
    const dateAt = found.columns.findIndex(c => /^Date published$/i.test(c));
    const result = [];
    for (const row of found.rows) {
      const cells = all('td,th', row);
      if (cells.length <= dateAt) continue;
      const offset = cells.length - found.columns.length;   // a leading checkbox cell shifts nothing; both tables count it
      const cell = i => cells[i + (offset > 0 ? offset : 0)];
      const titleCell = cell(dateAt - 1), time = text(cell(dateAt));
      if (!US_TIME.test(time)) continue;
      const parts = leaves(titleCell).map(text).filter(t => t && !META_NOISE.test(t));
      const title = parts.sort((a, b) => b.length - a.length)[0] || '';
      const marks = all('img,svg,[aria-label],[alt]', titleCell).map(n => n.getAttribute('aria-label') || n.getAttribute('alt') || '').join(' ') + ' ' + text(titleCell);
      const platforms = ['Instagram', 'Facebook'].filter(p => new RegExp(p, 'i').test(marks));
      const labels = all('[aria-label]', row).map(n => n.getAttribute('aria-label'));
      const id = labels.map(l => (l.match(/id (\d{10,})/) || [])[1]).find(Boolean)
        || all('a[href]', row).map(a => (a.getAttribute('href').match(/(?:content_id|post_id|story_fbid|fbid)=(\d{10,})/) || [])[1]).find(Boolean) || null;
      const metrics = {};
      for (const [field, pattern] of META_FIELDS) {
        const at = found.columns.findIndex(c => pattern.test(c));
        if (at >= 0 && cell(at)) metrics[field] = text(cell(at));
      }
      const owner = parts.filter(t => t !== title).find(t => /,/.test(t)) || '';
      result.push({title, time, note_id: id, metrics, platforms, owner, crossposted: /Crossposted/i.test(text(titleCell)), state: '', node: row});
    }
    return result;
  }

  function meta(platform) {
    if (/^\/login/.test(location.pathname) || (all('input[name="email"]').length && all('input[name="pass"]').length) || /facebook\.com\/?$/.test(location.host + location.pathname.replace(/\/$/, ''))) {
      if (!/business\.facebook\.com/.test(location.host)) return {status: 'login'};
    }
    if (/\/business\/loginpage|\/login\b|checkpoint/.test(location.pathname)) return {status: 'login'};
    if (phase !== 'notes') return {status: 'done'};
    const want = platform === 'facebook' ? '/latest/posts/published_posts' : '/latest/insights/content';
    if (/object_insights/.test(location.pathname)) return metaDetailPage(platform);
    if (!location.pathname.startsWith(want)) {
      const ids = metaIDs();
      if (ids.asset && ids.business) return {status: 'navigate', url: `https://business.facebook.com${want}/?business_id=${ids.business}&asset_id=${ids.asset}`};
      if (all('input[name="email"]').length) return {status: 'login'};
      return {status: 'wait', reason: '等待 Meta Business Suite 带上账号参数 ' + location.pathname};
    }
    const found = metaRows();
    if (found === null) {
      const tables = all('table').length, heads = all('th').slice(0, 8).map(text).join('|');
      return {status: 'wait', reason: `等待帖子表格（表格 ${tables} 个，表头 ${heads}）`};
    }
    if (!found.length) {
      const empty = leaves(document.body).some(n => /No results|No content|没有内容|No posts/i.test(text(n)));
      return empty ? {status: 'done', header: header(), notes: [], page: location.href} : {status: 'wait', reason: '等待表格行'};
    }
    return metaDetails(found, platform);
  }

  // The numbers live on each post's own insights page: the lists only fill the columns on screen,
  // and the Content table carries a crossposted reel's Facebook figures. Opening a row and choosing
  // the platform's tab are the only clicks the reader makes; they change nothing on the platform.
  const IG_LABELS = [['views', /^Views$/i], ['reach', /^Reach$/i], ['likes', /^Likes(?: and reactions)?$/i],
    ['comments', /^Comments$/i], ['shares', /^Shares$/i], ['saves', /^Saves$/i]];
  function click(node) {
    for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
      node.dispatchEvent(new MouseEvent(type, {bubbles: true, cancelable: true, view: window}));
    }
  }
  // Progress survives a full page load (sessionStorage); the SPA's own back keeps the list state.
  const igLoad = () => { try { return JSON.parse(sessionStorage.getItem('sptIG') || 'null'); } catch (e) { return null; } };
  const igSave = ig => { try { sessionStorage.setItem('sptIG', JSON.stringify({done: ig.done, failed: ig.failed, rows: ig.rows, queue: ig.queue, listURL: ig.listURL, current: ig.current, platform: ig.platform})); } catch (e) {} };
  const back = () => (window.__sptBack ? window.__sptBack() : history.back());
  function metaDetails(found, platform) {
    const saved = igLoad();
    const ig = state.ig = state.ig || {queue: null, done: {}, rows: {}, current: null, ticks: 0, listURL: location.href, failed: [], platform, ...(saved && saved.platform === platform ? saved : {})};
    const key = r => r.title + '|' + r.time;
    if (!ig.queue) {
      const cutoff = now - days * 86400000;
      const mark = platform === 'instagram' ? 'Instagram' : 'Facebook';
      const rows = found.filter(r => (r.platforms.includes(mark) || !r.platforms.length) && (usTime(r.time) || now) >= cutoff).slice(0, 12);
      for (const r of rows) ig.rows[key(r)] = strip(r);
      ig.queue = rows.map(key);
      ig.listURL = location.href;
      igSave(ig);
    }
    if (ig.current === null) {
      const next = ig.queue.find(k => !(k in ig.done) && !ig.failed.includes(k));
      if (!next) {
        const notes = Object.values(ig.rows).map(r => ({...r, metrics: (ig.done[key(r)] || {}).metrics || {}, detail_id: (ig.done[key(r)] || {}).id || null}));
        notes.forEach(n => { if (!Object.keys(n.metrics).length) n.state = '没打开详情'; });
        if (notes.length) notes[0].debug = {failed: ig.failed.length, url: location.href};
        try { sessionStorage.removeItem('sptIG'); } catch (e) {}
        return {status: 'done', header: header(), notes, page: location.href};
      }
      const row = found.find(r => key(r) === next);
      if (!row) { ig.failed.push(next); igSave(ig); return {status: 'wait', reason: '表格里找不到这一行'}; }
      const target = leaves(row.node).find(n => text(n) === row.title) || row.node;
      ig.current = next; ig.ticks = 0; ig.tab = false;
      igSave(ig);
      click(target);
      return {status: 'wait', reason: '打开帖子详情'};
    }
    if (ig.ticks++ > 24) { ig.failed.push(ig.current); ig.current = null; igSave(ig); return {status: 'wait', reason: '详情没打开'}; }
    return {status: 'wait', reason: '等待帖子详情 ' + location.pathname};
  }
  function metaDetailPage(platform) {
    const ig = state.ig = state.ig || {queue: null, done: {}, rows: {}, current: null, ticks: 0, failed: [], platform, ...(igLoad() || {})};
    if (ig.current === null) { back(); return {status: 'wait', reason: '回到列表'}; }
    if (ig.ticks++ > 24) { ig.failed.push(ig.current); ig.current = null; igSave(ig); back(); return {status: 'wait', reason: '详情读不出来，回列表'}; }
    const want = platform === 'instagram' ? /instagram/i : /facebook/i;
    const tabs = all('[role="tab"]');
    const tab = tabs.find(t => want.test(text(t)));
    const selected = t => t.getAttribute('aria-selected') === 'true' || /selected|active/i.test(t.className || '');
    if (tab && !selected(tab) && !ig.tab) { ig.tab = true; click(tab); return {status: 'wait', reason: '切到平台页签'}; }
    if (tab && !selected(tab) && ig.ticks < 8) return {status: 'wait', reason: '等待平台页签'};
    // The detail opens beside the list, which stays in the DOM with its own 「Views」 column header;
    // the post's figures start at the 「Total performance」 tab group, each label followed by its number.
    const everything = leaves(document.body);
    const start = everything.findIndex(n => /^Total performance$/i.test(text(n)));
    const items = start >= 0 ? everything.slice(start) : everything;
    const metrics = {};
    for (const [field, pattern] of IG_LABELS) {
      for (let i = 0; i < items.length - 1 && !(field in metrics); i++) {
        if (!pattern.test(text(items[i]))) continue;
        const next = text(items[i + 1]);
        if (NUMBER.test(next)) metrics[field] = next;
        else if (/^[‑–—-]+$/.test(next)) metrics[field] = '';
      }
    }
    if (!('views' in metrics) && !('reach' in metrics)) {
      const seen = items.map(text).filter(t => t.length <= 40).slice(0, 120).join('|');
      return {status: 'wait', reason: `等待详情数字（页签 ${tabs.map(t => text(t) + (selected(t) ? '*' : '')).join('/')}；叶子 ${items.length}，iframe ${all('iframe').length}，${location.pathname}；${seen}）`};
    }
    // The address names the post by the platform's own id (Facebook: the reel/video id of the
    // public link; Instagram: the media id the public shortcode encodes).
    ig.done[ig.current] = {metrics, id: new URLSearchParams(location.search).get('content_id') || null};
    ig.current = null;
    igSave(ig);
    back();
    return {status: 'wait', reason: '读完一篇，回列表'};
  }

  if (platform === 'tiktok') return tiktok();
  if (platform === 'facebook' || platform === 'instagram') return meta(platform);
  return rednote();
})
