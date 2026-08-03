# -*- coding: utf-8 -*-
"""
EGAD EDD Builder — generates EDD v6.0 CSV from SENAITE Batch data.

Python 2.7 compatible.  No f-strings, no pathlib, no annotations.

Called when publishing a report for a government-agency client.
Reads SENAITE API objects, applies EGAD config, produces 53-column CSV.

QC type mapping (pipeline labels → EGAD QA_QC_TYPE_LUP):
  MB / LB → LB   LFSM → MS   LFSMD → MSD   CCV → CCC
  LCS → LCS   LCSD → LCSD   Dup/DUP → L   FD → D   Normal/NA → NA

Result type codes:
  Normal target analyte → TRG
  NC_Flag analyte       → TIC  (Tentatively Identified Compound)
  Internal standard     → IS
  Surrogate             → SUR
"""
from __future__ import absolute_import, print_function, unicode_literals

import csv
import io
import logging

from senaite.pfas.egad_store import (
    get_lab_config,
    get_method_egad,
    get_analyte_cas,
    get_qualifier_dict,
    get_qc_type_dict,
    get_client_egad,
    get_lookups,
)

logger = logging.getLogger("senaite.pfas.egad_builder")

# Analyte keywords flagged as NC (Tentatively Identified Compound)
_NC_FLAG_KEYWORDS = frozenset([
    "9ClPF3ONS", "11ClPF3OUdS", "PFTrDA", "PFTrDS", "PFODA", "DONA",
    "PFPeS", "PFHpS", "PFNS", "PFDS", "PFUnDS", "PFDoS",
])

EDD_COLUMNS = [
    "PROJECT/SITE", "SAMPLE_POINT_NAME", "SAMPLE_ID", "LAB_SAMPLE_ID",
    "ANALYSIS_LAB", "SAMPLE_DATE", "SAMPLE_TIME", "SAMPLE_TYPE",
    "QC_TYPE", "RESULT_TYPE_CODE", "CAS_NO", "PARAMETER_NAME",
    "CONCENTRATION", "LAB_QUALIFIER", "REPORTING_LIMIT", "PARAMETER_UNITS",
    "% RECOVERY", "RPD", "TEST", "PARAMETER_QUALIFIER", "PARAMETER_FILTERED",
    "SAMPLE_COLLECTION_METHOD", "SAMPLE_LOCATION", "TREATMENT_STATUS",
    "SAMPLED_BY", "IDL", "MDL", "DILUTION_FACTOR", "BATCH_ID",
    "SAMPLE_DELIVERY_GROUP", "ANALYSIS_DATE", "ANALYSIS_TIME",
    "PREP_METHOD", "PREP_DATE", "PREP_TIME", "PREP_METHOD2",
    "PREP_DATE2", "PREP_TIME2", "WEIGHT_BASIS", "LAB_COMMENT",
    "VALIDATION_QUALIFIER", "VALIDATION_LEVEL", "VALIDATION_COMMENT",
    "VALIDATION_COMMENT_TYPE", "VALIDATION_SQL", "SAMPLE_DEPTH",
    "SAMPLE_DEPTH_UNIT", "SAMPLE_DEPTH_INTERVAL_TOP",
    "SAMPLE_DEPTH_INTERVAL_BOTTOM", "SAMPLE_DEPTH_INTERVAL_UNIT",
    "RADIOLOGICAL_COUNTING_ERROR", "SAMPLE_TYPE_QUALIFIER", "SAMPLE_COMMENT",
]

_LAB_REQUIRED = frozenset([
    "PROJECT/SITE", "SAMPLE_POINT_NAME", "LAB_SAMPLE_ID", "ANALYSIS_LAB",
    "SAMPLE_DATE", "SAMPLE_TIME", "SAMPLE_TYPE", "QC_TYPE",
    "RESULT_TYPE_CODE", "CAS_NO", "PARAMETER_NAME", "CONCENTRATION",
    "REPORTING_LIMIT", "PARAMETER_UNITS", "TEST", "PARAMETER_FILTERED",
    "SAMPLE_COLLECTION_METHOD", "TREATMENT_STATUS", "BATCH_ID",
    "SAMPLE_DELIVERY_GROUP", "ANALYSIS_DATE", "ANALYSIS_TIME",
])

