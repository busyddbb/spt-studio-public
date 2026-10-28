// Runs in <head> before the stylesheet paints: theme, motion, density and route from saved state.
// A file, not an inline script: the app's server sends script-src 'self'.
(() => {
  const root = document.documentElement;
  const read = (name, fallback) => { try { return localStorage.getItem(`media-studio.${name}`) || fallback; } catch { return fallback; } };
  const theme = read('theme', 'dark');
  root.dataset.theme = theme === 'light' ? 'light' : theme === 'system' ? (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light') : 'dark';
  root.dataset.motion = read('motion', 'full') === 'reduced' ? 'reduced' : 'full';
  root.dataset.density = read('density', 'comfortable') === 'compact' ? 'compact' : 'comfortable';
  const route = location.hash.slice(1).split('?')[0];
  root.dataset.route = ['works', 'notes', 'analytics', 'intelligence', 'publish', 'settings', 'tools'].includes(route) ? route : 'desk';
})();
