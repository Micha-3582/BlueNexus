/* Gemeinsame Diagramm-Zeichnung fuer die Verlaeufe (Seite "Verlaeufe" und Dashboard-Kachel). Benoetigt Chart.js.
 *
 *   VLChart.draw(inst, c, series, d, t0, t1, cv, opts) -> { any, created }
 *     inst    Objekt {diagramm-id: Chart} (wird gepflegt)
 *     c       Diagramm {id, title, series: [ids], colors: {id: '#rrggbb'}}
 *     series  {id: {label, unit, binary, ...}} (Register der Reihen)
 *     d       Antwort von /api/verlauf/data ({series: {id: {points, bucket_s, interval_s}}})
 *     t0, t1  Zeitraum in ms;  cv = <canvas>
 *     opts    { legend: true, theme: 'dark' | 'light', onCreate(chart) }
 */
window.VLChart = (function () {
  var COLORS = ['#4b9be6', '#35c07a', '#f0b429', '#e5544a', '#b57bee', '#2ec4b6', '#ff8fab', '#a0a8b8'];
  var STEPS = [60e3, 300e3, 600e3, 900e3, 1800e3, 3600e3, 7200e3, 10800e3, 21600e3, 43200e3, 86400e3, 172800e3, 604800e3, 2592000e3];

  function niceTicks(t0, t1, want) {
    var step = STEPS.find(function (s) { return (t1 - t0) / s <= want; }) || STEPS[STEPS.length - 1];
    var off = new Date(t0).getTimezoneOffset() * 60000, out = [];
    for (var t = Math.ceil((t0 + off) / step) * step - off; t <= t1; t += step) out.push({ value: t });
    return out;
  }
  function fmtTick(v, span) {
    var d = new Date(v), p = function (n) { return String(n).padStart(2, '0'); };
    if (span <= 36 * 3600000) return p(d.getHours()) + ':' + p(d.getMinutes());
    if (span <= 8 * 86400000) return p(d.getDate()) + '.' + p(d.getMonth() + 1) + '. ' + p(d.getHours()) + ':' + p(d.getMinutes());
    return p(d.getDate()) + '.' + p(d.getMonth() + 1) + '.' + String(d.getFullYear()).slice(2);
  }
  function fmtNum(v) {
    return v == null ? '–' : Math.abs(v) >= 100 ? Math.round(v).toLocaleString('de-DE') : v.toLocaleString('de-DE', { maximumFractionDigits: 2 });
  }

  /* Anzahl Punkte, die der Server liefern soll: Linien fein, Balken grob (sonst werden sie zu duenn) */
  function pointsFor(kind, width, scale) {
    return (kind === 'bar' || kind === 'stackbar') ? Math.max(20, Math.min(400, Math.round(width / 8))) : Math.min(2500, Math.max(300, Math.round(width * (scale || 1.4))));
  }

  function draw(inst, c, series, d, t0, t1, cv, opts) {
    opts = opts || {};
    var light = opts.theme === 'light';
    var TICK = light ? '#444b57' : '#9aa4b5', GRIDC = light ? 'rgba(0,0,0,.14)' : 'rgba(255,255,255,.08)', LEG = light ? '#222a35' : '#c8d0dc';
    var kind = ['line', 'area', 'bar', 'step', 'points', 'stackarea', 'stackbar'].indexOf(c.kind) >= 0 ? c.kind : 'line';
    var isBar = kind === 'bar' || kind === 'stackbar', stacked = kind === 'stackarea' || kind === 'stackbar';          // gestapelt: Reihen derselben Achse werden aufeinandergelegt
    if (inst[c.id] && inst[c.id]._vlKind !== kind) { inst[c.id].destroy(); delete inst[c.id]; }          // Darstellung gewechselt: neu aufbauen
    var ids = c.series.filter(function (i) { return series[i]; });
    var units = [];
    ids.forEach(function (i) { var u = series[i].binary ? '__b' : (series[i].unit || ''); if (units.indexOf(u) < 0) units.push(u); });
    var real = units.filter(function (u) { return u !== '__b'; });
    var axisOf = function (u) { return u === '__b' ? 'yb' : (u === real[0] ? 'y' : 'y1'); };
    var datasets = [], any = false;
    ids.forEach(function (id, k) {
      var s = d.series[id], col = (c.colors || {})[id] || COLORS[k % COLORS.length], bin = !!series[id].binary;
      var ax = axisOf(bin ? '__b' : (series[id].unit || '')), pts = (s && s.points) || [];
      if (pts.some(function (p) { return p[1] != null; })) any = true;
      var step = !!series[id].step;                       // z. B. Strompreis: Stufenlinie, kein Min/Max-Band
      var banded = kind === 'line' && !bin && !step && s && s.bucket_s > s.interval_s * 1.5;
      if (banded) {
        datasets.push({ label: '_min', _band: true, data: pts.map(function (p) { return { x: p[0], y: p[2] }; }), borderWidth: 0, pointRadius: 0, fill: false, yAxisID: ax, spanGaps: false });
        datasets.push({ label: '_max', _band: true, data: pts.map(function (p) { return { x: p[0], y: p[3] }; }), borderWidth: 0, pointRadius: 0, fill: '-1', backgroundColor: col + '30', yAxisID: ax, spanGaps: false });
      }
      datasets.push({ label: series[id].label + (series[id].unit && !bin ? ' (' + series[id].unit + ')' : ''), _unit: series[id].unit || '', _bin: bin, _minmax: banded,
        data: pts.map(function (p) { return { x: p[0], y: p[1], mn: p[2], mx: p[3] }; }),
        borderColor: col, backgroundColor: isBar ? col + 'cc' : (kind === 'area' ? col + '33' : (kind === 'stackarea' ? col + '88' : col)), borderWidth: isBar ? 0 : 1.3,
        pointRadius: kind === 'points' ? 2 : 0, pointHoverRadius: 4, showLine: kind !== 'points', fill: (kind === 'stackarea' && !bin) ? 'stack' : (kind === 'area' ? 'origin' : false), tension: 0,
        stepped: (bin || step || kind === 'step') ? 'before' : false, yAxisID: ax, spanGaps: false, barPercentage: 0.9, categoryPercentage: 0.9 });
    });
    var span = t1 - t0, grid = { color: GRIDC };
    var scales = {
      x: { type: 'linear', min: t0, max: t1, grid: grid, ticks: { color: TICK, maxRotation: 0, callback: function (v) { return fmtTick(v, span); } },
        afterBuildTicks: function (ax) { ax.ticks = niceTicks(ax.min, ax.max, Math.max(3, Math.min(10, Math.floor(ax.chart.width / 90)))); } },
      y: { position: 'left', beginAtZero: isBar || stacked, stacked: stacked, grid: grid, ticks: { color: TICK }, title: { display: !!real[0], text: real[0] || '', color: TICK } }
    };
    if (real.length > 1) scales.y1 = { position: 'right', beginAtZero: isBar || stacked, stacked: stacked, grid: { drawOnChartArea: false }, ticks: { color: TICK }, title: { display: true, text: real.slice(1).join(' / '), color: TICK } };
    if (units.indexOf('__b') >= 0) scales.yb = { display: false, min: -0.05, max: 1.05 };
    if (kind === 'stackbar') scales.x.stacked = true;
    var existing = inst[c.id];
    if (existing) {
      existing.data.datasets = datasets; existing.options.scales = scales; existing.update('none');
      return { any: any, created: false };
    }
    var cfg = {
      type: isBar ? 'bar' : 'line', data: { datasets: datasets },
      options: {
        animation: false, parsing: isBar, normalized: !isBar, maintainAspectRatio: false, interaction: { mode: stacked ? 'index' : 'nearest', axis: 'x', intersect: false },
        plugins: {
          legend: { display: opts.legend !== false, labels: { color: LEG, filter: function (it, data) { return !data.datasets[it.datasetIndex]._band; } } },
          tooltip: {
            filter: function (it) { return !it.dataset._band; },
            callbacks: {
              title: function (items) { return items.length ? new Date(items[0].parsed.x).toLocaleString('de-DE', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', second: span <= 6 * 3600000 ? '2-digit' : undefined }) : ''; },
              footer: function (items) {                         // gestapelt: Summe je Achse/Einheit
                if (!stacked) return '';
                var sums = {};
                items.forEach(function (it) { var ds = it.dataset; if (ds._bin || it.raw == null || it.raw.y == null) return; sums[ds._unit] = (sums[ds._unit] || 0) + it.raw.y; });
                var keys = Object.keys(sums); return keys.length && items.length > 1 ? 'Summe: ' + keys.map(function (u) { return fmtNum(sums[u]) + ' ' + u; }).join(' / ') : '';
              },
              label: function (it) {
                var r = it.raw || {}, ds = it.dataset;
                if (ds._bin) return ds.label + ': ' + (r.y ? 'an' : 'aus');
                return ds.label.replace(/ \(.*\)$/, '') + ': ' + fmtNum(r.y) + ' ' + ds._unit + (ds._minmax ? '  (' + fmtNum(r.mn) + ' … ' + fmtNum(r.mx) + ')' : '');
              }
            }
          }
        },
        scales: scales
      },
      plugins: [{
        id: 'zoomBox', afterDraw: function (chart) {            // Auswahlrechteck beim Aufziehen (Zoom)
          var s = chart._sel; if (!s) return;
          var a = chart.chartArea, x = Math.min(s.x0, s.x1), w = Math.abs(s.x1 - s.x0), ctx = chart.ctx;
          ctx.save(); ctx.fillStyle = 'rgba(60,162,203,.18)'; ctx.strokeStyle = 'rgba(60,162,203,.9)';
          ctx.fillRect(x, a.top, w, a.bottom - a.top); ctx.strokeRect(x, a.top, w, a.bottom - a.top); ctx.restore();
        }
      }]
    };
    var ch = new Chart(cv.getContext('2d'), cfg);
    ch._vlKind = kind;
    inst[c.id] = ch;
    if (opts.onCreate) opts.onCreate(ch);
    return { any: any, created: true };
  }

  return { COLORS: COLORS, pointsFor: pointsFor, draw: draw, fmtTick: fmtTick, niceTicks: niceTicks, fmtNum: fmtNum };
})();
