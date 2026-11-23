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
    final_volume: 'Dilutions are recorded at this stage, one row each: diluted from, fold, route and aliquot. The extraction record prints them.',
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

  /* One row: the cells are made once and redrawn in place, so the row
     keeps the focus the drawer hands back on close. No button stands in
     the row: a click on it (or Enter) opens the stage's drawer, and Edit
     is its menu (data-row-actions, the event "stage-edit"). */
  var STAGE_ACTIONS = JSON.stringify([{ label: 'Edit', event: 'stage-edit' }]);
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
                  solution: stageEl('td'), pedigree: stageEl('td') };
    order.appendChild(cells.n);
    var stage = stageEl('td', 'mp-stage-cell');
    stage.appendChild(cells.name);
    stage.appendChild(cells.slug);
    [order, stage, cells.records, cells.solution, cells.pedigree].forEach(function(td) { row.appendChild(td); });
    row._cells = cells;
    row.setAttribute('data-row-actions', STAGE_ACTIONS);
    row.addEventListener('pfas:row-action', function(e) {
      if (e.detail && e.detail.name === 'stage-edit') { openStageDrawer(row); }
    });
    /* the whole row opens the stage; not its drag handle, not the touch
       screen's dots, not the lift of a long press (which opened the menu) */
    row.addEventListener('pointerdown', function() { row._downAt = Date.now(); });
    row.addEventListener('click', function(e) {
      var t = e.target;
      if (t && t.closest && t.closest('.grip, button, a[href], input, select, textarea')) { return; }
      if (row._downAt && Date.now() - row._downAt > 500) { return; }
      openStageDrawer(row);
    });
    row.addEventListener('keydown', function(e) {
      if (e.key === 'Enter' && e.target === row) { e.preventDefault(); openStageDrawer(row); }
    });
    document.getElementById('stage-list').appendChild(row);
    var comps = window.PFAS && window.PFAS.components;
    if (comps && comps.rows) { comps.rows.init(row); }
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
        /* the row goes: the focus returns to Add */
        drawer.opener = document.getElementById('stage-add');
        removeStageRow(row);
        drawer.close();
      });
      foot.appendChild(remove);
    }
    drawer.open(row ? (base.name || 'Stage ' + base.order) : 'New stage', form,
                { footer: foot, cls: 'is-dialog', focus: inputs.name,
                  opener: row || document.getElementById('stage-add') });
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
   copy written to the tier's input on change. On this cell: the window
   from its tier, an own window or Off, and each blank the method holds
   judged here or off, written to the "Set on one cell" rows (ownEditor);
   every other action is a tier's. "New tier for selected cells" inserts a
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
        /* the tiers of the same edits, drawn under their QC types in the Rules list */
        drawTiers(box);
        if (window.PFAS && window.PFAS.components) {
          window.PFAS.components.sheet.init(fresh);
          /* greyed while the rule row as set on the page is Off */
          if (window.PFAS.components.muteIf) { window.PFAS.components.muteIf(document); }
        }
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
    /* Low level shown, then a view with no low-level tier: the grid goes
       back to the ordinary spike (an Off rule only greys Low level) */
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
  function tierEditor(prefix, title, core) {
    var reals = tierInputs(prefix), c = comps();
    if (!reals.length || !c) { return null; }
    function real(tail) { return reals.filter(function (n) { return n.name === prefix + tail; })[0] || null; }
    /* an LFSM tier writes its LFSMD tier too; an LFSMD tier with an LFSM
       tier of its name edits its RPD alone */
    var pair = partner(prefix, "LFSM", "LFSMD"), follows = partner(prefix, "LFSMD", "LFSM");
    function mirror(tail, value) {
      var t = pair && PAIRED.indexOf(tail) >= 0 ? tierInputs(pair).filter(function (n) {
        return n.name === pair + tail;
      })[0] : null;
      if (t && t.value !== value) { t.value = value; fire(t); }
    }
    function copy(tail, number) {
      var r = real(tail);
      if (!r) { return null; }
      var n = copyOf(r);
      if (number) { n.type = "number"; }        /* a window's end, drawn as one whatever the row draws */
      n.addEventListener("change", function () {
        if (r.value !== n.value) { r.value = n.value; fire(r); }
        mirror(tail, r.value);
      });
      return n;
    }
    var box = el("div", "pfas-sheet-form");
    box.appendChild(el("div", "pfas-sheet-flabel", title));
    if (follows) {
      var only = copy("rpd_5fmax", true);
      box.appendChild(el("div", "pfas-sheet-help", "Name, analytes and matrices as LFSM " + tierWords(keyOf(follows).name) +
                                                    ", set there."));
      if (only) {
        box.appendChild(field("RPD", only));
        c.num(only);
      }
      return box;
    }
    if (pair) {
      box.appendChild(el("div", "pfas-sheet-help", "LFSMD " + tierWords(keyOf(pair).name) +
                                                    " takes this name, these analytes and these matrices too."));
      /* the matrix picker writes the tier's own list: followed below */
      pairing = { prefix: prefix, mirror: mirror, box: box };
    }
    var name = copy("name"), group = copy("analyte_5fgroup"), scope = copy("matrix_5fscope");
    if (name) {
      box.appendChild(field("Name", name));
      var carry = carryLine(prefix, pair, real("name"), name);
      if (carry) { box.appendChild(carry); }
    }
    /* the core tier: every analyte no other tier takes falls back to it, so
       it applies to all or other analytes only */
    if (group && core) {
      Array.prototype.forEach.call(group.querySelectorAll("option"), function (o) {
        if (CORE_GROUPS.indexOf(o.value) < 0 && o.value !== group.value) { group.removeChild(o); }
      });
    }
    if (group) {
      box.appendChild(field("Applies to", group, core ? "The core tier: every analyte no other tier takes falls back to it." : ""));
    }
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
  /* A stored tier renamed carries its state, limits and flag (the server
     matches it by the name it was stored under). While the name differs
     from the stored one, a line says so, with a switch, on by default;
     turned off, it posts cfresh__<collection>__<index> = 1 for the tier (and
     its LFSMD twin), so the tier starts afresh. A new tier draws none. */
  function freshName(prefix) { return prefix.replace(/^c__/, "cfresh__").replace(/__$/, ""); }
  function freshInput(prefix) {
    var want = freshName(prefix);
    return Array.prototype.filter.call(document.querySelectorAll('[form="section-qc"][name]'), function (n) {
      return n.name === want;
    })[0] || null;
  }
  function setFresh(prefix, on) {
    var n = freshInput(prefix);
    if (!on) {
      if (n && n.parentNode) { n.parentNode.removeChild(n); }
      return;
    }
    if (n) { return; }
    n = el("input");
    n.type = "hidden";
    n.name = freshName(prefix);
    n.setAttribute("form", "section-qc");
    n.value = "1";
    (document.getElementById("section-qc") || document.body).appendChild(n);
  }
  function carryLine(prefix, pair, real, copied) {
    var stored = real ? real.defaultValue : "";
    if (!stored) { return null; }
    var wrap = el("div", "pfas-sheet-field mp-tier-carry");
    wrap.appendChild(el("div", "pfas-sheet-flabel", "Carry across"));
    var lab = el("label", "pfas-switch"), cb = el("input");
    cb.type = "checkbox";
    cb.checked = !freshInput(prefix);
    cb.setAttribute("aria-label", "Carry across the rename");
    lab.appendChild(cb);
    lab.appendChild(el("span", "pfas-switch-track"));
    wrap.appendChild(lab);
    wrap.appendChild(el("div", "pfas-sheet-help", "Its state, limits and flag carry across the rename. " +
                                                  "Off, the tier starts afresh under its new name."));
    function apply() {
      var renamed = real.value.trim() !== stored;
      wrap.hidden = !renamed;
      [prefix].concat(pair ? [pair] : []).forEach(function (p) { setFresh(p, renamed && !cb.checked); });
    }
    cb.addEventListener("change", apply);
    copied.addEventListener("change", apply);
    copied.addEventListener("input", function () {
      wrap.hidden = copied.value.trim() === stored;
    });
    apply();
    return wrap;
  }
  /* the fields an LFSMD tier takes from the LFSM tier of its name */
  var PAIRED = ["name", "analyte_5fgroup", "matrix_5fscope", "matrices", "low_5flevel_5fx_5frl"];
  function qcOf(prefix) {
    var n = tierInputs(prefix)[0], w = n && n.closest ? n.closest(".mp-qc-tiers") : null;
    return w ? w.getAttribute("data-qc") : "";
  }
  /* a tier row's name and whether it is a low-level tier, from its inputs */
  function keyOf(prefix) {
    var ins = tierInputs(prefix);
    function v(tail) {
      var n = ins.filter(function (x) { return x.name === prefix + tail; })[0];
      return n ? (n.value || "").trim() : "";
    }
    return { name: v("name"), low: v("low_5flevel_5fx_5frl") !== "" };
  }
  /* the `to` tier stored under a `from` tier's name, ordinary with ordinary
     and low level with low level: a pairing by name alone, as the tier view
     pairs them; "" where `prefix` is no `from` tier or none matches */
  function partner(prefix, from, to) {
    if (!prefix || qcOf(prefix) !== from) { return ""; }
    var me = keyOf(prefix), hit = "";
    if (!me.name) { return ""; }
    Array.prototype.forEach.call(tierRows(to), function (tr) {
      var n = rowInputs(tr).filter(function (x) { return /__name$/.test(x.name); })[0];
      if (!n || hit) { return; }
      var p = n.name.slice(0, -4), k = keyOf(p);
      if (k.name === me.name && k.low === me.low) { hit = p; }
    });
    return hit;
  }
  /* the open LFSM editor's pairing: a change to its tier's matrix list
     (written by the picker) is written to its LFSMD tier, while the editor
     is on the page; one listener, whatever the editors drawn */
  var pairing = null;
  document.addEventListener("change", function (e) {
    var t = e.target;
    if (!pairing || !t || !t.name || t.name !== pairing.prefix + "matrices") { return; }
    if (!document.contains(pairing.box)) { pairing = null; return; }
    pairing.mirror("matrices", t.value);
  });
  /* Edit tier in a tier's card, or in its node's row menu (`opener`, where
     the focus goes back): the tier's editor in the shared drawer */
  function editTier(b, opener) {
    var drawer = drawerOf();
    if (!b || !drawer) { return; }
    var title = b.getAttribute("data-tier-title") || "Tier";
    var editor = tierEditor(b.getAttribute("data-tier-edit"), title, b.getAttribute("data-tier-core") === "1");
    if (!editor) { return; }
    drawer.open(b.getAttribute("data-tier-head") || title, editor,
                { footer: el("div", "pfas-drawer-actions"), cls: "is-dialog", opener: opener || b });
    drawer.opener = opener || drawer.opener || b;
  }
  document.addEventListener("click", function (e) {
    editTier(e.target.closest ? e.target.closest("[data-tier-edit]") : null);
  });
  var CORE_GROUPS = ["all", "linked"];
  function tierName(prefix) {
    return tierInputs(prefix).filter(function (n) { return n.name === prefix + "name"; })[0] || null;
  }
  /* Remove tier in a tier's card: its row, and on LFSM the LFSMD tier of its
     name, removed on Save and put back by Undo until then; the core tier
     draws no Remove */
  /* a tier's name as the page shows it: a seeded key in words (the rules
     list's data-tier-words), a typed name as typed */
  function tierWords(name) {
    var l = document.getElementById("rules-list"), w = {};
    try { w = JSON.parse((l && l.getAttribute("data-tier-words")) || "{}") || {}; } catch (e) { w = {}; }
    return w[name] || name;
  }
  function removeTier(prefix) {
    if (!prefix) { return; }
    var qc = qcOf(prefix), pair = partner(prefix, "LFSM", "LFSMD");
    [[qc, prefix], ["LFSMD", pair]].forEach(function (x) {
      var n = x[1] ? tierName(x[1]) : null;
      if (n && n.value) { resetTier(x[0], n, x[0] + " tier " + tierWords(n.value)); }
    });
  }
  document.addEventListener("click", function (e) {
    var b = e.target.closest ? e.target.closest("[data-tier-remove]") : null;
    if (b) { removeTier(b.getAttribute("data-tier-remove")); }
  });
  /* A tier node's row menu (profile_grids._tier_menu): Edit tier, +
     Sub-group, Edit cells and Remove tier; a sub-group node's: Edit cells
     and Remove sub-group. Each acts on its node's card, as the card's own
     buttons do; an entry the server drew refused never acts. */
  document.addEventListener("pfas:row-action", function (e) {
    var node = e.detail && e.detail.row, name = e.detail ? e.detail.name : "";
    if (!node || !node.closest || !node.closest("#rules-list")) { return; }
    var card = cardOf(node);
    if (!card) { return; }
    var edit = card.querySelector("[data-tier-edit]");
    var prefix = edit ? edit.getAttribute("data-tier-edit") : "";
    if (name === "tier-edit") { editTier(edit, node); }
    else if (name === "tier-remove") {
      /* the tier's own Remove, never a low-level tier's beside it */
      var rm = Array.prototype.filter.call(card.querySelectorAll("[data-tier-remove]"), function (b) {
        return b.getAttribute("data-tier-remove") === prefix;
      })[0];
      if (rm) { removeTier(prefix); }
    }
    else if (name === "tier-sub") { subGroup(card, node); }
    else if (name === "tier-cells") {
      var first = subCards(node.getAttribute("data-hier-target"))[0];
      if (first) { editCells(first, node); }
    }
    else if (name === "cells-edit") { editCells(card, node); }
    else if (name === "cells-remove") { removeCells(card); }
  });
  /* Edit cells in a sub-group's card */
  document.addEventListener("click", function (e) {
    var b = e.target.closest ? e.target.closest("[data-cells-edit]") : null, l = rulesList();
    if (!b || !l) { return; }
    var card = Array.prototype.filter.call(l.querySelectorAll("[data-hier-card]"), function (c) {
      return c.getAttribute("data-hier-card") === b.getAttribute("data-cells-edit");
    })[0];
    if (card) { editCells(card, b); }
  });
  /* + Sub-group and Edit cells: the cells under a tier set on their own,
     written as the analyte grid's cell drawer writes them (setOwn: the
     "Set on one cell" collection's rows, found by QC type, analyte and
     matrix, added with its own + Add), so the tab's Save stores them and
     the preview draws them as the tier's sub-groups. Which cells a tier
     covers is the server's (data-cells-of: the engine's choice); the
     dialog only chooses among them. The choice on the cells: Own window
     (its range, or an RPD limit) or Not judged here. */
  function cellList(text) {
    try { var v = JSON.parse(text || "[]"); return Array.isArray(v) ? v : []; } catch (e) { return []; }
  }
  function cellsOf(card) {
    function get(k) { return card.getAttribute("data-cells-" + k) || ""; }
    return { qc: get("qc"), rpd: get("kind") === "rpd", lo: get("lo"), hi: get("hi"), head: get("head"),
             off: get("off") === "1" };
  }
  function subCards(key) {
    var l = rulesList();
    return l ? Array.prototype.filter.call(l.querySelectorAll("[data-sub-of]"), function (c) {
      return c.getAttribute("data-sub-of") === key;
    }) : [];
  }
  /* "PFOA in Eggs, Milk; PFOS in Eggs" */
  function cellWords(cells) {
    return cells.map(function (x) { return x[1] + " in " + x[2].join(", "); }).join("; ");
  }
  function cellCount(cells) {
    var n = cells.reduce(function (t, x) { return t + x[2].length; }, 0);
    return n + (n === 1 ? " cell" : " cells");
  }
  /* LFSMD follows LFSM: an LFSM cell not judged here leaves its LFSMD cell
     nothing to judge either. Not judged here on LFSM cells writes each
     matching LFSMD cell off, unless that cell holds an RPD limit of its
     own; an LFSM cell that was off and is set to Own window or sent back to
     its tier clears each matching LFSMD cell that is off. While an LFSM
     cell is off, its LFSMD cell is not switched off on its own. Only where
     the method holds LFSMD. */
  var FOLLOWS_OFF = "Off with LFSM: LFSMD follows LFSM here.";
  function holdsLfsmd() { return !!document.querySelector('.mp-qc-tiers[data-qc="LFSMD"]'); }
  function cellOff(qc, kw, m) {
    var tr = findCellRow(qc, kw, m), n = tr ? cellInput(tr, "off") : null;
    return !!(n && n.checked);
  }
  function lfsmOffIn(cells) {
    return cells.some(function (x) { return x[2].some(function (m) { return cellOff("LFSM", x[0], m); }); });
  }
  /* writes `mode` on the cells of `qc`, and on LFSM the LFSMD cells that follow them */
  function writeCells(qc, cells, mode, lo, hi, rpd) {
    cells.forEach(function (x) {
      x[2].forEach(function (m) {
        var was = cellOff(qc, x[0], m);
        setOwn(qc, x[0], [m], mode, lo, hi, rpd);
        if (qc !== "LFSM" || !holdsLfsmd()) { return; }
        var tr = findCellRow("LFSMD", x[0], m), limit = tr ? cellInput(tr, "rpd_5fmax") : null;
        var dupOff = cellOff("LFSMD", x[0], m);
        if (mode === "off") {
          if (!(tr && !dupOff && limit && limit.value !== "")) { setOwn("LFSMD", x[0], [m], "off"); }
        } else if (was && dupOff) {
          setOwn("LFSMD", x[0], [m], "");
        }
      });
    });
  }
  /* the choice and the window, appended to `box`; `changed` hears each
     change; `cellsNow` gives the cells it will write */
  function cellsChoice(d, box, changed, cellsNow) {
    var c = comps(), mode = d.off ? "off" : "window";
    var seg = el("div", "pfas-seg pfas-seg-sm is-fit");
    seg.setAttribute("role", "group");
    seg.setAttribute("aria-label", "On these cells");
    var why = el("div", "pfas-sheet-help", FOLLOWS_OFF);
    why.setAttribute("data-cells-why", "");
    /* an LFSMD cell whose LFSM cell is off is not switched off on its own */
    function refused() { return d.qc === "LFSMD" && lfsmOffIn(cellsNow()); }
    function note() {
      var no = refused(), b = seg.querySelector('.pfas-seg-item[data-value="off"]');
      if (b) { b.disabled = no; }
      why.hidden = !no;
    }
    var lo = el("input"), hi = el("input"), win;
    [lo, hi].forEach(function (n) { n.type = "number"; n.setAttribute("step", "any"); n.setAttribute("min", "0"); });
    lo.value = d.rpd ? "" : d.lo;
    hi.value = d.hi;
    lo.setAttribute("aria-label", "Own window minimum");
    hi.setAttribute("aria-label", d.rpd ? "Own RPD limit" : "Own window maximum");
    if (d.rpd) { win = field("RPD limit", hi); }
    else {
      var w = el("div");
      w.setAttribute("data-range", "");
      w.setAttribute("data-scale", "0,200");
      w.setAttribute("data-unit", "%");
      w.appendChild(lo);
      w.appendChild(hi);
      win = field("Own window", w);
    }
    function show() {
      Array.prototype.forEach.call(seg.querySelectorAll(".pfas-seg-item"), function (x) {
        x.setAttribute("aria-pressed", x.getAttribute("data-value") === mode ? "true" : "false");
      });
      win.hidden = mode !== "window";
      note();
      changed();
    }
    [["window", "Own window"], ["off", "Not judged here"]].forEach(function (o) {
      var b = el("button", "pfas-seg-item", o[1]);
      b.type = "button";
      b.setAttribute("data-value", o[0]);
      b.addEventListener("click", function () { mode = o[0]; show(); });
      seg.appendChild(b);
    });
    box.appendChild(field("On these cells", seg));
    box.appendChild(why);
    box.appendChild(win);
    if (c && c.seg) { c.seg(seg); }
    if (c) { if (d.rpd) { c.num(hi); } else { c.range(win.querySelector("[data-range]")); } }
    [lo, hi].forEach(function (n) { n.addEventListener("input", changed); n.addEventListener("change", changed); });
    show();
    return {
      mode: function () { return mode; },
      note: note,
      ready: function () {
        return mode === "off" ? !refused() : (hi.value !== "" && (d.rpd || lo.value !== ""));
      },
      write: function (qc, cells) { writeCells(qc, cells, mode, lo.value, hi.value, d.rpd); }
    };
  }
  function cellsDialog(d, box, opener, ready, apply) {
    var drawer = drawerOf();
    var foot = el("div", "pfas-drawer-actions"), go = el("button", "btn btn-primary", "Set cells");
    go.type = "button";
    go.setAttribute("data-cells-set", "");
    go.addEventListener("click", function () {
      if (go.disabled) { return; }
      apply();
      drawer.close();
    });
    foot.appendChild(go);
    drawer.open(d.head, box, { footer: foot, cls: "is-dialog", opener: opener });
    drawer.opener = opener;
    return function () { go.disabled = !ready(); };
  }
  /* a choice among `options` ([[value, label]]) in the shared picker, its
     list in the picker's own nameless field: it posts nothing */
  function choosing(options, chosen, noun) {
    var pick = el("div", "pfas-picker"), held = el("input");
    held.type = "hidden";
    held.value = JSON.stringify(chosen);
    pick.appendChild(held);
    pick.setAttribute("data-options", JSON.stringify(options));
    pick.setAttribute("data-noun", noun);
    pick.setAttribute("data-title", "this sub-group");
    return { el: pick, value: function () { return cellList(held.value); } };
  }
  function subGroup(card, opener) {
    var c = comps(), d = cellsOf(card), covered = cellList(card.getAttribute("data-cells-of"));
    if (!c || !drawerOf() || !covered.length) { return; }
    var matrices = [];
    covered.forEach(function (x) { x[2].forEach(function (m) { if (matrices.indexOf(m) < 0) { matrices.push(m); } }); });
    var box = el("div", "pfas-sheet-form");
    box.appendChild(el("div", "pfas-sheet-help", "Only the analytes and matrices this tier covers."));
    var an = choosing(covered.map(function (x) { return [x[0], x[1]]; }), [], "analytes");
    var ma = choosing(matrices.map(function (m) { return [m, m]; }), matrices, "matrices");
    box.appendChild(field("Analytes", an.el));
    box.appendChild(field("Matrices", ma.el));
    var line = el("div", "pfas-sheet-help"), sync = function () {};
    /* the cells chosen: each analyte chosen in the matrices chosen that it is covered in */
    function chosen() {
      var as = an.value(), ms = ma.value();
      return covered.filter(function (x) { return as.indexOf(x[0]) >= 0; }).map(function (x) {
        return [x[0], x[1], x[2].filter(function (m) { return ms.indexOf(m) >= 0; })];
      }).filter(function (x) { return x[2].length; });
    }
    function recount() {
      var cells = chosen();
      line.textContent = cells.length ? cellCount(cells) + ": " + cellWords(cells) : "No cell chosen yet.";
      if (choice) { choice.note(); }
      sync();
    }
    var choice = cellsChoice(d, box, recount, chosen);
    box.appendChild(line);
    /* a pick (the pickers' fields fire a bubbling change) redraws the count */
    box.addEventListener("change", recount);
    sync = cellsDialog(d, box, opener, function () { return chosen().length > 0 && choice.ready(); }, function () {
      choice.write(d.qc, chosen());
    });
    c.picker(an.el);
    c.picker(ma.el);
    recount();
  }
  function editCells(card, opener) {
    var d = cellsOf(card), cells = cellList(card.getAttribute("data-cells"));
    if (!comps() || !drawerOf() || !cells.length) { return; }
    var box = el("div", "pfas-sheet-form");
    box.appendChild(field(cellCount(cells), el("div", "pfas-sheet-help", cellWords(cells))));
    var sync = function () {};
    var choice = cellsChoice(d, box, function () { sync(); }, function () { return cells; });
    sync = cellsDialog(d, box, opener, function () { return choice.ready(); }, function () { choice.write(d.qc, cells); });
    sync();
  }
  /* Remove sub-group: its cells go back to the tier (their rows cleared,
     as the cell drawer's From its tier), on LFSM with the LFSMD cells off
     that follow them */
  function removeCells(card) {
    writeCells(cellsOf(card).qc, cellList(card.getAttribute("data-cells")), "");
  }
  /* A spike level in a tier card is a cell (data-spike, the one spike level
     input it shows): it opens the shared cell editor on that input, the
     editor the spike level collection's own cell opens, whose copy posts
     nothing and writes the input with input / change on Done */
  function openSpike(td) {
    var real = Array.prototype.filter.call(document.querySelectorAll('[form="section-qc"][name]'), function (n) {
      return n.name === td.getAttribute("data-spike");
    })[0];
    var cell = real && real.closest ? real.closest("td") : null;
    var btn = cell ? cell.querySelector(".pfas-cell-btn") : null, drawer = drawerOf();
    if (!btn) { return; }
    btn.click();
    if (drawer) { drawer.opener = td; }
  }
  document.addEventListener("click", function (e) {
    var td = e.target.closest ? e.target.closest("#rules-list td[data-spike]") : null;
    if (td) { openSpike(td); }
  });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Enter" && e.key !== " ") { return; }
    var td = e.target.closest ? e.target.closest("#rules-list td[data-spike]") : null;
    if (td) { e.preventDefault(); openSpike(td); }
  });
  /* + Add tier under a QC type's tiers: a row at the end of its collection,
     after the core tier, so it never takes the core tier's place; it applies
     nowhere until its matrices are listed, so adding it changes no judgement.
     On LFSM the LFSMD tier of its name is added too. Its editor opens. */
  function freeName() {
    var used = {};
    ["LFSM", "LFSMD"].concat(Array.prototype.map.call(document.querySelectorAll(".mp-qc-tiers[data-qc]"), function (w) {
      return w.getAttribute("data-qc");
    })).forEach(function (q) {
      Array.prototype.forEach.call(tierRows(q), function (tr) {
        rowInputs(tr).forEach(function (n) { if (/__name$/.test(n.name)) { used[n.value.trim()] = true; } });
      });
    });
    for (var i = 1; ; i++) { if (!used["new_tier_" + i]) { return "new_tier_" + i; } }
  }
  document.addEventListener("click", function (e) {
    var b = e.target.closest ? e.target.closest("[data-tier-add]") : null, drawer = drawerOf();
    if (!b || !drawer) { return; }
    var qc = b.getAttribute("data-tier-add"), name = freeName();
    var prefix = insertTier(qc, "", "key", "listed", "[]");
    if (!prefix) { return; }
    setValue(tierName(prefix), name);
    if (qc === "LFSM" && document.querySelector('.mp-qc-tiers[data-qc="LFSMD"]')) {
      var twin = insertTier("LFSMD", "", "key", "listed", "[]");
      if (twin) { setValue(tierName(twin), name); }
    }
    var editor = tierEditor(prefix, name, false);
    if (!editor) { return; }
    drawer.open("New tier \u00b7 " + qc + " " + name, editor,
                { footer: el("div", "pfas-drawer-actions"), cls: "is-dialog", opener: b });
    drawer.opener = b;
  });
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
  /* the Undo bar, drawn alike under the grid's pickers (#qc-resets) and
     above the Rules list, where a tier card's Remove tier is pressed */
  function drawResets() {
    Array.prototype.forEach.call(document.querySelectorAll("#qc-resets, [data-qc-resets]"), function (box) {
      box.textContent = "";
      resets.forEach(function (r) {
        var b = el("button", "btn-sm btn-secondary", "Undo reset");
        b.type = "button";
        b.addEventListener("click", function () { undoReset(r); });
        box.appendChild(el("span", "", r.label + " is removed on Save."));
        box.appendChild(b);
      });
      box.hidden = !resets.length;
    });
  }
  function undoReset(r) {
    resets = resets.filter(function (x) { return x !== r; });
    var input = nameInput(r.qc, r.row), tr = tierRows(r.qc)[r.row];
    if (r.fields && tr) {
      var ins = rowInputs(tr);
      r.fields.forEach(function (v, i) { if (ins[i]) { setValue(ins[i], v); } });
    } else if (input) { setValue(input, r.value); }
    drawResets();
  }
  /* a row added on this page (the add-row template's cf-new-row) is gone
     only with every field cleared: a new row with values but no name is
     refused at Save */
  function clearRow(tr) {
    var ins = rowInputs(tr), was = ins.map(function (n) { return n.value; });
    ins.forEach(function (n) { setValue(n, ""); });
    return was;
  }
  function resetTier(qc, input, label) {
    if (!input || !input.value) { return; }
    var tr = input.closest("tr"), row = Array.prototype.indexOf.call(tierRows(qc), tr);
    if (row < 0) { return; }
    var r = { qc: qc, row: row, value: input.value, label: label };
    if (tr.classList.contains("cf-new-row")) { r.fields = clearRow(tr); } else { setValue(input, ""); }
    resets.push(r);
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
  /* a setting on one analyte's cell: the rows of the "Set on one cell"
     collection (form#section-qc), one per QC type, analyte and matrix,
     found by those three values and added with the collection's own
     + Add, so the tab's Save stores them and the grid's preview draws them.
     A cell of a column standing for several matrices sets each of them. */
  function cellsWrap() {
    var t = document.querySelector('table.cf-coll[data-sheet="qc_cells"]');
    return t ? t.closest(".cf-coll-wrap") : null;
  }
  function cellRows() {
    var w = cellsWrap();
    return w ? Array.prototype.slice.call(w.querySelectorAll("table.cf-coll tbody tr:not(.pfas-empty-row)")) : [];
  }
  function cellInput(tr, field) {
    return rowInputs(tr).filter(function (n) { return n.name.slice(-(field.length + 2)) === "__" + field; })[0] || null;
  }
  function findCellRow(qc, kw, m) {
    return cellRows().filter(function (tr) {
      var k = cellInput(tr, "cell"), q = cellInput(tr, "qc_5ftype"), a = cellInput(tr, "analyte"), x = cellInput(tr, "matrix");
      return k && k.value && q && a && x && q.value === qc && a.value === kw && x.value === m;
    })[0] || null;
  }
  function addCellRow() {
    var w = cellsWrap(), add = w ? w.querySelector(".cf-add-row") : null, back = document.activeElement;
    if (!add) { return null; }
    add.click();
    if (back && back.focus) { back.focus(); }      /* the drawer keeps the focus */
    var rows = cellRows();
    return rows[rows.length - 1] || null;
  }
  function put(tr, field, v) {
    var n = cellInput(tr, field);
    if (!n) { return; }
    if (n.type === "checkbox") {
      if (n.checked !== !!v) { n.checked = !!v; fire(n); }
    } else {
      setValue(n, v === null || v === undefined ? "" : String(v));
    }
  }
  function clearCellRow(tr) {
    ["cell", "qc_5ftype", "analyte", "matrix", "recovery_5fmin", "recovery_5fmax", "rpd_5fmax"].forEach(function (f) {
      put(tr, f, "");
    });
    put(tr, "off", false);
  }
  /* mode "" removes the setting (the tier applies), "off" switches the check
     off there, "window" sets lo – hi (an RPD type: hi alone) */
  function setOwn(qc, kw, matrices, mode, lo, hi, rpd) {
    matrices.forEach(function (m) {
      var tr = findCellRow(qc, kw, m);
      if (!mode) { if (tr) { clearCellRow(tr); } return; }
      tr = tr || addCellRow();
      if (!tr) { return; }
      put(tr, "cell", qc + " \u00b7 " + kw + " \u00b7 " + m);
      put(tr, "qc_5ftype", qc);
      put(tr, "analyte", kw);
      put(tr, "matrix", m);
      put(tr, "off", mode === "off");
      put(tr, "recovery_5fmin", mode === "window" && !rpd ? lo : "");
      put(tr, "recovery_5fmax", mode === "window" && !rpd ? hi : "");
      put(tr, "rpd_5fmax", mode === "window" && rpd ? hi : "");
    });
  }
  function json(td, k) {
    try { return JSON.parse(td.getAttribute("data-" + k) || "[]"); } catch (e) { return []; }
  }
  /* what the drawer offers on the cell itself: whether its window comes
     from its tier, is set here or the check is off here; the window it
     sets; and each blank the method holds, judged here or off */
  function ownEditor(td) {
    var c = comps(), get = function (k) { return td.getAttribute("data-" + k) || ""; };
    var kw = get("analyte"), qc = get("qc"), ms = json(td, "matrices");
    if (!kw || !ms.length) { return null; }
    var rpd = get("own-kind") === "rpd";
    var box = el("div", "pfas-sheet-form");
    box.appendChild(el("div", "pfas-sheet-flabel", "On this cell"));
    var mode = get("own"), seg = el("div", "pfas-seg pfas-seg-sm is-fit");
    seg.setAttribute("role", "group");
    seg.setAttribute("aria-label", "Window");
    /* an LFSMD cell whose LFSM cell is off is not switched off on its own */
    var follows = qc === "LFSMD" && lfsmOffIn([[kw, kw, ms]]);
    [["", "From its tier"], ["window", "Own window"], ["off", "Off"]].forEach(function (o) {
      var b = el("button", "pfas-seg-item", o[1]);
      b.type = "button";
      b.setAttribute("aria-pressed", o[0] === mode ? "true" : "false");
      b.disabled = follows && o[0] === "off";
      b.addEventListener("click", function () {
        seg.querySelectorAll(".pfas-seg-item").forEach(function (x) { x.setAttribute("aria-pressed", x === b ? "true" : "false"); });
        /* an own window starts from the window in force; the grid's redraw
           draws the drawer again from what is now set */
        var lo = get("own-lo") || get("lo"), hi = get("own-hi") || get("hi");
        /* on LFSM with the LFSMD cells that follow it, as a sub-group writes them */
        writeCells(qc, [[kw, kw, ms]], o[0], lo, hi, rpd);
      });
      seg.appendChild(b);
    });
    box.appendChild(field("Window", seg));
    if (follows) { box.appendChild(el("div", "pfas-sheet-help", FOLLOWS_OFF)); }
    if (c && c.seg) { c.seg(seg); }
    if (mode === "window") {
      var hiIn = el("input"), loIn = el("input");
      [loIn, hiIn].forEach(function (n) { n.type = "number"; n.setAttribute("step", "any"); n.setAttribute("min", "0"); });
      loIn.value = get("own-lo");
      hiIn.value = get("own-hi");
      loIn.setAttribute("aria-label", "Own window minimum");
      hiIn.setAttribute("aria-label", rpd ? "Own RPD limit" : "Own window maximum");
      var write = function () { writeCells(qc, [[kw, kw, ms]], "window", loIn.value, hiIn.value, rpd); };
      loIn.addEventListener("change", write);
      hiIn.addEventListener("change", write);
      if (rpd) {
        box.appendChild(field("RPD limit", hiIn));
        if (c) { c.num(hiIn); }
      } else {
        var w = el("div");
        w.setAttribute("data-range", "");
        w.setAttribute("data-scale", "0,200");
        w.setAttribute("data-unit", "%");
        w.appendChild(loIn);
        w.appendChild(hiIn);
        box.appendChild(field("Own window", w));
        if (c) { c.range(w); }
      }
    }
    if (ms.length > 1) {
      box.appendChild(el("div", "pfas-sheet-help", "Applies in " + ms.join(", ") + "."));
    }
    json(td, "blanks").forEach(function (b) {
      var lab = el("label", "pfas-switch"), cb = el("input");
      cb.type = "checkbox";
      cb.checked = !b.off;
      cb.setAttribute("aria-label", b.label + " judged");
      lab.appendChild(cb);
      lab.appendChild(el("span", "pfas-switch-track"));
      cb.addEventListener("change", function () { setOwn(b.qc, kw, ms, cb.checked ? "" : "off"); });
      box.appendChild(field(b.label + " judged", lab));
    });
    return box;
  }
  /* The Rules section's List view (profile_grids.render_rules_list): each
     rule's card holds a nameless copy of its table row's state, writing the
     row's input; the node's state line follows that input. A QC type or a
     blank set Off folds under Removed in its group, greyed and still open;
     Remove QC type sets it Off (on LFSM the LFSMD that follows it too) and
     Restore sets it Enforced (on LFSMD its LFSM too): nothing stored is
     deleted. + Add QC type shows a type the table draws hidden, with what
     it is given: its default tier, all analytes and matrices, its limit left
     to type (required, so Save waits for it). Each QC type of Analyte
     recoveries opens into its tiers, drawn under its node and moved with
     it; the grid's preview draws them again from the edits not yet saved
     (drawTiers), and Open its tiers chooses the first. */
  var STATE_WORDS = { enforced: "Enforced", evaluate: "Evaluate", off: "Off" };
  /* a state line: words, or the placard's glyph (PFAS.components.limit.line) */
  function sayState(line, v) {
    var C = window.PFAS && window.PFAS.components;
    if (C && C.limit && C.limit.line) { C.limit.line(line, v); return; }
    line.textContent = v ? (STATE_WORDS[v] || v) : (line.getAttribute("data-inherited") || "");
  }
  function rulesList() { return document.getElementById("rules-list"); }
  function ruleNodes() {
    var l = rulesList();
    return l ? Array.prototype.slice.call(l.querySelectorAll(".pfas-hier-node[data-rule-state]")) : [];
  }
  function stateInput(id) { return id ? document.getElementById(id) : null; }
  /* a rule node's name: its title's words, without the state glyph it carries */
  function nodeTitle(node) {
    var t = node.querySelector(".pfas-hier-node-t"), g = t.querySelector(".pfas-state-g");
    return g ? t.textContent.slice(0, t.textContent.length - g.textContent.length) : t.textContent;
  }
  function nodeOfCode(code) {
    return ruleNodes().filter(function (n) { return n.getAttribute("data-rule-code") === code; })[0] || null;
  }
  function cardOf(node) {
    var l = rulesList(), key = node.getAttribute("data-hier-target");
    return l ? Array.prototype.filter.call(l.querySelectorAll("[data-hier-card]"), function (c) {
      return c.getAttribute("data-hier-card") === key;
    })[0] || null : null;
  }
  /* a QC type's tiers in the list: the nodes and lines under its node
     (data-tier-of), and their cards (data-tier-card-of) */
  function tiersOf(key, attr) {
    var l = rulesList();
    return l ? Array.prototype.filter.call(l.querySelectorAll("[" + (attr || "data-tier-of") + "]"), function (k) {
      return k.getAttribute(attr || "data-tier-of") === key;
    }) : [];
  }
  /* the tiers follow their QC type's node: shown and hidden with it, and
     right after it wherever it sits (the list or its group's Removed) */
  function carryTiers(node) {
    var at = node;
    tiersOf(node.getAttribute("data-hier-target")).forEach(function (k) {
      k.hidden = !!node.hidden;
      if (at.nextSibling !== k) { at.parentNode.insertBefore(k, at.nextSibling); }
      at = k;
    });
  }
  /* The preview's tiers (profile_grids.tier_trees, one carrier per QC
     type) put in the list: each type's tier nodes and lines in place of the
     ones under its node, its tier cards in place of theirs, and what its
     node and card draw from its tiers (data-tier-part) in place; the chosen
     node kept, or its QC type's node when that tier is gone. Nothing posts. */
  function drawTiers(box) {
    var l = rulesList(), c = comps();
    if (!l) { return; }
    var cards = l.querySelector(".pfas-hier-cards");
    var sel = l.querySelector(".pfas-hier-node.is-selected");
    var key = sel ? sel.getAttribute("data-hier-target") : "", owner = sel ? sel.getAttribute("data-tier-of") : "";
    Array.prototype.forEach.call(box.querySelectorAll("[data-qc-tree]"), function (w) {
      var own = w.getAttribute("data-tier-owner");
      var node = ruleNodes().filter(function (n) { return n.getAttribute("data-hier-target") === own; })[0];
      if (!node || !cards) { return; }
      tiersOf(own).concat(tiersOf(own, "data-tier-card-of")).forEach(function (k) { k.parentNode.removeChild(k); });
      var at = node;
      Array.prototype.slice.call(w.querySelectorAll("[data-tier-of]")).forEach(function (k) {
        at.parentNode.insertBefore(k, at.nextSibling);
        k.hidden = !!node.hidden;
        at = k;
      });
      Array.prototype.slice.call(w.querySelectorAll("[data-tier-card-of]")).forEach(function (k) { cards.appendChild(k); });
      Array.prototype.slice.call(w.querySelectorAll("[data-tier-part]")).forEach(function (p) {
        var key = p.getAttribute("data-tier-part");
        /* Analyte recoveries' card draws each type's tier table too */
        Array.prototype.filter.call(l.querySelectorAll("[data-tier-gpart]"), function (x) {
          return x.getAttribute("data-tier-gpart") === key;
        }).forEach(function (g) {
          var copy = p.cloneNode(true);
          copy.removeAttribute("data-tier-part");
          copy.setAttribute("data-tier-gpart", key);
          g.parentNode.replaceChild(copy, g);
        });
        var was = Array.prototype.filter.call(l.querySelectorAll("[data-tier-part]"), function (x) {
          return x.getAttribute("data-tier-part") === key;
        })[0];
        if (was) { was.parentNode.replaceChild(p, was); }
      });
    });
    if (!c || !c.hier) { return; }
    c.hier.init(l);                                   /* the new bars set */
    if (key && owner && !c.hier.select(l, key, false)) { c.hier.select(l, owner, false); }
  }
  function drawRuleNode(node) {
    var input = stateInput(node.getAttribute("data-rule-state"));
    if (!input) { return; }
    var line = node.querySelector("[data-state-of]"), v = input.value;
    if (line) { sayState(line, v); }
    var card = cardOf(node), off = v === "off";
    if (!off) { node.removeAttribute("data-removed-with"); }   /* back on: no longer removed with its LFSM */
    if (card) {
      var rm = card.querySelector("[data-qc-remove]"), rs = card.querySelector("[data-qc-restore]");
      if (rm) { rm.hidden = off && node.getAttribute("data-added") !== "1"; }
      if (rs) { rs.hidden = !off || node.getAttribute("data-added") === "1"; }
    }
    if (node.getAttribute("data-removable") !== "1" || node.hidden) { return; }
    var l = rulesList(), group = node.getAttribute("data-rule-group");
    var box = l ? Array.prototype.filter.call(l.querySelectorAll("[data-removed-of]"), function (b) {
      return b.getAttribute("data-removed-of") === group;
    })[0] : null;
    if (!box) { return; }
    var inBox = node.parentNode === box;
    if (off && !inBox) { box.appendChild(node); }
    else if (!off && inBox) {
      /* back in its own place: before the first of its group drawn after it */
      var mine = Number(node.getAttribute("data-rule-order")), after = ruleNodes().filter(function (n) {
        return n.parentNode === box.parentNode && n.getAttribute("data-rule-group") === group &&
               Number(n.getAttribute("data-rule-order")) > mine;
      })[0];
      box.parentNode.insertBefore(node, after || box);
    }
    carryTiers(node);
    box.hidden = !box.querySelector(".pfas-hier-node:not([hidden])");
  }
  function drawRules() { ruleNodes().forEach(drawRuleNode); }
  document.addEventListener("change", function (e) {
    var t = e.target;
    if (!t || !t.id || !rulesList()) { return; }
    ruleNodes().forEach(function (n) { if (n.getAttribute("data-rule-state") === t.id) { drawRuleNode(n); } });
  });
  function setState(id, value) {
    var input = stateInput(id);
    if (input && input.value !== value) { input.value = value; fire(input); }
  }
  function choose(node) {
    var c = comps(), l = rulesList();
    if (node && c && c.hier && l) { c.hier.select(l, node.getAttribute("data-hier-target")); }
  }
  /* what + Add QC type gave a type, put back: its tiers' rows cleared (an
     unnamed row is not stored), its limit no longer required, hidden again */
  var added = {};
  function unAdd(code) {
    var a = added[code], node = nodeOfCode(code);
    if (!a || !node) { return; }
    a.names.forEach(function (n) { var tr = n.closest("tr"); if (tr) { clearRow(tr); } });
    a.required.forEach(function (n) { n.required = false; });
    delete added[code];
    node.removeAttribute("data-added");
    node.hidden = true;
    carryTiers(node);
    var tr = tableRow(node.getAttribute("data-hier-target"));
    if (tr) { tr.hidden = true; }
    setState(node.getAttribute("data-rule-state"), "enforced");
    choose(ruleNodes().filter(function (n) { return !n.hidden; })[0]);
  }
  function tableRow(key) {
    return Array.prototype.filter.call(document.querySelectorAll('table tr[data-row]'), function (tr) {
      return tr.getAttribute("data-row") === key && tr.closest('[data-view-of="rules"]');
    })[0] || null;
  }
  document.addEventListener("click", function (e) {
    var rm = e.target.closest ? e.target.closest("[data-qc-remove]") : null;
    var rs = e.target.closest ? e.target.closest("[data-qc-restore]") : null;
    if (!rm && !rs) { return; }
    var id = (rm || rs).getAttribute(rm ? "data-qc-remove" : "data-qc-restore");
    var node = ruleNodes().filter(function (n) { return n.getAttribute("data-rule-state") === id; })[0];
    if (!node) { return; }
    var code = node.getAttribute("data-rule-code");
    if (rm && node.getAttribute("data-added") === "1") { unAdd(code); return; }
    /* LFSMD is the LFSM's duplicate: it goes with its LFSM and comes back
       with it; restoring LFSMD brings its LFSM back too */
    var pair = code === "LFSM" ? nodeOfCode("LFSMD") : (rs && code === "LFSMD" ? nodeOfCode("LFSM") : null);
    var pairOn = pair && !pair.hidden && pair.getAttribute("data-removable") === "1";
    setState(id, rm ? "off" : "enforced");
    if (pairOn && rm) {
      var pin = stateInput(pair.getAttribute("data-rule-state"));
      if (pin && pin.value !== "off") { pair.setAttribute("data-removed-with", "LFSM"); setState(pin.id, "off"); }
    } else if (pairOn && (code === "LFSMD" || pair.getAttribute("data-removed-with") === "LFSM")) {
      pair.removeAttribute("data-removed-with");
      setState(pair.getAttribute("data-rule-state"), "enforced");
    }
    choose(node);
  });
  /* The rule table's rows are buttons (profile_grids.rule_row_opens): a
     click anywhere on a row but a control in it, Enter or Space, or its one
     menu entry presses the trigger its List card holds (the limits window,
     the Calibration window, Open Analytes), the row taking the window's
     focus back on close; a row with no such window opens its region in
     place, as its Edit did. */
  var ROW_SKIP = "a[href], button, input, select, textarea, label, summary, .pfas-menu, .pfas-seg, .pfas-switch";
  function openRuleRow(tr) {
    var c = comps(), l = rulesList(), act = tr.getAttribute("data-rule-act");
    var key = tr.getAttribute("data-rule-card");
    var card = l && act ? Array.prototype.filter.call(l.querySelectorAll("[data-hier-card]"), function (n) {
      return n.getAttribute("data-hier-card") === key;
    })[0] : null;
    var b = card && c ? c.tiles.act(card, act) : null;
    if (b && !b.disabled) { c.tiles.press(b, tr); return; }
    if (tr.getAttribute("data-row-region") && c && c.sheet.region) { c.sheet.region(tr); }
  }
  function ruleRow(t) {
    var tr = t && t.closest ? t.closest("tr[data-rule-open]") : null;
    return tr && tr.closest('[data-view-of="rules"]') ? tr : null;
  }
  document.addEventListener("click", function (e) {
    var tr = ruleRow(e.target);
    if (!tr || e.defaultPrevented || e.button) { return; }
    var skip = e.target.closest(ROW_SKIP);
    if (skip && tr.contains(skip)) { return; }
    var sel = window.getSelection ? window.getSelection() : null;
    if (sel && !sel.isCollapsed && String(sel).trim() && sel.anchorNode && tr.contains(sel.anchorNode)) { return; }
    openRuleRow(tr);
  });
  document.addEventListener("keydown", function (e) {
    var tr = e.target;
    if ((e.key !== "Enter" && e.key !== " ") || !tr || !tr.matches || !tr.matches("tr[data-rule-open]")) { return; }
    e.preventDefault();
    openRuleRow(tr);
  });
  document.addEventListener("pfas:row-action", function (e) {
    var tr = e.detail && e.detail.row;
    if (e.detail.name === "rule-open" && tr && tr.matches && tr.matches("tr[data-rule-open]")) { openRuleRow(tr); }
  });
  /* Open its tiers: the QC type's first tier chosen in the list, its card shown */
  document.addEventListener("click", function (e) {
    var b = e.target.closest ? e.target.closest("[data-qc-open]") : null;
    var node = b ? nodeOfCode(b.getAttribute("data-qc-open")) : null, c = comps(), l = rulesList();
    if (!node || !c || !c.hier || !l) { return; }
    var first = tiersOf(node.getAttribute("data-hier-target")).filter(function (k) {
      return k.classList.contains("pfas-hier-node");
    })[0];
    if (!first) { return; }
    c.hier.select(l, first.getAttribute("data-hier-target"), true);
    if (first.scrollIntoView) { first.scrollIntoView({ block: "nearest" }); }
  });
  /* + Add QC type */
  var ADD_LINES = {
    tiers: [["State", "Enforced"], ["Per worksheet", "1, as every QC type the method switches on"],
            ["Tiers", "one, named default, all analytes, all matrices"], ["Window", "empty: you type it before Save"]],
    lfsmd: [["State", "Enforced"], ["Per worksheet", "1, as every QC type the method switches on"],
            ["Tiers", "one for each LFSM tier, by name: its analytes, matrices and window are LFSM's"],
            ["RPD", "empty for each tier: you type it before Save"]],
    blank: [["State", "Enforced"], ["Per worksheet", "1, as every QC type the method switches on"],
            ["Blank limit", "empty: you type it before Save"]]
  };
  var BLANKS = ["MB", "LRB", "MxB", "CCB", "FRB", "TB"];
  function kindOf(code) { return BLANKS.indexOf(code) >= 0 ? "blank" : (code === "LFSMD" ? "lfsmd" : "tiers"); }
  function limitInputs(prefix) {
    return tierInputs(prefix).filter(function (n) { return /__(recovery_5fmin|recovery_5fmax|rpd_5fmax)$/.test(n.name); });
  }
  function addType(code) {
    var node = nodeOfCode(code);
    if (!node || added[code]) { return false; }
    var a = { names: [], required: [] }, kind = kindOf(code);
    function tier(qc, name, group, scope, matrices, low) {
      var prefix = insertTier(qc, "", group, scope, matrices);
      if (!prefix) { return; }
      var n = tierName(prefix);
      setValue(n, name);
      a.names.push(n);
      if (low) {
        var l = tierInputs(prefix).filter(function (x) { return /__low_5flevel_5fx_5frl$/.test(x.name); })[0];
        if (l) { setValue(l, low); }
      }
      limitInputs(prefix).forEach(function (x) { x.required = true; a.required.push(x); });
    }
    if (kind === "blank") {
      var lim = Array.prototype.filter.call(document.querySelectorAll('[form="section-qc"][name]'), function (n) {
        return n.name === "t__blk__" + code + "__max_5fconc_5fx_5frl";
      })[0];
      if (!lim) { return false; }
      lim.required = true;
      a.required.push(lim);
    } else if (kind === "lfsmd") {
      Array.prototype.forEach.call(tierRows("LFSM"), function (tr) {
        var ins = rowInputs(tr);
        function v(tail) { var x = ins.filter(function (n) { return n.name.slice(-tail.length) === tail; })[0]; return x ? x.value : ""; }
        if (!v("__name").trim()) { return; }
        tier("LFSMD", v("__name").trim(), v("__analyte_5fgroup"), v("__matrix_5fscope"), v("__matrices") || "[]", v("__low_5flevel_5fx_5frl"));
      });
    } else {
      tier(code, "default", "all", "all", "[]", "");
    }
    if (!a.names.length && kind !== "blank") { return false; }
    added[code] = a;
    node.hidden = false;
    node.setAttribute("data-added", "1");
    var tr = tableRow(node.getAttribute("data-hier-target"));
    if (tr) { tr.hidden = false; }
    drawRuleNode(node);
    choose(node);
    return true;
  }
  document.addEventListener("click", function (e) {
    var b = e.target.closest ? e.target.closest("[data-qc-add]") : null, drawer = drawerOf();
    if (!b || !drawer) { return; }
    var codes = (b.getAttribute("data-qc-add") || "").split(",").filter(function (c) {
      return c && !added[c] && nodeOfCode(c);
    });
    var box = el("div", "pfas-sheet-form"), pick = codes[0] || "";
    if (!codes.length) {
      box.appendChild(el("div", "pfas-sheet-help", "Every QC type this group can hold is on the list."));
    } else {
      box.appendChild(el("div", "pfas-sheet-help", "The QC types an extraction worksheet can hold that this method does not:"));
      var seg = el("div", "pfas-seg pfas-seg-sm is-fit"), lines = el("dl", "pfas-hier-made");
      seg.setAttribute("role", "group");
      seg.setAttribute("aria-label", "QC type");
      function draw() {
        lines.textContent = "";
        ADD_LINES[kindOf(pick)].forEach(function (r) {
          lines.appendChild(el("dt", "", r[0]));
          lines.appendChild(el("dd", "", r[1]));
        });
        Array.prototype.forEach.call(seg.querySelectorAll(".pfas-seg-item"), function (i) {
          i.setAttribute("aria-pressed", i.getAttribute("data-value") === pick ? "true" : "false");
        });
      }
      codes.forEach(function (c) {
        var i = el("button", "pfas-seg-item", nodeTitle(nodeOfCode(c)));
        i.type = "button";
        i.setAttribute("data-value", c);
        i.addEventListener("click", function () { pick = c; draw(); });
        seg.appendChild(i);
      });
      seg.setAttribute("data-quiet", "");
      box.appendChild(field("QC type", seg));
      box.appendChild(lines);
      box.appendChild(el("div", "pfas-sheet-help", "Nothing regulatory is filled in for you: Save waits until the limit is typed."));
      draw();
    }
    var foot = el("div", "pfas-drawer-actions");
    if (codes.length) {
      var go = el("button", "btn btn-primary", "Add");
      go.type = "button";
      go.setAttribute("data-qc-add-go", "");
      go.addEventListener("click", function () {
        if (addType(pick)) { drawer.close(); }
      });
      foot.appendChild(go);
    }
    drawer.open("Add a QC type \u00b7 " + (b.getAttribute("data-qc-group") || ""), box,
                { footer: foot, cls: "is-dialog", opener: b });
    drawer.opener = b;
    var built = box.querySelector(".pfas-seg"), cs = comps();
    if (built && cs && cs.seg) { cs.seg(built); }
  });
  drawRules();
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
    var mine = el("div");
    on = { td: td, row: td.parentNode.getAttribute("data-row"), matrix: columnMatrices(td)[0], body: body,
           top: top, own: mine, notes: notes, foot: foot, prev: prev, next: next, edit: edit || null };
    function step(by) {
      var list = cells(), to = list[list.indexOf(on.td) + by];
      if (!to) { return; }
      if (to.scrollIntoView) { to.scrollIntoView({ block: "nearest" }); }
      openWindow(to, null, by < 0 ? "prev" : "next");
    }
    prev.addEventListener("click", function () { step(-1); });
    next.addEventListener("click", function () { step(1); });
    body.appendChild(top);
    body.appendChild(mine);
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
    var kind = get("set-kind"), own = kind === "own", cell = kind === "cell", method = kind === "method";
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
    var resettable = !!name && !method && !own, toDefault = resettable && get("fallback-is-default") === "1";
    var help = el("div", "pfas-sheet-help");
    if (own) {
      help.textContent = get("own") === "off" ? "Not judged here: set on this cell for this analyte."
                                              : "Set on this cell for this analyte.";
    } else if (cell && get("hi") === "") {
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
    var here = own || cell, wider = here ? get("tier-name") : (method ? "" : get("tier"));
    by.appendChild(setBy("This cell", own && get("own") === "off" ? "off" : (here ? span(get("lo"), get("hi")) : ""), here));
    by.appendChild(setBy(wider || "Tier",
                         here ? span(get("tier-lo"), get("tier-hi")) : (wider ? span(get("lo"), get("hi")) : ""),
                         !here && !method && !!get("tier")));
    by.appendChild(setBy("Method default", span(get("method-lo"), get("method-hi")), method));
    top.appendChild(by);

    on.own.textContent = "";
    var mineBox = ownEditor(td);
    if (mineBox) { on.own.appendChild(mineBox); }
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

/* Paste into a grid, and Copy from method. A block pasted from a spreadsheet
   onto a cell of the Analytes, Isotope standards or Matrices grid fills the
   cells it covers, rightwards and down over the cells shown, from the cell
   pasted on. "Copy from method" fetches another method's values for the
   grid (GET ?_copy_from=<method>&_tab=<tab>, read only) and matches them to
   this method's by the name each value posts under (a column the picker
   hides included), so only the analytes,
   matrices and columns this method has are offered; a value the other
   method leaves blank changes nothing here. Either is listed first, cell by
   cell, as it is now and as it would be, with what cannot be taken and why
   (a number refused as a typed one is: not a number, below its minimum,
   above its maximum, not one of the choices); Apply writes the ticked ones
   into the grid's own inputs, and the tab's Save stores them, with the
   checks every save runs. A single value pastes as the browser does. */
(function () {
  var GRIDS = ".pfas-pane .pfas-sheet-box";
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
  function drawerOf() { return window.PFAS && window.PFAS.components ? window.PFAS.components.drawer : null; }
  function box(n) {
    var b = n && n.closest ? n.closest(GRIDS) : null;
    return b && !b.closest("#qc-windows") ? b : null;
  }
  /* the input a person types into in a cell, or null (a read-only cell);
     `any`: a column the column picker hides counts too */
  function inputOf(td, any) {
    if (!td || td.hidden || (!any && td.classList.contains("is-col-off"))) { return null; }
    var n = Array.prototype.filter.call(td.querySelectorAll("input[name], select[name]"), function (x) {
      return x.type !== "hidden" && x.type !== "checkbox" && !x.disabled;
    })[0];
    return n || null;
  }
  function label(n) { return n.getAttribute("aria-label") || n.name; }
  /* (value as stored, or null and why not), as a typed value is checked */
  function taken(n, v) {
    v = String(v).trim();
    if (n.tagName === "SELECT") {
      var o = Array.prototype.filter.call(n.options, function (x) {
        return x.value === v || x.textContent.trim() === v;
      })[0];
      return o ? [o.value, ""] : [null, "not one of the choices"];
    }
    if (n.type === "number" && v !== "") {
      var x = Number(v.replace(/,/g, ""));
      if (isNaN(x)) { return [null, "not a number"]; }
      var lo = n.getAttribute("min"), hi = n.getAttribute("max");
      if (lo !== null && lo !== "" && x < Number(lo)) { return [null, "below " + lo]; }
      if (hi !== null && hi !== "" && x > Number(hi)) { return [null, "above " + hi]; }
      return [String(x), ""];
    }
    return [v, ""];
  }
  /* the list shown before anything changes: changes ticked (a change marked
     ticked: false starts unticked, so it is never written without the tick),
     refusals named */
  function review(title, changes, refused, note) {
    var drawer = drawerOf();
    if (!drawer) { return; }
    var body = el("div", "pfas-sheet-form");
    if (note) { body.appendChild(el("div", "pfas-sheet-help", note)); }
    if (!changes.length) { body.appendChild(el("div", "pfas-sheet-help", "Nothing would change.")); }
    var ticks = changes.map(function (c) {
      var row = el("label", "pfas-sheet-field"), cb = el("input");
      cb.type = "checkbox";
      cb.checked = c.ticked !== false;
      row.appendChild(cb);
      row.appendChild(el("span", "", label(c.input) + ": " + (c.input.value || "blank") + " → " + (c.value || "blank") +
                                      (c.why ? " (" + c.why + ")" : "")));
      body.appendChild(row);
      return cb;
    });
    refused.forEach(function (r) { body.appendChild(el("div", "pfas-sheet-help", r)); });
    var foot = el("div", "pfas-drawer-actions"), apply = el("button", "btn btn-sm btn-primary", "Apply");
    apply.type = "button";
    apply.disabled = !changes.length;
    apply.addEventListener("click", function () {
      changes.forEach(function (c, i) {
        if (ticks[i].checked && c.input.value !== c.value) { c.input.value = c.value; fire(c.input); }
      });
      drawer.close();
    });
    foot.appendChild(apply);
    drawer.open(title, body, { footer: foot });
  }

  /* ── paste ── */
  document.addEventListener("paste", function (e) {
    var b = box(e.target), td = e.target && e.target.closest ? e.target.closest("td[data-col]") : null;
    if (!b || !td) { return; }
    var text = (e.clipboardData || window.clipboardData || { getData: function () { return ""; } }).getData("text");
    var lines = String(text || "").replace(/\r/g, "").split("\n");
    if (lines.length && lines[lines.length - 1] === "") { lines.pop(); }
    var block = lines.map(function (l) { return l.split("\t"); });
    if (!block.length || (block.length === 1 && block[0].length === 1)) { return; }   /* one value: the browser's */
    e.preventDefault();
    var rows = Array.prototype.filter.call(b.querySelectorAll("tbody tr[data-row]"), function (tr) { return !tr.hidden; });
    function shown(tr) {
      return Array.prototype.filter.call(tr.querySelectorAll("td[data-col]"), function (x) {
        return !x.hidden && !x.classList.contains("is-col-off");
      });
    }
    var r0 = rows.indexOf(td.parentNode), c0 = shown(td.parentNode).indexOf(td);
    if (r0 < 0 || c0 < 0) { return; }
    var changes = [], refused = [], outside = 0;
    block.forEach(function (vals, r) {
      var tr = rows[r0 + r];
      vals.forEach(function (v, c) {
        var cell = tr ? shown(tr)[c0 + c] : null, n = inputOf(cell);
        if (!n) { outside += 1; return; }
        var t = taken(n, v);
        if (t[0] === null) { refused.push(label(n) + ": " + v + " is " + t[1] + "."); return; }
        if (t[0] !== n.value) { changes.push({ input: n, value: t[0] }); }
      });
    });
    if (outside) { refused.push(outside + (outside === 1 ? " value falls" : " values fall") + " outside the cells you can edit."); }
    review("Paste", changes, refused);
  });

  /* ── fill RLs from calibration: each RL cell's default (data-derived) ── */
  document.addEventListener("click", function (e) {
    var btn = e.target.closest ? e.target.closest("[data-fill-rl]") : null;
    if (!btn || !drawerOf()) { return; }
    var b = btn.closest(".pfas-sheet-box") || document, changes = [], none = 0;
    /* each default was drawn from the saved salt factors: one changed and
       not saved yet would give RLs from the old factor */
    var unsaved = Array.prototype.some.call(b.querySelectorAll('td[data-col="salt"]'), function (td) {
      var n = inputOf(td, true);
      return n && n.value !== n.defaultValue;
    });
    if (unsaved) {
      review("Fill RLs from calibration", [], [], "A salt factor has changed and is not saved yet. Save the tab first, then fill the RLs.");
      return;
    }
    Array.prototype.forEach.call(b.querySelectorAll("td[data-col]"), function (td) {
      var n = (td.getAttribute("data-col") || "").indexOf("rl-") === 0 ? inputOf(td, true) : null;
      if (!n) { return; }
      var v = td.getAttribute("data-derived");
      if (!v) { none += 1; return; }
      if (n.value === "") { changes.push({ input: n, value: v }); return; }
      if (Number(n.value) !== Number(v)) { changes.push({ input: n, value: v, ticked: false, why: "replaces a typed RL" }); }
    });
    var refused = none ? [none + (none === 1 ? " RL has" : " RLs have") +
                          " no default: check the calibration levels and the matrix's factor and unit."] : [];
    review("Fill RLs from calibration", changes, refused,
           "Each RL from the lowest calibrator, the matrix factor and the salt factor. A typed RL is left as it is unless you tick it.");
  });

  /* ── copy from method ── */
  document.addEventListener("click", function (e) {
    var btn = e.target.closest ? e.target.closest("[data-copy-from]") : null;
    var drawer = drawerOf();
    if (!btn || !drawer) { return; }
    var b = btn.closest(".pfas-sheet-box") || document, tab = btn.getAttribute("data-copy-from");
    var methods = [];
    try { methods = JSON.parse(btn.getAttribute("data-methods") || "[]"); } catch (err) { methods = []; }
    var body = el("div", "pfas-sheet-form"), pick = el("select");
    pick.setAttribute("aria-label", "Method");
    methods.forEach(function (m) { var o = el("option", "", m[1]); o.value = m[0]; pick.appendChild(o); });
    var f = el("div", "pfas-sheet-field");
    f.appendChild(el("div", "pfas-sheet-flabel", "Method"));
    f.appendChild(pick);
    body.appendChild(f);
    var foot = el("div", "pfas-drawer-actions"), show = el("button", "btn btn-sm btn-primary", "Show its values");
    show.type = "button";
    foot.appendChild(show);
    var mine = document.querySelector('#profile-form [name="method_id"]');
    show.addEventListener("click", function () {
      var url = location.pathname + "?method_id=" + encodeURIComponent(mine ? mine.value : "") +
                "&_copy_from=" + encodeURIComponent(pick.value) + "&_tab=" + encodeURIComponent(tab);
      fetch(url, { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (got) {
        var inputs = {};
        Array.prototype.forEach.call(b.querySelectorAll("td[data-col]"), function (td) {
          var n = inputOf(td, true);
          if (n) { inputs[n.name] = n; }
        });
        var changes = [], refused = [], absent = 0;
        Object.keys(got.values || {}).forEach(function (name) {
          var v = got.values[name], n = inputs[name];
          if (v === "" || v === null) { return; }           /* blank there: nothing to take */
          if (!n) { absent += 1; return; }
          var t = taken(n, v);
          if (t[0] === null) { refused.push(label(n) + ": " + v + " is " + t[1] + "."); return; }
          if (t[0] !== n.value) { changes.push({ input: n, value: t[0] }); }
        });
        var note = "From " + (got.method || pick.value) + "." +
                   (absent ? " " + absent + (absent === 1 ? " value is" : " values are") +
                             " for analytes, matrices or columns this method does not have." : "");
        review("Copy from " + (got.method || pick.value), changes, refused, note);
      });
    });
    drawer.open("Copy from method", body, { footer: foot });
  });

  /* ── copy tiers from method: this method's tier list of each QC type both
     run is replaced by the other's. The differences are listed first (GET
     ?_copy_tiers=<method>, read only); Replace posts the tiers-copy form,
     which the server checks as it checks an edit of the tiers. ── */
  document.addEventListener("click", function (e) {
    var btn = e.target.closest ? e.target.closest("[data-copy-tiers]") : null;
    var drawer = drawerOf();
    if (!btn || !drawer) { return; }
    var form = document.getElementById(btn.getAttribute("data-copy-tiers"));
    var methods = [];
    try { methods = JSON.parse(btn.getAttribute("data-methods") || "[]"); } catch (err) { methods = []; }
    var body = el("div", "pfas-sheet-form"), pick = el("select");
    pick.setAttribute("aria-label", "Method");
    methods.forEach(function (m) { var o = el("option", "", m[1]); o.value = m[0]; pick.appendChild(o); });
    var f = el("div", "pfas-sheet-field");
    f.appendChild(el("div", "pfas-sheet-flabel", "Method"));
    f.appendChild(pick);
    body.appendChild(f);
    var foot = el("div", "pfas-drawer-actions"), show = el("button", "btn btn-sm btn-primary", "Show the differences");
    show.type = "button";
    foot.appendChild(show);
    var mine = form ? form.querySelector('[name="method_id"]') : null;
    show.addEventListener("click", function () {
      var url = location.pathname + "?method_id=" + encodeURIComponent(mine ? mine.value : "") +
                "&_copy_tiers=" + encodeURIComponent(pick.value);
      fetch(url, { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (got) {
        var list = el("div", "pfas-sheet-form");
        list.appendChild(el("div", "pfas-sheet-help", "Each QC type below takes the tiers of " + (got.method || pick.value) +
                                                      " in place of its own. Unsaved changes on this tab are lost."));
        (got.types || []).forEach(function (t) {
          list.appendChild(el("div", "pfas-sheet-flabel", t.label));
          if (!t.changes.length) { list.appendChild(el("div", "pfas-sheet-help", "No change.")); }
          t.changes.forEach(function (c) { list.appendChild(el("div", "pfas-sheet-help", c)); });
          (t.dropped || []).forEach(function (d) {
            list.appendChild(el("div", "pfas-sheet-help", d[0] + ": leaves out " + d[1].join(", ") + ", not matrices of this method."));
          });
        });
        (got.skipped || []).forEach(function (s) { list.appendChild(el("div", "pfas-sheet-help", s[0] + ": not copied, " + s[1] + ".")); });
        (got.errors || []).forEach(function (x) { list.appendChild(el("p", "pfas-hint is-bad", x)); });
        if (got.error) { list.appendChild(el("p", "pfas-hint is-bad", got.error)); }
        var bar = el("div", "pfas-drawer-actions"), replace = el("button", "btn btn-sm btn-primary", "Replace the tiers");
        replace.type = "button";
        replace.disabled = !!(got.error || (got.errors || []).length || !(got.types || []).length);
        replace.addEventListener("click", function () {
          if (!form) { return; }
          form.querySelector('[name="source"]').value = pick.value;
          form.submit();
        });
        bar.appendChild(replace);
        drawer.open("Copy tiers from " + (got.method || pick.value), list, { footer: bar });
      });
    });
    drawer.open("Copy tiers from method", body, { footer: foot });
  });
})();

/* The salt factor calculator, in the Salt factor cell's editor (a cell with
   data-calc="salt"; pfas-components.js openCell asks for it). A standard
   supplied as a salt reads the counter-ion too; the factor converts it to the
   acid the results are reported as: f = M(acid) / M(salt) (EPA 537.1 Section 7.2.3,
   Mass acid = Measured Mass salt x MW acid / MW salt). The molecular weights are typed, or taken
   from the certificate of the row's CoA lot where it states them; nothing
   comes from a table of molecular weights. An analyte reported as a sum of
   isomer peaks takes one factor for every peak (linear and branched isomers
   share one molecular weight); where the standard holds the isomers as different
   salt forms, each form's share of the stated concentration weights its
   own ratio: f = sum of w x MW acid / MW salt. The equation, its terms and
   each step are drawn as the value drawer draws them (provenance.css).
   "Use this factor" writes it, at 4 significant figures, into the editor;
   Done keeps it and the tab's Save stores it. */
(function () {
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
  function pos(v) { var x = parseFloat(v); return isNaN(x) || x <= 0 ? null : x; }
  function sig4(v) { return String(Number(v.toPrecision(4))); }
  function json(td, k) {
    try { return JSON.parse(td.getAttribute("data-" + k) || "null"); } catch (e) { return null; }
  }

  /* {factor, steps, error}: the factor from the acid's molecular weight and the
     salt forms [{label, share (%), mass}]; one form is the whole standard */
  function saltFactor(acid, forms) {
    var a = pos(acid), steps = [];
    if (a === null) { return { factor: null, steps: steps, error: "Type the molecular weight of the acid." }; }
    if (!forms.length || forms.some(function (f) { return pos(f.mass) === null; })) {
      return { factor: null, steps: steps, error: "Type the molecular weight of each salt form." };
    }
    if (forms.length === 1) {
      var f1 = a / pos(forms[0].mass);
      steps.push({ label: "Factor", expression: "f = MWacid ÷ MWsalt = " + a + " ÷ " + pos(forms[0].mass), value: f1 });
      return f1 > 1 ? { factor: null, steps: steps, error: "A salt is heavier than its acid: check the molecular weights." }
                    : { factor: f1, steps: steps, error: "" };
    }
    var total = 0, sum = 0;
    forms.forEach(function (f) {
      var w = pos(f.share) === null ? 0 : pos(f.share) / 100, part = w * a / pos(f.mass);
      total += w;
      sum += part;
      steps.push({ label: f.label, expression: "w × MWacid ÷ MWsalt = " + (w * 100) + " % × " + a + " ÷ " + pos(f.mass), value: part });
    });
    steps.push({ label: "Factor", expression: "f = sum of the parts", value: sum });
    if (Math.abs(total - 1) > 1e-6) {
      return { factor: null, steps: steps, error: "The shares add up to " + Math.round(total * 1000) / 10 + " %, not 100 %." };
    }
    return sum > 1 ? { factor: null, steps: steps, error: "A salt is heavier than its acid: check the molecular weights." }
                   : { factor: sum, steps: steps, error: "" };
  }

  function field(label, input) {
    var f = el("div", "pfas-sheet-field");
    f.appendChild(el("div", "pfas-sheet-flabel", label));
    f.appendChild(input);
    return f;
  }
  function numIn(label, value) {
    var n = el("input");
    n.type = "number";
    n.setAttribute("step", "any");
    n.setAttribute("min", "0");
    n.setAttribute("aria-label", label);
    if (value !== null && value !== undefined) { n.value = String(value); }
    return n;
  }
  /* a symbol with its subscript: ["MW", "acid"] */
  function symbol(into, parts) {
    into.appendChild(document.createTextNode(parts[0]));
    if (parts[1]) { into.appendChild(el("sub", "", parts[1])); }
  }
  /* the equation as EPA 537.1 Section 7.2.3 prints it, drawn by the one
     equation drawing (provenance.js); a mixed standard weights each salt
     form by its share w */
  function formula(mixed) {
    var box = el("div");
    box.innerHTML = window.PFAS.provenance.formulaBlock("Mass_{acid} = " + (mixed ? "sum of w \u00d7 " : "") +
      "Measured Mass_{salt} \u00d7 MW_{acid} / MW_{salt}", []);
    return box.firstChild;
  }

  function build(td, body, cp) {
    var analyte = td.getAttribute("data-analyte") || "the analyte", peaks = json(td, "isomers") || [];
    var lots = json(td, "mw") || [], lotIn = null, lotName = td.getAttribute("data-lot-name");
    if (lotName) {
      lotIn = Array.prototype.filter.call(document.querySelectorAll("[name]"), function (n) { return n.name === lotName; })[0] || null;
    }
    var fromLot = lots.filter(function (l) { return lotIn && l[0] === lotIn.value; })[0] || null;
    var box = el("section", "mp-salt-calc");
    box.appendChild(el("h3", "pv-h", "Calculate the factor"));
    box.appendChild(el("p", "pv-rule", "A standard supplied as a salt reads its counter-ion too. The factor converts it to the acid " +
                                        analyte + " is reported as, as EPA 537.1 Section 7.2.3 gives it, where MW is the molecular weight."));
    if (fromLot) { box.appendChild(el("p", "pv-rule", "Molecular weights from the certificate of " + fromLot[1] + ".")); }
    var acid = numIn("Molecular weight of PFAS", fromLot ? fromLot[2] : null);
    var salt = numIn("Molecular weight of the salt form", fromLot ? fromLot[3] : null);
    box.appendChild(field("Molecular weight of PFAS (g/mol)", acid));
    var single = field("Molecular weight of the salt form (g/mol)", salt);
    box.appendChild(single);
    var mixed = false, forms = [];
    if (peaks.length) {
      box.appendChild(el("p", "pv-rule", analyte + " is reported as the sum of " + peaks.join(" and ") +
        ". The isomers share one molecular weight, so one factor serves every peak, and the worker applies it to each. " +
        "Where the standard holds them as different salt forms, give each form's share of the stated concentration."));
      var seg = el("div", "pfas-seg");
      seg.setAttribute("role", "group");
      seg.setAttribute("aria-label", "Salt forms in the standard");
      var multi = el("div", "mp-salt-forms");
      multi.hidden = true;
      peaks.forEach(function (p) {
        var share = numIn("Share of " + p + " (%)"), mass = numIn("Molecular weight of the " + p + " salt form");
        multi.appendChild(field("Share of " + p + " (%)", share));
        multi.appendChild(field("Molecular weight of the " + p + " salt form (g/mol)", mass));
        forms.push({ label: p, share: share, mass: mass });
      });
      [["one", "One salt form"], ["many", "Different salt forms"]].forEach(function (o) {
        var b = el("button", "pfas-seg-item", o[1]);
        b.type = "button";
        b.setAttribute("aria-pressed", o[0] === "one" ? "true" : "false");
        b.addEventListener("click", function () {
          seg.querySelectorAll(".pfas-seg-item").forEach(function (x) { x.setAttribute("aria-pressed", x === b ? "true" : "false"); });
          mixed = o[0] === "many";
          multi.hidden = !mixed;
          single.hidden = mixed;
          draw();
        });
        seg.appendChild(b);
      });
      box.appendChild(seg);
      box.appendChild(multi);
    }
    var out = el("div", "mp-salt-out");
    box.appendChild(out);
    var foot = el("div", "form-actions"), use = el("button", "btn btn-sm btn-primary", "Use this factor");
    use.type = "button";
    foot.appendChild(use);
    box.appendChild(foot);
    var result = null;
    function draw() {
      out.innerHTML = "";
      var list = mixed ? forms.map(function (f) { return { label: f.label, share: f.share.value, mass: f.mass.value }; })
                       : [{ label: "Salt", share: "100", mass: salt.value }];
      result = saltFactor(acid.value, list);
      out.appendChild(formula(mixed));
      var t = el("table", "pfas-table pv-terms"), tb = el("tbody");
      [[["MW", "acid"], "molecular weight of PFAS", acid.value || "—"]].concat(mixed ? forms.map(function (f) {
        return [["MW", "salt"], "molecular weight of the " + f.label + " salt form, its share w", (f.mass.value || "—") + " g/mol, " + (f.share.value || "—") + " %"];
      }) : [[["MW", "salt"], "molecular weight of purchased salt", salt.value || "—"]]).concat(
        [[["f"], "salt factor, MWacid ÷ MWsalt", result.factor === null ? "—" : sig4(result.factor)]]).forEach(function (r) {
        var tr = el("tr"), sym = el("td", "pv-sym");
        symbol(sym, r[0]);
        tr.appendChild(sym);
        tr.appendChild(el("td", "", r[1]));
        tr.appendChild(el("td", "num", String(r[2])));
        tb.appendChild(tr);
      });
      t.appendChild(tb);
      out.appendChild(t);
      if (result.steps.length) {
        out.appendChild(el("h3", "pv-h", "Step by step"));
        var ol = el("ol", "pv-steps");
        result.steps.forEach(function (s) {
          var li = el("li");
          li.appendChild(el("span", "", s.label));
          var eq = el("span", "pv-step-eq");
          eq.innerHTML = window.PFAS.provenance.formulaHtml(s.expression, []);
          li.appendChild(eq);
          li.appendChild(el("b", "", sig4(s.value)));
          ol.appendChild(li);
        });
        out.appendChild(ol);
      }
      if (result.error) {
        var refusal = out.appendChild(el("p", "pfas-hint is-bad", result.error));
        /* it fades in when its words change, never again on every key */
        var motion = window.PFAS.components && window.PFAS.components.motion;
        if (motion) { motion.hint(refusal, result.error); }
      } else { out.__pfasHint = null; }
      var typed = pos(cp.value);
      if (typed !== null && result.factor !== null && sig4(typed) !== sig4(result.factor)) {
        out.appendChild(el("p", "pv-rule", "The factor typed is " + cp.value + "; the molecular weights give " + sig4(result.factor) + "."));
      }
      use.disabled = result.factor === null;
    }
    use.addEventListener("click", function () {
      if (!result || result.factor === null) { return; }
      cp.value = sig4(result.factor);
      fire(cp);
      draw();
    });
    box.addEventListener("input", function (e) { if (e.target !== cp) { draw(); } });
    /* Enter in the calculator stays in it: the editor's Enter moves to the next cell */
    box.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); e.stopPropagation(); } });
    body.appendChild(box);
    draw();
  }

  document.addEventListener("pfas:cell-calc", function (e) {
    var td = e.target;
    if (!td || td.getAttribute("data-calc") !== "salt" || !e.detail) { return; }
    build(td, e.detail.body, e.detail.input);
  });
  if (typeof window !== "undefined") { window.PFAS = window.PFAS || {}; window.PFAS.saltFactor = saltFactor; }
})();

