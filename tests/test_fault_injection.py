"""Known-answer testing: every injected deviation must be caught, and nothing else.

The QC engine had only ever been exercised against one real export
(FDA_32PFAS × Animal Feed) whose failures happen to be the ones it contains.
That proves the checks run; it proves nothing about whether they DETECT.

`tools/generate_synthetic_runs.py` builds a run per method × matrix and writes a
manifest naming the deviations injected into it. These tests assert the flags
raised match that manifest — which catches both directions:

  * a MISS   — an injected deviation the system did not notice
  * a FALSE POSITIVE — a flag on a run with nothing wrong with it

A pass/fail check can only ever catch the first.

Two findings came out of building this, both worth keeping in mind when reading
a failure here:

  * the first version drew a random retention time per ROW, so every injection
    disagreed with itself and manufactured ~475 RT flags per run. A fixture that
    produces its own false positives cannot prove their absence.
  * it emitted SENAITE keywords ("M2-4:2FTS") where an instrument emits display
    names ("13C2,D4-4:2FTS"). Zero overlap with the engine's IS list, so an
    injected surrogate failure raised nothing and looked like a detection gap in
    the system rather than a bug in the fixture.
"""
import datetime
import glob
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("PFAS_ALLOW_LEGACY_VENDOR_MAP", "1")
os.environ.setdefault(
    "PFAS_QC_DB", os.path.join(tempfile.gettempdir(), "pfas_fault_qc.db"))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GENERATOR = os.path.join(ROOT, "tools", "generate_synthetic_runs.py")

#: injected deviation -> the check identity that must fire.
#: None means the deviation is recorded as a failing QC RESULT rather than a
#: flag — the blank contamination check writes a verdict, not a QCFlag.
EXPECTED_KIND = {
    "ccv_recovery_high":  "ccv",
    "calibration_r2_low": "calibration",
    "surrogate_low":      "is_response",
    "lfsm_low":           "lfsm",
    "lfsmd_rpd_high":     "lfsmd",
    "ion_ratio_out":      "ion_ratio",
    "sn_low":             "sn",
    "blank_contaminated": None,
}

_CACHE = {}


def _generate(deviations, method="FDA_32PFAS", matrix="Animal Feed"):
    key = (deviations, method, matrix)
    if key in _CACHE:
        return _CACHE[key]
    out = tempfile.mkdtemp(prefix="pfas_fault_")
    proc = subprocess.run(
        [sys.executable, GENERATOR, "--out", out, "--method", method,
         "--matrix", matrix, "--deviations", deviations],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-800:]
    files = glob.glob(os.path.join(out, "*.csv"))
    assert files, "generator wrote nothing for %s" % (key,)
    _CACHE[key] = files[0]
    return files[0]


def _evaluate(csv_path):
    """Run a synthetic export through import, corrections, QC and summary."""
    from pfas_pipeline.importer import load_instrument_csv, classify_injection
    from pfas_pipeline.injection_builder import REVIEW_CHECKS
    from pfas_pipeline.models import Batch
    from pfas_pipeline.run_queue import RunQueue
    from pfas_pipeline import pipeline, qc_store

    manifest = json.load(open(csv_path.replace(".csv", "_manifest.json")))
    sidecar = json.load(open(csv_path.replace(".csv", "_extraction.json")))
    rows = pipeline.apply_extract_corrections(
        load_instrument_csv(csv_path), manifest["method_id"], manifest["matrix"])
    batch = Batch(batch_id=manifest["batch_id"], injections=rows, analyst="s",
                  date=datetime.date.today(), matrix=manifest["matrix"],
                  method_id=manifest["method_id"],
                  instrument_file=os.path.basename(csv_path))
    batch.spikes = sidecar.get("_spikes") or {}
    plan = [{"injection_name": n,
             "qc_type": classify_injection(n, {}),
             "checks": REVIEW_CHECKS.get(classify_injection(n, {}),
                                         REVIEW_CHECKS["Sample"])}
            for n in sorted({r.injection_name for r in rows})]
    RunQueue(batch, plan, method_id=manifest["method_id"]).auto_evaluate()
    pipeline.build_summary(batch)
    failing_blanks = [r for r in qc_store._qc_rows(batch)
                      if r["qc_type"] in ("MB", "MxB", "LRB", "CCB")
                      and not r["passed"]]
    kinds = Counter(getattr(f, "check_kind", "") for f in batch.qc_flags)
    return manifest, batch, kinds, failing_blanks


