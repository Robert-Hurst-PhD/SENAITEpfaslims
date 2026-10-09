# -*- coding: utf-8 -*-
"""A blank-matrix lot's assigned levels (@@pfas-assigned-levels?uid=<lot>; matrix_blank.py). Python 2.7.

The levels annotate the reagent lot (one ZODB object owns them), appended: the newest is in force and the earlier ones stay as the
record. From the reference-material certificate, or previously quantified
by the lab -- then the runs they came from are named, and "Compute" fills
the form with the mean of those runs' matrix blanks. Entering levels is a
configuration act (manager tier); reading them is open to staff.
"""
from __future__ import absolute_import, unicode_literals

import json
import logging
from datetime import datetime

from zope.annotation.interfaces import IAnnotations

from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from senaite.pfas import matrix_blank as mxb
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import TIER_CONFIG, GateMixin, deny_gated_action

logger = logging.getLogger("senaite.pfas.browser.assigned_levels")

GATES = {"save": TIER_CONFIG}
EXTRA_ROWS = 5


def lot_object(portal, uid):
    try:
        return portal.get("pfas_reagents").get(uid) if uid else None
    except Exception:                                       # noqa: BLE001
        return None


def history(obj):
    """Every record on the lot, oldest first."""
    if obj is None:
        return []
    try:
        return json.loads(IAnnotations(obj).get(mxb.LEVELS_KEY) or u"[]")
    except (TypeError, ValueError):
        return []


def lot_record(portal, uid):
    """The record in force on a lot, or None."""
    return mxb.current(history(lot_object(portal, uid)))


def lot_label(obj):
    if obj is None:
        return u""
    return u"%s %s" % (obj.Title() or u"", getattr(obj, "lot_number", u"") or u"")


