# -*- coding: utf-8 -*-
"""The extraction queue as a long list, drawn by the Bench landing and the
Extraction Guide's batch picker alike: the filter bar (Not finished /
Finished / All, a search) and one page of rows (list_paging). Python 2.7."""
from __future__ import absolute_import, unicode_literals

import logging

logger = logging.getLogger("senaite.pfas.browser.queue_list")


class QueueList(object):
    """The extraction queue as a long list: the filter bar (Not finished /
    Finished / All and a search) and one page of rows. A view sets
    QUEUE_VIEW, the page the addresses point at."""

    QUEUE_VIEW = u"@@pfas-bench"

    def queue_show(self):
        from senaite.pfas.bench_queue import SHOW
        v = (self.request.form.get("show") or u"").strip()
        return v if v in [k for k, _l in SHOW] else u""

    def queue_q(self):
        return (self.request.form.get("q") or u"").strip()

    def queue_shows(self):
        from senaite.pfas.bench_queue import SHOW
        return [{"label": l, "url": self.queue_url(show=k), "on": k == self.queue_show()} for k, l in SHOW]

    def queue_url(self, show=None, page=None):
        from senaite.pfas.browser.list_paging import list_url
        return list_url(u"%s/%s" % (self.portal_url(), self.QUEUE_VIEW),
                        [("show", self.queue_show() if show is None else show), ("q", self.queue_q()),
                         ("page", page if page and page > 1 else None)])

    def queue_paging(self):
        if not hasattr(self, "_queue_pg"):
            from senaite.pfas.bench_queue import queue_filter
            from senaite.pfas.browser.list_paging import page_number, paging
            from senaite.pfas.browser.extraction_guide import extraction_queue
            try:
                rows = extraction_queue(self._portal(), self.request)
            except Exception as exc:                        # noqa: BLE001
                logger.warning("extraction queue: %s", exc)
                rows = []
            self._queue_all = rows
            self._queue_kept = queue_filter(rows, self.queue_show(), self.queue_q())
            self._queue_pg = paging(len(self._queue_kept), page_number(self.request.form),
                                    lambda p: self.queue_url(page=p))
        return self._queue_pg

    def queue_rows(self):
        pg = self.queue_paging()
        return self._queue_kept[pg["start"]:pg["end"]]

    def queue_empty_text(self):
        """What an empty page of the queue says."""
        self.queue_paging()
        if not self._queue_all:
            return u"No open worksheet."
        if self.queue_q():
            return u"No worksheet matches this search."
        return {u"": u"Every open worksheet's extraction is finished.",
                u"finished": u"No finished extraction yet."}.get(self.queue_show(), u"No open worksheet.")

    def queue_open_url(self, r):
        """Where a row's number opens: the worksheet's extraction record."""
        return u"%s/@@pfas-extraction-guide?batch_uid=%s" % (self.portal_url(), r.get("uid"))

    def queue_action(self, r):
        """A row's next step, {"label", "url"}: Add samples for a worksheet
        holding none, else Start extraction or Continue in the guide; None
        once the extraction is finished (the row's number opens it)."""
        from senaite.pfas.bench_queue import EMPTY, IN_PROGRESS, NOT_STARTED
        if r.get("state") == EMPTY:
            return {"label": u"Add samples", "url": u"%s/@@pfas-worksheet-samples" % r.get("url")}
        label = {NOT_STARTED: u"Start extraction", IN_PROGRESS: u"Continue"}.get(r.get("state"))
        return {"label": label, "url": self.queue_open_url(r)} if label else None
