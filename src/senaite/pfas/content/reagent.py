# -*- coding: utf-8 -*-
"""Reagent content type — a barcode-scanned reagent/standard lot."""
from plone.dexterity.content import Item
from plone.supermodel import model
from plone.autoform import directives
from zope import schema
from zope.interface import implementer
from senaite.pfas import messageFactory as _


class IReagent(model.Schema):
    """A reagent or standard lot, registered on first barcode scan."""
    catalog_number = schema.TextLine(title=_("Catalog Number"), required=True)
    lot_number = schema.TextLine(title=_("Lot Number"), required=True)
    manufacturer = schema.TextLine(title=_("Manufacturer"), required=False)
    expiry_date = schema.Date(title=_("Expiry Date"), required=False)
    date_opened = schema.Date(title=_("Date Opened"), required=False)
    reagent_class = schema.Choice(
        title=_("Reagent Class"),
        values=["solvent", "standard", "spe", "salt", "default"],
        default="default", required=False)
    barcode = schema.TextLine(title=_("Raw Barcode"), required=False)
    storage_location = schema.TextLine(title=_("Storage Location"), required=False)
    scan_count = schema.Int(title=_("Scan Count"), default=0, required=False)


@implementer(IReagent)
class Reagent(Item):
    """Reagent lot."""
