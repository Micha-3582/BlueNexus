/* Funkthermometer (ESP32-C3): Chip vorbereiten (Firmware per Web Serial aufspielen, esptool-js lokal ausgeliefert), Liste, Kopplungscode, Funk-Update.
   Ablauf "ESP vorbereiten": Chip loeschen, ein Image bei 0x0 schreiben, fertig - ohne WLAN, ohne Schluessel. Eingerichtet wird das Thermometer am Einsatzort
   per Handy (Einrichtungs-WLAN BlueNexus-Thermo-XXXX) mit dem Kopplungscode, den BlueNexus unter "Neues Thermometer einrichten" erzeugt. */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var card = $('thermo-card'); if (!card) return;
  var esc = function (t) { return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); };
  var state = { fw: null, server: '', secure: false, devices: [], busy: false };
  var USB_FILTER = [{ usbVendorId: 0x303A, usbProductId: 0x1001 }];       // ESP32-C3: "USB JTAG/serial debug unit"

  function msg(t, err) { var m = $('th-msg'); m.textContent = t || ''; m.style.color = err ? '#e5544a' : ''; }
  function api(url, method, body) {
    return fetch(url, { method: method || 'GET', headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) { if (!r.ok) throw new Error(j.error || ('Fehler ' + r.status)); return j; });
    });
  }
  function ago(s) {
    if (s == null) return 'noch keine Meldung';
    if (s < 90) return 'vor ' + s + ' s';
    if (s < 5400) return 'vor ' + Math.round(s / 60) + ' min';
    return s < 172800 ? 'vor ' + Math.round(s / 3600) + ' h' : 'vor ' + Math.round(s / 86400) + ' Tagen';
  }
  var dec = function (v, d) { return v == null ? '–' : Number(v).toFixed(d == null ? 1 : d).replace('.', ','); };

  /* ---------------- Liste ---------------- */
  /* Symbolknoepfe der Geraeteliste: quadratisch (.tgl, wie im Smart-Home-Bereich), Beschreibung als Hover-/Lesetext */
  function ti(p) { return '<svg viewBox="0 0 24 24" aria-hidden="true">' + p + '</svg>'; }
  var TI = {
    tag: ti('<path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/>'),
    bolt: ti('<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>'),
    key: ti('<circle cx="7.5" cy="15.5" r="4.5"/><path d="M10.7 12.3L21 2"/><path d="M16 7l3 3"/><path d="M18.5 4.5l2 2"/>'),
    clock: ti('<circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15 14"/>'),
    sliders: ti('<line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/>'),
    pen: ti('<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>'),
    down: ti('<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>'),
    trash: ti('<polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>')
  };
  function tbtn(act, id, title, icon, del) {
    return '<button type="button" class="tgl' + (del ? ' del' : '') + '" data-act="' + act + '" data-id="' + esc(id) + '" title="' + esc(title) + '" aria-label="' + esc(title) + '">' + icon + '</button>';
  }
  /* Neuen Kopplungscode erzeugen (Geraet ohne gespeicherten Code): ID, Sensoren, Verlaeufe, Regeln bleiben; der alte Schluessel gilt, bis sich das Geraet mit dem neuen meldet */
  function newCode(d) {
    var net = !!d.standalone, def = net ? ((function () { try { return localStorage.getItem('thSaServer') || ''; } catch (e) { return ''; } })() || (location.protocol === 'https:' ? location.origin : '')) : state.server;
    uiForm({ title: 'Neuen Kopplungscode erzeugen: ' + (d.name || d.id), okText: 'Erzeugen',
      message: 'Das Thermometer behält ID, Sensoren, Verläufe und Regeln. Es muss danach neu eingerichtet werden (Kopplungscode am Einsatzort im Einrichtungsfenster eingeben, bei einem Gerät mit alter Firmware erst „ESP vorbereiten“). Bis es sich mit dem neuen Schlüssel meldet, gilt der alte weiter.',
      fields: [{ id: 'server', label: net ? 'Internet-Adresse von BlueNexus (https://…)' : 'Adresse von BlueNexus im Heimnetz (http://…)', type: 'text', value: def }] }).then(function (r) {
      if (!r) return;
      api('/api/thermo/' + encodeURIComponent(d.id) + '/code', 'POST', { new: true, server: r.server }).then(function (j) {
        try { navigator.clipboard.writeText(j.code); } catch (e) { /* Feld bleibt zum Kopieren */ }
        showCode(d, j.code); return load();
      }).catch(function (e) { msg(e.message, true); });
    });
  }
  /* Kopplungscode anzeigen: Feld zum Markieren + Kopieren-Knopf (ein Klick legt den langen Code in die Zwischenablage) */
  function showCode(d, code) {
    var ov = document.createElement('div');
    ov.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.65);display:flex;align-items:center;justify-content:center;z-index:1000;padding:16px';
    ov.innerHTML = '<div role="dialog" aria-modal="true" style="background:var(--card);border:1px solid var(--border);border-radius:14px;padding:20px;width:100%;max-width:460px;box-shadow:0 12px 40px rgba(0,0,0,.5)">'
      + '<h3 style="margin:0 0 10px;font-size:17px">Kopplungscode: ' + esc(d.name || d.id) + '</h3>'
      + '<div class="muted" style="margin-bottom:12px">Gilt nur für dieses Gerät. Im Einrichtungsfenster des Thermometers einfügen.</div>'
      + '<textarea readonly rows="4" style="width:100%;font-family:monospace;font-size:13px;resize:none" onclick="this.select()">' + esc(code) + '</textarea>'
      + '<div style="display:flex;gap:10px;justify-content:flex-end;margin-top:14px"><button type="button" class="ghost dlg-no">Schließen</button><button type="button" class="dlg-copy">Kopieren</button></div></div>';
    var close = function () { document.removeEventListener('keydown', onKey); ov.remove(); };
    var onKey = function (e) { if (e.key === 'Escape') close(); };
    ov.querySelector('.dlg-no').onclick = close;
    ov.querySelector('.dlg-copy').onclick = function () {
      var ta = ov.querySelector('textarea'); ta.select();
      var done = function () { savedToast('Kopiert ✓'); };
      try { navigator.clipboard.writeText(code).then(done, function () { document.execCommand('copy'); done(); }); } catch (e) { document.execCommand('copy'); done(); }
    };
    ov.addEventListener('mousedown', function (e) { if (e.target === ov) close(); });
    document.addEventListener('keydown', onKey); document.body.appendChild(ov);
    ov.querySelector('.dlg-copy').focus();
  }
  function renderList() {
    var el = $('th-list');
    if (!state.devices.length) { el.innerHTML = '<div class="muted">Noch kein Thermometer eingerichtet.</div>'; return; }
    var etk = typeof etikettState === 'function' ? etikettState() : { kind: 'other', text: '' };
    el.innerHTML = state.devices.map(function (d) {
      var l = d.last || {}, bat = l.bat, bstate = bat == null || bat < 1 ? '' : (bat > 3.1 ? 'ok' : (bat < 3.0 ? 'low' : 'warn'));
      var batTxt = bstate === '' ? '' : ' · Batterie ' + dec(bat, 2) + ' V' + (bstate === 'low' ? ' – bald wechseln' : '');
      return '<div data-row="' + esc(d.id) + '" style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;border:1px solid var(--border);border-radius:12px;padding:10px 12px">'
        + '<span title="' + (d.online ? 'meldet sich' : 'meldet sich nicht') + '" style="width:10px;height:10px;border-radius:50%;background:' + (d.online ? '#35c07a' : (d.last_seen == null ? '#9aa4b5' : '#e5544a')) + '"></span>'
        + '<div style="flex:1;min-width:180px"><b>' + esc(d.name) + '</b> <span class="muted">· ' + esc(d.id) + (d.location ? ' · 📍 ' + esc(d.location) : '') + (d.standalone ? ' · ohne USB' : d.paired ? ' · per Code' : '') + (d.fw ? ' · Firmware ' + esc(d.fw) : '') + fwTxt(d) + '</span>'
        + '<div class="muted" style="font-size:13px">' + (d.last_seen == null ? (d.attempt ? '<span style="color:#e5544a">Anfrage angekommen, aber abgelehnt: ' + esc(d.attempt.why) + ' (vor ' + d.attempt.age_s + ' s, von ' + esc(d.attempt.ip) + ')</span>' : 'wartet auf die erste Meldung') : dec(l.temp) + ' °C · ' + dec(l.hum, 0) + ' % · ' + ago(d.age_s) + batTxt + (l.rssi != null ? ' · Empfang ' + dec(l.rssi, 0) + ' dBm' : '')) + ' · alle ' + d.interval + ' min' + metaTxt(d) + calTxt(d) + '</div></div>'
        + '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-left:auto">'
        + tbtn('label', d.id, 'Etikett drucken: Name, ID und QR-Code für das Gehäuse (Niimbot-Drucker, nur am Android-Handy)', TI.tag)
        + (d.update ? tbtn('update', d.id, d.ota_pending ? 'Firmware-Update ist vorgemerkt – das Thermometer lädt es bei seiner nächsten Meldung (erneut anstoßen: klicken)' : 'Firmware auf ' + (state.fw ? state.fw.version : 'die neueste Version') + ' aktualisieren (per Funk, bei der nächsten Meldung)', TI.down) : '')
        + (d.has_code ? tbtn('code', d.id, 'Kopplungscode wieder ansehen', TI.key) : tbtn('newcode', d.id, 'Neuen Kopplungscode erzeugen (z. B. für ein Thermometer mit älterer Firmware, das neu eingerichtet werden soll – ID, Sensoren und Verläufe bleiben erhalten)', TI.key))
        + tbtn('interval', d.id, 'Messintervall ändern (zum Testen oder Abgleichen kurz stellen)', TI.clock)
        + tbtn('calib', d.id, 'Auf Referenzwerte abgleichen (kalibrieren)', TI.sliders)
        + tbtn('rename', d.id, 'Umbenennen', TI.pen)
        + tbtn('del', d.id, 'Entfernen', TI.trash, true) + '</div></div>';
    }).join('');
  }
  function fwTxt(d) {                                     // Hinweis zur Firmware: Update verfuegbar / vorgemerkt / gescheitert / zu alt fuer Funk-Update
    if (d.ota_failed) return ' · <span style="color:#e5544a">Funk-Update auf ' + esc(d.ota_failed) + ' fehlgeschlagen</span>';
    if (d.ota_pending) return ' · <span style="color:#f0a63c">Update vorgemerkt</span>';
    if (d.update) return ' · <span style="color:#f0a63c">Update ' + esc(state.fw ? state.fw.version : '') + ' verfügbar</span>';
    if (d.fw && parseInt(d.fw, 10) < 2) return ' · <span class="muted">alte Firmware – einmal per USB auf ' + esc(state.fw ? state.fw.version : '2.0.0') + ' umflashen</span>';
    return '';
  }
  var RR = { 1: 'Einschalten', 2: 'RESET-Taste', 3: 'Software-Neustart', 4: 'Absturz', 5: 'Watchdog', 6: 'Watchdog', 7: 'Watchdog', 8: 'Zeitgeber', 9: 'Batterie schwach (Brownout)', 11: 'USB', 12: 'JTAG' };
  function metaTxt(d) {                                   // ab Firmware 1.1: Aufwachen Nr. und Grund des letzten Starts
    var m = d.meta || {};
    return (m.n != null ? ' · Aufwachen Nr. ' + m.n + (m.rr != null && RR[m.rr] ? ' (' + RR[m.rr] + ')' : '') : '') + (m.ap ? ' · AP ' + m.ap : '');
  }
  function calTxt(d) {
    var c = d.calib || {}, p = [];
    if (c.temp != null) p.push((c.temp > 0 ? '+' : '') + dec(c.temp, 2) + ' °C');
    if (c.hum != null) p.push((c.hum > 0 ? '+' : '') + dec(c.hum, 1) + ' %');
    return p.length ? ' · Abgleich ' + p.join(' / ') : '';
  }
  var focused = false;
  function focusFromLink() {                                  // QR-Code vom Etikett: /admin?thermo=<ID>#system -> Zeile hervorheben
    if (focused) return;
    var id = new URLSearchParams(location.search).get('thermo'); if (!id) return;
    focused = true;
    var row = card.querySelector('[data-row="' + id.replace(/[^a-z0-9-]/gi, '') + '"]');
    card.scrollIntoView({ block: 'start' });
    if (row) { row.style.outline = '2px solid #f0a63c'; row.scrollIntoView({ block: 'center' }); setTimeout(function () { row.style.outline = ''; }, 5000); }
    else msg('Dieses Thermometer gibt es nicht (mehr).', true);
  }
  function load() {
    return api('/api/thermo').then(function (j) {
      state.devices = j.devices || []; state.fw = j.firmware || null; state.server = j.server || ''; state.secure = !!j.secure;
      if ($('th-fwver')) $('th-fwver').textContent = state.fw ? state.fw.version : '';
      renderList(); checkEnv(); labelHint(); focusFromLink();
    }).catch(function (e) { msg(e.message, true); });
  }

  /* ---------------- Voraussetzungen ---------------- */
  function envProblem() {
    if (!navigator.serial) return 'Zum Flashen braucht der Browser „Web Serial“: bitte Chrome oder Edge am PC benutzen (nicht Firefox, Safari oder Handy).';
    if (!window.isSecureContext) return 'Flashen im Browser geht nur über eine gesicherte Adresse (https oder localhost). Öffne BlueNexus über die https-Adresse  Ein Thermometer ohne USB einzurichten geht auch ohne Flashen (Kopplungscode).';
    if (!state.fw) return 'Die Firmware-Datei fehlt in dieser Installation (static/firmware/thermo).';
    return '';
  }
  function checkEnv() {
    var p = envProblem(), w = $('th-warn');
    w.style.display = p ? '' : 'none'; w.textContent = p;
    $('th-flash').disabled = !!p || state.busy; $('th-reset').disabled = !(navigator.serial && window.isSecureContext) || state.busy;
  }

  /* ---------------- Fortschritt ---------------- */
  var STEPS = ['Mit dem Chip verbinden', 'Chip löschen', 'Firmware schreiben', 'Fertig'];
  var stepState = [];
  function steps(i, st, extra) {
    stepState[i] = { st: st, extra: extra || '' };
    $('th-steps').innerHTML = STEPS.map(function (s, k) {
      var x = stepState[k]; if (!x) return '<div class="muted" style="padding:2px 0">○ ' + esc(s) + '</div>';
      var icon = x.st === 'ok' ? '<span style="color:#35c07a">✓</span>' : x.st === 'err' ? '<span style="color:#e5544a">✗</span>' : '<span class="muted">…</span>';
      return '<div style="padding:2px 0' + (x.st === 'run' ? ';font-weight:600' : '') + '">' + icon + ' ' + esc(s) + (x.extra ? ' <span class="muted">' + esc(x.extra) + '</span>' : '') + '</div>';
    }).join('');
  }
  function resetSteps() { stepState = []; $('th-steps').innerHTML = ''; }

  /* ---------------- Flashen ---------------- */
  function loadLib() { return import('/static/esptool/bundle.js'); }
  function sha256hex(buf) { return crypto.subtle.digest('SHA-256', buf).then(function (h) { return Array.prototype.map.call(new Uint8Array(h), function (b) { return ('0' + b.toString(16)).slice(-2); }).join(''); }); }
  function openChip(lib, log) {
    return navigator.serial.requestPort({ filters: USB_FILTER }).then(function (port) {
      var transport = new lib.Transport(port, true);
      var term = { clean: function () {}, writeLine: log, write: log };
      var loader = new lib.ESPLoader({ transport: transport, baudrate: 115200, terminal: term, debugLogging: false });
      return loader.main().then(function (chip) { return { loader: loader, transport: transport, chip: chip }; }).catch(function (e) {
        return transport.disconnect().catch(function () {}).then(function () { throw e; });
      });
    });
  }
  function friendly(e) {
    var t = (e && e.message) || String(e);
    if (e && e.name === 'NotFoundError') return 'Kein Chip ausgewählt. Beim Anstecken muss ein Eintrag „USB JTAG/serial debug unit“ erscheinen – bei einem schon eingerichteten Thermometer erst den Download-Modus aktivieren (BOOT-Taste halten, USB-C anstecken oder RESET drücken, BOOT loslassen).';
    if (/Failed to connect|No serial data|timeout/i.test(t)) return 'Keine Verbindung zum Chip. Download-Modus aktivieren: BOOT-Taste halten, USB-C anstecken (oder RESET drücken), BOOT loslassen – dann erneut versuchen. Das Kabel muss Daten übertragen (nicht nur laden).';
    if (/busy|already open|InvalidStateError/i.test(t)) return 'Der Anschluss ist belegt (anderes Programm oder Browser-Fenster nutzt ihn). Bitte schließen und erneut versuchen.';
    return t;
  }
  function setBusy(b) { state.busy = b; $('th-flash').disabled = b; $('th-reset').disabled = b; checkEnv(); }

  function flash() {
    if (!state.fw) { msg('Die Firmware-Datei fehlt in dieser Installation.', true); return; }
    uiDialog({ title: 'ESP vorbereiten', okText: 'Weiter',
      html: '<div style="text-align:left;line-height:1.5">Der angesteckte Chip wird <b>gelöscht</b> und bekommt die Firmware <b>' + esc(state.fw.version) + '</b>. Ein schlafender Chip ist am PC nicht zu sehen – bitte so vorbereiten:<ol style="margin:8px 0 0 18px;padding:0"><li>USB-C-Kabel an den PC anstecken.</li><li>Neuer Chip: er meldet sich von selbst. Ein schon eingerichteter: <b>BOOT-Taste halten</b>, USB-C anstecken (oder RESET drücken), BOOT loslassen.</li><li>Auf „Weiter“ klicken und „USB JTAG/serial debug unit“ wählen.</li></ol></div>' }).then(function (ok) { if (ok) doFlash(); });
  }
  function doFlash() {
    var lib = null, session = null, logLines = [];
    msg(''); resetSteps(); setBusy(true);
    var log = function (s) { logLines.push(String(s)); if (logLines.length > 40) logLines.shift(); };
    steps(0, 'run');
    Promise.all([loadLib(), fetch(state.fw.url).then(function (r) { if (!r.ok) throw new Error('Firmware nicht ladbar'); return r.arrayBuffer(); })]).then(function (r) {
      return sha256hex(r[1]).then(function (h) {
        if (state.fw.sha256 && h !== state.fw.sha256) throw new Error('Die Firmware-Datei ist beschädigt (Prüfsumme stimmt nicht).');
        lib = r[0]; return openChip(lib, log).then(function (s) { session = s; return new Uint8Array(r[1]); });
      });
    }).then(function (fw) {
      steps(0, 'ok', session.chip); steps(1, 'run');
      return session.loader.eraseFlash().then(function () {
        steps(1, 'ok'); steps(2, 'run');
        return session.loader.writeFlash({
          fileArray: [{ data: fw, address: state.fw.offset || 0 }],
          flashSize: 'keep', flashMode: 'keep', flashFreq: 'keep', eraseAll: false, compress: true,
          reportProgress: function (i, w, t) { steps(2, 'run', Math.round(w / t * 100) + ' %'); }
        });
      });
    }).then(function () {
      steps(2, 'ok'); steps(3, 'ok', 'Firmware ' + state.fw.version + ' ist drauf');
      return session.transport.disconnect().catch(function () {});               /* ein automatischer Neustart wirkt bei diesem Board nicht - die RESET-Taste startet es */
    }).then(function () {
      msg('Fertig. Der Chip ist vorbereitet. Beim ersten Start (RESET drücken oder Strom anschließen) öffnet er das WLAN „BlueNexus-Thermo-XXXX“ – dort wird er am Einsatzort per Handy mit dem Kopplungscode eingerichtet (Anleitung unten). Den nächsten Chip einfach anstecken und noch einmal „ESP vorbereiten“ drücken.');
      setBusy(false);
    }).catch(function (e) {
      var k = stepState.map(function (x) { return x && x.st; }).lastIndexOf('run'); if (k >= 0) steps(k, 'err');
      (session ? session.transport.disconnect().catch(function () {}) : Promise.resolve()).then(function () { msg(friendly(e), true); setBusy(false); });
    });
  }

  /* ---------------- ESP32 loeschen ---------------- */
  function resetChip() {
    var err = !navigator.serial ? 'Zum Löschen braucht der Browser „Web Serial“ (Chrome oder Edge am PC).' : (!window.isSecureContext ? 'Das geht nur über https oder localhost.' : '');
    if (err) { msg(err, true); return; }
    uiDialog({ title: 'ESP32 löschen', okText: 'Weiter',
      html: '<div style="text-align:left;line-height:1.5">Der Chip wird <b>komplett gelöscht</b> (Auslieferungszustand). Ein schlafender Chip ist am PC nicht zu sehen – bitte so vorbereiten:<ol style="margin:8px 0 0 18px;padding:0"><li>USB-C-Kabel an den PC anstecken.</li><li><b>BOOT-Taste halten</b>, dann USB-C anstecken (oder RESET drücken), danach BOOT loslassen.</li><li>Auf „Weiter“ klicken und den Eintrag „USB JTAG/serial debug unit“ wählen.</li></ol></div>' }).then(function (ok) {
      if (!ok) return;
      resetSteps(); msg(''); setBusy(true);
      var session = null, log = function () {};
      loadLib().then(function (lib) { return openChip(lib, log); }).then(function (s) { session = s; steps(1, 'ok', s.chip); steps(2, 'run'); return s.loader.eraseFlash(); }).then(function () {
        steps(2, 'ok'); return session.transport.disconnect().catch(function () {});
      }).then(function () {
        msg('ESP32 gelöscht (Auslieferungszustand). Mit „ESP vorbereiten“ bekommt er wieder die Firmware. Ein dazugehöriges Thermometer in der Liste kannst du mit dem Mülleimer entfernen.'); setBusy(false);
      }).catch(function (e) {
        var k = stepState.map(function (x) { return x && x.st; }).lastIndexOf('run'); if (k >= 0) steps(k, 'err');
        (session ? session.transport.disconnect().catch(function () {}) : Promise.resolve()).then(function () { msg(friendly(e), true); setBusy(false); });
      });
    });
  }

  /* ---------------- Etikett fuers Gehaeuse (Niimbot, Code in /static/etikett/) ---------------- */
  function printLabel(d) {
    var es = etikettState();
    if (!es.ok) { uiAlert(es.kind === 'other' ? 'Etiketten drucken geht am Android-Handy (Chrome, über https): Öffne BlueNexus dort und drücke bei dem Thermometer „Etikett“.' : es.text, 'Drucken hier nicht möglich'); return; }
    etikettLoad().then(function () {
      var base = (typeof nfcBase === 'function' ? nfcBase() : location.origin).replace(/\/$/, '');
      EtikettDruck.open({ title: '🏷 Thermometer-Etikett drucken', intro: 'Name, ID und QR-Code für „' + d.name + '“ – zum Aufkleben auf das Gehäuse. Der QR-Code öffnet dieses Thermometer in BlueNexus (nur für Administratoren).',
        name: d.name, sub: d.id, url: base + '/admin?thermo=' + encodeURIComponent(d.id) + '#system' });
    }).catch(function (e) { uiAlert('Das Druckfenster konnte nicht geladen werden (' + e.message + '). Bitte die Seite neu laden.', 'Drucken nicht möglich'); });
  }
  function labelHint() {
    var el = $('th-etk-hint'); if (!el) return;
    var es = typeof etikettState === 'function' ? etikettState() : null;
    el.textContent = state.devices.length && es ? (es.ok ? '🏷 Etikett mit Namen, ID und QR-Code für das Gehäuse: „Etikett“ am Thermometer (Niimbot-Drucker, per Bluetooth).' : 'ℹ Etiketten für das Gehäuse drucken geht am Android-Handy (Chrome, https): BlueNexus dort öffnen und „Etikett“ am Thermometer drücken.') : '';
  }

  /* ---------------- Messintervall ---------------- */
  function setInterval_(d) {
    var opts = [[1, '1 Minute (nur zum Testen)'], [2, '2 Minuten'], [5, '5 Minuten'], [10, '10 Minuten'], [15, '15 Minuten (Standard)'], [30, '30 Minuten'], [60, '60 Minuten']];
    if (!opts.some(function (o) { return o[0] === d.interval; })) opts.push([d.interval, d.interval + ' Minuten (aktuell)']);
    uiForm({ title: 'Messintervall: ' + d.name, okText: 'Speichern',
      message: 'Wie oft das Thermometer misst und sendet. Kurze Intervalle kosten viel Batterie – 1 bis 5 Minuten nur zum Testen oder Abgleichen, danach wieder auf 15 Minuten. Das Thermometer übernimmt den neuen Wert bei seiner nächsten Meldung (nach einem Druck auf RESET sofort).',
      fields: [{ id: 'iv', label: 'Messung alle', type: 'select', value: String(d.interval), options: opts.map(function (o) { return [String(o[0]), o[1]]; }) }] }).then(function (r) {
      if (!r) return;
      api('/api/thermo/' + encodeURIComponent(d.id), 'PATCH', { interval: parseInt(r.iv, 10) }).then(function () { savedToast('Gespeichert ✓'); return load(); }).catch(function (e) { msg(e.message, true); });
    });
  }

  /* ---------------- Abgleich (Kalibrieren) ---------------- */
  function calibrate(d) {
    var raw = d.raw || {}, age = d.age_s;
    var intro = 'Lege das Thermometer neben dein Referenzgerät und warte, bis beide sich angeglichen haben (etwa 15 Minuten, nicht anfassen). Drücke dann die RESET-Taste am Thermometer: Es misst sofort neu und meldet sich nach 1 bis 20 Sekunden. Danach hier die Referenzwerte eintragen – BlueNexus rechnet den Korrekturwert aus und wendet ihn auf alle Messungen an (auch in Regeln und Diagrammen; ältere Verlaufswerte bleiben unverändert).';
    var cur = 'Letzte Messung' + (age == null ? '' : ' (vor ' + (age < 90 ? age + ' s' : Math.round(age / 60) + ' min') + ')') + ': ' + dec(raw.temp, 2) + ' °C, ' + dec(raw.hum, 1) + ' % (unkorrigiert).' + calTxt(d).replace(' · ', ' Aktuell:');
    uiForm({ title: 'Thermometer abgleichen: ' + d.name, message: intro + '  ' + cur, okText: 'Abgleichen', fields: [
      { id: 'ref_temp', label: 'Referenz-Temperatur (°C)', type: 'text', value: '' },
      { id: 'ref_hum', label: 'Referenz-Luftfeuchte (%)', type: 'text', value: '' },
      { id: 'reset', label: 'Abgleich löschen (Rohwerte verwenden)', type: 'checkbox', value: false }] }).then(function (r) {
      if (!r) return;
      var body = r.reset ? { reset: true } : { ref_temp: r.ref_temp, ref_hum: r.ref_hum };
      api('/api/thermo/' + encodeURIComponent(d.id) + '/calibrate', 'POST', body).then(function (j) {
        savedToast(r.reset ? 'Abgleich gelöscht ✓' : 'Abgeglichen ✓'); return load();
      }).catch(function (e) { uiDialog({ title: 'Abgleich nicht möglich', info: true, okText: 'OK', message: e.message }); });
    });
  }

  /* ---------------- Liste: Umbenennen, Entfernen ---------------- */
  $('th-list').addEventListener('click', function (ev) {
    var b = ev.target.closest('button[data-act]'); if (!b) return;
    var id = b.dataset.id, d = state.devices.find(function (x) { return x.id === id; }) || {};
    if (b.dataset.act === 'rename') {
      uiForm({ title: 'Thermometer umbenennen', fields: [{ id: 'name', label: 'Name', type: 'text', value: d.name || '' }], okText: 'Speichern' }).then(function (r) {
        if (!r || !String(r.name || '').trim()) return;
        api('/api/thermo/' + encodeURIComponent(id), 'PATCH', { name: r.name }).then(load).catch(function (e) { msg(e.message, true); });
      });
    } else if (b.dataset.act === 'update') {
      uiDialog({ title: 'Firmware-Update', okText: 'Update vormerken', message: '„' + (d.name || id) + '“ lädt die Firmware ' + (state.fw ? state.fw.version : '') + ' bei seiner nächsten Meldung (gleich nach der Messung, nur bei ausreichender Batterie) und startet neu. Es gibt keinen automatischen Rückfall bei einer fehlerhaften Firmware – neue Versionen erst an einem Thermometer testen.' }).then(function (ok) {
        if (!ok) return;
        api('/api/thermo/' + encodeURIComponent(id) + '/update', 'POST', {}).then(function (j) { savedToast('Update vorgemerkt ✓'); msg('Das Thermometer lädt die Firmware ' + j.version + ' bei seiner nächsten Meldung (spätestens nach ' + d.interval + ' Minuten; nach RESET sofort).'); return load(); }).catch(function (e) { msg(e.message, true); });
      });
    } else if (b.dataset.act === 'newcode') {
      newCode(d);
    } else if (b.dataset.act === 'code') {
      api('/api/thermo/' + encodeURIComponent(id) + '/code', 'POST', {}).then(function (j) { showCode(d, j.code); }).catch(function (e) { msg(e.message, true); });
    } else if (b.dataset.act === 'interval') {
      setInterval_(d);
    } else if (b.dataset.act === 'calib') {
      calibrate(d);
    } else if (b.dataset.act === 'label') {
      printLabel(d);
    } else if (b.dataset.act === 'del') {
      uiDialog({ title: 'Thermometer entfernen?', okText: 'Entfernen', message: '„' + (d.name || id) + '“ und seine Sensoren werden aus BlueNexus entfernt (Regeln und Diagramme, die sie benutzen, verlieren den Sensor). Am Chip selbst ändert sich nichts – dafür „ESP32 löschen“.' }).then(function (ok) {
        if (!ok) return;
        api('/api/thermo/' + encodeURIComponent(id), 'DELETE').then(function () { savedToast('Entfernt ✓'); return load(); }).catch(function (e) { msg(e.message, true); });
      });
    }
  });
  $('th-flash').addEventListener('click', flash);
  $('th-reset').addEventListener('click', resetChip);
  load();
  setInterval(function () { if (!document.hidden && !state.busy) load(); }, 20000);        // Liste (zuletzt gesehen, Werte) auffrischen

  /* Geraet ohne USB anlegen (Standort ohne eigene BlueNexus): ID + Schluessel erzeugen, Kopplungscode zum Kopieren zeigen */
  (function () {
    var go = $('th-sa-go'); if (!go) return;
    var srv = $('th-sa-server');
    function mode() { var r = document.querySelector('input[name="th-mode"]:checked'); return r ? r.value : 'lan'; }
    function fillAddr() {          // Adresse je nach Weg vorbelegen: Heimnetz = lokale http-Adresse, Internet = gemerkte/aktuelle https-Adresse
      var v = '';
      if (mode() === 'lan') { v = state.server || ''; srv.placeholder = 'http://192.168.x.x:5005'; }
      else { try { v = localStorage.getItem('thSaServer') || ''; } catch (e) { /* nur Komfort */ } if (!v && location.protocol === 'https:') v = location.origin; srv.placeholder = 'https://…'; }
      srv.value = v;
    }
    Array.prototype.forEach.call(document.querySelectorAll('input[name="th-mode"]'), function (r) { r.addEventListener('change', fillAddr); });
    fillAddr(); setTimeout(fillAddr, 1500);   // zweiter Versuch, sobald die Liste (mit lokaler Adresse) geladen ist
    go.addEventListener('click', function () {
      var name = $('th-sa-name').value.trim() || 'Thermometer', addr = srv.value.trim().replace(/\/+$/, '');
      var lan = mode() === 'lan';
      if (!(lan ? /^http:\/\/[A-Za-z0-9.\-]+(:\d{1,5})?$/ : /^https:\/\/[A-Za-z0-9.\-]+(:\d{1,5})?$/).test(addr)) { $('th-sa-msg').textContent = lan ? 'Bitte die lokale Adresse als http://192.168.x.x:5005 eintragen.' : 'Bitte die Internet-Adresse als https://… eintragen (Tunnel-Adresse von BlueNexus).'; $('th-sa-msg').style.color = '#e5544a'; return; }
      go.disabled = true;
      api('/api/thermo', 'POST', { standalone: true, mode: lan ? 'lan' : 'net', name: name, location: $('th-sa-loc').value.trim(), interval: +$('th-sa-int').value || 15, server: addr }).then(function (j) {
        try { if (!lan) localStorage.setItem('thSaServer', addr); } catch (e) { /* egal */ }
        $('th-sa-code').value = j.code; $('th-sa-out').style.display = 'block';
        $('th-sa-msg').style.color = ''; $('th-sa-msg').textContent = '„' + j.device.name + '“ (' + j.device.id + ') angelegt. Der Code wird nur jetzt angezeigt – jetzt kopieren und an den Standort schicken.';
        try { navigator.clipboard.writeText(j.code); } catch (e) { /* Kopieren-Knopf bleibt */ }
        load();
      }).catch(function (e) { $('th-sa-msg').style.color = '#e5544a'; $('th-sa-msg').textContent = e.message; }).then(function () { go.disabled = false; });
    });
    $('th-sa-copy').addEventListener('click', function () {
      var t = $('th-sa-code'); t.select();
      try { navigator.clipboard.writeText(t.value).then(function () { toast('Kopiert ✓'); }); } catch (e) { document.execCommand('copy'); }
    });
  })();
})();
