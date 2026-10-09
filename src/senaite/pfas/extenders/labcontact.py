# -*- coding: utf-8 -*-
"""Schema extender: add an explicit `pfas_initials` field to LabContact.

Core LabContact already carries the Signature ImageField (upload on its edit
form); this adds the INITIALS the lab signs documents with (data review
sign-offs, corrections, logbooks) so they are declared per person, not derived
from the name. Python 2.7 compatible."""
from __future__ import absolute_import, print_function, unicode_literals

from archetypes.schemaextender.field import ExtensionField
from archetypes.schemaextender.interfaces import ISchemaExtender
from Products.Archetypes.Field import StringField
from Products.Archetypes.Widget import StringWidget
from zope.component import adapts
from zope.interface import implements

from bika.lims.content.labcontact import LabContact


class _ExtStringField(ExtensionField, StringField):
    pass


class LabContactExtender(object):
    """Adds pfas_initials to every LabContact."""

    implements(ISchemaExtender)
    adapts(LabContact)

    _fields = [
        _ExtStringField(
            "pfas_initials",
            schemata="default",
            required=False,
            default="",
            widget=StringWidget(
                label="Initials",
                description=(
                    "The initials this person signs laboratory documents with "
                    "(data-review sign-offs, corrections, logbooks). Together "
                    "with the Signature image below, these are appended to "
                    "filled-out documents."
                ),
                size=6,
                maxlength=6,
            ),
        ),
    ]

    def __init__(self, context):
        self.context = context

    def getFields(self):
        return self._fields
