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
from senaite.pfas.browser.view_helpers import ViewHelpers
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from senaite.pfas import document_templates as dt
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.view_helpers import send_pdf


# Label sizes: (id, display_name, width_mm, height_mm). The stock sizes are
# document_templates.LABEL_SIZES (the designer draws on the same ones).
LABEL_SIZES = [tuple(s) for s in dt.LABEL_SIZES] + [("custom", 'Custom size', 0.0, 0.0)]


def label_href(portal_url, back=u"", **data):
    """@@pfas-label for one lot: the label's own fields only, URL-encoded
    (Python 2: encode text first). Used by the inventory rows' Print label."""
    from six.moves.urllib.parse import urlencode
    params = []
    for k in dt.field_keys("label") + ["back"]:
        v = back if k == "back" else data.get(k)
        if v:
            params.append((k, v.encode("utf-8") if not isinstance(v, bytes) else v))
    return "%s/@@pfas-label?%s" % (portal_url, urlencode(params))


class PFASLabelPrintView(ViewHelpers, BrowserView):
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
    def requested_size(self): return self._get("size")

    def js(self, value):
        """A value from the URL as a JavaScript literal (a quote or a
        backslash in it once broke the whole page's script)."""
        return dt.script_json(value)

    def label_sizes(self):
        return LABEL_SIZES

    def label_data(self):
        """This label's values, keyed as document_templates.LABEL_FIELDS."""
        return dict((k, self._get(k)) for k in dt.field_keys("label"))

    def designed(self):
        """Issued label templates, each with this label's pdfme input.
        Empty = only the built-in layout is offered."""
        if not hasattr(self, "_designed"):
            out = []
            try:
                from bika.lims import api
                data = self.label_data()
                if not data.get("storage"):
                    data["storage"] = self.storage()
                for entry, rev in dt.issued(dt.load(api.get_portal()), "label"):
                    size = dt.size_of("label", entry.get("size")) or {}
                    try:
                        doc, inputs = dt.compile_document("label", rev["template"], data)
                    except ValueError:
                        continue      # a value pdfme would evaluate: built-in layout
                    out.append({"id": entry["id"], "title": entry["title"], "rev": rev["rev"],
                                "size": size.get("title", u""), "size_id": entry.get("size"),
                                "template": doc, "inputs": inputs})
            except Exception:                                   # noqa: BLE001
                import logging
                logging.getLogger("senaite.pfas.label").warning(
                    "designed label templates unavailable", exc_info=True)
            self._designed = out
        return self._designed

    def designed_json(self):
        return dt.script_json(self.designed())

    def size_dict_json(self):
        d = {}
        for sid, sname, w, h in LABEL_SIZES:
            d[sid] = {"name": sname, "w": w, "h": h}
        return dt.script_json(d)


class PFASSittingLabelsView(ViewHelpers, BrowserView):
    """@@pfas-sitting-labels?entry=<prep entry id>: a label for every lot a
    prep sitting made, each with its own values (lot_record.label_rows). The
    issued label design as one PDF page per label; else the built-in sheet
    with a Code 128 barcode of each lot number."""

    template = ViewPageTemplateFile("templates/sitting_labels.pt")

    def __call__(self):
        flatten_form(self.request)
        if self.request.form.get("format") != "sheet":
            pdf = self._designed_pdf()
            if pdf:
                return send_pdf(self.request.response, pdf, "%s-labels.pdf" % self.entry_id())
        return self.template()

    def entry_id(self):
        return (self.request.form.get("entry") or u"").strip()

    def rows(self):
        if not hasattr(self, "_rows"):
            from bika.lims import api
            from senaite.pfas import lot_record, prep_entries
            from senaite.pfas.browser.prepared_standards import _list
            portal = api.get_portal()
            entry = prep_entries.load(portal).get(self.entry_id())
            self._rows = lot_record.label_rows(entry, dict((r["uid"], r) for r in _list(portal)))
        return self._rows

    def _designed_pdf(self):
        from bika.lims import api
        from senaite.pfas import pdf_renderer
        try:
            issued = dt.issued(dt.load(api.get_portal()), "label")
        except Exception:                                   # noqa: BLE001
            return None
        if not issued or not self.rows():
            return None
        _entry, rev = issued[0]
        try:
            docs = [dt.compile_document("label", rev["template"], row) for row in self.rows()]
        except ValueError:
            return None
        return pdf_renderer.render_documents(docs)

    def sizes(self):
        return [s for s in LABEL_SIZES if s[0] not in (u"a4", u"custom")]

    def size(self):
        sid = self.request.form.get("size") or u"2x1"
        found = [s for s in LABEL_SIZES if s[0] == sid] or [s for s in LABEL_SIZES if s[0] == u"2x1"]
        return {"id": found[0][0], "w": found[0][2], "h": found[0][3]} if found else {"id": sid, "w": 50.8, "h": 25.4}

    def sheet_style(self):
        s = self.size()
        return u"--lbl-w:%smm;--lbl-h:%smm" % (s["w"], s["h"])
