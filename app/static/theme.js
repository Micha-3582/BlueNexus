/* Darstellung: dunkel / hell / automatisch (nach Geraet). Wird im <head> geladen, damit die Seite nicht kurz im falschen Stil aufblitzt. */
(function () {
  var KEY = 'hn_theme', root = document.documentElement, mq = window.matchMedia ? window.matchMedia('(prefers-color-scheme: light)') : null;
  function get() { try { return localStorage.getItem(KEY) || 'auto'; } catch (e) { return 'auto'; } }
  function effective(c) { return c === 'light' || c === 'dark' ? c : (mq && mq.matches ? 'light' : 'dark'); }
  function apply() {
    var e = effective(get());
    root.setAttribute('data-theme', e);
    var m = document.querySelector('meta[name=theme-color]');
    if (m) m.setAttribute('content', e === 'light' ? '#ffffff' : '#1b1f24');
  }
  window.HNTheme = {
    get: get, effective: function () { return effective(get()); },
    set: function (t) { try { if (t === 'light' || t === 'dark') localStorage.setItem(KEY, t); else localStorage.removeItem(KEY); } catch (e) { /* Komfort */ } apply(); }
  };
  apply();
  document.addEventListener('DOMContentLoaded', apply);
  if (mq && mq.addEventListener) mq.addEventListener('change', function () { if (get() === 'auto') apply(); });
})();
