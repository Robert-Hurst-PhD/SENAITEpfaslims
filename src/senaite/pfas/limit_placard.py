# -*- coding: utf-8 -*-
"""The placard a limit box carries: its state (limit_states) in colour and
a glyph, so it reads without colour too. The editor draws the glyph alone,
never a word: a box in a card shows it larger, in its top-right corner
(CORNER), and a grid or table cell a small glyph in its top-right corner
(MARK). The state is the glyph's label and hover, so a screen reader and a
pointer still read it, and the glyphs differ by shape. WORD, the pill with
its word, is kept for a page outside the editor that asks for it.

  Enforced  a filled dot    brand fill
  Evaluate  a half dot      the information tint
  Off       a struck ring   a dashed grey ring; the box greys, stays editable

Outlined: the state is not stored on this profile, it is the method default
(its seed). Coral marks only a box that is Enforced with no limit: the run
is refused.

A box's state posts once per tab, from a hidden input named
`limitstate.<box>` (hidden_cells, drawn with the tab's Table view); every
placard of that box, in either view, is nameless and names the box
(data-limit-box). A right click on the box (its tile, its cell, its tier
row) opens the shared menu with a State group (pfas-components.js), which
writes the input and redraws each placard of the box. The box greys while
its input holds Off (data-mute-if).

Pure; no Zope imports. Python 2.7 compatible.
"""
from __future__ import absolute_import, unicode_literals

import json
import re

from senaite.pfas import limit_states as ls

GLYPHS = {"enforced": "●", "evaluate": "◐", "off": "⦸"}
# the same three shapes drawn, for a glyph alone (CORNER, MARK): a text
# glyph's size and face vary by font, a drawn one is one square on every
# screen; currentColor, so the state's colour (and a forced colour) fills
# it. As the word placard is filled for a state set on this profile and
# outlined for the method default, so is the glyph: GLYPH_SVG filled,
# GLYPH_SVG_DEFAULT outlined; six shapes, told apart without colour
_SVG = ('<svg class="pfas-glyph" viewBox="0 0 16 16" focusable="false" aria-hidden="true">{0}</svg>')
_RING = '<circle cx="8" cy="8" r="5.75" fill="none" stroke="currentColor" stroke-width="1.5"/>'
GLYPH_SVG = {
    # a disc; a ring half filled; a disc cut by a slash
    "enforced": _SVG.format('<circle cx="8" cy="8" r="6.5" fill="currentColor"/>'),
    "evaluate": _SVG.format(_RING + '<path d="M8 1.5a6.5 6.5 0 0 0 0 13z" fill="currentColor"/>'),
    "off": _SVG.format('<path fill-rule="evenodd" fill="currentColor" d="M1.5 8a6.5 6.5 0 1 0 13 0a6.5 6.5 0 1 0-13 0z'
                       'M4.78 3.02l8.2 8.2-1.76 1.76-8.2-8.2z"/>'),
}
GLYPH_SVG_DEFAULT = {
    # a ring; a ring halved by a line; a ring struck through
    "enforced": _SVG.format(_RING),
    "evaluate": _SVG.format(_RING + '<path d="M8 2.25v11.5" stroke="currentColor" stroke-width="1.5"/>'),
    "off": _SVG.format(_RING + '<path d="M3.9 3.9l8.2 8.2" stroke="currentColor" stroke-width="1.5"/>'),
}
NO_LIMIT_WORDS = {"enforced": "No limit set: the run is refused",
                  "evaluate": "No limit set: advisory, the run goes on",
                  "off": "Not set"}
DEFAULT_WORDS = "the method default"
# a box that uses another window when empty, set Off: what it judges is not
# judged at all, so it never says it uses the other window
OFF_USES_WORDS = "Off: not judged"
INPUT_PREFIX = ls.POST_PREFIX

# how a placard is drawn: WORD the pill with glyph and word; CORNER the glyph
# alone in a card box's top-right corner; MARK a small glyph in a grid
# cell's top-right corner, taking no room of the cell's
WORD, CORNER, MARK = "word", "corner", "mark"
VARIANTS = (WORD, CORNER, MARK)
# a box in a card (boxed, choice_box, a tier row) shows CORNER
CARD_PLACARD = CORNER
# the standards grid's window cells (box_parts) show MARK
GRID_PLACARD = MARK
# QC criteria's Table view, a Limits cell's boxes (cell_html): the small
# glyph pinned to each line's top-right, as the standards grid's
CELL_PLACARD = MARK
# a table's choice cell (an action level, config_forms): the glyph alone,
# kept in its line (the box holds nothing else)
CHOICE_PLACARD = CORNER
STATE_LABEL = "State: {0}"


