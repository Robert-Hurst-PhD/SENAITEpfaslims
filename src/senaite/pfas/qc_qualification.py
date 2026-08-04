# -*- coding: utf-8 -*-
"""
Qualified release — publishing a result that failed a QC criterion.

ISO 17025 §7.8.4 permits releasing non-conforming work when the deviation is
authorised, justified and recorded. Until 2026-08-04 this system implemented
only half of CLAUDE.md §10's rule: a failing QC result blocked release
absolutely, with no way for anyone to authorise an exception. That is stricter
than the standard and, in practice, unusable — a matrix that suppresses a
surrogate is a property of the sample, not a laboratory error, and the client is
still entitled to the result with an honest caveat.

What this module owns:

  * the LIBRARY of approved wordings, lab-wide and QAO-editable, keyed by
    (failure type, cause). No certificate wording is hardcoded (§1.1), and it
    stays under QA control rather than being retyped per case.
  * the CAUSE taxonomy — LABORATORY vs MATRIX — and a proposal for each failure
    type, which the QAO confirms or overrides.
  * SCOPING: which analytes on which samples a given failure actually touches.

Scope is deliberately narrow. A surrogate failure qualifies only the analytes
that surrogate quantifies, on the sample it failed in — a blanket qualification
devalues the warning it exists to make.

Python 2.7 (in-Plone add-on).
"""
from __future__ import absolute_import

import json
import logging

from zope.annotation.interfaces import IAnnotations

logger = logging.getLogger("senaite.pfas.qc_qualification")

LIBRARY_KEY = "senaite.pfas.qc_qualification.library"

# ── Causes ───────────────────────────────────────────────────────────────────
# The distinction drives the wording AND whether a retest is offered: a
# laboratory failure is ours to repeat, a matrix effect is not.
LABORATORY = "laboratory"
MATRIX = "matrix"

CAUSES = (
    (LABORATORY, u"Laboratory", u"Attributable to the analysis — instrument, "
                                u"calibration, reagents or process."),
    (MATRIX, u"Sample matrix", u"Attributable to the sample itself; repeating "
                               u"the analysis would not change the outcome."),
)

# ── Failure taxonomy ─────────────────────────────────────────────────────────
# Keyed to what the QC engine actually emits. `default_cause` is a PROPOSAL the
# QAO confirms or overrides — never a verdict, because a surrogate failure that
# really is a lab error is exactly the case where a retest should be offered.
FAILURE_TYPES = [
    ("calibration",  u"Calibration curve",        LABORATORY),
    ("ccv",          u"Continuing calibration verification", LABORATORY),
    ("is_response",  u"Internal standard response", LABORATORY),
    ("rt",           u"Retention time",           LABORATORY),
    ("ion_ratio",    u"Ion ratio / confirmation", LABORATORY),
    ("sn",           u"Signal to noise",          LABORATORY),
    ("blank",        u"Blank contamination",      LABORATORY),
    ("surrogate",    u"Surrogate recovery",       MATRIX),
    ("lfsm",         u"Matrix spike recovery",    MATRIX),
    ("lfsmd",        u"Matrix spike duplicate (RPD)", MATRIX),
    ("duplicate",    u"Sample duplicate (RPD)",   MATRIX),
]

FAILURE_LABELS = dict((k, label) for k, label, _c in FAILURE_TYPES)
DEFAULT_CAUSE = dict((k, cause) for k, _l, cause in FAILURE_TYPES)


def _msg(statement, offer_retest):
    return {"statement": statement, "offer_retest": offer_retest}


