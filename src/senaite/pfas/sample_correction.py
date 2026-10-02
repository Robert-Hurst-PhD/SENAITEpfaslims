# -*- coding: utf-8 -*-
"""Where a result is put on the sample basis -- a per-method choice
(DECISIONS 2026-10-02 "Per-sample correction").

    ""            the method's nominal matrix factor per sample type (the
                  behaviour before the choice existed)
    "instrument"  in the MS software: the imported concentration is already
                  per sample, so the LIMS applies NO factor (never twice)
    "lims"        back-calculated here, per sample:
                  C_sample = C_extract x final volume / sample amount, scaled
                  to the method's reporting unit; amount and final volume are
                  the ones logged in the guided extraction (FM-ENV-003)

    factor_for(row, reported_unit) -> float or None

`row` = {"amount", "amount_unit" (g | mL), "final_volume_ml"}; the extract
concentration is in ng/mL (the calibration unit). None -- never a guess --
when a value is missing, not positive, or the amount's kind does not fit the
reporting unit (a mass for a per-litre unit). Pure, no imports: the worker
loads this file from the add-on (pfas_pipeline.addon). Python 2.7 and 3.
"""
from __future__ import absolute_import, division, unicode_literals

NOMINAL, INSTRUMENT, LIMS = u"", u"instrument", u"lims"
MODES = (NOMINAL, INSTRUMENT, LIMS)

# ng/mL x mL / g = ng/g ; ng/mL x mL / mL = ng/mL. Scale to the reported unit.
_PER_GRAM = {u"ng/g": 1.0, u"ug/kg": 1.0, u"µg/kg": 1.0, u"ng/kg": 1000.0,
             u"pg/g": 1000.0, u"mg/kg": 0.001}
_PER_ML = {u"ng/ml": 1.0, u"ug/l": 1.0, u"µg/l": 1.0, u"ng/l": 1000.0, u"pg/ml": 1000.0}


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def factor_for(row, reported_unit):
    row = row or {}
    amount, volume = _num(row.get("amount")), _num(row.get("final_volume_ml"))
    if amount is None or volume is None:
        return None
    unit = (reported_unit or u"").strip().lower()
    kind = (row.get("amount_unit") or u"g").strip().lower()
    table = _PER_GRAM if kind == u"g" else _PER_ML if kind == u"ml" else None
    if not table or unit not in table:
        return None
    return volume / amount * table[unit]
