# -*- coding: utf-8 -*-
"""The signing core every signed step calls.

    problems(...)     the reasons a person may not sign, as messages
    sign(...)         keep the signature image, append the ledger row
    status(...)       what a record's rows say: valid, changed, superseded,
                      withdrawn
    cache(rows)       the record's display copy of its rows
    meaning_label(m)  "Prepared by", "Reviewed by", ...
    snapshot_uri(row) the image kept at signing, as a data URI for a print

The ledger is the source of truth for "signed"; a record keeps only the
display cache. A signature binds to the record's content hash: it is valid
while the record still hashes the same. Python 2.7; Plone is imported inside
the functions that need it.
"""
from __future__ import absolute_import, unicode_literals

import base64
import datetime
import logging
import os
import uuid

from senaite.pfas.esig import canonical, ledger

logger = logging.getLogger("senaite.pfas.esig")

try:
    _TEXT = unicode  # noqa: F821  (Python 2)
    _SEQ = (int, long)  # noqa: F821
except NameError:
    _TEXT = str
    _SEQ = (int,)

LABELS = (("preparer", "Prepared by"), ("reviewer", "Reviewed by"),
          ("authoriser", "Authorised by"), ("released_interim", "Released interim"),
          ("superseded", "Superseded"), ("withdrawn", "Withdrawn"),
          ("qa_approved", "Approved by QA"), ("corrected", "Corrected by"))
# the sign right each meaning needs; withdrawn has none (only its
# signer withdraws, which the withdrawing step checks), nor corrected (the
# page that corrects lets only those who may do the act sign it)
RIGHT_FOR = {"preparer": "preparer", "reviewer": "reviewer",
             # an interim certificate is released at Submit by whoever holds
             # the interim release right, never by the authoriser's right
             "authoriser": "authoriser", "released_interim": "interim_release",
             "superseded": "authoriser", "qa_approved": "qa_approver"}
# the meanings that sign a record's content; superseded and withdrawn rows
# only mark other rows
SIGNING = ("preparer", "reviewer", "authoriser", "released_interim", "qa_approved", "corrected")
# the marks given as part of another signature (the superseded mark a
# reissue puts on the revision before it): such a mark may take the right
# of the signature it is given with, named by right_of
MARKS = ("superseded",)


def _right(meaning, right_of=None):
    """The sign right `meaning` needs: a mark given with another signature
    needs that signature's right, any other meaning its own."""
    if right_of and meaning in MARKS and right_of in RIGHT_FOR:
        return RIGHT_FOR[right_of]
    return RIGHT_FOR.get(meaning)


# meanings one person may not both give on one record of these kinds
SEPARATE = {("preparer", "reviewer"): ("preparation", "batch_record")}
# meanings that need the signer's identity alone: a withdrawal is an
# administrative act of the signer or a Manager, signed with no staff
# record and no signature image
IDENTITY_ONLY = ("withdrawn",)

NO_RIGHT = "You do not hold the %s sign right."
SAME_PERSON = "The %s and the %s must be different people."
ALREADY = "You already signed this record as %s."
NO_STAFF = "No staff record: ask a Manager to add you on People & Roles."
NO_IMAGE = "No signature image on file: upload one on My profile."
NO_CREDENTIAL = "Your credentials could not be confirmed."
# every signature asks again for what its signer types to sign: the password,
# or the PIN they made their default (esig.credentials); the field is named so
# that Zope's error log obscures it
SECRET_FIELD = "sign_password"
NO_SECRET = "Enter your %s to sign."
WRONG_SECRET = "That %s is not right."
LOCKED = "Too many failed attempts: you may sign again in %d minutes."
CREDENTIAL_WORDS = {"password": "password", "pin": "PIN"}
# after a badge sign-in nobody typed a password: signing asks for the PIN
# only, and a person without one cannot sign
BADGE_NEEDS_PIN = "You signed in with your badge: set a PIN on My profile to sign."
EXPIRED = "Your %s has expired: change it on My profile to sign."
# a request that signs more than once (a certificate's issue and the mark on
# the revision it supersedes) confirms the credential once: who, with what
_CONFIRMED = "pfas_sign_confirmed"
NOT_THIS_RECORD = "The signature named to replace or withdraw is not on this record."
SIGNED_AT = "%Y-%m-%dT%H:%M:%SZ"


