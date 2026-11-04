# -*- coding: utf-8 -*-
"""
Canonical QC-type vocabulary — the single source of truth for QC-type text.

The worker stores QC types as the run spells them; every READER compares
through normalize_qc_type(), so one QC concept matches under any casing or
alias.

Decisions:
  * LCS (laboratory control sample) is its own QC type, not an alias of LFB;
    no current method runs it.
  * All codes are UPPER-CASE; multi-word codes use underscores.

Python 2.7 / 3 compatible.
"""
from __future__ import absolute_import

# Canonical QC-type codes.
CALIBRATION = ("CCV", "ICV", "CCB")
BLANKS = ("MB", "LRB", "SOLVENT_BLANK")
OTHER = ("DUP", "SAMPLE", "IS", "SUR", "CAL", "UNKNOWN")


# alias (already upper-cased) -> canonical code.
_ALIASES = {
    "SURR":         "SUR",           # surrogate: the lab's code is SUR
    "SURROGATE":    "SUR",
    "SOLVENTBLANK": "SOLVENT_BLANK",
    "SOLVENT BLANK": "SOLVENT_BLANK",
}


def normalize_qc_type(value):
    """Return the canonical QC-type code for *value*.

    Upper-cases and folds known aliases (SURR -> SUR, SolventBlank ->
    SOLVENT_BLANK). Unknown codes are still upper-cased so casing stays
    uniform, but are otherwise passed through unchanged (so a new QC type
    introduced upstream is not silently dropped).
    """
    if value is None:
        return value
    code = str(value).strip().upper()
    if not code:
        return code
    return _ALIASES.get(code, code)


# ── Which QC types a method runs: ONE source ────────────────────
# A method's qc_acceptance[key]["enabled"] is the truth -- the QC engine reads
# it, and Data Review's release gate and the Run Builder read it through here;
# no second list of a method's QC types.

def enabled_qc_types(profile):
    """qc_acceptance keys this method runs (enabled), in stored order."""
    return [k for k, v in ((profile or {}).get("qc_acceptance") or {}).items()
            if isinstance(v, dict) and v.get("enabled")]