/* What the method profile's List views share (window.PFAS.mpList). addFrom:
   a list's "+ Add" opens the shared drawer on a nameless copy of a grid's
   own chooser (the select `chooserId`), writes the choice into it with input
   and change, and sends the form the chooser posts with, as the grid's own
   Add does. post: a list's Remove sends a form with one field set, as the
   grid's Remove sends it with the ticked rows. */
(function () {
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
  function comps() { return window.PFAS && window.PFAS.components ? window.PFAS.components : null; }
  function send(form) {
    if (form.requestSubmit) { form.requestSubmit(); return; }
    if (form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }))) { form.submit(); }
  }
  function addFrom(btn, chooserId, label, title) {
    var c = comps(), real = document.getElementById(chooserId);
    var form = real ? document.getElementById(real.getAttribute("form")) : null;
    if (!c || !real || !form) { return; }
    var pop = real.closest ? real.closest(".pfas-sheet-adder") : null;
    var pick = el("select");
    pick.setAttribute("aria-label", label);
    Array.prototype.forEach.call(real.querySelectorAll("option"), function (o) {
      if (!o.value) { return; }
      var n = el("option", "", o.textContent);
      n.value = o.value;
      pick.appendChild(n);
    });
    var row = el("label", "pfas-pop-row");
    row.appendChild(el("span", "pfas-pop-l", label));
    row.appendChild(pick);
    var body = el("div");
    body.appendChild(row);
    var foot = el("div", "pfas-drawer-actions"), cancel = el("button", "btn btn-secondary", "Cancel"),
        add = el("button", "btn btn-primary", "Add");
    cancel.type = add.type = "button";
    cancel.addEventListener("click", function () { c.drawer.close(); });
    add.addEventListener("click", function () {
      if (!pick.value) { return; }
      real.value = pick.value;
      fire(real);
      c.drawer.close();
      send(form);
    });
    foot.appendChild(cancel);
    foot.appendChild(add);
    c.drawer.open((pop && pop.getAttribute("aria-label")) || title, body,
                  { footer: foot, cls: "is-dialog", opener: btn, focus: pick });
  }
  function post(formId, name, value) {
    var form = document.getElementById(formId);
    if (!form) { return; }
    var n = Array.prototype.filter.call(form.querySelectorAll("input"), function (i) { return i.name === name; })[0];
    if (!n) { n = el("input"); n.type = "hidden"; n.name = name; form.appendChild(n); }
    n.value = value;
    send(form);
  }
  /* a select's chosen option as it reads */
  function shown(sel) {
    var o = Array.prototype.filter.call(sel.querySelectorAll("option"), function (x) { return x.value === sel.value; })[0];
    return o ? o.textContent : sel.value;
  }
  /* the segment a hidden field is drawn as (config_form_macros: data-input names its id) */
  function segOf(real) {
    if (real.type !== "hidden" || !real.id) { return null; }
    return Array.prototype.filter.call(document.querySelectorAll(".pfas-seg[data-input]"), function (s) {
      return s.getAttribute("data-input") === real.id;
    })[0] || null;
  }
  var STRIP = ["name", "form", "id", "data-kind", "data-inherits", "data-input", "data-field", "required",
               "data-shared"];
  /* a nameless copy of one posted control, and how to read it back; a
     hidden number (number: true) is copied as a number box; a switch as a
     switch, read as its value while ticked, else blank */
  function copyOf(real, blank, number) {
    var seg = segOf(real), c = comps(), copy;
    if (real.type === "checkbox") {
      var sw = el("label", "pfas-switch");
      copy = el("input");
      copy.type = "checkbox";
      copy.checked = real.checked;
      sw.appendChild(copy);
      sw.appendChild(el("span", "pfas-switch-track"));
      return { node: sw, input: copy, value: function () { return copy.checked ? real.value : ""; } };
    }
    if (number && !seg) {
      copy = el("input");
      copy.type = "number";
      copy.setAttribute("step", "any");
      copy.setAttribute("min", "0");
      copy.value = real.value;
      if (blank) { copy.setAttribute("placeholder", blank); }
      return { node: copy, value: function () { return copy.value; } };
    }
    if (seg) {
      copy = seg.cloneNode(true);
      STRIP.forEach(function (a) { copy.removeAttribute(a); });
      Array.prototype.forEach.call(copy.querySelectorAll(".pfas-seg-pill"), function (p) { p.parentNode.removeChild(p); });
      Array.prototype.forEach.call(copy.querySelectorAll(".pfas-seg-item"), function (b) {
        b.setAttribute("aria-pressed", b.getAttribute("data-value") === real.value ? "true" : "false");
      });
      copy.__pfas = false;
      if (c) { c.seg(copy); }
      return { node: copy, value: function () {
        var on = copy.querySelector('.pfas-seg-item[aria-pressed="true"]');
        return on ? on.getAttribute("data-value") : real.value;
      } };
    }
    copy = real.cloneNode(true);
    STRIP.forEach(function (a) { copy.removeAttribute(a); });
    copy.classList.remove("rl-in");
    copy.classList.remove("is-inherited");
    /* a page stepper's box, copied without its stepper: the window draws its own */
    copy.classList.remove("pfas-num-in");
    copy.classList.remove("is-up");
    copy.classList.remove("is-down");
    copy.style.width = "";
    /* a grid cell's input is visually hidden behind its value button
       (pfas-components hideInput): its copy is a field of its own, shown,
       reachable by Tab and read aloud */
    copy.classList.remove("pfas-sr-hide");
    copy.removeAttribute("tabindex");
    copy.removeAttribute("aria-hidden");
    copy.value = real.value;
    if (blank && copy.tagName === "SELECT") {
      var none = Array.prototype.filter.call(copy.querySelectorAll("option"), function (o) { return o.value === ""; })[0];
      if (none) { none.textContent = blank; }
    } else if (blank) {
      copy.setAttribute("placeholder", blank);
    }
    return { node: copy, value: function () { return copy.value; } };
  }
  /* A list card's Edit: the shared drawer on nameless copies of posted
     controls (items: {real, label, blank: what a blank reads, when: [field
     name, [values]] shown only for those values, as the field reads in the
     drawer, else on the page; also: more controls a change is written to;
     number: a hidden field edited as a number box});
     Done writes each changed copy back with input and change, so the
     unsaved count and every drawing follow. opts.ranges: a min and a max
     side by side (their names ..._min, ..._max) are one range, as the cards
     draw it: two typed ends on one line with its bar, headed by their
     shared name, an empty end reading what it falls back to. */
  function rangeOf(a, b) {
    if (!a || !b || a.real.tagName !== "INPUT" || b.real.tagName !== "INPUT") { return null; }
    /* a pair its caller marks as min and max (end: "lo" | "hi", stem: its name) */
    if (a.end === "lo" && b.end === "hi") { return a.stem || null; }
    var n = a.real.name || "";
    if (!/_min$/.test(n) || b.real.name !== n.replace(/_min$/, "_max")) { return null; }
    var stem = String(a.label || "").replace(/\s+min(imum)?$/i, "").trim();
    return stem || null;
  }
  function rangeEnd(it) {
    var n = el("input");
    n.type = "number";
    n.setAttribute("step", "any");
    n.setAttribute("min", it.real.getAttribute("min") || "0");
    n.value = it.real.value;
    var ph = it.blank || it.real.getAttribute("placeholder") || "";
    if (ph) { n.setAttribute("placeholder", ph); }
    n.setAttribute("aria-label", it.label);
    if (it.real.name) { n.setAttribute("data-for-name", it.real.name); }
    return n;
  }
  function editCopies(title, items, opts) {
    var c = comps();
    opts = opts || {};
    if (!c || !items.length) { return null; }
    var body = el("div", opts.ranges ? "pfas-sheet-form is-limits" : "pfas-sheet-form"), pairs = [], skip = -1;
    items.forEach(function (it, at) {
      if (at === skip) { return; }
      var stem = opts.ranges ? rangeOf(it, items[at + 1]) : null;
      if (stem) {
        var hiIt = items[at + 1], lo = rangeEnd(it), hi = rangeEnd(hiIt), w = el("div", "pfas-range-field");
        w.setAttribute("data-range", "");
        w.setAttribute("data-scale", "0,200");
        w.setAttribute("data-unit", it.unit || "%");
        w.setAttribute("data-empty", "");
        w.appendChild(lo);
        w.appendChild(hi);
        var rf = el("div", "pfas-sheet-field");
        rf.appendChild(el("div", "pfas-sheet-flabel", stem));
        rf.appendChild(w);
        body.appendChild(rf);
        c.range(w);
        [[it, lo], [hiIt, hi]].forEach(function (x) {
          pairs.push({ it: x[0], cp: { node: x[1], input: x[1], value: function () { return x[1].value; } },
                       field: rf, start: x[1].value });
        });
        skip = at + 1;
        return;
      }
      var cp = copyOf(it.real, it.blank, it.number);
      (cp.input || cp.node).setAttribute("aria-label", it.label);
      /* the field's unit, its suffix (PFAS.components.fields draws it) */
      if (it.unit && cp.node.tagName !== "DIV") { (cp.input || cp.node).setAttribute("data-unit", it.unit); }
      if (it.real.name) { (cp.input || cp.node).setAttribute("data-for-name", it.real.name); }
      var f = el("div", "pfas-sheet-field");
      f.appendChild(el("div", "pfas-sheet-flabel", it.label));
      f.appendChild(cp.node);
      body.appendChild(f);
      /* a single number: the house stepper in every window, as a limits
         window's; the drawer makes every other box the house field */
      if (cp.node.tagName === "INPUT" && cp.node.type === "number") { c.num(cp.node); }
      pairs.push({ it: it, cp: cp, field: f, start: cp.value() });
    });
    function valueOf(name) {
      var p = pairs.filter(function (x) { return x.it.real.name === name; })[0];
      if (p) { return p.cp.value(); }
      var real = document.getElementsByName(name)[0];
      return real ? real.value : "";
    }
    function follow() {
      pairs.forEach(function (p) {
        if (p.it.when) { p.field.hidden = p.it.when[1].indexOf(valueOf(p.it.when[0])) < 0; }
      });
    }
    body.addEventListener("click", function () { setTimeout(follow, 0); });
    body.addEventListener("change", follow);
    follow();
    var foot = el("div", "pfas-drawer-actions"), done = el("button", "btn btn-primary", "Done");
    done.type = "button";
    done.addEventListener("click", function () {
      pairs.forEach(function (p) {
        var v = p.cp.value();
        if (v === p.start) { return; }
        [p.it.real].concat(p.it.also || []).forEach(function (r) {
          if (r.type === "checkbox") {
            if (r.checked !== !!v) { r.checked = !!v; fire(r); }
          } else if (r.value !== v) { r.value = v; fire(r); }
        });
      });
      c.drawer.close();
      if (opts.done) { opts.done(); }
    });
    foot.appendChild(done);
    var first = pairs.filter(function (p) { return !p.field.hidden; })[0];
    c.drawer.open(title, body, { footer: foot, cls: "is-dialog", opener: opts.opener || null,
                                 focus: first ? first.cp.input || first.cp.node : null });
    return body;
  }
  /* a list card's Reset: its controls cleared, each with input and change */
  function clear(reals) {
    reals.forEach(function (n) { if (n && n.value) { n.value = ""; fire(n); } });
  }
  window.PFAS = window.PFAS || {};
  window.PFAS.mpList = { addFrom: addFrom, post: post, fire: fire, el: el, shown: shown, editCopies: editCopies, clear: clear,
                         copyOf: copyOf };
})();

