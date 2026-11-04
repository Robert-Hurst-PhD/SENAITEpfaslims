# -*- coding: utf-8 -*-
"""The method profile's grids: one model, one renderer.

Every tab of the method profile editor is one grid (a sheet): a row per
analyte, standard, rule or matrix, a column per criterion. A tab's builder
returns a `Sheet`; `render_sheet` draws any sheet the same way, and the
`sheet` macro (browser/templates/grid_macros.pt) is the one place a page
calls it. pfas-components.js (PFAS.components.sheet) adds the selection bar,
the column switches, the links popover and the multi-row drawer.

What the markup keeps to:
  - a cell posts under its section's own input name, so config_forms.parse,
    the section stamps and the configuration history work unchanged;
  - a number or a min / max pair is the config table's cell input, which
    openCell turns into a value button edited in the drawer, never in the cell;
  - a default is what blank means (a placeholder), never a value: an
    inherited cell posts empty and shows where its value comes from (a
    switch has no blank: an inherited switch posts the value it shows);
  - the method profile's section forms are empty <form>s the inputs point
    at, so a sheet with a `form` writes form="<id>" on every posted control;
  - a cell's state is how it is drawn (set, inherited, off, locked,
    read-only), never a control beside it;
  - a section form always carries all of its fields (config_forms.parse
    reads an absent field as cleared), so a locked or read-only cell with a
    name posts its stored value through hidden inputs;
  - a row's drawer is the same cells as a vertical list, drawn here into a
    <template>, so the script needs no second renderer;
  - every value is escaped, and nothing carries a style attribute or a colour.

Pure; no Zope imports. Python 2.7 compatible.
"""
from __future__ import absolute_import, unicode_literals

import json
import re
from collections import OrderedDict

from senaite.pfas.qc.rules import STATES as RULE_STATES
from senaite.pfas import help_dictionary
from senaite.pfas import lab_time
from senaite.pfas.html_text import escape

try:
    _TEXT = unicode        # noqa: F821  (Py2.7)
except NameError:          # pragma: no cover  (Py3 tests)
    _TEXT = str

KINDS = ("text", "num", "pair", "select", "switch", "flag", "links", "state", "chips", "menu")
# na: the analyte is not reported in the column's matrices (no value, no input)
STATES = ("set", "inherited", "off", "locked", "readonly", "na")
ALIGNS = ("left", "right", "center")
EN_DASH = "–"
EM_DASH = "—"
# what a cell for an analyte not reported in a matrix reads
NOT_REPORTED = "not reported"
# what a bulk bar does to the ticked rows besides Edit selected and Clear
# selection: one column of a select (named by the action), and the matrix
# layout's own (the panel in a matrix, a matrix copied from another, the
# inherited values put back)
COLUMN_ACTIONS = ("set-quant",)
MATRIX_ACTIONS = ("set-panel", "copy-column", "reset-inherited")
# how Edit selected lays the ticked rows out: None, the row's fields as a
# list; "matrix", a table row per flag column (a matrix: its flag and the RL
# and MDL inputs the flag names), then the row's other fields
LAYOUTS = (None, "matrix")


class Column(object):
    """One criterion. `group` heads several columns with one spanning
    heading; a column with `default=False` starts hidden and is offered in
    the column picker; `unit` is the heading's second line (a pair's unit
    goes with its cells, so it is shown once); `sub` is a line under the
    heading (what a column that stands for several matrices lists);
    `min`, `max` and `step` are a number's or a pair's declared limits,
    which the drawer's stepper keeps to; `matrices` the matrices a column
    of the window grid stands for, drawn on its heading as data-matrices
    (JSON: a matrix name is never split out of words). A "menu" column is
    each row's ⋯ button (its cell's data on the button), which posts
    nothing and is never a drawer field. A "state" column with `word`
    shows its state as a word (td.pfas-sheet-role) beside the hidden input
    it posts; the row's drawer edits it with the segmented control."""

    def __init__(self, key, label, kind, align="left", group=None, default=True, unit=None,
                 min=None, max=None, step=None, sub=None, matrices=None, word=False):
        if kind not in KINDS:
            raise ValueError("unknown column kind: {0}".format(kind))
        if align not in ALIGNS:
            raise ValueError("unknown alignment: {0}".format(align))
        if word and kind != "state":
            raise ValueError("only a state column is drawn as a word: {0}".format(key))
        self.key = key
        self.label = label
        self.kind = kind
        self.align = align
        self.group = group
        self.default = default
        self.unit = unit
        self.sub = sub
        self.matrices = matrices
        self.min = min
        self.max = max
        self.step = step
        self.word = word

    @property
    def span(self):
        """A pair is two table cells (its min and its max input)."""
        return 2 if self.kind == "pair" else 1


class Cell(object):
    """One value. `name` is the posted input name (a pair's is a
    (min name, max name) tuple and its value a (min, max) tuple); `source`
    names where an inherited value comes from, or what a set value
    overrides; `options` are a select's or a state's [(value, label)];
    `links` are a links cell's [(label, href)], and on a read-only cell of
    any other column its navigation buttons, drawn after its words;
    `title` replaces the hover; `expands` is the id of the region the cell's
    button opens and closes (its value is the button's words); `data` are
    data-* attributes on the cell, for a page's own script. A flag (a
    reported / left-out mark that posts a box, never a switch) is its words
    (✓, ✗ or the RL it carries) with data {"in": bool, "rl": the RL as
    words, "rl_name": the RL input's name, or None where there is none}.
    `flags` are chips drawn in the cell after its value, as a row's are;
    `none` makes a pair one that can be marked "not assessed": (the
    marker box's input name, whether it is marked, what the cell is
    called in "Not assessed for <it>"); marked, it draws ✗ and its pair
    posts blank. A number cell can carry one too, its box posting the
    word "none" under the cell's own name while the number is off: the
    cell's data then say its hover and editor words (none-hover,
    none-text), and set-none "1" draws its none as a dash, a value, not
    the not-assessed cross."""

    def __init__(self, value, state="set", source=None, name=None, options=None, links=None, title=None,
                 expands=None, data=None, flags=(), none=None):
        if state not in STATES:
            raise ValueError("unknown cell state: {0}".format(state))
        self.value = value
        self.state = state
        self.source = source
        self.name = name
        self.options = options
        self.links = links
        self.title = title
        self.expands = expands
        self.data = data
        self.flags = tuple(flags or ())
        self.none = tuple(none) if none else None


class Row(object):
    """One analyte, standard, rule or matrix. `cells` is a list in column
    order or a dict keyed by column key; the Sheet keys it by column. A flag
    is words: a coral chip that marks the row, or a (words, "warn") pair, an
    amber chip that leaves the row unmarked. `data` are data-* attributes
    on the row, for a page's own script (a list is written as JSON). A
    group row of a folding sheet says what its members hold in `summary`."""

    def __init__(self, key, label, cells, sub=None, group=None, selectable=True, flags=(), data=None,
                 summary=None):
        self.key = key
        self.summary = summary
        self.label = label
        self.cells = cells
        self.sub = sub
        self.group = group
        self.selectable = selectable
        self.flags = tuple(flags or ())
        self.data = data


class Sheet(object):
    """One grid. `groups` are the row groups in order, each a (key, label)
    or a Row whose cells fill the group's heading row; `column_switches`
    names switch columns that get one switch setting every row, and flag
    columns that get a "✓ all" chip marking every row in; `form` is
    the id of the form the posted controls belong to; `hidden` are Cells
    posted as they are, never drawn (a field the section reads that no
    column shows); `layout` is how Edit selected lays the ticked rows out
    (LAYOUTS); `actions` are the bulk bar's one-column actions,
    (action, label) or, for a COLUMN_ACTION, (action, label, column key).
    Membership by its own forms, above the grid: `adder` (form id, input
    name, chooser id, heading, the chooser's label, [(value, label)]) is
    Add, opening a chooser of what can join (none to offer, no Add; a
    seventh item names the kind the unsaved counter reads the pick as; a
    chooser posting with the sheet's own form starts on a blank choice, or
    every Save would add the first);
    `remover` (form id, input name) is Remove, posting the ticked rows'
    keys; only a row that is a member (data {"member": "1"}) is taken: a
    spare row ticked for Edit selected is not.
    `fold` folds every group to its group row (the members hidden until the
    group is opened, the group row's `sub` then its `summary`) and names
    the view whose open groups the page remembers (data-fold); with
    selection, a group row's box ticks its members.
    `help` names the Help entry of a grid that is no section: its one Help
    button sits at the right end of the tools row (a grid inside a section
    has its section's, in the section's header)."""

    def __init__(self, id, columns, rows, groups=None, sticky_first=True, selection=True, picker=True,
                 column_switches=None, form=None, hidden=None, layout=None, actions=None, adder=None,
                 remover=None, fold=None, help=None):
        if layout not in LAYOUTS:
            raise ValueError("unknown layout: {0}".format(layout))
        self.id = id
        self.layout = layout
        self.form = form
        self.adder = tuple(adder) if adder else None
        self.remover = tuple(remover) if remover else None
        self.hidden = list(hidden or ())
        self.columns = list(columns)
        self.rows = list(rows)
        self.groups = [g if isinstance(g, Row) else Row(g[0], g[1], {}, selectable=False) for g in groups or ()]
        self.sticky_first = sticky_first
        self.selection = selection
        self.picker = picker
        self.fold = fold
        self.help = help
        self.column_switches = list(column_switches or ())
        kinds = dict((c.key, c.kind) for c in self.columns)
        for key in self.column_switches:
            if kinds.get(key) not in ("switch", "flag"):
                raise ValueError("a column switch heads a switch or a flag column: {0}".format(key))
        for row in self.rows + self.groups:
            row.cells = _keyed(self.columns, row.cells, row.key)
        self.actions = [tuple(a) for a in actions or ()]
        for a in self.actions:
            if a[0] in COLUMN_ACTIONS:
                if len(a) != 3 or kinds.get(a[2]) != "select":
                    raise ValueError("{0} names a select column: {1}".format(a[0], a[2:]))
            elif a[0] not in MATRIX_ACTIONS or len(a) != 2:
                raise ValueError("unknown action: {0}".format(a[0]))
            elif layout != "matrix":
                raise ValueError("{0} needs the matrix layout".format(a[0]))


def _keyed(columns, cells, row_key):
    keys = [c.key for c in columns]
    if isinstance(cells, dict):
        unknown = [k for k in cells if k not in keys]
        if unknown:
            raise ValueError("row {0}: no column {1}".format(row_key, unknown))
        return OrderedDict((k, cells[k]) for k in keys if cells.get(k) is not None)
    cells = list(cells or ())
    if len(cells) > len(keys):
        raise ValueError("row {0}: {1} cells for {2} columns".format(row_key, len(cells), len(keys)))
    return OrderedDict((k, c) for k, c in zip(keys, cells) if c is not None)


# ── text and markup ─────────────────────────────────────────────────────────

def _text(v):
    if v is None:
        return ""
    if isinstance(v, bytes):
        return v.decode("utf-8")
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return _TEXT(v)


def _esc(v):
    return escape(_text(v))


def _attrs(pairs):
    """' k="v"' for each pair in order; None and False leave the attribute out,
    True writes it as k="k"."""
    out = []
    for k, v in pairs:
        if v is None or v is False:
            continue
        out.append(' {0}="{1}"'.format(k, _esc(k if v is True else v)))
    return "".join(out)


def _tag(name, pairs, inner=None):
    if inner is None:
        return "<{0}{1}>".format(name, _attrs(pairs))
    return "<{0}{1}>{2}</{0}>".format(name, _attrs(pairs), inner)


def _cls(*names):
    names = [n for n in names if n]
    return " ".join(names) or None


def _present_name(name):
    """The marker that says a switch was drawn ('ami.PFOS.Eggs' ->
    'ami_present.PFOS.Eggs'): an unticked box posts nothing, so the marker is
    what tells the save that the box was there and is off."""
    head, dot, rest = name.partition(".")
    return head + "_present" + dot + rest if dot else name + "_present"


def _dom_id(sheet, name):
    return re.sub(r"[^A-Za-z0-9_-]", "-", "sheet-{0}-{1}".format(sheet.id, name))


def _state_options(cell):
    return cell.options or [(s, s.capitalize()) for s in RULE_STATES]


def _state_name(row, cell):
    return cell.name or "rulestate.{0}".format(row.key)


def _pair(v):
    if isinstance(v, (list, tuple)) and len(v) == 2:
        return v[0], v[1]
    return None, None


def _editable(col, cell):
    """Whether the cell posts: never a links cell, a locked or a read-only
    value; a state cell posts under rulestate.<row> when it names nothing."""
    if col.kind in ("links", "menu") or cell.state in ("locked", "readonly"):
        return False
    if col.kind == "state":
        return True
    if col.kind == "pair":
        return isinstance(cell.name, (list, tuple)) and len(cell.name) == 2
    return bool(cell.name)


def _kept_names(col, cell):
    """The names a locked or read-only cell posts to keep its stored value:
    nothing without a name."""
    if cell.state not in ("locked", "readonly") or not cell.name:
        return []
    if col.kind == "pair":
        return list(cell.name) if isinstance(cell.name, (list, tuple)) and len(cell.name) == 2 else []
    if col.kind in ("switch", "flag"):
        return [cell.name, _present_name(cell.name)]
    return [cell.name]


def _kept_inputs(col, cell, form):
    """Hidden inputs posting a locked or read-only cell's stored value, as
    its control would post it."""
    names = _kept_names(col, cell)
    if not names:
        return ""

    def hidden(name, value):
        return _tag("input", [("type", "hidden"), ("name", name), ("form", form), ("value", value)])
    if col.kind == "pair":
        return "".join(hidden(n, _text(v)) for n, v in zip(names, _pair(cell.value)))
    if col.kind in ("switch", "flag"):
        return (hidden(names[0], "on") if _on(col, cell) else "") + hidden(names[1], "1")
    return hidden(names[0], _chips_value(cell) if col.kind == "chips" else _text(cell.value))


def _on(col, cell):
    """Whether a switch is on or a flag reported."""
    if col.kind == "flag":
        return bool((cell.data or {}).get("in"))
    return bool(cell.value)


def _label_of(options, value):
    for v, label in options or ():
        if _text(v) == _text(value):
            return _text(label)
    return _text(value)


def _shown(col, cell, unit=False):
    """The value as words: what a read-only cell shows and what an inherited
    one says it inherits. The unit only where the heading does not carry it."""
    u = " " + col.unit if unit and col.unit else ""
    if col.kind == "pair":
        lo, hi = _pair(cell.value)
        if _text(lo) == "" and _text(hi) == "":
            return ""
        return "{0} {1} {2}{3}".format(_text(lo), EN_DASH, _text(hi), u)
    if col.kind == "switch":
        return "✓" if cell.value else "✗"
    if col.kind in ("select", "state"):
        return _label_of(cell.options if col.kind == "select" else _state_options(cell), cell.value)
    if col.kind == "chips" and isinstance(cell.value, (list, tuple)):
        return ", ".join(_text(v) for v in cell.value)
    if col.kind == "links":
        return ", ".join(_text(label) for label, _href in cell.links or ())
    t = _text(cell.value)
    return t + u if t else ""


def _hover(cell):
    if cell.title:
        return cell.title
    if cell.source and cell.state == "inherited":
        return "From {0}".format(cell.source)
    if cell.source and cell.state == "locked":
        return "Set by {0}".format(cell.source)
    if cell.source and cell.state == "set":
        return "Set here, overriding {0}".format(cell.source)
    return None


def _state_class(col, cell, empty):
    if cell.state == "off" or (empty and col.kind == "links"):
        return "is-off"
    if cell.state == "set":
        return "is-set" if cell.source and not empty else None
    return "is-" + cell.state


def _limit(v):
    return None if v is None else _text(v)


def _kind(name, default):
    """What a changed control counts as in the editor's unsaved-changes
    note (config_forms.change_kind), or `default` for a name no declared
    section posts (a panel flag, a rule's state); nothing for a drawer's
    copy, which posts nothing."""
    if not name:
        return None
    return _tab_modules()[0].change_kind(name) or default


def _number_input(col, value, placeholder, name, label, table, form=None, disabled=False):
    step = "any" if col.step is None else _text(col.step)
    return _tag("input", [("type", "number"), ("class", "rl-in pfas-sheet-in" if table else "pfas-sheet-in"),
                          ("name", name), ("form", form), ("step", step), ("min", _limit(col.min)),
                          ("max", _limit(col.max)), ("value", value), ("placeholder", placeholder),
                          ("disabled", disabled), ("aria-label", label), ("data-kind", _kind(name, "cell"))])


def _num_value(cell, value):
    """(value, placeholder): an inherited value is what blank means, and
    off reads an em dash."""
    if cell.state == "inherited":
        return "", _text(value) or None
    if cell.state == "off":
        return "", EM_DASH
    return _text(value), None


def _select(cell, name, label, table, form=None, disabled=False):
    """An inherited select selects the blank, which reads the inherited
    choice (as a config choice's blank reads its placeholder)."""
    inherited = cell.state == "inherited"
    value = "" if inherited else _text(cell.value)
    blank = _label_of(cell.options, cell.value) if inherited and _text(cell.value) else EM_DASH
    values = [_text(v) for v, _l in cell.options or ()]
    opts = [] if "" in values else [_tag("option", [("value", ""), ("selected", inherited)], _esc(blank))]
    for v, l in cell.options or ():
        shown = blank if inherited and _text(v) == "" else l
        opts.append(_tag("option", [("value", v), ("selected", _text(v) == value)], _esc(shown)))
    if value and value not in values:     # the stored value is always offered
        opts.append(_tag("option", [("value", value), ("selected", True)], _esc(value)))
    return _tag("select", [("class", "rl-in pfas-sheet-in" if table else "pfas-sheet-in"), ("name", name),
                           ("form", form), ("disabled", disabled), ("aria-label", label),
                           ("data-kind", _kind(name, "cell"))], "".join(opts))


