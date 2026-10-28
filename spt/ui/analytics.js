'use strict';

// 数据页：账号快照趋势、平台对比、内容表现。只读 dashboard 里已有的数据，不补造数值。
// 颜色都交给 CSS：每条序列包在 .series.series-<key> 里，JS 不写颜色值。
((scope) => {
  const dash = scope ? scope.MediaDashboard : require('./dashboard.js');
  const browser = !!scope && typeof document !== 'undefined';
  const array = (value) => Array.isArray(value) ? value : [];
  const known = (value) => typeof value === 'number' && Number.isFinite(value);
  const { amount, shortDate, metricValue, postTitle, seriesKey, platformLabel, staleDays, todayOf, daysBetween } = dash;
  const METRICS = [['followers', '粉丝'], ['views', '浏览'], ['reach', '触达'], ['interactions', '互动'], ['profile_visits', '主页访问'], ['page_visits', '主页访问'], ['follows_gained', '新增关注'], ['link_clicks', '链接点击']];
  const LABEL = Object.fromEntries(METRICS);
  const KPI_KEYS = ['followers', 'views', 'reach', 'interactions'];
  const TREND_KEYS = [['followers', '粉丝'], ['views', '浏览'], ['reach', '触达'], ['interactions', '互动']];
  const RANGES = [['all', '全部时间'], ['90', '近 90 天'], ['30', '近 30 天']];
  // 内容排名看哪一次：默认 D3，比 D1 稳、又比 D7 来得快。
  const RANK_WINDOWS = [['D1', '发布后 24 小时'], ['D3', '发布后 72 小时'], ['D7', '发布后 7 天']];
  const RANK_DEFAULT = 'D3';
  // 内容表现的两种看法：按浏览排名，或按分析里写的原因（标签）数。
  const CONTENT_VIEWS = [['rank', '排名'], ['tags', '原因标签']];
  // 排名表里这几列只在有人记了的时候才出现。
  const RATE_COLUMNS = [['completion_rate', '完播率'], ['ctr', '点击率'], ['avg_watch_sec', '平均观看秒']];
  const FORMATS = { video: '视频', reel: 'Reels', carousel: '轮播', image: '图片' };
  const BIG_JUMP = 3;    // 比之前大 3 倍以上（或只剩三分之一）：多半是口径变了，先核对
  const MIN_JUMP = 50;   // 差得太少（比如 2 变 7）不算异常
  const SMALL_BASE = 100; // 基数不到 100 时百分比没意义，只写差多少
  const DAY = 86400000;
  const dayValue = (date) => Date.UTC(+date.slice(0, 4), +date.slice(5, 7) - 1, +date.slice(8, 10));
  const isoOf = (time) => new Date(time).toISOString().slice(0, 10);
  // 这一页正在画的全部账号：同品牌同平台有几个号时，名字里才带账号名。
  let allAccounts = [];
  const labelOf = (account, deps) => dash.accountLabel(account, allAccounts, deps);
  const compact = (value) => {
    if (!known(value)) return '—';
    const abs = Math.abs(value);
    if (abs >= 1e6) return `${(value / 1e6).toFixed(1).replace(/\.0$/, '')}M`;
    if (abs >= 1e5) return `${(value / 1e3).toFixed(1).replace(/\.0$/, '')}K`;
    return amount(value);
  };

  // 一个账号某指标的快照序列：按日期去重、只留有数值的点。
  function series(account, key) {
    const seen = new Map();
    for (const snapshot of array(account?.history)) {
      const value = snapshot?.metrics?.[key];
      if (!/^\d{4}-\d{2}-\d{2}$/.test(String(snapshot?.date || '')) || !known(value)) continue;
      seen.set(snapshot.date, { date: snapshot.date, value, status: snapshot.status || null, window_start: snapshot.window_start || null, window_end: snapshot.window_end || null });
    }
    return [...seen.values()].sort((a, b) => a.date.localeCompare(b.date));
  }
  // 「近 30 天」从今天往回数，不是从最后一次记录往回数。
  function rangeStart(range, today) {
    if (range === 'all' || !today || !Number(range)) return null;
    return isoOf(dayValue(today) - Number(range) * DAY);
  }
  function clip(points, range, today) {
    const start = rangeStart(range, today);
    return start ? points.filter((point) => point.date >= start) : points;
  }
  // 页头的「截至」：账号快照的日期，和工作区里给这些账号的内容记数据的日期，取最新的一天。
  function latestDate(accounts, posts = []) {
    const day = (value) => { const match = String(value || '').match(/^\d{4}-\d{2}-\d{2}/); return match ? match[0] : ''; };
    const dates = accounts.flatMap((account) => array(account.history).map((item) => String(item?.date || '')).filter((date) => /^\d{4}-\d{2}-\d{2}$/.test(date)));
    const ids = new Set(accounts.map((account) => account.id));
    for (const post of array(posts)) {
      if (!ids.has(post?.account_id) || !dash.isWorkspacePost(post)) continue;
      for (const value of [post.observed_at, ...array(post.history).map((item) => item?.observed_at)]) { const date = day(value); if (date) dates.push(date); }
    }
    return dates.sort().pop() || null;
  }
  // 最新值和约 7 天前（最近的更早快照）的差。
  function delta(points, days = 7) {
    if (points.length < 2) return null;
    const last = points[points.length - 1];
    const floor = dayValue(last.date) - days * DAY;
    const earlier = [...points].reverse().find((point) => dayValue(point.date) <= floor) || points[0];
    if (earlier === last) return null;
    const diff = last.value - earlier.value;
    return { diff, pct: earlier.value ? diff / earlier.value * 100 : null, since: earlier.date, from: earlier.value, to: last.value };
  }
  // 变化怎么写：基数小只写差多少；跳得太大先核对；这两种都不用红绿色。
  function changeInfo(change) {
    if (!change) return null;
    const { diff, from, to } = change;
    const text = `${diff > 0 ? '+' : ''}${amount(diff)}`;
    if (diff === 0) return { tone: 'neutral', text: '持平', flat: true };
    const jump = Math.abs(diff) >= MIN_JUMP && (from > 0 ? to / from > BIG_JUMP || to / from < 1 / BIG_JUMP : to > 0);
    if (jump) return { tone: 'check', text, flag: '变化很大，先核对' };
    if (!(from >= SMALL_BASE)) return { tone: 'neutral', text };
    const pct = diff / from * 100;
    return { tone: diff > 0 ? 'up' : 'down', text: `${text} (${pct > 0 ? '+' : ''}${pct.toFixed(1)}%)` };
  }
  // 纵轴最大值：取 1、1.2、1.5、2、2.5、3、4、5、6、8 乘 10 的几次方里第一个够大的整数。
  const NICE = [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10];
  function niceMax(value) {
    if (!(value > 1)) return 1;
    const power = 10 ** Math.floor(Math.log10(value));
    for (const step of NICE) {
      const candidate = Math.round(step * power * 1e6) / 1e6;
      if (candidate >= value && Number.isInteger(candidate)) return candidate;
    }
    return 10 * power;
  }
  // 纵轴刻度：把最大值等分成 3 到 6 段，每段是整数，优先 1、2、5 开头的步长，再优先 4、5 段。
  function axisTicks(max) {
    const mantissa = (step) => step / 10 ** Math.floor(Math.log10(step));
    const score = (step) => {
      const m = Math.round(mantissa(step) * 100) / 100;
      return [1, 2, 5, 10].includes(m) ? 0 : m === 2.5 ? 1 : [1.5, 3].includes(m) ? 2 : null;
    };
    let best = null;
    for (const count of [3, 4, 5, 6]) {
      const step = max / count;
      if (!Number.isInteger(step) || step <= 0) continue;
      const base = score(step);
      if (base === null) continue;
      const total = base + (count === 4 || count === 5 ? 0 : 0.5);
      if (!best || total < best.total) best = { count, total };
    }
    const count = best ? best.count : Number.isInteger(max / 2) ? 2 : 1;
    return Array.from({ length: count + 1 }, (_, index) => max / count * index);
  }
  function linePath(points, x, y) {
    return points.map((point, index) => `${index ? 'L' : 'M'}${x(point.date).toFixed(1)} ${y(point.value).toFixed(1)}`).join(' ');
  }
  function sparklineSVG(points, platform = 'other') {
    if (points.length < 2) return '';
    const width = 120; const height = 34;
    const max = Math.max(...points.map((point) => point.value)); const min = Math.min(...points.map((point) => point.value));
    const first = dayValue(points[0].date); const span = Math.max(1, dayValue(points[points.length - 1].date) - first);
    const x = (date) => (dayValue(date) - first) / span * width;
    const y = (value) => max === min ? height / 2 : height - 3 - (value - min) / (max - min) * (height - 6);
    const line = linePath(points, x, y);
    // 拉伸到卡片宽度；线宽由 CSS 的 non-scaling-stroke 保持不变。
    return `<svg class="sparkline series series-${seriesKey(platform)}" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true" focusable="false"><path class="area" d="${line} L${width} ${height} L0 ${height} Z"/><path class="line" d="${line}"/></svg>`;
  }

  // ---- 趋势图 ----
  // 按真实像素宽度画（viewBox 的宽 = 屏幕上的宽），所以字在任何宽度都是 12px。
  const CHART = { font: 12, lineHeight: 14, top: 12, bottom: 26, gap: 10, minHeight: 200, maxHeight: 300, ratio: 0.36, minMarkerGap: 9, tickSpacing: 64 };
  // 每个平台除了颜色还有自己的点形和线型（线型在 CSS 的 --dash 里），色弱也分得清。
  const SHAPES = { instagram: 'circle', facebook: 'square', tiktok: 'triangle', rednote: 'diamond', youtube: 'down', google: 'plus', yelp: 'star', other: 'circle' };
  const shapeOf = (platform) => SHAPES[seriesKey(platform)] || 'circle';
  const fixed = (value) => value.toFixed(1);
  function markerPath(shape, cx, cy, r = 4.5) {
    const poly = (points) => `M${points.map(([dx, dy]) => `${fixed(cx + dx)} ${fixed(cy + dy)}`).join(' L')} Z`;
    switch (shape) {
      case 'square': { const s = r * 0.88; return poly([[-s, -s], [s, -s], [s, s], [-s, s]]); }
      case 'triangle': return poly([[0, -r * 1.2], [r * 1.1, r * 0.85], [-r * 1.1, r * 0.85]]);
      case 'down': return poly([[0, r * 1.2], [r * 1.1, -r * 0.85], [-r * 1.1, -r * 0.85]]);
      case 'diamond': return poly([[0, -r * 1.25], [r * 1.05, 0], [0, r * 1.25], [-r * 1.05, 0]]);
      case 'plus': { const a = r * 0.42; const b = r * 1.1; return poly([[-a, -b], [a, -b], [a, -a], [b, -a], [b, a], [a, a], [a, b], [-a, b], [-a, a], [-b, a], [-b, -a], [-a, -a]]); }
      case 'star': return poly(Array.from({ length: 10 }, (_, index) => { const radius = index % 2 ? r * 0.55 : r * 1.3; const angle = -Math.PI / 2 + index * Math.PI / 5; return [Math.cos(angle) * radius, Math.sin(angle) * radius]; }));
      default: return `M${fixed(cx - r)} ${fixed(cy)} a${r} ${r} 0 1 0 ${fixed(2 * r)} 0 a${r} ${r} 0 1 0 ${fixed(-2 * r)} 0 Z`;
    }
  }
  // 估算一段字在 12px 下有多宽（中文一个字一格，数字和字母窄一些）。
  function textWidth(text, size = CHART.font) {
    let units = 0;
    for (const char of String(text)) {
      if (/[⺀-鿿豈-﫿＀-￯　-〿]/.test(char)) units += 1;
      else if (/[0-9]/.test(char)) units += 0.6;
      else if (/[A-Z]/.test(char)) units += 0.68;
      else if (/[a-z]/.test(char)) units += 0.55;
      else if (char === ' ') units += 0.3;
      else units += 0.4;
    }
    return units * size;
  }
  function fitText(text, room) {
    if (textWidth(text) <= room) return text;
    const chars = [...String(text)];
    while (chars.length > 1 && textWidth(`${chars.join('')}…`) > room) chars.pop();
    return `${chars.join('')}…`;
  }
  // 横轴日期：从起点到终点等分，按天数取整，宽度越窄刻度越少。
  function dayTicks(from, to, plotWidth) {
    const span = Math.round((dayValue(to) - dayValue(from)) / DAY);
    if (span <= 0) return [from];
    const most = Math.max(2, Math.min(6, Math.floor(plotWidth / CHART.tickSpacing) + 1));
    const count = Math.min(most, span + 1);
    return [...new Set(Array.from({ length: count }, (_, index) => isoOf(dayValue(from) + Math.round(index * span / (count - 1)) * DAY)))];
  }
  // 右边的平台名上下错开，不互相压住。want 是这条线最后一个点的高度。
  function dodge(blocks, min, max, gap = 4) {
    const order = [...blocks].sort((a, b) => a.want - b.want);
    let floor = min;
    for (const block of order) { block.top = Math.max(block.want - 7, floor); floor = block.top + block.height + gap; }
    let ceiling = max;
    for (const block of [...order].reverse()) { if (block.top + block.height > ceiling) block.top = ceiling - block.height; ceiling = block.top - gap; }
    for (const block of order) block.top = Math.max(min, block.top);
    return blocks;
  }
  // 多条序列的折线图。seriesList: [{label, platform, points}]
  // options: width（像素）、from/to（横轴起止日期）、gapFrom（这天之后没有数据，画成阴影）、model（回填画了什么）
  function lineChartSVG(seriesList, key, deps, options = {}) {
    const shown = seriesList.filter((item) => item.points.length);
    if (!shown.some((item) => item.points.length >= 2)) return '';
    const width = Math.max(240, Math.round(options.width || 720));
    const height = Math.round(Math.min(CHART.maxHeight, Math.max(CHART.minHeight, width * CHART.ratio)));
    const all = shown.flatMap((item) => item.points);
    const dates = all.map((point) => point.date).sort();
    const dataFrom = dates[0]; const dataTo = dates[dates.length - 1];
    const from = options.from && options.from < dataFrom ? options.from : dataFrom;
    const to = options.to && options.to > dataTo ? options.to : dataTo;
    const max = niceMax(Math.max(...all.map((point) => point.value)) * 1.08);
    const ticks = axisTicks(max);
    const plotLeft = Math.ceil(Math.max(...ticks.map((tick) => textWidth(compact(tick))))) + 12;
    // 右边一栏：点形 + 平台名，下一行是最后的数；比别的线早结束的再写「截至哪天」。
    const ends = shown.map((item) => {
      const last = item.points[item.points.length - 1];
      return { item, last, value: compact(last.value), until: last.date < dataTo ? `截至 ${shortDate(last.date)}` : '' };
    });
    const widest = Math.max(...ends.map((end) => Math.max(textWidth(end.item.label), textWidth(end.value) * 1.08, end.until ? textWidth(end.until) : 0)));
    const textRoom = Math.min(Math.ceil(widest), Math.max(40, Math.floor(width * 0.4) - 26));
    const plotRight = width - textRoom - 26;
    const plotWidth = plotRight - plotLeft;
    const plotTop = CHART.top; const plotBottom = height - CHART.bottom;
    const start = dayValue(from); const span = dayValue(to) - start;
    const x = (date) => span ? plotLeft + (dayValue(date) - start) / span * plotWidth : plotLeft + plotWidth / 2;
    const y = (value) => plotTop + (1 - value / max) * (plotBottom - plotTop);
    const gapFrom = options.gapFrom && options.gapFrom >= from && options.gapFrom < to ? options.gapFrom : null;
    const band = gapFrom ? `<rect class="gap-band" x="${fixed(x(gapFrom))}" y="${plotTop}" width="${fixed(plotRight - x(gapFrom))}" height="${plotBottom - plotTop}"/><line class="gap-edge" x1="${fixed(x(gapFrom))}" x2="${fixed(x(gapFrom))}" y1="${plotTop}" y2="${plotBottom}"/>` : '';
    const grid = ticks.map((tick) => `<line class="grid-line" x1="${plotLeft}" x2="${fixed(plotRight)}" y1="${fixed(y(tick))}" y2="${fixed(y(tick))}"/><text class="axis-label" x="${plotLeft - 8}" y="${fixed(y(tick) + 4)}" text-anchor="end">${compact(tick)}</text>`).join('');
    const picks = dayTicks(from, to, plotWidth);
    const anchor = (index) => picks.length === 1 ? 'middle' : index === 0 ? 'start' : index === picks.length - 1 ? 'end' : 'middle';
    const xLabels = picks.map((date, index) => `<text class="axis-label" x="${fixed(x(date))}" y="${height - 8}" text-anchor="${anchor(index)}">${shortDate(date)}</text>`).join('');
    let partial = false;
    const lines = ends.map(({ item, last }) => {
      const shape = shapeOf(item.platform);
      const xs = item.points.map((point) => x(point.date));
      // 点挤在一起时只画最后一个点，线本身已经说明了走势。
      const dense = xs.some((value, index) => index > 0 && value - xs[index - 1] < CHART.minMarkerGap);
      const marked = dense ? [item.points.length - 1] : item.points.map((_, index) => index);
      const path = item.points.length > 1 ? linePath(item.points, x, y) : '';
      const area = path ? `<path class="area" d="${path} L${fixed(x(last.date))} ${fixed(y(0))} L${fixed(x(item.points[0].date))} ${fixed(y(0))} Z"/>` : '';
      const dots = marked.map((index) => {
        const point = item.points[index];
        const hollow = point.status === 'partial';
        if (hollow) partial = true;
        const period = point.window_start && point.window_end ? deps.esc(`（${shortDate(point.window_start)} 至 ${shortDate(point.window_end)}）`) : '';
        return `<path class="dot${hollow ? ' partial' : ''}" d="${markerPath(shape, x(point.date), y(point.value))}"><title>${deps.esc(item.label)} · ${shortDate(point.date)}：${amount(point.value)}${period}</title></path>`;
      }).join('');
      return `<g class="series series-${seriesKey(item.platform)}">${area}${path ? `<path class="line" d="${path}"/>` : ''}${dots}</g>`;
    }).join('');
    const column = plotRight + CHART.gap;
    const blocks = dodge(ends.map((end) => ({ end, want: y(end.last.value), height: (end.until ? 3 : 2) * CHART.lineHeight })), 0, height);
    const labels = blocks.map(({ end, want, top }) => {
      const mark = top + 7;
      // 标签被挤开、而这条线一直画到右边时，用一小段线连回去。
      const leader = end.last.date === to && Math.abs(mark - want) > 4 ? `<path class="leader" d="M${fixed(plotRight + 6)} ${fixed(want)} L${fixed(column)} ${fixed(mark)}"/>` : '';
      return `<g class="series series-${seriesKey(end.item.platform)} end-label">${leader}<path class="dot" d="${markerPath(shapeOf(end.item.platform), column + 5, mark, 4)}"/><text class="end-name" x="${fixed(column + 14)}" y="${fixed(top + 11)}">${deps.esc(fitText(end.item.label, textRoom))}</text><text class="end-value" x="${fixed(column + 14)}" y="${fixed(top + 25)}">${end.value}</text>${end.until ? `<text class="end-date" x="${fixed(column + 14)}" y="${fixed(top + 39)}">${end.until}</text>` : ''}</g>`;
    }).join('');
    if (options.model) Object.assign(options.model, { width, height, partial });
    const summary = ends.map(({ item, last }) => `${item.label} ${item.points.length} 次记录，最新 ${amount(last.value)}（${shortDate(last.date)}）`).join('；');
    return `<svg class="line-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${deps.esc(`${LABEL[key] || key}趋势：${summary}`)}">${band}${grid}${xLabels}${lines}<g class="end-labels">${labels}</g></svg>`;
  }
  function legendKeySVG(platform) {
    return `<svg class="legend-key" viewBox="0 0 28 12" aria-hidden="true" focusable="false"><line class="line" x1="1" y1="6" x2="27" y2="6"/><path class="dot" d="${markerPath(shapeOf(platform), 14, 6, 4)}"/></svg>`;
  }
  function legendHTML(shown, deps, partial = false) {
    const items = shown.map((item) => `<span class="series series-${seriesKey(item.platform)}">${legendKeySVG(item.platform)}${deps.esc(item.label)}</span>`).join('');
    const note = partial ? `<span class="legend-note"><svg class="legend-dot" viewBox="0 0 12 12" aria-hidden="true" focusable="false"><path class="dot partial" d="${markerPath('circle', 6, 6, 4)}"/></svg>空心点：那天只记了一部分数字</span>` : '';
    return `<div class="chart-legend">${items}${note}</div>`;
  }
  // 图例 + 图，包在一个按宽度重画的盒子里。
  // The shaded days after the last record explain themselves: no caption under the chart.
  function chartInnerHTML(spec, width) {
    const model = {};
    const svg = lineChartSVG(spec.list, spec.key, spec.deps, { ...spec.options, width, model });
    return `${legendHTML(spec.list.filter((item) => item.points.length), spec.deps, model.partial)}${svg}`;
  }
  function chartBoxHTML(spec, width) {
    return `<div class="chart-box" data-chart="trend" data-width="${Math.round(width)}">${chartInnerHTML(spec, width)}</div>`;
  }

  // 浏览器里：页面插进去以后量一下盒子的真实宽度，不一样就按那个宽度重画；窗口变宽变窄时也一样。
  let chartSpec = null;
  let lastWidth = 0;
  let observer = null;
  let observed = null;
  let burst = { count: 0, at: 0 };
  function guessWidth() {
    if (!browser) return 720;
    const current = document.querySelector('.chart-box[data-chart="trend"]');
    if (current?.clientWidth) return current.clientWidth;
    if (lastWidth) return lastWidth;
    const view = document.getElementById('view');
    if (!view?.clientWidth) return 720;
    const pad = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--pad')) || 16;
    return Math.max(240, Math.round(view.clientWidth - pad * 2 - 2));
  }
  function fitCharts() {
    if (!browser) return;
    const box = document.querySelector('.chart-box[data-chart="trend"]');
    if (!box || !chartSpec) {
      observer?.disconnect();
      observed = null;
      return;
    }
    const width = Math.round(box.clientWidth);
    if (width > 0) {
      lastWidth = width;
      const now = Date.now();
      if (now - burst.at > 500) burst = { count: 0, at: now };
      // 滚动条出现又消失时可能来回跳，短时间内最多重画几次。
      if (Math.abs(width - Number(box.dataset.width || 0)) >= 2 && ++burst.count <= 4) {
        box.dataset.width = String(width);
        box.innerHTML = chartInnerHTML(chartSpec, width);
      }
    }
    if (observed !== box && typeof ResizeObserver === 'function') {
      observer?.disconnect();
      observer = new ResizeObserver(() => requestAnimationFrame(fitCharts));
      observer.observe(box);
      observed = box;
    }
  }

  // 和图表同一组数字的表格：每行一个日期，每列一个平台。
  function trendTableHTML(seriesList, key, deps) {
    const shown = seriesList.filter((item) => item.points.length);
    if (!shown.length) return '';
    const dates = [...new Set(shown.flatMap((item) => item.points.map((point) => point.date)))].sort().reverse();
    const lookup = shown.map((item) => new Map(item.points.map((point) => [point.date, point])));
    const head = `<tr><th scope="col">记录日期</th>${shown.map((item) => `<th scope="col" class="num"><span class="series series-${seriesKey(item.platform)}"><i class="swatch"></i>${deps.esc(item.label)}</span></th>`).join('')}</tr>`;
    const rows = dates.map((date) => `<tr><th scope="row">${deps.esc(date)}</th>${lookup.map((points) => { const point = points.get(date); return `<td class="num">${point ? amount(point.value) : '—'}</td>`; }).join('')}</tr>`).join('');
    return `<div class="table-wrap"><table class="data-table"><caption class="sr-only">${deps.esc(LABEL[key] || key)}：每次记下的数</caption><thead>${head}</thead><tbody>${rows}</tbody></table></div>`;
  }
  function scope_(state) {
    const data = state.dashboard || {};
    let accounts = array(data.accounts).filter((item) => state.brand === 'all' || item.brand_id === state.brand);
    const platform = state.analyticsPlatform || 'all';
    if (platform !== 'all') accounts = accounts.filter((item) => item.platform === platform);
    return { data, accounts, platform };
  }
  // 有没有任何数：账号快照里任何一项，或这个账号任何一条内容的数据。
  function hasData(account, posts) {
    return METRICS.some(([key]) => series(account, key).length) || array(posts).some((post) => post.account_id === account.id && ['latest', 'D1', 'D3', 'D7'].some((window) => metricValue(post, 'views', window) !== null || metricValue(post, 'interactions', window) !== null));
  }
  // 好几个品牌的数放在一起时，名字前面带上品牌。
  const namer = (accounts, deps) => {
    const multi = new Set(accounts.map((account) => account.brand_id)).size > 1;
    return (account) => multi ? `${account.brand || ''} ${labelOf(account, deps)}`.trim() : labelOf(account, deps);
  };
  function deltaHTML(change, deps) {
    const info = changeInfo(change);
    if (!info) return '只记过一次';
    if (info.flat) return `和 ${shortDate(change.since)} 一样`;
    return `<span class="kpi-delta ${info.tone}">${info.text}</span> 较 ${shortDate(change.since)}${info.flag ? ` <span class="chip" data-tone="warn">${deps.esc(info.flag)}</span>` : ''}`;
  }
  // latest: the page's 截至 date. A card or row names its own date only when it is older than that.
  function kpiHTML(accounts, range, today, deps, latest = null) {
    return `<div class="kpi-grid">${KPI_KEYS.map((key) => {
      const label = `<div class="kpi-head"><span class="metric-label">${LABEL[key]}${key === 'views' || key === 'reach' ? '<small>28 天累计</small>' : ''}</span></div>`;
      const full = accounts.map((account) => ({ account, all: series(account, key) })).filter((item) => item.all.length);
      const parts = full.map((item) => ({ ...item, points: clip(item.all, range, today) })).filter((item) => item.points.length);
      if (!parts.length) {
        const last = full.map((item) => item.all[item.all.length - 1].date).sort().pop();
        return `<section class="panel kpi-card empty">${label}<strong class="kpi-value">—</strong>${last ? `<small>最近一次 ${shortDate(last)}</small>` : ''}</section>`;
      }
      const lastOf = (part) => part.points[part.points.length - 1];
      const asOf = parts.map((part) => lastOf(part).date).sort().pop();
      if (parts.length === 1) {
        const [part] = parts;
        return `<section class="panel kpi-card">${label}<strong class="kpi-value">${compact(lastOf(part).value)}</strong>${sparklineSVG(part.points, part.account.platform)}<p class="kpi-change">${deltaHTML(delta(part.points), deps)}</p><small>${deps.esc(labelOf(part.account, deps))}${asOf !== latest ? ` · ${shortDate(asOf)}` : ''}</small></section>`;
      }
      // 几个平台：只把同一天的数相加。更早的那一行变淡、写上它的日期，不算进合计。
      const same = parts.filter((part) => lastOf(part).date === asOf);
      const older = parts.filter((part) => lastOf(part).date !== asOf);
      const total = same.reduce((sum, part) => sum + lastOf(part).value, 0);
      const name = namer(parts.map((part) => part.account), deps);
      const row = (part, old) => {
        const date = deps.esc(shortDate(lastOf(part).date));
        return `<li class="series series-${seriesKey(part.account.platform)}${old ? ' older' : ''}"${old ? ` title="${date} 的数，没算进合计"` : ''}><i class="swatch"></i><span>${deps.esc(name(part.account))}</span>${old ? `<small>${date}<span class="sr-only">，没算进合计</span></small>` : ''}<span class="num">${compact(lastOf(part).value)}</span></li>`;
      };
      const breakdown = `<ul class="kpi-breakdown">${same.map((part) => row(part, false)).join('')}${older.map((part) => row(part, true)).join('')}</ul>`;
      return `<section class="panel kpi-card">${label}<strong class="kpi-value">${compact(total)}</strong>${breakdown}${asOf !== latest ? `<small>截至 ${shortDate(asOf)}</small>` : ''}</section>`;
    }).join('')}</div>`;
  }
  function trendHTML(accounts, state, range, today, deps) {
    const key = TREND_KEYS.some(([id]) => id === state.analyticsMetric) ? state.analyticsMetric : 'views';
    const view = state.analyticsView === 'table' ? 'table' : 'chart';
    const withData = accounts.filter((account) => series(account, key).length);
    const name = namer(withData, deps);
    const list = accounts.map((account) => ({ label: name(account), platform: account.platform, points: clip(series(account, key), range, today) }));
    const toggle = `<div class="segmented" role="group" aria-label="显示方式"><button type="button" data-analytics-view="chart" aria-pressed="${view === 'chart'}">图表</button><button type="button" data-analytics-view="table" aria-pressed="${view === 'table'}">表格</button></div>`;
    const metric = dash.listboxHTML({ id: 'analytics-metric', label: '趋势指标', value: key, options: TREND_KEYS });
    const head = `<div class="panel-head"><h2 class="panel-title" id="trend-title">趋势</h2>${metric}${toggle}</div>`;
    let body;
    if (!list.some((item) => item.points.length)) {
      const last = withData.map((account) => series(account, key).pop().date).sort().pop();
      const rangeName = RANGES.find(([id]) => id === range)?.[1] || '';
      // Older records exist: one button widens the range to them.
      body = range !== 'all' && last
        ? `<div class="empty-state compact"><strong>${rangeName}没有${LABEL[key] || ''}的记录</strong><div class="empty-actions"><button type="button" class="button primary" data-analytics-range="all">看全部时间</button><a class="button" href="#tools?name=data">导入数据</a></div></div>`
        : `<div class="empty-state compact"><strong>还没有${LABEL[key] || ''}的记录</strong><a class="button primary" href="#tools?name=data">导入数据</a></div>`;
    } else if (view === 'table') {
      body = trendTableHTML(list, key, deps);
    } else if (!list.some((item) => item.points.length >= 2)) {
      body = `<div class="empty-state compact"><strong>记录太少，还画不出趋势</strong><button type="button" class="button" data-analytics-view="table">看表格</button></div>`;
    } else {
      const lastData = list.flatMap((item) => item.points.map((point) => point.date)).sort().pop();
      const start = rangeStart(range, today);
      // 近 30/90 天：横轴一直画到今天，最后一次记录之后的空白画成阴影。
      const gapFrom = start && daysBetween(lastData, today) >= 2 ? lastData : null;
      chartSpec = { list, key, deps, options: { from: start || undefined, to: start ? today : undefined, gapFrom } };
      body = chartBoxHTML(chartSpec, guessWidth());
    }
    return `<section class="panel trend-panel" aria-labelledby="trend-title">${head}${body}</section>`;
  }
  // 一个平台的卡片；empty 表示这个范围里一个数都没有。latest 是页头的「截至」日期，比它旧才写自己的日期。
  function platformCard(account, range, today, deps, latest = null) {
    const rows = METRICS.filter(([key]) => !(key === 'page_visits' && account.platform !== 'facebook') && !(key === 'profile_visits' && account.platform === 'facebook')).map(([key, label]) => {
      const points = clip(series(account, key), range, today);
      if (!points.length) return '';
      const change = delta(points);
      const info = changeInfo(change);
      const small = info ? `<small class="${info.tone}" title="较 ${shortDate(change.since)}">${info.flat ? '持平' : info.text}${info.flag ? ' · 先核对' : ''}</small>` : '<small></small>';
      return `<div class="platform-metric"><span>${label}</span><strong>${compact(points[points.length - 1].value)}</strong>${small}</div>`;
    }).filter(Boolean);
    const head = `<div class="post-heading">${dash.platformHTML(account, deps)}<div><h3>${deps.esc(labelOf(account, deps))}</h3><span class="source-caption">${deps.esc(account.brand)}${account.handle ? ` · ${deps.esc(String(account.handle).replace(/^https?:\/\//, '').slice(0, 40))}` : ''}</span></div></div>`;
    const profileURL = account.profile_url ? deps.safeExternalURL(account.profile_url) : '';
    const profile = profileURL ? `<a class="text-action" href="${deps.esc(profileURL)}" target="_blank" rel="noopener noreferrer" title="在浏览器打开">公开主页<span class="sr-only">（在浏览器打开）</span> ${deps.icon('arrow-square-out')}</a>` : '';
    if (!rows.length) {
      const body = account.readonly
        ? `<p class="small-empty">只读资料</p>${profile}`
        : `<p class="small-empty">还没有数据</p><a class="text-action" href="#tools?name=data">导入数据</a>${profile}`;
      return { empty: true, html: `<section class="panel platform-card empty">${head}${body}</section>` };
    }
    const last = METRICS.flatMap(([key]) => clip(series(account, key), range, today).map((point) => point.date)).sort().pop();
    const spark = ['views', 'followers', 'interactions'].map((key) => clip(series(account, key), range, today)).find((points) => points.length >= 2) || [];
    const asOf = last && last !== latest ? `<p class="source-caption">截至 ${deps.esc(shortDate(last))}</p>` : '';
    return { empty: false, html: `<section class="panel platform-card series series-${seriesKey(account.platform)}">${head}${sparklineSVG(spark, account.platform)}<div class="platform-metrics">${rows.join('')}</div>${asOf}</section>` };
  }
  function platformCardsHTML(accounts, range, today, deps, latest = null) {
    const cards = accounts.map((account) => platformCard(account, range, today, deps, latest));
    const full = cards.filter((card) => !card.empty).map((card) => card.html);
    const empty = cards.filter((card) => card.empty).map((card) => card.html);
    const grid = full.length ? `<div class="platform-grid">${full.join('')}</div>` : '';
    // 没有数据的平台收起来；一个有数据的都没有时直接展开。
    const rest = empty.length ? `<details class="platform-empty"${full.length ? '' : ' open'}><summary>${empty.length} 个平台还没有数据</summary><div class="platform-grid">${empty.join('')}</div></details>` : '';
    return grid + rest;
  }
  function rankWindow(state) {
    return RANK_WINDOWS.some(([id]) => id === state.window) ? state.window : RANK_DEFAULT;
  }
  function rankThumbHTML(post, account, works, deps) {
    const work = post.work_id ? works.get(post.work_id) : null;
    const cover = deps.safeLocalURL(post.cover) || deps.safeLocalURL(work?.cover);
    return cover ? `<span class="rank-thumb"><img src="${deps.esc(cover)}" alt="" loading="lazy" decoding="async"></span>` : dash.platformHTML(account, deps);
  }
  // 分析里的原因标签：快照统计过的（analysis_tags）加上每条内容自己带的分析，只算正在看的这些账号的内容，按内容数排。
  function analysisTags(data, posts) {
    const byId = new Map(posts.map((post) => [post.id, post]));
    const tags = new Map();
    const add = (tag, post) => {
      const name = String(tag || '').trim();
      if (!name || !post) return;
      const entry = tags.get(name) || { tag: name, posts: [] };
      if (!entry.posts.includes(post)) entry.posts.push(post);
      tags.set(name, entry);
    };
    for (const item of array(data.snapshot?.analysis_tags)) for (const id of array(item?.post_ids)) add(item.tag, byId.get(id));
    for (const post of posts) for (const analysis of array(post.analyses)) for (const tag of array(analysis?.tags)) add(tag, post);
    // 同样多的按先出现的顺序（sort 是稳定的），不按字典序：不同机器的中文排序不一样。
    return [...tags.values()].map((entry) => ({ ...entry, count: entry.posts.length })).sort((a, b) => b.count - a.count);
  }
  function tagsHTML(rows, state, byId, deps) {
    if (!rows.length) return '<div class="empty-state compact"><strong>还没有分析</strong></div>';
    const wanted = String(state.analyticsTag || '');
    const picked = wanted ? rows.find((row) => row.tag === wanted) : null;
    if (wanted && !picked) return `<div class="empty-state compact"><strong>还没有「${deps.esc(wanted)}」的分析</strong><button type="button" class="button" data-analytics-tag="">全部原因</button></div>`;
    const shown = picked ? [picked] : rows;
    const chip = (post) => {
      const account = byId.get(post.account_id);
      const title = [labelOf(account, deps), post.published_at ? shortDate(post.published_at) : ''].filter(Boolean).join(' · ');
      return `<button type="button" class="chip tag-post" data-post-open="${deps.esc(post.id)}" title="${deps.esc(title)}">${deps.esc(postTitle(post))}</button>`;
    };
    const body = shown.map((row) => `<tr><th scope="row"><button type="button" class="chip tag-chip" data-analytics-tag="${deps.esc(row.tag)}" aria-pressed="${row === picked}">${deps.esc(row.tag)}</button></th><td class="num">${row.count}</td><td class="tag-posts"><div class="chip-row">${row.posts.map(chip).join('')}</div></td></tr>`).join('');
    const table = `<div class="table-wrap"><table class="data-table tag-table"><caption class="sr-only">分析里写到的原因，按内容数排</caption><thead><tr><th scope="col">原因</th><th scope="col" class="num">内容数</th><th scope="col">内容</th></tr></thead><tbody>${body}</tbody></table></div>`;
    const foot = picked && rows.length > 1 ? `<div class="post-list-foot"><span class="source-caption">共 ${rows.length} 个原因</span><button type="button" class="text-action" data-analytics-tag="">全部 ${deps.icon('caret-right')}</button></div>` : '';
    return table + foot;
  }
  function contentHTML(accounts, state, deps) {
    const data = state.dashboard || {};
    const ids = new Set(accounts.map((account) => account.id));
    const byId = new Map(accounts.map((account) => [account.id, account]));
    const works = new Map(array(state.allWorks).map((work) => [work.id, work]));
    const posts =array(data.posts).filter((post) => ids.has(post.account_id) && post.current !== false && post.source_kind !== 'metric_node');
    const tagRows = analysisTags(data, posts);
    const contentView = state.analyticsContent === 'tags' ? 'tags' : 'rank';
    // 一条分析都没有时不放切换：切过去也是空的。地址 #analytics?view=tags 照样能到。
    const viewSwitch = tagRows.length || contentView === 'tags' ? `<div class="segmented" role="group" aria-label="内容怎么看">${CONTENT_VIEWS.map(([id, label]) => `<button type="button" data-analytics-content="${id}" aria-pressed="${contentView === id}">${label}</button>`).join('')}</div>` : '';
    if (contentView === 'tags') return `<section class="panel content-panel" aria-labelledby="content-title"><div class="panel-head"><h2 class="panel-title" id="content-title">内容表现</h2>${viewSwitch}</div>${tagsHTML(tagRows, state, byId, deps)}</section>`;
    const withViews = (id) => posts.some((post) => metricValue(post, 'views', id) !== null);
    // 一条 D1/D3/D7 都没记过时按最新一次排，也就没有节点可切换。
    const windowed = RANK_WINDOWS.some(([id]) => withViews(id));
    const window = windowed ? rankWindow(state) : 'latest';
    const name = windowed ? window : '最新';
    const ranked = posts.map((post) => ({ post, views: metricValue(post, 'views', window) })).filter((item) => known(item.views)).sort((a, b) => b.views - a.views);
    const max = Math.max(1, ...ranked.map((item) => item.views));
    const top = ranked.slice(0, 12);
    const showPlatform = new Set(top.map(({ post }) => byId.get(post.account_id)?.platform)).size > 1;
    // 一整列都是空的就不放这一列。
    const others = RANK_WINDOWS.map(([id]) => id).filter((id) => id !== window && top.some(({ post }) => metricValue(post, 'views', id) !== null));
    const interactions = top.some(({ post }) => metricValue(post, 'interactions', window) !== null);
    const rates = RATE_COLUMNS.filter(([key]) => top.some(({ post }) => metricValue(post, key, window) !== null));
    const rows = top.map(({ post, views }, index) => {
      const account = byId.get(post.account_id);
      const subtitle = [post.published_at ? shortDate(post.published_at) : '日期未知', showPlatform ? labelOf(account, deps) : '', FORMATS[post.format] || post.format || ''].filter(Boolean).join(' · ');
      const cells = others.map((id) => `<td class="num extra">${dash.metricText(post, 'views', id)}</td>`).join('');
      const rateCells = rates.map(([key]) => `<td class="num extra">${dash.metricText(post, key, window)}</td>`).join('');
      return `<tr><td class="rank num">${index + 1}</td><td><button type="button" class="table-work" data-post-open="${deps.esc(post.id)}">${rankThumbHTML(post, account, works, deps)}<span><span class="work-title">${deps.esc(postTitle(post))}</span><span class="work-subtitle">${deps.esc(subtitle)}</span></span></button></td><td class="bar-cell series series-${seriesKey(account?.platform)}"><span class="rank-bar" style="--bar-size:${(views / max * 100).toFixed(1)}%"></span><strong>${compact(views)}</strong></td>${cells}${interactions ? `<td class="num extra">${dash.metricText(post, 'interactions', window)}</td>` : ''}${rateCells}</tr>`;
    }).join('');
    const alternatives = RANK_WINDOWS.map(([id]) => id).filter((id) => id !== window && withViews(id));
    const empty = alternatives.length
      ? `<div class="empty-state compact"><strong>${window} 还没有浏览数据</strong><div class="empty-actions">${alternatives.map((id) => `<button type="button" class="button" data-analytics-window="${id}">看 ${id}</button>`).join('')}</div></div>`
      : `<div class="empty-state compact"><strong>还没有内容的浏览数据</strong><a class="button primary" href="#tools?name=data">导入数据</a></div>`;
    const headCells = `<th scope="col" class="num">#</th><th scope="col">内容</th><th scope="col">${name} 浏览</th>${others.map((id) => `<th scope="col" class="num extra">${id}</th>`).join('')}${interactions ? `<th scope="col" class="num extra">${name} 互动</th>` : ''}${rates.map(([, label]) => `<th scope="col" class="num extra">${label}</th>`).join('')}`;
    const table = `<div class="table-wrap"><table class="data-table rank-table"><caption class="sr-only">按 ${windowed ? window : '最新一次'} 浏览排名的内容</caption><thead><tr>${headCells}</tr></thead><tbody>${rows}</tbody></table></div>`;
    const control = windowed ? `<div class="segmented" role="group" aria-label="按哪一次排名">${RANK_WINDOWS.map(([id, label]) => `<button type="button" data-analytics-window="${id}" aria-pressed="${window === id}" title="${label}">${id}</button>`).join('')}</div>` : '';
    return `<section class="panel content-panel" aria-labelledby="content-title"><div class="panel-head"><h2 class="panel-title" id="content-title">内容表现</h2>${viewSwitch}${control}</div>${top.length ? table : empty}</section>`;
  }
  function controlsHTML(state, allAccounts, range) {
    const brands = [...new Map(allAccounts.map((item) => [item.brand_id, item.brand])).entries()];
    return `<div class="page-controls analytics-controls">${dash.listboxHTML({ id: 'brand-filter', label: '品牌', value: state.brand || 'all', options: [['all', '全部品牌'], ...brands.map(([id, name]) => [id ?? '', name || '未命名品牌'])] })}${dash.listboxHTML({ id: 'analytics-range', label: '时间范围', value: range, options: RANGES })}${readButtonHTML(state)}<a class="button" href="#tools?name=data">导入数据</a></div>`;
  }
  // 读数据: only inside the Mac app, which reads 小红书 with this Mac's login.
  function readButtonHTML(state) {
    if (!state.metricsReader) return '';
    return state.metricsReading
      ? '<button type="button" class="button" disabled aria-busy="true">正在读…</button>'
      : '<button type="button" class="button primary" data-action="read-metrics">读数据</button>';
  }
  // 只放有数据的平台（和正在看的那个）。没有数据的平台收在页尾「N 个平台还没有数据」里，这里不再数一遍。
  function platformChipsHTML(state, allAccounts, deps) {
    const inBrand = allAccounts.filter((item) => state.brand === 'all' || item.brand_id === state.brand);
    const posts = array(state.dashboard?.posts);
    const platform = state.analyticsPlatform || 'all';
    const platforms = new Map();
    for (const account of inBrand) {
      const entry = platforms.get(account.platform) || { label: account.platform_label || platformLabel(account.platform, deps), data: false };
      entry.data = entry.data || hasData(account, posts);
      platforms.set(account.platform, entry);
    }
    const shown = [...platforms.entries()].filter(([id, entry]) => entry.data || id === platform);
    if (!shown.length && platform === 'all') return '';
    const chips = `<div class="segmented platform-chips" role="group" aria-label="平台"><button type="button" data-analytics-platform="all" aria-pressed="${platform === 'all'}">全部平台</button>${shown.map(([id, entry]) => `<button type="button" class="series series-${seriesKey(id)}" data-analytics-platform="${deps.esc(id)}" aria-pressed="${platform === id}"><i class="swatch"></i>${deps.esc(entry.label)}</button>`).join('')}</div>`;
    return `<div class="platform-filter">${chips}</div>`;
  }
  function renderAnalytics(state, deps) {
    const { data, accounts } = scope_(state);
    const all = array(data.accounts);
    allAccounts = all;
    chartSpec = null;
    if (state.dashboardLoading && !state.dashboard) return `${dash.headingHTML('数据')}<div class="dashboard-skeleton" aria-busy="true" aria-label="正在读取数据"><div class="skeleton skeleton-card"></div><div class="skeleton skeleton-card"></div><div class="skeleton skeleton-card"></div></div>`;
    const today = todayOf(state);
    const latest = latestDate(accounts, data.posts);
    const range = RANGES.some(([id]) => id === state.analyticsRange) ? state.analyticsRange : 'all';
    const stale = latest ? staleDays(latest, today) : 0;
    // One date for the whole page; old data turns it into a warning.
    const sub = stale ? `<span class="chip" data-tone="warn">数据停在 ${shortDate(latest)}</span>` : latest ? `截至 ${shortDate(latest)}` : '';
    const error = dash.errorHTML(state.dashboardError, deps);
    if (!all.length) return `<section class="analytics-page">${dash.headingHTML('数据', `<div class="page-controls">${readButtonHTML(state)}<a class="button" href="#tools?name=data">导入数据</a></div>`)}${error}<div class="empty-state"><h2>还没有账号资料</h2><a class="button primary" href="#tools?name=accounts">添加账号</a></div></section>`;
    const html = `<section class="analytics-page">${dash.headingHTML('数据', controlsHTML(state, all, range), sub)}${error}${platformChipsHTML(state, all, deps)}${kpiHTML(accounts, range, today, deps, latest)}${trendHTML(accounts, state, range, today, deps)}${platformCardsHTML(accounts, range, today, deps, latest)}${contentHTML(accounts, state, deps)}</section>`;
    if (browser && chartSpec) queueMicrotask(fitCharts);
    return html;
  }
  const exported = { readButtonHTML, series, delta, changeInfo, clip, rangeStart, niceMax, axisTicks, compact, sparklineSVG, lineChartSVG, legendHTML, chartBoxHTML, trendTableHTML, latestDate, rankWindow, renderAnalytics, textWidth, fitCharts, analysisTags, tagsHTML };
  if (typeof module !== 'undefined' && module.exports) module.exports = exported;
  if (scope) scope.MediaAnalytics = exported;
})(typeof window === 'undefined' ? null : window);
