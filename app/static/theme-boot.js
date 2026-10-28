'use strict';
// Runs before the stylesheets so the tool pages open in the right theme (no white flash).
// It has to be a file: the page's content security policy blocks inline scripts.
(function () {
  var root = document.documentElement;
  var theme = '';
  var embedded = false;
  try { embedded = new URLSearchParams(location.search).get('embed') === '1' && window.parent !== window; } catch (error) { /* plain page */ }
  // Inside the SPT window: take the look from the main page.
  try {
    if (window.parent !== window) {
      var look = window.parent.document.documentElement.dataset;
      theme = look.theme || '';
      if (look.density) root.dataset.density = look.density;
      if (look.motion) root.dataset.motion = look.motion;
    }
  } catch (error) { /* parent on another origin */ }
  var saved = function (name, fallback) {
    try { return localStorage.getItem('media-studio.' + name) || fallback; } catch (error) { return fallback; }
  };
  if (theme !== 'light' && theme !== 'dark') {
    var choice = saved('theme', 'dark');
    if (choice === 'system') {
      try { choice = matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'; } catch (error) { choice = 'dark'; }
    }
    theme = choice === 'light' ? 'light' : 'dark';
  }
  if (!root.dataset.density) root.dataset.density = saved('density', 'comfortable') === 'compact' ? 'compact' : 'comfortable';
  if (!root.dataset.motion) root.dataset.motion = saved('motion', 'full') === 'reduced' ? 'reduced' : 'full';
  root.dataset.theme = theme;
  if (embedded) root.classList.add('embedded');
})();
