/* raw_fit.js — the card's preview of a fit of overlapping peaks, made in the
 * browser before Apply so the analyst sees the fitted peaks, the interval
 * and the residual, and a fit the worker would refuse cannot be applied.
 * The worker's fit when the run is processed (pfas_pipeline.raw_integrate
 * fit_peaks) stays the value reported; this one repeats it: the same model
 * term for term (each peak a Gaussian, or an exponentially modified
 * Gaussian written with erfcx on its leading side and erfc on its trailing
 * side, summed on one straight baseline), the same starting values (each
 * peak at its click with the width the gaps allow, its area and the line
 * read by linear least squares; an EMG started with a short tail and with
 * one as long as its width, the closer fit kept), the same bounds, and the
 * same rules for a fit that collapsed. It is solved by Levenberg-Marquardt
 * within the bounds where the worker uses curve_fit; the area's SE is read,
 * as curve_fit reads it, from the pseudo-inverse of JᵀJ (its forward
 * differences, the worker's steps) scaled by the residual variance, and
 * gives the approximate interval, area ± 1.96 SE: the worker's own interval
 * is resampled and is never judged here.
 * tests/fixtures/fit_preview_cases.json holds this to the worker's fit.
 * Pure, no DOM; loaded before raw_data.js. Plain ES5. */
