# -*- coding: utf-8 -*-
"""
PFAS Preparation Logbook Definitions (@@pfas-prep-logbooks).

Manages versioned prep logbook definitions.  Each logbook has a family
identified by `logbook_slug`; revisions share the same slug.  Only one
revision per slug may have status="active".

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import logging
import re
import uuid
from datetime import date

from zope.event import notify
from zope.lifecycleevent import ObjectModifiedEvent

from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

logger = logging.getLogger("senaite.pfas.browser.prep_logbooks")

STATUS_DRAFT    = "draft"
STATUS_ACTIVE   = "active"
STATUS_ARCHIVED = "archived"


def _slugify(text):
    """Convert a title to a URL-safe slug."""
    s = (text or u"").lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_-]+", "-", s)
    return s[:64]


def _get_folder(portal):
    folder = portal.get("pfas_prep_logbooks")
    if folder is None:
        raise RuntimeError(
            "pfas_prep_logbooks folder not found. Reinstall senaite.pfas."
        )
    return folder


def _date_str(d):
    if not d:
        return u""
    try:
        return d.strftime("%Y-%m-%d")
    except AttributeError:
        return unicode(d)[:10] if d else u""


def _parse_date(s):
    if not s:
        return None
    try:
        from datetime import datetime
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _obj_to_dict(obj):
    return {
        "uid":               obj.getId(),
        "title":             obj.title or u"",
        "logbook_slug":      obj.logbook_slug or u"",
        "revision":          obj.revision or 1,
        "status":            obj.status or STATUS_DRAFT,
        "standard_type":     obj.standard_type or u"",
        "description":       obj.description or u"",
        "procedure":         obj.procedure or u"",
        "default_expiry_days": obj.default_expiry_days or 365,
        "analyte_template_json": obj.analyte_template_json or u"[]",
        "archived_date":     _date_str(obj.archived_date),
        "notes":             obj.notes or u"",
        "method_slug":       getattr(obj, "method_slug", None) or u"",
        "logbook_code":      getattr(obj, "logbook_code", None) or u"",
        "field_schema_json": getattr(obj, "field_schema_json", None) or u"[]",
        "sort_order":        int(getattr(obj, "sort_order", 100) or 100),
        "active":            bool(getattr(obj, "active", True)),
        "builtin":           bool(getattr(obj, "builtin", False)),
    }


def _populate_obj(obj, data):
    obj.title = data.get("title") or u""
    obj.logbook_slug = data.get("logbook_slug") or _slugify(data.get("title", ""))
    obj.revision = int(data.get("revision") or 1)
    obj.status = data.get("status") or STATUS_DRAFT
    obj.standard_type = data.get("standard_type") or u""
    obj.description = data.get("description") or u""
    obj.procedure = data.get("procedure") or u""
    obj.notes = data.get("notes") or u""
    try:
        obj.default_expiry_days = int(data.get("default_expiry_days") or 365)
    except (ValueError, TypeError):
        obj.default_expiry_days = 365
    obj.analyte_template_json = data.get("analyte_template_json") or u"[]"
    obj.archived_date = _parse_date(data.get("archived_date"))
    obj.method_slug = data.get("method_slug") or u""
    obj.logbook_code = data.get("logbook_code") or u""
    obj.field_schema_json = data.get("field_schema_json") or u"[]"
    try:
        obj.sort_order = int(data.get("sort_order") or 100)
    except (ValueError, TypeError):
        obj.sort_order = 100
    # active defaults True; treat any truthy value or absence as True
    raw_active = data.get("active")
    if raw_active is None:
        obj.active = True
    elif isinstance(raw_active, bool):
        obj.active = raw_active
    else:
        obj.active = str(raw_active).lower() not in ("false", "0", "no", "off")
    obj.builtin = bool(data.get("builtin", False))


def _save(portal, data):
    folder = _get_folder(portal)
    uid = (data.get("uid") or u"").strip() or None
    if uid and uid in folder:
        obj = folder[uid]
    else:
        uid = uid or uuid.uuid4().hex
        title = data.get("title") or u"Logbook"
        folder.invokeFactory("PrepLogbookDef", id=uid, title=title)
        obj = folder[uid]
    _populate_obj(obj, data)
    try:
        obj.reindexObject()
    except Exception:
        pass
    try:
        notify(ObjectModifiedEvent(obj))
    except Exception:
        pass
    return uid


def _get(portal, uid):
    try:
        folder = _get_folder(portal)
    except RuntimeError:
        return None
    obj = folder.get(uid)
    return _obj_to_dict(obj) if obj else None


def _list(portal, slug=None, status_filter=None):
    try:
        folder = _get_folder(portal)
    except RuntimeError:
        return []
    results = []
    for obj in folder.objectValues():
        if obj.portal_type != "PrepLogbookDef":
            continue
        d = _obj_to_dict(obj)
        if slug and d["logbook_slug"] != slug:
            continue
        if status_filter and d["status"] != status_filter:
            continue
        results.append(d)
    results.sort(key=lambda x: (x["logbook_slug"], -x["revision"]))
    return results


def _get_active_families(portal):
    """Return one dict per logbook family (the current active revision), sorted by sort_order."""
    all_defs = _list(portal)
    families = {}
    for d in all_defs:
        slug = d["logbook_slug"]
        if slug not in families:
            families[slug] = d
        else:
            # prefer active > draft > archived; within same status prefer higher revision
            existing = families[slug]
            order = {STATUS_ACTIVE: 0, STATUS_DRAFT: 1, STATUS_ARCHIVED: 2}
            if order.get(d["status"], 9) < order.get(existing["status"], 9):
                families[slug] = d
            elif d["status"] == existing["status"] and d["revision"] > existing["revision"]:
                families[slug] = d
    fams = list(families.values())
    fams.sort(key=lambda x: (int(x.get("sort_order") or 100), (x.get("title") or u"").lower()))
    return fams


def _archive_slug(portal, slug):
    """Archive all active revisions for a slug.  Returns list of archived uids."""
    folder = _get_folder(portal)
    archived = []
    for obj in folder.objectValues():
        if obj.portal_type != "PrepLogbookDef":
            continue
        if (obj.logbook_slug or "") == slug and (obj.status or "") == STATUS_ACTIVE:
            obj.status = STATUS_ARCHIVED
            obj.archived_date = date.today()
            try:
                obj.reindexObject()
            except Exception:
                pass
            try:
                notify(ObjectModifiedEvent(obj))
            except Exception:
                pass
            archived.append(obj.getId())
    return archived


def _next_revision(portal, slug):
    """Return the next revision number for a slug (max existing + 1)."""
    revs = [d["revision"] for d in _list(portal, slug=slug)]
    return max(revs) + 1 if revs else 1


_BUILTIN_DEFS = [
    {
        "logbook_slug": "250",
        "logbook_code": "FM-ENV-250",
        "title":        u"Solvent / Reagent Prep Log",
        "method_slug":  u"fda-32-pfas",
        "sort_order":   0,
        "status":       STATUS_ACTIVE,
        "active":       True,
        "builtin":      True,
        "revision":     1,
        "field_schema_json": u'[{"name":"prepared_by","label":"Prepared By","type":"text","required":true,"correctable":true,"width":"lg"},{"name":"prepared_date","label":"Date Prepared","type":"date","required":true,"correctable":true,"width":"md"},{"name":"ammonium_acetate_weight_g","label":"Ammonium Acetate Weight (g)","type":"number","correctable":true,"width":"sm"},{"name":"balance_sn","label":"Balance S/N","type":"text","correctable":true,"width":"md"},{"name":"notes","label":"Notes","type":"textarea","correctable":true},{"name":"reviewed_by","label":"Reviewed By","type":"text","correctable":true,"width":"lg"},{"name":"reviewed_date","label":"Date Reviewed","type":"date","correctable":true,"width":"md"},{"name":"solutions","label":"Solutions Prepared","type":"table","columns":[{"name":"name","label":"Solution Name","type":"text"},{"name":"lot_number","label":"Lot Number","type":"text"},{"name":"volume_ml","label":"Volume (mL)","type":"number"},{"name":"expiry","label":"Expiry","type":"date"}],"default_rows":[]},{"name":"chemicals","label":"Chemicals Used","type":"table","columns":[{"name":"material","label":"Material","type":"text"},{"name":"vendor","label":"Vendor","type":"text"},{"name":"lot_num","label":"Lot #","type":"text"},{"name":"expiry","label":"Expiry","type":"date"}],"default_rows":[]}]',
    },
    {
        "logbook_slug": "251",
        "logbook_code": "FM-ENV-251",
        "title":        u"Calibration Curve Prep Log",
        "method_slug":  u"fda-32-pfas",
        "sort_order":   1,
        "status":       STATUS_ACTIVE,
        "active":       True,
        "builtin":      True,
        "revision":     1,
        "field_schema_json": u'[{"name":"prepared_by","label":"Prepared By","type":"text","required":true,"correctable":true,"width":"lg"},{"name":"prepared_date","label":"Date Prepared","type":"date","required":true,"correctable":true,"width":"md"},{"name":"pds_a_lot","label":"PDS-A Lot","type":"lot_ref","lot_type":"Calibration Standard","correctable":true},{"name":"pds_b_lot","label":"PDS-B Lot","type":"lot_ref","lot_type":"Calibration Standard","correctable":true},{"name":"analyte_pds_lot","label":"Analyte PDS Lot","type":"lot_ref","lot_type":"Calibration Standard","correctable":true},{"name":"analyte_spike_lot","label":"Surrogate Spike Lot","type":"lot_ref","lot_type":"Surrogate Mix","correctable":true},{"name":"cal_a_lot","label":"CAL-A Lot","type":"lot_ref","lot_type":"Calibration Standard","correctable":true},{"name":"icv_conc_ng_ml","label":"ICV Concentration (ng/mL)","type":"number","correctable":true,"width":"sm"},{"name":"ccv_conc_ng_ml","label":"CCV Concentration (ng/mL)","type":"number","correctable":true,"width":"sm"},{"name":"diluent_is_conc","label":"Diluent IS Concentration (ng/mL)","type":"number","correctable":true,"width":"sm"},{"name":"notes","label":"Notes","type":"textarea","correctable":true},{"name":"reviewed_by","label":"Reviewed By","type":"text","correctable":true,"width":"lg"},{"name":"reviewed_date","label":"Date Reviewed","type":"date","correctable":true,"width":"md"},{"name":"cal_points","label":"Calibration Points","type":"table","columns":[{"name":"level","label":"Level","type":"text"},{"name":"name","label":"Name","type":"text"},{"name":"conc_ng_ml","label":"Conc (ng/mL)","type":"number"}],"default_rows":[{"level":"CAL-1","name":"FDA-CAL-1","conc_ng_ml":20.0},{"level":"CAL-2","name":"FDA-CAL-2","conc_ng_ml":10.0},{"level":"CAL-3","name":"FDA-CAL-3","conc_ng_ml":5.0},{"level":"CAL-4","name":"FDA-CAL-4","conc_ng_ml":2.5},{"level":"CAL-5","name":"FDA-CAL-5","conc_ng_ml":1.25},{"level":"CAL-6","name":"FDA-CAL-6","conc_ng_ml":0.625},{"level":"CAL-7","name":"FDA-CAL-7","conc_ng_ml":0.3125},{"level":"CAL-8","name":"FDA-CAL-8","conc_ng_ml":0.15625},{"level":"CAL-9","name":"FDA-CAL-9","conc_ng_ml":0.078125},{"level":"CAL-10","name":"FDA-CAL-10","conc_ng_ml":0.0390625}]}]',
    },
    {
        "logbook_slug": "252",
        "logbook_code": "FM-ENV-252",
        "title":        u"Extraction Log",
        "method_slug":  u"fda-32-pfas",
        "sort_order":   2,
        "status":       STATUS_ACTIVE,
        "active":       True,
        "builtin":      True,
        "revision":     1,
        "field_schema_json": u'[{"name":"analyst","label":"Analyst","type":"text","required":true,"correctable":true,"width":"lg"},{"name":"extraction_date","label":"Extraction Date","type":"date","required":true,"correctable":true,"width":"md"},{"name":"needle_cleaned","label":"Needle Cleaned / Instrument Blank Passed","type":"checkbox"},{"name":"notes","label":"Notes","type":"textarea","correctable":true},{"name":"reviewed_by","label":"Reviewed By","type":"text","correctable":true,"width":"lg"},{"name":"reviewed_date","label":"Date Reviewed","type":"date","correctable":true,"width":"md"},{"name":"samples","label":"Samples","type":"table","columns":[{"name":"sample_id","label":"Sample ID","type":"text"},{"name":"matrix","label":"Matrix","type":"text"},{"name":"weight_g","label":"Weight (g)","type":"number"},{"name":"notes","label":"Notes","type":"text"}],"default_rows":[]},{"name":"reagents","label":"Reagents Used","type":"table","columns":[{"name":"name","label":"Reagent","type":"text"},{"name":"lot","label":"Lot #","type":"text"},{"name":"supplier","label":"Supplier","type":"text"},{"name":"volume","label":"Volume","type":"text"}],"default_rows":[]},{"name":"standards","label":"Standards Used","type":"table","columns":[{"name":"name","label":"Standard","type":"text"},{"name":"lot","label":"Lot #","type":"text"},{"name":"conc","label":"Concentration","type":"text"},{"name":"volume","label":"Volume","type":"text"}],"default_rows":[]},{"name":"extraction_materials","label":"Extraction Materials","type":"table","columns":[{"name":"name","label":"Material","type":"text"},{"name":"lot","label":"Lot #","type":"text"},{"name":"notes","label":"Notes","type":"text"}],"default_rows":[]}]',
    },
    {
        "logbook_slug": "253",
        "logbook_code": "FM-ENV-253",
        "title":        u"Sample Processing Log",
        "method_slug":  u"fda-32-pfas",
        "sort_order":   3,
        "status":       STATUS_ACTIVE,
        "active":       True,
        "builtin":      True,
        "revision":     1,
        "field_schema_json": u'[{"name":"analyst","label":"Analyst","type":"text","required":true,"correctable":true,"width":"lg"},{"name":"processing_date","label":"Processing Date","type":"date","required":true,"correctable":true,"width":"md"},{"name":"balance_sn","label":"Balance S/N","type":"text","correctable":true,"width":"md"},{"name":"grinder_cleaned","label":"Grinder Cleaned / Blank Passed","type":"checkbox"},{"name":"notes","label":"Notes","type":"textarea","correctable":true},{"name":"samples","label":"Samples","type":"table","columns":[{"name":"sample_id","label":"Sample ID","type":"text"},{"name":"weight_g","label":"Weight (g)","type":"number"},{"name":"notes","label":"Notes","type":"text"}],"default_rows":[]},{"name":"processing_materials","label":"Processing Materials","type":"table","columns":[{"name":"name","label":"Material","type":"text"},{"name":"lot","label":"Lot #","type":"text"},{"name":"notes","label":"Notes","type":"text"}],"default_rows":[]}]',
    },
]


def seed_builtin_logbook_defs(portal):
    """Idempotently create PrepLogbookDef objects for the four standard logbooks.

    Matches by logbook_slug.  Skips slugs that already have a PrepLogbookDef.
    Updates sort_order, active, builtin, logbook_code, method_slug, and
    field_schema_json on existing objects only if field_schema_json is still
    the default "[]" (i.e. not yet configured by a user).
    Returns (created, updated, skipped) counts.
    """
    try:
        folder = _get_folder(portal)
    except RuntimeError as exc:
        logger.warning("seed_builtin_logbook_defs: %s", exc)
        return 0, 0, 0

    created = 0
    updated = 0
    skipped = 0

    for defn in _BUILTIN_DEFS:
        slug = defn["logbook_slug"]

        # Find existing object with this slug
        existing = None
        for obj in folder.objectValues():
            if obj.portal_type == "PrepLogbookDef":
                if (getattr(obj, "logbook_slug", "") or "") == slug:
                    existing = obj
                    break

        if existing is not None:
            changed = False
            # Always update registry-style fields (safe even if user edited SOP text)
            for attr, key in [("sort_order", "sort_order"), ("active", "active"),
                               ("builtin", "builtin"), ("logbook_code", "logbook_code"),
                               ("method_slug", "method_slug")]:
                if getattr(existing, attr, None) != defn.get(key):
                    setattr(existing, attr, defn[key])
                    changed = True
            # Only seed field_schema_json if still empty (don't overwrite user edits)
            cur_schema = getattr(existing, "field_schema_json", None) or "[]"
            if cur_schema in ("[]", "", None):
                existing.field_schema_json = defn["field_schema_json"]
                changed = True
            if changed:
                try:
                    existing.reindexObject()
                except Exception:
                    pass
                updated += 1
            else:
                skipped += 1
            continue

        # Create new PrepLogbookDef
        import uuid as _uuid
        new_id = "lbdef-" + _uuid.uuid4().hex[:8]
        try:
            folder.invokeFactory("PrepLogbookDef", id=new_id, title=defn["title"])
            obj = folder[new_id]
            _populate_obj(obj, defn)
            try:
                obj.reindexObject()
            except Exception:
                pass
            created += 1
            logger.info("seed_builtin_logbook_defs: created %s -> %s", slug, new_id)
        except Exception as exc:
            logger.error("seed_builtin_logbook_defs: failed on slug=%s: %s", slug, exc)

    logger.info(
        "seed_builtin_logbook_defs: created=%d updated=%d skipped=%d",
        created, updated, skipped,
    )
    return created, updated, skipped


class PFASPrepLogbooksView(BrowserView):
    """Manage prep logbook definitions."""

    template = ViewPageTemplateFile("templates/prep_logbooks.pt")

    def __call__(self):
        action = self.request.form.get("action", "")
        if self.request.method == "POST":
            try:
                from plone.protect.interfaces import IDisableCSRFProtection
                from zope.interface import alsoProvides
                alsoProvides(self.request, IDisableCSRFProtection)
            except ImportError:
                pass
            if action in ("add", "edit"):
                return self._handle_upsert()
            if action == "activate":
                return self._handle_activate()
            if action == "archive":
                return self._handle_archive()
            if action == "new_revision":
                return self._handle_new_revision()
            if action == "delete":
                return self._handle_delete()
        return self.template()

    def _portal(self):
        return getToolByName(self.context, "portal_url").getPortalObject()

    def _self_url(self):
        return "{}/@@pfas-prep-logbooks".format(self.context.absolute_url())

    def _redirect(self, url):
        self.request.response.redirect(url)
        return ""

    # ── Template data ─────────────────────────────────────────────────────

    def logbook_families(self):
        """Current active/draft revision per family, sorted by title."""
        fams = _get_active_families(self._portal())
        fams.sort(key=lambda x: x.get("title", "").lower())
        return fams

    def all_revisions(self, slug):
        """All revisions for a slug, newest first."""
        revs = _list(self._portal(), slug=slug)
        revs.sort(key=lambda x: -x["revision"])
        return revs

    def edit_uid(self):
        return self.request.form.get("edit_uid", "")

    def edit_data_json(self):
        uid = self.edit_uid()
        if uid:
            rec = _get(self._portal(), uid)
            if rec:
                return json.dumps(rec)
        return "null"

    def ok_msg(self):
        return self.request.form.get("ok", "").replace("+", " ")

    def error_msg(self):
        return self.request.form.get("error", "").replace("+", " ")

    def portal_url(self):
        return getToolByName(self.context, "portal_url")()

    def standard_types(self):
        return [
            "Calibration Standard",
            "QC Check Standard",
            "Surrogate Mix",
            "Internal Standard Mix",
            "Matrix Spike",
            "Solvent / Reagent",
            "Other",
        ]

    # ── Handlers ─────────────────────────────────────────────────────────

    def _handle_upsert(self):
        f = self.request.form
        title = f.get("title", "").strip()
        if not title:
            return self._redirect("{0}?error=Title+is+required".format(self._self_url()))
        data = {
            "uid":                 f.get("uid", "").strip() or None,
            "title":               title,
            "logbook_slug":        f.get("logbook_slug", "").strip() or _slugify(title),
            "revision":            f.get("revision", "1"),
            "status":              f.get("status", STATUS_DRAFT),
            "standard_type":       f.get("standard_type", "").strip(),
            "description":         f.get("description", "").strip(),
            "procedure":           f.get("procedure", "").strip(),
            "default_expiry_days": f.get("default_expiry_days", "365"),
            "analyte_template_json": f.get("analyte_template_json", "[]").strip(),
            "notes":               f.get("notes", "").strip(),
            "method_slug":         f.get("method_slug", "").strip(),
            "logbook_code":        f.get("logbook_code", "").strip(),
            "field_schema_json":   f.get("field_schema_json", "[]").strip() or "[]",
            "sort_order":          f.get("sort_order", "100"),
            "active":              f.get("active") not in ("false", "0", "no", "off"),
            "builtin":             f.get("builtin") in ("true", "1", "yes", "on"),
        }
        _save(self._portal(), data)
        return self._redirect("{0}?ok=Logbook+saved".format(self._self_url()))

    def _handle_activate(self):
        """Mark a revision active, archiving any prior active revision for the slug."""
        uid = self.request.form.get("uid", "").strip()
        rec = _get(self._portal(), uid)
        if not rec:
            return self._redirect("{0}?error=Not+found".format(self._self_url()))
        _archive_slug(self._portal(), rec["logbook_slug"])
        rec["status"] = STATUS_ACTIVE
        _save(self._portal(), rec)
        return self._redirect("{0}?ok=Revision+activated".format(self._self_url()))

    def _handle_new_revision(self):
        """Create a draft copy of an existing revision with revision+1."""
        uid = self.request.form.get("uid", "").strip()
        rec = _get(self._portal(), uid)
        if not rec:
            return self._redirect("{0}?error=Not+found".format(self._self_url()))
        new_rev = _next_revision(self._portal(), rec["logbook_slug"])
        rec.pop("uid", None)
        rec["revision"] = new_rev
        rec["status"] = STATUS_DRAFT
        rec["archived_date"] = ""
        _save(self._portal(), rec)
        return self._redirect("{0}?ok=New+revision+{1}+created+as+draft".format(
            self._self_url(), new_rev))

    def _handle_archive(self):
        """Soft-delete: set status=archived and record today's date."""
        uid = self.request.form.get("uid", "").strip()
        rec = _get(self._portal(), uid)
        if not rec:
            return self._redirect("{0}?error=Not+found".format(self._self_url()))
        if rec.get("status") == STATUS_ARCHIVED:
            return self._redirect("{0}?error=Already+archived".format(self._self_url()))
        rec["status"] = STATUS_ARCHIVED
        rec["archived_date"] = date.today().isoformat()
        _save(self._portal(), rec)
        return self._redirect("{0}?ok=Revision+archived".format(self._self_url()))

    def _handle_delete(self):
        """Hard-delete: only allowed for draft revisions that are not builtin."""
        uid = self.request.form.get("uid", "").strip()
        rec = _get(self._portal(), uid)
        if not rec:
            return self._redirect("{0}?error=Not+found".format(self._self_url()))
        if rec.get("builtin"):
            return self._redirect("{0}?error=Built-in+logbooks+cannot+be+deleted".format(
                self._self_url()))
        if rec.get("status") != STATUS_DRAFT:
            return self._redirect(
                "{0}?error=Only+draft+revisions+can+be+deleted.+Archive+active+ones+first.".format(
                    self._self_url()))
        try:
            folder = _get_folder(self._portal())
            if uid in folder:
                folder.manage_delObjects([uid])
                return self._redirect("{0}?ok=Draft+deleted".format(self._self_url()))
        except Exception as exc:
            logger.error("delete prep logbook: %s", exc)
        return self._redirect("{0}?error=Delete+failed".format(self._self_url()))
