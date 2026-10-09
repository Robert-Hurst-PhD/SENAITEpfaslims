# -*- coding: utf-8 -*-
"""Page addresses the lab has retired, and where each one now lives. A
bookmark or an old link to a retired address goes to its replacement, query
kept. Python 2.7.

The EDD export's pages were named after the one format they first served;
the export is now one tool with formats as profiles, so their addresses were renamed. This table is the one
place the old names remain.
"""
from __future__ import absolute_import, unicode_literals

RETIRED = {
    "@@pfas-egad-config": "@@pfas-edd-config",
    "@@pfas-egad-client-config": "@@pfas-edd-client-config",
    "@@pfas-egad-export": "@@pfas-edd-export",
    "@@pfas-egad-batches": "@@pfas-edd-batches",
}


class RetiredAddressView(object):
    """A retired page: its request goes to the replacement, query kept
    (registered under each retired name in retired_addresses.zcml)."""

    def __init__(self, context, request):
        self.context, self.request = context, request

    def __call__(self):
        new = RETIRED.get("@@" + (self.__name__ or ""), "")
        query = self.request.get("QUERY_STRING", "")
        target = "%s/%s" % (self.context.absolute_url(), new)
        self.request.response.redirect(target + ("?" + query if query else ""))
        return ""
