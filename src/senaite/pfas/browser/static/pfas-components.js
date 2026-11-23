/* pfas-components.js — behaviour for the shared components (pfas-components.css).
 * Loaded by the page macro and the core overlay viewlet. Plain ES5, no library.
 *   - theme: html[data-theme] from localStorage ("pfas_theme"); light unless the
 *     person chose dark (light is the lab's default)
 *   - .pfas-seg: (data-quiet: no pfas:seg event) the pill follows the active item; click switches items and
 *     panes ([data-tabs] root, data-pane ids); arrow keys move between tabs
 *   - .pfas-fab: open / close, scrim and Escape
 *   - .pfas-drawer: open(html) / close, scrim and Escape, #hash deep link hook
 *   - .btn-help[data-help-entry]: opens that Help entry in .pfas-help-panel beside the page
 *     (not modal); Close or Escape in the panel hides it and focuses the button again
 *   - .pfas-tree[data-view]: "path" hides rows marked is-off-path
 *   - .pfas-hier (PFAS.components.hier): a node shows its card; .pfas-band bars; a view
 *     switch ([data-view-switch]); a card's tiles open its windows (PFAS.components.tiles)
 *   - .pfas-tree.pfas-nav-tree: the navigation tree (ARIA tree, keys, row menu, pfas:pin event)
 *   - form[data-autosubmit]: a filter bar that submits when any field changes
 *   - [data-unsaved-for]: the pinned bar's line says when the form it names holds
 *     a change not saved yet
 *   - .pfas-num: [-] value [+] around every number input in the content area (not
 *     read-only, .no-stepper, [data-stepper=off], or in a table cell); hold repeats
 *   - .pfas-range: [data-range] around a min / max pair of number inputs, drawn as a
 *     two-handle slider that also takes typed digits (data-scale="lo,hi", data-unit)
 *   - grid cells: a td with one number input (or a declared td[data-pair] pair) shows a
 *     value button that opens the drawer with the full stepper or range; a table opts
 *     out with data-cells="plain"
 *   - .pfas-chips: input[data-chips] ("pairs" for A=B) drawn as chips; data-options
 *     is JSON [[value, label], ...] and limits what can be added
 *   - .pfas-picker[data-name][data-options]: a search box adding tokens with a cross;
 *     the chosen list is JSON in ONE hidden field named data-name (inside the picker,
 *     or a collection row's); .pfas-picker-lists keeps one picker per row with it
 *   - .pfas-sheet (PFAS.components.sheet): the selection bar, column switches, a links
 *     cell's list, Columns, a row's expand button and the row drawer on the grid
 *     profile_grids.py draws;
 *     events pfas:sheet-select and pfas:sheet-bulk
 *   - an equation (PFAS.equation draws, PFAS.components.equation wires): [data-equation]
 *     drawn over the server's plain text; [data-equation-open] opens its read-only window
 *     of options side by side, the one in use marked, every term defined
 *   - .pfas-menu (PFAS.components.menu): a context menu or an Actions button's list, one at
 *     a time over everything, with groups, disabled entries saying why, submenus and keys
 * All of these ENHANCE markup that already exists: the real named input stays in the
 * DOM and is the posted field, nothing is written on init, and content added later
 * (grids drawn by a script) is picked up by the observer in watchTables.
 * Pure helpers (PFAS.numeric: step, bump, clamp, lists, pairs) come first and touch no DOM.
 * Nothing cycles on its own; motion is CSS and honours reduced motion.
 */
/* Pure helpers: no DOM, so node can test them (tests/js/numeric_test.js). */
(function (g) {
  "use strict";
  function isNum(x) { return typeof x === "number" && isFinite(x); }
  function toNum(x) {
    if (isNum(x)) { return x; }
    if (x === null || x === undefined) { return NaN; }
    var s = String(x).replace(/^\s+|\s+$/g, "");
    if (s === "") { return NaN; }
    var n = Number(s);
    return isFinite(n) ? n : NaN;
  }
  /* decimals("0.50") = 2, decimals(0.125) = 3, decimals("1e-7") = 7 */
  function decimals(x) {
    var s = typeof x === "string" ? x.replace(/^\s+|\s+$/g, "") : (isNum(x) ? String(x) : "");
    if (!s || !isFinite(Number(s))) { return 0; }
    var m = /^[+-]?\d*(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/.exec(s);
    if (!m) { return 0; }
    var frac = (m[1] || "").length, exp = m[2] ? parseInt(m[2], 10) : 0;
    return Math.max(0, frac - exp);
  }
  function roundTo(x, dec) {
    var n = toNum(x);
    if (!isNum(n)) { return NaN; }
    dec = Math.max(0, Math.min(15, dec | 0));
    var r;
    if (/e/i.test(String(n))) { r = Number(n.toFixed(dec)); }
    else { r = Number(Math.round(Number(n + "e" + dec)) + "e-" + dec); }
    return r === 0 ? 0 : r;
  }
  function clamp(x, min, max) {
    var n = toNum(x), lo = toNum(min), hi = toNum(max);
    if (!isNum(n)) { return n; }
    if (isNum(lo) && n < lo) { n = lo; }
    if (isNum(hi) && n > hi) { n = hi; }
    return n;
  }
  /* The step a stepper takes: the numeric step; for "any" (or none) data-step,
     else the decimals of the value or placeholder, else 1. */
  function stepOf(o) {
    o = o || {};
    var s = toNum(o.step);
    if (isNum(s) && s > 0) { return s; }
    var d = toNum(o.dataStep);
    if (isNum(d) && d > 0) { return d; }
    var src = isNum(toNum(o.value)) ? o.value : (isNum(toNum(o.placeholder)) ? o.placeholder : null);
    var dec = src === null ? 0 : decimals(src);
    return dec > 0 ? roundTo(Math.pow(10, -dec), dec) : 1;
  }
  /* One press: value + dir * step, rounded to the step's decimals (or the
     value's own, when it has more), then clamped. An empty value starts at min, else 0. */
  function bump(value, dir, step, min, max) {
    var v = toNum(value), lo = toNum(min), st = toNum(step);
    if (!(st > 0)) { st = 1; }
    var out;
    if (!isNum(v)) { out = isNum(lo) ? lo : 0; }
    else { out = roundTo(v + (dir < 0 ? -st : st), Math.max(decimals(st), decimals(value))); }
    return clamp(out, min, max);
  }
  /* What a press acts on: the box's value, or, while the box is empty, the
     number it resolves to (data-resolved), the number the person sees. */
  function startFrom(value, resolved) {
    var empty = value === "" || value === null || value === undefined;
    return empty && isNum(toNum(resolved)) ? String(resolved) : value;
  }
  /* A pair's thumbs cannot cross: which is "lo" or "hi", other is the
     opposite end's value (empty = no limit). */
  function pairClamp(which, v, other) {
    var n = toNum(v), o = toNum(other);
    if (!isNum(n) || !isNum(o)) { return n; }
    return which === "lo" ? Math.min(n, o) : Math.max(n, o);
  }
  function parseScale(s) {
    var p = String(s === null || s === undefined ? "" : s).split(",");
    var a = toNum(p[0]), b = toNum(p[1]);
    return isNum(a) && isNum(b) && b > a ? [a, b] : null;
  }
  /* A typed value outside the scale widens it; the scale never narrows below base. */
  function scaleFor(base, lo, hi) {
    var a = base[0], b = base[1], vs = [toNum(lo), toNum(hi)];
    for (var i = 0; i < vs.length; i++) {
      if (isNum(vs[i])) { a = Math.min(a, vs[i]); b = Math.max(b, vs[i]); }
    }
    return [a, b];
  }
  function fraction(v, a, b) {
    var n = toNum(v);
    if (!isNum(n) || !(b > a)) { return 0; }
    return Math.max(0, Math.min(1, (n - a) / (b - a)));
  }
  /* Lists typed as text, as the server reads them (method_engine._names):
     split on "," or ";", trimmed, blanks dropped, repeats dropped. */
  function parseList(s) {
    var items = String(s === null || s === undefined ? "" : s).replace(/;/g, ",").split(","), out = [];
    for (var i = 0; i < items.length; i++) {
      var x = items[i].replace(/^\s+|\s+$/g, "");
      if (x && out.indexOf(x) < 0) { out.push(x); }
    }
    return out;
  }
  function joinList(arr) { return (arr || []).join(", "); }
  /* "OPR=LFB, IPR=LFB" as [[from, to], ...], sorted by the left side: the
     server keeps a dict and writes it sorted (method_profile_sections._as_text). */
  function parsePairs(s) {
    var items = parseList(s), map = {}, keys = [];
    for (var i = 0; i < items.length; i++) {
      var at = items[i].indexOf("=");
      if (at < 0) { continue; }
      var a = items[i].slice(0, at).replace(/^\s+|\s+$/g, ""), b = items[i].slice(at + 1).replace(/^\s+|\s+$/g, "");
      if (!a || !b) { continue; }
      if (!Object.prototype.hasOwnProperty.call(map, a)) { keys.push(a); }
      map[a] = b;
    }
    keys.sort();
    return keys.map(function (k) { return [k, map[k]]; });
  }
  function joinPairs(arr) {
    var rows = (arr || []).filter(function (p) { return p && p[0] && p[1]; }).slice();
    rows.sort(function (x, y) { return x[0] < y[0] ? -1 : (x[0] > y[0] ? 1 : 0); });
    return rows.map(function (p) { return p[0] + "=" + p[1]; }).join(", ");
  }
  /* run fn again once the page has settled: on window load and when the web
   * fonts are ready, either of which changes the width of a tab (tests/js/seg_test.js) */
  function whenSettled(win, d, fn) {
    win.addEventListener("load", function () { fn(); });
    if (d && d.fonts && d.fonts.ready && d.fonts.ready.then) { d.fonts.ready.then(function () { fn(); }); }
  }
  /* the shared multi-select (pfas-multi): the field stays one line -- the
   * first two chosen as tags, then "+N more" (tests/js/multi_test.js) */
  function multiSummary(labels) {
    labels = labels || [];
    return { tags: labels.slice(0, 2), more: Math.max(0, labels.length - 2) };
  }
  /* what is not chosen, in its usual order, matching the search (any case) */
  function multiFilter(items, query, chosen) {
    var q = String(query || "").toLowerCase();
    return (items || []).filter(function (i) {
      return (chosen || []).indexOf(i.v) === -1 && (!q || String(i.t).toLowerCase().indexOf(q) !== -1);
    });
  }
  function multiFooter(nChosen, nRest, noun) {
    return nChosen + " chosen \u00b7 " + nRest + " more" + (noun ? " " + noun : "");
  }
  /* a grid cell's text: its value, else what blank means for it (its
     placeholder, an inherited value), else nothing: an unset box is empty,
     never a word. A value of none is a chosen state, drawn as a dash. */
  function cellText(value, placeholder, isNone) {
    if (value === "" || value === null || value === undefined) { return isNone ? "\u2014" : (placeholder || ""); }
    return value;
  }
  var numeric = {
    cellText: cellText, toNum: toNum, decimals: decimals, roundTo: roundTo, clamp: clamp, stepOf: stepOf, bump: bump,
    startFrom: startFrom,
    pairClamp: pairClamp, parseScale: parseScale, scaleFor: scaleFor, fraction: fraction,
    parseList: parseList, joinList: joinList, parsePairs: parsePairs, joinPairs: joinPairs,
    whenSettled: whenSettled, multiSummary: multiSummary, multiFilter: multiFilter, multiFooter: multiFooter
  };
  g.PFAS = g.PFAS || {};
  g.PFAS.numeric = numeric;
  if (typeof module !== "undefined" && module.exports) { module.exports = numeric; }
})(typeof window !== "undefined" ? window : {});

/* ── The equation (PFAS.equation) ────────────────────────────────────────
   One drawing of an equation, as a method prints it, wherever one is shown:
   the value drawer, a column's card, the method profile's settings and the
   calibration card. A division ("÷", or "/" standing between spaces) is
   a stacked fraction, its numerator over a bar over its denominator; an
   operand in brackets gives its brackets to the bar; a fraction may hold a
   fraction. Each term's symbol is coloured where it stands as a whole word
   (a term keeps its colour wherever it appears; after six the colours start
   again), and "_{x}" is a subscript. Text after the closing "× 100"
   (", of the two concentrations", "(the duplicate ...)") is a note under
   the equation. Three sizes: display (framed, centred: a window, the
   drawer), card (framed, smaller: a column's card) and inline (no frame,
   left aligned: a card's own line, a setting's box). A window holds one or
   more options side by side, the one in use marked, then every term with
   what it means and where its value comes from. Pure strings, no DOM:
   the page part (drawing [data-equation], opening [data-equation-open])
   is PFAS.components.equation. */
(function (g) {
  "use strict";
  var SERIES = 6;
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function colour(i) { return "var(--series-" + ((i % SERIES) + 1) + ")"; }

  var WORD = /[A-Za-z0-9À-ɏ̀-ͯͰ-Ͽ₀-ₜ_]/;
  function lex(text, terms) {
    var syms = terms.map(function (t, i) { return { s: t.symbol, i: i }; })
      .filter(function (x) { return x.s; })
      .sort(function (a, b) { return b.s.length - a.s.length; });
    var out = [], word = "", i = 0;
    function flush() { if (word) { out.push({ k: "atom", text: word }); word = ""; } }
    function whole(at, len) {
      var a = text.charAt(at - 1), b = text.charAt(at + len);
      return !(a && WORD.test(a) && WORD.test(text.charAt(at))) &&
             !(b && WORD.test(b) && WORD.test(text.charAt(at + len - 1)));
    }
    while (i < text.length) {
      var hit = null;
      for (var n = 0; n < syms.length && !hit; n++) {
        if (text.substr(i, syms[n].s.length) === syms[n].s && whole(i, syms[n].s.length)) { hit = syms[n]; }
      }
      var c = text.charAt(i);
      if (hit) {
        flush();
        out.push({ k: "term", text: hit.s, i: hit.i });
        i += hit.s.length;
        continue;
      }
      if (/\s/.test(c)) {
        flush();
        if (!out.length || out[out.length - 1].k !== "sp") { out.push({ k: "sp" }); }
      } else if (c === "(" || c === ")" || c === "|") {
        flush();
        out.push({ k: "punct", text: c });
      } else if (c === "÷" || (c === "/" && /\s/.test(text.charAt(i - 1)) && /\s/.test(text.charAt(i + 1)))) {
        flush();
        out.push({ k: "div" });
      } else {
        word += c;
      }
      i += 1;
    }
    flush();
    return out;
  }
  function trimmed(nodes) {
    var a = 0, b = nodes.length;
    while (a < b && nodes[a].k === "sp") { a++; }
    while (b > a && nodes[b - 1].k === "sp") { b--; }
    return nodes.slice(a, b);
  }
  function operand(node) {
    return node.k === "group" && node.open === "(" && !node.unclosed ? trimmed(node.nodes) : [node];
  }
  function fold(nodes) {
    for (var i = 0; i < nodes.length; i++) {
      if (nodes[i].k !== "div") { continue; }
      var p = i - 1, n = i + 1;
      while (p >= 0 && nodes[p].k === "sp") { p--; }
      while (n < nodes.length && nodes[n].k === "sp") { n++; }
      if (p < 0 || n >= nodes.length || nodes[p].k === "div" || nodes[n].k === "div") { continue; }
      nodes.splice(p, n - p + 1, { k: "frac", num: operand(nodes[p]), den: operand(nodes[n]) });
      i = p;
    }
    return nodes;
  }
  function parse(toks, pos, stop) {
    var nodes = [];
    while (pos < toks.length) {
      var t = toks[pos];
      if (stop && t.k === "punct" && t.text === stop) { return { nodes: fold(nodes), pos: pos + 1, closed: true }; }
      if (t.k === "punct" && (t.text === "(" || t.text === "|")) {
        var close = t.text === "(" ? ")" : "|", inner = parse(toks, pos + 1, close);
        nodes.push({ k: "group", open: t.text, close: close, nodes: inner.nodes, unclosed: !inner.closed });
        pos = inner.pos;
        continue;
      }
      nodes.push(t);
      pos += 1;
    }
    return { nodes: fold(nodes), pos: pos, closed: false };
  }
  function sub(text) { return esc(text).replace(/_\{([^}]*)\}/g, "<sub>$1</sub>"); }
  function draw(nodes) {
    return nodes.map(function (x) {
      if (x.k === "sp") { return " "; }
      if (x.k === "div") { return "÷"; }
      if (x.k === "term") {
        return '<span class="pv-term" data-term="' + x.i + '" style="color:' + colour(x.i) + '">' + sub(x.text) + "</span>";
      }
      if (x.k === "group") { return esc(x.open) + draw(x.nodes) + (x.unclosed ? "" : esc(x.close)); }
      if (x.k === "frac") {
        return '<span class="pv-frac"><span class="pv-num">' + draw(x.num) + '</span><span class="pv-den">' +
          draw(x.den) + "</span></span>";
      }
      return sub(x.text);
    }).join("");
  }
  function split(formula) {
    var m = /^(.*×\s*\d+)(?:,\s*(.+)|\s+\((.+)\))$/.exec(formula || "");
    return m ? { eq: m[1], note: m[2] || m[3] } : { eq: formula || "", note: "" };
  }
  /* the equation's own markup, no frame */
  function html(formula, terms) {
    return draw(trimmed(parse(lex(split(formula).eq, terms || []), 0, null).nodes));
  }
  /* one equation, framed: the display size, or "card" */
  function block(formula, terms, size) {
    var note = split(formula).note;
    return '<div class="pv-formula' + (size ? " is-" + size : "") + '">' + html(formula, terms) +
      (note ? '<div class="pv-formula-note">' + esc(note) + "</div>" : "") + "</div>";
  }
  function list(formulas) { return [].concat(formulas || []).filter(function (f) { return f; }); }
  /* the inline size's content: one line per equation, a middle dot between */
  function lines(formulas, terms) {
    return list(formulas).map(function (f) { return '<span class="pv-formula-line">' + html(f, terms) + "</span>"; }).join("");
  }
  function inline(formulas, terms) { return '<div class="pv-formula is-inline">' + lines(formulas, terms) + "</div>"; }
  /* under an inline equation whose terms are values: what each value is,
     in its colour, then where they come from ("from this fit") */
  function key(terms, tail) {
    return '<span class="pv-formula-key">' + (terms || []).map(function (t, i) {
      return '<span data-term="' + i + '"><span class="pv-dot" style="background:' + colour(i) + '"></span> ' + esc(t.label) + "</span>";
    }).join(" ") + (tail ? " " + esc(tail) : "") + "</span>";
  }
  /* every term: its colour, symbol, what it means, its value (a column only
     when one is known), where the value comes from, and the options it is
     used in (a column only when a window holds more than one option) */
  function termsTable(terms) {
    terms = terms || [];
    var hasValue = terms.some(function (t) { return t.value != null && t.value !== ""; });
    var hasIn = terms.some(function (t) { return t["in"] && t["in"].length; });
    var h = '<table class="pfas-table pv-terms" data-col-resize="pv-terms"><thead><tr><th></th><th>Term</th><th>Means</th>' +
      (hasValue ? '<th class="num">Value</th>' : "") + "<th>Source</th>" + (hasIn ? "<th>Used in</th>" : "") +
      "</tr></thead><tbody>";
    terms.forEach(function (t, i) {
      h += '<tr data-term="' + i + '"><td><span class="pv-dot" style="background:' + colour(i) + '"></span></td>' +
        '<td class="pv-sym" style="color:' + colour(i) + '">' + sub(t.symbol) + "</td><td>" + esc(t.label) + "</td>" +
        (hasValue ? '<td class="num">' + esc(t.value == null ? "" : t.value) + (t.unit ? " " + esc(t.unit) : "") + "</td>" : "") +
        "<td>" + esc(t.source) + "</td>" +
        (hasIn ? '<td class="pv-in">' + esc([].concat(t["in"] || []).join(", ")) + "</td>" : "") + "</tr>";
    });
    return h + "</tbody></table>";
  }
  /* A window's body. spec: {chain: [[label, value]], options: [{value,
     label, note, formulas, isDefault}], terms, steps: [{head, note,
     formulas, alt: {lead, formulas}, terms}], foot}; `inUse` the value of
     the option in use, marked with a solid border and In use. */
  function windowHtml(spec, inUse) {
    spec = spec || {};
    var terms = spec.terms || [], h = "";
    if (spec.chain && spec.chain.length) {
      h += '<p class="pv-chain">' + spec.chain.map(function (c) {
        return '<span><span class="pv-chain-l">' + esc(c[0]) + "</span> <b>" + esc(c[1]) + "</b></span>";
      }).join('<span class="pv-chain-l"> · </span>') + "</p>";
    }
    var opts = spec.options || [];
    if (opts.length) {
      h += '<div class="pv-options">' + opts.map(function (o) {
        var used = inUse != null && String(o.value) === String(inUse);
        return '<section class="pv-option' + (used ? " is-used" : "") + '" data-option="' + esc(o.value) + '"' +
          (used ? ' aria-current="true"' : "") + '><div class="pv-option-head"><span class="pv-option-name">' + esc(o.label) + "</span>" +
          (o.isDefault ? '<span class="pfas-tag">Default</span>' : "") +
          (used ? '<span class="pfas-tag is-used">In use</span>' : "") + "</div>" +
          (o.note ? '<p class="pv-option-note">' + esc(o.note) + "</p>" : "") +
          list(o.formulas).map(function (f) { return block(f, terms); }).join("") + "</section>";
      }).join("") + "</div>";
    }
    if (terms.length) { h += termsTable(terms); }
    (spec.steps || []).forEach(function (s) {
      var st = s.terms || [];
      h += '<h3 class="pv-h">' + esc(s.head) + "</h3>" + (s.note ? '<p class="pv-rule">' + esc(s.note) + "</p>" : "") +
        list(s.formulas).map(function (f) { return block(f, st); }).join("") +
        (s.alt ? '<div class="pv-alt"><span>' + esc(s.alt.lead) + "</span> " + inline(s.alt.formulas, st) + "</div>" : "") +
        (st.length ? termsTable(st) : "");
    });
    if (spec.foot) { h += '<p class="pv-rule">' + esc(spec.foot) + "</p>"; }
    return h;
  }
  /* hover a term anywhere in root and it lights everywhere in root */
  function hover(root) {
    if (!root || root.__pvHover) { return; }
    root.__pvHover = true;
    root.addEventListener("mouseover", function (e) {
      var el = e.target.closest && e.target.closest("[data-term]");
      if (!el) { return; }
      var i = el.getAttribute("data-term");
      var all = root.querySelectorAll("[data-term]");
      for (var k = 0; k < all.length; k++) { all[k].classList.toggle("pv-hot", all[k].getAttribute("data-term") === i); }
    });
    root.addEventListener("mouseout", function (e) {
      if (e.target.closest && e.target.closest("[data-term]")) {
        var all = root.querySelectorAll(".pv-hot");
        for (var k = 0; k < all.length; k++) { all[k].classList.remove("pv-hot"); }
      }
    });
  }
  var equation = { esc: esc, colour: colour, split: split, html: html, block: block, lines: lines, inline: inline,
                   key: key, terms: termsTable, window: windowHtml, hover: hover };
  g.PFAS = g.PFAS || {};
  g.PFAS.equation = equation;
  if (typeof module !== "undefined" && module.exports) { module.exports.equation = equation; }
})(typeof window !== "undefined" ? window : {});

(function () {
  "use strict";
  if (typeof document === "undefined") { return; }   /* node: the helpers above only */
  var doc = document;

  /* theme: applied as early as the script runs, before first paint of the body */
  function theme(set) {
    try {
      if (set) { localStorage.setItem("pfas_theme", set); }
      var t = localStorage.getItem("pfas_theme") || "light";
      if (t === "dark") { doc.documentElement.setAttribute("data-theme", "dark"); }
      else { doc.documentElement.removeAttribute("data-theme"); }
      return t;
    } catch (e) { return "light"; }
  }
  theme();

  function placePill(seg) {
    var on = seg.querySelector('[aria-selected="true"], [aria-pressed="true"], .is-on');
    var pill = seg.querySelector(".pfas-seg-pill");
    if (!on || !pill) { return; }
    /* it moves by transform alone: its new size is taken at once, drawn at
       its old place and width (translateX, scaleX), then slides to the new,
       so nothing is laid out again while it moves; the first placing (where
       the page opens) and a wrapped strip's other row are drawn there, not
       slid in */
    var x = on.offsetLeft, y = on.offsetTop, w = on.offsetWidth || 1, prev = pill.__pfasAt;
    function at(px, sx) { return "translate(" + px + "px, " + y + "px) scaleX(" + sx + ")"; }
    pill.style.left = "0px";
    pill.style.top = "0px";
    pill.style.width = w + "px";
    pill.style.height = on.offsetHeight + "px";      /* a wrapped strip: the row the tab is on */
    pill.style.transition = "none";
    pill.style.transform = prev && prev.y === y ? at(prev.x, prev.w / w) : at(x, 1);
    pill.__pfasAt = { x: x, y: y, w: w };
    void pill.offsetWidth;                           /* the old place is drawn before the slide */
    pill.style.transition = "";
    pill.style.transform = at(x, 1);
    seg.classList.toggle("is-wrapped", seg.offsetHeight > on.offsetHeight + 12);
  }
  /* A tab strip wider than its box wraps onto a second row, so no tab is ever
     out of sight (a smaller screen cut tabs off at the edge); the pill
     follows the current tab's row. Should a strip still be wider than its box
     (one tab longer than the box), it scrolls sideways and says on which side
     more waits: has-more-left / has-more-right (an edge fades). */
  function stripCue(seg) {
    var left = seg.scrollLeft || 0, room = seg.scrollWidth - seg.clientWidth;
    seg.classList.toggle("has-more-left", room > 1 && left > 1);
    seg.classList.toggle("has-more-right", room > 1 && left < room - 1);
  }
  function initStripCue(seg) {
    if (!seg.classList.contains("pfas-seg-strip") || seg.__pfasStrip) { return; }
    seg.__pfasStrip = true;
    var on = seg.querySelector('[aria-selected="true"], [aria-pressed="true"], .is-on');
    if (on && seg.scrollWidth > seg.clientWidth + 1 && on.offsetLeft + on.offsetWidth > seg.clientWidth) {
      seg.scrollLeft = on.offsetLeft + on.offsetWidth - seg.clientWidth + 8;
    }
    seg.addEventListener("scroll", function () { stripCue(seg); });
    window.addEventListener("resize", function () { stripCue(seg); placePill(seg); });
    /* the strip's rows change when its box or its font changes (the web
       font arriving after the first layout): the pill follows */
    if (window.ResizeObserver) {
      try { new window.ResizeObserver(function () { stripCue(seg); placePill(seg); }).observe(seg); } catch (e) {}
    }
    stripCue(seg);
  }
  /* the item drawn pressed, the others not */
  function press(seg, item) {
    var items = seg.querySelectorAll(".pfas-seg-item");
    var attr = item.hasAttribute("aria-pressed") ? "aria-pressed" : "aria-selected";
    for (var i = 0; i < items.length; i++) {
      items[i].setAttribute(attr, "false");
      items[i].classList.remove("is-on");
      if (attr === "aria-selected") { items[i].setAttribute("tabindex", "-1"); }
    }
    item.setAttribute(attr, "true");
    if (attr === "aria-selected") { item.setAttribute("tabindex", "0"); }
    return items;
  }
  /* a pane whose shown view is cards: the cards rise, so the pane does not */
  function drawnCard(pane) {
    var cards = pane.querySelectorAll(".pfas-hier-card:not([hidden])");
    for (var i = 0; i < cards.length; i++) { if (!cards[i].parentNode.closest("[hidden]")) { return true; } }
    return false;
  }
  function activate(seg, item) {
    var items = press(seg, item);
    placePill(seg);
    var pane = item.getAttribute("data-pane");
    if (pane) {
      var root = seg.closest("[data-tabs]");
      if (!root || root === seg) { root = doc; }   /* data-tabs on the strip itself: its panes are elsewhere on the page */
      /* only this strip's own panes: a strip nested in a pane (a table's group tabs) must not close its parent's */
      var mine = {};
      for (var m = 0; m < items.length; m++) { mine[items[m].getAttribute("data-pane")] = true; }
      var panes = root.querySelectorAll(".pfas-pane");
      for (var p = 0; p < panes.length; p++) {
        if (mine[panes[p].id]) {
          var was = panes[p].classList.contains("is-active");
          panes[p].classList.toggle("is-active", panes[p].id === pane);
          if (panes[p].id === pane) {
            placeAll(panes[p]);   /* a strip in a pane hidden until now */
            /* a tab the person chose rises (a deep link's, on load, is
               drawn); a pane of cards leaves the rise to its cards */
            if (!was && seg.__pfasReady && !drawnCard(panes[p])) { arrive(panes[p], "is-arriving"); }
          }
        }
      }
      if (seg.hasAttribute("data-hash")) { try { history.replaceState(null, "", "#" + pane); } catch (e) {} }
    }
    if (seg.hasAttribute("data-quiet")) { return; }   /* a nested strip: it does not tell the page's own listeners */
    seg.dispatchEvent(new CustomEvent("pfas:seg", { bubbles: true, detail: { item: item, value: item.getAttribute("data-value") } }));
  }
  /* a form field drawn as a segment: the hidden input it names is what is
     posted; choosing an item writes its value there and says so (change),
     by click or by key alike */
  function writeField(seg, item) {
    var field = doc.getElementById(seg.getAttribute("data-input") || "");
    if (field) {
      field.value = item.getAttribute("data-value") || "";
      field.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }
  /* segments drawn for one field (a list card's copy of a table row's
     state) show what the field holds, whichever of them wrote it */
  function syncFieldSegs(field) {
    if (!field || !field.id) { return; }
    var segs = doc.querySelectorAll(".pfas-seg[data-field]");
    for (var i = 0; i < segs.length; i++) {
      if (segs[i].getAttribute("data-input") !== field.id) { continue; }
      var items = segs[i].querySelectorAll(".pfas-seg-item");
      for (var k = 0; k < items.length; k++) {
        if (items[k].getAttribute("data-value") === field.value) {
          if (items[k].getAttribute("aria-pressed") !== "true") { press(segs[i], items[k]); placePill(segs[i]); }
          break;
        }
      }
    }
  }
  /* A nameless switch drawn for a form's box (a list card's copy,
     input[data-switch-for] naming the box, data-switch-form its form; the
     copy itself names no form, so it is never posted nor counted): ticking
     it ticks the box, which says so (input, change); the box ticked
     anywhere else ticks every copy of it. */
  function switchBox(copy) {
    var name = copy.getAttribute("data-switch-for"), form = copy.getAttribute("data-switch-form");
    var all = doc.getElementsByName(name);
    for (var i = 0; i < all.length; i++) {
      if (all[i] !== copy && (!form || all[i].getAttribute("form") === form)) { return all[i]; }
    }
    return null;
  }
  /* A switch drawn for a choice field of two values (input[data-switch-input]
     naming the field's id, data-switch-on and data-switch-off the values it
     posts; the switch itself names no form): switched, it writes the
     field's value, which says so (input, change); the field written
     anywhere else moves every such switch of it. */
  function valueSwitches(id) {
    return Array.prototype.filter.call(doc.querySelectorAll("input[data-switch-input]"), function (n) {
      return n.getAttribute("data-switch-input") === id;
    });
  }
  function syncValueSwitch(sw, field) {
    var on = field.value === sw.getAttribute("data-switch-on");
    if (sw.checked !== on) { sw.checked = on; switchWord(sw); }
  }
  doc.addEventListener("change", function (e) {
    var t = e.target;
    if (!t || !t.getAttribute) { return; }
    if (t.type === "checkbox" && t.hasAttribute("data-switch-input")) {
      var field = doc.getElementById(t.getAttribute("data-switch-input"));
      var v = t.getAttribute(t.checked ? "data-switch-on" : "data-switch-off") || "";
      if (field && field.value !== v) {
        field.value = v;
        field.dispatchEvent(new Event("input", { bubbles: true }));
        field.dispatchEvent(new Event("change", { bubbles: true }));
      }
      return;
    }
    if (t.id && t.type !== "checkbox") { valueSwitches(t.id).forEach(function (sw) { syncValueSwitch(sw, t); }); }
  });
  doc.addEventListener("change", function (e) {
    var t = e.target;
    if (!t || !t.getAttribute || t.type !== "checkbox") { return; }
    if (t.hasAttribute("data-switch-input")) { return; }
    if (t.hasAttribute("data-switch-for")) {
      var box = switchBox(t);
      if (box && box.checked !== t.checked) {
        box.checked = t.checked;
        box.dispatchEvent(new Event("input", { bubbles: true }));
        box.dispatchEvent(new Event("change", { bubbles: true }));
      }
      return;
    }
    if (!t.name) { return; }
    var copies = doc.querySelectorAll("input[data-switch-for]");
    for (var i = 0; i < copies.length; i++) {
      if (copies[i].getAttribute("data-switch-for") === t.name && switchBox(copies[i]) === t) { copies[i].checked = t.checked; }
    }
  });
  function initSeg(seg) {
    if (seg.__pfas) { return; }
    seg.__pfas = true;
    if (seg.hasAttribute("data-field") && !doc.__pfasFieldSegs) {
      doc.__pfasFieldSegs = true;
      doc.addEventListener("change", function (e) { syncFieldSegs(e.target); });
    }
    if (!seg.querySelector(".pfas-seg-pill")) {
      var pill = doc.createElement("span"); pill.className = "pfas-seg-pill"; seg.insertBefore(pill, seg.firstChild);
    }
    /* a form field drawn as a segment shows what its field will post: a
       browser that restored the form on reload may hold another state than
       the one drawn pressed (nothing is said: the field is not changed) */
    if (seg.hasAttribute("data-field")) {
      var field = doc.getElementById(seg.getAttribute("data-input") || "");
      var all = seg.querySelectorAll(".pfas-seg-item");
      for (var k = 0; field && k < all.length; k++) {
        if (all[k].getAttribute("data-value") === field.value) {
          if (all[k].getAttribute("aria-pressed") !== "true") { press(seg, all[k]); }
          break;
        }
      }
    }
    /* a deep link (#pane) selects that tab on load */
    if (seg.hasAttribute("data-hash") && location.hash) {
      var want = seg.querySelector('.pfas-seg-item[data-pane="' + location.hash.slice(1) + '"]');
      if (want) { activate(seg, want); }
    }
    seg.__pfasReady = true;
    placePill(seg);
    initStripCue(seg);
    /* a segment built hidden (a drawer's) is measured when it first shows */
    if (window.ResizeObserver && !seg.classList.contains("pfas-seg-strip")) {
      try { new window.ResizeObserver(function () { placePill(seg); }).observe(seg); } catch (e) {}
    }
    seg.addEventListener("click", function (e) {
      var item = e.target.closest(".pfas-seg-item");
      if (!item || item.tagName === "A") { return; }   /* a link: the server renders the state */
      e.preventDefault();
      if (seg.hasAttribute("data-field")) {
        writeField(seg, item);
        activate(seg, item);
        return;
      }
      if (item.hasAttribute("data-submit")) {
        /* a form value: the seg's data-name names the hidden input; the form applies */
        var form = seg.closest("form"), name = seg.getAttribute("data-name");
        var input = form && name ? form.querySelector('input[name="' + name + '"]') : null;
        if (input) { input.value = item.getAttribute("data-value") || ""; }
        activate(seg, item);
        if (form) { form.submit(); }
        return;
      }
      activate(seg, item);
    });
    seg.addEventListener("keydown", function (e) {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") { return; }
      var items = Array.prototype.slice.call(seg.querySelectorAll(".pfas-seg-item")).filter(function (x) { return !x.disabled; });
      var i = items.indexOf(doc.activeElement);
      if (i < 0) { return; }
      var next = items[(i + (e.key === "ArrowRight" ? 1 : items.length - 1)) % items.length];
      next.focus();
      /* a form field moved to by the keyboard posts what it shows, as a click does */
      if (next.tagName !== "A") {
        if (seg.hasAttribute("data-field")) { writeField(seg, next); }
        activate(seg, next);
      }
      e.preventDefault();
    });
  }

  function initFab(fab) {
    if (fab.__pfas) { return; }
    fab.__pfas = true;
    var main = fab.querySelector(".pfas-fab-main");
    var scrim = fab.nextElementSibling && fab.nextElementSibling.classList.contains("pfas-fab-scrim") ? fab.nextElementSibling : null;
    function set(open) { fab.setAttribute("data-open", open ? "true" : "false"); if (main) { main.setAttribute("aria-expanded", open ? "true" : "false"); } }
    if (main) { main.addEventListener("click", function () { set(fab.getAttribute("data-open") !== "true"); }); }
    if (scrim) { scrim.addEventListener("click", function () { set(false); }); }
    doc.addEventListener("keydown", function (e) { if (e.key === "Escape") { set(false); } });
  }

  /* Something that leaves (a menu, a popover, the help panel, an old
     placard) is closed at once in every way that counts; then it plays its
     leaving animation (class cls) and only then does done remove or hide
     it. With no animation to play (reduced motion zeroes the tokens; a
     browser without getAnimations) done runs at once, so whatever reads the
     page straight after a close finds it closed. While it leaves it takes
     no pointer and is hidden from assistive technology; stay() cancels it. */
  function leave(node, cls, done) {
    stay(node, cls);
    var anims = [];
    if (node.getAnimations && node.isConnected !== false) {
      node.classList.add(cls);
      anims = node.getAnimations().filter(function (a) {
        var t = a.effect && a.effect.getComputedTiming ? a.effect.getComputedTiming() : null;
        return a.animationName && t && t.endTime > 0;
      });
    }
    if (!anims.length) { done(); node.classList.remove(cls); return; }
    var token = {};
    node.__pfasLeave = token;
    if (!node.hasAttribute("aria-hidden")) { node.setAttribute("aria-hidden", "true"); node.__pfasLeaveAria = true; }
    function end() {
      if (node.__pfasLeave !== token) { return; }
      stay(node, cls);
      done();
    }
    anims[0].finished.then(end, end);
  }
  function stay(node, cls) {
    node.__pfasLeave = null;
    if (node.__pfasLeaveAria) { node.removeAttribute("aria-hidden"); node.__pfasLeaveAria = false; }
    if (node.classList) { node.classList.remove(cls); }
  }
  /* something arriving plays its arriving animation (class cls) again from
     the start; the class goes once it has played */
  function arrive(node, cls) {
    if (!node.getAnimations || !node.getClientRects().length) { return; }   /* not drawn: nothing to see */
    node.classList.remove(cls);
    void node.offsetWidth;                  /* a style read: the animation starts again */
    node.classList.add(cls);
    if (node.__pfasArrive) { return; }
    node.__pfasArrive = true;
    node.addEventListener("animationend", function (e) { if (e.target === node) { node.classList.remove(cls); } });
  }

  /* ── Motion across the app: rows, tabs, notices, refusals, loops ──────────
     Each movement runs on the motion tokens, moves only transform and
     opacity, and is at once with reduced motion (the tokens read 0, so
     arrive() and leave() find nothing to play). */
  function reduced() { return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches); }
  /* A core list (table.contentstable) fills after the page is drawn. Its
     first fill: the first STAGGER rows rise one after the other, --t-step
     apart, and the rest come with the last of them, up to FILL_MAX (a row
     further down is below the window and comes at once). Every later change
     of its rows (a sort, a filter, a state, a page): its body fades in once,
     with no stagger. The same rows again (a tick, a redraw): nothing. */
  var STAGGER = 12, FILL_MAX = 40;
  function rowKeys(tbody) {
    var keys = [];
    for (var i = 0; i < tbody.childNodes.length; i++) {
      var tr = tbody.childNodes[i];
      if (tr.nodeType === 1 && tr.localName === "tr") { keys.push(tr.getAttribute("uid") || tr.getAttribute("id") || String(i)); }
    }
    return keys.join("|");
  }
  function settleList(tbody) {
    var keys = rowKeys(tbody), was = tbody.__pfasRows;
    tbody.__pfasRows = keys;
    if (!keys || keys === was) { return null; }
    if (!tbody.__pfasFilled) {
      tbody.__pfasFilled = true;
      var rows = tbody.querySelectorAll("tr");
      for (var i = 0; i < rows.length && i < FILL_MAX; i++) {
        rows[i].style.setProperty("--pfas-i", String(Math.min(i, STAGGER - 1)));
        rows[i].classList.add("is-filling");
        if (!rows[i].__pfasFill) {
          rows[i].__pfasFill = true;
          rows[i].addEventListener("animationend", function (e) { if (e.target === this) { this.classList.remove("is-filling"); } });
        }
      }
      return "fill";
    }
    arrive(tbody, "is-refreshing");
    return "refresh";
  }
  /* a link tab (a.pfas-seg-item: the server draws the page) changes page:
     between two loads of the one page the browser may play a view
     transition (pfas-components.css): the pill glides from the old tab to
     the new, the tabs' words cross-fade, the panel under the strip rises,
     the rest changes at once. Only a link tab's own click asks for it; every
     other page change, and reduced motion, skips it at both ends. */
  var VT_KEY = "pfas_vt_tab", vtNamed = [];
  function sameUrl(a, b) {
    try {
      var x = new URL(a, location.href), y = new URL(b, location.href);
      return x.origin === y.origin && x.pathname === y.pathname && x.search === y.search;
    } catch (e) { return false; }
  }
  function nameTabs(url) {
    unnameTabs();
    var segs = doc.querySelectorAll(".pfas-seg");
    for (var i = 0; i < segs.length; i++) {
      var items = segs[i].querySelectorAll("a.pfas-seg-item"), hit = false;
      for (var k = 0; k < items.length; k++) { if (sameUrl(items[k].getAttribute("href"), url)) { hit = true; } }
      if (!hit) { continue; }
      /* the new page is named before its own init has run: its strip is
         drawn now, the pill at its tab, so the pill has an end to glide to */
      initSeg(segs[i]);
      var pill = segs[i].querySelector(".pfas-seg-pill"), panel = segs[i].nextElementSibling;
      while (panel && (/^(script|style|template)$/.test(panel.localName) || panel.offsetParent === null)) { panel = panel.nextElementSibling; }
      var name = function (n, v, cls) {
        n.style.viewTransitionName = v;
        if (cls) { n.style.viewTransitionClass = cls; }
        vtNamed.push(n);
      };
      if (pill) { name(pill, "pfas-tab-pill"); }
      for (var j = 0; j < items.length; j++) { name(items[j], "pfas-tab-" + j, "pfas-tab-item"); }
      if (panel) { name(panel, "pfas-tab-panel"); }
      return vtNamed.length;
    }
    return 0;
  }
  function unnameTabs() {
    vtNamed.forEach(function (n) { n.style.viewTransitionName = ""; n.style.viewTransitionClass = ""; });
    vtNamed = [];
  }
  function vtGet() { try { return window.sessionStorage.getItem(VT_KEY); } catch (e) { return null; } }
  function vtSet(v) { try { if (v) { window.sessionStorage.setItem(VT_KEY, v); } else { window.sessionStorage.removeItem(VT_KEY); } } catch (e) {} }
  doc.addEventListener("click", function (e) {
    var a = e.target && e.target.closest ? e.target.closest("a.pfas-seg-item[href]") : null;
    if (!a || e.defaultPrevented || e.button > 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) { return; }
    try {
      var u = new URL(a.getAttribute("href"), location.href);
      if (u.origin === location.origin && u.pathname === location.pathname) { vtSet(u.pathname + u.search); }
    } catch (err) {}
  });
  window.addEventListener("pageswap", function (e) {
    if (!e.viewTransition) { return; }
    var to = e.activation && e.activation.entry ? e.activation.entry.url : "", want = vtGet();
    if (reduced() || !want || !to || !sameUrl(to, want) || !nameTabs(to)) { e.viewTransition.skipTransition(); }
  });
  window.addEventListener("pagereveal", function (e) {
    var want = vtGet();
    vtSet(null);
    if (!e.viewTransition) { return; }
    if (reduced() || !want || !sameUrl(location.href, want) || !nameTabs(location.href)) { e.viewTransition.skipTransition(); return; }
    e.viewTransition.finished.then(unnameTabs, unnameTabs);
  });
  /* the page a link tab opens holds its first paint until its content is
     parsed (the help panel follows the content area), so the strip and its
     panel are there to be named; any other page paints as soon as it can */
  (function () {
    var want = vtGet();
    if (doc.body || !doc.head || !want || !sameUrl(location.href, want) || reduced()) { return; }
    var l = doc.createElement("link");
    l.setAttribute("rel", "expect");
    l.setAttribute("href", "#pfas-help-panel");
    l.setAttribute("blocking", "render");
    doc.head.appendChild(l);
  })();
  /* A notice that appears after the person did something (a banner shown,
     a message added) rises in as a card does; one the page draws as it
     loads, or one shown while nobody acted, is simply there. */
  var NOTICE = ".pfas-banner, .alert, .portalMessage", acted = 0;
  function noticeReady() { return Date.now() - acted < 1500; }
  function noticed(n) {
    if (n && n.nodeType === 1 && n.matches && n.matches(NOTICE) && !n.hidden && noticeReady()) { arrive(n, "is-arriving"); }
  }
  /* A refused value: a soft ring shows once around the field (in and out,
     opacity only, laid over the page so nothing moves), and its hint fades
     in. Never a shake; never while typing (the hint fades only when its
     words change). */
  function ring(field) {
    if (!field || !field.getBoundingClientRect || reduced()) { return null; }
    var r = field.getBoundingClientRect();
    if (!r.width && !r.height) { return null; }
    var n = doc.createElement("div");
    n.className = "pfas-ring";
    n.setAttribute("aria-hidden", "true");
    n.style.left = (r.left - 4) + "px"; n.style.top = (r.top - 4) + "px";
    n.style.width = (r.width + 8) + "px"; n.style.height = (r.height + 8) + "px";
    doc.body.appendChild(n);
    var anims = n.getAnimations ? n.getAnimations().filter(function (a) {
      var t = a.effect && a.effect.getComputedTiming ? a.effect.getComputedTiming() : null;
      return t && t.endTime > 0;
    }) : [];
    function gone() { if (n.parentNode) { n.parentNode.removeChild(n); } }
    if (!anims.length) { gone(); return null; }
    anims[0].finished.then(gone, gone);
    return n;
  }
  function hint(node, words) {
    var box = node && node.parentNode;
    if (!box || box.__pfasHint === words) { return; }
    box.__pfasHint = words;
    arrive(node, "pfas-hint-in");
  }
  function refused(field) {
    if (!field || field.__pfasRung && Date.now() - field.__pfasRung < 1000) { return; }
    field.__pfasRung = Date.now();
    ring(field);
    var ids = (field.getAttribute("aria-describedby") || "").split(/\s+/);
    for (var i = 0; i < ids.length; i++) {
      var h = ids[i] ? doc.getElementById(ids[i]) : null;
      if (h && !h.hidden) { hint(h, h.textContent); }
    }
  }
  /* A lab step's GIF loops for ever: with reduced motion it shows one still
     frame (drawn once onto a canvas: the lab's own uploads too). */
  function stillGif(img) {
    if (!img || img.__pfasStill || !reduced()) { return; }
    var src = img.currentSrc || img.src || "";
    if (!/\.gif(\?|&|#|$)/i.test(src) || !img.complete || !img.naturalWidth) { return; }
    try {
      var c = doc.createElement("canvas");
      c.width = img.naturalWidth; c.height = img.naturalHeight;
      c.getContext("2d").drawImage(img, 0, 0);
      img.__pfasStill = true;
      img.src = c.toDataURL("image/png");
    } catch (e) { /* a picture from elsewhere cannot be read: it stays */ }
  }
  function watchMotion() {
    if (doc.__pfasMotion) { return; }
    doc.__pfasMotion = true;
    ["pointerdown", "change", "submit"].forEach(function (t) { doc.addEventListener(t, function () { acted = Date.now(); }, true); });
    doc.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { acted = Date.now(); } }, true);
    /* a field the browser refuses on a submit */
    doc.addEventListener("invalid", function (e) { refused(e.target); }, true);
    doc.addEventListener("load", function (e) { if (e.target && e.target.localName === "img") { stillGif(e.target); } }, true);
    var imgs = doc.querySelectorAll("img");
    for (var g = 0; g < imgs.length; g++) { stillGif(imgs[g]); }
    if (!window.MutationObserver || !doc.body) { return; }
    var tables = doc.querySelectorAll("table.contentstable > tbody");
    for (var t = 0; t < tables.length; t++) { settleList(tables[t]); }
    /* in the observer's own turn, before the page is painted, so a row
       never shows before it rises */
    new window.MutationObserver(function (ms) {
      var lists = [];
      ms.forEach(function (m) {
        var n = m.target;
        if (m.type === "attributes") {
          if (m.attributeName === "aria-invalid") { if (n.getAttribute("aria-invalid") === "true") { refused(n); } }
          else { noticed(n); }
          return;
        }
        if (n.localName === "tbody" && n.parentNode && n.parentNode.classList && n.parentNode.classList.contains("contentstable")) {
          if (lists.indexOf(n) < 0) { lists.push(n); }
          return;
        }
        Array.prototype.forEach.call(m.addedNodes || [], function (a) {
          noticed(a);
          if (a.nodeType === 1 && a.localName === "table" && a.classList.contains("contentstable") && a.tBodies && a.tBodies[0]) { lists.push(a.tBodies[0]); }
        });
      });
      lists.forEach(settleList);
    }).observe(doc.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["hidden", "aria-invalid"] });
  }

  /* a control that listens outside itself (a picker on its form field, a
     slider's release on the window) stops when its content is replaced: the
     drawer calls this on its old body before drawing the next */
  function dispose(root) {
    var all = root.querySelectorAll(".pfas-picker, [data-range]");
    for (var i = 0; i < all.length; i++) { if (all[i].__pfasDispose) { all[i].__pfasDispose(); } }
  }
  var drawer = {
    el: null,
    ensure: function () {
      if (drawer.el) { return drawer.el; }
      var d = doc.createElement("aside");
      d.className = "pfas-drawer"; d.setAttribute("role", "dialog"); d.setAttribute("aria-modal", "true"); d.setAttribute("data-open", "false");
      d.innerHTML = '<div class="pfas-drawer-head"><h2></h2><button type="button" class="btn-sm btn-secondary pfas-drawer-close" aria-label="Close">Close</button></div><div class="pfas-drawer-body"></div><div class="pfas-drawer-foot" hidden></div>';
      var s = doc.createElement("div"); s.className = "pfas-drawer-scrim";
      doc.body.appendChild(d); doc.body.appendChild(s);
      d.querySelector(".pfas-drawer-close").addEventListener("click", drawer.close);
      s.addEventListener("click", drawer.close);
      doc.addEventListener("keydown", function (e) { if (e.key === "Escape") { drawer.close(); } });
      d.addEventListener("keydown", function (e) { fieldEnter(d, e); });
      /* a box a window's script adds once it is open (a row, a redrawn
         block) is the house field too */
      if (window.MutationObserver) {
        new window.MutationObserver(function (ms) {
          ms.forEach(function (m) {
            Array.prototype.forEach.call(m.addedNodes || [], function (n) {
              if (n.nodeType !== 1) { return; }
              houseFields(n.matches && n.matches("input, select, textarea") ? n.parentNode : n);
            });
          });
        }).observe(d.querySelector(".pfas-drawer-body"), { childList: true, subtree: true });
      }
      drawer.el = d;
      return d;
    },
    /* content: an HTML string, or a node; opts: {footer: node, focus: node, cls: string,
       head: a node, or nodes, beside the title (a drawer's own Prev / Next), gone on the next open} */
    open: function (title, content, opts) {
      var d = drawer.ensure();
      opts = opts || {};
      /* what opened it gets the focus back on Close (a re-open while open keeps it) */
      if (d.getAttribute("data-open") !== "true") { drawer.opener = opts.opener || doc.activeElement; }
      d.querySelector("h2").textContent = title || "";
      var body = d.querySelector(".pfas-drawer-body"), foot = d.querySelector(".pfas-drawer-foot");
      dispose(body);
      body.textContent = "";
      if (content && content.nodeType) { body.appendChild(content); } else { body.innerHTML = content || ""; }
      foot.textContent = "";
      foot.hidden = !opts.footer;
      if (opts.footer) { foot.appendChild(opts.footer); }
      var tools = d.querySelector(".pfas-drawer-tools");
      if (tools) { tools.parentNode.removeChild(tools); }
      if (opts.head) {
        tools = doc.createElement("div"); tools.className = "pfas-drawer-tools";
        [].concat(opts.head).forEach(function (n) { tools.appendChild(n); });
        d.querySelector(".pfas-drawer-head").insertBefore(tools, d.querySelector(".pfas-drawer-close"));
      }
      d.className = "pfas-drawer" + (opts.cls ? " " + opts.cls : "");
      /* a table written into it widens as one on the page does */
      initTables(body);
      /* every box in it is the house field */
      houseFields(body);
      if (d.getAttribute("data-open") !== "true") { windowFrom(d, opts.opener); }
      d.setAttribute("data-open", "true");
      (opts.focus || d.querySelector(".pfas-drawer-close")).focus();
      tileOpened(d, opts.opener);
    },
    close: function () {
      if (drawer.el) {
        drawer.el.setAttribute("data-open", "false");
        /* it closes by a plain fade, back in the centre */
        styleVar(drawer.el, "--pfas-win-origin", null);
        styleVar(drawer.el, "--pfas-win-from", null);
      }
      var opener = drawer.opener;
      drawer.opener = null;
      if (opener && opener.focus) { try { opener.focus(); } catch (e) { /* gone from the page */ } }
    }
  };

  /* Where a window opens from. A window grows from the tile that opened it:
     its transform origin is the tile's centre, and it starts at the tile's
     size (a scale of .25 to .98), settling centred. A tile's click presses a
     hidden trigger, so the pending tile click names the tile; otherwise what
     opened it; a node with no box (hidden, or none) gives the centre and .98.
     The closed starting point is set with its transition held, then read
     once, so the very first window of a page moves too: the browser has
     drawn the closed window before it opens. */
  function styleVar(el, k, v) {
    if (v !== null) { el.style.setProperty(k, v); } else if (el.style.removeProperty) { el.style.removeProperty(k); } else { el.style.setProperty(k, ""); }
  }
  function windowFrom(d, opener) {
    var p = tilePending, from = opener || doc.activeElement;
    if (p && p.tile && Date.now() - p.at <= 1500 && (!opener || (opener.closest && opener.closest(".pfas-hier-acts")))) { from = p.tile; }
    var r = from && from !== doc.body && from.getBoundingClientRect && !d.contains(from) ? from.getBoundingClientRect() : null;
    var W = d.offsetWidth, H = d.offsetHeight, root = doc.documentElement;
    d.style.transition = "none";
    if (r && r.width && r.height && W && H) {
      var ox = r.left + r.width / 2 - ((root.clientWidth || W) - W) / 2;
      var oy = r.top + r.height / 2 - ((root.clientHeight || H) - H) / 2;
      var s = Math.max(0.25, Math.min(0.98, Math.max(r.width / W, r.height / H)));
      styleVar(d, "--pfas-win-origin", Math.round(ox) + "px " + Math.round(oy) + "px");
      styleVar(d, "--pfas-win-from", s.toFixed(3));
    } else {
      styleVar(d, "--pfas-win-origin", null);
      styleVar(d, "--pfas-win-from", null);
    }
    void d.offsetWidth;                     /* the style read: the closed window is drawn */
    d.style.transition = "";
  }

  /* ── An equation on the page (PFAS.equation draws it) ─────────────────
     [data-equation]='{"formulas": [...], "terms": [{"symbol", ...}]}': the
     inline size, drawn over the plain text the server wrote (what the page
     reads without the script). [data-equation-open]='{"title", "input",
     "options", "terms", "steps", "foot"}': the whole box opens the window,
     as a table row opens its record, the option in use read from the
     posted input it names at that moment; a control in the box (the
     switch, a button) acts as itself and opens nothing. Read only: the
     window changes no setting. */
  var EQ_SKIP = "a[href], button, input, select, textarea, label, summary, .pfas-seg, [contenteditable], .pfas-menu";
  function drawEquations(root) {
    var E = window.PFAS.equation, all = (root || doc).querySelectorAll("[data-equation]");
    for (var i = 0; i < all.length; i++) {
      var el = all[i], spec;
      if (el.getAttribute("data-equation-drawn")) { continue; }
      try { spec = JSON.parse(el.getAttribute("data-equation")); } catch (e) { continue; }
      el.innerHTML = E.lines(spec.formulas, spec.terms || []);
      el.setAttribute("data-equation-drawn", "true");
    }
  }
  function openEquation(el) {
    var E = window.PFAS.equation, spec;
    try { spec = JSON.parse(el.getAttribute("data-equation-open")); } catch (e) { return false; }
    var input = spec.input ? doc.getElementById(spec.input) : null;
    drawer.open(spec.title || "", E.window(spec, input ? input.value : spec.inUse), { cls: "is-dialog", opener: el });
    E.hover(drawer.el.querySelector(".pfas-drawer-body"));
    return true;
  }
  function equationBox(t) {
    var box = t && t.closest ? t.closest("[data-equation-open]") : null;
    if (!box) { return null; }
    var skip = t.closest(EQ_SKIP);
    return skip && box.contains(skip) && skip !== box ? null : box;
  }
  function initEquations(root) {
    drawEquations(root);
    var boxes = (root || doc).querySelectorAll("[data-equation-open]");
    for (var i = 0; i < boxes.length; i++) {
      if (!boxes[i].hasAttribute("tabindex")) { boxes[i].setAttribute("tabindex", "0"); }
      boxes[i].setAttribute("aria-haspopup", "dialog");
    }
    if (doc.__pfasEquations) { return; }
    doc.__pfasEquations = true;
    doc.addEventListener("click", function (e) {
      var box = equationBox(e.target);
      if (!box || e.defaultPrevented || e.button) { return; }
      openEquation(box);
    });
    doc.addEventListener("keydown", function (e) {
      if ((e.key !== "Enter" && e.key !== " ") || !e.target || !e.target.hasAttribute ||
          !e.target.hasAttribute("data-equation-open")) { return; }
      e.preventDefault();
      openEquation(e.target);
    });
  }

  function initTree(tree) {
    if (tree.__pfas) { return; }
    tree.__pfas = true;
    var sw = tree.querySelector("[data-tree-view]");
    if (sw) {
      try { var saved = localStorage.getItem("pfas_tree_view"); if (saved) { tree.setAttribute("data-view", saved); sw.checked = saved === "all"; } } catch (e) {}
      sw.addEventListener("change", function () {
        var v = sw.checked ? "all" : "path";
        tree.setAttribute("data-view", v);
        try { localStorage.setItem("pfas_tree_view", v); } catch (e) {}
      });
    }
  }

  /* ── Navigation tiles (.pfas-nav-tiles, the section panel) ────────────────
     The section panel's groups: ul.pfas-nav-tiles of li, each holding
     a.pfas-navtile[href][data-path][data-pinned="true|false"] (aria-current="page"
     on the current page; an icon and a span.pfas-navtile-label, the link's
     accessible name) and button.pfas-nav-more (the row menu). A plain list of
     links: Tab walks them in reading order, Enter follows the link, and the
     button stays out of the Tab order, as the mouse's. Shift+F10 or the menu
     key on a tile opens its row menu, as its button does: Pin or Unpin and
     Open in a new tab, one menu at a time, fixed to the window beside the tile
     (--menu-x, --menu-y); Escape, a press outside or Tab out closes it, and
     the focus goes back to the tile unless it went elsewhere. A tile drawn
     without the button has no row menu: those keys are then the browser's.
     Pin only flips data-pinned and says so in a bubbling pfas:pin event
     {path, pinned} on the tile: whoever keeps the pins saves them. */
  var navMenu = null;   /* the one open row menu: { box, button, item } */
  function navOwn(li, test) {
    var kids = li ? li.children : [];
    for (var i = 0; i < kids.length; i++) { if (test(kids[i])) { return kids[i]; } }
    return null;
  }
  function navBtn(item, cls) {
    var b = navOwn(item.parentNode, function (n) { return n.classList.contains(cls); });
    /* on a phone the row menu's button is not drawn: nor is its menu (keys included) */
    if (b && window.getComputedStyle && window.getComputedStyle(b).display === "none") { return null; }
    return b;
  }
  function navStop(tree) {
    var bs = tree.querySelectorAll(".pfas-nav-more");
    for (var i = 0; i < bs.length; i++) { bs[i].setAttribute("tabindex", "-1"); }
  }
  function navCloseMenu(refocus) {
    if (!navMenu) { return; }
    var m = navMenu;
    navMenu = null;
    if (m.box.parentNode) { m.box.parentNode.removeChild(m.box); }
    if (m.button) { m.button.setAttribute("aria-expanded", "false"); }
    if (refocus) { m.item.focus(); }
  }
  function navPlace(box, item) {
    var r = item.getBoundingClientRect(), w = window.innerWidth || 0, h = window.innerHeight || 0;
    var x = Math.max(4, Math.min(r.left, w - 176)), y = r.bottom + 2;
    if (h && y + 88 > h) { y = Math.max(4, r.top - 88); }
    box.style.setProperty("--menu-x", Math.round(x) + "px");
    box.style.setProperty("--menu-y", Math.round(y) + "px");
  }
  function navOpenMenu(tree, item) {
    navCloseMenu(false);
    var button = navBtn(item, "pfas-nav-more");
    var box = doc.createElement("div");
    box.className = "pfas-nav-menu";
    box.setAttribute("role", "menu");
    function entry(label, act) {
      var b = doc.createElement("button");
      b.type = "button";
      b.className = "pfas-nav-menu-item";
      b.setAttribute("role", "menuitem");
      b.setAttribute("tabindex", "-1");
      b.textContent = label;
      b.addEventListener("click", act);
      box.appendChild(b);
      return b;
    }
    var first = entry(item.getAttribute("data-pinned") === "true" ? "Unpin" : "Pin", function () {
      var pinned = item.getAttribute("data-pinned") !== "true";
      item.setAttribute("data-pinned", pinned ? "true" : "false");
      navCloseMenu(true);
      item.dispatchEvent(new CustomEvent("pfas:pin", { bubbles: true, detail: { path: item.getAttribute("data-path"), pinned: pinned } }));
    });
    entry("Open in a new tab", function () {
      navCloseMenu(true);
      window.open(item.getAttribute("href"), "_blank", "noopener");
    });
    box.addEventListener("keydown", function (e) {
      if (e.key !== "ArrowDown" && e.key !== "ArrowUp") { return; }
      e.preventDefault();
      var bs = box.querySelectorAll(".pfas-nav-menu-item"), i = Array.prototype.indexOf.call(bs, e.target);
      bs[(i + (e.key === "ArrowDown" ? 1 : bs.length - 1)) % bs.length].focus();
    });
    /* Tab out of the menu closes it, the focus left where Tab put it */
    box.addEventListener("focusout", function (e) {
      var to = e.relatedTarget;
      if (navMenu && navMenu.box === box && to && !box.contains(to) && !(button && button.contains(to))) { navCloseMenu(false); }
    });
    navPlace(box, item);
    item.parentNode.insertBefore(box, button ? button.nextSibling : item.nextSibling);
    if (button) { button.setAttribute("aria-expanded", "true"); }
    navMenu = { box: box, button: button, item: item };
    first.focus();
  }
  function watchNavMenu() {
    if (doc.__pfasNavMenu) { return; }
    doc.__pfasNavMenu = true;
    /* a press outside the open menu closes it; a press on its own button is that button's toggle */
    doc.addEventListener("click", function (e) {
      if (!navMenu || navMenu.box.contains(e.target) || (navMenu.button && navMenu.button.contains(e.target))) { return; }
      navCloseMenu(false);
    });
    doc.addEventListener("keydown", function (e) {
      if (navMenu && e.key === "Escape") { e.preventDefault(); navCloseMenu(true); }
    });
  }
  function isNavTile(n) { return !!(n && n.classList && n.classList.contains("pfas-navtile") && n.tagName === "A"); }
  function wireNavTiles(tree) {
    if (tree.__pfasNav) { return; }
    tree.__pfasNav = true;
    watchNavMenu();
    navStop(tree);
    tree.addEventListener("click", function (e) {
      var t = e.target && e.target.closest ? e.target : null;
      if (!t || t.closest(".pfas-nav-menu")) { return; }
      var btn = t.closest(".pfas-nav-more");
      var item = btn ? navOwn(t.closest("li"), isNavTile) : null;
      if (!item) { return; }
      if (navMenu && navMenu.button === btn) { navCloseMenu(true); }
      else { navOpenMenu(tree, item); }
    });
    tree.addEventListener("keydown", function (e) {
      if (!isNavTile(e.target)) { return; }
      if ((e.key === "ContextMenu" || (e.shiftKey && e.key === "F10")) && navBtn(e.target, "pfas-nav-more")) {
        e.preventDefault();
        navOpenMenu(tree, e.target);
      }
    });
    /* the menu key's contextmenu (no pointer) on a tile is the row menu's, not the site
       menu's, as is any contextmenu in the open row menu (the key's event lands where the
       row menu has just put the focus) */
    tree.addEventListener("contextmenu", function (e) {
      if (e.target && e.target.closest && e.target.closest(".pfas-nav-menu")) { e.preventDefault(); return; }
      if (!isNavTile(e.target) || e.clientX || e.clientY || !navBtn(e.target, "pfas-nav-more")) { return; }
      e.preventDefault();
      if (!navMenu || navMenu.item !== e.target) { navOpenMenu(tree, e.target); }
    });
  }
  /* a wired list whose tiles were drawn again: the buttons out of the Tab order again */
  function resetNavTiles(tree) {
    if (tree) { navStop(tree); }
  }
  /* root: one .pfas-nav-tiles, or a node (the document by default) whose lists are wired */
  function initNavTiles(root) {
    root = root || doc;
    if (root.classList && root.classList.contains("pfas-nav-tiles")) { wireNavTiles(root); return; }
    var lists = root.querySelectorAll(".pfas-nav-tiles");
    for (var i = 0; i < lists.length; i++) { wireNavTiles(lists[i]); }
  }

  /* Every table on a PFAS page scrolls sideways inside its own box: a table
     wider than its column never pushes the page sideways and never has its
     cells squeezed into each other on a phone. A table already inside a
     scrolling box is left as it is; core's listings are not touched (React
     renders them and they scroll on their own). */
  function inScrollBox(el, stop) {
    for (var p = el.parentElement; p && p !== stop; p = p.parentElement) {
      if (p.classList.contains("pfas-scroll-x")) { return true; }
      var o = window.getComputedStyle(p).overflowX;
      if (o === "auto" || o === "scroll") { return true; }
    }
    return false;
  }
  function wrapTables(root) {
    var area = doc.querySelector(".pfas-content-area");
    if (!area) { return; }
    var tables = (root && root.querySelectorAll ? root : area).querySelectorAll("table");
    for (var i = 0; i < tables.length; i++) {
      var t = tables[i];
      if (t.__pfasWrapped || !area.contains(t) || t.closest(".no-scroll-wrap")) { continue; }
      t.__pfasWrapped = true;
      if (inScrollBox(t, area)) { continue; }
      var box = doc.createElement("div");
      box.className = "pfas-scroll-x";
      t.parentNode.insertBefore(box, t);
      box.appendChild(t);
    }
  }
  function watchTables() {
    var area = doc.querySelector(".pfas-content-area");
    if (!area || !window.MutationObserver || area.__pfasWatch) { return; }
    area.__pfasWatch = true;
    var pending = false;
    new MutationObserver(function () {
      if (pending) { return; }
      pending = true;
      window.setTimeout(function () { pending = false; wrapTables(); enhance(); initTables(); initTiles(area); }, 50);
    }).observe(area, { childList: true, subtree: true });
  }

  /* ── Table foundations: widened columns, the scroll cue, switch words ───── */
  /* What the browser remembers is a convenience: a page draws and works
     without it, and storage that is missing or refuses is never an error. */
  function storeGet(k) {
    try { var s = window.localStorage; return s ? s.getItem(k) : null; } catch (e) { return null; }
  }
  function storeSet(k, v) {
    try { var s = window.localStorage; if (s) { s.setItem(k, v); } } catch (e) {}
  }
  /* a table's column headings, in the order their columns stand on screen
     (a heading spanning two header rows sits in the first row's markup but
     takes its column's place among the second row's): never a group's
     heading over its columns, the selection column or the row of column
     switches */
  function leafHeadings(table) {
    var head = table.tHead || table.querySelector("thead");
    if (!head) { return []; }
    var taken = [], at = [];                  /* per header row: the columns already filled from above */
    Array.prototype.forEach.call(head.querySelectorAll("tr"), function (tr, r) {
      var col = 0;
      taken[r] = taken[r] || {};
      Array.prototype.forEach.call(tr.children, function (cell) {
        if (cell.tagName !== "TH" && cell.tagName !== "TD") { return; }
        while (taken[r][col]) { col++; }
        var span = Number(cell.getAttribute("colspan") || 1) || 1, down = Number(cell.getAttribute("rowspan") || 1) || 1;
        /* a group heading spans only the columns shown (Columns), while its
           columns below keep their places, shown or not: it is counted here
           over every one of them, so a column after the group keeps its
           place in the order */
        if (cell.classList && cell.classList.contains("pfas-sheet-gh")) { span = groupWidth(head, cell) || span; }
        for (var i = 0; i < down; i++) {
          taken[r + i] = taken[r + i] || {};
          for (var j = 0; j < span; j++) { taken[r + i][col + j] = true; }
        }
        if (cell.tagName === "TH" && isLeafHeading(cell)) { at.push({ th: cell, col: col, n: at.length }); }
        col += span;
      });
    });
    at.sort(function (a, b) { return a.col - b.col || a.n - b.n; });
    at.forEach(function (x) { x.th.__pfasCol = x.col; });
    return at.map(function (x) { return x.th; });
  }
  /* the body cells that start in column `col` (counted as leafHeadings
     counts it: spans and cells held down from the row above taken) */
  function columnCells(table, col) {
    var out = [];
    Array.prototype.forEach.call(table.tBodies || [], function (tb) {
      var taken = [];
      Array.prototype.forEach.call(tb.rows, function (tr, r) {
        var at = 0;
        taken[r] = taken[r] || {};
        Array.prototype.forEach.call(tr.cells, function (cell) {
          while (taken[r][at]) { at++; }
          var span = Number(cell.getAttribute("colspan") || 1) || 1, down = Number(cell.getAttribute("rowspan") || 1) || 1;
          for (var i = 0; i < down; i++) {
            taken[r + i] = taken[r + i] || {};
            for (var j = 0; j < span; j++) { taken[r + i][at + j] = true; }
          }
          if (at === col && span === 1) { out.push(cell); }
          at += span;
        });
      });
    });
    return out;
  }
  /* the columns a group heading stands over, shown or not */
  function groupWidth(head, gh) {
    var g = gh.getAttribute("data-group"), w = 0;
    Array.prototype.forEach.call(head.querySelectorAll("th[data-col]"), function (th) {
      if (th !== gh && th.getAttribute("data-group") === g) { w += Number(th.getAttribute("colspan") || 1) || 1; }
    });
    return w;
  }
  function isLeafHeading(th) {
    var tr = th.parentNode;
    return th.getAttribute("scope") !== "colgroup" && !th.classList.contains("pfas-sheet-gh") &&
           !th.classList.contains("pfas-sheet-sel") && !th.hasAttribute("hidden") &&
           !(tr && tr.classList && tr.classList.contains("pfas-sheet-switches"));
  }
  var COL_MIN = 48;                                /* px: a column is never dragged narrower */
  /* A computer widens a column by dragging its heading's right edge; the
     widths are kept per table (key) in the browser, as a JSON list in the
     order of the headings that carry a handle, every heading but the last
     (null: a column left at its own width). */
  function initColResize(table, key) {
    var ths = leafHeadings(table).slice(0, -1), skey = "pfas.cols." + key;
    if (!ths.length || table.__pfasCols) { return; }
    table.__pfasCols = true;
    var raw = storeGet(skey), kept = null;
    try { kept = JSON.parse(raw || "null"); } catch (e) { kept = null; }     /* a kept value that is not JSON */
    /* kept for another set of columns: dropped, never laid on the wrong ones */
    if (!kept || kept.length !== ths.length) { kept = null; }
    /* a column given a width wraps its cells' words: a cell never wraps
       otherwise, and the table never draws a column narrower than its
       longest unwrapped entry (the pinned row names among them) */
    function setWidth(th, w) {
      th.style.width = w + "px";
      if (th.classList.contains("is-col-set")) { return; }
      th.classList.add("is-col-set");
      columnCells(table, th.__pfasCol).forEach(function (c) { c.classList.add("is-col-set"); });
    }
    ths.forEach(function (th, i) {
      var w = kept && kept[i];
      if (typeof w === "number" && w >= COL_MIN) { setWidth(th, w); }
    });
    function save() {
      storeSet(skey, JSON.stringify(ths.map(function (th) {
        var w = parseInt(th.style.width, 10);
        return isFinite(w) ? w : null;
      })));
    }
    ths.forEach(function (th) {
      var h = el("span", "pfas-col-handle");
      h.setAttribute("aria-hidden", "true");
      th.classList.add("has-col-handle");
      th.appendChild(h);
      h.addEventListener("click", function (e) { e.stopPropagation(); e.preventDefault(); });
      h.addEventListener("pointerdown", function (e) {
        if (e.button !== undefined && e.button !== 0) { return; }
        e.preventDefault(); e.stopPropagation();
        var x0 = e.clientX, w0 = th.getBoundingClientRect().width;
        h.classList.add("is-dragging");
        table.classList.add("is-col-dragging");
        try { if (h.setPointerCapture && e.pointerId !== undefined) { h.setPointerCapture(e.pointerId); } } catch (err) {}
        function move(ev) { setWidth(th, Math.max(COL_MIN, Math.round(w0 + ev.clientX - x0))); }
        function stop(ev) {
          if (ev && ev.type === "pointerup") { move(ev); }
          /* asked narrower than its content allows: keep what is drawn */
          var drawn = Math.round(th.getBoundingClientRect().width);
          if (drawn > parseInt(th.style.width, 10)) { th.style.width = drawn + "px"; }
          table.classList.remove("is-col-dragging");
          doc.removeEventListener("pointermove", move);
          doc.removeEventListener("pointerup", stop);
          doc.removeEventListener("pointercancel", stop);
          h.classList.remove("is-dragging");
          save();
        }
        doc.addEventListener("pointermove", move);
        doc.addEventListener("pointerup", stop);
        doc.addEventListener("pointercancel", stop);
      });
    });
  }
  /* A table wider than its box: the box takes has-more and a chip at its top
     right counts the columns whose right edge is past the box's ("3 more →"),
     recounted on scroll and resize. The chip is drawn once and only hidden
     or reworded after (its text node's data), so the content observer never
     sees it change. */
  function initScrollCue(wrap) {
    var table = wrap && wrap.querySelector("table");
    if (!table || wrap.__pfasCue) { return; }
    wrap.__pfasCue = true;
    var bar = el("div", "pfas-sheet-more-bar"), chip = el("span", "pfas-sheet-more"), txt = doc.createTextNode("");
    bar.setAttribute("aria-hidden", "true");
    bar.hidden = true;
    chip.appendChild(txt); bar.appendChild(chip);
    /* a click on the chip brings the next columns into view (a pointer's
       shortcut: the keys and the bars already scroll the box) */
    chip.title = "Show the next columns";
    chip.addEventListener("click", function () { scrollAcross(wrap, Math.round(wrap.clientWidth * 0.8)); });
    wrap.insertBefore(bar, wrap.firstChild);
    var ro = null;
    /* a box taken off the page lets go of the window and its observer */
    function release() {
      window.removeEventListener("resize", update);
      if (ro) { try { ro.disconnect(); } catch (e) {} ro = null; }
    }
    function update() {
      if (!doc.contains(wrap)) { release(); return; }
      var n = 0;
      if (wrap.scrollWidth > wrap.clientWidth + 1) {
        /* the visible area's right edge: inside the border, short of the
           scrollbar and its reserved gutter */
        var right = wrap.getBoundingClientRect().left + (wrap.clientLeft || 0) + wrap.clientWidth;
        leafHeadings(table).forEach(function (th) {
          var r = th.getBoundingClientRect();
          if (r.width > 0 && r.right > right + 1) { n++; }     /* a column Columns took off measures nothing */
        });
      }
      wrap.classList.toggle("has-more", n > 0);
      if (bar.hidden !== !n) { bar.hidden = !n; }
      var t = n ? n + " more →" : "";
      if (txt.data !== t) { txt.data = t; }
    }
    wrap.addEventListener("scroll", update);
    window.addEventListener("resize", update);
    /* the table changing width (Columns, a widened column) or its box
       (the sidebar folding, a drawer opening) */
    if (window.ResizeObserver) {
      try { ro = new window.ResizeObserver(update); ro.observe(table); ro.observe(wrap); } catch (e) { ro = null; }
    }
    update();
  }
  function scrollAcross(box, dx) {
    if (box.scrollBy) { box.scrollBy({ left: dx, behavior: "smooth" }); } else { box.scrollLeft += dx; }
  }

  /* ── Sideways scrolling within reach ──────────────────────────────────────
     A box's own sideways scrollbar is at its bottom edge, often below the
     window. Two ways in that need no trip to the bottom:
     - the pinned bar: while a sideways box runs past the bottom of the
       visible area, one bar drawn along that bottom edge, as wide as the box,
       scrolls it in step with it; the wheel over the bar scrolls sideways;
     - the wheel button: pressed over a box (not a link), the page scrolls
       the way the pointer moves away from where it was pressed, faster the
       further away, sideways in the box and up and down in the box or the
       page. Held and moved, it stops on release; clicked, it stays on until
       the next click, Esc or leaving the window.
     A computer only: a finger scrolls the box itself. */
  var RAIL_H = 14, AUTO_DEAD = 12, hrail = null, hplace = null;
  var HBOX = ".pfas-sheet-wrap, .pfas-scroll-x, .pfas-content-area .table-wrap";
  function finePointer() {
    return !(window.matchMedia && window.matchMedia("(pointer: coarse)").matches);
  }
  /* the visible area's top and bottom: the content area inside the window */
  function visibleBand() {
    var area = doc.querySelector(".pfas-content-area"), h = window.innerHeight || 0;
    if (!area) { return { top: 0, bottom: h }; }
    var r = area.getBoundingClientRect(), top = r.top + (area.clientTop || 0);
    return { top: Math.max(0, top), bottom: Math.min(h, top + area.clientHeight) };
  }
  /* the box the pinned bar stands in for: wider than it is shown, drawn (not
     in a closed section, a drawer or a dialog), on screen by more than a row,
     its own scrollbar below the band; the innermost of several (a box later
     in the page lies inside or below an earlier one) */
  function railBox(boxes, band) {
    var pick = null;
    for (var i = 0; i < boxes.length; i++) {
      var b = boxes[i];
      /* a closed section keeps its boxes' measures: shut is not shown */
      if (b.scrollWidth <= b.clientWidth + 1 || b.closest(".pfas-drawer, .pfas-modal, [hidden], details:not([open])")
          || (b.checkVisibility && !b.checkVisibility())) { continue; }
      var r = b.getBoundingClientRect();
      if (!r.height || r.top > band.bottom - 48 || r.bottom <= band.bottom + 1) { continue; }
      pick = b;
    }
    return pick;
  }
  /* pixels a frame for a pointer d px from where the wheel was pressed: still
     near it, faster away from it, never a jump */
  function autoSpeed(d) {
    var a = Math.abs(d) - AUTO_DEAD;
    if (a <= 0) { return 0; }
    return (d < 0 ? -1 : 1) * Math.min(60, Math.round(a * a / 400 + a / 8));
  }
  /* the nearest box that scrolls along an axis, from el outwards; up and
     down falls back to the page */
  function scroller(el, axis) {
    for (var n = el; n && n !== doc.body && n.nodeType === 1; n = n.parentElement) {
      var o = window.getComputedStyle(n)[axis === "x" ? "overflowX" : "overflowY"];
      var more = axis === "x" ? n.scrollWidth > n.clientWidth + 1 : n.scrollHeight > n.clientHeight + 1;
      if (more && (o === "auto" || o === "scroll")) { return n; }
    }
    if (axis === "y") {
      var page = doc.scrollingElement || doc.documentElement;
      return page && page.scrollHeight > page.clientHeight + 1 ? page : null;
    }
    return null;
  }
  function initHScroll() {
    if (doc.__pfasHScroll || !doc.body) { return; }
    doc.__pfasHScroll = true;
    var rail = el("div", "pfas-hrail"), inner = el("div", "pfas-hrail-in"), box = null, queued = false;
    rail.setAttribute("aria-hidden", "true");
    rail.tabIndex = -1;            /* a scrolling box takes no Tab stop: the table's own keys scroll it */
    rail.hidden = true;
    rail.appendChild(inner);
    doc.body.appendChild(rail);
    hrail = rail;
    function place() {
      queued = false;
      if (!doc.body.contains(rail)) { doc.body.appendChild(rail); }   /* a script that redrew the body */
      var b = finePointer() ? railBox(doc.querySelectorAll(HBOX), visibleBand()) : null;
      box = b;
      if (!b) { if (!rail.hidden) { rail.hidden = true; } return; }
      var r = b.getBoundingClientRect(), band = visibleBand();
      rail.style.left = Math.round(r.left + (b.clientLeft || 0)) + "px";
      rail.style.width = b.clientWidth + "px";
      rail.style.top = (band.bottom - RAIL_H) + "px";
      inner.style.width = b.scrollWidth + "px";
      if (rail.hidden) { rail.hidden = false; }
      if (Math.abs(rail.scrollLeft - b.scrollLeft) > 1) { rail.scrollLeft = b.scrollLeft; }
    }
    function queue() {
      if (queued) { return; }
      queued = true;
      (window.requestAnimationFrame || window.setTimeout)(place);
    }
    hplace = place;
    /* the bar moves the box only while it is held: a box scrolling on its
       own (smoothly, a frame at a time) is followed, never pulled back */
    var held = false;
    rail.addEventListener("pointerdown", function () { held = true; });
    doc.addEventListener("pointerup", function () { held = false; }, true);
    rail.addEventListener("scroll", function () {
      if (held && box && Math.abs(box.scrollLeft - rail.scrollLeft) > 1) { box.scrollLeft = rail.scrollLeft; }
    });
    rail.addEventListener("wheel", function (e) {
      if (!box || Math.abs(e.deltaX || 0) > Math.abs(e.deltaY || 0)) { return; }
      box.scrollLeft += (e.deltaY || 0) * (e.deltaMode === 1 ? 16 : 1);
      e.preventDefault();
    }, { passive: false });
    /* scroll does not bubble: caught on its way down, from every box and the page */
    doc.addEventListener("scroll", function (e) { if (e.target !== rail) { queue(); } }, true);
    window.addEventListener("resize", queue);
    if (window.MutationObserver) {
      new MutationObserver(queue).observe(doc.body, { childList: true, subtree: true, attributes: true,
                                                      attributeFilter: ["hidden", "open", "class"] });
    }
    queue();

    /* the wheel button */
    var auto = null, swallow = null;   /* swallow: the button whose release and click are not the page's */
    function stopAuto() {
      if (!auto) { return; }
      if (auto.mark.parentNode) { auto.mark.parentNode.removeChild(auto.mark); }
      doc.documentElement.classList.remove("is-autoscrolling");
      doc.removeEventListener("mousemove", auto.move, true);
      auto = null;
    }
    function step() {
      if (!auto) { return; }
      var sx = autoSpeed(auto.x - auto.x0), sy = autoSpeed(auto.y - auto.y0);
      if (auto.h && sx) { auto.h.scrollLeft += sx; }
      if (auto.v && sy) { auto.v.scrollTop += sy; }
      (window.requestAnimationFrame || window.setTimeout)(step);
    }
    doc.addEventListener("mousedown", function (e) {
      /* a click while it runs only stops it: nothing under it is pressed */
      if (auto) { e.preventDefault(); e.stopPropagation(); swallow = e.button; stopAuto(); return; }
      swallow = null;              /* a release with no click after it leaves nothing behind */
      if (e.button !== 1 || !finePointer() || !e.target.closest || e.target.closest("a[href]")) { return; }
      var h = e.target.closest(".pfas-hrail") ? box : scroller(e.target, "x"), v = scroller(e.target, "y");
      if (!h && !v) { return; }
      e.preventDefault();          /* no paste into a field, no browser scroll of its own */
      swallow = 1;
      var mark = el("div", "pfas-autoscroll-mark");
      mark.setAttribute("aria-hidden", "true");
      mark.style.left = e.clientX + "px";
      mark.style.top = e.clientY + "px";
      doc.body.appendChild(mark);
      doc.documentElement.classList.add("is-autoscrolling");
      auto = { h: h, v: v, x0: e.clientX, y0: e.clientY, x: e.clientX, y: e.clientY, moved: false, mark: mark };
      auto.move = function (m) {
        auto.x = m.clientX; auto.y = m.clientY;
        if (Math.abs(auto.x - auto.x0) > AUTO_DEAD || Math.abs(auto.y - auto.y0) > AUTO_DEAD) { auto.moved = true; }
      };
      doc.addEventListener("mousemove", auto.move, true);
      step();
    }, true);
    doc.addEventListener("mouseup", function (e) {
      if (swallow !== e.button) { return; }
      e.preventDefault(); e.stopPropagation();
      if (auto && auto.moved) { stopAuto(); }          /* held and moved: let go to stop */
    }, true);
    /* the press's own click (a paste, a new tab, a button) is not the page's */
    function swallowClick(e) {
      if (swallow !== e.button) { return; }
      e.preventDefault(); e.stopPropagation();
      swallow = null;
    }
    doc.addEventListener("click", swallowClick, true);
    doc.addEventListener("auxclick", swallowClick, true);
    doc.addEventListener("keydown", function (e) { if (auto && e.key === "Escape") { stopAuto(); } }, true);
    window.addEventListener("blur", stopAuto);
  }

  /* a switch says its state beside it: "On" / "Off" in its .pfas-switch-word */
  function switchWord(input) {
    var lab = input.closest("label"), word = lab && lab.querySelector(".pfas-switch-word");
    if (!word && lab && lab.nextElementSibling && lab.nextElementSibling.classList.contains("pfas-switch-word")) {
      word = lab.nextElementSibling;
    }
    if (!word) { return; }
    function draw() {
      var t = input.checked ? (input.getAttribute("data-word-on") || "On") : (input.getAttribute("data-word-off") || "Off");
      if (word.textContent !== t) { word.textContent = t; }
    }
    if (!input.__pfasWord) { input.__pfasWord = true; input.addEventListener("change", draw); }
    draw();
  }
  /* a choice that inherits the row above (select[data-inherits]): muted
     (is-inherited) while its blank, the inherited "\u00b7", is chosen */
  function inheritMark(sel) {
    function draw() { sel.classList.toggle("is-inherited", sel.value === ""); }
    if (!sel.__pfasInherit) { sel.__pfasInherit = true; sel.addEventListener("change", draw); }
    draw();
  }
  /* every grid and declared table on the page: widened columns (kept per
     page and table) and the scroll cue; every other data table that opts in
     (data-col-resize, naming it for its kept widths): widened columns;
     every switch with a state word; every inheriting choice muted while it
     inherits */
  /* In a table one types into, a column of boxes is centred under its
     heading, the heading and every cell; a number keeps ending at the right
     inside its box. A column of words, the row names, the selection box and
     a list drawn as chips keep starting at the left; a table with no box
     (results, a record) keeps its own alignment, numbers at the right. */
  var BOX = "input:not([type=hidden]):not([type=checkbox]):not([type=radio]), select, textarea, " +
            ".pfas-switch, .pfas-cell-btn, .pfas-flag, .pfas-seg";
  var NOT_BOX = ".pfas-chips, .pfas-tokens";
  function alignBoxColumns(table) {
    if (table.__pfasBoxCols || !table.tHead || !table.querySelector("tbody input, tbody select, tbody textarea, tbody .pfas-cell-btn, tbody .pfas-flag, tbody .pfas-seg")) { return; }
    table.__pfasBoxCols = true;
    leafHeadings(table).forEach(function (th) {
      var span = Number(th.getAttribute("colspan") || 1) || 1, cells = [];
      for (var k = 0; k < span; k++) { cells = cells.concat(columnCells(table, th.__pfasCol + k)); }
      var boxed = false;
      for (var i = 0; i < cells.length; i++) {
        var c = cells[i];
        if (c.tagName === "TH" || c.querySelector(NOT_BOX)) { return; }      /* row names (a grid's too), chips */
        if (c.querySelector(BOX)) { boxed = true; }
      }
      if (!boxed) { return; }
      th.classList.add("is-box-col");
      cells.forEach(function (c) { c.classList.add("is-box-col"); });
    });
  }
  function initTables(root) {
    root = root || doc;
    var typed = root.querySelectorAll(".pfas-content-area table, .pfas-drawer table, table.pfas-sheet, table.pfas-cf");
    for (var b = 0; b < typed.length; b++) { alignBoxColumns(typed[b]); }
    /* the grids and the tables the config forms draw (pfas-cf); a page's own
       table that borrows cf-coll keeps its own look */
    var all = doc.querySelectorAll("table.pfas-sheet, table.pfas-cf");
    var tables = root.querySelectorAll("table.pfas-sheet, table.pfas-cf, table[data-col-resize]");
    for (var i = 0; i < tables.length; i++) {
      var t = tables[i], at = Array.prototype.indexOf.call(all, t);
      var name = t.getAttribute("data-sheet") || t.getAttribute("data-col-resize") || t.id || String(at < 0 ? i : at);
      initColResize(t, (location.pathname || "") + "#" + name);
      /* an opted-in table: its columns only, its box left as it is */
      if (!t.classList.contains("pfas-sheet") && !t.classList.contains("pfas-cf")) { continue; }
      var wrap = t.closest(".pfas-sheet-wrap, .pfas-scroll-x");
      if (wrap && wrap.classList.contains("pfas-scroll-x")) { wrap.classList.add("is-cf"); }   /* its drawn scrollbar */
      if (wrap) { initScrollCue(wrap); }
    }
    var words = root.querySelectorAll(".pfas-switch-word");
    for (var w = 0; w < words.length; w++) {
      var lab = words[w].closest("label") || words[w].previousElementSibling;
      var box = lab && lab.querySelector("input[type=checkbox]");
      if (box) { switchWord(box); }
    }
    var inherits = root.querySelectorAll("select[data-inherits]");
    for (var h = 0; h < inherits.length; h++) { inheritMark(inherits[h]); }
  }

  /* ── Shared helpers for the input components ────────────────────────────── */
  var N = window.PFAS.numeric;
  var MINUS = "\u2212", idSeq = 0;
  /* Text made safe for HTML, in an element or an attribute: the one escape
     every page's script uses (PFAS.components.esc). */
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  /* The laboratory's day, "YYYY-MM-DD", that the page gives its scripts
     (data-lab-today on the root element, while the zone converts); null
     otherwise, and a script then keeps its own clock. */
  function labToday() {
    var v = doc.documentElement ? doc.documentElement.getAttribute("data-lab-today") : null;
    return v && /^\d{4}-\d{2}-\d{2}$/.test(v) ? v : null;
  }
  function el(tag, cls, text) {
    var e = doc.createElement(tag);
    if (cls) { e.className = cls; }
    if (text !== undefined) { e.textContent = text; }
    return e;
  }
  function fire(input, types) {
    types = types || ["input", "change"];
    for (var i = 0; i < types.length; i++) { input.dispatchEvent(new Event(types[i], { bubbles: true })); }
  }
  /* A script that sets .value without an event (a "Use" button, a calculator)
     must still refresh what the component draws: the instance's own value
     accessor calls the native one, then tells the component. */
  var nativeValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
  function watchValue(input, fn) {
    var fns = input.__pfasWatch;
    if (fns) { fns.push(fn); return; }
    input.__pfasWatch = [fn];
    try {
      Object.defineProperty(input, "value", {
        configurable: true,
        get: function () { return nativeValue.get.call(input); },
        set: function (v) { nativeValue.set.call(input, v); for (var i = 0; i < input.__pfasWatch.length; i++) { input.__pfasWatch[i](); } }
      });
    } catch (e) { /* the component then refreshes on events only */ }
    if (input.form) { input.form.addEventListener("reset", function () { window.setTimeout(fn, 0); }); }
  }
  /* An inserted control (a slider, a chip's text box) belongs to no form: it
     has no name to post, and a page that tracks edits by event.target.form must
     not count it as a change to the form that happens to wrap it. */
  function detach(ctl) { ctl.setAttribute("form", "pfas-no-form"); return ctl; }
  function squash(t) { return String(t || "").replace(/\s+/g, " ").replace(/^\s+|\s+$/g, ""); }
  /* The words of a caption, without the controls and hints drawn inside it. */
  function captionWords(node) {
    var c = node.cloneNode(true), junk = c.querySelectorAll(".pfas-num, .pfas-chips, .pfas-range-track, input, select, textarea, button, .hint, .pfas-hint");
    for (var i = 0; i < junk.length; i++) { if (junk[i].parentNode) { junk[i].parentNode.removeChild(junk[i]); } }
    return squash(c.textContent);
  }
  /* The caption a person reads beside an input that no <label> is tied to:
     the label of the field that holds it (a label or .pfas-label written
     before it, without a for), else the heading of its table column. */
  var FIELD_BOX = ".pfas-form-field, .cf-field";
  function captionNear(input) {
    var field = input.closest(FIELD_BOX);
    if (field) {
      var kids = field.children;
      for (var i = 0; i < kids.length; i++) {
        var k = kids[i];
        if (k === input || k.contains(input)) { break; }
        if ((k.tagName === "LABEL" && !k.getAttribute("for")) || k.classList.contains("pfas-label")) {
          var t = captionWords(k);
          if (t) { return t; }
        }
      }
    }
    var td = input.closest("td"), table = td && td.closest("table");
    if (!table) { return ""; }
    var at = 0;
    for (var c = td.previousElementSibling; c; c = c.previousElementSibling) { at += Number(c.getAttribute("colspan") || 1) || 1; }
    var heads = leafHeadings(table);
    for (var h = 0; h < heads.length; h++) {
      if (heads[h].__pfasCol === at) { return captionWords(heads[h]); }
    }
    return "";
  }
  /* The words that name an input: its aria-label, else what aria-labelledby
     names, else its <label>, else the caption beside it, else `fallback`
     (its name when none is given). */
  function labelText(input, fallback) {
    var t = input.getAttribute("aria-label");
    var by = !t && input.getAttribute("aria-labelledby");
    if (by) {
      t = by.split(/\s+/).map(function (id) { var n = doc.getElementById(id); return n ? captionWords(n) : ""; }).join(" ");
    }
    if (!squash(t) && input.labels && input.labels.length) { t = captionWords(input.labels[0]); }
    if (!squash(t)) { t = captionNear(input); }
    if (!squash(t)) { t = fallback || input.getAttribute("name") || "value"; }
    return squash(t).replace(/\s*\*$/, "");
  }

  /* ── .pfas-num: [−] value [+] around the real number input ──────────────────
     The input stays where it was, named and posted as before; the buttons only
     set its value and say so with input + change. */
  function numEligible(inp) {
    if (inp.type !== "number" || inp.readOnly || inp.disabled || inp.hidden || inp.__pfasNum) { return false; }
    if (inp.classList.contains("no-stepper") || inp.getAttribute("data-stepper") === "off") { return false; }
    /* steppers only where a small step is the natural edit: a value typed
       freely (step any, no declared step) is a reading or a limit, not a count */
    if (inp.getAttribute("step") === "any" && !inp.hasAttribute("data-step")) { return false; }
    if (inp.classList.contains("pfas-sr-hide") || inp.closest("td, th, [data-range], .pfas-num, .pfas-range")) { return false; }
    return true;
  }
  function makeNum(inp) {
    if (inp.__pfasNum) { return inp.__pfasNum; }
    var wrap = el("span", "pfas-num");
    var dec = el("button", "pfas-num-btn is-dec", MINUS), inc = el("button", "pfas-num-btn is-inc", "+");
    dec.type = "button"; inc.type = "button"; dec.tabIndex = -1; inc.tabIndex = -1;
    /* a label that wraps the input would now label the first button: tie it to the input */
    var lab = inp.closest("label");
    if (lab && !lab.htmlFor) { if (!inp.id) { inp.id = "pfas-n-" + (++idSeq); } lab.htmlFor = inp.id; }
    inp.parentNode.insertBefore(wrap, inp);
    wrap.appendChild(dec); wrap.appendChild(inp);
    /* the number an empty box resolves to, muted in the box until a value
       is typed; decoration only (aria-hidden): the box still posts "" */
    var resolved = inp.getAttribute("data-resolved") || "", shownResolved = null;
    if (resolved !== "") {
      wrap.setAttribute("data-resolved", resolved);
      shownResolved = el("span", "pfas-num-resolved", resolved);
      shownResolved.setAttribute("aria-hidden", "true");
      wrap.appendChild(shownResolved);
    }
    wrap.appendChild(inc);
    inp.classList.add("pfas-num-in");
    var stepAttr = inp.getAttribute("step");
    inp.setAttribute("inputmode", stepAttr && stepAttr !== "any" && N.decimals(stepAttr) === 0 ? "numeric" : "decimal");
    var model = { wrap: wrap, input: inp, sync: sync };
    inp.__pfasNum = model;
    function names() {
      var t = labelText(inp);
      dec.setAttribute("aria-label", "Decrease " + t); inc.setAttribute("aria-label", "Increase " + t);
    }
    function stepNow() {
      return N.stepOf({ step: inp.getAttribute("step"), dataStep: inp.getAttribute("data-step"), value: inp.value, placeholder: inp.getAttribute("placeholder") });
    }
    function sync() {
      /* the buttons act on the number the box shows: its value, or the one it resolves to */
      var v = N.toNum(N.startFrom(inp.value, resolved)), lo = N.toNum(inp.getAttribute("min")), hi = N.toNum(inp.getAttribute("max"));
      dec.disabled = isFinite(v) && isFinite(lo) && v <= lo;
      inc.disabled = isFinite(v) && isFinite(hi) && v >= hi;
      var shown = inp.value || inp.getAttribute("placeholder") || resolved;
      inp.style.width = Math.min(16, Math.max(5, String(shown).length + 2)) + "ch";
      /* hidden once anything is typed: a partly typed number ("-", "1e")
         reads "" yet is not an empty box */
      if (shownResolved) { shownResolved.hidden = inp.value !== "" || !!(inp.validity && inp.validity.badInput); }
    }
    function motion(dir) {
      inp.classList.remove("is-up", "is-down");
      void inp.offsetWidth;
      inp.classList.add(dir > 0 ? "is-up" : "is-down");
    }
    function press(dir) {
      var before = inp.value;
      inp.value = String(N.bump(N.startFrom(before, resolved), dir, stepNow(), inp.getAttribute("min"), inp.getAttribute("max")));
      if (inp.value !== before) { fire(inp); motion(dir); }
      sync();
    }
    var timer = null, iv = null;
    function stop() {
      if (timer) { window.clearTimeout(timer); timer = null; }
      if (iv) { window.clearInterval(iv); iv = null; }
    }
    function hold(btn, dir) {
      btn.addEventListener("pointerdown", function (e) {
        if (e.button) { return; }
        e.preventDefault();
        stop();
        press(dir);
        timer = window.setTimeout(function () {
          iv = window.setInterval(function () { press(dir); if (btn.disabled) { stop(); } }, 80);
        }, 400);
      });
      ["pointerup", "pointercancel", "pointerleave", "blur"].forEach(function (t) { btn.addEventListener(t, stop); });
      /* a keyboard press (Enter or Space on the focused button) arrives as a click with no pointer */
      btn.addEventListener("click", function (e) { if (e.detail === 0) { press(dir); } });
      btn.addEventListener("contextmenu", function (e) { e.preventDefault(); });
    }
    hold(dec, -1); hold(inc, 1);
    inp.addEventListener("keydown", function (e) {
      if (e.key === "ArrowUp" || e.key === "ArrowDown") { e.preventDefault(); press(e.key === "ArrowUp" ? 1 : -1); }
    });
    inp.addEventListener("input", sync);
    inp.addEventListener("change", sync);
    inp.addEventListener("animationend", function () { inp.classList.remove("is-up", "is-down"); });
    wrap.addEventListener("focusin", names);
    wrap.addEventListener("pointerenter", names);
    watchValue(inp, sync);
    names(); sync();
    return model;
  }
  function initNums(root) {
    var all = root.querySelectorAll("input[type=number]");
    for (var i = 0; i < all.length; i++) { if (numEligible(all[i])) { makeNum(all[i]); } }
  }

  /* ── Window fields: every box a window holds is the house field ──────────
     A text box is .pfas-input, a choice .pfas-select, free text
     .pfas-textarea, a number the stepper (whatever its step: in a window a
     number is always edited as one), a read-only or table-cell number a
     plain .pfas-input. A house component's own box (chips, picker, date,
     segment, switch, slider) is its own. A box with data-unit shows the
     unit as its suffix. The drawer runs this on every window it opens;
     running it twice changes nothing. */
  var FIELD_SKIP_TYPES = /^(hidden|checkbox|radio|file|range|button|submit|reset|image|color)$/;
  var FIELD_OWN = ".pfas-chips, .pfas-picker, .pfas-date, .pfas-seg, .pfas-switch, .pfas-range-track";
  var FIELD_HOUSE = /(^|\s)(pfas-input|pfas-select|pfas-textarea|pfas-chips-text|pfas-picker-in|pfas-date-text)(\s|$)/;
  function fieldStepper(inp) {
    if (inp.readOnly || inp.disabled || inp.hidden || inp.__pfasNum) { return false; }
    if (inp.classList.contains("no-stepper") || inp.getAttribute("data-stepper") === "off") { return false; }
    return !inp.closest("td, th, [data-range], .pfas-num, .pfas-range");
  }
  function fieldUnit(n) {
    var unit = n.getAttribute("data-unit");
    var box = n.closest(".pfas-num") || n;
    if (!unit || (box.parentNode && box.parentNode.classList.contains("pfas-field-u"))) { return; }
    var wrap = el("span", "pfas-field-u"), u = el("span", "pfas-field-unit", unit);
    u.setAttribute("aria-hidden", "true");
    box.parentNode.insertBefore(wrap, box);
    wrap.appendChild(box);
    wrap.appendChild(u);
  }
  function houseFields(root) {
    if (!root || !root.querySelectorAll) { return root; }
    var all = root.querySelectorAll("input, select, textarea");
    for (var i = 0; i < all.length; i++) {
      var n = all[i], tag = n.tagName;
      if (tag === "INPUT" && FIELD_SKIP_TYPES.test(n.type || "text")) { continue; }
      if (n.classList.contains("pfas-sr-hide") || n.closest(FIELD_OWN) || FIELD_HOUSE.test(n.className)) { continue; }
      if (tag === "SELECT") { n.classList.add("pfas-select"); }
      else if (tag === "TEXTAREA") { n.classList.add("pfas-textarea"); }
      else if (n.type === "number") {
        if (n.closest(".pfas-num")) { /* a stepper or a range end already */ }
        else if (fieldStepper(n)) { makeNum(n); }
        else { n.classList.add("pfas-input"); n.classList.add("is-num"); }
      } else { n.classList.add("pfas-input"); }
      fieldUnit(n);
    }
    return root;
  }
  /* Enter in a box of a window's fields (a field, an Add row, a settings
     block) presses the window's primary button (Done, Add, Set cells),
     unless the box keeps Enter for itself; a window drawn otherwise (a
     record's card, a page's own form) keeps its own keys */
  var FIELD_ENTER_IN = ".pfas-sheet-field, .pfas-pop-row, .cf-settings";
  var FIELD_ENTER_OWN = ".pfas-chips, .pfas-picker, .pfas-date, .pfas-chips-text, .pfas-picker-in, .pfas-date-text";
  function fieldEnter(d, e) {
    var t = e.target;
    if (e.key !== "Enter" || e.defaultPrevented || e.isComposing || e.shiftKey || e.altKey || e.ctrlKey || e.metaKey) { return; }
    if (!t || t.tagName !== "INPUT" || FIELD_SKIP_TYPES.test(t.type || "text") || t.closest(FIELD_ENTER_OWN) ||
        !t.closest(FIELD_ENTER_IN)) { return; }
    var body = d.querySelector(".pfas-drawer-body"), foot = d.querySelector(".pfas-drawer-foot");
    if (!body || !body.contains(t) || !foot || foot.hidden) { return; }
    var go = foot.querySelector(".btn-primary");
    if (!go || go.disabled) { return; }
    e.preventDefault();
    go.click();
  }

  /* ── .pfas-range: [lo] ──●━━━●── [hi] over two existing number inputs ─────────
     [data-range] holds the pair (lo first) with data-scale="lo,hi" and an optional
     data-unit. The sliders carry no name: only the typed inputs are posted, and
     only when a person changes them. A typed value outside the scale widens it. */
  function initRange(w) {
    if (w.__pfas) { return; }
    var ins = w.querySelectorAll("input[type=number]");
    if (ins.length < 2) { return; }
    w.__pfas = true;
    var lo = ins[0], hi = ins[1], unit = w.getAttribute("data-unit") || "";
    /* what an unset end shows: "none" unless the field says (data-empty="" shows nothing) */
    var empty = w.hasAttribute("data-empty") ? w.getAttribute("data-empty") : "none";
    var a0 = N.toNum(lo.getAttribute("min")), b0 = N.toNum(hi.getAttribute("max"));
    var base = N.parseScale(w.getAttribute("data-scale")) || [isFinite(a0) ? a0 : 0, isFinite(b0) && b0 > (isFinite(a0) ? a0 : 0) ? b0 : (isFinite(a0) ? a0 : 0) + 100];
    w.classList.add("pfas-range");
    var nl = makeNum(lo), nh = makeNum(hi);
    nl.wrap.classList.add("is-lo"); nh.wrap.classList.add("is-hi");
    if (!lo.getAttribute("placeholder") && empty) { lo.setAttribute("placeholder", empty); }
    if (!hi.getAttribute("placeholder") && empty) { hi.setAttribute("placeholder", empty); }
    var track = el("div", "pfas-range-track");
    track.appendChild(el("div", "pfas-range-rail")); track.appendChild(el("div", "pfas-range-fill"));
    function slider(which, src) {
      var s = el("input", "pfas-range-" + which);
      s.type = "range"; s.setAttribute("aria-label", labelText(src)); detach(s);
      track.appendChild(s);
      return s;
    }
    var sl = slider("lo", lo), sh = slider("hi", hi);
    function bubble(which) { var b = el("output", "pfas-range-bubble"); b.setAttribute("data-end", which); b.setAttribute("aria-hidden", "true"); track.appendChild(b); return b; }
    var bl = bubble("lo"), bh = bubble("hi");
    var ends = el("div", "pfas-range-ends"); ends.appendChild(el("span")); ends.appendChild(el("span")); track.appendChild(ends);
    var warn = el("div", "pfas-range-warn", "The minimum is above the maximum. Saving will be refused until one is changed.");
    warn.setAttribute("role", "alert"); warn.hidden = true;
    w.appendChild(nl.wrap); w.appendChild(track); w.appendChild(nh.wrap); w.appendChild(warn);

    function stepVal() {
      return N.stepOf({ step: lo.getAttribute("step"), dataStep: lo.getAttribute("data-step"), value: lo.value || hi.value, placeholder: lo.getAttribute("placeholder") });
    }
    function fmt(v) { return String(v) + (unit ? " " + unit : ""); }
    function render() {
      var a = N.toNum(lo.value), b = N.toNum(hi.value), ha = isFinite(a), hb = isFinite(b);
      var sc = N.scaleFor(base, a, b), st = String(stepVal());
      var s2 = [sl, sh];
      for (var i = 0; i < 2; i++) { s2[i].min = String(sc[0]); s2[i].max = String(sc[1]); s2[i].step = st; }
      sl.value = String(ha ? a : sc[0]); sh.value = String(hb ? b : sc[1]);
      sl.classList.toggle("is-empty", !ha); sh.classList.toggle("is-empty", !hb);
      sl.setAttribute("aria-valuetext", ha ? fmt(a) : "not set"); sh.setAttribute("aria-valuetext", hb ? fmt(b) : "not set");
      var fa = N.fraction(ha ? a : sc[0], sc[0], sc[1]), fb = N.fraction(hb ? b : sc[1], sc[0], sc[1]);
      track.style.setProperty("--lo", String(Math.min(fa, fb))); track.style.setProperty("--hi", String(Math.max(fa, fb)));
      bl.style.setProperty("--p", String(fa)); bh.style.setProperty("--p", String(fb));
      bl.textContent = ha ? fmt(a) : empty; bh.textContent = hb ? fmt(b) : empty;
      ends.firstChild.textContent = String(sc[0]); ends.lastChild.textContent = fmt(sc[1]);
      track.classList.toggle("lo-top", fa > 0.5);
      track.classList.toggle("is-blank", !ha && !hb);
      warn.hidden = !(ha && hb && a > b);
    }
    function move(which) {
      var s = which === "lo" ? sl : sh, tgt = which === "lo" ? lo : hi, other = which === "lo" ? hi : lo;
      var v = N.pairClamp(which, N.toNum(s.value), N.toNum(other.value));
      var out = String(N.roundTo(v, N.decimals(stepVal())));
      if (tgt.value !== out) { tgt.value = out; fire(tgt, ["input"]); }
      render();
    }
    function wire(which, s, tgt) {
      s.addEventListener("input", function () { move(which); });
      s.addEventListener("change", function () { if (!s.classList.contains("is-empty")) { fire(tgt, ["change"]); } });
      function show(on) { track.classList.toggle("show-" + which, on); }
      s.addEventListener("focus", function () { show(true); });
      s.addEventListener("blur", function () { show(false); });
      s.addEventListener("pointerdown", function () { show(true); });
      var up = function () { if (doc.activeElement !== s) { show(false); } };
      window.addEventListener("pointerup", up);
      outside.push(up);
    }
    var outside = [];
    w.__pfasDispose = function () {
      outside.forEach(function (f) { window.removeEventListener("pointerup", f); });
      outside = [];
    };
    wire("lo", sl, lo); wire("hi", sh, hi);
    [lo, hi].forEach(function (inp) {
      inp.addEventListener("input", render); inp.addEventListener("change", render);
      watchValue(inp, render);
    });
    render();
  }
  function initRanges(root) {
    var all = root.querySelectorAll("[data-range]");
    for (var i = 0; i < all.length; i++) { initRange(all[i]); }
  }

  /* ── Grid cells: a value button that opens the drawer ────────────────────────
     A td holding one number input shows its value as a button; a declared min/max
     pair (td[data-pair][data-pair-end]) shows "70 - 130 %" with a mini bar. The
     real inputs stay in the DOM, visually hidden, named and posted as before; the
     drawer edits COPIES and writes back on Done / Next. */
  /* a not-assessed cell's hover: profile_grids.NOT_ASSESSED_WORDS */
  var NOT_ASSESSED = "Not assessed for ";
  var SET_TO_NONE = "Set to none";
  function hideInput(inp) {
    inp.classList.add("pfas-sr-hide");
    inp.tabIndex = -1;
    inp.setAttribute("aria-hidden", "true");
  }
  function cellInput(td) {
    var tbl = td.closest("table");
    if (!tbl || tbl.getAttribute("data-cells") === "plain" || td.__pfasCell) { return null; }
    /* a hidden box beside the input (a pair's None marker) is no second control */
    var ctl = td.querySelectorAll("input:not([type=hidden]):not([hidden]), select, textarea");
    if (ctl.length !== 1) { return null; }
    var inp = ctl[0];
    /* a number held off by its None box is still a cell */
    var held = inp.disabled && td.querySelector("input.pfas-none-in");
    if (inp.type !== "number" || inp.readOnly || (inp.disabled && !held) || inp.hidden) { return null; }
    if (inp.classList.contains("no-stepper") || inp.getAttribute("data-stepper") === "off" || inp.getAttribute("data-cell") === "off") { return null; }
    return inp;
  }
  function pairPartner(td, end) {
    var id = td.getAttribute("data-pair"), tr = td.parentNode;
    if (!id || !tr || !tr.querySelectorAll) { return null; }
    var cells = tr.querySelectorAll("td[data-pair]");
    for (var i = 0; i < cells.length; i++) {
      if (cells[i].getAttribute("data-pair") === id && cells[i].getAttribute("data-pair-end") !== end) { return cells[i]; }
    }
    return null;
  }
  /* a cell's column name from its heading, without the unit drawn under it */
  function headerOf(td) {
    var tbl = td.closest("table"), head = tbl && tbl.tHead && tbl.tHead.rows[tbl.tHead.rows.length - 1];
    var th = head && head.cells[td.cellIndex];
    if (!th) { return ""; }
    var c = th.cloneNode(true);
    Array.prototype.forEach.call(c.querySelectorAll(".pfas-th-unit"), function (n) { n.parentNode.removeChild(n); });
    return squash(c.textContent);
  }
  function rowHeading(tr) {
    if (tr.getAttribute("data-label")) { return tr.getAttribute("data-label"); }   /* a sheet row names itself */
    var c = tr.cells[0];
    if (!c) { return ""; }
    var ctl = c.querySelector("input:not([type=hidden]):not([type=checkbox]), select");
    if (ctl) { return squash(ctl.tagName === "SELECT" ? (ctl.options[ctl.selectedIndex] || {}).text : ctl.value); }
    for (var n = c.firstChild; n; n = n.nextSibling) {
      var t = squash(n.textContent);
      if (t) { return t; }
    }
    return "";
  }
  function groupLabel(td) {
    var pane = td.closest(".pfas-pane");
    if (!pane || !pane.id) { return ""; }
    var item = doc.querySelector('.pfas-seg[data-quiet] .pfas-seg-item[data-pane="' + pane.id + '"]');   /* a nested group strip, not the page's own tabs */
    return item ? squash(item.firstChild && item.firstChild.nodeType === 3 ? item.firstChild.textContent : item.textContent).replace(/\s*\(\d+\/\d+\)$/, "") : "";
  }
  function cellTitle(td) {
    var what = td.getAttribute("data-label") || headerOf(td);   /* a declared label, else the column heading */
    var parts = [what, rowHeading(td.parentNode), groupLabel(td)].filter(function (x) { return x; });
    return parts.join(" \u00b7 ");
  }
  function initCell(td, inp) {
    var end = td.getAttribute("data-pair-end");
    var model = { td: td, inp: inp, pair: null };
    if (td.getAttribute("data-pair") && (end === "lo" || end === "hi")) {
      var pt = pairPartner(td, end), pi = pt ? (pt.__pfasCell ? pt.__pfasCell.inp : cellInput(pt)) : null;
      if (pi) {
        var sc = td.getAttribute("data-scale") || pt.getAttribute("data-scale");
        model.pair = { lo: end === "lo" ? inp : pi, hi: end === "lo" ? pi : inp, end: end,
                       scale: N.parseScale(sc) || [0, 100], scaleAttr: sc || "0,100", unit: td.getAttribute("data-unit") || pt.getAttribute("data-unit") || "" };
      }
    }
    /* a pair that can be marked not assessed: its hidden None box (in either
       end's cell), shown as \u2717 while ticked */
    if (model.pair) {
      model.none = td.querySelector("input.pfas-none-in") || (pt && pt.querySelector("input.pfas-none-in")) || null;
    } else {
      model.none = td.querySelector("input.pfas-none-in");     /* a number's: its words come from the cell */
    }
    td.__pfasCell = model;
    td.classList.add("pfas-cell");
    hideInput(inp);
    var btn = el("button", "pfas-cell-btn"); btn.type = "button"; btn.setAttribute("aria-haspopup", "dialog");
    /* a cell that is a limit box keeps its placard, the mark pinned over its corner */
    var plac = null;
    for (var pc = td.firstChild; pc; pc = pc.nextSibling) {
      if (pc.nodeType === 1 && pc.classList.contains("pfas-placard")) { plac = pc; break; }
    }
    if (plac && plac.classList.contains("is-mark")) {
      /* a standards grid cell's mark is pinned to the value's own box, so it
         belongs to that box and not to the cell's edge beside the next one */
      var anchor = el("span", "pfas-cell-anchor");
      td.insertBefore(anchor, plac);
      anchor.appendChild(btn);
      anchor.appendChild(plac);
    } else {
      td.insertBefore(btn, plac);
    }
    model.btn = btn;
    var ownTitle = td.getAttribute("title");        /* the cell's own hover, given back when none is cleared */
    function refresh() {
      var p = model.pair, text, none = model.none ? model.none.checked : false;
      btn.textContent = "";
      var said = td.getAttribute("data-none-hover") || (NOT_ASSESSED + (td.getAttribute("data-none") || ""));
      if (model.none) {
        td.classList.toggle("is-none", none);
        if (none) { td.setAttribute("title", said); } else if (td.getAttribute("title") === said) { td.removeAttribute("title"); }
        if (!p) { inp.disabled = none; }                         /* the box posts "none" in its place */
      }
      /* data-set-none="1": the cell's none is a value, a chosen state drawn
         as a dash (with its meaning on hover), not a blank. A cell with a
         None box is none while the box is ticked; one without is none while
         it is empty. (data-none is another thing: the cell CAN be marked not
         assessed, drawn as a cross.) */
      var setsNone = td.getAttribute("data-set-none") === "1";
      if (none) {
        text = setsNone ? "\u2014" : "\u2717";
        btn.appendChild(el("span", "pfas-cell-txt is-none", text));
        btn.setAttribute("aria-label", cellTitle(td) + ": " + (td.getAttribute("data-none-hover") || "not assessed") + ". Edit");
        return;
      }
      if (!p) {
        /* empty: what blank means for it, its placeholder or the number it
           resolves to (a method default), drawn muted; a None box, not the
           blank, says when a cell that has one is none */
        var v = inp.value, setNone = setsNone && !model.none && v === "";
        text = N.cellText(v, inp.getAttribute("placeholder") || inp.getAttribute("data-resolved"), setNone);
        btn.appendChild(el("span", "pfas-cell-txt" + (v === "" ? " is-none" : ""), text));
        if (setNone) { td.setAttribute("title", SET_TO_NONE); }
        else if (td.getAttribute("title") === SET_TO_NONE) {
          if (ownTitle !== null) { td.setAttribute("title", ownTitle); } else { td.removeAttribute("title"); }
        }
        if (setNone) { btn.setAttribute("aria-label", cellTitle(td) + ": none. Edit"); return; }
        /* the number it resolves to is the method's, never the cell's own */
        if (v === "" && text && !inp.getAttribute("placeholder") && inp.getAttribute("data-resolved")) {
          btn.setAttribute("aria-label", cellTitle(td) + ": " + text + ", method default. Edit");
          return;
        }
      } else {
        var a = p.lo.value, b = p.hi.value;
        var ta = N.cellText(a, p.lo.getAttribute("placeholder")), tb = N.cellText(b, p.hi.getAttribute("placeholder"));
        var unit = p.unit ? " " + p.unit : "";
        /* both ends unset: an empty box; one end open: the bound it sets
           ("\u2265 40 %", "\u2264 130 %"), never a dash beside nothing */
        text = ta === "" && tb === "" ? "" : tb === "" ? "\u2265 " + ta + unit : ta === "" ? "\u2264 " + tb + unit
             : ta + " \u2013 " + tb + unit;
        btn.appendChild(el("span", "pfas-cell-txt" + (a === "" && b === "" ? " is-none" : ""), text));
        var bar = el("span", "pfas-cell-bar"), fill = el("span");
        var s = N.scaleFor(p.scale, a, b), fa = N.fraction(a === "" ? s[0] : a, s[0], s[1]), fb = N.fraction(b === "" ? s[1] : b, s[0], s[1]);
        bar.style.setProperty("--lo", String(Math.min(fa, fb))); bar.style.setProperty("--hi", String(Math.max(fa, fb)));
        if (a === "" && b === "") { bar.classList.add("is-none"); }
        bar.appendChild(fill); btn.appendChild(bar);
      }
      btn.setAttribute("aria-label", cellTitle(td) + ": " + (text || "empty") + ". Edit");
    }
    model.refresh = refresh;
    [inp].concat(model.pair ? [model.pair.lo === inp ? model.pair.hi : model.pair.lo] : []).forEach(function (i) {
      i.addEventListener("input", refresh); i.addEventListener("change", refresh); watchValue(i, refresh);
    });
    if (model.none) { model.none.addEventListener("change", refresh); }
    if (inp.getAttribute("data-shared")) { inp.addEventListener("change", function () { shareValue(inp); }); }
    btn.addEventListener("click", function () { openCell(td); });
    refresh();
  }
  /* A value every row of a column shows (input[data-shared], naming the one
     hidden field that posts it; the row's own input posts nothing): an edit on
     one row is drawn on every row and written to that field. */
  function shareValue(inp) {
    var name = inp.getAttribute("data-shared");
    byAttr(doc.querySelectorAll("input[data-shared]"), "data-shared", name).forEach(function (o) {
      if (o !== inp && o.value !== inp.value) { o.value = inp.value; }
    });
    var field = byAttr(doc.querySelectorAll("input[type=hidden]"), "name", name)[0];
    if (field && field.value !== inp.value) { field.value = inp.value; fire(field, ["change"]); }
  }
  function initCells(root) {
    var all = root.querySelectorAll("td input[type=number]");
    for (var i = 0; i < all.length; i++) {
      var td = all[i].closest("td"), inp = td && cellInput(td);
      if (inp) { initCell(td, inp); }
    }
  }
  function copyNum(real, name) {
    var c = el("input", "");
    c.type = "number";
    ["min", "max", "step", "data-step", "placeholder", "data-resolved"].forEach(function (a) { if (real.hasAttribute(a)) { c.setAttribute(a, real.getAttribute(a)); } });
    c.setAttribute("aria-label", name);
    c.value = real.value;
    return c;
  }
  function nextCell(td) {
    var c = td.__pfasCell;
    for (var tr = td.parentNode.nextElementSibling; tr; tr = tr.nextElementSibling) {
      var cell = tr.cells && tr.cells[td.cellIndex];
      if (cell && cell.__pfasCell && !!cell.__pfasCell.pair === !!c.pair) { return cell; }
    }
    return null;
  }
  function openCell(td) {
    var c = td.__pfasCell, p = c.pair, title = cellTitle(td);
    var body = el("div", "pfas-cell-form"), copies = [], first, noneBox = null;
    if (p) {
      var w = el("div"); w.setAttribute("data-range", ""); w.setAttribute("data-scale", p.scaleAttr); w.setAttribute("data-unit", p.unit);
      var cl = copyNum(p.lo, title + " minimum"), ch = copyNum(p.hi, title + " maximum");
      w.appendChild(cl); w.appendChild(ch); body.appendChild(w);
      copies = [[p.lo, cl], [p.hi, ch]];
      first = p.end === "lo" ? cl : ch;
      initRange(w);
      /* what the cell says of itself (a window every row shares) */
      if (td.getAttribute("data-note")) { body.appendChild(el("p", "pfas-hint", td.getAttribute("data-note"))); }
      /* None: the class is not assessed; its window gives way */
      if (c.none) {
        var lab = el("label", "pfas-cell-none");
        noneBox = detach(el("input"));
        noneBox.type = "checkbox";
        noneBox.checked = c.none.checked;
        lab.appendChild(noneBox);
        lab.appendChild(el("span", "", td.getAttribute("data-none-text") ||
                                       ("None: recovery is not assessed for " + (td.getAttribute("data-none") || ""))));
        body.appendChild(lab);
        var syncNone = function () { cl.disabled = noneBox.checked; ch.disabled = noneBox.checked; };
        noneBox.addEventListener("change", syncNone);
        syncNone();
      }
    } else {
      var cp = copyNum(c.inp, title);
      body.appendChild(cp); makeNum(cp);
      copies = [[c.inp, cp]]; first = cp;
      /* None: a number that can be off (no holding time) */
      if (c.none) {
        var nlab = el("label", "pfas-cell-none");
        noneBox = detach(el("input"));
        noneBox.type = "checkbox";
        noneBox.checked = c.none.checked;
        nlab.appendChild(noneBox);
        nlab.appendChild(el("span", "", td.getAttribute("data-none-text") || ""));
        body.appendChild(nlab);
        var syncOne = function () { if (noneBox.checked) { cp.value = ""; } cp.disabled = noneBox.checked; };
        noneBox.addEventListener("change", syncOne);
        syncOne();
      }
      /* a cell with a calculator (data-calc): the page's script adds it to the
         editor and writes its result into the editor's copy; Done keeps it */
      if (td.getAttribute("data-calc")) {
        td.dispatchEvent(new CustomEvent("pfas:cell-calc", { bubbles: true, detail: { body: body, input: cp } }));
      }
    }
    function commit() {
      if (noneBox) {
        if (noneBox.checked) {
          (p ? [p.lo, p.hi] : [c.inp]).forEach(function (i) { if (i.value !== "") { i.value = ""; fire(i); } });
          if (!c.none.checked) { c.none.checked = true; fire(c.none); }
          return;
        }
        if (c.none.checked) { c.none.checked = false; fire(c.none); }
      }
      for (var i = 0; i < copies.length; i++) {
        if (copies[i][1].value !== copies[i][0].value) { copies[i][0].value = copies[i][1].value; fire(copies[i][0]); }
      }
    }
    var foot = el("div", "pfas-drawer-actions");
    var done = el("button", "btn btn-primary", "Done"), next = el("button", "btn btn-secondary", "Next \u2193");
    done.type = "button"; next.type = "button";
    var after = nextCell(td);
    next.disabled = !after;
    done.addEventListener("click", function () { commit(); drawer.close(); });
    function goNext() {
      commit();
      /* a page that redraws its rows on a change leaves the cells found before commit detached: look again */
      var target = doc.contains(td) ? nextCell(td) : (after && doc.contains(after) ? after : null);
      if (!target) { drawer.close(); return; }
      target.scrollIntoView({ block: "nearest" });
      openCell(target);
    }
    next.addEventListener("click", goNext);
    body.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && e.target.tagName === "INPUT" && e.target.type === "number") { e.preventDefault(); goNext(); }
    });
    foot.appendChild(done); foot.appendChild(next);
    drawer.open(title, body, { footer: foot, focus: first, cls: "is-cell" });
    if (first && first.select) { first.select(); }
  }

  /* ── .pfas-chips: a comma-typed list drawn as chips ──────────────────────────
     input[data-chips] keeps holding the joined text the server reads and is
     hidden. data-chips="pairs" draws "A -> B" for "A=B". data-options is JSON,
     [[value, label], ...]: only those can be added. The input is rewritten only
     when a person adds or removes a chip. */
  function readOptions(inp) {
    var raw = inp.getAttribute("data-options");
    if (!raw) { return null; }
    try {
      var o = JSON.parse(raw);
      return o.map(function (p) { return typeof p === "string" ? [p, p] : [String(p[0]), String(p.length > 1 ? p[1] : p[0])]; });
    } catch (e) { return null; }
  }
  function initChips(inp) {
    if (inp.__pfas) { return; }
    inp.__pfas = true;
    var pairs = inp.getAttribute("data-chips") === "pairs", options = readOptions(inp), name = labelText(inp);
    var wrap = el("div", "pfas-chips"), list = el("ul", "pfas-chips-list"), add = el("div", "pfas-chips-add");
    wrap.setAttribute("role", "group"); wrap.setAttribute("aria-label", name);
    wrap.appendChild(list); wrap.appendChild(add);
    inp.parentNode.insertBefore(wrap, inp.nextSibling);
    hideInput(inp);
    function items() { return pairs ? N.parsePairs(inp.value) : N.parseList(inp.value); }
    function write(arr) { inp.value = pairs ? N.joinPairs(arr) : N.joinList(arr); fire(inp); }
    function labelFor(v) {
      if (!options) { return v; }
      for (var i = 0; i < options.length; i++) { if (options[i][0] === v) { return options[i][1]; } }
      return v;
    }
    function known(v) {
      if (!options) { return true; }
      for (var i = 0; i < options.length; i++) { if (options[i][0] === v) { return true; } }
      return false;
    }
    function select(label) {
      var s = el("select", "pfas-chips-select"); s.setAttribute("aria-label", label);
      return detach(s);
    }
    var ctl = {};
    function fill(s, opts, placeholder) {
      var keep = s.value;
      s.textContent = "";
      var o0 = el("option", "", placeholder); o0.value = ""; s.appendChild(o0);
      opts.forEach(function (o) { var op = el("option", "", o[1]); op.value = o[0]; s.appendChild(op); });
      s.value = keep;
      if (s.value !== keep) { s.value = ""; }
    }
    function build() {
      if (options && pairs) {
        /* the left side is a name of the method's own (free text); only the right side is a listed value */
        ctl.a = el("input", "pfas-chips-text"); ctl.a.type = "text"; ctl.a.setAttribute("aria-label", "Replace " + name); ctl.a.placeholder = "name"; detach(ctl.a);
        ctl.b = select("Judged as");
        ctl.arrow = el("span", "pfas-chips-arrow", "\u2192");
        add.appendChild(ctl.a); add.appendChild(ctl.arrow); add.appendChild(ctl.b);
      } else if (options) { ctl.a = select("Add to " + name); add.appendChild(ctl.a); }
      else if (pairs) {
        ctl.a = el("input", "pfas-chips-text"); ctl.a.type = "text"; ctl.a.setAttribute("aria-label", "Replace " + name); ctl.a.placeholder = "from"; detach(ctl.a);
        ctl.b = el("input", "pfas-chips-text"); ctl.b.type = "text"; ctl.b.setAttribute("aria-label", "Judged as"); ctl.b.placeholder = "as"; detach(ctl.b);
        ctl.arrow = el("span", "pfas-chips-arrow", "\u2192");
        add.appendChild(ctl.a); add.appendChild(ctl.arrow); add.appendChild(ctl.b);
      } else {
        ctl.a = el("input", "pfas-chips-text"); ctl.a.type = "text"; ctl.a.setAttribute("aria-label", "Add to " + name); ctl.a.placeholder = "Add"; detach(ctl.a);
        add.appendChild(ctl.a);
      }
      ctl.btn = el("button", "btn btn-sm btn-secondary pfas-chips-add-btn", "Add"); ctl.btn.type = "button";
      add.appendChild(ctl.btn);
    }
    function draw() {
      var cur = items();
      list.textContent = "";
      cur.forEach(function (it, idx) {
        var li = el("li", "pfas-chips-item" + ((pairs ? known(it[1]) : known(it)) ? "" : " is-unknown"));
        var text = pairs ? labelFor(it[0]) + " \u2192 " + labelFor(it[1]) : labelFor(it);
        li.appendChild(el("span", "pfas-chips-text-label", text));
        var x = el("button", "pfas-chips-x", "\u00d7"); x.type = "button"; x.setAttribute("aria-label", "Remove " + text);
        x.addEventListener("click", function () {
          var arr = items(); arr.splice(idx, 1); write(arr);
          var nx = list.querySelectorAll(".pfas-chips-x");
          (nx[Math.min(idx, nx.length - 1)] || ctl.a).focus();
        });
        li.appendChild(x); list.appendChild(li);
      });
      if (options) {
        var taken = {};
        cur.forEach(function (it) { taken[pairs ? it[0] : it] = true; });
        if (pairs) { fill(ctl.b, options, "as"); }
        else { fill(ctl.a, options.filter(function (o) { return !taken[o[0]]; }), "Add\u2026"); }
      }
    }
    function commit() {
      var arr = items();
      if (pairs) {
        var a = (ctl.a.value || "").replace(/^\s+|\s+$/g, ""), b = (ctl.b.value || "").replace(/^\s+|\s+$/g, "");
        if (!a || !b || a.indexOf("=") >= 0 || b.indexOf("=") >= 0 || /[,;]/.test(a + b)) { return; }
        if (options && !known(b)) { return; }
        arr = arr.filter(function (p) { return p[0] !== a; }); arr.push([a, b]);
        ctl.a.value = ""; ctl.b.value = "";
      } else {
        var fresh = options ? [ctl.a.value] : N.parseList(ctl.a.value);
        fresh = fresh.filter(function (v) { return v && (!options || known(v)); });
        if (!fresh.length) { return; }
        fresh.forEach(function (v) { if (arr.indexOf(v) < 0) { arr.push(v); } });
        ctl.a.value = "";
      }
      write(arr);
      ctl.a.focus();
    }
    build();
    ctl.btn.addEventListener("click", commit);
    add.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && e.target.tagName === "INPUT") { e.preventDefault(); commit(); }
    });
    inp.addEventListener("input", draw); inp.addEventListener("change", draw); watchValue(inp, draw);
    draw();
  }
  function initAllChips(root) {
    var all = root.querySelectorAll("input[data-chips]");
    for (var i = 0; i < all.length; i++) { initChips(all[i]); }
  }

  /* ── .pfas-date: dates and times read ISO 8601 ───────────────────────────────
     A native date box shows the browser's locale (mm/dd/yyyy) and a time box
     its AM/PM. Each becomes a text box that shows and takes YYYY-MM-DD,
     YYYY-MM-DD HH:MM or HH:MM (24-hour), with a calendar button that opens
     the browser's own picker. The native input stays in the form, named and
     valued as before, so what the page posts is unchanged. */
  var DATE_FORMS = {
    "date": { ph: "YYYY-MM-DD", say: "Date", re: /^\d{4}-\d{2}-\d{2}$/ },
    "datetime-local": { ph: "YYYY-MM-DD HH:MM", say: "Date and time", re: /^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?$/ },
    "time": { ph: "HH:MM", say: "Time", re: /^\d{2}:\d{2}(:\d{2})?$/ }
  };
  function initDate(inp) {
    var f = DATE_FORMS[inp.type];
    if (!f || inp.__pfasDate || inp.getAttribute("data-native") === "on") { return; }
    inp.__pfasDate = true;
    var wrap = el("span", "pfas-date-wrap");
    var text = detach(el("input", "pfas-input pfas-date-text is-" + inp.type));
    text.type = "text"; text.inputMode = "numeric"; text.autocomplete = "off";
    text.placeholder = f.ph;
    /* the box is named by the label a person reads, never by the field's
       name in the form */
    text.setAttribute("aria-label", labelText(inp, f.say) + " (" + f.ph + ")");
    if (inp.title) { text.title = inp.title; }
    text.disabled = inp.disabled; text.readOnly = inp.readOnly;
    if (inp.required) { text.required = true; inp.required = false; }
    var btn = el("button", "pfas-date-btn");
    btn.type = "button"; btn.tabIndex = -1; btn.setAttribute("aria-label", "Open the calendar");
    btn.innerHTML = icon(inp.type === "time" ? "time" : "date", { hidden: true }) || (inp.type === "time" ? "Time" : "Date");
    btn.disabled = inp.disabled || inp.readOnly;
    inp.parentNode.insertBefore(wrap, inp);
    wrap.appendChild(text); wrap.appendChild(btn); wrap.appendChild(inp);
    inp.classList.add("pfas-date-native"); inp.tabIndex = -1;
    function show() { text.value = (nativeValue.get.call(inp) || "").replace("T", " ").slice(0, inp.type === "date" ? 10 : 16); }
    function take() {
      var v = text.value.replace(/^\s+|\s+$/g, "");
      if (v !== "" ? !f.re.test(v) : false) { text.setCustomValidity("Use " + f.ph); return; }
      text.setCustomValidity("");
      nativeValue.set.call(inp, inp.type === "datetime-local" ? v.replace(" ", "T") : v);
      if (v !== "" ? nativeValue.get.call(inp) === "" : false) { text.setCustomValidity("Not a date: use " + f.ph); return; }
      fire(inp, ["input", "change"]);
    }
    text.addEventListener("change", take);
    text.addEventListener("keydown", function (e) { if (e.key === "Enter") { take(); } });
    inp.addEventListener("change", show);
    inp.addEventListener("input", show);
    watchValue(inp, show);
    btn.addEventListener("click", function () {
      try { inp.showPicker(); } catch (e) { inp.focus(); }
    });
    show();
  }
  /* Units keep their case under the uppercase header and caption styles: a
     bracketed part of a header's or label's own text ("Reading (g)") is
     wrapped in .pfas-unit, which is never uppercased. */
  var UNIT_PART = /\([^()]{1,24}\)/g;
  function initUnits(root) {
    var heads = root.querySelectorAll("th, .pfas-form-field > label, .pfas-form-field > span:not([class]), .stat-label, .cf-label");
    for (var i = 0; i < heads.length; i++) {
      var h = heads[i];
      if (h.__pfasUnit) { continue; }
      h.__pfasUnit = true;
      var kids = Array.prototype.slice.call(h.childNodes);
      for (var k = 0; k < kids.length; k++) {
        var n = kids[k];
        if (n.nodeType !== 3 || !UNIT_PART.test(n.nodeValue)) { continue; }
        UNIT_PART.lastIndex = 0;
        var frag = doc.createDocumentFragment(), text = n.nodeValue, last = 0, m;
        while ((m = UNIT_PART.exec(text)) !== null) {
          frag.appendChild(doc.createTextNode(text.slice(last, m.index)));
          frag.appendChild(el("span", "pfas-unit", m[0]));
          last = m.index + m[0].length;
        }
        frag.appendChild(doc.createTextNode(text.slice(last)));
        h.replaceChild(frag, n);
      }
    }
  }
  /* ── .pfas-file: a full-size "Choose file" button with the file's name
     beside it, over the real file input (which stays in the form and posts
     the file; the browser's small native control is hidden) ─────────────── */
  function initFile(inp) {
    if (inp.__pfasFile || inp.hidden || inp.getAttribute("data-native") === "on" || inp.closest(".pfas-file, .dropzone, [data-dropzone]")) { return; }
    inp.__pfasFile = true;
    var wrap = el("span", "pfas-file");
    var btn = el("button", "btn btn-secondary pfas-file-btn", inp.multiple ? "Choose files" : "Choose file");
    btn.type = "button";
    btn.disabled = inp.disabled;
    var name = el("span", "pfas-file-name", "No file chosen");
    inp.parentNode.insertBefore(wrap, inp);
    wrap.appendChild(btn); wrap.appendChild(name); wrap.appendChild(inp);
    inp.classList.add("pfas-file-native");
    btn.addEventListener("click", function () { inp.click(); });
    function show() {
      var fs = inp.files || [];
      name.textContent = fs.length === 0 ? "No file chosen" : (fs.length === 1 ? fs[0].name : fs.length + " files");
    }
    inp.addEventListener("change", show);
    if (inp.form) { inp.form.addEventListener("reset", function () { window.setTimeout(show, 0); }); }
  }
  function initFiles(root) {
    var all = root.querySelectorAll('input[type="file"]');
    for (var i = 0; i < all.length; i++) { initFile(all[i]); }
  }
  /* A config-form field shown only while another field holds a value
     (config_forms Field.show_if): hidden, never disabled, so its value still
     posts and a save never clears it. */
  function showIfValue(name) {
    var els = doc.getElementsByName(name);
    for (var i = 0; i < els.length; i++) {
      var e = els[i];
      if (e.type === "checkbox" || e.type === "radio") { if (e.checked) { return e.value; } continue; }
      return e.value;
    }
    return "";
  }
  /* data-show-value: the one value it is shown for; data-show-values: the
     values, space-separated (a block shown for some choices of a segment) */
  function showIfHolds(r) {
    var v = showIfValue(r.getAttribute("data-show-if"));
    var many = r.getAttribute("data-show-values");
    if (many !== null) { return (" " + many + " ").indexOf(" " + v + " ") !== -1 && v !== ""; }
    return v === (r.getAttribute("data-show-value") || "");
  }
  /* A stage or Lab workflow question (record_macros.pt) carries its
     condition as JSON, {"field", "op", "value"}, as logbook_schema.condition_met
     reads it: a hidden question hides what depends on it, and its inputs are
     disabled, so they are neither required nor posted. One whose controlling
     field is not on this page (guided mode, another step) keeps the state the
     server drew from the saved answers. */
  function answerOf(name) {
    var q = doc.querySelector('.lb-q[data-q="' + name + '"]');
    if (!q) { return undefined; }
    if (q.hidden) { return null; }
    var out = [], els = q.querySelectorAll("input, select, textarea");
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      if (el.disabled) { continue; }
      if (el.type === "radio") { if (el.checked) { out.push(el.value); } }
      else if (el.type === "checkbox") { if (el.checked) { out.push(el.getAttribute("data-value") || el.value); } }
      else if (el.type !== "hidden" && el.name === name && (el.value || "").trim()) { out.push(el.value); }
    }
    return out;
  }
  function conditionMet(cond, answers) {
    var op = cond.op || "eq", want = cond.value;
    if (op === "filled") { return answers.length > 0; }
    if (op === "in") {
      var list = Array.isArray(want) ? want : [want];
      return answers.some(function (a) { return list.indexOf(a) !== -1; });
    }
    var hit = answers.indexOf(String(want)) !== -1;
    return op === "eq" ? hit : !hit;
  }
  function applyQuestion(q, raw) {
    var cond;
    try { cond = JSON.parse(raw); } catch (e) { return; }
    var answers = answerOf(cond.field);
    if (answers === undefined) { return; }
    var shown = answers !== null && conditionMet(cond, answers);
    q.hidden = !shown;
    var els = q.querySelectorAll("input, select, textarea, button");
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      if (!shown && !el.disabled) { el.disabled = true; el.setAttribute("data-sif-off", "1"); }
      else if (shown && el.getAttribute("data-sif-off")) { el.disabled = false; el.removeAttribute("data-sif-off"); }
    }
  }
  function applyShowIf(root) {
    var rows = (root || doc).querySelectorAll("[data-show-if]");
    for (var i = 0; i < rows.length; i++) {
      var raw = rows[i].getAttribute("data-show-if");
      if (raw.charAt(0) === "{") { applyQuestion(rows[i], raw); }
      else { rows[i].hidden = !showIfHolds(rows[i]); }
    }
  }
  /* A field that applies to some choices of another (a study kind's own
     fields): greyed and disabled for the rest, so it neither posts nor asks.
     data-enable-if names the field, data-enable-values the choices, space-separated;
     data-enable-also-if / data-enable-also-values name a second field whose
     choices enable it too (a view the first field's rule does not cover).
     A button carrying it (a segment's item) is disabled itself; one that says
     why (data-lock-reason) carries the lock mark and that reason on hover
     while it is off, and neither while it is on. */
  function lockMark(r, locked) {
    var reason = r.getAttribute("data-lock-reason");
    if (!reason) { return; }
    var mark = r.querySelector(".pfas-lock-mark");
    if (locked && !mark) {
      mark = doc.createElement("span");
      mark.className = "pfas-lock-mark";
      mark.setAttribute("aria-hidden", "true");
      mark.innerHTML = icon("lock", { hidden: true });
      r.appendChild(mark);
    } else if (!locked && mark) {
      mark.parentNode.removeChild(mark);
    }
    if (locked) { r.setAttribute("title", reason); } else { r.removeAttribute("title"); }
  }
  function enabledBy(r, field, values) {
    var name = r.getAttribute(field);
    if (!name) { return false; }
    return (" " + (r.getAttribute(values) || "") + " ").indexOf(" " + showIfValue(name) + " ") !== -1;
  }
  function applyEnableIf(root) {
    var rows = (root || doc).querySelectorAll("[data-enable-if]");
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i];
      var on = enabledBy(r, "data-enable-if", "data-enable-values") ||
               enabledBy(r, "data-enable-also-if", "data-enable-also-values");
      r.classList.toggle("is-off", !on);
      if (r.tagName === "BUTTON") { r.disabled = !on; }
      lockMark(r, !on);
      var ins = r.querySelectorAll("input, select, textarea");
      for (var j = 0; j < ins.length; j++) { ins[j].disabled = !on; }
    }
  }
  /* What a rule set Off no longer judges (a QC type's tiers and windows):
     greyed while data-mute-if's field holds one of data-mute-values, unless
     data-mute-unless's field holds one of data-mute-unless-values, and
     still open to read and edit, never disabled. */
  function applyMuteIf(root) {
    var rows = (root || doc).querySelectorAll("[data-mute-if]");
    for (var i = 0; i < rows.length; i++) {
      /* data-mute-blank: a field left blank holds a state inherited as Off */
      var blank = rows[i].hasAttribute("data-mute-blank") && showIfValue(rows[i].getAttribute("data-mute-if")) === "";
      rows[i].classList.toggle("is-muted", (blank || enabledBy(rows[i], "data-mute-if", "data-mute-values")) &&
                               !enabledBy(rows[i], "data-mute-unless", "data-mute-unless-values"));
    }
  }
  function initShowIf(root) {
    if (!root.querySelector("[data-show-if], [data-enable-if], [data-mute-if]")) { return; }
    applyShowIf(doc);
    applyEnableIf(doc);
    applyMuteIf(doc);
    if (doc.__pfasShowIf) { return; }
    doc.__pfasShowIf = true;
    doc.addEventListener("change", function () { applyShowIf(doc); applyEnableIf(doc); applyMuteIf(doc); });
    doc.addEventListener("input", function () { applyShowIf(doc); });
  }
  function initDates(root) {
    var all = root.querySelectorAll('input[type="date"], input[type="datetime-local"], input[type="time"]');
    for (var i = 0; i < all.length; i++) { initDate(all[i]); }
  }

  /* Text with parts that fill in by themselves (a QAPP's title, a document
     ID, a file name's date): users never type the {tokens}. A textarea or
     input with data-tokens ([[key, label]]) is drawn as a box whose tokens are
     chips, inserted from the "Insert:" bar at its foot; the field stays the
     posted one and keeps the tokens. An input is one line: Enter is ignored. */
  function initTokenText(ta) {
    if (ta.__pfasTokens) { return; }
    var tokens;
    try { tokens = JSON.parse(ta.getAttribute("data-tokens") || "[]"); } catch (e) { return; }
    ta.__pfasTokens = true;
    var names = {};
    tokens.forEach(function (t) { names[t[0]] = t[1]; });
    var single = ta.tagName === "INPUT";
    var box = el("div", single ? "pfas-tokens is-line" : "pfas-tokens"), ed = el("div", "pfas-tokens-text"),
        bar = el("div", "pfas-tokens-bar");
    ed.contentEditable = "true";
    ed.setAttribute("role", "textbox");
    ed.setAttribute("aria-multiline", single ? "false" : "true");
    if (single) {
      ed.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); } });
    }
    var lab = ta.labels && ta.labels[0];
    if (lab) {
      ed.setAttribute("aria-label", lab.textContent.trim());
      lab.addEventListener("click", function () { ed.focus(); });
    } else if (ta.getAttribute("aria-label")) {
      ed.setAttribute("aria-label", ta.getAttribute("aria-label"));
    }
    function chip(key) {
      var c = el("span", "pfas-token", names[key] || key);
      c.contentEditable = "false";
      c.setAttribute("data-token", key);
      return c;
    }
    function text(t) {
      t.split("\n").forEach(function (line, j) {
        if (j) { ed.appendChild(doc.createElement("br")); }
        if (line) { ed.appendChild(doc.createTextNode(line)); }
      });
    }
    function load() {
      ed.innerHTML = "";
      var re = /\{([a-z_]+)\}/g, s = ta.value, last = 0, m;
      while ((m = re.exec(s)) !== null) {
        if (!Object.prototype.hasOwnProperty.call(names, m[1])) { continue; }
        text(s.slice(last, m.index));
        ed.appendChild(chip(m[1]));
        last = re.lastIndex;
      }
      text(s.slice(last));
    }
    function save() {
      var out = "";
      (function walk(n) {
        for (var k = 0; k < n.childNodes.length; k++) {
          var c = n.childNodes[k];
          if (c.nodeType === 3) { out += c.nodeValue.replace(/ /g, " "); continue; }
          if (c.nodeType !== 1) { continue; }
          if (c.hasAttribute("data-token")) { out += "{" + c.getAttribute("data-token") + "}"; }
          else if (c.tagName === "BR") { out += "\n"; }
          else {
            /* a line the browser wrapped in its own block when Enter was pressed */
            if ((c.tagName === "DIV" || c.tagName === "P") && out && out.slice(-1) !== "\n") { out += "\n"; }
            walk(c);
          }
        }
      })(ed);
      ta.value = out.replace(/\n+$/, "");
    }
    bar.appendChild(el("span", "pfas-tokens-lead", "Insert:"));
    tokens.forEach(function (t) {
      var b = el("button", "btn-sm btn-secondary", t[1]);
      b.type = "button";
      b.addEventListener("mousedown", function (e) { e.preventDefault(); });   /* the caret stays in the text */
      b.addEventListener("click", function () {
        var sel = window.getSelection(), c = chip(t[0]);
        if (sel.rangeCount && ed.contains(sel.anchorNode)) {
          var r = sel.getRangeAt(0);
          r.deleteContents();
          r.insertNode(c);
          r.setStartAfter(c);
          r.collapse(true);
          sel.removeAllRanges();
          sel.addRange(r);
        } else {
          ed.appendChild(c);
        }
        save();
        fire(ta);
      });
      bar.appendChild(b);
    });
    ed.addEventListener("input", function () { save(); fire(ta, ["change"]); });
    ed.addEventListener("paste", function (e) {          /* plain text only */
      e.preventDefault();
      doc.execCommand("insertText", false, (e.clipboardData || window.clipboardData).getData("text"));
    });
    load();
    ta.parentNode.insertBefore(box, ta);
    box.appendChild(ed);
    box.appendChild(bar);
    box.appendChild(ta);
    ta.hidden = true;
    if (ta.form) {
      ta.form.addEventListener("submit", save);
      ta.form.addEventListener("reset", function () { window.setTimeout(load, 0); });
    }
  }
  function initTokens(root) {
    var all = root.querySelectorAll("textarea[data-tokens], input[data-tokens]");
    for (var i = 0; i < all.length; i++) { initTokenText(all[i]); }
  }

  /* The input components, on PFAS pages only (core's React listings are left alone). */
  function enhance(root) {
    var area = doc.querySelector(".pfas-content-area");
    var scope = !root || root === doc ? area : (area && area.contains(root) ? root : null);
    if (!scope) { return; }
    initRanges(scope);
    initNums(scope);
    initCells(scope);
    initAllChips(scope);
    initDates(scope);
    initUnits(scope);
    initFiles(scope);
    initShowIf(scope);
    initTokens(scope);
    initSheets(scope);
    initEquations(scope);
  }

  /* Rows a form adds and removes (check weights, measurements): [data-rows]
     holds the rows ([data-row]) in its [data-row-list] and a
     <template data-row-template> whose __i__ becomes the next free index, so
     each row posts its own indexed fields. [data-row-add] adds a row,
     [data-row-remove] removes the row it sits in. */
  function initRows(root) {
    var boxes = root.querySelectorAll("[data-rows]");
    for (var i = 0; i < boxes.length; i++) {
      (function (box) {
        if (box.__pfasRows) { return; }
        box.__pfasRows = true;
        var tpl = box.querySelector("template[data-row-template]");
        var list = box.querySelector("[data-row-list]") || box;
        var next = list.querySelectorAll("[data-row]").length;
        box.addEventListener("click", function (e) {
          var rm = e.target.closest("[data-row-remove]");
          if (rm && box.contains(rm)) {
            e.preventDefault();
            var row = rm.closest("[data-row]");
            if (row) { row.parentNode.removeChild(row); }
            return;
          }
          var add = e.target.closest("[data-row-add]");
          if (!add || !tpl || !box.contains(add)) { return; }
          e.preventDefault();
          var t = doc.createElement("template");
          t.innerHTML = tpl.innerHTML.replace(/__i__/g, String(next++));
          var made = t.content.firstElementChild;
          if (!made) { return; }
          list.appendChild(made);
          init(made);
          enhance(made);
          var first = made.querySelector("input, select");
          if (first) { first.focus(); }
        });
      })(boxes[i]);
    }
  }

  /* A dialog: [data-modal-open="id"] opens .pfas-modal#id and [data-modal-close]
     shuts the one it sits in. A list's create dialog (data-new) is also the
     top bar's "+" target when the page registers no hook of its own. */
  function initModals(root) {
    var opens = root.querySelectorAll("[data-modal-open]");
    for (var i = 0; i < opens.length; i++) {
      (function (b) {
        if (b.__pfasModal) { return; }
        b.__pfasModal = true;
        b.addEventListener("click", function (e) {
          var m = doc.getElementById(b.getAttribute("data-modal-open"));
          if (m) { e.preventDefault(); openModal(m); }
        });
      })(opens[i]);
    }
    var shuts = root.querySelectorAll("[data-modal-close]");
    for (var j = 0; j < shuts.length; j++) {
      (function (b) {
        if (b.__pfasModal) { return; }
        b.__pfasModal = true;
        b.addEventListener("click", function (e) {
          var m = b.closest(".pfas-modal");
          if (m) { e.preventDefault(); m.classList.remove("open"); }
        });
      })(shuts[j]);
    }
    var nw = root.querySelector("[data-modal-open][data-new]");
    if (nw && typeof window.pfasOpenNew !== "function") { window.pfasOpenNew = function () { nw.click(); }; }
    /* every dialog box is announced as one, named by its heading */
    var boxes = root.querySelectorAll(".pfas-modal-box:not([role])");
    for (var k = 0; k < boxes.length; k++) {
      var box = boxes[k], head = box.querySelector("h2, h3");
      box.setAttribute("role", "dialog");
      box.setAttribute("aria-modal", "true");
      if (head) {
        if (!head.id) { head.id = "pfas-dialog-" + (++idSeq); }
        box.setAttribute("aria-labelledby", head.id);
      }
    }
  }

  /* Core listings: the column menu sits in the filter row, after the state
     filters, instead of on a line of its own above the table. React owns both
     nodes, so a button in the row clicks core's own link, which stays hidden. */
  var COLS = 'a[aria-label="Configure table columns"]';
  function placeColumnButtons() {
    var boxes = doc.querySelectorAll(".listing-container");
    for (var i = 0; i < boxes.length; i++) {
      var box = boxes[i], link = box.querySelector(".table-responsive " + COLS);
      var bar = box.querySelector(".top-toolbar .filterbar");
      if (!link || !bar || box.closest(".pfas-content-area")) { continue; }
      var btn = bar.querySelector(".pfas-cols-btn");
      if (!btn) {
        btn = el("button", "nav-item btn btn-sm btn-outline-secondary mr-1 mb-1 pfas-cols-btn");
        btn.type = "button";
        btn.setAttribute("aria-label", link.getAttribute("aria-label"));
        btn.title = link.getAttribute("aria-label");
        btn.innerHTML = icon("more", { hidden: true }) || "\u22ef";
        btn.addEventListener("click", function (e) {
          e.preventDefault();
          var b = e.currentTarget.closest(".listing-container"), l = b && b.querySelector(COLS);
          if (l) { l.click(); }
        });
      }
      if (bar.lastElementChild !== btn) { bar.appendChild(btn); }
      box.classList.add("pfas-cols-moved");
    }
  }
  /* Core listings: the search box has a visible label, tied to it. React
     owns the group, so the label is added at its end (the overlay's CSS
     draws it first) and the box keeps core's own markup. */
  function labelListSearch() {
    var boxes = doc.querySelectorAll(".listing-container .top-toolbar .input-group");
    for (var i = 0; i < boxes.length; i++) {
      var group = boxes[i], box = group.querySelector('input[type="text"], input[type="search"]');
      if (!box || group.closest(".pfas-content-area") || group.querySelector(".pfas-list-search-label")) { continue; }
      if (!box.id) { box.id = "pfas-list-search-" + (++idSeq); }
      var lab = el("label", "input-group-prepend pfas-list-search-label");
      lab.htmlFor = box.id;
      lab.appendChild(el("span", "input-group-text", "Search"));
      group.appendChild(lab);
    }
  }
  function watchListings() {
    /* core pages only; the listing renders after load, so watch from the start */
    var root = doc.querySelector(".pfas-content-area") ? null : (doc.getElementById("content") || doc.body);
    if (!root || !window.MutationObserver || root.__pfasCols) { return; }
    root.__pfasCols = true;
    var pending = false;
    new MutationObserver(function () {
      if (pending) { return; }
      pending = true;
      window.setTimeout(function () { pending = false; placeColumnButtons(); labelListSearch(); stateCells(root); coreImages(root); }, 50);
    }).observe(root, { childList: true, subtree: true });
    placeColumnButtons();
    labelListSearch();
    stateCells(root);
    coreImages(root);
  }
  /* core's listing draws a sample's flags as coloured images beside its ID:
     Late as the failure diamond, all analyses on a worksheet as the
     navigation's worksheet picture, each with the image's own words as its
     name and tooltip (icons.py). The image stays in the page, hidden, so the
     listing keeps what it drew; a cell already drawn is left alone. */
  var CORE_IMG = { "late.svg": ["fail", null], "worksheet.svg": [null, "ico-worksheets"] };
  function coreImages(root) {
    var imgs = (root || doc).querySelectorAll("td img[src]"), i, im, file, kind, words, tip, wrap;
    for (i = 0; i < imgs.length; i++) {
      im = imgs[i];
      if (im.getAttribute("data-pfas-drawn")) { continue; }
      file = (im.getAttribute("src") || "").split("?")[0].split("/").pop();
      kind = CORE_IMG[file];
      if (!kind) { continue; }
      words = im.getAttribute("title") || im.getAttribute("alt") || "";
      if (kind[0]) {
        tip = tipIcon(kind[0], words);
        if (tip.indexOf("<") !== 0) { continue; }
      } else {
        tip = '<span class="pfas-tip" tabindex="0" role="img" aria-label="' + esc(words) + '" data-pfas-tip="' + esc(words) +
              '"><svg class="pfas-ico" aria-hidden="true"><use href="#' + kind[1] + '"></use></svg></span>';
      }
      wrap = doc.createElement("span"); wrap.innerHTML = tip;
      im.setAttribute("data-pfas-drawn", "1");
      im.className = (im.className ? im.className + " " : "") + "pfas-core-img";
      im.parentNode.insertBefore(wrap.firstChild, im);
    }
  }
  /* a sample's state in core's listing (its State column) as the stage's
     picture alone (icons.py, the same five stages as Worksheet status), its
     word as the picture's name and tooltip; a state that is no stage
     (cancelled, invalid, stored...) keeps its word. The listing redraws its
     rows, so this runs again after each redraw and skips a cell it drew. */
  var STATE_STAGE = { "Received": ["received", "done"], "To be verified": ["verify", "current"],
                      "Verified": ["verify", "done"], "Published": ["issued", "done"],
                      "Due": ["received", "pending"], "Sample due": ["received", "pending"],
                      "Registered": ["received", "pending"], "To be sampled": ["received", "pending"],
                      "Scheduled sampling": ["received", "pending"], "To be preserved": ["received", "pending"] };
  var STEP_STATE = { done: "done", current: "now", pending: "next" };
  function stateCells(root) {
    var cells = (root || doc).querySelectorAll("td.state_title"), i, td, word, st, tip, holder, words;
    for (i = 0; i < cells.length; i++) {
      td = cells[i];
      words = td.querySelector(".pfas-state-word");
      word = (words ? words.textContent : td.textContent || "").replace(/^\s+|\s+$/g, "");
      st = STATE_STAGE[word];
      if (!st) { continue; }
      tip = td.querySelector(".pfas-tip");
      if (tip && tip.getAttribute("data-pfas-tip") === word) { continue; }
      holder = td.querySelector("span span") || td.querySelector("span") || td;
      tip = tipIcon(st[0], word, { state: STEP_STATE[st[1]] });
      if (tip.indexOf("<") !== 0) { continue; }   /* no drawings on the page: the word stays */
      if (holder !== td) { holder.className = (holder.className ? holder.className + " " : "") + "pfas-state-word"; }
      var old = td.querySelector(".pfas-tip"); if (old) { old.parentNode.removeChild(old); }
      var wrap = doc.createElement("span"); wrap.innerHTML = tip;
      td.insertBefore(wrap.firstChild, td.firstChild);
    }
  }

  /* .pfas-multi: a list of checkboxes drawn as one-line multi-select. The
     checkboxes stay the posted fields; ticking an item ticks its box. */
  function initMulti(el) {
    if (el.__pfas) { return; }
    el.__pfas = true;
    var N = window.PFAS.numeric, noun = el.getAttribute("data-more") || "";
    var items = Array.prototype.map.call(el.querySelectorAll("input[type=checkbox]"), function (inp) {
      var lab = inp.closest("label");
      return { v: inp.name, t: (lab ? lab.textContent : inp.name).replace(/^\s+|\s+$/g, ""), input: inp };
    });
    var src = el.querySelector(".cf-chips");
    if (src) { src.hidden = true; }
    var field = doc.createElement("div"); field.className = "pfas-multi-field";
    var panel = doc.createElement("div"); panel.className = "pfas-multi-panel"; panel.hidden = true;
    panel.innerHTML = '<input type="search" class="pfas-multi-search" aria-label="Search" placeholder="Search">' +
                      '<ul class="pfas-multi-list" role="listbox"></ul><div class="pfas-multi-foot"></div>';
    el.appendChild(field); el.appendChild(panel);
    var search = panel.querySelector("input"), list = panel.querySelector("ul"), foot = panel.querySelector(".pfas-multi-foot");
    function chosen() { return items.filter(function (i) { return i.input.checked; }); }
    function render() {
      var ch = chosen(), sum = N.multiSummary(ch.map(function (i) { return i.t; }));
      field.innerHTML = "";
      sum.tags.forEach(function (t, k) {
        var tag = doc.createElement("span"); tag.className = "pfas-chips-item";
        tag.innerHTML = '<span class="pfas-chips-text-label"></span><button type="button" class="pfas-chips-x">\u00d7</button>';
        tag.firstChild.textContent = t;
        tag.lastChild.setAttribute("aria-label", "Remove " + t);
        tag.lastChild.addEventListener("click", function (e) { e.stopPropagation(); ch[k].input.checked = false; render(); });
        field.appendChild(tag);
      });
      if (sum.more) { var m = doc.createElement("span"); m.className = "pfas-multi-more"; m.textContent = "+" + sum.more + " more"; field.appendChild(m); }
      var n = doc.createElement("span"); n.className = "pfas-multi-count"; n.textContent = ch.length ? String(ch.length) : "Choose";
      field.appendChild(n);
      if (ch.length) {
        var clr = doc.createElement("button"); clr.type = "button"; clr.className = "pfas-chips-x"; clr.textContent = "\u00d7";
        clr.setAttribute("aria-label", "Clear all");
        clr.addEventListener("click", function (e) { e.stopPropagation(); items.forEach(function (i) { i.input.checked = false; }); render(); });
        field.appendChild(clr);
      }
      var rest = N.multiFilter(items, search.value, ch.map(function (i) { return i.v; }));
      list.innerHTML = "";
      rest.forEach(function (i) {
        var li = doc.createElement("li"); li.setAttribute("role", "option"); li.textContent = i.t;
        li.addEventListener("click", function () { i.input.checked = true; render(); });
        list.appendChild(li);
      });
      foot.textContent = N.multiFooter(ch.length, items.length - ch.length, noun);
    }
    field.addEventListener("click", function () { panel.hidden = !panel.hidden; if (!panel.hidden) { search.focus(); } });
    search.addEventListener("input", render);
    doc.addEventListener("click", function (e) { if (!el.contains(e.target)) { panel.hidden = true; } });
    render();
  }

  /* ── .pfas-picker: a search box adding tokens with a cross ───────────────────
     The chosen values are JSON in ONE hidden field named data-name (the
     picker's own, else the form control of that name: a collection row's),
     the field the server reads: a field posted once per value would reach
     the save as its first value only. A picker with no data-name keeps its
     list in its own nameless hidden field: a choice in a dialog that posts
     nothing. Picking writes that field and fires a
     bubbling input and change on it (the footer counts it as its row or
     setting, a preview redraws); a value written into it from elsewhere is
     drawn on its change. data-options is JSON [[value, label], ...];
     data-noun and data-title word the search box ("Search <noun> to add to
     <title>") and the empty list. The search box posts nothing and saves
     with no form. */
  function pickerField(el) {
    var name = el.getAttribute("data-name") || "";
    var own = el.querySelector('input[type="hidden"]');
    if (own && own.name === name) { return own; }
    var all = doc.querySelectorAll("input[name]");
    for (var i = 0; i < all.length; i++) { if (all[i].name === name) { return all[i]; } }
    return null;
  }
  function readJSON(text, fallback) {
    try { var v = JSON.parse(text || ""); return v === null || v === undefined ? fallback : v; } catch (e) { return fallback; }
  }
  function initPicker(el) {
    if (el.__pfas) { return; }
    var field = pickerField(el);
    if (!field) { return; }
    el.__pfas = true;
    var N = window.PFAS.numeric;
    var opts = readJSON(el.getAttribute("data-options"), []).map(function (o) { return { v: o[0], t: o[1] }; });
    function label(v) { var o = opts.filter(function (x) { return x.v === v; })[0]; return o ? o.t : v; }
    function chosen() { var v = readJSON(field.value, []); return Object.prototype.toString.call(v) === "[object Array]" ? v : []; }
    var sel = doc.createElement("div"); sel.className = "pfas-picker-sel";
    var box = doc.createElement("input"); box.type = "search"; box.className = "pfas-picker-in";
    box.setAttribute("form", "pfas-no-form"); box.setAttribute("autocomplete", "off");
    var list = doc.createElement("ul"); list.className = "pfas-picker-list"; list.setAttribute("role", "listbox");
    el.appendChild(sel); el.appendChild(box); el.appendChild(list);
    function write(values) {
      field.value = JSON.stringify(values);
      field.dispatchEvent(new Event("input", { bubbles: true }));
      field.dispatchEvent(new Event("change", { bubbles: true }));
    }
    function matches() { return N.multiFilter(opts, box.value, chosen()); }
    function add(v) { var now = chosen(); if (now.indexOf(v) === -1) { now.push(v); } box.value = ""; write(now); }
    function render() {
      var noun = el.getAttribute("data-noun") || "", title = el.getAttribute("data-title") || "";
      box.setAttribute("placeholder", "Search " + noun + " to add to " + title);
      box.setAttribute("aria-label", "Add " + noun + " to " + title);
      var now = chosen();
      sel.textContent = "";
      if (!now.length) {
        var none = doc.createElement("span"); none.className = "pfas-picker-empty";
        none.textContent = "No " + noun + " yet: " + title + " applies nowhere until you add some.";
        sel.appendChild(none);
      }
      now.forEach(function (v) {
        var tok = doc.createElement("button"); tok.type = "button"; tok.className = "pfas-tok";
        tok.textContent = label(v) + " ";
        var tx = doc.createElement("span"); tx.className = "pfas-tok-x"; tx.setAttribute("aria-hidden", "true");
        tx.innerHTML = icon("close", { hidden: true }); tok.appendChild(tx);
        tok.setAttribute("aria-label", "Remove " + label(v));
        tok.addEventListener("click", function () { write(chosen().filter(function (x) { return x !== v; })); });
        sel.appendChild(tok);
      });
      list.textContent = "";
      /* the options not chosen, matching the search: while it is typed in or has focus */
      var rest = box.value || doc.activeElement === box ? matches() : [];
      rest.forEach(function (o) {
        var li = doc.createElement("li"); li.setAttribute("role", "option"); li.textContent = o.t;
        li.addEventListener("click", function () { add(o.v); box.focus(); });
        list.appendChild(li);
      });
      list.hidden = !rest.length;
    }
    box.addEventListener("input", render);
    box.addEventListener("focus", render);
    box.addEventListener("blur", function () { window.setTimeout(render, 200); });   /* after a click on an option */
    box.addEventListener("keydown", function (e) {
      if (e.key !== "Enter") { return; }
      e.preventDefault();                       /* never submits the form */
      var first = matches()[0];
      if (first) { add(first.v); }
    });
    field.addEventListener("change", render);
    el.__pfasDispose = function () { field.removeEventListener("change", render); };
    el.__pfasRender = render;
    render();
  }
  /* .pfas-picker-lists: a collection's pickers, one per row ("<row>
     <label>"), kept with the rows: a row named, renamed or rescoped redraws
     its picker, hidden while the row's data-show control does not hold
     data-show-value; a row added (+ Add) gets one. Its attributes name the
     rows' controls: data-prefix + index + "__" + data-column (the hidden
     field), data-key (the row's name), data-show. */
  function initPickerLists(host) {
    if (host.__pfas) { return; }
    host.__pfas = true;
    function a(n) { return host.getAttribute(n) || ""; }
    var prefix = a("data-prefix");
    function control(name) {
      var all = doc.querySelectorAll("input[name], select[name]");
      for (var i = 0; i < all.length; i++) { if (all[i].name === name) { return all[i]; } }
      return null;
    }
    function sync() {
      var tail = "__" + a("data-column"), seen = {};
      Array.prototype.forEach.call(doc.querySelectorAll("input[name]"), function (f) {
        var n = f.name;
        if (n.indexOf(prefix) !== 0 || n.slice(-tail.length) !== tail) { return; }
        var row = n.slice(prefix.length, n.length - tail.length);
        if (!/^\d+$/.test(row)) { return; }
        seen[n] = true;
        var key = control(prefix + row + "__" + a("data-key")), show = control(prefix + row + "__" + a("data-show"));
        var name = key ? String(key.value || "") : "";
        var item = null;
        Array.prototype.forEach.call(host.querySelectorAll(".pfas-form-field"), function (r) {
          if (r.getAttribute("data-for") === n) { item = r; }
        });
        if (!item) {
          item = doc.createElement("div"); item.className = "pfas-form-field is-full"; item.setAttribute("data-for", n);
          var lab = doc.createElement("div"); lab.className = "cf-label"; item.appendChild(lab);
          var pk = doc.createElement("div"); pk.className = "pfas-picker"; pk.setAttribute("data-name", n);
          pk.setAttribute("data-options", a("data-options")); pk.setAttribute("data-noun", a("data-noun"));
          item.appendChild(pk);
          host.appendChild(item);
        }
        var picker = item.querySelector(".pfas-picker");
        item.querySelector(".cf-label").textContent = name + " " + a("data-label");
        picker.setAttribute("data-title", name);
        item.hidden = !name || (a("data-show") ? (show ? show.value : "") !== a("data-show-value") : false);
        initPicker(picker);
        if (picker.__pfasRender) { picker.__pfasRender(); }
      });
      Array.prototype.forEach.call(host.querySelectorAll(".pfas-form-field"), function (r) {
        if (!seen[r.getAttribute("data-for")]) { r.parentNode.removeChild(r); }
      });
    }
    function onEdit(e) {
      var n = e.target && e.target.name ? String(e.target.name) : "";
      if (n.indexOf(prefix) === 0) { sync(); }
    }
    doc.addEventListener("input", onEdit);
    doc.addEventListener("change", onEdit);
    doc.addEventListener("click", function (e) {
      if (e.target.closest && e.target.closest(".cf-add-row")) { window.setTimeout(sync, 0); }
    });
    sync();
  }

  /* ── .pfas-sheet: a tab's one grid (profile_grids.py draws it) ───────────────
     The table's inputs are the posted fields. A row's check box selects it and
     the bar above the grid counts the selection; "Edit selected" opens the
     drawer on the row's <template> (the same cells as a vertical list): for one
     row with the values its cells hold now, for several with every field at
     "Leave as is"; either way only what is changed in the drawer is written
     back. A column switch sets every row's switch in its column, and a flag
     column's "\u2713 all" chip reports every row in it; a panel flag opens its
     cell's editor; a links cell's count opens its list; Columns shows and
     hides the columns. The drawer edits copies and writes them back on Done,
     as openCell does. A folding sheet (data-fold) draws every group folded to
     its row: the row's toggle opens it (the members shown, aria-expanded and
     is-folded following) and tells the page (pfas:sheet-fold), which may
     remember it; a group row's box ticks every member, folded or not. */
  var sheetPop = null;
  /* closing a popover runs what it was opened with (a flag's editor):
     with keep, what was edited in it is written (a click outside it, on its
     own cell or on another); without (Escape), it is discarded */
  function closeSheetPop(keep) {
    if (!sheetPop) { return; }
    var p = sheetPop;
    sheetPop = null;
    /* it fades out as it came, then hides */
    leave(p.pop, "is-leaving", function () { p.pop.hidden = true; });
    p.btn.setAttribute("aria-expanded", "false");
    if (p.close) { p.close(keep !== false); }
  }
  /* a popover is fixed to the viewport, under what opened it: the grid's own
     scroll box would clip it */
  function placeSheetPop(btn, pop) {
    var r = btn.getBoundingClientRect();
    pop.style.left = Math.round(r.left) + "px";
    pop.style.top = Math.round(r.bottom + 4) + "px";
  }
  function openSheetPop(btn, pop, close) {
    var same = sheetPop && sheetPop.pop === pop;
    closeSheetPop();
    if (same || !pop) { return; }
    houseFields(pop);
    placeSheetPop(btn, pop);
    stay(pop, "is-leaving");
    pop.hidden = false;
    btn.setAttribute("aria-expanded", "true");
    sheetPop = { btn: btn, pop: pop, close: close || null };
  }
  /* the grid scrolled: an editor stays open on its cell (nothing written,
     nothing lost); a list or the picker closes */
  function scrollSheetPop() {
    if (sheetPop && sheetPop.close) { placeSheetPop(sheetPop.btn, sheetPop.pop); } else { closeSheetPop(); }
  }
  function sheetBox(root) {
    if (!root) { return null; }
    if (root.classList && root.classList.contains("pfas-sheet-box")) { return root; }
    return (root.closest && root.closest(".pfas-sheet-box")) || (root.querySelector && root.querySelector(".pfas-sheet-box"));
  }
  function byAttr(nodes, attr, value) {
    return Array.prototype.filter.call(nodes, function (n) { return n.getAttribute(attr) === value; });
  }
  function sheetChecks(box) { return Array.prototype.slice.call(box.querySelectorAll(".pfas-sheet-check")); }
  function sheetRowOf(box, key) { return byAttr(box.querySelectorAll("tr[data-row]"), "data-row", key)[0] || null; }
  /* a cell's posted controls, in order (a pair: min, then max) */
  function sheetInputs(tr, col) {
    var out = [];
    byAttr(tr.querySelectorAll("td[data-col]"), "data-col", col).forEach(function (td) {
      out.push.apply(out, td.querySelectorAll(".pfas-sheet-in"));
    });
    return out;
  }
  function sheetSelection(root) {
    var box = sheetBox(root);
    if (!box) { return []; }
    return sheetChecks(box).filter(function (c) { return c.checked; })
      .map(function (c) { return c.closest("tr").getAttribute("data-row"); });
  }
  function sheetSync(box) {
    var keys = sheetSelection(box), checks = sheetChecks(box), table = box.querySelector(".pfas-sheet");
    var bar = box.querySelector(".pfas-sheet-bar"), all = box.querySelector(".pfas-sheet-all");
    if (bar) {
      bar.hidden = !keys.length;
      bar.querySelector(".pfas-sheet-count").textContent = keys.length + " selected";
    }
    if (all) {
      all.checked = !!checks.length && keys.length === checks.length;
      all.indeterminate = keys.length > 0 && keys.length < checks.length;
    }
    checks.forEach(function (c) { c.closest("tr").classList.toggle("is-selected", c.checked); });
    /* a group's box says whether every member is ticked, or some */
    Array.prototype.forEach.call(box.querySelectorAll(".pfas-group-check"), function (g) {
      var mine = groupChecks(box, g.getAttribute("data-group")), on = mine.filter(function (c) { return c.checked; });
      g.checked = !!mine.length && on.length === mine.length;
      g.indeterminate = on.length > 0 && on.length < mine.length;
    });
    syncRemove(box);
    table.dispatchEvent(new CustomEvent("pfas:sheet-select", { bubbles: true, detail: { sheet: table.getAttribute("data-sheet"), rows: keys } }));
  }
  /* a folding group: its member rows, their boxes, and open or folded */
  function groupMembers(box, key) { return byAttr(box.querySelectorAll("tr[data-in-group]"), "data-in-group", key); }
  function groupChecks(box, key) {
    var out = [];
    groupMembers(box, key).forEach(function (tr) { out.push.apply(out, tr.querySelectorAll(".pfas-sheet-check")); });
    return out;
  }
  function foldGroup(box, key, open) {
    var row = byAttr(box.querySelectorAll("tr.pfas-sheet-grouprow"), "data-group", key)[0];
    if (!row) { return false; }
    row.setAttribute("aria-expanded", open ? "true" : "false");
    row.classList.toggle("is-folded", !open);
    var t = row.querySelector(".pfas-group-toggle");
    if (t) { t.setAttribute("aria-expanded", open ? "true" : "false"); }
    groupMembers(box, key).forEach(function (tr, i) {
      var shown = tr.hidden && open;
      tr.hidden = !open;
      /* a group opened: its first rows fade in (a row cannot grow) */
      if (shown && i < STAGGER) { arrive(tr, "is-arriving"); }
    });
    return true;
  }
  function colSwitchOf(box, col) { return byAttr(box.querySelectorAll(".pfas-sheet-colswitch input"), "data-col", col)[0] || null; }
  function sheetSwitches(box, col) {
    return Array.prototype.map.call(box.querySelectorAll("tr[data-row]"), function (tr) { return sheetInputs(tr, col)[0]; })
      .filter(function (i) { return i && i.type === "checkbox"; });
  }
  function syncColSwitch(box, col) {
    var sw = colSwitchOf(box, col), boxes = sheetSwitches(box, col);
    if (sw) { sw.checked = !!boxes.length && boxes.every(function (b) { return b.checked; }); }
  }
  /* a column switch, or a flag column's chip: every row's box in the column
     (a flag's hidden panel box; its cell redraws on the change) */
  function setColumn(box, col, on) {
    sheetSwitches(box, col).forEach(function (b) { if (b.checked !== on) { b.checked = on; fire(b); } });
  }
  /* ── a panel flag: \u2713 / \u2717, or the RL when one is set, over its cell's
     hidden panel box (the posted control). A click opens the cell's editor:
     Reported \u2713 / \u2717 and the RL, written on close into the box and the RL
     input of the row (in the RL column, behind the picker), then the cell is
     drawn again. A cell left out when the page was drawn has no RL input:
     it carries its row's RL input hidden (profile_grids), so reporting it
     and typing its RL save together. Escape discards the edit. */
  function flagBox(holder) { return holder.querySelector("input.pfas-sheet-in[type=checkbox]"); }
  /* the input of its row a flag names: data-rl-name, data-mdl-name */
  function flagNamed(btn, field) {
    var name = btn.getAttribute("data-" + field + "-name"), tr = btn.closest("tr");
    return name && tr ? byAttr(tr.querySelectorAll("input[name]"), "name", name)[0] || null : null;
  }
  function flagRl(btn) { return flagNamed(btn, "rl"); }
  /* the words profile_grids._flag_words and _flag_state write; only the
     drawer's flag, which flips, is pressed or not */
  /* a grid flag over an RL (data-rl-name) with none typed shows the RL that
     applies, the lowest calibrator's (data-rl-derived), muted; with neither
     it says "no RL", never a bare \u2713 */
  function drawFlag(btn, on, rl) {
    var hasRl = btn.hasAttribute("data-rl-name") && !btn.hasAttribute("aria-pressed");
    var derived = hasRl ? btn.getAttribute("data-rl-derived") || "" : "";
    btn.textContent = on ? (rl || derived || (hasRl ? "no RL" : "\u2713")) : "\u2717";
    btn.classList.toggle("is-rl", on && !!rl);
    btn.classList.toggle("is-derived", on && hasRl && !rl);
    btn.classList.toggle("is-out", !on);
    if (btn.hasAttribute("aria-pressed")) { btn.setAttribute("aria-pressed", on ? "true" : "false"); }
    btn.setAttribute("aria-label", (btn.getAttribute("data-label") || "") + ": " +
                     (on ? (rl ? "reported, RL " + rl : derived ? "reported, RL " + derived + " from the lowest calibrator"
                                : hasRl ? "reported, no RL" : "reported") : "left out"));
  }
  function syncFlag(td) {
    var btn = td && td.querySelector(".pfas-flag"), cb = btn && flagBox(td);
    if (!cb) { return; }
    var rin = flagRl(btn), rl = rin ? String(rin.value || "") : "";
    /* the RL the cell carries, as profile_grids draws it: none while left out */
    if (rin) { btn.setAttribute("data-rl", cb.checked ? rl : ""); }
    drawFlag(btn, cb.checked, rl);
    td.classList.toggle("is-out", !cb.checked);
  }
  function openFlag(td) {
    var btn = td && td.querySelector(".pfas-flag"), cb = btn && flagBox(td), box = btn && sheetBox(td);
    if (!cb || !box || btn.disabled) { return; }
    var pop = box.__pfasFlagPop;
    if (pop && sheetPop && sheetPop.pop === pop && pop.__pfasTd === td) { closeSheetPop(); return; }
    closeSheetPop();
    if (!pop) {
      pop = box.__pfasFlagPop = el("div", "pfas-sheet-pop is-flag");
      pop.setAttribute("role", "dialog");
      pop.hidden = true;
      box.appendChild(pop);
    }
    pop.__pfasTd = td;
    pop.innerHTML = "";
    var tr = td.closest("tr"), rin = flagRl(btn), unit = td.getAttribute("data-unit");
    var title = (tr.getAttribute("data-label") || "") + " \u00b7 " + (td.getAttribute("data-label") || "");
    pop.setAttribute("aria-label", title);
    pop.appendChild(el("div", "pfas-flag-h", title));
    var row = el("div", "pfas-flag-row"), seg = el("div", "pfas-seg pfas-seg-sm is-fit");
    seg.setAttribute("role", "group");
    seg.setAttribute("aria-label", "Reported");
    var yes = el("button", "pfas-seg-item", "\u2713"), no = el("button", "pfas-seg-item", "\u2717");
    [yes, no].forEach(function (b, i) { b.type = "button"; b.setAttribute("aria-pressed", (i === 0) === cb.checked ? "true" : "false"); seg.appendChild(b); });
    row.appendChild(el("span", "pfas-flag-l", "Reported"));
    row.appendChild(seg);
    pop.appendChild(row);
    var rlRow = el("label", "pfas-flag-row"), lab = el("span", "pfas-flag-l", "RL"), inp = detach(el("input"));
    if (unit) { lab.appendChild(doc.createTextNode(" ")); lab.appendChild(el("span", "pfas-sheet-unit", "(" + unit + ")")); }
    inp.type = "number";
    inp.setAttribute("step", "any");
    inp.setAttribute("min", "0");
    inp.value = rin ? rin.value : "";
    /* the RL in force when none is typed (the lowest calibrator): a grid
       input's placeholder, a left-out cell's hidden input's data-placeholder */
    inp.setAttribute("placeholder", rin ? rin.getAttribute("placeholder") || rin.getAttribute("data-placeholder") || "" : "");
    rlRow.appendChild(lab);
    rlRow.appendChild(inp);
    pop.appendChild(rlRow);
    if (rin) { pop.appendChild(el("p", "pfas-flag-note", "A blank RL takes the lowest calibrator.")); }
    makeNum(inp);
    function reported() { return yes.getAttribute("aria-pressed") === "true"; }
    function sync() {
      inp.disabled = !rin || !reported();
      rlRow.hidden = inp.disabled;
    }
    initSeg(seg);
    seg.addEventListener("click", sync);
    sync();
    openSheetPop(btn, pop, function (keep) {
      if (keep) {
        var on = reported();
        if (cb.checked !== on) { cb.checked = on; fire(cb); }
        if (rin && !inp.disabled && rin.value !== inp.value) { rin.value = inp.value; fire(rin); }
        syncFlag(td);
      }
      if (pop.contains(doc.activeElement)) { btn.focus(); }
    });
    (reported() ? yes : no).focus();
  }
  /* ── membership by the sheet's own forms, and a row's menu (\u22ef) ──────
     Add (above the grid) opens its chooser in a popover, which goes back to
     its blank choice when it closes (a chooser posting with the sheet's own
     form must not add on a later Save); Remove posts the ticked rows that are members (a row with data-member) through the
     form its button names, by a submit event the page's unsaved guard can
     hold back, each key once. A row's menu offers: Edit (the row's
     drawer); for a row with limits (its button's data-base, the pair every
     class copies), Copy that pair into every class pair (a pair with a None
     box) and Reset them to blank, the None marker cleared with them, each
     write fired so the footer counts it; and Remove, refused with the
     reason while the row's data-quantifies names natives. */
  function nativesWords(names) {
    return names.length < 2 ? names.join("") : names.slice(0, -1).join(", ") + " and " + names[names.length - 1];
  }
  function rowQuantifies(tr) {
    var v = readJSON(tr.getAttribute("data-quantifies"), []);
    return Object.prototype.toString.call(v) === "[object Array]" ? v : [];
  }
  /* the composites a standard is a member of (data-held-by): it stays while one averages it */
  function rowHeldBy(tr) {
    var v = readJSON(tr.getAttribute("data-held-by"), []);
    return Object.prototype.toString.call(v) === "[object Array]" ? v : [];
  }
  function memberRows(box) {
    return sheetSelection(box).map(function (k) { return sheetRowOf(box, k); })
      .filter(function (tr) { return tr && tr.hasAttribute("data-member"); })
      .map(function (tr) { return tr.getAttribute("data-row"); });
  }
  function submitByEvent(form) {
    if (form.requestSubmit) { form.requestSubmit(); return; }
    if (form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }))) { form.submit(); }
  }
  function postRemove(box, keys) {
    var rb = box.querySelector(".pfas-sheet-remove"), form = rb && doc.getElementById(rb.getAttribute("data-form"));
    if (!form || !keys.length) { return; }
    Array.prototype.forEach.call(form.querySelectorAll("input.pfas-sheet-posted"), function (i) { i.parentNode.removeChild(i); });
    keys.forEach(function (k) {
      var i = el("input", "pfas-sheet-posted");
      i.type = "hidden";
      i.name = rb.getAttribute("data-name");
      i.value = k;
      form.appendChild(i);
    });
    submitByEvent(form);
  }
  function syncRemove(box) {
    var rb = box.querySelector(".pfas-sheet-remove");
    if (rb) { rb.disabled = !memberRows(box).length; }
  }
  /* a row's class pairs: the columns whose pair carries a None box */
  function classCols(tr) {
    return byAttr(tr.querySelectorAll("td[data-none]"), "data-pair-end", "lo").map(function (td) { return td.getAttribute("data-col"); });
  }
  function setPair(tr, col, lo, hi) {
    var ins = sheetInputs(tr, col), nums = ins.filter(function (i) { return i.type !== "checkbox"; });
    ins.forEach(function (i) { if (i.type === "checkbox" && i.checked) { i.checked = false; fire(i); } });
    [lo, hi].forEach(function (v, k) { if (nums[k] && nums[k].value !== v) { nums[k].value = v; fire(nums[k]); } });
  }
  /* a grid row's actions as menu entries: what its \u22ef button and a right
     click on the row offer ({id, label, act, disabled, reason}); a page that
     draws the row elsewhere (a list's node) runs an entry by its id */
  function rowMenuItems(btn) {
    var box = sheetBox(btn), tr = btn && btn.closest("tr"), items = [];
    if (!box || !tr) { return items; }
    var key = tr.getAttribute("data-row"), base = btn.getAttribute("data-base");
    /* a row that has a card of its own opens it (the page hears
       pfas:row-card); what it quantifies, a plain count in its cell, is
       listed in a window */
    if (tr.getAttribute("data-card")) {
      items.push({ id: "card", label: "Show its card", act: function () {
        tr.dispatchEvent(new CustomEvent("pfas:row-card", { bubbles: true, detail: { row: tr, key: tr.getAttribute("data-card") } }));
      } });
    }
    var quant = readJSON(tr.getAttribute("data-quant-list"), []);
    if (quant.length) {
      var natives = rowQuantifies(tr).length, one = quant.length === 1;
      var noun = natives === quant.length ? (one ? "analyte" : "analytes") : (!natives ? (one ? "standard" : "standards") : "");
      items.push({ id: "quantifies", label: noun ? "Show the " + quant.length + " " + noun + " it quantifies" : "Show what it quantifies",
                   act: function () { showQuantifies(tr, quant); } });
    }
    /* a role drawn as a word (td.pfas-sheet-role) is set in the row's drawer,
       opened on the role's segment */
    var role = tr.querySelector("td.pfas-sheet-role[data-col]");
    if (role) { items.push({ id: "role", label: "Set role", act: function () { openSheetRow(box, key, role.getAttribute("data-col")); } }); }
    items.push({ id: "edit", label: base ? "Edit link and limits" : "Edit link", act: function () { openSheetRow(box, key); } });
    if (base) {
      items.push({ id: "copy", label: "Copy Aqueous to every class", act: function () {
        var aq = sheetInputs(tr, base).filter(function (i) { return i.type !== "checkbox"; }).map(function (i) { return i.value; });
        classCols(tr).forEach(function (col) { setPair(tr, col, aq[0] || "", aq[1] || ""); });
      } });
      items.push({ id: "reset", label: "Reset classes to Aqueous", act: function () { classCols(tr).forEach(function (col) { setPair(tr, col, "", ""); }); } });
    }
    if (box.querySelector(".pfas-sheet-remove")) {
      var natives = rowQuantifies(tr), held = rowHeldBy(tr);
      items.push({ id: "remove", label: "Remove from method", act: function () { postRemove(box, [key]); },
                   disabled: natives.length > 0 || held.length > 0,
                   reason: natives.length ? "Refused: it quantifies " + nativesWords(natives) + ". Change their Quantified by first."
                     : held.length ? "Refused: it is a member of " + nativesWords(held) + ". Edit or remove that composite first." : "" });
    }
    return items;
  }
  /* what a row quantifies, in a window that reads it */
  function showQuantifies(tr, names) {
    var body = el("ul", "pfas-tile-read pfas-quant-list");
    names.forEach(function (n) { body.appendChild(el("li", "", String(n))); });
    drawer.open((tr.getAttribute("data-label") || "") + ": quantifies", body, { cls: "is-dialog", opener: tr.querySelector(".pfas-rowmenu") || null });
  }
  /* the entries of the row `key`'s menu, or none for a row with no menu */
  function sheetRowItems(root, key) {
    var box = sheetBox(root), tr = box && sheetRowOf(box, key), btn = tr && tr.querySelector(".pfas-rowmenu");
    return btn ? rowMenuItems(btn) : [];
  }
  function openRowMenu(btn) {
    var box = sheetBox(btn), tr = btn && btn.closest("tr");
    if (!box || !tr) { return; }
    var pop = box.__pfasMenuPop;
    if (pop && sheetPop && sheetPop.pop === pop && pop.__pfasBtn === btn) { closeSheetPop(); return; }
    closeSheetPop();
    if (!pop) {
      pop = box.__pfasMenuPop = el("div", "pfas-sheet-pop is-menu");
      pop.setAttribute("role", "menu");
      pop.hidden = true;
      box.appendChild(pop);
    }
    pop.__pfasBtn = btn;
    pop.textContent = "";
    pop.setAttribute("aria-label", btn.getAttribute("aria-label") || "");
    rowMenuItems(btn).forEach(function (it) {
      var b = el("button", "pfas-menu-item", it.label);
      b.type = "button";
      b.setAttribute("role", "menuitem");
      b.addEventListener("click", function () { if (!b.disabled) { closeSheetPop(); it.act(); } });
      pop.appendChild(b);
      if (it.disabled) {
        b.disabled = true;
        pop.appendChild(el("p", "pfas-refused", it.reason));
      }
    });
    openSheetPop(btn, pop);
  }
  /* the Columns chips follow the picker: a column the grid starts without
     has its chip while it is shown, and the last chip counts what is hidden
     ("+ 2 hidden"), or names the picker when nothing is */
  function syncColChips(box) {
    var row = box.querySelector(".pfas-colchips"), picker = box.querySelector(".pfas-sheet-picker");
    if (!row || !picker) { return; }
    var boxes = Array.prototype.slice.call(picker.querySelectorAll("input[data-col]"));
    Array.prototype.forEach.call(row.querySelectorAll(".pfas-colchip[data-col]"), function (chip) {
      var cb = byAttr(boxes, "data-col", chip.getAttribute("data-col"))[0];
      chip.hidden = !(cb && cb.checked);
    });
    var n = boxes.filter(function (b) { return !b.checked; }).length, more = row.querySelector(".pfas-sheet-picker-btn");
    if (more) { more.textContent = n ? "+ " + n + " hidden" : "Columns"; }
  }
  /* Columns: a hidden column's cells are not drawn, and a group heading spans what is shown */
  function showColumn(box, col, on) {
    byAttr(box.querySelectorAll(".pfas-sheet [data-col]"), "data-col", col).forEach(function (n) { n.classList.toggle("is-col-off", !on); });
    Array.prototype.forEach.call(box.querySelectorAll("th.pfas-sheet-gh"), function (gh) {
      var shown = 0, total = 0;
      byAttr(box.querySelectorAll("thead th[data-col]"), "data-group", gh.getAttribute("data-group")).forEach(function (th) {
        var w = Number(th.getAttribute("colspan") || 1);
        total += w;
        if (!th.classList.contains("is-col-off")) { shown += w; }
      });
      gh.setAttribute("colspan", String(shown || total));
      gh.classList.toggle("is-col-off", !shown);
    });
    spanColumns(box);
  }
  /* A pair over several columns (td[data-span] names them, its upper end's
     td beside it): as wide as those of them shown, gone with the last. */
  function spanColumns(box) {
    var heads = box.querySelectorAll("thead th[data-col]");
    Array.prototype.forEach.call(box.querySelectorAll(".pfas-sheet td[data-span]"), function (lo) {
      var hi = pairPartner(lo, "lo"), width = 0;
      (lo.getAttribute("data-span") || "").split(" ").forEach(function (k) {
        var th = byAttr(heads, "data-col", k)[0];
        if (th && !th.classList.contains("is-col-off")) { width += Number(th.getAttribute("colspan") || 1) || 1; }
      });
      lo.classList.toggle("is-col-off", !width);
      if (hi) {
        hi.classList.toggle("is-col-off", width < 2);
        hi.setAttribute("colspan", String(Math.max(1, width - 1)));
      }
    });
  }
  /* the table's segment shows its hidden input's value; a state drawn as a
     word (td.pfas-sheet-role) shows the word its data-words give the value */
  function syncSheetSeg(hidden) {
    var td = hidden.parentNode;
    if (td && td.classList && td.classList.contains("pfas-sheet-role")) {
      var words = [], val = td.querySelector(".pfas-sheet-val");
      try { words = JSON.parse(td.getAttribute("data-words") || "[]"); } catch (e) { words = []; }
      var hit = words.filter(function (w) { return w[0] === hidden.value; })[0];
      if (val) { val.textContent = hit ? hit[1] : hidden.value; }
      return;
    }
    var seg = td && td.querySelector(".pfas-seg");
    var item = seg && byAttr(seg.querySelectorAll(".pfas-seg-item"), "data-value", hidden.value)[0];
    if (item) { activate(seg, item); }
  }
  function sheetForm(box, key, group) {
    var tpl = byAttr(box.querySelectorAll("template.pfas-sheet-row-tpl"), group ? "data-group" : "data-row", key)[0];
    var src = tpl && tpl.content && tpl.content.firstElementChild;
    if (!src) { return null; }
    var form = src.cloneNode(true);
    Array.prototype.forEach.call(form.querySelectorAll(".pfas-seg"), function (seg) {
      var hidden = seg.parentNode.querySelector("input[type=hidden]");
      hidden.id = "pfas-sheet-d-" + (++idSeq);
      seg.setAttribute("data-input", hidden.id);
    });
    return form;
  }
  function enhanceSheetForm(form) {
    /* a drawer's flag (a copy, no RL: that is its own field) flips its box */
    Array.prototype.forEach.call(form.querySelectorAll(".pfas-flag"), function (b) {
      var field = b.closest(".pfas-sheet-field"), cb = field && flagBox(field);
      if (!cb) { return; }
      if (!field.classList.contains("is-leave")) { drawFlag(b, cb.checked, ""); }
      b.addEventListener("click", function () { cb.checked = !cb.checked; fire(cb, ["change"]); drawFlag(b, cb.checked, ""); });
    });
    Array.prototype.forEach.call(form.querySelectorAll(".pfas-seg"), initSeg);
    Array.prototype.forEach.call(form.querySelectorAll("[data-range]"), initRange);
    /* a pair's None box, as in the cell editor: ticked, the window gives way
       (its ends blank, so Done writes them blank) */
    Array.prototype.forEach.call(form.querySelectorAll(".pfas-cell-none input[type=checkbox]"), function (nb) {
      var field = nb.closest(".pfas-sheet-field");
      var ends = field ? field.querySelectorAll("input[type=number]") : [];     /* a pair's two ends, or a number's one */
      function sync() {
        Array.prototype.forEach.call(ends, function (i) {
          if (nb.checked && i.value !== "") { i.value = ""; fire(i, ["input"]); }
          i.disabled = nb.checked;
        });
      }
      nb.addEventListener("change", sync);
      sync();
    });
    Array.prototype.forEach.call(form.querySelectorAll("input[type=number]"), function (inp) {
      if (!inp.closest("[data-range]")) { makeNum(inp); }
    });
    initAllChips(form);
  }
  /* several rows: no one row's values, and every field left as is until it is
     changed; only the inputs a person touched are written (a pair's other end
     keeps each row's own value) */
  function leaveAsIs(field) {
    Array.prototype.forEach.call(field.querySelectorAll(".pfas-sheet-help"), function (h) { h.parentNode.removeChild(h); });
    Array.prototype.forEach.call(field.querySelectorAll(".pfas-sheet-in"), function (i) {
      if (i.type === "checkbox") { i.checked = false; } else { i.value = ""; }
      i.removeAttribute("placeholder");
    });
    Array.prototype.forEach.call(field.querySelectorAll("option"), function (o) { if (o.value === "") { o.textContent = "\u2014"; } });
    Array.prototype.forEach.call(field.querySelectorAll(".pfas-seg-item"), function (b) {
      b.setAttribute("aria-pressed", "false");
      b.classList.remove("is-inherited");
    });
    Array.prototype.forEach.call(field.querySelectorAll(".pfas-flag"), function (b) {
      b.textContent = "\u2014";
      b.setAttribute("aria-pressed", "false");
    });
    var lab = el("label", "pfas-switch pfas-sheet-leave"), box = detach(el("input"));
    box.type = "checkbox";
    box.checked = true;
    lab.appendChild(box); lab.appendChild(el("span", "pfas-switch-track")); lab.appendChild(el("span", "", "Leave as is"));
    var head = field.querySelector(".pfas-sheet-flabel");
    field.insertBefore(lab, head ? head.nextSibling : field.firstChild);
    field.classList.add("is-leave");
    /* turning Leave as is off by hand applies the field as shown: a switch, a
       state, a choice, and any typed value; a blank number or text end is not
       written (it would clear that end in every row) */
    box.addEventListener("change", function () {
      field.classList.toggle("is-leave", box.checked);
      Array.prototype.forEach.call(field.querySelectorAll(".pfas-sheet-in"), function (i) {
        var always = i.type === "checkbox" || i.type === "hidden" || i.tagName === "SELECT";
        i.__pfasTouched = !box.checked && (always || i.value !== "");
      });
    });
    function changed(e) {
      if (lab.contains(e.target) || e.target === field || (head && head.contains(e.target))) { return; }
      if (e.type !== "click" && e.target.classList.contains("pfas-sheet-in")) { e.target.__pfasTouched = true; }
      box.checked = false;
      field.classList.remove("is-leave");
    }
    ["input", "change", "click"].forEach(function (t) { field.addEventListener(t, changed); });
  }
  /* write a drawer field into the row's own inputs (only the touched ones when
     `touched`); true when something changed */
  function writeSheetField(field, tr, touched) {
    var from = field.querySelectorAll(".pfas-sheet-in"), to = sheetInputs(tr, field.getAttribute("data-col")), changed = false;
    for (var i = 0; i < from.length && i < to.length; i++) {
      var a = from[i], b = to[i];
      if (touched && !a.__pfasTouched) { continue; }
      if (b.type === "checkbox") {
        if (b.checked !== a.checked) { b.checked = a.checked; fire(b); changed = true; }
      } else if (b.value !== a.value) {
        b.value = a.value;
        fire(b);
        if (b.type === "hidden") { syncSheetSeg(b); }
        changed = true;
      }
    }
    return changed;
  }
  function openSheetDrawer(title, form, done, focus) {
    enhanceSheetForm(form);
    var foot = el("div", "pfas-drawer-actions"), btn = el("button", "btn btn-primary", "Done");
    btn.type = "button";
    btn.addEventListener("click", function () { done(); drawer.close(); });
    foot.appendChild(btn);
    drawer.open(title, form, { footer: foot, cls: "is-dialog", focus: focus ? focus() : null });
  }
  /* one row: the drawer starts from the row's inputs as they stand, edits
     made in the grid and not yet saved included (the <template> holds the
     stored values) */
  function seedSheetField(field, tr) {
    var to = field.querySelectorAll(".pfas-sheet-in"), from = sheetInputs(tr, field.getAttribute("data-col"));
    for (var i = 0; i < to.length && i < from.length; i++) {
      if (to[i].type === "checkbox") {
        to[i].checked = from[i].checked;
      } else {
        to[i].value = from[i].value;
        if (to[i].type === "hidden") { syncSheetSeg(to[i]); }
      }
    }
  }
  /* an input a person changed in the drawer: the only ones Done writes */
  function trackTouched(form) {
    ["input", "change"].forEach(function (t) {
      form.addEventListener(t, function (e) {
        if (e.target.classList && e.target.classList.contains("pfas-sheet-in")) { e.target.__pfasTouched = true; }
      });
    });
  }
  /* one row's drawer; `col` names the field it opens on (its pressed
     segment item, else its first control) */
  function openSheetRow(root, key, col, group) {
    var box = sheetBox(root);
    var tr = box && (group ? byAttr(box.querySelectorAll("tr.pfas-sheet-grouprow"), "data-group", key)[0] : sheetRowOf(box, key));
    var form = tr && sheetForm(box, key, group);
    if (!form) { return; }
    var editable = Array.prototype.filter.call(form.querySelectorAll(".pfas-sheet-field"), function (f) {
      return !f.classList.contains("is-ro");
    });
    editable.forEach(function (f) { seedSheetField(f, tr); });
    trackTouched(form);
    openSheetDrawer(tr.getAttribute("data-label") || (group && groupTplLabel(box, key)) || key, form, function () {
      editable.forEach(function (f) { writeSheetField(f, tr, true); });
    }, col ? function () {
      var f = byAttr(form.querySelectorAll(".pfas-sheet-field"), "data-col", col)[0];
      return f && (f.querySelector('.pfas-seg-item[aria-pressed="true"]') ||
                   f.querySelector("button, select, input:not([type=hidden])")) || null;
    } : null);
  }
  /* a group row's own values (a heading row holding what every row shares):
     its drawer, as a row's */
  function groupTplLabel(box, key) {
    var tpl = byAttr(box.querySelectorAll("template.pfas-sheet-row-tpl"), "data-group", key)[0];
    return tpl ? tpl.getAttribute("data-label") : "";
  }
  function openSheetGroup(root, key, col) { openSheetRow(root, key, col, true); }
  /* Edit selected on the ticked rows, or on `rows` */
  function openSheetSelected(root, rows) {
    var box = sheetBox(root), keys = rows || sheetSelection(box);
    if (box && box.getAttribute("data-layout") === "matrix") { openMatrixSelected(box, keys); return; }
    if (keys.length < 2) { if (keys.length) { openSheetRow(box, keys[0]); } return; }
    var form = sheetForm(box, keys[0]);
    if (!form) { return; }
    Array.prototype.forEach.call(form.querySelectorAll(".pfas-sheet-field"), function (f) {
      if (f.classList.contains("is-ro")) { f.parentNode.removeChild(f); } else { leaveAsIs(f); }
    });
    openSheetDrawer("Edit " + keys.length + " rows", form, function () {
      var cols = [], table = box.querySelector(".pfas-sheet");
      Array.prototype.forEach.call(form.querySelectorAll(".pfas-sheet-field"), function (f) {
        var touched = Array.prototype.some.call(f.querySelectorAll(".pfas-sheet-in"), function (i) { return i.__pfasTouched; });
        if (f.classList.contains("is-leave") || !touched) { return; }
        keys.forEach(function (k) { var tr = sheetRowOf(box, k); if (tr) { writeSheetField(f, tr, true); } });
        cols.push(f.getAttribute("data-col"));
      });
      table.dispatchEvent(new CustomEvent("pfas:sheet-bulk", { bubbles: true, detail: { sheet: table.getAttribute("data-sheet"), rows: keys, cols: cols } }));
    });
  }
  /* ── the matrix layout (data-layout="matrix": the Analytes tab) ──────────
     Edit selected is one table, a row per matrix (In panel, RL, MDL), then
     the row's own fields: the sheet's bulk <template>, which names no input.
     Every field starts As is; a value sets every ticked row; \u2715 sets none;
     the hint under a field says what the ticked rows hold now (their inputs
     as they stand, unsaved edits included). Done writes into the grid only
     what was set.
     The bar's one-column actions (data-action) apply at once to the ticked
     rows and leave a toast whose Undo puts back exactly the values the action
     changed, each with its events, so the cells and the footer follow. The
     toast, and its Undo, go at the next action, any change made in the grid,
     or a submit. */
  var AS_IS = "pfas-as-is", HINT_MAX = 6;
  function bulkTemplate(box) {
    var tpl = box.querySelector("template.pfas-sheet-bulk-tpl");
    return tpl && tpl.content ? tpl.content.firstElementChild : null;
  }
  /* the matrices in order: {col: its flag column, label, unit} */
  function sheetMatrices(box) {
    var tpl = bulkTemplate(box);
    return tpl ? Array.prototype.map.call(tpl.querySelectorAll("tr[data-col]"), function (tr) {
      return { col: tr.getAttribute("data-col"), label: tr.getAttribute("data-label") || "", unit: tr.getAttribute("data-unit") || "" };
    }) : [];
  }
  /* a matrix row's typed fields (RL, MDL); with `inheriting`, only those whose blank inherits */
  function matrixFields(box, inheriting) {
    var tpl = bulkTemplate(box), tr = tpl && tpl.querySelector("tr[data-col]");
    return tr ? Array.prototype.filter.call(tr.querySelectorAll("td[data-field]"), function (td) {
      return td.getAttribute("data-field") !== "in" && (!inheriting || td.hasAttribute("data-inherits"));
    }).map(function (td) { return td.getAttribute("data-field"); }) : [];
  }
  /* a row's control for a matrix field: "in", its flag's box; another, the input the flag names */
  function matrixInput(tr, col, field) {
    var td = byAttr(tr.querySelectorAll("td[data-col]"), "data-col", col)[0], btn = td && td.querySelector(".pfas-flag");
    if (!btn) { return null; }
    return field === "in" ? flagBox(td) : flagNamed(btn, field);
  }
  function tickedRows(box) {
    return sheetSelection(box).map(function (k) { return sheetRowOf(box, k); }).filter(Boolean);
  }
  function readCtl(c) { return c.type === "checkbox" ? c.checked : c.value; }
  /* a grid control set to a value, with its events, logging what it held;
     a choice the control does not offer is not written */
  function writeCtl(c, v, log) {
    if (!c || c.disabled || readCtl(c) === v) { return; }
    if (c.tagName === "SELECT" && !byAttr(c.querySelectorAll("option"), "value", v).length) { return; }
    log.push([c, readCtl(c)]);
    if (c.type === "checkbox") { c.checked = v; } else { c.value = v; }
    fire(c);
  }
  /* a value as a hint says it: a flag \u2713 / \u2717, a choice its label, a blank none */
  function hintWord(c) {
    if (!c) { return "none"; }
    if (c.type === "checkbox") { return c.checked ? "\u2713" : "\u2717"; }
    if (c.value === "") { return "none"; }
    var o = c.tagName === "SELECT" ? byAttr(c.querySelectorAll("option"), "value", c.value)[0] : null;
    return o ? squash(o.textContent) : c.value;
  }
  /* "all 3 \u2713", "mixed: 1 \u2713, 2 \u2717", "all 3: none", "mixed: 2.0, 2.0, none" */
  function hintText(words, flag) {
    var n = words.length;
    if (!n) { return ""; }
    if (words.every(function (w) { return w === words[0]; })) {
      return n === 1 ? words[0] : "all " + n + (flag ? " " : ": ") + words[0];
    }
    if (flag) {
      var on = words.filter(function (w) { return w === "\u2713"; }).length;
      return "mixed: " + on + " \u2713, " + (n - on) + " \u2717";
    }
    return "mixed: " + words.slice(0, HINT_MAX).join(", ") + (n > HINT_MAX ? ", \u2026" : "");
  }
  /* what a bulk field sets: null for As is, a box's tick, or a value ("" is none) */
  function bulkValue(f) {
    var seg = f.querySelector(".pfas-seg"), c = f.querySelector(".pfas-bulk-in");
    if (seg) {
      var on = seg.querySelector('.pfas-seg-item[aria-pressed="true"]'), v = on ? on.getAttribute("data-value") : "";
      return v ? v === "on" : null;
    }
    if (!c) { return null; }
    if (c.tagName === "SELECT") { return c.value === AS_IS ? null : c.value; }
    if (f.classList.contains("is-none")) { return ""; }
    return c.value === "" ? null : c.value;
  }
  /* the grid control a bulk field writes in a row: a matrix's, or the row's own column */
  function bulkTarget(f, tr) {
    var mtr = f.closest("tr[data-col]");
    if (mtr) { return matrixInput(tr, mtr.getAttribute("data-col"), f.getAttribute("data-field")); }
    return sheetInputs(tr, f.getAttribute("data-col"))[0] || null;
  }
  /* a matrix's RL or MDL for a row left out of it: none in force, never shown
     (its cell reads \u2717) nor written */
  function leftOut(f, tr) {
    var mtr = f.closest("tr[data-col]"), box = mtr && f.getAttribute("data-field") !== "in" ?
      matrixInput(tr, mtr.getAttribute("data-col"), "in") : null;
    return !!box && !box.checked;
  }
  /* \u2715: the field sets none (the box gives way to the word), and \u21ba leaves it as is again */
  function toggleNone(f, x) {
    var none = !f.classList.contains("is-none"), c = f.querySelector(".pfas-bulk-in");
    var label = c.getAttribute("aria-label"), word = f.querySelector(".pfas-bulk-none");
    f.classList.toggle("is-none", none);
    c.value = "";
    c.hidden = none;
    if (!word) { word = el("span", "pfas-bulk-none", "none"); f.insertBefore(word, x); }
    word.hidden = !none;
    if (none) { x.textContent = "\u21ba"; } else { x.innerHTML = icon("close", { hidden: true }) || "\u2715"; }
    x.setAttribute("aria-label", none ? "Leave " + label + " as is" : "Set " + label + " to none");
  }
  function bulkSync(form, count) {
    var n = 0;
    Array.prototype.forEach.call(form.querySelectorAll(".pfas-bulk-f"), function (f) {
      var set = bulkValue(f) !== null;
      f.classList.toggle("is-changed", set);
      if (set) { n++; }
    });
    Array.prototype.forEach.call(form.querySelectorAll("tr[data-col]"), function (tr) {
      tr.classList.toggle("is-changed", !!tr.querySelector(".pfas-bulk-f.is-changed"));
    });
    count.textContent = n ? n + (n === 1 ? " change" : " changes") : "No changes";
  }
  function openMatrixSelected(box, keys) {
    var tpl = bulkTemplate(box), table = box.querySelector(".pfas-sheet");
    var rows = keys.map(function (k) { return sheetRowOf(box, k); }).filter(Boolean);
    if (!tpl || !rows.length) { return; }
    var form = tpl.cloneNode(true), fields = Array.prototype.slice.call(form.querySelectorAll(".pfas-bulk-f"));
    fields.forEach(function (f) {
      var words = rows.map(function (tr) { return leftOut(f, tr) ? "\u2717" : hintWord(bulkTarget(f, tr)); });
      f.querySelector(".pfas-hint").textContent = hintText(words, !!f.querySelector(".pfas-seg"));
    });
    Array.prototype.forEach.call(form.querySelectorAll(".pfas-seg"), initSeg);
    var foot = el("div", "pfas-drawer-actions pfas-bulk-foot"), count = el("span", "pfas-bulk-count");
    var done = el("button", "btn btn-primary", "Done");
    done.type = "button";
    foot.appendChild(el("span", "pfas-bulk-key", "Blank leaves a value as is. \u2715 sets it to none."));
    foot.appendChild(count);
    foot.appendChild(done);
    function sync() { bulkSync(form, count); }
    form.addEventListener("click", function (e) {
      var x = e.target.closest(".pfas-bulk-x");
      if (x && form.contains(x)) { toggleNone(x.closest(".pfas-bulk-f"), x); }
      sync();
    });
    ["input", "change"].forEach(function (t) { form.addEventListener(t, sync); });
    sync();
    done.addEventListener("click", function () {
      var log = [], cols = [];
      rows.forEach(function (tr) {
        fields.forEach(function (f) {
          /* a matrix's flag comes before its RL and MDL: a row left out once it is written takes neither */
          var v = bulkValue(f), c = v === null || leftOut(f, tr) ? null : bulkTarget(f, tr), was = log.length;
          writeCtl(c, v, log);
          var td = log.length > was ? c.closest("td[data-col]") : null;
          if (td && cols.indexOf(td.getAttribute("data-col")) < 0) { cols.push(td.getAttribute("data-col")); }
        });
      });
      drawer.close();
      table.dispatchEvent(new CustomEvent("pfas:sheet-bulk", { bubbles: true, detail: { sheet: table.getAttribute("data-sheet"), rows: keys, cols: cols } }));
    });
    var names = rows.map(function (tr) { return tr.getAttribute("data-label") || tr.getAttribute("data-row"); });
    drawer.open(rows.length === 1 ? names[0] : "Edit " + rows.length + " rows", form,
                { footer: foot, cls: "is-dialog", head: rows.length > 1 ? el("span", "pfas-bulk-who", names.join(", ")) : null });
    placeAll(form);                 /* the segments were measured before the drawer showed them */
  }
  /* ── the one-column actions and their toast ── */
  function analytesWord(n) { return n + (n === 1 ? " analyte" : " analytes"); }
  /* the toast rises in; it fades out when it ends, at once when another takes its place */
  function clearToast(box, now) {
    var t = box.__pfasToast;
    box.__pfasToast = null;
    if (!t || !t.parentNode) { return; }
    if (now) { t.parentNode.removeChild(t); return; }
    leave(t, "is-leaving", function () { if (t.parentNode) { t.parentNode.removeChild(t); } });
  }
  function undoAction(box, log) {
    log.slice().reverse().forEach(function (p) { writeCtl(p[0], p[1], []); });
    clearToast(box);
  }
  function showToast(box, text, log) {
    clearToast(box, true);
    var t = el("div", "pfas-toast"), undo = el("button", "btn btn-sm pfas-toast-undo", "Undo");
    t.setAttribute("role", "status");
    t.appendChild(el("span", "", text));
    undo.type = "button";
    undo.addEventListener("click", function () { undoAction(box, log); });
    t.appendChild(undo);
    var wrap = box.querySelector(".pfas-sheet-wrap");
    box.insertBefore(t, wrap ? wrap.nextSibling : null);
    box.__pfasToast = t;
    arrive(t, "is-arriving");
  }
  /* write into every ticked row, then draw the toast, words(n) and its Undo,
     n the rows the action changed (a row that does not offer the value, or
     whose control is locked, keeps its own; an action that changes nothing
     draws no toast): drawn after the action's own changes, only a later one
     ends it */
  function applyAction(box, write, words) {
    var rows = tickedRows(box), log = [], n = 0;
    closeSheetPop();
    clearToast(box, true);   /* the next action's toast takes its place at once */
    rows.forEach(function (tr) {
      var was = log.length;
      write(tr, log);
      if (log.length > was) { n++; }
    });
    if (n) { showToast(box, words(n), log); }
  }
  function popOption(value, words) { var o = el("option", "", words); o.setAttribute("value", value); return o; }
  function popSelect(pairs) {
    var s = el("select");
    detach(s);                      /* a popover's choice is no field of the form around it */
    pairs.forEach(function (p) { s.appendChild(popOption(p[0], p[1])); });
    return s;
  }
  /* a word and its control; a choice is named by its label, a segment by its own aria-label */
  function popRow(pop, words, ctl) {
    var r = el(ctl.tagName === "SELECT" ? "label" : "div", "pfas-pop-row");
    r.appendChild(el("span", "pfas-pop-l", words));
    r.appendChild(ctl);
    pop.appendChild(r);
    return ctl;
  }
  function colLabel(box, col) {
    var th = byAttr(box.querySelectorAll("thead th[data-col]"), "data-col", col)[0];
    if (!th) { return col; }
    var c = th.cloneNode(true);
    Array.prototype.forEach.call(c.querySelectorAll(".pfas-sheet-unit, .pfas-th-unit, .pfas-sheet-sub"), function (n) { n.parentNode.removeChild(n); });
    return squash(c.textContent);
  }
  function resetInherited(box) {
    var ms = sheetMatrices(box), fields = matrixFields(box, true);
    applyAction(box, function (tr, log) {
      ms.forEach(function (m) {
        var inPanel = matrixInput(tr, m.col, "in");
        if (!inPanel || !inPanel.checked) { return; }      /* left out: its RL is not read */
        fields.forEach(function (f) { writeCtl(matrixInput(tr, m.col, f), "", log); });
      });
    }, function (n) { return analytesWord(n) + " reset to inherited"; });
  }
  function columnAction(box, btn) {
    var action = btn.getAttribute("data-action"), rows = tickedRows(box);
    if (!rows.length) { return; }
    if (action === "reset-inherited") { closeSheetPop(); resetInherited(box); return; }
    var pop = box.__pfasActPop;
    if (pop && sheetPop && sheetPop.pop === pop && sheetPop.btn === btn) { closeSheetPop(); return; }
    if (!pop) {
      pop = box.__pfasActPop = el("div", "pfas-sheet-pop is-action");
      pop.setAttribute("role", "dialog");
      pop.hidden = true;
      box.appendChild(pop);
    }
    pop.textContent = "";
    var title = squash(btn.textContent).replace(/\u2026$/, "");
    pop.setAttribute("aria-label", title);
    pop.appendChild(el("div", "pfas-pop-h", title));
    var ms = sheetMatrices(box), go = el("button", "btn btn-sm btn-primary", action === "copy-column" ? "Copy" : "Set"), apply;
    go.type = "button";
    function matrix(col) { return ms.filter(function (m) { return m.col === col; })[0]; }
    if (action === "set-quant") {
      var col = btn.getAttribute("data-col"), src = sheetInputs(rows[0], col)[0];
      var sel = popRow(pop, colLabel(box, col), popSelect(src ? Array.prototype.map.call(src.querySelectorAll("option"), function (o) {
        return [o.value, squash(o.textContent)];
      }) : []));
      if (src) { sel.value = src.value; }
      apply = function () {
        var v = sel.value, words = v === "" ? "none" : hintWord(sel);
        applyAction(box, function (tr, log) { writeCtl(sheetInputs(tr, col)[0], v, log); },
                    function (n) { return colLabel(box, col) + " set to " + words + " for " + analytesWord(n); });
      };
    } else if (action === "set-panel") {
      var which = popRow(pop, "Matrix", popSelect(ms.map(function (m) { return [m.col, m.label]; })));
      var seg = el("div", "pfas-seg pfas-seg-sm is-fit"), yes = el("button", "pfas-seg-item", "\u2713"), no = el("button", "pfas-seg-item", "\u2717");
      seg.setAttribute("role", "group");
      seg.setAttribute("aria-label", "Reported");
      seg.setAttribute("data-quiet", "");
      [yes, no].forEach(function (b, i) { b.type = "button"; b.setAttribute("aria-pressed", i ? "false" : "true"); seg.appendChild(b); });
      popRow(pop, "Reported", seg);
      initSeg(seg);
      apply = function () {
        var m = matrix(which.value), on = yes.getAttribute("aria-pressed") === "true";
        applyAction(box, function (tr, log) { writeCtl(matrixInput(tr, m.col, "in"), on, log); },
                    function (n) { return m.label + " set to " + (on ? "\u2713" : "\u2717") + " for " + analytesWord(n); });
      };
    } else if (action === "copy-column") {
      /* a column takes another in its own unit: an RL is a number in the matrix's unit */
      var into = popRow(pop, "Column", popSelect(ms.map(function (m) { return [m.col, m.label]; })));
      var from = popRow(pop, "From", popSelect([]));
      var sources = function () {
        var to = matrix(into.value);
        from.textContent = "";
        ms.forEach(function (m) { if (to && m.col !== to.col && m.unit === to.unit) { from.appendChild(popOption(m.col, m.label)); } });
        go.disabled = !from.querySelector("option");
      };
      into.addEventListener("change", sources);
      sources();
      apply = function () {
        var to = matrix(into.value), src = matrix(from.value), fields = matrixFields(box, false);
        if (!to || !src) { return; }
        applyAction(box, function (tr, log) {
          var a = matrixInput(tr, src.col, "in"), on = !!a && a.checked;
          writeCtl(matrixInput(tr, to.col, "in"), on, log);
          if (!on) { return; }          /* a matrix left out has no RL in force to copy */
          fields.forEach(function (f) {
            var s = matrixInput(tr, src.col, f);
            if (s) { writeCtl(matrixInput(tr, to.col, f), s.value, log); }
          });
        }, function (n) { return to.label + " copied from " + src.label + " for " + analytesWord(n); });
      };
    } else {
      return;
    }
    go.addEventListener("click", function () { apply(); });
    var foot = el("div", "pfas-pop-row");
    foot.appendChild(go);
    pop.appendChild(foot);
    openSheetPop(btn, pop);
    placeAll(pop);                  /* its segment was measured while the popover was hidden */
    pop.querySelector("select, button").focus();
  }
  /* a row's expand button opens and closes the region it controls (a rule's
     limits); every button controlling one region shows whether it is open.
     A region that is itself a section (details.pfas-sec) is only opened (its
     own summary closes it, so an Edit never hides what it was pressed to
     show); a region inside a closed section opens that section with it. */
  function expandTarget(btn) { return doc.getElementById(btn.getAttribute("aria-controls") || ""); }
  function isSection(r) { return r.localName === "details"; }
  function regionOpen(r) { return isSection(r) ? r.open : !r.hidden; }
  function syncExpand(btn) {
    var r = expandTarget(btn);
    btn.setAttribute("aria-expanded", r && regionOpen(r) ? "true" : "false");
  }
  /* what opens a region: an expand button, or a row that is the button */
  var EXPANDS = ".pfas-sheet-expand, tr[data-row-region]";
  function syncRegion(r) {
    byAttr(doc.querySelectorAll(EXPANDS), "aria-controls", r.id).forEach(syncExpand);
  }
  function toggleRegion(btn) {
    var r = expandTarget(btn);
    if (!r) { return; }
    if (isSection(r)) { r.open = true; } else { r.hidden = !r.hidden; }
    var sec = r.parentNode && r.parentNode.closest ? r.parentNode.closest("details.pfas-sec") : null;
    if (sec && regionOpen(r)) { sec.open = true; }
    syncRegion(r);
    if (regionOpen(r)) { placeAll(r); r.scrollIntoView({ block: "nearest" }); }
  }
  /* ── a box of equal neighbours (td[data-box]: profile_grids.merge_boxes) ──
     The cells inside one box keep their own drawers; a pointer or focus on
     any of them lights the whole box, and the box's words (its first cell's)
     are centred across it at its first row's height: --box-w on that cell,
     measured again whenever the table's size changes (a fold opened, a
     resize). */
  function boxCells(table, id) { return byAttr(table.querySelectorAll("td[data-box]"), "data-box", id); }
  /* a box's first cell hidden (the column picker): the first cell shown in
     its row leads, its words with it */
  function boxLead(table, lead) {
    if (lead.getBoundingClientRect().width) { return lead; }
    var tr = lead.parentNode, next = boxCells(table, lead.getAttribute("data-box")).filter(function (td) {
      return td.parentNode === tr && td.getBoundingClientRect().width;
    })[0];
    if (!next) { return lead; }
    lead.removeAttribute("data-box-lead");
    next.setAttribute("data-box-lead", "1");
    Array.prototype.slice.call(lead.children).forEach(function (w) {
      if (w.classList.contains("pfas-box-words")) { next.appendChild(w); }
    });
    return next;
  }
  /* a box whose cells are controls (data-box-live) stands for equal values
     only until one changes: the change undoes it, each cell showing its own */
  function unbox(table, id) {
    boxCells(table, id).forEach(function (td) {
      ["data-box", "data-box-edge", "data-box-lead", "data-box-live"].forEach(function (a) { td.removeAttribute(a); });
      td.classList.remove("is-box-hot");
      td.classList.remove("is-box-focus");
      td.style.setProperty("--box-w", "");
      Array.prototype.forEach.call(td.querySelectorAll(".pfas-box-words"), function (w) { w.parentNode.removeChild(w); });
    });
  }
  function unboxRow(table, tr) {
    var ids = {};
    Array.prototype.forEach.call((tr || table).querySelectorAll("td[data-box-live]"), function (td) {
      ids[td.getAttribute("data-box")] = true;
    });
    Object.keys(ids).forEach(function (id) { unbox(table, id); });
  }
  /* a cell's own words: its flag's, or its number's (a blank, what it inherits) */
  function cellWords(td) {
    var flag = td.querySelector(".pfas-flag"), inp = td.querySelector("input.pfas-sheet-in:not([type=checkbox]):not([type=hidden])");
    if (flag) { return String(flag.textContent || "").trim(); }
    return inp ? String(inp.value || inp.getAttribute("placeholder") || "").trim() : null;
  }
  /* a live box stands only while every cell says what its words say (a value
     the browser restored on reload fires no event) */
  function checkBoxes(table) {
    Array.prototype.forEach.call(table.querySelectorAll("td[data-box-lead][data-box-live]"), function (lead) {
      var id = lead.getAttribute("data-box"), w = boxCells(table, id).map(function (td) {
        var words = td.querySelector(".pfas-box-words");
        return words ? String(words.textContent || "").trim() : null;
      }).filter(function (x) { return x !== null; })[0];
      if (boxCells(table, id).some(function (td) { return cellWords(td) !== w; })) { unbox(table, id); }
    });
  }
  function placeBoxes(table) {
    checkBoxes(table);
    Array.prototype.forEach.call(table.querySelectorAll("td[data-box-lead]"), function (first) {
      var lead = boxLead(table, first), r0 = lead.getBoundingClientRect(), right = r0.right;
      if (!r0.width) { return; }             /* folded or hidden: placed when it shows */
      boxCells(table, lead.getAttribute("data-box")).forEach(function (td) {
        var r = td.getBoundingClientRect();
        if (r.width && Math.abs(r.top - r0.top) < 1) { right = Math.max(right, r.right); }
      });
      lead.style.setProperty("--box-w", (right - r0.left) + "px");
    });
  }
  function initBoxes(table) {
    if (!table.querySelector("td[data-box]")) { return; }
    function light(e, on, focus) {
      var td = e.target && e.target.closest ? e.target.closest("td[data-box]") : null;
      if (!td || !table.contains(td)) { return; }
      boxCells(table, td.getAttribute("data-box")).forEach(function (c) {
        c.classList.toggle("is-box-hot", on);
        if (focus) { c.classList.toggle("is-box-focus", on); }
      });
    }
    table.addEventListener("mouseover", function (e) { light(e, true); });
    table.addEventListener("mouseout", function (e) { light(e, false); });
    table.addEventListener("focusin", function (e) { light(e, true, true); });
    table.addEventListener("focusout", function (e) { light(e, false, true); });
    /* a posted value changed in a row (typed, an editor's Done, Fill RLs,
       paste, a column's switch row by row); a selection is no change */
    function changed(e) {
      var t = e.target, tr = t && t.getAttribute && t.getAttribute("name") && t.closest ? t.closest("tbody tr") : null;
      if (tr && table.contains(tr)) { unboxRow(table, tr); }
    }
    table.addEventListener("input", changed, true);
    table.addEventListener("change", changed, true);
    /* typing in a boxed number shows its own value */
    table.addEventListener("focusin", function (e) {
      var td = e.target && e.target.matches && e.target.matches("input.pfas-sheet-in") ? e.target.closest("td[data-box-live]") : null;
      if (td) { unbox(table, td.getAttribute("data-box")); }
    });
    placeBoxes(table);
    if (window.ResizeObserver) {
      try { new window.ResizeObserver(function () { placeBoxes(table); }).observe(table); } catch (e) {}
    }
  }
  function initSheet(box) {
    var table = box.querySelector(".pfas-sheet");
    if (box.__pfas || !table) { return; }
    box.__pfas = true;
    initBoxes(table);
    Array.prototype.forEach.call(table.querySelectorAll(".pfas-seg"), initSeg);
    table.addEventListener("change", function (e) {
      var t = e.target, td = t.closest("td");
      if (t.classList.contains("pfas-sheet-all")) { sheetChecks(box).forEach(function (c) { c.checked = t.checked; }); }
      if (t.classList.contains("pfas-group-check")) {
        groupChecks(box, t.getAttribute("data-group")).forEach(function (c) { c.checked = t.checked; });
      }
      if (t.classList.contains("pfas-sheet-all") || t.classList.contains("pfas-sheet-check") ||
          t.classList.contains("pfas-group-check")) { sheetSync(box); return; }
      if (t.getAttribute("name")) { clearToast(box); }   /* a change made in the grid ends an action's Undo */
      if (t.closest(".pfas-sheet-colswitch")) { setColumn(box, t.getAttribute("data-col"), t.checked); return; }
      if (td && t.type === "checkbox" && t.classList.contains("pfas-sheet-in")) {
        syncColSwitch(box, td.getAttribute("data-col"));
        syncFlag(td);
      }
      /* an RL changed in its own cell (the drawer, a column action): its flag follows */
      var tr = t.getAttribute("name") ? t.closest("tr") : null;
      if (tr) { byAttr(tr.querySelectorAll(".pfas-flag"), "data-rl-name", t.getAttribute("name")).forEach(function (b) { syncFlag(b.closest("td")); }); }
      if (td && td.hasAttribute("data-opens-row")) { syncListWords(td); }
    });
    /* a list cell (td[data-opens-row]) is no button: a click, Enter or
       Space on it opens the row's drawer on that field */
    table.addEventListener("keydown", function (e) {
      var td = e.target;
      if ((e.key !== "Enter" && e.key !== " ") || !td.matches || !td.matches("td[data-opens-row]")) { return; }
      e.preventDefault();
      openListCell(box, td);
    });
    table.addEventListener("click", function (e) {
      var lc = e.target.closest("td[data-opens-row]");
      if (lc && table.contains(lc)) { openListCell(box, lc); return; }
      var fold = e.target.closest(".pfas-group-toggle");
      if (fold && table.contains(fold)) {
        var gr = fold.closest("tr"), key = gr.getAttribute("data-group"), open = gr.getAttribute("aria-expanded") !== "true";
        foldGroup(box, key, open);
        table.dispatchEvent(new CustomEvent("pfas:sheet-fold", { bubbles: true,
          detail: { sheet: table.getAttribute("data-sheet"), view: box.getAttribute("data-fold"), group: key, open: open } }));
        return;
      }
      var chip = e.target.closest(".pfas-colchip");
      if (chip && table.contains(chip)) { setColumn(box, chip.getAttribute("data-col"), true); return; }
      var f = e.target.closest(".pfas-flag");
      if (f && table.contains(f)) { openFlag(f.closest("td")); return; }
      var a = e.target.closest(".pfas-sheet-links");
      if (a && table.contains(a)) { e.preventDefault(); openSheetPop(a, a.nextElementSibling); return; }
      var x = e.target.closest(".pfas-sheet-expand");
      if (x && table.contains(x)) { toggleRegion(x); return; }
      var m = e.target.closest(".pfas-rowmenu");
      if (m && table.contains(m)) { openRowMenu(m); }
    });
    Array.prototype.forEach.call(table.querySelectorAll(EXPANDS), function (x) {
      syncExpand(x);
      /* a section opened or closed by its own summary: its buttons follow
         (toggle does not bubble, so on the section itself) */
      var r = expandTarget(x);
      if (r && isSection(r) && !r.__pfasExpand) { r.__pfasExpand = true; r.addEventListener("toggle", function () { syncRegion(r); }); }
    });
    var wrap = box.querySelector(".pfas-sheet-wrap");
    if (wrap) { wrap.addEventListener("scroll", scrollSheetPop); }
    var bar = box.querySelector(".pfas-sheet-bar");
    if (bar) {
      bar.querySelector(".pfas-sheet-edit").addEventListener("click", function () { openSheetSelected(box); });
      bar.querySelector(".pfas-sheet-clear").addEventListener("click", function () {
        sheetChecks(box).forEach(function (c) { c.checked = false; });
        sheetSync(box);
      });
      Array.prototype.forEach.call(bar.querySelectorAll("[data-action]"), function (b) {
        b.addEventListener("click", function () { columnAction(box, b); });
      });
    }
    var add = box.querySelector(".pfas-sheet-add"), adder = box.querySelector(".pfas-sheet-adder");
    if (add && adder) {
      add.addEventListener("click", function () {
        openSheetPop(add, adder, function () {
          var pick = adder.querySelector("select");
          if (pick && pick.querySelector("option[value='']") && pick.value !== "") { pick.value = ""; fire(pick); }
        });
        var s = adder.querySelector("select");
        if (s && !adder.hidden) { s.focus(); }
      });
      var cancel = adder.querySelector(".pfas-sheet-cancel");
      if (cancel) { cancel.addEventListener("click", function () { closeSheetPop(); add.focus(); }); }
    }
    var rb = box.querySelector(".pfas-sheet-remove");
    if (rb) { rb.addEventListener("click", function () { postRemove(box, memberRows(box)); }); }
    var pick = box.querySelector(".pfas-sheet-picker-btn"), picker = box.querySelector(".pfas-sheet-picker");
    if (pick && picker) {
      pick.addEventListener("click", function () { openSheetPop(pick, picker); });
      picker.addEventListener("change", function (e) {
        var col = e.target.getAttribute("data-col");
        if (col) { showColumn(box, col, e.target.checked); syncColChips(box); }
      });
      /* a column's chip: its \u2715 hides the column, as the picker would */
      var chips = box.querySelector(".pfas-colchips");
      if (chips) {
        chips.addEventListener("click", function (e) {
          var chip = e.target.closest(".pfas-colchip[data-col]");
          if (!chip) { return; }
          var col = chip.getAttribute("data-col"), cb = byAttr(picker.querySelectorAll("input[data-col]"), "data-col", col)[0];
          if (cb) { cb.checked = false; }
          showColumn(box, col, false);
          syncColChips(box);
          pick.focus();           /* the chip is gone: focus stays in the row */
        });
      }
      syncColChips(box);
    }
    if (!doc.__pfasSheetPop) {
      doc.__pfasSheetPop = true;
      doc.addEventListener("click", function (e) {
        if (sheetPop && !sheetPop.pop.contains(e.target) && !sheetPop.btn.contains(e.target)) { closeSheetPop(); }
      });
      doc.addEventListener("keydown", function (e) { if (e.key === "Escape") { closeSheetPop(false); } });
      /* a submit of a sheet's own form (its Save) ends that sheet's Undo; a
         submit refused (the footer's guard) or another form's leaves it */
      doc.addEventListener("submit", function (e) {
        var id = e.target && e.target.id;
        if (e.defaultPrevented || !id) { return; }
        byAttr(doc.querySelectorAll(".pfas-sheet-box"), "data-form", id).forEach(clearToast);
      });
    }
    if (sheetChecks(box).some(function (c) { return c.checked; })) { sheetSync(box); }   /* a selection the browser restored */
  }
  function openListCell(box, td) {
    var tr = td.closest("tr");
    if (tr && tr.getAttribute("data-row")) { openSheetRow(box, tr.getAttribute("data-row"), td.getAttribute("data-opens-row")); }
  }
  /* a list cell's words follow its hidden input: the items joined, a dash
     for none (an inherited list: its placeholder, muted) */
  function syncListWords(td) {
    var inp = td.querySelector("input.pfas-sheet-in"), w = td.querySelector(".pfas-sheet-val");
    if (!inp || !w) { return; }
    var v = String(inp.value || "").split(",").map(function (s) { return s.trim(); }).filter(Boolean).join(", ");
    var ph = String(inp.getAttribute("placeholder") || "").trim();
    w.textContent = v || ph || "—";
    w.classList.toggle("is-empty", !v && !ph);
    w.classList.toggle("is-inherited", !v && !!ph);
  }
  function initSheets(root) {
    var boxes = root.querySelectorAll(".pfas-sheet-box");
    for (var i = 0; i < boxes.length; i++) { initSheet(boxes[i]); }
  }
  var sheet = { init: initSheets, boxes: placeBoxes, selection: sheetSelection, openRow: openSheetRow, openGroup: openSheetGroup, openSelected: openSheetSelected,
                openFlag: openFlag, openRowMenu: openRowMenu, rowItems: sheetRowItems, fold: foldGroup,
                region: toggleRegion };

  /* Help: a .btn-help[data-help-entry] opens its entry in the panel beside
     the page (aside.pfas-help-panel, drawn once by the page macro), fetched
     bare from @@pfas-help. The panel is not modal: the page stays usable
     while it is open, and another Help button replaces the entry. An entry
     ends with its Related buttons: one opens in the same panel, and Close
     still goes back to the button on the page that opened the panel. The
     click is the button's own, so a Help button in a section's summary
     never opens or closes the section. The focus moves to the panel's title
     (which names the entry); Close, or Escape inside the panel, hides it and
     gives the focus back to that button. A page without the panel opens the
     Help page itself. */
  var HELP_LOADING = "Loading\u2026", HELP_FAILED = "This Help entry could not be loaded.";
  var help = { opener: null, seq: 0 };
  function helpPanel() { return doc.querySelector(".pfas-help-panel"); }
  function helpUrl(base, id, bare) {
    return base + (base.indexOf("?") < 0 ? "?" : "&") + "entry=" + encodeURIComponent(id) + (bare ? "&bare=1" : "");
  }
  function helpTerm(btn) {
    var label = btn.getAttribute("aria-label") || "";
    return label.indexOf("Help: ") === 0 ? label.slice(6) : squash(btn.textContent);
  }
  /* the entry's section out of the reply: whatever wraps it (a page frame
     added on the way) is left behind */
  function helpSection(html) {
    var t = doc.createElement("template");
    t.innerHTML = html || "";
    return (t.content || t).querySelector("section.help-entry");
  }
  function helpFailed(body, base, id) {
    body.textContent = "";
    var p = el("p", null, HELP_FAILED + " ");
    var a = el("a", "btn-sm btn-secondary", "Open in Help");
    a.setAttribute("href", helpUrl(base, id, false));
    p.appendChild(a);
    body.appendChild(p);
  }
  function openHelp(btn) {
    var id = btn.getAttribute("data-help-entry") || "";
    var panel = helpPanel(), base = panel ? panel.getAttribute("data-help-url") : "";
    if (!panel || !base || !window.fetch) {
      location.href = helpUrl(base || "@@pfas-help", id, false);
      return;
    }
    var title = panel.querySelector(".pfas-help-title"), body = panel.querySelector(".pfas-help-body");
    if (!panel.contains(btn)) {               /* a Related button keeps the page's opener */
      if (help.opener && help.opener !== btn) { help.opener.setAttribute("aria-expanded", "false"); }
      help.opener = btn;
      btn.setAttribute("aria-expanded", "true");
    }
    title.textContent = helpTerm(btn);
    body.textContent = HELP_LOADING;
    panel.setAttribute("data-entry", id);
    stay(panel, "is-leaving");
    panel.hidden = false;
    title.focus();
    var seq = ++help.seq;
    window.fetch(helpUrl(base, id, true), { credentials: "same-origin" })
      .then(function (r) { return r.text(); })
      .then(function (html) {
        if (seq !== help.seq) { return; }   /* another entry was asked for since, or the panel closed */
        var sec = helpSection(html);
        if (!sec) { helpFailed(body, base, id); return; }
        var h = sec.querySelector("h3");
        if (h) { title.textContent = squash(h.textContent); h.parentNode.removeChild(h); }
        body.textContent = "";
        body.appendChild(sec);
      }, function () {
        if (seq === help.seq) { helpFailed(body, base, id); }
      });
  }
  function closeHelp() {
    var panel = helpPanel();
    if (!panel || panel.hidden || panel.__pfasLeave) { return; }
    /* it slides out as it came, then hides */
    leave(panel, "is-leaving", function () { panel.hidden = true; });
    help.seq++;                             /* a reply still on its way is dropped */
    var opener = help.opener;
    help.opener = null;
    if (opener) {
      opener.setAttribute("aria-expanded", "false");
      try { opener.focus(); } catch (e) { /* gone from the page */ }
    }
  }
  function initHelp() {
    if (doc.__pfasHelp) { return; }
    doc.__pfasHelp = true;
    doc.addEventListener("click", function (e) {
      var t = e.target, btn = t && t.closest ? t.closest(".btn-help[data-help-entry]") : null;
      if (btn) { e.preventDefault(); openHelp(btn); return; }
      if (t && t.closest && t.closest(".pfas-help-close")) { closeHelp(); }
    });
    doc.addEventListener("keydown", function (e) {
      var panel = helpPanel(), a = doc.activeElement;
      if (e.key !== "Escape" || !panel || panel.hidden) { return; }
      if (a && (panel.contains(a) || a === help.opener)) { closeHelp(); }
    });
  }

  /* ── .pfas-menu: a context menu, or an Actions button's list ─────────────
     menu.open(items, opts) draws one menu at a time, fixed to the viewport
     and appended to the body (over the drawer and the page's dialogs).
     A menu opened from inside a modal dialog ([aria-modal="true"], the
     drawer) is drawn inside it, where assistive technology still reaches it.
     items: {id, label, key (the shortcut said beside it), disabled, reason
     (why it is disabled: its title and a muted line under it), checked
     (a choice of several, marked), act(item), items (a submenu, opening to
     the right, to the left when the right has no room)}, {sep: true} or
     {head: words} (a group's heading over the entries after it: read,
     never focused or chosen).
     opts: {x, y (viewport px; the pointer's), anchor (a node it opens under,
     above when there is no room below), opener (the focus goes back to it
     when the menu closes by a key or a choice), label}. Keys: the arrows,
     Home, End, Enter or Space, Escape, Tab, a first letter; it closes on a
     click outside it, a scroll, a resize, Escape or a choice; a disabled
     entry is reached and read, never acted on. */
  var MENU_MARGIN = 8;
  var menuState = null;
  /* where a menu of w x h opens at (x, y) in a viewport of vw x vh: to the
     left of x when the right has no room, up from `up` (y less its height
     when not given) when the bottom has none; never past the margin */
  function menuPlace(x, y, w, h, vw, vh, up) {
    var left = x + w > vw - MENU_MARGIN ? x - w : x, top = y;
    if (y + h > vh - MENU_MARGIN) { top = (up == null ? y : up) - h; }
    left = Math.max(MENU_MARGIN, Math.min(left, vw - MENU_MARGIN - w));
    top = Math.max(MENU_MARGIN, Math.min(top, vh - MENU_MARGIN - h));
    return { left: Math.round(left), top: Math.round(top) };
  }
  /* the side a submenu of width w opens on, beside its item's rect: right
     unless it would pass the viewport's width vw */
  function menuSide(rect, w, vw) { return rect.right + w <= vw - MENU_MARGIN ? "right" : "left"; }
  /* the index of the next label after `from` (wrapping) that starts with
     ch, ignoring case; -1 when none does */
  function menuFind(labels, ch, from) {
    var c = String(ch || "").toLowerCase(), n = labels.length;
    if (!c) { return -1; }
    for (var k = 1; k <= n; k++) {
      var i = ((from == null ? -1 : from) + k + n) % n;
      if (String(labels[i] || "").replace(/^\s+/, "").charAt(0).toLowerCase() === c) { return i; }
    }
    return -1;
  }
  function viewport() {
    var de = doc.documentElement || {};
    return { w: window.innerWidth || de.clientWidth || 1024, h: window.innerHeight || de.clientHeight || 768 };
  }
  /* where a menu opened from `opener` is drawn: inside the modal dialog that
     holds it, else the body */
  function menuHost(opener) {
    var modal = opener && opener.closest ? opener.closest('[aria-modal="true"]') : null;
    return modal || doc.body;
  }
  /* box set at viewport (left, top) inside host: a host that is transformed
     (the dialog drawer) is what fixed positioning is relative to, so the
     place is read against where the box lands at 0, 0 */
  function placeIn(box, host, left, top) {
    var dx = 0, dy = 0;
    if (host !== doc.body) {
      box.style.left = "0px";
      box.style.top = "0px";
      var r = box.getBoundingClientRect();
      dx = r.left;
      dy = r.top;
    }
    box.style.left = Math.round(left - dx) + "px";
    box.style.top = Math.round(top - dy) + "px";
  }
  function menuItems(box) {
    return Array.prototype.filter.call(box.children, function (n) { return n.classList.contains("pfas-menu-item"); });
  }
  function menuOff(item) { return item.getAttribute("aria-disabled") === "true"; }
  /* one list: its items as buttons, the separators, each submenu's items kept on its button */
  function menuBox(items, label, depth) {
    var box = doc.createElement("div");
    box.className = "pfas-menu" + (depth ? " is-sub" : "");
    box.setAttribute("role", "menu");
    if (label) { box.setAttribute("aria-label", label); }
    (items || []).forEach(function (it) {
      if (it.head) {
        var hd = doc.createElement("div");
        hd.className = "pfas-menu-head";
        hd.setAttribute("role", "presentation");
        hd.textContent = it.head;
        box.appendChild(hd);
        return;
      }
      if (it.sep) {
        var sep = doc.createElement("div");
        sep.className = "pfas-menu-sep";
        sep.setAttribute("role", "separator");
        box.appendChild(sep);
        return;
      }
      var b = doc.createElement("button");
      b.type = "button";
      b.className = "pfas-menu-item";
      b.setAttribute("tabindex", "-1");
      b.setAttribute("role", it.checked != null ? "menuitemradio" : "menuitem");
      if (it.checked != null) { b.setAttribute("aria-checked", it.checked ? "true" : "false"); }
      if (it.id) { b.setAttribute("data-id", it.id); }
      var h = '<span class="pfas-menu-label">' + escapeText(it.label) + "</span>";
      if (it.items) {
        b.setAttribute("aria-haspopup", "menu");
        b.setAttribute("aria-expanded", "false");
        h += '<span class="pfas-menu-key" aria-hidden="true">' + (icon("open", { hidden: true }) || "\u203a") + '</span>';
      } else if (it.key) {
        h += '<span class="pfas-menu-key">' + escapeText(it.key) + "</span>";
      }
      if (it.disabled) {
        b.setAttribute("aria-disabled", "true");
        if (it.reason) {
          b.title = it.reason;
          h += '<span class="pfas-menu-why">' + escapeText(it.reason) + "</span>";
        }
      } else if (it.note) {
        h += '<span class="pfas-menu-note">' + escapeText(it.note) + "</span>";
      }
      b.innerHTML = h;
      b.__pfasItem = it;
      box.appendChild(b);
    });
    return box;
  }
  function escapeText(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; });
  }
  function menuFocus(box, i) {
    var all = menuItems(box);
    if (!all.length) { return null; }
    var b = all[(i + all.length) % all.length];
    b.focus();
    return b;
  }
  function closeSub(box) {
    if (!box.__pfasSub) { return; }
    var sub = box.__pfasSub;
    box.__pfasSub = null;
    closeSub(sub);
    if (sub.parentNode) { sub.parentNode.removeChild(sub); }
    if (sub.__pfasFrom) { sub.__pfasFrom.setAttribute("aria-expanded", "false"); }
  }
  /* the submenu of item b of box, beside it; its first entry focused when asked */
  function openSub(box, b, focusFirst) {
    var it = b.__pfasItem;
    if (!it || !it.items || menuOff(b)) { return null; }
    if (box.__pfasSub && box.__pfasSub.__pfasFrom === b) {
      if (focusFirst) { menuFocus(box.__pfasSub, 0); }
      return box.__pfasSub;
    }
    closeSub(box);
    var sub = menuBox(it.items, it.label, 1);
    sub.__pfasFrom = b;
    sub.__pfasParent = box;
    wireMenu(sub);
    var host = box.parentNode || doc.body;
    host.appendChild(sub);
    var vp = viewport(), r = b.getBoundingClientRect(), s = sub.getBoundingClientRect();
    var side = menuSide(r, s.width, vp.w), at = menuPlace(side === "right" ? r.right : r.left - s.width, r.top,
                                                            s.width, s.height, vp.w, vp.h, r.bottom);
    sub.classList.toggle("is-left", side === "left");
    placeIn(sub, host, at.left, at.top);
    b.setAttribute("aria-expanded", "true");
    box.__pfasSub = sub;
    if (focusFirst) { menuFocus(sub, 0); }
    return sub;
  }
  /* a choice: the menu closes, the focus goes back to its opener, then the entry acts */
  function menuActivate(box, b) {
    var it = b.__pfasItem;
    if (!it || menuOff(b)) { return; }
    if (it.items) { openSub(box, b, true); return; }
    closeMenu(true);
    if (it.act) { it.act(it); }
  }
  function wireMenu(box) {
    box.addEventListener("click", function (e) {
      if (box.classList.contains("is-leaving")) { return; }   /* closed: it only fades */
      var b = e.target && e.target.closest ? e.target.closest(".pfas-menu-item") : null;
      if (b && b.parentNode === box) { menuActivate(box, b); }
    });
    box.addEventListener("mouseover", function (e) {
      var b = e.target && e.target.closest ? e.target.closest(".pfas-menu-item") : null;
      if (!b || b.parentNode !== box) { return; }
      b.focus();
      if (b.__pfasItem && b.__pfasItem.items) { openSub(box, b, false); } else { closeSub(box); }
    });
    box.addEventListener("keydown", function (e) {
      if (box.classList.contains("is-leaving")) { e.preventDefault(); return; }
      var all = menuItems(box), i = all.indexOf(doc.activeElement), b = all[i], k = e.key;
      var done = true;
      if (k === "ArrowDown") { menuFocus(box, i + 1); }
      else if (k === "ArrowUp") { menuFocus(box, i < 0 ? -1 : i - 1); }
      else if (k === "Home") { menuFocus(box, 0); }
      else if (k === "End") { menuFocus(box, -1); }
      else if (k === "ArrowRight") { if (b) { openSub(box, b, true); } }
      else if (k === "ArrowLeft" || k === "Escape") {
        if (box.__pfasParent) {
          var from = box.__pfasFrom;
          closeSub(box.__pfasParent);
          from.focus();
        } else if (k === "Escape") { closeMenu(true); }
      }
      else if (k === "Enter" || k === " ") { if (b) { menuActivate(box, b); } }
      else if (k === "Tab") { closeMenu(true); }
      else if (k && k.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
        var j = menuFind(all.map(function (x) { return x.__pfasItem ? x.__pfasItem.label : ""; }), k, i);
        if (j >= 0) { all[j].focus(); }
      } else { done = false; }
      if (done) { e.preventDefault(); e.stopPropagation(); }
    });
  }
  /* close the open menu (and its submenus); refocus: the focus back to its
     opener. It fades out as it came, taking no pointer while it does; now:
     at once (a menu opened in its place) */
  function closeMenu(refocus, now) {
    if (!menuState) { return; }
    var m = menuState;
    menuState = null;
    closeSub(m.box);
    var gone = function () { if (m.box.parentNode) { m.box.parentNode.removeChild(m.box); } };
    if (now) { gone(); } else { leave(m.box, "is-leaving", gone); }
    if (m.opener) {
      m.opener.removeAttribute("data-menu-open");
      if (m.opener.getAttribute("aria-haspopup") === "menu") { m.opener.setAttribute("aria-expanded", "false"); }
      if (refocus && m.opener.focus) { try { m.opener.focus(); } catch (e) { /* gone from the page */ } }
    }
    if (m.onClose) { m.onClose(); }
  }
  function inMenu(node) {
    for (var n = node; n && n.nodeType === 1; n = n.parentNode) { if (n.classList.contains("pfas-menu")) { return true; } }
    return false;
  }
  function watchMenus() {
    if (doc.__pfasMenus) { return; }
    doc.__pfasMenus = true;
    /* a press outside the menu closes it, the focus left where the press puts it; a
       press on a button that opens it (aria-haspopup) is left to its own click, which closes it */
    doc.addEventListener("pointerdown", function (e) {
      if (!menuState || inMenu(e.target)) { return; }
      var o = menuState.opener;
      if (o && o.getAttribute && o.getAttribute("aria-haspopup") === "menu" && o.contains(e.target)) { return; }
      closeMenu(false);
    }, true);
    window.addEventListener("scroll", function (e) { if (menuState && !inMenu(e.target)) { closeMenu(false); } }, true);
    window.addEventListener("resize", function () { closeMenu(false); });
  }
  function openMenu(items, opts) {
    opts = opts || {};
    closeMenu(false, true);
    watchMenus();
    var box = menuBox(items, opts.label, 0), opener = opts.opener || doc.activeElement, host = menuHost(opener);
    wireMenu(box);
    host.appendChild(box);
    var vp = viewport(), s = box.getBoundingClientRect(), x = opts.x, y = opts.y, up = null;
    if (opts.anchor) {
      var r = opts.anchor.getBoundingClientRect();
      x = r.left;
      y = r.bottom + 4;
      up = r.top - 4;
    }
    var at = menuPlace(x || 0, y || 0, s.width, s.height, vp.w, vp.h, up);
    placeIn(box, host, at.left, at.top);
    if (opener && opener.setAttribute) {
      opener.setAttribute("data-menu-open", "true");
      if (opener.getAttribute("aria-haspopup") === "menu") { opener.setAttribute("aria-expanded", "true"); }
    }
    menuState = { box: box, opener: opener, onClose: opts.onClose || null };
    menuFocus(box, 0);
    return box;
  }
  var menu = { open: openMenu, close: closeMenu, isOpen: function () { return !!menuState; },
               place: menuPlace, side: menuSide, find: menuFind };

  /* ── A table row: the whole row opens its item; its actions are its menu ──
     A row states its item's address once (data-row-open; or data-row-dialog,
     the id of the .pfas-modal that shows its detail) and its actions
     once (data-row-actions: a JSON list written by row_menu.actions, each
     {label, and one of href, modal (a .pfas-modal id), form (a form's id,
     with optional values to set and a confirm) or event (a name: the row
     hears "pfas:row-action" with {name, row}; "remove-row" removes it), note,
     blank, danger, off});
     no button or link stands inside a row. A click anywhere on the row
     opens the item (Ctrl, Cmd, Shift or the middle button: a new tab), the
     row is a Tab stop and Enter opens it. The actions are the row's menu: a
     right click with a mouse, the menu key or Shift+F10 on the focused
     row, and on a touch screen a long press or the quiet ⋯ drawn at the
     row's end, which a mouse never sees (td.row-plus-cell). */
  var ROW = "tr[data-row-open], tr[data-row-dialog], tr[data-row-actions]";
  /* a hierarchy's node with a row menu (.pfas-hier: the node is the row),
     or a card's mini-card standing for an item with no node of its own */
  var NODE_ROW = ".pfas-hier-node[data-row-actions], .pfas-hier-mini[data-row-actions]";
  var OPENS = "tr[data-row-open], tr[data-row-dialog]";
  var ROW_SKIP = "a[href], button, input, select, textarea, label, summary, details, [role=button], [contenteditable], .pfas-menu";
  var rowPressedAt = 0;
  /* the row's item: its page (a modifier or the middle button: a new tab) or its dialog */
  function rowOpen(tr, blank) {
    var dlg = tr.getAttribute("data-row-dialog"), m = dlg ? doc.getElementById(dlg) : null;
    if (m) { openModal(m); return; }
    rowGo(tr.getAttribute("data-row-open"), blank);
  }
  function rowGo(url, blank) {
    if (!url) { return; }
    if (blank) { window.open(url, "_blank", "noopener"); return; }
    window.location.assign(url);
  }
  function rowActions(tr) {
    var list = [];
    try { list = JSON.parse(tr.getAttribute("data-row-actions") || "[]"); } catch (e) { list = []; }
    return Array.isArray(list) ? list : [];
  }
  function openModal(m) { m.classList.add("open"); }
  function submitForm(f) {
    var b = f.querySelector("button[type=submit], input[type=submit]");
    if (f.requestSubmit) { f.requestSubmit(b || null); } else if (b) { b.click(); } else { f.submit(); }
  }
  function rowAct(a, tr) {
    if (a.href) { rowGo(a.href, !!a.blank); return; }
    if (a.event) {
      tr.dispatchEvent(new CustomEvent("pfas:row-action", { bubbles: true, detail: { name: a.event, row: tr } }));
      return;
    }
    if (a.modal) {
      var m = doc.getElementById(a.modal);
      if (m) { openModal(m); }
      return;
    }
    var f = a.form ? doc.getElementById(a.form) : null;
    if (!f) { return; }
    Object.keys(a.values || {}).forEach(function (k) {
      var n = f.querySelector('[name="' + k + '"]');
      if (!n) { n = el("input"); n.type = "hidden"; n.name = k; f.appendChild(n); }
      n.value = String(a.values[k]);
    });
    if (a.confirm && !window.confirm(a.confirm)) { return; }
    submitForm(f);
  }
  /* the row's menu as groups: its actions with Open in a new tab, then the
     ones that end or remove something (danger) after a separator */
  function rowItems(tr) {
    var url = tr.getAttribute("data-row-open"), acts = [], last = [];
    rowActions(tr).forEach(function (a) {
      if (!a || !a.label) { return; }
      var it = { label: String(a.label), note: a.note ? String(a.note) : "", act: function () { rowAct(a, tr); } };
      if (a.off) { it.disabled = true; it.reason = String(a.off); }
      (a.danger ? last : acts).push(it);
    });
    if (url) { acts.push({ label: "Open in a new tab", act: function () { rowGo(url, true); } }); }
    return [acts, last];
  }
  /* a table whose rows carry actions: a cell at the end of every row for
     the touch screen's ⋯, and a heading for it, so no column shifts */
  function dotCell(r) {
    var last = r.lastElementChild;
    if (last && last.classList.contains("row-plus-cell")) { return; }
    var head = !r.closest("tbody") && !r.querySelector("td");
    var c = el(head ? "th" : "td", "row-plus-cell");
    if (head) { c.setAttribute("aria-hidden", "true"); }
    if (!head && r.matches(ROW) && rowActions(r).length) {
      var b = el("button", "pfas-rowmenu");
      b.innerHTML = icon("more", { hidden: true }) || "\u22ef";
      b.type = "button";
      b.setAttribute("aria-haspopup", "menu");
      b.setAttribute("aria-label", "Actions");
      c.appendChild(b);
    }
    r.appendChild(c);
  }
  function rowDots(tr) {
    var table = tr.closest("table");
    if (!table) { return; }
    if (table.__pfasDots) { dotCell(tr); return; }   /* a row added later */
    table.__pfasDots = true;
    Array.prototype.forEach.call(table.querySelectorAll("tr"), dotCell);
  }
  function initRowLinks(root) {
    root = root || doc;
    var rows = Array.prototype.slice.call(root.querySelectorAll(ROW));
    if (root.matches && root.matches(ROW)) { rows.unshift(root); }
    for (var i = 0; i < rows.length; i++) {
      var tr = rows[i];
      if (tr.__pfasRow || !tr.closest("tbody")) { continue; }
      tr.__pfasRow = true;
      if (!tr.hasAttribute("tabindex")) { tr.setAttribute("tabindex", "0"); }
      if (rowActions(tr).length) { rowDots(tr); }
    }
    if (doc.__pfasRows) { return; }
    doc.__pfasRows = true;
    function rowOf(t) {
      if (!t || !t.closest) { return null; }
      var tr = t.closest(ROW);
      if (!tr || !tr.closest("tbody")) { return null; }
      var skip = t.closest(ROW_SKIP);
      return skip && tr.contains(skip) && skip !== tr ? null : tr;
    }
    function selecting(tr) {
      var sel = window.getSelection ? window.getSelection() : null;
      return !!(sel && !sel.isCollapsed && String(sel).trim() && sel.anchorNode && tr.contains(sel.anchorNode));
    }
    doc.addEventListener("click", function (e) {
      var dots = e.target && e.target.closest ? e.target.closest("td.row-plus-cell > .pfas-rowmenu") : null;
      if (dots) {
        var owner = dots.closest(ROW);
        if (!owner) { return; }
        e.preventDefault();
        if (menuState && menuState.opener === dots) { closeMenu(true); return; }
        openMenu(contextItems(owner), { anchor: dots, opener: dots });
        return;
      }
      var tr = rowOf(e.target);
      if (!tr || e.defaultPrevented || e.button) { return; }
      if (Date.now() - rowPressedAt < 800) { e.preventDefault(); return; }   /* the long press's lift */
      if (!tr.matches(OPENS) || selecting(tr)) { return; }
      rowOpen(tr, e.ctrlKey || e.metaKey || e.shiftKey);
    });
    doc.addEventListener("auxclick", function (e) {
      var tr = rowOf(e.target);
      if (tr && e.button === 1 && tr.getAttribute("data-row-open")) { e.preventDefault(); rowGo(tr.getAttribute("data-row-open"), true); }
    });
    doc.addEventListener("keydown", function (e) {
      var tr = e.target;
      if (!tr || !tr.matches || !tr.matches(ROW) || !tr.closest("tbody")) { return; }
      /* the menu key or Shift+F10 on the focused row: its menu, under the row */
      if (e.key === "ContextMenu" || (e.shiftKey && e.key === "F10")) {
        var items = contextItems(tr);
        if (items.length) { e.preventDefault(); openMenu(items, { anchor: tr, opener: tr }); }
        return;
      }
      if (e.key !== "Enter" || !tr.matches(OPENS)) { return; }
      e.preventDefault();
      rowOpen(tr, e.ctrlKey || e.metaKey);
    });
    /* a long press on a touch screen: the row's menu where the finger is */
    var press = null;
    function unpress() { if (press) { clearTimeout(press.timer); press = null; } }
    doc.addEventListener("pointerdown", function (e) {
      unpress();
      var tr = e.pointerType === "touch" ? (rowOf(e.target) || (e.target.closest ? e.target.closest(NODE_ROW) || e.target.closest("[data-limit-box]") : null) || tileFor(e.target)) : null;
      if (!tr) { return; }
      var x = e.clientX, y = e.clientY, t = e.target;
      press = { x: x, y: y, timer: setTimeout(function () {
        press = null;
        rowPressedAt = Date.now();
        if (menuState) { return; }   /* the browser's own long press already opened it */
        var items = contextItems(t);
        if (items.length) { openMenu(items, { x: x, y: y, opener: tr }); }
      }, 500) };
    });
    doc.addEventListener("pointermove", function (e) {
      if (press && (Math.abs(e.clientX - press.x) > 10 || Math.abs(e.clientY - press.y) > 10)) { unpress(); }
    });
    doc.addEventListener("pointerup", unpress);
    doc.addEventListener("pointercancel", unpress);
    /* an editable grid's row taken out: the form no longer posts its fields */
    doc.addEventListener("pfas:row-action", function (e) {
      var tr = e.detail && e.detail.row;
      if (e.detail.name !== "remove-row" || !tr || !tr.parentNode) { return; }
      var next = tr.nextElementSibling || tr.previousElementSibling;
      tr.parentNode.removeChild(tr);
      if (next && next.focus) { next.focus(); }
    });
  }

  /* ── Right click: a menu for what was clicked ─────────────────────────────
     On every page a right click (a long press on a touch screen; the menu key
     or Shift+F10 on what has the focus) opens .pfas-menu with what can be
     done to what is under it, nearest first: a value's Edit, its record and
     Copy; the row's actions (its \u22ef menu, its More menu, its own buttons)
     and Open for the row's record; a link's Open, Open in a new tab and Copy
     link; a button's own action; the section's help. A text box and selected
     text keep the browser's own menu (copy, paste), as does a place with
     nothing to offer, and Shift with the click always gives the browser's. */
  var TEXT_BOX = "input:not([type=checkbox]):not([type=radio]):not([type=button]):not([type=submit]):not([type=reset])" +
                 ":not([type=hidden]), textarea, select, [contenteditable=''], [contenteditable='true']";
  function said(n) {
    return String((n && (n.getAttribute("aria-label") || n.textContent || n.value)) || "").replace(/\s+/g, " ").trim();
  }
  function clipped(text, n) { return text.length > n ? text.slice(0, n - 1) + "\u2026" : text; }
  function copyText(text) {
    try { if (navigator.clipboard && navigator.clipboard.writeText) { navigator.clipboard.writeText(text); return; } } catch (e) {}
    var ta = el("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    doc.body.appendChild(ta);
    ta.select();
    try { doc.execCommand("copy"); } catch (e) {}
    doc.body.removeChild(ta);
  }
  function followable(a) { return !/^(#|javascript:)/i.test(a.getAttribute("href") || ""); }
  function offItem(n) { return !!n.disabled || n.getAttribute("aria-disabled") === "true"; }
  function pressItem(label, n) {
    var it = { label: label, act: function () { n.click(); } };
    if (offItem(n)) { it.disabled = true; it.reason = n.getAttribute("title") || ""; }
    return it;
  }
  /* the actions a row offers outside its \u22ef menu: its More menu's entries
     and its own buttons and links, each pressed as if clicked */
  function rowButtons(tr) {
    var out = [];
    Array.prototype.forEach.call(tr.querySelectorAll(".row-more-menu button, .row-more-menu a[href], .row-more-menu input[type=submit]," +
                                                     " .row-actions button, .row-actions a[href], .row-actions-cell button," +
                                                     " .row-actions-cell a[href], .row-action"), function (n) {
      if (out.some(function (o) { return o.n === n; }) || n.closest("summary") || n.type === "hidden") { return; }
      var words = said(n);
      if (words) { out.push({ n: n, item: pressItem(clipped(words, 40), n) }); }
    });
    return out.map(function (o) { return o.item; });
  }
  /* ── A limit box's state (limit_placard.py) ──────────────────────────────
     Every limit box ([data-limit-box]: a tile, a cell, a tier row) carries a
     placard of its state, Enforced, Evaluate or Off; its one posted input is
     limitstate.<box> (drawn once, with the tab's Table view). A right click
     on the box, the menu key or Shift+F10 on it, or a long press opens the
     menu with its State group first: the three states, the one in force
     checked, and Use the method default where the state differs from it.
     A choice changes that box alone: it writes the input (a change the
     page's Save counts), and every placard of the box redraws. */
  var LIMIT_GLYPH = { enforced: "\u25cf", evaluate: "\u25d0", off: "\u29b8" };
  var LIMIT_WORDS = { enforced: "Enforced", evaluate: "Evaluate", off: "Off" };
  var LIMIT_LABEL = "State: ";          /* limit_placard.STATE_LABEL */
  /* the glyph alone, drawn (limit_placard.GLYPH_SVG, GLYPH_SVG_DEFAULT):
     filled for a state set on this profile, outlined for the method default */
  var LIMIT_SVG_RING = '<circle cx="8" cy="8" r="5.75" fill="none" stroke="currentColor" stroke-width="1.5"/>';
  var LIMIT_SVG = {
    enforced: '<circle cx="8" cy="8" r="6.5" fill="currentColor"/>',
    evaluate: LIMIT_SVG_RING + '<path d="M8 1.5a6.5 6.5 0 0 0 0 13z" fill="currentColor"/>',
    off: '<path fill-rule="evenodd" fill="currentColor" d="M1.5 8a6.5 6.5 0 1 0 13 0a6.5 6.5 0 1 0-13 0zM4.78 3.02l8.2 8.2-1.76 1.76-8.2-8.2z"/>'
  };
  var LIMIT_SVG_DEFAULT = {
    enforced: LIMIT_SVG_RING,
    evaluate: LIMIT_SVG_RING + '<path d="M8 2.25v11.5" stroke="currentColor" stroke-width="1.5"/>',
    off: LIMIT_SVG_RING + '<path d="M3.9 3.9l8.2 8.2" stroke="currentColor" stroke-width="1.5"/>'
  };
  [LIMIT_SVG, LIMIT_SVG_DEFAULT].forEach(function (map) {
    Object.keys(map).forEach(function (st) {
      map[st] = '<svg class="pfas-glyph" viewBox="0 0 16 16" focusable="false" aria-hidden="true">' + map[st] + "</svg>";
    });
  });
  /* the box's one input: the name its greying follows (data-mute-if) */
  function limitInput(box) {
    var name = box.getAttribute("data-mute-if") || "limitstate." + box.getAttribute("data-limit-box");
    return doc.getElementsByName(name)[0] || null;
  }
  /* a placard that is a choice field's own control (limit_placard.choice_box):
     its states and the value each posts, [[state, value]] in menu order */
  function limitValues(box) {
    var v = box.getAttribute("data-limit-values");
    if (!v) { return null; }
    try { v = JSON.parse(v); } catch (e) { return null; }
    return Array.isArray(v) && v.length ? v : null;
  }
  function limitState(box) {
    var input = limitInput(box), vals = limitValues(box);
    if (vals) {
      var hit = input ? vals.filter(function (x) { return x[1] === input.value; })[0] : null;
      return hit ? hit[0] : (box.getAttribute("data-limit-state") || vals[0][0]);
    }
    return (input && input.value) || box.getAttribute("data-limit-state") || "enforced";
  }
  function drawLimit(key, state, held) {
    Array.prototype.forEach.call(doc.querySelectorAll("[data-limit-box]"), function (box) {
      if (box.getAttribute("data-limit-box") !== key) { return; }
      box.setAttribute("data-limit-state", state);
      box.classList.toggle("is-muted", state === "off");
      Array.prototype.forEach.call(box.querySelectorAll("[data-limit-placard]"), function (p) {
        if (p.getAttribute("data-limit-placard") !== key) { return; }
        placardGhost(p);
        ["enforced", "evaluate", "off"].forEach(function (st) { p.classList.toggle("is-" + st, st === state); });
        if (held) { p.classList.remove("is-default"); }
        p.classList.toggle("is-unset", state === "enforced" && p.classList.contains("is-empty"));
        var g = p.querySelector(".pfas-placard-g"), w = p.querySelector(".pfas-placard-w");
        /* a glyph alone is drawn (limit_placard.GLYPH_SVG), a word's glyph is text */
        if (g) {
          if (g.querySelector("svg")) { g.innerHTML = (p.classList.contains("is-default") ? LIMIT_SVG_DEFAULT : LIMIT_SVG)[state]; }
          else { g.textContent = LIMIT_GLYPH[state]; }
        }
        if (w) { w.textContent = LIMIT_WORDS[state]; }
        p.setAttribute("title", LIMIT_WORDS[state]);
        /* a glyph alone (a card's corner, a grid cell's mark) is an image
           whose label is the state, as its hover says */
        if (p.hasAttribute("aria-label")) { p.setAttribute("aria-label", LIMIT_LABEL + LIMIT_WORDS[state]); }
        arrive(p, "is-arriving");
      });
    });
    drawGlyphs(doc);
  }
  /* a state change cross-fades: a copy of the old placard, laid over it,
     fades out while the new one fades and grows in (--t-fast). The copy is
     no placard of the box (no data-limit-placard) and is hidden from
     assistive technology. */
  function placardGhost(p) {
    if (!p.getAnimations || !p.getClientRects || !p.parentNode || !p.getClientRects().length) { return; }
    var g = p.cloneNode(true);
    g.removeAttribute("data-limit-placard");
    g.removeAttribute("title");
    g.removeAttribute("role");
    g.removeAttribute("aria-label");
    g.classList.remove("is-arriving");
    g.classList.add("pfas-placard-ghost");
    g.setAttribute("aria-hidden", "true");
    g.style.margin = "0";
    p.parentNode.insertBefore(g, p);
    var a = g.getBoundingClientRect(), b = p.getBoundingClientRect();
    g.style.marginLeft = Math.round(b.left - a.left) + "px";
    g.style.marginTop = Math.round(b.top - a.top) + "px";
    leave(g, "is-leaving", function () { if (g.parentNode) { g.parentNode.removeChild(g); } });
  }
  /* A list row's state (.pfas-state-g, profile_grids): the placard's glyph
     in the placard's colour, its word kept as visually hidden text, so the
     row's name still says it. A rule with limit boxes (data-glyph-inputs:
     their posted inputs) shows a glyph for each state its boxes hold, in
     the order Enforced, Evaluate, Off; a rule with none shows the state its
     own input holds (data-state-of), the method default's while it is blank.
     A line that is words (no .pfas-state-g) is written as words. */
  function glyphStates(line) {
    var held = [];
    (line.getAttribute("data-glyph-inputs") || "").split(" ").forEach(function (n) {
      var inp = n ? doc.getElementsByName(n)[0] : null, v = inp ? inp.value : "";
      if (LIMIT_WORDS[v] && held.indexOf(v) < 0) { held.push(v); }
    });
    return ["enforced", "evaluate", "off"].filter(function (st) { return held.indexOf(st) >= 0; });
  }
  function stateLine(line, value) {
    if (!line.classList || !line.classList.contains("pfas-state-g")) {
      line.textContent = value ? (LIMIT_WORDS[value] || value) : (line.getAttribute("data-inherited") || "");
      return;
    }
    var states = glyphStates(line), words;
    if (states.length) {
      words = states.map(function (st) { return LIMIT_WORDS[st]; }).join(", ");
    } else {
      var st = value || line.getAttribute("data-state") || "";
      states = LIMIT_GLYPH[st] ? [st] : [];
      words = value ? (LIMIT_WORDS[value] || value) : (line.getAttribute("data-inherited") || LIMIT_WORDS[st] || "");
    }
    line.textContent = "";
    states.forEach(function (st) {
      var g = el("span", "pfas-state-m is-" + st, LIMIT_GLYPH[st]);
      g.setAttribute("aria-hidden", "true");
      line.appendChild(g);
    });
    line.appendChild(el("span", "pfas-sr-hide", words));
  }
  function drawGlyphs(root) {
    Array.prototype.forEach.call((root || doc).querySelectorAll(".pfas-state-g"), function (line) {
      var own = doc.getElementById(line.getAttribute("data-state-of") || "");
      stateLine(line, own ? own.value : "");
    });
    groupStates(root);
  }
  /* A group node of the rules list (profile_grids._group_state) is active,
     green, while any limit box of its rules is Enforced or Evaluate, and
     idle, grey, while every one is Off: read from the state lines it draws
     (their boxes' inputs, else the rule's own state). A parent
     (data-group-of: its groups' keys) is active while any of its groups
     is. Its words (data-group-words) say which. */
  function lineStates(line) {
    var held = glyphStates(line);
    if (held.length) { return held; }
    var own = doc.getElementById(line.getAttribute("data-state-of") || "");
    var v = (own && own.value) || line.getAttribute("data-state") || "";
    return v ? [v] : [];
  }
  function markGroup(n, on) {
    n.classList.toggle("is-active", on);
    n.classList.toggle("is-idle", !on);
    var w = n.querySelector("[data-group-words]");
    if (w) { w.textContent = w.getAttribute(on ? "data-on-words" : "data-off-words") || w.textContent; }
  }
  function groupStates(root) {
    var nodes = (root || doc).querySelectorAll(".pfas-hier-node.is-group.is-active, .pfas-hier-node.is-group.is-idle");
    var parents = [];
    Array.prototype.forEach.call(nodes, function (n) {
      if (n.hasAttribute("data-group-of")) { parents.push(n); return; }
      var lines = n.querySelectorAll(".pfas-state-g");
      if (!lines.length) { return; }
      markGroup(n, Array.prototype.some.call(lines, function (l) {
        return lineStates(l).some(function (st) { return st !== "off"; });
      }));
    });
    parents.forEach(function (p) {
      var hier = p.closest(".pfas-hier") || doc;
      markGroup(p, (p.getAttribute("data-group-of") || "").split(" ").some(function (k) {
        var g = k ? hier.querySelector('.pfas-hier-node.is-group[data-hier-target="' + k + '"]') : null;
        return !!g && g.classList.contains("is-active");
      }));
    });
  }
  function initGlyphs(root) {
    drawGlyphs(root);
    watchGlyphs();
  }
  /* a box's state set anywhere (its menu, a script writing its input):
     every row that shows it follows */
  function watchGlyphs() {
    if (doc.__pfasGlyphs) { return; }
    doc.__pfasGlyphs = true;
    ["input", "change"].forEach(function (t) {
      doc.addEventListener(t, function (e) {
        var n = e.target && e.target.name;
        if (n && (n.indexOf("limitstate.") === 0 || n.indexOf("rulestate.") === 0)) { drawGlyphs(doc); }
      });
    });
  }
  function setLimit(box, state) {
    var key = box.getAttribute("data-limit-box"), input = limitInput(box), vals = limitValues(box);
    var hit = vals ? vals.filter(function (x) { return x[0] === state; })[0] : null;
    var value = hit ? hit[1] : state;
    if (input && input.value !== value) {
      input.value = value;
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
    }
    drawLimit(key, state, true);
  }
  function limitItems(box) {
    var now = limitState(box), seed = box.getAttribute("data-limit-seed") || "", vals = limitValues(box);
    var states = vals ? vals.map(function (x) { return x[0]; }) : ["enforced", "evaluate", "off"];
    var items = states.map(function (st) {
      return { label: LIMIT_WORDS[st], checked: st === now, act: function () { setLimit(box, st); } };
    });
    /* its limits' editor is the tile's own menu entry, drawn after this group */
    if (seed && seed !== now) {
      items.push({ label: "Use the method default", note: LIMIT_WORDS[seed] || "",
                   act: function () { setLimit(box, seed); } });
    }
    if (!limitInput(box)) {
      items.forEach(function (it) { it.disabled = true; it.reason = "Not editable here"; });
    }
    return items;
  }

  /* the menu for a node, as groups of entries (a separator between groups) */
  function contextItems(target) {
    var groups = [], seen = {};
    function group(items) {
      items = items.filter(function (it) {
        if (!it) { return false; }
        if (it.head) { return true; }
        if (seen[it.label]) { return false; }
        seen[it.label] = true;
        return true;
      });
      /* a heading alone, its entries all offered above, is no group */
      if (items.some(function (it) { return !it.head; })) { groups.push(items); }
    }
    /* a row that states its actions (data-row-actions): those first; a
       hierarchy's node states them the same way (it is a button, so its
       own press is choosing it, never an entry of its menu) */
    sourceGroups(target, true).forEach(group);
    var node = target.closest(NODE_ROW);
    if (node) { rowItems(node).forEach(group); }
    var tile = tileFor(target);
    if (tile) { tileItems(tile, tileSpec(tile).menu).forEach(group); }
    var head = target.closest(".pfas-hier-card-t"), hcard = head ? head.closest("[data-hier-card]") : null;
    if (hcard) { headItems(hcard).forEach(group); }
    var tr = target.closest("tbody tr"), declared = !!(tr && tr.matches(ROW));
    if (declared) { rowItems(tr).forEach(group); }
    var cell = target.closest("td, tbody th"), value = [];
    var edit = cell && cell.querySelector(".pfas-cell-btn, .pfas-flag");
    if (edit) { value.push(pressItem("Edit", edit)); }
    var prov = target.closest("[data-prov]");
    if (prov) { value.push(pressItem("Where does this number come from?", prov)); }
    /* what the cell shows, never a button's spoken label; a cell one types
       into copies with the browser's own menu */
    var shown = cell ? String((edit || cell).textContent || "").replace(/\s+/g, " ").trim() : "";
    var typed = cell && Array.prototype.some.call(cell.querySelectorAll(TEXT_BOX), function (n) { return !n.classList.contains("pfas-sr-hide"); });
    if (shown && !typed) { value.push({ label: "Copy value", act: function () { copyText(shown); } }); }
    group(value);
    if (tr && !declared) {
      var row = [], rm = tr.querySelector(".pfas-rowmenu");
      if (rm) { row = row.concat(rowMenuItems(rm)); }
      row = row.concat(rowButtons(tr));
      var first = Array.prototype.filter.call(tr.querySelectorAll("a[href]"), followable)[0];
      if (first && !target.closest("a[href]") && !first.closest(".row-more-menu, .row-actions, .row-actions-cell")) {
        row.unshift({ label: "Open " + clipped(said(first), 40), act: function () { first.click(); } });
      }
      group(row);
    }
    var a = target.closest("a[href]");
    if (a && followable(a)) {
      group([{ label: "Open", act: function () { a.click(); } },
             { label: "Open in a new tab", act: function () { window.open(a.href, "_blank", "noopener"); } },
             { label: "Copy link", act: function () { copyText(a.href); } }]);
    }
    var ctl = target.closest("button, [role=button], [role=tab], summary, label.pfas-switch");
    if (ctl && ctl !== node &&
        !(tr && ctl.closest(".row-more-menu, .row-actions, .row-actions-cell, .pfas-rowmenu")) &&
        !ctl.classList.contains("pfas-cell-btn") && !ctl.classList.contains("pfas-flag") && !ctl.classList.contains("btn-help")) {
      var box = ctl.matches("label.pfas-switch") ? ctl.querySelector("input[type=checkbox]") : null;
      if (box) { group([pressItem(box.checked ? "Switch off" : "Switch on", box)]); }
      else if (said(ctl)) { group([pressItem(clipped(said(ctl), 40), ctl)]); }
    }
    var scope = target.closest("details.pfas-sec, section, .pfas-card, .pfas-sheet-box, fieldset, .pfas-pane, form");
    var help = scope && scope.querySelector(".btn-help");
    if (help && !target.closest(".btn-help")) { group([pressItem("Help", help)]); }
    sourceGroups(target, false).forEach(group);
    var out = [];
    groups.forEach(function (g, i) { if (i) { out.push({ sep: true }); } out = out.concat(g); });
    return out;
  }
  /* ── A card's tiles: a click opens the window that edits the tile ─────────
     A card draws no Edit button. Its actions are drawn once, as triggers:
     <button data-act="KEY"> in the card's (or a block's) hidden
     .pfas-hier-acts, each keeping the attributes its page script hears, so a
     trigger pressed opens what its button opened; a trigger hidden itself is
     not offered at present, one marked data-danger comes last. A tile names
     what it opens (data-tile-open="KEY") and what its menu offers
     (data-tile-menu, a JSON list of KEYs, else the open one), on itself or on
     the block or card holding it, the nearest winning; KEY is looked up from
     the tile outwards. data-tile-read: nowhere to edit it, the tile opens a
     window that reads it. A left click anywhere on the tile but an inline
     control (a switch, a segment, a button, a link, a field) presses its
     trigger; the tile is a Tab stop and Enter does the same; a right click,
     the menu key, Shift+F10 or a long press gives its menu. The window
     focuses the field the tile reads and gives the focus back to the tile. */
  var TILE = ".pfas-hier-tile, .pfas-hier-tilebox";
  var TILE_SKIP = "a[href], button, input, select, textarea, label, summary, .pfas-seg, .pfas-switch, [contenteditable]," +
                  " .pfas-menu, .pfas-hier-mini";
  var tilePending = null;
  /* the nearest of `attrs` on the tile or what holds it, up to its card: [attr, value] */
  function tileUp(tile, attrs) {
    for (var n = tile; n && n.nodeType === 1; n = n.parentNode) {
      for (var i = 0; i < attrs.length; i++) { if (n.hasAttribute(attrs[i])) { return [attrs[i], n.getAttribute(attrs[i])]; } }
      if (n.hasAttribute("data-hier-card")) { break; }
    }
    return null;
  }
  /* what a tile does: {open: KEY, read: true, menu: [KEY]}, or null for a tile that only reads where it is */
  function tileDepth(tile, attr) {
    var d = 0;
    for (var n = tile; n && n.nodeType === 1; n = n.parentNode, d++) {
      if (n.hasAttribute(attr)) { return d; }
      if (n.hasAttribute("data-hier-card")) { break; }
    }
    return -1;
  }
  /* the menu is the nearest one no farther out than what the tile opens,
     and always offers what the tile opens */
  function tileSpec(tile) {
    if (!tile || !tile.matches || !tile.matches(TILE)) { return null; }
    var o = tileUp(tile, ["data-tile-open", "data-tile-read"]), m = tileUp(tile, ["data-tile-menu"]), menu = [];
    var open = o && o[0] === "data-tile-open" ? o[1] : "";
    if (m && !(open && tileDepth(tile, "data-tile-menu") > tileDepth(tile, "data-tile-open"))) {
      try { menu = JSON.parse(m[1] || "[]") || []; } catch (e) { menu = []; }
    }
    if (open && menu.indexOf(open) < 0) { menu = [open].concat(menu); }
    var spec = { open: open, read: !!(o && o[0] === "data-tile-read"), menu: menu };
    return spec.open || spec.read || menu.length ? spec : null;
  }
  /* the acts a node holds as its own (not a nested card's or block's) */
  function ownActs(n) {
    var out = [];
    for (var i = 0; i < n.children.length; i++) {
      var box = n.children[i];
      if (!box.classList.contains("pfas-hier-acts")) { continue; }
      for (var j = 0; j < box.children.length; j++) { if (box.children[j].hasAttribute("data-act")) { out.push(box.children[j]); } }
    }
    return out;
  }
  /* the trigger KEY names, from `from` outwards up to its card */
  function actOf(from, key) {
    for (var n = from; n && n.nodeType === 1; n = n.parentNode) {
      var hit = ownActs(n).filter(function (b) { return b.getAttribute("data-act") === key; })[0];
      if (hit) { return hit; }
      if (n.hasAttribute("data-hier-card")) { break; }
    }
    return null;
  }
  function actOffered(b) { return !!b && !b.hidden && !b.disabled; }
  /* a trigger as a menu entry: a refused one (disabled) drawn off, its title saying why */
  function actItem(b, from) {
    var it = { label: String(b.textContent || "").replace(/\s+/g, " ").trim(), act: function () { pressAct(b, from); } };
    if (b.disabled) { it.disabled = true; it.reason = b.getAttribute("title") || ""; }
    return it;
  }
  /* a trigger pressed for a tile (or the heading): its own click, or where it goes */
  function pressAct(b, from) {
    tilePending = { tile: from || null, at: Date.now() };
    var go = b.getAttribute("data-go"), node = b.getAttribute("data-go-node");
    if (go) { tilePending = null; rowGo(go, false); return; }
    if (node) {
      /* another card's values (the parent a tile follows, a tier): that
         card's own window, in place, the focus back to the tile; with none,
         its card is chosen */
      var to = doc.querySelector('[data-hier-card="' + node + '"]'), key = to ? to.getAttribute("data-tile-open") : "";
      var own = key ? ownActs(to).filter(function (x) { return x.getAttribute("data-act") === key; })[0] : null;
      if (actOffered(own)) { tilePending = { tile: from || null, at: Date.now() }; own.click(); return; }
      tilePending = null;
      var h = b.closest(".pfas-hier"), n = h ? h.querySelector('[data-hier-target="' + node + '"]') : null;
      if (h) { hierSelect(h, node, true); }
      if (n && n.focus) { n.focus(); }
      return;
    }
    b.click();
  }
  function tileLabel(tile) {
    var l = tile.querySelector(".pfas-hier-tile-l");
    return String((l ? l.textContent : tile.getAttribute("aria-label")) || "").replace(/\s+/g, " ").trim();
  }
  /* a tile with nowhere to edit it: a window that reads it */
  function readTile(tile) {
    var body = el("div", "pfas-tile-read"), v = tile.querySelector(".pfas-hier-tile-v"), s = tile.querySelector(".pfas-hier-tile-s");
    body.appendChild(el("p", "pfas-tile-read-v", String((v || tile).textContent || "").replace(/\s+/g, " ").trim()));
    if (s && s.textContent.trim()) { body.appendChild(el("p", "pfas-tile-read-s", s.textContent.trim())); }
    drawer.open(tileLabel(tile), body, { cls: "is-dialog", opener: tile });
  }
  function openTile(tile) {
    var spec = tileSpec(tile);
    if (!spec) { return false; }
    if (spec.read) { readTile(tile); return true; }
    var b = actOf(tile, spec.open);
    if (!actOffered(b)) { return false; }
    pressAct(b, tile);
    return true;
  }
  /* the tile's menu as groups: its actions, then the ones that remove or reset (danger) */
  function tileItems(tile, keys) {
    var acts = [], last = [];
    keys.forEach(function (k) {
      var b = actOf(tile, k);
      if (!b || b.hidden) { return; }
      (b.hasAttribute("data-danger") ? last : acts).push(actItem(b, tile));
    });
    return [acts, last];
  }
  /* a card heading's menu: every action the card offers, its button row's too */
  function headItems(card) {
    var acts = [], last = [];
    ownActs(card).forEach(function (b) {
      if (b.hidden) { return; }
      (b.hasAttribute("data-danger") ? last : acts).push(actItem(b, card.querySelector(".pfas-hier-card-t")));
    });
    for (var i = 0; i < card.children.length; i++) {
      if (!card.children[i].classList.contains("pfas-hier-actions")) { continue; }
      Array.prototype.forEach.call(card.children[i].querySelectorAll("button, a[href]"), function (n) {
        if (!n.hidden && said(n)) { acts.push(pressItem(clipped(said(n), 40), n)); }
      });
    }
    return [acts, last];
  }
  function tileFor(t) {
    var tile = t && t.closest ? t.closest(TILE) : null;
    return tile && tileSpec(tile) ? tile : null;
  }
  /* the window just opened for a tile: the field it reads focused, the focus back to the tile on close */
  function tileNames(tile) {
    var out = [];
    Array.prototype.forEach.call(tile.attributes || [], function (a) {
      if (!/^data-.*names?$/.test(a.name) || !a.value) { return; }
      var v = a.value;
      if (/^[\[{]/.test(v)) {
        try { var j = JSON.parse(v); (Array.isArray(j) ? j : Object.keys(j).map(function (k) { return j[k]; })).forEach(function (x) { out = out.concat(x); }); } catch (e) { /* not a list */ }
      } else { out.push(v); }
    });
    return out.filter(function (x) { return typeof x === "string" && x; });
  }
  function tileFocus(body, tile) {
    var names = tileNames(tile), label = tileLabel(tile).toLowerCase(), hit = null;
    var marked = body.querySelectorAll("[data-for-name]");
    for (var i = 0; i < marked.length && !hit; i++) { if (names.indexOf(marked[i].getAttribute("data-for-name")) >= 0) { hit = marked[i]; } }
    if (!hit && label) {
      var labels = body.querySelectorAll(".pfas-sheet-flabel, .pfas-pop-l, label");
      for (var j = 0; j < labels.length && !hit; j++) {
        var w = String(labels[j].textContent || "").replace(/\s+/g, " ").trim().toLowerCase();
        if (!w || !(w === label || label.indexOf(w) === 0 || w.indexOf(label) === 0)) { continue; }
        var box = labels[j].tagName === "LABEL" ? labels[j] : labels[j].parentNode;
        /* a field first, never a stepper's button beside it */
        hit = box.querySelector("input:not([type=hidden]):not([type=range]), select, textarea") || box.querySelector("button");
      }
    }
    if (hit && hit.focus) { hit.focus(); }
  }
  /* only a window a trigger opened (its opener the trigger, or none) is the tile's */
  function tileOpened(d, opener) {
    var p = tilePending;
    tilePending = null;
    if (!p || !p.tile || Date.now() - p.at > 1500) { return; }
    if (opener && !(opener.closest && opener.closest(".pfas-hier-acts"))) { return; }
    drawer.opener = p.tile;
    tileFocus(d.querySelector(".pfas-drawer-body"), p.tile);
  }
  function initTiles(root) {
    var all = (root || doc).querySelectorAll(TILE);
    for (var i = 0; i < all.length; i++) {
      var t = all[i];
      if (!tileSpec(t)) { continue; }
      if (!t.hasAttribute("tabindex")) { t.setAttribute("tabindex", "0"); }
      t.classList.add("is-opens");
    }
    if (doc.__pfasTiles) { return; }
    doc.__pfasTiles = true;
    doc.addEventListener("click", function (e) {
      var t = e.target, tile = tileFor(t);
      if (!tile || e.defaultPrevented || e.button) { return; }
      var skip = t.closest(TILE_SKIP);
      if (skip && tile.contains(skip) && skip !== tile) { return; }
      var sel = window.getSelection ? window.getSelection() : null;
      if (sel && !sel.isCollapsed && String(sel).trim() && sel.anchorNode && tile.contains(sel.anchorNode)) { return; }
      if (Date.now() - rowPressedAt < 800) { return; }   /* the long press's lift */
      openTile(tile);
    });
    doc.addEventListener("keydown", function (e) {
      var tile = e.target;
      if (!tile || !tile.matches || !tile.matches(TILE) || !tileSpec(tile)) { return; }
      if (e.key === "ContextMenu" || (e.shiftKey && e.key === "F10")) {
        var items = contextItems(tile);
        if (items.length) { e.preventDefault(); openMenu(items, { anchor: tile, opener: tile }); }
        return;
      }
      if (e.key === "Enter") { e.preventDefault(); openTile(tile); }
    });
  }
  /* more groups for every right-click menu: fn(target) returns a list of
     groups (each a list of entries) or nothing; first: above what the
     target offers itself (a limit box's states), else after it */
  var menuSources = [];
  menu.source = function (fn, opts) { menuSources.push({ fn: fn, first: !!(opts && opts.first) }); };
  /* a limit box's State group, above what the box offers itself: the menu
     changes that box alone */
  menu.source(function (target) {
    var box = target && target.closest ? target.closest("[data-limit-box]") : null;
    /* headed by the box's own name, else the word State */
    return box ? [[{ head: box.getAttribute("data-limit-label") || "State" }].concat(limitItems(box))] : null;
  }, { first: true });
  function sourceGroups(target, first) {
    var out = [];
    menuSources.forEach(function (s) {
      if (s.first !== first) { return; }
      var gs = null;
      try { gs = s.fn(target); } catch (e) { gs = null; }
      (gs || []).forEach(function (g) { if (g && g.length) { out.push(g); } });
    });
    return out;
  }

  function initContextMenu() {
    if (doc.__pfasContext) { return; }
    doc.__pfasContext = true;
    doc.addEventListener("contextmenu", function (e) {
      var t = e.target && e.target.closest ? e.target : null;
      /* inside the open menu (where the menu key's own event lands once the
         keydown has opened it): nothing more, not the browser's menu over it */
      if (t && t.closest(".pfas-menu")) { e.preventDefault(); return; }
      if (!t || e.defaultPrevented || e.shiftKey || t.closest(TEXT_BOX)) { return; }
      /* a touch screen's own long press after the row's: the row's menu is open */
      if (Date.now() - rowPressedAt < 800) { e.preventDefault(); return; }
      var sel = window.getSelection ? window.getSelection() : null;
      if (sel && !sel.isCollapsed && String(sel).trim()) { return; }
      var items = contextItems(t);
      if (!items.length) { return; }
      e.preventDefault();
      /* the menu key and Shift+F10 come with no pointer: the menu opens under the focused node */
      var keyed = !e.clientX && !e.clientY;
      openMenu(items, keyed ? { anchor: t, opener: t } : { x: e.clientX, y: e.clientY, opener: menuOpener(t) });
    });
  }
  /* where the focus goes back when a right click's menu closes: the
     nearest node that takes it (the box, tile or row clicked inside), never
     the word or glyph the pointer was on */
  var FOCUSABLE = "[data-limit-box], [tabindex]:not([tabindex='-1']), a[href], button, input, select, textarea, summary";
  function menuOpener(t) {
    var tile = tileFor(t);
    var n = t.closest(FOCUSABLE) || tile || t.closest(NODE_ROW) || t.closest(ROW);
    return n || t;
  }

  /* ── Hierarchy (.pfas-hier): a list of parent nodes beside the chosen
     node's card. A node (.pfas-hier-node[data-hier-target], a button) shows
     the card whose data-hier-card it names and hides the others (hidden,
     never removed); the choice is remembered per list for the visit
     (sessionStorage "pfas.hier.<data-hier>"), so a list drawn again keeps
     it; Up / Down (Home / End) move between the nodes. A card with no
     node of its own names its parent's (data-hier-parent): choosing it
     shows that card with the parent's node chosen. A node that heads a
     nest (aria-controls naming a .pfas-hier-nest under it, a group's
     rules) opens it on a click and closes it on the next, aria-expanded
     saying which; choosing a node inside a closed nest opens it, and
     Up / Down pass over the nodes of a closed one. A band
     (.pfas-band[data-hi]) draws a range: its bar's ends are --lo / --hi,
     fractions of its scale (data-scale, else 0 to 200 %). A view switch ([data-view-switch="k"], a
     segment) shows the blocks [data-view-of="k"] whose data-view is the
     choice and hides the others, never disabling a field in them, and
     remembers it (localStorage, its data-view-store). A field the browser
     refuses while a view or a card hides it shows that view and card
     first, so the refusal is seen. */
  function hierStore(kind) {
    try { return window[kind] || null; } catch (e) { return null; }
  }
  function hierGet(kind, key) {
    try { var s = hierStore(kind); return s ? s.getItem(key) : null; } catch (e) { return null; }
  }
  function hierSet(kind, key, v) {
    try { var s = hierStore(kind); if (s) { s.setItem(key, v); } } catch (e) { /* storage refused: only forgets */ }
  }
  /* an axis from `min` (data-min, else 0) to `scale`; one that starts below
     zero marks its zero (--zero) */
  function band(el, lo, hi, scale, min) {
    var base = isFinite(min) ? min : 0;
    var top = isFinite(scale) && scale > base ? scale : (base < 0 ? 0 : 200);
    var a = isFinite(lo) ? lo : base, b = isFinite(hi) ? hi : a;
    if (b < a) { var t = a; a = b; b = t; }
    function frac(v) { return Math.max(0, Math.min(1, (v - base) / (top - base))); }
    el.style.setProperty("--lo", String(frac(a)));
    el.style.setProperty("--hi", String(frac(b)));
    if (base < 0 && top > 0) { el.style.setProperty("--zero", String(frac(0))); }
  }
  function bandOf(n) {
    band(n, parseFloat(n.getAttribute("data-lo")), parseFloat(n.getAttribute("data-hi")),
         parseFloat(n.getAttribute("data-scale")), parseFloat(n.getAttribute("data-min")));
  }
  function initBands(root) {
    var all = root.querySelectorAll(".pfas-band[data-hi]");
    for (var i = 0; i < all.length; i++) { bandOf(all[i]); }
  }
  function hierNodes(hier) {
    return Array.prototype.slice.call(hier.querySelectorAll(".pfas-hier-node[data-hier-target]"));
  }
  /* the node that shows `key`'s card: its own, else its parent's */
  function hierOwner(hier, key) {
    var nodes = hierNodes(hier);
    var own = nodes.filter(function (n) { return n.getAttribute("data-hier-target") === key; })[0];
    if (own) { return key; }
    var card = Array.prototype.filter.call(hier.querySelectorAll("[data-hier-card]"), function (c) {
      return c.getAttribute("data-hier-card") === key;
    })[0];
    var parent = card ? card.getAttribute("data-hier-parent") : null;
    return parent && nodes.some(function (n) { return n.getAttribute("data-hier-target") === parent; }) ? parent : null;
  }
  /* a group node's nest: the container its aria-controls names, in its list */
  function nestOf(hier, n) {
    var id = n.getAttribute("aria-controls"), nest = id ? doc.getElementById(id) : null;
    return nest && nest.classList.contains("pfas-hier-nest") && hier.contains(nest) ? nest : null;
  }
  function setNest(hier, nest, open) {
    nest.hidden = !open;
    hierNodes(hier).forEach(function (n) {
      if (n.getAttribute("aria-controls") === nest.id) { n.setAttribute("aria-expanded", open ? "true" : "false"); }
    });
  }
  /* a node shown: not drawn hidden, nor inside a closed nest */
  function nodeShown(n) {
    for (var e = n; e && e.nodeType === 1; e = e.parentNode) {
      if (e.hidden) { return false; }
      if (e.classList && e.classList.contains("pfas-hier")) { return true; }
    }
    return true;
  }
  /* the card that gives way to the next steps out (opacity, 6 px, quick):
     a copy of it with nothing a script finds or a form posts (no id, name,
     form or data-*), inert, dropped once it has faded; with reduced motion,
     none */
  function cardLeaves(card) {
    var mm = window.matchMedia;
    if (!mm || mm("(prefers-reduced-motion: reduce)").matches || !card.parentNode || !card.cloneNode) { return; }
    var ghost = card.cloneNode(true);
    [ghost].concat(Array.prototype.slice.call(ghost.querySelectorAll("*"))).forEach(function (n) {
      Array.prototype.slice.call(n.attributes || []).forEach(function (a) {
        if (a.name === "id" || a.name === "name" || a.name === "form" || a.name.indexOf("data-") === 0) { n.removeAttribute(a.name); }
      });
    });
    ghost.hidden = false;
    ghost.setAttribute("aria-hidden", "true");
    ghost.setAttribute("inert", "");
    ghost.classList.add("is-leaving");
    card.parentNode.insertBefore(ghost, card.parentNode.firstChild);
    function drop() { if (ghost.parentNode) { ghost.parentNode.removeChild(ghost); } }
    ghost.addEventListener("animationend", drop);
    setTimeout(drop, 400);
  }
  function hierSelect(hier, key, remember) {
    var nodes = hierNodes(hier), found = null, owner = hierOwner(hier, key);
    if (!owner) { return null; }
    nodes.forEach(function (n) {
      var on = n.getAttribute("data-hier-target") === owner;
      n.classList.toggle("is-selected", on);
      n.setAttribute("aria-pressed", on ? "true" : "false");
      if (on) { found = n; }
    });
    if (!found) { return null; }
    /* the nest the chosen node sits in is opened, so it is seen */
    for (var e = found.parentNode; e && e !== hier && e.nodeType === 1; e = e.parentNode) {
      if (e.classList.contains("pfas-hier-nest") && e.hidden) { setNest(hier, e, true); }
    }
    var cards = hier.querySelectorAll("[data-hier-card]");
    for (var i = 0; i < cards.length; i++) {
      var was = !cards[i].hidden;
      cards[i].hidden = cards[i].getAttribute("data-hier-card") !== key;
      if (was && cards[i].hidden) { cardLeaves(cards[i]); }
    }
    if (remember && hier.getAttribute("data-hier")) { hierSet("sessionStorage", "pfas.hier." + hier.getAttribute("data-hier"), key); }
    initTiles(hier);   /* a card drawn again since: its tiles Tab stops too */
    return found;
  }
  function initHier(hier) {
    if (hier.__pfas) { return; }
    hier.__pfas = true;
    var nodes = hierNodes(hier);
    if (!nodes.length) { return; }
    var want = hier.getAttribute("data-hier") ? hierGet("sessionStorage", "pfas.hier." + hier.getAttribute("data-hier")) : null;
    var drawn = hier.querySelector('.pfas-hier-node[aria-pressed="true"]');
    /* a remembered node now drawn hidden is not chosen again (one in a
       closed nest is: choosing it opens the nest) */
    if (want && !nodes.some(function (n) { return n.getAttribute("data-hier-target") === hierOwner(hier, want) && !n.hidden; })) { want = null; }
    if (!(want && hierSelect(hier, want, false))) {
      hierSelect(hier, (drawn || nodes[0]).getAttribute("data-hier-target"), false);
    }
    hier.addEventListener("click", function (e) {
      /* the touch screen's dots after a node: the node's row menu */
      var dots = e.target.closest ? e.target.closest(".pfas-hier-dots") : null;
      if (dots && dots.closest(".pfas-hier") === hier) {
        var owner = dots.previousElementSibling;
        while (owner && !owner.matches(NODE_ROW)) { owner = owner.previousElementSibling; }
        if (!owner) { return; }
        if (menuState && menuState.opener === dots) { closeMenu(true); return; }
        openMenu(contextItems(owner), { anchor: dots, opener: dots });
        return;
      }
      /* a count in a card's table opens its list, as a grid's links cell */
      var a = e.target.closest ? e.target.closest(".pfas-hier-table .pfas-sheet-links") : null;
      if (a && a.closest(".pfas-hier") === hier) { e.preventDefault(); openSheetPop(a, a.nextElementSibling); return; }
      var n = e.target.closest ? e.target.closest(".pfas-hier-node[data-hier-target]") : null;
      if (n && n.closest(".pfas-hier") === hier) {
        /* a group's node: one click opens its nest, the next closes it */
        var nest = nestOf(hier, n), open = nest ? nest.hidden : false;
        hierSelect(hier, n.getAttribute("data-hier-target"), true);
        if (nest) { setNest(hier, nest, open); }
      }
    });
    hier.addEventListener("keydown", function (e) {
      /* the menu key or Shift+F10 on a node with a row menu: its menu, under
         the node (the page's contextmenu leaves Shift to the browser) */
      if ((e.key === "ContextMenu" || (e.shiftKey && e.key === "F10")) && e.target.matches &&
          e.target.matches(NODE_ROW) && e.target.closest(".pfas-hier") === hier) {
        var items = contextItems(e.target);
        if (items.length) { e.preventDefault(); openMenu(items, { anchor: e.target, opener: e.target }); }
        return;
      }
      var keys = { ArrowUp: -1, ArrowDown: 1, Home: "first", End: "last" };
      if (!(e.key in keys)) { return; }
      /* a node drawn hidden (a compound that sets nothing of its own) is passed over */
      var list = hierNodes(hier).filter(nodeShown), i = list.indexOf(doc.activeElement);
      if (i < 0) { return; }
      var k = keys[e.key];
      var next = list[k === "first" ? 0 : (k === "last" ? list.length - 1 : Math.max(0, Math.min(list.length - 1, i + k)))];
      next.focus();
      hierSelect(hier, next.getAttribute("data-hier-target"), true);
      e.preventDefault();
    });
  }
  /* the segment's chosen item, after its own click or key has moved it */
  function segValue(seg) {
    var on = seg.querySelector('.pfas-seg-item[aria-pressed="true"], .pfas-seg-item[aria-selected="true"]');
    return on ? on.getAttribute("data-value") : null;
  }
  function segPress(seg, value) {
    var items = seg.querySelectorAll(".pfas-seg-item");
    for (var i = 0; i < items.length; i++) {
      if (items[i].getAttribute("data-value") === value) { press(seg, items[i]); placePill(seg); return true; }
    }
    return false;
  }
  function onSegChoice(seg, fn) {
    seg.addEventListener("click", function (e) {
      if (e.target.closest && e.target.closest(".pfas-seg-item")) { fn(segValue(seg)); }
    });
    seg.addEventListener("keydown", function (e) {
      if (e.key === "ArrowLeft" || e.key === "ArrowRight") { fn(segValue(seg)); }
    });
  }
  function showView(name, value, remember) {
    var blocks = doc.querySelectorAll("[data-view-of]"), any = false;
    for (var i = 0; i < blocks.length; i++) {
      if (blocks[i].getAttribute("data-view-of") !== name) { continue; }
      var was = blocks[i].hidden;
      blocks[i].hidden = blocks[i].getAttribute("data-view") !== value;
      /* a view chosen rises in as a card does; a view of cards has its
         cards rise already */
      if (remember && was && !blocks[i].hidden && !blocks[i].querySelector(".pfas-hier-card")) { arrive(blocks[i], "is-arriving"); }
      any = any || !blocks[i].hidden;
    }
    var segs = doc.querySelectorAll("[data-view-switch]");
    for (var j = 0; j < segs.length; j++) {
      if (segs[j].getAttribute("data-view-switch") !== name) { continue; }
      if (segValue(segs[j]) !== value) { segPress(segs[j], value); }
      if (remember && segs[j].getAttribute("data-view-store")) { hierSet("localStorage", segs[j].getAttribute("data-view-store"), value); }
    }
    return any;
  }
  function initViewSwitch(seg) {
    if (seg.__pfasView) { return; }
    seg.__pfasView = true;
    var name = seg.getAttribute("data-view-switch"), key = seg.getAttribute("data-view-store");
    var kept = key ? hierGet("localStorage", key) : null;
    if (!(kept && seg.querySelector('.pfas-seg-item[data-value="' + kept + '"]') && showView(name, kept, false))) {
      showView(name, segValue(seg), false);
    }
    onSegChoice(seg, function (v) { if (v) { showView(name, v, true); } });
  }
  function revealHidden(e) {
    for (var n = e.target; n && n.nodeType === 1; n = n.parentNode) {
      if (n.hidden && n.hasAttribute("data-view-of")) { showView(n.getAttribute("data-view-of"), n.getAttribute("data-view"), false); }
      if (n.hidden && n.hasAttribute("data-hier-card")) {
        var h = n.parentNode && n.parentNode.closest ? n.parentNode.closest(".pfas-hier") : null;
        if (h) { hierSelect(h, n.getAttribute("data-hier-card"), false); }
      }
    }
  }
  function initHierAll(root) {
    var hs = root.querySelectorAll(".pfas-hier"); for (var i = 0; i < hs.length; i++) { initHier(hs[i]); }
    initBands(root);
    var vs = root.querySelectorAll("[data-view-switch]"); for (var v = 0; v < vs.length; v++) { initViewSwitch(vs[v]); }
    if (!doc.__pfasReveal) {
      doc.__pfasReveal = true;
      doc.addEventListener("invalid", revealHidden, true);
    }
  }

  /* The pinned bar's Save line (pfas_macros save-bar): a field of the form it
     names, inside it or joined to it by form=, changed since the page was
     drawn. One listener for the page; a submit ends the page. */
  var unsavedWatched = false;
  function initUnsaved() {
    if (unsavedWatched) { return; }
    unsavedWatched = true;
    function changed(e) {
      var form = e.target && e.target.form;
      if (!form || !form.id) { return; }
      var notes = doc.querySelectorAll("[data-unsaved-for]");
      for (var i = 0; i < notes.length; i++) {
        if (notes[i].getAttribute("data-unsaved-for") === form.id && !notes[i].classList.contains("is-dirty")) {
          notes[i].classList.add("is-dirty");
          notes[i].textContent = "Unsaved changes";
        }
      }
    }
    doc.addEventListener("input", changed);
    doc.addEventListener("change", changed);
  }

  function init(root) {
    root = root || doc;
    initUnsaved();
    var multis = root.querySelectorAll(".pfas-multi"); for (var mi = 0; mi < multis.length; mi++) { initMulti(multis[mi]); }
    var pickers = root.querySelectorAll(".pfas-picker"); for (var pi = 0; pi < pickers.length; pi++) { initPicker(pickers[pi]); }
    var plists = root.querySelectorAll(".pfas-picker-lists"); for (var pl = 0; pl < plists.length; pl++) { initPickerLists(plists[pl]); }
    wrapTables(root === doc ? null : root);
    enhance(root);
    initTables(root);
    initHScroll();
    watchTables();
    watchListings();
    watchMotion();
    initModals(root);
    initRows(root);
    initSheets(root);
    initHelp();
    initContextMenu();
    initRowLinks(root);
    initTiles(root);
    initGlyphs(root);
    initTips();
    alertMarks(root);
    var segs = root.querySelectorAll(".pfas-seg"); for (var i = 0; i < segs.length; i++) { initSeg(segs[i]); }
    var secs = root.querySelectorAll("details.pfas-sec"); for (var si = 0; si < secs.length; si++) { initSection(secs[si]); }
    var fabs = root.querySelectorAll(".pfas-fab"); for (var f = 0; f < fabs.length; f++) { initFab(fabs[f]); }
    var trees = root.querySelectorAll(".pfas-tree"); for (var t = 0; t < trees.length; t++) { initTree(trees[t]); }
    initHierAll(root);
    initNavTiles(root);
    var forms = root.querySelectorAll("form[data-autosubmit]");   /* a filter bar: applies on change */
    for (var a = 0; a < forms.length; a++) {
      (function (form) {
        if (form.__pfas) { return; }
        form.__pfas = true;
        form.addEventListener("change", function () { form.submit(); });
      })(forms[a]);
    }
    var switches = root.querySelectorAll("[data-theme-switch]");
    for (var s = 0; s < switches.length; s++) {
      (function (el) {
        if (el.__pfas) { return; }
        el.__pfas = true;
        el.checked = theme() === "dark";
        el.addEventListener("change", function () { theme(el.checked ? "dark" : "light"); });
      })(switches[s]);
    }
  }
  /* a section (details.pfas-sec) opened by its summary: the segments it
     held closed were measured at no width, so their markers are placed again
     (toggle does not bubble: one listener per section) */
  function initSection(d) {
    if (d.__pfas) { return; }
    d.__pfas = true;
    d.addEventListener("toggle", function () { if (d.open) { placeAll(d); } });
  }
  if (doc.readyState === "loading") { doc.addEventListener("DOMContentLoaded", function () { init(); }); } else { init(); }
  function placeAll(root) {
    var segs = (root || doc).querySelectorAll(".pfas-seg"); for (var i = 0; i < segs.length; i++) { placePill(segs[i]); initStripCue(segs[i]); stripCue(segs[i]); }
  }
  window.addEventListener("resize", function () { placeAll(); });
  watchGlyphs();
  /* the tabs change width once the web font is in: place each marker again */
  window.PFAS.numeric.whenSettled(window, doc, function () { placeAll(); });
  /* one icon per group of sample types (sample_type_icons.py): the page
     macro writes the drawings once as JSON (#pfas-type-icons), so a row this
     script builds draws the same icon a template does. A code no group holds
     draws nothing. */
  var typeSpecCache = null;
  function typeSpec() {
    if (typeSpecCache) { return typeSpecCache; }
    var el = document.getElementById("pfas-type-icons");
    if (!el) { return null; }
    try { typeSpecCache = JSON.parse(el.textContent || "{}"); } catch (e) { return null; }
    return typeSpecCache;
  }
  function typeGroup(code) {
    var spec = typeSpec(), text = String(code == null ? "" : code).trim(), key;
    if (!spec || !text) { return null; }
    if (spec.words[text]) { return text; }
    key = text.toUpperCase();
    if (!spec.codes[key]) { key = key.replace(/-/g, " ").split(/\s+/)[0]; }
    return spec.codes[key] || null;
  }
  function typeLabel(code, sub) {
    var spec = typeSpec(), g = typeGroup(code), text = String(code == null ? "" : code).trim();
    if (!g) { return text; }
    if (g === "not_judged") { return spec.words[g]; }
    sub = sub != null ? String(sub) : (spec.words[text] ? "" : text);
    return sub ? spec.words[g] + ": " + sub : spec.words[g];
  }
  function typeIcon(code, sub, na, hidden) {
    var spec = typeSpec(), g = typeGroup(code), name;
    if (!g) { return ""; }
    name = na ? spec.words[g] + ": " + spec.na : typeLabel(code, sub);
    return '<svg class="pfas-type is-' + g.replace("_", "-") + (na ? " is-na" : "") + '" viewBox="0 0 24 24" focusable="false" ' +
           (hidden ? 'aria-hidden="true"' : 'role="img" aria-label="' + esc(name) + '"') +
           '><title>' + esc(name) + '</title>' + spec.drawings[g] + '</svg>';
  }
  function typeCell(code, words) {
    words = words == null ? String(code == null ? "" : code) : String(words);
    var icon = typeIcon(code, words, false, true);
    return icon ? '<span class="pfas-type-cell">' + icon + '<span>' + esc(words) + '</span></span>' : esc(words);
  }
  /* every other icon (icons.py): the page macro writes the drawings once as
     JSON (#pfas-icons), so an icon this script draws is the one a template
     draws. A name the set does not hold draws nothing. */
  var iconSpecCache = null;
  function iconSpec() {
    if (iconSpecCache) { return iconSpecCache; }
    var el = doc.getElementById("pfas-icons");
    if (!el) { return null; }
    try { iconSpecCache = JSON.parse(el.textContent || "{}"); } catch (e) { return null; }
    return iconSpecCache;
  }
  /* opts: label (the words, else the drawing's own), state (done, now,
     next), mark (warn, fail, wait, back), size (md, lg, xl), hidden, colour */
  function icon(name, opts) {
    var spec = iconSpec(), o = opts || {}, cls, tone, words;
    name = String(name == null ? "" : name);
    if (name.indexOf("type:") === 0) { return typeIcon(name.slice(5), o.label, false, o.hidden); }
    if (!spec || !spec.drawings[name]) { return ""; }
    words = o.label ? String(o.label) : (spec.words[name] || name);
    tone = o.colour || spec.colour[name];
    if (o.state === "next") { tone = "neutral"; }
    cls = "pfas-icon is-" + name + (tone ? " is-" + tone : "") + (o.state ? " is-" + o.state : "") +
          (o.size && o.size !== "sm" ? " is-" + o.size : "");
    return '<svg class="' + cls + '" viewBox="0 0 24 24" focusable="false" ' +
           (o.hidden ? 'aria-hidden="true">' : 'role="img" aria-label="' + esc(words) + '"><title>' + esc(words) + '</title>') +
           spec.drawings[name] + (o.mark && spec.marks[o.mark] ? spec.marks[o.mark] : "") + '</svg>';
  }
  function tipIcon(name, label, opts) {
    var o = {}, k, svg;
    for (k in (opts || {})) { if (Object.prototype.hasOwnProperty.call(opts, k)) { o[k] = opts[k]; } }
    o.label = label; o.hidden = true;
    svg = icon(name, o);
    if (!svg) { return esc(label); }
    return '<span class="pfas-tip" tabindex="0" role="img" aria-label="' + esc(label) + '" data-pfas-tip="' + esc(label) + '">' + svg + '</span>';
  }
  /* the tooltip: an icon's words on pointer hover, keyboard focus and a long
     press; it stays while the pointer is over it and closes on Escape */
  var tipEl = null, tipFor = null, tipPress = null;
  function tipShow(target) {
    var words = target.getAttribute("data-pfas-tip"), r, top;
    if (!words) { return; }
    if (!tipEl) {
      tipEl = doc.createElement("div");
      tipEl.className = "pfas-tooltip"; tipEl.setAttribute("role", "tooltip"); tipEl.id = "pfas-tooltip";
      tipEl.addEventListener("mouseleave", function () { tipHide(); });
      doc.body.appendChild(tipEl);
    }
    tipEl.textContent = words; tipEl.hidden = false; tipFor = target;
    r = target.getBoundingClientRect ? target.getBoundingClientRect() : { left: 0, top: 0, bottom: 0, width: 0 };
    top = r.top - (tipEl.offsetHeight || 24) - 6;
    tipEl.style.left = Math.max(4, r.left) + "px";
    tipEl.style.top = (top < 4 ? r.bottom + 6 : top) + "px";
  }
  function tipHide() {
    if (tipEl) { tipEl.hidden = true; }
    tipFor = null;
  }
  function tipTarget(e) {
    var n = e.target;
    while (n && n.nodeType === 1) { if (n.hasAttribute && n.hasAttribute("data-pfas-tip")) { return n; } n = n.parentNode; }
    return null;
  }
  function initTips() {
    if (doc.__pfasTips) { return; }
    doc.__pfasTips = true;
    doc.addEventListener("mouseover", function (e) { var t = tipTarget(e); if (t) { tipShow(t); } });
    doc.addEventListener("mouseout", function (e) {
      var t = tipTarget(e), to = e.relatedTarget;
      if (t && t === tipFor && !(to && tipEl && (to === tipEl || tipEl.contains(to))) && !(to && t.contains(to))) { tipHide(); }
    });
    doc.addEventListener("focusin", function (e) { var t = tipTarget(e); if (t) { tipShow(t); } });
    doc.addEventListener("focusout", function (e) { if (tipTarget(e) === tipFor) { tipHide(); } });
    doc.addEventListener("keydown", function (e) { if ((e.key === "Escape" || e.key === "Esc") && tipFor) { tipHide(); } });
    doc.addEventListener("touchstart", function (e) {
      var t = tipTarget(e);
      if (tipPress) { clearTimeout(tipPress); tipPress = null; }
      if (!t) { if (tipFor) { tipHide(); } return; }
      tipPress = setTimeout(function () { tipPress = null; tipShow(t); }, 450);
    }, { passive: true });
    doc.addEventListener("touchend", function () { if (tipPress) { clearTimeout(tipPress); tipPress = null; } }, { passive: true });
  }
  /* a list of notices (.bench-alerts): each says its kind by a mark at its
     start, a failure's diamond or a warning's triangle, not by the colour of
     its edge alone. A notice a template already marks is left as it is. */
  function hasMark(li) {
    for (var c = li.firstChild; c; c = c.nextSibling) {
      if (c.nodeType === 1 && /(^|\s)pfas-(alert-mark|icon)(\s|$)/.test(c.getAttribute("class") || "")) { return true; }
    }
    return false;
  }
  function alertMarks(root) {
    var items = (root || doc).querySelectorAll(".bench-alerts > li.bench-bad, .bench-alerts > li.bench-warn"), i, li, kind, svg, span;
    for (i = 0; i < items.length; i++) {
      li = items[i];
      if (hasMark(li)) { continue; }
      kind = li.className.indexOf("bench-bad") >= 0 ? "fail" : "warn";
      svg = icon(kind, { size: "md" });
      if (!svg) { continue; }
      span = doc.createElement("span");
      span.className = "pfas-alert-mark";
      span.innerHTML = svg;
      li.insertBefore(span, li.firstChild);
    }
  }
  window.PFAS = window.PFAS || {};
  /* range, picker, num: one control drawn where init() does not reach (a drawer, outside the content area) */
  window.PFAS.components = { muteIf: applyMuteIf, esc: esc, labToday: labToday, labelListSearch: labelListSearch, stripCue: stripCue, init: init, enhance: enhance, theme: theme, drawer: drawer, placePill: placePill, seg: initSeg, wrapTables: wrapTables, sheet: sheet,
                             range: initRange, picker: initPicker, num: makeNum, fields: houseFields, initNavTiles: initNavTiles, resetNavTiles: resetNavTiles,
                             tables: initTables, initColResize: initColResize, initScrollCue: initScrollCue, switchWord: switchWord,
                             hscroll: { init: initHScroll, railBox: railBox, autoSpeed: autoSpeed, scroller: scroller,
                                        place: function () { if (hplace) { hplace(); } }, rail: function () { return hrail; } },
                             inheritMark: inheritMark, help: { open: openHelp, close: closeHelp }, menu: menu,
                             limit: { items: limitItems, set: setLimit, line: stateLine, glyphs: drawGlyphs, groups: groupStates,
                                      svg: { set: LIMIT_SVG, "default": LIMIT_SVG_DEFAULT } },
                             motion: { leave: leave, stay: stay, arrive: arrive, settleList: settleList, nameTabs: nameTabs, unnameTabs: unnameTabs,
                                       ring: ring, hint: hint, stillGif: stillGif, noticed: noticed },
                             icon: { svg: icon, tip: tipIcon, alerts: alertMarks, tips: initTips, hide: tipHide, states: stateCells, coreImages: coreImages,
                                     reset: function () { iconSpecCache = null; } },
                             type: { icon: typeIcon, cell: typeCell, group: typeGroup, label: typeLabel, reset: function () { typeSpecCache = null; } },
                             context: { items: contextItems, init: initContextMenu },
                             rows: { init: initRowLinks, items: rowItems },
                             tiles: { init: initTiles, open: openTile, spec: tileSpec, act: actOf, press: pressAct },
                             hier: { init: initHierAll, band: band, drawBand: bandOf, select: hierSelect, view: showView },
                             equation: { init: initEquations, draw: drawEquations, open: openEquation } };
})();
