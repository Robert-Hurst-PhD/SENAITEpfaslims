# -*- coding: utf-8 -*-
"""
The reagent / standard label views.

    @@pfas-label             one label, its values in the URL
    @@pfas-sitting-labels    a label for every lot a preparation record made

Both answer a PDF drawn from the issued Labels design (Document Templates),
one label to a page at the design's stock size; label_pdf.LabelPrint says
what happens with several designs issued, or none.

@@pfas-label URL parameters (all optional):
  name      Reagent / solution name
  lot       Lot number (also the barcode)
  conc      Concentration (e.g. "100 ng/mL")
  vol       Volume (e.g. "10 mL")
  exp       Expiry date in force (ISO, e.g. "2026-12-31")
  exp_original Expiry before the lot was extended
  extended  "ext." when the lot was extended (a design that does not
            place it prints it after the expiry)
  date      Preparation date
  analyst   Prepared by
  method    Method name
  storage   Storage conditions
  size      A stock size (document_templates.LABEL_SIZES): the design of that size
  design    An issued design, by its id
  back      URL to return to

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

from Products.Five.browser import BrowserView
from six.moves.urllib.parse import urlencode

from senaite.pfas import document_templates as dt
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.label_pdf import LabelPrint
from senaite.pfas.browser.view_helpers import ViewHelpers


def label_href(portal_url, back=u"", **data):
    """@@pfas-label for one lot: the label's own fields only, URL-encoded
    (Python 2: encode text first). Used by the inventory rows' Print label."""
    params = []
    for k in dt.field_keys("label") + ["back"]:
        v = back if k == "back" else data.get(k)
        if v:
            params.append((k, v.encode("utf-8") if not isinstance(v, bytes) else v))
    return "%s/@@pfas-label?%s" % (portal_url, urlencode(params))


class PFASLabelPrintView(LabelPrint, ViewHelpers, BrowserView):
    """One reagent / standard label from the values in the URL."""

    label_kind = "label"

    def __call__(self):
        flatten_form(self.request)
        return self.labels_response([self.label_data()], "%s-label.pdf" % (self._get("lot") or "label"))

    def _get(self, key, default=""):
        val = self.request.form.get(key, default)
        if isinstance(val, bytes):
            val = val.decode("utf-8", "replace")
        return val.strip() if val else default

    def label_data(self):
        """This label's values, keyed as document_templates.LABEL_FIELDS."""
        return dict((k, self._get(k)) for k in dt.field_keys("label"))

    def label_subject(self):
        return self._get("lot") or self._get("name")

    def label_back(self):
        # only a page of this site: the address comes from the URL
        back = self._get("back")
        if back and back.startswith(self.portal_url() + "/"):
            return (u"Back", back)
        return None


class PFASSittingLabelsView(LabelPrint, ViewHelpers, BrowserView):
    """@@pfas-sitting-labels?entry=<preparation record id>: a label for
    every lot the preparation record made, each with its own values
    (lot_record.label_rows), as one PDF page per label."""

    label_kind = "label"

    def __call__(self):
        flatten_form(self.request)
        return self.labels_response(self.rows(), "%s-labels.pdf" % self.entry_id())

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

    def label_subject(self):
        return self.entry_id()

    def label_back(self):
        return (u"Prepared Standards", u"%s/@@pfas-prep-standards" % self.portal_url())
