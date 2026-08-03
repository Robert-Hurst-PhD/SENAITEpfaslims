"""
Pipeline Orchestrator — the master conductor that replaces clicking macro
buttons in Excel.

End-to-end flow:

  watcher detects new MS export CSV
      │
      ▼
  run_pipeline(csv_path)
      1. importer.load_instrument_csv()           ← DATA table
      2. validate all injection names             ← ValidateInjectionNames
      3. build Batch object
      4. RunQueue.auto_evaluate()                 ← all 6 QC sheets at once
      5. build Summary results with qualifiers    ← Summary Sheet
      6. attach extraction log (if found)
      7. generate report PDF                      ← RunFullPDFPipeline
      8. push everything to SENAITE               ← REST API
      9. notify reviewer queue (pending checks)
"""

from __future__ import annotations
import logging
import time
from datetime import datetime
from pathlib import Path

from .importer import (
    load_instrument_csv, detect_software_version,
    validate_injection_name, classify_injection,
    group_by_injection,
)
from .models import Batch, SummaryResult, reported_conc
from .run_queue import RunQueue
from .injection_builder import REVIEW_CHECKS
from .barcode import ExtractionLog
from .report import generate_batch_report
from .constants import (
    QUALIFIER_ND, QUALIFIER_LOD, QUALIFIER_BLOQ, QUALIFIER_NC,
    reload_criteria,
)
from .method_profiles import (
    reload_from_profiles,
    get_analyte_list as _get_analytes,
    get_non_iso_set as _get_non_iso_set,
    get_included_display_analytes as _get_included_analytes,
    get_isomer_summation as _get_isomer_summation,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Summary builder  (BuildSummary VBA macro → Sheet 5)
# ─────────────────────────────────────────────────────────────────────────────

def build_summary(batch: Batch) -> list[SummaryResult]:
    """
    Build the Summary Sheet:
      - one row per analyte × environmental sample
      - qualifiers: N.D. / < LOD / BLoQ / N.C. / SUR  matching real output
        like '8.39 (BLoQ)', '0.0537 (BLoQ; N.C.)', '10.6 (BLoQ; SUR)'
      - isomer pairs (lr-/br-) are summed and reported under the reported name
    """
    summary: list[SummaryResult] = []

    # Identify MB injection(s) for <LOD rule (blank ≥ sample → < LOD)
    mb_rows = [r for r in batch.injections
               if classify_injection(r.injection_name) == "MB"]
    mb_conc = {r.compound_name: reported_conc(r)
               for r in mb_rows}

    # Surrogate-flagged injections (from IS results)
    sur_injections = {
        (res.is_compound, res.injection_name)
        for res in batch.is_results if res.flag
    }

    sample_rows = [r for r in batch.injections
                   if classify_injection(r.injection_name) == "Sample"]

    by_sample: dict[str, dict[str, object]] = {}
    for r in sample_rows:
        by_sample.setdefault(r.injection_name, {})[r.compound_name] = r

    _method = getattr(batch, "method_id", "") or "FDA_32PFAS"
    _matrix = getattr(batch, "matrix", "") or ""
    _analytes = _get_included_analytes(_method, _matrix) if _matrix else _get_analytes(_method)
    _non_iso = _get_non_iso_set(_method)

    # Build isomer lookup tables from method profile.
    # by_linear: analyte IS the linear name (e.g. "lr-PFOS" in _analytes)
    # by_reported: analyte IS the reported name (e.g. "PFOA" in _analytes)
    _isomer_pairs = _get_isomer_summation(_method)
    _isomer_by_linear: dict[str, dict] = {}
    _isomer_by_reported: dict[str, dict] = {}
    for _pair in _isomer_pairs:
        lin, rep = _pair.get("linear", ""), _pair.get("reported", "")
        if lin:
            _isomer_by_linear[lin] = _pair
        if rep and rep != lin:
            _isomer_by_reported[rep] = _pair

    def _sum_isomer_pair(pair, compounds, sample_name):
        """Return (result, qualifier, flags) for an lr+br isomer pair."""
        lin_row = compounds.get(pair["linear"])
        br_row  = compounds.get(pair["branched"])
        rep     = pair["reported"]

        # Fallback: if instrument exported the reported name instead of lr-/br- peaks
        if lin_row is None and br_row is None:
            direct = compounds.get(rep)
            if direct is not None:
                lin_row = direct  # treat as single-peak source

        if lin_row is None and br_row is None:
            return None, QUALIFIER_ND, []

        total = 0.0
        blank_total = 0.0
        reporting_limit = None
        linked_is = None
        # An isomer the instrument reported as BLoQ contributes no number but
        # is still a detection. Summing it as absent and calling the pair N.D.
        # understates the result.
        any_bloq = any(getattr(irow, "conc_qualifier", "") == QUALIFIER_BLOQ
                       for irow in (lin_row, br_row) if irow is not None)

        for irow in (lin_row, br_row):
            if irow is None:
                continue
            conc = reported_conc(irow)
            if conc is None:
                continue
            total += conc
            blank = mb_conc.get(irow.compound_name)
            if blank is not None:
                blank_total += blank
            # Both isomers carry the same analyte RL; capture from either
            if reporting_limit is None and irow.reporting_limit is not None:
                reporting_limit = irow.reporting_limit
            if irow.linked_is:
                linked_is = irow.linked_is

        if total == 0.0:
            return None, (QUALIFIER_BLOQ if any_bloq else QUALIFIER_ND), []

        # < LOD: summed blank ≥ summed sample
        if blank_total > 0.0 and blank_total >= total:
            return None, QUALIFIER_LOD, []

        flags_out: list[str] = []
        # BLoQ: the SUMMED result is below the reporting limit
        qualifier_out = (QUALIFIER_BLOQ
                         if reporting_limit is not None and total < reporting_limit
                         else "")
        if rep in _non_iso:
            flags_out.append(QUALIFIER_NC)
        if linked_is and (linked_is, sample_name) in sur_injections:
            flags_out.append("SUR")
        return total, qualifier_out, flags_out

    for sample_name, compounds in by_sample.items():
        for analyte in _analytes:
            flags: list[str] = []
            qualifier = ""
            result = None

            # Check whether this analyte is part of an isomer summation pair
            iso_pair = _isomer_by_linear.get(analyte) or _isomer_by_reported.get(analyte)
            if iso_pair:
                result, qualifier, flags = _sum_isomer_pair(
                    iso_pair, compounds, sample_name)
                reported_name = iso_pair["reported"]
            else:
                reported_name = analyte
                row = compounds.get(analyte)

                if row is None or reported_conc(row) is None:
                    # No number. What that MEANS is the instrument's to say:
                    # "BLoQ" is a detection below the quantitation limit, which
                    # is not the same claim as "not detected". Reporting both
                    # as N.D. overstated how clean these samples were.
                    qualifier = getattr(row, "conc_qualifier", "") or QUALIFIER_ND
                    if qualifier not in (QUALIFIER_BLOQ, QUALIFIER_NC):
                        qualifier = QUALIFIER_ND
                else:
                    conc = reported_conc(row)
                    blank = mb_conc.get(analyte)

                    if blank is not None and conc is not None and blank >= conc:
                        qualifier = QUALIFIER_LOD
                    else:
                        result = conc
                        if (row.reporting_limit is not None and conc is not None
                                and conc < row.reporting_limit):
                            qualifier = QUALIFIER_BLOQ
                        if analyte in _non_iso:
                            flags.append(QUALIFIER_NC)
                        linked_is = row.linked_is
                        if linked_is and (linked_is, sample_name) in sur_injections:
                            flags.append("SUR")

            summary.append(SummaryResult(
                analyte=reported_name,
                sample_injection=sample_name,
                result_ppt=result if qualifier != QUALIFIER_LOD else None,
                qualifier=qualifier,
                flags=flags,
            ))

    batch.summary = summary
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# Main pipeline
# ─────────────────────────────────────────────────────────────────────────────

def run_pipeline(
    csv_path: str | Path,
    batch_id: str | None = None,
    analyst: str = "",
    matrix: str = "",
    method_id: str = "",
    extraction_log_path: str | Path | None = None,
    output_dir: str | Path = ".",
    senaite: "SenaiteConnector | None" = None,
    client_uid: str = "",
) -> tuple[Batch, RunQueue, Path]:
    """
    Full pipeline on one instrument export.
    Returns (batch, run_queue, report_pdf_path).
    """
    # Reload QC criteria and full profile data from the exported JSON so
    # manager changes in the SENAITE UI take effect without a worker restart.
    reload_criteria()
    reload_from_profiles()

    csv_path = Path(csv_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Import — resolve column-mapping profile from Import Studio REST bridge
    #    then load the CSV using that profile.  Strict mode: if SENAITE is
    #    offline or no profile is saved, refuse with an informative error.
    import_profile = None
    if senaite is not None:
        # Send the file's own headers and let SENAITE identify the instrument.
        # The pipeline deliberately does NOT detect the vendor itself: two
        # detectors meant two answers, and the profile key built from the
        # loser's answer never matched anything Import Studio had saved.
        import pandas as _pd
        _headers = list(_pd.read_csv(csv_path, dtype=str, encoding="utf-8-sig",
                                     nrows=0).columns)
        _version = detect_software_version(csv_path)
        # Fetch profile — raises on SENAITE connectivity failure (no fallback)
        import_profile = senaite.get_instrument_profile(
            version=_version, columns=_headers)
        if "error" in import_profile:
            raise ImportError(import_profile["error"])
        logger.info("Using Import Studio profile %s:%s for %s",
                    import_profile.get("resolved_vendor_key", "?"),
                    import_profile.get("resolved_version") or "(no version)",
                    csv_path.name)

    rows = load_instrument_csv(csv_path, profile=import_profile)
    logger.info("Loaded %d rows / %d injections from %s",
                len(rows), len(group_by_injection(rows)), csv_path.name)

    # 2. Validate injection names (ValidateInjectionNames)
    bad = []
    for inj_name in {r.injection_name for r in rows}:
        v = validate_injection_name(inj_name)
        if not v["valid"]:
            bad.append(inj_name)
    if bad:
        logger.warning("Invalid injection names: %s", bad)

    # 3. Batch
    batch = Batch(
        batch_id=batch_id or csv_path.stem,
        analyst=analyst,
        date=datetime.now(),
        matrix=matrix,
        method_id=method_id,
        instrument_file=csv_path.name,
        injections=rows,
    )

    # 4. Review plan (derived from the injections actually present)
    review_plan = [
        {
            "injection_name": name,
            "qc_type": classify_injection(name),
            "checks": REVIEW_CHECKS.get(classify_injection(name),
                                        REVIEW_CHECKS["Sample"]),
        }
        for name in sorted({r.injection_name for r in rows})
    ]

    queue = RunQueue(batch, review_plan, method_id=method_id)
    queue.auto_evaluate()
    logger.info("QC engine raised %d flags; %d checks pending review",
                len(batch.qc_flags), len(queue.pending()))

    # 5. Summary
    build_summary(batch)

    # 5b. Persist per-injection detail for the multi-page Results Review (D59).
    try:
        from .injection_store import persist_injection_results
        n_inj = persist_injection_results(batch)
        logger.info("Persisted %d per-injection rows to injection_results", n_inj)
    except Exception as e:                            # noqa: BLE001
        logger.error("injection_results persist failed: %s", e)

    # 6. Extraction log
    ext_log = None
    if extraction_log_path and Path(extraction_log_path).exists():
        import json
        data = json.loads(Path(extraction_log_path).read_text())
        ext_log = ExtractionLog(data["batch_id"], data["analyst"],
                                data["matrix"])
        ext_log.steps = data.get("steps", [])
        ext_log.reagent_scans = data.get("reagent_scans", [])
        ext_log.signoffs = data.get("signoffs", [])
        batch.extraction_log = data
        batch.reagents = data.get("reagent_scans", [])

    # 7. Report PDF
    report_path = output_dir / f"{batch.batch_id}_report.pdf"
    generate_batch_report(batch, ext_log, report_path)
    logger.info("Report written: %s", report_path)

    # Save the queue for remote review
    queue.save(output_dir / f"{batch.batch_id}_queue.json")

    # 8. Push to SENAITE
    if senaite:
        try:
            buid = senaite.create_batch(batch, client_uid)
            senaite.push_qc_flags(buid, batch.qc_flags)
            senaite.attach_file(buid, report_path, "Batch Report")
            if extraction_log_path:
                senaite.attach_file(buid, extraction_log_path,
                                    "Extraction Log")
            for s in batch.summary:
                v = validate_injection_name(s.sample_injection)
                if v.get("starlims_id"):
                    sample = senaite.find_sample_by_starlims(v["starlims_id"])
                    if sample:
                        senaite.push_result(sample["uid"], s.analyte, s)
            logger.info("Pushed batch %s to SENAITE (%s)", batch.batch_id, buid)
        except Exception as e:                       # noqa: BLE001
            logger.error("SENAITE push failed: %s", e)

    return batch, queue, report_path


# ─────────────────────────────────────────────────────────────────────────────
# Directory watcher  (replaces manual CSV copying)
# ─────────────────────────────────────────────────────────────────────────────

def start_watcher(
    watch_dir: str | Path,
    output_dir: str | Path,
    senaite: "SenaiteConnector | None" = None,
    poll_seconds: int = 30,
    extraction_log_dir: str | Path | None = None,
):
    """
    Poll the instrument output directory.  When a new CSV lands:
      1. wait until the file size is stable (export finished)
      2. run the full pipeline
      3. results reviewable from anywhere via the saved queue + SENAITE
    """
    watch_dir = Path(watch_dir)
    seen: set[str] = {p.name for p in watch_dir.glob("*.csv")}
    logger.info("Watching %s (every %ds)", watch_dir, poll_seconds)

    while True:
        time.sleep(poll_seconds)
        for p in watch_dir.glob("*.csv"):
            if p.name in seen:
                continue
            # wait for export to finish (stable size)
            size = -1
            while size != p.stat().st_size:
                size = p.stat().st_size
                time.sleep(5)
            seen.add(p.name)
            logger.info("New instrument file: %s", p.name)

            ext_log = None
            if extraction_log_dir:
                candidate = Path(extraction_log_dir) / f"{p.stem}_extraction.json"
                if candidate.exists():
                    ext_log = candidate

            try:
                run_pipeline(p, output_dir=output_dir, senaite=senaite,
                             extraction_log_path=ext_log)
            except Exception as e:                   # noqa: BLE001
                logger.exception("Pipeline failed for %s: %s", p.name, e)