/* A note's window, in place (profile_grids.inplace): a tile, row or note
   never takes the page to another tab, view or page. The trigger it presses
   carries data-inplace, {title, names, tables, read, note, goto}:
   - names: [[input name, label]] (or [name, label, [[value, words]]] for a
     hidden field drawn as a segment), the posted inputs edited on nameless
     copies, as PFAS.mpList.editCopies does;
   - tables: [{sel, head, cols, rows}], a table (a collection, a per-analyte
     table, a grid's columns whose data-col starts with one of `cols`, its
     rows `rows`; a region: its fields and each table in it) drawn in the
     window as one table of copies;
   - read, note: words; goto: [href, words], the one button in the window
     that leaves the page, for what the method profile does not hold.
   Done writes each changed copy into its own input with input and change,
   so the tab that posts it counts it unsaved, whichever tab is shown; the
   window says which tab saves it. */
(function () {
  function L() { return window.PFAS && window.PFAS.mpList; }
  function comps() { return window.PFAS && window.PFAS.components ? window.PFAS.components : null; }
  function el(tag, cls, text) { return L().el(tag, cls, text); }
  function clean(s) { return String(s === undefined || s === null ? "" : s).replace(/\s+/g, " ").trim(); }
  function list(x) { return Array.prototype.slice.call(x || []); }
  /* the posted control of that name, never a window's nameless copy */
  function real(name) {
    return list(document.getElementsByName(name)).filter(function (n) {
      return !(n.closest && n.closest(".pfas-drawer"));
    })[0] || null;
  }
  /* a control a form posts, drawn in a window: not a template row (NEW),
     not a hidden field (a segment's own, drawn by its choices), not a
     selection box */
  function copyable(n) {
    if (!n.name || /__NEW__/.test(n.name) || n.type === "hidden" || n.type === "button" || n.type === "submit") { return false; }
    var f = n.getAttribute("form");
    return f ? f !== "pfas-no-form" : !!n.form;
  }
  function labelOf(n) {
    var l = n.id ? document.querySelector('label[for="' + n.id + '"]') : null;
    if (l) { return clean(l.textContent); }
    if (n.getAttribute("aria-label")) { return clean(n.getAttribute("aria-label")); }
    var box = n.closest ? n.closest(".cf-settings") : null, cl = box ? box.querySelector(".cf-label") : null;
    return cl ? clean(cl.textContent) : n.name;
  }
  function formOf(n) { return n.form || (n.getAttribute("form") ? document.getElementById(n.getAttribute("form")) : null); }
  function shownForm() {
    var t = document.querySelector('#method-profile-tabs [aria-selected="true"]');
    var p = t ? t.getAttribute("data-pane") || "" : "";
    return p ? document.getElementById("section-" + p.replace("pane-", "")) : null;
  }
  /* "Saves with the Run & reporting tab." when a copy's input is another tab's */
  function savesWith(reals) {
    var here = shownForm(), tabs = [];
    reals.forEach(function (r) {
      var f = formOf(r), w = f ? f.getAttribute("data-tab-label") : "";
      if (f && f !== here && w && tabs.indexOf(w) < 0) { tabs.push(w); }
    });
    return tabs.length ? "Saves with the " + tabs.join(" and the ") + " tab." : "";
  }
  /* a hidden field as a segment of its choices */
  function segCopy(r, choices, label) {
    var seg = el("div", "pfas-seg pfas-seg-sm is-fit");
    seg.setAttribute("role", "group");
    seg.setAttribute("aria-label", label);
    choices.forEach(function (ch) {
      var b = el("button", "pfas-seg-item", ch[1]);
      b.type = "button";
      b.setAttribute("data-value", ch[0]);
      b.setAttribute("aria-pressed", String(r.value || "") === String(ch[0]) ? "true" : "false");
      seg.appendChild(b);
    });
    var c = comps();
    if (c && c.seg) { c.seg(seg); }
    return { node: seg, value: function () {
      var on = seg.querySelector('.pfas-seg-item[aria-pressed="true"]');
      return on ? on.getAttribute("data-value") : String(r.value || "");
    } };
  }
  function copy(r, label, choices) {
    var cp = choices ? segCopy(r, choices, label) : L().copyOf(r);
    var n = cp.input || cp.node;
    if (!choices) { n.setAttribute("aria-label", label); }
    if (r.name) { n.setAttribute("data-for-name", r.name); }
    return { real: r, cp: cp, start: cp.value() };
  }
  /* a table's rows as {label, cells: [{col, label, real}]} */
  function tableRows(t, spec) {
    var heads = {}, idx = [];
    list(t.querySelectorAll("thead th[data-col]")).forEach(function (th) { heads[th.getAttribute("data-col")] = clean(th.textContent); });
    var hr = t.tHead && t.tHead.rows.length ? t.tHead.rows[t.tHead.rows.length - 1] : null;
    if (hr) { list(hr.cells).forEach(function (c, i) { idx[i] = clean(c.textContent); }); }
    var cols = spec.cols || [], rows = spec.rows || [], out = [];
    list(t.tBodies).forEach(function (tb) {
      list(tb.rows).forEach(function (tr) {
        if (tr.hidden) { return; }
        var key = tr.getAttribute("data-row");
        if (rows.length && rows.indexOf(key) < 0) { return; }
        var cells = [], label = tr.getAttribute("data-label") || "";
        list(tr.cells).forEach(function (cell, i) {
          var col = cell.getAttribute("data-col") || String(i);
          var ins = list(cell.querySelectorAll("input, select, textarea")).filter(copyable);
          if (!ins.length) {
            if (!label && i < 2 && clean(cell.textContent)) { label = clean(cell.textContent); }
            return;
          }
          if (cols.length && !cols.some(function (p) { return col.indexOf(p) === 0; })) { return; }
          ins.forEach(function (r, k) {
            cells.push({ col: col + (k ? "." + k : ""), label: heads[col] || idx[i] || labelOf(r), real: r });
          });
        });
        if (cells.length) { out.push({ label: label, cells: cells }); }
      });
    });
    return out;
  }
  /* what a region's table is for: its QC type, else the heading drawn above it */
  function headOf(t) {
    var q = t.closest ? t.closest("[data-qc]") : null;
    if (q) { return q.getAttribute("data-qc"); }
    for (var n = t.closest(".pfas-scroll-x") || t; n; n = n.previousElementSibling) {
      if (n !== t && n.matches && n.matches(".section-group-hdr, h4, h5, .cf-coll-head")) { return clean(n.textContent); }
    }
    return "";
  }
  /* a table of copies; pairs collects what Done writes */
  function tableOf(rows, pairs) {
    var cols = [], names = {};
    rows.forEach(function (r) { r.cells.forEach(function (c) { if (!(c.col in names)) { names[c.col] = c.label; cols.push(c.col); } }); });
    var labelled = rows.some(function (r) { return r.label; });
    var t = el("table", "pfas-table pfas-inplace-table"), hr = el("tr");
    if (labelled) { hr.appendChild(el("th", "", "")); }
    cols.forEach(function (c) { var th = el("th", "", names[c]); th.setAttribute("scope", "col"); hr.appendChild(th); });
    var head = el("thead");
    head.appendChild(hr);
    t.appendChild(head);
    var body = el("tbody");
    rows.forEach(function (r) {
      var tr = el("tr");
      /* the row's name as the cards' own tables draw it, never upper-cased:
         each copy carries it in its label */
      if (labelled) { tr.appendChild(el("td", "pfas-inplace-l", r.label)); }
      cols.forEach(function (col) {
        var td = el("td"), c = r.cells.filter(function (x) { return x.col === col; })[0];
        if (c) {
          var p = copy(c.real, clean((r.label ? r.label + " " : "") + names[col]));
          pairs.push(p);
          td.appendChild(p.cp.node);
        }
        tr.appendChild(td);
      });
      body.appendChild(tr);
    });
    t.appendChild(body);
    var s = el("div", "pfas-scroll-x");
    s.appendChild(t);
    return s;
  }
  function field(label, node) {
    var f = el("div", "pfas-sheet-field");
    f.appendChild(el("div", "pfas-sheet-flabel", label));
    f.appendChild(node);
    return f;
  }
  /* the window's words and its one way out: what the profile does not hold */
  function tail(body, spec, reals) {
    var said = [spec.note, savesWith(reals)].filter(function (x) { return x; });
    said.forEach(function (w) { body.appendChild(el("p", "pfas-hier-note", w)); });
    if (spec.goto) {
      var go = el("div", "pfas-inplace-go"), a = el("a", "btn btn-sm btn-secondary", spec.goto[1]);
      a.setAttribute("href", spec.goto[0]);
      a.setAttribute("data-inplace-go", "");
      go.appendChild(a);
      body.appendChild(go);
      return a;
    }
    return null;
  }
  function open(spec, opener) {
    var c = comps(), lib = L();
    if (!c || !lib) { return null; }
    var names = (spec.names || []).map(function (n) { return { real: real(n[0]), label: n[1], choices: n[2] }; })
      .filter(function (x) { return x.real; });
    /* only plain fields: the shared copy editor, its ranges and steppers */
    if (names.length && !spec.tables && !spec.read && !names.some(function (x) { return x.choices; })) {
      var b0 = lib.editCopies(spec.title, names.map(function (x) { return { real: x.real, label: x.label }; }),
                              { opener: opener, ranges: true });
      if (b0) { tail(b0, spec, names.map(function (x) { return x.real; })); }
      return b0;
    }
    var body = el("div", "pfas-sheet-form pfas-inplace"), pairs = [];
    if (spec.read) { body.appendChild(el("p", "pfas-inplace-read", spec.read)); }
    names.forEach(function (x) {
      var p = copy(x.real, x.label, x.choices);
      pairs.push(p);
      body.appendChild(field(x.label, p.cp.node));
    });
    (spec.tables || []).forEach(function (ts) {
      var root = document.querySelector(ts.sel);
      if (!root) { return; }
      var one = String(root.localName || root.tagName || "").toLowerCase() === "table";
      var tables = one ? [root] : list(root.querySelectorAll("table"));
      if (!one) {
        /* a region: its own fields first, then each table in it */
        list(root.querySelectorAll("input, select, textarea")).filter(function (n) {
          return copyable(n) && !(n.closest && n.closest("table"));
        }).forEach(function (r) {
          var p = copy(r, labelOf(r));
          pairs.push(p);
          body.appendChild(field(labelOf(r), p.cp.node));
        });
      }
      tables.forEach(function (t, i) {
        var rows = tableRows(t, ts);
        if (!rows.length) { return; }
        var head = ts.head && !i ? ts.head : (one ? "" : headOf(t));
        if (head) { body.appendChild(el("h5", "pfas-hier-h", head)); }
        body.appendChild(tableOf(rows, pairs));
      });
    });
    var go = tail(body, spec, pairs.map(function (p) { return p.real; }));
    var foot = null;
    if (pairs.length) {
      foot = el("div", "pfas-drawer-actions");
      var done = el("button", "btn btn-primary", "Done");
      done.type = "button";
      done.addEventListener("click", function () {
        pairs.forEach(function (p) {
          var v = p.cp.value();
          if (v === p.start) { return; }
          var r = p.real;
          if (r.type === "checkbox") {
            if (r.checked !== !!v) { r.checked = !!v; lib.fire(r); }
          } else if (r.value !== v) { r.value = v; lib.fire(r); }
        });
        c.drawer.close();
      });
      foot.appendChild(done);
    }
    var first = pairs[0] ? pairs[0].cp.input || pairs[0].cp.node : go;
    if (first && first.classList && first.classList.contains("pfas-seg")) { first = first.querySelector('[aria-pressed="true"]') || first; }
    c.drawer.open(spec.title, body, { footer: foot, cls: "is-dialog", opener: opener || null, focus: first || null });
    return body;
  }
  document.addEventListener("click", function (e) {
    var b = e.target && e.target.closest ? e.target.closest("[data-inplace]") : null;
    if (!b) { return; }
    var spec = null;
    try { spec = JSON.parse(b.getAttribute("data-inplace") || "null"); } catch (err) { spec = null; }
    if (!spec) { return; }
    e.preventDefault();
    open(spec, b);
  });

  /* A card's Transitions block (profile_grids.transitions_block) follows the
     inputs Integration posts: each peak's quantifier, qualifiers and time,
     its window worked out from the method's Retention time tolerance, else
     the stored window, as rt_window does. */
  var NOT_SET = "Not set";
  function num(v) { var s = String(v === undefined || v === null ? "" : v).trim(); return s === "" ? NaN : Number(s); }
  function windowWords(rt, stored, tol, unit) {
    var t = num(rt), half;
    if (isNaN(t)) { return ""; }
    var v = num(tol);
    if (!isNaN(v) && v > 0) { half = unit === "min" ? v : t * v / 100; }
    else { half = num(stored); }
    if (isNaN(half)) { return ""; }
    return (t - half).toFixed(3) + " to " + (t + half).toFixed(3);
  }
  function json(n, k) { try { return JSON.parse(n.getAttribute(k) || "null"); } catch (e) { return null; } }
  function value(name) { var r = name ? real(name) : null; return r ? String(r.value || "").trim() : ""; }
  function redrawTrans(t) {
    var peaks = json(t, "data-trans-names") || [], tol = json(t, "data-trans-tol") || [];
    var tv = value(tol[0]), unit = value(tol[1]) || "pct";
    var trs = t.tBodies.length ? list(t.tBodies[0].rows) : [];
    peaks.forEach(function (p, i) {
      var tr = trs[i], n = p[1] || {};
      if (!tr || tr.cells.length < 5) { return; }
      var w = [value(n.quant), value(n.quals), value(n.rt), windowWords(value(n.rt), value(n.window), tv, unit)];
      w.forEach(function (x, j) {
        var cell = tr.cells[j + 1], said = x || NOT_SET;
        if (cell.textContent !== said) { cell.textContent = said; }
      });
    });
  }
  var transOf = null;
  function transIndex() {
    transOf = {};
    list(document.querySelectorAll("table[data-trans-names]")).forEach(function (t) {
      var names = (json(t, "data-trans-tol") || []).slice();
      (json(t, "data-trans-names") || []).forEach(function (p) {
        Object.keys(p[1] || {}).forEach(function (k) { names.push(p[1][k]); });
      });
      names.forEach(function (n) { (transOf[n] = transOf[n] || []).push(t); });
    });
  }
  document.addEventListener("change", function (e) {
    var n = e.target && e.target.name;
    if (!n) { return; }
    if (!transOf) { transIndex(); }
    (transOf[n] || []).forEach(redrawTrans);
  });
  window.PFAS = window.PFAS || {};
  window.PFAS.mpInPlace = { open: open, redrawTrans: redrawTrans };
})();

