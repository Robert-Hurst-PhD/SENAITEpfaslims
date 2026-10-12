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

Python 2.7 and 3 compatible.
"""
from __future__ import absolute_import, unicode_literals

import datetime
import os

try:
    from xml.sax.saxutils import escape as _escape
except ImportError:                                         # pragma: no cover
    from cgi import escape as _escape

try:
    from senaite.pfas.print_style import CSS
except ImportError:                                         # tests: loaded without the package
    from print_style import CSS

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
    return _escape(_u(value), {'"': "&quot;"})


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


def footer_text(doc_id, revision=None, printed_at=None, printed_by=None):
    """"<doc id> rev <n> . printed <date> by <user> . uncontrolled when printed"."""
    parts = [_u(doc_id).strip()]
    if _u(revision).strip():
        parts[0] = "%s rev %s" % (parts[0], _u(revision).strip())
    if printed_at:
        parts.append("printed %s%s" % (_u(printed_at),
                                       " by %s" % _u(printed_by) if printed_by else ""))
    parts.append(UNCONTROLLED)
    return " · ".join(p for p in parts if p)


def now_label():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def document_css(doc_id, revision=None, printed_by=None, printed_at=None,
                 size=None, margin=None, fonts=True, base=True):
    """The whole <style> text for one controlled document.

    size   a CSS page size ("letter", "A4 landscape"); leave None in a browser,
           where the person's own paper setting decides.
    margin a CSS margin ("14mm 12mm 16mm"); None keeps the stylesheet's.
    fonts  False when the browser already has the fonts (the page macro loads
           the add-on's woff2 files through pfas-tokens.css).
    base   False for a page that links pfas-print.css itself: only the @page rule
           naming this document is written, so the full stylesheet is not repeated
           in every page and never applies on screen.
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
    page.append('@bottom-left { content: "%s"; }' % css_string(
        footer_text(doc_id, revision, printed_at or now_label(), printed_by)))
    out.append("@page { %s }" % " ".join(page))
    return "\n".join(out)


def certificate_css(portal_url=None):
    """The stylesheet a section of an impress report carries: fonts and the
    lab theme, no @page (the report's own page size, margins and running
    header and footer are impress's)."""
    return font_face_css(portal_url) + "\n" + CSS


def lab_block(ps, logo=False):
    """The lab header row: mark or logo, name, address line, accreditation."""
    ps = ps or {}
    name = _u(ps.get("lab_name")).strip()
    contact = " · ".join(_u(ps.get(k)).strip()
                              for k in ("lab_address", "lab_phone", "lab_email")
                              if _u(ps.get(k)).strip())
    accred = _u(ps.get("accreditation")).strip()
    if logo and ps.get("logo_url"):
        mark = '<img class="pd-logo" src="%s" alt="%s"/>' % (esc(ps["logo_url"]), esc(name))
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


def head_html(ps, title, cells, subtitle=None, logo=False):
    """Lab header (mint rule), the document title and its control block."""
    out = [lab_block(ps, logo=logo), "<h1>%s</h1>" % esc(title)]
    if subtitle:
        out.append('<p class="muted">%s</p>' % esc(subtitle))
    out.append(control_block(cells))
    return "\n".join(out)


def current_user_label(context):
    """Full name of whoever is printing (their login when they have no name)."""
    try:
        from Products.CMFCore.utils import getToolByName
        member = getToolByName(context, "portal_membership").getAuthenticatedMember()
        return _u(member.getProperty("fullname", "") or member.getId() or "")
    except Exception:                                        # noqa: BLE001
        return ""


def print_settings(context):
    try:
        from Products.CMFCore.utils import getToolByName
        from senaite.pfas.print_settings import get_print_settings
        return get_print_settings(getToolByName(context, "portal_url").getPortalObject())
    except Exception:                                        # noqa: BLE001
        return {}
