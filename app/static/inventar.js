/* Geraeteuebersicht (Einstellungen -> System, nur Administratoren): Liste aller Geraete mit IP, kopieren / als CSV speichern. */
(function () {
  var $ = function (id) { return document.getElementById(id); };
  var card = $('inv-card');
  if (!card) return;
  var rows = [];
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function render() {
    var q = ($('inv-q').value || '').trim().toLowerCase();
    var shown = rows.filter(function (r) { return !q || (r.typ + ' ' + r.name + ' ' + r.ip + ' ' + r.mac + ' ' + r.detail).toLowerCase().indexOf(q) >= 0; });
    var dup = rows.filter(function (r) { return r.doppelt; }).length;
    $('inv-count').textContent = rows.length + ' Geräte' + (q ? ', ' + shown.length + ' angezeigt' : '') + (dup ? ' – ⚠ ' + dup + ' mit doppelter IP-Adresse' : '');
    $('inv-body').innerHTML = shown.length ? shown.map(function (r) {
      return '<tr' + (r.doppelt ? ' style="background:rgba(229,84,74,.12)"' : '') + '><td style="white-space:nowrap">' + esc(r.ip || '–') + (r.doppelt ? ' <span title="Diese IP-Adresse kommt mehrfach vor" style="color:#e5544a">⚠</span>' : '') + '</td><td>' + esc(r.name) + '</td><td>' + esc(r.typ) + '</td><td style="font-family:monospace;font-size:12px">' + esc(r.mac) + '</td><td class="muted">' + esc(r.detail) + '</td></tr>';
    }).join('') : '<tr><td colspan="5" class="muted">Nichts gefunden.</td></tr>';
  }
  async function load() {
    try {
      var r = await fetch('/api/inventory');
      if (!r.ok) throw new Error('HTTP ' + r.status);
      rows = (await r.json()).devices || [];
      $('inv-msg').textContent = '';
      render();
    } catch (e) { $('inv-msg').textContent = 'Liste konnte nicht geladen werden: ' + e.message; }
  }
  function text(sep) {
    return rows.map(function (r) { return [r.ip, r.name, r.typ, r.mac, r.detail].join(sep); }).join('\n');
  }
  $('inv-q').addEventListener('input', render);
  $('inv-reload').addEventListener('click', load);
  $('inv-copy').addEventListener('click', async function () {
    try { await navigator.clipboard.writeText(text('\t')); $('inv-msg').textContent = 'In die Zwischenablage kopiert ✓'; }
    catch (e) { $('inv-msg').textContent = 'Kopieren nicht möglich – bitte „Als CSV speichern“ benutzen.'; }
  });
  $('inv-csv').addEventListener('click', function () {
    var q = function (s) { return '"' + String(s == null ? '' : s).replace(/"/g, '""') + '"'; };
    var lines = ['IP;Name;Art;MAC;Hinweis'].concat(rows.map(function (r) { return [r.ip, r.name, r.typ, r.mac, r.detail].map(q).join(';'); }));
    var blob = new Blob(['\ufeff' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' });
    var a = document.createElement('a'); a.href = URL.createObjectURL(blob);
    a.download = 'BlueNexus-Geraete-' + new Date().toISOString().slice(0, 10) + '.csv';
    document.body.appendChild(a); a.click(); a.remove(); setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
  });
  load();
})();
