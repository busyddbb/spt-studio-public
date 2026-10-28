'use strict';

(() => {
  const STATUS = { published: '已发布', ready: '待发布', cut: '已成片', wip: '制作中' };
  const PLATFORMS = { instagram: 'Instagram', facebook: 'Facebook', tiktok: 'TikTok', youtube: 'YouTube', google_business: 'Google Business Profile', google_business_profile: 'Google Business Profile', google: 'Google', yelp: 'Yelp', rednote: 'rednote', xiaohongshu: 'rednote', douyin: '抖音', wechat: '视频号', shipinhao: '视频号', bilibili: '哔哩哔哩', kuaishou: '快手' };
  let API_BASE = '/api';
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  const icon = (name) => `<span class="icon i-${name}" aria-hidden="true"></span>`;
  const asArray = (value) => Array.isArray(value) ? value : [];
  const platformName = (name) => PLATFORMS[name] || name || '其他平台';
  const nameOf = (file) => typeof file === 'string' ? file.split('/').pop() : file?.name || file?.path?.split('/').pop() || '未命名文件';
  const pathOf = (file) => typeof file === 'string' ? file : file?.path || '';
  const isVideo = (file) => /^video\//.test(file?.mime_type || file?.type || '') || /\.(mp4|mov|m4v|webm|mkv)$/i.test(nameOf(file));
  const isImage = (file) => /^image\//.test(file?.mime_type || file?.type || '') || /\.(jpg|jpeg|png|webp|gif|avif)$/i.test(nameOf(file));
  // One name per destination: sidebar label = page <h1> = document.title prefix = palette label.
  const PAGES = [
    ['desk', '运营', 'squares-four', 'desk home dashboard 总览 首页 今天'],
    ['works', '资产库', 'folder-open', 'works library assets 作品 提示词 素材 记录'],
    ['notes', '便签', 'note', 'notes 待办 备忘 日历'],
    ['analytics', '数据', 'chart-line', 'analytics data 图表 粉丝 播放 趋势'],
    ['intelligence', '情报', 'file-text', 'intelligence intel news 新闻 研究'],
    ['publish', '发布', 'arrow-square-out', 'publish entries 平台入口 账号 后台 官方 平台'],
    ['settings', '设置', 'gear-six', 'settings preferences 工作区 外观 主题 skills'],
  ];
  const PAGE_NAMES = Object.fromEntries(PAGES.map(([key, label]) => [key, label]));
  const TOOL_NAMES = { studio: '编辑内容', accounts: '账号档案', planner: '发布日历', uploads: '上传素材', planning: '内容计划', data: '数据导入', publish: '发布记录', connections: '发布设置' };
  const TOOL_ICONS = { studio: 'file-text', accounts: 'desktop', planner: 'list-bullets', uploads: 'image', planning: 'stack', data: 'download', publish: 'arrow-square-out', connections: 'gear-six' };
  const PREFILL_KEYS = ['client', 'platform', 'handle'];
  // 发布 is 平台入口 ('', the official back-office entrances) and 账号档案; the editing tools sit in a ⋯ menu.
  const PUBLISH_TABS = ['', 'accounts'];
  const PUBLISH_TOOLS = ['publish', 'studio', 'planner', 'uploads', 'planning'];
  const ENTRIES_HASH = '#publish';
  const ENTRIES_NAME = '平台入口';
  // The Skills list lives under 设置 (no kind tab in 资产库): the library page at this address.
  const SKILLS_HASH = '#works?kind=skill';
  // Tool pages that belong to 数据 (import), not 发布.
  const DATA_TOOLS = ['data'];
  // Nav entries that only make sense with something behind them; the others always show.
  const DATA_ROUTES = ['analytics', 'intelligence', 'publish'];

  function apiURL(path, base = API_BASE) {
    const suffix = String(path).replace(/^\/api(?=\/|\?|$)/, '');
    return `${base.replace(/\/$/, '')}${suffix.startsWith('/') || suffix.startsWith('?') ? '' : '/'}${suffix}`;
  }
  function safeLocalURL(value) {
    if (typeof value !== 'string' || !value.startsWith('/api/works/') || value.startsWith('//')) return '';
    try {
      const parsed = new URL(value, 'http://127.0.0.1');
      return parsed.origin === 'http://127.0.0.1' && /^\/api\/works\/[^/]+\/(file|cover)$/.test(parsed.pathname) ? apiURL(value) : '';
    } catch { return ''; }
  }
  function fileURL(id, file) {
    const supplied = typeof file === 'object' && safeLocalURL(file?.url);
    if (supplied) return supplied;
    const path = pathOf(file);
    return path ? apiURL(`/api/works/${encodeURIComponent(id)}/file?path=${encodeURIComponent(path)}`) : '';
  }
  function safeExternalURL(value) {
    try {
      const parsed = new URL(value);
      return ['https:', 'http:'].includes(parsed.protocol) ? parsed.href : '';
    } catch { return ''; }
  }
  function splitRecords(records) {
    const current = [], historical = [];
    for (const record of asArray(records)) {
      const withdrawn = ['withdrawn', 'history'].includes(record.state) || record.current === false || record.is_current === false;
      (withdrawn ? historical : current).push(record);
    }
    return { current, historical };
  }
  // Plain words for a creator: the adopted version is 定稿, otherwise the latest edit; nothing when there is no version yet.
  function versionLabel(work) {
    if (work.current_version) return `定稿：${work.current_version}`;
    return work.latest_version ? `最新改到 ${work.latest_version}` : '';
  }
  function statusHTML(work) {
    const status = Object.hasOwn(STATUS, work.status) ? work.status : 'wip';
    return `<span class="status ${status}">${STATUS[status]}</span>`;
  }
  function coverHTML(work) {
    const url = safeLocalURL(work.cover);
    const fallback = `<span class="cover-placeholder">${icon('film-strip')}<span>暂无封面</span></span>`;
    return `<span class="work-cover">${url ? `<img src="${esc(url)}" alt="" loading="lazy" decoding="async">` : fallback}</span>`;
  }
  // The one warning a card still carries: the local final is not what the record says was published.
  // Whether a publication was checked on the platform is the detail's business (status_basis), not every card's.
  function mismatchNote(work) { return work.media_match === 'mismatch' ? '本地成片和发布记录里的不一样' : ''; }
  // A card is an <article>: the open button and the corner 复制 button sit side by side, never nested.
  // clientTag: the rendered client tag (swatch + name); without one the subtitle shows the code or the 专业.
  function cardHTML(work, clientTag = '') {
    const warning = mismatchNote(work), version = versionLabel(work);
    return `<article class="work-card"><button type="button" class="work-open" data-work="${esc(work.id)}" aria-label="查看${esc(work.title)}">${coverHTML(work)}<span class="work-info"><span class="work-title-row"><span class="work-title" title="${esc(work.title)}">${esc(work.title)}</span></span><span class="work-subtitle">${clientTag || `<span>${esc(work.client || work.category)}</span>`}<span>${esc(work.date || '')}</span></span><span class="work-meta">${statusHTML(work)}${version ? `<span class="work-version">${esc(version)}</span>` : ''}</span>${warning ? `<span class="work-warning">${icon('warning-circle')}<span>${esc(warning)}</span></span>` : ''}</span></button><button type="button" class="item-copy work-copy" data-copy-work="${esc(work.id)}" title="复制提示词（没有就复制文案）" aria-label="复制${esc(work.title)}的提示词或文案">${icon('copy')}</button></article>`;
  }
  function listRowHTML(work, clientTag = '') {
    const warning = mismatchNote(work), version = versionLabel(work);
    return `<tr><td><button type="button" class="table-work" data-work="${esc(work.id)}" aria-label="查看${esc(work.title)}">${coverHTML(work)}<span><span class="work-title">${esc(work.title)}</span>${version ? `<span class="table-version">${esc(version)}</span>` : ''}${warning ? `<span class="work-warning">${esc(warning)}</span>` : ''}</span></button></td><td>${clientTag || esc(work.client || '')}</td><td>${esc(work.date || '')}</td><td>${statusHTML(work)}</td></tr>`;
  }
  // The 资产库 address carries its filters: client (客户), category (专业) and status. worksParams returns only the
  // keys the address has, so navigate() leaves the others as they are.
  function worksHash({ client = '', category = '', status = '' } = {}) {
    const params = new URLSearchParams();
    if (client) params.set('client', client);
    if (category) params.set('category', category);
    if (status && Object.hasOwn(STATUS, status)) params.set('status', status);
    const query = params.toString();
    return `#works${query ? `?${query}` : ''}`;
  }
  function worksParams(params) {
    const out = {};
    const text = (key) => String(params.get(key) || '').replace(/[\u0000-\u001f]/g, '').trim().slice(0, 60);
    if (params.has('client')) out.client = text('client');
    if (params.has('category')) out.category = text('category');
    if (params.has('status')) out.status = Object.hasOwn(STATUS, params.get('status') || '') ? params.get('status') : '';
    return out;
  }
  // ⌘K subtitles: a work shows its client's name (else its 专业) and date; an item its client's name and group.
  function paletteHint(entry, clients = [], kind = 'work') {
    const client = entry?.client ? (asArray(clients).find((item) => item.code === entry.client)?.name || entry.client) : '';
    const parts = kind === 'work' ? [client || entry?.category, entry?.date] : [client, entry?.section];
    return parts.filter(Boolean).join(' · ');
  }
  function formatSize(value) {
    if (!Number.isFinite(Number(value)) || Number(value) <= 0) return '';
    const size = Number(value);
    if (size < 1024 * 1024) return `${(size / 1024).toFixed(0)} KB`;
    if (size < 1024 * 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`;
    return `${(size / 1024 / 1024 / 1024).toFixed(1)} GB`;
  }
  function readableTime(value) {
    if (!value) return '尚未索引';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
  }
  // A plain browser tab (Windows, or a Mac browser) has no SPT app bridge at all; an SPT app
  // that only lacks the publishing bridge is an old build and keeps its buttons.
  function inBrowser(host) { return !host?.mediaNativeAvailable && !host?.webkit?.messageHandlers; }
  // The official backends the SPT app's built-in window opens; a browser opens them in a new tab.
  const OFFICIAL_URLS = { rednote: 'https://creator.rednote.com/new/note-manager', xiaohongshu: 'https://creator.rednote.com/new/note-manager', instagram: 'https://www.instagram.com/', facebook: 'https://business.facebook.com/', tiktok: 'https://www.tiktok.com/tiktokstudio/upload', youtube: 'https://studio.youtube.com/', google_business: 'https://business.google.com/', google_business_profile: 'https://business.google.com/', google: 'https://business.google.com/', yelp: 'https://biz.yelp.com/', meta_suite: 'https://business.facebook.com/latest/home' };
  function officialURL(platform) { return Object.prototype.hasOwnProperty.call(OFFICIAL_URLS, platform) ? OFFICIAL_URLS[platform] : ''; }
  function hasAccountBridge(host) {
    return !!host?.mediaPublishingNativeAvailable && typeof host?.webkit?.messageHandlers?.openPublishing?.postMessage === 'function';
  }
  function requestAccountOpen(account, host, target = '') {
    if (!/^[A-Za-z0-9_-]{1,128}$/.test(account?.legacy_account_id || '')) return { error: '请先关联发布账号。' };
    if (!hasAccountBridge(host)) return { error: '请从 SPT 应用打开官方后台。' };
    if (target && target !== 'meta_suite') return { error: '未知的打开目标。' };
    try {
      const request = { account_id: account.legacy_account_id };
      if (target) request.target = target;
      host.webkit.messageHandlers.openPublishing.postMessage(request);
      return { opening: true };
    } catch { return { error: '官方后台未能打开，请重试。' }; }
  }
  function accountOpenResult(result) {
    if (result?.error) return { opened: false, message: String(result.error) };
    if (result?.ok === true && result?.opened === true) return { opened: true, message: '官方后台已打开' };
    return { opened: false, message: '官方后台未能打开，请重试。' };
  }
  // 发布 sub-tabs: 平台入口, 账号档案; the open tool from the ⋯ menu (or 发布设置) joins at the end.
  function publishTabs(current = '') {
    const tabs = [...PUBLISH_TABS];
    if (current && TOOL_NAMES[current] && !tabs.includes(current) && !DATA_TOOLS.includes(current)) tabs.push(current);
    return tabs;
  }
  // The ⋯ menu's tools; a shared copy (friends without 用户's data sources) has none.
  function publishMore(share = false) { return share ? [] : [...PUBLISH_TOOLS]; }
  // /api/health reports share: true only in the copy friends receive; a missing field is false.
  const isShare = (health) => health?.share === true;
  // Nav entries with nothing behind them, once the dashboard snapshot is in (null = still loading: list all).
  function hiddenRoutes(dashboard, health) {
    if (!dashboard) return [];
    const accounts = asArray(dashboard.accounts), intel = dashboard.intelligence || {};
    const sampled = accounts.some((account) => account?.as_of || asArray(account?.history).length);
    const data = asArray(dashboard.posts).length || asArray(dashboard.history_posts).length || sampled || Number(health?.counts?.imports) > 0;
    const intelligence = ['news', 'research', 'candidates'].some((key) => asArray(intel[key]).length);
    return DATA_ROUTES.filter((route) => route === 'analytics' ? !data : route === 'intelligence' ? !intelligence : !accounts.length);
  }
  // Where an address lands instead (the caller uses location.replace), or '' to stay.
  function routeRedirect(raw) {
    const [path, query = ''] = String(raw || '').split('?');
    const params = new URLSearchParams(query);
    if (path === 'tools' && params.get('name') === 'overview') return '#tools?name=data';
    return '';
  }
  // The sidebar entry a page belongs to: tools under 发布 (数据导入 under 数据), the Skills list under 设置.
  function navRoute(route, tool = '', skills = false) {
    if (route === 'tools') return DATA_TOOLS.includes(tool) ? 'analytics' : 'publish';
    return route === 'works' && skills ? 'settings' : route;
  }
  // document.title = the page's h1: a tool's name, 平台入口, Skills, else the sidebar label.
  function pageTitle(route, tool = '', view = '') {
    if (route === 'tools') return `${TOOL_NAMES[tool] || PAGE_NAMES.publish} · SPT`;
    if (route === 'publish') return `${ENTRIES_NAME} · SPT`;
    if (route === 'works' && view === 'skills') return 'Skills · SPT';
    return `${PAGE_NAMES[route] || PAGE_NAMES.desk} · SPT`;
  }
  // Palette match: 3 label prefix, 2 substring of label or keywords, 1 label letters in order, 0 no match.
  function matchScore(query, label, keys = '') {
    const q = String(query || '').trim().toLowerCase();
    if (!q) return 1;
    const name = String(label || '').toLowerCase();
    if (name.startsWith(q)) return 3;
    if (name.includes(q) || String(keys || '').toLowerCase().includes(q)) return 2;
    const compact = q.replace(/\s+/g, '');
    let at = 0;
    for (const char of name) if (char === compact[at]) at += 1;
    return compact && at >= compact.length ? 1 : 0;
  }
  function toastDuration(tone, hasAction, duration) {
    if (Number.isFinite(duration) && duration > 0) return duration;
    if (tone === 'error') return 0;
    return hasAction ? 8000 : 4000;
  }
  // Roving focus in a tablist: the index to move to, or -1 when the key does not move.
  function rovingIndex(key, index, count, vertical = false) {
    if (count < 1) return -1;
    if (key === 'Home') return 0;
    if (key === 'End') return count - 1;
    if (key === (vertical ? 'ArrowUp' : 'ArrowLeft')) return (Math.max(index, 0) - 1 + count) % count;
    if (key === (vertical ? 'ArrowDown' : 'ArrowRight')) return (index + 1) % count;
    return -1;
  }
  function neighborIds(ids, id) {
    const index = asArray(ids).indexOf(id);
    return index < 0 ? { prev: '', next: '' } : { prev: ids[index - 1] || '', next: ids[index + 1] || '' };
  }
  // The one place that knows how to put a taken-down note back: the take-down result carries its old
  // index (back in place); a shelf entry has none (appended to its group).
  function restoreRequest(note) {
    const body = { id: String(note?.id || ''), rope: String(note?.rope || '') };
    if (Number.isInteger(note?.index) && note.index >= 0) body.index = note.index;
    return body;
  }
  function nextDelay(delay) { return Math.min(Math.max(5000, Number(delay) * 2 || 0), 30000); }
  function resolveTheme(value, prefersDark) { return value === 'light' ? 'light' : value === 'system' ? (prefersDark ? 'dark' : 'light') : 'dark'; }
  const exports = { esc,apiURL,safeLocalURL,safeExternalURL,fileURL,splitRecords,versionLabel,statusHTML,coverHTML,mismatchNote,cardHTML,listRowHTML,worksHash,worksParams,paletteHint,isVideo,isImage,formatSize,inBrowser,officialURL,agentCommands,hasAccountBridge,requestAccountOpen,accountOpenResult,PAGE_NAMES,TOOL_NAMES,DATA_TOOLS,DATA_ROUTES,PUBLISH_TOOLS,ENTRIES_HASH,SKILLS_HASH,publishTabs,publishMore,isShare,hiddenRoutes,routeRedirect,navRoute,pageTitle,matchScore,toastDuration,rovingIndex,neighborIds,restoreRequest,nextDelay,resolveTheme };
  if (typeof module !== 'undefined' && module.exports) module.exports = exports;
  if (typeof document === 'undefined') return;
  const configuredBase = document.body.dataset.apiBase;
  if (configuredBase && /^\/api(?:\/[a-z0-9_-]+)*$/i.test(configuredBase)) API_BASE = configuredBase;
  const $ = (selector, parent = document) => parent.querySelector(selector);
  const $$ = (selector, parent = document) => [...parent.querySelectorAll(selector)];
  const dashboard = window.MediaDashboard;
  const library = window.SPTLibrary;
  const analytics = window.MediaAnalytics;
  const notesUI = window.SPTNotes;
  const Listbox = window.SPTListbox;
  const COVER_MODES = ['square', 'portrait', 'original'];
  const ROUTES = ['desk', 'works', 'analytics', 'intelligence', 'notes', 'publish', 'settings', 'tools'];
  const DETAIL_TABS = [['versions', '版本'], ['captions', '文案'], ['records', '记录'], ['files', '文件'], ['metrics', '数据']];
  // The overview shows each client's newest few; 全部 N opens the rest.
  const OVERVIEW_LIMIT = 10;
  const TOAST_ICONS = { info: 'info', success: 'check', warn: 'warning-circle', error: 'warning-circle' };
  const ARROWS = ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'];
  const state = {
    health:null, allWorks:[], works:[], query:'', category:'', status:'', client:'', clients:[], allItems:{}, layout:'grid', cover:'square',
    route:'desk', loading:false, error:'', detail:null, detailId:null, detailTab:'versions',
    version:'', preview:null, eventSource:null, requestId:0, requestController:null,
    detailRequestId:0, reindexing:false, theme:'dark', returnFocus:null, returnKey:'', extras:null,
    dashboard:null, dashboardLoading:false, dashboardError:'', dashboardRequestId:0,
    // 读数据 needs the Mac app (MetricsReader.swift); browsers and Windows have no reader.
    metricsReader:window.mediaMetricsReaderAvailable===true, metricsReading:false,
    brand:'all', window:'latest', accountMetric:'followers', accountId:'', postId:'', analyticsMetric:'views', analyticsPlatform:'all', analyticsRange:'all', analyticsView:'chart', analyticsContent:'rank', analyticsTag:'',
    intelTab:'news', intelPageTab:'news', pendingNativeDraft:null, tool:'studio', toolDraft:'', density:'comfortable', motion:'full', openingAccountId:null, welcomeDismissed:false,
    notes:null, notesView:'board', notesMonth:'', notesLoading:false, notesError:'', notesRequestId:0, dragging:null, workspaceSaving:false,
    notesQuery:'', noteDay:'', dayOpen:'', noteConflict:null, noteReturnFocus:null, noteReturnKey:'', lastNote:'', postReturnFocus:null, postReturnKey:'',
    kind:'work', libraryKind:'work', libraryQuery:'', section:'', items:[], itemsLoading:false, itemsError:'', itemRequestId:0, itemController:null, libraryIndex:null, libraryIndexFailed:false, item:null,
    matchCounts:null, countRequestId:0, countController:null, indexStamp:0, openGroups:new Set(), closedGroups:new Set(), worksQuiet:false, itemsQuiet:false,
    detailKind:'', detailStack:[], detailFocus:null,
  };
  // Connection to the local service: offline banner, retry with backoff (5s to 30s).
  const net = { online:true, delay:5000, timer:0, checking:false, streamErrors:0, readAt:null };
  // Palette: results = the last server search {query, works, items}; searching = the query being fetched.
  const pal = { items:[], active:0, moved:false, returnFocus:null, returnKey:'', results:null, searching:'', error:'', timer:0, controller:null, requestId:0 };
  const modalStack = [];
  let searchTimer,accountOpenTimer,noteSnapshot=null,navigated=false,frameEl=null;
  const libraryHTML = $('#library-template').innerHTML;
  const dialog = $('#detail-dialog');
  const postDialog = $('#post-dialog');
  const noteDialog = $('#note-dialog');
  const palette = $('#palette');
  // Dialogs the page does not ship in its HTML: 整理客户 (the wide detail shell) and the small confirm (the note shell).
  function makeDialog(id,className,title) {
    const element=document.createElement('dialog');
    element.id=id;element.className=className;element.setAttribute('aria-labelledby',title);
    element.innerHTML=`<div id="${id}-content"></div>`;
    document.body.append(element);
    return element;
  }
  const clientsDialog = makeDialog('clients-dialog','detail-dialog clients-dialog','clients-title');
  const confirmDialog = makeDialog('confirm-dialog','note-dialog confirm-dialog','confirm-title');
  // The 运营 preview and the library draw the same card: the client tag comes from the clients directory.
  const deps = {esc,icon,apiURL:(path)=>apiURL(path),readableTime,safeLocalURL,safeExternalURL,platformName,cardHTML:(work)=>cardHTML(work,clientTag(work.client)),nativeAvailable:()=>hasAccountBridge(window),browser:()=>inBrowser(window),officialURL,workspace:()=>state.health?.workspace_resolved||state.health?.workspace_path||'',plannerURL:()=>isShare(state.health)?'':toolURL('planner'),dataURL:()=>toolURL('data'),sideRail:()=>notesUI?notesUI.railHTML(state.notes,deps):''};
  // -- 客户 ----------------------------------------------------------------------------
  // The clients directory (health.clients, else derived from the works) drives chips, blocks, tags and ⌘K hints.
  function syncClients() { state.clients=library?library.clientDirectory(state.health,state.allWorks):[]; }
  function clientTag(code) { return library?library.clientTagHTML(code,state.clients,deps):''; }
  const workClient=(work)=>String(work?.client||'');
  const itemClient=(item)=>item?.client||library?.GENERAL_CLIENT||'通用';
  // Items carry client only on a service that knows clients; without it the row and the filter stay away.
  const itemsTagged=(items)=>asArray(items).some((item)=>item&&Object.hasOwn(item,'client'));
  function countBy(list,keyOf) {
    const counts={};
    for(const entry of asArray(list)){const key=keyOf(entry);if(key)counts[key]=(counts[key]||0)+1;}
    return counts;
  }
  // The pool the client chips count: every work, or the kind's unfiltered items (state.allItems) when they are in.
  function clientPool() {
    if(state.kind==='work'||!libraryReady())return {list:state.allWorks,total:state.allWorks.length,tagged:true,keyOf:workClient};
    const full=state.allItems[state.kind]||null, list=full||state.items;
    return {list,total:full?full.length:state.libraryIndex?.kinds?.[state.kind]?.count||list.length,tagged:itemsTagged(list),keyOf:itemClient};
  }
  function clientChipGroups(selected=state.client) {
    const pool=clientPool();
    if(!library||!pool.tagged||state.kind==='skill')return [];
    return library.clientChips(state.clients,countBy(pool.list,pool.keyOf),selected,{general:state.kind!=='work',groups:clientGroups()});
  }
  // Group order for chips and overview blocks: health.client_groups (file order), else 自己 / 客户.
  function clientGroups() { return library?library.clientGroupNames(state.health,state.clients):[]; }
  // 整理客户 needs a service that knows groups (it answers /api/clients/save).
  function clientGroupsSupported() { return Array.isArray(state.health?.client_groups)||state.health?.capabilities?.clients===true; }
  const showsClientRow=()=>clientChipGroups('').length>0;

  function readPreference(name,fallback) {
    try { return localStorage.getItem(`media-studio.${name}`) || fallback; } catch { return fallback; }
  }
  function savePreference(name,value) {
    try { localStorage.setItem(`media-studio.${name}`,value); } catch { /* The workbench also works without local storage. */ }
  }
  // 工具页自己会跟着主页面的 data-theme / density / motion 变；这里只是给旧版工具页兜底。
  function syncFrameTheme() {
    try { const root=frameEl?.contentDocument?.documentElement, own=document.documentElement.dataset; if(root)for(const key of ['theme','density','motion'])root.dataset[key]=own[key]; } catch { /* 不同源的工具页自己管主题 */ }
  }
  function setTheme(value) {
    state.theme = ['light','dark','system'].includes(value) ? value : 'dark';
    document.documentElement.dataset.theme = resolveTheme(state.theme, matchMedia('(prefers-color-scheme: dark)').matches);
    savePreference('theme',state.theme);
    $$('.theme-choice[data-theme]').forEach((button) => button.setAttribute('aria-pressed',String(button.dataset.theme === state.theme)));
    syncFrameTheme();
  }
  function setDensity(value) {
    state.density = value === 'compact' ? 'compact' : 'comfortable';
    document.documentElement.dataset.density = state.density;
    savePreference('density',state.density);
    syncFrameTheme();
    $$('[data-density-choice]').forEach((button) => button.setAttribute('aria-pressed',String(button.dataset.densityChoice === state.density)));
  }
  function setMotion(value) {
    state.motion = value === 'reduced' ? 'reduced' : 'full';
    document.documentElement.dataset.motion = state.motion;
    savePreference('motion',state.motion);
    syncFrameTheme();
    $$('[data-motion-choice]').forEach((button) => button.setAttribute('aria-pressed',String(button.dataset.motionChoice === state.motion)));
  }

  // -- focus and layers ---------------------------------------------------
  // A selector that finds "the same" control after a re-render: its id, else its first data-* attribute.
  function keyOf(element) {
    if (!element?.tagName || element === document.body) return '';
    if (element.tagName === 'H1' && element.closest('#view')) return '#view h1';
    if (element.id) return `#${CSS.escape(element.id)}`;
    const attr = [...element.attributes].find((item) => item.name.startsWith('data-'));
    return attr ? `${element.tagName.toLowerCase()}[${attr.name}="${CSS.escape(attr.value)}"]` : '';
  }
  // WebKit (the SPT app) does not focus a button or link on click: remember the control a click came from.
  let clicked=null, clickedAt=0;
  function lastClicked() { return clicked?.isConnected&&performance.now()-clickedAt<1000?clicked:null; }
  function returnTarget() { return lastClicked()||document.activeElement; }
  // Focus left on <body> or inside a closed dialog (Chrome blurs it only later) counts as lost.
  function focusLost(element = document.activeElement) { return !element || element === document.body || !element.isConnected || !!element.closest('dialog:not([open])'); }
  function restoreFocus(element,key) {
    const target = element?.isConnected && element !== document.body ? element : key ? $(key) : null;
    if (target) target.focus({ preventScroll:true });
    return !!target && document.activeElement === target;
  }
  function keepFocus(container,render) {
    const active = document.activeElement;
    const key = container && active && active !== container && container.contains(active) ? keyOf(active) : '';
    render();
    if (key && !container.contains(document.activeElement)) $(key,container)?.focus({ preventScroll:true });
  }
  function rerender(container,html) { if(container)keepFocus(container,()=>{container.innerHTML=html;}); }
  function isTypingTarget(element) { return !!element?.closest?.('input,textarea,select,[contenteditable=""],[contenteditable="true"]'); }
  function openModal(modal) {
    if (!modal.open) modal.showModal();
    const at = modalStack.indexOf(modal);
    if (at >= 0) modalStack.splice(at,1);
    modalStack.push(modal);
    placeToasts();
  }
  function topModal() {
    for (let index = modalStack.length - 1; index >= 0; index -= 1) if (modalStack[index].open) return modalStack[index];
    return null;
  }
  function requestClose(modal) {
    if (modal === noteDialog) closeNoteDialog();
    else if (modal === palette) closePalette();
    else if (modal === clientsDialog) closeClientsDialog();
    else if (modal === confirmDialog) settleConfirm(false);
    else modal.close();
  }
  function closeTopLayer(event) {
    const top = topModal();
    if (top) { event.preventDefault(); requestClose(top); return; }
    const menu = $('.export-menu[open]');
    if (menu) { event.preventDefault(); menu.open = false; $('summary',menu)?.focus(); }
  }

  // -- toasts ---------------------------------------------------------------
  // Toasts sit in the top-most open dialog: a modal dialog makes the rest of the page inert.
  function placeToasts() {
    const region = $('#notice'), host = topModal() || document.body;
    if (region && region.parentElement !== host) host.appendChild(region);
  }
  // notice(message, {tone: info|success|warn|error, action: {label, run}, duration, key}); a toast with the same key is updated in place.
  function notice(message,options={}) {
    const region = $('#notice');
    if (!region) return null;
    placeToasts();
    const same = options.key && $$('.toast',region).find((item) => item.dataset.key === options.key);
    if (same?.update) { same.update(message); return same; }
    const tone = Object.hasOwn(TOAST_ICONS,options.tone) ? options.tone : 'info';
    const action = typeof options.action?.run === 'function' ? options.action : null;
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.dataset.tone = tone;
    toast.setAttribute('role',tone === 'error' ? 'alert' : 'status');
    if (options.key) toast.dataset.key = options.key;
    toast.innerHTML = `${icon(TOAST_ICONS[tone])}<p class="toast-message"></p>${action ? `<button type="button" class="toast-action">${esc(action.label || '撤销')}</button>` : ''}<button type="button" class="icon-button toast-close" aria-label="关闭提示">${icon('x')}</button>`;
    const duration = toastDuration(tone,!!action,options.duration);
    let timer = 0, remaining = duration, started = 0, hovered = false, focused = false, cameFrom = null;
    const start = () => { clearTimeout(timer); if (hovered || focused || !duration) return; started = Date.now(); timer = setTimeout(dismiss,remaining); };
    const pause = () => { clearTimeout(timer); if (started) remaining = Math.max(1500,remaining - (Date.now() - started)); started = 0; };
    function dismiss() {
      clearTimeout(timer);
      const hadFocus = toast.contains(document.activeElement);
      toast.remove();
      if (hadFocus && !restoreFocus(cameFrom,'')) $('#view')?.focus({ preventScroll:true });
    }
    toast.update = (text) => { $('.toast-message',toast).textContent = text; remaining = duration; started = 0; start(); };
    $('.toast-message',toast).textContent = message;
    toast.addEventListener('mouseenter',() => { hovered = true; pause(); });
    toast.addEventListener('mouseleave',() => { hovered = false; start(); });
    toast.addEventListener('focusin',(event) => { if (!focused) cameFrom = event.relatedTarget; focused = true; pause(); });
    toast.addEventListener('focusout',(event) => { if (toast.contains(event.relatedTarget)) return; focused = false; start(); });
    $('.toast-close',toast).addEventListener('click',dismiss);
    if (action) $('.toast-action',toast).addEventListener('click',() => { dismiss(); action.run(); });
    region.appendChild(toast);
    $$('.toast',region).slice(0,-3).forEach((item) => item.remove());
    start();
    return toast;
  }

  // -- connection -------------------------------------------------------------
  function clockTime(date) {
    const time = date.toLocaleTimeString('zh-CN',{ hour:'2-digit', minute:'2-digit', hour12:false });
    return localDay(date) === localDay() ? time : `${date.getMonth() + 1}月${date.getDate()}日 ${time}`;
  }
  function renderOffline() {
    const banner = $('#offline-banner');
    if (!banner) return;
    banner.hidden = net.online;
    if (net.online) return;
    const text = $('p',banner);
    if (net.readAt) text.innerHTML = `连不上 SPT 本机服务。页面显示的是 <time datetime="${esc(net.readAt.toISOString())}">${esc(clockTime(net.readAt))}</time> 读取的内容。`;
    else text.textContent = '连不上 SPT 本机服务。请确认 SPT 正在运行。';
  }
  function scheduleRetry() {
    if (net.timer || net.checking) return;
    net.timer = setTimeout(retryConnect,net.delay);
    net.delay = nextDelay(net.delay);
  }
  async function retryConnect() {
    clearTimeout(net.timer); net.timer = 0; net.checking = true;
    let ok = false;
    try { ok = (await fetch(apiURL('/api/health'),{ cache:'no-store' })).ok; } catch { ok = false; }
    net.checking = false;
    if (ok) markOnline(); else scheduleRetry();
  }
  function markOffline() {
    if (net.online) { net.online = false; net.delay = 5000; document.documentElement.dataset.online = 'false'; updateShell(); }
    renderOffline();
    scheduleRetry();
  }
  function markOnline() {
    net.readAt = new Date(); net.streamErrors = 0;
    if (net.online) return;
    net.online = true; net.delay = 5000; clearTimeout(net.timer); net.timer = 0;
    document.documentElement.dataset.online = 'true';
    renderOffline(); updateShell();
    notice('已重新连上',{ tone:'success', key:'connection' });
    if (state.eventSource?.readyState === 2) { state.eventSource.close(); state.eventSource = null; }
    if (state.health) { refreshAfterIndex(); connectEvents(); } else connect();
  }
  // The event stream failing twice in a row: check the service before calling it offline.
  async function verifyConnection() {
    if (!net.online || net.checking) return;
    try { await fetch(apiURL('/api/health'),{ cache:'no-store' }); net.streamErrors = 0; } catch { markOffline(); }
  }
  async function manualRetry(button) {
    if (net.checking) return;
    net.delay = 5000;
    if (button) { button.disabled = true; button.textContent = '正在重试'; }
    await retryConnect();
    if (button?.isConnected) { button.disabled = false; button.textContent = '重试'; }
    if (!net.online) notice('还是连不上，稍后会自动再试。',{ tone:'warn', key:'connection' });
  }
  async function api(path,options={}) {
    let response;
    try { response = await fetch(apiURL(path),{cache:'no-store',...options}); }
    catch(error) {
      if(error.name==='AbortError') throw error;
      markOffline();
      throw new Error('连不上 SPT 本机服务。');
    }
    markOnline();
    let data;
    try { data=await response.json(); } catch { throw new Error('本地服务返回了无法识别的数据。'); }
    if(!response.ok){const error=new Error(data.error || `请求失败（${response.status}）`);error.status=response.status;error.data=data;throw error;}
    return data;
  }
  // Writes still try while offline (the service may be back before the retry timer notices); the message says nothing changed.
  async function postJSON(path,body) {
    try { return await api(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}); }
    catch(error) { if(!net.online&&!error.status&&error.name!=='AbortError')throw new Error('连不上 SPT 本机服务，刚才的操作没有生效。连上后再试一次。');throw error; }
  }

  // -- listbox controls (the hidden input keeps the old id) ---------------------------------
  function listbox(config) { return Listbox ? Listbox.listboxHTML(config) : ''; }
  function setControl(id,value) {
    const input=document.getElementById(id);if(!input)return;
    if(Listbox&&input.closest('[data-listbox]'))Listbox.setValue(id,value);else input.value=value;
  }
  function focusControl(id) { (document.getElementById(`${id}-button`)||document.getElementById(id))?.focus({preventScroll:true}); }
  function disableControl(id,disabled) { const target=document.getElementById(`${id}-button`)||document.getElementById(id);if(target)target.disabled=disabled; }
  function hideControl(id,hidden) { const input=document.getElementById(id);const root=input?.closest('[data-listbox]')||input;if(root)root.hidden=hidden; }

  function updateShell() {
    $('#connection-text').textContent=!net.online?'连不上本机服务':state.health?'本地资料已连接':'本地服务未连接';
    $('#source-path').textContent=state.health?.workspace_path||'SPT / 工作区';
    $('#source-path').title=state.health?.workspace_path||'';
    $('#sync-time').textContent=state.health?.indexed_at?`作品索引 ${readableTime(state.health.indexed_at)}`:'';
    // Tool routes belong to 发布 (数据导入 to 数据), the Skills list to 设置. Only the sidebar links: <html> carries data-route too.
    // 数据, 情报 and 发布 are listed once the snapshot shows something behind them; their pages still open by address.
    const current=navRoute(state.route,state.tool,state.kind==='skill'), hidden=hiddenRoutes(state.dashboard,state.health);
    $$('.primary-nav a[data-route]').forEach((link)=>{
      const selected=link.dataset.route===current;
      link.hidden=hidden.includes(link.dataset.route);
      link.classList.toggle('selected',selected);
      if(selected)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');
    });
    const refreshButton=$('.toolbar-refresh');
    if(refreshButton){refreshButton.disabled=state.reindexing;refreshButton.querySelector('span:last-child').textContent=state.reindexing?'正在刷新':'刷新';}
    if(state.route==='works')renderFolders();
  }

  // -- 发布 and its tools: one persistent iframe in #tool-host -------------------------------
  function toolURL(name='studio',draftID='',prefill={}) {
    if(!TOOL_NAMES[name]||!legacyURL(name))return '';
    const extra=PREFILL_KEYS.filter((key)=>prefill[key]).map((key)=>`&${key}=${encodeURIComponent(prefill[key])}`).join('');
    return `#tools?name=${name}${draftID?`&draft_id=${encodeURIComponent(draftID)}`:''}${extra}`;
  }
  // Sideways-scrolling tab strips: keep the selected tab in view and fade the edge that hides more tabs.
  function stripEdges(strip) {
    if(!strip)return;
    const update=()=>{const max=strip.scrollWidth-strip.clientWidth;strip.classList.toggle('more-start',strip.scrollLeft>2);strip.classList.toggle('more-end',max>2&&strip.scrollLeft<max-2);};
    if(!strip.dataset.edges){strip.dataset.edges='1';strip.addEventListener('scroll',update,{passive:true});}
    const selected=strip.querySelector('[aria-current="page"],[aria-selected="true"]');
    if(selected&&strip.scrollWidth>strip.clientWidth){const box=strip.getBoundingClientRect(), item=selected.getBoundingClientRect();strip.scrollLeft+=item.left-box.left-(box.width-item.width)/2;}
    update();
  }
  const shareMode=()=>isShare(state.health);
  // The tab strip, with the ⋯ menu (the editing tools) after it; the strip scrolls, the menu stays put.
  function subtabsHTML(current) {
    const tabs=publishTabs(current).filter((key)=>!key||toolURL(key));
    if(tabs.length<2)return '';
    const links=tabs.map((key)=>{
      const selected=key===current, href=key?toolURL(key,selected?state.toolDraft:''):ENTRIES_HASH;
      return `<a class="subtab${selected?' selected':''}" href="${esc(href)}" data-subtab="${esc(key||'entries')}"${selected?' aria-current="page"':''}>${esc(key?TOOL_NAMES[key]:ENTRIES_NAME)}</a>`;
    }).join('');
    const more=publishMore(shareMode()).filter((key)=>toolURL(key));
    const menu=more.length?`<details class="export-menu more-menu publish-more"><summary class="icon-button more-button" aria-label="更多发布工具" title="更多发布工具">${icon('dots-three')}</summary><div class="export-options">${more.map((key)=>`<a class="export-option" href="${esc(toolURL(key))}" data-subtab="${esc(key)}"${key===current?' aria-current="page"':''}>${esc(TOOL_NAMES[key])}</a>`).join('')}</div></details>`:'';
    return `<div class="subtabs-row"><nav class="subtabs" aria-label="发布">${links}</nav>${menu}</div>`;
  }
  function toolViewHTML(name) {
    // 导入数据 sits under 数据: a two-tab strip leads back to it instead of the 发布 tabs (a shared copy keeps 数据 alone: a way back).
    const data=DATA_TOOLS.includes(name);
    const nav=data&&shareMode()?`<a class="page-back" href="#analytics" aria-label="返回数据">${icon('arrow-left')}<span>数据</span></a>`
      :data?`<nav class="subtabs" aria-label="数据"><a class="subtab" href="#analytics" data-subtab="analytics">数据</a><a class="subtab selected" href="${esc(toolURL(name))}" data-subtab="${esc(name)}" aria-current="page">${esc(TOOL_NAMES[name])}</a></nav>`
      :subtabsHTML(name);
    return `<h1 class="sr-only" tabindex="-1">${esc(TOOL_NAMES[name])}</h1>${nav}`;
  }
  function renderTools() {
    const name=TOOL_NAMES[state.tool]?state.tool:'studio';
    const host=$('#tool-host');
    const legacy=legacyURL(name,state.toolDraft||'',state.toolPrefill);
    $('#view').innerHTML=toolViewHTML(name);
    stripEdges($('#view .subtabs'));
    if(!legacy||!host){
      if(host)host.hidden=true;
      // 数据导入 belongs to 数据: its way back goes there, not to 发布.
      const data=DATA_TOOLS.includes(name);
      $('#view').insertAdjacentHTML('beforeend',`<div class="empty-state">${icon('desktop')}<h2>${data?`${esc(TOOL_NAMES[name])}要在 SPT 应用里打开`:'发布工具要在 SPT 应用里打开'}</h2><a class="button primary" href="${data?'#analytics':'#publish'}">${data?'回到数据':'回到发布'}</a></div>`);
      return;
    }
    const target=new URL(legacy,location.origin);
    target.searchParams.set('embed','1');
    host.hidden=false;
    if(!frameEl){
      frameEl=document.createElement('iframe');
      frameEl.id='tool-frame';frameEl.className='tool-frame';frameEl.title=TOOL_NAMES[name];
      frameEl.addEventListener('load',()=>{frameEl.hidden=false;$('.tool-loading',host)?.remove();syncFrameTheme();});
      loadToolFrame(target.href);
      host.append(frameEl);
      return;
    }
    frameEl.title=TOOL_NAMES[name];
    // 同一个页面、同一份草稿：只换 hash，不重新载入。
    try{
      const current=new URL(frameEl.contentWindow.location.href);
      const same=(key)=>(current.searchParams.get(key)||'')===(target.searchParams.get(key)||'');
      if(current.origin===location.origin&&current.pathname===target.pathname&&same('draft_id')&&PREFILL_KEYS.every(same)){
        // replace(): switching tabs must not leave an extra Back step inside the frame.
        if(current.hash!==target.hash){const next=new URL(current.href);next.hash=target.hash;frameEl.contentWindow.location.replace(next.href);}
        return;
      }
    }catch{/* 不同源时直接重新载入 */}
    loadToolFrame(target.href);
  }
  function loadToolFrame(src) {
    const host=$('#tool-host');
    if(!$('.tool-loading',host))host.insertAdjacentHTML('afterbegin','<div class="tool-loading" role="status"><span class="spinner" aria-hidden="true"></span>正在打开…</div>');
    frameEl.hidden=true;
    try{if(frameEl.getAttribute('src')&&frameEl.contentWindow){frameEl.contentWindow.location.replace(src);return;}}catch{/* not loaded yet */}
    frameEl.src=src;
  }
  // 原生桥的回调只送到主页面：转给嵌入的工具页。
  function forwardToTool(method,...args) {
    try{const target=frameEl?.contentWindow;if(target&&typeof target[method]==='function'){target[method](...args);return true;}}catch{/* 跨源或已卸载 */}
    return false;
  }

  // -- 资产库 ------------------------------------------------------------------------
  // Write a region only when its markup changed: background refreshes (a note saved, the index rebuilt)
  // then leave cards, focus, an open menu and an expanded group alone.
  function paint(container,html) {
    if(!container||container.sptPainted===html)return false;
    container.sptPainted=html;
    rerender(container,html);
    return true;
  }
  // A role=status region re-announces every write: only write when the text says something new.
  function setStatus(element,text) { if(element&&element.textContent!==text)element.textContent=text; }
  // While searching, the tabs count matches in every kind (state.matchCounts), so hits elsewhere show up.
  function kindCounts() {
    if(state.query.trim()&&state.matchCounts)return state.matchCounts.counts;
    const kinds=state.libraryIndex?.kinds||{};
    return {work:state.allWorks.length,...Object.fromEntries(Object.entries(kinds).map(([key,value])=>[key,value.count]))};
  }
  function libraryReady() { return !!library&&state.health?.capabilities?.library===true; }
  function renderLibraryChrome() {
    if(!library)return;
    const slot=$('#kind-slot'), results=$('#work-results');
    if(!libraryReady()){
      paint(slot,state.health?'<p class="inline-message library-upgrade">提示词、素材、记录和 Skills 暂时用不了：后台服务还是旧版本。重启电脑后就能用（只退出 SPT 不够，后台服务不会跟着关）。</p>':'');
      paint($('#export-slot'),'');
      if(results){results.removeAttribute('role');results.removeAttribute('aria-labelledby');}
      return;
    }
    const matching=!!(state.query.trim()&&state.matchCounts), skills=state.kind==='skill';
    // The Skills page (from 设置) shows one kind: no tab strip, so the list is not a tab panel either.
    if(skills)paint(slot,'');
    else if(paint(slot,library.kindTabsHTML(state.kind,kindCounts(),deps,'work-results',{matching})))stripEdges(slot.querySelector('.kind-tabs')||slot);
    if(results&&skills){results.removeAttribute('role');results.removeAttribute('aria-labelledby');}
    else if(results){results.setAttribute('role','tabpanel');results.setAttribute('aria-labelledby',`kind-tab-${state.kind}`);}
    paint($('#export-slot'),library.exportMenuHTML(state.kind,deps,{guide:state.health?.capabilities?.guide===true,clients:clientGroupsSupported()&&!skills}));
    hideControl('status-filter',state.kind!=='work');
  }
  // Filter chips (aria-pressed). First row: the clients, in two clusters (自己 / 客户); it stays away when 自家 is the only
  // one. Second row: the 专业 of the chosen client (only when it spans more than one), or, for the other kinds, the groups.
  function renderFolders() {
    const nav=$('#category-nav');if(!nav)return;
    const pool=clientPool(), groups=clientChipGroups();
    const clientRow=groups.length?library.clientChipsHTML(groups,state.client,pool.total,deps):'';
    const scoped=state.client&&pool.tagged?asArray(pool.list).filter((entry)=>pool.keyOf(entry)===state.client):asArray(pool.list);
    if(state.kind!=='work'&&libraryReady()){
      const entry=state.libraryIndex?.kinds?.[state.kind];
      let sections=entry?.sections, total=entry?.count||0;
      // Under a chosen client the groups count that client's items only.
      if(state.client&&pool.tagged){const counts=countBy(scoped,(item)=>item.section||'未分类');sections=asArray(entry?.sections).filter((section)=>counts[section.name]).map((section)=>({name:section.name,count:counts[section.name]}));total=scoped.length;}
      // The Skills page lists its sources as foldable groups (and 设置 counts them): no chip row repeating them.
      const sectionRow=state.kind!=='skill'&&library.showsGroups(sections,state.section)?`<div class="chip-row section-chips">${library.sectionNavHTML(sections,state.section,total,deps)}</div>`:'';
      nav.hidden=state.kind==='skill'||(!clientRow&&!sectionRow);
      paint(nav,nav.hidden?'':clientRow+sectionRow);
      return;
    }
    const categories=countBy(scoped,(work)=>work.category||'未分类');
    const names=Object.keys(categories);
    const showCategories=state.client?names.length>1||!!state.category:!clientRow&&(names.length>1||!!state.category);
    const chip=(value,label,count,chosen)=>`<button type="button" class="category-link${chosen?' selected':''}" data-category="${esc(value)}" aria-pressed="${chosen}">${label}<span class="nav-count">${count}</span></button>`;
    const categoryRow=showCategories?`<div class="chip-row category-chips" role="group" aria-label="专业">${chip('',`${icon('folder-open')}全部`,scoped.length,!state.category)}${names.map((name)=>chip(name,esc(name),categories[name],state.category===name)).join('')}</div>`:'';
    nav.hidden=!clientRow&&!categoryRow;
    paint(nav,nav.hidden?'':clientRow+categoryRow);
  }
  function setLayoutButtons() {
    $('#grid-view').setAttribute('aria-pressed',String(state.layout==='grid'));
    $('#list-view').setAttribute('aria-pressed',String(state.layout==='list'));
    $('#grid-view').classList.toggle('selected',state.layout==='grid');
    $('#list-view').classList.toggle('selected',state.layout==='list');
    // 显示 (cover shape) only matters for cards with pictures: works and 素材, in the grid.
    const display=$('#display-slot');
    if(display)display.hidden=state.layout==='list'||!(state.kind==='work'||state.kind==='material'||!libraryReady());
    $$('[data-cover-mode]').forEach((button)=>button.setAttribute('aria-pressed',String(button.dataset.coverMode===state.cover)));
  }
  // The count next to the search: always announced, only shown once something narrows the list.
  function showCount(count,unit,narrowed) {
    const status=$('#result-count');
    setStatus(status,`${state.query.trim()?'找到 ':''}${count} ${unit}`);
    status?.classList.toggle('sr-only',!narrowed);
  }
  function elsewhere() {
    if(!state.query.trim()||!state.matchCounts||!library||state.kind==='skill')return [];
    return library.KINDS.map((kind)=>({key:kind.key,label:kind.label,count:state.matchCounts.counts[kind.key]||0}));
  }
  // While loading, whatever this kind already shows stays until the new list arrives (no spinner, no 读取中);
  // only a first load shows the spinner, and a quiet (background) load never touches the page.
  function keepWhileLoading(results,view,quiet) {
    if(quiet||results.dataset.view===view)return true;
    setStatus($('#result-count'),'读取中');
    return false;
  }
  function renderItems() {
    renderLibraryChrome();
    const label=library.KIND_LABEL[state.kind], query=state.query.trim();
    setLayoutButtons();
    const results=$('#work-results');
    results.dataset.cover=state.cover;
    results.setAttribute('aria-busy',String(state.itemsLoading));
    $('#library-message').hidden=true;
    if(state.itemsLoading){if(!keepWhileLoading(results,state.kind,state.itemsQuiet))paint(results,`<div class="empty-state"><span class="spinner" aria-hidden="true"></span><p>正在读取${esc(label)}</p></div>`);return;}
    results.dataset.view=state.kind;
    // The client filter narrows here, not on the server: the chips keep counting the whole kind.
    const tagged=itemsTagged(state.items), byClient=tagged&&!!state.client;
    const items=byClient?state.items.filter((item)=>itemClient(item)===state.client):state.items;
    const filtered=!!(query||state.section||byClient);
    showCount(items.length,'条',filtered);
    // 全部 with nothing typed or chosen: the overview, one foldable block per client (通用 under 自己).
    const overview=tagged&&state.kind!=='skill'&&!state.client&&!query&&!state.section&&showsClientRow();
    if(state.itemsError&&!state.items.length)paint(results,`<div class="empty-state">${icon('warning-circle')}<h2>${esc(label)}没能读取</h2><p class="error-detail">${esc(state.itemsError)}</p><button type="button" class="button primary" data-action="retry">重新连接</button></div>`);
    else if(!items.length)paint(results,library.emptyHTML(state.kind,filtered,deps,query,elsewhere()));
    else paint(results,library.itemsHTML(items,state.layout,deps,{grouped:state.kind==='skill'&&!query&&!state.section,open:state.openGroups,closed:state.closedGroups,clients:state.clients,groups:clientGroups(),byClient:overview?{limit:OVERVIEW_LIMIT}:null}));
  }
  // The Skills page before the service answers, or on a service too old to list skills (the slot says why).
  function renderSkillsWaiting() {
    renderLibraryChrome();
    const results=$('#work-results'), offline=!state.health&&!!state.error;
    results.setAttribute('aria-busy',String(!state.health&&!offline));
    const count=$('#result-count');setStatus(count,state.health||offline?'':'读取中');count?.classList.add('sr-only');
    if(offline)paint(results,`<div class="empty-state">${icon('warning-circle')}<h2>Skills 没能读取</h2><p class="error-detail">${esc(state.error)}</p><button type="button" class="button primary" data-action="retry">重新连接</button></div>`);
    else paint(results,state.health?'':'<div class="empty-state"><span class="spinner" aria-hidden="true"></span><p>正在读取 Skills</p></div>');
  }
  function renderWorks() {
    if (state.route !== 'works' || !$('#work-results')) return;
    if (state.kind === 'skill' && !libraryReady()) { renderSkillsWaiting(); return; }
    if (libraryReady() && state.kind !== 'work') { renderItems(); return; }
    renderLibraryChrome();
    const results = $('#work-results'), query = state.query.trim(), filtered = !!(query || state.status || state.category || state.client);
    results.setAttribute('aria-busy', String(state.loading));
    results.dataset.cover = state.cover;
    setLayoutButtons();
    const message = $('#library-message');
    message.hidden = !state.error || !state.works.length;
    if (!message.hidden) { message.className = 'inline-message error'; paint(message, `${icon('warning-circle')}<span>${esc(state.error)} 当前保留上次结果。</span><button type="button" class="button small" data-action="retry">重试</button>`); }
    if (state.loading) { if (!keepWhileLoading(results, 'work', state.worksQuiet)) paint(results, '<div class="empty-state"><span class="spinner" aria-hidden="true"></span><p>正在读取工作区</p></div>'); return; }
    results.dataset.view = 'work';
    // The client narrows here, not on the server (the list is already filtered by 专业, status and the search).
    const works = state.client ? state.works.filter((work) => workClient(work) === state.client) : state.works;
    showCount(works.length, '件', filtered);
    // 全部 with nothing typed or chosen (a status may be on): the overview, one foldable block per client.
    const overview = !!library && !state.client && !query && !state.category && showsClientRow();
    if (state.error && !state.works.length) {
      paint(results, `<div class="empty-state">${icon('warning-circle')}<h2>工作区没能读取</h2><p class="error-detail">${esc(state.error)}</p><button type="button" class="button primary" data-action="retry">重新连接</button></div>`);
    } else if (!works.length) {
      paint(results, library ? library.emptyHTML('work', filtered, deps, query, elsewhere()) : `<div class="empty-state">${icon('folder-open')}<h2>${filtered ? '没有符合筛选的作品' : '还没有作品'}</h2>${filtered ? '<button type="button" class="button primary" data-action="clear-filters">清除筛选</button>' : ''}</div>`);
    } else if (overview) {
      paint(results, library.clientBlocksHTML(library.groupByClient(works, state.clients, { limit: OVERVIEW_LIMIT, groups: clientGroups() }), worksBodyHTML, deps, { closed: state.closedGroups }));
    } else {
      paint(results, worksBodyHTML(works));
    }
  }
  // The grid, or the table in the list layout; the overview draws one per block.
  function worksBodyHTML(works) {
    if (state.layout === 'list') return `<div class="works-table-wrap"><table class="works-table"><thead><tr><th scope="col">作品</th><th scope="col">客户</th><th scope="col">日期</th><th scope="col">状态</th></tr></thead><tbody>${works.map((work) => listRowHTML(work, clientTag(work.client))).join('')}</tbody></table></div>`;
    return `<div class="works-grid">${works.map((work) => cardHTML(work, clientTag(work.client))).join('')}</div>`;
  }
  // quiet: a background refresh (index_updated); it keeps the page as it is until the new list arrives.
  async function loadWorks({refreshAll=false,quiet=false}={}) {
    const requestId=++state.requestId;
    state.requestController?.abort();
    state.requestController=new AbortController();
    state.loading=true;state.error='';state.worksQuiet=quiet;
    if(state.route==='works')renderWorks();
    const query=new URLSearchParams();
    if(state.route==='works'){
      if(state.category)query.set('category',state.category);
      if(state.status)query.set('status',state.status);
      if(state.query.trim())query.set('q',state.query.trim());
    }
    try{
      const data=await api(`/api/works?${query}`,{signal:state.requestController.signal});
      if(requestId!==state.requestId)return;
      const works=Array.isArray(data)?data:data.works;
      if(!Array.isArray(works))throw new Error('作品接口格式不匹配。');
      state.works=works;
      if(!query.size)state.allWorks=works;
      else if(refreshAll){
        const all=await api('/api/works',{signal:state.requestController.signal});
        if(requestId!==state.requestId)return;
        state.allWorks=Array.isArray(all)?all:asArray(all.works);
      }
      syncClients();
    }catch(error){if(error.name==='AbortError'||requestId!==state.requestId)return;state.error=error.message;}
    finally{if(requestId===state.requestId){state.loading=false;updateShell();renderCurrent();}}
  }
  async function loadLibraryIndex() {
    try{state.libraryIndex=await api('/api/library');state.libraryIndexFailed=false;}
    catch{state.libraryIndex=null;state.libraryIndexFailed=true;}
    if(state.route==='works'){renderLibraryChrome();renderFolders();}
    else if(state.route==='settings')paint($('#settings-skills-panel'),skillsPanelHTML());
  }
  async function loadItems({quiet=false}={}) {
    if(state.kind==='work'||!library)return loadWorks({quiet});
    const requestId=++state.itemRequestId;
    state.itemController?.abort();
    state.itemController=new AbortController();
    state.itemsLoading=true;state.itemsError='';state.itemsQuiet=quiet;
    if(state.route==='works')renderItems();
    const kind=state.kind, query=new URLSearchParams({kind});
    if(state.section)query.set('section',state.section);
    if(state.query.trim())query.set('q',state.query.trim());
    try{
      const data=await api(`/api/items?${query}`,{signal:state.itemController.signal});
      if(requestId!==state.itemRequestId)return;
      if(!Array.isArray(data.items))throw new Error('资产接口格式不匹配。');
      state.items=data.items;
      // The whole kind (no group, no search) is what the client chips count.
      if(!state.section&&!state.query.trim())state.allItems[kind]=data.items;
    }catch(error){if(error.name==='AbortError'||requestId!==state.itemRequestId)return;state.itemsError=error.message;}
    finally{if(requestId===state.itemRequestId){state.itemsLoading=false;if(state.route==='works'&&$('#work-results')){renderFolders();renderItems();}}}
  }
  function loadCurrentLibrary(options={}) {
    if(state.kind==='skill'&&!libraryReady()){renderWorks();return Promise.resolve();}
    return state.kind==='work'||!libraryReady()?loadWorks(options):loadItems(options);
  }
  // Which kind the page shows: the 资产库 tab (state.libraryKind) or 'skill' for the Skills page. The Skills page
  // keeps its own search: the library's query waits in state.libraryQuery for the way back. True when it changed.
  function useKind(kind) {
    if(kind===state.kind)return false;
    if(kind==='skill'){state.libraryQuery=state.query;state.query='';}
    else if(state.kind==='skill'){state.query=state.libraryQuery;state.libraryQuery='';}
    state.kind=kind;state.section='';state.items=[];state.itemsError='';state.matchCounts=null;
    return true;
  }
  // One search across the whole library: works plus every item kind (notes too). category/status narrow works only.
  async function searchAssets(query,signal,{category='',status=''}={}) {
    const works=new URLSearchParams({q:query});
    if(category)works.set('category',category);
    if(status)works.set('status',status);
    const [workData,itemData]=await Promise.all([api(`/api/works?${works}`,{signal}),api(`/api/items?${new URLSearchParams({q:query})}`,{signal})]);
    return {works:Array.isArray(workData)?workData:asArray(workData?.works),items:asArray(itemData?.items)};
  }
  // Match counts per kind for the tabs while a search is on; the newest request wins, stale ones are cancelled.
  async function loadMatchCounts() {
    const query=state.query.trim();
    if(!query||!libraryReady()||state.kind==='skill'){
      state.countController?.abort();
      if(state.matchCounts){state.matchCounts=null;renderWorks();}
      return;
    }
    const key=JSON.stringify([query,state.category,state.status,state.indexStamp]);
    if(state.matchCounts?.key===key)return;
    const requestId=++state.countRequestId;
    state.countController?.abort();
    state.countController=new AbortController();
    try{
      const results=await searchAssets(query,state.countController.signal,{category:state.category,status:state.status});
      if(requestId!==state.countRequestId)return;
      state.matchCounts={key,counts:library.countKinds(results)};
    }catch(error){if(error.name==='AbortError'||requestId!==state.countRequestId)return;state.matchCounts=null;}
    renderWorks();
  }
  function selectKind(kind) {
    if(!library?.isKind(kind)||kind===state.kind||!libraryReady())return;
    state.kind=kind;state.libraryKind=kind;state.section='';state.items=[];state.itemsError='';
    savePreference('kind',kind);
    renderFolders();loadCurrentLibrary();
    $(`[data-kind="${kind}"]`)?.focus({preventScroll:true});
  }
  function selectSection(section) { state.section=section;renderFolders();loadItems(); }
  async function loadDashboard() {
    const request=++state.dashboardRequestId;
    state.dashboardLoading=true;state.dashboardError='';
    if(!state.dashboard)renderCurrent();
    try{
      const data=await api('/api/dashboard');
      if(request!==state.dashboardRequestId)return;
      if(!Array.isArray(data.accounts)||!Array.isArray(data.posts))throw new Error('运营资料格式不匹配。');
      state.dashboard=data;
    }catch(error){if(request===state.dashboardRequestId)state.dashboardError=error.message;}
    finally{if(request===state.dashboardRequestId){state.dashboardLoading=false;renderCurrent();}}
  }
  // 读数据: ask the server for a read, wait while the Mac app reads 小红书 with its own login, then show what was recorded.
  async function readMetrics() {
    if(state.metricsReading)return;
    state.metricsReading=true;renderCurrent();
    try{
      const {run}=await postJSON('/api/metrics/capture/request',{reason:'手动'});
      const end=Date.now()+6*60000;
      let status;
      do{await new Promise((resolve)=>setTimeout(resolve,2000));status=await api('/api/metrics/capture');}
      while(status.current&&status.current.id===run.id&&Date.now()<end);
      const last=status.last&&status.last.id===run.id?status.last:null;
      if(!last)notice('还在读，读完数据页会自己更新。');
      else notice(last.message||'读完了',{tone:last.state==='done'?'success':'warn'});
      await loadDashboard();
    }catch(error){notice(error.message,{tone:'error'});}
    finally{state.metricsReading=false;renderCurrent();}
  }
  async function connect() {
    state.loading=true;state.error='';
    try{
      const health=await api('/api/health');
      if(health.app!=='spt')throw new Error('当前服务没有接入 SPT 资产库。');
      state.health=health;syncClients();
      // Items load alongside works: a page opened on another kind (or the Skills page) shows its spinner, not 还没有….
      await Promise.allSettled([loadWorks({refreshAll:true}),loadDashboard(),libraryReady()?loadLibraryIndex():null,loadNotes(),state.kind!=='work'&&libraryReady()?loadItems():null]);
      connectEvents();
    }catch(error){
      state.health=null;state.eventSource?.close();state.eventSource=null;
      state.error=error.message;state.dashboardError=error.message;state.loading=false;state.dashboardLoading=false;
      updateShell();renderCurrent();
    }
  }
  function connectEvents() {
    if(state.eventSource||!window.EventSource)return;
    const events=new EventSource(apiURL('/api/events'));
    state.eventSource=events;
    events.addEventListener('index_updated',refreshAfterIndex);
    events.onmessage=(event)=>{try{if(JSON.parse(event.data).type==='index_updated')refreshAfterIndex();}catch{/* Other events do not change current UI state. */}};
    events.onerror=()=>{$('#connection-text').textContent='作品更新正在重连';net.streamErrors+=1;if(net.streamErrors>=2)verifyConnection();};
    events.onopen=()=>{$('#connection-text').textContent='本地资料已连接';markOnline();};
  }
  async function refreshAfterIndex() {
    if(state.reindexing)return;
    try{state.health=await api('/api/health');}catch{/* Keep source snapshots until a confirmed response. */}
    // Quiet: an index update (e.g. a saved note) must not flash the library or announce 读取中.
    state.indexStamp+=1;state.allItems={};
    // An open ⌘K keeps its list and swaps in fresh results when they arrive.
    const paletteQuery=palette?.open?$('#palette-input').value.trim():'';
    if(paletteQuery&&pal.results?.query===paletteQuery)runPaletteSearch(paletteQuery);else pal.results=null;
    await Promise.allSettled([loadWorks({refreshAll:true,quiet:true}),loadDashboard(),libraryReady()?loadLibraryIndex():null,loadNotes()]);
    if(state.kind!=='work'&&libraryReady())loadItems({quiet:true});
    loadMatchCounts();
  }
  async function refresh() {
    if(!dashboard){location.reload();return;}
    if(!state.health){await connect();return;}
    await reindex();
  }
  async function reindex() {
    if(!state.health||state.reindexing)return;
    state.reindexing=true;updateShell();
    try{
      const result=await api('/api/reindex',{method:'POST'});
      state.health=await api('/api/health');
      state.indexStamp+=1;pal.results=null;state.allItems={};
      await Promise.allSettled([loadWorks({refreshAll:true,quiet:true}),loadDashboard(),libraryReady()?loadLibraryIndex():null]);
      if(state.kind!=='work'&&libraryReady())await loadItems({quiet:true});
      loadMatchCounts();
      if(asArray(result.issues).length)notice(`已刷新，${result.issues.length} 个文件未能读取`,{tone:'warn',action:{label:'查看',run:()=>{go('#settings');requestAnimationFrame(()=>{const row=$('#settings-issues');if(!row)return;row.scrollIntoView({block:'start'});row.focus({preventScroll:true});});}}});
      else if(state.dashboardError)notice(state.dashboardError,{tone:'warn'});
      else notice('已刷新',{tone:'success'});
    }catch(error){notice(error.message,{tone:'error'});}
    finally{state.reindexing=false;updateShell();}
  }

  // -- 便签 ----------------------------------------------------------------------------
  function notesReady() { return !!notesUI&&state.health?.capabilities?.notes===true; }
  async function loadNotes() {
    if(!notesReady())return;
    const request=++state.notesRequestId;
    state.notesLoading=true;
    try{
      const data=await api('/api/notes');
      if(request!==state.notesRequestId)return;
      if(!Array.isArray(data.ropes))throw new Error('便签格式不匹配。');
      state.notes=data;state.notesError='';
    }catch(error){if(request===state.notesRequestId)state.notesError=error.message;}
    finally{
      if(request===state.notesRequestId){
        state.notesLoading=false;
        // 正在编辑或拖动时不重画，免得打断。
        if(!state.dragging&&!noteDialog.open){
          const rail=$('.notes-rail');
          if(state.route==='notes')renderNotes();
          else if(state.route==='desk'&&rail?.parentElement)keepFocus(rail.parentElement,()=>{rail.outerHTML=deps.sideRail();});
        }
      }
    }
  }
  function renderNotes() {
    const view=$('#view');
    if(!notesUI){view.innerHTML='<div class="empty-state"><h1 tabindex="-1">便签没有载入</h1><p>重新载入页面后就能用。</p></div>';return;}
    if(state.health&&!notesReady()){view.innerHTML='<div class="empty-state"><h1 tabindex="-1">便签需要重启本地服务</h1><p>重启电脑后再打开 SPT，或在「终端」运行：</p><pre class="code-block">pkill -f &#39;app/server.py --port 8766&#39;</pre></div>';return;}
    const typing=document.activeElement?.id==='notes-search'?document.activeElement:null;
    const caret=typing?[typing.selectionStart,typing.selectionEnd]:null;
    const today=localDay();
    keepFocus(view,()=>{view.innerHTML=notesUI.pageHTML(state.notes,state.notesLoading||!state.health,state.notesError,deps,{mode:state.notesView,month:state.notesMonth||today.slice(0,7),today,query:state.notesQuery,posts:scheduledPosts()});});
    if(state.notesView==='calendar')loadScheduled();
    const search=$('#notes-search');
    if(search){search.value=state.notesQuery;filterNotes();if(caret){search.focus({preventScroll:true});search.setSelectionRange(caret[0],caret[1]);}}
    if(state.lastNote){$(`.note[data-note="${CSS.escape(state.lastNote)}"]`)?.classList.add('just-hung');state.lastNote='';}
  }
  // 月历里只读显示「发布日历」排好的发布：读旧版发布工具的 GET /api/state（同源，不经过 apiURL）。
  // 没有旧版发布、没排、读不到：月历和原来一模一样，不报错。10 秒内不重复读；工具页存过东西后作废重读。
  const sched={posts:[],at:0,loading:false};
  function scheduleReady() { return !!notesUI?.scheduledPosts&&state.dashboard?.capabilities?.legacy_publishing===true; }
  function scheduledPosts() { return scheduleReady()?sched.posts:[]; }
  async function loadScheduled(force=false) {
    if(!scheduleReady()||sched.loading||(!force&&Date.now()-sched.at<10000))return;
    sched.loading=true;sched.at=Date.now();
    let posts=[];
    try{
      const response=await fetch('/api/state',{cache:'no-store',headers:{Accept:'application/json'}});
      if(response.ok)posts=notesUI.scheduledPosts(await response.json(),platformName);
    }catch{/* No posts: the calendar shows notes only. */}
    finally{sched.loading=false;}
    if(JSON.stringify(posts)===JSON.stringify(sched.posts))return;
    sched.posts=posts;
    if(state.route==='notes'&&state.notesView==='calendar'&&!state.dragging&&!noteDialog.open)renderNotes();
  }
  // Search filters the page in place (no re-render while typing).
  function noteText(note) { return `${note?.text||''} ${note?.rope||''}`.toLowerCase(); }
  function filterNotes() {
    const view=$('#view'), query=state.notesQuery.trim().toLowerCase();
    const matches=(element)=>{const note=findNote(element.dataset.note,element.dataset.rope);return (note?noteText(note):`${element.textContent} ${element.dataset.rope||''}`.toLowerCase()).includes(query);};
    $$('.note[data-note]',view).forEach((element)=>{element.hidden=!!query&&!matches(element);});
    $$('.note-group',view).forEach((group)=>{group.hidden=!!query&&!$('.note[data-note]:not([hidden])',group);});
    $$('.cal-chip[data-note]',view).forEach((chip)=>chip.classList.toggle('is-dim',!!query&&!matches(chip)));
    const count=$('#notes-count');if(!count)return;
    if(!query){count.textContent='';return;}
    const found=asArray(state.notes?.ropes).flatMap((rope)=>asArray(rope.notes)).filter((note)=>noteText(note).includes(query)).length;
    count.textContent=found?`找到 ${found} 张`:`没有找到“${state.notesQuery.trim()}”`;
  }
  function localDay(date=new Date()) { return `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`; }
  function dayLabel(value) { const match=String(value||'').match(/^\d{4}-(\d{2})-(\d{2})/);return match?`${Number(match[1])}月${Number(match[2])}日`:String(value||''); }
  function setNotesView(value) {
    state.notesView=value==='calendar'?'calendar':'board';
    savePreference('notesView',state.notesView);
    if(state.route==='notes')renderNotes();
  }
  function shiftNotesMonth(step) {
    const month=state.notesMonth||localDay().slice(0,7);
    state.notesMonth=step?notesUI.shiftMonth(month,step):localDay().slice(0,7);
    renderNotes();
  }
  function rememberNoteReturn() { state.noteReturnFocus=returnTarget();state.noteReturnKey=keyOf(state.noteReturnFocus); }
  function openDay(date,focusId='') {
    if(!noteDialog.open)rememberNoteReturn();
    state.dayOpen=date;state.noteDay='';noteSnapshot=null;state.noteConflict=null;
    $('#note-dialog-content').innerHTML=notesUI.dayHTML(state.notes,date,deps,scheduledPosts());
    openModal(noteDialog);
    const sheet=$('#note-dialog-content');
    (focusId&&$(`[data-note="${CSS.escape(focusId)}"]`,sheet)||$('.day-note',sheet)||$('button',sheet))?.focus();
  }
  function findNote(id,rope) {
    return asArray(state.notes?.ropes).flatMap((item)=>asArray(item.notes)).find((note)=>note.id===id&&(!rope||note.rope===rope));
  }
  // New notes go to the group used last, unless the button names one.
  function defaultRope() {
    const names=asArray(state.notes?.ropes).map((rope)=>rope.name), last=readPreference('note-rope','');
    return names.includes(last)?last:names[0]||'';
  }
  function openNote(id,rope) {
    if(!notesReady()){notice('便签需要重启本地服务后才能使用。',{tone:'warn'});return;}
    const note=findNote(id,rope);
    if(note)showEditor(note,note.rope,'','');
  }
  function openNewNote({rope='',date='',text=''}={}) {
    if(!notesReady()){notice('便签需要重启本地服务后才能使用。',{tone:'warn'});return;}
    showEditor(null,rope||defaultRope(),date,text);
  }
  function showEditor(note,rope,date,text) {
    // Opening another note (e.g. ⌘K → 新建便签) must not throw away what is being written.
    if(noteDirty()){showNoteDiscard();return;}
    const fromDay=noteDialog.open&&$('.day-sheet',noteDialog)?state.dayOpen:'';
    if(!noteDialog.open)rememberNoteReturn();
    state.noteDay=fromDay;state.noteConflict=null;
    $('#note-dialog-content').innerHTML=notesUI.editorHTML(note,state.notes?.ropes,rope,deps,date,fromDay);
    const field=$('#note-text');
    if(field&&text)field.value=text;
    openModal(noteDialog);
    snapshotNote();
    if(field){field.focus();field.setSelectionRange(field.value.length,field.value.length);}
  }
  function noteValues() {
    if(!$('#note-form'))return '';
    return JSON.stringify([$('#note-text')?.value||'',$('#note-rope')?.value||'',$('#note-rope-new')?.value||'',$('#note-date')?.value||'',$('input[name="note-color"]:checked')?.value||'']);
  }
  function snapshotNote() { noteSnapshot=$('#note-form')?noteValues():null; }
  function noteDirty() { return noteDialog.open&&noteSnapshot!==null&&!!$('#note-form')&&noteValues()!==noteSnapshot; }
  function paintNoteForm(color) {
    const form=$('#note-form');if(!form||!notesUI)return;
    const shade=notesUI.COLORS.some(([key])=>key===color)?color:'lilac';
    notesUI.COLORS.forEach(([key])=>form.classList.remove(`note-${key}`));
    form.classList.add(`note-${shade}`);
  }
  function showNoteBar(id) {
    const bar=document.getElementById(id);if(!bar)return null;
    $$('.note-discard,.note-conflict',noteDialog).forEach((item)=>{item.hidden=item!==bar;});
    return bar;
  }
  function showNoteDiscard() { const bar=showNoteBar('note-discard');($('[data-note-discard-keep]',bar||noteDialog)||$('#note-text'))?.focus(); }
  function keepEditing() { const bar=$('#note-discard');if(bar)bar.hidden=true;$('#note-text')?.focus(); }
  // ×, 取消, Esc and the backdrop: unsaved edits ask first; an editor opened from a day sheet goes back to it.
  function closeNoteDialog() {
    if(noteDirty()){showNoteDiscard();return;}
    leaveNoteEditor();
  }
  function leaveNoteEditor(focusId='') {
    const editing=!!$('#note-form'), day=editing?state.noteDay:'', id=focusId||$('#note-id')?.value||'';
    noteSnapshot=null;state.noteConflict=null;state.noteDay='';
    if(day&&noteDialog.open)openDay(day,id);else noteDialog.close();
  }
  function noteError(message) { const element=$('#note-error');if(element){element.textContent=message;element.hidden=!message;} }
  async function saveNote() {
    const field=$('#note-text'), text=field.value;
    if(!text.trim()){noteError('先写点什么');field.focus();return;}
    const picked=$('#note-rope').value, creating=picked===notesUI?.NEW_ROPE;
    const id=$('#note-id').value, from=$('#note-from').value, rope=creating?($('#note-rope-new')?.value||'').trim():picked;
    if(creating&&!rope){noteError('给新分组起个名字');$('#note-rope-new')?.focus();return;}
    const color=$('input[name="note-color"]:checked')?.value||'lilac', date=$('#note-date')?.value||'', seen=$('#note-updated')?.value||'';
    const buttons=$$('#note-form [type="submit"]');buttons.forEach((button)=>{button.disabled=true;});
    try{
      const body={id:id||undefined,rope:id?from:rope,text,color,date};
      if(id&&seen)body.updated_at=seen;
      const saved=await postJSON('/api/notes/save',body);
      if(id&&rope&&rope!==from)await postJSON('/api/notes/move',{id,rope:from,to:rope});
      if(rope)savePreference('note-rope',rope);
      state.lastNote=saved.id;noteSnapshot=null;
      const day=state.noteDay;
      if(day){await loadNotes();if(noteDialog.open&&$('#note-form')){state.noteDay=day;leaveNoteEditor(saved.id);}}
      else{noteDialog.close();loadNotes();}
      notice(id?'已保存':'贴上了',{tone:'success'});
    }catch(error){
      buttons.forEach((button)=>{button.disabled=false;});
      if(error.status===409&&error.data?.conflict&&error.data.note){showConflict(error.data.note);return;}
      noteError(error.message);
    }
  }
  function showConflict(server) {
    state.noteConflict=server;
    const bar=showNoteBar('note-conflict');
    if(!bar){noteError('这张便签刚被改过，先看看新内容再保存。');return;}
    $('.note-conflict-text',bar).textContent=String(server.text||'');
    $('[data-note-conflict-keep]',bar)?.focus();
  }
  function takeServerNote() {
    const server=state.noteConflict;if(!server)return;
    $('#note-text').value=server.text||'';
    const radio=$(`input[name="note-color"][value="${CSS.escape(server.color||'lilac')}"]`);if(radio)radio.checked=true;
    paintNoteForm(server.color);
    if($('#note-date'))$('#note-date').value=server.date||'';
    if($('#note-updated'))$('#note-updated').value=server.updated_at||'';
    if(server.rope&&$('#note-from')){$('#note-from').value=server.rope;setControl('note-rope',server.rope);}
    state.noteConflict=null;$('#note-conflict').hidden=true;
    snapshotNote();$('#note-text').focus();
  }
  function keepMyNote() {
    const server=state.noteConflict;if(!server)return;
    if($('#note-updated'))$('#note-updated').value=server.updated_at||'';
    state.noteConflict=null;$('#note-conflict').hidden=true;
    $('#note-form')?.requestSubmit();
  }
  function openRopeForm(name) {
    if(!notesReady())return;
    if(!noteDialog.open)rememberNoteReturn();
    state.noteDay='';noteSnapshot=null;
    const rope=asArray(state.notes?.ropes).find((item)=>item.name===name);
    $('#note-dialog-content').innerHTML=notesUI.ropeFormHTML(name||'',!asArray(rope?.notes).length,deps);
    openModal(noteDialog);
    $('#rope-name').focus();$('#rope-name').select();
  }
  async function saveRope() {
    const name=$('#rope-name').value.trim(), from=$('#rope-from').value;
    if(!name){noteError('给分组起个名字');return;}
    try{
      if(from&&from!==name)await postJSON('/api/notes/rope',{action:'rename',name:from,to:name});
      else if(!from)await postJSON('/api/notes/rope',{action:'create',name});
      noteDialog.close();await loadNotes();
    }catch(error){noteError(error.message);}
  }
  function dropNote(id,rope) { const group=asArray(state.notes?.ropes).find((item)=>item.name===rope);if(group)group.notes=asArray(group.notes).filter((item)=>item.id!==id); }
  async function removeNote(id,rope) {
    const card=$(`.note[data-note="${CSS.escape(id)}"]`);
    const sibling=(element)=>element?.matches?.('.note[data-note]')?element:null;
    const next=card&&(sibling(card.nextElementSibling)||sibling(card.previousElementSibling)||card.parentElement?.querySelector('.note-add'));
    try{
      const result=await postJSON('/api/notes/remove',{id,rope});
      if(next){state.noteReturnFocus=next;state.noteReturnKey=keyOf(next);}
      noteSnapshot=null;dropNote(id,rope);
      if(state.noteDay&&noteDialog.open)leaveNoteEditor();else noteDialog.close();
      notice('已撤下',{action:{label:'撤销',run:()=>restoreNote({id,rope,...result})}});
      loadNotes();
    }catch(error){noteError(error.message);}
  }
  async function restoreNote(note) {
    let id=note.id;
    try{const restored=await postJSON('/api/notes/restore',restoreRequest(note));id=restored?.id||id;state.lastNote=id;notice('已放回',{tone:'success'});}
    catch(error){notice(error.message,{tone:'error'});}
    await loadNotes();
    if(state.route==='notes'&&!noteDialog.open)$(`.note[data-note="${CSS.escape(id)}"]`)?.focus();
  }
  function restoreFromShelf(button) {
    const value=button.dataset.noteRestore;
    const entry=asArray(state.notes?.shelf).find((item)=>item.id===value||item.key===value);
    restoreNote({id:entry?.id||value,rope:button.dataset.noteRope||button.dataset.rope||entry?.rope||''});
  }
  async function removeRope(name) {
    try{await postJSON('/api/notes/rope',{action:'remove',name});noteDialog.close();notice('分组已移除，文件夹收在「便签/.已撤下」里',{tone:'success'});await loadNotes();}
    catch(error){noteError(error.message);}
  }
  // 拖动便签：同一个分组里换位置，或者挪到另一个分组。位置用 offset 算，不受便签的小角度影响。
  function boardBoxes(board,skip) {
    return $$('.note',board).filter((note)=>note.dataset.note!==skip).map((note)=>({left:note.offsetLeft,top:note.offsetTop,width:note.offsetWidth,height:note.offsetHeight}));
  }
  function boardIndex(board,x,y) {
    const rect=board.getBoundingClientRect();
    return notesUI.dropIndex(boardBoxes(board,state.dragging?.id),x-rect.left+board.scrollLeft-board.clientLeft,y-rect.top+board.scrollTop-board.clientTop);
  }
  function clearDropMarks() { $$('.drop-before,.drop-end,.drop-target').forEach((element)=>element.classList.remove('drop-before','drop-end','drop-target')); }
  function markDrop(track,x,y) {
    clearDropMarks();
    if(track.classList.contains('cal-day')){track.classList.add('drop-target');return;}
    const notes=$$('.note',track).filter((note)=>note.dataset.note!==state.dragging?.id);
    const index=boardIndex(track,x,y);
    track.classList.add('drop-target');
    (notes[index]||track).classList.add(notes[index]?'drop-before':'drop-end');
    return index;
  }
  async function moveNote(id,from,to,index) {
    const source=asArray(state.notes?.ropes).find((rope)=>rope.name===from), target=asArray(state.notes?.ropes).find((rope)=>rope.name===to);
    const note=source&&asArray(source.notes).find((item)=>item.id===id);
    if(!note||!target)return;
    // 先在界面上挪好，再写文件；失败就重新读取。
    source.notes=source.notes.filter((item)=>item.id!==id);
    target.notes.splice(Math.min(index,target.notes.length),0,{...note,rope:to});
    renderNotes();
    try{await postJSON('/api/notes/move',{id,rope:from,to,index});}
    catch(error){notice(error.message,{tone:'error'});await loadNotes();}
  }
  // ⌥↑ ⌥↓ (⌥← ⌥→): move the focused note one place within its group.
  function nudgeNote(element,step) {
    const {note:id,rope}=element.dataset;
    const group=asArray(state.notes?.ropes).find((item)=>item.name===rope);
    const index=asArray(group?.notes).findIndex((item)=>item.id===id);
    if(index<0)return;
    const target=index+step;
    if(target<0||target>=group.notes.length){notice(step<0?'已经是第一张':'已经是最后一张',{key:'note-move'});return;}
    moveNote(id,rope,rope,target);
    $(`.note[data-note="${CSS.escape(id)}"]`)?.focus();
    notice(`已移到第 ${target+1} 张`,{key:'note-move'});
  }
  // 月历里把便签拖到另一天：只改日期。
  async function redateNote(id,rope,date) {
    const note=findNote(id,rope);
    if(!note||notesUI.dayOf(note)===date)return;
    const seen=note.updated_at;
    note.date=date;renderNotes();
    try{await postJSON('/api/notes/save',{id,rope,text:note.text,color:note.color,date,...(seen?{updated_at:seen}:{})});notice(`改到 ${dayLabel(date)}`,{tone:'success'});}
    catch(error){notice(error.message,{tone:'error'});}
    await loadNotes();
  }

  // -- 移到废纸篓：先问一声 -------------------------------------------------------------------
  // A small modal on top of whatever is open (the note shell, the same look as the 不保存 bar). Resolves true on the
  // danger button or Enter, false on 取消, Escape, the backdrop or anything else that closes it.
  let confirmSettle=null;
  function settleConfirm(value) {
    const done=confirmSettle;confirmSettle=null;
    if(confirmDialog.open)confirmDialog.close();
    done?.(value);
  }
  function confirmAction({title,detail='',label='好',cancel='取消',tone='danger'}={}) {
    if(confirmSettle)settleConfirm(false);
    $('#confirm-dialog-content').innerHTML=`<form class="note-editor confirm-box" id="confirm-form" method="dialog"><h2 id="confirm-title">${esc(title)}</h2>${detail?`<p class="confirm-detail">${esc(detail)}</p>`:''}<footer class="note-editor-foot confirm-foot"><button type="button" class="button" data-confirm="no">${esc(cancel)}</button><button type="submit" class="button ${tone==='danger'?'danger':'primary'}" data-confirm="yes">${esc(label)}</button></footer></form>`;
    openModal(confirmDialog);
    $('[data-confirm="yes"]',confirmDialog)?.focus();
    return new Promise((resolve)=>{confirmSettle=resolve;});
  }
  confirmDialog.addEventListener('click',(event)=>{if(event.target.closest?.('[data-confirm="no"]'))settleConfirm(false);});
  confirmDialog.addEventListener('close',()=>{if(confirmSettle)settleConfirm(false);});
  const firstLineOf=(text)=>String(text||'').split('\n')[0].trim().slice(0,60);
  // 删除 a note (in the editor, or on the 已撤下 shelf): the server moves the file to the system Trash, so there is no 撤销.
  async function deleteNote(id,rope,{shelf=false}={}) {
    const note=shelf?asArray(state.notes?.shelf).find((item)=>item.id===id):findNote(id,rope);
    if(!await confirmAction({title:'移到废纸篓？',detail:firstLineOf(note?.text),label:'移到废纸篓'}))return;
    try{
      await postJSON('/api/notes/delete',shelf?{id,rope,shelf:true}:{id,rope});
      if(!shelf){noteSnapshot=null;dropNote(id,rope);if(state.noteDay&&noteDialog.open)leaveNoteEditor();else if(noteDialog.open)noteDialog.close();}
      notice('已移到废纸篓',{tone:'success'});
      loadNotes();
    }catch(error){if(noteDialog.open&&$('#note-error'))noteError(error.message);else notice(error.message,{tone:'error'});}
  }
  async function clearShelf(count) {
    if(!await confirmAction({title:`把已撤下的 ${count} 张都移到废纸篓？`,label:'移到废纸篓'}))return;
    try{
      const result=await postJSON('/api/notes/shelf/clear',{});
      const moved=Number(result?.trashed);
      notice(moved>1?`${moved} 张已移到废纸篓`:'已移到废纸篓',{tone:'success'});
      loadNotes();
    }catch(error){notice(error.message,{tone:'error'});}
  }
  // 移到废纸篓 on a work: the folder goes to the system Trash; the card leaves the lists right away (the index catches up by event).
  async function trashWork(id) {
    const work=state.detail?.work?.id===id?state.detail.work:[...state.works,...state.allWorks].find((entry)=>entry.id===id);
    if(!await confirmAction({title:'移到废纸篓？',detail:work?.title||'',label:'移到废纸篓'}))return;
    try{
      await postJSON(`/api/works/${encodeURIComponent(id)}/trash`,{});
      if(dialog.open&&state.detailKind==='work'&&state.detailId===id){state.detailFocus=null;dialog.close();}
      state.works=state.works.filter((entry)=>entry.id!==id);state.allWorks=state.allWorks.filter((entry)=>entry.id!==id);
      state.items=state.items.filter((item)=>item?.work_id!==id);
      for(const kind of Object.keys(state.allItems))state.allItems[kind]=asArray(state.allItems[kind]).filter((item)=>item?.work_id!==id);
      syncClients();updateShell();
      if(state.route==='works'){renderFolders();renderWorks();}else if(state.route==='desk')renderCurrent();
      notice('已移到废纸篓',{tone:'success'});
    }catch(error){notice(error.message,{tone:'error'});}
  }

  // -- 整理客户 ---------------------------------------------------------------------------
  // The dialog edits a local copy of the groups; 保存 posts it once. Drag, ⌥↑/⌥↓ and the 移到… listbox all end in moveClient.
  const organizer={groups:[],snapshot:'',editing:-1,dragging:null,returnFocus:null,returnKey:''};
  function openClientsDialog(trigger) {
    if(!library)return;
    organizer.returnFocus=trigger||returnTarget();organizer.returnKey=keyOf(organizer.returnFocus);
    organizer.groups=library.clientGroupsFor(state.health,state.clients,countBy(state.allWorks,workClient));
    organizer.snapshot=JSON.stringify(organizer.groups);organizer.editing=-1;organizer.dragging=null;
    renderClientsDialog();
    openModal(clientsDialog);
    ($('.client-handle',clientsDialog)||$('[data-action="close-clients"]',clientsDialog))?.focus();
  }
  function renderClientsDialog() {
    const host=$('#clients-dialog-content');
    keepFocus(host,()=>{host.innerHTML=library.clientsDialogHTML(organizer.groups,deps,{editing:organizer.editing});});
  }
  function clientsError(message) { const element=$('#clients-error');if(element){element.textContent=message;element.hidden=!message;} }
  function clientsDirty() { return clientsDialog.open&&JSON.stringify(organizer.groups)!==organizer.snapshot; }
  // ×, 取消, Escape and the backdrop: unsaved changes ask first, like the note editor.
  function closeClientsDialog() {
    if(clientsDirty()){const bar=$('#clients-discard');if(bar){bar.hidden=false;$('[data-clients-discard-keep]',bar)?.focus();return;}}
    clientsDialog.close();
  }
  function findClientRow(code) {
    for(const [groupIndex,group] of organizer.groups.entries()){const clientIndex=group.clients.findIndex((client)=>client.code===code);if(clientIndex>=0)return {groupIndex,clientIndex,client:group.clients[clientIndex]};}
    return null;
  }
  const focusClient=(code,selector='.client-handle')=>$(`.client-row[data-client-row="${CSS.escape(code)}"] ${selector}`,clientsDialog)?.focus({preventScroll:true});
  // index counts the target group's rows without the moving one (drop positions are computed that way too); omitted = the end.
  function moveClient(code,groupIndex,index) {
    const at=findClientRow(code), target=organizer.groups[groupIndex];
    if(!at||!target)return;
    const [client]=organizer.groups[at.groupIndex].clients.splice(at.clientIndex,1);
    const place=Number.isInteger(index)?Math.max(0,Math.min(index,target.clients.length)):target.clients.length;
    target.clients.splice(place,0,client);
    renderClientsDialog();
  }
  function nudgeClient(code,step) {
    const at=findClientRow(code);if(!at)return;
    const group=organizer.groups[at.groupIndex], index=at.clientIndex+step;
    if(index<0||index>=group.clients.length){notice(step<0?'已经是第一个':'已经是最后一个',{key:'client-move'});return;}
    moveClient(code,at.groupIndex,index);
    focusClient(code);
    notice(`已移到第 ${index+1} 个`,{key:'client-move'});
  }
  function setClientColor(code,slot) {
    const at=findClientRow(code);if(!at)return;
    at.client.color=slot?library.PALETTE_HEX[slot-1]||null:null;
    renderClientsDialog();focusClient(code,'.swatch-pick');
  }
  function removeClient(code) {
    const at=findClientRow(code);if(!at||at.client.works)return;
    const group=organizer.groups[at.groupIndex];
    const next=group.clients[at.clientIndex+1]||group.clients[at.clientIndex-1];
    group.clients.splice(at.clientIndex,1);
    renderClientsDialog();
    if(next)focusClient(next.code);else $(`[data-group-rename="${at.groupIndex}"]`,clientsDialog)?.focus();
  }
  function addClientGroup() {
    organizer.groups.push({name:'',clients:[]});
    startGroupRename(organizer.groups.length-1);
  }
  function removeClientGroup(index) {
    if(organizer.groups[index]?.clients.length)return;
    organizer.groups.splice(index,1);
    if(organizer.editing===index)organizer.editing=-1;
    renderClientsDialog();
    $('[data-group-add]',clientsDialog)?.focus();
  }
  function startGroupRename(index) {
    organizer.editing=index;renderClientsDialog();
    const input=$(`[data-group-input="${index}"]`,clientsDialog);
    if(input){input.focus();input.select();}
  }
  // Enter or leaving the field keeps the new name; an emptied name keeps the old one, and an empty new group goes away.
  // inPlace (focus left by mouse): swap the field for the heading without redrawing, so the click that moved focus still lands.
  function commitGroupRename(index,value,{cancel=false,inPlace=false}={}) {
    if(organizer.editing!==index)return;
    organizer.editing=-1;
    const group=organizer.groups[index];
    if(!group){renderClientsDialog();return;}
    const name=cancel?group.name:String(value||'').trim();
    if(name)group.name=name;
    const abandoned=!group.name&&!group.clients.length;
    if(abandoned)organizer.groups.splice(index,1);
    if(abandoned&&inPlace){$(`[data-group-section="${index}"]`,clientsDialog)?.remove();$$(`.client-move [role="option"][data-value="${index}"]`,clientsDialog).forEach((option)=>option.remove());return;}
    if(!inPlace){renderClientsDialog();(abandoned?$('[data-group-add]',clientsDialog):$(`[data-group-rename="${index}"]`,clientsDialog))?.focus();return;}
    const shown=esc(group.name);
    const input=$(`[data-group-input="${index}"]`,clientsDialog);
    if(input)input.outerHTML=`<button type="button" class="clients-group-name" id="clients-group-${index}" data-group-rename="${index}" aria-label="改名：${shown}">${shown}</button>`;
    $(`[data-group-section="${index}"]`,clientsDialog)?.setAttribute('aria-label',group.name);
    $$(`.client-move [role="option"][data-value="${index}"] .listbox-option-label`,clientsDialog).forEach((label)=>{label.textContent=group.name;});
    $$('.client-move',clientsDialog).forEach((box)=>{if(box.querySelector('input[type="hidden"]')?.value===String(index))box.querySelector('.listbox-value').textContent=group.name;});
  }
  async function saveClients() {
    // WebKit does not move focus on click: a name still being typed is taken as it stands.
    const typing=$('[data-group-input]',clientsDialog);
    if(typing){const group=organizer.groups[Number(typing.dataset.groupInput)];const name=typing.value.trim();if(group&&name)group.name=name;}
    const problem=library.clientsSaveError(organizer.groups);
    if(problem){clientsError(problem);return;}
    clientsError('');
    const buttons=$$('#clients-form [type="submit"]');buttons.forEach((button)=>{button.disabled=true;});
    try{
      const result=await postJSON('/api/clients/save',library.clientsSavePayload(organizer.groups));
      if(state.health){if(Array.isArray(result?.clients))state.health.clients=result.clients;if(Array.isArray(result?.client_groups))state.health.client_groups=result.client_groups;}
      syncClients();organizer.snapshot=JSON.stringify(organizer.groups);
      clientsDialog.close();
      notice('已保存',{tone:'success'});
      if(state.route==='works'){renderFolders();renderWorks();}else renderCurrent();
    }catch(error){buttons.forEach((button)=>{button.disabled=false;});notice(error.message,{tone:'error'});}
  }
  // Everything inside the dialog is handled here; the page-wide handlers below only close the swatch popover.
  clientsDialog.addEventListener('click',(event)=>{
    const target=event.target.closest('button');if(!target)return;
    if(target.dataset.action==='close-clients')closeClientsDialog();
    else if(target.hasAttribute('data-clients-discard-keep')){const bar=$('#clients-discard');if(bar)bar.hidden=true;($('.client-handle',clientsDialog)||$('[data-action="close-clients"]',clientsDialog))?.focus();}
    else if(target.hasAttribute('data-clients-discard'))clientsDialog.close();
    else if(target.hasAttribute('data-group-add'))addClientGroup();
    else if(target.dataset.groupRename!==undefined)startGroupRename(Number(target.dataset.groupRename));
    else if(target.dataset.groupRemove!==undefined)removeClientGroup(Number(target.dataset.groupRemove));
    else if(target.dataset.clientColor!==undefined)setClientColor(target.dataset.clientColor,Number(target.dataset.color)||0);
    else if(target.dataset.clientDelete!==undefined)removeClient(target.dataset.clientDelete);
  });
  clientsDialog.addEventListener('input',(event)=>{
    const code=event.target.dataset?.clientName;if(code===undefined)return;
    const at=findClientRow(code);if(at)at.client.name=event.target.value;
  });
  clientsDialog.addEventListener('change',(event)=>{
    const id=String(event.target.id||'');if(!id.startsWith('client-move-'))return;
    const code=id.slice('client-move-'.length), groupIndex=Number(event.target.value);
    const at=findClientRow(code);
    if(!at||at.groupIndex===groupIndex)return;
    moveClient(code,groupIndex);
    focusControl(id);
    notice(`已移到「${organizer.groups[groupIndex]?.name||'新分组'}」`,{key:'client-move'});
  });
  clientsDialog.addEventListener('keydown',(event)=>{
    if(event.isComposing||event.keyCode===229)return;
    const key=String(event.key||'');
    const groupInput=event.target.closest?.('[data-group-input]');
    if(groupInput){
      const index=Number(groupInput.dataset.groupInput);
      if(key==='Enter'){event.preventDefault();commitGroupRename(index,groupInput.value);}
      else if(key==='Escape'){event.preventDefault();event.stopPropagation();commitGroupRename(index,'',{cancel:true});}
      return;
    }
    const row=event.target.closest?.('.client-row');
    if(row&&event.altKey&&!event.metaKey&&!event.ctrlKey&&(key==='ArrowUp'||key==='ArrowDown')&&!isTypingTarget(event.target)){event.preventDefault();nudgeClient(row.dataset.clientRow,key==='ArrowUp'?-1:1);}
  });
  clientsDialog.addEventListener('focusout',(event)=>{
    const groupInput=event.target.closest?.('[data-group-input]');
    if(groupInput&&!event.relatedTarget?.closest?.('[data-group-input]'))commitGroupRename(Number(groupInput.dataset.groupInput),groupInput.value,{inPlace:true});
  });
  // Drag a row within its group or into another one (an empty group is a target too).
  const clientRows=(list)=>$$('.client-row',list).filter((row)=>row.dataset.clientRow!==organizer.dragging);
  function clientDropIndex(list,y) {
    const rows=clientRows(list);
    const hit=rows.findIndex((row)=>{const box=row.getBoundingClientRect();return y<box.top+box.height/2;});
    return hit<0?rows.length:hit;
  }
  let clientDragFrame=0;
  clientsDialog.addEventListener('dragstart',(event)=>{
    const row=event.target.closest?.('.client-row');if(!row||event.target.closest?.('input'))return;
    organizer.dragging=row.dataset.clientRow;
    event.dataTransfer.effectAllowed='move';event.dataTransfer.setData('text/plain',row.dataset.clientRow);
    requestAnimationFrame(()=>row.classList.add('dragging'));
  });
  clientsDialog.addEventListener('dragover',(event)=>{
    if(!organizer.dragging)return;
    const list=event.target.closest?.('.clients-list');if(!list)return;
    event.preventDefault();event.dataTransfer.dropEffect='move';
    const y=event.clientY;
    cancelAnimationFrame(clientDragFrame);
    clientDragFrame=requestAnimationFrame(()=>{clearDropMarks();const rows=clientRows(list), index=clientDropIndex(list,y);list.classList.add('drop-target');(rows[index]||list).classList.add(rows[index]?'drop-before':'drop-end');});
  });
  clientsDialog.addEventListener('drop',(event)=>{
    if(!organizer.dragging)return;
    const list=event.target.closest?.('.clients-list');if(!list)return;
    event.preventDefault();cancelAnimationFrame(clientDragFrame);
    const code=organizer.dragging, index=clientDropIndex(list,event.clientY);
    organizer.dragging=null;clearDropMarks();
    moveClient(code,Number(list.dataset.groupList),index);
    focusClient(code);
  });
  clientsDialog.addEventListener('dragend',()=>{cancelAnimationFrame(clientDragFrame);organizer.dragging=null;clearDropMarks();$$('.dragging',clientsDialog).forEach((row)=>row.classList.remove('dragging'));});
  clientsDialog.addEventListener('close',()=>{
    organizer.groups=[];organizer.snapshot='';organizer.editing=-1;organizer.dragging=null;
    if(!restoreFocus(organizer.returnFocus,organizer.returnKey)&&!topModal())focusPage();
  });

  // -- routes --------------------------------------------------------------------------
  function libraryControlHTML(id) {
    if(id==='status-filter')return listbox({id,label:'作品状态',value:state.status,options:[['','全部状态'],...Object.entries(STATUS)]});
    // 封面比例 lives in the small 显示 menu (setLayoutButtons hides it where it does not apply).
    if(id==='cover-ratio')return library?`<span class="display-slot" id="display-slot">${library.displayMenuHTML(state.cover,deps)}</span>`:'';
    return '';
  }
  function showLibrary() {
    $('#view').innerHTML=libraryHTML;
    $$('[data-listbox-slot]').forEach((slot)=>{slot.outerHTML=libraryControlHTML(slot.dataset.listboxSlot);});
    if(state.kind==='skill')skillsChrome();
    $('#search').value=state.query;
    renderFolders();
    renderWorks();
  }
  // The Skills page is the library page under its own name, one step below 设置.
  function skillsChrome() {
    const view=$('#view');
    $('#library-title',view).textContent='Skills';
    $('.library-heading',view)?.insertAdjacentHTML('beforebegin',`<a class="page-back" href="#settings" aria-label="返回设置">${icon('arrow-left')}<span>设置</span></a>`);
    $('#search',view).placeholder='搜索 Skills';
    $('label[for="search"]',view).textContent='搜索 Skills';
  }
  function renderCurrent() {
    const view=$('#view');
    state.today=localDay();
    keepFocus(view,()=>{
      if(!dashboard&&['desk','intelligence','analytics'].includes(state.route))view.innerHTML='<div class="empty-state"><h1 tabindex="-1">界面没有完整载入</h1><p>重新载入后即可恢复。</p><button type="button" class="button primary" data-action="refresh">重新载入</button></div>';
      else if(state.route==='works'){if(!$('#work-results'))showLibrary();else renderWorks();}
      else if(state.route==='desk')view.innerHTML=dashboard.renderOverview(state,deps);
      else if(state.route==='analytics')view.innerHTML=analytics?analytics.renderAnalytics(state,deps):'<div class="empty-state"><h1 tabindex="-1">数据页没有载入</h1><p>重新载入后即可恢复。</p></div>';
      else if(state.route==='intelligence')view.innerHTML=dashboard.renderIntelligence(state,deps);
      else if(state.route==='notes')renderNotes();
      else if(state.route==='publish')renderPublish();
      else if(state.route==='tools')renderTools();
      else if(state.route==='settings')renderSettings();
    });
    updateShell();
  }
  function legacyURL(hash='publish',draftID='',prefill={}) {
    const base=state.dashboard?.capabilities?.legacy_base||document.body.dataset.legacyBase;
    if(!base||!base.startsWith('/')||base.startsWith('//'))return '';
    const target=new URL(base,location.origin);
    if(target.origin!==location.origin)return '';
    if(draftID)target.searchParams.set('draft_id',draftID);
    for(const key of PREFILL_KEYS)if(prefill?.[key])target.searchParams.set(key,prefill[key]);
    target.hash=hash;
    return target.pathname+target.search+target.hash;
  }
  function setRoute(route) { state.route=route;document.documentElement.dataset.route=route; }
  function setTitle() { document.title=pageTitle(state.route,state.tool,state.route==='works'&&state.kind==='skill'?'skills':state.route==='publish'?'entries':''); }
  function focusPage() {
    const heading=$('#view h1');
    if(heading){if(!heading.hasAttribute('tabindex'))heading.tabIndex=-1;heading.focus({preventScroll:true});}
    else $('#view').focus({preventScroll:true});
  }
  function scrollToTop() { for(const element of [document.scrollingElement,$('.workspace-content'),$('.body-layout'),$('#view')])if(element)element.scrollTop=0; }
  // A route change closes what is open, except an editor with unsaved text: it stays and asks.
  // Their close handlers then leave focus to the new page instead of an old trigger.
  function closeLayersForRoute() {
    if(palette?.open)palette.close();
    if(dialog.open){state.detailFocus=null;state.returnFocus=null;state.returnKey='';dialog.close();}
    if(postDialog.open){state.postReturnFocus=null;state.postReturnKey='';postDialog.close();}
    if(noteDialog.open){if(noteDirty())showNoteDiscard();else{state.noteReturnFocus=null;state.noteReturnKey='';noteDialog.close();}}
  }
  function navigate() {
    const raw=location.hash.slice(1);
    const requested=raw.split('?')[0]||'desk';
    const route=ROUTES.includes(requested)?requested:'desk';
    closeLayersForRoute();
    const params=new URLSearchParams(raw.split('?')[1]||location.search);
    const draftID=state.pendingNativeDraft||params.get('draft_id');
    if(route==='publish'&&draftID&&toolURL('publish',draftID)){state.pendingNativeDraft=null;location.replace(toolURL('publish',draftID));return;}
    // The retired 导入数据总览 lands on 数据导入.
    const redirect=ROUTES.includes(requested)?routeRedirect(raw):'';
    if(redirect){location.replace(redirect);return;}
    if(route==='tools'){
      state.tool=TOOL_NAMES[params.get('name')]?params.get('name'):'studio';state.toolDraft=/^[A-Za-z0-9_-]{1,128}$/.test(params.get('draft_id')||'')?params.get('draft_id'):'';
      // 添加账号 opens 账号档案 with the client, platform and handle filled in (the handle is what links the two records).
      const client=String(params.get('client')||'').slice(0,60), platform=/^[a-z_-]{1,30}$/.test(params.get('platform')||'')?params.get('platform'):'';
      const handle=String(params.get('handle')||'').replace(/[\u0000-\u001f]/g,'').slice(0,150);
      state.toolPrefill=state.tool==='accounts'&&(client||platform)?{client,platform,handle}:{};
    }
    // #works?client=AK&category=运营&status=published: a key in the address sets that filter; the others stay as they are.
    const filters=route==='works'?worksParams(params):{};
    const status=filters.status||'';
    // #works?kind=skill is the Skills page (from 设置); any other #works shows the 资产库 tab last used (a 专业 or status is works).
    const kindChanged=route==='works'&&useKind(params.get('kind')==='skill'?'skill':status||filters.category?'work':state.libraryKind);
    if(status){state.status=status;state.query='';state.category='';state.section='';state.client='';state.libraryKind='work';}
    let filterChanged=false;
    for(const key of ['client','category'])if(key in filters&&filters[key]!==state[key]){state[key]=filters[key];filterChanged=true;}
    if(route==='intelligence'&&['news','research','candidates'].includes(params.get('tab')))state.intelPageTab=params.get('tab');
    // #analytics?view=tags&tag=开头弱: the 原因标签 view, filtered to that tag (a tag chip in a post or work dialog lands here).
    if(route==='analytics'&&(params.has('view')||params.has('tag'))){state.analyticsContent=params.get('view')==='tags'||params.has('tag')?'tags':'rank';state.analyticsTag=String(params.get('tag')||'').replace(/[\u0000-\u001f]/g,'').trim().slice(0,60);}
    const previous=state.route, first=!navigated, fromTabs=!!returnTarget()?.closest?.('.subtabs');
    navigated=true;
    setRoute(route);
    if(route!=='tools'&&$('#tool-host'))$('#tool-host').hidden=true;
    if(route==='works'){showLibrary();syncWorksHash();if(status||kindChanged||filterChanged){loadCurrentLibrary();loadMatchCounts();}}else renderCurrent();
    setTitle();
    updateShell();
    // #settings?section=accounts (the welcome card, hidden nav entries): land on 账号与数据 itself.
    const section=route==='settings'&&params.get('section')==='accounts'?$('#settings-accounts'):null;
    if(section){section.tabIndex=-1;section.scrollIntoView({block:'start'});section.focus({preventScroll:true});return;}
    if(first)return;
    const active=document.activeElement, lost=focusLost(active);
    const typing=!lost&&isTypingTarget(active)&&!topModal();
    if(fromTabs&&$('.subtab[aria-current="page"]'))$('.subtab[aria-current="page"]').focus({preventScroll:true});
    else if(!topModal()&&!typing&&(previous!==route||lost))focusPage();
    if(previous!==route)scrollToTop();
  }
  // In-app navigation that runs synchronously (the palette, searches).
  function go(hash) {
    if(location.hash!==hash)history.pushState(null,'',hash);
    navigate();
  }
  function choiceHTML(label,attr,current,options) {
    return `<div class="settings-row"><span>${label}</span><div class="segmented" role="group" aria-label="${label}">${options.map(([value,text])=>`<button type="button" class="theme-choice" ${attr}="${value}" aria-pressed="${current===value}">${text}</button>`).join('')}</div></div>`;
  }
  function workspaceSettingsHTML() {
    const health=state.health;
    const source=health?.workspace_source;
    const fixed=source==='env';
    const editable=health?.capabilities?.workspace_setting===true&&!fixed;
    const picker=editable&&typeof window.webkit?.messageHandlers?.chooseWorkspace?.postMessage==='function';
    const path=health?.workspace_path||'';
    const connected=!!health&&net.online;
    const label=source==='custom'?'自定义位置':source==='env'?'由启动参数指定':'默认位置';
    const form=editable?`<form class="workspace-form" id="workspace-form"><label class="sr-only" for="workspace-path">工作区文件夹</label><input id="workspace-path" value="${esc(path)}" placeholder="例如 ~/Documents/我的工作区" autocomplete="off" spellcheck="false"><div class="workspace-actions">${picker?`<button type="button" class="button" data-action="choose-workspace">${icon('folder-open')}选择文件夹…</button>`:''}<button type="submit" class="button primary" ${state.workspaceSaving?'disabled':''}>${state.workspaceSaving?'正在切换…':'使用这个位置'}</button>${source==='custom'?`<button type="button" class="button" data-action="reset-workspace">恢复默认</button>`:''}</div><p class="note-error" id="workspace-error" role="alert" hidden></p></form>`:'';
    return `<section class="panel settings-section" aria-labelledby="settings-workspace"><h2 class="panel-title" id="settings-workspace">工作区</h2><div class="settings-row"><span>连接</span><div class="settings-value"><span class="chip" data-tone="${connected?'ok':'danger'}">${connected?'已连上本机服务':'连不上本机服务'}</span>${connected?'':'<div class="settings-actions"><button type="button" class="button small" data-action="retry">重新连接</button></div>'}</div></div><div class="settings-row"><span>位置</span><div class="settings-value">${form?'':`<div>${esc(path||'未连接')}</div>`}<small>${esc(label)}${health?.workspace_resolved&&health.workspace_resolved!==health.workspace_path?` · 实际位置 ${esc(health.workspace_resolved)}`:''}</small>${form}</div></div><div class="settings-row"><span>最近索引</span><div class="settings-value">${esc(readableTime(health?.indexed_at))}</div></div></section>`;
  }
  function helpSettingsHTML() {
    const guide=state.health?.capabilities?.guide===true;
    // The one place that lists shortcuts: pages and dialogs do not repeat them.
    const keys=[['⌘ K','命令面板：跳转页面、搜索资产、新建便签'],['⌘ ↩','保存便签；命令面板里复制提示词'],['⌘ C','复制选中便签的文字'],['⌥ ↑ ↓','调整便签顺序'],['← →','详情里看上一个、下一个'],['esc','关闭最上层的窗口']];
    return `<section class="panel settings-section" aria-labelledby="settings-help"><h2 class="panel-title" id="settings-help">帮助</h2>${guide?`<div class="settings-row"><span>存放说明</span><div class="settings-value"><div class="settings-actions flush"><button type="button" class="button small" data-action="open-guide">${icon('info')}打开存放说明</button></div></div></div>`:''}<div class="settings-row"><span>快捷键</span><div class="settings-value"><dl class="shortcut-list">${keys.map(([key,text])=>`<div><dt>${key.split(' ').map((part)=>`<kbd>${esc(part)}</kbd>`).join('')}</dt><dd>${esc(text)}</dd></div>`).join('')}</dl></div></div><div class="settings-row"><span>关于</span><div class="settings-value">SPT ${esc(state.health?.version||'')}</div></div></section>`;
  }
  function renderSettings() {
    const source=state.dashboard;
    const accountsURL=toolURL('accounts');
    const look=`<section class="panel settings-section" aria-labelledby="settings-look"><h2 class="panel-title" id="settings-look">外观</h2>${choiceHTML('主题','data-theme',state.theme,[['dark','夜灯'],['light','白天'],['system','跟随系统']])}${choiceHTML('密度','data-density-choice',state.density,[['comfortable','舒适'],['compact','紧凑']])}${choiceHTML('动效','data-motion-choice',state.motion,[['full','小幽灵会动'],['reduced','安静一点']])}</section>`;
    const accounts=`<section class="panel settings-section" aria-labelledby="settings-accounts"><h2 class="panel-title" id="settings-accounts">账号与数据</h2><div class="settings-row"><span>账号资料</span><div class="settings-value">${asArray(source?.accounts).length} 个平台入口<div class="settings-actions"><a class="button small" href="${ENTRIES_HASH}">${ENTRIES_NAME}</a>${accountsURL?`<a class="button small" href="${esc(accountsURL)}">账号档案</a>`:''}</div></div></div><div class="settings-row"><span>运营数据</span><div class="settings-value"><div class="settings-actions flush"><a class="button small" href="#analytics">看数据</a>${toolURL('data')?`<a class="button small" href="${esc(toolURL('data'))}">导入数据</a>`:''}</div></div></div><div class="settings-row"><span>情报</span><div class="settings-value"><div class="settings-actions flush"><a class="button small" href="#intelligence">看情报</a></div></div></div>${state.dashboardError?`<p class="settings-note">${esc(state.dashboardError)}</p>`:''}</section>`;
    const typing=document.activeElement?.id==='workspace-path'?document.activeElement.value:null;
    if(typing!==null)queueMicrotask(()=>{const field=$('#workspace-path');if(field&&document.activeElement!==field){field.value=typing;field.focus({preventScroll:true});}});
    $('#view').innerHTML=`<section class="settings-page"><header class="page-heading"><div><h1 tabindex="-1">设置</h1></div></header>${workspaceSettingsHTML()}${look}${librarySettingsHTML()}${accounts}${helpSettingsHTML()}</section>`;
  }
  function workspaceError(message) {
    const element=$('#workspace-error'), input=$('#workspace-path');
    if(element){element.textContent=message;element.hidden=!message;}
    if(input){if(message){input.setAttribute('aria-invalid','true');input.setAttribute('aria-describedby','workspace-error');input.focus();}else{input.removeAttribute('aria-invalid');input.removeAttribute('aria-describedby');}}
  }
  async function saveWorkspace(path) {
    if(state.workspaceSaving)return;
    state.workspaceSaving=true;renderSettings();
    try{
      const result=await postJSON('/api/settings/workspace',{path});
      state.health=result.health||await api('/api/health');
      state.notes=null;state.libraryIndex=null;
      await Promise.allSettled([loadWorks({refreshAll:true}),loadDashboard(),libraryReady()?loadLibraryIndex():null,loadNotes()]);
      const works=Number(state.health?.counts?.works)||0, notes=notesUI?notesUI.count?.(state.notes)??0:0;
      notice(`${path?'已换到新的工作区':'已恢复默认工作区'}：${works} 件作品${notesUI?`、${notes} 张便签`:''}。原来位置的文件都还在原处。`,{tone:'success',duration:8000});
    }catch(error){state.workspaceSaving=false;renderSettings();workspaceError(error.message);return;}
    state.workspaceSaving=false;if(state.route==='settings')renderSettings();
  }
  // Paths with spaces or Chinese characters must be quoted to paste into 终端.
  function shellQuote(path) { return /^[A-Za-z0-9_./~:@%+=-]+$/.test(path) ? path : `'${String(path).replace(/'/g, `'\\''`)}'`; }
  // 设置 › Agent 接入: spt/bin/* on a Mac; Windows has no sh, so python -m with the software folder on PYTHONPATH.
  function agentCommands(root, platform) {
    if(platform!=='windows'){
      return {cli:`${shellQuote(`${root}/bin/spt`)} search 关键词`,
        mcp:`claude mcp add spt -s user -- ${shellQuote(`${root}/bin/spt-mcp`)}`,
        codex:`# ~/.codex/config.toml\n[mcp_servers.spt]\ncommand = ${JSON.stringify(`${root}/bin/spt-mcp`)}`};
    }
    const base=String(root).replace(/[\\/]spt[\\/]?$/,'');
    const python=`${base}\\.venv\\Scripts\\python.exe`;
    return {cli:`cd /d "${base}" && "${python}" -m spt.server.cli search 关键词`,
      mcp:`claude mcp add spt -s user -e PYTHONPATH="${base}" -- "${python}" -m spt.server.mcp_server`,
      codex:`# ~/.codex/config.toml\n[mcp_servers.spt]\ncommand = ${JSON.stringify(python)}\nargs = ["-m", "spt.server.mcp_server"]\nenv = { PYTHONPATH = ${JSON.stringify(base)} }`};
  }
  // 未能读取: how many and which files (each line ends with its reason).
  function issuesHTML(issues) {
    const shown=issues.slice(0,8), rest=issues.length-shown.length;
    return `<div class="settings-row" id="settings-issues" tabindex="-1"><span>未能读取</span><div class="settings-value"><strong>${issues.length} 个文件</strong><ul class="issue-list">${shown.map((issue)=>`<li>${esc(issue)}</li>`).join('')}</ul>${rest>0?`<small>还有 ${rest} 个没列出。</small>`:''}</div></div>`;
  }
  function librarySettingsHTML() {
    const counts=state.health?.counts||{};
    const issues=asArray(state.health?.issues);
    const rows=[['作品','work'],['提示词','prompt'],['素材','material'],['记录','record']].map(([label,key])=>`<span class="settings-count"><strong>${Number(key==='work'?counts.works:counts[key])||0}</strong>${label}</span>`).join('');
    const root=state.health?.spt_root||'<SPT 文件夹>/spt';
    // The snippet names its own file, so no instruction line is needed next to it.
    const {cli,mcp,codex}=agentCommands(root,state.health?.platform);
    return `<section class="panel settings-section" aria-labelledby="settings-library"><h2 class="panel-title" id="settings-library">资产库</h2><div class="settings-row"><span>已收录</span><div class="settings-value settings-counts">${rows}</div></div><div class="settings-row"><span>放置规则</span><div class="settings-value">作品放 <code>工作区/&lt;专业&gt;/&lt;日期-客户-主题&gt;/</code>，完整规则见 <code>spt/AGENTS.md</code></div></div>${issues.length?issuesHTML(issues):''}</section>${skillsSettingsHTML()}<section class="panel settings-section" aria-labelledby="settings-agents"><details class="settings-advanced"><summary><h2 class="panel-title" id="settings-agents">Agent 接入</h2></summary><div class="settings-row"><span>命令行</span><div class="settings-value"><pre class="code-block">${esc(cli)}</pre><button type="button" class="button small" data-copy-text="${esc(cli)}">${icon('copy')}复制</button></div></div><div class="settings-row"><span>Claude Code</span><div class="settings-value"><pre class="code-block">${esc(mcp)}</pre><button type="button" class="button small" data-copy-text="${esc(mcp)}">${icon('copy')}复制</button></div></div><div class="settings-row"><span>Codex</span><div class="settings-value"><pre class="code-block">${esc(codex)}</pre><button type="button" class="button small" data-copy-text="${esc(codex)}">${icon('copy')}复制</button></div></div></details></section>`;
  }
  // 设置 › Skills: one row per source (Claude, Codex, 库内, outside folders) with its count and folder;
  // the list itself is its own page (SKILLS_HASH). Repainted alone when the library index arrives.
  const homePath=(path)=>String(path||'').replace(/^\/Users\/[^/]+(?=\/|$)/,'~');
  function skillsSettingsHTML() { return `<section class="panel settings-section" id="settings-skills-panel" aria-labelledby="settings-skills">${skillsPanelHTML()}</section>`; }
  function skillsPanelHTML() {
    const ready=libraryReady()&&!!state.libraryIndex;
    const head=`<div class="panel-head"><h2 class="panel-title" id="settings-skills">Skills</h2>${ready?`<a class="text-action" href="${SKILLS_HASH}">查看全部 ${icon('caret-right')}</a>`:''}</div>`;
    let body;
    if(!state.health)body=`<p class="small-empty">${state.error?'连不上本机服务':'读取中'}</p>`;
    else if(!libraryReady())body='<p class="small-empty">后台服务还是旧版本，重启电脑后就能看到 Skills。</p>';
    else if(!state.libraryIndex)body=`<p class="small-empty">${state.libraryIndexFailed?'Skills 没能读取':'读取中'}</p>`;
    else{
      const entry=state.libraryIndex.kinds?.skill;
      const groups=library.skillGroups(entry?.sections,state.health.skill_roots,deps.workspace());
      body=groups.length?groups.map((group)=>`<div class="settings-row"><span>${esc(group.name)}</span><div class="settings-value skill-source"><strong>${group.count}</strong>${group.path?`<code title="${esc(group.path)}">${esc(homePath(group.path))}</code>`:''}</div></div>`).join(''):'<p class="small-empty">还没有 Skills</p>';
    }
    return head+body;
  }
  // A handle can be a profile link (rednote): show the account name instead of a cut-off URL.
  function handleIsLink(handle) { return /^(https?:)?\/\/|^www\.|\.com\//i.test(String(handle||'')); }
  function handleLabel(account) {
    const handle=String(account.handle||'').trim();
    if(handle&&!handleIsLink(handle))return handle.startsWith('@')?handle:`@${handle}`;
    return [account.name||account.brand,account.platform_label].filter(Boolean).join(' · ');
  }
  function renderPublish() {
    // 普通 #publish 保留官方后台账号卡；队列是显式子页，作品详情可直接带 work_id 进入。
    const params = new URLSearchParams(location.hash.split('?')[1] || '');
    if (window.SPTPublishQueue && (params.get('view') === 'queue' || params.has('work_id'))) { window.SPTPublishQueue.render($('#view')); return; }
    const accountEntry=toolURL('accounts');
    const accounts=asArray(state.dashboard?.accounts);
    const groups=[];for(const account of accounts){let group=groups.find((item)=>item.id===(account.brand_id||account.brand));if(!group){group={id:account.brand_id||account.brand,brand:account.brand||'未命名客户',accounts:[]};groups.push(group);}group.accounts.push(account);}
    // Two accounts of one client on the same platform: the title carries the handle, so the line under it is not repeated.
    const cardHTML=(account)=>{const title=dashboard.accountLabel(account,accounts,deps), sub=handleLabel(account), repeated=sub.replace(/^@/,'').split(' · ').every((part)=>title.includes(part));return`<section class="panel publish-account"><div class="post-heading">${dashboard.platformHTML(account,deps)}<div><h2>${esc(title)}</h2>${repeated?'':`<span class="source-caption"${handleIsLink(account.handle)?` title="${esc(account.handle)}"`:''}>${esc(sub)}</span>`}</div></div><div class="publish-account-actions">${dashboard.accountBackendHTML(account,state,deps)}${safeExternalURL(account.profile_url)&&(account.readonly||!account.legacy_account_id)?`<a class="button small" href="${esc(safeExternalURL(account.profile_url))}" target="_blank" rel="noopener noreferrer">公开页面</a>`:''}${account.readonly?'':accountEntry?`<a class="button small" href="${esc(account.legacy_account_id?accountEntry:toolURL('accounts','',{client:account.brand,platform:account.platform,handle:account.handle||account.profile_url||''}))}">${account.legacy_account_id?'账号档案':'添加账号'}</a>`:''}</div></section>`;};
    const metaCard=(group)=>{const meta=dashboard.metaSuiteAccount(group.accounts);if(!meta)return '';return `<section class="panel publish-account publish-meta"><div class="post-heading"><span class="meta-mark large" aria-hidden="true"></span><div><h2>Meta Business Suite</h2><span class="source-caption">Instagram · Facebook</span></div></div><div class="publish-account-actions">${dashboard.metaSuiteHTML(group.accounts,state,deps)}</div></section>`;};
    let body;
    if(!state.dashboard&&(state.dashboardLoading||!state.health&&!state.dashboardError))body='<div class="publish-grid" aria-busy="true" aria-label="正在读取账号"><div class="skeleton skeleton-card"></div><div class="skeleton skeleton-card"></div><div class="skeleton skeleton-card"></div></div>';
    else if(!state.dashboard&&state.dashboardError)body=`<div class="empty-state">${icon('warning-circle')}<h2>账号资料没能读取</h2><p class="error-detail">${esc(state.dashboardError)}</p><button type="button" class="button primary" data-action="retry">重新连接</button></div>`;
    else if(!groups.length)body=`<div class="empty-state">${icon('desktop')}<h2>还没有账号资料</h2>${accountEntry?`<a class="button primary" href="${esc(accountEntry)}">打开账号档案</a>`:''}</div>`;
    else body=groups.map((group)=>`<section class="publish-client"><div class="account-group-header"><span class="client-name">${esc(group.brand)}</span><span class="client-meta">${group.accounts.length} 个平台</span>${accountEntry?`<a class="text-action" href="${esc(accountEntry)}">账号档案 ${icon('caret-right')}</a>`:''}</div><div class="publish-grid">${metaCard(group)}${group.accounts.map(cardHTML).join('')}</div></section>`).join('');
    queueMicrotask(()=>stripEdges($('#view .subtabs')));
    $('#view').innerHTML=`${subtabsHTML('')}<section class="publish-page"><header class="page-heading"><div><h1 tabindex="-1">${ENTRIES_NAME}</h1></div><div class="page-controls"><a class="button small" href="#publish?view=queue">发布队列</a></div></header>${body}</section>`;
  }

  // -- detail dialog: works, items, guide ------------------------------------------------
  const loadingHeader=(title,text)=>`<header class="detail-header"><h2 id="detail-title">${esc(title)}</h2><button type="button" class="icon-button" data-action="close-detail" aria-label="关闭详情">${icon('x')}</button></header><div class="empty-state"><span class="spinner" aria-hidden="true"></span><p>${esc(text)}</p></div>`;
  function setDetailReturn(trigger) { state.returnFocus=trigger||returnTarget();state.returnKey=keyOf(state.returnFocus);state.detailStack=[]; }
  // Prev/next walk the list the detail was opened from: the filtered works (or all of them), or the loaded items.
  function detailList() {
    if(state.detailKind==='item')return state.items;
    return state.works.some((work)=>work.id===state.detailId)?state.works:state.allWorks;
  }
  function detailNav() {
    const id=state.detailKind==='item'?state.item?.id:state.detailId;
    const {prev,next}=neighborIds(detailList().map((entry)=>entry.id),id);
    return {prev:!!prev,next:!!next,back:state.detailStack.length>0};
  }
  // Same markup as library.itemDetailHTML's nav, so both detail headers look alike.
  function stepButtonsHTML(nav) {
    return `<button type="button" class="icon-button detail-step" data-detail-step="-1" aria-label="上一个"${nav.prev?'':' disabled'}>${icon('caret-left')}</button><button type="button" class="icon-button detail-step" data-detail-step="1" aria-label="下一个"${nav.next?'':' disabled'}>${icon('caret-right')}</button>`;
  }
  function backHTML() { return `<button type="button" class="icon-button detail-back" data-detail-back aria-label="返回上一个">${icon('arrow-left')}</button>`; }
  function focusDetail(selector) {
    const target=selector?$(selector,dialog):null;
    (target&&!target.disabled?target:$('[data-action="close-detail"]',dialog))?.focus({preventScroll:true});
  }
  function stepDetail(step) {
    if(!dialog.open||!['work','item'].includes(state.detailKind))return;
    const id=state.detailKind==='item'?state.item?.id:state.detailId;
    const near=neighborIds(detailList().map((entry)=>entry.id),id), target=step<0?near.prev:near.next;
    if(!target)return;
    const focus=`[data-detail-step="${step<0?-1:1}"]`;
    if(state.detailKind==='item')openItem(target,null,{step:true,focus});else openWork(target,null,{step:true,focus});
  }
  // Going into a linked work remembers where it came from; 返回 lands back on the link that was used.
  function pushDetail(trigger) {
    const focus=trigger&&dialog.contains(trigger)?keyOf(trigger):'';
    if(state.detailKind==='work'&&state.detail)state.detailStack.push({kind:'work',id:state.detailId,title:state.detail.work.title,focus});
    else if(state.detailKind==='item'&&state.item)state.detailStack.push({kind:'item',id:state.item.id,title:state.item.title,focus});
  }
  function backDetail() {
    const entry=state.detailStack.pop();if(!entry)return;
    if(entry.kind==='item')openItem(entry.id,null,{drill:true,focus:entry.focus});else openWork(entry.id,null,{drill:true,focus:entry.focus});
  }
  async function openWork(id, trigger, { step = false, drill = false, focus = '' } = {}) {
    const requestId = ++state.detailRequestId;
    if (!step && !drill) setDetailReturn(trigger);
    const previousTab = state.detailTab;
    state.detailKind = 'work';
    state.detailId = id;
    state.detailFocus = { attr: 'data-work', id };
    if (!step) {
      state.detail = null; state.item = null; state.version = ''; state.preview = null;
      $('#detail-content').innerHTML = loadingHeader('作品详情', '正在读取作品');
    }
    $('#detail-content').setAttribute('aria-busy', 'true');
    openModal(dialog);
    try {
      const data = await api(`/api/works/${encodeURIComponent(id)}`);
      if (requestId !== state.detailRequestId || !dialog.open) return;
      if (!data.work) throw new Error('作品详情格式不匹配。');
      state.detail = data; state.item = null;
      const versions = asArray(data.versions);
      const current = versions.find((version) => version.is_current || version.name === data.work.current_version);
      state.version = current?.name || versions.find((version) => version.name === data.work.latest_version)?.name || versions.at(-1)?.name || '';
      const finals = asArray(data.finals || data.work.finals);
      const preferred = finals.find(isVideo) || finals.find(isImage);
      state.preview = data.work.media_match === 'mismatch' ? null : preferred || null;
      // Open on the first tab that has something; stepping keeps the tab when the next work has it too.
      const counts = detailCounts();
      state.detailTab = step && counts[previousTab] ? previousTab : DETAIL_TABS.find(([key]) => counts[key] > 0)?.[0] || 'versions';
      renderDetail(focus);
    } catch (error) {
      if (requestId !== state.detailRequestId || !dialog.open) return;
      $('#detail-content').innerHTML = `<header class="detail-header"><h2 id="detail-title">作品详情</h2><button type="button" class="icon-button" data-action="close-detail" aria-label="关闭详情">${icon('x')}</button></header><div class="empty-state">${icon('warning-circle')}<h2>详情没能读取</h2><p>${esc(error.message)}</p><button type="button" class="button primary" data-action="retry-detail">重试</button></div>`;
      focusDetail('[data-action="retry-detail"]');
    } finally {
      if (requestId === state.detailRequestId) $('#detail-content').removeAttribute('aria-busy');
    }
  }
  function currentVersion() { return asArray(state.detail?.versions).find((version) => version.name === state.version); }
  function detailCounts() {
    const data = state.detail, records = splitRecords(data.records);
    return { versions: asArray(data.versions).length + promptDocuments().length, captions: Object.keys(data.package || {}).length, records: records.current.length + (workDocument('记录.md') ? 1 : 0), files: asArray(data.finals || data.work.finals).length, metrics: asArray(data.metrics?.observations).length + asArray(data.metrics?.analyses).length };
  }
  function renderDetail(focus = '') {
    const data = state.detail, work = data.work, counts = detailCounts(), nav = detailNav();
    $('#detail-content').innerHTML = `<header class="detail-header">${nav.back ? backHTML() : ''}<div class="detail-heading"><h2 id="detail-title">${esc(work.title)}</h2><div class="detail-meta">${clientTag(work.client) || `<span>${esc(work.client || work.category)}</span>`}<span>${esc(work.date || '')}</span>${statusHTML(work)}${versionLabel(work) ? `<span>${esc(versionLabel(work))}</span>` : ''}${work.tool ? `<span>${esc(work.tool)}</span>` : ''}</div>${work.note ? `<p class="work-note">${esc(work.note)}</p>` : ''}</div>${stepButtonsHTML(nav)}<button type="button" class="icon-button" data-action="close-detail" aria-label="关闭详情">${icon('x')}</button></header><div class="detail-columns"><div class="preview-pane"><div id="preview-content"></div>${workIssuesHTML(work)}${basisHTML(work)}<div class="detail-actions"><button type="button" class="button primary" data-open-publish-work="${esc(work.id)}">发布</button><button type="button" class="button danger" data-work-trash="${esc(work.id)}">移到废纸篓</button></div></div><div class="detail-right"><div class="detail-tabs" role="tablist" aria-label="作品资料">${DETAIL_TABS.map(([key, label]) => `<button type="button" class="detail-tab${counts[key] ? '' : ' is-empty'}" id="tab-${key}" role="tab" aria-selected="${state.detailTab === key}" aria-controls="detail-panel" tabindex="${state.detailTab === key ? 0 : -1}" data-tab="${key}">${label}<small>${counts[key]}</small></button>`).join('')}</div><div class="detail-panel" id="detail-panel" role="tabpanel" aria-labelledby="tab-${state.detailTab}" tabindex="0"></div></div></div>`;
    renderPreview();
    renderDetailPanel();
    focusDetail(focus);
  }
  function previewCandidates() {
    const detail = state.detail;
    const versions = asArray(detail?.versions);
    const files = [...asArray(detail?.finals || detail?.work.finals), ...versions.flatMap((version) => [...asArray(version.media), ...asArray(version.returns), ...asArray(version.references)])];
    return files.filter((file, index) => (isVideo(file) || isImage(file)) && files.findIndex((other) => pathOf(other) === pathOf(file)) === index);
  }
  function renderPreview() {
    const work = state.detail.work, file = state.preview;
    let preview;
    if (file && fileURL(work.id, file)) {
      const url = esc(fileURL(work.id, file));
      const poster = safeLocalURL(work.cover) ? ` poster="${esc(safeLocalURL(work.cover))}"` : '';
      preview = isVideo(file) ? `<video controls preload="metadata" playsinline${poster} aria-label="${esc(nameOf(file))}" src="${url}"></video>` : `<img src="${url}" alt="${esc(nameOf(file))}">`;
    } else if (safeLocalURL(work.cover)) {
      preview = `<img src="${esc(safeLocalURL(work.cover))}" alt="${esc(work.title)}封面">`;
    } else preview = `<div class="preview-empty">${icon('film-strip')}<p>暂无可预览的封面</p></div>`;
    // One control says what is shown and switches it: the picker's value carries the name and size
    // (a separate caption above it only repeated the same words).
    const candidates = previewCandidates();
    const chosen = file ? candidates.findIndex((item) => pathOf(item) === pathOf(file)) : -1;
    const sized = (item) => `${nameOf(item)}${item?.size ? ` · ${formatSize(item.size)}` : ''}`;
    const picker = candidates.length ? listbox({ id: 'preview-select', className: 'preview-select', label: '选择预览文件', value: chosen >= 0 ? String(chosen) : '', options: [['', '作品封面'], ...candidates.map((item, index) => [String(index), `${sized(item)}${work.media_match === 'mismatch' && asArray(state.detail.finals).some((final) => pathOf(final) === pathOf(item)) ? '（和发布记录里的不一样）' : ''}`])] }) : '';
    $('#preview-content').innerHTML = `<div class="preview-stage">${preview}</div>${picker}`;
  }
  // The index words these for agents; the detail says them plainly.
  const PLAIN_ISSUES = {
    '本地成片与源记录当前采用版本的SHA-256不一致；不可据此重发': '本地成片和发布记录里的不一样，重发前先核对一下。',
    '源发布记录存在当前成品指纹，但本地未发现根目录成品': '发布记录里有成片，但作品文件夹里没找到成片文件。',
    '大文件未全量计算指纹，当前发布版本与本地成片尚未核对': '成片文件太大，还没核对它和发布出去的是不是同一个。',
    '发布状态来自源记录，平台未核': '记录里写已发布（平台上还没核对）。',
    '封面缩略图生成失败；原图未修改': '封面小图没做出来，原图没动。',
    '封面抽帧失败；原视频未修改': '没能从视频里取出封面，原视频没动。',
    '未找到ffmpeg，封面缓存暂不可用': '这台电脑没有 ffmpeg，视频封面暂时做不出来。',
  };
  // (Not issuesHTML: that name belongs to 设置's 未能读取 list, and a second declaration would replace it.)
  function workIssuesHTML(work) {
    const issues = asArray(work.issues).map((issue) => PLAIN_ISSUES[issue] || issue);
    if (work.media_match === 'mismatch' && !issues.some((issue) => /不匹配|不同|不一致|不一样/.test(issue))) issues.unshift('本地成片和发布记录里的不一样，用之前先核对一下。');
    if (work.status === 'published' && !work.verified) issues.push('记录里写已发布（平台上还没核对）。');
    return issues.length ? `<div class="issue-message">${icon('warning-circle')}<div>${[...new Set(issues)].map((issue) => `<p>${esc(issue)}</p>`).join('')}</div></div>` : '';
  }
  function basisHTML(work) {
    const basis = [...asArray(work.status_basis), ...asArray(work.selection_basis)];
    if (!basis.length) return '';
    return `<details class="evidence"><summary>这些状态是怎么来的</summary><div class="evidence-body">${basis.map((item) => `<div class="evidence-item">${esc(typeof item === 'string' ? item : item.text)}${item.source ? `<small>${esc(item.source)}</small>` : ''}</div>`).join('')}</div></details>`;
  }
  function renderDetailPanel() {
    const renderers = { versions: versionsHTML, captions: captionsHTML, records: recordsHTML, files: filesHTML, metrics: metricsPanelHTML };
    $('#detail-panel').setAttribute('aria-labelledby', `tab-${state.detailTab}`);
    $('#detail-panel').innerHTML = renderers[state.detailTab]();
    $$('.detail-tab').forEach((button) => {
      const selected = button.dataset.tab === state.detailTab;
      button.setAttribute('aria-selected', String(selected));
      button.tabIndex = selected ? 0 : -1;
    });
  }
  // 数据 tab: what the workspace's 数据/ folder recorded for this work (dashboard.workMetricsHTML draws it).
  function metricsPanelHTML() { return dashboard.workMetricsHTML(state.detail?.metrics, deps); }
  function workDocument(name) { return asArray(state.detail?.source_documents).find((doc) => doc.name === name); }
  function promptDocuments() { return asArray(state.detail?.source_documents).filter((doc) => /^提示词.*\.(md|txt)$/.test(doc.name)); }
  function promptDocumentsHTML() {
    const docs = promptDocuments();
    if (!docs.length) return '';
    return `<section class="prompt-documents"><h3>提示词文档<span class="verification"> ${docs.length}</span></h3>${docs.map((doc) => `<details class="source-document" ${docs.length === 1 ? 'open' : ''}><summary><span>${esc(doc.name)}</span><button type="button" class="button small" data-copy="doc" data-doc="${esc(doc.name)}">${icon('copy')}复制</button></summary><pre class="document-text">${esc(doc.text)}</pre></details>`).join('')}</section>`;
  }
  function versionsHTML() {
    const versions = asArray(state.detail.versions), work = state.detail.work;
    if (!versions.length) return promptDocumentsHTML() || `<p class="small-empty">这件作品还没有存版本或提示词。${work.current_version ? `记录里写定稿是 ${esc(work.current_version)}，这一版没有存文件。` : ''}</p>`;
    const version = currentVersion() || versions[0];
    state.version = version.name;
    const missingCurrent = work.current_version && !versions.some((item) => item.name === work.current_version);
    const picker = listbox({ id: 'version-select', label: '选择版本', value: version.name, options: versions.map((item) => [item.name, `${item.name}${item.is_current || item.name === work.current_version ? ' · 定稿' : item.name === work.latest_version ? ' · 最新' : ''}`]) });
    // The picker already says 定稿 / 最新 next to each version: below it only the version's date.
    return `${missingCurrent ? `<p class="version-note">记录里写定稿是 <strong>${esc(work.current_version)}</strong>，这一版没有存文件。</p>` : ''}<div class="panel-heading">${picker}<button type="button" class="button small" data-copy="prompt" ${version.prompt ? '' : 'disabled'}>${icon('copy')}复制提示词</button></div>${version.created_at ? `<p class="version-note">${esc(readableTime(version.created_at))}</p>` : ''}${version.prompt ? `<pre class="prompt-text">${esc(version.prompt)}</pre>` : '<p class="small-empty">这一版没有存提示词。</p>'}${mediaSection('编号素材', version.media)}${mediaSection('生成结果', version.returns)}${mediaSection('参考素材', version.references)}${promptDocumentsHTML()}`;
  }
  function mediaSection(title, files) {
    const items = asArray(files);
    if (!items.length) return '';
    return `<section><h3>${title}<span class="verification"> ${items.length}</span></h3><div class="media-grid">${items.map((file) => `<button type="button" class="media-item" data-preview-path="${esc(pathOf(file))}" title="预览${esc(nameOf(file))}"><span class="media-thumb">${isImage(file) ? `<img src="${esc(fileURL(state.detail.work.id, file))}" alt="" loading="lazy">` : icon(isVideo(file) ? 'film-strip' : 'file-text')}</span><span>${esc(nameOf(file))}</span></button>`).join('')}</div></section>`;
  }
  function captionsHTML() {
    const captions = Object.entries(state.detail.package || {});
    if (!captions.length) return '<p class="small-empty">这件作品还没有平台文案。</p>';
    return captions.map(([platform, text]) => `<section class="caption-section"><div class="panel-heading"><h3>${esc(platformName(platform))}</h3><button type="button" class="button small" data-copy="caption" data-platform="${esc(platform)}">${icon('copy')}复制</button></div><pre class="caption-text">${esc(typeof text === 'string' ? text : text?.caption || text?.text || '')}</pre></section>`).join('');
  }
  function recordHTML(record) {
    const url = safeExternalURL(record.url);
    const verification = record.verified ? (record.verification_source === 'file' ? '记录里写着核对过' : '核对过') : '平台上还没核对';
    const detail = [record.account, record.published_at, record.source_heading].filter(Boolean).join(' · ');
    return `<div class="record-item"><div><div class="record-platform">${esc(platformName(record.platform))}<span class="verification ${record.verified ? '' : 'unverified'}">${verification}</span></div>${detail ? `<p class="record-evidence">${esc(detail)}</p>` : ''}${record.evidence ? `<p class="record-evidence">${esc(record.evidence)}</p>` : ''}</div>${url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer" aria-label="在平台查看${esc(platformName(record.platform))}原文">查看原文${icon('arrow-square-out')}</a>` : ''}</div>`;
  }
  function recordsHTML() {
    const { current, historical } = splitRecords(state.detail.records);
    const note = workDocument('记录.md');
    const noteHTML = note && library ? `<details class="source-document work-record" open><summary><span>制作记录 · 记录.md</span></summary><div class="md-body">${library.markdownHTML(note.text, esc)}</div></details>` : '';
    if (!current.length && !historical.length) return `${noteHTML}<p class="small-empty">这件作品还没有发布记录。</p>`;
    return `${noteHTML}<section><h3 class="records-heading">发布记录 <span class="verification">${current.length}</span></h3>${current.length ? current.map(recordHTML).join('') : '<p class="small-empty">现在没有在用的发布记录。</p>'}</section>${historical.length ? `<details class="history-records"><summary>撤下的和以前的记录 · ${historical.length}</summary><div>${historical.map(recordHTML).join('')}</div></details>` : ''}`;
  }
  function filesHTML() {
    const finals = asArray(state.detail.finals || state.detail.work.finals);
    const documents = asArray(state.detail.source_documents);
    const archives = asArray(state.detail.archive_links || state.detail.archive);
    return `<section><h3 class="records-heading">成品文件</h3>${finals.length ? finals.map((file) => `<div class="file-row">${icon(isVideo(file) ? 'film-strip' : isImage(file) ? 'image' : 'file-text')}<div class="file-name"><span>${esc(nameOf(file))}</span><small>${esc([formatSize(file.size)].filter(Boolean).join(' · '))}</small></div>${isVideo(file) || isImage(file) ? `<button type="button" class="button small" data-preview-path="${esc(pathOf(file))}">预览</button>` : `<a class="button small" href="${esc(fileURL(state.detail.work.id, file))}" download>下载</a>`}</div>`).join('') : '<p class="small-empty">还没有找到成品文件。</p>'}</section>${documents.length ? `<section><h3>源文档</h3>${documents.map((file) => `<details class="source-document"><summary>${esc(file.name)}</summary><pre class="document-text">${esc(file.text)}</pre></details>`).join('')}</section>` : ''}${archives.length ? `<section><h3>外部归档路径</h3>${archives.map((path) => `<p class="archive-path">${esc(typeof path === 'string' ? path : path.path || path.name)}</p>`).join('')}</section>` : ''}`;
  }
  async function copyContent(button) {
    let text = '';
    if (button.dataset.copy === 'prompt') text = currentVersion()?.prompt || '';
    if (button.dataset.copy === 'doc') text = workDocument(button.dataset.doc)?.text || '';
    if (button.dataset.copy === 'caption') {
      const caption = state.detail.package?.[button.dataset.platform];
      text = typeof caption === 'string' ? caption : caption?.caption || caption?.text || '';
    }
    await writeClipboard(text, button);
  }
  async function writeClipboard(text, button) {
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      const original = button.innerHTML;
      button.innerHTML = `${icon('check')}已复制`;
      setTimeout(() => { if (button.isConnected) button.innerHTML = original; }, 1600);
    } catch { notice('复制失败，请选中文字后手动复制。', { tone: 'error' }); }
  }
  function findItem(id) { return state.item?.id === id ? state.item : state.items.find((item) => item.id === id); }
  async function copyItem(button, body = false) {
    const id = body ? button.dataset.copyBody : button.dataset.copyItem;
    let item = findItem(id);
    if (body && !item?.body) {
      try { item = (await api(`/api/items/${encodeURIComponent(id)}`)).item; } catch (error) { notice(error.message, { tone: 'error' }); return; }
    }
    const text = body ? item?.body : library.copyText(item);
    if (button.classList.contains('item-copy')) {
      if (!text) return;
      try { await navigator.clipboard.writeText(text); button.classList.add('copied'); button.innerHTML = icon('check'); notice(`已复制：${item.title}`, { tone: 'success' }); setTimeout(() => { if (button.isConnected) { button.classList.remove('copied'); button.innerHTML = icon('copy'); } }, 1600); }
      catch { notice('复制失败，请打开详情手动复制。', { tone: 'error' }); }
      return;
    }
    await writeClipboard(text, button);
  }
  function flashCopied(button) {
    if (!button?.isConnected) return;
    button.classList.add('copied'); button.innerHTML = icon('check');
    setTimeout(() => { if (button.isConnected) { button.classList.remove('copied'); button.innerHTML = icon('copy'); } }, 1600);
  }
  // Write text that may still be loading. WebKit (the SPT app) only lets the clipboard be written during the
  // click itself, so a ClipboardItem takes the pending text; otherwise the text is awaited, then written.
  async function clipboardLater(pending) {
    const text = Promise.resolve(pending);
    if (window.ClipboardItem && navigator.clipboard?.write) {
      try {
        const blob = text.then((value) => { if (!value) throw new Error('empty'); return new Blob([value], { type: 'text/plain' }); });
        await navigator.clipboard.write([new ClipboardItem({ 'text/plain': blob })]);
        return;
      } catch { /* an older engine: fall back to writeText below */ }
    }
    const value = await text;
    if (!value) throw new Error('empty');
    await navigator.clipboard.writeText(value);
  }
  // Corner 复制 on a work card: the adopted prompt, else the caption (library.workCopy decides).
  const workCopies = new Map();
  function copyWork(button) {
    const id = button.dataset.copyWork;
    const work = [...state.works, ...state.allWorks].find((entry) => entry.id === id);
    const key = `${id}@${work?.updated_at || ''}`;
    let copy = workCopies.get(key);
    if (!copy) {
      copy = api(`/api/works/${encodeURIComponent(id)}`).then((data) => library.workCopy(data, platformName));
      workCopies.set(key, copy);
      copy.catch(() => workCopies.delete(key));
    }
    clipboardLater(copy.then((result) => result.text)).then(async () => {
      const { label } = await copy;
      flashCopied(button);
      notice(`已复制：${work?.title || '作品'} · ${label}`, { tone: 'success' });
    }).catch(async () => {
      const result = await copy.catch(() => null);
      if (result && !result.text) notice('这件作品还没有提示词或文案可以复制。', { tone: 'warn' });
      else notice('复制失败，请打开作品手动复制。', { tone: 'error' });
    });
  }
  function setCover(value, menu) {
    state.cover = COVER_MODES.includes(value) ? value : 'square';
    savePreference('cover', state.cover);
    renderWorks();
    if (menu) $('summary', menu)?.focus({ preventScroll: true });
  }
  // The SPT app asks where to save an export (a save panel); a browser puts it in its download folder.
  function exportNotice() {
    return window.mediaNativeAvailable === true || hasAccountBridge(window) ? '正在导出：请在弹出的窗口里选好保存位置。' : '正在导出：文件会存到浏览器的下载位置。';
  }
  async function openItem(id, trigger, { step = false, drill = false, focus = '' } = {}) {
    const requestId = ++state.detailRequestId;
    if (!step && !drill) setDetailReturn(trigger);
    state.detailKind = 'item';
    state.detailFocus = { attr: 'data-item', id };
    if (!step) {
      state.detail = null;
      state.item = findItem(id) || null;
      $('#detail-content').innerHTML = loadingHeader(state.item?.title || '条目详情', '正在读取');
    }
    $('#detail-content').setAttribute('aria-busy', 'true');
    openModal(dialog);
    try {
      const data = await api(`/api/items/${encodeURIComponent(id)}`);
      if (requestId !== state.detailRequestId || !dialog.open) return;
      state.detail = null; state.item = data.item;
      $('#detail-content').innerHTML = library.itemDetailHTML(data.item, deps, detailNav());
      focusDetail(focus);
    } catch (error) {
      if (requestId !== state.detailRequestId || !dialog.open) return;
      $('#detail-content').innerHTML = `<header class="detail-header"><h2 id="detail-title">条目详情</h2><button type="button" class="icon-button" data-action="close-detail" aria-label="关闭详情">${icon('x')}</button></header><div class="empty-state">${icon('warning-circle')}<h2>详情没能读取</h2><p>${esc(error.message)}</p></div>`;
      focusDetail('');
    } finally {
      if (requestId === state.detailRequestId) $('#detail-content').removeAttribute('aria-busy');
    }
  }
  async function openGuide(trigger) {
    const requestId = ++state.detailRequestId;
    setDetailReturn(trigger);
    state.detail = null;
    state.item = null;
    state.detailKind = 'guide';
    state.detailFocus = null;
    const header = `<header class="detail-header"><div class="detail-heading"><h2 id="detail-title">存放说明</h2></div><button type="button" class="icon-button" data-action="close-detail" aria-label="关闭">${icon('x')}</button></header>`;
    $('#detail-content').innerHTML = `${header}<div class="empty-state"><span class="spinner" aria-hidden="true"></span><p>正在读取</p></div>`;
    openModal(dialog);
    try {
      const data = await api('/api/guide');
      if (requestId !== state.detailRequestId || !dialog.open) return;
      const source = data.path ? `<p class="source-caption">${esc(data.path)}</p>` : '';
      $('#detail-content').innerHTML = `${header}<div class="item-detail guide-body"><div class="md-body">${library.markdownHTML(String(data.markdown || '还没有存放说明。').replace(/^#\s+[^\n]*\n+/, ''), esc)}</div>${source}</div>`;
      focusDetail('');
    } catch (error) {
      if (requestId !== state.detailRequestId || !dialog.open) return;
      $('#detail-content').innerHTML = `${header}<div class="empty-state">${icon('warning-circle')}<h2>说明没能读取</h2><p>${esc(error.message)}</p></div>`;
    }
  }
  function selectCategory(category) {
    state.category=category;
    if(state.route!=='works'){history.replaceState(null,'','#works');setRoute('works');showLibrary();setTitle();}
    syncWorksHash();loadWorks();updateShell();loadMatchCounts();
  }
  // Keep the address in step with the filters (no history entry): a reload lands on the same view.
  function syncWorksHash() {
    if(state.route!=='works'||state.kind==='skill')return;
    const hash=worksHash({client:state.client,category:state.category,status:state.status});
    if(location.hash!==hash)history.replaceState(null,'',hash);
  }
  // A client chip, or a block's 全部 N: that client's works (or items), flat; '' is 全部, the overview. The 专业 or group
  // chosen under another client is dropped; the status stays. Nothing is fetched unless the server-side filter changed.
  function selectClient(code) {
    const client=String(code||'');
    const refetch=!!state.category||!!state.section;
    state.client=client;state.category='';state.section='';
    syncWorksHash();renderFolders();
    if(refetch){loadCurrentLibrary();loadMatchCounts();}else renderWorks();
    $(`#category-nav [data-client="${CSS.escape(client)}"]`)?.focus({preventScroll:true});
  }
  function clearFilters() {
    state.query='';state.status='';state.category='';state.section='';state.client='';
    $('#search').value='';setControl('status-filter','');syncWorksHash();renderFolders();loadCurrentLibrary();loadMatchCounts();
  }
  // Palette 「在资产库搜索」 / 「查看全部」: a fresh search with filters cleared, on the kind asked for
  // (else the open kind if it has hits, else the first kind that has some).
  function searchLibrary(query,kind='') {
    if(libraryReady()&&library.isKind(kind)&&kind!==state.libraryKind){state.libraryKind=kind;savePreference('kind',kind);}
    useKind(state.libraryKind);
    state.query=query;state.category='';state.section='';state.status='';state.client='';
    // The page is rebuilt below: show the spinner, not the previous search's cards.
    if(state.kind==='work'||!libraryReady())state.loading=true;else state.itemsLoading=true;
    go('#works');
    setControl('status-filter','');
    renderFolders();
    loadCurrentLibrary();loadMatchCounts();
    const search=$('#search');if(search){search.value=query;search.focus();}
  }
  // The Skills page (设置 › 查看全部 Skills, or ⌘K's 查看全部 … Skills), optionally searching.
  function openSkills(query='') {
    useKind('skill');
    state.query=query;state.section='';
    if(libraryReady())state.itemsLoading=true;
    go(SKILLS_HASH);
    renderFolders();loadCurrentLibrary();
    const search=$('#search');if(search){search.value=query;if(query)search.focus();}
  }
  function findPost(id) { return asArray(state.dashboard?.posts).find((post)=>post.id===id); }
  function openPost(id) {
    const post=findPost(id);if(!post)return;
    const account=asArray(state.dashboard?.accounts).find((item)=>item.id===post.account_id);
    state.postReturnFocus=returnTarget();state.postReturnKey=keyOf(state.postReturnFocus);
    $('#post-dialog-content').innerHTML=dashboard.postDialogHTML(post,account,state,deps);
    openModal(postDialog);
    $('[data-action="close-post"]',postDialog).focus();
  }
  async function copyPost(button) {
    const post=findPost(button.dataset.postCopy);
    if(!post?.caption)return;
    try{await navigator.clipboard.writeText(post.caption);notice('文案已复制',{tone:'success'});}catch{notice('复制失败，请选中文字后手动复制。',{tone:'error'});}
  }
  function selectAccount(id) {state.accountId=id;state.postId='';renderCurrent();$(`[data-account="${CSS.escape(id)}"]`)?.focus({preventScroll:true});}
  function openNativeAccount(id, target = '') {
    if (state.openingAccountId) return;
    const account = asArray(state.dashboard?.accounts).find((item) => item.id === id);
    state.openingAccountId = id;
    renderCurrent();
    const result = requestAccountOpen(account, window, target);
    if (result.error) {
      state.openingAccountId = null;
      renderCurrent();
      notice(result.error, { tone: 'error' });
      return;
    }
    clearTimeout(accountOpenTimer);
    accountOpenTimer = setTimeout(() => {
      if (!state.openingAccountId) return;
      state.openingAccountId = null;
      renderCurrent();
      notice('未收到后台打开结果，请重试。', { tone: 'warn' });
    }, 10000);
  }
  function setAnalyticsView(value) { state.analyticsView=value==='table'?'table':'chart';savePreference('analyticsView',state.analyticsView);renderCurrent(); }
  function dismissWelcome() { state.welcomeDismissed=true;savePreference('welcome-dismissed','1');renderCurrent();focusPage(); }

  // -- ⌘K command palette ------------------------------------------------------------------
  function paletteCommands() {
    const dark=document.documentElement.dataset.theme!=='light';
    const skills=state.route==='works'&&state.kind==='skill';
    // A hint only where it tells something the label does not: the current page, or where Skills now lives.
    const commands=PAGES.map(([key,label,iconName,keys])=>({group:'页面',label,icon:iconName,keys,hint:state.route===key&&!skills?'当前页':'',run:()=>go(`#${key}`)}));
    commands.push({group:'页面',label:'Skills',icon:'skill',keys:'skills 技能 claude codex 已安装',hint:skills?'当前页':'设置',run:()=>openSkills()});
    // Every tool the server has, the ⋯ ones included (a shared copy lists only 账号档案 and 数据导入).
    for(const name of ['accounts',...publishMore(shareMode()),'data'])if(toolURL(name))commands.push({group:name==='data'?'数据':'发布工具',label:TOOL_NAMES[name],icon:TOOL_ICONS[name],keys:name,hint:state.route==='tools'&&state.tool===name?'当前页':'',run:()=>go(toolURL(name))});
    commands.push({group:'动作',label:'新建便签',icon:'plus',keys:'new note 写 贴一张 便签',hint:'',run:()=>openNewNote()});
    commands.push({group:'动作',label:'刷新工作区',icon:'arrow-clockwise',keys:'refresh reload reindex 重新读取',hint:'',run:()=>refresh()});
    commands.push({group:'动作',label:dark?'换成白天':'换成夜灯',icon:dark?'sun':'moon',keys:'theme dark light 主题 切换 夜灯 白天 深色 浅色',hint:'',run:()=>setTheme(dark?'light':'dark')});
    if(clientGroupsSupported())commands.push({group:'动作',label:'整理客户',icon:'pencil',keys:'clients 客户 分组 整理 改名 颜色 名录',hint:'',run:()=>openClientsDialog(pal.returnFocus)});
    if(state.health?.capabilities?.guide===true)commands.push({group:'动作',label:'存放说明',icon:'info',keys:'guide help 帮助 使用说明',hint:'',run:()=>openGuide(pal.returnFocus)});
    return commands;
  }
  // Assets come from the server (every kind, notes too), grouped by kind. Typing waits 150 ms, a newer query
  // cancels the older request, and until the answer arrives the last results are narrowed locally.
  const PALETTE_LIMIT=5;
  function schedulePaletteSearch(query) {
    if(!query||!state.health||!library){clearTimeout(pal.timer);pal.controller?.abort();pal.searching='';return;}
    if(pal.results?.query===query){clearTimeout(pal.timer);if(pal.searching){pal.controller?.abort();pal.requestId+=1;pal.searching='';}return;}
    if(pal.searching===query)return;
    clearTimeout(pal.timer);
    pal.searching=query;
    pal.timer=setTimeout(()=>runPaletteSearch(query),150);
  }
  async function runPaletteSearch(query) {
    const requestId=++pal.requestId;
    pal.controller?.abort();
    pal.controller=new AbortController();
    try{
      const results=await searchAssets(query,pal.controller.signal);
      if(requestId!==pal.requestId)return;
      pal.results={query,...results};pal.error='';
    }catch(error){
      if(error.name==='AbortError'||requestId!==pal.requestId)return;
      pal.error=error.message;pal.errorQuery=query;
    }
    if(pal.searching===query)pal.searching='';
    if(palette?.open&&$('#palette-input').value.trim()===query)renderPalette(true);
  }
  // Where 「在资产库搜索」 lands: the open kind if it has hits, else the first kind that has some.
  function bestKind(results) {
    const current=library?.isKind(state.libraryKind)?state.libraryKind:'work';
    if(!results||!library)return current;
    const counts=library.countKinds(results);
    return counts[current]>0?current:library.KINDS.find((kind)=>counts[kind.key]>0)?.key||current;
  }
  async function openNoteFromSearch(ref) {
    go('#notes');
    if(!ref||!notesReady())return;
    const find=()=>findNote(ref.id,ref.rope)||findNote(ref.id);
    if(!find())await loadNotes();
    const note=find();
    if(!note){notice('这张便签找不到了，可能已经移走或撤下。',{tone:'warn'});return;}
    if(state.route!=='notes')return;
    // Focus its card first, so closing the note lands back on it.
    $(`.note[data-note="${CSS.escape(note.id)}"],.cal-chip[data-note="${CSS.escape(note.id)}"]`)?.focus({preventScroll:false});
    openNote(note.id,note.rope);
  }
  function paletteAsset(group,entry,header) {
    const base={key:`${group.key}:${entry.id}`,group:header,label:entry.title||'未命名',icon:group.icon};
    if(group.key==='work')return {...base,hint:paletteHint(entry,state.clients,'work'),run:()=>openWork(entry.id,pal.returnFocus)};
    if(group.key==='note'){const ref=library.noteRef(entry);return {...base,hint:entry.section||'',run:()=>openNoteFromSearch(ref)};}
    return {...base,hint:paletteHint(entry,state.clients,'item'),copy:library.promptLike(entry)?library.copyText(entry):'',run:()=>openItem(entry.id,pal.returnFocus)};
  }
  function paletteEntries(query) {
    const commands=paletteCommands().filter((command)=>!query||matchScore(query,command.label,command.keys)>0).map((command)=>({...command,key:`cmd:${command.group}:${command.label}`}));
    if(!query)return {entries:commands,status:'',none:false};
    const exact=pal.results?.query===query;
    const results=exact?pal.results:pal.results&&library?library.narrowResults(pal.results,query):null;
    const entries=[...commands];
    for(const group of results&&library?library.groupResults(results,query,PALETTE_LIMIT):[]){
      const header=exact?`${group.label} · ${group.total}`:group.label;
      for(const entry of group.entries)entries.push(paletteAsset(group,entry,header));
      if(exact&&group.total>group.entries.length){
        const what=`${group.unit}${/^[A-Za-z]/.test(group.label)?' ':''}${group.label}`;
        const run=group.key==='note'?()=>{state.notesQuery=query;go('#notes');}:group.key==='skill'?()=>openSkills(query):()=>searchLibrary(query,group.key);
        entries.push({key:`more:${group.key}`,group:header,label:`查看全部 ${group.total} ${what}`,icon:'caret-right',hint:group.key==='note'?'便签':group.key==='skill'?'设置':'资产库',run});
      }
    }
    const pending=!exact&&!!pal.searching;
    const failed=!exact&&!pending&&pal.error&&pal.errorQuery===query;
    const none=entries.length===0&&exact;
    // 共 N 条 counts what the library page will list (notes live on their own page).
    const counts=exact&&library?library.countKinds(results):null;
    const total=counts?library.KINDS.reduce((sum,kind)=>sum+(counts[kind.key]||0),0):0;
    entries.push({key:'search',group:'',label:`在资产库搜索“${query}”`,icon:'magnifying-glass',hint:total?`共 ${total} 条`:'资产库',run:()=>searchLibrary(query,bestKind(results))});
    return {entries,status:pending?'正在搜索资产…':failed?`资产没能搜索：${pal.error}`:'',none};
  }
  // fromSearch: results just arrived. The best match gets the highlight, unless the user already moved it
  // (arrows or pointer): then it stays on the same entry.
  function renderPalette(fromSearch=false) {
    const input=$('#palette-input'), list=$('#palette-list'), empty=$('.palette-empty',palette);
    const query=input.value.trim();
    schedulePaletteSearch(query);
    const activeKey=pal.items[pal.active]?.key;
    const {entries,status,none}=paletteEntries(query);
    empty.hidden=!none;
    empty.textContent=none?`没有找到“${query}”的页面或资产。`:'';
    pal.items=entries;
    const kept=fromSearch&&pal.moved&&activeKey?entries.findIndex((entry)=>entry.key===activeKey):-1;
    pal.active=kept>=0?kept:fromSearch&&!pal.moved?0:Math.max(0,Math.min(pal.active,entries.length-1));
    list.setAttribute('aria-busy',String(!!status&&status.startsWith('正在')));
    let group='';
    list.innerHTML=entries.map((item,index)=>{
      const head=item.group&&item.group!==group?`<li class="palette-group" role="presentation">${esc(item.group)}</li>`:'';
      if(item.group)group=item.group;
      const copy=item.copy?`<span class="palette-copy">复制<span class="sr-only">（⌘ 回车）</span></span>`:'';
      const row=`${head}<li class="palette-item" role="option" id="palette-opt-${index}" data-index="${index}" aria-selected="${index===pal.active}">${icon(item.icon)}<span class="palette-label">${esc(item.label)}</span>${item.hint?`<span class="palette-hint">${esc(item.hint)}</span>`:''}${copy}</li>`;
      return item.key==='search'&&status?`<li class="palette-status" role="presentation">${esc(status)}</li>${row}`:row;
    }).join('');
    syncPalette();
  }
  function syncPalette() {
    const input=$('#palette-input');
    $$('.palette-item',palette).forEach((option)=>option.setAttribute('aria-selected',String(Number(option.dataset.index)===pal.active)));
    const current=document.getElementById(`palette-opt-${pal.active}`);
    if(current){input.setAttribute('aria-activedescendant',current.id);current.scrollIntoView({block:'nearest'});}
    else input.removeAttribute('aria-activedescendant');
  }
  // ⌘↩ (or the 复制 tag) copies a prompt-like result instead of opening it.
  function copyPalette(index) {
    const item=pal.items[index];if(!item?.copy)return false;
    const {copy,label}=item;
    closePalette();
    navigator.clipboard.writeText(copy).then(()=>notice(`已复制：${label}`,{tone:'success'}),()=>notice('复制失败，请打开详情手动复制。',{tone:'error'}));
    return true;
  }
  function movePalette(step) { if(!pal.items.length)return;pal.active=(pal.active+step+pal.items.length)%pal.items.length;pal.moved=true;syncPalette(); }
  function openPalette() {
    if(!palette)return;
    if(palette.open){closePalette();return;}
    pal.returnFocus=returnTarget();pal.returnKey=keyOf(pal.returnFocus);
    Listbox?.closeAll();
    $('#palette-input').value='';pal.active=0;pal.moved=false;pal.results=null;pal.error='';
    renderPalette();
    openModal(palette);
    $('#palette-input').focus();
  }
  function stopPaletteSearch() { clearTimeout(pal.timer);pal.controller?.abort();pal.requestId+=1;pal.searching=''; }
  function closePalette() {
    stopPaletteSearch();
    if(palette.open)palette.close();
    if(!restoreFocus(pal.returnFocus,pal.returnKey)&&palette.contains(document.activeElement))document.activeElement.blur();
  }
  function runPalette(index) {
    const item=pal.items[index];if(!item)return;
    closePalette();
    item.run();
  }
  // Tabs: arrows, Home and End move focus and select, wherever a [role=tablist] is.
  function rovingTabs(event) {
    const tab=event.target.closest?.('[role="tab"]'), list=tab?.closest('[role="tablist"]');
    if(!list||event.altKey||event.metaKey||event.ctrlKey)return false;
    const tabs=$$('[role="tab"]',list).filter((item)=>!item.disabled&&!item.hidden&&item.closest('[role="tablist"]')===list);
    const index=rovingIndex(event.key,tabs.indexOf(tab),tabs.length,list.getAttribute('aria-orientation')==='vertical');
    if(index<0)return false;
    event.preventDefault();
    const next=tabs[index], key=keyOf(next), scope=next.closest('dialog')||document;
    if(next.getAttribute('aria-selected')!=='true')next.click();
    ((key&&$(key,scope))||next).focus();
    return true;
  }

  Listbox?.bind(document);
  document.addEventListener('click',(event)=>{clicked=event.target.closest?.('button,a[href],[tabindex]:not([tabindex="-1"]),summary')||null;clickedAt=performance.now();},true);
  document.addEventListener('keydown',()=>{clicked=null;},true);
  // Skills groups: remember which were opened (Codex starts closed) or closed, so re-renders keep them.
  document.addEventListener('toggle',(event)=>{
    const group=event.target;if(!group?.matches?.('details.item-group')||!library)return;
    const name=group.dataset.group||'';
    if(library.collapsedByDefault(name))state.openGroups[group.open?'add':'delete'](name);
    else state.closedGroups[group.open?'delete':'add'](name);
  },true);
  document.addEventListener('click',(event)=>{
    // Small library menus (⋯ and 显示): one open at a time; a click elsewhere closes them.
    const inMenu=event.target.closest('.export-menu');
    $$('.export-menu[open]').forEach((menu)=>{if(menu!==inMenu)menu.open=false;});
    const newNote=event.target.closest('[data-note-new]');
    if(newNote){if(newNote.tagName==='A')event.preventDefault();openNewNote({text:newNote.dataset.noteText||'',rope:newNote.dataset.noteRope||newNote.dataset.noteNew||'',date:newNote.dataset.noteDate||''});return;}
    const noteCard=event.target.closest('.note[data-note]');
    if(noteCard&&!event.target.closest('button,a')){openNote(noteCard.dataset.note,noteCard.dataset.rope);return;}
    const calDay=event.target.closest('.cal-day');
    if(calDay&&!event.target.closest('button,a')){if(calDay.dataset.count||calDay.dataset.posts)openDay(calDay.dataset.date);else openNewNote({date:calDay.dataset.date});return;}
    const target=event.target.closest('button,a');if(!target)return;
    const action=target.dataset.action;
    // Choosing something in a menu closes it; an export link also says where the file goes.
    if(inMenu&&!target.closest('summary')){inMenu.open=false;if(target.tagName==='A'&&target.hasAttribute('download'))notice(exportNotice());}
    if(target.tagName==='BUTTON'&&target.closest('summary'))event.preventDefault();
    if(target.dataset.calNew)openNewNote({date:target.dataset.calNew});
    else if(target.dataset.calDay)openDay(target.dataset.calDay);
    else if(target.dataset.calShift)shiftNotesMonth(Number(target.dataset.calShift));
    else if(target.hasAttribute('data-cal-today'))shiftNotesMonth(0);
    else if(target.dataset.notesView)setNotesView(target.dataset.notesView);
    else if(target.hasAttribute('data-day-back')){state.noteDay=state.noteDay||target.dataset.dayBack;closeNoteDialog();}
    else if(target.hasAttribute('data-note-discard-keep'))keepEditing();
    else if(target.hasAttribute('data-note-discard'))leaveNoteEditor();
    else if(target.hasAttribute('data-note-conflict-load'))takeServerNote();
    else if(target.hasAttribute('data-note-conflict-keep'))keepMyNote();
    else if(target.hasAttribute('data-note-copy'))writeClipboard($('#note-text')?.value||'',target);
    else if(target.dataset.noteCopyCard)writeClipboard(findNote(target.dataset.noteCopyCard,target.dataset.rope)?.text||'',target);
    else if(target.dataset.noteRestore)restoreFromShelf(target);
    else if(target.dataset.note)openNote(target.dataset.note,target.dataset.rope);
    else if(target.hasAttribute('data-rope-new'))openRopeForm('');
    else if(target.dataset.ropeEdit)openRopeForm(target.dataset.ropeEdit);
    else if(target.dataset.noteRemove)removeNote(target.dataset.noteRemove,target.dataset.rope);
    else if(target.dataset.noteDelete)deleteNote(target.dataset.noteDelete,target.dataset.noteRope??target.dataset.rope??'',{shelf:target.hasAttribute('data-shelf-item')});
    else if(target.dataset.shelfClear)clearShelf(Number(target.dataset.shelfClear)||0);
    else if(target.dataset.workTrash)trashWork(target.dataset.workTrash);
    else if(target.dataset.openPublishWork){dialog.close();window.SPTPublishQueue?.openWork(target.dataset.openPublishWork);}
    else if(action==='organize-clients')openClientsDialog(inMenu?$('summary',inMenu):target);
    else if(target.dataset.ropeRemove)removeRope(target.dataset.ropeRemove);
    else if(action==='close-note')closeNoteDialog();
    else if(action==='reload-notes')loadNotes();
    else if(action==='reset-workspace')saveWorkspace('');
    else if(action==='choose-workspace'){try{window.webkit.messageHandlers.chooseWorkspace.postMessage({});}catch{notice('请直接填写文件夹路径。',{tone:'warn'});}}
    else if(action==='retry-connect')manualRetry(target);
    else if(action==='dismiss-welcome')dismissWelcome();
    else if(target.hasAttribute('data-client'))selectClient(target.dataset.client);
    else if(target.hasAttribute('data-category'))selectCategory(target.dataset.category);
    else if(target.dataset.kind)selectKind(target.dataset.kind);
    else if(target.hasAttribute('data-section'))selectSection(target.dataset.section);
    else if(target.hasAttribute('data-detail-step'))stepDetail(Number(target.dataset.detailStep));
    else if(target.hasAttribute('data-detail-back')||target.classList.contains('detail-back'))backDetail();
    else if(target.dataset.item)openItem(target.dataset.item,target);
    else if(target.dataset.copyItem)copyItem(target);
    else if(target.dataset.copyWork)copyWork(target);
    else if(target.dataset.coverMode)setCover(target.dataset.coverMode,inMenu);
    else if(target.dataset.copyBody)copyItem(target,true);
    else if(target.dataset.copyText)writeClipboard(target.dataset.copyText,target);
    else if(target.hasAttribute('data-work')){if(target.closest('#detail-dialog')){pushDetail(target);openWork(target.dataset.work,null,{drill:true,focus:'[data-detail-back]'});}else openWork(target.dataset.work,target);}
    else if(target.dataset.postWork){postDialog.close();openWork(target.dataset.postWork,state.postReturnFocus);}
    else if(target.dataset.openAccount)openNativeAccount(target.dataset.openAccount,target.dataset.openTarget||'');
    else if(target.dataset.account)selectAccount(target.dataset.account);
    else if(target.dataset.post){state.postId=target.dataset.post;renderCurrent();$(`[data-post="${CSS.escape(target.dataset.post)}"]`)?.focus({preventScroll:true});}
    else if(target.dataset.postOpen)openPost(target.dataset.postOpen);
    else if(target.dataset.postCopy)copyPost(target);
    else if(target.dataset.analyticsView)setAnalyticsView(target.dataset.analyticsView);
    else if(target.dataset.analyticsPlatform){state.analyticsPlatform=target.dataset.analyticsPlatform;renderCurrent();}
    else if(target.dataset.analyticsWindow){state.window=target.dataset.analyticsWindow;renderCurrent();}
    else if(target.dataset.analyticsContent){state.analyticsContent=target.dataset.analyticsContent==='tags'?'tags':'rank';state.analyticsTag='';renderCurrent();}
    else if(target.hasAttribute('data-analytics-tag')&&!target.hasAttribute('href')){state.analyticsContent='tags';state.analyticsTag=target.dataset.analyticsTag||'';renderCurrent();}
    else if(target.dataset.analyticsRange){state.analyticsRange=target.dataset.analyticsRange;renderCurrent();focusControl('analytics-range');}
    else if(target.dataset.intelTab){state.intelTab=target.dataset.intelTab;renderCurrent();}
    else if(target.dataset.intelPageTab){state.intelPageTab=target.dataset.intelPageTab;renderCurrent();}
    else if(target.dataset.theme)setTheme(target.dataset.theme);
    else if(target.dataset.densityChoice)setDensity(target.dataset.densityChoice);
    else if(target.dataset.motionChoice)setMotion(target.dataset.motionChoice);
    else if(target.dataset.copy)copyContent(target);
    else if(target.dataset.tab){state.detailTab=target.dataset.tab;renderDetailPanel();}
    else if(target.hasAttribute('data-preview-path')){state.preview=previewCandidates().find((file)=>pathOf(file)===target.dataset.previewPath)||null;renderPreview();}
    else if(target.id==='grid-view'||target.id==='list-view'){state.layout=target.id==='grid-view'?'grid':'list';savePreference('layout',state.layout);renderWorks();}
    else if(action==='retry')connect();
    else if(action==='refresh')refresh();
    else if(action==='read-metrics')readMetrics();
    else if(action==='global-search')openPalette();
    else if(action==='clear-filters')clearFilters();
    else if(action==='close-detail')dialog.close();
    else if(action==='open-guide')openGuide(inMenu?$('summary',inMenu):target);
    else if(action==='close-post')postDialog.close();
    else if(action==='retry-detail')openWork(state.detailId,state.returnFocus,{drill:true});
  });
  // Text fields: skip IME composition (pinyin in progress), act on the composed text.
  function onTextInput(target) {
    if(target.id==='search'){state.query=target.value;clearTimeout(searchTimer);searchTimer=setTimeout(()=>{loadCurrentLibrary();loadMatchCounts();},180);}
    else if(target.id==='notes-search'){state.notesQuery=target.value;filterNotes();}
    else if(target.id==='palette-input'){pal.active=0;pal.moved=false;renderPalette();}
  }
  document.addEventListener('input',(event)=>{if(!event.isComposing)onTextInput(event.target);});
  document.addEventListener('compositionend',(event)=>onTextInput(event.target));
  document.addEventListener('change',(event)=>{
    const {id,value}=event.target;
    if(event.target.name==='note-color'){paintNoteForm(value);return;}
    if(id==='note-rope'){const box=$('.note-rope-new',noteDialog);if(box){box.hidden=value!==notesUI?.NEW_ROPE;if(!box.hidden)$('#note-rope-new')?.focus();}return;}
    if(id==='status-filter'){state.status=value;syncWorksHash();loadWorks();loadMatchCounts();}
    else if(id==='version-select'){state.version=value;renderDetailPanel();focusControl('version-select');}
    else if(id==='preview-select'){state.preview=value===''?null:previewCandidates()[Number(value)]||null;renderPreview();focusControl('preview-select');}
    else if(id==='brand-filter'){state.brand=value;state.accountId='';state.postId='';state.analyticsPlatform='all';state.analyticsTag='';renderCurrent();focusControl('brand-filter');}
    else if(id==='account-metric'){state.accountMetric=value;renderCurrent();focusControl('account-metric');}
    else if(id==='analytics-metric'){state.analyticsMetric=value;renderCurrent();focusControl('analytics-metric');}
    else if(id==='analytics-range'){state.analyticsRange=value;renderCurrent();focusControl('analytics-range');}
    else if(id==='metric-window'){state.window=value;renderCurrent();focusControl('metric-window');}
  });
  document.addEventListener('submit',(event)=>{
    if(event.target.id==='note-form'){event.preventDefault();saveNote();}
    else if(event.target.id==='rope-form'){event.preventDefault();saveRope();}
    else if(event.target.id==='clients-form'){event.preventDefault();saveClients();}
    else if(event.target.id==='confirm-form'){event.preventDefault();settleConfirm(true);}
    else if(event.target.id==='workspace-form'){event.preventDefault();const value=$('#workspace-path').value.trim();if(!value){workspaceError('请填写文件夹路径');return;}if(value===(state.health?.workspace_path||'')){workspaceError('已经在用这个位置了');return;}saveWorkspace(value);}
  });
  document.addEventListener('keydown',(event)=>{
    if(event.defaultPrevented||event.isComposing||event.keyCode===229)return;
    const key=String(event.key||''), top=topModal();
    if((event.metaKey||event.ctrlKey)&&!event.altKey&&!event.shiftKey&&key.toLowerCase()==='k'){event.preventDefault();openPalette();return;}
    if(key==='Escape'){closeTopLayer(event);return;}
    if(top===noteDialog&&(event.metaKey||event.ctrlKey)&&key==='Enter'){event.preventDefault();($('#note-form')||$('#rope-form'))?.requestSubmit();return;}
    // ⌘⌫ in the note editor: the same 移到废纸篓 confirm as the 删除 button (only a saved note has one).
    if(top===noteDialog&&(event.metaKey||event.ctrlKey)&&!event.altKey&&!event.shiftKey&&key==='Backspace'){const button=$('[data-note-delete]',noteDialog);if(button){event.preventDefault();deleteNote(button.dataset.noteDelete,button.dataset.rope||'');return;}}
    if(top===clientsDialog&&(event.metaKey||event.ctrlKey)&&key==='Enter'){event.preventDefault();$('#clients-form')?.requestSubmit();return;}
    const note=!top&&event.target.matches?.('.note[data-note]')?event.target:null;
    if(note&&(key==='Enter'||key===' ')){event.preventDefault();openNote(note.dataset.note,note.dataset.rope);return;}
    if(note&&(event.metaKey||event.ctrlKey)&&!event.altKey&&!event.shiftKey&&key.toLowerCase()==='c'&&!String(getSelection()||'')){event.preventDefault();writeClipboard(findNote(note.dataset.note,note.dataset.rope)?.text||'',note);return;}
    if(note&&event.altKey&&!event.metaKey&&!event.ctrlKey&&ARROWS.includes(key)){event.preventDefault();nudgeNote(note,key==='ArrowUp'||key==='ArrowLeft'?-1:1);return;}
    if(rovingTabs(event))return;
    if(top===dialog&&(key==='ArrowLeft'||key==='ArrowRight')&&!event.altKey&&!event.metaKey&&!event.ctrlKey&&!event.shiftKey&&!isTypingTarget(event.target)&&!event.target.closest?.('video,audio,[data-listbox],[role="slider"]')){event.preventDefault();stepDetail(key==='ArrowLeft'?-1:1);}
  });
  if(palette){
    const input=$('#palette-input'), list=$('#palette-list');
    input.addEventListener('keydown',(event)=>{
      if(event.isComposing||event.keyCode===229)return;
      if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();movePalette(event.key==='ArrowDown'?1:-1);}
      else if(event.key==='Enter'){event.preventDefault();if(!((event.metaKey||event.ctrlKey)&&copyPalette(pal.active)))runPalette(pal.active);}
    });
    list.addEventListener('mousedown',(event)=>event.preventDefault());
    list.addEventListener('mousemove',(event)=>{const option=event.target.closest('.palette-item');if(option&&Number(option.dataset.index)!==pal.active){pal.active=Number(option.dataset.index);pal.moved=true;syncPalette();}});
    list.addEventListener('click',(event)=>{
      const option=event.target.closest('.palette-item');if(!option)return;
      const index=Number(option.dataset.index);
      if(!(event.target.closest('.palette-copy')&&copyPalette(index)))runPalette(index);
    });
  }
  document.addEventListener('dragstart',(event)=>{
    const note=event.target.closest?.('.note[data-note],.cal-chip[data-note]');if(!note)return;
    state.dragging={id:note.dataset.note,rope:note.dataset.rope};
    event.dataTransfer.effectAllowed='move';event.dataTransfer.setData('text/plain',note.dataset.note);
    requestAnimationFrame(()=>note.classList.add('dragging'));
  });
  let dragFrame=0;
  const dropZone=(event)=>event.target.closest?.('.note-board,.cal-day');
  document.addEventListener('dragover',(event)=>{
    if(!state.dragging)return;
    const zone=dropZone(event);if(!zone)return;
    event.preventDefault();event.dataTransfer.dropEffect='move';
    const x=event.clientX,y=event.clientY;cancelAnimationFrame(dragFrame);dragFrame=requestAnimationFrame(()=>markDrop(zone,x,y));
  });
  document.addEventListener('drop',(event)=>{
    if(!state.dragging)return;
    const zone=dropZone(event);if(!zone)return;
    event.preventDefault();cancelAnimationFrame(dragFrame);
    const {id,rope}=state.dragging;
    if(zone.classList.contains('cal-day')){state.dragging=null;clearDropMarks();redateNote(id,rope,zone.dataset.date);return;}
    const index=boardIndex(zone,event.clientX,event.clientY);
    state.dragging=null;clearDropMarks();
    moveNote(id,rope,zone.dataset.ropeTrack,index);
  });
  document.addEventListener('dragend',()=>{cancelAnimationFrame(dragFrame);if(state.dragging){state.dragging=null;clearDropMarks();$$('.dragging').forEach((note)=>note.classList.remove('dragging'));}});
  window.sptWorkspaceChosen=(path)=>{if(typeof path!=='string'||!path)return;const input=$('#workspace-path');if(input)input.value=path;saveWorkspace(path);};
  for(const modal of [dialog,postDialog,noteDialog,palette,clientsDialog,confirmDialog].filter(Boolean)){
    modal.addEventListener('click',(event)=>{
      if(event.target!==modal)return;const rect=modal.getBoundingClientRect();
      if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)requestClose(modal);
    });
    // Other close requests (not the Escape key, which keydown handles) take the same path.
    modal.addEventListener('cancel',(event)=>{event.preventDefault();requestClose(modal);});
    modal.addEventListener('close',()=>{
      const at=modalStack.indexOf(modal);if(at>=0)modalStack.splice(at,1);
      placeToasts();
      $$('video',modal).forEach((video)=>{video.pause();video.removeAttribute('src');video.load();});
    });
  }
  noteDialog.addEventListener('close',()=>{
    noteSnapshot=null;state.noteDay='';state.dayOpen='';state.noteConflict=null;
    if(state.route==='notes')renderNotes();
    if(!restoreFocus(state.noteReturnFocus,state.noteReturnKey)&&!topModal())focusPage();
  });
  // Closing a detail returns to the card of the work or item last shown, even after a re-render.
  dialog.addEventListener('close',()=>{
    ++state.detailRequestId;
    const card=state.detailFocus?$(`#view [${state.detailFocus.attr}="${CSS.escape(state.detailFocus.id)}"]`):null;
    if(card)card.focus();else if(!restoreFocus(state.returnFocus,state.returnKey)&&!topModal())focusPage();
    state.detail=null;state.item=null;state.detailStack=[];state.detailFocus=null;state.detailKind='';
  });
  postDialog.addEventListener('close',()=>{if(!restoreFocus(state.postReturnFocus,state.postReturnKey)&&!topModal()&&focusLost())focusPage();});
  palette?.addEventListener('close',()=>{stopPaletteSearch();if(focusLost())restoreFocus(pal.returnFocus,pal.returnKey);});
  window.addEventListener('beforeunload',(event)=>{if(noteDirty()){event.preventDefault();event.returnValue='';}});
  document.addEventListener('error',(event)=>{
    if(!(event.target instanceof HTMLImageElement))return;
    const parent=event.target.parentElement;
    if(parent?.classList.contains('work-cover'))parent.innerHTML=`<span class="cover-placeholder">${icon('film-strip')}<span>封面不可用</span></span>`;
    else if(parent?.classList.contains('post-visual'))parent.innerHTML=`<span class="source-caption">封面不可用</span>`;
    else if(parent?.classList.contains('item-thumb'))parent.remove();
  },true);
  if(!window.MediaDesk)window.MediaDesk={};
  if(typeof window.MediaDesk.selectDraft!=='function')window.MediaDesk.selectDraft=(id)=>{
    if(!id||!/^[A-Za-z0-9_-]{1,128}$/.test(String(id)))return;
    if(toolURL('publish',String(id)))location.assign(toolURL('publish',String(id)));
  };
  window.mediaUploaderNativeFiles=(paths)=>{forwardToTool('mediaUploaderNativeFiles',paths);};
  window.mediaNativeUploadStatus=(result)=>{forwardToTool('mediaNativeUploadStatus',result);};
  window.mediaPublishingOpenResult=(result)=>{
    forwardToTool('mediaPublishingOpenResult',result);
    clearTimeout(accountOpenTimer);
    state.openingAccountId = null;
    renderCurrent();
    const outcome = accountOpenResult(result);
    notice(outcome.message, { tone: outcome.opened ? 'success' : 'error' });
  };
  // The embedded tool changed page by itself: follow it in the address, nav, sub-tabs and title; never reload it.
  window.sptToolNavigated=(name)=>{
    // 导入数据总览 is retired: a tool page that still links there lands on 数据导入.
    if(name==='overview'&&state.route==='tools'){location.replace('#tools?name=data');return;}
    if(typeof name!=='string'||!TOOL_NAMES[name]||state.route!=='tools'||name===state.tool)return;
    state.tool=name;
    const url=toolURL(name,state.toolDraft);
    if(url)history.replaceState(null,'',url);
    keepFocus($('#view'),()=>{$('#view').innerHTML=toolViewHTML(name);});
    stripEdges($('#view .subtabs'));
    if(frameEl)frameEl.title=TOOL_NAMES[name];
    setTitle();updateShell();
  };
  // ⌘K inside a tool page opens the same palette.
  window.sptOpenPalette=()=>openPalette();
  // A tool page saved accounts or drafts: refresh what 运营 and 发布 show.
  let toolChangeTimer=0;
  // Drafts may have been (re)scheduled too: the 便签 calendar reads its posts again.
  window.sptToolChanged=()=>{clearTimeout(toolChangeTimer);toolChangeTimer=setTimeout(()=>{sched.at=0;loadDashboard();if(state.route==='notes'&&state.notesView==='calendar')loadScheduled(true);},400);};
  window.addEventListener('hashchange',navigate);
  let stripTimer=0;
  window.addEventListener('resize',()=>{clearTimeout(stripTimer);stripTimer=setTimeout(()=>$$('.subtabs,.kind-tabs').forEach(stripEdges),150);});
  window.addEventListener('pagehide',()=>{state.eventSource?.close();state.eventSource=null;});
  window.addEventListener('pageshow',(event)=>{if(event.persisted&&state.health)connectEvents();});
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change',()=>{if(state.theme==='system')setTheme('system');});
  state.layout=readPreference('layout','grid')==='list'?'list':'grid';
  state.cover=COVER_MODES.includes(readPreference('cover','square'))?readPreference('cover','square'):'square';
  state.libraryKind=library?.isKind(readPreference('kind','work'))?readPreference('kind','work'):'work';state.kind=state.libraryKind;
  state.analyticsView=readPreference('analyticsView','chart')==='table'?'table':'chart';
  state.welcomeDismissed=readPreference('welcome-dismissed','')==='1';
  setTheme(readPreference('theme','dark'));setDensity(readPreference('density','comfortable'));setMotion(readPreference('motion','full'));state.notesView=readPreference('notesView','board')==='calendar'?'calendar':'board';
  document.documentElement.dataset.online='true';
  navigate();connect();
})();
