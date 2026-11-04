# -*- coding: utf-8 -*-
"""The certificate's quality-system statement.

Which quality system a result was produced under: the laboratory's internal
one, or a client's Quality Assurance Project Plan when the sample's batch is
linked to a project naming a QAPP (the project's QC criteria then apply in
place of the lab's where they differ -- project_specs.py / ruleset.py).

Two editable statements in Print Settings. The internal one may use
{lab_name}, {qam_title}, {qam_id} and {qam_rev}: the laboratory's name and
the controlled document marked as the laboratory's QAM (Controlled
Documents). The QAPP one may use {qapp_title}, {qapp_id}, {qapp_rev} and
{project}. A revision is the document's ACTIVE controlled revision; when none
is on file (or no document is marked) the certificate says so rather than
printing one. Pure; Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

INTERNAL_KEY = "coa_qs_internal"
QAPP_KEY = "coa_qs_qapp"
TOKENS = ("qapp_title", "qapp_id", "qapp_rev", "project")
# what each token reads as on the editor's chips (Print Settings)
TOKEN_LABELS = (("qapp_title", u"QAPP title"), ("qapp_id", u"QAPP document ID"),
                ("qapp_rev", u"QAPP revision"), ("project", u"Project"))
INTERNAL_TOKENS = ("lab_name", "qam_title", "qam_id", "qam_rev")
INTERNAL_TOKEN_LABELS = (("lab_name", u"Laboratory name"), ("qam_title", u"QAM title"),
                         ("qam_id", u"QAM document ID"), ("qam_rev", u"QAM revision"))
NO_REV = u"revision not on file"
NO_QAM = u"QAM not on file"


def _rev(rev):
    return (u"revision %s" % rev) if rev not in (None, u"") else NO_REV


def uses_qam(text):
    return any(u"{%s}" % t in (text or u"") for t in INTERNAL_TOKENS[1:])

DEFAULT_INTERNAL = (
    u"These analyses were performed under the laboratory’s internal quality "
    u"system, using the analytical method and quality control criteria stated "
    u"for each result.")
DEFAULT_QAPP = (
    u"These analyses were performed in accordance with the Quality Assurance "
    u"Project Plan {qapp_title} (document {qapp_id}, {qapp_rev}) for project "
    u"{project}. Where that plan specifies quality control criteria, they were "
    u"applied in place of the laboratory’s internal criteria.")


def _fill(text, tokens, values):
    for token in tokens:                 # only these: braces elsewhere stay as typed
        text = text.replace(u"{%s}" % token, u"%s" % values[token])
    return text


def render(settings, qapp=None, qam=None):
    """The statement for one sample. `qapp`: None (internal quality system)
    or {"title", "id", "rev" (None when no active revision), "project"}.
    `qam`: the laboratory's QAM {"title", "id", "rev"}, or None when no
    controlled document is marked as it."""
    settings = settings or {}
    if not qapp or not qapp.get("id"):
        qam = qam if qam and qam.get("id") else None
        text = (settings.get(INTERNAL_KEY) or u"").strip()
        return _fill(text, INTERNAL_TOKENS, {
            "lab_name": settings.get("lab_name") or u"",
            "qam_title": (qam.get("title") or qam["id"]) if qam else NO_QAM,
            "qam_id": qam["id"] if qam else NO_QAM,
            "qam_rev": _rev(qam.get("rev")) if qam else NO_REV})
    text = (settings.get(QAPP_KEY) or u"").strip()
    values = {"qapp_title": qapp.get("title") or qapp.get("id"),
              "qapp_id": qapp.get("id"),
              "qapp_rev": _rev(qapp.get("rev")),
              "project": qapp.get("project") or u""}
    return _fill(text, TOKENS, values)
