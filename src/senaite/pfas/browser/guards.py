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
ReportPackageGuard: a sample whose newest certificate, not yet issued,
waits for its package (building, failed, or none at a tier that needs one)
or, with no package, for its seal (pending or failed), is not published,
by Send or by any other path (edd_email.report_refusal, seal_hold).
SignatureGuard: a sample is not published without the publisher's own
signature, given on Data Review before the certificate is generated; before
its run is verified (prepublish) only on an interim signature; nor while a
QC hold applies at the moment of issue (controlled_publications.qc_hold_refusal).
A refusal of an issue a workflow action asked for (core's Publish on the
reports listing) is said in the page's messages (tell_refusal), as Send
says it.
WorksheetMethodGuard: an analysis goes on a worksheet only when its
sample's method is the worksheet's Method (worksheet_samples).
Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import logging

from bika.lims.interfaces import IGuardAdapter
from zope.interface import implementer

logger = logging.getLogger("senaite.pfas.guards")

PUBLISH_TRANSITIONS = ("publish", "prepublish", "republish")
# every transition that issues a certificate: the ones above and the ones
# the register records an issue on (controlled_publications)
PACKAGE_TRANSITIONS = ("publish", "prepublish", "publish_immediately", "republish")
# the transitions the register records an issue on: each one is signed;
# prepublish issues an interim certificate before verification
SIGNATURE_TRANSITIONS = ("publish", "publish_immediately", "republish", "prepublish")


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


def seal_hold(report):
    """"Seal pending" or "Seal failed: <reason>" while the worker has not
    sealed a certificate stored with no package; else None. A package is
    sealed by its own build, and its record speaks for it."""
    from senaite.pfas import report_packages
    return report_packages.seal_refusal(report_packages.seal_record(report))


def package_hold(reports, issued, refusal):
    """(report, why) when the sample's newest certificate (the first of
    `reports`, newest first) is not yet issued (`issued(report)`) and may
    not be sent (`refusal(report)`, the refusal Send gives) or is not yet
    sealed (seal_hold); else None. Only the newest counts: it is the one a
    publication is issued in, and older drafts are superseded by it. An
    issued newest certificate holds nothing: its package and its seal were
    settled when it was issued."""
    if not reports:
        return None
    newest = reports[0]
    if issued(newest):
        return None
    # the bytes the authoriser's signature binds to are the sealed ones
    why = refusal(newest) or seal_hold(newest)
    return (newest, why) if why else None


@implementer(IGuardAdapter)
class ReportPackageGuard(object):
    """A certificate goes out only with its package, sealed: no path that
    issues it (Send, the reports listing's Publish, a republish) publishes
    the sample while its newest certificate, not yet issued, has its
    package building or failed, or needs a package and has no record, or,
    with no package, waits for its seal or its seal failed. Older drafts
    are superseded and not judged."""

    def __init__(self, context):
        self.context = context

    def guard(self, transition):
        if transition not in PACKAGE_TRANSITIONS:
            return True
        from ZODB.POSException import ConflictError
        try:
            from bika.lims import api
            from senaite.pfas.browser.controlled_publications import certificate_reports, report_issued
            from senaite.pfas.browser.edd_email import report_refusal
            held = package_hold(certificate_reports(self.context), report_issued, report_refusal)
        except ConflictError:
            raise                                           # Zope retries the request
        except Exception as exc:                            # noqa: BLE001
            # an error here must not silently allow what it exists to block
            logger.error("ReportPackageGuard: %s", exc)
            return False
        if held:
            # the listing that offers the transition may show no reason
            logger.info("ReportPackageGuard: %s is not published (%s): %s: %s",
                        api.get_id(self.context), transition, api.get_id(held[0]), held[1])
            return False
        return True


@implementer(IGuardAdapter)
class SignatureGuard(object):
    """A certificate is issued only with its authoriser's signature: every
    transition that issues one needs the publisher's own pending signature
    on the sample, given on Data Review's Issue certificate card; while the
    current revision is interim, another interim needs a reason; and no QC
    hold may apply at the moment of issue, as Approve Release would refuse
    (controlled_publications.signature_refusal, which Send shows)."""

    def __init__(self, context):
        self.context = context

    def guard(self, transition):
        if transition not in SIGNATURE_TRANSITIONS:
            return True
        from ZODB.POSException import ConflictError
        try:
            from senaite.pfas.browser.controlled_publications import _current_userid, signature_refusal
            why = signature_refusal(self.context, _current_userid())
        except ConflictError:
            raise                                           # Zope retries the request
        except Exception as exc:                            # noqa: BLE001
            # an error here must not silently allow what it exists to block
            logger.error("SignatureGuard: %s", exc)
            return False
        if why:
            logger.info("SignatureGuard: not published (%s): %s", transition, why)
            try:
                tell_refusal(self.context, why)
            except ConflictError:
                raise                                       # Zope retries the request
            except Exception:                               # noqa: BLE001
                # saying why never changes the verdict
                logger.warning("SignatureGuard: the refusal was not said", exc_info=True)
            return False
        return True


