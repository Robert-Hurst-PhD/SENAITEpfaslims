# -*- coding: utf-8 -*-
"""
Laboratory staff pool — one place that reads core LabContacts and exposes
{fullname, initials, signature_url} for every module that signs documents
(run builder analyst selector, data-review sign-offs/corrections, certificates).

Initials come from the LabContact's explicit `pfas_initials` (schema extender);
derived from the full name only as a fallback. The Signature image is core
LabContact's own field — upload it on the contact's edit form.

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import logging

logger = logging.getLogger("senaite.pfas.staff")


def contacts_folder(portal):
    return portal["bika_setup"]["bika_labcontacts"]


def _derive_initials(fullname):
    return u"".join(w[0] for w in (fullname or u"").split() if w).upper()


def staff_record(contact):
    from senaite.pfas.doc_fields import utext
    full = contact.getFullname() if hasattr(contact, "getFullname") \
        else utext(contact.Title())
    if not full:
        return None
    initials = u""
    field = contact.getField("pfas_initials")
    if field is not None:
        initials = (field.get(contact) or u"").strip().upper()
    if not initials:
        initials = _derive_initials(full)
    sig_url = u""
    sig = contact.getSignature()
    if sig and getattr(sig, "size", 0):
        sig_url = contact.absolute_url() + "/Signature"
    email = (contact.getEmailAddress() or u"").strip()
    return {
        "fullname": full,
        "initials": initials,
        "email": email,
        "signature_url": sig_url,
        "job_title": getattr(contact, "getJobTitle", lambda: u"")() or u"",
        "placeholder": "PLACEHOLDER" in full.upper(),
        "url": contact.absolute_url(),
        "uid": contact.UID(),
        "username": (contact.getUsername() or u"").strip(),
    }


def has_login(contact):
    """True when the contact is active and its user name is an account."""
    from bika.lims import api
    username = (contact.getUsername() or u"").strip()
    return bool(username and api.is_active(contact)
                and api.get_user(username) is not None)


def list_staff(portal, active_with_login=False):
    """All lab contacts as [{fullname, initials, email, signature_url, ...}].
    active_with_login keeps only active contacts that can sign in: the
    pickers use it. A lookup by initials does not, so a document signed by
    someone who has since left keeps its signature."""
    folder = contacts_folder(portal)
    out = []
    for c in folder.objectValues():
        if active_with_login and not has_login(c):
            continue
        d = staff_record(c)
        if d:
            out.append(d)
    return sorted(out, key=lambda x: x["fullname"])


def initials_holder(portal, contact_uid, initials):
    """The full name of another contact, active or not, holding these
    initials, or None. Signatures are found by initials (find_by_initials),
    so an old record keeps naming one person: initials are never reused."""
    ini = (initials or u"").strip().upper()
    for c in contacts_folder(portal).objectValues():
        if c.UID() == contact_uid:
            continue
        d = staff_record(c)
        if d and d["initials"] == ini:
            return d["fullname"]
    return None


def find_by_initials(portal, initials):
    """Staff record whose initials match (case-insensitive), or None —
    used to append the person's signature image to filled-out documents."""
    if not initials:
        return None
    ini = initials.strip().upper()
    for d in list_staff(portal):
        if d["initials"] == ini:
            return d
    return None
