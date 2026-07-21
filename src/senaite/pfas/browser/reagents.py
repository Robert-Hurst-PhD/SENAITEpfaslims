# -*- coding: utf-8 -*-
"""
PFAS Reagent Inventory (@@pfas-reagents).

ISO 17025 / MLAB reagent tracking: catalog number, lot number, expiry,
storage location, and status for every chemical used in the lab.

Reagents are stored as first-class SENAITE Dexterity content objects in
portal/pfas_reagents/, indexed in senaite_catalog_setup, and participating
in the global audit trail.  Each lot is one Reagent object keyed by UUID.

Barcode scanning and OCR text recognition run entirely in the browser
(ZXing-js + Tesseract.js); no server-side scanner is needed.

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import logging
import os
import re
import uuid
from datetime import date, datetime, timedelta

from zope.annotation.interfaces import IAnnotations
from zope.event import notify
from zope.lifecycleevent import ObjectModifiedEvent

from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

logger = logging.getLogger("senaite.pfas.browser.reagents")

# Reagent status values
STATUS_ACTIVE     = "active"
STATUS_OPENED     = "opened"
STATUS_EXHAUSTED  = "exhausted"
STATUS_EXPIRED    = "expired"
STATUS_QUARANTINE = "quarantine"

ALL_STATUSES = [
    (STATUS_ACTIVE,     "Active / In Stock"),
    (STATUS_OPENED,     "Opened"),
    (STATUS_EXHAUSTED,  "Exhausted"),
    (STATUS_EXPIRED,    "Expired"),
    (STATUS_QUARANTINE, "Quarantine"),
]

# ── Lab settings / archive ────────────────────────────────────────────────────
_LAB_SETTINGS_KEY = u"senaite.pfas.lab_settings"
_ANN_ARCHIVED_KEY = u"senaite.pfas.reagent.archived"

# Reagent categories (ISO 17025-friendly)
# Vocabulary is OWNED by the Reagent content type — single source of truth
# (was duplicated here). Imported so this view stays in lock-step.
from senaite.pfas.content.reagent import REAGENT_CATEGORIES  # noqa: F401

# Mobile phase name pattern for auto-expiry (7 days from open date)
_MOBILE_PHASE_RE = re.compile(
    r'methanol|meoh|acetonitrile|acn|water|h2o|mobile.?phase|mph|formic',
    re.IGNORECASE,
)

# ── Expiry helpers ────────────────────────────────────────────────────────────
# Global default expiry periods (days). Editable in lab settings (Reagent
# Inventory → Expiry Defaults); these literals are only the seed values.

EXPIRY_DEFAULTS = {
    "reagent_default_days":       365,  # manufactured reagent w/o stated expiry
    "mobile_phase_open_days":     7,    # mobile phases after opening
    "opened_default_days":        365,  # other reagents after opening
    "prepared_std_default_days":  365,  # in-house prepared standards
}


def get_expiry_defaults(portal):
    """Merged global expiry defaults (lab settings over seeds)."""
    out = dict(EXPIRY_DEFAULTS)
    try:
        s = _get_lab_settings(portal)
        for k in EXPIRY_DEFAULTS:
            v = s.get(k)
            if v:
                out[k] = int(v)
    except Exception:
        pass
    return out


def _auto_expiry_from_open(name, opened_date_str, defaults=None):
    """Calculate auto-expiry from open date.

    Mobile phases: `mobile_phase_open_days` (default 7); all others
    `opened_default_days` (default 365). Periods come from the global
    expiry defaults, not hardcoded.
    Returns ISO date string or empty string if input is invalid.
    """
    d = defaults or EXPIRY_DEFAULTS
    if not opened_date_str:
        return ""
    try:
        opened = datetime.strptime(opened_date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return ""
    if _MOBILE_PHASE_RE.search(name or ""):
        exp = opened + timedelta(days=int(d.get("mobile_phase_open_days", 7)))
    else:
        exp = opened + timedelta(days=int(d.get("opened_default_days", 365)))
    return exp.strftime("%Y-%m-%d")


def _effective_expiry(rec, defaults=None):
    """Expiry date string in effect for a record.

    Inheritance chain: explicit expiry_date → manufacturer_expiry → GLOBAL
    default (received_date + reagent_default_days) so a manufactured reagent
    without a stated expiry is still governed by the preset global value."""
    exp = rec.get("expiry_date") or rec.get("manufacturer_expiry") or ""
    if exp:
        return exp
    received = rec.get("received_date") or ""
    if received:
        d = defaults or EXPIRY_DEFAULTS
        try:
            rd = datetime.strptime(received, "%Y-%m-%d").date()
            return (rd + timedelta(days=int(d.get("reagent_default_days", 365)))
                    ).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            pass
    return ""


def get_reagent_effective_expiry(portal, lot, name=None):
    """Public: effective expiry (incl. global-default fallback) of the reagent
    lot with the given lot number — used by prepared-standards inheritance."""
    try:
        folder = _get_reagents_folder(portal)
    except Exception:
        return ""
    defaults = get_expiry_defaults(portal)
    for obj in folder.objectValues():
        try:
            if (obj.lot_number or "") != lot:
                continue
            if name and name.strip() and (obj.title or "").strip() != name.strip():
                continue
            rec = {
                "expiry_date": _date_to_str(obj.expiry_date),
                "manufacturer_expiry": _date_to_str(obj.manufacturer_expiry),
                "received_date": _date_to_str(obj.received_date),
            }
            return _effective_expiry(rec, defaults)
        except Exception:
            continue
    return ""


def _is_expired(rec):
    exp = _effective_expiry(rec)
    if not exp:
        return False
    try:
        return datetime.strptime(exp, "%Y-%m-%d").date() < date.today()
    except (ValueError, TypeError):
        return False


# ── Content-object store helpers ──────────────────────────────────────────────

def _get_reagents_folder(portal):
    """Return the pfas_reagents Folder content object.

    Raises RuntimeError if not found — caller should handle gracefully.
    """
    folder = portal.get("pfas_reagents")
    if folder is None:
        raise RuntimeError(
            "pfas_reagents folder not found. Reinstall senaite.pfas to create it."
        )
    return folder


def _get_lab_settings(portal):
    ann = IAnnotations(portal)
    raw = ann.get(_LAB_SETTINGS_KEY)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {}


def _save_lab_settings(portal, settings):
    ann = IAnnotations(portal)
    ann[_LAB_SETTINGS_KEY] = json.dumps(settings)


def _is_production_mode(portal):
    """True when SENAITE global audit log is enabled (the lab's production gate)."""
    try:
        from bika.lims import api as bika_api
        setup = bika_api.get_senaite_setup()
        return bool(setup.getEnableGlobalAuditlog())
    except Exception:
        return False


def _get_production_since(portal):
    """Return datetime when audit was first enabled, or None."""
    s = _get_lab_settings(portal)
    ts = s.get("production_since")
    if ts:
        try:
            return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S")
        except (ValueError, TypeError):
            pass
    return None


def _maybe_record_production_since(portal):
    """On first request where audit is enabled, record the timestamp."""
    if not _is_production_mode(portal):
        return
    s = _get_lab_settings(portal)
    if s.get("production_since"):
        return
    s["production_since"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    _save_lab_settings(portal, s)


def _is_test_reagent_by_time(obj, prod_since):
    """True if this reagent was created before production mode was activated."""
    if prod_since is None:
        return True
    try:
        from DateTime import DateTime  # noqa: F401 — import just to confirm it exists
        created = obj.created()
        cd = datetime(
            created.year(), created.month(), created.day(),
            created.hour(), created.minute(), int(created.second()),
        )
        return cd < prod_since
    except Exception:
        return False


def _date_to_str(d):
    """Format a datetime.date (or None) as an ISO string."""
    if not d:
        return u""
    try:
        return d.strftime("%Y-%m-%d")
    except AttributeError:
        return unicode(d)[:10] if d else u""


def _str_to_date(s):
    """Parse an ISO date string to datetime.date, or return None."""
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _obj_to_dict(obj):
    """Convert a Reagent content object to the dict format the template expects."""
    d = {
        "uid":                obj.getId(),
        "name":               obj.title or u"",
        "category":           obj.category or u"",
        "supplier":           obj.supplier or u"",
        "cat_number":         obj.cat_number or u"",
        "lot_number":         obj.lot_number or u"",
        "received_date":      _date_to_str(obj.received_date),
        "manufacturer_expiry":_date_to_str(obj.manufacturer_expiry),
        "expiry_date":        _date_to_str(obj.expiry_date),
        "opened_date":        _date_to_str(obj.opened_date),
        "storage_location":   obj.storage_location or u"",
        "barcode":            obj.barcode or u"",
        "quantity":           obj.quantity or u"",
        "unit":               obj.unit or u"",
        "scan_count":         obj.scan_count or 0,
        "status":             obj.status or STATUS_ACTIVE,
        "notes":              obj.notes or u"",
        "is_test":            False,  # overwritten by _list_reagents
    }
    ann = IAnnotations(obj)
    arch_raw = ann.get(_ANN_ARCHIVED_KEY)
    if arch_raw:
        try:
            arch = json.loads(arch_raw)
            d["is_archived"] = True
            d["archived_by"] = arch.get("archived_by", u"")
            d["archived_at"] = arch.get("archived_at", u"")
        except (ValueError, TypeError):
            d["is_archived"] = True
            d["archived_by"] = u""
            d["archived_at"] = u""
    else:
        d["is_archived"] = False
        d["archived_by"] = u""
        d["archived_at"] = u""
    return d


def _populate_obj(obj, data):
    """Write form/dict data onto a Reagent content object.

    Performs auto-expiry computation and status auto-update, matching the
    original annotation-store behaviour.
    """
    obj.title = data.get("name") or u""
    obj.category = data.get("category") or u""
    obj.supplier = data.get("supplier") or u""
    obj.cat_number = data.get("cat_number") or u""
    obj.lot_number = data.get("lot_number") or u""
    obj.storage_location = data.get("storage_location") or u""
    obj.barcode = data.get("barcode") or u""
    obj.quantity = data.get("quantity") or u""
    obj.unit = data.get("unit") or u""
    obj.notes = data.get("notes") or u""
    obj.scan_count = int(data.get("scan_count") or 0)
    obj.status = data.get("status") or STATUS_ACTIVE

    # Date fields: accept both ISO strings (from forms) and datetime.date objects
    for field_name in ("received_date", "expiry_date", "manufacturer_expiry", "opened_date"):
        raw = data.get(field_name)
        if isinstance(raw, (str, bytes)):
            setattr(obj, field_name, _str_to_date(raw))
        else:
            setattr(obj, field_name, raw)

    # Auto-compute expiry from opened_date when not supplied
    defaults = data.get("_expiry_defaults") or EXPIRY_DEFAULTS
    if not obj.expiry_date and not obj.manufacturer_expiry and obj.opened_date:
        computed = _auto_expiry_from_open(obj.title, _date_to_str(obj.opened_date),
                                          defaults)
        obj.expiry_date = _str_to_date(computed)

    # Global-default assignment: a manufactured reagent with NO stated expiry
    # (neither explicit nor manufacturer) is assigned received_date + the
    # preset global period, so every lot is governed by a real date.
    if not obj.expiry_date and not obj.manufacturer_expiry and obj.received_date:
        rd = obj.received_date
        obj.expiry_date = rd + timedelta(
            days=int(defaults.get("reagent_default_days", 365)))
        note = u"Expiry assigned from global default ({0} days from receipt)".format(
            defaults.get("reagent_default_days", 365))
        obj.notes = (obj.notes + u"\n" + note).strip() if obj.notes else note

    # Auto-update to expired
    if obj.status not in (STATUS_EXHAUSTED, STATUS_QUARANTINE):
        if _is_expired(_obj_to_dict(obj)):
            obj.status = STATUS_EXPIRED


def _save_reagent(portal, data):
    """Upsert a Reagent content object.  Returns the object's Zope id (uid)."""
    folder = _get_reagents_folder(portal)
    uid = (data.get("uid") or u"").strip() or None

    if uid and uid in folder:
        obj = folder[uid]
    else:
        uid = uid or uuid.uuid4().hex
        name = data.get("name") or u"Reagent"
        folder.invokeFactory("Reagent", id=uid, title=name)
        obj = folder[uid]

    data["_expiry_defaults"] = get_expiry_defaults(portal)
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


def _get_reagent(portal, uid):
    """Return a reagent dict by uid, or None if not found."""
    try:
        folder = _get_reagents_folder(portal)
    except RuntimeError:
        return None
    obj = folder.get(uid)
    if obj is None:
        return None
    return _obj_to_dict(obj)


COA_DIR = os.environ.get("PFAS_COA_DIR", "/data/coa")
_COA_ANN_KEY  = u"senaite.pfas.reagent.coa"
_SCAN_LOG_KEY = u"senaite.pfas.reagent.scan_log"


def _get_coa_meta(portal, uid):
    """Return CoA metadata dict for a reagent uid, or {}."""
    try:
        folder = _get_reagents_folder(portal)
        obj = folder.get(uid)
        if obj is None:
            return {}
        ann = IAnnotations(obj)
        raw = ann.get(_COA_ANN_KEY)
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return {}


def _save_coa(portal, uid, file_data, filename, content_type, uploaded_by):
    """Write CoA file to disk and store metadata in annotations.

    file_data : bytes
    Returns True on success.
    """
    try:
        if not os.path.isdir(COA_DIR):
            os.makedirs(COA_DIR)
        ext = os.path.splitext(filename)[1] if filename else ".pdf"
        dest = os.path.join(COA_DIR, "{}{}" .format(uid, ext))
        with open(dest, "wb") as fh:
            fh.write(file_data)
        folder = _get_reagents_folder(portal)
        obj = folder.get(uid)
        if obj is not None:
            ann = IAnnotations(obj)
            ann[_COA_ANN_KEY] = json.dumps({
                "filename":     filename,
                "content_type": content_type,
                "uploaded_by":  uploaded_by,
                "uploaded_date":date.today().strftime("%Y-%m-%d"),
                "path":         dest,
            })
            try:
                obj.reindexObject()
            except Exception:
                pass
        return True
    except Exception as exc:
        logger.error("_save_coa %s: %s", uid, exc)
        return False


def _get_scan_log(portal, uid):
    """Return list of scan log entry dicts for a reagent uid (newest last)."""
    try:
        folder = _get_reagents_folder(portal)
        obj = folder.get(uid)
        if obj is None:
            return []
        ann = IAnnotations(obj)
        raw = ann.get(_SCAN_LOG_KEY)
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return []


def _append_scan_log(portal, uid, entry, max_entries=500):
    """Append a scan log entry dict and increment scan_count on the Reagent object."""
    try:
        folder = _get_reagents_folder(portal)
        obj = folder.get(uid)
        if obj is None:
            return False
        ann = IAnnotations(obj)
        raw = ann.get(_SCAN_LOG_KEY)
        log = json.loads(raw) if raw else []
        log.append(entry)
        if len(log) > max_entries:
            log = log[-max_entries:]
        ann[_SCAN_LOG_KEY] = json.dumps(log)
        obj.scan_count = (obj.scan_count or 0) + 1
        try:
            obj.reindexObject()
        except Exception:
            pass
        return True
    except Exception as exc:
        logger.error("_append_scan_log %s: %s", uid, exc)
        return False


def _delete_reagent(portal, uid):
    """Delete a Reagent content object.  Returns True if deleted."""
    try:
        folder = _get_reagents_folder(portal)
    except RuntimeError:
        return False
    if uid in folder:
        folder.manage_delObjects([uid])
        return True
    return False


def _archive_reagent(portal, uid, archived_by):
    """Soft-delete: mark a reagent archived via annotation. Returns True on success."""
    try:
        folder = _get_reagents_folder(portal)
    except RuntimeError:
        return False
    obj = folder.get(uid)
    if obj is None:
        return False
    ann = IAnnotations(obj)
    ann[_ANN_ARCHIVED_KEY] = json.dumps({
        "archived_by": archived_by,
        "archived_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    })
    try:
        obj.reindexObject()
    except Exception:
        pass
    return True


def _restore_reagent(portal, uid):
    """Remove archive annotation, restoring the reagent to the active list."""
    try:
        folder = _get_reagents_folder(portal)
    except RuntimeError:
        return False
    obj = folder.get(uid)
    if obj is None:
        return False
    ann = IAnnotations(obj)
    if _ANN_ARCHIVED_KEY in ann:
        del ann[_ANN_ARCHIVED_KEY]
    try:
        obj.reindexObject()
    except Exception:
        pass
    return True


def _purge_test_reagents(portal):
    """Hard-delete all reagents created before production_since. Returns count."""
    try:
        folder = _get_reagents_folder(portal)
    except RuntimeError:
        return 0
    prod_since = _get_production_since(portal)
    to_delete = []
    for obj in folder.objectValues():
        if obj.portal_type != "Reagent":
            continue
        if _is_test_reagent_by_time(obj, prod_since):
            to_delete.append(obj.getId())
    if to_delete:
        folder.manage_delObjects(to_delete)
    return len(to_delete)


def _list_reagents(portal, q="", status_filter="", category_filter="", show_archived=False):
    """Return filtered, sorted list of reagent dicts."""
    try:
        folder = _get_reagents_folder(portal)
    except RuntimeError:
        return []

    q_lower = (q or "").lower().strip()
    prod_since = _get_production_since(portal)
    results = []

    for obj in folder.objectValues():
        if obj.portal_type != "Reagent":
            continue
        d = _obj_to_dict(obj)

        # Archive filter: skip archived rows unless explicitly requested
        if d.get("is_archived") and not show_archived:
            continue

        if status_filter and d.get("status") != status_filter:
            continue
        if category_filter and d.get("category") != category_filter:
            continue
        if q_lower:
            searchable = u" ".join([
                d.get("name", ""),
                d.get("cat_number", ""),
                d.get("lot_number", ""),
                d.get("supplier", ""),
            ]).lower()
            if q_lower not in searchable:
                continue

        # Live expiry display — transient only; real write happens on next save
        if d.get("status") == STATUS_ACTIVE and _is_expired(d):
            d["status"] = STATUS_EXPIRED

        d["is_test"] = _is_test_reagent_by_time(obj, prod_since)
        results.append(d)

    results.sort(key=lambda x: (x.get("name") or "").lower())
    return results


def _status_badge_class(status):
    return {
        STATUS_ACTIVE:     "badge-active",
        STATUS_OPENED:     "badge-opened",
        STATUS_EXHAUSTED:  "badge-exhausted",
        STATUS_EXPIRED:    "badge-expired",
        STATUS_QUARANTINE: "badge-quarantine",
    }.get(status, "badge-active")


def _expiry_class(rec):
    exp = _effective_expiry(rec)
    if not exp:
        return ""
    try:
        exp_date = datetime.strptime(exp, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return ""
    today = date.today()
    if exp_date < today:
        return "exp-expired"
    if (exp_date - today).days <= 30:
        return "exp-warning"
    return ""


# ── View ──────────────────────────────────────────────────────────────────────

class PFASReagentsView(BrowserView):
    """PFAS Reagent Inventory — add, scan, OCR, track, expire."""

    template = ViewPageTemplateFile("templates/reagents.pt")

    def __call__(self):
        try:
            _maybe_record_production_since(self._portal())
        except Exception:
            pass
        action = self.request.form.get("action", "")
        if action == "lookup_json":
            return self._handle_lookup_json()
        if action == "barcode_lookup":
            return self._handle_barcode_lookup()
        if action == "suppliers_json":
            return self._handle_suppliers_json()
        if action == "reagent_suggestions":
            return self._handle_reagent_suggestions_json()
        if self.request.method == "POST":
            try:
                from plone.protect.interfaces import IDisableCSRFProtection
                from zope.interface import alsoProvides
                alsoProvides(self.request, IDisableCSRFProtection)
            except ImportError:
                pass
            if action in ("add", "edit"):
                return self._handle_upsert()
            if action == "open":
                return self._handle_open()
            if action == "status":
                return self._handle_status_change()
            if action == "delete":
                return self._handle_delete()
            if action == "save_expiry_defaults":
                return self._handle_save_expiry_defaults()
            if action == "restore":
                return self._handle_restore_reagent()
            if action == "purge_test":
                return self._handle_purge_test_reagents()
            if action == "upload_coa":
                return self._handle_coa_upload()
            if action == "log_scan":
                return self._handle_log_scan()
        if action == "coa":
            return self._serve_coa()
        return self.template()

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _portal(self):
        return getToolByName(self.context, "portal_url").getPortalObject()

    def _redirect(self, url):
        self.request.response.redirect(url)
        return ""

    def _self_url(self):
        return "{0}/@@pfas-reagents".format(self.context.absolute_url())

    def portal_url(self):
        return getToolByName(self.context, "portal_url")()

    def ok_msg(self):
        return self.request.form.get("ok", "").replace("+", " ")

    def error_msg(self):
        return self.request.form.get("error", "").replace("+", " ")

    def q(self):
        return self.request.form.get("q", "")

    def status_filter(self):
        return self.request.form.get("status", "")

    def edit_uid(self):
        return self.request.form.get("edit_uid", "")

    def edit_data_json(self):
        uid = self.edit_uid()
        if uid:
            rec = _get_reagent(self._portal(), uid)
            if rec:
                return json.dumps(rec)
        return "null"

    # ── Template data ─────────────────────────────────────────────────────────

    def is_production_mode(self):
        return _is_production_mode(self._portal())

    def show_archived(self):
        return self.request.form.get("show_archived", "") == "1"

    def test_reagent_count(self):
        """Count of reagents created before production mode was activated."""
        prod_since = _get_production_since(self._portal())
        if prod_since is None:
            return 0
        try:
            folder = _get_reagents_folder(self._portal())
        except RuntimeError:
            return 0
        cnt = 0
        for obj in folder.objectValues():
            if obj.portal_type != "Reagent":
                continue
            ann = IAnnotations(obj)
            if ann.get(_ANN_ARCHIVED_KEY):
                continue  # already archived, don't double-count
            if _is_test_reagent_by_time(obj, prod_since):
                cnt += 1
        return cnt

    def reagents(self):
        return _list_reagents(
            self._portal(),
            q=self.q(),
            status_filter=self.status_filter(),
            show_archived=self.show_archived(),
        )

    def all_statuses(self):
        return ALL_STATUSES

    def categories(self):
        return REAGENT_CATEGORIES

    def effective_expiry(self, rec):
        return _effective_expiry(rec)

    def expiry_class(self, rec):
        return _expiry_class(rec)

    def status_badge_class(self, rec):
        return _status_badge_class(rec.get("status", STATUS_ACTIVE))

    def status_label(self, rec):
        status = rec.get("status", STATUS_ACTIVE)
        for k, v in ALL_STATUSES:
            if k == status:
                return v
        return status.capitalize()

    def total_count(self):
        return len(_list_reagents(self._portal()))

    def active_count(self):
        return len(_list_reagents(self._portal(), status_filter=STATUS_ACTIVE))

    def expiring_soon_count(self):
        today = date.today()
        cnt = 0
        for rec in _list_reagents(self._portal()):
            exp = _effective_expiry(rec)
            if exp:
                try:
                    d = datetime.strptime(exp, "%Y-%m-%d").date()
                    if today <= d <= today + timedelta(days=30):
                        cnt += 1
                except (ValueError, TypeError):
                    pass
        return cnt

    # ── Action handlers ───────────────────────────────────────────────────────

    def _handle_upsert(self):
        f = self.request.form
        data = {
            "uid":                 f.get("uid", "").strip() or None,
            "name":                f.get("name", "").strip(),
            "supplier":            f.get("supplier", "").strip(),
            "cat_number":          f.get("cat_number", "").strip(),
            "lot_number":          f.get("lot_number", "").strip(),
            "category":            f.get("category", "").strip(),
            "received_date":       f.get("received_date", "").strip(),
            "opened_date":         f.get("opened_date", "").strip(),
            "manufacturer_expiry": f.get("manufacturer_expiry", "").strip(),
            "expiry_date":         f.get("expiry_date", "").strip(),
            "storage_location":    f.get("storage_location", "").strip(),
            "quantity":            f.get("quantity", "").strip(),
            "unit":                f.get("unit", "").strip(),
            "notes":               f.get("notes", "").strip(),
            "status":              f.get("status", STATUS_ACTIVE).strip(),
        }
        if not data["name"] or not data["lot_number"]:
            url = "{0}?error=Name+and+Lot+Number+are+required".format(self._self_url())
            return self._redirect(url)
        uid = _save_reagent(self._portal(), data)
        url = "{0}?ok=Reagent+saved+%28lot+{1}%29".format(
            self._self_url(), data["lot_number"].replace(" ", "+"))
        return self._redirect(url)

    def expiry_defaults(self):
        return get_expiry_defaults(self._portal())

    def _handle_save_expiry_defaults(self):
        """Persist global expiry defaults (lab settings) — the preset periods
        assigned when a reagent/standard has no stated expiry."""
        portal = self._portal()
        s = _get_lab_settings(portal)
        f = self.request.form
        for k in EXPIRY_DEFAULTS:
            v = (f.get(k) or "").strip()
            if v:
                try:
                    s[k] = int(v)
                except (TypeError, ValueError):
                    pass
        _save_lab_settings(portal, s)
        return self._redirect("{0}?ok=Expiry+defaults+saved".format(self._self_url()))

    def _handle_open(self):
        uid = self.request.form.get("uid", "").strip()
        opened_date = self.request.form.get("opened_date", "").strip()
        if not uid:
            return self._redirect("{0}?error=Missing+uid".format(self._self_url()))
        rec = _get_reagent(self._portal(), uid)
        if not rec:
            return self._redirect("{0}?error=Reagent+not+found".format(self._self_url()))
        rec["opened_date"] = opened_date or date.today().strftime("%Y-%m-%d")
        rec["status"] = STATUS_OPENED
        if not rec.get("expiry_date") and not rec.get("manufacturer_expiry"):
            rec["expiry_date"] = _auto_expiry_from_open(
                rec.get("name", ""), rec["opened_date"],
                get_expiry_defaults(self._portal()))
        _save_reagent(self._portal(), rec)
        url = "{0}?ok=Marked+as+opened".format(self._self_url())
        return self._redirect(url)

    def _handle_status_change(self):
        uid = self.request.form.get("uid", "").strip()
        new_status = self.request.form.get("new_status", "").strip()
        rec = _get_reagent(self._portal(), uid)
        if not rec:
            return self._redirect("{0}?error=Reagent+not+found".format(self._self_url()))
        rec["status"] = new_status
        _save_reagent(self._portal(), rec)
        return self._redirect("{0}?ok=Status+updated".format(self._self_url()))

    def _handle_delete(self):
        uid = self.request.form.get("uid", "").strip()
        portal = self._portal()
        if _is_production_mode(portal):
            from AccessControl import getSecurityManager
            try:
                user = getSecurityManager().getUser().getUserName()
            except Exception:
                user = u"unknown"
            if _archive_reagent(portal, uid, user):
                return self._redirect("{0}?ok=Reagent+archived".format(self._self_url()))
            return self._redirect("{0}?error=Reagent+not+found".format(self._self_url()))
        else:
            if _delete_reagent(portal, uid):
                return self._redirect("{0}?ok=Reagent+deleted".format(self._self_url()))
            return self._redirect("{0}?error=Reagent+not+found".format(self._self_url()))

    def _handle_restore_reagent(self):
        uid = self.request.form.get("uid", "").strip()
        if _restore_reagent(self._portal(), uid):
            return self._redirect("{0}?ok=Reagent+restored".format(self._self_url()))
        return self._redirect("{0}?error=Reagent+not+found".format(self._self_url()))

    def _handle_purge_test_reagents(self):
        self.request.response.setHeader("Content-Type", "application/json")
        count = _purge_test_reagents(self._portal())
        return json.dumps({"ok": True, "purged": count})

    def _handle_reagent_suggestions_json(self):
        """Deduplicated name+supplier+cat combos for autofill (non-test, non-archived)."""
        self.request.response.setHeader("Content-Type", "application/json")
        if not _is_production_mode(self._portal()):
            return json.dumps({"suggestions": []})
        try:
            folder = _get_reagents_folder(self._portal())
        except RuntimeError:
            return json.dumps({"suggestions": []})
        prod_since = _get_production_since(self._portal())
        seen = {}
        for obj in folder.objectValues():
            if obj.portal_type != "Reagent":
                continue
            if _is_test_reagent_by_time(obj, prod_since):
                continue
            ann = IAnnotations(obj)
            if ann.get(_ANN_ARCHIVED_KEY):
                continue
            name = (obj.title or u"").strip()
            if not name:
                continue
            supplier = (obj.supplier or u"").strip()
            key = u"{}||{}".format(name.lower(), supplier.lower())
            if key not in seen:
                seen[key] = {
                    "name":             name,
                    "supplier":         supplier,
                    "cat_number":       (obj.cat_number or u"").strip(),
                    "category":         (obj.category or u"").strip(),
                    "storage_location": (obj.storage_location or u"").strip(),
                }
        suggestions = sorted(seen.values(), key=lambda x: x["name"].lower())
        return json.dumps({"suggestions": suggestions})

    def coa_meta(self, uid):
        """Return CoA metadata dict for display in the template."""
        return _get_coa_meta(self._portal(), uid)

    def _handle_coa_upload(self):
        uid = self.request.form.get("uid", "").strip()
        upload = self.request.form.get("coa_file")
        if not uid or not upload:
            return self._redirect("{0}?error=Missing+file+or+uid".format(self._self_url()))
        try:
            file_data = upload.read()
            filename = getattr(upload, "filename", "coa.pdf")
            content_type = getattr(upload, "headers", {}).get(
                "content-type", "application/pdf")
        except Exception as exc:
            return self._redirect("{0}?error=Upload+failed%3A+{1}".format(
                self._self_url(), str(exc).replace(" ", "+")))

        from AccessControl import getSecurityManager
        try:
            user = getSecurityManager().getUser().getUserName()
        except Exception:
            user = "unknown"

        ok = _save_coa(self._portal(), uid, file_data, filename, content_type, user)
        if ok:
            return self._redirect("{0}?ok=CoA+uploaded".format(self._self_url()))
        return self._redirect("{0}?error=CoA+save+failed".format(self._self_url()))

    def _serve_coa(self):
        """Serve the stored CoA file for a given reagent uid."""
        uid = self.request.form.get("uid", "").strip()
        meta = _get_coa_meta(self._portal(), uid)
        path = meta.get("path", "")
        if not path or not os.path.exists(path):
            self.request.response.setStatus(404)
            return "CoA not found"
        ct = meta.get("content_type", "application/pdf")
        fn = meta.get("filename", "coa.pdf")
        self.request.response.setHeader("Content-Type", ct)
        self.request.response.setHeader(
            "Content-Disposition",
            'inline; filename="{}"'.format(fn)
        )
        with open(path, "rb") as fh:
            return fh.read()

    def scan_log_count(self, uid):
        """Return the current scan_count integer for a reagent uid."""
        try:
            folder = _get_reagents_folder(self._portal())
            obj = folder.get(uid)
            if obj is None:
                return 0
            return obj.scan_count or 0
        except Exception:
            return 0

    def _handle_barcode_lookup(self):
        """Exact-match lookup of a scanned value against barcode, lot_number, cat_number."""
        scanned = self.request.form.get("barcode", "").strip()
        self.request.response.setHeader("Content-Type", "application/json")
        if not scanned:
            return json.dumps({"match": None})
        try:
            folder = _get_reagents_folder(self._portal())
        except RuntimeError:
            return json.dumps({"match": None})
        for obj in folder.objectValues():
            if obj.portal_type != "Reagent":
                continue
            barcode = (obj.barcode    or "").strip()
            lot     = (obj.lot_number or "").strip()
            cat     = (obj.cat_number or "").strip()
            if scanned in (barcode, lot, cat):
                d = _obj_to_dict(obj)
                coa = _get_coa_meta(self._portal(), d["uid"])
                d["has_coa"] = bool(coa)
                return json.dumps({"match": d})
        return json.dumps({"match": None})

    def _handle_log_scan(self):
        """Append a scan log entry and increment scan_count. Returns JSON."""
        self.request.response.setHeader("Content-Type", "application/json")
        uid           = self.request.form.get("uid", "").strip()
        scanned_value = self.request.form.get("scanned_value", "").strip()
        notes         = self.request.form.get("notes", "").strip()
        if not uid:
            return json.dumps({"ok": False, "error": "Missing uid"})
        from AccessControl import getSecurityManager
        try:
            user = getSecurityManager().getUser().getUserName()
        except Exception:
            user = "unknown"
        entry = {
            "timestamp":     datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "scanned_by":    user,
            "scanned_value": scanned_value,
            "notes":         notes,
        }
        ok = _append_scan_log(self._portal(), uid, entry)
        if ok:
            rec = _get_reagent(self._portal(), uid)
            count = rec.get("scan_count", 0) if rec else 0
            return json.dumps({"ok": True, "count": count})
        return json.dumps({"ok": False, "error": "Reagent not found or save failed"})

    def _handle_suppliers_json(self):
        """Return sorted list of distinct supplier names from existing reagents."""
        self.request.response.setHeader("Content-Type", "application/json")
        try:
            folder = _get_reagents_folder(self._portal())
        except RuntimeError:
            return json.dumps({"suppliers": []})
        seen = set()
        for obj in folder.objectValues():
            if obj.portal_type != "Reagent":
                continue
            s = (obj.supplier or "").strip()
            if s:
                seen.add(s)
        return json.dumps({"suppliers": sorted(seen)})

    def _handle_lookup_json(self):
        """JSON endpoint for logbook reagent lookup (no auth check — same as other views)."""
        q = self.request.form.get("q", "")
        limit = int(self.request.form.get("limit", "20"))
        results = _list_reagents(self._portal(), q=q)[:limit]
        out = []
        for r in results:
            out.append({
                "uid":          r.get("uid", ""),
                "name":         r.get("name", ""),
                "supplier":     r.get("supplier", ""),
                "cat_number":   r.get("cat_number", ""),
                "lot_number":   r.get("lot_number", ""),
                "expiry_date":  _effective_expiry(r),
                "status":       r.get("status", STATUS_ACTIVE),
            })
        self.request.response.setHeader("Content-Type", "application/json")
        return json.dumps({"items": out})