/* The Isotope standards tab's List view (profile_grids.render_standards_list):
   the list holds the two groups' nodes; each standard's mini-card in its
   group's card opens its own card (its group's node stays chosen; Back to
   the group returns), both mirroring its row of the grid, the Table view,
   which holds every posted input; the list posts nothing. A card's Edit and
   the mini-card's menu run the grid row's own drawer and menu entries
   (PFAS.components.sheet openRow / rowItems), whose nameless copies write
   the row's inputs with input and change, so the unsaved count follows;
   a refused entry never acts. + Add standard opens the shared drawer on a
   nameless copy of the grid's own chooser, writes the choice into it and
   sends its form (standards-add), as the grid's Add does. An edit in the
   grid is drawn again in the cards and nodes: a class's own window as a
   bar, a blank class as following Aqueous, a ticked None box as not assessed with its notation mark; the
   one surrogate window, as typed or else the method default. */
(function () {
  var LIST = "standards-list";
  function list() { return document.getElementById(LIST); }
  function comps() { return window.PFAS && window.PFAS.components ? window.PFAS.components : null; }
  function pane() { return document.getElementById("pane-standards"); }
  /* the standards grid (the rules block above it is a sheet of its own) */
  function grid() { var p = pane(); return p ? p.querySelector('.pfas-sheet-box[data-sheet="standards"]') : null; }
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
  function byAttr(nodes, attr, v) {
    return Array.prototype.filter.call(nodes, function (n) { return n.getAttribute(attr) === v; });
  }
  function rowOf(key) {
    var b = grid();
    return b ? byAttr(b.querySelectorAll("tr[data-row]"), "data-row", key)[0] || null : null;
  }

  /* Edit: the grid row's drawer (a row with no menu, limits no standard
     takes, has its drawer too); the other entries: the row menu's own */
  function edit(key) {
    var c = comps(), b = grid();
    if (c && b) { c.sheet.openRow(b, key); }
  }
  function runItem(key, id) {
    var c = comps(), b = grid();
    if (!c || !b) { return; }
    var it = c.sheet.rowItems(b, key).filter(function (x) { return x.id === id; })[0];
    if (it && !it.disabled) { it.act(); }
  }
  var EVENTS = { "std-role": "role", "std-copy": "copy", "std-reset": "reset", "std-remove": "remove" };
  document.addEventListener("pfas:row-action", function (e) {
    var node = e.detail && e.detail.row, l = list();
    if (!node || !l || !l.contains(node)) { return; }
    var key = node.getAttribute("data-std-row"), name = e.detail.name;
    if (name === "std-edit") { edit(key); } else if (EVENTS[name]) { runItem(key, EVENTS[name]); }
  });
  document.addEventListener("click", function (e) {
    var l = list(), b = e.target.closest ? e.target.closest("[data-std-act], [data-std-add]") : null;
    if (!b || !l || !l.contains(b)) { return; }
    if (b.hasAttribute("data-std-add")) { addStandard(b); return; }
    var key = b.getAttribute("data-std-row");
    if (b.getAttribute("data-std-act") === "edit") { edit(key); } else { runItem(key, "remove"); }
  });

  function addStandard(btn) {
    window.PFAS.mpList.addFrom(btn, btn.getAttribute("data-std-add"), "Standard", "Add a standard");
  }

  /* a pair column of a grid row as its inputs hold it: the two ends, what
     a blank end inherits (its placeholder) and the None box */
  function pairOf(tr, col) {
    var nums = [], none = null;
    byAttr(tr.querySelectorAll("td[data-col]"), "data-col", col).forEach(function (td) {
      Array.prototype.forEach.call(td.querySelectorAll("input"), function (i) {
        if (i.type === "number") { nums.push(i); } else if (i.type === "checkbox") { none = i; }
      });
    });
    function v(i) { return nums[i] ? String(nums[i].value || "").trim() : ""; }
    function ph(i) { return nums[i] ? String(nums[i].getAttribute("placeholder") || "").trim() : ""; }
    return { lo: v(0), hi: v(1), phLo: ph(0), phHi: ph(1), none: !!(none && none.checked), found: nums.length > 0 };
  }
  function g(v) { var n = Number(v); return v !== "" && isFinite(n) ? String(n) : v; }
  function words(lo, hi) {
    if (!lo && !hi) { return "Not set"; }
    return (lo ? g(lo) : "—") + " – " + (hi ? g(hi) : "—") + " %";
  }
  function ends(lo, hi) {
    var a = parseFloat(lo), b = parseFloat(hi);
    return lo !== "" && hi !== "" && isFinite(a) && isFinite(b) ? [a, b] : null;
  }
  function setBand(b, e, thin) {
    if (!b) { return; }
    b.hidden = !e;
    b.classList.toggle("is-thin", !!thin);
    if (!e) { return; }
    b.setAttribute("data-lo", String(e[0]));
    b.setAttribute("data-hi", String(e[1]));
    var c = comps();
    if (c) { c.hier.band(b, e[0], e[1], parseFloat(b.getAttribute("data-scale"))); }
  }
  function setValue(tile, text) {
    var v = tile.querySelector(".pfas-hier-tile-v");
    if (v) { v.textContent = text; }
  }
  function redraw(card, node, tr) {
    var aq = pairOf(tr, "eis-aq"), aqEnds = ends(aq.lo, aq.hi), none = false, shown = null;
    Array.prototype.forEach.call(card.querySelectorAll("[data-std-col]"), function (tile) {
      var col = tile.getAttribute("data-std-col"), band = tile.querySelector("[data-std-band]");
      if (col === "role") {
        /* the role's input, in the word the grid draws for it (data-words) */
        var td = tr.querySelector("td.pfas-sheet-role"), hid = td ? td.querySelector("input[type=hidden]") : null;
        var said = [];
        try { said = JSON.parse((td && td.getAttribute("data-words")) || "[]"); } catch (err) { said = []; }
        var hit = hid ? said.filter(function (x) { return x[0] === hid.value; })[0] : null;
        if (hid) { setValue(tile, hit ? hit[1] : hid.value); }
        return;
      }
      if (col === "link") {
        var sel = byAttr(tr.querySelectorAll("td[data-col]"), "data-col", "link")[0];
        sel = sel ? sel.querySelector("select") : null;
        if (sel) { setValue(tile, sel.value || "Not linked"); }
        return;
      }
      if (col === "salt") {
        /* the standard's salt factor, as typed in its grid row */
        var st = byAttr(tr.querySelectorAll("td[data-col]"), "data-col", "salt")[0], si = st ? st.querySelector("input") : null;
        if (si) { setValue(tile, String(si.value || "").trim() || "Not set"); }
        return;
      }
      var p = pairOf(tr, col);
      if (!p.found) { return; }
      if (col === "eis-aq") {
        shown = p;
        setValue(tile, words(p.lo, p.hi));
        setBand(band, ends(p.lo, p.hi), false);
        return;
      }
      if (tile.hasAttribute("data-std-note")) {
        /* the method's one surrogate window: typed, else the method default */
        var dflt = !p.lo && !p.hi && !!(p.phLo || p.phHi);
        var w = dflt ? { lo: p.phLo, hi: p.phHi } : p;
        shown = w;
        setValue(tile, words(w.lo, w.hi));
        setBand(band, ends(w.lo, w.hi), false);
        var s = tile.querySelector(".pfas-hier-tile-s");
        if (s) { s.textContent = tile.getAttribute("data-std-note") + (dflt ? " · " + tile.getAttribute("data-std-default") : ""); }
        return;
      }
      var state = p.none ? "none" : (p.lo || p.hi ? "own" : "follows");
      tile.setAttribute("data-std-state", state);
      var v = tile.querySelector(".pfas-hier-tile-v");
      if (state === "none") {
        none = true;
        v.textContent = "";
        v.appendChild(el("span", "pfas-sheet-val is-empty", "—"));
        v.appendChild(el("sup", "", "1"));
        setBand(band, null);
      } else if (state === "follows") {
        v.textContent = "Follows Aqueous";
        setBand(band, aqEnds, true);
      } else {
        v.textContent = words(p.lo, p.hi);
        setBand(band, ends(p.lo, p.hi), false);
      }
    });
    var foot = card.querySelector("[data-std-footnote]");
    if (foot) { foot.hidden = !none; }
    if (shown) {
      /* its mini-card in the group's card (and the node of limits no standard takes) */
      var l = list(), key = card.getAttribute("data-std-row");
      var minis = l ? byAttr(l.querySelectorAll(".pfas-hier-mini[data-std-open]"), "data-std-open", key) : [];
      (node ? [node] : []).concat(minis).forEach(function (n) {
        var nv = n.querySelector("[data-std-value]");
        if (!nv) { return; }
        nv.textContent = words(shown.lo, shown.hi);
        setBand(n.querySelector("[data-std-band]"), ends(shown.lo, shown.hi), false);
      });
    }
  }
  function redrawAll() {
    var l = list();
    if (!l) { return; }
    Array.prototype.forEach.call(l.querySelectorAll("[data-hier-card][data-std-row]"), function (card) {
      var key = card.getAttribute("data-std-row"), tr = rowOf(key);
      if (!tr) { return; }
      redraw(card, byAttr(l.querySelectorAll(".pfas-hier-node"), "data-std-row", key)[0] || null, tr);
    });
    redrawRules();
    redrawSettings();
    redrawChain();
  }

  /* The Internal standards card's chain (profile_grids._render_chain):
     each standard sits under the internal standard its grid row's Linked
     to names, else under Not linked, shown only while it holds one. The
     analytes each corrects are the Analytes tab's, read as saved. */
  function redrawChain() {
    var l = list(), box = l ? l.querySelector("[data-std-chain]") : null;
    if (!box) { return; }
    var blocks = box.querySelectorAll("[data-chain-is]"), loose = byAttr(blocks, "data-chain-is", "")[0] || null;
    Array.prototype.forEach.call(box.querySelectorAll("[data-chain-std]"), function (li) {
      var tr = rowOf(li.getAttribute("data-chain-std"));
      var td = tr ? byAttr(tr.querySelectorAll("td[data-col]"), "data-col", "link")[0] : null;
      var sel = td ? td.querySelector("select") : null;
      if (!sel) { return; }
      var to = (sel.value && byAttr(blocks, "data-chain-is", sel.value)[0]) || loose;
      if (!to || to === li.closest("[data-chain-is]")) { return; }
      to.querySelector(".pfas-hier-chain-l").appendChild(li);
    });
    if (loose) { loose.hidden = !loose.querySelector("[data-chain-std]"); }
    /* what each internal standard quantifies, counted as the links now stand:
       its tile in Links and its mini-card */
    Array.prototype.forEach.call(blocks, function (b) {
      var key = b.getAttribute("data-chain-is");
      if (!key) { return; }
      var said = quantifies(b);
      var v = b.querySelector(".pfas-hier-tile-v");
      if (v) { v.textContent = said; }
      byAttr(l.querySelectorAll(".pfas-hier-mini[data-std-open]"), "data-std-open", key).forEach(function (m) {
        var s = m.querySelector("[data-std-does]");
        if (s) { s.textContent = said; }
      });
    });
  }
  /* "Quantifies 4 surrogates and 6 analytes" (profile_grids._is_quantifies):
     the standards in its block, its own analytes as drawn */
  function counted(n, noun) { return n + " " + noun + (n === 1 ? "" : "s"); }
  function quantifies(block) {
    var linked = Array.prototype.filter.call(block.querySelectorAll("[data-chain-std]"), function (li) {
      return !li.hasAttribute("data-chain-cmp");
    }).length;
    var own = parseInt(block.getAttribute("data-own") || "0", 10);
    var parts = (linked ? [counted(linked, "surrogate")] : []).concat(own ? [counted(own, "analyte")] : []);
    return parts.length ? "Quantifies " + parts.join(" and ") : "Quantifies nothing";
  }

  /* Each group's other settings (profile_grids.std_settings): a tile per
     field of the sections the Table view draws, read from its posted inputs
     by name (data-set-names) in the words the server draws: a switch Yes or
     No, a choice its option's words, a window its ends and bar, words as
     typed, else Not set. Edit settings opens the shared drawer on nameless
     copies of them all, Done writing each changed one with input and change.
     A tile naming another form (data-set-form) reads that form's inputs: QC
     criteria's Calibration card draws its settings the same way. */
  var NUM = /^-?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/;
  function json(n, k, d) { try { return JSON.parse(n.getAttribute(k) || "null") || d; } catch (e) { return d; } }
  function posted(name, form) {
    return Array.prototype.filter.call(document.getElementsByName(name), function (n) {
      return n.getAttribute("form") === (form || "section-standards");
    })[0] || null;
  }
  function formOf(tile) { return tile.getAttribute("data-set-form") || "section-standards"; }
  /* a setting another fixes (data-set-fixed: QC criteria's Origin under an
     Average RF, which passes through the origin): {words, note} while the
     other input holds the value, else null */
  function fixedBy(tile) {
    var fx = json(tile, "data-set-fixed", null);
    if (!fx) { return null; }
    var other = posted(fx.name, formOf(tile));
    return other && String(other.value || "") === fx.value ? fx : null;
  }
  function settingWords(tile) {
    var kind = tile.getAttribute("data-set-kind"), form = formOf(tile);
    var fx = fixedBy(tile);
    if (fx) { return { text: fx.words }; }
    var reals = json(tile, "data-set-names", []).map(function (n) { return posted(n, form); });
    if (reals.some(function (r) { return !r; })) { return null; }
    if (kind === "pair") {
      var a = String(reals[0].value || "").trim(), b = String(reals[1].value || "").trim();
      /* an empty window that uses another one says so (data-set-blank) */
      if (!a && !b && tile.hasAttribute("data-set-blank")) { return { text: tile.getAttribute("data-set-blank"), ends: null }; }
      return { text: words(a, b), ends: ends(a, b) };
    }
    if (kind === "bool") { return { text: reals[0].checked ? "Yes" : "No" }; }
    if (kind === "multi") {
      /* a list of boxes: the ticked ones' words */
      var labels = json(tile, "data-set-labels", []);
      var on = labels.filter(function (l, i) { return reals[i].checked; });
      return { text: on.length ? on.join(", ") : "None" };
    }
    var v = String(reals[0].value || "").trim();
    if (!v && tile.hasAttribute("data-set-blank")) { return { text: tile.getAttribute("data-set-blank") }; }
    if (kind === "choice") {
      var hit = json(tile, "data-set-choices", []).filter(function (c) { return c[0] === v; })[0];
      return { text: hit ? hit[1] : (v || "Not set") };
    }
    var unit = tile.getAttribute("data-set-unit");
    return { text: v ? (unit && NUM.test(v) ? v + " " + unit : v) : "Not set" };
  }
  function redrawSettings(root) {
    var l = root || list();
    if (!l) { return; }
    Array.prototype.forEach.call(l.querySelectorAll("[data-set-names]"), function (tile) {
      var w = settingWords(tile);
      if (!w) { return; }
      setValue(tile, w.text);
      if (tile.getAttribute("data-set-kind") === "pair") { setBand(tile.querySelector("[data-set-band]"), w.ends, false); }
    });
  }
  function settingItems(card) {
    var items = [];
    Array.prototype.forEach.call(card.querySelectorAll("[data-set-names]"), function (tile) {
      // a setting another fixes is not edited while it is fixed
      if (fixedBy(tile)) { return; }
      var labels = json(tile, "data-set-labels", []);
      /* what an empty one falls back to, in full: "Uses the Recovery
         window" reads Recovery in its box */
      var blank = String(tile.getAttribute("data-set-blank") || "").replace(/^Uses the (.+) window$/i, "$1");
      blank = blank ? blank.charAt(0).toUpperCase() + blank.slice(1) : "";
      json(tile, "data-set-names", []).forEach(function (name, i) {
        var real = posted(name, formOf(tile));
        if (real) {
          items.push({ real: real, label: labels[i] || name, blank: blank || undefined,
                       unit: tile.getAttribute("data-set-unit") || undefined });
        }
      });
    });
    return items;
  }
  document.addEventListener("click", function (e) {
    var b = e.target.closest ? e.target.closest("[data-std-settings]") : null, l = list();
    if (!b || !l || !l.contains(b) || !window.PFAS.mpList) { return; }
    var card = b.closest("[data-hier-card]"), title = card ? card.querySelector(".pfas-hier-card-t") : null;
    var items = card ? settingItems(card) : [];
    if (items.length) { window.PFAS.mpList.editCopies((title ? title.textContent : "Settings") + ": settings", items, { opener: b }); }
  });

  /* QC criteria's Calibration card (profile_grids._cal_group_entry): its
     tiles follow the calibration inputs QC criteria posts, wherever they
     are edited, and Edit calibration opens the shared drawer on nameless
     copies of them, Done writing each changed one with input and change.
     The other group cards (profile_cards.qc_group_entry: CCV, Confirmation
     and signal, Analyte recoveries, Blanks, Worksheet) draw theirs the same
     way; Edit on one of them, or Edit limits on one of its rules' cards
     (data-qc-card-of naming the group's), opens the centred window on the
     copies of one region's tiles (data-qc-edit naming its block). The
     group nodes' state lines follow the rule table's state inputs. */
  function rulesListEl() { return document.getElementById("rules-list"); }
  /* a blank's tile says what a result equal to its limit does, following
     its Fails at the limit box (data-at-limit names it) */
  function atLimit(root) {
    Array.prototype.forEach.call(root.querySelectorAll("[data-at-limit]"), function (w) {
      var box = posted(w.getAttribute("data-at-limit"), "section-qc");
      if (box) { w.textContent = w.getAttribute(box.checked ? "data-on-words" : "data-off-words") || w.textContent; }
    });
  }
  function calCard() {
    var r = rulesListEl();
    return r ? r.querySelector("[data-cal-card]") : null;
  }
  function qcCards() {
    var r = rulesListEl();
    return r ? Array.prototype.slice.call(r.querySelectorAll("[data-cal-card], [data-qc-card]")) : [];
  }
  ["input", "change"].forEach(function (t) {
    document.addEventListener(t, function (e) {
      if (!e.target || !e.target.getAttribute || e.target.getAttribute("form") !== "section-qc") { return; }
      qcCards().forEach(function (card) { if (!card.contains(e.target)) { redrawSettings(card); } });
      var r = rulesListEl();
      if (!r) { return; }
      atLimit(r);
      Array.prototype.forEach.call(r.querySelectorAll(".pfas-hier-node.is-group [data-state-of]"), function (line) {
        var input = document.getElementById(line.getAttribute("data-state-of"));
        if (!input) { return; }
        sayState(line, input.value);
      });
    });
  });
  document.addEventListener("click", function (e) {
    var b = e.target.closest ? e.target.closest("[data-cal-settings]") : null, card = calCard();
    /* the Calibration card's, or a Calibration rule's card's (its limits) */
    if (!b || !card || !rulesListEl().contains(b) || !window.PFAS.mpList) { return; }
    var title = card.querySelector(".pfas-hier-card-t"), items = settingItems(card);
    if (items.length) { window.PFAS.mpList.editCopies(title ? title.textContent : "Calibration", items, { opener: b }); }
  });
  document.addEventListener("click", function (e) {
    var b = e.target.closest ? e.target.closest("[data-qc-edit]") : null, r = rulesListEl();
    if (!b || !r || !r.contains(b) || !window.PFAS.mpList) { return; }
    var of = b.getAttribute("data-qc-card-of");
    var card = of ? byAttr(r.querySelectorAll("[data-hier-card]"), "data-hier-card", of)[0] : b.closest("[data-hier-card]");
    if (!card) { return; }
    var root = byAttr(card.querySelectorAll("[data-qc-block]"), "data-qc-block", b.getAttribute("data-qc-edit"))[0] || card;
    var title = card.querySelector(".pfas-hier-card-t"), items = settingItems(root);
    if (items.length) {
      window.PFAS.mpList.editCopies((title ? title.textContent : "Edit") + ": " + b.textContent.replace(/^Edit /, ""), items,
                                    { opener: b, ranges: true });
    }
  });

  /* Each group's rules (Surrogates, Internal standards: the group node and
     card, profile_grids._std_group_entry): a rule's window is read from its
     two posted inputs, named on the value (data-lo-name / data-hi-name; a
     blank pair reads its default, "Method default" in the note), its state
     line from its state input in the rules block (data-state-of). */
  var STATE_WORDS = { enforced: "Enforced", evaluate: "Evaluate", off: "Off" };
  /* a state line: words, or the placard's glyph (PFAS.components.limit.line) */
  function sayState(line, v) {
    var C = window.PFAS && window.PFAS.components;
    if (C && C.limit && C.limit.line) { C.limit.line(line, v); return; }
    line.textContent = v ? (STATE_WORDS[v] || v) : (line.getAttribute("data-inherited") || "");
  }
  function named(name) { return name ? document.getElementsByName(name)[0] || null : null; }
  function redrawRules() {
    var l = list();
    if (!l) { return; }
    Array.prototype.forEach.call(l.querySelectorAll("[data-rule-win][data-lo-name]"), function (v) {
      var lo = named(v.getAttribute("data-lo-name")), hi = named(v.getAttribute("data-hi-name"));
      if (!lo || !hi) { return; }
      var a = String(lo.value || "").trim(), b = String(hi.value || "").trim(), dflt = false;
      if (!a && !b && (v.getAttribute("data-default-lo") || v.getAttribute("data-default-hi"))) {
        a = v.getAttribute("data-default-lo") || ""; b = v.getAttribute("data-default-hi") || ""; dflt = true;
      }
      v.textContent = words(a, b);
      var key = v.getAttribute("data-rule-win"), box = v.parentNode;
      setBand(byAttr(box.querySelectorAll("[data-rule-band]"), "data-rule-band", key)[0], ends(a, b), false);
      var note = byAttr(box.querySelectorAll("[data-rule-note]"), "data-rule-note", key)[0];
      if (note) {
        note.textContent = [note.getAttribute("data-note") || "", dflt ? note.getAttribute("data-default-words") || "" : ""]
          .filter(function (x) { return x; }).join(" · ");
      }
    });
    Array.prototype.forEach.call(l.querySelectorAll("[data-state-of]"), function (line) {
      var input = document.getElementById(line.getAttribute("data-state-of"));
      if (!input) { return; }
      sayState(line, input.value);
    });
  }
  ["input", "change"].forEach(function (t) {
    document.addEventListener(t, function (e) {
      var p = pane(), l = list();
      if (!p || !l || !e.target || !p.contains(e.target) || l.contains(e.target)) { return; }
      redrawAll();
    });
  });

  /* a mini-card in a group's card opens its standard's card, its group's
     node staying chosen; Back to the group opens the group's card on its node */
  document.addEventListener("click", function (e) {
    var m = e.target.closest ? e.target.closest("[data-std-open]") : null, l = list(), c = comps();
    if (!m || !l || !l.contains(m) || !c || !c.hier) { return; }
    var key = m.getAttribute("data-std-open"), node = c.hier.select(l, key, true);
    if (!node) { return; }
    if (node.getAttribute("data-hier-target") === key) {
      if (node.focus) { node.focus(); }
      if (node.scrollIntoView) { node.scrollIntoView({ block: "nearest" }); }
      return;
    }
    var card = byAttr(l.querySelectorAll("[data-hier-card]"), "data-hier-card", key)[0];
    if (card && card.scrollIntoView) { card.scrollIntoView({ block: "nearest" }); }
  });

  /* the tab's warnings (profile_grids._link_warning): a name leaves once the
     input holding its link holds one (data-needs-one-of: one of those, a
     surrogate's internal standards), the warning once none is left */
  function redrawWarnings() {
    Array.prototype.forEach.call(document.querySelectorAll("[data-link-warn]"), function (w) {
      var left = 0;
      Array.prototype.forEach.call(w.querySelectorAll("[data-needs]"), function (chip) {
        var input = document.getElementsByName(chip.getAttribute("data-needs"))[0];
        var v = input ? String(input.value || "").trim() : "", allowed = null;
        try { allowed = JSON.parse(chip.getAttribute("data-needs-one-of") || "null"); } catch (err) { allowed = null; }
        chip.hidden = !!v && (!allowed || allowed.indexOf(v) >= 0);
        if (!chip.hidden) { left += 1; }
      });
      w.hidden = !left;
    });
  }
  document.addEventListener("change", redrawWarnings);

  /* A grid row's card: Show its card (the row's menu) shows the List view
     with that standard's card chosen. */
  function openCard(key) {
    var c = comps(), l = list();
    if (!c || !l || !key) { return; }
    c.hier.view("standards", "list", false);
    c.hier.select(l, key, true);
    var card = byAttr(l.querySelectorAll("[data-hier-card]"), "data-hier-card", key)[0];
    if (card && card.scrollIntoView) { card.scrollIntoView({ block: "nearest" }); }
    var t = card ? card.querySelector(".pfas-hier-card-t") : null;
    if (t) { t.setAttribute("tabindex", "-1"); t.focus(); }
  }
  document.addEventListener("pfas:row-card", function (e) {
    var tr = e.detail && e.detail.row, g = grid();
    if (tr && g && g.contains(tr)) { openCard(e.detail.key); }
  });
  document.addEventListener("click", function (e) {
    var g = grid(), t = e.target;
    if (!g || !t || !t.closest || e.button || e.defaultPrevented) { return; }
    var at = t.closest('tbody th.pfas-sheet-label, tbody td[data-col="quant"]'), tr = at ? at.closest("tr[data-card]") : null;
    if (!tr || !g.contains(tr) || t.closest("a[href], button, input, select, label")) { return; }
    /* in place: the name opens the row's window, the count what it
       quantifies; its card is the menu's Show its card */
    var key = tr.getAttribute("data-row");
    if (at.getAttribute("data-col") === "quant") { runItem(key, "quantifies"); } else { edit(key); }
  });

  /* Edit limits on a group's card: the shared drawer on nameless copies of
     the group's window inputs (PFAS.mpList.editCopies), Done writing each
     changed one with input and change. The surrogate window is edited as
     the grid's own row cell, which writes every SUR row and the one posted
     field; with no SUR row, the posted field itself as a number box. */
  function limitItems(card) {
    var items = [];
    Array.prototype.forEach.call(card.querySelectorAll(".pfas-hier-tiles [data-rule-win][data-lo-name]"), function (v) {
      var label = v.parentNode.querySelector(".pfas-hier-tile-l");
      label = label ? label.textContent : v.getAttribute("data-rule-win");
      [["data-lo-name", "min", "data-default-lo"], ["data-hi-name", "max", "data-default-hi"]].forEach(function (end) {
        var name = v.getAttribute(end[0]), b = grid();
        var shared = b ? byAttr(b.querySelectorAll("input[data-shared]"), "data-shared", name)[0] : null;
        var real = shared || named(name);
        if (!real) { return; }
        items.push({ real: real, label: label + " " + end[1], blank: v.getAttribute(end[2]) || "",
                     number: real.type === "hidden", end: end[1] === "min" ? "lo" : "hi", stem: label });
      });
    });
    return items;
  }
  document.addEventListener("click", function (e) {
    var b = e.target.closest ? e.target.closest("[data-std-limits]") : null, l = list();
    if (!b || !l || !l.contains(b) || !window.PFAS.mpList) { return; }
    var card = b.closest("[data-hier-card]"), title = card ? card.querySelector(".pfas-hier-card-t") : null;
    var items = card ? limitItems(card) : [];
    if (items.length) {
      window.PFAS.mpList.editCopies((title ? title.textContent : "Limits") + ": limits", items, { opener: b, ranges: true });
    }
  });
})();

