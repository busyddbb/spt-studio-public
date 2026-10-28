/* 发布队列 UI。仅管理同源本地队列；真实发布由 native worker/API 明确授权后执行。 */
(function () {
  'use strict';
  const state = { workId: '', preview: null, jobs: [], accounts: [], maxUploads: 2, loading: false, queueLoading: false, queueLoaded: false, error: '', submitting: false, selected: new Set(), scheduledMode: 'now', scheduledAt: '', submitEnabled: true, refreshTimer: 0, native: false };
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[ch]));
  const text = (value, fallback = '') => String(value ?? fallback);
  const queryWork = () => new URLSearchParams(location.hash.split('?')[1] || '').get('work_id') || '';
  const isQueueRoute = () => { const [path, query = ''] = String(location.hash || '').split('?'); const params = new URLSearchParams(query); return path === '#publish' && (params.get('view') === 'queue' || params.has('work_id')); };
  const api = async (path, options = {}) => { const response = await fetch(path, { cache: 'no-store', ...options }); let data = {}; try { data = await response.json(); } catch {} if (!response.ok) throw new Error(data.error || `请求失败（${response.status}）`); return data; };
  const isVideo = (item) => /\.(mp4|mov|m4v|webm|avi)$/i.test(text(item?.path || item?.name || item));
  const accountId = (account) => text(account?.id || account?.account_id || account?.legacy_account_id || account?.handle);
  const accountName = (account) => text(account?.name || account?.label || account?.handle || account?.account_id || '未命名账号');
  const platform = (account) => ({ xiaohongshu:'RedNote', rednote:'RedNote', instagram:'Instagram', tiktok:'TikTok' }[text(account?.platform).toLowerCase()] || text(account?.platform_label || account?.platform || '平台'));
  const supported = (account) => account?.supported !== false && ['xiaohongshu', 'rednote', '小红书'].includes(text(account?.platform).toLowerCase());
  const nativeRun = (payload) => {
    try {
      const handler = window.webkit?.messageHandlers?.runPublishingQueue;
      if (handler?.postMessage) { handler.postMessage(payload); return true; }
    } catch {}
    return false;
  };
  const nativePreview = (payload) => {
    try {
      const handler = window.webkit?.messageHandlers?.previewPublishingQueue;
      if (handler?.postMessage) { handler.postMessage(payload); return true; }
    } catch {}
    return false;
  };
  const localDateTimeValue = (date) => {
    const d = new Date(date);
    if (Number.isNaN(d.getTime())) return '';
    const pad = (value) => String(value).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  };
  const media = () => {
    const work = state.preview?.work || state.preview;
    return (state.preview?.media || work?.finals || work?.media || []).map((item) => typeof item === 'string' ? { name: item, path: item } : item);
  };
  const mediaPath = (item) => {
    const root = text(state.preview?.root);
    const raw = text(item?.path || item?.name);
    if (!raw) return '';
    if (root && raw.startsWith(`${root}/`)) return raw.slice(root.length + 1);
    return raw.startsWith('/') ? '' : raw;
  };
  const mediaURL = (item) => {
    const path = mediaPath(item);
    const base = (document.body?.dataset?.apiBase || '/api/spt').replace(/\/$/, '');
    return path && state.workId ? `${base}/works/${encodeURIComponent(state.workId)}/file?path=${encodeURIComponent(path)}` : '';
  };
  function previewHTML() {
    if (!state.workId) return '<div class="publish-empty">从作品详情点“发布”，或在地址中带入 work_id。</div>';
    if (state.loading) return '<div class="publish-empty"><span class="spinner" aria-hidden="true"></span>正在读取作品预览…</div>';
    if (state.error) return `<div class="publish-empty publish-error">${esc(state.error)}<button class="button small" data-pq-action="reload">重试</button></div>`;
    const work = state.preview?.work || state.preview || {};
    const files = media();
    const video = files.find(isVideo), images = files.filter((item) => !isVideo(item));
    const issues = state.preview?.issues || work.issues || [];
    const topics = state.preview?.topics || work.topics || [];
    const mediaList = files.map((item, index) => { const name = text(item.name || item.path || item, `媒体 ${index + 1}`); const url = mediaURL(item); const image = !isVideo(item) && url; return `<li><span>${index + 1}. ${index === 0 && !video ? '封面 · ' : ''}${esc(name)}</span>${image ? `<img src="${esc(url)}" alt="第${index + 1}张${index === 0 ? '（封面）' : ''}" loading="lazy">` : ''}</li>`; }).join('');
    const topicList = topics.length ? topics.map((topic) => `<span class="chip">#${esc(topic)}</span>`).join('') : '<span class="publish-hint">未设置话题</span>';
    return `<div class="publish-preview"><div class="publish-preview-copy"><span class="eyebrow">作品预览</span><h2>${esc(work.title || '未命名作品')}</h2><p>${esc(work.client || work.category || '')}${work.date ? ` · ${esc(work.date)}` : ''}</p><div class="publish-media-summary"><span>${video ? '视频' : '图文'}</span><span>${video ? esc(video.name || video.path) : `${images.length} 个媒体文件`}</span>${work.cover ? `<span>含封面（不计入媒体数量）</span>` : ''}</div><details open><summary>媒体顺序（${files.length} 个，不含根目录封面）</summary><ol class="publish-media-list">${mediaList || '<li>没有可发布媒体</li>'}</ol></details><div><strong>实际话题</strong><div class="publish-topic-list">${topicList}</div></div>${issues.length ? `<div class="issue-message">${issues.map((issue) => `<p>${esc(typeof issue === 'string' ? issue : issue.message || issue.code || '缺少必要资料')}</p>`).join('')}</div>` : ''}</div><div class="publish-caption"><strong>标题</strong><span>${esc(state.preview?.title || work.title || '未读取')}</span><strong>正文</strong><pre>${esc(state.preview?.body || state.preview?.caption || work.caption || '未读取')}</pre></div></div>`;
  }
  function accountsHTML() {
    if (!state.accounts.length) return '<div class="publish-empty">没有可用账号。请先在账号档案中关联账号。</div>';
    return `<div class="publish-account-list">${state.accounts.map((account) => { const id = accountId(account); const checked = state.selected.has(id); const defaults = account.defaults || {}; const ok = supported(account); return `<label class="publish-account-option${ok ? '' : ' is-disabled'}"><input type="checkbox" data-pq-account="${esc(id)}" aria-label="选择账号 ${esc(accountName(account))}" ${checked ? 'checked' : ''} ${ok ? '' : 'disabled'}><span class="publish-account-option-copy"><strong>${esc(accountName(account))}</strong><small>${esc(platform(account))}${ok ? '' : ' · 暂未接入自动发布'}</small><select class="publish-default-select" data-pq-default="${esc(id)}" aria-label="${esc(accountName(account))}默认可见范围"><option value="public" ${defaults.visibility === 'public' ? 'selected' : ''}>公开</option><option value="private" ${defaults.visibility === 'private' ? 'selected' : ''}>仅自己可见</option></select><small><input type="checkbox" data-pq-copy-default="${esc(id)}" aria-label="允许 ${esc(accountName(account))} 的正文复制" ${defaults.allow_body_copy === true ? 'checked' : ''}>允许正文复制</small></span></label>`; }).join('')}</div>`;
  }
  const jobStatus = (job) => text(job.status || job.state || 'queued');
  const jobLabel = (job) => ({ queued:'排队中', uploading:'上传中', processing:'平台处理中', preflight:'发布前核对', submit_intent:'已授权提交', submitted:'已提交，待回查', checking_result:'正在回查', published:'已发布', review:'审核中', under_review:'审核中', checking_login:'正在检查登录', needs_login:'需要登录', needs_attention:'需要人工处理', unknown:'状态待确认', failed:'失败', cancelled:'已停止' }[jobStatus(job)] || '状态待确认');
  function jobsHTML() {
    if (!state.jobs.length) return '<div class="publish-empty">还没有队列任务。</div>';
    return `<div class="publish-job-list">${state.jobs.map((job) => { const status = jobStatus(job); const canCancel = ['queued','pending','ready'].includes(status); const id = text(job.id || job.job_id); const note = job.note_id ? `noteID：${job.note_id}` : ''; const url = job.url || ''; const message = job.message || job.error || ''; return `<article class="publish-job"><div><strong>${esc(job.work_title || job.title || state.preview?.title || '作品')}</strong><span>${esc(job.account_name || job.account_id || '账号')} · ${esc(job.platform || '平台')}</span></div><div class="publish-job-status" data-status="${esc(status)}">${esc(jobLabel(job))}${job.progress != null ? ` · ${esc(job.progress)}%` : ''}</div>${canCancel ? `<button class="button small" data-pq-cancel="${esc(id)}">停止</button>` : ''}${status === 'needs_attention' || status === 'unknown' || status === 'needs_login' ? `<button class="button small" data-pq-preview="${esc(id)}">查看后台页面</button>` : ''}${['published','under_review','failed','cancelled','needs_attention','unknown','needs_login'].includes(status) ? `<button class="button small" data-pq-hide="${esc(id)}">清除</button>` : ''}${note || url ? `<p class="publish-job-result">${esc(note)}${url ? ` <a href="${esc(url)}" target="_blank" rel="noopener noreferrer">打开链接</a>` : ''}</p>` : ''}${message ? `<p class="publish-job-error">${esc(message)}</p>` : ''}</article>`; }).join('')}</div>`;
  }
  function render(host) {
    const nextWork = queryWork();
    if (nextWork !== state.workId) { state.workId = nextWork; state.preview = null; state.previewWorkId = ''; state.error = ''; state.loading = false; state.selected.clear(); state.scheduledMode = 'now'; state.scheduledAt = ''; }
    state.native = !!window.webkit?.messageHandlers?.runPublishingQueue?.postMessage;
    const blocked = !state.workId || !state.selected.size || (state.preview?.issues || []).length;
    host.innerHTML = `<section class="publish-queue-page"><header class="page-heading"><div><h1 tabindex="-1">发布队列</h1><p class="page-sub">多账号独立排队；同一账号逐条执行，最多同时上传 ${state.maxUploads} 个任务。</p></div><div class="page-controls"><a class="button small" href="#publish">官方后台入口</a><a class="button small" href="#tools?name=accounts">账号档案</a><button class="button small" data-pq-action="refresh">刷新队列</button></div></header><div class="publish-queue-grid"><section class="panel publish-compose"><div class="panel-head"><h2>准备发布</h2><span class="chip" data-tone="${state.native ? 'ok' : 'warn'}">${state.native ? '后台执行可用' : '仅本地队列'}</span></div>${previewHTML()}<div class="publish-form"><div class="publish-form-section"><h3>选择账号</h3>${accountsHTML()}<p class="publish-hint">每个账号独立保存默认规则；作品没有话题时也可正常排队，已有话题则沿用作品内容。</p></div><div class="publish-form-section publish-options"><h3>发布方式</h3><label><input type="radio" name="pq-schedule" value="now" ${state.scheduledMode === 'now' ? 'checked' : ''}>立即排队</label><label><input type="radio" name="pq-schedule" value="later" ${state.scheduledMode === 'later' ? 'checked' : ''}>定时发布</label><input type="datetime-local" id="pq-scheduled-at" value="${esc(state.scheduledAt)}" ${state.scheduledMode === 'later' ? '' : 'disabled'}><label class="publish-check"><input type="checkbox" id="pq-submit-enabled" ${state.submitEnabled ? 'checked' : ''}>授权后台自动提交（每个账号只提交一次）</label><p class="publish-hint">未勾选时只准备/上传草稿，不会点击平台发布。</p></div><div class="publish-actions"><button class="button primary" data-pq-action="enqueue" ${state.submitting || blocked ? 'disabled' : ''}>${state.submitting ? '正在加入队列…' : '加入后台发布队列'}</button><span class="publish-hint">提交后只回查结果，不会重复点击。</span></div></div></section><section class="panel publish-jobs"><div class="panel-head"><h2>队列进度</h2><span class="source-caption">${state.jobs.length} 个任务</span></div>${jobsHTML()}</section></div></section>`;
    bind(host);
    if (isQueueRoute() && state.workId && (!state.preview || state.previewWorkId !== state.workId) && !state.loading) loadPreview(host);
    if (isQueueRoute() && !state.queueLoaded && !state.queueLoading) loadQueue(host);
    else if (isQueueRoute()) scheduleRefresh();
  }
  function bind(host) {
    host.querySelectorAll('[data-pq-account]').forEach((input) => input.addEventListener('change', () => { input.checked ? state.selected.add(input.dataset.pqAccount) : state.selected.delete(input.dataset.pqAccount); render(host); }));
    host.querySelectorAll('[data-pq-default]').forEach((input) => input.addEventListener('change', () => saveDefaults(input.dataset.pqDefault, { visibility: input.value }, host)));
    host.querySelectorAll('[data-pq-copy-default]').forEach((input) => input.addEventListener('change', () => saveDefaults(input.dataset.pqCopyDefault, { allow_body_copy: input.checked }, host)));
    host.querySelectorAll('input[name="pq-schedule"]').forEach((input) => input.addEventListener('change', () => { state.scheduledMode = input.value; if (input.value === 'later' && !state.scheduledAt) state.scheduledAt = localDateTimeValue(Date.now() + 3600000); render(host); }));
    host.querySelector('#pq-scheduled-at')?.addEventListener('change', (event) => { state.scheduledAt = event.target.value; });
    host.querySelector('#pq-submit-enabled')?.addEventListener('change', (event) => { state.submitEnabled = event.target.checked; });
    host.querySelector('[data-pq-action="reload"]')?.addEventListener('click', () => { state.error = ''; state.preview = null; render(host); });
    host.querySelector('[data-pq-action="refresh"]')?.addEventListener('click', () => { state.jobs = []; loadQueue(host); });
    host.querySelector('[data-pq-action="enqueue"]')?.addEventListener('click', () => enqueue(host));
    host.querySelectorAll('[data-pq-cancel]').forEach((button) => button.addEventListener('click', () => cancel(button.dataset.pqCancel, host)));
    host.querySelectorAll('[data-pq-hide]').forEach((button) => button.addEventListener('click', () => hide(button.dataset.pqHide, host)));
    host.querySelectorAll('[data-pq-preview]').forEach((button) => button.addEventListener('click', () => nativePreview({ queue_id: button.dataset.pqPreview })));
  }
  async function loadPreview(host) { const target = host || document.querySelector('#view'); state.loading = true; render(target); const id = state.workId; try { const data = await api(`/api/publishing/work?work_id=${encodeURIComponent(id)}`); if (state.workId === id) { state.preview = data; state.previewWorkId = id; state.error = ''; } } catch (error) { if (state.workId === id) state.error = `作品预览读取失败：${error.message}`; } finally { if (state.workId === id) { state.loading = false; if (isQueueRoute()) render(target); } } }
  async function loadQueue(host) { if (state.queueLoading) return; state.queueLoading = true; try { const data = await api('/api/publishing/queue'); state.jobs = Array.isArray(data.jobs) ? data.jobs : []; state.accounts = Array.isArray(data.accounts) ? data.accounts : []; state.maxUploads = Number(data.max_uploads) || 2; state.queueLoaded = true; if (host && isQueueRoute()) render(host); } catch (error) { state.error = state.error || `队列服务暂不可用：${error.message}`; state.queueLoaded = true; if (host && isQueueRoute()) render(host); } finally { state.queueLoading = false; } }
  function scheduleRefresh() { clearTimeout(state.refreshTimer); if (isQueueRoute() && state.jobs.some((job) => !['published','review','failed','cancelled','under_review'].includes(jobStatus(job)))) state.refreshTimer = setTimeout(() => { if (isQueueRoute()) loadQueue(document.querySelector('#view')); }, 3000); }
  async function enqueue(host) { if (!state.workId || !state.selected.size || (state.preview?.issues || []).length) return; state.submitting = true; render(host); try { const data = await api('/api/publishing/action', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ action:'enqueue_work', arguments:{ work_id:state.workId, account_ids:[...state.selected], submit_enabled:state.submitEnabled, ...(state.scheduledMode === 'later' && state.scheduledAt ? { scheduled_at: new Date(state.scheduledAt).toISOString() } : {}) } }) }); state.jobs = Array.isArray(data.jobs) ? data.jobs : state.jobs; const payload = { queue_id:data.queue_id, jobs:state.jobs }; nativeRun(payload); } catch (error) { state.error = `加入队列失败：${error.message}`; } finally { state.submitting = false; render(host); } }
  async function hide(id, host) { try { await api('/api/publishing/action', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ action:'queue_hide', arguments:{ id } }) }); state.jobs = state.jobs.filter((job) => text(job.id || job.job_id) !== id); render(host); } catch (error) { state.error = `清除失败：${error.message}`; render(host); } }
  async function cancel(id, host) { try { await api('/api/publishing/action', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ action:'queue_cancel', arguments:{ id } }) }); state.jobs = state.jobs.map((job) => text(job.id || job.job_id) === id ? { ...job, status:'cancelled' } : job); render(host); } catch (error) { state.error = `停止任务失败：${error.message}`; render(host); } }
  async function saveDefaults(id, defaults, host) { try { await api('/api/publishing/action', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ action:'account_defaults', arguments:{ account_id:id, defaults } }) }); state.accounts = state.accounts.map((account) => accountId(account) === id ? { ...account, defaults:{ ...(account.defaults || {}), ...defaults } } : account); render(host); } catch (error) { state.error = `账号默认规则保存失败：${error.message}`; render(host); } }
  window.SPTPublishQueue = { render, openWork: (id) => { location.hash = `#publish?work_id=${encodeURIComponent(id)}`; } };
})();
