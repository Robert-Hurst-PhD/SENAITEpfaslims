# -*- coding: utf-8 -*-
"""Lab staff as documents need them (signatures live on SENAITE's Lab Contact; linked to the user).

    contact_for(userid)      -> the user's linked LabContact, or None
    staff_info(userid)       -> {"userid", "fullname", "jobtitle", "credentials",
                                 "sign_as": [...], "signature": data URI or ""}
    director_userid()        -> the Laboratory Supervisor's user name

The person's name and job title are core LabContact fields; the signature is
core's LabContact Signature image (what SENAITE's own reports print).
Credentials and "signs as" (preparer / reviewer) are PFAS settings kept in
an annotation on the same Lab Contact. The Laboratory Director is one person,
chosen on the Laboratory page only. Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import logging

from bika.lims import api
from zope.annotation.interfaces import IAnnotations

from senaite.pfas import coa_document

logger = logging.getLogger("senaite.pfas.staff")

STAFF_KEY = "senaite.pfas.staff"            # on a LabContact: {"credentials", "sign_as"}
DIRECTOR_KEY = "senaite.pfas.lab_director"  # on the portal: the director's user id
SIGN_ROLES = (("preparer", "Preparer"), ("reviewer", "Reviewer"))
# The "Signs as" control: each choice and the roles it writes
SIGNS_AS = (("none", "None", []), ("preparer", "Preparer", ["preparer"]),
            ("reviewer", "Reviewer", ["reviewer"]), ("both", "Both", ["preparer", "reviewer"]))


def signs_as_key(sign_as):
    """The "Signs as" choice a stored list reads as."""
    roles = set(clean_sign_as(sign_as))
    for key, _label, wrote in SIGNS_AS:
        if set(wrote) == roles:
            return key
    return "none"


def sign_as_for(key):
    """The roles one "Signs as" choice writes, or None for an unknown one."""
    for k, _label, wrote in SIGNS_AS:
        if k == key:
            return list(wrote)
    return None


def contact_for(userid):
    if not userid:
        return None
    try:
        user = api.get_user(userid)
        if user is None:
            return None
        return api.get_user_contact(user, ["LabContact"])
    except Exception:                                       # noqa: BLE001
        logger.warning("no contact for %s", userid, exc_info=True)
        return None


def staff_settings(contact):
    if contact is None:
        return {"credentials": "", "sign_as": []}
    raw = IAnnotations(contact).get(STAFF_KEY) or {}
    return {"credentials": raw.get("credentials") or "", "sign_as": list(raw.get("sign_as") or [])}


def image_bytes(value):
    """Bytes of an image field value (OFS Image, blob wrapper), or None."""
    if not value:
        return None
    for get in (lambda v: v.data, lambda v: v.getBlob().open().read()):
        try:
            data = get(value)
            if data and not isinstance(data, bytes):
                data = bytes(data) if not hasattr(data, "next") else str(data)
            if data:
                return data
        except Exception:                                   # noqa: BLE001
            continue
    try:
        data = str(value)
        return data or None
    except Exception:                                       # noqa: BLE001
        return None


def signature_uri(contact):
    if contact is None:
        return ""
    try:
        return coa_document.image_data_uri(image_bytes(contact.getSignature())) or ""
    except Exception:                                       # noqa: BLE001
        logger.warning("signature of %s unreadable", api.get_id(contact), exc_info=True)
        return ""


def staff_info(userid):
    contact = contact_for(userid)
    settings = staff_settings(contact)
    fullname, jobtitle = userid or "", ""
    if contact is not None:
        fullname = contact.getFullname() or fullname
        jobtitle = getattr(contact, "getJobTitle", lambda: "")() or ""
    else:
        try:
            user = api.get_user(userid)
            fullname = (user.getProperty("fullname") if user else "") or fullname
        except Exception:                                   # noqa: BLE001
            pass
    return {"userid": userid or "", "fullname": fullname, "jobtitle": jobtitle,
            "credentials": settings["credentials"], "sign_as": settings["sign_as"],
            "signature": signature_uri(contact), "has_contact": contact is not None}


def entry_status(userid):
    """entry_rights status for a user: Lab Contact, initials, signature."""
    from senaite.pfas import entry_rights
    from senaite.pfas.staff import staff_record
    contact = contact_for(userid)
    if contact is None:
        return entry_rights.NO_CONTACT
    row = staff_record(contact) or {}
    return entry_rights.status(True, row.get("initials"), bool(signature_uri(contact)))


def may_enter(userid=None):
    """The current (or named) user may enter data and review."""
    from senaite.pfas import entry_rights
    if userid is None:
        try:
            user = api.get_current_user()
            userid = user.getId() if user is not None else None
        except Exception:                                   # noqa: BLE001
            userid = None
    return bool(userid) and entry_status(userid) == entry_rights.OK


SIGNATURE_MAX_BYTES = 512 * 1024


def check_signature(raw):
    """(bytes, None) for a PNG or JPEG under the size cap, else (None, why).
    SVG and other formats are refused (an SVG can carry script)."""
    if not raw:
        return None, u"Choose a picture of the signature."
    if len(raw) > SIGNATURE_MAX_BYTES:
        return None, u"The picture is larger than 512 KB."
    if not coa_document.image_data_uri(raw):
        return None, u"The signature must be a PNG or JPEG picture."
    return raw, None


def clean_sign_as(values):
    allowed = [k for k, _t in SIGN_ROLES]
    return [k for k in allowed if k in (values or [])]


def fingerprint(raw):
    import hashlib
    return hashlib.sha256(raw).hexdigest()[:16] if raw else u""


def director_userid():
    from senaite.pfas import lab_identity
    return lab_identity.director_userid(api.get_portal())
