/*
 * Etikett mit QR-Code und Namen auf einem Niimbot-Drucker (D110 / D110_M) drucken – Fenster für „NFC + QR“.
 * Braucht qrcode.js, niimbot.js, label.js (gleicher Ordner). Wird erst beim ersten Klick geladen.
 * Aufruf: EtikettDruck.open({ name: 'Garagentor', url: 'https://…/nfc/…' })
 */
(function (root) {
  'use strict';

  const KEY = 'bnx.etikett.v1';
  const SIZES = { '14x30': { label: '14 × 30 mm', mm: 30 }, '12x22': { label: '12 × 22 mm', mm: 22 }, custom: { label: 'Andere Länge …', mm: 30 } };
  const LAYOUTS = { 'qr-left': 'QR-Code links, Name rechts', 'qr-right': 'Name links, QR-Code rechts', 'qr-only': 'Nur QR-Code' };
  const esc = (t) => String(t == null ? '' : t).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  let S = { size: '14x30', customMm: 30, layout: 'qr-left', byPrinter: {} };
  try { S = Object.assign(S, JSON.parse(localStorage.getItem(KEY) || '{}')); } catch (e) { /* ohne Speicher */ }
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(S)); } catch (e) { /* egal */ } };

  let printer = null, logText = '';                                 // die Verbindung bleibt bestehen, solange die Seite offen ist
  const log = (m) => { logText += new Date().toLocaleTimeString('de-DE') + '  ' + m + '\n'; };

  /** Kann dieses Gerät/dieser Browser Bluetooth-Drucker ansprechen? */
  function support() {
    if (!/Android/i.test(navigator.userAgent || '')) return { ok: false, kind: 'other', text: 'Etiketten drucken geht am Android-Handy (Chrome): Öffne BlueNexus dort.' };
    if (!window.isSecureContext) return { ok: false, kind: 'http', text: 'Das Drucken geht nur über eine sichere Adresse (https://, z. B. dein Fernzugriff). Öffne BlueNexus über diese Adresse.' };
    if (!navigator.bluetooth) return { ok: false, kind: 'browser', text: 'Dieser Browser kann keine Bluetooth-Drucker ansprechen. Öffne BlueNexus in Chrome.' };
    return { ok: true, kind: 'ok', text: 'Etiketten mit QR-Code und Namen lassen sich mit einem Niimbot-Drucker (D110) drucken: „🏷 Etikett“ am Tag.' };
  }

  const lengthDots = () => Label.lengthDots(S.size === 'custom' ? Math.max(10, Math.min(80, Number(S.customMm) || 30)) : SIZES[S.size].mm);

  /** Etikett zeichnen; der QR-Code soll mindestens 2 Druckpunkte je Modul haben – sonst mit niedrigerer Fehlerkorrektur, sonst gesperrt. */
  function build(name, url) {
    let r;
    for (const ecc of ['M', 'L']) {
      r = Label.renderLabel({ link: url, name, lengthDots: lengthDots(), headDots: Label.HEAD_DOTS, layout: S.layout, ecc, quiet: 2, maxFont: 36 });
      if (r.info.qr && !r.info.qr.error && r.info.qr.moduleDots >= 2) break;
    }
    const q = r.info.qr;
    r.blocked = !!(q && (q.error || q.moduleDots < 2));
    r.reason = q && q.error ? q.error : (r.blocked ? 'Der Link ist für dieses Etikett zu lang: Der QR-Code würde zu klein und wäre schlecht lesbar. Bitte ein größeres Etikett wählen.' : '');
    return r;
  }

  function flowFor(name) { return /_M\b|D11_H|B21_PRO|B1_PRO/i.test(name || '') ? 'v4' : 'legacy'; }

  function open(opts) {
    const st = support();
    if (!st.ok) { if (root.uiAlert) root.uiAlert(st.text, 'Drucken hier nicht möglich'); return; }
    const tagName = opts.name || 'Tag', url = opts.url;
    const ov = document.createElement('div');
    ov.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.7);display:flex;align-items:flex-start;justify-content:center;z-index:1000;padding:16px;overflow:auto';
    ov.innerHTML = `<div style="background:var(--card);border:1px solid var(--border);border-radius:16px;padding:20px;width:100%;max-width:440px;margin:auto;box-shadow:0 12px 40px rgba(0,0,0,.5)">
      <h3 style="margin:0 0 4px;font-size:18px">🏷 Etikett drucken</h3>
      <div class="muted" style="margin-bottom:12px">QR-Code und Name für den Tag „${esc(tagName)}“ (derselbe Link wie auf dem NFC-Tag).</div>
      <div style="background:#fff;border-radius:6px;padding:8px;display:inline-block;max-width:100%;overflow:auto"><canvas id="etk-prev" style="display:block;image-rendering:pixelated;max-width:100%;height:auto"></canvas></div>
      <div class="muted" id="etk-info" style="margin:6px 0 10px"></div>
      <label style="display:block;margin:8px 0 3px">Etikettengröße im Drucker</label>
      <select id="etk-size" style="width:100%"></select>
      <div id="etk-custom" style="display:none;margin-top:6px"><label style="display:block;margin:4px 0 3px">Länge in mm (Breite 12 mm)</label><input id="etk-mm" type="number" min="10" max="80" step="0.5" style="width:100%"></div>
      <label style="display:block;margin:10px 0 3px">Aufbau</label>
      <select id="etk-layout" style="width:100%"></select>
      <div id="etk-block" style="display:none;color:#e5544a;margin-top:10px"></div>
      <div id="etk-printer" class="muted" style="margin-top:12px"></div>
      <div style="height:8px;background:var(--card2);border-radius:99px;overflow:hidden;margin-top:12px"><i id="etk-bar" style="display:block;height:100%;width:0;background:var(--green);transition:width .15s"></i></div>
      <div id="etk-msg" class="muted" style="margin-top:8px;white-space:pre-line;min-height:20px"></div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:14px">
        <button id="etk-print" type="button">Drucken</button>
        <button id="etk-other" type="button" class="ghost" style="display:none">Anderer Drucker</button>
        <button id="etk-close" type="button" class="ghost" style="margin-left:auto">Schließen</button>
      </div>
      <details style="margin-top:14px"><summary class="muted" style="cursor:pointer">Hilfe bei Problemen</summary>
        <div class="muted" style="margin:8px 0">Drucker einschalten, die Niimbot-App am Handy beenden (der Drucker verbindet sich nur mit einem Gerät) und noch einmal drucken. Erscheint der Drucker nicht in der Liste:</div>
        <label class="chk" style="display:flex;gap:8px;align-items:center"><input type="checkbox" id="etk-all"> Alle Bluetooth-Geräte in der Auswahl zeigen</label>
        <div class="muted" style="margin-top:10px">Protokoll (für die Fehlersuche):</div>
        <pre id="etk-log" style="max-height:180px;overflow:auto;font:12px/1.4 Consolas,monospace;white-space:pre-wrap;background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:8px;margin:6px 0"></pre>
        <button id="etk-copy" type="button" class="ghost">Protokoll kopieren</button>
      </details></div>`;
    document.body.appendChild(ov);
    const $ = (id) => ov.querySelector('#' + id);
    for (const [k, o] of Object.entries(SIZES)) $('etk-size').insertAdjacentHTML('beforeend', `<option value="${k}">${o.label}</option>`);
    for (const [k, t] of Object.entries(LAYOUTS)) $('etk-layout').insertAdjacentHTML('beforeend', `<option value="${k}">${t}</option>`);
    let busy = false, closed = false;

    function preview() {
      $('etk-size').value = S.size; $('etk-layout').value = S.layout; $('etk-mm').value = S.customMm;
      $('etk-custom').style.display = S.size === 'custom' ? '' : 'none';
      const r = build(tagName, url), c = $('etk-prev');
      c.width = r.canvas.width; c.height = r.canvas.height; c.getContext('2d').drawImage(r.canvas, 0, 0);
      c.style.width = (r.canvas.width * 3) + 'px';
      const q = r.info.qr, bits = ['Etikett ' + (r.canvas.width / 8).toFixed(0) + ' × 12 mm'];
      if (q && !q.error) bits.push('QR-Code ' + q.modules + ' Module, ' + q.moduleDots + ' Punkte je Modul');
      if (r.info.text && r.info.text.tooBig) bits.push('Der Name passt nicht ganz – kürzer schreiben');
      $('etk-info').textContent = bits.join(' · ');
      $('etk-block').style.display = r.blocked ? '' : 'none'; $('etk-block').textContent = r.reason;
      $('etk-print').disabled = busy || r.blocked;
      return r;
    }
    function status() {
      const c = printer && printer.connected;
      $('etk-printer').innerHTML = c ? '<span style="color:var(--green)">● Verbunden mit „' + esc(printer.device.name || '?') + '“</span>' : 'Noch kein Drucker verbunden – beim Drucken wählst du ihn aus.';
      $('etk-other').style.display = c ? '' : 'none';
    }
    function say(text, kind) { const m = $('etk-msg'); m.textContent = text || ''; m.style.color = kind === 'err' ? '#e5544a' : kind === 'ok' ? 'var(--green)' : kind === 'warn' ? 'var(--amber, #f0b429)' : ''; m.dataset.kind = kind || ''; }
    const refreshLog = () => { $('etk-log').textContent = logText; };
    const setBusy = (b) => { busy = b; $('etk-other').disabled = b; preview(); };

    $('etk-size').onchange = () => { S.size = $('etk-size').value; save(); preview(); };
    $('etk-mm').oninput = () => { S.customMm = Number($('etk-mm').value) || 30; save(); preview(); };
    $('etk-layout').onchange = () => { S.layout = $('etk-layout').value; save(); preview(); };
    $('etk-close').onclick = () => { closed = true; ov.remove(); };
    $('etk-copy').onclick = async () => { try { await navigator.clipboard.writeText(logText); $('etk-copy').textContent = 'Kopiert ✓'; } catch (e) { const r = document.createRange(); r.selectNodeContents($('etk-log')); const s = getSelection(); s.removeAllRanges(); s.addRange(r); } };
    $('etk-other').onclick = async () => { if (printer) await printer.disconnect(); printer = null; status(); say('', ''); };

    async function connect() {
      const o = { optionalServices: Niimbot.CANDIDATE_SERVICES };
      if ($('etk-all').checked) o.acceptAllDevices = true; else o.filters = ['D1', 'B1', 'B2', 'B3', 'D3'].map((p) => ({ namePrefix: p }));
      const dev = await navigator.bluetooth.requestDevice(o);
      dev.addEventListener('gattserverdisconnected', () => { log('Verbindung getrennt.'); if (printer) printer.char = null; if (!closed) status(); });
      printer = new Niimbot.NiimbotPrinter({ log: (m) => { log(m); if (!closed) refreshLog(); }, chunk: 20 });
      say('Verbinde mit „' + (dev.name || 'Drucker') + '“ … (bis zu 20 Sekunden)');
      await printer.connect(dev);
      const remembered = S.byPrinter[dev.name || ''];
      if (remembered && SIZES[remembered] && remembered !== S.size) { S.size = remembered; save(); preview(); }
      status();
    }

    $('etk-print').onclick = async () => {                           // direkt aus dem Klick: die Bluetooth-Auswahl braucht eine Nutzeraktion
      const r = preview();
      if (r.blocked) return;
      setBusy(true); $('etk-bar').style.width = '0'; say('');
      try {
        if (!printer || !printer.connected) await connect();
        S.byPrinter[printer.device.name || ''] = S.size; save();       // pro Drucker merken, welche Etiketten zuletzt eingelegt waren
        const flow = flowFor(printer.device.name), run = flow === 'v4' ? printer.printV4.bind(printer) : printer.printLegacy.bind(printer);
        log('Ablauf: ' + (flow === 'v4' ? 'D110_M / V4' : 'älterer D110') + ' (Drucker „' + (printer.device.name || '?') + '“)');
        say('Drucke …');
        const res = await run(Label.toPrintCanvas(build(tagName, url).canvas, 'cw'), { density: 3, copies: 1, rowDelay: 6, onProgress: (p) => { $('etk-bar').style.width = Math.round(p * 100) + '%'; } });
        $('etk-bar').style.width = '100%';
        if (res && res.ok) say('Fertig. Etikett aus dem Drucker ziehen.', 'ok');
        else say('Gesendet, aber der Drucker hat nicht alles bestätigt. Kam kein Etikett, bitte noch einmal drucken oder unter „Hilfe bei Problemen“ nachsehen.', 'warn');
      } catch (e) {
        if (e && e.name === 'NotFoundError') say('Kein Drucker ausgewählt.');
        else { log('✗ ' + (e && e.message || e)); say('Das hat nicht geklappt: ' + (e && e.message || e) + '\n\nDrucker einschalten, Niimbot-App am Handy beenden und noch einmal versuchen.', 'err'); }
      } finally {
        refreshLog(); status();
        await new Promise((res) => setTimeout(res, 1500));            // der Drucker braucht nach jedem Etikett einen Moment
        if (!closed) setBusy(false);
      }
    };
    preview(); status(); refreshLog();
  }

  root.EtikettDruck = { open, support };
})(typeof window !== 'undefined' ? window : globalThis);
