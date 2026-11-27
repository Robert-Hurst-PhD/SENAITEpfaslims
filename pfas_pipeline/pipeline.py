"""
Pipeline orchestrator: one instrument export, end to end.

  watcher detects new MS export CSV
      │
      ▼
  run_pipeline(csv_path)
      1. importer.load_instrument_csv()
      2. validate all injection names
      3. build Batch object
      4. RunQueue.auto_evaluate()                 ← every QC check at once
      5. build Summary results with qualifiers
      6. attach extraction log (if found)
      7. generate report PDF
      8. push everything to SENAITE               ← REST API
      9. notify reviewer queue (pending checks)
"""

from __future__ import annotations
import json
import logging
import os
import sqlite3
import re
import time
from datetime import datetime
from pathlib import Path

from .importer import (
    load_instrument_csv, file_head,
    validate_injection_name, classify_injection,
    group_by_injection,
)
from . import dilution_routes
from .models import Batch, QCFlag, SummaryResult, reported_conc
from .run_queue import RunQueue
from .review_checks import REVIEW_CHECKS
from .analyte_alias import keyword_for, keyword_of
from .extraction_log import ExtractionLog
from .qc_engine import (single_transition_confirm_needed, KIND_OVER_RANGE, qualifiers_deleted, raw_is_deleted,
                        ratio_held,
                        COELUTION_FLAG, coelution_split, FITTED_FLAG, fitted_estimate)
from .report import generate_batch_report
from .constants import (
    QUALIFIER_ND, QUALIFIER_LOD, QUALIFIER_BLOQ, QUALIFIER_NC, QUALIFIER_ALOQ,
    QUALIFIER_CONF, QUALIFIER_NQ,
)
from .method_profiles import (
    reload_from_profiles,
    profile_configured,
    get_matrix_factor as _get_matrix_factor,
    get_salt_factors as _get_salt_factors,
    get_reporting_unit as _get_unit,
    get_sample_correction as _get_sample_correction,
    get_blank_subtraction as _get_blank_subtraction,
    get_analyte_list as _get_analytes,
    get_non_iso_set as _get_non_iso_set,
    get_included_display_analytes as _get_included_analytes,
    get_isomer_summation as _get_isomer_summation,
    get_surrogate_map as _get_surrogate_map,
    get_composites as _get_composites,
    quantifying_members as _quantifying_members,
    get_integration,
    get_labelled_links,
    integration_mode,
    get_profile,
)

from .addon import load as _addon

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Summary builder
# ─────────────────────────────────────────────────────────────────────────────

# Injection kinds with no sample basis. The instrument's own sample_type is the
# right authority here: it states what was in the vial.
_NO_SAMPLE_BASIS = frozenset(["Standard", "Quality Control"])


# Prepared in solvent: no sample weight stands behind them, whatever the
# export calls them (a solvent blank is exported as "Blank" like the method
# blank). The run record's role decides.
_NO_SAMPLE_BASIS_ROLES = frozenset(["CAL", "ICV", "CCV", "CCB"])


def _is_labelled(name):
    from .analyte_alias import is_labelled
    return is_labelled(name)


def _has_sample_basis(row):
    """Is this injection on the sample basis? An injection the run plan or
    the extraction record names is what its role says (whatever word the
    export uses for it); one they do not name falls back to the export's
    sample type, then the name."""
    from .importer import _MEMBER_ROLES
    if row.injection_name not in _MEMBER_ROLES and (row.sample_type or "").strip() in _NO_SAMPLE_BASIS:
        return False
    return classify_injection(row.injection_name) not in _NO_SAMPLE_BASIS_ROLES


def _isomer_parts(method_id):
    """{isomer peak name: the analyte its group is reported as} of the method
    (its Isomers tab)."""
    out = {}
    for g in (_get_isomer_summation(method_id) if method_id else []):
        for n in [g.get("linear")] + list(g.get("branched_list") or []):
            if n:
                out[n] = g.get("reported") or ""
    return out


def _is_native(row, parts=None):
    """A native analyte's row: so typed by the export ("Analyte"), or -- whatever
    the export calls it, or with no type column at all -- a compound the
    compound library holds as a native analyte, or an isomer peak of one (the
    method's isomer groups, `parts`). An instrument's own "Total" row sums
    natives and is never one."""
    kind = (row.compound_type or "").strip()
    if kind == "Analyte":
        return True
    if kind == "Total":
        return False
    from .analyte_alias import is_native_name
    name = row.compound_name
    return is_native_name(name) or bool((parts or {}).get(name)) and is_native_name(parts[name])


def apply_extract_corrections(rows, method_id, matrix, sample_amounts=None,
                              dilutions=None, fallbacks=None, acid_basis=None):
    """Put every concentration on the reported sample basis, in one place.

    Two multiplicative corrections, both configured per method: the per-analyte
    SALT factor (the standard was supplied as a salt, so the curve reads the
    counter-ion too) and the per-matrix factor that converts an extract
    concentration to the sample basis.

    Both apply to NATIVE ANALYTES ONLY. Internal standards and surrogates are
    judged on their own response, and the instrument's Total rows are sums of
    natives, so correcting either would double-count.

    Both also apply ONLY to injections that HAVE a sample basis. A calibration
    standard or a CCV is a prepared solution with no sample weight behind it:
    scaling it would misread its recovery. The method blank keeps the
    corrections: it is taken through the extraction like a sample and is
    reported on the same basis.

    One function, so "which corrections were applied, in what order" has
    exactly one answer to read.
    """
    # Salt (counter-ion) correction first: it corrects the standard the curve
    # was built from, so it belongs on the extract basis, before the extract is
    # converted to the sample basis. The two commute; the order keeps the log
    # readable.
    parts = _isomer_parts(method_id)
    salt_factors = _get_salt_factors(method_id) if method_id else {}
    # An analyte whose calibration lots were made from certificate values as
    # the acid (the run record's acid_basis_analytes) is already on the acid
    # basis: its salt factor would correct it twice.
    # An isomer peak (lr-/br-) takes the basis of the analyte it is reported as.
    acid = set((a or "").strip().upper() for a in (acid_basis or []))
    if acid and salt_factors:
        def on_acid(name):
            return name.upper() in acid or (parts.get(name) or "").upper() in acid
        skipped = sorted(a for a in salt_factors if on_acid(a))
        salt_factors = dict((a, f) for a, f in salt_factors.items() if not on_acid(a))
        # the value analyser says the factor was not applied, and why
        for row in rows:
            if row.compound_name in skipped and _is_native(row, parts) and _has_sample_basis(row):
                row.salt_basis = "acid"
        if skipped:
            logger.info("No salt correction for %s: calibration standards stated as acid",
                        ", ".join(skipped))
    if salt_factors:
        salted = 0
        for row in rows:
            if not _is_native(row, parts):
                continue
            if not _has_sample_basis(row):
                continue
            factor = salt_factors.get(row.compound_name)
            if not factor:
                continue
            _scale_row(row, factor, "salt_factor")
            salted += 1
        logger.info("Applied per-analyte salt correction to %d rows (%s)",
                    salted, ", ".join(
                        "{0} x {1:g}".format(a, f)
                        for a, f in sorted(salt_factors.items())
                        if not _is_labelled(a)))
    elif method_id:
        logger.info("No salt correction configured for %s — standards are "
                    "treated as free acids.", method_id)

    matrix_factor = None
    if method_id and matrix:
        matrix_factor = _get_matrix_factor(method_id, matrix)
    mode = _get_sample_correction(method_id) if method_id else ""
    reported_unit = _get_unit(method_id, matrix) if method_id and matrix else ""
    if mode == "instrument":
        # The MS software applied each sample's correction factor: the
        # imported number IS the sample-basis result. Applying any factor
        # here would correct it twice.
        for row in rows:
            if _is_native(row, parts) and _has_sample_basis(row) and reported_unit:
                row.conc_units = reported_unit
        logger.info("%s: results arrive per sample from the MS software; no "
                    "matrix factor applied", method_id)
        return rows
    if mode == "lims":
        per_sample = _addon("sample_correction").factor_for
        parents = dict((k, (v or {}).get("parent") or "") for k, v in (dilutions or {}).items())
        per_sample_rows, nominal = 0, set()
        for row in rows:
            if not _is_native(row, parts) or not _has_sample_basis(row):
                continue
            sample = parents.get(row.injection_name) or row.injection_name
            factor = per_sample((sample_amounts or {}).get(sample), reported_unit)
            if factor is None:
                factor = matrix_factor
                nominal.add(row.injection_name)
            else:
                per_sample_rows += 1
            if not factor:
                continue
            _scale_row(row, factor, "matrix_factor")
            if reported_unit:
                row.conc_units = reported_unit
        if fallbacks is not None:
            fallbacks.extend(sorted(nominal))
        if nominal:
            logger.warning(
                "%s: no logged sample amount and final volume for %s -- the "
                "nominal %s matrix factor was used for them, flagged for review",
                method_id, ", ".join(sorted(nominal)), matrix)
        logger.info("%s: back-calculated %d native rows from logged amounts",
                    method_id, per_sample_rows)
        return rows
    if matrix_factor and matrix_factor != 1.0:
        converted = 0
        for row in rows:
            if not _is_native(row, parts):
                continue
            if not _has_sample_basis(row):
                continue
            _scale_row(row, matrix_factor, "matrix_factor")
            # The row now carries a SAMPLE-basis concentration and says so:
            # everything downstream (the spike level above all) reads its unit.
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


def row_factor(row):
    """The product of the factors applied to a row's reading (salt, sample
    basis): what a reading kept before them is multiplied by to stand
    beside the row's number."""
    return (getattr(row, "salt_factor", None) or 1.0) * (getattr(row, "matrix_factor", None) or 1.0)


DILUTION_RECOVERY_UNSET = "choose how a dilution's surrogate recovery is taken"


def field_dilution(name, dilutions):
    """A dilution of a reported field sample (never of extracted QC, which
    is not diluted)."""
    entry = (dilutions or {}).get(name)
    return bool(entry) and classify_injection(entry.get("parent") or "") == "Sample"


def tag_quantitation(rows, method_id):
    """Each native's record of what it was quantified on ({"standard",
    "role"}) and, for one on a surrogate, the method's linked response
    ratio ("on" / "off"): a raw run read it so (raw_run.linked_standard);
    an export's number is the instrument's, quantified as its own method
    says, and the LIMS recomputes or multiplies nothing. The readout names
    the setting either way."""
    from .method_profiles import get_linked_response_ratio, get_labelled_roles
    if not method_id:
        return rows
    qmap = quantitation_map(method_id)
    if not qmap:
        return rows
    mode = get_linked_response_ratio(method_id)
    parts = _isomer_parts(method_id)
    roles = get_labelled_roles(method_id)
    for row in rows:
        if not _is_native(row, parts):
            continue
        named = (qmap.get(row.compound_name) or qmap.get(keyword_for(row.compound_name) or "") or "").strip()
        if not named:
            continue
        role = quantifying_role(method_id, named, roles)
        row.quantified_on = {"standard": named, "role": role or ""}
        if role == "surrogate":
            row.linked_ratio = mode
    return rows


