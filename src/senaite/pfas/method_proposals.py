# -*- coding: utf-8 -*-
"""A run's processing change proposed as the method's own setting.

A manager proposes a processing change of a run (raw_review: one trace's
change applied to every injection) as the method's own, for that compound
and trace. The Integration settings are per method and compound, with no
matrix, so a proposal is too. It waits on the method's page and the profile
is unchanged until a different manager or QA officer countersigns it; the
countersign saves it into the compound's Integration entry

    integration.analytes[<keyword>].processing =
        {"quant": record, "quant_transition": "<q1> > <q3>" (the quantifier
         it was made on; absent from an entry saved before, which counts as
         made on the quantifier it has), "quals": {"<q1> > <q3>": record}}

(Config History as any save) and issues the sub revision, whose record names
the run and the change. A smoothing change ({"kind": "smoothing", "points":
n}) is the compound's, of no one trace: its proposal's transition is None,
and countersigning it sets the compound's own smoothing,
integration.analytes[<keyword>].smooth_points = n. The maker may withdraw it, the countersigner refuse
it, each with a reason.

    portal annotation KEY = {method_id: [proposal]}, a proposal
        {"id": "MP<n>", "analyte", "transition" (None for the quantifier),
         "record" (raw_review.processing_of), "source": {"worksheet",
         "batch_id", "change"}, "proposed_by", "proposed_at",
         "state": "pending" | "applied" | "withdrawn" | "refused",
         "decided_by", "decided_at", "reason", "revision": label or None}

The worker applies a method's entry to every trace its run's own processing
file has no change for, through the same path (with_method_processing). An
entry with nothing in it is no setting: the fingerprint, the snapshot and
the worker's revision leave it out (without_empty_processing).

Pure functions + a thin storage shell. Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import copy
import json

KEY = "senaite.pfas.method_proposals"
PENDING, APPLIED, WITHDRAWN, REFUSED = "pending", "applied", "withdrawn", "refused"

ALREADY_WAITING = u"A change to %s is already waiting on the method's page."
NOT_THE_MAKER = u"A different manager or QA officer countersigns this change."
NO_RIGHT = u"A manager or QA officer decides this change."
ONLY_THE_MAKER = u"Only the person who proposed this change withdraws it."
GIVE_REASON = u"Give the reason."
NOT_WAITING = u"This change is no longer waiting."
NO_SUCH = u"There is no such proposed change."
UNISSUED = u"The method has changes not yet issued: issue them first."
NOT_SUB = u"Countersigning would issue a major revision: issue the method's revision first."
NO_TRANSITION = u"%s has no transition on the method."
NO_SUCH_TRANSITION = u"%s has no transition %s on the method."
NOT_SINGLE = u"%s is not a single peak on the method."


def transition_label(q):
    """A transition as the run's traces name it: "413.0 > 369.0". The
    worker names its traces with this one rule (raw_run._label)."""
    return u"%.1f > %.1f" % (float(q[0]), float(q[1]))


_label = transition_label


def is_smoothing(record):
    """True for a smoothing change: the compound's, of no one trace."""
    return isinstance(record, dict) and record.get("kind") == u"smoothing"


def trace_text(analyte, transition, record=None):
    """"PFOA, quantifier", "PFOA, 413.0 > 169.0", or for a smoothing
    change "PFOA, smoothing"."""
    if is_smoothing(record):
        return u"%s, smoothing" % analyte
    return u"%s, %s" % (analyte, transition or u"quantifier")


def waiting_key(analyte, transition, record=None):
    """What one waiting proposal holds the place of: a trace's change,
    (analyte, transition or None), or the compound's smoothing, apart from
    its quantifier's change."""
    if is_smoothing(record):
        return (analyte, None, u"smoothing")
    return (analyte, transition or None)


def empty_processing(entry):
    """True when a compound's processing entry holds no change."""
    return not (isinstance(entry, dict) and (entry.get("quant") or entry.get("quals")))


