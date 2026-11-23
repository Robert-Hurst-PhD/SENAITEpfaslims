# -*- coding: utf-8 -*-
"""@@pfas-lot-extensions: asking QA to extend a lot's expiry, and QA's
queue (lot_extension.py).

    ?lot=<uid>            the request form for one lot (reagent or prepared
                          standard), opened over the queue
    action=request        anyone who may record work asks: new date, reason,
                          evidence
    action=approve        a QA approver signs (sign dialog); the lots made
                          from it that are ticked are extended in the same
                          signature, each capped at the parent's new date
    action=refuse         QA refuses, with a reason

The entries are kept on each lot (lot_extension.KEY). The store helpers
here are the one place that reads and writes them:

    lot_of(portal, uid)                  -> (object, kind) or (None, "")
    load(obj) / store(obj, items)
    lot_facts(portal, obj, kind)         -> the lot as the form and the
                                            decision need it
    children_of(portal, obj)             -> the prepared lots made from it
    all_entries(portal)                  -> every entry on every lot
    signed_records(portal)               -> {entry id: its signature cache}
    record(portal, entry_id)             -> the signing entry, for the
                                            Signatures page
    withdraw_signed(portal, entry_id, by, at, reason, seq, cache)
                                         -> the entry and its children
                                            withdrawn (the signature was)

Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import json
import logging
from datetime import datetime

from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.pfas import lot_extension as lx
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.view_helpers import ViewHelpers

logger = logging.getLogger("senaite.pfas.browser.lot_extensions")

REAGENT, PREPARED = u"reagent", u"prepared_standard"
_FOLDERS = (("pfas_reagents", REAGENT), ("pfas_prepared_standards", PREPARED))
_GONE = (u"exhausted", u"archived")


# ── the store ────────────────────────────────────────────────────────────────

def lot_of(portal, uid):
    uid = (uid or u"").strip()
    if not uid:
        return None, u""
    for folder_id, kind in _FOLDERS:
        folder = portal.get(folder_id)
        if folder is not None and uid in folder.objectIds():
            return folder[uid], kind
    return None, u""


def _ann(obj):
    from zope.annotation.interfaces import IAnnotations
    return IAnnotations(obj)


def load(obj):
    return lx.entries(_ann(obj).get(lx.KEY))


def store(obj, items):
    # a write that fails refuses the step: an approval not kept on the lot
    # would leave its signature with nothing to hold it
    _ann(obj)[lx.KEY] = json.dumps(items)


def _rec(obj, kind):
    if kind == REAGENT:
        from senaite.pfas.browser.reagents import _obj_to_dict
        return _obj_to_dict(obj)
    from senaite.pfas.browser.prepared_standards import _obj_to_dict
    return _obj_to_dict(obj)


def lot_facts(portal, obj, kind):
    """{"kind", "uid", "lot_number", "name", "recorded" (its own date before
    any extension), "in_force" (now), "cap" (a prepared lot: the earliest
    date in force of its parents), "status", "items" (its entries)}."""
    rec = _rec(obj, kind)
    if kind == REAGENT:
        from senaite.pfas.browser.reagents import _base_expiry, _effective_expiry, get_expiry_defaults
        defaults = get_expiry_defaults(portal)
        recorded, in_force, cap = _base_expiry(rec, defaults), _effective_expiry(rec, defaults), u""
        name = rec.get("name") or u""
    else:
        from senaite.pfas.browser.prepared_standards import effective_expiry_info
        recorded = (rec.get("expiry_date") or u"")[:10]
        in_force = effective_expiry_info(portal, rec)["date"] or u""
        cap = effective_expiry_info(portal, {"parent_reagents": rec.get("parent_reagents") or []})["date"] or u""
        name = rec.get("title") or u""
    return {"kind": kind, "uid": obj.getId(), "lot_number": rec.get("lot_number") or u"", "name": name,
            "recorded": recorded, "in_force": in_force, "cap": cap, "status": rec.get("status") or u"",
            "no_expiry": bool(rec.get("no_expiry")),
            "items": rec.get("extensions") or []}


def _made_from(rec, uid, lot_number):
    for p in rec.get("parent_reagents") or []:
        if (p.get("uid") or u"").strip() == uid:
            return True
        if not (p.get("uid") or u"").strip() and lot_number and (p.get("lot") or u"").strip() == lot_number:
            return True
    return False


def children_of(portal, obj):
    """The prepared lots made directly from `obj` that are still in use,
    each as lot_facts with "other_cap": the earliest date in force of its
    other parents."""
    from senaite.pfas.browser.prepared_standards import _obj_to_dict, effective_expiry_info
    folder = portal.get("pfas_prepared_standards")
    if folder is None:
        return []
    uid, lot_number = obj.getId(), (getattr(obj, "lot_number", u"") or u"").strip()
    out = []
    for child in folder.objectValues():
        if getattr(child, "portal_type", "") != "PreparedStandard" or child.getId() == uid:
            continue
        rec = _obj_to_dict(child)
        if (rec.get("status") or u"") in _GONE or not _made_from(rec, uid, lot_number):
            continue
        facts = lot_facts(portal, child, PREPARED)
        others = [p for p in rec.get("parent_reagents") or []
                  if not ((p.get("uid") or u"").strip() == uid
                          or (lot_number and (p.get("lot") or u"").strip() == lot_number))]
        facts["other_cap"] = effective_expiry_info(portal, {"parent_reagents": others})["date"] or u"" \
            if others else u""
        out.append(facts)
    out.sort(key=lambda f: (f["lot_number"], f["uid"]))
    return out


def all_entries(portal):
    """Every extension entry on every lot, each with "lot_uid" and
    "lot_kind" as stored."""
    out = []
    for folder_id, _kind in _FOLDERS:
        folder = portal.get(folder_id)
        if folder is None:
            continue
        for obj in folder.objectValues():
            raw = _ann(obj).get(lx.KEY)
            if raw:
                out.extend(lx.entries(raw))
    return out


def signed_records(portal):
    """{entry id: its signature cache} for every entry signed for itself:
    a child extended with its parent is held by the parent's entry."""
    return dict((e["id"], e.get("signatures")) for e in all_entries(portal)
                if e.get("id") and not e.get("with") and e.get("signatures"))


