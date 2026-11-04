/* pfas-sidebar.js -- the rail and the section panel (templates/pfas_sidebar.pt):
   the rail's sections, the fold, the panel over the page and the phone's sheet,
   and saving pins, on PFAS and core pages alike. */

/* ── PFAS.nav: the rail and the panel ─────────────────────────────────
   The template draws every section the person may open, the current one
   shown. A rail button shows its section's panel and hides the others, on
   the page as it stands (it is a button, never a link); the mark of the
   current page's section (aria-current) stays where the page put it. The
   trees are the navigation tree component's.

   How the panel sits by the screen's width (pfas-sidebar.css draws each):
   - wide, 1280 px and more: the panel beside the rail. The top bar's menu
     button folds it to the rail and back, the choice kept for the session
     (sessionStorage pfas_panel_collapsed). Folded, a rail button opens its
     section over the page.
   - compact, below 1280 px: the panel is folded. A rail button (or the menu
     button) opens it over the page, which stays where it is; a press
     outside it, Escape or the same button closes it. Nothing is kept.
   - phone, 768 px and less: the rail is a bar along the bottom and a button
     opens its section as a sheet over the page, holding the focus; Escape,
     the backdrop or the same button closes it, the focus going back to the
     button that opened it. Nothing is kept.
   The state: html.pfas-panel-folded, the wide choice (pfas-topbar.js sets it
   from the session in the head, so the first paint is already folded; this
   keeps the class and the session in step), and is-open on the nav (over the
   page). html.pfas-has-nav says the page draws the nav, so the phone's page
   leaves room for the bar. Core's sidebar script binds #sidebar on core
   pages too, adding its own minimized and toggled; they are not this nav's
   states and are taken off. */
