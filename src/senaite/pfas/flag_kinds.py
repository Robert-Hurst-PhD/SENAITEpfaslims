# -*- coding: utf-8 -*-
"""Flags by kind of exceedance: every rule of one kind attaches the same
code when it fails.

A kind is a QC Qualifiers entry (key "kind.<kind>"): its code and wording
are the lab's, set once in QC Qualifiers and shipped blank, so a kind with
no code prints nothing and the library maps the failure as before. Which
kind a rule raises is the default map below, or the method's own choice
stored only where it differs:

    profile["engine"]["rule_kinds"][rule key] = kind key, or "" for none

A rule no kind covers raises no kind code; its own flags (rule_flags) act
as they always did. Reading never writes: an old profile reads with the
default map. Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

KINDS_KEY = "rule_kinds"
LIBRARY_PREFIX = "kind."

MATRIX = "matrix"
LAB_PROCESS = "lab_process"
PROCESS_CONTAMINATION = "process_contamination"
SAMPLER_CONTAMINATION = "sampler_contamination"
CALIBRATION = "calibration"
EXTRACTION = "extraction"
IDENTIFICATION = "identification"

# (key, name), in the order QC Qualifiers lists them
KINDS = (
    (MATRIX, "Matrix interference or bias"),
    (LAB_PROCESS, "Laboratory or process issue"),
    (PROCESS_CONTAMINATION, "Process contamination"),
    (SAMPLER_CONTAMINATION, "Sampler contamination"),
    (CALIBRATION, "Calibration or instrument"),
    (EXTRACTION, "Extraction or sample"),
    (IDENTIFICATION, "Identification"),
)
KIND_NAMES = dict(KINDS)
NO_KIND = "No kind"

# The rules each kind covers. The matrix spikes and the sample duplicate
# judge the client's sample (recovery or precision); the fortified blank the
# laboratory's process; the reagent blank the process's contamination; the
# field reagent blank the sampler's; the calibration verifications and the
# internal standard the instrument; the surrogate (the extracted internal
# standard, its dilution floor included) the extraction; ion ratio, S/N and
# retention time the identification. A rule absent here has no kind.
DEFAULT_KINDS = {
    "qc_type.LFSM": MATRIX, "qc_type.LFSMD": MATRIX, "qc_type.Dup": MATRIX,
    "qc_type.LFB": LAB_PROCESS,
    "blank.LRB": PROCESS_CONTAMINATION,
    "blank.FRB": SAMPLER_CONTAMINATION,
    "ccv_recovery": CALIBRATION, "ccv_frequency": CALIBRATION,
    "is_response": CALIBRATION, "is_vs_ccv": CALIBRATION,
    "surrogate_recovery": EXTRACTION,
    "ion_ratio": IDENTIFICATION, "sn_min": IDENTIFICATION, "rrt_deviation": IDENTIFICATION,
}


def _text(v):
    if v is None:
        return ""
    if isinstance(v, bytes):
        v = v.decode("utf-8")
    return ("%s" % v).strip()


def library_key(kind):
    """The QC Qualifiers entry a kind's code and wording live in."""
    return LIBRARY_PREFIX + kind if kind else ""


def is_kind_entry(key):
    return _text(key).startswith(LIBRARY_PREFIX)


def _stored(profile):
    eng = (profile or {}).get("engine")
    kinds = eng.get(KINDS_KEY) if isinstance(eng, dict) else None
    return kinds if isinstance(kinds, dict) else {}


def kind_of(profile, rule_key):
    """The kind rule `rule_key` raises ("" for none): the method's own
    choice where it stored one, else the default map. An unknown stored
    kind reads as none."""
    rule_key = _text(rule_key)
    if not rule_key:
        return ""
    stored = _stored(profile)
    if rule_key in stored:
        kind = _text(stored.get(rule_key))
        return kind if kind in KIND_NAMES else ""
    return DEFAULT_KINDS.get(rule_key, "")


def kind_view(profile):
    """{rule key: kind} of every rule the profile places: the default map
    with the method's own choices over it. A read: nothing is written."""
    out = dict(DEFAULT_KINDS)
    for k, v in _stored(profile).items():
        out[_text(k)] = _text(v) if _text(v) in KIND_NAMES else ""
    return dict((k, v) for k, v in out.items() if v)


def set_kind(profile, rule_key, kind):
    """Store a rule's kind where it differs from the default map (removed
    when it matches). The profile, changed in place."""
    kind = _text(kind)
    if kind and kind not in KIND_NAMES:
        raise ValueError("unknown kind of exceedance: %s" % kind)
    eng = profile.setdefault("engine", {})
    stored = dict(eng.get(KINDS_KEY) or {})
    if kind == DEFAULT_KINDS.get(rule_key, ""):
        stored.pop(rule_key, None)
    else:
        stored[rule_key] = kind
    if stored or KINDS_KEY in eng:
        eng[KINDS_KEY] = stored
    return profile


def kind_flag(library, kind):
    """(code, wording) the kind prints, ("", "") while the lab has set no
    code."""
    entry = (library or {}).get(library_key(kind)) if kind else None
    if not isinstance(entry, dict):
        return "", ""
    return _text(entry.get("code")), _text(entry.get("statement"))


def name(kind):
    return KIND_NAMES.get(kind) or NO_KIND
