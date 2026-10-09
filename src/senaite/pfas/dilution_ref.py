# -*- coding: utf-8 -*-
"""
Dilution tracking — the contract between FM-ENV-003 and the pipeline.

A dilution is not a separate sample. It is the SAME sample re-injected at a
known factor because the neat extract read above the calibration range, and it
exists so that the over-range analytes have a quantifiable number. The lab
records it on the Extraction Log (FM-ENV-003), because a 1:10 dilution is made
from the final extract at reconstitution — an extraction step.

That record is the ONLY source of truth for the relationship. Deriving it from
the injection name (`"…; Dil. 1:10"`) was deliberately rejected: naming
conventions belong to the lab, not to the code, and the same assumption in
``INJECTION_PATTERNS`` had already produced a validator that rejected the LIMS's
own output.

## The contract

FM-ENV-003's ``samples`` table carries two columns per row:

    dilution_of      the Sample ID (or injection name) this row was diluted from
    dilution_factor  the total fold, a number > 1 ("2", "10"); ratios are refused

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
    """A dilution's total fold as a float, or None (
    "Dilution fold"): a number greater than 1 -- "2", "10", 2.5.

    Ratios are refused, not interpreted: to this lab "1:1" is a 2-fold
    dilution (sample : diluent), while the code that existed read "1:10" as
    10-fold. A notation that can be read two ways is not evidence. A value of
    1 or below is not a dilution (the old reciprocal guess, "0.1" -> 10, went
    with the ratios)."""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(u"{0}".format(raw).strip())
    except (TypeError, ValueError):
        return None
    return value if value > 1 else None


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
        logger.warning("FM-ENV-003 on %r is not valid JSON",
                       getattr(batch, "getId", lambda: "?")())
        return out

    try:
        from senaite.pfas.logbook_schema import active_rows
    except Exception:
        def active_rows(rows):
            return [r for r in (rows or []) if isinstance(r, dict)]

    try:
        from senaite.pfas import extraction_batch
        rows = extraction_batch.rekey_rows(active_rows(data.get(SAMPLES_FIELD)),
                                           extraction_batch.load(batch))
    except Exception:                                       # noqa: BLE001
        rows = active_rows(data.get(SAMPLES_FIELD))
    for row in rows:
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


def sample_amounts_from_rows(rows):
    """{sample_id: {"amount", "amount_unit", "final_volume_ml"}} for the
    sample rows (not dilutions) that record a test-portion amount or a final
    volume -- what a "back-calculated in the LIMS" method corrects with
    (sample_correction.py)."""
    out = {}
    for row in rows or []:
        if not isinstance(row, dict) or (row.get(PARENT_COLUMN) or u"").strip():
            continue
        sid = (row.get(SAMPLE_ID_COLUMN) or u"").strip()
        if sid and (row.get("amount") or row.get("final_volume_ml")):
            out[sid] = {"amount": row.get("amount") or u"",
                        "amount_unit": row.get("amount_unit") or u"g",
                        "final_volume_ml": row.get("final_volume_ml") or u""}
    return out


def get_sample_amounts(batch):
    try:
        from zope.annotation.interfaces import IAnnotations
        data = json.loads(IAnnotations(batch).get(LOGBOOK_KEY) or u"{}")
    except Exception:                                       # noqa: BLE001
        return {}
    try:
        from senaite.pfas.logbook_schema import active_rows
    except Exception:                                       # noqa: BLE001
        def active_rows(rows):
            return [r for r in (rows or []) if isinstance(r, dict)]
    rows = active_rows(data.get(SAMPLES_FIELD))
    try:
        from senaite.pfas import extraction_batch
        rows = extraction_batch.rekey_rows(rows, extraction_batch.load(batch))
    except Exception:                                       # noqa: BLE001
        pass
    return sample_amounts_from_rows(rows)


# ── Matrix-spike pedigree ────────────────────────────────────────────────────
# The guided extraction records, per spiked injection, which sample it was
# fortified from and at what level. That is the same shape of fact as a
# dilution: something the bench did, recorded where the bench records it.
#
# It exists because the pipeline otherwise identifies an LFSM by looking for
# the literal substring "; LFSM " in the injection name — another hardcoded
# naming convention, and one this lab's names do not follow, so no LFSM was
# ever evaluated.

EXTRACTION_SESSION_KEY = u"senaite.pfas.extraction_session"


def spikes_from_rows(rows):
    """{injection: {"parent", "spike", "spike_unit", "level", "qc_type",
    "lfsm"}} from FM-ENV-003's older `spikes` rows (the guide's spike card
    before the extraction batch's members, extraction_batch.py, held them).
    `spike` is the amount added in `spike_unit` (the matrix's reporting
    unit), None for the method's level; an older row's `spike_ppt` is ppt."""
    out = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        inj = (row.get("sample_id") or u"").strip()
        parent = (row.get("spike_of") or u"").strip()
        qc_type = (row.get("qc_type") or u"").strip()
        if not inj or not (parent or qc_type in (u"LFB", u"LCS")):
            continue
        raw = row.get("spike_amount", row.get("spike_ppt"))
        unit = row.get("spike_unit") or (u"ppt" if row.get("spike_ppt") not in (None, u"", "") else u"")
        try:
            amount = float(raw) if raw not in (None, u"", "") else None
        except (TypeError, ValueError):
            amount = None
        out[inj] = {"parent": parent, "spike": amount, "spike_unit": unit if amount is not None else u"",
                    "level": (row.get("level") or u"").strip(),
                    "qc_type": (row.get("qc_type") or u"").strip(),
                    "lfsm": (row.get("lfsm_of") or u"").strip()}
    return out


def get_spikes(batch):
    """{injection: {"parent", "spike", "spike_unit", "level", "qc_type", "lfsm"}}.

    The guided extraction's spike rows (FM-ENV-003 `spikes`)
    are the record. A reviewer's amount for a recorded spike whose amount was
    blank (Data Review) fills it in; older session records that name a parent
    are still read."""
    out = {}
    if batch is None:
        return out
    # the extraction batch's members (extraction_batch.py)
    # are the record; the guide's older spike rows are read where none exist
    try:
        from senaite.pfas import extraction_batch
        members = extraction_batch.load(batch)
    except Exception:                                       # noqa: BLE001
        members = []
    if members:
        recorded = extraction_batch.spike_map(members)
        out.update(_session_spikes(batch, recorded))
        out.update(recorded)
        return out
    try:
        from zope.annotation.interfaces import IAnnotations
        logbook = json.loads(IAnnotations(batch).get(LOGBOOK_KEY) or u"{}")
    except Exception:                                       # noqa: BLE001
        logbook = {}
    recorded = spikes_from_rows(logbook.get("spikes") if isinstance(logbook, dict) else [])
    out.update(_session_spikes(batch, recorded))
    out.update(dict((k, v) for k, v in recorded.items()))
    return out


def _session_spikes(batch, recorded):
    """Older session pedigree entries with a parent; and, into `recorded`, a
    reviewer-entered amount for a recorded spike that had none."""
    out = {}
    try:
        from zope.annotation.interfaces import IAnnotations
        raw = IAnnotations(batch).get(EXTRACTION_SESSION_KEY)
    except Exception:
        return out
    if not raw:
        return out
    try:
        session = json.loads(raw)
    except (ValueError, TypeError):
        return out

    for injection, entry in (session.get("pedigree") or {}).items():
        if not isinstance(entry, dict):
            continue
        raw = entry.get("spike", entry.get("spike_ppt"))
        unit = entry.get("spike_unit") or (u"ppt" if "spike_ppt" in entry else u"")
        try:
            amount = float(raw) if raw not in (None, u"") else None
        except (TypeError, ValueError):
            amount = None
        if injection in recorded:
            if recorded[injection]["spike"] is None and amount is not None:
                recorded[injection]["spike"] = amount
                recorded[injection]["spike_unit"] = unit
                recorded[injection]["spike_source"] = entry.get("spike_source") or u""
            continue
        parent = (entry.get("parent_sample") or u"").strip()
        if not parent:
            continue
        out[injection] = {
            "parent": parent,
            "spike": amount, "spike_unit": unit if amount is not None else u"",
            "level": (entry.get("level") or u"").strip(),
            "qc_type": u"", "lfsm": u"",
        }
    return out