(function () {
  "use strict";
  /* the worker's bounds on each peak's width and tail (min), how near a
     bound a fitted parameter sits on it (a share of the bounds' span, or of
     the largest area), and the normal quantile of a 95 % interval */
  var SIGMA = [0.005, 0.2];
  var TAU = [0.002, 0.2];
  var ON_BOUND = 1e-6;
  var Z95 = 1.96;
  var EPS = 2.220446049250313e-16;
  var ROOT_EPS = Math.sqrt(EPS);
  var ROOT_2PI = Math.sqrt(2 * Math.PI);
  /* the steps a fit is given to settle, at most STEP_POINTS over the samples fitted, so a preview's
     cost (steps times samples) stays about the same on any span; what settled means: the cost falls
     by less than this share of itself, or no step lowers it. The most samples a preview fits:
     beyond them the card asks for narrower edges */
  var MAX_ITER = 200;
  var STEP_POINTS = 30000;
  var MOST_POINTS = 400;
  var FTOL = 1e-12;
  /* kept inside: a step that would cross a bound goes this share of the way to it, and a start on a
     bound is moved this far inside it (a share of the bound, at least 1), as the worker's solver keeps
     its steps strictly inside the bounds */
  var THETA = 0.995;
  var RSTEP = 1e-10;

  /* erfcx(z) = exp(z²) erfc(z) for z >= 0 (Numerical Recipes' Chebyshev fit, relative error under 1.2e-7) */
  function erfcx(z) {
    var u = 1 / (1 + 0.5 * z);
    return u * Math.exp(-1.26551223 + u * (1.00002368 + u * (0.37409196 + u * (0.09678418 + u * (-0.18628806 +
           u * (0.27886807 + u * (-1.13520398 + u * (1.48851587 + u * (-0.82215223 + u * 0.17087277)))))))));
  }
  /* one peak {area, mu, sigma, tau} at time x, above the baseline: a Gaussian, or an EMG written so it
     never overflows (erfcx where its argument is at or above zero, erfc below) */
  function componentAt(shape, c, x) {
    var u = (x - c.mu) / c.sigma;
    if (shape !== "emg") { return c.area / (c.sigma * ROOT_2PI) * Math.exp(-0.5 * u * u); }
    var z = (c.sigma / c.tau - u) / Math.SQRT2, v;
    if (z >= 0) { v = erfcx(z) * Math.exp(-0.5 * u * u); }
    else {
      v = (2 - Math.exp(-z * z) * erfcx(-z)) * Math.exp(Math.min(c.sigma * c.sigma / (2 * c.tau * c.tau) - (x - c.mu) / c.tau, 0));
    }
    return c.area / (2 * c.tau) * v;
  }

  /* ── the parameters: per peak area, mu, sigma (and tau), then the line's level and slope ── */
  function per(shape) { return shape === "emg" ? 4 : 3; }
  function peakOf(shape, p, j) {
    var n = per(shape), k = j * n;
    return { area: p[k], mu: p[k + 1], sigma: p[k + 2], tau: shape === "emg" ? p[k + 3] : null };
  }
  /* the model at the samples x: each peak on the line b0 + b1 (x - x[0]) */
  function model(shape, peaks, x, p) {
    var out = new Array(x.length), b0 = p[p.length - 2], b1 = p[p.length - 1], cs = [], i, j;
    for (j = 0; j < peaks; j++) { cs.push(peakOf(shape, p, j)); }
    for (i = 0; i < x.length; i++) {
      var v = b0 + b1 * (x[i] - x[0]);
      for (j = 0; j < peaks; j++) { v += componentAt(shape, cs[j], x[i]); }
      out[i] = v;
    }
    return out;
  }
  /* the Jacobian's columns by forward differences, as the worker steps: sqrt(eps) max(1, |p|), taken
     away from an upper bound it would cross */
  function jacobian(shape, peaks, x, p, f0, upper) {
    var cols = [];
    for (var i = 0; i < p.length; i++) {
      var h = ROOT_EPS * Math.max(1, Math.abs(p[i]));
      if (p[i] + h > upper[i]) { h = -h; }
      var q = p.slice();
      q[i] += h;
      var f = model(shape, peaks, x, q), col = new Array(x.length);
      for (var k = 0; k < x.length; k++) { col[k] = (f[k] - f0[k]) / h; }
      cols.push(col);
    }
    return cols;
  }
  function dot(a, b) { var s = 0; for (var i = 0; i < a.length; i++) { s += a[i] * b[i]; } return s; }
  function less(y, f) { var r = new Array(y.length); for (var i = 0; i < y.length; i++) { r[i] = y[i] - f[i]; } return r; }
  function clamp(v, lo, hi) { return v < lo ? lo : v > hi ? hi : v; }
  /* p moved by d, short of any bound it would cross (THETA of the way to it) */
  function inward(p, d, lo, hi) {
    var v = p + d;
    if (v < lo) { return p + THETA * (lo - p); }
    if (v > hi) { return p + THETA * (hi - p); }
    return v;
  }
  /* v inside its bounds: one on a bound moved RSTEP of the bound inside it */
  function inside(v, lo, hi) {
    v = clamp(v, lo, hi);
    if (v === lo && isFinite(lo)) { v = Math.min(lo + RSTEP * Math.max(1, Math.abs(lo)), (lo + hi) / 2); }
    if (v === hi && isFinite(hi)) { v = Math.max(hi - RSTEP * Math.max(1, Math.abs(hi)), (lo + hi) / 2); }
    return v;
  }

  /* the singular values and vectors of the matrix whose columns are `cols` (one-sided Jacobi):
     {s, u (the columns of U times s), v (the columns of V)} */
  function svd(cols) {
    var n = cols.length, u = cols.map(function (c) { return c.slice(); }), v = [], i, j, k;
    for (i = 0; i < n; i++) { v.push([]); for (j = 0; j < n; j++) { v[i].push(i === j ? 1 : 0); } }
    for (var sweep = 0; sweep < 80; sweep++) {
      var turned = false;
      for (i = 0; i < n - 1; i++) {
        for (j = i + 1; j < n; j++) {
          var a = dot(u[i], u[i]), b = dot(u[j], u[j]), g = dot(u[i], u[j]);
          if (g === 0 || Math.abs(g) <= EPS * Math.sqrt(a * b)) { continue; }
          turned = true;
          var zeta = (b - a) / (2 * g);
          var t = Math.abs(zeta) > 1e100 ? 1 / (2 * zeta) : (zeta >= 0 ? 1 : -1) / (Math.abs(zeta) + Math.sqrt(1 + zeta * zeta));
          var c = 1 / Math.sqrt(1 + t * t), s = c * t;
          rotate(u[i], u[j], c, s);
          rotate(v[i], v[j], c, s);
        }
      }
      if (!turned) { break; }
    }
    var sv = u.map(function (col) { return Math.sqrt(dot(col, col)); });
    return { s: sv, u: u, v: v };
    function rotate(p, q, c, s) {
      for (k = 0; k < p.length; k++) {
        var x = p[k], y = q[k];
        p[k] = c * x - s * y;
        q[k] = s * x + c * y;
      }
    }
  }
  /* the singular values numpy and curve_fit keep: above eps x the larger dimension x the largest */
  function kept(d, rows) {
    var top = Math.max.apply(null, d.s), cut = EPS * Math.max(rows, d.s.length) * top;
    return d.s.map(function (s) { return s > cut; });
  }
  /* least squares of y on the columns (numpy's lstsq, rcond=None) */
  function lstsq(cols, y) {
    var d = svd(cols), keep = kept(d, y.length), out = cols.map(function () { return 0; });
    for (var k = 0; k < cols.length; k++) {
      if (!keep[k]) { continue; }
      var w = dot(d.u[k], y) / (d.s[k] * d.s[k]);       /* u holds U times s */
      for (var i = 0; i < out.length; i++) { out[i] += w * d.v[k][i]; }
    }
    return out;
  }
  /* each parameter's variance: the diagonal of the pseudo-inverse of JᵀJ times the residual variance */
  function variances(cols, cost, rows) {
    var d = svd(cols), keep = kept(d, rows), n = cols.length, s2 = cost / (rows - n), out = [];
    for (var i = 0; i < n; i++) {
      var v = 0;
      for (var k = 0; k < n; k++) {
        if (keep[k]) { v += d.v[k][i] * d.v[k][i] / (d.s[k] * d.s[k]); }
      }
      out.push(v * s2);
    }
    return out;
  }
  /* (A + lambda diag A) d = g on the free parameters, by Cholesky; null when it is not positive */
  function damped(A, g, free, lambda) {
    var n = free.length, L = [], i, j, k;
    for (i = 0; i < n; i++) {
      L.push(new Array(n));
      for (j = 0; j <= i; j++) {
        var s = A[free[i]][free[j]];
        if (i === j) { s += lambda * Math.max(A[free[i]][free[i]], EPS); }
        for (k = 0; k < j; k++) { s -= L[i][k] * L[j][k]; }
        if (i === j) {
          if (!(s > 0)) { return null; }
          L[i][i] = Math.sqrt(s);
        } else {
          L[i][j] = s / L[j][j];
        }
      }
    }
    var z = new Array(n), d = new Array(n);
    for (i = 0; i < n; i++) {
      var zi = g[free[i]];
      for (k = 0; k < i; k++) { zi -= L[i][k] * z[k]; }
      z[i] = zi / L[i][i];
    }
    for (i = n - 1; i >= 0; i--) {
      var di = z[i];
      for (k = i + 1; k < n; k++) { di -= L[k][i] * d[k]; }
      d[i] = di / L[i][i];
    }
    return d;
  }
  /* Levenberg-Marquardt within the bounds, its steps either put back onto a bound they cross (a
     parameter on a bound whose gradient leads out of it held there) or, `kept`, stopped short of it
     (inward), from a start moved inside the bounds, so a parameter whose least is on a bound comes
     ever nearer it and the shared rule (collapsed) judges how near. {p, cost}, or null when it does
     not settle within `maxIter` steps or the cost cannot be computed */
  function solve(shape, peaks, x, y, p0, lower, upper, maxIter, kept) {
    var p = p0.map(function (v, i) { return kept ? inside(v, lower[i], upper[i]) : clamp(v, lower[i], upper[i]); });
    var f = model(shape, peaks, x, p), r = less(y, f), cost = dot(r, r), lambda = 1e-3;
    if (!isFinite(cost)) { return null; }
    for (var it = 0; it < maxIter; it++) {
      var J = jacobian(shape, peaks, x, p, f, upper), n = p.length, g = [], A = [], i, j;
      for (i = 0; i < n; i++) {
        g.push(dot(J[i], r));
        A.push([]);
        for (j = 0; j < n; j++) { A[i].push(j < i ? A[j][i] : dot(J[i], J[j])); }
      }
      var free = [];
      for (i = 0; i < n; i++) {
        if (!((p[i] <= lower[i] && g[i] < 0) || (p[i] >= upper[i] && g[i] > 0))) { free.push(i); }
      }
      if (!free.length) { return { p: p, cost: cost }; }
      for (;;) {
        var d = damped(A, g, free, lambda);
        if (d) {
          var q = p.slice();
          for (i = 0; i < free.length; i++) {
            var at = free[i];
            q[at] = kept ? inward(p[at], d[i], lower[at], upper[at]) : clamp(p[at] + d[i], lower[at], upper[at]);
          }
          var fq = model(shape, peaks, x, q), rq = less(y, fq), cq = dot(rq, rq);
          if (isFinite(cq) && cq < cost) {
            var fell = cost - cq;
            p = q; f = fq; r = rq; cost = cq;
            lambda = Math.max(lambda / 10, 1e-15);
            if (fell <= FTOL * cost) { return { p: p, cost: cost }; }
            break;
          }
        }
        lambda *= 10;
        if (lambda > 1e16) { return { p: p, cost: cost }; }      /* no step lowers it: at its least */
      }
    }
    return null;
  }

  /* the start with its areas and its line read by linear least squares, each peak's centre, width and
     tail held; an area that reads below zero starts at a thousandth of the largest (at least 1) */
  function linearAreas(shape, peaks, x, y, p0) {
    var n = per(shape), cols = [], j, i;
    for (j = 0; j < peaks; j++) {
      var c = peakOf(shape, p0, j);
      c.area = 1;
      cols.push(x.map(function (v) { return componentAt(shape, c, v); }));
    }
    cols.push(x.map(function () { return 1; }));
    cols.push(x.map(function (v) { return v - x[0]; }));
    var coef = lstsq(cols, y), out = p0.slice(), top = -Infinity;
    for (j = 0; j < peaks; j++) { top = Math.max(top, coef[j]); }
    var floor = Math.max(top, 1) * 1e-3;
    for (j = 0; j < peaks; j++) { out[j * n] = Math.max(coef[j], floor); }
    out[out.length - 2] = coef[peaks];
    out[out.length - 1] = coef[peaks + 1];
    for (i = 0; i < out.length; i++) { if (!isFinite(out[i])) { throw new Error("not computed"); } }
    return out;
  }
  function onBound(v, lo, hi, scale) {
    var tol = ON_BOUND * scale;
    return (isFinite(lo) && v - lo <= tol) || (isFinite(hi) && hi - v <= tol);
  }
  /* whether a fitted peak collapsed: its area at none, or its centre, width or tail on a bound of its
     own; a tail at its shortest is not (the EMG has become the Gaussian it tends to) */
  function collapsed(shape, p, lower, upper, peaks) {
    var n = per(shape), largest = 1, j, k;
    for (j = 0; j < peaks; j++) { largest = Math.max(largest, Math.abs(p[j * n])); }
    for (j = 0; j < peaks; j++) {
      for (k = 0; k < n; k++) {
        var i = j * n + k;
        if (k === 3 && upper[i] - p[i] > ON_BOUND * (upper[i] - lower[i])) { continue; }
        if (onBound(p[i], lower[i], upper[i], k === 0 ? largest : upper[i] - lower[i])) { return true; }
      }
    }
    return false;
  }
  /* a peak's apex and height above the baseline: a Gaussian's centre, an EMG's mode read on 4001
     points from mu - 3 sigma to mu + 3 sigma + 3 tau */
  function apexOf(shape, c) {
    if (shape !== "emg") { return [c.mu, c.area / (c.sigma * ROOT_2PI)]; }
    var a = c.mu - 3 * c.sigma, b = c.mu + 3 * c.sigma + 3 * c.tau, best = -Infinity, at = a;
    for (var i = 0; i <= 4000; i++) {
      var x = i === 4000 ? b : a + i * (b - a) / 4000, v = componentAt(shape, c, x);
      if (v > best) { best = v; at = x; }
    }
    return [at, best];
  }
  function nearest(t, x) {
    var best = 0;
    for (var i = 1; i < t.length; i++) { if (Math.abs(t[i] - x) < Math.abs(t[best] - x)) { best = i; } }
    return best;
  }
  function interp(x, xs, ys) {
    for (var i = 1; i < xs.length; i++) {
      if (x <= xs[i]) { return ys[i - 1] + (ys[i] - ys[i - 1]) * (x - xs[i - 1]) / (xs[i] - xs[i - 1]); }
    }
    return ys[ys.length - 1];
  }

  /* The fit of `opts.shape` ("gaussian" or "emg") at each of `opts.apexes`, summed on one straight
     line, over the samples nearest opts.start and opts.end, both included; judged as the worker
     judges it: by opts.limit, the largest multiple of the trace's baseline noise opts.noise the
     residual's RMS may be, and the reported peak opts.pick (an index among the apexes as given)
     against the detection floor opts.minSn. opts.fewest is the fewest samples the fit is made over.
     {components: [{area, se, mu, sigma, tau, apex, height}] in the order given, baseline [b0, b1,
     t0], span [t0, t1], ci_approx (the reported peak's approximate 95 % interval), residual_rms,
     noise_multiple, sn, refused}: refused is null, or {key, args} naming the worker's refusal
     (apart, few, not_computed, not_converged, collapsed, no_noise, residual [multiple, limit],
     floor [minSn]), or the preview's own: wide (more than MOST_POINTS samples). Before the fit is made a refusal comes with no components. */
  function fit(t, y, opts) {
    var shape = opts.shape === "emg" ? "emg" : "gaussian";
    var out = { shape: shape, components: [], baseline: null, span: null, ci_approx: null, residual_rms: null,
                noise_multiple: null, sn: null, refused: null };
    function refuse(key, args) { out.refused = { key: key, args: args || [] }; return out; }
    var s = nearest(t, opts.start), e = nearest(t, opts.end);
    var tt = t.slice(s, e + 1), yy = y.slice(s, e + 1);
    var clicks = (opts.apexes || []).map(Number);
    var order = clicks.map(function (v, i) { return i; }).sort(function (a, b) { return clicks[a] - clicks[b]; });
    var times = order.map(function (k) { return clicks[k]; }), peaks = times.length, i, j;
    for (i = 1; i < peaks; i++) { if (times[i] === times[i - 1]) { return refuse("apart"); } }
    if (!(tt.length && tt[0] < times[0] && times[peaks - 1] < tt[tt.length - 1])) { return refuse("apart"); }
    if (opts.fewest != null && tt.length < opts.fewest) { return refuse("few"); }
    if (tt.length > MOST_POINTS) { return refuse("wide"); }
    var maxIter = opts.maxIter || Math.min(MAX_ITER, Math.floor(STEP_POINTS / tt.length));
    for (i = 0; i < yy.length; i++) { if (!isFinite(yy[i])) { return refuse("not_computed"); } }
    var t0 = tt[0], t1 = tt[tt.length - 1], k = Math.min(3, Math.floor(tt.length / 2));
    var left = 0, right = 0;
    for (i = 0; i < k; i++) { left += yy[i] / k; right += yy[yy.length - k + i] / k; }
    var slope = (right - left) / (t1 - t0);
    var above = yy.map(function (v, n) { return v - (left + slope * (tt[n] - t0)); });
    var gaps = [], p0 = [], lower = [], upper = [];
    for (i = 1; i < peaks; i++) { gaps.push(times[i] - times[i - 1]); }
    /* one peak (the fits stepper's): its width is read from the span, edges lying about 3 sigma out, as the worker's alone fit does */
    if (peaks === 1) { gaps = [0.4 * (t1 - t0)]; }
    for (i = 0; i < peaks; i++) {
      var mu = times[i], below = i > 0 ? gaps[i - 1] : gaps[0], over = i < gaps.length ? gaps[i] : gaps[gaps.length - 1];
      var lo = Math.max(mu - below / 2, t0), hi = Math.min(mu + over / 2, t1);
      var sig = clamp(Math.min(below, over) / 2.5, SIGMA[0], SIGMA[1]);
      var h = Math.max(interp(mu, tt, above), 1), area = h * sig * ROOT_2PI;
      if (shape === "gaussian") {
        p0.push(area, mu, sig);
        lower.push(0, lo, SIGMA[0]);
        upper.push(Infinity, hi, SIGMA[1]);
      } else {
        p0.push(area, mu, sig, clamp(sig / 2, TAU[0], TAU[1]));
        lower.push(0, lo, SIGMA[0], TAU[0]);
        upper.push(Infinity, hi, SIGMA[1], TAU[1]);
      }
    }
    p0.push(left, slope);
    lower.push(-Infinity, -Infinity);
    upper.push(Infinity, Infinity);
    var n = per(shape), starts;
    try {
      starts = [linearAreas(shape, peaks, tt, yy, p0)];
      if (shape === "emg") {
        var longer = p0.slice();
        for (j = 0; j < peaks; j++) { longer[j * n + 3] = clamp(p0[j * n + 2], TAU[0], TAU[1]); }
        starts.push(linearAreas(shape, peaks, tt, yy, longer));
      }
    } catch (err) { return refuse("not_computed"); }
    /* each start is solved with its steps put onto the bounds and with them kept inside, and the
       least cost of all kept, as the worker solves each of its starts by steps that stop on the
       bounds and steps kept inside them (raw_integrate.FIT_SOLVERS) and keeps the closest: either
       rule alone can stop on a side least (a shoulder whose area reached nought, a shoulder that
       took the main peak's tail) */
    var best = null, runs = [];
    starts.forEach(function (start) { runs.push([start, false], [start, true]); });
    runs.forEach(function (run) {
      var got = solve(shape, peaks, tt, yy, run[0], lower, upper, maxIter, run[1]);
      if (!got) { return; }
      var f = model(shape, peaks, tt, got.p);
      var vars = variances(jacobian(shape, peaks, tt, got.p, f, upper), got.cost, tt.length);
      if (!vars.every(isFinite)) { return; }
      if (!best || got.cost < best.cost) { best = { p: got.p, cost: got.cost, vars: vars }; }
    });
    if (!best) { return refuse("not_converged"); }
    var p = best.p;
    if (collapsed(shape, p, lower, upper, peaks)) { return refuse("collapsed"); }
    var fitted = [];
    for (j = 0; j < peaks; j++) {
      var c = peakOf(shape, p, j), ah = apexOf(shape, c);
      c.se = Math.sqrt(Math.max(best.vars[j * n], 0));
      c.apex = ah[0];
      c.height = ah[1];
      fitted.push(c);
    }
    /* back in the order the apexes were given: the pick names one of them */
    var comps = new Array(peaks);
    order.forEach(function (k2, jj) { comps[k2] = fitted[jj]; });
    var rms = Math.sqrt(best.cost / tt.length), noise = opts.noise, pick = comps[opts.pick || 0] || comps[0];
    out.components = comps;
    out.baseline = [p[p.length - 2], p[p.length - 1], t0];
    out.span = [t0, t1];
    out.ci_approx = [pick.area - Z95 * pick.se, pick.area + Z95 * pick.se];
    out.residual_rms = rms;
    if (noise == null) { return refuse("no_noise"); }
    out.noise_multiple = noise > 0 ? rms / noise : (rms === 0 ? 0 : Infinity);
    if (!(out.noise_multiple <= opts.limit)) { return refuse("residual", [out.noise_multiple, opts.limit]); }
    out.sn = pick.height > 0 ? (noise > 0 ? pick.height / noise : Infinity) : 0;
    if (opts.minSn != null && !(out.sn >= opts.minSn)) { return refuse("floor", [opts.minSn]); }
    return out;
  }

  var api = { SIGMA: SIGMA, TAU: TAU, ON_BOUND: ON_BOUND, Z95: Z95, MOST_POINTS: MOST_POINTS, erfcx: erfcx, componentAt: componentAt,
              collapsed: collapsed, fit: fit };
  if (typeof window !== "undefined") { window.PFAS = window.PFAS || {}; window.PFAS.rawFit = api; }
  if (typeof module !== "undefined" && module.exports) { module.exports = api; }
})();
