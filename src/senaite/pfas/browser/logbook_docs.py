# -*- coding: utf-8 -*-
"""
Controlled-document (PDF) layer for logbooks.

Additive to the existing logbook DEFINITION machinery (PrepLogbookDef form
schemas): this attaches a controlled PDF document to each logbook family
(by slug) with the SAME revision + mandatory sign-off + delete->archive
semantics as SOPs, without touching the dynamic-form revision system.

Storage (portal annotations, keyed by logbook slug) + files on disk:
  senaite.pfas.logbook.{slug}.pdf_revisions  -> [rev dict, ...]
  senaite.pfas.logbook.{slug}.pdf_signoffs   -> {uid: {rev_num, ...}}
  senaite.pfas.logbook.pdf_archived          -> [slug, ...]  (deleted logbooks)
  /data/logbook_docs/{slug}/rev_N.pdf

PDF-only (fixed/immutable controlled documents). Python 2.7 compatible.
"""
from __future__ import absolute_import

import json
import os
import re
from datetime import date, datetime

from zope.annotation.interfaces import IAnnotations

LOGBOOK_DOC_DIR = os.environ.get("PFAS_LOGBOOK_DOC_DIR", "/data/logbook_docs")

_REV_KEY  = u"senaite.pfas.logbook.{slug}.pdf_revisions"
_SIG_KEY  = u"senaite.pfas.logbook.{slug}.pdf_signoffs"
_ARCH_KEY = u"senaite.pfas.logbook.pdf_archived"


# ── revisions ───────────────────────────────────────────────────────────────

def get_doc_revisions(portal, slug):
    raw = IAnnotations(portal).get(_REV_KEY.format(slug=slug))
    return json.loads(raw) if raw else []


def save_doc_revisions(portal, slug, data):
    IAnnotations(portal)[_REV_KEY.format(slug=slug)] = json.dumps(data)


def get_doc_signoffs(portal, slug):
    raw = IAnnotations(portal).get(_SIG_KEY.format(slug=slug))
    return json.loads(raw) if raw else {}


def save_doc_signoffs(portal, slug, data):
    IAnnotations(portal)[_SIG_KEY.format(slug=slug)] = json.dumps(data)


def get_active_doc_rev(portal, slug):
    return next((r for r in get_doc_revisions(portal, slug)
                 if r.get("status") == "active"), None)


# ── operations ──────────────────────────────────────────────────────────────

def is_pdf(filename):
    return os.path.splitext(filename or "")[1].lower() == ".pdf"


def upload_doc(portal, slug, upload, notes, uid):
    """Write an uploaded PDF as a new DRAFT revision. Returns (ok, msg)."""
    fname = getattr(upload, "filename", "") or ""
    if not fname:
        return (False, "no_file")
    if not is_pdf(fname):
        return (False, "not_pdf")

    revs = get_doc_revisions(portal, slug)
    rev_num = len(revs) + 1              # numbering iterates, never reused

    sop_dir = os.path.join(LOGBOOK_DOC_DIR, slug)
    if not os.path.isdir(sop_dir):
        os.makedirs(sop_dir)
    safe = re.sub(r"[^\w\.\-]", "_", os.path.basename(fname)) or "log.pdf"
    dest = os.path.join(sop_dir, "rev_{0}.pdf".format(rev_num))
    tmp = dest + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(upload.read())
    os.rename(tmp, dest)

    revs.append({
        "rev_num":      rev_num,
        "filename":     safe,
        "filepath":     dest,
        "content_type": "application/pdf",
        "uploaded_by":  uid,
        "uploaded_at":  date.today().isoformat(),
        "status":       "draft",
        "activated_by": None,
        "activated_at": None,
        "release_notes": notes or "",
    })
    save_doc_revisions(portal, slug, revs)
    return (True, "uploaded")


def activate_doc(portal, slug, rev_num, uid):
    """Activate a draft revision; supersede the current active one."""
    revs = get_doc_revisions(portal, slug)
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    found = False
    for r in revs:
        if r.get("status") == "active":
            r["status"] = "superseded"
        if r["rev_num"] == rev_num:
            r["status"] = "active"
            r["activated_by"] = uid
            r["activated_at"] = now
            found = True
    if not found:
        return (False, "rev_not_found")
    save_doc_revisions(portal, slug, revs)
    return (True, "activated")


def sign_doc(portal, slug, uid, fullname):
    """Record the current user's sign-off on the ACTIVE revision."""
    active = get_active_doc_rev(portal, slug)
    if not active:
        return (False, "no_active_rev")
    sigs = get_doc_signoffs(portal, slug)
    sigs[uid] = {
        "rev_num":   active["rev_num"],
        "signed_by": fullname,
        "signed_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    save_doc_signoffs(portal, slug, sigs)
    return (True, "signed")


# ── delete -> archive ───────────────────────────────────────────────────────

def get_archived_slugs(portal):
    raw = IAnnotations(portal).get(_ARCH_KEY)
    return set(json.loads(raw)) if raw else set()


def _save_archived_slugs(portal, slugs):
    IAnnotations(portal)[_ARCH_KEY] = json.dumps(sorted(slugs))


def archive_logbook(portal, slug):
    s = get_archived_slugs(portal)
    s.add(slug)
    _save_archived_slugs(portal, s)


def restore_logbook(portal, slug):
    s = get_archived_slugs(portal)
    s.discard(slug)
    _save_archived_slugs(portal, s)


# ── template summary ────────────────────────────────────────────────────────

def doc_info(portal, slug, uid):
    """Per-logbook controlled-document summary for the admin UI."""
    revs = get_doc_revisions(portal, slug)
    sigs = get_doc_signoffs(portal, slug)
    active = None
    drafts = []
    for r in revs:
        if r.get("status") == "active":
            active = r
        elif r.get("status") == "draft":
            drafts.append(r)
    if active:
        rev_num = active["rev_num"]
        signers = [v for v in sigs.values() if v.get("rev_num") == rev_num]
        user_signed = uid in sigs and sigs[uid].get("rev_num") == rev_num
    else:
        signers = []
        user_signed = False
    return {
        "active_rev":   active,
        "draft_revs":   drafts,
        "all_revs":     revs,
        "signoffs":     sigs,
        "signer_count": len(signers),
        "user_signed":  user_signed,
        "has_doc":      bool(revs),
    }


def resolve_download(portal, slug, rev_num):
    """Return (filepath, filename) for a revision, or (None, None)."""
    for r in get_doc_revisions(portal, slug):
        if r["rev_num"] == rev_num:
            return (r.get("filepath"), r.get("filename"))
    return (None, None)
