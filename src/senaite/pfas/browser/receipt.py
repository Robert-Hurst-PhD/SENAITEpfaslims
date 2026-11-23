# -*- coding: utf-8 -*-
"""
PFAS Sample Receipt (@@pfas-receipt) — internal printable receipt with QR code.

Accessed by lab staff after receiving a sample.  Requires authentication
(zope2.View permission).  Generates a QR code that links to the public
@@pfas-track page so clients can scan and track their sample.

Query string parameters:
  t=PF-YYMMDD-XXXX   — tracking number to render (one sample's receipt)
  coc=COC-YYYY-NNNN  — a received chain of custody: one receipt for the
                       shipment, inside the application's frame, listing
                       each sample with its tracking code and QR code

Without either it names what it needs (a received CoC) and prints nothing.

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import io
import logging
import re

from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from senaite.pfas.browser.formutil import flatten_form

logger = logging.getLogger('senaite.pfas.browser.receipt')


def _generate_qr_svg(url):
    """Return SVG string for a QR code encoding *url*.  Returns empty string on error."""
    try:
        import qrcode
        import qrcode.image.svg

        qr = qrcode.QRCode(
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=6,
            border=3,
        )
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(image_factory=qrcode.image.svg.SvgPathImage)
        buf = io.BytesIO()
        img.save(buf)
        return buf.getvalue().decode('utf-8')
    except Exception as exc:
        logger.warning('QR code generation failed: %s', exc)
        return u''


def sized_qr(svg, px):
    """The QR code's SVG as inline markup `px` square on screen and paper:
    no XML declaration, and the root's width and height in pixels (its
    viewBox keeps the drawing)."""
    svg = re.sub(r"^\s*<\?xml[^>]*\?>\s*", u"", svg or u"")
    if not svg:
        return u""

    def root(m):
        tag = re.sub(r'\s(width|height)="[^"]*"', u"", m.group(0))
        return tag[:-1] + u' width="%d" height="%d" aria-hidden="true">' % (px, px)
    return re.sub(r"<svg\b[^>]*>", root, svg, count=1)


def url_parts(url):
    """[the address up to its query, the query]: joined they are `url`."""
    head, mark, query = (url or u"").partition(u"?")
    return [p for p in (head, mark + query) if p]


def receipt_rows(sample_id, client_sid, coc):
    """[(label, value)] of a receipt's identity, a row only for a value held."""
    rows = [(u"Sample", sample_id), (u"Client sample ID", client_sid), (u"Chain of custody", coc)]
    return [(label, u"%s" % value) for label, value in rows if value]


