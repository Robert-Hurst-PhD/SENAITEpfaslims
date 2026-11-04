# -*- coding: utf-8 -*-
"""Who may enter data and review: a person with a Lab
Contact, initials and an uploaded signature. One check, used by every data
entry and review action: the PFAS pages that record or review data (the
wall, perms.keep_clients_out) and core's result submit / verify and
certificate publishing (guards.EntryRightsGuard). There is no override.
Automation accounts are an open question and are treated as people. Pure;
Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

OK, NO_CONTACT, NO_INITIALS, NO_SIGNATURE = "ok", "no_contact", "no_initials", "no_signature"
LABELS = {OK: u"✓ Allowed", NO_CONTACT: u"✗ No Lab Contact",
          NO_INITIALS: u"✗ No initials", NO_SIGNATURE: u"✗ No signature"}
REFUSAL = (u"Data entry and review need a Lab Contact with initials and a signature. "
           u"A lab manager sets them on Settings > People & Roles.")

# PFAS pages whose POSTs record or review data
DATA_ENTRY_VIEWS = frozenset((
    "pfas-logbook-dynamic", "pfas-prep-logbooks",
    "pfas-extraction-guide", "pfas-extraction-batch", "pfas-ws-stage",
    "pfas-data-review", "pfas-manual-integration", "pfas-dilution-result",
    "pfas-coc-receive", "pfas-homogenisation",
))
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
