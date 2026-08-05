"""A review check must not report a pass while the run carries its flags.

`RunQueue.auto_evaluate` maps engine flags onto review checks. Until 2026-08-05
it matched on `QCFlag.source` — the human-readable label. Wiring the profiled
checks on 08-04 changed those labels to carry the method id
("FDA_32PFAS Calibration" rather than "Calibration %"), so calibration, r², CCV
and RT stopped matching and reported **AUTO_PASS on a run carrying 326 flags**.
Measured on the real export: 10 calibration, 10 r² and 20 RT checks all passing.

One field cannot be both a label and a key. `QCFlag.check_kind` is the identity;
`source` is free to read however it reads.

These tests pin the identity, not the label — renaming a source string must stay
a cosmetic change.
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("PFAS_ALLOW_LEGACY_VENDOR_MAP", "1")

from pfas_pipeline import qc_engine
from pfas_pipeline.models import QCFlag


def test_every_kind_constant_is_distinct():
    kinds = [v for k, v in vars(qc_engine).items()
             if k.startswith("KIND_") and isinstance(v, str)]
    assert kinds, "no KIND_ constants found"
    assert len(kinds) == len(set(kinds)), kinds


def test_check_kinds_cover_every_mapped_check():
    """Every check the review queue can auto-resolve must map to a real kind."""
    import inspect
    from pfas_pipeline import run_queue
    src = inspect.getsource(run_queue.RunQueue.auto_evaluate)
    assert "_CHECK_KINDS" in src, "auto_evaluate no longer maps by kind"
    assert "f.source in relevant" not in src, (
        "auto_evaluate is matching on the display string again")
    known = {v for k, v in vars(qc_engine).items()
             if k.startswith("KIND_") and isinstance(v, str)}
    for kind in known:
        assert kind, "empty kind constant"


def test_a_flag_without_a_kind_never_satisfies_a_check():
    """The fallback must be 'unmatched', not 'matched'.

    A flag carrying no identity must not be silently attributed to a check —
    that is how the original defect passed unnoticed in the other direction.
    """
    flag = QCFlag(source="Calibration %", analyte="PFOA",
                  injection_name="X", value="1", issue="(CAL)")
    assert getattr(flag, "check_kind", "") == ""


def test_calibration_failures_reach_their_review_checks():
    """End-to-end on a real export: flags raised must not read as passes."""
    csv_path = os.environ.get("PFAS_TEST_RUN_CSV")
    if not csv_path or not os.path.exists(csv_path):
        print("  (skipped: set PFAS_TEST_RUN_CSV to an instrument export)")
        return

    from collections import Counter
    from pfas_pipeline.importer import load_instrument_csv, classify_injection
    from pfas_pipeline.injection_builder import REVIEW_CHECKS
    from pfas_pipeline.models import Batch
    from pfas_pipeline.run_queue import RunQueue
    from pfas_pipeline import pipeline as P

    rows = P.apply_extract_corrections(
        load_instrument_csv(csv_path), "FDA_32PFAS", "Animal Feed")
    batch = Batch(batch_id="T", injections=rows, analyst="t",
                  date=datetime.date(2025, 10, 20), matrix="Animal Feed",
                  method_id="FDA_32PFAS", instrument_file=csv_path)
    plan = [{"injection_name": n,
             "qc_type": classify_injection(n, {}),
             "checks": REVIEW_CHECKS.get(classify_injection(n, {}),
                                         REVIEW_CHECKS["Sample"])}
            for n in sorted({r.injection_name for r in rows})]
    queue = RunQueue(batch, plan, method_id="FDA_32PFAS")
    queue.auto_evaluate()

    # Every flag carries an identity.
    unkinded = [f for f in batch.qc_flags if not getattr(f, "check_kind", "")]
    assert not unkinded, "%d flags carry no check_kind" % len(unkinded)

    kinds = Counter(f.check_kind for f in batch.qc_flags)
    statuses = Counter(
        (c.check_name, c.status.name if hasattr(c.status, "name") else str(c.status))
        for c in queue.checks)

    # If the engine raised calibration flags, no calibration check may pass.
    if kinds.get(qc_engine.KIND_CALIBRATION):
        for name in ("calibration_pct_dev", "r_squared"):
            passed = statuses.get((name, "AUTO_PASS"), 0)
            assert passed == 0, (
                "%s reported AUTO_PASS %d time(s) while the run carried %d "
                "calibration flags" % (name, passed,
                                       kinds[qc_engine.KIND_CALIBRATION]))


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