def _switch(cell, name, label, form=None, disabled=False):
    box = _tag("input", [("type", "checkbox"), ("class", "pfas-sheet-in"), ("name", name), ("form", form),
                         ("value", "on"), ("aria-label", label), ("checked", bool(cell.value)),
                         ("disabled", disabled), ("data-kind", _kind(name, "flag"))])
    return '<label class="pfas-switch">{0}<span class="pfas-switch-track"></span></label>'.format(box)


def _flag_words(on, rl):
    """What a flag shows: the RL when one is set, else ✓; ✗ left out."""
    return (_text(rl) or "✓") if on else "✗"


def _flag_cell(cell, name, label, form=None, disabled=False):
    """A panel flag: a button showing ✓, ✗ or the RL, which opens the
    cell's editor (in the drawer it flips the flag), and the box it writes,
    hidden (the posted control: an unticked box posts nothing). Never a
    switch."""
    data = cell.data or {}
    on = bool(data.get("in"))
    rl = _text(data.get("rl")) if on else ""
    # the grid's flag opens a dialog, so its state is in its name; the
    # drawer's flips, so it is pressed or not
    btn = _tag("button", [("type", "button"), ("class", _cls("pfas-flag", "is-rl" if rl else None,
                                                             None if on else "is-out")),
                          ("aria-pressed", None if name else ("true" if on else "false")),
                          ("aria-haspopup", "dialog" if name else None),
                          ("aria-label", "{0}: {1}".format(label, _flag_state(on, rl))), ("data-label", label),
                          ("data-rl", _text(data.get("rl"))), ("data-rl-name", data.get("rl_name") or None),
                          ("data-mdl-name", (data.get("mdl_name") or None) if name else None),
                          ("disabled", disabled)], _esc(_flag_words(on, rl)))
    box = _tag("input", [("type", "checkbox"), ("class", "pfas-sheet-in"), ("hidden", True), ("name", name),
                         ("form", form), ("value", "on"), ("aria-label", label), ("checked", on),
                         ("disabled", disabled), ("data-kind", _kind(name, "flag"))])
    kept = "".join(_tag("input", [("type", "hidden"), ("name", n), ("form", form), ("value", v),
                                  ("data-placeholder", data.get("rl_placeholder") if n == data.get("rl_name") else None),
                                  ("data-kind", _kind(n, "cell"))])
                   for n, v in data.get("kept") or () if name)
    return btn + box + kept


def _flag_state(on, rl):
    """A flag's state as words, for its accessible name."""
    if not on:
        return "left out"
    return "reported, RL {0}".format(rl) if rl else "reported"


def _text_input(cell, name, label, table, form=None, chips=False, disabled=False):
    """A text or a chips cell; an inherited one is blank with the inherited
    text as its placeholder."""
    shown = _chips_value(cell) if chips else _text(cell.value)
    inherited = cell.state == "inherited"
    return _tag("input", [("type", "text"), ("class", "rl-in pfas-sheet-in" if table else "pfas-sheet-in"),
                          ("name", name), ("form", form), ("value", "" if inherited else shown),
                          ("placeholder", (shown or None) if inherited else None),
                          ("data-chips", "chips" if chips else None),
                          ("data-options", _chips_options(cell) if chips else None), ("disabled", disabled),
                          ("aria-label", label), ("data-kind", _kind(name, "cell"))])


def _state_input(cell, name, dom_id, form=None):
    """A state's posted field: blank when inherited."""
    value = "" if cell.state == "inherited" else _text(cell.value)
    return _tag("input", [("type", "hidden"), ("class", "pfas-sheet-in"), ("id", dom_id), ("name", name),
                          ("form", form), ("value", value), ("data-kind", _kind(name, "rule"))])


def _seg(cell, label, dom_id, disabled=False):
    """A state: the shared segmented control writing a hidden input (the
    posted field), as config_form_macros.pt draws a choice. An inherited
    state presses nothing and marks the choice it inherits."""
    value = _text(cell.value)
    inherited = cell.state == "inherited"
    items = "".join(_tag("button", [("type", "button"),
                                    ("class", "pfas-seg-item is-inherited" if inherited and _text(v) == value
                                     else "pfas-seg-item"),
                                    ("data-value", v),
                                    ("aria-pressed", "true" if _text(v) == value and not inherited else "false"),
                                    ("disabled", disabled)],
                         _esc(l))
                    for v, l in _state_options(cell))
    return _tag("div", [("class", "pfas-seg pfas-seg-sm is-fit"), ("role", "group"), ("data-field", True),
                        ("data-quiet", True), ("data-input", dom_id), ("aria-label", label)], items)


def _chips_value(cell):
    if isinstance(cell.value, (list, tuple)):
        return ", ".join(_text(v) for v in cell.value)
    return _text(cell.value)


def _chips_options(cell):
    if not cell.options:
        return None
    return json.dumps([[_text(v), _text(l)] for v, l in cell.options])


def _links(col, cell):
    links = cell.links or ()
    n = len(links)
    noun = col.unit or "analytes"
    if n == 1 and noun.endswith("s"):
        noun = noun[:-1]
    words = _text(cell.value) or "{0} {1}".format(n, noun)
    items = "".join("<li>{0}</li>".format(
        _tag("a", [("class", "btn-sm btn-secondary"), ("href", href)], _esc(label)) if href
        else "<span>{0}</span>".format(_esc(label))) for label, href in links)
    opener = _tag("a", [("class", "btn-sm btn-secondary pfas-sheet-links"), ("href", "#"), ("role", "button"),
                        ("aria-expanded", "false"), ("title", cell.title or _shown(col, cell))], _esc(words))
    return opener + '<div class="pfas-sheet-pop" hidden="hidden"><ul>{0}</ul></div>'.format(items)


LOCK_MARK = '<i class="fas fa-lock" aria-hidden="true"></i>'
# a state the method fixes: a drawn lock and its words, in place of the
# segment (nothing to choose)
LOCK_SVG = ('<svg class="pfas-lock" viewBox="0 0 16 16" width="12" height="12" aria-hidden="true" '
            'focusable="false"><rect x="3" y="7" width="10" height="7" rx="1.5" fill="currentColor"/>'
            '<path d="M5 7V5a3 3 0 0 1 6 0v2" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>')
FIXED_WORDS = "Fixed by the method"


def _val(text, locked=False):
    lock = LOCK_MARK if locked else ""
    return '<span class="pfas-sheet-val">{0}</span>{1}'.format(_esc(text), lock)


def _nav(links):
    """Navigation buttons: a link to another tab of the page (#pane-...)
    also names it in data-goto, which the page follows."""
    return " ".join(_tag("a", [("class", "btn-sm btn-secondary"), ("href", href),
                               ("data-goto", href[1:] if _text(href).startswith("#pane-") else None)],
                         _esc(label)) for label, href in links)


def _expander(cell):
    return _tag("button", [("type", "button"), ("class", "btn-sm btn-secondary pfas-sheet-expand"),
                           ("aria-expanded", "false"), ("aria-controls", cell.expands)],
                _esc(_text(cell.value) or "Edit"))


def _data_attrs(cell):
    """data-* attributes from a cell's or a row's data (a list as JSON)."""
    return [("data-" + k, json.dumps(v) if isinstance(v, (list, tuple)) else _text(v))
            for k, v in sorted((cell.data or {}).items())]


NOT_ASSESSED_WORDS = "Not assessed for {0}"
# the word a number cell's None box posts
NONE_WORD = "none"


def _none_marked(cell):
    """A pair marked not assessed: its ends post blank, whatever it holds."""
    return bool(cell.none and cell.none[1])


def _none_box(cell, label, form=None, word="on"):
    """A not-assessed pair's marker (a number's, the word "none"): a hidden
    box (posted ticked, nothing unticked), set by the cell's editor."""
    name, on, _words = cell.none
    return _tag("input", [("type", "checkbox"), ("class", "pfas-sheet-in pfas-none-in"), ("hidden", True),
                          ("name", name), ("form", form), ("value", word), ("checked", bool(on)),
                          ("aria-label", "{0} not assessed".format(label)), ("data-kind", _kind(name, "cell"))])


def _menu(row, cell):
    """A row's ⋯ menu button; what the menu offers is the page script's."""
    return _tag("button", [("type", "button"), ("class", "pfas-rowmenu"), ("aria-haspopup", "menu"),
                           ("aria-expanded", "false"), ("aria-label", "Actions for {0}".format(_text(row.label)))]
                + _data_attrs(cell), "\u22ef")


# ── the table ───────────────────────────────────────────────────────────────

def _cell_tds(sheet, row, col, cell):
    """The <td>s of one cell: one, or two for a pair (min, max)."""
    hidden = None if col.default else "is-col-off"
    align = None if col.align == "left" else "is-" + col.align
    num = "is-num" if col.kind in ("num", "pair") else None
    if cell is None:
        # a pair's upper end takes no room here either: its heading ends where
        # the lower end's box does
        return ([_tag("td", [("class", _cls(num, align, hidden)), ("data-col", col.key)], "")] +
                [_tag("td", [("class", _cls(num, align, "pfas-sheet-hi", hidden)), ("data-col", col.key)], "")]
                * (col.span - 1))
    if cell.state == "na":
        # not reported here: the words, muted, never an empty box
        words = '<span class="pfas-sheet-val is-empty">{0}</span>'.format(_esc(NOT_REPORTED))
        tds = [_tag("td", [("class", _cls("is-na", align, hidden)), ("title", cell.title), ("data-col", col.key)],
                    words)]
        if col.span == 2:
            tds.append(_tag("td", [("class", _cls("is-na", "pfas-sheet-hi", hidden)), ("data-col", col.key)], ""))
        return tds
    if col.kind == "menu":
        return [_tag("td", [("class", _cls("pfas-sheet-menu", hidden)), ("data-col", col.key)], _menu(row, cell))]
    if col.kind == "state" and cell.state == "locked":
        # fixed by the method: the lock and its words, never a segment; it
        # posts only what a named cell keeps (an unnamed one, nothing)
        fixed = '<span class="pfas-fixed">{0}{1}</span>'.format(LOCK_SVG, _esc(FIXED_WORDS))
        return [_tag("td", [("class", _cls("is-locked", align, hidden)), ("title", _hover(cell) or _shown(col, cell)),
                            ("data-col", col.key)], fixed + _kept_inputs(col, cell, sheet.form))]
    label = "{0} {1}".format(_text(row.label), _text(col.label))
    chips = "".join(_flag(f) for f in cell.flags)
    empty = _shown(col, cell) == ""
    cls = _cls(num, _state_class(col, cell, empty), align, hidden,
               "is-none" if col.kind == "num" and _none_marked(cell) else None)
    if col.kind == "flag":
        # a flag's data are its button's; a left-out cell is marked
        cls = _cls(cls, None if _on(col, cell) else "is-out")
        head = [("class", cls), ("title", _hover(cell)), ("data-col", col.key), ("data-label", col.label),
                ("data-unit", col.unit)]
    else:
        head = [("class", cls), ("title", _hover(cell)), ("data-col", col.key)] + _data_attrs(cell)
    edit = _editable(col, cell)
    if col.kind == "pair":
        if not edit:
            return [_tag("td", head, _val(_shown(col, cell), cell.state == "locked") +
                         _kept_inputs(col, cell, sheet.form)),
                    _tag("td", [("class", _cls(cls, "pfas-sheet-hi")), ("data-col", col.key)], "")]
        pid = _dom_id(sheet, "{0}-{1}".format(row.key, col.key))
        marked = _none_marked(cell)
        tds = []
        for end, v, n, word in zip(("lo", "hi"), _pair(cell.value), cell.name, ("minimum", "maximum")):
            value, placeholder = _num_value(cell, v)
            attrs = [("class", _cls(cls, "pfas-sheet-hi" if end == "hi" else None, "is-none" if marked else None)),
                     ("title", _hover(cell)), ("data-col", col.key), ("data-pair", pid), ("data-pair-end", end),
                     ("data-unit", col.unit), ("data-label", col.label),
                     ("data-none", cell.none[2] if cell.none else None)]
            inner = _number_input(col, "" if marked else value, placeholder, n, "{0} {1}".format(label, word),
                                  True, sheet.form)
            if cell.none and end == "hi":
                inner += _none_box(cell, label, sheet.form)
            tds.append(_tag("td", attrs, inner))
        return tds
    if not edit:
        kept = chips + _kept_inputs(col, cell, sheet.form)
        if col.kind == "links":
            # a count that opens the list, or a dash when there is nothing
            empty_words = '<span class="pfas-sheet-val is-empty">{0}</span>'.format(EM_DASH)
            return [_tag("td", head, (empty_words if empty else _links(col, cell)) + kept)]
        if cell.expands:
            return [_tag("td", head, _expander(cell) + kept)]
        if cell.links:
            words = _val(_text(cell.value)) + " " if cell.value not in (None, "") else ""
            return [_tag("td", head, words + _nav(cell.links) + kept)]
        return [_tag("td", head, _val(_shown(col, cell), cell.state == "locked") + kept)]
    if col.kind == "num":
        marked = _none_marked(cell)
        value, placeholder = _num_value(cell, "" if marked else cell.value)
        inner = _number_input(col, value, placeholder, cell.name, label, True, sheet.form, disabled=marked)
        if cell.none:
            inner += _none_box(cell, label, sheet.form, NONE_WORD)
            head.append(("data-none", cell.none[2]))
        return [_tag("td", head + [("data-label", col.label)], inner)]
    form = sheet.form
    if col.kind == "select":
        inner = _select(cell, cell.name, label, True, form)
    elif col.kind == "switch":
        inner = _switch(cell, cell.name, label, form) + _tag(
            "input", [("type", "hidden"), ("name", _present_name(cell.name)), ("form", form), ("value", "1")])
    elif col.kind == "flag":
        inner = _flag_cell(cell, cell.name, label, form) + _tag(
            "input", [("type", "hidden"), ("name", _present_name(cell.name)), ("form", form), ("value", "1")])
    elif col.kind == "state" and col.word:
        # the state as a word; the drawer's segment writes the hidden input
        # and the page redraws the word from data-words
        head = [(k, _cls("pfas-sheet-role", v) if k == "class" else v) for k, v in head]
        head.append(("data-words", json.dumps([[_text(v), _text(l)] for v, l in _state_options(cell)])))
        inner = (_val(_label_of(_state_options(cell), cell.value)) +
                 _state_input(cell, _state_name(row, cell), None, form))
    elif col.kind == "state":
        dom_id = _dom_id(sheet, _state_name(row, cell))
        inner = _state_input(cell, _state_name(row, cell), dom_id, form) + _seg(cell, label, dom_id)
    else:
        inner = _text_input(cell, cell.name, label, True, form, chips=col.kind == "chips")
    # the box first, under its heading's first letter; its chips after it
    return [_tag("td", head, inner + chips)]


def _heading(col, unit=True):
    if col.kind == "menu":
        return '<span class="pfas-sr-hide">{0}</span>'.format(_esc(col.label))
    text = _esc(col.label)
    if unit and col.unit and col.kind not in ("pair", "links"):
        # the unit on its own line under the name
        text += ' <span class="pfas-th-unit">{0}</span>'.format(_esc(col.unit))
    if col.sub:
        text += '<span class="pfas-sheet-sub">{0}</span>'.format(_esc(col.sub))
    return text


def _column_runs(columns):
    """Consecutive columns under the same group heading: [(group, [columns])]."""
    runs = []
    for col in columns:
        if runs and col.group and runs[-1][0] == col.group:
            runs[-1][1].append(col)
        else:
            runs.append((col.group, [col]))
    return runs


def _all_on(sheet, key):
    vals = [r.cells[key].value for r in sheet.rows if key in r.cells]
    return bool(vals) and all(vals)


def _thead(sheet):
    grouped = any(c.group for c in sheet.columns)
    switches = bool(sheet.column_switches)
    span = 1 + int(grouped) + int(switches)
    span_attr = span if span > 1 else None
    first = []
    if sheet.selection:
        first.append(_tag("th", [("scope", "col"), ("class", "pfas-sheet-sel"), ("rowspan", span_attr)],
                          _tag("input", [("type", "checkbox"), ("class", "pfas-sheet-all"), ("form", "pfas-no-form"),
                                         ("aria-label", "Select all rows")])))
    first.append(_tag("th", [("scope", "col"), ("class", "pfas-sheet-label"), ("rowspan", span_attr)], ""))
    second = []
    for group, cols in _column_runs(sheet.columns):
        if group:
            shown = sum(c.span for c in cols if c.default)
            first.append(_tag("th", [("scope", "colgroup"), ("class", _cls("pfas-sheet-gh", None if shown else "is-col-off")),
                                     ("colspan", shown or sum(c.span for c in cols)), ("data-group", group)],
                              _esc(group)))
        for col in cols:
            th = _tag("th", [("scope", "col"),
                             ("class", _cls(None if col.align == "left" else "is-" + col.align,
                                            None if col.default else "is-col-off")),
                             ("colspan", 2 if col.span == 2 else None),
                             ("rowspan", 2 if grouped and not group else None),
                             ("data-group", group), ("data-col", col.key),
                             ("data-matrices", json.dumps(col.matrices) if col.matrices else None)], _heading(col))
            (second if group else first).append(th)
    rows = [first] + ([second] if grouped else [])
    if switches:
        cells = []
        for col in sheet.columns:
            hidden = None if col.default else "is-col-off"
            colspan = 2 if col.span == 2 else None
            if col.key in sheet.column_switches and col.kind == "flag":
                chip = _tag("button", [("type", "button"), ("class", "pfas-colchip"), ("data-col", col.key),
                                       ("aria-label", "Every row: {0}".format(_text(col.label)))], "✓ all")
                cells.append(_tag("th", [("class", hidden), ("data-col", col.key)], chip))
            elif col.key in sheet.column_switches:
                box = _tag("input", [("type", "checkbox"), ("data-col", col.key), ("form", "pfas-no-form"),
                                     ("aria-label", "Every row: {0}".format(_text(col.label))),
                                     ("checked", _all_on(sheet, col.key))])
                cells.append(_tag("th", [("class", hidden), ("data-col", col.key)],
                                  '<label class="pfas-switch pfas-sheet-colswitch">{0}'
                                  '<span class="pfas-switch-track"></span></label>'.format(box)))
            else:
                cells.append(_tag("td", [("class", hidden), ("colspan", colspan), ("data-col", col.key)], ""))
        rows.append(cells)
    out = []
    for i, cells in enumerate(rows):
        cls = "pfas-sheet-switches" if switches and i == len(rows) - 1 else None
        out.append(_tag("tr", [("class", cls)], "".join(cells)))
    return "<thead>{0}</thead>".format("".join(out))


