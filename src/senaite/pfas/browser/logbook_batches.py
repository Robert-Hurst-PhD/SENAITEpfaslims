# -*- coding: utf-8 -*-
"""
@@pfas-logbook-batches — the bench entry point to batch logbooks.

Until now the per-batch logbook list (@@pfas-logbook-index) was reachable only
by typing its URL: nothing in the UI linked to it, and the sidebar's "Batch
Logbooks" entry pointed at the MANAGER configuration page instead. This view is
the missing route — a work queue of batches whose logbooks still need filling.

Default scope is deliberately "batches needing work", not "all batches", so the
page reads as a to-do list rather than an archive; ?all=1 reveals the rest.

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import logging

from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import require_manager

logger = logging.getLogger("senaite.pfas.browser.logbook_batches")

# Batch review states that mean "no longer being worked on".
CLOSED_STATES = frozenset(("closed", "cancelled", "published", "invalid"))


class PFASLogbookBatchesView(BrowserView):
    """Pick the batch whose logbooks you are filling in."""

    template = ViewPageTemplateFile("templates/logbook_batches.pt")

    def __call__(self):
        flatten_form(self.request)
        return self.template()

    # ── helpers ───────────────────────────────────────────────────────────
    def _portal(self):
        return getToolByName(self.context, "portal_url").getPortalObject()

    def portal_url(self):
        return self._portal().absolute_url()

    def show_all(self):
        return self.request.get("all", "") in ("1", "true", "yes")

    def is_manager(self):
        return require_manager(self.context, self.request)

    def setup_url(self):
        return "{0}/@@pfas-logbook-admin".format(self.portal_url())

    # ── the queue ─────────────────────────────────────────────────────────
    def _batch_row(self, batch):
        """One row: how many of this batch's logbooks are filled.

        Reuses PFASLogbookIndexView.logbooks(), which already resolves the
        method's required logbooks and each one's filled state — so this page
        can never disagree with the page it links to.
        """
        from senaite.pfas.browser.logbooks import PFASLogbookIndexView
        view = PFASLogbookIndexView(batch, self.request)
        try:
            method_id = view.batch_method() or ""
        except Exception:
            method_id = ""
        try:
            rows = view.logbooks() if method_id else []
        except Exception as exc:
            logger.warning("logbook rows for %s: %s", batch.getId(), exc)
            rows = []

        total = len(rows)
        done = len([r for r in rows if r.get("filled")])
        if total and done >= total:
            state, label = "complete", "All logbooks complete"
        elif done:
            state, label = "partial", "{0} of {1} logbooks done".format(done, total)
        elif total:
            state, label = "none", "Not started · {0} logbooks".format(total)
        else:
            state, label = "nomethod", "No method set — fill the extraction log first"

        return {
            "id":       batch.getId(),
            "title":    batch.Title() or batch.getId(),
            "method":   method_id,
            "url":      "{0}/@@pfas-logbook-index".format(batch.absolute_url()),
            "total":    total,
            "done":     done,
            "state":    state,
            "label":    label,
            "created":  batch.created(),
        }

    def batches(self):
        """Batches to show, newest first.

        Default: only those with outstanding logbook work — a batch with
        nothing left to do is noise on a bench queue. ?all=1 shows everything
        still open.
        """
        portal = self._portal()
        folder = portal.get("batches")
        if folder is None:
            return []

        wf = getToolByName(portal, "portal_workflow", None)
        rows = []
        for batch in folder.objectValues():
            if getattr(batch, "portal_type", "") != "Batch":
                continue
            try:
                if wf is not None:
                    status = wf.getInfoFor(batch, "review_state", "")
                    if status in CLOSED_STATES:
                        continue
            except Exception:
                pass
            rows.append(self._batch_row(batch))

        if not self.show_all():
            rows = [r for r in rows if r["state"] in ("partial", "none")]

        rows.sort(key=lambda r: r["created"], reverse=True)
        return rows

    def hidden_count(self):
        """How many open batches the default filter is holding back."""
        if self.show_all():
            return 0
        portal = self._portal()
        folder = portal.get("batches")
        if folder is None:
            return 0
        wf = getToolByName(portal, "portal_workflow", None)
        n = 0
        for batch in folder.objectValues():
            if getattr(batch, "portal_type", "") != "Batch":
                continue
            try:
                if wf is not None and wf.getInfoFor(batch, "review_state", "") in CLOSED_STATES:
                    continue
            except Exception:
                pass
            if self._batch_row(batch)["state"] not in ("partial", "none"):
                n += 1
        return n
