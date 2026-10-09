# -*- coding: utf-8 -*-
"""Issued revisions of a method profile.

A manager issues a revision when a method's settings are final. The revision
number increments and that method's settings report PDF is frozen:

    PDF       {dirname(PFAS_PROFILES_PATH)}/method_revisions/<method>/rev-0004.pdf
              (binary artifact -> filesystem tier)
    record    portal annotation KEY = {method: [{"rev", "issued_at",
              "issued_by", "reason", "fingerprint", "file"}]}

"Unissued changes" = the method's current settings fingerprint differs from
the latest revision's. The fingerprint covers what the method report is made
from: the profile (save stamps excluded) and the method's rule switches.

Pure helpers + a thin storage shell. Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import copy
import io
import json
import os

KEY = "senaite.pfas.method_revisions"
_STAMPS = ("updated_at", "updated_by")


def _settings_fingerprint(profile, toggles):
    try:
        from senaite.pfas import settings_report as sr
    except Exception:          # tests: loaded without the package
        import settings_report as sr
    p = copy.deepcopy(profile or {})
    for k in _STAMPS:
        p.pop(k, None)
    return sr.fingerprint(p, toggles or {})


fingerprint = _settings_fingerprint


def next_number(records):
    return max([r.get("rev", 0) for r in records] or [0]) + 1


def status(records, current_fingerprint):
    """{"rev", "issued_at", "issued_by", "unissued"} for the list page; rev
    None when never issued (unissued is then True)."""
    if not records:
        return {"rev": None, "issued_at": u"", "issued_by": u"", "unissued": True}
    last = sorted(records, key=lambda r: r.get("rev", 0))[-1]
    return {"rev": last.get("rev"), "issued_at": last.get("issued_at", u""),
            "issued_by": last.get("issued_by", u""),
            "unissued": last.get("fingerprint") != current_fingerprint}


def file_name(rev):
    return u"rev-%04d.pdf" % int(rev)


# ── storage (Zope + filesystem) ──────────────────────────────────────────────

def revisions_dir(method_id, base=None):
    if base is None:
        base = os.path.dirname(os.environ.get("PFAS_PROFILES_PATH", "/data/qc/method_profiles.json"))
    safe = u"".join(c for c in u"%s" % method_id if c.isalnum() or c in u"_-.")
    return os.path.join(base, "method_revisions", safe)


def _ann(portal):
    from zope.annotation.interfaces import IAnnotations
    return IAnnotations(portal)


def records(portal, method_id):
    raw = _ann(portal).get(KEY)
    data = json.loads(raw) if raw else {}
    return list(data.get(method_id) or [])


def issue(portal, method_id, pdf_bytes, fingerprint_value, who, when, reason, rev=None):
    """Write the frozen PDF, then record the revision. Returns the record.
    The file is written first (atomically): a record never points at a file
    that is not there."""
    raw = _ann(portal).get(KEY)
    data = json.loads(raw) if raw else {}
    recs = list(data.get(method_id) or [])
    rev = rev or next_number(recs)
    folder = revisions_dir(method_id)
    if not os.path.isdir(folder):
        os.makedirs(folder)
    path = os.path.join(folder, file_name(rev))
    if os.path.exists(path):
        raise ValueError(u"Revision %s of %s already exists on disk." % (rev, method_id))
    tmp = path + ".tmp"
    with io.open(tmp, "wb") as fh:
        fh.write(pdf_bytes)
    os.rename(tmp, path)
    rec = {"rev": rev, "issued_at": when, "issued_by": who, "reason": reason or u"",
           "fingerprint": fingerprint_value, "file": file_name(rev)}
    recs.append(rec)
    data[method_id] = recs
    _ann(portal)[KEY] = json.dumps(data, sort_keys=True)
    return rec


def read_pdf(method_id, rev):
    path = os.path.join(revisions_dir(method_id), file_name(rev))
    with io.open(path, "rb") as fh:
        return fh.read()
