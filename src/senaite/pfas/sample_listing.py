# -*- coding: utf-8 -*-
"""Core's samples lists (the site's, a client's, a batch's) name a sample's
properties in the lab's words: Matrix, Sampled, Client sample ID. Only the
column titles change; core's column keys, indexes and sorting stay core's.

    SAMPLES_COLUMN_TITLES        {core column key: the lab's title}
    retitle_columns(columns)     sets those titles on a listing's columns
    SamplesColumnTitlesAdapter   senaite.app.listing subscriber

Python 2.7 and 3 compatible.
"""
from __future__ import absolute_import, unicode_literals

SAMPLES_COLUMN_TITLES = {
    "getSampleTypeTitle": u"Matrix",
    "getDateSampled": u"Sampled",
    "getClientSampleID": u"Client sample ID",
}


def retitle_columns(columns, titles=None):
    """Set each known column's title in `columns` ({key: {"title", ...}})
    to the lab's word; a column the list does not have stays absent."""
    for key, title in (titles or SAMPLES_COLUMN_TITLES).items():
        col = columns.get(key) if columns else None
        if col is not None:
            col["title"] = title
    return columns


class SamplesColumnTitlesAdapter(object):
    """senaite.app.listing subscriber on core's samples lists."""

    priority_order = 1120

    def __init__(self, listing, context):
        self.listing, self.context = listing, context

    def before_render(self):
        retitle_columns(getattr(self.listing, "columns", None))

    def folder_item(self, obj, item, index):
        return item
