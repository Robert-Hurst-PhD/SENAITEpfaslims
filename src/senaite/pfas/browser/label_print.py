# -*- coding: utf-8 -*-
"""
PFAS Label Printer (@@pfas-label).

Generates a print-ready HTML label for reagents, standards, and prepared
solutions. The analyst uses the browser's print dialog (Ctrl+P / Cmd+P) to
send directly to a label printer or save as PDF.

Label size is selectable from common lab sizes or fully custom (width × height
in mm). JsBarcode renders a CODE128 barcode from the lot number client-side —
no server-side barcode library is required.

URL parameters (all optional):
  name      Reagent / solution name
  lot       Lot number (also used as barcode data)
  conc      Concentration (e.g. "100 ng/mL")
  vol       Volume (e.g. "10 mL")
  exp       Expiry date (ISO, e.g. "2026-12-31")
  date      Preparation date
  analyst   Prepared by
  method    Method name
  storage   Storage conditions (e.g. "-20°C in dark")
  back      URL to return to after printing

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from senaite.pfas.browser.formutil import flatten_form


# Common label sizes: (id, display_name, width_mm, height_mm)
LABEL_SIZES = [
    ("2x1",    '2" × 1" (tube/vial)',          50.8,  25.4),
    ("2x3",    '2" × 3" (bottle)',              50.8,  76.2),
    ("4x2",    '4" × 2" (larger bottle)',      101.6,  50.8),
    ("3x1",    '3" × 1" (rack/tube)',           76.2,  25.4),
    ("4x3",    '4" × 3" (bulk container)',     101.6,  76.2),
    ("a4",     'A4 full page (PDF archive)',    210.0, 297.0),
    ("custom", 'Custom size',                     0.0,   0.0),
]


class PFASLabelPrintView(BrowserView):
    """Render a browser-printable reagent / solution label."""

    template = ViewPageTemplateFile("templates/label_print.pt")

    def __call__(self):
        flatten_form(self.request)
        return self.template()

    def _get(self, key, default=""):
        val = self.request.form.get(key, default)
        if isinstance(val, bytes):
            val = val.decode("utf-8", "replace")
        return val.strip() if val else default

    # ── Label field accessors (used by template) ─────────────────────────────

    def name(self):        return self._get("name")
    def lot(self):         return self._get("lot")
    def conc(self):        return self._get("conc")
    def vol(self):         return self._get("vol")
    def exp(self):         return self._get("exp")
    def prep_date(self):   return self._get("date")
    def analyst(self):     return self._get("analyst")
    def method(self):      return self._get("method")
    def storage(self):     return self._get("storage", "-20°C")
    def back_url(self):    return self._get("back", "javascript:history.back()")
    def label_size(self):  return self._get("size", "2x1")

    def label_sizes(self):
        return LABEL_SIZES

    def size_dict_json(self):
        import json
        d = {}
        for sid, sname, w, h in LABEL_SIZES:
            d[sid] = {"name": sname, "w": w, "h": h}
        return json.dumps(d)
