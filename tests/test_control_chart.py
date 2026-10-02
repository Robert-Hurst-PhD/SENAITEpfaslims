# -*- coding: utf-8 -*-
"""Control charts: Levey-Jennings by default, Westgard rules as a view; a
warning can be dismissed and a point removed, each with a reason, both
undoable (DECISIONS 2026-10-02; docs/REUSE_REVIEW.md U7)."""
from __future__ import unicode_literals

import io
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PKG = os.path.join(ROOT, "src", "senaite", "pfas")
sys.path.insert(0, PKG)

import control_chart as cc      # noqa: E402

BASE = [100.0, 102.0, 98.0, 101.0, 99.0, 100.0, 103.0, 97.0, 100.0, 100.0]


def _pts(values):
    return [{"id": 10 + i, "value": v} for i, v in enumerate(values)]


def test_limits_from_the_baseline():
    lim = cc.limits(BASE)
    assert lim["mean"] == 100.0 and lim["n_baseline"] == 10
    assert abs(lim["sd"] - (28 / 9.0) ** 0.5) < 1e-4                       # sample SD
    assert abs(lim["ucl_3"] - (100 + 3 * (28 / 9.0) ** 0.5)) < 1e-3
    assert cc.limits(BASE[:4]) is None                                     # too few
    long = BASE * 3 + [500.0]
    assert cc.limits(long)["n_baseline"] == 20                             # first 20 only


def test_levey_jennings_warns_beyond_2_and_3_sd():
    lim = cc.limits(BASE)
    pts = _pts([100.0, 104.0, 106.0, 99.0])                                # +2.2 SD, +3.3 SD
    w = cc.lj_warnings(pts, lim)
    assert [(x["rule"], x["point_id"], x["severity"]) for x in w] == [
        ("2SD", 11, "warning"), ("3SD", 12, "reject")]
    assert w[0]["key"] == "11:2SD"


def test_westgard_checks_the_first_point_too():
    lim = cc.limits(BASE)
    w = cc.westgard(_pts([107.0, 100.0]), lim)
    assert any(x["rule"] == "1-3s" and x["indices"] == [0] for x in w), w


def test_westgard_multirule_set():
    lim = cc.limits(BASE)                                                   # sd ~1.76
    rules = set(x["rule"] for x in cc.westgard(_pts([104.0, 104.5]), lim))
    assert {"1-2s", "2-2s"} <= rules
    assert "R-4s" in set(x["rule"] for x in cc.westgard(_pts([104.0, 96.5]), lim))
    assert "4-1s" in set(x["rule"] for x in cc.westgard(_pts([102.0] * 4), lim))
    assert "10x" in set(x["rule"] for x in cc.westgard(_pts([100.5] * 10), lim))
    assert cc.westgard(_pts([100.0, 100.5, 99.5]), lim) == []


def test_a_dismissal_hides_only_that_rule_on_that_point():
    lim = cc.limits(BASE)
    w = cc.westgard(_pts([104.0, 104.5]), lim)                              # 1-2s x2, 2-2s
    left = cc.active(w, {"11:1-2s"})
    assert "11:1-2s" not in [x["key"] for x in left]
    assert "11:2-2s" in [x["key"] for x in left] and "10:1-2s" in [x["key"] for x in left]


def _store_module():
    import types
    names = ("senaite", "senaite.pfas", "senaite.pfas.qc", "senaite.pfas.qc.qc_types")
    saved = dict((k, sys.modules.get(k)) for k in names)
    mods = dict((k, types.ModuleType(str(k))) for k in names)
    mods["senaite.pfas"].__path__ = []
    mods["senaite.pfas.qc"].__path__ = []
    mods["senaite.pfas.qc.qc_types"].normalize_qc_type = lambda code: code
    mods["senaite.pfas"].qc = mods["senaite.pfas.qc"]
    mods["senaite.pfas.qc"].qc_types = mods["senaite.pfas.qc.qc_types"]
    sys.modules.update(mods)
    try:
        path = os.path.join(PKG, "qc", "store.py")
        if sys.version_info[0] >= 3:
            import importlib.util
            spec = importlib.util.spec_from_file_location("qc_store_under_test", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
        import imp
        return imp.load_source(str("qc_store_under_test"), path)
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def test_the_store_records_with_a_reason_and_undoes():
    store_mod = _store_module()
    tmp = tempfile.mkdtemp()
    try:
        st = store_mod.QCResultStore(os.path.join(tmp, "qc.db"))
        st.register_batch("B-1", "2026-10-01")
        with st._connect() as conn:
            for rid, analyte in ((5, "PFOA"), (6, "PFOS")):
                conn.execute("INSERT INTO qc_results (id, batch_id, run_date, analyte, qc_type, "
                             "created_at) VALUES (?, 'B-1', '2026-10-01', ?, 'LCS', 'now')",
                             (rid, analyte))
        try:
            st.annotate(99, "dismissed", "no such result", "demo", rule="2SD")
            assert False, "annotated a result that does not exist"
        except Exception as exc:                      # sqlite3.IntegrityError
            assert "FOREIGN KEY" in str(exc)
        try:
            st.annotate(5, "dismissed", "  ", "demo", rule="2SD")
            assert False, "dismissed without a reason"
        except ValueError:
            pass
        st.annotate(5, "dismissed", "known spike", "demo", rule="2SD")
        st.annotate(5, "excluded", "bad injection", "demo", rule="ignored")
        notes = sorted((n["action"], n["rule"], n["reason"], n["by_user"])
                       for n in st.get_annotations([5, 6]))
        assert notes == [("dismissed", "2SD", "known spike", "demo"),
                         ("excluded", "", "bad injection", "demo")]
        st.unannotate(5, "dismissed", rule="2SD")
        assert [n["action"] for n in st.get_annotations([5])] == ["excluded"]
        st.unannotate(5, "excluded", rule="stray")              # a removal has no rule
        assert st.get_annotations([5]) == []
        try:
            st.annotate(5, "deleted", "x", "demo")
            assert False, "unknown action accepted"
        except ValueError:
            pass
    finally:
        shutil.rmtree(tmp)


def test_the_view_removes_points_before_limits_and_offers_both_views():
    with io.open(os.path.join(PKG, "browser", "controlchart.py"), encoding="utf-8") as fh:
        src = fh.read()
    body = src[src.index("removed = [dict(p, note="):]
    assert body.index("points = [p for p in points if p[\"id\"] not in excluded]") < body.index(
        "cc.limits(")
    assert "cc.westgard if view_mode == \"westgard\" else cc.lj_warnings" in src
    assert "def _westgard" not in src and "def _compute_limits" not in src
    with io.open(os.path.join(PKG, "browser", "templates", "controlchart.pt"), encoding="utf-8") as fh:
        tpl = fh.read()
    for v in ('value="dismiss"', 'value="remove"', 'value="undismiss"', 'value="restore"',
              'name="view_mode"', 'name="reason" required="required"'):
        assert v in tpl, v


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
