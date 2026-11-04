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
           recovery limit passes or fails everything */
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

  /* ── Extraction stages ───────────────────────────
     One table row per stage (its order, name, what it records per sample
     and its two switches) and one drawer holding the whole stage. The
     drawer edits a copy: Done writes the row and the serialised list,
     Cancel or Escape leaves both as they were. Each row keeps the stage as
     stored, so a key the drawer has no field for (a newer editor's, a
     migration's) is carried through the next save. Nothing here sets an
     inline style: the look is the classes' (pfas-components.css). */
  var STAGE_CAPTURES = [['', 'Nothing'], ['amount', 'Sample amount (g or mL)'],
                        ['final_volume', 'Final extract volume (mL)'], ['spe_port', 'SPE port']];
  /* the table's word for each, as the stage form names them (stage_form.CAPTURE_LABELS) */
  var STAGE_CAPTURE_WORDS = { amount: 'Sample amount', final_volume: 'Final extract volume', spe_port: 'SPE port' };
  /* the note under the choice, where the choice needs one */
  var STAGE_CAPTURE_NOTES = {
    final_volume: 'Dilutions are recorded at this stage, one row each: diluted from, fold, route and aliquot. FM-ENV-003 prints them.',
    spe_port: 'Recorded for every sample and QC.'
  };
  /* the drawer's fields, in order: [key, label, kind, help line] */
  var STAGE_FIELDS = [
    ['order', 'Order', 'number', 'A number typed here moves the stage to that place.'],
    ['name', 'Name', 'text', ''],
    ['id', 'ID', 'text', 'Lower case, no spaces; an extraction keeps its records by it.'],
    ['description', 'Description', 'text', ''],
    ['reagent_roles', 'Reagent roles', 'csv', 'Separate with commas.'],
    ['equipment', 'Equipment with a serial number', 'csv', 'Separate with commas.'],
    ['consumables', 'Consumables recorded by lot', 'csv', 'Separate with commas.'],
    ['captures_samples', 'Records per sample', 'choice', ''],
    ['confirmations', 'Checks the chemist ticks', 'lines', 'One per line.'],
    ['creates_solution', 'Creates solution', 'switch', 'Records a new in-house Prepared Standard lot.'],
    ['capture_pedigree', 'Capture standard pedigree', 'switch', 'Records which prepared-standard lots were spiked.'],
    ['media', 'Action image', 'image', 'A GIF or photo shown in the Extraction Guide.']
  ];

  function stageEl(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) { e.className = cls; }
    if (text !== undefined) { e.textContent = text; }
    return e;
  }
  function stageText(v) { return v === undefined || v === null ? '' : String(v).trim(); }
  /* a list as stored or as typed, one item between each separator */
  function splitList(v, sep) {
    var s = Array.isArray(v) ? v.join(sep) : stageText(v);
    return s ? s.split(sep).map(function(x) { return x.trim(); }).filter(Boolean) : [];
  }
  function splitCsv(v) { return splitList(v, ','); }
  function splitLines(v) { return splitList(v, '\n'); }
  /* a choice the list does not offer is no choice */
  function captureOf(v) {
    var c = stageText(v);
    return STAGE_CAPTURES.some(function(o) { return o[0] === c; }) ? c : '';
  }

  /* The keys a stage is saved with, read from the stage: the list the
     extraction, its log and the review read (stage_form.DERIVED_KEYS,
     sample_table.STAGE_KEY) and the guide's name, order and image. */
  function stageKeys(s, i) {
    return {
      id:               stageText(s.id) || ('stage_' + (i + 1)),
      order:            parseInt(stageText(s.order), 10) || (i + 1),
      name:             stageText(s.name),
      description:      stageText(s.description),
      reagent_roles:    splitCsv(s.reagent_roles),
      equipment:        splitCsv(s.equipment),
      consumables:      splitCsv(s.consumables),
      captures_samples: captureOf(s.captures_samples),
      confirmations:    splitLines(s.confirmations),
      creates_solution: !!s.creates_solution,
      capture_pedigree: !!s.capture_pedigree,
      media:            stageText(s.media),
      media_alt:        stageText(s.media_alt)
    };
  }

  function stageRows() {
    var list = document.getElementById('stage-list');
    return list ? Array.prototype.slice.call(list.querySelectorAll('tr.mp-stage')) : [];
  }
  /* an empty list keeps its header and says so in one line */
  function stageEmpty() {
    var list = document.getElementById('stage-list');
    var empty = list ? list.querySelector('tr.pfas-empty-row') : null;
    if (empty) { empty.hidden = stageRows().length !== 0; }
  }

  /* One row: the cells are made once and redrawn in place, so the Edit
     button keeps the focus the drawer hands back on close. */
  function addStageRow(s) {
    var row = stageEl('tr', 'mp-stage');
    /* the stage as stored: keys the drawer has no field for are carried
       through the next save instead of being dropped */
    row._stored = s || {};
    var order = stageEl('td', 'mp-stage-order');
    var grip = stageEl('span', 'grip');
    grip.setAttribute('title', 'Drag to reorder');
    grip.setAttribute('aria-hidden', 'true');
    order.appendChild(grip);
    var cells = { n: stageEl('span', 'mp-stage-n'), name: stageEl('span', 'mp-stage-name'),
                  slug: stageEl('span', 'mp-stage-slug'), records: stageEl('td'),
                  solution: stageEl('td'), pedigree: stageEl('td'),
                  edit: stageEl('button', 'btn-sm btn-secondary mp-stage-edit', 'Edit') };
    order.appendChild(cells.n);
    var stage = stageEl('td', 'mp-stage-cell');
    stage.appendChild(cells.name);
    stage.appendChild(cells.slug);
    var act = stageEl('td', 'mp-stage-act');
    cells.edit.type = 'button';
    cells.edit.addEventListener('click', function() { openStageDrawer(row); });
    act.appendChild(cells.edit);
    [order, stage, cells.records, cells.solution, cells.pedigree, act].forEach(function(td) { row.appendChild(td); });
    row._cells = cells;
    document.getElementById('stage-list').appendChild(row);
    drawStageRow(row);
    stageEmpty();
    return row;
  }

  /* the row as the list would be saved: its order, its name over its id,
     the per-sample record as a word (none: a dash), the switches On / Off */
  function drawStageRow(row) {
    var k = stageKeys(row._stored || {}, stageRows().indexOf(row)), c = row._cells;
    c.n.textContent = String(k.order);
    c.name.textContent = k.name;
    c.slug.textContent = k.id;
    c.records.textContent = STAGE_CAPTURE_WORDS[k.captures_samples] || '\u2014';
    if (k.captures_samples) { c.records.removeAttribute('title'); }
    else { c.records.setAttribute('title', 'Nothing recorded per sample'); }
    c.solution.textContent = k.creates_solution ? 'On' : 'Off';
    c.pedigree.textContent = k.capture_pedigree ? 'On' : 'Off';
    c.edit.setAttribute('aria-label', 'Edit ' + (k.name || 'stage ' + k.order));
  }

  /* one field of the drawer: its label (and help line) on the left, its
     control on the right; a list of lines spans the block */
  function stageField(form, f, s) {
    var key = f[0], kind = f[2], id = 'mp-stage-' + key.replace(/_/g, '-');
    var lab = stageEl('div', 'cf-label'), ctl = stageEl('div', 'cf-control');
    var label = stageEl('label', '', f[1]);
    label.setAttribute('for', id);
    lab.appendChild(label);
    if (f[3]) { lab.appendChild(stageEl('span', 'hint', f[3])); }
    var input;
    if (kind === 'lines') {
      input = stageEl('textarea');
      input.setAttribute('rows', '3');
      input.value = splitLines(s[key]).join('\n');
      lab.className += ' is-wide';
      ctl.className += ' is-wide';
    } else if (kind === 'choice') {
      input = stageEl('select');
      STAGE_CAPTURES.forEach(function(o) {
        var opt = stageEl('option', '', o[1]);
        opt.value = o[0];
        input.appendChild(opt);
      });
      input.value = captureOf(s[key]);
    } else if (kind === 'switch') {
      input = stageEl('input');
      input.type = 'checkbox';
      input.checked = !!s[key];
    } else if (kind === 'number') {
      /* a whole number, ending at the right (pfas-components.css) */
      input = stageEl('input');
      input.type = 'number';
      input.setAttribute('min', '1');
      input.setAttribute('step', '1');
      input.value = stageText(s[key]);
    } else if (kind === 'image') {
      input = stageEl('input', 'mp-stage-file');
      input.type = 'file';
      input.setAttribute('accept', '.gif,.png,.jpg,.jpeg');
    } else {
      input = stageEl('input');
      input.type = 'text';
      input.value = kind === 'csv' ? splitCsv(s[key]).join(', ') : stageText(s[key]);
    }
    input.id = id;
    if (kind !== 'image') { input.setAttribute('data-field', key); }
    if (kind === 'switch') {
      /* the switch, then its state word beside it (On / Off) */
      var sw = stageEl('label', 'pfas-switch');
      sw.appendChild(input);
      sw.appendChild(stageEl('span', 'pfas-switch-track'));
      var word = stageEl('span', 'pfas-switch-word', input.checked ? 'On' : 'Off');
      word.setAttribute('aria-hidden', 'true');
      ctl.className += ' is-switch';
      ctl.appendChild(sw);
      ctl.appendChild(word);
      var comps = window.PFAS && window.PFAS.components;
      if (comps && comps.switchWord) { comps.switchWord(input); }
    } else if (kind === 'image') {
      stageImage(ctl, input, s);
    } else {
      ctl.appendChild(input);
    }
    if (kind === 'choice') {
      var note = stageEl('span', 'hint');
      var drawNote = function() {
        note.textContent = STAGE_CAPTURE_NOTES[input.value] || '';
        note.hidden = !note.textContent;
      };
      input.addEventListener('change', drawNote);
      drawNote();
      ctl.appendChild(note);
    }
    form.appendChild(lab);
    form.appendChild(ctl);
    return input;
  }

  /* Stage action image: uploaded at once (AJAX), so a rejected file never
     costs the manager their unsaved edits; the stage stores only the token,
     written by the drawer's Done. A late answer lands in the drawer it was
     sent from; a drawer closed meanwhile is gone with it. */
  function stageImage(ctl, file, s) {
    var media = stageEl('input'), alt = stageEl('input');
    media.type = 'hidden';
    alt.type = 'hidden';
    media.setAttribute('data-field', 'media');
    alt.setAttribute('data-field', 'media_alt');
    media.value = stageText(s.media);
    alt.value = stageText(s.media_alt);
    var thumb = stageEl('span', 'mp-stage-thumb');
    var clear = stageEl('button', 'btn-sm btn-secondary mp-stage-clear', 'Remove image');
    clear.type = 'button';
    function draw() {
      thumb.textContent = '';
      if (media.value) {
        var img = stageEl('img');
        img.alt = '';
        img.src = (window.MP_MEDIA_URL || '') + '?f=' + encodeURIComponent(media.value);
        thumb.appendChild(img);
      }
      thumb.hidden = !media.value;
      clear.hidden = !media.value;
    }
    file.addEventListener('change', function() {
      if (!file.files || !file.files[0]) { return; }
      var picked = file.files[0];
      var fd = new FormData();
      fd.append('action', 'upload');
      fd.append('media', picked);
      var xhr = new XMLHttpRequest();
      xhr.open('POST', window.MP_MEDIA_URL, true);
      ctl.setAttribute('data-uploading', '1');
      var done = function() {
        ctl.removeAttribute('data-uploading');
        ctl.dispatchEvent(new Event('mp-stage-upload', { bubbles: true }));
      };
      xhr.onload = function() {
        var res = {};
        try { res = JSON.parse(xhr.responseText); } catch (e) { res = {}; }
        if (res.ok && res.token) {
          media.value = res.token;
          if (!alt.value) { alt.value = picked.name; }
          draw();
        } else {
          window.alert('Upload failed: ' + (res.error || ('HTTP ' + xhr.status)));
        }
        done();
      };
      xhr.onerror = function() { window.alert('Upload failed: the network did not answer.'); done(); };
      ctl.dispatchEvent(new Event('mp-stage-upload', { bubbles: true }));
      xhr.send(fd);
    });
    clear.addEventListener('click', function() {
      media.value = '';
      alt.value = '';
      file.value = '';
      draw();
    });
    [media, alt, thumb, file, clear].forEach(function(n) { ctl.appendChild(n); });
    draw();
  }

  /* the drawer's fields as the stage keeps them */
  function stageDrawerValues(form) {
    var get = function(f) {
      var el = form.querySelector('[data-field="' + f + '"]');
      return el ? el.value.trim() : '';
    };
    var getBool = function(f) {
      var el = form.querySelector('[data-field="' + f + '"]');
      return el ? el.checked : false;
    };
    return {
      order:            parseInt(get('order'), 10),
      name:             get('name'),
      id:               get('id'),
      description:      get('description'),
      reagent_roles:    splitCsv(get('reagent_roles')),
      equipment:        splitCsv(get('equipment')),
      consumables:      splitCsv(get('consumables')),
      captures_samples: captureOf(get('captures_samples')),
      confirmations:    splitLines(get('confirmations')),
      creates_solution: getBool('creates_solution'),
      capture_pedigree: getBool('capture_pedigree'),
      media:            get('media'),
      media_alt:        get('media_alt')
    };
  }

  /* One stage's drawer, titled with its name; `row` null opens a new
     stage, added by Done (one past the highest order) and never by Cancel.
     A centred dialog, as a grid row's form opens; Done, as its Done. */
  function openStageDrawer(row) {
    var comps = window.PFAS && window.PFAS.components, drawer = comps ? comps.drawer : null;
    if (!drawer) { return; }
    var s = row ? (row._stored || {}) : {};
    var at = row ? stageRows().indexOf(row) : stageRows().length;
    /* the stage as the table shows it; a new one comes last */
    var base = stageKeys(s, at);
    if (!row) {
      base.order = stageRows().reduce(function(m, r, i) {
        return Math.max(m, stageKeys(r._stored || {}, i).order);
      }, 0) + 1;
    }
    var shown = {};
    Object.keys(s).forEach(function(k) { shown[k] = s[k]; });
    shown.order = base.order;
    var form = stageEl('div', 'cf-settings mp-stage-form');
    var inputs = {};
    STAGE_FIELDS.forEach(function(f) { inputs[f[0]] = stageField(form, f, shown); });
    var orderIn = inputs.order, idIn = inputs.id, shownOrder = orderIn.value;
    /* a value the list cannot take is refused here, with its reason under
       its box: an id the list already has, an order that is no place */
    function reason(input, id) {
      var err = stageEl('span', 'hint is-error');
      err.id = id;
      err.hidden = true;
      input.parentNode.appendChild(err);
      input.setAttribute('aria-describedby', err.id);
      input.addEventListener('input', function() {
        err.hidden = true;
        err.textContent = '';
        input.removeAttribute('aria-invalid');
      });
      return function(text) {
        err.textContent = text;
        err.hidden = false;
        input.setAttribute('aria-invalid', 'true');
        input.focus();
      };
    }
    var refuseId = reason(idIn, 'mp-stage-id-error');
    var refuseOrder = reason(orderIn, 'mp-stage-order-error');
    var foot = stageEl('div', 'pfas-drawer-actions mp-stage-actions');
    var done = stageEl('button', 'btn btn-primary', 'Done');
    var cancel = stageEl('button', 'btn btn-secondary', 'Cancel');
    done.type = 'button';
    cancel.type = 'button';
    foot.appendChild(done);
    foot.appendChild(cancel);
    /* Done waits for an image still uploading */
    form.addEventListener('mp-stage-upload', function() {
      done.disabled = !!form.querySelector('[data-uploading]');
    });
    done.addEventListener('click', function() {
      var edited = stageDrawerValues(form), next = {}, target = row;
      /* a stage id appears once in the list: an extraction keeps its
         records by it, and the tab's save refuses a second */
      if (edited.id && stageIdsBut(row).indexOf(edited.id) >= 0) {
        refuseId('Another stage has this ID.');
        return;
      }
      /* a typed order moves the stage to that place, and the list is
         numbered 1, 2, 3 ... again; left as shown, the order is kept; a
         typed order that is no place (0, below, blank, not a whole number)
         is refused */
      var typedOrder = orderIn.value.trim(), retyped = typedOrder !== shownOrder;
      if (retyped && !(/^[0-9]+$/.test(typedOrder) && parseInt(typedOrder, 10) >= 1)) {
        refuseOrder('Type a whole number, 1 or more.');
        return;
      }
      var moveTo = retyped ? parseInt(typedOrder, 10) : 0;
      edited.order = base.order;
      Object.keys(s).forEach(function(k) { next[k] = s[k]; });
      /* every key in the place the list saves it, then the drawer's values:
         a Done with nothing edited leaves the list as it was */
      Object.assign(next, base, edited);
      if (target) {
        target._stored = next;
      } else {
        target = addStageRow(next);
      }
      if (moveTo) {
        placeStageRow(target, moveTo);
        renumberStages();
      }
      /* a blank id is given a free one now, so it no longer follows the
         row's place */
      if (!stageText(target._stored.id)) { target._stored.id = freeStageId(target); }
      drawStageRow(target);
      stagesEdited();
      drawer.close();
    });
    cancel.addEventListener('click', function() { drawer.close(); });
    if (row) {
      var remove = stageEl('button', 'btn btn-danger mp-stage-remove', 'Remove stage');
      remove.type = 'button';
      remove.addEventListener('click', function() {
        /* the row's Edit button goes with it: the focus returns to Add */
        drawer.opener = document.getElementById('stage-add');
        removeStageRow(row);
        drawer.close();
      });
      foot.appendChild(remove);
    }
    drawer.open(row ? (base.name || 'Stage ' + base.order) : 'New stage', form,
                { footer: foot, cls: 'is-dialog', focus: inputs.name,
                  opener: row ? row._cells.edit : document.getElementById('stage-add') });
  }

  /* the ids of the other stages, as the list saves them */
  function stageIdsBut(row) {
    return stageRows().map(function(r, i) {
      return r === row ? '' : stageKeys(r._stored || {}, i).id;
    }).filter(Boolean);
  }
  /* stage_<n> from the row's place on, the first no other stage has */
  function freeStageId(row) {
    var taken = stageIdsBut(row), n = stageRows().indexOf(row) + 1;
    while (taken.indexOf('stage_' + n) >= 0) { n += 1; }
    return 'stage_' + n;
  }
  /* the row moved to place `pos` (1 first; past the end, last) */
  function placeStageRow(row, pos) {
    var others = stageRows().filter(function(r) { return r !== row; });
    var at = Math.min(Math.max(pos, 1), others.length + 1) - 1;
    var list = document.getElementById('stage-list');
    if (at < others.length) { list.insertBefore(row, others[at]); } else { list.appendChild(row); }
  }

  function removeStageRow(row) {
    if (row && row.parentNode) {
      row.parentNode.removeChild(row);
      renumberStages();
      stageEmpty();
      stagesEdited();
    }
  }

  /* A stage added, removed, moved or edited in its drawer is an unsaved
     change of its tab: nothing typed on the page fires for it, so the
     serialised list says so itself. */
  function stagesEdited() {
    syncStageJson();
    var h = document.getElementById('extraction_stages_json');
    if (h) { h.dispatchEvent(new Event('change', { bubbles: true })); }
  }

  /* the order follows the rows: a drag, a removal */
  function renumberStages() {
    stageRows().forEach(function(row, idx) {
      row._stored = row._stored || {};
      row._stored.order = idx + 1;
      drawStageRow(row);
    });
  }

  function syncStageJson() {
    /* no list on the page: leave the saved value alone, never write "[]" */
    var list = document.getElementById('stage-list');
    var hidden = document.getElementById('extraction_stages_json');
    if (!list || !hidden) { return; }
    var result = [];
    stageRows().forEach(function(row) {
      /* the edited keys over the stage as stored, so a key with no field
         in the drawer (a newer editor's, a migration's) is kept */
      var stored = row._stored || {};
      var kept = {};
      Object.keys(stored).forEach(function(k) { kept[k] = stored[k]; });
      result.push(Object.assign(kept, stageKeys(stored, result.length)));
    });
    hidden.value = JSON.stringify(result, null, 2);
  }

  /* Surrogate Map: a declared table (R2), server-rendered -- no JS. */

  /* Analytes: one server-drawn grid (profile_grids.analytes_sheet); each
     panel switch posts its own field, so nothing is serialised here. */

  document.addEventListener('DOMContentLoaded', function() {
    /* Salt and matrix adjustment factors are declared tables (R2,
       method_profile_sections), server-rendered -- no JS. */
    var stageList = document.getElementById('stage-list');
    if (!stageList) { return; }
    try {
      var stages = JSON.parse(document.getElementById('extraction_stages_json').value || '[]');
      /* a stage stored with no id keeps the id it is drawn with (its
         place), so a drag never moves it onto a new stage's id */
      stages.forEach(function(s, i) {
        if (s && typeof s === 'object' && !stageText(s.id)) { s.id = stageKeys(s, i).id; }
        addStageRow(s);
      });
      if (stages.length) { syncStageJson(); }
    } catch(e) {}
    stageEmpty();
    var add = document.getElementById('stage-add');
    if (add) { add.addEventListener('click', function() { openStageDrawer(null); }); }
    /* Stage rows reorder by their handle with SortableJS (mouse and touch),
       then renumber and re-serialise. */
    if (window.Sortable) {
      Sortable.create(stageList, {
        handle: '.grip', draggable: 'tr.mp-stage', animation: 150,
        ghostClass: 'dragging',
        onEnd: function () { renumberStages(); stagesEdited(); }
      });
    }
  });

  /* Serialise every table into its hidden field before the profile form
     submits. Each runs on its own: the first one threw on every page (its
     table had been replaced by named fields) and silently stopped all the
     others, so their edits never reached the server. */
  /* any form: each tab saves through its own, so the stage list is
     serialised before whichever form submits */
  document.addEventListener('submit', function() {
    [syncStageJson].forEach(function (fn) {
      try { fn(); } catch (e) {
        if (window.console) console.error('method profile: ' + (fn.name || 'sync') + ' failed', e);
      }
    });
  }, true);

