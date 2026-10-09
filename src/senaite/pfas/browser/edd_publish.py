# -*- coding: utf-8 -*-
"""
The EDD export at publication.

On a sample's publication, when its client exports EDDs: the batch's EDD is
generated in the client's profile and stored on the batch (none when it has
a blocking error). A sample's sample-type code override is kept on the
sample.

    sample annotation  edd_store.SAMPLE_TYPE_KEY  the code override
    batch annotation   edd_store.EXPORT_KEY       {csv, filename, generated,
                                                   error_count, blocking_count}

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import logging

from Products.CMFCore.utils import getToolByName
from zope.annotation.interfaces import IAnnotations

from senaite.pfas.edd_store import EXPORT_KEY, SAMPLE_TYPE_KEY

logger = logging.getLogger("senaite.pfas.browser.edd_publish")


# ── Public helpers ─────────────────────────────────────────────────────────────

def set_ar_sample_type(ar_obj, sample_type_code):
    """Persist a sample's sample-type code override (at intake)."""
    try:
        ann = IAnnotations(ar_obj)
        ann[SAMPLE_TYPE_KEY] = sample_type_code
    except Exception as exc:
        logger.warning("Cannot set the EDD sample type on %s: %s", ar_obj.getId(), exc)


def get_ar_sample_type(ar_obj, default="GW"):
    """A sample's sample-type code (its override, else the default)."""
    try:
        ann = IAnnotations(ar_obj)
        return ann.get(SAMPLE_TYPE_KEY) or default
    except Exception:
        return default


def get_batch_edd(batch_obj):
    """Return stored EDD dict for a batch, or None."""
    try:
        ann = IAnnotations(batch_obj)
        raw = ann.get(EXPORT_KEY)
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
        ann[EXPORT_KEY] = json.dumps({
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
      A sample whose client exports EDDs: generate its batch's EDD.
    """
    if event.transition is None:
        return
    transition_id = event.transition.id

    if instance.portal_type != "AnalysisRequest":
        return

    if transition_id in ("publish", "publish_immediately"):
        _handle_publish(instance)


def _handle_publish(ar):
    """Generate the batch's EDD when a sample of an exporting client is
    published."""
    try:
        portal = getToolByName(ar, "portal_url").getPortalObject()
    except Exception as exc:
        logger.error("EDD publish: cannot get portal from AR %s: %s", ar.getId(), exc)
        return

    # Get client
    client_obj = None
    try:
        client_obj = ar.getClient()
    except AttributeError:
        pass

    if client_obj is None:
        return

    # does the client export EDDs
    try:
        from senaite.pfas.edd_store import is_edd_enabled
        if not is_edd_enabled(client_obj):
            return
    except Exception as exc:
        logger.warning("EDD publish: cannot read the EDD setting of %s: %s",
                       ar.getId(), exc)
        return

    # Get batch
    batch_obj = None
    try:
        batch_obj = ar.getBatch()
    except AttributeError:
        pass

    if batch_obj is None:
        logger.info("EDD publish: AR %s has no batch, skipping EDD", ar.getId())
        return

    # Generate EDD
    try:
        from senaite.pfas.edd_builder import EDDBuilder
        builder = EDDBuilder(portal)
        csv_str, errors, filename = builder.generate_from_batch(
            batch_obj, client_obj=client_obj
        )
    except Exception as exc:
        logger.error("EDD publish: EDD generation failed for batch %s: %s",
                     batch_obj.getId(), exc)
        return

    blocking = [e for e in errors if e.get("type") == "BLOCKING"]
    if blocking:
        # Do NOT store an unsubmittable file on the batch. The other two exits
        # refuse outright — @@pfas-edd-export returns a JSON error and
        # edd_email declines to attach — while this one stored the bad CSV and
        # only logged. A file sitting on the batch reads as "the EDD is ready",
        # and the one place that publishes automatically was the one place that
        # made that claim untruthfully.
        _store_batch_edd(batch_obj, u"", filename, errors)
        logger.error(
            "EDD REFUSED for batch %s: %d BLOCKING validation error(s). "
            "No file stored. Resolve them and regenerate from "
            "@@pfas-edd-export?batch_id=%s. First: %s",
            batch_obj.getId(), len(blocking), batch_obj.getId(),
            blocking[0].get("message", "")
        )
    else:
        _store_batch_edd(batch_obj, csv_str, filename, errors)
        logger.info(
            "EDD generated for batch %s (%s, %d errors). "
            "Download from @@pfas-edd-export?batch_id=%s",
            batch_obj.getId(), filename, len(errors), batch_obj.getId()
        )

    # The export is delivered as an attachment on the report e-mail
    # (browser/edd_email.py): one e-mail carries the report and the EDD
    # (D63 step D). Generation and batch storage above are the audit trail
    # and what the export page offers.
