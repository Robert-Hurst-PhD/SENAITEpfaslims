# -*- coding: utf-8 -*-
"""PreparedStandard — an in-house prepared reagent or standard lot.

Separate from `Reagent` (procured lots).  Each object records:
  - Which prep logbook + revision was followed
  - Who prepared it and when
  - Analyte concentrations (JSON annotation)
  - Parent reagents consumed (JSON annotation)
  - Expiry date (auto = prepared_date + logbook.default_expiry_days, editable)
  - Internal certificate (generated HTML stored in annotation)

Python 2.7 compatible.
"""
from plone.dexterity.content import Item
from plone.supermodel import model
from zope import schema
from zope.interface import implementer

from senaite.pfas import messageFactory as _

STATUS_ACTIVE    = u"active"
STATUS_EXHAUSTED = u"exhausted"
STATUS_EXPIRED   = u"expired"

STANDARD_TYPES = [
    u"Calibration Standard",
    u"QC Check Standard",
    u"Surrogate Mix",
    u"Internal Standard Mix",
    u"Matrix Spike",
    u"Solvent / Reagent",
    u"Other",
]


class IPreparedStandard(model.Schema):
    """An in-house prepared reagent or standard."""

    lot_number = schema.TextLine(
        title=_(u"In-House Lot Number"),
        required=True,
    )
    standard_type = schema.Choice(
        title=_(u"Standard Type"),
        values=STANDARD_TYPES,
        required=False,
    )
    logbook_slug = schema.TextLine(
        title=_(u"Prep Logbook Slug"),
        description=_(u"Which logbook family was followed."),
        required=False,
    )
    logbook_revision = schema.Int(
        title=_(u"Logbook Revision"),
        description=_(u"Revision number in effect at time of preparation."),
        required=False,
    )
    logbook_title = schema.TextLine(
        title=_(u"Logbook Title"),
        description=_(u"Snapshot of logbook title at time of preparation."),
        required=False,
    )
    prepared_by = schema.TextLine(
        title=_(u"Prepared By"),
        required=False,
    )
    prepared_date = schema.Date(
        title=_(u"Date Prepared"),
        required=False,
    )
    expiry_date = schema.Date(
        title=_(u"Expiry Date"),
        required=False,
    )
    expiry_notes = schema.TextLine(
        title=_(u"Expiry Justification"),
        description=_(u"Required if expiry differs from the logbook default."),
        required=False,
    )
    storage_location = schema.TextLine(
        title=_(u"Storage Location"),
        required=False,
    )
    volume_prepared = schema.TextLine(
        title=_(u"Volume / Amount Prepared"),
        required=False,
    )
    status = schema.Choice(
        title=_(u"Status"),
        values=[STATUS_ACTIVE, STATUS_EXHAUSTED, STATUS_EXPIRED],
        default=STATUS_ACTIVE,
        required=False,
    )
    notes = schema.Text(
        title=_(u"Notes"),
        required=False,
    )


@implementer(IPreparedStandard)
class PreparedStandard(Item):
    """In-house prepared reagent or standard lot."""
