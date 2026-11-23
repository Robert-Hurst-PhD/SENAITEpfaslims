/* The CoC sample rows' detail: a row keeps its occasional values (composite,
 * sub-type, sampling point, container, preservative, homogenisation,
 * compliance, removal) in hidden boxes that post under their own names, and
 * shows them in words; their boxes are the one dialog #coc-detail. Edit
 * fills the dialog from the row, Done writes the row and its words, Cancel
 * leaves the row as it was. The words are coc_entry.detail_summary's, so a
 * saved row reads the same. A row offers only the sub-types of its matrix
 * that its method analyses (each option carries its sample type, data-type,
 * and the method profiles turned off for it, data-off); a sub-type the
 * matrix or method no longer allows is cleared. */
(function () {
  "use strict";
  var row = null;
  var CHOICES = [["subtype", "Sub-type"], ["sampling_point", "Sampling point"], ["container", "Container"],
                 ["preservation", "Preservative"], ["homogenisation", "Homogenisation"]];
  var SWITCHES = ["composite", "compliance", "remove"];
  var TEXTS = ["units", "description"];
  function box() { return document.getElementById("coc-detail"); }
  function part(r, key) { return r.querySelector('input[type="hidden"][name$="__' + key + '"]'); }
  function ctl(key) { return box().querySelector('[data-detail="' + key + '"]'); }
  function trim(v) { return String(v || "").replace(/^\s+|\s+$/g, ""); }
  function compositeWords(v) {
    if (!v.composite) { return ""; }
    var head = trim(v.units) ? "Composite of " + trim(v.units) + " units" : "Composite";
    return trim(v.description) ? head + ": " + trim(v.description) : head;
  }
  /* v: the row's values; text(key, value): the words of a choice */
  function words(v, text) {
    var out = [compositeWords(v)];
    CHOICES.forEach(function (c) {
      var val = trim(v[c[0]]);
      if (val) { out.push(c[1] + " " + (text ? text(c[0], val) : val)); }
    });
    if (v.compliance) { out.push("Compliance sample"); }
    var shown = out.filter(function (x) { return x; });
    return shown.length ? shown.join(" · ") : "No composite, container or preservative set";
  }
  function optionText(key, val) {
    var sel = box() && ctl(key), found = val;
    if (!sel) { return val; }
    Array.prototype.forEach.call(sel.options, function (o) { if (o.value === val) { found = trim(o.textContent); } });
    return found;
  }
  function read(r) {
    var v = {};
    SWITCHES.forEach(function (k) { var p = part(r, k); v[k] = !!p && p.value === "on"; });
    TEXTS.concat(CHOICES.map(function (c) { return c[0]; })).forEach(function (k) {
      var p = part(r, k); v[k] = p ? p.value : "";
    });
    return v;
  }
  function show(r) {
    var v = read(r), el = r.querySelector("[data-detail-summary]");
    if (!el) { return; }
    el.textContent = v.remove ? "Removed when saved" : words(v, optionText);
  }
  function rowValue(r, key) {
    var s = r.querySelector('select[name$="__' + key + '"]');
    return s ? s.value : "";
  }
  function fits(o, r) {
    var off = (o.getAttribute("data-off") || "").split(" ");
    return o.getAttribute("data-type") === rowValue(r, "sampletype") && off.indexOf(rowValue(r, "method")) === -1;
  }
  /* the dialog's sub-types that fit the row; false when none does */
  function filterSubtypes(r) {
    var sel = ctl("subtype"), any = false;
    if (!sel) { return false; }
    Array.prototype.forEach.call(sel.options, function (o) {
      if (!o.value) { return; }
      var ok = fits(o, r);
      o.hidden = !ok; o.disabled = !ok;
      if (ok) { any = true; }
    });
    return any;
  }
  function fire(el) {
    var ev;
    if (typeof Event === "function") { ev = new Event("change", { bubbles: true }); }
    else { ev = document.createEvent("Event"); ev.initEvent("change", true, false); }
    el.dispatchEvent(ev);
  }
  function open(r) {
    row = r;
    var v = read(r), sid = r.querySelector('input[name$="__client_sid"]');
    ctl("sample").textContent = sid && trim(sid.value) ? "Sample " + trim(sid.value) : "";
    SWITCHES.forEach(function (k) { ctl(k).checked = v[k]; });
    TEXTS.forEach(function (k) { ctl(k).value = v[k]; });
    CHOICES.forEach(function (c) { if (ctl(c[0])) { ctl(c[0]).value = v[c[0]]; } });
    var group = box().querySelector('[data-detail-group="subtype"]');
    if (group) { group.hidden = !filterSubtypes(r); }
    /* only a row that is not yet a sample can be taken off */
    box().querySelector('[data-detail-group="remove"]').hidden = !part(r, "remove");
    box().classList.add("open");
    ctl("composite").focus();
  }
  function done() {
    if (!row) { return; }
    var on = ctl("composite").checked;
    var vals = { composite: on ? "on" : "", compliance: ctl("compliance").checked ? "on" : "",
                 remove: ctl("remove").checked ? "on" : "",
                 /* not a composite: no units and no description are kept for the row */
                 units: on ? trim(ctl("units").value) : "", description: on ? trim(ctl("description").value) : "" };
    CHOICES.forEach(function (c) { vals[c[0]] = ctl(c[0]) ? ctl(c[0]).value : ""; });
    Object.keys(vals).forEach(function (k) { var p = part(row, k); if (p) { p.value = vals[k]; } });
    show(row);
    /* the row changed: the page's unsaved-changes watch hears a change */
    fire(part(row, "composite"));
    box().classList.remove("open");
    var back = row;
    row = null;
    if (back.focus) { back.focus(); }
  }
  /* a matrix or method that no longer allows the row's sub-type clears it */
  document.addEventListener("change", function (e) {
    var name = (e.target && e.target.name) || "";
    if (!/__(sampletype|method)$/.test(name) || !box()) { return; }
    var r = e.target.closest("tr"), p = r && part(r, "subtype");
    if (!p || !p.value) { return; }
    var sel = ctl("subtype"), keep = false;
    Array.prototype.forEach.call(sel ? sel.options : [], function (o) { if (o.value === p.value && fits(o, r)) { keep = true; } });
    if (!keep) { p.value = ""; show(r); }
  });
  document.addEventListener("click", function (e) {
    var t = e.target && e.target.closest ? e.target : null;
    if (!t || !box()) { return; }
    if (t.closest("[data-detail-done]")) { e.preventDefault(); done(); }
  });
  /* a row's Sample details, from the row's menu */
  document.addEventListener("pfas:row-action", function (e) {
    if (e.detail && e.detail.name === "sample-details" && e.detail.row && box()) { open(e.detail.row); }
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && e.target && e.target.closest && e.target.closest("#coc-detail") &&
        e.target.tagName === "INPUT" && e.target.type !== "checkbox") { e.preventDefault(); done(); }
  });
  /* "This is me" beside Sampled by: the box starts empty, and the signed-in
     person fills it with their own name only by saying so */
  document.addEventListener("click", function (e) {
    var me = e.target && e.target.closest ? e.target.closest("[data-this-is-me]") : null;
    var input = me && document.getElementById(me.getAttribute("data-this-is-me"));
    if (!input) { return; }
    e.preventDefault();
    input.value = me.getAttribute("data-name") || "";
    input.dispatchEvent(new Event("change", { bubbles: true }));
    input.focus();
  });
  if (typeof module !== "undefined" && module.exports) { module.exports = { words: words }; }
})();
