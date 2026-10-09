/* The one top toolbar (templates/pfas_topbar.pt) -- loaded on PFAS pages by
   pfas_macros.pt and on core pages by core_overlay_link.pt.

   - dropdowns: a [data-pfas-drop] button toggles its sibling .dropdown-menu
     (no Bootstrap JS: PFAS pages do not load it; on core pages the buttons
     carry no data-toggle, so Bootstrap leaves them alone);
   - menu button: PFAS pages collapse their panel, core pages the sidebar;
   - core pages: an H1 that only repeats the bar's title is hidden, so the
     title sits in the bar once (6C); an H1 that says something
     else (a batch's "Samples" listing) stays as the section heading. */
(function () {
  function closeAll(except) {
    /* only the bar's own menus: core's Bootstrap dropdowns (a sample's
       workflow menu) open and close themselves */
    var open = document.querySelectorAll('#pfas-topbar [data-pfas-drop] + .dropdown-menu.show');
    for (var i = 0; i < open.length; i++) {
      if (open[i] !== except) open[i].classList.remove('show');
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
    menu.classList.toggle('show');
    btn.setAttribute('aria-expanded', menu.classList.contains('show') ? 'true' : 'false');
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeAll(null);
  });
  window.addEventListener('resize', function () { closeAll(null); });

  window.pfasTopbarToggle = function () {
    if (window.pfasTogglePanel && document.getElementById('pfas-shell')) {
      window.pfasTogglePanel();
    } else if (window.pfasSidebarCollapseToggle) {
      window.pfasSidebarCollapseToggle();
    }
  };

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

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c];
    });
  }
  function links() { return box.querySelectorAll('a.pfas-search-hit'); }
  function setActive(i) {
    var l = links();
    if (!l.length) { active = -1; return; }
    active = (i + l.length) % l.length;
    for (var k = 0; k < l.length; k++) l[k].classList.toggle('active', k === active);
    l[active].scrollIntoView({block: 'nearest'});
  }
  function close() { box.hidden = true; active = -1; form.classList.remove('open'); }
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
    box.hidden = false; form.classList.add('open'); active = -1;
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
  input.addEventListener('focus', function () { if (input.value.trim().length >= 2 && box.innerHTML) { box.hidden = false; form.classList.add('open'); } });
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
      e.preventDefault(); input.focus(); input.select();
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