/* Composite standards on the Isotope standards tab's List view
   (profile_grids._cmp_entry and combine_offer): + Combine surrogates on the
   Surrogates card opens a centred window to choose two or more of the
   method's surrogates, in order; the name is built from them ("Mean of A
   and B"), never typed. Create writes one composite row into the tab's form
   (an id the profile does not hold, which the server replaces with a fresh
   one, and the members) with input and change, so the unsaved count
   follows, and draws its mini-card in the Surrogates card and its card; the tab's Save
   stores it. Edit members writes its members input the same way. Remove
   composite clears its id (a composite drawn since the page loaded loses
   its inputs), refused while it corrects an analyte: that is set by
   Quantified by on the Analytes tab. The window refuses fewer than two
   members, one chosen twice, members linked to different standards and a
   set already combined; the save checks each again. */
(function () {
  var FORM = "section-standards", AVERAGED = "Mean of the areas";
  function list() { return document.getElementById("standards-list"); }
  function comps() { return window.PFAS && window.PFAS.components ? window.PFAS.components : null; }
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
  function andWords(names) {
    return names.length < 2 ? names.join("") : names.slice(0, -1).join(", ") + " and " + names[names.length - 1];
  }
  function nameOf(members) { return "Mean of " + andWords(members); }
  function splitMembers(v) {
    return String(v || "").split(",").map(function (m) { return m.trim(); }).filter(function (m) { return m; });
  }
  function addBtn() { var l = list(); return l ? l.querySelector("[data-cmp-add]") : null; }
  function offer(btn) {
    try { return JSON.parse(btn.getAttribute("data-cmp-offer") || "[]") || []; } catch (e) { return []; }
  }
  function posted(name) {
    return Array.prototype.filter.call(document.getElementsByName(name), function (n) {
      return n.getAttribute("form") === FORM;
    })[0] || null;
  }
  function inputs(btn, index) {
    var i = String(index);
    return { id: posted(btn.getAttribute("data-cmp-id-name").replace("{i}", i)),
             members: posted(btn.getAttribute("data-cmp-members-name").replace("{i}", i)) };
  }
  function byKey(nodes, attr, v) {
    return Array.prototype.filter.call(nodes, function (n) { return n.getAttribute(attr) === v; })[0] || null;
  }
  function cardOf(key) {
    var l = list();
    return l ? Array.prototype.filter.call(l.querySelectorAll("[data-cmp-of]"), function (c) {
      return c.getAttribute("data-cmp-of") === key;
    })[0] || null : null;
  }
  /* every composite's members as the form holds them, but `skip`'s */
  function combined(btn, skip) {
    var l = list(), out = [];
    Array.prototype.forEach.call(l.querySelectorAll("[data-cmp-of]"), function (c) {
      if (c.getAttribute("data-cmp-of") === skip || c.hidden && c.hasAttribute("data-cmp-removed")) { return; }
      var ins = inputs(btn, c.getAttribute("data-cmp-index"));
      if (ins.id && ins.id.value && ins.members) { out.push(splitMembers(ins.members.value)); }
    });
    return out;
  }
  /* why these members cannot be combined, or "" */
  function problem(members, btn, skip) {
    if (members.length < 2) { return "Choose two or more surrogates."; }
    var twice = members.filter(function (m, i) { return members.indexOf(m) !== i; });
    if (twice.length) { return twice[0] + " is chosen twice."; }
    var link = {};
    offer(btn).forEach(function (o) { link[o[0]] = o[1] || ""; });
    var refs = members.map(function (m) { return link[m] || ""; });
    if (refs.some(function (r) { return r !== refs[0]; })) {
      return "These surrogates are linked to different standards: a composite's members share one link.";
    }
    var key = members.slice().sort().join("\n");
    if (combined(btn, skip).some(function (m) { return m.slice().sort().join("\n") === key; })) {
      return "These surrogates are combined already.";
    }
    return "";
  }
  /* the window: one choice per member, in order, + Add member, the name as
     it will read; `done(members)` on Create / Apply */
  function openWindow(btn, opener, title, start, action, skip, done) {
    var c = comps();
    if (!c) { return null; }
    var body = el("div", "pfas-sheet-form pfas-cmp-form"), rows = el("div", "pfas-cmp-members"), choices = offer(btn);
    var preview = el("p", "pfas-hier-note"), error = el("p", "pfas-hier-note is-error");
    error.setAttribute("role", "alert");
    error.hidden = true;
    function selects() { return Array.prototype.slice.call(rows.querySelectorAll("select")); }
    function chosen() { return selects().map(function (s) { return s.value; }).filter(function (v) { return v; }); }
    function redraw() {
      var m = chosen();
      preview.textContent = m.length ? nameOf(m) : "Choose the surrogates to average.";
      error.hidden = true;
    }
    function addRow(value) {
      var f = el("div", "pfas-sheet-field"), s = el("select");
      f.appendChild(el("div", "pfas-sheet-flabel", "Member " + (selects().length + 1)));
      var none = el("option", "", "Choose a surrogate");
      none.value = "";
      s.appendChild(none);
      choices.forEach(function (o) {
        var opt = el("option", "", o[0]);
        opt.value = o[0];
        s.appendChild(opt);
      });
      s.value = value || "";
      s.setAttribute("aria-label", "Member " + (selects().length + 1));
      s.addEventListener("change", redraw);
      f.appendChild(s);
      rows.appendChild(f);
      return s;
    }
    var first = null;
    (start.length ? start : ["", ""]).forEach(function (m) { var s = addRow(m); first = first || s; });
    var more = el("button", "btn btn-sm btn-secondary pfas-cmp-more", "+ Add member");
    more.type = "button";
    more.addEventListener("click", function () { addRow("").focus(); });
    var avg = el("div", "pfas-sheet-field");
    avg.appendChild(el("div", "pfas-sheet-flabel", "Averaged as"));
    avg.appendChild(el("span", "", AVERAGED));
    body.appendChild(rows);
    body.appendChild(more);
    body.appendChild(avg);
    body.appendChild(preview);
    body.appendChild(error);
    redraw();
    var foot = el("div", "pfas-drawer-actions"), cancel = el("button", "btn btn-secondary", "Cancel"),
        ok = el("button", "btn btn-primary", action);
    cancel.type = ok.type = "button";
    cancel.addEventListener("click", function () { c.drawer.close(); });
    ok.addEventListener("click", function () {
      var m = chosen(), why = problem(m, btn, skip);
      if (why) { error.textContent = why; error.hidden = false; return; }
      c.drawer.close();
      done(m);
    });
    foot.appendChild(cancel);
    foot.appendChild(ok);
    c.drawer.open(title, body, { footer: foot, cls: "is-dialog", opener: opener, focus: first });
    return body;
  }
  /* a card's and node's words for its members */
  function drawMembers(key, members, saved) {
    var l = list(), card = cardOf(key);
    Array.prototype.forEach.call(l.querySelectorAll("[data-cmp-row], [data-cmp-mini], [data-cmp-of]"), function (n) {
      var k = n.getAttribute("data-cmp-row") || n.getAttribute("data-cmp-mini") || n.getAttribute("data-cmp-of");
      if (k !== key) { return; }
      Array.prototype.forEach.call(n.querySelectorAll("[data-cmp-title]"), function (t) { t.textContent = nameOf(members); });
      var count = n.querySelector("[data-cmp-count]");
      if (count) { count.textContent = members.length + " members"; }
    });
    if (!card) { return; }
    card.setAttribute("aria-label", nameOf(members));
    card.setAttribute("data-cmp-members-of", members.join(", "));
    var chips = card.querySelector("[data-cmp-members]");
    if (chips) {
      chips.textContent = "";
      members.forEach(function (m) {
        var b = el("button", "pfas-hier-chip", m);
        b.type = "button";
        b.setAttribute("data-std-open", m);
        b.setAttribute("aria-label", "Show " + m);
        chips.appendChild(b);
      });
    }
    var cap = card.querySelector("[data-cmp-cap]");
    if (cap && !saved) { cap.textContent = "Composite · " + members.length + " members · not saved yet"; }
  }
  /* a composite created in the window: its mini-card after the others in
     the Surrogates card, its card with the others, opened from it */
  function drawNew(key, index) {
    var l = list(), group = byKey(l.querySelectorAll("[data-hier-card]"), "data-hier-card", "group-sur");
    var minis = group ? group.querySelector(".pfas-hier-minis") : null;
    var mini = el("button", "pfas-hier-mini");
    mini.type = "button";
    mini.setAttribute("data-std-open", key);
    mini.setAttribute("data-cmp-mini", key);
    var t = el("span", "pfas-hier-mini-t");
    t.setAttribute("data-cmp-title", "1");
    mini.appendChild(t);
    mini.appendChild(el("span", "pfas-hier-mini-s", "Composite · not saved yet"));
    if (minis) { minis.appendChild(mini); }
    var card = el("section", "pfas-hier-card");
    card.setAttribute("data-hier-card", key);
    card.setAttribute("data-cmp-of", key);
    card.setAttribute("data-cmp-index", String(index));
    card.setAttribute("data-cmp-new", "1");
    card.setAttribute("data-hier-parent", "group-sur");
    card.hidden = true;
    var h = el("h4", "pfas-hier-card-t");
    h.setAttribute("data-cmp-title", "1");
    var cap = el("p", "pfas-hier-card-cap");
    cap.setAttribute("data-cmp-cap", "1");
    var head = el("h5", "pfas-hier-h", "Members"), chips = el("span", "pfas-hier-chips");
    chips.setAttribute("data-cmp-members", "1");
    var note = el("p", "pfas-hier-note", "Saved with Isotope standards. Set what it corrects by Quantified by on " +
                  "the Analytes tab once it is saved.");
    /* as the server draws a composite's card: its actions are triggers a
       click on its heading's menu presses; the one button row, Back */
    card.setAttribute("data-tile-open", "edit");
    var trig = el("div", "pfas-hier-acts");
    trig.hidden = true;
    [["edit", "Edit members"], ["remove", "Remove composite"]].forEach(function (a) {
      var b = el("button", "", a[1]);
      b.type = "button";
      b.setAttribute("data-act", a[0]);
      b.setAttribute("data-cmp-act", a[0]);
      b.setAttribute("data-cmp-row", key);
      if (a[0] === "remove") { b.setAttribute("data-danger", "1"); }
      trig.appendChild(b);
    });
    var acts = el("div", "pfas-hier-actions");
    var back = el("button", "btn btn-sm btn-secondary", "Back to Surrogates");
    back.type = "button";
    back.setAttribute("data-std-open", "group-sur");
    acts.appendChild(back);
    [h, cap, head, chips, note, trig, acts].forEach(function (n) { card.appendChild(n); });
    l.querySelector(".pfas-hier-cards").appendChild(card);
    return card;
  }
  function create(btn) {
    openWindow(btn, btn, btn.getAttribute("data-cmp-title-words") || "Combine surrogates", [], "Create", null,
               function (members) {
      var index = parseInt(btn.getAttribute("data-cmp-next") || "0", 10), form = document.getElementById(FORM);
      btn.setAttribute("data-cmp-next", String(index + 1));
      var key = "new-" + index;
      [["data-cmp-id-name", key], ["data-cmp-members-name", members.join(", ")]].forEach(function (p) {
        var n = el("input");
        n.type = "hidden";
        n.name = btn.getAttribute(p[0]).replace("{i}", String(index));
        n.setAttribute("form", FORM);
        /* one composite in the footer's count, its inputs drawn blank (a
           hidden input's value is its default, so the count is told) */
        n.setAttribute("data-kind", "composite");
        n.setAttribute("data-unit", "cmp-new-" + index);
        n.__pfasInit = "";
        n.value = p[1];
        (form || document.body).appendChild(n);
        fire(n);
      });
      drawNew(key, index);
      drawMembers(key, members, false);
      var c = comps(), l = list();
      if (c && c.hier) { c.hier.select(l, key, true); }
    });
  }
  function editMembers(btn, opener, key) {
    var card = cardOf(key);
    if (!card) { return; }
    var ins = inputs(btn, card.getAttribute("data-cmp-index"));
    if (!ins.members) { return; }
    openWindow(btn, opener, "Edit members", splitMembers(ins.members.value), "Apply", key, function (members) {
      var v = members.join(", ");
      if (ins.members.value !== v) { ins.members.value = v; fire(ins.members); }
      drawMembers(key, members, !card.hasAttribute("data-cmp-new"));
    });
  }
  function removeComposite(btn, key) {
    var card = cardOf(key), l = list(), c = comps();
    if (!card) { return; }
    var ins = inputs(btn, card.getAttribute("data-cmp-index"));
    if (card.hasAttribute("data-cmp-new")) {
      /* drawn since the page loaded: its inputs go with it, back to blank
         first so the footer stops counting it */
      [ins.id, ins.members].forEach(function (n) { if (n) { n.value = ""; fire(n); } });
      [ins.id, ins.members].forEach(function (n) { if (n && n.parentNode) { n.parentNode.removeChild(n); } });
    } else if (ins.id && ins.id.value) {
      ins.id.value = "";
      fire(ins.id);
    }
    card.setAttribute("data-cmp-removed", "1");
    Array.prototype.forEach.call(l.querySelectorAll("[data-cmp-row], [data-cmp-mini]"), function (n) {
      if ((n.getAttribute("data-cmp-row") || n.getAttribute("data-cmp-mini")) === key && n.closest("[data-cmp-of]") === null) {
        n.hidden = true;
      }
    });
    if (c && c.hier) { c.hier.select(l, "group-sur", true); }
    card.hidden = true;
  }
  document.addEventListener("click", function (e) {
    var l = list(), b = e.target.closest ? e.target.closest("[data-cmp-add], [data-cmp-act]") : null;
    if (!b || !l || !l.contains(b) || b.disabled) { return; }
    var btn = addBtn();
    if (!btn) { return; }
    if (b.hasAttribute("data-cmp-add")) { create(btn); return; }
    var key = b.getAttribute("data-cmp-row");
    if (b.getAttribute("data-cmp-act") === "edit") { editMembers(btn, b, key); } else { removeComposite(btn, key); }
  });
  window.PFAS = window.PFAS || {};
  window.PFAS.composites = { nameOf: nameOf, problem: problem };
})();

