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
from .analyte_alias import keyword_for
from .barcode import ExtractionLog
from .report import generate_batch_report
from .constants import (
    QUALIFIER_ND, QUALIFIER_LOD, QUALIFIER_BLOQ, QUALIFIER_NC, QUALIFIER_ALOQ,
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
    dilutions = getattr(batch, "dilutions", None) or {}

    mb_rows = [r for r in batch.injections
               if classify_injection(r.injection_name, dilutions) == "MB"]
    mb_conc = {r.compound_name: reported_conc(r)
               for r in mb_rows}

    # Surrogate-flagged injections (from IS results)
    sur_injections = {
        (res.is_compound, res.injection_name)
        for res in batch.is_results if res.flag
    }

    # Field samples AND the QC samples that are registered as samples in their
    # own right. The method blank and the spikes were getting no result filed
    # at all, so 96 analyses sat unsubmitted and the worksheet could not be
    # verified. Each row carries its qc_type so reports and the EDD exclude
    # them deliberately rather than because they happen to be empty.
    REPORTED_ROLES = ("Sample", "MB", "LFSM", "LFSMD")
    sample_rows = [r for r in batch.injections
                   if classify_injection(r.injection_name, dilutions)
                   in REPORTED_ROLES]

    by_sample: dict[str, dict[str, object]] = {}
    role_of: dict[str, str] = {}
    for r in sample_rows:
        by_sample.setdefault(r.injection_name, {})[r.compound_name] = r
        role_of[r.injection_name] = classify_injection(
            r.injection_name, dilutions)

    # Dilution injections, indexed by the sample they were diluted FROM. A
    # dilution is not a sample of its own — reporting it as one listed Egg-3
    # and Egg-4 twice, with no indication which row was the answer.
    dil_rows: dict[str, dict[str, object]] = {}
    dil_meta: dict[str, dict] = {}
    for r in batch.injections:
        entry = dilutions.get(r.injection_name)
        if not entry:
            continue
        parent = entry.get("parent") or ""
        dil_rows.setdefault(parent, {})[r.compound_name] = r
        dil_meta[parent] = {"injection": r.injection_name,
                            "factor": entry.get("factor")}

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

    # Flags raised against an isomer COMPONENT, so the summed result can carry
    # them: a confirmation failure on br-PFOS is a failure of the PFOS number
    # it feeds, even though br-PFOS is not reported on its own.
    component_flags: dict = {}
    for f in (batch.qc_flags or []):
        component_flags.setdefault((f.injection_name, f.analyte), set()).add(
            f.issue)

    def _blank_for(analyte, sample_name):
        """Method-blank concentration to subtract — but never from the blank
        itself. Comparing the MB against its own result makes every blank
        report as < LOD, which hides the very contamination the blank exists
        to show."""
        if role_of.get(sample_name) == "MB":
            return None
        return mb_conc.get(analyte)

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
        any_aloq = any(getattr(irow, "conc_qualifier", "") == QUALIFIER_ALOQ
                       for irow in (lin_row, br_row) if irow is not None)

        for irow in (lin_row, br_row):
            if irow is None:
                continue
            conc = reported_conc(irow)
            if conc is None:
                continue
            total += conc
            blank = _blank_for(irow.compound_name, sample_name)
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
        if any_aloq:
            # One isomer off the top of the curve makes the SUM an
            # extrapolation too, so the pair is reported from the dilution.
            qualifier_out = QUALIFIER_ALOQ
        elif reporting_limit is not None and total < reporting_limit:
            qualifier_out = QUALIFIER_BLOQ
        else:
            qualifier_out = ""
        for irow in (lin_row, br_row):
            if irow is None:
                continue
            for issue in sorted(component_flags.get(
                    (sample_name, irow.compound_name), ())):
                tag = "{0}:{1}".format(irow.compound_name, issue)
                if tag not in flags_out:
                    flags_out.append(tag)
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
                    blank = _blank_for(analyte, sample_name)

                    if blank is not None and conc is not None and blank >= conc:
                        qualifier = QUALIFIER_LOD
                    else:
                        result = conc
                        if row.conc_qualifier == QUALIFIER_ALOQ:
                            # Above the top calibrator. The number exists but is
                            # an extrapolation, so it is not reportable as-is —
                            # it is the trigger for using the dilution.
                            qualifier = QUALIFIER_ALOQ
                        elif (row.reporting_limit is not None and conc is not None
                                and conc < row.reporting_limit):
                            qualifier = QUALIFIER_BLOQ
                        if analyte in _non_iso:
                            flags.append(QUALIFIER_NC)
                        linked_is = row.linked_is
                        if linked_is and (linked_is, sample_name) in sur_injections:
                            flags.append("SUR")

            # A neat injection that read ABOVE the quantitation limit has no
            # usable number: the analyte is off the top of the calibration
            # curve. That is exactly why the dilution was run, so the dilution
            # supplies the reported value — and the over-range neat reading is
            # kept beside it so the substitution can be checked.
            source_injection = sample_name
            neat_result = None
            neat_qualifier = ""
            dil_factor = None
            meta = dil_meta.get(sample_name)
            if meta and QUALIFIER_ALOQ in (qualifier or ""):
                drow = (dil_rows.get(sample_name) or {}).get(reported_name)
                if drow is None and iso_pair:
                    dres, dqual, dflags = _sum_isomer_pair(
                        iso_pair, dil_rows.get(sample_name) or {}, sample_name)
                    if dres is not None:
                        neat_result, neat_qualifier = result, qualifier
                        result, qualifier, flags = dres, dqual, dflags
                        source_injection = meta["injection"]
                        dil_factor = meta.get("factor")
                elif drow is not None and reported_conc(drow) is not None:
                    neat_result, neat_qualifier = result, qualifier
                    result = reported_conc(drow)
                    qualifier = (drow.conc_qualifier
                                 if drow.conc_qualifier != QUALIFIER_ALOQ else "")
                    source_injection = meta["injection"]
                    dil_factor = meta.get("factor")

            summary.append(SummaryResult(
                analyte=reported_name,
                sample_injection=sample_name,
                qc_type=role_of.get(sample_name, "Sample"),
                result_ppt=result if qualifier != QUALIFIER_LOD else None,
                qualifier=qualifier,
                source_injection=source_injection,
                neat_result=neat_result,
                neat_qualifier=neat_qualifier,
                dilution_factor=dil_factor,
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
    senaite_batch_id: str = "",
) -> tuple[Batch, RunQueue, Path]:
    """
    Full pipeline on one instrument export.
    Returns (batch, run_queue, report_pdf_path).

    batch_id          the WORKSHEET id (e.g. "WS-0005"). Data Review joins the
                      QC database on it, so it must be the worksheet's, not the
                      batch's.
    senaite_batch_id  the SENAITE Batch this run belongs to, if any. Distinct
                      from batch_id on purpose: passing the worksheet id into
                      the batch lookup made the connector create a SECOND Batch
                      titled after the worksheet on every run.
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

    # Dilution map — needed before the name check below.
    #
    # The dilution map comes from the batch's FM-ENV-252 extraction log, which
    # is the only place the parent/factor relationship is recorded. Empty for
    # any batch that logged none, so those behave exactly as before.
    dilution_map = {}
    spike_map = {}
    if senaite is not None and senaite_batch_id:
        prep = senaite.get_batch_dilutions(senaite_batch_id) or {}
        spike_map = prep.pop("_spikes", {}) or {}
        dilution_map = prep
        if spike_map:
            logger.info("Extraction pedigree records %d matrix spike(s): %s",
                        len(spike_map),
                        ", ".join("%s <- %s @ %s ppt" % (v.get("parent"), k,
                                                        v.get("spike_ppt"))
                                  for k, v in sorted(spike_map.items())))
        if dilution_map:
            logger.info("FM-ENV-252 records %d dilution(s): %s",
                        len(dilution_map),
                        ", ".join("%s <- %s" % (v.get("parent"), k)
                                  for k, v in sorted(dilution_map.items())))


    # 2. Injection-name check.
    #
    # This used to warn whenever a name failed INJECTION_PATTERNS, a hardcoded
    # list of regexes encoding one lab's typing conventions. Once runs are
    # driven from the Run Builder the check is worse than useless: on a
    # worklist-generated file it fired on 21 of 22 names, every one of them
    # issued by this system and every one of them binding correctly. A warning
    # that cries wolf on correct data trains people to ignore the log.
    #
    # What actually matters is whether an injection corresponds to something
    # the LIMS knows about. Sample injections must resolve to a sample; the
    # pattern result is kept at debug level for the StarLIMS-style
    # conventions that still rely on it.
    planned = []
    if senaite is not None and senaite_batch_id:
        planned = (senaite.get_run_manifest(senaite_batch_id) or {}).get(
            "planned") or []
    if planned:
        actual = {r.injection_name for r in rows}
        unplanned = sorted(actual - set(planned))
        not_run = [p for p in planned if p not in actual]
        logger.info("Run vs plan: %d of %d planned injections ran",
                    len(planned) - len(not_run), len(planned))
        if not_run:
            logger.info("  planned but not run: %s", not_run)
        if unplanned:
            logger.warning("  ran but not planned: %s", unplanned)

    unknown = []
    for inj_name in sorted({r.injection_name for r in rows}):
        v = validate_injection_name(inj_name)
        if not v["valid"]:
            logger.debug("Injection name matches no configured pattern: %r",
                         inj_name)
        if senaite is None or classify_injection(
                inj_name, dilution_map) != "Sample":
            continue
        if not senaite.find_sample_by_client_sample_id(inj_name):
            if not (v.get("starlims_id")
                    and senaite.find_sample_by_starlims(v["starlims_id"])):
                unknown.append(inj_name)
    if unknown:
        logger.warning(
            "These sample injections match no SENAITE sample — their results "
            "cannot be filed. Set the sample's Client Sample ID to the "
            "injection name, or build the run from the Run Builder: %s",
            unknown)

    # 3. Batch
    batch = Batch(
        batch_id=batch_id or csv_path.stem,
        analyst=analyst,
        date=datetime.now(),
        matrix=matrix,
        method_id=method_id,
        instrument_file=csv_path.name,
        injections=rows,
        dilutions=dilution_map,
        spikes=spike_map,
    )

    # 4. Review plan (derived from the injections actually present)
    review_plan = [
        {
            "injection_name": name,
            "qc_type": classify_injection(name, dilution_map),
            "checks": REVIEW_CHECKS.get(classify_injection(name, dilution_map),
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

    # 5c. Persist the QC verdicts and calibration curves. Data Review's QC
    # Summary gate and the control charts read these; nothing wrote them, so a
    # successful import still left the gate reporting "no_batch_record".
    try:
        from .qc_store import persist_qc_results, persist_calibrations
        n_qc = persist_qc_results(batch)
        n_cal = persist_calibrations(batch)
        logger.info("Persisted %d QC results and %d calibration curves",
                    n_qc, n_cal)
    except Exception as e:                            # noqa: BLE001
        logger.error("qc_results persist failed: %s", e)

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
            # The worksheet is the run's home in SENAITE (CLAUDE.md §3), and
            # the only container besides Client that accepts an Attachment.
            ws = senaite.find_worksheet(batch.batch_id)
            ws_uid = ws["uid"] if ws else ""
            if not ws:
                logger.warning(
                    "No SENAITE Worksheet %r — the report cannot be attached "
                    "and Data Review will not find this run.", batch.batch_id)

            # Never invent a Batch. Look up the one named, and say so if it is
            # missing, rather than creating a duplicate titled after the
            # worksheet — which is what produced the stray B-00N batches.
            buid = ""
            if senaite_batch_id:
                found = senaite.find_batch(senaite_batch_id)
                if found:
                    buid = found["uid"]
                else:
                    logger.warning("No SENAITE Batch %r — QC flags not pushed.",
                                   senaite_batch_id)
            if buid:
                senaite.push_qc_flags(buid, batch.qc_flags)
            if ws_uid:
                senaite.attach_file(ws_uid, report_path, "Batch Report")
                if extraction_log_path:
                    senaite.attach_file(ws_uid, extraction_log_path,
                                        "Extraction Log")
            # Bind each summary row to its SENAITE sample.
            #
            # This used to require validate_injection_name() to yield a
            # 7-digit StarLIMS id. Real injection names carry no such number,
            # so nothing ever matched and every sample result was discarded
            # silently. The injection name IS the client's own name for the
            # sample, which is exactly what ClientSampleID holds — so look it
            # up directly, and keep the StarLIMS id as a fallback for labs
            # that do embed one.
            pushed = 0
            unmatched_samples = set()
            unmatched_analytes = set()
            sample_cache: dict = {}
            for s in batch.summary:
                inj = s.sample_injection
                if inj not in sample_cache:
                    found = senaite.find_sample_by_client_sample_id(inj)
                    if not found:
                        v = validate_injection_name(inj)
                        if v.get("starlims_id"):
                            found = senaite.find_sample_by_starlims(
                                v["starlims_id"])
                    sample_cache[inj] = found
                sample = sample_cache[inj]
                if not sample:
                    unmatched_samples.add(inj)
                    continue
                keyword = keyword_for(s.analyte)
                if senaite.push_result(sample["uid"], keyword, s):
                    pushed += 1
                else:
                    unmatched_analytes.add((s.analyte, keyword))
            logger.info("Pushed %d of %d results to SENAITE samples",
                        pushed, len(batch.summary))
            if unmatched_samples:
                logger.warning(
                    "No SENAITE sample matches these injections (set the "
                    "sample's Client Sample ID to the injection name): %s",
                    sorted(unmatched_samples))
            if unmatched_analytes:
                logger.warning(
                    "No Analysis for these analytes (name -> keyword): %s",
                    sorted(unmatched_analytes))
            logger.info("Pushed run %s to SENAITE (worksheet %s, batch %s)",
                        batch.batch_id, ws_uid or "-", buid or "-")
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
