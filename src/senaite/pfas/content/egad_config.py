# -*- coding: utf-8 -*-
"""EGADConfig content type — singleton EGAD configuration for this laboratory.

Stored as six JSON blobs, one per configuration section.  Singleton: exactly
one EGADConfig object lives at portal/pfas_egad_config/egad_config.

Blob strategy: all six config sections stay as JSON strings.  The public API
in egad_store.py handles deserialisation, back-fill from DEFAULT_* constants,
and re-serialisation — nothing changes for callers.

Python 2.7 compatible.
"""
from plone.dexterity.content import Item
from plone.supermodel import model
from zope import schema
from zope.interface import implementer

from bika.lims.interfaces import IDeactivable
from senaite.pfas import messageFactory as _


class IEGADConfig(model.Schema):
    """Singleton EGAD configuration — six sections, each stored as a JSON blob."""

    lab_json = schema.Text(
        title=_(u"Lab Config JSON"),
        description=_(u"Laboratory-global EGAD settings"),
        required=False,
    )

    method_egad_json = schema.Text(
        title=_(u"Method EGAD JSON"),
        description=_(u"Per-method EGAD submission settings"),
        required=False,
    )

    analyte_cas_json = schema.Text(
        title=_(u"Analyte CAS JSON"),
        description=_(u"Analyte to CAS number and EGAD parameter name mapping"),
        required=False,
    )

    qualifier_map_json = schema.Text(
        title=_(u"Qualifier Map JSON"),
        description=_(u"Qualifier code mapping table"),
        required=False,
    )

    qc_type_map_json = schema.Text(
        title=_(u"QC Type Map JSON"),
        description=_(u"QC type code mapping table"),
        required=False,
    )

    lookups_json = schema.Text(
        title=_(u"Lookups JSON"),
        description=_(u"Refreshable EGAD lookup value lists"),
        required=False,
    )


@implementer(IEGADConfig, IDeactivable)
class EGADConfig(Item):
    """Singleton EGAD configuration — first-class SENAITE content."""