/* The per-analyte calibration range note ("2 to 160 (7 points)") follows the
   multiple and the highest standard as they are typed: the method's levels
   times the multiple, up to the highest standard (calibration_levels.levels). */
(function () {
  var box = document.querySelector(".cal-scale[data-levels]");
  if (!box) { return; }
  var base = [];
  try { base = JSON.parse(box.getAttribute("data-levels") || "[]"); } catch (e) { return; }
  function fmt(v) {
    var s = Number(v).toPrecision(4);
    return String(parseFloat(s));
  }
  function num(inp) {
    var v = inp ? parseFloat(String(inp.value).replace(",", ".")) : NaN;
    return isFinite(v) ? v : null;
  }
  function update(row) {
    var factor = num(row.querySelector('input[name$="__factor"]'));
    var top = num(row.querySelector('input[name$="__max"]'));
    var note = row.querySelector("td .cf-hint");
    if (!note) { return; }
    var f = factor === null ? 1 : factor;
    var lv = base.map(function (v) { return v * f; }).filter(function (v) { return top === null || v <= top * (1 + 1e-9); });
    note.textContent = lv.length ? fmt(lv[0]) + " to " + fmt(lv[lv.length - 1]) + " (" + lv.length + " points)" : "no levels";
  }
  box.addEventListener("input", function (e) {
    var row = e.target.closest ? e.target.closest("tr") : null;
    if (row) { update(row); }
  });
  box.addEventListener("change", function (e) {
    var row = e.target.closest ? e.target.closest("tr") : null;
    if (row) { update(row); }
  });
})();

