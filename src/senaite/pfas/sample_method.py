# -*- coding: utf-8 -*-
"""Which method a sample was analysed by -- one answer for the certificate
and for the publish guard (DECISIONS 2026-10-02).

The method comes from the sample's reported analyses (hidden ones and those
retracted / rejected / cancelled / invalid are not reported). An analysis
normally gets it when it goes on a worksheet that has a method. Results can
reach publication without one: entered on the sample view without a
worksheet, a worksheet created without a method, services listing several
methods with no default, scripts. Then the method is NOT identified, and so
it is when the reported analyses carry DIFFERENT methods: the certificate
refuses that sample and publishing is blocked (guards.SampleMethodGuard).

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


def identify_from(analyses):
    """(method or None, problem text or u"").

    No analyses -> (None, u""): nothing to report, nothing to refuse.
    """
    if not analyses:
        return None, u""
    methods, missing = {}, 0
    for an in analyses:
        try:
            m = an.getMethod()
        except Exception:
            m = None
        if m is None:
            missing += 1
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


def identify(sample):
    return identify_from(reported_analyses(sample))
