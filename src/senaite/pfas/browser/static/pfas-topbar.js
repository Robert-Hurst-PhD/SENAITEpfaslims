/* The one top toolbar (templates/pfas_topbar.pt) -- loaded on PFAS pages by
   pfas_macros.pt and on core pages by core_overlay_link.pt.

   - dropdowns: a [data-pfas-drop] button toggles its sibling .dropdown-menu
     (no Bootstrap JS: PFAS pages do not load it; on core pages the buttons
     carry no data-toggle, so Bootstrap leaves them alone);
   - menu button: it asks PFAS.nav (pfas-sidebar.js), which folds and opens
     the panel on PFAS and core pages alike; a page drawn without the
     navigation has no PFAS.nav of its own, so the button does nothing there;
     in the head it puts the session's fold on the root element, so the
     first paint is already folded;
   - core pages: an H1 that only repeats the bar's title is hidden, so the
     title sits in the bar once (6C); an H1 that says something
     else (a batch's "Samples" listing) stays as the section heading. */
(function () {
  var PFAS = window.PFAS = window.PFAS || {};
  PFAS.nav = PFAS.nav || { toggle: function () {} };
  /* the wide screen's fold, from the session, before the first paint
     (pfas-sidebar.css html.pfas-panel-folded; PFAS.nav keeps it in step) */
  try {
    if (window.sessionStorage.getItem('pfas_panel_collapsed') === '1') document.documentElement.classList.add('pfas-panel-folded');
  } catch (e) {}
  /* a menu closed is closed at once (its button says so) and fades out
     before it goes (pfas-components.css; at once with reduced motion) */
  function motion() { return PFAS.components && PFAS.components.motion; }
  function shown(menu) { return menu.classList.contains('show') && !menu.classList.contains('is-leaving'); }
  function hide(menu) {
    var m = motion(), btn = menu.parentNode && menu.parentNode.querySelector('[data-pfas-drop]');
    if (btn) btn.setAttribute('aria-expanded', 'false');
    if (!shown(menu)) return;
    if (m) m.leave(menu, 'is-leaving', function () { menu.classList.remove('show'); });
    else menu.classList.remove('show');
  }
  function closeAll(except) {
    /* only the bar's own menus: core's Bootstrap dropdowns (a sample's
       workflow menu) open and close themselves */
    var open = document.querySelectorAll('#pfas-topbar [data-pfas-drop] + .dropdown-menu.show');
    for (var i = 0; i < open.length; i++) {
      if (open[i] !== except) hide(open[i]);
    }
  }

  document.addEventListener('click', function (e) {
    var btn = e.target.closest ? e.target.closest('#pfas-topbar [data-pfas-drop]') : null;
    if (!btn) {
      if (!(e.target.closest && e.target.closest('#pfas-topbar .dropdown-menu'))) closeAll(null);
      return;
    }
    e.preventDefault();
    e.stopPropagation();
    var menu = btn.parentNode.querySelector('.dropdown-menu');
    if (!menu) return;
    closeAll(menu);
    if (shown(menu)) {
      hide(menu);
    } else {
      if (motion()) motion().stay(menu, 'is-leaving');
      menu.classList.add('show');
      btn.setAttribute('aria-expanded', 'true');
    }
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeAll(null);
  });
  window.addEventListener('resize', function () { closeAll(null); });

  function coreTitle() {
    if (document.body.classList.contains('pfas-app')) return;
    var title = document.getElementById('pfas-topbar-title');
    var h1 = document.querySelector('#content h1, .listing-title-viewlet h1, h1.documentFirstHeading');
    if (!title || !h1) return;
    var text = (h1.textContent || '').replace(/\s+/g, ' ').trim();
    var bar = (title.textContent || '').replace(/\s+/g, ' ').trim();
    if (!text || text.toLowerCase() !== bar.toLowerCase()) return;
    h1.classList.add('pfas-h1-in-topbar');
    var icon = h1.parentNode && h1.parentNode.querySelector('img');
    if (icon && h1.parentNode.classList.contains('listing-title-viewlet')) {
      icon.parentNode.classList.add('pfas-h1-in-topbar');
    }
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', coreTitle);
  } else {
    coreTitle();
  }
})();