# Seed wordings. Concise, and they say what the reader needs: which results are
# affected, why, and what it means for them. LABORATORY variants offer a
# retest; MATRIX variants state that the sample itself is the cause, because
# offering to repeat an analysis that would give the same answer is misleading.
DEFAULT_LIBRARY = {
    "calibration": {
        LABORATORY: _msg(
            u"The calibration curve for the affected analytes did not meet the "
            u"method's acceptance criteria for this run. The accuracy of these "
            u"results cannot be guaranteed. A re-analysis is available on "
            u"request.", True),
        MATRIX: _msg(
            u"The calibration response for the affected analytes was altered by "
            u"the sample matrix. Reported values should be treated as "
            u"indicative for these analytes.", False),
    },
    "ccv": {
        LABORATORY: _msg(
            u"The continuing calibration verification bracketing these samples "
            u"fell outside the method's acceptance window. The accuracy of the "
            u"affected results cannot be guaranteed. A re-analysis is available "
            u"on request.", True),
        MATRIX: _msg(
            u"Instrument response drifted across this sequence for the affected "
            u"analytes. Reported values should be treated as indicative.", False),
    },
    "is_response": {
        LABORATORY: _msg(
            u"The internal standard response for the affected analytes fell "
            u"outside the method's acceptance window, indicating an analytical "
            u"rather than sample cause. The accuracy of these results cannot be "
            u"guaranteed. A re-analysis is available on request.", True),
        MATRIX: _msg(
            u"The internal standard response was suppressed or enhanced by the "
            u"sample matrix. Reported values for the affected analytes are "
            u"matrix-influenced and should be treated as indicative.", False),
    },
    "rt": {
        LABORATORY: _msg(
            u"Retention times for the affected analytes fell outside the "
            u"method's tolerance. Identification confidence is reduced and the "
            u"accuracy of these results cannot be guaranteed. A re-analysis is "
            u"available on request.", True),
        MATRIX: _msg(
            u"Chromatography for the affected analytes was altered by the "
            u"sample matrix. Reported values should be treated as indicative.",
            False),
    },
    "ion_ratio": {
        LABORATORY: _msg(
            u"The qualifier-to-quantifier ion ratio for the affected analytes "
            u"fell outside the method's tolerance, so identification could not "
            u"be confirmed. The accuracy of these results cannot be guaranteed. "
            u"A re-analysis is available on request.", True),
        MATRIX: _msg(
            u"The qualifier ion ratio for the affected analytes was affected by "
            u"co-eluting sample matrix, so identification could not be "
            u"confirmed. Reported values should be treated as indicative.",
            False),
    },
    "sn": {
        LABORATORY: _msg(
            u"The signal-to-noise ratio for the affected analytes fell below "
            u"the method's minimum. The accuracy of these results near the "
            u"reporting limit cannot be guaranteed. A re-analysis is available "
            u"on request.", True),
        MATRIX: _msg(
            u"Sample matrix raised the baseline for the affected analytes, "
            u"reducing the signal-to-noise ratio below the method's minimum. "
            u"Reported values should be treated as indicative.", False),
    },
    "blank": {
        LABORATORY: _msg(
            u"The method blank contained the affected analytes above the "
            u"reporting limit, indicating laboratory contamination. Reported "
            u"values may be biased high and their accuracy cannot be "
            u"guaranteed. A re-analysis is available on request.", True),
        MATRIX: _msg(
            u"The affected analytes were detected in the blank at levels "
            u"consistent with the sample matrix or containers. Reported values "
            u"may be biased high.", False),
    },
    "surrogate": {
        LABORATORY: _msg(
            u"Surrogate recovery for the affected analytes fell outside the "
            u"method's acceptance window for analytical reasons. The accuracy "
            u"of these results cannot be guaranteed. A re-analysis is available "
            u"on request.", True),
        MATRIX: _msg(
            u"Surrogate recovery for the affected analytes fell outside the "
            u"method's acceptance window because of the sample matrix. This is "
            u"a characteristic of the sample type rather than of the analysis; "
            u"reported values for these analytes should be treated as "
            u"indicative.", False),
    },
    "lfsm": {
        LABORATORY: _msg(
            u"Matrix spike recovery for the affected analytes fell outside the "
            u"method's acceptance window for analytical reasons. The accuracy "
            u"of these results cannot be guaranteed. A re-analysis is available "
            u"on request.", True),
        MATRIX: _msg(
            u"Matrix spike recovery for the affected analytes fell outside the "
            u"method's acceptance window because of the sample matrix. This is "
            u"a characteristic of the sample type rather than of the analysis; "
            u"reported values for these analytes should be treated as "
            u"indicative.", False),
    },
    "lfsmd": {
        LABORATORY: _msg(
            u"Agreement between the matrix spike and its duplicate exceeded the "
            u"method's precision limit for analytical reasons. The precision of "
            u"the affected results cannot be guaranteed. A re-analysis is "
            u"available on request.", True),
        MATRIX: _msg(
            u"Agreement between the matrix spike and its duplicate exceeded the "
            u"method's precision limit owing to sample heterogeneity. Reported "
            u"values for the affected analytes should be treated as "
            u"indicative.", False),
    },
    "duplicate": {
        LABORATORY: _msg(
            u"Agreement between duplicate analyses exceeded the method's "
            u"precision limit for analytical reasons. The precision of the "
            u"affected results cannot be guaranteed. A re-analysis is available "
            u"on request.", True),
        MATRIX: _msg(
            u"Agreement between duplicate analyses exceeded the method's "
            u"precision limit owing to sample heterogeneity. Reported values "
            u"for the affected analytes should be treated as indicative.",
            False),
    },
}


