/* Hintergrund-Knotennetz im Worker (OffscreenCanvas): laeuft unabhaengig vom Hauptthread der Seite, damit die Animation nicht stehen bleibt,
   wenn die Seite gerade etwas Schweres tut (Klick, Neuzeichnen, Daten laden). Gezeichnet wird exakt wie in bg.js (dort als Rueckfall). */
var cv = null, ctx = null, W = 0, H = 0, dpr = 1, nodes = [], mx = -999, my = -999, run = false, blue = '#4b9be6', ora = '#f48c24';
function size(w, h, d) {
  W = w; H = h; dpr = d; cv.width = W * dpr; cv.height = H * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  var n = Math.round(Math.min(70, Math.max(24, W * H / 16000))); nodes = [];
  for (var i = 0; i < n; i++) nodes.push({ x: Math.random() * W, y: Math.random() * H, vx: (Math.random() - .5) * .22, vy: (Math.random() - .5) * .22, o: Math.random() < .12 });
}
function frame() {
  if (!run) return;
  ctx.clearRect(0, 0, W, H);
  var D = 150;
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
onmessage = function (e) {
  var m = e.data;
  if (m.t === 'init') {
    if (typeof requestAnimationFrame !== 'function') { postMessage({ t: 'norAF' }); return; }       // aeltere Browser: Zeichnen im Hauptthread (Rueckfall in bg.js)
    cv = m.canvas; ctx = cv.getContext('2d'); if (!ctx) { postMessage({ t: 'norAF' }); return; }
    blue = m.blue || blue; ora = m.ora || ora; size(m.w, m.h, m.dpr);
  } else if (!cv) return;
  else if (m.t === 'size') size(m.w, m.h, m.dpr);
  else if (m.t === 'pt') { mx = m.x; my = m.y; }
  else if (m.t === 'col') { blue = m.blue || blue; ora = m.ora || ora; }
  else if (m.t === 'run') { if (m.on && !run) { run = true; requestAnimationFrame(frame); } else if (!m.on) run = false; }
};
