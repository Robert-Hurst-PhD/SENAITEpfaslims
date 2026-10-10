# -*- coding: utf-8 -*-
"""Method studies: the data a study is calculated from, and the calculation
per analyte.

The worker stores every injection's result per analyte in the QC database
(injection_results, its run in batches). A study draws its replicates from
there:

  mdl  spiked samples (LFBs at the study's spiking level) and method blanks
       of the method x matrix within the period (40 CFR 136 App. B Rev. 2
       §4(b), §4(e): the last 24 months)
  mrl  seven LFBs at the proposed MRL, from the chosen worksheets (§9.2.6)
  pa   four to seven LFBs near mid-calibration (§9.2.3 / §9.2.4)
  dl   seven or more LFBs near the DL over three days (§9.2.8.1)

A result is excluded only with a reason (App. B §2(b), §4(b): documented
gross failures). Python 2.7 and 3; the queries take a sqlite3 connection.
"""
from __future__ import absolute_import, unicode_literals

try:
    from senaite.pfas import method_studies as ms
    from senaite.pfas.analyte_reference import native_keyword_for
except ImportError:                    # tests: loaded by path
    import method_studies as ms
    from analyte_reference import native_keyword_for

KINDS = [
    ("mdl", u"Annual MDL (40 CFR 136 App. B Rev. 2)"),
    ("mrl", u"MRL confirmation (EPA 537.1 §9.2.6)"),
    ("pa", u"Precision and accuracy (EPA 537.1 §9.2.3, §9.2.4)"),
    ("dl", u"Detection limit (EPA 537.1 §9.2.8.1)"),
    ("pt", u"Proficiency test"),
    ("idc", u"Initial demonstration of capability (EPA 537.1 §9.2)"),
]
# what a PT provider says of each reported analyte
PT_VERDICTS = [(u"acceptable", u"Acceptable"), (u"not_acceptable", u"Not acceptable")]
KIND_LABELS = dict(KINDS)
# the method blank by the method's name for it (EPA 537.1 calls it LRB)
BLANK_ROLE = {"EPA_537_1": "LRB"}
MDL_MONTHS = 24          # App. B Rev. 2 §4(b), §4(e)


def blank_role(method_id):
    return BLANK_ROLE.get(method_id, "MB")


def injections(conn, method, roles, batches=None, since=None, until=None, matrix=None):
    """[{"injection", "batch", "date", "values": {keyword: value | None}}]
    for the method's injections of `roles`, oldest first. A summed analyte is
    its total (its lr- / br- peaks are not listed); None = not detected."""
    q = ("SELECT r.batch_id, r.injection_name, r.run_date, r.analyte, r.role, r.calc_conc, "
         "r.conc_qualifier, b.matrix FROM injection_results r LEFT JOIN batches b "
         "ON b.batch_id = r.batch_id WHERE r.method = ? AND r.qc_type IN (%s)"
         % ",".join("?" * len(roles)))
    args = [method] + list(roles)
    if batches:
        q += " AND r.batch_id IN (%s)" % ",".join("?" * len(batches))
        args += list(batches)
    if since:
        q += " AND r.run_date >= ?"
        args.append(since)
    if until:
        q += " AND r.run_date <= ?"
        args.append(until)
    out = {}
    for batch, inj, date, name, role, conc, qual, bmatrix in conn.execute(q, args):
        if matrix and (bmatrix or u"") != matrix:
            continue
        if role == "internal standard" or (name or u"").startswith((u"lr-", u"br-")):
            continue
        # keyed by run AND injection: imported exports re-use names, and one
        # key merged three runs' blanks into one
        key = u"%s/%s" % (batch or u"", inj)
        rec = out.setdefault(key, {"injection": inj, "key": key, "batch": batch,
                                   "date": date or u"", "values": {}})
        rec["values"][native_keyword_for(name)] = conc
    return sorted(out.values(), key=lambda r: (r["date"], r["injection"]))


def _kept(rows, exclusions, kw):
    """The rows of one analyte left after the study's exclusions."""
    gone = set((e.get("injection"), e.get("analyte")) for e in exclusions or [])
    # an exclusion names the row's key ("WS-1/LRB"); one recorded by bare
    # injection name before 2026-10-09 still applies to it
    return [r for r in rows
            if not any((ident, a) in gone for ident in (r.get("key"), r["injection"]) for a in (kw, u"*"))]


def analytes(rows):
    return sorted(set(k for r in rows for k in r["values"]))


