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
  var SERIES = 6;

  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function num(v) {
    if (v == null || v === "") { return "—"; }
    if (typeof v === "number") { return Math.abs(v) >= 100 ? v.toFixed(1) : (Math.abs(v) >= 1 ? v.toPrecision(4) : v.toPrecision(3)).replace(/\.?0+$/, ""); }
    return String(v);
  }
  function colour(i) { return "var(--series-" + ((i % SERIES) + 1) + ")"; }
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

  function formulaHtml(formula, terms) {
    var text = esc(formula || "");
    var order = terms.map(function (t, i) { return { s: t.symbol, i: i }; })
      .filter(function (x) { return x.s; })
      .sort(function (a, b) { return b.s.length - a.s.length; });
    // replace longest symbols first; a placeholder keeps a symbol inside another from matching twice
    var marks = [];
    order.forEach(function (x) {
      var sym = esc(x.s);
      var idx = text.indexOf(sym);
      while (idx >= 0) {
        var ph = "\u0001" + marks.length + "\u0002";
        marks.push('<span class="pv-term" data-term="' + x.i + '" style="color:' + colour(x.i) + '">' + sym + "</span>");
        text = text.slice(0, idx) + ph + text.slice(idx + sym.length);
        idx = text.indexOf(sym);
      }
    });
    return text.replace(/\u0001(\d+)\u0002/g, function (_m, n) { return marks[+n]; });
  }

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
    h += '<div class="pv-formula">' + formulaHtml(r.formula, terms) + "</div>";
    if (rule.text) { h += '<p class="pv-rule">' + esc(rule.text) + "</p>"; }
    if (rule.lo != null || rule.hi != null) { h += '<p class="pv-rule">Window ' + esc(num(rule.lo)) + " – " + esc(num(rule.hi)) + (rule.basis ? " · " + esc(rule.basis) : "") + "</p>"; }
    h += '<table class="pfas-table pv-terms" data-col-resize="pv-terms"><thead><tr><th></th><th>Term</th><th>Means</th><th class="num">Value</th><th>Source</th></tr></thead><tbody>';
    terms.forEach(function (t, i) {
      var src = t.source || {}, link = "";
      if (src.record) { link = ' <button type="button" class="btn-sm btn-secondary pv-open" data-prov="' + esc(src.record) + '">Open</button>'; }
      h += '<tr class="pv-term-row" data-term="' + i + '"><td><span class="pv-dot" style="background:' + colour(i) + '"></span></td>' +
        '<td class="pv-sym" style="color:' + colour(i) + '">' + esc(t.symbol) + "</td><td>" + esc(t.label) + "</td>" +
        '<td class="num">' + esc(num(t.value)) + (t.unit ? " " + esc(t.unit) : "") + "</td><td>" + esc(sourceText(src)) + link + "</td></tr>";
    });
    h += "</tbody></table>";
    if (steps.length) {
      h += '<h3 class="pv-h">Step by step</h3><ol class="pv-steps">';
      steps.forEach(function (s) { h += "<li><span>" + esc(s.label) + '</span><code>' + esc(s.expression) + "</code><b>" + esc(num(s.value)) + "</b></li>"; });
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

  function linkHover(root) {
    root.addEventListener("mouseover", function (e) {
      var el = e.target.closest("[data-term]");
      if (!el) { return; }
      var i = el.getAttribute("data-term");
      var all = root.querySelectorAll("[data-term]");
      for (var k = 0; k < all.length; k++) { all[k].classList.toggle("pv-hot", all[k].getAttribute("data-term") === i); }
    });
    root.addEventListener("mouseout", function (e) {
      if (e.target.closest("[data-term]")) {
        var all = root.querySelectorAll(".pv-hot");
        for (var k = 0; k < all.length; k++) { all[k].classList.remove("pv-hot"); }
      }
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
      })
      .catch(function (err) { d.open("Where does this number come from?", '<p class="pv-rule">The record could not be loaded (' + esc(err) + ").</p>", { cls: "is-dialog" }); });
  }

  if (doc) {
    doc.addEventListener("click", function (e) {
      var el = e.target.closest("[data-prov]");
      if (!el) { return; }
      e.preventDefault();
      open(el.getAttribute("data-prov"));
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
  var api = { open: open, render: render, formulaHtml: formulaHtml, lineBlock: lineBlock };
  if (typeof window !== "undefined") { window.PFAS = window.PFAS || {}; window.PFAS.provenance = api; }
  if (typeof module !== "undefined" && module.exports) { module.exports = api; }
})();
