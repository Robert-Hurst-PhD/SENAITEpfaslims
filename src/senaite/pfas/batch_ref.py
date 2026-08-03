# -*- coding: utf-8 -*-
"""
Batch resolution — find a Batch wherever SENAITE keeps it.

A Batch with no Client lives in ``/senaite/batches``. A Batch WITH a Client is
stored under that client, ``/senaite/clients/<client>/<batch>``. Both are normal
SENAITE arrangements, and a batch moves from the first to the second the moment
its Client field is set.

Several views indexed ``portal["batches"]`` directly and so simply could not see
a client-owned batch. The Run Builder reported such a batch as "has no method"
rather than as not found, which sent the analyst to fix an extraction log that
was already complete.

Python 2.7 compatible.
"""
from __future__ import absolute_import, unicode_literals

import logging

logger = logging.getLogger("senaite.pfas.batch_ref")

_CATALOGS = ("senaite_catalog", "portal_catalog", "senaite_catalog_setup")


def _catalogs(portal):
    from Products.CMFCore.utils import getToolByName
    for name in _CATALOGS:
        try:
            tool = getToolByName(portal, name, None)
        except Exception:
            tool = None
        if tool is not None:
            yield tool


def get_batch(portal, batch_id):
    """The Batch with this id, or None. Searches the batches folder first (the
    common case, and cheapest), then the catalogs."""
    if not batch_id:
        return None
    try:
        folder = portal.get("batches")
        if folder is not None:
            batch = folder.get(batch_id)
            if batch is not None:
                return batch
    except Exception:
        pass
    for cat in _catalogs(portal):
        try:
            # unrestricted: this is an internal resolver, and a restricted
            # search silently returns nothing when the caller has no security
            # context (a bin/instance script, a test), which looks exactly like
            # "no such batch".
            for brain in cat.unrestrictedSearchResults(
                    portal_type="Batch", getId=batch_id):
                return brain.getObject()
        except Exception:
            continue
    return None


def list_batches(portal, review_state=None):
    """Every Batch in the site, client-owned ones included, newest first."""
    seen = set()
    out = []
    for cat in _catalogs(portal):
        try:
            query = {"portal_type": "Batch"}
            if review_state:
                query["review_state"] = review_state
            brains = cat.unrestrictedSearchResults(**query)
        except Exception:
            continue
        for brain in brains:
            uid = getattr(brain, "UID", None)
            if uid in seen:
                continue
            seen.add(uid)
            try:
                out.append(brain.getObject())
            except Exception:
                continue
        if out:
            break
    if not out:
        try:
            folder = portal.get("batches")
            if folder is not None:
                out = list(folder.objectValues())
        except Exception:
            pass
    return out
