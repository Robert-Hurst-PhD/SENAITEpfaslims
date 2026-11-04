# -*- coding: utf-8 -*-
"""Controlled documents on paper: the pieces every print path shares.

A printed record carries a control block (document or form number, revision,
effective or issue date) under the lab header, and a footer saying what it is,
who printed it and when, and that a printed copy is uncontrolled, with
"Page x of y" beside it. The look is pfas-print.css; WeasyPrint 0.42 has no
custom properties, so print_style.CSS is that file with the tokens resolved
(tools/make_print_css.py).

  document_css(...)   <style> text for a WeasyPrint document or a browser print
  head_html(...)      lab header, title and control block as HTML
  fonts               static Nunito files, as @font-face rules with file:// URLs
                      (WeasyPrint reads TrueType, not woff2 or variable fonts)
  now_label(), lab_or(...), times_line(...)
                      times on the laboratory's clock, and the line naming its
                      zone that a print showing a time carries once

Python 2.7 and 3 compatible.
"""
from __future__ import absolute_import, unicode_literals

import os
import re

from senaite.pfas import lab_time
from senaite.pfas.html_text import escape

from senaite.pfas.print_style import CSS

try:
    text_type = unicode                                      # noqa: F821 (py2)
except NameError:                                            # pragma: no cover
    text_type = str

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "browser", "static", "fonts", "print")
FACES = (("Nunito", 400, "Nunito-Regular.ttf"),
         ("Nunito", 600, "Nunito-SemiBold.ttf"),
         ("Nunito", 700, "Nunito-Bold.ttf"),
         ("Nunito", 800, "Nunito-ExtraBold.ttf"),
         ("Nunito Sans", 400, "NunitoSans-Regular.ttf"),
         ("Nunito Sans", 600, "NunitoSans-SemiBold.ttf"),
         ("Nunito Sans", 700, "NunitoSans-Bold.ttf"))
UNCONTROLLED = "uncontrolled when printed"