# warn: an amber note; ok: a mint chip; tag: a grey classification, not a
# fault; fault: coral words in the cell's own text (no chip), a state that
# needs fixing (an Enforced rule with no limit); quiet: the same words muted,
# a gap that holds nothing back (an Evaluate rule with no limit); aside:
# muted words after the value that qualify it ("Method · default")
FLAG_TONES = ("warn", "ok", "tag", "fault", "quiet", "aside")
# a flag a row carries by name, drawn as these words
FLAG_WORDS = {"no_window": "NO WINDOW"}


def _flag(flag):
    if isinstance(flag, (list, tuple)):
        words, tone = flag
        if tone not in FLAG_TONES:
            raise ValueError("unknown flag tone: {0}".format(tone))
        if tone == "tag":
            return '<span class="pfas-tag">{0}</span>'.format(_esc(words))
        if tone == "fault":
            return '<span class="pfas-flag-text is-flag">{0}</span>'.format(_esc(words))
        if tone == "quiet":
            return '<span class="pfas-flag-text is-quiet">{0}</span>'.format(_esc(words))
        if tone == "aside":
            return '<span class="pfas-sheet-aside">{0}</span>'.format(_esc(words))
        return '<span class="pfas-sheet-flag is-{0}">{1}</span>'.format(tone, _esc(words))
    return '<span class="pfas-sheet-flag">{0}</span>'.format(_esc(FLAG_WORDS.get(flag, flag)))


def _marked(row):
    """A coral flag marks the row (its off cells read coral); an amber one
    is a note on it."""
    return any(not isinstance(f, (list, tuple)) for f in row.flags)


def _row_label(row, scope):
    inner = _esc(row.label)
    if row.sub:
        inner += '<span class="pfas-sheet-sub">{0}</span>'.format(_esc(row.sub))
    inner += "".join(_flag(f) for f in row.flags)
    return _tag("th", [("scope", scope), ("class", "pfas-sheet-label")], inner)


def _cells(sheet, row):
    return "".join("".join(_cell_tds(sheet, row, col, row.cells.get(col.key))) for col in sheet.columns)


def _member_id(sheet, row):
    """A folding group's member row id: every member of a group shares the
    prefix sheet-<sheet>-g-<group>-."""
    return _dom_id(sheet, "g-{0}-{1}".format(row.group, row.key))


def _tr(sheet, row, folded=False):
    sel = ""
    if sheet.selection:
        box = _tag("input", [("type", "checkbox"), ("class", "pfas-sheet-check"), ("form", "pfas-no-form"),
                             ("aria-label", "Select {0}".format(_text(row.label)))]) if row.selectable else ""
        sel = _tag("td", [("class", "pfas-sheet-sel")], box)
    # a folded group's member: hidden until the group opens (it still posts)
    fold = [("id", _member_id(sheet, row)), ("data-in-group", row.group), ("hidden", True)] if folded else []
    return _tag("tr", [("data-row", row.key), ("data-label", row.label),
                       ("class", "is-flagged" if _marked(row) else None)] + fold + _data_attrs(row),
                sel + _row_label(row, "row") + _cells(sheet, row))


# the fold control's mark: a chevron that turns down while the group is open
CHEVRON = ('<svg class="pfas-group-chev" viewBox="0 0 16 16" width="12" height="12" aria-hidden="true" '
           'focusable="false"><path d="M6 3l5 5-5 5" fill="none" stroke="currentColor" stroke-width="2"/></svg>')


def _group_tr(sheet, group, members=()):
    if not sheet.fold:
        sel = _tag("td", [("class", "pfas-sheet-sel")], "") if sheet.selection else ""
        return _tag("tr", [("class", "pfas-sheet-grouprow"), ("data-group", group.key)],
                    sel + _row_label(group, "rowgroup") + _cells(sheet, group))
    # a folding group: one row saying what its members hold, opened by its
    # toggle; with selection its box ticks every member, folded or not
    sel = ""
    if sheet.selection:
        box = _tag("input", [("type", "checkbox"), ("class", "pfas-group-check"), ("form", "pfas-no-form"),
                             ("data-group", group.key),
                             ("aria-label", "Select every row of {0}".format(_text(group.label)))]) if members else ""
        sel = _tag("td", [("class", "pfas-sheet-sel")], box)
    toggle = _tag("button", [("type", "button"), ("class", "pfas-group-toggle"), ("aria-expanded", "false"),
                             ("aria-controls", " ".join(_member_id(sheet, r) for r in members) or None),
                             ("aria-label", "Rows of {0}".format(_text(group.label)))], CHEVRON) if members else ""
    inner = toggle + _esc(group.label)
    if group.sub:
        inner += '<span class="pfas-sheet-sub">{0}</span>'.format(_esc(group.sub))
    if group.summary:
        inner += '<span class="pfas-group-summary">{0}</span>'.format(_esc(group.summary))
    inner += "".join(_flag(f) for f in group.flags)
    label = _tag("th", [("scope", "rowgroup"), ("class", "pfas-sheet-label")], inner)
    # a group with no members has nothing to open: it claims no fold
    return _tag("tr", [("class", "pfas-sheet-grouprow is-folded" if members else "pfas-sheet-grouprow"),
                       ("data-group", group.key), ("aria-expanded", "false" if members else None)],
                sel + label + _cells(sheet, group))


def _tbodies(sheet):
    if not sheet.groups:
        return "<tbody>{0}</tbody>".format("".join(_tr(sheet, r) for r in sheet.rows))
    out = []
    keys = set(g.key for g in sheet.groups)
    for g in sheet.groups:
        members = [r for r in sheet.rows if r.group == g.key]
        body = _group_tr(sheet, g, members) + "".join(_tr(sheet, r, bool(sheet.fold)) for r in members)
        out.append(_tag("tbody", [("class", "pfas-sheet-group"), ("data-group", g.key)], body))
    rest = [r for r in sheet.rows if r.group not in keys]
    if rest:
        out.append("<tbody>{0}</tbody>".format("".join(_tr(sheet, r) for r in rest)))
    return "".join(out)


# ── the row drawer: the same cells as a vertical list ───────────────────────

def _field(col, cell):
    """One cell as a drawer field. A locked or read-only value with a name is
    its control, disabled; one without is its words."""
    edit = _editable(col, cell)
    off = not edit
    label = _text(col.label)
    if off and col.kind == "state" and cell.state == "locked":
        control = '<div class="pfas-sheet-ro"><span class="pfas-fixed">{0}{1}</span></div>'.format(
            LOCK_SVG, _esc(FIXED_WORDS))
    elif off and (col.kind == "links" or not _kept_names(col, cell)):
        # its words and the words its flags say ("no limit set"), as the cell
        # reads; a dash only when there is neither
        words = _esc(_shown(col, cell, unit=True)) + "".join(_flag(f) for f in cell.flags)
        control = '<div class="pfas-sheet-ro">{0}</div>'.format(words or EM_DASH)
    elif col.kind == "num":
        value, _p = _num_value(cell, "" if _none_marked(cell) else cell.value)
        control = _number_input(col, value, None, None, label, False, disabled=off or _none_marked(cell))
        if cell.none:
            box = _tag("input", [("type", "checkbox"), ("class", "pfas-sheet-in"), ("value", NONE_WORD),
                                 ("checked", bool(cell.none[1])), ("disabled", off)])
            control += '<label class="pfas-cell-none">{0}<span>{1}</span></label>'.format(
                box, _esc((cell.data or {}).get("none-text") or ""))
    elif col.kind == "pair":
        ends = []
        for v, word in zip(_pair(cell.value), ("minimum", "maximum")):
            value, _p = _num_value(cell, "" if _none_marked(cell) else v)
            ends.append(_number_input(col, value, None, None, "{0} {1}".format(label, word), False, disabled=off))
        control = _tag("div", [("data-range", True), ("data-unit", col.unit)], "".join(ends))
        if cell.none:
            box = _tag("input", [("type", "checkbox"), ("class", "pfas-sheet-in"), ("value", "on"),
                                 ("checked", bool(cell.none[1])), ("disabled", off)])
            control += '<label class="pfas-cell-none">{0}<span>None: recovery is not assessed for {1}</span></label>'.format(
                box, _esc(cell.none[2]))
    elif col.kind == "select":
        control = _select(cell, None, label, False, disabled=off)
    elif col.kind == "switch":
        control = _switch(cell, None, label, disabled=off)
    elif col.kind == "flag":
        control = _flag_cell(Cell(cell.value, data=dict(cell.data or {}, rl="", rl_name=None, kept=())), None,
                             label, disabled=off)
    elif col.kind == "state":
        control = _state_input(cell, None, None) + _seg(cell, label, None, disabled=off)
    else:
        control = _text_input(cell, None, label, False, chips=col.kind == "chips", disabled=off)
    help_text = None
    if cell.state == "inherited" and cell.source:
        help_text = "{0} from {1}".format(_shown(col, cell, unit=True), cell.source)
    elif cell.state == "locked" and cell.source:
        help_text = "Set by {0}".format(cell.source)
    help_html = '<div class="pfas-sheet-help">{0}</div>'.format(_esc(help_text)) if help_text else ""
    flabel = '<div class="pfas-sheet-flabel">{0}</div>'.format(_heading(col, unit=col.kind != "pair"))
    return _tag("div", [("class", _cls("pfas-sheet-field", None if edit else "is-ro")), ("data-col", col.key)],
                flabel + control + help_html)


def _template(sheet, row):
    fields = "".join(_field(col, row.cells[col.key]) for col in sheet.columns
                     if col.key in row.cells and col.kind != "menu" and row.cells[col.key].state != "na")
    return _tag("template", [("class", "pfas-sheet-row-tpl"), ("data-row", row.key)],
                '<div class="pfas-sheet-form">{0}</div>'.format(fields))


# ── entry points ────────────────────────────────────────────────────────────

def _bar(sheet):
    acts = "".join(_tag("button", [("type", "button"), ("class", "btn btn-sm btn-secondary"), ("data-action", a[0]),
                                   ("data-col", a[2] if len(a) > 2 else None)], _esc(a[1])) for a in sheet.actions)
    return ('<div class="pfas-sheet-bar" hidden="hidden">'
            '<span class="pfas-sheet-count" aria-live="polite">0 selected</span>'
            '<button type="button" class="btn btn-sm btn-primary pfas-sheet-edit">Edit selected</button>{0}'
            '<button type="button" class="btn btn-sm btn-secondary pfas-sheet-clear">Clear selection</button>'
            '</div>').format(acts)


# ── Edit selected in the matrix layout: the bulk form, drawn once ───────────

# the value of a bulk select's "As is" choice: it leaves every row as it is,
# and no cell holds or posts it
AS_IS = "pfas-as-is"
AS_IS_WORDS = "As is"
NO_FORM = "pfas-no-form"
# a matrix row's fields: its flag, then the inputs the flag names
MATRIX_FIELDS = (("in", "In panel"), ("rl", "RL"), ("mdl", "MDL"))
# the matrix fields whose blank takes a value from elsewhere (an RL: the
# lowest calibrator), which Reset selected to inherited blanks
INHERITING = ("rl",)


def _matrix_owned(sheet):
    """{flag column key: {field: Column}}: for each matrix, the columns
    holding the inputs its flags name (data rl_name, mdl_name), found in
    any row that draws them."""
    by_key = dict((c.key, c) for c in sheet.columns)
    out = OrderedDict()
    for col in sheet.columns:
        if col.kind != "flag":
            continue
        found = {}
        for row in sheet.rows:
            data = getattr(row.cells.get(col.key), "data", None) or {}
            for field, _words in MATRIX_FIELDS[1:]:
                name = data.get(field + "_name")
                if field in found or not name:
                    continue
                for key, cell in row.cells.items():
                    if cell.name == name and by_key[key].kind != "flag":
                        found[field] = by_key[key]
        out[col.key] = found
    return out


def _hint():
    """What the ticked rows hold now, written under a field by the script."""
    return '<span class="pfas-hint"></span>'


def _none_button(label):
    return _tag("button", [("type", "button"), ("class", "pfas-bulk-x"),
                           ("aria-label", "Set {0} to none".format(label))], "✕")


def _bulk_typed(col, label):
    """A typed bulk field: blank leaves every row as it is, ✕ sets none."""
    if col.kind == "num":
        step = "any" if col.step is None else _text(col.step)
        inp = _tag("input", [("type", "number"), ("class", "pfas-bulk-in"), ("form", NO_FORM), ("step", step),
                             ("min", _limit(col.min)), ("max", _limit(col.max)), ("placeholder", AS_IS_WORDS),
                             ("aria-label", label)])
    else:
        inp = _tag("input", [("type", "text"), ("class", "pfas-bulk-in"), ("form", NO_FORM),
                             ("placeholder", AS_IS_WORDS), ("aria-label", label)])
    return inp + _none_button(label)


def _bulk_select(cells, label):
    """A bulk choice: As is, the blank (none) and every choice any row
    offers, its stored value included."""
    opts = OrderedDict([(AS_IS, AS_IS_WORDS), ("", EM_DASH)])
    for cell in cells:
        for v, l in list(cell.options or ()) + [(cell.value, cell.value)]:
            v = _text(v)
            if v not in opts:
                opts[v] = _text(l)
    return _tag("select", [("class", "pfas-bulk-in"), ("form", NO_FORM), ("aria-label", label)],
                "".join(_tag("option", [("value", v), ("selected", v == AS_IS)], _esc(l)) for v, l in opts.items()))


def _bulk_seg(label):
    items = "".join(_tag("button", [("type", "button"), ("class", "pfas-seg-item"), ("data-value", v),
                                    ("aria-pressed", "true" if v == "" else "false")], w)
                    for v, w in (("", AS_IS_WORDS), ("on", "✓"), ("off", "✗")))
    return _tag("div", [("class", "pfas-seg pfas-seg-sm is-fit"), ("role", "group"), ("data-quiet", True),
                        ("aria-label", label)], items)


def _bulk_template(sheet):
    """Edit selected in the matrix layout: a table row per matrix (In panel,
    RL, MDL), then the row's own fields, every one starting As is with a
    hint under it. Drawn once for the sheet, it names no input: the script
    writes what is set into each ticked row's own."""
    owned = _matrix_owned(sheet)
    taken = set(c.key for fields in owned.values() for c in fields.values())
    cols = dict((c.key, c) for c in sheet.columns)
    rows = []
    for key, fields in owned.items():
        col = cols[key]
        label = _text(col.label)
        unit = ' <span class="pfas-sheet-unit">{0}</span>'.format(_esc(col.unit)) if col.unit else ""
        tds = [_tag("td", [("class", "pfas-bulk-f"), ("data-field", "in")],
                    _bulk_seg("{0} in panel".format(label)) + _hint())]
        for field, words in MATRIX_FIELDS[1:]:
            fcol = fields.get(field) or Column(field, words, "num")
            tds.append(_tag("td", [("class", "pfas-bulk-f"), ("data-field", field),
                                   ("data-inherits", field in INHERITING)],
                            _bulk_typed(fcol, "{0} {1}".format(words, label)) + _hint()))
        rows.append(_tag("tr", [("data-col", key), ("data-label", label), ("data-unit", col.unit)],
                         _tag("th", [("scope", "row")], _esc(label) + unit) + "".join(tds)))
    fields = []
    for col in sheet.columns:
        if col.kind in ("flag", "links") or col.key in taken:
            continue
        cells = [r.cells[col.key] for r in sheet.rows if col.key in r.cells and _editable(col, r.cells[col.key])]
        if not cells:
            continue
        if col.kind not in ("num", "text", "chips", "select"):
            raise ValueError("a matrix layout's own fields are numbers, words or choices: {0}".format(col.key))
        label = _text(col.label)
        ctl = _bulk_select(cells, label) if col.kind == "select" else _bulk_typed(col, label)
        fields.append(_tag("div", [("class", "pfas-bulk-f"), ("data-col", col.key)],
                           '<span class="pfas-sheet-flabel">{0}</span>'.format(_esc(label)) + ctl + _hint()))
    head = "".join(_tag("th", [("scope", "col")], _esc(w)) for w in ("Matrix",) + tuple(w for _f, w in MATRIX_FIELDS))
    return ('<template class="pfas-sheet-bulk-tpl"><div class="pfas-sheet-form is-matrix">'
            '<h3 class="pfas-sheet-h">Each matrix</h3>'
            '<table class="pfas-sheet-mx" data-col-resize="pfas-sheet-mx"><thead><tr>{0}</tr></thead><tbody>{1}</tbody></table>'
            '<h3 class="pfas-sheet-h">Each analyte</h3><div class="pfas-bulk-cells">{2}</div>'
            '</div></template>').format(head, "".join(rows), "".join(fields))