_QC_REQUIRED = frozenset([
    "PROJECT/SITE", "SAMPLE_POINT_NAME", "LAB_SAMPLE_ID", "ANALYSIS_LAB",
    "SAMPLE_DATE", "SAMPLE_TIME", "SAMPLE_TYPE", "QC_TYPE",
    "RESULT_TYPE_CODE", "CAS_NO", "PARAMETER_NAME",
    "PARAMETER_UNITS", "TEST", "PARAMETER_FILTERED",
    "SAMPLE_COLLECTION_METHOD", "TREATMENT_STATUS", "BATCH_ID",
    "SAMPLE_DELIVERY_GROUP", "ANALYSIS_DATE", "ANALYSIS_TIME",
])

_SOLID_SAMPLE_TYPES = frozenset([
    "SL", "SD", "SU", "SUL", "SUU", "AS", "BA", "FA",
    "MEA", "MLK", "EG", "FE", "MU", "SF", "SOF", "FI",
    "CP", "CH", "CO", "FR", "GR", "GRS", "LG", "NRV", "RV",
    "V", "GZ", "G", "HT", "HP", "KD", "LV", "MR", "HM",
    "MA", "MPS", "HN", "HR", "O", "TO", "WH", "WWHG", "WS",
    "SK", "MTB", "BC",
])


def _fmt_date(d):
    if d is None:
        return ""
    try:
        return d.strftime("%m/%d/%Y")
    except AttributeError:
        return str(d)


def _fmt_time(d):
    if d is None:
        return ""
    try:
        return d.strftime("%H:%M")
    except AttributeError:
        return str(d)


def _get_units(method_id, sample_type_code, method_cfg):
    if sample_type_code in _SOLID_SAMPLE_TYPES:
        return method_cfg.get("units_solid", "NG/KG")
    return method_cfg.get("units_water", "NG/L")


def _row_to_list(row_dict):
    """Convert row_dict to ordered list of 53 values."""
    g = row_dict.get
    conc = g("concentration")
    return [
        g("project_site", ""),
        g("sample_point_name", ""),
        g("sample_id", ""),
        g("lab_sample_id", ""),
        g("analysis_lab", ""),
        _fmt_date(g("sample_date")),
        _fmt_time(g("sample_time")),
        g("sample_type", ""),
        g("qc_type", "NA"),
        g("result_type_code", "TRG"),
        g("cas_no", ""),
        g("parameter_name", ""),
        "" if conc is None else conc,
        g("lab_qualifier", ""),
        g("reporting_limit", ""),
        g("parameter_units", ""),
        g("pct_recovery", ""),
        g("rpd", ""),
        g("test", ""),
        g("parameter_qualifier", ""),
        g("parameter_filtered", "NA"),
        g("sample_collection_method", ""),
        g("sample_location", "NA"),
        g("treatment_status", "N"),
        g("sampled_by", ""),
        g("idl", ""),
        g("mdl", ""),
        g("dilution_factor", 1),
        g("batch_id", ""),
        g("sdg", ""),
        _fmt_date(g("analysis_date")),
        _fmt_time(g("analysis_time")),
        g("prep_method", ""),
        _fmt_date(g("prep_date")),
        _fmt_time(g("prep_time")),
        g("prep_method2", ""),
        _fmt_date(g("prep_date2")),
        _fmt_time(g("prep_time2")),
        g("weight_basis", "NA"),
        g("lab_comment", ""),
        g("validation_qualifier", ""),
        g("validation_level", ""),
        g("validation_comment", ""),
        g("validation_comment_type", ""),
        g("validation_sql", ""),
        g("sample_depth", ""),
        g("sample_depth_unit", ""),
        g("sample_depth_interval_top", ""),
        g("sample_depth_interval_bottom", ""),
        g("sample_depth_interval_unit", ""),
        g("radiological_counting_error", ""),
        g("sample_type_qualifier", "NA"),
        g("sample_comment", ""),
    ]


