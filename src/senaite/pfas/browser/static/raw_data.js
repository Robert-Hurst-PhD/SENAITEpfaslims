/* raw_data.js — Data Review's Raw Data tab, for a run imported from raw data.
 * The overview: "By compound" (one analyte across every injection) or "By
 * injection" (every analyte of one injection), the list down the left (each a
 * button to its page), and each chromatogram as a small inline SVG, a button
 * that opens its full card in the centred dialog, Previous and Next (and
 * PageUp, PageDown) in its head walking the overview's order, the grid
 * following. The card: the quantifier and qualifier traces with the
 * integrated peak shaded over its baseline (an edit waiting for the run
 * drawn as it will be), its isotope standard beside it; under them the
 * readout strip (area, retention time, S/N, ion ratio, concentration, how
 * the peak was integrated) and the flags as chips; for an analyst who may
 * edit, the trace's edits on the chart: the baseline drawn with a handle
 * at each end (sideways the edge, up or down the level), the right-click
 * menu (and the Actions button, the menu key, the keys) to set an edge or
 * the level at the cursor, choose the line or another peak, add a peak or
 * split at the cursor, delete the peak, undo, zoom or copy the values,
 * with the area previewed as the worker will measure it and
 * the method's limits on a manual change said before anything is posted
 * (an edit the server refused opens again as it was posted); and a Details
 * disclosure with the rest. The server judges again and is the authority.
 * Data: #raw-data-json (data_review.raw_tab_json); one card from its card_url
 * (raw_card=1); edits post the hidden form#raw-edit. Chart.js and its
 * annotation plugin. Plain ES5. */