COLUMNS_WORD = "Columns"
HIDDEN_WORDS = "+ {0} hidden"


def _picker(sheet):
    """The Columns control: a row of chips, one per column the grid starts
    without (drawn while it is shown, its ✕ hides it again), then
    "+ <n> hidden", which opens the picker, the full list of columns. The
    page's script keeps the chips and the count with the picker."""
    cols = [c for c in sheet.columns if c.kind != "menu"]
    boxes = "".join(
        '<label class="pfas-switch">{0}<span class="pfas-switch-track"></span><span>{1}</span></label>'.format(
            _tag("input", [("type", "checkbox"), ("data-col", c.key), ("form", "pfas-no-form"), ("checked", c.default)]),
            _esc(c.label)) for c in cols)
    chips = "".join(_tag("button", [("type", "button"), ("class", "pfas-colchip"), ("data-col", c.key),
                                    ("aria-label", "Hide {0}".format(_text(c.label))), ("hidden", not c.default)],
                         '{0} <span aria-hidden="true">✕</span>'.format(_esc(c.label)))
                    for c in cols if not c.default)
    hidden = len([c for c in cols if not c.default])
    more = _tag("button", [("type", "button"), ("class", "pfas-colchip pfas-sheet-picker-btn"),
                           ("aria-expanded", "false")],
                _esc(HIDDEN_WORDS.format(hidden) if hidden else COLUMNS_WORD))
    return ('<div class="pfas-colchips">{0}{1}</div>'
            '<div class="pfas-sheet-pop pfas-sheet-picker" hidden="hidden">{2}</div>').format(chips, more, boxes)


def _adder(sheet):
    """Add: a chooser of what can join, in a popover, posted by its own form."""
    form, name, dom_id, heading, label, choices = sheet.adder[:6]
    kind = sheet.adder[6] if len(sheet.adder) > 6 else None
    if not choices:
        return ""
    if form == sheet.form:
        choices = [("", EM_DASH)] + list(choices)
    opts = "".join(_tag("option", [("value", v)], _esc(l)) for v, l in choices)
    pick = _tag("select", [("id", dom_id), ("name", name), ("form", form), ("data-kind", kind)], opts)
    return (_tag("button", [("type", "button"), ("class", "btn btn-sm btn-secondary pfas-sheet-add"),
                            ("aria-expanded", "false"), ("aria-haspopup", "dialog")], "Add") +
            _tag("div", [("class", "pfas-sheet-pop is-action pfas-sheet-adder"), ("hidden", True), ("role", "dialog"),
                         ("aria-label", heading)],
                 '<div class="pfas-pop-h">{0}</div>'.format(_esc(heading)) +
                 '<label class="pfas-pop-row"><span class="pfas-pop-l">{0}</span>{1}</label>'.format(_esc(label), pick) +
                 '<div class="pfas-pop-row">' +
                 _tag("button", [("type", "button"), ("class", "btn btn-sm btn-secondary pfas-sheet-cancel")], "Cancel") +
                 _tag("button", [("type", "submit"), ("class", "btn btn-sm btn-primary"), ("form", form)], "Add") +
                 "</div>"))


def _remover(sheet):
    """Remove: the ticked rows, posted by its own form; waits for a tick."""
    form, name = sheet.remover
    return _tag("button", [("type", "button"), ("class", "btn btn-sm btn-secondary pfas-sheet-remove"),
                           ("data-form", form), ("data-name", name), ("disabled", True)], "Remove")


def _tools(sheet):
    """Above the grid, on the right: Add, Remove, the Columns chips, then the
    grid's Help."""
    parts = []
    if sheet.adder:
        parts.append(_adder(sheet))
    if sheet.remover and sheet.selection:
        parts.append(_remover(sheet))
    if sheet.picker and not all(c.default for c in sheet.columns):
        parts.append(_picker(sheet))
    if sheet.help:
        parts.append(help_dictionary.help_button(sheet.help))
    parts = [p for p in parts if p]
    return '<div class="pfas-sheet-tools">{0}</div>'.format("".join(parts)) if parts else ""


def render_sheet(view, sheet):
    """The sheet's HTML (unicode). `view` is the page it is drawn on, for the
    page-level helpers a tab may need; the generic grid needs none."""
    box = _cls("pfas-sheet-box", "is-sticky-first" if sheet.sticky_first else None,
               "has-select" if sheet.selection else None)
    out = [_tag("div", [("class", box), ("data-sheet", sheet.id), ("data-form", sheet.form),
                      ("data-layout", sheet.layout), ("data-fold", sheet.fold)])]
    if sheet.selection:
        out.append(_bar(sheet))
    out.append(_tools(sheet))
    out.append('<div class="pfas-sheet-wrap"><table class="pfas-sheet" data-sheet="{0}">'.format(_esc(sheet.id)))
    out.append(_thead(sheet))
    out.append(_tbodies(sheet))
    out.append("</table></div>")
    out.extend(_tag("input", [("type", "hidden"), ("name", c.name), ("form", sheet.form),
                              ("value", _text(c.value))]) for c in sheet.hidden)
    out.extend(_template(sheet, r) for r in sheet.rows)
    if sheet.layout == "matrix":
        out.append(_bulk_template(sheet))
    out.append("</div>")
    return "".join(out)


# ── the tabs ────────────────────────────────────────────────────────────────

PANEL_GROUP = "Reported in, with RL"
# an analyte no surrogate quantifies: a classification, drawn as a grey tag
NO_SURROGATE = ("no-surrogate", "tag")
SALT_HINT = "Free-acid \u00f7 salt molar mass, 1.0 for none"
ANALYTES_FORM = "section-analytes"
# the Analytes tab's bulk bar, after Edit selected
ANALYTE_ACTIONS = [("set-quant", "Set Quantified by…", "quant"), ("set-panel", "Set panel for a matrix…"),
                   ("copy-column", "Copy column from…"), ("reset-inherited", "Reset selected to inherited")]


def _tab_modules():
    """(config_forms, method_profile_sections, profile_form, isomers,
    labelled_standards), imported when a tab is built so this module stays
    importable on its own."""
    from senaite.pfas import config_forms, method_profile_sections, profile_form, isomers, labelled_standards
    return config_forms, method_profile_sections, profile_form, isomers, labelled_standards


def _drawn(cf, table, profile, env):
    """{input name: the cell config_forms draws}, for every row the section
    lists: a name missing here is a row the section does not list."""
    out = {}
    for group in cf.render_table(table, profile, env):
        for row in group["rows"]:
            for cell in row["cells"]:
                out[cell["name"]] = cell
    return out


def _named(cf, table, profile, key, path):
    field = next(c for c in cf._bound(table, profile).columns if c.path[0] == path)
    return cf.cell_name(table, key, field)


def _isomer_words(entry, label):
    peaks = ([entry["linear"]] if entry.get("linear") else []) + list(entry.get("branched") or [])
    return "{0} {1} {2}".format(" + ".join(peaks), "→", label)


def _left_out_flag(cf, mps, rl_tbl, profile, matrix, kw, name):
    """The flag of a matrix the analyte is left out of. It carries the RL
    and MDL inputs that matrix's row would post, hidden, with what is stored
    for them, so the cell's editor can report it and set its RL in one save
    (profile_form.parse_sections reads that row once it is reported). Its RL
    is never shown: the flag reads ✗ and the RL column draws nothing."""
    fields = dict((f.path[0], f) for f in cf._bound(rl_tbl, profile).columns)
    entry = ((profile.get("reporting_limits") or {}).get(matrix) or {}).get(kw) or {}
    kept = []
    for path in ("rl", "mdl"):
        v = entry.get(path)
        kept.append((cf.cell_name(rl_tbl, (matrix, kw), fields[path]),
                     "" if v is None else cf._shown(v, fields[path].decimals)))
    low = mps._cal.derived_rl(profile, matrix, kw)
    return Cell("✗", name=name, data={"in": False, "rl": "", "rl_name": kept[0][0], "mdl_name": kept[1][0],
                                      "kept": kept,
                                      "rl_placeholder": None if low is None else mps.derived_rl_hint(low)})


def analytes_sheet(profile, env=None):
    """The Analytes tab: one row per panel analyte in the method's own order,
    each column posting its section's own input name to section-analytes.

    Shown: Reported in, with RL (a ✓ / ✗ flag per matrix, headed by the
    matrix and its unit, posted as ami.<keyword>.<matrix> and written by
    profile_form.apply_loose; a reported cell shows the analyte's RL there
    when one is set), Quantified by (the surrogate map, over the method's SUR
    standards; a native with none is off and flagged), Isomer sum (the
    isomer entry, read-only) and the Salt factor. Behind the column picker:
    the RLs (the flag's editor writes them), the MDLs, the salt factor's CoA
    lot and the isomer peaks. A section reads an absent field as cleared, so
    every field of every row it lists is drawn and posted, shown or not; an
    RL cell is drawn only where the analyte is reported in that matrix. A
    matrix it is left out of carries that row's RL and MDL in its flag,
    hidden, so reporting it and typing its RL save together."""
    cf, mps, pf, iso, ls = _tab_modules()
    profile = profile or {}
    env = env or {}
    panel = list(profile.get("master_analyte_set") or [])
    matrices = list(profile.get("supported_matrices") or [])
    units = profile.get("unit_map") or {}
    inclusion = profile.get("analyte_matrix_inclusion") or {}
    services = env.get("services") or {}
    titles = mps._analyte_titles(profile)
    cl, library = mps._library()
    full = cl.full_names(library)

    sur_tbl, rl_tbl, salt_tbl, iso_tbl = (mps.SURROGATE_MAP, mps.REPORTING_LIMITS, mps.SALT, mps.ISOMERS)
    sur_cells = _drawn(cf, sur_tbl, profile, env)
    rl_cells = _drawn(cf, rl_tbl, profile, env)
    salt_cells = _drawn(cf, salt_tbl, profile, env)
    iso_cells = _drawn(cf, iso_tbl, profile, env)
    derived = dict((r["key"], r.get("derived_rl")) for r in mps.reporting_limit_rows(profile, env)[1])
    roles = ls.roles(profile)
    standards = [(kw, (services.get(kw) or {}).get("name") or kw)
                 for kw in sorted(k for k, role in roles.items() if role == "surrogate")]

    columns = [Column("panel-{0}".format(i), m, "flag", align="center", group=PANEL_GROUP,
                      unit=units.get(m) or None) for i, m in enumerate(matrices)]
    columns += [Column("quant", "Quantified by", "select"), Column("iso", "Isomer sum", "select")]
    columns += [Column("rl-{0}".format(i), "RL {0}".format(m), "num", align="right", unit=units.get(m) or None,
                       default=False, min=0) for i, m in enumerate(matrices)]
    columns += [Column("mdl-{0}".format(i), "MDL {0}".format(m), "num", align="right",
                       unit=units.get(m) or None, default=False, min=0) for i, m in enumerate(matrices)]
    columns += [Column("salt", "Salt factor", "num", align="right", max=1),
                Column("lot", "CoA lot", "select", default=False),
                Column("linear", "Linear peak", "text", default=False),
                Column("branched", "Branched peaks", "chips", default=False),
                Column("reported", "Reported as", "text", default=False)]

    def drawn(cells, table, key, path):
        name = _named(cf, table, profile, key, path)
        return name, cells.get(name)

    rows = []
    for kw in panel:
        label = titles.get(kw, kw)
        cells = {}
        name, sur = drawn(sur_cells, sur_tbl, (kw,), "surrogate_is")
        quant = (sur or {}).get("value") or ""
        cells["quant"] = Cell(quant, state="set" if quant else "off", name=name, options=standards)
        entry = iso.entries(profile).get(kw)
        summed = iso.is_summed(profile, kw)
        cells["iso"] = Cell(kw if summed else "", state="readonly",
                            options=[(kw, _isomer_words(entry, label))] if summed else [("", EM_DASH)])
        for i, m in enumerate(matrices):
            for col, path in (("rl", "rl"), ("mdl", "mdl")):
                name, rc = drawn(rl_cells, rl_tbl, (m, kw), path)
                if rc is None:
                    continue               # not reported in this matrix
                low = derived.get((m, kw)) if path == "rl" else None
                if rc["value"] == "" and low is not None:
                    cell = Cell(mps.derived_rl_hint(low), state="inherited", source="the lowest calibrator",
                                name=name)
                else:
                    cell = Cell(rc["value"], name=name)
                cells["{0}-{1}".format(col, i)] = cell
        for i, m in enumerate(matrices):
            # the flag: reported or left out, with the RL set for it here
            reported = bool((inclusion.get(kw) or {}).get(m, True))
            name = pf.panel_switch_names(kw, m)[0]
            rl, mdl = cells.get("rl-{0}".format(i)), cells.get("mdl-{0}".format(i))
            if rl is not None:
                typed = _text(rl.value) if rl.state == "set" else ""
                cells["panel-{0}".format(i)] = Cell(_flag_words(reported, typed), name=name,
                                                    data={"in": reported, "rl": typed, "rl_name": rl.name,
                                                          "mdl_name": mdl.name if mdl is not None else None})
            else:
                cells["panel-{0}".format(i)] = _left_out_flag(cf, mps, rl_tbl, profile, m, kw, name)
        name, factor = drawn(salt_cells, salt_tbl, (kw,), "factor")
        lot_name, lot = drawn(salt_cells, salt_tbl, (kw,), "lot_uid")
        lot_value = (lot or {}).get("value") or ""
        lot_options = list((lot or {}).get("choices") or [])
        lot_label = _label_of(lot_options, lot_value) if lot_value else ""
        cells["salt"] = Cell((factor or {}).get("value") or "", name=name,
                             title=SALT_HINT + ("; CoA lot: {0}".format(lot_label) if lot_label else ""))
        cells["lot"] = Cell(lot_value, name=lot_name, options=lot_options)
        for path in ("linear", "branched", "reported"):
            name, rc = drawn(iso_cells, iso_tbl, (kw,), path)
            cells[path] = Cell((rc or {}).get("value") or "", name=name)
        rows.append(Row(kw, label, cells, sub=iso.full_name(profile, kw, full) or None,
                        flags=() if quant else (NO_SURROGATE,)))
    return Sheet("analytes", columns, rows, column_switches=["panel-{0}".format(i) for i in range(len(matrices))],
                 form=ANALYTES_FORM, layout="matrix", actions=ANALYTE_ACTIONS,
                 help=help_dictionary.SECTION_HELP["analytes"])


# The Engine flag the Analytes tab's banner stands for: on, the lab has yet
# to check the method's analyte set; its Confirmed button turns it off.
CONFIRMED_PATH = ("engine", "inclusion_needs_verification")
# the note while the flag is off and no confirmation is on record (a method
# shipped unflagged): Verify again stands beside it all the same
NOT_FLAGGED = "Analyte set not flagged for lab verification"


def confirmed_note(entry):
    """The one-line note the banner becomes: who confirmed the analyte set
    and on which day, from the history entry that last changed the flag
    (config_history.last_change with CONFIRMED_PATH); None when that change
    turned it on, or there is none."""
    for change in (entry or {}).get("changes") or ():
        if tuple(change.get("path") or ()) == CONFIRMED_PATH and not change.get("after"):
            return "Analyte set confirmed by {0} on {1}".format(
                _text(entry.get("who")) or "someone",
                lab_time.show(_text(entry.get("at")), "utc", "%Y-%m-%d"))
    return None


STANDARDS_FORM = "section-standards"
STANDARD_GROUPS = [("sur", "Surrogates (SUR)"), ("is", "Internal standards (IS)")]
SPARE_GROUP = ("spare", "Limits with no standard")
ROLE_WORDS = [("surrogate", "SUR"), ("injection_is", "IS")]
LIMITS_GROUP = "Recovery limits"
# the hover on a Quantifies cell with nothing in it
QUANTIFIES_NOTHING = "Quantifies nothing"
VERIFY = ("VERIFY", "warn")
# the SUR limits' Source while the Engine does not mark them to be verified
VERIFIED = ("VERIFIED", "ok")
# a standard joins or leaves the method by its own action form
STANDARDS_ADD = ("standards-add", "standard", "standards-add-pick", "Add a standard", "Standard")
STANDARDS_REMOVE = ("standards-remove", "standard")
# the column a SUR row's menu copies into every class ("Copy Aqueous to every class")
BASE_LIMITS = "eis-aq"


def counted(n, noun):
    """"1 tier", "2 tiers", "3 matrices"."""
    noun = _text(noun)
    if n != 1:
        noun = noun[:-2] + "ices" if noun.endswith("ix") else noun + "s"
    return "{0} {1}".format(n, noun)


def standards_to_add(profile, env=None):
    """[(keyword, name)]: the site's labelled standards the method does not
    use yet, the add picker's choices."""
    _cf, _mps, _pf, _iso, ls = _tab_modules()
    services = (env or {}).get("services") or {}
    used = ls.grid(profile or {})
    return [(kw, (services[kw] or {}).get("name") or kw) for kw in sorted(services)
            if (services[kw] or {}).get("role") in ls.ROLES and kw not in used]


def _limit_rows(cf, coll, profile, env):
    """The SUR limits grid's stored rows as drawn: [{column: (name, value)}],
    a box's value as it posts ("on" ticked, else blank)."""
    fields = cf._bound(coll, profile).columns
    out = []
    for r in cf.render_collection(coll, profile, env):
        if not r["template"]:
            out.append(OrderedDict((f.path[0], (c["name"], ("on" if c["checked"] else "") if f.kind == cf.BOOL
                                                else c["value"]))
                                   for f, c in zip(fields, r["cells"])))
    return fields, out


