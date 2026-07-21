/* method_profile_edit.js — All JavaScript for @@pfas-method-profile-edit.
 * Kept in a static file so Chameleon's HTML parser never sees the inline
 * </select>, </option>, </div> etc. that appear inside JS string literals.
 * Data flows IN via hidden <input> elements rendered by the TAL template;
 * this script reads/writes them via getElementById().
 */

  function tableToJson(tbodyId, fieldMap) {
    var rows = document.getElementById(tbodyId).querySelectorAll('tr');
    var result = [];
    rows.forEach(function(row) {
      var obj = {}, empty = true;
      fieldMap.forEach(function(f) {
        var el = row.querySelector('[data-field="' + f.key + '"]');
        if (!el) return;
        var val = el.type === 'checkbox' ? el.checked : el.value.trim();
        obj[f.key] = f.type === 'number' ? (parseFloat(val) || 0) : val;
        if (f.type !== 'bool' && val !== '' && val !== '0') empty = false;
        if (f.type === 'bool') empty = false;
      });
      if (!empty) result.push(obj);
    });
    return result;
  }

  function syncJson(tbodyId, hiddenId, fieldMap) {
    document.getElementById(hiddenId).value = JSON.stringify(tableToJson(tbodyId, fieldMap), null, 2);
  }

  var MF_FIELDS = [{key:'matrix',type:'text'},{key:'factor',type:'number'}];
  function addMatrixFactorRow(matrix, factor) {
    var tbody = document.getElementById('matrixFactorsBody');
    var tr = document.createElement('tr');
    tr.innerHTML =
      '<td><input type="text" data-field="matrix" value="' + _esc(matrix||'') + '" placeholder="e.g. milk" /></td>' +
      '<td><input type="number" data-field="factor" step="0.0001" min="0" value="' + (factor!=null?factor:'') + '" placeholder="1.0" /></td>' +
      '<td><button type="button" class="del-btn" onclick="this.closest(\'tr\').remove();syncMatrixFactorsJson()">&#215;</button></td>';
    tbody.appendChild(tr);
    tr.querySelectorAll('input').forEach(function(i) { i.addEventListener('change',syncMatrixFactorsJson); i.addEventListener('input',syncMatrixFactorsJson); });
  }
  function syncMatrixFactorsJson() { syncJson('matrixFactorsBody','matrix_factors_json',MF_FIELDS); }

  var SA_FIELDS = [{key:'analyte',type:'text'},{key:'factor',type:'number'},{key:'source',type:'text'}];
  function addSaltRow(analyte, factor, source) {
    var tbody = document.getElementById('saltAdjBody');
    var tr = document.createElement('tr');
    tr.innerHTML =
      '<td><input type="text" data-field="analyte" value="' + (analyte||'') + '" placeholder="e.g. PFOS" /></td>' +
      '<td><input type="number" data-field="factor" step="0.0001" min="0" max="1" value="' + (factor!=null?factor:'') + '" placeholder="0.9815" /></td>' +
      '<td><input type="text" data-field="source" value="' + (source||'') + '" placeholder="CoA lot #" /></td>' +
      '<td><button type="button" class="del-btn" onclick="this.closest(\'tr\').remove();syncSaltJson()">&#215;</button></td>';
    tbody.appendChild(tr);
    tr.querySelectorAll('input').forEach(function(i) { i.addEventListener('change',syncSaltJson); i.addEventListener('input',syncSaltJson); });
  }
  function syncSaltJson() { syncJson('saltAdjBody','salt_adjustment_factors_json',SA_FIELDS); }

  var EIS_FIELDS = [{key:'analyte',type:'text'},{key:'recovery_min',type:'number'},{key:'recovery_max',type:'number'}];
  function addEisRow(analyte, rmin, rmax) {
    var tbody = document.getElementById('eisOverrideBody');
    if (!tbody) return;
    var tr = document.createElement('tr');
    tr.innerHTML =
      '<td><input type="text" data-field="analyte" value="' + _esc(analyte||'') + '" placeholder="e.g. M2-4:2FTS" /></td>' +
      '<td><input type="number" data-field="recovery_min" step="0.1" min="0" value="' + (rmin!=null?rmin:'') + '" placeholder="20.0" /></td>' +
      '<td><input type="number" data-field="recovery_max" step="0.1" min="0" value="' + (rmax!=null?rmax:'') + '" placeholder="150.0" /></td>' +
      '<td><button type="button" class="del-btn" onclick="this.closest(\'tr\').remove();syncEisJson()">&#215;</button></td>';
    tbody.appendChild(tr);
    tr.querySelectorAll('input').forEach(function(i) { i.addEventListener('change',syncEisJson); i.addEventListener('input',syncEisJson); });
  }
  function syncEisJson() {
    if (document.getElementById('eis_overrides_json')) {
      syncJson('eisOverrideBody','eis_overrides_json',EIS_FIELDS);
    }
  }

  var IS_FIELDS = [{key:'linear',type:'text'},{key:'branched',type:'text'},{key:'reported',type:'text'},{key:'enabled',type:'bool'}];
  function addIsomerRow(linear, branched, reported, enabled) {
    var tbody = document.getElementById('isomerBody');
    var tr = document.createElement('tr');
    var checked = enabled !== false ? 'checked' : '';
    tr.innerHTML =
      '<td><input type="text" data-field="linear"   value="' + (linear||'')   + '" placeholder="lr-PFOS" /></td>' +
      '<td><input type="text" data-field="branched" value="' + (branched||'') + '" placeholder="br-PFOS" /></td>' +
      '<td><input type="text" data-field="reported" value="' + (reported||'') + '" placeholder="PFOS" /></td>' +
      '<td style="text-align:center"><label class="toggle-switch">' +
        '<input type="checkbox" data-field="enabled" ' + checked + ' />' +
        '<span class="toggle-track"></span></label></td>' +
      '<td><button type="button" class="del-btn" onclick="this.closest(\'tr\').remove();syncIsomerJson()">&#215;</button></td>';
    tbody.appendChild(tr);
    tr.querySelectorAll('input').forEach(function(i) { i.addEventListener('change',syncIsomerJson); i.addEventListener('input',syncIsomerJson); });
  }
  function syncIsomerJson() { syncJson('isomerBody','isomer_summation_json',IS_FIELDS); }

  /* ── Spike Levels — per matrix ──────────────────── */

  // QC types that carry spike concentration values.
  // LFSMD shares the same concentration table as LFSM.
  var SPIKE_QC_TYPES = ['LFB', 'LCS', 'LFSM'];
  var SPIKE_QC_LABELS = {LFB: 'LFB', LCS: 'LCS', LFSM: 'LFSM / LFSMD'};

  function _matId(matrix) {
    return matrix.replace(/[^a-zA-Z0-9]/g, '_');
  }

  function _spikeBodyId(matrix, qcType) {
    return 'spikeBody_' + _matId(matrix) + '_' + qcType;
  }

  function _activeSpikeQcTypes() {
    // Return the intersection of SPIKE_QC_TYPES with the method's associated_qc_types.
    var assoc = [];
    try { assoc = JSON.parse((document.getElementById('associated_qc_types_json') || {value:'[]'}).value || '[]'); }
    catch(e) {}
    // LFSMD association → show LFSM spike table (they share levels)
    if (assoc.indexOf('LFSMD') !== -1 && assoc.indexOf('LFSM') === -1) {
      assoc = assoc.concat(['LFSM']);
    }
    return SPIKE_QC_TYPES.filter(function(q) { return assoc.indexOf(q) !== -1; });
  }

  function buildSpikeMatrixSections() {
    var container = document.getElementById('spikeLevelsContainer');
    if (!container) return;

    var gridData = {};
    try { gridData = JSON.parse((document.getElementById('ami_grid_data') || {value:'{}'}).value || '{}'); }
    catch(e) {}
    var matrices = gridData.matrices || [];

    var sl = {};
    try { sl = JSON.parse((document.getElementById('spike_levels_json') || {value:'{}'}).value || '{}'); }
    catch(e) {}

    var activeQcTypes = _activeSpikeQcTypes();

    container.innerHTML = '';
    matrices.forEach(function(matrix) {
      var matData = sl[matrix] || {};
      var matId = _matId(matrix);
      var section = document.createElement('div');
      section.className = 'spike-matrix-section';
      section.setAttribute('data-matrix', matrix);

      var tablesHtml = activeQcTypes.map(function(qcType) {
        var bodyId = _spikeBodyId(matrix, qcType);
        return '<div style="flex:1;min-width:220px">' +
          '<div style="font-weight:700;font-size:12px;margin-bottom:6px">' +
            _esc(SPIKE_QC_LABELS[qcType] || qcType) + '</div>' +
          '<table class="listing" style="width:100%"><thead><tr>' +
            '<th style="width:45%">Level</th><th style="width:40%">ppt</th><th style="width:36px"></th>' +
          '</tr></thead><tbody id="' + bodyId + '"></tbody></table>' +
          '<button type="button" class="btn-add-row" style="margin-top:4px"' +
            ' onclick="addSpikeLevelRow(' + JSON.stringify(matrix) + ',' + JSON.stringify(qcType) + ')">+ Add level</button>' +
          '</div>';
      }).join('');

      section.innerHTML =
        '<div class="spike-matrix-hdr">' + _esc(matrix) + '</div>' +
        '<div style="padding:10px 12px">' +
          '<div style="display:flex;gap:24px;flex-wrap:wrap">' +
            tablesHtml +
          '</div>' +
        '</div>';

      container.appendChild(section);

      activeQcTypes.forEach(function(qcType) {
        (matData[qcType] || []).forEach(function(r) {
          addSpikeLevelRow(matrix, qcType, r.label, r.ppt);
        });
      });
    });
  }

  function addSpikeLevelRow(matrix, qcType, label, ppt) {
    var tbodyId = _spikeBodyId(matrix, qcType);
    var tbody   = document.getElementById(tbodyId);
    if (!tbody) return;
    var tr = document.createElement('tr');
    tr.innerHTML =
      '<td><input type="text" data-spike-matrix="' + _esc(matrix) + '" data-spike-qc="' + _esc(qcType) + '" data-spike-field="label"' +
        ' value="' + _esc(label || '') + '" placeholder="Low" style="width:95%" /></td>' +
      '<td><input type="number" data-spike-matrix="' + _esc(matrix) + '" data-spike-qc="' + _esc(qcType) + '" data-spike-field="ppt"' +
        ' value="' + (ppt != null ? ppt : '') + '" step="any" placeholder="ppt" style="width:95%" /></td>' +
      '<td><button type="button" class="del-btn"' +
        ' onclick="this.closest(\'tr\').remove();syncSpikeLevelsJson()">&#215;</button></td>';
    tbody.appendChild(tr);
    tr.querySelectorAll('input').forEach(function(i) {
      i.addEventListener('change', syncSpikeLevelsJson);
      i.addEventListener('input',  syncSpikeLevelsJson);
    });
  }

  function syncSpikeLevelsJson() {
    var result = {};
    var activeQcTypes = _activeSpikeQcTypes();
    document.querySelectorAll('#spikeLevelsContainer .spike-matrix-section').forEach(function(section) {
      var matrix = section.getAttribute('data-matrix');
      if (!matrix) return;
      result[matrix] = {};
      activeQcTypes.forEach(function(qcType) {
        result[matrix][qcType] = [];
        var tbody = document.getElementById(_spikeBodyId(matrix, qcType));
        if (!tbody) return;
        tbody.querySelectorAll('tr').forEach(function(tr) {
          var lbl   = tr.querySelector('[data-spike-field="label"]');
          var pptEl = tr.querySelector('[data-spike-field="ppt"]');
          var labelVal = lbl   ? lbl.value.trim()   : '';
          var pptVal   = pptEl && pptEl.value.trim() !== '' ? parseFloat(pptEl.value) : null;
          if (labelVal) {
            result[matrix][qcType].push({label: labelVal, ppt: isNaN(pptVal) ? null : pptVal});
          }
        });
      });
    });
    var el = document.getElementById('spike_levels_json');
    if (el) el.value = JSON.stringify(result);
  }

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
    var crSol  = s.creates_solution ? 'checked' : '';
    var crPed  = s.capture_pedigree ? 'checked' : '';

    var card = document.createElement('div');
    card.className = 'stage-card';
    card.id = id;
    card.setAttribute('draggable', 'true');
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
          '<label style="flex:1">Description<input type="text" data-field="description" value="' + _esc(desc) + '" placeholder="What happens at this stage" /></label>' +
        '</div>' +
        '<div class="stage-row">' +
          '<label style="flex:1">Reagent Roles (comma-separated)<input type="text" data-field="reagent_roles" value="' + _esc(roles) + '" placeholder="Methanol (HPLC grade), Acetonitrile, ..." /></label>' +
        '</div>' +
        '<div class="stage-row">' +
          '<label style="flex:1">Equipment (comma-separated)<input type="text" data-field="equipment" value="' + _esc(equip) + '" placeholder="Analytical balance, SPE manifold, ..." /></label>' +
        '</div>' +
        '<div class="stage-row" style="gap:20px">' +
          '<label class="cb-label"><input type="checkbox" data-field="creates_solution" ' + crSol + ' /> Creates Solution</label>' +
          '<label class="cb-label"><input type="checkbox" data-field="capture_pedigree" ' + crPed + ' /> Capture Standard Pedigree</label>' +
        '</div>' +
      '</div>';

    card.querySelector('[data-field="name"]').addEventListener('input', function() {
      card.querySelector('.stage-card-title').textContent = this.value || 'New Stage';
      syncStageJson();
    });
    card.querySelectorAll('input').forEach(function(i) {
      i.addEventListener('change', syncStageJson);
      i.addEventListener('input', function() { if (i.type !== 'text') syncStageJson(); });
    });

    card.addEventListener('dragstart', function(e) {
      e.dataTransfer.setData('text/plain', id);
      card.classList.add('dragging');
    });
    card.addEventListener('dragend', function() {
      card.classList.remove('dragging');
      renumberStages();
      syncStageJson();
    });
    card.addEventListener('dragover', function(e) {
      e.preventDefault();
      var list = document.getElementById('stage-list');
      var dragging = list.querySelector('.dragging');
      if (!dragging || dragging === card) return;
      var rect = card.getBoundingClientRect();
      var mid  = rect.top + rect.height / 2;
      if (e.clientY < mid) {
        list.insertBefore(dragging, card);
      } else {
        list.insertBefore(dragging, card.nextSibling);
      }
    });

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
      result.push({
        id:               get('id') || ('stage_' + (result.length + 1)),
        order:            parseInt(get('order'), 10) || (result.length + 1),
        name:             get('name'),
        description:      get('description'),
        reagent_roles:    splitCsv(get('reagent_roles')),
        equipment:        splitCsv(get('equipment')),
        creates_solution: getBool('creates_solution'),
        capture_pedigree: getBool('capture_pedigree'),
      });
    });
    document.getElementById('extraction_stages_json').value = JSON.stringify(result, null, 2);
  }

  function _esc(s) {
    return (s || '').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  /* ── Recovery Tiers ──────────────────────────────────────────── */

  function _tierChipHtml(val, cssClass, field) {
    return '<span class="tier-chip ' + cssClass + '" data-field="' + field + '" data-val="' + _esc(val) + '">' +
      _esc(val) +
      '<button type="button" class="tier-chip-rm" onclick="removeTierChip(this)">&times;</button>' +
      '</span>';
  }

  function _tierAddSelHtml(allItems, current, field, label) {
    var available = allItems.filter(function(x) { return current.indexOf(x) === -1; });
    var opts = '<option value="">' + _esc(label) + '</option>';
    available.forEach(function(x) { opts += '<option value="' + _esc(x) + '">' + _esc(x) + '</option>'; });
    return '<select class="tier-add-sel" data-field="' + field + '" data-all="' + _esc(JSON.stringify(allItems)) + '"' +
      ' onchange="addTierChip(this)">' + opts + '</select>';
  }

  function _buildTierCard(tier, idx, allAnalytes, allMatrices) {
    var ka  = tier.key_analytes    || [];
    var tm  = tier.tight_matrices  || [];
    var ns  = tier.no_std_analytes || [];

    var kaChips = ka.map(function(v) { return _tierChipHtml(v, '', 'key_analytes'); }).join('');
    var tmChips = tm.map(function(v) { return _tierChipHtml(v, 'mat-chip', 'tight_matrices'); }).join('');
    var nsChips = ns.map(function(v) { return _tierChipHtml(v, 'nostd-chip', 'no_std_analytes'); }).join('');

    return '<div class="tier-card" data-tier-idx="' + idx + '">' +
      '<div class="tier-card-hdr">' +
        '<span class="tier-badge">Tier ' + (idx + 1) + '</span>' +
        '<input type="text" class="tier-desc" value="' + _esc(tier.description || '') + '" placeholder="Describe when this tier applies" />' +
        '<button type="button" class="del-btn" title="Remove tier" onclick="removeTierCard(this)">&#215;</button>' +
      '</div>' +
      '<div class="tier-card-body">' +
        '<div class="tier-limits">' +
          '<label>Min Recovery <input type="number" class="tier-min" step="0.1" min="0" max="100" value="' + (tier.recovery_min != null ? tier.recovery_min : '') + '" oninput="syncRecoveryTiersJson()" /> %</label>' +
          '<label>Max Recovery <input type="number" class="tier-max" step="0.1" min="0" max="200" value="' + (tier.recovery_max != null ? tier.recovery_max : '') + '" oninput="syncRecoveryTiersJson()" /> %</label>' +
          '<label>RSD &#8804; <input type="number" class="tier-rsd" step="0.1" min="0" value="' + (tier.rsd_max != null ? tier.rsd_max : '') + '" oninput="syncRecoveryTiersJson()" /> %</label>' +
        '</div>' +
        '<div class="tier-chipfield" data-field="key_analytes">' +
          '<label>Key Analytes (stricter limits apply to these)</label>' +
          '<div class="tier-chip-row">' + kaChips + _tierAddSelHtml(allAnalytes, ka, 'key_analytes', '+ Add analyte') + '</div>' +
        '</div>' +
        '<div class="tier-chipfield" data-field="tight_matrices">' +
          '<label>Tight Matrices (leave empty = any matrix)</label>' +
          '<div class="tier-chip-row">' + tmChips + _tierAddSelHtml(allMatrices, tm, 'tight_matrices', '+ Add matrix') + '</div>' +
        '</div>' +
        '<div class="tier-chipfield" data-field="no_std_analytes">' +
          '<label>No-Std Analytes (always this tier, no labeled IS)</label>' +
          '<div class="tier-chip-row">' + nsChips + _tierAddSelHtml(allAnalytes, ns, 'no_std_analytes', '+ Add analyte') + '</div>' +
        '</div>' +
      '</div>' +
    '</div>';
  }

  function _tierMeta() {
    var gridData = {};
    try { gridData = JSON.parse((document.getElementById('ami_grid_data') || {value:'{}'}).value || '{}'); }
    catch(e) {}
    return { analytes: gridData.analytes || [], matrices: gridData.matrices || [] };
  }

  function buildRecoveryTiersGrid() {
    var el = document.getElementById('recoveryTiersContainer');
    if (!el) return;

    var tiers = [];
    try { tiers = JSON.parse(document.getElementById('recovery_tiers_json').value || '[]'); }
    catch(e) {}

    var meta = _tierMeta();
    var html = '';
    tiers.forEach(function(t, i) { html += _buildTierCard(t, i, meta.analytes, meta.matrices); });
    el.innerHTML = html;

    el.querySelectorAll('.tier-desc').forEach(function(inp) {
      inp.addEventListener('input', syncRecoveryTiersJson);
    });
  }

  function addRecoveryTier() {
    var el = document.getElementById('recoveryTiersContainer');
    var meta = _tierMeta();
    var count = el.querySelectorAll('.tier-card').length;
    var frag = document.createElement('div');
    frag.innerHTML = _buildTierCard({}, count, meta.analytes, meta.matrices);
    var card = frag.firstChild;
    el.appendChild(card);
    card.querySelector('.tier-desc').addEventListener('input', syncRecoveryTiersJson);
    _renumberTierBadges();
    syncRecoveryTiersJson();
  }

  function removeTierCard(btn) {
    btn.closest('.tier-card').remove();
    _renumberTierBadges();
    syncRecoveryTiersJson();
  }

  function _renumberTierBadges() {
    document.querySelectorAll('#recoveryTiersContainer .tier-card').forEach(function(card, i) {
      var badge = card.querySelector('.tier-badge');
      if (badge) badge.textContent = 'Tier ' + (i + 1);
      card.setAttribute('data-tier-idx', i);
    });
  }

  function addTierChip(sel) {
    var val = sel.value;
    if (!val) return;
    sel.value = '';
    var field = sel.getAttribute('data-field');
    var chipfield = sel.closest('.tier-chipfield');
    var row = sel.closest('.tier-chip-row');
    var cssClass = field === 'tight_matrices' ? 'mat-chip' : (field === 'no_std_analytes' ? 'nostd-chip' : '');
    var chip = document.createElement('span');
    chip.className = 'tier-chip ' + cssClass;
    chip.setAttribute('data-field', field);
    chip.setAttribute('data-val', val);
    chip.innerHTML = _esc(val) + '<button type="button" class="tier-chip-rm" onclick="removeTierChip(this)">&times;</button>';
    row.insertBefore(chip, sel);
    var opt = sel.querySelector('option[value="' + val.replace(/"/g, '\\"') + '"]');
    if (opt) opt.remove();
    syncRecoveryTiersJson();
  }

  function removeTierChip(btn) {
    var chip = btn.closest('.tier-chip');
    if (!chip) return;
    var val = chip.getAttribute('data-val');
    var field = chip.getAttribute('data-field');
    var row = chip.closest('.tier-chip-row');
    chip.remove();
    var sel = row.querySelector('select.tier-add-sel[data-field="' + field + '"]');
    if (sel && val) {
      var opt = document.createElement('option');
      opt.value = val;
      opt.textContent = val;
      var inserted = false;
      for (var i = 1; i < sel.options.length; i++) {
        if (sel.options[i].value > val) {
          sel.insertBefore(opt, sel.options[i]);
          inserted = true;
          break;
        }
      }
      if (!inserted) sel.appendChild(opt);
    }
    syncRecoveryTiersJson();
  }

  function syncRecoveryTiersJson() {
    var tiers = [];
    document.querySelectorAll('#recoveryTiersContainer .tier-card').forEach(function(card, idx) {
      var tier = { tier: idx + 1 };
      var desc = card.querySelector('.tier-desc');
      if (desc) tier.description = desc.value.trim();
      var minEl = card.querySelector('.tier-min');
      var maxEl = card.querySelector('.tier-max');
      var rsdEl = card.querySelector('.tier-rsd');
      if (minEl && minEl.value !== '') tier.recovery_min = parseFloat(minEl.value);
      if (maxEl && maxEl.value !== '') tier.recovery_max = parseFloat(maxEl.value);
      if (rsdEl && rsdEl.value !== '') tier.rsd_max     = parseFloat(rsdEl.value);
      ['key_analytes', 'tight_matrices', 'no_std_analytes'].forEach(function(field) {
        var chips = card.querySelectorAll('.tier-chip[data-field="' + field + '"]');
        var vals = Array.prototype.map.call(chips, function(c) { return c.getAttribute('data-val'); });
        tier[field] = vals;
      });
      tiers.push(tier);
    });
    var el = document.getElementById('recovery_tiers_json');
    if (el) el.value = JSON.stringify(tiers);
  }

  /* ── Surrogate Map — simple analyte → IS table ───────────────── */

  function buildSurrogateMapTable() {
    var tbody = document.getElementById('surMapBody');
    if (!tbody) return;
    var d = {};
    try { d = JSON.parse((document.getElementById('surrogate_is_data') || {value:'{}'}).value || '{}'); }
    catch(e) { return; }
    var analytes = d.analytes      || [];
    var labels   = d.analyte_labels || {};
    var surr     = d.surrogates    || [];   // [{keyword,name,in_core,role,url}]
    var map      = d.map           || {};   // effective (override or default)
    var defaults = d.defaults      || {};

    // Injection IS: prefill the field with the derived default if empty.
    var isField = document.getElementById('surrogate_is');
    if (isField && !isField.value && d.injection_is_default) {
      isField.value = d.injection_is_default;
    }

    tbody.innerHTML = '';
    if (!analytes.length) {
      tbody.innerHTML = '<tr><td colspan="3" style="color:var(--s-secondary);font-size:12px;padding:8px">No analytes configured.</td></tr>';
      return;
    }

    // Dropdown options = this method's DERIVED surrogate set (not the global pool)
    var surByKw = {};
    var baseSurOpts = '<option value="">— None —</option>';
    surr.forEach(function(s) {
      surByKw[s.keyword] = s;
      baseSurOpts += '<option value="' + _esc(s.keyword) + '">' + _esc(s.name) + '</option>';
    });

    analytes.forEach(function(kw) {
      var label   = labels[kw] || kw;
      var current = map[kw] || '';
      var dflt    = defaults[kw] || '';
      // include the current value as an option even if outside the derived set
      var opts = baseSurOpts;
      if (current && !surByKw[current]) {
        opts += '<option value="' + _esc(current) + '">' + _esc(current) + '</option>';
      }
      opts = opts.replace('value="' + _esc(current) + '"',
                          'value="' + _esc(current) + '" selected');
      // marking: default vs override, and core-service role
      var s = surByKw[current];
      var mark = '';
      if (current) {
        mark += (current === dflt)
          ? '<span class="sur-tag sur-default" title="from the analyte→surrogate master map">default</span>'
          : '<span class="sur-tag sur-override" title="overridden (default: ' + _esc(dflt || '—') + ')">override</span>';
        if (s && s.in_core) {
          mark += ' <a class="sur-tag sur-core" target="_blank" href="' + _esc(s.url) +
                  '" title="core AnalysisService · pfas_role=' + _esc(s.role) + '">&#128279; core</a>';
        } else {
          mark += ' <span class="sur-tag sur-nocore" title="no core AnalysisService marked pfas_role=surrogate">&#9888; not in core</span>';
        }
      } else if (dflt === '') {
        mark = '<span style="font-size:11px;color:var(--s-secondary)">no labeled standard</span>';
      }
      var tr = document.createElement('tr');
      tr.innerHTML =
        '<td class="pa-name">' + _esc(label) + '</td>' +
        '<td><select class="sur-map-sel" data-analyte="' + _esc(kw) + '"' +
          ' data-default="' + _esc(dflt) + '"' +
          ' onchange="syncSurrogateMapJson();updateSurMark(this)">' + opts + '</select></td>' +
        '<td class="sur-mark">' + mark + '</td>';
      tbody.appendChild(tr);
    });
    syncSurrogateMapJson();
  }

  function syncSurrogateMapJson() {
    var result = [];
    document.querySelectorAll('#surMapBody .sur-map-sel').forEach(function(sel) {
      var analyte = sel.getAttribute('data-analyte');
      if (analyte) result.push({analyte: analyte, surrogate_is: sel.value});
    });
    var el = document.getElementById('surrogate_map_json');
    if (el) el.value = JSON.stringify(result);
  }

  /* Update just one row's default/override tag after a change (no full rebuild,
     which would revert edits by re-reading the server payload). */
  function updateSurMark(sel) {
    var cell = sel.closest('tr').querySelector('.sur-mark');
    if (!cell) return;
    var cur = sel.value, dflt = sel.getAttribute('data-default') || '';
    if (!cur) { cell.innerHTML = ''; return; }
    cell.innerHTML = (cur === dflt)
      ? '<span class="sur-tag sur-default">default</span>'
      : '<span class="sur-tag sur-override" title="default: ' + _esc(dflt || '—') + '">override</span>';
  }
  window.updateSurMark = updateSurMark;

  /* ── Per-Analyte Assignments table ───────────────────────────── */

  function buildPerAnalyteTable() {
    var tbody = document.getElementById('perAnalyteBody');
    var jsonEl = document.getElementById('per_analyte_json');
    if (!tbody || !jsonEl) return;
    var rows = [];
    try { rows = JSON.parse(jsonEl.value || '[]'); } catch(e) { return; }
    tbody.innerHTML = '';
    rows.forEach(function(row) {
      var tr = document.createElement('tr');
      tr.setAttribute('data-analyte', row.analyte || '');
      tr.innerHTML =
        '<td class="pa-name">' + _esc(row.analyte || '') + '</td>' +
        '<td style="text-align:center">' +
          '<input type="checkbox" class="pa-cb" data-field="no_labeled_std"' +
          (row.no_labeled_std ? ' checked' : '') + ' onchange="syncPerAnalyteJson()" /></td>' +
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
      var noIs      = tr.querySelector('[data-field="no_labeled_std"]');
      var confirmIon = tr.querySelector('[data-field="confirm_ion_mz"]');
      var notes     = tr.querySelector('[data-field="notes"]');
      result.push({
        analyte:        tr.getAttribute('data-analyte'),
        no_labeled_std: noIs      ? noIs.checked       : false,
        confirm_ion_mz: confirmIon ? confirmIon.value.trim() : '',
        notes:          notes     ? notes.value.trim() : '',
      });
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
    /* Matrix adjustment is now server-rendered per supported matrix (named
       fields matrix_factor.<title>, tied to core SampleTypes) — no JS. */
    /* Salt adjustment is now server-rendered per analyte (named fields
       salt_factor.<kw> + salt_lot.<kw>) — no JS population needed. */
    try {
      var iso = JSON.parse(document.getElementById('isomer_summation_json').value || '[]');
      iso.forEach(function(r) { addIsomerRow(r.linear, r.branched, r.reported, r.enabled !== false); });
    } catch(e) {}
    try {
      var stages = JSON.parse(document.getElementById('extraction_stages_json').value || '[]');
      stages.forEach(function(s) { addStageCard(s); });
    } catch(e) {}
    try {
      var eisEl = document.getElementById('eis_overrides_json');
      if (eisEl) {
        var eis = JSON.parse(eisEl.value || '[]');
        eis.forEach(function(r) { addEisRow(r.analyte, r.recovery_min, r.recovery_max); });
      }
    } catch(e) {}
    buildRecoveryTiersGrid();
    buildAMIGrid();
    buildSpikeMatrixSections();
    buildSurrogateMapTable();
    buildPerAnalyteTable();
  });

  document.querySelector('form').addEventListener('submit', function() {
    syncMatrixFactorsJson(); syncSaltJson(); syncIsomerJson(); syncSpikeLevelsJson();
    syncStageJson(); syncEisJson(); syncRecoveryTiersJson();
    syncSurrogateMapJson(); syncAMIJson(); syncPerAnalyteJson();
  });
