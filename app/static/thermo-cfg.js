// Erzeugt die Konfigurations-Partition (4096 Byte) für das BlueNexus-Thermometer.
// Läuft im Browser und in Node (Referenz, bytegleich zu make_cfg.py). Format: src/config_store.h.
//
//   const bytes = buildCfg({ssid:"…", pass:"…", server:"http://192.168.2.40:5005",
//                           id:"t-8f3k2d9a", token:"…", name:"Aussen", interval:15,
//                           ip:{addr:"…", gw:"…", mask:"255.255.255.0", dns:"…"} /* oder null = DHCP */});
//   -> Uint8Array(4096), im Flash an Offset 0x1F0000 schreiben.

(function (root) {
  var SIZE = 4096, VER = 1;

  function crc32(bytes) {            // Standard-CRC32, identisch zu zlib.crc32
    var c, crc = 0xFFFFFFFF;
    for (var i = 0; i < bytes.length; i++) {
      c = (crc ^ bytes[i]) & 0xFF;
      for (var k = 0; k < 8; k++) c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
      crc = (crc >>> 8) ^ c;
    }
    return (crc ^ 0xFFFFFFFF) >>> 0;
  }

  function buildCfg(c) {
    var cfg = {
      v: 1, name: c.name || "", ssid: c.ssid, pass: c.pass || "",
      ip: c.ip || null,
      server: String(c.server).replace(/\/+$/, ""), id: c.id, token: c.token,
      interval: c.interval || 15
    };
    // Feldreihenfolge wie in Python (json.dumps ohne Leerzeichen); ensure_ascii=False -> UTF-8 direkt
    var payload = new TextEncoder().encode(JSON.stringify(cfg));
    if (payload.length > SIZE - 12) throw new Error("Konfiguration zu groß");
    var out = new Uint8Array(SIZE).fill(0xFF);
    out.set([0x42, 0x4E, 0x58, 0x43], 0);            // "BNXC"
    out[4] = VER; out[5] = 0;
    out[6] = payload.length & 0xFF; out[7] = payload.length >> 8;
    out.set(payload, 8);
    var crc = crc32(payload);
    for (var i = 0; i < 4; i++) out[8 + payload.length + i] = (crc >>> (8 * i)) & 0xFF;
    return out;
  }

  var api = { buildCfg: buildCfg, crc32: crc32, CFG_OFFSET: 0x1F0000, CFG_SIZE: SIZE };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.BNXC = api;
})(typeof self !== "undefined" ? self : this);
