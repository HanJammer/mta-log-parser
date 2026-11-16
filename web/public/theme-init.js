// Applies the saved theme and density before the first paint (kept external for CSP script-src 'self').
(function () {
  try {
    var p = localStorage.getItem('mlp.theme');
    var dark = p === 'dark' || (p !== 'light' && window.matchMedia('(prefers-color-scheme: dark)').matches);
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
    var prefs = JSON.parse(localStorage.getItem('mlp.prefs') || '{}');
    if (prefs && prefs.density === 'comfortable') document.documentElement.setAttribute('data-density', 'comfortable');
  } catch (e) {
    /* defaults */
  }
})();
