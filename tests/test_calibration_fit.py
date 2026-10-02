# -*- coding: utf-8 -*-
"""Calibration curve maths on the Calibrations page (docs/REUSE_REVIEW.md U2;
DECISIONS 2026-10-02): static/calibration_fit.js, least squares by the
vendored ml-matrix QR, checked against numpy on the FDA and EPA 1633A
ladders. Fit, weighting (none, 1/x, 1/x²) and origin (exclude, include,
force) are each honoured; R² follows the chosen weighting; the inverse gives
back each calibrator's concentration. Needs Node and numpy; skipped without."""
from __future__ import print_function, unicode_literals

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STATIC = os.path.join(ROOT, "src", "senaite", "pfas", "browser", "static")
TPL = os.path.join(ROOT, "src", "senaite", "pfas", "browser", "templates", "calibrations.pt")


def _node():
    for cand in (shutil.which("node") if hasattr(shutil, "which") else None,
                 os.path.expanduser("~/.local/node/bin/node")):
        if cand and os.path.exists(cand):
            return cand
    return None


def _cases():
    import numpy as np
    rng = np.random.default_rng(7)
    ladders = {"fda": [20.0 / 512 * 2 ** i for i in range(10)],
               "1633a": [0.2 * 2 ** i for i in range(9)]}
    out = []
    for name, xs in sorted(ladders.items()):
        x = np.array(xs)
        for curv in (0.0, -0.004):
            for noise in (0.0, 0.03):
                y = (0.05 + 1.3 * x + curv * x * x) * (1 + noise * rng.standard_normal(len(x)))
                pts = [{"x": float(a), "y": float(b)} for a, b in zip(x, y)]
                for weight in ("", "1/x", "1/x2"):
                    for typ, origin, cols in (("Linear", "exclude", [0, 1]),
                                              ("Quadratic", "exclude", [0, 1, 2]),
                                              ("Linear", "force", [1]),
                                              ("Quadratic", "force", [1, 2]),
                                              ("Linear", "include", [0, 1]),
                                              ("Quadratic", "include", [0, 1, 2])):
                        # 'include' adds the point (0, 0), weighted 1
                        xx = np.concatenate([[0.0], x]) if origin == "include" else x
                        yy = np.concatenate([[0.0], y]) if origin == "include" else y
                        w = {"": np.ones_like(xx), "1/x": np.where(xx > 0, 1 / np.where(xx > 0, xx, 1), 1),
                             "1/x2": np.where(xx > 0, 1 / np.where(xx > 0, xx, 1) ** 2, 1)}[weight]
                        yb = np.sum(w * yy) / np.sum(w)
                        X = np.column_stack([xx ** k for k in cols]) * np.sqrt(w)[:, None]
                        b = np.linalg.lstsq(X, yy * np.sqrt(w), rcond=None)[0]
                        coef = [0.0, 0.0, 0.0]
                        for k, v in zip(cols, b):
                            coef[k] = float(v)
                        f = coef[0] + coef[1] * xx + coef[2] * xx * xx
                        r2 = 1 - np.sum(w * (yy - f) ** 2) / np.sum(w * (yy - yb) ** 2)
                        out.append({"tag": "%s c%s n%s %s %s %s" % (name, curv, noise, typ,
                                                                    weight or "none", origin),
                                    "pts": pts, "type": typ, "weight": weight, "origin": origin,
                                    "coef": coef, "r2": float(r2)})
    return out


RUNNER = r"""
const C = require(process.argv[2]);
const cases = require(process.argv[3]);
const out = cases.map(c => {
  const m = C.fit(c.pts, {type: c.type, weight: c.weight, origin: c.origin});
  return {coef: [m.coef.c0, m.coef.c1, m.coef.c2], r2: C.r2(c.pts, m),
          f: c.pts.map(p => m.f(p.x)), inv: c.pts.map(p => m.inverse(m.f(p.x)))};
});
console.log(JSON.stringify(out));
"""


def test_matches_numpy_for_every_fit_weight_and_origin():
    node = _node()
    try:
        import numpy  # noqa: F401
    except ImportError:
        node = None
    if not node:
        print("  (skipped: needs node and numpy)")
        return
    cases = _cases()
    tmp = tempfile.mkdtemp()
    try:
        cpath, rpath = os.path.join(tmp, "cases.json"), os.path.join(tmp, "run.js")
        with io.open(cpath, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(cases))
        with io.open(rpath, "w", encoding="utf-8") as fh:
            fh.write(RUNNER)
        res = json.loads(subprocess.check_output(
            [node, rpath, os.path.join(STATIC, "calibration_fit.js"), cpath]).decode("utf-8"))
    finally:
        shutil.rmtree(tmp)
    assert len(res) == len(cases) == 144
    for c, r in zip(cases, res):
        for p, got in zip(c["pts"], r["f"]):
            want = c["coef"][0] + c["coef"][1] * p["x"] + c["coef"][2] * p["x"] ** 2
            assert abs(got - want) <= 1e-9 * abs(want), (c["tag"], got, want)
        assert abs(r["r2"] - c["r2"]) < 1e-10, (c["tag"], r["r2"], c["r2"])
        for p, x in zip(c["pts"], r["inv"]):
            assert x is not None and abs(x - p["x"]) <= 1e-9 * p["x"], (c["tag"], x, p["x"])
        if c["origin"] == "force":
            assert r["coef"][0] == 0, c["tag"]


def test_the_page_uses_it_and_lost_its_own_solver():
    with io.open(TPL, encoding="utf-8") as fh:
        tpl = fh.read()
    assert "++resource++senaite.pfas/vendor/ml-matrix-6.12.1.umd.js" in tpl
    assert "++resource++senaite.pfas/calibration_fit.js" in tpl
    assert tpl.index("ml-matrix-6.12.1.umd.js") < tpl.index("calibration_fit.js")
    for gone in ("function fitLinear", "function fitQuad", "backCalcBisect", "function wt("):
        assert gone not in tpl, gone
    assert os.path.exists(os.path.join(STATIC, "vendor", "ml-matrix-LICENSE.txt"))


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print("PASS", name)
        except AssertionError as exc:
            failed += 1
            print("FAIL", name, exc)
    print("{0}/{1} passed".format(len(tests) - failed, len(tests)))
    sys.exit(1 if failed else 0)
