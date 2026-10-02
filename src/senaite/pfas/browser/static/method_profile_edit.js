/* method_profile_edit.js — All JavaScript for @@pfas-method-profile-edit.
 * Kept in a static file so Chameleon's HTML parser never sees the inline
 * </select>, </option>, </div> etc. that appear inside JS string literals.
 * Data flows IN via hidden <input> elements rendered by the TAL template;
 * this script reads/writes them via getElementById().
 */

  function tableToJson(tbodyId, fieldMap) {
    var tbody = document.getElementById(tbodyId);
    if (!tbody) return null;            /* table not on this page: say so, don't guess */
    var rows = tbody.querySelectorAll('tr');
    var result = [];
    rows.forEach(function(row) {
      var obj = {}, empty = true;
      fieldMap.forEach(function(f) {
        var el = row.querySelector('[data-field="' + f.key + '"]');
        if (!el) return;
        var val = el.type === 'checkbox' ? el.checked : el.value.trim();
        /* a blank number is UNSET (null), never 0: 0 is a value -- a 0%
           recovery limit passes or fails everything (GAPS §51) */
        var num = parseFloat(val);
        obj[f.key] = f.type === 'number' ? (isNaN(num) ? null : num) : val;
        if (f.type !== 'bool' && val !== '' && val !== '0') empty = false;
        if (f.type === 'bool') empty = false;
      });
      if (!empty) result.push(obj);
    });
    return result;
  }

  function syncJson(tbodyId, hiddenId, fieldMap) {
    /* Missing table or field: leave the hidden value (the server-rendered
       saved data) alone. Writing "[]" here would wipe the setting. */
    var hidden = document.getElementById(hiddenId);
    var rows = tableToJson(tbodyId, fieldMap);
    if (!hidden || rows === null) return;
    hidden.value = JSON.stringify(rows, null, 2);
  }

  /* Spike levels and recovery tiers: declared grids (R2), server-rendered -- no JS. */

  /* ── Extraction Stages ─────────────────────────── */
  var _stageSeq = 0;
  function addStageCard(s) {
    s = s || {};
    _stageSeq++;
    var id     = 'stage-card-' + _stageSeq;
    var order  = s.order !== undefined ? s.order : _stageSeq;
    var stageId = s.id || '';
    var name   = s.name || '';
    var desc   = s.description || '';
    var roles  = (s.reagent_roles || []).join(', ');
    var equip  = (s.equipment || []).join(', ');
    var cons   = (s.consumables || []).join(', ');
    var crSol  = s.creates_solution ? 'checked' : '';
    var crPed  = s.capture_pedigree ? 'checked' : '';
    var media    = s.media || '';
    var mediaAlt = s.media_alt || '';

    var card = document.createElement('div');
    card.className = 'stage-card';
    card.id = id;
    card.innerHTML =
      '<div class="stage-card-hdr">' +
        '<span class="drag-handle" title="Drag to reorder">&#9776;</span>' +
        '<strong class="stage-card-title">' + (name || 'New Stage') + '</strong>' +
        '<button type="button" class="del-btn" onclick="removeStageCard(\'' + id + '\')">&#215;</button>' +
      '</div>' +
      '<div class="stage-card-body">' +
        '<div class="stage-row">' +
          '<label>Order<input type="number" data-field="order" value="' + order + '" min="1" max="99" style="width:60px" /></label>' +
          '<label>ID (slug)<input type="text" data-field="id" value="' + _esc(stageId) + '" placeholder="pre_setup" style="width:130px" /></label>' +
          '<label>Name<input type="text" data-field="name" value="' + _esc(name) + '" placeholder="Stage name" style="flex:1" /></label>' +
        '</div>' +
        '<div class="stage-row">' +
          '<label class="grow">Description<input type="text" data-field="description" value="' + _esc(desc) + '" placeholder="What happens at this stage" /></label>' +
        '</div>' +
        '<div class="stage-row">' +
          '<label class="grow">Reagent Roles (comma-separated)<input type="text" data-field="reagent_roles" value="' + _esc(roles) + '" placeholder="Methanol (HPLC grade), Acetonitrile, ..." /></label>' +
        '</div>' +
        '<div class="stage-row">' +
          '<label class="grow">Equipment with a serial number (comma-separated)<input type="text" data-field="equipment" value="' + _esc(equip) + '" placeholder="Analytical balance, SPE manifold, ..." /></label>' +
        '</div>' +
        '<div class="stage-row">' +
          '<label class="grow">Consumables, recorded by lot (comma-separated)<input type="text" data-field="consumables" value="' + _esc(cons) + '" placeholder="50 mL centrifuge tubes, LC vials, ..." /></label>' +
        '</div>' +
        '<div class="stage-row" style="gap:20px">' +
          '<label class="cb-label"><input type="checkbox" data-field="creates_solution" ' + crSol + ' /> Creates Solution</label>' +
          '<label class="cb-label"><input type="checkbox" data-field="capture_pedigree" ' + crPed + ' /> Capture Standard Pedigree</label>' +
        '</div>' +
        /* Action GIF/photo shown to the analyst in the Extraction Guide.
           The token rides in a hidden data-field input so syncStageJson()
           picks it up like any other field. */
        '<div class="stage-row stage-media-row" style="gap:12px;align-items:center">' +
          '<input type="hidden" data-field="media" value="' + _esc(media) + '" />' +
          '<input type="hidden" data-field="media_alt" value="' + _esc(mediaAlt) + '" />' +
          '<span class="stage-media-thumb">' +
            (media
              ? '<img alt="" src="' + _esc(window.MP_MEDIA_URL || '') + '?f=' + encodeURIComponent(media) + '" />'
              : '<span class="stage-media-empty">no action image</span>') +
          '</span>' +
          '<label style="flex:1">Action GIF / photo (shown in the Extraction Guide)' +
            '<input type="file" class="stage-media-file" accept=".gif,.png,.jpg,.jpeg" />' +
          '</label>' +
          (media ? '<button type="button" class="del-btn stage-media-clear" title="Remove image">&#215;</button>' : '') +
        '</div>' +
      '</div>';

    card.querySelector('[data-field="name"]').addEventListener('input', function() {
      card.querySelector('.stage-card-title').textContent = this.value || 'New Stage';
      syncStageJson();
    });
    card.querySelectorAll('input').forEach(function(i) {
      if (i.type === 'file') { return; }   // handled below
      i.addEventListener('change', syncStageJson);
      i.addEventListener('input', function() { if (i.type !== 'text') syncStageJson(); });
    });

    /* Stage action image: upload immediately (AJAX) so a rejected file never
       costs the manager their unsaved edits, then store only the token. */
    var fileIn = card.querySelector('.stage-media-file');
    if (fileIn) {
      fileIn.addEventListener('change', function () {
        if (!fileIn.files || !fileIn.files[0]) { return; }
        var fd = new FormData();
        fd.append('action', 'upload');
        fd.append('media', fileIn.files[0]);
        var xhr = new XMLHttpRequest();
        xhr.open('POST', window.MP_MEDIA_URL, true);
        xhr.onload = function () {
          var res = {};
          try { res = JSON.parse(xhr.responseText); } catch (e) { res = {}; }
          if (res.ok && res.token) {
            card.querySelector('[data-field="media"]').value = res.token;
            var altIn = card.querySelector('[data-field="media_alt"]');
            if (altIn && !altIn.value) { altIn.value = fileIn.files[0].name; }
            var thumb = card.querySelector('.stage-media-thumb');
            if (thumb) {
              thumb.textContent = '';
              var img = document.createElement('img');
              img.alt = '';
              img.src = window.MP_MEDIA_URL + '?f=' + encodeURIComponent(res.token);
              thumb.appendChild(img);
            }
            syncStageJson();
          } else {
            window.alert('Upload failed: ' + (res.error || ('HTTP ' + xhr.status)));
          }
        };
        xhr.onerror = function () { window.alert('Upload failed (network).'); };
        xhr.send(fd);
      });
    }
    var clearBtn = card.querySelector('.stage-media-clear');
    if (clearBtn) {
      clearBtn.addEventListener('click', function () {
        card.querySelector('[data-field="media"]').value = '';
        card.querySelector('[data-field="media_alt"]').value = '';
        var thumb = card.querySelector('.stage-media-thumb');
        if (thumb) {
          thumb.textContent = '';
          var sp = document.createElement('span');
          sp.className = 'stage-media-empty';
          sp.textContent = 'no action image';
          thumb.appendChild(sp);
        }
        clearBtn.parentNode.removeChild(clearBtn);
        syncStageJson();
      });
    }

    document.getElementById('stage-list').appendChild(card);
    syncStageJson();
  }

  function removeStageCard(id) {
    var el = document.getElementById(id);
    if (el) { el.parentNode.removeChild(el); renumberStages(); syncStageJson(); }
  }

  function renumberStages() {
    document.getElementById('stage-list').querySelectorAll('.stage-card').forEach(function(card, idx) {
      var inp = card.querySelector('[data-field="order"]');
      if (inp) inp.value = idx + 1;
    });
  }

  function syncStageJson() {
    var cards = document.getElementById('stage-list').querySelectorAll('.stage-card');
    var result = [];
    cards.forEach(function(card) {
      var get = function(f) {
        var el = card.querySelector('[data-field="' + f + '"]');
        return el ? el.value.trim() : '';
      };
      var getBool = function(f) {
        var el = card.querySelector('[data-field="' + f + '"]');
        return el ? el.checked : false;
      };
      var splitCsv = function(s) {
        return s ? s.split(',').map(function(x) { return x.trim(); }).filter(Boolean) : [];
      };
      /* WARNING: this object is rebuilt from scratch on every edit, so any
         stage key WITHOUT a matching [data-field] input above is silently
         dropped on the next profile save. Adding a key here without also
         adding its input in addStageCard() (or vice versa) loses data. */
      result.push({
        id:               get('id') || ('stage_' + (result.length + 1)),
        order:            parseInt(get('order'), 10) || (result.length + 1),
        name:             get('name'),
        description:      get('description'),
        reagent_roles:    splitCsv(get('reagent_roles')),
        equipment:        splitCsv(get('equipment')),
        consumables:      splitCsv(get('consumables')),
        creates_solution: getBool('creates_solution'),
        capture_pedigree: getBool('capture_pedigree'),
        media:            get('media'),
        media_alt:        get('media_alt'),
      });
    });
    document.getElementById('extraction_stages_json').value = JSON.stringify(result, null, 2);
  }

  function _esc(s) {
    return (s || '').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  /* Surrogate Map: a declared table (R2), server-rendered -- no JS. */

  /* ── Per-Analyte Assignments table ───────────────────────────── */

  var _paLabels = {}, _paOrig = {};
  function buildPerAnalyteTable() {
    var tbody = document.getElementById('perAnalyteBody');
    var jsonEl = document.getElementById('per_analyte_json');
    if (!tbody || !jsonEl) return;
    var rows = [];
    try { rows = JSON.parse(jsonEl.value || '[]'); } catch(e) { return; }
    try { _paLabels = JSON.parse((document.getElementById('per_analyte_labels') || {value: '{}'}).value || '{}'); }
    catch (e) { _paLabels = {}; }
    _paOrig = {};
    rows.forEach(function (r) { if (r.analyte) _paOrig[r.analyte] = r; });
    tbody.innerHTML = '';
    rows.forEach(function(row) {
      var tr = document.createElement('tr');
      tr.setAttribute('data-analyte', row.analyte || '');
      tr.innerHTML =
        '<td class="pa-name">' + _esc(_paLabels[row.analyte] || row.analyte || '') + '</td>' +
        '<td><input type="text" class="pa-inp pa-mono" data-field="confirm_ion_mz"' +
          ' value="' + _esc(row.confirm_ion_mz || '') + '" placeholder="413.04>369.00"' +
          ' oninput="syncPerAnalyteJson()" /></td>' +
        '<td><input type="text" class="pa-inp" data-field="notes"' +
          ' value="' + _esc(row.notes || '') + '"' +
          ' oninput="syncPerAnalyteJson()" /></td>';
      tbody.appendChild(tr);
    });
  }

  function syncPerAnalyteJson() {
    var jsonEl = document.getElementById('per_analyte_json');
    if (!jsonEl) return;
    var result = [];
    document.querySelectorAll('#perAnalyteBody tr[data-analyte]').forEach(function(tr) {
      var confirmIon = tr.querySelector('[data-field="confirm_ion_mz"]');
      var notes     = tr.querySelector('[data-field="notes"]');
      /* Edits merge onto the STORED row: rebuilding it from the three inputs
         dropped every other field a row carried (e.g. recovery_tier, which
         spec_sync reads). */
      var orig = _paOrig[tr.getAttribute('data-analyte')] || {};
      var row = {};
      Object.keys(orig).forEach(function (k) {
        if (k !== 'no_labeled_std') row[k] = orig[k];    /* derived now (P4) */
      });
      row.analyte        = tr.getAttribute('data-analyte');
      row.confirm_ion_mz = confirmIon ? confirmIon.value.trim() : '';
      row.notes          = notes     ? notes.value.trim() : '';
      result.push(row);
    });
    jsonEl.value = JSON.stringify(result);
  }

  /* ── Analyte × Matrix Inclusion grid ─────────────────────────── */

  function buildAMIGrid() {
    var gridEl = document.getElementById('amiGridContainer');
    if (!gridEl) return;

    var gridData, inclusion;
    try {
      gridData  = JSON.parse(document.getElementById('ami_grid_data').value  || '{}');
      inclusion = JSON.parse(document.getElementById('analyte_matrix_inclusion_json').value || '{}');
    } catch(e) {
      gridEl.textContent = 'Error loading grid data.';
      return;
    }

    var analytes = gridData.analytes || [];
    var labels   = gridData.analyte_labels || {};
    var matrices = gridData.matrices || [];

    if (!analytes.length || !matrices.length) {
      gridEl.innerHTML = '<em style="color:var(--s-secondary);font-size:12px">No analytes configured for this method.</em>';
      return;
    }

    var html = '<table class="inclusion-grid"><thead><tr>';
    html += '<th class="analyte-col">Analyte</th>';
    matrices.forEach(function(mat, ci) {
      html += '<th>' + _esc(mat) +
        '<span class="ami-col-ctrl">' +
        '<button type="button" class="ami-bulk-btn" title="Check all" onclick="amiColAll(' + ci + ',true)">&#10003;</button>' +
        '<button type="button" class="ami-bulk-btn" title="Uncheck all" onclick="amiColAll(' + ci + ',false)">&#10007;</button>' +
        '</span></th>';
    });
    html += '</tr></thead><tbody>';

    analytes.forEach(function(kw, ri) {
      var label = labels[kw] || kw;
      html += '<tr><td class="analyte-name">' +
        '<button type="button" class="ami-row-btn" title="Toggle row — keyword: ' + _esc(kw) + '" onclick="amiRowToggle(' + ri + ')">' +
        _esc(label) + '</button></td>';
      matrices.forEach(function(mat) {
        var checked = !(inclusion[kw] && inclusion[kw][mat] === false);
        html += '<td class="check-cell">' +
          '<input type="checkbox" class="ami-cb"' +
          ' data-analyte="' + _esc(kw) + '"' +
          ' data-matrix-idx="' + matrices.indexOf(mat) + '"' +
          (checked ? ' checked' : '') +
          ' onchange="syncAMIJson()" /></td>';
      });
      html += '</tr>';
    });

    html += '</tbody></table>';
    gridEl.innerHTML = html;
  }

  function amiColAll(colIdx, state) {
    var rows = document.querySelectorAll('.inclusion-grid tbody tr');
    rows.forEach(function(row) {
      var tds = row.querySelectorAll('td.check-cell');
      var cb = tds[colIdx] && tds[colIdx].querySelector('input[type=checkbox]');
      if (cb) cb.checked = state;
    });
    syncAMIJson();
  }

  function amiRowToggle(rowIdx) {
    var rows = document.querySelectorAll('.inclusion-grid tbody tr');
    var row = rows[rowIdx];
    if (!row) return;
    var cbs = row.querySelectorAll('input[type=checkbox]');
    var anyChecked = Array.prototype.some.call(cbs, function(cb) { return cb.checked; });
    Array.prototype.forEach.call(cbs, function(cb) { cb.checked = !anyChecked; });
    syncAMIJson();
  }

  function syncAMIJson() {
    var cbs = document.querySelectorAll('.ami-cb');
    var gridData;
    try { gridData = JSON.parse(document.getElementById('ami_grid_data').value || '{}'); }
    catch(e) { return; }
    var matrices = gridData.matrices || [];

    var result = {};
    Array.prototype.forEach.call(cbs, function(cb) {
      var a = cb.getAttribute('data-analyte');
      var mi = parseInt(cb.getAttribute('data-matrix-idx'), 10);
      var mat = matrices[mi];
      if (!a || mat === undefined) return;
      if (!result[a]) result[a] = {};
      result[a][mat] = cb.checked;
    });
    document.getElementById('analyte_matrix_inclusion_json').value = JSON.stringify(result);
  }

  document.addEventListener('DOMContentLoaded', function() {
    /* Salt and matrix adjustment factors are declared tables (R2,
       method_profile_sections), server-rendered -- no JS. */
    try {
      var stages = JSON.parse(document.getElementById('extraction_stages_json').value || '[]');
      stages.forEach(function(s) { addStageCard(s); });
    } catch(e) {}
    /* Stage cards reorder by their handle with SortableJS (mouse and touch;
       REUSE_REVIEW U3), then renumber and re-serialise as before. */
    var stageList = document.getElementById('stage-list');
    if (stageList && window.Sortable) {
      Sortable.create(stageList, {
        handle: '.drag-handle', draggable: '.stage-card', animation: 150,
        ghostClass: 'dragging',
        onEnd: function () { renumberStages(); syncStageJson(); }
      });
    }
    buildAMIGrid();
    buildPerAnalyteTable();
  });

  /* Serialise every table into its hidden field before the profile form
     submits. Each runs on its own: the first one threw on every page (its
     table had been replaced by named fields) and silently stopped all the
     others, so their edits never reached the server (GAPS §51). */
  var profileForm = document.getElementById('profile-form');
  if (profileForm) profileForm.addEventListener('submit', function() {
    [syncStageJson,
     syncAMIJson, syncPerAnalyteJson].forEach(function (fn) {
      try { fn(); } catch (e) {
        if (window.console) console.error('method profile: ' + (fn.name || 'sync') + ' failed', e);
      }
    });
  });