class SignatureRefused(Exception):
    """The signature may not be given; messages says why, text is them as
    one line for a 409 answer or a redirect."""

    def __init__(self, messages):
        self.messages = [_u(m) for m in messages]
        self.text = " ".join(self.messages)
        Exception.__init__(self, self.text.encode("utf-8") if bytes is str else self.text)

    def __unicode__(self):
        return self.text


def reason(exc):
    """A refused step's message as text: a SignatureRefused's messages, else
    the exception's own (a ledger that could not record the row)."""
    if isinstance(exc, SignatureRefused):
        return exc.text
    try:
        return _u("%s" % (exc,))
    except UnicodeDecodeError:
        return _u(str(exc))


def _u(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value if isinstance(value, _TEXT) else _TEXT(value)


def meaning_label(meaning):
    """The printed words of a meaning; an unknown one is shown as it is."""
    return dict(LABELS).get(meaning, _u(meaning))


# ── seams to Plone, each replaced in tests ───────────────────────────────────

def _staff():
    from senaite.pfas.browser import staff
    return staff


def current_userid(request):
    """The signed-in user's id, the one a signature is given as."""
    return _current_userid(request)


def _current_userid(request):
    from AccessControl import getSecurityManager
    user = getSecurityManager().getUser()
    userid = user.getId() if user is not None else None
    return _u(userid)


def _director_userid():
    """The Laboratory Director's user name; empty when it cannot be read, so
    a failed lookup exempts nobody."""
    try:
        return _u(_staff().director_userid())
    except Exception:                                       # noqa: BLE001
        logger.warning("director not readable", exc_info=True)
        return ""


def _initials(contact):
    from senaite.pfas.staff import staff_record
    try:
        return _u((staff_record(contact) or {}).get("initials"))
    except Exception:                                       # noqa: BLE001
        logger.warning("initials of the signer not readable", exc_info=True)
        return ""


def _zone():
    try:
        from senaite.pfas import lab_time
        return _u(lab_time.zone())
    except Exception:                                       # noqa: BLE001
        logger.warning("laboratory time zone not readable", exc_info=True)
        return ""


def _app_version():
    try:
        import pkg_resources
        return _u(pkg_resources.get_distribution("senaite.pfas").version)
    except Exception:                                       # noqa: BLE001
        return "dev"


def _utcnow():
    return datetime.datetime.utcnow()


def utcnow():
    """Now in UTC, naive: the clock a signature is stamped by."""
    return _utcnow()


def stamp():
    """Now as a signature stores it (SIGNED_AT, UTC)."""
    return _u(_utcnow().strftime(SIGNED_AT))


def staff_info(userid):
    """The staff record a signer is checked against (browser/staff)."""
    return _staff().staff_info(userid) if userid else {"has_contact": False}


# ── who may sign ─────────────────────────────────────────────────────────────

def _credentials():
    from senaite.pfas.esig import credentials
    return credentials


def _rules():
    """The signing rules a manager set (signing_rules); their seeds when the
    store cannot be read."""
    from senaite.pfas import signing_rules
    try:
        from bika.lims import api
        return signing_rules.load(api.get_portal())
    except Exception:                                       # noqa: BLE001
        logger.warning("signing rules not readable: their seeds apply", exc_info=True)
        return signing_rules.settings(None)


def rules():
    return _rules()


def _badge_session(request, userid):
    """True when `userid` is signed in at a registered terminal by their
    badge (browser/badges.badge_session). A request with no cookies at all
    is no terminal's."""
    if not getattr(request, "cookies", None):
        return False
    from senaite.pfas.browser import badges
    return badges.badge_session(request, userid)


def _is_automation(userid):
    """True for a declared service account (data_review.AUTOMATION_GROUP):
    it signs nothing, and its password is never expired."""
    from bika.lims import api
    from senaite.pfas.browser.data_review import AUTOMATION_GROUP
    user = api.get_user(userid)
    return user is not None and AUTOMATION_GROUP in (user.getGroups() or [])


def password_expired(userid, rules_=None):
    """True when `userid`'s password has passed the expiry the rules set;
    never for a service account, nor before the expiry is set."""
    rules_ = rules_ if rules_ is not None else _rules()
    if not rules_.get("expiry_days") or not userid or _is_automation(userid):
        return False
    return _credentials().password_expired(userid, _utcnow(), rules_)


def credential_kind(request, userid):
    """What signing asks `userid` for in this request: "pin" after a badge
    sign-in or when their profile makes the PIN the default, else
    "password"."""
    cr = _credentials()
    if userid and _badge_session(request, userid):
        return cr.PIN
    return cr.method(userid)


def _check_password(userid, secret):
    """True when `secret` is the signed-in user's current password (the
    user folder's own check)."""
    from bika.lims import api
    return bool(api.get_tool("portal_membership").testCurrentPassword(secret))


def _now():
    import time
    return time.time()


def _take_secret(request):
    """The secret the request posted, removed from it at once so nothing
    later (a draft, a redirect, an error log) can hold it."""
    secret = None
    for store in (getattr(request, "form", None), getattr(request, "other", None)):
        if isinstance(store, dict) and SECRET_FIELD in store:
            value = store.pop(SECRET_FIELD)
            secret = value if secret is None else secret
    if isinstance(secret, (list, tuple)):
        secret = secret[0] if secret else None
    return _u(secret) if secret is not None else ""


def _confirmed(request):
    other = getattr(request, "other", None)
    return other.setdefault(_CONFIRMED, {}) if isinstance(other, dict) else None


def confirm(request, userid):
    """(kind, None) when the request carries the signer's own credential,
    kind "password" or "pin" (the one their profile makes their default, and
    always the PIN after a badge sign-in); else (None, why). Every signature
    asks for it again; a request that signs more than once confirms it once.
    A failure is counted, and too many lock the person's signing for a
    while (esig.credentials, by the rules a manager set); a lock is checked
    before the credential is, and an expired password or PIN signs nothing.
    The secret is never logged."""
    if not userid:
        return None, NO_CREDENTIAL
    cache = _confirmed(request)
    if cache is not None and cache.get(userid):
        return cache[userid], None
    secret = _take_secret(request)
    cr = _credentials()
    try:
        rules_ = _rules()
        badge = _badge_session(request, userid)
        kind = cr.PIN if badge else cr.method(userid)
        wait = cr.locked(userid, _now(), rules=rules_)
        if wait:
            return None, LOCKED % max(1, (wait + 59) // 60)
        word = CREDENTIAL_WORDS.get(kind, kind)
        if badge and not cr.has_pin(userid):
            return None, BADGE_NEEDS_PIN
        if kind == cr.PIN and cr.pin_expired(userid, _utcnow(), rules_):
            return None, EXPIRED % word
        if kind == cr.PASSWORD and password_expired(userid, rules_):
            return None, EXPIRED % word
        if not secret:
            return None, NO_SECRET % word
        ok = cr.check_pin(userid, secret) if kind == cr.PIN else _check_password(userid, secret)
        if not ok:
            cr.failure(userid, kind, _now(), stamp(), rules=rules_)
            logger.warning("signature by %s refused: the %s did not match", userid, word)
            return None, WRONG_SECRET % word
        cr.clear(userid)
        if kind == cr.PASSWORD:
            cr.password_seen(userid, stamp())
    except Exception:                                       # noqa: BLE001
        # fail closed: a credential that cannot be checked confirms nothing
        logger.error("the signing credential of %s could not be checked", userid, exc_info=True)
        return None, NO_CREDENTIAL
    if cache is not None:
        cache[userid] = kind
    return kind, None


def credential_ok(request, userid):
    """The Part 11 credential hook, the one place a signature's credential is
    confirmed (confirm): the kind the signer typed, "password" or "pin",
    which the ledger entry records; "" when it is not confirmed."""
    return confirm(request, userid)[0] or ""


def explain(msgs, why):
    """The refusal messages with the credential's own reason in place of
    the general one."""
    if why and NO_CREDENTIAL in msgs:
        return [why if m == NO_CREDENTIAL else m for m in msgs]
    return msgs


def problems(kind, meaning, signer_userid, others, staff_info, credential, right_of=None):
    """Every reason signer_userid may not sign this record with meaning, as
    messages; empty when they may. others is [(meaning, userid)] of the
    record's live rows; staff_info is browser/staff.staff_info of the
    signer; credential is credential_ok's answer. The Laboratory Director
    holds every sign right. A meaning of IDENTITY_ONLY needs the
    credential alone. right_of names the meaning whose sign right this one
    takes (a mark given as part of another signature: _right)."""
    info = staff_info or {}
    out = []
    if not credential:
        out.append(NO_CREDENTIAL)
    if meaning in IDENTITY_ONLY:
        return out
    has_contact = bool(info.get("has_contact"))
    if not has_contact:
        out.append(NO_STAFF)
    right = _right(meaning, right_of)
    if right and right not in (info.get("sign_as") or []):
        director = _director_userid()
        if not (signer_userid and director == signer_userid):
            out.append(NO_RIGHT % meaning_label(meaning))
    others = [(m, u) for m, u in (others or [])]
    for pair, kinds in sorted(SEPARATE.items()):
        if kind in kinds and meaning in pair:
            other = pair[1] if meaning == pair[0] else pair[0]
            if (other, signer_userid) in others:
                out.append(SAME_PERSON % (meaning_label(pair[0]), meaning_label(pair[1])))
    if (meaning, signer_userid) in others:
        out.append(ALREADY % meaning_label(meaning))
    if has_contact and not info.get("signature"):
        out.append(NO_IMAGE)
    return out


# ── what the rows say ────────────────────────────────────────────────────────

def _entry(row):
    e = row.get("entry")
    return e if isinstance(e, dict) else {}


def _signer(row):
    return _u((_entry(row).get("signer") or {}).get("userid"))


def signer_of(row):
    """The user id a ledger row was signed by."""
    return _signer(row)


def back_references(rows):
    """(superseded_by, withdrawn_by): seq -> the first later row naming it in
    supersedes, or a withdrawn row naming it in withdraws; a reference
    counts only within one record. rows may span many records (the whole
    ledger) or be one record's. A reference that is not a row number (a row
    written around the ledger) names nothing."""
    by_seq = dict((r["seq"], r) for r in rows)
    superseded_by, withdrawn_by = {}, {}
    for r in rows:
        e = _entry(r)
        here = (e.get("kind"), e.get("record_id"))
        refs = [("supersedes", superseded_by)]
        if e.get("meaning") == "withdrawn":
            refs.append(("withdraws", withdrawn_by))
        for field, out in refs:
            ref = e.get(field)
            if isinstance(ref, bool) or not isinstance(ref, _SEQ):
                continue
            target = by_seq.get(ref)
            if target is not None and (_entry(target).get("kind"), _entry(target).get("record_id")) == here:
                out.setdefault(target["seq"], r)
    return superseded_by, withdrawn_by


def is_live(row, superseded_by, withdrawn_by):
    """A row signing content that is neither superseded nor withdrawn."""
    return (_entry(row).get("meaning") in SIGNING and row["seq"] not in superseded_by
            and row["seq"] not in withdrawn_by)


def status(kind, record_id, current_hash, path=None, hashes=None):
    """The record's rows read against its current hash:
    rows        every row, in seq order
    valid       meaning -> the latest live row signed on current_hash
    changed     True when a live row was signed on other content and no
                later valid row of its meaning exists
    superseded  the rows a later row names in supersedes, each with
                "superseded_by"
    withdrawn   the rows a withdrawn row names in withdraws, each with
                "withdrawn_by"
    live        the live rows, whatever content they signed
    A live row signs content (preparer, reviewer, authoriser, released
    interim) and is neither superseded nor withdrawn. hashes, {meaning:
    hash}, reads that meaning's rows against its own hash: a record whose
    signers attest different parts of it (current_hash for the others)."""
    hashes = hashes or {}

    def want(e):
        return hashes.get(e.get("meaning"), current_hash)
    rows = ledger.for_record(kind, record_id, path=path)
    by_seq = dict((r["seq"], r) for r in rows)
    superseded_by, withdrawn_by = back_references(rows)
    live = [r for r in rows if is_live(r, superseded_by, withdrawn_by)]
    valid = {}
    for r in live:
        if _entry(r).get("record_hash") == want(_entry(r)):
            valid[_entry(r)["meaning"]] = r
    changed = False
    for r in live:
        e = _entry(r)
        if e.get("record_hash") != want(e):
            later = valid.get(e["meaning"])
            if later is None or later["seq"] < r["seq"]:
                changed = True
    return {
        "rows": rows, "valid": valid, "changed": changed, "live": live,
        "superseded": [dict(by_seq[s], superseded_by=superseded_by[s]) for s in sorted(superseded_by)],
        "withdrawn": [dict(by_seq[s], withdrawn_by=withdrawn_by[s]) for s in sorted(withdrawn_by)],
    }


NO_SIGNATURES = "No signatures on this record"
CONTENT_CHANGED = "Signed content changed"
CACHE_MISMATCH = "The record's signatures do not match the ledger"
WITHDRAWN = "A signature on this record was withdrawn"


def verify_rows(st, cached):
    """None when a record's signatures hold, else why not. st is status()
    of the record against its content now: a live signature on other
    content means the content changed; a record with no signature on this
    content is not verified, nor one whose signature was withdrawn and not
    given again; every row the record's display cache (cached) names must
    be in the ledger with the same row hash."""
    if st.get("changed"):
        return CONTENT_CHANGED
    valid = st.get("valid") or {}
    for r in st.get("withdrawn") or []:
        later = valid.get(_entry(r).get("meaning"))
        if later is None or later["seq"] < r["seq"]:
            return WITHDRAWN
    if not valid:
        return NO_SIGNATURES
    in_ledger = dict((r.get("seq"), r.get("hash")) for r in st.get("rows") or [])
    for c in cached or []:
        if in_ledger.get(c.get("seq")) != c.get("hash"):
            return CACHE_MISMATCH
    return None


def merge_cache(cached, rows):
    """The display cache with rows added, one per ledger seq: a replayed
    signature returns its existing row, which is not listed twice."""
    out = dict((r.get("seq"), r) for r in cached or [])
    for r in rows or []:
        out[r.get("seq")] = r
    return [out[k] for k in sorted(out, key=lambda s: (s is None, s))]


def cache(rows):
    """The record's display cache of its rows: seq, hash, meaning, signer
    user id and full name, signed_at."""
    out = []
    for r in rows or []:
        e = _entry(r)
        out.append({"seq": r.get("seq"), "hash": r.get("hash"), "meaning": e.get("meaning"),
                    "signer": _signer(r), "fullname": (e.get("signer") or {}).get("fullname"),
                    "signed_at": e.get("signed_at")})
    return out


def images_dir(path=None):
    """Where the signature image snapshots are kept: beside the ledger file."""
    return os.path.join(os.path.dirname(_u(path or ledger.DB_PATH)), "signatures", "images")


_MIME = (("png", "image/png"), ("jpg", "image/jpeg"))


def kept_image(sha, path=None):
    """(bytes, mime) of the signature image kept as <sha>.<png|jpg>, or
    (None, None) when the file is missing or no longer hashes to sha."""
    sha = _u(sha)
    if not sha:
        return None, None
    for ext, mime in _MIME:
        target = os.path.join(images_dir(path), "%s.%s" % (sha, ext))
        if not os.path.isfile(target):
            continue
        with open(target, "rb") as fh:
            data = fh.read()
        if canonical.sha256_bytes(data) != sha:
            logger.error("signature image %s does not match its name", target)
            return None, None
        return data, mime
    logger.error("signature image %s is missing", sha)
    return None, None


def has_kept_image(sha, path=None):
    """True when the image kept as sha is on disk and still hashes to it:
    kept_image's answer, read quietly (a check run for every row of a
    listing logs nothing)."""
    sha = _u(sha)
    if not sha:
        return False
    for ext, _mime in _MIME:
        target = os.path.join(images_dir(path), "%s.%s" % (sha, ext))
        if os.path.isfile(target):
            with open(target, "rb") as fh:
                return canonical.sha256_bytes(fh.read()) == sha
    return False


def image_uri(sha, path=None):
    """The signature image kept as sha, as a data URI; "" when it is
    missing or altered."""
    data, mime = kept_image(sha, path=path)
    if data is None:
        return ""
    return "data:%s;base64,%s" % (mime, base64.b64encode(data).decode("ascii"))


def snapshot_uri(row, path=None):
    """The signature image a row was signed with, as a data URI, read from
    its snapshot (never the person's current image); "" when the file is
    missing or no longer hashes to the row's image_sha256."""
    uri = image_uri(_entry(row).get("image_sha256"), path=path)
    if not uri and _entry(row).get("image_sha256"):
        logger.error("signature image of row %s is missing or altered", row.get("seq"))
    return uri


def keep_signature_image(userid, path=None):
    """Keep the signer's image as it is now (images_dir/<sha256>.<ext>) and
    return its sha256: a signature given before its ledger row is written
    (the certificate's, on Data Review) prints and is recorded with the
    image of that moment. Raises SignatureRefused when the signer has no
    PNG or JPEG image, ledger.LedgerError when it cannot be written."""
    _contact, image = _image(_staff(), userid)
    ext = image_ext(image)
    if not ext:
        raise SignatureRefused([NO_IMAGE])
    try:
        _keep_image(path, image, ext)
    except (IOError, OSError):
        logger.error("signature image of %s not kept", userid, exc_info=True)
        raise ledger.LedgerError("The signature image could not be kept.")
    return canonical.sha256_bytes(image)


# ── signing ──────────────────────────────────────────────────────────────────

def _image(staff, userid):
    contact = staff.contact_for(userid) if userid else None
    if contact is None:
        return None, None
    try:
        return contact, staff.image_bytes(contact.getSignature())
    except Exception:                                       # noqa: BLE001
        logger.warning("signature of %s unreadable", userid, exc_info=True)
        return contact, None


def _earlier(current, meaning, record_hash):
    """The seq of the live row of meaning signed on other content, the one a
    new signature on this content replaces; None when there is none."""
    rows = [r for r in current["live"] if _entry(r).get("meaning") == meaning
            and _entry(r).get("record_hash") != record_hash]
    return rows[-1]["seq"] if rows else None


def _replacing(current, row, userid):
    """The live row of another signer that replaced row, following each
    replacement to the one that stands; None when the chain ends in no
    such row."""
    by = dict((r["seq"], r["superseded_by"]) for r in current["superseded"])
    live = set(r["seq"] for r in current["live"])
    seen = set()
    nxt = by.get(row["seq"])
    while nxt is not None and nxt["seq"] not in seen:
        if nxt["seq"] in live and _signer(nxt) != userid:
            return nxt["seq"]
        seen.add(nxt["seq"])
        nxt = by.get(nxt["seq"])
    return None


def _resolve_supersedes(current, meaning, record_hash, userid, auto_supersede):
    """The row a new signature names in supersedes when the caller names
    none (a named one always wins). The ledger's key holds supersedes, so
    the value decides between a replay and a new row.
    - The signer's live row of this meaning on this content is a replay:
      the same supersedes as that row, so the ledger returns it.
    - Otherwise, with auto_supersede, in order: the live row of this
      meaning on other content, whoever signed it; else the signer's own
      latest row on this content when it was withdrawn; else the live row
      of another signer that replaced the signer's own row on this
      content; else none.
    - A value that would meet one of the signer's earlier rows on this
      content (the ledger would hand back a row that no longer stands)
      names the signer's latest such row instead, so the signature is a
      new row; this holds for a record being made too."""
    mine = [r for r in current["rows"] if _entry(r).get("meaning") == meaning
            and _entry(r).get("record_hash") == record_hash and _signer(r) == userid]
    live_seqs = set(r["seq"] for r in current["live"])
    standing = [r for r in mine if r["seq"] in live_seqs]
    if standing:
        return _entry(standing[-1]).get("supersedes")
    choice = None
    if auto_supersede:
        choice = _earlier(current, meaning, record_hash)
        if choice is None and mine:
            withdrawn = set(r["seq"] for r in current["withdrawn"])
            if mine[-1]["seq"] in withdrawn:
                choice = mine[-1]["seq"]
            else:
                choice = _replacing(current, mine[-1], userid)
    if mine and choice in [_entry(r).get("supersedes") for r in mine]:
        choice = mine[-1]["seq"]
    return choice


def image_ext(data):
    """The file extension of a signature image by its first bytes: png or
    jpg; None for anything else."""
    if data and data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data and data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    return None


def _keep_image(path, data, ext):
    """Keep the signature image as <sha256>.<ext>: one file per picture,
    whatever rows name it. Written whole through a temporary file, so a
    retry after a failed write writes the same file again."""
    folder = images_dir(path)
    if not os.path.isdir(folder):
        try:
            os.makedirs(folder)
        except OSError:
            if not os.path.isdir(folder):
                raise
    target = os.path.join(folder, "%s.%s" % (canonical.sha256_bytes(data), ext))
    if os.path.isfile(target):
        with open(target, "rb") as fh:
            if fh.read() == data:
                return
    # a name of its own per write: Zope's threads share one process
    tmp = os.path.join(folder, "%s.tmp" % uuid.uuid4().hex)
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            # on disk before the ledger row that names it commits
            fh.flush()
            os.fsync(fh.fileno())
        os.rename(tmp, target)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


# the signer block's parts a signature given before its row may carry
SIGNER_OVERRIDES = ("fullname", "credentials", "initials")


def _overrides(given):
    """The signer block's values as at signing, from signer_overrides: only
    fullname, credentials and initials, each when given (credentials empty
    at signing stay empty); an empty name or initials never replaces the
    signer's."""
    out = {}
    for key in SIGNER_OVERRIDES:
        value = (given or {}).get(key)
        if value is None or (key != "credentials" and not _u(value)):
            continue
        out[key] = _u(value)
    return out


def sign(portal, request, kind, record_id, revision, record_hash, meaning,
         note="", supersedes=None, withdraws=None, path=None, auto_supersede=True,
         image_sha256=None, signer_overrides=None, credential=None, right_of=None):
    """Sign the record's content as the current user: check every refusal,
    keep the signature image as images_dir/<sha256>.<png|jpg>, then append
    the ledger row. Returns the ledger row with "reused" (True when this
    signer already gave this meaning to this content: that row stands and
    no image is written). supersedes, when not given, follows
    _resolve_supersedes: a replay keeps its row's, a re-sign after the
    signer's row was taken back names a row so it is a new one, and the
    live row of this meaning on other content is replaced unless
    auto_supersede is False (a record being made supersedes nothing);
    withdraws names the row a withdrawal takes back. The signer block keeps the credentials as at signing.
    image_sha256 names an image kept when the signature was given
    (keep_signature_image): the row records it, not the image on file now,
    so the row matches what was printed; that file gone refuses the
    signature (NO_IMAGE). A meaning of IDENTITY_ONLY records no image
    (image_sha256 null) and needs no staff record. signer_overrides gives the signer's
    fullname, credentials and initials as they were when the signature was
    given (_overrides): the row records them, not the staff record now.
    credential names the credential the signer already confirmed for this
    act ("password" or "pin": a certificate's signature is given on Data
    Review and its row written at publish); otherwise the request must
    carry it (confirm), and the row records which. right_of names the
    meaning a mark is given with (problems): the mark is signed under, and
    records, that meaning's right.
    Raises SignatureRefused, or ledger.LedgerError when the image or the
    row could not be recorded."""
    staff = _staff()
    userid = _current_userid(request)
    info = staff.staff_info(userid) if userid else {"has_contact": False}
    identity_only = meaning in IDENTITY_ONLY
    contact, image = (None, None) if identity_only else _image(staff, userid)
    kept_gone = False
    if image_sha256 and not identity_only:
        kept, _mime = kept_image(image_sha256, path=path)
        if kept is not None:
            image = kept
        else:
            # the row would record another picture than the one printed
            logger.error("signature of %s refused: the image kept at signing is missing", userid)
            kept_gone = True
    current = status(kind, record_id, record_hash, path=path)
    # who signed what is read from every live row, whatever content it
    # signed: a preparer stays the preparer after the content changes. The
    # same signer giving the same meaning again is left out: on the same
    # content that is a replay the ledger reuses, on new content it is a
    # re-sign that supersedes their own row.
    others = [(_entry(r).get("meaning"), _signer(r)) for r in current["live"]
              if not (_entry(r).get("meaning") == meaning and _signer(r) == userid)]
    if credential is not None:
        cred, why = (credential, None) if credential in CREDENTIAL_WORDS else ("", NO_CREDENTIAL)
    else:
        cred, why = confirm(request, userid)
    msgs = explain(problems(kind, meaning, userid, others, info, cred, right_of=right_of), why)
    # the image bytes decide: a PNG or JPEG, whatever staff_info reported
    ext = None if identity_only else image_ext(image)
    if not identity_only and NO_IMAGE not in msgs and (kept_gone or (not ext and info.get("has_contact"))):
        msgs.append(NO_IMAGE)
    # a back-reference names a row of this record
    seqs = [r["seq"] for r in current["rows"]]
    if (supersedes is not None and supersedes not in seqs) or \
            (withdraws is not None and withdraws not in seqs):
        msgs.append(NOT_THIS_RECORD)
    if msgs:
        raise SignatureRefused(msgs)
    if supersedes is None and meaning in SIGNING:
        supersedes = _resolve_supersedes(current, meaning, record_hash, userid, auto_supersede)
    entry = {
        "kind": _u(kind), "record_id": _u(record_id), "revision": revision,
        "record_hash": _u(record_hash), "meaning": _u(meaning),
        "signer": {"userid": userid, "fullname": _u(info.get("fullname")) or userid,
                   "initials": _initials(contact) if contact is not None else "",
                   "right": _u(_right(meaning, right_of)),
                   "credentials": _u(info.get("credentials"))},
        "signed_at": stamp(), "zone": _zone(),
        "note": _u(note).strip() or None, "supersedes": supersedes, "withdraws": withdraws,
        "image_sha256": None if identity_only else canonical.sha256_bytes(image), "credential": _u(cred),
        "app": _app_version(),
    }
    entry["signer"].update(_overrides(signer_overrides))
    # the image is on disk before the row that names it; a replay (the row
    # the ledger will reuse: the same key, supersedes and withdraws included)
    # writes nothing; a new row always has its image on disk
    replay = [r for r in current["rows"] if _entry(r).get("meaning") == meaning
              and _entry(r).get("record_hash") == record_hash and _signer(r) == userid
              and _entry(r).get("supersedes") == supersedes
              and _entry(r).get("withdraws") == withdraws]
    if not replay and not identity_only:
        try:
            _keep_image(path, image, ext)
        except (IOError, OSError):
            logger.error("signature image of %s not kept", userid, exc_info=True)
            raise ledger.LedgerError("The signature image could not be kept.")
    added = ledger.append(entry, path=path)
    for r in ledger.for_record(kind, record_id, path=path):
        if r["seq"] == added["seq"]:
            return dict(r, reused=added["reused"])
    raise ledger.LedgerError("The signature could not be recorded.")