def _validate_row(row_values, row_number, is_qc):
    errors = []
    required = _QC_REQUIRED if is_qc else _LAB_REQUIRED
    row_dict = dict(zip(EDD_COLUMNS, row_values))
    qual = str(row_dict.get("LAB_QUALIFIER", "") or "")

    for field in required:
        val = row_dict.get(field)
        if val is None or str(val).strip() == "":
            # Non-detect: blank CONCENTRATION is correct when U-qualified
            if field == "CONCENTRATION" and "U" in qual.upper():
                continue
            errors.append({
                "row": row_number,
                "field": field,
                "message": "Required field is blank",
                "type": "QC" if is_qc else "Lab",
            })

    cas = str(row_dict.get("CAS_NO", "") or "")
    if cas.upper() == "PLACEHOLDER":
        errors.append({
            "row": row_number,
            "field": "CAS_NO",
            "message": (
                "CAS_NO is PLACEHOLDER — assign a real CAS or DEP##### code "
                "in EGAD Config before submitting"
            ),
            "type": "BLOCKING",
        })
    elif not cas.strip():
        param = str(row_dict.get("PARAMETER_NAME", "") or "")
        errors.append({
            "row": row_number,
            "field": "CAS_NO",
            "message": "CAS_NO is empty for {0} — enter in EGAD Config".format(param),
            "type": "BLOCKING",
        })

    return errors