/* The Matrices tab's List view (profile_grids.render_matrices_list): All
   matrices, the parent every matrix follows (the storage and receipt ranges,
   same-day on ice), then each matrix's node and card, all mirroring the grid,
   the Table view, which holds every posted input; the list posts nothing.
   Edit on All matrices opens the grid's heading row in the shared drawer
   (PFAS.components.sheet openGroup), Edit matrix and the node's menu the
   matrix's row (openRow), whose nameless copies write the row's inputs with
   input and change; Remove from method posts the matrix to matrices-remove,
   as the grid's Remove posts the ticked rows (the server refuses one still
   in use); + Add matrix writes the grid's own chooser and sends the tab's
   form, as the grid's Add does. An edit in the grid is drawn again in the
   tiles and nodes: a range in °C with its bar, a value not set reading so.
   A matrix's own temperature ranges and same-day on ice read "As All
   matrices" until set; Reset to All matrices (the node's and the row's
   menu, and the button in the matrix's window) blanks them, each with
   input and change, so the unsaved count follows. */
(function () {
  var LIST = "matrices-list", HEAD = "method";
  var FACTOR_NOTE = "1.0 applies", NO_HOLDING = "No holding time", NOT_SET = "Not set";
  var AS_ALL = "As All matrices", MTX_AS_ALL = "Stored and received as All matrices", SET_HERE = " set here";
  var NO_REQ = "No requirement";
  var TEMP_COLS = ["store-sample", "store-processed", "store-extract", "receipt", "ice"];
  function isTemp(col) { return TEMP_COLS.indexOf(col) >= 0; }
  function list() { return document.getElementById(LIST); }
  function comps() { return window.PFAS && window.PFAS.components ? window.PFAS.components : null; }
  function pane() { return document.getElementById("pane-matrices"); }
  function grid() { var p = pane(); return p ? p.querySelector(".pfas-sheet-box") : null; }
  function byAttr(nodes, attr, v) {
    return Array.prototype.filter.call(nodes, function (n) { return n.getAttribute(attr) === v; });
  }
  function rowOf(key) {
    var b = grid();
    if (!b) { return null; }
    return key === HEAD ? byAttr(b.querySelectorAll("tr.pfas-sheet-grouprow"), "data-group", key)[0] || null
                        : byAttr(b.querySelectorAll("tr[data-row]"), "data-row", key)[0] || null;
  }
  function edit(key) {
    var c = comps(), b = grid();
    if (!c || !b) { return; }
    if (key === HEAD) { c.sheet.openGroup(b, key); } else { c.sheet.openRow(b, key); }
  }
  /* Remove from method: asked first, as the row's menu asks, when units
     hold the matrix (their names in its menu's confirm) */
  function remove(key) {
    var tr = rowOf(key), ask = "";
    try {
      (JSON.parse((tr && tr.getAttribute("data-row-actions")) || "[]") || []).forEach(function (a) {
        if (a.form === "matrices-remove" && a.confirm) { ask = a.confirm; }
      });
    } catch (e) { ask = ""; }
    if (ask && !window.confirm(ask)) { return; }
    window.PFAS.mpList.post("matrices-remove", "matrix", key);
  }
  /* the controls of a matrix's own temperatures in `root` (its grid row, or
     its window's form): the ends, the No requirement box, the on-ice value */
  function tempInputs(root) {
    var out = [];
    Array.prototype.forEach.call(root.querySelectorAll("[data-col]"), function (n) {
      if (!isTemp(n.getAttribute("data-col"))) { return; }
      out.push.apply(out, n.querySelectorAll("input[type=number], input[type=checkbox], input[data-tri]"));
    });
    return out;
  }
  function headIce() {
    var h = rowOf(HEAD), b = h ? h.querySelector('td[data-col="ice"] input[type=checkbox]') : null;
    return !!(b && b.checked);
  }
  /* Reset to All matrices: the matrix's own ranges, No requirement and on
     ice cleared; its switch shows All matrices' again. Each with input and
     change, so the unsaved count and a window's Done follow */
  function clearTemps(root) {
    tempInputs(root).forEach(function (n) {
      if (n.hasAttribute("data-tri-box")) {
        n.checked = headIce();
      } else if (n.type === "checkbox") {
        if (n.checked) { n.checked = false; window.PFAS.mpList.fire(n); }
      } else if (n.value) {
        n.value = ""; window.PFAS.mpList.fire(n);
      }
    });
  }
  function reset(key) {
    var tr = key === HEAD ? null : rowOf(key);
    if (tr) { clearTemps(tr); }
  }
  /* a matrix's on-ice switch: flipped, it writes the matrix's own value */
  document.addEventListener("change", function (e) {
    var b = e.target;
    if (!b || !b.hasAttribute || !b.hasAttribute("data-tri-box")) { return; }
    var own = b.closest("td, .pfas-sheet-field");
    var hid = own ? own.querySelector("input[data-tri]") : null;
    if (!hid) { return; }
    hid.value = b.checked ? "on" : "off";
    window.PFAS.mpList.fire(hid);
  });

  /* a node's menu, and a grid row's: Edit matrix, Reset to All matrices
     (Remove from method posts its own form through the shared row menu) */
  document.addEventListener("pfas:row-action", function (e) {
    var at = e.detail && e.detail.row, name = e.detail && e.detail.name;
    if (!at || (name !== "mtx-edit" && name !== "mtx-reset")) { return; }
    var key = at.getAttribute("data-mx-node") || at.getAttribute("data-row");
    var p = pane();
    if (!key || !p || !p.contains(at)) { return; }
    if (name === "mtx-reset") { reset(key); } else { edit(key); }
  });
  /* the button in the matrix's window: its copies blanked there, each
     marked changed, so Done writes them */
  document.addEventListener("click", function (e) {
    var b = e.target.closest ? e.target.closest("[data-mx-reset]") : null;
    var form = b && b.closest(".pfas-sheet-form");
    if (!form) { return; }
    clearTemps(form);
  });
  document.addEventListener("click", function (e) {
    var l = list(), b = e.target.closest ? e.target.closest("[data-mx-act], [data-mx-add]") : null;
    if (!b || !l || !l.contains(b)) { return; }
    if (b.hasAttribute("data-mx-add")) {
      window.PFAS.mpList.addFrom(b, b.getAttribute("data-mx-add"), "Sample Type", "Add a matrix");
      return;
    }
    var act = b.getAttribute("data-mx-act"), key = b.getAttribute("data-mx-of");
    if (act === "remove") { remove(key); } else { edit(key); }
  });

  function g(v) { var n = Number(v); return v !== "" && isFinite(n) ? String(n) : v; }
  function cells(tr, col) { return byAttr(tr.querySelectorAll("td[data-col]"), "data-col", col); }
  /* {words, ends, unset, note} for one grid cell, as profile_grids._cell_words
     reads it: null for a cell with no input (read-only: left as drawn) */
  function read(tr, col, unit) {
    var tds = cells(tr, col);
    if (!tds.length) { return null; }
    var ins = [];
    tds.forEach(function (td) { ins.push.apply(ins, td.querySelectorAll("input, select")); });
    var nums = ins.filter(function (i) { return i.type === "number"; });
    var box = ins.filter(function (i) { return i.type === "checkbox"; })[0];
    var sel = ins.filter(function (i) { return i.tagName === "SELECT"; })[0];
    var text = ins.filter(function (i) { return i.type === "text"; })[0];
    if (tds[0].hasAttribute("data-pair") && box && box.checked && isTemp(col)) {
      return { words: NO_REQ, ends: null, unset: false };
    }
    if (tds[0].hasAttribute("data-pair")) {
      var lo = g(String(nums[0] ? nums[0].value : "").trim()), hi = g(String(nums[1] ? nums[1].value : "").trim());
      if ((lo || hi) && tr.getAttribute("data-row") && isTemp(col)) {
        /* an end the matrix leaves blank reads All matrices' end */
        var parent = read(rowOf(HEAD), col, unit);
        if (parent && parent.ends) {
          lo = lo || String(parent.ends[0]);
          hi = hi || String(parent.ends[1]);
        }
      }
      if (!lo && !hi) {
        /* a matrix's own range left blank follows All matrices */
        return { words: tr.getAttribute("data-row") && isTemp(col) ? AS_ALL : NOT_SET, ends: null, unset: true };
      }
      return { words: ((lo || "—") + " – " + (hi || "—") + " " + (tds[0].getAttribute("data-unit") || "")).trim(),
               ends: lo && hi ? [Number(lo), Number(hi)] : null, unset: false };
    }
    if (col === "ice") {
      /* ✓ or ✗; a matrix's own value blank follows All matrices */
      var tri = tds[0].querySelector("input[data-tri]");
      if (tri) {
        if (tri.value !== "on" && tri.value !== "off") { return { words: AS_ALL, unset: true }; }
        return { words: tri.value === "on" ? "✓" : "✗", unset: false };
      }
      if (box) { return { words: box.checked ? "✓" : "✗", unset: false }; }
    }
    if (sel) {
      return sel.value ? { words: window.PFAS.mpList.shown(sel), unset: false } : { words: NOT_SET, unset: true };
    }
    if (text) {
      var v = String(text.value || "").split(",").map(function (x) { return x.trim(); }).filter(Boolean).join(", ");
      return v ? { words: v, unset: false } : { words: NOT_SET, unset: true };
    }
    if (nums.length) {
      if (box && box.checked) { return { words: "None", unset: false, note: NO_HOLDING }; }
      var n = g(String(nums[0].value || "").trim());
      if (!n) {
        var t = tds[0].getAttribute("title") || "";
        return t ? { words: t.charAt(0).toUpperCase() + t.slice(1), unset: false }
                 : { words: NOT_SET, unset: true, note: col === "factor" ? FACTOR_NOTE : "" };
      }
      return { words: unit === "days" ? n + (n === "1" ? " day" : " days") : n, unset: false };
    }
    if (box) { return { words: box.checked ? "✓" : "✗", unset: false }; }
    return null;
  }
  function setBand(b, ends) {
    if (!b) { return; }
    b.hidden = !ends;
    if (!ends) { return; }
    b.setAttribute("data-lo", String(ends[0]));
    b.setAttribute("data-hi", String(ends[1]));
    var c = comps();
    if (c) { c.hier.drawBand(b); }
  }
  function setNote(tile, note) {
    var s = tile.querySelector(".pfas-hier-tile-s");
    if (!note) { if (s) { s.parentNode.removeChild(s); } return; }
    if (!s) { s = window.PFAS.mpList.el("span", "pfas-hier-tile-s"); tile.appendChild(s); }
    s.textContent = note;
  }
  function redraw(card) {
    var key = card.getAttribute("data-mx-of"), tr = rowOf(key);
    if (!tr) { return; }
    var node = byAttr(list().querySelectorAll(".pfas-hier-node"), "data-mx-node", key)[0] || null;
    var own = [];
    Array.prototype.forEach.call(card.querySelectorAll("[data-mx-col]"), function (tile) {
      var col = tile.getAttribute("data-mx-col"), r = read(tr, col, col.indexOf("hold-") === 0 ? "days" : "");
      if (!r) { return; }
      if (isTemp(col) && !r.unset) { own.push(tile.getAttribute("data-mx-label") || col); }
      if (col === "nom" && !r.unset) {
        var u = read(tr, "nom-unit");
        if (u && !u.unset) { r.words += " " + u.words; }
      }
      tile.querySelector(".pfas-hier-tile-v").textContent = r.words;
      setBand(tile.querySelector("[data-mx-band]"), r.ends || null);
      setNote(tile, r.note || "");
      if (r.unset) { tile.setAttribute("data-mx-unset", "1"); } else { tile.removeAttribute("data-mx-unset"); }
      /* following All matrices: muted, as a value set to none */
      if (r.words === AS_ALL) { tile.classList.add("is-none"); } else { tile.classList.remove("is-none"); }
      var nv = node ? byAttr(node.querySelectorAll("[data-mx-value]"), "data-mx-value", col)[0] : null;
      if (nv) { nv.textContent = r.words; }
      if (nv && col === "receipt") { setBand(node.querySelector("[data-mx-band]"), r.ends || null); }
    });
    /* a matrix's caption: what it sets of its own temperatures, else that it follows */
    var cap = key === HEAD ? null : card.querySelector(".pfas-hier-card-cap");
    if (cap) {
      cap.textContent = (own.length ? own.join(", ") + SET_HERE : MTX_AS_ALL) + (cap.getAttribute("data-mx-tail") || "");
    }
  }
  function redrawAll() {
    var l = list();
    if (l) { Array.prototype.forEach.call(l.querySelectorAll("[data-hier-card][data-mx-of]"), redraw); }
  }
  ["input", "change"].forEach(function (t) {
    document.addEventListener(t, function (e) {
      var p = pane(), l = list();
      if (!p || !l || !e.target || !p.contains(e.target) || l.contains(e.target)) { return; }
      redrawAll();
    });
  });
  window.PFAS = window.PFAS || {};
  window.PFAS.matricesList = { redraw: redrawAll };
})();

/* The Analytes tab's List view (profile_grids.render_analytes_list):
   Regulated analytes, Other analytes, then the Method settings, each row
   beside its card, all mirroring the grid, the Table view, which holds every
   analyte input; of an analyte the list posts nothing. Edit and the row's
   menu open the grid row's own drawer (PFAS.components.sheet openRow), whose
   nameless copies write the row's inputs with input and change, so the
   unsaved count, the Quantified by warning and the grid follow; Open in
   Integration goes to Run & reporting, Integration. An edit anywhere in the
   grid is drawn again on the analyte's card and row: Quantified by and what
   it is, each matrix reported or left out (greyed, never hidden) with the RL
   that applies, its MDL and "Saves as" while Save rounds a stored value, the
   slots on the row, the isomer and salt values and the row flag. The Method settings card holds Surrogate
   recovery in a diluted sample itself (its segment writes its posted input);
   its row reads the choice. A search hit naming an analyte (?a=) opens its
   card. */
