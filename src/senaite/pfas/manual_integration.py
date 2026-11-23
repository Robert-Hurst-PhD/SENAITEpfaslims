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

Changes made on the Raw Data tab are kept apart from the report's records
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
            "raw_changes": []}


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


# ── changes made on the Raw Data tab ───────────────────────────────────────

# the People & Roles sign right each signature needs, the instrument report's
# records and the Raw Data changes alike
SIGN_RIGHT = {"analyst": "preparer", "reviewer": "reviewer"}
RAW_KINDS = ("integrate", "apex", "delete")
RAW_KIND_TEXT = {"integrate": "re-integrated", "apex": "another apex", "delete": "peak deleted"}
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
    body = json.dumps(dict((k, rec.get(k)) for k in ("injection", "analyte", "transition") + RAW_FIELDS),
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


def _sign_right(role, sign_as, name, act, signature=None):
    """ValueError when People & Roles gives the person (`name`) no sign right for
    `role`, or when they have no signature on file (`signature` False), as
    the instrument report's records ask; None is not checked."""
    if sign_as is not None and SIGN_RIGHT[role] not in sign_as:
        raise ValueError("%s has no %s sign right in People & Roles, so does not %s manual changes"
                         % (name, SIGN_RIGHT[role], act))
    if signature is not None and not signature:
        raise ValueError("%s has no signature on file, so does not %s manual changes" % (name, act))


def record_raw_edit(state, injection, analyte, transition, kind, before, after, who, when,
                    qc_type="", quant_transition=None):
    """An edit made on the Raw Data tab: no reason is asked. The trace's one
    record is made, or updated (also after an undo); the automatic peak
    (before) is the first edit's. A real change clears the signatures; the
    same edit posted again changes nothing. after: the edges, apex, area,
    the line it is measured on ("baseline"), any levels set by hand and the
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
    if rec is None:
        rec = {"id": _raw_new_id(state), "injection": injection, "analyte": analyte,
               "transition": transition, "qc_type": qc_type or "", "kind": kind,
               "before": before, "after": None, "by": who, "at": when, "dropped": None,
               "reason_id": "", "reason": "", "detail": "", "analyst": None, "verifier": None}
        state.setdefault("raw_changes", []).append(rec)
        changes = {"kind": [None, kind], "before": [None, before], "after": [None, after]}
    else:
        if not rec.get("dropped") and rec.get("kind") == kind and rec.get("after") == after:
            return rec
        changes = {"after": [rec.get("after"), after]}
        if rec.get("kind") != kind:
            changes["kind"] = [rec.get("kind"), kind]
        if rec.get("dropped"):
            changes["undone"] = [rec["dropped"], None]
        if rec.get("before") is None and before is not None:
            rec["before"] = before
        _clear_signatures(rec, changes)
    rec.update(kind=kind, after=after, by=who, at=when, dropped=None)
    _log(state, who, when, rec["id"], "edited on the Raw Data tab", changes)
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
    _log(state, who, when, rec["id"], "undone on the Raw Data tab", changes)
    return rec


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
_RAW_EDITED = ("edited on the Raw Data tab", "re-integrated")
_RAW_UNDONE = "undone on the Raw Data tab"


def raw_editors(state, rec):
    """The user ids who edited this change's peak since its last undo: the
    last editor and every edit the history keeps after the last undo."""
    who = set([rec["by"]]) if rec.get("by") else set()
    for h in state.get("history") or []:
        if h.get("id") != rec["id"]:
            continue
        if h.get("action") == _RAW_UNDONE:
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
            out.append("%s: an edit has no record; undo it on the Raw Data tab" % key)
            continue
        rec = _raw_find(state, injection, analyte, transition)
        if rec is None or rec.get("dropped"):
            out.append("%s / %s: an edit has no record; undo it on the Raw Data tab" % (injection, analyte))
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
    181904, perpendicular drop, baseline 4,000 and 4,000". A record with no
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
    its manual changes are the Raw Data tab's. A run whose every reported
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