class EGADBuilder(object):
    """
    Reads SENAITE batch/AR data and produces an EGAD EDD v6.0 CSV.

    Usage:
        builder = EGADBuilder(portal)
        csv_str, errors = builder.generate_from_batch(batch_obj)
        filename = builder.filename_for_batch(batch_obj, client_cfg)
    """

    def __init__(self, portal):
        self.portal = portal
        self._lab_cfg = get_lab_config(portal)
        self._method_egad = get_method_egad(portal)
        self._analyte_cas = get_analyte_cas(portal)
        self._qualifier_dict = get_qualifier_dict(portal)
        self._qc_type_dict = get_qc_type_dict(portal)

    def _apply_profile_vocab(self, profile):
        """Swap the lab-global qualifier/QC/analyte-CAS maps for the state
        profile's own vocabulary (D63 full untie). Profiles always carry these
        (backfilled on load), so Maine output is byte-identical while other
        state profiles translate qualifiers/QC types and name/code analytes
        their own way. Real CAS stays single-sourced via the profile helper."""
        from senaite.pfas.egad_store import (
            get_profile_qualifier_dict, get_profile_qc_type_dict,
            get_profile_analyte_cas)
        if not profile:
            return
        self._qualifier_dict = get_profile_qualifier_dict(profile)
        self._qc_type_dict = get_profile_qc_type_dict(profile)
        prof_cas = get_profile_analyte_cas(profile)
        if prof_cas:
            self._analyte_cas = prof_cas

    def _get_method_cfg(self, method_id):
        return self._method_egad.get(method_id, {
            "test_code": "E537.1",
            "prep_method": "SW3535",
            "units_water": "NG/L",
            "units_solid": "NG/KG",
        })

    def _translate_qualifier(self, our_qual):
        if not our_qual:
            return ""
        return self._qualifier_dict.get(our_qual, our_qual)

    def _translate_qc_type(self, our_qc):
        if not our_qc:
            return "NA"
        return self._qc_type_dict.get(our_qc, our_qc)

    def _result_type_code(self, keyword, analysis_type="target"):
        if analysis_type in ("IS", "internal_standard"):
            return "IS"
        if analysis_type in ("SUR", "surrogate"):
            return "SUR"
        if keyword in _NC_FLAG_KEYWORDS:
            return "TIC"
        return "TRG"

    def _build_sdg(self, batch_id):
        lab = self._lab_cfg
        prefix = lab.get("sdg_prefix", "") or ""
        fmt = lab.get("sdg_format", "{prefix}{batch_id}") or "{prefix}{batch_id}"
        return fmt.format(prefix=prefix, batch_id=batch_id)

    def generate_from_batch(self, batch_obj, client_obj=None, per_report_override=True):
        """
        Generate EDD CSV for a SENAITE batch.

        batch_obj:            SENAITE Batch AT object
        client_obj:           SENAITE Client AT object (for project_site etc.)
        per_report_override:  if False, suppress EDD even for gov clients

        Returns: (csv_string, validation_errors, filename)
        """
        if client_obj is not None:
            client_cfg = get_client_egad(client_obj)
        else:
            client_cfg = {}

        if not per_report_override:
            return ("", [], "")

        lab = self._lab_cfg
        project_site = (
            client_cfg.get("project_site") or
            (client_obj.Title() if client_obj else "") or
            ""
        )
        analysis_lab = (
            client_cfg.get("analysis_lab_override") or
            lab.get("analysis_lab_code") or
            ""
        )
        default_sample_type = client_cfg.get("default_sample_type", "GW")
        # EDD STATE PROFILE: per-client (client cfg `edd_profile`), Maine EGAD
        # by default. Controls SAMPLE_TYPE matrix map, output columns/aliases,
        # AND (D63) the state vocabulary: qualifier map, QC-type map, and
        # analyte parameter-naming/state-code overrides. The method still
        # supplies analytes/units/test/CAS by reference.
        from senaite.pfas.egad_store import get_edd_profile_for_client
        self._unmapped_matrices = set()
        self._edd_profile_id, self._edd_profile = \
            get_edd_profile_for_client(self.portal, client_cfg)
        self._apply_profile_vocab(self._edd_profile)

        batch_id = batch_obj.getId()
        sdg = self._build_sdg(batch_id)
        batch_date = getattr(batch_obj, "created", None)
        if callable(batch_date):
            batch_date = batch_date()

        rows_data = []
        all_errors = []

        # ── Collect field sample rows from ARs in the batch ───────────────────
        try:
            ars = batch_obj.getAnalysisRequests()
        except AttributeError:
            ars = []
        if not ars:
            # Batch.getAnalysisRequests() is unreliable across versions —
            # resolve via the sample catalog (ARs carry getBatchUID).
            try:
                from Products.CMFCore.utils import getToolByName
                cat = getToolByName(self.portal, "senaite_catalog_sample")
                ars = [b.getObject() for b in cat(
                    portal_type="AnalysisRequest",
                    getBatchUID=batch_obj.UID())]
            except Exception:
                ars = []

        # Resolve the BATCH's method profile once (issue D44#9): core Method
        # via the bridge, else the batch's extraction/run annotations. Rows
        # must speak the batch's method — not client defaults.
        batch_profile_id = self._batch_method_profile(batch_obj)

        for ar in ars:
            ar_rows = self._ar_to_rows(
                ar, project_site, analysis_lab, default_sample_type,
                sdg, batch_id, lab, client_cfg,
                batch_profile_id=batch_profile_id,
            )
            rows_data.extend(ar_rows)

        # ── Produce CSV (shaped by the EDD profile) ──────────────────────────
        prof = getattr(self, "_edd_profile", None) or {}
        out_cols = [c for c in (prof.get("columns") or EDD_COLUMNS)
                    if c in EDD_COLUMNS] or list(EDD_COLUMNS)
        aliases = prof.get("aliases") or {}
        idx = dict((c, i) for i, c in enumerate(EDD_COLUMNS))
        header = [aliases.get(c, c) for c in out_cols]
        csv_rows = [header]
        row_number = 0

        for rd in rows_data:
            row_number += 1
            is_qc = rd.get("qc_type", "NA") != "NA"
            full_vals = _row_to_list(rd)          # Maine superset order
            # validation runs on the FULL superset (Maine semantics);
            # output is then subset/reordered/aliased per the profile
            errs = _validate_row(full_vals, row_number, is_qc)
            all_errors.extend(errs)
            csv_rows.append([full_vals[idx[c]] for c in out_cols])

        for matrix in sorted(getattr(self, "_unmapped_matrices", set())):
            all_errors.append({
                "row": 0,
                "field": "SAMPLE_TYPE",
                "message": (
                    "No EGAD sample-type code configured for matrix {0!r} — "
                    "set it in the EGAD profile's matrix map. Exporting "
                    "without it would state the wrong matrix.".format(matrix)),
                "type": "Lab",
            })

        # Python 2.7 CSV: writer expects byte strings; encode unicode as utf-8
        buf = io.BytesIO()
        writer = csv.writer(buf)
        for r in csv_rows:
            encoded = []
            for v in r:
                if v is None:
                    encoded.append(b"")
                else:
                    cell = u"{0}".format(v)
                    encoded.append(cell.encode("utf-8"))
            writer.writerow(encoded)

        csv_str = buf.getvalue().decode("utf-8")

        filename = self.filename_for_batch(batch_id, client_cfg)
        return (csv_str, all_errors, filename)


    def _batch_method_profile(self, batch_obj):
        """Method PROFILE id for a batch: core Method (via the bridge) first,
        then the batch's extraction-log / run-manifest annotations."""
        try:
            m = batch_obj.getMethod()
            if m is not None:
                from senaite.pfas.method_bridge import get_profile_id_for_method
                pid = get_profile_id_for_method(self.portal, m)
                if pid:
                    return pid
        except Exception:
            pass
        try:
            import json as _json
            from zope.annotation.interfaces import IAnnotations
            ann = IAnnotations(batch_obj)
            for key in (u"senaite.pfas.run_manifest",
                        u"senaite.pfas.logbook.252",
                        u"senaite.pfas.logbook.251"):
                raw = ann.get(key)
                if raw:
                    d = _json.loads(raw)
                    mid = d.get("method_id") or d.get("method")
                    if mid:
                        return mid
        except Exception:
            pass
        return ""

    def _ar_to_rows(self, ar, project_site, analysis_lab, default_sample_type,
                    sdg, batch_id, lab, client_cfg, batch_profile_id=""):
        """Convert one AnalysisRequest and all its analyses to EDD row dicts."""
        rows = []

        # A dilution is not a sample of its own — it is the same extract
        # re-injected, and its result is folded into the parent. Exporting it
        # would report the same measurement twice to the regulator.
        try:
            from zope.annotation.interfaces import IAnnotations
            if (IAnnotations(ar).get("senaite.pfas.qc_type", "") or
                    "").strip() == "Dilution":
                return []
        except Exception:
            pass

        # Sample-level values
        lab_sample_id = ar.getId()
        client_sample_id = (
            getattr(ar, "getClientSampleID", lambda: "")() or ""
        )
        sample_date = None
        sample_time = None
        try:
            dt = ar.getDateSampled()
            if dt:
                sample_date = dt
                sample_time = dt
        except AttributeError:
            pass

        # Sample point name
        sample_point_name = ""
        try:
            sp = ar.getSamplePoint()
            if sp:
                sample_point_name = sp.Title() or ""
        except AttributeError:
            pass

        # Sample type code (per-sample override, else client default, else lab default)
        try:
            from zope.annotation.interfaces import IAnnotations
            ar_ann = IAnnotations(ar)
            sample_type_code = ar_ann.get("senaite.pfas.egad_sample_type", "")
            if not sample_type_code:
                # profile's configurable SampleType→code map (state-specific)
                try:
                    st = ar.getSampleType()
                    mm = (getattr(self, "_edd_profile", {}) or {}).get(
                        "matrix_map") or {}
                    sample_type_code = mm.get(st.Title() if st else "", "")
                except Exception:
                    sample_type_code = ""
            # No silent fallback. An unmapped matrix used to become the lab
            # default — "GW", groundwater, on every row of an Animal Feed
            # batch. A wrong matrix code on a regulatory submission is worse
            # than a late one, so the matrix is recorded as unmapped and the
            # export refuses, naming it, exactly as a PLACEHOLDER CAS does.
            if not sample_type_code:
                st_title = ""
                try:
                    st = ar.getSampleType()
                    st_title = (st.Title() or "") if st else ""
                except Exception:
                    st_title = ""
                self._unmapped_matrices.add(st_title or "(no sample type)")
        except Exception:
            sample_type_code = ""

        # QC type — derive from AR's sample type title
        sample_type_title = ""
        try:
            st = ar.getSampleType()
            if st:
                sample_type_title = (st.Title() or "").upper()
        except AttributeError:
            pass

        # The sample's own QC role, recorded on it. Sniffing the SampleType
        # TITLE for "MATRIX SPIKE" only works when a lab registers a dedicated
        # QC sample type; a method blank submitted as ordinary Animal Feed came
        # out as NA, so blank contamination was exported as a client result.
        our_qc_type = ""
        try:
            from zope.annotation.interfaces import IAnnotations
            our_qc_type = (IAnnotations(ar).get(
                "senaite.pfas.qc_type", "") or "").strip()
        except Exception:
            our_qc_type = ""

        if not our_qc_type:
            our_qc_type = "NA"
        for marker, code in ([] if our_qc_type != "NA" else [
            ("METHOD BLANK", "MB"), ("LAB BLANK", "LB"),
            ("MATRIX SPIKE DUPLICATE", "LFSMD"), ("MATRIX SPIKE", "LFSM"),
            ("LFSMD", "LFSMD"), ("LFSM", "LFSM"),
            ("LCS DUPLICATE", "LCSD"), ("LCS", "LCS"),
            ("DUPLICATE", "Dup"), ("DUP", "Dup"),
        ]):
            if marker in sample_type_title:
                our_qc_type = code
                break

        egad_qc_type = self._translate_qc_type(our_qc_type)
        is_qc_sample = egad_qc_type != "NA"

        # For QC samples: AQ (aqueous), SAMPLE_POINT_NAME="QC", SCM="NA"
        if is_qc_sample:
            edd_sample_type = "AQ"
            edd_spn = "QC"
            edd_scm = "NA"
            edd_location = "NA"
        else:
            edd_sample_type = sample_type_code
            edd_spn = sample_point_name or lab_sample_id
            edd_scm = lab.get("default_sample_collection_method", "LFS")
            edd_location = "NA"

        # Analysis/prep dates — use first analysis or AR verification date
        analysis_date = None
        analysis_time = None
        prep_date = None
        prep_time = None
        try:
            verified = ar.getDateVerified()
            if verified:
                analysis_date = verified
                analysis_time = verified
        except AttributeError:
            pass

        # Method info — the BATCH's method profile governs TEST/prep/units
        # (D44#9). ar.getMethod() returns the CORE Method object; map it to the
        # profile id via the bridge; else use the batch-level resolution.
        method_id = ""
        try:
            method = ar.getMethod()
            if method:
                from senaite.pfas.method_bridge import get_profile_id_for_method
                method_id = get_profile_id_for_method(self.portal, method) or ""
        except Exception:
            pass
        if not method_id:
            method_id = batch_profile_id or ""

        method_cfg = self._get_method_cfg(method_id)
        test_code = method_cfg.get("test_code", "")
        prep_method = method_cfg.get("prep_method", lab.get("default_prep_method", "SW3535"))

        # Units: the profile's UNIT MAP (method × matrix — §3 single source)
        # wins; EGAD-code based fallback otherwise.
        units = ""
        try:
            st = ar.getSampleType()
            matrix_title = st.Title() if st else ""
            if method_id and matrix_title:
                from senaite.pfas.method_profile_store import get_profile
                umap = (get_profile(self.portal, method_id) or {}).get(
                    "unit_map") or {}
                u = umap.get(matrix_title, "")
                if u:
                    units = u.upper().replace("NG/G", "NG/KG")
        except Exception:
            pass
        if not units:
            units = _get_units(method_id, edd_sample_type, method_cfg)

        weight_basis = "NA"
        if edd_sample_type in _SOLID_SAMPLE_TYPES:
            # Dry weight by default for food/solid matrices — configurable
            weight_basis = "DW"

        treatment_status = lab.get("default_treatment_status", "N")
        sampled_by = lab.get("sampled_by", "")
        parameter_filtered = lab.get("default_parameter_filtered", "U")
        if is_qc_sample:
            parameter_filtered = "NA"

        # ── Per-analyte rows ──────────────────────────────────────────────────
        try:
            analyses = ar.getAnalyses(full_objects=True)
        except Exception:
            analyses = []

        for analysis in analyses:
            try:
                keyword = analysis.getKeyword()
                title = analysis.Title()
                result = analysis.getResult()
                interims = analysis.getInterimFields() or []
                # review_state is a CATALOG BRAIN attribute — on full objects
                # it raises AttributeError and silently dropped EVERY analysis
                # from the EDD. Resolve via the workflow API instead.
                try:
                    from bika.lims import api as _bapi
                    review_state = _bapi.get_review_status(analysis) or ""
                except Exception:
                    review_state = getattr(analysis, "review_state", "") or ""
            except AttributeError:
                continue

            # Get result value
            conc = None
            our_qual = ""
            rl = None
            mdl_val = None

            if result is not None and result != "":
                try:
                    conc_f = float(result)
                    if conc_f < 0:
                        conc = None
                        our_qual = "N.D."
                    else:
                        conc = conc_f
                except (ValueError, TypeError):
                    our_qual = "N.D."

            # Look for interim fields: reporting_limit, MDL, qualifier
            for interim in interims:
                k = (interim.get("keyword") or "").lower()
                v = interim.get("value")
                if k in ("reporting_limit", "rl", "mql", "mdl_b"):
                    try:
                        rl = float(v)
                    except (TypeError, ValueError):
                        pass
                elif k in ("mdl",):
                    try:
                        mdl_val = float(v)
                    except (TypeError, ValueError):
                        pass
                elif k in ("qualifier", "lab_qualifier"):
                    our_qual = str(v or "")

            # Translate qualifier
            egad_qual = self._translate_qualifier(our_qual)

            # CAS lookup
            cas_entry = self._analyte_cas.get(keyword, {})
            cas_no = cas_entry.get("cas_no", "")
            parameter_name = cas_entry.get("parameter_name", title)

            # Result type code
            analysis_type = "target"
            try:
                from senaite.pfas.analytes import PFAS_ANALYTES, INTERNAL_STANDARDS
                if keyword in {a["keyword"] for a in INTERNAL_STANDARDS}:
                    analysis_type = "IS"
            except Exception:
                pass
            rtc = self._result_type_code(keyword, analysis_type)

            # Analysis date from individual analysis if available
            try:
                an_dt = analysis.getResultCaptureDate()
                if an_dt:
                    analysis_date = an_dt
                    analysis_time = an_dt
            except AttributeError:
                pass

            row = {
                "project_site": project_site,
                "sample_point_name": edd_spn,
                "sample_id": client_sample_id,
                "lab_sample_id": lab_sample_id,
                "analysis_lab": analysis_lab,
                "sample_date": sample_date,
                "sample_time": sample_time,
                "sample_type": edd_sample_type,
                "qc_type": egad_qc_type,
                "result_type_code": rtc,
                "cas_no": cas_no,
                "parameter_name": parameter_name,
                "concentration": conc,
                "lab_qualifier": egad_qual,
                "reporting_limit": rl,
                "parameter_units": units,
                "pct_recovery": None,
                "rpd": None,
                "test": test_code,
                "parameter_qualifier": "",
                "parameter_filtered": parameter_filtered,
                "sample_collection_method": edd_scm,
                "sample_location": edd_location,
                "treatment_status": treatment_status,
                "sampled_by": sampled_by,
                "idl": None,
                "mdl": mdl_val,
                "dilution_factor": 1,
                "batch_id": batch_id,
                "sdg": sdg,
                "analysis_date": analysis_date,
                "analysis_time": analysis_time,
                "prep_method": prep_method,
                "prep_date": prep_date,
                "prep_time": prep_time,
                "weight_basis": weight_basis,
            }
            rows.append(row)

        return rows

    def filename_for_batch(self, batch_id, client_cfg=None):
        """
        Filename convention: {CLIENT_ID}_{SDG}_{YYYYMMDD}_EDD.csv
        Falls back to batch_id if client info unavailable.
        """
        from datetime import date
        today = date.today().strftime("%Y%m%d")
        sdg = self._build_sdg(batch_id).replace("/", "-").replace(" ", "_")
        client_id = ""
        if client_cfg and client_cfg.get("project_site"):
            client_id = client_cfg["project_site"].replace(" ", "_")[:20]
        if client_id:
            return u"{0}_{1}_{2}_EDD.csv".format(client_id, sdg, today)
        return u"{0}_{1}_EDD.csv".format(sdg, today)

    @staticmethod
    def format_validation_report(errors):
        """Return a human-readable text report of validation errors."""
        if not errors:
            return u"Validation PASSED — no errors found.\n"
        lines = [u"EGAD EDD Validation Report", u"=" * 50, u""]
        blocking = [e for e in errors if e.get("type") == "BLOCKING"]
        regular = [e for e in errors if e.get("type") != "BLOCKING"]
        if blocking:
            lines.append(u"BLOCKING ERRORS (file cannot be submitted):")
            for e in blocking:
                lines.append(u"  Row {0:3d}  {1}: {2}".format(
                    e["row"], e["field"], e["message"]))
            lines.append(u"")
        if regular:
            lines.append(u"Other errors ({0} total):".format(len(regular)))
            for e in regular:
                lines.append(u"  Row {0:3d}  {1}: {2}".format(
                    e["row"], e["field"], e["message"]))
        return u"\n".join(lines) + u"\n"
