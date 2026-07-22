# -*- coding: utf-8 -*-
"""
EGAD EDD publish event subscriber.

On AR publish → if client has EGAD enabled:
  1. Generate EDD CSV for the batch
  2. Store it in ZODB annotations on the Batch
  3. Send a separate email to the client with the EDD attached

On AR receive → if client has EGAD enabled:
  reads EGAD_SAMPLE_TYPE annotation if previously set (from intake form).

EGAD_SAMPLE_TYPE annotation key on AnalysisRequest:
  "senaite.pfas.egad_sample_type"  →  EGAD SAMPLE_TYPE_LUP code (e.g. "GW")

Batch EDD storage annotation key:
  "senaite.pfas.egad_edd"  →  {"csv": str, "filename": str, "generated": str,
                                "error_count": int, "blocking_count": int,
                                "report": str}

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import logging

from Products.CMFCore.utils import getToolByName
from zope.annotation.interfaces import IAnnotations

logger = logging.getLogger("senaite.pfas.browser.egad_publish")

EGAD_SAMPLE_TYPE_KEY = u"senaite.pfas.egad_sample_type"
EGAD_BATCH_EDD_KEY   = u"senaite.pfas.egad_edd"


# ── Public helpers ─────────────────────────────────────────────────────────────

def set_ar_sample_type(ar_obj, egad_sample_type_code):
    """Persist the EGAD SAMPLE_TYPE code override on an AR (at intake)."""
    try:
        ann = IAnnotations(ar_obj)
        ann[EGAD_SAMPLE_TYPE_KEY] = egad_sample_type_code
    except Exception as exc:
        logger.warning("Cannot set EGAD sample type on %s: %s", ar_obj.getId(), exc)


def get_ar_sample_type(ar_obj, default="GW"):
    """Return the EGAD SAMPLE_TYPE code for an AR (annotation or default)."""
    try:
        ann = IAnnotations(ar_obj)
        return ann.get(EGAD_SAMPLE_TYPE_KEY) or default
    except Exception:
        return default


def get_batch_edd(batch_obj):
    """Return stored EDD dict for a batch, or None."""
    try:
        ann = IAnnotations(batch_obj)
        raw = ann.get(EGAD_BATCH_EDD_KEY)
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return None


def _store_batch_edd(batch_obj, csv_str, filename, errors):
    """Persist generated EDD on the batch annotation."""
    from datetime import datetime
    blocking = [e for e in errors if e.get("type") == "BLOCKING"]
    try:
        ann = IAnnotations(batch_obj)
        ann[EGAD_BATCH_EDD_KEY] = json.dumps({
            "csv":            csv_str,
            "filename":       filename,
            "generated":      datetime.utcnow().isoformat(),
            "error_count":    len(errors),
            "blocking_count": len(blocking),
        })
    except Exception as exc:
        logger.error("Cannot store EDD on batch %s: %s", batch_obj.getId(), exc)


# ── Event subscriber ───────────────────────────────────────────────────────────

def on_after_transition(instance, event):
    """
    Fire on every DCWorkflow transition.  Handles:

    transition = publish / publish_immediately
      If AnalysisRequest with a government-agency client → generate EDD.

    transition = receive
      Read EGAD_SAMPLE_TYPE from AR annotations (set at intake via the
      AR tracker tab or intake form).
    """
    if event.transition is None:
        return
    transition_id = event.transition.id

    if instance.portal_type != "AnalysisRequest":
        return

    if transition_id in ("publish", "publish_immediately"):
        _handle_publish(instance)


def _handle_publish(ar):
    """Generate EGAD EDD when a government-agency AR is published."""
    try:
        portal = getToolByName(ar, "portal_url").getPortalObject()
    except Exception as exc:
        logger.error("EGAD publish: cannot get portal from AR %s: %s", ar.getId(), exc)
        return

    # Get client
    client_obj = None
    try:
        client_obj = ar.getClient()
    except AttributeError:
        pass

    if client_obj is None:
        return

    # Check government-agency flag
    try:
        from senaite.pfas.egad_store import is_egad_enabled
        if not is_egad_enabled(client_obj):
            return
    except Exception as exc:
        logger.warning("EGAD publish: cannot check egad_enabled on %s: %s",
                       ar.getId(), exc)
        return

    # Get batch
    batch_obj = None
    try:
        batch_obj = ar.getBatch()
    except AttributeError:
        pass

    if batch_obj is None:
        logger.info("EGAD publish: AR %s has no batch, skipping EDD", ar.getId())
        return

    # Generate EDD
    try:
        from senaite.pfas.egad_builder import EGADBuilder
        builder = EGADBuilder(portal)
        csv_str, errors, filename = builder.generate_from_batch(
            batch_obj, client_obj=client_obj
        )
    except Exception as exc:
        logger.error("EGAD publish: EDD generation failed for batch %s: %s",
                     batch_obj.getId(), exc)
        return

    # Store on batch
    _store_batch_edd(batch_obj, csv_str, filename, errors)

    blocking = [e for e in errors if e.get("type") == "BLOCKING"]
    if blocking:
        logger.warning(
            "EGAD EDD generated with %d BLOCKING errors for batch %s — "
            "file cannot be submitted to Maine DEP until resolved. "
            "Download from @@pfas-egad-export?batch_id=%s",
            len(blocking), batch_obj.getId(), batch_obj.getId()
        )
    else:
        logger.info(
            "EGAD EDD generated for batch %s (%s, %d errors). "
            "Download from @@pfas-egad-export?batch_id=%s",
            batch_obj.getId(), filename, len(errors), batch_obj.getId()
        )

    # NOTE (D63 step D): the EDD is now delivered as an attachment ON the
    # report (COA) email — one email carries the report PDF + the state EDD CSV
    # (senaite.pfas.browser.edd_email.PFASEmailView). We deliberately no longer
    # send a SEPARATE EDD email here (that would double-deliver). Generation +
    # batch storage above are retained for the audit trail and the export view.
    # _email_edd_to_client(...) kept below for reference/rollback only.


def _email_edd_to_client(portal, client_obj, batch_obj, csv_str, filename, errors):
    """
    Send a separate email to the client with the EDD CSV attached.

    Uses Plone MailHost.  Only sends if client has a valid email address
    and the EDD has no BLOCKING errors.
    """
    blocking = [e for e in errors if e.get("type") == "BLOCKING"]
    if blocking:
        logger.info(
            "EDD email suppressed for batch %s — %d blocking errors",
            batch_obj.getId(), len(blocking)
        )
        return

    if not csv_str:
        return

    # Get client email
    client_email = ""
    try:
        client_email = client_obj.getEmailAddress() or ""
    except AttributeError:
        pass

    if not client_email:
        logger.info(
            "EDD email skipped for batch %s — client %s has no email address",
            batch_obj.getId(), client_obj.getId()
        )
        return

    # Lab settings for email
    try:
        from senaite.pfas.egad_store import get_lab_config
        lab_cfg = get_lab_config(portal)
    except Exception:
        lab_cfg = {}

    lab_name = ""
    try:
        lab = portal.bika_setup.laboratory
        lab_name = lab.Title() or "PFAS Laboratory"
    except Exception:
        lab_name = "PFAS Laboratory"

    try:
        from senaite.pfas.egad_store import get_client_egad
        client_cfg = get_client_egad(client_obj)
    except Exception:
        client_cfg = {}

    project_site = client_cfg.get("project_site", "") or client_obj.Title()
    batch_id = batch_obj.getId()

    subject = u"Maine EGAD EDD — {0} / {1}".format(project_site, batch_id)
    body = u"""Dear {client},

