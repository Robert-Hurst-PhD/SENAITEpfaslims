/* System map (@@pfas-system-map): the lab's live model as a tree, laid out
   with d3 (vendored, static/vendor/d3-7.9.0.min.js). A level is fetched from
   @@pfas-system-map-data when its node opens; nothing loads before. Nodes are
   buttons (keyboard reachable), the links SVG paths behind them. Drag moves
   the map; Ctrl + wheel or the Fit button changes the zoom, so a plain wheel
   still scrolls the page. Pages: system_map.pt; data: system_map_data.py. */
(function () {
  'use strict';
  var host = document.getElementById('pfas-map');
  if (!host || !window.d3) return;
  var d3 = window.d3;
  var view = host.querySelector('.pfas-map-view');
  var card = host.querySelector('.pfas-map-card');
  var dataUrl = host.getAttribute('data-url');
  var initial;
  try { initial = JSON.parse(host.getAttribute('data-root')); } catch (e) { return; }

  var NODE_W = 168, NODE_H = 44, DX = 58, DY = 214;
  var KIND_NAME = { lab: 'Laboratory', method: 'Method', matrix: 'Matrix', config: 'Method setting',
    worksheet: 'Worksheet', stages: 'Stages', sample: 'Sample', result: 'Result', group: 'Lots',
    lot: 'Lot', more: 'More' };
  var KIND_CLASS = { lab: 'k-lab', method: 'k-method', matrix: 'k-matrix', config: 'k-matrix',
    worksheet: 'k-worksheet', stages: 'k-worksheet', sample: 'k-sample', result: 'k-sample',
    group: 'k-lot', lot: 'k-lot', more: 'k-more' };

  function mk(data, parent) { return { data: data, parent: parent || null, kids: null, open: false }; }
  function setKids(t, list) { t.kids = (list || []).map(function (n) { return mk(n, t); }); }

  var top, sel;
  function start() {
    top = mk(initial.node);
    setKids(top, initial.children);
    top.open = true;
    sel = top;
  }
  start();

  var state = { pathOnly: false, cross: true, query: '' };
  try { state.pathOnly = window.localStorage.getItem('pfas_map_path') === '1'; } catch (e) { /* private window */ }

  /* ── the drawing surface ── */
  var fallback = view.querySelector('.pfas-map-fallback');
  if (fallback) fallback.parentNode.removeChild(fallback);
  var plane = document.createElement('div');
  plane.className = 'pfas-map-plane';
  view.appendChild(plane);
  var svg = d3.select(plane).append('svg').attr('aria-hidden', 'true');
  var gLinks = svg.append('g');
  var gCross = svg.append('g');
  var layer = document.createElement('div');
  plane.appendChild(layer);

  var current = d3.zoomIdentity.translate(24, 24);
  var zoom = d3.zoom().scaleExtent([0.35, 1.6])
    .filter(function (ev) {
      if (ev.type === 'wheel') return ev.ctrlKey;
      if (ev.button) return false;
      return !(ev.target.closest && ev.target.closest('button'));
    })
    .on('zoom', function (ev) {
      current = ev.transform;
      plane.style.transform = 'translate(' + current.x + 'px,' + current.y + 'px) scale(' + current.k + ')';
    });
  d3.select(view).call(zoom).on('dblclick.zoom', null);
  d3.select(view).call(zoom.transform, current);

  /* ── which nodes show ── */
  function onPath(t) { for (var w = sel; w; w = w.parent) { if (w === t) return true; } return false; }
  function kidsFor(t) {
    if (!t.open || !t.kids || !t.kids.length) return null;
    if (!state.pathOnly || t === sel) return t.kids;
    if (onPath(t)) return t.kids.filter(onPath);
    return null;
  }

  var bounds = { w: 0, h: 0 };
  function render() {
    var keepFocus = document.activeElement && document.activeElement.getAttribute
      ? document.activeElement.getAttribute('data-key') : null;
    var h = d3.hierarchy(top, kidsFor);
    d3.tree().nodeSize([DX, DY]).separation(function (a, b) { return a.parent === b.parent ? 1 : 1.25; })(h);
    var all = h.descendants();
    var minX = d3.min(all, function (d) { return d.x; });
    var maxX = d3.max(all, function (d) { return d.x; });
    var maxD = d3.max(all, function (d) { return d.depth; });
    var off = -minX + NODE_H / 2 + 8;
    bounds = { w: (maxD + 1) * DY + NODE_W, h: (maxX - minX) + NODE_H + 16 };
    svg.attr('width', bounds.w).attr('height', bounds.h);

    var pos = {};
    all.forEach(function (d) { d.left = d.y; d.cy = d.x + off; if (!pos[d.data.data.id]) pos[d.data.data.id] = d; });

    function curve(s, t) {
      var x1 = s.left + NODE_W, x2 = t.left, mx = (x1 + x2) / 2;
      return 'M' + x1 + ',' + s.cy + 'C' + mx + ',' + s.cy + ' ' + mx + ',' + t.cy + ' ' + x2 + ',' + t.cy;
    }
    var links = gLinks.selectAll('path').data(h.links());
    links.exit().remove();
    links.enter().append('path').merge(links)
      .attr('class', function (l) { return 'pfas-map-link' + (onPath(l.target.data) ? ' is-path' : ''); })
      .attr('d', function (l) { return curve(l.source, l.target); });

    var cross = [];
    if (state.cross) {
      var seen = {};
      all.forEach(function (d) {
        (d.data.data.links || []).forEach(function (to) {
          var t = pos[to];
          var key = [d.data.data.id, to].sort().join('>');
          if (t && !seen[key]) { seen[key] = 1; cross.push([d, t]); }
        });
      });
    }
    var cl = gCross.selectAll('path').data(cross);
    cl.exit().remove();
    cl.enter().append('path').attr('class', 'pfas-map-cross').merge(cl)
      .attr('d', function (p) {
        var a = p[0], b = p[1], x1 = a.left + NODE_W, x2 = b.left + NODE_W, bulge = Math.max(x1, x2) + 90;
        return 'M' + x1 + ',' + a.cy + 'C' + bulge + ',' + a.cy + ' ' + bulge + ',' + b.cy + ' ' + x2 + ',' + b.cy;
      });

    layer.textContent = '';
    var q = state.query.toLowerCase();
    all.forEach(function (d) {
      var t = d.data, n = t.data;
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'pfas-map-node' + (t === sel ? ' is-selected' : (onPath(t) ? ' is-path' : '')) +
        (q && (n.label + ' ' + (n.sub || '')).toLowerCase().indexOf(q) !== -1 ? ' is-match' : '');
      b.style.left = d.left + 'px';
      b.style.top = (d.cy - NODE_H / 2) + 'px';
      b.setAttribute('data-key', n.id);
      b.setAttribute('aria-label', n.label + ', ' + (KIND_NAME[n.kind] || n.kind));
      var edge = document.createElement('span');
      edge.className = 'pfas-map-edge ' + (KIND_CLASS[n.kind] || 'k-lab');
      var strong = document.createElement('b');
      strong.textContent = n.label;
      var small = document.createElement('small');
      small.textContent = n.sub || '';
      b.appendChild(edge); b.appendChild(strong); b.appendChild(small);
      b.addEventListener('click', function () { select(t); });
      layer.appendChild(b);
      if (n.has_children) {
        var tog = document.createElement('button');
        tog.type = 'button';
        tog.className = 'pfas-map-tog';
        tog.style.left = (d.left + NODE_W - 12) + 'px';
        tog.style.top = (d.cy - 12) + 'px';
        tog.textContent = t.open ? '−' : '+';
        tog.setAttribute('aria-label', (t.open ? 'Close ' : 'Open ') + n.label);
        tog.setAttribute('aria-expanded', t.open ? 'true' : 'false');
        tog.setAttribute('data-key', n.id + '|tog');
        tog.addEventListener('click', function () { toggle(t, tog); });
        layer.appendChild(tog);
      }
    });
    if (keepFocus) {
      var again = layer.querySelector('[data-key="' + keepFocus.replace(/"/g, '\\"') + '"]');
      if (again) again.focus();
    }
    showCard();
  }

  function toggle(t, tog) {
    if (t.open) { t.open = false; render(); return; }
    if (t.kids) { t.open = true; render(); return; }
    tog.setAttribute('aria-busy', 'true');
    fetch(dataUrl + '?node=' + encodeURIComponent(t.data.id), { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j.error) throw new Error(j.error);
        setKids(t, j.children);
        t.open = true;
        render();
      })
      .catch(function (err) {
        tog.removeAttribute('aria-busy');
        tog.title = 'Not opened: ' + (err && err.message ? err.message : 'the server did not answer');
      });
  }

  function select(t) { sel = t; render(); }

  function showCard() {
    var n = sel.data;
    var kind = card.querySelector('.pfas-map-kind');
    kind.querySelector('i').className = KIND_CLASS[n.kind] || 'k-lab';
    kind.querySelector('span').textContent = KIND_NAME[n.kind] || n.kind;
    card.querySelector('h3').textContent = n.label;
    var badge = card.querySelector('.pfas-map-badge');
    badge.hidden = !n.badge;
    badge.className = 'badge pfas-map-badge ' + (n.badge_kind || '');
    badge.textContent = n.badge || '';
    var dl = card.querySelector('dl');
    dl.textContent = '';
    (n.facts || []).forEach(function (f) {
      var dt = document.createElement('dt'), dd = document.createElement('dd');
      dt.textContent = f[0]; dd.textContent = f[1];
      dl.appendChild(dt); dl.appendChild(dd);
    });
    var open = card.querySelector('.pfas-map-open');
    open.hidden = !n.url;
    if (n.url) { open.href = n.url; open.textContent = 'Open ' + (KIND_NAME[n.kind] || '').toLowerCase(); }
    card.querySelector('.pfas-map-pathbtn').hidden = sel === top;
  }

  function fit() {
    var vw = view.clientWidth, vh = view.clientHeight;
    var k = Math.max(0.35, Math.min(1, (vw - 48) / bounds.w, (vh - 48) / bounds.h));
    var t = d3.zoomIdentity.translate(24, Math.max(24, (vh - bounds.h * k) / 2)).scale(k);
    d3.select(view).call(zoom.transform, t);
  }

  /* ── controls ── */
  var pathSwitch = document.getElementById('map-path-only');
  var crossSwitch = document.getElementById('map-cross');
  var find = document.getElementById('map-find');
  if (pathSwitch) {
    pathSwitch.checked = state.pathOnly;
    pathSwitch.addEventListener('change', function () {
      state.pathOnly = pathSwitch.checked;
      try { window.localStorage.setItem('pfas_map_path', state.pathOnly ? '1' : '0'); } catch (e) { /* ignore */ }
      render();
    });
  }
  if (crossSwitch) crossSwitch.addEventListener('change', function () { state.cross = crossSwitch.checked; render(); });
  if (find) find.addEventListener('input', function () { state.query = find.value.trim(); render(); });
  var pathBtn = card.querySelector('.pfas-map-pathbtn');
  pathBtn.addEventListener('click', function () {
    state.pathOnly = true;
    if (pathSwitch) pathSwitch.checked = true;
    render();
  });
  document.getElementById('map-fit').addEventListener('click', fit);
  document.getElementById('map-reset').addEventListener('click', function () {
    start();
    state.pathOnly = false; state.query = '';
    if (pathSwitch) pathSwitch.checked = false;
    if (find) find.value = '';
    render(); fit();
  });

  render();
  fit();
})();