# ── Library storage (lab-wide, QAO-editable) ─────────────────────────────────

def get_library(portal):
    """The lab's approved wordings, seeded from DEFAULT_LIBRARY when unset.

    Saved edits win per (failure type, cause); anything the lab has not
    customised falls through to the seed, so adding a failure type later does
    not leave a blank certificate statement.
    """
    saved = {}
    raw = IAnnotations(portal).get(LIBRARY_KEY)
    if raw:
        try:
            saved = json.loads(raw)
        except (ValueError, TypeError):
            logger.warning("QC qualification library unreadable; using defaults")
    out = {}
    for key, _label, _cause in FAILURE_TYPES:
        out[key] = {}
        for cause, _clabel, _cdesc in CAUSES:
            seed = (DEFAULT_LIBRARY.get(key) or {}).get(cause) or _msg(u"", False)
            entry = ((saved.get(key) or {}).get(cause) or {})
            out[key][cause] = {
                "statement": entry.get("statement") or seed["statement"],
                "offer_retest": bool(entry.get("offer_retest",
                                               seed["offer_retest"])),
                "customised": bool(entry.get("statement")),
            }
    return out


def save_library(portal, data):
    """Persist only what differs from the seed, so seed improvements reach a
    lab that never customised a given wording."""
    trimmed = {}
    for key, per_cause in (data or {}).items():
        for cause, entry in (per_cause or {}).items():
            statement = (entry or {}).get("statement") or u""
            seed = (DEFAULT_LIBRARY.get(key) or {}).get(cause) or _msg(u"", False)
            retest = bool((entry or {}).get("offer_retest"))
            if statement.strip() == seed["statement"].strip() \
                    and retest == seed["offer_retest"]:
                continue
            trimmed.setdefault(key, {})[cause] = {
                "statement": statement,
                "offer_retest": retest,
            }
    IAnnotations(portal)[LIBRARY_KEY] = json.dumps(trimmed)
    return trimmed


# ── Classifying a failure ────────────────────────────────────────────────────

# Matched against the QC flag's source and issue text, most specific first.
_SOURCE_HINTS = [
    ("ccv", ("ccv",)),
    ("calibration", ("calibration",)),
    # "surrogate" BEFORE "is_response": the engine emits one source,
    # "SUR-IS Response Table", for both roles, and it contains the substring
    # "IS Response". Matching that first classified every surrogate failure as
    # an instrument problem and proposed LABORATORY -- the opposite of the
    # intended default, and the one case where the wording must say the matrix
    # is responsible. The compound's ROLE settles it below; this ordering is
    # the fallback when the role cannot be resolved.
    ("surrogate", ("sur-is", "surrogate", "(sur)")),
    ("is_response", ("is response", "is raw")),
    ("ion_ratio", ("qual-quan", "ion ratio", "(iq)")),
    ("sn", ("signal-to-noise", "signal to noise")),
    ("rt", ("rrt", "retention", "rt deviation")),
    ("lfsmd", ("lfsmd",)),
    ("lfsm", ("lfsm",)),
    ("duplicate", ("dup",)),
    ("blank", ("blank", "mb", "lrb", "mxb")),
]


