/* Hintergrund: leuchtendes Knotennetz hinter den Karten (Canvas). Verlauf und Gitter sind reines CSS (theme.css) und laufen immer.
   Pro Geraet abschaltbar (Einstellungen -> Darstellung); pausiert bei verdecktem Tab, laeuft nicht bei "Bewegung reduzieren".
   Gezeichnet wird in einem Worker (OffscreenCanvas, bg-worker.js), damit die Animation nicht stehen bleibt, wenn der Hauptthread der Seite beschaeftigt ist
   (Klick, Neuzeichnen, Daten laden). Wo das nicht geht, zeichnet diese Datei selbst im Hauptthread (Rueckfall). */
(function () {
  var KEY = 'hn_bg', cv = null, run = false, started = false, wk = null, mode = '';
  var SELF = document.currentScript && document.currentScript.src;
  function enabled() { try { return localStorage.getItem(KEY) !== 'off'; } catch (e) { return true; } }
  function reduced() { return window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches; }
  var W = 0, H = 0, dpr = 1, nodes = [], mx = -999, my = -999, ctx = null;
  var col = function (v, d) { return getComputedStyle(document.documentElement).getPropertyValue(v).trim() || d; };
  var BLUE = '#4b9be6', ORA = '#f48c24';
  function dims() { dpr = Math.min(window.devicePixelRatio || 1, 2); W = innerWidth; H = innerHeight; }
  function size() {                                                    // Rueckfall (Hauptthread)
    dims(); cv.width = W * dpr; cv.height = H * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    var n = Math.round(Math.min(70, Math.max(24, W * H / 16000))); nodes = [];
    for (var i = 0; i < n; i++) nodes.push({ x: Math.random() * W, y: Math.random() * H, vx: (Math.random() - .5) * .22, vy: (Math.random() - .5) * .22, o: Math.random() < .12 });
  }
  function frame() {                                                   // Rueckfall (Hauptthread)
    if (!run || mode !== 'main') return;
    ctx.clearRect(0, 0, W, H);
    var blue = col('--accent-t', '#4b9be6'), ora = col('--brand', '#f48c24'), D = 150;
    for (var i = 0; i < nodes.length; i++) {
      var a = nodes[i]; a.x += a.vx; a.y += a.vy;
      if (a.x < 0 || a.x > W) a.vx *= -1;
      if (a.y < 0 || a.y > H) a.vy *= -1;
      for (var j = i + 1; j < nodes.length; j++) {
        var b = nodes[j], dx = a.x - b.x, dy = a.y - b.y, d = Math.sqrt(dx * dx + dy * dy);
        if (d < D) { ctx.globalAlpha = (1 - d / D) * .35; ctx.strokeStyle = blue; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke(); }
      }
      var m = Math.hypot(a.x - mx, a.y - my), boost = m < 160 ? 1 - m / 160 : 0;
      ctx.globalAlpha = .55 + boost * .45; ctx.fillStyle = a.o ? ora : blue;
      ctx.beginPath(); ctx.arc(a.x, a.y, (a.o ? 2.6 : 1.8) + boost * 2, 0, 6.2832); ctx.fill();
    }
    ctx.globalAlpha = 1; requestAnimationFrame(frame);
  }
  function newCanvas() {
    if (cv && cv.parentNode) cv.parentNode.removeChild(cv);
    cv = document.createElement('canvas'); cv.id = 'net'; cv.setAttribute('aria-hidden', 'true');
    document.body.insertBefore(cv, document.body.firstChild);
  }
  function colors() { return { blue: col('--accent-t', BLUE), ora: col('--brand', ORA) }; }
  function useMain() {                                                 // Rueckfall: im Hauptthread zeichnen (neues Canvas, das alte gehoert dem Worker)
    if (wk) { try { wk.terminate(); } catch (e) { /* egal */ } wk = null; }
    newCanvas(); ctx = cv.getContext('2d'); if (!ctx) return false;
    mode = 'main'; size(); return true;
  }
  function useWorker() {
    try {
      if (!SELF || !window.Worker || !window.OffscreenCanvas || !cv.transferControlToOffscreen) return false;
      var off = cv.transferControlToOffscreen();
      wk = new Worker(SELF.replace(/bg\.js(\?.*)?$/, 'bg-worker.js$1'));
      wk.onmessage = function (e) { if (e.data && e.data.t === 'norAF' && mode === 'worker') { mode = ''; if (useMain() && run) requestAnimationFrame(frame); } };
      wk.onerror = function () { if (mode === 'worker') { mode = ''; if (useMain() && run) requestAnimationFrame(frame); } };
      dims(); var c = colors();
      wk.postMessage({ t: 'init', canvas: off, w: W, h: H, dpr: dpr, blue: c.blue, ora: c.ora }, [off]);
      mode = 'worker'; return true;
    } catch (e) { wk = null; return false; }
  }
  function go(on) {                                                    // Animation starten/anhalten
    run = on;
    if (mode === 'worker' && wk) wk.postMessage({ t: 'run', on: on });
    else if (mode === 'main' && on) requestAnimationFrame(frame);
  }
  function start() {
    if (!enabled() || reduced() || !document.body) return;
    if (!cv) {
      newCanvas();
      if (!useWorker()) { if (cv.getContext && !useMain()) return; }
    }
    cv.style.display = '';
    if (mode === 'main') size(); else if (mode === 'worker') { dims(); wk.postMessage({ t: 'size', w: W, h: H, dpr: dpr }); }
    if (!started) {
      started = true;
      addEventListener('resize', function () { if (!run) return; if (mode === 'worker' && wk) { dims(); wk.postMessage({ t: 'size', w: W, h: H, dpr: dpr }); } else if (mode === 'main') size(); });
      addEventListener('pointermove', function (e) { mx = e.clientX; my = e.clientY; if (mode === 'worker' && wk) wk.postMessage({ t: 'pt', x: mx, y: my }); });
      setInterval(function () { if (mode === 'worker' && wk && run) { var c = colors(); wk.postMessage({ t: 'col', blue: c.blue, ora: c.ora }); } }, 2000);      // Farbwechsel (Theme) uebernehmen
      document.addEventListener('visibilitychange', function () { if (document.hidden) go(false); else if (cv && cv.style.display !== 'none' && !run && enabled()) go(true); });
    }
    if (!run) go(true);
  }
  function stop() { go(false); if (cv) cv.style.display = 'none'; }
  window.HNBg = { get: enabled, set: function (on) { try { if (on) localStorage.removeItem(KEY); else localStorage.setItem(KEY, 'off'); } catch (e) { /* Komfort */ } if (on) start(); else stop(); } };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
