# -*- coding: utf-8 -*-
"""Who may enter data and review: a person with a Lab
Contact, initials and an uploaded signature. One check, used by every data
entry and review action: the PFAS pages that record or review data (the
wall, perms.keep_clients_out) and core's result submit / verify and
certificate publishing (guards.EntryRightsGuard). There is no override.
An automation account (the PFASAutomation group) is a person for every
page and action but the worker's own requests (WORKER_VIEWS); it is never
given a Lab Contact or a signature. Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

OK, NO_CONTACT, NO_INITIALS, NO_SIGNATURE = "ok", "no_contact", "no_initials", "no_signature"
# the words; the page draws the mark beside them (icons.py): a tick for
# Allowed, the warning triangle for what is missing
LABELS = {OK: u"Allowed", NO_CONTACT: u"No Lab Contact",
          NO_INITIALS: u"No initials", NO_SIGNATURE: u"No signature"}
REFUSAL = (u"Data entry and review need a Lab Contact with initials and a signature. "
           u"A lab manager sets them on Settings > People & Roles.")

# PFAS pages whose POSTs record or review data
DATA_ENTRY_VIEWS = frozenset((
    "pfas-extraction-guide", "pfas-extraction-batch", "pfas-ws-stage",
    "pfas-data-review", "pfas-manual-integration", "pfas-dilution-result",
    "pfas-above-range", "pfas-coc-receive", "pfas-homogenisation",
    "pfas-extraction-corrections",
))
# Of those, the requests the pipeline worker makes with its own account: an
# automation account passes the check on these and nowhere else.
WORKER_VIEWS = frozenset(("pfas-dilution-result", "pfas-above-range"))
# core transitions that enter or review a result, or issue a certificate
ANALYSIS_TRANSITIONS = ("submit", "verify", "retract", "reject")
SAMPLE_TRANSITIONS = ("publish", "prepublish", "republish")


def status(has_contact, initials, has_signature):
    if not has_contact:
        return NO_CONTACT
    if not (initials or u"").strip():
        return NO_INITIALS
    if not has_signature:
        return NO_SIGNATURE
    return OK


def exempt(view, automation):
    """True when an automation account's request to `view` needs no Lab
    Contact, initials or signature: only a page of WORKER_VIEWS."""
    return bool(automation) and view in WORKER_VIEWS
