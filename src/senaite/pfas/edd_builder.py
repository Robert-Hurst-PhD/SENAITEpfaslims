# -*- coding: utf-8 -*-
"""
The EDD export: a batch's results as a delivery file, in the format of the
client's EDD profile. Python 2.7.

Everything format-specific comes from the profile (edd_store): its
defaults, method codes, value lists, code maps (qualifiers, QC types,
sample types), analyte naming and the client fields. Phase 1: the rows are
laid out in the default format's columns (edd_profiles); per-column
converters and other layouts are phase 2.

QC type, qualifier and sample-type codes: the profile's maps.
Result type codes: TRG (target), TIC (NC-flagged analyte), IS, SUR.
"""
from __future__ import absolute_import, print_function, unicode_literals

import csv
import io
import logging
from datetime import datetime

from senaite.pfas import edd_profiles as _formats
from senaite.pfas.edd_store import (
    SAMPLE_TYPE_KEY,
    client_field,
    get_client_settings,
    get_edd_profile_for_client,
    method_codes,
    profile_analyte_cas,
    profile_tic_keywords,
    profile_qc_type_dict,
    profile_qualifier_dict,
    section,
)

logger = logging.getLogger("senaite.pfas.edd_builder")


# The row layout -- columns, required fields, formatting and the per-row
# checks -- is the default format's (edd_profiles; pure, testable without
# Zope). Phase 1: every profile is laid out in it.
_FMT = _formats.FORMATS[_formats.DEFAULT_PROFILE_ID]
EDD_COLUMNS = _FMT.EDD_COLUMNS
_LAB_REQUIRED, _QC_REQUIRED = _FMT._LAB_REQUIRED, _FMT._QC_REQUIRED
_SOLID_SAMPLE_TYPES = _FMT._SOLID_SAMPLE_TYPES
_fmt_date, _fmt_time, _get_units = _FMT._fmt_date, _FMT._fmt_time, _FMT._get_units
_row_to_list, _validate_row = _FMT._row_to_list, _FMT._validate_row
WEIGHT_BASES = _FMT.WEIGHT_BASES


def weight_basis_for(weight_basis_map, matrix_title):
    """The format's WEIGHT_BASIS code the lab set for this matrix, or None
    when none is set or the value is not one of the format's codes."""
    code = ((weight_basis_map or {}).get(matrix_title or u"") or u"").strip().upper()
    return code if code in WEIGHT_BASES else None


