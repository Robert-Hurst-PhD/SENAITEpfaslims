/* PFAS logbook runtime: dynamic tables, GLP corrections wiring, and the
 * lot / reagent autocomplete.
 *
 * Shared by the concise form (logbook_dynamic.pt) and the guided step view
 * (logbook_guided.pt). Both pages define SAVED_DATA and FIELD_SCHEMA in a
 * tiny inline block, then load this file.
 *
 * Lives in a static resource rather than inline in the templates: Chameleon
 * parses inline <script> bodies as markup and chokes on bare "<", "&" and
 * "&&", which is why the original carried \x3c / \x26 escapes.
 *
 * Guided mode renders only ONE step's fields, so every lookup here must
 * tolerate an absent element — dynRenderTable and initDynAutocomplete both
 * bail out when their nodes are missing, which makes them step-safe as-is.
 */
  /* ── Table widget ── */
  var TABLE_DATA = {};
  FIELD_SCHEMA.forEach(function(f) {
    if (f.type !== 'table') return;
    var saved = SAVED_DATA[f.name];
    if (Array.isArray(saved) && saved.length) {
      TABLE_DATA[f.name] = saved;
    } else if (f.default_rows && f.default_rows.length) {
      TABLE_DATA[f.name] = f.default_rows.map(function(r){ return Object.assign({}, r); });
    } else {
      TABLE_DATA[f.name] = [];
    }
  });

  function _esc(s) {
    return String(s == null ? '' : s)
      .replace(/\x26/g, '\x26amp;').replace(/"/g, '\x26quot;').replace(/\x3c/g, '\x26lt;');
  }

  function dynRenderTable(fname) {
    var f = null;
    for (var i = 0; i < FIELD_SCHEMA.length; i++) {
      if (FIELD_SCHEMA[i].name === fname) { f = FIELD_SCHEMA[i]; break; }
    }
    if (!f) return;
    var cols = f.columns || [];
    var rows = TABLE_DATA[fname] || [];
    var tbody = document.getElementById('tbody-' + fname);
    if (!tbody) return;
    tbody.innerHTML = '';
    rows.forEach(function(row, ri) {
      var tr = document.createElement('tr');
      /* A row struck as not-applicable stays visible and readable — the paper
         logbook convention. readonly (not disabled) keeps the text legible and
         selectable; the cell inputs carry no name attribute either way, since
         values reach the server through the hidden <fname>_json. */
      var na = !!row._na;
      if (na) { tr.className = 'row-na'; }
      var html = cols.map(function(col) {
        var val = row[col.name] != null ? row[col.name] : '';
        var itype = col.type === 'date' ? 'date' : (col.type === 'number' ? 'number' : 'text');
        return '\x3ctd\x3e\x3cinput type="' + itype + '" value="' + _esc(val) + '"'
          + (na ? ' readonly="readonly"' : '')
          + ' oninput="TABLE_DATA[\'' + fname + '\'][' + ri + '][\'' + col.name + '\']=this.value;dynSyncTable(\'' + fname + '\')"'
          + '/\x3e\x3c/td\x3e';
      }).join('');
      html += '\x3ctd class="col-actions"\x3e'
            + '\x3cbutton type="button" class="btn-na-row"'
            + ' aria-pressed="' + (na ? 'true' : 'false') + '"'
            + ' title="' + (na ? 'Undo not-applicable' : 'Mark as not prepared this session') + '"'
            + ' onclick="dynToggleNA(\'' + fname + '\',' + ri + ')"\x3e'
            + (na ? '\x26#8634;' : 'N/A') + '\x3c/button\x3e';
      if (!na) {
        html += '\x3cbutton type="button" class="btn-del-row"'
             + ' onclick="dynDelRow(\'' + fname + '\',' + ri + ')"\x3e\x26#215;\x3c/button\x3e';
      }
      if (na) {
        var who = row._na_by || '';
        var when = row._na_at || '';
        html += '\x3cdiv class="row-na-note"\x3eN/A'
             + (who ? ' \x26middot; ' + _esc(who) : '')
             + (when ? ' \x26middot; ' + _esc(when) : '')
             + '\x3c/div\x3e';
      }
      html += '\x3c/td\x3e';
      tr.innerHTML = html;
      tbody.appendChild(tr);
    });
    dynSyncTable(fname);
  }

  /* Strike a row as not-applicable, or undo it.
     Only the flag is set here — who/when are stamped server-side on save, so
     they cannot be forged and the analyst types nothing. Undo must clear ALL
     THREE keys, otherwise a later re-strike would carry a stale name and date,
     which is a worse record than none. */
  window.dynToggleNA = function(fname, i) {
    var rows = TABLE_DATA[fname];
    if (!rows || !rows[i]) return;
    if (rows[i]._na) {
      delete rows[i]._na;
      delete rows[i]._na_by;
      delete rows[i]._na_at;
    } else {
      rows[i]._na = true;
    }
    dynRenderTable(fname);
  };

  window.dynAddRow = function(fname) {
    var f = null;
    for (var i = 0; i < FIELD_SCHEMA.length; i++) {
      if (FIELD_SCHEMA[i].name === fname) { f = FIELD_SCHEMA[i]; break; }
    }
    if (!f) return;
    var empty = {};
    (f.columns || []).forEach(function(c){ empty[c.name] = ''; });
    TABLE_DATA[fname] = TABLE_DATA[fname] || [];
    TABLE_DATA[fname].push(empty);
    dynRenderTable(fname);
  };

  function dynDelRow(fname, i) {
    if (TABLE_DATA[fname]) {
      TABLE_DATA[fname].splice(i, 1);
      dynRenderTable(fname);
    }
  }

  function dynSyncTable(fname) {
    var inp = document.getElementById(fname + '_json');
    if (inp) inp.value = JSON.stringify(TABLE_DATA[fname] || []);
  }

  /* ── Autocomplete (lot_ref / reagent_ref) ── */
  function initDynAutocomplete() {
    document.querySelectorAll('[data-ac]').forEach(function(inp) {
      var timer = null;
      inp.addEventListener('input', function() {
        markLotEdited(inp);
        var q = inp.value.trim();
        if (q.length < 1) { hideDynAc(inp); return; }
        /* debounce: the endpoint resolves parent-tightened expiry per record,
           so a request per keystroke is wasteful. */
        if (timer) { clearTimeout(timer); }
        timer = setTimeout(function() {
          var url = inp.getAttribute('data-ac') + '?q=' + encodeURIComponent(q);
          var lotType = inp.getAttribute('data-ac-type');
          if (lotType) url += '\x26type=' + encodeURIComponent(lotType);
          fetch(url)
            .then(function(r){ return r.json(); })
            .then(function(items){ showDynAc(inp, items); })
            .catch(function(){ hideDynAc(inp); });
        }, 180);
      });
      inp.addEventListener('blur', function() {
        setTimeout(function(){ hideDynAc(inp); }, 220);
      });
    });
  }

  /* ── Default an empty lot box to the most recent usable lot ──────────────
   * Server computes which lot (see lot_defaults_json); the client only fills
   * boxes that are EMPTY, so a saved lot or one the analyst just typed is
   * never overwritten. The value is real and editable — it posts as typed.
   */
  function markLotEdited(inp) {
    if (inp.getAttribute('data-lot-default')) {
      inp.removeAttribute('data-lot-default');
      var hint = inp.parentNode && inp.parentNode.querySelector('.lot-default-hint');
      if (hint) { hint.parentNode.removeChild(hint); }
    }
  }

  function applyLotDefaults() {
    var defaults = window.LOT_DEFAULTS || {};
    document.querySelectorAll('[data-ac-type]').forEach(function(inp) {
      if (inp.value) { return; }                       // never overwrite
      var d = defaults[inp.getAttribute('data-ac-type') || ''];
      if (!d || !d.lot_number) { return; }
      inp.value = d.lot_number;
      inp.setAttribute('data-lot-default', '1');
      if (inp.parentNode && !inp.parentNode.querySelector('.lot-default-hint')) {
        var hint = document.createElement('span');
        hint.className = 'lot-default-hint';
        hint.textContent = 'most recent' +
          (d.expiry_date ? ' · exp ' + d.expiry_date : '');
        inp.parentNode.appendChild(hint);
      }
    });
  }

  function showDynAc(inp, items) {
    var dd = document.getElementById('ac-' + inp.id);
    if (!dd) return;
    dd.innerHTML = '';
    if (!items.length) { dd.classList.remove('open'); return; }
    items.slice(0, 12).forEach(function(item) {
      var label = item.lot_number || item.name || '';
      var sub   = item.expiry_date ? 'exp: ' + item.expiry_date
                : (item.supplier ? item.supplier : '');
      var div = document.createElement('div');
      div.className = 'lot-ac-item';
      div.innerHTML = '\x3cspan\x3e' + _esc(label) + '\x3c/span\x3e'
        + (sub ? ' \x3cspan class="lot-ac-sub"\x3e' + _esc(sub) + '\x3c/span\x3e' : '');
      div.addEventListener('mousedown', function(e) {
        e.preventDefault();
        inp.value = label;
        hideDynAc(inp);
      });
      dd.appendChild(div);
    });
    dd.classList.add('open');
  }

  function hideDynAc(inp) {
    var dd = document.getElementById('ac-' + inp.id);
    if (dd) dd.classList.remove('open');
  }

  /* ── Init ── */
  document.addEventListener('DOMContentLoaded', function() {
    /* Render tables */
    FIELD_SCHEMA.forEach(function(f) {
      if (f.type === 'table') dynRenderTable(f.name);
    });
    /* GLP corrections */
    if (window.initCorrections) initCorrections(SAVED_DATA);
    /* Autocomplete */
    initDynAutocomplete();
    /* Pre-fill empty lot boxes with the most recent usable lot */
    applyLotDefaults();
  });