(function () {
  "use strict";
  var doc = typeof document !== "undefined" ? document : null;   /* node: the pure helpers only */

  /* ── the integrated peak as drawn ─────────────────────────────────────── */
  function baselineAt(peak, x) {
    var span = peak.end - peak.start;
    if (!span) { return peak.base_start; }
    return peak.base_start + (peak.base_end - peak.base_start) * (x - peak.start) / span;
  }

  /* the integrated region: the trace's points from start to end, and the
     baseline under each (what the shading fills between) */
  function peakFill(t, y, peak) {
    var top = [], base = [];
    if (!peak || peak.start == null || peak.end == null) { return { top: top, base: base }; }
    for (var i = 0; i < t.length; i++) {
      if (t[i] >= peak.start && t[i] <= peak.end) {
        top.push({ x: t[i], y: y[i] });
        base.push({ x: t[i], y: baselineAt(peak, t[i]) });
      }
    }
    return { top: top, base: base };
  }

  /* a peak's outline, closed: its baseline's start, the trace over the peak,
     its baseline's end and back (the automatic peak, dashed, once edited) */
  function peakOutline(t, y, peak) {
    if (!peak || peak.start == null || peak.end == null) { return []; }
    var out = [{ x: peak.start, y: peak.base_start }];
    for (var i = 0; i < t.length; i++) {
      if (t[i] >= peak.start && t[i] <= peak.end) { out.push({ x: t[i], y: y[i] }); }
    }
    out.push({ x: peak.end, y: peak.base_end });
    out.push({ x: peak.start, y: peak.base_start });
    return out;
  }

  /* the states a card or thumbnail is drawn in; any other draws none */
  var STATES = ["nd", "fail", "warn", "missing"];
  function knownState(state) { return STATES.indexOf(state) >= 0 ? state : ""; }
  function stateClass(state) { return knownState(state) ? "raw-card is-" + state : "raw-card"; }

  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function num(v, d) {
    if (v == null || v === "") { return "—"; }
    return typeof v === "number" ? (Math.abs(v) >= 1000 ? String(Math.round(v)).replace(/\B(?=(\d{3})+(?!\d))/g, ",") : v.toFixed(d == null ? 3 : d)) : String(v);
  }

  /* ── Python's number formatting, so a refusal reads as the server's ───── */
  /* "%.*f": the nearest decimal, an exact tie to the even digit (toFixed
     takes the larger) */
  function pyFixed(v, places) {
    var s = v.toFixed(places);
    if (!isFinite(v)) { return s; }
    var mag = Math.abs(v), exact = mag.toFixed(places + 20);
    if (!/50{19}$/.test(exact)) { return s; }
    var down = exact.slice(0, exact.length - (places < 1 ? 21 : 20));
    var last = parseInt(down.charAt(down.length - 1), 10);
    if (last % 2 === 0) { return (v < 0 ? "-" : "") + down; }
    return s;
  }
  /* "{:,.0f}": a count as the panel writes it, "4,000" (raw_review.counts) */
  function counts(v) {
    var s = pyFixed(v, 0), sign = s.charAt(0) === "-" ? "-" : "";
    return sign + s.slice(sign.length).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  }
  /* "%g": six significant digits, trailing zeros dropped, an exponent below
     1e-4 or from 1e6 */
  function pyG(v) {
    if (v === 0) { return "0"; }
    if (!isFinite(v)) { return v > 0 ? "inf" : (v < 0 ? "-inf" : "nan"); }
    var e = parseInt(v.toExponential(5).split("e")[1], 10);
    if (e < -4 || e >= 6) {
      var parts = v.toExponential(5).split("e");
      var mant = parts[0].indexOf(".") >= 0 ? parts[0].replace(/0+$/, "").replace(/\.$/, "") : parts[0];
      var ex = parseInt(parts[1], 10);
      var digits = String(Math.abs(ex));
      return mant + "e" + (ex < 0 ? "-" : "+") + (digits.length < 2 ? "0" + digits : digits);
    }
    var s = v.toFixed(Math.max(0, 5 - e));
    return s.indexOf(".") >= 0 ? s.replace(/0+$/, "").replace(/\.$/, "") : s;
  }
  /* "%r": the shortest text that reads back as the number */
  function pyRepr(v) {
    var s = String(v);
    return /^-?\d+$/.test(s) ? s + ".0" : s;
  }

  /* ── the engines' manual measure (raw_preview.py, held to the same
        fixture, tests/raw_preview_parity.json) ───────────────────────── */
  /* a manual peak's baselines (raw_preview.BASELINES): valley to valley,
     a perpendicular drop, flat at the lower edge, a tangent skim */
  var BASELINES = ["valley", "drop", "flat", "skim"];

  function quadraticAt(seg, x) {
    var n = seg.length, c = (n - 1) / 2.0, s0 = n, s2 = 0, s4 = 0, sy = 0, suy = 0, su2y = 0;
    for (var i = 0; i < n; i++) {
      var u = i - c, u2 = u * u, v = seg[i];
      s2 += u2; s4 += u2 * u2; sy += v; suy += u * v; su2y += u2 * v;
    }
    var b = suy / s2, det = s0 * s4 - s2 * s2;
    var a0 = (sy * s4 - s2 * su2y) / det, a2 = (s0 * su2y - s2 * sy) / det;
    var w = x - c;
    return a0 + b * w + a2 * w * w;
  }
  /* the Savitzky-Golay smoothing (second order, n points) of y at i; within
     half a window of either end the fit over the first or last n points */
  function savgolAt(y, i, n) {
    var half = Math.floor(n / 2);
    if (i < half) { return quadraticAt(y.slice(0, n), i); }
    if (i >= y.length - half) { return quadraticAt(y.slice(y.length - n), i - (y.length - n)); }
    return quadraticAt(y.slice(i - half, i + half + 1), half);
  }
  function toInt(v) {
    var n = Number(v);
    if (v == null || v === "" || isNaN(n)) { throw new TypeError("not a number: " + v); }
    return n < 0 ? Math.ceil(n) : Math.floor(n);
  }
  function classicSmoothing(y, smoothPoints) {
    var n = Math.min(toInt(smoothPoints), y.length - (1 - y.length % 2));
    return n >= 5 ? n : null;
  }
  function adaptiveSmoothing(y, m) { return y.length > 2 * m + 3 ? 2 * m + 1 : null; }
  function smoothed(y, i, n) { return n == null ? y[i] : savgolAt(y, i, n); }

  /* the index of t nearest x, the first of two equally near */
  function nearest(t, x) {
    var best = 0;
    for (var i = 1; i < t.length; i++) { if (Math.abs(t[i] - x) < Math.abs(t[best] - x)) { best = i; } }
    return best;
  }
  function interp(x, x0, x1, y0, y1) {
    if (x === x1) { return y1; }
    return (y1 - y0) / (x1 - x0) * (x - x0) + y0;
  }
  function mean(values) {
    var s = 0;
    for (var i = 0; i < values.length; i++) { s += values[i]; }
    return s / values.length;
  }
  function trapezoid(t, v) {
    var s = 0;
    for (var i = 0; i < t.length - 1; i++) { s += (t[i + 1] - t[i]) * (v[i + 1] + v[i]) / 2.0; }
    return s;
  }
  /* [index, smoothed value] of the highest smoothed point in [s, e], the first of equals */
  function apexOf(y, s, e, n) {
    var best = s, top = smoothed(y, s, n);
    for (var i = s + 1; i <= e; i++) {
      var v = smoothed(y, i, n);
      if (v > top) { best = i; top = v; }
    }
    return [best, top];
  }

  /* the level at an edge: the mean of the raw signal from point i outwards
     (side -1 before it, +1 after it) over n more points, cut at the trace's ends */
  function edgeLevel(y, i, side, n) {
    return side < 0 ? mean(y.slice(Math.max(i - n, 0), i + 1)) : mean(y.slice(i, i + n + 1));
  }
  /* Classic's baseline under points s..e: "valley" joins the two edge
     levels, "flat" runs flat at the lower */
  function classicBase(t, y, s, e, baseline, edgePoints) {
    var ep = toInt(edgePoints), left = edgeLevel(y, s, -1, ep), right = edgeLevel(y, e, 1, ep), out = [];
    for (var i = s; i <= e; i++) {
      out.push(baseline === "flat" ? Math.min(left, right) : interp(t[i], t[s], t[e], left, right));
    }
    return out;
  }
  /* Adaptive's line, [at s, at e]: each end the mean over m points on the
     outer side of the edge, read at that window's centre, the line through
     the two centres extrapolated to the edges (in points) */
  function adaptiveBase(y, s, e, m) {
    var w = Math.max(m, 1), l0 = Math.max(s - w, 0), r1 = Math.min(e + w, y.length - 1);
    var left = mean(y.slice(l0, s + 1)), right = mean(y.slice(e, r1 + 1));
    var cl = (l0 + s) / 2.0, cr = (e + r1) / 2.0, k = (right - left) / (cr - cl);
    return [left + k * (s - cl), right + k * (e - cr)];
  }

  function isFiniteNumber(v) { return typeof v === "number" && isFinite(v); }
  /* [left, right] baseline levels set by hand, two finite numbers, or null */
  function checkLevels(levels) {
    if (levels == null) { return null; }
    if (!(levels instanceof Array) || levels.length !== 2 || !isFiniteNumber(levels[0]) ||
        !isFiniteNumber(levels[1])) { throw new Error("the baseline levels are two numbers"); }
    return [levels[0], levels[1]];
  }
  /* the smoothed signal as a function of an index, each point once */
  function memo(y, n) {
    var seen = {};
    return function (i) {
      if (!seen.hasOwnProperty(i)) { seen[i] = smoothed(y, i, n); }
      return seen[i];
    };
  }
  /* the peak search amplitude when none is given (raw_preview.DEFAULT_SEARCH_AMP_SN) */
  var DEFAULT_SEARCH_AMP_SN = 3.0;
  /* [top, far edge] of the neighbouring peak beyond index i (step -1 before
     it, +1 after it) on the smoothed signal sm of n points: it falls while it
     falls to the valley, climbs while it rises to the top, then falls while
     it falls; a peak only when its top lies inside the trace, rises at
     least `rise` above that valley and the signal falls at least `rise` again
     to its far edge, else (or with no rise) null (raw_preview._outward) */
  function outward(sm, n, i, step, rise) {
    var j = i;
    while (j + step >= 0 && j + step < n && sm(j + step) <= sm(j)) { j += step; }
    var valley = j;
    while (j + step >= 0 && j + step < n && sm(j + step) > sm(j)) { j += step; }
    var top = j;
    if (rise == null || top === 0 || top === n - 1 || !(sm(top) - sm(valley) >= rise)) { return null; }
    while (j + step >= 0 && j + step < n && sm(j + step) <= sm(j)) { j += step; }
    if (!(sm(top) - sm(j) >= rise)) { return null; }
    return [top, j];
  }
  /* the index farthest beyond i (step -1 before it, +1 after it) that the
     neighbour walk from i, or from any edge between i and the peak, ends
     at whatever its rise: the end of its three runs, or its valley where
     the climb runs to the trace's end (raw_preview.walk_reach) */
  function walkReach(sm, n, i, step) {
    var j = i;
    while (j + step >= 0 && j + step < n && sm(j + step) <= sm(j)) { j += step; }
    var valley = j;
    while (j + step >= 0 && j + step < n && sm(j + step) > sm(j)) { j += step; }
    if (j === 0 || j === n - 1) { return valley; }
    while (j + step >= 0 && j + step < n && sm(j + step) <= sm(j)) { j += step; }
    return j;
  }
  /* how many points beyond an edge, and about the apex, the engine's manual
     measure reads (raw_preview.read_margin, the worker's) */
  function readMargin(engine, smoothPoints, edgePoints, m) {
    if (engine === "adaptive") { return Math.max(toInt(m), 1) + 1; }
    return Math.max(toInt(edgePoints), Math.floor(toInt(smoothPoints) / 2));
  }
  function engineSmoothing(engine, y, smoothPoints, m) {
    return engine === "adaptive" ? adaptiveSmoothing(y, Math.max(toInt(m), 1)) : classicSmoothing(y, smoothPoints);
  }
  /* [i0, i1]: the stored samples a drop's or a skim's measure from the
     edges at s and e reads at most: the neighbour walk either way, the
     sample past it, and the margin beyond (raw_preview.read_reach) */
  function readReach(engine, t, y, s, e, smoothPoints, edgePoints, m) {
    var n = y.length, sm = memo(y, engineSmoothing(engine, y, smoothPoints, m));
    var margin = readMargin(engine, smoothPoints, edgePoints, m);
    return [Math.max(walkReach(sm, n, s, -1) - 1 - margin, 0), Math.min(walkReach(sm, n, e, 1) + 1 + margin, n - 1)];
  }
  /* a Gaussian peak's half width at half its height, in its standard deviations */
  var HALF_WIDTH_SIGMA = Math.sqrt(2.0 * Math.log(2.0));
  /* [before, after]: how far a measured peak falls to half its height
     either side of its apex, on the engine's smoothed signal above its line
     carried on past its edges; null for a side that turns up again or
     reaches the trace's end first (raw_preview.half_widths) */
  function halfWidths(engine, t, y, measured, smoothPoints, m) {
    var s = measured.s, e = measured.e, a = nearest(t, measured.apex);
    var sm = memo(y, engineSmoothing(engine, y, smoothPoints, m)), b0 = measured.base_start, b1 = measured.base_end;
    if (t[e] === t[s]) { return [null, null]; }
    var above = function (i) { return sm(i) - interp(t[i], t[s], t[e], b0, b1); };
    var half = above(a) / 2.0;
    if (!(half > 0)) { return [null, null]; }
    var side = function (step) {
      var i = a;
      while (i + step >= 0 && i + step < t.length) {
        var j = i + step, vi = above(i), vj = above(j);
        if (vj <= half) { return Math.abs(measured.apex - (t[j] + (half - vj) / (vi - vj) * (t[i] - t[j]))); }
        if (sm(j) > sm(i)) { return null; }
        i = j;
      }
      return null;
    };
    return [side(-1), side(1)];
  }
  /* how far a neighbour's top rises above its valley at least: amp (the
     default when none) times the trace's sigma; null without a sigma */
  function riseOf(sigma, amp) {
    if (sigma == null) { return null; }
    return (amp == null ? DEFAULT_SEARCH_AMP_SN : amp) * sigma;
  }
  /* a manual peak's line over the edges s and e (raw_preview._line): ends(i,
     j) are the engine's levels at i and j, levels set by hand replace the
     two the baseline reads; valley the levels at s and e, flat the lower of
     them, drop the levels at the pair's outer edges (bounds, else each
     neighbour's far edge, else the edge), skim the smoothed signal at s
     and e; tops [[side, top]], side -1 before and +1 after, a side in skip
     left out */
  function manualLine(t, sm, s, e, baseline, ends, levels, bounds, rise, skip) {
    var left = null, right = null, tops = [], lo = s, hi = e, lv, rv;
    skip = skip || [];
    if (baseline === "drop" || baseline === "skim") {
      left = skip.indexOf(-1) >= 0 ? null : outward(sm, t.length, s, -1, rise);
      right = skip.indexOf(1) >= 0 ? null : outward(sm, t.length, e, 1, rise);
    }
    if (left) { tops.push([-1, left[0]]); }
    if (right) { tops.push([1, right[0]]); }
    if (baseline === "drop") {
      if (bounds != null) {
        lo = nearest(t, Math.min(bounds[0], bounds[1]));
        hi = nearest(t, Math.max(bounds[0], bounds[1]));
        if (lo > s || hi < e) { throw new Error("the drop's baseline runs under the whole pair"); }
      } else {
        lo = left ? left[1] : s;
        hi = right ? right[1] : e;
      }
    }
    if (levels != null) { lv = levels[0]; rv = levels[1]; }
    else if (baseline === "skim") { lv = sm(s); rv = sm(e); }
    else { var en = ends(lo, hi); lv = en[0]; rv = en[1]; }
    if (baseline === "flat") { lv = rv = Math.min(lv, rv); }
    var x0 = t[lo], x1 = t[hi];
    var line = function (i) { return interp(t[i], x0, x1, lv, rv); };
    return { b: [line(s), line(e)], line: line, outer: [lo, hi], tops: tops, ends: ends, rise: rise, skip: skip };
  }
  /* part over whole in %, a share of a peak only between 0 and 100; else
     null (raw_preview._share) */
  function shareOf(part, whole) {
    if (!(whole > 0)) { return null; }
    var share = part / whole * 100.0;
    return share >= 0.0 && share <= 100.0 ? share : null;
  }
  /* [valley share, skim share, the sides whose neighbour is no peak beside
     this one], each share in %, null where it does not apply
     (raw_preview._shares) */
  function lineShares(t, sm, s, e, a, height, baseline, ln) {
    var k, i;
    if (baseline === "drop") {
      var out = null, bad = [];
      for (k = 0; k < ln.tops.length; k++) {
        var top = ln.tops[k][1], lo = Math.min(a, top), hi = Math.max(a, top), v = lo;
        for (i = lo + 1; i <= hi; i++) { if (sm(i) < sm(v)) { v = i; } }
        var share = shareOf(sm(v) - ln.line(v), Math.min(height, sm(top) - ln.line(top)));
        if (share === null) { bad.push(ln.tops[k][0]); }
        else { out = out === null ? share : Math.max(out, share); }
      }
      return [out, null, bad];
    }
    if (baseline === "skim" && ln.tops.length) {
      var parent = ln.tops[0][1];
      for (k = 1; k < ln.tops.length; k++) { if (sm(ln.tops[k][1]) > sm(parent)) { parent = ln.tops[k][1]; } }
      var outer = manualLine(t, sm, s, e, "drop", ln.ends, null, null, ln.rise, ln.skip);
      return [null, shareOf(height, sm(parent) - outer.line(parent)), []];
    }
    return [null, null, []];
  }
  /* the measures over the line build(skip) draws, drawn again without a
     neighbour that is no peak beside this one: the trapezoid above it (clip,
     the engine's own reading of a part below it; none with levels set by
     hand), the shares, the baseline and its levels (raw_preview._measures) */
  function lineMeasures(t, y, s, e, a, top, build, sm, baseline, levels, clip) {
    var skip = [], ln, b0, b1, height, shares;
    for (;;) {
      ln = build(skip);
      b0 = ln.b[0]; b1 = ln.b[1];
      height = top - interp(t[a], t[s], t[e], b0, b1);
      shares = lineShares(t, sm, s, e, a, height, baseline, ln);
      if (!shares[2].length) { break; }
      skip = skip.concat(shares[2]);
    }
    var above = [];
    for (var i = s; i <= e; i++) { above.push(y[i] - interp(t[i], t[s], t[e], b0, b1)); }
    var area = levels != null ? trapezoid(t.slice(s, e + 1), above) : clip(t.slice(s, e + 1), above);
    return { s: s, e: e, start: t[s], end: t[e], base_start: b0, base_end: b1, apex_index: a, height: height,
             area: area, baseline: baseline, levels: levels, valley_share: shares[0], skim_share: shares[1],
             bounds: baseline === "drop" ? [t[ln.outer[0]], t[ln.outer[1]]] : null };
  }

  function classicPeak(t, y, start, end, baseline, smoothPoints, edgePoints, levels, bounds, rise) {
    var s = nearest(t, start), e = nearest(t, end);
    if (!(e > s)) { throw new Error("a peak's start is before its end"); }
    var ep = toInt(edgePoints), n = classicSmoothing(y, smoothPoints), sm = memo(y, n);
    var ends = function (i, j) { return [edgeLevel(y, i, -1, ep), edgeLevel(y, j, 1, ep)]; };
    var build = function (skip) { return manualLine(t, sm, s, e, baseline, ends, levels, bounds, rise, skip); };
    var ap = apexOf(y, s, e, n), a = ap[0];
    var out = lineMeasures(t, y, s, e, a, ap[1], build, sm, baseline, levels, function (tt, above) {
      return trapezoid(tt, above.map(function (v) { return Math.max(v, 0.0); }));
    });
    out.apex = t[a];
    return out;
  }

  function adaptivePeak(t, y, start, end, baseline, m, levels, bounds, rise) {
    var s = nearest(t, Math.min(start, end)), e = nearest(t, Math.max(start, end));
    if (e < s + 3) { throw new Error("the re-integration spans too few points"); }
    m = Math.max(toInt(m), 1);
    var n = adaptiveSmoothing(y, m), sm = memo(y, n);
    var ends = function (i, j) { return adaptiveBase(y, i, j, m); };
    var build = function (skip) { return manualLine(t, sm, s, e, baseline, ends, levels, bounds, rise, skip); };
    var ap = apexOf(y, s, e, n), a = ap[0], top = ap[1];
    var out = lineMeasures(t, y, s, e, a, top, build, sm, baseline, levels, function (tt, above) {
      return Math.max(trapezoid(tt, above), 0.0);
    });
    var rt = t[a];
    if (a > 0 && a < t.length - 1) {
      var y0 = smoothed(y, a - 1, n), y2 = smoothed(y, a + 1, n), den = y0 - 2 * top + y2;
      var off = den < 0 ? Math.min(0.5, Math.max(-0.5, 0.5 * (y0 - y2) / den)) : 0.0;
      rt = t[a] + off * (t[a + 1] - t[a]);
    }
    out.apex = rt;
    return out;
  }

  /* a manual peak's S/N, its height over the trace's noise sigma: under
     Classic no height above the baseline is 0; no noise is unbounded; no
     sigma, none */
  function snOf(engine, height, sigma) {
    if (sigma == null) { return null; }
    if (engine === "classic" && !(height > 0)) { return 0.0; }
    return sigma > 0 ? height / sigma : Infinity;
  }

  /* the manual peak between start and end under engine ("classic" or
     "adaptive") on the stored trace, as the worker will measure it: edge
     indices s and e, their times, the baseline ends, apex, height, area
     (trapezoid), S/N, the baseline and its levels, a drop's valley share and
     outer bounds, a skim's height over its parent's. opts: smooth_points and
     edge_points (Classic), m (Adaptive), levels ([left, right] set by hand),
     bounds (a drop's outer edges) and amp (the peak search amplitude a
     neighbour rises above its valley, times sigma). Throws, in raw_preview's
     words, on edges the engine refuses. */
  function previewPeak(engine, t, y, start, end, baseline, sigma, opts) {
    opts = opts || {};
    if (BASELINES.indexOf(baseline) < 0) { throw new Error("baseline is one of " + BASELINES.join(", ")); }
    var levels = checkLevels(opts.levels), bounds = opts.bounds == null ? null : opts.bounds;
    var rise = riseOf(sigma, opts.amp);
    var out = engine === "adaptive" ? adaptivePeak(t, y, start, end, baseline, opts.m, levels, bounds, rise)
                                    : classicPeak(t, y, start, end, baseline, opts.smooth_points, opts.edge_points,
                                                  levels, bounds, rise);
    out.sn = snOf(engine, out.height, sigma);
    return out;
  }

  /* another apex chosen as found (on the method's baseline): the candidate's
     own measures as the engine found them and the worker replays the
     choice, none where the record has none, and s and e, the indices of
     its edges in the stored trace t; never a measure of its own over the
     candidate's span (raw_preview.apex_preview) */
  var APEX_MEASURES = ["start", "end", "base_start", "base_end", "apex", "height", "area", "sn"];
  function apexPreview(t, c) {
    var out = {};
    APEX_MEASURES.forEach(function (k) { out[k] = c[k] == null ? null : c[k]; });
    out.s = nearest(t, c.start);
    out.e = nearest(t, c.end);
    return out;
  }

  /* ── the drag ─────────────────────────────────────────────────────────── */
  /* the index of the stored sample nearest x, among those inside fullRes
     ([lo, hi]) when given, the first of two equally near; -1 when none */
  function snapIndex(t, x, fullRes) {
    var best = -1;
    for (var i = 0; i < (t || []).length; i++) {
      if (fullRes && !(t[i] >= fullRes[0] && t[i] <= fullRes[1])) { continue; }
      if (best < 0 || Math.abs(t[i] - x) < Math.abs(t[best] - x)) { best = i; }
    }
    return best;
  }
  /* which edge a press at px takes: the nearer of the drawn start and end
     within tol pixels ("start" when equally near), else null */
  function dragTarget(px, startPx, endPx, tol) {
    var ds = startPx == null ? Infinity : Math.abs(px - startPx);
    var de = endPx == null ? Infinity : Math.abs(px - endPx);
    if (Math.min(ds, de) > tol) { return null; }
    return ds <= de ? "start" : "end";
  }

  /* the sample a held edge moves to with the pointer at x: the nearest
     inside fullRes, never on or across the other edge (start before end, a
     sample apart); -1 when that leaves no sample in the region */
  function dragIndex(t, x, fullRes, held, start, end) {
    var i = snapIndex(t, x, fullRes);
    if (held === "start" && end != null) { i = Math.min(i, snapIndex(t, end, null) - 1); }
    if (held === "end" && start != null) { i = Math.max(i, snapIndex(t, start, null) + 1); }
    if (i < 0 || i >= t.length) { return -1; }
    if (fullRes && !(t[i] >= fullRes[0] && t[i] <= fullRes[1])) { return -1; }
    return i;
  }
  /* a typed edge as it is kept: inside the region, or past it by no more
     than the tolerance the server allows, on its sample (the region's
     bound, said in note, when it was typed past it); further out, as typed,
     so the server's refusal stays in view */
  function typedEdge(t, v, fullRes, which) {
    if (!fullRes) { return { value: v, note: "" }; }
    var tol = edgeTolerance(t, fullRes);
    if (v < fullRes[0] - tol || v > fullRes[1] + tol) { return { value: v, note: "" }; }
    var i = snapIndex(t, v, fullRes);
    if (i < 0) { return { value: v, note: "" }; }
    var note = "";
    if (v < fullRes[0] || v > fullRes[1]) {
      note = "The " + which + " is moved to the full-resolution region's " + (v < fullRes[0] ? "first" : "last") +
             " sample, " + pyFixed(t[i], 3) + " min.";
    }
    return { value: t[i], note: note };
  }
  /* the edge boxes' step: the region's median sample spacing on two
     significant figures, so each press of the arrows reaches the next sample */
  function edgeStep(t, fullRes) {
    var half = fullRes ? edgeTolerance(t, fullRes) : 0;
    return half > 0 ? String(parseFloat((2 * half).toPrecision(2))) : "any";
  }

  /* ── what is posted ───────────────────────────────────────────────────── */
  function field(v) { return v == null || v === "" ? "" : String(v); }
  /* the hidden form's fields for an edit: only the kind's own filled, the
     rest empty (the server reads only the kind's); a re-integration's
     baseline levels set by hand both or neither */
  function editPayload(st) {
    var out = { injection: st.injection, analyte: st.analyte, transition: field(st.transition),
                mode: st.mode || "injection", kind: st.kind, start: "", end: "", apex: "", baseline: "", confirm: "",
                level_start: "", level_end: "" };
    if (st.kind === "integrate") { out.start = field(st.start); out.end = field(st.end); }
    if (st.kind === "integrate" && st.levels) { out.level_start = field(st.levels[0]); out.level_end = field(st.levels[1]); }
    if (st.kind === "apex") { out.apex = field(st.apex); }
    if (st.kind === "integrate" || st.kind === "apex") { out.baseline = field(st.baseline); }
    if (st.kind === "delete") { out.confirm = st.confirm ? "1" : ""; }
    return out;
  }

  /* the edit chart's span: the trace's full-resolution region, where its
     edges may lie, with a quarter of its width either side (within the
     trace), else the whole trace; y from 0 (or the lowest point) to the
     highest point of any trace in that span with room above, each end on
     two significant figures */
  function chartView(tr, traces) {
    var t = tr.t || [], x0 = t[0], x1 = t[t.length - 1];
    if (tr.full_res) {
      var pad = (tr.full_res[1] - tr.full_res[0]) / 4;
      x0 = Math.max(x0, tr.full_res[0] - pad);
      x1 = Math.min(x1, tr.full_res[1] + pad);
    }
    return { x: [x0, x1], y: spanY(traces || [tr], x0, x1) };
  }
  /* the count axis for the points of traces between x0 and x1: from 0 (or
     the lowest point) to the highest with room above, each end on two
     significant figures; what a zoomed chart's counts follow */
  function spanY(traces, x0, x1) {
    var lo = 0, hi = -Infinity;
    traces.forEach(function (o) {
      for (var i = 0; i < (o.t || []).length; i++) {
        if (o.t[i] >= x0 && o.t[i] <= x1) { lo = Math.min(lo, o.y[i]); hi = Math.max(hi, o.y[i]); }
      }
    });
    if (!(hi > lo)) { hi = lo + 1; }
    return [lo < 0 ? -roundUp(-lo) : 0, roundUp(hi + (hi - lo) * 0.08)];
  }
  /* the view a box drawn on the chart from (x0, y0) to (x1, y1) enlarges:
     {x, y} in either drawing direction, or null for a box no wider in time
     than least or with no height */
  function regionView(x0, y0, x1, y1, least) {
    var x = [Math.min(x0, x1), Math.max(x0, x1)], y = [Math.min(y0, y1), Math.max(y0, y1)];
    if (!(x[1] - x[0] > (least || 0) && y[1] > y[0])) { return null; }
    /* the counts on two significant figures, a box started on the zero line from zero */
    var lo = y[0] < 0 && -y[0] < (y[1] - y[0]) / 100 ? 0 : y[0];
    return { x: x, y: [lo < 0 ? -roundUp(-lo) : roundDown(lo), roundUp(y[1])] };
  }
  /* v rounded down to two significant figures */
  function roundDown(v) {
    if (!(v > 0)) { return v; }
    var m = Math.pow(10, Math.floor(Math.log(v) / Math.LN10) - 1);
    return parseFloat((Math.floor(parseFloat((v / m).toPrecision(12))) * m).toPrecision(12));
  }
  /* v rounded up to two significant figures, for the axis's top tick */
  function roundUp(v) {
    if (!(v > 0)) { return v; }
    var m = Math.pow(10, Math.floor(Math.log(v) / Math.LN10) - 1);
    return parseFloat((Math.ceil(parseFloat((v / m).toPrecision(12))) * m).toPrecision(12));
  }

  /* ── the overview thumbnail ───────────────────────────────────────────── */
  function r1(v) { return String(Math.round(v * 10) / 10); }
  /* one chromatogram as a small SVG: the thumbnail's envelope as a line,
     its integrated peak filled down to the baseline, the automatic peak
     dashed once edited; its state as classes (is-nd, is-fail, is-warn,
     is-missing, is-deleted, is-edited, is-pending). opts: w, h, pending. */
  function thumbSvg(th, opts) {
    opts = opts || {};
    var w = opts.w || 160, h = opts.h || 56;
    var cls = ["raw-spark"];
    if (knownState(th.state)) { cls.push("is-" + th.state); }
    if (th.deleted) { cls.push("is-deleted"); }
    if (th.edit === "edited") { cls.push("is-edited"); }
    if (th.edit === "pending" || opts.pending) { cls.push("is-pending"); }
    var out = '<svg class="' + cls.join(" ") + '" viewBox="0 0 ' + w + " " + h + '" preserveAspectRatio="none"' +
              ' aria-hidden="true" focusable="false">';
    var t = th.t || [], y = th.y || [];
    if (!t.length || !y.length) { return out + "</svg>"; }
    var t0 = t[0], t1 = t[t.length - 1], lo = 0, hi = -Infinity;
    for (var i = 0; i < y.length; i++) { lo = Math.min(lo, y[i]); hi = Math.max(hi, y[i]); }
    if (!(hi > lo)) { hi = lo + 1; }
    var span = t1 > t0 ? t1 - t0 : 1;
    function px(x) { return r1((x - t0) / span * w); }
    function py(v) { return r1(h - (v - lo) / (hi - lo) * h); }
    function region(peak, klass) {
      var pts = peakOutline(t, y, peak);
      if (!pts.length) { return ""; }
      var d = "M" + px(pts[0].x) + "," + py(pts[0].y);
      for (var k = 1; k < pts.length - 1; k++) { d += " L" + px(pts[k].x) + "," + py(pts[k].y); }
      return '<path class="' + klass + '" d="' + d + ' Z" vector-effect="non-scaling-stroke"/>';
    }
    if (th.auto) { out += region(th.auto, "raw-spark-auto"); }
    if (th.peak && !th.deleted) { out += region(th.peak, "raw-spark-area"); }
    var pts = [];
    for (var j = 0; j < t.length; j++) { pts.push(px(t[j]) + "," + py(y[j])); }
    return out + '<polyline class="raw-spark-line" points="' + pts.join(" ") +
           '" vector-effect="non-scaling-stroke"/></svg>';
  }

  /* ── the method's limits on a manual change (raw_preview.edit_problem) ── */
  function areaChangePct(autoArea, manualArea) {
    if (autoArea == null || manualArea == null || !(autoArea > 0)) { return null; }
    return Math.abs(manualArea - autoArea) / autoArea * 100.0;
  }
  /* value with the fewest decimals (one at least) that still reads below limit */
  function below(value, limit) {
    for (var places = 1; places < 10; places++) {
      var text = pyFixed(value, places);
      if (parseFloat(text) < limit) { return text; }
    }
    return pyRepr(value);
  }
  /* why the method refuses an edit, or null: a re-integration or another
     apex less than minChangePct % from the automatic area (no automatic area
     above 0: not judged), or with an S/N under minSn (unset: not judged; an
     S/N that cannot be read is refused while it is set) */
  function editProblem(kind, autoArea, manualArea, sn, minChangePct, minSn) {
    if (kind !== "integrate" && kind !== "apex") { return null; }
    var pct = areaChangePct(autoArea, manualArea);
    /* judged unrounded, but not on floating-point noise: 4.9999999999 % is a change AT 5 % */
    if (minChangePct != null && pct != null && parseFloat(pyFixed(pct, 9)) < minChangePct) {
      return "The change is under the method's smallest manual change of " + pyG(minChangePct) + " %: " +
             below(pct, minChangePct) + " %.";
    }
    if (minSn != null) {
      if (sn == null) { return "The peak's S/N cannot be read on this trace: process the run again."; }
      if (sn < minSn) {
        return "The peak's S/N " + below(sn, minSn) + " is under the method's smallest S/N for a manual peak, " +
               pyG(minSn) + ".";
      }
    }
    return null;
  }

  /* ── the dialog's live judgement, in raw_edit.decide's order and words ── */
  var STORED_BEFORE = "This trace was stored before it could be edited: process the run again.";
  var NO_SMOOTHING = "Set the compound's smoothing on the Integration tab, then process the run again.";
  var PREVIEW_FIELDS = { classic: ["smooth_points", "edge_points"], adaptive: ["smoothing"] };

  /* half the median spacing of the samples inside fullRes: how far past the
     region an edge set at its bound may sit */
  function edgeTolerance(t, fullRes) {
    var inside = [], steps = [];
    for (var i = 0; i < (t || []).length; i++) { if (t[i] >= fullRes[0] && t[i] <= fullRes[1]) { inside.push(t[i]); } }
    for (var k = 1; k < inside.length; k++) { steps.push(inside[k] - inside[k - 1]); }
    if (!steps.length) { return 0.0; }
    steps.sort(function (a, b) { return a - b; });
    var mid = Math.floor(steps.length / 2);
    return (steps.length % 2 ? steps[mid] : (steps[mid - 1] + steps[mid]) / 2.0) / 2.0;
  }
  function given(v, what) {
    if (v == null || String(v).replace(/^\s+|\s+$/g, "") === "") { throw new Error("Give the " + what + "."); }
    var n = typeof v === "number" ? v : Number(String(v).replace(/^\s+|\s+$/g, ""));
    if (isNaN(n) || !isFinite(n)) { throw new Error("The " + what + " is a number."); }
    return n;
  }
  function tracePreview(tr, start, end, baseline, levels, amp) {
    return previewPeak(tr.engine || "classic", tr.t, tr.y, start, end, baseline, tr.sigma,
                       { smooth_points: tr.smooth_points, edge_points: tr.edge_points, m: tr.smoothing,
                         levels: levels, amp: amp });
  }
  function measured(card, tr, start, end, baseline, levels, amp) {
    var full = tr.full_res, engine = tr.engine || "classic";
    if (!full) { throw new Error(STORED_BEFORE); }
    if (engine === "adaptive" && tr.smoothing == null) { throw new Error(NO_SMOOTHING); }
    var need = PREVIEW_FIELDS[engine] || [];
    for (var i = 0; i < need.length; i++) { if (tr[need[i]] == null) { throw new Error(STORED_BEFORE); } }
    var tol = edgeTolerance(tr.t, full);
    if (start < full[0] - tol || end > full[1] + tol) {
      throw new Error("The edges lie in the trace's full-resolution region, " + pyFixed(full[0], 3) + " to " +
                      pyFixed(full[1], 3) + " min. To go further, widen the method's window for " + shown(card) + ".");
    }
    try {
      return tracePreview(tr, start, end, baseline, levels, amp);
    } catch (err) {
      throw new Error("The peak cannot be measured between these edges: " + err.message + ".");
    }
  }
  /* what the card notes of a manual peak, never a refusal, in the server's
     words (raw_edit.notes): a drop's valley or a skim's height beside its
     parent past the method's limit */
  function peakNotes(manual, rules) {
    var out = [];
    if (manual.valley_share != null && rules.drop_valley_max_pct != null &&
        manual.valley_share > rules.drop_valley_max_pct) {
      out.push("The valley stands at " + pyFixed(manual.valley_share, 0) + " % of the smaller peak's height, " +
               "above the method's " + pyG(rules.drop_valley_max_pct) + " % for a perpendicular drop.");
    }
    if (manual.skim_share != null && rules.skim_ratio_pct != null && manual.skim_share > rules.skim_ratio_pct) {
      out.push("The peak is " + pyFixed(manual.skim_share, 0) + " % of its parent's height, above the method's " +
               pyG(rules.skim_ratio_pct) + " % for a tangent skim.");
    }
    return out;
  }
  /* the line's words the refusals name (raw_review.LINE_WORDS) */
  var LINE_WORDS = { valley: "valley to valley", drop: "perpendicular drop", flat: "flat baseline", skim: "tangent skim" };
  /* why levels set by hand are refused: outside the stored trace's lowest
     and highest count (raw_review.levels_outside, as a sentence); null */
  function levelsOutside(y, levels) {
    if (levels == null || !y.length) { return null; }
    var range = countRange({ y: y });
    if (levels[0] >= range[0] && levels[0] <= range[1] && levels[1] >= range[0] && levels[1] <= range[1]) { return null; }
    return "The baseline levels " + counts(levels[0]) + " and " + counts(levels[1]) + " lie outside the trace's range, " +
           counts(range[0]) + " to " + counts(range[1]) + " counts.";
  }
  /* a drop or a skim reading past the samples the stored trace keeps at
     full resolution is refused (raw_edit._within_reach) */
  function withinReach(tr, manual, baseline) {
    if ((baseline !== "drop" && baseline !== "skim") || tr.sigma == null) { return; }
    var t = tr.t, ix = readReach(tr.engine || "classic", t, tr.y, manual.s, manual.e, tr.smooth_points, tr.edge_points,
                                 tr.smoothing);
    var region = tr.full_res_reach || tr.full_res;
    if (region[0] <= t[ix[0]] && t[ix[1]] <= region[1]) { return; }
    if (!tr.full_res_reach) {
      throw new Error("This trace was stored before a " + LINE_WORDS[baseline] + " could be measured on it: process the run again.");
    }
    throw new Error("A " + LINE_WORDS[baseline] + " from these edges reads past the trace's full-resolution region, " +
                    pyFixed(region[0], 3) + " to " + pyFixed(region[1], 3) + " min: choose other edges or another baseline.");
  }
  /* an edge nearer its apex than the method's edges past the tail, in the
     peak's standard deviations on that side: the automatic peak's width
     when the manual apex lies within it at half height, else the manual
     peak's own; never a refusal (raw_edit.edge_notes) */
  function edgeNotes(tr, autoBase, manual, rules) {
    var engine = tr.engine || "classic", apex = manual.apex;
    if (apex == null) { return []; }
    var widths = function (measured) {
      try { return halfWidths(engine, tr.t, tr.y, measured, tr.smooth_points, tr.smoothing); } catch (err) { return [null, null]; }
    };
    var auto = tr.auto || tr.peak || {}, w = [null, null];
    if (auto.start != null && auto.end != null && autoBase) {
      var ref = null;
      try { ref = tracePreview(tr, auto.start, auto.end, autoBase); } catch (err) { ref = null; }
      if (ref) {
        w = widths(ref);
        if (!(w[0] != null && w[1] != null && ref.apex - w[0] <= apex && apex <= ref.apex + w[1])) { w = [null, null]; }
      }
    }
    if (w[0] == null && w[1] == null) { w = widths(manual); }
    var w0 = w[0] != null ? w[0] : w[1], w1 = w[1] != null ? w[1] : w[0], limit = rules.edge_sigma, out = [];
    /* a distance: a shoulder found with its apex past its own edge lies that near it */
    [["start", Math.abs(apex - manual.start), w0], ["end", Math.abs(manual.end - apex), w1]].forEach(function (side) {
      if (side[2] == null || !(side[2] > 0) || limit == null) { return; }
      var sigmas = side[1] / (side[2] / HALF_WIDTH_SIGMA);
      if (sigmas < limit) {
        out.push("The " + side[0] + " lies " + below(sigmas, limit) + " sigma from the apex, under the method's " +
                 pyG(limit) + " sigma for an edge.");
      }
    });
    return out;
  }
  /* the trapezoid over the automatic peak's edges on the method's baseline:
     what the manual area is judged against; null when it cannot be measured */
  function autoArea(tr, baseline) {
    var auto = tr.auto || tr.peak || {};
    if (auto.start == null || auto.end == null) { return null; }
    try { return tracePreview(tr, auto.start, auto.end, baseline).area; } catch (err) { return null; }
  }
  /* the automatic peak's own stored area (an edited trace's stored "auto"):
     what another apex chosen as found is judged against; null without one */
  function storedAutoArea(tr) {
    var auto = tr.auto || tr.peak || {};
    return auto.area == null ? null : auto.area;
  }
  /* an apex choice names its peak by the peak's apex, never by the edges
     that hold it (a shoulder can top out on its own edge, or just outside
     it), as raw_review does: the samples either side of the apex its local
     spacing is read over */
  var APEX_SPACING_POINTS = 2;
  /* half the median spacing of the samples within APEX_SPACING_POINTS either
     side of the sample of t nearest apex (the first of two equally near):
     how far a chosen apex may lie from a peak's own; 0 with fewer than two */
  function apexTolerance(t, apex) {
    t = t || [];
    if (t.length < 2) { return 0.0; }
    var near = 0, k;
    for (k = 1; k < t.length; k++) { if (Math.abs(t[k] - apex) < Math.abs(t[near] - apex)) { near = k; } }
    var lo = Math.max(near - APEX_SPACING_POINTS, 0), hi = Math.min(near + APEX_SPACING_POINTS, t.length - 1);
    var steps = [];
    for (k = lo; k < hi; k++) { steps.push(t[k + 1] - t[k]); }
    steps.sort(function (a, b) { return a - b; });
    var mid = Math.floor(steps.length / 2);
    return (steps.length % 2 ? steps[mid] : (steps[mid - 1] + steps[mid]) / 2.0) / 2.0;
  }
  /* the index in apexes of the one nearest apex, no further than tol from it;
     -1 when none is that near; two equally near name no peak (thrown) */
  function nearestApex(apexes, apex, tol) {
    var best = -1, bestD = null, shared = false;
    for (var i = 0; i < apexes.length; i++) {
      if (apexes[i] == null) { continue; }
      var d = Math.abs(apexes[i] - apex);
      if (d > tol) { continue; }
      if (best < 0 || d < bestD) { best = i; bestD = d; shared = false; } else if (d === bestD) { shared = true; }
    }
    if (shared) { throw new Error("Two peaks share the apex at " + pyFixed(apex, 3) + " min: choose one by its edges instead."); }
    return best;
  }
  function matchCandidate(tr, apex) {
    var cs = (tr.candidates || []).filter(function (c) { return c.start != null && c.end != null; });
    var i = nearestApex(cs.map(function (c) { return c.apex; }), apex, apexTolerance(tr.t, apex));
    return i < 0 ? null : cs[i];
  }
  /* the quantifier's peak is stored deleted or with no area (raw_edit's no-peak case) */
  function quantHasNoPeak(quant) {
    var peak = (quant && quant.peak) || {};
    return !!(!quant || quant.deleted || peak.deleted || !peak.area);
  }
  /* an edit of one trace of a card judged as the server will judge it:
     {problem: the refusal text or null, preview (another apex as found:
     its candidate's own measures, apexPreview), auto_area (the trapezoid
     over the automatic edges; another apex as found: the automatic peak's
     stored area), change (%), start, end: the edges measured (a
     re-integration's on the samples the worker takes; another apex's, its
     candidate's)}. edit: {kind, start,
     end, apex, baseline ("" for the method's)}. A deletion or an undo is
     not judged here. */
  function judge(card, tr, edit) {
    var res = { problem: null, preview: null, auto_area: null, change: null, start: null, end: null, notes: [] };
    if (edit.kind !== "integrate" && edit.kind !== "apex") { return res; }
    try {
      var start, end, apex, asFound = false;
      if (edit.kind === "integrate") {
        start = given(edit.start, "start");
        end = given(edit.end, "end");
        if (!(start < end)) { throw new Error("The start is before the end."); }
      } else {
        apex = given(edit.apex, "apex");
      }
      if (edit.baseline && BASELINES.indexOf(edit.baseline) < 0) { throw new Error("The baseline is Valley, Drop, Flat or Skim."); }
      /* a qualifier is read only beside a quantifier peak: said before anything of the trace is */
      if (tr !== card.quant && quantHasNoPeak(card.quant)) {
        throw new Error("The quantifier has no peak in " + card.injection + ": a qualifier edit would have no effect.");
      }
      if (!card.method_baseline) { throw new Error("The method's Integration names no baseline."); }
      /* the compound's rules for a manual peak: its fewest points, its peak
         search amplitude, its limits for a drop and a skim */
      if (card.rules_problem) { throw new Error(card.rules_problem); }
      var rules = card.rules || {}, amp = rules.search_amp_sn;
      var base = edit.baseline || card.method_baseline, manual, sn;
      if (edit.kind === "integrate") {
        var levels = edit.levels == null ? null : edit.levels;
        measured(card, tr, start, end, base, levels, amp);
        /* kept as the worker stores them, each on its nearest sample */
        res.start = tr.t[snapIndex(tr.t, start, tr.full_res)];
        res.end = tr.t[snapIndex(tr.t, end, tr.full_res)];
        manual = tracePreview(tr, res.start, res.end, base, levels, amp);
        /* the worker's order: the levels, then the fewest points */
        var outside = levelsOutside(tr.y, levels);
        if (outside) { throw new Error(outside); }
        var points = manual.e - manual.s + 1;
        if (rules.min_peak_points != null && points < rules.min_peak_points) {
          throw new Error("A manual peak needs at least " + rules.min_peak_points + " points between its edges: " +
                          points + " here.");
        }
        withinReach(tr, manual, base);
        sn = manual.sn;
      } else {
        if (!tr.candidates) { throw new Error("Another apex is chosen only on a single peak."); }
        var chosen = matchCandidate(tr, apex);
        if (!chosen) {
          throw new Error("No peak of " + card.injection + " / " + shown(card) + " has its apex at " + pyFixed(apex, 3) +
                          " min: choose one of its candidates.");
        }
        manual = measured(card, tr, chosen.start, chosen.end, base, null, amp);
        res.start = chosen.start;
        res.end = chosen.end;
        if (edit.baseline) {
          withinReach(tr, manual, base);
          sn = manual.sn;
        } else {
          /* as found: the candidate's own measures, the peak the worker
             replays, judged against the automatic peak's own area; none
             S/N being no limit */
          manual = apexPreview(tr.t, chosen);
          sn = chosen.sn != null ? chosen.sn : Infinity;
          asFound = true;
        }
      }
      res.preview = manual;
      var limits = card.limits || {};
      if (limits.min_manual_change_pct == null) { throw new Error("The method's limits on a manual change are not numbers."); }
      res.auto_area = asFound ? storedAutoArea(tr) : autoArea(tr, card.method_baseline);
      res.change = areaChangePct(res.auto_area, manual.area);
      res.problem = editProblem(edit.kind, res.auto_area, manual.area, sn, limits.min_manual_change_pct,
                                limits.min_manual_sn);
      if (res.problem === null) { res.notes = peakNotes(manual, rules).concat(edgeNotes(tr, card.method_baseline, manual, rules)); }
    } catch (err) {
      res.problem = err.message;
    }
    return res;
  }

  /* ── what the tab says of the run ─────────────────────────────────────── */
  function shortError(error) {
    var lines = String(error || "").replace(/^\s+|\s+$/g, "").split(/\r\n|[\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029]/);
    var line = (lines[0] || "").replace(/^\s+|\s+$/g, "");
    return line.length <= 200 ? line : line.slice(0, 197).replace(/\s+$/, "") + "...";
  }
  /* the banner over the tab: the run's failed processing, a retry, or edits
     waiting for it to be processed again; null when there is nothing to say */
  function banner(data) {
    var f = data.failure;
    if (f && f.status === "failed") {
      return { cls: "is-fail", text: "The run's last processing failed: " + (shortError(f.error) || "no reason was recorded.") };
    }
    if (f && f.status === "retrying") {
      return { cls: "is-warn", text: "The run is being processed again after a failure, attempt " + (f.attempts || 1) +
                                     (f.error ? ": " + shortError(f.error) : ".") };
    }
    if (data.waiting) {
      var n = data.edited || 0;
      return { cls: "is-warn", text: "Edits are waiting for the run to be processed again" +
                                     (n ? ": " + n + (n === 1 ? " trace" : " traces") + " edited." : ".") };
    }
    return null;
  }

  /* ── the page's address ───────────────────────────────────────────────── */
  function params(search) {
    var out = {};
    String(search || "").replace(/^\?/, "").split("&").forEach(function (kv) {
      if (!kv) { return; }
      var i = kv.indexOf("="), k = i < 0 ? kv : kv.slice(0, i), v = i < 0 ? "" : kv.slice(i + 1);
      try { out[decodeURIComponent(k)] = decodeURIComponent(v.replace(/\+/g, " ")); } catch (e) { /* malformed: skipped */ }
    });
    return out;
  }
  /* the edit as the server says it was posted (posted_<field>): its trace
     ("" the quantifier), kind, edges, apex, line and levels, read when the
     browser kept none of its own; null when the address names none */
  var POSTED_KINDS = ["integrate", "apex", "delete", "revert"];
  function postedEdit(p) {
    if (POSTED_KINDS.indexOf(p.posted_kind) < 0) { return null; }
    var number = function (k) { return p[k] == null || p[k] === "" || isNaN(Number(p[k])) ? null : Number(p[k]); };
    var ls = number("posted_level_start"), le = number("posted_level_end");
    return { transition: p.posted_transition || "", kind: p.posted_kind, start: number("posted_start"),
             end: number("posted_end"), apex: number("posted_apex"),
             baseline: BASELINES.indexOf(p.posted_baseline) >= 0 ? p.posted_baseline : "",
             levels: ls != null && le != null ? [ls, le] : null };
  }
  /* the card the edit's redirect names (open=<injection>|<analyte>), with
     the refusal it carries, the method's notes on the edit made (notes=,
     one per line, read only when the edit was made) and the edit as
     posted (a kind and a line the card knows); null when there is none */
  function openTarget(search) {
    var p = params(search), open = p.open || "", bar = open.indexOf("|");
    if (bar < 1 || bar === open.length - 1) { return null; }
    return { injection: open.slice(0, bar), analyte: open.slice(bar + 1),
             error: p.msg_type === "error" ? (p.detail || "") : "",
             notes: p.msg_type === "ok" && p.notes ? p.notes.split("\n").filter(function (n) { return n; }) : [],
             posted: postedEdit(p) };
  }
  /* the address without open=, the notes and the edit as posted, so a
     reload does not open the dialog again */
  function withoutOpen(search) {
    var kept = String(search || "").replace(/^\?/, "").split("&").filter(function (kv) {
      var k = kv.split("=")[0];
      return kv && k !== "open" && k !== "notes" && k.indexOf("posted_") !== 0;
    });
    return kept.length ? "?" + kept.join("&") : "";
  }

  /* the injection's sample type: its thumbnail's, else its entry in the
     list by injection; "" when the overview does not show it */
  function injectionType(data, injection, analyte) {
    var th = (data.thumbs || []).filter(function (x) { return x.injection === injection && x.analyte === analyte; })[0];
    if (th && th.type) { return th.type; }
    var it = data.mode === "compound" ? null : (data.list || []).filter(function (x) { return x.name === injection; })[0];
    return (it && it.type) || "";
  }
  /* the sample type of a calibrator, as the run's roles name it */
  var CALIBRATOR = "CAL";
  /* what deleting the peak of trace `index` (0 the quantifier) does, said
     before it is made: a qualifier's result reads N.C.; the quantifier's
     reads N.D., an isotope standard's natives lose their concentration, and
     a calibrator comes off the curve it was on */
  /* an analyte is keyed by its keyword (the traces' and edits'); it is
     shown by its label, the compound library's display name its rows carry */
  function shown(x) { return (x && (x.label || x.analyte)) || ""; }
  /* the label the tab's data gives an analyte's keyword; the keyword itself
     when none does */
  function labelIn(data, analyte) {
    var all = (data.thumbs || []).concat(data.list || []);
    for (var i = 0; i < all.length; i++) {
      if ((all[i].analyte || all[i].name) === analyte && all[i].label) { return all[i].label; }
    }
    return analyte;
  }
  function deleteWarning(card, index, type, deleted) {
    if (index > 0) { return "The result reads N.C. The ion ratio comes from the qualifiers left."; }
    if (deleted) { return "The peak is deleted."; }
    var cal = type === CALIBRATOR, name = shown(card);
    if (card.is_standard && !(card.natives || []).length) {
      return name + " is an isotope standard. Deleting its peak in " + card.injection +
             " leaves its recovery there unjudged.";
    }
    if ((card.natives || []).length) {
      return "Deleting the isotope standard peak of " + name + " in " + card.injection + " leaves " +
             card.natives.join(", ") + " without a concentration." + (cal ? " " + card.injection + " comes off their curves." : "");
    }
    return name + " reads N.D. in " + card.injection + "." +
           (cal ? " " + card.injection + " comes off the " + name + " curve." : "");
  }

  /* whether deleting the quantifier's peak is confirmed before it is posted:
     an isotope standard (the card says so), or a deletion the server has
     already asked to have confirmed */
  function confirmsDelete(card, index, armed) {
    return index === 0 && (!!card.is_standard || (card.natives || []).length > 0 || !!armed);
  }

  /* ── the card ─────────────────────────────────────────────────────────── */
  /* the change of a manual area from the automatic one, in %, signed; null
     without an automatic area above 0 */
  function signedChange(autoArea, manualArea) {
    if (autoArea == null || manualArea == null || !(autoArea > 0)) { return null; }
    return (manualArea - autoArea) / autoArea * 100.0;
  }
  function signedPct(v) { return (v < 0 ? "−" : v > 0 ? "+" : "") + pyFixed(Math.abs(v), 1) + " %"; }
  /* how the stored peak of a trace was integrated: "Automatic · valley to
     valley", "Manual · flat baseline at 4,000" (the line in the panel's
     words, the card's "line"), "Peak deleted"; an edit kept with no effect
     left the automatic peak */
  function integrationText(tr) {
    tr = tr || {};
    if (tr.deleted) { return "Peak deleted"; }
    var manual = tr.edit === "edited" || (tr.auto != null && tr.edit !== "no_effect");
    return (manual ? "Manual" : "Automatic") + (tr.line ? " · " + tr.line : "");
  }
  /* the readout strip, [label, value, the line under the value]: the area
     (once edited, the automatic area and the change under it), retention
     time, S/N, ion ratio with its expected value, concentration with its
     unit, and how the quantifier's peak was integrated */
  function readout(a) {
    var q = a.quant || {}, auto = q.auto || {}, under = "";
    var change = q.auto && !q.deleted ? signedChange(auto.area, a.area) : null;
    if (change != null) { under = "automatic " + num(auto.area, 0) + " · change " + signedPct(change); }
    var conc = a.state === "nd" ? "N.D." : (a.conc == null ? "—" : num(a.conc) + (a.unit ? " " + a.unit : ""));
    var ion = a.ion_ratio == null ? "—" : num(a.ion_ratio) + (a.ion_expected == null ? "" : ", expected " + num(a.ion_expected));
    return [["Area", num(a.area, 0), under], ["Retention time", a.rt == null ? "—" : num(a.rt) + " min", ""],
            ["S/N", num(a.sn, 1), ""], ["Ion ratio", ion, ""], ["Concentration", conc, ""],
            ["Integration", integrationText(q), ""]];
  }
  /* the Details disclosure's [label, value] pairs: the measures that
     explain the peak where it has them, the engine always named, and the
     isotope standard it is read against */
  function details(a) {
    var rows = [["Engine", a.engine || "Classic"]];
    if (a.smoothing_points != null) {
      rows.push(["Smoothing", a.smoothing_points + " points" + (a.smoothing_from ? ", from " + a.smoothing_from : "")]);
    }
    if (a.fwhm_s != null) { rows.push(["FWHM", num(a.fwhm_s, 1) + " s"]); }
    if (a.tailing != null) { rows.push(["Tailing", num(a.tailing, 2)]); }
    if (a.plates != null) { rows.push(["Plates", num(a.plates, 0)]); }
    if (a.qual_sn != null) { rows.push(["Qualifier S/N", num(a.qual_sn, 1)]); }
    if (a.file_transition) { rows.push(["File transition", a.file_transition]); }
    rows.push(["Isotope standard", a.is ? shown(a.is) : "—"]);
    return rows;
  }
  var OVERFLOW_TEXT = "Overflow at the apex: the stored value is above the file's number range.";
  /* the fit's state by its short name: "Fit refused", "Pair fit failed" */
  function fitName(text) { return String(text || "").split(":")[0]; }
  /* the flags under the readout as chips, {cls: a badge class, text}: the
     result's flags (a failure on a row that failed, else a warning: the
     row carries no kind of its own), the overflow, the fit by a short name,
     and what the method notes of a manual peak drawn (notes: a warning) */
  function flagChips(a, notes) {
    var out = (a.flags || []).map(function (f) { return { cls: a.state === "fail" ? "badge-fail" : "badge-warn", text: f }; });
    if (a.overflowed) { out.push({ cls: "badge-fail", text: "Overflow" }); }
    if (a.fit_text) { out.push({ cls: "badge-warn", text: fitName(a.fit_text) }); }
    (notes || []).forEach(function (n) { out.push({ cls: "badge-warn", text: n }); });
    return out;
  }
  function chipItems(chips) {
    return chips.map(function (c) { return '<li class="badge ' + c.cls + '">' + esc(c.text) + "</li>"; }).join("");
  }
  /* the long texts behind the chips and the peak's note, for Details */
  function longNotes(a) {
    var out = [];
    if (a.overflowed) { out.push(OVERFLOW_TEXT); }
    if (a.fit_text && a.fit_text !== fitName(a.fit_text)) { out.push(a.fit_text); }
    if (a.note) { out.push(a.note); }
    return out;
  }

  /* the readout strip and the flags (the notes on a manual peak drawn
     join them), under the charts; a line for what the card says it did */
  function cardHead(a) {
    var h = '<dl class="raw-readout">';
    readout(a).forEach(function (c) {
      h += "<div><dt>" + esc(c[0]) + "</dt><dd>" + esc(c[1]) +
           (c[2] ? '<span class="raw-under">' + esc(c[2]) + "</span>" : "") + "</dd></div>";
    });
    h += "</dl>";
    h += '<ul class="raw-flags" data-role="flags">' + chipItems(flagChips(a)) + "</ul>";
    return h + '<p class="raw-note" data-role="said" aria-live="polite"></p>';
  }
  /* the Details disclosure: the rest of the values, the long notes and the
     curve the concentration was read on, a button to the Calibration tab */
  function cardDetail(a) {
    var h = '<details class="raw-details"><summary class="btn-help is-term">Details</summary><dl class="raw-details-list">';
    details(a).forEach(function (kv) { h += "<dt>" + esc(kv[0]) + "</dt><dd>" + esc(kv[1]) + "</dd>"; });
    h += "</dl>";
    longNotes(a).forEach(function (n) { h += '<p class="raw-note">' + esc(n) + "</p>"; });
    if (a.conc != null) {
      h += '<p class="raw-curve">Quantified against the run\'s curve ' +
           '<a class="btn-sm btn-secondary" href="?tab=calibration">Calibration</a></p>';
    }
    return h + "</details>";
  }

  /* the card's body as the dialog draws it, top to bottom: the server's
     refusal (flash), the Trace switch, the trace line, the charts, the
     readout strip and the flags, the edit's boxes and preview (editable)
     and Details; the edit itself is made on the chart and its menu */
  /* the chart's zoom tools: in, out, a region drawn as a box, the whole window */
  function zoomIcon(path) {
    return '<svg viewBox="0 0 16 16" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" ' +
           'stroke-width="1.6" stroke-linecap="round">' + path + "</svg>";
  }
  var LENS = '<circle cx="6.5" cy="6.5" r="4.5"/><path d="M10 10l4.5 4.5"/>';
  var ZOOM_BAR = '<div class="raw-zoom" role="toolbar" aria-label="Zoom the chart" data-role="zoom">' +
    [["in", "Zoom in", LENS + '<path d="M4.5 6.5h4M6.5 4.5v4"/>'],
     ["out", "Zoom out", LENS + '<path d="M4.5 6.5h4"/>'],
     ["region", "Zoom to a region: drag a box on the chart", '<rect x="2" y="2" width="12" height="12" stroke-dasharray="2 2"/>' +
      '<path d="M6 8h4M8 6v4"/>'],
     ["full", "Back to the whole window", '<path d="M6 2H2v4M10 2h4v4M6 14H2v-4M10 14h4v-4"/>']].map(function (b) {
      return '<button type="button" class="btn btn-sm btn-secondary" data-zoom="' + b[0] + '" title="' + b[1] +
             '" aria-label="' + b[1] + '"' + (b[0] === "region" ? ' aria-pressed="false"' : "") + ">" + zoomIcon(b[2]) +
             "</button>";
    }).join("") + "</div>";
  function cardBody(a, traces, index, editable, flash) {
    var h = "";
    if (flash) { h += '<p class="raw-refusal" role="alert">' + esc(flash) + "</p>"; }
    if (traces.length > 1) {
      h += seg("Trace", traces.map(function (tr, i) {
        return [String(i), i === 0 ? "Quantifier" : "Qualifier" + (traces.length > 2 ? " " + i : "")];
      }), String(index));
    }
    h += '<p class="raw-trace-line" data-role="trace-line"></p>';
    h += '<div class="raw-charts">' + ZOOM_BAR + '<div class="raw-chart raw-chart-edit" data-role="wrap">' +
         '<canvas data-role="traces" tabindex="0" role="application" aria-label="The trace, its peak and baseline. ' +
         'Menu key for its actions."></canvas></div>';
    h += "</div>";
    h += cardHead(a);
    if (editable) {
      h += '<div class="raw-edit" data-role="edit">' +
           '<div class="raw-pane" data-pane="integrate">' +
             '<div class="raw-edges">' +
               '<label>Start, min <input type="number" step="any" data-edge="start" /></label>' +
               '<label>End, min <input type="number" step="any" data-edge="end" /></label>' +
               '<label hidden="hidden">Start level, counts <input type="number" step="any" data-level="start" /></label>' +
               '<label hidden="hidden">End level, counts <input type="number" step="any" data-level="end" /></label>' +
             "</div>" +
             '<p class="raw-preview" data-role="preview" aria-live="polite"></p>' +
             '<p class="raw-note" data-role="edge-note" aria-live="polite"></p>' +
             '<p class="raw-refusal" data-role="problem" role="alert"></p>' +
           "</div>" +
           '<div class="raw-pane" data-pane="delete" hidden="hidden"><p class="raw-warning" data-role="delete-text"></p></div>' +
           '<div class="raw-pane" data-pane="revert" hidden="hidden"><p>Back to the automatic integration.</p></div>' +
           "</div>";
    }
    h += cardDetail(a);
    return h;
  }

  /* ── an edit waiting for the run, and one the server refused ──────────── */
  /* what the card draws of a trace's edit while the run has not been
     processed since (the card's pending_edit), or null: {kind, start, end,
     apex, baseline ("" for the method's), levels, preview: the measure the
     shading is drawn from, or null}. A re-integration on its edges and
     line as the review previews it; another apex on its candidate's edges
     (as found, the candidate's own measures); an undo the automatic peak;
     a deletion no peak. */
  function pendingEdges(tr, card) {
    var pe = tr && tr.edit === "pending" ? tr.pending_edit : null;
    if (!pe) { return null; }
    var out = { kind: pe.kind, start: null, end: null, apex: pe.apex == null ? null : pe.apex,
                baseline: pe.baseline || "", levels: pe.levels || null, preview: null };
    var amp = ((card && card.rules) || {}).search_amp_sn, line = out.baseline || (card && card.method_baseline);
    if (pe.kind === "revert") {
      var au = tr.auto || {};
      if (au.start != null && au.end != null) {
        out.start = au.start;
        out.end = au.end;
        if (au.base_start != null && au.base_end != null) {
          out.preview = { s: nearest(tr.t, au.start), e: nearest(tr.t, au.end), base_start: au.base_start,
                          base_end: au.base_end, area: au.area == null ? null : au.area };
        }
      }
      return out;
    }
    try {
      if (pe.kind === "integrate") {
        out.start = pe.start;
        out.end = pe.end;
        out.preview = tracePreview(tr, pe.start, pe.end, line, out.levels, amp);
      } else if (pe.kind === "apex") {
        var c = matchCandidate(tr, pe.apex);
        if (c) {
          out.start = c.start;
          out.end = c.end;
          out.preview = out.baseline ? tracePreview(tr, c.start, c.end, out.baseline, null, amp) : apexPreview(tr.t, c);
        }
      }
    } catch (err) {
      out.preview = null;                 /* the edges alone, where the trace cannot be measured */
    }
    return out;
  }
  /* the edit the card opens on again after the server refused it (the edit
     remembered when it was posted), for the trace it was made on: a
     re-integration or another apex on the edges posted, judged again; a
     deletion to confirm; null for anything else */
  function refusedEdit(last, error, transition) {
    if (!last || !error || last.transition !== transition) { return null; }
    if (last.kind === "integrate" || last.kind === "apex") {
      return { mode: "integrate", kind: last.kind, start: last.start == null ? null : last.start,
               end: last.end == null ? null : last.end, apex: last.apex == null ? null : last.apex,
               baseline: last.baseline || "", levels: last.levels || null, touched: true };
    }
    return last.kind === "delete" ? { mode: "delete", armed: true } : null;
  }

  /* ── Previous and Next ───────────────────────────────────────────────── */
  /* the thumbnail step places from this one in the overview's order, a
     chromatogram with no trace passed over; null at either end */
  function neighbour(thumbs, injection, analyte, step) {
    var list = (thumbs || []).filter(function (th) { return th.state !== "missing"; });
    for (var i = 0; i < list.length; i++) {
      if (list[i].injection === injection && list[i].analyte === analyte) {
        var j = i + step;
        return j >= 0 && j < list.length ? list[j] : null;
      }
    }
    return null;
  }
  /* the step a key takes: PageUp -1, PageDown +1, none in a box being typed in */
  function pageStep(key, tag) {
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(String(tag || "").toUpperCase())) { return 0; }
    return key === "PageUp" ? -1 : key === "PageDown" ? 1 : 0;
  }

  /* ── the chart's gestures: handles, the menu's entries, the keys ─────── */
  /* the smoothed signal of a stored trace as its engine reads it */
  function traceSignal(tr) {
    var y = tr.y || [], engine = tr.engine || "classic", n = null;
    try {
      n = engine === "adaptive" ? adaptiveSmoothing(y, Math.max(toInt(tr.smoothing), 1))
                                : classicSmoothing(y, tr.smooth_points);
    } catch (err) { n = null; }
    return memo(y, n);
  }
  /* the lowest and highest count of the stored trace: where a level set by
     hand may lie (raw_review.levels_outside) */
  function countRange(tr) {
    var y = tr.y || [], lo = Infinity, hi = -Infinity;
    for (var i = 0; i < y.length; i++) { lo = Math.min(lo, y[i]); hi = Math.max(hi, y[i]); }
    return y.length ? [lo, hi] : null;
  }
  function clampTo(v, range) { return range ? Math.max(range[0], Math.min(range[1], v)) : v; }
  /* the indices [lo, hi] of the samples inside the full-resolution region */
  function fullIndices(t, fullRes) {
    var lo = -1, hi = -1;
    for (var i = 0; i < (t || []).length; i++) {
      if (!fullRes || (t[i] >= fullRes[0] && t[i] <= fullRes[1])) { if (lo < 0) { lo = i; } hi = i; }
    }
    return lo < 0 ? null : [lo, hi];
  }

  /* a handle dragged, or double-clicked: h {held "start", "end" or "line",
     t, fullRes, start, end, levels [left, right] (the line's values at the
     edges as drawn), manual [left, right] (a level set by hand), baseline,
     signal(start, end) (the line's values at those edges with no level set
     by hand), range (the counts a level may take), from {start, end, x}
     (the line's edges and the pointer's time when it was pressed)}; p {x,
     y (the pointer's time and count), axis ("x" sideways, "y" up or down),
     shift (the level kept on the signal), reset (a double-click)}. Sideways
     an edge moves to its sample (dragIndex), a level not set by hand
     following the signal; up or down that end's level is the pointer's
     count, inside the trace's range (flat: both ends, the line kept
     level); the line moves both edges by the same samples. Gives {start,
     end, levels, manual}. */
  function handleDrag(h, p) {
    var start = h.start, end = h.end, manual = [!!(h.manual || [])[0], !!(h.manual || [])[1]];
    var levels = (h.levels || [null, null]).slice(), side = h.held === "start" ? 0 : h.held === "end" ? 1 : -1;
    var flat = h.baseline === "flat";
    function onSignal(k) { if (flat || k < 0) { manual = [false, false]; } else { manual[k] = false; } }
    if (p.reset || p.shift) {
      onSignal(side);
    }
    if (!p.reset && side >= 0 && p.axis === "y" && !p.shift) {
      var v = clampTo(p.y, h.range);
      if (flat) { manual = [true, true]; levels = [v, v]; } else { manual[side] = true; levels[side] = v; }
    } else if (!p.reset && side >= 0 && p.axis === "x") {
      var i = dragIndex(h.t, p.x, h.fullRes, h.held, start, end);
      if (i >= 0) { if (side === 0) { start = h.t[i]; } else { end = h.t[i]; } }
    } else if (!p.reset && side < 0 && h.from) {
      var span = fullIndices(h.t, h.fullRes), a = snapIndex(h.t, h.from.start, null), b = snapIndex(h.t, h.from.end, null);
      var to = snapIndex(h.t, h.from.start + (p.x - h.from.x), h.fullRes);
      if (span && to >= 0) {
        to = Math.max(span[0], Math.min(to, span[1] - (b - a)));
        start = h.t[to];
        end = h.t[to + (b - a)];
      }
    }
    var sig = (manual[0] && manual[1]) ? null : h.signal(start, end);
    for (var k = 0; k < 2; k++) { if (!manual[k]) { levels[k] = sig ? sig[k] : null; } }
    return { start: start, end: end, levels: levels, manual: manual };
  }
  /* the levels posted for the line drawn through `levels` at the edges
     start and end, or null with none set by hand: under a drop the line's
     values at the pair's outer edges (bounds), which the engine reads,
     each kept inside range (the trace's counts, where the server takes a
     level), so the line the preview draws is the one posted */
  function postedLevels(baseline, start, end, levels, manual, bounds, range) {
    if (!manual || !(manual[0] || manual[1]) || !levels || levels[0] == null || levels[1] == null) { return null; }
    if (baseline === "drop" && bounds && end > start) {
      return [clampTo(interp(bounds[0], start, end, levels[0], levels[1]), range),
              clampTo(interp(bounds[1], start, end, levels[0], levels[1]), range)];
    }
    return [clampTo(levels[0], range), clampTo(levels[1], range)];
  }

  /* the peak search's slope and smoothing when none is given
     (raw_preview.REVIEW_DEFAULTS) */
  var DEFAULT_SEARCH_SLOPE = 0.7, DEFAULT_SEARCH_SMOOTH_PCT = 50.0;
  /* the automatic peak's full width at half its height, in points of the
     full-resolution region (its mean spacing), measured on the method's
     line; null when it cannot be read */
  function autoWidthPoints(card, tr, span) {
    var auto = tr.auto || tr.peak || {}, t = tr.t || [];
    if (auto.start == null || auto.end == null || !(span[1] > span[0])) { return null; }
    var w;
    try {
      var ref = tracePreview(tr, auto.start, auto.end, card.method_baseline);
      w = halfWidths(tr.engine || "classic", t, tr.y || [], ref, tr.smooth_points, tr.smoothing);
    } catch (err) { return null; }
    var full = w[0] != null && w[1] != null ? w[0] + w[1] : w[0] != null ? 2 * w[0] : w[1] != null ? 2 * w[1] : null;
    var step = (t[span[1]] - t[span[0]]) / (span[1] - span[0]);
    return full != null && full > 0 && step > 0 ? full / step : null;
  }
  /* the mean of y over n points centred on i, cut at the trace's ends,
     each point once */
  function movingMean(y, n) {
    var seen = {}, before = Math.floor((n - 1) / 2);
    return function (i) {
      if (!seen.hasOwnProperty(i)) {
        var a = Math.max(i - before, 0), b = Math.min(i - before + n - 1, y.length - 1);
        seen[i] = mean(y.slice(a, b + 1));
      }
      return seen[i];
    };
  }
  /* another peak around the cursor at time `at`, the method's peak search:
     with W the automatic peak's width at half height in points, the raw
     signal is smoothed over the search smoothing's share of W (at least
     one point); from the cursor's sample that signal is climbed to its
     top, then followed down each side while it falls, inside the
     full-resolution region; the peak, measured on the method's line, is
     kept only when its S/N reaches the peak search amplitude and, the
     source's rule being for a peak of unit height, its derivative falls
     across the top by more than its height above the line times the
     search slope over W squared. With no automatic width to read, the engine's
     smoothing is climbed and no slope is asked. {start, end, apex, area,
     sn}, or null */
  function addAt(card, tr, at) {
    if (at == null || !tr || !tr.full_res) { return null; }
    var t = tr.t || [], span = fullIndices(t, tr.full_res), rules = (card && card.rules) || {};
    if (!span || at < tr.full_res[0] || at > tr.full_res[1]) { return null; }
    var width = autoWidthPoints(card || {}, tr, span), sm;
    if (width == null) {
      sm = traceSignal(tr);
    } else {
      var pct = rules.search_smooth_pct == null ? DEFAULT_SEARCH_SMOOTH_PCT : rules.search_smooth_pct;
      sm = movingMean(tr.y || [], Math.max(1, Math.round(pct / 100.0 * width)));
    }
    var lo = span[0], hi = span[1], j = snapIndex(t, at, tr.full_res);
    if (j < hi && sm(j + 1) > sm(j)) { while (j < hi && sm(j + 1) > sm(j)) { j++; } }
    else { while (j > lo && sm(j - 1) > sm(j)) { j--; } }
    /* the fall of the smoothed derivative (a central difference) across
       the top, where it crosses zero */
    var fall = null;
    if (width != null) {
      if (j <= 0 || j >= t.length - 1) { return null; }
      var d = function (i) { return (sm(Math.min(i + 1, t.length - 1)) - sm(Math.max(i - 1, 0))) / 2.0; };
      var k = d(j) > 0 ? j : j - 1;
      fall = d(k) - d(k + 1);
    }
    var s = j, e = j;
    while (s > lo && sm(s - 1) <= sm(s)) { s--; }
    while (e < hi && sm(e + 1) <= sm(e)) { e++; }
    if (e - s < 4) { return null; }
    var amp = rules.search_amp_sn, p;
    try { p = tracePreview(tr, t[s], t[e], card.method_baseline, null, amp); } catch (err) { return null; }
    if (p.sn == null || !(p.sn >= (amp == null ? DEFAULT_SEARCH_AMP_SN : amp))) { return null; }
    if (fall != null) {
      var slope = rules.search_slope == null ? DEFAULT_SEARCH_SLOPE : rules.search_slope;
      if (!(p.height > 0) || !(fall / p.height > slope / (width * width))) { return null; }
    }
    return { start: t[s], end: t[e], apex: p.apex, area: p.area, sn: p.sn };
  }
  /* the automatic peak split at `at`: a perpendicular drop at the cursor
     between it and its neighbour, the side holding its apex kept: {start,
     end, baseline: "drop"}, or null when no neighbouring peak lies across
     the cursor */
  function splitAt(card, tr, at) {
    var auto = (tr && (tr.auto || tr.peak)) || {};
    if (at == null || auto.start == null || auto.end == null || !tr.full_res) { return null; }
    var t = tr.t || [], i = snapIndex(t, at, tr.full_res);
    if (i < 0) { return null; }
    var apex = auto.apex == null ? (auto.start + auto.end) / 2 : auto.apex, after = t[i] > apex;
    var start = after ? auto.start : t[i], end = after ? t[i] : auto.end;
    if (!(start < end)) { return null; }
    var p;
    try { p = tracePreview(tr, start, end, "drop", null, ((card && card.rules) || {}).search_amp_sn); } catch (err) { return null; }
    if (!p.bounds) { return null; }
    var across = after ? nearest(t, p.bounds[1]) > p.e : nearest(t, p.bounds[0]) < p.s;
    return across ? { start: t[p.s], end: t[p.e], baseline: "drop" } : null;
  }
  /* what the edges start and end can be drawn on: {drop: a neighbouring
     peak beside them, skim: a parent to skim from}; both false when the
     trace cannot be measured there */
  function geometryOf(card, tr, start, end) {
    var out = { drop: false, skim: false }, amp = ((card && card.rules) || {}).search_amp_sn;
    if (start == null || end == null || !(start < end)) { return out; }
    try {
      var d = tracePreview(tr, start, end, "drop", null, amp);
      out.drop = !!d.bounds && (nearest(tr.t, d.bounds[0]) < d.s || nearest(tr.t, d.bounds[1]) > d.e);
      out.skim = tracePreview(tr, start, end, "skim", null, amp).skim_share != null;
    } catch (err) { /* neither */ }
    return out;
  }

  var BASELINE_ENTRIES = [["valley", "Valley to valley"], ["drop", "Perpendicular drop"], ["skim", "Tangent skim"],
                          ["flat", "Flat at the lower edge"]];
  var NO_TIME = "Point at a time on the chart first.";
  var NO_EDGES = "Set the start and end first.";
  /* the chart's menu, in its four groups, each entry {id, label, key,
     disabled, reason} (a choice of several: checked; a submenu: items):
     s {at (the cursor's time, null when none), fullRes, start, end (the
     edges drawn), baseline (the line drawn), geometry ({drop, skim}),
     candidates (the peaks found, null on a trace that is not a single
     peak), apex (the candidate chosen), minSn (the method's smallest S/N
     for a manual peak), amp and slope (the peak search's), add, split
     (addAt's and splitAt's), deleted (the stored peak), edited (an edit
     stored), changed (a change drawn and not applied), confirm (deleting
     the peak asks to be confirmed), peak (a peak to zoom to)} */
  function menuEntries(s) {
    var at = s.at, out = [], edges = s.start != null && s.end != null && s.start < s.end;
    var outside = at != null && s.fullRes && (at < s.fullRes[0] || at > s.fullRes[1]);
    var where = outside ? "The time lies outside the trace's full-resolution region, " + pyFixed(s.fullRes[0], 3) +
                          " to " + pyFixed(s.fullRes[1], 3) + " min." : null;
    function entry(id, label, key, reason, more) {
      var e = { id: id, label: label, key: key || "", disabled: !!reason, reason: reason || "" };
      for (var k in more || {}) { if (more.hasOwnProperty(k)) { e[k] = more[k]; } }
      out.push(e);
      return e;
    }
    function timeReason(extra) { return at == null ? NO_TIME : where || extra || null; }
    entry("start", "Set start here", "[", timeReason(s.end != null && at >= s.end ? "The start is before the end." : null));
    entry("end", "Set end here", "]", timeReason(s.start != null && at <= s.start ? "The start is before the end." : null));
    entry("level", "Drop baseline here", "D", timeReason(edges ? null : NO_EDGES));
    out.push({ sep: true });
    var g = s.geometry || {}, on = s.baseline;
    entry("baseline", "Baseline", "", edges ? null : NO_EDGES, { items: BASELINE_ENTRIES.map(function (b) {
      var why = b[0] === "drop" && !g.drop ? "No neighbouring peak beside these edges." :
                b[0] === "skim" && !g.skim ? "No parent peak beside these edges to skim from." : "";
      return { id: "baseline-" + b[0], value: b[0], label: b[1], checked: b[0] === on, disabled: !!why, reason: why };
    }) });
    var cs = s.candidates, found = null;
    if (!cs) { found = "Another apex is chosen only on a single peak."; }
    else if (cs.length < 2) { found = "One peak was found in the window."; }
    entry("peaks", "Peaks found", "", found, found ? {} : { items: cs.map(function (c, k) {
      var why = s.minSn != null && c.sn != null ? editProblem("apex", null, null, c.sn, null, s.minSn) || "" : "";
      return { id: "peak-" + k, index: k, label: pyFixed(c.apex, 2) + " min · area " + num(c.area, 0) + " · S/N " +
               (c.sn == null ? "—" : num(c.sn, 1)), checked: s.apex != null && c.apex === s.apex, disabled: !!why,
               reason: why };
    }) });
    entry("add", "Add peak at cursor", "A", timeReason(s.add ? null : "No peak near the cursor passes the method's peak search: slope " +
          pyG(s.slope == null ? DEFAULT_SEARCH_SLOPE : s.slope) + ", S/N " +
          pyG(s.amp == null ? DEFAULT_SEARCH_AMP_SN : s.amp) + "."));
    entry("split", "Split at cursor", "S", timeReason(s.split ? null : "No neighbouring peak across the cursor."));
    out.push({ sep: true });
    entry("delete", "Delete peak", "Del", s.deleted ? "The peak is deleted." : null, { confirm: !!s.confirm });
    entry("undo", "Undo edit", "U", s.edited ? null : "The trace is not edited.");
    entry("restore", "Restore automatic", "", s.edited || s.changed ? null : "The trace is automatic.",
          { discard: !!s.changed });
    out.push({ sep: true });
    entry("zoom-peak", "Zoom to peak", "Z", edges || s.peak ? null : "No peak to zoom to.");
    entry("zoom-window", "Zoom to window", "W");
    entry("copy", "Copy values", "");
    return out;
  }

  /* the dialog's keys: e {key, shiftKey, ctrlKey, metaKey, altKey, tag
     (the focused element's), editable (a contenteditable), onChart (the
     chart has the focus)}; {act, by} or null. Nothing in a text box but
     Escape (asking first when a change is not applied); arrows, Tab and
     the menu key only on the chart. */
  var KEY_ACTS = { "[": "start", "]": "end", d: "level", a: "add", s: "split", u: "undo", z: "zoom-peak",
                   w: "zoom-window", Delete: "delete" };
  function keyMap(e) {
    var k = e.key, tag = String(e.tag || "").toUpperCase();
    if (k === "Escape") { return { act: "close" }; }
    if (e.ctrlKey || e.metaKey || e.altKey) { return null; }
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(tag) || e.editable) { return null; }
    var page = pageStep(k, tag);
    if (page) { return { act: page < 0 ? "previous" : "next" }; }
    if (e.onChart) {
      if (k === "ArrowLeft" || k === "ArrowRight") { return { act: "nudge", by: (k === "ArrowLeft" ? -1 : 1) * (e.shiftKey ? 5 : 1) }; }
      if (k === "Tab") { return { act: "handle", by: e.shiftKey ? -1 : 1 }; }
      if (k === "ContextMenu" || (k === "F10" && e.shiftKey)) { return { act: "menu" }; }
    }
    if (k === "Enter") { return /^(BUTTON|A|SUMMARY)$/.test(tag) ? null : { act: "apply" }; }
    var act = KEY_ACTS[k] || (k && k.length === 1 ? KEY_ACTS[k.toLowerCase()] : null);
    return act ? { act: act } : null;
  }

  /* ── the chart's time axis: zoom and pan ──────────────────────────────── */
  /* the view [x0, x1] zoomed by factor (below 1 in, above 1 out) around
     time at, inside limits [lo, hi], never narrower than least */
  function zoomView(view, at, factor, limits, least) {
    var w = (view[1] - view[0]) * factor, full = limits[1] - limits[0];
    w = Math.max(least || 0, Math.min(w, full));
    var f = view[1] > view[0] ? (at - view[0]) / (view[1] - view[0]) : 0.5;
    return panView([at - f * w, at - f * w + w], 0, limits);
  }
  /* the view moved by dx, kept inside limits */
  function panView(view, dx, limits) {
    var w = view[1] - view[0], a = view[0] + dx;
    a = Math.max(limits[0], Math.min(a, limits[1] - w));
    return [a, a + w];
  }
  /* the peak between start and end with half its width either side, inside limits */
  function peakView(start, end, limits) {
    var m = (end - start) / 2;
    return [Math.max(limits[0], start - m), Math.min(limits[1], end + m)];
  }

  /* the readout as text for the clipboard: the card's name, then a line
     per value, label and value apart by a tab */
  function valuesText(a) {
    var lines = [shown(a) + " in " + a.injection];
    readout(a).forEach(function (c) { lines.push(c[0] + "\t" + c[1] + (c[2] ? "\t" + c[2] : "")); });
    return lines.join("\n");
  }

  /* ── the browser: charts, the overview, the dialog ────────────────────── */
  function token(name) { return getComputedStyle(doc.documentElement).getPropertyValue(name).trim(); }
  function points(tr) { return tr.t.map(function (x, i) { return { x: x, y: tr.y[i] }; }); }
  var SERIES = ["--series-1", "--series-2", "--series-3", "--series-4"];

  /* a plain chart: the traces, the first's peak shaded (the isotope standard's) */
  function form() { return doc.getElementById("raw-edit"); }
  function components() { return window.PFAS && window.PFAS.components; }

  /* the trace the analyst was on when the page went away to post an edit */
  var LAST = "pfas.raw.last";
  function remember(v) { try { window.sessionStorage.setItem(LAST, JSON.stringify(v)); } catch (e) { /* none kept */ } }
  function recall() {
    try { return JSON.parse(window.sessionStorage.getItem(LAST) || "null"); } catch (e) { return null; }
  }
  function forget() { try { window.sessionStorage.removeItem(LAST); } catch (e) { /* none kept */ } }

  var EDIT_TEXT = { auto: "Automatic", edited: "Edited", deleted: "Peak deleted",
                    pending: "Waiting for the run to be processed again", no_effect: "No effect" };

  function seg(label, items, on) {
    return '<div class="pfas-seg pfas-seg-sm is-fit" role="group" data-quiet="" aria-label="' + esc(label) + '">' +
      items.map(function (it) {
        return '<button type="button" class="pfas-seg-item" data-value="' + esc(it[0]) + '" aria-pressed="' +
               (it[0] === on ? "true" : "false") + '">' + esc(it[1]) + "</button>";
      }).join("") + "</div>";
  }
  function pressSeg(el, value) {
    var items = el.querySelectorAll(".pfas-seg-item");
    for (var i = 0; i < items.length; i++) {
      items[i].setAttribute("aria-pressed", items[i].getAttribute("data-value") === value ? "true" : "false");
    }
    var C = components();
    if (C && C.placePill) { C.placePill(el); }
  }
  function onSeg(el, fn) {
    el.addEventListener("click", function (e) {
      var item = e.target.closest(".pfas-seg-item");
      if (item && el.contains(item)) { fn(item.getAttribute("data-value")); }
    });
  }
  function el(tag, cls, html) {
    var n = doc.createElement(tag);
    if (cls) { n.className = cls; }
    if (html != null) { n.innerHTML = html; }
    return n;
  }

  /* the open dialog; one at a time. Its charts go when the dialog closes
     or another card opens, and a card asked for before either is dropped
     when it arrives (`asked` counts the requests). */
  var current = null, asked = 0, watching = false;
  function dispose() {
    if (current) {
      if (current.chart) { current.chart.destroy(); }
      current = null;
    }
  }
  function watchClose(drawer) {
    if (watching || !drawer.el || !window.MutationObserver) { return; }
    watching = true;
    new window.MutationObserver(function () {
      if (drawer.el.getAttribute("data-open") !== "true") { asked++; dispose(); }
    }).observe(drawer.el, { attributes: true, attributeFilter: ["data-open"] });
  }

  /* the full card in the dialog, with its edits when this analyst may make
     them; step (-1, +1) when Previous or Next opened it, its button keeping
     the focus. The edit is made on the chart: the baseline drawn with a
     handle at each end, the right-click menu (or the Actions button, or
     the menu key on the chart) carrying every action, and the keys. */
  function dialog(data, a, flash, last, step) {
    var C = components();
    dispose();
    var traces = [a.quant].concat(a.quals || []);
    var f = form();
    var editable = !!(a.can_edit && data.can_edit !== false && f);
    var ui = { a: a, data: data, traces: traces, index: 0, chart: null, armed: false, pending: null,
               at: null, handle: "start", view: null, line: null, drawn: null, chartFocus: false };
    current = ui;
    /* the quantifier is posted with no transition of its own */
    if (last && !last.transition) { last.transition = a.quant.transition; }
    /* the method's notes on the edit just made, on its trace until the analyst changes anything */
    ui.serverNotes = (last && last.notes) || [];
    ui.notesOn = last ? last.transition : null;
    if (last && last.transition) {
      for (var q = 1; q < traces.length; q++) { if (traces[q].transition === last.transition) { ui.index = q; } }
    }
    var body = el("div", "raw-dialog " + stateClass(a.state).replace("raw-card", "").replace(/^\s+/, ""));
    body.innerHTML = cardBody(a, traces, ui.index, editable, flash);
    var foot = el("div", "pfas-drawer-actions"), submit = null;
    var actionsBtn = el("button", "btn btn-secondary", "Actions");
    actionsBtn.type = "button";
    actionsBtn.setAttribute("aria-haspopup", "menu");
    actionsBtn.setAttribute("aria-expanded", "false");
    actionsBtn.setAttribute("data-role", "actions");
    foot.appendChild(actionsBtn);
    if (editable) {
      submit = el("button", "btn btn-primary");
      submit.type = "button";
      foot.appendChild(submit);
    }
    var head = navHead(step);
    C.drawer.open(shown(a) + " in " + a.injection, body, { cls: "is-dialog raw-dialog-box", footer: foot,
                                                           head: head.nodes, focus: head.focus });
    if (C.init) { C.init(body); }
    var traceSeg = body.querySelector('.pfas-seg[aria-label="Trace"]');
    if (traceSeg) { onSeg(traceSeg, function (v) { ui.index = parseInt(v, 10); ui.armed = false; showTrace(); }); }
    var canvas = body.querySelector('canvas[data-role="traces"]');

    /* the edit being drawn: mode (the pane), kind, edges, apex, baseline
       ("" for the method's), levels (as posted, null with none set by
       hand), manual (each end's level set by hand), handles (the line's
       values at the edges where set by hand) */
    var st = null;
    function tr() { return traces[ui.index]; }
    function rules() { return a.rules || {}; }
    function line() { return st.baseline || a.method_baseline; }
    /* a change drawn and not posted: Previous and Next ask before leaving it */
    ui.dirty = function () { return !!(editable && st && st.mode === "integrate" && st.touched); };
    function seedLevels(levels) {
      st.levels = levels || null;
      st.manual = levels ? [true, true] : [false, false];
      st.handles = null;           /* drawn from the line the engine measures with them */
    }
    function startState() {
      var t = tr(), p = t.peak || {};
      var own = t.edit !== "auto" && t.baseline && t.baseline !== a.method_baseline ? t.baseline : "";
      st = { mode: "integrate", kind: "integrate", start: p.start, end: p.end, apex: null, baseline: own,
             touched: false, note: "" };
      seedLevels(t.edit === "edited" ? t.levels : null);
      /* an edit waiting for the run: the edges start from its edges */
      var pe = ui.pending = pendingEdges(t, a);
      if (pe && pe.kind === "delete") {
        st.start = st.end = null;   /* a deletion waiting: no edges, as the chart draws none */
      } else if (pe && pe.start != null && pe.end != null) {
        st.kind = pe.kind === "apex" ? "apex" : "integrate";
        st.start = pe.start;
        st.end = pe.end;
        st.apex = pe.apex;
        st.baseline = pe.baseline && pe.baseline !== a.method_baseline ? pe.baseline : "";
        seedLevels(pe.kind === "integrate" ? pe.levels : null);
      }
      /* refused: the edit as it was posted, to adjust rather than retype */
      var back = refusedEdit(last, flash, t.transition);
      if (back && back.mode === "delete") {
        if (ui.index === 0) {
          st.mode = "delete";
          ui.armed = true;          /* the server asked for the deletion to be confirmed */
        }
      } else if (back) {
        for (var k in back) { if (back.hasOwnProperty(k)) { st[k] = back[k]; } }
        seedLevels(back.levels);
      }
      last = null;
    }
    /* the edit as judge and the post read it */
    function editOf() {
      return { kind: st.kind, start: st.start, end: st.end, apex: st.apex, baseline: st.baseline,
               levels: st.kind === "integrate" ? st.levels : null };
    }
    function edgesSet() { return typeof st.start === "number" && typeof st.end === "number" && st.start < st.end; }
    /* the outer edges a drop's line runs between, with no level set by hand */
    function dropBounds(start, end) {
      try { return tracePreview(tr(), start, end, "drop", null, rules().search_amp_sn).bounds; } catch (err) { return null; }
    }
    /* what a handle's drag reads: the edit as drawn */
    function handleState(held, from) {
      var t = tr();
      return { held: held, t: t.t, fullRes: t.full_res, start: st.start, end: st.end,
               levels: st.handles || ui.drawn || [null, null], manual: st.manual, baseline: line(),
               range: countRange(t), from: from,
               signal: function (s, e) {
                 try {
                   var p = tracePreview(t, s, e, line(), null, rules().search_amp_sn);
                   return [p.base_start, p.base_end];
                 } catch (err) { return [t.y[nearest(t.t, s)], t.y[nearest(t.t, e)]]; }
               } };
    }
    /* a drag's result taken as the edit: a re-integration on these edges and levels */
    function takeDrag(d) {
      st.mode = "integrate";
      st.kind = "integrate";
      st.start = d.start;
      st.end = d.end;
      st.manual = d.manual;
      st.handles = d.manual[0] || d.manual[1] ? d.levels : null;
      st.levels = postedLevels(line(), d.start, d.end, d.levels, d.manual,
                               line() === "drop" ? dropBounds(d.start, d.end) : null, countRange(tr()));
      st.touched = true;
      st.note = "";
      boxes();
      update();
    }
    /* the baseline drawn at another line: the levels set by hand kept where the handles are */
    function setLine(mode) {
      st.baseline = mode === a.method_baseline ? "" : mode;
      if (st.kind === "integrate" && (st.manual[0] || st.manual[1]) && edgesSet()) {
        st.levels = postedLevels(line(), st.start, st.end, st.handles || ui.drawn, st.manual,
                                 line() === "drop" ? dropBounds(st.start, st.end) : null, countRange(tr()));
      }
      st.mode = "integrate";
      st.touched = true;
      update();
    }
    function setEdges(start, end, baseline) {
      st.mode = "integrate";
      st.kind = "integrate";
      st.start = start;
      st.end = end;
      if (baseline != null) { st.baseline = baseline === a.method_baseline ? "" : baseline; }
      seedLevels(null);
      st.touched = true;
      st.note = "";
      boxes();
      update();
    }

    /* what the menu is built from, as the edit stands */
    function menuState() {
      var t = tr(), lim = a.limits || {}, edges = edgesSet();
      return { at: ui.at, fullRes: t.full_res, start: typeof st.start === "number" ? st.start : null,
               end: typeof st.end === "number" ? st.end : null, baseline: line(),
               geometry: edges ? geometryOf(a, t, st.start, st.end) : null, candidates: t.candidates || null,
               apex: st.kind === "apex" ? st.apex : null, minSn: lim.min_manual_sn, amp: rules().search_amp_sn, slope: rules().search_slope,
               add: addAt(a, t, ui.at), split: splitAt(a, t, ui.at), deleted: !!t.deleted && t.edit !== "pending",
               edited: !!t.edit && t.edit !== "auto", changed: !!st.touched || st.mode !== "integrate",
               confirm: confirmsDelete(a, ui.index, false), peak: !!(t.peak && t.peak.start != null) };
    }
    var VIEW_ONLY = ["zoom-peak", "zoom-window", "copy"];
    function entries() {
      var list = menuEntries(menuState());
      if (!editable) { list = list.filter(function (e) { return e.id && VIEW_ONLY.indexOf(e.id) >= 0; }); }
      return list;
    }
    function menuItems() {
      return entries().map(function (e) {
        if (e.sep) { return e; }
        var it = { id: e.id, label: e.label, key: e.key, disabled: e.disabled, reason: e.reason };
        if (e.items) {
          it.items = e.items.map(function (s) {
            return { id: s.id, label: s.label, checked: s.checked, disabled: s.disabled, reason: s.reason,
                     act: function () { run(s); } };
          });
        } else {
          it.act = function () { run(e); };
        }
        return it;
      });
    }
    /* an entry of the menu, or its key, done */
    function run(e) {
      if (!e || e.disabled) { return; }
      var t = tr(), id = e.id;
      if (id === "start" || id === "end") {
        takeDrag(handleDrag(handleState(id), { x: ui.at, axis: "x" }));
      } else if (id === "level") {
        var v = clampTo(traceSignal(t)(snapIndex(t.t, ui.at, t.full_res)), countRange(t));
        takeDrag({ start: st.start, end: st.end, levels: [v, v], manual: [true, true] });
      } else if (id.indexOf("baseline-") === 0) {
        setLine(e.value);
      } else if (id.indexOf("peak-") === 0) {
        choose(t.candidates[e.index]);
      } else if (id === "add") {
        var found = addAt(a, t, ui.at);
        if (found) { setEdges(found.start, found.end, null); }
      } else if (id === "split") {
        var cut = splitAt(a, t, ui.at);
        if (cut) { setEdges(cut.start, cut.end, cut.baseline); }
      } else if (id === "delete") {
        st.mode = "delete";
        ui.armed = false;
        update();
      } else if (id === "undo" || (id === "restore" && !e.discard)) {
        st.mode = "revert";
        update();
      } else if (id === "restore") {
        startState();                 /* the change drawn is let go */
        boxes();
        update();
      } else if (id === "zoom-peak") {
        var s = edgesSet() ? st.start : (t.peak || {}).start, en = edgesSet() ? st.end : (t.peak || {}).end;
        zoomTo(peakView(s, en, limits()));
      } else if (id === "zoom-window") {
        zoomTo(null);
      } else if (id === "copy") {
        copyValues();
      }
    }
    function openMenu(opts) {
      if (!C.menu) { return; }
      C.menu.open(menuItems(), { x: opts.x, y: opts.y, anchor: opts.anchor, opener: opts.opener,
                                 label: "The peak of " + tr().transition });
    }
    actionsBtn.addEventListener("click", function () {
      if (C.menu && C.menu.isOpen()) { C.menu.close(true); return; }
      openMenu({ anchor: actionsBtn, opener: actionsBtn });
    });

    /* ── the chart ── */
    function limits() { var t = tr().t; return [t[0], t[t.length - 1]]; }
    function windowView() { return chartView(tr(), traces).x; }
    /* the count axis for view v: a region's own, the whole window's, or
       the trace and its drawn baseline between v's ends */
    function countsFor(v) {
      if (ui.yview) { return ui.yview; }
      if (!ui.view) { return chartView(tr(), traces).y; }
      var ln = ui.line, shown = [tr()];
      if (ln) { shown.push({ t: [ln[0], ln[2]], y: [ln[1], ln[3]] }); }
      return spanY(shown, v[0], v[1]);
    }
    function zoomTo(view, counts) {
      ui.view = view;
      ui.yview = view && counts ? counts : null;
      if (!ui.chart) { return; }
      var v = view || windowView(), y = countsFor(v);
      ui.chart.options.scales.x.min = v[0];
      ui.chart.options.scales.x.max = v[1];
      ui.chart.options.scales.y.min = y[0];
      ui.chart.options.scales.y.max = y[1];
      ui.chart.update("none");
    }
    /* the narrowest view: eight edge tolerances either side */
    function leastSpan() { var t = tr(); return 8 * 2 * edgeTolerance(t.t, t.full_res || limits()); }
    function setRegion(on) {
      ui.region = on;
      var b = body.querySelector('[data-zoom="region"]'), wrap = body.querySelector('[data-role="wrap"]');
      if (b) { b.setAttribute("aria-pressed", on ? "true" : "false"); }
      if (wrap) { wrap.classList.toggle("is-region", on); }
    }
    var zoomBar = body.querySelector('[data-role="zoom"]');
    if (zoomBar) {
      zoomBar.addEventListener("click", function (e) {
        var b = e.target && e.target.closest ? e.target.closest("[data-zoom]") : null;
        if (!b || !ui.chart) { return; }
        var z = b.getAttribute("data-zoom"), cur = [ui.chart.scales.x.min, ui.chart.scales.x.max];
        if (z === "region") { setRegion(!ui.region); return; }
        setRegion(false);
        if (z === "full") { zoomTo(null); return; }
        zoomTo(zoomView(cur, (cur[0] + cur[1]) / 2, z === "in" ? 0.5 : 2, limits(), leastSpan()));
      });
    }
    function copyValues() {
      var said = body.querySelector('[data-role="said"]'), text = valuesText(a);
      function say(s) { if (said) { said.textContent = s; } }
      try {
        window.navigator.clipboard.writeText(text).then(function () { say("The values are copied."); },
                                                         function () { say("The values could not be copied."); });
      } catch (err) { say("The values could not be copied."); }
    }
    function draw() {
      var t = tr(), wrap = body.querySelector('[data-role="wrap"]');
      if (ui.chart) { ui.chart.destroy(); ui.chart = null; }
      if (!window.Chart) { return; }
      var others = traces.filter(function (x, i) { return i !== ui.index; });
      var sets = [
        { label: "baseline", data: [], borderColor: token("--s-secondary"), borderWidth: 0, pointRadius: 0, showLine: true },
        { label: "integrated", data: [], borderWidth: 0, pointRadius: 0, showLine: true,
          backgroundColor: token("--s-primary-lt"), fill: "-1" },
        { label: "automatic", data: t.auto ? peakOutline(t.t, t.y, t.auto) : [], borderColor: token("--s-secondary"),
          borderWidth: 1, borderDash: [2, 3], pointRadius: 0, showLine: true },
        { label: t.transition, data: points(t), borderColor: token(SERIES[ui.index % SERIES.length]), borderWidth: 1.5,
          pointRadius: 0, showLine: true }];
      others.forEach(function (o) {
        sets.push({ label: o.transition, data: points(o), borderColor: token("--s-border"), borderWidth: 1,
                    pointRadius: 0, showLine: true });
      });
      var view = chartView(t, traces), x = ui.view || view.x, y = ui.view ? countsFor(x) : view.y;
      ui.chart = new window.Chart(canvas, {
        type: "scatter", data: { datasets: sets },
        options: { animation: false, maintainAspectRatio: false,
                   plugins: { legend: { display: false }, annotation: { annotations: {} } },
                   scales: { x: { title: { display: true, text: "min" }, min: x[0], max: x[1] },
                             y: { min: y[0], max: y[1] } } }
      });
      if (wrap) { gestures(wrap); }
    }

    /* the shading, the baseline and its handles, the candidates as the edit stands */
    function paint(res) {
      if (!ui.chart) { return; }
      var t = tr(), sets = ui.chart.data.datasets, top = [], base = [], ln = null;
      /* an edit waiting for the run is drawn until the analyst changes it */
      var pe = !st.touched && st.mode === "integrate" ? ui.pending : null;
      var p = (res && res.preview) || (pe && pe.preview);
      if (p) {
        for (var i = p.s; i <= p.e; i++) {
          top.push({ x: t.t[i], y: t.y[i] });
          base.push({ x: t.t[i], y: interp(t.t[i], t.t[p.s], t.t[p.e], p.base_start, p.base_end) });
        }
        ln = [t.t[p.s], p.base_start, t.t[p.e], p.base_end];
      } else if (!pe && (!st.touched || st.mode !== "integrate") && !t.deleted && t.peak && t.peak.start != null) {
        var fl = peakFill(t.t, t.y, t.peak);    /* the stored peak: the one a delete removes */
        top = fl.top; base = fl.base;
        ln = [t.peak.start, t.peak.base_start, t.peak.end, t.peak.base_end];
      }
      sets[0].data = base;
      sets[1].data = top;
      var working = editable && st.mode === "integrate" && !(pe && pe.kind === "delete");
      if (working && !ln && edgesSet()) {      /* not measured: the handles on the signal */
        ln = [st.start, t.y[nearest(t.t, st.start)], st.end, t.y[nearest(t.t, st.end)]];
      }
      if (pe && pe.kind === "delete") { ln = null; }
      ui.line = ln;
      ui.drawn = ln ? [ln[1], ln[3]] : null;
      var marks = {}, colour = token(st.touched ? "--s-warning" : pe ? "--s-info" : "--s-secondary");
      if (ln) {
        marks.baseline = { type: "line", xMin: ln[0], yMin: ln[1], xMax: ln[2], yMax: ln[3], borderColor: colour,
                           borderWidth: 2 };
        if (p && p.bounds && (p.bounds[0] < ln[0] || p.bounds[1] > ln[2])) {
          /* a drop: the line under the pair to its outer edges, and the drops at the edges */
          var at0 = interp(p.bounds[0], ln[0], ln[2], ln[1], ln[3]), at1 = interp(p.bounds[1], ln[0], ln[2], ln[1], ln[3]);
          marks.outer = { type: "line", xMin: p.bounds[0], yMin: at0, xMax: p.bounds[1], yMax: at1, borderColor: colour,
                          borderWidth: 1, borderDash: [4, 3] };
          marks.dropStart = { type: "line", xMin: ln[0], xMax: ln[0], yMin: ln[1], yMax: t.y[p.s], borderColor: colour,
                              borderWidth: 1 };
          marks.dropEnd = { type: "line", xMin: ln[2], xMax: ln[2], yMin: ln[3], yMax: t.y[p.e], borderColor: colour,
                            borderWidth: 1 };
        }
        if (working) {
          ["start", "end"].forEach(function (h, k) {
            var chosen = ui.chartFocus && ui.handle === h;
            marks["handle_" + h] = { type: "point", xValue: ln[2 * k], yValue: ln[2 * k + 1], radius: 7,
                                     backgroundColor: chosen ? token("--s-primary-lt") : "transparent",
                                     borderColor: token("--s-primary-dk"), borderWidth: chosen ? 3 : 2 };
          });
        }
      }
      if (working) {
        (t.candidates || []).forEach(function (c, k) {
          var on = st.kind === "apex" && st.apex === c.apex;
          marks["cand" + k] = { type: "point", xValue: c.apex, yValue: c.y, radius: on ? 6 : 5,
                                backgroundColor: "transparent", borderColor: token(on ? "--s-warning" : "--s-info"),
                                borderWidth: 2, click: function () { if (!ui.justDragged) { choose(c); } } };
        });
      }
      ui.chart.options.plugins.annotation.annotations = marks;
      ui.chart.update("none");
    }

    /* the chart's gestures: a handle or the line dragged, a handle
       double-clicked, the menu on a right-click, the wheel zooming the
       time axis around the cursor, the axis dragged to pan; the cursor's
       time kept for the menu and the keys */
    function gestures(wrap) {
      var held = null, press = null, axis = null, moved = false, from = null;
      function pos(e) {
        var r = canvas.getBoundingClientRect();
        return { px: e.clientX - r.left, py: e.clientY - r.top };
      }
      function timeAt(px) { return ui.chart.scales.x.getValueForPixel(px); }
      function countAt(py) { return ui.chart.scales.y.getValueForPixel(py); }
      function inArea(q) {
        var ar = ui.chart.chartArea;
        return q.px >= ar.left && q.px <= ar.right && q.py >= ar.top && q.py <= ar.bottom;
      }
      /* what a press at q takes: a handle (within 9 px), the line (6 px), the axis, or nothing */
      function target(q) {
        var ar = ui.chart.chartArea;
        if (q.py > ar.bottom && q.px >= ar.left && q.px <= ar.right) { return "axis"; }
        var ln = ui.line;
        if (!ln || !editable || st.mode !== "integrate") { return null; }
        var xs = ui.chart.scales.x, ys = ui.chart.scales.y, best = null, bestD = 9;
        ["start", "end"].forEach(function (h, k) {
          var d = Math.sqrt(Math.pow(q.px - xs.getPixelForValue(ln[2 * k]), 2) +
                            Math.pow(q.py - ys.getPixelForValue(ln[2 * k + 1]), 2));
          if (d <= bestD) { best = h; bestD = d; }
        });
        if (best) { return best; }
        var x = timeAt(q.px);
        if (x > ln[0] && x < ln[2] && Math.abs(q.py - ys.getPixelForValue(interp(x, ln[0], ln[2], ln[1], ln[3]))) <= 6) {
          return "line";
        }
        return null;
      }
      canvas.onpointerdown = function (e) {
        if (e.button !== 0 || !ui.chart) { return; }
        var q = pos(e);
        if (ui.region && inArea(q)) {     /* a box drawn to zoom into, not a handle */
          held = "region"; press = q; moved = false;
          from = { x: timeAt(q.px), y: countAt(q.py) };
          canvas.setPointerCapture(e.pointerId);
          e.preventDefault();
          return;
        }
        held = target(q);
        if (!held) { return; }
        press = q;
        axis = held === "line" || held === "axis" ? "x" : null;
        moved = false;
        from = held === "axis" ? { view: [ui.chart.scales.x.min, ui.chart.scales.x.max] }
                               : { start: st.start, end: st.end, x: timeAt(q.px) };
        if (held === "start" || held === "end") { ui.handle = held; }
        canvas.setPointerCapture(e.pointerId);
        wrap.classList.add("is-dragging");
        e.preventDefault();
      };
      canvas.onpointermove = function (e) {
        if (!ui.chart) { return; }
        var q = pos(e);
        if (!held) {
          if (inArea(q)) { ui.at = timeAt(q.px); }
          var over = target(q);
          wrap.classList.toggle("is-edge", over === "start" || over === "end");
          wrap.classList.toggle("is-line", over === "line" || over === "axis");
          return;
        }
        if (held === "region") {
          var marks = ui.chart.options.plugins.annotation.annotations;
          marks.region = { type: "box", xMin: from.x, xMax: timeAt(q.px), yMin: from.y, yMax: countAt(q.py),
                           borderColor: token("--s-info"), borderWidth: 1, borderDash: [4, 3],
                           backgroundColor: "transparent" };
          moved = true;
          ui.chart.update("none");
          return;
        }
        if (axis === null) {            /* past a few pixels the drag takes its direction */
          var dx = Math.abs(q.px - press.px), dy = Math.abs(q.py - press.py);
          if (dx < 4 && dy < 4) { return; }
          axis = dx >= dy ? "x" : "y";
        }
        moved = true;
        if (held === "axis") {
          var w = from.view[1] - from.view[0], ar = ui.chart.chartArea;
          zoomTo(panView(from.view, -(q.px - press.px) / (ar.right - ar.left) * w, limits()));
          return;
        }
        var d = handleDrag(handleState(held, from), { x: timeAt(q.px), y: countAt(q.py), axis: axis, shift: e.shiftKey });
        if (d.start !== st.start || d.end !== st.end || d.levels[0] !== (st.handles || ui.drawn || [])[0] ||
            d.levels[1] !== (st.handles || ui.drawn || [])[1] || d.manual[0] !== st.manual[0] || d.manual[1] !== st.manual[1]) {
          takeDrag(d);
        }
      };
      canvas.onpointerup = canvas.onpointercancel = canvas.onlostpointercapture = function (e) {
        if (!held) { return; }
        if (held === "region") {
          held = null;
          try { canvas.releasePointerCapture(e.pointerId); } catch (err) { /* released already */ }
          delete ui.chart.options.plugins.annotation.annotations.region;
          var q = pos(e), box = moved ? regionView(from.x, from.y, timeAt(q.px), countAt(q.py), leastSpan()) : null;
          setRegion(false);
          if (box) { zoomTo(box.x, box.y); } else { ui.chart.update("none"); }
          ui.justDragged = true;       /* the click that ends the box is not a candidate's */
          window.setTimeout(function () { ui.justDragged = false; }, 0);
          return;
        }
        held = null;
        wrap.classList.remove("is-dragging");
        try { canvas.releasePointerCapture(e.pointerId); } catch (err) { /* released already */ }
        if (moved) {                 /* the click that ends a drag is not a candidate's */
          ui.justDragged = true;
          window.setTimeout(function () { ui.justDragged = false; }, 0);
        }
      };
      /* a handle double-clicked: its level back on the signal */
      canvas.ondblclick = function (e) {
        var h = ui.chart ? target(pos(e)) : null;
        if (h !== "start" && h !== "end") { return; }
        e.preventDefault();
        takeDrag(handleDrag(handleState(h), { reset: true }));
      };
      canvas.oncontextmenu = function (e) {
        if (!ui.chart) { return; }
        e.preventDefault();
        var q = pos(e);
        if (inArea(q)) { ui.at = timeAt(q.px); }
        openMenu({ x: e.clientX, y: e.clientY, opener: canvas });
      };
      canvas.onwheel = function (e) {
        if (!ui.chart || !e.deltaY) { return; }
        var q = pos(e);
        if (!inArea(q)) { return; }
        e.preventDefault();
        var least = leastSpan();
        zoomTo(zoomView([ui.chart.scales.x.min, ui.chart.scales.x.max], timeAt(q.px), e.deltaY > 0 ? 1.25 : 0.8,
                        limits(), least));
      };
      canvas.onfocus = function () { ui.chartFocus = true; if (st) { paint(lastRes); } };
      canvas.onblur = function () { ui.chartFocus = false; if (st) { paint(lastRes); } };
    }

    /* the keys while this card is open (keyMap): true when the key was this card's */
    ui.key = function (k) {
      var t = tr(), list, e;
      if (k.act === "menu") {
        var ln = ui.line, r = canvas.getBoundingClientRect(), x = r.left, y = r.top;
        if (ln && ui.chart) {
          var k2 = ui.handle === "end" ? 2 : 0;
          x += ui.chart.scales.x.getPixelForValue(ln[k2]);
          y += ui.chart.scales.y.getPixelForValue(ln[k2 + 1]);
          if (ui.at == null) { ui.at = ln[k2]; }
        }
        openMenu({ x: x, y: y, opener: canvas });
        return true;
      }
      if (k.act === "apply") {
        if (submit && !submit.disabled) { post(); return true; }
        return false;
      }
      if (k.act === "handle") {
        if (!editable || !ui.line) { return false; }
        if (k.by > 0 && ui.handle !== "end") { ui.handle = "end"; paint(lastRes); return true; }
        if (k.by < 0 && ui.handle === "end") { ui.handle = "start"; paint(lastRes); return true; }
        return false;
      }
      if (k.act === "nudge") {
        if (!editable || st.mode !== "integrate" || !edgesSet()) { return false; }
        var i = snapIndex(t.t, st[ui.handle], null) + k.by;
        i = Math.max(0, Math.min(i, t.t.length - 1));
        takeDrag(handleDrag(handleState(ui.handle), { x: t.t[i], axis: "x" }));
        return true;
      }
      list = entries();
      for (var n = 0; n < list.length; n++) { if (list[n].id === k.act) { e = list[n]; } }
      if (!e) { return false; }
      run(e);
      return true;
    };

    function boxes() {
      var s = body.querySelector('input[data-edge="start"]'), e = body.querySelector('input[data-edge="end"]');
      if (!s) { return; }
      s.value = st.start == null ? "" : typeof st.start === "number" ? st.start.toFixed(3) : String(st.start);
      e.value = st.end == null ? "" : typeof st.end === "number" ? st.end.toFixed(3) : String(st.end);
    }
    /* a level box shows while that end's level is set by hand */
    function levelBoxes() {
      ["start", "end"].forEach(function (side, k) {
        var box = body.querySelector('input[data-level="' + side + '"]');
        if (!box) { return; }
        var on = st.mode === "integrate" && st.kind === "integrate" && !!st.manual[k];
        box.closest("label").hidden = !on;
        var v = (st.handles || ui.drawn || [])[k];
        if (on && doc.activeElement !== box) { box.value = v == null ? "" : String(Math.round(v)); }
      });
    }

    function choose(c) {
      st.mode = "integrate";
      st.kind = "apex";
      st.note = "";
      st.apex = c.apex;
      st.start = c.start;
      st.end = c.end;
      seedLevels(null);
      st.touched = true;
      boxes();
      update();
    }

    function deleteText() {
      return deleteWarning(a, ui.index, injectionType(data, a.injection, a.analyte), !!tr().deleted);
    }
    function needsConfirm() {
      return confirmsDelete(a, ui.index, ui.armed);
    }

    /* everything the edit shows: the panes, the preview, the refusal, the notes, the button */
    var lastRes = null;
    function update() {
      var t = tr();
      var panes = body.querySelectorAll(".raw-pane");
      for (var i = 0; i < panes.length; i++) { panes[i].hidden = panes[i].getAttribute("data-pane") !== st.mode; }
      var res = null, problem = null;
      if (editable && st.mode === "integrate" && st.touched) {
        res = judge(a, t, editOf());
        problem = res.problem;
      }
      if (st.touched) { ui.serverNotes = []; }
      var shownNotes = res ? res.notes : (t.transition === ui.notesOn ? ui.serverNotes : []);
      lastRes = res;
      var prev = body.querySelector('[data-role="preview"]');
      if (prev) {
        var p = res && res.preview;
        prev.textContent = p ? "Area " + num(p.area, 0) + " · S/N " + (p.sn == null ? "—" : num(p.sn, 1)) +
                               (res.change == null ? "" : " · change " + pyFixed(res.change, 1) + " %") : "";
        body.querySelector('[data-role="problem"]').textContent = problem || "";
        body.querySelector('[data-role="edge-note"]').textContent = st.mode === "integrate" ? st.note || "" : "";
      }
      /* the flags, and what the method notes of the manual peak (never a refusal), as chips */
      var flags = body.querySelector('[data-role="flags"]');
      if (flags) { flags.innerHTML = chipItems(flagChips(a, shownNotes || [])); }
      var dt = body.querySelector('[data-role="delete-text"]');
      if (dt) {
        dt.textContent = deleteText() + (ui.armed && needsConfirm() ? " Confirm to delete it." : "");
      }
      if (submit) {
        if (st.mode === "integrate") {
          submit.textContent = st.kind === "apex" ? "Choose this peak" : "Re-integrate";
          submit.disabled = !st.touched || !!problem;
        } else if (st.mode === "delete") {
          submit.textContent = ui.armed && needsConfirm() ? "Confirm delete" : "Delete peak";
          submit.disabled = !!t.deleted && t.edit !== "pending";
        } else {
          submit.textContent = "Undo edit";
          submit.disabled = false;
        }
      }
      var trace = body.querySelector('[data-role="trace-line"]');
      /* an edit the run could not apply says why; one waiting for the run says what it is */
      trace.textContent = t.transition + " · " + (EDIT_TEXT[t.edit] || EDIT_TEXT.auto) +
                          (t.edit === "no_effect" && t.no_effect ? ": " + t.no_effect : "") +
                          (t.edit === "pending" && t.pending_text ? ": " + t.pending_text : "");
      paint(res);
      levelBoxes();
    }

    function post() {
      var t = tr();
      if (st.mode === "delete" && needsConfirm() && !ui.armed) {
        ui.armed = true;            /* a confirming click first */
        update();
        return;
      }
      var kind = st.mode === "integrate" ? st.kind : st.mode, edit = editOf();
      var res = kind === "integrate" ? judge(a, t, edit) : null;
      var levels = kind === "integrate" ? edit.levels : null;
      var payload = editPayload({ injection: a.injection, analyte: a.analyte, transition: ui.index ? t.transition : "",
                                  mode: data.mode, kind: kind, start: res ? res.start : st.start,
                                  end: res ? res.end : st.end, apex: st.apex, baseline: st.baseline, levels: levels,
                                  confirm: kind === "delete" && ui.armed });
      for (var k in payload) {
        if (payload.hasOwnProperty(k) && f.elements[k]) { f.elements[k].value = payload[k]; }
      }
      /* the edit as posted, for the card to open on again if the server refuses it */
      remember({ open: a.injection + "|" + a.analyte, transition: t.transition, kind: kind,
                 start: res ? res.start : st.start, end: res ? res.end : st.end, apex: st.apex, baseline: st.baseline,
                 levels: levels });
      submit.disabled = true;
      f.submit();
    }

    function showTrace() {
      startState();
      ui.view = null;
      ui.yview = null;
      setRegion(false);
      ui.handle = "start";
      var step = edgeStep(tr().t, tr().full_res), edges = body.querySelectorAll("input[data-edge]");
      for (var k = 0; k < edges.length; k++) { edges[k].setAttribute("step", step); }
      if (traceSeg) { pressSeg(traceSeg, String(ui.index)); }
      if (editable) { boxes(); }
      draw();
      update();
    }

    if (editable) {
      submit.addEventListener("click", post);
      ["start", "end"].forEach(function (edge) {
        var box = body.querySelector('input[data-edge="' + edge + '"]');
        box.addEventListener("input", function () {
          var v = box.value === "" ? null : parseFloat(box.value);
          st[edge] = v != null && isNaN(v) ? box.value : v;
          st.note = "";
          st.mode = "integrate";
          st.kind = "integrate";
          st.touched = true;
          update();
        });
        box.addEventListener("change", function () {         /* typed, or the stepper's buttons: on its sample */
          var v = parseFloat(box.value), t = tr();
          if (isNaN(v)) { return; }
          var kept = typedEdge(t.t, v, t.full_res, edge);
          st[edge] = kept.value;
          st.note = kept.note;
          st.mode = "integrate";
          st.kind = "integrate";
          st.touched = true;
          boxes();
          update();
        });
      });
      /* a level typed: that end's level by hand, in counts (flat: both) */
      ["start", "end"].forEach(function (side, k) {
        var box = body.querySelector('input[data-level="' + side + '"]');
        box.addEventListener("change", function () {
          var v = parseFloat(box.value);
          if (isNaN(v) || !edgesSet()) { return; }
          var h = handleState(side), d = handleDrag(h, { y: v, axis: "y" });
          takeDrag(d);
        });
      });
    }
    showTrace();
  }

  /* the card the dialog shows or is fetching, {data, injection, analyte}:
     where Previous and Next step from */
  var shownCard = null;
  /* Previous and Next for the dialog's head, each disabled at its end of
     the overview; {nodes, focus: the button of `step` when it opened the
     card and can step again} */
  function navHead(step) {
    var nodes = [], focus = null;
    [[-1, "Previous"], [1, "Next"]].forEach(function (d) {
      var b = el("button", "btn-sm btn-secondary", esc(d[1]));
      b.type = "button";
      b.setAttribute("data-step", String(d[0]));
      b.disabled = !shownCard || !neighbour(shownCard.data.thumbs, shownCard.injection, shownCard.analyte, d[0]);
      b.addEventListener("click", function () { move(d[0]); });
      if (step === d[0] && !b.disabled) { focus = b; }
      nodes.push(b);
    });
    return { nodes: nodes, focus: focus };
  }
  function drawerOpen() {
    var C = components();
    return !!(C && C.drawer && C.drawer.el && C.drawer.el.getAttribute("data-open") === "true");
  }
  /* the next or previous chromatogram in the overview's order, the dialog
     kept open; a change drawn and not posted is asked about first */
  function move(step) {
    if (!shownCard || !drawerOpen() || asking()) { return; }
    var th = neighbour(shownCard.data.thumbs, shownCard.injection, shownCard.analyte, step), data = shownCard.data;
    if (!th) { return; }
    var go = function () {
      openCard(data, th.injection, th.analyte, "", null, step);
      followThumb(gridRoot, th.injection, th.analyte, components().drawer);
    };
    if (current && current.dirty && current.dirty()) { askLeave(go); } else { go(); }
  }

  /* the grid the cards are opened from */
  var gridRoot = null;
  /* the grid follows the walk: the thumbnail of the card now open scrolled
     into view and made the drawer's opener, so Close or Escape returns the
     focus to the card just reviewed */
  function followThumb(root, injection, analyte, drawer) {
    if (!root || !drawer) { return null; }
    var all = root.querySelectorAll("button.raw-thumb");
    for (var i = 0; i < all.length; i++) {
      if (all[i].getAttribute("data-injection") === injection && all[i].getAttribute("data-analyte") === analyte) {
        if (all[i].scrollIntoView) { all[i].scrollIntoView({ block: "nearest" }); }
        drawer.opener = all[i];
        return all[i];
      }
    }
    return null;
  }

  /* the question before leaving a change: the page's dialog #raw-leave,
     over the open card */
  var leaving = null;
  function leaveBox() {
    var m = doc.getElementById("raw-leave");
    if (!m || m.__raw) { return m; }
    m.__raw = true;
    doc.body.appendChild(m);        /* beside the drawer, so its place in the page sets no stacking */
    var back = null;
    function shut() {
      m.classList.remove("open");
      leaving = null;
      if (back && back.focus) { try { back.focus(); } catch (e) { /* gone */ } }
    }
    m.querySelector('[data-role="stay"]').addEventListener("click", shut);
    m.querySelector('[data-role="leave"]').addEventListener("click", function () {
      var go = leaving;
      back = null;
      shut();
      if (go) { go(); }
    });
    /* Escape answers this question only, wherever the focus is: caught
       before the drawer's own Escape, the card stays open */
    doc.addEventListener("keydown", function (e) {
      if (!m.classList.contains("open")) { return; }
      if (e.key === "Escape") { e.stopPropagation(); shut(); return; }
      if (e.key === "Tab") {        /* the focus stays on the question's two buttons */
        var stay = m.querySelector('[data-role="stay"]'), leave = m.querySelector('[data-role="leave"]');
        e.preventDefault();
        e.stopPropagation();
        (doc.activeElement === stay ? leave : stay).focus();
      }
    }, true);
    m.__ask = function (go) {
      back = doc.activeElement;
      leaving = go;
      m.classList.add("open");
      m.querySelector('[data-role="stay"]').focus();
    };
    return m;
  }
  function askLeave(go) {
    var m = leaveBox();
    if (!m) { go(); return; }
    m.__ask(go);
  }
  function asking() { var m = doc.getElementById("raw-leave"); return !!(m && m.classList.contains("open")); }

  /* one card fetched and opened in the dialog; step (-1, +1) when Previous
     or Next opened it */
  function openCard(data, injection, analyte, flash, last, step) {
    var C = components();
    if (!C || !C.drawer) { return; }
    dispose();
    shownCard = { data: data, injection: injection, analyte: analyte };
    var title = labelIn(data, analyte) + " in " + injection, head = navHead(step);
    C.drawer.open(title, '<p class="raw-note">Loading the card.</p>', { cls: "is-dialog", head: head.nodes,
                                                                        focus: head.focus });
    watchClose(C.drawer);
    var mine = ++asked;
    var url = data.card_url + "&injection=" + encodeURIComponent(injection) + "&analyte=" + encodeURIComponent(analyte);
    fetch(url, { credentials: "same-origin", headers: { "Accept": "application/json" } })
      .then(function (r) { return r.json(); })
      .then(function (a) {
        if (mine !== asked) { return; }          /* closed, or another card asked for since */
        if (a.error) {
          C.drawer.open(title, '<p class="raw-refusal">' + esc(a.error) + "</p>", { cls: "is-dialog", head: navHead().nodes });
          return;
        }
        dialog(data, a, flash, last, step);
      })
      .catch(function () {
        if (mine !== asked) { return; }
        C.drawer.open(title, '<p class="raw-refusal">The card could not be loaded.</p>',
                      { cls: "is-dialog", head: navHead().nodes });
      });
  }

  function listHref(mode, name) {
    return "?tab=raw&amp;mode=" + mode + "&amp;" + (mode === "compound" ? "analyte" : "injection") + "=" +
           encodeURIComponent(name);
  }

  /* one entry of the list down the left: a button to its page, its type
     and how many of its rows are flagged */
  function listItem(mode, i, selected) {
    return '<a class="btn-sm btn-secondary" href="' + listHref(mode, i.name) + '"' +
           (i.name === selected ? ' aria-current="true"' : "") + ">" + esc(i.label || i.name) +
           '<span class="raw-type">' + esc(i.type || "") + (i.flagged ? " · ✗ " + esc(i.flagged) : "") + "</span></a>";
  }

  function thumbButton(data, th, pendingKeys) {
    var name = data.mode === "compound" ? th.injection : shown(th);
    var cls = "raw-thumb" + (knownState(th.state) ? " is-" + th.state : "") + (th.deleted ? " is-deleted" : "");
    var pending = !!pendingKeys[th.injection + "|" + th.analyte];
    var said = [];
    if (data.mode === "compound" && th.type) { said.push(th.type); }
    if (th.state_text) { said.push(th.state_text); }
    else if (th.qualifier) { said.push(th.qualifier); }
    else if (th.conc != null) { said.push(num(th.conc)); }
    if (th.edit === "edited") { said.push("Edited"); }
    if (th.edit === "pending" || pending) { said.push("Waiting"); }
    return '<button type="button" class="' + cls + '" data-injection="' + esc(th.injection) + '" data-analyte="' +
           esc(th.analyte) + '"' + (th.state === "missing" ? ' disabled="disabled"' : "") + ">" +
           thumbSvg(th, { pending: pending }) + '<span class="raw-thumb-name">' + esc(name) + "</span>" +
           '<span class="raw-thumb-said">' + esc(said.join(" · ")) + "</span></button>";
  }

  function render(root, data) {
    var mode = data.mode === "compound" ? "compound" : "injection";
    var h = "", note = banner(data);
    if (note) { h += '<p class="raw-banner ' + note.cls + '" role="status">' + esc(note.text) + "</p>"; }
    h += '<nav class="pfas-seg pfas-seg-sm is-spaced" aria-label="View">' +
         [["compound", "By compound"], ["injection", "By injection"]].map(function (m) {
           return '<a class="pfas-seg-item' + (m[0] === mode ? ' is-on" aria-current="page"' : '"') +
                  ' href="?tab=raw&amp;mode=' + m[0] + '">' + m[1] + "</a>";
         }).join("") + "</nav>";
    h += '<div class="raw-split"><nav class="raw-list" aria-label="' + (mode === "compound" ? "Compounds" : "Injections") + '">' +
         (data.list || []).map(function (i) { return listItem(mode, i, data.selected); }).join("") +
         "</nav><div class=\"raw-overview\">";
    if ((data.cal_dropped || []).length) {
      h += '<p class="raw-dropped">Calibrators off the curve by a deleted peak: ' +
           esc(data.cal_dropped.map(function (c) { return c.injection; }).join(", ")) + "</p>";
    }
    var pendingKeys = {};
    (data.pending || []).forEach(function (p) { pendingKeys[p.injection + "|" + p.analyte] = true; });
    h += '<div class="raw-thumbs">' + (data.thumbs || []).map(function (th) {
      return thumbButton(data, th, pendingKeys);
    }).join("") + "</div></div></div>";
    root.innerHTML = h;
    gridRoot = root;
    var C = components();
    if (C && C.init) { C.init(root); }
    root.addEventListener("click", function (e) {
      var b = e.target.closest("button.raw-thumb");
      if (b && !b.disabled) { openCard(data, b.getAttribute("data-injection"), b.getAttribute("data-analyte"), "", null); }
    });
    /* the open card's keys (keyMap), caught before the drawer's own
       Escape: PageUp and PageDown walk the overview, Escape asks first when
       a change is not applied, the rest are the card's; none while the
       question or a menu is open, or with the focus outside the dialog */
    doc.addEventListener("keydown", function (e) {
      var C = components(), t = e.target || doc.body;
      if (!shownCard || !drawerOpen() || asking() || (C.menu && C.menu.isOpen())) { return; }
      if (t !== doc.body && !C.drawer.el.contains(t)) { return; }
      var k = keyMap({ key: e.key, shiftKey: e.shiftKey, ctrlKey: e.ctrlKey, metaKey: e.metaKey, altKey: e.altKey,
                       tag: t.tagName, editable: !!t.isContentEditable,
                       onChart: !!(t.getAttribute && t.getAttribute("data-role") === "traces") });
      if (!k) { return; }
      if (k.act === "previous" || k.act === "next") { e.preventDefault(); move(k.act === "previous" ? -1 : 1); return; }
      if (k.act === "close") {
        if (current && current.dirty && current.dirty()) {
          e.preventDefault();
          e.stopPropagation();
          askLeave(function () { C.drawer.close(); });
        }
        return;
      }
      if (current && current.key && current.key(k)) { e.preventDefault(); }
    }, true);
    /* back from an edit: its card again, with what the server said of it */
    var target = openTarget(window.location.search);
    if (target) {
      var last = recall();
      forget();
      if (!last || last.open !== target.injection + "|" + target.analyte) { last = null; }
      /* the browser kept none: the edit as the server says it was posted */
      if (!last && target.posted) { last = target.posted; }
      if (target.notes.length) {
        last = last || { transition: "" };
        last.notes = target.notes;
      }
      try { history.replaceState(null, "", window.location.pathname + withoutOpen(window.location.search) + window.location.hash); }
      catch (e) { /* the address stays */ }
      openCard(data, target.injection, target.analyte, target.error, last);
    }
  }

  if (doc) {
    var start = function () {
      var src = doc.getElementById("raw-data-json"), root = doc.getElementById("raw-data");
      if (src && root) { render(root, JSON.parse(src.textContent)); }
    };
    if (doc.readyState === "loading") { doc.addEventListener("DOMContentLoaded", start); } else { start(); }
  }
  var api = { baselineAt: baselineAt, peakFill: peakFill, peakOutline: peakOutline, stateClass: stateClass,
              readout: readout, details: details, cardBody: cardBody, followThumb: followThumb, flagChips: flagChips, longNotes: longNotes,
              integrationText: integrationText, signedChange: signedChange, pendingEdges: pendingEdges,
              refusedEdit: refusedEdit, neighbour: neighbour, pageStep: pageStep, edgeLevel: edgeLevel, classicBase: classicBase, adaptiveBase: adaptiveBase,
              previewPeak: previewPeak, apexPreview: apexPreview, snOf: snOf, snapIndex: snapIndex, dragTarget: dragTarget,
              editPayload: editPayload, thumbSvg: thumbSvg, chartView: chartView, areaChangePct: areaChangePct, editProblem: editProblem,
              edgeTolerance: edgeTolerance, judge: judge, pyFixed: pyFixed, pyG: pyG, shortError: shortError,
              banner: banner, openTarget: openTarget, withoutOpen: withoutOpen, postedEdit: postedEdit, dragIndex: dragIndex,
              typedEdge: typedEdge, edgeStep: edgeStep, injectionType: injectionType, deleteWarning: deleteWarning, confirmsDelete: confirmsDelete,
              knownState: knownState, listItem: listItem, apexTolerance: apexTolerance, nearestApex: nearestApex,
              matchCandidate: matchCandidate, shown: shown, labelIn: labelIn, BASELINES: BASELINES, peakNotes: peakNotes, shareOf: shareOf, outward: outward,
              walkReach: walkReach, readMargin: readMargin, readReach: readReach, halfWidths: halfWidths, counts: counts,
              levelsOutside: levelsOutside, edgeNotes: edgeNotes, HALF_WIDTH_SIGMA: HALF_WIDTH_SIGMA,
              DEFAULT_SEARCH_AMP_SN: DEFAULT_SEARCH_AMP_SN, DEFAULT_SEARCH_SLOPE: DEFAULT_SEARCH_SLOPE,
              DEFAULT_SEARCH_SMOOTH_PCT: DEFAULT_SEARCH_SMOOTH_PCT, autoWidthPoints: autoWidthPoints, handleDrag: handleDrag, postedLevels: postedLevels,
              menuEntries: menuEntries, keyMap: keyMap, chipItems: chipItems, addAt: addAt, splitAt: splitAt, geometryOf: geometryOf,
              zoomView: zoomView, panView: panView, spanY: spanY, regionView: regionView, peakView: peakView, valuesText: valuesText, countRange: countRange };
  if (typeof window !== "undefined") { window.PFAS = window.PFAS || {}; window.PFAS.rawData = api; }
  if (typeof module !== "undefined" && module.exports) { module.exports = api; }
})();