def record(portal, entry_id):
    """(the signing entry with this id, its lot object), or (None, None)."""
    obj, _kind = lot_of(portal, lx.lot_uid_of(entry_id))
    if obj is None:
        return None, None
    return lx.find(load(obj), entry_id), obj


def withdraw_signed(portal, entry_id, by, at, reason, seq, cache_rows=()):
    """The signature on `entry_id` was withdrawn: the entry and every child
    entry its signature extended are withdrawn, so each lot returns to its
    previous date in force. The withdrawal row joins the entry's display
    cache. Returns the lot numbers changed: an entry already withdrawn is
    kept as it is, so a retried withdrawal changes nothing twice."""
    from senaite.pfas.esig import signing
    entry, obj = record(portal, entry_id)
    if entry is None:
        return []
    day = _lab_day(at)
    done = []
    if entry.get("state") != lx.WITHDRAWN:
        gone = lx.withdrawn(entry, by, at, reason, seq, day)
        gone["signatures"] = signing.merge_cache(entry.get("signatures"), cache_rows)
        store(obj, lx.put(load(obj), gone))
        done.append(entry.get("lot_number") or u"")
    for c in entry.get("children") or []:
        cobj, _k = lot_of(portal, c.get("lot_uid"))
        if cobj is None:
            continue
        items = load(cobj)
        mine = lx.find(items, c.get("id"))
        if mine is not None and mine.get("state") != lx.WITHDRAWN:
            store(cobj, lx.put(items, lx.withdrawn(mine, by, at, reason, seq, day)))
            done.append(c.get("lot_number") or u"")
    return done


def _lab_day(stamp):
    """The laboratory day of a UTC stamp ("YYYY-MM-DDTHH:MM:SSZ"); its own
    date part when the clock cannot be read."""
    try:
        from senaite.pfas import lab_time
        day = lab_time.lab_date(stamp)
        if day is not None:
            return day.isoformat()
    except Exception:                                       # noqa: BLE001
        logger.warning("laboratory day of %s not read", stamp, exc_info=True)
    return (stamp or u"")[:10]


def _restore_status(obj, kind):
    """A reagent saved while out of date carries the status "expired": an
    approved extension makes it fit for use again."""
    if kind == REAGENT and (getattr(obj, "status", u"") or u"") == u"expired":
        obj.status = u"active"
        try:
            obj.reindexObject()
        except Exception:                                   # noqa: BLE001
            pass


# ── the page ─────────────────────────────────────────────────────────────────