(function () {
  var PFAS = window.PFAS = window.PFAS || {};
  var nav = PFAS.nav = PFAS.nav || {};
  var KEY = 'pfas_panel_collapsed';
  /* pfas-sidebar.css uses the same two queries */
  var COMPACT = '(max-width: 1279.98px)', PHONE = '(max-width: 768px)';
  var FOLDED = 'pfas-panel-folded', HAS_NAV = 'pfas-has-nav';
  function root() { return document.documentElement; }
  var opener = null;
  function el() { return document.getElementById('sidebar'); }
  function each(box, sel, fn) { Array.prototype.forEach.call(box.querySelectorAll(sel), fn); }
  function media(q) { return !!(window.matchMedia && window.matchMedia(q).matches); }
  function stored() { try { return window.sessionStorage.getItem(KEY) === '1'; } catch (e) { return false; } }
  function store(folded) { try { window.sessionStorage.setItem(KEY, folded ? '1' : '0'); } catch (e) {} }
  function panel(sb) { return sb.querySelector('.pfas-panel'); }
  function shownSection(sb) { return sb.querySelector('.pfas-panel-section:not([hidden])'); }

  /* 'wide', 'compact' or 'phone' */
  nav.mode = function () { return media(PHONE) ? 'phone' : (media(COMPACT) ? 'compact' : 'wide'); };
  /* the panel is not beside the page: the rail alone, a section opening over the page */
  nav.folded = function () {
    return nav.mode() !== 'wide' || root().classList.contains(FOLDED);
  };
  nav.isOpen = function () { var sb = el(); return !!(sb && sb.classList.contains('is-open')); };

  /* show the section `id`; false when it is not drawn (nothing changes) */
  nav.show = function (id) {
    var sb = el();
    var target = sb && sb.querySelector('.pfas-panel-section[data-section="' + id + '"]');
    if (!target) return false;
    sb.setAttribute('data-section', id);
    each(sb, '.pfas-panel-section', function (s) {
      if (s === target) s.removeAttribute('hidden'); else s.setAttribute('hidden', 'hidden');
    });
    each(sb, '.pfas-rail-btn', function (b) {
      b.setAttribute('aria-pressed', b.getAttribute('data-section') === id ? 'true' : 'false');
    });
    if (sb.classList.contains('is-open') && nav.mode() === 'phone') sheet(sb, true);
    return true;
  };

  /* on a phone the open panel is a modal dialog named by its section */
  function sheet(sb, on) {
    var p = panel(sb), s = shownSection(sb);
    if (!p) return;
    if (on) {
      p.setAttribute('role', 'dialog');
      p.setAttribute('aria-modal', 'true');
      if (s && s.getAttribute('aria-labelledby')) p.setAttribute('aria-labelledby', s.getAttribute('aria-labelledby'));
    } else {
      p.removeAttribute('role');
      p.removeAttribute('aria-modal');
      p.removeAttribute('aria-labelledby');
    }
  }
  /* the open panel's tab stops, in order */
  function stops(sb) {
    var p = panel(sb);
    if (!p) return [];
    return Array.prototype.filter.call(p.querySelectorAll('a[href], button, [tabindex]'), function (n) {
      return n.getAttribute('tabindex') !== '-1' && !n.disabled && !n.closest('[hidden]');
    });
  }

  /* open the panel over the page on section `id` (the one shown when none);
     `from` is the button that opened it, which takes the focus back */
  nav.open = function (id, from) {
    var sb = el();
    if (!sb || (id && !nav.show(id))) return false;
    opener = from || null;
    sb.classList.add('is-open');
    if (nav.mode() === 'phone') {
      sheet(sb, true);
      var first = stops(sb)[0];
      if (first) first.focus();
    }
    return true;
  };
  nav.close = function () {
    var sb = el();
    if (!sb || !sb.classList.contains('is-open')) return;
    var p = panel(sb), back = opener, inside = !!(p && p.contains(document.activeElement));
    var modal = p && p.getAttribute('aria-modal') === 'true';
    opener = null;
    sb.classList.remove('is-open');
    sheet(sb, false);
    if (back && (inside || modal)) back.focus();
  };
  /* the top bar's menu button: on a wide screen it folds and unfolds the
     panel for the session; below, it opens and closes it over the page */
  nav.toggle = function (from) {
    var sb = el();
    if (!sb) return;
    if (nav.mode() === 'wide') {
      var fold = !root().classList.contains(FOLDED);
      nav.close();
      root().classList.toggle(FOLDED, fold);
      store(fold);
    } else if (nav.isOpen()) {
      nav.close();
    } else {
      nav.open(null, from);
    }
  };

  function railClick(sb, e) {
    var b = e.target && e.target.closest ? e.target.closest('.pfas-rail-btn') : null;
    if (!b || !sb.contains(b)) return;
    var id = b.getAttribute('data-section');
    if (!nav.folded()) { nav.show(id); return; }
    if (nav.isOpen() && sb.getAttribute('data-section') === id) { nav.close(); return; }
    nav.open(id, b);
  }
  /* once per document: a press outside, Escape, the sheet's focus trap, and
     a change of width closing what is open over the page */
  function watch() {
    if (document.__pfasNavFold) return;
    document.__pfasNavFold = true;
    document.addEventListener('click', function (e) {
      var t = e.target;
      if (!nav.isOpen() || !t || !t.closest || !document.documentElement.contains(t)) return;
      if (t.closest('#sidebar .pfas-rail, #sidebar .pfas-panel, .pfas-topbar-toggle')) return;
      nav.close();
    });
    document.addEventListener('keydown', function (e) {
      var sb = el();
      if (!sb || !nav.isOpen()) return;
      if (e.key === 'Escape') {
        /* an open row menu takes Escape first */
        if (!e.defaultPrevented && !sb.querySelector('.pfas-nav-menu')) nav.close();
        return;
      }
      if (e.key !== 'Tab' || nav.mode() !== 'phone') return;
      var s = stops(sb), a = document.activeElement, i = s.indexOf(a);
      if (!s.length) { e.preventDefault(); return; }
      if (i < 0) { e.preventDefault(); (e.shiftKey ? s[s.length - 1] : s[0]).focus(); }
      else if (e.shiftKey && i === 0) { e.preventDefault(); s[s.length - 1].focus(); }
      else if (!e.shiftKey && i === s.length - 1) { e.preventDefault(); s[0].focus(); }
    });
    [COMPACT, PHONE].forEach(function (q) {
      var mq = window.matchMedia && window.matchMedia(q);
      if (!mq) return;
      if (mq.addEventListener) mq.addEventListener('change', nav.close); else if (mq.addListener) mq.addListener(nav.close);
    });
  }
  /* ── Pins: Pin and Unpin in a row's menu, saved on the server ──
     The navigation tree says Pin or Unpin in a pfas:pin event {path, pinned}
     on the row, its data-pinned already flipped. That is one POST of path,
     pinned and the page's _authenticator (data-token) to the pins view
     (data-pins-url). Its reply's rows (sidebar_pins.pins_for) are the pins
     as Home lists them: the list is drawn again from them alone, as the
     template draws it, and every page row's data-pinned follows them; a
     family's row, which leads to one of its pages, is never pinned. A refused
     POST, a reply that is not the view's or none at all puts the row back
     and says why in the panel's status line. A page stored under another of
     its paths is unpinned by the path it is stored under. The nav's
     data-pins are the rows the page was drawn with. */
  var NOT_SAVED = 'The pin was not saved. Reload the page and try again.';
  function pinRows(sb) {
    if (!sb.__pfasPins) {
      var rows;
      try { rows = JSON.parse(sb.getAttribute('data-pins') || '[]'); } catch (e) { rows = []; }
      sb.__pfasPins = Array.isArray(rows) ? rows : [];
    }
    return sb.__pfasPins;
  }
  function storedPath(sb, path) {
    var hit = pinRows(sb).filter(function (r) { return r.path === path || r.url_path === path; })[0];
    return hit ? hit.path : path;
  }
  function say(sb, text) {
    var line = sb.querySelector('.pfas-nav-status');
    if (line) line.textContent = text || '';
  }
  function make(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text) n.textContent = text;
    return n;
  }
  function drawPins(sb) {
    var box = sb.querySelector('#pfas-nav-pins');
    if (!box) return;
    var active = document.activeElement;
    var had = active && box.contains(active) && active.getAttribute ? active.getAttribute('data-path') : null;
    while (box.firstChild) box.removeChild(box.firstChild);
    var purl = sb.getAttribute('data-portal') || '', back = null;
    pinRows(sb).forEach(function (r) {
      var li = make('li'), a = make('a', 'pfas-nav-row'), more = make('button', 'pfas-nav-more');
      li.setAttribute('role', 'none');
      a.setAttribute('role', 'treeitem');
      a.setAttribute('data-pinned', 'true');
      a.setAttribute('href', purl + '/' + r.url_path);
      a.setAttribute('data-path', r.path);
      a.appendChild(make('span', 'pfas-nav-label', r.label));
      if (r.ambiguous) a.appendChild(make('span', 'pfas-nav-place', r.place));
      more.setAttribute('type', 'button');
      more.setAttribute('tabindex', '-1');
      more.setAttribute('aria-haspopup', 'menu');
      more.setAttribute('aria-expanded', 'false');
      more.setAttribute('aria-label', 'Row menu');
      li.appendChild(a);
      li.appendChild(more);
      box.appendChild(li);
      if (had !== null && r.path === had) back = a;
    });
    if (pinRows(sb).length) box.removeAttribute('hidden'); else box.setAttribute('hidden', 'hidden');
    if (PFAS.components && PFAS.components.resetNavTree) PFAS.components.resetNavTree(box, back);
    if (had === null) return;
    /* the focus was in the list: on the same pin, else the first, else Home's first row */
    var home = box.closest('.pfas-panel-section');
    var to = back || box.querySelector('[role=treeitem]') || (home && home.querySelector('[role=treeitem]'));
    if (to) to.focus();
  }
  function syncPinned(sb) {
    var on = {};
    pinRows(sb).forEach(function (r) { on[r.url_path] = true; });
    var box = sb.querySelector('#pfas-nav-pins');
    each(sb, '.pfas-nav-row[role=treeitem]', function (a) {
      if (box && box.contains(a)) return;
      var pinned = !a.hasAttribute('aria-owns') && !!on[a.getAttribute('data-path')];
      a.setAttribute('data-pinned', pinned ? 'true' : 'false');
    });
  }
  function savePin(sb, e) {
    var item = e.target, d = e.detail || {}, url = sb.getAttribute('data-pins-url');
    if (!d.path || !url || !window.fetch) return;
    function fail(text) {
      item.setAttribute('data-pinned', d.pinned ? 'false' : 'true');
      say(sb, text || NOT_SAVED);
    }
    var body = 'path=' + encodeURIComponent(storedPath(sb, d.path)) + '&pinned=' + (d.pinned ? '1' : '0') +
               '&_authenticator=' + encodeURIComponent(sb.getAttribute('data-token') || '');
    window.fetch(url, { method: 'POST', credentials: 'same-origin', body: body,
                        headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json' } })
      .then(function (res) {
        return res.json().then(function (j) { return { ok: res.ok, status: res.status, j: j }; },
                               function () { return { ok: false, status: res.status, j: null }; });
      })
      .then(function (r) {
        if (r.ok && r.j && Array.isArray(r.j.rows)) {
          sb.__pfasPins = r.j.rows;
          say(sb, '');
          drawPins(sb);
          syncPinned(sb);
        } else {
          /* a 403 is the page's expired authenticator: say what to do, not its words */
          fail(r.status === 403 ? null : r.j && r.j.error);
        }
      }, function () { fail(); });
  }

  function shedCore(sb) {
    ['minimized', 'toggled'].forEach(function (c) { if (sb.classList.contains(c)) sb.classList.remove(c); });
  }
  nav.init = function () {
    var sb = el();
    if (!sb || sb.__pfasNav) return;
    sb.__pfasNav = true;
    root().classList.add(HAS_NAV);
    root().classList.toggle(FOLDED, stored());
    sb.addEventListener('click', function (e) { railClick(sb, e); });
    sb.addEventListener('pfas:pin', function (e) { savePin(sb, e); });
    shedCore(sb);
    if (window.MutationObserver) {
      new window.MutationObserver(function () { shedCore(sb); }).observe(sb, { attributes: true, attributeFilter: ['class'] });
    }
    watch();
    if (PFAS.components && PFAS.components.initNavTree) PFAS.components.initNavTree(sb);
  };
  nav.init();
})();

/* ── Core SENAITE page: the viewport ──
   Core pages end up with two <meta name="viewport"> tags and SENAITE's
   initial-scale=0.8 one wins, so everything appears zoomed out on a phone:
   one tag stays, at 1.0. */
(function () {
  if (document.body.classList.contains('pfas-app')) return;
  function fixViewport() {
    var metas = document.querySelectorAll('meta[name="viewport"]');
    if (metas.length <= 1) return;
    for (var i = 1; i < metas.length; i++) {
      metas[i].parentNode.removeChild(metas[i]);
    }
    metas[0].setAttribute('content', 'width=device-width, initial-scale=1.0');
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', fixViewport);
  } else {
    fixViewport();
  }
})();
