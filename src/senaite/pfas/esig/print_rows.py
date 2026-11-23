# -*- coding: utf-8 -*-
"""A signed record's print, from the signature ledger: the Signatures
table's rows and the fields a signed role prints as at signing (its kept
image, name and credentials).

    table_and_fields(st, current, roles=("preparer", "reviewer"), path=None)
        -> (rows, fields)
    certificate(entry, path=None)
        -> {"authorized": the authoriser as signed, "signatures": rows} or None
    pending_certificate(pending, path=None)  the same from the signature
        given on Data Review, before the certificate is issued
    unsigned_certificate(interim)  the same for a certificate nobody signed

st is esig.signing.status of the record; current, the hash it reads each
role against, or {meaning: hash} when its signers attest different parts of
it. Every signed record's print calls this one helper. Python 2.7; the
laboratory clock is imported inside the function.
"""
from __future__ import absolute_import, unicode_literals

from senaite.pfas import report_documents as rd


def _when(value):
    """A signature time on the laboratory clock, with its zone."""
    from senaite.pfas import lab_time, print_doc
    return u"%s %s" % (lab_time.show(value), print_doc.zone_label()) if value else u""


def _certificate_when(value):
    """A signature time on a certificate: the laboratory clock, its zone
    named once in the certificate's time zone note while the zone converts
    (document_templates.TIMES_NOTE); with the zone in the cell otherwise."""
    from senaite.pfas import lab_time
    if value and lab_time.active():
        return lab_time.show(value)
    return _when(value)


def table_and_fields(st, current, roles=("preparer", "reviewer"), path=None, when=_when):
    """(the Signatures table's rows, the fields a signed role prints from
    the ledger) of a record read against its content now. A signature time
    prints on the laboratory clock with its zone (`when`); a changed
    signature names when the change was found."""
    from senaite.pfas import print_doc
    from senaite.pfas.esig import signing

    def image(row):
        return signing.snapshot_uri(row, path=path)
    rows = rd.signature_rows(st, current, when, changed_at=print_doc.now_stamp())
    fields = rd.signature_images(st, current, roles, image)
    fields.update(rd.signer_fields(st, current, roles))
    return rows, fields


# a certificate's authoriser signs as authoriser, or as released interim
CERTIFICATE_ROLES = ("authoriser", "released_interim")
NO_ROW = u"The ledger holds no signature %s for %s."
NO_IMAGE = rd.NO_KEPT_IMAGE
# the certificate's authoriser block names the time as the signing time
SIGNED = u"Signed %s"
# the certificate's own hash exists only once it is issued: the register,
# the Signatures page and the verifier hold it
RECORDED_AT_ISSUE = u"recorded at issue"
NOT_YET_SIGNED = rd.NOT_YET_SIGNED
# a signer with no name kept: never the account id (coa_document's placeholder)
NO_STAFF_RECORD = u"Name not on file"


