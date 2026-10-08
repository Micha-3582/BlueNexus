/* Eigenes, dunkel gestyltes Kalender-Popup (statt des Browser-Standard-Datepickers). Genutzt von Dashboard und Verlaeufe.
 *   openCalendarPicker(anker, { value: 'JJJJ-MM-TT', min: 'JJJJ-MM-TT', max: 'JJJJ-MM-TT' }, tag => ...)
 */
(function () {
  var MONTHS = ['Januar', 'Februar', 'März', 'April', 'Mai', 'Juni', 'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember'];
  var pop = null, onOutside = null, onEsc = null;
  function pad(n) { return String(n).padStart(2, '0'); }
  function todayIso() { var d = new Date(); return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); }
  function close() {
    if (pop) { pop.remove(); pop = null; }
    if (onOutside) { document.removeEventListener('click', onOutside); onOutside = null; }
    if (onEsc) { document.removeEventListener('keydown', onEsc); onEsc = null; }
  }
  function open(anchor, opts, onPick) {
    close();
    var today = todayIso();
    var ym = (opts.value || today).split('-').map(Number), vy = ym[0], vm = ym[1];
    var el = document.createElement('div');
    el.className = 'calpop';
    function place() {
      var r = anchor.getBoundingClientRect(), top = r.bottom + 6, left = r.left;
      if (left + el.offsetWidth > window.innerWidth - 10) left = window.innerWidth - el.offsetWidth - 10;
      if (top + el.offsetHeight > window.innerHeight - 10) top = r.top - el.offsetHeight - 6;
      el.style.left = Math.max(10, left) + 'px';
      el.style.top = Math.max(10, top) + 'px';
    }
    function render() {
      var first = new Date(vy, vm - 1, 1), startOffset = (first.getDay() + 6) % 7, days = new Date(vy, vm, 0).getDate();
      var prevOff = opts.min && vy + '-' + pad(vm) + '-01' <= opts.min;
      var nextOff = opts.max && vy + '-' + pad(vm) + '-' + pad(days) >= opts.max;
      var cells = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'].map(function (w) { return '<div class="cal-wd">' + w + '</div>'; }).join('');
      for (var i = 0; i < startOffset; i++) cells += '<div></div>';
      for (var d = 1; d <= days; d++) {
        var iso = vy + '-' + pad(vm) + '-' + pad(d), dis = (opts.min && iso < opts.min) || (opts.max && iso > opts.max), cls = ['cal-day'];
        if (iso === today) cls.push('today');
        if (iso === opts.value) cls.push('sel');
        cells += '<button type="button" class="' + cls.join(' ') + '"' + (dis ? ' disabled' : '') + ' data-day="' + iso + '">' + d + '</button>';
      }
      el.innerHTML = '<div class="cal-head"><button type="button" class="cal-nav" data-nav="-1"' + (prevOff ? ' disabled' : '') + '>‹</button>'
        + '<b>' + MONTHS[vm - 1] + ' ' + vy + '</b><button type="button" class="cal-nav" data-nav="1"' + (nextOff ? ' disabled' : '') + '>›</button></div>'
        + '<div class="cal-grid">' + cells + '</div>';
    }
    render();
    document.body.appendChild(el);
    pop = el;
    place();
    el.addEventListener('click', function (e) {
      var nav = e.target.closest('[data-nav]');
      if (nav) { vm += Number(nav.dataset.nav); if (vm < 1) { vm = 12; vy--; } else if (vm > 12) { vm = 1; vy++; } render(); place(); return; }
      var day = e.target.closest('[data-day]');
      if (day) { close(); onPick(day.dataset.day); }
    });
    setTimeout(function () {
      onOutside = function (e) { if (!el.contains(e.target) && !anchor.contains(e.target)) close(); };
      document.addEventListener('click', onOutside);
    }, 0);
    onEsc = function (e) { if (e.key === 'Escape') close(); };
    document.addEventListener('keydown', onEsc);
  }
  window.openCalendarPicker = open;
  window.closeCalPop = close;
})();