class PFASReceiptView(BrowserView):
    """
    @@pfas-receipt — printable sample receipt with tracking number and QR code.
    Internal use only (authenticated).
    """
    template = ViewPageTemplateFile('templates/receipt.pt')
    # one receipt per chain of custody, inside the application's frame
    coc_template = ViewPageTemplateFile('templates/receipt_coc.pt')

    QR_PX = 112

    def __call__(self):
        flatten_form(self.request)
        if self.tracking_number():
            return self.template()
        return self.coc_template()

    def coc_state(self):
        """What the CoC receipt page can show: "none" (no CoC named),
        "missing" (no such CoC, or another client's), "not_received" (the
        receipt comes once the laboratory receives it) or "ok"."""
        if not self.request.form.get('coc', '').strip():
            return "none"
        coc = self.coc_receipt()
        if coc is None:
            return "missing"
        return "ok" if coc["received"] else "not_received"

    def _portal_url(self):
        return self.context.portal_url.getPortalObject().absolute_url()

    def _sample(self):
        """The sample the tracking number names, or None; read once."""
        if not hasattr(self, "_ar"):
            self._ar = None
            t = self.tracking_number()
            if t:
                try:
                    from bika.lims import api
                    from senaite.pfas.tracking_store import get_ar_uid_by_tracking
                    uid = get_ar_uid_by_tracking(self.context.portal_url.getPortalObject(), t)
                    self._ar = api.get_object_by_uid(uid, None) if uid else None
                except Exception as exc:                    # noqa: BLE001
                    logger.warning('receipt %s: sample not read: %s', t, exc)
        return self._ar

    def _field(self, name):
        """A field of the sample as text; empty without a sample or a value."""
        ar = self._sample()
        try:
            field = ar.getField(name) if ar is not None else None
            return u"%s" % (field.get(ar) or u"") if field is not None else u""
        except Exception:                                   # noqa: BLE001
            return u""

    def _coc_number(self):
        """The CoC number the sample carries (the tracking number names the
        sample); empty when the sample came in without one."""
        return self._field("CoCNumber")

    def identity(self):
        """[(label, value)] naming what was received, each only when the
        sample holds it: the laboratory's sample number, the client's own
        sample ID, the chain of custody. The receipt card and the printed
        control block show the same rows (receipt_rows)."""
        ar = self._sample()
        return receipt_rows(ar.getId() if ar is not None else u"",
                            self._field("ClientSampleID"), self._coc_number())

    def lab_name(self):
        """The laboratory's name: core's Laboratory record, the name the
        printed header and the certificate carry."""
        from senaite.pfas import lab_identity
        return lab_identity.lab_name()

    def coc_link_number(self):
        """The CoC number the page is about, for the way back to it: the one
        asked for, else the one the sample carries."""
        coc = self.coc_receipt()
        return coc["number"] if coc else self._coc_number()

    def coc_receipt(self):
        """The chain of custody named by ?coc= as the receipt lists it, or
        None: its number, client, who received it and when, and its samples,
        each with the tracking number it was given on receipt (empty before)."""
        if not hasattr(self, "_coc"):
            self._coc = None
            num = self.request.form.get('coc', '').strip()
            if num and not self.tracking_number():
                self._coc = self._read_coc(num)
        return self._coc

    def _may_see(self, rec):
        """Lab staff see every CoC's receipt; a client only their own."""
        from bika.lims import api
        from senaite.pfas.browser.perms import is_staff
        if is_staff(api.get_portal()):
            return True
        try:
            client = api.get_current_client()
        except Exception:                                   # noqa: BLE001
            client = None
        return client is not None and api.get_uid(client) == rec.get("client_uid")

    def _read_coc(self, num):
        from bika.lims import api
        from senaite.pfas import coc_records as cr
        from senaite.pfas.tracking_store import tracking_for
        portal = self.context.portal_url.getPortalObject()
        rec = cr.load(portal, num)
        if not rec or not self._may_see(rec):
            return None
        samples = []
        for uid in rec.get("samples") or []:
            s = api.get_object_by_uid(uid, None)
            if s is None:
                continue
            number = tracking_for(portal, s)[0] or u""
            track = u"%s/@@pfas-track?t=%s" % (portal.absolute_url(), number) if number else u""
            samples.append({"id": s.getId(), "csid": s.getClientSampleID() or u"", "tracking": number,
                            "qr": sized_qr(_generate_qr_svg(track), self.QR_PX) if track else u""})
        rc = rec.get("receipt") or {}
        return {"number": rec["number"], "client": rec.get("client") or u"",
                "received": rec.get("status") == cr.RECEIVED,
                "received_at": cr.received_in_force(rec), "received_by": rc.get("received_by") or u"",
                "samples": samples}

    def print_control(self):
        t = self.tracking_number()
        coc = self.coc_receipt()
        if coc:
            cells = [(u"Chain of custody", coc["number"]), (u"Client", coc["client"]),
                     (u"Received", u" ".join(x for x in (coc["received_at"], coc["received_by"]) if x))]
            return {"doc_id": u"Sample receipt", "title": u"Sample receipt",
                    "cells": [(l, v) for l, v in cells if v]}
        cells = ([(u"Tracking number", t)] if t else []) + self.identity()
        return {"doc_id": u"Sample receipt", "title": u"Sample receipt", "cells": cells}

    def tracking_number(self):
        return self.request.form.get('t', '').strip().upper()

    def tracker_url(self):
        t = self.tracking_number()
        if not t:
            return ''
        return '{0}/@@pfas-track?t={1}'.format(self._portal_url(), t)

    def tracker_url_parts(self):
        """The tracking address in the pieces it may break between when it
        does not fit one line: the page, then the tracking number, which is
        never split."""
        return url_parts(self.tracker_url())

    def qr_svg(self):
        """Return SVG markup for the QR code linking to the tracker page."""
        url = self.tracker_url()
        if not url:
            return u''
        return _generate_qr_svg(url)

    def portal_url(self):
        return self._portal_url()
