/* Funkthermometer (ESP32-C3): einrichten, flashen und zuruecksetzen - direkt im Browser per Web Serial (esptool-js, lokal ausgeliefert).
   Ablauf: Thermometer in BlueNexus anlegen (ID + Schluessel) -> Konfiguration (cfg.bin) im Browser bauen (WLAN-Passwort bleibt im Browser) ->
   Chip loeschen, Firmware (ein Image) bei 0x0 und cfg.bin bei 0x1F0000 schreiben -> Neustart -> auf die erste Messung warten. */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var card = $('thermo-card'); if (!card) return;
  var esc = function (t) { return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); };
  var state = { fw: null, server: '', secure: false, devices: [], busy: false, wifi: { saved: false, ssid: '', has_pass: false } };
  var USB_FILTER = [{ usbVendorId: 0x303A, usbProductId: 0x1001 }];       // ESP32-C3: "USB JTAG/serial debug unit"
  var IPV4 = /^(25[0-5]|2[0-4]\d|1?\d?\d)(\.(25[0-5]|2[0-4]\d|1?\d?\d)){3}$/;

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

  /* ---------------- Gemerktes WLAN ---------------- */
  function applyWifi() {
    var w = state.wifi, ss = $('th-ssid'), pw = $('th-pass');
    if (w.saved) {
      if (!ss.value || ss.dataset.auto === '1') { ss.value = w.ssid; ss.dataset.auto = '1'; }
      pw.placeholder = w.has_pass ? 'gemerkt – leer lassen' : 'Passwort';
      $('th-saved').textContent = 'WLAN „' + w.ssid + '“ ist gemerkt' + (w.has_pass ? ' (mit Passwort)' : '') + '.';
    } else { pw.placeholder = 'Passwort'; $('th-saved').textContent = ''; }
    $('th-forget').style.display = w.saved ? '' : 'none';
  }
  $('th-ssid').addEventListener('input', function () { $('th-ssid').dataset.auto = '0'; });

  /* ---------------- Liste ---------------- */
  function renderList() {
    var el = $('th-list');
    if (!state.devices.length) { el.innerHTML = '<div class="muted">Noch kein Thermometer eingerichtet.</div>'; return; }
    el.innerHTML = state.devices.map(function (d) {
      var l = d.last || {}, bat = l.bat, bstate = bat == null || bat < 1 ? '' : (bat > 3.1 ? 'ok' : (bat < 3.0 ? 'low' : 'warn'));
      var batTxt = bstate === '' ? '' : ' · Batterie ' + dec(bat, 2) + ' V' + (bstate === 'low' ? ' – bald wechseln' : '');
      return '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;border:1px solid var(--border);border-radius:12px;padding:10px 12px">'
        + '<span title="' + (d.online ? 'meldet sich' : 'meldet sich nicht') + '" style="width:10px;height:10px;border-radius:50%;background:' + (d.online ? '#35c07a' : (d.last_seen == null ? '#9aa4b5' : '#e5544a')) + '"></span>'
        + '<div style="flex:1;min-width:180px"><b>' + esc(d.name) + '</b> <span class="muted">· ' + esc(d.id) + (d.fw ? ' · Firmware ' + esc(d.fw) : '') + '</span>'
        + '<div class="muted" style="font-size:13px">' + (d.last_seen == null ? (d.attempt ? '<span style="color:#e5544a">Anfrage angekommen, aber abgelehnt: ' + esc(d.attempt.why) + ' (vor ' + d.attempt.age_s + ' s, von ' + esc(d.attempt.ip) + ')</span>' : 'wartet auf die erste Meldung') : dec(l.temp) + ' °C · ' + dec(l.hum, 0) + ' % · ' + ago(d.age_s) + batTxt + (l.rssi != null ? ' · Empfang ' + dec(l.rssi, 0) + ' dBm' : '')) + ' · alle ' + d.interval + ' min</div></div>'
        + '<button type="button" class="ghost" data-act="rename" data-id="' + esc(d.id) + '" title="Umbenennen">✎</button>'
        + '<button type="button" class="ghost" data-act="key" data-id="' + esc(d.id) + '" title="Neuer Schlüssel / Zugangsdaten zum Abtippen">🔑</button>'
        + '<button type="button" class="ghost" data-act="del" data-id="' + esc(d.id) + '" title="Entfernen">✕</button></div>';
    }).join('');
  }
  function load() {
    return api('/api/thermo').then(function (j) {
      state.devices = j.devices || []; state.fw = j.firmware || null; state.server = j.server || ''; state.secure = !!j.secure; state.wifi = j.wifi || state.wifi; applyWifi();
      if (!$('th-server').value) $('th-server').value = state.server;
      renderList(); checkEnv();
    }).catch(function (e) { msg(e.message, true); });
  }

  /* ---------------- Voraussetzungen ---------------- */
  function envProblem() {
    if (!navigator.serial) return 'Zum Flashen braucht der Browser „Web Serial“: bitte Chrome oder Edge am PC benutzen (nicht Firefox, Safari oder Handy).';
    if (!window.isSecureContext) return 'Flashen im Browser geht nur über eine gesicherte Adresse (https oder localhost). Öffne BlueNexus über die https-Adresse – oder nimm „Ohne PC einrichten“.';
    if (!state.fw) return 'Die Firmware-Datei fehlt in dieser Installation (static/firmware/thermo).';
    return '';
  }
  function checkEnv() {
    var p = envProblem(), w = $('th-warn');
    w.style.display = p ? '' : 'none'; w.textContent = p;
    $('th-flash').disabled = !!p || state.busy; $('th-reset').disabled = !(navigator.serial && window.isSecureContext) || state.busy;
  }

  /* ---------------- Eingaben ---------------- */
  function readForm() {
    var name = $('th-name').value.trim() || 'Thermometer', ssid = $('th-ssid').value, pass = $('th-pass').value, server = $('th-server').value.trim().replace(/\/+$/, '');
    if (!ssid) throw new Error('Bitte den WLAN-Namen eintragen.');
    if (new TextEncoder().encode(ssid).length > 32) throw new Error('Der WLAN-Name ist zu lang (höchstens 32 Zeichen).');
    if (pass && (pass.length < 8 || pass.length > 63)) throw new Error('Das WLAN-Passwort muss 8 bis 63 Zeichen haben (oder leer bei einem offenen WLAN).');
    var useSaved = !pass && state.wifi.saved && state.wifi.ssid === ssid && state.wifi.has_pass;
    if (!/^http:\/\/[^\/\s]+$/.test(server)) throw new Error('Die Adresse von BlueNexus muss so aussehen: http://192.168.x.x:5005 (nur http, ohne Pfad).');
    var ip = null;
    if ($('th-fixed').checked) {
      var a = $('th-ip').value.trim(), g = $('th-gw').value.trim(), m = $('th-mask').value.trim() || '255.255.255.0', d = $('th-dns').value.trim() || g;
      [a, g, m, d].forEach(function (x) { if (!IPV4.test(x)) throw new Error('Feste IP: bitte gültige Adressen eintragen (z. B. 192.168.2.60).'); });
      ip = { addr: a, gw: g, mask: m, dns: d };
    }
    return { name: name, ssid: ssid, pass: pass, useSaved: useSaved, server: server, interval: parseInt($('th-int').value, 10) || 15, ip: ip };
  }

  /* ---------------- Fortschritt ---------------- */
  var STEPS = ['Thermometer anlegen', 'Mit dem Chip verbinden', 'Chip löschen', 'Firmware schreiben', 'Konfiguration schreiben', 'Neustart', 'Auf die erste Messung warten'];
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
  function setBusy(b) { state.busy = b; $('th-flash').disabled = b; $('th-reset').disabled = b; $('th-manual').disabled = b; checkEnv(); }

  function flash() {
    var f;
    try { f = readForm(); } catch (e) { msg(e.message, true); return; }
    if (!f.pass && !f.useSaved) {                              // kein Passwort eingetragen und keins gemerkt: nachfragen (haeufiger Tippfehler: Chip kaeme sonst nicht ins WLAN)
      uiDialog({ title: 'Kein WLAN-Passwort?', okText: 'Ja, das WLAN ist offen', message: 'Es ist kein Passwort eingetragen. Nur bei einem offenen WLAN ohne Passwort ist das richtig – sonst kann sich das Thermometer nicht verbinden.' }).then(function (ok) { if (ok) doFlash(f); });
      return;
    }
    doFlash(f);
  }
  function doFlash(f) {
    var fwUrl = state.fw && state.fw.url, created = null, lib = null, session = null, logLines = [];
    msg(''); resetSteps(); setBusy(true);
    var log = function (s) { logLines.push(String(s)); if (logLines.length > 40) logLines.shift(); };
    steps(0, 'run');
    api('/api/thermo', 'POST', { name: f.name, interval: f.interval, remember: $('th-remember').checked, wifi: { ssid: f.ssid, pass: f.pass, server: f.server, ip: f.ip } }).then(function (j) {
      created = j; steps(0, 'ok', j.device.id); if (j.wifi) { state.wifi = j.wifi; applyWifi(); }
      var cfgBytes = Uint8Array.from(atob(j.cfg), function (c) { return c.charCodeAt(0); });       // vom Server gebaut (ID, Schluessel, WLAN) - 4096 Byte
      steps(1, 'run');
      return Promise.all([loadLib(), fetch(fwUrl).then(function (r) { if (!r.ok) throw new Error('Firmware nicht ladbar'); return r.arrayBuffer(); })]).then(function (r) {
        return sha256hex(r[1]).then(function (h) {
          if (state.fw.sha256 && h !== state.fw.sha256) throw new Error('Die Firmware-Datei ist beschädigt (Prüfsumme stimmt nicht).');
          lib = r[0]; return openChip(lib, log).then(function (s) { session = s; return { fw: new Uint8Array(r[1]), cfg: cfgBytes }; });
        });
      });
    }).then(function (d) {
      steps(1, 'ok', session.chip); steps(2, 'run');
      return session.loader.eraseFlash().then(function () {
        steps(2, 'ok'); steps(3, 'run');
        var wrote = 0;
        return session.loader.writeFlash({
          fileArray: [{ data: d.fw, address: state.fw.offset || 0 }, { data: d.cfg, address: state.fw.cfg_offset }],
          flashSize: 'keep', flashMode: 'keep', flashFreq: 'keep', eraseAll: false, compress: true,
          reportProgress: function (i, w, t) { if (i === 0) steps(3, 'run', Math.round(w / t * 100) + ' %'); else { if (!wrote) { steps(3, 'ok'); wrote = 1; } steps(4, 'run'); } }
        });
      });
    }).then(function () {
      steps(3, 'ok'); steps(4, 'ok'); steps(5, 'run');
      return autoRestart(session, created.device.id);
    }).then(function (r) {
      steps(5, 'ok', r.device ? 'automatisch (' + r.how + ')' : 'nicht automatisch – bitte jetzt die RESET-Taste am Board drücken');
      return session.transport.disconnect().catch(function () {}).then(function () { return r; });
    }).then(function (r) {
      if (r.device) { steps(6, 'ok'); return r.device; }
      steps(6, 'run', 'bitte jetzt die RESET-Taste am Board drücken – das Thermometer meldet sich dann nach 1 bis 20 Sekunden'); return waitFirst(created.device.id, 60);
    }).then(function (dev) {
      steps(6, 'ok');
      msg('Thermometer verbunden: ' + dec(dev.last.temp) + ' °C, ' + dec(dev.last.hum, 0) + ' % Luftfeuchte. Die Sensoren findest du unter Smart Home → Sensoren (zunächst nur für Administratoren sichtbar).');
      setBusy(false); return load();
    }).catch(function (e) {
      var k = stepState.map(function (x) { return x && x.st; }).lastIndexOf('run'); if (k >= 0) steps(k, 'err');
      var ours = created && k >= 0 && k <= 5;
      var cleanup = (ours ? api('/api/thermo/' + created.device.id, 'DELETE').catch(function () {}) : Promise.resolve());
      var closer = session ? session.transport.disconnect().catch(function () {}) : Promise.resolve();
      var diag = (k === 6 && created) ? api('/api/thermo/' + encodeURIComponent(created.device.id) + '/status').then(function (j) { return j.device; }).catch(function () { return null; }) : Promise.resolve(null);
      Promise.all([cleanup, closer, diag]).then(function (r) {
        var dev = r[2], why = '';
        if (k === 6) why = dev && dev.attempt
          ? 'Eine Anfrage ist bei BlueNexus angekommen, wurde aber abgelehnt: ' + dev.attempt.why + ' (von ' + dev.attempt.ip + ').'
          : 'Bei BlueNexus ist keine Anfrage angekommen. Häufige Ursachen: Der Chip ist nach dem Flashen nicht neu gestartet (RESET-Taste drücken oder USB-C kurz abziehen und wieder anstecken – er meldet sich dann innerhalb von etwa 20 Sekunden), WLAN-Name oder -Passwort stimmen nicht (nur 2,4 GHz), oder die Adresse unter „Erweitert“ ist von dort aus nicht erreichbar.';
        msg((k === 6 ? 'Der Chip ist geflasht, hat sich aber in 60 Sekunden nicht gemeldet. ' + why + ' Meldet er sich später doch noch, siehst du es in der Liste.' : friendly(e)) + (ours ? ' (Das angelegte Thermometer wurde wieder entfernt.)' : ''), true);
        setBusy(false); load();
      });
    });
  }
  /* Neustart ins Programm nach dem Flashen. Beim eingebauten USB-Anschluss des ESP32-C3 (USB-Serial/JTAG) bleibt der Chip je nach Board und Treiber im Download-Modus stehen;
     deshalb mehrere Verfahren nacheinander, nach jedem prueft BlueNexus, ob sich das Thermometer meldet (es meldet sich 1-20 s nach dem Start). Das erste, das wirkt, wird angezeigt.
     Klappt keins, bleibt die RESET-Taste am Board. */
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  function seen(id) { return api('/api/thermo/' + encodeURIComponent(id) + '/status').then(function (j) { return j.device && j.device.last_seen != null ? j.device : null; }).catch(function () { return null; }); }
  function pollSeen(id, secs) {
    var t0 = Date.now();
    return (function next() {
      return seen(id).then(function (d) { if (d) return d; if (Date.now() - t0 > secs * 1000) return null; return sleep(1500).then(next); });
    })();
  }
  function autoRestart(session, id) {
    var tr = session.transport, ld = session.loader;
    var tries = [
      ['RTS-Reset', function () { return tr.setDTR(false).then(function () { return tr.setRTS(true); }).then(function () { return sleep(200); }).then(function () { return tr.setRTS(false); }); }],
      ['Soft-Reset', function () { return ld.softReset(false); }],
      ['Hard-Reset (Bibliothek)', function () { return ld.after('hard_reset'); }]
    ];
    return (function run(i) {
      if (i >= tries.length) return Promise.resolve({ device: null, how: '' });
      steps(5, 'run', 'Verfahren ' + (i + 1) + ' von ' + tries.length + ': ' + tries[i][0] + ' – bitte noch nichts drücken (das Thermometer meldet sich 1 bis 20 s nach dem Start)');
      return Promise.race([Promise.resolve().then(tries[i][1]).catch(function () {}), sleep(4000)]).then(function () { return pollSeen(id, 18); })      /* haengt ein Verfahren (Chip startet mitten im Befehl neu), nach 4 s weiter */.then(function (d) {
        return d ? { device: d, how: tries[i][0] } : run(i + 1);
      });
    })(0);
  }
  function waitFirst(id, secs) {
    var t0 = Date.now(), hinted = false;
    return new Promise(function (resolve, reject) {
      (function poll() {
        api('/api/thermo/' + encodeURIComponent(id) + '/status').then(function (j) {
          if (j.device && j.device.last_seen != null) return resolve(j.device);
          if (Date.now() - t0 > secs * 1000) return reject(new Error('timeout'));
          if (Date.now() - t0 > 20000 && !hinted) { hinted = true; steps(6, 'run', 'noch nichts angekommen – RESET-Taste am Board drücken (ca. 20 Sekunden warten)'); }
          setTimeout(poll, 2000);
        }).catch(reject);
      })();
    });
  }

  /* ---------------- Zuruecksetzen ---------------- */
  function resetChip() {
    var err = !navigator.serial ? 'Zum Löschen braucht der Browser „Web Serial“ (Chrome oder Edge am PC).' : (!window.isSecureContext ? 'Das geht nur über https oder localhost.' : '');
    if (err) { msg(err, true); return; }
    uiDialog({ title: 'Thermometer zurücksetzen', okText: 'Weiter',
      html: '<div style="text-align:left;line-height:1.5">Der Chip wird <b>komplett gelöscht</b> (Auslieferungszustand). Ein schlafender Chip ist am PC nicht zu sehen – bitte so vorbereiten:<ol style="margin:8px 0 0 18px;padding:0"><li>USB-C-Kabel an den PC anstecken.</li><li><b>BOOT-Taste halten</b>, dann USB-C anstecken (oder RESET drücken), danach BOOT loslassen.</li><li>Auf „Weiter“ klicken und den Eintrag „USB JTAG/serial debug unit“ wählen.</li></ol></div>' }).then(function (ok) {
      if (!ok) return;
      resetSteps(); msg(''); setBusy(true);
      var session = null, log = function () {};
      loadLib().then(function (lib) { return openChip(lib, log); }).then(function (s) { session = s; steps(1, 'ok', s.chip); steps(2, 'run'); return s.loader.eraseFlash(); }).then(function () {
        steps(2, 'ok'); return session.transport.disconnect().catch(function () {});
      }).then(function () {
        msg('Chip gelöscht. Er ist jetzt im Auslieferungszustand und lässt sich über „Einrichten und flashen“ neu einrichten. Ein dazugehöriges Thermometer in der Liste kannst du mit ✕ entfernen.'); setBusy(false);
      }).catch(function (e) {
        var k = stepState.map(function (x) { return x && x.st; }).lastIndexOf('run'); if (k >= 0) steps(k, 'err');
        (session ? session.transport.disconnect().catch(function () {}) : Promise.resolve()).then(function () { msg(friendly(e), true); setBusy(false); });
      });
    });
  }

  /* ---------------- Ohne PC (Einrichtungs-WLAN am Handy) ---------------- */
  function creds(j, intro) {
    var rows = [['Name', j.device.name], ['Geräte-ID', j.device.id], ['Schlüssel', j.token], ['Server', j.server || $('th-server').value || '']];
    return uiDialog({ title: 'Zugangsdaten', info: true, okText: 'Fertig',
      html: '<div style="text-align:left;line-height:1.5">' + intro + '<div style="margin-top:8px">' + rows.map(function (r) {
        return '<div style="margin:6px 0"><span class="muted">' + esc(r[0]) + '</span><br><code style="user-select:all;word-break:break-all">' + esc(r[1]) + '</code></div>';
      }).join('') + '</div><div class="muted" style="margin-top:8px">Der Schlüssel wird nur jetzt angezeigt. Das Thermometer öffnet ohne Einrichtung ein eigenes WLAN „BlueNexus-Thermo-XXXX“; dort die Werte und dein WLAN eintragen.</div></div>' });
  }
  function manual() {
    msg(''); setBusy(true);
    var name = $('th-name').value.trim() || 'Thermometer';
    api('/api/thermo', 'POST', { name: name, interval: parseInt($('th-int').value, 10) || 15 }).then(function (j) {
      return creds(j, 'Trage diese Werte im Einrichtungs-Formular des Thermometers ein.').then(function () { setBusy(false); return load(); });
    }).catch(function (e) { msg(e.message, true); setBusy(false); });
  }

  /* ---------------- Liste: Umbenennen, Schluessel, Entfernen ---------------- */
  $('th-list').addEventListener('click', function (ev) {
    var b = ev.target.closest('button[data-act]'); if (!b) return;
    var id = b.dataset.id, d = state.devices.find(function (x) { return x.id === id; }) || {};
    if (b.dataset.act === 'rename') {
      uiForm({ title: 'Thermometer umbenennen', fields: [{ id: 'name', label: 'Name', type: 'text', value: d.name || '' }], okText: 'Speichern' }).then(function (r) {
        if (!r || !String(r.name || '').trim()) return;
        api('/api/thermo/' + encodeURIComponent(id), 'PATCH', { name: r.name }).then(load).catch(function (e) { msg(e.message, true); });
      });
    } else if (b.dataset.act === 'key') {
      uiDialog({ title: 'Neuer Schlüssel?', okText: 'Neuen Schlüssel erzeugen', message: 'Der alte Schlüssel wird ungültig; das Thermometer muss danach neu eingerichtet werden (flashen oder am Handy eintragen). Die Sensoren bleiben bestehen.' }).then(function (ok) {
        if (!ok) return;
        api('/api/thermo/' + encodeURIComponent(id) + '/key', 'POST').then(function (j) { return creds({ device: j.device, token: j.token, server: j.server }, 'Neuer Schlüssel für dieses Thermometer.'); }).then(load).catch(function (e) { msg(e.message, true); });
      });
    } else if (b.dataset.act === 'del') {
      uiDialog({ title: 'Thermometer entfernen?', okText: 'Entfernen', message: '„' + (d.name || id) + '“ und seine Sensoren werden aus BlueNexus entfernt (Regeln und Diagramme, die sie benutzen, verlieren den Sensor). Am Chip selbst ändert sich nichts – dafür „Zurücksetzen“.' }).then(function (ok) {
        if (!ok) return;
        api('/api/thermo/' + encodeURIComponent(id), 'DELETE').then(function () { savedToast('Entfernt ✓'); return load(); }).catch(function (e) { msg(e.message, true); });
      });
    }
  });
  $('th-fixed').addEventListener('change', function () { card.querySelectorAll('.th-ip').forEach(function (x) { x.style.display = $('th-fixed').checked ? '' : 'none'; }); });
  card.querySelectorAll('.th-ip').forEach(function (x) { x.style.display = 'none'; });
  $('th-forget').addEventListener('click', function () {
    uiDialog({ title: 'Gemerktes WLAN vergessen?', okText: 'Vergessen', message: 'Name und Passwort werden vom Server gelöscht. Bereits eingerichtete Thermometer behalten ihre Einstellungen.' }).then(function (ok) {
      if (!ok) return;
      api('/api/thermo_wifi', 'DELETE').then(function (j) { state.wifi = j.wifi; $('th-pass').value = ''; applyWifi(); savedToast('Vergessen ✓'); }).catch(function (e) { msg(e.message, true); });
    });
  });
  $('th-flash').addEventListener('click', flash);
  $('th-reset').addEventListener('click', resetChip);
  $('th-manual').addEventListener('click', manual);
  load();
  setInterval(function () { if (!document.hidden && !state.busy) load(); }, 20000);        // Liste (zuletzt gesehen, Werte) auffrischen
})();
