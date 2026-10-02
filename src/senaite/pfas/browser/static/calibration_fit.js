/* Calibration curve fitting for the Calibrations page (docs/REUSE_REVIEW.md U2;
   DECISIONS 2026-10-02).

   Least squares by ml-matrix's QR decomposition (MIT) instead of hand-written
   normal equations and Cramer's rule; the concentration read back off a curve
   by the closed-form inverse instead of bisection; R² computed with the SAME
   weights as the fit (none = the plain R²; 1/x and 1/x² = the weighted R² the
   instrument software reports for a weighted curve).

     fit(points, {type: 'Linear'|'Quadratic'|'Average RF',
                  weight: ''|'1/x'|'1/x2',
                  origin: 'exclude'|'include'|'force'})
       -> {f(x), inverse(y), coef: {c0, c1, c2}, type, weight, origin}  or null
     r2(points, model)  -> number or null

   'include' adds the point (0, 0); 'force' fits with no intercept.
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

  function points(pts, origin) {
    var out = (pts || []).filter(function (p) {
      return p && isFinite(p.x) && isFinite(p.y);
    });
    if (origin === 'include') out = [{x: 0, y: 0}].concat(out);
    return out;
  }

  /* Weighted least squares: minimise sum w (y - X b)^2 via QR of sqrt(w) X. */
  function wls(pts, weight, powers) {
    var rows = [], rhs = [];
    pts.forEach(function (p) {
      var s = Math.sqrt(weightOf(p.x, weight));
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
    return {f: f, inverse: inverse, coef: coef, type: kind,
            weight: opts.weight || '', origin: opts.origin || 'exclude'};
  }

  function fit(pts, opts) {
    opts = opts || {};
    var kind = kindOf(opts.type), origin = opts.origin || 'exclude';
    var p = points(pts, origin);
    if (!p.length) return null;
    var coef;
    if (kind === 'avgrf') {
      var rfs = p.filter(function (q) { return q.x > 0; })
                 .map(function (q) { return q.y / q.x; });
      if (!rfs.length) return null;
      coef = {c0: 0, c1: rfs.reduce(function (a, b) { return a + b; }, 0) / rfs.length, c2: 0};
    } else {
      var force = origin === 'force';
      var powers = kind === 'quadratic' ? (force ? [1, 2] : [0, 1, 2]) : (force ? [1] : [0, 1]);
      if (p.length < powers.length) {
        if (kind === 'quadratic') return fit(pts, {type: 'Linear', weight: opts.weight, origin: origin});
        return null;
      }
      coef = wls(p, opts.weight || '', powers);
      if (!coef) return null;
    }
    return model(coef, kind, opts);
  }

  /* R² with the fit's own weights. */
  function r2(pts, m) {
    if (!m) return null;
    var p = points(pts, m.origin);
    if (p.length < 2) return null;
    var w = p.map(function (q) { return weightOf(q.x, m.weight); });
    var sw = w.reduce(function (a, b) { return a + b; }, 0);
    var ybar = p.reduce(function (a, q, i) { return a + w[i] * q.y; }, 0) / sw;
    var ssTot = 0, ssRes = 0;
    p.forEach(function (q, i) {
      ssTot += w[i] * (q.y - ybar) * (q.y - ybar);
      ssRes += w[i] * (q.y - m.f(q.x)) * (q.y - m.f(q.x));
    });
    return ssTot > 0 ? 1 - ssRes / ssTot : 1;
  }

  return {fit: fit, r2: r2, weightOf: weightOf};
}));
