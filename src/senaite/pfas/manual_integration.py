# -*- coding: utf-8 -*-
"""Manual integration: detection, reasons and records.

When the import captures a manual integration, or the
instrument report shows one, each must be justified from a list of reasons
and signed (analyst, then reviewer), and the report's before / after pages
stamped with the justification. The documentation follows a state laboratory accreditation programme's
manual-integration technical assistance document (2016) §5.2 and a state
environmental agency's manual-integration policy (2010).

    is_manual(raw, markers)   the ONE decision, also made by the pipeline
                              (pfas_pipeline loads this file): with markers,
                              a cell holding any of them; without, any cell
                              that is not blank / a "no"
    SEED_REASONS              the starting reason list (lab-editable)
    IMPROPER                  practices that are never a reason

The worksheet's records (a dict, stored on the worksheet):

    {"report_fp": sha256 of the report the pages refer to,
     "report_file": its file name (the report under review is pinned),
     "heading_scan": {"fp", "pages", "found", "by", "at"} | None   the
                  report's pages carrying the lab's heading, recorded for that
                  report: as typed (pages) and as the viewer found them (found),
     "dismissed": {"<page>": {"reason", "by", "at", "reviewer"}}   heading
                  pages that are not a manual integration, with why,
     "records": [{"id", "injection", "analyte", "source", "qc_type",
                  "before_page", "after_page", "reason_id", "reason", "detail",
                  "analyst": {"userid", "name", "at"} | None,
                  "reviewer": {...} | None}],
     "none_in_report": {"userid", "name", "at"} | None,
     "history": [{"at", "by", "id", "action", "changes"}],   append-only
     "stamped": {"file", "fp", "of", "at", "by"} | None,
     "raw_changes": [{"id", "injection", "analyte", "transition", "qc_type",
                  "kind", "before", "after", "by", "at", "dropped",
                  "reason_id", "reason", "detail",
                  "analyst": {"userid", "name", "initials", "at", "fp"} | None,
                  "verifier": {"userid", "name", "at", "fp"} | None}]}

    merge_detected(state, rows, who, when)   add the export's manual integrations
    update(state, id, fields, who, when)     edit; a real change clears signatures
    sign(state, id, role, who, when)         analyst, then a DIFFERENT reviewer
    rebind_report(state, fp, who, when)      a new report clears pages / signatures
    record_scan(state, fp, pages, who, when) the report's heading pages
    dismiss(state, page, reason, who, when)  a heading page that is not one
    countersign(state, kind, who, when)      a DIFFERENT person confirms a
                                             dismissal, "none", or a typed scan
    server_heading_pages(texts, heading)     the server's scan of the report
    gate(state, report_fp)                   (ok, [what is missing])

Changes made on the Integration Review tab are kept apart from the report's records
(raw_changes): one per (injection, analyte, transition), the transition None
for the quantifier. An edit asks for nothing; before submit each open change
has a reason and the analyst's initials, given once for all; at verify a
different person countersigns them. The report's gate and stamp ignore them.
`no_effect` names the changes the run kept but could not apply,
{(injection, analyte, transition): why}: they ask no reason or signature.
`sign_as` is the person's People & Roles sign rights (SIGN_RIGHT): initials need
the analyst's, a countersignature the reviewer's.

    record_raw_edit(state, injection, analyte, transition, kind, before,
                    after, who, when, qc_type, quant_transition)
                                             an edit made or changed
    drop_raw_edit(state, injection, analyte, transition, who, when,
                  quant_transition)          the edit undone
    shared_partner(state, injection, analyte)
                                             the peak a moved edge is shared
                                             with, both records naming it
    set_raw_reason(state, id, reason_id, reason, detail, who, when)
    initial_raw(state, initials, who, when, name, no_effect, sign_as)
                                             the analyst, once for all
    countersign_raw(state, who, when, name, no_effect, sign_as)
                                             the verifier, a DIFFERENT person
    raw_gate(state, phase, no_effect, overrides)
                                             (ok, [what is missing]) at
                                             "submit" or "verify"; an edit in
                                             the run's file with no record
                                             is missing too

A change applied to every injection of the run ("Apply to all") is the
compound's processing for the run, not a manual change: it asks no reason
or initials, and is listed in the run's processing history
(processing_changes), each change with who, when, before and after. Only
a major change (PROCESSING_MAJOR_KINDS) is countersigned at release, by a
person other than its maker. The change in force for a trace is its last
record not undone; only that one is undone, which puts back its before.

    "processing_changes": [{"id", "analyte", "transition", "kind", "before",
                  "after", "major", "skipped", "by", "at",
                  "undone": {"by", "at"} | None,
                  "verifier": {"userid", "name", "at", "fp"} | None,
                  and for a smoothing change "mid", "label"}]

    record_processing_change(state, analyte, transition, kind, before,
                             after, major, who, when, skipped, mid, label)
    undo_processing_change(state, id, who, when)
    processing_open(state)                   the changes in force
    countersign_processing(state, who, when, name, sign_as, signature, method)
    processing_gate(state, phase, processing, method, stored_smoothing,
                    label, stored_processing)
                                             `method` the method's changes
                                             the run applies (method_held);
                                             the smoothing and the trace
                                             changes its stored peaks show
                                             each need a record in force
                                             (ok, [what is missing]); a
                                             change in the run's processing
                                             file with no record is missing
    processing_orphans(state, processing)    those changes, by their key
    undo_orphan_processing(state, key, who, when, record)
                                             one of them taken out of the
                                             file: its history row
    smoothing_first_mid(state, analyte)      (found, mid): the Mid of the
                                             compound's first smoothing
                                             change that carries one

Pure: Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

# a cell meaning "nothing changed"
_EMPTY = frozenset(("", "0", "no", "n", "false", "none", "-", "nan", "n/a", "na"))

# The starting list, verbatim from the sources; a manager edits the list,
# these only seed it.
SEED_REASONS = [
    ("not-identified", "The software did not identify and integrate the peak of interest", "VELAP TAD 2.1"),
    ("inconsistent", "The software integrated the peak of interest in an inconsistent manner", "VELAP TAD 2.1"),
    ("wrong-peak", "The software identified and integrated a peak other than the peak of interest", "VELAP TAD 2.1"),
    ("split-peak", "Split peaks", "VELAP TAD 2.2.1"),
    ("co-elution", "Co-elution of target compounds / shoulders", "VELAP TAD 2.2.2"),
    ("baseline-noise", "Baseline noise", "VELAP TAD 2.2.3"),
    ("negative-peak", "Negative peaks", "VELAP TAD 2.2.4"),
    ("baseline-drift", "Rising or falling baselines", "VELAP TAD 2.2.5"),
    ("tailing", "Excessive peak tailing", "VELAP TAD 2.2.6"),
    ("summed-areas", "Integration of summed areas", "VELAP TAD 2.2.7"),
    ("interferant", "Adding area due to a co-eluting interferant", "NC DEQ policy 2010"),
    ("matrix", "Matrix interference", "NC DEQ policy 2010"),
    ("separation", "Failure to separate peaks", "NC DEQ policy 2010"),
]

# Never a justification (VELAP TAD 3.3-3.4; NC DEQ policy 2010).
IMPROPER = [
    "Making a quality control sample meet its acceptance criteria",
    "Peak shaving: removing area from an acceptable automatic integration",
    "Peak juicing: adding area to an acceptable automatic integration",
    "Changing the peak height to other than the highest point of the peak",
    "Baseline elevated above, or dropped below, the signal",
    "Selectively adjusting integration events",
]


def _text(raw):
    if raw is None:
        return ""
    if isinstance(raw, float) and raw != raw:          # NaN from an empty cell
        return ""
    return ("%s" % raw).strip()


def parse_markers(text):
    """"!, m, Manual" -> ["!", "m", "Manual"] (the import profile's setting)."""
    return [m.strip() for m in (text or "").split(",") if m.strip()]


def is_manual(raw, markers=None):
    """Was this result manually integrated? With markers (the import
    profile's "values meaning manual integration"), when the cell contains
    any of them (case-insensitive); without, when the cell holds anything
    other than a blank or a "no"."""
    cell = _text(raw)
    if markers:
        low = cell.lower()
        return any(m.lower() in low for m in markers if m)
    return cell.lower() not in _EMPTY


# ── the worksheet's records ────────────────────────────────────────────────

EDITABLE = ("reason_id", "reason", "detail", "before_page", "after_page")
QC_TYPES_FLAGGED = ("MB", "LRB", "MxB", "LFB", "LFSM", "LFSMD", "Dup", "CAL", "ICV", "CCV", "CCB")


def empty_state():
    return {"report_fp": "", "report_file": "", "records": [], "none_in_report": None,
            "history": [], "stamped": None, "heading_scan": None, "dismissed": {},
            "raw_changes": [], "processing_changes": []}


def _log(state, who, when, rec_id, action, changes=None):
    state.setdefault("history", []).append(
        {"at": when, "by": who, "id": rec_id or "", "action": action, "changes": changes or {}})


def _find(state, rec_id):
    for r in state.get("records") or []:
        if r["id"] == rec_id:
            return r
    raise KeyError(rec_id)


def _new_id(state):
    # a raw change moved out of the records keeps its id: it is never reused
    moved = [r for r in state.get("raw_changes") or [] if r["id"].startswith("mi-")]
    n = max([int(r["id"].split("-")[-1]) for r in (state.get("records") or []) + moved
             if r["id"].split("-")[-1].isdigit()] or [0]) + 1
    return "mi-%d" % n


def add(state, injection, analyte, source, qc_type, who, when):
    """A new record; an (injection, analyte) already listed is refused."""
    if any(r["injection"] == injection and r["analyte"] == analyte for r in state.get("records") or []):
        raise ValueError("%s / %s is already listed" % (injection, analyte))
    rec = {"id": _new_id(state), "injection": injection, "analyte": analyte, "source": source,
           "qc_type": qc_type or "", "before_page": None, "after_page": None,
           "reason_id": "", "reason": "", "detail": "", "analyst": None, "reviewer": None}
    state.setdefault("records", []).append(rec)
    state["none_in_report"] = None
    _log(state, who, when, rec["id"], "added", {"injection": [None, injection], "analyte": [None, analyte],
                                               "source": [None, source]})
    return rec


def merge_detected(state, rows, who, when):
    """Add a record for each manually integrated (injection, analyte) of the
    export not already listed. rows: [{"injection", "analyte", "qc_type"}].
    Returns the records added."""
    have = set((r["injection"], r["analyte"]) for r in state.get("records") or [])
    added = []
    for row in rows:
        key = (row["injection"], row["analyte"])
        if key not in have:
            added.append(add(state, key[0], key[1], "export", row.get("qc_type"), who, when))
            have.add(key)
    return added


def _clean(field, value):
    if field in ("before_page", "after_page"):
        if value in (None, ""):
            return None
        page = int(value)
        if page < 1:
            raise ValueError("a page number starts at 1")
        return page
    return ("%s" % (value or "")).strip()


def update(state, rec_id, fields, who, when):
    """Apply edits to a record. Any real change to what was justified (reason,
    detail, pages) clears both signatures: a signature attests to what it was
    given. Every change is recorded with its old and new value."""
    rec = _find(state, rec_id)
    changes = {}
    for field in EDITABLE:
        if field not in fields:
            continue
        new = _clean(field, fields[field])
        if field in ("before_page", "after_page") and new is not None and not state.get("report_fp"):
            raise ValueError("%s: upload the instrument report before giving pages" % rec_id)
        if new != rec.get(field):
            changes[field] = [rec.get(field), new]
            rec[field] = new
    if changes:
        if rec.get("analyst") or rec.get("reviewer"):
            changes["signatures"] = ["cleared", None]
        rec["analyst"] = rec["reviewer"] = None
        state["stamped"] = None
        _log(state, who, when, rec_id, "edited", changes)
    return changes


def missing(rec, role):
    """What a record still needs before `role` may sign it."""
    out = []
    if not rec.get("reason"):
        out.append("a reason")
    if rec.get("before_page") is None or rec.get("after_page") is None:
        out.append("the before and after pages")
    if role == "reviewer" and not rec.get("analyst"):
        out.append("the analyst's signature")
    return out


def sign(state, rec_id, role, who, when, name=""):
    """The analyst signs first, then a reviewer who is not the analyst.
    Raises ValueError with what is missing."""
    if role not in ("analyst", "reviewer"):
        raise ValueError("unknown role %s" % role)
    rec = _find(state, rec_id)
    if rec.get(role):
        raise ValueError("%s is already signed as %s." % (rec_id, role))
    need = missing(rec, role)
    if need:
        raise ValueError("%s: needs %s" % (rec_id, ", ".join(need)))
    if role == "reviewer" and rec["analyst"]["userid"] == who:
        raise ValueError("%s: the reviewer must not be the analyst" % rec_id)
    rec[role] = {"userid": who, "name": name or who, "at": when}
    if role == "analyst":
        rec["reviewer"] = None
    state["stamped"] = None
    _log(state, who, when, rec_id, "signed as %s" % role)
    return rec


def phase(review_status):
    """"verify" once the worksheet is verified or published, else "submit":
    the phase Data Review's gates are enforced in. A submitted worksheet is
    still read at submit: Approve Release gives the countersignature."""
    return "verify" if review_status in ("verified", "published") else "submit"


READY_TO_VERIFY = "Ready to verify"
NOT_READY_TO_VERIFY = "Not ready to verify"


def readiness_phase(review_status):
    """"verify" from to_be_verified on, else "submit": the phase the
    readiness lines are worded in (Data Review's Manual changes and
    Processing changes, the Manual integration page). A submitted worksheet
    waits for its verifier, so its lines judge the release. They read the
    gate in force (phase()): a line names only what the reviewer must do
    first, never the countersignature Approve Release itself gives."""
    return "verify" if review_status in ("to_be_verified", "verified", "published") else "submit"


def verify_readiness(phase, ok, missing):
    """The readiness line in the verify phase: {"ok", "text"}, the text
    "Ready to verify", or "Not ready to verify: " and the first thing
    missing, named. None in the submit phase, where each page words its
    line to submit."""
    if phase != "verify":
        return None
    if ok:
        return {"ok": True, "text": READY_TO_VERIFY}
    text = "%s: %s" % (NOT_READY_TO_VERIFY, missing[0]) if missing else NOT_READY_TO_VERIFY
    return {"ok": False, "text": text}


def action_allowed(review_status, action):
    """Whether a record-changing action may run in this worksheet state. A
    submitted worksheet waits for its reviewer: only the reviewer's signature,
    a countersignature and the stamp (the verify gate wants the stamped copy
    after the reviewer signs) may follow; verified and published are read only."""
    if review_status in ("verified", "published"):
        return False
    if review_status == "to_be_verified":
        return action in ("sign_reviewer", "countersign", "stamp")
    return True


def refused_text(review_status):
    """Why a record-changing action was refused, naming the state the
    worksheet is in; a submitted worksheet still takes the reviewer's
    signature (action_allowed)."""
    word = {"verified": u"verified", "published": u"published"}.get(review_status, u"submitted")
    return u"This worksheet is %s: its manual integration records are read only%s." % (
        word, u" except the reviewer's signature" if word == u"submitted" else u"")


def scoped(names, allowed):
    """The names inside the Method x Matrix panel (`allowed`; None = no panel
    to scope by), in their order."""
    return [n for n in names if allowed is None or n in allowed]


def refuse_signed_change(rec, fields):
    """A signed record changes only after it is reopened: a posted field that
    differs from what is stored is refused, never ignored."""
    for field in EDITABLE:
        if field in fields and _clean(field, fields[field]) != rec.get(field):
            raise ValueError("%s is signed: Edit it from the row menu first." % rec["id"])


def all_signed(state):
    """Every record is signed by the analyst and by the reviewer."""
    recs = state.get("records") or []
    return bool(recs) and all(r.get("analyst") and r.get("reviewer") for r in recs)


def reopen(state, rec_id, who, when):
    """A signed record is opened for editing: both signatures are cleared, so
    the stamped copy is void, and it is logged."""
    try:
        rec = _find(state, rec_id)
    except KeyError:
        raise ValueError("%s: no such record" % rec_id)
    if not (rec.get("analyst") or rec.get("reviewer")):
        raise ValueError("%s: it is not signed" % rec_id)
    rec["analyst"] = rec["reviewer"] = None
    state["stamped"] = None
    _log(state, who, when, rec_id, "reopened for editing", {"signatures": ["cleared", None]})
    return rec


def rebind_report(state, fp, who, when):
    """The report the pages refer to changed (re-uploaded, another chosen,
    removed, or a first one where none was): every page, signature, scan and
    dismissal is cleared, and the stamped copy is void."""
    if (state.get("report_fp") or "") == (fp or ""):
        return False
    old = state.get("report_fp") or ""
    state["report_fp"] = fp or ""
    for rec in state.get("records") or []:
        rec["before_page"] = rec["after_page"] = None
        rec["analyst"] = rec["reviewer"] = None
    state["none_in_report"] = None
    state["stamped"] = None
    state["heading_scan"] = None
    state["dismissed"] = {}
    _log(state, who, when, "", "report changed" if old else "report chosen", {"report": [old or None, fp or None]})
    return True


def parse_pages(text):
    """"3, 5,8" -> [3, 5, 8]; "none" -> [] (no page carries the heading);
    blank -> None (nothing recorded: a blank field attests nothing). Refuses
    anything that is not a page number."""
    if not ("%s" % (text or "")).strip():
        return None
    if ("%s" % text).strip().lower() == "none":
        return []
    out = set()
    for part in ("%s" % (text or "")).replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit() or int(part) < 1:
            raise ValueError("%s is not a page number" % part)
        out.add(int(part))
    return sorted(out)


def record_scan(state, fp, pages, who, when, found=None):
    """Record which pages of the report carry the lab's heading: as typed
    (the viewer's scan, correctable by hand) and as the viewer found them.
    Typing can only ADD pages: a page the viewer found stays a heading page
    (uncovered() uses both), so taking one out goes through dismiss(), with a
    reason. found None (no viewer: no internet) keeps what an earlier scan of
    this report found. Only for the report under review."""
    if not fp or fp != state.get("report_fp"):
        raise ValueError("the report changed while the page was open: reload it")
    pages = sorted(set(int(p) for p in pages))
    old = state.get("heading_scan") or {}
    if found is None:
        found = old.get("found") if old.get("fp") == fp else None
    found = sorted(set(int(p) for p in found)) if found is not None else None
    if old.get("fp") == fp and old.get("pages") == pages and old.get("found") == found:
        return False
    state["heading_scan"] = {"fp": fp, "pages": pages, "found": found, "by": who, "at": when}
    _log(state, who, when, "", "heading pages recorded",
         {"pages": [old.get("pages"), pages], "found": [old.get("found"), found]})
    return True


def _norm(text):
    import re
    return re.sub(r"\s+", "", "%s" % (text or "")).lower()


def page_has_heading(text, heading):
    """THE matching rule (the browser viewer normalises the same way): the
    heading appears in the page's text, ignoring case and all white space
    ("Manual  Integration", "ManualIntegration" -- text extraction often
    drops or doubles the spaces)."""
    h = _norm(heading)
    return bool(h) and h in _norm(text)


def server_heading_pages(texts, heading):
    """The server's scan: [page] carrying the heading, from each page's text.
    None when no page has any text (a scanned image): that is no scan."""
    if not texts or not any(("%s" % (t or "")).strip() for t in texts):
        return None
    return [i + 1 for i, t in enumerate(texts) if page_has_heading(t, heading)]


def heading_pages(state, server=None):
    """The report's heading pages: the server's scan, typed and found by the
    viewer, together."""
    scan = state.get("heading_scan") or {}
    pages = set(server or [])
    if scan.get("fp") == state.get("report_fp"):
        pages |= set(scan.get("pages") or []) | set(scan.get("found") or [])
    return sorted(pages)


def dismiss(state, page, reason, who, when, server=None):
    """A heading page that is not a manual integration (a summary or index
    page, say), with why; a reviewer countersigns it. Only a heading page."""
    page = int(page)
    if page not in heading_pages(state, server):
        raise ValueError("page %d is not a recorded heading page" % page)
    reason = ("%s" % (reason or "")).strip()
    if not reason:
        raise ValueError("page %d: say why it is not a manual integration" % page)
    state.setdefault("dismissed", {})["%d" % page] = {"reason": reason, "by": who, "at": when}
    _log(state, who, when, "", "heading page dismissed", {"page": [None, page], "reason": [None, reason]})


def countersign(state, kind, who, when, name="", page=None):
    """A reviewer who is NOT the person who made it confirms: a dismissal
    ("dismissal", page), "Confirm: none" ("none"), or a typed heading-page
    record standing in for a scan the server could not make ("scan").
    Changing what was confirmed makes a new entry, unsigned."""
    if kind == "dismissal":
        entry = (state.get("dismissed") or {}).get("%d" % int(page or 0))
        maker = (entry or {}).get("by")
        label = "page %d dismissal" % int(page or 0)
    elif kind == "none":
        entry = state.get("none_in_report")
        maker = (entry or {}).get("userid")
        label = "none in the report"
    elif kind == "scan":
        entry = state.get("heading_scan")
        if entry and entry.get("fp") != state.get("report_fp"):
            entry = None
        maker = (entry or {}).get("by")
        label = "the heading-page record"
    else:
        raise ValueError("unknown countersignature %s" % kind)
    if not entry:
        raise ValueError("%s: nothing to countersign" % label)
    if maker == who:
        raise ValueError("%s: the reviewer must not be the person who made it" % label)
    entry["reviewer"] = {"userid": who, "name": name or who, "at": when}
    _log(state, who, when, "", "countersigned " + label)
    return entry


def uncovered(state, server=None):
    """Heading pages that no record lists and no one has dismissed."""
    listed = set()
    for r in state.get("records") or []:
        listed.update(p for p in (r.get("before_page"), r.get("after_page")) if p)
    dismissed = state.get("dismissed") or {}
    return [p for p in heading_pages(state, server) if p not in listed and ("%d" % p) not in dismissed]


def confirm_none(state, who, when, name=""):
    """A person confirms the report shows no manual integration (needed when
    the export did not capture it). Refused while records exist."""
    if state.get("records"):
        raise ValueError("manual integrations are listed: justify them instead")
    if not state.get("report_fp"):
        raise ValueError("upload the instrument report first")
    state["none_in_report"] = {"userid": who, "name": name or who, "at": when}
    _log(state, who, when, "", "confirmed none in the report")


def signed_fingerprint(state):
    """What a stamped copy must match: every record's justified content and
    signatures, and the report."""
    import hashlib
    import json
    body = json.dumps({"report": state.get("report_fp"),
                       "records": [dict((k, r.get(k)) for k in ("id", "injection", "analyte")
                                        + EDITABLE + ("analyst", "reviewer"))
                                   for r in state.get("records") or []]},
                      sort_keys=True)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def gate(state, report_fp, captured=True, server=None):
    """(ok, [what is missing]) for the Instrument Report gate.

    server: the server's scan of this report (server_heading_pages), or None
    when there is none with text. A server scan is the heading-page record;
    without one, a typed record stands in and a reviewer countersigns it.
    Every heading page is listed by a record or dismissed with a reason and
    a reviewer's countersignature; "none in the report" is countersigned
    too. Each record needs a reason, both pages and both signatures, and the
    stamped copy must match them and the current report."""
    records = state.get("records") or []
    out = []
    if not records and captured and not report_fp:
        return True, []
    if not report_fp:
        return False, ["upload the instrument report"]
    if (state.get("report_fp") or "") != report_fp:
        return False, ["the instrument report changed: confirm the pages again"]
    scan = state.get("heading_scan") or {}
    if scan.get("fp") != report_fp:
        scan = {}
    if server is None and (records or not captured):
        if not scan:
            out.append("record the report's heading pages (Report pages, then Save)")
        elif not scan.get("reviewer"):
            out.append("the heading-page record: the reviewer's countersignature")
    out.extend("page %d carries the heading but is not listed: add it, or dismiss it with a reason" % p
               for p in uncovered(state, server))
    pages = set(heading_pages(state, server))
    for key, d in sorted((state.get("dismissed") or {}).items()):
        if int(key) in pages and not d.get("reviewer"):
            out.append("page %s dismissal: the reviewer's countersignature" % key)
    if not records:
        none = state.get("none_in_report")
        if not captured and not none:
            out.append("manual integration not captured by the export: add them, or confirm there are none")
        elif none and not none.get("reviewer"):
            out.append("none in the report: the reviewer's countersignature")
        return (not out), out
    for rec in records:
        need = missing(rec, "reviewer")
        if rec.get("analyst") and not rec.get("reviewer"):
            need.append("the reviewer's signature")
        if need:
            out.append("%s %s / %s: %s" % (rec["id"], rec["injection"], rec["analyte"], ", ".join(need)))
    if not out:
        st = state.get("stamped") or {}
        if st.get("of") != signed_fingerprint(state):
            out.append("stamp the report")
    return (not out), out


# ── changes made on the Integration Review tab ───────────────────────────────────────

# the People & Roles sign right each signature needs, the instrument report's
# records and the Integration Review changes alike
SIGN_RIGHT = {"analyst": "preparer", "reviewer": "reviewer"}
RAW_KINDS = ("integrate", "apex", "delete", "fit")
RAW_KIND_TEXT = {"integrate": "re-integrated", "apex": "another apex", "delete": "peak deleted",
                 "fit": "peaks fitted"}
RAW_FIELDS = ("kind", "before", "after", "reason_id", "reason", "detail")


def _transition(transition, quant_transition=None):
    """None for the quantifier: no transition, an empty one, or the
    quantifier's own."""
    if transition in (None, "") or transition == quant_transition:
        return None
    return transition


def _raw_find(state, injection, analyte, transition):
    for r in state.get("raw_changes") or []:
        if (r["injection"], r["analyte"], r.get("transition")) == (injection, analyte, transition):
            return r
    return None


def _raw_by_id(state, rec_id):
    for r in state.get("raw_changes") or []:
        if r["id"] == rec_id:
            return r
    raise KeyError(rec_id)


def _raw_new_id(state):
    n = max([int(r["id"].split("-")[-1]) for r in state.get("raw_changes") or []
             if r["id"].startswith("re-") and r["id"].split("-")[-1].isdigit()] or [0]) + 1
    return "re-%d" % n


def raw_fingerprint(rec):
    """What a signature on a raw change attests: the change and its reason.
    A signature counts only while this is unchanged."""
    import hashlib
    import json
    # the pairing of a shared edge is attested too, but only a record that has one carries it: a
    # record without it reads as it always did, so its signatures stay valid
    keys = ("injection", "analyte", "transition") + RAW_FIELDS + (("shared_with",) if rec.get("shared_with") else ())
    body = json.dumps(dict((k, rec.get(k)) for k in keys),
                      sort_keys=True)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def raw_signed(rec, role):
    sig = rec.get(role)
    return bool(sig) and sig.get("fp") == raw_fingerprint(rec)


def _clear_signatures(rec, changes):
    if rec.get("analyst") or rec.get("verifier"):
        changes["signatures"] = ["cleared", None]
    rec["analyst"] = rec["verifier"] = None


def raw_key(rec):
    """(injection, analyte, transition) of a raw change; None for the quantifier."""
    return (rec["injection"], rec["analyte"], rec.get("transition"))


def raw_open(state, no_effect=None):
    """The changes that need a reason and signatures: every one not undone,
    less those the run could not apply (`no_effect`)."""
    no_effect = no_effect or {}
    return [r for r in state.get("raw_changes") or [] if not r.get("dropped") and raw_key(r) not in no_effect]


def _sign_right(role, sign_as, name, act, signature=None, what="manual changes"):
    """ValueError when People & Roles gives the person (`name`) no sign right for
    `role`, or when they have no signature on file (`signature` False), as
    the instrument report's records ask; None is not checked."""
    if sign_as is not None and SIGN_RIGHT[role] not in sign_as:
        raise ValueError("%s has no %s sign right in People & Roles, so does not %s %s"
                         % (name, SIGN_RIGHT[role], act, what))
    if signature is not None and not signature:
        raise ValueError("%s has no signature on file, so does not %s %s" % (name, act, what))


def record_raw_edit(state, injection, analyte, transition, kind, before, after, who, when,
                    qc_type="", quant_transition=None, reason_id="", reason="", detail="", shared_with=""):
    """An edit made on the Integration Review tab, with the reason (from the lab's list,
    by id and text) and comment given when it was made; none given leaves the
    record's as they are. The trace's one record is made, or updated (also
    after an undo); the automatic peak (before) is the first edit's. A real
    change clears the signatures, and so does a changed reason or comment
    (set_raw_reason); the same edit posted again changes nothing else.
    after: the edges, apex, area, the line it is measured on ("baseline"), any levels set by hand and the
    record's "version" (raw_review.EDIT_VERSION: its baseline is named in
    this version's words); ignored for a delete."""
    if kind not in RAW_KINDS:
        raise ValueError("%s / %s: the change is one of %s" % (injection, analyte, ", ".join(RAW_KINDS)))
    if kind == "delete":
        after = {"deleted": True}
    elif not isinstance(after, dict) or not after:
        raise ValueError("%s / %s: the edited peak is missing" % (injection, analyte))
    transition = _transition(transition, quant_transition)
    rec = _raw_find(state, injection, analyte, transition)
    given = bool(reason_id or reason or detail)
    if rec is not None and not rec.get("dropped") and rec.get("kind") == kind and rec.get("after") == after \
            and (shared_with or "") == (rec.get("shared_with") or ""):
        if given:
            set_raw_reason(state, rec["id"], reason_id, reason, detail, who, when)
        return rec
    if rec is None:
        rec = {"id": _raw_new_id(state), "injection": injection, "analyte": analyte,
               "transition": transition, "qc_type": qc_type or "", "kind": kind,
               "before": before, "after": None, "by": who, "at": when, "dropped": None,
               "reason_id": "", "reason": "", "detail": "", "analyst": None, "verifier": None}
        state.setdefault("raw_changes", []).append(rec)
        changes = {"kind": [None, kind], "before": [None, before], "after": [None, after]}
        if shared_with:
            changes["shared_with"] = [None, shared_with]
    else:
        changes = {"after": [rec.get("after"), after]}
        if (shared_with or "") != (rec.get("shared_with") or ""):
            changes["shared_with"] = [rec.get("shared_with") or None, shared_with or None]
        if rec.get("kind") != kind:
            changes["kind"] = [rec.get("kind"), kind]
        if rec.get("dropped"):
            changes["undone"] = [rec["dropped"], None]
        if rec.get("before") is None and before is not None:
            rec["before"] = before
        _clear_signatures(rec, changes)
    # the other analyte whose peak shares an edge moved with this one (a drop line), kept apart
    # from the analyst's comment
    rec.update(kind=kind, after=after, by=who, at=when, dropped=None, shared_with=shared_with or "")
    _log(state, who, when, rec["id"], "edited on the Integration Review tab", changes)
    if given:
        set_raw_reason(state, rec["id"], reason_id, reason, detail, who, when)
    return rec


def drop_raw_edit(state, injection, analyte, transition, who, when, quant_transition=None):
    """The edit undone: the change leaves the list to sign and the history
    keeps it. None when the trace has no open change."""
    rec = _raw_find(state, injection, analyte, _transition(transition, quant_transition))
    if rec is None or rec.get("dropped"):
        return None
    changes = {"undone": [None, {"by": who, "at": when}]}
    _clear_signatures(rec, changes)
    rec["dropped"] = {"by": who, "at": when}
    _log(state, who, when, rec["id"], "undone on the Integration Review tab", changes)
    return rec


def shared_partner(state, injection, analyte):
    """The analyte whose quantifier peak shares a moved edge with this one
    in the injection: named so by this trace's open record and naming this
    analyte back in its own; None otherwise (one side re-edited on its own
    since, or undone). Undoing one half of a shared edge undoes both."""
    def named(an):
        rec = _raw_find(state, injection, an, None)
        return (rec.get("shared_with") or None) if rec is not None and not rec.get("dropped") else None
    partner = named(analyte)
    return partner if partner and named(partner) == analyte else None


def set_raw_reason(state, rec_id, reason_id, reason, detail, who, when):
    """The reason (from the lab's list) and detail of an open change. A real
    change clears its signatures."""
    rec = _raw_by_id(state, rec_id)
    if rec.get("dropped"):
        raise ValueError("%s: the change was undone" % raw_label(rec))
    changes = {}
    for field, value in (("reason_id", reason_id), ("reason", reason), ("detail", detail)):
        new = ("%s" % (value or "")).strip()
        if new != (rec.get(field) or ""):
            changes[field] = [rec.get(field), new]
            rec[field] = new
    if changes:
        _clear_signatures(rec, changes)
        _log(state, who, when, rec_id, "reason given", changes)
    return changes


def initial_raw(state, initials, who, when, name="", no_effect=None, sign_as=None, signature=None):
    """The analyst initials every open change at once; refused while any of
    them lacks a reason, or when People & Roles gives the analyst no preparer
    sign right or no signature on file. Those already initialled as they
    stand are kept."""
    initials = ("%s" % (initials or "")).strip()
    if not initials:
        raise ValueError("type your initials")
    _sign_right("analyst", sign_as, name or who, "initial", signature)
    recs = raw_open(state, no_effect)
    if not recs:
        raise ValueError("no manual changes to initial")
    no_reason = [raw_label(r) for r in recs if not r.get("reason")]
    if no_reason:
        raise ValueError("give a reason first: %s" % "; ".join(no_reason))
    todo = [r for r in recs if not raw_signed(r, "analyst")]
    for rec in todo:
        rec["analyst"] = {"userid": who, "name": name or who, "initials": initials, "at": when,
                          "fp": raw_fingerprint(rec)}
        rec["verifier"] = None
    if todo:
        _log(state, who, when, "", "initialled", {"changes": [None, [r["id"] for r in todo]]})
    return todo


# history actions that edit a raw change's peak
# a history entry written under the tab's former name still counts as an edit
# (or an undo): the editors of a change must stay known after a rename
_FORMER_TAB = "the Raw" + " Data tab"
_RAW_EDITED = ("edited on the Integration Review tab", "edited on " + _FORMER_TAB, "re-integrated")
_RAW_UNDONE = ("undone on the Integration Review tab", "undone on " + _FORMER_TAB)


def raw_editors(state, rec):
    """The user ids who edited this change's peak since its last undo: the
    last editor and every edit the history keeps after the last undo."""
    who = set([rec["by"]]) if rec.get("by") else set()
    for h in state.get("history") or []:
        if h.get("id") != rec["id"]:
            continue
        if h.get("action") in _RAW_UNDONE:
            who = set()
        elif h.get("action") in _RAW_EDITED and h.get("by"):
            who.add(h["by"])
    if rec.get("by"):
        who.add(rec["by"])
    return who


def countersign_raw(state, who, when, name="", no_effect=None, sign_as=None, signature=None):
    """The verifier countersigns every open change at once: each needs its
    reason and the analyst's initials, the verifier needs the reviewer sign
    right in People & Roles and a signature on file, and is never the person who initialled a change nor
    anyone who edited its peak since its last undo. A change already
    countersigned as it stands is kept."""
    recs = raw_open(state, no_effect)
    if recs:
        _sign_right("reviewer", sign_as, name or who, "countersign", signature)
    need = [raw_label(r) for r in recs if not r.get("reason") or not raw_signed(r, "analyst")]
    if need:
        raise ValueError("the manual changes need a reason and the analyst's initials first: %s"
                         % "; ".join(need))
    todo = [r for r in recs if not raw_signed(r, "verifier")]
    own = []
    for r in todo:
        if r["analyst"]["userid"] == who:
            own.append("%s initialled %s" % (who, raw_label(r)))
        if who in raw_editors(state, r):
            own.append("%s edited %s" % (who, raw_label(r)))
    if own:
        raise ValueError("a different person countersigns these manual changes: %s" % "; ".join(own))
    for rec in todo:
        rec["verifier"] = {"userid": who, "name": name or who, "at": when, "fp": raw_fingerprint(rec)}
    if todo:
        _log(state, who, when, "", "countersigned", {"changes": [None, [r["id"] for r in todo]]})
    return todo


def _unrecorded(state, overrides):
    """The edits in the run's file (`overrides`, by key) that no open record
    lists: one whose record was never saved, or was undone."""
    from senaite.pfas.raw_review import parse_edit_key
    out = []
    for key in sorted(overrides or {}):
        try:
            injection, analyte, transition = parse_edit_key(key)
        except ValueError:
            out.append("%s: an edit has no record; undo it on the Integration Review tab" % key)
            continue
        rec = _raw_find(state, injection, analyte, transition)
        if rec is None or rec.get("dropped"):
            out.append("%s / %s: an edit has no record; undo it on the Integration Review tab" % (injection, analyte))
    return out


def raw_gate(state, phase="submit", no_effect=None, overrides=None):
    """(ok, [what is missing]): before submit every open change has a reason
    and the analyst's initials; at verify also the verifier's
    countersignature. An undone change needs nothing, nor one the run could
    not apply (`no_effect`). Every edit in the run's file (`overrides`)
    has an open record: an edit with none is missing, as nobody would sign
    it."""
    out = _unrecorded(state, overrides)
    for rec in raw_open(state, no_effect):
        need = []
        if not rec.get("reason"):
            need.append("a reason")
        if not raw_signed(rec, "analyst"):
            need.append("the analyst's initials")
        elif phase == "verify" and not raw_signed(rec, "verifier"):
            need.append("the verifier's countersignature")
        if need:
            out.append("%s: %s" % (raw_label(rec), ", ".join(need)))
    return (not out), out


# ── the run's processing changes ("Apply to all") ─────────────────────────

# a change of how the compound is processed, not of where its peak is cut:
# countersigned at release. Moving the edges or changing the line is not;
# a fit and a change of the compound's smoothing are.
PROCESSING_MAJOR_KINDS = ("fit", "smoothing")
PROCESSING_KIND_TEXT = {"integrate": "re-integrated for all injections", "fit": "fitted for all injections",
                        "smoothing": "smoothed for all injections"}
PROCESSING_FIELDS = ("analyte", "transition", "kind", "before", "after", "major")
# a smoothing change is the compound's, every trace in every injection, held
# apart from its traces' changes; its record keeps "mid", the window the run
# smoothed over before any smoothing change of the run, and "label", the
# compound's name, so it is worded as made whatever the method holds later
SMOOTHING = "smoothing"
SMOOTHING_TEXT = "Smoothing for %s: %s to %s"
SMOOTHING_STEPS = ("Low", "Mid", "High")


def smoothing_step(points, mid):
    """The step a window of `points` is from the compound's Mid (`mid`
    points, 2m + 1): "Mid"; "Low", m - 1; "High", 2m; else "N points"."""
    if points is None:
        return SMOOTHING_STEPS[1]
    if mid:
        m = (int(mid) - 1) // 2
        steps = {2 * (m - 1) + 1: SMOOTHING_STEPS[0], int(mid): SMOOTHING_STEPS[1], 4 * m + 1: SMOOTHING_STEPS[2]}
        if points in steps:
            return steps[points]
    return "%d points" % points


def smoothing_first_mid(state, analyte):
    """(found, mid): whether the run's history holds a smoothing change of
    the compound, and the Mid of the first of them that carries one (None
    when none does). A change taken out of the file with no record carries
    no Mid and is passed over; once any change is on record, the stored
    peaks may show an undone window, so they are never read for Mid."""
    earlier = [r for r in state.get("processing_changes") or []
               if r.get("kind") == SMOOTHING and r.get("analyte") == analyte]
    return bool(earlier), next((r["mid"] for r in earlier if r.get("mid")), None)


def smoothing_words(rec, label=None):
    """"Smoothing for PFOS: Mid to High", by the compound's `label` (else
    the one the record keeps, else its keyword)."""
    before = (rec.get("before") or {}).get("points")
    after = (rec.get("after") or {}).get("points")
    return SMOOTHING_TEXT % (label or rec.get("label") or rec["analyte"], smoothing_step(before, rec.get("mid")),
                             smoothing_step(after, rec.get("mid")) if after is not None else "none")


def processing_label(rec):
    """"PFOA quantifier, re-integrated for all injections"; a smoothing
    change "Smoothing for PFOA: Mid to High"."""
    if rec.get("kind") == SMOOTHING:
        return smoothing_words(rec)
    return "%s %s, %s" % (rec["analyte"], rec.get("transition") or "quantifier",
                          PROCESSING_KIND_TEXT.get(rec.get("kind"), rec.get("kind") or ""))


def processing_rec_key(rec):
    """The processing key a record names: its trace's, or its compound's
    smoothing key."""
    from senaite.pfas.raw_review import processing_key, smoothing_key
    if rec.get("kind") == SMOOTHING:
        return smoothing_key(rec["analyte"])
    return processing_key(rec["analyte"], rec.get("transition"), None)


def processing_entry(processing, key):
    """The run's processing file's entry for a key (a trace's or a smoothing
    key), or None."""
    from senaite.pfas.raw_review import parse_smoothing_key
    analyte = parse_smoothing_key(key)
    if analyte is not None:
        return ((processing or {}).get("smoothing") or {}).get(analyte)
    return ((processing or {}).get("traces") or {}).get(key)


def processing_key_text(key, label=None):
    """A processing key as the person reads it: a trace's key as it is, a
    smoothing key as "PFOS smoothing", by the compound's `label` (a
    function of the keyword) where given, never "smoothing:PFOS"."""
    from senaite.pfas.raw_review import parse_smoothing_key
    analyte = parse_smoothing_key(key)
    if analyte is None:
        return key
    return "%s smoothing" % ((label(analyte) if label else None) or analyte)


def processing_trace_text(key):
    """A trace's processing key as its trace: "PFNA quantifier", "PFNA
    413.0 > 169.0"."""
    analyte, transition = processing_key_trace(key)[:2]
    return "%s %s" % (analyte, transition or "quantifier")


def processing_key_trace(key):
    """(analyte, transition or None, smoothing) of a processing key; a key
    that cannot be read is its own analyte."""
    from senaite.pfas.raw_review import parse_processing_key, parse_smoothing_key
    analyte = parse_smoothing_key(key)
    if analyte is not None:
        return analyte, None, True
    try:
        analyte, transition = parse_processing_key(key)
    except ValueError:
        analyte, transition = key, None
    return analyte, transition, False


def processing_fingerprint(rec):
    """What a countersignature on a processing change attests: the change,
    before and after; for a smoothing change its Mid too, as its words
    (Low, Mid or High) are read from it. It counts only while this is
    unchanged."""
    import hashlib
    import json
    fields = PROCESSING_FIELDS + (("mid",) if rec.get("kind") == SMOOTHING else ())
    body = json.dumps(dict((k, rec.get(k)) for k in fields), sort_keys=True)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def processing_signed(rec):
    sig = rec.get("verifier")
    return bool(sig) and sig.get("fp") == processing_fingerprint(rec)


def _processing_trace(rec):
    """What a change replaces: its trace's last change, or, for a smoothing
    change, the compound's last smoothing change, never a trace's."""
    return (rec["analyte"], rec.get("transition"), rec.get("kind") == SMOOTHING)


def record_processing_change(state, analyte, transition, kind, before, after, major, who, when, skipped=(),
                             before_method=False, mid=None, label=None):
    """A change applied to every injection, listed in the run's processing
    history: `before` the trace's change in force on the run until now
    (None for none: the automatic peak, or, with `before_method`, a change
    the method holds, kept as "before_method": True), `after` the change
    made, `major` whether it is countersigned at release, `skipped` the
    [injection, why] that kept their automatic peak. `transition` is None
    for the quantifier. A smoothing change, the compound's, keeps `mid`
    and `label` (SMOOTHING) and names no transition."""
    changes = state.setdefault("processing_changes", [])
    n = max([int(r["id"][1:]) for r in changes if r["id"][1:].isdigit()] or [0]) + 1
    rec = {"id": "P%d" % n, "analyte": analyte, "transition": transition or None, "kind": kind,
           "before": before, "after": after, "major": bool(major),
           "skipped": [list(s) for s in skipped or ()], "by": who, "at": when, "undone": None, "verifier": None}
    if kind == SMOOTHING:
        rec.update(transition=None, mid=mid, label=label)
    if before_method and before is None:
        rec["before_method"] = True
    changes.append(rec)
    _log(state, who, when, rec["id"], "applied to all injections",
         {"kind": [None, kind], "before": [None, before], "after": [None, after]})
    return rec


def processing_open(state):
    """The changes in force: of each trace, its last change not undone."""
    last = {}
    for rec in state.get("processing_changes") or []:
        if not rec.get("undone"):
            last[_processing_trace(rec)] = rec
    return [r for r in state.get("processing_changes") or [] if last.get(_processing_trace(r)) is r]


def undo_processing_change(state, rec_id, who, when):
    """The change in force undone: its before is in force again. ValueError
    for a change undone already, or one a later change replaced."""
    rec = next((r for r in state.get("processing_changes") or [] if r["id"] == rec_id), None)
    if rec is None:
        raise ValueError("%s: there is no such processing change" % rec_id)
    if rec.get("undone"):
        raise ValueError("%s: the processing change was undone already" % processing_label(rec))
    if not any(r is rec for r in processing_open(state)):
        raise ValueError("%s: a later change replaced it; it is not the change in force" % processing_label(rec))
    rec["undone"] = {"by": who, "at": when}
    _log(state, who, when, rec["id"], "processing change undone", {"undone": [None, rec["undone"]]})
    return rec


def countersign_processing(state, who, when, name="", sign_as=None, signature=None, method=None):
    """The verifier countersigns every major change in force at once, the
    run's own and the method's it applies (`method`, method_held's
    {key: record}): with the reviewer sign right in People & Roles and a
    signature on file, and never the person who made one. A change
    countersigned as it stands is kept; nothing to countersign asks
    nothing. Returns what was countersigned."""
    todo = [r for r in processing_open(state) if r.get("major") and not processing_signed(r)]
    held = [h for h in method_held(method) if h["major"] and not method_held_signed(state, h)]
    if not todo and not held:
        return []
    _sign_right("reviewer", sign_as, name or who, "countersign", signature, "processing changes")
    own = [processing_label(r) for r in todo if r.get("by") == who]
    own += [method_held_label(h) for h in held if h["record"].get("by") == who]
    if own:
        raise ValueError("a different person countersigns this processing change: %s" % "; ".join(own))
    for rec in todo:
        rec["verifier"] = {"userid": who, "name": name or who, "at": when, "fp": processing_fingerprint(rec)}
    signed = state.setdefault("method_processing_signed", {})
    for h in held:
        signed[h["key"]] = {"userid": who, "name": name or who, "at": when, "fp": method_held_fingerprint(h)}
    _log(state, who, when, "", "processing changes countersigned",
         {"changes": [None, [r["id"] for r in todo] + [h["key"] for h in held]]})
    return todo + held


# a change the method holds (countersigned from a run as the method's own,
# method_proposals) that the run applied where its own file holds none, as
# its stored peaks show it (raw_review.method_applied): listed on the run as
# the method's processing, and a major one countersigned at release as the
# run's own. The countersignature is kept in the run's state by the change's
# key and counts while the record the run applied is the one signed: a run
# processed again with another record is countersigned again.
#     "method_processing_signed": {key: {"userid", "name", "at", "fp"}}
METHOD_KIND_TEXT = {"integrate": "re-integrated by the method's processing",
                    "fit": "fitted by the method's processing"}


def method_held(method):
    """[{"key", "analyte", "transition", "record", "kind", "major"}] of the
    method's changes the run applied (`method`, {processing key: record},
    read from its stored peaks by raw_review.method_applied), by key."""
    from senaite.pfas.raw_review import parse_processing_key
    out = []
    for key in sorted(method or {}):
        record = method[key] if isinstance(method[key], dict) else {}
        try:
            analyte, transition = parse_processing_key(key)
        except ValueError:
            analyte, transition = key, None
        kind = record.get("kind")
        out.append({"key": key, "analyte": analyte, "transition": transition, "record": record,
                    "kind": kind, "major": kind in PROCESSING_MAJOR_KINDS})
    return out


def method_held_label(held):
    """"PFNA quantifier, fitted by the method's processing"."""
    return "%s %s, %s" % (held["analyte"], held.get("transition") or "quantifier",
                          METHOD_KIND_TEXT.get(held.get("kind"), "changed by the method's processing"))


def method_held_fingerprint(held):
    """What a countersignature on a method-held change attests: its key and
    the method's record."""
    import hashlib
    import json
    body = json.dumps({"key": held["key"], "record": held["record"]}, sort_keys=True)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def method_held_signed(state, held):
    sig = (state.get("method_processing_signed") or {}).get(held["key"])
    return bool(sig) and sig.get("fp") == method_held_fingerprint(held)


# the history's words for a change taken out of the run's processing file
# that had no record: the file was written and its record never saved
PROCESSING_ORPHAN_UNDONE = "undone; no record was saved"
# a change in the file that no record in force shows, and where it is undone
PROCESSING_UNRECORDED = "%s: a processing change has no record; undo it under Processing changes on the Overview tab"
# a record in force whose change the run's file does not hold: the record
# claims a change the run does not apply
PROCESSING_NOT_IN_FILE = ("%s: the recorded processing change is not in the run's file: undo it under "
                          "Processing changes on the Overview tab")


def processing_in_force(state, key):
    """The change in force on record for the trace of a processing key, or
    for the compound of a smoothing key, or None (a key that cannot be
    read has none)."""
    from senaite.pfas.raw_review import parse_processing_key, parse_smoothing_key
    analyte = parse_smoothing_key(key)
    if analyte is not None:
        trace = (analyte, None, True)
    else:
        try:
            trace = parse_processing_key(key) + (False,)
        except ValueError:
            return None
    return next((r for r in processing_open(state) if _processing_trace(r) == trace), None)


def processing_orphans(state, processing):
    """The keys of the run's processing file (`processing`, the whole file
    dict) whose entry is not exactly the change in force on record for its
    trace (its "after", who and when included): a trace with no record in
    force, or one whose file holds another change than its record, sorted.
    Nobody would see or countersign such a change as it is processed. A
    compound's smoothing change is judged so too, by its smoothing key."""
    from senaite.pfas.raw_review import smoothing_key
    traces = (processing or {}).get("traces") or {}
    entries = [(key, traces[key]) for key in traces]
    smoothing = (processing or {}).get("smoothing") or {}
    entries += [(smoothing_key(analyte), smoothing[analyte]) for analyte in smoothing]
    out = []
    for key, entry in sorted(entries):
        rec = processing_in_force(state, key)
        if rec is None or entry != rec.get("after"):
            out.append(key)
    return out


def undo_orphan_processing(state, key, who, when, record=None, restored=None):
    """A change with no record taken out of the run's processing file
    (`record`, the entry removed; `restored`, the change in force on record
    put back in its place, or None): listed as a change not recorded and
    undone, and the history keeps who, when and both."""
    analyte, transition = processing_key_trace(key)[:2]
    entry = record if isinstance(record, dict) else {}
    changes = state.setdefault("processing_changes", [])
    n = max([int(r["id"][1:]) for r in changes if r["id"][1:].isdigit()] or [0]) + 1
    rec = {"id": "P%d" % n, "analyte": analyte, "transition": transition, "kind": entry.get("kind"),
           "before": None, "after": record, "major": entry.get("kind") in PROCESSING_MAJOR_KINDS, "skipped": [],
           "by": entry.get("by") or "", "at": entry.get("at") or "", "undone": {"by": who, "at": when},
           "verifier": None, "recorded": False}
    changes.append(rec)
    _log(state, who, when, rec["id"], PROCESSING_ORPHAN_UNDONE,
         {"key": [key, None], "processing": [record, restored]})
    return rec


# stored peaks smoothed by a smoothing change of the run while none is in
# force on record: the run's file lost it, or the run is not yet processed
# again after an undo
SMOOTHING_UNRECORDED_PEAKS = ("%s: the run's stored peaks are smoothed by a change with no record in force; "
                              "process the run again")
# stored peaks measured by a run's own processing change of a trace while
# no record of it is in force: the file lost it with its record, or the run
# is not yet processed again after an undo
PROCESSING_UNRECORDED_PEAKS = ("%s: the run's stored peaks show a processing change with no record in force; "
                               "process the run again")


def processing_gate(state, phase, processing, method=None, stored_smoothing=None, label=None,
                    stored_processing=None):
    """(ok, [what is missing]): every change in the run's processing file
    (`processing`, the whole file dict) is its trace's record in force
    (processing_orphans), as nobody would see or countersign one without,
    and every record in force has its change in the file, or the record
    claims a change the run does not apply; at verify, every major change in
    force carries the verifier's countersignature. An undone change, and
    a minor one, need nothing. The file is always given ({} for none): a
    gate that read no file would pass a change nobody recorded. `method`
    ({key: record}, method_held): at verify, each major change the method
    holds and the run applies carries the countersignature too.
    `stored_smoothing` ({keyword: change}, raw_review.smoothing_applied):
    the smoothing changes the run's stored peaks name; one with no
    smoothing change in force on record is missing. `label` names a
    compound for a smoothing change's words (processing_key_text).
    `stored_processing` ({key: record}, raw_review.processing_applied):
    the run's own trace changes its stored peaks show; one whose trace has
    no change in force on record is missing, as for smoothing."""
    if processing is None:
        raise ValueError("the processing gate reads the run's processing file: pass {} for none")
    out = [PROCESSING_UNRECORDED % processing_key_text(key, label) for key in processing_orphans(state, processing)]
    for rec in processing_open(state):
        key = processing_rec_key(rec)
        if processing_entry(processing, key) is None:
            out.append(PROCESSING_NOT_IN_FILE % processing_key_text(key, label))
    from senaite.pfas.raw_review import smoothing_key
    for analyte in sorted(stored_smoothing or {}):
        if processing_in_force(state, smoothing_key(analyte)) is None:
            out.append(SMOOTHING_UNRECORDED_PEAKS % processing_key_text(smoothing_key(analyte), label))
    for key in sorted(stored_processing or {}):
        if processing_in_force(state, key) is None:
            out.append(PROCESSING_UNRECORDED_PEAKS % processing_trace_text(key))
    if phase == "verify":
        for rec in processing_open(state):
            if rec.get("major") and not processing_signed(rec):
                out.append("%s: the verifier's countersignature" % processing_label(rec))
        for held in method_held(method):
            if held["major"] and not method_held_signed(state, held):
                out.append("%s: the verifier's countersignature" % method_held_label(held))
    return (not out), out


def raw_label(rec):
    """"S1 / PFOA quantifier, re-integrated"."""
    return "%s / %s %s, %s" % (rec["injection"], rec["analyte"], rec.get("transition") or "quantifier",
                               RAW_KIND_TEXT.get(rec.get("kind"), rec.get("kind") or ""))


def _raw_review():
    """raw_review, the panel's words for a manual peak's line. Read when a
    peak is named, never when the module loads: the worker loads this file
    on its own for is_manual alone."""
    from senaite.pfas import raw_review
    return raw_review


def peak_text(peak):
    """A peak as the review reads it: its edges and area, its apex, or
    deleted, then the line it is measured on and any levels set by hand in
    the panel's words (raw_review.line_text): "11.16 to 11.34 min, area
    181904, perpendicular drop, baseline 4,000 and 4,000"; a fit its shape,
    its peaks and the one reported: "4.10 to 4.50 min, EMG, 2 peaks, peak 1
    reported" (its area is the worker's, once fitted). A record with no
    version reads its baseline through raw_review.LEGACY_BASELINES ("drop"
    is the flat baseline, never the perpendicular drop)."""
    if not peak:
        return "no peak"
    if peak.get("deleted"):
        return "peak deleted"
    parts = []
    if peak.get("start") is not None and peak.get("end") is not None:
        parts.append("%.2f to %.2f min" % (peak["start"], peak["end"]))
    elif peak.get("apex") is not None:
        parts.append("apex %.2f min" % peak["apex"])
    if peak.get("area") is not None:
        parts.append("area %.0f" % peak["area"])
    if peak.get("shape"):
        parts.append(_raw_review().fit_words(peak["shape"], len(peak.get("apexes") or ())))
        if isinstance(peak.get("pick"), int):
            parts.append("peak %d reported" % (peak["pick"] + 1))
    if peak.get("baseline"):
        rr = _raw_review()
        baseline = peak["baseline"]
        if peak.get("version") is None:
            baseline = rr.LEGACY_BASELINES.get(baseline, baseline)
        parts.append(rr.line_text(baseline, peak.get("levels")))
    return ", ".join(p for p in parts if p) or "no peak"


def raw_summary(rec):
    """"<automatic> -> <now>"."""
    return "%s → %s" % (peak_text(rec.get("before")), peak_text(rec.get("after")))


def _stale_capture(state, imported_at):
    """Whether the kept mark predates the run's latest import."""
    mark = state.get("migrated_captured") or {}
    return bool(mark and imported_at and (mark.get("at") or "") < imported_at)


def captured(state, detected, imported_at=""):
    """Whether the run's manual integrations were captured: as the export
    says, or as kept on the state (migrated_captured) when its records
    moved to raw changes. The kept mark no longer counts once the run is
    imported again after it (`imported_at`): the confirmation is asked
    again."""
    if detected:
        return True
    return bool(state.get("migrated_captured")) and not _stale_capture(state, imported_at)


def clear_stale_capture(state, imported_at, who, when, released=False):
    """Drop the kept mark when the run was imported again after it, saying
    so in the history; True when dropped. A released worksheet (`released`:
    verified or published) keeps its mark: its release stands as it was."""
    if released or not _stale_capture(state, imported_at):
        return False
    mark = state.pop("migrated_captured")
    _log(state, who, when, "", "captured mark cleared: the run was imported again",
         {"migrated_captured": [mark, None], "imported": [None, imported_at]})
    return True


def vendor_detections(rows):
    """([{"injection", "analyte", "qc_type"}] flagged manual, captured) from
    rows (injection, analyte, qc_type, flag, derived_from). A row the LIMS
    integrated from raw data (derived_from "raw:...") is not the export's:
    its manual changes are the Integration Review tab's. A run whose every reported
    row the LIMS integrated is captured: nothing in it is the export's to
    flag."""
    raw = [r for r in rows if ("%s" % (r[4] or "")).startswith("raw:")]
    rows = [r for r in rows if not ("%s" % (r[4] or "")).startswith("raw:")]
    captured = any(r[3] is not None for r in rows) or bool(raw and not rows)
    flagged, seen = [], set()
    for inj, an, qc, flag, _derived in rows:
        if flag and (inj, an) not in seen:
            seen.add((inj, an))
            flagged.append({"injection": inj, "analyte": an, "qc_type": qc or ""})
    return flagged, captured
