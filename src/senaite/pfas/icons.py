# -*- coding: utf-8 -*-
"""The one icon helper: every icon a page draws comes from here.

Icons carry the state, words carry the name. Shape says what kind of thing
it is, fill and outline its state, a corner mark a flag; colour only repeats
what the shape says. Every drawing is on a 24 grid with a 2-unit margin, one
1.5 line with round joins (the class sets it), and at most one accent
(class pfas-icon-a, filled). Outcome marks are filled shapes (pfas-icon-f)
or a heavy line (pfas-icon-w), so they keep their weight at 16 px.

No drawing's outline is a circle: circles are the limit box's state glyphs
(limit_placard.py). The certificate draws none of these.

Families: outcome (pass, warn, fail, unjudged, note, waiting, sent-back),
stage (received, extraction, analysis, verify, issued), sign-off,
document, lot, action. A sample type is `type:<code>` and is drawn by
sample_type_icons, unchanged.

    svg(name, label=None, state=None, mark=None, size=None, hidden=False)
    tip(name, label, **kw)    a focusable icon whose words show as a tooltip
                              on hover, keyboard focus and a long press
    mark(kind, label)         an outcome mark: pass, warn, fail, unjudged, note
    spec()                    the drawings as JSON for pfas-components.js

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import json
import math

from senaite.pfas import sample_type_icons as sti
from senaite.pfas.html_text import escape


def _cross(cx=12.0, cy=12.0, a=3.7, w=1.0):
    """A saltire as one outline, knocked out of the failure diamond."""
    pts = [(-w, -a), (w, -a), (w, -w), (a, -w), (a, w), (w, w), (w, a), (-w, a),
           (-w, w), (-a, w), (-a, -w), (-w, -w)]
    c = math.cos(math.pi / 4)
    s = math.sin(math.pi / 4)
    q = ["%.2f %.2f" % (cx + x * c - y * s, cy + x * s + y * c) for x, y in pts]
    return "M" + "L".join(q) + "Z"


_PAGE = '<path d="M6 3.75h8.25L18 7.5v12.75H6Z"/><path d="M14.25 3.75V7.5H18"/>'
_NIB = ('<path d="M12 3 17.25 9.25 14 18h-4L6.75 9.25Z"/><path d="M12 12.5V18"/>'
        '<rect x="11" y="9.6" width="2" height="2" rx=".5"/>')
_BOTTLE = '<path d="M10.5 4.5v4L7 13.5v6.75h10V13.5l-3.5-5v-4"/>'

DRAWINGS = {
    # outcomes: the mark is the outcome
    "pass": '<path class="pfas-icon-w" d="M5.5 12.5l4 4L18.75 7.25"/>',
    "warn": ('<path class="pfas-icon-f" fill-rule="evenodd" d="M12 2.75 22 20.5H2Z'
             'M11.1 9.25h1.8v5.6h-1.8ZM11.1 16.4h1.8v1.8h-1.8Z"/>'),
    "fail": ('<path class="pfas-icon-f" fill-rule="evenodd" d="M12 1.75 22.25 12 12 22.25 1.75 12Z'
             + _cross() + '"/>'),
    "unjudged": '<path stroke-dasharray="2.4 2.2" d="M12 3.25 20.75 12 12 20.75 3.25 12Z"/>',
    "note": ('<path d="M4.75 4.75h14.5v10.5h-7.5l-4 3.75v-3.75h-3Z"/>'
             '<rect class="pfas-icon-a" x="11.1" y="6.9" width="1.8" height="1.8" rx=".4"/>'
             '<rect class="pfas-icon-a" x="11.1" y="9.6" width="1.8" height="3.9" rx=".4"/>'),
    "waiting": ('<path d="M7 3.75h10M7 20.25h10"/><path d="M8.25 3.75c0 4.5 3.75 4.75 3.75 8.25s-3.75 3.75-3.75 8.25'
                'M15.75 3.75c0 4.5-3.75 4.75-3.75 8.25s3.75 3.75 3.75 8.25"/>'
                '<path class="pfas-icon-a" d="M9.6 18.5h4.8L12 15.75Z"/>'),
    "sent-back": '<path class="pfas-icon-w" d="M19.5 19v-4.25a4 4 0 0 0-4-4H5.5M9.75 6.5 5.5 10.75 9.75 15"/>',
    # workflow stages: the accent filled when done, outlined now, dashed to come
    "received": ('<path d="M3.75 13.75h4.5l1.5 2.25h4.5l1.5-2.25h4.5v6.5H3.75Z"/>'
                 '<rect class="pfas-icon-a" x="9" y="4" width="6" height="6.5" rx="1"/>'),
    "extraction": ('<path d="M7 3.75h10"/><path d="M8 3.75v10l2.25 3.25v3.25h3.5V17L16 13.75v-10"/>'
                   '<rect class="pfas-icon-a" x="8" y="8" width="8" height="3.5"/>'),
    "analysis": ('<path d="M3.25 20h17.5"/><path class="pfas-icon-a" d="M4 20c3.2 0 3.7-14.25 8-14.25S16.8 20 20 20Z"/>'
                 '<path d="M4 20c3.2 0 3.7-14.25 8-14.25S16.8 20 20 20"/>'),
    "verify": '<path d="M2.75 12.75l3.5 3.5 6.25-6.75"/><path class="pfas-icon-w" d="M10 15.25l2 2L21.25 7.5"/>',
    "issued": (_PAGE + '<path d="M10.5 15.5 9.75 21 12 19.6l2.25 1.4-.75-5.5"/>'
               '<rect class="pfas-icon-a" x="9.25" y="10" width="5.5" height="5.5" rx="2.75"/>'),
    # sign-off: a pen nib
    "sig-wait": _NIB + '<path stroke-dasharray="1.6 1.9" d="M5 21h14"/>',
    "sig-signed": _NIB + '<rect class="pfas-icon-a" x="4.75" y="20" width="14.5" height="2" rx=".6"/>',
    "sig-withdrawn": _NIB + '<path d="M4.5 4.5l15 15"/>',
    # documents: a page with a folded corner
    "doc-draft": '<g stroke-dasharray="2.2 2">' + _PAGE + '</g>',
    "doc-issued": _PAGE + '<rect class="pfas-icon-a" x="8.5" y="10.5" width="7" height="7" rx="1"/>',
    "doc-superseded": _PAGE + '<path d="M3.5 14h17"/>',
    "doc-revoked": _PAGE + '<path d="M3.75 3.75l16.5 16.5"/>',
    # lots: a bottle
    "lot": '<path d="M9.75 4.5h4.5"/>' + _BOTTLE + '<path class="pfas-icon-a" d="M7 15h10v5.25H7Z"/>',
    "lot-opened": '<path d="M14.25 2.75l3 1.5"/>' + _BOTTLE + '<path class="pfas-icon-a" d="M7 15h10v5.25H7Z"/>',
    "lot-archived": '<g stroke-dasharray="2.2 2"><path d="M9.75 4.5h4.5"/>' + _BOTTLE + '</g>',
    # actions: line pictograms
    "search": '<rect x="4" y="4" width="13" height="13" rx="6.5"/><path d="M15.25 15.25 20.25 20.25"/>',
    "bell": '<path d="M6.5 16.5V11a5.5 5.5 0 0 1 11 0v5.5l1.5 2h-14Z"/><path d="M10 21h4"/>',
    "settings": ('<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><rect x="13" y="5" width="4" height="4" rx="1"/>'
                 '<rect x="7" y="15" width="4" height="4" rx="1"/>'),
    "add": '<path d="M12 5v14M5 12h14"/>',
    "close": '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
    "more": ('<rect class="pfas-icon-a" x="4.25" y="10.75" width="3" height="2.5" rx=".7"/>'
             '<rect class="pfas-icon-a" x="10.5" y="10.75" width="3" height="2.5" rx=".7"/>'
             '<rect class="pfas-icon-a" x="16.75" y="10.75" width="3" height="2.5" rx=".7"/>'),
    "menu": '<path d="M4 7h16M4 12h16M4 17h16"/>',
    "back": '<path d="M19 12H5M10.5 6.5 5 12l5.5 5.5"/>',
    "open": '<path d="M9.5 6l6 6-6 6"/>',
    "expand": '<path d="M6 9.5l6 6 6-6"/>',
    "download": '<path d="M12 4v11M7.5 10.5 12 15l4.5-4.5M4.5 19.5h15"/>',
    "upload": '<path d="M12 15V4M7.5 8.5 12 4l4.5 4.5M4.5 19.5h15"/>',
    "print": '<path d="M7 9V4h10v5M7 16H5V9h14v7h-2"/><path d="M7.5 13.5h9v6.5h-9Z"/>',
    "edit": '<path d="M15.5 4.5l4 4L9 19H5v-4Z"/><path d="M13.5 6.5l4 4"/>',
    "delete": '<path d="M4.5 6.5h15M9 6.5v-2h6v2M6.5 6.5l1 13.5h9l1-13.5M10 10v6.5M14 10v6.5"/>',
    "pin": '<path d="M9 4h6M10 4v5.5L7 13h10l-3-3.5V4M12 13v7"/>',
    "lock": '<rect x="5.5" y="11" width="13" height="9" rx="2"/><path d="M8.5 11V8a3.5 3.5 0 0 1 7 0v3"/>',
    "date": '<rect x="4" y="5.5" width="16" height="14.5" rx="2"/><path d="M4 10h16M8.5 3.5v4M15.5 3.5v4"/>',
    "time": '<rect x="4" y="4" width="16" height="16" rx="5"/><path d="M12 8v4.5l3 2"/>',
    "help": ('<rect x="4" y="4" width="16" height="16" rx="4.5"/>'
             '<path d="M9.75 9.75a2.25 2.25 0 1 1 3.4 1.95c-.7.45-1.15.9-1.15 1.8"/>'
             '<rect class="pfas-icon-a" x="11.2" y="15.4" width="1.6" height="1.6" rx=".4"/>'),
    "external": '<path d="M14 4.5h5.5V10M19.5 4.5 11 13M17 13.5v5.5H5.5V7.5H11"/>',
    "filter": '<path d="M4 7h16M7 12h10M10 17h4"/>',
    "person": '<rect x="8" y="3.5" width="8" height="8" rx="4"/><path d="M4.5 20.5v-1a5 5 0 0 1 5-5h5a5 5 0 0 1 5 5v1"/>',
    "building": ('<path d="M5 21V4.5a1.5 1.5 0 0 1 1.5-1.5h8A1.5 1.5 0 0 1 16 4.5V21"/><path d="M16 9h2.5A1.5 1.5 0 0 1 20 10.5V21"/>'
                 '<path d="M3 21h18"/><path d="M9 7h3M9 11h3M9 15h3"/>'),
    "sign-out": '<path d="M10 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h4"/><path d="M14 8l4 4-4 4"/><path d="M18 12H9"/>',
    "badge": ('<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 3v3h6V3"/>'
              '<rect x="9.5" y="9" width="5" height="5" rx="2.5"/><path d="M8.5 17.5h7"/>'),
    # the system tour: a signpost, a custody form, a thermometer, a table sent out
    "tour": ('<path d="M12 3.5V21M8 21h8"/><path d="M12 5.25h6.5l2 2.5-2 2.5H12Z"/>'
             '<path class="pfas-icon-a" d="M12 12.5H5.5l-2 2.5 2 2.5H12Z"/>'),
    "custody": ('<rect x="5" y="4.5" width="14" height="16" rx="2"/><path d="M9 4.5V3.25h6V4.5"/>'
                '<path d="M8.5 9.5h7M8.5 12.5h7"/><rect class="pfas-icon-a" x="8.5" y="15.25" width="7" height="2" rx=".6"/>'),
    "temperature": ('<path d="M9.75 14.25V5.5a2.25 2.25 0 0 1 4.5 0v8.75a4 4 0 1 1-4.5 0Z"/>'
                    '<rect class="pfas-icon-a" x="11.2" y="9" width="1.6" height="7.5" rx=".5"/>'),
    "edd": ('<rect x="3.75" y="4.75" width="12.5" height="14.5" rx="1.5"/><path d="M3.75 9.5h12.5M3.75 14.25h12.5M9.9 4.75v14.5"/>'
            '<path class="pfas-icon-w" d="M17.5 12h3.5M19.25 10.25 21 12l-1.75 1.75"/>'),
}

FAMILY = {}
for _n in ("pass", "warn", "fail", "unjudged", "note", "waiting", "sent-back"):
    FAMILY[_n] = "outcome"
for _n in ("received", "extraction", "analysis", "verify", "issued"):
    FAMILY[_n] = "stage"
for _n in ("sig-wait", "sig-signed", "sig-withdrawn"):
    FAMILY[_n] = "sign-off"
for _n in ("doc-draft", "doc-issued", "doc-superseded", "doc-revoked"):
    FAMILY[_n] = "document"
for _n in ("lot", "lot-opened", "lot-archived"):
    FAMILY[_n] = "lot"
for _n in DRAWINGS:
    FAMILY.setdefault(_n, "action")

# The meaning colour of a drawing, an --ico-* token (pfas-tokens.css);
# a drawing not named here takes the text colour.
COLOUR = {"pass": "ok", "warn": "warn", "fail": "fail", "unjudged": "neutral", "note": "info",
          "waiting": "info", "sent-back": "warn",
          "received": "brand", "extraction": "brand", "analysis": "brand", "verify": "brand", "issued": "brand",
          "sig-wait": "neutral", "sig-signed": "ok", "sig-withdrawn": "neutral",
          "doc-draft": "neutral", "doc-issued": "brand", "doc-superseded": "neutral", "doc-revoked": "neutral",
          "lot-archived": "neutral"}
TOKENS = ("brand", "ok", "info", "warn", "fail", "neutral", "pale")

# The words of a drawing when nothing more is said: its accessible name.
WORDS = {"pass": "Pass", "warn": "Warning", "fail": "Failure", "unjudged": "Not judged", "note": "Note",
         "waiting": "Waiting", "sent-back": "Sent back",
         "received": "Received", "extraction": "Extraction", "analysis": "Analysis", "verify": "Verify",
         "issued": "Certificate issued",
         "sig-wait": "Waiting for a signature", "sig-signed": "Signed", "sig-withdrawn": "Signature withdrawn",
         "doc-draft": "Draft", "doc-issued": "Issued", "doc-superseded": "Superseded", "doc-revoked": "Revoked",
         "lot": "In date", "lot-opened": "Opened", "lot-archived": "Archived",
         "tour": "System tour", "custody": "Chain of custody", "temperature": "Temperature", "edd": "Data deliverable"}

# Corner marks: a flag on a 24 px icon's lower right, over a halo of the
# ground. At 16 px the flag stands as its own outcome mark instead.
MARKS = {
    "warn": '<path d="M18.25 12.75 23.5 22.5H13Z"/>',
    "fail": '<path d="M18.25 12.5 23.75 18 18.25 23.5 12.75 18Z"/>',
    "wait": ('<path class="pfas-icon-w" d="M14.25 13.25h7.5M14.25 22.75h7.5M15.25 13.25c0 3.1 2.75 3.1 2.75 4.75'
             's-2.75 1.65-2.75 4.75M20.75 13.25c0 3.1-2.75 3.1-2.75 4.75s2.75 1.65 2.75 4.75"/>'),
    "back": '<path class="pfas-icon-w" d="M22.25 22.5v-3.25a2.75 2.75 0 0 0-2.75-2.75H14.25M17 13.75l-2.75 2.75L17 19.25"/>',
}
MARK_COLOUR = {"warn": "warn", "fail": "fail", "wait": "info", "back": "warn"}
STATES = ("done", "now", "next")
SIZES = ("sm", "md", "lg", "xl")


def _text(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return "%s" % (value,)


def _esc(text):
    return escape(_text(text))


def _mark(kind):
    body = MARKS[kind]
    halo = body.replace('class="pfas-icon-w"', 'class="pfas-icon-halo is-line"').replace(
        '<path d=', '<path class="pfas-icon-halo" d=')
    if 'class="pfas-icon-w"' not in body:
        body = body.replace('<path d=', '<path class="pfas-icon-f" d=')
    return '<g class="pfas-icon-mark is-%s">%s%s</g>' % (MARK_COLOUR[kind], halo, body)


def classes(name, state=None, mark=None, size=None, colour=None):
    out = ["pfas-icon", "is-" + name]
    tone = colour or COLOUR.get(name)
    if state == "next":
        tone = "neutral"
    if tone:
        out.append("is-" + tone)
    if state in STATES:
        out.append("is-" + state)
    if size in SIZES and size != "sm":
        out.append("is-" + size)
    return " ".join(out)


def svg(name, label=None, state=None, mark=None, size=None, hidden=False, colour=None):
    """One icon. `label`: its accessible name and hover words (default: the
    drawing's own word). `hidden`: words beside it say the same, so a
    screen reader skips it. A sample type is "type:<code>"."""
    name = _text(name)
    if name.startswith("type:"):
        return sti.svg(name[5:], sub=label, hidden=hidden)
    if name not in DRAWINGS:
        return ""
    words = _text(label) if label else WORDS.get(name, name)
    attrs = 'aria-hidden="true"' if hidden else 'role="img" aria-label="%s"' % _esc(words)
    title = "" if hidden else "<title>%s</title>" % _esc(words)
    m = _mark(mark) if mark in MARKS else ""
    return ('<svg class="%s" viewBox="0 0 24 24" focusable="false" %s>%s%s%s</svg>'
            % (classes(name, state, mark, size, colour), attrs, title, DRAWINGS[name], m))


def tip(name, label, **kw):
    """An icon standing alone, as in a table's status column: it takes focus,
    and its words show on hover, focus and a long press (pfas-components.js
    `.pfas-tip`), as its accessible name."""
    kw["hidden"] = True
    icon = svg(name, label, **kw)
    if not icon:
        return _esc(label)
    words = _esc(label)
    return ('<span class="pfas-tip" tabindex="0" role="img" aria-label="%s" data-pfas-tip="%s">%s</span>'
            % (words, words, icon))


def mark(kind, label=None, size=None):
    """An outcome mark: pass, warn, fail, unjudged or note."""
    return svg(kind, label=label, size=size)


# a workflow stage's step as the stage lists give it (sample_status
# _build_stage_steps): done, current, pending; drawn done, now, next
STEP_STATE = {"done": "done", "current": "now", "pending": "next"}
STEP_WORDS = {"done": "done", "current": "now", "pending": "to come"}


def stage(icon, label, status, size=None, hidden=False):
    """A workflow stage's own picture, filled when done, outlined in brand
    where the work is now, dashed and pale to come; its name is the stage
    and where it stands ("Extraction, done")."""
    state = STEP_STATE.get(status, "next")
    words = "%s, %s" % (_text(label), STEP_WORDS.get(status, "to come"))
    return svg(icon, words, state=state, size=size, hidden=hidden)


# a record's status chip (its badge class) as a picture: what is fine draws
# nothing (the owner, 2026-11-20: no mark on a lot that is fine); opened is
# the bottle with its cap off; quarantine, pending and expired the bottle
# with its flag; used up or archived the dashed bottle. A document takes the
# page. A status no picture says keeps its word (None).
_STATUS = {
    "lot": {"active": None, "ok": None, "opened": ("lot-opened", None), "expired": ("lot", "fail"),
            "quarantine": ("lot", "warn"), "pending": ("lot", "wait"), "exhausted": ("lot-archived", None),
            "archived": ("lot-archived", None)},
    "document": {"active": None, "ok": None, "draft": ("doc-draft", None), "expired": ("doc-issued", "fail"),
                 "archived": ("doc-superseded", None)},
}


def status_mark(badge_cls, label, reasons=(), family="lot"):
    """The status a list's chip said in words, as a picture with the words
    for its name and tooltip; with reasons (what needs doing) the warning
    mark. "" when there is nothing to show; None when no picture says it."""
    label = _text(label)
    reasons = [r for r in (reasons or ()) if r]
    if reasons:
        return tip("warn", u"%s: %s" % (label, u"; ".join(_text(r) for r in reasons)))
    kinds = _STATUS.get(family, {})
    for c in _text(badge_cls).split():
        key = c[6:] if c.startswith("badge-") else None
        if key is None or key not in kinds:
            continue
        shape = kinds[key]
        if shape is None:
            return ""
        name, flag = shape
        return tip(name, label, mark=flag, size="lg" if flag else None)
    return None


def spec():
    """The drawings, marks, colours and words as JSON, for pfas-components.js."""
    return json.dumps({"drawings": DRAWINGS, "marks": dict((k, _mark(k)) for k in MARKS),
                       "colour": COLOUR, "words": WORDS},
                      sort_keys=True, separators=(",", ":")).replace("</", "<\\/")
