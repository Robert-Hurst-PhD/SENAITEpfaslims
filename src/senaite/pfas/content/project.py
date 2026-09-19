# -*- coding: utf-8 -*-
"""Project content type — a client's project, the entity that carries a QAPP.

The lab's quality system is a document hierarchy (QAM, SOPs, job aids,
supplemental). A client's project-specific QAPP is the SAME kind of
controlled document (see senaite.pfas.browser.sop_documents.DOC_TYPES), just
client-owned, and it overrides the lab's internal system for that project.

Project is the entity that carries that override: it names the owning Client
and, optionally, the QAPP document that governs it. The link is one
direction only — the Project points at the QAPP document id; the document
itself does not know which project(s) reference it (see DOC_TYPES's comment).

A Batch is linked to a Project by annotation, not by a schema field — Batch
is a core SENAITE type and this add-on never forks core. See
senaite.pfas.project_ref.

Python 2.7 compatible.
"""
from plone.dexterity.content import Item
from plone.supermodel import model
from zope import schema
from zope.interface import implementer

from bika.lims.interfaces import IDeactivable
from senaite.pfas import messageFactory as _

STATUS_ACTIVE = u"active"
STATUS_CLOSED = u"closed"


class IPFASProject(model.Schema):
    """A client project. `title` (from plone.dublincore) carries the project
    name."""

    client_uid = schema.TextLine(
        title=_(u"Client"),
        description=_(u"UID of the owning SENAITE Client."),
        required=True,
    )
    project_code = schema.TextLine(
        title=_(u"Project Code"),
        description=_(u"The lab's code for this project."),
        required=True,
    )
    qapp_document_id = schema.TextLine(
        title=_(u"QAPP Document"),
        description=_(u"Id of the controlled document (type QAPP) governing "
                       u"this project, e.g. \"QAPP-001\". Optional — a "
                       u"project with none falls back to the lab's internal "
                       u"quality system."),
        required=False,
    )
    start_date = schema.Date(
        title=_(u"Start Date"),
        required=False,
    )
    end_date = schema.Date(
        title=_(u"End Date"),
        required=False,
    )
    status = schema.Choice(
        title=_(u"Status"),
        values=[STATUS_ACTIVE, STATUS_CLOSED],
        default=STATUS_ACTIVE,
        required=False,
    )
    notes = schema.Text(
        title=_(u"Notes"),
        required=False,
    )


@implementer(IPFASProject, IDeactivable)
class PFASProject(Item):
    """Client project — first-class SENAITE content, indexed in setup catalog."""
