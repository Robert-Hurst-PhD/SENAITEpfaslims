# -*- coding: utf-8 -*-
"""The batch record: one worksheet's record from receipt to release.

The worksheet's guided extraction is its record, kept under the method
revision the extraction started with and its own copy of the stage plan
(stage_plan.py). This module puts the parts every store already holds
together, each one a plain structure read by the page:

    {"worksheet", "title", "method", "method_id", "revision", "matrix", "client",
     "state", "progress": [done, planned],
     "parts": {"receipt":  the samples' CoC summary (coc_records.summary),
               "members":  the extraction batch's members (extraction_batch.load),
               "stages":   every planned stage, recorded or not (extraction_review.review),
               "loaded":   {"standards", "solvents"} the run was loaded with (run manifest),
               "run":      the built run's injection list (run_lots.injection_list),
               "review":   Data Review's checklist,
               "identity": the injections' identity corrections at review, only
                           when there are any,
               "amendments": the extraction corrections made before release
                           (extraction_amendments.record_part), only when
                           there are any,
               "amendments_after_release": those made after it, only when
                           there are any},
     "amendment_log": the corrections log as stored (never hashed),
     "record_revision": 1 as released, one more per amendment after it,
     "revision_words": "Record rev 1", or "Record rev 2 · amended after release",
     "corrections": corrections() of the record, "chips": chips() of it}

Where a record is (state):

    not_started  no extraction session
    open         the extraction is started, not finalised
    finalised    the extraction is finalised
    run_built    the run is built: the manifest names when, or holds its rows
    released     released: the checklist names who approved it, or the
                 worksheet is verified (or published) by any route

The record's hash covers what was done -- the method id and revision,
receipt, members, stages, loaded, run -- never where the record is (state,
progress) nor the review: a signature binds to the work, and the release is
its own act. The title is printed but not hashed: it carries the method's
display name, and renaming a method changes nothing that was done.

Two people sign it (esig.signing, kind "batch_record", record id the
worksheet id): the finaliser attests the extraction as its preparer, bound to
extraction_hash (method id and revision, receipt, members, stages), since
the run is built after the extraction is finalised; the approver attests the
whole record as its reviewer, bound to record_hash. The ledger is the truth;
the extraction session keeps a display cache under "signatures".

A correction of the finalised extraction (extraction_amendments) never
edits the stored members, stages or session, so the preparer's extraction
hash never moves. The corrections made before release enter the reviewer's
record hash, only when there are any, as the identity corrections do; those
made after release are the record's next revision, signed by the Lab
Manager who made them (sign_corrected, meaning "corrected") over
revision_hash, so the release signature keeps verifying revision 1.

Pure, standard library only. Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import re

from senaite.pfas.esig import canonical

NOT_STARTED, OPEN, FINALISED, RUN_BUILT, RELEASED = (
    "not_started", "open", "finalised", "run_built", "released")
STATES = (NOT_STARTED, OPEN, FINALISED, RUN_BUILT, RELEASED)
STATE_LABELS = {
    NOT_STARTED: "Not started",
    OPEN: "Open",
    FINALISED: "Finalised",
    RUN_BUILT: "Run built",
    RELEASED: "Released",
}
# the checklist key Data Review's Approve Release writes (the study review's
# approval too); a saved checklist carries it unset until then
RELEASE_KEY = "approved_by"
# worksheet review states that mean released, however it was verified
RELEASED_REVIEW_STATES = frozenset(("verified", "published"))
# the parts of a record its hash covers: the method by its id, never its
# display name
HASHED = ("method_id", "revision")
HASHED_PARTS = ("receipt", "members", "stages", "loaded", "run")
# the injections' identity corrections at review (injection_identity): a
# part of the record, and of the reviewer's hash, only when there are any
IDENTITY_PART = "identity"
# the extraction corrections (extraction_amendments.record_part): the part
# made before release binds the reviewer, only when there are any; the part
# made after release is the record's next revision, bound by its own
# signature (revision_hash)
AMENDMENTS_PART = "amendments"
AFTER_RELEASE_PART = "amendments_after_release"
CORRECTED = "corrected"
# Verify's send backs (review_send_back): likewise only when there are any
SEND_BACK_PART = "send_back"
# what the finaliser attests: the extraction, before any run is built
EXTRACTION_PARTS = ("receipt", "members", "stages")
# what the extraction hash leaves out of those parts: the subtraction blank
# a member is marked as (chosen at review), and the CoC's client and project
# names (corrected on a received CoC); the samples, CoC numbers, receipt
# dates and statuses stay in
MEMBER_REVIEW_KEYS = ("subtract",)
RECEIPT_DESCRIPTIVE = ("client_name", "project_name")
# Approve Release over a preparer signature on other content
EXTRACTION_CHANGED = "The extraction changed after it was finalised: send it back to be finalised again."
KIND = "batch_record"
# the preparer cell of a record finalised before signatures were kept
FINALISED_BEFORE = "Finalised before signatures"
# the queue's word for a record's signatures (signature_word)
SIGNED, PARTLY_SIGNED, CHANGED, UNSIGNED = "Signed", "Partly signed", "Changed", "Unsigned"
UNREADABLE = "unreadable"
UNREADABLE_LABEL = "Could not be read"

_SEP = "·"


def title(ws_id, method_title, revision):
    """"WS-329 · EPA 1633A r4.1"; a revision stored as an integer predates
    major.sub and reads "r3.0" (method_revisions.revision_text); no
    revision, no "r"; no method, the worksheet alone. The title is printed,
    never hashed: the record keeps the revision as stored."""
    if not method_title:
        return ws_id or ""
    out = "%s %s %s" % (ws_id or "", _SEP, method_title)
    if revision is not None:
        from senaite.pfas.method_revisions import revision_text
        out += " r" + revision_text(revision)
    return out


def state(session, manifest, checklist, review_state=""):
    """Where the record is, the furthest step reached first. `review_state`,
    the worksheet's: a worksheet verified outside Approve Release is
    released too."""
    session, manifest, checklist = session or {}, manifest or {}, checklist or {}
    if checklist.get(RELEASE_KEY) or (review_state or "") in RELEASED_REVIEW_STATES:
        return RELEASED
    if manifest.get("built_at") or manifest.get("rows"):
        return RUN_BUILT
    if session.get("finalized"):
        return FINALISED
    if session:
        return OPEN
    return NOT_STARTED


# the states a finalised extraction stands in: a planned stage missing in
# one of them is a record finalised before Finalise refused it
_FINALISED_OR_LATER = (FINALISED, RUN_BUILT, RELEASED)


def missing_stages(record):
    """The planned stages a record holds no entry for, [(order, name)], in
    plan order (its "stages" part, each row marked recorded or not)."""
    rows = ((record or {}).get("parts") or {}).get("stages") or []
    return [(r.get("order"), _text(r.get("name") or "")) for r in rows
            if isinstance(r, dict) and not r.get("recorded")]


def not_recorded_note(missing):
    """"stages 3 Concentration and 5 Reconstitution not recorded" for the
    planned stages a finalised record lacks; "" for none."""
    if not missing:
        return ""
    named = " and ".join(("%s %s" % (_text(o), n)).strip() for o, n in missing)
    return "%s %s not recorded" % ("stages" if len(missing) > 1 else "stage", named)


def state_label(record):
    """The record's state in words; a record whose extraction was finalised
    with planned stages missing says which ("Finalised, stage 3
    Concentration not recorded"), whatever step it reached since: the gap
    is never hidden. A worksheet released with no guided extraction is
    not one."""
    st = (record or {}).get("state") or NOT_STARTED
    labels = dict(STATE_LABELS)
    labels[UNREADABLE] = UNREADABLE_LABEL
    label = labels.get(st, st)
    if st in _FINALISED_OR_LATER and (record or {}).get("finalised"):
        note = not_recorded_note(missing_stages(record))
        if note:
            return "%s, %s" % (label, note)
    return label


def progress(session, stages):
    """(stages recorded, stages planned): only the plan's stages count."""
    done = set("%s" % k for k in ((session or {}).get("stages") or {}))
    planned = ["%s" % s.get("order") for s in stages or [] if isinstance(s, dict)]
    return len([o for o in planned if o in done]), len(planned)


def _stage_rows(stages_review):
    """The review's stage rows: extraction_review.review()'s "stages", or
    the list itself."""
    if isinstance(stages_review, dict):
        return list(stages_review.get("stages") or [])
    return list(stages_review or [])


def _text(value):
    """A value as text: a UTF-8 byte string (Python 2) decoded, never
    raising on a non-ASCII title."""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return u"%s" % (value,)


def joined(values):
    """The distinct values, sorted, as one line of text: a worksheet's
    samples may span matrices or clients."""
    return u", ".join(sorted(set(_text(v) for v in values or () if v)))


def assemble(ws_id, method_title, revision, receipt, members, stages_review, loaded, run, review,
             session=None, manifest=None, review_state="", method_id="", matrix="", client="",
             identity=None, amendments=None, send_back=None):
    """The record of one worksheet. `session`, the extraction session, says
    whether the extraction is started and finalised, and which stages are
    recorded; `manifest`, the run manifest, whether the run is built;
    `review_state`, the worksheet's. Without them the record is not started.
    `method_id` names the method in the hash; `matrix` and `client`, the
    samples', are shown, not hashed (the receipt holds the samples).
    `identity`, the injections' identity corrections at review
    (injection_identity.record_part): a part only when there are any, and
    then in the reviewer's hash. `amendments`, the worksheet's extraction
    corrections as stored (extraction_amendments.KEY, JSON or a dict): the
    part made before release in the reviewer's hash, the part made after
    it in the revision's, each only when there are any; the members part
    stays the members as finalised.
    `send_back`, Verify's send backs (review_send_back.record_part): a part
    only when there are any, in the reviewer's hash."""
    stages = _stage_rows(stages_review)
    record = {
        "worksheet": ws_id or "",
        "title": title(ws_id, method_title, revision),
        "method": method_title or "",
        "method_id": method_id or "",
        "revision": revision,
        "matrix": matrix or "",
        "client": client or "",
        # the print needs an extraction session, whatever the state says
        "printable": bool(session),
        "state": state(session, manifest, review, review_state),
        # whether the extraction itself was finalised, whatever step the
        # record reached since (shown, never hashed)
        "finalised": bool((session or {}).get("finalized")),
        "progress": list(progress(session, stages)),
        "parts": {
            "receipt": receipt or {},
            "members": list(members or []),
            "stages": stages,
            "loaded": loaded or {},
            "run": list(run or []),
            "review": review or {},
        },
    }
    if identity:
        record["parts"][IDENTITY_PART] = list(identity)
    if send_back:
        record["parts"][SEND_BACK_PART] = list(send_back)
    from senaite.pfas import extraction_amendments as ea
    log = ea.load(amendments)
    before, after = ea.record_part(log), ea.record_part(log, after_release=True)
    if before:
        record["parts"][AMENDMENTS_PART] = before
    if after:
        record["parts"][AFTER_RELEASE_PART] = after
    record["amendment_log"] = log["log"]
    record["record_revision"] = ea.revision(log)
    record["revision_words"] = revision_words(record["record_revision"])
    record["corrections"] = corrections(record)
    record["chips"] = chips(record)
    return record


def record_hash(record):
    """sha256 hex over what the record says was done (HASHED, HASHED_PARTS)
    as canonical JSON: keys sorted, no spaces, non-ASCII escaped. Its
    signatures, state, progress and review are not hashed. A value JSON
    cannot hold raises: the hash never stands for a guess at it."""
    record = record or {}
    parts = record.get("parts") or {}
    body = dict((k, record.get(k)) for k in HASHED)
    body["parts"] = dict((k, parts.get(k)) for k in HASHED_PARTS)
    # the identity corrections bind the reviewer only when there are any: a
    # record with none hashes as it always did
    if parts.get(IDENTITY_PART):
        body["parts"][IDENTITY_PART] = parts[IDENTITY_PART]
    if parts.get(SEND_BACK_PART):
        body["parts"][SEND_BACK_PART] = parts[SEND_BACK_PART]
    # so do the extraction corrections made before release
    if parts.get(AMENDMENTS_PART):
        body["parts"][AMENDMENTS_PART] = parts[AMENDMENTS_PART]
    return canonical.sha256_of(body)


def _body_of(record):
    return dict((k, (record or {}).get(k)) for k in HASHED)


def revision_hash(record):
    """sha256 hex over the record in force after release: what record_hash
    covers and the corrections made after release. With none, the record
    hash itself: revision 1 is the record as released."""
    record = record or {}
    after = (record.get("parts") or {}).get(AFTER_RELEASE_PART)
    if not after:
        return record_hash(record)
    parts = record.get("parts") or {}
    body = _body_of(record)
    body["parts"] = dict((k, parts.get(k)) for k in HASHED_PARTS)
    for key in (IDENTITY_PART, SEND_BACK_PART, AMENDMENTS_PART):
        if parts.get(key):
            body["parts"][key] = parts[key]
    body["parts"][AFTER_RELEASE_PART] = after
    return canonical.sha256_of(body)


def extraction_hash(record):
    """sha256 hex over the extraction the finaliser attests (HASHED,
    EXTRACTION_PARTS), as record_hash: the run and the lots it was loaded
    with are left out, so building the run leaves the extraction signed;
    so are the members' subtraction-blank mark and the receipt's client and
    project names (MEMBER_REVIEW_KEYS, RECEIPT_DESCRIPTIVE), which review
    and a CoC correction change after the extraction is done."""
    record = record or {}
    parts = dict(record.get("parts") or {})
    if isinstance(parts.get("receipt"), dict):
        parts["receipt"] = dict((k, v) for k, v in parts["receipt"].items() if k not in RECEIPT_DESCRIPTIVE)
    if isinstance(parts.get("members"), list):
        parts["members"] = [dict((k, v) for k, v in m.items() if k not in MEMBER_REVIEW_KEYS)
                            if isinstance(m, dict) else m for m in parts["members"]]
    body = dict((k, record.get(k)) for k in HASHED)
    body["parts"] = dict((k, parts.get(k)) for k in EXTRACTION_PARTS)
    return canonical.sha256_of(body)


def hashes(record):
    """{meaning: the hash its signer attests}: the preparer the extraction,
    the reviewer the whole record."""
    out = {"preparer": extraction_hash(record), "reviewer": record_hash(record)}
    # a record amended after release: its corrections' signer attests the
    # revision
    if ((record or {}).get("parts") or {}).get(AFTER_RELEASE_PART):
        out[CORRECTED] = revision_hash(record)
    return out


def _record_id(ws):
    return ws.getId() if hasattr(ws, "getId") else (ws or "")


def signatures_of(ws, record, path=None):
    """esig.signing.status of the worksheet's record: each meaning read
    against the hash its signer attests (hashes)."""
    from senaite.pfas.esig import signing
    return signing.status(KIND, _record_id(ws), record_hash(record), path=path, hashes=hashes(record))


def _supersedes(st, meaning, request):
    """The seq of the valid row of meaning on this content when another
    person signed it: one signer of a meaning stands; None otherwise (the
    same person reuses their row, other content is superseded by the
    signing core)."""
    from senaite.pfas.esig import signing
    earlier = st["valid"].get(meaning)
    if earlier is not None and signing.signer_of(earlier) != signing.current_userid(request):
        return earlier["seq"]
    return None


def sign_finalised(portal, request, record, note="", path=None):
    """Sign the record's extraction as its preparer, the current user; the
    display cache of the row. A re-finalise of changed content supersedes
    the earlier preparer row (the signing core); of the same content by
    another person, that person's row is superseded here, so one preparer
    stands; by the same person, their row is reused. Raises
    signing.SignatureRefused or ledger.LedgerError."""
    from senaite.pfas.esig import signing
    st = signatures_of(record.get("worksheet"), record, path=path)
    row = signing.sign(portal, request, KIND, record.get("worksheet"), record.get("revision"),
                       extraction_hash(record), "preparer", note=note,
                       supersedes=_supersedes(st, "preparer", request), path=path)
    return signing.cache([row])


def sign_approved(portal, request, record, note="", path=None):
    """Sign the whole record as its reviewer, the current user, before
    anything is released; the display cache of the row. The finaliser may
    not approve (the signing core reads every live row of the record). An
    extraction signed by its finaliser and changed since must be finalised
    again first: a record is never released over a preparer signature on
    other content; one finalised before signatures were kept (no preparer
    row) is approved alone. Another approver of the same content supersedes
    the earlier one. Raises signing.SignatureRefused or ledger.LedgerError."""
    from senaite.pfas.esig import signing
    st = signatures_of(record.get("worksheet"), record, path=path)
    signed = [r for r in st["live"] if (r.get("entry") or {}).get("meaning") == "preparer"]
    if signed and "preparer" not in st["valid"]:
        raise signing.SignatureRefused([EXTRACTION_CHANGED])
    row = signing.sign(portal, request, KIND, record.get("worksheet"), record.get("revision"),
                       record_hash(record), "reviewer", note=note,
                       supersedes=_supersedes(st, "reviewer", request), path=path)
    return signing.cache([row])



# ── the corrections of a finalised extraction ──────────────────────────────
#
# One row per entry of the corrections log (extraction_amendments): every
# amendment, send back, re-extraction and undo, oldest first. A confirmation
# is the countersign of the entry it confirms, and a link the worksheet a
# re-extraction was done in: each is shown on that entry's row.

KIND_WORDS = {"amend": "Amended", "send_back": "Sent back", "reextract": "Re-extraction",
              "revert": "Undone"}
CHIP_ORDER = ("amend", "send_back", "reextract")
AWAITING = "Awaiting countersign"
COUNTERSIGNED = "Countersigned by %s, %s"
UNDONE_BY = "Undone by %s"
CLOSED = "Closed: recorded again"
REPLACED_BY = "Replaced by %s"
SIGNED_REV = "Signed, record rev %d"
NOT_SIGNED_REV = "Not signed, record rev %d"
REV_ONLY = "Record rev %d"
WITHHELD_WORD = "Withheld"
REEXTRACTED_IN = "Re-extracted in %s"
REV_WORDS = "Record rev %d"
AMENDED_AFTER = "Record rev %d · amended after release"
# signing a correction made after release (sign_corrected)
NOT_AFTER_RELEASE = "%s is not an amendment made after release: it is countersigned at verification."
UNDONE = "%s is undone: it is not signed."
NOT_RELEASED = "The record is not released: its corrections are countersigned at verification."
NOT_AUTHOR = "%s was made by another person: the Lab Manager who made it signs it."


def revision_words(rev):
    """"Record rev 1" as released; "Record rev 2 · amended after release"
    once amended after it."""
    try:
        rev = int(rev or 1)
    except (TypeError, ValueError):
        rev = 1
    return REV_WORDS % rev if rev <= 1 else AMENDED_AFTER % rev


def _log_and_members(record_or_ws):
    """(the corrections log, the members as finalised) of a record
    (assemble) or a worksheet."""
    if isinstance(record_or_ws, dict):
        parts = record_or_ws.get("parts") or {}
        return list(record_or_ws.get("amendment_log") or []), list(parts.get("members") or [])
    from senaite.pfas import annotation_store, extraction_batch
    from senaite.pfas import extraction_amendments as ea
    state = ea.load(annotation_store.read_json(record_or_ws, ea.KEY, {}))
    return state["log"], list(extraction_batch.load(record_or_ws) or [])


def _revisions(log):
    """{entry id: the record revision it made} of each amendment made after
    release and not undone, in log order."""
    from senaite.pfas import extraction_amendments as ea
    out, n = {}, 1
    for e in ea.entries_in_force({"log": log}, (ea.AMEND,)):
        if e.get("after_release"):
            n += 1
            out[e.get("id")] = n
    return out


def revision(record_or_ws):
    """The record's revision: 1 as released, one more per amendment made
    after release and in force (extraction_amendments.revision)."""
    from senaite.pfas import extraction_amendments as ea
    log, _members = _log_and_members(record_or_ws)
    return ea.revision({"log": log})


def _signed_ids(st):
    """The entry ids a "corrected" ledger row names (its note starts with
    the entry id, sign_corrected)."""
    out = set()
    for r in (st or {}).get("rows") or []:
        e = r.get("entry") or {}
        if e.get("meaning") == CORRECTED:
            out.add(_text(e.get("note") or "").split(",")[0].strip())
    return out


def _words(entry, field, value, names):
    """A fact as the lab reads it: a member by its name."""
    value = _text(value if value is not None else "")
    if field == "parent" and value:
        return names.get(value) or value
    return value


def _before_after(entry, by_id, names, links):
    from senaite.pfas import extraction_amendments as ea
    act = entry.get("action")
    if act == ea.AMEND:
        field = entry.get("field")
        before = [_words(entry, field, entry.get("from"), names)]
        after = [_words(entry, field, entry.get("to"), names)]
        for k, pair in sorted((entry.get("also") or {}).items()):
            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                label = ea.FIELD_LABELS.get(k, k).lower()
                before.append("%s %s" % (label, _text(pair[0])))
                after.append("%s %s" % (label, _text(pair[1])))
        name = entry.get("name")
        if isinstance(name, (list, tuple)) and len(name) == 2 and name[1]:
            before.append("name %s" % _text(name[0]))
            after.append("name %s" % _text(name[1]))
        return ", ".join(v for v in before if v), ", ".join(v for v in after if v)
    if act == ea.SEND_BACK:
        target = dict(ea.TARGETS).get(entry.get("to"), entry.get("to") or "")
        if entry.get("stage"):
            target = "%s from stage %s" % (target, entry["stage"])
        state = _text(ea.STATE_WORDS.get(entry.get("from_state"), entry.get("from_state") or ""))
        return state[:1].upper() + state[1:], _text(target)
    if act == ea.REEXTRACT:
        ws = links.get(entry.get("id"))
        return "", (REEXTRACTED_IN % ws) if ws else WITHHELD_WORD
    if act == ea.REVERT:
        target = by_id.get(entry.get("reverts")) or {}
        return (_words(target, target.get("field"), target.get("to"), names),
                _words(target, target.get("field"), target.get("from"), names))
    return "", ""


def corrections(record_or_ws, fullname=None, st=None):
    """The record's corrections, one row per entry, oldest first: every
    amendment, send back, re-extraction and undo (a confirmation and a
    re-extraction's link show on the entry they name). `record_or_ws`, a
    record (assemble) or a worksheet. `fullname`, a user id to the
    person's name (else the name kept on the entry, else the id); `st`,
    signatures_of the record: with it an amendment made after release says
    whether its signature is in the ledger. Each row:

        {"id": "EA-1", "action": "amend" | "send_back" | "reextract" | "revert",
         "kind": "Amended" | "Sent back" | "Re-extraction" | "Undone",
         "what": "Amended 537_DW_LFB-M_261113-01 level" (extraction_amendments.describe),
         "target": the member's issued name or the sample, "" for the batch,
         "field": "Level", or "" when not one fact,
         "before": "Mid, amount 80", "after": "High, amount 160",
         "reason", "by": a name, "at": on the laboratory's clock,
         "in_force": True while it stands (not undone, not recorded again),
         "undone_by": the undo's id or "",
         "after_release": True for an amendment made after release,
         "record_rev": the revision it made, or None,
         "countersigned": True once confirmed (or signed, after release),
         "countersign": "Countersigned by NAME, 2026-11-20 10:00" | "Awaiting countersign"
                        | "Signed, record rev 2" | "Not signed, record rev 2" | "Record rev 2"
                        | "Undone by EA-3" | "Closed: recorded again" | "Replaced by EA-4" | "",
         "can_undo": True for an amendment made before release, in force and not confirmed}

    "Record rev N" is said when no `st` was given. Without a log, []."""
    from senaite.pfas import extraction_amendments as ea
    from senaite.pfas import lab_time
    log, members = _log_and_members(record_or_ws)
    if not log:
        return []
    state = {"log": log}
    by_id = dict((e.get("id"), e) for e in log)
    names = dict((m.get("id"), m.get("injection") or m.get("id")) for m in members)
    links = ea.links(state)
    standing = set(e.get("id") for e in ea.entries_in_force(state, ea.CONFIRMED_KINDS))
    undone = dict((e.get("reverts"), e.get("id")) for e in log if e.get("action") == ea.REVERT)
    confirms = dict((e.get("confirms"), e) for e in log if e.get("action") == ea.CONFIRM)
    revs = _revisions(log)
    signed = _signed_ids(st) if st is not None else None
    # the amendment of each member's fact that applies; one whose stored
    # value is no longer the one it corrected is closed (the fact was
    # recorded again after a send back), one a later amendment of the same
    # fact replaced is not applied
    applied = ea.amendments_in_force(state, members)
    live = set(e.get("id") for e in applied.values())
    by_member = dict((m.get("id"), m) for m in members)

    def closed(e):
        m = by_member.get(e.get("member"))
        if m is None:
            return False
        stored = m.get("sample_id") if e.get("field") == ea.SAMPLE else m.get(e.get("field"))
        return _text(stored or "") != _text(e.get("from") or "")

    def who(e, kept=""):
        by = e.get("by") or ""
        if fullname and by:
            name = fullname(by)
            if name:
                return _text(name)
        return _text(kept or by)

    rows = []
    for e in log:
        act = e.get("action")
        if act not in KIND_WORDS:
            continue
        eid = e.get("id") or ""
        before, after = _before_after(e, by_id, names, links)
        # a sample row's amendment is read without the extraction table:
        # it stands while it is not undone
        in_force = eid in standing and (act != ea.AMEND or bool(e.get("sample")) or eid in live)
        replaced = ""
        if act == ea.AMEND and e.get("member") and eid in standing and eid not in live and not closed(e):
            later = applied.get((e.get("member"), e.get("field"))) or {}
            replaced = later.get("id") or ""
        conf = confirms.get(eid)
        rev = revs.get(eid)
        if act == ea.REVERT:
            countersign, done = "", False
        elif eid in undone:
            countersign, done = UNDONE_BY % undone[eid], False
        elif e.get("after_release"):
            if signed is None:
                countersign, done = REV_ONLY % (rev or 1), False
            elif eid in signed:
                countersign, done = SIGNED_REV % (rev or 1), True
            else:
                countersign, done = NOT_SIGNED_REV % (rev or 1), False
        elif conf is not None:
            countersign, done = COUNTERSIGNED % (who(conf, conf.get("name")),
                                                 lab_time.show(conf.get("at"))), True
        elif act == ea.AMEND and e.get("member") and eid in standing and closed(e):
            countersign, done = CLOSED, False
        elif replaced:
            countersign, done = REPLACED_BY % replaced, False
        else:
            countersign, done = AWAITING, False
        target = e.get("member") or e.get("sample") or ""
        rows.append({
            "id": eid, "action": act, "kind": KIND_WORDS[act],
            "what": _text(ea.describe(e, members)),
            "target": _text(names.get(target) or target),
            "field": _text(ea.FIELD_LABELS.get(e.get("field"), e.get("field") or "")) if act == ea.AMEND else "",
            "before": _text(before), "after": _text(after),
            "reason": _text(e.get("reason") or ""),
            "by": who(e, e.get("name_by")),
            "at": lab_time.show(e.get("at")),
            "in_force": bool(in_force) if act != ea.REVERT else False,
            "undone_by": undone.get(eid, ""),
            "after_release": bool(e.get("after_release")),
            "record_rev": rev,
            "countersigned": done,
            "countersign": countersign,
            "can_undo": bool(act == ea.AMEND and eid in standing and conf is None
                             and not e.get("after_release")),
        })
    return rows


def chips(record_or_ws):
    """The header's words for what was done to the record, in this order:
    "Amended" (an amendment not undone), "Sent back", "Re-extraction"."""
    from senaite.pfas import extraction_amendments as ea
    log, _members = _log_and_members(record_or_ws)
    kinds = set(e.get("action") for e in ea.entries_in_force({"log": log}))
    return [KIND_WORDS[k] for k in CHIP_ORDER if k in kinds]


def sign_corrected(portal, request, record, entry, note="", path=None):
    """Sign an amendment made after release as the record's next revision:
    a ledger row of kind batch_record, meaning "corrected", over
    revision_hash of `record`, which is assembled with the amendment in its
    log. `entry`, the amendment or its id. The release signature keeps
    binding revision 1 (record_hash leaves the part made after release
    out). Refused unless the entry is an amendment made after release and
    in force, the record is released, and the signer is the Lab Manager who
    made it and holds the reviewer sign right; the signing core refuses
    the rest (credentials, staff record, image). The row's note starts
    with the entry id and names the revision. A later revision's row
    supersedes the earlier one. Returns the display cache of the row.
    Raises signing.SignatureRefused or ledger.LedgerError."""
    from senaite.pfas.esig import signing
    from senaite.pfas import extraction_amendments as ea
    record = record or {}
    eid = _text((entry or {}).get("id") if isinstance(entry, dict) else (entry or ""))
    log = list(record.get("amendment_log") or [])
    target = dict((e.get("id"), e) for e in log).get(eid)
    if target is None or target.get("action") != ea.AMEND or not target.get("after_release"):
        raise signing.SignatureRefused([NOT_AFTER_RELEASE % (eid or "That")])
    if eid not in set(e.get("id") for e in ea.entries_in_force({"log": log}, (ea.AMEND,))):
        raise signing.SignatureRefused([UNDONE % eid])
    if record.get("state") != RELEASED:
        raise signing.SignatureRefused([NOT_RELEASED])
    userid = signing.current_userid(request)
    if not userid or target.get("by") != userid:
        raise signing.SignatureRefused([NOT_AUTHOR % eid])
    info = signing.staff_info(userid) or {}
    if "reviewer" not in (info.get("sign_as") or []) and signing._director_userid() != userid:
        raise signing.SignatureRefused([signing.NO_RIGHT % signing.meaning_label("reviewer")])
    rev = _revisions(log).get(eid) or revision(record)
    text = "%s, record rev %d" % (eid, rev)
    if _text(note).strip():
        text = "%s: %s" % (text, _text(note).strip())
    row = signing.sign(portal, request, KIND, record.get("worksheet"), record.get("revision"),
                       revision_hash(record), CORRECTED, note=text, path=path)
    return signing.cache([row])


def verify(st, cached):
    """None when the record's signatures hold, else why not
    (esig.signing.verify_rows); cached, the session's display cache."""
    from senaite.pfas.esig import signing
    return signing.verify_rows(st, cached)


def finalised_before_signatures(session, st):
    """True for an extraction finalised while no signature was kept: the
    session is finalised and the ledger holds no preparer row for it."""
    if not (session or {}).get("finalized"):
        return False
    return not [r for r in (st or {}).get("rows") or []
                if (r.get("entry") or {}).get("meaning") == "preparer"]


def legacy_preparer_row(session, st, fullname, when):
    """The Signatures row of an extraction finalised before signatures were
    kept (finalised_before_signatures): its finaliser by name, when, and
    "Finalised before signatures" in the image cell; None otherwise. The
    print and the record view show the same row."""
    if not finalised_before_signatures(session, st):
        return None
    who = session.get("finalized_by")
    return {"meaning": "Prepared by", "name": (fullname(who) if who else "") or "",
            "credentials": "", "image": FINALISED_BEFORE,
            "at": when(session.get("finalized_at")) if session.get("finalized_at") else "",
            "hash": "", "role": "preparer"}


def signature_word(session):
    """The queue's word for a record's signatures, from the session's
    display cache (the record view reads the ledger): a signed extraction
    sent back after finalising has Changed."""
    session = session or {}
    meanings = set(c.get("meaning") for c in session.get("signatures") or [])
    if "preparer" in meanings and not session.get("finalized"):
        return CHANGED
    if "reviewer" in meanings and session.get("finalized") and "preparer" not in meanings:
        # finalised before signatures were kept, then approved: nothing is
        # left to sign
        return SIGNED
    if "preparer" in meanings and "reviewer" in meanings:
        return SIGNED
    if meanings & set(("preparer", "reviewer")):
        return PARTLY_SIGNED
    return UNSIGNED


def _ws_number(ws_id):
    m = re.search(r"(\d+)\s*$", ws_id or "")
    return int(m.group(1)) if m else -1


def unreadable(ws_id, uid):
    """The queue's stand-in for a worksheet whose record could not be read."""
    return {"worksheet": ws_id or "", "uid": uid or "", "title": ws_id or "",
            "matrix": "", "client": "", "printable": False, "state": UNREADABLE, "progress": [0, 0]}


def queue_rows(records):
    """One row per record, the open ones first, then the newest worksheet
    first (WS-1000 before WS-99). A record carries the worksheet's uid."""
    rows = []
    for r in records or []:
        st = r.get("state") or NOT_STARTED
        done, planned = (list(r.get("progress") or []) + [0, 0])[:2]
        rows.append({
            "id": r.get("worksheet") or "",
            "uid": r.get("uid") or "",
            "title": r.get("title") or "",
            "matrix": r.get("matrix") or "",
            "client": r.get("client") or "",
            "printable": bool(r.get("printable")),
            "state": st,
            "label": state_label(r),
            "progress": "%d of %d stages" % (done, planned) if planned else "",
            "signed": r.get("signed") or "",
        })
    rows.sort(key=lambda row: (row["state"] != OPEN, -_ws_number(row["id"]), row["id"]))
    return rows
