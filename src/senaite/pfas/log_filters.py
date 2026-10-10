# -*- coding: utf-8 -*-
"""Log noise from core that carries no information.

Core's bika.lims.workflow.doActionFor logs, for every transition a guard
refuses, a WARNING naming the transition and the object, then an ERROR with
CMFCore's untranslated message id: "No workflow provides the '${action_id}'
action." Data Review's release cascade submits each analysis, and core then
tries the worksheet and sample after each one (refused until the last has
moved): about three such pairs per analysis, every release. The WARNING
says what happened and is kept; the ERROR line -- that exact, unexpanded
text, on the senaite.core logger only -- is dropped (lab, 2026-10-09).
Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import logging

NOISE = u"No workflow provides the '${action_id}' action."


class DropUnexpandedWorkflowError(logging.Filter):
    def filter(self, record):
        try:
            msg = record.getMessage()
        except Exception:                                   # noqa: BLE001
            return True
        return not (record.levelno == logging.ERROR and msg.strip() == NOISE)


def install():
    """Idempotent: one filter on the senaite.core logger."""
    log = logging.getLogger("senaite.core")
    if not any(isinstance(f, DropUnexpandedWorkflowError) for f in log.filters):
        log.addFilter(DropUnexpandedWorkflowError())
