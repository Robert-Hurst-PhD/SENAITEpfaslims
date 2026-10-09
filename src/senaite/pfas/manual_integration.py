# -*- coding: utf-8 -*-
"""Manual integration: detection, reasons and records.

when the import captures a manual integration, or the
instrument report shows one, each must be justified from a list of reasons
and signed (analyst, then reviewer), and the report's before / after pages
stamped with the justification. The documentation follows the VELAP Manual
Integration Technical Assistance Document (Virginia DCLS, 11/30/2016) §5.2,
and the North Carolina DEQ Manual Integration Policy (04/09/2010).

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
     "stamped": {"file", "fp", "of", "at", "by"} | None}

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

Pure: Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

# a cell meaning "nothing changed"
_EMPTY = frozenset(("", "0", "no", "n", "false", "none", "-", "nan", "n/a", "na"))

# The starting list. Verbatim from the sources; a manager
# edits the list, these only seed it.
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
            "history": [], "stamped": None, "heading_scan": None, "dismissed": {}}


def _log(state, who, when, rec_id, action, changes=None):
    state.setdefault("history", []).append(
        {"at": when, "by": who, "id": rec_id or "", "action": action, "changes": changes or {}})


def _find(state, rec_id):
    for r in state.get("records") or []:
        if r["id"] == rec_id:
            return r
    raise KeyError(rec_id)


def _new_id(state):
    n = max([int(r["id"].split("-")[-1]) for r in state.get("records") or []
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

