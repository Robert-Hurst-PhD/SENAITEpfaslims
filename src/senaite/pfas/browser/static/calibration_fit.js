/* Calibration curve fitting for the Calibrations page.

   Least squares by ml-matrix's QR decomposition (MIT) instead of hand-written
   normal equations and Cramer's rule; the concentration read back off a curve
   by the closed-form inverse instead of bisection; R² computed with the SAME
   weights as the fit (none = the plain R²; 1/x and 1/x² = the weighted R² the
   instrument software reports for a weighted curve). The worker fits and
   reads every curve the same way (senaite.pfas quant_fit).

     fit(points, {type: 'Linear'|'Quadratic'|'Average RF',
                  weight: ''|'1/x'|'1/x2',
                  origin: 'exclude'|'include'|'force'})
       -> {f(x), inverse(y), coef: {c0, c1, c2}, type, weight, origin}  or null
     refusal(points, opts) -> 'turns' for a quadratic refused, else null
     r2(points, model)  -> number or null
     sampleReading(model, y, bottom, top) -> {x, place}

   Origin, for a line and a quadratic alike: 'exclude' fits a constant term;
   'force' fits none, adds no point and keeps the calibrators' weights;
   'include' adds the point (0, 0) weighted as the lowest calibrator, so the
   curve does not change with the concentration unit. An Average RF passes
   through the origin by definition: its origin is 'force' whatever is
   asked, unweighted, its R² that of the line through the origin with every
   weight 1. A quadratic must rise across its calibration range, from its
   lowest calibrator to its highest; one that turns within it is not drawn.
   Loaded in the browser after static/vendor/ml-matrix-6.12.1.umd.js (global
   mlMatrix; MIT, licence beside it) and in Node tests from the same file. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory(require(require('path').join(
      __dirname, 'vendor', 'ml-matrix-6.12.1.umd.js')));
  } else {
    root.PFASCalFit = factory(root.mlMatrix);
  }
}(typeof self !== 'undefined' ? self : this, function (ml) {
  'use strict';

  function weightOf(x, weight) {
    if (weight === '1/x') return x > 0 ? 1 / x : 1;
    if (weight === '1/x2') return x > 0 ? 1 / (x * x) : 1;
    return 1;
  }

  function kindOf(type) {
    var t = String(type || 'Linear').toLowerCase().replace(/[\s_]/g, '');
    if (t === 'quadratic') return 'quadratic';
    if (t === 'averagerf' || t === 'avgrf') return 'avgrf';
    return 'linear';
  }

  /* the calibrators, each with its weight; under 'include' the origin
     first, weighted as the lowest calibrator */
  function points(pts, origin, weight) {
    var out = (pts || []).filter(function (p) {
      return p && isFinite(p.x) && isFinite(p.y);
    }).map(function (p) { return {x: p.x, y: p.y, w: weightOf(p.x, weight)}; });
    if (origin === 'include' && out.length) {
      var low = Math.min.apply(null, out.map(function (p) { return p.x; }));
      out = [{x: 0, y: 0, w: weightOf(low, weight)}].concat(out);
    }
    return out;
  }

  /* Weighted least squares: minimise sum w (y - X b)^2 via QR of sqrt(w) X. */
  function wls(pts, powers) {
    var rows = [], rhs = [];
    pts.forEach(function (p) {
      var s = Math.sqrt(p.w);
      rows.push(powers.map(function (k) { return s * Math.pow(p.x, k); }));
      rhs.push([s * p.y]);
    });
    var qr = new ml.QrDecomposition(new ml.Matrix(rows));
    if (!qr.isFullRank()) return null;
    var b = qr.solve(new ml.Matrix(rhs)).getColumn(0);
    var coef = {c0: 0, c1: 0, c2: 0};
    powers.forEach(function (k, i) { coef['c' + k] = b[i]; });
    return coef;
  }

  function model(coef, kind, opts) {
    var f = function (x) { return coef.c0 + coef.c1 * x + coef.c2 * x * x; };
    var inverse = function (y) {
      if (coef.c2 === 0) {
        return coef.c1 !== 0 ? (y - coef.c0) / coef.c1 : null;
      }
      /* c2 x² + c1 x + (c0 - y) = 0: the root on the rising branch of the
         curve, by the cancellation-free form (a near-zero c2 loses all
         precision in the textbook formula) */
      var a = coef.c2, b = coef.c1, c = coef.c0 - y;
      var disc = b * b - 4 * a * c;
      if (disc < 0) return null;
      var q = -0.5 * (b + (b >= 0 ? 1 : -1) * Math.sqrt(disc));
      var roots = [q / a];
      if (q !== 0) roots.push(c / q);
      var ok = roots.filter(function (x) {
        return x >= 0 && coef.c1 + 2 * coef.c2 * x > 0;
      });
      return ok.length ? Math.min.apply(null, ok) : null;
    };
    /* an Average RF is a line through the origin, unweighted */
    var avg = kind === 'avgrf';
    return {f: f, inverse: inverse, coef: coef, type: kind,
            weight: avg ? '' : (opts.weight || ''), origin: avg ? 'force' : (opts.origin || 'exclude')};
  }

  /* the slope c1 + 2·c2·x above zero at the lowest and the highest
     calibrator, and so everywhere between */
  function risesAcross(coef, low, high) {
    return coef.c1 + 2 * coef.c2 * low > 0 && coef.c1 + 2 * coef.c2 * high > 0;
  }

  /* {m: the fit, why: 'turns' for a quadratic refused}; both null when
     nothing can be fitted */
  function fitWhy(pts, opts) {
    opts = opts || {};
    var kind = kindOf(opts.type), origin = kind === 'avgrf' ? 'force' : (opts.origin || 'exclude');
    var p = points(pts, origin, kind === 'avgrf' ? '' : opts.weight);
    if (!p.length) return {m: null, why: null};
    var coef;
    if (kind === 'avgrf') {
      var rfs = p.filter(function (q) { return q.x > 0; })
                 .map(function (q) { return q.y / q.x; });
      if (!rfs.length) return {m: null, why: null};
      coef = {c0: 0, c1: rfs.reduce(function (a, b) { return a + b; }, 0) / rfs.length, c2: 0};
    } else {
      var force = origin === 'force';
      var powers = kind === 'quadratic' ? (force ? [1, 2] : [0, 1, 2]) : (force ? [1] : [0, 1]);
      if (p.length < powers.length) {
        if (kind === 'quadratic') return fitWhy(pts, {type: 'Linear', weight: opts.weight, origin: origin});
        return {m: null, why: null};
      }
      coef = wls(p, powers);
      if (!coef) return {m: null, why: null};
      if (kind === 'quadratic') {
        var xs = p.filter(function (q) { return q.x > 0; }).map(function (q) { return q.x; });
        if (!risesAcross(coef, Math.min.apply(null, xs), Math.max.apply(null, xs))) {
          return {m: null, why: 'turns'};
        }
      }
    }
    return {m: model(coef, kind, opts), why: null};
  }

  function fit(pts, opts) { return fitWhy(pts, opts).m; }
  function refusal(pts, opts) { return fitWhy(pts, opts).why; }

  /* R² with the fit's own weights; an Average RF's with every weight 1 and
     no added point. */
  function r2(pts, m) {
    if (!m) return null;
    var p = points(pts, m.origin, m.weight);
    if (p.length < 2) return null;
    var w = p.map(function (q) { return q.w; });
    var sw = w.reduce(function (a, b) { return a + b; }, 0);
    var ybar = p.reduce(function (a, q, i) { return a + w[i] * q.y; }, 0) / sw;
    var ssTot = 0, ssRes = 0;
    p.forEach(function (q, i) {
      ssTot += w[i] * (q.y - ybar) * (q.y - ybar);
      ssRes += w[i] * (q.y - m.f(q.x)) * (q.y - m.f(q.x));
    });
    return ssTot > 0 ? 1 - ssRes / ssTot : 1;
  }

  /* A calibrator read against the fit: x (expected), y (its response
     ratio), the fit at x, the concentration read back off the fit from y, and
     that value's deviation from x against the window (±limit %, null = not
     judged). */
  function readout(m, p, limit) {
    var fy = m ? m.f(p.x) : null, back = m ? m.inverse(p.y) : null;
    var dev = (back != null && p.x) ? (back - p.x) / p.x * 100 : null;
    return {x: p.x, y: p.y, fit_y: fy, back: back, dev: dev,
            within: (limit == null || dev == null) ? null : Math.abs(dev) <= limit};
  }
  /* "Open the calculation": every point read the same way, and the R². */
  function calculation(pts, m) {
    return {points: (pts || []).map(function (p) { return readout(m, p, null); }), r2: r2(pts, m)};
  }

  /* A native's reading in a sample. place 'above' for a ratio above the
     curve's response at the highest calibrator (the reading kept where the
     curve reaches it), 'below' for a quadratic's ratio below its response
     at the lowest: the reading on the curve between zero and that
     calibrator, on the rising branch (null where there is none), a number
     the worker keeps only at or above the MDL; a straight line reads as
     inverse() does. */
  function sampleReading(m, y, bottom, top) {
    if (!m || y == null) return {x: null, place: null};
    if (m.coef.c2 !== 0 && bottom != null && y < m.f(bottom)) return {x: m.inverse(y), place: 'below'};
    var atTop = top != null ? m.f(top) : null;
    return {x: m.inverse(y), place: (atTop != null && y > atTop + 1e-9 * Math.abs(atTop)) ? 'above' : null};
  }

  return {fit: fit, refusal: refusal, r2: r2, weightOf: weightOf, readout: readout,
          calculation: calculation, sampleReading: sampleReading};
}));
