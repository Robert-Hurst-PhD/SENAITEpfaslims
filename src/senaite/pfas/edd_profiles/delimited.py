# -*- coding: utf-8 -*-
"""The column-mapped delimited-file format, as an EDD export profile type:
a profile of this type describes its delivery as DATA (files, columns,
sources, conditions, formats, code maps, value lists, row grain), edited on
the EDD pages and written by one generic writer (senaite.pfas.edd_delimited).
No delivery format is code: a state's format is a profile of this type.

Pure; Python 2.7 and 3 (the export itself, `generate`, runs in Zope).
"""
from __future__ import absolute_import, unicode_literals

PROFILE_ID = "delimited"
NAME = u"Column-mapped delimited files"

# the forms the EDD settings page shows for this type: its own tabs replace
# the default format's Defaults / Methods / Qualifiers / QC types forms
DEFAULT_FIELDS = []
METHOD_FIELDS = []
ANALYTE_LABELS = {"code": u"CAS / code", "name": u"Name in this format"}
VALUE_LIST_SOURCE = None
QUALIFIER_LIST = ""
QC_TYPE_LIST = ""
UNNAMED_NOTE = u""
TABS = (("files", u"Files"), ("columns", u"Columns"), ("maps", u"Code maps"), ("lists", u"Value lists"),
        ("named_defaults", u"Lab values"), ("client_fields", u"Client fields"), ("analytes", u"Analytes"),
        ("test", u"Test export"), ("profiles", u"Profiles"))


def seed_profile():
    from senaite.pfas import edd_delimited
    return edd_delimited.skeleton(NAME)


def refresh_from_upload(current, upload_bytes):
    """This type imports one list at a time (sheet and column named on the
    Value lists tab), never a fixed workbook."""
    return current, {"updated": [], "errors": [u"Import a list by its sheet and column (Value lists tab)."]}


def generate(builder, batch_obj, client_obj, client_cfg):
    """(content, errors, filename) of a batch in a profile of this type."""
    from senaite.pfas import edd_facts
    return edd_facts.generate(builder, batch_obj, client_obj, client_cfg)
