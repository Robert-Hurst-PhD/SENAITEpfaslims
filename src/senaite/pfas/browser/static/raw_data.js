/* raw_data.js — Data Review's Integration Review tab, for a run imported from raw data.
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
  /* the fit's preview, loaded before this file (node: beside it) */
  var rawFit = (typeof window !== "undefined" && window.PFAS && window.PFAS.rawFit) ||
               (typeof require === "function" ? require("./raw_fit.js") : null);

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
  /* an axis number in scientific notation as a coefficient times 10 with a
     superscript power (2.5 × 10⁵), never e notation; zero stays "0". A
     count below 10,000 is written plainly, so one axis never mixes forms:
     axisCounts(max) gives the label function of an axis ending at max. */
  var SUPER = { "0": "\u2070", "1": "\u00b9", "2": "\u00b2", "3": "\u00b3", "4": "\u2074", "5": "\u2075",
                "6": "\u2076", "7": "\u2077", "8": "\u2078", "9": "\u2079", "-": "\u207b" };
  function sciCounts(v) {
    if (v === 0) { return "0"; }
    if (!isFinite(v)) { return String(v); }
    var parts = Math.abs(v).toExponential(2).split("e");
    var mant = parts[0].replace(/0+$/, "").replace(/\.$/, "");
    var power = String(parseInt(parts[1], 10)).replace(/./g, function (c) { return SUPER[c]; });
    return (v < 0 ? "-" : "") + mant + " \u00d7 10" + power;
  }
  /* the axis' tick values: a step of 1, 2 or 5 times a power of ten, as few
     as keep each label clear of the next (about one per `room` pixels of the
     axis), from the first step at or above min up to the last at or below
     max, which need not be max itself. */
  function niceTicks(min, max, height, room) {
    var span = max - min;
    if (!isFinite(span) || span <= 0) { return [min]; }
    var want = Math.max(2, Math.floor((height > 0 ? height : 200) / (room || 36)));
    var raw = span / want, pow = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10)), f = raw / pow;
    var step = (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * pow;
    var first = Math.ceil(min / step - 1e-9), out = [], k;
    for (k = first; k * step <= max + step * 1e-9; k += 1) {
      out.push(parseFloat((k * step).toPrecision(12)));
    }
    return out;
  }
  function axisCounts(max) {
    return function (v) { return Math.abs(max) >= 10000 ? sciCounts(v) : counts(v); };
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
  /* what a change to one injection still lacks: a reason from the lab's list,
     then a comment; "" when it has both */
  var REASON_TEXT = "Choose a reason from the lab's list.", COMMENT_TEXT = "Write a comment on the change.";
  function commentProblem(reasonId, comment) {
    if (!reasonId) { return REASON_TEXT; }
    return String(comment == null ? "" : comment).replace(/^\s+|\s+$/g, "") ? "" : COMMENT_TEXT;
  }
  function editPayload(st) {
    var out = { injection: st.injection, analyte: st.analyte, transition: field(st.transition),
                mode: st.mode || "injection", kind: st.kind, start: "", end: "", apex: "", baseline: "", confirm: "",
                level_start: "", level_end: "" };
    if (st.kind === "integrate") { out.start = field(st.start); out.end = field(st.end); }
    if (st.kind === "integrate" && st.levels) { out.level_start = field(st.levels[0]); out.level_end = field(st.levels[1]); }
    if (st.kind === "apex") { out.apex = field(st.apex); }
    /* a drop line's shared edge moved: the partner's analyte and edges, edited in the same action */
    if (st.kind === "integrate" && st.partner) {
      out.partner_analyte = field(st.partner.analyte);
      out.partner_start = field(st.partner.start);
      out.partner_end = field(st.partner.end);
    }
    if (st.kind === "integrate" || st.kind === "apex") { out.baseline = field(st.baseline); }
    if (st.kind === "delete") { out.confirm = st.confirm ? "1" : ""; }
    out.reason_id = st.kind === "revert" ? "" : field(st.reason_id);
    out.detail = st.kind === "revert" ? "" : field(st.detail);
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
     than least or with no height; heightPx, when given, is the box's height
     on the screen: a box of 8 px or less zooms time only (y null, the counts
     fit to the new window) */
  function regionView(x0, y0, x1, y1, least, heightPx) {
    var x = [Math.min(x0, x1), Math.max(x0, x1)], y = [Math.min(y0, y1), Math.max(y0, y1)];
    if (heightPx != null && heightPx <= TALL_PX && x[1] - x[0] > (least || 0)) { return { x: x, y: null }; }
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
    var w = opts.w || 160, h = opts.h || 78;
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
    if (th.peak && !th.deleted) { out += region(th.peak, isManual(th) ? "raw-spark-area is-manual" : "raw-spark-area"); }
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
  /* value with the fewest decimals (one at least) that still reads above limit (raw_preview._above) */
  function above(value, limit) {
    for (var places = 1; places < 10; places++) {
      var text = pyFixed(value, places);
      if (parseFloat(text) > limit) { return text; }
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
  /* the line the automatic peak was measured on: the processing change that made it (a change
     applied to all), else the method's */
  function autoLine(card, tr) {
    return (tr && tr.processing && tr.processing.baseline) || card.method_baseline;
  }
  /* the trapezoid over the automatic peak's edges on `baseline` (autoLine's): what the manual
     area is judged against; null when it cannot be measured */
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
     not judged here. `forAll` judges a change "Apply to all" would make: processing, not a
     manual change, so the method's smallest manual change and S/N do not apply; the hard
     limits (the fewest points, the full-resolution reach) still do. */
  function judge(card, tr, edit, forAll) {
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
      if (!forAll && limits.min_manual_change_pct == null) { throw new Error("The method's limits on a manual change are not numbers."); }
      res.auto_area = asFound ? storedAutoArea(tr) : autoArea(tr, autoLine(card, tr));
      res.change = areaChangePct(res.auto_area, manual.area);
      res.problem = forAll ? null : editProblem(edit.kind, res.auto_area, manual.area, sn, limits.min_manual_change_pct,
                                                limits.min_manual_sn);
      if (res.problem === null) { res.notes = peakNotes(manual, rules).concat(edgeNotes(tr, autoLine(card, tr), manual, rules)); }
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
  /* a processing the worker failed, or refused (never tried again) */
  function failedRun(f) { return !!f && (f.status === "failed" || f.status === "refused"); }
  /* the banner over the tab: the run's failed processing, a refused one while edits wait on it, or
     a retry; null when there is nothing to say. Edits being processed are the band's
     (processingBand), not the banner's */
  function banner(data) {
    var f = data.failure;
    /* edits made after a failed run wait on a new processing: the band says so, the old failure is not repeated */
    if (f && !data.processing && (f.status === "failed" || (f.status === "refused" && data.waiting))) {
      return { cls: "is-fail", text: "The run's last processing failed: " + (shortError(f.error) || "no reason was recorded.") };
    }
    if (f && f.status === "retrying") {
      return { cls: "is-warn", text: "The run is being processed again after a failure, attempt " + (f.attempts || 1) +
                                     (f.error ? ": " + shortError(f.error) : ".") };
    }
    return null;
  }
  /* the band under the strip while the worker processes the run (data.processing, the server's
     raw_progress): the ring, "Processing run · Started: HH:MM · Est. completion: HH:MM" and the
     smaller line under it; a store that cannot be read says so, with no ring. The words are the
     server's, on the lab's clock; "" when nothing is processed */
  function processingBand(p) {
    if (!p || !p.text) { return ""; }
    var ring = p.state === "unreadable" ? "" : '<span class="pfas-progress-ring" role="img" aria-label="Processing"></span>';
    return '<div class="pfas-busy raw-busy" role="status">' + ring + '<div class="pfas-busy-text"><span class="pfas-busy-line">' +
           esc(p.text) + "</span>" + (p.note ? '<span class="pfas-busy-note">' + esc(p.note) + "</span>" : "") + "</div></div>";
  }
  /* faint cards under each section's heading while a first import has stored nothing yet */
  var GHOSTS = { analyte: 16, surrogate: 8, internal_standard: 3 };
  function ghostSectionsHtml(pairs) {
    return (pairs || []).map(function (pair) {
      var cards = "", n = GHOSTS[pair[0]] || 8;
      for (var i = 0; i < n; i++) { cards += '<span class="raw-thumb-ghost"></span>'; }
      return '<section class="raw-section is-ghost" data-section="' + esc(pair[0]) + '">' +
             '<h3 class="raw-section-head">' + esc(pair[1]) + "</h3>" +
             '<div class="raw-thumbs" aria-hidden="true">' + cards + "</div></section>";
    }).join("");
  }

  /* ── the edit's answer and the wait for the run ──────────────────────── */
  var SESSION_ENDED = "Your session ended: sign in again, then apply.";
  var POLL_MS = 5000, STALL_MS = 60000, PAGE_POLL_MS = 5000, MIN_POLL_MS = 2000;
  /* the wait between two looks at the run's status: what the server sends (poll_ms), never under the floor,
     so a wrong figure cannot make the page hammer the server; no figure, the page's own */
  function pollEvery(sent, fallback, floor) {
    var n = parseInt(sent, 10), min = floor == null ? MIN_POLL_MS : floor;
    return Math.max(min, n > 0 ? n : fallback);
  }
  /* a watch is idle, and may be woken to look at once, when no timer waits and no look is out */
  /* the floor in force; a test lowers it through window.PFAS.rawMinPollMs, the page never sets it */
  function minPoll() {
    var o = typeof window !== "undefined" && window.PFAS ? window.PFAS.rawMinPollMs : null;
    return typeof o === "number" ? o : MIN_POLL_MS;
  }
  function watchIdle(w) { return !!w && !w.timer && !w.inFlight; }
  /* the answer to an edit posted by fetch: {ok, kind, error, notes, waiting}; a body that
     is not JSON is the sign-in page, a session that ended */
  function replyOf(text) {
    var r = null;
    try { r = JSON.parse(text); } catch (e) { r = null; }
    if (!r || typeof r !== "object" || Array.isArray(r)) { return { ok: false, session: true, error: SESSION_ENDED }; }
    var out = { ok: !!r.ok, kind: r.kind || "", error: r.error || "", notes: r.notes || [], waiting: !!r.waiting };
    /* a preview of "Apply to all" also answers what it would do */
    if (typeof r.text === "string") { out.text = r.text; out.needs_confirm = !!r.needs_confirm; out.natives = r.natives || []; out.major = !!r.major; }
    return out;
  }
  var NO_ANSWER = "The server did not answer: try again.";
  var STATUS_LOST = "The run's status could not be read: reload the page.";
  /* the answer to a fetch (its response and text): the JSON the server wrote, whatever the
     status (a refusal is JSON); else the sign-in page (a redirect, 401 or 403) is an ended
     session and any other answer is none */
  function isObject(text) {
    try { var r = JSON.parse(text); return !!r && typeof r === "object" && !Array.isArray(r); } catch (e) { return false; }
  }
  function endedSession(resp) {
    return !!resp && (resp.redirected === true || resp.status === 401 || resp.status === 403);
  }
  function replyFrom(resp, text) {
    if (isObject(text)) { return replyOf(text); }
    if (endedSession(resp)) { return { ok: false, session: true, error: SESSION_ENDED }; }
    return { ok: false, noanswer: true, error: NO_ANSWER };
  }
  /* the run's status answer: {status} or {session: true, error} or {noanswer: true, error} */
  function statusFrom(resp, text) {
    if (isObject(text)) { return { status: JSON.parse(text) }; }
    if (endedSession(resp)) { return { session: true, error: SESSION_ENDED }; }
    return { noanswer: true, error: NO_ANSWER };
  }
  /* one look at the run's status (raw_status=1) after `elapsedMs` of waiting: done when
     nothing waits, failed (and stopped) only when its processing failed after `since` (the
     time of the failure on record when the edit was posted: an older one is not this edit's);
     a retry keeps waiting */
  function pollStep(status, elapsedMs, since) {
    var f = status && status.failure;
    if (failedRun(f) && !(since && f.at && String(f.at) <= String(since))) {
      return { done: false, failed: true, text: "The run's last processing failed: " + shortError(f.error) };
    }
    if (!status || !status.waiting) { return { done: true, failed: false, text: "" }; }
    return { done: false, failed: false, text: elapsedMs >= STALL_MS ? "Still processing the run" : "Saved. Processing the run again" };
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
     ("" the quantifier), kind, edges, apex, line and levels, a fit's shape,
     apexes and the peak picked, read when the browser kept none of its own;
     null when the address names none */
  var POSTED_KINDS = ["integrate", "apex", "fit", "delete", "revert"];
  var FIT_SHAPES = ["gaussian", "emg"];
  function postedEdit(p) {
    if (POSTED_KINDS.indexOf(p.posted_kind) < 0) { return null; }
    var number = function (k) { return p[k] == null || p[k] === "" || isNaN(Number(p[k])) ? null : Number(p[k]); };
    var ls = number("posted_level_start"), le = number("posted_level_end");
    var out = { transition: p.posted_transition || "", kind: p.posted_kind, start: number("posted_start"),
                end: number("posted_end"), apex: number("posted_apex"),
                baseline: BASELINES.indexOf(p.posted_baseline) >= 0 ? p.posted_baseline : "",
                levels: ls != null && le != null ? [ls, le] : null };
    if (p.posted_kind === "fit") {
      var apexes = String(p.posted_apexes || "").split(",").filter(function (v) {
        return v !== "" && !isNaN(Number(v));
      }).map(Number);
      out.shape = FIT_SHAPES.indexOf(p.posted_shape) >= 0 ? p.posted_shape : "";
      out.apexes = apexes;
      out.pick = number("posted_pick");
      out.alone = p.posted_alone === "1";
    }
    return out;
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
     reads N.D., an isotope standard's natives lose their concentration (N.Q.), and
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

  var ALL_LEVELS = "Levels set by hand apply to this injection only.";
  var ALL_ONE = "Choosing an apex or deleting applies to this injection only.";
  var ALL_SINGLE = "Apply to all is for a single peak.";
  /* "" when the change drawn may be applied to every injection, else why it may not; the
     method's mode for the compound is the card's peak_mode, never the view's */
  function allOffered(st, a) {
    if ((a.peak_mode || "single") !== "single") { return ALL_SINGLE; }
    if (st.kind === "apex" || st.mode === "delete") { return ALL_ONE; }
    if (st.levels) { return ALL_LEVELS; }
    return "";
  }
  var ALL_NO_PEAK = "This trace has no peak to apply from.";
  /* what "Apply to all" posts (null when the trace has no peak to measure from): the edges as offsets from the automatic peak's apex, the one
     the worker measures from; a fit adds kind "fit" and its own fields here */
  function allPayload(st, tr, a) {
    /* a fit goes in absolute times: the server places it from each injection's expected time */
    if (st.kind === "fit") {
      var all = { analyte: a.analyte, transition: tr.transition || "", kind: "fit", shape: st.shape || "",
                  injection: a.injection || "", start: field(st.start), end: field(st.end),
                  apexes: fitApexText(st.apexes) };
      if (st.alone) { all.alone = "1"; }
      return all;
    }
    var apex = (tr.auto || tr.peak || {}).apex;
    if (apex == null) { return null; }
    function off(x) { return Math.round((x - apex) * 10000) / 10000; }
    return { analyte: a.analyte, transition: tr.transition || "", kind: st.kind, baseline: st.baseline || "",
             start_offset: off(st.start), end_offset: off(st.end) };
  }

  /* ── the fit tool: overlapping peaks fitted between two edges ─────────── */
  var FIT_APEXES = "Click two or three apexes between the edges.";
  var FIT_ISOTOPE = "An isotope standard's peak is not fitted.";
  var FIT_UNSET = "Set the fit limit on the method's Integration tab.";
  var FIT_MAJOR = "This changes how the compound is processed: it is countersigned at release.";
  /* the preview's interval is the covariance's; the worker judges the resampled one */
  var FIT_FINAL = "The final check uses the resampled interval.";
  var FIT_FITTING = "Fitting the peaks.";
  var FIT_FAILED = "The preview could not be computed.";
  /* past the most samples the preview fits (raw_fit.MOST_POINTS): the preview is not drawn, but the
     fit may still be applied; the cap limits the preview's cost, not what an analyst may fit */
  var FIT_WIDE = "Too long to preview: the fit is checked when the run is processed.";
  var FIT_NO_FLOOR = "Process the run again to preview the detection floor.";
  var FIT_MOST = 3;
  /* the apexes in time order, as posted: "4.2500,4.3100" */
  function fitApexSorted(apexes) {
    return (apexes || []).filter(function (v) { return typeof v === "number" && isFinite(v); })
      .sort(function (p, q) { return p - q; });
  }
  function fitApexText(apexes) {
    return fitApexSorted(apexes).map(function (v) { return v.toFixed(4); }).join(",");
  }
  /* the time the trace's peak is searched about, as the run stored it (a fit applied to all is placed
     from it); null when the trace holds none */
  /* the expected RT of a card: the quantifier's own first, then the card's, so the chart line and the pane read one */
  function expectedRtOf(a) {
    var q = (a && a.quant) || {};
    return q.expected_rt != null ? q.expected_rt : (a ? a.expected_rt : null);
  }
  function expectedOf(a, tr) {
    var v = tr && tr.expected_rt;
    return v == null || isNaN(Number(v)) ? null : Number(v);
  }
  /* the index among the apexes (in time order) nearest the expected time, the first of two equally
     near; 0 where there is no expected time */
  function defaultPick(apexes, expected) {
    var best = 0;
    if (expected == null) { return best; }
    /* the offsets to six decimals, as the server keeps them, so a tie is the same tie there */
    function off(v) { return Math.abs(Math.round((v - expected) * 1e6) / 1e6); }
    for (var i = 1; i < apexes.length; i++) {
      if (off(apexes[i]) < off(apexes[best])) { best = i; }
    }
    return best;
  }
  /* the component a fit applied to all reports, or -1 when none can be named: no apex, no expected
     time stored, or an expected time that is not between the edges */
  function fitAllPick(st, a, tr) {
    var ap = fitApexSorted(st.apexes), e = expectedOf(a, tr);
    if (!ap.length || e == null || !(st.start < e && e < st.end)) { return -1; }
    return defaultPick(ap, e);
  }
  /* the component this injection's fit reports: the one chosen, else the one nearest the expected time */
  function fitPick(st, a, tr) {
    var ap = fitApexSorted(st.apexes);
    return st.pick != null && st.pick < ap.length ? st.pick : defaultPick(ap, expectedOf(a, tr));
  }
  /* "" when the fit drawn can be applied, else what it lacks */
  function fitProblem(st) {
    var s = st.start, e = st.end, ap = fitApexSorted(st.apexes);
    if (typeof s !== "number" || typeof e !== "number" || !(s < e)) { return NO_EDGES; }
    /* one apex only for a fit alone, the fits stepper's candidate; the fit tool's own clicks are two or three */
    if (st.alone ? ap.length !== 1 : (ap.length < 2 || ap.length > FIT_MOST)) { return FIT_APEXES; }
    for (var i = 0; i < ap.length; i++) {
      if (!(s < ap[i] && ap[i] < e) || (i && ap[i] === ap[i - 1])) { return FIT_APEXES; }
    }
    return "";
  }
  /* what a fit of one injection posts besides the trace's own fields */
  function fitPayload(st, a, tr) {
    var out = { kind: "fit", shape: st.shape || "", apexes: fitApexText(st.apexes), start: field(st.start),
                end: field(st.end), pick: String(fitPick(st, a, tr)) };
    if (st.alone) { out.alone = "1"; }
    return out;
  }
  /* the apexes after a click at x: one within tol is taken away, else x is added (never a fourth) */
  function apexClick(apexes, x, tol) {
    var ap = fitApexSorted(apexes);
    for (var i = 0; i < ap.length; i++) {
      if (Math.abs(ap[i] - x) <= tol) { ap.splice(i, 1); return ap; }
    }
    if (ap.length < FIT_MOST) { ap.push(Math.round(x * 10000) / 10000); }
    return fitApexSorted(ap);
  }
  /* a multiple on two decimals, more where two would read as the limit it is under */
  function belowLimit(v, limit) {
    for (var places = 2; places < 10; places++) {
      var text = v.toFixed(places);
      if (limit == null || !(v < limit) || parseFloat(text) < limit) { return text; }
    }
    return String(v);
  }
  /* the stored fit in words: "Area 26,090 · 95 % interval 24,543 to 35,154 · residual 1.05 times the noise" */
  function fitReadout(fit) {
    fit = fit || {};
    var c = (fit.components || [])[fit.pick || 0] || {}, out = ["Area " + num(c.area, 0)];
    var ci = fit.ci, label = "95 % interval";
    if (!ci && fit.ci_approx) { ci = fit.ci_approx; label = "approximate 95 % interval"; }
    if (ci && ci.length === 2) { out.push(label + " " + num(ci[0], 0) + " to " + num(ci[1], 0)); }
    if (fit.noise_multiple != null) { out.push("residual " + belowLimit(fit.noise_multiple, fit.noise_multiple_limit) + " times the noise"); }
    return out.join(" · ");
  }
  /* a text of the worker's with its numbers put in as Python's % puts them: %s as given, %g, %% */
  function fitText(text, args) {
    var k = 0;
    return String(text).replace(/%([%sg])/g, function (m, c) {
      if (c === "%") { return "%"; }
      var v = args[k++];
      return c === "g" ? pyG(v) : String(v);
    });
  }
  /* the fit as the worker would make and judge it, previewed (raw_fit.js), with `problem`: "" or the
     worker's refusal in the words the card is sent (`words`, raw_review.fit_preview_words), the
     residual's multiple written with the fewest decimals that read over the limit; and `fit`, the
     preview as a stored fit's record, drawn alike. The approximate interval is never a refusal. */
  function fitPreview(t, y, opts, words) {
    words = words || {};
    var texts = words.texts || {}, fewest = ((words.fewest || {})[opts.shape] || {})[String((opts.apexes || []).length)];
    var o = {}, k;
    for (k in opts) { if (opts.hasOwnProperty(k)) { o[k] = opts[k]; } }
    o.fewest = fewest == null ? null : fewest;
    var res = rawFit.fit(t, y, o), why = res.refused;
    res.problem = "";
    res.own = !!why && why.key === "wide";          /* the card's own sentence, not a refusal of the worker's */
    res.unpreviewed = res.own;                      /* not drawn, but not refused: Apply stays on */
    if (res.own) {
      res.problem = FIT_WIDE;
    } else if (why) {
      var args = why.key === "residual" ? [above(why.args[0], why.args[1]), why.args[1]] : why.args;
      res.problem = fitText(texts[why.key] || why.key, args);
    }
    res.fit = res.components.length ? {
      shape: res.shape, pick: opts.pick || 0, baseline: res.baseline, span: res.span, ci_approx: res.ci_approx,
      noise_multiple: res.noise_multiple, noise_multiple_limit: opts.limit,
      components: res.components.map(function (c) { return { area: c.area, se: c.se, mu: c.mu, sigma: c.sigma, tau: c.tau }; })
    } : null;
    return res;
  }
  /* what applying a fit to all reports, said before it is made: the click nearest the expected time */
  function fitAllWords(apexes, expected, edges) {
    var ap = fitApexSorted(apexes);
    if (!ap.length) { return ""; }
    if (expected == null) {
      return "No expected time is stored for this trace, so no peak can be named.";
    }
    if (edges && !(edges[0] < expected && expected < edges[1])) {
      return "The fit's edges must lie either side of the expected time, " + pyFixed(expected, 3) + " min.";
    }
    return "In every injection the reported peak is peak " + (defaultPick(ap, expected) + 1) +
           ", the one nearest the expected time, " + pyFixed(expected, 3) + " min. " + FIT_MAJOR;
  }
  /* one fitted component at time x, above the baseline: the preview's model (raw_fit.js), the worker's */
  function fitComponentAt(shape, c, x) { return rawFit.componentAt(shape, c, x); }
  function fitBaselineAt(fit, x) { var b = fit.baseline || [0, 0, 0]; return b[0] + b[1] * (x - b[2]); }
  function fitModelAt(fit, x) {
    var y = fitBaselineAt(fit, x);
    (fit.components || []).forEach(function (c) { y += fitComponentAt(fit.shape, c, x); });
    return y;
  }
  function curveXs(from, to, n) {
    var out = [];
    for (var i = 0; i <= n; i++) { out.push(from + (to - from) * i / n); }
    return out;
  }
  /* component k over the fitted span, drawn on the baseline */
  function fitCurve(fit, k) {
    var span = fit.span || [0, 0], c = fit.components[k];
    return curveXs(span[0], span[1], 160).map(function (x) {
      return { x: x, y: fitBaselineAt(fit, x) + fitComponentAt(fit.shape, c, x) };
    });
  }
  /* the reported component's area, as the card fills it: its curve and the baseline under it,
     between mu - 3 sigma and mu + 3 sigma (+ 3 tau), inside the fitted span */
  function fitFill(fit) {
    var c = (fit.components || [])[fit.pick || 0], top = [], base = [];
    if (!c || !fit.span) { return { top: top, base: base }; }
    var lo = Math.max(fit.span[0], c.mu - 3 * c.sigma), hi = Math.min(fit.span[1], c.mu + 3 * c.sigma + (c.tau ? 3 * c.tau : 0));
    curveXs(lo, hi, 80).forEach(function (x) {
      base.push({ x: x, y: fitBaselineAt(fit, x) });
      top.push({ x: x, y: fitBaselineAt(fit, x) + fitComponentAt(fit.shape, c, x) });
    });
    return { top: top, base: base };
  }
  /* the signal less the fitted model, at the trace's samples inside the fitted span */
  function fitResidual(fit, t, y) {
    var out = [], span = fit.span || [-Infinity, Infinity];
    for (var i = 0; i < t.length; i++) {
      if (t[i] >= span[0] && t[i] <= span[1]) { out.push({ x: t[i], y: y[i] - fitModelAt(fit, t[i]) }); }
    }
    return out;
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
    return (editedByHand(tr) ? "Manual" : "Automatic") + (tr.line ? " · " + tr.line : "");
  }
  /* a peak edited by hand: an edit stored, or an automatic peak kept beside it */
  function editedByHand(tr) {
    tr = tr || {};
    return tr.edit === "edited" || (tr.auto != null && tr.edit !== "no_effect");
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
    var ion = (a.ions || []).length ? a.ions.map(ionLine).join("\n")
            : a.ion_ratio == null ? "—" : num(a.ion_ratio) + (a.ion_expected == null ? "" : ", expected " + num(a.ion_expected));
    return [["Area", num(a.area, 0), under], ["Retention time", a.rt == null ? "—" : num(a.rt) + " min", ""],
            ["S/N", num(a.sn, 1), ""], ["Ion ratio", ion, fitMixed(a, null)], ["Concentration", conc, ""],
            ["Integration", integrationText(q), ""]];
  }

  /* ── ion ratios ───────────────────────────────────────────────────────── */
  /* where the expected ratio came from, as the line says it; the mean of the
     run's calibrators is said by their count, "from 7 calibrators" */
  var ION_SOURCES = { "method": "from the method", "quantitation reference": "from the quantitation reference",
                      "export": "from the export" };
  /* a difference in whole percent, signed: "+3 %", "−20 %", "0 %" */
  function wholePct(v) {
    var s = pyFixed(Math.abs(v), 0);
    return (s === "0" ? "" : v < 0 ? "−" : "+") + s + " %";
  }
  /* one qualifier's line, named by its transition where the card knows it:
     "413.0 > 169.0: 0.214 against 0.208 expected from 7 calibrators · +3 %";
     a qualifier not calculated says so; with no expected ratio, the ratio alone */
  function ionLine(ion) {
    ion = ion || {};
    var o = ion.observed, e = ion.expected, n = ion.n_cal || 0;
    var obs = (ion.label ? ion.label + ": " : "") +
              (typeof o === "number" ? num(o) : o === "uncalculable" ? "Not calculated" : "—");
    if (typeof e !== "number" || !e) { return obs; }
    var src = ion.source === "calibrators" ? "from " + n + (n === 1 ? " calibrator" : " calibrators") : ION_SOURCES[ion.source] || "";
    return obs + " against " + num(e) + " expected" + (src ? " " + src : "") +
           (typeof o === "number" ? " · " + wholePct((o / e - 1) * 100) : "");
  }
  /* detected as the worker reads it (qc_engine.qual_quan_check): a
     concentration, or one below or above the range */
  function detectedOf(a) {
    return !!a && (a.conc != null || a.qualifier === "BLoQ" || a.qualifier === "ALoQ");
  }
  /* the line's verdict by the method's tolerance in % (null while the check
     is Off), as the worker judges: |observed ÷ expected − 1| over it fails,
     and so does a qualifier not calculated beside a detection; null with
     nothing to judge */
  function ionStatus(ion, tolPct, detected) {
    ion = ion || {};
    var icon = null;
    if (tolPct == null) { return null; }
    if (ion.observed === "uncalculable") { icon = detected ? "fail" : null; }
    else if (typeof ion.observed === "number" && typeof ion.expected === "number" && ion.expected) {
      icon = Math.abs(ion.observed / ion.expected - 1) * 100 > tolPct ? "fail" : "pass";
    }
    if (!icon) { return null; }
    return { icon: icon, label: STATUS_WORD[icon], colour: STATUS_COLOUR[icon] };
  }
  /* a qualifier's ratio while one trace's edge is dragged: the dragged
     trace's previewed area against the other's stored one, qualifier over
     quantifier; null without both areas */
  function ionPreview(draggedArea, otherArea, draggingQuant) {
    var quant = draggingQuant ? draggedArea : otherArea, qual = draggingQuant ? otherArea : draggedArea;
    if (quant == null || qual == null || !(quant > 0)) { return null; }
    return qual / quant;
  }
  /* the stored area of a trace, null for a deleted peak */
  function storedArea(tr) { return !tr || tr.deleted ? null : (tr.peak || {}).area == null ? null : tr.peak.area; }
  /* the preview's ratio words for trace `index` (0 the quantifier) at `area`:
     every qualifier's ratio when the quantifier is dragged, that
     qualifier's alone otherwise; "" with none to say */
  function ionPreviewText(a, index, area) {
    var quals = a.quals || [], vals = [];
    if (!index) { quals.forEach(function (q) { vals.push(ionPreview(area, storedArea(q), true)); }); }
    else { vals.push(ionPreview(area, storedArea(a.quant), false)); }
    if (!vals.some(function (v) { return v != null; })) { return ""; }
    return (vals.length > 1 ? "ion ratios " : "ion ratio ") + vals.map(function (v) { return num(v); }).join(", ");
  }
  /* a quantifier fitted beside a qualifier integrated: the ratio sets the
     two areas side by side, which the card says. `fitting` is the trace
     being fitted (0 the quantifier, k the k-th qualifier), which counts as
     fitted; null for the stored peaks alone */
  var FIT_MIXED = "Quantifier fitted, qualifier integrated";
  function fitMixed(a, fitting) {
    var fitted = fitting === 0 || !!(a.quant || {}).fit;
    return fitted && (a.quals || []).some(function (q, k) { return fitting !== k + 1 && !q.fit && !q.deleted; }) ? FIT_MIXED : "";
  }
  /* said before a change to a calibrator whose ratio feeds an expected one
     (the card's ion_warning: a qualifier's expected ratio is the
     calibrators' mean), or, with `all`, before a change applied to all
     injections, which reaches every calibrator (ion_warning_all); nothing
     when no other injection would be judged again */
  function calibratorWarning(a, all) {
    var w = (a || {})[all ? "ion_warning_all" : "ion_warning"];
    if (!w || !w.feeds || !w.samples) { return ""; }
    return (all ? "The calibrators' ratios feed" : "This calibrator's ratio feeds") + " the expected ion ratio: " + w.samples +
           (w.samples === 1 ? " sample" : " samples") + " will be checked again.";
  }
  /* a measure the card carries beside the quantifier's own record */
  function measure(a, k) { return a[k] != null ? a[k] : (a.quant || {})[k]; }
  /* the six ways a peak is integrated or fitted, [key, name], one wording for the pane and the chart's menu */
  var FIT_METHODS = [["valley", "Valley to valley"], ["drop", "Perpendicular drop"], ["flat", "Flat at the lower edge"], ["skim", "Tangent skim"],
                     ["gaussian", "Gaussian fit"], ["emg", "EMG fit"]];
  function fitMethodName(key) {
    for (var i = 0; i < FIT_METHODS.length; i++) { if (FIT_METHODS[i][0] === key) { return FIT_METHODS[i][1]; } }
    return "—";
  }
  /* the method the stored peak was integrated by: the fit's shape, else the baseline */
  function fitMethodOf(q) {
    q = q || {};
    return q.fit && q.fit.shape ? q.fit.shape : q.baseline;
  }
  /* the fits the stepper offers: each fitting method the worker scored for the quantifier's peak,
     in the stored order, [{method, name, score, cand}]; a run with no stored scores offers the six
     methods unscored, on the peak's current edges (cand is null) */
  function fitSteps(a) {
    var scores = ((a && a.quant) || {}).fit_scores, steps;
    if (!scores || !scores.length) {
      steps = FIT_METHODS.map(function (m) { return { method: m[0], name: m[1], score: null, cand: null }; });
    } else {
      steps = scores.map(function (c) {
        return { method: c.method, name: fitMethodName(c.method), score: c.score == null ? null : c.score, cand: c };
      });
    }
    /* an isotope standard's peak is not fitted: no fit among the steps, as the menu's fit tool is shut */
    return a && a.is_standard ? steps.filter(function (x) { return x.method !== "gaussian" && x.method !== "emg"; }) : steps;
  }
  /* the step the stepper opens on: the peak's stored fitting method, else the first */
  function fitStart(a, steps) {
    var m = fitMethodOf((a && a.quant) || {});
    for (var i = 0; i < steps.length; i++) { if (steps[i].method === m) { return i; } }
    return 0;
  }
  function checkIcon(name, fallback) {
    var I = icons();
    return (I && I.svg(name, { hidden: true })) || fallback;
  }
  /* a stepper built once into `bar`: a Previous button, the output, a Next button. Later calls change only what
     differs, in place, so the button pressed keeps the keyboard focus and the output's new words are announced;
     a button that goes disabled under the focus hands it to its partner. o: attr (the data- name of the
     buttons), labels [previous, next], off [previous, next], text, title (on both buttons), hidden */
  function paintStepper(bar, o) {
    var btns = bar.querySelectorAll("button"), out = bar.querySelector("output"), i;
    if (btns.length !== 2 || !out) {
      var title = o.title ? ' title="' + esc(o.title) + '"' : "";
      bar.innerHTML = '<button type="button" class="btn btn-sm btn-secondary" data-' + o.attr + '="-1" aria-label="' + esc(o.labels[0]) + '"' + title + ">" +
        checkIcon("open", "Previous") + '</button><output aria-live="polite"></output>' +
        '<button type="button" class="btn btn-sm btn-secondary" data-' + o.attr + '="1" aria-label="' + esc(o.labels[1]) + '"' + title + ">" +
        checkIcon("open", "Next") + "</button>";
      btns = bar.querySelectorAll("button");
      out = bar.querySelector("output");
    }
    for (i = 0; i < 2; i++) {
      if (!!btns[i].disabled !== !!o.off[i]) { btns[i].disabled = !!o.off[i]; }
      if (o.title) { btns[i].setAttribute("title", o.title); } else if (btns[i].getAttribute("title")) { btns[i].removeAttribute("title"); }
    }
    if (out.textContent !== o.text) { out.textContent = o.text; }
    bar.hidden = !!o.hidden;
    var act = doc && doc.activeElement;
    for (i = 0; i < 2; i++) {
      if (act === btns[i] && btns[i].disabled && !btns[1 - i].disabled && btns[1 - i].focus) { btns[1 - i].focus(); }
    }
  }
  /* the words under the smoothing stepper: why it is shut, what is previewed against the stored step, that a
     drawn edit went with it (and is sent no further), and that it was set aside (Ctrl+Z brings it back) */
  var SMOOTH_ASIDE = "Your drawn edit was set aside; Ctrl+Z brings it back.";
  function smoothNote(o) {
    var out = [];
    if (o.blocked) { out.push(o.blocked); }
    if (o.preview) {
      out.push("Previewing " + o.name + " smoothing on this peak. The stored setting is " + o.stored + ".");
      if (o.drawn) { out.push(o.drawn); }
    }
    if (o.aside) { out.push(SMOOTH_ASIDE); }
    return out.join(" ");
  }
  /* the score badge: the shown candidate's total, passing at the method's threshold, and an arrow
     opening each check's points and the total against the threshold. No score (an unscored
     candidate, a peak integrated by hand) is a dash and no arrow. A check's outcome is an icon
     and, for a screen reader, the words met or not met. `labels` maps a check's key to its
     words (the card's check_labels); `open` is the breakdown's state. */
  function scoreBadge(step, threshold, labels, open) {
    if (!step || step.score == null) { return '<span class="raw-score-badge"><span class="raw-score-num">\u2014</span></span>'; }
    labels = labels || {};
    var checks = (step.cand && step.cand.checks) || [], pass = step.score >= threshold;
    var rows = checks.map(function (c) {
      return '<li class="raw-check is-' + (c.ok ? "pass" : "fail") + '">' +
             checkIcon(c.ok ? "pass" : "fail", "") +
             '<span class="raw-check-name">' + esc(labels[c.key] || c.key) + "</span>" +
             '<span class="raw-check-pts">' + esc(c.points) + " of " + esc(c.max) + "</span>" +
             '<span class="sr-only">' + (c.ok ? "met" : "not met") + "</span></li>";
    }).join("");
    return '<span class="raw-score-badge ' + (pass ? "is-pass" : "is-warn") + '"><span class="raw-score-num">' + esc(step.score) + "</span>" +
           '<span class="sr-only">' + (pass ? "meets" : "is under") + " the threshold of " + esc(threshold) + "</span>" +
           '<button type="button" class="raw-score-more" aria-expanded="' + (open ? "true" : "false") +
           '" aria-controls="raw-score-checks" aria-label="Score breakdown">' + checkIcon("expand", "More") + "</button></span>" +
           '<ul class="raw-score-checks" id="raw-score-checks"' + (open ? "" : " hidden") + ">" + rows +
           '<li class="raw-check-total">Total ' + esc(step.score) + " of 100 against " + esc(threshold) + "</li></ul>";
  }
  /* the smoothing stepper: Low, Mid and High from the card's smoothing_steps (half-widths; the server
     decides which are allowed, a null is skipped). A window is 2m + 1 points. */
  var SMOOTH_NAMES = ["Low", "Mid", "High"], SMOOTH_KEYS = ["low", "mid", "high"];
  function smoothingList(a) {
    var s = (a && a.smoothing_steps) || {};
    return SMOOTH_KEYS.map(function (k, i) { return { name: SMOOTH_NAMES[i], m: s[k] == null ? null : s[k] }; });
  }
  /* the step the card opens on: the change in force (its window), else Mid */
  function smoothingStart(a, list) {
    for (var i = 0; i < list.length; i++) {
      if (list[i].m != null && 2 * list[i].m + 1 === (a || {}).smoothing_in_force_points) { return i; }
    }
    return 1;
  }
  /* the next step allowed from `at` in the direction dir (-1 or 1), or -1 */
  function smoothingNext(list, at, dir) {
    for (var i = at + dir; i >= 0 && i < list.length; i += dir) { if (list[i].m != null) { return i; } }
    return -1;
  }
  /* a smoothing change is a compound's: only "Apply to this injection" with another smoothing than the
     stored one asks first; "Apply to all" never does */
  function needsSmoothingWarning(stored, chosen, button) {
    return button === "one" && stored != null && chosen != null && stored !== chosen;
  }
  /* Apply sends the smoothing alone while an edit is also drawn: said beside the stepper and in the question */
  function smoothingDropsEdges(label) {
    return "Apply sends the smoothing for every " + label + " peak; your drawn edges are not sent. Draw them again once the run has been processed.";
  }
  function smoothingWarning(label, count, kept) {
    var text = "Smoothing cannot be kept for one injection. Applying it updates every " + label + " peak in this run, " +
               count + " injections, and refits them.";
    if (kept > 0) {
      text += " " + kept + " " + label + (kept === 1 ? " peak integrated by hand keeps its edges." : " peaks integrated by hand keep their edges.");
    }
    return text;
  }
  /* the trace drawn smoothed over 2m + 1 points as its engine reads it, [{x, y}] */
  function smoothedLine(tr, m) {
    var y = tr.y || [], n = null;
    try { n = engineSmoothing(tr.engine || "classic", y, 2 * m + 1, m); } catch (err) { n = null; }
    return (tr.t || []).map(function (x, i) { return { x: x, y: smoothed(y, i, n) }; });
  }
  function unitText(v, d, unit) { return v == null || v === "" ? "—" : num(v, d) + unit; }
  /* the pane's rows by group, [[group, [[label, value, key, extra]]]]. The
     key names the rows judged against the method (rt, asymmetry, sn,
     qual_sn, ion_ratio); extra is {under: a second line} or, on an ion
     ratio row, {index: the qualifier's place in a.ions} */
  function paneRows(a, editable) {
    var q = a.quant || {}, auto = q.auto || {}, under = null;
    var change = q.auto && !q.deleted ? signedChange(auto.area, a.area) : null;
    if (change != null) { under = "automatic " + num(auto.area, 0) + " · change " + signedPct(change); }
    var conc = a.state === "nd" ? "N.D." : (a.conc == null ? "—" : num(a.conc) + (a.unit ? " " + a.unit : ""));
    var peak = q.peak || {}, levels = measure(a, "baseline_levels") || [];
    var baseStart = levels[0] != null ? levels[0] : peak.base_start, baseEnd = levels[1] != null ? levels[1] : peak.base_end;
    var expectedRt = expectedRtOf(a);
    var asym = a.asymmetry == null ? "—" : num(a.asymmetry, 2), asymUnder = null;
    if (a.asymmetry == null && a.asymmetry_note) {
      asymUnder = "Not measured: " + String(a.asymmetry_note).replace(/(to|at) 10 %( of the apex height)?/, "to the level needed");
    }
    var edgeRows = editable === false ? [["Start RT", unitText(peak.start, 3, " min")], ["End RT", unitText(peak.end, 3, " min")]] : [];
    var mixed = fitMixed(a, null);
    var valley = measure(a, "valley_share"), drop = measure(a, "drop_rt");
    var ions = (a.ions || []).length ? a.ions : [{ observed: a.ion_ratio, expected: a.ion_expected }];
    var ionRows = [];
    ions.forEach(function (ion, i) {
      var tag = ions.length > 1 && ion.label ? " " + ion.label : "", o = ion.observed;
      ionRows.push(["Ion ratio" + tag, typeof o === "number" ? num(o) : o === "uncalculable" ? "Not calculated" : "—", "ion_ratio",
                    i === 0 && mixed ? { index: i, under: mixed } : { index: i }]);
      ionRows.push(["Expected ion ratio" + tag, typeof ion.expected === "number" ? num(ion.expected) : "—", undefined, { index: i }]);
    });
    return [
      ["Result", [["Concentration", conc], ["Area", num(a.area, 0), undefined, under ? { under: under } : undefined],
                  ["Height", measure(a, "height") == null ? "—" : counts(measure(a, "height"))]]],
      ["Peak", [["Retention time", unitText(a.rt, 3, " min"), "rt"], ["Expected RT", unitText(expectedRt, 3, " min")],
                ["Asymmetry", asym, "asymmetry", asymUnder ? { under: asymUnder } : undefined],
                ["Tailing", a.tailing == null ? "—" : num(a.tailing, 2)], ["FWHM", unitText(a.fwhm_s, 1, " s")],
                ["Plates", a.plates == null ? "—" : num(a.plates, 0)]]],
      ["Integration", edgeRows.concat([["Drop-line RT", unitText(drop, 3, " min")], ["Valley share", valley == null ? "—" : num(valley, 0) + " %"],
                       ["Baseline at start", baseStart == null ? "—" : counts(baseStart)],
                       ["Baseline at end", baseEnd == null ? "—" : counts(baseEnd)],
                       ["Fitting method", fitMethodName(fitMethodOf(q))], ["Integration", integrationText(q)]])],
      ["Smoothing", []],
      ["Signal", [["S/N", num(a.sn, 1), "sn"], ["Qualifier S/N", a.qual_sn == null ? "—" : num(a.qual_sn, 1), "qual_sn"]].concat(ionRows)],
      ["Source", [["Isotope standard", a.is ? shown(a.is) : "—"], ["File transition", a.file_transition || "—"]]]
    ];
  }
  /* what places the apex label: its words, kind, spot and the plot it is kept inside; the same key is the same place */
  function labelKey(L, px, py, ca) {
    ca = ca || {};
    return [L.lines.join("|"), L.manual ? 1 : 0, Math.round(px * 2), Math.round(py * 2), ca.left, ca.right, ca.top, ca.bottom].join(":");
  }
  /* the chart's label by the apex, {lines, manual, x, y}: the peak's time and
     area; null for a deleted or missing peak. `t` is the trace shown */
  function peakLabel(a, t, isQuant) {
    t = t || {};
    var p = t.peak || {}, rt = isQuant ? a.rt : p.apex, area = isQuant ? a.area : p.area;
    if (t.deleted || rt == null) { return null; }
    return { lines: ["RT " + num(rt, 3) + " min", "Area " + num(area, 0)], manual: editedByHand(t), x: rt };
  }
  /* "1": the Details are shown, "0": hidden; nothing stored: shown */
  var DETAILS_KEY = "pfas.raw.details";
  function detailsChoice(stored) { return stored !== "0"; }
  function readDetails() {
    try { return detailsChoice(window.localStorage.getItem(DETAILS_KEY)); } catch (e) { return true; }
  }
  function writeDetails(on) {
    try { window.localStorage.setItem(DETAILS_KEY, on ? "1" : "0"); } catch (e) { /* not remembered */ }
  }
  /* the fit's state by its short name: "Fit refused", "Pair fit failed" */
  function fitName(text) { return String(text || "").split(":")[0]; }
  /* the flags under the readout as chips, {cls: a badge class, text}: the
     result's flags (a failure on a row that failed, else a warning: the
     row carries no kind of its own), the fit by a short name,
     and what the method notes of a manual peak drawn (notes: a warning) */
  function flagChips(a, notes) {
    var out = (a.flags || []).map(function (f) { return { cls: a.state === "fail" ? "badge-fail" : "badge-warn", text: f }; });
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
    if (a.fit_text && a.fit_text !== fitName(a.fit_text)) { out.push(a.fit_text); }
    if (a.note) { out.push(a.note); }
    return out;
  }

  /* the readout strip and the flags (the notes on a manual peak drawn
     join them), under the charts; a line for what the card says it did */
  /* an editable cell of the readout: the integration's start or end time as a box,
     marked by a pencil and a dashed edge; the edit is the card's own (pending until Re-integrate) */
  var PENCIL = '<svg class="raw-pencil" viewBox="0 0 16 16" aria-hidden="true" focusable="false" fill="none" ' +
               'stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' +
               '<path d="M2 14l1-4 8-8 3 3-8 8z"/><path d="M9.5 3.5l3 3"/></svg>';
  function edgeCell(edge, label) {
    return '<div class="raw-edit-cell"><dt>' + label + PENCIL + '</dt><dd><input type="number" step="any" data-edge="' +
           edge + '" aria-label="' + label + ', min" title="Edit, then Re-integrate" /> <span class="raw-unit">min</span></dd></div>';
  }
  /* a value judged against a method limit is marked by colour, and a screen
     reader hears the verdict in words; no verdict, the plain value. Only the
     rows the method judges use it. */
  var VERDICT_WORDS = { pass: "within the method's limit", warn: "near the method's limit", fail: "outside the method's limit" };
  function verdictCell(value, verdict) {
    if (!VERDICT_WORDS.hasOwnProperty(verdict)) { return esc(value); }
    return '<span class="raw-verdict is-' + verdict + '">' + esc(value) + '<span class="sr-only"> \u00b7 ' +
           VERDICT_WORDS[verdict] + "</span></span>";
  }
  /* the verdict of a keyed row: the card's own, and for an ion row the one at its index */
  function rowVerdict(key, index, verdicts) {
    var v = verdicts && key ? verdicts[key] : null;
    if (key === "ion_ratio") { v = v && index != null ? v[index] : null; }
    return v || null;
  }
  /* the rows of one group as a list of label and value; a keyed row carries
     its key (and a qualifier's index) for the colour rule */
  function rowHtml(r, verdicts) {
    var extra = r[3] || {}, attrs = (r[2] ? ' data-key="' + r[2] + '"' : "") + (extra.index != null ? ' data-index="' + extra.index + '"' : "");
    return '<div class="raw-row"' + attrs + "><dt>" + esc(r[0]) + "</dt><dd>" + verdictCell(r[1], rowVerdict(r[2], extra.index, verdicts)) +
           (extra.under ? '<span class="raw-under">' + esc(extra.under) + "</span>" : "") + "</dd></div>";
  }
  /* what a group holds besides its rows: the score and the fit stepper, the
     Start and End boxes, the smoothing stepper */
  function groupHead(name, editable) {
    if (name === "Integration") {
      return '<div class="raw-step" data-role="fits"></div><p class="raw-note" data-role="fit-note" hidden></p>' +
             (editable ? '<dl class="raw-edge-pair">' + edgeCell("start", "Start") + edgeCell("end", "End") + "</dl>" : "");
    }
    return name === "Smoothing" ? '<div class="raw-step" data-role="smoothing"></div><p class="raw-smooth-note" data-role="smooth-note" role="status" hidden></p>' : "";
  }
  /* the pane: the groups, then the notes behind the chips and the curve the concentration was read on */
  function cardHead(a, editable) {
    var h = '<div class="raw-pane-col" data-role="pane"><div class="raw-score" data-role="score"></div>';
    paneRows(a, !!editable).forEach(function (g) {
      h += '<section class="raw-grp"><h3 class="raw-gh">' + esc(g[0]) + "</h3>" + groupHead(g[0], editable) +
           (g[1].length ? '<dl class="raw-kv">' + g[1].map(function (r) { return rowHtml(r, a.verdicts); }).join("") + "</dl>" : "") + "</section>";
    });
    longNotes(a).forEach(function (n) { h += '<p class="raw-note">' + esc(n) + "</p>"; });
    if (a.conc != null) {
      h += '<p class="raw-curve">Quantified against the run\'s curve ' +
           '<a class="btn-sm btn-secondary" href="?tab=calibration">Calibration</a></p>';
    }
    return h + "</div>";
  }
  /* the flags and the line for what the card said it did, under the chart */
  function cardFlags(a) {
    return '<ul class="raw-flags" data-role="flags">' + chipItems(flagChips(a)) + "</ul>" +
           '<p class="raw-note" data-role="said" aria-live="polite"></p>';
  }

  /* the card's body as the dialog draws it: the server's refusal (flash), the
     Trace switch and the trace line, then two columns: the chart column (the
     zoom tools, the chart and its residual, the flags and, editable, the edit's
     boxes and preview) and the pane of grouped values; the edit itself is made
     on the chart and its menu */
  /* the chart's zoom tools: in, out, the whole window (a box is dragged on an empty area, not a button) */
  function zoomIcon(path) {
    return '<svg viewBox="0 0 16 16" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" ' +
           'stroke-width="1.6" stroke-linecap="round">' + path + "</svg>";
  }
  var LENS = '<circle cx="6.5" cy="6.5" r="4.5"/><path d="M10 10l4.5 4.5"/>';
  var ZOOM_BAR = '<div class="raw-zoom" role="toolbar" aria-label="Zoom the chart" data-role="zoom">' +
    [["in", "Zoom in", LENS + '<path d="M4.5 6.5h4M6.5 4.5v4"/>'],
     ["out", "Zoom out", LENS + '<path d="M4.5 6.5h4"/>'],
     ["full", "Back to the whole window", '<path d="M6 2H2v4M10 2h4v4M6 14H2v-4M10 14h4v-4"/>']].map(function (b) {
      return '<button type="button" class="btn btn-sm btn-secondary" data-zoom="' + b[0] + '" title="' + b[1] +
             '" aria-label="' + b[1] + '"' + ">" + zoomIcon(b[2]) +
             "</button>";
    }).join("") + '<button type="button" class="btn btn-sm btn-secondary raw-details-toggle" aria-pressed="true">Details</button></div>';
  /* whether the card's drop line is an edge the quantifier shares with its partner's peak */
  function sharesEdge(a, q) {
    var peak = q && q.peak, rt = measure(a, "drop_rt");
    if (!a || !a.partner || !peak || rt == null || !q.t || !q.full_res) { return false; }
    var tol = 2 * edgeTolerance(q.t, q.full_res), side = dropSide(peak, rt, tol);
    var theirs = side === "end" ? a.partner.start : side === "start" ? a.partner.end : null;
    return typeof theirs === "number" && Math.abs(theirs - rt) <= tol + 1e-9;
  }
  function dragHint(a, q) {
    return '<p class="raw-note raw-drag-hint">Drag on the chart to zoom in. Double-click for the whole window. ' +
           'Drag an edge, or the drop line, anywhere along its band. ' +
           (sharesEdge(a, q) ? "The drop line moves the shared edge of both peaks." : "The drop line moves this peak's edge only.") + "</p>";
  }
  function cardBody(a, traces, index, editable, flash) {
    var h = "";
    if (flash) { h += '<p class="raw-refusal" role="alert">' + esc(flash) + "</p>"; }
    if (traces.length > 1) {
      h += seg("Trace", traces.map(function (tr, i) {
        return [String(i), i === 0 ? "Quantifier" : "Qualifier" + (traces.length > 2 ? " " + i : "")];
      }), String(index));
    }
    h += '<p class="raw-trace-line" data-role="trace-line"></p>';
    h += '<div class="raw-peak-grid"><div class="raw-chart-col"><div class="raw-charts">' + ZOOM_BAR + (editable ? dragHint(a, traces[0]) : "") +
         '<div class="raw-chart raw-chart-edit" data-role="wrap">' +
         '<canvas data-role="traces" tabindex="0" role="application" aria-label="The trace, its peak and baseline. ' +
         'Menu key for its actions."></canvas><span class="raw-peak-label" data-role="peak-label" hidden="hidden"></span></div>' +
         '<div class="raw-residual" data-role="residual" hidden="hidden"><canvas data-role="residual-canvas" ' +
         'aria-label="What the fit leaves of the signal"></canvas></div>';
    h += "</div>";
    h += '<p class="raw-note" data-role="fit-readout"></p>';
    h += cardFlags(a);
    if (editable) {
      h += '<div class="raw-edit" data-role="edit">' +
           '<div class="raw-pane" data-pane="integrate">' +
             '<div class="raw-edges">' +
               '<label hidden="hidden">Start level, counts <input type="number" step="any" data-level="start" /></label>' +
               '<label hidden="hidden">End level, counts <input type="number" step="any" data-level="end" /></label>' +
             "</div>" +
             '<p class="raw-preview" data-role="preview" aria-live="polite"></p>' +
             '<p class="raw-note" data-role="edge-note" aria-live="polite"></p>' +
             '<p class="raw-refusal" data-role="problem" role="alert"></p>' +
           "</div>" +
           '<div class="raw-pane" data-pane="fit" hidden="hidden">' +
             '<div class="raw-fit-options">' + seg("Shape", [["gaussian", "Gaussian"], ["emg", "EMG"]], "gaussian") +
               '<span data-role="fit-report"></span></div>' +
             '<p class="raw-note" data-role="fit-hint">Click each apex on the chart, up to three. Click one again to take it away.</p>' +
             '<p class="raw-refusal" data-role="fit-problem" role="alert"></p>' +
             '<p class="raw-note" data-role="fit-picked"></p>' +
             '<p class="raw-preview" data-role="fit-preview" aria-live="polite"></p>' +
             '<p class="raw-note" data-role="fit-final" hidden="hidden">' + FIT_FINAL + "</p>" +
             '<p class="raw-note" data-role="fit-floor" hidden="hidden">' + FIT_NO_FLOOR + "</p>" +
           "</div>" +
           '<div class="raw-pane" data-pane="delete" hidden="hidden"><p class="raw-warning" data-role="delete-text"></p></div>' +
           '<div class="raw-pane" data-pane="revert" hidden="hidden"><p>Back to the automatic integration.</p>' +
             '<p class="raw-warning" data-role="revert-warning"' + (calibratorWarning(a) ? "" : ' hidden="hidden"') + ">" +
             esc(calibratorWarning(a)) + "</p></div>" +
           "</div>";
    }
    h += "</div>" + cardHead(a, editable) + "</div>";
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
    if (last.kind === "fit") {
      return { mode: "fit", kind: "fit", shape: last.shape || "gaussian", apexes: fitApexSorted(last.apexes), alone: !!last.alone,
               start: last.start == null ? null : last.start, end: last.end == null ? null : last.end,
               pick: last.pick == null ? null : last.pick, touched: true };
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
  /* the card Previous (-1) or Next (+1) opens from the open one, in the overview's order. A card that has left Show
     (fixed, undone) is not in that order: the step goes from its place in the whole sorted run to the next card
     that does pass Show, so the buttons never go dead under it */
  function stepFrom(data, injection, analyte, step) {
    var shownList = displayedThumbs(data), at = neighbour(shownList, injection, analyte, step);
    var inList = shownList.some(function (th) { return th.injection === injection && th.analyte === analyte; });
    if (inList || !data || (data.processing && data.processing.first)) { return at; }
    var f = data.filter || filterRead(null), pendingKeys = pendingKeysOf(data), all = [];
    sectionsOf(orderThumbs(data.thumbs, f.sort, data.mode, pendingKeys), data.sections).forEach(function (sec) { all = all.concat(sec.items); });
    var shownKeys = {};
    shownList.forEach(function (th) { shownKeys[th.injection + "\u0000" + th.analyte] = true; });
    for (var i = 0; i < all.length; i++) {
      if (all[i].injection === injection && all[i].analyte === analyte) {
        for (var j = i + step; j >= 0 && j < all.length; j += step) {
          if (shownKeys[all[j].injection + "\u0000" + all[j].analyte]) { return all[j]; }
        }
        return null;
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

  /* what a press takes and what it then does: target (null for an empty
     area) and the pointer's movement in px since the press. An empty area
     dragged past 4 px is a zoom box, otherwise a click (in the fit tool an
     apex, in every mode a click); a handle, the drop line, the expected-time line, the baseline and
     the axis keep their own drag. */
  var CLICK_PX = 4, SNAP_PX = 6, GRAB_PX = 9, TALL_PX = 8;
  function pressKind(target, movedPx) {
    if (target === "start" || target === "end") { return "edge"; }
    if (target === "drop" || target === "axis" || target === "rt" || target === "line") { return target; }
    return movedPx > CLICK_PX ? "zoom" : "click";
  }
  /* a pointer height within SNAP_PX of the signal's is on the signal: the level is not set by hand */
  function onSignal(pointerPx, signalPx) { return Math.abs(pointerPx - signalPx) <= SNAP_PX; }
  /* the edge a press at px takes: the nearer of the two within GRAB_PX of its
     time, at any height ("start" when equally near), else null */
  function edgeAt(px, startPx, endPx) { return dragTarget(px, startPx, endPx, GRAB_PX); }
  /* of the offers [{kind, d (px away), limit (px)}] in priority order, the nearest within its limit;
     a tie goes to the earlier */
  function nearestPress(offers) {
    var best = null, bestD = Infinity;
    for (var i = 0; i < offers.length; i++) {
      if (offers[i].d <= offers[i].limit && offers[i].d < bestD) { best = offers[i].kind; bestD = offers[i].d; }
    }
    return best;
  }
  /* the side ("start" or "end") of the peak's own edge the drop line is, that
     edge's time being drop_rt; null when there is none or it is neither */
  function dropSide(peak, dropRt, tol) {
    if (dropRt == null || !peak) { return null; }
    var near = function (v) { return typeof v === "number" && Math.abs(v - dropRt) <= (tol || 0) + 1e-9; };
    var ds = near(peak.start) ? Math.abs(peak.start - dropRt) : Infinity, de = near(peak.end) ? Math.abs(peak.end - dropRt) : Infinity;
    return ds === Infinity && de === Infinity ? null : ds <= de ? "start" : "end";
  }
  /* what the partner's edit is when the shared edge of a drop is moved to newEdge on this peak's
     `side`: the partner {analyte, start, end} (its own other edge kept), or null where the card
     knows no partner, the partner's edge is not the shared one (within tol) or nothing moved */
  function partnerEdit(side, newEdge, partner, dropRt, tol) {
    /* nothing moved: the edge is on the shared edge's own sample (half a sample either way; the
       tolerance is a whole sample, as dropSide reads the edge) */
    if (!partner || !side || typeof newEdge !== "number" || dropRt == null || Math.abs(newEdge - dropRt) <= (tol || 0) / 2 + 1e-9) { return null; }
    var own = side === "end" ? partner.start : partner.end;
    if (typeof own !== "number" || Math.abs(own - dropRt) > (tol || 0) + 1e-9) { return null; }
    return { analyte: partner.analyte, start: side === "end" ? newEdge : partner.start, end: side === "end" ? partner.end : newEdge };
  }
  /* the level the held handle would take at the pointer's time with no level set by hand: the
     line's value there (flat: the flat level), on the sample dragIndex gives */
  function signalAt(h, x) {
    var side = h.held === "start" ? 0 : h.held === "end" ? 1 : -1;
    if (side < 0) { return null; }
    var i = dragIndex(h.t, x, h.fullRes, h.held, h.start, h.end);
    if (i < 0) { return null; }
    var sig = h.signal(side === 0 ? h.t[i] : h.start, side === 1 ? h.t[i] : h.end);
    return sig ? sig[side] : null;
  }

  /* a handle dragged, or double-clicked: h {held "start", "end", "drop" or
     "line", dropSide (the edge the drop line is), t, fullRes, start, end,
     levels [left, right] (the line's values at the edges as drawn), manual
     [left, right] (a level set by hand), baseline, signal(start, end) (the
     line's values at those edges with no level set by hand), range (the
     counts a level may take), from {start, end, x} (the line's edges and the
     pointer's time when it was pressed)}; p {x, y (the pointer's time and
     count; either may be left out), snapped (the pointer is within SNAP_PX
     of the signal), shift (the level kept on the signal), reset (a
     double-click)}. There is no direction lock: a held edge takes the
     pointer's sample (dragIndex) and, in the same move, its level is the
     pointer's count inside the trace's range (flat: both ends, the line
     kept level), unless snapped or Shift, which keep it on the signal; the
     drop line moves its edge in time only; the line moves both edges by the
     same samples. Gives {start, end, levels, manual}. */
  function handleDrag(h, p) {
    var start = h.start, end = h.end, manual = [!!(h.manual || [])[0], !!(h.manual || [])[1]];
    var levels = (h.levels || [null, null]).slice();
    var side = h.held === "start" ? 0 : h.held === "end" ? 1 : h.held === "drop" ? (h.dropSide === "start" ? 0 : h.dropSide === "end" ? 1 : -1) : -1;
    var flat = h.baseline === "flat", drop = h.held === "drop";
    function onSig(k) { if (flat || k < 0) { manual = [false, false]; } else { manual[k] = false; } }
    /* the drop line with no shared edge to hold moves nothing, never the whole line */
    if (drop && side < 0) { return { start: start, end: end, levels: levels, manual: manual }; }
    if (p.reset || p.shift) { onSig(side); }
    if (!p.reset && side >= 0) {
      if (p.x != null) {
        var i = dragIndex(h.t, p.x, h.fullRes, side === 0 ? "start" : "end", start, end);
        if (i >= 0) { if (side === 0) { start = h.t[i]; } else { end = h.t[i]; } }
      }
      if (!drop && p.y != null && !p.shift && !p.snapped) {
        var v = clampTo(p.y, h.range);
        if (flat) { manual = [true, true]; levels = [v, v]; } else { manual[side] = true; levels[side] = v; }
      } else if (!drop && p.snapped) {
        onSig(side);
      }
    } else if (!p.reset && side < 0 && h.held !== "drop" && h.from) {
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
     full-resolution region (its mean spacing), measured on the line it was
     processed on (autoLine); null when it cannot be read */
  function autoWidthPoints(card, tr, span) {
    var auto = tr.auto || tr.peak || {}, t = tr.t || [];
    if (auto.start == null || auto.end == null || !(span[1] > span[0])) { return null; }
    var w;
    try {
      var ref = tracePreview(tr, auto.start, auto.end, autoLine(card, tr));
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

  var BASELINE_ENTRIES = ["valley", "drop", "skim", "flat"].map(function (k) { return [k, fitMethodName(k)]; });
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
    entry("fit", "Fit overlapping peaks", "", s.standard ? FIT_ISOTOPE : s.fitLimit == null ? FIT_UNSET : null);
    out.push({ sep: true });
    entry("delete", "Delete peak", "Del", s.deleted ? "The peak is deleted." : null, { confirm: !!s.confirm });
    entry("undo", "Undo edit", "U", s.edited ? null : "The trace is not edited.");
    entry("restore", "Restore automatic", "", s.edited || s.changed ? null : "The trace is automatic.",
          { discard: !!s.changed });
    out.push({ sep: true });
    /* the compound's expected time on the method, from the quantifier's
       found apex as the run stored it; only where the card offers it */
    var rt = s.setRt;
    if (rt) {
      entry("set-rt", "Set as expected retention time", "",
            !rt.quant ? "The expected time is set from the quantifier peak." :
            rt.rt == null ? "No detected peak to take the time from." :
            rt.pending ? "An edit of this peak waits for the run to be processed." :
            rt.expected != null && Math.round(rt.expected * 1e4) === Math.round(rt.rt * 1e4) ?
              "The expected retention time is already " + pyFixed(rt.rt, 3) + " min." : null);
      out.push({ sep: true });
    }
    entry("zoom-peak", "Zoom to peak", "Z", edges || s.peak ? null : "No peak to zoom to.");
    entry("zoom-window", "Zoom to window", "W");
    entry("copy", "Copy values", "");
    return out;
  }

  /* ── the expected retention time, a line on the chart ─────────────────── */
  /* the times every trace of the compound holds, [lo, hi]: the latest first
     time to the earliest last time, where the expected time may be set
     (expected_rt.span); null when no trace holds a time */
  function rtSpan(traces) {
    var lo = -Infinity, hi = Infinity, any = false;
    (traces || []).forEach(function (o) {
      var t = (o && o.t) || [];
      if (t.length) { any = true; lo = Math.max(lo, t[0]); hi = Math.min(hi, t[t.length - 1]); }
    });
    return any && lo <= hi ? [lo, hi] : null;
  }
  /* the time the line dragged to x is set at: the stored sample of t nearest
     x inside span, kept to the ten-thousandth of a minute as the method
     keeps it and never past span's ends; null when span holds no sample */
  function rtDragTime(t, x, span) {
    if (!span || x == null || !isFinite(x)) { return null; }
    var i = snapIndex(t, Math.max(span[0], Math.min(span[1], x)), span);
    if (i < 0) { return null; }
    var v = Math.round(t[i] * 1e4) / 1e4;
    if (v < span[0]) { v = Math.ceil(span[0] * 1e4) / 1e4; }
    if (v > span[1]) { v = Math.floor(span[1] * 1e4) / 1e4; }
    return v;
  }
  /* a press at px takes the line drawn at linePx, within tol pixels */
  function rtHit(px, linePx, tol) {
    return linePx != null && isFinite(linePx) && Math.abs(px - linePx) <= tol;
  }
  /* the fields posted to set the time: the card's, and the time where the
     line was dragged (none: the server takes the quantifier's found apex) */
  function rtPayload(a, mode, time) {
    var out = { injection: a.injection, analyte: a.analyte, mode: mode || "injection" };
    if (time != null) { out.rt = String(time); }
    return out;
  }
  /* what is said once the method holds the new time, or why it does not */
  function rtSetText(name, was, now) {
    return name + ": expected retention time set to " + pyFixed(now, 3) + " min" +
           (was == null ? "." : ", was " + pyFixed(was, 3) + " min.");
  }
  function rtRefusedText(name, error) {
    return name + ": expected retention time not set. " + (error || "The server could not be reached.");
  }
  /* the line's label */
  function rtLabel(v) { return "Expected " + pyFixed(v, 3) + " min"; }

  /* the dialog's keys: e {key, shiftKey, ctrlKey, metaKey, altKey, tag
     (the focused element's), editable (a contenteditable), onChart (the
     chart has the focus)}; {act, by} or null. Nothing in a text box but
     Escape (asking first when a change is not applied); arrows, Tab and
     the menu key only on the chart. Cmd acts as Ctrl; Alt gives none. */
  var KEY_ACTS = { "[": "start", "]": "end", d: "level", a: "add", s: "split", u: "undo", z: "zoom-peak",
                   w: "zoom-window", Delete: "delete", "+": "zoom-in", "=": "zoom-in", "-": "zoom-out", "0": "zoom-window",
                   "?": "keys" };
  function keyMap(e) {
    var k = e.key, tag = String(e.tag || "").toUpperCase(), mod = !!(e.ctrlKey || e.metaKey);
    if (k === "Escape") { return { act: "close" }; }
    if (e.altKey) { return null; }
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(tag) || e.editable) { return null; }
    if (mod) {
      var low = k && k.length === 1 ? k.toLowerCase() : k;
      if (low === "z") { return { act: e.shiftKey ? "step-forward" : "step-back" }; }
      if (low === "y") { return { act: "step-forward" }; }
      if (low === "s") { return { act: "apply-one" }; }
      if (k === "ArrowLeft" || k === "ArrowRight") { return { act: "injection", by: k === "ArrowLeft" ? -1 : 1 }; }
      if (k === "ArrowUp" || k === "ArrowDown") { return { act: "compound", by: k === "ArrowUp" ? -1 : 1 }; }
      return null;
    }
    var page = pageStep(k, tag);
    if (page) { return { act: page < 0 ? "previous" : "next" }; }
    if (e.onChart) {
      if (k === "ArrowLeft" || k === "ArrowRight") { return { act: "nudge", by: (k === "ArrowLeft" ? -1 : 1) * (e.shiftKey ? 5 : 1) }; }
      if (k === "Tab") { return { act: "handle", by: e.shiftKey ? -1 : 1 }; }
      if (k === "ContextMenu" || (k === "F10" && e.shiftKey)) { return { act: "menu" }; }
    }
    if (k === "Enter") { return /^(BUTTON|A|SUMMARY)$/.test(tag) ? null : { act: "apply" }; }
    var act = KEY_ACTS.hasOwnProperty(k) ? KEY_ACTS[k] : (k && k.length === 1 ? KEY_ACTS[k.toLowerCase()] : null);
    return act ? { act: act } : null;
  }

  /* the card's drawing, step by step: each snapshot is the drawing before a change.
     back(current) gives the one before (null when none) and keeps current for forward */
  function EditStack(limit) {
    this.limit = limit || 100;
    this.undo = [];
    this.redo = [];
  }
  EditStack.prototype.push = function (snapshot) {
    this.undo.push(snapshot);
    if (this.undo.length > this.limit) { this.undo.shift(); }
    this.redo = [];
  };
  EditStack.prototype.back = function (current) {
    if (!this.undo.length) { return null; }
    this.redo.push(current);
    if (this.redo.length > this.limit) { this.redo.shift(); }
    return this.undo.pop();
  };
  EditStack.prototype.forward = function (current) {
    if (!this.redo.length) { return null; }
    this.undo.push(current);
    if (this.undo.length > this.limit) { this.undo.shift(); }
    return this.redo.pop();
  };
  EditStack.prototype.clear = function () { this.undo = []; this.redo = []; };

  /* the keys panel: [keys, what it does, the keyMap act] */
  var KEYS_HELP = [
    ["[", "Set the start edge at the cursor", "start"],
    ["]", "Set the end edge at the cursor", "end"],
    ["D", "Set the level at the cursor", "level"],
    ["A", "Add a peak at the cursor", "add"],
    ["S", "Split the peak at the cursor", "split"],
    ["Delete", "Delete the peak", "delete"],
    ["U", "Undo the saved edit", "undo"],
    ["Ctrl+Z", "Undo a drawing step", "step-back"],
    ["Ctrl+Y or Ctrl+Shift+Z", "Redo a drawing step", "step-forward"],
    ["Ctrl+S", "Apply to this injection", "apply-one"],
    ["Enter", "Apply to this injection", "apply"],
    ["Left or Right on the chart", "Move the handle one sample, Shift five", "nudge"],
    ["Tab on the chart", "Move between the two handles", "handle"],
    ["Menu key or Shift+F10", "Open the peak menu", "menu"],
    ["Z", "Zoom to the peak", "zoom-peak"],
    ["W or 0", "Zoom to the whole window", "zoom-window"],
    ["+ or =", "Zoom in", "zoom-in"],
    ["-", "Zoom out", "zoom-out"],
    ["Ctrl+Left or Ctrl+Right", "Previous or next injection", "injection"],
    ["Ctrl+Up or Ctrl+Down", "Previous or next compound", "compound"],
    ["Page Up", "Previous card", "previous"],
    ["Page Down", "Next card", "next"],
    ["?", "Show these keys", "keys"],
    ["Escape", "Close this list, then the card", "close"]
  ];
  /* where Ctrl+Left, Right, Up or Down goes: the injection (axis "injection") or the compound
     (axis "compound") by steps from this one, the other kept; null at either end */
  function stepTarget(data, injection, analyte, axis, by) {
    var list = axis === "compound" ? data.analytes : data.injections, own = axis === "compound" ? analyte : injection;
    var names = (list || []).map(function (x) { return x && typeof x === "object" ? x.name : x; });
    var at = names.indexOf(own), to = at + by;
    if (at < 0 || to < 0 || to >= names.length) { return null; }
    return axis === "compound" ? { injection: injection, analyte: names[to] } : { injection: names[to], analyte: analyte };
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
  /* the trace line on the card: the light theme draws it in a darker token,
     which holds 3:1 over the manual fill; the dark theme keeps its series */
  var LIGHT_TRACE = "--s-info-text";
  function traceToken(index, dark) { return dark ? SERIES[index % SERIES.length] : LIGHT_TRACE; }
  /* the integrated area's fill: amber for a manual peak (an edit applied,
     waiting, or kept with no effect), teal for an automatic one */
  function isManual(tr) {
    return tr.edit === "edited" || tr.edit === "pending" || tr.edit === "no_effect";
  }
  function fillToken(tr) { return isManual(tr) ? "--s-manual-fill" : "--s-primary-lt"; }
  /* a view part way from one to another, eased out (cubic); f in [0, 1] */
  function easedView(from, to, f) {
    var k = Math.max(0, Math.min(1, f)), e = 1 - Math.pow(1 - k, 3);
    return [from[0] + (to[0] - from[0]) * e, from[1] + (to[1] - from[1]) * e];
  }

  /* a plain chart: the traces, the first's peak shaded (the isotope standard's) */
  function form() { return doc.getElementById("raw-edit"); }
  function components() { return window.PFAS && window.PFAS.components; }

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
  var current = null, asked = 0, watching = false, poll = null, generation = 0, chain = null;
  function stopPoll() { if (poll) { clearTimeout(poll); poll = null; } }
  function dispose() {
    if (current) {
      if (current.chart) { current.chart.destroy(); }
      if (current.resChart) { current.resChart.destroy(); }
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
               at: null, handle: "start", view: null, line: null, drawn: null, chartFocus: false,
               rt: expectedRtOf(a) == null ? null : Number(expectedRtOf(a)), rtDrag: null, rtBusy: false, busy: {}, saying: null, saidShown: false };
    current = ui;
    var keep = last && last.hasView ? last : null;
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
    var foot = el("div", "pfas-drawer-actions"), submit = null, allBtn = null, allLine = null, backBtn = null;
    var actionsBtn = el("button", "btn btn-secondary", "Actions");
    actionsBtn.type = "button";
    actionsBtn.setAttribute("aria-haspopup", "menu");
    actionsBtn.setAttribute("aria-expanded", "false");
    actionsBtn.setAttribute("data-role", "actions");
    foot.appendChild(actionsBtn);
    var commentBox = null, reasonSel = null, detailBox = null, commentGo = null, commentHint = null, ionWarn = null;
    if (editable) {
      submit = el("button", "btn btn-primary", "Apply to this injection");
      submit.type = "button";
      submit.setAttribute("data-role", "apply-one");
      foot.insertBefore(submit, actionsBtn);
      /* the peak goes back to the automatic integration; directly left of Apply, as the review board draws it */
      backBtn = el("button", "btn btn-secondary");
      backBtn.type = "button";
      backBtn.setAttribute("data-role", "revert");
      backBtn.innerHTML = checkIcon("revert", "") + '<span data-role="revert-words">Back to automatic</span>';
      foot.insertBefore(backBtn, submit);
      /* "Apply to all N injections": a preview first, then Confirm; no reason or comment is asked */
      allBtn = el("button", "btn btn-secondary", "Apply to all " + a.injection_count + " injections");
      allBtn.type = "button";
      allBtn.setAttribute("data-role", "apply-all");
      foot.insertBefore(allBtn, actionsBtn);
      allLine = el("p", "raw-note");
      allLine.setAttribute("data-role", "all-line");
      allLine.hidden = true;
      foot.appendChild(allLine);
      /* the reason (the lab's list) and a comment, asked when the change is made */
      commentBox = el("div", "raw-comment");
      commentBox.setAttribute("data-role", "comment");
      commentBox.hidden = true;
      var rl = el("label", "raw-comment-reason", "Reason ");
      reasonSel = el("select");
      reasonSel.setAttribute("data-role", "reason");
      var ro = el("option", "", "Choose a reason");
      ro.value = "";
      reasonSel.appendChild(ro);
      (a.reasons || []).forEach(function (r) {
        var o = el("option");
        o.value = r.id;
        o.textContent = r.text;
        reasonSel.appendChild(o);
      });
      rl.appendChild(reasonSel);
      var dl = el("label", "raw-comment-detail", "Comment ");
      detailBox = el("textarea");
      detailBox.setAttribute("data-role", "detail");
      detailBox.setAttribute("rows", "2");
      dl.appendChild(detailBox);
      commentHint = el("p", "raw-note");
      commentHint.setAttribute("data-role", "comment-problem");
      commentGo = el("button", "btn btn-primary", "Apply");
      commentGo.type = "button";
      commentGo.setAttribute("data-role", "comment-apply");
      /* a calibrator whose ratio feeds the expected ion ratio says so before its Apply */
      ionWarn = el("p", "raw-warning");
      ionWarn.setAttribute("data-role", "ion-warning");
      ionWarn.hidden = true;
      [rl, dl, commentHint, ionWarn, commentGo].forEach(function (n) { commentBox.appendChild(n); });
      foot.appendChild(commentBox);
    }
    var head = navHead(step);
    C.drawer.open(shown(a) + " in " + a.injection, body, { cls: "is-dialog raw-dialog-wide", footer: foot,
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
    /* the expected-time line: on the quantifier, where the card offers the
       route and the method holds a time; where it is being dragged to */
    function rtOn() { return !!a.set_rt_url && ui.index === 0 && (ui.rt != null || ui.rtDrag != null); }
    function rtShown() { return ui.rtDrag != null ? ui.rtDrag : ui.rt; }
    function line() { return st.baseline || a.method_baseline; }
    /* a change drawn and not posted: Previous and Next ask before leaving it */
    ui.dirty = function () {
      return editDrawn() || (editable && smoothChanged());
    };
    /* an edge or fit edit drawn and not posted */
    function editDrawn() {
      return !!(editable && st && ((st.mode === "integrate" && st.touched) || (st.mode === "fit" && fitApexSorted(st.apexes).length)));
    }
    /* the card's drawing as a stack of snapshots (Ctrl+Z, Ctrl+Y); a snapshot is pushed before
       each change commits: a drag, a typed edge, the line, a level, add, split, an apex chosen */
    ui.stack = new EditStack();
    function snapshot() { return JSON.parse(JSON.stringify(st)); }
    /* the drawing before a change goes on the stack only when the change altered it */
    function recorded(was) { if (JSON.stringify(was) !== JSON.stringify(snapshot())) { ui.stack.push(was); } }
    function restoreDrawing(snap) {
      for (var k in st) { if (st.hasOwnProperty(k)) { delete st[k]; } }
      for (var k2 in snap) { if (snap.hasOwnProperty(k2)) { st[k2] = snap[k2]; } }
      ui.asideNote = false;
      ui.armed = false;
      ui.commentOpen = false;
      boxes();
      update();
    }
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
    /* the edge of this peak the drop line is, only for the quantifier under a drop: the shared edge
       drop_rt, which the stored peak holds as its start or end */
    function dropSideOf() {
      var t = tr();
      return line() === "drop" && ui.index === 0 ? dropSide(t.peak, measure(a, "drop_rt"), 2 * edgeTolerance(t.t, t.full_res || limits())) : null;
    }
    /* what a handle's drag reads: the edit as drawn */
    function handleState(held, from) {
      var t = tr();
      return { held: held, dropSide: dropSideOf(), t: t.t, fullRes: t.full_res, start: st.start, end: st.end,
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
    /* a drag repaints at most once a frame; under reduced motion on release only */
    function repaintDrag() {
      if (!window.requestAnimationFrame) { update(); return; }
      ui.dragDirty = true;
      if (reduced()) { return; }
      if (ui.dragFrame) { return; }
      ui.dragFrame = window.requestAnimationFrame(function () {
        ui.dragFrame = 0;
        if (ui.dragDirty) { ui.dragDirty = false; update(); }
      });
    }
    function flushDrag() {
      if (ui.dragFrame) { window.cancelAnimationFrame(ui.dragFrame); ui.dragFrame = 0; }
      if (ui.dragDirty) { ui.dragDirty = false; update(); }
    }
    function takeDrag(d, dragging) {
      var was = snapshot();
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
      if (!dragging) { recorded(was); }
      else if (!ui.dragOpen && JSON.stringify(was) !== JSON.stringify(snapshot())) { ui.dragOpen = true; ui.stack.push(was); }   /* a drag is one step */
      boxes();
      if (dragging) { repaintDrag(); } else { update(); }
    }
    /* the baseline drawn at another line: the levels set by hand kept where the handles are */
    function setLine(mode) {
      var was = snapshot();
      st.baseline = mode === a.method_baseline ? "" : mode;
      if (st.kind === "integrate" && (st.manual[0] || st.manual[1]) && edgesSet()) {
        st.levels = postedLevels(line(), st.start, st.end, st.handles || ui.drawn, st.manual,
                                 line() === "drop" ? dropBounds(st.start, st.end) : null, countRange(tr()));
      }
      st.mode = "integrate";
      if (st.kind === "fit") { st.kind = "integrate"; st.alone = false; }    /* a line is not a fit */
      st.touched = true;
      recorded(was);
      update();
    }
    function setEdges(start, end, baseline) {
      var was = snapshot();
      st.mode = "integrate";
      st.kind = "integrate";
      st.start = start;
      st.end = end;
      if (baseline != null) { st.baseline = baseline === a.method_baseline ? "" : baseline; }
      seedLevels(null);
      st.touched = true;
      st.note = "";
      recorded(was);
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
               fitLimit: a.fit_limit, standard: !!a.is_standard,
               confirm: confirmsDelete(a, ui.index, false), peak: !!(t.peak && t.peak.start != null),
               setRt: a.set_rt_url ? { quant: ui.index === 0, rt: a.quant && a.quant.deleted ? null : a.rt,
                                       expected: expectedRtOf(a), pending: tr().edit === "pending" } : null };
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
      if (st.mode === "fit" && (id === "start" || id === "end")) {
        var wasEdge = snapshot();
        st[id] = typedEdge(t.t, ui.at, t.full_res, id).value;
        recorded(wasEdge);
        boxes();
        update();
      } else if (id === "fit") {
        enterFit();
      } else if (id === "start" || id === "end") {
        takeDrag(handleDrag(handleState(id), { x: ui.at }));
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
        var wasDel = snapshot();
        st.mode = "delete";
        ui.armed = false;
        recorded(wasDel);
        update();
      } else if (id === "undo" || (id === "restore" && !e.discard)) {
        var wasRev = snapshot();
        st.mode = "revert";
        recorded(wasRev);
        update();
      } else if (id === "restore") {
        var wasRes = snapshot();
        startState();                 /* the change drawn is let go */
        recorded(wasRes);
        boxes();
        update();
      } else if (id === "zoom-peak") {
        var s = edgesSet() ? st.start : (t.peak || {}).start, en = edgesSet() ? st.end : (t.peak || {}).end;
        zoomTo(peakView(s, en, limits()));
      } else if (id === "zoom-window") {
        zoomTo(null);
      } else if (id === "copy") {
        copyValues();
      } else if (id === "set-rt") {
        setExpected(null);
      }
    }
    /* the fit tool: the edges as drawn (else the stored peak's), no apex clicked yet, the shape kept */
    function enterFit() {
      var was = snapshot(), p = tr().peak || {};
      var edges = edgesSet() ? [st.start, st.end] : [p.start == null ? null : p.start, p.end == null ? null : p.end];
      st.mode = "fit";
      st.kind = "fit";
      st.alone = false;             /* the fit tool's own clicks are two or three apexes */
      st.shape = st.shape || "gaussian";
      st.apexes = [];
      st.pick = null;
      seedLevels(null);             /* levels set by hand apply to one injection only */
      st.start = edges[0];
      st.end = edges[1];
      st.note = "";
      recorded(was);
      boxes();
      update();
    }
    /* the apexes after a click at time x; the picked peak stays the one at its time */
    function clickApex(x, tol) {
      var was = snapshot(), old = fitApexSorted(st.apexes), at = st.pick != null ? old[st.pick] : null;
      st.apexes = apexClick(old, x, tol);
      if (st.apexes.length !== 1) { st.alone = false; }       /* a second apex makes it the fit tool's own fit */
      st.pick = at == null ? null : (st.apexes.indexOf(at) < 0 ? null : st.apexes.indexOf(at));
      recorded(was);
      update();
    }
    /* a time onto the method, posted to the analyst's own route with no
       reload: the dragged line's time, or none for the quantifier's found
       apex, which the server reads from the run. The line then stays where
       the method holds it, what was set is said and Next takes the focus,
       so the next compound is one key away; a refusal puts the line back
       and says why. */
    function setExpected(time) {
      if (ui.rtBusy) { return; }
      ui.rtBusy = true;
      var name = shown(a), fd = new window.FormData(), p = rtPayload(a, data.mode, time);
      for (var k in p) { if (p.hasOwnProperty(k)) { fd.append(k, p[k]); } }
      if (f && f.elements._authenticator) { fd.append("_authenticator", f.elements._authenticator.value); }
      function done(j) {
        ui.rtBusy = false;
        ui.rtDrag = null;
        if (j && j.ok) {
          ui.rt = a.expected_rt = j["new"];
          if (a.quant && a.quant.expected_rt != null) { a.quant.expected_rt = j["new"]; }
          announce(rtSetText(name, j.old, j["new"]), false);
          if (current === ui) { focusNext(); }
        } else {
          announce(rtRefusedText(name, j && j.error), true);
        }
        if (current === ui) { paint(lastRes); }
      }
      window.fetch(a.set_rt_url, { method: "POST", body: fd, credentials: "same-origin",
                                   headers: { "Accept": "application/json" } })
        .then(function (r) { return r.json(); })
        .then(done, function () { done(null); });
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
    /* the milliseconds a zoom takes: the reveal time, none when the person prefers reduced motion */
    function reduced() {
      var mq = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
      return !!(mq && mq.matches);
    }
    function zoomMs() { return reduced() ? 0 : parseFloat(token("--t-reveal")) || 0; }
    function setScales(x, y) {
      var o = ui.chart.options.scales;
      o.x.min = x[0]; o.x.max = x[1]; o.y.min = y[0]; o.y.max = y[1];
      ui.chart.update("none");
      placeLabel();
      if (ui.resChart) {
        ui.resChart.options.scales.x.min = x[0];
        ui.resChart.options.scales.x.max = x[1];
        ui.resChart.update("none");
      }
    }
    /* the view set at once (instant: a pan under the pointer) or eased to */
    function zoomTo(view, counts, instant) {
      ui.view = view;
      ui.yview = view && counts ? counts : null;
      if (ui.zoomFrame) { window.cancelAnimationFrame(ui.zoomFrame); ui.zoomFrame = 0; }
      if (!ui.chart) { return; }
      var v = view || windowView(), y = countsFor(v), ms = instant ? 0 : zoomMs(), o = ui.chart.options.scales;
      if (!ms || !window.requestAnimationFrame) { setScales(v, y); return; }
      var chart = ui.chart, fromX = [o.x.min, o.x.max], fromY = [o.y.min, o.y.max], t0 = null;
      function frame(now) {
        ui.zoomFrame = 0;
        if (ui.chart !== chart) { return; }
        if (t0 === null) { t0 = now; }
        var f = (now - t0) / ms;
        setScales(easedView(fromX, v, f), easedView(fromY, y, f));
        if (f < 1) { ui.zoomFrame = window.requestAnimationFrame(frame); }
      }
      ui.zoomFrame = window.requestAnimationFrame(frame);
    }
    /* the narrowest view: eight edge tolerances either side */
    function leastSpan() { var t = tr(); return 8 * 2 * edgeTolerance(t.t, t.full_res || limits()); }
    /* the Details button shows or hides the pane and the label; the choice is remembered */
    var detailsBtn = body.querySelector(".raw-details-toggle"), detailsOn = readDetails();
    function showDetails(on) {
      detailsOn = on;
      C.drawer.el.classList.toggle("is-bare", !on);
      if (detailsBtn) { detailsBtn.setAttribute("aria-pressed", on ? "true" : "false"); }
      placeLabel();
    }
    showDetails(detailsOn);
    if (detailsBtn) { detailsBtn.addEventListener("click", function () { showDetails(!detailsOn); writeDetails(detailsOn); }); }
    var zoomBar = body.querySelector('[data-role="zoom"]');
    if (zoomBar) {
      zoomBar.addEventListener("click", function (e) {
        var b = e.target && e.target.closest ? e.target.closest("[data-zoom]") : null;
        if (!b || !ui.chart) { return; }
        var z = b.getAttribute("data-zoom"), cur = [ui.chart.scales.x.min, ui.chart.scales.x.max];
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
          backgroundColor: token(fillToken(t)), fill: "-1" },
        { label: "automatic", data: t.auto ? peakOutline(t.t, t.y, t.auto) : [], borderColor: token("--s-secondary"),
          borderWidth: 1, borderDash: [2, 3], pointRadius: 0, showLine: true },
        { label: t.transition, data: points(t), borderColor: token(traceToken(ui.index, doc.documentElement.getAttribute("data-theme") === "dark")),
          borderWidth: 1.5,
          pointRadius: 0, showLine: true }];
      others.forEach(function (o) {
        sets.push({ label: o.transition, data: points(o), borderColor: token("--s-border"), borderWidth: 1,
                    pointRadius: 0, showLine: true });
      });
      /* a smoothing previewed: the trace as that smoothing draws it, dashed */
      if (ui.smoothPreview && ui.smoothM != null) {
        sets.push({ label: "smoothed", data: smoothedLine(t, ui.smoothM), borderColor: token("--smooth-preview"), borderWidth: 1.5,
                    borderDash: [4, 3], pointRadius: 0, showLine: true });
      }
      /* the fit shown: each component dashed on its baseline */
      var stored = ui.fitDrawn = fitShown();
      fitSets(stored).forEach(function (d) { sets.push(d); });
      var view = chartView(t, traces), x = ui.view || view.x, y = ui.view ? countsFor(x) : view.y;
      drawResidual(stored, x);        /* before the chart, so the chart is the last one made */
      ui.chart = new window.Chart(canvas, {
        type: "scatter", data: { datasets: sets }, plugins: [LABEL_PLUGIN],
        options: { animation: false, maintainAspectRatio: false,
                   layout: { padding: { top: 8, right: 12, bottom: 4, left: 4 } },
                   plugins: { legend: { display: false }, annotation: { annotations: {} } },
                   scales: { x: { title: { display: true, text: "Retention time (min)" }, min: x[0], max: x[1] },
                             y: { title: { display: true, text: "Intensity (counts)" }, min: y[0], max: y[1],
                                  afterBuildTicks: function (axis) {
                                    axis.ticks = niceTicks(axis.min, axis.max, axis.height).map(function (v) { return { value: v }; });
                                  },
                                  ticks: { callback: function (v) { return axisCounts(this.max)(v); } } } } }
      });
      placeLabel();
      if (wrap) { gestures(wrap); }
    }
    /* the label by the apex: the time and area of the peak shown. It is placed again on every layout of the
       chart (a resize, the Details toggle, a change of columns), hidden when the apex lies outside the x scale,
       and kept whole inside the plot */
    function placeLabel(c) {
      var lab = body.querySelector('[data-role="peak-label"]'), t = tr(), chart = c || ui.chart;
      if (!lab) { return; }
      var L = peakLabel(a, t, ui.index === 0), sx = chart && chart.scales && chart.scales.x;
      if (!L || !chart || !sx || L.x < sx.min || L.x > sx.max) { lab.hidden = true; ui.labelKey = "hidden"; return; }
      var ca = chart.chartArea, i = nearest(t.t, L.x);
      var px = sx.getPixelForValue(L.x), py = chart.scales.y.getPixelForValue(t.y[i]);
      /* a drag lays the chart out on every frame: nothing moved, nothing is measured (a measure forces a layout) */
      var key = labelKey(L, px, py, ca);
      if (key === ui.labelKey && !lab.hidden) { return; }
      ui.labelKey = key;
      lab.innerHTML = "<span>" + esc(L.lines[0]) + "</span><span>" + esc(L.lines[1]) + "</span>";
      lab.classList.toggle("is-manual", L.manual);
      lab.hidden = false;
      var w = lab.offsetWidth || 0, h = lab.offsetHeight || 0;
      lab.style.left = Math.min(Math.max(px, ca.left + w / 2), Math.max(ca.right - w / 2, ca.left + w / 2)) + "px";
      lab.style.top = Math.min(Math.max(py - 8, ca.top + h), ca.bottom) + "px";
    }
    var LABEL_PLUGIN = { id: "peakLabel", afterLayout: function (c) { placeLabel(c); } };

    /* the fit drawn: the preview while the fit tool is open (none until it is made), else the stored fit */
    function fitShown() {
      var t = tr();
      if (st && st.mode === "fit") { return ui.previewFit || null; }
      return t.fit && !t.deleted && t.fit.components && t.fit.span ? t.fit : null;
    }
    function fitSets(fit) {
      return (fit ? fit.components : []).map(function (c, k) {
        return { label: "fitted peak " + (k + 1), data: fitCurve(fit, k), borderColor: token("--s-secondary"),
                 borderWidth: 1, borderDash: [4, 3], pointRadius: 0, showLine: true };
      });
    }
    /* the fit shown drawn again on the chart as it stands: its components and the residual strip */
    function drawFit() {
      if (!ui.chart) { return; }
      var shownFit = ui.fitDrawn = fitShown(), sets = ui.chart.data.datasets.filter(function (d) { return !/^fitted peak /.test(d.label); });
      ui.chart.data.datasets = sets.concat(fitSets(shownFit));
      drawResidual(shownFit, ui.view || chartView(tr(), traces).x);
      paint(lastRes);
    }
    /* the chart's fit made the one to show, when it is not: the stored fit leaves as the fit tool opens */
    function syncFit() { if (fitShown() !== (ui.fitDrawn || null)) { drawFit(); } }

    /* the fit previewed as drawn (raw_fit.js): made a moment after the last change, as clicks and
       drags come in bursts, and never for a drawing the fit tool already says is incomplete; Apply
       waits for it, and stays off while the worker would refuse the fit */
    var PREVIEW_WAIT = 150;
    function previewKey() {
      return JSON.stringify([ui.index, st.shape || "gaussian", fitApexSorted(st.apexes), st.start, st.end, fitPick(st, a, tr())]);
    }
    function previewOk() {
      return !!ui.preview && ui.previewKey === previewKey() && (!ui.preview.problem || !!ui.preview.unpreviewed);
    }
    function schedulePreview() {
      if (!st || st.mode !== "fit" || fitProblem(st)) {
        if (ui.previewTimer) { clearTimeout(ui.previewTimer); ui.previewTimer = 0; }
        ui.preview = ui.previewKey = null;
        ui.previewFit = null;
        syncFit();
        return;
      }
      var key = previewKey();
      if (key === ui.previewKey) { return; }
      ui.previewKey = key;
      ui.preview = null;
      if (ui.previewTimer) { clearTimeout(ui.previewTimer); }
      ui.previewTimer = setTimeout(function () {
        ui.previewTimer = 0;
        if (current !== ui || ui.previewKey !== key || st.mode !== "fit") { return; }
        var t = tr();
        try {
          ui.preview = fitPreview(t.t, t.y, { apexes: fitApexSorted(st.apexes), shape: st.shape || "gaussian", start: st.start,
                                              end: st.end, pick: fitPick(st, a, t), limit: a.fit_limit, noise: t.sigma,
                                              minSn: t.min_sn }, a.fit_preview);
        } catch (err) {
          /* a preview that fails says so and leaves Apply off */
          ui.preview = { problem: FIT_FAILED, own: true, components: [], fit: null };
        }
        ui.previewFit = ui.preview.fit;
        drawFit();
        update();
      }, PREVIEW_WAIT);
    }

    /* the residual strip under the chart: what the fit shown leaves, on the chart's own time axis */
    function drawResidual(stored, x) {
      if (ui.resChart) { ui.resChart.destroy(); ui.resChart = null; }
      var box = body.querySelector('[data-role="residual"]'), rc = body.querySelector('canvas[data-role="residual-canvas"]');
      if (box) { box.hidden = !stored; }
      if (!stored || !rc) { return; }
      var t = tr();
      ui.resChart = new window.Chart(rc, {
        type: "scatter",
        data: { datasets: [{ label: "residual", data: fitResidual(stored, t.t, t.y), borderColor: token("--s-secondary"),
                             borderWidth: 1, pointRadius: 0, showLine: true }] },
        options: { animation: false, maintainAspectRatio: false, plugins: { legend: { display: false } },
                   scales: { x: { min: x[0], max: x[1], title: { display: true, text: "min" } },
                             y: { title: { display: true, text: "residual" }, ticks: { maxTicksLimit: 3 } } } } });
    }

    /* the shading, the baseline and its handles, the candidates as the edit stands */
    function paint(res) {
      if (!ui.chart) { return; }
      var t = tr(), sets = ui.chart.data.datasets, top = [], base = [], ln = null;
      /* an edit waiting for the run is drawn until the analyst changes it */
      var pe = !st.touched && st.mode === "integrate" ? ui.pending : null;
      var p = (res && res.preview) || (pe && pe.preview);
      var pf = st.mode === "fit" ? ui.previewFit : null;
      if (pf) {
        var pff = fitFill(pf);
        top = pff.top; base = pff.base;
      } else if (p) {
        for (var i = p.s; i <= p.e; i++) {
          top.push({ x: t.t[i], y: t.y[i] });
          base.push({ x: t.t[i], y: interp(t.t[i], t.t[p.s], t.t[p.e], p.base_start, p.base_end) });
        }
        ln = [t.t[p.s], p.base_start, t.t[p.e], p.base_end];
      } else if (st.mode !== "fit" && !pe && (!st.touched || st.mode !== "integrate") && !t.deleted && t.peak && t.peak.start != null) {
        /* the stored peak: the one a delete removes; a fitted one is its reported component */
        var fl = t.fit && t.fit.components && t.fit.span ? fitFill(t.fit) : peakFill(t.t, t.y, t.peak);
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
      var dropEdge = working && edgesSet() ? dropSideOf() : null;
      if (dropEdge) {
        /* the shared edge as a full-height vertical line, held as "drop" */
        var dropAt = dropEdge === "start" ? ln[0] : ln[2];
        marks.dropShared = { type: "line", xMin: dropAt, xMax: dropAt, borderColor: colour, borderWidth: 2 };
      }
      ui.dropAt = dropEdge ? (dropEdge === "start" ? ln[0] : ln[2]) : null;
      if (working) {
        (t.candidates || []).forEach(function (c, k) {
          var on = st.kind === "apex" && st.apex === c.apex;
          marks["cand" + k] = { type: "point", xValue: c.apex, yValue: c.y, radius: on ? 6 : 5,
                                backgroundColor: "transparent", borderColor: token(on ? "--s-warning" : "--s-info"),
                                borderWidth: 2, click: function () { if (!ui.justDragged) { choose(c); } } };
        });
      }
      if (st.mode === "fit") { fitMarks(marks, t); }
      if (rtOn()) {
        var rv = rtShown();
        marks.expected = { type: "line", xMin: rv, xMax: rv, borderWidth: 2, borderDash: [6, 4],
                           borderColor: token(ui.rtDrag != null ? "--s-warning" : "--s-info"),
                           label: { display: true, content: rtLabel(rv), position: "start",
                                    backgroundColor: token("--s-info-lt"), color: token("--s-info-text") } };
      }
      ui.chart.options.plugins.annotation.annotations = marks;
      ui.chart.update("none");
    }

    /* the fit being drawn: its edges, each apex clicked (the one reported here thick), and where the
       peak reported in every injection is, the click nearest the expected time */
    function fitMarks(marks, t) {
      var ap = fitApexSorted(st.apexes), here = fitPick(st, a, t), all = fitAllPick(st, a, t);
      ["start", "end"].forEach(function (e) {
        if (typeof st[e] === "number") {
          marks["fit_" + e] = { type: "line", xMin: st[e], xMax: st[e], borderColor: token("--s-warning"), borderWidth: 2 };
        }
      });
      ap.forEach(function (v, k) {
        marks["fit_apex" + k] = { type: "line", xMin: v, xMax: v, borderColor: token(k === here ? "--s-primary-dk" : "--s-info"),
                                  borderWidth: k === here ? 3 : 1, borderDash: [5, 3],
                                  label: { display: true, content: "Peak " + (k + 1) + (k === here ? ", reported here" : "") +
                                           (k === all ? ", reported in all" : ""), position: "start",
                                           backgroundColor: token("--s-info-lt"), color: token("--s-info-text") } };
      });
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
      /* what a press at q takes: a handle (within 9 px of its point), then whichever of the drop
         line and an edge (within 9 px of its time, at any height) and the expected-time line (5 px)
         is nearest, a tie going to the drop line, then an edge, then the line; then the baseline
         (6 px), the axis, or nothing */
      function target(q) {
        var ar = ui.chart.chartArea;
        if (q.py > ar.bottom && q.px >= ar.left && q.px <= ar.right) { return "axis"; }
        var ln = ui.line, working = !!ln && editable && st.mode === "integrate";
        var xs = ui.chart.scales.x, ys = ui.chart.scales.y, inY = q.py >= ar.top && q.py <= ar.bottom;
        if (working && inY) {
          var circle = null, cd = GRAB_PX;
          ["start", "end"].forEach(function (h, k) {
            var d = Math.sqrt(Math.pow(q.px - xs.getPixelForValue(ln[2 * k]), 2) + Math.pow(q.py - ys.getPixelForValue(ln[2 * k + 1]), 2));
            if (d <= cd) { circle = h; cd = d; }
          });
          if (circle) { return circle; }
        }
        var offers = [];
        function offer(kind, d, limit) { offers.push({ kind: kind, d: d, limit: limit }); }
        if (working && inY) {
          if (ui.dropAt != null) { offer("drop", Math.abs(q.px - xs.getPixelForValue(ui.dropAt)), GRAB_PX); }
          var edge = edgeAt(q.px, xs.getPixelForValue(ln[0]), xs.getPixelForValue(ln[2]));
          if (edge) { offer(edge, Math.abs(q.px - xs.getPixelForValue(edge === "start" ? ln[0] : ln[2])), GRAB_PX); }
        }
        if (rtOn() && !ui.rtBusy && inY) { offer("rt", Math.abs(q.px - xs.getPixelForValue(rtShown())), 5); }
        var best = nearestPress(offers);
        if (best) { return best; }
        if (!working) { return null; }
        var x = timeAt(q.px);
        if (x > ln[0] && x < ln[2] && Math.abs(q.py - ys.getPixelForValue(interp(x, ln[0], ln[2], ln[1], ln[3]))) <= 6) {
          return "line";
        }
        return null;
      }
      function ends() {
        held = null;
        try { canvas.releasePointerCapture(ui.pointerId); } catch (err) { /* released already */ }
      }
      canvas.onpointerdown = function (e) {
        if (e.button !== 0 || !ui.chart) { return; }
        var q = pos(e);
        held = target(q);
        if (!held) {
          if (!inArea(q)) { return; }
          held = "zoom";                /* an empty area: a box to zoom into, or a click */
          press = q; moved = false;
          from = { x: timeAt(q.px), y: countAt(q.py) };
          ui.pointerId = e.pointerId;
          canvas.setPointerCapture(e.pointerId);
          e.preventDefault();
          return;
        }
        press = q;
        moved = false;
        from = held === "axis" ? { view: [ui.chart.scales.x.min, ui.chart.scales.x.max] }
                               : { start: st.start, end: st.end, x: timeAt(q.px) };
        if (held === "start" || held === "end") { ui.handle = held; }
        ui.pointerId = e.pointerId;
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
          wrap.classList.toggle("is-line", over === "line" || over === "axis" || over === "rt" || over === "drop");
          return;
        }
        var far = Math.max(Math.abs(q.px - press.px), Math.abs(q.py - press.py));
        if (held === "zoom") {
          if (pressKind(null, far) !== "zoom") {      /* back within 4 px of the press: a click again */
            if (moved) {
              moved = false;
              delete ui.chart.options.plugins.annotation.annotations.region;
              ui.chart.update("none");
            }
            return;
          }
          var marks = ui.chart.options.plugins.annotation.annotations;
          marks.region = { type: "box", xMin: from.x, xMax: timeAt(q.px), yMin: from.y, yMax: countAt(q.py),
                           borderColor: token("--s-info"), borderWidth: 1, borderDash: [4, 3],
                           backgroundColor: "transparent" };
          moved = true;
          ui.chart.update("none");
          return;
        }
        /* a handle or the drop line stays put for a few pixels, so a click does not move it */
        if ((held === "start" || held === "end" || held === "drop") && !moved && far < CLICK_PX) { return; }
        moved = true;
        if (held === "axis") {
          var w = from.view[1] - from.view[0], ar = ui.chart.chartArea;
          zoomTo(panView(from.view, -(q.px - press.px) / (ar.right - ar.left) * w, limits()), null, true);
          return;
        }
        if (held === "rt") {            /* the expected time, on a sample every trace holds */
          var to = rtDragTime(traces[0].t, timeAt(q.px), rtSpan(traces));
          if (to != null && to !== ui.rtDrag) { ui.rtDrag = to; paint(lastRes); }
          return;
        }
        var p = { x: timeAt(q.px), shift: e.shiftKey };
        if (held === "start" || held === "end") {
          /* the level is the pointer's count, unless the pointer is on the signal at that sample */
          var sv = signalAt(handleState(held, from), p.x);
          p.y = countAt(q.py);
          p.snapped = sv != null && onSignal(q.py, ui.chart.scales.y.getPixelForValue(sv));
        }
        var d = handleDrag(handleState(held, from), p);
        if (d.start !== st.start || d.end !== st.end || d.levels[0] !== (st.handles || ui.drawn || [])[0] ||
            d.levels[1] !== (st.handles || ui.drawn || [])[1] || d.manual[0] !== st.manual[0] || d.manual[1] !== st.manual[1]) {
          takeDrag(d, true);
        }
      };
      canvas.onpointerup = canvas.onpointercancel = canvas.onlostpointercapture = function (e) {
        if (!held) { return; }
        if (held === "zoom") {
          ends();
          delete ui.chart.options.plugins.annotation.annotations.region;
          var q = pos(e), box = moved && e.type === "pointerup" ? regionView(from.x, from.y, timeAt(q.px), countAt(q.py), leastSpan(), Math.abs(q.py - press.py)) : null;
          if (box) { zoomTo(box.x, box.y); } else { ui.chart.update("none"); }
          if (moved) {                 /* the click that ends the box is not a candidate's or an apex */
            ui.justDragged = true;
            window.setTimeout(function () { ui.justDragged = false; }, 0);
          }
          return;
        }
        if (held === "rt") {
          held = null;
          wrap.classList.remove("is-dragging");
          try { canvas.releasePointerCapture(e.pointerId); } catch (err) { /* released already */ }
          ui.justDragged = true;
          window.setTimeout(function () { ui.justDragged = false; }, 0);
          /* released where it was dragged to: the method takes the time;
             a cancelled drag puts the line back */
          if (e.type === "pointerup" && moved && ui.rtDrag != null && ui.rtDrag !== ui.rt) {
            setExpected(ui.rtDrag);
          } else {
            ui.rtDrag = null;
            paint(lastRes);
          }
          return;
        }
        held = null;
        ui.dragOpen = false;
        wrap.classList.remove("is-dragging");
        try { canvas.releasePointerCapture(e.pointerId); } catch (err) { /* released already */ }
        flushDrag();
        if (moved) {                 /* the click that ends a drag is not a candidate's */
          ui.justDragged = true;
          window.setTimeout(function () { ui.justDragged = false; }, 0);
        }
      };
      /* a handle double-clicked: its level back on the signal */
      canvas.ondblclick = function (e) {
        if (!ui.chart) { return; }
        var q = pos(e), h = target(q);
        if (!h && inArea(q)) { e.preventDefault(); zoomTo(null); return; }   /* an empty area: the whole window */
        if (h !== "start" && h !== "end" && h !== "drop") { return; }
        e.preventDefault();
        takeDrag(handleDrag(handleState(h), { reset: true }));
      };
      /* in the fit tool a click sets an apex, or takes the one beside it away */
      canvas.onclick = function (e) {
        if (!ui.chart || !st || st.mode !== "fit" || ui.justDragged) { return; }
        var q = pos(e);
        if (!inArea(q)) { return; }
        var xs = ui.chart.scales.x, tol = 10 * (xs.max - xs.min) / (ui.chart.chartArea.right - ui.chart.chartArea.left);
        if (xs.min == null) { return; }
        var tt = tr(), at = timeAt(q.px), i = snapIndex(tt.t, at, null);
        clickApex(i >= 0 ? tt.t[i] : at, tol);
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
        if (submit && !submit.disabled) { applyOne(); return true; }
        return false;
      }
      if (k.act === "apply-one") {
        /* the Apply button's own path: a change opens the comment box, an armed undo posts at
           once; nothing posts with Apply disabled, and the key is the card's even then, so the
           browser does not save the page */
        if (editable && submit && !submit.disabled) { applyOne(); }
        return true;
      }
      if (k.act === "step-back" || k.act === "step-forward") {
        if (!editable || !st) { return false; }
        if (ui.busy[ui.index]) { return true; }       /* posted, or waiting for the run: the drawing stands */
        var snap = k.act === "step-back" ? ui.stack.back(snapshot()) : ui.stack.forward(snapshot());
        if (!snap) { return false; }
        restoreDrawing(snap);
        return true;
      }
      if (k.act === "zoom-in" || k.act === "zoom-out") {
        if (!ui.chart) { return false; }
        var xs0 = ui.chart.scales.x, vw = [xs0.min, xs0.max];
        zoomTo(zoomView(vw, (vw[0] + vw[1]) / 2, k.act === "zoom-in" ? 0.8 : 1.25, limits(), leastSpan()));
        return true;
      }
      if (k.act === "injection" || k.act === "compound") {
        walk(k.act, k.by);
        return true;
      }
      if (k.act === "keys") { toggleKeys(); return true; }
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
        takeDrag(handleDrag(handleState(ui.handle), { x: t.t[i] }));
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
      var was = snapshot();
      st.mode = "integrate";
      st.kind = "apex";
      st.note = "";
      st.apex = c.apex;
      st.start = c.start;
      st.end = c.end;
      seedLevels(null);
      st.touched = true;
      recorded(was);
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
    /* the fits stepper and the score badge, on the quantifier. A step previews that candidate through
       the edit's own drawing (its edges and line, or a fit of its shape on one apex); nothing is
       applied until Apply. The score shows only while the drawing is still the candidate's. */
    var fitList = fitSteps(a), fitAt = fitStart(a, fitList), fitStartAt = fitAt, scoreOpen = false;
    /* the smoothing stepper: a step only previews (the dashed line, no score); it is applied by "Apply to this
       injection" (asked first) or "Apply to all", and is the compound's, never one injection's */
    var smoothList = smoothingList(a), smoothStart = smoothingStart(a, smoothList), smoothAt = smoothStart;
    var SMOOTH_PAIRED = "Smoothing cannot be changed for a paired or summed peak";
    ui.smoothPreview = false;
    ui.smoothM = null;
    ui.smoothAllPrev = null;
    ui.asideNote = false;
    function smoothBlocked() { return !!a.peak_mode && a.peak_mode !== "single"; }
    function smoothChanged() { return smoothAt !== smoothStart && smoothList[smoothAt].m != null; }
    function smoothReset() {
      var was = smoothChanged();
      smoothAt = smoothStart;
      ui.smoothPreview = false;
      ui.smoothM = null;
      ui.smoothAllPrev = null;
      return was;
    }
    /* a step drops an edge or fit edit drawn (Ctrl+Z brings it back): the smoothing is the compound's, the
       edit this injection's. A drag or a fits step afterwards keeps the smoothing chosen. */
    function smoothTo(i) {
      if (smoothBlocked() || i < 0 || i >= smoothList.length || i === smoothAt || smoothList[i].m == null) { return; }
      if (editDrawn()) {
        var was = snapshot();
        startState();
        recorded(was);
        ui.asideNote = true;          /* said under the stepper: the edit is not lost, Ctrl+Z brings it back */
        if (editable) { boxes(); }
      }
      smoothAt = i;
      ui.smoothPreview = smoothChanged();
      ui.smoothM = ui.smoothPreview ? smoothList[i].m : null;
      ui.smoothAllPrev = null;
      draw();
      update();
    }
    function smoothingStepper() {
      var bar = body.querySelector('[data-role="smoothing"]'), note = body.querySelector('[data-role="smooth-note"]');
      var blocked = smoothBlocked();
      if (note) {
        var words = smoothNote({ blocked: blocked ? SMOOTH_PAIRED + "." : "", preview: ui.smoothPreview, name: smoothList[smoothAt].name,
                                 stored: smoothList[smoothStart].name,
                                 drawn: editDrawn() ? smoothingDropsEdges(a.label || a.analyte) : "", aside: !!ui.asideNote });
        if (note.textContent !== words) { note.textContent = words; }
        note.hidden = !words;
      }
      if (!bar) { return; }
      var lo = blocked ? -1 : smoothingNext(smoothList, smoothAt, -1), hi = blocked ? -1 : smoothingNext(smoothList, smoothAt, 1);
      paintStepper(bar, { attr: "smooth", labels: ["Less smoothing", "More smoothing"], off: [lo < 0, hi < 0],
                          text: smoothList[smoothAt].m == null ? "\u2014" : smoothList[smoothAt].name, title: blocked ? SMOOTH_PAIRED : "" });
    }
    function stepTo(i) {
      if (i < 0 || i >= fitList.length || i === fitAt) { return; }
      var step = fitList[i], c = step.cand, p = tr().peak || {};
      var from = edgesSet() ? [st.start, st.end] : [p.start, p.end];
      var lo = c && c.start != null ? c.start : from[0], hi = c && c.end != null ? c.end : from[1];
      fitAt = i;
      if (step.method === "gaussian" || step.method === "emg") {
        var was = snapshot();
        st.mode = "fit";
        st.kind = "fit";
        st.shape = step.method;
        st.alone = true;
        st.apexes = [p.apex != null ? p.apex : (lo + hi) / 2];
        st.pick = null;
        seedLevels(null);
        st.start = lo;
        st.end = hi;
        st.note = "";
        recorded(was);
        boxes();
        update();
      } else if (i === fitStartAt && (!c || c.start == null || edgesAre(c, p))) {
        run({ id: "restore", discard: true });
      } else if (c && c.start != null && c.end != null) {
        st.alone = false;
        setEdges(lo, hi, step.method);
      } else {
        st.alone = false;
        setLine(step.method);
      }
    }
    /* the method the drawing is: the fit's shape, else the line it is measured on; an untouched drawing
       is the stored peak's own method; a deletion or an undo is none */
    function drawnMethod() {
      if (st.mode === "fit") { return st.shape || "gaussian"; }
      if (st.mode !== "integrate") { return null; }
      if (!st.touched && !ui.pending) { return fitMethodOf(tr()); }
      return line();
    }
    function syncStep() {
      var m = drawnMethod(), at = -1;
      for (var k = 0; k < fitList.length; k++) { if (fitList[k].method === m) { at = k; } }
      fitAt = at;
    }
    function edgesAre(c, p) { return Math.abs(c.start - p.start) < 5e-4 && Math.abs(c.end - p.end) < 5e-4; }
    /* the candidate the drawing still is, or null: a drag or a typed edge makes it nobody's */
    function shownStep() {
      var step = fitList[fitAt];
      if (!step || !step.cand || step.cand.start == null || tr().edit !== "auto" || !edgesSet()) { return null; }
      /* levels set by hand, or a fit of two or three apexes, are nobody's candidate */
      if (st.levels || (st.manual && (st.manual[0] || st.manual[1]))) { return null; }
      if (st.mode === "fit" && fitApexSorted(st.apexes).length !== 1) { return null; }
      return Math.abs(st.start - step.cand.start) < 5e-4 && Math.abs(st.end - step.cand.end) < 5e-4 ? step : null;
    }
    function stepper() {
      smoothingStepper();
      var on = ui.index === 0, bar = body.querySelector('[data-role="fits"]'), score = body.querySelector('[data-role="score"]');
      var note = body.querySelector('[data-role="fit-note"]');
      if (on) { syncStep(); }
      var name = fitAt >= 0 ? fitList[fitAt].name : fitMethodName(drawnMethod());
      if (bar) {
        paintStepper(bar, { attr: "fit", labels: ["Previous fit", "Next fit"], off: [fitAt <= 0, fitAt >= fitList.length - 1], text: name, hidden: !on });
      }
      var shown = on ? shownStep() : null;
      if (note) {
        var why = on && fitAt >= 0 && fitList[fitAt].cand ? fitList[fitAt].cand.note || "" : "";
        note.textContent = why;
        note.hidden = !why;
      }
      if (score) {
        var skey = JSON.stringify([shown ? shown.method : null, on, !!ui.smoothPreview]);
        if (score.getAttribute("data-key") !== skey) {
          score.setAttribute("data-key", skey);
          /* a smoothing previewed has no score until it is applied and the run processed again */
          score.innerHTML = on ? scoreBadge(ui.smoothPreview ? null : shown, a.fit_accept_score, a.check_labels, scoreOpen) : "";
        }
        /* the breakdown opens and shuts in place: the arrow pressed keeps the focus */
        var more = score.querySelector(".raw-score-more"), list = score.querySelector(".raw-score-checks");
        if (more && more.getAttribute("aria-expanded") !== (scoreOpen ? "true" : "false")) { more.setAttribute("aria-expanded", scoreOpen ? "true" : "false"); }
        if (list && list.hidden === scoreOpen) { list.hidden = !scoreOpen; }
      }
    }
    var stepBar = body.querySelector('[data-role="fits"]');
    if (stepBar) {
      stepBar.addEventListener("click", function (e) {
        var b = e.target && e.target.closest ? e.target.closest("[data-fit]") : null;
        if (b && !b.disabled) { stepTo(fitAt + parseInt(b.getAttribute("data-fit"), 10)); }       /* from no step, Next is the first */
      });
    }
    var smoothBar = body.querySelector('[data-role="smoothing"]');
    if (smoothBar) {
      smoothBar.addEventListener("click", function (e) {
        var b = e.target && e.target.closest ? e.target.closest("[data-smooth]") : null;
        if (b && !b.disabled) { smoothTo(smoothingNext(smoothList, smoothAt, parseInt(b.getAttribute("data-smooth"), 10))); }
      });
    }
    var scoreBox = body.querySelector('[data-role="score"]');
    if (scoreBox) {
      scoreBox.addEventListener("click", function (e) {
        var b = e.target && e.target.closest ? e.target.closest(".raw-score-more") : null;
        if (!b) { return; }
        scoreOpen = !scoreOpen;
        stepper();
      });
    }
    function update() {
      var t = tr();
      if (ui.asideNote && editDrawn()) { ui.asideNote = false; }       /* a new edit is drawn: the set-aside edit is let go */
      /* a smoothing is previewed on the integration drawing only: a delete or an undo leaves it */
      if (smoothChanged() && (st.mode === "delete" || st.mode === "revert")) { smoothReset(); draw(); }
      schedulePreview();
      stepper();
      var panes = body.querySelectorAll(".raw-pane");
      for (var i = 0; i < panes.length; i++) { panes[i].hidden = panes[i].getAttribute("data-pane") !== st.mode; }
      var res = null, problem = null;
      if (st.mode === "integrate" && st.touched) {
        res = judge(a, t, editOf());
        problem = res.problem;
      }
      if (st.touched) { ui.serverNotes = []; }
      var shownNotes = res ? res.notes : (t.transition === ui.notesOn ? ui.serverNotes : []);
      lastRes = res;
      var prev = body.querySelector('[data-role="preview"]');
      if (prev) {
        var p = res && res.preview;
        var ionText = p ? ionPreviewText(a, ui.index, p.area) : "";
        prev.textContent = p ? "Area " + num(p.area, 0) + " · S/N " + (p.sn == null ? "—" : num(p.sn, 1)) +
                               (res.change == null ? "" : " · change " + pyFixed(res.change, 1) + " %") +
                               (ionText ? " · " + ionText : "") : "";
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
          submit.textContent = "Apply to this injection";
          submit.disabled = !st.touched || !!problem;
        } else if (st.mode === "fit") {
          submit.textContent = "Apply to this injection";
          submit.disabled = !!fitProblem(st) || !previewOk();     /* no fit limit: no preview is made, so it is never applied */
        } else if (st.mode === "delete") {
          submit.textContent = ui.armed && needsConfirm() ? "Confirm delete" : "Apply to this injection";
          submit.disabled = !!t.deleted && t.edit !== "pending";
        } else {
          submit.textContent = "Undo edit";
          submit.disabled = false;
        }
        if (smoothChanged()) { submit.disabled = false; }
        if (ui.busy[ui.index]) { submit.disabled = true; }       /* posted, or waiting for the run */
        /* the comment box stays only for a change that can be applied, never for an undo */
        if (submit.disabled || st.mode === "revert") { ui.commentOpen = false; }
        commentBox.hidden = !ui.commentOpen;
        var cp = commentProblem(reasonSel.value, detailBox.value);
        commentHint.textContent = cp;
        ionWarn.textContent = calibratorWarning(a);
        ionWarn.hidden = !ionWarn.textContent;
        commentGo.disabled = !!cp || !!ui.busy[ui.index];
      }
      if (st.mode === "fit") { fitPane(); }
      var stored = body.querySelector('[data-role="fit-readout"]');
      if (stored) { stored.textContent = t.fit && !t.deleted ? fitReadout(t.fit) : ""; }
      if (allBtn) { updateAll(); }
      if (backBtn) { updateBack(); }
      var trace = body.querySelector('[data-role="trace-line"]');
      /* an edit the run could not apply says why; one waiting for the run says what it is */
      trace.textContent = t.transition + " · " + (EDIT_TEXT[t.edit] || EDIT_TEXT.auto) +
                          (t.edit === "no_effect" && t.no_effect ? ": " + t.no_effect : "") +
                          (t.edit === "pending" && t.pending_text ? ": " + t.pending_text : "");
      paint(res);
      levelBoxes();
    }

    /* "Back to automatic": offered where there is a saved edit, a drawn change or a smoothing preview to give up;
       where a calibrator warning applies the first click shows it and the second posts */
    function updateBack() {
      var t = tr();
      if (st.mode !== "revert") { ui.backArmed = false; }
      backBtn.disabled = !(t.edit && t.edit !== "auto") && !st.touched && st.mode === "integrate" && !smoothChanged() || !!ui.busy[ui.index];
      var words = ui.backArmed ? "Confirm back to automatic" : "Back to automatic";
      backBtn.querySelector('[data-role="revert-words"]').textContent = words;
    }
    function backToAutomatic() {
      var t = tr();
      if (ui.busy[ui.index] || backBtn.disabled) { return; }
      /* a smoothing preview is the compound's, not this peak's: it goes with the return to automatic */
      if (smoothChanged()) { smoothReset(); draw(); }
      if (!t.edit || t.edit === "auto") {
        var was = snapshot();
        startState();                 /* only a drawn change: it is let go */
        recorded(was);
        boxes();
        update();
        return;
      }
      if (st.mode !== "revert") { var wasRev = snapshot(); st.mode = "revert"; recorded(wasRev); }
      if (calibratorWarning(a) && !ui.backArmed) { ui.backArmed = true; update(); return; }
      ui.backArmed = false;
      post();
    }

    /* "Apply to all N injections": offered for a change drawn on a single peak; its preview
       holds only while the drawing is the one previewed */
    /* the injections holding the trace shown: what the preview counts */
    function countOf(t) { return t.injection_count != null ? t.injection_count : a.injection_count; }
    function updateAll() {
      var t = tr(), fitting = st.mode === "fit";
      if (smoothChanged()) {
        /* an isotope standard asks to confirm, as an edit of it applied to all does */
        allBtn.hidden = false;
        allBtn.textContent = ui.smoothAllPrev ? "Confirm" : "Apply to all " + a.injection_count + " injections";
        allBtn.disabled = !!ui.busy[ui.index];
        allLine.textContent = ui.smoothAllPrev ? ui.smoothAllPrev.text : "";
        allLine.hidden = !allLine.textContent;
        return;
      }
      var reason = st.mode === "delete" ? ALL_ONE : st.mode === "integrate" || fitting ? allOffered(st, a) : "";
      var touched = st.mode === "integrate" && st.touched, apex = (t.auto || t.peak || {}).apex;
      /* judged without the manual-change limits; the hard ones still refuse */
      var hard = touched ? judge(a, t, editOf(), true).problem : null;
      if (!reason && touched && apex == null) { reason = ALL_NO_PEAK; }
      /* a fit is drawn when it is whole; it is applied once its preview has passed */
      var whole = fitting && !fitProblem(st), drawn = fitting ? whole && previewOk() : touched && !hard;
      if (ui.allPrev && (ui.allPrev.snap !== snap() || !drawn || reason)) { ui.allPrev = null; }
      allBtn.hidden = st.mode === "revert";
      allBtn.textContent = ui.allPrev ? "Confirm" : "Apply to all " + countOf(t) + " injections";
      allBtn.disabled = !drawn || !!reason || !!ui.busy[ui.index] || (fitting && fitAllPick(st, a, t) < 0);
      var line = ui.allPrev ? ui.allPrev.text + (ui.allPrev.major ? " " + FIT_MAJOR : "") +
                              (calibratorWarning(a, true) ? " " + calibratorWarning(a, true) : "")
                            : whole && !reason ? fitAllWords(st.apexes, expectedOf(a, t), [st.start, st.end])
                            : (st.mode !== "revert" && (touched || st.mode === "delete" || fitting) ? reason || hard || "" : "");
      allLine.textContent = line;
      allLine.hidden = !line;
    }
    /* the fit tool's pane: the shape, which peak is reported here, what is still lacking */
    function fitPane() {
      var ap = fitApexSorted(st.apexes), here = fitPick(st, a, tr());
      var shape = body.querySelector('.pfas-seg[aria-label="Shape"]');
      if (shape) { pressSeg(shape, st.shape || "gaussian"); }
      var rep = body.querySelector('[data-role="fit-report"]');
      if (rep) {
        var key = ap.length + ":" + here;
        if (rep.getAttribute("data-key") !== key) {
          rep.setAttribute("data-key", key);
          rep.innerHTML = ap.length < 2 ? "" : seg("Report", ap.map(function (v, k) { return [String(k), "Peak " + (k + 1)]; }), String(here));
          var rs = rep.querySelector(".pfas-seg");
          if (rs) {
            if (C.placePill) { C.placePill(rs); }
            onSeg(rs, function (v) { var was = snapshot(); st.pick = parseInt(v, 10); recorded(was); update(); });
          }
        }
      }
      var prob = body.querySelector('[data-role="fit-problem"]'), picked = body.querySelector('[data-role="fit-picked"]');
      var why = fitProblem(st) || (a.fit_limit == null ? FIT_UNSET : ""), pv = !why && ui.preview && ui.previewKey === previewKey() ? ui.preview : null;
      if (prob) { prob.textContent = why || (pv && pv.problem ? (pv.own ? pv.problem : "Fit refused: " + pv.problem + ".") : ""); }
      var readout = body.querySelector('[data-role="fit-preview"]'), fin = body.querySelector('[data-role="fit-final"]');
      if (readout) { readout.textContent = why ? "" : pv ? (pv.fit ? fitReadout(pv.fit) + fitIonText(pv.fit) : "") : FIT_FITTING; }
      if (fin) { fin.hidden = !(pv && pv.fit); }
      var floor = body.querySelector('[data-role="fit-floor"]');
      if (floor) { floor.hidden = !(pv && pv.fit && tr().min_sn == null); }
      if (picked) { picked.textContent = why ? "" : "This injection reports peak " + (here + 1) + ", at " + pyFixed(ap[here], 3) + " min."; }
    }
    /* the ratio on the fitted area of the peak reported, against the other trace's stored area */
    function fitIonText(fit) {
      var c = (fit.components || [])[fit.pick || 0] || {};
      var text = c.area == null ? "" : ionPreviewText(a, ui.index, c.area), mixed = fitMixed(a, ui.index);
      return (text ? " · " + text : "") + (text && mixed ? " · " + mixed : "");
    }
    function sendAll(extra) {
      var fd = new FormData(), p = allPayload(st, tr(), a), k;
      if (!ui.index) { p.transition = ""; }          /* the quantifier is named by none */
      if (f.elements._authenticator) { fd.append("_authenticator", f.elements._authenticator.value); }
      fd.append("action", "raw_apply_all");
      for (k in p) { if (p.hasOwnProperty(k)) { fd.append(k, p[k]); } }
      for (k in extra) { if (extra.hasOwnProperty(k)) { fd.append(k, extra[k]); } }
      return fetch(f.getAttribute("action"), { method: "POST", body: fd, credentials: "same-origin", headers: { "Accept": "application/json" } })
        .then(function (r) { return r.text().then(function (text) { return replyFrom(r, text); }); });
    }
    function applyAll() {
      var t = tr(), idx = ui.index, mine = ui;
      if (ui.busy[idx] || allBtn.disabled) { return; }
      if (smoothChanged()) {
        if (!a.standard_all_text) { sendSmoothing(false); return; }
        if (ui.smoothAllPrev) { sendSmoothing(true); return; }
        previewSmoothing();
        return;
      }
      var was = snap(), since = (data.failure && data.failure.at) || "", previewed = ui.allPrev;
      if (previewed && previewed.snap !== was) { previewed = ui.allPrev = null; }    /* a new drawing is previewed again */
      function failed(text) {
        delete mine.busy[idx];
        if (current === mine && drawerOpen()) { mine.say(idx, text, true); update(); } else { pageNote(text, true); }
      }
      ui.busy[idx] = true;
      if (!previewed) {
        update();
        sendAll({ preview: "1" }).then(function (reply) {
          delete mine.busy[idx];
          if (reply.ok && current === mine && drawerOpen()) {
            mine.allPrev = { text: reply.text, needs_confirm: !!reply.needs_confirm, major: !!reply.major, snap: was };
            update();
          } else if (!reply.ok) { failed(reply.error || "The change could not be previewed."); }
        }).catch(function () { failed("The change could not be sent."); });
        return;
      }
      ui.allPrev = null;
      ui.stack.clear();
      update();
      ui.say(idx, "Saving the change.", false);
      sendAll(previewed.needs_confirm ? { confirm: "1" } : {}).then(function (reply) {
        if (reply.ok) {
          waitForRun({ data: data, ui: mine, idx: idx, last: { transition: t.transition, notes: [] },
                       waiting: reply.waiting, since: since, was: was });
          return;
        }
        failed(reply.error || "The change was not applied.");
      }).catch(function () { failed("The change could not be sent."); });
    }

    function say(text, isError) {
      var box = body.querySelector('[data-role="said"]');
      if (box) { box.className = isError ? "raw-refusal" : "raw-note"; box.textContent = text; }
    }

    /* what the post and the run's answer say, kept with the trace they are about */
    function paintSaid() {
      var box = body.querySelector('[data-role="said"]'), sy = ui.saying;
      if (!box || !sy) { return; }
      if (sy.index === ui.index) {
        box.className = sy.error ? "raw-refusal" : "raw-note";
        box.textContent = sy.text;
        ui.saidShown = true;
      } else if (ui.saidShown) {
        box.className = "raw-note";
        box.textContent = "";
        ui.saidShown = false;
      }
    }
    ui.say = function (index, text, error) { ui.saying = { index: index, text: text, error: !!error }; paintSaid(); };
    ui.unsay = function () {
      ui.saying = null;
      var box = body.querySelector('[data-role="said"]');
      if (box && ui.saidShown) { box.className = "raw-note"; box.textContent = ""; }
      ui.saidShown = false;
    };
    ui.release = function (index) { delete ui.busy[index]; if (current === ui) { update(); } };
    /* a change drawn since the post, on any trace */
    function snap() { return JSON.stringify([ui.index, st.mode, st.kind, st.start, st.end, st.apex, st.baseline, st.levels, st.shape, st.apexes, st.pick]); }
    ui.drawnSince = function (was) { return !!(ui.dirty && ui.dirty() && snap() !== was); };
    /* the view on screen, Whole window (a null view) included */
    ui.zoomed = function () { var v = ui.view; return { view: v ? v.slice() : null, yview: ui.yview ? ui.yview.slice() : null }; };
    /* the refusal in the card, over the edit as posted */
    function refused(index, error, posted) {
      ui.say(index, error, true);
      if (index !== ui.index) { return; }
      var box = body.querySelector("p.raw-refusal.is-flash");
      if (!box) {
        box = el("p", "raw-refusal is-flash");
        box.setAttribute("role", "alert");
        body.insertBefore(box, body.firstChild);
      }
      box.textContent = error;
      var back = refusedEdit(posted, error, tr().transition);
      if (back && back.mode === "delete") {
        st.mode = "delete";
        ui.armed = true;
      } else if (back) {
        for (var k in back) { if (back.hasOwnProperty(k)) { st[k] = back[k]; } }
        seedLevels(back.levels);
      }
    }

    /* "Apply to this injection": an undo posts at once, a delete asks its confirm first, any
       other change opens the comment box, whose Apply posts */
    /* a smoothing change goes to the compound's peaks in the run, whichever button asked. It does not reuse
       sendAll: that sends the drawn edit's edges, offsets and kind, which a smoothing change refuses. */
    function smoothingPost(extra) {
      var fd = new FormData();
      if (f.elements._authenticator) { fd.append("_authenticator", f.elements._authenticator.value); }
      fd.append("action", "raw_apply_all");
      fd.append("analyte", a.analyte);
      fd.append("smoothing", String(2 * smoothList[smoothAt].m + 1));
      for (var k in extra) { if (extra.hasOwnProperty(k)) { fd.append(k, extra[k]); } }
      return fetch(f.getAttribute("action"), { method: "POST", body: fd, credentials: "same-origin", headers: { "Accept": "application/json" } })
        .then(function (r) { return r.text().then(function (text) { return replyFrom(r, text); }); });
    }
    /* an isotope standard's smoothing for all, previewed: the words the server confirms it with, then Confirm */
    function previewSmoothing() {
      var idx = ui.index, mine = ui;
      if (ui.busy[idx]) { return; }
      ui.busy[idx] = true;
      update();
      smoothingPost({ preview: "1" }).then(function (reply) {
        delete mine.busy[idx];
        if (reply.ok && current === mine && drawerOpen()) {
          mine.smoothAllPrev = { text: reply.text || "" };
          update();
        } else if (!reply.ok) {
          if (current === mine && drawerOpen()) { mine.say(idx, reply.error || "The change could not be previewed.", true); update(); }
          else { pageNote(reply.error || "The change could not be previewed.", true); }
        }
      }).catch(function () {
        delete mine.busy[idx];
        pageNote("The change could not be sent.", true);
        if (current === mine && drawerOpen()) { update(); }
      });
    }
    function sendSmoothing(confirm) {
      var t = tr(), idx = ui.index, mine = ui, was = snap(), since = (data.failure && data.failure.at) || "", sent = smoothAt;
      function failed(text) {
        delete mine.busy[idx];
        if (current === mine && drawerOpen()) { mine.say(idx, text, true); update(); } else { pageNote(text, true); }
      }
      ui.busy[idx] = true;
      ui.stack.clear();
      update();
      ui.say(idx, "Saving the change.", false);
      smoothingPost(confirm ? { confirm: "1" } : {})
        .then(function (reply) {
          if (reply.ok) {
            /* applied: the chosen step is now the stored one, nothing is previewed or left to leave */
            if (current === mine) {
              /* the step that was posted is the stored one; a step pressed while saving is a new preview */
              smoothStart = sent;
              a.smoothing_in_force_points = 2 * smoothList[sent].m + 1;
              ui.smoothPreview = smoothChanged();
              ui.smoothM = ui.smoothPreview ? smoothList[smoothAt].m : null;
              ui.smoothAllPrev = null;
              draw();
              update();
            }
            waitForRun({ data: data, ui: mine, idx: idx, last: { transition: t.transition, notes: [] },
                         waiting: reply.waiting, since: since, was: was });
            return;
          }
          failed(reply.error || "The change was not applied.");
        }).catch(function () { failed("The change could not be sent."); });
    }
    /* the question before one injection's button changes a whole compound: Cancel keeps the stored step.
       An isotope standard's modal carries the words its change for all is confirmed with, and its Apply confirms. */
    function askSmoothing() {
      if (ui.smoothClose) { ui.smoothClose(); }          /* a question still open goes, with its key listener */
      var m = el("div", "pfas-modal is-top open"), back = doc.activeElement, label = a.label || a.analyte;
      m.id = "raw-smoothing";
      m.innerHTML = '<div class="pfas-modal-box" role="dialog" aria-modal="true" aria-labelledby="raw-smoothing-h">' +
        '<h2 id="raw-smoothing-h">' + esc("Change the smoothing for " + label + "?") + "</h2>" +
        '<p data-role="smooth-from">' + esc("From " + smoothList[smoothStart].name + " to " + smoothList[smoothAt].name + ".") + "</p>" +
        '<p data-role="smooth-text">' + esc(smoothingWarning(label, a.injection_count, a.manual_kept || 0)) + "</p>" +
        (editDrawn() ? '<p data-role="smooth-drops">' + esc(smoothingDropsEdges(label)) + "</p>" : "") +
        (a.standard_all_text ? '<p data-role="smooth-standard">' + esc(a.standard_all_text) + "</p>" : "") +
        '<div class="form-actions is-end"><button type="button" class="btn btn-secondary" data-role="smooth-cancel">Cancel</button>' +
        '<button type="button" class="btn btn-primary" data-role="smooth-apply">' + esc("Apply to all " + label + " peaks") + "</button></div></div>";
      doc.body.appendChild(m);
      var cancelBtn = m.querySelector('[data-role="smooth-cancel"]'), applyBtn = m.querySelector('[data-role="smooth-apply"]');
      /* Escape answers this question only, and the focus stays on its two buttons: caught before the drawer's own keys */
      function keys(e) {
        if (e.key === "Escape") { e.stopPropagation(); cancel(); return; }
        if (e.key === "Tab") {
          e.preventDefault();
          e.stopPropagation();
          (doc.activeElement === cancelBtn ? applyBtn : cancelBtn).focus();
        }
      }
      function shut() {
        ui.smoothClose = null;
        doc.removeEventListener("keydown", keys, true);
        if (m.parentNode) { m.parentNode.removeChild(m); }
        if (back && back.focus) { try { back.focus(); } catch (e) { /* gone */ } }
      }
      function cancel() { shut(); smoothTo(smoothStart); }
      ui.smoothClose = shut;
      doc.addEventListener("keydown", keys, true);
      cancelBtn.addEventListener("click", cancel);
      applyBtn.addEventListener("click", function () { shut(); sendSmoothing(!!a.standard_all_text); });
      cancelBtn.focus();
    }
    function applyOne() {
      if (ui.busy[ui.index]) { return; }
      if (smoothChanged()) {
        if (needsSmoothingWarning(smoothList[smoothStart].m, smoothList[smoothAt].m, "one")) { askSmoothing(); }
        return;
      }
      if (st.mode === "revert") { post(); return; }
      if (st.mode === "delete" && needsConfirm() && !ui.armed) {
        ui.armed = true;            /* a confirming click first */
        update();
        return;
      }
      ui.commentOpen = true;
      update();
      if (reasonSel) { reasonSel.focus(); }
    }

    /* the partner's edit when this peak's shared edge was moved under a drop (partnerEdit), else null */
    function sharedEdit(res) {
      var side = dropSideOf(), t = tr();
      if (!side || !res) { return null; }
      return partnerEdit(side, side === "start" ? res.start : res.end, a.partner, measure(a, "drop_rt"),
                         2 * edgeTolerance(t.t, t.full_res || limits()));
    }
    function post() {
      var t = tr(), idx = ui.index;
      if (ui.busy[idx]) { return; }
      var asked = st.mode !== "revert";
      if (asked && commentProblem(reasonSel.value, detailBox.value)) { return; }
      var kind = st.mode === "integrate" ? st.kind : st.mode, edit = editOf();
      if (kind === "fit" && (fitProblem(st) || !previewOk())) { return; }
      var res = kind === "integrate" ? judge(a, t, edit) : null;
      var levels = kind === "integrate" ? edit.levels : null;
      var payload = editPayload({ injection: a.injection, analyte: a.analyte, transition: ui.index ? t.transition : "",
                                  mode: data.mode, kind: kind, start: res ? res.start : st.start,
                                  end: res ? res.end : st.end, apex: st.apex, baseline: st.baseline, levels: levels,
                                  confirm: kind === "delete" && ui.armed, partner: kind === "integrate" ? sharedEdit(res) : null,
                                  reason_id: asked ? reasonSel.value : "", detail: asked ? detailBox.value : "" });
      if (kind === "fit") {
        var fp = fitPayload(st, a, t);
        for (var fk in fp) { if (fp.hasOwnProperty(fk)) { payload[fk] = fp[fk]; } }
      }
      /* the edit as posted: what a refusal draws again */
      var posted = { transition: t.transition, kind: kind, start: res ? res.start : st.start, end: res ? res.end : st.end,
                     apex: st.apex, baseline: st.baseline, levels: levels };
      if (kind === "fit") { posted.shape = st.shape; posted.apexes = fitApexSorted(st.apexes); posted.pick = fitPick(st, a, t); posted.alone = !!st.alone; }
      var was = snap(), since = (data.failure && data.failure.at) || "";
      ui.busy[idx] = true;
      ui.stack.clear();            /* the edit is sent: its steps are no longer the card's to take back; a refusal draws the edit as posted */
      ui.commentOpen = false;
      var old = body.querySelector("p.raw-refusal.is-flash");
      if (old) { old.textContent = ""; }
      update();
      ui.say(idx, "Saving the change.", false);
      var formData = new FormData();
      ["action", "_authenticator"].forEach(function (n) { if (f.elements[n]) { formData.append(n, f.elements[n].value); } });
      for (var pk in payload) { if (payload.hasOwnProperty(pk)) { formData.append(pk, payload[pk]); } }
      var mine = ui;
      /* the form's own address: a field named action shadows form.action */
      fetch(f.getAttribute("action"), { method: "POST", body: formData, credentials: "same-origin", headers: { "Accept": "application/json" } })
        .then(function (r) { return r.text().then(function (text) { return replyFrom(r, text); }); })
        .then(function (reply) {
          if (reply.ok) {
            if (asked) { reasonSel.value = ""; detailBox.value = ""; }
            waitForRun({ data: data, ui: mine, idx: idx, last: { transition: t.transition, notes: reply.notes },
                         waiting: reply.waiting, since: since, was: was });
            return;
          }
          answered(reply.error || "The change was not applied.", !reply.session && !reply.noanswer);
        })
        .catch(function () { answered("The change could not be sent.", false); });
      /* a refusal, an ended session or no answer: in the card when it is still the one shown,
         else on the page, where the analyst now is */
      function answered(text, refusal) {
        if (current === mine && drawerOpen()) {
          delete mine.busy[idx];
          if (refusal) { refused(idx, text, posted); } else { mine.say(idx, text, true); }
          update();
        } else {
          delete mine.busy[idx];
          pageNote(text, true);
        }
      }
    }

    function showTrace() {
      ui.stack.clear();
      ui.boxWas = null;
      startState();
      var pk = tr().peak;
      ui.view = pk && pk.start != null && pk.end != null && !tr().deleted ? peakView(pk.start, pk.end, limits()) : null;
      ui.yview = null;
      ui.handle = "start";
      var step = edgeStep(tr().t, tr().full_res), edges = body.querySelectorAll("input[data-edge]");
      for (var k = 0; k < edges.length; k++) { edges[k].setAttribute("step", step); }
      if (traceSeg) { pressSeg(traceSeg, String(ui.index)); }
      if (editable) { boxes(); }
      draw();
      update();
      paintSaid();
    }

    if (editable) {
      var shapeSeg = body.querySelector('.pfas-seg[aria-label="Shape"]');
      if (shapeSeg) {
        onSeg(shapeSeg, function (v) { var was = snapshot(); st.shape = v; recorded(was); update(); });
      }
      submit.addEventListener("click", applyOne);
      allBtn.addEventListener("click", applyAll);
      backBtn.addEventListener("click", backToAutomatic);
      commentGo.addEventListener("click", post);
      reasonSel.addEventListener("change", update);
      detailBox.addEventListener("input", update);
      ["start", "end"].forEach(function (edge) {
        var box = body.querySelector('input[data-edge="' + edge + '"]');
        box.addEventListener("input", function () {
          if (!ui.boxWas) { ui.boxWas = snapshot(); }
          var v = box.value === "" ? null : parseFloat(box.value);
          st[edge] = v != null && isNaN(v) ? box.value : v;
          st.note = "";
          if (st.mode !== "fit") { st.mode = "integrate"; st.kind = "integrate"; st.touched = true; }
          update();
        });
        box.addEventListener("change", function () {         /* typed, or the stepper's buttons: on its sample */
          var v = parseFloat(box.value), t = tr();
          var was = ui.boxWas || snapshot();
          ui.boxWas = null;
          if (isNaN(v)) { recorded(was); return; }       /* what the input wrote is one step too */
          var kept = typedEdge(t.t, v, t.full_res, edge);
          st[edge] = kept.value;
          st.note = kept.note;
          if (st.mode !== "fit") { st.mode = "integrate"; st.kind = "integrate"; st.touched = true; }
          recorded(was);
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
          var h = handleState(side), d = handleDrag(h, { y: v });
          takeDrag(d);
        });
      });
    }
    showTrace();
    /* the card made again after an apply: the zoom it had */
    if (keep && keep.viewIndex === ui.index) {
      ui.view = keep.view;
      ui.yview = keep.yview || null;
      draw();
    }
    /* the last expected time set stays in view as the walk goes on */
    var said = body.querySelector('[data-role="said"]');
    if (said && rtLast && a.set_rt_url) { said.textContent = rtLast; }
  }

  /* the last expected retention time set, said on each card opened after it */
  var rtLast = null;
  /* what the expected-time line did, said on the open card */
  function announce(text, isError) {
    var C = components(), box = C && C.drawer && C.drawer.el ? C.drawer.el.querySelector('[data-role="said"]') : null;
    if (!isError) { rtLast = text; }
    if (box) {
      box.className = isError ? "raw-refusal" : "raw-note";
      box.textContent = text;
    }
  }
  /* the focus on Next, where there is a next chromatogram */
  function focusNext() {
    var C = components(), b = C && C.drawer && C.drawer.el ? C.drawer.el.querySelector('button[data-step="1"]') : null;
    if (b && !b.disabled) { b.focus(); }
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
      b.disabled = !shownCard || !stepFrom(shownCard.data, shownCard.injection, shownCard.analyte, d[0]);
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
  /* Ctrl+Arrow: along the grid's own axis (the compounds of an injection, the injections of a
     compound) the next card of the grid, as Page Down; across it, the grid's selection moves to
     the next injection or compound whose pair has a trace, the grid and its list made again for
     it. A change drawn and not posted is asked about first. */
  function walk(act, by) {
    if (!shownCard || !drawerOpen() || asking()) { return; }
    var data = shownCard.data, along = data.mode === "compound" ? act === "injection" : act === "compound";
    var go = function () {
      if (along) { move(by); return; }
      var stamp = asked, at = { injection: shownCard.injection, analyte: shownCard.analyte };
      (function next() {
        var to = stepTarget(data, at.injection, at.analyte, act, by);
        if (!to) { return; }                               /* the end: the card stays */
        fetchTab(data, act === "injection" ? to.injection : to.analyte).then(function (fresh) {
          if (stamp !== asked || !drawerOpen() || !fresh || typeof fresh !== "object") { return; }
          if (!hasTrace(fresh, to)) { at = to; next(); return; }
          applyTab(data, fresh);
          openCard(data, to.injection, to.analyte, "", null, by);
          followThumb(gridRoot, to.injection, to.analyte, components().drawer);
        }).catch(function () { /* the card stays */ });
      })();
    };
    if (current && current.dirty && current.dirty()) { askLeave(go); } else { go(); }
  }
  function hasTrace(fresh, to) {
    return (fresh.thumbs || []).some(function (th) {
      return th.injection === to.injection && th.analyte === to.analyte && th.state !== "missing";
    });
  }

  /* the keys panel (KEYS_HELP) in a dialog over the card; it takes every key while open */
  var keysBack = null;
  function keysBox() {
    var m = doc.getElementById("raw-keys");
    if (m) { return m; }
    m = el("div", "pfas-modal is-top");
    m.id = "raw-keys";
    var rows = KEYS_HELP.map(function (r) {
      return "<tr><th scope=\"row\"><kbd>" + esc(r[0]) + "</kbd></th><td>" + esc(r[1]) + "</td></tr>";
    }).join("");
    m.innerHTML = '<div class="pfas-modal-box" role="dialog" aria-modal="true" aria-labelledby="raw-keys-h">' +
      '<h2 id="raw-keys-h">Keys</h2><table class="raw-keys"><tbody>' + rows + "</tbody></table>" +
      '<p class="raw-note">Cmd works as Ctrl on a Mac.</p>' +
      '<div class="form-actions is-end"><button type="button" class="btn btn-secondary" data-role="close">Close</button></div></div>';
    doc.body.appendChild(m);
    m.querySelector('[data-role="close"]').addEventListener("click", function () { shutKeys(); });
    return m;
  }
  function keysOpen() { var m = doc.getElementById("raw-keys"); return !!(m && m.classList.contains("open")); }
  function toggleKeys() {
    if (keysOpen()) { shutKeys(); return; }
    var m = keysBox();
    keysBack = doc.activeElement;
    m.classList.add("open");
    var b = m.querySelector('[data-role="close"]');
    if (b && b.focus) { b.focus(); }
  }
  function shutKeys() {
    var m = doc.getElementById("raw-keys");
    if (m) { m.classList.remove("open"); }
    if (keysBack && keysBack.focus) { try { keysBack.focus(); } catch (e) { /* gone */ } }
    keysBack = null;
  }

  function move(step) {
    if (!shownCard || !drawerOpen() || asking()) { return; }
    var th = stepFrom(shownCard.data, shownCard.injection, shownCard.analyte, step), data = shownCard.data;
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
  function asking() {
    var m = doc.getElementById("raw-leave");
    return !!((m && m.classList.contains("open")) || doc.getElementById("raw-smoothing"));
  }

  /* the grid made again from raw_tab=1 for the mode and selection shown: the list and the
     thumbnails (and the banner) in place, the data object kept so the open handlers see it */
  function tabUrl(data, query, pick) {
    var sel = data.mode === "compound" ? "analyte" : "injection", chosen = pick || data.selected;
    return data.card_url.replace("raw_card=1", query) + "&mode=" + data.mode +
           (chosen ? "&" + sel + "=" + encodeURIComponent(chosen) : "");
  }
  /* the grid's answer for the selection pick (the shown one when none) */
  function fetchTab(data, pick) {
    return fetch(tabUrl(data, "raw_tab=1", pick), { credentials: "same-origin", headers: { "Accept": "application/json" } })
      .then(function (r) { return r.json(); });
  }
  function refreshGrid(data) {
    return fetchTab(data).then(function (fresh) { applyTab(data, fresh); });
  }
  function applyTab(data, fresh) {
    if (!gridRoot || !fresh || typeof fresh !== "object") { return; }
    for (var k in fresh) { if (fresh.hasOwnProperty(k) && k !== "card_url") { data[k] = fresh[k]; } }
    /* an answer that names no processing has none */
    data.processing = fresh.processing || null;
    data.busy = fresh.busy || [];
    var mode = data.mode === "compound" ? "compound" : "injection";
    var list = gridRoot.querySelector(".raw-list"), thumbs = gridRoot.querySelector(".raw-sections");
    if (list) { list.innerHTML = listHtml(data, mode); }
    if (thumbs) { thumbs.innerHTML = sectionsHtml(data); }
    var C = components();
    if (C && C.init) { C.init(list || gridRoot); if (thumbs) { C.init(thumbs); } }
    setBanner(banner(data));
    setBand(data);
  }
  /* only what says the run is being processed: the band and the dimmed cards */
  function applyBusy(data, fresh) {
    if (!gridRoot || !fresh || typeof fresh !== "object") { return; }
    ["processing", "pending", "busy"].forEach(function (k) { if (fresh.hasOwnProperty(k)) { data[k] = fresh[k]; } });
    setBand(data);
    var thumbs = gridRoot.querySelector(".raw-sections"), C = components();
    if (thumbs) { thumbs.innerHTML = sectionsHtml(data); if (C && C.init) { C.init(thumbs); } }
  }
  function setBand(data) {
    var slot = gridRoot && gridRoot.querySelector(".raw-band");
    if (slot) { slot.innerHTML = processingBand(data.processing); }
  }
  /* the page while the worker processes the run, or while its store cannot be read: the run's
     status (raw_status=1, the light read: it carries the band) looked at every poll_ms, the band's
     words kept current, and once nothing is processed the grid read once (raw_tab=1) and made again
     in place; no full reload. An ended session stops it, saying nothing new. A hidden page stops looking and looks again once it is
     shown. One watch for the page; an edit's own wait (waitForRun) takes its place */
  var runWatch = null;
  function pagePollMs(data) {
    return pollEvery(data && data.processing && data.processing.poll_ms, (api && api.PAGE_POLL_MS) || PAGE_POLL_MS,
                     minPoll());
  }
  function stopWatch() {
    if (runWatch && runWatch.timer) { clearTimeout(runWatch.timer); }
    runWatch = null;
  }
  function watchRun(data) {
    stopWatch();
    var me = { timer: null, look: null, inFlight: false };
    runWatch = me;
    function next() { me.inFlight = false; if (runWatch === me) { me.timer = setTimeout(me.look, pagePollMs(data)); } }
    me.look = function () {
      me.timer = null;
      if (runWatch !== me || (doc && doc.hidden) || me.inFlight) { return; }
      me.inFlight = true;
      fetch(tabUrl(data, "raw_status=1"), { credentials: "same-origin", headers: { "Accept": "application/json" } })
        .then(function (r) { return r.text().then(function (text) { return statusFrom(r, text); }); })
        .then(function (res) {
          if (runWatch !== me) { return; }
          /* the session ended: the looking stops and nothing new is said, as the card's wait does */
          if (res.session) { stopWatch(); return; }
          if (!res.status) { next(); return; }
          var p = res.status.processing;
          if (p) { data.processing = p; setBand(data); setBanner(banner(data)); next(); return; }
          stopWatch();
          refreshGrid(data).catch(function () { /* the grid stays as it was */ });
        })
        .catch(next);
    };
    next();
  }
  function wakeWatch() {
    if (doc && !doc.hidden && watchIdle(runWatch)) { runWatch.look(); }
  }
  function setBanner(note) {
    var old = null, kids = gridRoot.children || [], k;
    for (k = 0; k < kids.length; k++) { if (/(^|\s)raw-banner(\s|$)/.test(kids[k].className || "")) { old = kids[k]; break; } }
    if (old && !note) { old.parentNode.removeChild(old); }
    else if (note && !old) { old = el("p", ""); old.setAttribute("role", "status"); gridRoot.insertBefore(old, gridRoot.firstChild); }
    if (old && note) { old.className = "raw-banner " + note.cls; old.textContent = note.text; }
  }
  /* a word to the analyst on the page, over the grid: where an answer lands when the card
     it was for is no longer the one shown */
  function pageNote(text, isError) {
    if (!gridRoot) { return; }
    setBanner({ cls: isError ? "is-fail" : "is-warn", text: text });
  }
  /* the run is processed again: one poll for the page (never two: a newer wait ends the
     older), kept when the card closes, looking at the status each POLL_MS until nothing
     waits. Then the grid is made again in place and, if the card that made the edit is still
     open and nothing was drawn on it since, the card too (the trace and zoom kept).
     o: data, ui (the card; null when the page loaded waiting), idx (its trace), last, waiting,
     since (the failure on record when the edit was posted), was (the edit as drawn then) */
  /* the page may start its wait while the file is still being read, before `api` exists */
  function pollMs() { return (api && api.POLL_MS) || POLL_MS; }
  function waitForRun(o) {
    var data = o.data, ui = o.ui, idx = o.idx, mygen, started = Date.now(), bad = 0;
    function open() { return !!ui && current === ui && drawerOpen(); }
    function end() {
      if (generation === mygen) { generation++; chain = null; }
      stopPoll();
      if (ui) { ui.release(idx); }
    }
    function live() { return generation === mygen; }
    function note(text, isError) {
      if (open()) { ui.say(idx, text, isError); } else { pageNote(text, isError); }
    }
    function reopen() {
      if (!open()) { return; }
      var a = ui.a, last = { transition: o.last.transition, notes: o.last.notes };
      var v = ui.index === idx ? ui.zoomed() : null;
      if (v) { last.hasView = true; last.view = v.view; last.yview = v.yview; last.viewIndex = idx; }
      openCard(data, a.injection, a.analyte, "", last);
      followThumb(gridRoot, a.injection, a.analyte, components().drawer);
    }
    function finish() {
      refreshGrid(data).catch(function () { /* the grid stays as it was */ }).then(function () {
        if (!live()) { return; }
        end();
        if (data.processing) { watchRun(data); }
        if (!open()) { return; }
        if (ui.drawnSince(o.was)) { ui.unsay(); askLeave(reopen); } else { reopen(); }
      });
    }
    /* the wait ends in failure: the grid made again first, so its banner (the server's) is
       not written over; a word of ours after it only where the server has none (`word`) */
    function lost(text, word) {
      end();
      var after = generation;
      refreshGrid(data).catch(function () { /* as it was */ }).then(function () {
        /* the page looks on as after a finished wait, unless a newer wait has begun meanwhile */
        if (generation === after && data.processing) { watchRun(data); }
        if (word) { note(text, true); } else if (open()) { ui.say(idx, text, true); }
      });
    }
    function again() {
      if (!live()) { return; }
      if (++bad >= 3) { lost(STATUS_LOST, true); return; }
      poll = setTimeout(look, pollMs());
    }
    function look() {
      poll = null;
      if (!live()) { return; }
      /* a hidden page asks nothing; it looks again once shown */
      if (doc && doc.hidden) { poll = setTimeout(look, pollMs()); return; }
      fetch(tabUrl(data, "raw_status=1"), { credentials: "same-origin", headers: { "Accept": "application/json" } })
        .then(function (r) { return r.text().then(function (text) { return statusFrom(r, text); }); })
        .then(function (res) {
          if (!live()) { return; }
          if (res.session) { end(); note(SESSION_ENDED, true); return; }
          if (!res.status) { again(); return; }
          bad = 0;
          if (res.status.processing !== undefined) { data.processing = res.status.processing; setBand(data); }
          var step = pollStep(res.status, Date.now() - started, o.since);
          if (step.done) { finish(); return; }
          if (step.failed) { lost(step.text, false); return; }
          if (open()) { ui.say(idx, step.text, false); }     /* the page's banner is the server's */
          poll = setTimeout(look, pollMs());
        })
        .catch(again);
    }
    if (chain) { chain(); }
    chain = null;
    stopPoll();
    stopWatch();
    mygen = ++generation;
    if (ui) { chain = function () { ui.release(idx); }; }
    if (o.waiting === false) { finish(); return; }
    if (open()) { ui.say(idx, pollStep({ waiting: true }, 0).text, false); }
    poll = setTimeout(look, pollMs());
    /* the band and the cards being processed, read once as the wait starts: the edited card
       dimmed and the band shown at once; the banner and the list are the wait's to say */
    if (ui) {
      fetch(tabUrl(data, "raw_tab=1") + "&busy=1", { credentials: "same-origin", headers: { "Accept": "application/json" } })
        .then(function (r) { return r.json(); })
        .then(function (fresh) { if (live()) { applyBusy(data, fresh); } })
        .catch(function () { /* the grid stays as it was */ });
    }
  }

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

  /* a card's status as one icon (icons.py), ranked once here: failed, flagged, edited,
     waiting, not detected, passed. No reading (state "missing") has none. `pending`: an
     edit of the trace waits for the run. */
  var STATUS_ORDER = ["fail", "warn", "edit", "waiting", "not-detected", "pass"];
  var STATUS_WORD = { "fail": "Failed", "warn": "Flagged", "edit": "Edited", "waiting": "Waiting",
                      "not-detected": "Not detected", "pass": "Passed" };
  var STATUS_COLOUR = { "fail": "fail", "warn": "warn", "edit": "warn", "waiting": "info",
                        "not-detected": "neutral", "pass": "ok" };
  function thumbStatus(th, pending) {
    if (th.state === "missing") { return null; }
    var waits = th.edit === "pending" || !!pending, icon;
    if (th.state === "fail" || (th.failed && th.failed.length)) { icon = "fail"; }
    else if (th.state === "warn") { icon = "warn"; }
    else if (isManual(th) && (th.edit !== "pending" || th.auto)) { icon = "edit"; }
    else if (waits) { icon = "waiting"; }
    else if (th.state === "nd") { icon = "not-detected"; }
    else { icon = "pass"; }
    return { icon: icon, label: STATUS_WORD[icon], colour: STATUS_COLOUR[icon] };
  }
  /* the first-ranked of several statuses (null ones are passed over) */
  function worstStatus(list) {
    var best = null;
    (list || []).forEach(function (st) {
      if (st && (!best || STATUS_ORDER.indexOf(st.icon) < STATUS_ORDER.indexOf(best.icon))) { best = st; }
    });
    return best;
  }
  function pendingKeysOf(data) {
    var keys = {};
    (data.pending || []).forEach(function (p) { keys[p.injection + "|" + p.analyte] = true; });
    return keys;
  }
  /* the cards the worker is processing again: an edit or a processing change of theirs waits
     (data.pending, data.busy), while the run is processed (data.processing) */
  function busyKeysOf(data) {
    var keys = {};
    if (!data.processing || data.processing.state === "unreadable") { return keys; }
    (data.pending || []).concat(data.busy || []).forEach(function (p) { keys[p.injection + "|" + p.analyte] = true; });
    return keys;
  }
  /* one injection's row in the list, ranked by thumbStatus from the same inputs whether or not it is
     the one open: failed checks, flagged-only, and an edit on record (waiting while the run is
     processed again). The open injection adds only a waiting edit of its own traces (data.pending):
     an edit comes from edited_in alone, so the row ranks the same open or shut. */
  function injectionStatus(data, i, own) {
    var edited = (data.edited_in || []).indexOf(i.name) >= 0;
    var sts = [thumbStatus({ state: (i.failed && i.failed.length) || i.flagged ? "fail" : (i.warned ? "warn" : ""),
                             edit: edited ? (data.waiting ? "pending" : "edited") : "auto" }, false)];
    if (own) {
      var keys = pendingKeysOf(data);
      (data.thumbs || []).forEach(function (th) {
        if (keys[th.injection + "|" + th.analyte]) { sts.push(thumbStatus({ state: "", edit: "auto" }, true)); }
      });
    }
    return worstStatus(sts);
  }
  function icons() {
    var w = typeof window !== "undefined" ? window : null;
    return w && w.PFAS && w.PFAS.components && w.PFAS.components.icon;
  }
  function statusIcon(st) {
    if (!st) { return ""; }
    var I = icons();
    return (I && I.svg(st.icon, { label: st.label, colour: st.colour })) || esc(st.label);
  }
  function hhmm(when) {
    var m = /(\d\d):(\d\d)/.exec(String(when || "").replace(/^[^T ]*[T ]/, ""));
    return m ? m[1] + ":" + m[2] : "";
  }
  var COMPACT_KEY = "raw-compact-list";
  function compactList() {
    try { return window.localStorage.getItem(COMPACT_KEY) === "1"; } catch (e) { return false; }
  }
  function setCompactList(on) {
    try { window.localStorage.setItem(COMPACT_KEY, on ? "1" : "0"); } catch (e) { /* not remembered */ }
  }
  /* the left list: the order warning above the entries, the selected injection's status
     from its thumbnails; one place for the first draw and every redraw */
  function listHtml(data, mode) {
    var h = "";
    if (mode === "injection" && data.order_warning) { h += '<p class="raw-order-warning" role="status">' + esc(data.order_warning) + "</p>"; }
    if (mode === "compound") {
      /* the picker in the grid's sections, each under its name */
      return h + sectionsOf(data.list, data.sections).map(function (sec) {
        return '<p class="raw-list-head">' + esc(sec.title) + "</p>" + sec.items.map(function (i) {
          return listItem(mode, i, data.selected);
        }).join("");
      }).join("");
    }
    return h + (data.list || []).map(function (i) {
      return listItem(mode, i, data.selected, mode === "injection" ? injectionStatus(data, i, i.name === data.selected) : undefined);
    }).join("");
  }

  function listHref(mode, name) {
    return "?tab=raw&amp;mode=" + mode + "&amp;" + (mode === "compound" ? "analyte" : "injection") + "=" +
           encodeURIComponent(name);
  }

  /* one entry of the list down the left: a button to its page, its type
     and how many of its rows are flagged */
  /* a row's failed checks: the count beside the diamond (a hidden drawing), the checks as the
     row's tooltip on hover and focus, and as the row's description for a screen reader; the row
     link stays the one tab stop */
  var rowSeq = 0;
  function failMark(i) {
    var failed = i.failed || [], count = failed.length || i.flagged || 0, I = icons();
    if (!count) { return null; }
    var id = "raw-li-" + (rowSeq++) + "-" + String(i.name).replace(/[^A-Za-z0-9_-]/g, "_");
    var words = "Failed: " + count + (count === 1 ? " check" : " checks") + (failed.length ? ". " + failed.join(" \u00b7 ") : "");
    return { id: id, words: words, tip: failed.join(" \u00b7 "),
             mark: ((I && I.svg("fail", { hidden: true })) || esc("Failed ")) + '<span class="raw-li-count">' + esc(count) + "</span>",
             desc: '<span class="pfas-sr-hide" id="' + id + '">' + esc(words) + "</span>" };
  }
  /* in "By injection": position, time, name, type icon with its word and the status icon; in
     "By compound": the name and its failed count. `status` overrides the entry's own */
  function listItem(mode, i, selected, status) {
    var cur = i.name === selected ? ' aria-current="true"' : "", f = failMark(i);
    var tip = f ? ' aria-describedby="' + f.id + '"' + (f.tip ? ' data-pfas-tip="' + esc(f.tip) + '"' : "") : "";
    if (mode !== "injection") {
      return '<a class="btn-sm btn-secondary" href="' + listHref(mode, i.name) + '"' + cur + tip + ">" + esc(i.label || i.name) +
             '<span class="raw-type">' + (f ? '<span class="raw-li-fail">' + f.mark + "</span>" : "") + "</span></a>" + (f ? f.desc : "");
    }
    var st = status || (f ? { icon: "fail", label: "Failed", colour: "fail" } : { icon: "pass", label: "Passed", colour: "ok" });
    var mark = st.icon === "fail" && f ? f.mark : statusIcon(st), T = typeof window !== "undefined" && window.PFAS && window.PFAS.components;
    var type = T && T.type && i.type ? T.type.cell(i.type, i.type) : "";
    return '<a class="btn-sm btn-secondary raw-li" href="' + listHref(mode, i.name) + '"' + cur + tip + ">" +
           '<span class="raw-li-pos">' + esc(i.position || "") + '</span><span class="raw-li-time">' + esc(hhmm(i.acquired)) +
           '</span><span class="raw-li-name">' + esc(i.label || i.name) + '</span>' +
           '<span class="raw-type">' + (type || esc(i.type || "")) + '</span><span class="raw-li-status">' + mark + "</span></a>" +
           (f ? f.desc : "");
  }

  /* ── the sections: analytes, surrogates, internal standards ───────────── */
  var SECTION_DEFAULT = [["analyte", "Analytes"], ["surrogate", "Surrogates"], ["internal_standard", "Internal standards"]];
  function sectionKey(item) {
    return item && item.section && SECTION_DEFAULT.some(function (p) { return p[0] === item.section; }) ? item.section : "analyte";
  }
  /* how many of a section's thumbnails failed, carry a warning, were changed by hand or
     were not detected, from their state, edit and qualifier */
  function sectionCounts(thumbs) {
    var out = { failed: 0, warn: 0, manual: 0, nd: 0 };
    (thumbs || []).forEach(function (th) {
      if (th.state === "missing") { return; }
      if (th.state === "fail" || (th.failed && th.failed.length)) { out.failed += 1; }
      if (th.state === "warn") { out.warn += 1; }
      if (isManual(th)) { out.manual += 1; }
      if (th.state === "nd" || th.qualifier === "N.D.") { out.nd += 1; }
    });
    return out;
  }
  /* the sections that hold something, in the server's order: [{ key, title, items }] */
  function sectionsOf(items, pairs) {
    var order = (pairs && pairs.length ? pairs : SECTION_DEFAULT);
    return order.map(function (p) {
      return { key: p[0], title: p[1], items: (items || []).filter(function (x) { return sectionKey(x) === p[0]; }) };
    }).filter(function (sec) { return sec.items.length > 0; });
  }
  var COUNT_WORDS = [["failed", "failed", "fail", "fail", "Failed"], ["warn", "warning", "warn", "warn", "Flagged"],
                     ["manual", "manual", "edit", "warn", "Edited"], ["nd", "not detected", "not-detected", "neutral", "Not detected"]];
  function countIcon(row) {
    return statusIcon({ icon: row[2], label: row[4], colour: row[3] });
  }
  /* the heading's counts of what needs a look: an icon and a number each, none for a count of nought */
  function sectionSummary(counts) {
    return COUNT_WORDS.filter(function (row) { return counts[row[0]] > 0; }).map(function (row) {
      return '<span class="raw-section-count">' + countIcon(row) + counts[row[0]] + " " + row[1] + "</span>";
    }).join("");
  }
  function sectionHead(sec) {
    return '<h3 class="raw-section-head" tabindex="-1">' + esc(sec.title) + " \u00b7 " + sec.items.length +
           '<span class="raw-section-sum">' + sectionSummary(sectionCounts(sec.items)) + "</span></h3>";
  }
  /* a button to each section, above the grid, with how many it holds and an icon for what needs a look */
  function jumpHtml(secs) {
    return '<nav class="raw-jumps" aria-label="Sections">' + secs.map(function (sec) {
      var c = sectionCounts(sec.items);
      return '<button type="button" class="btn-sm btn-secondary raw-jump" data-target="raw-sec-' + esc(sec.key) + '">' + esc(sec.title) +
             ' <span class="raw-jump-n">' + sec.items.length + "</span>" +
             COUNT_WORDS.filter(function (row) { return row[0] !== "nd" && c[row[0]] > 0; }).map(countIcon).join("") + "</button>";
    }).join("") + "</nav>";
  }
  function thumbButton(data, th, pendingKeys, busyKeys) {
    var name = data.mode === "compound" ? th.injection : shown(th), key = th.injection + "|" + th.analyte;
    var busy = !!(busyKeys && busyKeys[key]);
    var cls = "raw-thumb" + (knownState(th.state) ? " is-" + th.state : "") + (th.deleted ? " is-deleted" : "") + (busy ? " is-busy" : "");
    var pending = !!pendingKeys[key], status = thumbStatus(th, pending);
    return '<button type="button" class="' + cls + '" data-injection="' + esc(th.injection) + '" data-analyte="' +
           esc(th.analyte) + '"' + (th.state === "missing" ? ' disabled="disabled"' : "") + ">" +
           thumbSvg(th, { pending: pending }) + '<span class="raw-thumb-head"><span class="raw-thumb-name">' + esc(name) +
           "</span>" + (status ? '<span class="raw-thumb-status">' + statusIcon(status) + "</span>" : "") + "</span>" +
           (busy ? '<span class="raw-thumb-busy">Being processed</span>' : "") + "</button>";
  }

  function thumbsHtml(data) {
    var pendingKeys = pendingKeysOf(data), busyKeys = busyKeysOf(data);
    return (data.thumbs || []).map(function (th) { return thumbButton(data, th, pendingKeys, busyKeys); }).join("");
  }
  /* ── Sort and Show: the funnel's menu ─────────────────────────────────── */
  var FILTER_KEY = "pfas.raw.filter";
  var SORTS = [["az", "A to Z"], ["action", "Action required first"]];
  var SHOWS = [["all", "All"], ["action", "Action required only"], ["detected", "Detected"], ["nd", "Not detected"], ["manual", "Integrated by hand"]];
  function inList(list, v) { return list.some(function (p) { return p[0] === v; }); }
  /* the stored choice as { show, sort }; anything unreadable or unknown is the default */
  function filterRead(raw) {
    var out = { show: "all", sort: "az" }, o = null;
    try { o = raw ? JSON.parse(raw) : null; } catch (e) { o = null; }
    if (o && inList(SHOWS, o.show)) { out.show = o.show; }
    if (o && inList(SORTS, o.sort)) { out.sort = o.sort; }
    return out;
  }
  function filterLoad() {
    try { return filterRead(window.localStorage.getItem(FILTER_KEY)); } catch (e) { return filterRead(null); }
  }
  function filterSave(f) {
    try { window.localStorage.setItem(FILTER_KEY, JSON.stringify(f)); } catch (e) { /* not remembered */ }
  }
  /* a thumb needs action when it failed, carries a warning, or its edit waits for the run */
  function isActionThumb(th, pendingKeys) {
    return th.state === "fail" || th.state === "warn" || !!(th.failed && th.failed.length) || th.edit === "pending" ||
           !!(pendingKeys && pendingKeys[th.injection + "|" + th.analyte]);
  }
  function isNotDetected(th) { return th.state === "nd" || th.qualifier === "N.D."; }
  /* the thumbs a Show choice keeps; a missing reading is neither detected nor not detected */
  function filterThumbs(thumbs, show, pendingKeys) {
    return (thumbs || []).filter(function (th) {
      if (show === "action") { return isActionThumb(th, pendingKeys); }
      if (show === "detected") { return th.state !== "missing" && !isNotDetected(th); }
      if (show === "nd") { return th.state !== "missing" && isNotDetected(th); }
      if (show === "manual") { return isManual(th); }
      return true;
    });
  }
  /* a copy in A to Z order of the card's name (numbers as numbers), or with fail, then warn, then
     waiting first and the rest A to Z; the name is the injection by compound, else the compound */
  function orderThumbs(thumbs, sort, mode, pendingKeys) {
    var name = function (th) { return String(mode === "compound" ? th.injection : shown(th)); };
    var rank = function (th) {
      if (sort !== "action") { return 0; }
      if (th.state === "fail" || (th.failed && th.failed.length)) { return 0; }
      if (th.state === "warn") { return 1; }
      return isActionThumb(th, pendingKeys) ? 2 : 3;
    };
    return (thumbs || []).map(function (th, i) { return { th: th, i: i }; }).sort(function (a, b) {
      return (rank(a.th) - rank(b.th)) || name(a.th).localeCompare(name(b.th), undefined, { numeric: true, sensitivity: "base" }) || (a.i - b.i);
    }).map(function (x) { return x.th; });
  }
  /* the funnel's name: it says when a Show choice is in force, as its colour does */
  function filterLabel(f) { return f && f.show !== "all" ? "Sort and filter, filter is on" : "Sort and filter"; }
  function filterButtonHtml(f, open) {
    var I = icons();
    return '<button type="button" class="btn btn-sm btn-secondary raw-filter' + (f && f.show !== "all" ? " has-filter" : "") +
           '" ' + (f && f.show !== "all" ? 'aria-label="Sort and filter, filter is on"' : 'aria-label="Sort and filter"') + ' aria-expanded="' + (open ? "true" : "false") + '" aria-haspopup="menu">' +
           ((I && I.svg("filter", { hidden: true })) || "") + "</button>";
  }
  /* the menu's entries: two groups, the current choice marked */
  function filterMenuItems(f, pick) {
    var items = [{ head: "Sort" }];
    SORTS.forEach(function (p) {
      items.push({ id: "sort-" + p[0], label: p[1], checked: f.sort === p[0], act: function () { if (pick) { pick({ sort: p[0] }); } } });
    });
    items.push({ head: "Show" });
    SHOWS.forEach(function (p) {
      items.push({ id: "show-" + p[0], label: p[1], checked: f.show === p[0], act: function () { if (pick) { pick({ show: p[0] }); } } });
    });
    return items;
  }
  /* whether the grid, whose box is `rect`, runs below a window of height h (a few pixels are the end) */
  function moreBelow(rect, h) { return !!rect && rect.bottom - h > 8; }
  /* what scrolls the page: the content area of the shell (the body is a fixed height there), else the window */
  function scrollHost(root, win) {
    var host = root && root.closest ? root.closest(".pfas-content-area") : null;
    return host || win;
  }
  /* the host's visible height and its bottom edge on the screen, as moreBelow wants them */
  function hostView(host, win) {
    if (host && host !== win && host.getBoundingClientRect) {
      var r = host.getBoundingClientRect();
      return { bottom: r.bottom, height: host.clientHeight || (r.bottom - r.top) || 768 };
    }
    var h = (win && win.innerHeight) || 768;
    return { bottom: h, height: h };
  }
  function moreButtonHtml() {
    var I = icons();
    return '<button type="button" class="raw-more" aria-label="Scroll down" hidden="hidden">' + ((I && I.svg("expand", { hidden: true })) || "") + "</button>";
  }

  /* the grid in its sections, the jump buttons above them; Show and Sort from data.filter; a
     section with nothing left after Show is not drawn */
  function displayedSections(data) {
    var f = data.filter || filterRead(null), pendingKeys = pendingKeysOf(data);
    var shownThumbs = orderThumbs(filterThumbs(data.thumbs, f.show, pendingKeys), f.sort, data.mode, pendingKeys);
    return sectionsOf(shownThumbs, data.sections);
  }
  /* the thumbnails as the overview shows them: sections in order, each by Sort, after Show; what Previous
     and Next step through. A run still on its first processing shows ghosts, none to open. */
  function displayedThumbs(data) {
    if (!data || (data.processing && data.processing.first)) { return []; }
    var out = [];
    displayedSections(data).forEach(function (sec) { out = out.concat(sec.items); });
    return out;
  }
  function sectionsHtml(data) {
    if (data.processing && data.processing.first) { return ghostSectionsHtml(data.sections); }
    var pendingKeys = pendingKeysOf(data), busyKeys = busyKeysOf(data);
    var secs = displayedSections(data);
    return (secs.length > 1 ? jumpHtml(secs) : "") + secs.map(function (sec) {
      return '<section class="raw-section" id="raw-sec-' + esc(sec.key) + '" data-section="' + esc(sec.key) + '">' + sectionHead(sec) +
             '<div class="raw-thumbs">' + sec.items.map(function (th) { return thumbButton(data, th, pendingKeys, busyKeys); }).join("") +
             "</div></section>";
    }).join("");
  }

  function render(root, data) {
    var mode = data.mode === "compound" ? "compound" : "injection";
    var h = "", note = banner(data);
    if (note) { h += '<p class="raw-banner ' + note.cls + '" role="status">' + esc(note.text) + "</p>"; }
    h += '<div class="raw-band">' + processingBand(data.processing) + "</div>";
    data.filter = data.filter || filterLoad();
    h += '<div class="raw-viewbar"><nav class="pfas-seg pfas-seg-sm" aria-label="View">' +
         [["compound", "By compound"], ["injection", "By injection"]].map(function (m) {
           return '<a class="pfas-seg-item' + (m[0] === mode ? ' is-on" aria-current="page"' : '"') +
                  ' href="?tab=raw&amp;mode=' + m[0] + '">' + m[1] + "</a>";
         }).join("") + "</nav>" + filterButtonHtml(data.filter) + "</div>";
    h += '<div class="raw-split' + (mode === "injection" && compactList() ? " is-compact" : "") + '"><div class="raw-side">' +
         (mode === "injection" ? '<label class="pfas-switch raw-compact"><input type="checkbox" data-role="compact"' +
           (compactList() ? ' checked="checked"' : "") + '><span class="pfas-switch-track"></span> Compact list</label>' : "") +
         '<nav class="raw-list" aria-label="' + (mode === "compound" ? "Compounds" : "Injections") + '">' + listHtml(data, mode) +
         "</nav></div><div class=\"raw-overview\">";
    if ((data.cal_dropped || []).length) {
      h += '<p class="raw-dropped">Calibrators off the curve by a deleted peak: ' +
           esc(data.cal_dropped.map(function (c) { return c.injection; }).join(", ")) + "</p>";
    }
    h += '<div class="raw-sections">' + sectionsHtml(data) + "</div></div></div>" + moreButtonHtml();
    root.innerHTML = h;
    gridRoot = root;
    var C = components();
    if (C && C.init) { C.init(root); }
    root.addEventListener("change", function (e) {
      var box = e.target && e.target.getAttribute && e.target.getAttribute("data-role") === "compact" ? e.target : null;
      if (!box) { return; }
      setCompactList(box.checked);
      var split = root.querySelector(".raw-split");
      if (split) { split.classList.toggle("is-compact", !!box.checked); }
    });
    var host = scrollHost(root, window);
    function showMore() {
      var more = root.querySelector(".raw-more"), grid = root.querySelector(".raw-sections");
      if (more && grid) { more.hidden = !moreBelow(grid.getBoundingClientRect(), hostView(host, window).bottom); }
    }
    /* bound once for the page, to what scrolls it: the shell's content area, else the window */
    if (!root.getAttribute("data-more-bound")) {
      root.setAttribute("data-more-bound", "1");
      host.addEventListener("scroll", showMore, { passive: true });
      window.addEventListener("resize", showMore);
    }
    showMore();
    root.addEventListener("click", function (e) {
      if (e.target.closest("button.raw-more")) {
        host.scrollBy({ top: Math.round(hostView(host, window).height * 0.85), behavior: "smooth" });
        return;
      }
      var funnel = e.target.closest("button.raw-filter");
      if (funnel) {
        var Cm = components();
        if (!Cm || !Cm.menu) { return; }
        if (Cm.menu.isOpen()) { Cm.menu.close(true); return; }
        Cm.menu.open(filterMenuItems(data.filter, function (change) {
          var f = { show: change.show || data.filter.show, sort: change.sort || data.filter.sort };
          data.filter = f;
          filterSave(f);
          funnel.classList.toggle("has-filter", f.show !== "all");
          funnel.setAttribute("aria-label", filterLabel(f));
          var box = root.querySelector(".raw-sections");
          if (box) { box.innerHTML = sectionsHtml(data); if (Cm.init) { Cm.init(box); } }
          showMore();
        }), { anchor: funnel, opener: funnel, label: "Sort and filter" });
        return;
      }
      var jump = e.target.closest("button.raw-jump");
      if (jump) {
        var sec = doc.getElementById(jump.getAttribute("data-target"));
        if (sec && sec.scrollIntoView) { sec.scrollIntoView({ block: "start", behavior: "smooth" }); }
        var head = sec && sec.querySelector(".raw-section-head");
        if (head && head.focus) { head.focus(); }
        return;
      }
      var b = e.target.closest("button.raw-thumb");
      if (b && !b.disabled) { openCard(data, b.getAttribute("data-injection"), b.getAttribute("data-analyte"), "", null); }
    });
    /* the open card's keys (keyMap), caught before the drawer's own
       Escape: PageUp and PageDown walk the overview, Escape asks first when
       a change is not applied, the rest are the card's; none while the
       question or a menu is open, or with the focus outside the dialog */
    doc.addEventListener("keydown", function (e) {
      var C = components(), t = e.target || doc.body;
      if (keysOpen()) {
        /* the list takes every key: Escape or ? shuts it, the card behind stays as it is */
        if (e.key === "Escape" || e.key === "?") { e.preventDefault(); e.stopPropagation(); shutKeys(); }
        else if (e.key === "Tab") { e.preventDefault(); }
        return;
      }
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
    /* the run being processed when the page loads, or its store unreadable: the page looks again */
    if (data.processing) { watchRun(data); }
    /* back from an edit: its card again, with what the server said of it */
    var target = openTarget(window.location.search);
    if (target) {
      /* the edit as the server says it was posted */
      var last = target.posted || null;
      if (target.notes.length) {
        last = last || { transition: "" };
        last.notes = target.notes;
      }
      try { history.replaceState(null, "", window.location.pathname + withoutOpen(window.location.search) + window.location.hash); }
      catch (e) { /* the address stays */ }
      openCard(data, target.injection, target.analyte, target.error, last);
    }
  }

  /* the Overview's line while the run is processed (#raw-busy-line), from the run's status
     (raw_status=1): done once nothing is processed; the server's words while it is; a store that
     cannot be read just now keeps the words it had */
  function lineStep(status) {
    var p = status && status.processing;
    if (!p) { return { done: true, text: null }; }
    return { done: false, text: p.state === "unreadable" ? null : (p.text || null) };
  }
  /* the line looked at every data-poll-ms; it goes once the run is done, with no reload. A hidden
     page stops looking and looks again once shown; an ended session stops it */
  var lineWatch = null;
  function watchLine(line) {
    var me = { timer: null, look: null, inFlight: false }, url = line.getAttribute("data-status-url");
    var every = pollEvery(line.getAttribute("data-poll-ms"), PAGE_POLL_MS, minPoll());
    lineWatch = me;
    function next() { me.inFlight = false; if (lineWatch === me) { me.timer = setTimeout(me.look, every); } }
    me.look = function () {
      me.timer = null;
      if (lineWatch !== me || doc.hidden || me.inFlight) { return; }
      me.inFlight = true;
      fetch(url, { credentials: "same-origin", headers: { "Accept": "application/json" } })
        .then(function (r) { return r.text().then(function (text) { return statusFrom(r, text); }); })
        .then(function (res) {
          if (lineWatch !== me) { return; }
          if (res.session) { lineWatch = null; return; }
          if (!res.status) { next(); return; }
          var step = lineStep(res.status);
          if (step.done) {
            if (line.parentNode) { line.parentNode.removeChild(line); }
            lineWatch = null;
            return;
          }
          var words = line.querySelector(".pfas-busy-line");
          if (step.text && words) { words.textContent = step.text; }
          next();
        })
        .catch(next);
    };
    next();
  }

  if (doc) {
    var start = function () {
      var src = doc.getElementById("raw-data-json"), root = doc.getElementById("raw-data");
      if (src && root) { render(root, JSON.parse(src.textContent)); }
      var line = doc.getElementById("raw-busy-line");
      if (line) { watchLine(line); }
    };
    doc.addEventListener("visibilitychange", function () {
      wakeWatch();
      if (!doc.hidden && watchIdle(lineWatch)) { lineWatch.look(); }
    });
    if (doc.readyState === "loading") { doc.addEventListener("DOMContentLoaded", start); } else { start(); }
  }
  var api = { replyOf: replyOf, replyFrom: replyFrom, statusFrom: statusFrom, pollStep: pollStep, NO_ANSWER: NO_ANSWER, STATUS_LOST: STATUS_LOST, POLL_MS: POLL_MS, STALL_MS: STALL_MS, MIN_POLL_MS: MIN_POLL_MS, pollEvery: pollEvery, watchIdle: watchIdle, SESSION_ENDED: SESSION_ENDED,
              baselineAt: baselineAt, peakFill: peakFill, peakOutline: peakOutline, stateClass: stateClass,
              readout: readout, detectedOf: detectedOf, wholePct: wholePct, storedArea: storedArea, ionLine: ionLine, ionStatus: ionStatus, ionPreview: ionPreview, ionPreviewText: ionPreviewText, fitMixed: fitMixed, calibratorWarning: calibratorWarning, paneRows: paneRows, verdictCell: verdictCell, fitMethods: FIT_METHODS, fitSteps: fitSteps, fitStart: fitStart, smoothingList: smoothingList, smoothingStart: smoothingStart, smoothingNext: smoothingNext, needsSmoothingWarning: needsSmoothingWarning, smoothingWarning: smoothingWarning, smoothingDropsEdges: smoothingDropsEdges, smoothNote: smoothNote, labelKey: labelKey, paintStepper: paintStepper, smoothedLine: smoothedLine, scoreBadge: scoreBadge, fitMethodName: fitMethodName, fitMethodOf: fitMethodOf, peakLabel: peakLabel, detailsChoice: detailsChoice, cardBody: cardBody, followThumb: followThumb, flagChips: flagChips, longNotes: longNotes,
              integrationText: integrationText, signedChange: signedChange, pendingEdges: pendingEdges,
              refusedEdit: refusedEdit, neighbour: neighbour, pageStep: pageStep, edgeLevel: edgeLevel, classicBase: classicBase, adaptiveBase: adaptiveBase,
              previewPeak: previewPeak, apexPreview: apexPreview, snOf: snOf, snapIndex: snapIndex, dragTarget: dragTarget,
              editPayload: editPayload, thumbSvg: thumbSvg, thumbStatus: thumbStatus, filterThumbs: filterThumbs, orderThumbs: orderThumbs, filterButtonHtml: filterButtonHtml, filterLabel: filterLabel, filterMenuItems: filterMenuItems, filterRead: filterRead, FILTER_KEY: FILTER_KEY, moreBelow: moreBelow, scrollHost: scrollHost, hostView: hostView, sectionCounts: sectionCounts, sectionsOf: sectionsOf, sectionsHtml: sectionsHtml, displayedThumbs: displayedThumbs, stepFrom: stepFrom, jumpHtml: jumpHtml, injectionStatus: injectionStatus, listHtml: listHtml, worstStatus: worstStatus, chartView: chartView, areaChangePct: areaChangePct, editProblem: editProblem,
              commentProblem: commentProblem, edgeTolerance: edgeTolerance, judge: judge, pyFixed: pyFixed, pyG: pyG, shortError: shortError,
              banner: banner, failedRun: failedRun, processingBand: processingBand, ghostSectionsHtml: ghostSectionsHtml, busyKeysOf: busyKeysOf,
              thumbButton: thumbButton, lineStep: lineStep, PAGE_POLL_MS: PAGE_POLL_MS, openTarget: openTarget, withoutOpen: withoutOpen, postedEdit: postedEdit, dragIndex: dragIndex,
              typedEdge: typedEdge, edgeStep: edgeStep, injectionType: injectionType, deleteWarning: deleteWarning, confirmsDelete: confirmsDelete,
              allOffered: allOffered, allPayload: allPayload, autoLine: autoLine, autoArea: autoArea,
              knownState: knownState, listItem: listItem, apexTolerance: apexTolerance, nearestApex: nearestApex,
              matchCandidate: matchCandidate, shown: shown, labelIn: labelIn, BASELINES: BASELINES, peakNotes: peakNotes, shareOf: shareOf, outward: outward,
              walkReach: walkReach, readMargin: readMargin, readReach: readReach, halfWidths: halfWidths, counts: counts, sciCounts: sciCounts, axisCounts: axisCounts, niceTicks: niceTicks,
              levelsOutside: levelsOutside, edgeNotes: edgeNotes, HALF_WIDTH_SIGMA: HALF_WIDTH_SIGMA,
              DEFAULT_SEARCH_AMP_SN: DEFAULT_SEARCH_AMP_SN, DEFAULT_SEARCH_SLOPE: DEFAULT_SEARCH_SLOPE,
              DEFAULT_SEARCH_SMOOTH_PCT: DEFAULT_SEARCH_SMOOTH_PCT, autoWidthPoints: autoWidthPoints, handleDrag: handleDrag, pressKind: pressKind, nearestPress: nearestPress, partnerEdit: partnerEdit, sharesEdge: sharesEdge, signalAt: signalAt, onSignal: onSignal, edgeAt: edgeAt, dropSide: dropSide, SNAP_PX: SNAP_PX, GRAB_PX: GRAB_PX, postedLevels: postedLevels,
              rtSpan: rtSpan, rtDragTime: rtDragTime, rtHit: rtHit, rtPayload: rtPayload, rtSetText: rtSetText,
              rtRefusedText: rtRefusedText, rtLabel: rtLabel,
              menuEntries: menuEntries, fitProblem: fitProblem, expectedOf: expectedOf, expectedRtOf: expectedRtOf, fitPick: fitPick, fitAllPick: fitAllPick, fitPayload: fitPayload, fitReadout: fitReadout, defaultPick: defaultPick, apexClick: apexClick, fitAllWords: fitAllWords, fitCurve: fitCurve, fitFill: fitFill, fitResidual: fitResidual, fitComponentAt: fitComponentAt, fitPreview: fitPreview, fitText: fitText, above: above, keyMap: keyMap, EditStack: EditStack, KEYS_HELP: KEYS_HELP, stepTarget: stepTarget, chipItems: chipItems, addAt: addAt, splitAt: splitAt, geometryOf: geometryOf,
              zoomView: zoomView, panView: panView, spanY: spanY, regionView: regionView, peakView: peakView, fillToken: fillToken, easedView: easedView, traceToken: traceToken, valuesText: valuesText, countRange: countRange };
  if (typeof window !== "undefined") { window.PFAS = window.PFAS || {}; window.PFAS.rawData = api; }
  if (typeof module !== "undefined" && module.exports) { module.exports = api; }
})();
