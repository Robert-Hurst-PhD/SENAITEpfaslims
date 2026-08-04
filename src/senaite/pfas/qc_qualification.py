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

# ── Disposition ──────────────────────────────────────────────────────────────
# What the system DOES with a failure, decided without a human in the loop.
#
# QUALIFY  the failure is attributable to the sample, so the result is released
#          with a qualifier and standard wording. Repeating the analysis would
#          give the same answer.
# BLOCK    the failure occurred on material the LABORATORY prepared and
#          controls — a blank, a calibration standard, a CCV. Those are known
#          inputs that should always pass, so a failure is a laboratory problem.
#          It is not excusable as a matrix effect and must not be caveated onto
#          a client certificate; the batch is held and the lab resolves it.
QUALIFY = "qualify"
BLOCK = "block"

DISPOSITIONS = (
    (QUALIFY, u"Qualify and release",
     u"Attributable to the sample. Released with a qualifier and standard "
     u"wording; re-analysis would not change the outcome."),
    (BLOCK, u"Hold for laboratory resolution",
     u"Occurred on laboratory control material that should always pass. Held "
     u"for investigation or re-analysis; never qualified onto a certificate."),
)

# Injection roles that are LABORATORY control material. A failure on any of
# these blocks regardless of failure type: the lab made the sample, so the lab
# owns the failure. Client material — samples, and the spikes and duplicates
# prepared FROM them — can carry a matrix qualifier.
CONTROL_ROLES = frozenset([
    "MB", "MxB", "LRB", "LFB", "LCS", "CCB", "CAL", "CCV", "ICV", "Standard",
    "Blank", "Quality Control",
])

# ── Failure taxonomy ─────────────────────────────────────────────────────────
# Keyed to what the QC engine actually emits. `default_cause` is a PROPOSAL the
# QAO confirms or overrides — never a verdict, because a surrogate failure that
# really is a lab error is exactly the case where a retest should be offered.
# (key, label, default disposition, qualifier code)
#
# Codes extend the set the EDD already emits (U, J, B, NC, EMPC) rather than
# starting a second vocabulary. They are DRAFTS for the QAO to confirm — the
# library editor owns them, and nothing here is authoritative until approved.
FAILURE_TYPES = [
    ("calibration",  u"Calibration curve",                   BLOCK,   u""),
    ("ccv",          u"Continuing calibration verification", BLOCK,   u""),
    ("blank",        u"Blank contamination",                 BLOCK,   u"B"),
    ("is_response",  u"Internal standard response",          BLOCK,   u""),
    ("surrogate",    u"Surrogate recovery",                  QUALIFY, u"M"),
    ("lfsm",         u"Matrix spike recovery",               QUALIFY, u"M"),
    ("lfsmd",        u"Matrix spike duplicate (RPD)",        QUALIFY, u"P"),
    ("duplicate",    u"Sample duplicate (RPD)",              QUALIFY, u"P"),
    ("ion_ratio",    u"Ion ratio / confirmation",            QUALIFY, u"NC"),
    ("sn",           u"Signal to noise",                     QUALIFY, u"J"),
    ("rt",           u"Retention time",                      QUALIFY, u"NC"),
]

FAILURE_LABELS = dict((k, label) for k, label, _d, _c in FAILURE_TYPES)
DEFAULT_DISPOSITION = dict((k, d) for k, _l, d, _c in FAILURE_TYPES)
DEFAULT_CODE = dict((k, code) for k, _l, _d, code in FAILURE_TYPES)


def disposition_for(failure_type, injection_role=u"", library=None):
    """QUALIFY or BLOCK for a failure, given where it happened.

    Two rules, in order:

    1. A failure on LABORATORY CONTROL MATERIAL always blocks. A method blank,
       a calibration standard and a CCV are inputs the laboratory prepared and
       controls; they are supposed to pass every time, so a failure means
       something is wrong here, not in the client's sample. Excusing it as a
       matrix effect would be false — there is no client matrix in a blank.
    2. Otherwise the failure type's configured disposition applies.
    """
    if injection_role and injection_role in CONTROL_ROLES:
        return BLOCK
    if library and failure_type in library:
        configured = (library[failure_type] or {}).get("disposition")
        if configured in (QUALIFY, BLOCK):
            return configured
    return DEFAULT_DISPOSITION.get(failure_type, BLOCK)


