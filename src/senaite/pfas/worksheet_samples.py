# -*- coding: utf-8 -*-
"""Adding samples to a worksheet: one method and one matrix per worksheet.

The worksheet's method is core's own worksheet Method field. Its matrix is
the one value this module stores on the worksheet (MATRIX_KEY), written by
the samples page alone and read through `stored_matrix`.

A sample's method, one rule for the samples page and the assign guard:
the method whose generated analysis profile the sample was registered with
(analysis_profiles), else the one method its analyses carry when they agree.
A sample that names none, or several, cannot be identified.

Pure helpers (no Plone):
    sample_method(profile_uids, by_profile, analysis_methods)  (id, reason)
    group_by_sample(entries)        analysis entries grouped by their sample
    sample_row(sample, analyses, method_id, reason, received)  a list row
    pick_rows(rows, method_id, matrix, canonical)  (tickable, apart)
    read_back(sample_id, wanted, added, keywords)  the "N of N added" line
    assign_allowed(ws_method, sample_method_id)
    stale_method(analysis_method_uid, ws_method_uid)

Portal readers:
    stored_matrix(ws) / store_matrix(ws, matrix)
    profile_methods(portal)         {profile uid: method id}
    sample_method_of(portal, sample, by_profile=None)
    unassigned(portal)              the received samples waiting for a worksheet
Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

MATRIX_KEY = "senaite.pfas.worksheet_matrix"

NOT_IDENTIFIED = u"Method not identified: none of its analyses has a method and it was not " \
                 u"registered with a method's analyses."
SEVERAL_PROFILES = u"Method not identified: it was registered with the analyses of several methods ({0})."
SEVERAL_METHODS = u"Method not identified: its analyses carry different methods ({0})."


# ── pure ────────────────────────────────────────────────────────────────────

def sample_method(profile_uids, by_profile, analysis_methods):
    """(method id, reason): the method of the profile(s) the sample was
    registered with when they name exactly one; else the one method its
    analyses carry (analyses without a method do not count). The reason
    says why no method could be identified, else it is u""."""
    from_profiles = sorted(set(by_profile.get(u) for u in profile_uids or () if by_profile.get(u)))
    if len(from_profiles) == 1:
        return from_profiles[0], u""
    if len(from_profiles) > 1:
        return u"", SEVERAL_PROFILES.format(u", ".join(from_profiles))
    found = sorted(set(m for m in analysis_methods or () if m))
    if len(found) == 1:
        return found[0], u""
    if found:
        return u"", SEVERAL_METHODS.format(u", ".join(found))
    return u"", NOT_IDENTIFIED


def group_by_sample(entries):
    """[{"sample": key, "uid", ...}] -> [(sample key, [entry, ...])] in the
    order each sample first appears."""
    order, groups = [], {}
    for e in entries or ():
        key = e.get("sample")
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(e)
    return [(k, groups[k]) for k in order]


def sample_row(sample, analyses, method_id, reason, received=u""):
    """One list row for a sample and its waiting analyses (catalog brains:
    UID, getKeyword), the project's added analytes counted with them;
    "analyses" [(uid, keyword)] is what its Add asks core for."""
    try:
        coc = sample.getField("CoCNumber").get(sample) or u""
    except Exception:                                       # noqa: BLE001
        coc = u""
    held = [(b.UID, b.getKeyword) for b in analyses or ()]
    return {"uid": sample.UID(), "id": sample.getId(), "url": sample.absolute_url(),
            "client_sid": sample.getClientSampleID() or u"", "coc": coc,
            "matrix": sample.getSampleTypeTitle() or u"", "received": received,
            "tests": len(held), "analyses": held, "method": method_id or u"", "reason": reason or u""}


def pick_rows(rows, method_id, matrix, canonical=None):
    """(tickable, apart) of the sample rows for a worksheet of `method_id`
    and `matrix`. A row: {"method", "reason", "matrix", ...}. A row of
    another method or of another matrix is left out; a row whose method is
    not identified is listed apart (it cannot be ticked) when its matrix is
    the worksheet's. `canonical(title)` names a matrix as the method does
    (its aliases); without it titles are compared as they are."""
    name = canonical or (lambda t: t or u"")
    want = name(matrix)
    tickable, apart = [], []
    for r in rows or ():
        if not want or name(r.get("matrix")) != want:
            continue
        if not r.get("method"):
            apart.append(r)
        elif r["method"] == method_id:
            tickable.append(r)
    key = lambda r: r.get("id") or u""
    return sorted(tickable, key=key), sorted(apart, key=key)


def read_back(sample_id, wanted, added, keywords=None):
    """The line a sample's Add says: "DW-0895: 25 of 25 added", naming what
    was not added. `wanted` the analysis uids asked for, `added` those now
    on the worksheet, `keywords` {uid: keyword} to name the leftovers."""
    wanted = list(wanted or ())
    got = set(added or ())
    left = [u for u in wanted if u not in got]
    line = u"%s: %d of %d added" % (sample_id, len(wanted) - len(left), len(wanted))
    if left:
        names = sorted(set((keywords or {}).get(u) or u for u in left))
        line += u"; not added: %s" % u", ".join(names)
    return line


def assign_allowed(ws_method, sample_method_id):
    """May an analysis go on a worksheet? Only when its sample's method is
    the worksheet's Method, whatever the analysis itself carries (a project's
    added analyte has no method). A sample whose method is not identified
    goes on no worksheet that has a Method, as the samples page never
    offers it. A worksheet without a Method takes anything: an older
    worksheet keeps working."""
    if not ws_method:
        return True
    return sample_method_id == ws_method


def stale_method(analysis_method_uid, ws_method_uid):
    """Must an added analysis's own method be cleared? Core gives an analysis
    the first method of the worksheet's instrument; the analysis takes the
    worksheet's method instead, so any other method it carries is cleared."""
    return bool(ws_method_uid) and bool(analysis_method_uid) and analysis_method_uid != ws_method_uid


