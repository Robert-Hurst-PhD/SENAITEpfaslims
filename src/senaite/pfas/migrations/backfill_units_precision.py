# -*- coding: utf-8 -*-
"""
Backfill: the reporting unit and display precision on core analyses
(one owner per fact). The worker sets both on every result it writes from now on; this gives
results written before the same: the unit from the method profile for the
sample's matrix, and the decimals the lab's rounding leaves for the result.
The stored result is not changed.

  docker exec -u senaite <container> sh -c 'cd /home/senaite/senaitelims && \
    bin/instance run /addon/src/senaite/pfas/migrations/backfill_units_precision.py'

Uses analysis_display.apply, the same rule SENAITE applies on every change
from now on. Idempotent. Python 2.7.
"""
from __future__ import absolute_import, print_function, unicode_literals


def run(portal):
    from bika.lims import api
    from senaite.pfas.analysis_display import apply
    from senaite.pfas.sample_method import reported_analyses
    changed = unchanged = 0
    for brain in api.search({"portal_type": "AnalysisRequest"}, "senaite_catalog_sample"):
        for an in reported_analyses(api.get_object(brain)):
            if apply(an):
                changed += 1
            else:
                unchanged += 1
    print("analyses changed: %d, unchanged or not PFAS analytes: %d" % (changed, unchanged))


if __name__ == "__main__":
    import transaction
    from Testing.makerequest import makerequest
    from zope.component.hooks import setSite
    app_ = makerequest(app)                                 # noqa: F821 (bin/instance run)
    portal_ = app_.senaite
    setSite(portal_)
    portal_.setupCurrentSkin(app_.REQUEST)
    # catalogs filter by the current user: run as the Zope admin, or every
    # sample is invisible and nothing is backfilled
    from AccessControl.SecurityManagement import newSecurityManager
    newSecurityManager(None, app_.acl_users.getUserById("admin").__of__(app_.acl_users))
    run(portal_)
    transaction.commit()
    print("committed")
