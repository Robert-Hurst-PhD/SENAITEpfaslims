# -*- coding: utf-8 -*-
"""The certificate's signature.

The authoriser signs on Data Review's Issue certificate card before the
certificate is generated: a pending signature is kept on each sample
(pending_record). Publishing is refused without the publisher's own pending
signature (refusal). When the sample is published, the register's
subscriber turns the pending signature into the ledger row, bound to the
stored PDF as it goes out (sign_issue); a reissue marks the previous
revision's row superseded.

    pending_record(userid, interim, note, at, signer)  the record kept on
                                 the sample
    signer_snapshot(userid)      the signer as printed, the image kept now
    problems(request, interim)   why the current user may not sign it
    refusal(pending, userid, current_interim)  why publishing is refused
    state_refusal(pending, state)  why the sample's review state issues
                                 nothing on it: before verification only
                                 an interim
    mark_refusal(pending, mark)  why the signature does not match the
                                 interim mark the certificate was
                                 generated with
    sign_issue(...)              the ledger rows of one issue, as register
                                 entry fields

Python 2.7; pure apart from the signing core's seams.
"""
from __future__ import absolute_import, unicode_literals

import datetime
import logging

from senaite.pfas.esig import canonical, ledger, signing

logger = logging.getLogger("senaite.pfas.esig.certificate")

KIND = "certificate"
SIGN_FIRST = "Sign the certificate on Data Review before issuing it"
FINAL_DUE = "A final certificate is due; give a reason to issue another interim."
NOT_SIGNED = "No signature was given on Data Review."
OTHER_SIGNER = "Signed on Data Review by %s, published by %s."
NO_PDF = "No stored certificate to sign."
STALE = "Sign the certificate again on Data Review"
KEPT_IMAGE_GONE = "The kept signature image is missing: sign the certificate again on Data Review"
GENERATED_INTERIM = "The certificate was generated as interim: generate it again."
GENERATED_FINAL = "The certificate was generated as final: generate it again."
GENERATED_OTHER = "The certificate was generated for another signature: generate it again."
# what identifies the signature a certificate printed
SIGNATURE_KEYS = ("userid", "image_sha256", "at")
# how long a signature given on Data Review stays good for issuing
MAX_AGE = datetime.timedelta(hours=24)


def meaning_for(interim):
    """An interim certificate is released, a final one authorised."""
    return "released_interim" if interim else "authoriser"