def dilution_recovery_flags(rows, method_id, dilutions):
    """Under the linked response ratio with no choice of how a dilution's
    surrogate recovery is taken: one advisory flag per diluted field
    sample, filed on the sample it was diluted from, naming the choice to
    make. Its recovery is then not judged; its results are not held."""
    from .method_profiles import get_linked_response_ratio, get_dilution_recovery
    if not method_id or get_linked_response_ratio(method_id) != "on" or get_dilution_recovery(method_id):
        return []
    flags = []
    for inj in sorted(set(r.injection_name for r in rows)):
        if not field_dilution(inj, dilutions):
            continue
        flags.append(QCFlag(
            source="Dilution recovery", analyte="(surrogates)",
            injection_name=dilution_routes.file_under(inj, dilutions), value=inj,
            issue="(DILREC) %s: %s" % (inj, DILUTION_RECOVERY_UNSET), check_kind="dilution_recovery",
            advisory=True))
    return flags


def _scale_row(row, factor, kind):
    """Multiply the row's three concentration fields by `factor`, keeping
    what they were before the FIRST correction and which factors were
    applied (value provenance). The scaled fields are what every rule
    reads."""
    for field in ("calculated_conc", "measured_conc", "reporting_limit"):
        value = getattr(row, field, None)
        raw_field = "raw_" + field
        if getattr(row, raw_field, None) is None and value is not None:
            setattr(row, raw_field, value)
        if value is not None:
            setattr(row, field, value * factor)
    setattr(row, kind, factor)


def choose_subtraction_blank(mb_names, marked):
    """The method blank a run compares with / subtracts: the marked one when
    it ran, else the only one, else None."""
    if marked and marked in mb_names:
        return marked
    if len(mb_names) == 1:
        return mb_names[0]
    return None


