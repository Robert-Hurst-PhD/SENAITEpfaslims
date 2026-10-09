# -*- coding: utf-8 -*-
"""The certificate's surrogate / internal-standard sub-table.

surrogates and internal standards print as a separate
sub-table, with a note that this is quality control data used to account for
sample concentrations or verify recovery efficiencies. A surrogate shows its
% recovery, an internal standard its area as % of the calibration average;
each with the window and the status the worker's check decided (stored per
injection in injection_results, qc_schema migrations 10-18). The status is
never recomputed here: "no criterion" stays "No criterion set", never a pass.

Which injections: the NEAT injection only -- the one the
worker binds to the sample (its name is the sample's Client Sample ID;
pipeline.run_pipeline), else the sample's 7-digit StarLIMS id, never a
dilution.

    select(rows, client_sid)            -> the sample's neat injection rows
    build(rows, client_sid, n, rule, role_labels)
        -> {"state": "none" | "legacy" | "unjudged" | "rows", "rows": [...],
            "injections": n}

    none      no injection of this sample in its worksheets' runs
    legacy    the run was stored before the verdicts were (no std_role)
    unrounded the run was judged before checks used the rounded value
              (: no judged_rule recorded)
    rule_changed  judged with another rule / precision than this
              certificate prints with
    unjudged  the run carries its labelled standards, but no check judged
              one for this injection (e.g. no recovery reported)

Pure: Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

try:
    from senaite.pfas.rounding import PCT_PLACES, judged_rule, round_places
    from senaite.pfas.report_format import QC_NOTE
except ImportError:                                         # loaded by path (tests)
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from rounding import PCT_PLACES, judged_rule, round_places
    from report_format import QC_NOTE

DEFAULT_NOTE = QC_NOTE
NO_DATA = "No surrogate or internal-standard results are recorded for this sample."
# LEGACY / UNJUDGED are seen by the lab only (preview): publishing is refused
LEGACY = ("This sample's run was processed before surrogate and internal-standard "
          "verdicts were kept; reprocess the run to show them. Not publishable until then.")
UNROUNDED = ("This sample's run was judged before every check used the rounded value; "
             "reprocess the run. Not publishable until then.")
RULE_CHANGED = ("This sample's run was judged with a rounding rule or precision the "
                "issued reporting template has since changed; reprocess the run. Not "
                "publishable until then.")
UNJUDGED = ("No surrogate recovery or internal-standard response was judged for this "
            "sample's injection. Not publishable until the run is reprocessed with them.")

# a sample that was run but whose verdicts are missing is not published
# until the run is reprocessed (guards.QCStandardsGuard);
# the designed certificate refuses it too (coa_document.data)
BLOCKS_PUBLISHING = ("legacy", "unrounded", "rule_changed", "unjudged")

# (column key, title, example)
COLUMNS = [
    ("injection", "Injection", "DEMO-0001"),
    ("standard", "Labelled standard", "13C2-PFDA"),
    ("role", "Role", "Surrogate (SUR)"),
    ("measure", "Measured as", "% recovery"),
    ("value", "Value (%)", "98.4"),
    ("window", "Window (%)", "70-130"),
    ("status", "Status", "Within"),
]
REQUIRED = ("standard", "role", "value", "window", "status")

MEASURES = {"surrogate": "% recovery", "injection_is": "% of calibration average"}
STATUS = {"within": "Within", "outside": "Outside", "no criterion": "No criterion set"}
_ROLE_ORDER = {"surrogate": 0, "injection_is": 1}


def _g(row, key):
    v = row.get(key)
    return v if v not in ("",) else None


def _limit(v):
    """A window limit as the method states it (never rounded): 70.0 -> 70."""
    if v is None:
        return None
    return ("%f" % float(v)).rstrip("0").rstrip(".")


def select(rows, client_sid):
    """The sample's NEAT injection rows: injection name == Client Sample ID;
    failing that, the StarLIMS id the worker parsed (sample_id) on a field
    sample's injection. Dilutions never."""
    sid = (client_sid or "").strip()
    if not sid:
        return []
    rows = [r for r in rows or [] if (r.get("qc_type") or "") != "Dilution"]
    by_name = [r for r in rows if (r.get("injection_name") or "").strip() == sid]
    if by_name:
        return by_name
    return [r for r in rows if (r.get("sample_id") or "").strip() == sid
            and (r.get("qc_type") or "") == "Sample"]


def _entry(r, n, rule, labels):
    role = r.get("std_role") or ""
    if role == "surrogate":
        value, lo, hi, status = (_g(r, "recovery"), _g(r, "rec_min"), _g(r, "rec_max"),
                                 r.get("rec_status") or "")
        judged = _g(r, "rec_judged")
        guidance = bool(r.get("rec_guidance"))
    elif role == "injection_is":
        value, lo, hi, status = (_g(r, "resp_pct"), _g(r, "resp_min"), _g(r, "resp_max"),
                                 r.get("resp_status") or "")
        judged = _g(r, "resp_judged")
        guidance = False
    else:
        return None
    if value is None or not status:
        return None                 # the check did not judge it (e.g. not reported)
    text = STATUS.get(status, status)
    if guidance and status == "outside":
        text = "Outside (guidance only)"
    window = ("%s-%s" % (_limit(lo), _limit(hi))) if lo is not None and hi is not None else "—"
    return {"injection": r.get("injection_name") or "", "standard": r.get("analyte") or "",
            "role": labels.get(role, role), "measure": MEASURES[role],
            # the value the check JUDGED (a whole percent);
            # a run stored before it was kept is rounded by the same rule
            "value": round_places(judged if judged is not None else value, PCT_PLACES, rule) or "",
            "window": window, "status": text,
            "flag": status == "outside", "_order": (_ROLE_ORDER[role], r.get("analyte") or "")}


def build(rows, client_sid, n=3, rule="epa", role_labels=None):
    picked = select(rows, client_sid)
    if not picked:
        return {"state": "none", "rows": [], "injections": 0}
    labels = dict(role_labels or ())
    if not any(r.get("std_role") for r in picked):
        # the run is there but was stored before the verdicts were: not
        # "nothing recorded"
        return {"state": "legacy", "rows": [], "injections": 0}
    # judged as this certificate prints, or not at all
    rules = set(r.get("judged_rule") or "" for r in picked)
    if "" in rules:
        return {"state": "unrounded", "rows": [], "injections": 0}
    if rules != set([judged_rule(rule, n)]):
        return {"state": "rule_changed", "rows": [], "injections": 0, "judged": sorted(rules)}
    out = [e for e in (_entry(r, n, rule, labels) for r in picked) if e is not None]
    if not out:
        return {"state": "unjudged", "rows": [], "injections": 0}
    out.sort(key=lambda e: (e["injection"], e["_order"]))
    for e in out:
        del e["_order"]
    return {"state": "rows", "rows": out, "injections": len(set(e["injection"] for e in out))}


def note(fmt, state):
    """The text under the sub-table's title: the lab's note, and why the
    table is empty when it is."""
    text = (fmt or {}).get("coa_qc_note") or DEFAULT_NOTE
    if state == "none":
        return "%s %s" % (text, NO_DATA)
    if state == "legacy":
        return "%s %s" % (text, LEGACY)
    if state == "unjudged":
        return "%s %s" % (text, UNJUDGED)
    if state == "unrounded":
        return "%s %s" % (text, UNROUNDED)
    if state == "rule_changed":
        return "%s %s" % (text, RULE_CHANGED)
    return text
