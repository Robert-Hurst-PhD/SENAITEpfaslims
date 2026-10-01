# -*- coding: utf-8 -*-
"""Per-method isomers (DECISIONS 2026-10-01).

    isomers = {analyte keyword: {"linear": "lr-PFOS",
                                 "branched": ["br-PFOS", ...],
                                 "reported": "" | label}}

The KEY is the panel analyte's keyword -- the identity SENAITE imports a
result under, so the pipeline keeps using it. "reported" is only the LABEL
every page and the certificate show for the summed analyte; blank means the
plain name (the analyte's display name without its "lr-" prefix). "lr-" names
the linear PEAK, never the reported total.

Replaces `isomer_summation` ([{"linear", "branched", "reported", "enabled"}]).
Reporting is ALWAYS one analyte out (the sum); the isomer peaks are kept only
for the lab's own review -- control charts, retention time, calibration --
under their peak names (DECISIONS 2026-10-01, revised the same day).
Pure; Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

KEY = "isomers"
LEGACY = "isomer_summation"


PEAK_PREFIXES = ("lr-", "br-")


def is_peak_name(keyword):
    """An isomer PEAK (linear/branched), kept for review, never a reported
    analyte on its own (one analyte out)."""
    return (keyword or u"").lower().startswith(PEAK_PREFIXES)


def plain_name(keyword, titles):
    title = titles.get(keyword) or keyword
    return title[3:] if title.lower().startswith("lr-") else title


def from_legacy(profile):
    out = {}
    for pair in profile.get(LEGACY) or []:
        if not isinstance(pair, dict) or not pair.get("reported"):
            continue
        kw = pair["reported"].strip()
        entry = out.setdefault(kw, {"linear": "", "branched": [], "reported": ""})
        if pair.get("linear") and not entry["linear"]:
            entry["linear"] = pair["linear"].strip()
        br = (pair.get("branched") or "").strip()
        if br and br not in entry["branched"]:
            entry["branched"].append(br)
    return out


def migrate(profile):
    """True if `profile` was migrated in place (idempotent)."""
    changed = False
    if KEY not in profile:
        profile[KEY] = from_legacy(profile)
        changed = True
    if LEGACY in profile:
        profile.pop(LEGACY)
        changed = True
    for entry in (profile.get(KEY) or {}).values():
        if isinstance(entry, dict) and "summed" in entry:
            entry.pop("summed")         # always summed: one analyte out
            changed = True
    return changed


def entries(profile):
    return dict((k, v) for k, v in (profile.get(KEY) or {}).items() if isinstance(v, dict))


def label(profile, keyword, titles):
    """What every page shows for `keyword` in this method: the reported name
    of a summed analyte (default its plain name), else its display name."""
    entry = entries(profile).get(keyword)
    if entry and (entry.get("linear") or entry.get("branched")):
        return (entry.get("reported") or "").strip() or plain_name(keyword, titles)
    return titles.get(keyword) or keyword


def labels(profile, keywords, titles):
    return dict((kw, label(profile, kw, titles)) for kw in keywords)


def check(profile, titles):
    """Refusals for a whole saved profile."""
    errors = []
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
