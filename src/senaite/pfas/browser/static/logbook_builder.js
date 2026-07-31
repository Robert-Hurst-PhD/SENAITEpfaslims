/* PFAS logbook form builder.
 *
 * Replaces hand-typed JSON with a visual field + step editor. Serialises back
 * into the two hidden inputs (#lbFieldSchema, #lbStepsJson) that the server
 * already reads, so prep_logbooks.py needs no parsing change.
 *
 * The field-type vocabulary is NOT defined here — it is injected as
 * window.LB_FIELD_TYPES from senaite.pfas.logbook_schema.FIELD_TYPES, so the
 * builder can never offer a type the renderer does not honour.
 *
 * Lives in a static resource (not inline in the .pt) because Chameleon parses
 * inline <script> bodies and chokes on bare "<", "&" and "&&".
 *
 * ES5 only — this ships to whatever the bench tablets run.
 */
(function () {
  "use strict";

  var TYPES = window.LB_FIELD_TYPES || [];
  var LOT_TYPES = window.LB_LOT_TYPES || [];
  var COLUMN_TYPES = ["text", "date", "number"];
  var WIDTHS = ["sm", "md", "lg"];
  var NAME_RE = /^[a-z][a-z0-9_]{0,63}$/;

  var fields = [];   // [{name,label,type,required,width,correctable,lot_type,columns,default_rows}]
  var steps = [];    // [{id,title,instructions,media,media_alt,fields:[name,...]}]

  function capsFor(type) {
    for (var i = 0; i < TYPES.length; i++) {
      if (TYPES[i].type === type) { return TYPES[i].caps || []; }
    }
    return [];
  }
  function hasCap(type, cap) { return capsFor(type).indexOf(cap) !== -1; }

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) { e.className = cls; }
    if (text !== undefined && text !== null) { e.textContent = String(text); }
    return e;
  }
  function opt(value, label, selected) {
    var o = document.createElement("option");
    o.value = value;
    o.textContent = label;
    if (selected) { o.selected = true; }
    return o;
  }
  function slugId(s) {
    return (s || "").toLowerCase().replace(/[^a-z0-9_-]+/g, "-")
                    .replace(/^-+|-+$/g, "").substring(0, 32);
  }

  /* Derive the stored key from the analyst-facing question, obeying the
     server rules: start with a letter, lowercase/digits/underscore only,
     never a leading underscore, never a _json suffix. */
  function deriveName(label) {
    var s = (label || "").toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .substring(0, 60);
    if (!s) { return ""; }
    if (!/^[a-z]/.test(s)) { s = "f_" + s; }
    if (/_json$/.test(s)) { s += "_v"; }
    return s;
  }

  /* ── Fields tab ─────────────────────────────────────────────────────── */

  function renderFields() {
    var host = document.getElementById("fbFieldList");
    if (!host) { return; }
    host.textContent = "";

    if (!fields.length) {
      host.appendChild(el("div", "fb-empty",
        "No fields yet. Add the first one below."));
    }

    fields.forEach(function (f, idx) {
      var row = el("div", "fb-row");

      var head = el("div", "fb-row-head");
      var grip = el("span", "fb-idx", String(idx + 1));
      head.appendChild(grip);

      /* ONE visible box. What you type is what the analyst sees; the stored
         key is derived from it automatically. The key is shown small
         underneath and only becomes editable on request, because changing it
         once results exist orphans the data already saved under the old key. */
      var labelIn = el("input", "fb-in fb-in-label");
      labelIn.type = "text"; labelIn.value = f.label || "";
      labelIn.placeholder = "What the analyst is asked, e.g. Balance serial number";
      labelIn.addEventListener("input", function () {
        f.label = labelIn.value;
        if (!f._lockName) {
          var old = f.name;
          f.name = deriveName(labelIn.value);
          renameInSteps(old, f.name);
          var kt = row.querySelector(".fb-keytext");
          if (kt) { kt.textContent = f.name || "(not set)"; }
        }
        markDirty();
      });
      head.appendChild(labelIn);

      var typeSel = el("select", "fb-in fb-in-type");
      TYPES.forEach(function (t) {
        typeSel.appendChild(opt(t.type, t.label, t.type === f.type));
      });
      typeSel.addEventListener("change", function () {
        f.type = typeSel.value;
        if (f.type === "table" && !f.columns) { f.columns = []; f.default_rows = []; }
        renderFields(); markDirty();
      });
      head.appendChild(typeSel);

      var btns = el("span", "fb-rowbtns");
      btns.appendChild(iconBtn("▲", "Move up", function () { move(fields, idx, -1); }));
      btns.appendChild(iconBtn("▼", "Move down", function () { move(fields, idx, 1); }));
      btns.appendChild(iconBtn("×", "Remove field", function () {
        if (!window.confirm("Remove field '" + (f.name || "") + "'?")) { return; }
        removeFromSteps(f.name);
        fields.splice(idx, 1); renderFields(); renderSteps(); markDirty();
      }));
      head.appendChild(btns);
      row.appendChild(head);

      /* cap-driven sub-controls */
      var sub = el("div", "fb-row-sub");
      if (hasCap(f.type, "required")) {
        sub.appendChild(checkbox("Required", f.required, function (v) {
          f.required = v; markDirty();
        }));
      }
      if (hasCap(f.type, "width")) {
        var w = el("label", "fb-sublabel"); w.appendChild(document.createTextNode("Width "));
        var ws = el("select", "fb-in fb-in-sm");
        WIDTHS.forEach(function (x) { ws.appendChild(opt(x, x, x === (f.width || "md"))); });
        ws.addEventListener("change", function () { f.width = ws.value; markDirty(); });
        w.appendChild(ws); sub.appendChild(w);
      }
      if (hasCap(f.type, "correctable")) {
        var cbc = checkbox("Allow corrections", f.correctable, function (v) {
          f.correctable = v; markDirty();
        });
        cbc.title = "Lets an analyst change this value after saving without " +
                    "erasing history: the original is kept, struck through, " +
                    "with who changed it and when. Required for regulated " +
                    "records.";
        sub.appendChild(cbc);
      }
      if (hasCap(f.type, "lot_type")) {
        var l = el("label", "fb-sublabel");
        l.appendChild(document.createTextNode("Lot type "));
        var ls = el("select", "fb-in");
        ls.appendChild(opt("", "— any —", !f.lot_type));
        LOT_TYPES.forEach(function (x) {
          ls.appendChild(opt(x, x, x === f.lot_type));
        });
        ls.addEventListener("change", function () { f.lot_type = ls.value; markDirty(); });
        l.appendChild(ls); sub.appendChild(l);
      }
      if (sub.childNodes.length) { row.appendChild(sub); }

      if (hasCap(f.type, "columns")) { row.appendChild(columnEditor(f)); }

      /* the derived storage key, visible but out of the way */
      var keyBar = el("div", "fb-keybar");
      keyBar.appendChild(el("span", "fb-keylabel", "saved as"));
      keyBar.appendChild(el("code", "fb-keytext", f.name || "(not set)"));
      var edit = el("button", "fb-keyedit", f._lockName ? "auto" : "edit");
      edit.type = "button";
      edit.title = f._lockName
        ? "Go back to deriving the key from the question"
        : "Set the key by hand (only needed to match an existing record)";
      edit.addEventListener("click", function () {
        if (f._lockName) {                       // back to automatic
          f._lockName = false;
          f.name = deriveName(f.label || "");
          renderFields(); renderSteps(); markDirty();
          return;
        }
        var v = window.prompt(
          "Storage key for this field.\n\n" +
          "Lowercase letters, digits and underscores. Changing this on a " +
          "logbook that already has saved records will orphan the old values.",
          f.name || "");
        if (v === null) { return; }
        var old = f.name;
        f.name = deriveName(v);
        f._lockName = true;
        renameInSteps(old, f.name);
        renderFields(); renderSteps(); markDirty();
      });
      keyBar.appendChild(edit);
      row.appendChild(keyBar);

      host.appendChild(row);
    });
  }

  function checkbox(label, checked, onchange) {
    var l = el("label", "fb-sublabel");
    var c = document.createElement("input");
    c.type = "checkbox"; c.checked = !!checked;
    c.addEventListener("change", function () { onchange(c.checked); });
    l.appendChild(c);
    l.appendChild(document.createTextNode(" " + label));
    return l;
  }

  function iconBtn(glyph, title, fn) {
    var b = el("button", "fb-iconbtn", glyph);
    b.type = "button"; b.title = title;
    b.addEventListener("click", fn);
    return b;
  }

  function move(arr, idx, delta) {
    var to = idx + delta;
    if (to < 0 || to >= arr.length) { return; }
    var tmp = arr[idx]; arr[idx] = arr[to]; arr[to] = tmp;
    renderFields(); renderSteps(); markDirty();
  }

  function columnEditor(f) {
    var wrap = el("div", "fb-cols");
    wrap.appendChild(el("div", "fb-cols-title", "Table columns"));
    (f.columns || []).forEach(function (c, ci) {
      var r = el("div", "fb-colrow");
      var n = el("input", "fb-in fb-in-sm"); n.type = "text";
      n.value = c.name || ""; n.placeholder = "col_name";
      n.addEventListener("input", function () { c.name = n.value.trim(); markDirty(); });
      var lb = el("input", "fb-in"); lb.type = "text";
      lb.value = c.label || ""; lb.placeholder = "Column label";
      lb.addEventListener("input", function () { c.label = lb.value; markDirty(); });
      var ts = el("select", "fb-in fb-in-sm");
      COLUMN_TYPES.forEach(function (t) {
        ts.appendChild(opt(t, t, t === (c.type || "text")));
      });
      ts.addEventListener("change", function () { c.type = ts.value; markDirty(); });
      r.appendChild(n); r.appendChild(lb); r.appendChild(ts);
      r.appendChild(iconBtn("×", "Remove column", function () {
        f.columns.splice(ci, 1); renderFields(); markDirty();
      }));
      wrap.appendChild(r);
    });
    var add = el("button", "btn-add-row", "+ Add Column");
    add.type = "button";
    add.addEventListener("click", function () {
      if (!f.columns) { f.columns = []; }
      f.columns.push({ name: "", label: "", type: "text" });
      renderFields(); markDirty();
    });
    wrap.appendChild(add);
    if ((f.default_rows || []).length) {
      wrap.appendChild(el("div", "fb-hint",
        (f.default_rows.length) + " default row(s) preserved. Edit them on the JSON tab."));
    }
    return wrap;
  }

  /* ── Steps tab ──────────────────────────────────────────────────────── */

  function claimedBy(name) {
    for (var i = 0; i < steps.length; i++) {
      if ((steps[i].fields || []).indexOf(name) !== -1) { return i; }
    }
    return -1;
  }
  function removeFromSteps(name) {
    steps.forEach(function (s) {
      var i = (s.fields || []).indexOf(name);
      if (i !== -1) { s.fields.splice(i, 1); }
    });
  }
  function renameInSteps(oldName, newName) {
    if (!oldName || oldName === newName) { return; }
    steps.forEach(function (s) {
      var i = (s.fields || []).indexOf(oldName);
      if (i !== -1) { s.fields[i] = newName; }
    });
  }

  function renderSteps() {
    var host = document.getElementById("fbStepList");
    if (!host) { return; }
    host.textContent = "";

    if (!steps.length) {
      host.appendChild(el("div", "fb-empty",
        "No steps. This logbook opens as a single concise form."));
    }

    steps.forEach(function (s, idx) {
      var card = el("div", "fb-step");

      var head = el("div", "fb-row-head");
      head.appendChild(el("span", "fb-idx", String(idx + 1)));
      var t = el("input", "fb-in fb-in-label"); t.type = "text";
      t.value = s.title || ""; t.placeholder = "Step title, e.g. Weigh the reagent";
      t.addEventListener("input", function () {
        s.title = t.value;
        if (!s.id) { s.id = slugId(t.value) || ("s" + (idx + 1)); }
        markDirty();
      });
      head.appendChild(t);
      var btns = el("span", "fb-rowbtns");
      btns.appendChild(iconBtn("▲", "Move up", function () { moveStep(idx, -1); }));
      btns.appendChild(iconBtn("▼", "Move down", function () { moveStep(idx, 1); }));
      btns.appendChild(iconBtn("×", "Remove step", function () {
        if (!window.confirm("Remove this step? Its fields return to unassigned; no field is deleted.")) { return; }
        steps.splice(idx, 1); renderSteps(); markDirty();
      }));
      head.appendChild(btns);
      card.appendChild(head);

      var body = el("div", "fb-step-body");

      /* instructions */
      var left = el("div", "fb-step-instr");
      left.appendChild(el("label", "fb-sublabel", "Instructions (one action per line)"));
      var ta = el("textarea", "fb-in fb-instr");
      ta.rows = 5; ta.value = s.instructions || "";
      ta.addEventListener("input", function () { s.instructions = ta.value; markDirty(); });
      left.appendChild(ta);
      body.appendChild(left);

      /* media */
      var right = el("div", "fb-step-media");
      right.appendChild(el("label", "fb-sublabel", "Picture of the action"));
      var prev = el("div", "fb-thumb");
      if (s.media) {
        var img = document.createElement("img");
        img.src = mediaSrc(s.media);
        img.alt = s.media_alt || "";
        prev.appendChild(img);
      } else {
        prev.appendChild(el("span", "fb-thumb-empty", "none chosen"));
      }
      right.appendChild(prev);

      var pickBtn = el("button", "btn-sm", "Choose animation");
      pickBtn.type = "button";
      pickBtn.addEventListener("click", function () { openGallery(s); });
      right.appendChild(pickBtn);

      var upLabel = el("label", "fb-uplabel", "or upload your own");
      var file = document.createElement("input");
      file.type = "file";
      file.accept = ".gif,.png,.jpg,.jpeg";
      file.className = "fb-file";
      file.addEventListener("change", function () {
        if (file.files && file.files[0]) { uploadMedia(file.files[0], s); }
      });
      upLabel.appendChild(file);
      right.appendChild(upLabel);

      if (s.media) {
        var rm = el("button", "btn-sm", "Remove");
        rm.type = "button";
        rm.addEventListener("click", function () {
          s.media = ""; s.media_alt = ""; renderSteps(); markDirty();
        });
        right.appendChild(rm);
      }
      body.appendChild(right);
      card.appendChild(body);

      /* field assignment */
      var fa = el("div", "fb-assign");
      fa.appendChild(el("div", "fb-cols-title", "Fields shown on this step"));
      if (!fields.length) {
        fa.appendChild(el("span", "fb-hint", "Define fields first."));
      }
      fields.forEach(function (f) {
        if (!f.name) { return; }
        var owner = claimedBy(f.name);
        var mine = owner === idx;
        var lab = el("label", "fb-assign-item" + (!mine && owner !== -1 ? " is-taken" : ""));
        var cb = document.createElement("input");
        cb.type = "checkbox";
        cb.checked = mine;
        cb.disabled = !mine && owner !== -1;
        cb.addEventListener("change", function () {
          if (!s.fields) { s.fields = []; }
          if (cb.checked) { s.fields.push(f.name); }
          else {
            var i = s.fields.indexOf(f.name);
            if (i !== -1) { s.fields.splice(i, 1); }
          }
          renderSteps(); markDirty();
        });
        lab.appendChild(cb);
        lab.appendChild(document.createTextNode(" " + (f.label || f.name)));
        var badge = el("span", "fb-tybadge", f.type);
        lab.appendChild(badge);
        if (!mine && owner !== -1) {
          lab.appendChild(el("span", "fb-taken", "in step " + (owner + 1)));
        }
        fa.appendChild(lab);
      });
      card.appendChild(fa);

      host.appendChild(card);
    });

    updateUnassigned();
  }

  function moveStep(idx, delta) {
    var to = idx + delta;
    if (to < 0 || to >= steps.length) { return; }
    var tmp = steps[idx]; steps[idx] = steps[to]; steps[to] = tmp;
    renderSteps(); markDirty();
  }

  function updateUnassigned() {
    var box = document.getElementById("fbUnassigned");
    if (!box) { return; }
    if (!steps.length) { box.textContent = ""; return; }
    var loose = [];
    fields.forEach(function (f) {
      if (f.name && claimedBy(f.name) === -1) { loose.push(f.label || f.name); }
    });
    box.textContent = loose.length
      ? ("Unassigned fields (" + loose.length + "): " + loose.join(", ")
         + " — these appear in a final 'Additional fields' step.")
      : "All fields are assigned to a step.";
  }

  /* ── Step imagery: built-in library + own uploads ───────────────────── */

  /* A step's media is either "lib:<name>" (a shipped pixel-art animation) or
     an uploaded token. One field, two sources — mirrors media_src() server
     side so the picker preview and the analyst view agree. */
  function mediaSrc(token) {
    token = token || "";
    if (token.indexOf("lib:") === 0) {
      return window.LB_LIBRARY_BASE + token.substring(4) + ".gif";
    }
    return window.LB_MEDIA_URL + "?f=" + encodeURIComponent(token);
  }

  function openGallery(step) {
    var lib = window.LB_LIBRARY || [];
    var back = el("div", "fb-gal-backdrop");
    var box = el("div", "fb-gal");
    box.appendChild(el("div", "fb-gal-title", "Choose an animation"));
    var grid = el("div", "fb-gal-grid");
    lib.forEach(function (item) {
      var cell = el("button", "fb-gal-cell");
      cell.type = "button";
      var im = document.createElement("img");
      im.src = window.LB_LIBRARY_BASE + item.name + ".gif";
      im.alt = item.label;
      cell.appendChild(im);
      cell.appendChild(el("span", "fb-gal-cap", item.label));
      if (step.media === "lib:" + item.name) { cell.className += " is-on"; }
      cell.addEventListener("click", function () {
        step.media = "lib:" + item.name;
        step.media_alt = item.label;
        close(); renderSteps(); markDirty();
      });
      grid.appendChild(cell);
    });
    box.appendChild(grid);
    var bar = el("div", "fb-gal-bar");
    var cancel = el("button", "btn-sm", "Cancel");
    cancel.type = "button";
    cancel.addEventListener("click", function () { close(); });
    bar.appendChild(cancel);
    box.appendChild(bar);
    back.appendChild(box);
    document.body.appendChild(back);
    function close() {
      if (back.parentNode) { back.parentNode.removeChild(back); }
    }
    back.addEventListener("click", function (ev) {
      if (ev.target === back) { close(); }
    });
  }

  /* ── Media upload (AJAX so a reject never loses the typing) ─────────── */

  function uploadMedia(file, step) {
    var fd = new FormData();
    fd.append("action", "upload");
    fd.append("media", file);
    var xhr = new XMLHttpRequest();
    xhr.open("POST", window.LB_MEDIA_URL, true);
    xhr.onload = function () {
      var res = {};
      try { res = JSON.parse(xhr.responseText); } catch (e) { res = {}; }
      if (res.ok && res.token) {
        step.media = res.token;
        step.media_alt = step.media_alt || file.name;
        renderSteps(); markDirty();
      } else {
        window.alert("Upload failed: " + (res.error || ("HTTP " + xhr.status)));
      }
    };
    xhr.onerror = function () { window.alert("Upload failed (network)."); };
    xhr.send(fd);
  }

  /* ── Validation + serialization ─────────────────────────────────────── */

  function validate() {
    var errs = [];
    var seen = {};
    fields.forEach(function (f, i) {
      var w = "Field " + (i + 1);
      if (!f.name) { errs.push(w + ": name is required."); }
      else if (!NAME_RE.test(f.name)) {
        errs.push(w + " ('" + f.name + "'): use lowercase letters, digits and underscores, starting with a letter.");
      } else if (f.name.charAt(0) === "_") {
        errs.push(w + " ('" + f.name + "'): names may not start with an underscore.");
      } else if (/_json$/.test(f.name)) {
        errs.push(w + " ('" + f.name + "'): names may not end with '_json'.");
      } else if (seen[f.name]) {
        errs.push(w + ": duplicate name '" + f.name + "'.");
      } else { seen[f.name] = 1; }

      if (f.type === "table") {
        if (!(f.columns || []).length) {
          errs.push(w + " ('" + f.name + "'): a table needs at least one column.");
        }
        var cs = {};
        (f.columns || []).forEach(function (c, ci) {
          var cw = w + " column " + (ci + 1);
          if (!c.name) { errs.push(cw + ": name is required."); }
          else if (!NAME_RE.test(c.name)) { errs.push(cw + " ('" + c.name + "'): invalid name."); }
          else if (cs[c.name]) { errs.push(cw + ": duplicate column '" + c.name + "'."); }
          else { cs[c.name] = 1; }
        });
      }
    });
    steps.forEach(function (s, i) {
      if (!(s.title || "").trim()) { errs.push("Step " + (i + 1) + ": title is required."); }
      if (!s.id) { s.id = slugId(s.title) || ("s" + (i + 1)); }
    });
    return errs;
  }

  function cleanFields() {
    /* NB: _lockName is a builder-only flag and is deliberately not emitted. */
    return fields.map(function (f) {
      var o = { name: f.name, label: f.label || f.name, type: f.type };
      if (hasCap(f.type, "required") && f.required) { o.required = true; }
      if (hasCap(f.type, "width") && f.width) { o.width = f.width; }
      if (hasCap(f.type, "correctable") && f.correctable) { o.correctable = true; }
      if (hasCap(f.type, "lot_type") && f.lot_type) { o.lot_type = f.lot_type; }
      if (hasCap(f.type, "columns")) {
        o.columns = (f.columns || []).map(function (c) {
          return { name: c.name, label: c.label || c.name,
                   type: COLUMN_TYPES.indexOf(c.type) !== -1 ? c.type : "text" };
        });
        o.default_rows = f.default_rows || [];
      }
      return o;
    });
  }

  function cleanSteps() {
    return steps.map(function (s, i) {
      return {
        id: s.id || ("s" + (i + 1)),
        title: s.title || "",
        instructions: s.instructions || "",
        media: s.media || "",
        media_alt: s.media_alt || "",
        fields: (s.fields || []).filter(function (n) {
          return fields.some(function (f) { return f.name === n; });
        })
      };
    });
  }

  function showErrors(errs) {
    var box = document.getElementById("fbErrors");
    if (!box) { return; }
    box.textContent = "";
    if (!errs.length) { box.style.display = "none"; return; }
    box.style.display = "block";
    errs.slice(0, 8).forEach(function (e) { box.appendChild(el("div", null, e)); });
  }

  /* Called by serializeForm() in prep_logbooks.pt before submit.
     Returns false to block submission. */
  window.lbSerializeBuilder = function () {
    var errs = validate();
    showErrors(errs);
    if (errs.length) {
      switchTab("fields");
      return false;
    }
    document.getElementById("lbFieldSchema").value = JSON.stringify(cleanFields());
    document.getElementById("lbStepsJson").value = JSON.stringify(cleanSteps());
    return true;
  };

  function markDirty() {
    syncJsonTab();
    updateUnassigned();
  }

  function syncJsonTab() {
    var a = document.getElementById("fbFieldsJsonRaw");
    var b = document.getElementById("fbStepsJsonRaw");
    if (a) { a.value = JSON.stringify(cleanFields(), null, 2); }
    if (b) { b.value = JSON.stringify(cleanSteps(), null, 2); }
  }

  /* ── Load / tabs ────────────────────────────────────────────────────── */

  window.lbLoadBuilder = function (fieldSchemaJson, stepsJson, procedureText) {
    fields = [];
    steps = [];
    try {
      var f = JSON.parse(fieldSchemaJson || "[]");
      if (Object.prototype.toString.call(f) === "[object Array]") { fields = f; }
    } catch (e) { fields = []; }
    try {
      var s = JSON.parse(stepsJson || "[]");
      if (Object.prototype.toString.call(s) === "[object Array]") { steps = s; }
    } catch (e) { steps = []; }
    fields.forEach(function (x) {
      if (!x.type) { x.type = "text"; }
      /* A field loaded from storage already has a key that saved records are
         filed under. Never re-derive it from a label edit — that would orphan
         existing data. Only fields added in this session auto-derive. */
      if (x.name) { x._lockName = true; }
    });
    steps.forEach(function (x) { if (!x.fields) { x.fields = []; } });
    window.__lbProcedure = procedureText || "";
    renderFields(); renderSteps(); syncJsonTab(); showErrors([]);
    switchTab("fields");
  };

  function switchTab(name) {
    var tabs = document.querySelectorAll(".fb-tab");
    var panes = document.querySelectorAll(".fb-pane");
    var i;
    for (i = 0; i < tabs.length; i++) {
      tabs[i].className = "fb-tab" +
        (tabs[i].getAttribute("data-fbtab") === name ? " is-active" : "");
    }
    for (i = 0; i < panes.length; i++) {
      panes[i].className = "fb-pane" +
        (panes[i].getAttribute("data-fbpane") === name ? " is-active" : "");
    }
  }

  function init() {
    var sel = document.getElementById("fbNewType");
    if (sel) {
      TYPES.forEach(function (t) { sel.appendChild(opt(t.type, t.label, t.type === "text")); });
    }
    var add = document.getElementById("fbAddField");
    if (add) {
      add.addEventListener("click", function () {
        var t = sel ? sel.value : "text";
        var f = { name: "", label: "", type: t };
        if (t === "table") { f.columns = []; f.default_rows = []; }
        fields.push(f);
        renderFields(); renderSteps(); markDirty();
      });
    }
    var addStep = document.getElementById("fbAddStep");
    if (addStep) {
      addStep.addEventListener("click", function () {
        steps.push({ id: "s" + (steps.length + 1), title: "", instructions: "",
                     media: "", media_alt: "", fields: [] });
        renderSteps(); markDirty();
      });
    }
    var seed = document.getElementById("fbSeedSteps");
    if (seed) {
      seed.addEventListener("click", function () {
        var proc = (document.getElementById("lbProc") || {}).value ||
                   window.__lbProcedure || "";
        var lines = proc.split("\n").map(function (l) {
          return l.replace(/^\s*\d+[.)]\s*/, "").trim();
        }).filter(function (l) { return l.length > 0; });
        if (!lines.length) {
          window.alert("The Procedure box is empty — nothing to seed from.");
          return;
        }
        if (steps.length && !window.confirm("Replace the current " + steps.length + " step(s)?")) {
          return;
        }
        steps = lines.map(function (l, i) {
          return { id: "s" + (i + 1), title: l.substring(0, 60),
                   instructions: l, media: "", media_alt: "", fields: [] };
        });
        renderSteps(); markDirty();
      });
    }
    var apply = document.getElementById("fbApplyJson");
    if (apply) {
      apply.addEventListener("click", function () {
        var errBox = document.getElementById("fbJsonErr");
        try {
          var f = JSON.parse(document.getElementById("fbFieldsJsonRaw").value || "[]");
          var s = JSON.parse(document.getElementById("fbStepsJsonRaw").value || "[]");
          if (Object.prototype.toString.call(f) !== "[object Array]" ||
              Object.prototype.toString.call(s) !== "[object Array]") {
            throw new Error("Both must be JSON arrays.");
          }
          fields = f; steps = s;
          fields.forEach(function (x) { if (!x.type) { x.type = "text"; } });
          steps.forEach(function (x) { if (!x.fields) { x.fields = []; } });
          if (errBox) { errBox.textContent = ""; }
          renderFields(); renderSteps(); switchTab("fields");
        } catch (e) {
          if (errBox) { errBox.textContent = "Invalid JSON: " + e.message; }
        }
      });
    }
    document.addEventListener("click", function (ev) {
      var t = ev.target;
      if (t && t.className && String(t.className).indexOf("fb-tab") === 0) {
        switchTab(t.getAttribute("data-fbtab"));
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
