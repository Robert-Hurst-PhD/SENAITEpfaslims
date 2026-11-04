# -*- coding: utf-8 -*-
"""The certificate template as a controlled document.

A revision freezes everything the Certificate of Analysis is drawn from:

    print_settings   the lab's Print Settings (identity, accreditation,
                     statements, sign-off, quality-system statement inputs)
    report_formats   each method's Reporting-tab format {method: {...}}
    format_defaults  the built-in default of each format setting added after
                     revisions were first issued (report_format
                     .recorded_defaults); a revision without it prints by
                     the rule in force before (issued_defaults). Bookkeeping
                     of the code, like the layout hash: not fingerprinted
    layout           a hash of the certificate layout files

A Manager issues a revision (number, who, when, note). Certificates are
rendered from the ISSUED revision, never from the live draft, and each
issued certificate records the revision it used. "Unissued changes" = the
live draft's fingerprint differs from the issued one; what differs is listed.

    snapshot(print_settings, report_formats, layout, designed=None) -> dict
        designed: the designed certificate layout (pdfme template),
        present ONLY when the lab has one -- an absent design adds no key, so
        the fingerprint of an install without one is unchanged
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


def _report_format():
    from senaite.pfas import report_format
    return report_format


# not part of what a revision prints differently by: see the module docstring
_NOT_FINGERPRINTED = ("format_defaults",)


def snapshot(print_settings, report_formats, layout, designed=None):
    ps = copy.deepcopy(print_settings or {})
    for k in _STAMPS:
        ps.pop(k, None)
    # no logo adds no fingerprint key, so such an install's fingerprint is
    # unchanged
    if not ps.get("logo_sha"):
        ps.pop("logo_sha", None)
    snap = {"print_settings": ps,
            "report_formats": copy.deepcopy(report_formats or {}),
            "layout": layout or u"",
            "format_defaults": _report_format().recorded_defaults()}
    if designed is not None:
        snap["designed_layout"] = copy.deepcopy(designed)
    return snap


def designed_layout(snap):
    """The designed certificate layout a revision carries, or None (the HTML
    certificate)."""
    return (snap or {}).get("designed_layout")


# the owner's rule: a certificate is published only from an issued
# certificate layout (the standard certificate is no fallback)
LAYOUT_NEEDED = u"Issue a certificate layout in Reporting Setup first."


def certificate_layout_problem(snap):
    """Why no certificate can be published from the issued revision `snap`
    (None when nothing is issued): it carries no certificate layout. None
    when it does. A draft layout is not issued and does not count."""
    return None if designed_layout(snap) is not None else LAYOUT_NEEDED


def fingerprint(snap):
    snap = dict((k, v) for k, v in (snap or {}).items() if k not in _NOT_FINGERPRINTED)
    raw = json.dumps(snap, sort_keys=True, default=lambda o: u"%s" % o)
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
    if issued.get("designed_layout") != draft.get("designed_layout"):
        if draft.get("designed_layout") is None:
            out.append(u"Designed certificate layout withdrawn (back to the standard certificate)")
        else:
            out.append(u"Designed certificate layout")
    return out


def printed_settings(snap, live):
    """The Print Settings a certificate prints: the issued revision's, or the
    live ones when no revision is issued (publishing is then held by its own
    guard)."""
    if snap is None:
        return dict(live or {})
    return dict(snap.get("print_settings") or {})


def lab_address_problem(snap, rev, live):
    """Why a certificate would print no laboratory address, or None. An
    address entered on the Laboratory page reaches certificates only with
    the next issued revision."""
    if (printed_settings(snap, live).get("lab_address") or u"").strip():
        return None
    if snap is not None and ((live or {}).get("lab_address") or u"").strip():
        return (u"the laboratory address is not in the issued reporting template "
                u"(revision %s): issue a new revision (Reporting Template) to carry "
                u"the address entered on the Laboratory page" % rev)
    return u"the laboratory address is not set (Laboratory)"


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
    sha = (snap.get("print_settings") or {}).get("logo_sha")
    if sha:
        # the logo is kept with the revision: a later site logo does not
        # change what it prints
        from senaite.pfas import lab_identity
        lab_identity.keep_logo_version(portal, sha)
    return rec


def certificate_format(snap, method_id, profile, matrix, live_settings):
    """(merged settings, method x matrix format) the certificate prints one
    sample with: the issued revision's print settings and report formats when
    one is issued, else the live settings and the profile's own format. An
    issued revision prints as it did when issued: a setting it does not
    record reads the rule in force then (report_format.issued_defaults)."""
    report_format = _report_format()
    defaults = None
    if snap is not None:
        settings = dict(snap.get("print_settings") or {})
        source = {report_format.KEY: (snap.get("report_formats") or {}).get(method_id) or {}}
        defaults = report_format.issued_defaults(snap.get("format_defaults"))
    else:
        settings, source = dict(live_settings or {}), profile
    fmt = report_format.resolve(source, matrix, defaults)
    merged = dict(settings)
    merged.update(fmt)
    merged.update(report_format.rules(defaults))
    return merged, fmt


def issued_snapshot(portal):
    cur = current(records(portal))
    return (cur or {}).get("snapshot"), (cur or {}).get("rev")
