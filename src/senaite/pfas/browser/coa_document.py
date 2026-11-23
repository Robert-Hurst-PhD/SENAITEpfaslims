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
layout. The authoriser prints from the signature given on Data Review when
the certificate is generated, from its ledger row on a reprint of an issued
revision, and as "Not yet signed" when nobody signed; an interim revision
prints INTERIM on every page and is refused from a design without the mark
(_authoriser). A client who takes black-and-white certificates gets the same
compiled layout with every colour ink or paper (document_templates.monochrome).
Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import logging

from bika.lims import api
from zope.globalrequest import getRequest

from senaite.pfas import coa_document as cd
from senaite.pfas import document_templates as dt
from senaite.pfas import pdf_renderer
from senaite.pfas import print_doc

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
        lines.append(u"%s (%s, %s)" % (content, who, print_doc.lab_or(
            when, when[:16].replace(u"T", u" "))) if who or when else content)
    return u"\n".join(reversed(lines))


PREVIEW_MARK = u"PREVIEW, not a certificate"


def preview_mark(issue_mark):
    """The issue mark a preview prints: PREVIEW_MARK, before INTERIM when
    the revision previewed is interim."""
    return u" \u00b7 ".join(m for m in (PREVIEW_MARK, issue_mark or u"") if m)


SITE_LOGO = u"@@site-logo"


def _logo_data_uri(raw):
    from senaite.pfas import lab_identity
    if raw and len(raw) > lab_identity.LOGO_MAX_BYTES:
        logger.warning("logo is %d bytes, over %d: not placed on designed documents",
                       len(raw), lab_identity.LOGO_MAX_BYTES)
        return u""
    return cd.image_data_uri(raw) or u""


def _logo_uri(settings):
    """The certificate's logo as a data URI. SENAITE's site logo -- the one
    the settings' logo_sha names when they carry it (an issued revision keeps
    its logo), else the live one -- or only this site's own files: a
    portal-relative path, or a URL on this portal; the server never fetches
    an outside address. The mime type comes from the image's own bytes."""
    url = (settings.get("logo_url") or u"").strip()
    if not url:
        return u""
    from senaite.pfas import lab_identity
    portal = api.get_portal()
    if url == SITE_LOGO:
        sha = (settings.get("logo_sha") or u"").strip()
        if sha:
            return _logo_data_uri(lab_identity.logo_for_sha(portal, sha))
        found = lab_identity.logo_bytes(portal)
        return _logo_data_uri(found[1]) if found else u""
    raw = lab_identity.legacy_logo_bytes(portal, url)
    return _logo_data_uri(raw)


def _signatories(signatories, preview):
    """The signatories for the designed certificate, one block per role,
    each with title, credentials and signature from their Lab Contact
    (browser/staff.py). Outside a preview, the preparer and reviewer must
    hold the right to sign as that role (designed documents only); the
    Director is whoever the Laboratory page names, and must have a signature
    image on file (it prints on every certificate). When the reviewer is the
    Director, "reviewer_is_director" makes one "Reviewed and authorized by"
    block (coa_document.signers)."""
    from senaite.pfas.browser import staff
    problems, out = [], {}
    roles = (("preparer", signatories.get("prepared") or []),
             ("reviewer", signatories.get("verified") or []))
    first_reviewer = None
    for role, people in roles:
        first = None
        for p in people:
            info = staff.staff_info(p.get("userid"))
            if role not in info["sign_as"]:
                problems.append(u"%s may not sign as %s" % (cd.staff_name(info, p.get("userid")), role))
            if first is None:
                first = dict(p, credentials=info["credentials"],
                             jobtitle=p.get("jobtitle") or info["jobtitle"])
                out[role] = cd.signatory(first, info["signature"])
                if role == "reviewer":
                    first_reviewer = p.get("userid")
    director = staff.director_userid()
    if director:
        info = staff.staff_info(director)
        # staff_info falls back to the account id: never printed
        name = cd.staff_name(info, director)
        out["director"] = cd.signatory({"fullname": name, "jobtitle": info["jobtitle"],
                                        "credentials": info["credentials"]}, info["signature"])
        out["reviewer_is_director"] = bool(first_reviewer) and first_reviewer == director
        if not info["signature"]:
            # the director's image prints on every certificate: none on file
            # refuses the issue as a designed record refuses it (doc_people)
            problems.append(u"%s has no signature on file" % name)
    else:
        problems.append(u"no Laboratory Director is set: name one on Laboratory")
    if problems and not preview:
        raise ValueError(u"signatories: " + u"; ".join(problems) + u" on People & Roles")
    return out