/* QC criteria: the applied windows are the recovery editor. The QC type and
   the spike level segments redraw the grid, as does an edit to what it is
   resolved from (the tiers, the groups, the grouped tiers setting): a
   server preview, the same parse and resolver a save runs, nothing written.
   A cell opens the cell drawer, "<analyte> · <column> · <QC type>" with
   ← Prev / Next → over the grid's window cells in reading order (the
   focus stays on the button pressed; Close returns to the cell shown): its
   window, large, on a 0 – 200 % bar; whether it is set on this cell (by a
   tier listing its matrix: "Reset to tier X" names the tier and window that
   reset leaves), from a wider tier or the method default; the Set by list
   (this cell, the tier, the method, the one that sets it marked); and the
   tier's own editor inline (name, applies to, matrices as the tier's own
   search picker, the window as min and max with a two-handle slider), each
   copy written to the tier's input on change. Nothing is stored for a
   cell: every action is a tier's. "New tier for selected cells" inserts a
   tier, of the group and scope the server names for the cell (a tier for
   listed matrices listing the cell's column), BEFORE the tier that sets it
   (the first matching tier applies), by moving the rows below it down one,
   and edits it in the drawer; it is offered only where that changes the
   cell. A reset removes the tier that sets it (a cleared name removes a
   tier on Save), naming everything it sets, and is named for what it
   leaves: "Reset cell to method default (lo – hi)" only where the tier
   under it is the method's default tier, else "Reset to tier X (lo –
   hi)", a tier named as typed; never both. Each reset can be undone until
   Save. A redrawn grid keeps the
   drawer on its cell (its row and its column's first matrix): what it
   shows of the cell is drawn again, the editor is kept, and a cell gone
   closes it.
   The grid opens with every analyte group folded to its row; the groups
   the person opens are remembered per method and QC type shown
   (localStorage "pfas.mp.grp.<method>.<qc>": the open groups' keys) and
   opened again on load and on every redraw. Storage refused (a private
   window) only forgets. The drawer stepping to a cell of a folded group
   opens the group. */
