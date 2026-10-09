# -*- coding: utf-8 -*-
"""Render a designed certificate.

    documents(collection, layout, snapshot=None, rev=None) -> [(template, input)]
    render(collection, layout, snapshot=None, rev=None)    -> PDF bytes

Each sample's data comes from the certificate's own assembly -- the views the
HTML certificate draws from (PFASCoASectionsView, PFASCoAAttestationView) --
flattened by senaite.pfas.coa_document and compiled per document by
document_templates.compile_document, then rendered by the pfas-render
container. Every failure raises (ValueError for the data, RenderError for the
renderer): a controlled certificate is refused, never printed in another
layout. Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import logging

from bika.lims import api
from zope.globalrequest import getRequest

from senaite.pfas import coa_document as cd
from senaite.pfas import document_templates as dt
from senaite.pfas import pdf_renderer

logger = logging.getLogger("senaite.pfas.coa_document")


def _remarks(sample):
    """The sample's remarks, oldest first, as the certificate's remarks
    section lists them."""
    try:
        history = sample.getRemarks() or []
    except Exception:                                       # noqa: BLE001
        return u""
    lines = []
    for rec in history:
        content = getattr(rec, "content", None)
        if content is None:
            lines.append(u"%s" % rec)
            continue
        who = getattr(rec, "user_name", u"") or getattr(rec, "user_id", u"")
        when = u"%s" % (getattr(rec, "created", u"") or u"")
        content = cd._plain(u"%s" % content)        # remarks are stored as HTML
        lines.append(u"%s (%s, %s)" % (content, who, when[:16].replace(u"T", u" "))
                     if who or when else content)
    return u"\n".join(reversed(lines))


PREVIEW_MARK = u"PREVIEW, not a certificate"
LOGO_MAX_BYTES = 1024 * 1024


def _logo_uri(settings):
    """The Print Settings logo as a data URI. Only this site's own files: a
    portal-relative path, or a URL on this portal -- the server never fetches
    an outside address."""
    url = (settings.get("logo_url") or u"").strip()
    if not url:
        return u""
    portal = api.get_portal()
    base = portal.absolute_url()
    if url.startswith(base):
        url = url[len(base):]
    elif "://" in url or url.startswith("//"):
        logger.warning("logo %s is not on this site: not placed on designed documents", url)
        return u""
    path = str(url.split("?")[0].lstrip("/"))
    try:
        obj = portal.unrestrictedTraverse(path)
    except Exception:                                       # noqa: BLE001
        logger.warning("logo %s not found", url)
        return u""
    from senaite.pfas.browser.staff import image_bytes
    raw = None
    for candidate in (obj, getattr(obj, "image", None)):
        raw = image_bytes(candidate) if candidate is not None else None
        if raw:
            break
    if raw and len(raw) > LOGO_MAX_BYTES:
        # every document of a certificate carries it: a big logo times many
        # samples would pass the renderer's request limit at publish
        logger.warning("logo is %d bytes, over %d: not placed on designed documents", len(raw), LOGO_MAX_BYTES)
        return u""
    return cd.image_data_uri(raw) or u""


def _signatories(signatories, preview):
    """The three signatories for the designed certificate, each with title,
    credentials and signature from their Lab Contact (browser/staff.py).
    Outside a preview, each must hold the right to sign as that role (lab
    decision 2026-10-05: designed documents only), and a Director must be
    named in Site Settings."""
    from senaite.pfas.browser import staff
    problems, out = [], {}
    roles = (("preparer", signatories.get("prepared") or []),
             ("reviewer", signatories.get("verified") or []))
    for role, people in roles:
        first = None
        for p in people:
            info = staff.staff_info(p.get("userid"))
            if role not in info["sign_as"]:
                problems.append(u"%s may not sign as %s" % (info["fullname"] or p.get("userid"), role))
            if first is None:
                first = dict(p, credentials=info["credentials"],
                             jobtitle=p.get("jobtitle") or info["jobtitle"])
                out[role] = cd.signatory(first, info["signature"])
    director = staff.director_userid()
    if director:
        info = staff.staff_info(director)
        out["director"] = cd.signatory({"fullname": info["fullname"], "jobtitle": info["jobtitle"],
                                        "credentials": info["credentials"]}, info["signature"])
        if "director" not in info["sign_as"]:
            problems.append(u"%s may not sign as director" % info["fullname"])
    else:
        problems.append(u"no Laboratory Director is set (Site Settings)")
    if problems and not preview:
        raise ValueError(u"signatories: " + u"; ".join(problems) + u" (Lab Staff)")
    return out


def _interpretation(sample):
    ris = []
    try:
        for ri in sample.getResultsInterpretationDepts() or []:
            dept = api.get_object(ri.get("uid"), default=None) if ri.get("uid") else None
            ris.append({"title": api.get_title(dept) if dept is not None else u"",
                        "richtext": ri.get("richtext") or u""})
    except Exception:                                       # noqa: BLE001
        logger.warning("results interpretation of %s unreadable", api.get_id(sample), exc_info=True)
        raise
    return cd.interpretation(ris)


def _report_attachments(sample):
    """Attachments impress prints on the certificate (report option "r")."""
    found = list(sample.getAttachment() or [])
    for an in sample.getAnalyses(full_objects=True):
        found += list(an.getAttachment() or [])
    return [u"%s: %s" % (api.get_id(sample), a.getAttachmentFile().filename or api.get_id(a))
            for a in found if a.getReportOption() == "r"]


def documents(collection, layout, snapshot=None, rev=None, request=None, preview=False):
    """[(compiled template, input)] -- one per sample, in collection order.
    `snapshot`/`rev` draw a preview from a draft, as the HTML preview does."""
    from senaite.pfas.browser.coa_attestation import PFASCoAAttestationView
    from senaite.pfas.browser.coa_sections import PFASCoASectionsView
    portal = api.get_portal()
    request = request or getRequest()
    sections = PFASCoASectionsView(portal, request)
    sections.collection = list(collection)
    if snapshot is not None:
        sections.snapshot_override, sections.snapshot_rev = snapshot, rev
    att = PFASCoAAttestationView(portal, request)
    att.collection = list(collection)
    lab, meta = sections.lab(), sections.doc_meta()
    settings = sections.settings()
    signatories = att.resolve_signatories(collection)
    quals = att.qc_qualifications(collection)
    accred = att.accreditation_disclosure(collection)
    out = []
    samples = [api.get_object(m) for m in collection]
    missing = cd.unsupported(signatories, [a for s in samples for a in _report_attachments(s)])
    if missing:
        raise ValueError(u"the standard certificate would print %s, which the designed layout "
                         u"cannot show yet" % u" and ".join(missing))
    extra = {"lab_address": settings.get("lab_address"), "lab_phone": settings.get("lab_phone"),
             "lab_email": settings.get("lab_email"), "lab_logo": _logo_uri(settings)}
    extra.update(_signatories(signatories, preview))
    for sample in samples:
        smp = sections._sample(sample)
        data = cd.data(lab, meta, smp, signatories, quals, accred, _remarks(sample),
                       _interpretation(sample), extra, preview=preview)
        if preview:
            data["stamp"] = u"%s \u00b7 %s" % (PREVIEW_MARK, data["stamp"])
        out.append(dt.compile_document("coa", layout, data))
    return out


def render(collection, layout, snapshot=None, rev=None, request=None, preview=False):
    if not collection:
        raise ValueError("no samples on the certificate")
    docs = documents(collection, layout, snapshot, rev, request, preview)
    return pdf_renderer.render_documents(docs)