/* ── Site search in the bar (GitHub's header pattern) ──────────
   "/" focuses the box from anywhere but a field; typing asks @@pfas-search
   (format=json) after a short pause and draws the groups it returns; arrows
   move, Enter opens the highlighted result or, with none, the full results
   page; Esc closes. Results are links: middle-click opens a new tab.
   Set up once the page is parsed: core pages load this script in <head>. */
function pfasSearchInit() {
  var form = document.querySelector('#pfas-topbar .pfas-topbar-search');
  if (!form || form.getAttribute('data-ready')) return;
  form.setAttribute('data-ready', '1');
  var input = form.querySelector('input[name=q]');
  var box = document.getElementById('pfas-search-results');
  var endpoint = form.getAttribute('data-endpoint');
  var timer = null, seq = 0, active = -1;

  var esc = window.PFAS.components.esc;
  function links() { return box.querySelectorAll('a.pfas-search-hit'); }
  function setActive(i) {
    var l = links();
    if (!l.length) { active = -1; return; }
    active = (i + l.length) % l.length;
    for (var k = 0; k < l.length; k++) l[k].classList.toggle('active', k === active);
    l[active].scrollIntoView({block: 'nearest'});
  }
  /* the results box fades in when it opens and out when it closes; drawn
     again while open (typing), it stays as it is */
  var motion = window.PFAS.components.motion;
  function show() { if (motion) motion.stay(box, 'is-leaving'); box.hidden = false; form.classList.add('open'); }
  function close() {
    active = -1; form.classList.remove('open');
    if (box.hidden) return;
    if (motion) motion.leave(box, 'is-leaving', function () { box.hidden = true; });
    else box.hidden = true;
  }
  function draw(data) {
    var q = input.value.trim();
    if (!data.groups || !data.groups.length) {
      box.innerHTML = '<div class="pfas-search-empty">Nothing found for “' + esc(q) + '”</div>';
    } else {
      var html = '';
      data.groups.forEach(function (g) {
        html += '<div class="pfas-search-group">' + esc(g.label) + '</div>';
        g.hits.forEach(function (i) {
          html += '<a class="pfas-search-hit" role="option" href="' + esc(i.url) + '"><span class="pfas-search-title">' +
                  esc(i.title) + '</span>' + (i.subtitle ? '<span class="pfas-search-sub">' + esc(i.subtitle) + '</span>' : '') + '</a>';
        });
      });
      html += '<a class="pfas-search-hit pfas-search-all" href="' + esc(data.more) + '">All results for “' + esc(q) + '”</a>';
      box.innerHTML = html;
    }
    show(); active = -1;
  }
  function run() {
    var q = input.value.trim();
    if (q.length < 2) { close(); return; }
    var mine = ++seq;
    fetch(endpoint + '?format=json&q=' + encodeURIComponent(q), {credentials: 'same-origin'})
      .then(function (r) { return r.json(); })
      .then(function (d) { if (mine === seq) draw(d); })
      .catch(function () {});
  }
  input.addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(run, 200); });
  input.addEventListener('focus', function () { if (input.value.trim().length >= 2 && box.innerHTML) show(); });
  input.addEventListener('keydown', function (e) {
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive(active + 1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(active - 1); }
    else if (e.key === 'Enter' && active >= 0) { e.preventDefault(); links()[active].click(); }
    else if (e.key === 'Escape') { close(); input.blur(); document.body.classList.remove('pfas-search-mobile'); }
  });
  document.addEventListener('keydown', function (e) {
    var t = e.target, tag = (t && t.tagName) || '';
    /* SENAITE's listings autofocus their own search box: an empty field the
       page focused is not someone typing, so "/" still opens site search */
    var idle = t && t.hasAttribute && t.hasAttribute('autofocus') && !t.value;
    if (e.key === '/' && t !== input && (idle || (!/INPUT|TEXTAREA|SELECT/.test(tag) && !(t && t.isContentEditable)))) {
      e.preventDefault(); document.body.classList.add('pfas-search-mobile'); input.focus(); input.select();   /* folded to its icon: the box opens first */
    }
  });
  document.addEventListener('click', function (e) {
    if (form.contains(e.target) || (e.target.closest && e.target.closest('.pfas-topbar-search-toggle'))) return;
    close(); document.body.classList.remove('pfas-search-mobile');
  });
  window.pfasSearchOpen = function () {          /* phone: the icon opens the box */
    document.body.classList.add('pfas-search-mobile'); input.focus();
  };
}
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', pfasSearchInit);
} else {
  pfasSearchInit();
}

