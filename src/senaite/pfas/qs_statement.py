# -*- coding: utf-8 -*-
"""The certificate's quality-system statement (DECISIONS 2026-10-01).

Which quality system a result was produced under: the laboratory's internal
one, or a client's Quality Assurance Project Plan when the sample's batch is
linked to a project naming a QAPP (the project's QC criteria then apply in
place of the lab's where they differ -- project_specs.py / ruleset.py).

Two editable statements in Print Settings; the QAPP one may use
{qapp_title}, {qapp_id}, {qapp_rev} and {project}. The revision is the QAPP's
ACTIVE controlled-document revision; when none is on file the certificate
says so rather than printing one (CLAUDE.md §8). Pure; Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

INTERNAL_KEY = "coa_qs_internal"
QAPP_KEY = "coa_qs_qapp"
TOKENS = ("qapp_title", "qapp_id", "qapp_rev", "project")
NO_REV = u"revision not on file"

DEFAULT_INTERNAL = (
    u"These analyses were performed under the laboratory’s internal quality "
    u"system, using the analytical method and quality control criteria stated "
    u"for each result.")
DEFAULT_QAPP = (
    u"These analyses were performed in accordance with the Quality Assurance "
    u"Project Plan {qapp_title} (document {qapp_id}, {qapp_rev}) for project "
    u"{project}. Where that plan specifies quality control criteria, they were "
    u"applied in place of the laboratory’s internal criteria.")


def render(settings, qapp=None):
    """The statement for one sample. `qapp`: None (internal quality system)
    or {"title", "id", "rev" (None when no active revision), "project"}."""
    settings = settings or {}
    if not qapp or not qapp.get("id"):
        return (settings.get(INTERNAL_KEY) or u"").strip()
    text = (settings.get(QAPP_KEY) or u"").strip()
    values = {"qapp_title": qapp.get("title") or qapp.get("id"),
              "qapp_id": qapp.get("id"),
              "qapp_rev": (u"revision %s" % qapp["rev"]) if qapp.get("rev") not in (None, u"") else NO_REV,
              "project": qapp.get("project") or u""}
    for token in TOKENS:                 # only these: braces elsewhere stay as typed
        text = text.replace(u"{%s}" % token, u"%s" % values[token])
    return text
