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
    var etk = typeof etikettState === 'function' ? etikettState() : { kind: 'other', text: '' };
    el.innerHTML = state.devices.map(function (d) {
      var l = d.last || {}, bat = l.bat, bstate = bat == null || bat < 1 ? '' : (bat > 3.1 ? 'ok' : (bat < 3.0 ? 'low' : 'warn'));
      var batTxt = bstate === '' ? '' : ' · Batterie ' + dec(bat, 2) + ' V' + (bstate === 'low' ? ' – bald wechseln' : '');
      return '<div data-row="' + esc(d.id) + '" style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;border:1px solid var(--border);border-radius:12px;padding:10px 12px">'
        + '<span title="' + (d.online ? 'meldet sich' : 'meldet sich nicht') + '" style="width:10px;height:10px;border-radius:50%;background:' + (d.online ? '#35c07a' : (d.last_seen == null ? '#9aa4b5' : '#e5544a')) + '"></span>'
        + '<div style="flex:1;min-width:180px"><b>' + esc(d.name) + '</b> <span class="muted">· ' + esc(d.id) + (d.fw ? ' · Firmware ' + esc(d.fw) : '') + '</span>'
        + '<div class="muted" style="font-size:13px">' + (d.last_seen == null ? (d.attempt ? '<span style="color:#e5544a">Anfrage angekommen, aber abgelehnt: ' + esc(d.attempt.why) + ' (vor ' + d.attempt.age_s + ' s, von ' + esc(d.attempt.ip) + ')</span>' : 'wartet auf die erste Meldung') : dec(l.temp) + ' °C · ' + dec(l.hum, 0) + ' % · ' + ago(d.age_s) + batTxt + (l.rssi != null ? ' · Empfang ' + dec(l.rssi, 0) + ' dBm' : '')) + ' · alle ' + d.interval + ' min' + metaTxt(d) + calTxt(d) + '</div></div>'
        + (etk.kind === 'other' ? '' : '<button type="button" class="ghost" data-act="label" data-id="' + esc(d.id) + '" title="Etikett mit Namen, ID und QR-Code für das Gehäuse drucken (Niimbot, am Android-Handy)">Etikett</button>')
        + '<button type="button" class="ghost" data-act="interval" data-id="' + esc(d.id) + '" title="Messintervall ändern (zum Testen oder Abgleichen kurz stellen)">Intervall</button>'
        + '<button type="button" class="ghost" data-act="calib" data-id="' + esc(d.id) + '" title="Auf Referenzwerte abgleichen (kalibrieren)">Abgleichen</button>'
        + '<button type="button" class="ghost" data-act="rename" data-id="' + esc(d.id) + '" title="Umbenennen">✎</button>'
        + '<button type="button" class="ghost" data-act="del" data-id="' + esc(d.id) + '" title="Entfernen">✕</button></div>';
    }).join('');
  }
  var RR = { 1: 'Einschalten', 2: 'RESET-Taste', 3: 'Software-Neustart', 4: 'Absturz', 5: 'Watchdog', 6: 'Watchdog', 7: 'Watchdog', 8: 'Zeitgeber', 9: 'Batterie schwach (Brownout)', 11: 'USB', 12: 'JTAG' };
  function metaTxt(d) {                                   // ab Firmware 1.1: Aufwachen Nr. und Grund des letzten Starts
    var m = d.meta || {};
    return m.n != null ? ' · Aufwachen Nr. ' + m.n + (m.rr != null && RR[m.rr] ? ' (' + RR[m.rr] + ')' : '') : '';
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
      state.devices = j.devices || []; state.fw = j.firmware || null; state.server = j.server || ''; state.secure = !!j.secure; state.wifi = j.wifi || state.wifi; applyWifi();
      if (!$('th-server').value) $('th-server').value = state.server;
      renderList(); checkEnv(); labelHint(); focusFromLink();
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
  function setBusy(b) { state.busy = b; $('th-flash').disabled = b; $('th-reset').disabled = b; checkEnv(); }

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
    var fwUrl = state.fw && state.fw.url, created = null, lib = null, session = null, logLines = [], ov = null;
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
      steps(3, 'ok'); steps(4, 'ok'); steps(5, 'ok', 'fertig geschrieben');
      return session.transport.disconnect().catch(function () {});               /* ein automatischer Neustart wirkt bei diesem Board nicht (getestet: RTS-, Soft- und Hard-Reset) - die RESET-Taste startet es */
    }).then(function () {
      steps(6, 'run', 'jetzt die RESET-Taste am Board drücken – das Thermometer meldet sich dann nach 1 bis 20 Sekunden');
      ov = resetOverlay();                                                         // grosser Hinweis ueber der Seite: nicht zu uebersehen
      return waitFirst(created.device.id, 90, ov);
    }).then(function (dev) {
      steps(6, 'ok'); if (ov) ov.close(true);
      msg('Thermometer verbunden: ' + dec(dev.last.temp) + ' °C, ' + dec(dev.last.hum, 0) + ' % Luftfeuchte. Die Sensoren findest du unter Smart Home → Sensoren (zunächst nur für Administratoren sichtbar).');
      setBusy(false); return load();
    }).catch(function (e) {
      if (ov) ov.close(false);
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
        msg((k === 6 ? (e && e.message === 'Abgebrochen' ? 'Abgebrochen. Der Chip ist geflasht – nach dem Druck auf die RESET-Taste meldet er sich und erscheint in der Liste.' : 'Der Chip ist geflasht, hat sich aber in 90 Sekunden nicht gemeldet. ' + why + ' Meldet er sich später doch noch, siehst du es in der Liste.') : friendly(e)) + (ours ? ' (Das angelegte Thermometer wurde wieder entfernt.)' : ''), true);
        setBusy(false); load();
      });
    });
  }
  function waitFirst(id, secs, ov) {
    var t0 = Date.now(), hinted = false;
    return new Promise(function (resolve, reject) {
      (function poll() {
        api('/api/thermo/' + encodeURIComponent(id) + '/status').then(function (j) {
          if (j.device && j.device.last_seen != null) return resolve(j.device);
          if (ov && ov.cancelled) return reject(new Error('Abgebrochen'));
          if (ov) ov.tick(Math.round((Date.now() - t0) / 1000));
          if (Date.now() - t0 > secs * 1000) return reject(new Error('timeout'));
          if (Date.now() - t0 > 30000 && !hinted) { hinted = true; steps(6, 'run', 'noch nichts angekommen – die RESET-Taste am Board noch einmal drücken (manchmal braucht es zwei Anläufe)'); }
          setTimeout(poll, 2000);
        }).catch(reject);
      })();
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
        msg('ESP32 gelöscht. Er ist jetzt im Auslieferungszustand und lässt sich über „Einrichten und flashen“ neu einrichten. Ein dazugehöriges Thermometer in der Liste kannst du mit ✕ entfernen.'); setBusy(false);
      }).catch(function (e) {
        var k = stepState.map(function (x) { return x && x.st; }).lastIndexOf('run'); if (k >= 0) steps(k, 'err');
        (session ? session.transport.disconnect().catch(function () {}) : Promise.resolve()).then(function () { msg(friendly(e), true); setBusy(false); });
      });
    });
  }

  /* ---------------- Grosser Hinweis: jetzt RESET druecken ---------------- */
  function resetOverlay() {
    if (!document.getElementById('th-css')) {
      var st = document.createElement('style'); st.id = 'th-css';
      st.textContent = '@keyframes thPulse{0%,100%{box-shadow:0 0 0 0 rgba(240,166,60,.65)}50%{box-shadow:0 0 0 22px rgba(240,166,60,0)}}@keyframes thSpin{to{transform:rotate(360deg)}}';
      document.head.appendChild(st);
    }
    var ov = document.createElement('div');
    ov.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.78);display:flex;align-items:center;justify-content:center;z-index:1300;padding:16px';
    ov.innerHTML = '<div class="th-ovcard" style="background:var(--card);border:2px solid #f0a63c;border-radius:18px;padding:26px 24px;width:100%;max-width:520px;text-align:center;box-shadow:0 12px 50px rgba(0,0,0,.6)">'
      + '<div style="width:104px;height:104px;margin:0 auto 16px;border-radius:50%;background:#f0a63c;color:#1b1f24;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:21px;letter-spacing:1px;animation:thPulse 1.4s infinite">RESET</div>'
      + '<div style="font-size:23px;font-weight:800;line-height:1.25;margin-bottom:10px">Jetzt die RESET-Taste am Thermometer drücken</div>'
      + '<div style="font-size:16px;line-height:1.55">Das Flashen ist <b>fertig</b>. Damit das Thermometer startet, auf der Platine die kleine Taste <b>RESET</b> (RST) <b>einmal</b> drücken – <b>nicht</b> die Taste BOOT. Die blaue LED blitzt dann <b>3× kurz</b> auf, wenn die Meldung gesendet wurde.</div>'
      + '<div class="th-ovstat muted" style="margin-top:18px;display:flex;align-items:center;justify-content:center;gap:10px"><span style="width:18px;height:18px;border:3px solid var(--border);border-top-color:#f0a63c;border-radius:50%;animation:thSpin .9s linear infinite"></span><span class="th-ovtxt">Warte auf das Thermometer …</span></div>'
      + '<div class="th-ovhint" style="display:none;margin-top:14px;padding:10px 12px;border-radius:10px;background:rgba(240,166,60,.16);color:#f0a63c;font-weight:700">Noch nichts angekommen? Die RESET-Taste <b>noch einmal</b> drücken – manchmal braucht es zwei Anläufe.</div>'
      + '<div style="margin-top:20px"><button type="button" class="ghost th-ovcancel">Abbrechen</button></div></div>';
    document.body.appendChild(ov);
    var o = { cancelled: false, tick: function (sec) {
      ov.querySelector('.th-ovtxt').textContent = 'Warte auf das Thermometer … ' + sec + ' s';
      if (sec >= 30) ov.querySelector('.th-ovhint').style.display = '';
    }, close: function (ok) {
      if (!ov.parentNode) return;
      if (!ok) { ov.remove(); return; }
      ov.querySelector('.th-ovcard').innerHTML = '<div style="font-size:64px;color:#35c07a;line-height:1">✓</div><div style="font-size:22px;font-weight:800;margin-top:8px">Thermometer verbunden</div>';
      setTimeout(function () { ov.remove(); }, 1400);
    } };
    ov.querySelector('.th-ovcancel').addEventListener('click', function () { o.cancelled = true; });
    return o;
  }

  /* ---------------- Etikett fuers Gehaeuse (Niimbot, Code in /static/etikett/) ---------------- */
  function printLabel(d) {
    var es = etikettState();
    if (!es.ok) { uiAlert(es.text, 'Drucken hier nicht möglich'); return; }
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
  load();
  setInterval(function () { if (!document.hidden && !state.busy) load(); }, 20000);        // Liste (zuletzt gesehen, Werte) auffrischen
})();