def calculate(kind, spikes, blanks=None, fortified=None, exclusions=None, existing=None):
    """{keyword: result} per method_studies, one analyte at a time.
    fortified = {keyword: concentration} (or one value for all); existing =
    {keyword: MDL in force} (mdl only)."""
    out = {}
    for kw in analytes(spikes):
        rows = _kept(spikes, exclusions, kw)
        vals = [r["values"].get(kw) for r in rows]
        fort = fortified.get(kw) if isinstance(fortified, dict) else fortified
        if kind == "mdl":
            brows = _kept(blanks or [], exclusions, kw)
            out[kw] = ms.mdl_rev2([(v, r["date"], r["batch"]) for v, r in zip(vals, rows)],
                                  [r["values"].get(kw) for r in brows],
                                  existing=(existing or {}).get(kw))
        elif kind == "mrl":
            out[kw] = ms.mrl_confirmation(vals, fort) if fort else _no_fortified()
        elif kind == "pa":
            out[kw] = ms.precision_accuracy(vals, fort) if fort else _no_fortified()
        elif kind == "dl":
            out[kw] = ms.detection_limit([(v, r["date"]) for v, r in zip(vals, rows)])
    return out


def _no_fortified():
    return {"verdict": "not evaluated", "reason": u"no fortified concentration for this level"}


def applied_values(kind, results, fortified=None):
    """What an approved study writes to the method profile's Reporting
    Limits: an MDL study its MDLs; a passing MRL
    confirmation its fortified concentration as the RL. {keyword: {field:
    value}}; nothing for the other kinds."""
    out = {}
    for kw, res in sorted((results or {}).items()):
        # an MDL only where every App. B requirement was met (no notes) and
        # the replicates varied (identical results give s = 0: no MDL)
        if kind == "mdl" and res.get("verdict") == "calculated" and (res.get("mdl") or 0) > 1e-9:
            out[kw] = {"mdl": float(u"%.3g" % res["mdl"])}
        elif kind == "mrl" and res.get("verdict") == "pass":
            fort = fortified.get(kw) if isinstance(fortified, dict) else fortified
            if fort:
                out[kw] = {"rl": float(fort)}
    return out


# ── several spiking levels (2026-10-09: results per level) ─────────────

def calculate_levels(kind, spikes, blanks=None, fortified=None, exclusions=None, existing=None):
    """{level: {keyword: result}}: each spike row carries its "level" (the
    extraction batch member's label); `fortified` = {level: value or
    {keyword: value}}. Blanks are shared by every level."""
    out = {}
    for level in sorted(set(r.get("level") or u"" for r in spikes)):
        rows = [r for r in spikes if (r.get("level") or u"") == level]
        out[level] = calculate(kind, rows, blanks, (fortified or {}).get(level), exclusions, existing)
    return out


def applied_by_level(kind, results, fortified=None):
    """What approval writes, from per-level results. An MDL comes from ONE
    spiking level (App. B Rev. 2 §4(b): "only data with the same spiking
    level"); several levels apply nothing. A confirmed MRL: per analyte, the
    lowest level that passed (its fortified concentration as the RL)."""
    results = results or {}
    if kind == "mdl":
        if len(results) != 1:
            return {}
        (level, res), = results.items()
        return applied_values("mdl", res)
    if kind == "mrl":
        out = {}
        ranked = sorted(results.items(), key=lambda kv: _fort_of((fortified or {}).get(kv[0]), None) or 0)
        for level, res in ranked:
            for kw, vals in applied_values("mrl", res, (fortified or {}).get(level)).items():
                out.setdefault(kw, vals)
        return out
    return {}


def _fort_of(f, kw):
    if isinstance(f, dict):
        vals = [v for v in f.values() if v]
        return min(vals) if vals else None
    return f


# ── proficiency tests ───────────────────────────────────────────────────────

def pt_results(entries):
    """{keyword: {"reported", "assigned", "verdict"}} from the page's rows,
    keeping only analytes something was entered for."""
    out = {}
    for kw, e in sorted((entries or {}).items()):
        e = dict((k, (u"%s" % (v or u"")).strip()) for k, v in (e or {}).items())
        if any(e.get(k) for k in ("reported", "assigned", "verdict")):
            out[kw] = {"reported": e.get("reported", u""), "assigned": e.get("assigned", u""),
                       "verdict": e.get("verdict", u"")}
    return out


def pt_problems(pt, certificate_present):
    """What holds a PT study's approval: the provider's certificate ("store a passing certificate with each study"), the round,
    at least one analyte, and the provider's verdict on each."""
    pt = pt or {}
    out = []
    if not certificate_present:
        out.append(u"Attach the provider's certificate.")
    if not (pt.get("provider") or u"").strip() or not (pt.get("round") or u"").strip():
        out.append(u"State the provider and the round.")
    results = pt.get("results") or {}
    if not results:
        out.append(u"Enter the reported analytes.")
    valid = set(k for k, _l in PT_VERDICTS)
    missing = sorted(kw for kw, r in results.items() if r.get("verdict") not in valid)
    if missing:
        out.append(u"The provider's verdict is missing for %s." % u", ".join(missing))
    return out


def pt_verdict(pt):
    results = (pt or {}).get("results") or {}
    if not results:
        return u"not evaluated"
    return u"pass" if all(r.get("verdict") == u"acceptable" for r in results.values()) else u"fail"