# Draft wordings, in the style commercial certificates use: what failed, which
# results it affects, and what the reader should conclude. Written from
# convention rather than transcribed from a standard — the QAO edits and
# approves them in the library editor, and that approval is what makes them
# authoritative. No clause is cited because none has been verified here.
#
# BLOCK entries carry an INTERNAL note instead of client wording: they never
# reach a certificate, so what matters is telling the analyst what to do.
DEFAULT_LIBRARY = {
    "surrogate": {
        "statement": u"Surrogate recovery for the affected analytes fell "
                     u"outside the method acceptance window. This is "
                     u"attributable to the sample matrix rather than to the "
                     u"analysis; re-analysis would be expected to give the "
                     u"same outcome. The accuracy of the affected results "
                     u"cannot be guaranteed and they should be treated as "
                     u"indicative.",
    },
    "lfsm": {
        "statement": u"Matrix spike recovery for the affected analytes fell "
                     u"outside the method acceptance window, indicating that "
                     u"the sample matrix suppresses or enhances the response "
                     u"of these analytes. The accuracy of the affected results "
                     u"cannot be guaranteed and they should be treated as "
                     u"indicative.",
    },
    "lfsmd": {
        "statement": u"Agreement between the matrix spike and its duplicate "
                     u"exceeded the method precision limit, consistent with "
                     u"sample heterogeneity. The precision of the affected "
                     u"results cannot be guaranteed.",
    },
    "duplicate": {
        "statement": u"Agreement between duplicate analyses exceeded the "
                     u"method precision limit, consistent with sample "
                     u"heterogeneity. The precision of the affected results "
                     u"cannot be guaranteed.",
    },
    "ion_ratio": {
        "statement": u"The qualifier-to-quantifier ion ratio for the affected "
                     u"analytes fell outside the method tolerance, most "
                     u"commonly caused by co-eluting sample matrix. "
                     u"Identification could not be confirmed and the affected "
                     u"results should be treated as presumptive.",
    },
    "sn": {
        "statement": u"Sample matrix raised the baseline for the affected "
                     u"analytes, reducing the signal-to-noise ratio below the "
                     u"method minimum. The affected results are estimated and "
                     u"their accuracy near the reporting limit cannot be "
                     u"guaranteed.",
    },
    "rt": {
        "statement": u"Retention time for the affected analytes fell outside "
                     u"the method tolerance, consistent with matrix effects on "
                     u"the chromatography. Identification could not be "
                     u"confirmed and the affected results should be treated as "
                     u"presumptive.",
    },
    # Held, never issued. The text is for the analyst.
    "calibration": {
        "statement": u"Calibration did not meet method criteria. Held for "
                     u"laboratory resolution: review the curve, recalibrate "
                     u"and re-analyse the affected sequence.",
    },
    "ccv": {
        "statement": u"Continuing calibration verification fell outside the "
                     u"method window. Held for laboratory resolution: "
                     u"recalibrate and re-analyse the samples bracketed by "
                     u"this CCV.",
    },
    "blank": {
        "statement": u"Analytes were detected in a laboratory blank above the "
                     u"reporting limit. Held for laboratory resolution: "
                     u"identify the contamination source and re-extract the "
                     u"affected batch.",
    },
    "is_response": {
        "statement": u"Injection internal standard response fell outside the "
                     u"method window, indicating an instrument or injection "
                     u"problem. Held for laboratory resolution: re-inject and "
                     u"investigate before release.",
    },
}


# ── Library storage (lab-wide, QAO-editable) ─────────────────────────────────

def get_library(portal):
    """The lab's qualifier library, seeded where it has not been customised.

    One entry per failure type: its disposition, its certificate code and its
    wording. Saved edits win field by field, so a seed improvement still
    reaches anything the QAO has not overridden.
    """
    saved = {}
    raw = IAnnotations(portal).get(LIBRARY_KEY)
    if raw:
        try:
            saved = json.loads(raw)
        except (ValueError, TypeError):
            logger.warning("QC qualifier library unreadable; using defaults")
    out = {}
    for key, label, disposition, code in FAILURE_TYPES:
        entry = saved.get(key) or {}
        seed = DEFAULT_LIBRARY.get(key) or {}
        out[key] = {
            "key": key,
            "label": label,
            "disposition": entry.get("disposition") or disposition,
            "code": entry.get("code", code),
            "statement": entry.get("statement") or seed.get("statement", u""),
            "customised": bool(entry),
        }
    return out


def save_library(portal, data):
    """Store only what differs from the seed."""
    trimmed = {}
    for key, _label, disposition, code in FAILURE_TYPES:
        entry = (data or {}).get(key) or {}
        seed_text = (DEFAULT_LIBRARY.get(key) or {}).get("statement", u"")
        diff = {}
        if (entry.get("disposition") or disposition) != disposition:
            diff["disposition"] = entry["disposition"]
        if entry.get("code", code) != code:
            diff["code"] = entry.get("code", code)
        if (entry.get("statement") or u"").strip() != seed_text.strip():
            diff["statement"] = entry.get("statement") or u""
        if diff:
            trimmed[key] = diff
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


def qualifier_for(portal, failure_type, injection_role=u""):
    """The qualifier to apply, or None when the failure must be held.

    No human in the loop: the QAO's control is the library, not a per-result
    approval. Returns the code, the wording and why it was chosen, so the
    certificate and the audit trail say the same thing.
    """
    library = get_library(portal)
    entry = library.get(failure_type)
    if not entry:
        # Unrecognised failures hold. Releasing one under a qualifier chosen by
        # nobody is exactly the silent-substitution failure this codebase has
        # spent the day removing.
        return None
    disposition = disposition_for(failure_type, injection_role, library)
    if disposition == BLOCK:
        return None
    return {
        "failure_type": failure_type,
        "label": entry["label"],
        "code": entry["code"],
        "statement": entry["statement"],
    }


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
