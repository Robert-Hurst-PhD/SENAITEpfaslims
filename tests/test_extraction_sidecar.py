# -*- coding: utf-8 -*-
"""The run's extraction record comes from the SENAITE guided extraction
(DECISIONS 2026-10-02 DB1): the Run Builder writes it beside the uploaded CSV,
BEFORE the CSV, and the tablet service with its own reagent catalogue is gone."""
from __future__ import unicode_literals

import ast
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PKG = os.path.join(ROOT, "src", "senaite", "pfas")
sys.path.insert(0, PKG)

import extraction_sidecar as es  # noqa: E402

SESSION = {
    "method_id": "FDA_32PFAS", "analyst": "DEMO", "started_at": "2026-10-02T13:00:00Z",
    "finalized": True, "finalized_at": "2026-10-02T16:00:00Z", "finalized_by": "AN2",
    "stages": {
        "10": {"completed_at": "2026-10-02T15:00:00Z", "reagents": [
            {"role": "NH4OH", "name": "Ammonium hydroxide", "lot": "L10", "expiry": "2027-01-01"}]},
        "2": {"completed_at": "2026-10-02T14:00:00Z", "analyst": "AN3", "deviations": "Late spike",
              "reagents": [{"role": "Methanol", "name": "Methanol", "lot": " L2 ",
                            "inventory_uid": "u2", "cat_number": "M-1"},
                           {"role": "Water", "name": "Water", "lot": ""}]},
    },
}


def test_steps_follow_stage_order_numerically_with_names():
    r = es.build_sidecar(SESSION, {"2": "Spike", "10": "Elute"}, worksheet_id="WS-9",
                         senaite_batch_id="B-1", matrix="Egg", client_uid="c1")
    assert [s["step"] for s in r["steps"]] == ["Spike", "Elute"]      # 2 before 10
    assert r["steps"][0]["by"] == "AN3" and r["steps"][1]["by"] == "DEMO"
    assert r["steps"][0]["detail"] == "Late spike"
    assert (r["batch_id"], r["senaite_batch_id"], r["matrix"], r["method_id"], r["client_uid"]) \
        == ("WS-9", "B-1", "Egg", "FDA_32PFAS", "c1")


def test_only_filled_lots_are_recorded_with_inventory_link():
    r = es.build_sidecar(SESSION, {})
    assert [(s["lot_number"], s["step"]) for s in r["reagent_scans"]] == \
        [("L2", "Stage 2"), ("L10", "Stage 10")]
    assert r["reagent_scans"][0]["inventory_uid"] == "u2"
    assert r["reagent_scans"][0]["catalog_number"] == "M-1"


def test_signoff_and_completion_only_when_finalized():
    r = es.build_sidecar(SESSION, {})
    assert r["completed"] == "2026-10-02T16:00:00Z"
    assert r["signoffs"] == [{"role": "Analyst", "initials": "AN2", "at": "2026-10-02T16:00:00Z"}]
    open_sess = dict(SESSION, finalized=False)
    r2 = es.build_sidecar(open_sess, {})
    assert r2["completed"] is None and r2["signoffs"] == []


def test_progress():
    assert es.extraction_progress({}) is None
    assert es.extraction_progress({"stages": {}}) is None
    p = es.extraction_progress(dict(SESSION, finalized=False))
    assert p["started"] and p["completed"] is None and p["analyst"] == "DEMO"
    assert es.extraction_progress(SESSION)["completed"] == "2026-10-02T16:00:00Z"


def _src(*parts):
    with io.open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def test_run_builder_writes_the_record_before_the_csv():
    tree = ast.parse(_src("src", "senaite", "pfas", "browser", "run_builder.py").encode("utf-8"))
    fn = [n for n in ast.walk(tree)
          if isinstance(n, ast.FunctionDef) and n.name == "_handle_upload_export"][0]
    calls = [(n.lineno, n.func.attr) for n in ast.walk(fn)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr in ("_write_sidecar", "write")]
    sidecar = [ln for ln, a in calls if a == "_write_sidecar"]
    writes = [ln for ln, a in calls if a == "write"]
    assert sidecar and writes and min(sidecar) < min(writes), calls


def test_the_record_beside_the_csv_wins_in_the_watcher():
    src = _src("pfas_pipeline", "pipeline.py")
    body = src[src.index("candidates = [p.with_name("):]
    body = body[:body.index("for candidate in candidates")]
    assert "insert(" not in body, "a configured directory must not outrank the Run Builder's record"


def test_the_tablet_service_is_gone():
    assert "extraction-ui" not in _src("docker-compose.yml").split("# The extraction-ui")[0]
    assert "extraction_api" not in _src("Dockerfile.worker")
    for gone in (("extraction_api.py",), ("pfas_pipeline", "barcode.py"),
                 ("pfas_pipeline", "injection_builder.py")):
        assert not os.path.exists(os.path.join(ROOT, *gone)), gone
    assert "/data/extraction_logs" not in _src("src", "senaite", "pfas", "browser", "sample_status.py")


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
