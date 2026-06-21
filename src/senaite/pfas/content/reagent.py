# -*- coding: utf-8 -*-
"""Reagent content type — a barcode-scanned reagent/standard lot.

First-class SENAITE citizen: indexed in senaite_catalog_setup, participates
in the global audit log, and is managed via standard Plone role/permission model.

Python 2.7 compatible.
"""
from plone.dexterity.content import Item
from plone.supermodel import model
from zope import schema
from zope.interface import implementer

from bika.lims.interfaces import IDeactivable
from senaite.pfas import messageFactory as _

STATUS_ACTIVE     = u"active"
STATUS_OPENED     = u"opened"
STATUS_EXHAUSTED  = u"exhausted"
STATUS_EXPIRED    = u"expired"
STATUS_QUARANTINE = u"quarantine"

REAGENT_CATEGORIES = [
    u"Mobile Phase / Solvent",
    u"Extraction Reagent",
    u"Standard / Reference Material",
    u"Internal Standard",
    u"Buffer",
    u"Acid / Base",
    u"Salt",
    u"Other Reagent",
]


class IReagent(model.Schema):
    """A reagent or standard lot, registered on first barcode scan.

    Fields map 1-to-1 with the legacy annotation store keys so migration
    is lossless.  `title` (from plone.dublincore) carries the reagent name.
    """
    category = schema.Choice(
        title=_(u"Category"),
        values=REAGENT_CATEGORIES,
        required=False,
    )
    supplier = schema.TextLine(
        title=_(u"Supplier / Manufacturer"),
        required=False,
    )
    cat_number = schema.TextLine(
        title=_(u"Catalog Number"),
        required=False,
    )
    lot_number = schema.TextLine(
        title=_(u"Lot Number"),
        required=True,
    )
    received_date = schema.Date(
        title=_(u"Received Date"),
        required=False,
    )
    manufacturer_expiry = schema.Date(
        title=_(u"Manufacturer Expiry"),
        required=False,
    )
    expiry_date = schema.Date(
        title=_(u"Effective Expiry Date"),
        description=_(u"Auto-computed from opened date when not set by manufacturer."),
        required=False,
    )
    opened_date = schema.Date(
        title=_(u"Date Opened"),
        required=False,
    )
    storage_location = schema.TextLine(
        title=_(u"Storage Location"),
        required=False,
    )
    barcode = schema.TextLine(
        title=_(u"Raw Barcode"),
        required=False,
    )
    quantity = schema.TextLine(
        title=_(u"Quantity"),
        required=False,
    )
    unit = schema.TextLine(
        title=_(u"Unit"),
        required=False,
    )
    scan_count = schema.Int(
        title=_(u"Scan Count"),
        default=0,
        required=False,
    )
    status = schema.Choice(
        title=_(u"Status"),
        values=[STATUS_ACTIVE, STATUS_OPENED, STATUS_EXHAUSTED,
                STATUS_EXPIRED, STATUS_QUARANTINE],
        default=STATUS_ACTIVE,
        required=False,
    )
    notes = schema.Text(
        title=_(u"Notes"),
        required=False,
    )


@implementer(IReagent, IDeactivable)
class Reagent(Item):
    """Reagent lot — first-class SENAITE content, indexed in setup catalog."""
