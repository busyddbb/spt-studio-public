(function () {
  'use strict';
  // Single-select listbox that replaces native <select> (WAI-ARIA "select-only combobox").
  // A hidden input keeps the old id and value and fires a bubbling `change`, so existing handlers keep working.

  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const normalize = (options) => (options || []).map((option) => (Array.isArray(option) ? { value: option[0], label: option[1] } : option));

  // options: [{value, label, hint?, disabled?}] or [[value, label]]
  // name: form field name for the hidden input; attrs: extra attributes for it (e.g. {'data-filter': 'status'}).
  // A disabled listbox also disables the hidden input, so it stays out of FormData like a disabled <select>.
  function listboxHTML({ id, label, value = '', options = [], showLabel = false, className = '', disabled = false, name = '', attrs = {} }) {
    const list = normalize(options);
    const current = list.find((option) => String(option.value) === String(value)) || list[0] || { value: '', label: '' };
    const key = esc(id);
    const extra = Object.entries(attrs || {}).map(([attr, val]) => (val === true ? ` ${esc(attr)}` : val === false || val == null ? '' : ` ${esc(attr)}="${esc(val)}"`)).join('');
    const items = list.map((option, index) => `<li role="option" id="${key}-opt-${index}" data-value="${esc(option.value)}" aria-selected="${option === current}"${option.disabled ? ' aria-disabled="true"' : ''}><span class="listbox-option-label">${esc(option.label)}</span>${option.hint ? `<span class="listbox-hint">${esc(option.hint)}</span>` : ''}<span class="icon i-check listbox-check" aria-hidden="true"></span></li>`).join('');
    return `<div class="listbox${className ? ` ${esc(className)}` : ''}" data-listbox><span class="listbox-label${showLabel ? '' : ' sr-only'}" id="${key}-label">${esc(label)}</span><input type="hidden" id="${key}"${name ? ` name="${esc(name)}"` : ''} value="${esc(current.value)}"${disabled ? ' disabled' : ''}${extra}><button type="button" class="listbox-button" id="${key}-button" role="combobox" aria-haspopup="listbox" aria-expanded="false" aria-controls="${key}-list" aria-labelledby="${key}-label"${disabled ? ' disabled' : ''}><span class="listbox-value">${esc(current.label)}</span><span class="icon i-caret-down" aria-hidden="true"></span></button><ul class="listbox-list" id="${key}-list" role="listbox" aria-labelledby="${key}-label" tabindex="-1" hidden>${items}</ul></div>`;
  }

  const parts = (root) => ({ root, input: root.querySelector('input[type=hidden]'), button: root.querySelector('.listbox-button'), list: root.querySelector('.listbox-list') });
  const enabled = (p) => [...p.list.querySelectorAll('[role=option]:not([aria-disabled=true])')];

  function show(p, option) {
    p.list.querySelectorAll('[role=option]').forEach((item) => item.setAttribute('aria-selected', String(item === option)));
    p.input.value = option.dataset.value;
    p.button.querySelector('.listbox-value').textContent = option.querySelector('.listbox-option-label').textContent;
  }

  function activate(p, option) {
    if (!option) return;
    p.list.querySelectorAll('.active').forEach((item) => item.classList.remove('active'));
    option.classList.add('active');
    p.button.setAttribute('aria-activedescendant', option.id);
    option.scrollIntoView({ block: 'nearest' });
  }

  function close(p) {
    p.list.hidden = true;
    p.button.setAttribute('aria-expanded', 'false');
    p.button.removeAttribute('aria-activedescendant');
    p.root.classList.remove('open', 'listbox-up', 'listbox-end');
    p.list.querySelectorAll('.active').forEach((item) => item.classList.remove('active'));
  }

  function closeAll(except) {
    document.querySelectorAll('[data-listbox].open').forEach((root) => { if (root !== except) close(parts(root)); });
  }

  function open(p, index) {
    closeAll(p.root);
    p.list.hidden = false;
    p.button.setAttribute('aria-expanded', 'true');
    p.root.classList.add('open');
    // Open upwards / align right when the list would run past the window edge.
    const box = p.button.getBoundingClientRect();
    const height = p.list.offsetHeight;
    if (box.bottom + height + 8 > innerHeight && box.top - height - 8 > 0) p.root.classList.add('listbox-up');
    if (box.left + p.list.offsetWidth + 8 > innerWidth) p.root.classList.add('listbox-end');
    const options = enabled(p);
    let at = index ?? options.findIndex((option) => option.getAttribute('aria-selected') === 'true');
    if (at < 0) at = 0;
    activate(p, options[Math.min(at, options.length - 1)]);
  }

  // A change handler often re-renders the page (sometimes after a fetch), which drops focus to <body>.
  // For a moment afterwards, put focus back on the re-rendered button (same id) unless it has moved on purpose.
  function refocus(button) {
    let frames = 0;
    const tick = () => {
      const active = document.activeElement;
      if (!active || active === document.body || !active.isConnected) {
        const next = document.getElementById(button.id);
        if (next && next !== button && !next.disabled) { next.focus(); return; }
      } else if (active !== button) return;
      if (++frames < 90) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  function fireChange(p) {
    p.input.dispatchEvent(new Event('change', { bubbles: true }));
    refocus(p.button);
  }

  function choose(p, option) {
    if (!option || option.getAttribute('aria-disabled') === 'true') return;
    const changed = p.input.value !== option.dataset.value;
    show(p, option);
    close(p);
    p.button.focus();
    if (changed) fireChange(p);
  }

  // Enable or disable options after render (e.g. until data they depend on has loaded).
  function setDisabled(id, isDisabled) {
    const input = document.getElementById(id);
    const root = input && input.closest('[data-listbox]');
    if (!root) return;
    root.querySelectorAll('[role=option]').forEach((option) => {
      if (isDisabled(option.dataset.value)) option.setAttribute('aria-disabled', 'true');
      else option.removeAttribute('aria-disabled');
    });
  }

  // Update the shown value without firing `change` (for state restored in code).
  function setValue(id, value) {
    const input = document.getElementById(id);
    const root = input && input.closest('[data-listbox]');
    if (!root) return;
    const p = parts(root);
    const option = [...p.list.querySelectorAll('[role=option]')].find((item) => item.dataset.value === String(value));
    if (option) show(p, option);
  }

  let typed = '';
  let typedAt = 0;

  function onKey(event) {
    const button = event.target.closest && event.target.closest('.listbox-button');
    if (!button) return;
    const p = parts(button.closest('[data-listbox]'));
    const options = enabled(p);
    const isOpen = !p.list.hidden;
    const current = options.indexOf(p.list.querySelector('.active'));
    const go = (index) => { event.preventDefault(); activate(p, options[Math.max(0, Math.min(options.length - 1, index))]); };
    switch (event.key) {
      case 'ArrowDown': if (!isOpen) { event.preventDefault(); open(p); } else go(current + 1); return;
      case 'ArrowUp':
        if (!isOpen) { event.preventDefault(); open(p); } else if (event.altKey) { event.preventDefault(); choose(p, options[current]); } else go(current - 1);
        return;
      case 'Home': event.preventDefault(); if (isOpen) go(0); else open(p, 0); return;
      case 'End': event.preventDefault(); if (isOpen) go(options.length - 1); else open(p, options.length - 1); return;
      case 'PageDown': if (isOpen) go(current + 10); return;
      case 'PageUp': if (isOpen) go(current - 10); return;
      case 'Enter': case ' ': event.preventDefault(); if (isOpen) choose(p, options[current]); else open(p); return;
      // Capture-phase stop keeps Escape from also closing a surrounding dialog.
      case 'Escape': if (isOpen) { event.preventDefault(); event.stopPropagation(); close(p); } return;
      case 'Tab': if (isOpen) close(p); return;
      default:
        if (event.key.length !== 1 || event.metaKey || event.ctrlKey || event.altKey) return;
        typed = Date.now() - typedAt > 600 ? event.key.toLowerCase() : typed + event.key.toLowerCase();
        typedAt = Date.now();
        {
          const match = options.find((option) => option.textContent.trim().toLowerCase().startsWith(typed));
          if (!match) return;
          event.preventDefault();
          if (isOpen) activate(p, match);
          else if (p.input.value !== match.dataset.value) { show(p, match); fireChange(p); }
        }
    }
  }

  function bind(doc = document) {
    doc.addEventListener('keydown', onKey, true);
    // A button fires `click` on Space keyup; the keydown above already handled it.
    doc.addEventListener('keyup', (event) => { if (event.key === ' ' && event.target.closest && event.target.closest('.listbox-button')) event.preventDefault(); }, true);
    // Keep focus on the button while picking with the mouse.
    doc.addEventListener('mousedown', (event) => { if (event.target.closest && event.target.closest('.listbox-list')) event.preventDefault(); });
    doc.addEventListener('mouseover', (event) => {
      const option = event.target.closest && event.target.closest('[data-listbox] [role=option]:not([aria-disabled=true])');
      if (option) activate(parts(option.closest('[data-listbox]')), option);
    });
    doc.addEventListener('click', (event) => {
      const button = event.target.closest && event.target.closest('.listbox-button');
      if (button) { const p = parts(button.closest('[data-listbox]')); if (p.list.hidden) open(p); else close(p); return; }
      // preventDefault stops a wrapping <label> from forwarding the click to the button and reopening the list.
      const list = event.target.closest && event.target.closest('[data-listbox] .listbox-list');
      if (list) {
        event.preventDefault();
        const option = event.target.closest('[role=option]');
        if (option) choose(parts(list.closest('[data-listbox]')), option);
        return;
      }
      closeAll(null);
    });
    doc.addEventListener('focusout', (event) => {
      const root = event.target.closest && event.target.closest('[data-listbox]');
      if (root && root.classList.contains('open') && !root.contains(event.relatedTarget)) close(parts(root));
    });
    addEventListener('resize', () => closeAll(null));
  }

  const exported = { listboxHTML, setValue, setDisabled, bind, closeAll };
  if (typeof window !== 'undefined') window.SPTListbox = exported;
  if (typeof module !== 'undefined' && module.exports) module.exports = exported;
}());
