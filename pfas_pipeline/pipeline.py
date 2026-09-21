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
from .models import Batch, QCFlag, SummaryResult, reported_conc
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
    get_matrix_factor as _get_matrix_factor,
    get_salt_factors as _get_salt_factors,
    get_reporting_unit as _get_unit,
    get_analyte_list as _get_analytes,
    get_non_iso_set as _get_non_iso_set,
    get_included_display_analytes as _get_included_analytes,
    get_isomer_summation as _get_isomer_summation,
    get_surrogate_map as _get_surrogate_map,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Summary builder  (BuildSummary VBA macro → Sheet 5)
# ─────────────────────────────────────────────────────────────────────────────

# Injection kinds with no sample basis. The instrument's own sample_type is the
# right authority here: it states what was in the vial.
_NO_SAMPLE_BASIS = frozenset(["Standard", "Quality Control"])


def _has_sample_basis(row):
    return (row.sample_type or "").strip() not in _NO_SAMPLE_BASIS


def apply_extract_corrections(rows, method_id, matrix):
    """Put every concentration on the reported sample basis, in one place.

    Two multiplicative corrections, both configured per method: the per-analyte
    SALT factor (the standard was supplied as a salt, so the curve reads the
    counter-ion too) and the per-matrix factor that converts an extract
    concentration to the sample basis.

    Both apply to NATIVE ANALYTES ONLY. Internal standards and surrogates are
    judged on their own response, and the instrument's Total rows are sums of
    natives, so correcting either would double-count.

    Both also apply ONLY to injections that HAVE a sample basis. A calibration
    standard or a CCV is a prepared solution: there is no sample weight behind
    it, so converting it to a sample basis is meaningless. Scaling them made
    every CCV read ~200% of its expected concentration, which stayed invisible
    for as long as nothing checked CCV recovery -- wiring that check is what
    exposed it. The method blank keeps the corrections: it is taken through the
    extraction like a sample and is reported on the same basis.

    Named and extracted rather than left inline because "which corrections were
    applied, in what order" is a question a reviewer asks of every result, and
    it should have exactly one answer to read.
    """
    # Salt (counter-ion) correction first: it corrects the standard the curve
    # was built from, so it belongs on the extract basis, before the extract is
    # converted to the sample basis. The two are multiplicative and commute,
    # but keeping the order meaningful keeps the log readable.
    salt_factors = _get_salt_factors(method_id) if method_id else {}
    if salt_factors:
        salted = 0
        for row in rows:
            if (row.compound_type or "").strip() != "Analyte":
                continue
            if not _has_sample_basis(row):
                continue
            factor = salt_factors.get(row.compound_name)
            if not factor:
                continue
            for field in ("calculated_conc", "measured_conc",
                          "reporting_limit"):
                value = getattr(row, field, None)
                if value is not None:
                    setattr(row, field, value * factor)
            salted += 1
        logger.info("Applied per-analyte salt correction to %d rows (%s)",
                    salted, ", ".join(
                        "{0} x {1:g}".format(a, f)
                        for a, f in sorted(salt_factors.items())
                        if not a.startswith("M")))
    elif method_id:
        logger.info("No salt correction configured for %s — standards are "
                    "treated as free acids.", method_id)

    matrix_factor = None
    if method_id and matrix:
        matrix_factor = _get_matrix_factor(method_id, matrix)
    if matrix_factor and matrix_factor != 1.0:
        converted = 0
        for row in rows:
            if (row.compound_type or "").strip() != "Analyte":
                continue
            if not _has_sample_basis(row):
                continue
            for field in ("calculated_conc", "measured_conc",
                          "reporting_limit"):
                value = getattr(row, field, None)
                if value is not None:
                    setattr(row, field, value * matrix_factor)
            # The row now carries a SAMPLE-basis concentration, so it must say
            # so: everything downstream that compares against it — the spike
            # level above all — reads this to know what it is looking at.
            reported_unit = _get_unit(method_id, matrix)
            if reported_unit:
                row.conc_units = reported_unit
            converted += 1
        logger.info("Applied the %s matrix factor %.4g to %d native analyte "
                    "rows; results are now on the sample basis (%s)",
                    matrix, matrix_factor, converted,
                    _get_unit(method_id, matrix) or "per method unit map")
    elif method_id and matrix:
        logger.warning("No matrix factor configured for %s / %s — results stay "
                       "on the extract basis the instrument reported, which "
                       "will not match a spike level recorded per sample.",
                       method_id, matrix)
    return rows


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
    # Keyed by KEYWORD so a surrogate failure is found whichever spelling the
    # instrument used for it.
    sur_injections = {
        (keyword_for(res.is_compound or ""), res.injection_name)
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
    # The METHOD owns the surrogate -> analyte quantification link (§3). The
    # instrument's own `linked_is` column is the fallback, not the authority:
    # taking it as the authority meant a lab's drag-and-drop surrogate map had
    # no effect on any result, and the method's notation never reached the
    # analysis at all.
    _sur_map = _get_surrogate_map(_method)
    _is_mismatch: dict = {}

    def _quantifying_is(analyte_name, irow):
        """The surrogate this analyte is quantified against, as a keyword.

        Both sides are normalised before they are compared: the profile stores
        "M8PFOA" and the instrument exports "13C8-PFOA" for the same compound,
        so a raw comparison called all 20 surrogates a disagreement. Returning
        the keyword also keeps the surrogate-failure lookup spelling-agnostic.
        """
        configured = keyword_for(_sur_map.get(analyte_name) or "") or None
        reported = keyword_for(getattr(irow, "linked_is", None) or "") or None
        if configured and reported and configured != reported:
            # A method naming one surrogate while the instrument used another
            # is a finding for review, not something to resolve silently.
            _is_mismatch[analyte_name] = (configured, reported)
        return configured or reported

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
            resolved = _quantifying_is(rep or irow.compound_name, irow)
            if resolved:
                linked_is = resolved

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
                        linked_is = _quantifying_is(analyte, row)
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

    # A method that names one quantifying surrogate while the instrument
    # reported another is a review finding, not something to resolve silently
    # in either direction. Tagged on the affected rows so it reaches Data
    # Review rather than only the worker log.
    if _is_mismatch:
        for analyte, (configured, reported) in sorted(_is_mismatch.items()):
            logger.warning(
                "Surrogate map disagrees with the instrument for %s: method "
                "profile says %s, %s reported %s",
                analyte, configured, _method, reported)
        for row in summary:
            pair = _is_mismatch.get(row.analyte)
            if pair:
                row.is_mismatch = ("method profile names {0}; instrument "
                                   "reported {1}".format(*pair))
        # Also raised as a QC flag so it reaches Data Review and the QC Review
        # Report through the same channel as every other reviewer finding.
        for analyte, (configured, reported) in sorted(_is_mismatch.items()):
            batch.qc_flags.append(QCFlag(
                source="Surrogate Map",
                analyte=analyte,
                injection_name="",
                value=reported,
                issue="(ISMAP) method profile names {0}; instrument reported "
                      "{1}".format(configured, reported),
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
    # ── Run parameters from the extraction sidecar ───────────────────────────
    #
    # The sidecar has always carried batch_id, analyst and matrix — but it was
    # read at step 6, AFTER the import, the corrections, the QC engine and the
    # summary had all run without them. The watcher passes none of these, so
    # every automated run silently produced results with no matrix factor, no
    # salt correction, no dilution handling, no spike evaluation and no unit,
    # under a batch_id Data Review could not join. Everything validated on this
    # project used manual invocation with the arguments supplied by hand.
    #
    # An EXPLICIT argument always wins: the sidecar fills gaps, it does not
    # override a caller who knows better.
    #
    # Read BEFORE the profile reload below (moved ahead of it so
    # senaite_batch_id is known in time to overlay that batch's resolved
    # criteria — see reload_from_profiles(batch_id=...) just below): both
    # blocks only ever read function arguments/the sidecar file, so this
    # reordering changes nothing else about either one.
    sidecar = {}
    if extraction_log_path and Path(extraction_log_path).exists():
        import json as _json
        try:
            sidecar = _json.loads(Path(extraction_log_path).read_text()) or {}
        except (ValueError, OSError) as exc:
            logger.error("extraction sidecar %s is unreadable (%s); the run "
                         "continues with whatever arguments were passed",
                         extraction_log_path, exc)
            sidecar = {}
    if sidecar:
        batch_id = batch_id or sidecar.get("batch_id") or None
        analyst = analyst or sidecar.get("analyst") or ""
        matrix = matrix or sidecar.get("matrix") or ""
        method_id = method_id or sidecar.get("method_id") or ""
        client_uid = client_uid or sidecar.get("client_uid") or ""
        senaite_batch_id = (senaite_batch_id
                            or sidecar.get("senaite_batch_id") or "")
        logger.info("Sidecar %s supplied: batch_id=%s method=%s matrix=%s "
                    "senaite_batch_id=%s",
                    Path(extraction_log_path).name, batch_id or "-",
                    method_id or "-", matrix or "-", senaite_batch_id or "-")
    elif not method_id or not matrix:
        logger.warning(
            "No method_id/matrix supplied and no extraction sidecar found for "
            "%s. Results will stay on the extract basis with no salt or matrix "
            "correction, and LFSM/LFSMD cannot be evaluated. Provide a "
            "<stem>_extraction.json sidecar, or call run_pipeline with the "
            "arguments.", csv_path.name)

    # Reload QC criteria and full profile data from the exported JSON so
    # manager changes in the SENAITE UI take effect without a worker restart.
    # senaite_batch_id (now known, from an explicit argument or the sidecar
    # above) additionally overlays that batch's RESOLVED (project-aware)
    # criteria, if senaite.pfas has ever exported any for it — see
    # reload_from_profiles()'s docstring for the safety property this
    # preserves when there is none, which is every run today.
    reload_criteria()
    reload_from_profiles(batch_id=senaite_batch_id or None)

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

    # Convert extract concentrations to the reported sample basis, using the
    # method's configured per-matrix multiplier. Applied to NATIVE ANALYTES
    # ONLY: internal standards and surrogates are judged on their own response
    # and instrument-computed Total rows are sums of natives, so multiplying
    # either would double-count. Everything else the instrument reports is
    # already on its final basis.
    rows = apply_extract_corrections(rows, method_id, matrix)

    # Dilution map — needed before the name check below.
    #
    # The dilution map comes from the batch's FM-ENV-252 extraction log, which
    # is the only place the parent/factor relationship is recorded. Empty for
    # any batch that logged none, so those behave exactly as before.
    dilution_map = {}
    spike_map = {}
    if senaite is not None and not senaite_batch_id:
        # A connector without a batch id silently skips the extraction
        # pedigree, so matrix spikes and dilutions both vanish and the run
        # still looks complete -- it just reports "required QC not evaluated"
        # and folds no dilution into its parent. That cost a full E2E
        # misdiagnosis; say so instead.
        logger.warning(
            "senaite_batch_id was not supplied, so FM-ENV-252 is not read: "
            "matrix spikes and dilutions will be absent, LFSM/LFSMD cannot be "
            "evaluated, and dilution injections will be reported as samples in "
            "their own right. Pass the SENAITE Batch id to use the pedigree.")
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
    if sidecar:
        # Already parsed above — read once, not twice.
        data = sidecar
        ext_log = ExtractionLog(data.get("batch_id") or batch.batch_id,
                                data.get("analyst") or analyst,
                                data.get("matrix") or matrix)
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

            # The sidecar carries the run parameters, so look for it beside
            # the CSV as well as in a configured directory — a generator or an
            # instrument PC can then drop both files together.
            ext_log = None
            candidates = [p.with_name(f"{p.stem}_extraction.json")]
            if extraction_log_dir:
                candidates.insert(
                    0, Path(extraction_log_dir) / f"{p.stem}_extraction.json")
            for candidate in candidates:
                if candidate.exists():
                    ext_log = candidate
                    break
            if ext_log is None:
                logger.warning(
                    "%s has no %s_extraction.json sidecar — the run will have "
                    "no method, matrix, batch id or extraction pedigree.",
                    p.name, p.stem)

            try:
                run_pipeline(p, output_dir=output_dir, senaite=senaite,
                             extraction_log_path=ext_log)
            except Exception as e:                   # noqa: BLE001
                logger.exception("Pipeline failed for %s: %s", p.name, e)