def without_empty_processing(rows):
    """A copy of the Integration rows ({keyword: row}) with every empty
    processing entry left out: an empty entry is no setting."""
    out = {}
    for kw, row in (rows or {}).items():
        if isinstance(row, dict) and "processing" in row and empty_processing(row["processing"]):
            row = dict(row)
            row.pop("processing")
        out[kw] = row
    return out


# ── the proposals (pure) ────────────────────────────────────────────────────

def _proposals(data, method_id):
    return (data or {}).get(method_id) or []


def pending(data, method_id):
    """The method's proposals still waiting, in the order made."""
    return [p for p in _proposals(data, method_id) if p.get("state") == PENDING]


def propose(data, method_id, analyte, transition, record, source, who, when):
    """A new data dict with the proposal added. `record` is the run's
    processing change (raw_review.processing_of refuses one it cannot
    read). A second waiting proposal for the same trace is refused."""
    from senaite.pfas import raw_review
    clean = raw_review.processing_of(record)
    # a smoothing change is the compound's, of no one trace
    transition = None if is_smoothing(clean) else (transition or None)
    mine = waiting_key(analyte, transition, clean)
    if any(waiting_key(p["analyte"], p.get("transition"), p.get("record")) == mine
           for p in pending(data, method_id)):
        raise ValueError(ALREADY_WAITING % trace_text(analyte, transition, clean))
    out = copy.deepcopy(data or {})
    recs = out.setdefault(method_id, [])
    n = max([int(p["id"][2:]) for p in recs if p["id"][2:].isdigit()] or [0]) + 1
    recs.append({"id": u"MP%d" % n, "analyte": analyte, "transition": transition, "record": clean,
                 "source": dict(source or {}), "proposed_by": who, "proposed_at": when, "state": PENDING,
                 "decided_by": None, "decided_at": None, "reason": None, "revision": None})
    return out


def _waiting(data, method_id, pid):
    p = next((r for r in _proposals(data, method_id) if r["id"] == pid), None)
    if p is None:
        raise ValueError(NO_SUCH)
    if p.get("state") != PENDING:
        raise ValueError(NOT_WAITING)
    return p


def _reason(reason):
    reason = (reason or u"").strip()
    if not reason:
        raise ValueError(GIVE_REASON)
    return reason


def _decide(p, who, rights):
    """A countersign or a refusal: a manager's role or the QA approver sign
    right, and never the person who proposed it."""
    rights = rights or {}
    if not (rights.get("manager") or rights.get("qa")):
        raise ValueError(NO_RIGHT)
    if p.get("proposed_by") == who:
        raise ValueError(NOT_THE_MAKER)


def countersign(data, method_id, pid, who, when, rights):
    """The proposal countersigned, in `data`: its state "applied". The
    caller saves the change and issues the revision in the same transaction
    and sets the proposal's "revision"."""
    p = _waiting(data, method_id, pid)
    _decide(p, who, rights)
    p.update(state=APPLIED, decided_by=who, decided_at=when)
    return p


def refuse(data, method_id, pid, who, when, reason, rights):
    """The proposal refused by one who may countersign it, with a reason."""
    p = _waiting(data, method_id, pid)
    _decide(p, who, rights)
    p.update(state=REFUSED, decided_by=who, decided_at=when, reason=_reason(reason))
    return p


def withdraw(data, method_id, pid, who, when, reason):
    """The proposal withdrawn by the person who made it, with a reason."""
    p = _waiting(data, method_id, pid)
    if p.get("proposed_by") != who:
        raise ValueError(ONLY_THE_MAKER)
    p.update(state=WITHDRAWN, decided_by=who, decided_at=when, reason=_reason(reason))
    return p


def revision_reason(source):
    """The reason the issued revision gives: the run and its change."""
    source = source or {}
    return u"From %s, processing change %s" % (source.get("worksheet") or u"", source.get("change") or u"")


# ── the method's entry ──────────────────────────────────────────────────────

def _row(profile, analyte):
    rows = ((profile or {}).get("integration") or {}).get("analytes") or {}
    row = rows.get(analyte)
    return row if isinstance(row, dict) else None


