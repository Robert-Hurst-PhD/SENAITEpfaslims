# -*- coding: utf-8 -*-
"""What every PFAS browser view repeated, once: the site, its address, a
redirect and how a screen shows a time. A view inherits ViewHelpers before
BrowserView; a view whose own copy differs (a redirect with a message, the
page's own address) keeps it.

Python 2.7 compatible.
"""
from __future__ import absolute_import, unicode_literals

import re


class LabTime(object):
    """How a screen shows a time. A view that does not take ViewHelpers adds
    this alone (it defines nothing else)."""

    def zone_active(self):
        """True when times are shown on the laboratory's clock."""
        from senaite.pfas import lab_time
        return lab_time.active()

    def lab_at(self, value, before, fmt=u"%Y-%m-%d %H:%M"):
        """A recorded UTC instant (stored text, a DateTime or a datetime) as a
        screen shows it: on the laboratory's clock in `fmt` while the zone
        converts. Otherwise `before`, what the screen has always shown; a bare
        date is never shifted. A screen names no zone: a stored " UTC" is
        dropped."""
        from senaite.pfas import print_doc
        shown = print_doc.lab_or(value, before, fmt)
        if isinstance(shown, bytes):
            shown = shown.decode("utf-8", "replace")
        return re.sub(r"\s*UTC$", u"", shown) if shown else shown

    def lab_today(self):
        """The laboratory's date, "YYYY-MM-DD", for a field a screen fills in
        with today; the UTC date while the zone does not convert."""
        from senaite.pfas import lab_time
        return lab_time.today().isoformat()


class MethodNames(object):
    """view.method_name(id): a method by its one name, for any view."""

    def method_name(self, method_id):
        """The name a person reads for a method (method_name below)."""
        return method_name(method_id, self.__dict__.setdefault("_method_names", {}))


class ViewHelpers(LabTime, MethodNames):

    def _portal(self):
        from bika.lims import api            # imported here: tests load views without Zope
        return api.get_portal()

    def portal_url(self):
        return self._portal().absolute_url()

    def _redirect(self, url):
        self.request.response.redirect(url)
        return ""


def method_name(method_id, seen=None):
    """The name a person reads for a method, on a screen or a printout: its
    profile's display name (configured_methods.label). A stored method id
    is never what a page prints; a page that lists many methods hands in
    `seen` so each profile is read once."""
    if not method_id:
        return u""
    if seen is not None and method_id in seen:
        return seen[method_id]
    from bika.lims import api            # imported here: tests load views without Zope
    from senaite.pfas import configured_methods
    try:
        name = configured_methods.label(api.get_portal(), method_id)
    except Exception:                                       # noqa: BLE001
        name = method_id
    if seen is not None:
        seen[method_id] = name
    return name


def core_method_name(method, seen=None):
    """A core Method object by the one name its method has (method_name);
    its own title only when no profile names it."""
    from senaite.pfas.doc_fields import utext
    if method is None:
        return u""
    try:
        mid = method.getMethodID() or u""
    except Exception:                                       # noqa: BLE001
        mid = u""
    name = method_name(mid, seen) if mid else u""
    if name and name != mid:
        return name
    return utext(method.Title()) or name or method.getId()


# the request parameter senaite.impress's publisher reads its samples from;
# without it the publisher opens empty
PUBLISHER_ITEMS = "items"


def publisher_url(base_url, uids):
    """The publisher (`<base>/publish`) opened on these samples; u"" when
    there are none."""
    uids = [u for u in uids or [] if u]
    if not uids:
        return u""
    return u"%s/publish?%s=%s" % (base_url, PUBLISHER_ITEMS, u",".join(uids))


def _native(value):
    """A header value as the native str waitress requires on Python 2."""
    return value if isinstance(value, str) else value.encode("utf-8")


def send_pdf(response, pdf, filename, inline=True):
    """`pdf` as the response, shown in the browser (inline) or downloaded."""
    response.setHeader(_native("Content-Type"), _native("application/pdf"))
    response.setHeader(_native("Content-Disposition"), _native(
        '%s; filename="%s"' % ("inline" if inline else "attachment", filename)))
    return pdf