def _esc(v):
    from senaite.pfas.html_text import escape
    return escape(u"{0}".format(v))


def input_name(key):
    return INPUT_PREFIX + ls.encode_key(key)


def _empty(profile, key):
    parsed = ls.parse_tier_key(key)
    if parsed is not None:
        return False
    box = ls.BOX.get(key)
    return bool(box) and box["kind"] in (ls.NEEDED, ls.OPTIONAL) and ls.applies(profile, box) \
        and ls.is_empty(profile, box)


def _held(profile, key):
    parsed = ls.parse_tier_key(key)
    if parsed is not None:
        t = ls.find_tier(profile, parsed[0], parsed[1])
        return t is not None and t.get(ls.TIER_KEY) in ls.STATES
    return ls.is_stored(profile, key)


def _draw(cls, key, state, title, variant):
    """The placard's markup: WORD says the word after the glyph; CORNER and
    MARK are the glyph alone, an image whose label is the state, outlined
    while the state is the method default."""
    if variant not in VARIANTS:
        raise ValueError("a placard is drawn as one of {0}: {1}".format(VARIANTS, variant))
    if variant == WORD:
        glyph = '<span class="pfas-placard-g" aria-hidden="true">{0}</span>'.format(GLYPHS[state])
        return ('<span class="{0}" data-limit-placard="{1}" title="{2}">{3}'
                '<span class="pfas-placard-w">{4}</span></span>').format(
                    cls, _esc(key), _esc(title), glyph, _esc(ls.STATE_WORDS[state]))
    drawn = GLYPH_SVG_DEFAULT if "is-default" in cls.split() else GLYPH_SVG
    glyph = '<span class="pfas-placard-g" aria-hidden="true">{0}</span>'.format(drawn[state])
    return ('<span class="{0} is-{1}" data-limit-placard="{2}" role="img" aria-label="{3}" '
            'title="{4}">{5}</span>').format(cls, variant, _esc(key), _esc(STATE_LABEL.format(title)),
                                             _esc(title), glyph)


def placard(profile, key, state=None, variant=CARD_PLACARD):
    """The placard of box `key` as the profile holds it (`state`: as drawn,
    when the page draws a posted state), drawn as `variant`."""
    state = state or ls.state_of(profile, key) or "enforced"
    unset = state == "enforced" and _empty(profile, key)
    empty = _empty(profile, key)
    cls = "pfas-placard is-{0}{1}{2}{3}".format(state, "" if _held(profile, key) else " is-default",
                                              " is-empty" if empty else "", " is-unset" if unset else "")
    word = ls.STATE_WORDS[state]
    title = "{0}{1}".format(word, ", " + DEFAULT_WORDS if not _held(profile, key) else "")
    return _draw(cls, key, state, title, variant)


def box_attrs(profile, key):
    """The attributes of the element that is the box: its key, a Tab stop
    for the menu key, greyed while its state is Off."""
    return [("data-limit-box", key), ("data-limit-state", ls.state_of(profile, key) or "enforced"),
            ("data-limit-seed", seed_of(profile, key)), ("data-limit-label", label_of(profile, key)),
            ("tabindex", "0"), ("data-mute-if", input_name(key)), ("data-mute-values", "off")]


def seed_of(profile, key):
    """The state the method's own settings give the box (Use the method
    default sets it back to this)."""
    parsed = ls.parse_tier_key(key)
    if parsed is not None:
        t = ls.find_tier(profile, parsed[0], parsed[1])
        return ls.tier_seed(profile, parsed[0], t) if t is not None else "enforced"
    return ls.seed(profile, ls.BOX[key]) if key in ls.BOX else "enforced"


# a tier's name as the editor shows it: the seeded tiers' stored keys read
# as words (the key stays what is stored); a name the lab typed reads as typed
TIER_WORDS = {"tier1_key_tight": u"Regulated analytes, tight", "tier2_linked": u"Linked analytes",
              "tier3_no_std": u"No Matching Isotopes"}


def tier_words(name):
    """A tier's name in words (TIER_WORDS), else as it is stored."""
    return TIER_WORDS.get(name, name)


def label_of(profile, key):
    parsed = ls.parse_tier_key(key)
    if parsed is not None:
        return u"{0} {1}".format(parsed[0], tier_words(parsed[1]))
    return ls.BOX[key]["label"] if key in ls.BOX else key


