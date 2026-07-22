# -*- coding: utf-8 -*-
"""
D63 step D — attach the state EDD CSV to the report (COA) email.

Overrides senaite.core's @@email view
(bika.lims.browser.publish.emailview.EmailView) on the PFAS browser layer,
extending `email_attachments` to append one EDD CSV per batch represented in the
emailed reports.  So a single email carries the report PDF(s) + the state EDD.

Not a core fork: a more-specific-layer (ISenaitePFASLayer) subclass that calls
super().  If senaite.core changes the `email_attachments` property contract,
revisit here (see DECISIONS.md D63).

Delivery gate: the client's per-client EDD config must have `egad_enabled`
(the explicit "emit a state EDD for this client" opt-in) — otherwise ordinary
commercial clients would receive an EDD they never need.  The STATE is the
client's `edd_profile`; the METHOD comes from the batch.

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import logging

from bika.lims import api
from bika.lims.api import mail as mailapi
from bika.lims.browser.publish.emailview import EmailView

logger = logging.getLogger("senaite.pfas.browser.edd_email")


class PFASEmailView(EmailView):
    """Core @@email view + state EDD CSV attachment(s)."""

    @property
    def email_attachments(self):
        # Core attachments first (report PDFs + user-selected attachments).
        attachments = super(PFASEmailView, self).email_attachments
        try:
            attachments.extend(self._edd_attachments())
        except Exception as exc:
            # Never let EDD assembly break the report email itself.
            logger.error("EDD attach failed; report email still sent: %s", exc)
        return attachments

    def _edd_attachments(self):
        """One EDD CSV per distinct batch across the emailed reports, for
        clients that have opted into state EDD delivery. A report can span more
        than one batch (primary + contained samples), so every sample is
        considered; batches are de-duplicated by UID."""
        out = []
        seen_batches = set()
        for batch, client in self._batches_and_clients():
            buid = api.get_uid(batch)
            if buid in seen_batches:
                continue
            seen_batches.add(buid)

            if not self._edd_enabled(client):
                continue

            att = self._build_edd_attachment(batch, client)
            if att is not None:
                out.append(att)
        return out

    # ── helpers ──────────────────────────────────────────────────────────────

    def _batches_and_clients(self):
        """Yield (batch, client) for every sample across the emailed reports —
        the primary sample and any contained samples of each report."""
        for report in self.reports:
            samples = []
            try:
                primary = report.getAnalysisRequest()
                if primary is not None:
                    samples.append(primary)
            except Exception:
                pass
            try:
                samples.extend(report.getContainedAnalysisRequests() or [])
            except Exception:
                pass
            for ar in samples:
                batch = None
                client = None
                try:
                    batch = ar.getBatch()
                except Exception:
                    pass
                if batch is None:
                    continue
                try:
                    client = ar.getClient()
                except Exception:
                    pass
                if client is None:
                    continue
                yield (batch, client)

    def _edd_enabled(self, client):
        try:
            from senaite.pfas.egad_store import is_egad_enabled
            return bool(is_egad_enabled(client))
        except Exception:
            return False

    def _build_edd_attachment(self, batch, client):
        """Generate the state EDD for a batch and return a mail attachment, or
        None (empty CSV, or BLOCKING validation errors → do not attach a bad
        file; the batch-stored EDD + export view still surface the errors)."""
        from senaite.pfas.egad_builder import EGADBuilder
        portal = api.get_portal()
        builder = EGADBuilder(portal)
        csv_str, errors, filename = builder.generate_from_batch(
            batch, client_obj=client)

        if not csv_str:
            return None

        blocking = [e for e in errors if e.get("type") == "BLOCKING"]
        if blocking:
            logger.warning(
                "EDD not attached to report email for batch %s — %d blocking "
                "error(s); resolve in EGAD Config, then resend.",
                api.get_id(batch), len(blocking))
            return None

        csv_bytes = csv_str.encode("utf-8") if isinstance(csv_str, unicode) \
            else csv_str
        return mailapi.to_email_attachment(csv_bytes, filename)
