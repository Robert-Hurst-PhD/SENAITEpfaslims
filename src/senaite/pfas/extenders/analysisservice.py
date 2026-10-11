# -*- coding: utf-8 -*-
"""
Archetypes schema extender for SENAITE AnalysisService.

Adds the PFAS fields to every AnalysisService edit form (its PFAS tab):

  pfas_role   — intrinsic identity of this service within the PFAS system:
                  analyte       — native target analyte
                  surrogate     — isotopically-labeled surrogate (quantifies a native)
                  injection_is  — injection internal standard (surrogates quantify against it)
                Blank = not part of the PFAS service set.

and the rest of the compound library (senaite.pfas.compound_library): the
compound's name in instrument exports, its CAS number, the native a labelled
standard is the labelled form of, other export spellings, published-method
names and the key-analyte default. The service is the one owner of these
facts; SENAITE exports them to the worker (compound_library.json) with the
method profiles and whenever a service changes.

This role is the single authoritative source for the IS/surrogate/analyte
distinction.  The Method Profile, wizard, and pipeline all derive their IS
lists and surrogate maps from this field rather than from category names or
private per-profile lists.

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

from archetypes.schemaextender.field import ExtensionField
from archetypes.schemaextender.interfaces import ISchemaExtender
from Products.Archetypes.Field import BooleanField, LinesField, StringField
from Products.Archetypes.public import DisplayList
from Products.Archetypes.Widget import BooleanWidget, LinesWidget, SelectionWidget, StringWidget
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


class _ExtLinesField(ExtensionField, LinesField):
    pass


class _ExtBooleanField(ExtensionField, BooleanField):
    pass


class AnalysisServiceExtender(object):
    """Adds PFAS identity fields to every AnalysisService.

    pfas_role            — analyte / surrogate / injection_is (the authoritative
                           source for the analyte/surrogate/IS lists).
    pfas_quant_surrogate — on an ANALYTE service: the KEYWORD of the surrogate
                           SUGGESTED when this native joins a method with no
                           surrogate chosen yet. Not read at run time: each
                           method's Surrogate Map owns the link.
    pfas_display_name, pfas_cas, pfas_labelled_analog_of, pfas_aliases,
    pfas_published_names, pfas_key_analyte
                         — the compound library's facts
                           (senaite.pfas.compound_library.FIELDS).
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
                    "surrogate map.  The injection IS (13C4-PFOA) is the single "
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
                label="Suggested Surrogate (keyword)",
                description=(
                    "For an ANALYTE service: the surrogate suggested when this "
                    "native is added to a method. Only a suggestion -- each "
                    "method chooses its own quantifying surrogate on its "
                    "Method Profile Surrogate Map."
                ),
                size=20,
            ),
        ),
        _ExtStringField(
            "pfas_display_name",
            schemata="PFAS",
            required=False,
            default="",
            widget=StringWidget(
                label="Name in instrument exports",
                description=(
                    "The compound name the instrument exports and the pipeline "
                    "matches results on (e.g. 13C2,D4-6:2FTS). Blank: the keyword."
                ),
                size=30,
            ),
        ),
        _ExtStringField(
            "pfas_labelled_analog_of",
            schemata="PFAS",
            required=False,
            default="",
            widget=StringWidget(
                label="Labelled form of (native keyword)",
                description=(
                    "For a LABELLED standard: the keyword of the native analyte "
                    "it is the isotopically labelled form of (13C8-PFOA: PFOA). "
                    "A native linked in a method to its own labelled form has a "
                    "labelled standard of its own there. Blank for a native."
                ),
                size=20,
            ),
        ),
        _ExtStringField(
            "pfas_cas",
            schemata="PFAS",
            required=False,
            default="",
            widget=StringWidget(
                label="CAS number",
                description=(
                    "For a NATIVE analyte: its CAS Registry Number, which EDD "
                    "exports carry (a delivery format's own code overrides it in "
                    "that format's EDD export profile). Leave blank where none "
                    "exists."
                ),
                size=20,
            ),
        ),
        _ExtLinesField(
            "pfas_aliases",
            schemata="PFAS",
            required=False,
            default=(),
            widget=LinesWidget(
                label="Other names in instrument exports",
                description=(
                    "Other names an instrument or export may use for this "
                    "compound, one per line (a retired supplier code, the "
                    "linear peak's name, a vendor spelling). Each is read as "
                    "this service."
                ),
                rows=3,
            ),
        ),
        _ExtLinesField(
            "pfas_published_names",
            schemata="PFAS",
            required=False,
            default=(),
            widget=LinesWidget(
                label="Names in published methods",
                description=(
                    "How a published method names this analyte where it differs "
                    "from the keyword, one per line (EPA's HFPO-DA for GenX). "
                    "Used to join a method's own tables to the analyte."
                ),
                rows=2,
            ),
        ),
        _ExtBooleanField(
            "pfas_key_analyte",
            schemata="PFAS",
            required=False,
            default=False,
            widget=BooleanWidget(
                label="Key analyte by default",
                description=(
                    "A NATIVE marked here starts as a key analyte when a method "
                    "is set up; each method's Key analytes list decides."
                ),
            ),
        ),
    ]

    def __init__(self, context):
        self.context = context

    def getFields(self):
        return self._fields
