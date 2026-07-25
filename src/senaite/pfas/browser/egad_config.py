# -*- coding: utf-8 -*-
"""
EGAD EDD configuration panel — browser views.

Python 2.7 compatible.  No f-strings, no pathlib, no annotations.

Views:
  @@pfas-egad-config          GET=show config panel, POST=save section
  @@pfas-egad-export          GET=download EDD CSV for a batch
  @@pfas-egad-client-config   GET/POST per-client EGAD settings
  @@pfas-egad-batches         GET=batch EDD dashboard; ?batch_id=X = sample type editor
                              POST=save per-sample EGAD SAMPLE_TYPE overrides

Roles required: Manager, LabManager, Owner
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import logging

from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.egad_store import (
    DEFAULT_ANALYTE_CAS,
    DEFAULT_QC_TYPE_MAP,
    get_analyte_cas,
    get_lab_config,
    get_lookups,
    get_method_egad,
    get_qualifier_map,
    get_qc_type_map,
    refresh_lookups_from_xlsx,
    save_analyte_cas,
    save_lab_config,
    save_method_egad,
    save_qualifier_map,
    save_qc_type_map,
    get_client_egad,
    save_client_egad,
)

logger = logging.getLogger("senaite.pfas.browser.egad_config")

_ALLOWED_ROLES = frozenset(("Manager", "LabManager", "Owner"))

_METHODS = ("EPA_537_1", "EPA_1633A", "FDA_32PFAS")

_METHOD_LABELS = {
    "EPA_537_1":  "EPA 537.1 Drinking Water",
    "EPA_1633A":  "EPA 1633A Multi-Matrix",
    "FDA_32PFAS": "FDA 32-PFAS in Food",
}

# Ordered analyte list for the CAS table (same order as method_profile_store)
_ANALYTE_ORDER = [
    "PFBA", "PFPeA", "PFHxA", "PFHpA", "PFOA", "PFNA", "PFDA",
    "PFUDA", "PFDoA", "PFTrDA", "PFTeDA", "PFHxDA", "PFODA",
    "PFBS", "PFPeS", "PFHxS", "br-PFHxS", "PFHpS",
    "PFOS", "br-PFOS", "PFNS", "PFDS", "PFUnDS", "PFDoS", "PFTrDS",
    "FOSA", "GenX", "DONA",
    "4:2FTS", "6:2FTS", "8:2FTS", "10:2FTS",
    "9ClPF3ONS", "11ClPF3OUdS",
]

# Human-readable analyte titles for display
_ANALYTE_TITLES = {
    "PFBA": "PFBA", "PFPeA": "PFPeA", "PFHxA": "PFHxA",
    "PFHpA": "PFHpA", "PFOA": "PFOA", "PFNA": "PFNA",
    "PFDA": "PFDA", "PFUDA": "PFUDA", "PFDoA": "PFDoA",
    "PFTrDA": "PFTrDA", "PFTeDA": "PFTeDA", "PFHxDA": "PFHxDA",
    "PFODA": "PFODA", "PFBS": "PFBS", "PFPeS": "PFPeS",
    "PFHxS": "lr-PFHxS", "br-PFHxS": "br-PFHxS",
    "PFHpS": "PFHpS", "PFOS": "lr-PFOS", "br-PFOS": "br-PFOS",
    "PFNS": "PFNS", "PFDS": "PFDS", "PFUnDS": "PFUnDS",
    "PFDoS": "PFDoS", "PFTrDS": "PFTrDS",
    "FOSA": "FOSA", "GenX": "GenX (HFPO-DA)", "DONA": "DONA",
    "4:2FTS": "4:2 FTS", "6:2FTS": "6:2 FTS",
    "8:2FTS": "8:2 FTS", "10:2FTS": "10:2 FTS",
    "9ClPF3ONS": "9Cl-PF3ONS", "11ClPF3OUdS": "11Cl-PF3OUdS",
}

# Analytes whose real CAS is NOT accepted by Maine EGAD's CAS_LUP, so a
# Maine-issued DEP##### code must be entered manually. The guidance clears once
# a DEP code is present (see analyte_cas_rows). PFTrDS was removed: its CAS
# (791563-89-8) is now confirmed and accepted (DECISIONS D-line 526), so it no
# longer needs manual entry.
_NEEDS_MANUAL_CAS = frozenset(["PFUnDS"])


def _require_manager(context, request):
    try:
        from AccessControl import getSecurityManager
        user = getSecurityManager().getUser()
        roles = user.getRolesInContext(context)
        return bool(_ALLOWED_ROLES.intersection(roles))
    except Exception:
        return False


def _portal(context):
    return context.portal_url.getPortalObject()


# ── Main config panel ─────────────────────────────────────────────────────────

class PFASEGADConfigView(BrowserView):
    """
    EGAD EDD configuration panel.

    Tabs:
      lab       — lab-global settings (analysis_lab_code, prep_method, etc.)
      methods   — per-method TEST code, units, prep method
      cas       — analyte → EGAD CAS_NO + PARAMETER_NAME table
      qualifiers — our qualifier → EGAD qualifier code
      qc_types  — our QC type → EGAD QC type code
      lookups   — refreshable lookup tables (upload new XLSX)
    """

    template = ViewPageTemplateFile("templates/egad_config.pt")

    def __call__(self):
        flatten_form(self.request)
        if not _require_manager(self.context, self.request):
            self.request.response.setStatus(403)
            return "Forbidden: Manager, LabManager, or Owner role required"

        if self.request.method == "POST":
            return self._handle_post()

        return self.template()

    def _handle_post(self):
        form = self.request.form
        portal = _portal(self.context)
        section = form.get("section", "")

        if section == "edd_profiles":
            from senaite.pfas.egad_store import (
                get_edd_profiles, save_edd_profile, clone_edd_profile)
            import re as _re
            f = self.request.form
            act = f.get("edd_action", "")
            if act == "clone":
                src = f.get("source_id", "maine_egad")
                name = (f.get("new_name") or "").strip() or "New EDD profile"
                pid = _re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_")
                clone_edd_profile(portal, src, pid, name)
            elif act == "save":
                pid = f.get("profile_id", "")
                profs = get_edd_profiles(portal)
                prof = profs.get(pid)
                if prof is not None:
                    prof["name"] = (f.get("name") or prof.get("name") or pid)
                    prof["state"] = (f.get("state") or
                                     prof.get("state") or "").strip()
                    cols = [c.strip() for c in
                            (f.get("columns") or "").splitlines() if c.strip()]
                    if cols:
                        prof["columns"] = cols
                    # D63: state vocabulary — JSON blocks for the state's own
                    # qualifier/QC maps and analyte naming/coding. Bad JSON is
                    # ignored (keeps the prior value) rather than clobbering.
                    for field, key in (
                        ("matrix_map_json", "matrix_map"),
                        ("aliases_json", "aliases"),
                        ("qualifier_map_json", "qualifier_map"),
                        ("qc_type_map_json", "qc_type_map"),
                        ("analyte_naming_json", "analyte_naming"),
                    ):
                        raw = f.get(field)
                        if raw is None or not raw.strip():
                            continue
                        try:
                            prof[key] = json.loads(raw)
                        except (ValueError, TypeError):
                            pass
                    save_edd_profile(portal, pid, prof)
            self.request.response.redirect(
                "{0}/@@pfas-egad-config?saved=1#edd-profiles".format(
                    portal.absolute_url()))
            return u""
        if section == "lab":
            data = {
                "analysis_lab_code": form.get("analysis_lab_code", "").strip(),
                "default_prep_method": form.get("default_prep_method", "SW3535").strip(),
                "default_sample_collection_method": form.get("default_sample_collection_method", "LFS").strip(),
                "default_treatment_status": form.get("default_treatment_status", "N").strip(),
                "default_parameter_filtered": form.get("default_parameter_filtered", "U").strip(),
                "sdg_prefix": form.get("sdg_prefix", "").strip(),
                "sdg_format": form.get("sdg_format", "{prefix}{batch_id}").strip(),
                "sampled_by": form.get("sampled_by", "").strip(),
            }
            save_lab_config(portal, data)
            self.request.response.setStatus(200)
            return json.dumps({"status": "ok", "section": "lab"})

        elif section == "methods":
            method_egad = get_method_egad(portal)
            for mid in _METHODS:
                method_egad[mid]["test_code"] = form.get("{0}_test_code".format(mid), "").strip()
                method_egad[mid]["prep_method"] = form.get("{0}_prep_method".format(mid), "SW3535").strip()
                method_egad[mid]["units_water"] = form.get("{0}_units_water".format(mid), "NG/L").strip()
                method_egad[mid]["units_solid"] = form.get("{0}_units_solid".format(mid), "NG/KG").strip()
            save_method_egad(portal, method_egad)
            return json.dumps({"status": "ok", "section": "methods"})

        elif section == "cas":
            cas_data = get_analyte_cas(portal)
            # Each analyte row submits: cas_<kw>, param_<kw>, note_<kw>
            for kw in _ANALYTE_ORDER:
                safe_kw = kw.replace(":", "_").replace("-", "_").replace(" ", "_")
                cas_no = form.get("cas_{0}".format(safe_kw), "").strip()
                param_name = form.get("param_{0}".format(safe_kw), "").strip()
                note = form.get("note_{0}".format(safe_kw), "").strip()
                if kw in cas_data:
                    cas_data[kw]["cas_no"] = cas_no
                    cas_data[kw]["parameter_name"] = param_name
                    cas_data[kw]["override_note"] = note
                else:
                    cas_data[kw] = {"cas_no": cas_no, "parameter_name": param_name, "override_note": note}
            save_analyte_cas(portal, cas_data)
            return json.dumps({"status": "ok", "section": "cas"})

        elif section == "qualifiers":
            rows_json = form.get("qualifier_rows_json", "[]")
            try:
                rows = json.loads(rows_json)
            except ValueError:
                rows = []
            save_qualifier_map(portal, rows)
            return json.dumps({"status": "ok", "section": "qualifiers"})

        elif section == "qc_types":
            rows_json = form.get("qc_type_rows_json", "[]")
            try:
                rows = json.loads(rows_json)
            except ValueError:
                rows = []
            save_qc_type_map(portal, rows)
            return json.dumps({"status": "ok", "section": "qc_types"})

        elif section == "lookups":
            # File upload
            uploaded = self.request.get("lookup_xlsx")
            if uploaded and hasattr(uploaded, "read"):
                xlsx_bytes = uploaded.read()
                result = refresh_lookups_from_xlsx(portal, xlsx_bytes)
                return json.dumps({"status": "ok", "section": "lookups", "result": result})
            return json.dumps({"status": "error", "message": "No file uploaded"})

        return json.dumps({"status": "error", "message": "Unknown section: " + section})

    # ── Template helper methods ───────────────────────────────────────────────

    def portal_url(self):
        return _portal(self.context).absolute_url()

    def active_tab(self):
        return self.request.get("tab", "lab")

    def lab_config(self):
        return get_lab_config(_portal(self.context))

    def method_egad(self):
        return get_method_egad(_portal(self.context))

    def method_list(self):
        cfg = self.method_egad()
        result = []
        for mid in _METHODS:
            entry = cfg.get(mid, {})
            entry["method_id"] = mid
            entry["label"] = _METHOD_LABELS.get(mid, mid)
            result.append(entry)
        return result

    def analyte_cas_rows(self):
        cas_data = get_analyte_cas(_portal(self.context))
        rows = []
        for kw in _ANALYTE_ORDER:
            entry = cas_data.get(kw, {"cas_no": "", "parameter_name": "", "override_note": ""})
            safe_kw = kw.replace(":", "_").replace("-", "_").replace(" ", "_")
            is_blank = not entry.get("cas_no", "")
            is_placeholder = str(entry.get("cas_no", "")).upper() == "PLACEHOLDER"
            is_blocking = is_blank or is_placeholder
            # "Manual DEP code" guidance is DATA-DRIVEN, not a permanent label:
            # for a manual-required analyte (real CAS Maine won't accept) it
            # shows until a Maine DEP##### code is actually entered, then it
            # auto-clears. Was hardcoded frozenset membership that persisted
            # forever regardless of the data — a §1 defect.
            cas_val = str(entry.get("cas_no", "") or "").upper()
            needs_manual = (kw in _NEEDS_MANUAL_CAS
                            and not cas_val.startswith("DEP"))
            rows.append({
                "keyword": kw,
                "safe_keyword": safe_kw,
                "title": _ANALYTE_TITLES.get(kw, kw),
                "cas_no": entry.get("cas_no", ""),
                "parameter_name": entry.get("parameter_name", ""),
                "override_note": entry.get("override_note", ""),
                "needs_manual": needs_manual,
                "is_blank": is_blank,
                "is_placeholder": is_placeholder,
                "is_blocking": is_blocking,
            })
        return rows

    def qualifier_map(self):
        return get_qualifier_map(_portal(self.context))

    def qc_type_map(self):
        return get_qc_type_map(_portal(self.context))

    def egad_qualifier_codes(self):
        lookups = get_lookups(_portal(self.context))
        return sorted(lookups.get("concentration_qualifiers", []))

    def egad_qc_type_codes(self):
        lookups = get_lookups(_portal(self.context))
        return sorted(lookups.get("qc_types", []))

    def lookups_info(self):
        lookups = get_lookups(_portal(self.context))
        return {
            "last_refresh": lookups.get("last_refresh", ""),
            "last_refresh_filename": lookups.get("last_refresh_filename", ""),
            "qualifier_count": len(lookups.get("concentration_qualifiers", [])),
            "qc_type_count": len(lookups.get("qc_types", [])),
            "sample_type_count": len(lookups.get("sample_types", [])),
            "units_count": len(lookups.get("units", [])),
            "analysis_lab_count": len(lookups.get("analysis_labs", [])),
            "test_count": len(lookups.get("tests", [])),
            "prep_method_count": len(lookups.get("prep_methods", [])),
        }

    def default_qc_type_map_json(self):
        return json.dumps(DEFAULT_QC_TYPE_MAP)

    def blocking_cas_count(self):
        rows = self.analyte_cas_rows()
        return sum(1 for r in rows if r["is_blocking"])

    def analysis_lab_options(self):
        lookups = get_lookups(_portal(self.context))
        return sorted(lookups.get("analysis_labs", []))

    def test_options(self):
        lookups = get_lookups(_portal(self.context))
        return sorted(lookups.get("tests", []))

    def prep_method_options(self):
        lookups = get_lookups(_portal(self.context))
        return sorted(lookups.get("prep_methods", []))

    def sample_collection_method_options(self):
        lookups = get_lookups(_portal(self.context))
        return sorted(lookups.get("sample_collection_methods", []))


# ── Per-client EGAD settings ──────────────────────────────────────────────────

    def edd_profiles(self):
        from senaite.pfas.egad_store import get_edd_profiles
        profs = get_edd_profiles(_portal(self.context))
        out = []
        for k, v in sorted(profs.items()):
            out.append({
                "id": k, "name": v.get("name", k), "base": v.get("base", ""),
                "state": v.get("state", ""),
                "n_columns": len(v.get("columns") or []),
                "columns_text": "\n".join(v.get("columns") or []),
                "matrix_map_json": json.dumps(v.get("matrix_map") or {},
                                              indent=1, sort_keys=True),
                "aliases_json": json.dumps(v.get("aliases") or {},
                                           indent=1, sort_keys=True),
                "qualifier_map_json": json.dumps(v.get("qualifier_map") or [],
                                                 indent=1),
                "qc_type_map_json": json.dumps(v.get("qc_type_map") or [],
                                               indent=1),
                "analyte_naming_json": json.dumps(v.get("analyte_naming") or {},
                                                  indent=1, sort_keys=True),
            })
        return out


class PFASEGADClientConfigView(BrowserView):
    """
    Per-client EGAD toggle and settings.
    Accessed from the client record or from the EGAD config panel.
    """

    template = ViewPageTemplateFile("templates/egad_client_config.pt")

    def __call__(self):
        flatten_form(self.request)
        if not _require_manager(self.context, self.request):
            self.request.response.setStatus(403)
            return "Forbidden"

        if self.request.method == "POST":
            return self._handle_post()

        return self.template()

    def _handle_post(self):
        form = self.request.form
        # The context should be the Client object
        data = {
            "egad_enabled": bool(form.get("egad_enabled")),
            "project_site": form.get("project_site", "").strip(),
            "default_sample_type": form.get("default_sample_type", "GW").strip(),
            "analysis_lab_override": form.get("analysis_lab_override", "").strip(),
            "per_report_override_default": bool(form.get("per_report_override_default", True)),
            "edd_profile": form.get("edd_profile", "maine_egad").strip() or "maine_egad",
        }
        save_client_egad(self.context, data)
        self.request.response.redirect(
            self.context.absolute_url() + "/@@pfas-egad-client-config?saved=1"
        )

    def client_egad_config(self):
        return get_client_egad(self.context)

    def edd_profile_options(self):
        from senaite.pfas.egad_store import get_edd_profiles
        profs = get_edd_profiles(_portal(self.context))
        return [{"id": k, "name": v.get("name", k)}
                for k, v in sorted(profs.items())]

    def portal_url(self):
        return _portal(self.context).absolute_url()

    def sample_type_options(self):
        lookups = get_lookups(_portal(self.context))
        return sorted(lookups.get("sample_types", ["GW", "SW", "AQ"]))


    def analysis_lab_options(self):
        lookups = get_lookups(_portal(self.context))
        return sorted(lookups.get("analysis_labs", []))

    def saved(self):
        return bool(self.request.get("saved"))


# ── EDD export ────────────────────────────────────────────────────────────────

class PFASEGADExportView(BrowserView):
    """
    Generate and return an EGAD EDD CSV for a batch.

    GET @@pfas-egad-export?batch_id=B20260615-001
        → returns CSV download if no validation blocking errors
        → returns JSON validation report if blocking errors exist

    GET @@pfas-egad-export?batch_id=...&preview=1
        → returns JSON with validation_report text (no download)
    """

    def __call__(self):
        flatten_form(self.request)
        if not _require_manager(self.context, self.request):
            self.request.response.setStatus(403)
            return "Forbidden"

        batch_id = self.request.get("batch_id", "")
        preview = bool(self.request.get("preview"))

        if not batch_id:
            return json.dumps({"error": "batch_id is required"})

        portal = _portal(self.context)

        # Look up batch object
        batch_obj = None
        try:
            from bika.lims.catalog import CATALOG_ANALYSIS_REQUEST_LISTING
            pc = portal.portal_catalog
            brains = pc({"portal_type": "Batch", "id": batch_id})
            if brains:
                batch_obj = brains[0].getObject()
        except Exception as exc:
            logger.error("Cannot look up batch %s: %s", batch_id, exc)

        if batch_obj is None:
            # Batches are not reliably indexed in portal_catalog (SENAITE 2.x
            # uses its own catalogs) — resolve directly from the folder.
            try:
                batch_obj = portal["batches"].get(batch_id)
            except Exception:
                batch_obj = None
        if batch_obj is None:
            return json.dumps({"error": "Batch not found: " + batch_id})

        # Get client
        client_obj = None
        try:
            client_obj = batch_obj.getClient()
        except AttributeError:
            pass
        if client_obj is None:
            # batches aren't always client-linked — derive from the batch's
            # first sample (AR.getClient), the same join the EDD rows use
            try:
                from Products.CMFCore.utils import getToolByName
                cat = getToolByName(portal, "senaite_catalog_sample")
                brains = cat(portal_type="AnalysisRequest",
                             getBatchUID=batch_obj.UID())
                if brains:
                    client_obj = brains[0].getObject().getClient()
            except Exception:
                client_obj = None

        from senaite.pfas.egad_builder import EGADBuilder
        builder = EGADBuilder(portal)

        per_report = not bool(self.request.get("suppress"))
        client_cfg = get_client_egad(client_obj) if client_obj else {}

        csv_str, errors, filename = builder.generate_from_batch(
            batch_obj,
            client_obj=client_obj,
            per_report_override=per_report,
        )

        blocking = [e for e in errors if e.get("type") == "BLOCKING"]
        report_text = builder.format_validation_report(errors)

        if preview:
            return json.dumps({
                "batch_id": batch_id,
                "filename": filename,
                "row_count": csv_str.count("\r\n") - 1 if csv_str else 0,
                "blocking_count": len(blocking),
                "error_count": len(errors),
                "validation_report": report_text,
                "has_csv": bool(csv_str),
            })

        if blocking:
            self.request.response.setHeader("Content-Type", "application/json")
            return json.dumps({
                "error": "BLOCKING validation errors — cannot generate EDD",
                "blocking_errors": [e["message"] for e in blocking],
                "validation_report": report_text,
            })

        # Return CSV download
        filename_safe = filename or (batch_id + "_EDD.csv")
        self.request.response.setHeader(
            "Content-Type", "text/csv; charset=utf-8"
        )
        self.request.response.setHeader(
            "Content-Disposition",
            "attachment; filename=\"{0}\"".format(filename_safe)
        )
        if isinstance(csv_str, unicode):
            return csv_str.encode("utf-8")
        return csv_str


# ── Batch EDD Dashboard + Per-sample SAMPLE_TYPE editor ──────────────────────

class PFASEGADBatchesView(BrowserView):
    """
    @@pfas-egad-batches

    Without ?batch_id: lists recent batches with EDD status and download links.
    With ?batch_id=XXX: shows per-sample EGAD SAMPLE_TYPE editor for that batch.

    POST: saves per-sample SAMPLE_TYPE overrides (from the sample type editor).
    """

    template = ViewPageTemplateFile("templates/egad_batches.pt")

    def __call__(self):
        flatten_form(self.request)
        if not _require_manager(self.context, self.request):
            self.request.response.setStatus(403)
            return "Forbidden"

        if self.request.method == "POST":
            return self._handle_post()

        return self.template()

    def _handle_post(self):
        """Save per-sample EGAD SAMPLE_TYPE overrides and redirect back."""
        from senaite.pfas.browser.egad_publish import set_ar_sample_type
        portal = _portal(self.context)
        pc = getToolByName(portal, "portal_catalog")

        batch_id = self.request.form.get("batch_id", "")
        saved = 0

        for key, value in self.request.form.items():
            if key.startswith("sampletype_") and value:
                ar_id = key[len("sampletype_"):]
                try:
                    brains = pc(portal_type="AnalysisRequest", id=ar_id)
                    if brains:
                        ar_obj = brains[0].getObject()
                        set_ar_sample_type(ar_obj, value.strip().upper())
                        saved += 1
                except Exception as exc:
                    logger.warning("Cannot save EGAD sample type for AR %s: %s", ar_id, exc)

        redirect_url = "{0}/@@pfas-egad-batches?batch_id={1}&saved={2}".format(
            self.portal_url(), batch_id, saved
        )
        self.request.response.redirect(redirect_url)
        return ""

    def portal_url(self):
        return _portal(self.context).absolute_url()

    def batch_id(self):
        return self.request.get("batch_id", "")

    def saved_count(self):
        """Number of sample types just saved (from redirect param)."""
        try:
            return int(self.request.get("saved", 0))
        except (ValueError, TypeError):
            return 0

    def recent_batches(self):
        """
        Return list of recent batch dicts for the dashboard view.
        Sorted newest first, limited to 60 batches.
        """
        from senaite.pfas.browser.egad_publish import get_batch_edd
        portal = _portal(self.context)
        pc = getToolByName(portal, "portal_catalog")

        try:
            brains = pc(
                portal_type="Batch",
                sort_on="created",
                sort_order="descending",
                sort_limit=60,
            )
        except Exception as exc:
            logger.warning("Cannot list batches for EGAD dashboard: %s", exc)
            return []

        rows = []
        base = self.portal_url()
        for brain in brains:
            try:
                batch_obj = brain.getObject()
                bid = batch_obj.getId()

                client_obj = None
                try:
                    client_obj = batch_obj.getClient()
                except AttributeError:
                    pass

                client_cfg = get_client_egad(client_obj) if client_obj else {}
                egad_enabled = client_cfg.get("egad_enabled", False)

                stored = get_batch_edd(batch_obj)

                rows.append({
                    "batch_id":        bid,
                    "title":           batch_obj.Title() or bid,
                    "created":         brain.created.strftime("%Y-%m-%d"),
                    "client_title":    client_obj.Title() if client_obj else "",
                    "egad_enabled":    egad_enabled,
                    "has_edd":         stored is not None,
                    "edd_generated":   (stored or {}).get("generated", "")[:10],
                    "edd_filename":    (stored or {}).get("filename", ""),
                    "edd_error_count": (stored or {}).get("error_count", 0),
                    "edd_blocking":    (stored or {}).get("blocking_count", 0),
                    "download_url":    "{0}/@@pfas-egad-export?batch_id={1}".format(base, bid),
                    "preview_url":     "{0}/@@pfas-egad-export?batch_id={1}&preview=1".format(base, bid),
                    "sampletype_url":  "{0}/@@pfas-egad-batches?batch_id={1}".format(base, bid),
                })
            except Exception as exc:
                logger.warning("EGAD batch dashboard: error on batch %s: %s",
                               getattr(brain, "getId", lambda: "?")(), exc)

        return rows

    def batch_sample_types(self):
        """
        Return list of AR dicts for the per-batch sample type editor.
        Each dict includes: ar_id, ar_title, senaite_sample_type, egad_sample_type, field_name.
        """
        from senaite.pfas.browser.egad_publish import get_ar_sample_type
        bid = self.batch_id()
        if not bid:
            return []

        portal = _portal(self.context)
        pc = getToolByName(portal, "portal_catalog")

        # Derive client default sample type for this batch
        default_type = "GW"
        try:
            batch_brains = pc(portal_type="Batch", id=bid)
            if batch_brains:
                batch_obj = batch_brains[0].getObject()
                try:
                    client_obj = batch_obj.getClient()
                    if client_obj:
                        cfg = get_client_egad(client_obj)
                        default_type = cfg.get("default_sample_type", "GW") or "GW"
                except AttributeError:
                    pass
        except Exception:
            pass

        # Fetch ARs in this batch
        ar_brains = []
        for index_field in ("getBatchUID", "getBatch"):
            try:
                ar_brains = pc(portal_type="AnalysisRequest", **{index_field: bid})
                if ar_brains:
                    break
            except Exception:
                pass

        rows = []
        for brain in ar_brains:
            try:
                ar_obj = brain.getObject()
                ar_id = ar_obj.getId()
                st_obj = None
                try:
                    st_obj = ar_obj.getSampleType()
                except AttributeError:
                    pass
                rows.append({
                    "ar_id":                ar_id,
                    "ar_title":             ar_obj.Title() or ar_id,
                    "senaite_sample_type":  st_obj.Title() if st_obj else "",
                    "egad_sample_type":     get_ar_sample_type(ar_obj, default=default_type),
                    "field_name":           "sampletype_{0}".format(ar_id),
                })
            except Exception as exc:
                logger.warning("EGAD sample type editor: error on AR: %s", exc)

        return rows

    def sample_type_options(self):
        """EGAD SAMPLE_TYPE lookup codes for the dropdown."""
        from senaite.pfas.egad_store import DEFAULT_LOOKUPS
        try:
            lookups = get_lookups(_portal(self.context))
            codes = lookups.get("sample_types", DEFAULT_LOOKUPS.get("sample_types", []))
        except Exception:
            codes = DEFAULT_LOOKUPS.get("sample_types", [])
        return codes
