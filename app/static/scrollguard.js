/* Seite hinter Fenstern festhalten: Solange ein Vollbild-Fenster (Dialog, Auswahl, Kamera-Vollbild ...) offen ist, scrollt die Seite dahinter
   nicht mit (sonst dreht sie mit, sobald man in der Liste am Anfang/Ende ist). Gilt fuer alle Fenster der App, ohne dass jedes etwas tun muss:
   erkannt wird ein sichtbares, bildschirmgrosses Element mit position:fixed und hohem z-index. */
(function () {
  var locked = null, de = document.documentElement;
  function isOverlay(el) {
    if (el.nodeType !== 1 || el.tagName === 'SCRIPT' || el.tagName === 'STYLE') return false;
    var cs = getComputedStyle(el);
    if (cs.position !== 'fixed' || cs.display === 'none' || cs.visibility === 'hidden' || cs.pointerEvents === 'none') return false;
    if ((parseInt(cs.zIndex, 10) || 0) < 1000) return false;
    return el.offsetWidth >= window.innerWidth * 0.9 && el.offsetHeight >= window.innerHeight * 0.9;
  }
  function wanted() {
    var kids = document.body ? document.body.children : [];
    for (var i = 0; i < kids.length; i++) if (isOverlay(kids[i])) return true;
    var fixed = document.querySelectorAll('.vl-modal, .wiz-overlay, .cam-box.fs');      // feste Fenster, die nicht direkt im body liegen
    for (var j = 0; j < fixed.length; j++) if (isOverlay(fixed[j])) return true;
    return false;
  }
  function lock() {
    var b = document.body, gap = window.innerWidth - de.clientWidth;
    locked = { de: de.style.overflow, b: b.style.overflow, pr: b.style.paddingRight };
    de.style.overflow = 'hidden';
    b.style.overflow = 'hidden';
    if (gap > 0) b.style.paddingRight = gap + 'px';          // kein Springen durch die verschwindende Bildlaufleiste
  }
  function unlock() {
    de.style.overflow = locked.de;
    document.body.style.overflow = locked.b;
    document.body.style.paddingRight = locked.pr;
    locked = null;
  }
  function tick() {
    var w = wanted();
    if (w && !locked) lock();
    else if (!w && locked) unlock();
  }
  setInterval(tick, 200);                                      // Fenster werden von vielen Stellen erzeugt/entfernt; eine kleine Pruefung ist robuster als jede Stelle anzupassen
})();
