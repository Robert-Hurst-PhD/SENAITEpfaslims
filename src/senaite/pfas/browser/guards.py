# -*- coding: utf-8 -*-
"""Workflow guards (SENAITE IGuardAdapter: guard_handler asks every named
adapter before offering a transition; False blocks it).

SampleMethodGuard: a sample whose method cannot be identified is not
published, pre-published or re-published (DECISIONS 2026-10-02) -- the
certificate refuses it for the same reason (sample_method.identify).
Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import logging

from bika.lims.interfaces import IGuardAdapter
from zope.interface import implementer

logger = logging.getLogger("senaite.pfas.guards")

PUBLISH_TRANSITIONS = ("publish", "prepublish", "republish")


@implementer(IGuardAdapter)
class SampleMethodGuard(object):

    def __init__(self, context):
        self.context = context

    def guard(self, transition):
        if transition not in PUBLISH_TRANSITIONS:
            return True
        try:
            from senaite.pfas.sample_method import identify
            _method, problem = identify(self.context)
        except Exception as exc:                            # noqa: BLE001
            # an error here must not silently allow what it exists to block
            logger.error("SampleMethodGuard: %s", exc)
            return False
        return not problem
