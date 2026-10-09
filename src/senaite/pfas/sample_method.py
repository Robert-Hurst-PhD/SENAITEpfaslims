# -*- coding: utf-8 -*-
"""Which method a sample was analysed by -- one answer for the certificate
and for the publish guard.

The method comes from the sample's reported analyses (hidden ones and those
retracted / rejected / cancelled / invalid are not reported). An analysis
normally gets it when it goes on a worksheet that has a method. Results can
reach publication without one: entered on the sample view without a
worksheet, a worksheet created without a method, services listing several
methods with no default, scripts. Then the method is NOT identified, and so
it is when the reported analyses carry DIFFERENT methods: the certificate
refuses that sample and publishing is blocked (guards.SampleMethodGuard).

A project may ADD analytes to its method's panel (project specs): such a service is outside the method's panel by definition, so
its analysis carries no method. It is accepted -- and only it -- when its
keyword is an analyte the sample's batch's project adds for the method the
sample's other analyses carry; `added_for(method)` gives
those keywords.

`identify_from` is pure (takes the analyses); `identify` reads a sample.
Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

EXCLUDED_STATES = ("retracted", "rejected", "cancelled", "invalid")
REMEDY = (u"Put the analyses on a worksheet with the method, then verify again.")


def _state(obj):
    try:
        from bika.lims import api
        return api.get_review_status(obj)
    except Exception:                                    # tests
        return getattr(obj, "review_state", u"")


def reported_analyses(sample):
    found = []
    for an in sample.objectValues():
        if getattr(an, "portal_type", "") != "Analysis":
            continue
        try:
            if an.getHidden():
                continue
        except Exception:
            pass
        if _state(an) in EXCLUDED_STATES:
            continue
        found.append(an)
    return found


def identify_from(analyses, added_for=None):
    """(method or None, problem text or u"").

    No analyses -> (None, u""): nothing to report, nothing to refuse.
    `added_for(method)`: the keywords the sample's project adds to that
    method's panel; their method-less analyses are accepted.
    """
    if not analyses:
        return None, u""
    methods, missing, missing_kws = {}, 0, set()
    for an in analyses:
        try:
            m = an.getMethod()
        except Exception:
            m = None
        if m is None:
            missing += 1
            try:
                missing_kws.add(an.getKeyword())
            except Exception:
                missing_kws.add(None)
            continue
        try:
            key = m.UID()
        except Exception:
            key = id(m)
        methods.setdefault(key, m)
    if not methods:
        return None, (u"Method not identified: none of this sample's analyses has a method. "
                      + REMEDY)
    if len(methods) > 1:
        names = sorted(_name(m) for m in methods.values())
        return None, (u"Method not identified: this sample's analyses carry different "
                      u"methods (%s). " % u", ".join(names) + REMEDY)
    method = list(methods.values())[0]
    if missing and added_for is not None and missing_kws <= set(added_for(method) or ()):
        return method, u""                  # the project's added analytes
    if missing:
        return None, (u"Method not identified: %d of this sample's analyses have no method "
                      u"(the others: %s). " % (missing, _name(method)) + REMEDY)
    return method, u""


def _name(method):
    for attr in ("getMethodID", "Title"):
        try:
            v = getattr(method, attr)()
            if v:
                return u"%s" % v
        except Exception:
            pass
    return u"?"


def project_added(sample):
    """`added_for` for this sample: the analytes its batch's project adds to
    a method's panel for the sample's matrix (the effective profile's panel
    minus the method's own)."""
    def added_for(method):
        try:
            from bika.lims import api
            from senaite.pfas.method_profile_store import get_profile
            from senaite.pfas.project_specs import profile_for_batch
            from senaite.pfas.report_limits import canonical_matrix
            portal = api.get_portal()
            mid = method.getMethodID()
            bare = get_profile(portal, mid) or {}
            matrix = canonical_matrix(bare, sample.getSampleTypeTitle())
            eff = profile_for_batch(portal, sample.getBatch(), mid, matrix) or bare
            return (set(eff.get("master_analyte_set") or [])
                    - set(bare.get("master_analyte_set") or []))
        except Exception:                                   # noqa: BLE001
            return set()
    return added_for


def identify(sample):
    return identify_from(reported_analyses(sample), project_added(sample))
