# -*- coding: utf-8 -*-
"""Labels print from an issued design, and from nothing else.

    LabelPrint   what the three label views share (@@pfas-label,
                 @@pfas-sitting-labels, a worksheet's @@pfas-extraction-labels)

A label is a controlled document: its layout is a design the laboratory
issued under Document Templates for one stock size. A view answers one PDF,
a page per label at that size, with no header or footer. With several
designs issued the person picks one; with none the page says so and sends
them to Document Templates. There is no other layout to fall back to, and a
design that cannot be drawn is refused, never replaced. Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import logging

from bika.lims import api
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from six.moves.urllib.parse import urlencode

from senaite.pfas import document_templates as dt
from senaite.pfas import pdf_renderer
from senaite.pfas.browser.view_helpers import send_pdf

logger = logging.getLogger("senaite.pfas.label_pdf")


def _bytes(value):
    return value.encode("utf-8") if not isinstance(value, bytes) else value


def print_url(base, form, design_id):
    """The view's own address with one design chosen: the request's other
    parameters kept (Python 2: URL-encode bytes)."""
    params = [(k, v) for k, v in sorted((form or {}).items())
              if k != "design" and isinstance(v, (bytes, type(u"")))]
    params.append(("design", design_id))
    return "%s?%s" % (base, urlencode([(_bytes(k), _bytes(v)) for k, v in params]))


def documents(kind, template, rows):
    """[(template, input)] for the renderer, a label each. ValueError: a
    value pdfme would evaluate rather than print."""
    return [dt.compile_document(kind, template, row) for row in rows]


class LabelPrint(object):
    """Mixed into a label view. The view sets `label_kind` and calls
    labels_response(rows, filename)."""

    label_kind = "label"
    designs_page = ViewPageTemplateFile("templates/label_designs.pt")

    # what the page that stands in for the PDF shows
    def label_subject(self):
        return u""

    def label_back(self):
        """(button text, URL) back to where the labels were asked for."""
        return None

    def kind_title(self):
        return dt.KINDS[self.label_kind]["title"]

    def issued_designs(self):
        if not hasattr(self, "_issued_designs"):
            self._issued_designs = dt.issued(dt.load(api.get_portal()), self.label_kind)
        return self._issued_designs

    def design_choices(self):
        out = []
        for entry, rev in self.issued_designs():
            size = dt.size_of(self.label_kind, entry.get("size")) or {}
            out.append({"id": entry["id"], "title": entry.get("title") or entry["id"],
                        "size": size.get("title") or entry.get("size") or u"", "rev": rev["rev"],
                        "url": print_url(self.request.get("ACTUAL_URL") or self.request.get("URL"),
                                         self.request.form, entry["id"])})
        return out

    def templates_url(self):
        return u"%s/@@pfas-document-templates?kind=labels" % api.get_portal().absolute_url()

    def label_state(self):
        """none: no design is issued; empty: nothing to print; choose:
        several designs are issued."""
        return getattr(self, "_label_state", u"none")

    def _page(self, state):
        self._label_state = state
        return self.designs_page()

    def labels_response(self, rows, filename):
        form = self.request.form
        if not self.issued_designs():
            return self._page(u"none")
        if not rows:
            return self._page(u"empty")
        picked = dt.choose(self.issued_designs(), form.get("design"), form.get("size"))
        if picked is None:
            return self._page(u"choose")
        _entry, rev = picked
        # an extended lot's mark follows its expiry on a design without
        # the field (lot_extension.label_row)
        from senaite.pfas import lot_extension
        shows = dt.shows(rev["template"], "extended")
        rows = [lot_extension.label_row(r, shows) for r in rows]
        response = self.request.response
        try:
            pdf = pdf_renderer.render_documents(documents(self.label_kind, rev["template"], rows))
        except ValueError as exc:
            response.setStatus(400)
            response.setHeader("Content-Type", "text/plain; charset=utf-8")
            return u"The labels were not printed: %s." % exc
        except pdf_renderer.RenderError as exc:
            logger.warning("labels not rendered: %s", exc)
            response.setStatus(500)
            response.setHeader("Content-Type", "text/plain; charset=utf-8")
            return u"The labels were not printed. %s" % exc
        return send_pdf(response, pdf, filename)
