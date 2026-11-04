# -*- coding: utf-8 -*-
"""What the Prepared Standards and Prep Logbooks pages share."""
from __future__ import absolute_import, unicode_literals


class PrepTypesMixin(object):

    def standard_types(self):
        """[(key, label)]: the lab's prepared-standard types."""
        from bika.lims import api
        from senaite.pfas import vocab_store as vs
        return vs.options(vs.get(api.get_portal()), "prepared_standard_types")
