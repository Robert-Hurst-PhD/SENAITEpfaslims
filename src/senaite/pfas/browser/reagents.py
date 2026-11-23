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
from datetime import datetime, timedelta

from zope.annotation.interfaces import IAnnotations
from zope.event import notify
from zope.lifecycleevent import ObjectModifiedEvent

from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from senaite.pfas import lab_time
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.uploads import CONTENT_TYPES, content_type_for
from senaite.pfas.browser.perms import TIER_CONFIG, GateMixin, deny_gated_action, signed_in_name
from senaite.pfas.holding_time import date_to_iso as _date_to_str, parse_date as _str_to_date

logger = logging.getLogger("senaite.pfas.browser.reagents")

# Reagent status values
STATUS_ACTIVE     = "active"
STATUS_OPENED     = "opened"
STATUS_EXHAUSTED  = "exhausted"
STATUS_EXPIRED    = "expired"
STATUS_QUARANTINE = "quarantine"
STATUS_PENDING    = "pending"       # a new lot until accepted (lot_status)

ALL_STATUSES = [
    (STATUS_ACTIVE,     "Active"),
    (STATUS_OPENED,     "Opened"),
    (STATUS_EXHAUSTED,  "Exhausted"),
    (STATUS_EXPIRED,    "Expired"),
    (STATUS_QUARANTINE, "Quarantine"),
    (STATUS_PENDING,    "Pending acceptance"),
]

# ── Lab settings / archive ────────────────────────────────────────────────────
_LAB_SETTINGS_KEY = u"senaite.pfas.lab_settings"
_ANN_ARCHIVED_KEY = u"senaite.pfas.reagent.archived"

# Reagent categories (ISO 17025-friendly)
# Vocabulary is OWNED by the Reagent content type — single source of truth
# (was duplicated here). Imported so this view stays in lock-step.
from senaite.pfas.document_templates import script_json
from senaite.pfas.browser.view_helpers import ViewHelpers

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


def _defaults(defaults):
    """`defaults`, else the lab's saved expiry defaults: one rule for every
    page (the shipped seeds only where no site is at hand)."""
    if defaults:
        return defaults
    try:
        from bika.lims import api
        return get_expiry_defaults(api.get_portal())
    except Exception:                                       # noqa: BLE001
        return EXPIRY_DEFAULTS


