# -*- coding: utf-8 -*-
"""
Logbook-specific METAL macro provider.

Registered at @@pfas-logbook-macros. Exposes the `logbook_field` macro so the
concise form (logbook_dynamic.pt) and the guided step view (logbook_guided.pt)
render a field identically —, define UI once.

Kept separate from @@pfas-macros: that file is site-wide page chrome and
already 1100+ lines; field widgets are a logbook concern.

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile


class PFASLogbookMacrosView(BrowserView):
    """Exposes logbook_field_macros.pt macros to other templates."""

    _template = ViewPageTemplateFile("templates/logbook_field_macros.pt")

    @property
    def macros(self):
        return self._template.macros

    def receipt_thermometers(self):
        """Instruments a receipt temperature can be taken with (IR guns and
        thermometers registered on Equipment), for a `thermometer` field."""
        from senaite.pfas import equipment_types as et
        from senaite.pfas import facility_qc as fq
        return [u for u in fq.list_units(True) if u.get("unit_type") in et.RECEIPT_KINDS]

    def corrected_rows(self, data, schema, fname):
        """[(row label, observed, corrected)] for the columns corrected by the
        thermometer field `fname`."""
        out = []
        for field in schema or []:
            if field.get("type") != "table":
                continue
            cols = [c for c in field.get("columns") or [] if c.get("corrected_by") == fname]
            first = (field.get("columns") or [{}])[0].get("name")
            for row in data.get(field.get("name")) or []:
                if not isinstance(row, dict):
                    continue
                for c in cols:
                    if row.get(c["name"]) not in (None, u"", ""):
                        out.append((row.get(first) or u"", row.get(c["name"]),
                                    row.get(c["name"] + u"_corrected")))
        return out
