# -*- coding: utf-8 -*-
"""@@pfas-signatures: the signature ledger, for Managers.

Every ledger row with its filters (kind, signer, meaning, from and to on the
laboratory's calendar, state), the chain check (action=check_chain), the CSV
export (?format=csv), the records export the verifier reads
(?format=records), each row's link to its record, the orphans, a Withdraw
for each standing signature (action=withdraw: the signer only, with
a reason) and the seal worker's health read from <ledger dir>/signatures.head.

    row_marks(rows)                    seq -> {"superseded_by"|"withdrawn_by": seq}
    find_records(rows, portal)         (kind, record id) -> {"seqs", "url"},
                                       one lookup per kind
    orphans(rows, portal, found=None)  rows no record holds
    build_items(...) / select(...)     the rows as the page and the CSV show them
    health(path, now=None)             the worker's last head line, unsealed rows
    check_chain(path)                  "Chain whole through row N" or broken
    may_withdraw(row, userid, is_manager)
    withdraw(portal, request, row, reason, path=None)
    csv_text(items)
    scan_records(portal)               every record that can hold signatures,
                                       one pass per kind (the records export)
    records_export(found, exported_at)  each record's cached seqs, as JSON

The ledger is the truth; a record's display cache only mirrors it, which is
how an orphan is found. Python 2.7; Plone is imported inside the functions
and the view's methods.
"""
from __future__ import absolute_import, unicode_literals

import datetime
import io
import json
import logging
import numbers
import os
import re

from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.pfas.browser.perms import GateMixin, TIER_CONFIG
from senaite.pfas.esig import canonical, ledger, signing
from senaite.pfas.method_revisions import revision_text

logger = logging.getLogger("senaite.pfas.browser.signatures_page")

try:
    _TEXT = unicode  # noqa: F821  (Python 2)
except NameError:
    _TEXT = str

# the chain check reads the whole ledger: configuration rights, like the
# sibling Configuration History page; a withdrawal has its own rule
PAGE_GATES = {"check_chain": TIER_CONFIG}

HEAD_NAME = "signatures.head"
STAMP = "%Y-%m-%dT%H:%M:%SZ"
# a row the worker has not sealed, or a head file it has not rewritten,
# within the ledger's silence window is shown as a problem (the verifier
# judges by the same window)
UNSEALED_AFTER = ledger.WORKER_SILENT_AFTER
STALE_AFTER = ledger.WORKER_SILENT_AFTER

KIND_LABELS = (("preparation", "Preparation record"), ("batch_record", "Batch record"),
               ("certificate", "Certificate"), ("lot_extension", "Lot extension"),
               ("coc_receipt", "CoC receipt"))
KIND_PLURALS = (("preparation", "preparation records"), ("batch_record", "batch records"),
                ("certificate", "certificates"), ("lot_extension", "lot extensions"),
                ("coc_receipt", "CoC receipts"))
STATE_LABELS = (("sealed", "Sealed"), ("unsealed", "Unsealed"), ("superseded", "Superseded"),
                ("withdrawn", "Withdrawn"), ("orphan", "Orphan"))
CSV_COLUMNS = ("seq", "signed_at", "kind", "record_id", "revision", "meaning", "signer",
               "fullname", "record_hash", "state", "sealed_at", "cert")

REASON_NEEDED = "Give the reason for withdrawing the signature."
NOT_YOURS = "Only the signer may withdraw a signature."
NO_ROW = "No such signature."
NOT_STANDING = "Only a standing signature can be withdrawn."
CHAIN_WHOLE = "Chain whole through row %d"
CHAIN_BROKEN = "Chain broken at row %d"
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _entry(row):
    e = row.get("entry")
    return e if isinstance(e, dict) else {}


