/* New Prepared Standard: a sitting made from its recipe.
 *
 * The dialog opens on a prep log (FM-ENV-001 | FM-ENV-002) and a method; the
 * standard is one of the method's recipes on that log; its name, lot #,
 * volume, storage and expiry fill from the recipe, and each "made from" lists
 * the lots it may use, newest first. The server calculates the concentrations
 * and the expiry again when it saves (prep_sitting.py); what is shown here is
 * the same rule, for the analyst to see before saving.
 *
 * The helpers are DOM-free and tested in node: tests/js/prep_new_test.js. */
(function (root) {
  "use strict";

  function lotNumber(title, day) {
    return (title || "") + "_" + String(day || "").replace(/-/g, "").slice(2, 8);
  }

  function addDays(day, n) {
    var d = new Date(day + "T00:00:00Z");
    if (isNaN(d.getTime())) { return ""; }
    d.setUTCDate(d.getUTCDate() + n);
    return d.toISOString().slice(0, 10);
  }

  /* The prep date + the recipe's shelf life, no later than the earliest
     parent's expiry; with no shelf life, the earliest parent's. */
  function expiry(day, shelfDays, parentExpiries) {
    var caps = (parentExpiries || []).filter(Boolean).sort();
    var cap = caps.length ? caps[0] : "";
    if (shelfDays === null || shelfDays === undefined || shelfDays === "" || !day) { return cap; }
    var own = addDays(day, Number(shelfDays));
    return cap && cap.localeCompare(own) === -1 ? cap : own;
  }

  function fmt(v) {
    return v === null || v === undefined || isNaN(v) ? "" : String(Number(Number(v).toPrecision(6)));
  }

  /* A parent amount scaled to a larger (or smaller) batch. */
  function scaled(take, recipeFinal, final) {
    var t = parseFloat(take), rf = parseFloat(recipeFinal), f = parseFloat(final);
    if (isNaN(t)) { return ""; }
    if (isNaN(rf) || isNaN(f) || rf === 0) { return fmt(t); }
    return fmt(t * f / rf);
  }

  function recipesOn(method, log) {
    return ((method || {}).recipes || []).filter(function (r) { return r.log === log; });
  }

  /* A new sitting's prep date: the laboratory's day when the page gives it,
     else the UTC date. */
  function newDay() {
    var C = root.PFAS && root.PFAS.components;
    return (C && C.labToday && C.labToday()) || new Date().toISOString().slice(0, 10);
  }

  var api = { lotNumber: lotNumber, expiry: expiry, scaled: scaled, recipesOn: recipesOn, newDay: newDay };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; }
  if (typeof document === "undefined") { return; }

  function el(id) { return document.getElementById(id); }

  function option(value, text, selected) {
    var o = document.createElement("option");
    o.value = value; o.textContent = text;
    if (selected) { o.selected = true; }
    return o;
  }

  function init() {
    var holder = el("psNewData"), form = el("psNewForm");
    if (!holder || !form) { return; }
    var NS = JSON.parse(holder.getAttribute("data-new") || "{}");
    var state = { log: ((NS.logs || [])[0] || {}).slug || "", recipe: null };
    var methodSel = el("psNewMethod"), recipeSel = el("psNewRecipe");

    (NS.methods || []).forEach(function (m, i) { methodSel.appendChild(option(m.id, m.label, i === 0)); });

    function method() {
      return (NS.methods || []).filter(function (m) { return m.id === methodSel.value; })[0] || { recipes: [] };
    }

    function markLog() {
      Array.prototype.forEach.call(el("psNewLog").querySelectorAll("[data-log]"), function (b) {
        b.setAttribute("aria-selected", b.getAttribute("data-log") === state.log ? "true" : "false");
      });
      if (root.PFAS && PFAS.components) { PFAS.components.placePill(el("psNewLog")); }
    }

    function parentExpiries() {
      return Array.prototype.map.call(el("psNewParents").querySelectorAll("select"), function (s) {
        var o = s.options[s.selectedIndex];
        return o ? o.getAttribute("data-expiry") || "" : "";
      });
    }

    function refreshDates() {
      var r = state.recipe, day = el("psNewDate").value;
      el("psNewLot").value = r ? lotNumber(r.titles[0], day) : "";
      el("psNewExpiry").value = r ? expiry(day, r.shelf_days, parentExpiries()) : "";
    }

    function scaleAmounts() {
      var r = state.recipe;
      if (!r) { return; }
      Array.prototype.forEach.call(el("psNewParents").querySelectorAll("[data-take]"), function (inp) {
        inp.value = scaled(inp.getAttribute("data-take"), r.final, el("psNewFinal").value);
      });
    }

    function buildParents(r) {
      var body = el("psNewParents");
      body.innerHTML = "";
      (r.made_from || []).forEach(function (mf, i) {
        var tr = document.createElement("tr");
        var name = document.createElement("td");
        name.textContent = mf.label || "";
        var lotCell = document.createElement("td"), sel = document.createElement("select");
        sel.name = "pl_lot." + i;
        sel.setAttribute("aria-label", "Lot of " + (mf.label || ""));
        sel.appendChild(option("", mf.lots.length ? "Choose a lot" : "No usable lot"));
        mf.lots.forEach(function (l, j) {
          var o = option(l.key, l.label, j === 0);
          o.setAttribute("data-expiry", l.expiry || "");
          sel.appendChild(o);
        });
        sel.addEventListener("change", refreshDates);
        lotCell.appendChild(sel);
        var qtyCell = document.createElement("td"), qty = document.createElement("input");
        qty.type = "text"; qty.className = "pfas-input is-num"; qty.name = "pl_qty." + i;
        qty.setAttribute("aria-label", "Amount taken");
        if (mf.take !== null && mf.take !== undefined && mf.take !== "") { qty.setAttribute("data-take", mf.take); }
        qtyCell.appendChild(qty);
        var unitCell = document.createElement("td"), unit = document.createElement("input");
        unit.type = "text"; unit.className = "pfas-input is-num"; unit.name = "pl_unit." + i;
        unit.value = mf.take_unit || ""; unit.setAttribute("aria-label", "Unit");
        unitCell.appendChild(unit);
        [name, lotCell, qtyCell, unitCell].forEach(function (c) { tr.appendChild(c); });
        body.appendChild(tr);
      });
    }

    function fill() {
      var r = state.recipe, has = !!r;
      el("psNewEmpty").hidden = has;
      el("psNewBody").hidden = !has;
      el("psNewSave").disabled = !has;
      if (!has) { return; }
      el("psNewName").value = r.titles[0] || r.name;
      el("psNewSitting").textContent = r.statement;
      el("psNewFinal").value = r.final === null || r.final === undefined ? "" : r.final;
      el("psNewFinalUnit").textContent = (r.final_unit || "") + (r.per_level ? " per level" : "");
      var loc = (r.storage || {}).location || "", locSel = el("psNewStorage");
      locSel.value = Array.prototype.some.call(locSel.options, function (o) { return o.value === loc; }) ? loc : "";
      el("psNewCond").value = (r.storage || {}).conditions || "";
      el("psNewRecipeCard").href = el("psNewRecipeCard").getAttribute("data-base") + "?method=" +
        encodeURIComponent(methodSel.value) + "&recipe=" + encodeURIComponent(r.id);
      buildParents(r);
      scaleAmounts();
      refreshDates();
    }

    function refresh() {
      var list = recipesOn(method(), state.log), keep = recipeSel.value;
      recipeSel.innerHTML = "";
      list.forEach(function (r) { recipeSel.appendChild(option(r.id, r.name, r.id === keep)); });
      state.recipe = list.filter(function (r) { return r.id === recipeSel.value; })[0] || null;
      markLog();
      fill();
    }

    el("psNewLog").addEventListener("click", function (e) {
      var b = e.target.closest("[data-log]");
      if (!b) { return; }
      state.log = b.getAttribute("data-log");
      refresh();
    });
    methodSel.addEventListener("change", refresh);
    recipeSel.addEventListener("change", refresh);
    el("psNewDate").addEventListener("change", refreshDates);
    el("psNewFinal").addEventListener("input", scaleAmounts);
    el("psNewBy").value = NS.who || "";

    root.pfasOpenNew = function () {
      var m = /[?&]log=([0-9A-Za-z_-]+)/.exec(location.search);
      if (m) { state.log = m[1]; }
      if (!el("psNewDate").value) { el("psNewDate").value = newDay(); }
      el("psNew").classList.add("open");
      refresh();
      /* the pills measured zero while the dialog was closed */
      if (el("psNewTabs") && root.PFAS && PFAS.components) { PFAS.components.placePill(el("psNewTabs")); }
    };
    refresh();
  }

  if (document.readyState === "loading") { document.addEventListener("DOMContentLoaded", init); } else { init(); }
})(typeof window !== "undefined" ? window : this);
