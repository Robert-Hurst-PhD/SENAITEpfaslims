# -*- coding: utf-8 -*-
"""What a core analysis shows: the method x matrix reporting unit and the
decimals the lab's rounding leaves (one owner per fact).

Core formats a result with the analysis's own Unit and Precision. The method
profile owns both, so they are set on the analysis inside SENAITE whenever
it changes -- the worker's result, a
result typed on Manage Results, a submission. The stored result is not
changed. (The worker cannot send them: senaite.jsonapi refuses Precision,
and the refusal sinks the whole update.)

Core expresses decimals, not significant figures, so for a value of 1000 or
more Precision alone would show more digits than the certificate. Core's
analysis listings (sample view, worksheet) therefore show the result as the
certificate states it, rounded by the lab's rule (PFASResultListingAdapter).

    apply(analysis)               set Unit / Precision; True when changed
    on_analysis_changed(...)      IObjectModifiedEvent / IAfterTransitionEvent
Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import logging

logger = logging.getLogger("senaite.pfas.analysis_display")


def precision_for(result, sig_figs, rule):
    """Decimals `result` keeps rounded to `sig_figs` by `rule` ("40.3" -> 1),
    or None for a result that is not a number."""
    from senaite.pfas import rounding
    text = rounding.round_sig(result, sig_figs, rule)
    if text is None:
        return None
    return len(text.split(".", 1)[1]) if "." in text else 0


def _profile_for(analysis):
    from senaite.pfas.method_bridge import profile_id_for_method
    from senaite.pfas.method_profile_store import get_profile
    method = analysis.getMethod()
    mid = profile_id_for_method(method) if method is not None else u""
    if not mid:
        batch = analysis.getRequest().getBatch()
        if batch is not None:
            from senaite.pfas import batch_method
            mid = batch_method.resolve(batch)[0]
    if not mid:
        return {}
    from bika.lims import api
    return get_profile(api.get_portal(), mid)


def _is_analyte(analysis):
    svc = analysis.getAnalysisService()
    field = svc.getField("pfas_role") if svc is not None else None
    return bool(field is not None and field.get(svc) == u"analyte")


def apply(analysis):
    """Set the analysis's Unit and Precision from its method profile."""
    if not _is_analyte(analysis):
        return False
    from senaite.pfas import report_format, rounding
    from senaite.pfas.report_limits import canonical_matrix
    profile = _profile_for(analysis)
    if not profile:
        return False
    matrix = canonical_matrix(profile, analysis.getRequest().getSampleTypeTitle())
    unit = (profile.get("unit_map") or {}).get(matrix) or u""
    fmt = report_format.resolve(profile, matrix)
    precision = precision_for(analysis.getResult(), int(fmt.get("coa_sig_figs") or 3),
                              fmt.get("coa_rounding") or rounding.DEFAULT_RULE)
    before = (analysis.getUnit() or u"", analysis.getPrecision())
    if unit:
        analysis.getField("Unit").set(analysis, unit)
    if precision is not None:
        analysis.getField("Precision").set(analysis, precision)
    changed = (analysis.getUnit() or u"", analysis.getPrecision()) != before
    if changed:
        analysis.reindexObject()
    return changed


def on_analysis_changed(analysis, event):
    try:
        apply(analysis)
    except Exception:                                       # noqa: BLE001
        logger.warning("unit / precision not set on %s", analysis, exc_info=True)


class PFASApplyDisplayView(object):
    """POST {"analysis_uids": [...]}: set Unit / Precision on the analyses the
    worker just wrote. senaite.jsonapi's update fires no modified event, so
    the worker asks for this once after its pushes; each analysis needs the
    right to edit its result."""

    EDIT_RESULT = "senaite.core: Field: Edit Analysis Result"

    def __init__(self, context, request):
        self.context, self.request = context, request

    def __call__(self):
        import json
        from AccessControl import getSecurityManager
        from bika.lims import api
        resp = self.request.response
        resp.setHeader("Content-Type", "application/json")
        if self.request.method != "POST":
            resp.setStatus(405)
            return json.dumps({"ok": False, "error": u"POST only"})
        try:
            body = json.loads(self.request.get("BODY") or u"{}")
        except (TypeError, ValueError):
            resp.setStatus(400)
            return json.dumps({"ok": False, "error": u"not JSON"})
        done = refused = 0
        sm = getSecurityManager()
        allowed = []
        for uid in body.get("analysis_uids") or []:
            an = api.get_object_by_uid(uid, default=None)
            if an is None or not sm.checkPermission(self.EDIT_RESULT, an):
                refused += 1
                continue
            allowed.append(an)
        from senaite.pfas.browser.perms import disable_csrf
        disable_csrf(self.request)
        for an in allowed:
            if apply(an):
                done += 1
        return json.dumps({"ok": True, "changed": done, "refused": refused})


