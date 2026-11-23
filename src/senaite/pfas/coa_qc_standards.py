# -*- coding: utf-8 -*-
"""The certificate's surrogate / internal-standard sub-table.

Surrogates and internal standards print as a separate
sub-table, with a note that this is quality control data used to account for
sample concentrations or verify recovery efficiencies. A surrogate shows its
% recovery, an internal standard its area as % of the calibration average;
each with the window and the status the worker's check decided (stored per
injection in injection_results). The status is never recomputed here: "no
criterion" stays "No criterion set", never a pass.

Which injections: the NEAT injection only -- the one the
worker binds to the sample (the injection name the LIMS issued for it on
the worksheet, else its Client Sample ID; pipeline.run_pipeline), else the
sample's 7-digit StarLIMS id, never a dilution. `names` is
sample_names(issued, client_sid), or a Client Sample ID alone.

    sample_names(issued, client_sid)    -> what the sample's injections go by
    select(rows, names)                 -> the sample's neat injection rows
    build(rows, names, n, rule, role_labels, places)
        -> {"state": "none" | "legacy" | "unjudged" | "rows", "rows": [...],
            "injections": n}

    A surrogate's recovery prints as the check judged it, at the method's
    decimal places for recoveries (method_engine.recovery_decimals; a whole
    percent by default). An internal standard's response is not a recovery:
    it prints as judged, a whole percent.

    none      no injection of this sample in its worksheets' runs
    legacy    the run was stored before the verdicts were (no std_role)
    unrounded the run was judged before checks used the rounded value
              (no judged_rule recorded)
    rule_changed  judged with another rule / precision, or recoveries at
              other decimal places, than this certificate prints with
    unjudged  the run carries its labelled standards, but no check judged
              one for this injection (e.g. no recovery reported)

Pure: Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

from senaite.pfas.rounding import PCT_PLACES, judged_rule, recovery_text, round_places
from senaite.pfas.report_format import QC_NOTE

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
    ("standard", "Isotope standard", "13C2-PFDA"),
    ("role", "Role", "Surrogate (SUR)"),
    ("measure", "Measured as", "% recovery"),
    ("value", "Value (%)", "98.4"),
    ("window", "Window (%)", "70-130"),
    ("status", "Status", "Within"),
]
REQUIRED = ("standard", "role", "value", "window", "status")

# what a listed value is: the check that judged it (_verdict)
MEASURES = {"recovery": "% recovery", "response": "% of calibration average"}
# a missing window and a class the lab chose not to assess are different facts
STATUS = {"within": "Within", "outside": "Outside", "no criterion": "No criterion set",
          "not assessed": "Not assessed"}
_ROLE_ORDER = {"surrogate": 0, "injection_is": 1}
# a value its box judged in the state Evaluate (a surrogate's recovery, an
# internal standard's response) prints the plain result of the comparison,
# Within or Outside, with no flag and no qualifier: every Evaluate box prints
# the same way, and only an Enforced failure flags


def _g(row, key):
    v = row.get(key)
    return v if v not in ("",) else None


def _limit(v):
    """A window limit as the method states it (never rounded): 70.0 -> 70."""
    if v is None:
        return None
    return ("%f" % float(v)).rstrip("0").rstrip(".")


def _clean(name):
    return (name.decode("utf-8") if isinstance(name, bytes) else (name or "")).strip()


def sample_names(issued, client_sid):
    """What a sample's injections go by: {"issued": the injection names the
    LIMS issued for it (one per worksheet it was run on), "client": its
    Client Sample ID}."""
    out = []
    for n in issued or []:
        n = _clean(n)
        if n and n not in out:
            out.append(n)
    return {"issued": out, "client": _clean(client_sid)}


def _names(names):
    """(issued names, client sample id) from `names`: sample_names' dict, or
    one name (a Client Sample ID, as a run named by the client's id)."""
    if isinstance(names, dict):
        found = sample_names(names.get("issued"), names.get("client"))
    else:
        found = sample_names([], names)
    return found["issued"], found["client"]


def lookup(names):
    """Every name to read the rows of `names` by: the issued names, then the
    Client Sample ID."""
    issued, client = _names(names)
    return issued + ([client] if client and client not in issued else [])


def select(rows, names):
    """The sample's NEAT injection rows: those under every name the LIMS
    issued for it (one per worksheet it was run on; the worker bound its
    results by them); when the runs hold none of them, those named by its
    Client Sample ID, failing that the StarLIMS id the worker parsed
    (sample_id) on a field sample's injection. Dilutions never. `names` is
    sample_names' dict, or a Client Sample ID."""
    issued, client = _names(names)
    rows = [r for r in rows or [] if (r.get("qc_type") or "") != "Dilution"]
    if issued:
        by_issued = [r for r in rows if (r.get("injection_name") or "").strip() in issued]
        if by_issued:
            return by_issued
    if not client:
        return []
    by_name = [r for r in rows if (r.get("injection_name") or "").strip() == client]
    if by_name:
        return by_name
    return [r for r in rows if (r.get("sample_id") or "").strip() == client
            and (r.get("qc_type") or "") == "Sample"]


def _verdict(r):
    """(measure, value, lo, hi, status, judged, evaluate) of the check that
    judged the standard, or None. A surrogate is listed by its recovery;
    one whose run reports no recovery (an isotope-dilution standard read
    from a raw run) by its response against the calibration average, which
    the worker judges for every labelled standard. An internal standard is
    listed by its response."""
    role = r.get("std_role") or ""
    if role not in _ROLE_ORDER:
        return None
    if role == "surrogate":
        value, status = _g(r, "recovery"), r.get("rec_status") or ""
        if value is not None and status:
            return ("recovery", value, _g(r, "rec_min"), _g(r, "rec_max"), status,
                    _g(r, "rec_judged"), bool(r.get("rec_guidance")))
    value, status = _g(r, "resp_pct"), r.get("resp_status") or ""
    if value is not None and status:
        # an internal standard's response judged in Evaluate: the worker
        # files its miss advisory
        return ("response", value, _g(r, "resp_min"), _g(r, "resp_max"), status,
                _g(r, "resp_judged"), bool(r.get("advisory")))
    return None                     # no check judged it (e.g. not reported)


def _entry(r, n, rule, labels, places=0):
    role = r.get("std_role") or ""
    found = _verdict(r)
    if found is None:
        return None
    measure, value, lo, hi, status, judged, guidance = found
    text = STATUS.get(status, status)
    evaluate = guidance and status in ("within", "outside")
    window = ("%s-%s" % (_limit(lo), _limit(hi))) if lo is not None and hi is not None else "—"
    return {"injection": r.get("injection_name") or "", "standard": r.get("analyte") or "",
            "role": labels.get(role, role), "measure": MEASURES[measure],
            # the value the check JUDGED; a run stored before it was
            # kept is rounded by the same rule
            "value": _shown(measure, value, judged, rule, places),
            "window": window, "status": text,
            "flag": status == "outside" and not evaluate, "_order": (_ROLE_ORDER[role], r.get("analyte") or "")}


def _shown(measure, value, judged, rule, places):
    """The printed value: what the check judged (a whole percent), or a
    recovery to the method's places when it sets more -- the value the
    check judged at those places, since a run judged at other places is
    refused (rule_changed). A response is never a recovery."""
    if measure == "recovery" and places and places > PCT_PLACES:
        return recovery_text(value, places, rule) or ""
    return round_places(judged if judged is not None else value, PCT_PLACES, rule) or ""


def build(rows, names, n=3, rule="epa", role_labels=None, places=0):
    picked = select(rows, names)
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
    if rules != set([judged_rule(rule, n, places)]):
        return {"state": "rule_changed", "rows": [], "injections": 0, "judged": sorted(rules)}
    out = [e for e in (_entry(r, n, rule, labels, places) for r in picked) if e is not None]
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