class PFASLotExtensionsView(ViewHelpers, BrowserView):

    template = ViewPageTemplateFile("templates/lot_extensions.pt")

    def __call__(self):
        flatten_form(self.request)
        if self.request.method == "POST":
            # PFAS forms carry no token; each step checks its own right
            from senaite.pfas.browser.perms import disable_csrf
            disable_csrf(self.request)
            action = self.request.form.get("action") or u""
            if action == "request":
                return self._request()
            if action == "approve":
                return self._approve()
            if action == "refuse":
                return self._refuse()
        return self.template()

    # ── helpers ──────────────────────────────────────────────────────────

    def _portal(self):
        from bika.lims import api
        return api.get_portal()

    def page_url(self):
        return u"%s/@@pfas-lot-extensions" % self.portal_url()

    def ok_msg(self):
        return self.request.get("ok", "")

    def error_msg(self):
        return self.request.get("error", "")

    def _back(self, ok, text, lot=u""):
        from six.moves.urllib.parse import urlencode
        q = {"ok" if ok else "error": text.encode("utf-8")}
        if lot and not ok:
            q["lot"] = lot.encode("utf-8")
        self.request.response.redirect("%s?%s" % (self.page_url(), urlencode(q)))
        return ""

    def _who(self):
        from senaite.pfas.browser.perms import signed_in_name
        from senaite.pfas.esig import signing
        return signing.current_userid(self.request), signed_in_name(self.context)

    def _now(self):
        """Now in UTC, stored as "YYYY-MM-DDTHH:MM:SSZ"."""
        return datetime.utcnow().replace(microsecond=0).isoformat() + u"Z"

    def may_enter(self):
        from senaite.pfas.browser.staff import may_enter
        return may_enter()

    def is_qa(self):
        """The signed-in person holds the QA approver sign right (or is the
        Laboratory Director, who holds every right)."""
        from senaite.pfas.browser import staff
        from senaite.pfas.esig import signing
        userid = signing.current_userid(self.request)
        if not userid:
            return False
        info = staff.staff_info(userid) or {}
        return signing.RIGHT_FOR[lx.MEANING] in (info.get("sign_as") or []) or \
            (staff.director_userid() or u"") == userid

    # ── what the page shows ──────────────────────────────────────────────

    def lot(self):
        """The lot the request form is for (?lot=<uid>), or None."""
        if hasattr(self, "_lot"):
            return self._lot
        self._lot = None
        obj, kind = lot_of(self._portal(), self.request.form.get("lot"))
        if obj is not None:
            self._lot = lot_facts(self._portal(), obj, kind)
            self._lot["waiting"] = lx.waiting(self._lot["items"])
        return self._lot

    def rows(self):
        """Every entry, waiting ones first, then newest first."""
        if hasattr(self, "_rows"):
            return self._rows
        items = all_entries(self._portal())
        items.sort(key=lambda e: (e.get("state") != lx.REQUESTED,
                                  [-ord(c) for c in (e.get("requested_at") or u"")]))
        self._rows = [dict(e, state_label=lx.label(e.get("state"))) for e in items]
        return self._rows

    def waiting(self):
        return [r for r in self.rows() if r.get("state") == lx.REQUESTED and not r.get("with")]

    def decided(self):
        return [r for r in self.rows() if r.get("state") != lx.REQUESTED][:100]

    def decision(self, entry):
        """The approve form's data for a waiting entry: its children offered
        as tick boxes, each with the date it would take, and the sign
        dialog's."""
        from senaite.pfas.esig import signing
        portal = self._portal()
        obj, _kind = lot_of(portal, entry.get("lot_uid"))
        kids = []
        if obj is not None:
            for c in children_of(portal, obj):
                cap = min([d for d in (entry.get("new_expiry"), c.get("other_cap")) if d])
                kids.append(dict(c, offer=cap, open=bool(lx.waiting(c["items"])),
                                 later=bool(cap and c["in_force"] and cap > c["in_force"])))
        who = self._who()[1]
        return {"children": kids,
                "esig": {"record": entry["id"], "revision": lx.REVISION,
                         "hash_prefix": u"Set when signed",
                         "content_text": u"Extend lot %s from %s to %s, and each lot ticked" % (
                             entry.get("lot_number"), entry.get("from_expiry"), entry.get("new_expiry")),
                         "meaning_label": signing.meaning_label(lx.MEANING), "signer_name": who,
                         "action": u"approve-%s" % entry["id"], "form_id": u"approve-form-%s" % entry["id"]}}

    def label_url(self, entry):
        """Print label for a lot whose extension is in force: its label now
        carries the new date, marked extended."""
        from senaite.pfas import lot_expiry
        from senaite.pfas.browser.label_print import label_href
        obj, kind = lot_of(self._portal(), entry.get("lot_uid"))
        if obj is None or entry.get("state") != lx.APPROVED:
            return u""
        facts, rec = lot_facts(self._portal(), obj, kind), _rec(obj, kind)
        return label_href(self.portal_url(), back=self.page_url(), name=facts["name"],
                          lot=facts["lot_number"],
                          exp=lot_expiry.shown_expiry(facts["in_force"], facts["no_expiry"]),
                          storage=rec.get("storage_conditions") or rec.get("storage_location"),
                          **lx.label_values(facts["items"]))

    def lot_url(self, entry):
        if entry.get("lot_kind") == PREPARED:
            return u"%s/@@pfas-prep-standards?record=%s" % (self.portal_url(), entry.get("lot_uid"))
        return u"%s/@@pfas-reagents?q=%s" % (self.portal_url(), entry.get("lot_number") or u"")

    # ── the steps ────────────────────────────────────────────────────────

    def _request(self):
        from senaite.pfas.entry_rights import REFUSAL
        f = self.request.form
        uid = (f.get("lot") or u"").strip()
        if not self.may_enter():
            return self._back(False, REFUSAL, uid)
        portal = self._portal()
        obj, kind = lot_of(portal, uid)
        if obj is None:
            return self._back(False, u"Lot not found.")
        facts = lot_facts(portal, obj, kind)
        who, name = self._who()
        entry, problems = lx.request(facts["items"], facts, facts["recorded"], facts["in_force"],
                                     f.get("new_expiry"), f.get("reason"), f.get("evidence"),
                                     who, name, self._now(), cap=facts["cap"])
        if problems:
            return self._back(False, u" ".join(problems), uid)
        store(obj, facts["items"] + [entry])
        return self._back(True, u"Extension of lot %s sent to QA." % facts["lot_number"])

    def _refuse(self):
        f = self.request.form
        if not self.is_qa():
            return self._back(False, u"Only a QA approver may refuse an extension.")
        entry, obj = record(self._portal(), f.get("entry") or u"")
        if entry is None:
            return self._back(False, u"Extension not found.")
        who, name = self._who()
        try:
            done = lx.refuse(entry, who, name, self._now(), f.get("why"))
        except ValueError as exc:
            return self._back(False, u"%s" % exc)
        store(obj, lx.put(load(obj), done))
        return self._back(True, u"Extension of lot %s refused." % entry.get("lot_number"))

    def _approve(self):
        from senaite.pfas import lab_time
        from senaite.pfas.esig import ledger, signing
        f = self.request.form
        if f.get("sign") != "1":
            # an approval is recorded only through the sign dialog
            return self._back(False, u"Sign the approval to record it.")
        portal = self._portal()
        entry, obj = record(portal, f.get("entry") or u"")
        if entry is None:
            return self._back(False, u"Extension not found.")
        who, name = self._who()
        offered = dict((c["uid"], c) for c in self.decision(entry)["children"])
        children, child_items = [], {}
        # one field per child lot ticked (flatten_form keeps one value per name)
        for uid in sorted(offered):
            if not f.get("child.%s" % uid):
                continue
            c = offered[uid]
            child_items[uid] = c["items"]
            ce = lx.child_entry(entry, dict(c, new_expiry=(f.get("child_new.%s" % uid) or c["offer"])),
                                c["items"])
            ce["cap"] = c.get("other_cap") or u""
            children.append(ce)
        problems = lx.approve_problems(entry, who, children, child_items)
        if problems:
            return self._back(False, u" ".join(problems))
        record_hash = lx.record_hash(entry, children)
        try:
            row = signing.sign(portal, self.request, lx.KIND, entry["id"], lx.REVISION, record_hash,
                               lx.MEANING, note=(f.get("sign_note") or u"").strip())
        except (signing.SignatureRefused, ledger.LedgerError) as exc:
            return self._back(False, signing.reason(exc))
        sig = {"seq": row["seq"], "hash": row["hash"], "record_hash": record_hash}
        day = lab_time.today().isoformat()
        parent, kids = lx.approve(entry, who, name, self._now(), day, sig, children)
        parent["signatures"] = signing.merge_cache(entry.get("signatures"), signing.cache([row]))
        store(obj, lx.put(load(obj), parent))
        _restore_status(obj, entry.get("lot_kind"))
        for k in kids:
            cobj, ckind = lot_of(portal, k["lot_uid"])
            store(cobj, lx.put(load(cobj), k))
            _restore_status(cobj, ckind)
        lots = [entry.get("lot_number")] + [k.get("lot_number") for k in kids]
        return self._back(True, u"Extension approved: %s. Print the new label%s from Decided." % (
            u", ".join(lots), u"s" if len(lots) > 1 else u""))
