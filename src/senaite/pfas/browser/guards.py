# -*- coding: utf-8 -*-
"""Workflow guards (SENAITE IGuardAdapter: guard_handler asks every named
adapter before offering a transition; False blocks it).

SampleMethodGuard: a sample whose method cannot be identified is not
published, pre-published or re-published -- the
certificate refuses it for the same reason (sample_method.identify).
ReportTemplateGuard: nothing is published before a reporting-template
revision is issued (report_templates).
CertificateLayoutGuard: nothing is published while the issued revision
carries no certificate layout (report_templates.certificate_layout_problem).
QCStandardsGuard: a sample that was run but whose surrogate / internal-
standard verdicts are missing (a run stored before they were kept, or
nothing judged), or whose run was judged unrounded or with another rounding
rule than its certificate prints with, is not published until
the run is reprocessed (coa_qc_standards.BLOCKS_PUBLISHING).
ReceiptComplianceGuard: a compliance sample received out of compliance with
its method is not published; a resample is requested (receipt_compliance).
Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import logging

from bika.lims.interfaces import IGuardAdapter
from zope.interface import implementer

logger = logging.getLogger("senaite.pfas.guards")

PUBLISH_TRANSITIONS = ("publish", "prepublish", "republish")


@implementer(IGuardAdapter)
class EntryRightsGuard(object):
    """Submitting, verifying, retracting or rejecting a result, and issuing a
    certificate, need a Lab Contact with initials and a signature
    (entry_rights.py)."""

    def __init__(self, context):
        self.context = context

    def guard(self, transition):
        from senaite.pfas import entry_rights
        if transition not in entry_rights.ANALYSIS_TRANSITIONS + entry_rights.SAMPLE_TRANSITIONS:
            return True
        try:
            from senaite.pfas.browser.staff import may_enter
            return may_enter()
        except Exception as exc:                            # noqa: BLE001
            # an error here must not silently allow what it exists to block
            logger.error("EntryRightsGuard: %s", exc)
            return False


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
class CertificateLayoutGuard(object):
    """No certificate while the issued revision carries no certificate
    layout: a certificate is published only from an issued layout."""

    def __init__(self, context):
        self.context = context

    def guard(self, transition):
        if transition not in PUBLISH_TRANSITIONS:
            return True
        try:
            from bika.lims import api
            from senaite.pfas.report_templates import certificate_layout_problem, issued_snapshot
            snap, _rev = issued_snapshot(api.get_portal())
        except Exception as exc:                            # noqa: BLE001
            # an error here must not silently allow what it exists to block
            logger.error("CertificateLayoutGuard: %s", exc)
            return False
        return certificate_layout_problem(snap) is None


@implementer(IGuardAdapter)
class LabAddressGuard(object):
    """No certificate without the laboratory's address (ISO/IEC 17025
    7.8.2.1 b). The accreditation statement is optional."""

    def __init__(self, context):
        self.context = context

    def guard(self, transition):
        if transition not in PUBLISH_TRANSITIONS:
            return True
        try:
            from bika.lims import api
            from senaite.pfas.print_settings import get_print_settings
            from senaite.pfas.report_templates import issued_snapshot, lab_address_problem
            portal = api.get_portal()
            # the address the certificate prints: the issued revision's
            snap, rev = issued_snapshot(portal)
            return lab_address_problem(snap, rev, get_print_settings(portal)) is None
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



def receipt_hold(sample):
    """The receipt breaches that hold a compliance sample, or []."""
    from senaite.pfas import coc_records as cr
    from senaite.pfas import receipt_compliance as rc
    from bika.lims import api
    fld = sample.getField("ComplianceSample")
    if not (fld and fld.get(sample)):
        return []
    num_fld = sample.getField("CoCNumber")
    num = (num_fld.get(sample) if num_fld else u"") or u""
    rec = cr.load(api.get_portal(), num) if num else {}
    flags = ((rec or {}).get("receipt") or {}).get("flags") or []
    found = rc.breaches(flags, (api.get_id(sample), sample.getClientSampleID()))
    return found if rc.resample_required(True, found) else []


@implementer(IGuardAdapter)
class ReceiptComplianceGuard(object):
    """A compliance sample received out of compliance with its method is
    held from publishing: re-running it cannot change how it arrived, so a
    resample is requested instead (rc.resample_required)."""

    def __init__(self, context):
        self.context = context

    def guard(self, transition):
        if transition not in PUBLISH_TRANSITIONS:
            return True
        try:
            return not receipt_hold(self.context)
        except Exception as exc:                            # noqa: BLE001
            logger.error("ReceiptComplianceGuard: %s", exc)
            return False
