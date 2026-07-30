# -*- coding: utf-8 -*-
"""
PFAS per-batch logbooks.

Built-in logbooks (FM-ENV-250 through 253) each have a dedicated view with
specialist fields.  Custom logbooks added through the admin panel use the
generic PFASLogbookCustomView which renders fields based on their definition.

Logbook definitions (names, order, custom field config) are stored in ZODB
via logbook_store.py.  Data for each logbook per-batch is stored in
IAnnotations on the Batch object.

Annotation key pattern: "senaite.pfas.logbook.{slug}"
  slug "250"–"253"   → built-in logbooks
  slug "custom-xxx"  → user-created logbooks

Cal data is also exported to /data/qc/batches/{batch_uid}/cal_251.json
so the pipeline injection builder can read it.

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import logging
import os
from datetime import date

from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from zope.annotation.interfaces import IAnnotations
from senaite.pfas.browser.formutil import flatten_form

logger = logging.getLogger("senaite.pfas.browser.logbooks")

_KEY_PREFIX = u"senaite.pfas.logbook."

# Fields that support the GLP strike-through correction model (text/date/number only; not table rows)
_CORR_FIELDS_250 = ["prepared_by", "prepared_date", "ammonium_acetate_weight_g",
                     "balance_sn", "notes", "reviewed_by", "reviewed_date"]
_CORR_FIELDS_251 = ["prepared_by", "prepared_date", "pds_a_lot", "pds_b_lot",
                     "analyte_pds_lot", "analyte_spike_lot", "cal_a_lot",
                     "icv_conc_ng_ml", "ccv_conc_ng_ml", "diluent_is_conc",
                     "notes", "reviewed_by", "reviewed_date"]
_CORR_FIELDS_252 = ["analyst", "extraction_date", "notes", "reviewed_by", "reviewed_date"]
_CORR_FIELDS_253 = ["analyst", "processing_date", "balance_sn", "notes"]


def _apply_field_corrections(form, existing, fields, data):
    """
    Process GLP correction submissions.

    When `_corr_by_FNAME` is present in the form, the field is being corrected:
      - `_newval_FNAME`  = the corrected value (submitted instead of the disabled main input)
      - `_corr_by_FNAME` = initials of the person making the correction
    The original value is taken from `existing` and stored in `_corrections[FNAME]`.

    For non-corrected fields the caller already populated `data[fname]` from the
    normal form field; this function only overrides fields being corrected.
    """
    corrections = dict(existing.get("_corrections") or {})
    for fname in fields:
        corr_by = (form.get("_corr_by_" + fname) or u"").strip()
        if corr_by:
            new_val = (form.get("_newval_" + fname) or u"").strip()
            corrections[fname] = {
                u"original":     existing.get(fname, u""),
                u"corrected_by": corr_by,
                u"corrected_at": date.today().strftime("%Y-%m-%d"),
            }
            data[fname] = new_val
    data[u"_corrections"] = corrections
BATCHES_EXPORT_ROOT = os.environ.get("PFAS_BATCHES_PATH", "/data/qc/batches")

# Default cal points for FDA 32-PFAS (ng/mL) — DERIVED from the single-source
# ladder (analyte_reference.CAL_LADDERS, descending: CAL-1 = highest). Values
# identical to the previous hardcoded list; removes the 3rd duplicated (and
# once contradictory) copy of the FDA ladder.
from senaite.pfas.analyte_reference import get_cal_ladder as _get_cal_ladder

# Injection name prefix = the FDA method's core code (MethodID == "FDA_32PFAS"),
# matching the run worklist (run_builder derives the same code from core services)
# so a logged cal standard traces to its worklist injection.
FDA_CAL_DEFAULTS = [
    ("CAL-%d" % (i + 1), "FDA_32PFAS-CAL-%d" % (i + 1), conc)
    for i, conc in enumerate(_get_cal_ladder("FDA_32PFAS"))
]

# ── Annotation helpers ─────────────────────────────────────────────────────────

def _get_logbook(batch, form_num):
    """Return the logbook dict for form_num (e.g. 250) on this batch."""
    key = _KEY_PREFIX + str(form_num)
    ann = IAnnotations(batch)
    raw = ann.get(key)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {}


def _save_logbook(batch, form_num, data):
    """Persist logbook data dict for form_num on this batch."""
    key = _KEY_PREFIX + str(form_num)
    ann = IAnnotations(batch)
    ann[key] = json.dumps(data)
    try:
        from bika.lims.api.snapshot import take_snapshot
        take_snapshot(batch)
    except Exception:
        pass


def _batch_uid(batch):
    """Return a filesystem-safe UID for the batch."""
    try:
        uid = batch.UID()
        return uid if uid else batch.getId()
    except Exception:
        return batch.getId()


def _export_cal_to_file(batch, data):
    """Write FM-ENV-251 cal data to /data/qc/batches/{uid}/cal_251.json."""
    uid = _batch_uid(batch)
    out_dir = os.path.join(BATCHES_EXPORT_ROOT, uid)
    try:
        if not os.path.exists(out_dir):
            os.makedirs(out_dir)
        path = os.path.join(out_dir, "cal_251.json")
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.rename(tmp, path)
        logger.info("Exported FM-ENV-251 cal data to %s", path)
    except (IOError, OSError) as exc:
        logger.warning("Failed to export FM-ENV-251: %s", exc)


# ── Base class ─────────────────────────────────────────────────────────────────

class _LogbookBase(BrowserView):

    def portal_url(self):
        return getToolByName(self.context, "portal_url")()

    def batch_url(self):
        return self.context.absolute_url()

    def batch_id(self):
        return self.context.getId()

    def batch_title(self):
        return self.context.Title() if hasattr(self.context, "Title") else self.batch_id()

    def batch_method(self):
        """Return the method ID for this batch.

        Priority: extraction session > logbook 251/252 annotation > SENAITE batch method.
        """
        try:
            from senaite.pfas.browser.extraction_guide import _load_session
            sess = _load_session(self.context)
            if sess.get("method_id"):
                return sess["method_id"]
        except Exception:
            pass
        for form_num in (251, 252):
            method = _get_logbook(self.context, form_num).get("method", "")
            if method:
                return method
        try:
            m = self.context.getMethod()
            if m:
                return m.getId()
        except Exception:
            pass
        return ""

    def _redirect(self, url):
        self.request.response.redirect(url)
        return ""

    def _redirect_self(self, msg=""):
        url = self.batch_url() + "/" + self._VIEW_NAME
        if msg:
            url += "?ok=" + msg.replace(" ", "+")
        return self._redirect(url)

    def _redirect_error(self, msg):
        url = self.batch_url() + "/" + self._VIEW_NAME + "?error=" + msg.replace(" ", "+")
        return self._redirect(url)

    def ok_msg(self):
        return self.request.form.get("ok", "").replace("+", " ")

    def error_msg(self):
        return self.request.form.get("error", "").replace("+", " ")


# ── Logbook index (sub-tab) ────────────────────────────────────────────────────

class PFASLogbookIndexView(_LogbookBase):
    """Index of all four logbooks for a batch."""

    _VIEW_NAME = "@@pfas-logbook-index"
    template = ViewPageTemplateFile("templates/logbook_index.pt")

    def __call__(self):
        flatten_form(self.request)
        return self.template()

    def logbooks(self):
        from senaite.pfas.logbook_store import get_active_logbook_defs
        from senaite.pfas.method_profile_store import get_profile
        portal = getToolByName(self.context, "portal_url").getPortalObject()

        # All active defs indexed by slug
        all_defs = {d["slug"]: d for d in get_active_logbook_defs(portal)}

        # Order by the method's required_logbooks list (falls back to all defs)
        method_id = self.batch_method()
        required_slugs = []
        if method_id:
            try:
                profile = get_profile(portal, method_id)
                required_slugs = profile.get("required_logbooks", [])
            except Exception:
                pass

        if required_slugs:
            ordered_defs = [all_defs[s] for s in required_slugs if s in all_defs]
            # Append any active logbook not in required list that already has data
            seen = set(required_slugs)
            for slug, d in sorted(all_defs.items(), key=lambda x: x[1].get("sort_order", 100)):
                if slug not in seen and _get_logbook(self.context, slug):
                    ordered_defs.append(d)
        else:
            ordered_defs = sorted(all_defs.values(), key=lambda d: d.get("sort_order", 100))

        # Load extraction session to determine logbook 252 status
        extraction_session = {}
        extraction_finalized = False
        try:
            from senaite.pfas.browser.extraction_guide import _load_session
            extraction_session = _load_session(self.context)
            extraction_finalized = bool(extraction_session.get("finalized", False))
        except Exception:
            pass

        base = self.batch_url()
        batch_uid = ""
        try:
            batch_uid = self.context.UID() or ""
        except Exception:
            pass

        _BUILTIN_SUBTITLES = {
            "250": "Balance S/N · reagent lots · ammonium acetate weight",
            "251": "PDS lots · cal point concentrations · CCV/ICV conc · sign-off",
            "252": "Stage-by-stage: reagent lots · equipment S/Ns · spike pedigree · deviations",
            "253": "Sample IDs · processing date · matrix · analyst",
        }

        rows = []
        for d in ordered_defs:
            slug = d["slug"]
            form_num = d.get("form_num", slug)
            title = d.get("title", slug)
            builtin = d.get("builtin", False)
            is_extraction_log = (slug == "252")

            # Route: extraction log → guided extraction; others → standard logbook views
            if is_extraction_log:
                url = "{0}/@@pfas-extraction-guide?batch_uid={1}".format(
                    self.portal_url(), batch_uid)
            else:
                schema_raw = d.get("field_schema_json") or "[]"
                has_schema = False
                try:
                    has_schema = bool(json.loads(schema_raw))
                except (ValueError, TypeError):
                    pass
                if has_schema:
                    url = "{0}/@@pfas-logbook-dynamic?slug={1}".format(base, slug)
                elif builtin:
                    url = "{0}/@@pfas-logbook-{1}".format(base, slug)
                else:
                    url = "{0}/@@pfas-logbook-custom?slug={1}".format(base, slug)

            # Filled: extraction log is filled if session is finalized OR annotation exists
            if is_extraction_log:
                filled = extraction_finalized or bool(_get_logbook(self.context, slug))
            else:
                filled = bool(_get_logbook(self.context, slug))

            # Subtitle: built-in logbooks have fixed descriptions; custom ones derive from schema
            subtitle = _BUILTIN_SUBTITLES.get(slug, "")
            if not subtitle and not builtin:
                try:
                    fields = json.loads(d.get("field_schema_json") or "[]")
                    labels = [f.get("label", "") for f in fields[:4] if f.get("label")]
                    subtitle = " · ".join(labels)
                except (ValueError, TypeError):
                    pass

            rows.append({
                "num":               form_num,
                "title":             "{0}: {1}".format(form_num, title),
                "subtitle":          subtitle,
                "url":               url,
                "filled":            filled,
                "is_extraction_log": is_extraction_log,
                "eg_finalized":      extraction_finalized if is_extraction_log else False,
                "eg_started":        bool(extraction_session) if is_extraction_log else False,
            })
        return rows

    def admin_url(self):
        return self.portal_url() + "/@@pfas-logbook-admin"


# ── FM-ENV-250: Solvent / Reagent Prep Log ────────────────────────────────────

class PFASLogbook250View(_LogbookBase):

    _VIEW_NAME = "@@pfas-logbook-250"
    template = ViewPageTemplateFile("templates/logbook_250.pt")

    def __call__(self):
        flatten_form(self.request)
        if self.request.method == "POST":
            return self._handle_post()
        return self.template()

    def data(self):
        return _get_logbook(self.context, 250)

    def data_json(self):
        return json.dumps(self.data(), indent=2)

    def _handle_post(self):
        f = self.request.form
        solutions_raw = f.get("solutions_json", "[]")
        chemicals_raw = f.get("chemicals_json", "[]")
        try:
            solutions = json.loads(solutions_raw)
        except (ValueError, TypeError):
            solutions = []
        try:
            chemicals = json.loads(chemicals_raw)
        except (ValueError, TypeError):
            chemicals = []

        existing = _get_logbook(self.context, 250)
        data = {
            "prepared_by":              f.get("prepared_by", ""),
            "prepared_date":            f.get("prepared_date", ""),
            "reviewed_by":              f.get("reviewed_by", ""),
            "reviewed_date":            f.get("reviewed_date", ""),
            "solutions":                solutions,
            "chemicals":                chemicals,
            "ammonium_acetate_weight_g": f.get("ammonium_acetate_weight_g", ""),
            "balance_sn":               f.get("balance_sn", ""),
            "notes":                    f.get("notes", ""),
        }
        _apply_field_corrections(f, existing, _CORR_FIELDS_250, data)
        _save_logbook(self.context, 250, data)
        return self._redirect_self("Solvent+Reagent+Prep+Log+saved")


# ── FM-ENV-251: Calibration Curve Prep Log ────────────────────────────────────

class PFASLogbook251View(_LogbookBase):

    _VIEW_NAME = "@@pfas-logbook-251"
    template = ViewPageTemplateFile("templates/logbook_251.pt")

    def __call__(self):
        flatten_form(self.request)
        if self.request.method == "POST":
            action = self.request.form.get("action", "")
            if action == "download_csv":
                return self._download_csv()
            return self._handle_post()
        return self.template()

    def data(self):
        return _get_logbook(self.context, 251)

    def data_json(self):
        return json.dumps(self.data(), indent=2)

    def default_cal_points_json(self):
        """JSON of default FDA cal points for pre-populating the form."""
        rows = [{"level": lv, "name": nm, "conc_ng_ml": c}
                for lv, nm, c in FDA_CAL_DEFAULTS]
        return json.dumps(rows)

    def _handle_post(self):
        f = self.request.form
        cal_raw = f.get("cal_points_json", "[]")
        try:
            cal_points = json.loads(cal_raw)
        except (ValueError, TypeError):
            cal_points = []

        existing = _get_logbook(self.context, 251)
        data = {
            "method":           f.get("method", "FDA_32PFAS"),
            "prepared_by":      f.get("prepared_by", ""),
            "prepared_date":    f.get("prepared_date", ""),
            "reviewed_by":      f.get("reviewed_by", ""),
            "reviewed_date":    f.get("reviewed_date", ""),
            "pds_a_lot":        f.get("pds_a_lot", ""),
            "pds_b_lot":        f.get("pds_b_lot", ""),
            "analyte_pds_lot":  f.get("analyte_pds_lot", ""),
            "analyte_spike_lot": f.get("analyte_spike_lot", ""),
            "cal_a_lot":        f.get("cal_a_lot", ""),
            "cal_points":       cal_points,
            "ccv_conc_ng_ml":   f.get("ccv_conc_ng_ml", "1.25"),
            "icv_conc_ng_ml":   f.get("icv_conc_ng_ml", "1.25"),
            "diluent_is_conc":  f.get("diluent_is_conc", "1.0"),
            "notes":            f.get("notes", ""),
        }
        _apply_field_corrections(f, existing, _CORR_FIELDS_251, data)
        _save_logbook(self.context, 251, data)
        _export_cal_to_file(self.context, data)
        return self._redirect_self("Calibration+Curve+Prep+Log+saved")

    def _download_csv(self):
        """Return cal ladder as a downloadable CSV for the injection builder."""
        data = self.data()
        cal_points = data.get("cal_points", [])
        if not cal_points:
            cal_points = [{"level": lv, "name": nm, "conc_ng_ml": c}
                          for lv, nm, c in FDA_CAL_DEFAULTS]

        import csv
        import StringIO
        buf = StringIO.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["Level", "Name", "Concentration_ng_mL"])
        for pt in cal_points:
            writer.writerow([
                pt.get("level", ""),
                pt.get("name", ""),
                pt.get("conc_ng_ml", ""),
            ])
        content = buf.getvalue()

        batch_id = self.batch_id()
        fname = "cal_ladder_{0}.csv".format(batch_id)
        self.request.response.setHeader("Content-Type", "text/csv")
        self.request.response.setHeader(
            "Content-Disposition", "attachment; filename=" + fname)
        return content


# ── FM-ENV-252: Extraction Log ────────────────────────────────────────────────

class PFASLogbook252View(_LogbookBase):

    _VIEW_NAME = "@@pfas-logbook-252"
    template = ViewPageTemplateFile("templates/logbook_252.pt")

    def __call__(self):
        flatten_form(self.request)
        if self.request.method == "POST":
            return self._handle_post()
        # If the batch's method has extraction stages, redirect to the
        # guided extraction workflow — logbook 252 IS the guided extraction.
        try:
            from senaite.pfas.method_profile_store import get_profile
            portal = getToolByName(self.context, "portal_url").getPortalObject()
            method_id = self.batch_method()
            if method_id:
                profile = get_profile(portal, method_id)
                if profile.get("extraction_stages"):
                    uid = ""
                    try:
                        uid = self.context.UID() or ""
                    except Exception:
                        pass
                    guide_url = "{0}/@@pfas-extraction-guide?batch_uid={1}".format(
                        self.portal_url(), uid)
                    return self._redirect(guide_url)
        except Exception:
            pass
        return self.template()

    def data(self):
        return _get_logbook(self.context, 252)

    def data_json(self):
        return json.dumps(self.data(), indent=2)

    def _handle_post(self):
        f = self.request.form
        for key in ("samples_json", "reagents_json", "standards_json",
                    "extraction_materials_json"):
            try:
                json.loads(f.get(key, "[]"))
            except (ValueError, TypeError):
                return self._redirect_error("Invalid+JSON+in+" + key)

        existing = _get_logbook(self.context, 252)
        data = {
            "method":           f.get("method", ""),
            "analyst":          f.get("analyst", ""),
            "extraction_date":  f.get("extraction_date", ""),
            "reviewed_by":      f.get("reviewed_by", ""),
            "reviewed_date":    f.get("reviewed_date", ""),
            "samples":          json.loads(f.get("samples_json", "[]")),
            "reagents":         json.loads(f.get("reagents_json", "[]")),
            "standards":        json.loads(f.get("standards_json", "[]")),
            "extraction_materials": json.loads(
                f.get("extraction_materials_json", "[]")),
            "needle_cleaned":   f.get("needle_cleaned") == "yes",
            "notes":            f.get("notes", ""),
        }
        _apply_field_corrections(f, existing, _CORR_FIELDS_252, data)
        _save_logbook(self.context, 252, data)
        return self._redirect_self("Extraction+Log+saved")


# ── FM-ENV-253: Sample Processing Log ────────────────────────────────────────

class PFASLogbook253View(_LogbookBase):

    _VIEW_NAME = "@@pfas-logbook-253"
    template = ViewPageTemplateFile("templates/logbook_253.pt")

    def __call__(self):
        flatten_form(self.request)
        if self.request.method == "POST":
            return self._handle_post()
        return self.template()

    def data(self):
        return _get_logbook(self.context, 253)

    def data_json(self):
        return json.dumps(self.data(), indent=2)

    def _handle_post(self):
        f = self.request.form
        existing = _get_logbook(self.context, 253)
        data = {
            "analyst":          f.get("analyst", ""),
            "processing_date":  f.get("processing_date", ""),
            "balance_sn":       f.get("balance_sn", ""),
            "grinder_cleaned":  f.get("grinder_cleaned") == "yes",
            "samples":          json.loads(f.get("samples_json", "[]")),
            "processing_materials": json.loads(
                f.get("processing_materials_json", "[]")),
            "notes":            f.get("notes", ""),
        }
        _apply_field_corrections(f, existing, _CORR_FIELDS_253, data)
        _save_logbook(self.context, 253, data)
        return self._redirect_self("Sample+Processing+Log+saved")


# ── Logbook Admin (portal-level) ──────────────────────────────────────────────

# Single source for the management role gate — shared with prep_logbooks and
# logbook_media so all three enforce the same rule (see browser/perms.py).
from senaite.pfas.browser.perms import (  # noqa: E402
    ALLOWED_ROLES as _ALLOWED_ROLES,
    require_manager as _require_manager,
)


class PFASLogbookAdminView(BrowserView):
    """
    @@pfas-logbook-admin — portal-level logbook definition manager.

    Tab 1-N: per-method required-logbook sequence (reads/writes method profile).
    Final tab: Logbook Pool — global definitions (rename, add, toggle, delete).
    """

    template = ViewPageTemplateFile("templates/logbook_admin.pt")

    def __call__(self):
        flatten_form(self.request)
        if not _require_manager(self.context, self.request):
            self.request.response.setStatus(403)
            return "Forbidden"
        if self.request.method == "POST":
            return self._handle_post()
        if self.request.form.get("action") == "download_logbook_doc":
            return self._download_doc()
        return self.template()

    def _download_doc(self):
        from senaite.pfas.browser.logbook_docs import resolve_download
        slug = self.request.form.get("slug", "")
        try:
            rev_num = int(self.request.form.get("rev_num", 0))
        except (TypeError, ValueError):
            rev_num = 0
        path, fname = resolve_download(self._portal(), slug, rev_num)
        if not path or not os.path.exists(path):
            self.request.response.setStatus(404)
            return "Not found"
        inline = self.request.form.get("view", "0") == "1"
        disp = "inline" if inline else "attachment"
        with open(path, "rb") as fh:
            data = fh.read()
        self.request.response.setHeader("Content-Type", "application/pdf")
        self.request.response.setHeader(
            "Content-Disposition",
            '{0}; filename="{1}"'.format(disp, fname or "logbook.pdf"))
        return data

    def _portal(self):
        return getToolByName(self.context, "portal_url").getPortalObject()

    def portal_url(self):
        return getToolByName(self.context, "portal_url")()

    def logbook_defs(self):
        """Active logbook families for the pool table (archived ones excluded —
        they live under the Archived section)."""
        from senaite.pfas.logbook_store import get_logbook_defs
        from senaite.pfas.browser.logbook_docs import get_archived_slugs
        archived = get_archived_slugs(self._portal())
        return [d for d in get_logbook_defs(self._portal())
                if d["slug"] not in archived]

    def archived_logbooks(self):
        """Deleted logbooks — hidden from the pool, retained; FM-ENV numbers
        are never reused. Restorable."""
        from senaite.pfas.logbook_store import get_logbook_defs
        from senaite.pfas.browser.logbook_docs import get_archived_slugs
        archived = get_archived_slugs(self._portal())
        return [d for d in get_logbook_defs(self._portal())
                if d["slug"] in archived]

    # ── controlled-document (PDF) layer ──────────────────────────────────────

    def _uid(self):
        from AccessControl import getSecurityManager
        return getSecurityManager().getUser().getId() or ""

    def _fullname(self):
        from AccessControl import getSecurityManager
        user = getSecurityManager().getUser()
        mt = getToolByName(self._portal(), "portal_membership", None)
        if mt:
            member = mt.getMemberById(user.getId())
            if member and member.getProperty("fullname", ""):
                return member.getProperty("fullname", "")
        return user.getUserName() or user.getId() or "Unknown"

    def logbook_doc_info(self, slug):
        """Controlled-PDF summary for one logbook (revisions, active, sign-off)."""
        from senaite.pfas.browser.logbook_docs import doc_info
        return doc_info(self._portal(), slug, self._uid())

    def saved(self):
        return self.request.get("saved", "")

    # ── Method-aware helpers ──────────────────────────────────────────────────

    def available_methods(self):
        """Return list of {method_id, display_name} for all defined methods."""
        from senaite.pfas.method_profile_store import DEFAULT_PROFILES
        result = []
        for mid, p in sorted(DEFAULT_PROFILES.items()):
            result.append({
                "method_id":    mid,
                "display_name": p.get("display_name", mid),
            })
        return result

    def method_config_json(self):
        """
        JSON blob consumed by the admin template JS.

        {
          "FDA_32PFAS": {
            "required": [
              {"slug":"250","form_num":"FM-ENV-001","title":"Solvent / Reagent Prep Log"},
              ...
            ],
            "available": [...]   # pool logbooks NOT in required
          },
          ...
        }
        """
        from senaite.pfas.logbook_store import get_logbook_defs
        from senaite.pfas.method_profile_store import get_profile, DEFAULT_PROFILES
        portal = self._portal()
        all_defs = {d["slug"]: d for d in get_logbook_defs(portal)}

        result = {}
        for mid in DEFAULT_PROFILES:
            try:
                profile = get_profile(portal, mid)
                req_slugs = profile.get("required_logbooks", [])
            except Exception:
                req_slugs = []

            required = []
            for s in req_slugs:
                if s in all_defs:
                    d = all_defs[s]
                    required.append({
                        "slug":     s,
                        "form_num": d.get("form_num", s),
                        "title":    d.get("title", s),
                        "builtin":  d.get("builtin", False),
                    })

            req_set = set(req_slugs)
            available = []
            for s, d in sorted(all_defs.items()):
                if s not in req_set and d.get("active", True):
                    # Only offer logbooks with no method restriction, or matching this method
                    method_slug = d.get("method_slug", "") or ""
                    if not method_slug or method_slug == mid:
                        available.append({
                            "slug":     s,
                            "form_num": d.get("form_num", s),
                            "title":    d.get("title", s),
                        })

            result[mid] = {"required": required, "available": available}

        return json.dumps(result)

    # ── POST handlers ─────────────────────────────────────────────────────────

    def _handle_doc_action(self, action, slug):
        """Controlled-PDF actions on a logbook: upload / activate / sign, and
        delete->archive / restore. Mirrors the SOP document-control flow."""
        from senaite.pfas.browser import logbook_docs as ld
        portal = self._portal()
        uid = self._uid()
        def done(msg):
            self.request.response.redirect(
                "{0}/@@pfas-logbook-admin?saved={1}#lb-{2}".format(
                    self.portal_url(), msg, slug))
            return ""

        if not slug:
            return done("bad_request")
        if action == "upload_logbook_doc":
            upload = self.request.form.get("doc_file")
            notes = (self.request.form.get("release_notes") or "").strip()
            ok, msg = ld.upload_doc(portal, slug, upload, notes, uid)
            return done(msg)
        if action == "activate_logbook_doc":
            try:
                rev_num = int(self.request.form.get("rev_num", 0))
            except (TypeError, ValueError):
                rev_num = 0
            ok, msg = ld.activate_doc(portal, slug, rev_num, uid)
            return done(msg)
        if action == "sign_logbook_doc":
            ok, msg = ld.sign_doc(portal, slug, uid, self._fullname())
            return done(msg)
        if action == "archive_logbook":
            ld.archive_logbook(portal, slug)
            return done("archived")
        if action == "restore_logbook":
            ld.restore_logbook(portal, slug)
            return done("restored")
        return done("bad_request")

    def _handle_post(self):
        from senaite.pfas.logbook_store import get_logbook_defs, save_logbook_defs
        import uuid
        portal = self._portal()
        action = self.request.form.get("action", "")
        slug = self.request.form.get("slug", "")
        defs = get_logbook_defs(portal)
        slugs = [d["slug"] for d in defs]

        # ── Controlled-document (PDF) actions ────────────────────────────────
        if action in ("upload_logbook_doc", "activate_logbook_doc",
                      "sign_logbook_doc", "archive_logbook", "restore_logbook"):
            return self._handle_doc_action(action, slug)

        # ── Method sequence save ──────────────────────────────────────────────
        if action == "save_method_config":
            method_id = self.request.form.get("method_id", "").strip()
            raw = self.request.form.get("required_logbooks_json", "[]")
            try:
                req = json.loads(raw)
                if not isinstance(req, list):
                    req = []
            except (ValueError, TypeError):
                req = []
            if method_id:
                from senaite.pfas.method_profile_store import get_profile, save_profile
                profile = get_profile(portal, method_id)
                profile["required_logbooks"] = [str(s) for s in req]
                save_profile(portal, method_id, profile)
            self.request.response.redirect(
                "{0}/@@pfas-logbook-admin?saved=method&tab={1}".format(
                    self.portal_url(), method_id)
            )
            return ""

        # ── Pool-level add with optional method scope ────────────────────────
        elif action == "add":
            new_title    = self.request.form.get("new_title", "").strip()
            new_form_num = self.request.form.get("new_form_num", "").strip()
            cols_raw     = self.request.form.get("new_columns", "").strip()
            method_scope = self.request.form.get("new_method_scope", "").strip()
            table_columns = [c.strip() for c in cols_raw.split(",") if c.strip()]
            if new_title:
                new_slug = "custom-" + uuid.uuid4().hex[:8]
                defs.append({
                    "slug":             new_slug,
                    "form_num":         new_form_num or new_slug,
                    "title":            new_title,
                    "builtin":          False,
                    "active":           True,
                    "table_columns":    table_columns,
                    "method_slug":      method_scope,
                    "field_schema_json": "[]",
                })
                # If scoped to a method, also add it to that method's required list
                if method_scope:
                    try:
                        from senaite.pfas.method_profile_store import get_profile, save_profile
                        profile = get_profile(portal, method_scope)
                        req = list(profile.get("required_logbooks", []))
                        if new_slug not in req:
                            req.append(new_slug)
                        profile["required_logbooks"] = req
                        save_profile(portal, method_scope, profile)
                    except Exception:
                        pass

        elif action == "rename":
            new_title = self.request.form.get("title", "").strip()
            new_form_num = self.request.form.get("form_num", "").strip()
            for d in defs:
                if d["slug"] == slug:
                    if new_title:
                        d["title"] = new_title
                    if new_form_num:
                        d["form_num"] = new_form_num
                    break

        elif action == "toggle":
            for d in defs:
                if d["slug"] == slug:
                    d["active"] = not d.get("active", True)
                    break

        elif action == "move_up":
            idx = slugs.index(slug) if slug in slugs else -1
            if idx > 0:
                defs[idx - 1], defs[idx] = defs[idx], defs[idx - 1]

        elif action == "move_down":
            idx = slugs.index(slug) if slug in slugs else -1
            if 0 <= idx < len(defs) - 1:
                defs[idx + 1], defs[idx] = defs[idx], defs[idx + 1]

        elif action == "delete":
            from senaite.pfas.logbook_store import is_builtin
            if slug and not is_builtin(slug):
                defs = [d for d in defs if d["slug"] != slug]

        elif action == "reseed_builtins":
            from senaite.pfas.browser.prep_logbooks import seed_builtin_logbook_defs
            seed_builtin_logbook_defs(portal)
            self.request.response.redirect(
                self.portal_url() + "/@@pfas-logbook-admin?saved=reseed"
            )
            return ""

        save_logbook_defs(portal, defs)
        self.request.response.redirect(
            self.portal_url() + "/@@pfas-logbook-admin?saved=1"
        )
        return ""


# ── Generic custom logbook (batch-level) ──────────────────────────────────────

# ── Dynamic schema helpers ────────────────────────────────────────────────────

def _parse_schema(defn):
    """Parse field_schema_json from a PrepLogbookDef dict or object.  Returns []."""
    if isinstance(defn, dict):
        raw = defn.get("field_schema_json") or u"[]"
    else:
        raw = getattr(defn, "field_schema_json", None) or u"[]"
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
    except (ValueError, TypeError):
        pass
    return []


def _correctable_fields(schema_fields):
    """Return list of field names with correctable=True (excludes table/checkbox)."""
    return [
        f["name"] for f in schema_fields
        if f.get("correctable")
        and f.get("type") not in ("table", "checkbox")
        and f.get("name")
    ]


def _extract_data_from_schema(form, schema_fields):
    """Build data dict from POST form data based on the field schema."""
    data = {}
    for field in schema_fields:
        fname = field.get("name")
        if not fname:
            continue
        ftype = field.get("type", "text")
        if ftype == "table":
            raw = form.get(fname + "_json", "[]")
            try:
                data[fname] = json.loads(raw)
            except (ValueError, TypeError):
                data[fname] = []
        elif ftype == "checkbox":
            data[fname] = form.get(fname) == "yes"
        else:
            data[fname] = form.get(fname, "") or ""
    return data


def _date_str_obj(obj, field):
    """Safe date → YYYY-MM-DD string from a content object attribute."""
    val = getattr(obj, field, None)
    if not val:
        return u""
    try:
        return val.strftime("%Y-%m-%d")
    except AttributeError:
        return str(val)[:10]


# ── Dynamic logbook renderer ──────────────────────────────────────────────────

class PFASDynamicLogbookView(_LogbookBase):
    """
    @@pfas-logbook-dynamic?slug=<slug>

    Renders a logbook form from a PrepLogbookDef's field_schema_json.
    All field types (text, date, number, textarea, lot_ref, reagent_ref,
    checkbox, table) are supported.  GLP corrections use the same
    _apply_field_corrections() as the hardcoded views.
    """

    _VIEW_NAME = "@@pfas-logbook-dynamic"
    template = ViewPageTemplateFile("templates/logbook_dynamic.pt")

    def __call__(self):
        flatten_form(self.request)
        if self.request.method == "POST":
            return self._handle_post()
        return self.template()

    def slug(self):
        return self.request.get("slug", "")

    def _slug(self):
        return self.slug()

    def _redirect_self(self, msg=""):
        url = "{0}/@@pfas-logbook-dynamic?slug={1}".format(
            self.batch_url(), self._slug())
        if msg:
            url += "&ok=" + msg.replace(" ", "+")
        return self._redirect(url)

    def _logbook_def(self):
        """Return PrepLogbookDef dict for this slug (active revision preferred)."""
        from senaite.pfas.browser.prep_logbooks import _list
        portal = getToolByName(self.context, "portal_url").getPortalObject()
        slug = self._slug()
        defs = _list(portal, slug=slug, status_filter="active")
        if not defs:
            defs = _list(portal, slug=slug)
        return defs[0] if defs else {}

    def logbook_def(self):
        return self._logbook_def()

    def field_schema(self):
        """Parsed list of field definition dicts."""
        return _parse_schema(self._logbook_def())

    def field_schema_json(self):
        return json.dumps(self.field_schema())

    def logbook_title(self):
        d = self._logbook_def()
        code = d.get("logbook_code") or d.get("logbook_slug") or self._slug()
        title = d.get("title") or self._slug()
        if code and code != title:
            return u"{0}: {1}".format(code, title)
        return title

    def logbook_code(self):
        d = self._logbook_def()
        return d.get("logbook_code") or self._slug()

    def data(self):
        return _get_logbook(self.context, self._slug())

    def data_json(self):
        return json.dumps(self.data())

    def _handle_post(self):
        f = self.request.form
        slug = self._slug()
        schema_fields = self.field_schema()
        existing = self.data()

        data = _extract_data_from_schema(f, schema_fields)
        correctable = _correctable_fields(schema_fields)
        _apply_field_corrections(f, existing, correctable, data)
        _save_logbook(self.context, slug, data)

        # FM-ENV-251 special: export cal data for pipeline injection builder
        if slug == "251":
            _export_cal_to_file(self.context, data)

        return self._redirect_self("Saved")


# ── AJAX: Prepared Standard lot autocomplete ──────────────────────────────────

class PFASLotAutocompleteView(BrowserView):
    """
    @@pfas-lot-autocomplete?type=Calibration+Standard&q=PDS

    Returns JSON list of PreparedStandard lots matching the query.
    Used by lot_ref fields in the dynamic logbook renderer.
    """

    def __call__(self):
        flatten_form(self.request)
        self.request.response.setHeader("Content-Type", "application/json")
        try:
            from plone.protect.interfaces import IDisableCSRFProtection
            from zope.interface import alsoProvides
            alsoProvides(self.request, IDisableCSRFProtection)
        except ImportError:
            pass

        q = (self.request.get("q") or u"").lower().strip()
        lot_type = (self.request.get("type") or u"").strip()

        portal = getToolByName(self.context, "portal_url").getPortalObject()
        folder = portal.get("pfas_prepared_standards")
        if not folder:
            return json.dumps([])

        results = []
        for obj in folder.objectValues():
            if obj.portal_type != "PreparedStandard":
                continue
            obj_type = (getattr(obj, "standard_type", "") or "").strip()
            if lot_type and obj_type != lot_type:
                continue
            obj_status = (getattr(obj, "status", "active") or "active").lower()
            if obj_status == "expired":
                continue
            lot_num = getattr(obj, "lot_number", "") or ""
            title = getattr(obj, "title", "") or lot_num
            if q and q not in lot_num.lower() and q not in title.lower():
                continue
            results.append({
                "lot_number":    lot_num,
                "title":         title,
                "standard_type": obj_type,
                "expiry_date":   _date_str_obj(obj, "expiry_date"),
                "status":        obj_status,
            })
        results.sort(key=lambda x: x["lot_number"])
        return json.dumps(results[:50])


# ── AJAX: Reagent inventory autocomplete ──────────────────────────────────────

class PFASReagentAutocompleteView(BrowserView):
    """
    @@pfas-reagent-autocomplete?q=methanol

    Returns JSON list of active Reagent records matching the query.
    Used by reagent_ref fields in the dynamic logbook renderer.
    """

    def __call__(self):
        flatten_form(self.request)
        self.request.response.setHeader("Content-Type", "application/json")
        try:
            from plone.protect.interfaces import IDisableCSRFProtection
            from zope.interface import alsoProvides
            alsoProvides(self.request, IDisableCSRFProtection)
        except ImportError:
            pass

        q = (self.request.get("q") or u"").lower().strip()

        portal = getToolByName(self.context, "portal_url").getPortalObject()
        folder = portal.get("pfas_reagents")
        if not folder:
            return json.dumps([])

        results = []
        for obj in folder.objectValues():
            if obj.portal_type != "Reagent":
                continue
            name = getattr(obj, "title", "") or ""
            lot = getattr(obj, "lot_number", "") or ""
            if q and q not in name.lower() and q not in lot.lower():
                continue
            results.append({
                "name":       name,
                "lot_number": lot,
                "supplier":   getattr(obj, "supplier", "") or "",
                "status":     (getattr(obj, "status", "active") or "active"),
            })
        results.sort(key=lambda x: x["name"])
        return json.dumps(results[:50])


class PFASLogbookCustomView(_LogbookBase):
    """
    @@pfas-logbook-custom?slug=custom-xxx

    Generic logbook renderer for user-created logbooks.  Fields:
      - Analyst, Date, Reviewed By, Reviewed Date, Notes (always present)
      - A dynamic table whose columns are defined in the logbook definition
    """

    _VIEW_NAME = "@@pfas-logbook-custom"
    template = ViewPageTemplateFile("templates/logbook_custom.pt")

    def __call__(self):
        flatten_form(self.request)
        if self.request.method == "POST":
            return self._handle_post()
        return self.template()

    def _slug(self):
        return self.request.get("slug", "")

    def _redirect_self(self, msg=""):
        slug = self._slug()
        url = "{0}/@@pfas-logbook-custom?slug={1}".format(
            self.batch_url(), slug)
        if msg:
            url += "&ok=" + msg
        return self._redirect(url)

    def logbook_def(self):
        from senaite.pfas.logbook_store import get_logbook_defs
        portal = getToolByName(self.context, "portal_url").getPortalObject()
        slug = self._slug()
        for d in get_logbook_defs(portal):
            if d["slug"] == slug:
                return d
        return {"slug": slug, "form_num": slug, "title": "Custom Logbook",
                "table_columns": []}

    def data(self):
        return _get_logbook(self.context, self._slug())

    def data_json(self):
        return json.dumps(self.data(), indent=2)

    def rows_json(self):
        return json.dumps(self.data().get("rows", []))

    def table_columns(self):
        return self.logbook_def().get("table_columns", [])

    def table_columns_json(self):
        return json.dumps(self.table_columns())

    def _handle_post(self):
        f = self.request.form
        slug = self._slug()
        rows_raw = f.get("rows_json", "[]")
        try:
            rows = json.loads(rows_raw)
        except (ValueError, TypeError):
            rows = []
        data = {
            "analyst":        f.get("analyst", ""),
            "log_date":       f.get("log_date", ""),
            "reviewed_by":    f.get("reviewed_by", ""),
            "reviewed_date":  f.get("reviewed_date", ""),
            "notes":          f.get("notes", ""),
            "rows":           rows,
        }
        _save_logbook(self.context, slug, data)
        return self._redirect_self("Saved")
