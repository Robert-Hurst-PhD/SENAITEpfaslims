# -*- coding: utf-8 -*-
"""
Dilution tracking — the contract between FM-ENV-252 and the pipeline.

A dilution is not a separate sample. It is the SAME sample re-injected at a
known factor because the neat extract read above the calibration range, and it
exists so that the over-range analytes have a quantifiable number. The lab
records it on the Extraction Log (FM-ENV-252), because a 1:10 dilution is made
from the final extract at reconstitution — an extraction step.

That record is the ONLY source of truth for the relationship. Deriving it from
the injection name (`"…; Dil. 1:10"`) was deliberately rejected: naming
conventions belong to the lab, not to the code, and the same assumption in
``INJECTION_PATTERNS`` had already produced a validator that rejected the LIMS's
own output.

## The contract

FM-ENV-252's ``samples`` table carries two columns per row:

    dilution_of      the Sample ID (or injection name) this row was diluted from
    dilution_factor  the factor, written either as "1:10" or as "10" or "0.1"

A row with an empty ``dilution_of`` is a neat sample — which every existing
logbook entry is, so batches recorded before these columns existed resolve to
"no dilutions" and behave exactly as they did.

## What the pipeline does with it

* the dilution injection is classified ``Dilution``, not ``Sample`` — so it stops
  appearing as a sample in its own right (it was being double-reported);
* QC rules are NOT applied to it, except the internal-standard consistency
  check, which is the one thing a dilution must still demonstrate;
* in the final report, an analyte whose NEAT result is above the limit of
  quantitation is reported from the dilution instead, with the neat value
  retained beside it for verification.

Python 2.7 compatible.
"""
from __future__ import absolute_import, unicode_literals

import json
import logging
import re

logger = logging.getLogger("senaite.pfas.dilution_ref")

LOGBOOK_SLUG = "252"
LOGBOOK_KEY = u"senaite.pfas.logbook.252"
SAMPLES_FIELD = "samples"
PARENT_COLUMN = "dilution_of"
FACTOR_COLUMN = "dilution_factor"
SAMPLE_ID_COLUMN = "sample_id"

# "1:10" | "1 : 10" | "10" | "0.1"
_RATIO_RE = re.compile(r'^\s*(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)\s*$')


def parse_factor(raw):
    """Normalise a written dilution factor to a float multiplier, or None.

    "1:10" -> 10.0 (the extract was diluted ten-fold)
    "10"   -> 10.0
    "0.1"  -> 10.0   — some instruments record the reciprocal; a factor below 1
                       can only mean that, so invert rather than reject it.
    """
    if raw is None:
        return None
    text = u"{0}".format(raw).strip()
    if not text:
        return None
    match = _RATIO_RE.match(text)
    if match:
        num, den = float(match.group(1)), float(match.group(2))
        if num == 0:
            return None
        return den / num
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    if value == 0:
        return None
    return 1.0 / value if value < 1 else value


def get_dilutions(batch):
    """{dilution_sample_id: {"parent": str, "factor": float|None}} for a batch.

    Empty when the logbook has no dilution rows — which is every batch recorded
    before these columns existed, so the caller's behaviour is unchanged.
    """
    out = {}
    if batch is None:
        return out
    try:
        from zope.annotation.interfaces import IAnnotations
        raw = IAnnotations(batch).get(LOGBOOK_KEY)
    except Exception:
        return out
    if not raw:
        return out
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning("FM-ENV-252 on %r is not valid JSON",
                       getattr(batch, "getId", lambda: "?")())
        return out

    try:
        from senaite.pfas.logbook_schema import active_rows
    except Exception:
        def active_rows(rows):
            return [r for r in (rows or []) if isinstance(r, dict)]

    for row in active_rows(data.get(SAMPLES_FIELD)):
        parent = (row.get(PARENT_COLUMN) or u"").strip()
        if not parent:
            continue
        sample_id = (row.get(SAMPLE_ID_COLUMN) or u"").strip()
        if not sample_id:
            continue
        out[sample_id] = {
            "parent": parent,
            "factor": parse_factor(row.get(FACTOR_COLUMN)),
        }
    return out
