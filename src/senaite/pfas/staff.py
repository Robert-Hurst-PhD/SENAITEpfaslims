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


def _contacts_folder(portal):
    try:
        return portal["bika_setup"]["bika_labcontacts"]
    except Exception:
        return None


def _derive_initials(fullname):
    return u"".join(w[0] for w in (fullname or u"").split() if w).upper()


def _one(contact):
    try:
        full = contact.getFullname() if hasattr(contact, "getFullname") \
            else contact.Title()
    except Exception:
        full = contact.Title()
    if not full:
        return None
    initials = u""
    try:
        field = contact.getField("pfas_initials")
        if field is not None:
            initials = (field.get(contact) or u"").strip().upper()
    except Exception:
        pass
    if not initials:
        initials = _derive_initials(full)
    sig_url = u""
    try:
        sig = contact.getSignature()
        if sig and getattr(sig, "size", 0):
            sig_url = contact.absolute_url() + "/Signature"
    except Exception:
        pass
    return {
        "fullname": full,
        "initials": initials,
        "signature_url": sig_url,
        "job_title": getattr(contact, "getJobTitle", lambda: u"")() or u"",
        "placeholder": "PLACEHOLDER" in full.upper(),
        "url": contact.absolute_url(),
    }


def list_staff(portal):
    """All lab contacts as [{fullname, initials, signature_url, ...}]."""
    folder = _contacts_folder(portal)
    if folder is None:
        return []
    out = []
    for c in folder.objectValues():
        d = _one(c)
        if d:
            out.append(d)
    return sorted(out, key=lambda x: x["fullname"])


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
