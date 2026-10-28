'use strict';

((scope) => {
  // 资产库的类型标签。Skills 不在这里：它的列表从「设置 › Skills」打开（#works?kind=skill），⌘K 照样搜得到。
  const KINDS = [
    { key: 'work', label: '作品', icon: 'stack' },
    { key: 'prompt', label: '提示词', icon: 'prompt' },
    { key: 'material', label: '素材', icon: 'material' },
    { key: 'record', label: '记录', icon: 'record' },
  ];
  const KIND_LABEL = { ...Object.fromEntries(KINDS.map((kind) => [kind.key, kind.label])), skill: 'Skills' };
  const TEXT_LABEL = { prompt: '提示词', material: '写法', record: '正文', skill: '说明' };
  const EXPORTS = [['xlsx', 'Excel 表格'], ['csv', 'CSV'], ['md', 'Markdown']];
  const COVERS = [['square', '统一方形'], ['portrait', '竖版 3:4'], ['original', '原始比例']];
  // ⌘K 搜索结果的分组顺序（便签不在资产库的类型里，但也能搜到）。
  const RESULT_GROUPS = [
    { key: 'work', label: '作品', icon: 'stack', unit: '件' },
    { key: 'prompt', label: '提示词', icon: 'prompt', unit: '条' },
    { key: 'material', label: '素材', icon: 'material', unit: '条' },
    { key: 'record', label: '记录', icon: 'record', unit: '条' },
    { key: 'note', label: '便签', icon: 'note', unit: '张' },
    { key: 'skill', label: 'Skills', icon: 'skill', unit: '个' },
  ];
  const ITEM_FIELDS = ['title', 'text', 'note', 'tags', 'tool', 'section', 'code'];
  const WORK_FIELDS = ['title', 'client', 'category', 'note', 'tags', 'tool'];
  const NOTE_FILE = /^(\d{8}-\d{6}-[a-z0-9]{4})\.md$/;
  const array = (value) => Array.isArray(value) ? value : [];
  const isKind = (value) => KINDS.some((kind) => kind.key === value);

  function itemFileURL(item, apiURL) {
    const value = item?.file_url;
    if (typeof value !== 'string' || !/^\/api\/items\/[a-f0-9]{20}\/file$/.test(value)) return '';
    return apiURL(value);
  }
  // 卡片用的小图：只认服务给的缩略图地址，否则退回原文件。
  function itemThumbURL(item, apiURL) {
    const value = item?.thumb_url;
    if (typeof value !== 'string' || !/^\/api\/items\/[a-f0-9]{20}\/thumb(\?v=[a-f0-9]{12})?$/.test(value)) return '';
    return apiURL(value);
  }
  function mediaKind(item) {
    const name = String(item?.file || '');
    if (/\.(mp4|mov|m4v|webm)$/i.test(name)) return 'video';
    if (/\.(jpe?g|png|webp|gif|avif)$/i.test(name)) return 'image';
    return '';
  }
  const copiesPath = (item) => item?.kind === 'skill' || (item?.kind === 'material' && !!item?.file && !item?.text);
  function copyText(item) {
    return copiesPath(item) ? String(item.path || '') : String(item?.text || '');
  }
  function copyLabel(item) {
    if (copiesPath(item)) return '复制路径';
    return `复制${TEXT_LABEL[item?.kind] || '内容'}`;
  }
  function isDocument(item) {
    return /\.md$/i.test(String(item?.path || '')) && item?.source !== '素材表';
  }
  // 能一键复制正文的条目（提示词、带写法的素材），⌘K 里给「复制」。
  function promptLike(item) {
    return ['prompt', 'material'].includes(item?.kind) && !copiesPath(item) && !!String(item?.text || '').trim();
  }
  // 复制路径时给完整路径：工作区里的相对路径接上工作区位置。
  function fullPath(path, root = '') {
    const value = String(path || '');
    if (!value || /^(\/|~)/.test(value) || !root) return value;
    return `${String(root).replace(/\/+$/, '')}/${value}`;
  }

  // -- 搜索：和服务端一样，按任意空白（含全角空格）切词，每个词都要出现，不分大小写 --
  const searchWords = (query) => String(query || '').toLowerCase().split(/\s+/).filter(Boolean);
  function matchesWords(entry, words, fields) {
    const haystack = fields.map((key) => String(entry?.[key] ?? '')).join('\n').toLowerCase();
    return words.every((word) => haystack.includes(word));
  }
  // 新结果回来之前，先用上一次的结果在本地筛一遍（只会少，不会多出不匹配的）。
  function narrowResults(results, query) {
    const words = searchWords(query);
    return {
      works: array(results?.works).filter((work) => matchesWords(work, words, WORK_FIELDS)),
      items: array(results?.items).filter((item) => matchesWords(item, words, ITEM_FIELDS)),
    };
  }
  function countKinds(results) {
    const counts = Object.fromEntries(RESULT_GROUPS.map((group) => [group.key, 0]));
    counts.work = array(results?.works).length;
    for (const item of array(results?.items)) if (Object.hasOwn(counts, item?.kind)) counts[item.kind] += 1;
    return counts;
  }
  function titleScore(title, words, query) {
    const name = String(title || '').toLowerCase(), whole = String(query || '').trim().toLowerCase();
    if (whole && name.startsWith(whole)) return 3;
    return words.length && words.every((word) => name.includes(word)) ? 2 : 1;
  }
  // 按类型分组，组内标题命中的排前面；每组只留前 limit 个，total 是这一组一共几个。
  function groupResults(results, query = '', limit = 5) {
    const words = searchWords(query);
    const byKind = { work: array(results?.works).map((work) => ({ ...work, kind: 'work' })) };
    for (const item of array(results?.items)) (byKind[item?.kind] ||= []).push(item);
    return RESULT_GROUPS.filter((group) => byKind[group.key]?.length).map((group) => {
      const ranked = byKind[group.key].map((entry, index) => ({ entry, index, score: titleScore(entry.title, words, query) }))
        .sort((a, b) => b.score - a.score || a.index - b.index).map(({ entry }) => entry);
      return { ...group, total: ranked.length, entries: ranked.slice(0, Math.max(1, limit)) };
    });
  }
  // 作品卡片上的「复制」：定稿那一版的提示词；没定稿就用最新一版的；再没有就用作品根目录的提示词文档
  // （多份时第一份）；都没有才复制平台文案。定稿版本没存提示词时不拿别的版本顶替。
  // 返回 {text, label}，label 用在提示里。
  function workCopy(detail, platformName = (name) => name) {
    const work = detail?.work || {};
    const versions = array(detail?.versions);
    const adopted = versions.find((version) => version.is_current || (work.current_version && version.name === work.current_version));
    const latest = work.current_version ? null : versions.find((version) => version.name === work.latest_version) || versions.at(-1);
    const version = adopted || latest;
    if (String(version?.prompt || '').trim()) return { text: version.prompt, label: `${adopted ? '定稿' : '最新'} ${version.name} 的提示词` };
    const doc = array(detail?.source_documents).find((entry) => /^提示词.*\.(md|txt)$/.test(entry?.name || '') && String(entry.text || '').trim());
    if (doc) return { text: String(doc.text).replace(/^---[ \t]*\n[\s\S]*?\n---[ \t]*(?:\n|$)/, '').trim() || doc.text, label: doc.name.replace(/\.(md|txt)$/, '') };
    for (const [platform, value] of Object.entries(detail?.package || {})) {
      const text = typeof value === 'string' ? value : value?.caption || value?.text || '';
      if (String(text).trim()) return { text, label: `${platformName(platform)} 文案` };
    }
    return { text: '', label: '' };
  }
  // 便签条目指回「便签」页上的那一张：文件名就是便签编号，上一级文件夹是分组。
  function noteRef(item) {
    const parts = String(item?.path || '').split('/');
    const match = NOTE_FILE.exec(parts.at(-1) || '');
    if (item?.kind !== 'note' || !match) return null;
    return { id: match[1], rope: parts.length >= 3 ? parts.at(-2) : String(item.section || '') };
  }

  function inline(text, esc) {
    return esc(text)
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (match, label, href) => /^https?:\/\//.test(href)
        ? `<a href="${href}" target="_blank" rel="noopener noreferrer">${label}</a>`
        : `<span class="md-link" title="${href}">${label}</span>`);
  }
  function tableHTML(lines, esc) {
    const cells = (line) => line.trim().replace(/^\||\|$/g, '').split('|').map((cell) => cell.trim());
    const [head, , ...rows] = lines;
    return `<div class="table-wrap md-table"><table><thead><tr>${cells(head).map((cell) => `<th>${inline(cell, esc)}</th>`).join('')}</tr></thead><tbody>${rows.map((row) => `<tr>${cells(row).map((cell) => `<td>${inline(cell, esc)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  }
  function markdownHTML(source, esc) {
    const lines = String(source || '').replace(/\r\n?/g, '\n').split('\n');
    const html = [];
    let paragraph = [];
    const flush = () => { if (paragraph.length) html.push(`<p>${paragraph.map((line) => inline(line, esc)).join('<br>')}</p>`); paragraph = []; };
    for (let index = 0; index < lines.length; index += 1) {
      const line = lines[index];
      const trimmed = line.trim();
      if (trimmed.startsWith('```')) {
        flush();
        const body = [];
        while (++index < lines.length && !lines[index].trim().startsWith('```')) body.push(lines[index]);
        html.push(`<pre class="md-code"><code>${esc(body.join('\n'))}</code></pre>`);
      } else if (/^#{1,4}\s+/.test(trimmed)) {
        flush();
        const level = Math.min(trimmed.match(/^#+/)[0].length + 2, 6);
        html.push(`<h${level} class="md-heading">${inline(trimmed.replace(/^#+\s+/, ''), esc)}</h${level}>`);
      } else if (trimmed.startsWith('|') && /^\|[\s:|-]+\|?$/.test((lines[index + 1] || '').trim())) {
        flush();
        const block = [line];
        while (index + 1 < lines.length && lines[index + 1].trim().startsWith('|')) block.push(lines[++index]);
        html.push(tableHTML(block, esc));
      } else if (/^([-*+]|\d+\.)\s+/.test(trimmed)) {
        flush();
        const ordered = /^\d+\./.test(trimmed);
        const items = [];
        index -= 1;
        const marker = ordered ? /^\d+\.\s+/ : /^[-*+]\s+/;
        while (index + 1 < lines.length && marker.test(lines[index + 1].trim())) items.push(lines[++index].trim().replace(marker, ''));
        const tag = ordered ? 'ol' : 'ul';
        html.push(`<${tag}>${items.map((item) => `<li>${inline(item, esc)}</li>`).join('')}</${tag}>`);
      } else if (trimmed.startsWith('>')) {
        flush();
        const quote = [];
        index -= 1;
        while (index + 1 < lines.length && lines[index + 1].trim().startsWith('>')) quote.push(lines[++index].trim().replace(/^>\s?/, ''));
        html.push(`<blockquote>${quote.map((item) => inline(item, esc)).join('<br>')}</blockquote>`);
      } else if (/^(-{3,}|\*{3,})$/.test(trimmed)) {
        flush();
        html.push('<hr>');
      } else if (!trimmed) {
        flush();
      } else paragraph.push(trimmed);
    }
    flush();
    return html.join('');
  }

  // 资产类型是真正的 tablist：选中的那个 tabindex=0，其余 -1（方向键切换由 spt.js 处理）。
  // 有搜索词时 counts 是各类型的匹配数（matching），一条都没有的类型变淡。
  function kindTabsHTML(selected, counts, deps, panelId = 'work-results', { matching = false } = {}) {
    const current = isKind(selected) ? selected : KINDS[0].key;
    return `<div class="kind-tabs${matching ? ' is-matching' : ''}" role="tablist" aria-label="资产类型">${KINDS.map((kind) => {
      const active = kind.key === current;
      const count = counts?.[kind.key];
      const known = Number.isFinite(count);
      return `<button type="button" class="kind-tab${active ? ' selected' : ''}${known && count === 0 ? ' is-empty' : ''}" role="tab" id="kind-tab-${kind.key}" aria-selected="${active}" aria-controls="${deps.esc(panelId)}" tabindex="${active ? 0 : -1}" data-kind="${kind.key}">${deps.icon(kind.icon)}<span>${kind.label}</span>${known ? `<span class="nav-count">${count}${matching ? '<span class="sr-only">个匹配</span>' : ''}</span>` : ''}</button>`;
    }).join('')}</div>`;
  }
  // 分组只有一个（又没选着）时不画：一排只写「全部 4、运营 4」的按钮没有用。
  const showsGroups = (sections, selected) => array(sections).length > 1 || !!selected;
  // 分组是筛选按钮，不是页面：用 aria-pressed。
  function sectionNavHTML(sections, selected, total, deps) {
    const chip = (value, label, count, chosen) => `<button type="button" class="category-link${chosen ? ' selected' : ''}" data-section="${deps.esc(value)}" aria-pressed="${chosen}">${label}<span class="nav-count">${count}</span></button>`;
    return chip('', `${deps.icon('folder-open')}全部`, total, !selected) + array(sections).map((section) => chip(section.name, deps.esc(section.name), section.count, selected === section.name)).join('');
  }
  // -- 客户：资产库的第一层 ------------------------------------------------------------
  // 没有客户的条目（提示词模板、记录）算「通用」，排在「自己」那一簇。
  const GENERAL_CLIENT = '通用';
  const PALETTE_SIZE = 8;
  // 8 个色位在夜灯主题下的色值。整理客户时选了色位就存这个值（客户.md 只认 #rrggbb）；画的时候认出来换回
  // var(--client-N)，白天主题跟着变。
  const PALETTE_HEX = ['#9fe6d0', '#a8d4ff', '#ffb8d2', '#ffd37a', '#f4a68c', '#c5e59a', '#d6b4ff', '#8fdce8'];
  const paletteSlot = (color) => PALETTE_HEX.indexOf(String(color || '').toLowerCase()) + 1;
  // 分组：服务给了 group 就用它；没给（旧服务、作品里推出来的）按类型：自己 / 客户。
  const OWN_GROUP = '自己', CLIENT_GROUP = '客户';
  const groupOf = (entry) => String(entry?.group ?? '').trim() || (entry?.kind === 'own' ? OWN_GROUP : CLIENT_GROUP);
  const validColor = (value) => /^#[0-9a-f]{6}$/i.test(String(value || '')) ? String(value).toLowerCase() : null;
  const madeUp = (code, kind = 'client') => ({ code, name: code, kind, color: null, index: 0 });
  // 客户名录：服务给了 health.clients 就照它的顺序；没给就从作品推（自家算自己，其余算客户；自家最前，再按简称）。
  // 作品里出现、名录里没有的简称补在后面。index 从 1 起，是配色用的位置。服务给了分组名就带上 group。
  function clientDirectory(health, works = []) {
    const listed = array(health?.clients).filter((entry) => typeof entry?.code === 'string' && entry.code.trim())
      .map((entry) => ({ code: entry.code.trim(), name: String(entry.name || '').trim() || entry.code.trim(), kind: entry.kind === 'own' ? 'own' : 'client', color: validColor(entry.color), ...(String(entry.group ?? '').trim() ? { group: String(entry.group).trim() } : {}) }));
    const known = new Set(listed.map((entry) => entry.code));
    const extra = new Set();
    for (const work of array(works)) { const code = String(work?.client || '').trim(); if (code && !known.has(code)) extra.add(code); }
    const byCode = (a, b) => (a === '自家' ? -1 : b === '自家' ? 1 : a.localeCompare(b, 'zh'));
    const derived = [...extra].sort(byCode).map((code) => ({ code, name: code, kind: code === '自家' ? 'own' : 'client', color: null }));
    return [...listed, ...derived].map((entry, index) => ({ ...entry, index: index + 1 }));
  }
  const clientOf = (clients, code) => (code ? array(clients).find((entry) => entry.code === code) : null) || null;
  const clientName = (clients, code) => clientOf(clients, code)?.name || String(code || '');
  // 色点：客户自己的颜色优先（是 8 个色位之一就换回主题色），否则按名录位置轮 8 个色；名录外的用默认灰。只是色点的底色，不碰文字。
  function swatchStyle(entry) {
    const slot = paletteSlot(entry?.color);
    if (slot) return ` style="--series:var(--client-${slot})"`;
    if (entry?.color) return ` style="--series:${entry.color}"`;
    return entry?.index > 0 ? ` style="--series:var(--client-${((entry.index - 1) % PALETTE_SIZE) + 1})"` : '';
  }
  // 分组的先后：health.client_groups 照文件顺序（没给就「自己、客户」）；名录里用到、单子上没有的分组补在后面。
  function clientGroupNames(health, clients = []) {
    const listed = array(health?.client_groups).map((name) => String(name ?? '').trim()).filter(Boolean);
    const names = listed.length ? [...new Set(listed)] : [OWN_GROUP, CLIENT_GROUP];
    for (const entry of array(clients)) { const name = groupOf(entry); if (!names.includes(name)) names.push(name); }
    return names;
  }
  // 簇的 key：自己、客户沿用 own / client（样式和测试认它们），别的分组按位置。
  const groupKey = (name, index) => (name === OWN_GROUP ? 'own' : name === CLIENT_GROUP ? 'client' : `group-${index}`);
  const swatchHTML = (entry) => `<i class="swatch" aria-hidden="true"${swatchStyle(entry)}></i>`;
  // 卡片和表格里的客户标签：色点 + 名字（名录里的名字，没有就用简称）。
  function clientTagHTML(code, clients, deps) {
    if (!code) return '';
    const entry = clientOf(clients, code);
    return `<span class="client-tag">${swatchHTML(entry)}<span>${deps.esc(entry?.name || code)}</span></span>`;
  }
  // 客户筛选行按分组分簇（默认「自己」和「客户」，通用在自己最前；分组名就是簇名，改了名就显示新名字）。
  // counts 是 简称 → 数量；一条都没有的不列，选中的哪怕是 0 也列；一个成员都没有的分组不画。
  // 只有自家（或只有通用）一个、又没选着时不值得一行：返回 []。groups 是分组的先后（clientGroupNames）。
  function clientChips(clients, counts, selected = '', { general = false, groups = null } = {}) {
    const count = (code) => Number(counts?.[code]) || 0;
    const entries = [];
    if (general && (count(GENERAL_CLIENT) || selected === GENERAL_CLIENT)) entries.push(madeUp(GENERAL_CLIENT, 'own'));
    for (const entry of array(clients)) if (count(entry.code) || entry.code === selected) entries.push(entry);
    for (const code of Object.keys(counts || {})) if (code && code !== GENERAL_CLIENT && count(code) && !entries.some((entry) => entry.code === code)) entries.push(madeUp(code));
    if (selected && !entries.some((entry) => entry.code === selected)) entries.push(madeUp(selected, selected === GENERAL_CLIENT ? 'own' : 'client'));
    if (!entries.length || (entries.length === 1 && entries[0].kind === 'own' && !selected)) return [];
    const names = array(groups).length ? [...array(groups)] : [OWN_GROUP, CLIENT_GROUP];
    for (const entry of entries) if (!names.includes(groupOf(entry))) names.push(groupOf(entry));
    return names.map((name, index) => ({ key: groupKey(name, index), name, chips: entries.filter((entry) => groupOf(entry) === name).map((entry) => ({ entry, count: count(entry.code) })) }))
      .filter((group) => group.chips.length);
  }
  function clientChipsHTML(groups, selected, total, deps) {
    if (!array(groups).length) return '';
    const chip = ({ entry, count }) => `<button type="button" class="category-link client-chip${entry.code === selected ? ' selected' : ''}" data-client="${deps.esc(entry.code)}" aria-pressed="${entry.code === selected}">${swatchHTML(entry)}${deps.esc(entry.name)}<span class="nav-count">${count}</span></button>`;
    const all = `<button type="button" class="category-link${selected ? '' : ' selected'}" data-client="" aria-pressed="${!selected}">${deps.icon('folder-open')}全部<span class="nav-count">${total}</span></button>`;
    return `<div class="chip-row client-chips">${all}${groups.map((group) => `<span class="chip-group" role="group" aria-label="${group.name}"><span class="chip-group-name" aria-hidden="true">${group.name}</span>${group.chips.map(chip).join('')}</span>`).join('')}</div>`;
  }
  // 总览：按分组先后（默认先「自己」再「客户」），每个客户一块（名录顺序），块里只放前 limit 条（列表本身就是新的在前）；
  // 一条都没有的客户不出现，一块都没有的分组也不出现。
  function groupByClient(entries, clients, { limit = 10, general = false, groups = null } = {}) {
    const lists = new Map();
    for (const entry of array(entries)) {
      const code = String(entry?.client || (general ? GENERAL_CLIENT : '')).trim();
      if (!code) continue;
      if (!lists.has(code)) lists.set(code, []);
      lists.get(code).push(entry);
    }
    const names = array(groups).length ? [...array(groups)] : [OWN_GROUP, CLIENT_GROUP];
    const tiers = names.map((name, index) => ({ key: groupKey(name, index), name, blocks: [] }));
    const place = (client) => {
      const list = lists.get(client.code);
      if (!list?.length) return;
      lists.delete(client.code);
      const name = groupOf(client);
      let tier = tiers.find((item) => item.name === name);
      if (!tier) { tier = { key: groupKey(name, tiers.length), name, blocks: [] }; tiers.push(tier); }
      tier.blocks.push({ client, total: list.length, entries: list.slice(0, Math.max(1, limit)) });
    };
    if (general) place(madeUp(GENERAL_CLIENT, 'own'));
    for (const client of array(clients)) place(client);
    for (const code of [...lists.keys()]) place(madeUp(code));
    return tiers.filter((tier) => tier.blocks.length);
  }
  // 总览的块：和 Skills 分组一样是可收起的 <details>（收起过的记在 view.closed，键是 client:简称）；
  // 旁边的「全部 N」选中这个客户。body(entries, block) 画块里的卡片或表格。
  function clientBlocksHTML(tiers, body, deps, view = {}) {
    return array(tiers).map((tier) => `<section class="client-tier" aria-labelledby="client-tier-${tier.key}"><h2 class="client-tier-name" id="client-tier-${tier.key}">${tier.name}</h2>${tier.blocks.map((block) => {
      const key = `client:${block.client.code}`, open = !view.closed?.has?.(key);
      return `<div class="client-block"><details class="item-group" data-group="${deps.esc(key)}"${open ? ' open' : ''}><summary class="item-group-head client-block-head" data-group-toggle="${deps.esc(key)}"><span class="icon i-caret-right item-group-caret" aria-hidden="true"></span>${swatchHTML(block.client)}<span class="item-group-name">${deps.esc(block.client.name)}</span><span class="nav-count">${block.total}</span></summary>${body(block.entries, block)}</details><button type="button" class="button small client-block-all" data-client="${deps.esc(block.client.code)}" aria-label="${deps.esc(block.client.name)}：全部 ${block.total}">全部 ${block.total}</button></div>`;
    }).join('')}</section>`).join('');
  }

  // -- 整理客户 -----------------------------------------------------------------------
  // 下拉选择统一用 SPTListbox：浏览器里是 window.SPTListbox，node 测试里直接 require。
  function listboxHTML(options) {
    const Listbox = (typeof window !== 'undefined' && window.SPTListbox) || (typeof require === 'function' ? require('./listbox.js') : null);
    return Listbox ? Listbox.listboxHTML(options) : '';
  }
  // 对话框里的分组 [{name, clients: [{code, name, color, works}]}]：分组照 clientGroupNames 的先后（空的也留着，好把客户挪进去），
  // 客户照名录顺序。name 和简称一样时留空（输入框的占位就是简称）。works 取 health 报的数和 counts（简称 → 作品数）里大的那个。
  function clientGroupsFor(health, clients, counts = {}) {
    const reported = new Map(array(health?.clients).map((entry) => [String(entry?.code || '').trim(), Number(entry?.works) || 0]));
    const groups = clientGroupNames(health, clients).map((name) => ({ name, clients: [] }));
    for (const entry of array(clients)) {
      const group = groups.find((item) => item.name === groupOf(entry));
      group.clients.push({ code: entry.code, name: entry.name === entry.code ? '' : entry.name, color: entry.color || null, works: Math.max(reported.get(entry.code) || 0, Number(counts?.[entry.code]) || 0) });
    }
    return groups;
  }
  // 发给 /api/clients/save 的内容：分组名去掉首尾空白，名字空着就用简称，颜色只认 #rrggbb；没名字又没人的分组不发。
  function clientsSavePayload(groups) {
    return { groups: array(groups).map((group) => ({ name: String(group?.name || '').trim(), clients: array(group?.clients).map((client) => ({ code: String(client?.code || ''), name: String(client?.name || '').trim() || String(client?.code || ''), color: validColor(client?.color) })) })).filter((group) => group.name || group.clients.length) };
  }
  // 存之前本地能看出来的问题（一句话），没有就 ''。
  function clientsSaveError(groups) {
    const names = array(groups).map((group) => String(group?.name || '').trim());
    if (names.some((name, index) => !name && array(groups[index]?.clients).length)) return '分组要有名字';
    const seen = new Set();
    for (const name of names.filter(Boolean)) { if (seen.has(name)) return `有两个「${name}」`; seen.add(name); }
    return '';
  }
  // 整理客户对话框。每个分组一节：标题可点了改名（view.editing 是正在改名的分组号，那一节画输入框）、空分组才有「删除分组」；
  // 每个客户一行：拖动把手、色点（点开 8 个色位 + 无）、简称、名字、作品数（0 件时换成「删除」）、「移到…」。
  function clientsDialogHTML(groups, deps, view = {}) {
    const list = array(groups);
    const options = list.map((group, index) => ({ value: String(index), label: String(group.name || '').trim() || '新分组' }));
    let position = 0;
    const row = (client, groupIndex, clientIndex) => {
      position += 1;
      const code = deps.esc(client.code), label = deps.esc(String(client.name || '').trim() || client.code);
      const slot = paletteSlot(client.color), works = Number(client.works) || 0;
      const dots = Array.from({ length: PALETTE_SIZE }, (_, index) => `<button type="button" class="swatch-option" data-client-color="${code}" data-color="${index + 1}" aria-pressed="${slot === index + 1}" aria-label="颜色 ${index + 1}"><i class="swatch" aria-hidden="true" style="--series:var(--client-${index + 1})"></i></button>`).join('')
        + `<button type="button" class="swatch-option swatch-none" data-client-color="${code}" data-color="" aria-pressed="${!client.color}" aria-label="无"><i class="swatch" aria-hidden="true"></i></button>`;
      const tail = works ? `<span class="client-works">${works} 件</span>` : `<button type="button" class="button small danger" data-client-delete="${code}">删除</button>`;
      const move = listboxHTML({ id: `client-move-${client.code}`, label: `移到…：${label}`, value: String(groupIndex), options, className: 'client-move' });
      return `<li class="client-row" draggable="true" data-client-row="${code}" data-group-index="${groupIndex}" data-client-index="${clientIndex}"><button type="button" class="client-handle" data-client-handle="${code}" aria-label="拖动排序：${label}" aria-keyshortcuts="Alt+ArrowUp Alt+ArrowDown">${deps.icon('list-bullets')}</button><details class="export-menu swatch-menu"><summary class="swatch-pick" aria-label="颜色：${label}"><i class="swatch" aria-hidden="true"${swatchStyle(client.color ? { color: client.color } : { index: position })}></i></summary><div class="swatch-options" role="group" aria-label="颜色">${dots}</div></details><span class="client-code">${code}</span><input class="client-name" data-client-name="${code}" value="${deps.esc(client.name || '')}" placeholder="${code}" maxlength="40" autocomplete="off" aria-label="名字：${code}">${tail}${move}</li>`;
    };
    const section = (group, index) => {
      const name = String(group.name || '').trim(), shown = deps.esc(name || '新分组'), members = array(group.clients);
      const head = view.editing === index
        ? `<input class="clients-group-input" data-group-input="${index}" value="${deps.esc(name)}" maxlength="30" autocomplete="off" aria-label="分组名">`
        : `<button type="button" class="clients-group-name" id="clients-group-${index}" data-group-rename="${index}" aria-label="改名：${shown}">${shown}</button>`;
      const remove = members.length ? '' : `<button type="button" class="button small danger" data-group-remove="${index}">删除分组</button>`;
      return `<section class="clients-group${members.length ? '' : ' is-empty'}" data-group-section="${index}" aria-label="${shown}"><header class="clients-group-head">${head}<span class="nav-count">${members.length}</span>${remove}</header><ul class="clients-list" data-group-list="${index}">${members.map((client, clientIndex) => row(client, index, clientIndex)).join('')}</ul></section>`;
    };
    const discard = '<div class="note-discard" id="clients-discard" role="alert" hidden><p>还没保存。</p><div class="note-bar-actions"><button type="button" class="button small" data-clients-discard-keep>继续整理</button><button type="button" class="button small danger" data-clients-discard>不保存</button><button type="submit" class="button small primary">保存</button></div></div>';
    return `<header class="detail-header"><div class="detail-heading"><h2 id="clients-title">整理客户</h2></div><button type="button" class="icon-button" data-action="close-clients" aria-label="关闭">${deps.icon('x')}</button></header><form class="clients-form" id="clients-form" method="dialog"><div class="clients-groups">${list.map(section).join('')}<button type="button" class="button clients-add-group" data-group-add>${deps.icon('plus')}新分组</button></div><p class="note-error" id="clients-error" role="alert" hidden></p>${discard}<footer class="note-editor-foot clients-foot"><button type="button" class="button" data-action="close-clients">取消</button><button type="submit" class="button primary" aria-keyshortcuts="Meta+Enter">保存</button></footer></form>`;
  }

  // 「⋯」菜单：整理客户 + 存放说明 + 导出表格（Skills 页也能只导出 Skills）。
  function exportMenuHTML(kind, deps, { guide = false, clients = false } = {}) {
    const link = (format, label, scoped) => `<a class="export-option" href="${deps.esc(deps.apiURL(`/api/export?format=${format}${scoped ? `&kind=${kind}` : ''}`))}" download>${deps.esc(label)}</a>`;
    const scoped = isKind(kind) || kind === 'skill' ? `<span class="export-caption">只导出${KIND_LABEL[kind]}</span>${EXPORTS.map(([format, label]) => link(format, label, true)).join('')}` : '';
    const parts = [clients ? '整理客户' : '', guide ? '存放说明' : ''].filter(Boolean);
    const name = parts.length ? `${parts.join('、')}和导出` : '导出表格';
    const clientsHTML = clients ? `<button type="button" class="export-option menu-action" data-action="organize-clients">${deps.icon('pencil')}<span>整理客户</span></button>` : '';
    const guideHTML = guide ? `<button type="button" class="export-option menu-action" data-action="open-guide">${deps.icon('info')}<span>存放说明</span></button>` : '';
    return `<details class="export-menu more-menu"><summary class="icon-button more-button" aria-label="${name}" title="${name}">${deps.icon('dots-three')}</summary><div class="export-options">${clientsHTML}${guideHTML}<span class="export-caption">导出全部资产</span>${EXPORTS.map(([format, label]) => link(format, label, false)).join('')}${scoped}</div></details>`;
  }
  // 「显示」小菜单：封面比例（按下的那个就是当前的）。
  function displayMenuHTML(cover, deps) {
    const current = COVERS.some(([key]) => key === cover) ? cover : COVERS[0][0];
    return `<details class="export-menu display-menu"><summary class="button" title="封面比例">${deps.icon('image')}<span>显示</span></summary><div class="export-options" role="group" aria-label="封面比例"><span class="export-caption" aria-hidden="true">封面比例</span>${COVERS.map(([key, label]) => `<button type="button" class="export-option menu-action" data-cover-mode="${key}" aria-pressed="${key === current}">${deps.icon('check')}<span>${label}</span></button>`).join('')}</div></details>`;
  }

  const pixels = (value) => Number.isInteger(value) && value > 0 && value < 100000 ? value : 0;
  // 卡片优先用缩略图（视频也是一张静图）；详情里的预览始终用原文件。
  function thumbHTML(item, deps, controls = false) {
    const kind = mediaKind(item);
    if (!kind) return '';
    const width = pixels(item.width); const height = pixels(item.height);
    const size = width && height ? ` width="${width}" height="${height}"` : '';
    const thumb = controls ? '' : itemThumbURL(item, deps.apiURL);
    if (thumb) return `<img src="${deps.esc(thumb)}" alt="" loading="lazy" decoding="async"${size}>`;
    const url = itemFileURL(item, deps.apiURL);
    if (!url) return '';
    if (kind === 'video') return `<video ${controls ? 'controls ' : 'muted '}preload="metadata" playsinline src="${deps.esc(url)}" aria-label="${deps.esc(item.title)}"></video>`;
    return `<img src="${deps.esc(url)}" alt="${controls ? deps.esc(item.title) : ''}" loading="lazy" decoding="async"${size}>`;
  }
  // inGroup：卡片已经排在同名分组下面，分组名不再在卡片上重复。
  function metaChips(item, deps, inGroup = false) {
    const parts = [inGroup ? '' : item.section, item.tags, item.source === '作品' ? '来自作品' : '', item.status];
    return parts.filter(Boolean).map((part) => `<span>${deps.esc(part)}</span>`).join('');
  }
  // clients：客户名录；条目带 client 时在 meta 前面加客户标签（名录没给就不加）。
  function itemCardHTML(item, deps, inGroup = false, clients = null) {
    const thumb = thumbHTML(item, deps);
    const text = item.kind === 'skill' ? item.note : item.text;
    const client = clients ? clientTagHTML(item.client, clients, deps) : '';
    const meta = metaChips(item, deps, inGroup);
    return `<article class="item-card${thumb ? ' has-thumb' : ''}${item.status ? ' is-muted' : ''}"><button type="button" class="item-open" data-item="${deps.esc(item.id)}" aria-label="查看${deps.esc(item.title)}">${thumb ? `<span class="item-thumb" data-media="${mediaKind(item)}">${thumb}</span>` : ''}<span class="item-head">${item.code ? `<span class="item-code">${deps.esc(item.code)}</span>` : ''}<span class="item-title" title="${deps.esc(item.title)}">${deps.esc(item.title)}</span></span>${text ? `<span class="item-text">${deps.esc(String(text).slice(0, 220))}</span>` : ''}${client || meta ? `<span class="item-meta">${client}${meta}</span>` : ''}</button><button type="button" class="item-copy" data-copy-item="${deps.esc(item.id)}" title="${copyLabel(item)}" aria-label="${copyLabel(item)}：${deps.esc(item.title)}"${copyText(item) ? '' : ' disabled'}>${deps.icon('copy')}</button></article>`;
  }
  function itemRowHTML(item, deps, clients = null) {
    const text = item.kind === 'skill' ? item.note : item.text;
    const client = clients ? clientTagHTML(item.client, clients, deps) : '';
    return `<tr><td><button type="button" class="table-work item-row-open" data-item="${deps.esc(item.id)}"><span><span class="work-title">${item.code ? `${deps.esc(item.code)} · ` : ''}${deps.esc(item.title)}</span><span class="table-version">${deps.esc(String(text || '').slice(0, 90))}</span></span></button></td><td>${client}${deps.esc(item.section)}</td><td>${deps.esc(item.tags || '')}</td><td><button type="button" class="button small" data-copy-item="${deps.esc(item.id)}" aria-label="${copyLabel(item)}：${deps.esc(item.title)}"${copyText(item) ? '' : ' disabled'}>${deps.icon('copy')}复制</button></td></tr>`;
  }
  // Codex 自带的 skill 一大堆，默认收起；展开过的分组名记在 open 里，重画时保持。
  const collapsedByDefault = (section) => /^Codex\b/i.test(String(section || ''));
  // 设置 › Skills：每个来源一行 {name, count, path}。Claude、Codex 装的在前（读到的目录哪怕一个也没有也列出），
  // 然后是库内（工作区的 skills 文件夹），最后是 SPT.yaml 接进来的外部来源。
  function skillGroups(sections, roots = [], workspace = '') {
    const rank = (name) => / 已安装$/.test(name) ? 0 : name === '库内' ? 1 : 2;
    const rows = array(sections).filter((section) => section?.name).map((section) => ({ name: String(section.name), count: Number(section.count) || 0, path: '' }));
    for (const root of array(roots)) {
      const match = /\/\.(claude|codex)\/skills\/?$/i.exec(String(root || ''));
      if (!match) continue;
      const name = `${match[1].toLowerCase() === 'claude' ? 'Claude' : 'Codex'} 已安装`;
      const row = rows.find((entry) => entry.name === name);
      if (row) row.path = String(root);
      else rows.push({ name, count: 0, path: String(root) });
    }
    const own = rows.find((entry) => entry.name === '库内');
    if (own && workspace) own.path = fullPath('skills', workspace);
    return rows.map((row, index) => ({ row, index })).sort((a, b) => rank(a.row.name) - rank(b.row.name) || a.index - b.index).map(({ row }) => row);
  }
  // view.grouped：按分组分块（Skills 没搜索、没选分组时）；每块是可以收起的 <details>。
  // view.clients：客户名录（卡片带客户标签）；view.byClient = {limit}：按客户分块的总览（全部、没搜索、没选分组时）。
  function itemsHTML(items, layout, deps, view = {}) {
    const clients = view.clients || null;
    const body = (list, inGroup = false) => layout === 'list'
      ? `<div class="table-wrap"><table class="data-table items-table"><thead><tr><th scope="col">条目</th><th scope="col">分组</th><th scope="col">标签</th><th scope="col"><span class="sr-only">复制</span></th></tr></thead><tbody>${list.map((item) => itemRowHTML(item, deps, clients)).join('')}</tbody></table></div>`
      : `<div class="items-grid">${list.map((item) => itemCardHTML(item, deps, inGroup, clients)).join('')}</div>`;
    if (view.byClient) return clientBlocksHTML(groupByClient(items, clients, { limit: view.byClient.limit, general: true, groups: view.groups }), (list) => body(list), deps, view);
    const groups = new Map();
    for (const item of array(items)) {
      const name = String(item.section || '未分类');
      if (!groups.has(name)) groups.set(name, []);
      groups.get(name).push(item);
    }
    if (!view.grouped || (groups.size < 2 && ![...groups.keys()].some(collapsedByDefault))) return body(array(items));
    return [...groups].map(([name, list]) => {
      const open = collapsedByDefault(name) ? !!view.open?.has?.(name) : !view.closed?.has?.(name);
      return `<details class="item-group" data-group="${deps.esc(name)}"${open ? ' open' : ''}><summary class="item-group-head" data-group-toggle="${deps.esc(name)}"><span class="icon i-caret-right item-group-caret" aria-hidden="true"></span><span class="item-group-name">${deps.esc(name)}</span><span class="nav-count">${list.length}</span></summary>${body(list, true)}</details>`;
    }).join('');
  }
  // 空的时候一句话加一个动作：没有东西就给「看存放说明」，搜不到就给「清除筛选」。
  // query 可选，用来回显搜的词；elsewhere 是别的类型里的匹配 [{key,label,count}]，每类一个跳过去的按钮。
  function emptyHTML(kind, filtered, deps, query = '', elsewhere = []) {
    const label = KIND_LABEL[kind] || '条目';
    if (filtered) {
      const words = String(query || '').trim();
      const others = array(elsewhere).filter((entry) => entry.count > 0 && entry.key !== kind && isKind(entry.key));
      const jump = others.map((entry) => `<button type="button" class="button" data-kind="${deps.esc(entry.key)}">看${deps.esc(entry.label)}（${entry.count}）</button>`).join('');
      return `<div class="empty-state">${deps.icon('magnifying-glass')}<h2>${words ? `${label}里没有“${deps.esc(words)}”` : `没有符合筛选的${label}`}</h2><div class="empty-actions">${jump}<button type="button" class="button${jump ? '' : ' primary'}" data-action="clear-filters">清除筛选</button></div></div>`;
    }
    return `<div class="empty-state">${deps.icon('folder-open')}<h2>还没有${label}</h2><button type="button" class="button primary" data-action="open-guide">${deps.icon('info')}看存放说明</button></div>`;
  }
  // 详情里的上一个、下一个、返回。nav = {prev, next, back}；不传就不画。
  function detailNavHTML(nav, deps) {
    if (!nav) return { back: '', steps: '' };
    const back = nav.back ? `<button type="button" class="icon-button detail-back" data-detail-back aria-label="返回上一个">${deps.icon('arrow-left')}</button>` : '';
    const steps = `<button type="button" class="icon-button detail-step" data-detail-step="-1" aria-label="上一个"${nav.prev ? '' : ' disabled'}>${deps.icon('caret-left')}</button><button type="button" class="icon-button detail-step" data-detail-step="1" aria-label="下一个"${nav.next ? '' : ' disabled'}>${deps.icon('caret-right')}</button>`;
    return { back, steps };
  }

  function itemDetailHTML(item, deps, nav = null) {
    const media = thumbHTML(item, deps, true);
    const controls = detailNavHTML(nav, deps);
    const meta = [KIND_LABEL[item.kind], item.section, item.code, item.tool, item.status, item.modified_at ? deps.readableTime(item.modified_at) : ''].filter(Boolean);
    const label = TEXT_LABEL[item.kind] || '内容';
    const textBlock = item.kind === 'skill' ? '' : isDocument(item)
      ? `<div class="md-body">${markdownHTML(item.body || item.text, deps.esc)}</div>`
      : `<pre class="prompt-text">${deps.esc(item.text || '')}</pre>${item.body && item.body !== item.text ? `<div class="md-body item-extra">${markdownHTML(item.body, deps.esc)}</div>` : ''}`;
    const skillBlock = item.kind === 'skill' ? `<div class="md-body">${markdownHTML(item.body || item.note, deps.esc)}</div>` : '';
    const fullCopy = isDocument(item) && item.body && item.body !== item.text;
    // 路径是普通文字，旁边一个明明白白的「复制路径」按钮（上面的复制按钮已经复制路径时就不重复）。
    const where = fullPath(item.path, deps.workspace?.());
    const pathHTML = item.path ? `<div class="item-path"><span class="item-path-text" title="${deps.esc(where)}">${deps.icon('folder')}<span>${deps.esc(item.path)}</span></span>${copiesPath(item) ? '' : `<button type="button" class="button small" data-copy-text="${deps.esc(where)}" aria-label="复制路径：${deps.esc(item.path)}">${deps.icon('copy')}复制路径</button>`}</div>` : '';
    return `<header class="detail-header">${controls.back}<div class="detail-heading"><h2 id="detail-title">${deps.esc(item.title)}</h2><div class="detail-meta">${meta.map((part) => `<span>${deps.esc(part)}</span>`).join('')}</div></div>${controls.steps}<button type="button" class="icon-button" data-action="close-detail" aria-label="关闭详情" autofocus>${deps.icon('x')}</button></header><div class="item-detail">${media ? `<div class="preview-stage">${media}</div>` : ''}${item.note && !String(item.text || '').startsWith(item.note) && item.kind !== 'skill' ? `<p class="item-note">${deps.esc(item.note)}</p>` : ''}${item.tags ? `<div class="item-meta">${String(item.tags).split(/[,，、]\s*/).filter(Boolean).map((tag) => `<span>${deps.esc(tag)}</span>`).join('')}</div>` : ''}<div class="panel-heading"><h3>${item.kind === 'skill' ? 'SKILL.md' : label}</h3><div class="item-actions"><button type="button" class="button small" data-copy-item="${deps.esc(item.id)}"${copyText(item) ? '' : ' disabled'}>${deps.icon('copy')}${copyLabel(item)}</button>${fullCopy ? `<button type="button" class="button small" data-copy-body="${deps.esc(item.id)}">${deps.icon('copy')}复制全文</button>` : ''}</div></div>${textBlock}${skillBlock}${pathHTML}${item.work_id ? `<div class="post-actions"><button type="button" class="button" data-work="${deps.esc(item.work_id)}">${deps.icon('stack')}打开所属作品</button></div>` : ''}</div>`;
  }

  const exported = { KINDS, KIND_LABEL, RESULT_GROUPS, GENERAL_CLIENT, PALETTE_HEX, collapsedByDefault, skillGroups, isKind, itemFileURL, itemThumbURL, mediaKind, copyText, copyLabel, isDocument, promptLike, fullPath, workCopy, searchWords, narrowResults, countKinds, groupResults, noteRef, markdownHTML, kindTabsHTML, showsGroups, sectionNavHTML, clientDirectory, clientOf, clientName, clientGroupNames, swatchStyle, clientTagHTML, clientChips, clientChipsHTML, groupByClient, clientBlocksHTML, clientGroupsFor, clientsSavePayload, clientsSaveError, clientsDialogHTML, exportMenuHTML, displayMenuHTML, itemCardHTML, itemRowHTML, itemsHTML, emptyHTML, detailNavHTML, itemDetailHTML };
  if (typeof module !== 'undefined' && module.exports) module.exports = exported;
  if (scope) scope.SPTLibrary = exported;
})(typeof window === 'undefined' ? null : window);
