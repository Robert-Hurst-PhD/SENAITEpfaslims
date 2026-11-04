# -*- coding: utf-8 -*-
"""
Raise an ISO 17025 deviation when a QC criterion was never configured.

A criterion the method does not define is not a QC failure — nothing was
judged. But it is also not nothing: a batch whose CCV window or calibration r²
is unset has been measured against no standard at all, and releasing it on
silence is exactly what §7.8.4's technical review exists to prevent.

The pipeline records such gaps on the batch (`batch.unconfigured`) and files
them as `unevaluated` rows in `qc_results`, which holds the Data Review gate.
This module turns that into something a reviewer can act on and a QAO is told
about: an open Deviation against the worksheet, carrying the exact criterion,
the method it belongs to and where to set it.

It is raised where the run arrives: the worker, after pushing a run's
results, asks @@pfas-unconfigured-deviation, which reads the QC Summary as
Data Review's gate reads it. A page never raises it: rendering is a read.

Reuses the deviation registry (worksheet link, risk score, sign-off workflow)
and the QAO named once in Print Settings for CoA attestation.

Python 2.7 (in-Plone add-on).
"""
from __future__ import absolute_import

import json
import logging

from zope.annotation.interfaces import IAnnotations

logger = logging.getLogger("senaite.pfas.qc_deviation")

# THE key for the deviation/CAR registry, defined here and imported everywhere
# else (browser/deviations.py, data_review): a second copy of the string can
# drift, and a deviation filed under it is invisible to every reader.
ANN_REGISTRY_KEY = u"senaite.pfas.deviations.registry"

# Marks the deviations this module owns, so a run delivered again updates the
# existing record rather than filing a duplicate.
SIGNATURE_KEY = "pfas_unconfigured_signature"

EVENT_TYPE = "QC criterion not configured"


def get_registry(portal):
    """The deviation/CAR registry as a list -- the one reader of the key."""
    raw = IAnnotations(portal).get(ANN_REGISTRY_KEY)
    return json.loads(raw) if raw else []


def save_registry(portal, data):
    """Persist the registry -- the one writer of the key."""
    IAnnotations(portal)[ANN_REGISTRY_KEY] = json.dumps(data)


def _next_id(registry):
    from senaite.pfas import lab_time
    year = lab_time.today().year
    prefix = "DEV-{0}-".format(year)
    seq = len([e for e in registry
               if str(e.get("dev_id", "")).startswith(prefix)]) + 1
    return "{0}{1:03d}".format(prefix, seq)


def _signature(worksheet_id, gaps):
    """Identity of a gap set, so the same gaps do not file twice."""
    parts = sorted(u"{0}|{1}".format(g.get("qc_type") or u"",
                                     g.get("reason") or u"")
                   for g in gaps)
    return u"{0}::{1}".format(worksheet_id, u"||".join(parts))


def _describe(gaps):
    lines = [u"The following QC criteria are not configured for this method, "
             u"so the corresponding checks could not be evaluated. Results are "
             u"held until each is set in Method Profiles.", u""]
    for gap in gaps:
        lines.append(u"• {0}: {1}".format(
            gap.get("qc_type") or u"(unknown check)",
            gap.get("reason") or u""))
    return u"\n".join(lines)


def ensure_deviation(portal, worksheet_id, gaps, filed_by=u"system"):
    """Open (or refresh) a deviation for unconfigured criteria on a worksheet.

    Idempotent: returns the existing record when the same gaps are already
    filed, so each push of the same run finds the one record.
    """
    if not gaps or not worksheet_id:
        return None
    signature = _signature(worksheet_id, gaps)
    registry = get_registry(portal)

    for dev in registry:
        if dev.get(SIGNATURE_KEY) == signature and dev.get("status") != "closed":
            # Already filed. Retry the notification if it never got through:
            # this early return happens before _notify_qao, and configuring
            # the QAO afterwards must be enough to close the loop.
            if not dev.get("qao_notified"):
                if _notify_qao(portal, dev, worksheet_id, gaps):
                    dev["qao_notified"] = True
                    dev["closure_notes"] = u""
                    save_registry(portal, registry)
                    logger.info("QAO notified retrospectively for %s",
                                dev.get("dev_id"))
            return dev

    dev_id = _next_id(registry)
    from senaite.pfas import lab_time
    today = lab_time.today().isoformat()
    record = {
        "dev_id":      dev_id,
        "type":        "deviation",
        "filed_by":    filed_by,
        "filed_at":    today,
        "status":      "open",
        "event_type":  EVENT_TYPE,
        "event_date":  today,
        "description": _describe(gaps),
        # A criterion that was never set is not a borderline call: every result
        # it governs is unjudged, so it scores as certain and significant.
        "likelihood":  3,
        "severity":    3,
        "risk_score":  9,
        "risk_colour": "orange",
        "affected_worksheets": [worksheet_id],
        "affected_date_from":  today,
        "affected_date_to":    "",
        "scale_description":   u"All results on this worksheet governed by the "
                               u"criteria listed above.",
        "root_cause":          u"",
        "corrective_actions":  [],
        "closed_by":   None,
        "closed_at":   None,
        "closure_notes": "",
        SIGNATURE_KEY: signature,
    }
    logger.warning("Raised %s for unconfigured QC criteria on %s",
                   dev_id, worksheet_id)
    # Whether the QAO was actually reached is part of the record. A
    # notification that silently did not send is worse than none: the
    # deviation would look attended to. A QAO contact with no address reads
    # "not notified" until a real address is set.
    notified = _notify_qao(portal, record, worksheet_id, gaps)
    record["qao_notified"] = bool(notified)
    if not notified:
        record["closure_notes"] = (
            u"QAO was NOT notified automatically: {0} Tell them directly. "
            u"Once it is configured the notification is retried "
            u"automatically; there is no need to re-file this deviation.".format(
                record.get("qao_notify_error") or u"reason unrecorded."))
    registry.append(record)
    save_registry(portal, registry)
    return record