def _u(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value if isinstance(value, type("")) else type("")(value)


def now_stamp(now=None):
    """Now as a signature records it (signing.SIGNED_AT): UTC, to the
    second. A stored stamp; the card shows it through lab_time."""
    now = now or signing.utcnow()
    return _u(now.replace(microsecond=0).isoformat() + "Z")


def signed_at(pending):
    """When the pending signature was given, a naive UTC datetime; None
    when its stamp is missing or cannot be read."""
    try:
        return datetime.datetime.strptime(_u((pending or {}).get("at")), signing.SIGNED_AT)
    except (TypeError, ValueError):
        return None


def is_stale(pending, now):
    """True when the pending signature is older than MAX_AGE, or its time
    cannot be read: a signature is an act of now, not a standing permit."""
    at = signed_at(pending)
    return at is None or now - at > MAX_AGE


def pending_record(userid, interim, note, at, signer=None, credential=None):
    """The signature kept on a sample until its certificate is published;
    signer (signer_snapshot) adds the signer as at signing: the certificate
    generated before publish prints it. credential, what the signer typed
    to give it ("password" or "pin"): the ledger row written at publish
    records it."""
    interim = bool(interim)
    rec = {"userid": _u(userid), "meaning": meaning_for(interim),
           "note": _u(note).strip(), "interim": interim, "at": _u(at)}
    if credential:
        rec["credential"] = _u(credential)
    rec.update(signer or {})
    return rec


def _confirmed_by(pending):
    """The credential a pending signature was given with, or "" when it
    names none (given before every signature asked for one)."""
    cred = _u((pending or {}).get("credential"))
    return cred if cred in signing.CREDENTIAL_WORDS else ""


def signer_snapshot(userid, path=None):
    """{fullname, credentials, image_sha256}: the signer as the certificate
    prints them, the image kept now (signing.keep_signature_image) so the
    ledger row written at publish records the same picture. Raises
    signing.SignatureRefused or ledger.LedgerError when no image can be
    kept."""
    info = signing.staff_info(userid)
    sha = signing.keep_signature_image(userid, path=path)
    # a name, never the account id (the signer holds a staff record to sign)
    name = _u(info.get("fullname"))
    return {"fullname": name if name != _u(userid) else "",
            "credentials": _u(info.get("credentials")), "image_sha256": _u(sha)}


def problems(request, interim, pending=None):
    """Every reason the signed-in person may not sign a certificate with
    this meaning, as messages; empty when they may. A certificate has no
    earlier signer to keep apart from: the record is new at each issue.
    The credential is the one the request carries (the sign dialog), or,
    for a signature already given (`pending`, asked again at publish), the
    one it was given with."""
    userid = signing.current_userid(request)
    if pending is not None:
        cred = _confirmed_by(pending)
        why = None if cred else STALE
    else:
        cred, why = signing.confirm(request, userid)
    return signing.explain(signing.problems(KIND, meaning_for(interim), userid, [],
                                            signing.staff_info(userid), cred), why)


def refusal(pending, userid, current_interim, now):
    """Why the sample may not be published by userid at `now` (naive UTC),
    or None. Only the publisher's own pending signature issues, and only
    within MAX_AGE of its giving; while the current revision is interim,
    another interim needs a reason (the signature's note)."""
    pending = pending or {}
    if not userid or not pending.get("userid") or pending.get("userid") != userid:
        return SIGN_FIRST
    if is_stale(pending, now) or not _confirmed_by(pending):
        return STALE
    if current_interim and pending.get("interim") and not (pending.get("note") or "").strip():
        return FINAL_DUE
    return None


# a sample's states from which a final certificate issues: its run verified
VERIFIED_STATES = ("verified", "published")
# results submitted, not yet verified: an interim certificate issues
# (core's prepublish), never a final one
SUBMITTED_STATE = "to_be_verified"
FINAL_NOT_VERIFIED = "A final certificate is issued once the run is verified."
NOT_SUBMITTED = "The results are not submitted for verification yet."


def state_refusal(pending, state):
    """Why the sample, in review state `state`, may not be issued on the
    pending signature, or None. A verified sample issues either kind; a
    sample whose results are submitted but not verified issues only an
    interim certificate; any other sample issues nothing."""
    if state in VERIFIED_STATES:
        return None
    if state == SUBMITTED_STATE:
        return None if (pending or {}).get("interim") else FINAL_NOT_VERIFIED
    return NOT_SUBMITTED


def mark_signature(pending):
    """The signature a certificate was generated with, as its mark keeps
    it: who signed, the image kept then and when; empty when nobody had
    signed (the certificate prints Not yet signed)."""
    pending = pending or {}
    return dict((k, _u(pending.get(k))) for k in SIGNATURE_KEYS)


def mark_refusal(pending, mark):
    """Why the pending signature may not issue the stored certificate, or
    None: the certificate prints interim or final as it was generated
    (`mark`, recorded at Generate), so a signature of the other kind would
    issue a document that says otherwise; and it prints the signature it
    was generated with, so another one (another signer, or the same signer
    again with a new image or time) would record a row the PDF does not
    show. A certificate stored with no mark, or with a mark that keeps no
    signature, is not judged by what it lacks."""
    if not mark:
        return None
    if bool(mark.get("interim")) != bool((pending or {}).get("interim")):
        return GENERATED_INTERIM if mark.get("interim") else GENERATED_FINAL
    printed = mark.get("signature")
    if isinstance(printed, dict) and dict((k, _u(printed.get(k))) for k in SIGNATURE_KEYS) != \
            mark_signature(pending):
        return GENERATED_OTHER
    return None


def _note(pending, shown):
    text = "Signed %s on Data Review" % shown(pending.get("at") or "")
    extra = _u(pending.get("note")).strip()
    return "%s. %s" % (text, extra) if extra else text


def sign_issue(portal, request, entry, prev, pending, pdf, path=None, shown=None):
    """The register entry's signature fields for one issue: the pending
    signature appended as the ledger row of entry's report id and
    revision, bound to the stored PDF's sha256. A pending signature that is
    missing or another person's is recorded unsigned with the reason (the
    publish guard refuses those first). A signature the signing core
    refuses, or a row the ledger cannot write, raises
    signing.SignatureRefused or ledger.LedgerError: the certificate is not
    issued without its row. On a reissue, the previous revision's signed
    row is marked superseded by the publisher, under the sign right of what
    is signed now (a second interim's mark under the interim release
    right, a final's under the authoriser's); a mark that cannot be
    written is recorded on the entry and does not stop the issue, whose
    own row already stands. The new row supersedes nothing of its own."""
    shown = shown or (lambda value: value)
    userid = signing.current_userid(request)
    out = {"certificate_sha256": canonical.sha256_bytes(pdf) if pdf else "",
           "signature_seq": None, "unsigned": True,
           "supersedes_seq": (prev or {}).get("signature_seq")}
    if pending:
        out["interim"] = bool(pending.get("interim"))
    meaning = (pending.get("meaning") or meaning_for(pending.get("interim"))) if pending else None
    why = None
    if not pending or not pending.get("userid"):
        why = NOT_SIGNED
    elif pending.get("userid") != userid:
        why = OTHER_SIGNER % (pending.get("userid"), userid)
    elif not pdf:
        why = NO_PDF
    if why is None:
        # a refusal or a ledger failure propagates: the publish aborts
        row = signing.sign(portal, request, KIND, entry["report_id"], entry["revision"],
                           out["certificate_sha256"], meaning,
                           note=_note(pending, shown), path=path, auto_supersede=False,
                           # the image, name and credentials the generated
                           # certificate printed
                           image_sha256=pending.get("image_sha256"),
                           signer_overrides=dict((k, pending[k]) for k in signing.SIGNER_OVERRIDES
                                                 if k in pending),
                           # confirmed when the signature was given on Data Review
                           credential=_confirmed_by(pending))
        signer = (row.get("entry") or {}).get("signer") or {}
        out.update({"signature_seq": row["seq"], "unsigned": False,
                    "signed_by": signer.get("fullname") or userid, "signed_by_userid": userid})
    if why is not None:
        logger.warning("certificate %s issued unsigned: %s", entry.get("report_id"), why)
        out["signature_error"] = why
    if prev and prev.get("signature_seq") is not None:
        try:
            mark = signing.sign(portal, request, KIND, prev["report_id"], prev["revision"],
                                prev.get("certificate_sha256") or "", "superseded",
                                note="Superseded by %s" % entry["report_id"],
                                supersedes=prev["signature_seq"], path=path, auto_supersede=False,
                                credential=_confirmed_by(pending) or None,
                                # the right of what was signed now; an issue
                                # recorded unsigned signed nothing
                                right_of=meaning if why is None else None)
        except (signing.SignatureRefused, ledger.LedgerError) as exc:
            logger.warning("certificate %s not marked superseded: %s", prev.get("report_id"), exc)
            out["superseded_error"] = signing.reason(exc)
        else:
            out["superseded_seq"] = mark["seq"]
    return out