# the request keys core's workflow_action view names the action by: a
# request carrying one performs a transition; a page drawing its buttons
# carries none
WORKFLOW_ACTION_KEYS = ("workflow_action", "workflow_action_id")
# what tell_refusal has said in this request
TOLD_KEY = "senaite.pfas.guards.told"


def tell_refusal(sample, why):
    """Say why an issue a workflow action asked for is refused, as Send says
    it ("<sample id>: why"), in the page's messages: core's Publish on the
    reports listing says only that nothing was published. Said once a
    request; nothing is said where no workflow action is asked (a listing
    drawing its buttons). True when said."""
    from bika.lims import api
    request = api.get_request()
    if request is None or not any(request.get(k) for k in WORKFLOW_ACTION_KEYS):
        return False
    from Products.statusmessages.interfaces import IStatusMessage
    from zope.annotation.interfaces import IAnnotations
    annotations = IAnnotations(request)
    told = annotations.get(TOLD_KEY)
    if told is None:
        told = annotations[TOLD_KEY] = []
    text = u"{0}: {1}".format(api.get_id(sample), why)
    if text in told:
        return False
    told.append(text)
    IStatusMessage(request).add(text, type=u"warning")
    return True


def _request_worksheet(request):
    """The worksheet an assign is asked from, as core's assign guard finds
    it: the one core's addAnalysis names (ws_uid), else one the request
    traversed. None outside a worksheet."""
    from bika.lims import api
    uid = request.get("ws_uid", "") if request is not None else ""
    if uid:
        obj = api.get_object_by_uid(uid, None)
        if getattr(obj, "portal_type", None) == "Worksheet":
            return obj
    for obj in (request.get("PARENTS", []) if request is not None else []) or []:
        if getattr(obj, "portal_type", None) == "Worksheet":
            return obj
    return None


@implementer(IGuardAdapter)
class WorksheetMethodGuard(object):
    """An analysis goes on a worksheet only when its sample's method is the
    worksheet's Method (worksheet_samples.assign_allowed): every way an
    analysis is assigned asks this. Asked once per row of a listing, so the
    worksheet's and each sample's method are read once per request."""

    CACHE = "_pfas_worksheet_method_guard"

    def __init__(self, context):
        self.context = context

    def guard(self, transition):
        if transition != "assign":
            return True
        from ZODB.POSException import ConflictError
        try:
            from bika.lims import api
            from senaite.pfas import worksheet_samples as wsm
            from senaite.pfas.method_bridge import profile_id_for_method
            request = api.get_request()
            ws = _request_worksheet(request)
            if ws is None:
                return True                 # core's own guard refuses an assign outside a worksheet
            cache = request.get(self.CACHE) if request is not None else None
            if cache is None:
                cache = {"ws": {}, "sample": {}, "profiles": None}
                if request is not None:
                    request.set(self.CACHE, cache)
            ws_uid = api.get_uid(ws)
            if ws_uid not in cache["ws"]:
                m = ws.getMethod()
                cache["ws"][ws_uid] = profile_id_for_method(m) if m is not None else u""
            ws_method = cache["ws"][ws_uid]
            if not ws_method:
                return True
            sample = self.context.getRequest()
            s_uid = api.get_uid(sample)
            if s_uid not in cache["sample"]:
                if cache["profiles"] is None:
                    cache["profiles"] = wsm.profile_methods(api.get_portal())
                cache["sample"][s_uid] = wsm.sample_method_of(api.get_portal(), sample, cache["profiles"])[0]
            return wsm.assign_allowed(ws_method, cache["sample"][s_uid])
        except ConflictError:
            raise                                           # Zope retries the request
        except Exception as exc:                            # noqa: BLE001
            # an error here must not silently allow what it exists to block
            logger.error("WorksheetMethodGuard: %s", exc)
            return False


@implementer(IGuardAdapter)
class ReopenGuard(object):
    """Only Send back reopens a submitted or verified worksheet
    (senaite.pfas.reopen_guard): the worksheet's retract, and an analysis's
    retract on such a worksheet, run only inside a request Send back or the
    identity retraction marked. Core offers a transition only when this
    passes, so the plain Retract is hidden, and a URL firing it refused."""

    def __init__(self, context):
        self.context = context

    def guard(self, transition):
        if transition != "retract":
            return True
        from bika.lims import api
        from senaite.pfas import reopen_guard
        try:
            request = api.get_request()
            if getattr(self.context, "portal_type", "") == "Worksheet":
                kind, state = "worksheet", api.get_review_status(self.context)
            else:
                ws = self.context.getWorksheet()
                kind, state = "analysis", (api.get_review_status(ws) if ws is not None else None)
            return reopen_guard.allowed(kind, transition, state, reopen_guard.marked(request))
        except Exception as exc:                            # noqa: BLE001
            # fails closed: a reopen not understood is not made
            logger.warning("reopen guard: %s", exc)
            return False