def qao_email(portal):
    """The QAO's address, from the single place the QAO is already named."""
    from senaite.pfas.print_settings import get_signoff_signers
    try:
        qao = (get_signoff_signers(portal) or {}).get("qao")
        return (qao or {}).get("email") or u""
    except Exception as exc:                                # noqa: BLE001
        logger.warning("could not resolve the QAO contact: %s", exc)
        return u""


def _notify_qao(portal, record, worksheet_id, gaps):
    """Email the QAO. A failure here must not undo the deviation."""
    address = qao_email(portal)
    if not address:
        logger.warning(
            u"%s: no QAO email: set the QAO's initials in Print Settings and "
            u"an email address on that LabContact. The notification is retried "
            u"once one is set.", record["dev_id"])
        record["qao_notify_error"] = (
            u"No email address on the QAO LabContact "
            u"(Print Settings \u2192 QAO initials).")
        return False

    # A MailHost with no SMTP host silently accepts nothing. Say so up front
    # rather than reporting a generic send failure.
    if not (getattr(getattr(portal, "MailHost", None), "smtp_host", "") or ""):
        logger.warning(u"%s: QAO is %s but no SMTP host is configured in "
                       u"MailHost, so nothing can be sent.",
                       record["dev_id"], address)
        record["qao_notify_error"] = (
            u"No SMTP host configured in MailHost; "
            u"the QAO address ({0}) is set.".format(address))
        return False

    try:
        from senaite.pfas import lab_identity
        prefix = lab_identity.mail_prefix(portal)
    except Exception:                                       # noqa: BLE001
        prefix = u"[LIMS]"
    subject = u"{0} {1}: QC criteria not configured on {2}".format(
        prefix, record["dev_id"], worksheet_id)
    body = u"{0}\n\n{1}\n\nWorksheet: {2}/worksheets/{3}\nMethod Profiles: " \
           u"{2}/@@pfas-method-profiles\n".format(
               subject, record["description"],
               portal.absolute_url(), worksheet_id)
    try:
        from senaite.pfas import mail_text
        message = mail_text.message(
            portal.getProperty("email_from_address", "lims@localhost"),
            address, subject, body)
        portal.MailHost.send(message, immediate=True)
        logger.info("Notified the QAO (%s) of %s", address, record["dev_id"])
        return True
    except Exception as exc:                                # noqa: BLE001
        logger.error("QAO notification failed for %s: %s",
                     record["dev_id"], exc)
        record["qao_notify_error"] = u"Send failed: {0}".format(exc)
        return False


def retry_notifications(portal):
    """E-mail the QAO each open deviation this module filed that never
    reached the QAO; returns how many went. Asked on a POST (the worker's
    notice tick), never by a page. Nothing is tried, and nothing logged,
    while there is no QAO address or no SMTP host to send it with."""
    if not qao_email(portal):
        return 0
    if not (getattr(getattr(portal, "MailHost", None), "smtp_host", "") or ""):
        return 0
    registry = get_registry(portal)
    sent = 0
    for dev in registry:
        if not dev.get(SIGNATURE_KEY) or dev.get("status") == "closed" \
                or dev.get("qao_notified"):
            continue
        worksheet_id = (dev.get("affected_worksheets") or [u""])[0]
        if _notify_qao(portal, dev, worksheet_id, []):
            dev["qao_notified"] = True
            dev["closure_notes"] = u""
            sent += 1
            logger.info("QAO notified retrospectively for %s", dev.get("dev_id"))
    if sent:
        save_registry(portal, registry)
    return sent