def _qualifier(row, transition):
    """The trace's transition as the method's entry keys it: None for the
    quantifier (named by its own transition too), else the qualifier's."""
    if transition in (None, u"") or (row.get("quant") and transition == _label(row["quant"])):
        return None
    return transition


def _structure(profile, analyte, row, qual, quant_label=None):
    """What in the compound's own row keeps a change of this trace from
    being applied, as (key, transition) or None: no quantifier ("no_quant"),
    integrated as its isomer peaks ("isomers"), a pair or a summed peak
    ("pair", "summed": no one apex places the edges, and the worker refuses
    a run's own change there), or a transition it no longer has
    ("transition"): `qual` a qualifier not among its qualifiers, or, for
    the quantifier, `quant_label` (the transition a saved change was made
    on) not its quantifier. Proposing and applying judge by this one rule."""
    from senaite.pfas import isomers
    if not row or not row.get("quant"):
        return ("no_quant", None)
    if isomers.peaks_of(profile, analyte):
        return ("isomers", None)
    mode = row.get("mode") or "single"
    if mode == "pair":
        return ("pair", None)
    if mode != "single" or analyte in isomers.branched_peaks(profile):
        return ("summed", None)
    if qual is not None and qual not in [_label(q) for q in row.get("quals") or []]:
        return ("transition", qual)
    if qual is None and quant_label and quant_label != _label(row["quant"]):
        return ("transition", quant_label)
    return None


ALREADY_HELD = u"The method already holds this change."
ISOMERS_TEXT = u"%s is integrated as its isomer peaks."


def holds(profile, analyte, transition, record):
    """True when the compound's saved entry already holds `record` for this
    trace, on the transition it now has."""
    from senaite.pfas import raw_review
    row = _row(profile, analyte)
    if not row or not row.get("quant"):
        return False
    if is_smoothing(record):
        # the compound's own smoothing, in points
        try:
            return int(row.get("smooth_points")) == int(record.get("points"))
        except (TypeError, ValueError):
            return False
    entry = row.get("processing") or {}
    qual = _qualifier(row, transition)
    if qual is None:
        saved, label = entry.get("quant"), entry.get("quant_transition")
        if label and label != _label(row["quant"]):
            return False
    else:
        saved = (entry.get("quals") or {}).get(qual)
    try:
        return bool(saved) and raw_review.processing_of(saved) == raw_review.processing_of(record)
    except ValueError:
        return False


def applies(profile, analyte, transition, record=None):
    """Why the method cannot take a change of this trace, or None: what
    keeps it from being applied (_structure: the worker would leave it out
    once saved), or, given the change's `record`, the method holding it
    already."""
    row = _row(profile, analyte)
    if is_smoothing(record):
        transition = None                       # the compound's, of no one trace
    found = _structure(profile, analyte, row, _qualifier(row, transition) if row else None)
    if found:
        key, label = found
        return {"no_quant": NO_TRANSITION % analyte, "isomers": ISOMERS_TEXT % analyte,
                "pair": NOT_SINGLE % analyte, "summed": NOT_SINGLE % analyte,
                "transition": NO_SUCH_TRANSITION % (analyte, label)}[key]
    if record is not None and holds(profile, analyte, transition, record):
        return ALREADY_HELD
    return None


def with_change(profile, proposal):
    """A copy of `profile` with the proposal's change in its compound's
    processing entry, merged with what the entry holds; ValueError when
    the method cannot take it (applies)."""
    why = applies(profile, proposal["analyte"], proposal.get("transition"), proposal["record"])
    if why:
        raise ValueError(why)
    out = copy.deepcopy(profile)
    row = out["integration"]["analytes"][proposal["analyte"]]
    if is_smoothing(proposal["record"]):
        # the compound's own smoothing: its Mid from now on
        row["smooth_points"] = int(proposal["record"]["points"])
        return out
    entry = dict(row.get("processing") or {})
    qual = _qualifier(row, proposal.get("transition"))
    if qual is None:
        entry["quant"] = copy.deepcopy(proposal["record"])
        # the transition it was made on: a quantifier changed since is
        # another trace, and the change is then left out (_structure)
        entry["quant_transition"] = _label(row["quant"])
    else:
        quals = dict(entry.get("quals") or {})
        quals[qual] = copy.deepcopy(proposal["record"])
        entry["quals"] = quals
    row["processing"] = entry
    return out


