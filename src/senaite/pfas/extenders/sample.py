# -*- coding: utf-8 -*-
"""Schema extender: what a sample asks of homogenisation, and what a
composite is made of (H2-H3).

    HomogenisationMethod   the lab's method id (homogenisation.py), prefilled
                           from the matrix's default when the sample is made
    CompositeUnits         how many units were combined (core's Composite
                           tick box says whether it is one)
    CompositeDescription   what was combined

They sit on core's Add Sample form and the sample view, editable while
core lets its own Composite field be edited (FieldEditComposite).
Python 2.7.
"""
from __future__ import absolute_import, print_function, unicode_literals

from archetypes.schemaextender.field import ExtensionField
from archetypes.schemaextender.interfaces import IOrderableSchemaExtender
from Products.Archetypes.Field import IntegerField
from Products.Archetypes.Field import StringField
from Products.Archetypes.interfaces import IVocabulary
from Products.Archetypes.utils import DisplayList
from Products.Archetypes.Widget import IntegerWidget
from bika.lims.browser.widgets import SelectionWidget as BikaSelectionWidget
from Products.Archetypes.Widget import StringWidget
from zope.component import adapts
from zope.interface import implementer
from zope.interface import implements

from bika.lims.content.analysisrequest import AnalysisRequest
from senaite.core.permissions import FieldEditComposite
from Products.CMFCore.permissions import View


class _ExtStringField(ExtensionField, StringField):
    pass


class _ExtIntegerField(ExtensionField, IntegerField):
    pass


@implementer(IVocabulary)
class HomogenisationVocabulary(object):
    """The lab's methods: "Not homogenised" first, active ones, and the
    sample's own value even when that method is retired."""

    def getDisplayList(self, instance):
        from bika.lims import api
        from senaite.pfas import homogenisation as hg
        current = u""
        try:
            field = instance.getField(hg.FIELD_METHOD)
            current = field.get(instance) or u"" if field is not None else u""
        except Exception:                                   # noqa: BLE001
            pass
        items = [(u"", u"")] + hg.choices(hg.load_methods(api.get_portal()), current)
        return DisplayList(items)

    def isFlat(self):
        return True

    def showLeafsOnly(self):
        return True


@implementer(IVocabulary)
class FieldQCVocabulary(object):

    def getDisplayList(self, instance):
        from senaite.pfas.coc_records import FIELD_QC_TYPES
        return DisplayList([(u"", u"")] + [(t, t) for t in FIELD_QC_TYPES])

    def isFlat(self):
        return True

    def showLeafsOnly(self):
        return True


class SampleExtender(object):

    implements(IOrderableSchemaExtender)
    adapts(AnalysisRequest)

    _fields = [
        _ExtStringField(
            "HomogenisationMethod",
            mode="rw",
            read_permission=View,
            write_permission=FieldEditComposite,
            vocabulary=HomogenisationVocabulary(),
            enforceVocabulary=False,
            widget=BikaSelectionWidget(
                label="Homogenisation",
                description="How the sample is homogenised. Blank takes the matrix's default.",
                format="select",
                render_own_label=True,
                visible={"add": "edit", "header_table": "visible"},
            ),
        ),
        _ExtIntegerField(
            "CompositeUnits",
            mode="rw",
            read_permission=View,
            write_permission=FieldEditComposite,
            widget=IntegerWidget(
                label="Units combined",
                description="For a composite: how many units were combined.",
                render_own_label=True,
                size=4,
                visible={"add": "edit", "header_table": "visible"},
            ),
        ),
        _ExtStringField(
            "CompositeDescription",
            mode="rw",
            read_permission=View,
            write_permission=FieldEditComposite,
            widget=StringWidget(
                label="What was combined",
                description="For a composite, e.g. whole egg, shell removed.",
                render_own_label=True,
                size=30,
                visible={"add": "edit", "header_table": "visible"},
            ),
        ),
        # chain of custody
        _ExtStringField(
            "CoCNumber",
            mode="r",
            read_permission=View,
            write_permission=FieldEditComposite,
            widget=StringWidget(
                label="CoC number",
                description="The chain of custody this sample was submitted under.",
                render_own_label=True,
                visible={"add": "invisible", "header_table": "visible"},
            ),
        ),
        _ExtStringField(
            "FieldQCType",
            mode="rw",
            read_permission=View,
            write_permission=FieldEditComposite,
            vocabulary=FieldQCVocabulary(),
            enforceVocabulary=False,
            widget=BikaSelectionWidget(
                label="Field QC",
                description="A field blank or duplicate: which kind.",
                format="select",
                render_own_label=True,
                visible={"add": "edit", "header_table": "visible"},
            ),
        ),
        _ExtStringField(
            "FieldQCOf",
            mode="rw",
            read_permission=View,
            write_permission=FieldEditComposite,
            widget=StringWidget(
                label="Field QC of",
                description="The client sample ID this blank or duplicate goes with.",
                render_own_label=True,
                size=20,
                visible={"add": "edit", "header_table": "visible"},
            ),
        ),
    ]

    def __init__(self, context):
        self.context = context

    def getFields(self):
        return self._fields

    def getOrder(self, schematas):
        """Right after core's Composite, so the composite's details follow
        its tick box on the add form and the sample view."""
        names = [f.getName() for f in self._fields[:3]]
        for key, fields in schematas.items():
            if "Composite" in fields and all(n in fields for n in names):
                rest = [f for f in fields if f not in names]
                at = rest.index("Composite") + 1
                schematas[key] = rest[:at] + names + rest[at:]
        return schematas