def _authoriser(sample, report_id, preview):
    """(the authorizing person, the Signatures table's rows, interim) for
    the revision printed, report_id on the primary sample's register. An
    issued revision (a reprint) prints its ledger row as signed
    (esig.print_rows.certificate), whatever the signer's right or image is
    now. A certificate generated before issue prints the signature given on
    Data Review (the sample's pending signature): the signer as at signing,
    the image kept then and the signing time. Nobody signed: "Not yet
    signed", never a refusal. A preview reads no register entry. Interim
    or final: the register entry once issued, else the pending signature,
    the one Generate records on the stored certificate."""
    from senaite.pfas.browser import staff
    from senaite.pfas.browser.controlled_publications import get_publication_log, pending_signature
    from senaite.pfas.esig import print_rows
    entry = None
    if not preview:
        entry = next((e for e in get_publication_log(sample) if e.get("report_id") == report_id), None)
    pending = pending_signature(sample)
    interim = cd.is_interim(entry, pending)
    if entry is not None:
        # an issued revision never takes a signature given after it
        signed = print_rows.certificate(entry) or print_rows.unsigned_certificate(interim)
    elif pending and pending.get("userid"):
        signed = print_rows.pending_certificate(pending)
    else:
        signed = print_rows.unsigned_certificate(interim)
    info = dict(signed["authorized"])
    if info.get("userid"):
        # the role beside the name is the one People & Roles gives today
        now = staff.staff_info(info["userid"])
        info["jobtitle"] = now.get("jobtitle") or u""
        info["role"] = cd.authorizing_role(info["jobtitle"], info["userid"] == staff.director_userid(),
                                           now.get("sign_as"))
    return info, signed["signatures"], interim


def _places_issue_mark(layout):
    """True when the layout places the issue_mark field marked "on every
    page": an interim certificate says INTERIM on each of its pages."""
    base = (layout or {}).get("basePdf")
    fields = [f for page in (layout or {}).get("schemas") or [] for f in page or []]
    fields += list(base.get("staticSchema") or []) if isinstance(base, dict) else []
    return any(dt.base_key(f.get("name")) == "issue_mark" and f.get(dt.EVERY_PAGE)
               for f in fields)


def _interpretation(sample):
    ris = []
    try:
        for ri in sample.getResultsInterpretationDepts() or []:
            dept = api.get_object(ri.get("uid"), default=None) if ri.get("uid") else None
            ris.append({"title": api.safe_unicode(api.get_title(dept)) if dept is not None else u"",
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
    accred = att.accreditation_disclosure(collection)
    out = []
    samples = [api.get_object(m) for m in collection]
    # the authoriser and the interim mark of the revision printed, read on
    # the primary sample (the one its register entry and pending signature
    # are kept on)
    authorized, rows, interim = _authoriser(samples[0], meta.get("report_id"), preview)
    if interim and not preview and not _places_issue_mark(layout):
        # an interim certificate never goes out without INTERIM on each page
        raise ValueError(cd.NO_ISSUE_MARK)
    signatories = dict(signatories, authorized=authorized, interim=interim,
                       issue_mark=cd.issue_mark(interim))
    missing = cd.unsupported(signatories, [a for s in samples for a in _report_attachments(s)])
    if missing:
        raise ValueError(u"the standard certificate would print %s, which the designed layout "
                         u"cannot show yet" % u" and ".join(missing))
    if not preview and not (settings.get("lab_address") or u"").strip():
        # ISO/IEC 17025 7.8.2.1 b): the laboratory's address is on every
        # report; the accreditation statement is optional
        from senaite.pfas.print_settings import get_print_settings
        from senaite.pfas.report_templates import lab_address_problem
        snap, rev = sections.template_revision()
        raise ValueError(lab_address_problem(snap, rev, get_print_settings(portal))
                         or u"the laboratory address is not set (Laboratory)")
    extra = {"lab_address": settings.get("lab_address"), "lab_phone": settings.get("lab_phone"),
             "lab_email": settings.get("lab_email"), "lab_logo": _logo_uri(settings)}
    extra.update(_signatories(signatories, preview))
    extra["signatures"] = rows
    # the client of the primary sample may take its certificates in black
    # and white: the same layout, recoloured once compiled
    from senaite.pfas.browser.coa_sections import certificate_mono
    mono = certificate_mono(collection)
    for sample in samples:
        smp = sections._sample(sample)
        data = cd.data(lab, meta, smp, signatories, accred, _remarks(sample),
                       _interpretation(sample), extra, preview=preview)
        if preview:
            # a preview says so on every page: above the title, where an
            # interim certificate says INTERIM, and in a stamp a layout
            # issued earlier places
            data["stamp"] = u"%s \u00b7 %s" % (PREVIEW_MARK, data["stamp"])
            data["issue_mark"] = preview_mark(data.get("issue_mark"))
        template, inputs = dt.compile_document("coa", layout, data)
        out.append(dt.monochrome_document("coa", template, inputs) if mono else (template, inputs))
    return out


def render(collection, layout, snapshot=None, rev=None, request=None, preview=False):
    if not collection:
        raise ValueError("no samples on the certificate")
    docs = documents(collection, layout, snapshot, rev, request, preview)
    return pdf_renderer.render_documents(docs)
