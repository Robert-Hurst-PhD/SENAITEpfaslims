# -*- coding: utf-8 -*-
"""What a run imported from raw data is expected to hold (<stem>.rawexpect.json).

Written by the Run Builder when it builds a run for a method whose
Integration settings are entered (raw_expect.wants_raw). The
worker's pull (pfas_pipeline.raw_pull) waits until every injection's raw
folder is on the share and settled, then copies and reads them (converting
only another vendor's folder) and hands the worker the run.

    {"run", "run_record": the run's record (as <stem>_extraction.json),
     "calibration": the run's curve decision,
     "injections": [{"name", "file", "type", "role", "level",
                     "expected_conc": {compound: concentration}}]}

`file` is what the instrument's sample list puts in FILE_NAME (the
method's export columns), so it names the raw folder the instrument
writes. A calibrator's concentrations are its loaded lot's where the lot
states them, else (natives only) the analyte's own ladder level; a check
standard's natives are its lot's or none. A labelled standard in a
calibrator, CCV or ICV is its lot's value, else the method's labelled
standard level (calibration.labelled_conc), else left out. An analyte with
isomers is split under its peak names: the linear peak v x (1 - b), the
branched peak v x b, b the branched fraction the lot's native certificate
states; b = 0 gives the linear peak only, and no b refuses. What was
derived is named in the run record's "expected_conc_sources": each split's
fraction and the certificate lots stating it, and each labelled standard
given the method's level, per slot. All in the ladder's unit. Pure;
Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

from senaite.pfas import calibration_levels as _cl
from senaite.pfas import composite_standards as _cmp
from senaite.pfas import isomers as _iso
from senaite.pfas import recipe_calc as _rc
from senaite.pfas import run_plan as _rp

RAW_MODES = (u"validation", u"lims")
# the ladder's units as the concentration converter names them
_UNIT = {u"ppt": u"ng/L"}


def mode(profile):
    """Where the method's results come from: vendor (the default),
    validation or lims."""
    m = ((profile or {}).get(u"integration") or {}).get(u"mode")
    return m if m in (u"vendor",) + RAW_MODES else u"vendor"


def run_mode(paths):
    """The results source a run was built or uploaded under, as its run
    record (<stem>_extraction.json) states it: the first of `paths` that
    holds a known mode, or None when none does (a record missing or that
    cannot be read is passed over)."""
    import io
    import json
    for path in paths or ():
        try:
            with io.open(path, encoding="utf-8") as fh:
                m = (json.load(fh) or {}).get(u"integration_mode")
        except (IOError, OSError, ValueError, AttributeError):
            continue
        if m in (u"vendor",) + RAW_MODES:
            return m
    return None


# the settings that mark a method's Integration as entered, per engine (the
# m/z tolerance has a default): the worker's required settings, which
# tests/test_raw_expect.py holds these equal to
_ENTERED = {u"classic": (u"smooth_points", u"baseline", u"area", u"min_sn"),
            u"adaptive": (u"smooth_points", u"area", u"min_sn", u"sensitivity", u"shoulder_pct",
                          u"qual_apex_tol")}


def wants_raw(profile):
    """A run expects its raw data once the method's Integration settings are
    entered: under Vendor results the raw run is compared, not reported;
    under Validation and LIMS integration always."""
    intg = (profile or {}).get(u"integration") or {}
    entered = all(intg.get(k) not in (None, u"") for k in _ENTERED[
        u"adaptive" if intg.get(u"engine") == u"adaptive" else u"classic"])
    return mode(profile) in RAW_MODES or entered


def lot_values(conc_rows, unit):
    """{analyte: concentration in `unit`} from a lot's analyte concentrations;
    an analyte without a value is left out."""
    to = _UNIT.get(unit, unit)
    out = {}
    for c in conc_rows or []:
        v = _rc.convert(c.get(u"concentration"), c.get(u"unit"), to)
        if c.get(u"analyte") and v is not None:
            out[c[u"analyte"]] = v
    return out


def _ladder(profile, level):
    out = {}
    try:
        i = int(level) - 1
    except (TypeError, ValueError):
        return out
    for kw in (profile or {}).get(u"master_analyte_set") or []:
        lv = _cl.levels(profile, kw)
        if 0 <= i < len(lv):
            out[kw] = lv[i]
    return out


def labelled_conc(profile):
    """The method's labelled standard level in every calibrator and check
    standard, in the ladder's unit; None when unset."""
    try:
        v = float(_cl._calib(profile).get(u"labelled_conc"))
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def isomer_entries(profile):
    """{analyte keyword: its isomers entry}."""
    return _iso.entries(profile or {})


# the injections given the method's labelled level and split by a certificate
_STANDARD_ROLES = (u"CCV", u"ICV")


