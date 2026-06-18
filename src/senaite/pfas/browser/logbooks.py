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

from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from zope.annotation.interfaces import IAnnotations

logger = logging.getLogger("senaite.pfas.browser.logbooks")

_KEY_PREFIX = u"senaite.pfas.logbook."
BATCHES_EXPORT_ROOT = os.environ.get("PFAS_BATCHES_PATH", "/data/qc/batches")

# Default cal points for FDA 32-PFAS (ng/mL)
FDA_CAL_DEFAULTS = [
    ("CAL-1",  "FDA-CAL-1",  20.0),
    ("CAL-2",  "FDA-CAL-2",  10.0),
    ("CAL-3",  "FDA-CAL-3",   5.0),
    ("CAL-4",  "FDA-CAL-4",   2.5),
    ("CAL-5",  "FDA-CAL-5",   1.25),
    ("CAL-6",  "FDA-CAL-6",   0.625),
    ("CAL-7",  "FDA-CAL-7",   0.3125),
    ("CAL-8",  "FDA-CAL-8",   0.15625),
    ("CAL-9",  "FDA-CAL-9",   0.078125),
    ("CAL-10", "FDA-CAL-10",  0.0390625),
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
        """Best-guess method ID for this batch from saved logbook data."""
        for form_num in (251, 252):
            method = _get_logbook(self.context, form_num).get("method", "")
            if method:
                return method
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
        return self.template()

    def logbooks(self):
        from senaite.pfas.logbook_store import get_active_logbook_defs
        portal = getToolByName(self.context, "portal_url").getPortalObject()
        defs = get_active_logbook_defs(portal)
        base = self.batch_url()
        portal_url = self.portal_url()
        rows = []
        for d in defs:
            slug = d["slug"]
            form_num = d.get("form_num", slug)
            title = d.get("title", slug)
            builtin = d.get("builtin", False)
            if builtin:
                url = "{0}/@@pfas-logbook-{1}".format(base, slug)
            else:
                url = "{0}/@@pfas-logbook-custom?slug={1}".format(base, slug)
            filled = bool(_get_logbook(self.context, slug))
            rows.append({
                "num":   form_num,
                "title": "{0}: {1}".format(form_num, title),
                "url":   url,
                "filled": filled,
            })
        return rows

    def admin_url(self):
        return self.portal_url() + "/@@pfas-logbook-admin"


# ── FM-ENV-250: Solvent / Reagent Prep Log ────────────────────────────────────

class PFASLogbook250View(_LogbookBase):

    _VIEW_NAME = "@@pfas-logbook-250"
    template = ViewPageTemplateFile("templates/logbook_250.pt")

    def __call__(self):
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
        _save_logbook(self.context, 250, data)
        return self._redirect_self("Solvent+Reagent+Prep+Log+saved")


# ── FM-ENV-251: Calibration Curve Prep Log ────────────────────────────────────

class PFASLogbook251View(_LogbookBase):

    _VIEW_NAME = "@@pfas-logbook-251"
    template = ViewPageTemplateFile("templates/logbook_251.pt")

    def __call__(self):
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
        if self.request.method == "POST":
            return self._handle_post()
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
        _save_logbook(self.context, 252, data)
        return self._redirect_self("Extraction+Log+saved")


# ── FM-ENV-253: Sample Processing Log ────────────────────────────────────────

class PFASLogbook253View(_LogbookBase):

    _VIEW_NAME = "@@pfas-logbook-253"
    template = ViewPageTemplateFile("templates/logbook_253.pt")

    def __call__(self):
        if self.request.method == "POST":
            return self._handle_post()
        return self.template()

    def data(self):
        return _get_logbook(self.context, 253)

    def data_json(self):
        return json.dumps(self.data(), indent=2)

    def _handle_post(self):
        f = self.request.form
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
        _save_logbook(self.context, 253, data)
        return self._redirect_self("Sample+Processing+Log+saved")


# ── Logbook Admin (portal-level) ──────────────────────────────────────────────

_ALLOWED_ROLES = frozenset(("Manager", "LabManager", "Owner"))


def _require_manager(context, request):
    try:
        from AccessControl import getSecurityManager
        user = getSecurityManager().getUser()
        return bool(_ALLOWED_ROLES.intersection(user.getRolesInContext(context)))
    except Exception:
        return False


class PFASLogbookAdminView(BrowserView):
    """
    @@pfas-logbook-admin — portal-level logbook definition manager.

    Allows managers to rename logbooks, change form numbers, toggle active
    state, reorder, add new custom logbooks, and delete custom (non-built-in)
    logbooks.
    """

    template = ViewPageTemplateFile("templates/logbook_admin.pt")

    def __call__(self):
        if not _require_manager(self.context, self.request):
            self.request.response.setStatus(403)
            return "Forbidden"
        if self.request.method == "POST":
            return self._handle_post()
        return self.template()

    def _portal(self):
        return getToolByName(self.context, "portal_url").getPortalObject()

    def portal_url(self):
        return getToolByName(self.context, "portal_url")()

    def logbook_defs(self):
        from senaite.pfas.logbook_store import get_logbook_defs
        return get_logbook_defs(self._portal())

    def saved(self):
        return self.request.get("saved", "")

    def _handle_post(self):
        from senaite.pfas.logbook_store import get_logbook_defs, save_logbook_defs
        import uuid
        portal = self._portal()
        action = self.request.form.get("action", "")
        slug = self.request.form.get("slug", "")
        defs = get_logbook_defs(portal)
        slugs = [d["slug"] for d in defs]

        if action == "rename":
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

        elif action == "add":
            new_title = self.request.form.get("new_title", "").strip()
            new_form_num = self.request.form.get("new_form_num", "").strip()
            cols_raw = self.request.form.get("new_columns", "").strip()
            table_columns = [c.strip() for c in cols_raw.split(",") if c.strip()]
            if new_title:
                new_slug = "custom-" + uuid.uuid4().hex[:8]
                defs.append({
                    "slug":          new_slug,
                    "form_num":      new_form_num or new_slug,
                    "title":         new_title,
                    "builtin":       False,
                    "active":        True,
                    "table_columns": table_columns,
                })

        save_logbook_defs(portal, defs)
        self.request.response.redirect(
            self.portal_url() + "/@@pfas-logbook-admin?saved=1"
        )
        return ""


# ── Generic custom logbook (batch-level) ──────────────────────────────────────

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
