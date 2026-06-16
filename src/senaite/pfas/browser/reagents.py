# -*- coding: utf-8 -*-
"""
PFAS Reagent Inventory (@@pfas-reagents).

ISO 17025 / MLAB reagent tracking: catalog number, lot number, expiry,
storage location, and status for every chemical used in the lab.

Each catalog number may have many records (one per received lot).
Records are keyed by UUID in ZODB portal annotations.

Barcode scanning and OCR text recognition run entirely in the browser
(ZXing-js + Tesseract.js); no server-side scanner is needed.

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import logging
import re
import uuid
from datetime import date, datetime, timedelta

from persistent.mapping import PersistentMapping
from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from zope.annotation.interfaces import IAnnotations

logger = logging.getLogger("senaite.pfas.browser.reagents")

REAGENTS_KEY = u"senaite.pfas.reagents"

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

# Reagent categories (ISO 17025-friendly)
REAGENT_CATEGORIES = [
    "Mobile Phase / Solvent",
    "Extraction Reagent",
    "Standard / Reference Material",
    "Internal Standard",
    "Buffer",
    "Acid / Base",
    "Salt",
    "Other Reagent",
]

# Mobile phase name pattern for auto-expiry (7 days from open date)
_MOBILE_PHASE_RE = re.compile(
    r'methanol|meoh|acetonitrile|acn|water|h2o|mobile.?phase|mph|formic',
    re.IGNORECASE,
)

# ── Expiry helpers ────────────────────────────────────────────────────────────

def _auto_expiry_from_open(name, opened_date_str):
    """Calculate auto-expiry from open date.

    Mobile phases: 7 days.  All others: 1 year.
    Returns ISO date string or empty string if input is invalid.
    """
    if not opened_date_str:
        return ""
    try:
        opened = datetime.strptime(opened_date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return ""
    if _MOBILE_PHASE_RE.search(name or ""):
        exp = opened + timedelta(days=7)
    else:
        try:
            exp = date(opened.year + 1, opened.month, opened.day)
        except ValueError:
            exp = date(opened.year + 1, 3, 1)  # Feb 29 edge case
    return exp.strftime("%Y-%m-%d")


def _effective_expiry(rec):
    """Return the expiry date string in effect for a record."""
    return rec.get("expiry_date") or rec.get("manufacturer_expiry") or ""


def _is_expired(rec):
    exp = _effective_expiry(rec)
    if not exp:
        return False
    try:
        return datetime.strptime(exp, "%Y-%m-%d").date() < date.today()
    except (ValueError, TypeError):
        return False


# ── Store helpers ─────────────────────────────────────────────────────────────

def _get_store(portal):
    ann = IAnnotations(portal)
    if REAGENTS_KEY not in ann:
        ann[REAGENTS_KEY] = PersistentMapping()
    return ann[REAGENTS_KEY]


def _save_reagent(portal, data):
    """Upsert a reagent record.  Assigns a UUID if one is absent."""
    store = _get_store(portal)
    uid = data.get("uid") or uuid.uuid4().hex
    data["uid"] = uid
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    data.setdefault("created", now)
    data["updated"] = now
    # Auto-compute expiry when no manufacturer date is given and opened_date is set
    if not data.get("expiry_date") and data.get("opened_date"):
        data["expiry_date"] = _auto_expiry_from_open(
            data.get("name", ""), data["opened_date"]
        )
    # Auto-update status to expired
    if data.get("status") not in (STATUS_EXHAUSTED, STATUS_QUARANTINE):
        if _is_expired(data):
            data["status"] = STATUS_EXPIRED
    store[uid] = json.dumps(data)
    return uid


def _get_reagent(portal, uid):
    store = _get_store(portal)
    raw = store.get(uid)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def _delete_reagent(portal, uid):
    store = _get_store(portal)
    if uid in store:
        del store[uid]
        return True
    return False


def _list_reagents(portal, q="", status_filter="", category_filter=""):
    """Return filtered, sorted list of reagent dicts."""
    store = _get_store(portal)
    q_lower = (q or "").lower().strip()
    results = []
    for uid, raw in store.items():
        try:
            d = json.loads(raw)
        except (ValueError, TypeError):
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
        # Live expiry check
        if d.get("status") == STATUS_ACTIVE and _is_expired(d):
            d["status"] = STATUS_EXPIRED
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
        action = self.request.form.get("action", "")
        if action == "lookup_json":
            return self._handle_lookup_json()
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

    def reagents(self):
        return _list_reagents(
            self._portal(),
            q=self.q(),
            status_filter=self.status_filter(),
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
            rec["expiry_date"] = _auto_expiry_from_open(rec.get("name", ""), rec["opened_date"])
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
        if _delete_reagent(self._portal(), uid):
            return self._redirect("{0}?ok=Reagent+deleted".format(self._self_url()))
        return self._redirect("{0}?error=Not+found".format(self._self_url()))

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