# why a saved entry no longer fits its compound: the worker leaves it out,
# and Data Review says so
MISFIT_TEXT = u"%s: the method's saved processing no longer fits, %s. Remove it on the method's page."
NO_QUANT = u"it has no quantifier transition"
ISOMER_PEAKS = u"it is integrated as its isomer peaks"
NOW_PAIR = u"now a pair"
NOW_SUMMED = u"now summed"
NO_LONGER_TRANSITION = u"%s is no longer a transition"
UNREADABLE = u"it cannot be read"
FIT_OUTSIDE = u"the fit's span lies outside the window"


def saved_traces(entry):
    """[(transition or None, record)] of a saved entry, quantifier first."""
    out = [(None, entry["quant"])] if entry.get("quant") else []
    quals = entry.get("quals") if isinstance(entry.get("quals"), dict) else {}
    return out + sorted(quals.items())


def _misfit(profile, analyte, row, transition, record, quant_label=None):
    """Why the compound can no longer take a saved change of this trace, or
    None: what keeps it from being applied (_structure; for the quantifier
    `quant_label`, the transition it was saved on, a change saved without
    one counting as made on the quantifier it has), a record it cannot
    read, or a fit's span no longer in the compound's window."""
    from senaite.pfas import raw_review, rt_window
    if is_smoothing(record):
        transition, quant_label = None, None    # the compound's, of no one trace
    found = _structure(profile, analyte, row, transition, quant_label)
    if found:
        key, label = found
        return {"no_quant": NO_QUANT, "isomers": ISOMER_PEAKS, "pair": NOW_PAIR, "summed": NOW_SUMMED,
                "transition": NO_LONGER_TRANSITION % label}[key]
    try:
        clean = raw_review.processing_of(record)
    except ValueError:
        return UNREADABLE
    if clean["kind"] == "fit":
        try:
            intg = (profile or {}).get("integration") or {}
            width = rt_window.half_width(row.get("rt"), row.get("window"), rt_window.tolerance(intg))[0]
        except (TypeError, ValueError):
            width = None
        if width is not None and (clean["start_offset"] < -width or clean["end_offset"] > width):
            return FIT_OUTSIDE
    return None


def misfits(profile):
    """[(analyte, transition or None, why)] of the saved processing changes
    the method's compounds can no longer take, by compound."""
    rows = ((profile or {}).get("integration") or {}).get("analytes") or {}
    out = []
    for kw in sorted(rows):
        row = rows[kw]
        if not isinstance(row, dict) or empty_processing(row.get("processing")):
            continue
        entry = row["processing"]
        for transition, record in saved_traces(entry):
            why = _misfit(profile, kw, row, transition, record, entry.get("quant_transition"))
            if why:
                out.append((kw, transition, why))
    return out


def misfit_text(analyte, why):
    return MISFIT_TEXT % (analyte, why)


# a saved fit the compound can take while the method's fit limit is unset:
# the worker skips it on every injection (raw_review.FIT_NO_LIMIT_TEXT)
NO_FIT_LIMIT_TEXT = (u"%s: the method's saved fit is skipped on every injection until the fit limit is set "
                     u"under Integration, on the method's Run & reporting tab.")


def unlimited_fits(profile):
    """[(analyte, transition or None)] of the saved fits the method's
    compounds can take (fitting_entry) while its fit limit is unset
    (raw_edit.fit_limit): each is skipped on every injection."""
    from senaite.pfas.raw_edit import fit_limit
    intg = (profile or {}).get("integration") or {}
    if fit_limit(intg) is not None:
        return []
    out = []
    for kw in sorted(intg.get("analytes") or {}):
        for transition, record in saved_traces(fitting_entry(profile, kw)):
            if isinstance(record, dict) and record.get("kind") == "fit":
                out.append((kw, transition))
    return out


