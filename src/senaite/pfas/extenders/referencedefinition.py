# -*- coding: utf-8 -*-
"""
Archetypes schema extender for SENAITE ReferenceDefinition.

Adds three PFAS-specific fields to every ReferenceDefinition edit form:

  pfas_qc_code          — shortcode identifying the QC type in the pool
                          (MB, LFB, LFSM, LFSMD, LCS, LRB, MxB, Dup, CCV,
                           ICV, CAL).  Blank = not a PFAS QC type.
  pfas_category         — instrument / extraction / blank
  pfas_acceptance_schema — which parameter schema to use when defining
                           acceptance criteria in the Method Profile
                           (recovery_tiered, tiered_recovery_rpd, rpd_tiered,
                            blank_threshold, instrument_ccv, instrument_cal)

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

from archetypes.schemaextender.field import ExtensionField
from archetypes.schemaextender.interfaces import ISchemaExtender
from Products.Archetypes.Field import StringField
from Products.Archetypes.public import DisplayList
from Products.Archetypes.Widget import SelectionWidget
from zope.component import adapts
from zope.interface import implements

from bika.lims.content.referencedefinition import ReferenceDefinition

# ── Vocabulary constants ──────────────────────────────────────────────────────

QC_CODE_VOCAB = DisplayList((
    ("",       "— not a PFAS QC type —"),
    ("MB",     "MB — Method Blank"),
    ("LRB",    "LRB — Lab Reagent Blank"),
    ("MxB",    "MxB — Matrix Blank"),
    ("LFB",    "LFB — Laboratory Fortified Blank"),
    ("LCS",    "LCS — Laboratory Control Sample"),
    ("LFSM",   "LFSM — Lab Fortified Sample Matrix"),
    ("LFSMD",  "LFSMD — LFSM Duplicate"),
    ("Dup",    "Dup — Sample Duplicate"),
    ("CAL",    "CAL — Calibration Standard"),
    ("ICV",    "ICV — Initial Calibration Verification"),
    ("CCV",    "CCV — Continuing Calibration Verification"),
))

CATEGORY_VOCAB = DisplayList((
    ("",            "— select —"),
    ("blank",       "Blank"),
    ("extraction",  "Extraction / Matrix"),
    ("instrument",  "Instrument Verification"),
))

SCHEMA_VOCAB = DisplayList((
    ("",                    "— select —"),
    ("blank_threshold",     "Blank threshold (max conc × RL)"),
    ("recovery_tiered",     "Tiered recovery (LFB / LCS / LFSM)"),
    ("tiered_recovery_rpd", "Tiered recovery + RPD (LFSMD)"),
    ("rpd_tiered",          "Tiered RPD only (field duplicate)"),
    ("instrument_cal",      "Instrument — calibration"),
    ("instrument_ccv",      "Instrument — CCV"),
))


# ── Extended field classes ────────────────────────────────────────────────────

class _ExtStringField(ExtensionField, StringField):
    pass


# ── Extender ─────────────────────────────────────────────────────────────────

class ReferenceDefinitionExtender(object):
    """Adds PFAS QC pool metadata fields to ReferenceDefinition."""

    implements(ISchemaExtender)
    adapts(ReferenceDefinition)

    _fields = [
        _ExtStringField(
            "pfas_qc_code",
            schemata="PFAS",
            required=False,
            default="",
            vocabulary=QC_CODE_VOCAB,
            widget=SelectionWidget(
                label="PFAS QC Type Code",
                description=(
                    "Select the PFAS QC type this reference material "
                    "represents.  Leave blank for non-PFAS definitions."
                ),
                format="select",
            ),
        ),
        _ExtStringField(
            "pfas_category",
            schemata="PFAS",
            required=False,
            default="",
            vocabulary=CATEGORY_VOCAB,
            widget=SelectionWidget(
                label="PFAS QC Category",
                description=(
                    "Blank: contamination check.  "
                    "Extraction/Matrix: spiked sample QC.  "
                    "Instrument Verification: calibration / CCV."
                ),
                format="select",
            ),
        ),
        _ExtStringField(
            "pfas_acceptance_schema",
            schemata="PFAS",
            required=False,
            default="",
            vocabulary=SCHEMA_VOCAB,
            widget=SelectionWidget(
                label="PFAS Acceptance Schema",
                description=(
                    "Controls which parameter fields appear in the Method "
                    "Profile when acceptance criteria are defined for this "
                    "QC type."
                ),
                format="select",
            ),
        ),
    ]

    def __init__(self, context):
        self.context = context

    def getFields(self):
        return self._fields