def _u(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return text_type(value)


def esc(value):
    return escape(_u(value))


def css_string(value):
    """`value` as the inside of a CSS "..." string."""
    out = []
    for ch in _u(value):
        if ch in '"\\':
            out.append("\\" + ch)
        elif ch in "\r\n":
            out.append(" ")
        elif ord(ch) > 126:
            # the page may reach the browser with its non-ASCII characters
            # turned into HTML entities, which a <style> element never decodes
            out.append("\\%x " % ord(ch))
        else:
            out.append(ch)
    return "".join(out)


def font_face_css(portal_url=None):
    """@font-face rules for the static files. WeasyPrint is handed the HTML as
    a string, so there is no base URL: a document it draws on its own names
    each file by absolute file:// URL. A section of an impress report names
    them through the site instead (portal_url): impress fetches site URLs
    itself, and the same rule then works in a browser."""
    rules = []
    for family, weight, name in FACES:
        path = os.path.join(FONT_DIR, name)
        if not os.path.exists(path):
            continue
        if portal_url:
            url = "%s/++resource++senaite.pfas/fonts/print/%s" % (portal_url.rstrip("/"), name)
        else:
            url = "file://" + path
        rules.append('@font-face { font-family: "%s"; font-weight: %d; '
                     'src: url("%s"); }' % (family, weight, url))
    return "\n".join(rules)


def doc_line(doc_id, revision=None):
    """"<doc id> Rev <n>": the document and its revision."""
    doc = _u(doc_id).strip()
    if _u(revision).strip():
        doc = ("%s Rev %s" % (doc, _u(revision).strip())).strip()
    return doc


def printed_line(printed_at=None, printed_by=None):
    """"Printed <date> by <user> . uncontrolled when printed", and the line
    naming the laboratory's zone when the printed stamp carries a time."""
    parts = []
    if printed_at:
        parts.append("Printed %s%s" % (_u(printed_at),
                                       " by %s" % _u(printed_by) if printed_by else ""))
    parts.append(UNCONTROLLED)
    zone = times_line(printed_at)
    if zone:
        parts.append(zone)
    return " · ".join(parts)


def footer_text(doc_id, revision=None, printed_at=None, printed_by=None):
    """The document line at the foot of every page: the document with its
    revision, and under it who printed it, when, and that a printed copy is
    uncontrolled. "Page x of y" and "Issued: <date>" sit beside it."""
    return "\n".join(l for l in (doc_line(doc_id, revision), printed_line(printed_at, printed_by)) if l)


MINUTE = "%Y-%m-%d %H:%M"
_CLOCK = re.compile(r"(?<!\d)\d{1,2}:\d{2}(?!\d)")


def now_label(fmt=MINUTE):
    """Now on the laboratory's clock (the server's clock, UTC, while the zone
    is not set)."""
    return lab_time.show(lab_time.now(), "lab", fmt)


def zone_label():
    """The zone a print names beside a time it stamps: the laboratory's, or
    UTC while no zone converts."""
    return lab_time.zone() if lab_time.active() else "UTC"


def now_stamp():
    """"<now> <zone>": a print stamp that names its zone."""
    return "%s %s" % (now_label(), zone_label())


def lab_or(value, before, fmt=MINUTE):
    """A stored UTC instant (a DateTime, a datetime or stored text) as a print
    shows it: on the laboratory's clock while the zone converts. Otherwise
    `before`, what the print has always shown, byte for byte. Text with no
    clock time, or that cannot be read, also prints `before`: a bare date is
    never shifted."""
    if not lab_time.active():
        return before
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    if isinstance(value, text_type) and not _CLOCK.search(value):
        return before
    if lab_time.to_wall(value, "utc") is None:
        return before
    return lab_time.show(value, "utc", fmt)


def times_line(*shown):
    """"Times are <zone>." when one of the values a print shows carries a
    clock time (HH:MM) and the zone converts; "" otherwise. A print carries
    it once, in its footer."""
    line = lab_time.footer()
    if line and any(_CLOCK.search(_u(v)) for v in shown):
        return line
    return ""


def document_css(doc_id, revision=None, printed_by=None, printed_at=None,
                 size=None, margin=None, fonts=True, base=True, issued=None):
    """The whole <style> text for one controlled document.

    size   a CSS page size ("letter", "A4 landscape"); leave None in a browser,
           where the person's own paper setting decides.
    margin a CSS margin ("14mm 12mm 16mm"); None keeps the stylesheet's.
    fonts  False when the browser already has the fonts (the page macro loads
           the add-on's woff2 files through pfas-tokens.css).
    base   False for a page that links pfas-print.css itself: only the @page rule
           naming this document is written, so the full stylesheet is not repeated
           in every page and never applies on screen.
    issued the date this revision was issued, shown as "Issued: <date>" at the
           right; none shown without one.
    """
    out = []
    if base:
        if fonts:
            out.append(font_face_css())
        out.append(CSS)
    page = []
    if size:
        page.append("size: %s;" % size)
    if margin:
        page.append("margin: %s;" % margin)
    page.append('@bottom-left { content: "%s"; }' % "\\A ".join(
        css_string(l) for l in footer_text(doc_id, revision, printed_at or now_label(), printed_by).split("\n")))
    if _u(issued).strip():
        page.append('@bottom-right { content: "%s"; }' % css_string("Issued: %s" % _u(issued).strip()))
    out.append("@page { %s }" % " ".join(page))
    return "\n".join(out)


def certificate_css(portal_url=None):
    """The stylesheet a section of an impress report carries: fonts and the
    lab theme, no @page (the report's own page size, margins and running
    header and footer are impress's)."""
    return font_face_css(portal_url) + "\n" + CSS


def lab_block(ps, logo=False, portal_url=u""):
    """The lab header row: mark or logo, name, address line, accreditation."""
    ps = ps or {}
    name = _u(ps.get("lab_name")).strip()
    contact = " · ".join(_u(ps.get(k)).strip()
                              for k in ("lab_address", "lab_phone", "lab_email")
                              if _u(ps.get(k)).strip())
    accred = _u(ps.get("accreditation")).strip()
    if logo and ps.get("logo_url"):
        from senaite.pfas.print_settings import logo_src
        mark = '<img class="pd-logo" src="%s" alt="%s"/>' % (esc(logo_src(ps, portal_url)), esc(name))
    else:
        mark = '<span class="pd-mark" aria-hidden="true">%s</span>' % esc(name[:1].upper() or "L")
    sub = "".join('<div class="pd-lab-sub">%s</div>' % esc(t) for t in (contact, accred) if t)
    return ('<table class="pd-lab"><tr><td style="width:46px">%s</td>'
            '<td><div class="pd-lab-name">%s</div>%s</td></tr></table>'
            % (mark, esc(name), sub))


def control_block(cells):
    """The bordered control grid. cells = [(label, value), ...]; an empty
    value is skipped (a cell that says nothing is not a control)."""
    cells = [(l, v) for l, v in cells if _u(v).strip()]
    if not cells:
        return ""
    row = "".join('<td><small>%s</small><b%s>%s</b></td>'
                  % (esc(l), ' class="pd-docid"' if i == 0 else "", esc(v))
                  for i, (l, v) in enumerate(cells))
    return ('<table class="pd-ctl" aria-label="Document control"><tr>%s</tr></table>' % row)


def head_html(ps, title, cells, subtitle=None, logo=False, portal_url=u""):
    """Lab header (mint rule), the document title and its control block."""
    out = [lab_block(ps, logo=logo, portal_url=portal_url), "<h1>%s</h1>" % esc(title)]
    if subtitle:
        out.append('<p class="muted">%s</p>' % esc(subtitle))
    out.append(control_block(cells))
    return "\n".join(out)


def current_user_label(context):
    """Full name of whoever is printing (their login when they have no name)."""
    from Products.CMFCore.utils import getToolByName
    member = getToolByName(context, "portal_membership").getAuthenticatedMember()
    return _u(member.getProperty("fullname", "") or member.getId() or "")


def print_settings(context):
    from Products.CMFCore.utils import getToolByName
    from senaite.pfas.print_settings import get_print_settings
    return get_print_settings(getToolByName(context, "portal_url").getPortalObject())
