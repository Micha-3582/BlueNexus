/* Kopie aus dem Testprojekt Etikettendruck-Test (Micha-3582/Etikettendruck-Test), Stand 17.10.2026. Änderungen bitte dort testen und hierher kopieren. */
/*
 * Etikett zeichnen: QR-Code + Name, in Lesrichtung (quer) – danach für den Druck um 90° gedreht.
 * Maße: 203 dpi = ca. 8 Punkte je mm; der Druckkopf des D110 hat 96 Punkte (= 12 mm).
 */
(function (root) {
  'use strict';

  const DOTS_PER_MM = 8;
  const HEAD_DOTS = 96;
  const SIZES = {
    '14x30': { label: '14 × 30 mm', lengthMm: 30 },
    '12x22': { label: '12 × 22 mm', lengthMm: 22 },
    custom: { label: 'Eigene Länge …', lengthMm: 30 },
  };
  const FONT = '"Segoe UI", "Helvetica Neue", Arial, sans-serif';

  function newCanvas(w, h) {
    const c = (typeof document !== 'undefined') ? document.createElement('canvas') : null;
    c.width = w; c.height = h;
    return c;
  }

  /** Text in Zeilen umbrechen (an Leerzeichen, zu lange Wörter zeichenweise). */
  function wrapLines(ctx, text, maxW) {
    const words = String(text || '').split(/\s+/).filter(Boolean), lines = [];
    let cur = '';
    const fits = (s) => ctx.measureText(s).width <= maxW;
    for (const w of words) {
      const t = cur ? cur + ' ' + w : w;
      if (fits(t)) { cur = t; continue; }
      if (cur) { lines.push(cur); cur = ''; }
      if (fits(w)) { cur = w; continue; }
      let part = '';
      for (const ch of w) {                                      // einzelnes Wort länger als die Zeile
        if (fits(part + ch)) part += ch; else { if (part) lines.push(part); part = ch; }
      }
      cur = part;
    }
    if (cur) lines.push(cur);
    return lines;
  }

  /** Größte Schrift finden, bei der der Name in die Box passt (fett, ggf. mehrzeilig). */
  function fitText(ctx, text, boxW, boxH, maxSize, minSize) {
    const words = String(text || '').split(/\s+/).filter(Boolean);
    for (let size = maxSize; size >= minSize; size--) {           // zuerst: kein Wort mitten durchtrennen
      ctx.font = 'bold ' + size + 'px ' + FONT;
      if (!words.every((w) => ctx.measureText(w).width <= boxW)) continue;
      const lines = wrapLines(ctx, text, boxW);
      const lineH = Math.round(size * 1.12);
      if (lines.length * lineH <= boxH) return { size, lines, lineH };
    }
    for (let size = maxSize; size >= minSize; size--) {           // sonst: lange Wörter notfalls trennen
      ctx.font = 'bold ' + size + 'px ' + FONT;
      const lines = wrapLines(ctx, text, boxW);
      const lineH = Math.round(size * 1.12);
      if (lines.length * lineH <= boxH && lines.every((l) => ctx.measureText(l).width <= boxW)) return { size, lines, lineH, broken: true };
    }
    ctx.font = 'bold ' + minSize + 'px ' + FONT;
    const lines = wrapLines(ctx, text, boxW);
    return { size: minSize, lines, lineH: Math.round(minSize * 1.12), tooBig: true };
  }

  /** QR-Code mittig in ein Quadrat (box) zeichnen, ganzzahlige Modulgröße. Rückgabe: Infos oder {error}. */
  function drawQr(ctx, text, bx, by, box, ecc, quiet) {
    let qr;
    try { qr = root.qrcode(0, ecc || 'M'); qr.addData(String(text), 'Byte'); qr.make(); }
    catch (e) { return { error: 'Der Text ist für einen QR-Code zu lang.' }; }
    const n = qr.getModuleCount(), total = n + 2 * quiet;
    const mod = Math.max(1, Math.floor(box / total)), size = mod * n;
    const x0 = bx + Math.floor((box - size) / 2), y0 = by + Math.floor((box - size) / 2);
    ctx.fillStyle = '#000';
    for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) if (qr.isDark(r, c)) ctx.fillRect(x0 + c * mod, y0 + r * mod, mod, mod);
    return { modules: n, moduleDots: mod, moduleMm: mod / DOTS_PER_MM, sizeDots: size, fits: mod * total <= box };
  }

  /**
   * Etikett in Lesrichtung zeichnen.
   * o: { link, name, lengthDots, headDots, layout: 'qr-left'|'qr-right'|'qr-only'|'name-only', ecc, quiet, maxFont, border }
   */
  function renderLabel(o) {
    const W = o.lengthDots, H = o.headDots || HEAD_DOTS, pad = 4;
    const cv = newCanvas(W, H), ctx = cv.getContext('2d');
    ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, W, H);
    ctx.textBaseline = 'top'; ctx.fillStyle = '#000';
    const info = { width: W, height: H };
    const box = H - 2 * pad;
    const layout = o.layout || 'qr-left';
    let textBox = null, qrX = pad;
    if (layout === 'qr-only') { qrX = Math.floor((W - box) / 2); }
    else if (layout === 'qr-left') { qrX = pad; textBox = { x: pad + box + 6, w: W - (pad + box + 6) - pad }; }
    else if (layout === 'qr-right') { qrX = W - pad - box; textBox = { x: pad, w: qrX - 6 - pad }; }
    else if (layout === 'name-only') { textBox = { x: pad + 2, w: W - 2 * pad - 4 }; }
    if (layout !== 'name-only') {
      const q = drawQr(ctx, o.link, qrX, pad, box, o.ecc, o.quiet == null ? 2 : o.quiet);
      Object.assign(info, { qr: q });
    }
    if (textBox && o.name) {
      const f = fitText(ctx, o.name, textBox.w, box, o.maxFont || 36, 9);
      const totalH = f.lines.length * f.lineH, y0 = pad + Math.floor((box - totalH) / 2);
      ctx.fillStyle = '#000';
      f.lines.forEach((l, i) => ctx.fillText(l, textBox.x, y0 + i * f.lineH));
      info.text = { size: f.size, lines: f.lines.length, tooBig: !!f.tooBig };
    }
    if (o.border) { ctx.strokeStyle = '#000'; ctx.lineWidth = 1; ctx.strokeRect(0.5, 0.5, W - 1, H - 1); }
    return { canvas: cv, info };
  }

  /** Testbild: Rahmen, Millimeter-Skala, Buchstabe und Pfeil – zeigt Ausrichtung, Ränder und ob etwas abgeschnitten wird. */
  function renderTest(o) {
    const W = o.lengthDots, H = o.headDots || HEAD_DOTS;
    const cv = newCanvas(W, H), ctx = cv.getContext('2d');
    ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = '#000'; ctx.strokeStyle = '#000'; ctx.lineWidth = 1;
    ctx.strokeRect(0.5, 0.5, W - 1, H - 1);
    ctx.font = '10px ' + FONT; ctx.textBaseline = 'top';
    for (let mm = 1; mm * DOTS_PER_MM < W; mm++) {                // Skala oben und unten (alle 5 mm lang + Zahl)
      const x = mm * DOTS_PER_MM, long = mm % 5 === 0;
      ctx.fillRect(x, 1, 1, long ? 8 : 4);
      ctx.fillRect(x, H - (long ? 9 : 5), 1, long ? 8 : 4);
      if (long && mm % 10 === 0) ctx.fillText(String(mm), x + 2, 10);
    }
    for (let mm = 1; mm * DOTS_PER_MM < H; mm++) {                // Skala links
      const y = mm * DOTS_PER_MM, long = mm % 5 === 0;
      ctx.fillRect(1, y, long ? 8 : 4, 1);
    }
    ctx.font = 'bold 44px ' + FONT; ctx.fillText('F', 16, 24);   // F: zeigt Drehung und Spiegelung eindeutig
    ctx.font = 'bold 14px ' + FONT;
    ctx.fillText('→ Leserichtung', 56, 30);
    ctx.font = '11px ' + FONT;
    ctx.fillText(W + '×' + H + ' Punkte (' + (W / DOTS_PER_MM).toFixed(1) + '×' + (H / DOTS_PER_MM).toFixed(1) + ' mm)', 56, 54);
    return { canvas: cv, info: { width: W, height: H } };
  }

  /** Lesbares Etikett für den Druck drehen: Breite = Druckkopf (96), Höhe = Länge. dir: 'cw' (rechts) oder 'ccw' (links). */
  function toPrintCanvas(src, dir) {
    const out = newCanvas(src.height, src.width), ctx = out.getContext('2d');
    ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, out.width, out.height);
    if (dir === 'ccw') { ctx.translate(0, out.height); ctx.rotate(-Math.PI / 2); }
    else { ctx.translate(out.width, 0); ctx.rotate(Math.PI / 2); }
    ctx.drawImage(src, 0, 0);
    return out;
  }

  root.Label = { DOTS_PER_MM, HEAD_DOTS, SIZES, renderLabel, renderTest, toPrintCanvas, lengthDots: (mm) => Math.round(mm * DOTS_PER_MM) };
})(typeof window !== 'undefined' ? window : globalThis);
