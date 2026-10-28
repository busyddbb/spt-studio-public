'use strict';

// 便签：按分组贴在板上，也可以按日期收进月历。只负责生成 HTML 和计算位置；读写在 spt.js。
((scope) => {
  const COLORS = [['lilac', '薰衣草'], ['mint', '薄荷'], ['pink', '樱花'], ['butter', '奶油'], ['sky', '天空']];
  const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日'];
  const CHIPS_PER_DAY = 3;
  // 发布日历里排好时间的内容，在月历里只读显示：空心框加「发布」图标，和实心的便签分开。
  const POSTS_PER_DAY = 2;
  const POST_ICON = 'arrow-square-out';
  const POST_STATUS = { draft: '草稿', review: '待审核', approved: '已批准' };
  // The 分组 picker's last option: name a new group right in the editor.
  const NEW_ROPE = '__new__';
  const array = (value) => Array.isArray(value) ? value : [];
  const pad = (value) => String(value).padStart(2, '0');

  // 下拉选择统一用 SPTListbox：浏览器里是 window.SPTListbox，node 测试里直接 require。
  function listboxHTML(options) {
    const Listbox = (typeof window !== 'undefined' && window.SPTListbox) || (typeof require === 'function' ? require('./listbox.js') : null);
    return Listbox ? Listbox.listboxHTML(options) : '';
  }

  // 每张便签固定一个小角度，重新载入也不会乱晃。
  function tilt(id) {
    let hash = 0;
    for (const char of String(id)) hash = (hash * 31 + char.codePointAt(0)) | 0;
    return ((Math.abs(hash) % 7) - 3) * 0.6;
  }
  // 拖动时：按便签在板上的位置（offset，不受旋转影响）找插入点。
  // 先找鼠标所在的那一行，再看落在哪张便签的左半边。
  function dropIndex(boxes, x, y) {
    if (!boxes.length) return 0;
    const rows = [];
    boxes.forEach((box, index) => {
      const row = rows.find((item) => Math.abs(item.top - box.top) < 8);
      if (row) { row.items.push(index); row.bottom = Math.max(row.bottom, box.top + box.height); }
      else rows.push({ top: box.top, bottom: box.top + box.height, items: [index] });
    });
    const distance = (row) => y < row.top ? row.top - y : y > row.bottom ? y - row.bottom : 0;
    const row = rows.reduce((best, item) => distance(item) < distance(best) ? item : best, rows[0]);
    const hit = row.items.find((index) => x < boxes[index].left + boxes[index].width / 2);
    return hit === undefined ? row.items[row.items.length - 1] + 1 : hit;
  }
  function count(snapshot) {
    return array(snapshot?.ropes).reduce((total, rope) => total + array(rope.notes).length, 0);
  }
  function allNotes(snapshot) {
    return array(snapshot?.ropes).flatMap((rope) => array(rope.notes));
  }
  // 便签落在哪一天：写了日期就用日期，否则是写下它的那天。
  function dayOf(note) {
    const value = String(note?.date || note?.created || note?.updated_at || '');
    return /^\d{4}-\d{2}-\d{2}/.test(value) ? value.slice(0, 10) : '';
  }
  function shortDate(value) {
    const match = String(value || '').match(/\d{4}-(\d{2})-(\d{2})/);
    return match ? `${Number(match[1])}月${Number(match[2])}日` : '';
  }
  function monthDay(value) {
    const match = String(value || '').match(/\d{4}-(\d{2})-(\d{2})/);
    return match ? `${match[1]}/${match[2]}` : '';
  }
  const firstLine = (text, size = 40) => String(text || '').split('\n')[0].trim().slice(0, size);
  function colorOf(note) {
    return COLORS.some(([key]) => key === note?.color) ? note.color : 'lilac';
  }
  function monthOf(value) {
    return /^\d{4}-\d{2}$/.test(String(value || '')) ? value : String(value || '').slice(0, 7);
  }
  function shiftMonth(month, step) {
    const [year, number] = monthOf(month).split('-').map(Number);
    const date = new Date(Date.UTC(year, number - 1 + step, 1));
    return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}`;
  }
  // 旧版发布工具 GET /api/state 里排了时间的草稿 → 月历用的只读条目，按本机时区落到某天某时，按时间排好。
  // 平台名先用 /api/state 给的名字，没有再用 label(id)。
  function scheduledPosts(data, label = (id) => id) {
    const names = new Map(array(data?.platforms).map((item) => [item?.id, item?.name]));
    return array(data?.drafts).flatMap((draft) => {
      const when = new Date(typeof draft?.scheduled_at === 'string' ? draft.scheduled_at : '');
      if (!draft?.scheduled_at || Number.isNaN(when.getTime())) return [];
      return [{
        id: String(draft.id ?? ''),
        title: String(draft.title ?? '').trim() || '未命名内容',
        day: `${when.getFullYear()}-${pad(when.getMonth() + 1)}-${pad(when.getDate())}`,
        time: `${pad(when.getHours())}:${pad(when.getMinutes())}`,
        at: when.getTime(),
        platforms: array(draft.platforms).map((id) => String(names.get(id) || label(id) || '')).filter(Boolean),
        status: POST_STATUS[draft.status] || '',
      }];
    }).sort((a, b) => a.at - b.at || a.title.localeCompare(b.title));
  }
  // 「计划发布：标题，10月24日 14:00，Instagram」；withStatus 时在最后加上审核状态。
  function postLabel(post, withStatus = false) {
    const parts = [`计划发布：${post.title}`, `${shortDate(post.day)} ${post.time}`];
    if (array(post.platforms).length) parts.push(post.platforms.join('、'));
    if (withStatus && post.status) parts.push(post.status);
    return parts.join('，');
  }
  // 一条排好的发布：去发布日历的链接，不能拖动。没有发布日历的地址时只显示文字。
  function postHTML(post, href, deps, className, withStatus = false) {
    const label = postLabel(post, withStatus);
    const head = `${deps.icon(POST_ICON)}<time datetime="${deps.esc(`${post.day}T${post.time}`)}">${deps.esc(post.time)}</time><span class="${className}-title">${deps.esc(post.title)}</span>`;
    const meta = withStatus ? `<small>${deps.esc([array(post.platforms).join('、'), post.status].filter(Boolean).join(' · ') || '没写平台')}</small>` : '';
    const attr = `data-${className}="${deps.esc(post.id)}" title="${deps.esc(label)}"`;
    if (!href) return `<span class="${className}" ${attr}><span class="sr-only">${deps.esc(label)}</span><span class="${className}-body" aria-hidden="true">${head}${meta}</span></span>`;
    return `<a class="${className}" href="${deps.esc(href)}" ${attr} draggable="false" aria-label="${deps.esc(label)}">${head}${meta}</a>`;
  }
  // 月历的格子：从周一开始，整周显示，前后补上邻月的日子。
  function monthDays(month) {
    const [year, number] = monthOf(month).split('-').map(Number);
    const first = new Date(Date.UTC(year, number - 1, 1));
    const lead = (first.getUTCDay() + 6) % 7;
    const length = new Date(Date.UTC(year, number, 0)).getUTCDate();
    const cells = Math.ceil((lead + length) / 7) * 7;
    return Array.from({ length: cells }, (_, index) => {
      const date = new Date(Date.UTC(year, number - 1, 1 - lead + index));
      const iso = `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`;
      return { date: iso, day: date.getUTCDate(), inMonth: date.getUTCMonth() === number - 1, weekend: index % 7 >= 5 };
    });
  }

  // 板上的一张便签：可以用 Tab 走到，回车打开，⌥↑ ⌥↓ 调整顺序（键盘处理在 spt.js）。
  function noteHTML(note, deps) {
    const text = String(note.text || '');
    const [head, ...rest] = text.split('\n');
    const body = rest.join('\n').replace(/^\n+/, '');
    const written = String(note.created || note.updated_at || '').slice(0, 10);
    const when = note.date ? `<time class="note-day" datetime="${deps.esc(note.date)}" title="放在这天">${deps.esc(shortDate(note.date))}</time>` : `<time class="note-written" datetime="${deps.esc(written)}">写于 ${deps.esc(shortDate(written))}</time>`;
    const label = `便签：${firstLine(text) || '空白'}${note.date ? `，${shortDate(note.date)}` : ''}`;
    // The copy button is for the mouse (keyboard: ⌘C on the focused card), so it stays out of the Tab order.
    const copy = `<button type="button" class="note-copy" data-note-copy-card="${deps.esc(note.id)}" data-rope="${deps.esc(note.rope)}" tabindex="-1" aria-label="复制这张便签的文字" title="复制文字">${deps.icon('copy')}</button>`;
    return `<article class="note note-${colorOf(note)}" draggable="true" tabindex="0" data-note="${deps.esc(note.id)}" data-rope="${deps.esc(note.rope)}" style="--tilt:${tilt(note.id)}deg" aria-label="${deps.esc(label)}" aria-keyshortcuts="Meta+C Alt+ArrowUp Alt+ArrowDown"><span class="note-tape" aria-hidden="true"></span><p class="note-text"><span class="note-title">${deps.esc(head)}</span>${body ? `\n<span class="note-body">${deps.esc(body)}</span>` : ''}</p>${when}${copy}</article>`;
  }
  function groupHTML(rope, deps) {
    const notes = array(rope.notes);
    const name = deps.esc(rope.name);
    const hidden = Number.isInteger(rope.hidden) && rope.hidden > 0 ? `<p class="settings-note">还有 ${rope.hidden} 张没显示</p>` : '';
    return `<section class="note-group${notes.length ? '' : ' is-empty'}" data-rope-section="${name}" aria-label="${name}"><header class="note-group-head"><span class="note-group-tag">${name}</span><small>${notes.length} 张</small><button type="button" class="icon-button note-group-edit" data-rope-edit="${name}" aria-label="整理分组：${name}" title="改名或收起">${deps.icon('pencil')}</button></header><div class="note-board" data-rope-track="${name}">${notes.map((note) => noteHTML(note, deps)).join('')}<button type="button" class="note-add" data-note-new="${name}" data-note-rope="${name}">${deps.icon('plus')}<span>贴一张</span></button></div>${hidden}</section>`;
  }
  // posts：scheduledPosts() 的结果，只读；deps.plannerURL() 给出发布日历的地址（没有就只显示文字）。
  function calendarHTML(snapshot, month, today, deps, posts = []) {
    const current = monthOf(month || today);
    const byDay = new Map();
    for (const note of allNotes(snapshot)) {
      const day = dayOf(note);
      if (!day) continue;
      if (!byDay.has(day)) byDay.set(day, []);
      byDay.get(day).push(note);
    }
    const postsByDay = new Map();
    for (const post of array(posts)) {
      if (!post?.day) continue;
      if (!postsByDay.has(post.day)) postsByDay.set(post.day, []);
      postsByDay.get(post.day).push(post);
    }
    const planner = postsByDay.size && typeof deps.plannerURL === 'function' ? deps.plannerURL() || '' : '';
    const [year, number] = current.split('-').map(Number);
    const inMonth = [...byDay.entries()].filter(([day]) => day.startsWith(current)).reduce((total, [, items]) => total + items.length, 0);
    const postsInMonth = [...postsByDay.entries()].filter(([day]) => day.startsWith(current)).reduce((total, [, items]) => total + items.length, 0);
    const several = array(snapshot?.ropes).length > 1;
    const cells = monthDays(current).map((cell) => {
      const notes = byDay.get(cell.date) || [];
      const dayPosts = postsByDay.get(cell.date) || [];
      const chips = notes.slice(0, CHIPS_PER_DAY).map((note) => {
        const first = firstLine(note.text, 60) || '空白';
        const name = `${note.rope} · ${first}${note.date ? '' : '（没定日期，放在写下它的那天）'}`;
        return `<button type="button" class="cal-chip note-${colorOf(note)}${note.date ? '' : ' is-undated'}" draggable="true" data-note="${deps.esc(note.id)}" data-rope="${deps.esc(note.rope)}" title="${deps.esc(name)}" aria-label="${deps.esc(name)}">${several ? `<span class="cal-chip-rope">${deps.esc(String(note.rope).slice(0, 4))}</span>` : ''}${deps.esc(first.slice(0, 30))}</button>`;
      }).join('');
      const more = notes.length > CHIPS_PER_DAY ? `<button type="button" class="cal-more" data-cal-day="${cell.date}">还有 ${notes.length - CHIPS_PER_DAY} 张</button>` : '';
      const classes = ['cal-day', cell.inMonth ? '' : 'cal-outside', cell.weekend ? 'cal-weekend' : '', cell.date === today ? 'cal-today' : ''].filter(Boolean).join(' ');
      // data-count：手机上不画小条，只显示这天有几张；data-posts：手机上另画一个空心小圈。
      const label = `${shortDate(cell.date)}${notes.length ? `，${notes.length} 张便签` : ''}${dayPosts.length ? `，${dayPosts.length} 条计划发布` : ''}`;
      // A day with notes (or posts) opens its list (which has 在这天写一张); an empty day starts a note. The ＋ is a mouse shortcut.
      const num = notes.length || dayPosts.length ? `<button type="button" class="cal-num" data-cal-day="${cell.date}" aria-label="${deps.esc(label)}，打开这天">${cell.day}</button>` : `<button type="button" class="cal-num" data-cal-new="${cell.date}" aria-label="${deps.esc(label)}，在这天写一张">${cell.day}</button>`;
      const add = cell.inMonth ? `<button type="button" class="cal-add" data-cal-new="${cell.date}" tabindex="-1" aria-label="在${deps.esc(shortDate(cell.date))}写一张" title="在这天写一张">${deps.icon('plus')}</button>` : '';
      const morePosts = dayPosts.length > POSTS_PER_DAY ? `<button type="button" class="cal-more" data-cal-day="${cell.date}">还有 ${dayPosts.length - POSTS_PER_DAY} 条发布</button>` : '';
      const postBox = dayPosts.length ? `<div class="cal-posts">${dayPosts.slice(0, POSTS_PER_DAY).map((post) => postHTML(post, planner, deps, 'cal-post')).join('')}${morePosts}</div><span class="cal-post-mark" aria-hidden="true"></span>` : '';
      return `<div class="${classes}" data-date="${cell.date}"${notes.length ? ` data-count="${notes.length}"` : ''}${dayPosts.length ? ` data-posts="${dayPosts.length}"` : ''}>${num}${add}<div class="cal-chips">${chips}${more}</div>${postBox}</div>`;
    }).join('');
    return `<section class="panel note-calendar" aria-label="${year} 年 ${number} 月"><header class="cal-head"><div class="cal-title"><h2>${year} 年 ${number} 月</h2><small>${inMonth} 张${postsInMonth ? ` · ${postsInMonth} 条计划发布` : ''}</small></div><div class="cal-nav"><button type="button" class="icon-button" data-cal-shift="-1" aria-label="上个月">${deps.icon('caret-left')}</button><button type="button" class="button small" data-cal-today>今天</button><button type="button" class="icon-button" data-cal-shift="1" aria-label="下个月">${deps.icon('caret-right')}</button></div></header><div class="cal-week" aria-hidden="true">${WEEKDAYS.map((day, index) => `<span class="${index >= 5 ? 'cal-weekend' : ''}">${day}</span>`).join('')}</div><div class="cal-grid">${cells}</div></section>`;
  }
  // 某一天的全部便签（月历里「还有 N 张」点开）。data-day 让编辑框能回到这一天。
  // 这天在发布日历里排了发布，就在便签后面列出「排好的发布」（只读，点开去发布日历）。
  function dayHTML(snapshot, date, deps, posts = []) {
    const notes = allNotes(snapshot).filter((note) => dayOf(note) === date);
    const day = deps.esc(date);
    const dayPosts = array(posts).filter((post) => post?.day === date);
    const planner = dayPosts.length && typeof deps.plannerURL === 'function' ? deps.plannerURL() || '' : '';
    const postList = dayPosts.length ? `<section class="day-posts" aria-labelledby="day-posts-title"><h3 class="day-posts-title" id="day-posts-title">${deps.icon(POST_ICON)}排好的发布</h3>${dayPosts.map((post) => postHTML(post, planner, deps, 'day-post', true)).join('')}</section>` : '';
    return `<div class="note-editor day-sheet" data-day="${day}"><header class="note-editor-head"><h2 id="note-dialog-title">${deps.esc(shortDate(date))}</h2><button type="button" class="icon-button" data-action="close-note" aria-label="关闭">${deps.icon('x')}</button></header><div class="day-list">${notes.map((note) => `<button type="button" class="day-note note-${colorOf(note)}" data-note="${deps.esc(note.id)}" data-rope="${deps.esc(note.rope)}" data-day="${day}"><span>${deps.esc(String(note.text || '').slice(0, 160))}</span><small>${deps.esc(note.rope)}</small></button>`).join('') || '<p class="small-empty">这天没有便签。</p>'}${postList}</div><footer class="note-editor-foot"><span class="note-hint"></span><button type="button" class="button primary" data-cal-new="${day}">${deps.icon('plus')}在这天写一张</button></footer></div>`;
  }
  function ghostHTML(size = 88) {
    return `<svg class="ghost-mark" width="${size}" height="${Math.round(size * 1.18)}" viewBox="40 24 176 208" aria-hidden="true"><path class="ghost-body" d="M48 112A80 80 0 0 1 208 112V160H152Q144 160 144 168V224H72A24 24 0 0 1 48 200Z"/><path class="ghost-flap" d="M152 176Q152 168 160 168H208L152 224Z"/><path class="ghost-eye" d="M89 124a13 17 0 1 0 26 0a13 17 0 1 0 -26 0ZM141 124a13 17 0 1 0 26 0a13 17 0 1 0 -26 0Z"/><path class="ghost-cheek" d="M69 150a11 11 0 1 0 22 0a11 11 0 1 0 -22 0ZM165 148a11 11 0 1 0 22 0a11 11 0 1 0 -22 0Z"/></svg>`;
  }
  // 已撤下的便签：snapshot.shelf = [{id, rope, text, color, updated_at, taken_down_at}]，最新的在前。空的时候不画。
  // 每张能「放回」或「删除」（移到系统废纸篓，spt.js 先问一声）；「清空」把整架都移到废纸篓。
  function shelfHTML(snapshot, deps) {
    const items = array(snapshot?.shelf).filter((item) => item && item.id);
    if (!items.length) return '';
    const rows = items.map((item) => {
      const text = String(item.text || '').trim();
      const when = monthDay(item.taken_down_at || item.removed_at);
      const meta = [item.rope, when ? `${when} 撤下` : '已撤下'].filter(Boolean).join(' · ');
      const title = deps.esc(firstLine(text) || '空白便签');
      return `<li class="shelf-item" data-color="${colorOf(item)}"><p class="shelf-text">${deps.esc(text || '空白便签')}</p><span class="shelf-meta">${deps.esc(meta)}</span><span class="shelf-actions"><button type="button" class="button small" data-note-restore="${deps.esc(item.id)}" data-note-rope="${deps.esc(item.rope || '')}" aria-label="放回：${title}">放回</button><button type="button" class="button small danger" data-note-delete="${deps.esc(item.id)}" data-note-rope="${deps.esc(item.rope || '')}" data-shelf-item aria-label="移到废纸篓：${title}">删除</button></span></li>`;
    }).join('');
    return `<details class="notes-shelf"><summary>已撤下 <span class="nav-count">${items.length}</span></summary><div class="shelf-bar"><button type="button" class="button small danger" data-shelf-clear="${items.length}">清空</button></div><ul class="shelf-list">${rows}</ul></details>`;
  }

  // view: { mode: 'board' | 'calendar', month: 'YYYY-MM', today: 'YYYY-MM-DD', query: 搜索框里已有的字, posts: 月历里只读显示的计划发布 }
  function pageHTML(snapshot, loading, error, deps, view = {}) {
    const ropes = array(snapshot?.ropes);
    const mode = view.mode === 'calendar' ? 'calendar' : 'board';
    const total = count(snapshot);
    const toggle = `<div class="segmented notes-view" role="group" aria-label="便签视图"><button type="button" data-notes-view="board" aria-pressed="${mode === 'board'}">分组</button><button type="button" data-notes-view="calendar" aria-pressed="${mode === 'calendar'}">日历</button></div>`;
    const search = total ? `<div class="search notes-search">${deps.icon('magnifying-glass')}<label class="sr-only" for="notes-search">搜索便签</label><input id="notes-search" type="search" placeholder="搜索便签" autocomplete="off" value="${deps.esc(view.query || '')}"></div>` : '';
    // No count under the title: each group (or the month) already carries its own.
    const heading = `<header class="page-heading"><div><h1 tabindex="-1">便签</h1>${total ? '<p class="result-count" id="notes-count" aria-live="polite"></p>' : ''}</div><div class="page-controls">${search}${toggle}${mode === 'board' ? `<button type="button" class="button" data-rope-new>${deps.icon('plus')}新分组</button>` : ''}<button type="button" class="button primary" data-note-new="">${deps.icon('note')}贴一张</button></div></header>`;
    const shelf = shelfHTML(snapshot, deps);
    if (error && !snapshot) return `<section class="notes-page">${heading}<div class="empty-state">${deps.icon('warning-circle')}<h2>便签没能读取</h2><p>${deps.esc(error)}</p><button type="button" class="button primary" data-action="reload-notes">再试一次</button></div></section>`;
    if (loading && !snapshot) return `<section class="notes-page">${heading}<div class="empty-state" aria-busy="true"><span class="spinner" aria-hidden="true"></span><p>正在读取便签</p></div></section>`;
    if (snapshot && snapshot.ready === false) return `<section class="notes-page">${heading}<div class="empty-state">${ghostHTML()}<h2>还没有工作区</h2><a class="button primary" href="#settings">去设置</a></div></section>`;
    const message = error ? `<div class="inline-message error" role="status">${deps.icon('warning-circle')}<span>${deps.esc(error)}</span></div>` : '';
    if (mode === 'calendar') return `<section class="notes-page">${heading}${message}${calendarHTML(snapshot, view.month, view.today, deps, array(view.posts))}${shelf}</section>`;
    if (!ropes.length) return `<section class="notes-page">${heading}${message}<div class="empty-state notes-empty">${ghostHTML()}<h2>这里空空的</h2><button type="button" class="button primary" data-note-new="">${deps.icon('note')}贴第一张</button></div>${shelf}</section>`;
    return `<section class="notes-page">${heading}${message}${ropes.map((rope) => groupHTML(rope, deps)).join('')}${shelf}</section>`;
  }
  // fromDay：从某一天的便签列表打开时，顶部给一个回到那天的按钮。
  function editorHTML(note, ropes, rope, deps, date = '', fromDay = '') {
    const editing = !!note?.id;
    const color = colorOf(note);
    const names = array(ropes).map((item) => item.name);
    const current = note?.rope || rope || names[0] || '随手记';
    if (!names.includes(current)) names.push(current);
    const day = editing ? (note.date || '') : date;
    const back = /^\d{4}-\d{2}-\d{2}$/.test(String(fromDay || '')) ? `<button type="button" class="text-action note-back" data-day-back="${fromDay}">${deps.icon('caret-left')}${deps.esc(shortDate(fromDay))}</button>` : '';
    const group = listboxHTML({ id: 'note-rope', label: '分组', value: current, options: [...names.map((name) => [name, name]), { value: NEW_ROPE, label: '＋ 新分组…' }], showLabel: true });
    const newRope = '<label class="note-pick note-rope-new" hidden><span>新分组的名字</span><input id="note-rope-new" maxlength="30" placeholder="比如：AK、灵感、待办" autocomplete="off"></label>';
    const copy = editing ? '<button type="button" class="text-action" data-note-copy>复制文字</button>' : '';
    const discard = '<div class="note-discard" id="note-discard" role="alert" hidden><p>这张便签还没保存。</p><div class="note-bar-actions"><button type="button" class="button small" data-note-discard-keep>继续编辑</button><button type="button" class="button small danger" data-note-discard>不保存</button><button type="submit" class="button small primary">保存</button></div></div>';
    const conflict = '<div class="note-conflict" id="note-conflict" role="alert" hidden><p>这张便签刚被改过（可能是 Claude 或 Codex）。</p><blockquote class="note-conflict-text"></blockquote><div class="note-bar-actions"><button type="button" class="button small" data-note-conflict-load>换成新内容</button><button type="button" class="button small primary" data-note-conflict-keep>保留我的</button></div></div>';
    return `<form class="note-editor note-${color}" id="note-form" method="dialog">${back}<header class="note-editor-head"><h2 id="note-dialog-title">${editing ? '便签' : '新便签'}</h2>${copy}<button type="button" class="icon-button" data-action="close-note" aria-label="关闭">${deps.icon('x')}</button></header><label class="sr-only" for="note-text">便签内容</label><textarea id="note-text" class="note-paper" rows="8" maxlength="20000" placeholder="写点什么……第一行会当标题" autofocus>${deps.esc(note?.text || '')}</textarea><div class="note-options"><div class="note-colors" role="radiogroup" aria-label="颜色">${COLORS.map(([key, label]) => `<label class="note-swatch note-${key}" title="${label}"><input type="radio" name="note-color" value="${key}" ${key === color ? 'checked' : ''}><span class="sr-only">${label}</span></label>`).join('')}</div><div class="note-fields"><div class="note-pick">${group}</div>${newRope}<label class="note-pick"><span>放到哪天</span><input type="date" id="note-date" value="${deps.esc(day)}"></label></div></div><p class="note-error" id="note-error" role="alert" hidden></p>${discard}${conflict}<footer class="note-editor-foot">${editing ? `<button type="button" class="button danger" data-note-remove="${deps.esc(note.id)}" data-rope="${deps.esc(note.rope)}">撤下</button><button type="button" class="button danger" data-note-delete="${deps.esc(note.id)}" data-rope="${deps.esc(note.rope)}" aria-keyshortcuts="Meta+Backspace">删除</button>` : ''}<span class="note-hint"></span><button type="button" class="button" data-action="close-note">取消</button><button type="submit" class="button primary" aria-keyshortcuts="Meta+Enter">${editing ? '保存' : '贴上'}</button></footer><input type="hidden" id="note-id" value="${deps.esc(note?.id || '')}"><input type="hidden" id="note-from" value="${deps.esc(note?.rope || '')}"><input type="hidden" id="note-updated" value="${deps.esc(note?.updated_at || '')}"></form>`;
  }
  function ropeFormHTML(name, empty, deps) {
    const editing = !!name;
    return `<form class="note-editor rope-form" id="rope-form" method="dialog"><header class="note-editor-head"><h2 id="note-dialog-title">${editing ? '整理分组' : '新分组'}</h2><button type="button" class="icon-button" data-action="close-note" aria-label="关闭">${deps.icon('x')}</button></header><label class="field-label" for="rope-name">名字</label><input id="rope-name" class="rope-name-input" maxlength="30" value="${deps.esc(name || '')}" placeholder="比如：AK、灵感、待办" autocomplete="off" autofocus><p class="note-error" id="note-error" role="alert" hidden></p><footer class="note-editor-foot">${editing ? `<button type="button" class="button danger" data-rope-remove="${deps.esc(name)}" ${empty ? '' : 'disabled aria-describedby="rope-remove-why"'}>移除这个分组</button>` : ''}<span class="note-hint" id="rope-remove-why">${editing && !empty ? '分组里还有便签' : ''}</span><button type="button" class="button" data-action="close-note">取消</button><button type="submit" class="button primary">${editing ? '改名' : '新建'}</button></footer><input type="hidden" id="rope-from" value="${deps.esc(name || '')}"></form>`;
  }
  function localToday() {
    const now = new Date();
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
  }
  function addDays(iso, days) {
    const date = new Date(`${iso}T00:00:00Z`);
    date.setUTCDate(date.getUTCDate() + days);
    return date.toISOString().slice(0, 10);
  }
  // 运营页右侧：排在今天到一周内的便签先放，其余按最近改过的补上。
  function railHTML(snapshot, deps) {
    const today = deps.today || localToday(), week = addDays(today, 7);
    const all = allNotes(snapshot);
    const soon = all.filter((note) => note.date && note.date >= today && note.date <= week).sort((a, b) => a.date.localeCompare(b.date));
    const recent = all.filter((note) => !soon.includes(note)).sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)));
    const notes = [...soon, ...recent].slice(0, 4);
    const body = notes.length ? `<div class="mini-notes">${notes.map((note) => `<button type="button" class="mini-note note-${colorOf(note)}" data-note="${deps.esc(note.id)}" data-rope="${deps.esc(note.rope)}" style="--tilt:${tilt(note.id)}deg"><span class="note-tape" aria-hidden="true"></span><span class="mini-note-text">${deps.esc(String(note.text || '').slice(0, 80))}</span><small>${deps.esc(note.rope)}${note.date ? ` · ${deps.esc(shortDate(note.date))}` : ''}</small></button>`).join('')}</div>` : `<div class="mini-empty">${ghostHTML(56)}<p>还没有便签</p></div>`;
    return `<aside class="notes-rail" aria-label="${soon.length ? '今天和这周的便签' : '最近的便签'}"><section class="panel"><div class="panel-head"><h2 class="panel-title">${soon.length ? '今天和这周' : '便签'}</h2><a class="text-action" href="#notes">全部 ${deps.icon('caret-right')}</a></div>${body}<button type="button" class="button small notes-rail-add" data-note-new="">${deps.icon('plus')}贴一张</button></section></aside>`;
  }
  const exported = { COLORS, NEW_ROPE, tilt, dropIndex, count, dayOf, monthDays, shiftMonth, scheduledPosts, postLabel, pageHTML, calendarHTML, dayHTML, editorHTML, ropeFormHTML, railHTML, ghostHTML, shelfHTML };
  if (typeof module !== 'undefined' && module.exports) module.exports = exported;
  if (scope) scope.SPTNotes = exported;
})(typeof window === 'undefined' ? null : window);