def certificate(entry, path=None):
    """What a certificate prints from the ledger for the register entry of
    the revision printed: {"authorized": the authoriser as signed (name,
    credentials, the image kept at signing, the laboratory time, the first
    twelve characters of the signed hash), "signatures": the Signatures
    table's rows}; None when the entry has no signature row (a revision not
    yet signed prints as it does today). The authoriser is read by the
    entry's row, whatever has happened to it since: a signed role prints as
    signed once its right or image is gone, and a reissue's superseded row
    still names who authorised the revision; a withdrawn row prints its
    signer with the withdrawal time, no image and no hash. A kept image
    that is missing or altered raises ValueError: the print is refused
    rather than drawn without it."""
    from senaite.pfas.esig import signing
    seq = (entry or {}).get("signature_seq")
    if seq is None:
        return None
    record_id = entry.get("report_id") or u""
    current = entry.get("certificate_sha256") or u""
    st = signing.status("certificate", record_id, current, path=path)
    found = [r for r in st.get("rows") or [] if r.get("seq") == seq]
    if not found:
        raise ValueError(NO_ROW % (seq, record_id))
    row = found[0]
    e = row.get("entry") if isinstance(row.get("entry"), dict) else {}
    signer = e.get("signer") or {}
    withdrawn = [w for w in st.get("withdrawn") or [] if w.get("seq") == seq]
    rows, _fields = table_and_fields(st, current, roles=CERTIFICATE_ROLES, path=path,
                                     when=_certificate_when)
    if withdrawn:
        # a withdrawn signature counts as unsigned: the block names who
        # signed and when it was withdrawn, with no image and no hash
        by = withdrawn[0].get("withdrawn_by") or {}
        by = by.get("entry") if isinstance(by.get("entry"), dict) else {}
        image, at, signed_hash = u"", rd.WITHDRAWN % _certificate_when(by.get("signed_at")), u""
    else:
        image = signing.snapshot_uri(row, path=path)
        if not image:
            raise ValueError(NO_IMAGE % seq)
        at, signed_hash = SIGNED % _certificate_when(e.get("signed_at")), (e.get("record_hash") or u"")[:12]
    who = {"userid": signer.get("userid") or u"",
           "fullname": signer.get("fullname") or signer.get("userid") or u"",
           "credentials": signer.get("credentials") or u"", "signature": image,
           "date": _certificate_when(e.get("signed_at")), "authorised_at": at,
           # kept for the register's and the verifier's use: the body prints no hash
           "authorised_hash": signed_hash,
           "meaning": e.get("meaning") or u"",
           "label": signing.meaning_label(e.get("meaning")),
           # the row names the signer: never refused for a staff record gone since
           "has_contact": True}
    return {"authorized": who, "signatures": rows}


def pending_certificate(pending, path=None):
    """What a certificate generated before publish prints of its authoriser:
    the signature given on Data Review (the sample's pending record), the
    signer's name and credentials as at signing, the image kept then, the
    meaning and the signing time; the Signatures table's one row says the
    hash is recorded at issue (the PDF does not exist yet). A pending record
    without its kept image asks for the certificate to be signed again; a
    kept image missing or altered raises ValueError: the print is refused
    rather than drawn without it."""
    from senaite.pfas.esig import certificate as esig_certificate
    from senaite.pfas.esig import signing
    pending = pending or {}
    sha = pending.get("image_sha256")
    if not sha:
        raise ValueError(esig_certificate.STALE)
    image = signing.image_uri(sha, path=path)
    if not image:
        raise ValueError(NO_IMAGE % u"given on Data Review")
    meaning = pending.get("meaning") or esig_certificate.meaning_for(pending.get("interim"))
    label = signing.meaning_label(meaning)
    when = _certificate_when(pending.get("at"))
    who = {"userid": pending.get("userid") or u"",
           "fullname": pending.get("fullname") or NO_STAFF_RECORD,
           "credentials": pending.get("credentials") or u"", "signature": image,
           "date": when, "authorised_at": SIGNED % when, "meaning": meaning, "label": label,
           # the signer held the authoriser right when signing
           "has_contact": True}
    row = rd.signature_row(label, who["fullname"], who["credentials"], rd.ON_FILE, when,
                           RECORDED_AT_ISSUE, meaning)
    return {"authorized": who, "signatures": [row]}


def unsigned_certificate(interim):
    """What a certificate nobody has signed prints of its authoriser: "Not
    yet signed", with no credentials, image or time; never a refusal."""
    from senaite.pfas.esig import certificate as esig_certificate
    from senaite.pfas.esig import signing
    meaning = esig_certificate.meaning_for(interim)
    label = signing.meaning_label(meaning)
    who = {"userid": u"", "fullname": NOT_YET_SIGNED, "credentials": u"", "signature": u"",
           "date": u"", "authorised_at": u"", "meaning": meaning, "label": label, "role": u"",
           "has_contact": True, "unsigned": True}
    row = rd.signature_row(label, NOT_YET_SIGNED, u"", u"", u"", u"", meaning)
    return {"authorized": who, "signatures": [row]}