Please find attached the Maine DEP EGAD Electronic Data Deliverable (EDD v6.0)
for batch {batch_id} ({project_site}).

Filename: {filename}
Errors: {n_errors}

Please review the EDD and submit it to Maine DEP at dep.edd@maine.gov.
Note: your laboratory submits the EDD directly to the State.

If you have questions about this submission, please contact the laboratory.

Regards,
{lab_name}
""".format(
        client=client_obj.Title(),
        batch_id=batch_id,
        project_site=project_site,
        filename=filename,
        n_errors=len([e for e in errors if e.get("type") != "BLOCKING"]),
        lab_name=lab_name,
    )

    try:
        from email import MIMEMultipart, MIMEText, MIMEBase
        from email.mime.multipart import MIMEMultipart as MPart
        from email.mime.text import MIMEText as MText
        from email.mime.base import MIMEBase as MBase
        from email import encoders
    except ImportError:
        try:
            from email.mime.multipart import MIMEMultipart as MPart
            from email.mime.text import MIMEText as MText
            from email.mime.base import MIMEBase as MBase
            from email import encoders
        except ImportError:
            logger.error("Cannot import email libraries for EDD delivery")
            return

    msg = MPart()
    msg["Subject"] = subject
    msg["To"] = client_email

    # Lab from address
    from_address = ""
    try:
        from_address = portal.email_from_address or ""
    except Exception:
        pass

    if from_address:
        msg["From"] = from_address

    msg.attach(MText(body, "plain", "utf-8"))

    # Attach CSV
    csv_bytes = csv_str.encode("utf-8") if isinstance(csv_str, unicode) else csv_str
    attachment = MBase("text", "csv")
    attachment.set_payload(csv_bytes)
    encoders.encode_base64(attachment)
    attachment.add_header(
        "Content-Disposition",
        "attachment",
        filename=filename.encode("utf-8") if isinstance(filename, unicode) else filename
    )
    msg.attach(attachment)

    try:
        mh = portal.MailHost
        mh.send(msg.as_string(), immediate=True)
        logger.info("EDD email sent to %s for batch %s", client_email, batch_id)
    except Exception as exc:
        logger.error(
            "EDD email failed for batch %s to %s: %s",
            batch_id, client_email, exc
        )