class PFASResultListingAdapter(object):
    """senaite.app.listing subscriber on core's analyses listings: a PFAS
    analyte's shown result is the certificate's -- rounded to the method x
    matrix significant figures by the lab's rule -- for every magnitude
    (1234.5 -> "1230" at 3 figures, which Precision cannot express). The
    stored result and the edit box are unchanged. Its Method is read-only:
    the batch owns it."""

    priority_order = 1100

    def __init__(self, listing, context):
        self.listing, self.context = listing, context
        self._by_sample = {}

    def before_render(self):
        pass

    def _format(self, an):
        """(sig figs, rule) for the analysis's sample, cached per sample."""
        sample = an.getRequest()
        key = sample.UID()
        if key not in self._by_sample:
            from senaite.pfas import report_format, rounding
            from senaite.pfas.report_limits import canonical_matrix
            profile = _profile_for(an)
            if not profile:
                self._by_sample[key] = None
            else:
                fmt = report_format.resolve(profile, canonical_matrix(profile, sample.getSampleTypeTitle()))
                self._by_sample[key] = (int(fmt.get("coa_sig_figs") or 3),
                                        fmt.get("coa_rounding") or rounding.DEFAULT_RULE)
        return self._by_sample[key]

    def folder_item(self, obj, item, index):
        if not item:
            return item
        try:
            from bika.lims import api
            from senaite.pfas import rounding
            an = api.get_object(obj)
            if not _is_analyte(an):
                return item
            # The method is the batch's (batch_method.resolve reads the
            # analyses first), so it is shown, not chosen per analysis: the
            # shared PFAS services allow every method, and another one picked
            # on a worksheet row would move the batch's method.
            if "Method" in (item.get("allow_edit") or []):
                item["allow_edit"] = [k for k in item["allow_edit"] if k != "Method"]
                # drawn as core draws a method it does not offer to change
                method = an.getMethod()
                if method is not None:
                    from bika.lims.utils import get_link_for
                    item["Method"] = api.get_title(method)
                    item.setdefault("replace", {})["Method"] = get_link_for(method, tabindex="-1")
            if not item.get("formatted_result"):
                return item
            fmt = self._format(an)
            if fmt is None:
                return item
            text = rounding.round_sig(an.getResult(), fmt[0], fmt[1])
            if text is not None:
                item["formatted_result"] = text
        except Exception:                                   # noqa: BLE001
            logger.warning("listing result not rounded", exc_info=True)
        return item


class _AlwaysShown(dict):
    """A column whose default visibility stays on: core's analyses listing
    turns its Unit column off after the rows are built (when no unit can be
    chosen), which a subscriber cannot follow."""

    def __setitem__(self, key, value):
        dict.__setitem__(self, key, True if key == "toggle" else value)


SAMPLE_HIDDEN_COLUMNS = ("SubmittedBy", "Attachments")


class SampleAnalysesColumnsAdapter(object):
    """senaite.app.listing subscriber on a sample's analyses: the unit in its
    own column after Result instead of appended to the result, no
    Submitter or Attachments column, and read-only rows without selection
    for anyone but a manager."""

    priority_order = 1110

    def __init__(self, listing, context):
        self.listing, self.context = listing, context

    def _on_sample(self):
        try:
            from bika.lims.interfaces import IAnalysisRequest
            return IAnalysisRequest.providedBy(self.context)
        except ImportError:
            return False

    def _is_manager(self):
        from senaite.pfas.browser.perms import MANAGER_ROLES, _has_any_role
        return _has_any_role(self.context, MANAGER_ROLES)

    def before_render(self):
        if not self._on_sample():
            return
        # results are entered and reviewed on the worksheet and Data Review:
        # on the sample, the selection and its action buttons are a manager's
        # (retract, reject), the rows read-only for everyone else
        if not self._is_manager():
            self.listing.show_select_column = False
        cols = self.listing.columns
        if "Unit" in cols and not isinstance(cols["Unit"], _AlwaysShown):
            cols["Unit"] = _AlwaysShown(cols["Unit"])
            cols["Unit"]["toggle"] = True
        for rs in self.listing.review_states or []:
            if rs.get("columns"):
                rs["columns"] = [c for c in rs["columns"] if c not in SAMPLE_HIDDEN_COLUMNS]

    def folder_item(self, obj, item, index):
        if not item or not self._on_sample():
            return item
        if not self._is_manager():
            item["allow_edit"] = []
        unit = item.get("Unit")
        after = (item.get("after") or {}).get("Result") or u""
        if unit:
            shown = self.listing.render_unit(unit)
            if after.startswith(shown):
                item["after"]["Result"] = after[len(shown):]
        return item
