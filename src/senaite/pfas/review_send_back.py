# -*- coding: utf-8 -*-
"""Verify sends a submitted worksheet back to the analyst.

The verifier gives a reason, typed or chosen from the lab's list (vocab_store
"send_back_reasons") and edited; the worksheet goes back to open by core's own
worksheet "retract" (to_be_verified -> open: every analysis is retracted,
keeping its value, and a retest without a result is added to the same
worksheet). The analyst corrects what is wrong and submits again. Unlike
Reject, nothing goes to a new worksheet.

The record, one worksheet annotation (KEY), is an append-only log in the
shape the extraction corrections' send back uses:

    {"log": [{"id": "SB-1", "action": "send_back", "to": "data_review",
              "reason", "by", "at", "cleared", "retracted"}, ...]}

"interims" (only when there were any) names the interim certificates the
send back marked superseded by the next certificate
(interim_certificates.mark_superseded). "cleared" names the sign-offs the
send back cleared (the identity
correction's reset rule, injection_identity.reset_signoffs: the results
and the run are filed and judged again); "retracted" how many analyses
core retracted. The record is minimal by the owner's decision (2026-11-25): when, why and
who (the audit trail, not a signature). The e-signature ledger is not
written: a signature made before stays as it is, and the send back is its
own event. A worksheet with no run file is sent back too: it reopens, the
retests stay empty until a run is uploaded.

Release waits (pending) until the run is filed again after the latest send
back: the retests hold no result before then.

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import copy
import json

import six

KEY = "senaite.pfas.review_send_back"

SEND_BACK = "send_back"
# where a worksheet sent back from Verify returns to
TO_DATA_REVIEW = "data_review"
TO_LABELS = {TO_DATA_REVIEW: "Data Review"}
# the words, shared with the extraction corrections' send back
SEND_BACK_LABEL, SENT_BACK_LABEL = "Send back", "Sent back"

SUBMITTED = "to_be_verified"

NO_REASON = "A send back needs a reason. Nothing was changed."
NOT_VERIFIER = "Only a Lab Manager sends a worksheet back."
AUTOMATED = "An automated account does not send a worksheet back."
NOT_SUBMITTED = "Only a worksheet waiting for verification is sent back."

# the checklist items by their labels, for the history
ITEM_LABELS = {"coc": "Chain of Custody", "final_data": "Final Data Summary",
               "instrument_report": "Instrument Report"}
from senaite.pfas.injection_identity import RESULT_SIGNOFF_LABELS as _RESULT_LABELS  # noqa: E402
ITEM_LABELS.update(_RESULT_LABELS)


def _text(value):
    if value is None:
        return ""
    if isinstance(value, six.binary_type):
        return value.decode("utf-8")
    return six.text_type(value).strip()


def empty():
    return {"log": []}


def load(raw):
    """The record from its stored JSON (or a dict); empty when unreadable."""
    if isinstance(raw, dict):
        data = raw
    else:
        try:
            data = json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            data = {}
    log = data.get("log") if isinstance(data, dict) else None
    return {"log": [dict(e) for e in log if isinstance(e, dict)] if isinstance(log, list) else []}


def dump(state):
    return json.dumps(load(state), sort_keys=True)


def refusal(reason, ws_state, is_manager, actor_kind):
    """Why the worksheet is not sent back, or None."""
    if actor_kind == "automated":
        return AUTOMATED
    if not is_manager:
        return NOT_VERIFIER
    if ws_state != SUBMITTED:
        return NOT_SUBMITTED
    if not _text(reason):
        return NO_REASON
    return None


def record(state, reason, who, when, cleared, retracted=0):
    """(new state, entry): the send back appended."""
    state = load(state)
    n = len([e for e in state["log"] if e.get("action") == SEND_BACK])
    entry = {"id": "SB-%d" % (n + 1), "action": SEND_BACK, "to": TO_DATA_REVIEW,
             "reason": _text(reason), "by": _text(who), "at": _text(when),
             "cleared": list(cleared or []), "retracted": int(retracted or 0)}
    state["log"].append(entry)
    return state, entry


def clear_submission(checklist):
    """The checklist with its submission cleared (submitted again after the
    fix); a copy, every item as it was."""
    cl = copy.deepcopy(checklist or {})
    cl["submitted_by"] = None
    cl["submitted_at"] = None
    return cl


def _instant(value):
    text = _text(value).replace(" UTC", "").replace(" ", "T")
    return text[:19]


def pending(state, filed_at):
    """True while the run has not been filed again since the latest send
    back (`filed_at`, when the run's QC was last written); never sent back,
    False."""
    sends = [e for e in load(state)["log"] if e.get("action") == SEND_BACK]
    if not sends:
        return False
    # a run never filed reads "" and is earlier than any send back
    return _instant(filed_at) <= _instant(sends[-1].get("at"))


def history(state):
    """Every send back, newest first, with its words."""
    out = []
    for e in reversed(load(state)["log"]):
        out.append(dict(e, change="{0} to {1}".format(SENT_BACK_LABEL,
                                                       TO_LABELS.get(e.get("to"), e.get("to") or "")),
                        cleared_text=", ".join(ITEM_LABELS.get(c.get("item"), c.get("item") or "")
                                               for c in e.get("cleared") or [])))
    return out


def record_part(state):
    """The batch record's send-back part: every entry, oldest first; []
    without one (the record's hash is then unchanged)."""
    out = []
    for e in load(state)["log"]:
        part = dict((k, e.get(k)) for k in ("id", "action", "to", "reason", "by", "at", "cleared",
                                             "retracted"))
        if e.get("interims"):
            part["interims"] = list(e["interims"])
        out.append(part)
    return out
