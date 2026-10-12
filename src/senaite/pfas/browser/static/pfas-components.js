/* pfas-components.js — behaviour for the shared components (pfas-components.css).
 * Loaded by the page macro and the core overlay viewlet. Plain ES5, no library.
 *   - theme: html[data-theme] from localStorage ("pfas_theme"); light unless the
 *     person chose dark (light is the lab's default)
 *   - .pfas-seg: (data-quiet: no pfas:seg event) the pill follows the active item; click switches items and
 *     panes ([data-tabs] root, data-pane ids); arrow keys move between tabs
 *   - .pfas-fab: open / close, scrim and Escape
 *   - .pfas-drawer: open(html) / close, scrim and Escape, #hash deep link hook
 *   - .pfas-tree[data-view]: "path" hides rows marked is-off-path
 *   - form[data-autosubmit]: a filter bar that submits when any field changes
 *   - .pfas-num: [-] value [+] around every number input in the content area (not
 *     read-only, .no-stepper, [data-stepper=off], or in a table cell); hold repeats
 *   - .pfas-range: [data-range] around a min / max pair of number inputs, drawn as a
 *     two-handle slider that also takes typed digits (data-scale="lo,hi", data-unit)
 *   - grid cells: a td with one number input (or a declared td[data-pair] pair) shows a
 *     value button that opens the drawer with the full stepper or range; a table opts
 *     out with data-cells="plain"
 *   - .pfas-chips: input[data-chips] ("pairs" for A=B) drawn as chips; data-options
 *     is JSON [[value, label], ...] and limits what can be added
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
  var numeric = {
    toNum: toNum, decimals: decimals, roundTo: roundTo, clamp: clamp, stepOf: stepOf, bump: bump,
    pairClamp: pairClamp, parseScale: parseScale, scaleFor: scaleFor, fraction: fraction,
    parseList: parseList, joinList: joinList, parsePairs: parsePairs, joinPairs: joinPairs
  };
  g.PFAS = g.PFAS || {};
  g.PFAS.numeric = numeric;
  if (typeof module !== "undefined" && module.exports) { module.exports = numeric; }
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
    pill.style.left = on.offsetLeft + "px";
    pill.style.width = on.offsetWidth + "px";
  }
  function activate(seg, item) {
    var items = seg.querySelectorAll(".pfas-seg-item");
    var attr = item.hasAttribute("aria-pressed") ? "aria-pressed" : "aria-selected";
    for (var i = 0; i < items.length; i++) {
      items[i].setAttribute(attr, "false");
      items[i].classList.remove("is-on");
      if (attr === "aria-selected") { items[i].setAttribute("tabindex", "-1"); }
    }
    item.setAttribute(attr, "true");
    if (attr === "aria-selected") { item.setAttribute("tabindex", "0"); }
    placePill(seg);
    var pane = item.getAttribute("data-pane");
    if (pane) {
      var root = seg.closest("[data-tabs]");
      if (!root || root === seg) { root = doc; }   /* data-tabs on the strip itself: its panes are elsewhere on the page */
      /* only this strip's own panes: a strip nested in a pane (a table's group tabs) must not close its parent's */
      var mine = {};
      for (var m = 0; m < items.length; m++) { mine[items[m].getAttribute("data-pane")] = true; }
      var panes = root.querySelectorAll(".pfas-pane");
      for (var p = 0; p < panes.length; p++) { if (mine[panes[p].id]) { panes[p].classList.toggle("is-active", panes[p].id === pane); } }
      if (seg.hasAttribute("data-hash")) { try { history.replaceState(null, "", "#" + pane); } catch (e) {} }
    }
    if (seg.hasAttribute("data-quiet")) { return; }   /* a nested strip: it does not tell the page's own listeners */
    seg.dispatchEvent(new CustomEvent("pfas:seg", { bubbles: true, detail: { item: item, value: item.getAttribute("data-value") } }));
  }
  function initSeg(seg) {
    if (seg.__pfas) { return; }
    seg.__pfas = true;
    if (!seg.querySelector(".pfas-seg-pill")) {
      var pill = doc.createElement("span"); pill.className = "pfas-seg-pill"; seg.insertBefore(pill, seg.firstChild);
    }
    /* a deep link (#pane) selects that tab on load */
    if (seg.hasAttribute("data-hash") && location.hash) {
      var want = seg.querySelector('.pfas-seg-item[data-pane="' + location.hash.slice(1) + '"]');
      if (want) { activate(seg, want); }
    }
    placePill(seg);
    seg.addEventListener("click", function (e) {
      var item = e.target.closest(".pfas-seg-item");
      if (!item || item.tagName === "A") { return; }   /* a link: the server renders the state */
      e.preventDefault();
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
      var items = Array.prototype.slice.call(seg.querySelectorAll(".pfas-seg-item"));
      var i = items.indexOf(doc.activeElement);
      if (i < 0) { return; }
      var next = items[(i + (e.key === "ArrowRight" ? 1 : items.length - 1)) % items.length];
      next.focus();
      if (next.tagName !== "A") { activate(seg, next); }
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
      drawer.el = d;
      return d;
    },
    /* content: an HTML string, or a node; opts: {footer: node, focus: node, cls: string} */
    open: function (title, content, opts) {
      var d = drawer.ensure();
      opts = opts || {};
      d.querySelector("h2").textContent = title || "";
      var body = d.querySelector(".pfas-drawer-body"), foot = d.querySelector(".pfas-drawer-foot");
      body.textContent = "";
      if (content && content.nodeType) { body.appendChild(content); } else { body.innerHTML = content || ""; }
      foot.textContent = "";
      foot.hidden = !opts.footer;
      if (opts.footer) { foot.appendChild(opts.footer); }
      d.className = "pfas-drawer" + (opts.cls ? " " + opts.cls : "");
      d.setAttribute("data-open", "true");
      (opts.focus || d.querySelector(".pfas-drawer-close")).focus();
    },
    close: function () { if (drawer.el) { drawer.el.setAttribute("data-open", "false"); } }
  };

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
      window.setTimeout(function () { pending = false; wrapTables(); enhance(); }, 50);
    }).observe(area, { childList: true, subtree: true });
  }

  /* ── Shared helpers for the input components ────────────────────────────── */
  var N = window.PFAS.numeric;
  var MINUS = "\u2212", idSeq = 0;
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
  /* The words that name an input: its aria-label, else its <label>, else its name. */
  function labelText(input) {
    var t = input.getAttribute("aria-label");
    if (!t && input.labels && input.labels.length) {
      var c = input.labels[0].cloneNode(true), junk = c.querySelectorAll(".pfas-num, .pfas-chips, .pfas-range-track, input, select, textarea, button, .hint");
      for (var i = 0; i < junk.length; i++) { if (junk[i].parentNode) { junk[i].parentNode.removeChild(junk[i]); } }
      t = c.textContent;
    }
    if (!t) { t = input.getAttribute("name") || "value"; }
    return squash(t).replace(/\s*\*$/, "");
  }

  /* ── .pfas-num: [−] value [+] around the real number input ──────────────────
     The input stays where it was, named and posted as before; the buttons only
     set its value and say so with input + change. */
  function numEligible(inp) {
    if (inp.type !== "number" || inp.readOnly || inp.disabled || inp.hidden || inp.__pfasNum) { return false; }
    if (inp.classList.contains("no-stepper") || inp.getAttribute("data-stepper") === "off") { return false; }
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
    wrap.appendChild(dec); wrap.appendChild(inp); wrap.appendChild(inc);
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
      var v = N.toNum(inp.value), lo = N.toNum(inp.getAttribute("min")), hi = N.toNum(inp.getAttribute("max"));
      dec.disabled = isFinite(v) && isFinite(lo) && v <= lo;
      inc.disabled = isFinite(v) && isFinite(hi) && v >= hi;
      var shown = inp.value || inp.getAttribute("placeholder") || "";
      inp.style.width = Math.min(16, Math.max(5, String(shown).length + 2)) + "ch";
    }
    function motion(dir) {
      inp.classList.remove("is-up", "is-down");
      void inp.offsetWidth;
      inp.classList.add(dir > 0 ? "is-up" : "is-down");
    }
    function press(dir) {
      var before = inp.value;
      inp.value = String(N.bump(before, dir, stepNow(), inp.getAttribute("min"), inp.getAttribute("max")));
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
    var a0 = N.toNum(lo.getAttribute("min")), b0 = N.toNum(hi.getAttribute("max"));
    var base = N.parseScale(w.getAttribute("data-scale")) || [isFinite(a0) ? a0 : 0, isFinite(b0) && b0 > (isFinite(a0) ? a0 : 0) ? b0 : (isFinite(a0) ? a0 : 0) + 100];
    w.classList.add("pfas-range");
    var nl = makeNum(lo), nh = makeNum(hi);
    nl.wrap.classList.add("is-lo"); nh.wrap.classList.add("is-hi");
    if (!lo.getAttribute("placeholder")) { lo.setAttribute("placeholder", "none"); }
    if (!hi.getAttribute("placeholder")) { hi.setAttribute("placeholder", "none"); }
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
      sl.setAttribute("aria-valuetext", ha ? fmt(a) : "none"); sh.setAttribute("aria-valuetext", hb ? fmt(b) : "none");
      var fa = N.fraction(ha ? a : sc[0], sc[0], sc[1]), fb = N.fraction(hb ? b : sc[1], sc[0], sc[1]);
      track.style.setProperty("--lo", String(Math.min(fa, fb))); track.style.setProperty("--hi", String(Math.max(fa, fb)));
      bl.style.setProperty("--p", String(fa)); bh.style.setProperty("--p", String(fb));
      bl.textContent = ha ? fmt(a) : "none"; bh.textContent = hb ? fmt(b) : "none";
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
      window.addEventListener("pointerup", function () { if (doc.activeElement !== s) { show(false); } });
    }
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
  function hideInput(inp) {
    inp.classList.add("pfas-sr-hide");
    inp.tabIndex = -1;
    inp.setAttribute("aria-hidden", "true");
  }
  function cellInput(td) {
    var tbl = td.closest("table");
    if (!tbl || tbl.getAttribute("data-cells") === "plain" || td.__pfasCell) { return null; }
    var ctl = td.querySelectorAll("input:not([type=hidden]), select, textarea");
    if (ctl.length !== 1) { return null; }
    var inp = ctl[0];
    if (inp.type !== "number" || inp.readOnly || inp.disabled || inp.hidden) { return null; }
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
  function headerOf(td) {
    var tbl = td.closest("table"), head = tbl && tbl.tHead && tbl.tHead.rows[tbl.tHead.rows.length - 1];
    var th = head && head.cells[td.cellIndex];
    return th ? squash(th.textContent) : "";
  }
  function rowHeading(tr) {
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
    var c = td.__pfasCell;
    var what = c.pair && td.getAttribute("data-label") ? td.getAttribute("data-label") : headerOf(td);
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
    td.__pfasCell = model;
    td.classList.add("pfas-cell");
    hideInput(inp);
    var btn = el("button", "pfas-cell-btn"); btn.type = "button"; btn.setAttribute("aria-haspopup", "dialog");
    td.appendChild(btn);
    model.btn = btn;
    function refresh() {
      var p = model.pair, text;
      btn.textContent = "";
      if (!p) {
        var v = inp.value;
        text = v === "" ? "none" : v;
        btn.appendChild(el("span", "pfas-cell-txt" + (v === "" ? " is-none" : ""), text));
      } else {
        var a = p.lo.value, b = p.hi.value;
        text = (a === "" ? "none" : a) + " \u2013 " + (b === "" ? "none" : b) + (p.unit ? " " + p.unit : "");
        btn.appendChild(el("span", "pfas-cell-txt" + (a === "" && b === "" ? " is-none" : ""), text));
        var bar = el("span", "pfas-cell-bar"), fill = el("span");
        var s = N.scaleFor(p.scale, a, b), fa = N.fraction(a === "" ? s[0] : a, s[0], s[1]), fb = N.fraction(b === "" ? s[1] : b, s[0], s[1]);
        bar.style.setProperty("--lo", String(Math.min(fa, fb))); bar.style.setProperty("--hi", String(Math.max(fa, fb)));
        if (a === "" && b === "") { bar.classList.add("is-none"); }
        bar.appendChild(fill); btn.appendChild(bar);
      }
      btn.setAttribute("aria-label", cellTitle(td) + ": " + text + ". Edit");
    }
    model.refresh = refresh;
    [inp].concat(model.pair ? [model.pair.lo === inp ? model.pair.hi : model.pair.lo] : []).forEach(function (i) {
      i.addEventListener("input", refresh); i.addEventListener("change", refresh); watchValue(i, refresh);
    });
    btn.addEventListener("click", function () { openCell(td); });
    refresh();
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
    ["min", "max", "step", "data-step", "placeholder"].forEach(function (a) { if (real.hasAttribute(a)) { c.setAttribute(a, real.getAttribute(a)); } });
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
    var body = el("div", "pfas-cell-form"), copies = [], first;
    if (p) {
      var w = el("div"); w.setAttribute("data-range", ""); w.setAttribute("data-scale", p.scaleAttr); w.setAttribute("data-unit", p.unit);
      var cl = copyNum(p.lo, title + " minimum"), ch = copyNum(p.hi, title + " maximum");
      w.appendChild(cl); w.appendChild(ch); body.appendChild(w);
      copies = [[p.lo, cl], [p.hi, ch]];
      first = p.end === "lo" ? cl : ch;
      initRange(w);
    } else {
      var cp = copyNum(c.inp, title);
      body.appendChild(cp); makeNum(cp);
      copies = [[c.inp, cp]]; first = cp;
    }
    function commit() {
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

  /* The input components, on PFAS pages only (core's React listings are left alone). */
  function enhance(root) {
    var area = doc.querySelector(".pfas-content-area");
    var scope = !root || root === doc ? area : (area && area.contains(root) ? root : null);
    if (!scope) { return; }
    initRanges(scope);
    initNums(scope);
    initCells(scope);
    initAllChips(scope);
  }

  function init(root) {
    root = root || doc;
    wrapTables(root === doc ? null : root);
    enhance(root);
    watchTables();
    var segs = root.querySelectorAll(".pfas-seg"); for (var i = 0; i < segs.length; i++) { initSeg(segs[i]); }
    var fabs = root.querySelectorAll(".pfas-fab"); for (var f = 0; f < fabs.length; f++) { initFab(fabs[f]); }
    var trees = root.querySelectorAll(".pfas-tree"); for (var t = 0; t < trees.length; t++) { initTree(trees[t]); }
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
  if (doc.readyState === "loading") { doc.addEventListener("DOMContentLoaded", function () { init(); }); } else { init(); }
  window.addEventListener("resize", function () {
    var segs = doc.querySelectorAll(".pfas-seg"); for (var i = 0; i < segs.length; i++) { placePill(segs[i]); }
  });
  window.PFAS = window.PFAS || {};
  window.PFAS.components = { init: init, enhance: enhance, theme: theme, drawer: drawer, placePill: placePill, wrapTables: wrapTables };
})();
