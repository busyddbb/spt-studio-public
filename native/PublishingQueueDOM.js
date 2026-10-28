// Public DOM only. This exact resource is executed by WebKit and offline tests.
// Every invocation performs at most one UI action and returns for the next tick.
(function (args) {
  'use strict';
  const {options: o = {}, title, body, mediaNames, phase} = args;
  const all = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  // Some controls live inside shadow roots; deepAll looks there too.
  const shadowRoots = (root = document) => Array.from(root.querySelectorAll('*')).filter(n => n.shadowRoot).flatMap(n => [n.shadowRoot, ...shadowRoots(n.shadowRoot)]);
  const deepAll = selector => [document, ...shadowRoots()].flatMap(r => Array.from(r.querySelectorAll(selector)));
  // The platform's submit bar is a custom element with a closed shadow root it keeps as `_sr`;
  // its 发布 / 暂存离开 buttons live inside, and its attributes say whether submit is ready.
  const publishHost = () => all('xhs-publish-btn').filter(visible)[0] || null;
  const publishState = () => {
    const host = publishHost();
    if (!host) return {host: null};
    const label = host.getAttribute('submit-text') || '发布';
    const busy = host.getAttribute('submit-loading') === 'true' || host.getAttribute('submit-disabled') === 'true';
    const root = host._sr || host.shadowRoot;
    const inner = root ? Array.from(root.querySelectorAll('button,[role="button"],div,span')).filter(n => visible(n) && text(n).replace(/\s+/g, '') === label) : [];
    const buttons = inner.filter(n => !inner.some(other => other !== n && n.contains(other)));
    return {host, busy, button: buttons.length === 1 ? buttons[0] : null, count: buttons.length, hasRoot: !!root};
  };
  const visible = n => !!n && n.getClientRects().length > 0 && getComputedStyle(n).visibility !== 'hidden';
  const text = n => String(n?.innerText ?? n?.textContent ?? '').replace(/\u00a0/g, ' ').trim();
  const exact = (a, b) => String(a).replace(/\r\n/g, '\n') === String(b).replace(/\r\n/g, '\n');
  const fail = reason => ({status: 'attention', reason});
  const wait = reason => ({status: 'wait', reason});
  const enabled = n => visible(n) && !n.disabled && n.getAttribute('aria-disabled') !== 'true';
  const button = label => all('button,[role="button"],a,[role="tab"],[class*="tab-item"],[class*="tabItem"]').filter(n => enabled(n) && text(n).replace(/[（(]\d+[)）]$/, '').replace(/\s+\d+$/, '').trim() === label);
  const key = JSON.stringify([title, o.expected_profile_id, mediaNames]);
  if (!window.__sptPublishingStep || window.__sptPublishingStep.key !== key) window.__sptPublishingStep = {key};
  const state = window.__sptPublishingStep;
  if (/\/login(?:\/|$)/.test(location.pathname) || all('input[placeholder="手机号"],input[placeholder="验证码"]').some(visible)) return {status: 'login'};
  const topics = Array.isArray(o.topics) ? o.topics : [];
  const topicName = value => String(value || '').trim().replace(/^#/, '').replace(/\[话题\]#?$/, '').replace(/#$/, '').trim();
  const editor = () => all('.ProseMirror[contenteditable="true"]').filter(visible);
  const topicNodes = ed => {
    const found = all('[data-type="topic"],[data-type="mention"],[data-topic],[data-topic-id],[contenteditable="false"],a,span[class],[class*="topic"],[class*="hash"],[class*="tag"]', ed).filter(n => {
      return n.hasAttribute('data-topic') || n.hasAttribute('data-topic-id') || /topic|mention|hashtag/i.test(n.getAttribute('data-type') || n.className || '') || /^#.+\[话题\]#$/.test(text(n));
    });
    return found.filter(n => !found.some(other => other !== n && other.contains(n)));
  };
  // A topic node's name: a label-like attribute when it holds a plain name, otherwise its text.
  const plainName = v => v && !/^[\[{]/.test(v) && !/^[a-f\d]{24}$/i.test(v) && !/^\d+$/.test(v) ? v : '';
  const nodeName = n => plainName(n.getAttribute('data-label')) || plainName(n.getAttribute('data-name')) || plainName(n.getAttribute('data-topic-name')) || plainName(n.getAttribute('data-topic')) || text(n);
  const readTopics = ed => topicNodes(ed).map(n => topicName(nodeName(n)));
  const describeNode = n => n.tagName.toLowerCase() + (typeof n.className === 'string' && n.className ? '.' + n.className.trim().split(/\s+/).slice(0, 2).join('.') : '') + Array.from(n.attributes).filter(a => /^data-/.test(a.name)).map(a => '[' + a.name + '=' + String(a.value).slice(0, 30) + ']').join('') + '="' + text(n).slice(0, 30) + '"';
  function identity() {
    if (!/^[a-f0-9]{24}$/i.test(o.expected_profile_id || '')) return fail('账号档案缺少可核对的平台 profile ID');
    const roots = all('header,[role="banner"],[data-testid="account"],[class*="account-info"],[class*="user-info"],[class*="userInfo"],[class*="accountInfo"],[class*="header"],[class*="Header"],[class*="sidebar"],[class*="Sidebar"],[class*="user"],[class*="account"]');
    // The account name sits in the page chrome: a header/sidebar block, or any short text along the top.
    const top = all('body *').filter(n => n.children.length === 0 && visible(n) && n.getBoundingClientRect().top < 90);
    const leaves = [...roots.flatMap(root => [root, ...all('*', root)]).filter(n => visible(n) && n.children.length === 0), ...top];
    const named = leaves.some(n => text(n).replace(/\s+/g, ' ') === String(o.expected_name || '').replace(/\s+/g, ' ').trim());
    if (!named) {
      // The chrome renders after navigation; give it time before calling it absent.
      state.nameTicks = (state.nameTicks || 0) + 1;
      if (state.nameTicks <= 30) return wait('等待官方账号栏');
    }
    const links = roots.flatMap(root => all('a[href],[data-profile-id]', root));
    // A note author link elsewhere on the page is not an account identity.
    const identified = links.some(n => {
      if (n.getAttribute('data-profile-id') === o.expected_profile_id) return true;
      try { return new URL(n.getAttribute('href'), location.href).pathname.split('/').includes(o.expected_profile_id); } catch (_) { return false; }
    });
    if (!named) return fail('官方账号栏名称无法确认');
    if (!identified && o.identity_proof?.profile_id !== o.expected_profile_id) {
      const anotherID = links.some(n => /(?:user\/)?profile\/[a-f0-9]{24}/i.test(n.getAttribute('href') || '') || /^[a-f0-9]{24}$/i.test(n.getAttribute('data-profile-id') || ''));
      return anotherID ? fail('官方账号栏 profile ID 与目标不符') : {status: 'identity_required'};
    }
    return null;
  }
  const SWITCH = 'input[type="checkbox"],[role="checkbox"],[role="switch"],[class*="switch"],[class*="checkbox"],[class*="toggle"]';
  function control(pattern) {
    const labels = all('label,[role="checkbox"],[role="switch"],input[type="checkbox"]').filter(n => visible(n) && pattern.test(text(n) || n.getAttribute('aria-label') || ''));
    const controls = labels.map(n => {
      if (n.matches('input,[role="checkbox"],[role="switch"]')) return n;
      if (n.control) return n.control;
      return n.querySelector('input[type="checkbox"],[role="checkbox"],[role="switch"]');
    }).filter(Boolean);
    let unique = [...new Set(controls)];
    if (!unique.length) {
      // A plain text label beside a switch: climb a little from the text and take the one switch there.
      const leaves = all('body *').filter(n => n.children.length === 0 && visible(n) && pattern.test(text(n)));
      const near = leaves.flatMap(leaf => {
        for (let box = leaf.parentElement, i = 0; box && i < 3; box = box.parentElement, i++) {
          const found = all(SWITCH, box).filter(visible).filter(n => !all(SWITCH, n).length);
          if (found.length) return found.length === 1 ? found : [];
        }
        return [];
      });
      unique = [...new Set(near)];
    }
    return unique.length === 1 ? unique[0] : null;
  }
  function checked(n) {
    if (!n) return null;
    if (n.matches('input')) return !!n.checked;
    const value = n.getAttribute('aria-checked');
    if (value === 'true' || value === 'false') return value === 'true';
    const inner = n.querySelector('input[type="checkbox"]');
    if (inner) return !!inner.checked;
    const cls = typeof n.className === 'string' ? n.className : '';
    if (/(^|[\s_-])(is-)?(checked|active|open|on)(?=$|[\s_-])/.test(cls)) return true;
    if (/(^|[\s_-])(un-?checked|off|inactive)(?=$|[\s_-])/.test(cls) || /switch|toggle|checkbox/.test(cls)) return false;
    return null;
  }
  const mentionsOf = hint => all('body *').filter(x => x.children.length === 0 && visible(x) && hint.test(text(x)));
  const shortChain = x => text(x).slice(0, 20) + '<' + [x.parentElement, x.parentElement?.parentElement].filter(Boolean).map(y => y.tagName.toLowerCase() + (typeof y.className === 'string' && y.className ? '.' + y.className.trim().split(/\s+/)[0] : '')).join('<');
  function settings(mutate) {
    for (const [pattern, desired, label, hint] of [[/^(允许正文复制|允许复制正文|允许他人复制正文|正文复制|允许复制)$/, !!o.allow_body_copy, '正文复制', /复制/], [/^(定时发布|预约发布)$/, false, '定时发布', /定时|预约/]]) {
      const n = control(pattern), current = checked(n);
      if (current === null) {
        const mentions = mentionsOf(hint);
        // A toggle the platform no longer offers cannot be on; only an existing one must be read.
        if (!mentions.length && !desired) continue;
        return fail('无法读取' + label + '开关（页面相关文字：' + (mentions.slice(0, 5).map(shortChain).join('；') || '无') + '）');
      }
      if (current !== desired) { if (!mutate) return fail(label + '设置不符'); n.click(); return wait('设置' + label); }
    }
    const visibility = o.visibility === 'private' ? '仅自己可见' : '公开可见';
    const found = all('button,[role="combobox"],[class*="permission"],[class*="visibility"]').filter(n => visible(n) && text(n) === visibility);
    if (!found.length) {
      const choices = all('[role="option"],label,button').filter(n => enabled(n) && text(n) === visibility);
      if (mutate && choices.length === 1) { choices[0].click(); return wait('设置可见范围'); }
      const current = all('[role="combobox"],[class*="permission"],[class*="visibility"]').filter(n => enabled(n) && /^(公开可见|仅自己可见)$/.test(text(n)));
      if (mutate && current.length === 1) { current[0].click(); return wait('展开可见范围'); }
      return fail('无法确认可见范围（页面相关文字：' + (mentionsOf(/可见|公开|仅自己|私密|谁可以看/).slice(0, 6).map(shortChain).join('；') || '无') + '）');
    }
    return null;
  }
  function contentProof(resultMode) {
    const es = editor(), ts = all('input[placeholder="填写标题会有更多赞哦"],textarea[placeholder="填写标题会有更多赞哦"]').filter(visible);
    if (es.length !== 1 || ts.length !== 1) return wait('等待官方编辑器');
    if (!exact(ts[0].value, title)) return fail('标题回读不一致');
    const ed = es[0], actualTopics = readTopics(ed);
    if (topics.length !== actualTopics.length || topics.some((t, i) => t !== actualTopics[i])) return fail('结构化话题回读不一致');
    const clone = ed.cloneNode(true);
    // Topic nodes are a separate platform field. Do not accept plaintext #tags.
    topicNodes(clone).forEach(n => n.remove());
    const read = n => n.nodeType === 3 ? n.textContent : n.tagName === 'BR' ? (/trailingBreak/.test(n.className || '') ? '' : '\n') : Array.from(n.childNodes).map(read).join('') + (/^(P|DIV)$/.test(n.tagName) ? '\n' : '');
    const observed = read(clone).replace(/\r\n/g, '\n');
    // Appended topic separators are tracked; arbitrary body whitespace is never collapsed.
    // Paragraph rendering may add or drop blank lines; words and their order must not change.
    const squeeze = v => v.replace(/\n+/g, '\n');
    const candidates = [observed, observed.replace(/\n$/, ''), ...(squeeze(observed) === squeeze(body) ? [body] : [])];
    const tail = (v, b) => v.startsWith(b) && /^[ \n]*$/.test(v.slice(b.length)) && v.length - b.length <= topics.length * 2 + 2;
    // Blank lines may collapse into paragraph breaks and each topic row leaves a break or space behind; both at once is still the same text.
    const so = squeeze(observed), sb = squeeze(body).replace(/\n$/, '');
    const sameText = so === sb || so.trimEnd() === sb.trimEnd() || (topics.length > 0 && tail(so, sb));
    if (!candidates.some(v => exact(v, body) || (topics.length > 0 && tail(v, body))) && !sameText) {
      const at = [...so].findIndex((c, i) => c !== sb[i]);
      return fail('正文回读不一致（回读 ' + so.length + ' 字 / 期望 ' + sb.length + ' 字，第 ' + at + ' 字起不同：回读「' + so.slice(Math.max(0, at - 4), at + 8).replace(/\n/g, '⏎') + '」期望「' + sb.slice(Math.max(0, at - 4), at + 8).replace(/\n/g, '⏎') + '」）');
    }
    const containers = all('[data-testid="upload-list"],.upload-list,.media-list,.img-list,.image-list,[class*="upload-list"],[class*="image-list"]')
      .filter(visible).filter(n => all('img,video', n).length > 0);
    const lists = containers.filter(n => !containers.some(other => other !== n && n.contains(other)));
    const media = lists.length === 1 ? all('img,video', lists[0]).filter(visible) : [];
    if (media.length !== mediaNames.length) return wait('等待媒体预览数量核齐');
    const progress = all('[role="progressbar"],.uploading,.processing,[class*="upload-progress"]', lists[0]).filter(visible);
    if (progress.length) {
      if (progress.every(n => /转码|处理中/.test(text(n)))) return {status: 'media_processing', upload_complete: true};
      return wait('等待媒体上传');
    }
    if (media.some(n => n.tagName === 'IMG' && (!n.complete || n.naturalWidth === 0))) return wait('等待图片预览');
    // The chooser is cleared once the platform takes the files; its previews carry no names.
    // Names are compared wherever the page still offers them; otherwise the order is the one delivered to the chooser.
    const chooser = all('input[type="file"]').find(n => n.files && n.files.length === mediaNames.length);
    const fileNames = chooser ? Array.from(chooser.files).map(f => f.name) : media.map(n => n.getAttribute('data-filename') || n.getAttribute('alt') || '');
    const known = fileNames.filter(Boolean);
    if (!resultMode && known.length && fileNames.some((n, i) => n && n !== mediaNames[i])) return fail('上传文件顺序无法回读确认（页面文件名：' + fileNames.join(',') + '）');
    const settingError = settings(false); if (settingError) return settingError;
    // The platform shows its submit control only once every image is stored on its side; until then the form is not ready.
    if (!resultMode) {
      const submitWords = /^(发布|立即发布|发布笔记)$/;
      const inNav = n => !!n.closest('nav,aside,[role="navigation"],[class*="sidebar"],[class*="side-bar"],[class*="menu-panel"],[class*="menu-container"]');
      const ps = publishState();
      const submits = ps.host ? (ps.button && !ps.busy ? [ps.button] : []) : deepAll('button,[role="button"],div,span').filter(n => visible(n) && submitWords.test(text(n).replace(/\s+/g, '')) && !inNav(n));
      if (ps.host && !ps.hasRoot) return fail('发布栏组件没有可读的内部按钮');
      if (ps.host && ps.hasRoot && !ps.busy && !ps.button) return fail('发布栏里找不到唯一的「' + (ps.host.getAttribute('submit-text') || '发布') + '」按钮（' + ps.count + ' 个）');
      if (!submits.length) {
        const busy = all('body *').filter(n => n.children.length === 0 && visible(n) && /上传中|处理中|转码|\d+%/.test(text(n))).map(n => text(n).slice(0, 10)).slice(0, 4);
        state.submitWaits = (state.submitWaits || 0) + 1;
        if (state.submitWaits > 30) {
          const inputs = deepAll('input[type="submit"],input[type="button"]').map(n => (visible(n) ? '' : '[隐藏]') + (n.value || '').slice(0, 8));
          const hosts = all('*').filter(n => n.shadowRoot).map(n => n.tagName.toLowerCase() + '[' + (n.shadowRoot.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 12) + ']').slice(0, 6);
          const frames = all('iframe').map(n => (n.getAttribute('src') || '').replace(/^https?:\/\//, '').slice(0, 30));
          const aria = all('[aria-label*="发布"],[title*="发布"]').filter(n => !inNav(n)).map(n => n.tagName.toLowerCase() + ':' + (n.getAttribute('aria-label') || n.getAttribute('title') || '').slice(0, 10));
          const errors = all('body *').filter(n => n.children.length === 0 && visible(n) && /失败|重试|错误|不符|超过|请/.test(text(n))).map(n => text(n).slice(0, 14)).slice(0, 5);
          const column = all('body *').filter(n => n.children.length === 0 && visible(n) && text(n) && n.getBoundingClientRect().left < 900 && !n.closest('nav,aside,[class*="menu"],.ProseMirror'))
            .sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top).map(n => text(n).replace(/\s+/g, ' ').slice(0, 10)).join('|').slice(0, 420);
          // What sits in the floating bar at the bottom of the viewport, whatever it is made of.
          const vh = window.innerHeight;
          const bar = deepAll('*').filter(n => { const r = n.getBoundingClientRect(); return r.top > vh - 120 && r.top < vh && r.width > 60 && r.width < 320 && r.height > 24 && r.height < 90 && !n.closest('nav,aside,[class*="menu"]'); })
            .slice(0, 8).map(n => { const cls = x => typeof x.className === 'string' && x.className ? '.' + x.className.trim().split(/\s+/).slice(0, 2).join('.') : ''; const r = n.getBoundingClientRect(); const ps = ['::before', '::after'].map(x => getComputedStyle(n, x).content).filter(c => c && c !== 'none' && c !== '""').join('/'); return n.tagName.toLowerCase() + cls(n) + '[' + (n.innerText || '').slice(0, 6) + '|' + (n.textContent || '').trim().slice(0, 6) + '|' + ps.slice(0, 10) + ']@' + Math.round(r.left) + ',' + Math.round(r.top); });
          const short = n => { const r = n.getBoundingClientRect(); const c = typeof n.className === 'string' && n.className ? '.' + n.className.trim().split(/\s+/).slice(0, 2).join('.') : ''; return n.tagName.toLowerCase() + c + '[' + (n.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 8) + ']@' + Math.round(r.left) + ',' + Math.round(r.top) + ' ' + Math.round(r.width) + 'x' + Math.round(r.height); };
          const fixed = all('body *').filter(n => /fixed|sticky/.test(getComputedStyle(n).position) && !n.closest('nav,aside,[class*="menu"]')).slice(0, 6).map(short);
          const red = all('body *').filter(n => /rgb\((2[0-9]{2}), ([0-6][0-9]|[0-9]), ([0-9]{1,3})\)/.test(getComputedStyle(n).backgroundColor) && n.getBoundingClientRect().width > 80).slice(0, 5).map(short);
          const tops = Array.from(document.body.children).map(n => n.tagName.toLowerCase() + (typeof n.className === 'string' && n.className ? '.' + n.className.trim().split(/\s+/)[0] : '') + (n.id ? '#' + n.id : '')).slice(0, 8);
          const customs = all('*').filter(n => n.tagName.includes('-') && /publish|btn|button|submit/i.test(n.tagName)).slice(0, 3).map(n => {
            const ctor = customElements.get(n.tagName.toLowerCase());
            const methods = ctor ? Object.getOwnPropertyNames(ctor.prototype).filter(k => k !== 'constructor').slice(0, 14).join(',') : '';
            const attrs = n.getAttributeNames().map(a => a + '=' + String(n.getAttribute(a)).slice(0, 24)).join(' ');
            return n.tagName.toLowerCase() + '{' + attrs + '}' + ' shadow:' + (n.shadowRoot ? 'open' : 'closed/none') + ' children:' + n.childElementCount + ' defined:' + !!ctor + ' methods:' + methods + ' keys:' + Object.keys(n).slice(0, 6).join(',');
          });
          const at = [[516, 805], [660, 805], [588, 805]].map(([x, y]) => { const e = document.elementFromPoint(x, y); return e ? e.tagName.toLowerCase() + (typeof e.className === 'string' && e.className ? '.' + e.className.split(/\s+/)[0] : '') : 'null'; });
          return fail(('平台没有出现发布按钮（自定义元素：' + (customs.join('；') || '无') + '；elementFromPoint：' + at.join('/') + '；fixed：' + (fixed.join('；') || '无') + '；红底：' + (red.join('；') || '无') + '；body 子节点：' + tops.join(',') + '；底栏元素：' + (bar.join('；') || '无') + '；视口高 ' + vh + '；input：' + (inputs.join('、') || '无') + '；aria：' + (aria.join('、') || '无') + '；shadow：' + (hosts.join('、') || '无') + '；iframe：' + (frames.join('、') || '无') + '；进度：' + (busy.join('、') || '无') + '）').slice(0, 900));
        }
        return wait('等待平台处理完图片、出现发布按钮' + (busy.length ? '（' + busy.join('、') + '）' : ''));
      }
    }
    return {status: 'proof', evidence: {
      identity_verified: true, account_profile_id: o.expected_profile_id,
      duplicate_checked: true, upload_complete: true, media_count: mediaNames.length,
      media_order: mediaNames, title, body, topics: actualTopics, topics_complete: true,
      settings: {allow_body_copy: !!o.allow_body_copy, scheduled: false, visibility: o.visibility || 'public'},
      settings_verified: true
    }};
  }
  // A note card is the largest block around one publish time, below the tabs and search box.
  const TIME = /^(?:发布于\s*)?\d{4}[-年./]\d{1,2}[-月./]\d{1,2}日?(?:\s+\d{1,2}:\d{2})?$/;
  const timeLeaves = root => all('*', root).filter(n => n.children.length === 0 && visible(n) && TIME.test(text(n).replace(/\s+/g, ' ')));
  const chrome = n => all('input[placeholder*="搜索"],[role="tablist"],[role="tab"]', n).length > 0;
  function cards() {
    const marked = all('[data-testid="note-card"],.note-card,[class*="note-card"],[class*="note-item"],[data-impression],article').filter(visible);
    const innermost = marked.filter(n => !marked.some(other => n !== other && n.contains(other)))
      .filter(n => timeLeaves(n).length === 1 || idOf(n) || all('a[href]', n).length);
    if (innermost.length) return innermost;
    const found = [];
    for (const time of timeLeaves(document.body)) {
      let card = null;
      for (let node = time.parentElement; node && node !== document.body; node = node.parentElement) {
        if (timeLeaves(node).length > 1 || chrome(node)) break;
        card = node;
      }
      if (card && !found.includes(card)) found.push(card);
    }
    return found;
  }
  const hitCards = () => cards().filter(n => text(n).split('\n').some(line => line.trim() === String(title).trim()));
  // Only attributes that name a note: data-note-id, an edit/explore link, or noteId inside data-* JSON.
  const idOf = n => {
    const values = [n, ...all('*', n)].flatMap(x => Array.from(x.attributes || []).map(a => [a.name, a.value]));
    for (const [name, value] of values) {
      const v = String(value || '');
      if (/^data-(note-?id|noteid)$/i.test(name) && /^[a-f\d]{24}$/i.test(v)) return v;
      if (name === 'href') {
        const m = v.match(/(?:[?&](?:id|noteId|note_id)=|\/(?:explore|discovery\/item|item|notes?)\/)([a-f\d]{24})(?:$|[/?&#])/i);
        if (m) return m[1];
      }
      if (/^data-/.test(name)) {
        const m = v.match(/["']?note_?id["']?\s*[:=]\s*["']([a-f\d]{24})["']/i);
        if (m) return m[1];
      }
    }
    return null;
  };
  // Class names and tags only, no page text: what to fix if the list cannot be read.
  const outline = () => {
    const main = all('main,[class*="content"],[class*="list"]').filter(visible).sort((a, b) => all('*', b).length - all('*', a).length)[0] || document.body;
    const names = all('*', main).slice(0, 400).map(n => n.tagName.toLowerCase() + (typeof n.className === 'string' && n.className ? '.' + n.className.trim().split(/\s+/)[0] : ''));
    return [...new Set(names)].slice(0, 40).join(' ');
  };
  function clickPublish() {
    const badIdentity = identity(); if (badIdentity) return badIdentity;
    const proof = contentProof(false); if (proof.status !== 'proof') return proof;
    // The publish control may be a styled div or span rather than a <button>.
    // The submit control reads 发布 / 立即发布 / 发布笔记 and sits in the form below the editor;
    // the side navigation has a 发布笔记 entry too, which only opens this page and is never it.
    const PUBLISH = /^(发布|立即发布|发布笔记)$/;
    const editorTop = (editor()[0] || document.body).getBoundingClientRect().top;
    const inChrome = n => !!n.closest('nav,aside,[role="navigation"],[role="menuitem"],[class*="sidebar"],[class*="side-bar"],[class*="menu"],[class*="tippy"],[class*="popover"]') || (n.matches('a[href]') && !/publish|submit|btn|button/i.test(typeof n.className === 'string' ? n.className : ''));
    const looksClickable = n => n.matches('button,[role="button"]') || !!n.closest('button,[role="button"],[class*="btn"],[class*="button"],[class*="publish"],[class*="submit"]') || getComputedStyle(n).cursor === 'pointer';
    const ps = publishState();
    if (ps.host) {
      if (ps.busy) return wait('等待发布按钮可用');
      if (!ps.button) return fail('发布栏里找不到唯一的发布按钮（' + ps.count + ' 个）');
    }
    const worded = ps.button ? [ps.button] : deepAll('button,[role="button"],a,div,span').filter(n => visible(n) && PUBLISH.test(text(n).replace(/\s+/g, '')));
    const labelled = ps.button ? worded : worded.filter(n => looksClickable(n) && !inChrome(n));
    const off = n => !enabled(n) || /(^|[\s_-])(disabled|is-disabled)(?=$|[\s_-])/.test(typeof n.className === 'string' ? n.className : '');
    const live = labelled.filter(n => !off(n));
    let nodes = live.filter(n => !live.some(other => other !== n && n.contains(other)));
    if (nodes.length > 1 && nodes.some(n => n.closest('button'))) nodes = nodes.filter(n => n.closest('button'));
    if (nodes.length > 1) {
      const owners = [...new Set(nodes.map(n => n.closest('button,[role="button"],[class*="btn"],[class*="button"]') || n))];
      if (owners.length === 1) nodes = [nodes[0]];
    }
    if (nodes.length !== 1) {
      // A disabled publish control means the platform is still processing; nothing has been clicked yet.
      if (!nodes.length && labelled.some(off)) return wait('等待发布按钮可用');
      // The submit bar appears only once the platform has taken all media; scroll the form to its end and wait for it.
      if (!nodes.length) {
        const boxes = all('body *').filter(n => /(auto|scroll)/.test(getComputedStyle(n).overflowY) && n.scrollHeight > n.clientHeight + 10);
        const box = boxes.sort((a, b) => b.scrollHeight - a.scrollHeight)[0] || document.scrollingElement || document.documentElement;
        box.scrollTop = box.scrollHeight;
        state.publishWaits = (state.publishWaits || 0) + 1;
        if (state.publishWaits <= 60) return wait('等待发布按钮出现');
      }
      const cls = x => typeof x.className === 'string' && x.className ? '.' + x.className.trim().split(/\s+/).slice(0, 2).join('.') : '';
      const where = n => { const r = n.getBoundingClientRect(); const anc = []; for (let x = n, i = 0; x && x !== document.body && i < 5; x = x.parentElement, i++) anc.push(x.tagName.toLowerCase() + cls(x)); return text(n).slice(0, 8) + ':' + anc.join('<') + '@' + Math.round(r.top) + ',' + Math.round(r.left); };
      const brief = n => { const r = n.getBoundingClientRect(); const anc = []; for (let x = n, i = 0; x && x !== document.body && i < 3; x = x.parentElement, i++) anc.push(x.tagName.toLowerCase() + cls(x)); return (visible(n) ? '' : '[隐藏]') + text(n).slice(0, 6) + ':' + anc.join('<') + '@' + Math.round(r.top); };
      const leaves = all('body *').filter(n => n.children.length === 0 && text(n) && !n.closest('[class*="menu"],nav,aside,.ProseMirror'));
      const acts = leaves.filter(n => /^(发布|立即发布|发布笔记|暂存离开|暂存|保存草稿|提交)$/.test(text(n).replace(/\s+/g, ''))).slice(0, 6).map(brief);
      const hiddenButtons = all('button').filter(n => !visible(n)).map(n => text(n).slice(0, 8)).filter(Boolean).slice(0, 6);
      const below = leaves.filter(n => visible(n)).sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top).slice(-8).map(brief);
      acts.push('最底 8 条：' + below.join('；'));
      return fail(('发布按钮无法唯一确认（找到 ' + nodes.length + ' 个；button 总数 ' + all('button').length + '；编辑器顶 ' + Math.round(editorTop) + '；隐藏按钮：' + (hiddenButtons.join('、') || '无') + '；动作文字：' + (acts.join('；') || '无') + '）').slice(0, 800));
    }
    if (state.clicked) return fail('此页面已点击发布，禁止重复');
    state.clicked = true;
    for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
      nodes[0].dispatchEvent(new MouseEvent(type, {bubbles: true, cancelable: true, composed: true, view: window, button: 0}));
    }
    return {status: 'clicked'};
  }
  if (phase === 'click') return clickPublish();
  if (phase === 'duplicate') {
    if (!/note-manager|draft/.test(location.pathname)) return wait('等待笔记管理');
    const search = all('input[placeholder*="搜索"]').filter(visible);
    if (!state.searchCleared && search.length === 1 && search[0].value) {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(search[0], '');
      search[0].dispatchEvent(new Event('input', {bubbles: true}));
      search[0].dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));
      state.searchCleared = true; return wait('清除旧笔记筛选');
    }
    if (hitCards().length) return {status: 'duplicate'};
    const badIdentity = identity();
    if (badIdentity?.status === 'identity_required') {
      const first = cards()[0];
      if (!first) {
        const empty = all('*').some(n => n.children.length === 0 && visible(n) && /暂无笔记|还没有发布|没有笔记|暂无数据/.test(text(n)));
        if (empty) return fail('该账号尚无可用于核验作者身份的后台笔记，请先人工核对账号');
        if (!state.allTab) {
          const allTab = [...button('全部笔记'), ...button('全部')];
          if (allTab.length === 1) { state.allTab = true; allTab[0].click(); return wait('切到全部笔记'); }
        }
        state.listTicks = (state.listTicks || 0) + 1;
        return state.listTicks > 40 ? fail('后台笔记列表读不到卡片（页面结构：' + outline() + '）') : wait('等待笔记列表加载');
      }
      const id = idOf(first);
      if (id) return {status: 'identity_note', note_id: id, url: 'https://www.rednote.com/discovery/item/' + id};
      const edits = all('button,[role="button"],a,span,div', first).filter(n => n.children.length === 0 && text(n) === '编辑' && !n.disabled);
      if (edits.length === 1) { edits[0].click(); return {status: 'identity_opening'}; }
      first.dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
      first.dispatchEvent(new MouseEvent('mouseenter', {bubbles: true}));
      state.identityTicks = (state.identityTicks || 0) + 1;
      return state.identityTicks > 8 ? fail('无法从后台原笔记打开作者身份核验') : wait('展开后台笔记操作');
    }
    if (badIdentity) return badIdentity;
    const tabs = [button('全部笔记').length ? '全部笔记' : '全部'];
    // Some official clients expose cloud drafts, others only the complete
    // note manager. Existing local jobs are checked by the backend; an
    // occupied editor also fails closed before any text is overwritten.
    if (button('草稿箱').length) tabs.push('草稿箱');
    state.scan = state.scan || {index: 0, selected: false, changed: null, pages: 0};
    const scan = state.scan;
    if (scan.index >= tabs.length) return {status: 'clear', identity_verified: true, account_profile_id: o.expected_profile_id};
    if (!scan.selected) {
      const matches = button(tabs[scan.index]);
      if (matches.length !== 1) return fail('无法完整核对已有笔记与草稿');
      scan.selected = true; scan.changed = null; matches[0].click(); return wait('核对' + tabs[scan.index]);
    }
    const signature = cards().map(text).join('|');
    if (scan.changed !== null && scan.changed === signature) return wait('等待下一页笔记');
    if (!cards().length && !all('[class*="empty"],[role="status"]').some(n => visible(n) && /暂无|没有|空空/.test(text(n)))) return wait('等待列表加载');
    if (hitCards().length) return {status: 'duplicate'};
    const next = all('button,[role="button"]').filter(n => enabled(n) && /^(下一页|Next)$/i.test(n.getAttribute('aria-label') || n.getAttribute('title') || text(n)));
    if (next.length === 1) {
      if (++scan.pages > 500) return fail('笔记列表分页过多，请先核对原记录');
      scan.changed = signature; next[0].click(); return wait('核对下一页');
    }
    scan.index++; scan.selected = false; return wait('核对下一分类');
  }
  if (phase === 'identity_open') {
    if (!/\/publish\/update/.test(location.pathname)) return wait('等待原笔记编辑地址');
    const id = new URL(location.href).searchParams.get('id');
    if (!/^[a-f0-9]{24}$/i.test(id || '')) return fail('原笔记地址缺少真实 note ID');
    return {status: 'identity_note', note_id: id, url: 'https://www.rednote.com/discovery/item/' + id};
  }
  if (phase === 'identity_verify') {
    const profilePath = '/user/profile/' + o.expected_profile_id;
    // Public note pages now need a platform token and redirect to /404; the
    // account's public profile page still opens, so identity is read there.
    if (/^\/404(?:\/|$)/.test(location.pathname)) return {status: 'identity_profile', url: 'https://www.rednote.com' + profilePath};
    if (location.pathname === profilePath) {
      const nameLeaves = all('body *').filter(n => n.children.length === 0 && visible(n) && text(n).replace(/\s+/g, ' ') === String(o.expected_name || '').trim());
      const isTitle = n => /^(H1|H2|H3)$/.test(n.tagName) || /name|nick|title|user/i.test(n.className || '') || /name|nick|title|user/i.test(n.parentElement?.className || '');
      if (nameLeaves.some(isTitle)) {
        const owner = all('button,[role="button"],a,span,div').some(n => n.children.length === 0 && visible(n) && /^(编辑资料|Edit profile)$/.test(text(n)));
        return {status: 'identity_verified', account_profile_id: o.expected_profile_id, basis: owner ? 'profile_owner' : 'profile_name'};
      }
      const missing = all('body *').some(n => n.children.length === 0 && visible(n) && /页面不存在|404|无法浏览|用户不存在/.test(text(n)));
      if (missing) return fail('目标账号公开主页打不开，无法核验身份');
      state.profileTicks = (state.profileTicks || 0) + 1;
      return state.profileTicks > 40 ? fail('公开主页上的账号名与目标不符') : wait('等待公开主页');
    }
    const authorRoots = all('[data-testid="note-author"],[class*="author-wrapper"],[class*="author-info"],[class*="author-container"]')
      .filter(n => visible(n) && !n.closest('[class*="comment"]'));
    if (!authorRoots.length) return wait('等待公开笔记作者栏');
    const verified = authorRoots.some(root => all('a[href]', root).some(n => {
      try { return new URL(n.getAttribute('href'), location.href).pathname === '/user/profile/' + o.expected_profile_id; } catch (_) { return false; }
    }) && [root, ...all('*', root)].some(n => n.children.length === 0 && text(n) === o.expected_name));
    return verified ? {status: 'identity_verified', account_profile_id: o.expected_profile_id} : fail('后台原笔记作者与目标账号 profile ID 不符');
  }
  if (phase === 'preflight') {
    if (o.duplicate_checked !== true) return fail('尚未核对已有笔记与草稿');
    const badIdentity = identity(); if (badIdentity) return badIdentity;
    const es = editor(); if (es.length !== 1) return wait('等待正文编辑器');
    const current = readTopics(es[0]);
    if (current.some(t => !topics.includes(t))) return fail('编辑器中出现其他结构化话题（' + current.filter(t => !topics.includes(t)).join('、') + '；节点：' + topicNodes(es[0]).slice(0, 6).map(describeNode).join('；') + '）');
    const missing = topics.find(t => !current.includes(t));
    if (missing) {
      // Tiptap keeps the typed "#topic" in a suggestion decoration while its popup is open:
      // commit that, never type the topic a second time on top of it.
      const pending = all('.suggestion,[data-decoration-id],[data-decoration-content]', es[0]).some(n => topicName(text(n)) === missing);
      if (state.topic === missing || pending) {
        state.topic = missing;
        // The suggestion list is matched by its text, not its class names: the
        // one visible leaf outside the editor whose text is exactly this topic.
        const outside = all('body *').filter(n => visible(n) && !es[0].contains(n));
        const marked = outside.filter(n => n.matches('[role="option"],.topic-item,[class*="topic-item"],[class*="topic-name"],[class*="topicName"]') && topicName(text(n)) === missing);
        // Recommended-topic chips with the same name were on the page before typing; only what appeared since counts.
        const fresh = n => !(state.preexisting || []).includes(n);
        const byText = outside.filter(n => n.children.length === 0 && topicName(text(n)) === missing && fresh(n));
        const candidates = marked.filter(fresh).length ? marked.filter(fresh) : byText;
        // Image-preview captions and recommendation chips also carry topic names; they are not the picker.
        const inPreview = n => !!n.closest('[class*="preview"],[class*="image-"],[class*="upload"]');
        const leaves = candidates.filter(n => !inPreview(n) && !candidates.some(other => other !== n && n.contains(other)));
        const chain = n => [n, n.parentElement, n.parentElement?.parentElement].filter(Boolean).map(x => x.tagName.toLowerCase() + (typeof x.className === 'string' && x.className ? '.' + x.className.trim().split(/\s+/)[0] : '')).reverse().join('>');
        // The platform lists same-named topics; inside one suggestion list the top row is what a person clicks.
        // Recommended-topic chips re-render after every insert; the suggestion list is told apart by its container.
        const listOf = n => n.closest('[class*="tippy"],[data-tippy-root],[class*="popper"],[class*="popover"],[class*="dropdown"],[class*="suggest"],[class*="mention"],[role="listbox"]');
        const listed = leaves.filter(listOf);
        const picks = listed.length ? listed : leaves;
        const oneList = picks.length > 1 && listOf(picks[0]) && picks.every(n => listOf(n) === listOf(picks[0]));
        if (picks.length === 1 || oneList) {
          state.commits = state.commits || {};
          const attempt = state.commits[missing] = (state.commits[missing] || 0) + 1;
          if (attempt > 4) {
            // Which element owns the handler (Vue keeps them in _vei) and where the list sits relative to the editor.
            const cls = x => typeof x.className === 'string' && x.className ? '.' + x.className.trim().split(/\s+/).slice(0, 2).join('.') : '';
            const describe = n => { const r = n.getBoundingClientRect(), er = es[0].getBoundingClientRect(); const anc = []; for (let x = n, i = 0; x && x !== document.body && i < 8; x = x.parentElement, i++) anc.push(x.tagName.toLowerCase() + cls(x) + (x._vei ? '{' + Object.keys(x._vei).join(',') + '}' : '')); return anc.join('<') + ' @' + Math.round(r.top - er.top) + ',' + Math.round(r.left - er.left); };
            return fail('点选话题后编辑器里没有出现结构化话题（用过：' + (state.ways || []).join('/') + '；候选：' + leaves.slice(0, 3).map(describe).join('；') + '）');
          }
          state.ways = state.ways || [];
          const highlighted = !!picks[0].closest('.is-selected,[aria-selected="true"],[class*="selected"],[class*="active"]');
          const row = picks[0].closest('[class*="item"],[role="option"],li') || picks[0];
          if (attempt % 2 === 1 && highlighted) {
            // Our row is the highlighted one; Enter in the editor commits it (Tiptap suggestion).
            state.ways.push('enter');
            es[0].dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true}));
          } else {
            // A person's click is mousedown, mouseup, click on the row; pickers often act on mousedown.
            const target = attempt <= 2 ? row : picks[0];
            state.ways.push('mouse');
            for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
              target.dispatchEvent(new MouseEvent(type, {bubbles: true, cancelable: true, composed: true, view: window, button: 0}));
            }
          }
          state.topic = null; state.justClicked = missing; state.readTicks = 0; return wait('回读结构化话题');
        }
        if (picks.length > 1) return fail('话题候选不唯一（' + picks.slice(0, 5).map(chain).join('；') + '）');
        if (++state.topicTicks > 25 && (state.tries || {})[missing] < 2) {
          // The popup did not come: take the typed "#topic" back out and type it once more.
          const typed = all('.suggestion,[data-decoration-id]', es[0]).find(n => topicName(text(n)) === missing);
          const range = document.createRange();
          if (typed) range.selectNodeContents(typed);
          else {
            const last = all('*', es[0]).filter(n => n.children.length === 0 && text(n).endsWith('#' + missing)).pop();
            if (!last) return fail('官方话题候选未出现，且找不到刚输入的话题文字');
            const node = last.firstChild || last; const full = node.textContent || '';
            range.setStart(node, Math.max(0, full.lastIndexOf('#' + missing))); range.setEnd(node, full.length);
          }
          const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range);
          document.execCommand('delete');
          state.topic = null; state.topicTicks = 0; return wait('重输话题');
        }
        if (state.topicTicks > 25) {
          const seen = outside.filter(n => n.children.length === 0 && text(n).includes(missing)).slice(0, 5)
            .map(n => [n, n.parentElement, n.parentElement?.parentElement].filter(Boolean).map(x => x.tagName.toLowerCase() + (typeof x.className === 'string' && x.className ? '.' + x.className.trim().split(/\s+/)[0] : '')).reverse().join('>'));
          return fail('官方话题候选未出现' + (seen.length ? '（页面上含该话题的元素：' + seen.join('；') + '）' : '（页面上没有任何含该话题的文字）'));
        }
        return wait('等待官方话题候选');
      }
      if (state.justClicked === missing && (state.readTicks = (state.readTicks || 0) + 1) <= 10) return wait('回读结构化话题');
      state.tries = state.tries || {};
      state.tries[missing] = (state.tries[missing] || 0) + 1;
      if (state.tries[missing] > 2) {
        const inside = all('*', es[0]).filter(n => n.children.length === 0 && text(n).includes(missing)).slice(0, 4)
          .map(n => [n.parentElement?.parentElement, n.parentElement, n].filter(Boolean).map(x => x.tagName.toLowerCase() + (typeof x.className === 'string' && x.className ? '.' + x.className.trim().split(/\s+/)[0] : '') + Array.from(x.attributes || []).filter(a => /^data-/.test(a.name)).map(a => '[' + a.name + ']').join('')).join('>'));
        return fail('点选话题后编辑器里没有出现结构化话题（编辑器内：' + (inside.join('；') || '没有该话题文字') + '）');
      }
      state.preexisting = all('body *').filter(n => visible(n) && !es[0].contains(n) && n.children.length === 0 && topicName(text(n)) === missing);
      es[0].focus();
      const range = document.createRange(); range.selectNodeContents(es[0]); range.collapse(false);
      const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range);
      // Tags sit together on one line under the body: a line break before the first, a space before the rest.
      const tail = (es[0].innerText || '').replace(/\u00a0/g, ' ');
      const lead = current.length === 0 ? '\n' : (/\s$/.test(tail) ? '' : ' ');
      if (!document.execCommand('insertText', false, lead + '#' + missing)) return fail('官方编辑器未接收话题查询');
      es[0].dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText', data: '#' + missing}));
      state.topic = missing; state.topicTicks = 0; return wait('搜索结构化话题');
    }
    const settingError = settings(true); if (settingError) return settingError;
    return contentProof(false);
  }
  if (phase === 'result') {
    if (!/note-manager/.test(location.pathname)) return wait('等待发布结果回查');
    const selected = all('[role="tab"][aria-selected="true"],.tab.active,.tab-item.active,[class*="tab"][class*="active"]').filter(visible).map(text);
    const hits = hitCards();
    if (hits.length !== 1) return hits.length > 1 ? fail('同标题结果不唯一，需人工核对') : wait('等待笔记记录');
    const card = hits[0], statusText = text(card);
    if (/未通过|发布失败|审核不通过/.test(statusText)) return fail('平台显示未通过');
    const result_status = /审核中|正在审核/.test(statusText) || selected.some(t => /^审核中/.test(t)) ? 'under_review' : selected.some(t => /^已发布/.test(t)) ? 'published' : null;
    if (!result_status) {
      const published = button('已发布');
      if (published.length === 1 && !state.resultTab) { state.resultTab = true; published[0].click(); return wait('核对已发布分类'); }
      return wait('无法确认实际发布状态');
    }
    const id = idOf(card);
    if (!id) return fail('官方记录未提供可核对的 note ID');
    // The manager's cards carry an 编辑 button rather than a link; the edit page address follows from the note id.
    const edit = all('a[href]', card).map(n => n.getAttribute('href')).find(h => /publish\/update/.test(h) && h.includes(id)) || ('/publish/update?id=' + id);
    return {status: 'result_card', note_id: id, result_status,
      url: 'https://www.rednote.com/discovery/item/' + id, edit_url: new URL(edit, location.href).href};
  }
  if (phase === 'result_verify') {
    const record = o.result_record || {};
    const id = new URL(location.href).searchParams.get('id');
    if (!id || id !== record.note_id || !['published', 'under_review'].includes(record.result_status)) return fail('编辑回查页面与笔记记录不一致');
    const badIdentity = identity(); if (badIdentity) return badIdentity;
    const proof = contentProof(true); if (proof.status !== 'proof') return proof;
    return {status: 'result', note_id: id, url: record.url, result_status: record.result_status,
      evidence: {...proof.evidence, content_verified: true, result_status: record.result_status}};
  }
  return fail('未知执行阶段');
})