class PFASAssignedLevelsView(BrowserView, GateMixin):

    template = ViewPageTemplateFile("templates/assigned_levels.pt")

    def __call__(self):
        flatten_form(self.request)
        f = self.request.form
        self.problems, self.saved, self.computed, self.computed_unit = [], False, {}, u""
        if self.request.get("REQUEST_METHOD") == "POST":
            denied = deny_gated_action(self.context, self.request, f.get("action") or u"", GATES)
            if denied is not None:
                return denied
            try:
                from plone.protect import CheckAuthenticator
                CheckAuthenticator(self.request)
            except ImportError:
                pass
            if f.get("action") == "save":
                self._save()
            elif f.get("action") == "compute":
                self.computed = self._compute()
        return self.template()

    def portal(self):
        return getToolByName(self.context, "portal_url").getPortalObject()

    def portal_url(self):
        return self.portal().absolute_url()

    def uid(self):
        return (self.request.form.get("uid") or u"").strip()

    def lot(self):
        return lot_object(self.portal(), self.uid())

    def label(self):
        return lot_label(self.lot())

    def records(self):
        return list(reversed(history(self.lot())))

    def current(self):
        return mxb.current(history(self.lot()))

    def method(self):
        """The method whose analytes are listed (rule 2): the one
        asked for, else the one with the newest matrix blank, else the
        newest blank's."""
        asked = (self.request.form.get("method") or u"").strip()
        if asked:
            return asked
        runs = self.mxb_runs() or self.blank_runs()
        return runs[0]["method"] if runs else u""

    def blank_runs(self):
        if not hasattr(self, "_blank_runs"):
            from senaite.pfas.browser.blank_history import blank_data
            self._blank_runs = blank_data()
        return self._blank_runs

    def methods(self):
        return sorted(set(r["method"] for r in self.blank_runs() if r["method"]))

    def own_blanks(self):
        """The matrix blanks made from THIS lot (their member names it):
        never another material that shared a run."""
        if not hasattr(self, "_own"):
            from senaite.pfas.browser.blank_history import mxb_member
            cache, uid = {}, self.uid()
            self._own = [r for r in self.blank_runs() if r["qc_type"] == "MxB" and uid
                         and (mxb_member(r, cache) or {}).get("lot") == uid]
        return self._own

    def mxb_runs(self):
        """The runs holding a matrix blank of this lot, newest first: what
        levels can be quantified from (of the listed method, once chosen)."""
        seen, out = set(), []
        asked = (self.request.form.get("method") or u"").strip()
        for r in self.own_blanks():
            if asked and r["method"] != asked:
                continue
            if r["batch_id"] not in seen:
                seen.add(r["batch_id"])
                out.append(r)
        return out

    def _quantified(self, batch_ids):
        """quantified_from over this lot's matrix blanks in those runs."""
        want = set(batch_ids or [])
        keys = [r["key"] for r in self.own_blanks() if r["batch_id"] in want]
        return mxb.quantified_from(self.blank_runs(), keys)

    def analytes(self):
        """The names results are stored under (so a level meets its measured
        value): the method's blanks, and whatever the lot already holds."""
        names = set()
        method = self.method()
        for r in self.blank_runs():
            if r["method"] == method:
                names.update(a for a in r["values"] if a)
        cur = self.current() or {}
        names.update((cur.get("levels") or {}).keys())
        names.update(self.computed.keys())
        return sorted(names)

    def value_for(self, analyte):
        f = self.request.form
        key = u"level.%s" % analyte
        if key in f and not self.computed:
            return f.get(key)
        if analyte in self.computed:
            return u"%.4g" % self.computed[analyte]
        v = ((self.current() or {}).get("levels") or {}).get(analyte)
        return u"" if v is None else u"%g" % v

    def form_value(self, key, default=u""):
        if key == "unit" and self.computed_unit:
            return self.computed_unit
        cur = self.current() or {}
        return self.request.form.get(key, cur.get(key, default)) or default

    def extra_rows(self):
        return range(EXTRA_ROWS)

    def sources(self):
        return mxb.SOURCES

    def chosen_runs(self):
        f = self.request.form
        picked = [k[4:] for k in f if k.startswith(u"run.") and f.get(k)]
        if picked or self.request.get("REQUEST_METHOD") == "POST":
            return picked
        return list((self.current() or {}).get("runs") or [])

    def _compute(self):
        means, _counts, units = self._quantified(self.chosen_runs())
        if not means:
            self.problems = [u"Those runs have no matrix blank of this lot."]
            return {}
        if len(units) != 1:
            self.problems = [u"Those runs reported in different units (%s)." % u", ".join(sorted(units))]
            return {}
        self.computed_unit = list(units)[0]
        return means

    def _pairs(self):
        f = self.request.form
        pairs = [(k[6:], f.get(k)) for k in f if k.startswith(u"level.")]
        for i in self.extra_rows():
            pairs.append((f.get(u"new_name.%d" % i), f.get(u"new_level.%d" % i)))
        return pairs

    def _save(self):
        obj = self.lot()
        if obj is None:
            self.problems = [u"No such lot."]
            return
        levels, problems = mxb.parse_levels(self._pairs())
        known = set(r["batch_id"] for r in self.own_blanks())
        runs = self.chosen_runs()
        problems += [u"%s has no matrix blank of this lot." % r for r in runs if r not in known]
        f = self.request.form
        if f.get("source") == "quantified" and runs:
            _means, _n, units = self._quantified(runs)
            if len(units) > 1:
                problems.append(u"Those runs reported in different units (%s)." % u", ".join(sorted(units)))
            elif units and not mxb.same_unit(list(units)[0], f.get("unit") or u""):
                problems.append(u"Those runs reported in %s." % list(units)[0])
        rec, more = mxb.make_record(f.get("source") or u"", f.get("unit") or u"", levels, runs,
                                    f.get("note") or u"", self._user(),
                                    datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"))
        problems += more
        if problems:
            self.problems = problems
            return
        ann = IAnnotations(obj)
        ann[mxb.LEVELS_KEY] = json.dumps(history(obj) + [rec])
        obj.reindexObject()
        self.saved = True

    def _user(self):
        try:
            from plone import api as papi
            return papi.user.get_current().getId() or u""
        except Exception:                                   # noqa: BLE001
            return u""