/* A session that timed out: a background request -- a Save, a
   search, a listing refresh -- is answered with the login page, and the page
   would break or seem to do nothing. Send the person to sign in, and back to
   this page afterwards. Covers fetch and XMLHttpRequest (core listings). */
(function () {
  if (window.__pfasSessionWatch) return;
  window.__pfasSessionWatch = true;
  var LOGIN = /\/(login|login_form|require_login)(\?|$)/;
  function onLoginPage() { return LOGIN.test(location.pathname + '?'); }
  function toLogin(url) {
    if (onLoginPage()) return;
    var base = String(url).split('?')[0];
    base = base.replace(/\/acl_users\/credentials_cookie_auth\/require_login$/, '/login')
               .replace(/\/login_form$/, '/login');
    location.href = base + '?came_from=' + encodeURIComponent(location.href);
  }
  if (window.fetch) {
    var origFetch = window.fetch;
    window.fetch = function () {
      return origFetch.apply(this, arguments).then(function (resp) {
        try { if (resp && resp.redirected && LOGIN.test(resp.url)) toLogin(resp.url); } catch (e) {}
        return resp;
      });
    };
  }
  if (window.XMLHttpRequest) {
    var origSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.send = function () {
      this.addEventListener('load', function () {
        try { if (this.responseURL && LOGIN.test(this.responseURL)) toLogin(this.responseURL); } catch (e) {}
      });
      return origSend.apply(this, arguments);
    };
  }
}());

/* A registered lab terminal: after 10
   minutes without activity the person is signed out, so the next person's
   work is never recorded under their name. The bar carries the seconds
   (data-terminal-idle) only on a registered terminal. */
