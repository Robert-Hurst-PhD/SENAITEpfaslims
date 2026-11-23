# -*- coding: utf-8 -*-
"""Schema extender: what a sample asks of homogenisation, what a
composite is made of, and the report tier it is reported at.

    HomogenisationMethod   the lab's method id (homogenisation.py), prefilled
                           from the matrix's default when the sample is made
    CompositeUnits         how many units were combined (core's Composite
                           tick box says whether it is one)
    CompositeDescription   what was combined
    ReportTier             the report tier's id (report_tiers), prefilled
                           from the client's default when the sample is made;
                           set by a Lab Manager (the LabManager or Manager
                           role at the portal; core grants Manage Bika to
                           clerks too) until the sample is published, and
                           offered on Add Sample only to them

They sit on core's Add Sample form and the sample view, editable while
core lets its own Composite field be edited (FieldEditComposite).
Python 2.7.
"""
from __future__ import absolute_import, print_function, unicode_literals

from archetypes.schemaextender.field import ExtensionField
from archetypes.schemaextender.interfaces import IOrderableSchemaExtender
from Products.Archetypes.Field import BooleanField
from Products.Archetypes.Field import IntegerField
from Products.Archetypes.Field import StringField
from Products.Archetypes.interfaces import IVocabulary
from Products.Archetypes.utils import DisplayList
from Products.Archetypes.Widget import BooleanWidget
from Products.Archetypes.Widget import IntegerWidget
from bika.lims.browser.widgets import SelectionWidget as BikaSelectionWidget
from Products.Archetypes.Widget import StringWidget
from zope.component import adapts
from zope.interface import implementer
from zope.interface import implements

from bika.lims.content.analysisrequest import AnalysisRequest
from senaite.core.permissions import FieldEditComposite
from senaite.core.permissions import ManageBika
from Products.CMFCore.permissions import View


class _ExtStringField(ExtensionField, StringField):
    pass


class _ExtBooleanField(ExtensionField, BooleanField):
    pass


class _ExtIntegerField(ExtensionField, IntegerField):
    pass


def _tier_locked(instance):
    from bika.lims import api
    from senaite.pfas import report_tiers as rt
    return api.get_review_status(instance) in rt.LOCKED_STATES


def _may_set_tier(instance):
    """Whether the current user may set a sample's report tier: the
    LabManager or Manager role at the portal (perms.MANAGER_ROLES). Core's
    Manage Bika is not enough, since core grants it to the LabClerk too.
    Asked on every call, by the extender's field choice and by the field's
    own write and edit checks. A check that cannot be made denies."""
    from senaite.pfas.browser.perms import MANAGER_ROLES, has_role_at_portal
    return has_role_at_portal(instance, MANAGER_ROLES)


class _ReportTierField(_ExtStringField):
    """The report tier: written by a Lab Manager only (the role narrows the
    write permission), and read-only to everyone once the sample is
    published (or invalid, cancelled or rejected). This is the hard rule:
    whichever variant a form draws, a clerk's value is never written."""

    def writeable(self, instance, debug=False):
        if _tier_locked(instance) or not _may_set_tier(instance):
            return False
        return _ExtStringField.writeable(self, instance, debug)

    def checkPermission(self, mode, instance):
        if mode == "edit" and (_tier_locked(instance) or not _may_set_tier(instance)):
            return False
        return _ExtStringField.checkPermission(self, mode, instance)


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
            current = (field.get(instance) or u"") if field is not None else u""
        except AttributeError:
            pass
        items = [(u"", u"")] + hg.choices(hg.load_methods(api.get_portal()), current)
        return DisplayList(items)

    def isFlat(self):
        return True

    def showLeafsOnly(self):
        return True


@implementer(IVocabulary)
class ReportTierVocabulary(object):
    """The issued report tiers, "Client's default" first, and the sample's
    own value even when the issued catalogue no longer has it."""

    def getDisplayList(self, instance):
        from bika.lims import api
        from senaite.pfas import report_tiers as rt
        from senaite.pfas.report_templates import issued_tiers
        catalogue, _rev = issued_tiers(api.get_portal())
        items = [(u"", u"Client's default")]
        items += [(t["id"], rt.label(catalogue, t["id"])) for t in catalogue]
        current = u""
        try:
            field = instance.getField(rt.FIELD)
            current = (field.get(instance) or u"") if field is not None else u""
        except AttributeError:
            pass
        if current and current not in [i for i, _l in items]:
            items.append((current, current))
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


def _report_tier_field(visible):
    """The Certificate tier field with the widget visibility `visible`: what the
    client receives with the report, prefilled from the client's default
    when the sample is made (report_tiers on_sample_initialized). A plain
    selection widget: core's Add Sample form draws an input only for the
    widget classes it lists, never a subclass."""
    return _ReportTierField(
        "ReportTier",
        mode="rw",
        read_permission=View,
        write_permission=ManageBika,
        vocabulary=ReportTierVocabulary(),
        enforceVocabulary=False,
        widget=BikaSelectionWidget(
            label="Certificate tier",
            description="Blank takes the client's default.",
            format="select",
            render_own_label=True,
            visible=visible,
        ),
    )


# Add Sample and the edit form offer the tier to a Lab Manager only; everyone
# sees it read-only in the sample header. Core's header lists a field only
# when its widget answers "visible" for the view mode, and Archetypes answers
# None for a mode the dict does not name, so both name view and edit. Two
# fields built once, never one mutated.
REPORT_TIER_ON_ADD = _report_tier_field(
    {"add": "edit", "edit": "visible", "view": "visible", "header_table": "visible"})
REPORT_TIER_IN_HEADER = _report_tier_field(
    {"add": "invisible", "edit": "invisible", "view": "visible", "header_table": "visible"})


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
                label="Items composited",
                description="For a composite: how many separate items were ground together.",
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
        # a regulatory compliance sample: received out of compliance with its
        # method it is held from publishing and a resample is requested
        # (receipt_compliance; set on its CoC row)
        _ExtBooleanField(
            "ComplianceSample",
            mode="rw",
            read_permission=View,
            write_permission=FieldEditComposite,
            default=False,
            widget=BooleanWidget(
                label="Compliance sample",
                description="Received out of compliance with its method, it is held and a resample is requested.",
                render_own_label=True,
                visible={"add": "edit", "header_table": "visible"},
            ),
        ),
        # the sample's sub-type (a sample_subtypes id, from its CoC row): a
        # regulatory limit that names sub-types applies only to samples of those
        _ExtStringField(
            "SampleSubtype",
            mode="rw",
            read_permission=View,
            write_permission=FieldEditComposite,
            widget=StringWidget(
                label="Sub-type",
                description="The sample type's sub-type, as its CoC row names it.",
                render_own_label=True,
                size=20,
                visible={"add": "invisible", "header_table": "visible"},
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
        # the Certificate tier comes last, chosen by the user's role on each call;
        # getOrder places only the first three
        variant = REPORT_TIER_ON_ADD if _may_set_tier(self.context) else REPORT_TIER_IN_HEADER
        return list(self._fields) + [variant]

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
