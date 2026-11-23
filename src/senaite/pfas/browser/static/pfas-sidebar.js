/* pfas-sidebar.js -- the rail and the section panel (templates/pfas_sidebar.pt):
   the rail's sections, the fold, the panel over the page and the phone's sheet,
   and saving pins, on PFAS and core pages alike. */

/* ── PFAS.nav: the rail and the panel ─────────────────────────────────
   The template draws every section the person may open, the current one
   shown. A rail button shows its section's panel and hides the others, on
   the page as it stands (it is a button, never a link); the mark of the
   current page's section (aria-current) stays where the page put it. The
   tiles and their row menu are the nav tiles component's
   (pfas-components.js initNavTiles). Choosing a page folds the panel to the
   rail (nav.choose): a plain click or Enter on a tile, not one that opens the
   page in another tab or window.

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

  /* ── Motion (pfas-sidebar.css): something shown rises (the shared arrive);
     a closed panel is closed at once and keeps is-closing on the nav while
     its fade plays, then goes; opened again meanwhile, it stays. With no
     animation to play (reduced motion; no getAnimations) it goes at once. */
  function arrive(n, cls) {
    var m = PFAS.components && PFAS.components.motion;
    if (n && m) m.arrive(n, cls);
  }
  function unsettle(sb) { sb.__pfasClosing = null; sb.classList.remove('is-closing'); }
  function settle(sb) {
    var p = panel(sb), anims = [];
    unsettle(sb);
    if (p && p.getAnimations) {
      sb.classList.add('is-closing');
      anims = p.getAnimations().filter(function (a) {
        var t = a.effect && a.effect.getComputedTiming ? a.effect.getComputedTiming() : null;
        return a.animationName && t && t.endTime > 0;
      });
    }
    if (!anims.length) { unsettle(sb); return; }
    var token = {};
    sb.__pfasClosing = token;
    function end() { if (sb.__pfasClosing === token) unsettle(sb); }
    anims[0].finished.then(end, end);
  }
  /* the pressed fill: one mark behind the rail's buttons, moved by transform
     to the pressed one (its size taken at once); the first place, and a
     place after the rail changed size, is drawn there, not slid to */
  function placeMark(sb, slide) {
    var rail = sb.querySelector('.pfas-rail');
    if (!rail) return;
    var mark = rail.querySelector('.pfas-rail-mark');
    if (!mark) {
      mark = document.createElement('span');
      mark.className = 'pfas-rail-mark';
      mark.setAttribute('aria-hidden', 'true');
      rail.insertBefore(mark, rail.firstChild);
    }
    var on = rail.querySelector('.pfas-rail-btn[aria-pressed="true"]');
    var drawn = !!(on && on.offsetWidth);
    mark.hidden = !drawn;
    rail.classList.toggle('has-mark', drawn);
    if (!drawn) { mark.__pfasAt = null; return; }
    var at = 'translate(' + on.offsetLeft + 'px, ' + on.offsetTop + 'px)';
    mark.style.width = on.offsetWidth + 'px';
    mark.style.height = on.offsetHeight + 'px';
    if (slide && mark.__pfasAt) {
      mark.style.transform = at;
    } else {
      mark.style.transition = 'none';
      mark.style.transform = at;
      void mark.offsetWidth;               /* drawn there before the transition is back */
      mark.style.transition = '';
    }
    mark.__pfasAt = at;
  }
  nav.placeMark = function () { var sb = el(); if (sb) placeMark(sb, false); };

  /* 'wide', 'compact' or 'phone' */
  nav.mode = function () { return media(PHONE) ? 'phone' : (media(COMPACT) ? 'compact' : 'wide'); };
  /* the panel is not beside the page: the rail alone, a section opening over the page */
  nav.folded = function () {
    return nav.mode() !== 'wide' || root().classList.contains(FOLDED);
  };
  /* a page was chosen: the panel folds, for the session on a wide screen, and
     the page it leads to is drawn folded. */
  nav.choose = function () {
    var sb = el();
    if (!sb) return;
    if (nav.mode() === 'wide') {
      root().classList.add(FOLDED);
      store(true);
    }
    nav.close();
  };
  nav.isOpen = function () { var sb = el(); return !!(sb && sb.classList.contains('is-open')); };

  /* show the section `id`; false when it is not drawn (nothing changes) */
  nav.show = function (id) {
    var sb = el();
    var target = sb && sb.querySelector('.pfas-panel-section[data-section="' + id + '"]');
    if (!target) return false;
    var fresh = target.hasAttribute('hidden');
    sb.setAttribute('data-section', id);
    each(sb, '.pfas-panel-section', function (s) {
      if (s === target) s.removeAttribute('hidden'); else s.setAttribute('hidden', 'hidden');
    });
    each(sb, '.pfas-rail-btn', function (b) {
      b.setAttribute('aria-pressed', b.getAttribute('data-section') === id ? 'true' : 'false');
    });
    if (sb.classList.contains('is-open') && nav.mode() === 'phone') sheet(sb, true);
    /* a section shown in a drawn panel rises; in a panel about to open, the panel does */
    if (fresh) arrive(target, 'is-arriving');
    placeMark(sb, true);
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
    sb.classList.remove('is-closing');
    unsettle(sb);
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
    settle(sb);
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
      /* folded: the panel fades out over the page, which takes its width at
         once; unfolded: it rises in beside the page */
      if (fold) {
        settle(sb);
      } else {
        unsettle(sb);
        arrive(panel(sb), 'is-arriving');
      }
    } else if (nav.isOpen()) {
      nav.close();
    } else {
      nav.open(null, from);
    }
  };

  function tileClick(sb, e) {
    var a = e.target && e.target.closest ? e.target.closest('a.pfas-navtile') : null;
    if (!a || !sb.contains(a) || e.defaultPrevented) return;
    /* a page opened in another tab or window leaves this one as it is */
    if (e.button > 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
    nav.choose();
  }
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
     A tile's menu says Pin or Unpin in a pfas:pin event {path, pinned}
     on the tile, its data-pinned already flipped. That is one POST of path,
     pinned and the page's _authenticator (data-token) to the pins view
     (data-pins-url). Its reply's rows (sidebar_pins.pins_for) are the pins
     as Home lists them: the list is drawn again from them alone, as the
     template draws it, and every tile's data-pinned follows them. A refused
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
  function iconOf(name) { return /^ico-[a-z0-9-]+$/.test(name || '') ? name : 'ico-page'; }
  function drawPins(sb) {
    var box = sb.querySelector('#pfas-nav-pins');
    if (!box) return;
    var active = document.activeElement;
    var had = active && box.contains(active) && active.getAttribute ? active.getAttribute('data-path') : null;
    /* the pins drawn before: a page newly pinned rises in, the others stay */
    var before = {}, fresh = [];
    each(box, 'a.pfas-navtile', function (a) { before[a.getAttribute('data-path')] = true; });
    while (box.firstChild) box.removeChild(box.firstChild);
    var purl = sb.getAttribute('data-portal') || '', back = null;
    pinRows(sb).forEach(function (r) {
      var li = make('li'), a = make('a', 'pfas-navtile'), more = make('button', 'pfas-nav-more');
      li.setAttribute('role', 'listitem');   /* the panel's lists have no box (display: contents) */
      a.setAttribute('data-pinned', 'true');
      a.setAttribute('href', purl + '/' + r.url_path);
      a.setAttribute('data-path', r.path);
      a.innerHTML = '<svg aria-hidden="true"><use href="#' + iconOf(r.icon) + '"></use></svg>';
      a.appendChild(make('span', 'pfas-navtile-label', r.label));
      if (r.ambiguous) a.appendChild(make('span', 'pfas-navtile-place', r.place));
      more.setAttribute('type', 'button');
      more.setAttribute('tabindex', '-1');
      more.setAttribute('aria-haspopup', 'menu');
      more.setAttribute('aria-expanded', 'false');
      more.setAttribute('aria-label', 'Row menu');
      li.appendChild(a);
      li.appendChild(more);
      box.appendChild(li);
      if (!before[r.path]) fresh.push(a);
      if (had !== null && r.path === had) back = a;
    });
    /* the list is as many tiles across as it holds, up to three: the panel's width follows */
    box.setAttribute('data-cols', String(Math.max(1, Math.min(pinRows(sb).length, 3))));
    if (pinRows(sb).length) box.removeAttribute('hidden'); else box.setAttribute('hidden', 'hidden');
    if (PFAS.components && PFAS.components.resetNavTiles) PFAS.components.resetNavTiles(box);
    fresh.forEach(function (a) { arrive(a, 'is-arriving'); });
    if (had === null) return;
    /* the focus was in the list: on the same pin, else the first, else Home's first tile */
    var home = box.closest('.pfas-panel-section');
    var to = back || box.querySelector('a.pfas-navtile') || (home && home.querySelector('a.pfas-navtile'));
    if (to) to.focus();
  }
  function syncPinned(sb) {
    var on = {};
    pinRows(sb).forEach(function (r) { on[r.url_path] = true; });
    var box = sb.querySelector('#pfas-nav-pins');
    each(sb, 'a.pfas-navtile', function (a) {
      if (box && box.contains(a)) return;
      var pinned = !!on[a.getAttribute('data-path')];
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
    sb.addEventListener('click', function (e) { railClick(sb, e); tileClick(sb, e); });
    sb.addEventListener('pfas:pin', function (e) { savePin(sb, e); });
    shedCore(sb);
    if (window.MutationObserver) {
      new window.MutationObserver(function () { shedCore(sb); }).observe(sb, { attributes: true, attributeFilter: ['class'] });
    }
    watch();
    if (PFAS.components && PFAS.components.initNavTiles) PFAS.components.initNavTiles(sb);
    placeMark(sb, false);
    /* the rail's buttons change size with the width and the web font */
    window.addEventListener('resize', function () { placeMark(sb, false); });
    var rail = sb.querySelector('.pfas-rail');
    if (rail && window.ResizeObserver) {
      try { new window.ResizeObserver(function () { placeMark(sb, false); }).observe(rail); } catch (e) {}
    }
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