# ── portal readers ──────────────────────────────────────────────────────────

def stored_matrix(ws):
    """The worksheet's matrix as its samples page stored it, or u""."""
    from zope.annotation.interfaces import IAnnotations
    try:
        return IAnnotations(ws).get(MATRIX_KEY) or u""
    except TypeError:
        return u""


def store_matrix(ws, matrix):
    from zope.annotation.interfaces import IAnnotations
    IAnnotations(ws)[MATRIX_KEY] = u"%s" % (matrix or u"")


def profile_methods(portal):
    """{generated analysis profile uid: method id} (analysis_profiles)."""
    from zope.annotation.interfaces import IAnnotations
    from senaite.pfas.analysis_profiles import KEY
    out = {}
    for method_id, mine in (IAnnotations(portal).get(KEY) or {}).items():
        for puid in (mine or {}).values():
            out[puid] = method_id
    return out


def _profile_uids(sample):
    raw = getattr(sample, "getRawProfiles", None)
    if raw is not None:
        return list(raw() or [])
    from bika.lims import api
    return [api.get_uid(p) for p in sample.getProfiles() or []]


def sample_method_of(portal, sample, by_profile=None):
    """(method id, reason) for a sample: sample_method on what it holds.
    Its analyses are woken only when its profiles name no method."""
    from senaite.pfas.method_bridge import profile_id_for_method
    by_profile = profile_methods(portal) if by_profile is None else by_profile
    uids = _profile_uids(sample)
    mid, reason = sample_method(uids, by_profile, ())
    if mid or any(by_profile.get(u) for u in uids):
        return mid, reason
    from senaite.pfas.sample_method import reported_analyses
    methods = []
    for an in reported_analyses(sample):
        m = an.getMethod()
        if m is not None:
            methods.append(profile_id_for_method(m))
    return sample_method((), {}, methods)


def unassigned(portal):
    """[(sample, [analysis brain, ...])]: the received samples whose routine
    analyses wait for a worksheet, from one query of the analysis catalog;
    only the samples are woken."""
    from bika.lims import api
    brains = api.get_tool("senaite_catalog_analysis")(portal_type="Analysis", review_state="unassigned")
    entries = [{"sample": str(b.getPath().rsplit(str("/"), 1)[0]), "brain": b} for b in brains]
    out = []
    for path, group in group_by_sample(entries):
        sample = api.get_object_by_path(path, None)
        if getattr(sample, "portal_type", None) == "AnalysisRequest":
            out.append((sample, [e["brain"] for e in group]))
    return out
