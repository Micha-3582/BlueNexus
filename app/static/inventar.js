/* Geraeteuebersicht (Einstellungen -> System, nur Administratoren): oeffnet auf Knopfdruck ein eigenes Fenster mit allen Geraeten samt IP.
   Spalten per Klick sortierbar, Suche, Kopieren, CSV. */
(function () {
  var open = document.getElementById('inv-open');
  if (!open) return;
  var COLS = [['ip', 'IP-Adresse'], ['name', 'Name'], ['typ', 'Art'], ['mac', 'MAC'], ['detail', 'Hinweis']];
  var rows = [], sort = { k: 'ip', dir: 1 }, ov = null;
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function ipNum(s) { var m = /^(\d+)\.(\d+)\.(\d+)\.(\d+)$/.exec(s || ''); return m ? ((+m[1] * 256 + +m[2]) * 256 + +m[3]) * 256 + +m[4] : null; }
  function cmp(a, b) {
    var k = sort.k, x = a[k] || '', y = b[k] || '';
    if (k === 'ip') {                                         // Zahlenreihenfolge; Eintraege ohne IP immer ans Ende
      var nx = ipNum(x), ny = ipNum(y);
      if (nx == null && ny == null) return a.name.localeCompare(b.name, 'de');
      if (nx == null) return 1;
      if (ny == null) return -1;
      return (nx - ny) * sort.dir;
    }
    if (!x && y) return 1;                                    // leere Felder ans Ende
    if (x && !y) return -1;
    return x.localeCompare(y, 'de', { numeric: true, sensitivity: 'base' }) * sort.dir;
  }
  function view() {
    var q = (ov.querySelector('.inv-q').value || '').trim().toLowerCase();
    return rows.filter(function (r) { return !q || (r.typ + ' ' + r.name + ' ' + r.ip + ' ' + r.mac + ' ' + r.detail).toLowerCase().indexOf(q) >= 0; }).sort(cmp);
  }
  function render() {
    var list = view(), dup = rows.filter(function (r) { return r.doppelt; }).length;
    ov.querySelector('.inv-count').textContent = rows.length + ' Geräte' + (list.length !== rows.length ? ', ' + list.length + ' angezeigt' : '') + (dup ? ' – ⚠ ' + dup + ' mit doppelter IP-Adresse' : '');
    ov.querySelector('thead tr').innerHTML = COLS.map(function (c) {
      var on = sort.k === c[0];
      return '<th data-k="' + c[0] + '" role="button" tabindex="0" aria-sort="' + (on ? (sort.dir > 0 ? 'ascending' : 'descending') : 'none') + '" title="Nach „' + c[1] + '“ sortieren" style="cursor:pointer;user-select:none;white-space:nowrap;text-align:left;padding:6px 8px;position:sticky;top:0;background:var(--card);border-bottom:1px solid var(--border)">' + c[1] + ' <span style="opacity:' + (on ? 1 : 0.3) + '">' + (on ? (sort.dir > 0 ? '▲' : '▼') : '↕') + '</span></th>';
    }).join('');
    ov.querySelector('tbody').innerHTML = list.length ? list.map(function (r) {
      return '<tr style="border-bottom:1px solid var(--border)' + (r.doppelt ? ';background:rgba(229,84,74,.12)' : '') + '"><td style="white-space:nowrap;padding:6px 8px">' + esc(r.ip || '–') + (r.doppelt ? ' <span title="Diese IP-Adresse kommt mehrfach vor" style="color:#e5544a">⚠</span>' : '') + '</td><td style="padding:6px 8px">' + esc(r.name) + '</td><td style="padding:6px 8px">' + esc(r.typ) + '</td><td style="font-family:monospace;font-size:12px;padding:6px 8px;white-space:nowrap">' + esc(r.mac) + '</td><td class="muted" style="padding:6px 8px">' + esc(r.detail) + '</td></tr>';
    }).join('') : '<tr><td colspan="5" class="muted" style="padding:10px 8px">Nichts gefunden.</td></tr>';
  }
  function setSort(k) { sort = sort.k === k ? { k: k, dir: -sort.dir } : { k: k, dir: 1 }; render(); }
  var lock = null;
  function lockPage() {                                       // Seite hinter dem Fenster festhalten (sonst scrollt sie mit, sobald die Liste am Anfang/Ende ist)
    var de = document.documentElement, b = document.body, gap = window.innerWidth - de.clientWidth;
    lock = { de: de.style.overflow, b: b.style.overflow, pr: b.style.paddingRight };
    de.style.overflow = 'hidden';
    b.style.overflow = 'hidden';
    if (gap > 0) b.style.paddingRight = gap + 'px';           // kein Springen durch die verschwindende Bildlaufleiste
  }
  function unlockPage() {
    if (!lock) return;
    document.documentElement.style.overflow = lock.de;
    document.body.style.overflow = lock.b;
    document.body.style.paddingRight = lock.pr;
    lock = null;
  }
  function close() { if (!ov) return; document.removeEventListener('keydown', onKey, true); ov.remove(); ov = null; unlockPage(); }
  function onKey(e) { if (e.key === 'Escape') { e.stopPropagation(); close(); } }
  function text(sep) { return view().map(function (r) { return [r.ip, r.name, r.typ, r.mac, r.detail].join(sep); }).join('\n'); }
  async function load() {
    var msg = ov.querySelector('.inv-msg');
    try {
      var r = await fetch('/api/inventory');
      if (!r.ok) throw new Error('HTTP ' + r.status);
      rows = (await r.json()).devices || [];
      msg.textContent = '';
      render();
    } catch (e) { msg.textContent = 'Liste konnte nicht geladen werden: ' + e.message; }
  }
  function show() {
    if (ov) return;
    ov = document.createElement('div');
    ov.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.7);display:flex;align-items:center;justify-content:center;z-index:1500;padding:16px;overscroll-behavior:contain';
    ov.innerHTML = '<div role="dialog" aria-modal="true" aria-label="Geräteübersicht" style="background:var(--card);border:1px solid var(--border);border-radius:16px;padding:16px 18px;width:100%;max-width:1100px;max-height:92vh;display:flex;flex-direction:column;box-shadow:0 12px 40px rgba(0,0,0,.5)">'
      + '<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px"><h3 style="margin:0;font-size:18px;flex:1">Geräteübersicht (IP-Adressen)</h3><button type="button" class="ghost inv-x" aria-label="Schließen" title="Schließen">✕</button></div>'
      + '<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:8px"><input class="inv-q" type="search" placeholder="Suchen (IP, Name, Art …)" style="flex:1;min-width:180px"><button type="button" class="ghost inv-reload">Aktualisieren</button><button type="button" class="ghost inv-copy">Kopieren</button><button type="button" class="ghost inv-csv">Als CSV speichern</button></div>'
      + '<div class="muted inv-count" style="margin-bottom:6px"></div>'
      + '<div style="overflow:auto;overscroll-behavior:contain;flex:1;min-height:120px"><table style="width:100%;border-collapse:collapse"><thead><tr></tr></thead><tbody></tbody></table></div>'
      + '<div class="muted inv-msg" style="margin-top:6px"></div></div>';
    document.body.appendChild(ov);
    lockPage();
    document.addEventListener('keydown', onKey, true);
    ov.addEventListener('mousedown', function (e) { if (e.target === ov) close(); });
    ov.querySelector('.inv-x').addEventListener('click', close);
    ov.querySelector('.inv-q').addEventListener('input', render);
    ov.querySelector('.inv-reload').addEventListener('click', load);
    ov.querySelector('thead').addEventListener('click', function (e) { var th = e.target.closest('th[data-k]'); if (th) setSort(th.dataset.k); });
    ov.querySelector('thead').addEventListener('keydown', function (e) { var th = e.target.closest('th[data-k]'); if (th && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); setSort(th.dataset.k); } });
    ov.querySelector('.inv-copy').addEventListener('click', async function () {
      var msg = ov.querySelector('.inv-msg');
      try { await navigator.clipboard.writeText(text('\t')); msg.textContent = 'In die Zwischenablage kopiert ✓'; }
      catch (e) { msg.textContent = 'Kopieren nicht möglich – bitte „Als CSV speichern“ benutzen.'; }
    });
    ov.querySelector('.inv-csv').addEventListener('click', function () {
      var q = function (s) { return '"' + String(s == null ? '' : s).replace(/"/g, '""') + '"'; };
      var lines = ['IP;Name;Art;MAC;Hinweis'].concat(view().map(function (r) { return [r.ip, r.name, r.typ, r.mac, r.detail].map(q).join(';'); }));
      var blob = new Blob(['﻿' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' });
      var a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'BlueNexus-Geraete-' + new Date().toISOString().slice(0, 10) + '.csv';
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
    });
    render();
    load();
    ov.querySelector('.inv-q').focus();
  }
  open.addEventListener('click', show);
})();
