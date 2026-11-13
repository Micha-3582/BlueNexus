/* Einstellungen -> System (nur Administratoren): Meldungen der Content-Security-Policy im Meldemodus. Der Browser blockiert nichts, er meldet nur. */
(function () {
  var box = document.getElementById('csp-body');
  if (!box) return;
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function when(ts) { return ts ? new Date(ts * 1000).toLocaleString('de-DE') : '–'; }
  function render(j) {
    var pol = j.policies || {}, head = Object.keys(pol).map(function (k) {
      var p = pol[k], kinds = Object.keys(p.by_rule || {}).map(function (r) { return esc(r) + ': ' + p.by_rule[r]; }).join(', ');
      return '<div style="margin:4px 0"><b>' + esc(p.label) + '</b> · ' + p.reports + ' Meldungen an ' + p.places + ' Stellen' + (kinds ? ' <span class="muted">(' + kinds + ')</span>' : '') + '</div>';
    }).join('');
    var rows = (j.entries || []).map(function (e) {
      return '<tr style="border-top:1px solid var(--border)"><td style="padding:4px">' + esc(pol[e.p] ? pol[e.p].label : e.p) + '</td><td style="padding:4px">' + esc(e.rule) + '</td><td style="padding:4px;word-break:break-all">' + esc(e.blocked) + '</td>'
        + '<td style="padding:4px">' + esc(e.page) + '</td><td style="padding:4px;word-break:break-all">' + esc(e.src) + (e.line ? ':' + e.line : '') + '</td><td style="padding:4px;text-align:right">' + e.n + '</td>'
        + '<td style="padding:4px;word-break:break-all" class="muted">' + esc(e.sample) + '</td></tr>';
    }).join('');
    box.innerHTML = head + (rows
      ? '<div class="table-scroll" style="margin-top:8px"><table style="width:100%;border-collapse:collapse;font-size:13px"><thead><tr class="muted" style="text-align:left"><th style="padding:4px">Regel</th><th style="padding:4px">Verletzt</th><th style="padding:4px">Blockiert</th><th style="padding:4px">Seite</th><th style="padding:4px">Quelle</th><th style="padding:4px;text-align:right">Anzahl</th><th style="padding:4px">Beispiel</th></tr></thead><tbody>' + rows + '</tbody></table></div>'
      : '<div class="muted" style="margin-top:6px">Noch keine Meldungen. Seiten öffnen, dann hier aktualisieren.</div>')
      + '<div class="muted" style="margin-top:6px">Gesammelt seit ' + esc(when(j.since)) + '.</div>';
  }
  function load() {
    fetch('/api/csp-reports', { cache: 'no-store' }).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); }).then(render)
      .catch(function () { box.textContent = 'Die Meldungen konnten nicht geladen werden.'; });
  }
  document.getElementById('csp-refresh').addEventListener('click', load);
  document.getElementById('csp-clear').addEventListener('click', function () {
    uiDialog({ title: 'Meldungen zurücksetzen?', message: 'Alle gesammelten Meldungen werden gelöscht.', okText: 'Zurücksetzen' }).then(function (ok) {
      if (ok) fetch('/api/csp-reports', { method: 'DELETE' }).then(load);
    });
  });
  load();
})();