def test_a_clean_run_raises_nothing():
    """The false-positive baseline. Without this the detection tests mean
    nothing — anything can 'detect' a fault if it flags everything."""
    manifest, batch, kinds, blanks = _evaluate(_generate("clean"))
    assert not batch.qc_flags, "clean run raised %d flag(s): %s" % (
        len(batch.qc_flags), dict(kinds))
    assert not blanks, "clean run failed %d blank result(s)" % len(blanks)
    assert manifest["injected"] == [], manifest["injected"]


def test_every_deviation_is_detected():
    for deviation, want in sorted(EXPECTED_KIND.items()):
        _manifest, batch, kinds, blanks = _evaluate(_generate(deviation))
        if want is None:
            assert blanks, (
                "%s produced no failing blank result — a contaminated blank "
                "must be judged" % deviation)
        else:
            assert kinds.get(want), (
                "%s was NOT detected: expected a %r flag, got %s"
                % (deviation, want, dict(kinds) or "no flags at all"))


def test_detection_is_specific():
    """A deviation must not light up unrelated checks.

    `lfsm_low` legitimately raises `lfsmd` too: a spike recovered at 35% makes
    the spike/duplicate RPD large, which is real chemistry rather than noise.
    """
    allowed = {
        "ccv_recovery_high":  {"ccv"},
        "calibration_r2_low": {"calibration"},
        "surrogate_low":      {"is_response"},
        "lfsm_low":           {"lfsm", "lfsmd"},
        "lfsmd_rpd_high":     {"lfsmd"},
        "ion_ratio_out":      {"ion_ratio"},
        "sn_low":             {"sn"},
        "blank_contaminated": set(),
    }
    for deviation, permitted in sorted(allowed.items()):
        _m, _b, kinds, _blanks = _evaluate(_generate(deviation))
        unexpected = {k for k in kinds if k and k not in permitted}
        assert not unexpected, (
            "%s also raised %s — unrelated checks fired"
            % (deviation, sorted(unexpected)))


def test_the_manifest_names_the_affected_analytes():
    """Scope matters: a qualification that names the wrong analytes, or all of
    them, is not usable on a certificate."""
    manifest, _b, _k, _blanks = _evaluate(_generate("surrogate_low"))
    entries = [e for e in manifest["expected"]
               if e["deviation"] == "surrogate_low"]
    assert entries, manifest["expected"]
    assert entries[0]["analytes"], "no affected analytes recorded"
    assert entries[0]["disposition"] == "qualify"


def test_every_method_and_matrix_imports():
    """EPA 537.1 and EPA 1633A had never processed a run before this."""
    out = tempfile.mkdtemp(prefix="pfas_fault_all_")
    proc = subprocess.run(
        [sys.executable, GENERATOR, "--out", out, "--deviations", "clean"],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-800:]
    files = sorted(glob.glob(os.path.join(out, "*.csv")))
    assert len(files) >= 18, "expected 18 method x matrix runs, got %d" % len(files)
    methods = set()
    for path in files:
        manifest, batch, kinds, blanks = _evaluate(path)
        methods.add(manifest["method_id"])
        assert batch.summary, "%s produced no summary rows" % os.path.basename(path)
        assert not batch.qc_flags, "%s raised %s on clean data" % (
            os.path.basename(path), dict(kinds))
    assert methods == {"FDA_32PFAS", "EPA_537_1", "EPA_1633A"}, methods


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