def _u(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value if isinstance(value, _TEXT) else "%s" % (value,)


# ── what each row is ─────────────────────────────────────────────────────────

def row_marks(rows):
    """seq -> {"superseded_by": seq} and/or {"withdrawn_by": seq}, read as
    esig.signing.status reads one record (signing.back_references). rows is
    the whole ledger, or every row of the records concerned."""
    superseded_by, withdrawn_by = signing.back_references(rows)
    out = {}
    for mark, refs in (("superseded_by", superseded_by), ("withdrawn_by", withdrawn_by)):
        for seq, by in refs.items():
            out.setdefault(seq, {})[mark] = by["seq"]
    return out


def _standing(row, marks):
    """A signature on content that is neither superseded nor withdrawn."""
    return signing.is_live(row, marks, ())


def sample_of(report_id):
    """The sample id of a certificate's report id "<sample id>-R<n>"; None
    for anything else."""
    head, sep, tail = _u(report_id).rpartition("-R")
    return head if sep and head and tail.isdigit() else None


def _seqs(cache):
    return set(c.get("seq") for c in cache or [] if isinstance(c, dict))


def _find_preparations(portal, ids):
    """Each preparation record's cached seqs and its first lot's record card."""
    from six.moves.urllib.parse import quote
    from senaite.pfas import prep_entries
    entries = prep_entries.load(portal)
    purl = portal.absolute_url()
    out = {}
    for rid in ids:
        e = entries.get(rid)
        if e is None:
            continue
        lots = e.get("lots") or []
        out[rid] = {"seqs": _seqs(e.get("signatures")),
                    "url": "%s/@@pfas-prep-standards?record=%s" % (purl, quote(lots[0].encode("utf-8")))
                    if lots else ""}
    return out


def _find_batch_records(portal, ids):
    """Each worksheet's extraction session cache and its batch record view:
    the ledger names the worksheet by id, the record view by uid."""
    from bika.lims import api
    from senaite.pfas.browser.extraction_guide import _load_session
    purl = portal.absolute_url()
    out = {}
    for brain in api.search({"portal_type": "Worksheet", "id": list(ids)}, "senaite_catalog_worksheet"):
        ws = api.get_object(brain)
        out[_u(ws.getId())] = {"seqs": _seqs((_load_session(ws) or {}).get("signatures")),
                               "url": "%s/@@pfas-batch-records?record=%s" % (purl, api.get_uid(ws))}
    return out


SEALED = "Sealed"
SEAL_PENDING = "Seal pending"
SEAL_FAILED = "Seal failed"


# the register says a row's seal time only when the seal came this many
# minutes or more after the signing: an on-time seal repeats the signed time
SEAL_LATE_MINUTES = 10


def seal_line(signed_at, sealed_at, shown):
    """What the State cell says of a row's seal: u"" for none (the Unsealed
    state says it) or for one within SEAL_LATE_MINUTES of the signing,
    "Sealed <time>" for a later one. `shown(stamp, "utc")` gives a stored
    time as the page shows it."""
    if not sealed_at:
        return u""
    from senaite.pfas import lab_time
    signed, sealed = lab_time.to_wall(signed_at, "utc"), lab_time.to_wall(sealed_at, "utc")
    if signed is not None and sealed is not None and \
            (sealed - signed).total_seconds() < SEAL_LATE_MINUTES * 60:
        return u""
    return u"Sealed %s" % shown(sealed_at, "utc")


def certificate_seal(entry, rec):
    """The certificate's own seal as the register and its report say:
    Sealed when the register holds the sealed hash, else the report's seal
    record, pending or failed; "" when it has none (sealed in a package)."""
    if (entry or {}).get("sealed_sha256"):
        return SEALED
    state = (rec or {}).get("state")
    return {"sealed": SEALED, "pending": SEAL_PENDING, "failed": SEAL_FAILED}.get(state, "")


def _report_seal(api, entry):
    """The seal record of the register entry's report, when the register
    does not already say it is sealed."""
    from senaite.pfas import report_packages
    if entry.get("sealed_sha256") or not entry.get("report_uid"):
        return None
    report = api.get_object_by_uid(entry["report_uid"], None)
    return report_packages.seal_record(report) if report is not None else None


def _find_certificates(portal, ids):
    """Each issue's register entry: its signature_seq, its seal, and the
    sample. An issue the sample's register does not hold keeps the sample's
    link and no seq."""
    from bika.lims import api
    from senaite.pfas.browser.controlled_publications import get_publication_log
    by_sample = {}
    for rid in ids:
        sid = sample_of(rid)
        if sid:
            by_sample.setdefault(sid, []).append(rid)
    out = {}
    if not by_sample:
        return out
    for brain in api.search({"portal_type": "AnalysisRequest", "getId": list(by_sample)},
                            "senaite_catalog_sample"):
        ar = api.get_object(brain)
        log = dict((e.get("report_id"), e) for e in get_publication_log(ar))
        url = api.get_url(ar)
        for rid in by_sample.get(_u(api.get_id(ar)), []):
            entry = log.get(rid) or {}
            seq = entry.get("signature_seq")
            out[rid] = {"seqs": set([seq]) if seq is not None else set(), "url": url,
                        "seal": certificate_seal(entry, _report_seal(api, entry)) if entry else ""}
    return out


def _extension_url(portal, entry):
    from six.moves.urllib.parse import quote
    purl = portal.absolute_url()
    if entry.get("lot_kind") == "prepared_standard":
        return "%s/@@pfas-prep-standards?record=%s" % (purl, quote(_u(entry.get("lot_uid")).encode("utf-8")))
    return "%s/@@pfas-lot-extensions" % purl


def _find_lot_extensions(portal, ids):
    """Each extension the ledger names, by its id (the lot's uid with the
    entry's number): the seqs its entry's cache holds and its lot. One
    signature covers the lots extended with it, so the record is the
    entry that was signed; the children's entries name it."""
    from senaite.pfas.browser import lot_extensions
    out = {}
    for rid in ids:
        entry, _obj = lot_extensions.record(portal, rid)
        if entry is not None:
            out[rid] = {"seqs": _seqs(entry.get("signatures")), "url": _extension_url(portal, entry)}
    return out


def _receipt_seqs(rec):
    """The seqs a CoC's receipt holds: every correction's display cache."""
    from senaite.pfas import coc_records as cr
    out = set()
    for c in cr.corrections(rec):
        out |= _seqs(c.get("signatures"))
    return out


def _find_coc_receipts(portal, ids):
    """Each CoC whose receipt date a signature corrected, by its number:
    the seqs its corrections' caches hold and its receive page."""
    from six.moves.urllib.parse import quote
    from senaite.pfas import coc_records as cr
    purl = portal.absolute_url()
    out = {}
    for rid in ids:
        rec = cr.load(portal, rid)
        if rec is not None:
            out[rid] = {"seqs": _receipt_seqs(rec),
                        "url": "%s/@@pfas-coc-receive?coc=%s" % (purl, quote(_u(rid).encode("utf-8")))}
    return out


FINDERS = {"preparation": _find_preparations, "batch_record": _find_batch_records,
           "certificate": _find_certificates, "lot_extension": _find_lot_extensions,
           "coc_receipt": _find_coc_receipts}


def find_records(rows, portal, finders=None, failed=None):
    """(kind, record id) -> {"seqs": the seqs the record's cache holds,
    "url": its page}, one lookup per kind. A record that no longer exists is
    absent. A kind that could not be read gives {"seqs": None, "url": ""}
    for its records: unknown, never an orphan; it is added to failed, a
    list the page says from."""
    finders = FINDERS if finders is None else finders
    ids = {}
    for r in rows:
        e = _entry(r)
        if e.get("kind") and e.get("record_id"):
            ids.setdefault(e["kind"], set()).add(e["record_id"])
    out = {}
    for kind in sorted(ids):
        try:
            found = finders[kind](portal, sorted(ids[kind]))
        except Exception:                                   # noqa: BLE001
            logger.exception("signature records of kind %s not read", kind)
            found = dict((rid, {"seqs": None, "url": ""}) for rid in ids[kind])
            if failed is not None:
                failed.append(kind)
        for rid, rec in found.items():
            out[(kind, rid)] = rec
    return out


def _scan_preparations(portal):
    """Every preparation record and the seqs its cache holds."""
    from senaite.pfas import prep_entries
    return dict((_u(rid), _seqs(e.get("signatures")))
                for rid, e in prep_entries.load(portal).items() if isinstance(e, dict))


def _scan_batch_records(portal):
    """Every worksheet carrying an extraction session, and the seqs its
    session's cache holds."""
    from bika.lims import api
    from senaite.pfas.browser.extraction_guide import _load_session
    out = {}
    for brain in api.search({"portal_type": "Worksheet"}, "senaite_catalog_worksheet"):
        ws = api.get_object(brain)
        session = _load_session(ws)
        if session:
            out[_u(ws.getId())] = _seqs(session.get("signatures"))
    return out


def _scan_certificates(portal):
    """Every certificate issue a sample's register holds, and its
    signature_seq."""
    from bika.lims import api
    from senaite.pfas.browser.controlled_publications import get_publication_log
    out = {}
    for brain in api.search({"portal_type": "AnalysisRequest"}, "senaite_catalog_sample"):
        for entry in get_publication_log(api.get_object(brain)):
            rid, seq = entry.get("report_id"), entry.get("signature_seq")
            if rid:
                out[_u(rid)] = set([seq]) if seq is not None else set()
    return out


def _scan_lot_extensions(portal):
    """Every extension entry that was signed for itself (not a child
    extended with its parent), and the seqs its cache holds."""
    from senaite.pfas.browser import lot_extensions
    return dict((_u(rid), _seqs(cache)) for rid, cache in lot_extensions.signed_records(portal).items())


def _scan_coc_receipts(portal):
    """Every CoC whose receipt date was corrected, and the seqs its
    corrections' caches hold."""
    from senaite.pfas import coc_records as cr
    out = {}
    for rec in cr.for_client(portal, None):
        if cr.corrections(rec):
            out[_u(rec["number"])] = _receipt_seqs(rec)
    return out


SCANNERS = {"preparation": _scan_preparations, "batch_record": _scan_batch_records,
            "certificate": _scan_certificates, "lot_extension": _scan_lot_extensions,
            "coc_receipt": _scan_coc_receipts}


def scan_records(portal, scanners=None, failed=None):
    """(kind, record id) -> {"seqs": the seqs its cache holds} for every
    record that can carry a signature cache, read from the records' side
    in one pass per kind, so a record whose ledger rows were all removed is
    still exported with the seqs it holds. A kind that could not be read is
    added to failed and gives nothing."""
    scanners = SCANNERS if scanners is None else scanners
    out = {}
    for kind in sorted(scanners):
        try:
            found = scanners[kind](portal)
        except Exception:                                   # noqa: BLE001
            logger.exception("signature records of kind %s not scanned", kind)
            if failed is not None:
                failed.append(kind)
            continue
        for rid, seqs in found.items():
            out[(kind, rid)] = {"seqs": seqs}
    return out


def orphans(rows, portal, found=None, marks=None):
    """The standing signatures no record holds: the record no longer exists,
    or its display cache lacks the row's seq. Superseded and withdrawn rows,
    and the rows that mark them, are never orphans. marks, row_marks of the
    whole ledger, when rows is a filtered part of it."""
    marks = row_marks(rows) if marks is None else marks
    if found is None:
        found = find_records(rows, portal)
    out = []
    for r in rows:
        if not _standing(r, marks):
            continue
        e = _entry(r)
        rec = found.get((e.get("kind"), e.get("record_id")))
        if rec is None or (rec.get("seqs") is not None and r["seq"] not in rec["seqs"]):
            out.append(r)
    return out


def shown_revision(entry):
    """The revision a ledger row names, as the register prints it: a batch
    record's is its method revision, major.sub (an integer signed before
    major.sub reads "N.0"); another record's as signed. The row keeps
    the value as signed."""
    rev = entry.get("revision")
    return revision_text(rev) if entry.get("kind") == "batch_record" and rev is not None else rev


def build_items(rows, marks, found, orphan_seqs, shown):
    """The rows as the page and the CSV show them. state is one word, the
    most telling: withdrawn, superseded, orphan, else sealed or unsealed;
    flags hold every word that applies, for the State filter."""
    out = []
    for r in rows:
        e = _entry(r)
        signer = e.get("signer") or {}
        m = marks.get(r["seq"]) or {}
        sealed = "sealed" if r.get("seal") else "unsealed"
        flags = set([sealed])
        if "withdrawn_by" in m:
            flags.add("withdrawn")
        if "superseded_by" in m:
            flags.add("superseded")
        if r["seq"] in orphan_seqs:
            flags.add("orphan")
        state = next((s for s in ("withdrawn", "superseded", "orphan") if s in flags), sealed)
        rec = found.get((e.get("kind"), e.get("record_id"))) or {}
        out.append({
            "seq": r["seq"], "signed_at": _u(e.get("signed_at")), "kind": _u(e.get("kind")),
            "record_id": _u(e.get("record_id")), "revision": shown_revision(e),
            "meaning": _u(e.get("meaning")), "signer": _u(signer.get("userid")),
            "fullname": _u(signer.get("fullname")), "record_hash": _u(e.get("record_hash")),
            "state": state, "sealed_at": _u(r.get("sealed_at")), "cert": _u(r.get("seal_cert")),
            "flags": flags, "url": rec.get("url") or "",
            "certificate_seal": (rec.get("seal") or "") if e.get("kind") == "certificate" else "",
            # a certificate's own seal is said only while it is not sealed
            "certificate_flag": (rec.get("seal") or "") if e.get("kind") == "certificate"
                                and rec.get("seal") != SEALED else "",
            "seal_line": seal_line(e.get("signed_at"), r.get("sealed_at"), shown),
            "kind_label": dict(KIND_LABELS).get(e.get("kind"), _u(e.get("kind"))),
            "meaning_label": signing.meaning_label(e.get("meaning")),
            "state_label": dict(STATE_LABELS).get(state, state),
            "shown_at": shown(e.get("signed_at"), "utc"), "note": _u(e.get("note")),
            "supersedes": e.get("supersedes"), "withdraws": e.get("withdraws"),
            "marked_by": m.get("withdrawn_by") or m.get("superseded_by"),
            "withdrawable": _standing(r, marks),
        })
    return out


def _lab_day(stamp):
    from senaite.pfas import lab_time
    return lab_time.lab_date(stamp, "utc")


def select(items, kind=None, signer=None, meaning=None, day_from=None, day_to=None,
           state=None, day_of=None):
    """The items the filters keep, in their order. From and To are whole
    days on the laboratory's calendar (day_of gives a signed_at's day); a
    bound that is not a day is ignored."""
    day_of = day_of or _lab_day
    day_from = day_from if day_from and _DAY.match(day_from) else None
    day_to = day_to if day_to and _DAY.match(day_to) else None
    out = []
    for i in items:
        if (kind and i["kind"] != kind) or (signer and i["signer"] != signer) \
                or (meaning and i["meaning"] != meaning) or (state and state not in i["flags"]):
            continue
        if day_from or day_to:
            day = day_of(i["signed_at"]) if i["signed_at"] else None
            day = day.isoformat() if hasattr(day, "isoformat") else day
            if not day or (day_from and day < day_from) or (day_to and day > day_to):
                continue
        out.append(i)
    return out


# ── password resets and signing attempts ─────────────────────────────────────

ATTEMPT_WORDS = {"failed": "Wrong %s", "locked": "Signing locked"}


def attempt_rows(events, shown):
    """The failed signing attempts and locks (esig.credentials.attempts) as
    the Signing attempts table shows them: Time, Person, What happened."""
    out = []
    for e in events or ():
        word = signing.CREDENTIAL_WORDS.get(e.get("kind"), _u(e.get("kind")) or "credential")
        what = ATTEMPT_WORDS.get(e.get("action"), _u(e.get("action")))
        out.append({"at": shown(e.get("at"), "utc"), "userid": _u(e.get("userid")),
                    "what": what % word if "%s" in what else what})
    return out


def reset_reviews(resets, items):
    """Each password reset with the signatures made as its person while it
    was open: from the reset until they changed the password themselves
    (still open: until now). resets: esig.credentials.resets(); items:
    build_items rows. Signed and reset times are stored stamps, compared as
    text."""
    out = []
    for r in resets or ():
        start, end = _u(r.get("at")), _u(r.get("closed_at"))
        seqs = [i["seq"] for i in items
                if i["signer"] == r.get("userid") and i["signed_at"] >= start
                and (not end or i["signed_at"] < end)]
        out.append({"userid": _u(r.get("userid")), "by": _u(r.get("by")), "at": start,
                    "closed_at": end, "seqs": seqs})
    return out


# ── the chain and the worker ─────────────────────────────────────────────────

def chain_message(broken, head_seq):
    return CHAIN_WHOLE % head_seq if broken is None else CHAIN_BROKEN % broken


def check_chain(path=None):
    """{"ok", "text"}: the chain read from the first row to the last."""
    broken, whole = ledger.check(path)
    return {"ok": broken is None, "text": chain_message(broken, whole)}


def head_path(path=None):
    return os.path.join(os.path.dirname(path or ledger.DB_PATH), HEAD_NAME)


def _parse(stamp):
    try:
        return datetime.datetime.strptime(stamp, STAMP)
    except (TypeError, ValueError):
        return None


def health(path=None, now=None):
    """The seal worker as its last head line and the ledger say:
    unsealed_old  rows with no seal signed more than ten minutes ago (None
                  when the ledger cannot be read; error then says so)
    key_ok        the worker's own word that its seal key is usable; None
                  without a head file
    head_at       when the worker last wrote it
    stale         True when it has not for ten minutes, or never did
    cert_not_after the seal certificate's last valid moment"""
    now = now or signing.utcnow()
    try:
        with io.open(head_path(path), encoding="utf-8") as fh:
            head = json.loads(fh.read())
    except (IOError, OSError, ValueError):
        head = {}
    if not isinstance(head, dict):
        head = {}
    at = _parse(head.get("at"))
    out = {"unsealed_old": None, "error": "",
           "key_ok": head.get("key_ok") if isinstance(head.get("key_ok"), bool) else None,
           "head_at": head.get("at") if at else None,
           "stale": at is None or now - at > STALE_AFTER,
           "cert_not_after": head.get("cert_not_after") or None}
    cutoff = now - UNSEALED_AFTER

    def old(row):
        # a row whose time cannot be read is counted: it is a problem too
        signed = _parse(_entry(row).get("signed_at"))
        return signed is None or signed < cutoff
    try:
        out["unsealed_old"] = len([r for r in ledger.rows(path=path, unsealed=True) if old(r)])
    except ledger.LedgerError as exc:
        out["error"] = signing.reason(exc)
    return out


# ── withdrawal ───────────────────────────────────────────────────────────────

def may_withdraw(row, userid):
    """A signature is withdrawn only by its own signer, whatever roles they
    hold. The one rule for the Signatures page and a record's card. No staff
    record or signature image is needed: the withdrawal is signed with the
    user's identity alone."""
    return bool(userid and signing.signer_of(row) == userid)


def standing_signature(row, path=None):
    """True for a row that signs content and still stands on its record:
    neither withdrawn nor superseded."""
    e = _entry(row)
    if e.get("meaning") not in signing.SIGNING:
        return False
    st = signing.status(e.get("kind"), e.get("record_id"), e.get("record_hash"), path=path)
    return row["seq"] in [r["seq"] for r in st["live"]]


def safe_return(url, portal_url):
    """`url` when it is a page of this site, else the site's own address:
    a withdrawal returns only to a page of the site."""
    url, portal_url = _u(url).strip(), _u(portal_url).rstrip("/")
    if url == portal_url or url.startswith(portal_url + "/"):
        return url
    return portal_url


def find_row(seq, path=None):
    try:
        seq = int(seq)
    except (TypeError, ValueError):
        return None
    return ledger.row(seq, path=path)


def withdraw(portal, request, row, reason, path=None):
    """Withdraw a standing signature as the current user: a withdrawn row
    naming it, with the reason as its note, on the content it signed. The
    caller has checked may_withdraw. Raises signing.SignatureRefused or
    ledger.LedgerError."""
    reason = _u(reason).strip()
    if not reason:
        raise signing.SignatureRefused([REASON_NEEDED])
    e = _entry(row)
    st = signing.status(e.get("kind"), e.get("record_id"), e.get("record_hash"), path=path)
    if row["seq"] not in [r["seq"] for r in st["live"]]:
        raise signing.SignatureRefused([NOT_STANDING])
    return signing.sign(portal, request, e["kind"], e["record_id"], e.get("revision"),
                        e["record_hash"], "withdrawn", note=reason, withdraws=row["seq"], path=path)


# what each kind of record says when its signature's withdrawal moved it
FOLLOWS = {"lot_extension": "lot %s back to its previous expiry",
           "coc_receipt": "CoC %s back to its previous receipt date"}


def withdrawn_text(row, changed):
    """The page's line for a withdrawal: the records it moved, if any."""
    what = FOLLOWS.get(_entry(row).get("kind"))
    if changed and what:
        return "Signature %d withdrawn: %s." % (row["seq"], what % ", ".join(changed))
    return "Signature %d withdrawn." % row["seq"]


def withdraw_record(portal, row, gone, reason):
    """What the record does when its signature is withdrawn: a lot
    extension (and each lot extended with it) is withdrawn, so each lot
    returns to its previous expiry; a receipt date correction is withdrawn,
    so the CoC's samples return to the receipt date before it. The
    withdrawal joins its cache. The lot or CoC numbers changed; [] for any
    other kind."""
    e = _entry(row)
    if e.get("kind") == "coc_receipt":
        from senaite.pfas.browser import coc_receive
        return coc_receive.withdraw_signed(portal, e.get("record_id"), row["seq"], signing.signer_of(gone),
                                           _entry(gone).get("signed_at"), reason, signing.cache([gone]))
    if e.get("kind") != "lot_extension":
        return []
    from senaite.pfas.browser import lot_extensions
    return lot_extensions.withdraw_signed(portal, e.get("record_id"), signing.signer_of(gone),
                                          _entry(gone).get("signed_at"), reason, gone.get("seq"),
                                          signing.cache([gone]))


def withdrawn_already(portal, row, path=None):
    """withdraw_record for a row the ledger already shows withdrawn; [] when
    it is not, or the record has nothing to follow (lot_extensions and
    coc_records keep an entry already withdrawn as it is)."""
    e = _entry(row)
    if e.get("kind") not in FOLLOWS:
        return []
    try:
        st = signing.status(e.get("kind"), e.get("record_id"), e.get("record_hash"), path=path)
    except ledger.LedgerError:
        return []
    for r in st.get("withdrawn") or []:
        if r["seq"] == row["seq"]:
            by = r["withdrawn_by"]
            return withdraw_record(portal, row, by, _entry(by).get("note"))
    return []


# ── CSV ──────────────────────────────────────────────────────────────────────

def _cell(value):
    text = _u(value)
    # a spreadsheet runs a cell that starts like a formula
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        text = "'" + text
    if any(c in text for c in (",", '"', "\r", "\n")):
        text = '"' + text.replace('"', '""') + '"'
    return text


def csv_text(items):
    lines = [",".join(CSV_COLUMNS)]
    lines.extend(",".join(_cell(i.get(c)) for c in CSV_COLUMNS) for i in items)
    return "\r\n".join(lines) + "\r\n"


# ── the records export ───────────────────────────────────────────────────────

RECORDS_FAILED = "The %s could not be read: the records export would be incomplete."


def records_export(found, exported_at):
    """{"records": [{"kind", "record_id", "seqs"}], "exported_at"}: each
    record find_records found with the seqs its display cache holds, for the
    verifier to check against the ledger. A record whose seqs are unknown
    (its kind could not be read) keeps seqs null, which the verifier never
    reads as empty; the page refuses such an export before it is made."""
    records = []
    for kind, rid in sorted(found):
        seqs = found[(kind, rid)].get("seqs")
        if seqs is not None:
            seqs = sorted(q for q in seqs if isinstance(q, numbers.Integral)
                          and not isinstance(q, bool))
        records.append({"kind": kind, "record_id": rid, "seqs": seqs})
    return {"records": records, "exported_at": exported_at}


# ── the page ─────────────────────────────────────────────────────────────────

class PFASSignatureWithdrawView(BrowserView):
    """@@pfas-signature-withdraw: a signer withdraws their own standing
    signature from the record's Signatures card, with a reason and their
    password or PIN; the same withdrawal the Signatures page makes, which
    a Manager uses for anyone's. Back to the page it came from."""

    path = None

    def __call__(self):
        from bika.lims import api
        from plone.protect import CheckAuthenticator
        from senaite.pfas.browser.formutil import flatten_form
        from senaite.pfas.browser.perms import refuse
        from zExceptions import Forbidden
        flatten_form(self.request)
        if self.request.method != "POST":
            return refuse(self.request)
        try:
            CheckAuthenticator(self.request)
        except Forbidden:
            return refuse(self.request)
        form = self.request.form
        back = safe_return(form.get("came_from"), api.get_portal().absolute_url())
        try:
            row = find_row(form.get("seq"), self.path)
        except ledger.LedgerError as exc:
            return self._return(back, False, signing.reason(exc))
        if row is None:
            return self._return(back, False, NO_ROW)
        userid = signing.current_userid(self.request)
        if not may_withdraw(row, userid):
            return refuse(self.request, NOT_YOURS)
        portal = api.get_portal()
        try:
            gone = withdraw(portal, self.request, row, form.get("reason"), path=self.path)
        except (signing.SignatureRefused, ledger.LedgerError) as exc:
            lots = withdrawn_already(portal, row, self.path)
            if lots:
                return self._return(back, True, withdrawn_text(row, lots))
            return self._return(back, False, signing.reason(exc))
        return self._return(back, True, withdrawn_text(row, withdraw_record(portal, row, gone, form.get("reason"))))

    def _return(self, url, ok, text):
        from six.moves.urllib.parse import urlencode
        sep = "&" if "?" in url else "?"
        self.request.response.redirect("%s%s%s" % (url, sep, urlencode(
            {("ok" if ok else "error"): _u(text).encode("utf-8")})))
        return ""


class PFASSignaturesView(GateMixin, BrowserView):

    template = ViewPageTemplateFile("templates/signatures.pt")
    PAGE = 50
    # ?format=<name> answers with the method named; the page itself otherwise
    FORMATS = {"csv": "csv_response", "records": "records_response"}
    path = None
    read_error = ""
    failed_kinds = ()
    _whole = False

    def __call__(self):
        from senaite.pfas.browser.formutil import flatten_form
        from senaite.pfas.browser.perms import deny_gated_action, disable_csrf
        from senaite.pfas.browser.perms import may_read_config, refuse
        flatten_form(self.request)
        self.message = None
        form = self.request.form
        # the manager's ledger; the read-only inspector reads it by GET
        if not may_read_config(self.context, self.request):
            return refuse(self.request, "Forbidden")
        if self.request.method == "POST":
            action = form.get("action", "")
            denied = deny_gated_action(self.context, self.request, action, PAGE_GATES)
            if denied is not None:
                return denied
            if action == "withdraw":
                return self._withdraw()
            disable_csrf(self.request)
            if action == "check_chain":
                try:
                    self.message = check_chain(self.path)
                except ledger.LedgerError as exc:
                    self.message = {"ok": False, "text": signing.reason(exc)}
        elif form.get("msg"):
            self.message = {"ok": form.get("ok") == "1", "text": form.get("msg")}
        handler = self.FORMATS.get(form.get("format") or "")
        if handler:
            return getattr(self, handler)()
        return self.template()

    def _withdraw(self):
        from bika.lims import api
        from senaite.pfas.browser.perms import disable_csrf, refuse
        try:
            row = find_row(self.request.form.get("seq"), self.path)
        except ledger.LedgerError as exc:
            return self._back(False, signing.reason(exc))
        if row is None:
            return self._back(False, NO_ROW)
        userid = signing.current_userid(self.request)
        if not may_withdraw(row, userid):
            return refuse(self.request, NOT_YOURS)
        disable_csrf(self.request)
        portal = api.get_portal()
        try:
            gone = withdraw(portal, self.request, row, self.request.form.get("reason"), path=self.path)
        except (signing.SignatureRefused, ledger.LedgerError) as exc:
            # the ledger may already hold the withdrawal (a request retried
            # after its row was written): the record still follows it
            lots = withdrawn_already(portal, row, self.path)
            if lots:
                return self._back(True, withdrawn_text(row, lots))
            return self._back(False, signing.reason(exc))
        lots = withdraw_record(portal, row, gone, self.request.form.get("reason"))
        return self._back(True, withdrawn_text(row, lots))

    def _back(self, ok, text):
        from six.moves.urllib.parse import urlencode
        q = dict(self._filters(), ok="1" if ok else "0", msg=text)
        self.request.response.redirect("%s?%s" % (self.page_url(), urlencode(
            dict((k, _u(v).encode("utf-8")) for k, v in q.items() if v))))
        return ""

    # ── filters ──────────────────────────────────────────────────────────────

    def portal_url(self):
        from bika.lims import api
        return api.get_portal().absolute_url()

    def page_url(self):
        return "%s/@@pfas-signatures" % self.portal_url()

    def _f(self, name, choices=None):
        value = _u(self.request.form.get(name) or "").strip()
        if choices is not None and value not in choices:
            return ""
        return value

    def kind_filter(self):
        return self._f("kind", [k for k, _l in KIND_LABELS])

    def meaning_filter(self):
        return self._f("meaning", list(ledger.MEANINGS))

    def state_filter(self):
        return self._f("state", [s for s, _l in STATE_LABELS])

    def signer_filter(self):
        return self._f("signer")

    def date_from(self):
        return self._f("from")[:10]

    def date_to(self):
        return self._f("to")[:10]

    def _filters(self):
        return dict((k, v) for k, v in (
            ("kind", self.kind_filter()), ("signer", self.signer_filter()),
            ("meaning", self.meaning_filter()), ("from", self.date_from()),
            ("to", self.date_to()), ("state", self.state_filter())) if v)

    def hidden_filters(self):
        """The filters as (name, value), carried through a POST and back."""
        return sorted(self._filters().items())

    def _url(self, **changes):
        from six.moves.urllib.parse import urlencode
        q = dict(self._filters())
        q.update(changes)
        q = dict((k, _u(v).encode("utf-8")) for k, v in q.items() if v)
        return "%s?%s" % (self.page_url(), urlencode(q)) if q else self.page_url()

    def _seg(self, name, labels, current):
        return [{"label": label, "on": value == current, "url": self._url(**{name: value, "page": ""})}
                for value, label in (("", "All"),) + tuple(labels)]

    def kind_links(self):
        return self._seg("kind", KIND_LABELS, self.kind_filter())

    def state_links(self):
        return self._seg("state", STATE_LABELS, self.state_filter())

    def meanings(self):
        return list(signing.LABELS)

    def csv_url(self):
        return self._url(format="csv")

    def zone_active(self):
        from senaite.pfas import lab_time
        return lab_time.active()

    def records_url(self):
        return "%s?format=records" % self.page_url()

    # ── rows ─────────────────────────────────────────────────────────────────

    def _resolve(self, rows):
        """rows as the page shows them: their records looked up (one lookup
        per kind), orphans marked against the whole ledger's marks, times
        on the laboratory's clock."""
        from bika.lims import api
        from senaite.pfas import lab_time
        if not rows:
            return []
        failed = []
        found = find_records(rows, api.get_portal(), failed=failed)
        self.failed_kinds.extend(k for k in failed if k not in self.failed_kinds)
        lost = set(r["seq"] for r in orphans(rows, None, found=found, marks=self._marks))
        return build_items(rows, self._marks, found, lost, lab_time.show)

    def _selected(self, resolve=False):
        """The filtered items, oldest first; None when the ledger cannot be
        read. Marks are read over the whole ledger. Records are looked up
        here for every kept row only when the State filter needs them, or
        resolve asks (the CSV); otherwise items() looks them up for the page
        shown alone."""
        if hasattr(self, "_items") and (self._whole or not resolve):
            return self._items
        self._items, self.read_error, self.failed_kinds = None, "", []
        try:
            rows = ledger.rows(path=self.path)
        except ledger.LedgerError as exc:
            self.read_error = signing.reason(exc)
            return None
        self._marks = row_marks(rows)
        kept = select(build_items(rows, self._marks, {}, set(), lambda value, kind="utc": ""),
                      kind=self.kind_filter(), signer=self.signer_filter(),
                      meaning=self.meaning_filter(), day_from=self.date_from(),
                      day_to=self.date_to())
        seqs = set(i["seq"] for i in kept)
        self._rows = dict((r["seq"], r) for r in rows if r["seq"] in seqs)
        self._whole = bool(resolve or self.state_filter())
        if self._whole:
            self._items = select(self._resolve([r for r in rows if r["seq"] in seqs]),
                                 state=self.state_filter())
        else:
            self._items = kept
        return self._items

    def failed_messages(self):
        """What the page says of a kind whose records could not be read: its
        rows show no link and are never counted as orphans."""
        return ["The %s could not be read: their rows have no link and no orphan check."
                % dict(KIND_PLURALS).get(k, k) for k in self.failed_kinds]

    def page(self):
        try:
            return max(1, int(self.request.form.get("page") or 1))
        except (TypeError, ValueError):
            return 1

    def paging(self):
        items = self._selected() or []
        total = len(items)
        pages = max(1, (total + self.PAGE - 1) // self.PAGE)
        page = min(self.page(), pages)
        return {"total": total, "page": page, "pages": pages,
                "first": (page - 1) * self.PAGE + 1 if total else 0,
                "last": min(total, page * self.PAGE),
                "prev": self._url(page=page - 1) if page > 1 else None,
                "next": self._url(page=page + 1) if page < pages else None}

    def items(self):
        """The page of rows shown, newest first, their records looked up for
        this page alone unless every kept row already was."""
        items = list(reversed(self._selected() or []))
        start = (self.paging()["page"] - 1) * self.PAGE
        shown = items[start:start + self.PAGE]
        if self._items is None or self._whole:
            return shown
        done = dict((i["seq"], i) for i in self._resolve(
            [self._rows[i["seq"]] for i in sorted(shown, key=lambda i: i["seq"])]))
        return [done[i["seq"]] for i in shown]

    def read_only(self):
        """The ledger drawn view-only (the inspector reading it): no chain
        check, no withdrawal."""
        return not self.can_configure()

    def can_withdraw(self, item):
        if not item.get("withdrawable"):
            return False
        if not hasattr(self, "_userid"):
            self._userid = signing.current_userid(self.request)
        return may_withdraw({"entry": {"signer": {"userid": item["signer"]}}}, self._userid)

    def attempts(self):
        """The newest failed signing attempts and locks, for the Signing
        attempts table; none when the store cannot be read."""
        from senaite.pfas import lab_time
        from senaite.pfas.esig import credentials
        try:
            return attempt_rows(credentials.attempts(self.PAGE), lab_time.show)
        except Exception:                                   # noqa: BLE001
            logger.warning("signing attempts not readable", exc_info=True)
            return []

    def resets(self):
        """Each password reset by another account with the signatures made as
        its person until they changed it, for the quality officer's review;
        the ledger read whole, whatever the filters."""
        from senaite.pfas import lab_time
        from senaite.pfas.esig import credentials
        try:
            got = credentials.resets(limit=self.PAGE)
        except Exception:                                   # noqa: BLE001
            logger.warning("password resets not readable", exc_info=True)
            return []
        if not got:
            return []
        try:
            rows = ledger.rows(path=self.path)
        except ledger.LedgerError:
            rows = []
        items = build_items(rows, row_marks(rows), {}, set(), lambda value, kind="utc": "")
        out = reset_reviews(got, items)
        for r in out:
            r["shown_at"] = lab_time.show(r["at"], "utc")
            r["shown_closed"] = lab_time.show(r["closed_at"], "utc") if r["closed_at"] else ""
            # the table filtered to the person from the reset's day on
            day = lab_time.lab_date(r["at"], "utc")
            r["url"] = self._url(signer=r["userid"], page="", kind="", meaning="", state="",
                                 to="", **{"from": day.isoformat() if day else ""})
        return out

    def health(self):
        if not hasattr(self, "_health"):
            self._health = health(self.path)
        return self._health

    def shown(self, stamp):
        from senaite.pfas import lab_time
        return lab_time.show(stamp, "utc") if stamp else ""

    def csv_response(self):
        from senaite.pfas import lab_time
        items = self._selected(resolve=True)
        if items is None:
            self.request.response.setStatus(409)
            return self.read_error
        resp = self.request.response
        resp.setHeader("Content-Type", "text/csv; charset=utf-8")
        resp.setHeader("Content-Disposition",
                       'attachment; filename="signatures-%s.csv"' % lab_time.today().isoformat())
        return csv_text(items).encode("utf-8")

    def records_response(self):
        """The records export: every record that can hold signatures, read
        from the records alone (never from the ledger it is checked
        against), the page's filters aside. Refused (409) when a kind of
        record cannot be read, as a partial export would make orphans of the
        rows it left out."""
        from bika.lims import api
        from senaite.pfas import lab_time
        from senaite.pfas.esig import certificate
        resp = self.request.response
        failed = []
        found = scan_records(api.get_portal(), failed=failed)
        if failed:
            resp.setStatus(409)
            return " ".join(RECORDS_FAILED % dict(KIND_PLURALS).get(k, k) for k in failed)
        # a stored stamp, UTC as a signature records it, not a time shown
        body = records_export(found, certificate.now_stamp())
        resp.setHeader("Content-Type", "application/json; charset=utf-8")
        resp.setHeader("Content-Disposition", 'attachment; filename="signatures-records-%s.json"'
                       % lab_time.today().isoformat())
        return canonical.dumps(body).encode("utf-8")
