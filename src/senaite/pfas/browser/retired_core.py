# -*- coding: utf-8 -*-
"""Core screens the lab has retired (core integration).

SENAITE's Analysis Specifications, Dynamic Analysis Specifications and
Calculations judge or recompute a result by rules the QC engine does not
know: a specification flags results on core screens, a calculation rewrites a
result the pipeline wrote. The method profiles own the criteria, so these
folders leave the sidebar and the Setup groups (lims_setup.py), and any
request into them -- the listing, an add form, an item -- goes to Method
Profiles instead. Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

RETIRED_SETUP_IDS = frozenset(("bika_analysisspecs", "dynamicanalysisspecs", "bika_calculations"))
# a client's own specifications page (Client type action "specs")
RETIRED_SEGMENTS = RETIRED_SETUP_IDS | frozenset(("analysisspecs",))


def retired_path(path):
    """True when a URL path enters one of the retired folders."""
    segments = [s for s in ("%s" % (path or "")).split("?", 1)[0].split("/") if s]
    return any(s in RETIRED_SEGMENTS for s in segments)


def redirect_retired(event):
    """IPubAfterTraversal: a request into a retired folder goes to Method
    Profiles. Costs one string split per request."""
    request = event.request
    if not retired_path(request.get("PATH_INFO", "")):
        return
    from bika.lims import api
    from zExceptions import Redirect
    raise Redirect("%s/@@pfas-method-profiles" % api.get_portal().absolute_url())
