/* pfas-components.js — behaviour for the shared components (pfas-components.css).
 * Loaded by the page macro and the core overlay viewlet. Plain ES5, no library.
 *   - theme: html[data-theme] from localStorage ("pfas_theme"); light unless the
 *     person chose dark (light is the lab's default)
 *   - .pfas-seg: the pill follows the active item; click switches items and
 *     panes ([data-tabs] root, data-pane ids); arrow keys move between tabs
 *   - .pfas-fab: open / close, scrim and Escape
 *   - .pfas-drawer: open(html) / close, scrim and Escape, #hash deep link hook
 *   - .pfas-tree[data-view]: "path" hides rows marked is-off-path
 *   - form[data-autosubmit]: a filter bar that submits when any field changes
 * Nothing cycles on its own; motion is CSS and honours reduced motion.
 */
(function () {
  "use strict";
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
      var panes = root.querySelectorAll(".pfas-pane");
      for (var p = 0; p < panes.length; p++) { panes[p].classList.toggle("is-active", panes[p].id === pane); }
      if (seg.hasAttribute("data-hash")) { try { history.replaceState(null, "", "#" + pane); } catch (e) {} }
    }
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
      d.innerHTML = '<div class="pfas-drawer-head"><h2></h2><button type="button" class="btn-sm btn-secondary pfas-drawer-close" aria-label="Close">Close</button></div><div class="pfas-drawer-body"></div>';
      var s = doc.createElement("div"); s.className = "pfas-drawer-scrim";
      doc.body.appendChild(d); doc.body.appendChild(s);
      d.querySelector(".pfas-drawer-close").addEventListener("click", drawer.close);
      s.addEventListener("click", drawer.close);
      doc.addEventListener("keydown", function (e) { if (e.key === "Escape") { drawer.close(); } });
      drawer.el = d;
      return d;
    },
    open: function (title, html) {
      var d = drawer.ensure();
      d.querySelector("h2").textContent = title || "";
      d.querySelector(".pfas-drawer-body").innerHTML = html || "";
      d.setAttribute("data-open", "true");
      d.querySelector(".pfas-drawer-close").focus();
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

  function init(root) {
    root = root || doc;
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
  window.PFAS.components = { init: init, theme: theme, drawer: drawer, placePill: placePill };
})();
