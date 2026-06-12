# -*- coding: utf-8 -*-
"""
PFAS Sample Receipt (@@pfas-receipt) — internal printable receipt with QR code.

Accessed by lab staff after receiving a sample.  Requires authentication
(zope2.View permission).  Generates a QR code that links to the public
@@pfas-track page so clients can scan and track their sample.

Query string parameters:
  t=PF-YYMMDD-XXXX   — tracking number to render

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import io
import logging

from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

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


class PFASReceiptView(BrowserView):
    """
    @@pfas-receipt — printable sample receipt with tracking number and QR code.
    Internal use only (authenticated).
    """
    template = ViewPageTemplateFile('templates/receipt.pt')

    def __call__(self):
        return self.template()

    def _portal_url(self):
        return self.context.portal_url.getPortalObject().absolute_url()

    def tracking_number(self):
        return self.request.form.get('t', '').strip().upper()

    def tracker_url(self):
        t = self.tracking_number()
        if not t:
            return ''
        return '{0}/@@pfas-track?t={1}'.format(self._portal_url(), t)

    def qr_svg(self):
        """Return SVG markup for the QR code linking to the tracker page."""
        url = self.tracker_url()
        if not url:
            return u''
        return _generate_qr_svg(url)

    def portal_url(self):
        return self._portal_url()
