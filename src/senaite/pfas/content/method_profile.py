# -*- coding: utf-8 -*-
"""MethodProfile content type — full PFAS method QC configuration.

First-class SENAITE citizen: indexed in senaite_catalog_setup, participates
in the global audit log, and managed via @@pfas-method-profiles.

The full profile is stored as a JSON blob in ``profile_json`` (blob strategy).
One Dexterity object per method ID (e.g. FDA_32PFAS, EPA_537_1, EPA_1633A).
``title`` (from plone.dublincore) carries the method display name.

Python 2.7 compatible.
"""
from plone.dexterity.content import Item
from plone.supermodel import model
from zope import schema
from zope.interface import implementer

from bika.lims.interfaces import IDeactivable
from senaite.pfas import messageFactory as _


class IMethodProfile(model.Schema):
    """Method profile — the complete nested QC configuration for one method,
    stored as a JSON string.  Blob strategy preserves read-time back-fill and
    all existing CRUD semantics while gaining audit trail and ACL from Dexterity."""

    profile_json = schema.Text(
        title=_(u"Profile JSON"),
        description=_(u"Full method profile configuration as JSON"),
        required=False,
    )


@implementer(IMethodProfile, IDeactivable)
class MethodProfile(Item):
    """Method profile — first-class SENAITE content, indexed in setup catalog."""
