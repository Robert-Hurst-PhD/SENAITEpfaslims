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
      var html = cols.map(function(col) {
        var val = row[col.name] != null ? row[col.name] : '';
        var itype = col.type === 'date' ? 'date' : (col.type === 'number' ? 'number' : 'text');
        return '\x3ctd\x3e\x3cinput type="' + itype + '" value="' + _esc(val) + '"'
          + ' oninput="TABLE_DATA[\'' + fname + '\'][' + ri + '][\'' + col.name + '\']=this.value;dynSyncTable(\'' + fname + '\')"'
          + '/\x3e\x3c/td\x3e';
      }).join('');
      html += '\x3ctd\x3e\x3cbutton type="button" class="btn-del-row"'
            + ' onclick="dynDelRow(\'' + fname + '\',' + ri + ')"\x3e\x26#215;\x3c/button\x3e\x3c/td\x3e';
      tr.innerHTML = html;
      tbody.appendChild(tr);
    });
    dynSyncTable(fname);
  }

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
      inp.addEventListener('input', function() {
        var q = inp.value.trim();
        if (q.length < 1) { hideDynAc(inp); return; }
        var url = inp.getAttribute('data-ac') + '?q=' + encodeURIComponent(q);
        var lotType = inp.getAttribute('data-ac-type');
        if (lotType) url += '\x26type=' + encodeURIComponent(lotType);
        fetch(url)
          .then(function(r){ return r.json(); })
          .then(function(items){ showDynAc(inp, items); })
          .catch(function(){ hideDynAc(inp); });
      });
      inp.addEventListener('blur', function() {
        setTimeout(function(){ hideDynAc(inp); }, 220);
      });
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
  });
