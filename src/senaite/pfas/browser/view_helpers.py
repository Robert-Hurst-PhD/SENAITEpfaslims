# -*- coding: utf-8 -*-
"""What every PFAS browser view repeated, once: the site, its address, a
redirect and how a screen shows a time. A view inherits ViewHelpers before
BrowserView; a view whose own copy differs (a redirect with a message, the
page's own address) keeps it.

Python 2.7 compatible.
"""
from __future__ import absolute_import, unicode_literals


class LabTime(object):
    """How a screen shows a time. A view that does not take ViewHelpers adds
    this alone (it defines nothing else)."""

    def zone_active(self):
        """True when times are shown on the laboratory's clock. A screen then
        names no zone; while the zone is unset, a time it labels UTC still
        says so."""
        from senaite.pfas import lab_time
        return lab_time.active()

    def lab_at(self, value, before, fmt=u"%Y-%m-%d %H:%M"):
        """A recorded UTC instant (stored text, a DateTime or a datetime) as a
        screen shows it: on the laboratory's clock in `fmt` while the zone
        converts, naming no zone. Otherwise `before`, what the screen has
        always shown, byte for byte; a bare date is never shifted."""
        from senaite.pfas import print_doc
        return print_doc.lab_or(value, before, fmt)

    def lab_today(self):
        """The laboratory's date, "YYYY-MM-DD", for a field a screen fills in
        with today; the UTC date while the zone does not convert."""
        from senaite.pfas import lab_time
        return lab_time.today().isoformat()


class ViewHelpers(LabTime):

    def _portal(self):
        from bika.lims import api            # imported here: tests load views without Zope
        return api.get_portal()

    def portal_url(self):
        return self._portal().absolute_url()

    def _redirect(self, url):
        self.request.response.redirect(url)
        return ""


def _native(value):
    """A header value as the native str waitress requires on Python 2."""
    return value if isinstance(value, str) else value.encode("utf-8")


def send_pdf(response, pdf, filename, inline=True):
    """`pdf` as the response, shown in the browser (inline) or downloaded."""
    response.setHeader(_native("Content-Type"), _native("application/pdf"))
    response.setHeader(_native("Content-Disposition"), _native(
        '%s; filename="%s"' % ("inline" if inline else "attachment", filename)))
    return pdf
