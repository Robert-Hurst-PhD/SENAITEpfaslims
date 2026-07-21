# -*- coding: utf-8 -*-
"""
Archetypes schema extender for SENAITE AnalysisService.

Adds one PFAS-specific field to every AnalysisService edit form:

  pfas_role   — intrinsic identity of this service within the PFAS system:
                  analyte       — native target analyte
                  surrogate     — isotopically-labeled surrogate (quantifies a native)
                  injection_is  — injection internal standard (surrogates quantify against it)
                Blank = not part of the PFAS service set.

This role is the single authoritative source for the IS/surrogate/analyte
distinction.  The Method Profile, wizard, and pipeline all derive their IS
lists and surrogate maps from this field rather than from category names or
private per-profile lists.

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

from archetypes.schemaextender.field import ExtensionField
from archetypes.schemaextender.interfaces import ISchemaExtender
from Products.Archetypes.Field import StringField
from Products.Archetypes.public import DisplayList
from Products.Archetypes.Widget import SelectionWidget, StringWidget
from zope.component import adapts
from zope.interface import implements

from bika.lims.content.analysisservice import AnalysisService

ROLE_VOCAB = DisplayList((
    ("",            "— not a PFAS service —"),
    ("analyte",     "Target Analyte"),
    ("surrogate",   "Surrogate / Labeled Standard"),
    ("injection_is","Injection Internal Standard"),
))


class _ExtStringField(ExtensionField, StringField):
    pass


class AnalysisServiceExtender(object):
    """Adds PFAS identity fields to every AnalysisService.

    pfas_role            — analyte / surrogate / injection_is (the authoritative
                           source for the analyte/surrogate/IS lists).
    pfas_quant_surrogate — on an ANALYTE service: the KEYWORD of the surrogate
                           AnalysisService that quantifies it (the native→
                           surrogate quantification link, now living ON core
                           services — D58). Rich editing is in the Method
                           Profile → Surrogate Map; this field is the store.
    """

    implements(ISchemaExtender)
    adapts(AnalysisService)

    _fields = [
        _ExtStringField(
            "pfas_role",
            schemata="PFAS",
            required=False,
            default="",
            vocabulary=ROLE_VOCAB,
            widget=SelectionWidget(
                label="PFAS Role",
                description=(
                    "Identity of this service within the PFAS analytical system. "
                    "Surrogates quantify native analytes via the isotope-dilution "
                    "surrogate map.  The injection IS (M4PFOA) is the single "
                    "standard that all surrogates are quantified against."
                ),
                format="select",
            ),
        ),
        _ExtStringField(
            "pfas_quant_surrogate",
            schemata="PFAS",
            required=False,
            default="",
            widget=StringWidget(
                label="Quantifying Surrogate (keyword)",
                description=(
                    "For an ANALYTE service: the keyword of the surrogate "
                    "AnalysisService that quantifies this native (isotope "
                    "dilution). Edit via the Method Profile Surrogate Map; "
                    "this is the authoritative store on the core service."
                ),
                size=20,
            ),
        ),
    ]

    def __init__(self, context):
        self.context = context

    def getFields(self):
        return self._fields