def _auto_expiry_from_open(name, opened_date_str, defaults=None):
    """Calculate auto-expiry from open date.

    Mobile phases: `mobile_phase_open_days` (default 7); all others
    `opened_default_days` (default 365). Periods come from the global
    expiry defaults, not hardcoded.
    Returns ISO date string or empty string if input is invalid.
    """
    if not opened_date_str:
        return ""
    try:
        opened = datetime.strptime(opened_date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return ""
    d = _defaults(defaults)
    if _MOBILE_PHASE_RE.search(name or ""):
        exp = opened + timedelta(days=int(d.get("mobile_phase_open_days", 7)))
    else:
        exp = opened + timedelta(days=int(d.get("opened_default_days", 365)))
    return exp.strftime("%Y-%m-%d")


def _effective_expiry(rec, defaults=None, as_of=None):
    """Expiry date string in effect for a record on `as_of` (a laboratory
    day; None is now): the latest extension QA approved by then
    (lot_extension.in_force, over the record's "extensions"), else
    _base_expiry. A lot whose category has no expiry ("no_expiry", a lab
    setting) never expires, whatever date it carries: "" (lot_expiry.NO_EXPIRY)."""
    if rec.get("no_expiry"):
        return u""
    from senaite.pfas import lot_extension
    return lot_extension.in_force(_base_expiry(rec, defaults), rec.get("extensions"), as_of)


def no_expiry_categories():
    """The reagent categories whose "No expiry" switch is on (the lab's
    category list, vocab_store)."""
    try:
        from bika.lims import api
        from senaite.pfas import vocab_store as vs
        return vs.flagged(vs.get(api.get_portal()), "reagent_categories", "no_expiry")
    except Exception:                                       # noqa: BLE001
        logger.warning("no-expiry categories not readable", exc_info=True)
        return set()


def no_coa_categories():
    """The reagent categories whose "No CoA" switch is on (the lab's
    category list, vocab_store): a lot in one is not marked for a missing
    CoA."""
    try:
        from bika.lims import api
        from senaite.pfas import vocab_store as vs
        return vs.flagged(vs.get(api.get_portal()), "reagent_categories", "no_coa")
    except Exception:                                       # noqa: BLE001
        logger.warning("no-CoA categories not readable", exc_info=True)
        return set()


def _base_expiry(rec, defaults=None):
    """The lot's own expiry, before any extension.

    Inheritance chain: explicit expiry_date → manufacturer_expiry → GLOBAL
    default (received_date + reagent_default_days) so a manufactured reagent
    without a stated expiry is still governed by the preset global value."""
    exp = rec.get("expiry_date") or rec.get("manufacturer_expiry") or ""
    if exp:
        return exp
    received = rec.get("received_date") or ""
    if received:
        d = _defaults(defaults)
        try:
            rd = datetime.strptime(received, "%Y-%m-%d").date()
            return (rd + timedelta(days=int(d.get("reagent_default_days", 365)))
                    ).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            pass
    return ""


def migrate_expiry_source(portal):
    """Record once, on every reagent lot that has none, where its
    expiry_date came from (lot_expiry.migrated_source: assigned when its
    note and value say the default period set it, else entered). A lot that
    has a source is never touched again, so a second run changes nothing.
    Returns the number of lots given a source."""
    from senaite.pfas import lot_expiry as le
    try:
        folder = _get_reagents_folder(portal)
    except RuntimeError:
        return 0
    n = 0
    for obj in folder.objectValues():
        if getattr(obj, "portal_type", "") != "Reagent":
            continue
        ann = IAnnotations(obj)
        if le.SOURCE_KEY in ann:
            continue
        rec = {"expiry_date": _date_to_str(obj.expiry_date),
               "manufacturer_expiry": _date_to_str(obj.manufacturer_expiry),
               "received_date": _date_to_str(obj.received_date), "notes": obj.notes or u""}
        ann[le.SOURCE_KEY] = le.migrated_source(rec)
        n += 1
    return n


def _is_expired(rec, as_of=None):
    """Is this lot expired, as of `as_of` (default today)?

    `as_of` exists because judging a lot against TODAY makes a released batch
    less defensible as time passes: every standard on this instance is now
    expired, yet the runs that used them were in date at the time. The
    traceability record has to be judged against the date the lot was USED --
    decided in item 7 and never implemented until now.

    An UNKNOWN expiry still returns False here, because "no date recorded" is
    not the same claim as "expired" and this answer drives the lot picker. It is
    not silence, though: `_expiry_unknown` reports it separately and the
    traceability gate treats it as unresolved.
    """
    from senaite.pfas.lot_expiry import expired_on
    day = as_of or lab_time.today()
    return expired_on(_effective_expiry(rec, as_of=u"%s" % day), day)


def _expiry_unknown(rec):
    """True when no expiry can be resolved for this lot at all.

    Distinct from `_is_expired`, which answers False for such a lot -- correctly,
    since an unrecorded date is not evidence of expiry. But it must not read as
    a clean bill of health either: an undated lot is undocumented, and
    makes provenance a hard requirement. The gate refuses rather
    than guessing, which is the same posture `tests/test_holding_time.py` pins
    for an unset holding time.
    """
    return not rec.get("no_expiry") and not _effective_expiry(rec)


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
    try:   # change history (R1)
        from senaite.pfas import config_history
        config_history.track(portal, 'reagent_expiry', "defaults", lambda: get_expiry_defaults(portal), label=u"Reagent & standard expiry defaults")
    except Exception:
        pass
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
        created = obj.created()
        cd = datetime(
            created.year(), created.month(), created.day(),
            created.hour(), created.minute(), int(created.second()),
        )
        return cd < prod_since
    except Exception:
        return False






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
        "storage_conditions": getattr(obj, "storage_conditions", None) or u"",
        "barcode":            obj.barcode or u"",
        "quantity":           obj.quantity or u"",
        "unit":               obj.unit or u"",
        "low_stock_level":    getattr(obj, "low_stock_level", None) or u"",
        "scan_count":         obj.scan_count or 0,
        "status":             obj.status or STATUS_ACTIVE,
        "notes":              obj.notes or u"",
        "is_test":            False,  # overwritten by _list_reagents
    }
    ann = IAnnotations(obj)
    # the extensions QA approved or was asked for (lot_extension.py)
    from senaite.pfas import lot_extension
    d["extensions"] = lot_extension.entries(ann.get(lot_extension.KEY))
    # where its expiry_date came from: entered or assigned (lot_expiry)
    from senaite.pfas import lot_expiry as le
    d["expiry_source"] = ann.get(le.SOURCE_KEY) or u""
    # a lot whose category has no expiry never expires (_effective_expiry):
    # a status "expired" a save stored before its category had no expiry
    # reads as active
    d["no_expiry"] = d["category"] in no_expiry_categories()
    # a lot whose category needs no CoA is not marked for a missing one
    d["no_coa"] = d["category"] in no_coa_categories()
    if d["no_expiry"] and d["status"] == STATUS_EXPIRED:
        d["status"] = STATUS_ACTIVE
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
    obj.storage_conditions = data.get("storage_conditions") or u""
    obj.barcode = data.get("barcode") or u""
    obj.quantity = data.get("quantity") or u""
    obj.unit = data.get("unit") or u""
    obj.low_stock_level = data.get("low_stock_level") or u""
    obj.notes = data.get("notes") or u""
    obj.scan_count = int(data.get("scan_count") or 0)
    obj.status = data.get("status") or STATUS_ACTIVE
    old_expiry = _date_to_str(getattr(obj, "expiry_date", None))

    # Date fields: accept both ISO strings (from forms) and datetime.date objects
    for field_name in ("received_date", "expiry_date", "manufacturer_expiry", "opened_date"):
        raw = data.get(field_name)
        if isinstance(raw, (str, bytes)):
            setattr(obj, field_name, _str_to_date(raw))
        else:
            setattr(obj, field_name, raw)

    # Auto-compute expiry from opened_date when not supplied; a lot whose
    # category has no expiry never takes a default
    defaults = _defaults(data.get("_expiry_defaults"))
    no_expiry = bool(data.get("_no_expiry"))
    assigned = False
    if not no_expiry and not obj.expiry_date and not obj.manufacturer_expiry and obj.opened_date:
        computed = _auto_expiry_from_open(obj.title, _date_to_str(obj.opened_date),
                                          defaults)
        obj.expiry_date = _str_to_date(computed)
        assigned = bool(obj.expiry_date)

    # Global-default assignment: a manufactured reagent with NO stated expiry
    # (neither explicit nor manufacturer) is assigned received_date + the
    # preset global period, so every lot is governed by a real date.
    if not no_expiry and not obj.expiry_date and not obj.manufacturer_expiry and obj.received_date:
        rd = obj.received_date
        obj.expiry_date = rd + timedelta(
            days=int(defaults.get("reagent_default_days", 365)))
        note = u"Expiry assigned from global default ({0} days from receipt)".format(
            defaults.get("reagent_default_days", 365))
        obj.notes = (obj.notes + u"\n" + note).strip() if obj.notes else note
        assigned = True

    # where the expiry_date came from, kept on the lot: an assigned date is
    # not a recorded one (lot_extension.edit_problems)
    from senaite.pfas import lot_expiry as le
    ann = IAnnotations(obj)
    ann[le.SOURCE_KEY] = le.source_after_save(old_expiry, _date_to_str(obj.expiry_date),
                                              ann.get(le.SOURCE_KEY) or u"", assigned)

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
        # a new lot is accepted before use (lot_status)
        from senaite.pfas.lot_status import initial_status
        data["status"] = initial_status(True)

    data["_expiry_defaults"] = get_expiry_defaults(portal)
    data["_no_expiry"] = (data.get("category") or u"") in no_expiry_categories()
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
        # Resolve the reagent FIRST. This wrote the file to disk,
        # then skipped the annotation when the reagent did not exist, then
        # returned True regardless -- so POSTing a CoA against a uid that is not
        # a reagent reported "CoA uploaded", attached it to nothing, and left an
        # orphan file behind. The operator is told the lot is documented when it
        # is not, which is worse than an outright failure.
        folder = _get_reagents_folder(portal)
        obj = folder.get(uid) if uid else None
        if obj is None or getattr(obj, "portal_type", "") != "Reagent":
            logger.error("_save_coa: no Reagent for uid %r -- refusing", uid)
            return False
        if not os.path.isdir(COA_DIR):
            os.makedirs(COA_DIR)
        ext = os.path.splitext(filename)[1] if filename else ".pdf"
        dest = os.path.join(COA_DIR, "{}{}" .format(uid, ext))
        with open(dest, "wb") as fh:
            fh.write(file_data)
        if obj is not None:
            ann = IAnnotations(obj)
            ann[_COA_ANN_KEY] = json.dumps({
                "filename":     filename,
                "content_type": content_type,
                "uploaded_by":  uploaded_by,
                "uploaded_date":lab_time.today().isoformat(),
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



def _append_scan_log(portal, uid, entry):
    """Append a scan log entry dict and increment scan_count on the Reagent
    object. Every scan is kept: the lot's use record is never trimmed."""
    try:
        folder = _get_reagents_folder(portal)
        obj = folder.get(uid)
        if obj is None:
            return False
        ann = IAnnotations(obj)
        raw = ann.get(_SCAN_LOG_KEY)
        log = json.loads(raw) if raw else []
        log.append(entry)
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


def _used_reagent_uids(portal):
    """Reagent lots a record names: the inventory ledger (an extraction, a
    prep entry) and every prepared standard's parent reagents."""
    used = set()
    from senaite.pfas import inventory_ledger
    for kind, uid in inventory_ledger.uses_for_items():
        if kind == u"reagent":
            used.add(uid)
    from senaite.pfas.browser.prepared_standards import _list as _list_standards
    for ps in _list_standards(portal):
        for p in ps.get("parent_reagents") or []:
            if p.get("uid"):
                used.add(p["uid"])
    return used


def _purge_test_reagents(portal):
    """Hard-delete the reagents created before production began, except a lot
    a record names: (deleted, kept). Nothing is deleted outside production or
    without its start date (every lot would count as before it)."""
    try:
        folder = _get_reagents_folder(portal)
    except RuntimeError:
        return 0, 0
    prod_since = _get_production_since(portal)
    if prod_since is None or not _is_production_mode(portal):
        return 0, 0
    used = _used_reagent_uids(portal)
    to_delete, kept = [], 0
    for obj in folder.objectValues():
        if obj.portal_type != "Reagent" or not _is_test_reagent_by_time(obj, prod_since):
            continue
        if obj.UID() in used:
            kept += 1
        else:
            to_delete.append(obj.getId())
    if to_delete:
        folder.manage_delObjects(to_delete)
    return len(to_delete), kept


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

        from senaite.pfas.lot_status import matches_filter
        if not matches_filter(d.get("status"), status_filter):
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
        STATUS_PENDING:    "badge-pending",
    }.get(status, "badge-active")


def _expiry_class(rec):
    exp = _effective_expiry(rec)
    if not exp:
        return ""
    try:
        exp_date = datetime.strptime(exp, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return ""
    today = lab_time.today()
    if exp_date < today:
        return "exp-expired"
    if (exp_date - today).days <= 30:
        return "exp-warning"
    return ""


# ── View ──────────────────────────────────────────────────────────────────────

# Lab configuration within the reagent inventory. Everything else
# here -- add, edit, open, status, CoA upload, scan, and delete (which ARCHIVES
# in production and is reversible via restore) -- is bench work and stays open,
# performable by a person or a future service account.
# `purge_test` hard-deletes the reagents created before production began that
# no record names; it refuses outside production.
def _q(text):
    """Text for a redirect's query string."""
    try:
        from urllib import quote_plus            # Python 2
    except ImportError:                         # Python 3
        from urllib.parse import quote_plus
    return quote_plus((u"%s" % text).encode("utf-8"))


REAGENT_GATES = {
    "save_expiry_defaults": TIER_CONFIG,
    "purge_test": TIER_CONFIG,
    # removing or restoring a lot record, and replacing its certificate file
    "delete": TIER_CONFIG,
    "restore": TIER_CONFIG,
    "upload_coa": TIER_CONFIG,
}


class PFASReagentsView(ViewHelpers, GateMixin, BrowserView):
    """PFAS Reagent Inventory — add, scan, OCR, track, expire."""

    template = ViewPageTemplateFile("templates/reagents.pt")
    # Materials & Containers is this page over the lots whose category has
    # no expiry (PFASMaterialsView); the inventory lists every other lot
    materials = False
    page_title = u"Reagent Inventory"

    def __call__(self):
        flatten_form(self.request)
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
            denied = deny_gated_action(
                self.context, self.request, action, REAGENT_GATES)
            if denied is not None:
                return denied
            from senaite.pfas.browser.perms import disable_csrf
            disable_csrf(self.request)
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
            if action == "save_certificate":
                return self._handle_save_certificate()
            if action == "receipt":
                return self._handle_receipt()
        if action == "coa":
            return self._serve_coa()
        return self.template()

    # ── Helpers ──────────────────────────────────────────────────────────────

    # ── reference samples: receipt and CoA ────────────────────────────

    def view_mode(self):
        """Lots | Reference samples."""
        return u"reference" if self.request.form.get("view") == "reference" else u"lots"

    def analyte_keywords(self):
        """Every method's analyte keywords (master_analyte_set): what a
        certificate's analytes are named by."""
        if not hasattr(self, "_keywords"):
            out = set()
            try:
                from senaite.pfas.method_profile_store import list_method_ids, raw_profile
                for mid in list_method_ids(self._portal()):
                    out.update((raw_profile(self._portal(), mid) or {}).get("master_analyte_set") or [])
            except Exception:                               # noqa: BLE001
                logger.warning("analyte keywords", exc_info=True)
            self._keywords = sorted(out)
        return self._keywords

    def library_cas(self):
        """{analyte keyword: CAS} from the compound library, shown read-only
        beside a certificate's analytes (a placeholder shows as none)."""
        try:
            from senaite.pfas import compound_library, compound_library_store
            return dict((kw, c) for kw, c in compound_library.cas_by_keyword(
                compound_library_store.library(self._portal()), dashed=True).items()
                if c and "PLACEHOLDER" not in c.upper())
        except Exception:                                   # noqa: BLE001
            logger.warning("library CAS", exc_info=True)
            return {}

    def reference_category(self):
        from senaite.pfas.content.reagent import CATEGORY_REFERENCE
        return CATEGORY_REFERENCE

    def _reference_lots(self):
        """Usable reference-sample lots: the inventory's reference category."""
        if not hasattr(self, "_ref_lots"):
            from senaite.pfas import study_runs as sru
            from senaite.pfas.browser.bench_inventory import usable_lots
            from senaite.pfas.content.reagent import CATEGORY_PURCHASED_WATER, CATEGORY_REFERENCE
            self._ref_lots = sru.lot_choices(usable_lots(self._portal(), lab_time.today().isoformat()),
                                             sru.REFERENCE_LOT, CATEGORY_REFERENCE, CATEGORY_PURCHASED_WATER)
        return self._ref_lots

    def _reagent_obj(self, uid):
        folder = self._portal().get("pfas_reagents")
        obj = folder.get(uid) if folder is not None and uid else None
        return obj if getattr(obj, "portal_type", "") == "Reagent" else None

    def reference_samples(self):
        """Every usable reference-sample lot with its receipt and CoA."""
        from senaite.pfas import study_runs as sru
        out = []
        for l in self._reference_lots():
            obj = self._reagent_obj(l["uid"])
            out.append(dict(l, receipt=sru.load_receipt(obj) if obj is not None else None,
                            coa=_get_coa_meta(self._portal(), l["uid"]) or None))
        return out

    def _handle_receipt(self):
        """Record a reference sample's receipt; its CoA goes where every
        lot's CoA goes (the reagent's own). Checked first, written after: a
        refused receipt changes nothing."""
        from senaite.pfas import study_runs as sru
        from six.moves.urllib.parse import quote_plus
        f = self.request.form
        back = u"%s?view=reference" % self._self_url()

        def refused(msg):
            return self._redirect(u"%s&error=%s" % (back, quote_plus(msg.encode("utf-8"))))
        uid = (f.get("uid") or u"").strip()
        if uid not in [l["uid"] for l in self._reference_lots()]:
            return refused(u"Only a usable reference-sample lot takes a receipt here.")
        obj = self._reagent_obj(uid)
        who = signed_in_name(self.context)
        receipt, error = sru.new_receipt(f, sru.load_receipt(obj), who,
                                         datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"))
        if error:
            return refused(error)
        received = _str_to_date((f.get("received_at") or u"").strip()[:10])
        if received is None:
            return refused(u"Give the date it was received as a date.")
        upload, data = f.get("coa_file"), None
        if upload is not None and getattr(upload, "filename", u""):
            data = upload.read()
            if not data.startswith(b"%PDF"):
                return refused(u"The CoA must be a PDF.")
        if data is not None and not _save_coa(self._portal(), uid, data, upload.filename,
                                              "application/pdf", who):
            return refused(u"The CoA was not saved.")
        sru.save_receipt(obj, receipt)
        # the lot's own Received Date, through the inventory's save (its
        # derived expiry and its modified event, the audit log's snapshot)
        lot = _get_reagent(self._portal(), uid)
        lot["received_date"] = received.isoformat()
        _save_reagent(self._portal(), lot)
        return self._redirect(u"%s&ok=Receipt+recorded" % back)

    def _self_url(self):
        return "{0}/@@{1}".format(self.context.absolute_url(),
                                  "pfas-materials" if self.materials else "pfas-reagents")

    def ok_msg(self):
        return self.request.form.get("ok", "").replace("+", " ")

    def error_msg(self):
        return self.request.form.get("error", "").replace("+", " ")

    def q(self):
        return self.request.form.get("q", "")

    def status_filter(self):
        """The Status filter: Active until someone chooses ("all" = every
        status)."""
        s = self.request.form.get("status")
        if s is None:
            return STATUS_ACTIVE
        return u"" if s == "all" else s

    def edit_uid(self):
        return self.request.form.get("edit_uid", "")

    def edit_data_json(self):
        uid = self.edit_uid()
        if uid:
            rec = _get_reagent(self._portal(), uid)
            if rec:
                return script_json(rec)
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
        # the same lot records on both pages, split by the category's
        # "No expiry" switch
        return [r for r in _list_reagents(
            self._portal(),
            q=self.q(),
            status_filter=self.status_filter(),
            show_archived=self.show_archived(),
        ) if bool(r.get("no_expiry")) == self.materials]

    def all_statuses(self):
        return ALL_STATUSES

    def categories(self):
        """[(key, label)]: the lab's reagent categories, those with no
        expiry on Materials & Containers, the others on the inventory."""
        from bika.lims import api
        from senaite.pfas import vocab_store as vs
        stored = vs.get(api.get_portal())
        none = vs.flagged(stored, "reagent_categories", "no_expiry")
        return [(k, l) for k, l in vs.options(stored, "reagent_categories") if (k in none) == self.materials]

    def effective_expiry(self, rec):
        return _effective_expiry(rec)

    def shown_expiry(self, rec):
        """The expiry column: "No expiry" for a lot whose category has none."""
        from senaite.pfas import lot_expiry as le
        return le.shown_expiry(_effective_expiry(rec), rec.get("no_expiry"))

    # ── Certificate values ────────────────────────────────

    def _certificate_obj(self, uid):
        try:
            return _get_reagents_folder(self._portal()).get(uid)
        except RuntimeError:
            return None

    def certificate(self):
        """The certificate dialog's data for ?certificate=<uid>, or None."""
        from senaite.pfas import certificate_values as cv
        from senaite.pfas import prep_entries as pe
        from senaite.pfas.browser.prepared_standards import _get as _get_ps
        uid = (self.request.form.get("certificate") or u"").strip()
        obj = self._certificate_obj(uid) if uid else None
        if obj is None:
            return None
        rec = _obj_to_dict(obj) or {}
        from senaite.pfas.annotation_store import read_json
        cert = read_json(obj, cv.KEY, {})
        made = [(_get_ps(self._portal(), u) or {}).get("lot_number") or u for u in
                cv.made_from(uid, pe.load(self._portal()))]
        rows = cv.rows(cert) + [{"analyte": u"", "stated_as": u"acid"}]   # one empty row to add to
        return {"uid": uid, "name": rec.get("name") or u"", "lot": rec.get("lot_number") or u"",
                "cert": cert, "rows": rows, "made_from": made, "on_file": bool(cert.get("analytes")),
                "corrections": list(reversed(cert.get("corrections") or []))}

    def _handle_save_certificate(self):
        """Save a lot's certificate values; a change to a value on file needs a
        reason, is kept, and flags the lots made from the lot and the runs that
        used them for review -- nothing is recalculated."""
        from senaite.pfas import certificate_values as cv
        from senaite.pfas import inventory_ledger as led
        from senaite.pfas import prep_entries as pe
        from senaite.pfas.browser.staff import may_enter
        from senaite.pfas.entry_rights import REFUSAL
        f = self.request.form
        uid = (f.get("uid") or u"").strip()
        back = u"%s?certificate=%s" % (self._self_url(), uid)
        if not may_enter():
            return self._redirect(u"%s&error=%s" % (back, _q(REFUSAL)))
        obj = self._certificate_obj(uid)
        if obj is None:
            return self._redirect(u"%s?error=No+such+lot" % self._self_url())
        ann = IAnnotations(obj)
        try:
            before = json.loads(ann.get(cv.KEY) or "{}")
        except (TypeError, ValueError):
            before = {}
        after, errors = cv.from_form(f, known=self.analyte_keywords() or None)
        if errors:
            return self._redirect(u"%s&error=%s" % (back, _q(u" ".join(errors))))
        who = signed_in_name(self.context)
        at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M")
        out, err = cv.correct(before, after, f.get("reason") or u"", who, at)
        if err:
            return self._redirect(u"%s&error=%s" % (back, _q(err)))
        try:
            from senaite.pfas import config_history
            config_history.track(self._portal(), "reagent_certificate", uid,
                                 lambda: json.loads(ann.get(cv.KEY) or "{}"), label=u"Certificate values")
        except Exception:                                   # noqa: BLE001
            pass
        ann[cv.KEY] = json.dumps(out, sort_keys=True)
        added = len(out.get("corrections") or []) - len(before.get("corrections") or [])
        if added:
            from senaite.pfas.browser.prepared_standards import _get_folder as _ps_folder
            from bika.lims import api
            rec = _obj_to_dict(obj) or {}
            entry = cv.flag_entry(u"Certificate values of %s corrected: %s" % (
                rec.get("lot_number") or uid, (f.get("reason") or u"").strip()), who, at)
            lots = cv.made_from(uid, pe.load(self._portal()))
            folder = _ps_folder(self._portal())
            runs = set()
            for lot_uid in lots:
                lot = folder.get(lot_uid)
                if lot is not None:
                    cv.add_flag(lot, entry)
            for kind, u in [(u"reagent", uid)] + [(u"prepared", l) for l in lots]:
                for use in led.uses_of(None, kind, u):
                    if not (use.get("batch_uid") or u"").startswith(u"prep:"):
                        runs.add(use.get("batch_uid"))
            for ws_uid in sorted(runs):
                ws = api.get_object_by_uid(ws_uid, None)
                if ws is not None:
                    cv.add_flag(ws, entry)
        return self._redirect(u"%s?ok=Certificate+values+saved" % self._self_url())


    def label_url(self, rec):
        """Print label: this lot's values on @@pfas-label."""
        from senaite.pfas.browser.label_print import label_href
        vol = u" ".join(x for x in (rec.get("quantity") or u"", rec.get("unit") or u"") if x)
        from senaite.pfas import lot_expiry as le, lot_extension
        return label_href(self.portal_url(), back=self._self_url(), name=rec.get("name"),
                          lot=rec.get("lot_number"),
                          exp=le.shown_expiry(self.effective_expiry(rec), rec.get("no_expiry")), vol=vol,
                          storage=rec.get("storage_conditions") or rec.get("storage_location"),
                          **lot_extension.label_values(rec.get("extensions")))

    def expiry_class(self, rec):
        return _expiry_class(rec)

    def lot_status_label(self, status):
        return dict(ALL_STATUSES).get(status, (status or u"").capitalize())

    def status_badge_class(self, rec):
        return _status_badge_class(rec.get("status", STATUS_ACTIVE))

    def attention(self, rec):
        """Why an active lot needs attention (lot_attention), else []."""
        if rec.get("status", STATUS_ACTIVE) != STATUS_ACTIVE or rec.get("is_archived"):
            return []
        from senaite.pfas import lot_attention
        # a lot whose category needs no CoA is not asked for one
        coa = None if rec.get("no_coa") else bool(self.coa_meta(rec.get("uid", "")))
        return lot_attention.reasons(expiry=_effective_expiry(rec), quantity=rec.get("quantity"),
                                     low_stock=rec.get("low_stock_level"), coa=coa)

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
        today = lab_time.today()
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
            "storage_conditions":  f.get("storage_conditions", "").strip(),
            "quantity":            f.get("quantity", "").strip(),
            "unit":                f.get("unit", "").strip(),
            "low_stock_level":     f.get("low_stock_level", "").strip(),
            "notes":               f.get("notes", "").strip(),
            "status":              f.get("status", STATUS_ACTIVE).strip(),
        }
        if not data["name"] or not data["lot_number"]:
            url = "{0}?error=Name+and+Lot+Number+are+required".format(self._self_url())
            return self._redirect(url)
        # supplier and storage are core's lists (core_lists.py)
        from senaite.pfas.browser.core_lists import problems
        from senaite.pfas.browser.core_lists import lot_problems
        from six.moves.urllib.parse import quote_plus
        bad = lot_problems(data) + problems(data)
        # a recorded expiry moves earlier only: a later date comes through an
        # extension (lot_extension.edit_problems); the date the system
        # assigned is not recorded, so a supplier's date may replace it
        from senaite.pfas import lot_expiry as le, lot_extension
        old = _get_reagent(self._portal(), data["uid"]) if data["uid"] else None
        if old:
            computed = ("expiry_date",) if old.get("expiry_source") == le.ASSIGNED else ()
            bad += lot_extension.edit_problems(
                (("expiry_date", u"The expiry"), ("manufacturer_expiry", u"The manufacturer's expiry")),
                old, data, computed)
            if computed and data["manufacturer_expiry"] and \
                    data["expiry_date"][:10] == (old.get("expiry_date") or u"")[:10]:
                # the supplier's date replaces the one the system assigned
                data["expiry_date"] = u""
        if bad:
            return self._redirect("{0}?error={1}".format(self._self_url(), quote_plus(bad[0].encode("utf-8"))))
        _save_reagent(self._portal(), data)
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
        rec["opened_date"] = opened_date or lab_time.today().isoformat()
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
        if new_status not in [k for k, _l in ALL_STATUSES]:
            return self._redirect("{0}?error=Unknown+status".format(self._self_url()))
        from senaite.pfas.lot_status import status_change_problem
        from senaite.pfas.browser.perms import MANAGER_ROLES, has_role_at_portal
        why = status_change_problem(rec.get("status") or STATUS_ACTIVE, new_status,
                                    has_role_at_portal(self.context, MANAGER_ROLES))
        if why:
            from six.moves.urllib.parse import quote_plus
            return self._redirect("{0}?error={1}".format(self._self_url(), quote_plus(why.encode("utf-8"))))
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
        portal = self._portal()
        if not _is_production_mode(portal) or _get_production_since(portal) is None:
            return json.dumps({"ok": False, "error": u"Test lots are removed only once production has begun."})
        count, kept = _purge_test_reagents(portal)
        return json.dumps({"ok": True, "purged": count, "kept": kept})

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
            filename = os.path.basename(getattr(upload, "filename", "") or "coa.pdf")
        except Exception as exc:
            return self._redirect("{0}?error=Upload+failed%3A+{1}".format(
                self._self_url(), str(exc).replace(" ", "+")))
        content_type = content_type_for(filename)
        if content_type is None:
            return self._redirect("{0}?error=A+certificate+is+a+PDF+or+an+image+(PDF,+PNG,+JPG)".format(
                self._self_url()))

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
        fn = os.path.basename(meta.get("filename") or "coa.pdf")
        # the type the stored file's name says, never the one the browser sent
        ct = content_type_for(path) or content_type_for(fn) or "application/octet-stream"
        self.request.response.setHeader("Content-Type", ct)
        self.request.response.setHeader("X-Content-Type-Options", "nosniff")
        self.request.response.setHeader(
            "Content-Disposition",
            '{0}; filename="{1}"'.format("inline" if ct in CONTENT_TYPES.values() else "attachment",
                                         fn.replace('"', ""))
        )
        with open(path, "rb") as fh:
            return fh.read()


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
        """The core Suppliers (and "In-house"): what a label is matched
        against and what the form offers (core_lists.py)."""
        from senaite.pfas.browser.core_lists import IN_HOUSE, supplier_titles
        self.request.response.setHeader("Content-Type", "application/json")
        return json.dumps({"suppliers": supplier_titles() + [IN_HOUSE]})

    def core_suppliers(self):
        from senaite.pfas.browser.core_lists import IN_HOUSE, supplier_titles
        return supplier_titles() + [IN_HOUSE]

    def core_storage(self):
        from senaite.pfas.browser.core_lists import storage_titles
        return storage_titles()

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


class PFASMaterialsView(PFASReagentsView):
    """Materials & Containers: the reagent inventory over the lots whose
    category has no expiry (tubes, tips, homogenisers). The same lot
    records, so traceability and the stage pickers find them as before;
    the form asks no expiry question."""

    template = ViewPageTemplateFile("templates/reagents.pt")
    materials = True
    page_title = u"Materials & Containers"
