/* Control charts' lab overlay.
 *
 * Stacked: a strip per chosen reading under the chart, on the same run axis,
 * the rejected runs shaded through every strip. Relative overlay: one plot,
 * the analyte in standard deviations from its mean (the 2SD / 3SD lines read
 * for it), each reading on its own axis in its own units; the key sits above
 * the graph, top right. The helpers are DOM-free: tests/js/overlay_test.js. */
(function (root) {
  "use strict";

  function relative(values, mean, sd) {
    return (values || []).map(function (v) {
      if (v === null || v === undefined || !sd) { return null; }
      return Math.round(((v - mean) / sd) * 1000) / 1000;
    });
  }

  function shaded(westgard) {
    var seen = {};
    (westgard || []).forEach(function (v) {
      if (v.severity === "reject") { (v.indices || []).forEach(function (i) { seen[i] = true; }); }
    });
    return Object.keys(seen).map(Number).sort(function (a, b) { return a - b; });
  }

  var api = { relative: relative, shaded: shaded };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; }
  if (typeof window === "undefined") { return; }
  root.PFAS = root.PFAS || {};
  root.PFAS.chartOverlay = api;

  var COLOURS = ["--series-4", "--series-2", "--series-3", "--series-5"];
  function tok(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888"; }

  /* the strips under the main chart: one small chart per reading */
  api.drawStrips = function (holder, labels, overlays, westgard, axisX) {
    if (!holder || !overlays || !overlays.length) { return; }
    var shade = shaded(westgard), bad = tok("--s-info-lt");
    overlays.forEach(function (ov, n) {
      var box = document.createElement("div");
      box.className = "chart-strip";
      var canvas = document.createElement("canvas");
      box.appendChild(canvas);
      holder.appendChild(box);
      var ann = {};
      shade.forEach(function (i) {
        ann["s" + i] = { type: "box", xMin: i - 0.5, xMax: i + 0.5, backgroundColor: bad, borderWidth: 0,
                         drawTime: "beforeDatasetsDraw" };
      });
      var c = tok(COLOURS[n % COLOURS.length]);
      new root.Chart(canvas, {
        type: "line",
        data: { labels: labels, datasets: [{ label: ov.label + " (" + ov.unit + ")", data: ov.values, spanGaps: true,
                borderColor: c, backgroundColor: c, borderWidth: 1.5, pointRadius: 2, tension: 0 }] },
        options: { responsive: true, maintainAspectRatio: false, animation: false,
                   plugins: { legend: { display: false }, annotation: { annotations: ann },
                              title: { display: true, text: ov.label + " (" + ov.unit + ")", align: "start", font: { size: 11 } } },
                   scales: { x: Object.assign({}, axisX, { ticks: { display: n === overlays.length - 1 } }),
                             y: { grace: "10%", ticks: { font: { size: 10 } } } } }
      });
    });
  };

  /* the relative overlay: the main dataset in SDs, a dataset and an axis per reading */
  api.relativeSets = function (values, mean, sd, overlays) {
    var sets = [], scales = {};
    (overlays || []).forEach(function (ov, n) {
      var c = tok(COLOURS[n % COLOURS.length]), id = "y" + (n + 2);
      sets.push({ label: ov.label + " (" + ov.unit + ")", data: ov.values, yAxisID: id, spanGaps: true,
                  borderColor: c, backgroundColor: c, borderWidth: 1.5, pointRadius: 2, tension: 0, order: 2 });
      scales[id] = { position: "right", grid: { display: false }, grace: "10%",
                     title: { display: true, text: ov.unit, font: { size: 11 } } };
    });
    return { values: relative(values, mean, sd), sets: sets, scales: scales };
  };
})(typeof window !== "undefined" ? window : this);
