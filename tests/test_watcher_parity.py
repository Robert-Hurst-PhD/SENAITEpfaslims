"""The automated path must produce the same results as the manual one.

`start_watcher` called `run_pipeline(csv, output_dir, senaite,
extraction_log_path)` — with no `method_id`, `matrix`, `batch_id` or
`senaite_batch_id`. So every file processed automatically got:

  * no matrix factor and no reporting unit — results left on the extract basis
  * no salt correction
  * no dilution map, so a dilution was reported as a sample in its own right
  * no extraction pedigree, so LFSM/LFSMD could not be evaluated
  * a batch_id defaulted from the filename, which Data Review cannot join

Every validation on this project had used manual invocation with the arguments
supplied by hand, so the path a lab actually uses was never the path that was
tested.

The sidecar the watcher already looked for carried `batch_id`, `analyst` and
`matrix` all along — but it was read at step 6, after the import, the
corrections, the QC engine and the summary had already run without them.

These tests pin the contract: the sidecar fills gaps, an explicit argument
always wins, and both routes agree exactly.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("PFAS_ALLOW_LEGACY_VENDOR_MAP", "1")
# Persist somewhere writable. Without this the run logs two "unable to open
# database file" errors against the container path -- harmless for these
# assertions, but noise that could hide a real persistence failure.
os.environ.setdefault(
    "PFAS_QC_DB", os.path.join(tempfile.gettempdir(), "pfas_parity_qc.db"))


def _sidecar(path, **overrides):
    data = {"batch_id": "PARITY-01", "analyst": "KCP",
            "matrix": "Animal Feed", "method_id": "FDA_32PFAS",
            "steps": [], "reagent_scans": [], "signoffs": []}
    data.update(overrides)
    with open(path, "w") as fh:
        json.dump(data, fh)
    return path


def _digest(batch):
    import hashlib
    rows = sorted(
        (r.analyte, r.sample_injection,
         None if r.result_ppt is None else round(r.result_ppt, 9),
         r.qualifier, tuple(sorted(r.flags)))
        for r in batch.summary)
    return hashlib.sha256(
        json.dumps(rows, default=str).encode()).hexdigest()[:16]


def _run(csv_path, tmp, **kw):
    from pfas_pipeline.pipeline import run_pipeline
    batch, _queue, _report = run_pipeline(csv_path, output_dir=tmp, **kw)
    return batch


def test_sidecar_and_explicit_arguments_agree():
    csv_path = os.environ.get("PFAS_TEST_RUN_CSV")
    if not csv_path or not os.path.exists(csv_path):
        print("  (skipped: set PFAS_TEST_RUN_CSV to an instrument export)")
        return

    tmp = tempfile.mkdtemp(prefix="pfas_parity_")
    side = _sidecar(os.path.join(tmp, "run_extraction.json"))

    explicit = _run(csv_path, tmp, batch_id="PARITY-01", analyst="KCP",
                    matrix="Animal Feed", method_id="FDA_32PFAS")
    from_sidecar = _run(csv_path, tmp, extraction_log_path=side)

    assert explicit.batch_id == from_sidecar.batch_id == "PARITY-01"
    assert explicit.matrix == from_sidecar.matrix == "Animal Feed"
    assert explicit.method_id == from_sidecar.method_id == "FDA_32PFAS"
    assert len(explicit.summary) == len(from_sidecar.summary)
    assert len(explicit.qc_flags) == len(from_sidecar.qc_flags)
    assert _digest(explicit) == _digest(from_sidecar), (
        "the automated path produced different results from the manual one")


def test_an_explicit_argument_beats_the_sidecar():
    """The sidecar fills gaps; it must not override a caller who knows better."""
    csv_path = os.environ.get("PFAS_TEST_RUN_CSV")
    if not csv_path or not os.path.exists(csv_path):
        print("  (skipped: set PFAS_TEST_RUN_CSV to an instrument export)")
        return

    tmp = tempfile.mkdtemp(prefix="pfas_parity_")
    side = _sidecar(os.path.join(tmp, "run_extraction.json"),
                    batch_id="FROM-SIDECAR", matrix="Eggs")
    batch = _run(csv_path, tmp, extraction_log_path=side,
                 batch_id="FROM-CALLER", matrix="Animal Feed")
    assert batch.batch_id == "FROM-CALLER", batch.batch_id
    assert batch.matrix == "Animal Feed", batch.matrix


def test_the_watcher_looks_for_a_sidecar_beside_the_csv():
    """A generator or an instrument PC drops both files together."""
    import inspect
    from pfas_pipeline import pipeline
    src = inspect.getsource(pipeline.start_watcher)
    assert 'p.with_name(f"{p.stem}_extraction.json")' in src, (
        "start_watcher no longer looks for a sidecar beside the CSV")
    assert "has no" in src and "sidecar" in src, (
        "start_watcher should warn when a file arrives with no sidecar")


def test_run_pipeline_reads_the_sidecar_before_it_is_needed():
    """Reading it at step 6 was the whole defect — the corrections, the QC
    engine and the summary had already run without those values."""
    import inspect
    from pfas_pipeline import pipeline
    src = inspect.getsource(pipeline.run_pipeline)
    sidecar_at = src.index("sidecar = {}")
    corrections_at = src.index("apply_extract_corrections")
    summary_at = src.index("build_summary")
    assert sidecar_at < corrections_at, "sidecar is read after the corrections"
    assert sidecar_at < summary_at, "sidecar is read after the summary"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