def _group_rows(profile, grid, rules):
    """The SUR and IS group rows, each counting its standards and saying how
    they are judged: the IS row's window is the IS Response rule's stored
    limits (QC criteria), never a constant."""
    _cf, mps, _pf, _iso, _ls = _tab_modules()
    n_sur = len([k for k in grid if grid[k].get("role") == "surrogate"])
    n_is = len([k for k in grid if grid[k].get("role") == "injection_is"])
    if rules.rule_state(profile, profile.get("method_id"), "surrogate_recovery") == "off":
        sur = "{0}, recovery not judged (QC criteria)".format(counted(n_sur, "extracted standard"))
    else:
        sur = "{0}, recovery-checked".format(counted(n_sur, "extracted standard"))
    if rules.rule_state(profile, profile.get("method_id"), "is_response") == "off":
        is_ = "{0}, area not judged (QC criteria)".format(counted(n_is, "injection standard"))
    else:
        window = _rule_limits(mps, profile)["is_response"]
        is_ = "{0}, judged on area against the calibration{1} (QC criteria)".format(
            counted(n_is, "injection standard"), ", " + window if window else "")
    words = {STANDARD_GROUPS[0][0]: sur, STANDARD_GROUPS[1][0]: is_}
    return [Row(key, label, {}, sub=words[key], selectable=False) for key, label in STANDARD_GROUPS]


def standards_sheet(profile, env=None):
    """The Labelled standards tab: one row per labelled standard the method
    uses, SUR then IS, each column posting its section's own input name to
    section-standards.

    Shown: the row's menu (⋯), Role (SUR or IS), Linked to (the method's
    other standards) and Quantifies (read-only: the natives the surrogate
    map quantifies against it and the standards linked to it); each row
    carries the natives it quantifies (data-quantifies), which refuse its
    removal. When the Engine judges extracted standards per matrix class,
    a Source column (the lab's citation of the method table; on a SUR,
    VERIFY while the Engine marks the limits to be verified, else
    VERIFIED) and each SUR's recovery limits, aqueous and per class; a blank class reads the aqueous
    limit, and a class marked None is not assessed. Add and Remove sit
    above the grid. A limits row is the standard's whose keyword its name
    resolves to in the compound library, as the pipeline reads it (13C8-PFOSA
    is 13C8-FOSA's), and posts under its stored name; a row no SUR of the
    method takes is drawn in its own group, "Limits with no standard".
    Membership is presence: there is no Used column, and each drawn row
    posts its used field as 1. The SUR limits grid is addressed by position
    and reads an absent row as removed, so every stored row it holds is
    posted, drawn or not."""
    cf, mps, _pf, _iso, ls = _tab_modules()
    rules, _qct = _qc_modules()
    profile = profile or {}
    env = env or {}
    eng = mps._engine_module().engine(profile)
    services = env.get("services") or {}
    grid = ls.grid(profile)
    group_of = {"surrogate": STANDARD_GROUPS[0][0], "injection_is": STANDARD_GROUPS[1][0]}
    linked = {}
    for kw, ref in ls.chain(profile).items():
        linked.setdefault(ref, []).append(kw)

    ls_tbl = mps.LABELLED_STANDARDS
    ls_cells = _drawn(cf, ls_tbl, profile, env)

    def drawn(kw, path):
        name = _named(cf, ls_tbl, profile, (kw,), path)
        return name, (ls_cells.get(name) or {}).get("value") or ""

    limits = eng["eis_recovery_limits"]
    coll = mps.EIS_GRID
    fields, stored_rows = _limit_rows(cf, coll, profile, env)
    surs = sorted(kw for kw in grid if grid[kw].get("role") == "surrogate")
    on_rows, spare = OrderedDict(), []
    if limits:
        resolve = mps.eis_resolver()
        matched = {}
        for vals in stored_rows:           # a row under the standard's own keyword first
            if vals["analyte"][1] in surs and vals["analyte"][1] not in matched:
                matched[vals["analyte"][1]] = vals
        for i, vals in enumerate(stored_rows):
            if any(vals is v for v in matched.values()):
                continue
            kw = resolve(vals["analyte"][1])   # then a spelling the library resolves to it
            if kw in surs and kw not in matched:
                matched[kw] = vals
            else:
                spare.append((i, vals))
        nxt = len(stored_rows)
        for kw in surs:
            if kw in matched:
                on_rows[kw] = matched[kw]
            else:                          # no row yet: a new one, written once a limit is set
                on_rows[kw] = OrderedDict((f.path[0], (cf.collection_name(coll, nxt, f),
                                                       kw if f.path[0] == "analyte" else ""))
                                          for f in fields)
                nxt += 1
    hidden = []
    drawn_rows = list(on_rows.values()) + [vals for _i, vals in spare]
    for vals in stored_rows:               # kept as stored: rows the sheet does not draw
        if not any(vals is v for v in drawn_rows):
            for path, (name, value) in vals.items():
                # a class marked not assessed posts its box, its ends blank
                # (the box wins on the save; a number field refuses "none")
                end = path.rsplit("_", 1)
                if len(end) == 2 and end[1] in ("min", "max") and \
                        (vals.get(end[0] + "_none") or ("", ""))[1] == "on":
                    value = ""
                hidden.append(Cell(value, name=name))
    verify = (VERIFY,) if limits and eng["eis_verify_flag"] else ()
    checked = verify or ((VERIFIED,) if limits else ())     # what a SUR's Source cell says

    def limit_cells(vals):
        """The row's limits cells; its stored name posts as it is. A class
        carries its None box: marked, it is not assessed and posts blank."""
        hidden.append(Cell(vals["analyte"][1], name=vals["analyte"][0]))
        out = {}
        aq = (vals["aq_min"][1], vals["aq_max"][1])
        for key, label in mps._EIS_COLS:
            pair = (vals[key + "_min"][1], vals[key + "_max"][1])
            names = (vals[key + "_min"][0], vals[key + "_max"][0])
            if key == "aq":
                out["eis-" + key] = Cell(pair, name=names)
                continue
            marked = vals[key + "_none"][1] == "on"
            none = (vals[key + "_none"][0], marked, label)
            title = NOT_ASSESSED_WORDS.format(label) if marked else None
            if (marked or pair == ("", "")) and aq != ("", ""):
                out["eis-" + key] = Cell(aq, state="inherited", source="aqueous", name=names, none=none,
                                         title=title)
            else:
                out["eis-" + key] = Cell(pair, name=names, none=none, title=title)
        return out

    columns = [Column("role", "Role", "state", word=True),
               Column("link", "Linked to", "select"), Column("quant", "Quantifies", "links")]
    if limits:
        columns.append(Column("source", "Source", "text"))
        columns += [Column("eis-" + key, label, "pair", align="right", group=LIMITS_GROUP, unit="%", min=0)
                    for key, label in mps._EIS_COLS]
    columns.append(Column("menu", "Row menu", "menu"))         # the row's menu ends the row

    rows = []
    for kw in sorted(grid):
        cells = {}
        name, role = drawn(kw, "role")
        cells["role"] = Cell(role, name=name, options=list(ROLE_WORDS))
        name, ref = drawn(kw, "reference")
        cells["link"] = Cell(ref, name=name, options=[(k, k) for k in sorted(grid) if k != kw])
        natives = ls.removal_blocked_by(profile, kw)
        standards = sorted(linked.get(kw) or [])
        words = ", ".join(w for w in (natives and counted(len(natives), "analyte"),
                                      standards and counted(len(standards), "standard")) if w)
        cells["quant"] = Cell(words, state="readonly", links=[(k, None) for k in natives + standards],
                              title="Quantifies " + ", ".join(natives + standards) if words else QUANTIFIES_NOTHING)
        hidden.append(Cell("1", name=_named(cf, ls_tbl, profile, (kw,), "used")))
        name, source = drawn(kw, "source")
        if limits:
            cells["source"] = Cell(source, name=name, flags=checked if kw in on_rows else ())
        else:                              # no limits drawn: the citation is kept as stored
            hidden.append(Cell(source, name=name))
        if kw in on_rows:
            cells.update(limit_cells(on_rows[kw]))
        cells["menu"] = Cell(None, state="readonly", data={"base": BASE_LIMITS} if kw in on_rows else None)
        label = (services.get(kw) or {}).get("name") or kw
        rows.append(Row(kw, kw, cells, sub=label if label != kw else None,
                        group=group_of.get(grid[kw].get("role")),
                        data={"quantifies": natives, "member": "1"}))
    groups = _group_rows(profile, grid, rules)
    if spare:                              # stored limits no standard of the method takes: shown, never hidden
        groups.append(SPARE_GROUP)
        for i, vals in spare:
            rows.append(Row("limits-{0}".format(i), vals["analyte"][1], limit_cells(vals),
                            group=SPARE_GROUP[0], flags=verify))
    adder = STANDARDS_ADD + (standards_to_add(profile, env),)
    return Sheet("standards", columns, rows, groups=groups, form=STANDARDS_FORM, hidden=hidden,
                 adder=adder, remover=STANDARDS_REMOVE, help=help_dictionary.SECTION_HELP["standards"])


# ── the Matrices tab ────────────────────────────────────────────────────────

MATRICES_FORM = "section-matrices"
# a matrix leaves the method by its own action: the ticked rows
MATRICES_REMOVE = ("matrices-remove", "matrix")
METHOD_ROW = ("method", "All matrices")
NOMINAL_GROUP = "Nominal amount"
RECEIPT_GROUP = "Receipt"
DEGREES = "°C"


def _listing_tiers(mps, profile):
    """{matrix: [tier names]}: the tiers, of every QC type, whose own matrix
    list names the matrix, each name once."""
    out = OrderedDict()
    for _qc, entry in sorted((profile.get("qc_acceptance") or {}).items()):
        for t in (entry.get("tiers") or []) if isinstance(entry, dict) else []:
            if not isinstance(t, dict) or not mps._qc_tiers().is_listed(t):
                continue
            for m in mps.tier_matrices(profile, t):
                names = out.setdefault(m, [])
                if _text(t.get("name")) not in names:
                    names.append(_text(t.get("name")))
    return out


def matrices_to_add(profile, env=None):
    """(input name, [(value, label)]): the matrices collection's next row,
    named as its "+ Add" row is, and the Sample Types the method does not
    list yet. A blank pick posts nothing new."""
    cf, mps, _pf, _iso, _ls = _tab_modules()
    profile = profile or {}
    coll = cf._bound(mps.MATRICES, profile)
    used = set(profile.get("supported_matrices") or [])
    name = cf.collection_name(coll, len(coll.read(profile)), coll.key)
    return name, [(v, l) for v, l in cf._choices(coll.key, profile, env) if v not in used]


def _holding_cell(value, name, matrix):
    """A sample holding cell: days, or the None box (the method sets no
    holding time for the matrix), which posts "none" under the cell's own
    name while the number is off. A blank number is unset."""
    marked = value == NONE_WORD
    return Cell("" if marked else value, name=name, none=(name, marked, matrix),
                title="No holding time for {0}".format(matrix) if marked else None,
                data={"set-none": "1", "none-hover": "No holding time for {0}".format(matrix),
                      "none-text": "None: no holding time for {0}".format(matrix)})


def matrices_sheet(profile, env=None):
    """The Matrices tab: one row per matrix the method supports, each column
    posting its section's own input name to section-matrices.

    Shown: Unit, Aliases, the Matrix class (when the Engine judges extracted
    standards per class), the Matrix factor, the Nominal amount and its unit,
    and per kept item its holding days. Per method, in the heading row:
    each kept item's storage range, the receipt range and its same-day on
    ice rule. Read-only: the Tier group (the tiers whose own matrix list
    names the matrix), when the method's recovery tiers are grouped.
    Behind the column picker, locked: the Sample Type, posted as stored
    (the collection's key; core owns the name, and a matrix is removed by
    its own action). A section reads an absent field as cleared, so every
    field of every row the sections list is drawn and posted."""
    cf, mps, _pf, _iso, _ls = _tab_modules()
    profile = profile or {}
    env = env or {}
    eng = mps._engine_module().engine(profile)
    grouped = mps.grouped_tiers(profile)
    listing = _listing_tiers(mps, profile)
    linked = dict((r["key"][0], r) for r in mps.matrix_factor_rows(profile)[1])

    mf_tbl, nom_tbl, hold_tbl = mps.MATRIX_FACTORS, mps.NOMINAL_AMOUNTS, mps.STORAGE_HOLDING
    mf_cells = _drawn(cf, mf_tbl, profile, env)
    nom_cells = _drawn(cf, nom_tbl, profile, env)
    hold_cells = _drawn(cf, hold_tbl, profile, env)
    holds = dict((r["key"], r) for r in cf._rows(cf._bound(hold_tbl, profile), profile, env)[1])
    coll = [r for r in cf.render_collection(mps.MATRICES, profile, env) if not r["template"]]
    coll_paths = [c.path[0] for c in cf._bound(mps.MATRICES, profile).columns]
    receipt = dict((f.path[-1], f.name) for f in mps.SAMPLE_RECEIPT.fields())
    drawn_receipt = dict((f["name"], f) for g in cf.render(mps.SAMPLE_RECEIPT, profile, env) for f in g["fields"])
    lo, hi, ice = (drawn_receipt[receipt[k]] for k in ("min_c", "max_c", "same_day_on_ice"))

    def drawn(cells, table, key, path):
        name = _named(cf, table, profile, key, path)
        return name, (cells.get(name) or {}).get("value") or ""

    def named_pair(cells, table, key):
        names = tuple(_named(cf, table, profile, key, p) for p in ("min_c", "max_c"))
        return Cell(tuple((cells.get(n) or {}).get("value") or "" for n in names), name=names)

    columns = [Column("name", "Sample Type", "select", default=False),
               Column("unit", "Unit", "select"), Column("aliases", "Aliases", "chips")]
    if eng["eis_recovery_limits"]:
        columns.append(Column("class", "Matrix class", "select"))
    columns += [Column("factor", "Matrix factor", "num", align="right", min=0),
                Column("nom", "Amount", "num", align="right", group=NOMINAL_GROUP, min=0),
                Column("nom-unit", "Unit", "select", group=NOMINAL_GROUP)]
    for key, label, _clock, _st, _h in mps.KEPT:
        columns += [Column("hold-" + key, "Holding", "num", align="right", group=label, unit="days", min=0),
                    Column("store-" + key, "Stored at", "pair", align="right", group=label, unit=DEGREES)]
    columns += [Column("receipt", "Allowed", "pair", align="right", group=RECEIPT_GROUP, unit=DEGREES),
                Column("ice", "Same-day on ice", "switch", align="center", group=RECEIPT_GROUP)]
    if grouped:
        columns.append(Column("tier", "Tier group", "text"))

    head = {"receipt": Cell((lo["value"], hi["value"]), name=(lo["name"], hi["name"])),
            "ice": Cell(bool(ice["checked"]), name=ice["name"], title=ice["label"])}
    for key, _label, _clock, _st, _h in mps.KEPT:
        head["store-" + key] = named_pair(hold_cells, hold_tbl, (key,))

    rows = []
    for r in coll:
        cells = dict(zip(coll_paths, r["cells"]))
        m = cells["name"]["value"]
        out = {"name": Cell(m, state="locked", source="the core Sample Type", name=cells["name"]["name"],
                            options=list(cells["name"]["choices"])),
               "unit": Cell(cells["unit"]["value"], name=cells["unit"]["name"],
                            options=list(cells["unit"]["choices"])),
               "aliases": Cell(cells["aliases"]["value"], name=cells["aliases"]["name"])}
        if "matrix_class" in cells:
            out["class"] = Cell(cells["matrix_class"]["value"], name=cells["matrix_class"]["name"],
                                options=list(cells["matrix_class"]["choices"]))
        name, value = drawn(mf_cells, mf_tbl, (m,), "factor")
        out["factor"] = Cell(value, name=name)
        name, value = drawn(nom_cells, nom_tbl, (m,), "amount")
        out["nom"] = Cell(value, name=name)
        name, value = drawn(nom_cells, nom_tbl, (m,), "unit")
        out["nom-unit"] = Cell(value, name=name, options=list((nom_cells.get(name) or {}).get("choices") or ()))
        for key, _label, _clock, _st, _h in mps.KEPT:
            name, value = drawn(hold_cells, hold_tbl, (key,), m)
            blank = (holds[(key,)].get("placeholders") or {}).get(m)
            if key == "sample":
                out["hold-" + key] = _holding_cell(value, name, m)
            else:
                out["hold-" + key] = Cell(value, name=name, title=blank if blank and not value else None)
        if grouped:
            out["tier"] = Cell(", ".join(listing.get(m) or []), state="readonly")
        row = linked.get(m) or {}
        flags = ((row["note"], "warn"),) if row.get("warn") and row.get("note") else ()
        rows.append(Row(m, m, out, group=METHOD_ROW[0], flags=flags, data={"member": "1"}))
    groups = [Row(METHOD_ROW[0], METHOD_ROW[1], head, selectable=False)]
    add_name, addable = matrices_to_add(profile, env)
    adder = (MATRICES_FORM, add_name, "matrices-add-pick", "Add a matrix", "Sample Type", addable, "matrix")
    return Sheet("matrices", columns, rows, groups=groups, form=MATRICES_FORM, adder=adder,
                 remover=MATRICES_REMOVE if len(rows) > 1 else None,
                 help=help_dictionary.SECTION_HELP["matrices"])


# ── the QC criteria tab ─────────────────────────────────────────────────────

QC_FORM = "section-qc"
# The LFSMD row's sub-label: the one basis every method's RPD has.
LFSMD_SUB = u"RPD of the two measured concentrations"
# the window grid's QC types, in this order, with their short names
QC_TYPES = [("LFB", "LFB"), ("LFSM", "LFSM"), ("LFSMD", "LFSMD RPD"), ("Dup", "SD RPD")]
QC_LEVELS = [("ordinary", "Ordinary spike"), ("low", "Low level")]
# each QC type's tiers: the declared collection that holds them
TIER_SECTIONS = [("LFSM", "tiers"), ("LFB", "tiers_lfb"), ("LFSMD", "lfsmd"), ("Dup", "dup")]
# the sections the tab draws whatever QC types the method runs
QC_FIXED_SECTIONS = ["engine_notes_rt", "xbatch", "blk", "mxb", "cal", "cal_levels",
                     "cal_scale", "engine_notes_conf", "engine_notes_is", "run_rules"]
