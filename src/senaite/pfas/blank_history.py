# -*- coding: utf-8 -*-
"""Blank history and the lots behind a change in background (Part 2).

A blank's results (qc_results) belong to a run; the run's lots are the ones
its extraction batch recorded (inventory_ledger: reagents, standards and
consumables, by stage) and its calibration prep (FM-ENV-002). Comparing a
blank with the previous blank of the same method, matrix and kind, the lots
both used are folded away: what is left -- lots changed for the same role,
lots new to this run, lots no longer used -- are the candidates for a change
in background.

    BLANK_TYPES                         the blank kinds tracked
    runs(rows)                          [{batch_id, run_date, method, matrix,
                                          qc_type, values: {analyte: value}, failed}]
    previous(runs, current)             the comparable run before `current`
    lots_of(ledger_rows, fm251)         [{kind, lot, name, role, stage}]
    lot_diff(current, previous)         {"changed", "new", "gone", "shared"}
    rise(current, previous)             [(analyte, now, before)] that went up

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

# extracted blanks, the solvent (instrument) blank and the matrix blank
BLANK_TYPES = ("MB", "LRB", "CCB", "MxB")

# FM-ENV-002 lot fields (the same list Data Review's traceability walk reads)
FM251_FIELDS = (("pds_a_lot", u"PDS-A"), ("pds_b_lot", u"PDS-B"),
                ("analyte_pds_lot", u"Analyte PDS"), ("analyte_spike_lot", u"Surrogate Spike"),
                ("cal_a_lot", u"CAL-A"))


def runs(rows):
    """One entry per (run, blank kind) from qc_results rows ({batch_id,
    run_date, method, matrix, qc_type, analyte, value, passed, qc_level,
    units}), newest first. An isomer component is kept under its own name.
    Every blank is one entry per injection (its qc_level; rows stored before
    2026-10-09 have none but a matrix blank's): two method blanks of one run
    are two entries, and a matrix blank is compared with its own lot's
    assigned levels (matrix_blank.py)."""
    by = {}
    for r in rows or []:
        if r.get("qc_type") not in BLANK_TYPES:
            continue
        inj = r.get("qc_level") or u""
        key = (r.get("batch_id"), r.get("qc_type"), inj)
        e = by.setdefault(key, {"batch_id": r.get("batch_id"), "run_date": (u"%s" % (r.get("run_date") or u""))[:10],
                                "method": r.get("method") or u"", "matrix": r.get("matrix") or u"",
                                "qc_type": r.get("qc_type"), "injection": inj,
                                "key": inj or r.get("batch_id"),
                                "units": r.get("units") or u"", "values": {}, "failed": []})
        e["values"][r.get("analyte")] = r.get("value")
        if not r.get("passed", 1):
            e["failed"].append(r.get("analyte"))
    return sorted(by.values(), key=lambda e: (e["run_date"], e["batch_id"], e["injection"]), reverse=True)


def comparable(a, b):
    """Same blank kind and method; same matrix when both runs know theirs."""
    if a["qc_type"] != b["qc_type"] or a["method"] != b["method"]:
        return False
    return not (a.get("matrix") and b.get("matrix") and a["matrix"] != b["matrix"])


def previous(all_runs, current):
    """The comparable blank just before `current` (by run date, run id, then
    injection: a second matrix blank in a run follows the first)."""
    def k(r):
        return (r["run_date"], r["batch_id"], r.get("injection") or u"")
    earlier = [r for r in all_runs if k(r) < k(current) and comparable(r, current)]
    return max(earlier, key=k) if earlier else None


def lots_of(ledger_rows, fm251=None):
    """Every lot the run used: the extraction's (ledger) and the calibration
    prep's prepared standards (FM-ENV-002), each once."""
    out, seen = [], set()
    for r in ledger_rows or []:
        lot = (r.get("lot") or u"").strip()
        if not lot or (r.get("kind"), lot) in seen:
            continue
        seen.add((r.get("kind"), lot))
        out.append({"kind": r.get("kind") or u"", "lot": lot, "name": r.get("item_name") or u"",
                    "role": r.get("role") or r.get("item_name") or u"", "stage": r.get("stage_name") or u""})
    for field, label in FM251_FIELDS:
        lot = ((fm251 or {}).get(field) or u"").strip()
        if lot and ("prepared_standard", lot) not in seen:
            seen.add(("prepared_standard", lot))
            out.append({"kind": u"prepared_standard", "lot": lot, "name": label, "role": label,
                        "stage": u"Calibration prep (FM-ENV-002)"})
    return out


def lot_diff(current, previous_lots):
    """Fold away what both runs used. `changed`: the same role or item with a
    different lot ({role, now, before}); `new`: lots this run used that the
    previous did not, for a role it did not have; `gone`: the reverse."""
    cur = dict(((l["kind"], l["lot"]), l) for l in current or [])
    prev = dict(((l["kind"], l["lot"]), l) for l in previous_lots or [])
    shared = [cur[k] for k in cur if k in prev]
    only_now = [cur[k] for k in cur if k not in prev]
    only_before = [prev[k] for k in prev if k not in cur]

    def slot(l):
        return (l["kind"], (l.get("role") or l.get("name") or u"").lower())
    before_by_slot = dict((slot(l), l) for l in only_before)
    changed, new = [], []
    for l in only_now:
        b = before_by_slot.pop(slot(l), None)
        if b is not None:
            changed.append({"role": l.get("role") or l.get("name"), "kind": l["kind"],
                            "now": l["lot"], "before": b["lot"], "name": l.get("name"),
                            "stage": l.get("stage")})
        else:
            new.append(l)
    gone = list(before_by_slot.values())
    key = lambda x: (x.get("kind") or u"", x.get("role") or x.get("name") or u"")   # noqa: E731
    return {"changed": sorted(changed, key=key), "new": sorted(new, key=key),
            "gone": sorted(gone, key=key), "shared": sorted(shared, key=key)}


def rise(current, prev):
    """[(analyte, now, before)] for analytes higher in this blank than in the
    previous one (a non-detect counts as 0), largest rise first. With no
    previous blank there is nothing to rise from."""
    out = []
    if not prev:
        return out
    for a, v in (current.get("values") or {}).items():
        if v is None:
            continue
        b = (prev.get("values") or {}).get(a)
        if float(v) > float(b or 0.0):
            out.append((a, float(v), None if b is None else float(b)))
    return sorted(out, key=lambda t: t[1] - (t[2] or 0.0), reverse=True)
