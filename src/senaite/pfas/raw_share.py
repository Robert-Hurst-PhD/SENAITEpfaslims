# -*- coding: utf-8 -*-
"""Where the instrument's raw data is pulled from (System).

    share_path       the instrument PC's data folder, shared read-only and
                     mounted on the server: an absolute path
    settle_minutes   how long a run's raw folders must be unchanged before
                     they are pulled: a whole number of minutes, 1 or more

Both are unset until a site administrator enters them; the worker pulls
nothing until then. Kept on the portal and exported as JSON for the worker
(its pull, pfas_pipeline.raw_pull, reads the export). Pure apart from
load/save; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import json
import os

KEY = "senaite.pfas.raw_share"
EXPORT = os.environ.get("PFAS_RAW_SHARE_EXPORT", "/data/qc/raw_share.json")
FIELDS = ("share_path", "settle_minutes")


def settings(stored):
    stored = stored or {}
    return dict((k, stored.get(k)) for k in FIELDS)


def from_form(form):
    """(settings, errors) from the System form; blank is unset."""
    path = (form.get("raw_share_path") or "").strip() or None
    minutes = (form.get("raw_settle_minutes") or "").strip() or None
    errors = []
    if path is not None and not path.startswith("/"):
        errors.append("The raw-data share is an absolute path, e.g. /mnt/lcms/data.")
    if minutes is not None:
        try:
            minutes = int(minutes)
            if minutes < 1:
                raise ValueError(minutes)
        except ValueError:
            errors.append("The settle time is a whole number of minutes, 1 or more.")
    return {"share_path": path, "settle_minutes": minutes}, errors


def export(values, path=None):
    """Write the worker's copy."""
    path = path or EXPORT
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(settings(values), fh, sort_keys=True)
    os.rename(tmp, path)


def _ann(portal):
    from zope.annotation.interfaces import IAnnotations
    return IAnnotations(portal)


def load(portal):
    try:
        return settings(json.loads(_ann(portal).get(KEY) or "{}"))
    except ValueError:
        return settings({})


def save(portal, values):
    from senaite.pfas import after_commit
    _ann(portal)[KEY] = json.dumps(settings(values), sort_keys=True)
    after_commit.run_once("raw share export", export, values)