class EDDBuilder(object):
    """
    Reads SENAITE batch/AR data and produces the EDD file of the client's
    profile.

    Usage:
        builder = EDDBuilder(portal)
        csv_str, errors = builder.generate_from_batch(batch_obj)
        filename = builder.filename_for_batch(batch_obj, client_cfg)
    """

    def __init__(self, portal):
        self.portal = portal
        self._use_profile({})

    def _use_profile(self, client_cfg):
        """Everything the export reads comes from the client's profile: its
        defaults, method codes, code maps, analyte naming and valid codes
        (the CAS stays single-sourced in analyte_reference)."""
        self._edd_profile_id, self._edd_profile = \
            get_edd_profile_for_client(self.portal, client_cfg)
        prof = self._edd_profile
        self._lab_cfg = section(prof, "defaults") or {}
        self._qualifier_dict = profile_qualifier_dict(prof)
        self._qc_type_dict = profile_qc_type_dict(prof)
        self._analyte_cas = profile_analyte_cas(prof)
        self._tic = profile_tic_keywords(prof)
        # the format's valid concentration qualifiers: the profile's own
        # list, else its value list
        fmt = _formats.format_of(prof)
        self._valid_qualifiers = set(prof.get("valid_qualifiers") or
                                     (section(prof, "value_lists") or {}).get(fmt.QUALIFIER_LIST) or [])

    def _get_method_cfg(self, method_id):
        return method_codes(self._edd_profile, method_id)

    def _translate_qualifier(self, our_qual):
        if not our_qual:
            return ""
        return self._qualifier_dict.get(our_qual, our_qual)

    def _issue_qualifiers(self, codes, sample_id, keyword):
        """The state's LAB_QUALIFIER for a result's internal codes: each translated through the state profile's qualifier
        map, distinct, joined by the profile's `qualifier_separator` (default
        none: "U" + "J" -> "UJ"). An internal code with no state mapping, or
        a result that is not one of the state's valid codes, is a BLOCKING
        validation error: the EDD never passes an internal code through."""
        prof = getattr(self, "_edd_profile", None) or {}
        out = []
        for code in codes:
            if code not in self._qualifier_dict or not self._qualifier_dict[code]:
                self._qualifier_errors.append({
                    "row": 0, "field": "LAB_QUALIFIER", "type": "BLOCKING",
                    "message": "{0} {1}: internal qualifier {2!r} has no {3} code -- map it "
                               "in EDD Configuration (qualifier map)".format(
                                   sample_id, keyword, code, prof.get("state") or "state")})
                continue
            mapped = self._qualifier_dict[code]
            if mapped not in out:
                out.append(mapped)
        issued = (prof.get("qualifier_separator") or "").join(out)
        valid = self._valid_qualifiers
        if issued and valid and issued not in valid:
            self._qualifier_errors.append({
                "row": 0, "field": "LAB_QUALIFIER", "type": "BLOCKING",
                "message": "{0} {1}: {2!r} (from {3}) is not a valid {4} qualifier -- map "
                           "the combination in EDD Configuration".format(
                               sample_id, keyword, issued, ", ".join(codes),
                               prof.get("state") or "state")})
        return issued

    def _acquired(self, analysis):
        """When the analysis's result was acquired on the instrument (the
        worker's push log), else when it was captured in SENAITE."""
        from bika.lims import api as _a
        uid = _a.get_uid(analysis)
        if not hasattr(self, "_acq_by_uid"):
            self._acq_by_uid = {}
            try:
                import sqlite3
                from senaite.pfas.qc.store import DEFAULT_DB_PATH
                conn = sqlite3.connect(DEFAULT_DB_PATH)
                try:
                    for a_uid, at in conn.execute(
                            "SELECT analysis_uid, acquired_at FROM result_pushes "
                            "WHERE ok=1 AND acquired_at != ''"):
                        self._acq_by_uid[a_uid] = at
                finally:
                    conn.close()
            except Exception as exc:                        # noqa: BLE001
                logger.warning("EDD: acquisition times unreadable: %s", exc)
        at = self._acq_by_uid.get(uid)
        if at:
            try:
                return datetime.strptime(at[:19], "%Y-%m-%dT%H:%M:%S")
            except ValueError:
                pass
        try:
            return analysis.getResultCaptureDate()
        except AttributeError:
            return None

    def _extracted(self, analysis):
        """When the analysis's extraction (its worksheet's guided extraction)
        was finished; None when it was not."""
        try:
            ws = analysis.getWorksheet()
        except Exception:                                   # noqa: BLE001
            ws = None
        if ws is None:
            return None
        from senaite.pfas.browser.extraction_guide import _load_session
        from senaite.pfas import lab_time
        at = (_load_session(ws) or {}).get("finalized_at") or u""
        try:
            when = datetime.strptime(at[:19], "%Y-%m-%dT%H:%M:%S") if at else None
        except ValueError:
            return None
        zone = lab_time.get_zone(self.portal)
        if when is not None and not zone and not getattr(self, "_tz_warned", False):
            self._tz_warned = True
            self._qualifier_errors.append({
                "row": 0, "field": "PREP_DATE", "type": "Lab",
                "message": "The laboratory time zone is not set (Site Settings): prep "
                           "dates are UTC while analysis dates are the instrument's clock."})
        # recorded in UTC; the analysis date is on the laboratory's clock
        return lab_time.to_lab(when, zone)

    def _translate_qc_type(self, our_qc):
        if not our_qc:
            return "NA"
        return self._qc_type_dict.get(our_qc, our_qc)

    def _result_type_code(self, keyword, analysis_type="target"):
        if analysis_type in ("IS", "internal_standard"):
            return "IS"
        if analysis_type in ("SUR", "surrogate"):
            return "SUR"
        if keyword in self._tic:
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
        client_cfg = get_client_settings(client_obj) if client_obj is not None else {}

        if not per_report_override:
            return ("", [], "")

        # the client's profile first: everything below reads it
        self._use_profile(client_cfg)
        lab = self._lab_cfg
        project_site = (
            client_field(client_cfg, "project_site") or
            (client_obj.Title() if client_obj else "") or
            ""
        )
        analysis_lab = (
            client_field(client_cfg, "analysis_lab_override") or
            lab.get("analysis_lab_code") or
            ""
        )
        default_sample_type = client_field(client_cfg, "default_sample_type", "GW")
        self._unmapped_matrices = set()
        self._unset_weight_basis = set()
        self._rounding_errors = []
        self._qualifier_errors = []
        self._tz_warned = False

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
            full_vals = _row_to_list(rd)          # the format's superset order
            # validation runs on the FULL superset (the format's semantics);
            # output is then subset/reordered/aliased per the profile
            errs = _validate_row(full_vals, row_number, is_qc)
            all_errors.extend(errs)
            csv_rows.append([full_vals[idx[c]] for c in out_cols])

        all_errors.extend(getattr(self, "_rounding_errors", []))
        all_errors.extend(getattr(self, "_qualifier_errors", []))
        for matrix in sorted(getattr(self, "_unmapped_matrices", set())):
            all_errors.append({
                "row": 0,
                "field": "SAMPLE_TYPE",
                "message": (
                    "No sample-type code configured for matrix {0!r} — "
                    "set it in the EDD profile's matrix map. Exporting "
                    "without it would state the wrong matrix.".format(matrix)),
                "type": "Lab",
            })

        for matrix in sorted(getattr(self, "_unset_weight_basis", set())):
            all_errors.append({
                "row": 0,
                "field": "WEIGHT_BASIS",
                "message": (
                    "No weight basis set for matrix {0!r} -- choose WET, DRY, "
                    "LIP or NA in the EDD profile.".format(matrix)),
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
        """Method PROFILE id for a batch: the ONE resolver (batch_method.py; core first)."""
        from senaite.pfas import batch_method as bm
        return bm.resolve(batch_obj)[0]

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
            sample_type_code = ar_ann.get(SAMPLE_TYPE_KEY, "")
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
            # the CoC's field QC (a field reagent blank, a field duplicate):
            # exported as a client sample before
            try:
                from senaite.pfas.coc_records import FIELD_QC_CODES
                fq = ar.getField("FieldQCType").get(ar) if ar.getField("FieldQCType") else u""
                our_qc_type = FIELD_QC_CODES.get(fq or u"", "")
            except Exception:                               # noqa: BLE001
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

        code_qc_type = self._translate_qc_type(our_qc_type)
        is_qc_sample = code_qc_type != "NA"

        # A QC sample carries the matrix of the batch it belongs to. It was
        # hardcoded to AQ (aqueous) regardless — so a matrix spike extracted
        # from feed alongside the field samples was submitted as aqueous while
        # those samples went as FE. QC_TYPE is what marks a row as QC; the
        # matrix column should say what the matrix was.
        if is_qc_sample:
            edd_sample_type = sample_type_code
            edd_spn = "QC"
            edd_scm = "NA"
            edd_location = "NA"
        else:
            edd_sample_type = sample_type_code
            edd_spn = sample_point_name or lab_sample_id
            edd_scm = lab.get("default_sample_collection_method", "LFS")
            edd_location = "NA"

        # Analysis / prep dates are set per analysis below: its injection's
        # acquisition time and its extraction's finish. They were the release
        # time and blank.

        # Method info — the BATCH's method profile governs TEST/prep/units.
        # ar.getMethod() returns the CORE Method object; map it to the
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
        # wins; the profile's method unit codes otherwise.
        units = ""
        matrix_title = ""
        try:
            st = ar.getSampleType()
            matrix_title = st.Title() if st else ""
            if method_id and matrix_title:
                from senaite.pfas.method_profile_store import get_profile
                umap = (get_profile(self.portal, method_id) or {}).get(
                    "unit_map") or {}
                u = umap.get(matrix_title, "")
                if u:
                    # the value is in this unit; relabelling it (ng/g as
                    # NG/KG) would report it 1000x off
                    units = u.upper()
        except Exception:
            pass
        if not units:
            units = _get_units(method_id, edd_sample_type, method_cfg)

        # the basis the lab reports this matrix on (profile, per matrix);
        # none set, or not one of the format's codes: the export refuses
        weight_basis = weight_basis_for(
            (getattr(self, "_edd_profile", {}) or {}).get("weight_basis_map"),
            matrix_title)
        if weight_basis is None:
            self._unset_weight_basis.add(matrix_title or "(no sample type)")
            weight_basis = ""

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
        # the certificate's own rows: the same ROUNDED result, RL / MDL from
        # the method profile and non-detect decision
        cert, reported = self._certificate_rows(ar)

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
            # A neat reading replaced by its dilution is reported by the
            # retest, with the dilution's factor.
            dilution_factor = 1
            try:
                if analysis.isRetested():
                    continue
                if analysis.isRetest():
                    from senaite.pfas.browser.dilution_retests import _load
                    rec = _load(analysis.getRetestOf()) or {}
                    dilution_factor = rec.get("factor") or 1
            except Exception:                               # noqa: BLE001
                pass

            # Only what the certificate reports, as it reports it: the
            # rounded result (a non-detect is decided on it), and the RL / MDL
            # of the method profile, rounded alike and already scaled by the
            # dilution. Never an unrounded or interim-field value.
            from bika.lims import api as _uapi
            if _uapi.get_uid(analysis) not in reported:
                continue
            row_c = cert.get(keyword)
            if row_c is None:
                continue
            conc = row_c["result"] if row_c["detected"] else None
            rl = row_c["rl"] or None
            mdl_val = row_c["mdl"] or None
            # every internal code the certificate prints for this result (U
            # for a non-detect, the QC qualification codes), plus an interim
            # qualifier; each is issued as the STATE's code
            codes = ["N.D."] if row_c["detected"] is False else []
            codes += [c.strip() for c in (row_c.get("qualifiers") or "").split(",")
                      if c.strip() and c.strip() != "U"]
            for interim in interims:
                k = (interim.get("keyword") or "").lower()
                if k in ("qualifier", "lab_qualifier") and interim.get("value"):
                    codes.append(str(interim.get("value")))

            code_qual = self._issue_qualifiers(codes, lab_sample_id, keyword)

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

            analysis_date = analysis_time = self._acquired(analysis)
            prep_date = prep_time = self._extracted(analysis)

            row = {
                "project_site": project_site,
                "sample_point_name": edd_spn,
                "sample_id": client_sample_id,
                "lab_sample_id": lab_sample_id,
                "analysis_lab": analysis_lab,
                "sample_date": sample_date,
                "sample_time": sample_time,
                "sample_type": edd_sample_type,
                "qc_type": code_qc_type,
                "result_type_code": rtc,
                "cas_no": cas_no,
                "parameter_name": parameter_name,
                "concentration": conc,
                "lab_qualifier": code_qual,
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
                "dilution_factor": dilution_factor,
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

    def _certificate_rows(self, ar):
        """({keyword: certificate row}, {uid of each reported analysis}) as
        the certificate assembles them (PFASCoASectionsView._sample). A
        sample the certificate cannot assemble yields no rows and a BLOCKING
        validation error: the EDD never falls back to unrounded values."""
        from bika.lims import api
        from senaite.pfas.browser.coa_sections import PFASCoASectionsView
        view = PFASCoASectionsView(self.portal, getattr(self.portal, "REQUEST", None))
        try:
            smp = view._sample(ar)
            reported = set(api.get_uid(a) for a in view._analyses(ar))
        except Exception as exc:                            # noqa: BLE001
            smp, reported = {"error": u"%s" % exc}, set()
        if smp.get("error"):
            self._rounding_errors.append({
                "row": 0, "field": "CONCENTRATION", "type": "BLOCKING",
                "message": "{0}: no rows -- the certificate cannot assemble this sample "
                           "({1})".format(api.get_id(ar), smp["error"])})
            return {}, set()
        return dict((r["keyword"], r) for r in smp.get("rows") or []), reported

    def filename_for_batch(self, batch_id, client_cfg=None):
        """
        Filename convention: {CLIENT_ID}_{SDG}_{YYYYMMDD}_EDD.csv
        Falls back to batch_id if client info unavailable.
        """
        from datetime import date
        today = date.today().strftime("%Y%m%d")
        if client_cfg:
            self._use_profile(client_cfg)
        sdg = self._build_sdg(batch_id).replace("/", "-").replace(" ", "_")
        client_id = ""
        if client_field(client_cfg, "project_site"):
            client_id = client_field(client_cfg, "project_site").replace(" ", "_")[:20]
        if client_id:
            return u"{0}_{1}_{2}_EDD.csv".format(client_id, sdg, today)
        return u"{0}_{1}_EDD.csv".format(sdg, today)

    @staticmethod
    def format_validation_report(errors):
        """Return a human-readable text report of validation errors."""
        if not errors:
            return u"Validation PASSED — no errors found.\n"
        lines = [u"EDD Validation Report", u"=" * 50, u""]
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