def _split(expected, entries, fractions, slot, attached, used):
    """`expected` with each analyte that has isomers under its peak names:
    linear v x (1 - b), branched v x b. `attached`: a lot is loaded for
    the slot. Each fraction used is added to `used`."""
    for kw in sorted(entries):
        e = entries[kw]
        linear, branched = e.get(u"linear"), [b for b in e.get(u"branched") or [] if b]
        if kw not in expected or not linear:
            continue
        if not branched:
            expected[linear] = expected.pop(kw)
            continue
        source = ((fractions or {}).get(kw) or {}).get(slot)
        b = (source or {}).get(u"fraction")
        if b is None and not attached:
            raise ValueError(u"{0} in {1}: no lot is attached for {1}, so the branched fraction of its "
                             u"native standard is not known. Choose the lot for {1}.".format(kw, slot))
        if b is None:
            raise ValueError(u"{0} in {1}: the lot's native certificate states no branched %, so its "
                             u"linear and branched peaks cannot be given their concentrations. Enter "
                             u"it on the reagent's certificate values.".format(kw, slot))
        if not 0.0 <= b <= 1.0:
            raise ValueError(u"{0} in {1}: a branched fraction of {2:g} is outside 0 to 1.".format(kw, slot, b))
        if b > 0 and len(branched) > 1:
            raise ValueError(u"{0} in {1}: {2} branched peaks, and one certificate fraction cannot be "
                             u"divided among them.".format(kw, slot, len(branched)))
        v = expected.pop(kw)
        expected[linear] = v * (1.0 - b)
        if b > 0:
            expected[branched[0]] = v * b
        used.setdefault(kw, {})[slot] = source
    return expected


def _equal_members(profile, expected, slot, lot):
    """Refuses a calibrator or check standard whose composite standard's
    members are at different concentrations (lot values, else the method's
    labelled level): the mean of their areas stands for one amount only, as
    EPA 1633A Table 4 adds 13C2-PFDoA and 13C2-PFTeDA at one level."""
    for cname, stated in _cmp.unequal_members(profile, expected):
        where = u"Lot {0}, loaded for {1},".format(lot, slot) if lot else u"{0}".format(slot)
        raise ValueError(u"{0} states the members of {1} at different concentrations: {2}. A composite "
                         u"averages its members' areas, so they must be added at one concentration. Load a "
                         u"lot that states them alike, or change the composite's members.".format(
                             where, cname, u", ".join(u"{0} {1:g}".format(m, float(c)) for m, c in stated)))


def raw_expectation(rows, record, profile, columns, lot_values=None, calibration=None, run=u"",
                    branched=None, lot_names=None):
    """The run's expectation from its sequence `rows` (the run manifest's).
    `branched`: {analyte keyword: {lot slot ("CAL-3", "CCV", "ICV"):
    {"fraction": 0-1, "from": [the certificate lots stating it]}}}, from
    each slot's native certificate. A slot in `lot_values` has a lot
    attached; `lot_names` ({slot: lot number}) names it in a refusal."""
    lots = lot_values or {}
    labelled = labelled_conc(profile)
    grid = (profile or {}).get(u"labelled_standards")
    grid = sorted(grid) if isinstance(grid, dict) else []
    entries = isomer_entries(profile)
    used, given = {}, {}
    table = _rp.export_rows(rows, columns)
    header = table[0]
    col = header.index(u"FILE_NAME") if u"FILE_NAME" in header else None
    injections = []
    for row, line in zip(rows, table[1:]):
        role = (row.get(u"role") or u"").upper()
        level = (u"%s" % (row.get(u"level") or u"")).strip() or None
        inj = {u"name": row.get(u"name"), u"file": line[col] if col is not None else row.get(u"name"),
               u"type": row.get(u"type"), u"role": row.get(u"role") or u"",
               u"level": level}
        slot = u"CAL-%s" % level if role == u"CAL" and level else role
        if role == u"CAL" and level:
            expected = _ladder(profile, level)
            expected.update(lots.get(slot) or {})
        else:
            expected = dict(lots.get(role) or {})
        if slot.startswith(u"CAL-") or role in _STANDARD_ROLES:
            # a lot's value wins over the method's level
            if labelled is not None:
                for kw in grid:
                    if kw not in expected:
                        expected[kw] = labelled
                        if kw not in given.setdefault(slot, []):
                            given[slot].append(kw)
            _equal_members(profile, expected, slot, (lot_names or {}).get(slot))
            _split(expected, entries, branched, slot, slot in lots, used)
        if expected:
            inj[u"expected_conc"] = expected
        injections.append(inj)
    record = dict(record or {})
    record[u"integration_mode"] = mode(profile)      # the run keeps the source it was built under
    sources = {}
    if used:
        sources[u"branched"] = used
    if given:
        sources[u"labelled_conc"] = {u"value": labelled, u"unit": _cl.unit(profile), u"slots": given}
    if sources:
        record[u"expected_conc_sources"] = sources
    return {u"run": run, u"run_record": record, u"calibration": calibration or {},
            u"injections": injections}
