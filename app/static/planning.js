'use strict';
(() => {
  const P = {accounts: [], accountId: '', data: null, media: [], tab: 'strategy', batchId: '', group: 1, questionEdit: '', itemEdit: '', observationEdit: '', loading: true, error: '', review: null, drafts: new Map(), generation: 0, active: false};
  const tabs = [['strategy', '01', '账号定位'], ['questions', '02', '真实问题库'], ['plan', '03', '12 篇计划'], ['review', '04', '每 4 篇复盘']];
  const types = {method: '方法', case: '案例', process: '过程', template: '模板'};
  const sources = {search: '搜索问题', comment: '读者评论', work_record: '工作记录', other: '其他真实来源'};
  const statuses = {needs_question: '待补问题', needs_material: '待补素材', ready_to_write: '可以开写', draft_created: '已转草稿'};
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  // Styled single-select shared with the SPT shell (/workspace/listbox.js); keeps the old id/name/data-* on a hidden input.
  const listbox = config => window.SPTListbox ? window.SPTListbox.listboxHTML(config) : '';
  const platformLabels = {instagram: 'Instagram', facebook: 'Facebook', tiktok: 'TikTok', youtube: 'YouTube', google_business: 'Google 商家', google_ads: 'Google Ads', xiaohongshu: 'rednote'};
  // Readable account handle: "@name" from a profile link, '' when the link only holds an internal ID.
  const handleText = value => { const raw = String(value ?? '').trim(); if (!/^https?:\/\//i.test(raw)) return raw && !/^@|\s/.test(raw) ? `@${raw}` : raw; try { const url = new URL(raw); if (!/(^|\.)(instagram\.com|tiktok\.com|youtube\.com|facebook\.com|threads\.net|x\.com|twitter\.com)$/i.test(url.hostname)) return ''; const first = decodeURIComponent(url.pathname.split('/').filter(Boolean)[0] || '').replace(/^@/, ''); return /^[\w.-]{2,40}$/.test(first) && !/^(channel|c|user|profile\.php|people|pages|watch|p|reel|reels|share|groups)$/i.test(first) ? `@${first}` : ''; } catch { return ''; } };
  const root = () => document.getElementById('media-planning');
  const checked = v => v ? ' checked' : '';
  const account = () => P.accounts.find(a => a.id === P.accountId);
  const batches = () => P.data?.batches || [];
  const batch = () => batches().find(b => b.id === P.batchId) || batches()[0];
  const cards = () => batch()?.cards || [];
  const questions = () => P.data?.questions || [];
  const activeQuestions = () => questions().filter(q => q.status !== 'parked');
  const inboxQuestions = () => questions().filter(q => q.status === 'inbox');
  const pillars = () => P.data?.strategy?.pillars || [];
  const num = v => v === null || v === undefined || v === '' ? '—' : Number(v).toLocaleString('zh-CN', {maximumFractionDigits: 2});
  const datetime = v => {
    if (!v) return '';
    const d = new Date(v); if (!Number.isFinite(d.getTime())) return '';
    return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  };
  const displayDate = v => { const d = new Date(v); return v && Number.isFinite(d.getTime()) ? d.toLocaleString('zh-CN', {month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit'}) : '未记录'; };
  const latest = id => (P.data?.observations || []).filter(o => o.item_id === id).sort((a, b) => String(b.observed_at).localeCompare(String(a.observed_at)) || String(b.created_at).localeCompare(String(a.created_at)) || String(b.id).localeCompare(String(a.id)))[0];
  function formKey(name, id = '') { return `${P.accountId}:${name}:${id}`; }
  function formValues(form) {
    const data = new FormData(form), values = Object.fromEntries(data.entries());
    values.media_ids = data.getAll('media_ids');
    values.material_ready = !!data.get('material_ready');
    return values;
  }
  function remember(form) { if (form?.dataset.planningForm) P.drafts.set(formKey(form.dataset.planningForm, form.dataset.recordId), formValues(form)); }
  function draft(name, id, fallback) { return P.drafts.get(formKey(name, id)) || fallback; }
  async function api(path, body) {
    const response = await fetch(path, body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    let data; try { data = await response.json(); } catch { throw Error('本地服务没有返回完整数据，请刷新重试。'); }
    if (!response.ok || data.error) throw Error(data.error || '未能保存，请重试。');
    return data;
  }
  // Shared toasts (✕ to close, errors stay) when the main page is loaded; the plain one is only a fallback.
  function toast(message, error = false) {
    if (window.MediaToast) { window.MediaToast(message, error); return; }
    const region = document.getElementById('toast-region');
    if (!region) return;
    const item = document.createElement('div'); item.className = `toast${error ? ' error' : ''}`; item.textContent = message; region.append(item); setTimeout(() => item.remove(), 6000);
  }
  function button(label, action, extra = '', primary = false) { return `<button type="button" class="planning-button${primary ? ' primary' : ''}" data-planning-action="${action}" ${extra}>${label}</button>`; }
  function field(label, name, value, {textarea = false, required = false, placeholder = '', help = '', type = 'text', rows = 3, max = 4000, step = 'any'} = {}) {
    return `<label class="planning-field"><span>${label}${required ? ' <em>必填</em>' : ''}</span>${textarea ? `<textarea name="${name}" rows="${rows}" maxlength="${max}" ${required ? 'required' : ''} placeholder="${esc(placeholder)}">${esc(value)}</textarea>` : `<input name="${name}" type="${type}" value="${esc(value)}" maxlength="${max}" ${required ? 'required' : ''} ${type === 'number' ? `min="0" step="${step}"` : ''} placeholder="${esc(placeholder)}">`}${help ? `<small>${help}</small>` : ''}</label>`;
  }
  function select(label, name, value, values, empty = '', scope = 'planning') {
    const options = [...(empty ? [['', empty]] : []), ...values.map(([id, title]) => [String(id), title])];
    return `<div class="planning-field"><span aria-hidden="true">${label}</span>${listbox({ id: `${scope}-${name}`, name, label, value: value ?? '', options, className: 'listbox-field' })}</div>`;
  }
  function empty(title, text, action = '') { return `<div class="planning-empty"><span class="planning-empty-mark">＋</span><h3>${title}</h3><p>${text}</p>${action}</div>`; }
  function render() { return '<section id="media-planning" class="planning-workspace" aria-label="内容计划"><div class="planning-loading"><span class="loading-spinner"></span><p>正在读取账号的内容计划…</p></div></section>'; }
  function header() {
    const strategy = P.data?.strategy;
    const active = inboxQuestions().length;
    const filled = cards().filter(c => c.question_id).length;
    const observed = cards().filter(c => latest(c.id)).length;
    return `<header class="planning-header"><div><span class="planning-kicker">内容成长 / 按账号积累</span><h1>内容计划</h1><p>先定方向，再做 12 篇。每完成 4 篇，用实际反馈调整下一组。</p></div><div class="planning-account"><span aria-hidden="true">当前账号</span>${listbox({ id: 'planning-account', label: '当前账号', value: P.accountId ?? '', className: 'listbox-quiet listbox-block', attrs: { 'data-planning-account': true }, options: P.accounts.map(a => [String(a.id), `${a.name || a.handle}${handleText(a.handle) && handleText(a.handle) !== a.name ? ` · ${handleText(a.handle)}` : ''} · ${platformLabels[a.platform] || a.platform}`]) })}<small>每个账号独立保存定位、选题和复盘</small></div></header><div class="planning-progress" aria-label="工作进度"><div><span>账号定位</span><strong>${strategy ? '已建立' : '待填写'}</strong><small>一个人群 · 一个问题 · 三个栏目</small></div><div><span>待选问题</span><strong>${active}<i> 条</i></strong><small>来自搜索、评论与自己的工作</small></div><div><span>本批选题</span><strong>${filled}<i> / 12</i></strong><small>问题不够时保留空位</small></div><div><span>本批观察</span><strong>${observed}<i> / 12</i></strong><small>手工记录 · 不代替平台数据</small></div></div>`;
  }
  function draw() {
    const el = root(); if (!P.active || !el) return;
    if (P.loading) { el.innerHTML = '<div class="planning-loading"><span class="loading-spinner"></span><p>正在读取账号的内容计划…</p></div>'; return; }
    if (P.error) { el.innerHTML = `<div class="planning-empty"><h2>暂时没有读到内容计划</h2><p>${esc(P.error)}</p>${button('重新读取', 'reload')}</div>`; return; }
    if (!P.accounts.length) { el.innerHTML = `<header class="planning-header"><div><span class="planning-kicker">内容成长</span><h1>先让计划有自己的账号。</h1><p>Instagram、Facebook、TikTok、YouTube、小红书等账号分别保存定位与选题。</p></div></header>${empty('添加第一个内容账号', '填入账号名称即可开始本地规划，不需要登录平台。Google Ads 广告数据仍在「数据导入」里管理。', '<a class="planning-button primary" href="#accounts">去添加账号 →</a>')}`; return; }
    el.innerHTML = `${header()}<div class="planning-tabs" role="tablist" aria-label="计划步骤">${tabs.map(([id, number, label]) => `<button type="button" role="tab" aria-selected="${P.tab === id}" class="${P.tab === id ? 'active' : ''}" data-planning-tab="${id}"><span>${number}</span>${label}</button>`).join('')}</div><div class="planning-stage" role="tabpanel">${P.tab === 'strategy' ? strategyView() : P.tab === 'questions' ? questionsView() : P.tab === 'plan' ? planView() : reviewView()}</div><details class="planning-ai"><summary><span>✦</span><strong>把当前资料交给 AI</strong><small>定位、问题出处、计划约束一起带走</small></summary><div class="planning-ai-body"><p>复制后交给你使用的 AI。这里整理已有信息，不会在网页中调用外部模型或自动编造素材。</p><textarea data-planning-prompt readonly aria-label="给 AI 的完整任务">${esc(aiPrompt())}</textarea><div class="planning-actions">${button('复制给 AI 的任务', 'copy-prompt')}<span class="planning-muted">内容仅来自当前账号与所选批次。</span></div></div></details><footer class="planning-source">方法参考：<a href="https://x.com/JessiCao_JC/status/2110614414890283326" target="_blank" rel="noopener noreferrer">JessiCao_JC 的内容实践分享 ↗</a><span>已转成可保存、可复盘的本地流程；效果需要实际发布后验证。</span></footer>`;
  }
  function strategyView() {
    const s = P.data?.strategy || {};
    const d = draft('strategy', '', {...s, pillar1: s.pillars?.[0] || '', pillar2: s.pillars?.[1] || '', pillar3: s.pillars?.[2] || ''});
    return `<div class="planning-split"><form class="planning-panel planning-form" data-planning-form="strategy"><div class="planning-panel-heading"><span class="planning-step">01</span><div><h2>这一个账号，持续帮助谁？</h2><p>写具体的人、具体场景，以及你能持续提供的经验。</p></div></div><div class="planning-form-grid">${field('目标读者', 'audience', d.audience, {required: true, placeholder: '例如：第一次独立做品牌短视频的小团队'})}${field('他们遇到的场景', 'scenario', d.scenario, {required: true, placeholder: '例如：每周要交付视频，缺少稳定的制作流程'})}</div>${field('持续解决的核心问题', 'problem', d.problem, {textarea: true, required: true, placeholder: '写清一个能长期回答的问题，先不追逐所有热门话题。'})}${field('你已经拥有的经验与素材', 'materials', d.materials, {textarea: true, required: true, placeholder: '真实项目、制作过程、失败记录、客户提问、可展示案例…', help: '只填写确实拥有或可以获得授权的素材。'})}<div class="planning-field"><span>三个固定栏目 <em>必填</em></span><div class="planning-pillar-fields">${[1, 2, 3].map(i => `<label><span>0${i}</span><input name="pillar${i}" value="${esc(d[`pillar${i}`])}" maxlength="80" required aria-label="栏目 ${i}" placeholder="栏目 ${i}"></label>`).join('')}</div><small>栏目是长期主题；方法、案例、过程、模板是呈现方式。</small></div><div class="planning-actions"><button class="planning-button primary" type="submit">保存账号定位</button>${s.updated_at ? `<span class="planning-muted">上次保存 ${esc(displayDate(s.updated_at))}</span>` : '<span class="planning-muted">保存后就可以收集问题。</span>'}</div></form><aside class="planning-side"><div class="planning-side-card green"><span class="planning-kicker">执行的起点</span><h2>先具体，<br>再持续。</h2><p>不从“今天发什么”开始。让同一类读者反复得到一个明确的帮助。</p><div class="planning-mini-path"><span>定位</span><b>→</b><span>真实问题</span><b>→</b><span>12 篇试做</span></div></div><div class="planning-side-card"><h3>填写完成的标准</h3><ul><li>能说出读者正在做什么。</li><li>能找到他们真正问过的问题。</li><li>三个栏目都有持续可用的素材。</li></ul>${button('去收集真实问题 →', 'tab', 'data-tab="questions"')}</div></aside></div>`;
  }
  function questionForm() {
    const original = questions().find(q => q.id === P.questionEdit) || {};
    const d = draft('question', P.questionEdit, {...original, priority: original.priority || 2, source_type: original.source_type || 'search', status: original.status || 'inbox'});
    const opts = pillars().map(x => [x, x]); if (d.pillar && !opts.some(x => x[0] === d.pillar)) opts.push([d.pillar, `${d.pillar}（原栏目）`]);
    return `<form class="planning-panel planning-form" data-planning-form="question" data-record-id="${esc(P.questionEdit)}" id="planning-question-editor"><div class="planning-panel-heading"><span class="planning-step">＋</span><div><h2>${P.questionEdit ? '编辑这个真实问题' : '收进一个真实问题'}</h2><p>保留原话与出处，再决定是否值得写。</p></div>${P.questionEdit ? button('新建问题', 'new-question') : ''}</div>${field('读者实际问了什么？', 'question', d.question, {required: true, textarea: true, placeholder: '粘贴问题原话，或根据真实工作记录准确转述。', max: 1000})}${field('问题出现的具体情境', 'context', d.context, {textarea: true, rows: 2, placeholder: '对方做到哪一步？具体哪里卡住了？'})}<div class="planning-form-grid">${select('来源类型', 'source_type', d.source_type, Object.entries(sources))}${select('所属栏目', 'pillar', d.pillar, opts, '选择栏目（可以稍后补充）', 'question')}</div>${field('来源链接', 'source_url', d.source_url, {type: 'url', placeholder: 'https://…（没有公开链接可留空）'})}${field('出处说明', 'source_note', d.source_note, {textarea: true, rows: 2, placeholder: '例如：哪条评论、哪次客户沟通、哪份工作记录；来源要可追溯。'})}${field('可以用什么真实素材回答？', 'materials', d.materials, {textarea: true, rows: 2, placeholder: '案例文件、截图、实操录像、自己的失败记录…'})}<div class="planning-form-grid">${select('优先级', 'priority', d.priority, [[1, '优先回答'], [2, '常规'], [3, '以后再做']])}${select('问题状态', 'status', d.status, [['inbox', '待选问题'], ['selected', '已进入计划'], ['parked', '暂时搁置']])}</div><label class="planning-check"><input name="material_ready" type="checkbox" value="true"${checked(d.material_ready)}><span>回答所需的素材已经备好</span></label><div class="planning-actions"><button class="planning-button primary" type="submit">${P.questionEdit ? '保存修改' : '加入问题库'}</button></div></form>`;
  }
  function questionsView() {
    const list = [...questions()].sort((a, b) => (a.status === 'parked') - (b.status === 'parked') || a.priority - b.priority);
    return `<div class="planning-section-heading"><div><h2>让选题有真实的出处。</h2><p>把搜索问题、读者评论、自己的工作记录汇成一个可复用的问题库。</p></div>${button('开始做 12 篇计划 →', 'tab', 'data-tab="plan"')}</div><div class="planning-questions-layout"><section class="planning-question-list">${list.length ? list.map(q => `<article class="planning-question-card${q.status === 'parked' ? ' parked' : ''}"><div class="planning-row"><span class="planning-tag">${esc(sources[q.source_type] || '真实来源')}</span><span class="planning-muted">${q.status === 'parked' ? '已搁置' : q.status === 'selected' ? '已进入计划' : q.priority === 1 ? '优先回答' : q.priority === 3 ? '以后再做' : '常规'}</span></div><h3>${esc(q.question)}</h3>${q.context ? `<p>${esc(q.context)}</p>` : ''}<div class="planning-question-source">${q.source_url ? `<a href="${esc(safeURL(q.source_url))}" target="_blank" rel="noopener noreferrer">查看来源 ↗</a>` : '<span>没有公开链接</span>'}${q.source_note ? `<span>${esc(q.source_note)}</span>` : '<span>待补出处说明</span>'}</div><div class="planning-row"><div class="planning-tags">${q.pillar ? `<span class="planning-tag light">${esc(q.pillar)}</span>` : ''}<span class="planning-tag ${q.material_ready ? 'green' : 'amber'}">${q.material_ready ? '素材已备好' : '待备素材'}</span></div>${button('编辑', 'edit-question', `data-id="${esc(q.id)}"`)}</div>${q.provenance ? '<small class="planning-feedback-origin">↳ 来自一篇内容的实际反馈</small>' : ''}</article>`).join('') : empty('问题库还是空的', '先收进 3—5 个你真的见过的问题。计划不足 12 个时会留空，不会替你编造读者需求。')}</section>${questionForm()}</div>`;
  }
  function batchToolbar() {
    return `<div class="planning-batch-toolbar"><div class="planning-batch-label"><span aria-hidden="true">当前批次</span>${listbox({ id: 'planning-batch', label: '当前批次', value: batch()?.id ?? '', className: 'listbox-quiet', attrs: { 'data-planning-batch': true }, options: batches().map(b => [String(b.id), b.name || `12 篇计划 · ${displayDate(b.created_at)}`]) })}</div><div class="planning-actions"><a class="planning-button" href="/api/planning/export?account_id=${encodeURIComponent(P.accountId)}&batch_id=${encodeURIComponent(batch()?.id || '')}" download>导出本批资料</a>${button('新建下一批', 'create-batch')}</div></div>`;
  }
  function planView() {
    if (!batch()) return `<div class="planning-plan-intro"><span class="planning-kicker">小步试做 · 持续调整</span><h2>12 篇，不是一口气写完。</h2><p>按三个小组推进：每组 4 篇，发布后记录反馈，再调整下一组。</p><div class="planning-type-counts">${Object.entries(types).map(([key, title]) => `<div><strong>${{method: 3, case: 4, process: 3, template: 2}[key]}</strong><span>篇${title}</span></div>`).join('')}</div><div class="planning-plan-condition"><span class="${P.data?.strategy ? 'ready' : ''}">${P.data?.strategy ? '✓' : '○'} 账号定位${P.data?.strategy ? '已保存' : '待完成'}</span><span>${inboxQuestions().length} 个待选问题</span></div>${button('建立 12 篇计划框架', 'create-batch', P.data?.strategy ? '' : 'disabled', true)}${!P.data?.strategy ? button('先填写定位', 'tab', 'data-tab="strategy"') : ''}<small>按固定结构分配真实问题。没有调用 AI；问题不足的卡片会留空。</small></div>`;
    const all = cards(), counts = Object.fromEntries(Object.keys(types).map(type => [type, all.filter(c => c.content_type === type).length]));
    return `${batchToolbar()}<div class="planning-section-heading"><div><h2>本批 12 篇，分成 3 组。</h2><p>先把问题、素材和希望得到的反馈写清楚，再写正文。</p></div><div class="planning-tags">${Object.entries(types).map(([type, title]) => `<span class="planning-tag light">${title} ${counts[type]}</span>`).join('')}</div></div><p class="planning-inline-note">框架由本地规则建立，标题与正文由你或 AI 完成。转成草稿只会进入本地发布计划。</p><div class="planning-groups">${[1, 2, 3].map(group => `<section class="planning-group"><header><span>第 ${group} 组</span><small>第 ${(group - 1) * 4 + 1}—${group * 4} 篇</small></header>${all.filter(c => c.group === group).sort((a, b) => a.position - b.position).map(cardView).join('')}<button type="button" class="planning-group-review" data-planning-action="review-group" data-group="${group}">记录这一组的反馈 →</button></section>`).join('')}</div>${P.itemEdit ? itemEditor() : ''}`;
  }
  function cardView(c) {
    const q = questions().find(q => q.id === c.question_id);
    return `<article class="planning-plan-card${P.itemEdit === c.id ? ' selected' : ''}"><div class="planning-row"><span class="planning-card-number">${String(c.position).padStart(2, '0')}</span><span class="planning-tag type-${esc(c.content_type)}">${esc(types[c.content_type] || c.content_type)}</span></div><h3>${esc(c.title || '待补标题')}</h3><p class="planning-card-question">${esc(c.question || q?.question || '还没有对应的真实问题')}</p><div class="planning-card-bottom"><span class="planning-tag ${c.status === 'ready_to_write' || c.status === 'draft_created' ? 'green' : 'amber'}">${esc(statuses[c.status] || '待完善')}</span>${c.draft_id && c.material_gap ? '<span class="planning-tag amber">材料待补</span>' : ''}${button(c.draft_sync_status === 'changed' ? '查看修改' : '打开编辑', 'edit-item', `data-id="${esc(c.id)}"`)}</div></article>`;
  }
  function itemEditor() {
    const c = cards().find(x => x.id === P.itemEdit); if (!c) return '';
    const d = draft('item', c.id, c);
    const qopts = activeQuestions().map(q => [q.id, q.question]);
    if (d.question_id && !qopts.some(x => x[0] === d.question_id)) { const q = questions().find(q => q.id === d.question_id); if (q) qopts.push([q.id, `${q.question}（已搁置）`]); }
    const popts = pillars().map(x => [x, x]); if (d.pillar && !popts.some(x => x[0] === d.pillar)) popts.push([d.pillar, `${d.pillar}（原栏目）`]);
    return `<form class="planning-panel planning-form planning-item-editor" data-planning-form="item" data-record-id="${esc(c.id)}" id="planning-item-editor"><div class="planning-panel-heading"><span class="planning-step">${String(c.position).padStart(2, '0')}</span><div><h2>把这一篇准备具体</h2><p>第 ${c.group} 组 · ${esc(c.title || '待补标题')}</p></div>${button('收起', 'close-item')}</div><div class="planning-form-grid">${select('要回答的真实问题', 'question_id', d.question_id, qopts, '待补真实问题')}${field('内容标题', 'title', d.title, {placeholder: '围绕这一个问题写清标题', max: 300})}${select('内容类型', 'content_type', d.content_type, Object.entries(types))}${select('所属栏目', 'pillar', d.pillar, popts, '待补栏目', 'item')}</div>${field('这一篇用什么素材证明？', 'material_plan', d.material_plan, {textarea: true, rows: 2, placeholder: '写具体案例、操作步骤、过程记录或模板文件。'})}<label class="planning-check planning-material-ready"><input name="material_ready" type="checkbox" value="true"${checked(d.material_ready)}><span>这一篇所需的真实素材已经备齐</span></label><div class="planning-form-grid">${field('读者看完可以做什么？', 'reader_action', d.reader_action, {textarea: true, rows: 2, placeholder: '一个可执行的小动作'})}${field('希望收到什么反馈？', 'expected_feedback', d.expected_feedback, {textarea: true, rows: 2, placeholder: '希望对方收藏什么、问什么、尝试什么'})}</div>${field('这一篇只验证什么变化？', 'variable', d.variable, {placeholder: '例如：换一种开头，其他表达与选题尽量保持一致'})}${field('正文 / 脚本', 'body', d.body, {textarea: true, rows: 9, max: 30000, placeholder: '在这里写完整文案，或把下方任务交给 AI，检查后粘贴回来。没有正文时不能转成草稿。'})}<fieldset class="planning-media"><legend>关联本地素材</legend>${P.media.length ? P.media.map(m => `<label class="planning-check"><input type="checkbox" name="media_ids" value="${esc(m.id)}"${checked((d.media_ids || []).includes(m.id))}><span>${esc(m.name)} <small>本地素材</small></span></label>`).join('') : '<p>还没有素材。<a href="#uploads">去加入视频或图片 →</a></p>'}</fieldset><div class="planning-actions"><button class="planning-button primary" type="submit">保存这一篇</button>${button(c.draft_id ? '打开现有草稿' : '转成本地草稿', 'create-draft', `data-id="${esc(c.id)}"`)}<span class="planning-muted">先保存编辑，再转草稿。${c.draft_sync_status === 'changed' ? '计划已有修改，没有覆盖原草稿；可打开原草稿自行调整。' : '不会上传或发布。'}</span></div></form>`;
  }
  function observationForm() {
    const c = cards().find(x => x.id === P.observationEdit); if (!c) return '';
    const o = latest(c.id) || {};
    const d = draft('observation', c.id, {...o, published_at: datetime(o.published_at), observed_at: datetime(o.observed_at || new Date().toISOString())});
    return `<form class="planning-panel planning-form" data-planning-form="observation" data-record-id="${esc(c.id)}" id="planning-observation-editor"><div class="planning-panel-heading"><span class="planning-step">${String(c.position).padStart(2, '0')}</span><div><h2>记录一次实际观察</h2><p>${esc(c.title || c.question || '这一篇内容')} · 新记录会保留历史观察</p></div>${button('收起', 'close-observation')}</div><div class="planning-callout">数据由你从平台后台手工填写，当前没有平台核实。未知指标请留空，只有实际为 0 时才填写 0。</div>${field('已发布内容的链接', 'post_url', d.post_url, {type: 'url', placeholder: 'https://…（没有可分享链接可以留空）'})}<div class="planning-form-grid">${field('实际发布时间', 'published_at', d.published_at, {type: 'datetime-local', required: true, help: '按本机时区填写，不用计划时间代替。'})}${field('本次采集时间', 'observed_at', d.observed_at, {type: 'datetime-local', required: true, help: '新采集请改为实际时间；补充旧记录时保留原时间。'})}</div><div class="planning-metric-fields">${[['views', '阅读 / 播放'], ['impressions', '曝光'], ['saves', '收藏'], ['comments', '评论'], ['follows', '新增关注'], ['production_minutes', '制作耗时（分钟）']].map(([name, label]) => field(label, name, d[name], {type: 'number', placeholder: '未知留空', step: name === 'production_minutes' ? 'any' : '1'})).join('')}</div>${field('评论里冒出的真实追问', 'reader_question', d.reader_question, {textarea: true, rows: 2, placeholder: '记录一条实际出现的追问；没有就留空。'})}<div class="planning-form-grid">${field('下一篇准备怎么回答？', 'next_answer', d.next_answer, {textarea: true, rows: 2})}${field('回答这次追问需要什么素材？', 'next_materials', d.next_materials, {textarea: true, rows: 2})}</div>${field('这次观察的备注', 'note', d.note, {textarea: true, rows: 2, placeholder: '例如：更换了开头、平台活动带来曝光、数据仍在增长…'})}<div class="planning-actions"><button class="planning-button primary" type="submit">保存这次观察</button><span class="planning-muted">后续可把实际追问转进下一批问题库。</span></div></form>`;
  }
  function reviewView() {
    if (!batch()) return empty('先建立一批内容计划', '复盘与每一篇具体内容绑定。先准备内容，再把真实发布后的观察录入。', button('去建立计划 →', 'tab', 'data-tab="plan"', true));
    const groupCards = cards().filter(c => c.group === P.group).sort((a, b) => a.position - b.position);
    return `${batchToolbar()}<div class="planning-section-heading"><div><h2>每 4 篇，停下来看看。</h2><p>找出读者真正需要的内容，再把追问带进下一轮。</p></div><div class="planning-group-tabs" aria-label="复盘分组">${[1, 2, 3].map(g => `<button type="button" class="${P.group === g ? 'active' : ''}" data-planning-action="select-group" data-group="${g}">第 ${g} 组</button>`).join('')}</div></div><div class="planning-callout">不同内容的观察时长可能不同。收藏率只在同一篇的收藏数和阅读 / 播放数都已填写时显示；不把空值当成 0。</div><div class="planning-review-cards">${groupCards.map(c => {
      const o = latest(c.id), hours = o ? (new Date(o.observed_at) - new Date(o.published_at)) / 3600000 : null;
      const paired = o && o.saves != null && o.views != null && o.views > 0;
      return `<article class="planning-review-card"><div class="planning-row"><span class="planning-card-number">${String(c.position).padStart(2, '0')} <small>${esc(types[c.content_type])}</small></span><span class="planning-tag ${o ? 'green' : 'light'}">${o ? '人工录入' : '未观察'}</span></div><h3>${esc(c.title || c.question || '待补标题')}</h3><div class="planning-observation-meta">${o ? `观察 ${Number.isFinite(hours) ? Math.round(hours * 10) / 10 : '—'} 小时 · ${esc(displayDate(o.observed_at))}` : '发布后再填写实际反馈'}</div><dl class="planning-review-metrics"><div><dt>阅读 / 播放</dt><dd>${num(o?.views)}</dd></div><div><dt>收藏</dt><dd>${num(o?.saves)}</dd></div><div><dt>收藏 / 阅读</dt><dd>${paired ? `${(o.saves / o.views * 100).toFixed(2)}%` : '—'}</dd></div></dl>${o?.reader_question ? `<blockquote><span>读者追问</span>${esc(o.reader_question)}</blockquote>` : '<p class="planning-no-feedback">尚未记录具体追问</p>'}<div class="planning-actions">${button(o ? '追加一次观察' : '记录发布后反馈', 'edit-observation', `data-id="${esc(c.id)}"`)}${o?.reader_question && (!o.next_answer || !o.next_materials) ? '<span class="planning-muted">补齐下一篇的回答方向与素材后，可转入问题库。</span>' : ''}${o?.reader_question ? button(o.promoted_question_id ? '已进入问题库' : '把追问转成下个选题', 'promote-feedback', `data-id="${esc(o.id)}" ${o.promoted_question_id || !o.next_answer || !o.next_materials ? 'disabled' : ''}`) : ''}</div></article>`;
    }).join('')}</div><div class="planning-review-action">${button('查看这 4 篇的复盘', 'review-batch', '', true)}<span>有几篇记录就先看几篇，不会锁住下一步。</span></div>${P.review ? reviewResult() : ''}${P.observationEdit ? observationForm() : ''}`;
  }
  function reviewResult() {
    const r = P.review;
    return `<section class="planning-panel planning-review-result"><div class="planning-panel-heading"><span class="planning-step">↺</span><div><h2>第 ${P.group} 组 · 复盘依据</h2><p>已观察 ${r.observed_count ?? 0} / 4 篇 · ${r.windows_comparable ? '观察时长可比较' : '观察时长仍需对齐'}</p></div></div><p>${esc(r.comparison_rule || '先对齐观察时长，再比较同一种指标。')}</p>${r.missing_positions?.length ? `<div class="planning-callout">第 ${r.missing_positions.map(esc).join('、')} 篇还没有观察数据，结论仍不完整。</div>` : ''}<div class="planning-review-table"><table><thead><tr><th>内容</th><th>观察时长</th><th>阅读 / 播放</th><th>收藏 / 阅读</th><th>制作分钟</th></tr></thead><tbody>${(r.items || []).map(i => `<tr><td>${String(i.card.position).padStart(2, '0')} · ${esc(i.card.title || i.card.question || '待补标题')}</td><td>${i.window_hours == null ? '—' : `${num(i.window_hours)} 小时`}</td><td>${num(i.observation?.views)}</td><td>${i.save_rate_percent == null ? '—' : `${num(i.save_rate_percent)}%`}</td><td>${num(i.observation?.production_minutes)}</td></tr>`).join('')}</tbody></table></div>${r.limitations?.length ? `<ul class="planning-limitations">${r.limitations.map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}<p class="planning-next-review">下一步：从实际追问里选一个问题，准备对应素材。下一篇先只调整一个变量。</p></section>`;
  }
  function safeURL(value) { try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) ? url.href : '#'; } catch { return '#'; } }
  function aiPrompt() {
    const s = P.data?.strategy, b = batch();
    const lines = ['你是我的内容执行助手。请依据下面的真实资料完善内容计划，不编造读者需求、案例、数据或已发布结果。', '', `账号：${account()?.name || account()?.handle || ''}（${account()?.platform || ''} / ${account()?.handle || ''}）`, '', '【账号定位】'];
    if (s) lines.push(`读者：${s.audience}`, `场景：${s.scenario}`, `核心问题：${s.problem}`, `已有素材：${s.materials}`, `固定栏目：${s.pillars.join(' / ')}`); else lines.push('尚未填写。先根据我实际提供的信息补齐，不自行假定。');
    lines.push('', '【真实问题库】');
    if (activeQuestions().length) activeQuestions().forEach((q, i) => lines.push(`${i + 1}. ${q.question}`, `   情境：${q.context || '待补'}；来源：${sources[q.source_type]} ${q.source_url || ''} ${q.source_note || ''}`, `   栏目：${q.pillar || '待补'}；素材：${q.materials || '待补'}；${q.material_ready ? '素材已准备' : '素材尚未备好'}`)); else lines.push('暂无真实问题，不要自行编造。');
    lines.push('', '【本批计划】');
    if (b) { lines.push(b.name || '12 篇计划'); cards().forEach(c => lines.push(`${c.position}. 第${c.group}组 / ${types[c.content_type]} / ${c.pillar || '待补栏目'}`, `   标题：${c.title || '待写'}；问题：${c.question || questions().find(q => q.id === c.question_id)?.question || '待补真实问题'}`, `   素材：${c.material_plan || '待补'}；读者动作：${c.reader_action || '待补'}；预期反馈：${c.expected_feedback || '待补'}；验证变量：${c.variable || '待补'}`, c.body ? `   已有正文：${c.body}` : '   正文：尚未撰写')); } else lines.push('尚未建立；使用 12 篇结构：3 篇方法、4 篇案例、3 篇过程、2 篇模板，分为 3 组，每组 4 篇。');
    const feedback = (P.data?.observations || []).filter(o => o.reader_question);
    if (feedback.length) { lines.push('', '【实际反馈（人工记录）】'); feedback.forEach(o => lines.push(`追问：${o.reader_question}；准备回答：${o.next_answer || '待定'}；所需素材：${o.next_materials || '待补'}；内容链接：${o.post_url || '未提供'}`)); }
    lines.push('', '【请完成】', '1. 保留已有定位和真实出处。问题不足就列出缺项，不填充虚构选题。', '2. 每篇围绕一个具体问题，提供标题、素材安排、正文或脚本、读者可做的动作与预期反馈。没有证据的判断标为待验证。', '3. 保留方法 / 案例 / 过程 / 模板的组合。先完成第一组 4 篇，再根据反馈调整后续内容。', '4. 复盘时保留缺失值，结合观察时长看数据；先指出证据和限制，再建议下一篇只改一个变量。', '5. 输出可以直接检查与使用的中文内容，产品名、工具名、API 名保留英文。不要声称已经上传或发布。');
    return lines.join('\n');
  }
  async function reload({initial = false} = {}) {
    const generation = ++P.generation;
    if (initial) { P.loading = true; P.error = ''; draw(); }
    try {
      if (initial) {
        const state = await api('/api/state'); if (generation !== P.generation || !P.active) return;
        P.accounts = (state.accounts || []).filter(a => a.platform !== 'google_ads');
        if (!P.accounts.some(a => a.id === P.accountId)) P.accountId = P.accounts[0]?.id || '';
      }
      if (!P.accountId) { P.data = null; P.loading = false; draw(); return; }
      const id = P.accountId;
      const result = await Promise.allSettled([api(`/api/planning?account_id=${encodeURIComponent(id)}`), api('/api/media')]);
      if (generation !== P.generation || !P.active || id !== P.accountId) return;
      if (result[0].status === 'rejected') throw result[0].reason;
      P.data = result[0].value;
      P.media = result[1].status === 'fulfilled' ? result[1].value.jobs || [] : [];
      if (!batches().some(b => b.id === P.batchId)) P.batchId = batches()[0]?.id || '';
      P.error = '';
    } catch (error) { if (generation === P.generation) P.error = error.message; }
    finally { if (generation === P.generation) { P.loading = false; draw(); } }
  }
  async function mutate(action, args, success) {
    const id = P.accountId;
    const result = await api('/api/planning/action', {action, arguments: {account_id: id, ...args}});
    if (success) toast(success);
    if (P.active && P.accountId === id) await reload();
    return result;
  }
  function scrollTo(id) { document.getElementById(id)?.scrollIntoView({behavior: 'smooth', block: 'start'}); }
  async function onClick(event) {
    const target = event.target.closest('[data-planning-action], [data-planning-tab]'); if (!target || !root()?.contains(target)) return;
    if (target.dataset.planningTab) { P.tab = target.dataset.planningTab; draw(); return; }
    const action = target.dataset.planningAction, actionAccount = P.accountId;
    if (action === 'tab') { P.tab = target.dataset.tab; draw(); return; }
    if (action === 'new-question') { P.questionEdit = ''; draw(); scrollTo('planning-question-editor'); return; }
    if (action === 'edit-question') { P.questionEdit = target.dataset.id; draw(); scrollTo('planning-question-editor'); return; }
    if (action === 'edit-item') { P.itemEdit = target.dataset.id; draw(); scrollTo('planning-item-editor'); return; }
    if (action === 'close-item') { P.itemEdit = ''; draw(); return; }
    if (action === 'edit-observation') { P.observationEdit = target.dataset.id; draw(); scrollTo('planning-observation-editor'); return; }
    if (action === 'close-observation') { P.observationEdit = ''; draw(); return; }
    if (action === 'select-group' || action === 'review-group') { P.group = Number(target.dataset.group); P.review = null; P.observationEdit = ''; if (action === 'review-group') P.tab = 'review'; draw(); return; }
    if (action === 'copy-prompt') {
      const textarea = root().querySelector('[data-planning-prompt]');
      try { await navigator.clipboard.writeText(textarea.value); toast('已复制当前账号的 AI 任务。'); }
      catch { textarea.focus(); textarea.select(); toast('任务已选中，请按 ⌘C 复制。'); }
      return;
    }
    target.disabled = true;
    try {
      if (action === 'reload') await reload({initial: true});
      else if (action === 'create-batch') { const r = await mutate('create_batch', {}, '已建立 12 篇框架。缺少真实问题的位置已留空。'); if (P.accountId !== actionAccount || !P.active) return; P.batchId = r.batch.id; P.itemEdit = ''; P.observationEdit = ''; P.review = null; P.tab = 'plan'; draw(); }
      else if (action === 'create-draft') {
        const form = document.getElementById('planning-item-editor');
        if (form?.dataset.recordId === target.dataset.id && P.drafts.has(formKey('item', target.dataset.id))) { toast('这一篇还有未保存编辑，先点“保存这一篇”。', true); return; }
        const r = await mutate('create_plan_draft', {id: target.dataset.id});
        toast(r.reused ? (r.draft_sync_status === 'changed' ? '已打开原草稿。计划中的修改没有自动覆盖它。' : '已打开原有本地草稿。') : '已保存为本地草稿，没有上传或发布。');
        if (!r.reused) { try { if (window.parent !== window && typeof window.parent.sptToolChanged === 'function') window.parent.sptToolChanged(); } catch { /* not inside the SPT window */ } }
        if (P.accountId !== actionAccount || !P.active) return;
        window.dispatchEvent(new CustomEvent('planning-draft-created', {detail: {draft: r.draft}})); location.hash = '#planner';
      } else if (action === 'promote-feedback') { await mutate('promote_feedback', {observation_id: target.dataset.id}, '真实追问已进入这个账号的问题库，保留原内容出处。'); P.review = null; draw(); }
      else if (action === 'review-batch') { const actionBatch = batch().id, actionGroup = P.group; const r = await api('/api/planning/action', {action: 'review_batch', arguments: {account_id: actionAccount, batch_id: actionBatch, group: actionGroup}}); if (!P.active || P.accountId !== actionAccount || batch()?.id !== actionBatch || P.group !== actionGroup) return; P.review = r; draw(); root()?.querySelector('.planning-review-result')?.scrollIntoView({behavior: 'smooth', block: 'start'}); }
    } catch (error) { toast(error.message, true); }
    finally { if (target.isConnected) target.disabled = false; }
  }
  async function onSubmit(event) {
    const form = event.target.closest('[data-planning-form]'); if (!form || !root()?.contains(form)) return;
    event.preventDefault(); const name = form.dataset.planningForm, id = form.dataset.recordId || '', values = formValues(form), key = formKey(name, id), accountId = P.accountId;
    const submit = form.querySelector('[type="submit"]'); submit.disabled = true;
    try {
      let action, args;
      if (name === 'strategy') { action = 'save_strategy'; args = {audience: values.audience, scenario: values.scenario, problem: values.problem, materials: values.materials, pillars: [values.pillar1, values.pillar2, values.pillar3]}; }
      else if (name === 'question') { action = id ? 'update_question' : 'add_question'; args = {id: id || undefined, question: values.question, context: values.context, source_type: values.source_type, source_url: values.source_url, source_note: values.source_note, pillar: values.pillar, materials: values.materials, material_ready: values.material_ready, priority: Number(values.priority), status: values.status}; }
      else if (name === 'item') { action = 'update_plan_item'; args = {id, question_id: values.question_id || null, title: values.title, content_type: values.content_type, pillar: values.pillar, material_plan: values.material_plan, material_ready: values.material_ready, reader_action: values.reader_action, expected_feedback: values.expected_feedback, variable: values.variable, body: values.body, media_ids: values.media_ids}; }
      else if (name === 'observation') { action = 'observe_plan_item'; args = {id, post_url: values.post_url, published_at: new Date(values.published_at).toISOString(), observed_at: new Date(values.observed_at).toISOString(), reader_question: values.reader_question, next_answer: values.next_answer, next_materials: values.next_materials, note: values.note}; for (const metric of ['views', 'impressions', 'saves', 'comments', 'follows', 'production_minutes']) args[metric] = values[metric] === '' ? null : Number(values[metric]); }
      if (!action) return;
      await api('/api/planning/action', {action, arguments: {account_id: accountId, ...args}});
      P.drafts.delete(key);
      toast(name === 'strategy' ? '已保存这个账号的定位。' : name === 'question' ? '真实问题已保存。' : name === 'item' ? '这一篇已保存。' : '观察已保存；未填写的指标继续保留为空。');
      if (P.accountId === accountId) {
        if (name === 'question') P.questionEdit = '';
        if (name === 'observation') { P.observationEdit = ''; P.review = null; }
        await reload();
      }
    } catch (error) { toast(error.message, true); }
    finally { if (submit.isConnected) submit.disabled = false; }
  }
  function onInput(event) { remember(event.target.closest('[data-planning-form]')); }
  async function onChange(event) {
    if (event.target.matches('[data-planning-account]')) {
      P.accountId = event.target.value; P.data = null; P.batchId = ''; P.questionEdit = ''; P.itemEdit = ''; P.observationEdit = ''; P.review = null; P.loading = true; draw(); await reload();
    } else if (event.target.matches('[data-planning-batch]')) { P.batchId = event.target.value; P.itemEdit = ''; P.observationEdit = ''; P.review = null; draw(); }
    else {
      const form = event.target.closest('[data-planning-form]');
      if (form?.dataset.planningForm === 'item' && event.target.name === 'question_id') { const ready = form.querySelector('[name="material_ready"]'); if (ready) ready.checked = false; }
      remember(form);
    }
  }
  function mount() {
    P.active = true; const el = root(); if (!el) return;
    el.addEventListener('click', onClick); el.addEventListener('submit', onSubmit); el.addEventListener('input', onInput); el.addEventListener('change', onChange);
    reload({initial: true});
  }
  function unmount() {
    const el = root(); if (el) { el.removeEventListener('click', onClick); el.removeEventListener('submit', onSubmit); el.removeEventListener('input', onInput); el.removeEventListener('change', onChange); }
    P.active = false; P.generation++;
  }
  window.MediaPlanning = {render, mount, unmount};
})();
