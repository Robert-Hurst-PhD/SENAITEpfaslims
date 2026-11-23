/* New Prepared Standard: a sitting made from its recipe.
 *
 * The dialog opens on a method and one of its recipes -- the ones the address
 * names (?method=&recipe=, the Recipes page's Make), else the first; its
 * name, lot #, volume, storage, expiry and default standard type fill from
 * the recipe, and each "made from" lists the lots it may use, newest first. The server calculates the concentrations
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

  /* A lot is out of date on `day` when its expiry is before it (one expiring
     that day is in date); the server judges it again (lot_expiry.py). */
  function expiredOn(expiry, day) {
    return !!(expiry && day) && expiry.localeCompare(day) === -1;
  }

  /* The text of a lot's option on the prep date: its label, marked when the
     lot is out of date that day. */
  function lotText(label, expiry, day) {
    return expiredOn(expiry, day) ? label + " \u00b7 expired" : label;
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

  /* The item whose id is `want`, else the first, else null. */
  function choose(list, want) {
    var found = (list || []).filter(function (x) { return x.id === want; })[0];
    return found || (list || [])[0] || null;
  }

  /* A new sitting's prep date: the laboratory's day when the page gives it,
     else the UTC date. */
  function newDay() {
    var C = root.PFAS && root.PFAS.components;
    return (C && C.labToday && C.labToday()) || new Date().toISOString().slice(0, 10);
  }

  /* One value of a query string ("?a=1&b=2"); "" when absent or when its
     escape is malformed -- a bad address must not stop the dialog. */
  function fromQuery(search, name) {
    var m = new RegExp("[?&]" + name + "=([^&#]*)").exec(search || "");
    if (!m) { return ""; }
    try { return decodeURIComponent(m[1].replace(/\+/g, " ")); } catch (e) { return ""; }
  }

  var api = { lotNumber: lotNumber, expiry: expiry, scaled: scaled, choose: choose, fromQuery: fromQuery,
              newDay: newDay, expiredOn: expiredOn, lotText: lotText };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; }
  if (typeof document === "undefined") { return; }

  function el(id) { return document.getElementById(id); }

  function option(value, text, selected) {
    var o = document.createElement("option");
    o.value = value; o.textContent = text;
    if (selected) { o.selected = true; }
    return o;
  }

  function param(name) { return fromQuery(location.search, name); }

  function init() {
    var holder = el("psNewData"), form = el("psNewForm");
    if (!holder || !form) { return; }
    var NS = JSON.parse(holder.getAttribute("data-new") || "{}");
    var state = { recipe: null };
    var methodSel = el("psNewMethod"), recipeSel = el("psNewRecipe");
    var first = choose(NS.methods, param("method"));

    (NS.methods || []).forEach(function (m) { methodSel.appendChild(option(m.id, m.label, m === first)); });

    function method() {
      return (NS.methods || []).filter(function (m) { return m.id === methodSel.value; })[0] || { recipes: [] };
    }

    function parentExpiries() {
      return Array.prototype.map.call(el("psNewParents").querySelectorAll("select"), function (s) {
        var o = s.options[s.selectedIndex];
        return o ? o.getAttribute("data-expiry") || "" : "";
      });
    }

    /* a parent out of date on the prep date is marked, and the reason for
       using it is asked for: required while one is picked, else not posted */
    function refreshExpired() {
      var day = el("psNewDate").value, used = [];
      Array.prototype.forEach.call(el("psNewParents").querySelectorAll("select"), function (s) {
        Array.prototype.forEach.call(s.options, function (o) {
          if (o.value) { o.textContent = lotText(o.getAttribute("data-label"), o.getAttribute("data-expiry"), day); }
        });
        var o = s.options[s.selectedIndex];
        if (o && o.value && expiredOn(o.getAttribute("data-expiry"), day)) { used.push(o.getAttribute("data-label")); }
      });
      var field = el("psNewExpiredField"), reason = el("psNewExpiredReason");
      field.hidden = !used.length;
      reason.disabled = !used.length;
      reason.required = !!used.length;
      el("psNewExpiredLots").textContent = used.join("; ");
    }

    function refreshDates() {
      var r = state.recipe, day = el("psNewDate").value;
      el("psNewLot").value = r ? lotNumber(r.titles[0], day) : "";
      el("psNewExpiry").value = r ? expiry(day, r.shelf_days, parentExpiries()) : "";
      refreshExpired();
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
        /* the first lot in date on the prep date is preselected, never one out of date */
        var day = el("psNewDate").value, pick = mf.lots.filter(function (l) { return !expiredOn(l.expiry, day); })[0];
        mf.lots.forEach(function (l) {
          var o = option(l.key, l.label, l === pick);
          o.setAttribute("data-expiry", l.expiry || "");
          o.setAttribute("data-label", l.label);
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
      /* the recipe's kind gives the type (blank when the lab's list lacks
         it); the select still overrides it */
      el("psNewType").value = r.standard_type || "";
      el("psNewRecipeCard").href = el("psNewRecipeCard").getAttribute("data-base") + "?method=" +
        encodeURIComponent(methodSel.value) + "&recipe=" + encodeURIComponent(r.id);
      buildParents(r);
      scaleAmounts();
      refreshDates();
    }

    function refresh(want) {
      var list = method().recipes || [], pick = choose(list, want || recipeSel.value);
      recipeSel.innerHTML = "";
      list.forEach(function (r) { recipeSel.appendChild(option(r.id, r.name, r === pick)); });
      state.recipe = pick;
      fill();
    }

    methodSel.addEventListener("change", function () { refresh(); });
    recipeSel.addEventListener("change", function () { refresh(); });
    el("psNewDate").addEventListener("change", refreshDates);
    /* Save opens the sign dialog, whose Sign is this form's default button:
       Enter in a field must not post the record past the dialog unseen */
    el("psNewForm").addEventListener("keydown", function (e) {
      if (e.key === "Enter" && e.target.tagName !== "TEXTAREA" && e.target.tagName !== "BUTTON") { e.preventDefault(); }
    });
    /* the form is checked before the sign dialog opens: a field left empty
       is shown here, on its own tab, not behind the dialog where Sign would
       do nothing */
    document.addEventListener("click", function (e) {
      var b = e.target.closest && e.target.closest("#psNewSave"), form = el("psNewForm");
      if (!b || form.checkValidity()) { return; }
      e.preventDefault(); e.stopPropagation();
      var bad = form.querySelector(":invalid"), pane = bad && bad.closest(".pfas-pane");
      var tab = pane && el("psNewTabs").querySelector('[data-pane="' + pane.id + '"]');
      if (tab) { tab.click(); }
      form.reportValidity();
    }, true);
    el("psNewFinal").addEventListener("input", scaleAmounts);
    el("psNewBy").value = NS.who || "";

    root.pfasOpenNew = function () {
      if (!el("psNewDate").value) { el("psNewDate").value = newDay(); }
      el("psNew").classList.add("open");
      refresh(param("recipe"));
      /* the pills measured zero while the dialog was closed */
      if (el("psNewTabs") && root.PFAS && PFAS.components) { PFAS.components.placePill(el("psNewTabs")); }
    };
    refresh(param("recipe"));
  }

  if (document.readyState === "loading") { document.addEventListener("DOMContentLoaded", init); } else { init(); }
})(typeof window !== "undefined" ? window : this);