def choice_box(name, label, value, values, off_value="off", tag="span", words="", cls="",
               variant=CHOICE_PLACARD, attrs=()):
    """A placard that is a choice field's own control, not a limit box of
    limit_states (an action level: printed or left off): it writes the
    field's input `name` (data-limit-values: [[state, posted value]] in its
    menu's order), greys while that input reads `off_value`, and offers no
    method default. `value` is the input's value as drawn."""
    state = next((st for st, v in values if v == (value or "")), values[0][0])
    attrs = [("class", " ".join(x for x in ("pfas-limit-box is-choice", cls, "is-muted" if state == "off" else "") if x)),
             ("data-limit-box", name), ("data-limit-state", state), ("data-limit-label", label),
             ("data-limit-values", json.dumps([list(x) for x in values])), ("tabindex", "0"),
             ("data-mute-if", name), ("data-mute-values", off_value)] + list(attrs)
    plac = _draw("pfas-placard is-{0}".format(state), name, state, ls.STATE_WORDS[state], variant)
    # `tag`, `words`: the element that is the box and what it says before
    # its placard (a list row: the limit's name)
    return "<{0}{1}>{2}{3}</{0}>".format(tag, "".join(' {0}="{1}"'.format(k, _esc(v)) for k, v in attrs),
                                          words, plac)


def box_parts(profile, key, variant=GRID_PLACARD):
    """(attributes, placard) of box `key` for an element a grid draws
    itself (a pair's cell): what boxed() puts on a tile."""
    return box_attrs(profile, key), placard(profile, key, variant=variant)


_OPEN = re.compile(r"^(\s*<([a-zA-Z0-9]+))([^>]*)>")


def boxed(html, profile, key, empty_words=None, first=False, variant=CARD_PLACARD):
    """`html`, one element (a tile, a cell, a row), made the box `key`: its
    attributes on the opening tag, greyed while Off, and the placard last
    inside it (`first`: first, before the words), drawn as `variant` (a
    card's tile: the corner glyph). `empty_words`: what an empty box says in
    place of its value (a box that uses another window)."""
    if not html or not key:
        return html
    m = _OPEN.match(html)
    if not m:
        return html
    state = ls.state_of(profile, key) or "enforced"
    attrs = m.group(3)
    if state == "off":
        if 'class="' in attrs:
            attrs = attrs.replace('class="', 'class="is-muted ', 1)
        else:
            attrs += ' class="is-muted"'
    extra = "".join(' {0}="{1}"'.format(k, _esc(v)) for k, v in box_attrs(profile, key)
                    if '{0}="'.format(k) not in attrs)
    tag = m.group(2)
    close = "</{0}>".format(tag)
    body = html[m.end():]
    plac = placard(profile, key, variant=variant)
    if first:
        body = plac + body
    elif body.endswith(close):
        body = body[:-len(close)] + plac + close
    else:
        body = body + plac
    if empty_words and state == "off" and _uses(key):
        empty_words = OFF_USES_WORDS
    if empty_words and 'data-set-blank="' not in attrs:
        # an empty window that uses another one says so, as the page
        # redraws it (data-set-blank)
        extra += ' data-set-blank="{0}"'.format(_esc(empty_words))
    out = "{0}{1}{2}>{3}".format(m.group(1), attrs, extra, body)
    if empty_words and _empty_uses(profile, key):
        out = out.replace(">{0}<".format(_esc(_not_set_words())), ">{0}<".format(_esc(empty_words)), 1)
    return out


def _not_set_words():
    from senaite.pfas import profile_grids
    return profile_grids.NOT_SET_WORDS


def _uses(key):
    box = ls.BOX.get(key)
    return bool(box) and box["kind"] == ls.USES


def _empty_uses(profile, key):
    box = ls.BOX.get(key)
    return bool(box) and box["kind"] == ls.USES and ls.is_empty(profile, box)


def uses_words(key):
    box = ls.BOX.get(key)
    return box.get("uses") if box else None


# ── which box a drawn field is ──────────────────────────────────────────────

# the boxes whose field a section draws under a name of its own (the
# worksheet size, the dilutions' lowest EIS recovery)
FIELD_BOXES = {"f__max_size": "worksheet_size", "f__eis_floor_pct": "dilution_eis_floor"}


