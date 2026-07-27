# -*- coding: utf-8 -*-
"""
Canonical QC-type vocabulary — the single source of truth for QC-type text.

Every writer into the QC store normalizes through normalize_qc_type() so the
same QC concept is always stored under one uniform ALL-CAPS code, regardless
of how the pipeline / importer / seed happened to spell it.

Decisions:
  * LCS and LFB are the same QC type (lab fortified blank / lab control
    sample). Canonical name: LFB. LCS is an alias that folds into LFB.
  * All codes are UPPER-CASE; multi-word codes use underscores.

Python 2.7 / 3 compatible.
"""
from __future__ import absolute_import

# Canonical QC-type codes.
CALIBRATION = ("CCV", "ICV", "CCB")
BLANKS = ("MB", "LRB", "SOLVENT_BLANK")
FORTIFIED = ("LFB", "LFSM", "LFSMD")
OTHER = ("DUP", "SAMPLE", "IS", "SURR", "CAL", "UNKNOWN")

CANONICAL_QC_TYPES = frozenset(CALIBRATION + BLANKS + FORTIFIED + OTHER)

# alias (already upper-cased) -> canonical code.
_ALIASES = {
    "LCS":          "LFB",           # lab control sample == lab fortified blank
    "SOLVENTBLANK": "SOLVENT_BLANK",
    "SOLVENT BLANK": "SOLVENT_BLANK",
}


def normalize_qc_type(value):
    """Return the canonical QC-type code for *value*.

    Upper-cases and folds known aliases (LCS -> LFB, SolventBlank ->
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
