'use strict';
(() => {
  const STATUS = {draft: '草稿', review: '待审核', approved: '已批准'};
  const WEEK = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];
  const COLORS = {instagram: '#c252a2', facebook: '#4081e3', tiktok: '#2b3039', youtube: '#e65c63', google_business: '#36a07c', xiaohongshu: '#e65b72'};
  const LABELS = {instagram: 'Instagram', facebook: 'Facebook', tiktok: 'TikTok', youtube: 'YouTube', google_business: 'Google 商家', xiaohongshu: 'rednote'};
  const SHORT = {instagram: 'IG', facebook: 'FB', tiktok: 'TK', youtube: 'YT', google_business: 'G', xiaohongshu: 'rednote'};
  const C = {ctx: null, dataset: null, view: 'month', date: new Date(), query: '', platform: '', account: '', status: '', unscheduled: true, controller: null, busy: false, previousFocus: null, samples: null};
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[ch]));
  // Styled single-select shared with the SPT shell (/workspace/listbox.js); keeps the old id/name/data-* on a hidden input.
  const listbox = config => window.SPTListbox ? window.SPTListbox.listboxHTML(config) : '';
  const svg = name => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${({left: '<path d="m14 6-6 6 6 6"/>', right: '<path d="m10 6 6 6-6 6"/>', plus: '<path d="M12 5v14M5 12h14"/>', search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4.5 4.5"/>', clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>', calendar: '<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M8 3v4M16 3v4M3 11h18"/>', close: '<path d="m6 6 12 12M18 6 6 18"/>', copy: '<rect x="8" y="8" width="12" height="13" rx="2"/><path d="M15 8V4a1 1 0 0 0-1-1H4a1 1 0 0 0-1 1v11a1 1 0 0 0 1 1h4"/>', chevron: '<path d="m6 9 6 6 6-6"/>', grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>', list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>', week: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16M15 4v16"/>', dots: '<circle cx="5" cy="12" r="1.6" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1.6" fill="currentColor" stroke="none"/><circle cx="19" cy="12" r="1.6" fill="currentColor" stroke="none"/>', download: '<path d="M12 3v13m-5-5 5 5 5-5M4 17v4h16v-4"/>'})[name] || ''}</svg>`;
  const root = () => document.getElementById('media-calendar');
  const pad = n => String(n).padStart(2, '0');
  const dayKey = date => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
  const localInput = date => `${dayKey(date)}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
  const parseDate = value => { if (!value) return null; const date = new Date(value); return Number.isFinite(date.getTime()) ? date : null; };
  const atDay = key => { if (!/^\d{4}-\d{2}-\d{2}$/.test(key || '')) return null; const [y, m, d] = key.split('-').map(Number); const date = new Date(y, m - 1, d, 12); return dayKey(date) === key ? date : null; };
  const addDays = (date, count) => new Date(date.getFullYear(), date.getMonth(), date.getDate() + count, 12);
  const monday = date => addDays(date, -(date.getDay() + 6) % 7);
  const monthStart = date => new Date(date.getFullYear(), date.getMonth(), 1, 12);
  const dateLabel = date => date.toLocaleDateString('zh-CN', {month: 'long', day: 'numeric', weekday: 'long'});
  const timeLabel = date => date.toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit', hour12: false});
  const timezone = () => Intl.DateTimeFormat().resolvedOptions().timeZone || '设备本地时区';
  const isDemo = () => C.ctx?.dataset === 'demo';
  const platformName = id => LABELS[id] || (C.ctx?.platforms || []).find(p => p.id === id)?.name || id;
  const platformIDs = draft => Array.isArray(draft.platforms) ? draft.platforms : [];
  const accountIDs = draft => Array.isArray(draft.account_ids) ? draft.account_ids : [];
  const statusLabel = draft => STATUS[draft.status] || '草稿';
  const rawDrafts = () => Array.isArray(C.ctx?.drafts) ? C.ctx.drafts : [];
  const useSamples = () => isDemo() && !rawDrafts().length;
  const accounts = () => useSamples() ? C.samples.accounts : (C.ctx?.accounts || []);
  const drafts = () => useSamples() ? C.samples.drafts : rawDrafts();
  const findDraft = id => drafts().find(d => String(d.id) === String(id));
  const notify = (text, error = false) => C.ctx?.toast?.(text, error);
  // Tell the SPT window that a draft changed, so 运营 and 发布 reload (nothing happens outside the window).
  const shellChanged = () => { try { if (window.parent !== window && typeof window.parent.sptToolChanged === 'function') window.parent.sptToolChanged(); } catch { /* not inside the SPT window */ } };
  const button = (action, label, attrs = '', kind = '') => `<button type="button" class="mc-button ${kind}" data-mc-action="${action}" ${attrs}>${label}</button>`;
  function makeSamples() {
    const start = monday(new Date());
    const sampleAccounts = [['instagram', 'Studio · 海外', '@studio.example'], ['tiktok', 'Studio · 短视频', '@studio.example'], ['youtube', 'Studio · 教程', '@studio.example'], ['xiaohongshu', 'Studio · 创作笔记', '@创作示例']].map(([platform, name, handle], index) => ({id: `mc-example-account-${index}`, platform, name: `${name}（示例）`, handle, brand: '虚构示例品牌'}));
    const rows = [
      ['一支视频，从分镜开始', '用三个镜头讲清一个想法：开场给场景，中段看过程，结尾留下结果。\n\n此内容为界面演示示例。', 0, 10, 0, 'approved'],
      ['30 秒，看见光线的变化', '同一张桌面，试试不同时间的自然光。把对比放在一起，记录这次拍摄观察。\n\n此内容为界面演示示例。', 1, 15, 1, 'review'],
      ['封面设计的三个取舍', '这次只讨论标题、主体和留白。保留能帮助读者理解内容的部分。\n\n此内容为界面演示示例。', 2, 9, 3, 'draft'],
      ['从素材到成片：剪辑过程', '整理素材，挑选关键片段，完成粗剪，最后处理声音。展示一条短片的实际制作步骤。\n\n此内容为界面演示示例。', 3, 18, 2, 'approved'],
      ['镜头之外的准备', '分享拍摄前的准备：清理画面、检查素材、确认今天只要完成的一件事。\n\n此内容为界面演示示例。', 4, 11, 0, 'review'],
      ['这个转场是怎么拍的？', '把两个相似的动作连接起来，让下一个场景自然出现。\n\n此内容为界面演示示例。', 5, 14, 1, 'draft'],
      ['下次拍摄前的检查清单', '把常遗漏的三件事写下来：电量、声音、备份。\n\n此内容为界面演示示例。', null, 0, 3, 'draft'],
      ['一周内容复盘', '收集真正收到的问题，再决定下一轮要回答什么。\n\n此内容为界面演示示例。', null, 0, 2, 'draft']
    ];
    return {accounts: sampleAccounts, drafts: rows.map(([title, body, offset, hour, index, status], i) => { const date = offset === null ? null : addDays(start, offset); if (date) date.setHours(hour, 0, 0, 0); return {id: `mc-example-${i}`, title, body, status, platforms: [sampleAccounts[index].platform], account_ids: [sampleAccounts[index].id], scheduled_at: date?.toISOString() || '', media_ids: [], example: true}; })};
  }
  function filtered() {
    const query = C.query.trim().toLocaleLowerCase();
    return drafts().filter(d => {
      const variants = d.platform_variants && typeof d.platform_variants === 'object' && !Array.isArray(d.platform_variants) ? Object.values(d.platform_variants).filter(value => typeof value === 'string').join('\n') : '';
      const text = `${d.title || ''}\n${d.body || ''}\n${variants}`.toLocaleLowerCase();
      return (!query || text.includes(query)) && (!C.platform || platformIDs(d).includes(C.platform)) && (!C.account || accountIDs(d).some(id => String(id) === C.account)) && (!C.status || d.status === C.status);
    });
  }
  function range() {
    if (C.view === 'week') { const start = monday(C.date); return {start, end: addDays(start, 7)}; }
    return {start: monthStart(C.date), end: new Date(C.date.getFullYear(), C.date.getMonth() + 1, 1, 12)};
  }
  function inRange(draft, selectedRange = range()) {
    const d = parseDate(draft.scheduled_at); if (!d) return false;
    return dayKey(d) >= dayKey(selectedRange.start) && dayKey(d) < dayKey(selectedRange.end);
  }
  function sorted(items) { return [...items].sort((a, b) => (parseDate(a.scheduled_at)?.getTime() || Infinity) - (parseDate(b.scheduled_at)?.getTime() || Infinity) || String(a.title || '').localeCompare(String(b.title || ''))); }
  function pips(draft) { return platformIDs(draft).map(id => `<span class="mc-platform" style="--mc-platform:${COLORS[id] || '#817694'}" title="${esc(platformName(id))}"><i></i>${esc(SHORT[id] || platformName(id))}</span>`).join(''); }
  function accountNames(draft) { return accountIDs(draft).map(id => accounts().find(a => String(a.id) === String(id))?.name || '未知账号').join('、') || '未指定账号'; }
  function card(draft, compact = true) {
    const d = parseDate(draft.scheduled_at);
    return `<article class="mc-card mc-status-${esc(STATUS[draft.status] ? draft.status : 'draft')} ${compact ? 'mc-card-compact' : ''}"><button type="button" class="mc-card-open" data-mc-action="edit" data-mc-id="${esc(draft.id)}" aria-label="${isDemo() ? '预览示例' : '编辑'}：${esc(draft.title || '未命名内容')}"><span class="mc-card-top"><span class="mc-card-time">${d ? esc(timeLabel(d)) : '待安排'}</span><span class="mc-card-status">${esc(statusLabel(draft))}</span></span><strong>${esc(draft.title || '未命名内容')}</strong>${compact ? '' : `<span class="mc-card-excerpt">${esc(draft.body || '')}</span>`}<span class="mc-card-bottom">${pips(draft)}</span></button>${compact ? '' : `<div class="mc-card-meta">${esc(accountNames(draft))}</div>`}<div class="mc-card-actions">${button('schedule', `${svg('clock')}<span>${d ? '改期' : '安排时间'}</span>`, `data-mc-id="${esc(draft.id)}" ${isDemo() ? 'disabled title="演示只读"' : ''}`, 'mc-card-action')}${!compact && ['draft', 'review'].includes(draft.status) ? button('status', draft.status === 'review' ? '批准内容' : '提交审核', `data-mc-id="${esc(draft.id)}" data-mc-status="${draft.status === 'review' ? 'approved' : 'review'}" ${isDemo() ? 'disabled title="演示只读"' : ''}`, 'mc-review-action') : ''}${button('copy', svg('copy'), `data-mc-id="${esc(draft.id)}" aria-label="复制发布包：${esc(draft.title || '')}" title="复制发布包"`, 'mc-icon-button mc-card-copy')}</div></article>`;
  }
  function monthView(items) {
    const first = monthStart(C.date), start = monday(first);
    const needed = (first.getDay() + 6) % 7 + new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate();
    const count = Math.ceil(needed / 7) * 7;
    const today = dayKey(new Date());
    return `<div class="mc-scroll-grid" tabindex="0" aria-label="月历，可横向滚动"><div class="mc-month-grid" role="group" aria-label="${esc(first.toLocaleDateString('zh-CN', {year: 'numeric', month: 'long'}))} 内容日历">${WEEK.map(x => `<div class="mc-weekday">${x}</div>`).join('')}${Array.from({length: count}, (_, index) => { const day = addDays(start, index), key = dayKey(day), rows = sorted(items.filter(d => dayKey(parseDate(d.scheduled_at) || new Date(0)) === key)), other = day.getMonth() !== C.date.getMonth(); return `<section class="mc-day ${other ? 'mc-other-month' : ''} ${key === today ? 'mc-today' : ''}" aria-label="${esc(dateLabel(day))}"><header class="mc-day-header"><span class="mc-day-number" ${key === today ? 'aria-current="date"' : ''}>${day.getDate()}</span>${button('new-day', svg('plus'), `data-mc-date="${key}" aria-label="在 ${esc(dateLabel(day))} 新建内容" ${isDemo() ? 'disabled' : ''}`, 'mc-day-add mc-icon-button')}</header><div class="mc-day-cards">${rows.slice(0, 2).map(d => card(d)).join('')}${rows.length > 2 ? button('show-day', `另有 ${rows.length - 2} 条内容`, `data-mc-date="${key}"`, 'mc-more') : ''}</div></section>`; }).join('')}</div></div>`;
  }
  function weekView(items) {
    const start = monday(C.date), today = dayKey(new Date());
    return `<div class="mc-scroll-grid" tabindex="0" aria-label="周历，可横向滚动"><div class="mc-week-grid">${Array.from({length: 7}, (_, i) => { const day = addDays(start, i), key = dayKey(day), rows = sorted(items.filter(d => dayKey(parseDate(d.scheduled_at) || new Date(0)) === key)); return `<section class="mc-week-day ${key === today ? 'mc-today' : ''}"><header><span>${WEEK[i]}</span><strong class="mc-day-number" ${key === today ? 'aria-current="date"' : ''}>${day.getDate()}</strong><small>${day.getMonth() + 1} 月</small></header><div class="mc-week-cards">${rows.map(d => card(d)).join('')}${!rows.length ? '<p class="mc-day-empty">暂无安排</p>' : ''}</div>${button('new-day', `${svg('plus')}<span>添加内容</span>`, `data-mc-date="${key}" ${isDemo() ? 'disabled' : ''}`, 'mc-week-add')}</section>`; }).join('')}</div></div>`;
  }
  function listView(items) {
    const rows = sorted(items.filter(d => inRange(d)));
    if (!rows.length) return emptyState();
    const groups = new Map(); rows.forEach(d => { const key = dayKey(parseDate(d.scheduled_at)); if (!groups.has(key)) groups.set(key, []); groups.get(key).push(d); });
    return `<div class="mc-list">${[...groups].map(([key, group]) => `<section class="mc-list-group"><header><div><strong>${esc(dateLabel(atDay(key)))}</strong><span>${group.length} 条内容</span></div>${button('new-day', `${svg('plus')}添加`, `data-mc-date="${key}" ${isDemo() ? 'disabled' : ''}`, 'mc-list-add')}</header><div class="mc-list-cards">${group.map(d => card(d, false)).join('')}</div></section>`).join('')}</div>`;
  }
  function emptyState() { return `<div class="mc-empty"><span>${svg('calendar')}</span><h3>${drafts().length ? '这个范围内还没有安排' : '你的第一条内容，从这里开始'}</h3>${isDemo() ? '' : button('new', `${svg('plus')}新建内容`, '', 'mc-primary')}${demoLink()}</div>`; }
  // The demo data lives behind the empty state only, so the daily header stays about real work.
  function demoLink() { return !isDemo() && !drafts().length ? '<button type="button" class="mc-button mc-text-button" data-action="demo">查看演示数据</button>' : ''; }
  // ··· menu (menu button pattern): Enter/Space/↓ opens on the first item, ↑ on the last; ↑↓ Home End move; Escape and Tab close.
  function overflowMenu() {
    return `<div class="mc-overflow"><button type="button" class="mc-button mc-icon-button mc-overflow-button" id="mc-overflow-button" aria-haspopup="menu" aria-expanded="false" aria-controls="mc-overflow-menu" aria-label="更多操作" title="更多操作">${svg('dots')}</button><div class="mc-overflow-menu" id="mc-overflow-menu" role="menu" aria-labelledby="mc-overflow-button" hidden><a class="mc-overflow-item" role="menuitem" tabindex="-1" href="${esc(C.ctx.exportURL)}" download>${svg('download')}<span>导出全部草稿</span></a></div></div>`;
  }
  const menuParts = () => { const el = root(); return {button: el?.querySelector('#mc-overflow-button'), menu: el?.querySelector('#mc-overflow-menu')}; };
  const menuItems = menu => [...menu.querySelectorAll('[role="menuitem"]')];
  function openMenu(focus = 'first') {
    const {button, menu} = menuParts(); if (!button || !menu) return;
    menu.hidden = false; button.setAttribute('aria-expanded', 'true');
    // Opens toward the page: right-aligned under the button, or left-aligned when the button sits at the left (phones).
    menu.classList.remove('mc-overflow-start'); if (menu.getBoundingClientRect().left < 8) menu.classList.add('mc-overflow-start');
    const items = menuItems(menu); (focus === 'last' ? items[items.length - 1] : items[0])?.focus();
  }
  function closeMenu(returnFocus = false) {
    const {button, menu} = menuParts(); if (!button || !menu || menu.hidden) return;
    menu.hidden = true; button.setAttribute('aria-expanded', 'false');
    if (returnFocus) button.focus();
  }
  function menuClick(event) {
    const {button, menu} = menuParts(); if (!button || !menu) return;
    if (button.contains(event.target)) { if (menu.hidden) openMenu(); else closeMenu(true); return; }
    if (menu.contains(event.target)) { if (event.target.closest('[role="menuitem"]')) closeMenu(true); return; }
    closeMenu();
  }
  function menuKey(event) {
    const {button, menu} = menuParts(); if (!button || !menu) return;
    if (event.target === button && ['ArrowDown', 'ArrowUp'].includes(event.key)) { event.preventDefault(); openMenu(event.key === 'ArrowUp' ? 'last' : 'first'); return; }
    if (menu.hidden || !menu.contains(event.target)) return;
    const items = menuItems(menu), index = items.indexOf(document.activeElement);
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); closeMenu(true); }
    else if (event.key === 'Tab') closeMenu();
    else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); const step = event.key === 'ArrowDown' ? 1 : -1; items[(index + step + items.length) % items.length]?.focus(); }
    else if (event.key === 'Home' || event.key === 'End') { event.preventDefault(); items[event.key === 'Home' ? 0 : items.length - 1]?.focus(); }
    else if (event.key === ' ' && document.activeElement?.matches('a[role="menuitem"]')) { event.preventDefault(); document.activeElement.click(); }
  }
  function content() {
    const items = filtered(), scheduled = items.filter(d => parseDate(d.scheduled_at)), unscheduled = items.filter(d => !parseDate(d.scheduled_at));
    const visible = scheduled.filter(d => inRange(d)), currentRange = range();
    const month = C.date.toLocaleDateString('zh-CN', {year: 'numeric', month: 'long'});
    const period = C.view === 'week' ? `${currentRange.start.toLocaleDateString('zh-CN', {year: 'numeric', month: 'numeric', day: 'numeric'})} — ${addDays(currentRange.end, -1).toLocaleDateString('zh-CN', {month: 'numeric', day: 'numeric'})}` : month;
    const allPlatforms = (C.ctx?.platforms?.length ? C.ctx.platforms : Object.entries(LABELS).map(([id, name]) => ({id, name}))).filter(p => p.id !== 'google_ads');
    const activeFilters = !!(C.query || C.platform || C.account || C.status);
    return `<div class="mc-intro"><div><h1>发布日历</h1></div><div class="mc-intro-actions">${C.ctx.exportURL ? overflowMenu() : ''}${button('new', `${svg('plus')}新建内容`, isDemo() ? 'disabled title="返回真实数据后可新建"' : '', 'mc-primary')}</div></div><div class="mc-context-row"><span class="mc-timezone">${svg('clock')}${esc(timezone())}</span></div>${isDemo() ? '<div class="mc-demo-note"><strong>演示内容 · 只读</strong><button type="button" class="mc-button" data-action="real">返回真实数据</button></div>' : ''}<div class="mc-summary"><div><span class="mc-summary-dot mc-purple"></span><strong>${visible.length}</strong><span>${C.view === 'week' ? '本周' : '本月'}安排</span></div><div><span class="mc-summary-dot mc-amber"></span><strong>${items.filter(d => d.status === 'review').length}</strong><span>待审核</span></div><button type="button" data-mc-action="focus-unscheduled"><span class="mc-summary-dot mc-gray"></span><strong>${unscheduled.length}</strong><span>未排期</span></button><span class="mc-summary-scope">${items.length} 条内容</span></div><section class="mc-calendar-shell" aria-label="内容排期"><div class="mc-toolbar"><div class="mc-date-navigation"><h2>${esc(period)}</h2><div class="mc-date-buttons">${button('prev', svg('left'), `aria-label="上${C.view === 'week' ? '一周' : '个月'}"`, 'mc-icon-button')}${button('next', svg('right'), `aria-label="下${C.view === 'week' ? '一周' : '个月'}"`, 'mc-icon-button')}${button('today', '今天', '', 'mc-today-button')}</div></div><div class="mc-view-switch" role="group" aria-label="日历显示方式">${[['month', 'grid', '月'], ['week', 'week', '周'], ['list', 'list', '列表']].map(([id, icon, label]) => button('view', `${svg(icon)}${label}`, `data-mc-view="${id}" aria-pressed="${C.view === id}"`, C.view === id ? 'mc-selected' : '')).join('')}</div></div><div class="mc-filters"><label class="mc-search">${svg('search')}<input type="search" id="calendar-search" data-mc-filter="query" aria-label="搜索标题或正文" placeholder="搜索标题或正文" value="${esc(C.query)}"></label><div class="mc-select">${listbox({ id: 'mc-filter-platform', label: '按平台筛选', value: C.platform || '', className: 'listbox-block', attrs: { 'data-mc-filter': 'platform' }, options: [['', '全部平台'], ...allPlatforms.map(p => [p.id, platformName(p.id)])] })}</div><div class="mc-select">${listbox({ id: 'mc-filter-account', label: '按账号筛选', value: C.account || '', className: 'listbox-block', attrs: { 'data-mc-filter': 'account' }, options: [['', '全部账号'], ...accounts().map(a => [String(a.id), `${a.brand ? `${a.brand} · ` : ''}${a.name || a.handle} · ${platformName(a.platform)}`])] })}</div><div class="mc-select">${listbox({ id: 'mc-filter-status', label: '按内容状态筛选', value: C.status || '', className: 'listbox-block', attrs: { 'data-mc-filter': 'status' }, options: [['', '全部状态'], ...Object.entries(STATUS)] })}</div>${activeFilters ? button('reset-filters', '清除', '', 'mc-clear') : ''}</div>${C.view === 'month' ? monthView(scheduled) : C.view === 'week' ? weekView(scheduled) : listView(scheduled)}${C.view !== 'list' && !visible.length ? `<div class="mc-range-empty"><span>${drafts().length ? '当前日期范围内没有符合条件的排期。' : '日历还是空的。'}</span>${scheduled.length ? button('jump-content', '跳到最近有内容的日期', '', 'mc-text-button') : ''}${demoLink()}</div>` : ''}<footer class="mc-calendar-footer"><span><i class="mc-legend-dot mc-draft"></i>草稿</span><span><i class="mc-legend-dot mc-review"></i>待审核</span><span><i class="mc-legend-dot mc-approved"></i>已批准</span></footer></section><section class="mc-unscheduled" aria-label="未排期内容"><button type="button" class="mc-unscheduled-toggle" data-mc-action="toggle-unscheduled" aria-expanded="${C.unscheduled}"><span><span class="mc-unscheduled-icon">${svg('calendar')}</span><strong>未排期内容</strong><span class="mc-count">${unscheduled.length}</span></span><span class="mc-collapse-icon ${C.unscheduled ? 'mc-expanded' : ''}">${svg('chevron')}</span></button>${C.unscheduled ? `<div class="mc-unscheduled-body">${unscheduled.length ? `<div class="mc-unscheduled-grid">${unscheduled.map(d => card(d, false)).join('')}</div>` : `<p class="mc-unscheduled-empty">${activeFilters ? '当前筛选内没有未排期内容。' : '没有待安排的草稿。'}</p>`}</div>` : ''}</section><dialog class="mc-dialog" id="mc-dialog" aria-labelledby="mc-dialog-title"></dialog>`;
  }
  function render(ctx) {
    if (C.dataset !== ctx.dataset) { C.query = ''; C.platform = ''; C.account = ''; C.status = ''; C.date = new Date(); C.view = 'month'; C.dataset = ctx.dataset; C.samples = null; }
    C.ctx = ctx;
    if (!C.samples) C.samples = makeSamples();
    return `<section id="media-calendar" class="mc-workspace">${content()}</section>`;
  }
  function draw(preserveFocus = false) {
    const el = root(); if (!el) return;
    const active = document.activeElement, filter = active?.dataset.mcFilter, action = active?.dataset.mcAction, view = active?.dataset.mcView, start = active?.selectionStart, end = active?.selectionEnd;
    el.innerHTML = content();
    if (filter) { const input = el.querySelector(`[data-mc-filter="${filter}"]`); input?.focus(); if (preserveFocus && input?.setSelectionRange && start !== null) { try { input.setSelectionRange(start, end); } catch {} } }
    else if (action) { [...el.querySelectorAll('[data-mc-action]')].find(item => item.dataset.mcAction === action && (!view || item.dataset.mcView === view))?.focus(); }
  }
  function openDialog(html) { const dialog = root()?.querySelector('#mc-dialog'); if (!dialog) return; C.previousFocus = document.activeElement; dialog.innerHTML = html; dialog.showModal(); }
  function closeDialog() { const dialog = root()?.querySelector('#mc-dialog'); if (dialog?.open) dialog.close(); }
  const dialogHeader = title => `<header class="mc-dialog-header"><h2 id="mc-dialog-title">${title}</h2>${button('close-dialog', svg('close'), 'aria-label="关闭"', 'mc-icon-button')}</header>`;
  function showPreview(draft) { openDialog(`${dialogHeader(isDemo() ? '示例内容预览' : '内容详情')}<div class="mc-preview"><div class="mc-preview-tags">${pips(draft)}<span class="mc-preview-status">${esc(statusLabel(draft))}</span></div><h3>${esc(draft.title || '未命名内容')}</h3><p class="mc-preview-account">${esc(accountNames(draft))}</p><div class="mc-preview-body">${esc(draft.body || '')}</div><p class="mc-preview-date">${svg('clock')}${draft.scheduled_at && parseDate(draft.scheduled_at) ? esc(parseDate(draft.scheduled_at).toLocaleString('zh-CN', {year: 'numeric', month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit'})) : '尚未排期'} · ${esc(timezone())}</p><footer>${button('copy', `${svg('copy')}复制发布包`, `data-mc-id="${esc(draft.id)}"`, 'mc-primary')}${button('close-dialog', '关闭')}</footer></div>`); }
  function showSchedule(draft) {
    if (isDemo()) { notify('演示内容只读，请返回真实数据后再安排时间。'); return; }
    const d = parseDate(draft.scheduled_at) || new Date(); if (!draft.scheduled_at) { d.setDate(d.getDate() + 1); d.setHours(9, 0, 0, 0); }
    openDialog(`${dialogHeader(draft.scheduled_at ? '修改内容排期' : '安排发布时间')}<form data-mc-form="schedule" data-mc-id="${esc(draft.id)}"><p class="mc-dialog-draft-title">${esc(draft.title || '未命名内容')}</p><label class="mc-dialog-field"><span>计划时间</span><input name="scheduled_at" type="datetime-local" value="${localInput(d)}" required aria-describedby="mc-time-help"><small id="mc-time-help">${esc(timezone())}</small></label><p class="mc-dialog-notice">修改排期后，内容会回到草稿状态，需重新审核。这个时间只是提醒，到时间不会自动发出。</p><p class="mc-form-error" role="alert"></p><footer class="mc-dialog-actions">${draft.scheduled_at ? button('unschedule', '移回未排期', `data-mc-id="${esc(draft.id)}"`, 'mc-text-button') : ''}<span></span>${button('close-dialog', '取消')}<button type="submit" class="mc-button mc-primary">保存排期</button></footer></form>`);
    root()?.querySelector('[name="scheduled_at"]')?.focus();
  }
  async function saveSchedule(id, value) {
    if (isDemo() || C.busy) return;
    const dialog = root()?.querySelector('#mc-dialog'), originalContext = C.ctx;
    const previousSchedule = findDraft(id)?.scheduled_at || '';
    C.busy = true; dialog?.querySelectorAll('button,input').forEach(el => { el.disabled = true; });
    try {
      const response = await fetch(`/api/drafts/${encodeURIComponent(id)}`, {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({scheduled_at: value})});
      let data; try { data = await response.json(); } catch { throw new Error('本地服务返回了不完整的结果，请刷新检查保存状态。'); }
      if (!response.ok || data.error) throw new Error(data.error || '排期保存失败，请重试。');
      if (C.ctx === originalContext) closeDialog();
      const savedSchedule = data.draft?.scheduled_at ?? value;
      const previousTime = parseDate(previousSchedule), savedTime = parseDate(savedSchedule);
      const unchanged = previousSchedule === savedSchedule || (previousTime && savedTime && previousTime.getTime() === savedTime.getTime());
      const message = unchanged ? '排期未变化。' : savedSchedule ? '本地排期已保存。' : '内容已移回未排期。';
      const savedStatus = STATUS[data.draft?.status];
      originalContext.toast?.(`${message}${savedStatus ? `当前状态：${savedStatus}。` : ''}`);
      if (!unchanged) shellChanged();
      try { await originalContext.onRefresh?.(); } catch { originalContext.toast?.('排期已保存；页面刷新未成功，请重新载入工作区。', true); }
    } catch (error) { const message = error.message || '排期保存失败，请重试。'; if (dialog?.isConnected) { const box = dialog.querySelector('.mc-form-error'); if (box) box.textContent = message; } originalContext.toast?.(message, true); }
    finally { C.busy = false; if (dialog?.isConnected) dialog.querySelectorAll('button,input').forEach(el => { el.disabled = false; }); }
  }
  async function saveDraftStatus(draft, status, source) {
    if (isDemo() || C.busy) return;
    if (!((draft.status === 'draft' && status === 'review') || (draft.status === 'review' && status === 'approved'))) return;
    const originalContext = C.ctx;
    C.busy = true; source.disabled = true;
    try {
      const response = await fetch(`/api/drafts/${encodeURIComponent(draft.id)}`, {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({status})});
      let data; try { data = await response.json(); } catch { throw new Error('本地服务返回了不完整的结果，请刷新检查审核状态。'); }
      if (!response.ok || data.error) throw new Error(data.error || '审核状态未能保存，请重试。');
      originalContext.toast?.(status === 'approved' ? '已批准内容；此状态不代表已经发布。' : '内容已提交本地审核。');
      shellChanged();
      try { await originalContext.onRefresh?.(); } catch { originalContext.toast?.('审核状态已保存；页面刷新未成功，请重新载入工作区。', true); }
    } catch (error) { originalContext.toast?.(error.message || '审核状态保存失败，请重试。', true); }
    finally { C.busy = false; if (source.isConnected) source.disabled = false; }
  }
  function copyFallback(text) { const area = document.createElement('textarea'); area.value = text; area.className = 'mc-clipboard'; (root()?.querySelector('dialog[open]') || root() || document.body).append(area); area.select(); const ok = document.execCommand('copy'); area.remove(); if (!ok) throw new Error('复制失败，请在编辑页手动复制内容。'); }
  async function copyDraft(draft) {
    const d = parseDate(draft.scheduled_at);
    const variants = draft.platform_variants && typeof draft.platform_variants === 'object' ? draft.platform_variants : {};
    const body = platformIDs(draft).some(id => variants[id]) ? platformIDs(draft).map(id => `【${platformName(id)}】\n${variants[id] || draft.body || ''}`).join('\n\n') : (draft.body || '');
    const text = `${isDemo() ? '【虚构示例 · 非真实发布内容】\n\n' : ''}标题：${draft.title || ''}\n\n正文：\n${body}\n\n目标平台：${platformIDs(draft).map(platformName).join('、')}\n目标账号：${accountNames(draft)}\n计划时间：${d ? `${d.toLocaleString('zh-CN')}（${timezone()}）` : '未排期'}\n审核状态：${statusLabel(draft)}`;
    try { if (navigator.clipboard?.writeText) { try { await navigator.clipboard.writeText(text); } catch { copyFallback(text); } } else copyFallback(text); notify('已复制'); } catch (error) { notify(error.message, true); }
  }
  function click(event) {
    const el = event.target.closest('[data-mc-action]'); if (!el || !root()?.contains(el) || el.disabled) return;
    const action = el.dataset.mcAction, draft = findDraft(el.dataset.mcId);
    if (action === 'close-dialog') { closeDialog(); return; }
    if (action === 'edit' && draft) { if (isDemo()) showPreview(draft); else { closeDialog(); C.ctx.onEdit?.(draft.id); } return; }
    if (action === 'schedule' && draft) { showSchedule(draft); return; }
    if (action === 'copy' && draft) { copyDraft(draft); return; }
    if (action === 'unschedule' && draft) { saveSchedule(draft.id, ''); return; }
    if (action === 'status' && draft) { saveDraftStatus(draft, el.dataset.mcStatus, el); return; }
    if (action === 'new' || action === 'new-day') { if (isDemo()) return; const day = atDay(el.dataset.mcDate); C.ctx.onNew?.(day ? `${dayKey(day)}T09:00` : undefined); return; }
    if (action === 'show-day') { const day = atDay(el.dataset.mcDate); if (!day) return; const rows = sorted(filtered().filter(d => { const value = parseDate(d.scheduled_at); return value && dayKey(value) === dayKey(day); })); openDialog(`${dialogHeader(esc(dateLabel(day)))}<div class="mc-day-dialog-cards">${rows.map(d => card(d, false)).join('')}</div>`); return; }
    if (action === 'view' && ['month', 'week', 'list'].includes(el.dataset.mcView)) C.view = el.dataset.mcView;
    if (action === 'prev' || action === 'next') { const direction = action === 'next' ? 1 : -1; C.date = C.view === 'week' ? addDays(C.date, direction * 7) : new Date(C.date.getFullYear(), C.date.getMonth() + direction, 1, 12); }
    if (action === 'today') C.date = new Date();
    if (action === 'reset-filters') { C.query = ''; C.platform = ''; C.account = ''; C.status = ''; }
    if (action === 'toggle-unscheduled') C.unscheduled = !C.unscheduled;
    if (action === 'focus-unscheduled') C.unscheduled = true;
    if (action === 'jump-content') { const now = new Date().getTime(); const rows = filtered().filter(d => parseDate(d.scheduled_at)).sort((a, b) => Math.abs(parseDate(a.scheduled_at).getTime() - now) - Math.abs(parseDate(b.scheduled_at).getTime() - now)); if (rows.length) C.date = parseDate(rows[0].scheduled_at); }
    draw();
    if (action === 'focus-unscheduled') root()?.querySelector('.mc-unscheduled')?.scrollIntoView({behavior: 'smooth', block: 'start'});
  }
  function mount() {
    unmount(); const el = root(); if (!el || !document.getElementById('content')?.contains(el)) return;
    C.controller = new AbortController(); const options = {signal: C.controller.signal};
    el.addEventListener('click', click, options);
    document.addEventListener('click', menuClick, options);
    el.addEventListener('keydown', menuKey, options);
    // Focus moving to another control (or out of this page) closes the menu; a click on its own item must not.
    el.addEventListener('focusout', event => { const {menu} = menuParts(); if (menu && !menu.hidden && event.relatedTarget && !menu.parentElement.contains(event.relatedTarget)) closeMenu(); }, options);
    window.addEventListener('blur', () => closeMenu(), options);
    el.addEventListener('input', event => { if (event.target.dataset.mcFilter === 'query') { C.query = event.target.value; if (!event.isComposing) draw(true); } }, options);
    el.addEventListener('compositionend', event => { if (event.target.dataset.mcFilter === 'query') { C.query = event.target.value; draw(true); } }, options);
    el.addEventListener('change', event => { const key = event.target.dataset.mcFilter; if (['platform', 'account', 'status'].includes(key)) { C[key] = event.target.value; draw(); } }, options);
    el.addEventListener('submit', event => { const form = event.target; if (form.dataset.mcForm !== 'schedule') return; event.preventDefault(); if (isDemo() || C.busy) return; const value = new FormData(form).get('scheduled_at'); const date = parseDate(value); if (!date || localInput(date) !== value) { form.querySelector('.mc-form-error').textContent = '请选择有效的日期和时间；夏令时切换时可能有不存在的时段。'; return; } saveSchedule(form.dataset.mcId, date.toISOString()); }, options);
    el.addEventListener('close', event => { if (event.target.id === 'mc-dialog' && C.previousFocus?.isConnected) C.previousFocus.focus(); }, {...options, capture: true});
  }
  function unmount() { C.controller?.abort(); C.controller = null; closeDialog(); C.previousFocus = null; }
  window.MediaCalendar = {render, mount, unmount};
})();
