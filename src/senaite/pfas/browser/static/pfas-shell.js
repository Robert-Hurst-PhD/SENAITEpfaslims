/* pfas-shell.js -- the PFAS page frame's behaviour (templates/pfas_macros.pt):
   declared collections, the create menu's ?new=, clickable rows,
   row menus, the panel toggle and the logbook correction UI. Loaded at the
   end of the body, before the page's own scripts. */

/* Lab name on the tab: the page's own title, then the laboratory's name once
   (the pfas-lab-name meta of the page frame); nothing when no name is set. */
(function () {
  var meta = document.querySelector('meta[name="pfas-lab-name"]');
  var name = meta ? (meta.getAttribute('content') || '').trim() : '';
  if (!name) return;
  var suffix = ' \u00b7 ' + name;
  var title = document.title || '';
  if (title.slice(-suffix.length) === suffix) return;
  document.title = title + suffix;
})();

/* Declared collections (config_form_macros.pt): "+ Add <noun>" clones the
   template row with the next index; config_forms.parse_collection reads every
   index the form carries. The first row added replaces the empty table's
   line (pfas-empty-row). */
document.addEventListener('click', function (e) {
  var btn = e.target.closest ? e.target.closest('.cf-add-row') : null;
  if (!btn) return;
  var wrap = btn.closest('.cf-coll-wrap');
  var tpl = wrap && wrap.querySelector('template.cf-row-template');
  var body = wrap && wrap.querySelector('table.cf-coll tbody');
  if (!tpl || !body) return;
  var n = parseInt(btn.getAttribute('data-next'), 10) || 0;
  btn.setAttribute('data-next', String(n + 1));
  var row = tpl.content.firstElementChild.cloneNode(true);
  row.querySelectorAll('[name]').forEach(function (el) {
    el.name = el.name.replace('__NEW__', '__' + n + '__');
  });
  var empty = body.querySelector('tr.pfas-empty-row');
  if (empty) body.removeChild(empty);
  body.appendChild(row);
  var first = row.querySelector('input, select');
  if (first) first.focus();
});

/* "+" create menu targets: ?new=<kind> opens the page's own
   create form, through the hook the page registers as window.pfasOpenNew. */
window.addEventListener('load', function () {
  var m = /[?&]new=([A-Za-z0-9_]+)/.exec(location.search);   /* new=1 too: the Reagent lot entry never opened */
  if (m && typeof window.pfasOpenNew === 'function') window.pfasOpenNew(m[1]);
});

/* A row with data-href opens its record when clicked anywhere but on a
   control of its own (a link, a button, a box, its "+" menu); from the
   keyboard the row is a focusable link (Tab to it, Enter). */
document.querySelectorAll('tr[data-href]').forEach(function (row) {
  row.setAttribute('tabindex', '0');
  row.setAttribute('role', 'link');
});
document.addEventListener('keydown', function (e) {
  if (e.key !== 'Enter' || !e.target.matches || !e.target.matches('tr[data-href]')) return;
  window.location.href = e.target.getAttribute('data-href');
});
document.addEventListener('click', function (e) {
  var row = e.target.closest ? e.target.closest('tr[data-href]') : null;
  if (!row || e.defaultPrevented) return;
  if (e.target.closest('a, button, input, select, textarea, label, summary, details, form')) return;
  if (window.getSelection && String(window.getSelection())) return;   /* selecting text */
  var url = row.getAttribute('data-href');
  if (e.ctrlKey || e.metaKey) { window.open(url, '_blank'); } else { window.location.href = url; }
});

/* Row "More" menus (.row-more): one open at a time; a click elsewhere closes. */
document.addEventListener('click', function (e) {
  var mine = e.target.closest ? e.target.closest('details.row-more') : null;
  document.querySelectorAll('details.row-more[open]').forEach(function (d) {
    if (d !== mine) d.removeAttribute('open');
  });
});

/* ── GLP field correction UI (logbooks) ── */
window.initCorrections = function (savedData) {
  var corr = (savedData && savedData._corrections) || {};
  Object.keys(corr).forEach(function (fname) {
    var c = corr[fname];
    var wrap = document.querySelector('.corr-field[data-field="' + fname + '"]');
    if (!wrap) return;
    wrap.classList.add('has-correction');
    var badge = document.createElement('div');
    badge.className = 'corr-existing';
    var curVal = (savedData[fname] != null ? savedData[fname] : '').toString();
    /* every value the field held, oldest first, each struck through */
    var chain = (c.earlier || []).map(function (e) {
      return '<span class="corr-struck" title="' + _cEsc(e.corrected_by) + ' · ' + _cEsc(e.corrected_at) + '">' +
             _cEsc(e.original) + '</span><span class="corr-arrow">&#8594;</span>';
    }).join('');
    badge.innerHTML = chain +
      '<span class="corr-struck">' + _cEsc(c.original) + '</span>' +
      '<span class="corr-arrow">&#8594;</span>' +
      '<strong>' + _cEsc(curVal) + '</strong>' +
      ' <span class="corr-meta">' + _cEsc(c.corrected_by) +
      ' · ' + _cEsc(c.corrected_at) + '</span>';
    var firstInp = wrap.querySelector('input, textarea, select');
    if (firstInp) wrap.insertBefore(badge, firstInp);
    else wrap.appendChild(badge);
  });
};

window.toggleCorrect = function (fname) {
  var panel = document.getElementById('cp-' + fname);
  if (!panel) return;
  var isOpen = panel.classList.contains('open');
  var mainInp = wrap_inp(fname);
  if (isOpen) {
    panel.classList.remove('open');
    var byInp = document.getElementById('cb-' + fname);
    if (byInp) byInp.value = '';
    var nvInp = document.getElementById('cn-' + fname);
    if (nvInp) nvInp.value = '';
    if (mainInp) mainInp.disabled = false;
  } else {
    panel.classList.add('open');
    var origSpan = document.getElementById('co-' + fname);
    if (origSpan && mainInp) origSpan.textContent = mainInp.value || '(empty)';
    if (mainInp) mainInp.disabled = true;
    var nvInp = document.getElementById('cn-' + fname);
    if (nvInp) { nvInp.value = ''; nvInp.focus(); }
  }
};

function wrap_inp(fname) {
  var w = document.querySelector('.corr-field[data-field="' + fname + '"]');
  return w ? (w.querySelector('input:not([type=hidden]), textarea, select') || null) : null;
}

function _cEsc(s) {
  return (s == null ? '' : String(s))
    .replace(/\x26/g, '&amp;').replace(/\x3c/g, '&lt;').replace(/\x3e/g, '&gt;');
}