(function () {
  var shown = { qc: "LFSM", level: "ordinary" };
  var timer = null;
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) { n.className = cls; }
    if (text !== undefined) { n.textContent = text; }
    return n;
  }
  function fire(n) {
    n.dispatchEvent(new Event("input", { bubbles: true }));
    n.dispatchEvent(new Event("change", { bubbles: true }));
  }
  function preview() {
    var form = document.getElementById("section-qc");
    if (!form || !document.getElementById("qc-windows")) { return; }
    var data = new FormData(form);
    data.append("_preview", "rt");
    data.append("qc_type", shown.qc);
    data.append("level", shown.level);
    fetch(form.getAttribute("action"), { method: "POST", body: data, credentials: "same-origin" })
      .then(function (r) { return r.text(); })
      .then(function (html) {
        var box = document.createElement("div");
        box.innerHTML = html;
        var fresh = box.querySelector("#qc-windows"), now = document.getElementById("qc-windows");
        if (!fresh || !now) { return; }
        now.parentNode.replaceChild(fresh, now);
        if (window.PFAS && window.PFAS.components) { window.PFAS.components.sheet.init(fresh); }
        reopen();
        reachable();
        follow();
      });
  }
  /* folded groups, remembered per method and QC type shown */
  var methodIn = document.querySelector('#profile-form [name="method_id"]');
  function grid() { return document.querySelector("#qc-windows .pfas-sheet-box"); }
  function foldKey(box) {
    return "pfas.mp.grp." + (methodIn ? methodIn.value : "") + "." + (box.getAttribute("data-fold") || "");
  }
  function openGroups(box) {
    try {
      var s = window.localStorage, v = s ? JSON.parse(s.getItem(foldKey(box)) || "[]") : [];
      return Array.isArray(v) ? v : [];
    } catch (e) { return []; }
  }
  function remember(box, key, open) {
    var list = openGroups(box).filter(function (k) { return k !== key; });
    if (open) { list.push(key); }
    try { var s = window.localStorage; if (s) { s.setItem(foldKey(box), JSON.stringify(list)); } } catch (e) {}
  }
  function reopen() {
    var box = grid(), c = comps();
    if (!box || !c) { return; }
    openGroups(box).forEach(function (k) { c.sheet.fold(box, k, true); });
  }
  /* a cell in a folded group is shown before the drawer opens on it */
  function reveal(td) {
    var tr = td.parentNode, key = tr.getAttribute("data-in-group"), box = grid(), c = comps();
    if (!tr.hidden || !key || !box || !c) { return; }
    c.sheet.fold(box, key, true);
    remember(box, key, true);
  }
  document.addEventListener("pfas:sheet-fold", function (e) {
    var box = e.target.closest ? e.target.closest("#qc-windows .pfas-sheet-box") : null;
    if (box && e.detail) { remember(box, e.detail.group, e.detail.open); }
  });
  /* a cell opens the drawer from the keyboard too */
  function reachable() {
    document.querySelectorAll("#qc-windows td[data-window]").forEach(function (td) {
      td.tabIndex = 0;
      td.setAttribute("role", "button");
    });
  }
  function later() {
    clearTimeout(timer);
    timer = setTimeout(preview, 350);
  }
  /* the QC type's tiers and their matrix lists */
  function showTiers() {
    document.querySelectorAll(".mp-qc-tiers, .mp-qc-lists").forEach(function (w) {
      w.hidden = w.getAttribute("data-qc") !== shown.qc;
    });
  }
  /* the QC type shown: the segment writes its field (qc-show) on a click
     and on a key alike, so the tiers and the grid follow either */
  function showQc(qc) {
    shown.qc = qc;
    showTiers();
    /* Low level shown under an RPD view, then a recovery view whose rule
       has it Off: the grid goes back to the ordinary spike */
    var low = document.querySelector('[data-level-seg] .pfas-seg-item[data-value="low"]');
    var ordinary = document.querySelector('[data-level-seg] .pfas-seg-item[data-value="ordinary"]');
    if (shown.level === "low" && low && low.disabled && ordinary) {
      ordinary.click();
      return;
    }
    preview();
  }
  document.addEventListener("change", function (e) {
    var t = e.target;
    if (t && t.id === "qc-show" && t.closest && t.closest(".pfas-pill-row") && t.value) {
      showQc(t.value);
    }
  });
  document.addEventListener("click", function (e) {
    var item = e.target.closest ? e.target.closest("[data-level-seg] .pfas-seg-item") : null;
    if (!item || item.disabled) { return; }
    shown.level = item.getAttribute("data-value");
    preview();
  });
  /* a saved field changed (a picker's search box posts nothing) */
  function onEdit(e) {
    var t = e.target;
    if (t && t.name && t.closest && t.closest("[data-preview]")) { later(); }
  }
  document.addEventListener("input", onEdit);
  document.addEventListener("change", onEdit);

  /* the drawer */
  function tierInputs(prefix) {
    if (!prefix) { return []; }
    return Array.prototype.filter.call(document.querySelectorAll('[form="section-qc"][name]'), function (n) {
      return n.name.indexOf(prefix) === 0;
    });
  }
  function labelOf(n) { return n.getAttribute("aria-label") || n.name; }
  function copyOf(real) {
    var c;
    if (real.tagName === "SELECT") {
      c = real.cloneNode(true);
      ["name", "form", "id", "class"].forEach(function (a) { c.removeAttribute(a); });
    } else {
      c = el("input");
      c.type = real.type === "number" ? "number" : "text";
      ["min", "max", "step", "placeholder"].forEach(function (a) {
        if (real.hasAttribute(a)) { c.setAttribute(a, real.getAttribute(a)); }
      });
    }
    c.value = real.value;
    c.setAttribute("aria-label", labelOf(real));
    return c;
  }
  function field(label, node, help) {
    var f = el("div", "pfas-sheet-field");
    f.appendChild(el("div", "pfas-sheet-flabel", label));
    if (node) { f.appendChild(node); }
    if (help) { f.appendChild(el("div", "pfas-sheet-help", help)); }
    return f;
  }
  function comps() { return window.PFAS && window.PFAS.components ? window.PFAS.components : null; }
  function drawerOf() { var c = comps(); return c ? c.drawer : null; }
  /* the matrices a tier may list: its collection's pickers' options */
  function matrixOptions(prefix) {
    var coll = prefix.replace(/\d+__$/, "");
    var host = Array.prototype.filter.call(document.querySelectorAll(".pfas-picker-lists"), function (h) {
      return h.getAttribute("data-prefix") === coll && h.getAttribute("data-column") === "matrices";
    })[0];
    return host ? host.getAttribute("data-options") || "[]" : "[]";
  }
  /* a tier's own fields, inline in the cell drawer: copies that post
     nothing, each written to the tier's input on change with a bubbling
     change (the footer counts it, the grid redraws); its matrix list is
     the tier's own search picker on the tier's own field, shown while the
     tier lists its matrices; its window the min / max pair with the
     two-handle slider (an RPD limit, a maximum alone, a stepper) */
  function tierEditor(prefix, title) {
    var reals = tierInputs(prefix), c = comps();
    if (!reals.length || !c) { return null; }
    function real(tail) { return reals.filter(function (n) { return n.name === prefix + tail; })[0] || null; }
    function copy(tail, number) {
      var r = real(tail);
      if (!r) { return null; }
      var n = copyOf(r);
      if (number) { n.type = "number"; }        /* a window's end, drawn as one whatever the row draws */
      n.addEventListener("change", function () {
        if (r.value !== n.value) { r.value = n.value; fire(r); }
      });
      return n;
    }
    var box = el("div", "pfas-sheet-form");
    box.appendChild(el("div", "pfas-sheet-flabel", title));
    var name = copy("name"), group = copy("analyte_5fgroup"), scope = copy("matrix_5fscope");
    if (name) { box.appendChild(field("Name", name)); }
    if (group) { box.appendChild(field("Applies to", group)); }
    if (scope) {
      var f = field("Matrices", scope), list = real("matrices");
      if (list) {
        var pick = el("div", "pfas-picker");
        pick.setAttribute("data-name", list.name);
        pick.setAttribute("data-options", matrixOptions(prefix));
        pick.setAttribute("data-noun", "matrices");
        pick.setAttribute("data-title", name && name.value ? name.value : title);
        f.appendChild(pick);
        c.picker(pick);
        var show = function () { pick.hidden = scope.value !== "listed"; };
        scope.addEventListener("change", show);
        show();
      }
      box.appendChild(f);
    }
    var lo = copy("recovery_5fmin", true), hi = copy("recovery_5fmax", true), rpd = copy("rpd_5fmax", true);
    if (lo && hi) {
      var w = el("div");
      w.setAttribute("data-range", "");
      w.setAttribute("data-scale", "0,200");
      w.setAttribute("data-unit", "%");
      w.appendChild(lo);
      w.appendChild(hi);
      box.appendChild(field("Window", w));
      c.range(w);
    } else if (rpd) {
      var g = field("Window", rpd);
      box.appendChild(g);
      c.num(rpd);
    }
    return box;
  }
  /* the rows of a QC type's tier collection, in index order (an empty
     table's line is no row) */
  function tierRows(qc) {
    var wrap = document.querySelector('.mp-qc-tiers[data-qc="' + qc + '"]');
    return wrap ? wrap.querySelectorAll("table.cf-coll tbody tr:not(.pfas-empty-row)") : [];
  }
  function rowInputs(tr) {
    return Array.prototype.filter.call(tr.querySelectorAll("input, select"), function (n) { return n.name; });
  }
  function setValue(n, v) {
    if (n.value !== v) { n.value = v; fire(n); }
  }
  /* a new tier where the row at `before` is (rows below it move down one),
     or at the end; its group, scope and matrix list set, everything else blank */
  function insertTier(qc, before, group, scope, matrices) {
    var wrap = document.querySelector('.mp-qc-tiers[data-qc="' + qc + '"]');
    var add = wrap ? wrap.querySelector(".cf-add-row") : null;
    if (!add) { return ""; }
    add.click();
    var rows = Array.prototype.slice.call(tierRows(qc));
    var at = rows.length - 1;
    if (before) {
      rows.forEach(function (tr, i) {
        if (rowInputs(tr).some(function (n) { return n.name.indexOf(before) === 0; })) { at = i; }
      });
    }
    /* a reset below the new row now sits one row further down */
    resets.forEach(function (r) {
      if (r.qc === qc && r.row >= at) { r.row += 1; }
    });
    for (var j = rows.length - 1; j > at; j--) {
      var to = rowInputs(rows[j]), from = rowInputs(rows[j - 1]);
      for (var x = 0; x < to.length && x < from.length; x++) { setValue(to[x], from[x].value); }
    }
    var mine = rowInputs(rows[at]);
    mine.forEach(function (n) {
      if (/__analyte_5fgroup$/.test(n.name)) { setValue(n, group); }
      else if (/__matrix_5fscope$/.test(n.name)) { setValue(n, scope); }
      else if (/__matrices$/.test(n.name)) { setValue(n, matrices || "[]"); }
      else { setValue(n, ""); }
    });
    var m = mine[0] ? /^(c__.+?__\d+__)/.exec(mine[0].name) : null;
    return m ? m[1] : "";
  }
  /* resets made on this page, each undone until Save: kept by the row the
     tier sits in (a new tier above it moves it down), never by its input */
  var resets = [];
  function nameInput(qc, row) {
    var tr = tierRows(qc)[row];
    return tr ? rowInputs(tr).filter(function (n) { return /__name$/.test(n.name); })[0] || null : null;
  }
  function drawResets() {
    var box = document.getElementById("qc-resets");
    if (!box) { return; }
    box.textContent = "";
    resets.forEach(function (r) {
      var b = el("button", "btn-sm btn-secondary", "Undo reset");
      b.type = "button";
      b.addEventListener("click", function () { undoReset(r); });
      box.appendChild(el("span", "", r.label + " is removed on Save."));
      box.appendChild(b);
    });
    box.hidden = !resets.length;
  }
  function undoReset(r) {
    resets = resets.filter(function (x) { return x !== r; });
    var input = nameInput(r.qc, r.row);
    if (input) { setValue(input, r.value); }
    drawResets();
  }
  function resetTier(qc, input, label) {
    if (!input || !input.value) { return; }
    var tr = input.closest("tr"), row = Array.prototype.indexOf.call(tierRows(qc), tr);
    if (row < 0) { return; }
    resets.push({ qc: qc, row: row, value: input.value, label: label });
    setValue(input, "");
    drawResets();
  }
  /* a window as the drawer words it: "lo – hi", "≤ hi" for a maximum alone */
  function span(lo, hi) {
    if (hi === "") { return ""; }
    return lo === "" ? "\u2264 " + hi : lo + " \u2013 " + hi;
  }
  /* the window on its bar, scaled 0 – 200 % */
  function bar(lo, hi) {
    var b = el("span", "pfas-cell-bar");
    b.appendChild(el("span"));
    if (hi === "") { b.classList.add("is-none"); return b; }
    function at(v) { return String(Math.max(0, Math.min(1, Number(v) / 200))); }
    b.style.setProperty("--lo", at(lo === "" ? 0 : lo));
    b.style.setProperty("--hi", at(hi));
    return b;
  }
  function setBy(label, window, on) {
    var r = el("div", "pfas-setby" + (on ? " is-set" : ""));
    r.appendChild(el("span", "", label));
    r.appendChild(el("b", "", window || "\u2014"));
    return r;
  }
  function cells() { return Array.prototype.slice.call(document.querySelectorAll("#qc-windows td[data-window]")); }
  /* the matrices a cell's column stands for: its heading's list (JSON, so a
     matrix name holding a comma stays whole) */
  function columnMatrices(td) {
    var th = document.querySelector('#qc-windows thead th[data-col="' + td.getAttribute("data-col") + '"]');
    try { return th ? JSON.parse(th.getAttribute("data-matrices") || "[]") : []; } catch (e) { return []; }
  }
  function findCell(row, matrix) {
    return cells().filter(function (td) {
      return td.parentNode.getAttribute("data-row") === row && columnMatrices(td).indexOf(matrix) >= 0;
    })[0] || null;
  }
  /* the cell the drawer is open on: its row and its column's first matrix
     (what finds it in a redrawn grid), and the parts drawn from it */
  var on = null;
  /* `edit`: the tier the editor edits, where not the cell's own (a new
     tier); `focus`: "prev" or "next", the head button pressed to get here */
  function openWindow(td, edit, focus) {
    var drawer = drawerOf();
    if (!drawer) { return; }
    reveal(td);
    var body = el("div", "pfas-sheet-form"), top = el("div", "pfas-sheet-form"), notes = el("div", "pfas-sheet-form");
    var foot = el("div", "pfas-drawer-actions");
    var prev = el("button", "btn btn-sm btn-secondary", "\u2190 Prev"), next = el("button", "btn btn-sm btn-secondary", "Next \u2192");
    prev.type = "button";
    next.type = "button";
    on = { td: td, row: td.parentNode.getAttribute("data-row"), matrix: columnMatrices(td)[0], body: body,
           top: top, notes: notes, foot: foot, prev: prev, next: next, edit: edit || null };
    function step(by) {
      var list = cells(), to = list[list.indexOf(on.td) + by];
      if (!to) { return; }
      if (to.scrollIntoView) { to.scrollIntoView({ block: "nearest" }); }
      openWindow(to, null, by < 0 ? "prev" : "next");
    }
    prev.addEventListener("click", function () { step(-1); });
    next.addEventListener("click", function () { step(1); });
    body.appendChild(top);
    var get = function (k) { return td.getAttribute("data-" + k) || ""; };
    var editor = edit ? tierEditor(edit.prefix, edit.title) :
                 tierEditor(get("prefix"), get("tier") || "Tier");
    if (editor) { body.appendChild(editor); }
    body.appendChild(notes);
    draw();
    /* stepping keeps the focus on the button pressed (the other where it is
       now off), so Enter steps on; Close returns to the cell shown */
    var keep = focus === "prev" ? (prev.disabled ? next : prev) : focus === "next" ? (next.disabled ? prev : next) : null;
    drawer.open(get("title"), body, { cls: "is-cell", footer: foot, head: [prev, next], opener: td, focus: keep });
    drawer.opener = td;
  }
  /* what the drawer shows of its cell, drawn again after a redraw */
  function draw() {
    var td = on.td, drawer = drawerOf();
    function get(k) { return td.getAttribute("data-" + k) || ""; }
    var kind = get("set-kind"), cell = kind === "cell", method = kind === "method";
    var list = cells(), i = list.indexOf(td);
    on.prev.disabled = i <= 0;
    on.next.disabled = i < 0 || i >= list.length - 1;
    var name = tierInputs(get("prefix")).filter(function (n) { return /__name$/.test(n.name); })[0] || null;
    function action(words, run, into) {
      var b = el("button", "btn btn-sm btn-secondary", words);
      b.type = "button";
      b.addEventListener("click", run);
      into.appendChild(b);
      return b;
    }
    function reset() { drawer.close(); resetTier(get("qc"), name, get("set-by")); }

    var top = on.top;
    top.textContent = "";
    var win = field("Effective window", el("div", "pfas-win-big", get("window")));
    win.appendChild(bar(get("lo"), get("hi")));
    /* a reset is named for what it leaves: the method default (the footer's,
       only where the tier under this one is the method's default tier, as
       the server says), else the tier that takes over, or no window (the
       help line's); never both */
    var resettable = !!name && !method, toDefault = resettable && get("fallback-is-default") === "1";
    var help = el("div", "pfas-sheet-help");
    if (cell && get("hi") === "") {
      help.appendChild(el("span", "", "Tier " + get("tier") + " lists this matrix but sets no window. "));
    } else if (cell) {
      help.appendChild(el("span", "", "Set on this cell. "));
    } else if (method) {
      help.textContent = "Method default";
    } else if (get("tier")) {
      help.appendChild(el("span", "", "From tier " + get("tier") + ". "));
    } else {
      help.textContent = "No tier applies";
    }
    if (resettable && !toDefault) {
      action(get("tier-name") ? "Reset to tier " + get("tier-name") + " (" + span(get("tier-lo"), get("tier-hi")) + ")"
                              : "Reset to no window", reset, help);
    }
    win.appendChild(help);
    top.appendChild(win);
    var by = field("Set by");
    var wider = cell ? get("tier-name") : (method ? "" : get("tier"));
    by.appendChild(setBy("This cell", cell ? span(get("lo"), get("hi")) : "", cell));
    by.appendChild(setBy(wider || "Tier",
                         cell ? span(get("tier-lo"), get("tier-hi")) : (wider ? span(get("lo"), get("hi")) : ""),
                         !cell && !method && !!get("tier")));
    by.appendChild(setBy("Method default", span(get("method-lo"), get("method-hi")), method));
    top.appendChild(by);

    var notes = on.notes;
    notes.textContent = "";
    var foot = on.foot;
    foot.textContent = "";
    /* the new tier is offered once: while it is edited here, the cell still
       names the tier it would take the cell from (an unnamed tier is not one) */
    if (get("new-group") && !on.edit) {
      action("New tier for selected cells", function () {
        var at = insertTier(get("qc"), get("before"), get("new-group"), get("new-scope"), get("new-matrices"));
        if (at) { openWindow(on.td, { prefix: at, title: "New tier" }); }
      }, foot);
      notes.appendChild(el("div", "pfas-sheet-help", "This tier will set: " + get("new-covers") + "."));
      if (get("new-shadows")) { notes.appendChild(el("div", "pfas-sheet-help", get("new-shadows") + ".")); }
    }
    var def = span(get("method-lo"), get("method-hi"));
    if (toDefault || method) {
      action("Reset cell to method default" + (def ? " (" + def + ")" : ""), reset, foot).disabled = method;
    }
    if (resettable) {
      notes.appendChild(el("div", "pfas-sheet-help", "Reset removes " + get("set-by") + ": " + get("tier-group") +
                           ", " + get("tier-scope") + ". It sets " + get("covers") + ". Undo reset restores it until Save."));
    }
  }
  /* after a redraw: the drawer's cell found again (and drawn), or the drawer closed */
  function follow() {
    var drawer = drawerOf();
    if (!on || !drawer || !drawer.el || drawer.el.getAttribute("data-open") !== "true" || !drawer.el.contains(on.body)) {
      on = null;
      return;
    }
    var td = findCell(on.row, on.matrix);
    if (!td) { on = null; drawer.close(); return; }
    reveal(td);
    on.td = td;
    drawer.opener = td;
    drawer.el.querySelector("h2").textContent = td.getAttribute("data-title") || "";
    draw();
  }
  document.addEventListener("click", function (e) {
    var td = e.target.closest ? e.target.closest("#qc-windows td[data-window]") : null;
    if (td) { openWindow(td); }
  });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Enter" && e.key !== " ") { return; }
    var td = e.target.closest ? e.target.closest("#qc-windows td[data-window]") : null;
    if (td) { e.preventDefault(); openWindow(td); }
  });
  reopen();
  reachable();
})();

