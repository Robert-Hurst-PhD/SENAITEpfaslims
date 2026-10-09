# -*- coding: utf-8 -*-
"""
Write the core Analysis Profiles for every method (analysis_profiles.py). Every method profile save does this; run once for the
methods saved before it existed. Idempotent.

  docker exec -u senaite <container> sh -c 'cd /home/senaite/senaitelims && \
    bin/instance run /addon/src/senaite/pfas/migrations/sync_analysis_profiles.py'

Python 2.7.
"""
from __future__ import absolute_import, print_function, unicode_literals


def run(portal):
    from senaite.pfas.analysis_profiles import sync_method
    from senaite.pfas.method_profile_store import list_method_ids
    for mid in sorted(list_method_ids(portal)):
        lines = sync_method(portal, mid)
        print(mid, "|", "; ".join(lines) or "up to date")


if __name__ == "__main__":
    import transaction
    from Testing.makerequest import makerequest
    from zope.component.hooks import setSite
    app_ = makerequest(app)                                 # noqa: F821 (bin/instance run)
    portal_ = app_.senaite
    setSite(portal_)
    # catalogs filter by the current user: run as the Zope admin, or samples
    # are invisible (a "no sample uses it" check would always pass)
    from AccessControl.SecurityManagement import newSecurityManager
    newSecurityManager(None, app_.acl_users.getUserById("admin").__of__(app_.acl_users))
    portal_.setupCurrentSkin(app_.REQUEST)
    run(portal_)
    transaction.commit()
    print("committed")
