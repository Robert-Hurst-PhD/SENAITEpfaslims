/* provenance.js — "Where does this number come from?"
 * Any element with data-prov="<key>" opens the value's record in the shared
 * drawer (pfas-components.js): the formula with each term coloured, the terms
 * with their sources, the steps of a chain, the rule and verdict, and below
 * them the imported rows and the export lines the terms were read from, the
 * cited cells lit in the term's colour. Hover a term anywhere and it lights
 * everywhere (Head, Xie and Hearst, CHI 2022: colour as the visual link).
 * Deep link: #prov=<key>. Plain ES5, no library. */
(function () {
  "use strict";
  var doc = typeof document !== "undefined" ? document : null;   /* node: the pure helpers only */
  var KINDS = { IS: "Isotope standard response", RT: "Retention time", ION: "Ion ratio",
    CAL: "Calibration point", CCV: "Continuing calibration verification", ICV: "Initial calibration verification",
    SUR: "Surrogate recovery", LFSM: "Matrix spike recovery", LFSMD: "Matrix spike duplicate RPD",
    LFSMD_REC: "Matrix spike duplicate recovery", BLANK: "Blank", LFB: "Fortified blank recovery",
    LCS: "Laboratory control sample recovery", DUP: "Duplicate RPD", RESULT: "Reported result", RUN: "Run file" };

  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function num(v) {
    if (v == null || v === "") { return "—"; }
    if (typeof v === "number") { return Math.abs(v) >= 100 ? v.toFixed(1) : (Math.abs(v) >= 1 ? v.toPrecision(4) : v.toPrecision(3)).replace(/\.?0+$/, ""); }
    return String(v);
  }
  function colour(i) { return eqApi().colour(i); }
  function batchId() {
    var m = doc.querySelector('meta[name="pfas-batch-id"]');
    return (m && m.getAttribute("content")) || "";
  }
  function endpoint() {
    var m = doc.querySelector('meta[name="pfas-provenance-url"]');
    return (m && m.getAttribute("content")) || "@@pfas-provenance";
  }

  function sourceText(s) {
    if (!s) { return ""; }
    if (s.peak) { return s.file + ": " + s.peak; }
    if (s.file) { return s.file + " line " + s.line + (s.column ? ", " + s.column : ""); }
    if (s.rows) { return s.rows.length + " calibrator rows" + (s.column ? " (" + s.column + ")" : ""); }
    if (s.profile !== undefined) { return "method profile: " + s.key + (s.label ? " (" + s.label + ")" : ""); }
    if (s.extraction) { return "extraction record: " + s.extraction; }
    if (s.record) { return "recorded value " + s.record; }
    if (s.computed) { return "computed here"; }
    return "";
  }

  /* The one drawing of an equation is the shared component's
     (pfas-components.js, PFAS.equation): read when used, so the order the
     two scripts load in does not matter; in node, required beside this file. */
  function eqApi() {
    if (typeof window !== "undefined" && window.PFAS && window.PFAS.equation) { return window.PFAS.equation; }
    return require("./pfas-components.js").equation;
  }
  function formulaHtml(formula, terms) { return eqApi().html(formula, terms); }

  /* the equation with each term coloured: the one drawing of a formula, used
     by the value drawer, a column's card and the salt factor calculator */
  function formulaBlock(formula, terms) { return eqApi().block(formula, terms); }

  /* one block per imported line: the line's heading, the row's filled
     fields only (the cited term's cell outlined in its colour), and one line on
     what was stored with the run -- "as read", or what differs from the file. */
  function same(a, b) {
    var x = parseFloat(a), y = parseFloat(b);
    if (isNaN(x) || isNaN(y)) { return String(a == null ? "" : a).trim() === String(b == null ? "" : b).trim(); }
    return Math.abs(x - y) <= 1e-9 * Math.max(1, Math.abs(x), Math.abs(y));
  }
  function when(t) { return String(t || "").replace("T", " ").slice(0, 16); }
  function storedLine(row, f, cells) {
    if (!row) { return '<p class="pv-stored">Not stored with the run.</p>'; }
    var cols = (f && f.columns) || {}, parts = [], diff = false;
    [["calc_conc", "reported"], ["rt", "RT"]].forEach(function (p) {
      var v = row[p[0]], col = cols[p[0]], fv = cells && col != null ? cells[col] : null, txt = p[1] + " " + num(v);
      if (fv != null && !same(v, fv)) { diff = true; txt += " (the file reads " + fv + ")"; }
      parts.push(txt);
    });
    return '<p class="pv-stored">' + (diff ? "Stored with the run: " : "Stored with the run as read: ") +
      esc(parts.join(", ")) + ".</p>";
  }
  function lineBlock(f, ln, terms, rows) {
    var hot = {};
    (terms || []).forEach(function (t, i) {
      var srcs = [t.source || {}].concat((t.source && t.source.rows) || []);
      srcs.forEach(function (s) {
        if (s.file === f.file && +s.line === +ln.line) {
          var col = f.columns && f.columns[s.column];
          hot[col == null ? "*" : col] = i;
        }
      });
    });
    var row = (rows || []).filter(function (r) { return r.source_file === f.file && +r.source_row === +ln.line; })[0];
    var head = [f.file, "line " + ln.line].concat(row ? [row.injection_name, row.analyte, when(row.acquired_at)] : [])
      .filter(function (x) { return x; });
    var h = '<section class="pv-line"><h3 class="pv-h">' + esc(head.join(" \u00b7 ")) + '</h3><dl class="pv-grid">';
    (ln.cells || []).forEach(function (c, ci) {
      if (String(c == null ? "" : c).trim() === "") { return; }
      var ti = hot[ci] != null ? hot[ci] : hot["*"];
      h += ti == null ? '<div class="pv-f">' :
        '<div class="pv-f is-term" data-term="' + ti + '" style="box-shadow:inset 0 0 0 2px ' + colour(ti) + '">';
      h += "<dt>" + esc((f.header || [])[ci] || "column " + (ci + 1)) + "</dt><dd>" + esc(c) + "</dd></div>";
    });
    return h + "</dl>" + storedLine(row, f, ln.cells) + "</section>";
  }

  function render(b) {
    var r = b.record, terms = r.terms || [], steps = r.steps || [], rule = r.rule || {};
    var title = (KINDS[r.kind] || r.kind) + " — " + r.analyte + (r.injection ? " · " + r.injection.split("|")[0] : "");
    var badge = r.verdict === "within" ? "badge-active" : r.verdict === "outside" ? "badge-expired" : "badge-archived";
    var h = '<div class="pv-head"><span class="pv-value">' + esc(num(r.value_text || r.value)) + (r.unit ? ' <small>' + esc(r.unit) + "</small>" : "") + "</span>" +
      '<span class="badge ' + badge + '">' + esc(r.verdict || "recorded") + "</span></div>";
    h += formulaBlock(r.formula, terms);
    if (rule.text) { h += '<p class="pv-rule">' + esc(rule.text) + "</p>"; }
    if (rule.lo != null || rule.hi != null) { h += '<p class="pv-rule">Window ' + esc(num(rule.lo)) + " – " + esc(num(rule.hi)) + (rule.basis ? " · " + esc(rule.basis) : "") + "</p>"; }
    h += '<table class="pfas-table pv-terms" data-col-resize="pv-terms"><thead><tr><th></th><th>Term</th><th>Means</th><th class="num">Value</th><th>Source</th></tr></thead><tbody>';
    /* a term with a record of its own: the whole row opens it (data-prov),
       and its menu says so; no button stands in the row */
    var opens = JSON.stringify([{ label: "Open its record", event: "pv-open" }]);
    terms.forEach(function (t, i) {
      var src = t.source || {}, rec = "";
      if (src.record) { rec = ' data-prov="' + esc(src.record) + '" tabindex="0" data-row-actions="' + esc(opens) + '"'; }
      h += '<tr class="pv-term-row" data-term="' + i + '"' + rec + '><td><span class="pv-dot" style="background:' + colour(i) + '"></span></td>' +
        '<td class="pv-sym" style="color:' + colour(i) + '">' + esc(t.symbol) + "</td><td>" + esc(t.label) + "</td>" +
        '<td class="num">' + esc(num(t.value)) + (t.unit ? " " + esc(t.unit) : "") + "</td><td>" + esc(sourceText(src)) + "</td></tr>";
    });
    h += "</tbody></table>";
    if (steps.length) {
      h += '<h3 class="pv-h">Step by step</h3><ol class="pv-steps">';
      steps.forEach(function (s) {
        h += "<li><span>" + esc(s.label) + '</span><span class="pv-step-eq">' + formulaHtml(s.expression, terms) +
          "</span><b>" + esc(num(s.value)) + "</b></li>";
      });
      h += "</ol>";
    }
    if (rule.qualifier || (rule.flags && rule.flags.length)) {
      h += '<p class="pv-rule">Qualifier: ' + esc(rule.qualifier || "none") + (rule.flags && rule.flags.length ? " · flags: " + esc(rule.flags.join(", ")) : "") + "</p>";
    }
    var shown = {};
    (b.files || []).forEach(function (f) {
      if (f.missing) {
        h += '<h3 class="pv-h">' + esc(f.file) + '</h3><p class="pv-rule">The file is no longer in the import folder; lines ' +
          esc(f.lines.join(", ")) + " were read.</p>";
        return;
      }
      (f.lines || []).forEach(function (ln) { shown[f.file + ":" + ln.line] = true; h += lineBlock(f, ln, terms, b.rows); });
    });
    /* a stored row whose file line is not drawn above: what was stored, said once */
    (b.rows || []).forEach(function (x) {
      if (shown[x.source_file + ":" + x.source_row]) { return; }
      var head = [x.injection_name, x.analyte, when(x.acquired_at)].filter(function (v) { return v; });
      h += '<section class="pv-line"><h3 class="pv-h">' + esc(head.join(" \u00b7 ")) + "</h3>" + storedLine(x, null, null) + "</section>";
    });
    return { title: title, html: h };
  }

  function linkHover(root) { eqApi().hover(root); }

  /* A column header holding data-eq='{"formula":..,"terms":[{"symbol","label"}]}'
     shows how the column is worked out on hover or focus: the equation, then
     each term with what it means, lit together as in the drawer. */
  function equationCard(formula, terms) {
    var h = formulaBlock(formula, terms) + '<ul class="pv-card-terms">';
    terms.forEach(function (t, i) {
      h += '<li data-term="' + i + '"><span class="pv-dot" style="background:' + colour(i) + '"></span> ' +
        '<span class="pv-sym" style="color:' + colour(i) + '">' + esc(t.symbol) + "</span> " + esc(t.label) + "</li>";
    });
    return h + "</ul>";
  }
  function wireCards() {
    var card = null, owner = null;
    function hide() {
      if (card) { card.parentNode.removeChild(card); card = null; }
      if (owner) { owner.removeAttribute("aria-describedby"); owner = null; }
    }
    function show(th) {
      if (owner === th) { return; }
      hide();
      var eq;
      try { eq = JSON.parse(th.getAttribute("data-eq")); } catch (e) { return; }
      card = doc.createElement("div");
      card.className = "pv-card";
      card.id = "pv-card";
      card.setAttribute("role", "tooltip");
      card.innerHTML = equationCard(eq.formula, eq.terms || []);
      linkHover(card);
      th.appendChild(card);
      /* fixed, set from the header's box: a scrolling table wrapper never clips it */
      var box = th.getBoundingClientRect(), w = card.offsetWidth;
      card.style.top = box.bottom + "px";
      card.style.left = Math.max(8, Math.min(box.right - w, window.innerWidth - w - 8)) + "px";
      owner = th;
      th.setAttribute("aria-describedby", "pv-card");
    }
    doc.addEventListener("mouseover", function (e) {
      var th = e.target.closest && e.target.closest("[data-eq]");
      if (th) { show(th); } else if (card && !card.contains(e.target)) { hide(); }
    });
    doc.addEventListener("focusin", function (e) {
      var th = e.target.closest && e.target.closest("[data-eq]");
      if (th) { show(th); } else { hide(); }
    });
    doc.addEventListener("focusout", function (e) { if (e.target === owner) { hide(); } });
    doc.addEventListener("keydown", function (e) { if (e.key === "Escape") { hide(); } });
    /* a click (or Enter) on the header opens the same content in the shared centred dialog */
    function openFull(th) {
      var d = window.PFAS && window.PFAS.components && window.PFAS.components.drawer, eq;
      if (!d) { return; }
      try { eq = JSON.parse(th.getAttribute("data-eq")); } catch (e) { return; }
      hide();
      var title = "", n;
      for (n = th.firstChild; n && !title; n = n.nextSibling) {
        if (n.nodeType === 3) { title = n.nodeValue.replace(/\s+/g, " ").trim(); }
      }
      d.open(title || "How it is worked out", equationCard(eq.formula, eq.terms || []), { cls: "is-dialog" });
      var body = d.el && d.el.querySelector(".pfas-drawer-body");
      if (body) { linkHover(body); }
    }
    doc.addEventListener("click", function (e) {
      var th = e.target.closest && e.target.closest("[data-eq]");
      if (th) { openFull(th); }
    });
    doc.addEventListener("keydown", function (e) {
      if (e.key !== "Enter" && e.key !== " ") { return; }
      var th = doc.activeElement && doc.activeElement.closest && doc.activeElement.closest("[data-eq]");
      if (th && doc.activeElement === th) { e.preventDefault(); openFull(th); }
    });
  }

  function open(key) {
    var d = window.PFAS && window.PFAS.components && window.PFAS.components.drawer;
    if (!d) { return; }
    d.open("Where does this number come from?", '<p class="pv-rule">Loading ' + esc(key) + "…</p>", { cls: "is-dialog" });
    try { history.replaceState(null, "", "#prov=" + encodeURIComponent(key)); } catch (e) {}
    var url = endpoint() + "?batch_id=" + encodeURIComponent(batchId()) + "&key=" + encodeURIComponent(key);
    fetch(url, { credentials: "same-origin", headers: { "Accept": "application/json" } })
      .then(function (r) { return r.json(); })
      .then(function (b) {
        if (b.error) { d.open("Where does this number come from?", '<p class="pv-rule">' + esc(b.error) + "</p>", { cls: "is-dialog" }); return; }
        var out = render(b);
        d.open(out.title, out.html, { cls: "is-dialog" });
        var body = d.el.querySelector(".pfas-drawer-body");
        linkHover(body);
        var comps = window.PFAS && window.PFAS.components;
        if (body && comps && comps.rows) { comps.rows.init(body); }
      })
      .catch(function (err) { d.open("Where does this number come from?", '<p class="pv-rule">The record could not be loaded (' + esc(err) + ").</p>", { cls: "is-dialog" }); });
  }

  if (doc) {
    wireCards();
    doc.addEventListener("click", function (e) {
      if (e.target.closest(".pfas-rowmenu")) { return; }   /* a term row's dots open its menu, not the record */
      var el = e.target.closest("[data-prov]");
      if (!el) { return; }
      e.preventDefault();
      open(el.getAttribute("data-prov"));
    });
    /* a term row's menu: Open its record */
    doc.addEventListener("pfas:row-action", function (e) {
      var row = e.detail && e.detail.row;
      if (!row || e.detail.name !== "pv-open" || !row.getAttribute("data-prov")) { return; }
      open(row.getAttribute("data-prov"));
    });
    doc.addEventListener("keydown", function (e) {
      if (e.key !== "Enter" && e.key !== " ") { return; }
      var el = doc.activeElement && doc.activeElement.closest && doc.activeElement.closest("[data-prov]");
      if (!el) { return; }
      e.preventDefault();
      open(el.getAttribute("data-prov"));
    });
    var fromHash = function () {
      var m = /[#&]prov=([^&]+)/.exec(location.hash || "");
      if (m) { open(decodeURIComponent(m[1])); }
    };
    if (doc.readyState === "loading") { doc.addEventListener("DOMContentLoaded", fromHash); } else { fromHash(); }
  }
  var api = { open: open, render: render, formulaHtml: formulaHtml, formulaBlock: formulaBlock, equationCard: equationCard, lineBlock: lineBlock };
  if (typeof window !== "undefined") { window.PFAS = window.PFAS || {}; window.PFAS.provenance = api; }
  if (typeof module !== "undefined" && module.exports) { module.exports = api; }
})();