def box_of_name(name):
    """The box an input of a section form is judged in (its name
    f__<section>__<key>, the worksheet's f__max_size), or None."""
    if name in FIELD_BOXES:
        return FIELD_BOXES[name]
    bits = (name or "").split("__")
    if len(bits) == 3 and bits[0] == "f":
        return ls.box_for_field(bits[1], bits[2])
    return None


def box_of_names(names):
    for n in names or ():
        key = box_of_name(n)
        if key:
            return key
    return None


# ── the one posted input per box ────────────────────────────────────────────

def keys(profile, codes=None, boxes=None):
    """Every box key a tab posts: `boxes` (default every box of BOXES), and
    each tier of each QC type in `codes` the method holds (default every
    held type)."""
    out = [b["key"] for b in ls.BOXES] if boxes is None else list(boxes)
    qca = (profile or {}).get("qc_acceptance") or {}
    for code in sorted(qca if codes is None else codes):
        for t in ls.tiers(profile, code):
            if t.get("name"):
                out.append(ls.tier_key(code, t))
    return out


def hidden_values(profile, keys_):
    """[(input name, state)] for each box, the state it reads; a project box
    with no state stored (limit_states.PROJECT_BOXES) posts blank until a
    person sets it, so a limit typed in the same save takes its own seed."""
    return [(input_name(k), "" if k in ls.PROJECT_BOXES and not ls.is_stored(profile, k)
             else ls.state_of(profile, k) or "enforced") for k in keys_]


# ── a box's value in words, for a read-only cell ────────────────────────────

def _units():
    from senaite.pfas import method_profile_sections as mps
    out = {}
    for f in mps.CALIBRATION_CCV.fields():
        if len(f.path) == 2:
            out[tuple(f.path)] = f.unit or u""
    return out


def _g(v):
    try:
        return u"{0:g}".format(float(v))
    except (TypeError, ValueError):
        return u"{0}".format(v)


def box_words(profile, key):
    """What the box holds, in words: a window "50 – 150 %", one limit with
    its unit, a tier's window or RPD; an empty box its "Uses ..." or Not
    set; a rule's own tile none."""
    parsed = ls.parse_tier_key(key)
    if parsed is not None:
        t = ls.find_tier(profile, parsed[0], parsed[1]) or {}
        if t.get("recovery_min") is not None and t.get("recovery_max") is not None:
            return u"{0} – {1} %".format(_g(t["recovery_min"]), _g(t["recovery_max"]))
        if t.get("rpd_max") is not None:
            return u"≤ {0} %".format(_g(t["rpd_max"]))
        if t.get("max_conc_x_rl") is not None:
            return u"{0} {1:.3g} × RL".format(u"<" if t.get("fails_at_limit") else u"≤",
                                                  float(t["max_conc_x_rl"]))
        return u"Not set"
    box = ls.BOX.get(key)
    if box is None or not box["fields"]:
        return u""
    if ls.is_empty(profile, box):
        if box.get("uses"):
            return OFF_USES_WORDS if ls.state_of(profile, key) == "off" else box["uses"]
        if box["kind"] in (ls.NEEDED, ls.OPTIONAL) and ls.applies(profile, box):
            # what an empty box means in its state: Enforced refuses the
            # run, Evaluate advises, Off is not judged
            return NO_LIMIT_WORDS[ls.state_of(profile, key) or "enforced"]
        return u"Not set"
    units = _units()
    vals = [ls._section(profile, g).get(k) for g, k in box["fields"]]
    unit = units.get(box["fields"][0], u"") if box["fields"][0][0] else u""
    if len(vals) == 2:
        return u"{0} – {1} {2}".format(_g(vals[0]), _g(vals[1]), unit).strip()
    return u"{0} {1}".format(_g(vals[0]), unit).strip()


def cell_html(profile, keys_, words=None):
    """A read-only cell holding one or more boxes: each its own line, its
    placard first, then its words, so a long limit wraps after the placard
    and never pushes it out of the cell; each its own box (a right click on
    it changes it alone); with several, each named."""
    keys_ = [k for k in keys_ if k]
    many = len(keys_) > 1
    out = []
    for k in keys_:
        w = (words or {}).get(k)
        w = box_words(profile, k) if w is None else w
        text = u"{0}: {1}".format(label_of(profile, k), w) if many else w
        out.append(boxed(u'<span class="pfas-limit-box"><span class="pfas-limit-w">{0}</span></span>'.format(
            _esc(text)), profile, k, first=True, variant=CELL_PLACARD))
    return u"".join(out)
