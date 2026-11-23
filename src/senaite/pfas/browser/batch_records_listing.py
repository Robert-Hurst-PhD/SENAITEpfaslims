# -*- coding: utf-8 -*-
"""@@pfas-batch-records as SENAITE's own listing: the worksheets' batch
records, paged and filtered by senaite.app.listing (the table core's own
Worksheets list draws).

It opens on In progress, every worksheet until it is verified (open or
awaiting verification), the 50 oldest first; All lists every worksheet, and
the filters, the search and the sort can be changed. ?all=1 opens on All.
A row is one worksheet's record as batch_records.PFASBatchRecordsView reads
it for a queue row (only the rows of the page shown are read): its record,
matrix, client, state, stages, the lots loaded for its run and its
signatures. ?record=<uid> and ?action=verify_record are the record view of
PFASBatchRecordsView, unchanged.

Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import collections
import logging

from senaite.app.listing import ListingView

from senaite.pfas import batch_record as br
from senaite.pfas.html_text import escape
from senaite.pfas import worksheet_lots

logger = logging.getLogger("senaite.pfas.browser.batch_records_listing")

WORKSHEET_CATALOG = "senaite_catalog_worksheet"
# every worksheet until it is verified: open, or awaiting verification
IN_PROGRESS = ("open", "to_be_verified")
EVERY = ("open", "to_be_verified", "verified", "rejected")
NOT_LOADED = "Not loaded"
COLUMNS = (("record", "Record"), ("matrix", "Matrix"), ("client", "Client"), ("state", "State"),
           ("stages", "Stages"), ("lots", "Loaded on instrument"), ("signatures", "Signatures"),
           ("created", "Created"), ("actions", ""))


def lots_loaded(record):
    """How many lots the record's run was loaded on the instrument with, in words: "3 lots",
    "1 lot", or Not loaded."""
    n = len(worksheet_lots.loaded_lots(((record or {}).get("parts") or {}).get("loaded")))
    if not n:
        return NOT_LOADED
    return "%d lot" % n if n == 1 else "%d lots" % n


def _button(href, text):
    return '<a class="btn btn-sm btn-secondary" href="%s">%s</a>' % (escape(href), escape(text))


def row_cells(row, record, purl, created=""):
    """(values, html) of one listing row: `row` is batch_record.queue_rows'
    row of `record`; each navigation is a button."""
    uid = row["uid"]
    values = {"record": row["title"], "matrix": row["matrix"], "client": row["client"],
              "state": row["label"], "stages": row["progress"], "lots": lots_loaded(record),
              "signatures": row["signed"], "created": created, "actions": ""}
    rec_url = "%s/@@pfas-batch-records?record=%s" % (purl, uid)
    html = {"record": _button(rec_url, row["title"]),
            "signatures": _button(rec_url, row["signed"]) if row["signed"] else ""}
    actions = [_button("%s/@@pfas-extraction-guide?batch_uid=%s" % (purl, uid), "Open extraction")]
    if row["printable"]:
        actions.append(_button("%s/@@pfas-extraction-pdf?batch_uid=%s" % (purl, uid), "Print record"))
    html["actions"] = " ".join(actions)
    return values, html


# the columns the worksheet catalog can sort by
SORT_INDEXES = {"record": "getId", "created": "created"}


def columns():
    """The listing's columns: the record and the date created sort by the
    catalog, the rest are read per row and do not sort."""
    out = collections.OrderedDict()
    for key, title in COLUMNS:
        out[key] = {"title": title, "index": SORT_INDEXES[key]} if key in SORT_INDEXES else \
            {"title": title, "sortable": False}
    return out


def review_states(columns):
    """The filters: In progress (the default) and All, the oldest first."""
    def state(sid, title, states):
        return {"id": sid, "title": title, "transitions": [], "custom_transitions": [],
                "contentFilter": {"review_state": list(states), "sort_on": "created",
                                  "sort_order": str("ascending")},
                "columns": list(columns)}
    return [state("default", "In progress", IN_PROGRESS), state("all", "All", EVERY)]


class PFASBatchRecordsListing(ListingView):
    """The Batch records list on senaite.app.listing; the record view is
    PFASBatchRecordsView's."""

    def __init__(self, context, request):
        super(PFASBatchRecordsListing, self).__init__(context, request)
        self.catalog = WORKSHEET_CATALOG
        self.contentFilter = {"portal_type": "Worksheet", "review_state": list(IN_PROGRESS),
                              "sort_on": "created", "sort_order": str("ascending")}
        self.title = "Batch records"
        self.description = "Each worksheet's record from receipt to release."
        self.pagesize = 50
        # the page is a PFAS page: no core content tabs, no core Add button
        self.hide_plone_toolbar = True
        self.context_actions = {}
        self.show_select_column = False
        self.show_workflow_action_buttons = False
        self.columns = columns()
        self.review_states = review_states(self.columns.keys())
        if (request.get("all") or "") in ("1", "true", "yes"):
            self.default_review_state = "all"
        self._records = None

    def __call__(self):
        req = self.request
        if req.get("record") or req.get("action") == "verify_record":
            from senaite.pfas.browser.batch_records import PFASBatchRecordsView
            view = PFASBatchRecordsView(self.context, req)
            view.__name__ = self.__name__
            return view()
        return super(PFASBatchRecordsListing, self).__call__()

    def _reader(self):
        """The record view's reader, kept for the page's rows (one profile
        read per method)."""
        if self._records is None:
            from senaite.pfas.browser.batch_records import PFASBatchRecordsView
            self._records = PFASBatchRecordsView(self.context, self.request)
            self._records._profiles = {}
        return self._records

    def folderitem(self, obj, item, index):
        from bika.lims import api
        from senaite.pfas import retired
        brain = obj
        mark = retired.get(api.get_object(brain)) if hasattr(brain, "getObject") else None
        # a retired worksheet is no work in progress: only the "All" list holds it
        if mark is not None and (self.review_state or {}).get("id") != "all":
            return None
        record = self._reader().queue_record(brain)
        record["uid"] = record.get("uid") or api.get_uid(brain)
        row = br.queue_rows([record])[0]
        from senaite.pfas import print_doc
        when = getattr(brain, "created", None)
        # the date the worksheet was made, on the laboratory's clock while
        # the zone converts; its stored UTC date otherwise
        before = when.ISO8601()[:10] if hasattr(when, "ISO8601") else ""
        created = print_doc.lab_or(when, before, "%Y-%m-%d")
        values, html = row_cells(row, record, api.get_portal().absolute_url(), created or "")
        if mark is not None and mark.get("note"):
            values["state"] = u"%s. %s" % (values["state"], mark["note"])
        item.update(values)
        item.setdefault("replace", {}).update(dict((k, v) for k, v in html.items() if v))
        return item
