/* Gemeinsame Sortierung fuer ALLE Listen der App (Standard): lang druecken, dann an die neue Stelle ziehen.
 *
 *   sortableList(container, { item, idOf, url, onDone, canStart, setActive })
 *     container   Element oder ID der Liste (wird nur einmal angebunden; neu gezeichneter Inhalt funktioniert weiter)
 *     item        CSS-Selektor der direkten Kinder, die sortiert werden (Standard: alle Kinder mit data-sort-id)
 *     idOf        el -> ID (Standard: el.dataset.sortId)
 *     url         optional: POST {ids: [...]} an diese Adresse, sobald losgelassen wird
 *     onDone      optional: onDone(ids) nach dem Loslassen (z. B. Entwurf aendern statt sofort speichern)
 *     canStart    optional: () => false sperrt das Sortieren zeitweise
 *     setActive   optional: setActive(true/false), z. B. um das automatische Neuzeichnen waehrend des Ziehens anzuhalten
 *
 * Bedienelemente (Knoepfe, Felder, Links, Auswahllisten, Regler) bleiben normal bedienbar; gestartet wird auf freier Zeilenflaeche.
 * Auf dem Handy scrollt die Seite normal, solange nicht lange gedrueckt wurde. Am Rand scrollt die Seite beim Ziehen mit.
 */
(function () {
  if (window.sortableList) return;
  var LONG_MS = 500, TOLERANCE = 10, EDGE = 70, SCROLL_STEP = 14;
  var style = document.createElement('style');
  style.textContent = '.sort-active{-webkit-user-select:none;user-select:none;cursor:grabbing}' +
    '.sort-dragging{transform:scale(1.01);box-shadow:0 10px 28px rgba(0,0,0,.5);opacity:.92;position:relative;z-index:5;outline:2px solid var(--accent,#3ca2cb);outline-offset:1px}';
  document.head.appendChild(style);

  var INTERACTIVE = 'input,select,textarea,button,a,label,summary,[contenteditable],.no-sort,.edit-panel,.tgl,.switch';

  window.sortableList = function (container, opts) {
    var box = typeof container === 'string' ? document.getElementById(container) : container;
    if (!box || box.dataset.sortableBound) return;
    box.dataset.sortableBound = '1';
    opts = opts || {};
    var idOf = opts.idOf || function (el) { return el.dataset.sortId; };
    var isItem = function (el) { return el.parentElement === box && (opts.item ? el.matches(opts.item) : el.dataset.sortId !== undefined); };
    var items = function () { return Array.prototype.filter.call(box.children, isItem); };
    var setActive = opts.setActive || function () {};
    var pending = null, dragEl = null, last = { x: 0, y: 0 }, scroller = null;

    function cancelPending() {
      if (pending) { clearTimeout(pending.timer); pending = null; if (!dragEl) setActive(false); }
    }
    function stopScroller() { if (scroller) { clearInterval(scroller); scroller = null; } }
    function endDrag() {
      cancelPending();
      if (!dragEl) return;
      dragEl.classList.remove('sort-dragging'); box.classList.remove('sort-active');
      var ids = items().map(idOf);
      dragEl = null; stopScroller(); setActive(false);
      document.removeEventListener('pointermove', onMove, true);
      document.removeEventListener('pointerup', endDrag, true);
      document.removeEventListener('pointercancel', endDrag, true);
      document.removeEventListener('touchmove', blockTouch, true);
      if (opts.url) {
        fetch(opts.url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids: ids }) })
          .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { if (!r.ok) throw new Error(j.error || ('Fehler ' + r.status)); }); })
          .then(function () { if (window.savedToast) window.savedToast('Reihenfolge gespeichert ✓'); })
          .catch(function (e) { if (window.shellyMsg) window.shellyMsg(e.message, true); });
      }
      if (opts.onDone) opts.onDone(ids);
    }
    function blockTouch(e) { if (dragEl && e.cancelable) e.preventDefault(); }
    function onMove(e) {
      last.x = e.clientX; last.y = e.clientY;
      if (!dragEl) return;
      e.preventDefault();
      var els = items();
      var target = els.find(function (el) {
        if (el === dragEl) return false;
        var r = el.getBoundingClientRect();
        return e.clientY >= r.top && e.clientY <= r.bottom && e.clientX >= r.left - 40 && e.clientX <= r.right + 40;
      });
      if (!target) return;
      if (els.indexOf(dragEl) < els.indexOf(target)) box.insertBefore(dragEl, target.nextSibling); else box.insertBefore(dragEl, target);
    }
    function startDrag(el) {
      pending = null; dragEl = el;
      box.classList.add('sort-active'); el.classList.add('sort-dragging');
      if (navigator.vibrate) navigator.vibrate(15);
      document.addEventListener('pointermove', onMove, true);
      document.addEventListener('pointerup', endDrag, true);
      document.addEventListener('pointercancel', endDrag, true);
      document.addEventListener('touchmove', blockTouch, { capture: true, passive: false });
      scroller = setInterval(function () {                // am oberen/unteren Rand mitscrollen
        if (!dragEl) return;
        if (last.y < EDGE) window.scrollBy(0, -SCROLL_STEP); else if (last.y > window.innerHeight - EDGE) window.scrollBy(0, SCROLL_STEP);
      }, 30);
    }
    box.addEventListener('pointerdown', function (e) {
      if (e.button !== undefined && e.button > 0) return;
      if (opts.canStart && !opts.canStart()) return;
      var el = e.target.closest ? items().find(function (it) { return it.contains(e.target); }) : null;
      if (!el || e.target.closest(INTERACTIVE)) return;
      cancelPending();
      setActive(true);
      last.x = e.clientX; last.y = e.clientY;
      pending = { x: e.clientX, y: e.clientY, timer: setTimeout(function () { startDrag(el); }, LONG_MS) };
    });
    box.addEventListener('pointermove', function (e) {
      if (pending && (Math.abs(e.clientX - pending.x) > TOLERANCE || Math.abs(e.clientY - pending.y) > TOLERANCE)) cancelPending();
    });
    ['pointerup', 'pointercancel', 'pointerleave'].forEach(function (ev) { box.addEventListener(ev, function () { if (!dragEl) cancelPending(); }); });
    box.addEventListener('contextmenu', function (e) { if (pending || dragEl) e.preventDefault(); });
  };
})();