def build_summary(batch: Batch) -> list[SummaryResult]:
    """
    Build the summary (one row per analyte x sample):
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
    # Every method blank is JUDGED alike (run_queue's blank check). One is the
    # blank results are compared with and, when the method subtracts, taken
    # from: the one the extraction batch marks, else the only one. Several and
    # none marked: nothing is compared or subtracted, and the run says so --
    # the blank is never guessed.
    mb_names = sorted(set(r.injection_name for r in mb_rows))
    chosen_mb = choose_subtraction_blank(mb_names, getattr(batch, "subtraction_blank", "") or "")
    if chosen_mb is None and len(mb_names) > 1:
        if not hasattr(batch, "unconfigured"):
            batch.unconfigured = []          # (set by the run queue in a real run)
        batch.unconfigured.append({
            "qc_type": "MB", "analyte": "", "method_id": getattr(batch, "method_id", "") or "",
            "reason": "%d method blanks (%s) and none marked for subtraction: results are not "
                      "compared with a blank: choose the subtraction blank on the extraction "
                      "batch and reprocess" % (len(mb_names), ", ".join(mb_names))})
    mb_conc = {r.compound_name: reported_conc(r)
               for r in mb_rows if r.injection_name == chosen_mb}

    # Surrogate-flagged injections (from IS results)
    # Keyed by KEYWORD so a surrogate failure is found whichever spelling the
    # instrument used for it.
    sur_injections = {
        (keyword_for(res.is_compound or ""), res.injection_name)
        for res in batch.is_results if res.flag
    }

    # Field samples AND the QC samples registered as samples in their own
    # right: every analysis gets a result filed, or the worksheet cannot be
    # verified. Each row carries its qc_type, so reports and the EDD exclude
    # QC by its type.
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
    # dilution is not a sample of its own: one sample, one reported row.
    dil_rows: dict[str, dict[str, object]] = {}
    dil_meta: dict[str, dict] = {}
    for r in batch.injections:
        entry = dilutions.get(r.injection_name)
        if not entry:
            continue
        parent = entry.get("parent") or ""
        dil_rows.setdefault(parent, {})[r.compound_name] = r
        dil_meta[parent] = {"injection": r.injection_name,
                            "factor": entry.get("factor"), "route": entry.get("route") or "",
                            "sur_handling": entry.get("sur_handling") or "",
                            "is_handling": entry.get("is_handling") or ""}

    _method = getattr(batch, "method_id", "") or ""
    if not _method:
        # never another method's panel and criteria: refuse
        raise ValueError("The batch names no method, so its results cannot be "
                         "summarised against one. Give the run its method.")
    _matrix = getattr(batch, "matrix", "") or ""
    _analytes = _get_included_analytes(_method, _matrix) if _matrix else _get_analytes(_method)
    _non_iso = _get_non_iso_set(_method)
    _dil_in_software = _get_sample_correction(_method) == "instrument"
    from .method_profiles import get_linked_response_ratio as _get_linked
    _linked = _get_linked(_method) == "on"
    _subtract_blank = _get_blank_subtraction(_method) if _method else False
    # FDA §10.2(4) needs the method's confirmation rule, resolved once per
    # batch; a batch whose method has no exported profile refuses
    # (get_profile raises) rather than dropping the prompt.
    from .method_profiles import get_profile as _get_profile_obj
    _conf_profile = _get_profile_obj(_method)
    # the method's dilution settings: a re-spiked result's qualifier, the fold
    # rule (by the role of the standard quantifying each analyte)
    _dil_settings = dilution_routes.settings_of(
        _conf_profile._profile_data() if _conf_profile is not None else {})
    from .method_profiles import get_labelled_roles as _labelled_roles
    _std_roles = _labelled_roles(_method)
    _rl_matrix = (_addon("report_limits").canonical_matrix(_conf_profile._profile_data(), _matrix)
                  if _conf_profile is not None else _matrix)

    def _bloq(conc, qualifier, reported_name, row_rl=None, fold=None):
        """The qualifier a numeric result reads: below quantitation is
        decided by the reporting limit the certificate prints, for a single
        analyte and a summed isomer alike -- the method's RL for the
        REPORTED analyte in this matrix (typed, else its default from the
        lowest calibrator), times a dilution's fold, judged on the value
        rounded as the certificate rounds it. Only where the method has no
        RL for the analyte does the instrument row's own limit decide.
        A qualifier other than BLoQ (ALoQ, < LOD, ...) is kept."""
        if conc is None or qualifier not in ("", QUALIFIER_BLOQ):
            return qualifier
        rl = (_conf_profile.reporting_limits(reported_name, _rl_matrix, getattr(batch, "acid_basis", None))[0]
              if _conf_profile is not None else None)
        if rl is None:
            if not qualifier and row_rl is not None and conc < row_rl:
                return QUALIFIER_BLOQ
            return qualifier
        rl = _addon("report_limits").scaled_rl(rl, fold)
        judged = _conf_profile.judged_conc(conc, _matrix)
        return QUALIFIER_BLOQ if judged is not None and judged < rl else ""
    # ...and the lab's switch for whether to prompt at all. The OBLIGATION is
    # method text; the PROMPT is optional, because PFBA can be confirmed by
    # routes other than the LC-HRMS the method cites (a second column, a
    # different ionisation mode, an alternative transition) recorded elsewhere.
    #
    # Gated through the same _rule_enabled/_load_rule_toggles pair every other
    # instrument rule uses, on a key that IS in RULE_LIBRARY and in
    # LIBRARY_KEY_TO_ENGINE_CHECKS: a switch the engine reads must be one the
    # lab is given.
    _confirm_on = True
    if _conf_profile is not None:
        from .run_queue import _load_rule_toggles, _rule_enabled
        _confirm_on = _rule_enabled(_load_rule_toggles(_method),
                                    "single_transition_confirm")
    if not _confirm_on:
        logger.info("%s: single-transition confirmation prompt is switched OFF "
                    "in the QC rules; §10.2(4) positives will carry no "
                    "confirmation qualifier", _method)

    # Build isomer lookup tables from method profile.
    # by_linear: analyte IS the linear name (e.g. "lr-PFOS" in _analytes)
    # by_reported: analyte IS the reported name (e.g. "PFOA" in _analytes)
    # The METHOD owns the surrogate -> analyte quantification link (§3). The
    # instrument's own `linked_is` column is the fallback, not the authority.
    _sur_map = _get_surrogate_map(_method)
    _is_mismatch: dict = {}

    def _quantifying_is(analyte_name, irow):
        """The surrogate this analyte is quantified against, as a keyword.

        Both sides are normalised before they are compared: a profile may hold
        a supplier code ("M8PFOA") where the instrument exports "13C8-PFOA" for
        the same compound. Returning the keyword also keeps the
        surrogate-failure lookup spelling-agnostic.
        """
        named = (_sur_map.get(analyte_name) or "").strip()
        members = _quantifying_members(_method, named) if named else []
        if named and members and members != [named]:
            # a composite: the value was calculated on the mean of its
            # members' areas only where the run quantified it so (a raw
            # run's row names the composite); an export naming one member
            # was not, which is a finding for review
            given = (getattr(irow, "linked_is", None) or "").strip()
            if given and given != named:
                _is_mismatch[analyte_name] = (
                    "averages " + _and_words(members),
                    keyword_for(given) or given)
            return named
        # an id no composite of the profile holds names no compound
        configured = (keyword_for(named) or None) if members else None
        reported = keyword_for(getattr(irow, "linked_is", None) or "") or None
        if configured and reported and configured != reported:
            # A method naming one surrogate while the instrument used another
            # is a finding for review, not something to resolve silently.
            _is_mismatch[analyte_name] = ("names " + configured, reported)
        return configured or reported

    def _sur_failed(linked_is, sample_name):
        """Whether the standard a result was quantified on failed in that
        injection: for a composite, any of its members (each is half the
        denominator, so either failure reaches the result)."""
        if not linked_is:
            return False
        return any((keyword_for(m) or m, sample_name) in sur_injections
                   for m in _quantifying_members(_method, linked_is) or [linked_is])

    def _role_of(value):
        return quantifying_role(_method, value, _std_roles)

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
        """Method-blank concentration to subtract, never from the blank
        itself: an MB compared against its own result would report as < LOD
        and hide the contamination the blank exists to show."""
        if role_of.get(sample_name) == "MB":
            return None
        return mb_conc.get(analyte)

    def _subtract_method_blank(result, qualifier, reported_name, iso_pair, compounds,
                               sample_name, fold=None):
        """(result, qualifier, amount subtracted or None). A summed analyte's
        blank is the sum of its components' blanks; what is left is judged
        against the printed RL (_bloq)."""
        names = ([iso_pair.get("linear")] + list(iso_pair.get("branched_list") or (
            [iso_pair["branched"]] if iso_pair.get("branched") else []))
            if iso_pair else [reported_name])
        blanks = [_blank_for(n, sample_name) for n in names if n]
        if iso_pair and all(b is None for b in blanks):
            blanks = [_blank_for(reported_name, sample_name)]
        got = [b for b in blanks if b is not None and b > 0]
        if not got:
            return result, qualifier, None
        blank = sum(got)
        left = result - blank
        if left <= 0:
            return None, QUALIFIER_LOD, blank
        rls = [getattr(compounds.get(n), "reporting_limit", None) for n in names if n]
        rl = next((r for r in rls if r is not None), None)
        return left, _bloq(left, qualifier, reported_name, rl, fold), blank

    def _sum_isomer_pair(pair, compounds, sample_name):
        """Return (result, qualifier, flags) for an lr+br isomer pair."""
        rep = pair["reported"]
        # linear + every branched peak (an analyte may integrate several)
        names = [pair.get("linear")] + list(pair.get("branched_list")
                                            or ([pair["branched"]] if pair.get("branched") else []))
        rows = [compounds.get(n) for n in names if n]

        # Fallback: if instrument exported the reported name instead of lr-/br- peaks
        if all(r is None for r in rows):
            direct = compounds.get(rep)
            if direct is not None:
                rows = [direct]  # treat as single-peak source

        if all(r is None for r in rows):
            return None, QUALIFIER_ND, []

        # An isomer left unquantified by its standard's deleted peak has lost
        # its number: a sum without it is understated and N.D. is false, so
        # the pair is not quantified either.
        if any(getattr(irow, "conc_qualifier", "") == QUALIFIER_NQ
               for irow in rows if irow is not None):
            return None, QUALIFIER_NQ, []

        total = 0.0
        blank_total = 0.0
        reporting_limit = None
        linked_is = None
        # An isomer the instrument reported as BLoQ contributes no number but
        # is still a detection: the pair is never N.D. because of it.
        any_bloq = any(getattr(irow, "conc_qualifier", "") == QUALIFIER_BLOQ
                       for irow in rows if irow is not None)
        any_aloq = any(getattr(irow, "conc_qualifier", "") == QUALIFIER_ALOQ
                       for irow in rows if irow is not None)

        for irow in rows:
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

        # an isomer above the range is a detection above it, whether or not
        # it carries a number: the pair is never N.D. or BLoQ because of it
        if total == 0.0 and not any_aloq:
            return None, (QUALIFIER_BLOQ if any_bloq else QUALIFIER_ND), []

        # < LOD: summed blank ≥ summed sample
        if blank_total > 0.0 and blank_total >= total and not any_aloq:
            return None, QUALIFIER_LOD, []

        flags_out: list[str] = []
        # BLoQ: the SUMMED result is below the reporting limit
        if any_aloq:
            # One isomer off the top of the curve makes the SUM an
            # extrapolation too, so the pair is reported from the dilution.
            qualifier_out = QUALIFIER_ALOQ
        else:
            # the SUM against the reported analyte's printed RL, never one
            # isomer's own limit
            qualifier_out = _bloq(total, "", rep, reporting_limit)
        for irow in rows:
            if irow is None:
                continue
            for issue in sorted(component_flags.get(
                    (sample_name, irow.compound_name), ())):
                tag = "{0}:{1}".format(irow.compound_name, issue)
                if tag not in flags_out:
                    flags_out.append(tag)
        if rep in _non_iso:
            flags_out.append(QUALIFIER_NC)
        if _sur_failed(linked_is, sample_name):
            flags_out.append("SUR")
        # above the range with no isomer giving a number: no sum to report
        return (total if total or not any_aloq else None), qualifier_out, flags_out

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
                    # "BLoQ" is a detection below the quantitation limit, not
                    # "not detected", nor is "N.Q.", a peak whose standard's
                    # peak was deleted, nor "ALoQ", a detection above the
                    # calibration range with no number to report.
                    qualifier = getattr(row, "conc_qualifier", "") or QUALIFIER_ND
                    if qualifier not in (QUALIFIER_BLOQ, QUALIFIER_NC, QUALIFIER_NQ, QUALIFIER_ALOQ):
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
                        else:
                            qualifier = _bloq(conc, "", analyte, row.reporting_limit)
                        if analyte in _non_iso:
                            flags.append(QUALIFIER_NC)
                        linked_is = _quantifying_is(analyte, row)
                        if _sur_failed(linked_is, sample_name):
                            flags.append("SUR")

            # A neat injection that read ABOVE the quantitation limit has no
            # usable number (off the top of the calibration curve): the
            # dilution supplies the reported value, and the over-range neat
            # reading is kept beside it so the substitution can be checked.
            source_injection = sample_name
            neat_result = None
            neat_qualifier = ""
            dil_factor = None
            # every row of one injection shares its acquisition time (and in
            # the isomer branch `row` is not this analyte's row at all)
            analysed_at = _acq(next(iter(compounds.values()), None))
            neat_analysed_at = ""
            meta = dil_meta.get(sample_name)
            # The diluted reading times the fold -- unless the method puts
            # results on the sample basis in the MS software, which then
            # applied the dilution too. With no usable fold the dilution is NOT
            # substituted: the neat stays ALoQ.
            dil_scale = (1.0 if _dil_in_software
                         else (meta.get("factor") if meta else None))
            # the lab's fold rule (Lab Workflow, Dilutions): with "only when
            # added" and no quantifying standard added, the reading already
            # is the undiluted one
            if meta and dil_scale and not _dil_in_software:
                # the reading is the undiluted one (power 0), once diluted
                # (1), or, linked through an internal standard not added
                # back, twice (2): dilution_routes.fold_power
                dil_scale = dil_scale ** dilution_routes.fold_power(
                    meta, _dil_settings, _role_of(_sur_map.get(reported_name)), _linked)
            if meta and QUALIFIER_ALOQ in (qualifier or "") and not dil_scale:
                logger.warning("Dilution %s of %s has no usable fold; the neat "
                               "ALoQ reading is kept", meta.get("injection"), sample_name)
            if meta and dil_scale and QUALIFIER_ALOQ in (qualifier or ""):
                drow = (dil_rows.get(sample_name) or {}).get(reported_name)
                if drow is None and iso_pair:
                    dres, dqual, dflags = _sum_isomer_pair(
                        iso_pair, dil_rows.get(sample_name) or {}, sample_name)
                    if dres is not None:
                        neat_result, neat_qualifier = result, qualifier
                        result, qualifier, flags = dres * dil_scale, dqual, dflags
                        source_injection = meta["injection"]
                        dil_factor = meta.get("factor")
                        neat_analysed_at = analysed_at
                        analysed_at = _acq(next(iter((dil_rows.get(sample_name) or {}).values()), None))
                elif drow is not None and reported_conc(drow) is not None:
                    neat_result, neat_qualifier = result, qualifier
                    flags = list(flags)
                    result = reported_conc(drow) * dil_scale
                    qualifier = (drow.conc_qualifier
                                 if drow.conc_qualifier != QUALIFIER_ALOQ else "")
                    source_injection = meta["injection"]
                    dil_factor = meta.get("factor")
                    neat_analysed_at = analysed_at
                    analysed_at = _acq(drow)
                if source_injection != sample_name:
                    # the diluted result against the RL times its fold, as
                    # the certificate prints it
                    qualifier = _bloq(result, qualifier, reported_name, fold=dil_factor)
                # a qualifier the analyst deleted on the dilution that
                # supplies the value confirms nothing, as on a neat injection
                members = [reported_name] + ([iso_pair.get("linear")] + list(
                    iso_pair.get("branched_list") or ([iso_pair["branched"]] if iso_pair.get("branched") else []))
                    if iso_pair else [])
                if (source_injection != sample_name and QUALIFIER_NC not in flags
                        and any(qualifiers_deleted((dil_rows.get(sample_name) or {}).get(n)) for n in members
                                if (dil_rows.get(sample_name) or {}).get(n) is not None)):
                    flags.append(QUALIFIER_NC)
                # a result from a re-spiked dilution is a method modification:
                # marked for the QAO's qualifier when the method qualifies it
                if (source_injection != sample_name
                        and dilution_routes.qualifies_respike(meta, _dil_settings)
                        and dilution_routes.RESPIKE_FLAG not in flags):
                    flags.append(dilution_routes.RESPIKE_FLAG)

            # a value from a peak split from its co-eluting partner (the
            # pair's fit, a failed fit, a drop or skim drawn on the pair) is
            # an estimate: marked for the QAO's co-elution qualifier, judged
            # on the injection that supplies the value and, for a summed
            # analyte, on each of its peaks
            supplied = (dil_rows.get(sample_name) or {}) if source_injection != sample_name else compounds
            peaks_of = [reported_name] + ([iso_pair.get("linear")] + list(
                iso_pair.get("branched_list") or ([iso_pair["branched"]] if iso_pair.get("branched") else []))
                if iso_pair else [])
            if (result is not None and COELUTION_FLAG not in flags
                    and any(coelution_split(supplied.get(n)) for n in peaks_of if supplied.get(n) is not None)):
                flags.append(COELUTION_FLAG)
            # a value from a quantifier peak separated by curve fitting, on
            # one injection or on all, is an estimate: marked for the QAO's
            # fitted-estimate qualifier, judged as the co-elution mark is and
            # apart from it, so a peak both split and fitted carries both
            if (result is not None and FITTED_FLAG not in flags
                    and any(fitted_estimate(supplied.get(n)) for n in peaks_of if supplied.get(n) is not None)):
                flags.append(FITTED_FLAG)

            # above the calibration range and reported from no dilution: the
            # bound the certificate prints it above, the highest top among
            # its rows that read ALoQ (each a true lower bound of a sum)
            range_top = None
            if qualifier == QUALIFIER_ALOQ and source_injection == sample_name:
                tops = [compounds[n].range_top for n in peaks_of
                        if compounds.get(n) is not None and compounds[n].conc_qualifier == QUALIFIER_ALOQ
                        and getattr(compounds[n], "range_top", None) is not None]
                range_top = max(tops) if tops else None

            # FDA §10.2(4): PFBA and PFPeA have one usable MS/MS transition, so
            # their identity cannot be confirmed by ion ratio the way every other
            # analyte's is. A POSITIVE therefore requires confirmation by an
            # orthogonal technique (LC-HRMS, agreeing within
            # confirm_pct_diff_max).
            #
            # It belongs HERE and not in the run queue: detection is decided in
            # this function, and auto_evaluate() runs BEFORE build_summary (the
            # summary consumes batch.is_results, which auto_evaluate produces).
            # One question, one answer.
            #
            # Which analytes need it comes from the METHOD's confirmation_rule
            # (single_transition_analytes): method-conditional by data, never
            # by an `if method ==` here.
            if (_confirm_on and _conf_profile is not None
                    and qualifier not in (QUALIFIER_ND, QUALIFIER_LOD)):
                # Detected. BLoQ and ALoQ count: both are detections, one below
                # and one above the quantitation range, and §10.2(4) is about
                # identification rather than quantitation.
                prompt = single_transition_confirm_needed(
                    _conf_profile, reported_name, True)
                if prompt:
                    flags.append(QUALIFIER_CONF)
                    batch.confirmations_required.append({
                        "sample_injection": sample_name,
                        "analyte": reported_name,
                        "qc_type": role_of.get(sample_name, "Sample"),
                        "prompt": prompt,
                    })

            # The method blank, subtracted when the method says so (off by
            # default). The blank is on the sample basis, like the result (a
            # dilution's too, scaled above), so the subtraction comes last. Nothing left reads "< LOD"; a
            # remainder under the RL reads BLoQ.
            blank_subtracted = None
            if (_subtract_blank and result is not None
                    and qualifier not in (QUALIFIER_ND, QUALIFIER_LOD)):
                result, qualifier, blank_subtracted = _subtract_method_blank(
                    result, qualifier, reported_name, iso_pair, compounds, sample_name, dil_factor)

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
                analysed_at=analysed_at,
                neat_analysed_at=neat_analysed_at,
                blank_subtracted=blank_subtracted,
                flags=flags,
                range_top=range_top if qualifier == QUALIFIER_ALOQ else None,
                # the instrument wrote BLoQ and gave no number for this
                # result or one of its peaks (an imported row, never a raw
                # run's own reading): it waits on the reviewer's reason
                no_number=(source_injection == sample_name
                           and any(instrument_gave_no_number(compounds.get(n)) for n in peaks_of)),
            ))

    # A method that names one quantifying surrogate while the instrument
    # reported another is a review finding, not something to resolve silently
    # in either direction. Tagged on the affected rows so it reaches Data
    # Review rather than only the worker log.
    if _is_mismatch:
        for analyte, (configured, reported) in sorted(_is_mismatch.items()):
            logger.warning(
                "Surrogate map disagrees with the instrument for %s: method "
                "profile %s, %s reported %s",
                analyte, configured, _method, reported)
        for row in summary:
            pair = _is_mismatch.get(row.analyte)
            if pair:
                row.is_mismatch = ("method profile {0}; instrument "
                                   "reported {1}".format(*pair))
        # Also raised as a QC flag so it reaches Data Review and the QC Review
        # Report through the same channel as every other reviewer finding.
        for analyte, (configured, reported) in sorted(_is_mismatch.items()):
            batch.qc_flags.append(QCFlag(
                source="Surrogate Map",
                analyte=analyte,
                injection_name="",
                value=reported,
                issue="(ISMAP) method profile {0}; instrument reported "
                      "{1}".format(configured, reported),
            ))

    batch.summary = summary
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# Main pipeline
# ─────────────────────────────────────────────────────────────────────────────

def quantifying_role(method_id, value, roles):
    """The role ({keyword: role}, the method's grid) of the standard a
    surrogate-map value names: a composite's members' one role (they share
    it), None when there is none."""
    found = set(roles.get(keyword_for(m) or m or "")
                for m in _quantifying_members(method_id, (value or "").strip()))
    return found.pop() if len(found) == 1 else None


def _and_words(names):
    """"A", "A and B", "A, B and C"."""
    names = list(names)
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1] if names else ""


def _acq(row):
    """An injection row's acquisition time as ISO text, or ""."""
    when = getattr(row, "acquisition_datetime", None) if row is not None else None
    return when.isoformat() if when else ""


def _iso(value):
    """A sidecar timestamp ("YYYY-MM-DDTHH:MM:SSZ") as a datetime, or None."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


class ReimportRefused(RuntimeError):
    """A run delivered for a worksheet that takes no further import: the
    watcher records the refusal and moves on, never retrying it."""


# a worksheet in one of these states takes no run again: verified or
# published, its record stands; rejected, its retest goes on a new worksheet
REIMPORT_CLOSED_STATES = ("verified", "published", "rejected")


def apply_identity(run_roles, identity):
    """(roles, levels, applied) with a reviewer's identity corrections
    (senaite.pfas.injection_identity.overlay, the run manifest's
    "identity") over the run's roles: each corrected injection takes its
    corrected role, a CCV its fixed level ({injection: "low" |
    "standard"}); `applied` is {injection: its correction}, what the run
    records it judged with."""
    roles = dict(run_roles or {})
    levels, applied = {}, {}
    for inj, c in sorted((identity or {}).items()):
        if not isinstance(c, dict) or not c.get("role"):
            continue
        roles[inj] = c["role"]
        if c.get("level") in ("low", "standard"):
            levels[inj] = c["level"]
        applied[inj] = dict(c)
    if applied:
        logger.info("Identity corrected at review: %s", ", ".join(
            "%s -> %s" % (k, v.get("to") or v.get("role")) for k, v in sorted(applied.items())))
    return roles, levels, applied


# the role of an injection a reviewer took out of the run
NOT_JUDGED = "NotJudged"


def drop_not_judged(rows, applied):
    """The rows less those of an injection corrected to Not judged: no QC,
    curve check or result uses it."""
    out = set(inj for inj, c in (applied or {}).items() if (c or {}).get("role") == NOT_JUDGED)
    if not out:
        return rows
    return [r for r in rows if r.injection_name not in out]


def not_judged(names):
    """{injection: a Not judged correction} for `names`: what drop_not_judged
    takes them out by, with no identity correction recorded for them."""
    return dict((n, {"role": NOT_JUDGED}) for n in names or ())


def withhold(member_map, spike_map):
    """(member_map, spike_map, withheld): the extraction batch's members
    withheld for re-extraction (each marked "withheld" by the record in
    force, under its name in force, its issued names and its re-injections)
    taken out of both maps; `withheld` their names. Their rows are dropped
    as a Not judged injection's are: nothing of theirs is judged, filed or
    pushed."""
    held = sorted(k for k, v in (member_map or {}).items() if (v or {}).get("withheld"))
    members = dict((k, v) for k, v in (member_map or {}).items() if k not in held)
    spikes = dict((k, v) for k, v in (spike_map or {}).items() if k not in held)
    return members, spikes, held


def follow_aliases(spike_map, member_map, present):
    """The spike record with each parent and LFSM it names given as the
    name the run carries: a member an amendment renamed ran under its
    issued name (a member map key "alias_of" its name in force)."""
    ran_as = {}
    for k, v in (member_map or {}).items():
        to = (v or {}).get("alias_of")
        if to and k in present and to not in present:
            ran_as[to] = k
    out = {}
    for k, v in (spike_map or {}).items():
        v = dict(v or {})
        for f in ("parent", "lfsm"):
            if v.get(f) in ran_as:
                v[f] = ran_as[v[f]]
        out[k] = v
    return out


def applied_amendments(manifest_ids, member_ids):
    """The extraction corrections a run is judged with: those the members
    it read carry and the run manifest names, both. A worker that read
    either answer without them applied none, so release keeps waiting."""
    return sorted(set(manifest_ids or ()) & set(member_ids or ()))


def _verdict_rows(batch):
    """The run's QC verdict rows, as they are stored (qc_store._qc_rows);
    [] when they cannot be formed (the store reports that itself)."""
    from .qc_store import _qc_rows
    try:
        return _qc_rows(batch)
    except Exception as exc:                                # noqa: BLE001
        logger.warning("identity check: the QC rows could not be formed: %s", exc)
        return []


# the corrected roles no verdict is owed for
_IDENTITY_UNJUDGED = ("Sample", NOT_JUDGED)


def identity_gaps(applied, verdicts, method_id=""):
    """An unevaluated QC result for each injection a reviewer corrected to a
    QC role that the run gave no verdict as that role (`verdicts`, the QC
    rows: an injection is named whole in a row's qc_level): it holds
    release and names why, never a QC silently unjudged."""
    judged = set()
    for v in verdicts or []:
        qt = (v.get("qc_type") or "").upper()
        for token in re.split(r"[\s|]+", v.get("qc_level") or ""):
            if token:
                judged.add((qt, token))
    out = []
    for inj, c in sorted((applied or {}).items()):
        role = (c or {}).get("role") or ""
        if not role or role in _IDENTITY_UNJUDGED or (role.upper(), inj) in judged:
            continue
        out.append({"qc_type": role, "analyte": "", "method_id": method_id,
                    "reason": "%s was corrected to %s at review, but the run gave it no %s verdict "
                              "(no expected concentration in the export, or the method does not "
                              "judge %s): it is not judged" % (inj, role, role, role)})
    return out


def reimport_refusal(worksheet, worksheet_id) -> str:
    """Why a run cannot be imported into this worksheet (SENAITE's record
    of it, with its review_state), or "" when it can."""
    state = (worksheet or {}).get("review_state") or ""
    if state not in REIMPORT_CLOSED_STATES:
        return ""
    if state == "rejected":
        return ("%s is rejected: a run is not imported into it again; the retest goes on a "
                "new worksheet" % worksheet_id)
    return ("%s is %s: a run is not imported again once its worksheet is verified; import it "
            "on a new worksheet" % (worksheet_id, state))


# the worksheet's batch report, and an earlier import's, kept beside it
BATCH_REPORT = "Batch Report"
BATCH_REPORT_SUPERSEDED = "Batch Report superseded"


def attach_batch_report(senaite, ws_uid, report_path, superseded=False):
    """Attach the run's batch report to its worksheet. The worksheet's
    attachment is the record: once SENAITE holds it, the copy written to
    the output folder is removed, so one copy stands. Kept when the upload
    did not give back an attachment (the folder copy is then the only one).
    `superseded`, another import's rows were kept as superseded: its report
    is kept too, relabelled "Batch Report superseded"; the same import
    processed again (an analyst's raw edit) replaces its own report.
    Returns the attachment's uid, or None."""
    uid = senaite.attach_file(ws_uid, report_path, BATCH_REPORT,
                              keep_as=BATCH_REPORT_SUPERSEDED if superseded else "")
    if not uid:
        logger.warning("The batch report stays at %s: it was not attached to "
                       "the worksheet.", report_path)
        return None
    try:
        Path(report_path).unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.error("The attached batch report %s could not be removed from "
                     "the output folder: %s", report_path, exc)
    return uid


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
    senaite_batch_id  the SENAITE Batch this run belongs to, if any. Never the
                      worksheet id: a Batch is looked up, never created.
    """
    # ── Run parameters from the extraction sidecar ───────────────────────────
    # The sidecar fills in batch_id, analyst and matrix before the profile
    # reload below; an explicit argument always wins.
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
            "arguments.", Path(csv_path).name)

    # A worksheet verified, published or rejected takes no run again: refused
    # before anything is read or written. SENAITE out of reach raises here
    # like any other push failure, and the watcher retries.
    if senaite is not None and batch_id:
        why = reimport_refusal(senaite.find_worksheet(batch_id), batch_id)
        if why:
            raise ReimportRefused(why)

    # The method profiles from the exported JSON, so manager changes in the
    # SENAITE UI take effect without a worker restart; senaite_batch_id (from
    # an explicit argument or the sidecar above) also applies that batch's
    # resolved (project-aware) criteria to its method's profile.
    reload_from_profiles(batch_id=senaite_batch_id or None)
    # a run is judged by ITS method or not at all: refuse, never fall back
    # to another method's criteria
    if not method_id:
        raise RuntimeError(
            "No method for %s: neither the call nor the extraction sidecar names "
            "one, so the run cannot be judged. Build the run in the Run Builder "
            "(its sidecar carries the method) or pass method_id." % Path(csv_path).name)
    from .method_profiles import _profile_data_cache, resolve_method_id
    resolved = resolve_method_id(method_id)
    if resolved is not None:
        method_id = resolved                 # an alias ("537.1") -> the method's id
    from .method_profiles import profile_stale
    if profile_stale(method_id):
        raise RuntimeError(
            "The exported method profile for %s predates the Engine settings, so "
            "the run is not judged with them silently off. Restart SENAITE (it "
            "migrates and re-exports the profiles), then run the batch again."
            % method_id)
    if not profile_configured(method_id):
        # never judge with criteria the lab did not set
        raise RuntimeError(
            "No exported method profile for %s: the export (%s) holds %s. Save "
            "the method's profile in SENAITE (Method Profiles) so it is exported, "
            "then run the batch again."
            % (method_id, os.environ.get("PFAS_PROFILES_PATH",
                                         "/data/qc/method_profiles.json"),
               ", ".join(sorted(_profile_data_cache)) or "no method"))
    # the compounds are the services' library as SENAITE exported it: no
    # export, an ambiguous one, or a compound the method names that it does
    # not hold is refused, never looked up in another table
    from .analyte_alias import library_refusal
    why = library_refusal(method_id, _profile_data_cache.get(method_id))
    if why:
        raise RuntimeError(why)

    csv_path = Path(csv_path)
    from .importer import set_member_roles, set_level_overrides
    set_member_roles({})                 # a run's member roles never leak into the next
    set_level_overrides({})
    identity_applied = {}                # {injection: the correction in force, as applied}
    amendments_applied = []              # the extraction corrections the run is judged with
    withheld = []                        # the members withheld for re-extraction
    member_map = {}                      # {injection: {"sample_uid", "role"}}
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Import — resolve column-mapping profile from Import Studio REST bridge
    #    then load the CSV using that profile.  Strict mode: if SENAITE is
    #    offline or no profile is saved, refuse with an informative error.
    import_profile = None
    # a raw run (its record and one mzML per injection) is integrated here,
    # with the method's Integration settings: no import layout reads it
    raw = is_raw_run(csv_path)
    if senaite is not None and not raw:
        # SENAITE identifies the instrument; the pipeline never detects the
        # vendor itself (one detector, one answer).
        # The file's first lines and the run's instrument: SENAITE matches
        # them against the saved import layouts (each read with its own
        # options) and answers the one layout that fits, or a refusal.
        # Raises on a SENAITE connectivity failure (no fallback).
        import_profile = senaite.get_instrument_profile(
            head=file_head(csv_path),
            instrument_uid=(sidecar or {}).get("instrument_uid") or "")
        if "error" in import_profile:
            raise ImportError(import_profile["error"])
        logger.info("Using the import layout %s for %s",
                    import_profile.get("name") or import_profile.get("resolved_vendor_key", "?"),
                    csv_path.name)

    raw_traces = []                      # a raw run's chromatograms, kept for review
    acid_basis = list((sidecar or {}).get("acid_basis_analytes") or [])
    rows = load_rows(csv_path, import_profile, method_id, traces=raw_traces, acid_basis=acid_basis)
    refuse_unreadable(rows, import_profile, csv_path)
    logger.info("Loaded %d rows / %d injections from %s",
                len(rows), len(group_by_injection(rows)), csv_path.name)
    this_file = set(r.injection_name for r in rows)     # what the plan check compares
    # A supplementary run (what review asked for) ADDS to the
    # extraction batch's earlier runs: they are processed together, so a
    # dilution meets its neat reading and the worksheet's QC is not replaced.
    for earlier in (sidecar.get("supplementary_of") or []) if sidecar else []:
        # an earlier run imported is in the archive (instrument_files)
        found = _addon("instrument_files").locate(str(csv_path.parent), earlier)
        if found is None:
            raise RuntimeError("supplementary run %s: the earlier run %s is not in %s"
                               % (csv_path.name, earlier, csv_path.parent))
        path = Path(found)
        rows = load_rows(path, import_profile, method_id, traces=raw_traces, acid_basis=acid_basis) + rows
        logger.info("With the earlier run %s: %d rows", earlier, len(rows))
    if (import_profile or {}).get("labelled_from_columns"):
        made = labelled_rows(rows, method_id)
        rows = rows + made
        logger.info("%d labelled-standard row(s) made from the analytes' IS columns", len(made))

    # Dilution map — needed before the name check below.
    #
    # The dilution map comes from the batch's FM-ENV-003 extraction log, which
    # is the only place the parent/factor relationship is recorded. Empty for
    # a batch that logged none.
    dilution_map = {}
    spike_map = {}
    field_blanks, field_duplicates, trip_blanks = [], [], []
    mxb_references = {}
    logged_amounts = {}
    if senaite is not None and not senaite_batch_id and not batch_id:
        # (the worksheet id is enough: it is the extraction batch)
        # Without either id the extraction pedigree is skipped: matrix spikes
        # and dilutions vanish while the run looks complete, so say so.
        logger.warning(
            "senaite_batch_id was not supplied, so FM-ENV-003 is not read: "
            "matrix spikes and dilutions will be absent, LFSM/LFSMD cannot be "
            "evaluated, and dilution injections will be reported as samples in "
            "their own right. Pass the SENAITE Batch id to use the pedigree.")
    if senaite is not None and (senaite_batch_id or batch_id):
        # the worksheet is the extraction batch; its id is the run's
        prep = senaite.get_batch_dilutions(senaite_batch_id, worksheet_id=batch_id or "") or {}
        spike_map = prep.pop("_spikes", {}) or {}
        # the extraction batch's members: what each LIMS-issued injection is,
        # and a sample's SENAITE uid
        member_map = prep.pop("_members", {}) or {}
        # a member withheld for re-extraction is judged as nothing: out of
        # the members and the spikes, its rows dropped below
        member_map, spike_map, withheld = withhold(member_map, spike_map)
        prep_amendments = prep.pop("_amendments", []) or []
        # every PLANNED injection's role, as the Run Builder built the row
        # (calibrators, ICV/QCS, CCV/CCC, solvent blank...), so a name may use
        # the method's own terms; the batch's members' own record wins.
        # An unplanned injection still falls back to the
        # name tokens and is reported as unplanned below.
        run_manifest = senaite.get_run_manifest(senaite_batch_id, worksheet_id=batch_id or "") or {}
        run_roles = dict(run_manifest.get("roles") or {})
        run_roles.update(dict((k, (v or {}).get("role") or "Sample") for k, v in member_map.items()))
        # a reviewer's identity correction (Data Review) wins over both
        run_roles, levels, identity_applied = apply_identity(run_roles, run_manifest.get("identity"))
        set_level_overrides(levels)
        field_blanks = sorted(k for k, v in member_map.items() if (v or {}).get("field_qc") == "FRB")
        field_duplicates = sorted(k for k, v in member_map.items() if (v or {}).get("field_qc") == "FD")
        trip_blanks = sorted(k for k, v in member_map.items() if (v or {}).get("field_qc") == "TB")
        set_member_roles(run_roles)
        # an injection corrected to Not judged keeps its record (its
        # provenance below) but no QC or result uses it
        rows = drop_not_judged(rows, identity_applied)
        rows = drop_not_judged(rows, not_judged(withheld))
        # the extraction corrections the members above carry and the manifest names
        amendments_applied = applied_amendments(run_manifest.get("amendments"), prep_amendments)
        # a matrix blank's lot reference values (Matrix blanks)
        mxb_references = dict((k, v["reference"]) for k, v in member_map.items()
                              if (v or {}).get("reference"))
        # a re-injection replaces the injection it repeats
        # (only where the re-injection is among the rows: a run uploaded
        # without it keeps the original)
        present = set(r.injection_name for r in rows)
        replaced = set((v or {}).get("replaces") for k, v in member_map.items()
                       if (v or {}).get("replaces") and k in present)
        if replaced:
            rows = [r for r in rows if r.injection_name not in replaced]
            logger.info("Re-injections replace %s", ", ".join(sorted(replaced)))
            # a spike or duplicate made from a re-injected sample reads the
            # re-injection as its parent
            alias = dict(((v or {}).get("replaces"), k) for k, v in member_map.items()
                         if (v or {}).get("replaces") and k in present)
            spike_map = dict((k, dict(v, parent=alias.get(v.get("parent"), v.get("parent"))))
                             for k, v in spike_map.items())
        # a parent or LFSM an amendment renamed ran under its issued name
        spike_map = follow_aliases(spike_map, member_map, present)
        logged_amounts = prep.pop("_samples", {}) or {}
        dilution_map = prep
        if spike_map:
            logger.info("Extraction pedigree records %d matrix spike(s): %s",
                        len(spike_map),
                        ", ".join("%s <- %s @ %s %s" % (
                            v.get("parent"), k,
                            v.get("spike", v.get("spike_ppt")),
                            v.get("spike_unit") or ("ppt" if v.get("spike_ppt") else "(method level)"))
                                  for k, v in sorted(spike_map.items())))
        if dilution_map:
            logger.info("FM-ENV-003 records %d dilution(s): %s",
                        len(dilution_map),
                        ", ".join("%s <- %s" % (v.get("parent"), k)
                                  for k, v in sorted(dilution_map.items())))

    # Convert extract concentrations to the reported sample basis (natives
    # only; IS/surrogates are judged on their own response and instrument
    # Total rows are sums of natives). HOW is the method's choice
    # (sample_correction.py): nominal factor, already done in the MS
    # software, or back-calculated here from each sample's logged amount and
    # final volume -- which is why this runs after the dilution map is known
    # (a dilution takes its parent sample's amounts).
    sample_amounts = logged_amounts
    correction_fallbacks: list = []
    rows = apply_extract_corrections(rows, method_id, matrix,
                                     sample_amounts=sample_amounts,
                                     dilutions=dilution_map,
                                     fallbacks=correction_fallbacks,
                                     acid_basis=(sidecar or {}).get("acid_basis_analytes"))
    # spike levels entered before the amount adjustment: each spiked
    # portion's expected level is scaled by nominal / actual amount when its
    # result is on the actual portion (per-sample correction)
    from .method_profiles import get_spike_basis, get_nominal_amount, spike_scale
    spike_basis = get_spike_basis(method_id) if method_id else ""
    spike_scales = {}
    if spike_basis == "before" and _get_sample_correction(method_id) in ("lims", "instrument"):
        nominal, nominal_unit = get_nominal_amount(method_id, matrix)
        for inj in set(r.injection_name for r in rows):
            ratio = spike_scale(nominal, nominal_unit, (sample_amounts or {}).get(inj))
            if ratio is not None:
                spike_scales[inj] = ratio
    else:
        spike_basis = ""


    # 2. Injection-name check: what matters is whether an injection
    # corresponds to something the LIMS knows about (the run plan; a sample
    # injection must resolve to a sample). A name pattern miss is logged at
    # debug level only: Run Builder names are issued by this system.
    planned = []
    if senaite is not None and (senaite_batch_id or batch_id):
        planned = (senaite.get_run_manifest(senaite_batch_id, worksheet_id=batch_id or "") or {}).get(
            "planned") or []
        # a member withheld for re-extraction ran and is dropped: not a
        # planned injection missing from the run
        planned = [p for p in planned if p not in withheld]
    if planned:
        actual = this_file                   # this file, not the earlier runs it joins
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
        if inj_name in member_map:
            continue                     # the extraction batch names its sample
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
        acid_basis=list((sidecar or {}).get("acid_basis_analytes") or []),
        spikes=spike_map,
        field_blanks=field_blanks,
        field_duplicates=field_duplicates,
        trip_blanks=trip_blanks,
        mxb_references=mxb_references,
        spike_basis=spike_basis,
        spike_scales=spike_scales,
        # the marked blank AS RUN: a re-injection carries the mark and the
        # original it replaced is no longer among the rows
        subtraction_blank=next((k for k, v in sorted(member_map.items())
                                if (v or {}).get("subtract")
                                and k in set(r.injection_name for r in rows)), ""),
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

    # a standard's row keeps its number and loses the instrument's ALoQ or
    # BLoQ before it is judged
    standard_tokens(batch.injections)
    # a quadratic's sample below its lowest calibrator has a number only at
    # or above the MDL, decided before the QC engine judges the numbers
    raw_below_mdl(batch.injections, method_id, matrix, batch.acid_basis)
    queue = RunQueue(batch, review_plan, method_id=method_id)
    queue.auto_evaluate()
    # the run against its plan: each difference holds release until a
    # reviewer clears it
    from .run_shape import problems as _shape_problems, QC_TYPE as _SHAPE
    for reason in _shape_problems(planned, rows, spike_map):
        batch.unconfigured.append({"qc_type": _SHAPE, "analyte": "", "reason": reason,
                                   "method_id": method_id})
    # the instrument's clock against the run's order: judged in the queue
    # (run_queue 9a) as a bracketing failure of each injection out of order.
    # Samples corrected with the NOMINAL factor: flagged after the engine, so
    # the flag informs the reviewer and changes no automatic verdict.
    batch.correction_fallbacks = list(correction_fallbacks)
    for inj in correction_fallbacks:
        batch.qc_flags.append(QCFlag(
            source="Sample correction", analyte="(natives)", injection_name=inj,
            value="nominal matrix factor", issue="(NOM)",
            check_kind="sample_correction"))
    logger.info("QC engine raised %d flags; %d checks pending review",
                len(batch.qc_flags), len(queue.pending()))

    # 4b. Above the calibration range: the platform's own judgement (rule
    # switch over_range), so the summary reports the dilution or ALoQ
    batch.qc_flags.extend(over_range(batch.injections, method_id, matrix))
    # a raw run's result above the highest calibrator still on its own curve
    batch.qc_flags.extend(raw_range(batch.injections, method_id))
    # every other ALoQ (the instrument's own word): the top of its range
    range_tops(batch.injections, method_id, matrix)
    # a raw run's native the analyst left unquantified by deleting its
    # isotope standard's peak: release waits for it
    batch.qc_flags.extend(raw_is_deleted(batch.injections))
    # what each native was quantified on and the method's linked response
    # ratio, for the readout; a raw result whose linked ratio could not be
    # formed: release waits for it
    tag_quantitation(batch.injections, method_id)
    batch.qc_flags.extend(ratio_held(batch.injections))
    # a diluted field sample whose surrogate recovery the method has not
    # said how to take: flagged, not held
    batch.qc_flags.extend(dilution_recovery_flags(batch.injections, method_id, dilution_map))

    # 5. Summary
    build_summary(batch)
    # the final values' chains, from the summary just built (value provenance)
    from . import provenance as _prov
    from .method_profiles import get_profile as _gp
    try:
        _prov_profile = _gp(method_id) if method_id else None
        _prov.record_summary(batch, _prov_profile)
        _prov.record_file(batch, csv_path.name, import_profile)
        _prov.record_identity(batch, identity_applied)
        _prov.record_amendments(batch, amendments_applied)
    except Exception as exc:                                # noqa: BLE001
        logger.exception("value provenance of the summary could not be recorded for %s", batch.batch_id)
        batch.unconfigured.append({"qc_type": "Provenance", "analyte": "", "method_id": method_id,
                                   "reason": "the final values' provenance could not be recorded (%s)" % exc})

    # a check standard a reviewer corrected the identity of that gave no
    # verdict (no expected concentration) is never left silently unjudged
    _gaps = identity_gaps(identity_applied, _verdict_rows(batch), method_id)
    if _gaps:
        if not hasattr(batch, "unconfigured"):
            batch.unconfigured = []
        batch.unconfigured.extend(_gaps)

    # 5a. FDA §10.2(4). build_summary has just decided what was detected, so the
    # confirmation checks can now be settled — PENDING where a single-transition
    # positive genuinely owes an LC-HRMS confirmation, AUTO_PASS where §10.2(4)
    # does not apply. Has to follow build_summary and therefore cannot be part of
    # auto_evaluate; see RunQueue.resolve_confirmations.
    n_conf = queue.resolve_confirmations()
    if n_conf:
        logger.warning(
            "FDA §10.2(4): %d single-transition positive(s) require LC-HRMS "
            "confirmation before the identification can be reported as "
            "confirmed — see the identity_confirmation review checks", n_conf)

    # 5a. Validation: one side of a run is reported, the other is kept for
    # the comparison -- its rows only, nothing judged, stored or pushed
    # the results source the run was built / uploaded under, else the method's
    mode = (sidecar or {}).get("integration_mode") or integration_mode(method_id)
    side = comparison_side(raw, mode, supplementary=bool((sidecar or {}).get("supplementary_of")))

    # 5a'. A run imported again before it is verified keeps the earlier
    # import's rows of its side as superseded copies; processing the same
    # import again (an analyst's raw edit) keeps nothing. Rows that cannot be
    # kept are not replaced: the import fails here, before any store is
    # written, and is tried again
    from .injection_store import begin_import
    kept = begin_import(getattr(batch, "batch_id", "") or "", csv_path, side=side or "reported", raw=bool(raw))
    if kept:
        logger.info("%s: the earlier import's rows kept as superseded: %s", csv_path.name,
                    ", ".join("%s %d" % kv for kv in sorted(kept.items()) if kv[1]))

    if side:
        from .injection_store import injection_dicts, persist_alt_results
        n_alt = persist_alt_results(getattr(batch, "batch_id", "") or "", side, injection_dicts(batch))
        if raw:
            from .injection_store import persist_raw_traces
            persist_raw_traces(getattr(batch, "batch_id", "") or "", raw_traces)
        logger.info("%s: %d %s row(s) kept for the comparison, not reported", csv_path.name, n_alt, side)
        return batch, queue, None

    # 5b. Persist per-injection detail for the multi-page Results Review.
    try:
        from .injection_store import persist_injection_results
        n_inj = persist_injection_results(batch)
        logger.info("Persisted %d per-injection rows to injection_results", n_inj)
    except sqlite3.Error as e:
        logger.error("injection_results persist failed: %s", e)
    try:
        # the side now reported: its rows kept apart under an earlier source go
        from .injection_store import persist_alt_results
        persist_alt_results(getattr(batch, "batch_id", "") or "", "raw" if raw else "vendor", [])
    except sqlite3.Error as e:
        logger.error("alt_results not cleared: %s", e)
    if raw:
        try:
            from .injection_store import persist_raw_traces
            n_tr = persist_raw_traces(getattr(batch, "batch_id", "") or "", raw_traces)
            logger.info("Persisted %d raw traces", n_tr)
        except sqlite3.Error as e:
            logger.error("raw traces persist failed: %s", e)

    # 5c. Persist the QC verdicts and calibration curves: Data Review's QC
    # Summary gate and the control charts read these.
    try:
        from .qc_store import persist_qc_results, persist_calibrations, persist_provenance
        n_qc = persist_qc_results(batch)
        n_cal = persist_calibrations(batch)
        # a new import kept what it replaced itself (begin_import): only a
        # processing of the same import keeps its ion-ratio records
        n_prov = persist_provenance(batch, reprocess=not kept)
        logger.info("Persisted %d QC results, %d calibration curves and %d provenance records",
                    n_qc, n_cal, n_prov)
    except sqlite3.Error as e:
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
        # When the extraction happened, not when the worker read the file.
        ext_log.started = _iso(data.get("started")) or ext_log.started
        ext_log.completed = _iso(data.get("completed"))
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
            # The worksheet is the run's home in SENAITE, and
            # the only container besides Client that accepts an Attachment.
            ws = senaite.find_worksheet(batch.batch_id)
            ws_uid = ws["uid"] if ws else ""
            if not ws:
                logger.warning(
                    "No SENAITE Worksheet %r — the report cannot be attached "
                    "and Data Review will not find this run.", batch.batch_id)

            # Never invent a Batch: look up the one named, and say so if it is
            # missing.
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
                attach_batch_report(senaite, ws_uid, report_path,
                                    superseded=bool(kept and any(kept.values())))
                if extraction_log_path:
                    senaite.attach_file(ws_uid, extraction_log_path,
                                        "Extraction Log")
            # Bind each summary row to its SENAITE sample: the injection name
            # is the client's own name for the sample (ClientSampleID); an
            # embedded StarLIMS id is the fallback.
            pushed = locked = 0
            unmatched_samples = set()
            unmatched_analytes = set()
            sample_cache: dict = {}
            lookup_notes: dict = {}      # injection -> why no sample was chosen
            push_rows = []               # the push log (push_log.py)
            row_by_inj = {}
            for r in (batch.injections or []):
                row_by_inj.setdefault(r.injection_name, r)
            for s in batch.summary:
                inj = s.sample_injection
                if inj not in sample_cache and (member_map.get(inj) or {}).get("sample_uid"):
                    # the LIMS issued this name for this sample
                    sample_cache[inj] = {"uid": member_map[inj]["sample_uid"]}
                    lookup_notes[inj] = ""
                if inj not in sample_cache:
                    found = senaite.find_sample_by_client_sample_id(inj, buid)
                    lookup_note = getattr(senaite, "last_lookup", "") or ""
                    if not found and not lookup_note:
                        v = validate_injection_name(inj)
                        if v.get("starlims_id"):
                            found = senaite.find_sample_by_starlims(
                                v["starlims_id"])
                    sample_cache[inj] = found
                    lookup_notes[inj] = lookup_note
                sample = sample_cache[inj]
                if not sample:
                    if (member_map.get(inj) or {}).get("role") not in (None, "", "Sample"):
                        continue         # a QC member of the batch: not a client sample
                    unmatched_samples.add(inj)
                    # only a field sample is expected to be a SENAITE sample:
                    # QC injections (blanks, spikes, calibration) are not
                    if (getattr(s, "qc_type", "Sample") or "Sample") == "Sample":
                        push_rows.append({"injection": inj, "analyte": s.analyte, "ok": False,
                                          "reason": lookup_notes.get(inj)
                                          or "no SENAITE sample has this Client Sample ID"})
                    continue
                keyword = keyword_for(s.analyte)
                ok = senaite.push_result(sample["uid"], keyword, s)
                outcome = getattr(senaite, "last_push", None) or {}
                push_rows.append({"injection": inj, "sample_uid": sample["uid"], "analyte": s.analyte,
                                  "keyword": keyword, "ok": bool(ok),
                                  # the reported reading's acquisition (the EDD's analysis date)
                                  "acquired_at": _acq(row_by_inj.get(
                                      getattr(s, "source_injection", "") or inj)),
                                  "analysis_uid": outcome.get("analysis_uid", ""),
                                  "value": outcome.get("value", ""),
                                  "reason": outcome.get("reason", "") if not ok else ""})
                if ok:
                    pushed += 1
                elif outcome.get("analysis_uid"):
                    locked += 1                  # there, but not editable
                else:
                    unmatched_analytes.add((s.analyte, keyword))
            logger.info("Pushed %d of %d results to SENAITE samples",
                        pushed, len(batch.summary))
            if locked:
                logger.warning(
                    "%d result(s) not written: their analyses are already "
                    "submitted or verified (see the push log); retract them in "
                    "SENAITE to take this run's values", locked)
            if hasattr(senaite, "apply_display"):
                senaite.apply_display([r["analysis_uid"] for r in push_rows
                                       if r.get("ok") and r.get("analysis_uid")])
            try:
                from .push_log import save_pushes
                save_pushes(batch.batch_id, push_rows)
            except sqlite3.Error as exc:
                logger.error("push log not written: %s", exc)
            # a QC criterion the run could not be judged against is a
            # deviation, raised here where the run arrives (never by a page),
            # after the push log is saved: the summary scopes a matrix spike
            # to its samples through it. The connector logs a failure rather
            # than retrying the run.
            if ws_uid and hasattr(senaite, "raise_unconfigured_deviation"):
                senaite.raise_unconfigured_deviation(ws_uid)
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
            # raised: the watcher retries the whole run (a re-import supersedes
            # its rows); a push that stopped partway never passes silently
            raise

    return batch, queue, report_path


# ─────────────────────────────────────────────────────────────────────────────
# Directory watcher
# ─────────────────────────────────────────────────────────────────────────────

def _record_import(import_log, name, batch_id, status, attempts, error):
    try:
        import_log.record(name, batch_id, status, attempts, error)
    except Exception as exc:                                # noqa: BLE001
        logger.error("import log not written for %s: %s", name, exc)


def _load_watched(path):
    """{file name: mtime_ns} the watcher processed, or None with no record."""
    try:
        with open(path) as fh:
            data = json.load(fh)
        return {str(k): int(v) for k, v in data.items()}
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        logger.warning("watcher record %s unreadable (%s); starting afresh", path, exc)
        return None


def _save_watched(path, seen):
    try:
        tmp = Path(str(path) + ".tmp")
        with open(tmp, "w") as fh:
            json.dump(seen, fh)
        os.replace(str(tmp), str(path))
    except OSError as exc:
        logger.warning("watcher record %s not written: %s", path, exc)


# the export types the Run Builder's upload accepts, and a raw run's record
WATCHED_TYPES = (".csv", ".txt", ".tsv", ".rawrun")
# how often the watch loop asks SENAITE to send the due notice e-mails
NOTICE_TICK_SECONDS = 900
# how often the worker asks the add-on to sweep the instrument archive
ARCHIVE_SWEEP_SECONDS = 86400


def _watched(watch_dir):
    return sorted(p for p in Path(watch_dir).iterdir()
                  if p.is_file() and p.suffix.lower() in WATCHED_TYPES)


def load_raw_run(*args, **kwargs):
    # imported on a raw run only: integration needs scipy, an export does not
    from .raw_run import load_raw_run as load
    return load(*args, **kwargs)


def comparison_side(raw, mode, supplementary=False):
    """The side of a run kept for the comparison and not reported: a raw
    run unless the method's results come from the LIMS integration, an
    export when they do (but a supplementary run's: those are imported from
    the export); None for the side that is reported."""
    if raw:
        return None if mode == "lims" else "raw"
    return "vendor" if mode == "lims" and not supplementary else None


def is_raw_run(path):
    return Path(path).suffix.lower() == ".rawrun"


def quantitation_map(method_id):
    """What each compound is quantified on: a native on its surrogate (the
    surrogate map), an isomer peak on its reported analyte's unless the map
    names one for the peak itself, a labelled standard on the one it is
    linked to."""
    out = dict(_get_surrogate_map(method_id))
    for pair in _get_isomer_summation(method_id):
        surrogate = out.get(pair.get("reported"))
        if not surrogate:
            continue
        for name in [pair.get("linear")] + list(pair.get("branched_list") or []):
            if name:
                out.setdefault(name, surrogate)
    for std, ref in get_labelled_links(method_id).items():
        out.setdefault(std, ref)
    return out


def load_rows(path, import_profile, method_id, traces=None, acid_basis=None):
    """The run's rows: an export read with its import layout, or a raw run
    integrated and quantified with the method's Integration settings (its
    traces into `traces`), each labelled standard's stated amounts as acid
    by its salt factor unless the run's calibration lots state it as the
    acid (`acid_basis`, the run record's acid_basis_analytes). An export's
    numbers are the instrument's: nothing of it is recomputed."""
    if is_raw_run(path):
        from .method_profiles import get_linked_response_ratio, get_labelled_roles, get_labelled_salt_factors
        return load_raw_run(str(path), get_integration(method_id),
                            get_profile(method_id).calibration_rule, quantitation_map(method_id),
                            traces=traces, composites=_get_composites(method_id),
                            linked=get_linked_response_ratio(method_id) == "on",
                            roles=get_labelled_roles(method_id),
                            salt_factors=get_labelled_salt_factors(method_id), acid_basis=acid_basis)
    return load_instrument_csv(path, profile=import_profile)


def refuse_unreadable(rows, profile, path):
    """An export the layout reads no row of -- no row naming both an injection
    and a compound -- is refused, never processed as a run of nothing."""
    def named(v):
        return bool(v) and ("%s" % v).strip().lower() not in ("nan", "none")
    if not any(named(r.injection_name) and named(r.compound_name) for r in rows):
        raise ImportError(
            "No row of %s names both an injection and a compound as the import layout %s "
            "reads it (%d row(s)): check its layout and column mapping in Import Studio."
            % (Path(path).name, (profile or {}).get("name") or "(none)", len(rows)))


def labelled_rows(rows, method_id):
    """Rows for the labelled standards a layout gives only as columns of each
    analyte's row (the profile's "labelled standards from columns"): one per
    injection and standard, from the IS area and IS retention time, the
    standard named by the row's linked standard, else the method's surrogate
    map. A standard the export has a row for is left as it is."""
    from dataclasses import replace
    from .analyte_alias import labelled_display_name
    sur = _get_surrogate_map(method_id) if method_id else {}
    have = set((r.concat_id, r.compound_name) for r in rows)
    parts = _isomer_parts(method_id)
    out = []
    for r in rows:
        if r.is_response is None or not _is_native(r, parts):
            continue
        name = r.linked_is or sur.get(r.compound_name) or sur.get(keyword_for(r.compound_name) or "")
        if not name:
            continue
        if _quantifying_members(method_id, name) != [name]:
            continue                    # a composite is no one compound: no row is made for it
        name = labelled_display_name(keyword_of(name) or name)
        if (r.concat_id, name) in have:
            continue
        have.add((r.concat_id, name))
        out.append(replace(
            r, compound_name=name, compound_type="Internal Standard", compound_group="",
            response=r.is_response, observed_rt=r.is_observed_rt, is_response=None,
            response_ratio=None, expected_conc=None, calculated_conc=None, measured_conc=None,
            pct_deviation=None, pct_recovery_is=None, ion_ratios=None, expected_ion_ratios=None,
            quan_ref_expected_ion_ratios=None, method_expected_ion_ratios=None,
            qual_ions_responses=None, signal_to_noise=None, qual_sn=None, reporting_limit=None,
            r2=None, linked_is=None, conc_qualifier="", manual_changes=None,
            manual_integration=None, included_in_cal=False,
            derived_from="columns of " + (r.compound_name or "")))
    return out


def standard_tokens(rows):
    """A standard never reads ALoQ or BLoQ: a calibrator is a point of its
    curve, judged on its deviation, and a check standard (ICV, CCV) on its
    window. A vendor export's calibrator, ICV or CCV row loses the
    instrument's word; its number is kept and judged as reported, and the
    word is kept on the row's provenance (derived_from). A calibrator is
    found by its role in the run plan, else, for a run with no role
    recorded, by the export's "Standard". A raw row never carries one.
    Returns the rows changed."""
    from .qc_engine import STANDARD_TOKENS
    changed = []
    for r in rows:
        if r.conc_qualifier not in STANDARD_TOKENS or (r.derived_from or "").startswith("raw:"):
            continue
        role = classify_injection(r.injection_name)
        if role not in ("CAL", "ICV", "CCV") and not (role == "Sample" and r.sample_type == "Standard"):
            continue
        r.derived_from = "the instrument wrote %s" % r.conc_qualifier
        r.conc_qualifier = ""
        changed.append(r)
    return changed


def over_range(rows, method_id, matrix):
    """[QCFlag] for each injection's native result above the method's top
    calibration level, in the matrix's reporting unit (the profile's levels,
    senaite.pfas.calibration_levels): the platform's own judgement, whatever
    the instrument wrote. An isomer group is judged on its sum. The rows read
    ALoQ, so the summary reports the dilution where there is one. Switched
    by the rule over_range (QC Rules)."""
    from .run_queue import _load_rule_toggles, _rule_enabled, _rule_state
    from .method_profiles import _profile_data_cache
    if not method_id or not _rule_enabled(_load_rule_toggles(method_id), "over_range"):
        return []
    evaluate = _rule_state(_load_rule_toggles(method_id), "over_range") == "evaluate"
    data = _profile_data_cache.get(method_id) or {}
    cal = _addon("calibration_levels")
    unit = (data.get("unit_map") or {}).get(matrix) or ""
    group_of = _isomer_parts(method_id)
    members = {}
    for r in rows:
        if reported_conc(r) is None or not _is_native(r, group_of) or not _has_sample_basis(r):
            continue
        kw = group_of.get(r.compound_name) or keyword_for(r.compound_name) or r.compound_name
        members.setdefault((r.concat_id, kw), []).append(r)
    flags = []
    for (_cid, kw), group in members.items():
        top = cal.derived_top(data, matrix, kw)
        if top is None:
            continue
        total = sum(reported_conc(r) for r in group)
        if total <= top * (1 + 1e-9):
            continue
        for r in group:
            r.conc_qualifier = QUALIFIER_ALOQ
            # the group's sum is above this top: the bound it is reported above
            r.range_top = top
            flags.append(QCFlag(
                source="Calibration range", check_kind=KIND_OVER_RANGE, analyte=r.compound_name,
                injection_name=r.injection_name, value="%g %s" % (total, unit),
                issue="(ALoQ) above the top calibration level %g %s" % (top, unit),
                advisory=evaluate))
    return flags


def raw_range(rows, method_id):
    """[QCFlag] for each native result of a raw run above the calibration
    range: its response ratio above the curve's response at the highest
    calibrator still on this run's curve (the record's above_range, judged
    in raw_run for every fit), with a reading or without one (a quadratic
    the ratio never reaches). The row reads ALoQ, so the summary reports the
    dilution where there is one; an isomer peak is judged on its own curve
    and makes its group ALoQ. Its range_top is the top calibrator on the
    sample basis: the curve's top_conc times the factors the row was given.
    A vendor export's row is not judged here: its instrument wrote its own
    ALoQ. Not switched by over_range, which judges the method's levels: this
    run's curve ends where its own calibrators do."""
    parts = _isomer_parts(method_id)
    flags = []
    for r in rows:
        derived = getattr(r, "derived_from", "") or ""
        if not derived.startswith("raw:"):
            continue
        rec = json.loads(derived[len("raw:"):]) or {}
        quant = rec.get("quant") or {}
        curve = quant.get("curve") or {}
        top = curve.get("top_conc")
        # the curve's reading, before any correction to the sample basis: on
        # a curve rising across its range, above the top calibrator exactly
        # when the ratio is (a record written before above_range was kept)
        reading = r.raw_calculated_conc if r.raw_calculated_conc is not None else r.calculated_conc
        if top is None or not (quant.get("above_range")
                               or (reading is not None and reading > top * (1 + 1e-9))):
            continue
        if not _is_native(r, parts) or not _has_sample_basis(r):
            continue
        # over_range judged a number above the method's top level already
        if r.conc_qualifier == QUALIFIER_ALOQ and reported_conc(r) is not None:
            continue
        r.conc_qualifier = QUALIFIER_ALOQ
        r.range_top = top * row_factor(r)
        value = reported_conc(r)
        flags.append(QCFlag(
            source="Calibration range", check_kind=KIND_OVER_RANGE, analyte=r.compound_name,
            injection_name=r.injection_name,
            value=("%g %s" % (value, getattr(r, "conc_units", "") or "") if value is not None
                   else "ratio %g" % quant.get("ratio")).strip(),
            issue="(ALoQ) above the highest calibrator on this run's curve, %s at %g" % (
                curve.get("top_injection") or "", top)))
    return flags


def instrument_gave_no_number(row):
    """An imported row the instrument wrote BLoQ with no number: its
    concentration cell held only the word (a number beside it, or in the
    concentration column with the word in Quantitation Status, is kept by
    the importer and reported). A raw run's row is the LIMS's own reading
    and never one."""
    return bool(row is not None and row.conc_qualifier == QUALIFIER_BLOQ
                and reported_conc(row) is None
                and not (getattr(row, "derived_from", "") or "").startswith("raw:"))


def raw_below_mdl(rows, method_id, matrix, acid_basis=None):
    """A raw run's native in a sample below its quadratic's lowest
    calibrator (the record's below, raw_run) has a number only at or above
    the MDL: its reading on the rising branch between zero and that
    calibrator, times the factors the row was given (the sample basis), is
    judged rounded as the certificate rounds it against the MDL of the
    analyte it is reported as, in the run's matrix. At or above it the row
    takes that number, the lowest calibrator on the same basis its
    reporting limit, as a straight line's reading there has; below it, with
    no MDL set, or with no reading at or above zero, the row stays BLoQ with
    no number. The record says which (quant.below_mdl, quant.mdl). An
    isomer's peak is judged on its own reading; a dilution needs nothing
    more, the MDL scaling with the fold as the reading does. Not switched
    by the mdl_check rule, which flags detections below the MDL: this
    decides whether there is a number at all. Runs before the QC engine,
    which then judges the number the row has. Returns the rows given a
    number."""
    from .method_profiles import get_profile
    from .run_queue import _units_compatible
    quant_fit = _addon("quant_fit")
    profile = get_profile(method_id) if method_id else None
    parts = _isomer_parts(method_id)
    rl_matrix = (_addon("report_limits").canonical_matrix(profile._profile_data(), matrix)
                 if profile is not None else matrix)
    kept = []
    for r in rows:
        derived = getattr(r, "derived_from", "") or ""
        if not derived.startswith("raw:"):
            continue
        rec = json.loads(derived[len("raw:"):]) or {}
        quant = rec.get("quant") or {}
        if (not quant.get("below") or r.conc_qualifier != QUALIFIER_BLOQ
                or not _is_native(r, parts) or not _has_sample_basis(r)):
            continue
        kw = parts.get(r.compound_name) or keyword_for(r.compound_name) or r.compound_name
        mdl = profile.reporting_limits(kw, rl_matrix, acid_basis)[1] if profile is not None else None
        reading = quant.get("below_reading")
        factor = row_factor(r)
        value = reading * factor if reading is not None else None
        unit = (getattr(r, "conc_units", "") or "").strip()
        if value is None:
            verdict = quant_fit.BELOW_NO_ROOT
        elif mdl is None:
            verdict = quant_fit.BELOW_NO_MDL
        elif not _units_compatible("" if unit.lower() == "nan" else unit,
                                   profile.reporting_limits(kw, rl_matrix, acid_basis)[2]):
            # never judged across units, as the MDL check is not
            verdict = quant_fit.BELOW_OTHER_UNIT
        else:
            judged = profile.judged_conc(value, matrix)
            verdict = (quant_fit.BELOW_AT_MDL if judged is not None and judged >= mdl
                       else quant_fit.BELOW_UNDER_MDL)
        quant["below_mdl"] = verdict
        quant["mdl"] = mdl
        if verdict == quant_fit.BELOW_AT_MDL:
            bottom = (quant.get("curve") or {}).get("bottom_conc")
            r.calculated_conc = r.measured_conc = value
            r.raw_calculated_conc = r.raw_measured_conc = reading
            r.reporting_limit = bottom * factor if bottom is not None else None
            r.conc_qualifier = ""
            kept.append(r)
        rec["quant"] = quant
        r.derived_from = "raw:" + json.dumps(rec, sort_keys=True)
    return kept


def range_tops(rows, method_id, matrix):
    """The top of the calibration range on the sample basis (range_top) for
    each native result that reads ALoQ and has none yet, as the instrument
    wrote it: the highest concentration the run's calibrators state for the
    compound times the factors the row was given. Where the run states none,
    or the MS software applied the sample's factors itself, the method's top
    level in the reporting unit (calibration_levels.derived_top); None where
    neither is known."""
    from .method_profiles import _profile_data_cache
    from .qc_engine import calibrator_rows
    parts = _isomer_parts(method_id)
    data = (_profile_data_cache.get(method_id) or {}) if method_id else {}
    software = bool(method_id) and _get_sample_correction(method_id) == "instrument"
    stated = {}
    for r in rows:
        if r.conc_qualifier != QUALIFIER_ALOQ or getattr(r, "range_top", None) is not None:
            continue
        if not _is_native(r, parts) or not _has_sample_basis(r):
            continue
        if r.compound_name not in stated:
            stated[r.compound_name] = [c.expected_conc for c in calibrator_rows(rows, r.compound_name)
                                       if c.expected_conc]
        if stated[r.compound_name] and not software:
            r.range_top = max(stated[r.compound_name]) * (r.salt_factor or 1.0) * (r.matrix_factor or 1.0)
        elif data and matrix:
            kw = parts.get(r.compound_name) or keyword_for(r.compound_name) or r.compound_name
            r.range_top = _addon("calibration_levels").derived_top(data, matrix, kw)


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
    # A file is new when its name OR its modification time is: re-uploading a
    # run under the same name (the Run Builder's reprocess) must run it again.
    #
    # What was processed is kept beside the output, so a file that lands
    # while the worker is down (a restart) is run when it comes back. Without
    # a record (the first start) the files already there count as processed.
    state = Path(output_dir) / ".watched.json"
    seen: dict[str, int] = _load_watched(state)
    if seen is None:
        seen = {p.name: p.stat().st_mtime_ns for p in _watched(watch_dir)}
        _save_watched(state, seen)
    else:
        # a .txt / .tsv the record does not name counts as processed, as at a
        # first start
        for p in _watched(watch_dir):
            if p.suffix.lower() != ".csv" and p.name not in seen:
                seen[p.name] = p.stat().st_mtime_ns
        _save_watched(state, seen)
    logger.info("Watching %s (every %ds)", watch_dir, poll_seconds)
    from . import import_log
    retries: dict[str, tuple] = {}            # name -> (attempts, next try at, mtime)
    next_notice_tick = 0.0
    next_sweep = 0.0

    while True:
        time.sleep(poll_seconds)
        if senaite is not None and senaite.warm_caches():
            logger.info("Site warmed: every open worksheet's method worked out")
        if senaite is not None and time.time() >= next_notice_tick:
            next_notice_tick = time.time() + NOTICE_TICK_SECONDS
            senaite.send_notice_reminders()
        if senaite is not None and time.time() >= next_sweep:
            next_sweep = time.time() + ARCHIVE_SWEEP_SECONDS
            senaite.sweep_instrument_archive()
        for p in _watched(watch_dir):
            if seen.get(p.name) == p.stat().st_mtime_ns:
                continue
            attempts, next_at, mtime = retries.get(p.name, (0, 0, None))
            if mtime is not None and mtime != p.stat().st_mtime_ns:
                attempts, next_at = 0, 0          # delivered again: a new run
            elif attempts and time.time() < next_at:
                continue
            # wait for export to finish (stable size)
            size = -1
            while size != p.stat().st_size:
                size = p.stat().st_size
                time.sleep(5)
            seen[p.name] = p.stat().st_mtime_ns
            _save_watched(state, seen)
            logger.info("New instrument file: %s", p.name)

            # The sidecar carries the run parameters. The one BESIDE the CSV
            # wins: the Run Builder writes it from the SENAITE guided
            # extraction at upload. The configured directory is only a
            # fallback for files dropped by hand.
            ext_log = None
            candidates = [p.with_name(f"{p.stem}_extraction.json")]
            if extraction_log_dir:
                candidates.append(
                    Path(extraction_log_dir) / f"{p.stem}_extraction.json")
            for candidate in candidates:
                if candidate.exists():
                    ext_log = candidate
                    break
            if ext_log is None:
                logger.warning(
                    "%s has no %s_extraction.json sidecar — the run will have "
                    "no method, matrix, batch id or extraction pedigree.",
                    p.name, p.stem)

            batch_id = import_log.sidecar_batch_id(ext_log) if ext_log else ""
            try:
                run_pipeline(p, output_dir=output_dir, senaite=senaite,
                             extraction_log_path=ext_log)
            except ReimportRefused as e:
                # recorded once, never retried: the queue moves on
                logger.warning("Refused %s: %s", p.name, e)
                retries.pop(p.name, None)
                _record_import(import_log, p.name, batch_id, "refused", attempts + 1, str(e))
            except Exception as e:                   # noqa: BLE001
                logger.exception("Pipeline failed for %s: %s", p.name, e)
                attempts += 1
                final = attempts > len(import_log.RETRY_DELAYS)
                if final:
                    retries.pop(p.name, None)
                else:
                    # not processed: tried again after the delay
                    retries[p.name] = (attempts, time.time() + import_log.RETRY_DELAYS[attempts - 1],
                                       seen.get(p.name))
                    seen.pop(p.name, None)
                    _save_watched(state, seen)
                _record_import(import_log, p.name, batch_id, "failed" if final else "retrying",
                               attempts, "%s: %s" % (type(e).__name__, e))
            else:
                retries.pop(p.name, None)
                _record_import(import_log, p.name, batch_id, "imported", attempts + 1, "")
                # processed: the export moves to the archive (instrument_files)
                try:
                    moved = _addon("instrument_files").archive(str(p))
                    if moved:
                        logger.info("%s moved to the archive", p.name)
                except OSError as e:
                    logger.error("%s not moved to the archive: %s", p.name, e)