# the Low-level recoveries row (rules.LOW_LEVEL_ROW): whether a recovery
# judged against a low-level tier is judged
LOW_LEVEL_RULE = ("low_level_recovery", "Low-level recoveries")
LOW_LEVEL_STATE = "rulestate." + LOW_LEVEL_RULE[0]
# the Show segment's own field above the window grid: the QC type shown,
# read by the page and never posted
SHOW_FIELD = "qc-show"
RUN_LABELS = {"Dup": "SD"}
# the sub-labels of the QC-type and the blank rows, and the limits words of
# the rows whose limits are the window grid's
QC_ROW_SUB = "Analyte recoveries"
BLANK_SUB = "Blank limit"
IN_THE_GRID = "In the grid below"
WINDOWS_REGION = "qc-ed-windows"
BLANK_REGION = "qc-ed-blank"
BATCH_REGION = "qc-ed-xbatch"


def _qc_modules():
    """(rules, qc_types), imported when the tab is built."""
    from senaite.pfas.qc import rules, qc_types
    return rules, qc_types


def recovery_section_ids(profile):
    """The recovery sections the tab draws for this method: the groups and
    the LFSM tiers always; the spike levels of the spiked QC types it runs
    (LFSMD shares the LFSM levels); LFB, LFSMD and Dup tiers where it holds
    them."""
    _rules, qct = _qc_modules()
    profile = profile or {}
    on = set(qct.enabled_qc_types(profile))
    if "LFSMD" in on:
        on.add("LFSM")
    qca = profile.get("qc_acceptance") or {}
    ids = ["groups", "tiers"] + ["spk_" + q for q in ("LFSM", "LFB", "LCS") if q in on]
    return (ids + (["tiers_lfb"] if "LFB" in qca else []) + (["dup"] if "Dup" in qca else []) +
            (["lfsmd"] if "LFSMD" in qca else []))


def qc_section_ids(profile):
    """Every section the QC criteria tab's form saves, in order."""
    return recovery_section_ids(profile) + list(QC_FIXED_SECTIONS)


def _runs(profile, qc):
    """Whether the method runs `qc`, as the engine reads it (an entry
    without the flag runs)."""
    entry = ((profile or {}).get("qc_acceptance") or {}).get(qc)
    return isinstance(entry, dict) and bool(entry.get("enabled", True))


def qc_type_offers(profile, env=None):
    """[{key, code, enabled, blank}]: every QC type the tab can switch on or
    off (the lab's QC types, env["qc_codes"], and any the method holds)."""
    _cf, mps, _pf, _iso, _ls = _tab_modules()
    codes = (env or {}).get("qc_codes") or []
    blanks = set(code for code, _l in mps.BLANK_TYPES)
    rows = mps.qc_type_rows(profile or {}, dict((c, c) for c in codes))
    return [{"key": r["key"], "code": r["code"], "enabled": r["enabled"], "blank": r["key"] in blanks}
            for r in rows if r["toggle"]]


def qc_rows(profile, env=None):
    """[{key, code, label, sub}]: the rule table's QC-type rows, one per
    offered QC type that is not a blank and has a row (rules.qc_row_key),
    recoveries before RPDs: key qc_type.<the stored spelling>, the label
    from the type's kind ("LFSM recovery", "SD RPD")."""
    _cf, mps, _pf, _iso, _ls = _tab_modules()
    rules, _qct = _qc_modules()
    kinds = ["recovery", "rpd"]
    out = []
    for o in qc_type_offers(profile, env):
        key = rules.qc_row_key(o["key"])
        if o["blank"] or not key:
            continue
        kind = mps.QC_KIND.get(o["code"], "other")
        name = RUN_LABELS.get(o["key"], o["key"])
        label = {"recovery": name + " recovery", "rpd": name + " RPD"}.get(kind, name)
        order = (kinds.index(kind) if kind in kinds else len(kinds), label)
        out.append((order, {"key": key, "code": o["key"], "label": label,
                            "sub": LFSMD_SUB if o["key"] == "LFSMD" else QC_ROW_SUB}))
    return [r for _o, r in sorted(out, key=lambda pair: pair[0])]


def qc_row_state(profile, code):
    """A QC type's or blank's row as the tab draws it: the state the worker
    reads (rules.rule_state; a type the method does not hold is Enforced).
    Drawn set, never inherited, so the state posts as shown: the Show
    picker reads it, and the writer stores only a state that differs."""
    rules, _qct = _qc_modules()
    return rules.rule_state(profile, None, rules.qc_row_key(code))


def shown_qc_type(profile, qc_type="LFSM"):
    """The QC type the window grid shows: the one asked for unless its row
    is Off, else the first whose row is Enforced or Evaluate."""
    qc_type = qc_type if qc_type in dict(QC_TYPES) else "LFSM"
    if qc_row_state(profile, qc_type) != "off":
        return qc_type
    return next((q for q, _l in QC_TYPES if qc_row_state(profile, q) != "off"), qc_type)


def required_rows(profile, group):
    """The Calibration & CCV criteria of `group` (calibration, confirmation,
    is_response) that may be required, each with whether the Engine
    requires it (engine.required_keys)."""
    cf, mps, _pf, _iso, _ls = _tab_modules()
    req = (((profile or {}).get("engine") or {}).get("required_keys") or {}).get(group) or []
    return [{"key": f.path[1], "label": f.label, "on": f.path[1] in req}
            for f in mps.SECTIONS["cal"].fields()
            if len(f.path) == 2 and f.path[0] == group and f.kind in (cf.NUMBER, cf.INT)]


def _region_id(sid, group):
    return "qc-ed-" + re.sub(r"[^a-z0-9]+", "-", "{0} {1}".format(sid, group).lower()).strip("-")


def _group_parts(mps, pf, sid, group):
    """A section group's parts: the group, then the Required chips and the
    flag notes it carries (profile_form.CAL_GROUP_PARTS, by its first
    field), then what the region shows beside it."""
    parts = [{"kind": "section", "sid": sid, "group": group}]
    fields = dict(mps.SECTIONS[sid].groups).get(group) or []
    extra = pf.CAL_GROUP_PARTS.get(fields[0].name) if sid == "cal" and fields else None
    if extra and extra.get("required"):
        parts.append({"kind": "required", "group": extra["required"]})
    if extra and extra.get("notes"):
        parts.append({"kind": "table", "sid": extra["notes"]})
    if (sid, group) == ("cal", "Calibration"):
        parts += [{"kind": "collection", "sid": "cal_levels", "title": "Calibration levels"},
                  {"kind": "table", "sid": "cal_scale", "title": "Per-analyte calibration range"}]
    if sid == "run_rules":
        parts += [{"kind": "section", "sid": "run_rules", "group": title}
                  for title, _f in mps.SECTIONS[sid].groups if title != group]
    return parts


def rule_editors(profile, env=None):
    """The regions a rule's row opens, in the order of their first rule:
    [{id, title, rules: [rule keys], parts, open, sec}]. A region with a
    `sec` is one of the tab's sections (the analyte recoveries, the
    extraction batch size), drawn closed under its own summary; the others
    open under the rule table from their rule's row. A part is a declared
    section (or one of its groups), table or collection, drawn by its
    config-form macro on section-qc, a rule group's Required chips, or the
    spike levels recommended from the calibration curve (spike_hint). Each
    section group is drawn once, in the region of the first rule that owns
    it; together the parts draw every section the form saves."""
    _cf, mps, pf, _iso, _ls = _tab_modules()
    rules, _qct = _qc_modules()
    profile = profile or {}
    ids = qc_section_ids(profile)
    regions = OrderedDict()
    for rule in rules.RULE_LIBRARY:
        editor = rule.get("editor") or ""
        if not editor.startswith("drawer:"):
            continue
        _d, sid, group = editor.split(":", 2)
        rid = _region_id(sid, group)
        if rid not in regions:
            regions[rid] = {"id": rid, "title": "", "rules": [], "labels": [], "sec": None,
                            "parts": _group_parts(mps, pf, sid, group), "open": False}
        regions[rid]["rules"].append(rule["key"])
        regions[rid]["labels"].append(rule["label"])
    for r in regions.values():
        r["title"] = ", ".join(r.pop("labels"))
    # what the window grid resolves from redraws it as it is edited
    # (preview): the tiers table first, then who each tier applies to --
    # each listed tier's own matrices, then the key analytes
    tier_sections = dict(TIER_SECTIONS)
    parts = [{"kind": "collection", "sid": tier_sections[qc], "qc": qc, "title": "Tiers: " + label,
              "preview": True} for qc, label in QC_TYPES if tier_sections[qc] in ids]
    parts += [{"kind": "lists", "title": mps.GROUPS_TITLE,
               "lists": [{"qc": x["qc"], "sid": x["sid"]} for x in parts]},
              {"kind": "section", "sid": "groups", "group": None, "preview": True, "bare": True}]
    parts += [{"kind": "table", "sid": "engine_notes_rt"}]
    spikes = [sid for sid in ids if sid.startswith("spk_")]
    parts += [{"kind": "spike_hint"}] if spikes else []
    parts += [{"kind": "collection", "sid": sid, "title": "Spike levels: " + mps.SPIKE_LABELS[sid[4:]]}
              for sid in spikes]
    gridded = dict(QC_TYPES)
    regions[WINDOWS_REGION] = {"id": WINDOWS_REGION, "title": "Analyte recoveries", "sec": "windows",
                               "rules": [r["key"] for r in qc_rows(profile, env) if r["code"] in gridded] +
                                        [LOW_LEVEL_RULE[0]],
                               "parts": parts, "open": True}
    regions[BLANK_REGION] = {"id": BLANK_REGION, "title": "Blank limits", "sec": None,
                             "rules": [rules.BLANK_KEY(code) for code, _l in mps.BLANK_TYPES],
                             "parts": [{"kind": "table", "sid": "blk"},
                                       {"kind": "section", "sid": "mxb", "group": None}], "open": False}
    regions[BATCH_REGION] = {"id": BATCH_REGION, "title": "Extraction batch size", "sec": "xbatch", "rules": [],
                             "parts": [{"kind": "section", "sid": "xbatch", "group": None}], "open": True}
    return list(regions.values())


def _g(v):
    try:
        return "{0:g}".format(float(v))
    except (TypeError, ValueError):
        return _text(v)


def _range(lo, hi, unit="%"):
    if lo in (None, "") or hi in (None, ""):
        return ""
    return "{0} {1} {2} {3}".format(_g(lo), EN_DASH, _g(hi), unit).strip()


def _rule_limits(mps, profile):
    """{rule key: the effective limits in words}, from the sections' values
    (blank where a rule's limits are unset)."""
    iv = profile.get("instrument_verification") or {}

    def get(group, key):
        v = (iv.get(group) or {}).get(key)
        return None if v in (None, "") else v

    def said(words, group, key):
        v = get(group, key)
        return words.format(_g(v)) if v is not None else ""

    def pair(group, lo, hi):
        return _range(get(group, lo), get(group, hi))

    def joined(*parts):
        return ", ".join(p for p in parts if p)

    cl = mps._cl()
    levels = [v for v in (cl._num(r.get("conc")) for r in cl.rows(profile)) if v is not None]
    single = get("confirmation", "single_transition_analytes") or []
    low_ccv = pair("ccv", "low_level_min", "low_level_max")
    return {
        "is_response": pair("is_response", "vs_ical_avg_min", "vs_ical_avg_max"),
        "is_vs_ccv": pair("is_response", "vs_last_ccv_min", "vs_last_ccv_max"),
        "rrt_deviation": joined(said("Relative RT \u00b1 {0} %", "confirmation", "rrt_tol_pct"),
                                said("RT \u00b1 {0} min", "confirmation", "rt_tol_abs_min")),
        "ion_ratio": said("\u00b1 {0} %", "confirmation", "ion_ratio_tol_pct"),
        "cal_r2": said("\u2265 {0}", "calibration", "r2_min"),
        "ccv_recovery": joined(pair("ccv", "recovery_min", "recovery_max"), "low level " + low_ccv if low_ccv else ""),
        "ccv_frequency": said("Every {0} samples", "ccv", "frequency"),
        "sn_min": joined(said("Quan \u2265 {0}", "confirmation", "sn_quan_min"),
                         said("confirm \u2265 {0}", "confirmation", "sn_confirm_min")),
        "single_transition_confirm": counted(len(single), "analyte") if single else "",
        "over_range": "Top level {0} {1}".format(_g(max(levels)), cl.unit(profile)).strip() if levels else "",
    }


def _blank_words(vals):
    v = (vals or {}).get("max_conc_x_rl")
    if v is None:
        return ""
    return "{0} {1:.3g} \u00d7 RL".format("below" if vals.get("fails_at_limit") else "at most", float(v))


NO_LIMIT_WORDS = "no limit set"
NO_LIMIT_HOVER = "Enforced, but no limit is set: set one or switch the rule off"
NO_LIMIT_EVALUATE = "Evaluate, but no limit is set: set one or switch the rule off"
# a rule whose value is a list, not a limit: none listed is nothing to judge
# (inert by design), never a missing limit
NOT_A_LIMIT = ("single_transition_confirm",)


def _limits_cell(words, state):
    """A rule's effective limits, read-only: its words; with none, an
    Enforced rule says "no limit set" in coral, an Evaluate rule the same
    words muted, and an Off rule (it owes no limit) an em dash."""
    if words:
        return Cell(words, state="readonly")
    if state == "enforced":
        return Cell("", state="readonly", flags=((NO_LIMIT_WORDS, "fault"),), title=NO_LIMIT_HOVER)
    if state == "evaluate":
        return Cell("", state="readonly", flags=((NO_LIMIT_WORDS, "quiet"),), title=NO_LIMIT_EVALUATE)
    return Cell(EM_DASH, state="readonly")


# a rule the profile does not hold takes the method's default state: its
# control stays outlined, and its Scope cell says so after the scope, muted
# ("Method · default")
DEFAULT_ASIDE = ("\u00b7 default", "aside")


def _no_window(mps, profile, qcs):
    """The panel analytes that resolve to no window, at an ordinary or a low
    spike, in some matrix they are reported in, for any of `qcs`."""
    inclusion = profile.get("analyte_matrix_inclusion") or {}
    missing = set()
    for qc in qcs:
        grids = [mps.recovery_grid(profile, None, qc, level) for level, _l in QC_LEVELS]
        for rows in zip(*[g["rows"] for g in grids]):
            for kw in rows[0]["keys"]:
                for i, m in enumerate(grids[0]["matrices"]):
                    if not (inclusion.get(kw) or {}).get(m, True):
                        continue
                    if all(r["analytes"][kw][i]["window"] is None for r in rows):
                        missing.add(kw)
    return missing


