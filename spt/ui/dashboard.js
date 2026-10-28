'use strict';

((scope) => {
  const array = (value) => Array.isArray(value) ? value : [];
  const metricLabels = { followers: '粉丝', views: '浏览', reach: '触达', interactions: '互动', likes: '赞', comments: '评论', saves: '收藏', shares: '分享', follows: '新增关注', profile_visits: '主页访问', link_clicks: '链接点击', three_second_views: '3秒播放', avg_watch_time_sec: '平均时长', completion_rate: '完播率', ctr: '点击率', three_sec_rate: '三秒率', avg_watch_sec: '平均观看秒' };
  const METRIC_KEYS = Object.keys(metricLabels);
  // 百分数（0–100）和秒数的键：显示时带单位。
  const PERCENT_KEYS = ['completion_rate', 'ctr', 'three_sec_rate'];
  const SECOND_KEYS = ['avg_watch_time_sec', 'avg_watch_sec'];
  const known = (value) => typeof value === 'number' && Number.isFinite(value);
  const amount = (value) => known(value) ? new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 1 }).format(value) : '—';
  // 63 → 63%，12.5 → 12.5%；不知道就是 —。
  const percent = (value) => known(value) ? `${amount(value)}%` : '—';
  const shortDate = (value) => {
    if (!value) return '采样日期未知';
    const match = String(value).match(/(\d{4})-(\d{2})-(\d{2})/);
    return match ? `${match[2]}/${match[3]}` : String(value);
  };
  // 记录时间按写下的时区原样显示：10/22 09:30；只有日期时就 10/22。
  const shortTime = (value) => {
    const text = String(value || '');
    // 带时区的时间（服务端统一存成 UTC）换成这台电脑的本地时间；没写时区的照原样。
    if (/T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})$/.test(text)) {
      const moment = new Date(text);
      if (!Number.isNaN(moment.getTime())) return `${pad(moment.getMonth() + 1)}/${pad(moment.getDate())} ${pad(moment.getHours())}:${pad(moment.getMinutes())}`;
    }
    const match = text.match(/(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/);
    if (!match) return value ? text : '—';
    return match[4] ? `${match[2]}/${match[3]} ${match[4]}:${match[5]}` : `${match[2]}/${match[3]}`;
  };
  const NODE_HOURS = { D1: 24, D3: 72, D7: 168 }; // 节点离发布多少小时
  const NODES = Object.keys(NODE_HOURS);
  const pad = (value) => String(value).padStart(2, '0');
  const STALE_DAYS = 7;        // 账号数据满一周没记录就提醒（和每周例行同步）
  const CAPTURE_WEEK_DAYS = 7; // 「今天」里：最近一次记录数据隔了一周才标出来
  const INTEL_NEW_DAYS = 7;    // 7 天内发布的情报算新
  const INTEL_STALE_DAYS = 7;  // 情报超过 7 天没核对就提醒
  const POST_LIST_LIMIT = 6;   // 运营页的内容列表最多列 6 条，其余到「数据」看
  const WINDOW_DAYS = { D1: 1, D3: 3, D7: 7 }; // 发布后第几天记这一次数据
  const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六'];
  const WINDOWS = [{ value: 'latest', label: '最新一次', hint: '每条内容最近记的一次' }, { value: 'D1', label: 'D1', hint: '发布后 24 小时' }, { value: 'D3', label: 'D3', hint: '发布后 72 小时' }, { value: 'D7', label: 'D7', hint: '发布后 7 天' }];
  const ACCOUNT_METRICS = [['followers', '粉丝'], ['views', '浏览'], ['interactions', '互动']];
  // 平台名称：每个页面都用这一份。账号自带的 platform_label 优先。
  const PLATFORM_NAMES = { instagram: 'Instagram', facebook: 'Facebook', tiktok: 'TikTok', youtube: 'YouTube', rednote: 'rednote', xiaohongshu: 'rednote', google_business_profile: 'Google 商家资料', google_business: 'Google 商家资料', google: 'Google', yelp: 'Yelp', cross_platform: '多平台', douyin: '抖音', bilibili: '哔哩哔哩', kuaishou: '快手', wechat: '视频号', shipinhao: '视频号' };
  // 图表配色的分组：CSS 按 .series-<key> 给出 --series，JS 里不写颜色。
  const SERIES = { instagram: 'instagram', facebook: 'facebook', tiktok: 'tiktok', rednote: 'rednote', xiaohongshu: 'rednote', youtube: 'youtube', google: 'google', google_business_profile: 'google', google_business: 'google', yelp: 'yelp' };

  function platformLabel(platform, deps) {
    const key = String(platform || '').trim();
    if (!key) return '';
    const name = PLATFORM_NAMES[key.toLowerCase()];
    if (name) return name;
    const named = typeof deps?.platformName === 'function' ? deps.platformName(key) : '';
    return named && named !== key ? named : key.replace(/_/g, ' ');
  }
  const seriesKey = (platform) => SERIES[String(platform || '').trim().toLowerCase()] || 'other';

  // 下拉选择统一用 SPTListbox：浏览器里是 window.SPTListbox，node 测试里直接 require。
  function listboxHTML(options) {
    const Listbox = (typeof window !== 'undefined' && window.SPTListbox) || (typeof require === 'function' ? require('./listbox.js') : null);
    return Listbox ? Listbox.listboxHTML(options) : '';
  }
  function notesModule() {
    return (typeof window !== 'undefined' && window.SPTNotes) || (typeof require === 'function' ? require('./notes.js') : null);
  }

  function localDay(date = new Date()) {
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
  }
  const isoDay = (value) => {
    const match = String(value || '').match(/^\d{4}-\d{2}-\d{2}/);
    return match ? match[0] : '';
  };
  const dayNumber = (day) => Date.UTC(+day.slice(0, 4), +day.slice(5, 7) - 1, +day.slice(8, 10)) / 86400000;
  const addDays = (day, count) => new Date((dayNumber(day) + count) * 86400000).toISOString().slice(0, 10);
  function daysBetween(from, to) {
    const start = isoDay(from); const end = isoDay(to);
    return start && end ? Math.round(dayNumber(end) - dayNumber(start)) : null;
  }
  // 隔了 limit 天或更久时返回过了几天，否则 0。
  function staleDays(latest, today, limit = STALE_DAYS) {
    const days = daysBetween(latest, today);
    return days !== null && days >= limit ? days : 0;
  }
  const todayOf = (state) => isoDay(state?.today) || localDay();
  function dayLabel(day) {
    const iso = isoDay(day);
    if (!iso) return '';
    const weekday = new Date(dayNumber(iso) * 86400000).getUTCDay();
    return `${Number(iso.slice(5, 7))}月${Number(iso.slice(8, 10))}日 周${WEEKDAYS[weekday]}`;
  }
  // 所有账号里最近的一次采样日期。
  function latestSample(accounts) {
    const dates = array(accounts).flatMap((account) => [account?.as_of, ...array(account?.history).map((item) => item?.date)]).map(isoDay).filter(Boolean);
    return dates.sort().pop() || null;
  }
  const hasSamples = (accounts) => !!latestSample(accounts);
  const chipHTML = (text, tone, deps) => `<span class="chip" data-tone="${tone}">${deps.esc(text)}</span>`;

  function postTitle(post) {
    const raw = String(post.title || post.content_id || '').trim();
    if (raw === 'unknown_official_menu_identity') return '菜品待核对';
    if (!raw || /^[a-z0-9]+(?:_[a-z0-9]+)+$/i.test(raw)) return post.source_kind === 'metric_node' ? '账号数据节点' : '内容待核对';
    if (/^(?:[a-f0-9]{12,}|[A-Z]{1,3}\d{2,})$/.test(raw)) return '内容记录';
    // 只有一个编号（菜单号之类）时写明是编号，免得和排名数字连成「3 046」。
    if (/^\d{1,5}$/.test(raw)) return `编号 ${raw}`;
    return raw.replace(/^\d{4}-\d{2}-\d{2}[_ ]/, '').replace(/_/g, ' · ');
  }
  function metricValue(item, key, window = 'latest') {
    const metrics = window === 'latest' ? item?.metrics : item?.metrics_by_window?.[window] || (item?.metric_window === window ? item.metrics : null);
    return known(metrics?.[key]) ? metrics[key] : null;
  }
  function metricText(item, key, window = 'latest') {
    const value = metricValue(item, key, window);
    if (value === null) return '—';
    if (SECOND_KEYS.includes(key)) return `${amount(value)}s`;
    if (PERCENT_KEYS.includes(key)) return percent(value);
    return amount(value);
  }
  // 账号名：一个品牌在这个平台只有一个号时就是平台名；有几个号时加上账号名，才分得开。
  const handleIsLink = (handle) => /^(https?:)?\/\/|^www\.|\.com\//i.test(String(handle || ''));
  function accountHandle(account) {
    const handle = String(account?.handle || '').trim();
    if (handle && !handleIsLink(handle)) return handle;
    const name = String(account?.name || '').trim();
    if (name) return name;
    return handle.replace(/^https?:\/\//, '').slice(0, 40);
  }
  function accountLabel(account, accounts = [], deps) {
    const platform = account?.platform_label || platformLabel(account?.platform, deps);
    const brand = account?.brand_id || account?.brand;
    const siblings = array(accounts).filter((item) => item && item !== account && (item.brand_id || item.brand) === brand && item.platform === account?.platform && item.id !== account?.id);
    const handle = siblings.length ? accountHandle(account) : '';
    return handle ? `${platform} · ${handle}` : platform;
  }
  // 这一次（latest / D1 / D3 / D7）有没有记下任何数字。
  const hasWindowData = (post, window = 'latest') => METRIC_KEYS.some((key) => metricValue(post, key, window) !== null);
  const hasAnyData = (post) => ['latest', 'D1', 'D3', 'D7'].some((window) => hasWindowData(post, window));
  function metricContext(post, window = 'latest') {
    const cohort = window === 'latest' ? post.metric_window : window;
    const dates = post.metric_observed_at_by_window;
    // 最新一次不在 D1/D3/D7 任何一个节点上时，日期就是那一次记录的日期。
    const at = dates && cohort ? dates[cohort] || null : cohort === post.metric_window ? post.observed_at || null : null;
    return { cohort, at };
  }
  function historySeries(post, window = 'latest') {
    const { cohort } = metricContext(post, window);
    if (!cohort) return [];
    return array(post.history).map((snapshot) => {
      const metrics = snapshot.metrics_by_window?.[cohort] || (snapshot.window === cohort ? snapshot.metrics : null);
      return { value: metrics?.views, at: snapshot.observed_at, window: cohort };
    }).filter((item) => known(item.value) && item.at)
      .filter((item, index, items) => items.findIndex((other) => other.at === item.at && other.value === item.value) === index).slice(-7);
  }
  function accountPosts(data, id) {
    return array(data.posts).filter((post) => post.account_id === id && post.current !== false && !['withdrawn', 'deleted', 'archived'].includes(post.status));
  }
  // 新发的排在前面；没有发布日期的放最后，其余保持原来的顺序。
  function byNewest(posts) {
    return array(posts).map((post, index) => ({ post, index, day: String(post.published_at || '') }))
      .sort((a, b) => (b.day > a.day) - (b.day < a.day) || a.index - b.index).map((entry) => entry.post);
  }
  function selectedItems(state) {
    const data = state.dashboard || {};
    const accounts = array(data.accounts).filter((item) => state.brand === 'all' || item.brand_id === state.brand);
    let account = accounts.find((item) => item.id === state.accountId);
    if (!account) account = accounts.find((item) => item.platform === 'instagram') || accounts[0];
    const posts = byNewest(accountPosts(data, account?.id));
    // 默认看最新一条记过数据的内容；一条都没有时看最新发的那条。
    const window = state.window || 'latest';
    const post = posts.find((item) => item.id === state.postId) || posts.find((item) => hasWindowData(item, window)) || posts.find(hasAnyData) || posts[0];
    return { accounts, account, posts, post };
  }
  function platformHTML(account, deps) {
    const platform = account?.platform || 'other';
    return `<span class="platform-mark platform-${deps.esc(platform)}" aria-label="${deps.esc(account?.platform_label || platformLabel(platform, deps))}"></span>`;
  }
  // 页头：标题 + 右侧控件。sub 只放会变的状态（截至哪天、数据停在哪天），不放解释这一页的句子。
  // title 是固定文字，sub 和 controls 由调用方转义好。
  function headingHTML(title, controls = '', sub = '') {
    return `<header class="page-heading"><div><h1 tabindex="-1">${title}</h1>${sub ? `<p class="page-sub">${sub}</p>` : ''}</div>${controls}</header>`;
  }
  function errorHTML(message, deps) {
    return message ? `<div class="inline-message error" role="status">${deps.icon('warning-circle')}<span>${deps.esc(message)}</span><button type="button" class="button small" data-action="refresh">重试</button></div>` : '';
  }
  function brandOptions(accounts) {
    const brands = [...new Map(array(accounts).map((item) => [item.brand_id, item.brand])).entries()];
    return [['all', '全部品牌'], ...brands.map(([id, name]) => [id ?? '', name || '未命名品牌'])];
  }
  // 页面级控件只放影响整页的：品牌和写便签。「看哪一次数据」放在内容卡片里。
  function scopeControls(state, deps) {
    const accounts = array(state.dashboard?.accounts);
    const write = `<button type="button" class="button" data-note-new>${deps.icon('note')}写便签</button>`;
    if (!accounts.length) return `<div class="page-controls">${write}</div>`;
    return `<div class="page-controls">${listboxHTML({ id: 'brand-filter', label: '品牌', value: state.brand || 'all', options: brandOptions(accounts) })}${write}</div>`;
  }
  function accountBackendHTML(account, state, deps, compact = false) {
    if (!account?.legacy_account_id) return '';
    const name = accountLabel(account, state.dashboard?.accounts, deps);
    if (deps.browser?.()) {
      // No SPT app here: the official backend opens in a new tab; a platform without one shows nothing.
      const url = deps.officialURL?.(account.platform) || '';
      if (!url) return '';
      const link = `href="${deps.esc(url)}" target="_blank" rel="noopener noreferrer"`;
      if (compact) return `<a class="account-open" ${link} title="官方后台" aria-label="官方后台：${deps.esc(account.brand || '')} ${deps.esc(name)}">${deps.icon('arrow-square-out')}</a>`;
      return `<a class="button small" ${link} aria-label="打开${deps.esc(account.brand)} ${deps.esc(name)}官方后台">${deps.icon('arrow-square-out')}官方后台</a>`;
    }
    const opening = state.openingAccountId === account.id;
    const label = opening ? '正在打开…' : deps.nativeAvailable?.() ? '官方后台' : '在 SPT 应用中打开';
    const busy = opening ? 'disabled aria-busy="true"' : '';
    if (compact) {
      return `<button type="button" class="account-open" data-open-account="${deps.esc(account.id)}" title="${deps.esc(label)}" aria-label="${deps.esc(label)}：${deps.esc(account.brand || '')} ${deps.esc(name)}" ${busy}>${deps.icon(opening ? 'arrow-clockwise' : 'arrow-square-out')}</button>`;
    }
    return `<button type="button" class="button small" data-open-account="${deps.esc(account.id)}" aria-label="打开${deps.esc(account.brand)} ${deps.esc(name)}官方后台" ${busy}>${deps.icon('arrow-square-out')}${label}</button>`;
  }
  // Instagram and Facebook are managed together in Meta Business Suite: one entry per client.
  function metaSuiteAccount(accounts) {
    return accounts.find((item) => item.platform === 'facebook' && item.legacy_account_id) || accounts.find((item) => item.platform === 'instagram' && item.legacy_account_id) || null;
  }
  function metaSuiteHTML(accounts, state, deps, compact = false) {
    const account = metaSuiteAccount(accounts);
    if (!account) return '';
    if (deps.browser?.()) {
      const label = compact ? 'Meta<span class="meta-suite-more"> Business Suite</span>' : 'Meta Business Suite';
      return `<a class="${compact ? 'meta-suite-link' : 'button small'}" href="${deps.esc(deps.officialURL?.('meta_suite') || 'https://business.facebook.com/latest/home')}" target="_blank" rel="noopener noreferrer" title="Instagram 和 Facebook 在这里一起管理" aria-label="打开 ${deps.esc(account.brand)} 的 Meta Business Suite"><span class="meta-mark" aria-hidden="true"></span>${label}</a>`;
    }
    const opening = state.openingAccountId === account.id;
    const busy = opening ? 'disabled aria-busy="true"' : '';
    // 窄的账号栏里只写「Meta」（CSS 按栏宽藏起后半），名字不用被挤掉；读屏照样读全称（aria-label）。
    const label = opening ? '正在打开…' : compact ? 'Meta<span class="meta-suite-more"> Business Suite</span>' : 'Meta Business Suite';
    return `<button type="button" class="${compact ? 'meta-suite-link' : 'button small'}" data-open-account="${deps.esc(account.id)}" data-open-target="meta_suite" title="Instagram 和 Facebook 在这里一起管理" aria-label="打开 ${deps.esc(account.brand)} 的 Meta Business Suite" ${busy}><span class="meta-mark" aria-hidden="true"></span>${label}</button>`;
  }
  function accountGroups(accounts) {
    const order = [];
    const groups = new Map();
    for (const account of accounts) {
      const id = account.brand_id || account.brand || 'ungrouped';
      if (!groups.has(id)) {
        groups.set(id, { id, brand: account.brand || '未命名账号', accounts: [] });
        order.push(id);
      }
      groups.get(id).accounts.push(account);
    }
    return order.map((id) => groups.get(id));
  }
  // 账号有没有任何数据：采样日期或粉丝、浏览、互动里任何一个数。
  const accountHasData = (account) => hasSamples([account]) || ACCOUNT_METRICS.some(([key]) => metricValue(account, key) !== null);
  function accountRowHTML(account, selected, maximum, state, deps) {
    const key = state.accountMetric;
    const value = metricValue(account, key);
    const display = value === null && account.display_metrics?.[key] ? `约 ${account.display_metrics[key]}` : amount(value);
    const percent = value === null ? 0 : Math.min(100, Math.max(0, value / maximum * 100));
    const isSelected = account.id === selected?.id;
    const label = accountLabel(account, state.dashboard?.accounts, deps);
    return `<div class="account-row ${isSelected ? 'selected' : ''}"><button type="button" class="account-select" data-account="${deps.esc(account.id)}" aria-pressed="${isSelected}" aria-label="查看${deps.esc(account.brand)} ${deps.esc(label)}的内容">${platformHTML(account, deps)}<span class="account-text"><span class="account-platform">${deps.esc(label)}${account.readonly ? ' · 只读' : ''}</span><span class="metric-rail ${value === null ? 'unavailable' : ''}" aria-hidden="true"><span style="--bar-size:${percent}%"></span></span></span><span class="account-number">${deps.esc(display)}<small>${account.as_of ? deps.esc(shortDate(account.as_of)) : '未采集'}</small></span></button>${accountBackendHTML(account, state, deps, true)}</div>`;
  }
  // 还没有数据的平台收成一行，点开还是原来的账号行（可以选中、打开官方后台）。
  // 手动展开过的折叠在页面重画后保持展开（toggle 不冒泡，所以在捕获阶段听）。
  const openFolds = new Set();
  if (scope && typeof document !== 'undefined') {
    document.addEventListener('toggle', (event) => {
      const fold = event.target;
      if (!fold?.matches?.('details.account-empty[data-fold]')) return;
      if (fold.open) openFolds.add(fold.dataset.fold);
      else openFolds.delete(fold.dataset.fold);
    }, true);
  }
  function emptyAccountsHTML(accounts, group, selected, maximum, state, deps) {
    const names = accounts.map((account) => accountLabel(account, state.dashboard?.accounts, deps)).join('、');
    const open = openFolds.has(group) || accounts.some((account) => account.id === selected?.id);
    return `<details class="account-empty" data-fold="${deps.esc(group)}"${open ? ' open' : ''}><summary><span class="account-empty-marks" aria-hidden="true">${accounts.map((account) => platformHTML(account, deps)).join('')}</span><span class="account-empty-text">${deps.esc(names)}</span><small>还没有数据</small></summary><div class="account-list">${accounts.map((account) => accountRowHTML(account, selected, maximum, state, deps)).join('')}</div></details>`;
  }
  function accountsHTML(accounts, selected, state, deps) {
    const head = (actions) => `<div class="panel-head"><h2 class="panel-title" id="accounts-title">账号表现</h2>${actions}</div>`;
    if (!accounts.length) return `<section class="panel accounts-panel" aria-labelledby="accounts-title">${head('')}<div class="empty-state compact"><strong>还没有账号</strong><a class="button primary" href="#tools?name=accounts">添加账号</a></div></section>`;
    const key = state.accountMetric;
    const maximum = Math.max(1, ...accounts.map((item) => metricValue(item, key)).filter(known));
    const groups = accountGroups(accounts).map((group) => {
      const dates = group.accounts.map((item) => item.as_of).filter(Boolean).sort();
      const latest = dates[dates.length - 1];
      const filled = group.accounts.filter(accountHasData);
      const empty = group.accounts.filter((account) => !accountHasData(account));
      const rows = filled.length ? `<div class="account-list">${filled.map((account) => accountRowHTML(account, selected, maximum, state, deps)).join('')}</div>` : '';
      const fold = empty.length ? emptyAccountsHTML(empty, group.id, selected, maximum, state, deps) : '';
      return `<div class="account-group"><div class="account-group-header"><div class="client-text"><span class="client-name">${deps.esc(group.brand)}</span><span class="client-meta">${group.accounts.length} 个平台${latest ? ` · ${deps.esc(shortDate(latest))}` : ''}</span></div>${metaSuiteHTML(group.accounts, state, deps, true)}</div>${rows}${fold}</div>`;
    }).join('');
    const actions = `${listboxHTML({ id: 'account-metric', label: '账号指标', value: key || 'followers', options: ACCOUNT_METRICS })}<a class="text-action" href="#analytics">数据 ${deps.icon('caret-right')}</a>`;
    return `<section class="panel accounts-panel" aria-labelledby="accounts-title">${head(actions)}${groups}</section>`;
  }
  function metricHTML(item, key, state, label) {
    return `<div><span class="metric-label">${label || metricLabels[key] || key}</span><strong class="metric-value">${metricText(item,key,state.window)}</strong></div>`;
  }
  // 工作区记的数据：固定四格，记了的其他项（分享、完播率、点击率……）跟在后面。
  const WORKSPACE_BASE = [['views', '浏览'], ['likes', '赞'], ['comments', '评论'], ['saves', '收藏']];
  const WORKSPACE_MORE = [['shares', '分享'], ['completion_rate', '完播率'], ['ctr', '点击率'], ['three_sec_rate', '三秒率'], ['avg_watch_sec', '平均观看秒'], ['reach', '触达'], ['profile_visits', '主页访问'], ['follows', '新增关注']];
  const isWorkspacePost = (post) => post?.source_kind === 'workspace_metrics';
  function metricsHTML(post, state) {
    const visual = /video|reel/i.test(post.format || '') || known(post.duration_sec);
    let keys;
    if (isWorkspacePost(post)) keys = [...WORKSPACE_BASE, ...WORKSPACE_MORE.filter(([key]) => metricValue(post, key, state.window) !== null)];
    else keys = visual ? [['views','播放量'],['completion_rate','完播率'],['avg_watch_time_sec','平均时长'],['interactions','互动']] : [['views','浏览量'],['likes','赞'],['saves','收藏'],['comments','评论']];
    return `<div class="post-metrics">${keys.map(([key,label]) => metricHTML(post,key,state,label)).join('')}</div>`;
  }
  function chartHTML(post, state, deps) {
    const values = historySeries(post,state.window);
    if (values.length < 2) return '';
    const maximum = Math.max(1,...values.map((item) => item.value));
    const title = `${values[0].window} 浏览`;
    return `<div class="snapshot-chart" role="img" aria-label="${deps.esc(title)}：${deps.esc(values.map((item) => `${shortDate(item.at)} ${item.value}`).join('，'))}"><span class="field-label">${deps.esc(title)}</span><div class="chart-bars">${values.map((item) => `<div class="chart-bar"><span style="--bar-size:${item.value / maximum * 100}%"></span></div>`).join('')}</div><div class="chart-labels">${values.map((item) => `<span>${deps.esc(shortDate(item.at))}</span>`).join('')}</div></div>`;
  }
  // 还没记过数据的内容：一句话说清什么时候可以记。
  function captureHint(post, today) {
    const published = isoDay(post?.published_at);
    if (!published) return '还没有记录数据。发布日期不详，记数据时以平台后台为准。';
    const due = Object.entries(WINDOW_DAYS).map(([window, days]) => ({ window, day: addDays(published, days) }));
    const past = due.filter((item) => item.day < today);
    const now = due.filter((item) => item.day === today);
    const later = due.filter((item) => item.day > today);
    if (!now.length && !later.length) return '还没有记录数据。发布已经超过 7 天，平台后台现在只能看到累计数。';
    const parts = [];
    if (past.length === 1) parts.push(`${past[0].window}（${shortDate(past[0].day)}）已经过了`);
    else if (past.length) parts.push(`${past.map((item) => item.window).join('、')} 已经过了`);
    if (now.length) parts.push(`${now.map((item) => item.window).join('、')} 今天记`);
    if (later.length) parts.push(later.map((item) => `${item.window} 在 ${shortDate(item.day)}`).join('，'));
    return `还没有记录数据。${parts.join('；')}。`;
  }
  function metricsBlockHTML(post, state, deps) {
    const window = state.window || 'latest';
    if (!hasAnyData(post)) return `<p class="metric-empty">${deps.esc(captureHint(post, todayOf(state)))}</p>`;
    const select = `<div class="post-metrics-head">${listboxHTML({ id: 'metric-window', label: '数据', value: window, options: WINDOWS, showLabel: true, className: 'metric-window' })}</div>`;
    if (!hasWindowData(post, window)) {
      const others = ['D1', 'D3', 'D7'].filter((name) => name !== window && hasWindowData(post, name));
      return `${select}<p class="metric-empty">${window === 'latest' ? '最新一次' : `${window} `}没有记下数字。${others.length ? `${others.join('、')} 有，换过去看。` : ''}</p>`;
    }
    const context = metricContext(post, window);
    return `${select}${metricsHTML(post, state)}<p class="metric-period">${context.cohort ? `${deps.esc(context.cohort)} · ` : ''}${context.at ? `${deps.esc(shortDate(context.at))} 记录` : '记录日期不详'}</p>${chartHTML(post, state, deps)}`;
  }
  function postMediaHTML(post, account, deps, video = false) {
    const cover = deps.safeLocalURL(post.cover);
    const preview = deps.safeLocalURL(post.preview_url);
    if (video && preview) return `<div class="post-visual"><video controls preload="metadata" playsinline src="${deps.esc(preview)}" ${cover ? `poster="${deps.esc(cover)}"` : ''} aria-label="${deps.esc(postTitle(post))}"></video></div>`;
    if (cover) return `<div class="post-visual"><img src="${deps.esc(cover)}" alt="${deps.esc(postTitle(post))}工作区封面" decoding="async"></div>`;
    return `<div class="post-visual empty">${platformHTML(account,deps)}<span>${post.source_kind === 'metric_node' ? '数据节点' : '原文未附封面'}</span></div>`;
  }
  function postActions(post, deps) {
    const url = deps.safeExternalURL(post.url);
    return `<div class="post-actions"><button type="button" class="button small" data-post-open="${deps.esc(post.id)}">${post.caption_complete ? '查看全文' : '查看记录'}</button>${post.work_id ? `<button type="button" class="button small" data-work="${deps.esc(post.work_id)}">${deps.icon('stack')}对应作品</button>` : ''}${url ? `<a class="button small" href="${deps.esc(url)}" target="_blank" rel="noopener noreferrer">${deps.icon('arrow-square-out')}平台原文</a>` : ''}</div>`;
  }
  // 账号还没有内容记录：一句话说缺什么，给一个能做的动作。
  function postEmptyHTML(account, deps, accounts = []) {
    const label = accountLabel(account, accounts, deps);
    const name = `${account?.brand || ''} ${label}`.trim() || '这个账号';
    const profile = deps.safeExternalURL(account?.profile_url);
    const profileLink = (primary) => profile ? `<a class="${primary ? 'button primary' : 'text-action'}" href="${deps.esc(profile)}" target="_blank" rel="noopener noreferrer">查看公开主页 ${deps.icon('arrow-square-out')}</a>` : '';
    const body = account?.readonly
      ? `<strong>${deps.esc(name)} 是只读资料</strong>${profileLink(true) || '<a class="button" href="#tools?name=accounts">看账号档案</a>'}`
      : `<strong>${deps.esc(name)} 还没有内容记录</strong><a class="button primary" href="#tools?name=data">导入数据</a>${profileLink(false)}`;
    return `<section class="panel post-panel" aria-labelledby="post-empty-title"><div class="panel-head"><h2 class="panel-title" id="post-empty-title">账号内容</h2></div><div class="empty-state compact">${platformHTML(account,deps)}${body}</div></section>`;
  }
  // 列表里放最近的几条；正在看的那条一直留在列表里（排在外面时顶替最后一行）。
  function postListItems(posts, post) {
    const top = posts.slice(0, POST_LIST_LIMIT);
    if (!post || top.includes(post)) return top;
    return [...top.slice(0, POST_LIST_LIMIT - 1), post];
  }
  function postListHTML(account, posts, post, deps, accounts = []) {
    if (posts.length < 2) return '';
    const rows = postListItems(posts, post);
    const name = `${account?.brand || ''} ${accountLabel(account, accounts, deps)}`.trim();
    const items = rows.map((item) => {
      const current = item.id === post.id;
      return `<li><button type="button" class="post-select" data-post="${deps.esc(item.id)}"${current ? ' aria-current="true"' : ''}><span>${deps.esc(postTitle(item))}</span><small>${item.published_at ? deps.esc(shortDate(item.published_at)) : '日期未知'}</small>${current ? '<span class="post-current">正在看</span>' : deps.icon('caret-right')}</button></li>`;
    }).join('');
    const more = posts.length > rows.length;
    // 「数据」页只列记过数据的内容，这个账号一条都没有时不放链接。
    const link = more && posts.some(hasAnyData) ? `<a class="text-action" href="#analytics" data-analytics-platform="${deps.esc(account?.platform || 'all')}">全部 ${deps.icon('caret-right')}</a>` : '';
    // Only a list that holds more than it shows gets a foot: the total and the way to the rest.
    return `<ul class="post-list" aria-label="${deps.esc(name)}的内容">${items}</ul>${more ? `<div class="post-list-foot"><span class="source-caption">共 ${posts.length} 条</span>${link}</div>` : ''}`;
  }
  function postHTML(account, posts, post, state, deps) {
    const accounts = array(state.dashboard?.accounts);
    if (!post) return postEmptyHTML(account, deps, accounts);
    const compact = post.source_kind === 'metric_node' && !deps.safeLocalURL(post.cover) && !deps.safeLocalURL(post.preview_url);
    const caption = post.caption || (compact ? '未收录文案' : '原记录里没有文案。');
    const captionHTML = `<p class="post-caption ${post.caption ? '' : 'empty'}">${deps.esc(caption)}</p>`;
    const metrics = metricsBlockHTML(post, state, deps);
    const body = compact ? `${metrics}${captionHTML}` : `${captionHTML}${metrics}`;
    const visibleIssues = compact ? array(post.issues).filter((issue) => /不一致|冲突|成片|成品|媒体|SHA/i.test(issue)) : array(post.issues);
    const subtitle = post.published_at ? deps.esc(shortDate(post.published_at)) : post.source_kind === 'metric_node' ? '历史记录' : '发布日期未知';
    const label = accountLabel(account, accounts, deps);
    return `<section class="panel post-panel ${compact ? 'metric-node' : ''}" aria-labelledby="selected-post-title"><div class="post-heading">${platformHTML(account,deps)}<div><h2 id="selected-post-title">${deps.esc(postTitle(post))}</h2><div class="source-caption">${deps.esc(label)} · ${subtitle}</div></div></div><div class="post-main">${compact ? '' : postMediaHTML(post,account,deps)}<div class="post-body">${body}</div></div>${postActions(post,deps)}${visibleIssues.length ? `<p class="work-warning">${deps.icon('warning-circle')}${deps.esc(visibleIssues.join('；'))}</p>` : ''}${postListHTML(account, posts, post, deps, accounts)}</section>`;
  }
  function workPreviewHTML(state, deps) {
    const works = array(state.allWorks);
    const head = `<div class="panel-head"><h2 class="panel-title" id="recent-works-title">最近作品</h2>${works.length ? `<a class="text-action" href="#works">资产库 ${deps.icon('caret-right')}</a>` : ''}</div>`;
    let body;
    if (!works.length && state.loading) body = `<p class="small-empty"><span class="spinner" aria-hidden="true"></span>正在读取作品</p>`;
    else if (!works.length) body = `<div class="empty-state compact"><strong>工作区里还没有作品</strong><a class="button primary" href="#works">打开资产库</a></div>`;
    else body = `<div class="works-grid">${works.slice(0, 4).map(deps.cardHTML).join('')}</div>`;
    return `<section class="panel works-preview" aria-labelledby="recent-works-title">${head}${body}</section>`;
  }

  // 情报：新的、还有效的排在前面。
  const intelDate = (item) => isoDay(item?.published_at || item?.observed_at || item?.captured_at || item?.checked_at);
  function isNewIntel(item, today) {
    const days = daysBetween(intelDate(item), today);
    return days !== null && days >= 0 && days <= INTEL_NEW_DAYS;
  }
  function isActiveCandidate(item, today) {
    const until = isoDay(item?.expires_at);
    return item?.status === 'candidate' && !!until && until >= today;
  }
  function newIntelCount(intel, today) {
    return [...array(intel?.news), ...array(intel?.research)].filter((item) => isNewIntel(item, today)).length + array(intel?.candidates).filter((item) => isActiveCandidate(item, today)).length;
  }
  // 新情报在哪一类：「今天」的链接直接打开那一类。
  function freshIntel(intel, today) {
    const counts = [
      ['news', array(intel?.news).filter((item) => isNewIntel(item, today)).length, '官方动态'],
      ['research', array(intel?.research).filter((item) => isNewIntel(item, today)).length, '研究资料'],
      ['candidates', array(intel?.candidates).filter((item) => isActiveCandidate(item, today)).length, '市场线索'],
    ];
    const kinds = counts.filter(([, count]) => count);
    const top = counts.reduce((best, entry) => entry[1] > best[1] ? entry : best, counts[0]);
    const label = kinds.length !== 1 ? '条新情报' : top[0] === 'candidates' ? '条有效的市场线索' : `条新${top[2]}`;
    return { total: kinds.reduce((sum, [, count]) => sum + count, 0), tab: top[0], label, detail: kinds.length > 1 ? kinds.map(([, count, name]) => `${name} ${count}`).join(' · ') : '' };
  }
  function sortIntel(items, today) {
    return array(items).map((item, index) => ({ item, index, fresh: isNewIntel(item, today), date: intelDate(item) }))
      .sort((a, b) => (b.fresh - a.fresh) || b.date.localeCompare(a.date) || a.index - b.index).map((entry) => entry.item);
  }
  function candidateGroups(items, today) {
    const list = array(items);
    const active = list.filter((item) => isActiveCandidate(item, today)).sort((a, b) => isoDay(a.expires_at).localeCompare(isoDay(b.expires_at)));
    const rest = list.filter((item) => !isActiveCandidate(item, today)).sort((a, b) => String(b.captured_at || '').localeCompare(String(a.captured_at || '')));
    return { active, rest };
  }
  function candidateChip(item, today) {
    if (isActiveCandidate(item, today)) return { text: `有效至 ${shortDate(item.expires_at)}`, tone: 'ok' };
    if (item?.status === 'candidate' || item?.status === 'expired') return { text: '已过期', tone: 'neutral' };
    if (item?.status === 'test') return { text: '测试', tone: 'neutral' };
    return item?.status ? { text: String(item.status), tone: 'neutral' } : null;
  }
  // 资料里原样写的状态词换成一句好懂的话；认不出的照原文显示。
  function intelStateText(value) {
    const text = String(value || '').trim();
    if (/已核/.test(text)) return '对照过官方原文';
    if (text === '待用') return '还没用上';
    if (text === '已用') return '用过了';
    return text;
  }
  const intelTitle = (item) => String(item?.title || '').trim().replace(/_/g, ' ') || '未命名';
  function intelItemHTML(item, today, deps, options = {}) {
    const url = deps.safeExternalURL(item.url);
    const title = intelTitle(item);
    const date = intelDate(item);
    const chip = options.candidate ? candidateChip(item, today) : isNewIntel(item, today) ? { text: '新', tone: 'accent' } : null;
    const source = [options.candidate ? platformLabel(item.platform, deps) : item.source, date ? shortDate(date) : '', options.candidate ? '' : intelStateText(item.state)].filter(Boolean).join(' · ');
    const summary = options.candidate ? item.notes : item.summary;
    const noteText = [title, summary, url].filter(Boolean).join('\n');
    const heading = url ? `<a href="${deps.esc(url)}" target="_blank" rel="noopener noreferrer" title="在浏览器打开">${deps.esc(title)}<span class="sr-only">（在浏览器打开）</span>${deps.icon('arrow-square-out')}</a>` : deps.esc(title);
    return `<article class="intel-item"><h3>${heading}</h3><p class="intel-source">${chip ? chipHTML(chip.text, chip.tone, deps) : ''}<span>${deps.esc(source)}</span></p>${options.full && summary ? `<p>${deps.esc(summary)}</p>` : ''}<button type="button" class="text-action" data-note-new data-note-text="${deps.esc(noteText)}">存为便签</button></article>`;
  }
  const refreshEmpty = (title, deps) => `<div class="empty-state compact"><strong>${deps.esc(title)}</strong><button type="button" class="button small" data-action="refresh">刷新</button></div>`;
  // 去情报页某一类的链接：href 带上分类，data-intel-page-tab 让当前页面先切到那一类。
  const intelLink = (tab, text, deps) => `<a class="text-action" href="#intelligence?tab=${tab}" data-intel-page-tab="${tab}">${text} ${deps.icon('caret-right')}</a>`;
  function intelRailHTML(state, deps) {
    const data = state.dashboard?.intelligence || {};
    // 一条情报都没有（比如刚开始用）就不放这一栏：这里没有能做的事。
    if (!array(data.news).length && !array(data.research).length && !array(data.candidates).length) return '';
    const today = todayOf(state);
    const tab = state.intelTab === 'research' ? 'research' : 'news';
    const label = tab === 'research' ? '研究资料' : '官方动态';
    const items = sortIntel(data[tab], today).slice(0, 4);
    const list = items.length ? `<div class="intel-list">${items.map((item) => intelItemHTML(item, today, deps)).join('')}</div>` : `<p class="small-empty">还没有${label}。</p>`;
    const checked = isoDay(data.as_of);
    const stale = checked ? staleDays(checked, today, INTEL_STALE_DAYS) : 0;
    // Only old material earns a line: the same chip the 情报 page shows.
    const foot = stale ? `<p class="intel-stale">${chipHTML(`资料停在 ${shortDate(checked)}`, 'warn', deps)}</p>` : '';
    const candidates = array(data.candidates);
    let leads = '';
    if (candidates.length) {
      const active = candidates.filter((item) => isActiveCandidate(item, today)).length;
      const latest = candidates.map((item) => isoDay(item.captured_at)).filter(Boolean).sort().pop();
      const summary = active ? `<strong>${active} 条有效线索</strong><small>共 ${candidates.length} 条记录</small>` : `<strong>现在没有有效线索</strong><small>${latest ? `最近一条是 ${shortDate(latest)} 记下的` : `共 ${candidates.length} 条记录`}</small>`;
      leads = `<section class="panel"><div class="panel-head"><h2 class="panel-title">市场线索</h2></div><div class="intel-candidates">${deps.icon('file-text')}<div>${summary}</div></div>${intelLink('candidates', active ? '查看线索' : '查看记录', deps)}</section>`;
    }
    return `<aside class="intelligence-rail" aria-label="情报摘要"><section class="panel"><div class="panel-head"><h2 class="panel-title">情报</h2>${intelLink(tab, '全部', deps)}</div><div class="segmented" role="group" aria-label="情报类别"><button type="button" data-intel-tab="news" aria-pressed="${tab === 'news'}">官方动态</button><button type="button" data-intel-tab="research" aria-pressed="${tab === 'research'}">研究资料</button></div>${list}${foot}</section>${leads}</aside>`;
  }

  // 「今天」：只放有数据的条目，每条都点到它数的那些东西。
  function todayItems(state, deps) {
    const today = todayOf(state);
    const items = [];
    if (state.notes) {
      const dated = array(state.notes.ropes).flatMap((rope) => array(rope.notes)).map((note) => isoDay(note?.date)).filter(Boolean);
      const due = dated.filter((day) => day === today).length;
      const overdue = dated.filter((day) => day < today).length;
      if (due) items.push({ href: '#notes', value: due, label: '张便签今天到期' });
      if (overdue) items.push({ href: '#notes', value: overdue, label: '张便签过了日期还没撤下' });
    }
    // 只有一件就直接打开那件作品，几件时去资产库按状态筛选。
    for (const [status, label] of [['ready', '件待发布'], ['cut', '件已成片还没发布']]) {
      const works = array(state.allWorks).filter((work) => work.status === status);
      if (works.length === 1) items.push({ work: works[0].id, value: 1, label, detail: works[0].title || '' });
      else if (works.length) items.push({ href: `#works?status=${status}`, value: works.length, label });
    }
    // 数据按周补一次：隔了一周以上才提醒。链接去数据导入；没有这个工具的服务去「数据」。
    const latest = latestSample(state.dashboard?.accounts);
    if (latest) {
      const gap = daysBetween(latest, today);
      items.push({ href: deps?.dataURL?.() || '#analytics', value: shortDate(latest), label: '最近一次记录数据', chip: gap >= CAPTURE_WEEK_DAYS ? `${gap} 天没更新` : '' });
    }
    const fresh = freshIntel(state.dashboard?.intelligence, today);
    if (fresh.total) items.push({ href: `#intelligence?tab=${fresh.tab}`, tab: fresh.tab, value: fresh.total, label: fresh.label, detail: fresh.detail });
    return items;
  }
  function todayItemHTML(item, deps) {
    const inner = `<span class="today-value">${deps.esc(item.value)}</span><span class="today-label">${deps.esc(item.label)}</span>${item.detail ? `<span class="today-detail">${deps.esc(item.detail)}</span>` : ''}${item.chip ? chipHTML(item.chip, 'warn', deps) : ''}`;
    if (item.work) return `<button type="button" class="today-item" data-work="${deps.esc(item.work)}">${inner}</button>`;
    return `<a class="today-item" href="${deps.esc(item.href)}"${item.tab ? ` data-intel-page-tab="${deps.esc(item.tab)}"` : ''}>${inner}</a>`;
  }
  function todayHTML(state, deps) {
    const items = todayItems(state, deps);
    if (!items.length) return '';
    return `<section class="today-strip" aria-labelledby="today-title"><h2 id="today-title" class="today-title">今天 <span class="today-date">${deps.esc(dayLabel(todayOf(state)))}</span></h2><ul class="today-list">${items.map((item) => `<li>${todayItemHTML(item, deps)}</li>`).join('')}</ul></section>`;
  }
  // 第一次用：还没有账号或数据时，列出起步的几步，做完的打勾。
  function welcomeHTML(state, deps) {
    if (state.welcomeDismissed || (state.dashboardError && !state.dashboard)) return '';
    const accounts = array(state.dashboard?.accounts);
    const data = hasSamples(accounts);
    if (accounts.length && data) return '';
    const notes = array(state.notes?.ropes).reduce((total, rope) => total + array(rope.notes).length, 0);
    const steps = [
      [!!state.health?.workspace_ready, '选好工作区', '#settings', '去设置'],
      [array(state.allWorks).length > 0, '收进第一件作品', '#works', '打开资产库'],
      [accounts.length > 0, '写下要管理的账号', '#settings?section=accounts', '账号与数据'],
      [data, '导入平台数据', '#settings?section=accounts', '账号与数据'],
      [notes > 0, '贴一张便签', '', '写便签'],
    ];
    const next = steps.findIndex(([done]) => !done);
    const items = steps.map(([done, title, href, action], index) => {
      const kind = `button small${index === next ? ' primary' : ''}`;
      const control = href ? `<a class="${kind}" href="${href}">${action}</a>` : `<button type="button" class="${kind}" data-note-new>${action}</button>`;
      return `<li class="welcome-step" data-done="${done}"><span class="welcome-step-mark" aria-hidden="true"></span><div class="welcome-step-text"><strong>${done ? '<span class="sr-only">已完成：</span>' : ''}${title}</strong></div>${control}</li>`;
    }).join('');
    const notesUI = notesModule();
    const ghost = notesUI?.ghostHTML ? notesUI.ghostHTML(64) : '';
    return `<section class="welcome-card" aria-labelledby="welcome-title">${ghost}<div class="welcome-body"><h2 id="welcome-title">从这几步开始</h2><ol class="welcome-steps">${items}</ol><button type="button" class="text-action" data-action="dismiss-welcome">先不用</button></div></section>`;
  }
  function renderOverview(state, deps) {
    const { accounts,account,posts,post } = selectedItems(state);
    state.accountId = account?.id || '';
    state.postId = post?.id || '';
    if (state.dashboardLoading && !state.dashboard) return `${headingHTML('运营')}<div class="dashboard-skeleton" aria-busy="true" aria-label="正在读取运营资料"><div class="skeleton skeleton-card"></div><div class="skeleton skeleton-card"></div><div class="skeleton skeleton-card"></div></div>`;
    // 起步卡片在的时候（还没有账号数据），空着的面板先不放，免得和起步的几步重复。
    const welcome = welcomeHTML(state, deps);
    const sparse = !!welcome;
    const accountsPanel = sparse && !accounts.length ? '' : accountsHTML(accounts, account, state, deps);
    const postPanel = !account || (sparse && !post) ? '' : postHTML(account, posts, post, state, deps);
    const worksPanel = sparse && !array(state.allWorks).length ? '' : workPreviewHTML(state, deps);
    const operations = accountsPanel || postPanel ? `<div class="overview-operations">${accountsPanel}${postPanel}</div>` : '';
    return `<header class="page-heading overview-heading"><h1 class="sr-only" tabindex="-1">运营</h1>${scopeControls(state, deps)}</header>${errorHTML(state.dashboardError, deps)}${welcome}${todayHTML(state, deps)}<div class="overview-layout${sparse ? ' is-sparse' : ''}"><div class="overview-main">${operations}${worksPanel}</div><div class="overview-side">${deps.sideRail ? deps.sideRail(state) : ''}${intelRailHTML(state, deps)}</div></div>`;
  }
  function candidatesHTML(items, today, deps) {
    const list = array(items);
    if (!list.length) return refreshEmpty('还没有市场线索', deps);
    const { active, rest } = candidateGroups(list, today);
    // No live lead: say so; the expired ones (with their dates) are folded right below.
    const top = active.length
      ? `<div class="intel-list">${active.map((item) => intelItemHTML(item, today, deps, { full: true, candidate: true })).join('')}</div>`
      : refreshEmpty('现在没有有效线索', deps);
    const archive = rest.length ? `<details class="intel-archive"><summary>${rest.length} 条已失效的线索</summary><div class="intel-list">${rest.map((item) => intelItemHTML(item, today, deps, { full: true, candidate: true })).join('')}</div></details>` : '';
    return top + archive;
  }
  function renderIntelligence(state,deps) {
    const intel = state.dashboard?.intelligence || {};
    const today = todayOf(state);
    const tab = ['news', 'research', 'candidates'].includes(state.intelPageTab) ? state.intelPageTab : 'news';
    const checked = isoDay(intel.as_of);
    if (state.dashboardLoading && !state.dashboard) return `<section class="intelligence-page">${headingHTML('情报')}<div class="intel-list" aria-busy="true" aria-label="正在读取情报"><div class="skeleton skeleton-line"></div><div class="skeleton skeleton-line"></div><div class="skeleton skeleton-line"></div></div></section>`;
    const stale = checked ? staleDays(checked, today, INTEL_STALE_DAYS) : 0;
    const controls = stale ? `<div class="page-controls">${chipHTML(`资料停在 ${shortDate(checked)}`, 'warn', deps)}</div>` : '';
    // 每个分类：总数，再标出里面有几条新的（线索标有效的），方便从「今天」点过来找到。
    const fresh = (items) => array(items).filter((item) => isNewIntel(item, today)).length;
    const tabs = [
      ['news', '官方动态', array(intel.news).length, fresh(intel.news), '新'],
      ['research', '研究资料', array(intel.research).length, fresh(intel.research), '新'],
      ['candidates', '市场线索', array(intel.candidates).length, array(intel.candidates).filter((item) => isActiveCandidate(item, today)).length, '有效'],
    ];
    const tabBar = `<div class="segmented" role="group" aria-label="情报分类">${tabs.map(([id, label, total, marked, word]) => `<button type="button" data-intel-page-tab="${id}" aria-pressed="${tab === id}">${label}<span class="nav-count">${total}</span>${marked ? chipHTML(`${word} ${marked}`, word === '新' ? 'accent' : 'ok', deps) : ''}</button>`).join('')}</div>`;
    let body;
    if (tab === 'candidates') body = candidatesHTML(intel.candidates, today, deps);
    else {
      const items = sortIntel(intel[tab], today);
      body = items.length ? `<div class="intel-list">${items.map((item) => intelItemHTML(item, today, deps, { full: true })).join('')}</div>` : refreshEmpty(`还没有${tab === 'research' ? '研究资料' : '官方动态'}`, deps);
    }
    return `<section class="intelligence-page">${headingHTML('情报', controls)}${errorHTML(state.dashboardError,deps)}${tabBar}${body}</section>`;
  }
  // ---- 工作区记的数据：时间线、留存曲线、分析 ----
  // 节点比该记的时间晚了几小时（不到 1 小时不算）。服务端给了 late_hours 就用它。
  function lateHours(window, ageHours, late = null) {
    if (known(late)) return late >= 1 ? Math.round(late) : 0;
    const due = NODE_HOURS[window];
    if (!due || !known(ageHours)) return 0;
    const over = ageHours - due;
    return over >= 1 ? Math.round(over) : 0;
  }
  function nodeChipHTML(window, ageHours, deps, late = null) {
    if (!NODES.includes(window)) return '';
    const over = lateHours(window, ageHours, late);
    return `<span class="chip node-chip" data-tone="${over ? 'warn' : 'accent'}">${deps.esc(window)}${over ? ` 晚 ${over}h` : ''}</span>`;
  }
  const hoursText = (hours) => known(hours) ? `${Math.round(hours)} h` : '—';
  // 每次记录一行，按记录顺序；一整列没数就不放。
  const TIMELINE_KEYS = [['views', '浏览'], ['likes', '赞'], ['comments', '评论'], ['saves', '收藏'], ['shares', '分享'], ['completion_rate', '完播率']];
  function observations(post) {
    return array(post?.history).filter((item) => item && item.metrics && typeof item.metrics === 'object' && (item.observed_at || item.at));
  }
  function timelineHTML(post, deps) {
    const rows = observations(post);
    if (!rows.length || !(isWorkspacePost(post) || rows.some((item) => 'age_hours' in item))) return '';
    const cell = (metrics, key) => known(metrics?.[key]) ? (PERCENT_KEYS.includes(key) ? percent(metrics[key]) : amount(metrics[key])) : '—';
    const keys = TIMELINE_KEYS.filter(([key], index) => index === 0 || rows.some((item) => known(item.metrics?.[key])));
    const head = `<tr><th scope="col">记录时间</th><th scope="col" class="num">距发布</th>${keys.map(([, label]) => `<th scope="col" class="num">${label}</th>`).join('')}<th scope="col">节点</th></tr>`;
    const body = rows.map((item) => `<tr><th scope="row">${deps.esc(shortTime(item.observed_at || item.at))}</th><td class="num">${hoursText(item.age_hours)}</td>${keys.map(([key]) => `<td class="num">${cell(item.metrics, key)}</td>`).join('')}<td>${nodeChipHTML(item.window, item.age_hours, deps, item.late_hours)}</td></tr>`).join('');
    return `<div class="table-wrap"><table class="data-table metric-timeline"><caption class="sr-only">每次记下的数</caption><thead>${head}</thead><tbody>${body}</tbody></table></div>`;
  }
  // 留存曲线：最近一次读到的，一点一秒。宽度跟着盒子走，线宽由 CSS 的 non-scaling-stroke 保持不变。
  function retentionPoints(curve) {
    return array(curve?.points).map((point) => Array.isArray(point) ? { second: Number(point[0]), rate: Number(point[1]) } : { second: Number(point?.second), rate: Number(point?.rate) })
      .filter((point) => known(point.second) && known(point.rate)).sort((a, b) => a.second - b.second);
  }
  function retentionHTML(curves, platform, deps) {
    // 作品详情给一组曲线（最新在前）；内容条目只给最新一条曲线（对象）。
    const curve = Array.isArray(curves) ? curves[0] : curves;
    const points = retentionPoints(curve);
    if (points.length < 2) return '';
    const width = 320; const height = 110; const pad = 4;
    const maxSecond = Math.max(1, points[points.length - 1].second);
    const x = (second) => pad + second / maxSecond * (width - pad * 2);
    const y = (rate) => pad + (1 - Math.min(100, Math.max(0, rate)) / 100) * (height - pad * 2);
    const line = points.map((point, index) => `${index ? 'L' : 'M'}${x(point.second).toFixed(1)} ${y(point.rate).toFixed(1)}`).join(' ');
    const dots = points.map((point) => `<circle class="dot" cx="${x(point.second).toFixed(1)}" cy="${y(point.rate).toFixed(1)}" r="3"><title>${point.second} 秒：${percent(point.rate)}</title></circle>`).join('');
    const picks = points.length <= 6 ? points : [points[0], ...points.filter((_, index) => index > 0 && index < points.length - 1 && index % Math.ceil((points.length - 2) / 4) === 0).slice(0, 4), points[points.length - 1]];
    const labels = picks.map((point) => `<span>${point.second}s ${deps.esc(percent(point.rate))}</span>`).join('');
    const summary = points.map((point) => `${point.second} 秒 ${percent(point.rate)}`).join('，');
    return `<section class="retention"><h3>留存${curve?.at ? `<span class="verification"> ${deps.esc(shortDate(curve.at))}</span>` : ''}</h3><svg class="retention-chart series series-${seriesKey(platform)}" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="${deps.esc(`留存：${summary}`)}"><path class="area" d="${line} L${x(points[points.length - 1].second).toFixed(1)} ${height - pad} L${x(points[0].second).toFixed(1)} ${height - pad} Z"/><path class="line" d="${line}"/>${dots}</svg><div class="chart-labels">${labels}</div></section>`;
  }
  // 标签链接到「数据 › 原因标签」里这个标签那一行。
  const tagHash = (tag) => `#analytics?view=tags&tag=${encodeURIComponent(String(tag))}`;
  const tagChipHTML = (tag, deps) => `<a class="chip tag-chip" href="${deps.esc(tagHash(tag))}" data-analysis-tag="${deps.esc(tag)}">${deps.esc(tag)}</a>`;
  function analysesHTML(analyses, deps) {
    const list = array(analyses).filter((item) => item && (item.conclusion || item.node || array(item.tags).length));
    if (!list.length) return '';
    const items = list.map((item) => {
      const meta = [item.date ? shortDate(item.date) : '', item.node].filter(Boolean).join(' · ');
      const tags = array(item.tags).filter(Boolean);
      return `<li class="analysis-item"><div class="analysis-meta">${deps.esc(meta || '分析')}</div><p>${deps.esc(item.conclusion || '')}</p>${tags.length ? `<div class="chip-row">${tags.map((tag) => tagChipHTML(tag, deps)).join('')}</div>` : ''}</li>`;
    }).join('');
    return `<section class="analyses"><h3>分析<span class="verification"> ${list.length}</span></h3><ul class="analysis-list">${items}</ul></section>`;
  }
  function postDataHTML(post, account, deps) {
    return `${timelineHTML(post, deps)}${retentionHTML(post.retention, account?.platform || post.platform, deps)}${analysesHTML(post.analyses, deps)}`;
  }
  // 作品详情的「数据」：最新一次、D1/D3/D7 三格、分析。data 是 /api/works/<id> 的 metrics。
  function workMetricsHTML(data, deps) {
    const rows = array(data?.observations);
    const latest = data?.latest?.metrics ? data.latest : rows.length ? { at: rows[rows.length - 1].at, age_hours: rows[rows.length - 1].age_hours, metrics: rows[rows.length - 1].metrics } : null;
    if (!latest?.metrics && !array(data?.analyses).length) return '<p class="small-empty">这件作品还没有记录数据。</p>';
    const fake = { source_kind: 'workspace_metrics', metrics: latest?.metrics || {} };
    const latestBlock = latest?.metrics ? `${metricsHTML(fake, { window: 'latest' })}<p class="metric-period">${deps.esc(shortTime(latest.at))} 记录${known(latest.age_hours) ? ` · 发布后 ${Math.round(latest.age_hours)} h` : ''}</p>` : '';
    const nodes = data?.nodes || {};
    const cells = NODES.map((window) => {
      const node = nodes[window];
      const views = node?.metrics?.views;
      const over = node ? lateHours(window, node.age_hours, node.late_hours) : 0;
      return `<div class="node-cell${node ? '' : ' empty'}"><span class="metric-label">${window}</span><strong>${known(views) ? amount(views) : '—'}</strong>${node?.at ? `<small>${deps.esc(shortDate(node.at))}${over ? ` · 晚 ${over}h` : ''}</small>` : ''}</div>`;
    }).join('');
    const timeline = rows.length > 1 ? timelineHTML({ source_kind: 'workspace_metrics', history: rows.map((row) => ({ ...row, observed_at: row.at })) }, deps) : '';
    return `<div class="work-metrics">${latestBlock}<div class="node-cells">${cells}</div>${timeline}${retentionHTML(data?.retention, rows[rows.length - 1]?.platform, deps)}${analysesHTML(data?.analyses, deps)}</div>`;
  }
  function postDialogHTML(post,account,state,deps) {
    const context = metricContext(post,state.window);
    const url = deps.safeExternalURL(post.url);
    const name = accountLabel(account, state.dashboard?.accounts, deps);
    return `<header class="detail-header"><div class="detail-heading"><h2 id="post-dialog-title">${deps.esc(postTitle(post))}</h2><div class="detail-meta">${deps.esc(account?.brand || '')} · ${deps.esc(name)}${post.published_at ? ` · ${deps.esc(shortTime(post.published_at))}` : ''}</div></div><button type="button" class="icon-button" data-action="close-post" aria-label="关闭内容记录">${deps.icon('x')}</button></header><div class="post-dialog-body">${postMediaHTML(post,account,deps,true)}${metricsHTML(post,state)}${postDataHTML(post, account, deps)}<div class="panel-heading"><h3>${post.caption_complete ? '完整文案' : '原记录文案摘录'}</h3>${post.caption ? `<button type="button" class="button small" data-post-copy="${deps.esc(post.id)}">${deps.icon('copy')}复制文案</button>` : ''}</div><p class="post-caption">${deps.esc(post.caption || '没有收录文案。')}</p>${post.work_id ? `<div class="post-actions"><button type="button" class="button" data-post-work="${deps.esc(post.work_id)}">${deps.icon('stack')}对应作品</button>${url ? `<a class="button" href="${deps.esc(url)}" target="_blank" rel="noopener noreferrer">平台原文</a>` : ''}</div>` : url ? `<div class="post-actions"><a class="button" href="${deps.esc(url)}" target="_blank" rel="noopener noreferrer">平台原文</a></div>` : ''}<details class="post-source"><summary>来源与采样</summary><div>${post.title && postTitle(post) !== post.title ? `原始标题：${deps.esc(post.title)}<br>` : ''}${post.content_id ? `内容编号：${deps.esc(post.content_id)}<br>` : ''}${context.cohort ? `当前节点：${deps.esc(context.cohort)}<br>` : ''}采样：${deps.esc(context.at || '未记载')}<br>来源：${deps.esc(post.source || '未记载')}${array(post.issues).length ? `<p class="work-warning">${deps.esc(post.issues.join('；'))}</p>` : ''}</div></details></div>`;
  }
  const exported = { accountBackendHTML,metaSuiteHTML,metaSuiteAccount,postTitle,metricValue,metricText,metricContext,historySeries,accountPosts,selectedItems,amount,percent,shortDate,shortTime,platformHTML,renderOverview,renderIntelligence,postDialogHTML,
    platformLabel,seriesKey,listboxHTML,headingHTML,errorHTML,localDay,daysBetween,addDays,staleDays,todayOf,latestSample,dayLabel,todayHTML,welcomeHTML,newIntelCount,freshIntel,sortIntel,candidateGroups,intelStateText,
    hasWindowData,hasAnyData,captureHint,postListItems,workPreviewHTML,STALE_DAYS,CAPTURE_WEEK_DAYS,POST_LIST_LIMIT,
    accountLabel,accountHandle,lateHours,nodeChipHTML,timelineHTML,retentionHTML,analysesHTML,tagHash,tagChipHTML,postDataHTML,workMetricsHTML,isWorkspacePost,PERCENT_KEYS };
  if (typeof module !== 'undefined' && module.exports) module.exports = exported;
  if (scope) scope.MediaDashboard = exported;
})(typeof window === 'undefined' ? null : window);
