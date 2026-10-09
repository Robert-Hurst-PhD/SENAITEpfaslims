# -*- coding: utf-8 -*-
"""The laboratory and signatory fields of a designed record:
the extraction log, the QC Review report and the batch logbooks.

    signed_fields(design, people, preview=False) -> {field: value}

`people`: {"preparer": (who, date), "reviewer": (who, date)} -- `who` as the
record names the person. The Director is the one named in Site Settings.

A person is looked up as a user only when the record names them by user id;
any other name prints as written and has no signature -- a name is never
matched to an account. A signature prints only for a user holding that sign
right (Lab Staff). When the design PLACES a role's signature and it cannot be
given -- not a user, no sign right, no signature on file -- the document is
refused outside a preview (sign rights are enforced
on designed documents). A design that places no signature is not affected.
Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

from bika.lims import api
from zope.globalrequest import getRequest

from senaite.pfas import coa_document as cd
from senaite.pfas import document_templates as dt


class SignatoryError(ValueError):
    """A placed signature that its signer may not give."""


def _placed(design):
    return set(dt.base_key(f.get("name")) for page in (design or {}).get("schemas") or []
               for f in page or [] if f.get("type") == "image")


def _lab():
    from senaite.pfas.browser.coa_document import _logo_uri
    from senaite.pfas.browser.coa_sections import PFASCoASectionsView
    view = PFASCoASectionsView(api.get_portal(), getRequest())
    s = view.settings()
    return {"lab_name": s.get("lab_name") or u"", "lab_address": s.get("lab_address") or u"",
            "lab_phone": s.get("lab_phone") or u"", "lab_email": s.get("lab_email") or u"",
            "lab_accreditation": s.get("accreditation") or u"", "lab_logo": _logo_uri(s)}


def _person(role, who, date, placed, problems):
    from senaite.pfas.browser import staff
    who = (u"%s" % (who or u"")).strip()
    user = api.get_user(who) if who else None
    if user is None:
        if role + "_signature" in placed:
            problems.append(u"%s (%s) is not a user, so no signature can be placed"
                            % (who or u"nobody named", role))
        return cd.signatory({"fullname": who, "date": date})
    info = staff.staff_info(who)
    signature = info["signature"] if role in info["sign_as"] else u""
    if role + "_signature" in placed:
        if role not in info["sign_as"]:
            problems.append(u"%s may not sign as %s" % (info["fullname"], role))
        elif not signature:
            problems.append(u"%s has no signature on file" % info["fullname"])
    return cd.signatory({"fullname": info["fullname"], "jobtitle": info["jobtitle"],
                         "credentials": info["credentials"], "date": date}, signature)


def signed_fields(design, people, preview=False):
    from senaite.pfas.browser import staff
    placed = _placed(design)
    problems = []
    out = _lab()
    for role in ("preparer", "reviewer"):
        who, date = (people or {}).get(role) or (u"", u"")
        p = _person(role, who, u"%s" % (date or u""), placed, problems)
        for k in ("name", "title", "credentials", "date", "signature"):
            out["%s_%s" % (role, k)] = p.get(k) or u""
    director = staff.director_userid()
    if director:
        p = _person("director", director, u"", placed, problems)
    else:
        p = cd.signatory(None)
        if "director_signature" in placed:
            problems.append(u"no Laboratory Director is set (Site Settings)")
    for k in ("name", "title", "credentials", "signature"):
        out["director_%s" % k] = p.get(k) or u""
    if problems and not preview:
        raise SignatoryError(u"signatories: " + u"; ".join(problems) + u" (Lab Staff)")
    return out