def rules_table(profile, env=None):
    """The QC criteria tab's rule table: one row per rule of the library in
    its order, then one per QC type the tab offers (qc_rows, under
    "Analyte recoveries"), Low-level recoveries, and one per blank (under
    "Blank limit").

    Every row posts one of three states, Enforced, Evaluate or Off. A
    rule's posts rulestate.<key>; a state the profile does not hold is
    inherited from the method's default and posts blank, so an untouched
    tab writes nothing; a held state that differs from the default names
    it. A QC type's or blank's posts rulestate.<qc_type.CODE | blank.CODE>,
    drawn as qc_row_state and named in qc_offered so the save reads it;
    Low-level recoveries' posts rulestate.low_level_recovery, which the
    spike-level segment also reads (profile_form.apply_loose stores either
    only where it differs from what the row reads). A QC-type row that is
    not Off counts, in coral, the panel analytes that resolve to no window
    of its type. Scope and Effective limits are read-only; a rule whose
    limits are on this tab opens their region (rule_editors)."""
    _cf, mps, _pf, _iso, _ls = _tab_modules()
    rules, _qct = _qc_modules()
    profile = profile or {}
    env = env or {}
    mid = profile.get("method_id") or ""
    region_of = {}
    for region in rule_editors(profile, env):
        for key in region["rules"]:
            region_of.setdefault(key, region["id"])
    words = _rule_limits(mps, profile)
    states = profile.get("rule_states") if isinstance(profile.get("rule_states"), dict) else None
    toggles = profile.get("rule_toggles") or {}
    bare = dict((k, v) for k, v in profile.items() if k not in ("rule_states", "rule_toggles"))
    names = dict((st, st.capitalize()) for st in rules.STATES)

    def edit(key):
        rid = region_of.get(key)
        return Cell("Edit", state="readonly", expands=rid) if rid else None

    columns = [Column("state", "State", "state"), Column("scope", "Scope", "text"),
               Column("limits", "Effective limits", "text"), Column("edit", "Limits", "text")]
    rows = []
    for rule in rules.RULE_LIBRARY:
        key = rule["key"]
        value = rules.rule_state(profile, mid, key)
        name = "rulestate." + key
        default = rules.rule_state(bare, mid, key)
        if key in (states if states is not None else toggles):
            # set here; the edge marks only a state that differs from the default
            state = Cell(value, name=name,
                         source="the default, {0}".format(names[default]) if value != default else None)
        else:
            source = "the rule switch" if states is not None and key in toggles else "the method default"
            state = Cell(value, state="inherited", name=name, source=source)
        if key == "surrogate_recovery":
            limits = Cell(_surrogate_windows(mps, profile), state="readonly",
                          links=[("Isotope standards", "#pane-standards")],
                          title="Each standard's window, on the Isotope standards tab")
        elif key == "mdl_check":
            limits = Cell("MDL", state="readonly", links=[("Analytes", "#pane-analytes")],
                          title="Each analyte's MDL, on the Analytes tab")
        elif key in NOT_A_LIMIT:
            limits = Cell(words.get(key) or EM_DASH, state="readonly")
        else:
            limits = _limits_cell(words.get(key), value)
        scope_cell = Cell(rule["scope"], state="readonly",
                          flags=(DEFAULT_ASIDE,) if state.state == "inherited" else ())
        rows.append(Row(key, rule["label"], {"state": state, "scope": scope_cell,
                                             "limits": limits, "edit": edit(key)}))

    scope = rules.SCOPE_WINDOWS
    gridded = dict(QC_TYPES)
    qc = qc_rows(profile, env)
    qca = profile.get("qc_acceptance") or {}
    for r in qc:
        value = qc_row_state(profile, r["code"])
        # a type the method holds, in the grid: a type it never runs has no
        # injections, so nothing of it can lack a window
        windowed = r["code"] in gridded and isinstance(qca.get(r["code"]), dict)
        missing = _no_window(mps, profile, [r["code"]]) if windowed and value != "off" else ()
        n = len(missing)
        flags = ("{0} {1} no window".format(n, "analyte has" if n == 1 else "analytes have"),) if n else ()
        rows.append(Row(r["key"], r["label"], {
            "state": Cell(value, name="rulestate." + r["key"]), "scope": Cell(scope, state="readonly"),
            "limits": Cell(IN_THE_GRID if windowed else EM_DASH, state="readonly"),
            "edit": edit(r["key"]) if windowed else None}, sub=r["sub"], flags=flags))

    rows.append(Row(LOW_LEVEL_RULE[0], LOW_LEVEL_RULE[1], {
        "state": Cell(rules.rule_state(profile, None, rules.LOW_LEVEL_ROW), name=LOW_LEVEL_STATE),
        "scope": Cell(scope, state="readonly"), "limits": Cell(IN_THE_GRID, state="readonly"),
        "edit": edit(LOW_LEVEL_RULE[0])}))

    blank_vals = mps.read_blank_limits(profile)
    for code, label in mps.BLANK_TYPES:
        key = rules.BLANK_KEY(code)
        value = qc_row_state(profile, code)
        rows.append(Row(key, label, {"state": Cell(value, name="rulestate." + key),
                                     "scope": Cell(rules.SCOPE_METHOD, state="readonly"),
                                     "limits": _limits_cell(_blank_words(blank_vals.get((code,))), value),
                                     "edit": edit(key)},
                        sub=BLANK_SUB))
    offered = [r["code"] for r in qc] + [code for code, _l in mps.BLANK_TYPES]
    hidden = [Cell(",".join(offered), name="qc_offered")]
    return Sheet("rules", columns, rows, selection=False, picker=False, form=QC_FORM, hidden=hidden)


def _surrogate_windows(mps, profile):
    """The surrogate windows the Isotope standards tab holds, in words: one
    per standard where the Engine judges standards on their own limits,
    else the method's one surrogate window when it is set."""
    if mps._engine_module().engine(profile)["eis_recovery_limits"]:
        n = len(mps.EIS_GRID.read(profile))
    else:
        window = (profile.get("instrument_verification") or {}).get("surrogate_window") or {}
        n = 1 if any(window.get(k) not in (None, "") for k in ("recovery_min", "recovery_max")) else 0
    return "1 window" if n == 1 else "{0} windows".format(n)


def _column_grids(mps, profile, env, qc_type):
    """{level: recovery_grid} for `qc_type` at every spike level the grid's
    columns are compared over: the ordinary spike, and the low level
    wherever a tier of the type sets one (without one, the low level is
    the ordinary grid). Whether Low-level recoveries is Off does not
    matter: the page can show the low level before that row is saved, and a
    column must never claim matrices alike at a level it did not compare;
    the columns stay the same whichever level the picker shows."""
    levels = ["ordinary"]
    if any(t.get(mps.LOW_LEVEL_KEY) for t in mps._tiers(profile, qc_type)):
        levels.append("low")
    return OrderedDict((lvl, mps.recovery_grid(profile, env, qc_type, lvl)) for lvl in levels)


def _reported(inclusion, kw, matrix):
    """Is `kw` reported in `matrix` (the panel's analyte x matrix inclusion,
    reported unless left out)?"""
    return bool((inclusion.get(kw) or {}).get(matrix, True))


def _matrix_columns(mps, profile, grids, qc_type):
    """[(label, [matrices])]: the window grid's matrix columns, from
    `grids` (_column_grids). Matrices alike for every panel analyte at every
    level -- the same window, set by the same tier in the same way (a cell
    stands for its whole column and opens one tier in the drawer), and the
    same analytes reported -- share one column, "All N matrices", whose
    header lists them: the largest such set (the first, on a tie), drawn
    first. Every other matrix differs for some analyte and is its own
    column, named for it, in the method's order."""
    inclusion = profile.get("analyte_matrix_inclusion") or {}
    grids = list(grids)
    matrices = grids[0]["matrices"] if grids else []
    alike = OrderedDict()
    for i, m in enumerate(matrices):
        said = []
        for grid in grids:
            for g in grid["rows"]:
                for kw in g["keys"]:
                    if not _reported(inclusion, kw, m):
                        said.append(None)                 # not reported here
                        continue
                    c = g["analytes"][kw][i]
                    said.append((mps.window_text(c["window"], qc_type), c["index"], c.get("set_by")))
        alike.setdefault(tuple(said), []).append(m)
    shared = max(alike.values(), key=len) if alike else []
    if len(shared) < 2:
        return [(m, [m]) for m in matrices]
    return [("All {0} matrices".format(len(shared)), shared)] + [(m, [m]) for m in matrices if m not in shared]


def _tier_words(mps, cells, qc_type):
    """What a group row says it takes, from its cells in every matrix, each
    tier by its name as typed: "· X lo – hi"; where a tier for listed
    matrices sets some, "· A lo – hi where listed, else B lo – hi"; "· no
    tier" where none applies."""
    seen = OrderedDict()
    for c in cells:
        seen.setdefault(c["index"], c)

    def said(c):
        if c["index"] is None:
            return "no tier"
        window = mps.window_text(c["window"], qc_type) if c["window"] is not None else "no window"
        return "{0} {1}".format(_text(c["tier"]), window)

    # a tier scoped to the cells it sets (recovery_grid's set_by "cell"):
    # the one test of a tier's own matrix list, tier_names_matrix
    scoped = set(c["index"] for c in cells if c.get("set_by") == "cell")

    def listed(i):
        return i in scoped
    where = [c for i, c in seen.items() if listed(i)]
    rest = [c for i, c in seen.items() if not listed(i)]
    if len(seen) == 1:
        words = said(list(seen.values())[0])
    elif where and len(rest) == 1:
        words = "{0} where listed, else {1}".format(", ".join(said(c) for c in where), said(rest[0]))
    else:
        words = ", ".join(said(c) for c in seen.values())
    return "\u00b7 " + words


# a folded group names at most this many members that differ, then "and n more"
SUMMARY_NAMED = 3
NO_WINDOW_WORDS = "no window"
NO_VALUES_WORDS = "no values"


def _most(values, weights):
    """The value carrying the most weight; the first such on a tie."""
    totals = OrderedDict()
    for v, w in zip(values, weights):
        totals[v] = totals.get(v, 0) + w
    return max(totals.items(), key=lambda kv: kv[1])[0] if totals else None


def group_summary(members, columns, group=None):
    """What a folded group row says its members hold, from the windows as
    words: `members` [(name, [window per column, None where not reported])],
    `columns` [(label, [matrices])], `group` the group's own window per
    column (by default, what most members hold there). The window shared
    is the one that covers the most matrices.
    All alike: "20 analytes · all 40 – 130". Columns whose window differs
    are named: "4 analytes · Eggs 80 – 120 · all 65 – 135 elsewhere".
    Members that differ from the group are named, up to three, then "and n
    more": "4 analytes · 3 at 40 – 130 · PFOS 50 – 150", with "in <column>"
    where a member differs in some columns only (and no "0 at" where every
    member differs)."""
    labels = [label for label, _ms in columns]
    weights = [max(1, len(ms or ())) for _label, ms in columns]
    if group is None:
        group = [_most([vals[j] for _n, vals in members if vals[j] is not None], [1] * len(members))
                 for j in range(len(columns))]
    shown = [(g, w) for g, w in zip(group, weights) if g is not None]
    shared = _most([g for g, _w in shown], [w for _g, w in shown])
    apart = [(labels[j], g) for j, g in enumerate(group) if g is not None and g != shared]
    odd = []
    for name, vals in members:
        diffs = [(j, v) for j, v in enumerate(vals)
                 if v is not None and group[j] is not None and v != group[j]]
        if diffs:
            reported = [j for j, v in enumerate(vals) if v is not None]
            alike = len(set(v for _j, v in diffs)) == 1
            if len(columns) == 1 or (alike and len(diffs) == len(reported)):
                odd.append("{0} {1}".format(name, diffs[0][1]))
            else:
                at = OrderedDict()
                for j, v in diffs:
                    at.setdefault(v, []).append(labels[j])
                odd.append("{0} {1}".format(name, " and ".join(
                    "{0} in {1}".format(v, " and ".join(ls)) for v, ls in at.items())))
    n = len(members)
    parts = ["1 analyte" if n == 1 else "{0} analytes".format(n)]
    if shared is None:
        # nothing to say a window of: never "all None"
        parts.append(NO_VALUES_WORDS)
        return " \u00b7 ".join(parts)
    none = shared == NO_WINDOW_WORDS          # "no window" is a state, never "at" or "all"
    if not apart and not odd:
        parts.append(NO_WINDOW_WORDS if none else "all {0}".format(shared))
        return " \u00b7 ".join(parts)
    if apart:
        parts.append(", ".join("{0} {1}".format(label, g) for label, g in apart))
        parts.append("{0} elsewhere".format(NO_WINDOW_WORDS if none else "all " + shared))
    elif n > len(odd):
        # how many hold the group's window; none: the members are named alone
        parts.append("{0} {1}".format(n - len(odd), "with " + NO_WINDOW_WORDS if none else "at " + shared))
    if odd:
        named = ", ".join(odd[:SUMMARY_NAMED])
        if len(odd) > SUMMARY_NAMED:
            named += " and {0} more".format(len(odd) - SUMMARY_NAMED)
        parts.append(named)
    return " \u00b7 ".join(parts)


def posted_tier_rows(form):
    """{collection id: {tier name: row index}}: where each tier sits in the
    tier collections a page posted. A preview resolves the tiers as edited
    (a cleared name removes a tier, so later tiers move up), while the
    page's rows keep their own indices: the drawer must edit the row that
    holds the tier it names."""
    cf, mps, _pf, _iso, _ls = _tab_modules()
    out = {}
    for _qc, sid in TIER_SECTIONS:
        coll = mps.SECTIONS[sid]
        head, tail = cf.collection_name(coll, 0, coll.key).split("__0__", 1)
        pattern = re.compile(r"^{0}__(\d+)__{1}$".format(re.escape(head), re.escape(tail)))
        rows = {}
        for key, value in (form or {}).items():
            m = pattern.match(_text(key))
            name = _text(value).strip()
            if m and name:
                rows[name] = int(m.group(1))
        out[sid] = rows
    return out


def _new_tier(mps, profile, winner, flags, matrix, level):
    """(analyte group, matrix scope) of the tier that would take a cell from
    its winner: the most specific group the engine selects the analyte by
    (no labelled standard, else a key analyte in a matrix a key-analyte
    tier lists -- the new tier listing the cell's column --, else the
    method default), inserted before the winner. None where a new tier
    would not change the cell (the winner is already of that group and
    scope), at a low spike, or where the tier checker keeps one ordinary
    tier (a method whose Engine does not group tiers): the tier is edited
    instead."""
    if level != "ordinary":
        return None
    if not mps.grouped_tiers(profile):
        return ("all", "all") if winner is None else None
    k, n = flags
    if n:
        target = ("no_std", "all")
    elif k and mps._qc_tiers().key_tier_lists(profile, matrix):
        target = ("key", mps.LISTED)
    else:
        target = ("linked", "all")
    if winner is None:
        return target
    group = winner.get("analyte_group") or "all"
    if target[0] == "linked":
        same = group in ("linked", "all")
    elif target[0] == "no_std":
        same = group == "no_std"
    else:
        same = group == "key" and mps.tier_names_matrix(profile, winner, matrix)
    return None if same else target


def _tier_covers(mps, profile, env, qc_type):
    """{tier index: {analyte group title: [matrices]}}: every group and
    matrix of the panel each tier of `qc_type` sets, at either spike level."""
    inclusion = profile.get("analyte_matrix_inclusion") or {}
    covers = {}
    for lvl, _l in QC_LEVELS:
        grid = mps.recovery_grid(profile, env, qc_type, lvl)
        for g in grid["rows"]:
            for kw in g["keys"]:
                for i, m in enumerate(grid["matrices"]):
                    c = g["analytes"][kw][i]
                    if c["index"] is not None and (inclusion.get(kw) or {}).get(m, True):
                        seen = covers.setdefault(c["index"], OrderedDict()).setdefault(g["title"], [])
                        if m not in seen:
                            seen.append(m)
    return covers


def _with_tier(profile, qc_type, at, group, scope, matrices=()):
    """The profile with a (group, scope) tier inserted at `at` in `qc_type`
    (a listed one listing `matrices`), a window set so that it judges what
    it takes."""
    q = dict(profile)
    qca = dict(q.get("qc_acceptance") or {})
    entry = dict(qca.get(qc_type) or {})
    tiers = list(entry.get("tiers") or [])
    tier = {"name": "", "analyte_group": group, "matrix_scope": scope,
            "recovery_min": 0.0, "recovery_max": 200.0, "rpd_max": 100.0}
    if scope != "all":
        tier["matrices"] = list(matrices)
    tiers.insert(at, tier)
    entry["tiers"] = tiers
    qca[qc_type] = entry
    q["qc_acceptance"] = qca
    return q


