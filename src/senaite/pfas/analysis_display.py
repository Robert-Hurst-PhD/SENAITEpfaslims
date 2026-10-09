# -*- coding: utf-8 -*-
"""What a core analysis shows: the method x matrix reporting unit and the
decimals the lab's rounding leaves (one owner per fact).

Core formats a result with the analysis's own Unit and Precision, which every
PFAS service left blank / 3. The method profile owns both, so they are set on
the analysis inside SENAITE whenever it changes -- the worker's result, a
result typed on Manage Results, a submission -- and once for the analyses
written before (migrations/backfill_units_precision.py). The stored result is
not changed. (The worker cannot send them: senaite.jsonapi refuses Precision,
and the refusal sinks the whole update.)

Core expresses decimals, not significant figures, so for a value of 1000 or
more Precision alone would show more digits than the certificate. Core's
analysis listings (sample view, worksheet) therefore show the result as the
certificate states it, rounded by the lab's rule (PFASResultListingAdapter; 2026-10-05: core must follow the rounding rules).

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
    try:
        from senaite.pfas import rounding
    except ImportError:                                     # tests, outside Plone
        import rounding
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
    try:
        svc = analysis.getAnalysisService()
        field = svc.getField("pfas_role") if svc is not None else None
        return bool(field is not None and field.get(svc) == u"analyte")
    except Exception:                                       # noqa: BLE001
        return False


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
        try:
            from plone.protect.interfaces import IDisableCSRFProtection
            from zope.interface import alsoProvides
            alsoProvides(self.request, IDisableCSRFProtection)
        except ImportError:
            pass
        done = refused = 0
        sm = getSecurityManager()
        for uid in body.get("analysis_uids") or []:
            an = api.get_object_by_uid(uid, default=None)
            if an is None or not sm.checkPermission(self.EDIT_RESULT, an):
                refused += 1
                continue
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
            # The method is the batch's (the generated method x matrix
            # profile sets it; batch_method.resolve reads the analyses
            # first), so it is shown, not chosen per analysis: the shared
            # PFAS services allow all three methods, and picking another one
            # on a worksheet row moved the batch's method.
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
