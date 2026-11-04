# -*- coding: utf-8 -*-
"""Per-method isomers.

    isomers = {analyte keyword: {"linear": "lr-PFOS",
                                 "branched": ["br-PFOS", ...],
                                 "reported": "" | label}}

The KEY is the panel analyte's keyword -- the identity SENAITE imports a
result under, so the pipeline keeps using it. "reported" is only the LABEL
every page and the certificate show for the summed analyte; blank means the
plain name (the analyte's display name without its "lr-" prefix). "lr-" names
the linear PEAK, never the reported total.

Reporting is ALWAYS one analyte out (the sum); the isomer peaks are kept only
for the lab's own review -- control charts, retention time, calibration --
under their peak names. Pure; Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

KEY = "isomers"


PEAK_PREFIXES = ("lr-", "br-")


def is_peak_name(keyword):
    """An isomer PEAK (linear/branched), kept for review, never a reported
    analyte on its own (one analyte out)."""
    return (keyword or u"").lower().startswith(PEAK_PREFIXES)


def plain_name(keyword, titles):
    title = titles.get(keyword) or keyword
    return title[3:] if title.lower().startswith("lr-") else title


def entries(profile):
    return dict((k, v) for k, v in (profile.get(KEY) or {}).items() if isinstance(v, dict))


def label(profile, keyword, titles):
    """What every page shows for `keyword` in this method: the reported name
    of a summed analyte (default its plain name), else its display name."""
    entry = entries(profile).get(keyword)
    if entry and (entry.get("linear") or entry.get("branched")):
        return (entry.get("reported") or "").strip() or plain_name(keyword, titles)
    return titles.get(keyword) or keyword


def is_summed(profile, keyword):
    entry = entries(profile).get(keyword)
    return bool(entry and (entry.get("linear") or entry.get("branched")))


def full_name(profile, keyword, names):
    """The analyte's full name as reported in this method. The
    reference names the PFOS / PFHxS keyword after its LINEAR isomer; a
    method that sums the isomers reports the total, so the name says so
    instead of "(linear)". `names`: {keyword: full name}."""
    name = (names.get(keyword) or u"").strip()
    if not name or not is_summed(profile, keyword):
        return name
    if name.lower().endswith(u"(linear)"):
        name = name[:-len(u"(linear)")].rstrip()
    return u"%s (total of linear and branched isomers)" % name


def labels(profile, keywords, titles):
    return dict((kw, label(profile, kw, titles)) for kw in keywords)


def peak_names(profile):
    """{peak name: the analyte it sums into} over the profile's isomers."""
    out = {}
    for kw, e in entries(profile).items():
        for peak in ([e["linear"]] if e.get("linear") else []) + list(e.get("branched") or []):
            out[peak] = kw
    return out


def peaks_of(profile, keyword):
    """The analyte's isomer peaks, linear first: each is integrated and
    quantified as its own analyte; [] for an analyte without isomers."""
    e = entries(profile).get(keyword) or {}
    return ([e["linear"]] if e.get("linear") else []) + [b for b in e.get("branched") or [] if b]


def integration_names(profile, keywords):
    """`keywords` with each analyte that has isomers replaced by its peaks,
    each name once: the rows a raw run is integrated with."""
    out = []
    for kw in keywords:
        for name in peaks_of(profile, kw) or [kw]:
            if name not in out:
                out.append(name)
    return out


def partners(profile):
    """{peak: its partner}: a linear peak's partner is its first branched
    peak, a branched peak's its linear peak."""
    out = {}
    for e in entries(profile).values():
        linear = e.get("linear")
        branched = [b for b in e.get("branched") or [] if b]
        if not linear:
            continue
        if branched:
            out[linear] = branched[0]
        for b in branched:
            out[b] = linear
    return out


def branched_peaks(profile):
    """Every branched peak name: integrated as the sum of the peaks in its
    own window, leaving out its linear partner's peak."""
    return set(b for e in entries(profile).values() for b in e.get("branched") or [] if b)


def summed_of(profile, name):
    """The analyte a peak name sums into, else None."""
    return peak_names(profile).get(name)


def check(profile, titles, library=None):
    """Refusals for a whole saved profile. With the compound `library`, every
    peak name must be a spelling the library knows: the linear peak one of
    its own analyte's, a branched peak an analyte's."""
    errors = []
    if library is not None:
        from senaite.pfas import compound_library as cl
        def resolves(peak):
            """The analyte a peak name names: the name itself, or what follows
            its lr-/br- prefix, as the library spells it."""
            base = peak[3:] if (peak or "").lower().startswith(PEAK_PREFIXES) else peak
            return cl.keyword_of(library, peak) or cl.keyword_of(library, base)
        for kw in sorted(entries(profile)):
            e = entries(profile)[kw]
            if e.get("linear") and resolves(e["linear"]) != kw:
                errors.append("%s: the linear peak %s is not lr- plus a spelling of %s in the compound "
                              "library (Setup > Analysis Services, the PFAS tab's export names)."
                              % (kw, e["linear"], kw))
            for peak in e.get("branched") or []:
                if cl.role_of(library, resolves(peak) or peak) != "analyte":
                    errors.append("%s: the branched peak %s is not br- plus an analyte of the compound "
                                  "library." % (kw, peak))
    panel = list(profile.get("master_analyte_set") or [])
    taken = {}                       # name -> what already uses it
    for kw in panel:
        taken[kw.lower()] = "the analyte %s" % kw
        taken[(titles.get(kw) or kw).lower()] = "the analyte %s" % kw
    for kw in sorted(entries(profile)):
        e = entries(profile)[kw]
        peaks = ([e["linear"]] if e.get("linear") else []) + list(e.get("branched") or [])
        if not peaks:
            continue
        if kw not in panel:
            errors.append("%s has isomers but is not in this method's analyte panel." % kw)
        if e.get("branched") and not e.get("linear"):
            errors.append("%s: a branched peak needs its linear peak too." % kw)
        for peak in peaks:
            owner = taken.get(peak.lower())
            if owner and owner != "the analyte %s" % kw:
                errors.append("%s: the peak name %s is already used by %s, so its "
                              "result would be counted twice." % (kw, peak, owner))
            taken[peak.lower()] = "%s's isomers" % kw
    shown = {}                       # every panel analyte's label, isomers or not
    for kw in panel:
        name = label(profile, kw, titles)
        if name.lower() in shown:
            errors.append("%s and %s would both be reported as %s." % (
                shown[name.lower()], kw, name))
        else:
            shown[name.lower()] = kw
    return errors