def misfit_lines(profile):
    """[(text, the method editor's section id)] of what Data Review says of
    the method's saved processing: one line per compound and reason it can
    no longer take (misfits, in the compounds' Integration rows,
    "intg_an"), then one per compound whose saved fit waits on the fit
    limit (unlimited_fits, in the Integration settings, "intg"). The page
    opens the pane that holds the section (site_search.pane_for)."""
    out = []
    for analyte, _transition, why in misfits(profile):
        line = (misfit_text(analyte, why), u"intg_an")
        if line not in out:
            out.append(line)
    for analyte, _transition in unlimited_fits(profile):
        line = (NO_FIT_LIMIT_TEXT % analyte, u"intg")
        if line not in out:
            out.append(line)
    return out


def fitting_entry(profile, analyte):
    """The compound's saved entry without the changes it can no longer take
    (misfits): what the worker applies. {} for none."""
    row = (((profile or {}).get("integration") or {}).get("analytes") or {}).get(analyte)
    if not isinstance(row, dict) or empty_processing(row.get("processing")):
        return {}
    out, entry = {}, row["processing"]
    for transition, record in saved_traces(entry):
        if _misfit(profile, analyte, row, transition, record, entry.get("quant_transition")):
            continue
        if transition is None:
            out["quant"] = record
        else:
            out.setdefault("quals", {})[transition] = record
    return out


def without_entry(profile, analyte, transition):
    """A copy of `profile` with one saved change taken out of the compound's
    entry (Remove on the method's page); ValueError when it holds none."""
    out = copy.deepcopy(profile)
    row = (((out.get("integration") or {}).get("analytes") or {}).get(analyte)) or {}
    entry = dict(row.get("processing") or {}) if isinstance(row, dict) else {}
    if transition is None:
        if not entry.get("quant"):
            raise ValueError(NO_SAVED % trace_text(analyte, transition))
        entry.pop("quant")
        entry.pop("quant_transition", None)
    else:
        quals = dict(entry.get("quals") or {})
        if transition not in quals:
            raise ValueError(NO_SAVED % trace_text(analyte, transition))
        quals.pop(transition)
        if quals:
            entry["quals"] = quals
        else:
            entry.pop("quals", None)
    row["processing"] = entry
    return out


NO_SAVED = u"%s holds no saved processing."


def with_method_processing(proc, entries):
    """(the run's processing file dict with the method's entries added
    where the run holds no change of the trace, the keys taken from the
    method). `proc` is raw_review.read_processing's whole dict, never
    changed; `entries` {keyword: processing entry}. The run's own change of
    a trace wins."""
    from senaite.pfas import raw_review
    method = {}
    for analyte, entry in sorted((entries or {}).items()):
        if empty_processing(entry):
            continue
        if entry.get("quant"):
            method[raw_review.processing_key(analyte, None, None)] = entry["quant"]
        for label, record in sorted((entry.get("quals") or {}).items()):
            method[raw_review.processing_key(analyte, label, None)] = record
    # a run file of another version or shape is left as it is, for the
    # worker to refuse naming it: the method's entries never mend it
    if proc and (proc.get("version") != raw_review.PROCESSING_VERSION or not isinstance(proc.get("traces"), dict)):
        return proc, set()
    own = (proc or {}).get("traces") or {}
    taken = set(k for k in method if k not in own)
    if not taken:
        return proc, set()
    traces = dict(own)
    traces.update((k, method[k]) for k in taken)
    # the run's smoothing changes are kept as they are
    return raw_review.processing_dict(traces, (proc or {}).get("smoothing")), taken


# ── storage (Zope) ─────────────────────────────────────────────────────────

def _ann(portal):
    from zope.annotation.interfaces import IAnnotations
    return IAnnotations(portal)


def load(portal):
    """Every method's proposals: {method_id: [proposal]}."""
    raw = _ann(portal).get(KEY)
    return json.loads(raw) if raw else {}


def save(portal, data):
    _ann(portal)[KEY] = json.dumps(data, sort_keys=True)
