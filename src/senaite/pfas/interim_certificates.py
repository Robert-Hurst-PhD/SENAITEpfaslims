# -*- coding: utf-8 -*-
"""Interim certificates released at Submit.

A client whose reporting settings take interim certificates
(edd_store "interim_certificates") gets one when the Analyst submits the
run for verification: Submit's sign dialog signs the certificate as
released interim, the signature waits on the client's samples, and the
certificate is generated and issued through the issue path every
certificate takes (core's prepublish, signed and recorded like a publish).
The final follows once the run is verified, and supersedes it.

Submit is never held for an interim: when one cannot be released the run
is submitted without it, and the reason says why. Asked before Submit:

    why_not(tiers, can_issue, sign_problems)  the first reason, or None

where `tiers` is [(client name, tier name, needs a package)] of the
interim clients' samples, `can_issue` whether the signer may generate and
send certificates at all (the publisher and the e-mail form), and
`sign_problems` why they may not sign as released interim, apart from the
credential the dialog asks. The Interim release right is the authority to
issue the interim: its signer needs no Publisher role
(browser/interim_release.py).

Pure: Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

# the client setting, on Client reporting
SETTING = "interim_certificates"

NO_INTERIM = u"No interim certificate: %s"
# a package is built only from a verified run (its parts are the reviewed
# ones), so a tier that needs one has no interim
NEEDS_PACKAGE = u"%s reports at %s, which needs a package, built only once the run is verified."
NO_TIER = u"%s reports at a certificate tier the issued catalogue does not hold."
# what generating and sending a certificate ask of the signer: core's
# Manage Analysis Requests (the publisher and the e-mail form), which the
# Analyst role already gives; a signer without it holds none of the roles
# that give it
CANNOT_ISSUE = (u"you may not generate certificates: your roles do not give the Manage Analysis "
                u"Requests permission that generating and sending them need.")
SIGNED = u"Interim certificate signed: issue it from the certificate card."


def why_not(tiers, can_issue, sign_problems):
    """The first reason no interim certificate is released at this Submit,
    or None when one is. A tier that needs a package speaks first: no
    right or role changes that."""
    for client, tier_name, needs_package in tiers or []:
        if tier_name is None:
            return NO_TIER % client
        if needs_package:
            return NEEDS_PACKAGE % (client, tier_name)
    if not can_issue:
        return CANNOT_ISSUE
    problems = [p for p in (sign_problems or []) if p]
    if problems:
        return u" ".join(problems)
    return None


def note(why):
    """What Submit says when no interim is released."""
    return NO_INTERIM % why


# ── an interim issued before Verify sent the worksheet back ─────────────────
# The interim stays on record, signed as issued; the next certificate of
# the sample supersedes it, carries why, and its e-mail tells the client.
# The sample's marks (MARKS_KEY) are an append-only list:
#   {"action": "mark", "report_id", "send_back", "reason", "by", "at"}
#   {"action": "superseded", "by_report", "at", "marks": [report_id]}

MARKS_KEY = "senaite.pfas.interim_superseded"
REISSUE_REASON = u"Supersedes interim certificate %s: the run was sent back at verification: %s"


def interim_to_mark(log):
    """The report id of the sample's current issue when it is an interim
    certificate (`log`: the publication log, newest first), else None."""
    if not log:
        return None
    top = log[0]
    return top.get("report_id") if top.get("interim") else None


def mark_superseded(marks, report_id, send_back, reason, by, at):
    """(marks, the mark appended)."""
    mark = {"action": "mark", "report_id": report_id, "send_back": send_back,
            "reason": reason or u"", "by": by or u"", "at": at or u""}
    return list(marks or []) + [mark], mark


def pending_marks(marks):
    """The marks no issue has superseded yet."""
    out = []
    for m in marks or []:
        if m.get("action") == "mark":
            out.append(m)
        elif m.get("action") == "superseded":
            out = []
    return out


def reissue_reason(marks):
    """The reissue reason the next certificate records."""
    return u"; ".join(REISSUE_REASON % (m.get("report_id"), m.get("reason")) for m in marks or [])


def resolve(marks, new_report_id, at):
    """(marks, carried): the next issue supersedes the pending marks; what
    its register entry carries ([{"report_id", "reason"}]); nothing
    appended when none is pending."""
    todo = pending_marks(marks)
    if not todo:
        return list(marks or []), []
    carried = [{"report_id": m.get("report_id"), "reason": m.get("reason")} for m in todo]
    done = {"action": "superseded", "by_report": new_report_id, "at": at or u"",
            "marks": [m.get("report_id") for m in todo]}
    return list(marks or []) + [done], carried