(function () {
  function start() {
    var bar = document.getElementById('pfas-topbar');
    var secs = bar && Number(bar.getAttribute('data-terminal-idle'));
    if (!secs) return;
    var target = bar.getAttribute('data-badge-signin') + '?idle=1';
    var timer;
    function reset() {
      clearTimeout(timer);
      timer = setTimeout(function () { location.href = target; }, secs * 1000);
    }
    ['mousemove', 'mousedown', 'keydown', 'touchstart', 'scroll', 'wheel'].forEach(function (ev) {
      document.addEventListener(ev, reset, { passive: true });
    });
    reset();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
}());

/* Accessibility: a <label> written beside its field
   rather than tied to it (325 of them) names nothing for a screen reader --
   tie each to the field that follows it; and say a page's error or saved
   message aloud when it appears. */
(function () {
  var FIELD = 'input:not([type=hidden]), select, textarea';
  var seq = 0;
  function tie(label) {
    if (label.htmlFor || label.querySelector(FIELD)) return;
    var el = label.nextElementSibling;
    while (el && !el.matches(FIELD) && !el.querySelector(FIELD) && el.tagName !== 'LABEL') el = el.nextElementSibling;
    var field = el && el.tagName !== 'LABEL' ? (el.matches(FIELD) ? el : el.querySelector(FIELD)) : null;
    if (!field && label.parentElement) {
      var all = label.parentElement.querySelectorAll(FIELD);
      if (all.length === 1) field = all[0];
    }
    if (!field || field.labels && field.labels.length) return;
    if (!field.id) field.id = 'pfas-f-' + (++seq);
    label.htmlFor = field.id;
  }
  function start() {
    Array.prototype.forEach.call(document.querySelectorAll('label'), tie);
    Array.prototype.forEach.call(document.querySelectorAll(
        '.alert-error, .alert-danger, .bench-bad, .portalMessage.error'), function (e) {
      if (!e.getAttribute('role')) e.setAttribute('role', 'alert');
    });
    Array.prototype.forEach.call(document.querySelectorAll(
        '.alert-success, .alert-info, .portalMessage.info'), function (e) {
      if (!e.getAttribute('role')) e.setAttribute('role', 'status');
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
}());


/* Opening a form moves the keyboard into it: a button that reveals a form
   or dialog (New Reagent, New Deviation...) left focus on the button, so a
   keyboard user had to hunt for the fields it opened. After such a click,
   the first field that has just become visible gets the focus. A tab, a
   step or another segmented choice only changes what is shown, and a Help
   button opens the panel beside the page: neither opens a form, so nothing
   is focused for them and the focus stays where the person put it. */
(function () {
  function opensNoForm(btn) {
    return !!(btn.closest('.pfas-seg, [role=tablist]') || btn.getAttribute('role') === 'tab' ||
              btn.classList.contains('btn-help'));
  }
  var FIELD = 'input:not([type=hidden]):not([disabled]), select:not([disabled]), textarea:not([disabled])';
  function visible(el) {
    return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  }
  function shown() {
    var out = [];
    Array.prototype.forEach.call(document.querySelectorAll(FIELD), function (f) {
      if (visible(f) && !f.closest('#pfas-topbar, #sidebar')) out.push(f);
    });
    return out;
  }
  document.addEventListener('click', function (e) {
    var btn = e.target.closest ? e.target.closest('button, a.btn, a.btn-sm, [role=button]') : null;
    if (!btn || btn.type === 'submit' || btn.closest('form') && btn.type !== 'button') return;
    if (opensNoForm(btn)) return;
    var before = shown();
    setTimeout(function () {
      if (document.activeElement && document.activeElement !== btn &&
          document.activeElement !== document.body) return;   /* the page moved focus itself */
      var now = shown().filter(function (f) { return before.indexOf(f) < 0; });
      if (now.length) now[0].focus();
    }, 80);
  }, true);
}());


/* Accessibility of core listings: senaite.app.listing draws checkboxes,
   icon buttons and selects with no accessible name, and redraws its rows on
   every sort, page and search. On core pages, name each one from what the row or control
   already shows; only attributes the listing does not set are touched, and
   a name the page already gives is kept. */
(function () {
  function txt(el) { return el ? (el.textContent || '').replace(/\s+/g, ' ').trim() : ''; }
  function named(el) {
    return el.hasAttribute('aria-label') || el.hasAttribute('aria-labelledby') ||
           (el.labels && el.labels.length);
  }
  function name(el, label) { if (label && !named(el)) el.setAttribute('aria-label', label); }
  /* a row is named by its identifying column (the sample id, the analysis'
     service, the worksheet or client title), else by its first link, else
     by its first cell with text */
  var KEY_COLS = ['getId', 'Service', 'Title', 'title', 'getFullname', 'Fullname'];
  function rowName(row) {
    if (!row) return '';
    for (var c = 0; c < KEY_COLS.length; c++) {
      var cell = row.querySelector('td.' + KEY_COLS[c]);
      if (cell && txt(cell)) return txt(cell);
    }
    var links = row.querySelectorAll('td a');
    for (var i = 0; i < links.length; i++) if (txt(links[i])) return txt(links[i]);
    var cells = row.querySelectorAll('td');
    for (var k = 0; k < cells.length; k++) {
      if (!cells[k].querySelector('input, select') && txt(cells[k])) return txt(cells[k]);
    }
    return '';
  }
  var ICONS = {'fa-search': 'Search', 'fa-undo': 'Clear search'};
  function label(root) {
    Array.prototype.forEach.call(root.querySelectorAll('input[type=checkbox][name=select_all]'), function (c) {
      name(c, 'Select all rows');
    });
    Array.prototype.forEach.call(root.querySelectorAll('input[type=checkbox][name="uids:list"]'), function (c) {
      var r = rowName(c.closest('tr'));
      name(c, r ? 'Select ' + r : 'Select row');
    });
    Array.prototype.forEach.call(root.querySelectorAll('button'), function (b) {
      if (txt(b)) return;
      var i = b.querySelector('i');
      if (!i) return;
      for (var k in ICONS) if (i.classList.contains(k)) { name(b, ICONS[k]); return; }
    });
    Array.prototype.forEach.call(root.querySelectorAll('a.pull-right'), function (a) {
      if (!txt(a) && a.querySelector('i.fa-ellipsis-h')) name(a, 'Configure table columns');
    });
    Array.prototype.forEach.call(root.querySelectorAll('button img, a.btn img'), function (img) {
      var host = img.closest('button, a');
      if (!img.hasAttribute('alt') && txt(host)) img.setAttribute('alt', '');
    });
    Array.prototype.forEach.call(root.querySelectorAll('select'), function (s) {
      if (named(s)) return;
      var first = s.options && s.options.length ? s.options[0] : null;
      if (s.title) {
        var r = rowName(s.closest('tr'));
        name(s, r ? s.title + ' for ' + r : s.title);
      } else if (first && first.value === '' && txt(first)) {
        name(s, txt(first).replace(/^Select\s+/i, '').replace(/^./, function (c) { return c.toUpperCase(); }));
      }
    });
    Array.prototype.forEach.call(root.querySelectorAll('input[name=ar_count]'), function (n) {
      name(n, 'Number of samples to add');
    });
    Array.prototype.forEach.call(root.querySelectorAll('.input-group input[type=text][size="3"]'), function (n) {
      name(n, 'Rows per page');
    });
  }
  window.pfasLabelListings = label;
  var queued = false;
  function soon() {
    if (queued) return;
    queued = true;
    (window.requestAnimationFrame || setTimeout)(function () { queued = false; label(document); });
  }
  function start() {
    if (document.body.classList.contains('pfas-app')) return;   /* core pages only */
    /* core pages have no main landmark: the content column is it; and of
       their three <footer>s only the outermost is the page footer */
    var col = document.getElementById('portal-column-content');
    if (col && !document.querySelector('main, [role=main]')) col.setAttribute('role', 'main');
    Array.prototype.forEach.call(document.querySelectorAll(
        '#portal-column-content footer, footer footer'), function (f) {
      if (!f.getAttribute('role')) f.setAttribute('role', 'none');
    });
    label(document);
    if (window.MutationObserver) {
      new MutationObserver(soon).observe(document.body, {childList: true, subtree: true});
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
}());


/* The notifications bell (bell.py, @@pfas-bell): "For you" and
   "Outstanding actions", fetched once the page has loaded; the count is
   both; with nothing open there is no badge. */
function pfasBellInit() {
  var li = document.querySelector('.pfas-bell[data-endpoint]');
  if (!li) { return; }
  var count = li.querySelector('.pfas-bell-count'), list = li.querySelector('.pfas-bell-list');
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) { e.className = cls; }
    if (text) { e.textContent = text; }
    return e;
  }
  function section(title, entries) {
    if (!entries.length) { return; }
    list.appendChild(el('div', 'dropdown-header', title));
    entries.forEach(function (it) {
      var row = el('div', 'pfas-bell-item is-' + (it.level === 'bad' ? 'bad' : 'warn'));
      var text = el('div', 'pfas-bell-text');
      text.appendChild(el('strong', '', it.title));
      if (it.detail) { text.appendChild(el('span', 'pfas-bell-detail', it.detail)); }
      if (it.at) { text.appendChild(el('span', 'pfas-bell-at', it.at)); }
      row.appendChild(text);
      (it.actions || []).forEach(function (a) {
        var b = el('a', 'btn-sm btn-secondary', a.label);
        b.href = a.url;
        row.appendChild(b);
      });
      list.appendChild(row);
    });
  }
  fetch(li.getAttribute('data-endpoint'), { credentials: 'same-origin' })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (!d || !d.count) { return; }
      count.textContent = d.count > 99 ? '99+' : String(d.count);
      count.hidden = false;
      list.innerHTML = '';
      section('For you', d.for_you || []);
      section('Outstanding actions', d.actions || []);
      if (d.settings_url) {
        var foot = el('div', 'pfas-bell-foot', 'E-mail reminders: ');
        var s = el('a', 'btn-sm btn-secondary', 'System, Notifications');
        s.href = d.settings_url;
        foot.appendChild(s);
        list.appendChild(foot);
      }
    })
    .catch(function () {});
}
if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', pfasBellInit); } else { pfasBellInit(); }

/* ── The slow-page line ──────────────────────────────────────────────────
   A click on a link that leaves this page (or a form sent the browser's
   way): if nothing has painted 300 ms later, a 2 px line under the top bar
   steps to 30 %, then 60 % at 1 s and 80 % at 2.5 s, each step by transform
   on --t-reveal (pfas-topbar.css); it goes with the page. A link the page
   handles itself, one that opens a new tab, a download and a jump within
   the page start nothing. Reduced motion: each step at once. */
(function () {
  var PFAS = window.PFAS = window.PFAS || {};
  var line = null, timers = [];
  var P = PFAS.progress = { STEPS: [[300, 0.3], [1000, 0.6], [2500, 0.8]], GIVE_UP: 15000 };
  var DOWNLOAD = /([?&](export|download|format)=|\.(pdf|csv|xlsx?|zip|json|txt)(\?|$)|-pdf(\?|$)|\/download)/i;
  function bar() {
    if (!line) {
      line = document.createElement('div');
      line.className = 'pfas-progress';
      line.setAttribute('aria-hidden', 'true');
      document.body.appendChild(line);
    }
    return line;
  }
  P.step = function (f) { var b = bar(); b.classList.add('is-on'); b.style.transform = 'scaleX(' + f + ')'; };
  P.stop = function () {
    timers.forEach(function (t) { clearTimeout(t); });
    timers = [];
    if (line) { line.classList.remove('is-on'); line.style.transform = ''; }
  };
  P.start = function () {
    P.stop();
    P.STEPS.forEach(function (s) { timers.push(setTimeout(function () { P.step(s[1]); }, s[0])); });
    timers.push(setTimeout(P.stop, P.GIVE_UP));
  };
  /* does this link take the window to another page? */
  P.leaves = function (a) {
    var href = a.getAttribute('href') || '';
    if (!href || href.charAt(0) === '#' || /^(javascript|mailto|tel):/i.test(href)) return false;
    if (a.hasAttribute('download') || (a.getAttribute('target') && a.getAttribute('target') !== '_self')) return false;
    var u;
    try { u = new URL(href, location.href); } catch (e) { return false; }
    if (u.origin !== location.origin || DOWNLOAD.test(u.pathname + u.search)) return false;
    return !(u.pathname === location.pathname && u.search === location.search && u.hash);
  };
  /* on the window, so every handler on the page has had its say first */
  window.addEventListener('click', function (e) {
    if (e.defaultPrevented || e.button > 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
    var a = e.target && e.target.closest ? e.target.closest('a[href]') : null;
    if (a && P.leaves(a)) P.start();
  });
  window.addEventListener('submit', function (e) {
    var f = e.target;
    if (e.defaultPrevented || (f && f.getAttribute && f.getAttribute('target') && f.getAttribute('target') !== '_self')) return;
    if (f && f.action && DOWNLOAD.test(f.action)) return;
    P.start();
  });
  window.addEventListener('pagehide', P.stop);
  window.addEventListener('pageshow', P.stop);
})();
