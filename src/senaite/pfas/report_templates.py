# -*- coding: utf-8 -*-
"""The certificate template as a controlled document (DECISIONS 2026-10-02
"Extraction UI, Data Review, reporting template").

A revision freezes everything the Certificate of Analysis is drawn from:

    print_settings   the lab's Print Settings (identity, accreditation,
                     statements, sign-off, quality-system statement inputs)
    report_formats   each method's Reporting-tab format {method: {...}}
    layout           a hash of the certificate layout files

A Manager issues a revision (number, who, when, note). Certificates are
rendered from the ISSUED revision, never from the live draft, and each
issued certificate records the revision it used. "Unissued changes" = the
live draft's fingerprint differs from the issued one; what differs is listed.

    snapshot(print_settings, report_formats, layout) -> dict
    fingerprint(snap) -> str
    changes(issued_snap, draft_snap) -> ["what differs", ...]
    status(records, draft_fp) -> {"rev", "issued_at", "unissued", "none_issued"}
    next_number(records) / current(records)

Pure apart from the storage shell at the end. Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import copy
import hashlib
import json

KEY = "senaite.pfas.report_template_revisions"
_STAMPS = ("updated_at", "updated_by")


def snapshot(print_settings, report_formats, layout):
    ps = copy.deepcopy(print_settings or {})
    for k in _STAMPS:
        ps.pop(k, None)
    return {"print_settings": ps,
            "report_formats": copy.deepcopy(report_formats or {}),
            "layout": layout or u""}


def fingerprint(snap):
    raw = json.dumps(snap or {}, sort_keys=True, default=lambda o: u"%s" % o)
    if not isinstance(raw, bytes):
        raw = raw.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def changes(issued, draft):
    """What the draft changes, in words a Manager can check before issuing."""
    issued, draft = issued or {}, draft or {}
    out = []
    a, b = issued.get("print_settings") or {}, draft.get("print_settings") or {}
    for k in sorted(set(a) | set(b)):
        if a.get(k) != b.get(k):
            out.append(u"Print setting %s" % k)
    fa, fb = issued.get("report_formats") or {}, draft.get("report_formats") or {}
    for m in sorted(set(fa) | set(fb)):
        if fa.get(m) != fb.get(m):
            out.append(u"Report format of %s" % m)
    if issued.get("layout") != draft.get("layout"):
        out.append(u"Certificate layout (the template files changed)")
    return out


def next_number(records):
    return max([r.get("rev", 0) for r in records or []] or [0]) + 1


def current(records):
    recs = sorted(records or [], key=lambda r: r.get("rev", 0))
    return recs[-1] if recs else None


def status(records, draft_fp):
    cur = current(records)
    if cur is None:
        return {"rev": None, "issued_at": u"", "unissued": True, "none_issued": True}
    return {"rev": cur["rev"], "issued_at": cur.get("issued_at") or u"",
            "unissued": cur.get("fingerprint") != draft_fp, "none_issued": False}


# ── storage shell (portal annotation; one small list) ─────────────────────────

def _ann(portal):
    from zope.annotation.interfaces import IAnnotations
    return IAnnotations(portal)


def records(portal):
    try:
        return json.loads(_ann(portal).get(KEY) or u"[]")
    except (TypeError, ValueError):
        return []


def issue(portal, snap, who, when, note):
    """Issue the draft as the next revision; returns the record."""
    recs = records(portal)
    rec = {"rev": next_number(recs), "issued_at": when, "issued_by": who,
           "note": note or u"", "fingerprint": fingerprint(snap), "snapshot": snap}
    recs.append(rec)
    _ann(portal)[KEY] = json.dumps(recs)
    return rec


def issued_snapshot(portal):
    cur = current(records(portal))
    return (cur or {}).get("snapshot"), (cur or {}).get("rev")
