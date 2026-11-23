# -*- coding: utf-8 -*-
"""The Sample Type form refuses a title already in use: a matrix is named
by its Sample Type's title, so two Sample Types of one title, or a title a
method profile holds for another matrix (its name or an earlier name), would
make two matrices one (matrix_rename.title_in_use says which). A field
validator on core's form, for the PFAS layer: core's form and template are
not changed. Python 2.7."""
from __future__ import absolute_import, unicode_literals

from senaite.core.content.sampletype import ISampleTypeSchema
from senaite.core.interfaces import ISampleType
from senaite.pfas.interfaces import ISenaitePFASLayer
from z3c.form import validator
from zope.interface import Invalid


def _sample_types():
    from bika.lims import api
    return dict((b.UID, api.safe_unicode(b.getObject().Title()))
                for b in api.get_tool("senaite_catalog_setup")(portal_type="SampleType"))


def _profiles(portal):
    from senaite.pfas import method_profile_store as mps
    return dict((mid, mps.raw_profile(portal, mid) or {}) for mid in mps.list_method_ids(portal))


class SampleTypeTitleValidator(validator.SimpleFieldValidator):
    """Refuses a title already in use, on the add and the edit form."""

    def validate(self, value):
        super(SampleTypeTitleValidator, self).validate(value)
        from bika.lims import api
        from senaite.pfas.matrix_rename import title_in_use
        uid = api.get_uid(self.context) if ISampleType.providedBy(self.context) else None
        problem = title_in_use(api.safe_unicode(value or u""), uid, _sample_types(),
                               _profiles(api.get_portal()))
        if problem:
            raise Invalid(problem + u" Choose another name.")


validator.WidgetValidatorDiscriminators(
    SampleTypeTitleValidator, field=ISampleTypeSchema["title"], request=ISenaitePFASLayer)