def windows_sheet(profile, env=None, qc_type="LFSM", level="ordinary", posted=None):
    """The applied windows, the recovery editor: one row per panel analyte
    under its analyte group (the group row shows what an analyte of that
    group alone gets and names the tiers it takes), one column per set of
    matrices alike for every analyte (_matrix_columns: the shared column
    lists its matrices, every matrix that differs is its own), each cell the
    window the engine applies to that analyte there for `qc_type` at an
    ordinary or a low spike, resolved per analyte with the engine's own
    flags (method_profile_sections.recovery_grid), values centred. A cell's
    state is how it is drawn: set where its window is set on the cell
    itself, inherited from the tier that sets it or the method's default
    tier, off (an em dash, the row flagged NO WINDOW) where no window
    applies, and absent where the analyte is not reported in the matrix.

    Nothing in it posts. Its data-* attributes give the drawer the window,
    the tier that sets it (its group and scope, its row's name prefix in the
    page's tier collection, `posted` mapping a tier name to the row a page
    posted it in), what applies with that tier removed, what removing it
    changes (every analyte group and matrix it sets, at either spike level),
    and the group and scope of the tier that would take the cell from it
    (empty where the tier is edited instead), with every group and matrix
    that new tier would set and the tiers it would leave setting no cell,
    and the drawer's numbers: the window (lo, hi), the tier a reset on the
    cell reverts to (tier-name, tier-lo, tier-hi; fallback-is-default where
    that is the method's default tier, from the same resolver, never from
    equal numbers) and the method's default tier (method-lo, method-hi), an
    RPD limit a maximum alone; set-kind is what sets the cell (cell, tier,
    method: recovery_grid's set_by), a window or not.
    A tier that applies but sets no window is still the cell's tier."""
    cf, mps, _pf, _iso, _ls = _tab_modules()
    profile = profile or {}
    qc_type = shown_qc_type(profile, qc_type)
    level = level if level in dict(QC_LEVELS) else "ordinary"
    grids = _column_grids(mps, profile, env, qc_type)
    grid = grids.get(level) or mps.recovery_grid(profile, env, qc_type, level)
    matrices = grid["matrices"]
    rpd = qc_type in mps.RPD_QC_TYPES
    spans = _matrix_columns(mps, profile, grids.values(), qc_type)
    columns = [Column("m-{0}".format(j), label, "text" if rpd else "pair", align="center", unit="%",
                      sub=", ".join(ms) if len(ms) > 1 else None, matrices=list(ms))
               for j, (label, ms) in enumerate(spans)]
    # each column's cells are its first matrix's: the others are alike
    firsts = [(j, matrices.index(ms[0]), label, ms) for j, (label, ms) in enumerate(spans)]
    inclusion = profile.get("analyte_matrix_inclusion") or {}
    titles = mps._analyte_titles(profile)
    flags = mps.engine_flags(profile)
    tiers = mps._tiers(profile, qc_type)
    coll = mps.SECTIONS.get(dict(TIER_SECTIONS)[qc_type])
    coll_id = coll.id if coll is not None and coll.id in qc_section_ids(profile) else ""
    at = (posted or {}).get(coll_id) or {}
    runs = _runs(profile, qc_type)
    qc_label = dict(QC_TYPES)[qc_type]
    unit = "" if rpd else " %"
    group_words = dict(mps.GROUP_CHOICES)
    scope_words = dict(mps.SCOPE_CHOICES)

    def included(kw, m):
        return _reported(inclusion, kw, m)

    def prefix(index):
        """The name prefix of the page's row that holds tiers[index]."""
        if not coll_id or index is None:
            return ""
        row = at.get(_text(tiers[index].get("name")).strip(), index)
        return "__".join(["c", cf._enc(coll_id), _text(row)]) + "__"

    covers = _tier_covers(mps, profile, env, qc_type)

    def covered(index, among=None):
        return "; ".join("{0} in {1}".format(title, ", ".join(sorted(ms, key=matrices.index)))
                         for title, ms in (covers if among is None else among).get(index, {}).items())

    proposals = {}

    def proposal(at, group, scope, listed):
        """What inserting a (group, scope) tier at `at` (listing `listed`)
        would set, and which tiers would then set no cell."""
        key = (at, group, scope, tuple(listed))
        if key not in proposals:
            q = _with_tier(profile, qc_type, at, group, scope, listed)
            after = _tier_covers(mps, q, env, qc_type)
            lost = [_text(t.get("name")) for i, t in enumerate(tiers)
                    if covers.get(i) and not after.get(i if i < at else i + 1)]
            proposals[key] = (covered(at, after), lost)
        return proposals[key]

    def value(window):
        if rpd:
            return mps.window_text(window, qc_type)
        return window if window is not None else (None, None)

    def ends(window):
        """(lo, hi) of a window as the drawer's numbers: an RPD limit is a
        maximum alone, an end not set is empty."""
        if window is None:
            return "", ""
        lo, hi = (None, window) if rpd else window
        return tuple("" if x is None else "{0:g}".format(float(x)) for x in (lo, hi))

    method_ends = ends(mps.tier_window(mps._method_default_tier(profile, qc_type), qc_type))

    def cell(c, kw, m, column, ms):
        label = " \u00b7 ".join([titles.get(kw, kw), column, qc_label])
        winner = tiers[c["index"]] if c["index"] is not None else None
        new = _new_tier(mps, profile, winner, flags.get(kw, (False, False)), m, level) if coll_id else None
        # a new tier for listed matrices lists the column's: every matrix it shows
        listed = list(ms) if new and new[1] != "all" else []
        data = {"title": label, "qc": qc_type, "coll": coll_id, "prefix": prefix(c["index"]),
                "new-group": new[0] if new else "", "new-scope": new[1] if new else "",
                "new-matrices": json.dumps(listed) if listed else "",
                "before": prefix(c["index"]) if new else "", "new-covers": "", "new-shadows": ""}
        # the numbers the drawer draws: the effective window, the tier a reset
        # on the cell reverts to (what applies with its tier removed) and the
        # method's default tier
        own, under = ends(c["window"]), ends(c["fallback_window"] if c.get("fallback_tier") else None)
        data.update({"lo": own[0], "hi": own[1], "set-kind": c.get("set_by") or "",
                     "fallback-is-default": "1" if c.get("fallback_default") else "",
                     "tier-name": _text(c.get("fallback_tier") or ""), "tier-lo": under[0], "tier-hi": under[1],
                     "method-lo": method_ends[0], "method-hi": method_ends[1]})
        if new:
            sets, lost = proposal(len(tiers) if c["index"] is None else c["index"], new[0], new[1], listed)
            data["new-covers"] = sets
            data["new-shadows"] = "; ".join("{0} would no longer set any cell".format(n) for n in lost)
        if winner is None:
            data.update({"window": "No window", "set-by": "No tier", "fallback": "No window", "default": "",
                         "tier": "", "tier-group": "", "tier-scope": "", "covers": ""})
            return Cell(value(None), state="off",
                        title="No window" if runs else "{0} is not run".format(qc_label), data=data)
        if c["window"] is None:          # a tier that sets no window still sets the cell
            data.update({"window": "No window", "set-by": "{0}, no window".format(c["source"]),
                         "fallback": "No window" if c["fallback_window"] is None else "{0} {1}".format(
                             c["fallback"], mps.window_text(c["fallback_window"], qc_type)),
                         "default": "1" if c["default"] else "", "tier": _text(winner.get("name")),
                         "tier-group": group_words.get(winner.get("analyte_group") or "all", ""),
                         "tier-scope": scope_words.get(winner.get("matrix_scope") or "all", ""),
                         "covers": covered(c["index"])})
            return Cell(value(None), state="off", title="No window", data=data)
        data.update({
            "window": mps.window_text(c["window"], qc_type) + unit, "set-by": c["source"],
            "fallback": "No window" if c["fallback_window"] is None else "{0} {1}".format(
                c["fallback"], mps.window_text(c["fallback_window"], qc_type)),
            "default": "1" if c["default"] else "", "tier": _text(winner.get("name")),
            "tier-group": group_words.get(winner.get("analyte_group") or "all", ""),
            "tier-scope": scope_words.get(winner.get("matrix_scope") or "all", ""),
            "covers": covered(c["index"])})
        if c.get("set_by") == "cell":
            return Cell(value(c["window"]), state="set", source=c["source"], data=data,
                        title="Set on this cell by {0}".format(c["source"]))
        return Cell(value(c["window"]), state="inherited", source=c["source"], data=data)

    def words(window):
        return mps.window_text(window, qc_type) if window is not None else NO_WINDOW_WORDS

    groups, rows = [], []
    for g in grid["rows"]:
        gcells = {}
        for j, i, _label, _ms in firsts:
            c = g["cells"][i]
            gcells["m-{0}".format(j)] = Cell(value(c["window"]), state="readonly" if c["window"] is not None
                                              else "off", title=c["source"])
        held, flagged = [], False
        for kw in g["keys"]:
            cells, off, said = {}, False, []
            for j, i, label, ms in firsts:
                m = matrices[i]
                if not included(kw, m):
                    # not reported in this column's matrices: said so, never blank
                    cells["m-{0}".format(j)] = Cell(None, state="na", title="{0} is not reported in {1}".format(
                        titles.get(kw, kw), ", ".join(ms)))
                    said.append(None)
                    continue
                c = g["analytes"][kw][i]
                cells["m-{0}".format(j)] = cell(c, kw, m, label, ms)
                off = off or c["window"] is None
                said.append(words(c["window"]))
            held.append((titles.get(kw, kw), said))
            flagged = flagged or (off and runs)
            rows.append(Row(kw, titles.get(kw, kw), cells, group=g["key"],
                            flags=("no_window",) if off and runs else ()))
        summary = group_summary(held, spans, [words(g["cells"][i]["window"]) for _j, i, _l, _m in firsts]) \
            if held else None
        # a member flagged NO WINDOW flags its group row too: folding never hides it
        groups.append(Row(g["key"], g["title"], gcells, selectable=False,
                          sub=_tier_words(mps, g["cells"], qc_type), summary=summary,
                          flags=("no_window",) if flagged else ()))
    # every group folds to its row; the page remembers the open ones per
    # QC type shown
    return Sheet("windows", columns, rows, groups=groups, selection=False, picker=False, form=QC_FORM,
                 fold=qc_type)


def preview_windows(stored, form, env=None):
    """The window grid for a QC criteria form AS EDITED, not saved: the
    groups and the tier collections parsed and applied as a save does, then
    drawn for the QC type and spike level the form asks for, each cell
    naming the row the page posted its tier in.
    (html, errors); nothing is written."""
    cf, mps, _pf, _iso, _ls = _tab_modules()
    ids = qc_section_ids(stored)
    profile = stored
    for sid in ["groups"] + [t for _q, t in TIER_SECTIONS if t in ids]:
        updates, errors = cf.parse(mps.SECTIONS[sid], form, stored, env)
        if errors:
            return "", errors
        profile = cf.apply(mps.SECTIONS[sid], profile, updates, env)
    qc_type = (form or {}).get("qc_type") or "LFSM"
    level = (form or {}).get("level") or "ordinary"
    rules, _qct = _qc_modules()
    state = (form or {}).get(LOW_LEVEL_STATE) or rules.rule_state(stored, None, rules.LOW_LEVEL_ROW)
    if level == "low" and qc_type not in mps.RPD_QC_TYPES and state == "off":
        level = "ordinary"          # the rule has the low-level recovery checks Off: never drawn as judged
    sheet = windows_sheet(profile, env, qc_type, level, posted=posted_tier_rows(form))
    return render_sheet(None, sheet), []


def _segment(attrs, items, value, disabled=(), item_attrs=None, item_tail=None):
    """A segment of `items` [(value, label)]; `item_attrs(value)` gives an
    item's own attributes, `item_tail(value)` markup after its words."""
    return _tag("div", [("class", "pfas-seg pfas-seg-sm is-fit"), ("role", "group"), ("data-quiet", True)] + attrs,
                "".join(_tag("button", [("type", "button"), ("class", "pfas-seg-item"), ("data-value", v),
                                        ("aria-pressed", "true" if v == value else "false"),
                                        ("disabled", v in disabled)] + (item_attrs(v) if item_attrs else []),
                             _esc(label) + (item_tail(v) if item_tail else ""))
                        for v, label in items))


# the one line under the grid's pickers: how each state of a cell is drawn
WINDOWS_LEGEND = ('<p class="pfas-legend">'
                  '<span class="pfas-legend-val is-set">40 \u2013 160</span> set on this cell \u00b7 '
                  '<span class="pfas-legend-val is-inherited">40 \u2013 130</span> from its tier \u00b7 '
                  '<span class="pfas-legend-val is-off">\u2014</span> no window \u00b7 '
                  + LOCK_MARK + ' fixed by a rule \u00b7 '
                  '<span class="pfas-legend-val is-folded">' + CHEVRON + '</span> folded group \u00b7 '
                  'open to see each analyte</p>')


def windows_controls(profile, env=None, qc_type="LFSM", level="ordinary"):
    """What sits above the window grid: the Show segment (the QC type whose
    windows the grid shows, shown_qc_type) and the spike-level segment. A
    QC type is offered while its rule row is Enforced or Evaluate
    (data-enable-if on the row's posted state, drawn off while it is Off).
    The Low level choice is off while no QC type the method runs has a
    low-level tier. The Low-level recoveries rule covers the recovery
    checks only: under Show LFB or LFSM the choice follows the rule's row
    the same way, and while the row is what keeps it off it carries the
    lock mark and the reason on hover (data-lock-reason: the page puts both
    back and takes them away as the row changes); under LFSMD RPD and SD
    RPD it is free, since the RPD checks judge their low-level tiers
    whatever the rule holds. Show switches on the page without a redraw,
    so it writes its value into a field of its own that posts nothing
    (qc-show), and the Low level choice is enabled too while that field
    names an RPD view (data-enable-also-if). The legend line follows the
    pickers."""
    _cf, mps, _pf, _iso, _ls = _tab_modules()
    rules, _qct = _qc_modules()
    profile = profile or {}
    qc_type = shown_qc_type(profile, qc_type)
    has_low = any(t.get(mps.LOW_LEVEL_KEY) for q, _l in QC_TYPES if _runs(profile, q) for t in mps._tiers(profile, q))
    low_on = has_low and (rules.rule_state(profile, None, rules.LOW_LEVEL_ROW) != "off"
                          or qc_type in mps.RPD_QC_TYPES)
    level = level if level in dict(QC_LEVELS) and (low_on or level == "ordinary") else "ordinary"
    off = [q for q, _l in QC_TYPES if qc_row_state(profile, q) == "off"]

    def follows_row(q):
        return [("data-enable-if", "rulestate." + rules.QC_TYPE_KEY(q)), ("data-enable-values", "enforced evaluate")]

    # the rule, not a missing tier, is what keeps Low level off
    locked = has_low and not low_on
    reason = "Fixed by the rule {0}: Off".format(LOW_LEVEL_RULE[1])

    def follows_low_level(v):
        # only where a low-level tier exists: the row never unlocks a level
        # the method has no window for
        return [("data-enable-if", LOW_LEVEL_STATE), ("data-enable-values", "enforced evaluate"),
                ("data-enable-also-if", SHOW_FIELD), ("data-enable-also-values", " ".join(mps.RPD_QC_TYPES)),
                ("data-lock-reason", reason), ("title", reason if locked else None)] \
            if v == "low" and has_low else []

    def lock(v):
        return LOCK_MARK if v == "low" and locked else ""
    shown = _tag("input", [("type", "hidden"), ("id", SHOW_FIELD), ("name", SHOW_FIELD),
                           ("form", "pfas-no-form"), ("value", qc_type)])
    segs = _segment([("data-qc-seg", True), ("aria-label", "QC type"), ("data-field", True),
                     ("data-input", SHOW_FIELD)], QC_TYPES, qc_type, disabled=off, item_attrs=follows_row)
    segs += _segment([("data-level-seg", True), ("aria-label", "Spike level")], QC_LEVELS, level,
                     disabled=() if low_on else ("low",), item_attrs=follows_low_level, item_tail=lock)
    return _tag("div", [("class", "pfas-pill-row")], shown + segs) + WINDOWS_LEGEND


def posted_names(sheet):
    """Every input name the sheet posts: the cells' own names, a switch's
    present marker, a state's rulestate.<row> when it names nothing, and the
    stored value of a locked or read-only cell with a name, and the sheet's
    hidden fields."""
    names = set(c.name for c in sheet.hidden)
    for row in sheet.rows + sheet.groups:
        for col in sheet.columns:
            cell = row.cells.get(col.key)
            if cell is None:
                continue
            if not _editable(col, cell):
                names.update(_kept_names(col, cell))
                continue
            if col.kind == "pair":
                names.update(cell.name)
                if cell.none:
                    names.add(cell.none[0])
            elif col.kind == "state":
                names.add(_state_name(row, cell))
            elif col.kind in ("switch", "flag"):
                names.update((cell.name, _present_name(cell.name)))
                names.update(n for n, _v in (cell.data or {}).get("kept") or ())
            else:
                names.add(cell.name)
    return names


# ── a section's summary line ────────────────────────────────────────────────

MIDDOT = " \u00b7 "
# the editor's sections drawn from more than one declared section
SUMMARY_PARTS = {"sur": ("engine_sur", "cal_sur"), "names": ("engine_names",)}
# Engine's Method & names also draws the profile's Display name and Description
NAME_FIELDS = 2


def _counts(cf, mps, profile, env, sid):
    """[(n, noun)]: what one declared section draws, a collection's rows by
    its own noun, a table's rows, a section's fields (a min / max pair once)."""
    sec = mps.SECTIONS[sid]
    drawn = cf.render(sec, profile, env)
    if isinstance(sec, cf.Collection):
        return [(len([r for r in drawn if not r["template"]]), sec.noun)]
    if isinstance(sec, cf.Table):
        return [(sum(len(g["rows"]) for g in drawn), "row")]
    return [(sum(len(g["shown"]) for g in drawn), "setting")]


def _joined(parts):
    totals = OrderedDict()
    for n, noun in parts:
        totals[noun] = totals.get(noun, 0) + n
    return MIDDOT.join(counted(n, noun) for noun, n in totals.items())


def window_columns(profile, env=None, qc_type="LFSM"):
    """The window grid's matrix columns as [[matrix]], the shared column
    first (_matrix_columns, which the grid draws)."""
    _cf, mps, _pf, _iso, _ls = _tab_modules()
    profile = profile or {}
    qc_type = shown_qc_type(profile, qc_type)
    grids = _column_grids(mps, profile, env, qc_type)
    return [ms for _label, ms in _matrix_columns(mps, profile, grids.values(), qc_type)]


def _windows_summary(mps, profile, env):
    types = [label for q, label in QC_TYPES if qc_row_state(profile, q) != "off"]
    if not types:
        return "No QC type judged"
    qc_type = shown_qc_type(profile)
    n = len(profile.get("supported_matrices") or [])
    cols = window_columns(profile, env, qc_type)
    if len(cols) > 1:
        tail = counted(len(cols), "matrix column")
    else:
        tail = counted(n, "matrix") if n < 2 else "all {0} matrices share one window".format(n)
    return MIDDOT.join([", ".join(types), counted(len(mps._tiers(profile, qc_type)), "tier"), tail])


def section_summary(profile, env, sid):
    """The one phrase a section's summary line states (unicode): the rules
    and their states, the windows the grid shows, the batch limit, where
    results come from, the certificate rows and limits; any other section
    its count of rows or settings. A section the site's own records draw
    (the run template, the retired notes) is the view's."""
    cf, mps, _pf, _iso, _ls = _tab_modules()
    rules, _qct = _qc_modules()
    profile = profile or {}
    env = env or {}
    if sid == "rules":
        states = [r.cells["state"].value for r in rules_table(profile, env).rows]
        return MIDDOT.join([counted(len(states), "rule")] +
                           ["{0} {1}".format(states.count(st), st) for st in rules.STATES])
    if sid == "windows":
        return _windows_summary(mps, profile, env)
    if sid == "xbatch":
        most = cf.current(mps.SECTIONS["xbatch"], profile).get("f__max_size")
        return "No limit" if most in (None, "") else "{0} per batch".format(_g(most))
    if sid == "intg":
        modes = dict(mps.INTEGRATION_MODES)
        mode = (profile.get("integration") or {}).get("mode")
        mode = mode if mode in modes else "vendor"
        tail = ("change log" if mode == "vendor"
                else "method defaults, per-compound overrides and the change log")
        return "Results come from {0}{1}{2}".format(modes[mode], MIDDOT, tail)
    if sid == "rf":
        n = sum(len(g["rows"]) for g in cf.render(mps.SECTIONS["rf"], profile, env))
        return counted(n, "matrix row") + "; a blank cell inherits All matrices"
    if sid == "al":
        rows = [r for g in cf.render(mps.SECTIONS["al"], profile, env) for r in g["rows"]]
        n = len([r for r in rows if r["cells"][0]["value"] != "off"])
        return counted(n, "limit") + " on this method\u2019s certificates"
    if sid == "stages":
        return counted(len(profile.get("extraction_stages") or []), "stage")
    parts = [(NAME_FIELDS, "setting")] if sid == "names" else []
    for part in SUMMARY_PARTS.get(sid, (sid,)):
        parts += _counts(cf, mps, profile, env, part)
    return _joined(parts)