(function () {
  var LIST = "analytes-list", NOT_SET = "Not set";
  function list() { return document.getElementById(LIST); }
  function comps() { return window.PFAS && window.PFAS.components ? window.PFAS.components : null; }
  function pane() { return document.getElementById("pane-analytes"); }
  function grid() { var p = pane(); return p ? p.querySelector('.pfas-sheet-box[data-sheet="analytes"]') : null; }
  function byAttr(nodes, attr, v) {
    return Array.prototype.filter.call(nodes, function (n) { return n.getAttribute(attr) === v; });
  }
  function named(name) { return name ? document.getElementsByName(name)[0] || null : null; }
  function json(n, k, d) { try { return JSON.parse(n.getAttribute(k) || "null") || d; } catch (e) { return d; } }
  function card(key) { var l = list(); return l ? byAttr(l.querySelectorAll("[data-hier-card]"), "data-an-of", key)[0] || null : null; }
  function node(key) { var l = list(); return l ? byAttr(l.querySelectorAll(".pfas-hier-node"), "data-an-node", key)[0] || null : null; }
  function setText(n, text) { if (n && n.textContent !== text) { n.textContent = text; } }
  function setShown(n, text) { if (n) { setText(n, text); n.hidden = !text; } }

  function edit(key) {
    var c = comps(), b = grid();
    if (c && b) { c.sheet.openRow(b, key); }
  }
  /* its transitions' window, the focus back to its node on close */
  function integration(key) {
    var cd = card(key), b = cd ? cd.querySelector('[data-act="intg"]') : null, c = comps();
    if (!b) { return; }
    if (c && c.tiles) { c.tiles.press(b, node(key)); } else { b.click(); }
  }
  document.addEventListener("pfas:row-action", function (e) {
    var at = e.detail && e.detail.row, l = list();
    if (!at || !l || !l.contains(at)) { return; }
    var key = at.getAttribute("data-an-node");
    if (e.detail.name === "an-edit") { edit(key); } else if (e.detail.name === "an-intg") { integration(key); }
  });
  document.addEventListener("click", function (e) {
    var l = list(), b = e.target.closest ? e.target.closest("[data-an-act]") : null;
    if (!b || !l || !l.contains(b)) { return; }
    if (b.getAttribute("data-an-act") === "edit") { edit(b.getAttribute("data-an-of")); }
  });

  function unit(words, u) { return u ? words + " " + u : words; }
  /* one matrix tile, as profile_grids._an_matrix_tile draws it */
  function drawMatrix(tile, nd) {
    var box = named(tile.getAttribute("data-an-box")), rl = named(tile.getAttribute("data-an-rl-name"));
    var mdl = named(tile.getAttribute("data-an-mdl-name"));
    if (!box) { return; }
    var on = !!box.checked, u = tile.getAttribute("data-an-unit") || "", derived = tile.getAttribute("data-an-derived") || "";
    var typed = on && rl ? String(rl.value || "").trim() : "", words, note = "";
    if (!on) { words = "Left out"; note = "Left out of this matrix everywhere"; }
    else if (typed) { words = "RL " + unit(typed, u); }
    else if (derived) { words = "RL " + unit(derived, u); note = "From the lowest calibrator"; }
    else { words = "No RL"; }
    setText(tile.querySelector("[data-an-in]"), on ? "Reported" : "Left out");
    setText(tile.querySelector("[data-an-rl]"), words);
    setShown(tile.querySelector("[data-an-rl-note]"), note);
    var mv = mdl ? String(mdl.value || "").trim() : "", m = tile.querySelector("[data-an-mdl]");
    setText(m, mv ? "MDL " + unit(mv, u) : "MDL not set");
    if (m) { m.hidden = !on; }
    /* "Saves as" while the box holds the value Save rounds */
    [["rl", rl], ["mdl", mdl]].forEach(function (p) {
      var s = byAttr(tile.querySelectorAll("[data-an-saves]"), "data-an-saves", p[0])[0];
      if (!s || !s.getAttribute("data-an-saves-as")) { return; }
      s.hidden = !(on && p[1] && p[1].hasAttribute("data-saves-as") && p[1].value === p[1].defaultValue);
    });
    tile.classList.toggle("is-muted", !on);
    var slot = nd ? byAttr(nd.querySelectorAll("[data-an-slot]"), "data-an-slot", tile.getAttribute("data-an-col"))[0] : null;
    if (slot) { slot.classList.toggle("is-out", !on); }
    return on ? null : tile.querySelector(".pfas-hier-tile-l").textContent.split(" · ")[0];
  }
  /* a value tile (data-an-name): a choice's shown option, else as typed */
  function drawValue(tile) {
    var input = named(tile.getAttribute("data-an-name"));
    if (!input) { return; }
    var v = input.tagName === "SELECT" ? (input.value ? window.PFAS.mpList.shown(input) : "") : String(input.value || "").trim();
    setText(tile.querySelector(".pfas-hier-tile-v"), v || NOT_SET);
    if (v) { tile.removeAttribute("data-an-unset"); } else { tile.setAttribute("data-an-unset", "1"); }
  }
  function redraw(key) {
    var cd = card(key), nd = node(key), l = list();
    if (!cd || !l) { return; }
    var qt = cd.querySelector("[data-an-quant-tile]"), sel = qt ? named(qt.getAttribute("data-an-name")) : null;
    if (sel) {
      var v = String(sel.value || ""), words = v ? window.PFAS.mpList.shown(sel) : "";
      var notes = json(l, "data-an-quant-notes", {});
      setText(qt.querySelector("[data-an-quant]"), words || NOT_SET);
      setShown(qt.querySelector("[data-an-quant-note]"), v && notes[v] ? notes[v] : "");
      setText(cd.querySelector("[data-an-flag-v]"), v ? "None" : "No Quantified by");
      if (nd) {
        setText(nd.querySelector("[data-an-quant]"), words);
        var tag = nd.querySelector("[data-an-tag]");
        if (tag) { tag.hidden = !!v; }
      }
    }
    var out = [];
    Array.prototype.forEach.call(cd.querySelectorAll("[data-an-col]"), function (t) {
      var left = drawMatrix(t, nd);
      if (left) { out.push(left); }
    });
    if (nd) { setText(nd.querySelector("[data-an-slots-words]"), out.length ? "Left out of " + out.join(", ") : "Reported in every matrix"); }
    Array.prototype.forEach.call(cd.querySelectorAll("[data-an-label][data-an-name]"), drawValue);
  }
  function redrawAll() {
    var l = list();
    if (!l) { return; }
    Array.prototype.forEach.call(l.querySelectorAll("[data-hier-card][data-an-of]"), function (cd) {
      if (cd.querySelector("[data-an-quant-tile]")) { redraw(cd.getAttribute("data-an-of")); }
    });
  }
  /* the Method settings row reads the choice its card's segment writes */
  function drawSetting() {
    var l = list(), v = l ? l.querySelector("[data-an-dilrec]") : null;
    if (!v) { return; }
    var input = named(v.getAttribute("data-an-dilrec")), words = json(v, "data-an-words", {});
    setText(v, input && input.value && words[input.value] ? words[input.value] : NOT_SET);
  }
  ["input", "change"].forEach(function (t) {
    document.addEventListener(t, function (e) {
      var p = pane(), l = list(), at = e.target;
      if (!p || !l || !at || !p.contains(at)) { return; }
      if (l.contains(at)) { drawSetting(); return; }
      var tr = at.closest ? at.closest("tr[data-row]") : null, b = grid();
      if (tr && b && b.contains(tr)) { redraw(tr.getAttribute("data-row")); } else { redrawAll(); }
    });
  });
  /* a search hit naming an analyte opens its card */
  document.addEventListener("DOMContentLoaded", function () {
    var m = /[?&]a=([^&#]+)/.exec(window.location.search || ""), l = list(), c = comps();
    if (!m || !l || !c || !c.hier) { return; }
    var key = decodeURIComponent(m[1].replace(/\+/g, " ")), nd = node(key);
    if (!nd) { return; }
    c.hier.select(l.querySelector(".pfas-hier"), key, true);
    if (nd.scrollIntoView) { nd.scrollIntoView({ block: "nearest" }); }
  });
  window.PFAS = window.PFAS || {};
  window.PFAS.analytesList = { redraw: redrawAll, redrawOne: redraw };
})();

/* Certificate format's List view (profile_grids.render_report_format_list):
   All matrices, the parent whose settings every matrix follows, then each
   matrix's card showing only what it sets for itself, each beside what All
   matrices holds; the rest named once as following All matrices. The table,
   the Table view, holds every posted input; the list posts nothing. Edit
   opens the shared drawer on nameless copies of the row's inputs, a matrix's
   blank reading "As All matrices", and Done writes the changed ones back
   with input and change; Reset to All matrices clears what the matrix sets.
   A change in the table is drawn again in the cards and nodes. */
(function () {
  var LIST = "report-format-list", ALL = "rf-all", FOLLOWS = "Follows All matrices", AS_ALL = "As All matrices";
  function list() { return document.getElementById(LIST); }
  function comps() { return window.PFAS && window.PFAS.components ? window.PFAS.components : null; }
  function byAttr(nodes, attr, v) {
    return Array.prototype.filter.call(nodes, function (n) { return n.getAttribute(attr) === v; });
  }
  function card(key) { var l = list(); return l ? byAttr(l.querySelectorAll("[data-hier-card]"), "data-rf-of", key)[0] || null : null; }
  function names(c) { try { return JSON.parse(c.getAttribute("data-rf-names") || "[]"); } catch (e) { return []; } }
  function input(name) {
    return Array.prototype.filter.call(document.querySelectorAll('[form="section-run"][name]'), function (n) {
      return n.name === name;
    })[0] || null;
  }
  function label(tile, nm) { return tile ? tile.querySelector(".pfas-hier-tile-l").textContent : nm; }
  /* what a cell reads: a choice's shown option, a text as typed; on All
     matrices a blank text reads its built-in default (its placeholder) */
  function words(n, parent) {
    if (n.tagName === "SELECT") { return n.value || parent ? window.PFAS.mpList.shown(n) : ""; }
    return n.value || (parent ? (n.getAttribute("placeholder") || "—") : "");
  }
  function redraw() {
    var l = list(), top = card(ALL);
    if (!l || !top) { return; }
    var parent = {};
    names(top).forEach(function (nm) {
      var n = input(nm), tile = byAttr(top.querySelectorAll("[data-rf-name]"), "data-rf-name", nm)[0];
      if (!n || !tile) { return; }
      parent[label(tile, nm)] = words(n, true);
      tile.querySelector(".pfas-hier-tile-v").textContent = words(n, true);
    });
    Array.prototype.forEach.call(l.querySelectorAll("[data-hier-card]"), function (c) {
      var key = c.getAttribute("data-rf-of");
      if (key === ALL) { return; }
      var follows = [], own = 0;
      names(c).forEach(function (nm) {
        var n = input(nm), tile = byAttr(c.querySelectorAll("[data-rf-name]"), "data-rf-name", nm)[0];
        if (!n || !tile) { return; }
        var said = label(tile, nm), set = !!n.value;
        tile.hidden = !set;
        tile.querySelector(".pfas-hier-tile-v").textContent = set ? words(n, false) : "";
        var s = tile.querySelector(".pfas-hier-tile-s");
        if (s) { s.textContent = "All matrices: " + (parent[said] || ""); }
        if (set) { own += 1; } else { follows.push(said); }
      });
      var f = c.querySelector("[data-rf-follows]");
      if (f) { f.hidden = !follows.length; f.querySelector(".pfas-hier-tile-v").textContent = follows.join(", "); }
      var value = own ? own + " set here" : FOLLOWS;
      var cap = c.querySelector("[data-rf-value]");
      if (cap) { cap.textContent = value; }
      var node = byAttr(l.querySelectorAll(".pfas-hier-node"), "data-rf-node", key)[0];
      var nv = node ? node.querySelector("[data-rf-value]") : null;
      if (nv) { nv.textContent = value; }
    });
  }
  /* Edit: the shared copy editor (PFAS.mpList.editCopies), a matrix's blank
     reading "As All matrices" */
  function edit(key, opener) {
    var cd = card(key);
    if (!cd || !comps()) { return; }
    var parent = key === ALL, items = [];
    names(cd).forEach(function (nm) {
      var real = input(nm), tile = byAttr(cd.querySelectorAll("[data-rf-name]"), "data-rf-name", nm)[0];
      if (real) { items.push({ real: real, label: label(tile, nm), blank: parent ? null : AS_ALL }); }
    });
    var title = cd.querySelector(".pfas-hier-card-t");
    window.PFAS.mpList.editCopies(title ? title.textContent : "Certificate format", items, { opener: opener || null });
  }
  function reset(key) {
    var cd = card(key);
    if (!cd || key === ALL) { return; }
    window.PFAS.mpList.clear(names(cd).map(input));
  }
  document.addEventListener("pfas:row-action", function (e) {
    var node = e.detail && e.detail.row, l = list();
    if (!node || !l || !l.contains(node)) { return; }
    var key = node.getAttribute("data-rf-node");
    if (e.detail.name === "rf-edit") { edit(key, node); } else if (e.detail.name === "rf-reset") { reset(key); }
  });
  document.addEventListener("click", function (e) {
    var l = list(), b = e.target.closest ? e.target.closest("[data-rf-act]") : null;
    if (!b || !l || !l.contains(b)) { return; }
    var key = b.getAttribute("data-rf-of");
    if (b.getAttribute("data-rf-act") === "reset") { reset(key); } else { edit(key, b); }
  });
  ["input", "change"].forEach(function (t) {
    document.addEventListener(t, function (e) {
      var l = list(), n = e.target;
      if (!l || !n || !n.getAttribute || l.contains(n) || n.getAttribute("form") !== "section-run" ||
          String(n.getAttribute("name") || "").indexOf("t__rf__") !== 0) { return; }
      redraw();
    });
  });
  window.PFAS = window.PFAS || {};
  window.PFAS.reportFormatList = { redraw: redraw };
})();

/* Integration's List view (profile_grids.render_integration_list): the
   method defaults, the parent every compound follows, then each compound
   that sets its own, its card showing only what it sets, each beside the
   method's value, the rest named once as following the method; then every
   compound's transitions and windows, its own with no parent, a row each. The form and
   the table, the Table view, hold every posted input; the list posts
   nothing. Edit opens the shared copy editor (PFAS.mpList.editCopies) on the
   card's controls, a compound's blank reading the method's value; Reset to
   method defaults clears what the compound sets (never its transitions,
   which have no parent); + Override a compound chooses a compound that
   follows the method and opens its Edit; a transitions row, or a fold,
   opens its compounds' transitions, Done writing each change to every
   compound it stands for. A change in the form or the table is drawn again. */
(function () {
  var LIST = "integration-list", TRANS = "integration-transitions", METHOD = "intg-method";
  var FOLLOWS = "Follows method defaults", DEFAULT = "Default", NOT_SET = "Not set", DASH = "—";
  var NUM = /^-?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/;
  function list() { return document.getElementById(LIST); }
  function comps() { return window.PFAS && window.PFAS.components ? window.PFAS.components : null; }
  function mk(tag, cls, text) { return window.PFAS.mpList.el(tag, cls, text); }
  function json(n, k, d) { try { return JSON.parse(n.getAttribute(k) || "null") || d; } catch (e) { return d; } }
  function byAttr(nodes, attr, v) {
    return Array.prototype.filter.call(nodes, function (n) { return n.getAttribute(attr) === v; });
  }
  /* the tab's posted fields by name; a redraw reads them once */
  var byName = null;
  function input(name) {
    if (byName) { return byName[name] || null; }
    return Array.prototype.filter.call(document.getElementsByName(name), function (n) {
      return n.getAttribute("form") === "section-run";
    })[0] || null;
  }
  function reading(fn) {
    byName = {};
    Array.prototype.forEach.call(document.querySelectorAll('[form="section-run"][name]'), function (n) {
      if (!(n.name in byName)) { byName[n.name] = n; }
    });
    try { return fn(); } finally { byName = null; }
  }
  /* a setting as it reads (profile_grids._intg_words) */
  function words(kind, value, choices, unit) {
    var v = String(value === undefined || value === null ? "" : value).trim();
    if (!v) { return ""; }
    if (kind === "choice") {
      var hit = (choices || []).filter(function (c) { return c[0] === v; })[0];
      return hit ? hit[1] : v;
    }
    return unit && NUM.test(v) ? v + " " + unit : v;
  }
  function index(key) { return Number(String(key).slice(5)); }
  /* a compound row's input names, in the table's column order */
  function namesOf(l, i) {
    var prefix = json(l, "data-intg-prefix", []), suffix = json(l, "data-intg-suffix", []);
    if (prefix[i]) { return suffix.map(function (s) { return prefix[i] + s; }); }
    return json(l, "data-intg-whole", {})["intg-" + i] || [];
  }
  function card(key) { var l = list(); return l ? byAttr(l.querySelectorAll("[data-hier-card]"), "data-intg-of", key)[0] || null : null; }
  function node(key) { var l = list(); return l ? byAttr(l.querySelectorAll(".pfas-hier-node"), "data-intg-node", key)[0] || null : null; }
  function tile(label, value, note, attrs) {
    var t = mk("div", "pfas-hier-tile");
    (attrs || []).forEach(function (a) { t.setAttribute(a[0], a[1]); });
    t.appendChild(mk("span", "pfas-hier-tile-l", label));
    t.appendChild(mk("span", "pfas-hier-tile-v", value));
    if (note) { t.appendChild(mk("span", "pfas-hier-tile-s", note)); }
    return t;
  }
  function setNote(t, note) {
    var s = t.querySelector(".pfas-hier-tile-s");
    if (!note) { if (s) { s.parentNode.removeChild(s); } return; }
    if (!s) { s = mk("span", "pfas-hier-tile-s"); t.appendChild(s); }
    s.textContent = note;
  }
  /* the method defaults: each tile from its field, a blank as what it
     resolves to; {field name: what it reads} */
  function drawMethod() {
    var out = {}, cd = card(METHOD);
    if (!cd) { return out; }
    Array.prototype.forEach.call(cd.querySelectorAll("[data-intg-name]"), function (t) {
      var real = input(t.getAttribute("data-intg-name"));
      if (!real) { return; }
      var kind = t.getAttribute("data-intg-kind"), unit = t.getAttribute("data-intg-unit") || "";
      /* a value whose unit is its switch's (the retention time tolerance) */
      var from = t.getAttribute("data-intg-unit-from");
      if (from) { var sw = input(from), uw = json(t, "data-intg-unit-words", {}); unit = uw[sw ? sw.value : ""] || uw[""] || unit; }
      var choices = json(t, "data-intg-choices", []);
      var own = words(kind, real.value, choices, unit), said = words(kind, t.getAttribute("data-intg-resolved"), choices, unit);
      var w = own || said || NOT_SET;
      t.querySelector(".pfas-hier-tile-v").textContent = w;
      setNote(t, !own && said ? DEFAULT : "");
      out[t.getAttribute("data-intg-name")] = w;
    });
    return out;
  }
  function drawCompound(l, cd, parent) {
    var key = cd.getAttribute("data-intg-of"), names = namesOf(l, index(key)), at = json(l, "data-intg-at", [[], []]);
    var cols = json(l, "data-intg-cols", []), box = cd.querySelector("[data-intg-tiles]");
    var method = json(box, "data-intg-method", []), set = [], follows = [];
    at[0].forEach(function (j, k) {
      var real = input(names[j]), col = cols[k] || [];
      var w = real ? words(col[1], real.value, col[4], col[2]) : "";
      if (w) { set.push(tile(col[0], w, "Method: " + (col[3] ? (parent[col[3]] || NOT_SET) : method[k]))); }
      else { follows.push(col[0]); }
    });
    box.textContent = "";
    if (set.length) {
      set.forEach(function (t) { box.appendChild(t); });
      /* as the server draws it: a click goes to the method defaults */
      if (follows.length) {
        box.appendChild(tile(FOLLOWS, follows.join(", "), "", [["data-intg-follows", "data-intg-follows"], ["data-tile-open", "all"],
                                                               ["data-tile-menu", '["all", "edit", "reset"]']]));
      }
    }
    var value = set.length ? set.length + " set here" : FOLLOWS;
    cd.querySelector("[data-intg-value]").textContent = value;
    var n = node(key);
    if (n) {
      n.querySelector("[data-intg-value]").textContent = value;
      n.hidden = !set.length;
      var dots = byAttr(l.querySelectorAll(".pfas-hier-dots"), "data-intg-node", key)[0];
      if (dots) { dots.hidden = !set.length; }
    }
    return set.length > 0;
  }
  function drawTransitions(l) {
    var t = document.getElementById(TRANS);
    if (!t) { return; }
    var own = json(l, "data-intg-at", [[], []])[1], labels = json(t, "data-intg-labels", []);
    var right = json(t, "data-intg-right", []), rows = [];
    labels.forEach(function (label, i) {
      var names = namesOf(l, i);
      var w = own.map(function (j) {
        var real = input(names[j]);
        if (!real) { return DASH; }
        if (real.tagName === "SELECT") { return real.value ? window.PFAS.mpList.shown(real) : DASH; }
        return String(real.value || "").trim() || DASH;
      });
      rows.push({ key: "intg-" + i, label: label, words: w });
    });
    var body = t.querySelector("tbody"), first = body.querySelector("tr[data-row-actions]");
    var menu = first ? first.getAttribute("data-row-actions") : null;
    function said(keys, w) { return JSON.stringify(keys) + "#" + JSON.stringify(w); }
    var drawn = Array.prototype.map.call(body.querySelectorAll("tr"), function (tr) {
      /* the touch screen's ⋯ cell the row menu adds is no value */
      var tds = Array.prototype.filter.call(tr.querySelectorAll("td"), function (td) { return !td.classList.contains("row-plus-cell"); });
      return said(json(tr, "data-intg-keys", []), tds.slice(1).map(function (td) { return td.textContent; }));
    }).join("\n");
    var want = rows.map(function (r) { return said([r.key], r.words); }).join("\n");
    if (drawn === want) { return; }
    function tr(keys, head, w) {
      var r = mk("tr");
      r.setAttribute("tabindex", "0");
      r.setAttribute("data-intg-keys", JSON.stringify(keys));
      if (menu) { r.setAttribute("data-row-actions", menu); }
      r.appendChild(head);
      w.forEach(function (x, i) { r.appendChild(mk("td", right[i] ? "is-num" : "", x)); });
      return r;
    }
    body.textContent = "";
    rows.forEach(function (r) { body.appendChild(tr([r.key], mk("td", "", r.label), r.words)); });
    var c = comps();
    if (c && c.rows) { c.rows.init(body); }
  }
  function redraw() { reading(drawAll); }
  function drawAll() {
    var l = list();
    if (!l) { return; }
    var parent = drawMethod(), following = 0;
    Array.prototype.forEach.call(l.querySelectorAll("[data-hier-card]"), function (cd) {
      if (cd.getAttribute("data-intg-of") === METHOD) { return; }
      if (!drawCompound(l, cd, parent)) { following += 1; }
    });
    var add = l.querySelector("[data-intg-add]");
    if (add) { add.hidden = !following; }
    /* a compound no longer set apart: its card gives way to the method's */
    var hier = l.querySelector(".pfas-hier"), on = hier ? hier.querySelector('.pfas-hier-node[aria-pressed="true"]') : null;
    var c = comps();
    if (on && on.hidden && c) { c.hier.select(hier, METHOD, true); }
    drawTransitions(l);
  }

  function editMethod(opener) {
    var cd = card(METHOD);
    if (!cd) { return; }
    var items = [];
    json(cd, "data-intg-names", []).forEach(function (nm) {
      var real = input(nm), t = byAttr(cd.querySelectorAll("[data-intg-name]"), "data-intg-name", nm)[0];
      if (!real || !t) { return; }
      var when = t.getAttribute("data-show-if");
      items.push({ real: real, label: t.querySelector(".pfas-hier-tile-l").textContent,
                   unit: t.hasAttribute("data-intg-unit-from") ? undefined : (t.getAttribute("data-intg-unit") || undefined),
                   when: when ? [when, (t.getAttribute("data-show-values") || t.getAttribute("data-show-value") || "").split(" ")] : null });
    });
    window.PFAS.mpList.editCopies("Method defaults", items, { opener: opener || null });
  }
  function editCompound(key, opener) {
    var l = list(), cd = card(key);
    if (!l || !cd) { return; }
    var names = namesOf(l, index(key)), at = json(l, "data-intg-at", [[], []]), cols = json(l, "data-intg-cols", []);
    var parent = drawMethod(), method = json(cd.querySelector("[data-intg-tiles]"), "data-intg-method", []), items = [];
    at[0].forEach(function (j, k) {
      var real = input(names[j]), col = cols[k] || [];
      if (real) {
        items.push({ real: real, label: col[0], unit: col[2] || undefined,
                     blank: "Method: " + (col[3] ? (parent[col[3]] || NOT_SET) : method[k]) });
      }
    });
    window.PFAS.mpList.editCopies(cd.querySelector(".pfas-hier-card-t").textContent, items, {
      opener: opener || null,
      done: function () {
        /* drawn at once, so a compound now set apart is chosen */
        redraw();
        var hier = l.querySelector(".pfas-hier"), n = node(key), c = comps();
        if (hier && n && !n.hidden && c) { c.hier.select(hier, key, true); }
      }
    });
  }
  function reset(key) {
    var l = list();
    if (!l || key === METHOD) { return; }
    var names = namesOf(l, index(key));
    window.PFAS.mpList.clear(json(l, "data-intg-at", [[], []])[0].map(function (j) { return input(names[j]); }));
  }
  function editTransitions(keys, opener) {
    var l = list(), t = document.getElementById(TRANS);
    if (!l || !t || !keys.length) { return; }
    var own = json(l, "data-intg-at", [[], []])[1], labels = json(t, "data-intg-labels", []);
    var heads = Array.prototype.slice.call(t.querySelectorAll("thead th"), 1).map(function (th) {
      return th.firstChild ? String(th.firstChild.textContent).trim() : th.textContent;
    });
    var each = keys.map(function (k) { return namesOf(l, index(k)); }), items = [];
    own.forEach(function (j, i) {
      var real = input(each[0][j]);
      if (!real) { return; }
      items.push({ real: real, label: heads[i] || "",
                   also: each.slice(1).map(function (ns) { return input(ns[j]); }).filter(Boolean) });
    });
    var title = keys.length === 1 ? labels[index(keys[0])] : keys.length + " compounds";
    window.PFAS.mpList.editCopies(title, items, { opener: opener || null });
  }
  function addCompound(btn) {
    var l = list(), c = comps();
    if (!l || !c) { return; }
    var pick = mk("select");
    pick.setAttribute("aria-label", "Compound");
    Array.prototype.forEach.call(l.querySelectorAll(".pfas-hier-node[data-intg-node]"), function (n) {
      var key = n.getAttribute("data-intg-node");
      if (key === METHOD || !n.hidden) { return; }
      var o = mk("option", "", n.querySelector(".pfas-hier-node-t").textContent);
      o.value = key;
      pick.appendChild(o);
    });
    var row = mk("label", "pfas-pop-row");
    row.appendChild(mk("span", "pfas-pop-l", "Compound"));
    row.appendChild(pick);
    var body = mk("div");
    body.appendChild(row);
    var foot = mk("div", "pfas-drawer-actions"), go = mk("button", "btn btn-primary", "Choose");
    go.type = "button";
    go.addEventListener("click", function () { if (pick.value) { editCompound(pick.value, btn); } });
    foot.appendChild(go);
    c.drawer.open("Override a compound", body, { footer: foot, cls: "is-dialog", opener: btn, focus: pick });
  }
  /* each reads the tab's fields once */
  function once(fn) { return function () { var a = arguments; return reading(function () { return fn.apply(null, a); }); }; }
  editMethod = once(editMethod);
  editCompound = once(editCompound);
  reset = once(reset);
  editTransitions = once(editTransitions);

  document.addEventListener("click", function (e) {
    var l = list(), b = e.target.closest ? e.target.closest("[data-intg-act], [data-intg-add]") : null;
    if (b && l && l.contains(b)) {
      if (b.hasAttribute("data-intg-add")) { addCompound(b); return; }
      var key = b.getAttribute("data-intg-of");
      if (b.getAttribute("data-intg-act") === "reset") { reset(key); }
      else if (key === METHOD) { editMethod(b); } else { editCompound(key, b); }
      return;
    }
    /* a transitions row, or a fold, opens its compounds' transitions */
    var t = document.getElementById(TRANS), tr = e.target.closest ? e.target.closest("tr[data-intg-keys]") : null;
    if (!tr || !t || !t.contains(tr) || e.target.closest(".pfas-rowmenu, td.row-plus-cell")) { return; }
    editTransitions(json(tr, "data-intg-keys", []), tr);
  });
  document.addEventListener("keydown", function (e) {
    var t = document.getElementById(TRANS), tr = e.target;
    if (e.key !== "Enter" || !t || !tr || !tr.matches || !tr.matches("tr[data-intg-keys]") || !t.contains(tr)) { return; }
    e.preventDefault();
    editTransitions(json(tr, "data-intg-keys", []), tr);
  });
  document.addEventListener("pfas:row-action", function (e) {
    var at = e.detail && e.detail.row, l = list();
    if (!at || !l || !l.contains(at)) { return; }
    var name = e.detail.name;
    if (name === "intg-edit") { editCompound(at.getAttribute("data-intg-node"), at); }
    else if (name === "intg-reset") { reset(at.getAttribute("data-intg-node")); }
    else if (name === "intg-trans-edit") { editTransitions(json(at, "data-intg-keys", []), at); }
  });
  var due = null;
  ["input", "change"].forEach(function (type) {
    document.addEventListener(type, function (e) {
      var l = list(), n = e.target;
      if (!l || !n || !n.getAttribute || l.contains(n) || n.getAttribute("form") !== "section-run") { return; }
      var name = String(n.getAttribute("name") || "");
      if (name.indexOf("f__") !== 0 && name.indexOf("t__intg_5fan__") !== 0) { return; }
      /* an edit writes several fields at once: draw once after them */
      if (due) { return; }
      due = setTimeout(function () { due = null; redraw(); }, 0);
    });
  });
  window.PFAS = window.PFAS || {};
  window.PFAS.integrationList = { redraw: redraw };
})();

/* Each rule card's Flag tile (profile_grids.render_flag_tile): its Code
   with the QC Qualifiers wording, Attaches to and Internal note, read from
   the flags table's posted inputs by name (data-flag-names, in the form
   data-flag-form), so an edit in the Table view redraws it. A click on the
   tile's Attaches to or Internal note (its Edit flag trigger) opens the
   centred window (the shared drawer as a dialog) on copies of the three:
   Code a list of the QC Qualifiers entries that carry a code (the page's
   #pfas-flag-choices), its wording read only beside Open QC Qualifiers;
   Attaches to a segment greyed while there is no code; the note. Save
   writes each changed input with input and change, so the tab's unsaved
   count follows and the tab's Save stores it; Cancel writes nothing. Bound
   by the tile's own attributes, wherever a card places it. */
(function () {
  var CHOICES = null;
  function comps() { return window.PFAS && window.PFAS.components ? window.PFAS.components : null; }
  function choices() {
    if (CHOICES) { return CHOICES; }
    var n = document.getElementById("pfas-flag-choices");
    try { CHOICES = JSON.parse(n ? n.textContent : "{}") || {}; } catch (e) { CHOICES = {}; }
    CHOICES.codes = CHOICES.codes || [];
    CHOICES.places = CHOICES.places || [];
    CHOICES.words = CHOICES.words || {};
    return CHOICES;
  }
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
  function inputs(tile) {
    var names = {}, form = tile.getAttribute("data-flag-form"), out = {};
    try { names = JSON.parse(tile.getAttribute("data-flag-names") || "{}") || {}; } catch (e) { names = {}; }
    ["code", "attach", "output", "note"].forEach(function (k) {
      out[k] = Array.prototype.filter.call(document.getElementsByName(names[k] || ""), function (n) {
        return n.getAttribute("form") === form;
      })[0] || null;
    });
    return out;
  }
  function entry(key) { return choices().codes.filter(function (c) { return c[0] === key; })[0] || null; }
  function place(key) {
    var all = choices().places;
    return all.filter(function (p) { return p[0] === key; })[0] || all[0] || ["result", "Result", ""];
  }
  /* where a code is issued: [value, words] ("" = the certificate and the EDD) */
  function output(key) {
    var all = choices().outputs || [["", "Certificate and EDD"]];
    return all.filter(function (o) { return o[0] === key; })[0] || all[0];
  }
  function kinded(tile) { return !!tile.querySelector('[data-flag-part="kind"][data-flag-kind]'); }
  function setPart(tile, part, value, note, muted) {
    var t = tile.querySelector('[data-flag-part="' + part + '"]');
    if (!t) { return; }
    var v = t.querySelector(".pfas-hier-tile-v"), s = t.querySelector(".pfas-hier-tile-s");
    if (v) { v.textContent = value; }
    if (s) { s.textContent = note || ""; } else if (note) { t.appendChild(el("span", "pfas-hier-tile-s", note)); }
    t.classList.toggle("is-none", !!muted);
  }
  /* what a code key reads: [letter, wording] ("" for none) */
  function words(key) {
    var e = key ? entry(key) : null, w = choices().words;
    if (!key) { return ["", w.code_help || ""]; }
    return e ? [e[1], e[3] || w.code_help || ""] : ["", w.no_letter || ""];
  }
  function redraw(tile) {
    var r = inputs(tile), w = choices().words;
    if (!r.code || !r.attach || !r.note) { return; }
    var said = words(String(r.code.value || "")), pl = place(String(r.attach.value || "result"));
    /* a rule that raises a kind: its kind's code attaches at the place too */
    var placed = !!said[0] || kinded(tile);
    setPart(tile, "code", said[0] || w.no_code || "", said[1]);
    setPart(tile, "attach", placed ? pl[1] : (w.nothing || ""), placed ? pl[2] : "", !placed);
    if (r.output) { setPart(tile, "output", output(String(r.output.value || ""))[1], ""); }
    /* a note the group card writes once stays pointed there */
    var shared = tile.querySelector('[data-flag-part="note"][data-flag-shared]');
    var text = String(r.note.value || "").trim();
    if (shared && text) { return; }
    /* the Low-level recoveries note names each tier's N as {0:g} */
    if (tile.hasAttribute("data-flag-note-help")) { text = text.replace(/\{0(?::[^}]*)?\}/g, "N"); }
    setPart(tile, "note", text || w.no_note || "", w.note_help || "");
  }
  function tiles() { return document.querySelectorAll("[data-flag-tile]"); }
  ["input", "change"].forEach(function (t) {
    document.addEventListener(t, function (e) {
      var form = e.target && e.target.getAttribute ? e.target.getAttribute("form") : null;
      if (!form) { return; }
      Array.prototype.forEach.call(tiles(), function (tile) {
        if (tile.getAttribute("data-flag-form") === form) { redraw(tile); }
      });
    });
  });
  function field(label, control, help) {
    var f = el("div", "pfas-sheet-field");
    f.appendChild(el("div", "pfas-sheet-flabel", label));
    f.appendChild(control);
    if (help) { f.appendChild(help); }
    return f;
  }
  function open(tile, opener) {
    var c = comps(), r = inputs(tile), all = choices(), w = all.words;
    if (!c || !c.drawer) { return; }
    var title = tile.getAttribute("data-flag-title") || "Flag";
    if (!r.code || !r.attach || !r.note) {
      /* a tier added on this page has no flag row until the tab is saved */
      c.drawer.open(title, el("p", "pfas-hier-note", w.unsaved || "Save the tab first: this flag can be set once it is saved."),
                    { cls: "is-dialog", opener: opener });
      return;
    }
    var body = el("div", "pfas-sheet-form pfas-flag-form");
    /* Code: every entry that carries a code, code first, then its failure */
    var sel = el("select", "rl-in");
    sel.setAttribute("aria-label", "Code");
    var none = el("option", null, w.no_code || "");
    none.value = "";
    sel.appendChild(none);
    all.codes.forEach(function (cd) {
      var o = el("option", null, cd[1] + " · " + cd[2]);
      o.value = cd[0];
      sel.appendChild(o);
    });
    if (r.code.value && !entry(r.code.value)) {
      var kept = el("option", null, r.code.value);
      kept.value = r.code.value;
      sel.appendChild(kept);
    }
    sel.value = r.code.value || "";
    body.appendChild(field("Code", sel, el("p", "pfas-hier-note", "From QC Qualifiers. Pick " + (w.no_code || "No code") +
                                           " for a rule that prints nothing.")));
    /* the wording, read only: the QAO edits it in QC Qualifiers */
    var wording = el("p", "pfas-flag-wording");
    var lib = el("a", "btn btn-sm btn-secondary", "Go to QC Qualifiers");
    lib.href = all.library || "@@pfas-qc-qualifiers";
    var wbox = el("div", "pfas-flag-wbox");
    wbox.appendChild(wording);
    wbox.appendChild(lib);
    body.appendChild(field("Wording", wbox, el("p", "pfas-hier-note", "Read only: the QAO edits wording in QC Qualifiers.")));
    /* Attaches to: a segment, greyed while there is no code */
    var seg = el("div", "pfas-seg pfas-seg-sm is-fit");
    seg.setAttribute("role", "group");
    seg.setAttribute("aria-label", "Attaches to");
    var start = String(r.attach.value || "result");
    all.places.forEach(function (p) {
      var b = el("button", "pfas-seg-item", p[1]);
      b.type = "button";
      b.setAttribute("data-value", p[0]);
      b.setAttribute("aria-pressed", p[0] === start ? "true" : "false");
      seg.appendChild(b);
    });
    var placeHelp = el("p", "pfas-hier-note");
    var attachField = field("Attaches to", seg, placeHelp);
    body.appendChild(attachField);
    /* Output: where the code is issued */
    var out = el("select", "rl-in");
    out.setAttribute("aria-label", "Output");
    (all.outputs || [["", "Certificate and EDD"]]).forEach(function (o) {
      var opt = el("option", null, o[1]);
      opt.value = o[0];
      out.appendChild(opt);
    });
    out.value = r.output ? String(r.output.value || "") : "";
    if (r.output) { body.appendChild(field("Output", out, null)); }
    var note = el("textarea", "rl-in");
    note.rows = 3;
    note.value = r.note.value || "";
    note.setAttribute("aria-label", "Internal note");
    body.appendChild(field("Internal note", note, el("p", "pfas-hier-note",
      [w.note_help || "", tile.getAttribute("data-flag-note-help") || ""].filter(function (x) { return x; }).join(" "))));
    var joins = el("p", "pfas-hier-note");
    body.appendChild(joins);
    function chosen() {
      var p = seg.querySelector('.pfas-seg-item[aria-pressed="true"]');
      return p ? p.getAttribute("data-value") : start;
    }
    function follow() {
      var said = words(sel.value);
      wording.textContent = said[0] ? said[1] : (sel.value ? said[1] : "");
      wbox.hidden = !said[0];
      var off = !said[0] && !kinded(tile);
      attachField.classList.toggle("is-muted", off);
      Array.prototype.forEach.call(seg.querySelectorAll("button"), function (b) { b.disabled = off; });
      placeHelp.textContent = off ? (w.nothing || "") : place(chosen())[2];
      joins.textContent = said[0] ? String(w.joins || "").replace("{0}", said[0]) : "";
    }
    seg.addEventListener("click", function (e) {
      var b = e.target.closest ? e.target.closest(".pfas-seg-item") : null;
      if (!b || b.disabled) { return; }
      Array.prototype.forEach.call(seg.querySelectorAll(".pfas-seg-item"), function (x) {
        x.setAttribute("aria-pressed", x === b ? "true" : "false");
      });
      if (c.placePill) { c.placePill(seg); }
      follow();
    });
    sel.addEventListener("change", follow);
    follow();
    var foot = el("div", "pfas-drawer-actions");
    var save = el("button", "btn btn-primary", "Save"), cancel = el("button", "btn btn-secondary", "Cancel");
    save.type = cancel.type = "button";
    save.addEventListener("click", function () {
      var want = { code: sel.value || "", attach: chosen(), note: note.value };
      if (r.output) { want.output = out.value || ""; }
      Object.keys(want).forEach(function (k) {
        if (String(r[k].value || "") !== want[k]) { r[k].value = want[k]; fire(r[k]); }
      });
      redraw(tile);
      c.drawer.close();
    });
    cancel.addEventListener("click", function () { c.drawer.close(); });
    foot.appendChild(save);
    foot.appendChild(cancel);
    c.drawer.open(title, body, { footer: foot, cls: "is-dialog", opener: opener, focus: sel });
    if (c.seg) { c.seg(seg); }
  }
  document.addEventListener("click", function (e) {
    var b = e.target.closest ? e.target.closest("[data-flag-edit]") : null;
    var tile = b ? b.closest("[data-flag-tile]") : null;
    if (!tile) { return; }
    e.preventDefault();
    open(tile, b);
  });
  window.PFAS = window.PFAS || {};
  window.PFAS.flagTile = { redraw: redraw, open: open };
})();

/* The cards lists (profile_cards: the Matrices tab's Correction group, Run
   & reporting, Engine; a list marked data-set-list, its inputs' form in
   data-set-form). The list posts nothing: each tile is drawn again from the
   inputs it names (data-set-names) in the words the server draws (a switch
   Yes or No, a choice its option's words, a list of switches the ticked
   ones', words as typed, a blank its default noted, else Not set); a
   node's value from what it counts. Edit, and Edit in a node's menu, opens
   the shared centred window on nameless copies of the card's inputs (or of
   one block's, data-set-edit naming it), Done writing each changed one with
   input and change, so the unsaved count follows. A card's segment writes
   its input through data-input (PFAS.components seg, syncFieldSegs), its
   switch through data-switch-for (PFAS.components).
   Run & reporting: the run template's steps and the extraction stages are
   mini-cards drawn from the Table view's rows: a drag reorders those rows
   (the template's own renumbering, the stages' own), a stage opens its own
   window, a step's menu removes it as the table's does; + Add step and
   + Add stage add as the table does; a collection's mini-card opens its
   row's inputs, + Add a row adds one to the table first. A Reporting row
   opens its fold, as built. */
(function () {
  var NOT_SET = "Not set";
  function lists() { return Array.prototype.slice.call(document.querySelectorAll("[data-set-list]")); }
  function json(n, k, d) { try { return JSON.parse(n.getAttribute(k) || "null") || d; } catch (e) { return d; } }
  function byAttr(nodes, attr, v) {
    return Array.prototype.filter.call(nodes, function (n) { return n.getAttribute(attr) === v; });
  }
  function el(tag, cls, text) { return window.PFAS.mpList.el(tag, cls, text); }
  function comps() { return window.PFAS && window.PFAS.components ? window.PFAS.components : null; }
  function formOf(n) {
    var l = n.closest ? n.closest("[data-set-list]") : null;
    return n.getAttribute("data-set-form") || (l ? l.getAttribute("data-set-form") : "");
  }
  /* the one input `name` of `form` posts (never a card's copy) */
  function posted(name, form) {
    return Array.prototype.filter.call(document.getElementsByName(name), function (n) {
      return n.getAttribute("form") === form;
    })[0] || null;
  }
  function counted(n, noun) { return n + " " + (n === 1 ? noun : noun + "s"); }
  function isSet(n) {
    if (!n) { return false; }
    return n.type === "checkbox" ? !!n.checked : String(n.value || "").trim() !== "";
  }
  function shown(sel) {
    var o = Array.prototype.filter.call(sel.querySelectorAll("option"), function (x) { return x.value === sel.value; })[0];
    return o ? o.textContent : sel.value;
  }
  /* {text, note} a tile reads, or null while an input it names is not on the page */
  function words(tile) {
    var form = formOf(tile), kind = tile.getAttribute("data-set-kind");
    var labels = json(tile, "data-set-labels", []);
    var reals = json(tile, "data-set-names", []).map(function (n) { return posted(n, form); });
    if (!reals.length || reals.some(function (r) { return !r; })) { return null; }
    if (kind === "multi") {
      var on = labels.filter(function (l, i) { return reals[i].checked; });
      return { text: on.length ? on.join(", ") : "None" };
    }
    if (kind === "bool") { return { text: reals[0].checked ? "Yes" : "No" }; }
    var v = String(reals[0].value || "").trim();
    if (!v && tile.hasAttribute("data-set-blank")) {
      return { text: tile.getAttribute("data-set-blank"), note: tile.getAttribute("data-set-blank-note") || "" };
    }
    if (kind === "choice") {
      var hit = json(tile, "data-set-choices", []).filter(function (c) { return c[0] === v; })[0];
      return { text: hit ? hit[1] : (v ? (reals[0].tagName === "SELECT" ? shown(reals[0]) : v) : NOT_SET) };
    }
    var unit = tile.getAttribute("data-set-unit");
    return { text: v ? (unit && /^-?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/.test(v) ? v + " " + unit : v) : NOT_SET,
             note: tile.hasAttribute("data-set-blank") ? "" : null };
  }
  function setNote(tile, note) {
    if (note === null || note === undefined) { return; }
    var s = tile.querySelector(".pfas-hier-tile-s");
    if (!note) { if (s) { s.parentNode.removeChild(s); } return; }
    if (!s) { s = el("span", "pfas-hier-tile-s"); tile.appendChild(s); }
    s.textContent = note;
  }
  /* a node's value: the inputs it counts ("n of m set"), a switch's two
     words, the studies ticked, decimal places, a table's rows */
  function value(v, form) {
    var names;
    if (v.hasAttribute("data-set-count")) {
      names = json(v, "data-set-count", []);
      var n = names.filter(function (x) {
        return (Array.isArray(x) ? x : [x]).some(function (nm) { return isSet(posted(nm, form)); });
      }).length;
      return n ? n + " of " + names.length + " set" : NOT_SET;
    }
    if (v.hasAttribute("data-set-bool")) {
      var b = json(v, "data-set-bool", {}), box = posted(b.name, form);
      return box ? (box.checked ? b.on : b.off) : null;
    }
    if (v.hasAttribute("data-set-checked")) {
      names = json(v, "data-set-checked", []);
      var on = names.filter(function (nm) { return isSet(posted(nm, form)); }).length;
      return on ? on + " of " + names.length + " offered" : "None offered";
    }
    if (v.hasAttribute("data-set-places")) {
      var p = posted(v.getAttribute("data-set-places"), form), d = p ? String(p.value || "").trim() : "";
      if (!p) { return null; }
      return d && d !== "0" ? counted(parseInt(d, 10) || 0, "decimal place") : v.getAttribute("data-set-blank");
    }
    if (v.hasAttribute("data-set-rows")) {
      var rows = document.querySelectorAll(v.getAttribute("data-set-rows")).length;
      return counted(rows, v.getAttribute("data-set-noun"));
    }
    if (v.hasAttribute("data-set-coll")) {
      var k = collRows(v.getAttribute("data-set-coll")).filter(function (tr) { return collHead(tr); }).length;
      var noun = v.getAttribute("data-set-noun");
      return k ? counted(k, noun) : "No " + noun + "s";
    }
    return null;
  }
  function redraw(l) {
    var form = l.getAttribute("data-set-form");
    Array.prototype.forEach.call(l.querySelectorAll("[data-set-names]"), function (tile) {
      if (tile.hasAttribute("data-set-control")) { return; }
      var w = words(tile);
      if (!w) { return; }
      var v = tile.querySelector(".pfas-hier-tile-v");
      if (v) { v.textContent = w.text; }
      setNote(tile, w.note);
    });
    Array.prototype.forEach.call(l.querySelectorAll("[data-set-value]"), function (v) {
      var w = value(v, form);
      if (w !== null) { v.textContent = w; }
    });
    drawSteps(l);
    drawStages(l);
    Array.prototype.forEach.call(l.querySelectorAll("[data-coll]"), drawColl);
  }
  function redrawAll() { lists().forEach(redraw); }
  var due = null;
  function soon() { if (!due) { due = setTimeout(function () { due = null; redrawAll(); }, 0); } }
  ["input", "change"].forEach(function (type) {
    document.addEventListener(type, function (e) {
      var n = e.target;
      if (!n || !n.getAttribute || !n.getAttribute("form")) { return; }
      if (lists().some(function (l) { return l.getAttribute("data-set-form") === n.getAttribute("form"); })) { soon(); }
    });
  });

  /* Edit: the shared window on nameless copies of a card's inputs, or of
     one block's */
  function edit(card, scope, opener) {
    if (!card || !window.PFAS.mpList) { return; }
    var root = scope ? byAttr(card.querySelectorAll("[data-set-block]"), "data-set-block", scope)[0] || card : card;
    var form = formOf(card), items = [];
    Array.prototype.forEach.call(root.querySelectorAll("[data-set-names]"), function (tile) {
      var labels = json(tile, "data-set-labels", []);
      json(tile, "data-set-names", []).forEach(function (name, i) {
        var real = posted(name, form);
        if (real) { items.push({ real: real, label: labels[i] || name }); }
      });
    });
    var title = card.querySelector(".pfas-hier-card-t");
    if (items.length) { window.PFAS.mpList.editCopies(title ? title.textContent : "Edit", items, { opener: opener || null }); }
  }
  function cardOf(l, key) { return byAttr(l.querySelectorAll("[data-hier-card]"), "data-hier-card", key)[0] || null; }

  /* ── Run & reporting: steps, stages, collections ── */
  function stepRows() { return Array.prototype.slice.call(document.querySelectorAll("#seq-chips .pfas-seqrow")); }
  function drawSteps(l) {
    var box = l.querySelector("[data-seq-minis]");
    if (!box || !document.getElementById("seq-chips")) { return; }
    box.textContent = "";
    stepRows().forEach(function (tr, i) {
      var kind = tr.getAttribute("data-kind"), code = tr.getAttribute("data-code") || "";
      var label = tr.querySelector(".lbl"), n = parseInt(tr.getAttribute("data-n") || "0", 10) || 0;
      var m = el("div", "pfas-hier-mini");
      m.setAttribute("tabindex", "0");
      m.setAttribute("data-seq-mini", String(i));
      m.setAttribute("data-seq-code", code);
      m.setAttribute("data-row-actions", JSON.stringify(stepActions(tr, i, stepRows().length)));
      var t = el("span", "pfas-hier-mini-t"), grip = el("span", "grip");
      grip.setAttribute("aria-hidden", "true");
      t.appendChild(grip);
      /* its type's icon before its words, as profile_cards draws it */
      var c = comps(), icon = c && c.type ? c.type.icon(kind === "samples" ? "Sample" : code, null, false, true) : "";
      if (icon) { t.insertAdjacentHTML("beforeend", icon); }
      t.appendChild(document.createTextNode((i + 1) + " · " + (kind === "samples" ? "Samples" : (label ? label.textContent : code))));
      m.appendChild(t);
      m.appendChild(el("span", "pfas-hier-mini-s", kind === "samples" ? "Every sample of the run" : code + " · " + counted(n, "injection")));
      box.appendChild(m);
      if (c && c.rows) { c.rows.init(m); }
    });
  }
  /* a step's menu: Edit step, Move up, Move down, then its row's own
     (Remove step while it may go) */
  function stepActions(tr, i, n) {
    var own = [];
    try { own = JSON.parse(tr.getAttribute("data-row-actions") || "[]") || []; } catch (e) { own = []; }
    var out = [{ label: "Edit step", event: "seq-edit" }];
    if (i > 0) { out.push({ label: "Move up", event: "seq-up" }); }
    if (i < n - 1) { out.push({ label: "Move down", event: "seq-down" }); }
    return out.concat(own);
  }
  /* a step's window: what it is and where it runs, read here (its code and
     injections come from the Run Builder; its place from the order) */
  function openStep(i, opener) {
    var c = comps(), rows = stepRows(), tr = rows[i];
    if (!c || !tr) { return; }
    var kind = tr.getAttribute("data-kind"), label = tr.querySelector(".lbl"), n = parseInt(tr.getAttribute("data-n") || "0", 10) || 0;
    var name = kind === "samples" ? "Samples" : (label ? label.textContent : tr.getAttribute("data-code") || "");
    var body = el("div", "pfas-hier-tiles pfas-step-read");
    [["Code", kind === "samples" ? "—" : tr.getAttribute("data-code") || "—"],
     ["Injections", kind === "samples" ? "Every sample of the run" : String(n)],
     ["Position", (i + 1) + " of " + rows.length]].forEach(function (x) {
      var t = el("div", "pfas-hier-tile");
      t.appendChild(el("span", "pfas-hier-tile-l", x[0]));
      t.appendChild(el("span", "pfas-hier-tile-v", x[1]));
      body.appendChild(t);
    });
    var foot = el("div", "pfas-drawer-actions"), done = el("button", "btn btn-primary", "Done");
    done.type = "button";
    done.addEventListener("click", function () { c.drawer.close(); });
    foot.appendChild(done);
    c.drawer.open("Step " + (i + 1) + " · " + name, body, { footer: foot, cls: "is-dialog", opener: opener || null, focus: done });
  }
  /* Move up or down: the table's rows in the new order, renumbered, an
     unsaved change; the focus stays on the moved step */
  function moveStep(l, i, by) {
    var rows = stepRows(), body = document.getElementById("seq-chips"), j = i + by;
    if (!body || !rows[i] || !rows[j] || body.closest(".is-readonly")) { return; }
    if (by < 0) { body.insertBefore(rows[i], rows[j]); } else { body.insertBefore(rows[j], rows[i]); }
    if (window.PFAS.runTemplate) { window.PFAS.runTemplate.moved(); }
    redraw(l);
    /* the change just said is drawn again once more (soon): focus after it */
    function refocus() {
      var m = l.querySelector('[data-seq-mini="' + j + '"]');
      if (m && m.focus) { m.focus(); }
    }
    refocus();
    setTimeout(refocus, 0);
  }
  function stageMinis(l) { return l.querySelector("[data-stage-minis]"); }
  function drawStages(l) {
    var box = stageMinis(l);
    if (!box || !document.getElementById("stage-list") || typeof stageRows !== "function") { return; }
    box.textContent = "";
    var words = { amount: "Sample amount", final_volume: "Final extract volume", spe_port: "SPE port" };
    stageRows().forEach(function (row, i) {
      var k = stageKeys(row._stored || {}, i), m = el("div", "pfas-hier-mini");
      m.setAttribute("tabindex", "0");
      m.setAttribute("data-stage-mini", String(i));
      m.setAttribute("data-row-actions", JSON.stringify([{ label: "Edit", event: "stage-edit" }]));
      var t = el("span", "pfas-hier-mini-t"), grip = el("span", "grip");
      grip.setAttribute("aria-hidden", "true");
      t.appendChild(grip);
      t.appendChild(document.createTextNode(k.order + " · " + k.name));
      var sub = ["Records: " + (words[k.captures_samples] || "Nothing")];
      if (k.creates_solution) { sub.push("creates solution"); }
      if (k.capture_pedigree) { sub.push("pedigree"); }
      m.appendChild(t);
      m.appendChild(el("span", "pfas-hier-mini-s", sub.join(" · ")));
      box.appendChild(m);
      var c = comps();
      if (c && c.rows) { c.rows.init(m); }
    });
    var empty = l.querySelector("[data-stage-empty]");
    if (empty) { empty.hidden = stageRows().length !== 0; }
  }
  function collTable(id) { return byAttr(document.querySelectorAll("table.cf-coll"), "data-sheet", id)[0] || null; }
  function collRows(id) {
    var t = collTable(id);
    return t ? Array.prototype.filter.call(t.querySelectorAll("tbody tr"), function (tr) {
      return !tr.classList.contains("pfas-empty-row");
    }) : [];
  }
  function collInputs(tr) {
    return Array.prototype.filter.call(tr.querySelectorAll("input, select"), function (n) { return n.name; });
  }
  function collLabels(id) {
    var t = collTable(id);
    return t ? Array.prototype.map.call(t.querySelectorAll("thead th"), function (th) { return th.textContent.trim(); }) : [];
  }
  function cellWords(n) { return n.tagName === "SELECT" ? (n.value ? shown(n) : "") : String(n.value || "").trim(); }
  function collHead(tr) { var ins = collInputs(tr); return ins.length ? cellWords(ins[0]) : ""; }
  function drawColl(card) {
    var id = card.getAttribute("data-coll"), box = card.querySelector("[data-coll-minis]");
    if (!box || !collTable(id)) { return; }
    var labels = collLabels(id), any = false;
    box.textContent = "";
    collRows(id).forEach(function (tr, i) {
      var ins = collInputs(tr), head = collHead(tr);
      if (!head) { return; }
      any = true;
      var m = el("div", "pfas-hier-mini");
      m.setAttribute("tabindex", "0");
      m.setAttribute("data-coll-mini", String(i));
      m.setAttribute("data-row-actions", JSON.stringify([{ label: "Edit", event: "coll-edit" }]));
      m.appendChild(el("span", "pfas-hier-mini-t", head));
      var sub = ins.slice(1).map(function (n, j) {
        var w = cellWords(n);
        return w ? (labels[j + 1] || "") + ": " + w : "";
      }).filter(Boolean).join(" · ");
      if (sub) { m.appendChild(el("span", "pfas-hier-mini-s", sub)); }
      box.appendChild(m);
      var c = comps();
      if (c && c.rows) { c.rows.init(m); }
    });
    var empty = card.querySelector("[data-coll-empty]");
    if (empty) { empty.hidden = any; }
  }
  function editColl(card, tr, opener, done) {
    var id = card.getAttribute("data-coll"), labels = collLabels(id);
    var items = collInputs(tr).map(function (n, j) { return { real: n, label: labels[j] || n.name }; });
    var title = card.querySelector(".pfas-hier-card-t");
    window.PFAS.mpList.editCopies(title ? title.textContent : "Edit", items,
                                  { opener: opener || null, done: function () { redrawAll(); if (done) { done(); } } });
  }
  function addColl(card, opener) {
    var t = collTable(card.getAttribute("data-coll")), wrap = t ? t.closest(".cf-coll-wrap") : null;
    var add = wrap ? wrap.querySelector(".cf-add-row") : null;
    if (!add) { return; }
    add.click();
    var rows = collRows(card.getAttribute("data-coll"));
    if (rows.length) { editColl(card, rows[rows.length - 1], opener); }
  }
  /* + Add step: the window on a nameless copy of the table's chooser; Add
     writes the chooser and adds as the table's own button does */
  function addStep(opener) {
    var c = comps(), real = document.getElementById("seq-add"), btn = document.getElementById("seq-add-btn");
    if (!c || !real || !btn) { return; }
    var pick = el("select");
    pick.setAttribute("aria-label", "Step");
    Array.prototype.forEach.call(real.querySelectorAll("option"), function (o) {
      if (!o.value) { return; }
      var n = el("option", "", o.textContent);
      n.value = o.value;
      pick.appendChild(n);
    });
    var row = el("label", "pfas-pop-row");
    row.appendChild(el("span", "pfas-pop-l", "Step"));
    row.appendChild(pick);
    var body = el("div");
    body.appendChild(row);
    var foot = el("div", "pfas-drawer-actions"), cancel = el("button", "btn btn-secondary", "Cancel"),
        add = el("button", "btn btn-primary", "Add");
    cancel.type = add.type = "button";
    cancel.addEventListener("click", function () { c.drawer.close(); });
    add.addEventListener("click", function () {
      if (!pick.value) { return; }
      real.value = pick.value;
      btn.click();
      c.drawer.close();
    });
    foot.appendChild(cancel);
    foot.appendChild(add);
    c.drawer.open("Add a step", body, { footer: foot, cls: "is-dialog", opener: opener || null, focus: pick });
  }
  /* a drag among the mini-cards: the table's rows put in the same order */
  function reorder(rows, order, body) {
    order.forEach(function (i) { if (rows[i]) { body.appendChild(rows[i]); } });
  }
  function sortable(box, done) {
    if (!box || box.__pfasSort || !window.Sortable || box.closest(".is-readonly")) { return; }
    box.__pfasSort = true;
    window.Sortable.create(box, { draggable: ".pfas-hier-mini", handle: ".grip", animation: 150, ghostClass: "dragging",
                                  onEnd: done });
  }
  function initSort(l) {
    sortable(l.querySelector("[data-seq-minis]"), function () {
      var box = l.querySelector("[data-seq-minis]"), body = document.getElementById("seq-chips");
      var order = Array.prototype.map.call(box.querySelectorAll("[data-seq-mini]"), function (m) {
        return parseInt(m.getAttribute("data-seq-mini"), 10);
      });
      reorder(stepRows(), order, body);
      if (window.PFAS.runTemplate) { window.PFAS.runTemplate.moved(); }
      redraw(l);
    });
    sortable(stageMinis(l), function () {
      var box = stageMinis(l), body = document.getElementById("stage-list");
      var order = Array.prototype.map.call(box.querySelectorAll("[data-stage-mini]"), function (m) {
        return parseInt(m.getAttribute("data-stage-mini"), 10);
      });
      reorder(stageRows(), order, body);
      renumberStages();
      stagesEdited();
      redraw(l);
    });
  }
  function stageRowOf(m) {
    return typeof stageRows === "function" ? stageRows()[parseInt(m.getAttribute("data-stage-mini"), 10)] || null : null;
  }

  document.addEventListener("click", function (e) {
    var t = e.target, l = t && t.closest ? t.closest("[data-set-list]") : null;
    if (!l) { return; }
    var b = t.closest("[data-set-edit]");
    if (b) {
      var scope = b.getAttribute("data-set-edit");
      edit(b.closest("[data-hier-card]"), scope === "data-set-edit" ? "" : scope, b);
      return;
    }
    if (t.closest("[data-seq-add]")) { addStep(t.closest("[data-seq-add]")); return; }
    if (t.closest("[data-stage-add]")) { if (typeof openStageDrawer === "function") { openStageDrawer(null); } return; }
    var ca = t.closest("[data-coll-add]");
    if (ca) { addColl(ca.closest("[data-coll]"), ca); return; }
    if (t.closest(".grip")) { return; }
    var sm = t.closest("[data-stage-mini]");
    if (sm) { var row = stageRowOf(sm); if (row) { openStageDrawer(row); } return; }
    var qm = t.closest("[data-seq-mini]");
    if (qm) { openStep(parseInt(qm.getAttribute("data-seq-mini"), 10), qm); return; }
    var cm = t.closest("[data-coll-mini]");
    if (cm) {
      var card = cm.closest("[data-coll]"), tr = collRows(card.getAttribute("data-coll"))[parseInt(cm.getAttribute("data-coll-mini"), 10)];
      if (tr) { editColl(card, tr, cm); }
    }
  });
  document.addEventListener("keydown", function (e) {
    var m = e.target;
    if ((e.key !== "Enter" && e.key !== " ") || !m || !m.matches || !m.matches("[data-stage-mini], [data-coll-mini], [data-seq-mini]")) { return; }
    e.preventDefault();
    m.click();
  });
  document.addEventListener("pfas:row-action", function (e) {
    var at = e.detail && e.detail.row, l = at && at.closest ? at.closest("[data-set-list]") : null;
    if (!l) { return; }
    var name = e.detail.name;
    if (name === "set-edit") { edit(cardOf(l, at.getAttribute("data-card-node")), "", at); }
    else if (name === "stage-edit") { var row = stageRowOf(at); if (row) { openStageDrawer(row); } }
    else if (name === "coll-edit") { at.click(); }
    else if (name === "seq-edit") { openStep(parseInt(at.getAttribute("data-seq-mini"), 10), at); }
    else if (name === "seq-up" || name === "seq-down") {
      moveStep(l, parseInt(at.getAttribute("data-seq-mini"), 10), name === "seq-up" ? -1 : 1);
    }
    else if (name === "seq-remove") {
      var tr = stepRows()[parseInt(at.getAttribute("data-seq-mini"), 10)];
      if (tr) { tr.dispatchEvent(new CustomEvent("pfas:row-action", { bubbles: true, detail: { name: "seq-remove", row: tr } })); }
    }
  });
  function init() {
    lists().forEach(function (l) { redraw(l); initSort(l); });
  }
  if (document.readyState === "loading") { document.addEventListener("DOMContentLoaded", function () { setTimeout(init, 0); }); }
  else { init(); }
  window.PFAS = window.PFAS || {};
  window.PFAS.cardsList = { redraw: redrawAll, init: init };
})();
