/* Kopie aus dem Testprojekt Etikettendruck-Test (Micha-3582/Etikettendruck-Test), Stand 17.10.2026. Änderungen bitte dort testen und hierher kopieren. */
/*
 * Niimbot-Etikettendrucker (D110 / D110_M u. a.) per Web Bluetooth ansprechen.
 *
 * Eigene, kleine Umsetzung des bekannten Protokolls (Vorlage: niimprint / NiimBlue, beide Open Source):
 *   Paket: 55 55 | Befehl | Länge | Daten ... | Prüfsumme (XOR aus Befehl, Länge, Daten) | AA AA
 *   Bild: Zeile für Zeile (0x85), 1 Bit je Punkt, schwarz = 1, 96 Punkte Breite beim D110 (= 12 mm Druckkopf).
 *
 * Reine Logik (Paket bauen/lesen, Bild in Zeilen) ist von Web Bluetooth getrennt und lässt sich ohne Drucker testen.
 */
(function (root) {
  'use strict';

  const SERVICE = 'e7810a71-73ae-499d-8c15-faa9aef0c3f2';
  const CHARACTERISTIC = 'bef8d6c9-9c21-4c9e-b632-bd58c1009f9f';
  // Weitere Dienste, die Niimbot-Geräte anbieten können (Web Bluetooth zeigt nur Dienste, die vorher erlaubt wurden)
  const CANDIDATE_SERVICES = [SERVICE, '49535343-fe7d-4ae5-8fa9-9fafd205e455', '0000ff00-0000-1000-8000-00805f9b34fb', '0000fee7-0000-1000-8000-00805f9b34fb',
    '0000ae00-0000-1000-8000-00805f9b34fb', '0000ae30-0000-1000-8000-00805f9b34fb'];

  const CMD = {
    CONNECT: 0xc1, PRINTER_STATUS_DATA: 0xa5, EMPTY_ROW: 0x84, ROW_INDEXED: 0x83,
    START_PRINT: 0x01, START_PAGE: 0x03, DIMENSION: 0x13, QUANTITY: 0x15, GET_RFID: 0x1a, ALLOW_CLEAR: 0x20,
    LABEL_DENSITY: 0x21, LABEL_TYPE: 0x23, GET_INFO: 0x40, IMAGE_ROW: 0x85, HEARTBEAT: 0xdc, STATUS: 0xa3,
    END_PAGE: 0xe3, END_PRINT: 0xf3,
  };
  const INFO = { DENSITY: 1, SPEED: 2, LABEL_TYPE: 3, LANGUAGE: 6, AUTOSHUTDOWN: 7, DEVICE_TYPE: 8, SOFTWARE: 9, BATTERY: 10, SERIAL: 11, HARDWARE: 12 };

  const hex = (b) => Array.from(b, (x) => x.toString(16).padStart(2, '0')).join(' ');
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  function checksum(cmd, data) {
    let x = (cmd ^ data.length) & 0xff;
    for (const b of data) x ^= b;
    return x & 0xff;
  }

  function encodePacket(cmd, data) {
    data = Uint8Array.from(data || []);
    if (data.length > 255) throw new Error('Paket zu lang');
    const out = new Uint8Array(data.length + 7);
    out[0] = 0x55; out[1] = 0x55; out[2] = cmd; out[3] = data.length;
    out.set(data, 4);
    out[4 + data.length] = checksum(cmd, data);
    out[5 + data.length] = 0xaa; out[6 + data.length] = 0xaa;
    return out;
  }

  /** Setzt Antworten des Druckers aus einzelnen Funk-Stücken wieder zu Paketen zusammen. */
  class PacketParser {
    constructor() { this.buf = []; }
    push(bytes) {
      for (const b of bytes) this.buf.push(b);
      const out = [];
      for (;;) {
        let i = 0;
        while (i + 1 < this.buf.length && !(this.buf[i] === 0x55 && this.buf[i + 1] === 0x55)) i++;
        if (i > 0) this.buf.splice(0, i);                         // Müll vor dem Kopf verwerfen
        if (this.buf.length < 4) break;
        const len = this.buf[3], total = len + 7;
        if (this.buf.length < total) break;
        const cmd = this.buf[2], data = this.buf.slice(4, 4 + len);
        const ok = this.buf[4 + len] === checksum(cmd, data) && this.buf[5 + len] === 0xaa && this.buf[6 + len] === 0xaa;
        this.buf.splice(0, ok ? total : 2);                       // kaputtes Paket: Kopf überspringen und neu einrasten
        if (ok) out.push({ cmd, data: Uint8Array.from(data) });
      }
      return out;
    }
  }

  /**
   * Bild (Canvas im Druckformat: Breite = Druckkopf, Höhe = Etikettenlänge) in Druckzeilen umwandeln.
   * Schwarz (dunkler als threshold) = 1, links = höchstes Bit. Transparente Punkte zählen als weiß.
   */
  function imageToRows(canvas, threshold) {
    threshold = threshold == null ? 128 : threshold;
    const w = canvas.width, h = canvas.height;
    const px = canvas.getContext('2d').getImageData(0, 0, w, h).data;
    const rowBytes = Math.ceil(w / 8), rows = [];
    for (let y = 0; y < h; y++) {
      const row = new Uint8Array(rowBytes);
      for (let x = 0; x < w; x++) {
        const o = (y * w + x) * 4, a = px[o + 3] / 255;
        const lum = (0.299 * px[o] + 0.587 * px[o + 1] + 0.114 * px[o + 2]) * a + 255 * (1 - a);
        if (lum < threshold) row[x >> 3] |= 0x80 >> (x & 7);
      }
      rows.push(row);
    }
    return { rows, width: w, height: h };
  }

  function popcount(bytes) { let n = 0; for (const b of bytes) { let x = b; while (x) { n += x & 1; x >>= 1; } } return n; }

  /** Zeile als Paket. counts=true: Zeilennummer, 3 Pixelzähler (schwarze Punkte im linken/mittleren/rechten Drittel), Wiederholung; sonst Zähler 0 (alte Geräte). */
  function rowPacket(y, bytes, repeat, counts) {
    const data = new Uint8Array(6 + bytes.length);
    data[0] = (y >> 8) & 255; data[1] = y & 255;
    if (counts) {
      const per = Math.ceil(bytes.length / 3);
      for (let i = 0; i < 3; i++) data[2 + i] = Math.min(255, popcount(bytes.slice(i * per, (i + 1) * per)));
    }
    data[5] = repeat || 1;
    data.set(bytes, 6);
    return encodePacket(CMD.IMAGE_ROW, data);
  }

  /**
   * Alle Zeilen in Pakete umwandeln. mode: 'classic' (jede Zeile einzeln, Zähler 0) | 'counts' (gleiche Zeilen zusammengefasst, mit Pixelzählern)
   * | 'counts-empty' (wie 'counts', leere Zeilen als eigener Befehl 0x84). Rückgabe: Liste { y, packet }.
   */
  function rowsToPackets(rows, mode) {
    const out = [];
    const same = (a, b) => a.length === b.length && a.every((v, i) => v === b[i]);
    for (let y = 0; y < rows.length;) {
      let r = 1;
      if (mode !== 'classic') while (y + r < rows.length && r < 255 && same(rows[y], rows[y + r])) r++;
      const blank = rows[y].every((v) => v === 0);
      if (mode === 'counts-empty' && blank) out.push({ y, end: y + r, packet: encodePacket(0x84, [(y >> 8) & 255, y & 255, r]) });
      else out.push({ y, end: y + r, packet: rowPacket(y, rows[y], r, mode !== 'classic') });
      y += r;
    }
    return out;
  }

  /** Pixelzähler für Zeilenpakete wie in niimbluelib: 3 Teile (je ein Drittel der Druckkopfbreite); passt die Zeile nicht, [0, niedrig, hoch] der Gesamtzahl. */
  function countParts(bytes, headPixels) {
    const chunk = Math.floor(headPixels / 8 / 3), split = bytes.length <= chunk * 3;
    let total = 0;
    const parts = [0, 0, 0];
    bytes.forEach((v, n) => {
      const c = Math.floor(n / chunk);
      for (let b = 0; b < 8; b++) if (v & (1 << b)) { total++; if (split && c <= 2) parts[c]++; }
    });
    if (split) return { total, parts };
    return { total, parts: [0, total & 255, (total >> 8) & 255] };
  }

  /** Bildzeilen für Geräte mit V4-Ablauf (D110_M): leere Zeilen 0x84, sehr wenige Punkte 0x83 (Liste), sonst 0x85 (Bitmap); gleiche Zeilen mit Wiederholung. */
  function rowsToPacketsV4(rows, headPixels) {
    const out = [], same = (a, b) => a.length === b.length && a.every((v, i) => v === b[i]);
    for (let y = 0; y < rows.length;) {
      let r = 1;
      while (y + r < rows.length && r < 255 && same(rows[y], rows[y + r])) r++;
      const row = rows[y], hi = (y >> 8) & 255, lo = y & 255, black = popcount(row);
      let pk;
      if (black === 0) pk = encodePacket(CMD.EMPTY_ROW, [hi, lo, r]);
      else {
        const cp = countParts(row, headPixels);
        if (black <= 6) {
          const idx = [];
          for (let bi = 0; bi < row.length; bi++) for (let bit = 0; bit < 8; bit++) if (row[bi] & (0x80 >> bit)) { const x = bi * 8 + bit; idx.push((x >> 8) & 255, x & 255); }
          pk = encodePacket(CMD.ROW_INDEXED, [hi, lo, ...cp.parts, r, ...idx]);
        } else pk = encodePacket(CMD.IMAGE_ROW, [hi, lo, ...cp.parts, r, ...row]);
      }
      out.push({ y, end: y + r, packet: pk });
      y += r;
    }
    return out;
  }

  /** Auf was warten wir nach einem Befehl? (Antwort-Befehl = Befehl + 1, bei Infos 0x40 + Schlüssel) */
  class NiimbotPrinter {
    constructor(opts) {
      opts = opts || {};
      this.log = opts.log || function () {};
      this.chunk = opts.chunk || 20;                              // Funk-Stücke von höchstens 20 Byte gehen immer durch
      this.parser = new PacketParser();
      this.inbox = []; this.waiters = [];
      this.char = null; this.device = null;
      this._onNotify = this._onNotify.bind(this);
    }

    get connected() { return !!(this.device && this.device.gatt && this.device.gatt.connected && this.char); }

    /** Verbinden, bis zu 3 Versuche (unter Windows klappt die Dienstsuche oft erst beim zweiten Mal). */
    async connect(device) {
      this.device = device;
      const withTimeout = (p, ms, msg) => Promise.race([p, new Promise((_, rej) => setTimeout(() => rej(new Error(msg)), ms))]);
      let lastErr;
      for (let attempt = 1; attempt <= 2; attempt++) {
        try {
          this.log('Verbinde mit „' + (device.name || '?') + '“ (Versuch ' + attempt + ' von 2) …');
          this.log('  Hinweis: Fragt Windows unten rechts nach einer Kopplung/Verbindung, bitte bestätigen (bis zu 40 Sekunden Zeit).');
          const server = await withTimeout(device.gatt.connect(), 40000, 'Zeitüberschreitung beim Verbinden');
          this.log('Bluetooth-Verbindung steht, suche Dienste …');
          await sleep(700);                                       // dem Drucker kurz Zeit lassen (Windows)
          const services = await withTimeout(server.getPrimaryServices(), 40000, 'Zeitüberschreitung bei der Dienstsuche');
          let pick = null;
          for (const sv of services) {
            let chars = [];
            try { chars = await sv.getCharacteristics(); } catch (e) { this.log('  Dienst ' + sv.uuid + ': Eigenschaften nicht lesbar (' + e.message + ')'); }
            for (const c of chars) {
              const pr = c.properties, flags = ['read', 'write', 'writeWithoutResponse', 'notify', 'indicate'].filter((k) => pr[k]).join('+');
              this.log('  Dienst ' + sv.uuid + ' · Eigenschaft ' + c.uuid + ' (' + flags + ')');
              const canWrite = pr.writeWithoutResponse || pr.write, canNotify = pr.notify || pr.indicate;
              const known = sv.uuid === SERVICE && c.uuid === CHARACTERISTIC;
              if (known || (!pick && canWrite && canNotify)) { if (known || !pick) pick = c; }
            }
          }
          if (!pick) throw new Error('Kein passender Dienst gefunden (' + services.length + ' Dienste sichtbar)');
          this.char = pick;
          await this.char.startNotifications();
          this.char.addEventListener('characteristicvaluechanged', this._onNotify);
          this.log('Verbunden (Eigenschaft ' + pick.uuid + ').');
          await this.handshake();
          return;
        } catch (e) {
          lastErr = e;
          this.log('⚠ Versuch ' + attempt + ' fehlgeschlagen: ' + e.message);
          try { device.gatt.disconnect(); } catch (x) { /* egal */ }
          this.char = null;
          if (attempt < 2) await sleep(1500);
        }
      }
      throw lastErr;
    }

    /** Begrüßung wie niimbluelib: „Connect“, danach Statusdaten (schaltet neuere Geräte in den passenden Modus). Fehlt die Antwort, geht es trotzdem weiter. */
    async handshake() {
      const c = await this.send(CMD.CONNECT, [1], { expect: 0xc2, timeout: 2000, required: false });
      if (c) this.log('   Connect-Antwort: ' + hex(c.data));
      const st = await this.send(CMD.PRINTER_STATUS_DATA, [1], { expect: 0xb5, timeout: 2000, required: false });
      if (st) this.log('   Statusdaten: ' + hex(st.data));
    }

    async disconnect() {
      try { if (this.char) this.char.removeEventListener('characteristicvaluechanged', this._onNotify); } catch (e) { /* egal */ }
      try { if (this.device && this.device.gatt.connected) this.device.gatt.disconnect(); } catch (e) { /* egal */ }
      this.char = null;
    }

    _onNotify(ev) {
      const v = ev.target.value, bytes = new Uint8Array(v.buffer, v.byteOffset, v.byteLength);
      this.log('◀ ' + hex(bytes));
      for (const p of this.parser.push(bytes)) {
        if (p.cmd === 0xd3 && p.data.length >= 2) this.log('   (Fortschritt vom Drucker: Zeile ' + (p.data[0] * 256 + p.data[1]) + ')');
        const i = this.waiters.findIndex((w) => w.codes.includes(p.cmd));
        if (i >= 0) { const w = this.waiters.splice(i, 1)[0]; clearTimeout(w.timer); w.resolve(p); }
        else { this.inbox.push(p); if (this.inbox.length > 50) this.inbox.shift(); }
      }
    }

    async _write(bytes) {
      if (!this.char) throw new Error('Nicht mit dem Drucker verbunden');
      for (let i = 0; i < bytes.length; i += this.chunk) {
        const part = bytes.slice(i, i + this.chunk);
        if (this.char.writeValueWithoutResponse) await this.char.writeValueWithoutResponse(part);
        else await this.char.writeValue(part);
      }
    }

    _wait(codes, timeout) {
      const i = this.inbox.findIndex((p) => codes.includes(p.cmd));
      if (i >= 0) return Promise.resolve(this.inbox.splice(i, 1)[0]);
      return new Promise((resolve, reject) => {
        const w = { codes, resolve };
        w.timer = setTimeout(() => {
          this.waiters = this.waiters.filter((x) => x !== w);
          reject(new Error('keine Antwort (erwartet: ' + codes.map((c) => '0x' + c.toString(16)).join('/') + ')'));
        }, timeout);
        this.waiters.push(w);
      });
    }

    /** Befehl senden. expect: Antwort-Befehl(e); required=false: bei fehlender Antwort nur Warnung statt Fehler. */
    async send(cmd, data, o) {
      o = o || {};
      const pkt = encodePacket(cmd, data);
      if (o.expect) {                                              // veraltete Antworten dieser Art verwerfen: nur was NACH dem Senden kommt, zählt
        const codes = [].concat(o.expect), before = this.inbox.length;
        this.inbox = this.inbox.filter((p) => !codes.includes(p.cmd));
        if (this.inbox.length !== before) this.log('   (alte Meldung des Druckers verworfen)');
      }
      this.log('▶ ' + hex(pkt));
      await this._write(pkt);
      if (!o.expect) return null;
      try { return await this._wait([].concat(o.expect), o.timeout || 2500); }
      catch (e) {
        if (o.required === false) { this.log('⚠ ' + e.message); return null; }
        throw e;
      }
    }

    async info(key) {
      const p = await this.send(CMD.GET_INFO, [key], { expect: 0x40 + key, timeout: 2500 });
      return p.data;
    }

    /** Akku, Seriennummer, Versionen lesen (ändert nichts am Drucker). */
    async readInfo() {
      const out = {};
      const num = (d) => d.reduce((a, b) => a * 256 + b, 0);
      const tries = [['battery', INFO.BATTERY, (d) => d[0] + ' %'], ['serial', INFO.SERIAL, (d) => hex(d).replace(/ /g, '')],
        ['software', INFO.SOFTWARE, (d) => (num(d) / 100).toFixed(2)], ['hardware', INFO.HARDWARE, (d) => (num(d) / 100).toFixed(2)],
        ['type', INFO.DEVICE_TYPE, (d) => String(num(d))]];
      for (const [name, key, fmt] of tries) {
        try { const d = await this.info(key); out[name] = fmt(d); } catch (e) { out[name] = '–'; this.log('⚠ ' + name + ': ' + e.message); }
      }
      return out;
    }

    /**
     * Druck nach dem Ablauf „D110MV4PrintTask“ aus niimbluelib (D110_M): Etikettentyp, Dichte, Start (9 Byte), Status (ohne Antwort), Seitenmaße (13 Byte),
     * Bildzeilen, Seitenende, Status abfragen bis die Seite fertig ist, Druckende. Es gibt hier KEINEN „Seite starten“-Befehl.
     */
    async printV4(canvas, opts) {
      opts = Object.assign({ density: 3, copies: 1, labelType: 1, speed: 1, rowDelay: 6, threshold: 128, headPixels: 96 }, opts || {});
      const { rows, width, height } = imageToRows(canvas, opts.threshold);
      const prog = opts.onProgress || function () {};
      const refused = [], silent = [];
      const check = (name, r) => {
        if (!r) { silent.push(name); return r; }
        if (r.data.length && r.data[0] === 0) { refused.push(name); this.log('⚠ Der Drucker lehnt „' + name + '“ ab (Antwort 0).'); }
        else this.log('✓ ' + name + ': ok (Antwort ' + hex(r.data) + ')');
        return r;
      };
      const u16 = (n) => [(n >> 8) & 255, n & 255];
      this.inbox = [];                                                                 // nichts vom vorigen Auftrag mitnehmen
      for (let copy = 1; copy <= opts.copies; copy++) {
        this.log('— V4-Druck ' + copy + ' von ' + opts.copies + ': ' + width + ' × ' + height + ' Punkte');
        let started = false;
        for (let attempt = 1; attempt <= 4 && !started; attempt++) {
          check('Etikettentyp', await this.send(CMD.LABEL_TYPE, [opts.labelType], { expect: [0x33, 0x24], required: false }));
          check('Druckstärke', await this.send(CMD.LABEL_DENSITY, [opts.density], { expect: [0x31, 0x22], required: false }));
          const sr = await this.send(CMD.START_PRINT, [...u16(1), 0, 0, 0, 0, 0, opts.speed, 0], { expect: 0x02, timeout: 3000, required: false });
          started = !!(sr && sr.data.length && sr.data[0] === 1);
          if (started) this.log('✓ Druck starten: ok (Antwort ' + hex(sr.data) + ')');
          else if (attempt < 4) {
            this.log('⚠ Der Drucker ist noch beschäftigt oder hat nicht geantwortet – warte kurz und versuche es noch einmal (Versuch ' + (attempt + 1) + ' von 4).');
            await this.send(CMD.END_PRINT, [1], { expect: 0xf4, timeout: 1500, required: false });      // einen hängenden Auftrag sauber abschließen
            await sleep(1800);
          }
        }
        if (!started) throw new Error('Der Drucker nimmt den Druckauftrag nicht an (noch beschäftigt?). Kurz warten und noch einmal versuchen – oder Drucker aus- und einschalten.');
        await this.send(CMD.STATUS, [1]);                                              // ohne Antwort abzuwarten (wie niimbluelib)
        await sleep(100);
        check('Seitenmaße', await this.send(CMD.DIMENSION, [...u16(height), ...u16(width), ...u16(1), 0, 0, 0, 0, 0, 0, 0], { expect: 0x14, required: false }));
        const pkts = rowsToPacketsV4(rows, opts.headPixels);
        this.log('   ' + rows.length + ' Zeilen in ' + pkts.length + ' Paketen');
        for (let i = 0; i < pkts.length; i++) {
          await this._write(pkts[i].packet);
          if (opts.rowDelay) await sleep(opts.rowDelay);
          if (i % 4 === 0 || i === pkts.length - 1) prog((copy - 1 + pkts[i].end / rows.length) / opts.copies);
        }
        check('Seite beenden', await this.send(CMD.END_PAGE, [1], { expect: 0xe4, timeout: 10000, required: false }));
        // Warten, bis der Drucker die Seite fertig hat (Status: Seite, Druck-%, Vorschub-%)
        const t0 = Date.now();
        let fin = false;
        while (!fin && Date.now() - t0 < 25000) {
          const r = await this.send(CMD.STATUS, [1], { expect: 0xb3, timeout: 1500, required: false });
          if (r && r.data.length >= 4) {
            const page = r.data[0] * 256 + r.data[1], pp = r.data[2], fp = r.data[3], err = r.data.length >= 10 ? r.data[9] : 0;
            this.log('   Status: Seite ' + page + ' · Druck ' + pp + ' % · Vorschub ' + fp + ' %' + (err ? ' · FEHLER ' + err : ''));
            if (err) throw new Error('Der Drucker meldet einen Fehler (' + err + ') – Etikettenrolle/Deckel prüfen');
            fin = page >= 1 && pp >= 100 && fp >= 100;
          }
          if (!fin) await sleep(300);
        }
        if (!fin) silent.push('Fertig-Status');
        check('Druck beenden', await this.send(CMD.END_PRINT, [1], { expect: 0xf4, timeout: 3000, required: false }));
        await this.send(CMD.HEARTBEAT, [1]);                                           // wie niimbluelib nach dem Druckende, ohne Antwort
        await sleep(opts.copies > copy ? 1500 : 500);                                  // dem Drucker Zeit lassen, bevor das nächste Etikett kommt
      }
      return { ok: !refused.length && !silent.length, refused, silent };
    }

    /**
     * Druck für den älteren D110 (ohne „_M“) nach niimbluelib D110PrintTask: Dichte, Etikettentyp, Start (1 Byte), Druck löschen, Seite starten,
     * Maße (Zeilen, Breite), Stückzahl, Bildzeilen, Seitenende, Status abfragen bis der Seitenzähler hochzählt, Druckende.
     * Dieses Modell meldet im Status nur den Seitenzähler (Druck/Vorschub bleiben 0 %).
     */
    async printLegacy(canvas, opts) {
      opts = Object.assign({ density: 3, copies: 1, labelType: 1, rowDelay: 6, threshold: 128, headPixels: 96 }, opts || {});
      opts.density = Math.min(opts.density, 3);                                       // der ältere D110 kennt Stärken 1 bis 3
      const { rows, width, height } = imageToRows(canvas, opts.threshold);
      const prog = opts.onProgress || function () {};
      const refused = [], silent = [];
      const check = (name, r) => {
        if (!r) { silent.push(name); return r; }
        if (r.data.length && r.data[0] === 0) { refused.push(name); this.log('⚠ Der Drucker lehnt „' + name + '“ ab (Antwort 0).'); }
        else this.log('✓ ' + name + ': ok (Antwort ' + hex(r.data) + ')');
        return r;
      };
      const u16 = (n) => [(n >> 8) & 255, n & 255];
      const statusPage = async () => {
        const r = await this.send(CMD.STATUS, [1], { expect: 0xb3, timeout: 1500, required: false });
        if (!r || r.data.length < 2) return null;
        this.log('   Status: Seite ' + (r.data[0] * 256 + r.data[1]) + (r.data.length >= 4 ? ' · Druck ' + r.data[2] + ' % · Vorschub ' + r.data[3] + ' %' : ''));
        return r.data[0] * 256 + r.data[1];
      };
      this.inbox = [];                                                                 // nichts vom vorigen Auftrag mitnehmen
      for (let copy = 1; copy <= opts.copies; copy++) {
        this.log('— Druck (älterer D110) ' + copy + ' von ' + opts.copies + ': ' + width + ' × ' + height + ' Punkte');
        let started = false;
        for (let attempt = 1; attempt <= 4 && !started; attempt++) {
          check('Druckstärke', await this.send(CMD.LABEL_DENSITY, [opts.density], { expect: [0x31, 0x22], required: false }));
          check('Etikettentyp', await this.send(CMD.LABEL_TYPE, [opts.labelType], { expect: [0x33, 0x24], required: false }));
          const sr = await this.send(CMD.START_PRINT, [1], { expect: 0x02, timeout: 3000, required: false });
          started = !!(sr && sr.data.length && sr.data[0] === 1);
          if (started) this.log('✓ Druck starten: ok (Antwort ' + hex(sr.data) + ')');
          else if (attempt < 4) {
            this.log('⚠ Der Drucker ist noch beschäftigt oder hat nicht geantwortet – warte kurz und versuche es noch einmal (Versuch ' + (attempt + 1) + ' von 4).');
            await this.send(CMD.END_PRINT, [1], { expect: 0xf4, timeout: 1500, required: false });
            await sleep(1800);
          }
        }
        if (!started) throw new Error('Der Drucker nimmt den Druckauftrag nicht an (noch beschäftigt?). Kurz warten und noch einmal versuchen – oder Drucker aus- und einschalten.');
        check('Druck löschen', await this.send(CMD.ALLOW_CLEAR, [1], { expect: 0x30, required: false }));
        check('Seite starten', await this.send(CMD.START_PAGE, [1], { expect: 0x04, required: false }));
        check('Maße', await this.send(CMD.DIMENSION, [...u16(height), ...u16(width)], { expect: 0x14, required: false }));
        check('Stückzahl', await this.send(CMD.QUANTITY, [...u16(1)], { expect: 0x16, required: false }));
        const base = (await statusPage()) || 0;                                        // Seitenzähler vor dem Druck (kann vom vorigen Auftrag übrig sein)
        const pkts = rowsToPacketsV4(rows, opts.headPixels);
        this.log('   ' + rows.length + ' Zeilen in ' + pkts.length + ' Paketen');
        for (let i = 0; i < pkts.length; i++) {
          await this._write(pkts[i].packet);
          if (opts.rowDelay) await sleep(opts.rowDelay);
          if (i % 4 === 0 || i === pkts.length - 1) prog((copy - 1 + pkts[i].end / rows.length) / opts.copies);
        }
        check('Seite beenden', await this.send(CMD.END_PAGE, [1], { expect: 0xe4, timeout: 10000, required: false }));
        const t0 = Date.now();
        let fin = false;
        while (!fin && Date.now() - t0 < 25000) {
          const page = await statusPage();
          if (page !== null) fin = page > base || (page >= 1 && base === 0);
          if (!fin) await sleep(300);
        }
        if (!fin) silent.push('Fertig-Status');
        check('Druck beenden', await this.send(CMD.END_PRINT, [1], { expect: 0xf4, timeout: 3000, required: false }));
        await sleep(opts.copies > copy ? 1500 : 500);
      }
      return { ok: !refused.length && !silent.length, refused, silent };
    }
  }

  const api = { SERVICE, CHARACTERISTIC, CANDIDATE_SERVICES, CMD, INFO, hex, checksum, encodePacket, PacketParser, imageToRows, rowPacket, rowsToPackets, rowsToPacketsV4, countParts, popcount, NiimbotPrinter };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.Niimbot = api;
})(typeof window !== 'undefined' ? window : globalThis);
