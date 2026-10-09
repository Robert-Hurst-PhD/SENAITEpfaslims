/* Document Templates designer: pdfme's Designer on one template's
 * draft. A field named after a data field (lot, exp, "lot (2)") shows that
 * data; every other field is fixed content, so this page keeps pdfme's
 * readOnly flag in step with the name. Validation and the data -> input rule
 * live on the server (senaite.pfas.document_templates); this page asks it. */
(function () {
  'use strict';

  var cfg = JSON.parse(document.getElementById('dt-config').textContent);
  var P = window.PFASPdfme;
  var el = document.getElementById('dt-designer');
  var token = (document.getElementById('dt-token') || {}).value || '';
  var keys = cfg.fields.map(function (f) { return f.key; });
  var tableCols = {};
  (cfg.tables || []).forEach(function (t) { tableCols[t.name] = t.columns; });
  var dirty = false, busy = false;

  function css(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  // the same pattern as document_templates.COPY_PATTERN: "lot (2)", "lot copy"
  var COPY_PATTERN = /( \(\d+\)| copy( \d+)?)+$/;
  function baseKey(name) { return String(name || '').replace(COPY_PATTERN, ''); }

  function eachField(t, fn) {
    (t.schemas || []).forEach(function (page) { (page || []).forEach(fn); });
  }

  /* Binding is by name: data-named fields take data, the rest are fixed. */
  /* A data table's columns are linked by key (cfg.columns_key). pdfme's own
     panel can add, remove or rename columns, so when the headings and the
     links no longer line up, link each heading to the column whose title it
     contains; an unmatched heading stays unlinked and the server says so. */
  function linkColumns(f) {
    var cols = tableCols[baseKey(f.name)];
    var head = f.head || [];
    var links = f[cfg.columns_key] || [];
    if (!cols || links.length === head.length) return false;
    f[cfg.columns_key] = head.map(function (h) {
      var text = String(h || '').toLowerCase();
      var hit = cols.filter(function (c) { return text.indexOf(c.title.toLowerCase()) >= 0; });
      hit.sort(function (a, b) { return b.title.length - a.title.length; });
      return hit.length ? hit[0].key : null;
    });
    return true;
  }

  function normalise(t) {
    var changed = false;
    eachField(t, function (f) {
      if (f.type === 'multiVariableText') return;          // its {names} decide
      if (f.type === 'table') {
        var isData = !!tableCols[baseKey(f.name)];
        if (isData && f.readOnly) { delete f.readOnly; changed = true; }
        if (!isData && !f.readOnly) { f.readOnly = true; changed = true; }
        if (isData && linkColumns(f)) changed = true;
        return;
      }
      if (f.type === 'image') {
        // a logo / signature field takes its picture from the data
        var pic = (cfg.images || []).indexOf(baseKey(f.name)) >= 0;
        if (pic && f.readOnly) { delete f.readOnly; changed = true; }
        if (!pic && !f.readOnly) { f.readOnly = true; changed = true; }
        return;
      }
      var bound = cfg.bindable.indexOf(f.type) >= 0 && keys.indexOf(baseKey(f.name)) >= 0;
      if (bound && f.readOnly) { delete f.readOnly; changed = true; }
      if (!bound && !f.readOnly) { f.readOnly = true; changed = true; }
    });
    return changed;
  }

  function showProblems(list) {
    var ul = document.getElementById('dt-problems');
    ul.innerHTML = '';
    (list || []).forEach(function (p) {
      var li = document.createElement('li');
      li.className = 'bench-warn';
      li.textContent = p;
      ul.appendChild(li);
    });
  }

  function post(action, extra) {
    var fd = new FormData();
    fd.append('action', action);
    fd.append('id', cfg.id);
    fd.append('_authenticator', token);
    Object.keys(extra || {}).forEach(function (k) { fd.append(k, extra[k]); });
    return fetch(cfg.endpoint, { method: 'POST', body: fd, credentials: 'same-origin' })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, body: j }; }); });
  }

  /* pdfme's own settings for each field type, filled in where a field (a
     starting layout, an older save) does not carry them, so the server's
     renderer gets the complete template the designer would have made. */
  function withDefaults(t) {
    var changed = false;
    eachField(t, function (f) {
      var p = pluginFor(f.type);
      if (!p) return;
      var d = p.propPanel.defaultSchema;
      Object.keys(d).forEach(function (k) {
        if (d[k] === undefined) return;
        if (!(k in f)) { f[k] = JSON.parse(JSON.stringify(d[k])); changed = true; return; }
        // one level down too: a table's head / body styles given in part
        if (d[k] && typeof d[k] === 'object' && !Array.isArray(d[k]) &&
            f[k] && typeof f[k] === 'object' && !Array.isArray(f[k])) {
          Object.keys(d[k]).forEach(function (sub) {
            if (!(sub in f[k]) && d[k][sub] !== undefined) {
              f[k][sub] = JSON.parse(JSON.stringify(d[k][sub]));
              changed = true;
            }
          });
        }
      });
    });
    return changed;
  }

  var template = cfg.template;
  var startedFromStarter = false;
  if (cfg.starter) {
    template = cfg.starter;
    startedFromStarter = true;
  }
  withDefaults(template);
  normalise(template);
  var designer = new P.Designer({
    domContainer: el,
    template: template,
    plugins: P.plugins,
    options: { lang: 'en', theme: { token: { colorPrimary: css('--s-primary') || undefined } } }
  });
  showProblems(cfg.problems);
  if (startedFromStarter) {
    dirty = true;
    document.getElementById('dt-saved').textContent =
      'A starting layout with everything this document must show: arrange it, then Save draft.';
  }

  designer.onChangeTemplate(function () {
    if (busy) return;
    var t = designer.getTemplate();
    if (normalise(t)) {
      busy = true;
      try { designer.updateTemplate(t); } finally { busy = false; }
    }
    dirty = true;
    if (!startedFromStarter) document.getElementById('dt-saved').textContent = 'Unsaved changes';
  });

  /* ── add a data field ─────────────────────────────────────────────────── */
  function pluginFor(type) {
    var names = Object.keys(P.plugins);
    for (var i = 0; i < names.length; i++) {
      var p = P.plugins[names[i]];
      if (p.propPanel.defaultSchema.type === type) return p;
    }
    return null;
  }

  function addField(field) {
    var isImage = (cfg.images || []).indexOf(field.key) >= 0;
    var type = isImage ? 'image' : document.getElementById('dt-add-as').value;
    var plugin = pluginFor(type);
    if (!plugin) return;
    var t = designer.getTemplate();
    var page = designer.getPageCursor ? designer.getPageCursor() : 0;
    var taken = {};
    eachField(t, function (f) { taken[f.name] = true; });
    var name = field.key, n = 2;
    while (taken[name]) { name = field.key + ' (' + (n++) + ')'; }
    var base = t.basePdf || {};
    var w = Math.max(10, Math.min((base.width || 50) - 4, type === 'text' ? 40 : (type === 'code128' || type === 'image' ? 40 : 16)));
    var h = type === 'text' ? 5 : (type === 'code128' ? 8 : 16);
    var s = JSON.parse(JSON.stringify(plugin.propPanel.defaultSchema));
    s.name = name;
    s.content = isImage ? (cfg.placeholder || '') : field.example;
    // below whatever is already on the page, so new fields do not pile up
    var y = 2;
    (t.schemas[page] || []).forEach(function (o) {
      if (o.position) y = Math.max(y, o.position.y + (o.height || 0) + 1);
    });
    if (y + h > (base.height || 25)) y = 2;
    s.position = { x: 2, y: y };
    s.width = w;
    s.height = h;
    if (type === 'text') s.fontSize = 8;
    if (type === 'text' && (cfg.long || []).indexOf(field.key) >= 0) {
      s.overflow = 'expand';          // a paragraph: grows, moves what follows down
      s.width = Math.max(w, (base.width || 210) - 20);
    }
    delete s.readOnly;
    t.schemas[page] = (t.schemas[page] || []).concat([s]);
    designer.updateTemplate(t);
  }

  /* The columns a table starts with: a small chooser, grouped as the data
     fields are; pdfme's own panel can still edit them afterwards. */
  function chooseColumns(table) {
    var old = document.getElementById('dt-col-chooser');
    if (old) old.parentNode.removeChild(old);
    var box = document.createElement('div');
    box.id = 'dt-col-chooser';
    box.className = 'dt-col-chooser';
    var groups = table.groups && table.groups.length ? table.groups
      : [{ title: table.title, keys: table.columns.map(function (c) { return c.key; }) }];
    var byKey = {};
    table.columns.forEach(function (c) { byKey[c.key] = c; });
    groups.forEach(function (g) {
      var fs = document.createElement('fieldset');
      var lg = document.createElement('legend');
      lg.textContent = g.title;
      fs.appendChild(lg);
      g.keys.forEach(function (k) {
        if (!byKey[k]) return;
        var lab = document.createElement('label');
        var cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.value = k;
        cb.checked = k !== 'analysis_date' && k !== 'action_level' && k !== 'analyte_name';
        lab.appendChild(cb);
        lab.appendChild(document.createTextNode(' ' + byKey[k].title));
        fs.appendChild(lab);
      });
      box.appendChild(fs);
    });
    var go = document.createElement('button');
    go.type = 'button';
    go.className = 'btn-sm btn-primary';
    go.textContent = 'Add the table';
    go.addEventListener('click', function () {
      var picked = Array.prototype.slice.call(box.querySelectorAll('input:checked')).map(function (i) { return i.value; });
      if (!picked.length) return;
      addTable({ name: table.name, columns: table.columns.filter(function (c) { return picked.indexOf(c.key) >= 0; }) });
      box.parentNode.removeChild(box);
    });
    box.appendChild(go);
    document.querySelector('.dt-toolbar').appendChild(box);
  }

  function addTable(table) {
    var plugin = pluginFor('table');
    var t = designer.getTemplate();
    var page = designer.getPageCursor ? designer.getPageCursor() : 0;
    var taken = {};
    eachField(t, function (f) { taken[f.name] = true; });
    var name = table.name, n = 2;
    while (taken[name]) { name = table.name + ' (' + (n++) + ')'; }
    var base = t.basePdf || {};
    var pad = base.padding || [10, 10, 10, 10];
    var s = JSON.parse(JSON.stringify(plugin.propPanel.defaultSchema));
    var cols = table.columns;
    s.name = name;
    s.head = cols.map(function (c) { return c.title; });
    s.headWidthPercentages = cols.map(function () { return 100 / cols.length; });
    s[cfg.columns_key] = cols.map(function (c) { return c.key; });
    s.content = JSON.stringify([cols.map(function (c) { return c.example; })]);
    // below what is already on the page, in the compact ruled style
    var y = (pad[0] || 10);
    (t.schemas[page] || []).forEach(function (o) {
      if (o.position && !o[cfg.every_page]) y = Math.max(y, o.position.y + (o.height || 0) + 4);
    });
    if (y + 20 > (base.height || 297) - (pad[2] || 10)) y = (pad[0] || 10);
    s.position = { x: pad[3] || 10, y: y };
    s.tableStyles = { borderColor: '#222222', borderWidth: 0.2 };
    s.headStyles = Object.assign({}, s.headStyles, { fontSize: 7.5, fontColor: '#222222', backgroundColor: '',
      borderColor: '#222222', borderWidth: { top: 0.3, right: 0, bottom: 0.3, left: 0 },
      padding: { top: 1.5, right: 1.5, bottom: 1.5, left: 1.5 } });
    s.bodyStyles = Object.assign({}, s.bodyStyles, { fontSize: 8, borderColor: '#dddddd', alternateBackgroundColor: '',
      borderWidth: { top: 0, right: 0, bottom: 0.1, left: 0 }, padding: { top: 1, right: 1.5, bottom: 1, left: 1.5 } });
    s.width = (base.width || 210) - (pad[1] || 10) - (pad[3] || 10);
    s.height = 20;
    s.showHead = true;
    s.repeatHead = true;
    delete s.readOnly;
    t.schemas[page] = (t.schemas[page] || []).concat([s]);
    designer.updateTemplate(t);
  }

  /* "On every page": the selected fields repeat on each page of a document
     (letterhead, report number, page numbers); the server moves them into
     pdfme's repeating area when it renders. */
  function showEveryPage() {
    var names = [];
    eachField(designer.getTemplate(), function (f) { if (f[cfg.every_page]) names.push(f.name); });
    var el = document.getElementById('dt-every-list');
    if (el) el.textContent = names.length ? 'On every page: ' + names.join(', ') : 'Nothing is on every page yet.';
  }

  function toggleEveryPage() {
    var picked = (designer.getSelectedSchemas ? designer.getSelectedSchemas() : []).map(function (s) { return s.name; });
    if (!picked.length) { showProblems(['Select one or more fields on the page first.']); return; }
    var t = designer.getTemplate();
    var on = false;
    eachField(t, function (f) { if (picked.indexOf(f.name) >= 0 && !f[cfg.every_page]) on = true; });
    eachField(t, function (f) {
      if (picked.indexOf(f.name) < 0) return;
      if (on) f[cfg.every_page] = true; else delete f[cfg.every_page];
    });
    designer.updateTemplate(t);
    showEveryPage();
  }

  var tablesHolder = document.getElementById('dt-tables');
  if (tablesHolder) {
    (cfg.tables || []).forEach(function (tb) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'btn-sm btn-secondary';
      b.textContent = '+ ' + tb.title + ' table';
      b.title = 'Columns: ' + tb.columns.map(function (c) { return c.title; }).join(', ');
      b.addEventListener('click', function () { chooseColumns(tb); });
      tablesHolder.appendChild(b);
    });
  }
  var everyBtn = document.getElementById('dt-every-page');
  if (everyBtn) everyBtn.addEventListener('click', toggleEveryPage);
  showEveryPage();

  var holder = document.getElementById('dt-fields');
  if (holder && (cfg.fields.length > 12 || (cfg.groups || []).length > 1)) {
    // many data fields (a certificate): one picker, grouped (sample, analysis,
    // laboratory, preparer / reviewer / director ...)
    var pick = document.createElement('select');
    pick.id = 'dt-field-pick';
    pick.setAttribute('aria-label', 'Data field');
    var index = {};
    cfg.fields.forEach(function (f, i) { index[f.key] = i; });
    (cfg.groups && cfg.groups.length ? cfg.groups : [{ title: 'Data', keys: cfg.fields.map(function (f) { return f.key; }) }])
      .forEach(function (g) {
        var og = document.createElement('optgroup');
        og.label = g.title;
        g.keys.forEach(function (k) {
          if (!(k in index)) return;
          var o = document.createElement('option');
          o.value = String(index[k]);
          o.textContent = cfg.fields[index[k]].title + ((cfg.images || []).indexOf(k) >= 0 ? ' (picture)' : '');
          og.appendChild(o);
        });
        pick.appendChild(og);
      });
    var add = document.createElement('button');
    add.type = 'button';
    add.className = 'btn-sm btn-secondary';
    add.textContent = '+ Add';
    add.addEventListener('click', function () { addField(cfg.fields[Number(pick.value)]); });
    holder.appendChild(pick);
    holder.appendChild(add);
  } else if (holder) {
    cfg.fields.forEach(function (f) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'btn-sm btn-secondary';
      b.textContent = '+ ' + f.title;
      b.title = 'Example: ' + f.example;
      b.addEventListener('click', function () { addField(f); });
      holder.appendChild(b);
    });
  }

  /* ── save / preview ───────────────────────────────────────────────────── */
  var saveBtn = document.getElementById('dt-save');
  if (saveBtn) {
    saveBtn.addEventListener('click', function () {
      saveBtn.disabled = true;
      post('save_draft', { template: JSON.stringify(designer.getTemplate()) }).then(function (res) {
        saveBtn.disabled = false;
        if (!res.ok) { showProblems([res.body.error || 'Not saved.']); return; }
        dirty = false;
        startedFromStarter = false;
        showProblems(res.body.problems);
        var st = res.body.status;
        document.getElementById('dt-status').textContent = st.none_issued ? 'Not issued'
          : (st.unissued ? 'Issued rev ' + st.rev + ', draft changed' : 'Issued rev ' + st.rev);
        document.getElementById('dt-saved').textContent = 'Draft saved ' + res.body.saved_at.replace('T', ' ');
      }, function () {
        saveBtn.disabled = false;
        showProblems(['Not saved: the server did not answer.']);
      });
    });
  }

  document.getElementById('dt-preview').addEventListener('click', function () {
    var t = designer.getTemplate();
    post('preview_inputs', { template: JSON.stringify(t) }).then(function (res) {
      if (!res.ok) { showProblems([res.body.error || 'No preview.']); return null; }
      showProblems(res.body.problems);
      if (!res.body.template) return null;
      // the same compiled document the server renders (compile_document)
      return P.generate({ template: res.body.template, inputs: [res.body.inputs], plugins: P.plugins });
    }).then(function (pdf) {
      if (!pdf) return;
      var frame = document.getElementById('dt-pdf');
      if (frame.dataset.url) URL.revokeObjectURL(frame.dataset.url);
      frame.dataset.url = URL.createObjectURL(new Blob([pdf.buffer], { type: 'application/pdf' }));
      frame.src = frame.dataset.url;
      frame.hidden = false;
      frame.scrollIntoView({ behavior: 'smooth' });
    }).catch(function (e) { showProblems(['No preview: ' + (e && e.message || e)]); });
  });

  window.addEventListener('beforeunload', function (e) {
    if (dirty && saveBtn) { e.preventDefault(); e.returnValue = ''; }
  });
}());
