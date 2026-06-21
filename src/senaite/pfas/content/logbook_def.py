# -*- coding: utf-8 -*-
"""LogbookDef content type — a PFAS logbook definition.

First-class SENAITE citizen: indexed in senaite_catalog_setup, participates
in the global audit log, and managed via @@pfas-logbook-admin.

Python 2.7 compatible.
"""
from plone.dexterity.content import Item
from plone.supermodel import model
from zope import schema
from zope.interface import implementer

from bika.lims.interfaces import IDeactivable
from senaite.pfas import messageFactory as _


class ILogbookDef(model.Schema):
    """A logbook definition — form number, title, active flag, and optional
    custom table columns.  ``title`` (from plone.dublincore) carries the
    human-readable name; the object ID carries the slug."""

    form_num = schema.TextLine(
        title=_(u"Form Number"),
        description=_(u"Display code shown in the logbook index, e.g. FM-ENV-250"),
        required=False,
    )
    builtin = schema.Bool(
        title=_(u"Built-in"),
        description=_(u"True for the four original lab logbooks (can rename, cannot delete)"),
        default=False,
        required=False,
    )
    active = schema.Bool(
        title=_(u"Active"),
        description=_(u"False hides this logbook from the logbook index"),
        default=True,
        required=False,
    )
    sort_order = schema.Int(
        title=_(u"Sort Order"),
        description=_(u"Controls display ordering; lower numbers appear first"),
        default=0,
        required=False,
    )
    table_columns = schema.List(
        title=_(u"Table Columns"),
        description=_(u"Column names for the data table (custom logbooks only)"),
        required=False,
        value_type=schema.TextLine(),
    )


@implementer(ILogbookDef, IDeactivable)
class LogbookDef(Item):
    """Logbook definition — first-class SENAITE content, indexed in setup catalog."""
