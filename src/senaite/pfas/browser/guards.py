# -*- coding: utf-8 -*-
"""Workflow guards (SENAITE IGuardAdapter: guard_handler asks every named
adapter before offering a transition; False blocks it).

SampleMethodGuard: a sample whose method cannot be identified is not
published, pre-published or re-published -- the
certificate refuses it for the same reason (sample_method.identify).
ReportTemplateGuard: nothing is published before a reporting-template
revision is issued (report_templates).
QCStandardsGuard: a sample that was run but whose surrogate / internal-
standard verdicts are missing (a run stored before they were kept, or
nothing judged), or whose run was judged unrounded or with another rounding
rule than its certificate prints with, is not published until
the run is reprocessed (coa_qc_standards.BLOCKS_PUBLISHING).
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


@implementer(IGuardAdapter)
class ReportTemplateGuard(object):
    """No certificate before a reporting-template revision is issued: every
    certificate records the revision it was drawn from."""

    def __init__(self, context):
        self.context = context

    def guard(self, transition):
        if transition not in PUBLISH_TRANSITIONS:
            return True
        try:
            from bika.lims import api
            from senaite.pfas.report_templates import issued_snapshot
            snap, _rev = issued_snapshot(api.get_portal())
        except Exception as exc:                            # noqa: BLE001
            logger.error("ReportTemplateGuard: %s", exc)
            return False
        return snap is not None


@implementer(IGuardAdapter)
class LabAddressGuard(object):
    """No certificate without the laboratory's address (ISO/IEC 17025
    7.8.2.1 b; lab, 2026-10-09). The accreditation statement is optional."""

    def __init__(self, context):
        self.context = context

    def guard(self, transition):
        if transition not in PUBLISH_TRANSITIONS:
            return True
        try:
            from bika.lims import api
            from senaite.pfas.print_settings import get_print_settings
            return bool((get_print_settings(api.get_portal()).get("lab_address") or u"").strip())
        except Exception as exc:                            # noqa: BLE001
            logger.error("LabAddressGuard: %s", exc)
            return False


@implementer(IGuardAdapter)
class QCStandardsGuard(object):
    """A certificate never prints an empty surrogate / internal-standard
    table for a sample that was run. A sample with no run
    at all prints the table's no-data line and is not held here."""

    def __init__(self, context):
        self.context = context

    def guard(self, transition):
        if transition not in PUBLISH_TRANSITIONS:
            return True
        try:
            from senaite.pfas import coa_qc_standards
            from senaite.pfas.browser.coa_sections import qc_standards_state
            state = qc_standards_state(self.context)
        except Exception as exc:                            # noqa: BLE001
            logger.error("QCStandardsGuard: %s", exc)
            return False
        return state not in coa_qc_standards.BLOCKS_PUBLISHING

