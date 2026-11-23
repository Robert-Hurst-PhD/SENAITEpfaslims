# -*- coding: utf-8 -*-
"""POST @@pfas-set-expected-rt: the analyst's route to a compound's
expected retention time, from the Raw Data card of a worksheet under review.

    injection, analyte   the card: its quantifier peak's found time (the
                         stored result row's) becomes the compound's
                         expected time on the method profile
    rt                   the time the expected-time line was dragged to, in
                         its place: read strictly and held to the times
                         every stored trace of the compound in that
                         injection covers (expected_rt.span)

A request that accepts application/json (the dragged line's) is answered
{"ok", "analyte", "old", "new"} or {"error"} with a refusing status, so the
analyst moves on to the next compound with no reload; the card menu's form
is answered by a redirect back to the card.

Allowed to whoever may edit the run's peaks (the analyst, or a manager)
while the worksheet's review is open; never through the method profile
editor, which stays the manager's. The time is written straight to the
stored profile (expected_rt.plan refuses what the method's Integration
check would refuse) and the change history records who, the worksheet, the
injection, how it was set and the time before and after. No new method
revision is owed: the expected times are outside the revision fingerprint.

Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import json
import logging

from senaite.pfas.browser.data_review import PFASDataReviewView
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import refuse

logger = logging.getLogger("senaite.pfas.browser.expected_rt")

DONE = u"expected_rt_set"
REFUSED = u"expected_rt_refused"


class PFASSetExpectedRTView(PFASDataReviewView):

    def __call__(self):
        flatten_form(self.request)
        if (self.request.get("REQUEST_METHOD") or "").upper() != "POST":
            self.request.response.setStatus(405)
            self.request.response.setHeader("Allow", "POST")
            return u"POST required"
        if not self.raw_can_edit():
            return refuse(self.request, json.dumps({"error": u"You may not edit this run's peaks."})
                          if self._wants_json() else "Forbidden")
        from senaite.pfas.browser.perms import disable_csrf
        disable_csrf(self.request)
        return self._set()

    def _wants_json(self):
        return "application/json" in (self.request.get_header("Accept") or "")

    def _answer(self, problem, back, status=409):
        """A refusal: in JSON for the dragged line, else back to the card."""
        if self._wants_json():
            self.request.response.setStatus(status)
            self.request.response.setHeader("Content-Type", "application/json; charset=utf-8")
            return json.dumps({"error": problem})
        return self._redirect_with_msg(REFUSED, "error", tab="raw", extra=back, detail=problem)

    def _set(self):
        from six.moves.urllib.parse import quote
        from senaite.pfas import config_history, expected_rt, raw_edit, raw_review
        from senaite.pfas.method_profile_sections import check_integration
        from senaite.pfas.method_profile_store import raw_profile, save_profile
        ws = self._get_worksheet()
        if ws is None:
            if self._wants_json():
                return self._answer(u"No worksheet.", u"", status=404)
            return self._redirect_with_msg("no_worksheet", "error")
        f = self.request.form
        inj, an = raw_edit.text(f, "injection"), raw_edit.text(f, "analyte")
        q = lambda s: quote(s.encode("utf-8"), safe="")                 # noqa: E731
        mode = f.get("mode") if f.get("mode") in self.RAW_MODES else u"injection"
        back = u"&mode=%s&injection=%s&analyte=%s&open=%s" % (mode, q(inj), q(an), q(inj + u"|" + an))
        mid = self.batch_method()
        traces = self._raw_traces(injection=inj, analytes=[an]) if inj and an else []
        card = raw_review.card(inj, an, traces, self._raw_rows(), [], self._raw_overrides()) if traces else None
        if not mid or card is None:
            return self._answer(u"%s / %s is not in this worksheet's raw run." % (inj, an), back, status=404)
        portal = self._portal()
        profile = raw_profile(portal, mid)
        dragged = f.get("rt") not in (None, u"", "")
        if dragged:
            # the line dragged to a time: no peak is read, so an edit waiting
            # for the run does not hold it back
            found = expected_rt.posted_time(f.get("rt"))
            if found is None:
                return self._answer(u"The dragged time is not a number of minutes.", back, status=400)
            pending = False
        else:
            found = card.get("rt") if not (card.get("quant") or {}).get("deleted") else None
            pending = (card.get("quant") or {}).get("edit") == u"pending"
        problem, change = expected_rt.plan(profile, an, found, check=check_integration, pending=pending,
                                           span=expected_rt.span(traces))
        if problem:
            return self._answer(problem, back)
        old, new = change
        reason = expected_rt.change_reason(ws.getId(), inj, an, old, new, dragged=dragged)
        config_history.track(portal, "method_profile", mid, lambda: raw_profile(portal, mid),
                             action=u"Set expected retention time", reason=reason)
        save_profile(portal, mid, expected_rt.applied(profile, an, new))
        from senaite.pfas import records
        records.log(ws, u"expected retention time set", reason=reason)
        logger.info("%s: expected retention time of %s %s -> %s from %s", mid, an, old, new, inj)
        if self._wants_json():
            self.request.response.setHeader("Content-Type", "application/json; charset=utf-8")
            return json.dumps({"ok": True, "analyte": an, "old": old, "new": new})
        return self._redirect_with_msg(DONE, "ok", tab="raw", extra=back)