/* Sections that open and close (details.pfas-sec): a tab opens with every
   section closed, and the browser remembers which the person opened, per
   method and tab (localStorage "pfas.mp.sec.<method>.<tab>": the open
   sections' data-sec). Storage refused (a private window) only forgets. A
   field the browser refuses on submit inside a closed section opens it, so
   the refusal is seen. */
(function () {
  function store() {
    try { return window.localStorage || null; } catch (e) { return null; }
  }
  var idIn = document.querySelector('#profile-form [name="method_id"]');
  var method = idIn ? idIn.value : '';
  function key(pane) { return 'pfas.mp.sec.' + method + '.' + pane.id.slice(5); }
  function sections(pane) {
    return Array.prototype.slice.call(pane.querySelectorAll('details.pfas-sec[data-sec]'));
  }
  function remembered(pane) {
    try {
      var s = store(), v = s ? JSON.parse(s.getItem(key(pane)) || '[]') : [];
      return Array.isArray(v) ? v : [];
    } catch (e) { return []; }
  }
  function remember(pane) {
    var open = sections(pane).filter(function (d) { return d.open; })
                             .map(function (d) { return d.getAttribute('data-sec'); });
    try { var s = store(); if (s) { s.setItem(key(pane), JSON.stringify(open)); } } catch (e) {}
  }
  Array.prototype.forEach.call(document.querySelectorAll('.pfas-pane'), function (pane) {
    if (!pane.id || pane.id.indexOf('pane-') !== 0) { return; }
    var open = remembered(pane);
    sections(pane).forEach(function (d) {
      if (open.indexOf(d.getAttribute('data-sec')) !== -1) { d.open = true; }
      /* toggle does not bubble: one listener per section */
      d.addEventListener('toggle', function () { remember(pane); });
    });
  });
  document.addEventListener('invalid', function (e) {
    var d = e.target && e.target.closest ? e.target.closest('details.pfas-sec') : null;
    if (d) { d.open = true; }
  }, true);
})();
