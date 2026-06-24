# -*- coding: utf-8 -*-
"""PrepLogbookDef — a versioned preparation logbook definition.

Each instance represents ONE REVISION of a named preparation procedure.
Revisions sharing the same `logbook_slug` form a "family"; the one with
status="active" is current.  Issuing a new revision archives the current
one and creates a successor object.

Python 2.7 compatible.
"""
from plone.dexterity.content import Item
from plone.supermodel import model
from zope import schema
from zope.interface import implementer

from senaite.pfas import messageFactory as _


class IPrepLogbookDef(model.Schema):
    """Versioned preparation logbook definition."""

    logbook_slug = schema.TextLine(
        title=_(u"Logbook Slug"),
        description=_(u"Machine-readable family identifier, auto-set from title."),
        required=False,
    )
    revision = schema.Int(
        title=_(u"Revision Number"),
        default=1,
        required=True,
    )
    status = schema.Choice(
        title=_(u"Status"),
        values=[u"draft", u"active", u"archived"],
        default=u"draft",
        required=True,
    )
    standard_type = schema.Choice(
        title=_(u"Standard Type"),
        values=[
            u"Calibration Standard",
            u"QC Check Standard",
            u"Surrogate Mix",
            u"Internal Standard Mix",
            u"Matrix Spike",
            u"Solvent / Reagent",
            u"Other",
        ],
        required=False,
    )
    description = schema.Text(
        title=_(u"Description"),
        description=_(u"What this logbook is used to prepare."),
        required=False,
    )
    procedure = schema.Text(
        title=_(u"Procedure"),
        description=_(u"Step-by-step preparation instructions."),
        required=False,
    )
    default_expiry_days = schema.Int(
        title=_(u"Default Expiry (days from preparation)"),
        default=365,
        required=False,
    )
    analyte_template_json = schema.Text(
        title=_(u"Analyte Template (JSON)"),
        description=_(u"Default analyte concentrations: [{analyte, concentration, unit}, ...]"),
        required=False,
    )
    archived_date = schema.Date(
        title=_(u"Archived Date"),
        required=False,
    )
    notes = schema.Text(
        title=_(u"Notes"),
        required=False,
    )
    method_slug = schema.TextLine(
        title=_(u"Method Slug"),
        description=_(u"Which method owns this template (e.g. fda-32-pfas)."),
        required=False,
    )
    logbook_code = schema.TextLine(
        title=_(u"Logbook Code"),
        description=_(u"FM-ENV code or other form code (e.g. FM-ENV-250)."),
        required=False,
    )
    field_schema_json = schema.Text(
        title=_(u"Field Schema (JSON)"),
        description=_(u"Ordered list of field definitions: [{name, label, type, ...}]"),
        required=False,
    )
    sort_order = schema.Int(
        title=_(u"Sort Order"),
        description=_(u"Position in the batch logbook list (lower = first)."),
        default=100,
        required=False,
    )
    active = schema.Bool(
        title=_(u"Show in Batch Index"),
        description=_(u"If False, hidden from the batch logbook list."),
        default=True,
        required=False,
    )
    builtin = schema.Bool(
        title=_(u"Built-in"),
        description=_(u"True for the four standard logbooks (cannot delete)."),
        default=False,
        required=False,
    )


@implementer(IPrepLogbookDef)
class PrepLogbookDef(Item):
    """Versioned preparation logbook definition."""
