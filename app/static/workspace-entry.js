'use strict';
(() => {
  // Styled selects (shared with the SPT window) listen on the document.
  window.SPTListbox?.bind();
  const params = new URL(location.href).searchParams;
  const embedded = params.get('embed') === '1' && window.parent !== window;
  const sameOriginParent = () => { try { return window.parent.location.origin === location.origin ? window.parent : null; } catch { return null; } };
  // Tool pages the SPT window knows by name; the names are the same words as the hashes here.
  const TOOLS = new Set(['studio', 'accounts', 'planner', 'uploads', 'planning', 'data', 'publish', 'connections']);
  const windowHook = () => { try { return typeof window.parent.sptToolNavigated === 'function'; } catch { return false; } };
  if (embedded) {
    document.documentElement.classList.add('embedded');
    const parent = sameOriginParent();
    // The native bridge announces itself on the top page; inside the SPT window the tools share it.
    if (parent) {
      for (const flag of ['mediaNativeAvailable', 'mediaPublishingNativeAvailable', 'mediaRednoteUploadNativeAvailable']) {
        if (parent[flag] && !window[flag]) window[flag] = true;
      }
      // Same look as the SPT window: theme, density and motion follow the main page.
      const copyLook = () => {
        for (const key of ['theme', 'density', 'motion']) {
          const value = parent.document.documentElement.dataset[key];
          if (value) document.documentElement.dataset[key] = value;
        }
      };
      copyLook();
      new MutationObserver(copyLook).observe(parent.document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'data-density', 'data-motion'] });
    }
    // The old project page has a newer version in the SPT window (运营): open that instead.
    // Only once the window can follow along (it then provides sptToolNavigated).
    window.addEventListener('click', (event) => {
      if (!parent || !windowHook() || !(event.target instanceof Element)) return;
      if (!event.target.closest('a[href="#desk"]')) return;
      event.preventDefault();
      event.stopPropagation();
      parent.location.hash = '#desk';
    }, true);
    // Links to the main SPT pages move the whole window, not just this frame.
    document.addEventListener('click', (event) => {
      const link = event.target.closest('a[href^="/workspace/"]');
      if (!link || !parent) return;
      event.preventDefault();
      parent.location.hash = new URL(link.href, location.origin).hash || '#desk';
    });
    // ⌘K / Ctrl+K inside a tool page opens the SPT window's command palette (same keys as the window itself).
    document.addEventListener('keydown', (event) => {
      if (!(event.metaKey || event.ctrlKey) || event.altKey || event.shiftKey || event.isComposing) return;
      if (String(event.key).toLowerCase() !== 'k' && event.code !== 'KeyK') return;
      let opened = false;
      try {
        if (typeof window.parent.sptOpenPalette === 'function') {
          window.SPTListbox?.closeAll?.();
          window.parent.sptOpenPalette();
          opened = true;
        }
      } catch { /* the window can live without it */ }
      if (opened) event.preventDefault();
    });
  }
  // Tell the SPT window which tool is showing, so its sidebar and title follow in-frame moves.
  const syncTool = () => {
    if (!embedded) return;
    const name = location.hash.slice(1).split('?')[0];
    if (!TOOLS.has(name)) return;
    try { if (windowHook()) window.parent.sptToolNavigated(name); } catch { /* the window can live without it */ }
  };
  const revealCurrentTool = () => {
    const tools = document.getElementById('legacy-tools');
    if (tools) tools.open = embedded || !['publish', 'connections'].includes(location.hash.slice(1));
  };
  revealCurrentTool();
  syncTool();
  window.addEventListener('hashchange', () => { revealCurrentTool(); syncTool(); });
  const draftId = params.get('draft_id');
  if (draftId && /^[A-Za-z0-9_-]{1,128}$/.test(draftId)) {
    window.MediaDesk?.selectDraft(draftId);
  }
})();