def classify_failure(source, issue=u"", qc_type=u"", analyte=u"",
                     method_id=u""):
    """Canonical failure type for a QC flag, or "" when unrecognised.

    Deliberately returns empty rather than guessing: an unrecognised failure
    must not be qualified under someone else's wording.

    When the flag came from the combined surrogate/IS table, the COMPOUND'S
    ROLE decides which it is. A surrogate is added before extraction and travels
    with the sample, so its recovery reflects the matrix; the injection standard
    is added at reconstitution, so its response reflects the instrument. They
    need opposite default causes and opposite wordings, and the source string
    cannot tell them apart.
    """
    haystack = u" ".join([source or u"", issue or u"", qc_type or u""]).lower()
    for key, needles in _SOURCE_HINTS:
        for needle in needles:
            if needle in haystack:
                if key in ("surrogate", "is_response") and analyte:
                    return _labelled_role(analyte, method_id) or key
                return key
    return u""


def _labelled_role(analyte, method_id):
    """"surrogate" or "is_response" for a labelled compound, per the METHOD."""
    try:
        from bika.lims import api
        from senaite.pfas.method_profile_store import get_profile
        chain = (get_profile(api.get_portal(), method_id)
                 or {}).get("surrogate_is_chain") or {}
    except Exception:
        return u""
    if not chain:
        return u""
    surrogates = [k for k in chain]
    injection_stds = [v for v in chain.values() if v]
    if any(_same_compound(name, analyte) for name in injection_stds) \
            and not any(_same_compound(name, analyte) for name in surrogates):
        return "is_response"
    if any(_same_compound(name, analyte) for name in surrogates):
        return "surrogate"
    return u""


def propose_cause(failure_type):
    return DEFAULT_CAUSE.get(failure_type, LABORATORY)


# ── Scoping ──────────────────────────────────────────────────────────────────

def analytes_for_failure(failure_type, analyte, method_id=""):
    """Which reported analytes a failure on `analyte` actually affects.

    An IS or surrogate failure is recorded against the LABELLED compound, but
    what the client reads is the natives that compound quantifies — so the
    method's surrogate map is reversed to find them. Everything else affects
    the analyte it was raised on.
    """
    if failure_type not in ("surrogate", "is_response"):
        return [analyte] if analyte else []
    try:
        from senaite.pfas.method_bridge import get_method_surrogate_map
        mapping = get_method_surrogate_map(method_id) or {}
    except Exception:
        mapping = {}
    if not mapping:
        mapping = _surrogate_map_fallback(method_id)
    natives = sorted(set(
        native for native, surrogate in mapping.items()
        if surrogate and _same_compound(surrogate, analyte)))
    return natives or ([analyte] if analyte else [])


def _same_compound(a, b):
    """Compare labelled-compound names across spellings (M8PFOA / 13C8-PFOA)."""
    if not a or not b:
        return False
    if a == b:
        return True
    try:
        from senaite.pfas.analyte_reference import COMPOUND_NAME_TO_KEYWORD
        return (COMPOUND_NAME_TO_KEYWORD.get(a, a)
                == COMPOUND_NAME_TO_KEYWORD.get(b, b))
    except Exception:
        return False


def _surrogate_map_fallback(method_id):
    """native -> surrogate, straight from the stored method profile."""
    try:
        from bika.lims import api
        from senaite.pfas.method_profile_store import get_profile
        profile = get_profile(api.get_portal(), method_id) or {}
    except Exception:
        return {}
    out = {}
    for row in (profile.get("surrogate_map") or []):
        analyte = (row.get("analyte") or "").strip()
        surrogate = (row.get("surrogate_is") or "").strip()
        if analyte and surrogate:
            out[analyte] = surrogate
    return out
