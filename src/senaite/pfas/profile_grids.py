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

import copy
import json
import re
from collections import OrderedDict

from senaite.pfas.qc.rules import STATES as RULE_STATES
from senaite.pfas import help_dictionary
from senaite.pfas import icons
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
    it posts; the row's drawer edits it with the segmented control.
    `narrow` draws a column as narrow as its values allow (many matrices
    side by side), its heading `label` short and `title` the full name,
    which the heading's hover and every cell's label carry. `scale` (lo,
    hi) is a pair's slider axis, drawn as data-scale on its cells and its
    drawer range (else the components' 0 to 100)."""

    def __init__(self, key, label, kind, align="left", group=None, default=True, unit=None,
                 min=None, max=None, step=None, sub=None, matrices=None, word=False,
                 title=None, narrow=False, scale=None):
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
        self.title = title
        self.narrow = narrow
        self.scale = scale

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
    the not-assessed cross. `groups` heads a select's options:
    [(heading, [values])], each heading over its values, in that order
    (the options keep their own order within it). `saves_as` is the text
    a number cell's stored value is saved as when Save changes it (a
    reported value rounded as it prints), drawn beside the box and counted
    as an unsaved change.
    A pair can cover more than its own column: `span` lists the columns it
    covers, its own first (the row draws nothing else under them, its upper
    end taking their width); `key` is its tds' data-col in place of the
    column's, so what acts on a column (Edit selected, the bulk bar, paste)
    never reaches it; `label` names it in place of the column's heading.
    Its data may grey it while a rule is Off: "mute-if" (the state's input
    name), "mute-values", "mute-blank", and "muted" as drawn."""

    def __init__(self, value, state="set", source=None, name=None, options=None, links=None, title=None,
                 expands=None, data=None, flags=(), none=None, groups=None, saves_as=None, span=None,
                 key=None, label=None, html=None, box=None):
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
        self.groups = list(groups or ())
        self.saves_as = saves_as
        self.span = tuple(span) if span else None
        self.key = key
        self.label = label
        # a read-only cell's markup, built by its owner (a limit box's words
        # and placard, limit_placard), drawn in place of its escaped words
        self.html = html
        # the limit box a pair's cell is judged in: (its attributes, its
        # placard) from limit_placard.box_parts; the lower end's cell is the
        # box, its mark over the cell's top-right corner
        self.box = box


class Row(object):
    """One analyte, standard, rule or matrix. `cells` is a list in column
    order or a dict keyed by column key; the Sheet keys it by column. A flag
    is words: a coral chip that marks the row, or a (words, "warn") pair, an
    amber chip that leaves the row unmarked. `data` are data-* attributes
    on the row, for a page's own script (a list is written as JSON). A
    group row of a folding sheet says what its members hold in `summary`.
    A `hidden` row is drawn hidden and still posts (a QC type the method may
    add, shown when it is added). `drawer` is markup its window draws after
    its fields (a button the page's own script runs). `tail` is markup its
    owner builds, drawn under the label after its flags (a rule's Applies to
    row, sample_type_icons.row)."""

    def __init__(self, key, label, cells, sub=None, group=None, selectable=True, flags=(), data=None,
                 summary=None, hidden=False, drawer=None, tail=None):
        self.key = key
        self.tail = tail
        self.drawer = drawer
        self.hidden = hidden
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
                 remover=None, fold=None, help=None, note=None):
        if layout not in LAYOUTS:
            raise ValueError("unknown layout: {0}".format(layout))
        # one line above the grid: what the next Save changes unasked
        self.note = note
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
        # (tab, [(method id, name)]): "Copy from method" offers the other
        # methods' values for this grid (copy_values), set by the page
        self.copy_from = None
        # "Fill RLs from calibration": the grid's RL cells carry their
        # default (data-derived), listed as changes to tick before any is written
        self.fill_rl = False
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
            # a rule's state the sheet draws no column for (each limit box
            # carries its own: limit_placard) is kept on the row, read by
            # the list beside it, and posts nothing
            keys = [c.key for c in self.columns]
            kept = dict((k, row.cells.pop(k)) for k in KEPT_CELLS
                        if isinstance(row.cells, dict) and k not in keys and k in row.cells)
            row.cells = _keyed(self.columns, row.cells, row.key)
            row.cells.update((k, v) for k, v in kept.items() if v is not None)
        self.actions = [tuple(a) for a in actions or ()]
        for a in self.actions:
            if a[0] in COLUMN_ACTIONS:
                if len(a) != 3 or kinds.get(a[2]) != "select":
                    raise ValueError("{0} names a select column: {1}".format(a[0], a[2:]))
            elif a[0] not in MATRIX_ACTIONS or len(a) != 2:
                raise ValueError("unknown action: {0}".format(a[0]))
            elif layout != "matrix":
                raise ValueError("{0} needs the matrix layout".format(a[0]))


KEPT_STATE = "state"
# cells a sheet draws no column for, kept on the row for the list beside it:
# a rule's state, and the region its row opens (the row is the button)
KEPT_CELLS = (KEPT_STATE, "edit")


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
    # a switch that may follow another posts its own hidden value
    return bool(cell.name) or (col.kind == "switch" and "tri" in (cell.data or {}))


def _shared(cell):
    """Whether the cell shows a value every row of its column shares (data
    {"shared": True}): each row draws it, one hidden field of the sheet
    posts it."""
    return bool((cell.data or {}).get("shared"))


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
        if isinstance(cell.value, (_TEXT, str)) and cell.value:
            return cell.value                  # words in place of a window ("off")
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


def _number_input(col, value, placeholder, name, label, table, form=None, disabled=False, shared=None,
                  saves_as=None):
    """`shared` names the one posted field a value every row shows is
    written to: the input itself then posts nothing. `saves_as`: what Save
    stores for the drawn value (the editor counts it unsaved)."""
    step = "any" if col.step is None else _text(col.step)
    return _tag("input", [("type", "number"), ("class", "rl-in pfas-sheet-in" if table else "pfas-sheet-in"),
                          ("name", name), ("form", form), ("step", step), ("min", _limit(col.min)),
                          ("max", _limit(col.max)), ("value", value), ("placeholder", placeholder),
                          ("disabled", disabled), ("aria-label", label), ("data-kind", _kind(name, "cell")),
                          ("data-shared", shared), ("data-saves-as", saves_as)])


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

    def option(v, l):
        shown = blank if inherited and _text(v) == "" else l
        return _tag("option", [("value", v), ("selected", _text(v) == value)], _esc(shown))
    headed = dict((_text(v), head) for head, vs in cell.groups for v in vs)
    opts += [option(v, l) for v, l in cell.options or () if _text(v) not in headed]
    for head, _vs in cell.groups:
        under = [option(v, l) for v, l in cell.options or () if headed.get(_text(v)) == head]
        if under:
            opts.append(_tag("optgroup", [("label", head)], "".join(under)))
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


def _tri_switch(cell, form, label):
    """A switch that may follow another (a matrix's same-day on ice): it
    shows what applies and posts nothing itself; its hidden input, named
    by data tri, holds the cell's own value ("" follows, "on", "off"), which
    the page's script writes when the switch is flipped. In a window
    (`form` None) both are nameless copies."""
    data = cell.data or {}
    box = _tag("input", [("type", "checkbox"), ("class", "pfas-sheet-in"), ("value", "on"),
                         ("aria-label", label), ("checked", bool(cell.value)), ("data-tri-box", True)])
    own = _tag("input", [("type", "hidden"), ("class", "pfas-sheet-in"), ("data-tri", True),
                         ("name", data["tri"] if form else None), ("form", form),
                         ("value", _text(data.get("tri-value")))])
    return '<label class="pfas-switch">{0}<span class="pfas-switch-track"></span></label>{1}'.format(box, own)


# an RL flag reported with no RL stored and none from the calibration
NO_RL = "no RL"


def _flag_words(on, rl, derived="", has_rl=False):
    """What a flag shows: the RL when one is set, else the RL that applies
    in its place (the lowest calibrator, `derived`); an RL flag with
    neither says so, any other flag shows ✓; ✗ left out."""
    if not on:
        return "✗"
    return _text(rl) or _text(derived) or (NO_RL if has_rl else "✓")


def _flag_cell(cell, name, label, form=None, disabled=False):
    """A panel flag: a button showing ✓, ✗ or the RL, which opens the
    cell's editor (in the drawer it flips the flag), and the box it writes,
    hidden (the posted control: an unticked box posts nothing). Never a
    switch."""
    data = cell.data or {}
    on = bool(data.get("in"))
    rl = _text(data.get("rl")) if on else ""
    # a grid flag over an RL: with none typed it shows the RL that applies,
    # muted (is-derived), never a bare ✓
    has_rl = bool(name and data.get("rl_name"))
    derived = _text(data.get("derived")) if has_rl else ""
    # the grid's flag opens a dialog, so its state is in its name; the
    # drawer's flips, so it is pressed or not
    btn = _tag("button", [("type", "button"), ("class", _cls("pfas-flag", "is-rl" if rl else None,
                                                             "is-derived" if on and has_rl and not rl else None,
                                                             None if on else "is-out")),
                          ("aria-pressed", None if name else ("true" if on else "false")),
                          ("aria-haspopup", "dialog" if name else None),
                          ("aria-label", "{0}: {1}".format(label, _flag_state(on, rl, derived, has_rl))),
                          ("data-label", label),
                          ("data-rl", _text(data.get("rl"))), ("data-rl-name", data.get("rl_name") or None),
                          ("data-rl-derived", derived or None),
                          ("data-mdl-name", (data.get("mdl_name") or None) if name else None),
                          ("disabled", disabled)], _esc(_flag_words(on, rl, derived, has_rl)))
    box = _tag("input", [("type", "checkbox"), ("class", "pfas-sheet-in"), ("hidden", True), ("name", name),
                         ("form", form), ("value", "on"), ("aria-label", label), ("checked", on),
                         ("disabled", disabled), ("data-kind", _kind(name, "flag"))])
    kept = "".join(_tag("input", [("type", "hidden"), ("name", n), ("form", form), ("value", v),
                                  ("data-placeholder", data.get("rl_placeholder") if n == data.get("rl_name") else None),
                                  ("data-kind", _kind(n, "cell"))])
                   for n, v in data.get("kept") or () if name)
    return btn + box + kept


def _flag_state(on, rl, derived="", has_rl=False):
    """A flag's state as words, for its accessible name."""
    if not on:
        return "left out"
    if rl:
        return "reported, RL {0}".format(rl)
    if derived:
        return "reported, RL {0} from the lowest calibrator".format(derived)
    return "reported, no RL" if has_rl else "reported"


def _text_input(cell, name, label, table, form=None, chips=False, disabled=False, hidden=False):
    """A text or a chips cell; an inherited one is blank with the inherited
    text as its placeholder. `hidden`: a grid's list cell, posted as the
    joined text the chips write, drawn as words beside it."""
    shown = _chips_value(cell) if chips or hidden else _text(cell.value)
    inherited = cell.state == "inherited"
    return _tag("input", [("type", "text"), ("class", "rl-in pfas-sheet-in" if table else "pfas-sheet-in"),
                          ("name", name), ("form", form), ("value", "" if inherited else shown),
                          ("placeholder", (shown or None) if inherited else None),
                          ("data-chips", "chips" if chips else None),
                          ("data-options", _chips_options(cell) if chips else None), ("disabled", disabled),
                          ("hidden", hidden), ("aria-label", label), ("data-kind", _kind(name, "cell"))])


def _chips_words(cell):
    """A list cell's words: its items joined, an inherited list muted, a
    dash for none."""
    shown = _chips_value(cell)
    if not shown:
        return '<span class="pfas-sheet-val is-empty">{0}</span>'.format(EM_DASH)
    return '<span class="{0}">{1}</span>'.format(
        "pfas-sheet-val is-inherited" if cell.state == "inherited" else "pfas-sheet-val", _esc(shown))


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


LOCK_MARK = icons.svg("lock", hidden=True)
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


# what a cell inside a box of equal neighbours carries (merge_boxes)
BOX_KEYS = ("box", "box-edge", "box-lead", "box-live")


def _box_words(cell, words, derived=False):
    """The words of a box whose cells are controls (an RL flag, a number),
    drawn once on its first cell, centred across the box over the controls,
    which keep their own words for a screen reader and their own clicks."""
    data = cell.data or {}
    if not (data.get("box-live") and data.get("box-lead")):
        return ""
    return _tag("span", [("class", _cls("pfas-sheet-val", "pfas-box-words", "is-derived" if derived else None)),
                         ("aria-hidden", "true")], _esc(_text(words)))


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
                + _data_attrs(cell), icons.svg("more", hidden=True))


# ── the table ───────────────────────────────────────────────────────────────

def _cell_tds(sheet, row, col, cell):
    """The <td>s of one cell: one, or two for a pair (min, max)."""
    # the column's own classes, on every td it draws: hidden, narrow
    hidden = _cls(None if col.default else "is-col-off", "is-narrow" if col.narrow else None)
    align = None if col.align == "left" else "is-" + col.align
    num = "is-num" if col.kind in ("num", "pair") else None
    if cell is None:
        # a pair's upper end takes no room here either: its heading ends where
        # the lower end's box does
        return ([_tag("td", [("class", _cls(num, align, hidden)), ("data-col", col.key)], "")] +
                [_tag("td", [("class", _cls(num, align, "pfas-sheet-hi", hidden)), ("data-col", col.key)], "")]
                * (col.span - 1))
    if cell.state == "na":
        # not reported here (or what the cell says it is): the words, muted,
        # never an empty box
        words = '<span class="pfas-sheet-val is-empty">{0}</span>'.format(
            _esc((cell.data or {}).get("na-words") or NOT_REPORTED))
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
    label = "{0} {1}".format(_text(row.label), _text(col.title or col.label))
    chips = "".join(_flag(f) for f in cell.flags)
    empty = _shown(col, cell) == ""
    cls = _cls(num, _state_class(col, cell, empty), align, hidden,
               "is-none" if col.kind == "num" and _none_marked(cell) else None)
    if col.kind == "flag":
        # a flag's data are its button's; a left-out cell is marked
        cls = _cls(cls, None if _on(col, cell) else "is-out")
        head = [("class", cls), ("title", _hover(cell)), ("data-col", col.key), ("data-label", col.label),
                ("data-unit", col.unit)] + [("data-" + k, (cell.data or {}).get(k)) for k in BOX_KEYS]
    else:
        head = [("class", cls), ("title", _hover(cell)), ("data-col", col.key)] + _data_attrs(cell)
    edit = _editable(col, cell)
    if col.kind == "pair":
        if not edit:
            # a cell inside a box of equal neighbours (merge_boxes): its
            # lower end draws the box's left side, its upper end the right
            box = (cell.data or {}).get("box")
            edges = (cell.data or {}).get("box-edge") or ""
            lo_head = [(k, " ".join(e for e in edges.split() if e != "r") if k == "data-box-edge" else v)
                       for k, v in head]
            hi = [("data-box", box), ("data-box-edge", " ".join(e for e in edges.split() if e != "l"))] if box else []
            return [_tag("td", lo_head, _val(_shown(col, cell), cell.state == "locked") +
                         _kept_inputs(col, cell, sheet.form)),
                    _tag("td", [("class", _cls(cls, "pfas-sheet-hi")), ("data-col", col.key)] + hi, "")]
        key = cell.key or col.key
        pid = _dom_id(sheet, "{0}-{1}".format(row.key, key))
        marked = _none_marked(cell)
        shared = _shared(cell)
        data = cell.data or {}
        label = "{0} {1}".format(_text(row.label), _text(cell.label or col.title or col.label))
        span = _span_of(sheet, cell)
        width = sum(c.span for c in sheet.columns if span and c.key in span and c.default)
        if span:
            # wider than its column, never drawn narrow; as wide as the
            # columns it covers that are shown, gone with the last of them
            cls = _cls(*[c for c in (cls or "").split() if c not in ("is-narrow", "is-col-off")] +
                       ["is-col-off" if not width else None])
        cls = _cls(cls, "is-muted" if data.get("muted") else None)
        mute = [("data-" + k, _text(v)) for k, v in sorted(data.items()) if k.startswith("mute-")]
        tds = []
        for end, v, n, word in zip(("lo", "hi"), _pair(cell.value), cell.name, ("minimum", "maximum")):
            value, placeholder = _num_value(cell, v)
            attrs = [("class", _cls(cls, "pfas-sheet-hi" if end == "hi" else None, "is-none" if marked else None)),
                     ("title", _hover(cell)), ("data-col", key), ("data-pair", pid), ("data-pair-end", end),
                     ("data-unit", col.unit), ("data-label", cell.label or col.title or col.label),
                     ("data-scale", _scale_attr(col)), ("data-none", cell.none[2] if cell.none else None),
                     ("data-note", data.get("note")), ("data-set-none", data.get("set-none")),
                     ("data-none-hover", data.get("none-hover")),
                     ("data-none-text", data.get("none-text"))] + mute
            if span and end == "lo":
                attrs.append(("data-span", " ".join(span)))
            if span and end == "hi":
                attrs.append(("colspan", _text(max(1, width - 1))))
                if width < 2:
                    attrs[0] = ("class", _cls(attrs[0][1], "is-col-off"))
            if shared:
                # one value on every row: the row's copy posts nothing, and
                # the sheet's hidden field of that name is what is saved
                inner = _number_input(col, value, placeholder, None, "{0} {1}".format(label, word),
                                      True, NO_FORM, shared=n)
            else:
                inner = _number_input(col, "" if marked else value, placeholder, n,
                                      "{0} {1}".format(label, word), True, sheet.form)
            if cell.none and end == "hi":
                inner += _none_box(cell, label, sheet.form)
            if cell.box and end == "lo":
                battrs, plac = cell.box
                # no Tab stop of its own: the cell's button reaches its menu
                have = set(k for k, _v in attrs)
                attrs += [(k, v) for k, v in battrs if k not in ("class", "tabindex") and k not in have]
                inner += plac
            if span and end == "hi" and data.get("note"):
                # what the one box over many columns stands for, beside it
                inner += _tag("span", [("class", "pfas-sheet-aside pfas-sheet-span-note")], _esc(data["note"]))
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
        if cell.html:
            # markup its owner built (a limit box's words and placard) wins
            # over navigation buttons: no button stands in such a cell
            return [_tag("td", head, cell.html + kept)]
        if cell.links:
            words = _val(_text(cell.value)) + " " if cell.value not in (None, "") else ""
            return [_tag("td", head, words + _nav(cell.links) + kept)]
        return [_tag("td", head, _val(_shown(col, cell), cell.state == "locked") + kept)]
    if col.kind == "num":
        marked = _none_marked(cell)
        value, placeholder = _num_value(cell, "" if marked else cell.value)
        saves_as = None if marked or cell.state != "set" else cell.saves_as
        inner = _number_input(col, value, placeholder, cell.name, label, True, sheet.form, disabled=marked,
                              saves_as=saves_as)
        if saves_as:
            inner += '<span class="pfas-hint">{0}</span>'.format(_esc(saves_as_words(saves_as)))
        if cell.none:
            inner += _none_box(cell, label, sheet.form, NONE_WORD)
            head.append(("data-none", cell.none[2]))
        inner += _box_words(cell, value or placeholder or "", cell.state == "inherited")
        return [_tag("td", head + [("data-label", col.label)], inner)]
    form = sheet.form
    if col.kind == "select":
        inner = _select(cell, cell.name, label, True, form)
    elif col.kind == "switch" and "tri" in (cell.data or {}):
        inner = _tri_switch(cell, form, label)
    elif col.kind == "switch":
        inner = _switch(cell, cell.name, label, form) + _tag(
            "input", [("type", "hidden"), ("name", _present_name(cell.name)), ("form", form), ("value", "1")])
    elif col.kind == "flag":
        inner = _flag_cell(cell, cell.name, label, form) + _tag(
            "input", [("type", "hidden"), ("name", _present_name(cell.name)), ("form", form), ("value", "1")])
        data = cell.data or {}
        inner += _box_words(cell, _flag_words(bool(data.get("in")), data.get("rl"), data.get("derived"), True),
                            not _text(data.get("rl")))
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
    elif col.kind == "chips":
        # no button in a row: the list reads as words, its input hidden and
        # posting; the cell opens the row's drawer on it, where the chips
        # are added and removed
        head += [("role", "button"), ("tabindex", "0"), ("data-opens-row", col.key),
                 ("aria-label", "Edit {0}".format(label))]
        inner = _chips_words(cell) + _text_input(cell, cell.name, label, True, form, hidden=True)
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
                                            None if col.default else "is-col-off",
                                            "is-narrow" if col.narrow else None)),
                             ("title", col.title),
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
    if getattr(row, "tail", None):
        inner += row.tail
    return _tag("th", [("scope", scope), ("class", "pfas-sheet-label")], inner)


def _span_of(sheet, cell):
    """The columns a pair covers (Cell.span) that the sheet has, its own
    first; None for a cell in its one column."""
    if cell is None or not cell.span:
        return None
    keys = [c.key for c in sheet.columns]
    span = [k for k in cell.span if k in keys]
    return tuple(span) if len(span) > 1 else None


def _cells(sheet, row):
    """The row's tds, column by column; a column a spanning pair covers is
    drawn by that pair alone."""
    out, covered = [], set()
    for col in sheet.columns:
        if col.key in covered:
            continue
        cell = row.cells.get(col.key)
        span = _span_of(sheet, cell)
        if span:
            covered.update(span[1:])
        out.append("".join(_cell_tds(sheet, row, col, cell)))
    return "".join(out)


def _member_id(sheet, row):
    """A folding group's member row id: every member of a group shares the
    prefix sheet-<sheet>-g-<group>-."""
    return _dom_id(sheet, "g-{0}-{1}".format(row.group, row.key))


def _tr(sheet, row, folded=False):
    """A row."""
    sel = ""
    if sheet.selection:
        box = _tag("input", [("type", "checkbox"), ("class", "pfas-sheet-check"), ("form", "pfas-no-form"),
                             ("aria-label", "Select {0}".format(_text(row.label)))]) if row.selectable else ""
        sel = _tag("td", [("class", "pfas-sheet-sel")], box)
    # a folded group's member: hidden until the group opens (it still posts)
    fold = [("id", _member_id(sheet, row)), ("data-in-group", row.group), ("hidden", True)] if folded else []
    hide = [("hidden", True)] if getattr(row, "hidden", False) and not fold else []
    # a row that opens a region names it, open or not
    region = (row.data or {}).get("row-region")
    aria = [("aria-controls", region), ("aria-expanded", "false")] if region else []
    return _tag("tr", [("data-row", row.key), ("data-label", row.label),
                       ("class", _cls("is-flagged" if _marked(row) else None))] +
                fold + hide + _data_attrs(row) + aria,
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
    label = _text(cell.label or col.label)
    if off and col.kind == "state" and cell.state == "locked":
        control = '<div class="pfas-sheet-ro"><span class="pfas-fixed">{0}{1}</span></div>'.format(
            LOCK_SVG, _esc(FIXED_WORDS))
    elif off and (col.kind == "links" or not _kept_names(col, cell)):
        # its words and the words its flags say ("no limit set"), as the cell
        # reads; a dash only when there is neither
        words = cell.html or (_esc(_shown(col, cell, unit=True)) + "".join(_flag(f) for f in cell.flags))
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
        # a range that follows another shows that one's ends in its blank boxes
        follows = bool((cell.data or {}).get("follows"))
        for v, word in zip(_pair(cell.value), ("minimum", "maximum")):
            value, _p = _num_value(cell, "" if _none_marked(cell) else v)
            ends.append(_number_input(col, value, _p if follows else None, None, "{0} {1}".format(label, word),
                                      False, disabled=off))
        control = _tag("div", [("data-range", True), ("data-unit", col.unit), ("data-scale", _scale_attr(col))],
                       "".join(ends))
        if cell.none:
            box = _tag("input", [("type", "checkbox"), ("class", "pfas-sheet-in"), ("value", "on"),
                                 ("checked", bool(cell.none[1])), ("disabled", off)])
            words = (cell.data or {}).get("none-text") or "None: recovery is not assessed for {0}".format(cell.none[2])
            control += '<label class="pfas-cell-none">{0}<span>{1}</span></label>'.format(box, _esc(words))
    elif col.kind == "select":
        control = _select(cell, None, label, False, disabled=off)
    elif col.kind == "switch" and "tri" in (cell.data or {}):
        control = _tri_switch(cell, None, label)
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
    note = (cell.data or {}).get("note")
    if note:
        help_text = MIDDOT.join(t for t in (help_text, note) if t)
    help_html = '<div class="pfas-sheet-help">{0}</div>'.format(_esc(help_text)) if help_text else ""
    flabel = '<div class="pfas-sheet-flabel">{0}</div>'.format(
        _esc(cell.label) if cell.label else _heading(col, unit=col.kind != "pair"))
    return _tag("div", [("class", _cls("pfas-sheet-field", None if edit else "is-ro")),
                        ("data-col", cell.key or col.key)],
                flabel + control + help_html)


def _scale_attr(col):
    """A pair's data-scale ("lo,hi"), or None where it declares none."""
    return "{0},{1}".format(_g(col.scale[0]), _g(col.scale[1])) if col.scale else None


# a matrix section's fields in a row's window (the matrix layout), named
# for what they are: the section's heading names the matrix
MATRIX_FIELD_WORDS = {"in": "Reported", "rl": "RL", "mdl": "MDL"}


def _relabelled(cell, words):
    c = copy.copy(cell)
    c.label = words
    return c


def _matrix_template_fields(sheet, row, cols):
    """A row's window in the matrix layout: the row's own fields first (what
    holds for the analyte in every matrix: Quantified by, isomers, salt),
    then one section per matrix, headed by the matrix and its unit: its
    flag (Reported), then the RL and MDL inputs the flag names. Every field
    keeps its column (data-col), so Done writes what it wrote; the sheet's
    columns keep their order."""
    owned = _matrix_owned(sheet)
    shown = dict((c.key, c) for c in cols)
    inside = set(owned)
    for found in owned.values():
        inside.update(c.key for c in found.values())
    out = [_field(c, row.cells[c.key]) for c in cols if c.key not in inside]
    for flag_key, found in owned.items():
        flag = shown.get(flag_key)
        if flag is None:
            continue
        parts = [_field(flag, _relabelled(row.cells[flag_key], MATRIX_FIELD_WORDS["in"]))]
        for field in ("rl", "mdl"):
            col = found.get(field)
            if col is not None and col.key in shown:
                parts.append(_field(col, _relabelled(row.cells[col.key], MATRIX_FIELD_WORDS[field])))
        head = MIDDOT.join(w for w in (flag.label, flag.unit) if w)
        out.append(_tag("fieldset", [("class", "pfas-sheet-fsec"), ("data-matrix-of", flag_key)],
                        _tag("legend", [("class", "pfas-sheet-fsec-h")], _esc(head)) +
                        _tag("div", [("class", "pfas-sheet-fsec-b")], "".join(parts))))
    return "".join(out)


def _template(sheet, row, group=False):
    """A row's drawer; a group row's (data-group, its label) where the
    heading row holds values of its own that post (what every row shares).
    In the matrix layout a row's window is grouped by matrix
    (_matrix_template_fields)."""
    cols = [col for col in sheet.columns
            if col.key in row.cells and col.kind != "menu" and row.cells[col.key].state != "na"]
    if sheet.layout == "matrix" and not group:
        fields = _matrix_template_fields(sheet, row, cols)
    else:
        fields = "".join(_field(col, row.cells[col.key]) for col in cols)
    key = [("data-group", row.key), ("data-label", row.label)] if group else [("data-row", row.key)]
    return _tag("template", [("class", "pfas-sheet-row-tpl")] + key,
                '<div class="pfas-sheet-form">{0}{1}</div>'.format(fields, row.drawer or ""))


def _posts(sheet, row):
    return any(_editable(col, row.cells[col.key]) for col in sheet.columns if col.key in row.cells)


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
                           ("aria-label", "Set {0} to none".format(label))], icons.svg("close", hidden=True))


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
                         '{0} {1}'.format(_esc(c.label), icons.svg("close", hidden=True)))
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


COPY_WORDS = "Copy from method"


def _copier(sheet):
    """"Copy from method": the other methods this grid's values can be
    taken from (method_profile_edit.js asks the page for one's values,
    shows them against this method's and writes the ones chosen into the
    grid; the tab's own Save stores them)."""
    tab, methods = sheet.copy_from
    return _tag("button", [("type", "button"), ("class", "btn-sm btn-secondary"), ("data-copy-from", tab),
                           ("data-methods", json.dumps([[_text(m), _text(t)] for m, t in methods]))],
                _esc(COPY_WORDS))


FILL_RL_WORDS = "Fill RLs from calibration"


def _filler(sheet):
    """"Fill RLs from calibration": method_profile_edit.js lists each RL
    cell's default (its data-derived: the lowest calibrator in the matrix's
    unit times the matrix factor and the salt factor) against what the cell
    holds, a typed RL unticked, and writes the ticked ones into the grid;
    the tab's own Save stores them."""
    return _tag("button", [("type", "button"), ("class", "btn-sm btn-secondary"), ("data-fill-rl", sheet.id)],
                _esc(FILL_RL_WORDS))


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
    if sheet.copy_from and sheet.copy_from[1]:
        parts.append(_copier(sheet))
    if sheet.fill_rl:
        parts.append(_filler(sheet))
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
    if sheet.note:
        out.append('<p class="pfas-hint is-flush pfas-sheet-note" role="note">{0}</p>'.format(_esc(sheet.note)))
    out.append(_tools(sheet))
    out.append('<div class="pfas-sheet-wrap"><table class="pfas-sheet" data-sheet="{0}">'.format(_esc(sheet.id)))
    out.append(_thead(sheet))
    out.append(_tbodies(sheet))
    out.append("</table></div>")
    out.extend(_tag("input", [("type", "hidden"), ("name", c.name), ("form", sheet.form),
                              ("value", _text(c.value)), ("id", _dom_id(sheet, c.name))] +
                    [("data-" + k, v) for k, v in sorted((c.data or {}).items())]) for c in sheet.hidden)
    out.extend(_template(sheet, r) for r in sheet.rows)
    out.extend(_template(sheet, g, group=True) for g in sheet.groups if _posts(sheet, g))
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
    hint = None if low is None else mps.derived_rl_hint(low, profile, matrix)
    # reported in the editor with no RL typed, it shows the lowest calibrator's
    return Cell("✗", name=name, data={"in": False, "rl": "", "rl_name": kept[0][0], "mdl_name": kept[1][0],
                                      "kept": kept, "rl_placeholder": hint, "derived": hint or ""})


def _salt_calc(kw, label, isomer, lot_name, env):
    """What the Salt factor cell's calculator (method_profile_edit.js) is
    given: the analyte, its isomer peaks when it is a sum, the name of the
    row's CoA lot input, and the molar masses each standard lot's
    certificate states for it ([lot uid, lot, acid, salt]); nothing is
    looked up from a table of molar masses."""
    peaks = ([isomer["linear"]] if isomer and isomer.get("linear") else []) + \
        list((isomer or {}).get("branched") or [])
    mw = [[lot.get("uid"), lot.get("label") or "", m[0], m[1]]
          for lot in (env or {}).get("standard_lots") or []
          for m in [((lot.get("mw") or {}).get(kw))] if m]
    return {"calc": "salt", "analyte": label, "isomers": peaks, "lot-name": lot_name, "mw": mw}


def chemical_name(name, summed=True):
    """The chemical name a row shows under its analyte: the library's full
    name without a trailing bracketed remark ("(F-53B major)"); the stored
    name is not changed. "(linear)" stays on an analyte the method does not
    sum, the linear peak the name stands for; a summed analyte's Isomer sum
    column says what is reported."""
    name = (name or u"").strip()
    if not summed and name.endswith(u"(linear)"):
        return name
    if name.endswith(u")") and u" (" in name:
        depth = 0
        for i in range(len(name) - 1, -1, -1):
            depth += {u")": 1, u"(": -1}.get(name[i], 0)
            if depth == 0:
                if i > 0 and name[i - 1] == u" ":
                    return name[:i].rstrip()
                break
    return name


def _natural(label):
    """A label's sort key: case-blind, its numbers in their natural order
    (4:2 FTS before 10:2 FTS)."""
    return [(0, int(p), u"") if p.isdigit() else (1, 0, p)
            for p in re.split(r"(\d+)", _text(label).lower()) if p]


def analyte_order(keys, titles=None, by=None):
    """`keys` in the order the editor draws analytes: alphabetical by label
    (`titles` maps a key to its label), case-blind, numbers natural. `by`
    maps a key to a first sort term (Quantified by order: the standard's
    label, an analyte with none last). A drawing order only: the stored
    analyte set keeps its own order."""
    titles = titles or {}

    def key(k):
        label = _natural(titles.get(k, k))
        if by is None:
            return (label,)
        first = _text(by.get(k))
        return (0 if first else 1, _natural(first), label)
    return sorted(keys, key=key)


def merge_boxes(keys):
    """The boxes a grid of cells draws: `keys` is a list of rows, each a
    list of cell keys in column order (None never merges). In each row,
    neighbouring cells with the same key are one run; a run then joins the
    run under it when both cover the same columns with the same key.
    Returns {(row, col): (top row, first col, last row, last col)}, the box
    each merged cell belongs to; a cell alone in its box is not listed."""
    runs = []
    for r, row in enumerate(keys):
        found, c = [], 0
        while c < len(row):
            end = c
            while row[c] is not None and end + 1 < len(row) and row[end + 1] == row[c]:
                end += 1
            found.append((c, end, row[c]))
            c = end + 1
        runs.append(found)
    boxes = {}                       # (row, first col, last col) -> top row
    for r, found in enumerate(runs):
        above = dict(((a, b), k) for a, b, k in runs[r - 1]) if r else {}
        for a, b, k in found:
            if k is not None and r and above.get((a, b)) == k:
                boxes[(r, a, b)] = boxes[(r - 1, a, b)]
            else:
                boxes[(r, a, b)] = r
    bottom = {}
    for (r, a, b), top in boxes.items():
        bottom[(top, a, b)] = max(bottom.get((top, a, b), r), r)
    out = {}
    for (r, a, b), top in boxes.items():
        last = bottom[(top, a, b)]
        if a == b and top == last:
            continue
        for c in range(a, b + 1):
            out[(r, c)] = (top, a, last, b)
    return out


def rl_box_key(cell, unit):
    """What two of an analyte's matrix cells (its reported flag with the RL,
    its RL, its MDL) must share to be drawn as one box: the value as shown,
    whether it is typed or the lowest calibrator's, and the matrix's unit.
    None, never merged, for a matrix it is left out of, an absent cell or a
    cell with no value."""
    if cell is None:
        return None
    data = cell.data or {}
    if "in" in data:
        if not data.get("in"):
            return None
        typed, derived = _text(data.get("rl")), _text(data.get("derived"))
        return ("set", typed, unit) if typed else (("derived", derived, unit) if derived else None)
    shown = _text(cell.value).strip()
    if not shown or _none_marked(cell) or cell.state not in ("set", "inherited"):
        return None
    return ("set" if cell.state == "set" else "derived", shown, unit)


def _mark_rl_boxes(cells, col_keys, units, prefix):
    """An analyte's equal matrix cells side by side drawn as one box
    (merge_boxes on its row alone: a box never joins two analytes). Each
    cell keeps its own control, name and editor; data-box-live marks a box
    the page undoes once a value in its row changes."""
    keys = [rl_box_key(cells.get(k), u) for k, u in zip(col_keys, units)]
    for (_r, c), (_top, first, _last, end) in merge_boxes([keys]).items():
        cell = cells[col_keys[c]]
        data = dict(cell.data or {})
        data["box"] = "box-{0}-{1}".format(prefix, first)
        data["box-edge"] = " ".join(e for e, on in (("t", True), ("r", c == end), ("b", True), ("l", c == first)) if on)
        data["box-live"] = "1"
        if c == first:
            data["box-lead"] = "1"
        cell.data = data


def merge_counts(keys):
    """(cells, boxes, row merges) of a grid as merge_boxes draws it: the
    cells that hold a key, the boxes they make, and how many runs joined
    the run above them."""
    merged = merge_boxes(keys)
    cells = sum(1 for row in keys for k in row if k is not None)
    tops = set()
    for (r, c), box in merged.items():
        tops.add(box)
    alone = sum(1 for r, row in enumerate(keys) for c, k in enumerate(row) if k is not None and (r, c) not in merged)
    joins = sum(box[2] - box[0] for box in tops)
    return cells, alone + len(tops), joins


def analytes_sheet(profile, env=None):
    """The Analytes tab: one row per panel analyte, alphabetical
    (analyte_order), each column posting its section's own input name to section-analytes.
    It has no parent.

    Shown: Reported in, with RL (a flag per matrix, headed by the matrix
    and its unit, posted as ami.<keyword>.<matrix> and written by
    profile_form.apply_loose; a reported cell shows the RL that applies
    there: the analyte's RL when one is set, else the lowest calibrator's,
    muted; ✗ left out), Quantified by (the surrogate map, over the method's SUR
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
    rounded = mps.rounded_on_save(profile, env)
    roles = ls.roles(profile)
    surrogates = [(kw, (services.get(kw) or {}).get("name") or kw)
                  for kw in sorted(k for k, role in roles.items() if role == "surrogate")]
    # the method's composites after its surrogates, by name
    composites = [(c["id"], c["name"]) for c in std_composites(profile)]
    # then its internal standards: an analyte quantified on one is
    # calibrated by internal-standard quantitation (EPA 537.1)
    injection = [(kw, (services.get(kw) or {}).get("name") or kw)
                 for kw in sorted(k for k, role in roles.items() if role == "injection_is")]
    standards = surrogates + composites + injection
    quant_groups = [(h, [v for v, _l in opts]) for h, opts in ((QUANT_SUR_HEAD, surrogates + composites),
                                                               (QUANT_IS_HEAD, injection)) if opts]

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
    # alphabetical (analyte_order): a drawing order, the stored set keeps its own
    for kw in analyte_order(panel, titles):
        label = titles.get(kw, kw)
        cells = {}
        name, sur = drawn(sur_cells, sur_tbl, (kw,), "surrogate_is")
        quant = (sur or {}).get("value") or ""
        cells["quant"] = Cell(quant, state="set" if quant else "off", name=name, options=standards,
                              groups=quant_groups)
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
                # the default at full precision, for Fill RLs from calibration
                fill = {"derived": repr(float(low))} if low is not None else None
                if rc["value"] == "" and low is not None:
                    cell = Cell(mps.derived_rl_hint(low, profile, m), state="inherited",
                                source="the lowest calibrator", name=name, data=fill)
                else:
                    saves = (rounded.get((m, kw)) or {}).get(path)
                    cell = Cell(rc["value"], name=name, data=fill, saves_as=saves[1] if saves else None)
                cells["{0}-{1}".format(col, i)] = cell
        for i, m in enumerate(matrices):
            # the flag: reported or left out, with the RL set for it here
            reported = bool((inclusion.get(kw) or {}).get(m, True))
            name = pf.panel_switch_names(kw, m)[0]
            rl, mdl = cells.get("rl-{0}".format(i)), cells.get("mdl-{0}".format(i))
            if rl is not None:
                typed = _text(rl.value) if rl.state == "set" else ""
                # no RL stored: the lowest calibrator's, the RL that applies
                derived_rl = _text(rl.value) if rl.state == "inherited" else ""
                cells["panel-{0}".format(i)] = Cell(_flag_words(reported, typed, derived_rl, True), name=name,
                                                    data={"in": reported, "rl": typed, "rl_name": rl.name,
                                                          "derived": derived_rl,
                                                          "mdl_name": mdl.name if mdl is not None else None})
            else:
                cells["panel-{0}".format(i)] = _left_out_flag(cf, mps, rl_tbl, profile, m, kw, name)
        name, factor = drawn(salt_cells, salt_tbl, (kw,), "factor")
        lot_name, lot = drawn(salt_cells, salt_tbl, (kw,), "lot_uid")
        lot_value = (lot or {}).get("value") or ""
        lot_options = list((lot or {}).get("choices") or [])
        lot_label = _label_of(lot_options, lot_value) if lot_value else ""
        cells["salt"] = Cell((factor or {}).get("value") or "", name=name,
                             title=SALT_HINT + ("; CoA lot: {0}".format(lot_label) if lot_label else ""),
                             data=_salt_calc(kw, label, entry if summed else None, lot_name, env))
        cells["lot"] = Cell(lot_value, name=lot_name, options=lot_options)
        for path in ("linear", "branched", "reported"):
            name, rc = drawn(iso_cells, iso_tbl, (kw,), path)
            cells[path] = Cell((rc or {}).get("value") or "", name=name)
        for part in ("panel", "rl", "mdl"):
            _mark_rl_boxes(cells, ["{0}-{1}".format(part, i) for i in range(len(matrices))],
                           [units.get(m) or "" for m in matrices], "an-{0}-{1}".format(kw, part))
        rows.append(Row(kw, label, cells, sub=chemical_name(full.get(kw), summed) or None,
                        flags=() if quant else (NO_SURROGATE,)))
    sheet = Sheet("analytes", columns, rows, column_switches=["panel-{0}".format(i) for i in range(len(matrices))],
                  form=ANALYTES_FORM, layout="matrix", actions=ANALYTE_ACTIONS,
                  help=help_dictionary.SECTION_HELP["analytes"])
    sheet.fill_rl = any(v is not None for v in derived.values())
    sheet.note = rounded_note(rounded, titles)
    return sheet


def saves_as_words(text):
    """The hint beside a value Save rounds."""
    return "Saves as {0}".format(text)


# how many rounded values the note names before it counts the rest
NOTE_NAMES = 8


def rounded_note(rounded, titles=None):
    """The line above the Analytes grid naming each stored RL and MDL the
    next Save rounds to its matrix's significant figures
    (method_profile_sections.rounded_on_save), or None when Save rounds
    nothing."""
    shown = _tab_modules()[0]._shown        # the stored value as its box shows it
    items = []
    for (matrix, kw), cols in sorted(rounded.items()):
        for col in ("rl", "mdl"):
            if col in cols:
                before, after = cols[col]
                items.append("{0} {1}, {2}: {3} {4} {5}".format(
                    (titles or {}).get(kw, kw), col.upper(), matrix, shown(before), "→", after))
    if not items:
        return None
    shown = "; ".join(items[:NOTE_NAMES])
    more = len(items) - NOTE_NAMES
    return "Save rounds {0} to the figures the certificate prints: {1}{2}.".format(
        counted(len(items), "stored value"), shown, "; and {0} more".format(more) if more > 0 else "")


# The Engine flag the Analytes tab's banner stands for: on, the lab has yet
# to check the method's analyte set; its Confirm analyte set button turns it off.
CONFIRMED_PATH = ("engine", "inclusion_needs_verification")
# the note while the flag is off and no confirmation is on record (a method
# shipped unflagged): Confirm again stands beside it all the same
NOT_FLAGGED = "Analyte set not flagged for lab confirmation"


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
# the Analytes tab's Quantified by: its choices under these headings
QUANT_SUR_HEAD = "Surrogates"
QUANT_IS_HEAD = "Internal standards"
# a standard joins or leaves the method by its own action form
STANDARDS_ADD = ("standards-add", "standard", "standards-add-pick", "Add a standard", "Standard")
STANDARDS_REMOVE = ("standards-remove", "standard")
# the column a SUR row's menu copies into every class ("Copy Aqueous to every class")
BASE_LIMITS = "eis-aq"


# A method whose Engine does not judge standards per matrix class has one
# surrogate window for every standard: the grid draws it on each SUR row, in
# one column, and posts it once under the Surrogates section's own names.
WINDOW_COLUMN = "sur-window"
WINDOW_NOTE = "Applies to every surrogate of the method"
METHOD_TEXT = "the method text"
WINDOW_SECTION = "cal_sur"


# the Engine's "starts from" choice that reads the Surrogates section's window
WINDOW_BASE = "surrogate_window"


def window_in_grid(profile):
    """Whether the Isotope standards grid holds the method's one surrogate
    window: wherever the Engine does not judge standards per matrix class.
    Where it does, each standard has its own limits in the grid, and the
    one window (a base those limits may start from) stays a field of the
    Surrogates section."""
    _cf, mps, _pf, _iso, _ls = _tab_modules()
    return not mps._engine_module().engine(profile or {})["eis_recovery_limits"]


def _window_fields(mps):
    """The surrogate window's two fields (min, max) of the Surrogates section."""
    lo, hi = [f for f in mps.SECTIONS[WINDOW_SECTION].fields() if f.path[0] == "surrogate_window"]
    return lo, hi


def field_mark(profile, key):
    """A section field's limit box mark, beside its box in a Table view's
    fold: the box's glyph alone, as every placard is, on an element that is
    the box (its right click opens the State menu, it greys while Off)."""
    from senaite.pfas import limit_placard
    return limit_placard.boxed(_tag("span", [("class", "cf-limit-mark")], ""), profile, key,
                               variant=limit_placard.CARD_PLACARD)


# the folds whose limit box fields carry their mark (a rule's own limits are
# marked on its rule row instead): Dilutions, on Run & reporting
MARKED_SECTIONS = ("dil",)


def _field_marks(groups, profile):
    """Each drawn field that is a limit box (limit_placard.box_of_name: the
    dilutions' lowest EIS recovery) carries its mark, as its card's tile
    carries the placard: anything the List shows, the Table shows."""
    from senaite.pfas import limit_placard
    out = []
    for g in groups:
        marked = []
        for key in ("fields", "shown"):
            marked.append([dict(f, placard=field_mark(profile, limit_placard.box_of_name(f.get("name"))))
                           if limit_placard.box_of_name(f.get("name")) else f for f in g.get(key) or ()])
        out.append(dict(g, fields=marked[0], shown=marked[1]))
    return out


def fold_groups(sid, groups, profile):
    """A section's drawn groups (config_forms.render) as its fold shows
    them: the Surrogates section without the surrogate window while the
    grid holds it (the grid posts it, under the same names), and, where the
    Engine judges standards per matrix class, without it unless the Engine's
    window starts from the surrogate window (an undrawn field posts nothing,
    so the stored window stays); a group left with nothing is not drawn.
    The linked response ratio is drawn as the profile reads it, the retired
    surrogate_amount "measured" as On. Every other section as rendered."""
    if sid in MARKED_SECTIONS:
        groups = _field_marks(groups, profile)
    if sid == "lrr":
        _cf, mps, _pf, _iso, _ls = _tab_modules()
        value = mps.linked_response_ratio(profile)
        return [dict(g, fields=[dict(f, value=value) for f in g["fields"]],
                     shown=[dict(f, value=value) for f in g["shown"]]) for g in groups]
    if sid != WINDOW_SECTION:
        return groups
    _cf, mps, _pf, _iso, _ls = _tab_modules()
    eng = mps._engine_module().engine(profile or {})
    if not window_in_grid(profile) and eng["eis_default_window"] == WINDOW_BASE:
        return groups
    gone = set(f.name for f in _window_fields(mps))
    out = []
    for g in groups:
        g = dict(g, fields=[f for f in g["fields"] if f["name"] not in gone],
                 shown=[f for f in g["shown"] if f["name"] not in gone])
        if g["fields"]:
            out.append(g)
    return out


def _window_cell(cf, mps, profile, env):
    """(the cell every SUR row shows, the two hidden fields that post it):
    the profile's own window as stored, else, drawn as inherited, the
    window the method text states (method_engine.surrogate_window, as the
    worker judges it); typing a window sets the profile's own, and clearing
    it gives the method text's back."""
    lo, hi = _window_fields(mps)
    drawn = dict((f["name"], f["value"]) for g in cf.render(mps.SECTIONS[WINDOW_SECTION], profile, env)
                 for f in g["fields"])
    names = (lo.name, hi.name)
    stored = (_text(drawn[lo.name]), _text(drawn[hi.name]))
    data = {"shared": True, "note": WINDOW_NOTE}
    posted = [Cell(v, name=n) for n, v in zip(names, stored)]
    judged = mps._engine_module().surrogate_window(profile)
    if judged is not None and judged["source"] == "method_text":
        # an end the profile holds alone is kept as stored and posted back:
        # it judges nothing until both are set
        cell = Cell((_g(judged["min"]), _g(judged["max"])), state="inherited", source=METHOD_TEXT,
                    name=names, title=mps._engine_module().METHOD_DEFAULT_WORDS, data=data)
        return cell, posted
    return Cell(stored, name=names, title=mps._engine_module().METHOD_DEFAULT_WORDS, data=data), posted


# the IS response windows (section cal_is), held in the internal standard
# rows: one window against the initial calibration average, in the limits
# columns (spanning the matrix classes: it is method-wide), and the
# comparison to the most recent CCV in a column of its own
IS_WINDOW_KEY = "is-resp"
IS_WINDOW_NOTE = "All matrices \u00b7 % of the initial calibration average"
IS_CCV_COLUMN = "is-ccv"
IS_CCV_LABEL = "IS vs most recent CCV"
# a window whose rule is Off, as config_forms.na_text says it
KEPT_NOT_JUDGED = "{0} is Off: kept, not judged"


def _is_window_cells(cf, mps, profile, env, span=None):
    """(the IS Response window every IS row shows, its comparison to the
    most recent CCV, the four hidden fields that post them): section
    cal_is's fields as stored, each a shared pair (each row's inputs post
    nothing, the hidden field of its name is saved), the first covering
    `span`, each greyed while its rule is Off (as its state's input holds
    it, an inherited Off too) and still edited."""
    rules, _qct = _qc_modules()
    drawn = dict((f["name"], f["value"]) for g in cf.render(mps.SECTIONS["cal_is"], profile, env)
                 for f in g["fields"])
    names = dict((f.path[1], f.name) for f in mps.SECTIONS["cal_is"].fields())
    states = dict((r.key, r) for r in _library_rows(profile, tuple(IS_RULE_FIELDS)))
    cells, posted = [], []
    for rule, note, over in (("is_response", IS_WINDOW_NOTE, span), ("is_vs_ccv", None, None)):
        pair = tuple(names[e] for e in IS_RULE_FIELDS[rule])
        stored = tuple(_text(drawn[n]) for n in pair)
        posted += [Cell(v, name=n) for n, v in zip(pair, stored)]
        row = states[rule]
        state = row.cells["state"]
        off = _text(state.value) == "off"
        label = _rule_label(rules, rule)
        # greyed while its own limit box is Off (its posted input,
        # limitstate.<box>), never disabled
        data = {"mute-if": "limitstate." + rule, "mute-values": "off"}
        data.update(shared=True, muted=off)
        if note:
            data["note"] = note
        title = MIDDOT.join(w for w in (KEPT_NOT_JUDGED.format(label) if off else "", note) if w) or None
        cells.append(Cell(stored, name=pair, data=data, title=title, span=over,
                          key=IS_WINDOW_KEY if rule == "is_response" else None,
                          label=label if rule == "is_response" else None))
    return cells[0], cells[1], posted


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
    limits, never a constant."""
    _cf, mps, _pf, _iso, _ls = _tab_modules()
    n_sur = len([k for k in grid if grid[k].get("role") == "surrogate"])
    n_is = len([k for k in grid if grid[k].get("role") == "injection_is"])
    if rules.rule_state(profile, profile.get("method_id"), "surrogate_recovery") == "off":
        sur = "{0}, recovery not judged".format(counted(n_sur, "extracted standard"))
    else:
        sur = "{0}, recovery-checked".format(counted(n_sur, "extracted standard"))
    if rules.rule_state(profile, profile.get("method_id"), "is_response") == "off":
        is_ = "{0}, area not judged".format(counted(n_is, "injection standard"))
    else:
        window = _rule_limits(mps, profile)["is_response"]
        is_ = "{0}, judged on area against the calibration{1}".format(
            counted(n_is, "injection standard"), ", " + window if window else "")
    words = {STANDARD_GROUPS[0][0]: sur, STANDARD_GROUPS[1][0]: is_}
    return [Row(key, label, {}, sub=words[key], selectable=False) for key, label in STANDARD_GROUPS]


def short_heading(label):
    """A narrow column's heading: the last word of its full name,
    capitalised ("Landfill leachate" is "Leachate")."""
    words = (label or "").split()
    if not words:
        return label or ""
    last = words[-1]
    return last[:1].upper() + last[1:]


def _std_salt_columns():
    """The standards grid's Salt factor and CoA lot, drawn as the Analytes
    grid draws an analyte's."""
    return [Column("salt", "Salt factor", "num", align="right", max=1),
            Column("lot", "CoA lot", "select", default=False)]


def _std_salt_cells(cf, mps, profile, env, salt_cells, kw, label):
    """{"salt", "lot"}: a labelled standard's salt factor and CoA lot cells,
    posting to the salt_std section (the same list an analyte's factor is
    kept in), with the analyte cell's hint and calculator."""
    tbl = mps.SALT_STD
    name = _named(cf, tbl, profile, (kw,), "factor")
    lot_name = _named(cf, tbl, profile, (kw,), "lot_uid")
    factor, lot = salt_cells.get(name) or {}, salt_cells.get(lot_name) or {}
    lot_value = lot.get("value") or ""
    lot_options = list(lot.get("choices") or [])
    lot_label = _label_of(lot_options, lot_value) if lot_value else ""
    return {"salt": Cell(factor.get("value") or "", name=name,
                         title=SALT_HINT + ("; CoA lot: {0}".format(lot_label) if lot_label else ""),
                         data=_salt_calc(kw, label, None, lot_name, env)),
            "lot": Cell(lot_value, name=lot_name, options=lot_options)}


def standards_sheet(profile, env=None):
    """The Labelled standards tab: one row per labelled standard the method
    uses, SUR then IS, each column posting its section's own input name to
    section-standards.

    Shown: the row's menu (⋯), Role (SUR or IS), Linked to (the method's
    other standards) and Quantifies (read-only: the natives the surrogate
    map quantifies against it and the standards linked to it); each row
    carries the natives it quantifies (data-quantifies), which refuse its
    removal. When the Engine judges extracted standards per matrix class,
    each SUR's recovery limits, aqueous and per class; a blank class reads the aqueous
    limit, and a class marked None is not assessed. Where the Engine does
    not, one Recovery limits column: the method's one surrogate window,
    shown on every SUR row and posted once (_window_cell). Add and Remove
    sit above the grid. A limits row is the standard's whose keyword its name
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
               Column("link", "Linked to", "select"), Column("quant", "Quantifies", "text")]
    window = None
    if limits:
        # every matrix class side by side: narrow, each headed by the last
        # word of its name, the full name on hover
        columns += [Column("eis-" + key, short_heading(label), "pair", align="right", group=LIMITS_GROUP,
                           unit="%", min=0, title=label, narrow=True)
                    for key, label in mps._EIS_COLS]
    elif window_in_grid(profile):
        window, posted = _window_cell(cf, mps, profile, env)
        hidden += posted
        columns.append(Column(WINDOW_COLUMN, LIMITS_GROUP, "pair", align="right", unit="%", min=0))
    # each IS row's response window in the limits columns, one box over the
    # matrix classes; its comparison to the most recent CCV after them
    is_start = BASE_LIMITS if limits else WINDOW_COLUMN
    is_window, is_ccv, posted = _is_window_cells(
        cf, mps, profile, env, span=["eis-" + key for key, _l in mps._EIS_COLS] if limits else None)
    hidden += posted
    columns.append(Column(IS_CCV_COLUMN, IS_CCV_LABEL, "pair", align="right", unit="%", min=0,
                          title=_rule_label(rules, "is_vs_ccv")))
    # each standard's salt factor and its CoA lot, as an analyte's
    columns += _std_salt_columns()
    columns.append(Column("menu", "Row menu", "menu"))         # the row's menu ends the row
    salt_cells = _drawn(cf, mps.SALT_STD, profile, env)

    from senaite.pfas import limit_placard
    sur_box = limit_placard.box_parts(profile, "surrogate_recovery")
    rows = []
    for kw in sorted(grid):
        cells = {}
        cells.update(_std_salt_cells(cf, mps, profile, env, salt_cells, kw, (services.get(kw) or {}).get("name") or kw))
        name, role = drawn(kw, "role")
        cells["role"] = Cell(role, name=name, options=list(ROLE_WORDS))
        name, ref = drawn(kw, "reference")
        # a surrogate links to an internal standard alone (the stored value
        # is always drawn, so a link to a surrogate shows and is refused)
        targets = [k for k in sorted(grid) if k != kw and
                   (grid[kw].get("role") != "surrogate" or grid[k].get("role") == "injection_is")]
        cells["link"] = Cell(ref, name=name, options=[(k, k) for k in targets])
        natives = ls.removal_blocked_by(profile, kw)
        held = ls.composites_holding(profile, kw)
        standards = sorted(linked.get(kw) or [])
        words = ", ".join(w for w in (natives and counted(len(natives), "analyte"),
                                      standards and counted(len(standards), "standard")) if w)
        # a plain count, no button in the cell: the names open from the
        # row's menu (data-quant-list) and the standard's card (its links)
        cells["quant"] = Cell(words, state="readonly", links=[(k, None) for k in natives + standards],
                              title="Quantifies " + ", ".join(natives + standards) if words else QUANTIFIES_NOTHING,
                              html=_val(words) if words else
                              '<span class="pfas-sheet-val is-empty">{0}</span>'.format(EM_DASH))
        hidden.append(Cell("1", name=_named(cf, ls_tbl, profile, (kw,), "used")))
        if kw in on_rows:
            cells.update(limit_cells(on_rows[kw]))
        if window is not None and grid[kw].get("role") == "surrogate":
            cells[WINDOW_COLUMN] = window
        if grid[kw].get("role") == "surrogate":
            # every class cell, and the one window, of a surrogate is judged
            # in the one Surrogate Recovery box: its placard on each, a right
            # click on any sets that box
            for ck, c in cells.items():
                if (ck == WINDOW_COLUMN or ck.startswith("eis-")) and c.key != IS_WINDOW_KEY:
                    c.box = sur_box
        if grid[kw].get("role") == "injection_is":
            cells[is_start] = is_window
            cells[IS_CCV_COLUMN] = is_ccv
        cells["menu"] = Cell(None, state="readonly", data={"base": BASE_LIMITS} if kw in on_rows else None)
        label = (services.get(kw) or {}).get("name") or kw
        rows.append(Row(kw, kw, cells, sub=label if label != kw else None,
                        group=group_of.get(grid[kw].get("role")),
                        data=dict({"quantifies": natives, "member": "1", "quant-list": natives + standards,
                                   "card": kw},
                                  **({"held-by": held} if held else {}))))
    # the method's composites post with this tab: one row each, its id and
    # its members (the List view's composite cards and the Combine window
    # write them)
    cmp_coll = mps.COMPOSITES
    for i, vals in enumerate(mps.read_composites(profile)):
        for f in cmp_coll.columns:
            # counted as one composite whichever input changed (the
            # footer's unsaved count: data-kind, data-unit)
            hidden.append(Cell(vals[f.path[0]], name=cf.collection_name(cmp_coll, i, f),
                               data={"kind": cf.change_kind(cf.collection_name(cmp_coll, i, f)),
                                     "unit": "cmp-%d" % i}))
    groups = _group_rows(profile, grid, rules)
    if spare:                              # stored limits no standard of the method takes: shown, never hidden
        groups.append(SPARE_GROUP)
        for i, vals in spare:
            rows.append(Row("limits-{0}".format(i), vals["analyte"][1], limit_cells(vals),
                            group=SPARE_GROUP[0]))
    adder = STANDARDS_ADD + (standards_to_add(profile, env),)
    return Sheet("standards", columns, rows, groups=groups, form=STANDARDS_FORM, hidden=hidden,
                 adder=adder, remover=STANDARDS_REMOVE, help=help_dictionary.SECTION_HELP["standards"])


# ── the Isotope standards tab as a list: each standard beside its card ─────

STD_LIST_ID = "standards-list"
FOLLOWS_AQ = "Follows Aqueous"
NOT_LINKED = "Not linked"
NOT_SET_WORDS = "Not set"
STD_NONE_NOTE = "Not assessed in this matrix class: its None box is ticked."
ADD_STD_WORDS = "+ Add standard"
REMOVE_STD_WORDS = "Remove from method"
STD_OFF_NOTE = "Not judged: {0} is Off."
IS_AREA_LABEL = "Area against the calibration"
IS_AREA_NOTE = "Set on Internal standards"
# each group's parent node and card: its rules, their states and limits,
# then its standards as mini-cards
STD_GROUP_KEY = "group-{0}"
STD_GROUP_TITLES = {"sur": "Surrogates", "is": "Internal standards"}
# the rule whose Off greys the whole group, its standards with it
STD_GROUP_PRIMARY = {"sur": "surrogate_recovery", "is": "is_response"}
EDIT_LIMITS_WORDS = "Edit limits"
MDL_EDIT_WORDS = "Edit MDLs"
MDL_TITLE = "Each analyte's MDL"
PER_CLASS_WORDS = "Per standard and matrix class"
PER_CLASS_NOTE = "Each standard's card holds its windows by matrix class."
STD_MINIS_HEAD = "Standards"
STD_NO_MEMBERS = {"sur": "No surrogate in the method yet.", "is": "No internal standard in the method yet."}
STD_RULES_ID = "std-rules"
# the IS response windows each IS rule judges by (section cal_is)
IS_RULE_FIELDS = {"is_response": ("vs_ical_avg_min", "vs_ical_avg_max"),
                  "is_vs_ccv": ("vs_last_ccv_min", "vs_last_ccv_max")}
IS_RULE_CAPTIONS = {"is_response": "Method-wide: every matrix, against the initial calibration average",
                    "is_vs_ccv": "Against the most recent CCV. Off: greyed, still editable."}
# a group card's two headings: its rules' states, then their windows
STD_RULES_HEAD = "Rules"
STD_LIMITS_HEAD = "Limits"
# the tab's other settings each group's card shows, by heading: every field
# of the sections drawn on the tab (as their fold draws them), so the List
# view reaches each one and those sections show in the Table view alone
STD_SETTINGS = {"sur": (("Settings", ("engine_sur", "cal_sur")), ("Surrogate failure", ("surscope",))),
                "is": (("How results are corrected", ("lrr",)),)}
EDIT_SETTINGS_WORDS = "Edit settings"
# a surrogate's card: the analytes it corrects, edited in the Analytes
# tab's Quantified by column
CORRECTS_HEAD = "Corrects"
CORRECTS_NOTHING = "Corrects no analyte."
LINKED_TO_IT_HEAD = "Standards linked to it"
EDIT_ON_ANALYTES = "Edit what it corrects"
OPEN_ANALYTES_WORDS = "Edit Quantified by"
QUANTIFIED_BY_TITLE = "Quantified by"
# the Analytes grid, whose columns a window copies (Quantified by, the MDLs)
ANALYTES_SHEET = '.pfas-sheet-box[data-sheet="analytes"] table'


def quantified_by(title, natives=None):
    """The window of the analytes' Quantified by (the Analytes grid's own
    inputs): `natives`' rows, else every analyte's."""
    return inplace(title, tables=[{"sel": ANALYTES_SHEET, "cols": ["quant"], "rows": list(natives or [])}])
# the Internal standards card's chain: each IS, the standards linked to it,
# the analytes each corrects (Linked to and Quantified by, nothing new stored)
CHAIN_HEAD = "Links"
CHAIN_ARROW = "\u2192"
CHAIN_NOTHING = "no analyte"
CHAIN_UNLINKED = "Not linked to an internal standard"
CHAIN_NOTE = "Read from Linked to and Quantified by. {0} of {1} analytes are corrected by a standard."
# an internal standard's mini-card: what it quantifies, counted
IS_QUANTIFIES = "Quantifies {0}"
# the way back from a standard's card to its group's
BACK_WORDS = "Back to {0}"
# the Internal standards card's "How results are corrected": what an
# analyte's Quantified by decides, read only, then the one choice, the
# response ratio linked to the injection standard
# (method_profile_sections.LINKED_RATIO), each option over the equation it
# uses
CORR_HEAD = "How results are corrected"
CORR_LINES = (("Quantified by a surrogate", "Isotope dilution"),
              ("Quantified by an internal standard", "Internal-standard quantitation"))
CORR_LINES_NOTE = "Set by each analyte's Quantified by on Analytes"
RATIO_LABEL = "Response ratio linked to the injection standard"
# Each option's equations, as the shared equation component draws them
# (pfas-components.js, PFAS.equation): "_{x}" is a subscript, a division is
# a stacked fraction, a bracketed operand gives its brackets to the bar.
RATIO_EQUATIONS = {
    "off": ("RR_{analyte} = (A_{analyte} \u00d7 C_{surrogate}) \u00f7 A_{surrogate}",),
    "on": ("RR_{surrogate} = (A_{surrogate} \u00d7 C_{IS}) \u00f7 A_{IS}",
           "RR_{analyte} = (A_{analyte} \u00d7 C_{surrogate}) \u00f7 RR_{surrogate}")}
RATIO_NOTES = {"off": "The surrogate counts as spiked.",
               "on": "The surrogate is first measured against the internal standard."}
# every term of either option: (symbol, what it means, where its value
# comes from, the options it is used in)
INJ_SOURCE = "integration of this injection"
RUN_SOURCE = "run record"
HERE_SOURCE = "computed here"
CURVE_SOURCE = "calibration curve"
RATIO_TERMS = (
    ("A_{analyte}", "the analyte's peak area in this injection", INJ_SOURCE, ("off", "on")),
    ("A_{surrogate}", "the surrogate's peak area in this injection", INJ_SOURCE, ("off", "on")),
    ("C_{surrogate}", "the surrogate's level in the calibrators, times its salt factor", RUN_SOURCE, ("off", "on")),
    ("A_{IS}", "the internal standard's peak area in this injection", INJ_SOURCE, ("on",)),
    ("C_{IS}", "the internal standard's level in the calibrators, times its salt factor", RUN_SOURCE, ("on",)),
    ("RR_{surrogate}", "the surrogate's response ratio, the first step of On", HERE_SOURCE, ("on",)))
# the step every result shares: the response ratio read back through the
# curve fitted on the calibrators' response ratios
CURVE_STEP = {
    "head": "Then the concentration, from the curve",
    "note": ("The curve is fitted on the calibrators' response ratios, worked out the same way "
             "as the option in use."),
    "formulas": ["C_{analyte} = (RR_{analyte} \u2212 intercept) \u00f7 slope"],
    "alt": {"lead": "On an average-factor fit:", "formulas": ["C_{analyte} = RR_{analyte} \u00f7 RRF"]},
    "terms": [{"symbol": "RR_{analyte}", "label": "the analyte's response ratio, from the option in use",
               "source": HERE_SOURCE},
              {"symbol": "intercept", "label": "where the curve crosses the axis", "source": CURVE_SOURCE},
              {"symbol": "slope", "label": "response ratio per unit of concentration", "source": CURVE_SOURCE},
              {"symbol": "RRF", "label": "the mean response factor, on an average-factor fit",
               "source": CURVE_SOURCE}]}
RATIO_FOOT = "Read only. The switch on the card changes the setting."
RATIO_UNUSED = "No analyte is quantified on a surrogate: the choice is kept for when one is."
# the Analytes tab's one setting for a diluted sample's surrogate recovery
# (method_profile_sections.DILUTION_RECOVERY), each option over its
# equation; read only where the response ratio is linked
DILREC_EQUATIONS = {"fold": "R = (C_{found} \u00d7 DF) \u00f7 C_{spiked}", "measured": "R = C_{found} \u00f7 C_{spiked}",
                    "parent": "R = R_{parent}"}
DILREC_TERMS = (
    ("C_{found}", "the surrogate found in the diluted extract", HERE_SOURCE, ("fold", "measured")),
    ("DF", "the dilution factor", "the retest", ("fold",)),
    ("C_{spiked}", "the surrogate spiked into the sample", RUN_SOURCE, ("fold", "measured")),
    ("R_{parent}", "the undiluted sample's recovery", "the parent sample", ("parent",)))
DILREC_FOOT = "Read only. The choice on this tab changes the setting."
DILREC_UNSET = "Not set: a diluted sample's surrogate recovery is not judged"
# the links each tab requires before its Save (method_profile_sections
# LINK_CHECKS), named in a warning on the tab
UNLINKED_SUR_HEAD = "Surrogates not linked to an internal standard"
UNLINKED_SUR_NOTE = ("Set each one's Linked to an internal standard, never a surrogate: "
                     "the tab is not saved while one is not.")
UNQUANTIFIED_HEAD = "Analytes with no Quantified by"
UNQUANTIFIED_NOTE = ("Set each one's Quantified by to a surrogate or an internal standard: "
                     "the tab is not saved while one is missing.")
YES_WORDS = "Yes"
NO_WORDS = "No"
# composite standards: the mean of two or more surrogates' areas, each its
# own node and card under Surrogates (composite_standards); its members and
# what it corrects are read from the grid and the Analytes tab
COMBINE_WORDS = "+ Combine surrogates"
COMBINE_TITLE = "Combine surrogates"
CMP_MEMBERS_HEAD = "Members"
CMP_EDIT_WORDS = "Edit members"
CMP_REMOVE_WORDS = "Remove composite"
CMP_AVERAGED_LABEL = "Averaged as"
CMP_CAPTION = "Composite"
CMP_LINKED = "linked to {0} as its members are"
CMP_UNLINKED = "its members linked to no standard"
CMP_NOTE = ("The analyte's area is divided by the mean of the members' areas in the same injection. "
            "Each member is judged on its own; a member missing leaves no reading.")
ALSO_IN = "Also in {0}: {1}"
HELD_REFUSED = "Refused: it is a member of {0}. Edit or remove that composite first."


def _and_words(names):
    """"A", "A and B", "A, B and C"."""
    names = [_text(n) for n in names]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1] if names else ""


def remove_refused(natives, held=()):
    """Why a standard cannot leave the method: the natives it quantifies (as
    the grid's row menu words it), else the composites it is a member of,
    or "" when nothing points at it."""
    if natives:
        return "Refused: it quantifies {0}. Change their Quantified by first.".format(_and_words(natives))
    if held:
        return HELD_REFUSED.format(_and_words(held))
    return ""


def _pair_ends(pair):
    """(lo, hi) as floats, or None while either end is blank."""
    lo, hi = _pair(pair)
    try:
        return (float(lo), float(hi)) if lo not in (None, "") and hi not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _window_text(pair):
    """A window in words: "50 – 150 %"; one end alone shows a dash for the
    other; blank, "Not set"."""
    lo, hi = [_text(v) if v not in (None, "") else "" for v in _pair(pair)]
    if not lo and not hi:
        return NOT_SET_WORDS
    return "{0} {1} {2} %".format(_g(lo) if lo else EM_DASH, EN_DASH, _g(hi) if hi else EM_DASH)


def _std_band(ends, thin=False):
    """A tile's or node's bar, always drawn (hidden without a window) so the
    page can redraw it as the grid's inputs change."""
    return _band(ends or (0, 0), thin=thin, attrs=[("data-std-band", True), ("hidden", None if ends else True)])


def class_state(cell):
    """How the card reads one matrix class of a standard's limits, as the
    worker judges it: "none" (its None box ticked: not assessed), "own" (a
    window of its own, either end typed) or "follows" (blank: the
    standard's Aqueous limits judge it)."""
    if cell.none and cell.none[1]:
        return "none"
    if cell.state != "inherited" and any(v not in (None, "") for v in _pair(cell.value)):
        return "own"
    return "follows"


def _class_tiles(row, sheet):
    """The Aqueous tile then one tile per matrix class: its own window as a
    bar, "Follows Aqueous" with the Aqueous bar, or the not-assessed dash
    with its notation mark."""
    aq = row.cells.get("eis-aq")
    aq_pair = aq.value if aq is not None else ("", "")
    aq_ends = _pair_ends(aq_pair)
    tiles, follows = [], []
    for col in sheet.columns:
        if not col.key.startswith("eis-"):
            continue
        cell = row.cells.get(col.key)
        if cell is None:
            continue
        label = col.title or col.label
        state = "own" if col.key == "eis-aq" else class_state(cell)
        attrs = [("data-std-col", col.key), ("data-std-state", state)]
        if state == "none":
            tiles.append(_tag("div", [("class", "pfas-hier-tile")] + attrs,
                              _tag("span", [("class", "pfas-hier-tile-l")], _esc(label)) +
                              _tag("span", [("class", "pfas-hier-tile-v")], OFF_MARK) + _std_band(None)))
            continue
        if state == "follows":
            follows.append(label)
            tiles.append(_tile(label, FOLLOWS_AQ, _std_band(aq_ends, thin=True), attrs=attrs))
            continue
        tiles.append(_tile(label, _window_text(cell.value), _std_band(_pair_ends(cell.value)), attrs=attrs))
    return tiles


def _sur_cell(cells, key):
    """A row's surrogate limits under `key`, never the IS response window
    an IS row holds there (IS_WINDOW_KEY)."""
    cell = cells.get(key)
    return None if cell is None or cell.key == IS_WINDOW_KEY else cell


def _edit_std_words(row):
    """Edit opens the grid row's drawer: its link, and its limits where the
    row holds any (class limits, or the method's one surrogate window)."""
    if row.cells.get("eis-aq") is not None or row.cells.get(WINDOW_COLUMN) is not None:
        return "Edit link and limits"
    return "Edit link"


def _std_menu(row, sheet, limits):
    """A standard's node menu, the grid row menu's entries (pfas:row-action
    events the page runs through that menu): Set role, Edit, Copy / Reset
    for a standard with class limits, then Remove from method, refused with
    its reason while it quantifies natives. None for a row with no menu."""
    from senaite.pfas import row_menu
    menu = row.cells.get("menu")
    if menu is None:
        return None
    natives = (row.data or {}).get("quantifies") or []
    held = (row.data or {}).get("held-by") or []
    return row_menu.actions(
        ("Set role", "event", "std-role") if row.cells.get("role") is not None else None,
        (_edit_std_words(row), "event", "std-edit"),
        ("Copy Aqueous to every class", "event", "std-copy") if limits else None,
        ("Reset classes to Aqueous", "event", "std-reset") if limits else None,
        (REMOVE_STD_WORDS, "event", "std-remove", {"danger": True, "off": remove_refused(natives, held)})
        if sheet.remover else None)


def _chips_block(head, names, empty):
    """A card's heading over its names as chips, or its empty words."""
    return (_tag("h5", [("class", "pfas-hier-h")], _esc(head)) +
            (_tag("span", [("class", "pfas-hier-chips")],
                  "".join(_tag("span", [("class", "pfas-hier-chip")], _esc(n)) for n in names))
             if names else _tag("p", [("class", "pfas-hier-empty")], _esc(empty))))


def _corrects(natives, standards):
    """A surrogate card's Corrects: the analytes whose Quantified by names
    it, read only; the standards linked to it under their own heading."""
    return _tag("div", [("data-std-corrects-of", True), ("class", "pfas-hier-tilebox"), ("aria-label", CORRECTS_HEAD)] +
                tile_opens("analytes"),
                _chips_block(CORRECTS_HEAD, natives, CORRECTS_NOTHING) +
                (_chips_block(LINKED_TO_IT_HEAD, standards, "") if standards else ""))


def std_chain(sheet, profile, composites=()):
    """[(IS key, its own natives, [(standard key, its natives)])] for each
    internal standard of the sheet, the standards whose Linked to names it
    in the grid's order, then the composites (std_composites) whose
    members are linked to it, each as (id, its natives, its name); then
    ("", [], [...]) for the surrogates linked to no internal standard
    (blank, or another surrogate). Read from the grid's rows: the link cell
    and the natives each row quantifies."""
    def link(r):
        c = r.cells.get("link")
        return _text(c.value) if c is not None and c.value else ""

    def natives(r):
        return list((r.data or {}).get("quantifies") or [])
    iss = [r for r in sheet.rows if r.group == STANDARD_GROUPS[1][0]]
    surs = [r for r in sheet.rows if r.group == STANDARD_GROUPS[0][0]]
    keys = set(r.key for r in iss)
    def cmps(on):
        return [(c["id"], list(c["natives"]), c["name"]) for c in composites or () if on(c["reference"])]
    out = [(r.key, natives(r), [(x.key, natives(x)) for x in surs if link(x) == r.key] +
            cmps(lambda ref, k=r.key: ref == k)) for r in iss]
    out.append(("", [], [(x.key, natives(x)) for x in surs if link(x) not in keys] +
                cmps(lambda ref: ref not in keys)))
    return out


def _chain_kids(natives):
    return _tag("span", [("class", "pfas-hier-chain-a")],
                _esc(CHAIN_ARROW + " " + (", ".join(natives) if natives else CHAIN_NOTHING)))


def _render_chain(chain, profile):
    """The chain as a compact tree: each IS (and the natives it quantifies
    itself), under it each standard linked to it, a button opening that
    standard's card, with the analytes it corrects; the standards linked to
    no IS under their own heading, hidden while there is none. Each standard
    carries its key (data-chain-std) so the page moves it as its Linked to
    changes; the analytes read as saved."""
    blocks = []
    for is_key, own, kids in chain:
        items = "".join(_tag("li", [("class", "pfas-hier-chain-i"), ("data-chain-std", kid[0]),
                                    ("data-chain-cmp", True if len(kid) > 2 else None)],
                             _tag("button", [("type", "button"), ("class", "pfas-hier-chain-n"),
                                             ("data-std-open", kid[0]),
                                             ("aria-label", "Show " + _text(kid[-1] if len(kid) > 2 else kid[0]))],
                                  _esc(kid[2] if len(kid) > 2 else kid[0])) +
                             _chain_kids(kid[1]))
                        for kid in kids)
        # one tile per internal standard, as the card's other tiles: its
        # name, the analytes it quantifies itself, the standards linked to it
        if is_key:
            head = (_tag("span", [("class", "pfas-hier-tile-l")], _esc(is_key)) +
                    _tag("span", [("class", "pfas-hier-tile-v")], _esc(_is_quantifies(chain, is_key))) +
                    (_chain_kids(own) if own else ""))
        else:
            head = _tag("span", [("class", "pfas-hier-tile-l")], _esc(CHAIN_UNLINKED))
        # an internal standard's tile opens its row's window in place, its
        # card in the menu (Show); the unlinked ones' only reads
        blocks.append(_tag("div", [("class", "pfas-hier-tile pfas-hier-chain-b"), ("data-chain-is", is_key),
                                   ("data-own", "%d" % len(own) if is_key else None),
                                   ("hidden", True if not is_key and not kids else None)] +
                           (tile_opens("isedit-" + is_key, ["isedit-" + is_key, "is-" + is_key]) if is_key
                            else TILE_READ),
                           _tag("div", [("class", "pfas-hier-chain-r")], head) +
                           _tag("ul", [("class", "pfas-hier-chain-l")], items)))
    panel = list((profile or {}).get("master_analyte_set") or [])
    corrected = set(n for _k, own, kids in chain for n in own + [a for kid in kids for a in kid[1]])
    note = CHAIN_NOTE.format(len([a for a in panel if a in corrected]), len(panel))
    return (_tag("h5", [("class", "pfas-hier-h")], _esc(CHAIN_HEAD)) +
            _tag("div", [("class", "pfas-hier-tiles pfas-hier-chain"), ("data-std-chain", True)],
                 "".join(blocks) + card_acts(*[x for k, _o, _k in chain if k for x in (
                     card_act("isedit-" + k, "Edit " + _text(k), [("data-std-act", "edit"), ("data-std-row", k)]),
                     card_act("is-" + k, "Show " + _text(k), [("data-std-open", k)]))])) +
            _tag("p", [("class", "pfas-hier-note")], _esc(note)))


def _rule_label(rules, key):
    return next((r["label"] for r in rules.RULE_LIBRARY if r["key"] == key), key)


def _std_entry(row, sheet, profile, judged, first=False):
    """(node, dots, card) for one row of the standards grid."""
    _cf, mps, _pf, _iso, _ls = _tab_modules()
    rules, _qct = _qc_modules()
    eng = mps._engine_module()
    cells = row.cells
    role = cells.get("role")
    link = cells.get("link")
    quant = cells.get("quant")
    window = _sur_cell(cells, WINDOW_COLUMN)
    limits = _sur_cell(cells, BASE_LIMITS) is not None
    sur = row.group == STANDARD_GROUPS[0][0]
    is_ = row.group == STANDARD_GROUPS[1][0]
    off = (sur and judged["sur_off"]) or (is_ and judged["is_off"])
    # greyed while its group's rule is Off, following the state as it is set
    mute = judged["mute"].get(row.group) or []

    if limits:
        node_pair = cells["eis-aq"].value
    elif window is not None:
        node_pair = window.value
    else:
        node_pair = None
    node_ends = _pair_ends(node_pair) if node_pair is not None else None
    node_words = _window_text(node_pair) if node_pair is not None else ""
    link_value = _text(link.value) if link is not None and link.value else ""
    sub_line = MIDDOT.join(w for w in (row.sub, "Linked to " + link_value if link_value else "") if w)
    menu = _std_menu(row, sheet, limits)
    key = row.key
    node = _tag("button", [("type", "button"),
                           ("class", _cls("pfas-hier-node", "is-sub" if sur or is_ else None,
                                          "is-selected" if first else None, "is-muted" if off else None)),
                           ("data-hier-target", key), ("aria-pressed", "true" if first else "false"),
                           ("data-std-row", key), ("data-row-actions", menu)] + mute,
                _tag("span", [("class", "pfas-hier-node-t")], _esc(row.label)) +
                _tag("span", [("class", "pfas-hier-node-v"), ("data-std-value", True)], _esc(node_words)) +
                (_std_band(node_ends) if node_pair is not None else "") +
                (_tag("span", [("class", "pfas-hier-node-s")], _esc(sub_line)) if sub_line else ""))
    dots = _dots(row.label, [("data-std-row", key)] + mute, muted=off) if menu else ""
    # its mini-card in the group's card: name, link (an IS: what it
    # quantifies) and window, opening its card
    # an IS's window is its group's IS Response window
    if is_:
        w = judged["windows"]["is_response"]
        window_part = (_tag("span", [("class", "pfas-hier-mini-v")] + _rule_win_attrs("is_response", w),
                            _esc(_rule_window_words(w))) + _rule_band("is_response", w))
    elif node_pair is not None:
        window_part = (_tag("span", [("class", "pfas-hier-mini-v"), ("data-std-value", True)], _esc(node_words)) +
                       _std_band(node_ends))
    else:
        window_part = ""
    # the mini-card is the standard's one row in the list: it opens its card
    # and carries the grid row's menu (a right click, a long press)
    if is_:
        mini_says = _is_quantifies(judged["chain"], key)
    else:
        mini_says = "Linked to " + link_value if link_value else NOT_LINKED
    mini = _tag("button", [("type", "button"), ("class", _cls("pfas-hier-mini", "is-muted" if off else None)),
                           ("data-std-open", key), ("data-std-row", key), ("data-row-actions", menu),
                           ("aria-label", "Show " + _text(row.label))] + mute,
                _tag("span", [("class", "pfas-hier-mini-t")], _esc(row.label)) +
                _tag("span", [("class", "pfas-hier-mini-s"), ("data-std-does", "is" if is_ else None)],
                     _esc(mini_says)) +
                window_part)

    # the card: the role, the link, the limits, what it quantifies
    group = dict(judged["groups"]).get(row.group, "")
    caption = [w for w in (row.sub, group) if w]
    from senaite.pfas import limit_placard
    # the box that judges the standard's window: a surrogate's Surrogate
    # Recovery, an internal standard's IS Response; one box for every
    # standard of the group and every matrix class, so a right click on any
    # of its tiles sets that one box
    own_box = "surrogate_recovery" if sur else ("is_response" if is_ else None)
    tiles = []
    if role is not None:
        tiles.append(_tile("Role", _label_of(_state_options(role), role.value), attrs=[("data-std-col", "role")]))
    if link is not None:
        tiles.append(_tile("Linked to", link_value or NOT_LINKED, attrs=[("data-std-col", "link")]))
    if limits:
        tiles += [limit_placard.boxed(t, profile, own_box) if sur else t for t in _class_tiles(row, sheet)]
    elif window is not None:
        note = [WINDOW_NOTE] + ([eng.METHOD_DEFAULT_WORDS] if window.state == "inherited" else [])
        tile = _tile(LIMITS_GROUP, _window_text(window.value), _std_band(_pair_ends(window.value)),
                     note=MIDDOT.join(note),
                     attrs=[("data-std-col", WINDOW_COLUMN), ("data-std-note", WINDOW_NOTE),
                            ("data-std-default", eng.METHOD_DEFAULT_WORDS)])
        tiles.append(limit_placard.boxed(tile, profile, own_box) if sur else tile)
    if is_:
        # the group's IS Response window, drawn again as it is edited there
        tiles.append(limit_placard.boxed(
            _rule_tile(IS_AREA_LABEL, "is_response", judged["windows"]["is_response"], IS_AREA_NOTE),
            profile, own_box))
    # the heading's state is the group box's placard, in place of any word
    # for it
    state = limit_placard.boxed(_tag("span", [("class", "pfas-card-state")], ""), profile, own_box) \
        if sur else ""
    head = (_tag("h4", [("class", "pfas-hier-card-t")], _esc(row.label)) +
            _tag("p", [("class", "pfas-hier-card-cap")], _esc(MIDDOT.join(caption)) + state))
    body = _tag("div", [("class", "pfas-hier-tiles")], "".join(tiles))
    if off:
        body += _tag("p", [("class", "pfas-hier-note")],
                     _esc(STD_OFF_NOTE.format(judged["sur_label"] if sur else judged["is_label"])))
    natives = (row.data or {}).get("quantifies") or []
    held = (row.data or {}).get("held-by") or []
    if quant is not None and sur:
        # what the surrogate corrects, shown here and edited where it is
        # stored: the Analytes tab's Quantified by
        body += _corrects(natives, [k for k, _h in (quant.links or []) if k not in natives])
    elif quant is not None:
        body += _chips_block("Quantifies", [k for k, _h in (quant.links or [])], QUANTIFIES_NOTHING + ".")
    for cname, cnatives in judged.get("held", {}).get(key, []):
        # a member of a composite: what the composite corrects is its too
        body += _tag("p", [("class", "pfas-hier-note"), ("data-std-also", True)],
                     _esc(ALSO_IN.format(cname, ", ".join(cnatives) if cnatives else CHAIN_NOTHING)))
    body += _std_standard_blocks(row, profile)
    parent = STD_GROUP_KEY.format(row.group) if row.group in STD_GROUP_TITLES else None
    # no Edit button: a tile opens the row's drawer; Remove in the menu only
    triggers = [card_act("edit", _edit_std_words(row), [("data-std-act", "edit"), ("data-std-row", key)])]
    if quant is not None and sur:
        triggers.append(card_act("analytes", EDIT_ON_ANALYTES,
                                 [quantified_by("{0}: {1}".format(QUANTIFIED_BY_TITLE, row.label), natives)]))
    if menu and sheet.remover:
        triggers.append(card_act("remove", REMOVE_STD_WORDS, [("data-std-act", "remove"), ("data-std-row", key),
                                                              ("disabled", True if natives or held else None),
                                                              ("title", remove_refused(natives, held)
                                                               if natives or held else None)], danger=True))
    if natives or held:
        body += _tag("p", [("class", "pfas-hier-note")], _esc(remove_refused(natives, held)))
    if limits:
        body += _tag("p", [("class", "pfas-hier-note"), ("data-std-footnote", True),
                           ("hidden", None if any(class_state(cells[c.key]) == "none" for c in sheet.columns
                                                  if c.key.startswith("eis-") and c.key != "eis-aq"
                                                  and c.key in cells) else True)],
                     "<sup>1</sup> " + _esc(STD_NONE_NOTE))
    body += card_acts(*triggers) + (actions_row(_back_button(row.group)) if parent else "")
    card = _tag("section", [("class", _cls("pfas-hier-card", "is-muted" if off else None)),
                            ("data-hier-card", key), ("data-std-row", key), ("data-hier-parent", parent),
                            ("aria-label", row.label), ("hidden", None if first else True)] + mute +
                tile_opens("edit", ["edit", "remove"]), head + body)
    return node, dots, card, mini


STD_SALT_LABEL = "Salt factor"
STD_SALT_NOTE = ("Converts the stated spiked concentration to the acid form before the response ratio "
                 "is formed.")


def _std_standard_blocks(row, profile):
    """A surrogate's or internal standard's own Transitions block (the
    analyte card's) and its Salt factor tile, the value its grid
    row holds (the row's drawer edits it); "" for limits no standard takes."""
    salt = (row.cells or {}).get("salt")
    if salt is None:
        return ""
    value = _text(salt.value).strip()
    tile = _tile(STD_SALT_LABEL, value or NOT_SET_WORDS, note=STD_SALT_NOTE, attrs=[("data-std-col", "salt")])
    return transitions_block(profile, row.key) + _tag("div", [("class", "pfas-hier-tiles")], tile)


INTG_ACT = "intg"


def _back_button(gkey):
    """The way back from a standard's card to its group's card."""
    return _list_button(BACK_WORDS.format(STD_GROUP_TITLES[gkey]), [("data-std-open", STD_GROUP_KEY.format(gkey))])


def _is_quantifies(chain, is_key):
    """An internal standard's mini-card words: the standards whose Linked to
    names it and the analytes it quantifies itself, counted."""
    for key, own, kids in chain:
        if key == is_key:
            linked = len([k for k in kids if len(k) == 2])
            parts = ([counted(linked, "surrogate")] if linked else []) + ([counted(len(own), "analyte")] if own else [])
            return IS_QUANTIFIES.format(" and ".join(parts)) if parts else QUANTIFIES_NOTHING
    return QUANTIFIES_NOTHING


def standards_rules_table(profile, env=None):
    """The rules the Isotope standards tab holds (STANDARD_RULES: IS
    Response, IS response vs. the most recent CCV, Surrogate Recovery), one
    row each in the library's order, each drawn whatever its state: an Off
    rule greys its group, never hides it. Its state posts
    rulestate.<key> to section-standards, as QC criteria's rows post theirs
    (an inherited state posts blank, so an untouched tab writes nothing).
    The Table view's rules block; the list's group cards write it."""
    from senaite.pfas import limit_placard, limit_states
    columns = [Column("scope", "Scope", "text"), Column("limits", "Effective limits", "text")]
    boxes = [b["key"] for k in STANDARD_RULES for b in limit_states.boxes_of(k)]
    hidden = [Cell(v, name=n, data={"kind": "rule"}) for n, v in limit_placard.hidden_values(profile or {}, boxes)]
    rows = _library_rows(profile or {}, STANDARD_RULES)
    _tail_applies(rows, profile)
    return Sheet(STD_RULES_ID, columns, rows, selection=False, picker=False, form=STANDARDS_FORM, hidden=hidden)


def std_rule_windows(profile, env=None):
    """{rule key: {names: (lo, hi) input names, pair: (lo, hi) as the inputs
    hold them, default: the window a blank pair is judged by (the method
    text's surrogate window) or None, per_class}} for the three rules the
    Isotope standards tab holds. The IS rules' windows are section cal_is's
    fields; the surrogate window is the one the grid posts where the Engine
    does not judge standards per matrix class, else none (per_class)."""
    cf, mps, _pf, _iso, _ls = _tab_modules()
    profile = profile or {}
    held = cf.current(mps.SECTIONS["cal_is"], profile)
    names = dict((f.path[1], f.name) for f in mps.SECTIONS["cal_is"].fields())
    out = {}
    for key, ends in IS_RULE_FIELDS.items():
        pair = tuple(names[e] for e in ends)
        out[key] = {"names": pair, "pair": tuple(_text(held.get(n)) if held.get(n) is not None else ""
                                                 for n in pair),
                    "default": None, "per_class": False}
    if window_in_grid(profile):
        cell, posted = _window_cell(cf, mps, profile, env)
        out["surrogate_recovery"] = {"names": tuple(c.name for c in posted),
                                     "pair": tuple(_text(c.value) for c in posted),
                                     "default": cell.value if cell.state == "inherited" else None,
                                     "per_class": False}
    else:
        out["surrogate_recovery"] = {"names": None, "pair": None, "default": None, "per_class": True}
    return out


def _rule_window_words(w):
    """A rule's window in words: as set, else its default, else Not set;
    per standard and matrix class where the Engine judges so."""
    if w["per_class"]:
        return PER_CLASS_WORDS
    if any(v not in (None, "") for v in w["pair"]):
        return _window_text(w["pair"])
    return _window_text(w["default"]) if w["default"] else NOT_SET_WORDS


def _rule_window_ends(w):
    if w["per_class"]:
        return None
    return _pair_ends(w["pair"]) or (_pair_ends(w["default"]) if w["default"] else None)


def _rule_win_attrs(key, w):
    """What the page redraws a rule's window from: its two inputs by name,
    and the default a blank pair reads."""
    if w["per_class"]:
        return [("data-rule-win", key)]
    dflt = _pair(w["default"]) if w["default"] else ("", "")
    return [("data-rule-win", key), ("data-lo-name", w["names"][0]), ("data-hi-name", w["names"][1]),
            ("data-default-lo", _g(dflt[0]) if dflt[0] not in (None, "") else None),
            ("data-default-hi", _g(dflt[1]) if dflt[1] not in (None, "") else None)]


def _rule_band(key, w):
    ends = _rule_window_ends(w)
    return _band(ends or (0, 0), attrs=[("data-rule-band", key), ("hidden", None if ends else True)])


def _rule_tile(label, key, w, note="", attrs=(), cls=None):
    """A tile of a rule's window: its words and its bar, and its note with
    "Method default" while a blank pair reads the default; the page redraws
    all three from the rule's inputs."""
    default = w["default"] and not any(v not in (None, "") for v in w["pair"] or ())
    said = _engine_words()["default"]
    return _tag("div", [("class", _cls("pfas-hier-tile", cls))] + list(attrs),
                _tag("span", [("class", "pfas-hier-tile-l")], _esc(label)) +
                _tag("span", [("class", "pfas-hier-tile-v")] + _rule_win_attrs(key, w), _esc(_rule_window_words(w))) +
                ("" if w["per_class"] else _rule_band(key, w)) +
                _tag("span", [("class", "pfas-hier-tile-s"), ("data-rule-note", key), ("data-note", note or None),
                              ("data-default-words", said if w["default"] else None)],
                     _esc(MIDDOT.join(x for x in (note, said if default else "") if x))))


def _rule_mute(cell, name):
    """Greyed while the rule's posted state is Off (data-mute-if), an
    inherited Off included; never hidden."""
    attrs = [("data-mute-if", name), ("data-mute-values", "off")]
    if cell.state == "inherited" and _text(cell.value) == "off":
        attrs.append(("data-mute-blank", "1"))
    return attrs


def _setting(label, f):
    """One setting of a drawn field (config_forms.render) as its card tile
    reads it: a switch Yes or No, a choice its option's words (a blank
    choice too), a window its ends with a bar, words as typed, else Not
    set; with the posted inputs it reads by name, both ends of a pair."""
    kind = f["kind"]
    pair = f.get("pair")
    s = {"label": label, "kind": kind, "names": [f["name"]], "labels": [label], "choices": None,
         "ends": None, "note": "", "unit": _text(f.get("unit"))}
    if pair:
        ends = (_text(f.get("value")), _text(pair.get("value")))
        s.update(label=f.get("pair_label") or label, kind="pair", names=[f["name"], pair["name"]],
                 labels=[f["label"], pair["label"]], words=_window_text(ends), ends=_pair_ends(ends),
                 note=_text(pair.get("help") or ""))
    elif kind == "bool":
        s["words"] = YES_WORDS if f.get("checked") else NO_WORDS
    elif kind == "choice":
        s["choices"] = [[_text(v), _text(l)] for v, l in f.get("choices") or ()]
        s["words"] = _label_of(f.get("choices"), f.get("value")) or NOT_SET_WORDS
    else:
        v = _text(f.get("value")).strip()
        s["words"] = ("{0} {1}".format(v, s["unit"]) if v and s["unit"] and PLAIN_NUMBER.match(v) else v) \
            or NOT_SET_WORDS
    return s


def std_settings(profile, env=None, groups_of=None):
    """{group key: [(heading, [setting])]}: the tab's other settings each
    group's card shows (STD_SETTINGS), one per field of each section as its
    fold draws it, a pair as one, a table (the flag notes) a cell each under
    its row's label. `groups_of(sid)`: the section as drawn (the view's
    section_groups), else rendered here."""
    cf, mps, _pf, _iso, _ls = _tab_modules()
    profile = profile or {}
    if groups_of is None:
        def groups_of(sid):
            return fold_groups(sid, cf.render(mps.SECTIONS[sid], profile, env or {}), profile)
    out = {}
    for gkey, heads in STD_SETTINGS.items():
        blocks = []
        for head, sids in heads:
            items = []
            for sid in sids:
                for g in groups_of(sid):
                    if "rows" in g:
                        for r in g["rows"]:
                            many = len(r["cells"]) > 1
                            items += [_setting(r["label"] + (" " + c["label"] if many else ""), c)
                                      for c in r["cells"]]
                    else:
                        items += [_setting(f["label"], f) for f in g["shown"]]
            if items:
                blocks.append((head, items))
        out[gkey] = blocks
    return out


def _setting_tile(s, form=None, attrs=(), cls=None):
    """A setting's tile, naming the inputs the page redraws it from and the
    drawer edits (data-set-names), each input's label, its kind and, for a
    choice, its options' words; `form` the form those inputs post to where
    it is not Isotope standards' (data-set-form)."""
    extra = list(attrs)
    attrs = [("data-set-names", json.dumps(s["names"])), ("data-set-form", form), ("data-set-kind", s["kind"]),
             ("data-set-labels", json.dumps(s["labels"])),
             ("data-set-choices", json.dumps(s["choices"]) if s["choices"] is not None else None),
             # a setting another one fixes: its words while that one holds the value
             ("data-set-fixed", json.dumps(s["fixed"]) if s.get("fixed") else None),
             ("data-set-unit", s["unit"] if s["kind"] not in ("pair", "bool", "choice") and s["unit"] else None)]
    band = _band(s["ends"] or (0, 0), attrs=[("data-set-band", True), ("hidden", None if s["ends"] else True)]) \
        if s["kind"] == "pair" else ""
    return _tile(s["label"], s["words"], band, note=s["note"], attrs=attrs + extra, cls=cls)


def value_switch(input_id, value, on, off, label, word_on="On", word_off="Off"):
    """The house switch for a choice field of two values: a nameless box
    (it names no form, so it never posts) writing the field `input_id`
    (`on` or `off`, PFAS.components), its word beside it; it acts at once."""
    checked = _text(value) == on
    box = _tag("input", [("type", "checkbox"), ("form", NO_FORM), ("data-switch-input", input_id),
                         ("data-switch-on", on), ("data-switch-off", off), ("aria-label", label),
                         ("data-word-on", word_on), ("data-word-off", word_off), ("checked", True if checked else None)])
    return _tag("label", [("class", "pfas-switch pfas-hier-switch")],
                box + _tag("span", [("class", "pfas-switch-track"), ("aria-hidden", "true")], "") +
                _tag("span", [("class", "pfas-switch-word")], _esc(word_on if checked else word_off)))


def _eq_text(formula):
    """An equation's plain text, what the page reads without the script:
    "_{x}" as a subscript."""
    return re.sub(r"_\{([^}]*)\}", r"<sub>\1</sub>", _esc(formula))


def _eq_inline(formulas, rows, attrs=(), stack=False):
    """The shared equation's inline size (.pv-formula.is-inline): the plain
    text, drawn over by the component from data-equation, each term of
    `rows` (as RATIO_TERMS) in the colour its window gives it; `stack` one
    equation under another."""
    spec = {"formulas": list(formulas), "terms": [{"symbol": r[0]} for r in rows]}
    lines = "".join(_tag("span", [("class", "pv-formula-line")], _eq_text(f)) for f in formulas)
    return _tag("div", [("class", _cls("pv-formula", "is-inline", "is-stack" if stack else None)),
                        ("data-equation", json.dumps(spec, sort_keys=True))] + list(attrs), lines)


def _eq_terms(rows, labels):
    """The window's terms from (symbol, means, source, the options it is
    used in), each option named by its label."""
    return [{"symbol": sym, "label": means, "source": source, "in": [labels[v] for v in used]}
            for sym, means, source, used in rows]


def equation_window(title, input_name, options, equations, terms, notes=None, default=None,
                    steps=(), foot=""):
    """What [data-equation-open] holds: the window's title, the posted input
    whose value is the option in use when it opens, each option (value,
    label, its note, its equations, whether it is the default) side by side,
    every term, the steps after, and the line under it."""
    labels = dict(options)
    return {"title": title, "input": input_name,
            "options": [{"value": v, "label": l, "note": (notes or {}).get(v, ""),
                         "formulas": list(equations[v]), "isDefault": v == default} for v, l in options],
            "terms": _eq_terms(terms, labels), "steps": list(steps), "foot": foot}


def _corr_block(judged):
    """The Internal standards card's "How results are corrected": what an
    analyte's Quantified by decides, read only; then the response ratio
    linked to the injection standard, the one choice, over the equation the
    chosen option uses (the other drawn hidden, shown as the choice
    changes), and its help line. Greyed, still editable, while no analyte
    is quantified on a surrogate."""
    from senaite.pfas import method_profile_sections as mps
    ratio = judged["ratio"]
    # what Quantified by decides: edited on Analytes, where a click goes
    lines = "".join(_tile(label, words, note=CORR_LINES_NOTE, attrs=tile_opens("analytes")) for label, words in CORR_LINES)
    eqs = "".join(_eq_inline(RATIO_EQUATIONS[v], RATIO_TERMS,
                             [("data-ratio-eq", v), ("data-show-if", ratio["name"]), ("data-show-values", v),
                              ("hidden", None if v == ratio["value"] else True)], stack=True)
                  for v in ("off", "on"))
    window = equation_window(RATIO_LABEL, ratio["name"], mps.LINKED_RATIOS, RATIO_EQUATIONS, RATIO_TERMS,
                             notes=RATIO_NOTES, default=mps.LINKED_RATIO_DEFAULT, steps=[CURVE_STEP],
                             foot=RATIO_FOOT)
    unused = not judged["on_surrogate"]
    # the whole box opens both calculations in the shared window; its
    # switch acts at once and opens nothing
    tile = _tag("div", [("class", _cls("pfas-hier-tile", "pfas-hier-amount", "is-muted" if unused else None)),
                        ("data-std-ratio", True), ("data-equation-open", json.dumps(window, sort_keys=True))],
                _tag("span", [("class", "pfas-hier-tile-l")], _esc(RATIO_LABEL)) +
                value_switch(ratio["name"], ratio["value"], "on", "off", RATIO_LABEL) + eqs +
                # the help line for the state the switch is in, the other hidden
                "".join(_tag("span", [("class", "pfas-hier-tile-s"), ("data-show-if", ratio["name"]),
                                      ("data-show-value", v), ("hidden", None if v == ratio["value"] else True)],
                             _esc(ratio["help"][v])) for v, _l in mps.LINKED_RATIOS if v in ratio["help"]) +
                (_tag("span", [("class", "pfas-hier-tile-s")], _esc(RATIO_UNUSED)) if unused else ""))
    return (_tag("h5", [("class", "pfas-hier-h")], _esc(CORR_HEAD)) +
            _tag("div", [("class", "pfas-hier-tiles"), ("data-std-corr", True)], lines + tile))


def _boxed_setting(s, profile):
    """A setting's tile; one that is a limit box (the surrogates' window in
    CCVs) with its placard, an empty one saying the window it uses."""
    from senaite.pfas import limit_placard
    tile = _setting_tile(s)
    box = limit_placard.box_of_names(s["names"])
    return limit_placard.boxed(tile, profile, box, limit_placard.uses_words(box)) if box else tile


def _std_group_entry(gkey, members, rule_sheet, windows, profile, judged, first):
    """(node, card) of one standards group (Surrogates, Internal standards):
    the node carries its rules, each with its state and its window as a bar
    (on EPA 1633A-like Engines, per standard and matrix class); both cards
    are drawn alike: title and count, each rule's state (nameless segments
    writing the rules block's inputs), its windows, the Settings (the
    Internal standards': how results are corrected), Links (the internal
    standards' chain), each rule's Flag tile, the actions, then the group's standards
    as mini-cards, each opening its own card. Greyed while its first rule is
    Off, never hidden."""
    rules, _qct = _qc_modules()
    keys = dict(STANDARD_RULE_GROUPS)[gkey]
    rows = [r for r in rule_sheet.rows if r.key in keys]
    title = STD_GROUP_TITLES[gkey]
    key = STD_GROUP_KEY.format(gkey)
    primary = next(r for r in rule_sheet.rows if r.key == STD_GROUP_PRIMARY[gkey])
    pstate = primary.cells["state"]
    off = _text(pstate.value) == "off"
    # no state segments: each window is its own limit box with its placard
    # (limit_placard), greying itself while Off
    from senaite.pfas import limit_placard
    # the group greys while its first rule's box is Off (that box's input)
    mute = [("data-mute-if", limit_placard.input_name(primary.key)), ("data-mute-values", "off")]
    lines, states, tiles = [], [], []
    for r in rows:
        cell = r.cells["state"]
        name = _state_name(r, cell)
        dom_id = _dom_id(rule_sheet, name)
        w = windows[r.key]
        # a rule's line greys while its window's box is Off
        rmute = [("data-mute-if", limit_placard.input_name(r.key)), ("data-mute-values", "off")]
        roff = _text(cell.value) == "off"
        line = state_glyph(cell, dom_id, r.key, profile)
        lines.append(_tag("span", [("class", _cls("pfas-hier-rule", "is-muted" if roff else None))] + rmute,
                          _tag("span", [("class", "pfas-hier-rule-l")], _esc(r.label) + line) +
                          _tag("span", [("class", "pfas-hier-node-v")] + _rule_win_attrs(r.key, w),
                               _esc(_rule_window_words(w))) +
                          ("" if w["per_class"] else _rule_band(r.key, w))))
        note = (PER_CLASS_NOTE if w["per_class"] else
                IS_RULE_CAPTIONS.get(r.key) or WINDOW_NOTE)
        tiles.append(limit_placard.boxed(_rule_tile(r.label, r.key, w, note), profile, r.key))
    node = _tag("button", [("type", "button"),
                           ("class", _cls("pfas-hier-node", "is-group", "is-selected" if first else None,
                                          "is-muted" if off else None)),
                           ("data-hier-target", key), ("aria-pressed", "true" if first else "false"),
                           ("data-std-group", gkey)] + mute,
                _tag("span", [("class", "pfas-hier-node-t")], _esc(title)) +
                _tag("span", [("class", "pfas-hier-node-v")], _esc(counted(len(members), "standard"))) +
                "".join(lines))
    cap = [counted(len(members), "extracted standard" if gkey == "sur" else "injection standard")]
    # the caption ends with the group's first rule's state, following its input
    pid = _dom_id(rule_sheet, _state_name(primary, pstate))
    cap_state = _tag("span", [("data-state-of", pid),
                              ("data-inherited", _state_line(pstate) if pstate.state == "inherited" else None)],
                     _esc(_state_line(pstate)))
    editable = any(not windows[r.key]["per_class"] for r in rows)
    # the tab's other settings of the group, each section's under its heading;
    # the Internal standards' first: how results are corrected
    blocks = judged["settings"].get(gkey) or []

    def block(head, items):
        if head == CORR_HEAD:
            return _corr_block(judged)
        return (_tag("h5", [("class", "pfas-hier-h")], _esc(head)) +
                _tag("div", [("class", "pfas-hier-tiles"), ("data-std-settings-of", gkey)] + tile_opens("settings"),
                     "".join(_boxed_setting(s, profile) for s in items)))
    # both groups drawn alike: Settings, then Links (the internal
    # standards' chain), then each rule's Flag tile
    settings = "".join(block(h, i) for h, i in blocks)
    # a note several of the group's rules share: once, above their tiles
    shared_html, shared = shared_note_block(profile, [(r.key, r.label) for r in rows])
    notes = shared_html + "".join(render_flag_tile(r.key, profile, judged.get("env"), title=r.label,
                                                   named=len(rows) > 1, shared=r.key in shared)
                                  for r in rows)
    editable_settings = [b for b in blocks if b[0] != CORR_HEAD]
    # no Edit button: a limit tile opens the limits, a setting tile the settings
    triggers = card_acts(card_act("limits", EDIT_LIMITS_WORDS, [("data-std-limits", gkey)]) if editable else "",
                         card_act("settings", EDIT_SETTINGS_WORDS, [("data-std-settings", gkey)])
                         if editable_settings else "",
                         card_act("analytes", OPEN_ANALYTES_WORDS, [quantified_by(QUANTIFIED_BY_TITLE)])
                         if any(h == CORR_HEAD for h, _i in blocks) else "")
    buttons = ""
    if gkey == "sur":
        # two or more surrogates averaged into one standard (composite_standards)
        offer = judged["combine"]
        buttons += _list_button(COMBINE_WORDS, [("data-cmp-add", "1"),
                                                ("data-cmp-offer", json.dumps(offer["offer"])),
                                                ("data-cmp-id-name", offer["id_name"]),
                                                ("data-cmp-members-name", offer["members_name"]),
                                                ("data-cmp-next", "%d" % offer["next"]),
                                                ("data-cmp-title-words", COMBINE_TITLE)])
    acts = actions_row(buttons)
    minis = [m for m in judged["minis"] if m[0] in [r.key for r in members]]
    if gkey == "sur":
        minis += [(e["id"], e["mini"]) for e in judged["composites"]]
    # the internal standards' card draws the chain down to the analytes
    chain = _render_chain(judged["chain"], profile) if gkey == "is" else ""
    body = (_tag("h5", [("class", "pfas-hier-h")], _esc(STD_LIMITS_HEAD)) +
            _tag("div", [("class", "pfas-hier-tiles")] + (tile_opens("limits") if editable else TILE_READ),
                 "".join(tiles)) + settings + chain + notes +
            _tag("p", [("class", "pfas-hier-note mp-qc-off-note")],
                 _esc(STD_OFF_NOTE.format(primary.label) + " Its limits are kept and still editable.")) +
            _tag("h5", [("class", "pfas-hier-h")], STD_MINIS_HEAD) +
            (_tag("div", [("class", "pfas-hier-minis")], "".join(m[1] for m in minis)) if minis else
             _tag("p", [("class", "pfas-hier-empty")], _esc(STD_NO_MEMBERS[gkey]))) +
            triggers + acts)
    card = _tag("section", [("class", _cls("pfas-hier-card", "is-group", "is-muted" if off else None)),
                            ("data-hier-card", key), ("data-std-group", gkey), ("aria-label", title),
                            ("hidden", None if first else True)] + mute,
                _tag("h4", [("class", "pfas-hier-card-t")], _esc(title)) +
                _tag("p", [("class", "pfas-hier-card-cap")], _esc(MIDDOT.join(cap) + MIDDOT) + cap_state) +
                applies_lines([(r.key, r.label, row_is_off(r)) for r in rows], profile) + body)
    return node, card


def render_dilution_recovery(profile, env=None, mirror=False):
    """The Analytes tab's Surrogate recovery in a dilution: its posted input
    (posting to section-analytes, counted by the tab's unsaved guard) drawn
    as a segment, the chosen option's equation under it (the others hidden,
    shown as the choice changes), "Not set" while nothing is chosen, and
    the help line. Greyed, still editable, while the response ratio is not
    linked to the injection standard (the worker reads it only then).
    `mirror`: the same tile without the input, its segment writing the one
    input the List's card holds (data-input), so the Table view shows and
    sets it too and it posts once."""
    cf, mps, _pf, _iso, _ls = _tab_modules()
    profile = profile or {}
    f = [x for g in cf.render(mps.DILUTION_RECOVERY, profile, env or {}) for x in g["fields"]][0]
    value = mps.dilution_recovery(profile)
    name = f["name"]
    real = _tag("input", [("type", "hidden"), ("id", name), ("name", name), ("form", "section-analytes"),
                          ("data-kind", f["counts_as"]), ("value", value)], None)
    items = "".join(_tag("button", [("type", "button"), ("class", "pfas-seg-item"), ("data-value", v),
                                    ("aria-pressed", "true" if v == value else "false")], _esc(l))
                    for v, l in mps.DILUTION_RECOVERIES)
    seg = _tag("div", [("class", "pfas-seg pfas-seg-sm is-fit"), ("role", "group"), ("data-field", True),
                       ("data-quiet", True), ("data-input", name), ("aria-label", f["label"])], items)
    eqs = "".join(_eq_inline([DILREC_EQUATIONS[v]], DILREC_TERMS,
                             [("data-dilrec-eq", v), ("data-show-if", name), ("data-show-values", v),
                              ("hidden", None if v == value else True)])
                  for v, _l in mps.DILUTION_RECOVERIES)
    window = equation_window(f["label"], name, mps.DILUTION_RECOVERIES,
                             dict((k, [e]) for k, e in DILREC_EQUATIONS.items()), DILREC_TERMS,
                             foot=DILREC_FOOT)
    unset = _tag("p", [("class", "pfas-hier-note"), ("data-dilrec-unset", True), ("data-show-if", name),
                       ("data-show-value", ""), ("hidden", True if value else None)], _esc(DILREC_UNSET))
    unused = mps.linked_response_ratio(profile) != "on"
    return _tag("div", [("class", _cls("pfas-hier-tile", "pfas-hier-amount", "is-muted" if unused else None)),
                        ("data-dilrec", True), ("data-equation-open", json.dumps(window, sort_keys=True))],
                ("" if mirror else real) + _tag("span", [("class", "pfas-hier-tile-l")], _esc(f["label"])) +
                seg + eqs + unset +
                _tag("span", [("class", "pfas-hier-tile-s")], _esc(f["help"])))


def analytes_table_settings(profile, env=None):
    """The Analytes tab's Method settings under its Table view, as the List
    has them: the heading with the group's one help ? and the Surrogate
    recovery in a diluted sample tile, a nameless mirror of the List's
    (render_dilution_recovery, mirror): anything the List shows, the Table
    shows. The analyte set's state is the line above the sheet."""
    return _tag("div", [("class", "mp-an-settings")],
                group_head(AN_SETTINGS_HEAD, help_dictionary.SECTION_HELP["dilrec"]) +
                _tag("div", [("class", "pfas-hier-tiles")], render_dilution_recovery(profile, env, mirror=True)))


def _link_warning(head, note, items):
    """The tab's warning naming each link its Save requires (house warning
    banner): a chip per standard or analyte, each naming the input that
    holds its link (data-needs), so the page drops it once that input holds
    one (data-needs-one-of: one of those values); "" while nothing is
    missing."""
    if not items:
        return ""
    chips = "".join(_tag("span", [("class", "pfas-hier-chip"), ("data-needs", it[1]),
                                  ("data-needs-one-of", json.dumps(it[2]) if len(it) > 2 else None)], _esc(it[0]))
                    for it in items)
    return _tag("div", [("class", "pfas-banner is-warn"), ("role", "status"), ("data-link-warn", True)],
                _tag("span", [], icons.svg("warn", hidden=True) + ' ' +
                     _tag("strong", [], _esc(head) + ".") + " " + _esc(note)) +
                _tag("span", [("class", "pfas-hier-chips")], chips))


def standards_link_warning(profile):
    """The Isotope standards tab's warning: each Used surrogate with no
    Linked to, or linked to a surrogate or a composite
    (method_profile_sections.unlinked_surrogates, misdirected_surrogates),
    by the grid row's Linked to input, which must name an internal standard."""
    cf, mps, _pf, _iso, _ls = _tab_modules()
    profile = profile or {}
    iss = _ls.injection(profile)
    bad = sorted(set(mps.unlinked_surrogates(profile)) | set(k for k, _r, _w in mps.misdirected_surrogates(profile)))
    return _link_warning(UNLINKED_SUR_HEAD, UNLINKED_SUR_NOTE,
                         [(kw, _named(cf, mps.LABELLED_STANDARDS, profile, (kw,), "reference"), iss)
                          for kw in bad])


def analytes_link_warning(profile):
    """The Analytes tab's warning: each analyte reported in a matrix with no
    Quantified by (method_profile_sections.unquantified_analytes), by the
    grid row's Quantified by input."""
    cf, mps, _pf, _iso, _ls = _tab_modules()
    profile = profile or {}
    return _link_warning(UNQUANTIFIED_HEAD, UNQUANTIFIED_NOTE,
                         [(kw, _named(cf, mps.SURROGATE_MAP, profile, (kw,), "surrogate_is"))
                          for kw in mps.unquantified_analytes(profile)])


def _cmp_is(profile, value):
    from senaite.pfas import composite_standards as cmp
    return cmp.is_composite(profile, value)


def std_composites(profile):
    """[{"id", "name", "members", "natives", "reference"}] for each of the
    method's composites in drawn order (composite_standards): its members
    and its link read from the grid, what it corrects from the Analytes
    tab's Quantified by."""
    from senaite.pfas import composite_standards as cmp
    return [{"id": cid, "name": cmp.name(profile, cid), "members": cmp.members(profile, cid),
             "natives": cmp.natives_of(profile, cid), "reference": cmp.reference(profile, cid)}
            for cid in cmp.ordered(profile)]


def combine_offer(profile):
    """What the Combine window offers: [[keyword, linked to]] for each
    surrogate of the method's grid, by keyword; and the posted names of a
    composite's id and members ("{i}" standing for its row's index), with
    the index the next one takes."""
    _cf, mps, _pf, _iso, ls = _tab_modules()
    cf = _cf
    grid = ls.grid(profile)
    offer = [[kw, (grid[kw] or {}).get("reference") or ""] for kw in sorted(grid)
             if (grid[kw] or {}).get("role") == "surrogate"]
    coll = mps.COMPOSITES
    names = dict((f.path[0], cf.collection_name(coll, "{i}", f)) for f in coll.columns)
    return {"offer": offer, "id_name": names["id"], "members_name": names["members"],
            "next": len(mps.read_composites(profile))}


def _cmp_caption(c):
    linked = CMP_LINKED.format(c["reference"]) if c["reference"] else CMP_UNLINKED
    return MIDDOT.join([CMP_CAPTION, counted(len(c["members"]), "member"), linked])


def _cmp_entry(c, index, off):
    """(node, card, mini) of one composite: its name built from its members,
    the members as buttons opening their own cards, what it corrects, read
    only (edited on Analytes), Edit members and Remove composite, refused
    while it corrects an analyte."""
    key = c["id"]
    sub = (CMP_LINKED.format(c["reference"]) if c["reference"] else CMP_UNLINKED)
    node = _tag("button", [("type", "button"),
                           ("class", _cls("pfas-hier-node", "is-sub", "is-muted" if off else None)),
                           ("data-hier-target", key), ("aria-pressed", "false"), ("data-cmp-row", key)],
                _tag("span", [("class", "pfas-hier-node-t"), ("data-cmp-title", True)], _esc(c["name"])) +
                _tag("span", [("class", "pfas-hier-node-v"), ("data-cmp-count", True)],
                     _esc(counted(len(c["members"]), "member"))) +
                _tag("span", [("class", "pfas-hier-node-s")], _esc(CMP_CAPTION + MIDDOT + sub)))
    mini = _tag("button", [("type", "button"), ("class", _cls("pfas-hier-mini", "is-muted" if off else None)),
                           ("data-std-open", key), ("data-cmp-mini", key), ("aria-label", "Show " + _text(c["name"]))],
                _tag("span", [("class", "pfas-hier-mini-t"), ("data-cmp-title", True)], _esc(c["name"])) +
                _tag("span", [("class", "pfas-hier-mini-s")], _esc(CMP_CAPTION)))
    chips = "".join(_tag("button", [("type", "button"), ("class", "pfas-hier-chip"), ("data-std-open", m),
                                    ("aria-label", "Show " + _text(m))], _esc(m)) for m in c["members"])
    natives = c["natives"]
    # no Edit button: a tile opens Edit members; Remove in the menu only
    acts = card_acts(card_act("edit", CMP_EDIT_WORDS, [("data-cmp-act", "edit"), ("data-cmp-row", key)]),
                     card_act("analytes", EDIT_ON_ANALYTES,
                              [quantified_by("{0}: {1}".format(QUANTIFIED_BY_TITLE, c["name"]), natives)]),
                     card_act("remove", CMP_REMOVE_WORDS, [("data-cmp-act", "remove"), ("data-cmp-row", key),
                                                           ("disabled", True if natives else None),
                                                           ("title", remove_refused(natives) if natives else None)],
                              danger=True))
    body = (_tag("div", [("class", "pfas-hier-tiles")],
                 _tile(CMP_AVERAGED_LABEL, cmp_averaged_words(), attrs=TILE_READ) +
                 _tile("Linked to", c["reference"] or NOT_LINKED)) +
            _tag("h5", [("class", "pfas-hier-h")], _esc(CMP_MEMBERS_HEAD)) +
            _tag("span", [("class", "pfas-hier-chips"), ("data-cmp-members", True)], chips) +
            _tag("div", [("class", "pfas-hier-tilebox"), ("aria-label", CORRECTS_HEAD)] + tile_opens("analytes"),
                 _chips_block(CORRECTS_HEAD, natives, CORRECTS_NOTHING)) +
            _tag("p", [("class", "pfas-hier-note")], _esc(CMP_NOTE)) +
            (_tag("p", [("class", "pfas-hier-note")], _esc(remove_refused(natives))) if natives else "") +
            acts + actions_row(_back_button(STANDARD_GROUPS[0][0])))
    card = _tag("section", [("class", _cls("pfas-hier-card", "is-muted" if off else None)),
                            ("data-hier-card", key), ("data-hier-parent", STD_GROUP_KEY.format(STANDARD_GROUPS[0][0])),
                            ("data-cmp-of", key), ("data-cmp-index", "%d" % index),
                            ("data-cmp-members-of", ", ".join(c["members"])),
                            ("aria-label", c["name"]), ("hidden", True)] + tile_opens("edit", ["edit", "remove"]),
                _tag("h4", [("class", "pfas-hier-card-t"), ("data-cmp-title", True)], _esc(c["name"])) +
                _tag("p", [("class", "pfas-hier-card-cap"), ("data-cmp-cap", True)], _esc(_cmp_caption(c))) + body)
    return node, card, mini


def cmp_averaged_words():
    from senaite.pfas import composite_standards as cmp
    return cmp.AVERAGED_WORDS["area"]


def _engine_words():
    from senaite.pfas import method_engine
    return {"guidance": method_engine.GUIDANCE_WORDS, "default": method_engine.METHOD_DEFAULT_WORDS}


def render_standards_list(profile, env=None, sheet=None, rule_sheet=None, groups_of=None):
    """The Isotope standards tab's List view: <div id="standards-list">, one
    list: the two groups' nodes, Surrogates and Internal standards (and any
    limits no standard takes, each a node of its own). Drawn from the sheet
    it mirrors; it posts nothing: the grid, the rules block and the sections
    under them (the Table view) hold every input, and the card's buttons and
    the mini-card's menu act through the grid's own row drawer, menu and
    forms. Each group's node carries its rules (standards_rules_table) with
    their states and windows; its card lists its standards as mini-cards,
    each opening that standard's card (data-hier-parent: the group's node
    stays chosen; Back returns to the group's card). Where the
    Engine judges standards per matrix class, a SUR's card draws its Aqueous
    and per-class limits as bars; else every SUR's card shows the method's
    one surrogate window. Each group's card also shows the tab's other
    settings of the group (std_settings; `groups_of` the sections as the
    page draws them), which Edit settings edits."""
    _cf, mps, _pf, _iso, _ls = _tab_modules()
    rules, _qct = _qc_modules()
    profile = profile or {}
    sheet = sheet or standards_sheet(profile, env)
    rule_sheet = rule_sheet or standards_rules_table(profile, env)
    mid = profile.get("method_id")
    states = dict((r.key, r.cells["state"]) for r in rule_sheet.rows)
    windows = std_rule_windows(profile, env)
    from senaite.pfas import limit_states
    judged = {"sur_off": limit_states.box_state(profile, "surrogate_recovery") == "off",
              "is_off": limit_states.box_state(profile, "is_response") == "off",
              "sur_label": _rule_label(rules, "surrogate_recovery"), "is_label": _rule_label(rules, "is_response"),
              "windows": windows,
              "mute": dict((g, [("data-mute-if", "limitstate." + STD_GROUP_PRIMARY[g]), ("data-mute-values", "off")])
                           for g, _k in STANDARD_RULE_GROUPS),
              "guidance": "surrogate_recovery" in mps._engine_module().guidance_only_rules(profile),
              "settings": std_settings(profile, env, groups_of),
              # the page's env: each rule's Flag tile reads the QC Qualifiers library from it
              "env": env,
              "chain": std_chain(sheet, profile, std_composites(profile)),
              "groups": [(g.key, g.label) if isinstance(g, Row) else (g[0], g[1]) for g in sheet.groups]}
    # the linked response ratio's posted input, and whether any analyte is
    # quantified on a surrogate (a composite averages surrogates)
    roles = _ls.roles(profile)
    field = mps.LINKED_RATIO.fields()[0]
    judged["ratio"] = {"name": field.name, "value": mps.linked_response_ratio(profile), "help": field.state_help}
    judged["on_surrogate"] = any(roles.get(r.get("surrogate_is")) == "surrogate" or
                                 _cmp_is(profile, r.get("surrogate_is")) for r in mps._map_rows(profile))
    composites = std_composites(profile)
    judged["held"] = {}
    for c in composites:
        for m in c["members"]:
            judged["held"].setdefault(m, []).append((c["name"], c["natives"]))
    judged["combine"] = combine_offer(profile)
    judged["composites"] = []
    for i, c in enumerate(composites):
        node, card, mini = _cmp_entry(c, i, judged["sur_off"])
        judged["composites"].append({"id": c["id"], "node": node, "card": card, "mini": mini})
    entries = OrderedDict()
    for r in sheet.rows:
        entries[r.key] = _std_entry(r, sheet, profile, judged, False)
    judged["minis"] = [(k, e[3]) for k, e in entries.items()]
    nodes, cards = [], []
    first = True
    for gkey, glabel in judged["groups"]:
        members = [r for r in sheet.rows if r.group == gkey]
        if gkey in STD_GROUP_TITLES:
            # the group's own node heads it, chosen first: no heading above it
            gnode, gcard = _std_group_entry(gkey, members, rule_sheet, windows, profile, judged, first)
            first = False
            nodes.append(gnode)
            cards.append(gcard)
        elif members:
            nodes.append(_tag("p", [("class", "pfas-hier-group")], _esc(glabel)))
        for r in members:
            node, dots, card, _mini = entries[r.key]
            if gkey not in STD_GROUP_TITLES:
                # limits no standard takes: a node of their own, no group card lists them
                nodes.append(node + dots)
            cards.append(card)
        if gkey == STANDARD_GROUPS[0][0]:
            # the composites' cards, opened from the Surrogates card's minis
            cards += [e["card"] for e in judged["composites"]]
    if sheet.adder and sheet.adder[5]:
        nodes.append(_tag("div", [("class", "pfas-hier-actions")],
                          _list_button(ADD_STD_WORDS, [("data-std-add", sheet.adder[2])])))
    if not cards:
        cards.append(_tag("p", [("class", "pfas-hier-empty")], "No isotope standard in the method yet."))
    # the list's one help ? above it at the top right, as the grid's tools row holds it
    head = _tag("div", [("class", "pfas-hier-help")], help_dictionary.help_button(sheet.help)) if sheet.help else ""
    return head + _tag("div", [("id", STD_LIST_ID), ("class", "pfas-hier"), ("data-hier", "standards")],
                       _tag("div", [("class", "pfas-hier-list"), ("role", "group"),
                                    ("aria-label", "Isotope standards")], "".join(nodes)) +
                       _tag("div", [("class", "pfas-hier-cards")], "".join(cards)))


# ── the Analytes tab as a list: each analyte beside its card ───────────────

AN_LIST_ID = "analytes-list"
# the list's groups: the method's own key analytes (the tiers' "Regulated
# analytes"), the rest of the panel, then the tab's method-wide settings
AN_GROUPS = (("key", "Regulated analytes"), ("other", "Other analytes"))
AN_GROUP_WORDS = {"key": "Regulated analyte", "other": "Other analyte"}
AN_SETTINGS_HEAD = "Method settings"
AN_DILREC = "an-dilrec"
AN_SET = "an-set"
AN_SET_TITLE = "Analyte set confirmation"
AN_SET_LABEL = "Lab confirmation"
AN_FLAGGED = "Flagged"
AN_FLAGGED_NOTE = ("Check the analyte set against the published method's target list, and which analytes "
                   "are reportable in each matrix, before production use.")
AN_CONFIRMED = "Confirmed"
AN_NOT_FLAGGED = "Not flagged"
AN_REPORTED = "Reported"
AN_LEFT_OUT = "Left out"
AN_LEFT_OUT_NOTE = "Left out of this matrix everywhere"
AN_NO_RL = "No RL"
AN_FROM_CAL = "From the lowest calibrator"
AN_MDL_NOT_SET = "MDL not set"
AN_SLOTS_ALL = "Reported in every matrix"
AN_SLOTS_OUT = "Left out of {0}"
# what a Quantified by is, by the standard's role (labelled_standards.roles)
# or a composite of surrogates
AN_QUANT_KINDS = {"surrogate": "A surrogate", "injection_is": "An internal standard",
                  "composite": "A composite of surrogates"}
AN_QUANT_TAIL = "; the chain is on Isotope standards"
AN_FLAG_LABEL = "Row flag"
AN_EDIT_WORDS = "Edit analyte"
AN_FLAG_NONE = "None"
AN_NO_QUANT = "No Quantified by"
AN_FLAG_NOTE = "Raised when an analyte has no Quantified by."
AN_ISO_HEAD = "Isomers and salt"
AN_NOT_SUMMED = "Not summed"
AN_TRANS_HEAD = "Transitions"
AN_TRANS_NOTE = "The same values as Run & reporting, Integration."
AN_INTG_WORDS = "Edit transitions"


def _an_unit(words, unit):
    return "{0} {1}".format(words, unit) if unit else _text(words)


def _an_matrix_tile(kw, i, matrix, unit, flag, rl, mdl):
    """One matrix of an analyte's card: reported or left out, the RL that
    applies there (typed; else the lowest calibrator's, so noted; else No RL),
    its MDL and what Save stores for either; greyed while its panel box is
    unticked (data-mute-if), never hidden. Names what the page redraws it
    from: the panel box (data-an-box), the RL and MDL inputs the flag names."""
    data = flag.data or {}
    on = bool(data.get("in"))
    typed = _text(data.get("rl")) if on else ""
    derived = _text(data.get("derived"))
    if not on:
        words, note = AN_LEFT_OUT, AN_LEFT_OUT_NOTE
    elif typed:
        words, note = "RL " + _an_unit(typed, unit), ""
    elif derived:
        words, note = "RL " + _an_unit(derived, unit), AN_FROM_CAL
    else:
        words, note = AN_NO_RL, ""
    mdl_value = _text(mdl.value) if mdl is not None and mdl.state != "inherited" else ""
    mdl_words = ("MDL " + _an_unit(mdl_value, unit)) if mdl_value else AN_MDL_NOT_SET

    def saves(cell, what, prefix):
        text = cell.saves_as if cell is not None and cell.state == "set" else None
        return _tag("span", [("class", "pfas-hier-tile-s"), ("data-an-saves", what),
                             ("data-an-saves-as", text), ("hidden", None if text and on else True)],
                    _esc(prefix + saves_as_words(text) if text else ""))
    return _tag("div", [("class", _cls("pfas-hier-tile", None if on else "is-muted")),
                        ("data-an-col", "panel-{0}".format(i)), ("data-an-of", kw), ("data-an-unit", unit or None),
                        ("data-an-box", flag.name), ("data-an-rl-name", data.get("rl_name") or None),
                        ("data-an-mdl-name", data.get("mdl_name") or None), ("data-an-derived", derived or None),
                        ("data-mute-if", flag.name), ("data-mute-blank", "1")],
                _tag("span", [("class", "pfas-hier-tile-l")], _esc(MIDDOT.join(w for w in (matrix, unit) if w))) +
                _tag("span", [("class", "pfas-hier-tile-s"), ("data-an-in", True)],
                     _esc(AN_REPORTED if on else AN_LEFT_OUT)) +
                _tag("span", [("class", "pfas-hier-tile-v"), ("data-an-rl", True)], _esc(words)) +
                _tag("span", [("class", "pfas-hier-tile-s"), ("data-an-rl-note", True), ("hidden", None if note else True)],
                     _esc(note)) +
                _tag("span", [("class", "pfas-hier-tile-s"), ("data-an-mdl", True), ("hidden", None if on else True)],
                     _esc(mdl_words)) +
                saves(rl, "rl", "") + saves(mdl, "mdl", "MDL: "))


def _an_value_tile(label, words, unset, attrs=()):
    """A tile of the card that reads one value; one with nothing set reads so."""
    return _tile(label, words, attrs=list(attrs) + [("data-an-unset", "1" if unset else None),
                                                    ("data-an-label", label)]), unset, label


def _an_block(head, tiles, key, note=""):
    """A heading over its tiles."""
    return (_tag("h5", [("class", "pfas-hier-h")], _esc(head)) +
            _tag("div", [("class", "pfas-hier-tiles"), ("data-an-block", key)], "".join(t[0] for t in tiles)) +
            (_tag("p", [("class", "pfas-hier-note")], _esc(note)) if note else ""))


# the Transitions block's note, after AN_TRANS_NOTE: how its windows are
# worked out (rt_window)
TRANS_TOL_SET = "Windows are worked out from the profile-wide Retention time tolerance, {0}."
TRANS_TOL_UNSET = ("The profile's Retention time tolerance is not set: each window is the one stored with "
                   "its transition.")
TRANS_PEAK_WORDS = {"linear": "Linear", "branched": "Branched"}


def transitions_block(profile, kw, read=None):
    """A compound's Transitions block, as the analyte card and the surrogate
    and internal standard cards draw it, a click opening its window on the
    inputs Integration posts (the same values): one row per peak (an
    isomer sum's linear peak first, then each branched peak), its
    quantifier, qualifiers, retention time and window. Every window is the
    one the worker searches (rt_window): its time plus or minus the
    method's Retention time tolerance, else the window stored with the
    transition, which the note says."""
    _cf, mps, _pf, iso, _ls = _tab_modules()
    from senaite.pfas import rt_window as rtw
    read = mps.read_integration(profile) if read is None else read
    try:
        tol = rtw.tolerance((profile or {}).get("integration"))
    except (TypeError, ValueError):
        tol = None
    peaks = iso.peaks_of(profile, kw) or [kw]
    branched = iso.branched_peaks(profile)

    def unit(words):
        return _tag("span", [("class", "pfas-hier-unit")], _esc(words))
    heads = [_esc("Peak"), _esc("Quantifier"), _esc("Qualifiers"), _esc("RT") + " " + unit("min"),
             _esc("Window") + " " + unit("min") + (" " + _esc("at " + rtw.tolerance_words(tol)) if tol else "")]
    body = []
    for name in peaks:
        row = read.get((name,)) or {}
        rt = _text(row.get("rt"))
        try:
            half = rtw.half_width(row.get("rt"), row.get("window"), tol)[0]
            window = rtw.words(row.get("rt"), half, unit=False)
        except (TypeError, ValueError):
            window = ""
        kind = "" if len(peaks) == 1 else TRANS_PEAK_WORDS["branched" if name in branched else "linear"]
        cells = [_esc(name) + (" " + unit(kind) if kind else "")]
        for words in (_text(row.get("quant")), _text(row.get("quals")), rt, window):
            cells.append(_esc(words or NOT_SET_WORDS))
        body.append(_tag("tr", [], "".join(_tag("td", [("class", "is-num" if i > 2 else None)], c)
                                            for i, c in enumerate(cells))))
    names = [[name, trans_names(name)] for name in peaks]
    table = _tag("table", [("class", "pfas-table pfas-hier-table"), ("data-an-block", "trans"),
                           ("data-trans-of", kw), ("data-trans-names", json.dumps(names)),
                           ("data-trans-tol", json.dumps(TRANS_TOL_NAMES))],
                 _tag("thead", [], _tag("tr", [], "".join(_tag("th", [("class", "is-right" if i > 2 else None)], h)
                                                          for i, h in enumerate(heads)))) +
                 _tag("tbody", [], "".join(body)))
    tol_note = TRANS_TOL_SET.format(rtw.tolerance_words(tol)) if tol else TRANS_TOL_UNSET
    note = " ".join((AN_TRANS_NOTE, tol_note))
    # a click opens the window on the very inputs Integration posts; the
    # window is the stored one only while no tolerance works it out
    fields = []
    for name, own in names:
        head = "{0} \u00b7 ".format(name) if len(peaks) > 1 else ""
        fields += [[own[part], head + TRANS_FIELD_WORDS[part]] for part in TRANS_PARTS
                   if part != "window" or not tol]
    edit = card_act(INTG_ACT, TRANS_EDIT_WORDS, [inplace("{0}: {1}".format(AN_TRANS_HEAD, kw), names=fields,
                                                         note=tol_note)])
    return (_tag("h5", [("class", "pfas-hier-h")], _esc(AN_TRANS_HEAD)) +
            _tag("div", [("class", "pfas-hier-tilebox"), ("aria-label", AN_TRANS_HEAD)] + tile_opens(INTG_ACT),
                 _scroll(table) + _tag("p", [("class", "pfas-hier-note")], _esc(note)) + card_acts(edit)))


TRANS_PARTS = ("quant", "quals", "rt", "window")
TRANS_FIELD_WORDS = {"quant": "Quantifier", "quals": "Qualifiers", "rt": "Retention time", "window": "Window"}
TRANS_EDIT_WORDS = "Edit transitions"
# the method's Retention time tolerance and its unit, as Integration posts them
TRANS_TOL_NAMES = ["f__rt_window_tol", "f__rt_window_unit"]


def trans_names(kw):
    """{part: input name} of compound `kw`'s transition inputs, as
    Integration's table posts them (method_profile_sections INTEGRATION's
    compound rows)."""
    cf = _tab_modules()[0]
    return dict((part, "__".join(["t", cf._enc("intg_an"), cf._enc(kw), cf._enc(part)])) for part in TRANS_PARTS)


def _an_quant_words(cell, kinds):
    """(what Quantified by reads, its note) for the select as drawn."""
    value = _text(cell.value)
    if not value:
        return NOT_SET_WORDS, ""
    kind = AN_QUANT_KINDS.get(kinds.get(value))
    return _label_of(cell.options, value), (kind + AN_QUANT_TAIL) if kind else ""


def _an_entry(row, sheet, profile, group, kinds, read, first):
    """(node, dots, card) of one analyte, drawn from its grid row."""
    from senaite.pfas import row_menu
    cols = OrderedDict((c.key, c) for c in sheet.columns)
    cells = row.cells
    kw = row.key
    quant = cells["quant"]
    q_words, q_note = _an_quant_words(quant, kinds)
    flags = [(i, c) for i, c in enumerate(c for c in sheet.columns if c.key.startswith("panel-"))]
    out = [col.label for _i, col in flags if not bool((cells[col.key].data or {}).get("in"))]
    menu = row_menu.actions(("Edit", "event", "an-edit"), (AN_INTG_WORDS, "event", "an-intg"))
    slots = "".join(_tag("span", [("class", _cls("pfas-hier-slot", None if (cells[col.key].data or {}).get("in")
                                                  else "is-out")), ("data-an-slot", col.key), ("title", col.label)], "")
                    for _i, col in flags)
    slot_words = AN_SLOTS_OUT.format(", ".join(out)) if out else AN_SLOTS_ALL
    tag = _tag("span", [("class", "pfas-tag"), ("data-an-tag", True), ("hidden", True if quant.value else None)],
               _esc(NO_SURROGATE[0]))
    node = _tag("button", [("type", "button"), ("class", _cls("pfas-hier-node", "is-selected" if first else None)),
                           ("data-hier-target", kw), ("aria-pressed", "true" if first else "false"),
                           ("data-an-node", kw), ("data-row-actions", menu)],
                _tag("span", [("class", "pfas-hier-node-t")], _esc(row.label)) +
                _tag("span", [("class", "pfas-hier-node-v")],
                     _tag("span", [("data-an-quant", True)], _esc(q_words if quant.value else "")) + tag) +
                _tag("span", [("class", "pfas-hier-slots"), ("aria-hidden", "true")], slots) +
                _tag("span", [("class", "pfas-sr-hide"), ("data-an-slots-words", True)], _esc(slot_words)))
    dots = _dots(row.label, [("data-an-node", kw)])

    # the card: Quantified by, each matrix, isomers and salt, transitions, flag
    q_tile = _tag("div", [("class", "pfas-hier-tile"), ("data-an-quant-tile", True), ("data-an-name", quant.name)],
                  _tag("span", [("class", "pfas-hier-tile-l")], _esc(cols["quant"].label)) +
                  _tag("span", [("class", "pfas-hier-tile-v"), ("data-an-quant", True)], _esc(q_words)) +
                  _tag("span", [("class", "pfas-hier-tile-s"), ("data-an-quant-note", True),
                                ("hidden", None if q_note else True)], _esc(q_note)))
    units = dict((col.key, col.unit) for _i, col in flags)
    matrices = []
    for i, col in flags:
        matrices.append(_an_matrix_tile(kw, i, col.label, units[col.key], cells[col.key],
                                        cells.get("rl-{0}".format(i)), cells.get("mdl-{0}".format(i))))
    iso_cell = cells["iso"]
    summed = bool(_text(iso_cell.value))
    salt, lot = cells["salt"], cells["lot"]
    lot_words = _label_of(lot.options, lot.value) if _text(lot.value) else ""
    iso_tiles = [_an_value_tile(cols["iso"].label, _shown(cols["iso"], iso_cell) if summed else AN_NOT_SUMMED,
                                not summed)]
    for key in ("linear", "branched", "reported"):
        words = _chips_value(cells[key])
        iso_tiles.append(_an_value_tile(cols[key].label, words or NOT_SET_WORDS, not words,
                                        attrs=[("data-an-name", cells[key].name)]))
    iso_tiles.append(_an_value_tile(cols["salt"].label, _text(salt.value) or NOT_SET_WORDS, not _text(salt.value),
                                    attrs=[("data-an-name", salt.name)]))
    iso_tiles.append(_an_value_tile(cols["lot"].label, lot_words or NOT_SET_WORDS, not lot_words,
                                    attrs=[("data-an-name", lot.name)]))
    flag_tile = _tag("div", [("class", "pfas-hier-tile"), ("data-an-flag", True)],
                     _tag("span", [("class", "pfas-hier-tile-l")], _esc(AN_FLAG_LABEL)) +
                     _tag("span", [("class", "pfas-hier-tile-v"), ("data-an-flag-v", True)],
                          _esc(AN_FLAG_NONE if quant.value else AN_NO_QUANT)) +
                     _tag("span", [("class", "pfas-hier-tile-s")], _esc(AN_FLAG_NOTE)))
    caption = MIDDOT.join(w for w in (row.sub, AN_GROUP_WORDS[group]) if w)
    # no Edit button: a tile opens the analyte's window, Transitions its
    # own (the inputs Integration posts); no help ? of its own: its group
    # heading holds the one ?
    acts = card_acts(card_act("edit", AN_EDIT_WORDS, [("data-an-act", "edit"), ("data-an-of", kw)]))
    body = (_tag("h5", [("class", "pfas-hier-h")], _esc(cols["quant"].label)) +
            _tag("div", [("class", "pfas-hier-tiles")], q_tile) +
            _tag("h5", [("class", "pfas-hier-h")], _esc(PANEL_GROUP)) +
            _tag("div", [("class", "pfas-hier-tiles"), ("data-an-matrices", True)], "".join(matrices)) +
            _an_block(AN_ISO_HEAD, iso_tiles, "iso") +
            transitions_block(profile, kw, read) +
            _tag("h5", [("class", "pfas-hier-h")], "Flag") +
            _tag("div", [("class", "pfas-hier-tiles")], flag_tile) + acts)
    card = _tag("section", [("class", "pfas-hier-card"), ("data-hier-card", kw), ("data-an-of", kw),
                            ("aria-label", row.label), ("hidden", None if first else True)] +
                tile_opens("edit", ["edit"]),
                card_head(row.label) +
                _tag("p", [("class", "pfas-hier-card-cap")], _esc(caption)) + body)
    return node, dots, card


def _an_settings(profile, settings_html, confirmed, chosen=False):
    """(nodes, cards) of the Method settings group: Surrogate recovery in a
    diluted sample (its card holds the setting as render_dilution_recovery
    draws it, its posted input with it) and Analyte set confirmation (the
    Engine flag's state, with the forms that confirm it). `chosen`: the
    first is the list's chosen row (a method with no analyte)."""
    _cf, mps, _pf, _iso, _ls = _tab_modules()
    value = mps.dilution_recovery(profile)
    words = _label_of(mps.DILUTION_RECOVERIES, value) if value else NOT_SET_WORDS
    name = mps.DILUTION_RECOVERY.fields()[0].name
    dil_node = _tag("button", [("type", "button"), ("class", _cls("pfas-hier-node", "is-selected" if chosen else None)),
                               ("data-hier-target", AN_DILREC), ("aria-pressed", "true" if chosen else "false"),
                               ("data-an-node", AN_DILREC)],
                    _tag("span", [("class", "pfas-hier-node-t")], _esc(mps.DILUTION_RECOVERY.title)) +
                    _tag("span", [("class", "pfas-hier-node-v"), ("data-an-dilrec", name),
                                  ("data-an-words", json.dumps(dict(mps.DILUTION_RECOVERIES)))], _esc(words)))
    dil_card = _tag("section", [("class", "pfas-hier-card"), ("data-hier-card", AN_DILREC), ("data-an-of", AN_DILREC),
                                ("aria-label", mps.DILUTION_RECOVERY.title), ("hidden", None if chosen else True)],
                    card_head(mps.DILUTION_RECOVERY.title) +
                    _tag("p", [("class", "pfas-hier-card-cap")], _esc(AN_SETTINGS_HEAD)) +
                    _tag("div", [("class", "pfas-hier-tiles")], settings_html))
    flagged = bool(mps._engine_module().engine(profile)["inclusion_needs_verification"])
    note = _text(confirmed) if confirmed else NOT_FLAGGED
    on_record = note != NOT_FLAGGED
    state = AN_FLAGGED if flagged else (AN_CONFIRMED if on_record else AN_NOT_FLAGGED)
    set_node = _tag("button", [("type", "button"), ("class", "pfas-hier-node"), ("data-hier-target", AN_SET),
                               ("aria-pressed", "false"), ("data-an-node", AN_SET)],
                    _tag("span", [("class", "pfas-hier-node-t")], _esc(AN_SET_TITLE)) +
                    _tag("span", [("class", "pfas-hier-node-v")], _esc(state)))
    if flagged:
        tile = _tile(AN_SET_LABEL, AN_FLAGGED, note=AN_FLAGGED_NOTE, attrs=TILE_READ)
        act = _tag("button", [("type", "submit"), ("class", "btn btn-sm btn-primary"), ("form", "analytes-confirm")],
                   "Confirm analyte set")
    else:
        tile = _tile(AN_SET_LABEL, AN_CONFIRMED if on_record else state, note=note, attrs=TILE_READ)
        act = _tag("button", [("type", "submit"), ("class", "btn btn-sm btn-secondary"), ("form", "analytes-verify")],
                   "Confirm again")
    set_card = _tag("section", [("class", "pfas-hier-card"), ("data-hier-card", AN_SET), ("data-an-of", AN_SET),
                                ("aria-label", AN_SET_TITLE), ("hidden", True)],
                    _tag("h4", [("class", "pfas-hier-card-t")], _esc(AN_SET_TITLE)) +
                    _tag("p", [("class", "pfas-hier-card-cap")], _esc(AN_SETTINGS_HEAD)) +
                    _tag("div", [("class", "pfas-hier-tiles")], tile) +
                    _tag("div", [("class", "pfas-hier-actions")], act))
    return [dil_node, set_node], [dil_card, set_card]


def analyte_groups(profile, sheet):
    """[(group key, label, [row])]: the sheet's rows split into the method's
    own key analytes (method_profile_sections.key_analytes) and the rest,
    each in the sheet's order (alphabetical, analyte_order); a group with
    no row is left out."""
    _cf, mps, _pf, _iso, _ls = _tab_modules()
    keys = mps.key_analytes(profile or {})
    out = []
    for gkey, label in AN_GROUPS:
        rows = [r for r in sheet.rows if (r.key in keys) == (gkey == "key")]
        if rows:
            out.append((gkey, label, rows))
    return out


def render_analytes_list(profile, env=None, sheet=None, settings_html="", confirmed=None):
    """The Analytes tab's List view: <div id="analytes-list">, the
    round-on-save line (as the grid draws it) over one list in three
    groups: Regulated analytes, Other analytes, each alphabetical, each
    analyte a row beside its card; then Method settings. Drawn from the
    grid it mirrors; it posts nothing of an analyte: the grid (the Table
    view) holds every input, and Edit and the row's menu act through the
    grid row's own drawer. The Method settings card holds `settings_html`
    (render_dilution_recovery: the one setting the tab posts outside the
    grid, drawn once, here); `confirmed` is the analyte set's note
    (confirmed_note, else NOT_FLAGGED)."""
    _cf, mps, _pf, _iso, ls = _tab_modules()
    profile = profile or {}
    sheet = sheet or analytes_sheet(profile, env)
    kinds = dict(ls.roles(profile))
    kinds.update((c["id"], "composite") for c in std_composites(profile))
    read = mps.read_integration(profile)
    nodes, cards = [], []
    first = True
    for gkey, label, rows in analyte_groups(profile, sheet):
        # each group's one help ? at its right end; the cards carry none
        nodes.append(group_head(label + MIDDOT + "%d" % len(rows), sheet.help))
        for r in rows:
            node, dots, card = _an_entry(r, sheet, profile, gkey, kinds, read, first)
            first = False
            nodes.append(node + dots)
            cards.append(card)
    # no analyte: the first setting is the chosen row
    s_nodes, s_cards = _an_settings(profile, settings_html, confirmed, chosen=first)
    nodes.append(group_head(AN_SETTINGS_HEAD + MIDDOT + "%d" % len(s_nodes), help_dictionary.SECTION_HELP["dilrec"]))
    nodes += s_nodes
    cards += s_cards
    note = (_tag("p", [("class", "pfas-hint is-flush pfas-sheet-note"), ("role", "note")], _esc(sheet.note))
            if sheet.note else "")
    # what each standard is, as a Quantified by's note reads it, for the
    # page to redraw the note as the choice changes
    notes = dict((k, AN_QUANT_KINDS[v] + AN_QUANT_TAIL) for k, v in kinds.items() if v in AN_QUANT_KINDS)
    return _tag("div", [("id", AN_LIST_ID), ("data-an-quant-notes", json.dumps(notes, sort_keys=True))],
                note + _tag("div", [("class", "pfas-hier"), ("data-hier", "analytes")],
                            _tag("div", [("class", "pfas-hier-list"), ("role", "group"), ("aria-label", "Analytes")],
                                 "".join(nodes)) +
                            _tag("div", [("class", "pfas-hier-cards")], "".join(cards))))


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
    mx_tbl = mps.MATRIX_TEMPERATURES
    mx_cells = _drawn(cf, mx_tbl, profile, env)
    coll = [r for r in cf.render_collection(mps.MATRICES, profile, env) if not r["template"]]
    coll_paths = [c.path[0] for c in cf._bound(mps.MATRICES, profile).columns]
    receipt = dict((f.path[-1], f.name) for f in mps.SAMPLE_RECEIPT.fields())
    drawn_receipt = dict((f["name"], f) for g in cf.render(mps.SAMPLE_RECEIPT, profile, env) for f in g["fields"])
    lo, hi, ice, rnone = (drawn_receipt[receipt[k]] for k in ("min_c", "max_c", "same_day_on_ice", "none"))

    def drawn(cells, table, key, path):
        name = _named(cf, table, profile, key, path)
        return name, (cells.get(name) or {}).get("value") or ""

    def named_pair(cells, table, key):
        names = tuple(_named(cf, table, profile, key, p) for p in ("min_c", "max_c"))
        nname = _named(cf, table, profile, key, "none")
        marked = (cells.get(nname) or {}).get("value") == "on"
        return Cell(tuple((cells.get(n) or {}).get("value") or "" for n in names), name=names,
                    none=(nname, marked, ""), data=dict(NO_REQ_DATA))

    columns = [Column("name", "Sample Type", "select", default=False),
               Column("unit", "Unit", "select"), Column("aliases", "Aliases", "chips")]
    if eng["eis_recovery_limits"]:
        columns.append(Column("class", "Matrix class", "select"))
    columns += [Column("factor", "Matrix factor", "num", align="right", min=0),
                Column("nom", "Amount", "num", align="right", group=NOMINAL_GROUP, min=0),
                Column("nom-unit", "Unit", "select", group=NOMINAL_GROUP)]
    store_scale, receipt_scale = range_scales(profile)
    for key, label, _clock, _st, _h in mps.KEPT:
        columns += [Column("hold-" + key, "Holding", "num", align="right", group=label, unit="days", min=0),
                    Column("store-" + key, "Stored at", "pair", align="right", group=label, unit=DEGREES,
                           scale=store_scale)]
    columns += [Column("receipt", "Allowed", "pair", align="right", group=RECEIPT_GROUP, unit=DEGREES,
                       scale=receipt_scale),
                Column("ice", "Same-day on ice", "switch", align="center", group=RECEIPT_GROUP)]
    if grouped:
        columns.append(Column("tier", "Tier group", "text"))

    # All matrices' ranges, each named in its window by what it judges
    # ("Sample stored at", "Allowed on receipt"), not three alike "Stored at"
    head = {"receipt": Cell((lo["value"], hi["value"]), name=(lo["name"], hi["name"]),
                            label=_mx_label(next(c for c in columns if c.key == "receipt")),
                            none=(rnone["name"], rnone["value"] == "on", ""), data=dict(NO_REQ_DATA)),
            "ice": Cell(bool(ice["checked"]), name=ice["name"], title=ice["label"],
                        label=_mx_label(next(c for c in columns if c.key == "ice")))}
    for col in columns:
        if col.key.startswith("store-"):
            head[col.key] = named_pair(hold_cells, hold_tbl, (col.key[len("store-"):],))
            head[col.key].label = _mx_label(col)

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
        out.update(_mx_temperature_cells(mps, mx_cells, mx_tbl, profile, m, head, columns,
                                         homogenised=env.get("homogenised")))
        if grouped:
            out["tier"] = Cell(", ".join(listing.get(m) or []), state="readonly")
        row = linked.get(m) or {}
        flags = ((row["note"], "warn"),) if row.get("warn") and row.get("note") else ()
        rows.append(Row(m, m, out, group=METHOD_ROW[0], flags=flags, data={"member": "1"}))
    removable = len(rows) > 1
    for r in rows:
        r.data["row-actions"] = matrix_menu(r.key, removable, (env.get("held_by") or {}).get(r.key))
        r.drawer = _mx_reset_button(r.key)
    groups = [Row(METHOD_ROW[0], METHOD_ROW[1], head, selectable=False)]
    add_name, addable = matrices_to_add(profile, env)
    adder = (MATRICES_FORM, add_name, MATRICES_ADD_PICK, "Add a matrix", "Sample Type", addable, "matrix")
    return Sheet("matrices", columns, rows, groups=groups, form=MATRICES_FORM, adder=adder,
                 remover=MATRICES_REMOVE if removable else None,
                 help=help_dictionary.SECTION_HELP["matrices"])


MATRICES_ADD_PICK = "matrices-add-pick"
EDIT_MATRIX_WORDS = "Edit matrix"
REMOVE_MATRIX_WORDS = "Remove from method"
RESET_MATRIX_WORDS = "Reset to All matrices"
# a range set to No requirement: a dash in its cell, its words on hover,
# the box in its window (matrix_temperature.NO_REQUIREMENT)
NO_REQ_DATA = (("set-none", "1"), ("none-hover", "No requirement"), ("none-text", "No requirement: not judged"))
# a matrix's own temperature cells, by grid column: (the column prefix of
# Temperature by matrix, its maximum's path or None for on ice)
MX_TEMP_COLS = (("store-sample", "sample"), ("store-processed", "processed"), ("store-extract", "extract"),
                ("receipt", "receipt"), ("ice", None))


def _mx_temperature_cells(mps, cells, tbl, profile, matrix, head, columns, homogenised=None):
    """A matrix row's own ranges and same-day on ice (Temperature by
    matrix): set, its values; No requirement, its box ticked; unset,
    inherited, All matrices' value its placeholder and its note (a blank
    posts blank: it follows). Same-day on ice is a switch showing what
    applies, which posts nothing itself: its hidden input holds the
    matrix's own value ("", "on", "off"). A matrix not homogenised has no
    processed-sample range (n/a: not drawn, its stored value kept)."""
    cf = _tab_modules()[0]
    out = {}
    made = None if homogenised is None else set(_text(m).strip().lower() for m in homogenised)
    for key, pre in MX_TEMP_COLS:
        col = next(c for c in columns if c.key == key)
        if pre is None:
            name = _named(cf, tbl, profile, (matrix,), "on_ice")
            value = (cells.get(name) or {}).get("value") or ""
            follows = value not in ("on", "off")
            shown = bool(head["ice"].value) if follows else value == "on"
            out[key] = Cell(shown, state="inherited" if follows else "set", label=_mx_label(col),
                            title="{0}: {1}".format(_mx_label(col), MX_AS_ALL) if follows else None,
                            data={"tri": name, "tri-value": "" if follows else value})
            continue
        if pre == "processed" and made is not None and _text(matrix).strip().lower() not in made:
            out[key] = Cell("", state="na", title="Not homogenised: no processed sample",
                            data={"na-words": "not homogenised"})
            continue
        names = tuple(_named(cf, tbl, profile, (matrix,), pre + end) for end in ("_min", "_max"))
        nname = _named(cf, tbl, profile, (matrix,), pre + "_none")
        marked = (cells.get(nname) or {}).get("value") == "on"
        value = tuple((cells.get(n) or {}).get("value") or "" for n in names)
        none = (nname, marked, matrix)
        if marked or any(_text(v) for v in value):
            out[key] = Cell(value, name=names, label=_mx_label(col), none=none, data=dict(NO_REQ_DATA))
        else:
            parent = tuple(_num_words(v) for v in _pair(head[key].value))
            if _none_marked(head[key]):
                words = NO_REQUIREMENT
            else:
                words = _cell_words(col, Cell(parent))[0] if any(parent) else ""
            data = dict(NO_REQ_DATA, follows="1",
                        note="{0}: {1}".format(MX_AS_ALL, words) if words else MX_AS_ALL)
            out[key] = Cell(parent, state="inherited", name=names, label=_mx_label(col), none=none, data=data)
    return out


def _mx_reset_button(matrix):
    """Reset to All matrices in the matrix's window: blanks its own ranges
    and same-day on ice there (the page's script), Done writing them."""
    return _tag("div", [("class", "pfas-drawer-extra")],
                _tag("button", [("type", "button"), ("class", "btn btn-sm btn-secondary"),
                                ("data-mx-reset", matrix)], _esc(RESET_MATRIX_WORDS)))


def matrix_menu(matrix, removable, held_by=None):
    """A matrix's row menu, on its grid row and its node alike: Edit matrix
    (its row's drawer, an event the page runs), Reset to All matrices (its
    own temperature ranges blanked, an event the page runs), then Remove
    from method, which posts the matrix to its own form (matrices-remove),
    as the grid's Remove does with the ticked rows; none while it is the
    only matrix. The units whose list of matrices held names it
    (`held_by`) are named under Remove and asked about before it is sent:
    the removal takes it off them."""
    from senaite.pfas import row_menu
    opts = {"danger": True, "values": {MATRICES_REMOVE[1]: matrix}}
    if held_by:
        units = ", ".join(held_by)
        opts["note"] = REMOVE_HELD_NOTE.format(units)
        opts["confirm"] = REMOVE_HELD_CONFIRM.format(matrix, units)
    return row_menu.actions(
        (EDIT_MATRIX_WORDS, "event", "mtx-edit"),
        (RESET_MATRIX_WORDS, "event", "mtx-reset"),
        (REMOVE_MATRIX_WORDS, "form", MATRICES_REMOVE[0], opts) if removable else None)


REMOVE_HELD_NOTE = "Held by {0}"
REMOVE_HELD_CONFIRM = "Remove {0} from the method? It is also taken off what {1} hold."


# ── the Matrices tab as a list: All matrices, then each matrix ─────────────

MTX_LIST_ID = "matrices-list"
MTX_FOLLOWS = "Every matrix follows these"
MTX_AS_ALL = "Stored and received as All matrices"
MX_AS_ALL = "As All matrices"
NO_REQUIREMENT = "No requirement"
MX_SET_HERE = "{0} set here"
ADD_MATRIX_WORDS = "+ Add matrix"
FACTOR_NOTE = "1.0 applies"
NO_HOLDING = "No holding time"


def _num_words(v):
    """A typed number as the card reads it (1.50 reads 1.5), as the page's
    script reads the input again."""
    return _g(v) if _text(v) else ""


def _cell_words(col, cell):
    """(words, ends, unset): what a matrices card's tile reads for one grid
    cell, as the page reads it again from the cell's inputs: a choice's
    label, a list joined, a number, a number of days (the None box: None),
    a range in °C with its ends, ✓ or ✗; unset when nothing is set (a
    blank the grid names, as the processed sample's "not homogenised", is
    its words)."""
    if col.kind == "pair" and _none_marked(cell):
        # set to No requirement: not judged, a chosen value
        return NO_REQUIREMENT, None, False
    if col.kind == "pair" and cell.state == "inherited":
        # a matrix's own range left blank: it follows All matrices
        return MX_AS_ALL, None, True
    if col.key == "ice" and "tri" in (cell.data or {}):
        # a matrix's own same-day on ice, or As All matrices
        v = _text(cell.data.get("tri-value"))
        if v not in ("on", "off"):
            return MX_AS_ALL, None, True
        return ("✓" if v == "on" else "✗"), None, False
    if col.kind == "pair":
        lo, hi = [_num_words(v) for v in _pair(cell.value)]
        if not lo and not hi:
            return NOT_SET_WORDS, None, True
        ends = (float(lo), float(hi)) if lo and hi else None
        return "{0} {1} {2} {3}".format(lo or EM_DASH, EN_DASH, hi or EM_DASH, col.unit or "").strip(), ends, False
    if col.kind == "switch":
        return ("✓" if cell.value else "✗"), None, False
    if col.kind == "select":
        v = _text(cell.value)
        return (_label_of(cell.options, v) if v else NOT_SET_WORDS), None, not v
    if col.kind == "chips":
        v = _chips_value(cell)
        return (v or NOT_SET_WORDS), None, not v
    if col.kind == "num" and cell.none and cell.none[1]:
        return NONE_WORD.capitalize(), None, False
    v = _num_words(cell.value) if col.kind == "num" else _text(cell.value)
    if not v:
        return (_text(cell.title).capitalize() if cell.title else NOT_SET_WORDS), None, not cell.title
    if col.unit == "days":
        return "{0} {1}".format(v, "day" if v == "1" else "days"), None, False
    return v, None, False


def range_scales(profile):
    """(storage axis, receipt axis): each range of the tab is drawn on its
    own field's scale (the drawer's slider's), read from the field."""
    _cf, mps, _pf, _iso, _ls = _tab_modules()
    store = next(f for f in mps._hold_columns(profile) if f.path[-1] == "min_c")
    receipt = next(f for f in mps.SAMPLE_RECEIPT.fields() if f.path[-1] == "min_c")
    return tuple(store.scale), tuple(receipt.scale)


def _mx_tile(col, cell, of, label, scale=None, unit_cell=None):
    """One tile of a matrices card, naming the grid column it reads
    (data-mx-col); a nominal amount reads with its unit (`unit_cell`); a
    tile with nothing set reads so."""
    words, ends, unset = _cell_words(col, cell)
    if unit_cell is not None and not unset and _text(unit_cell.value):
        words = "{0} {1}".format(words, _label_of(unit_cell.options, unit_cell.value))
    note = ""
    if col.key == "factor" and unset:
        note = FACTOR_NOTE
    elif col.kind == "num" and cell.none and cell.none[1]:
        note = NO_HOLDING
    band = _band(ends, attrs=[("data-mx-band", True)], scale=scale) if col.kind == "pair" else ""
    attrs = [("data-mx-col", col.key), ("data-mx-of", of), ("data-mx-unset", "1" if unset else None),
             ("data-mx-label", label)]
    # following All matrices: muted, as a value set to none
    return _tile(label, words, band, note=note, attrs=attrs, cls="is-none" if words == MX_AS_ALL else None), unset


def _mx_label(col):
    """A tile's label: a kept item's storage by the item, the receipt range
    and on ice by what they judge, the nominal amount by its group's name, a
    holding time by its kept item's."""
    if col.key.startswith("store-"):
        return "{0} stored at".format(col.group)
    if col.key == "receipt":
        return "Allowed on receipt"
    if col.key == "ice":
        return "Same-day on ice"
    if col.key == "nom":
        return NOMINAL_GROUP
    if col.key.startswith("hold-"):
        return "{0} holding".format(col.group)
    return col.title or col.label


def _mx_card(key, title, caption, tiles, acts, shown, tail=None):
    """A matrices card: its tiles, each opening the matrix's window (no Edit
    button), its actions the card's triggers (Remove in the menu only)."""
    body = "".join(t[0] for t in tiles)
    return _tag("section", [("class", "pfas-hier-card"), ("data-hier-card", key), ("data-mx-of", key),
                            ("aria-label", title), ("hidden", None if shown else True)] +
                tile_opens("edit", ["edit", "remove"]),
                _tag("h4", [("class", "pfas-hier-card-t")], _esc(title)) +
                _tag("p", [("class", "pfas-hier-card-cap"), ("data-mx-tail", tail)], _esc(caption)) +
                _tag("div", [("class", "pfas-hier-tiles")], body) + card_acts(*acts))


def render_matrices_list(profile, env=None, sheet=None, groups_of=None):
    """The Matrices tab's List view: <div id="matrices-list">, All matrices
    first, the parent whose values every matrix follows (each kept item's
    storage range and the receipt range, drawn as ranges on their own axes,
    and same-day on ice), then each matrix under it, its card holding only
    what is its own (unit, aliases, class, factor, nominal amount, holding
    times, tier group); a value not set reads so. Drawn from the grid it mirrors; it posts nothing:
    the grid (the Table view) holds every input, and Edit and the node's
    menu act through the grid row's own drawer and the tab's own forms.
    Under the matrices, the Correction group: Sample basis and Method blank,
    each beside its card (profile_cards.correction_parts), read from Sample
    correction as the Table view draws it (`groups_of(sid)`, the view's
    section_groups)."""
    from senaite.pfas import profile_cards
    profile = profile or {}
    sheet = sheet or matrices_sheet(profile, env)
    cols = OrderedDict((c.key, c) for c in sheet.columns)
    head = sheet.groups[0]
    store_scale, receipt_scale = range_scales(profile)
    nodes, cards = [group_head(profile_cards.MATRICES_GROUP, help_dictionary.SECTION_HELP["matrices"])], []

    # All matrices: the ranges every matrix shares
    r_words, r_ends, _u = _cell_words(cols["receipt"], head.cells["receipt"])
    nodes.append(_tag("button", [("type", "button"), ("class", "pfas-hier-node is-selected"),
                                 ("data-hier-target", head.key), ("aria-pressed", "true"), ("data-mx-node", head.key)],
                      _tag("span", [("class", "pfas-hier-node-t")], _esc(head.label)) +
                      _tag("span", [("class", "pfas-hier-node-v"), ("data-mx-value", "receipt")], _esc(r_words)) +
                      _band(r_ends, attrs=[("data-mx-band", True)], scale=receipt_scale) +
                      _tag("span", [("class", "pfas-hier-node-s")], _esc(MTX_FOLLOWS))))
    tiles = []
    for key, cell in head.cells.items():
        scale = store_scale if key.startswith("store-") else receipt_scale if key == "receipt" else None
        label = _mx_label(cols[key])
        tiles.append(_mx_tile(cols[key], cell, head.key, label, scale) + (label,))
    cards.append(_mx_card(head.key, head.label, MTX_FOLLOWS, tiles,
                          [card_act("edit", "Edit", [("data-mx-act", "edit-all"), ("data-mx-of", head.key)])], True))

    # each matrix: what is its own
    for r in sheet.rows:
        menu = (r.data or {}).get("row-actions")
        sub = ""
        if "class" in r.cells:
            sub = _tag("span", [("class", "pfas-hier-node-s"), ("data-mx-value", "class")],
                       _esc(_cell_words(cols["class"], r.cells["class"])[0]))
        nodes.append(_tag("button", [("type", "button"), ("class", "pfas-hier-node is-sub"),
                                     ("data-hier-target", r.key), ("aria-pressed", "false"), ("data-mx-node", r.key),
                                     ("data-row-actions", menu)],
                          _tag("span", [("class", "pfas-hier-node-t")], _esc(r.label)) +
                          _tag("span", [("class", "pfas-hier-node-v"), ("data-mx-value", "unit")],
                               _esc(_cell_words(cols["unit"], r.cells["unit"])[0])) + sub) +
                     (_dots(r.label, [("data-mx-node", r.key)]) if menu else ""))
        tiles, own = [], []
        for key in [k for k in cols if k in r.cells]:
            if key in ("name", "nom-unit"):
                continue
            cell = r.cells[key]
            if cell.state == "na":
                continue                # not the matrix's (a processed range not homogenised)
            if key in dict(MX_TEMP_COLS) and cols[key].kind == "pair" and cell.state == "set" \
                    and not _none_marked(cell):
                # an end the matrix leaves blank reads All matrices' end
                ends = [v if _text(v) else h for v, h in zip(_pair(cell.value), _pair(head.cells[key].value))]
                cell = Cell(tuple(ends), name=cell.name, label=cell.label)
            label = _mx_label(cols[key])
            scale = store_scale if key.startswith("store-") else receipt_scale if key == "receipt" else None
            tile = _mx_tile(cols[key], cell, r.key, label, scale,
                            unit_cell=r.cells.get("nom-unit") if key == "nom" else None)
            tiles.append(tile + (label,))
            if key in dict(MX_TEMP_COLS) and not tile[1]:
                own.append(label)
        acts = [card_act("edit", EDIT_MATRIX_WORDS, [("data-mx-act", "edit"), ("data-mx-of", r.key)])]
        if sheet.remover:
            acts.append(card_act("remove", REMOVE_MATRIX_WORDS, [("data-mx-act", "remove"), ("data-mx-of", r.key)],
                                 danger=True))
        # what the matrix sets of its own temperatures, else that it follows
        head_words = MX_SET_HERE.format(", ".join(own)) if own else MTX_AS_ALL
        rest = [_text(f[0]) for f in r.flags if isinstance(f, (list, tuple))]
        caption = MIDDOT.join([head_words] + rest)
        cards.append(_mx_card(r.key, r.label, caption, tiles, acts, False,
                              tail="".join(MIDDOT + t for t in rest) or None))
    if sheet.adder and sheet.adder[5]:
        nodes.append(_tag("div", [("class", "pfas-hier-actions")],
                          _list_button(ADD_MATRIX_WORDS, [("data-mx-add", sheet.adder[2])])))
    c_nodes, c_cards = profile_cards.correction_parts(profile, env, groups_of)
    nodes += c_nodes
    cards += c_cards
    return _tag("div", [("id", MTX_LIST_ID), ("class", "pfas-hier"), ("data-hier", "matrices"), ("data-set-list", True),
                        ("data-set-form", MATRICES_FORM)],
                _tag("div", [("class", "pfas-hier-list"), ("role", "group"), ("aria-label", "Matrices")],
                     "".join(nodes)) +
                _tag("div", [("class", "pfas-hier-cards")], "".join(cards)))


# ── Certificate format as a list: All matrices, then what each matrix sets ──

RF_LIST_ID = "report-format-list"
RF_ALL_LABEL = "All matrices"
RF_FOLLOWS = "Follows All matrices"
RF_SET_HERE = "{0} set here"
RF_PARENT_NOTE = "All matrices: {0}"
RF_RESET_WORDS = "Reset to All matrices"
RF_OPEN_ALL_WORDS = "Edit All matrices"
# the All matrices row's card, every matrix's parent
RF_ALL_KEY = "rf-all"


def _rf_words(cell, parent=False):
    """What one Certificate format cell reads: a choice's label, a text as
    typed; on All matrices a blank reads the built-in setting it starts from
    (the choice the table shows selected, a text's placeholder); a blank
    matrix cell reads "" (it follows All matrices)."""
    value = _text(cell.get("value"))
    if cell.get("kind") == "choice":
        value = value or (_text(cell.get("default")) if parent else "")
        return _label_of(cell.get("choices"), value) if value else ""
    if not value and parent:
        return _text(cell.get("placeholder")) or EM_DASH
    return value


def render_report_format_list(profile, env=None, groups=None):
    """Certificate format's List view: <div id="report-format-list">, All
    matrices first, the parent whose settings every matrix follows, then
    each matrix, its card showing only the settings it sets for itself (each
    with what All matrices holds), the rest named once as following All
    matrices. Drawn from the table it mirrors (`groups`, as the section
    draws it); it posts nothing: the table holds every input, and a click
    on a card's tile writes them through nameless copies in the shared
    drawer (no Edit button; Reset to All matrices in the menu only); the
    tile naming what follows All matrices opens All matrices' window."""
    from senaite.pfas import row_menu
    cf, mps, _pf, _iso, _ls = _tab_modules()
    profile = profile or {}
    groups = groups if groups is not None else cf.render(mps.SECTIONS["rf"], profile, env or {})
    rows = [r for g in groups for r in g["rows"]]
    if not rows:
        return ""
    top, kids = rows[0], rows[1:]
    # what All matrices holds, by setting (its column's label)
    parent = dict((c["label"], _rf_words(c, True)) for c in top["cells"])
    nodes, cards = [], []

    def names(row):
        return json.dumps([c["name"] for c in row["cells"]])

    def card(key, title, caption, tiles, acts, row, shown):
        return _tag("section", [("class", "pfas-hier-card"), ("data-hier-card", key), ("data-rf-of", key),
                                ("data-rf-names", names(row)), ("aria-label", title), ("hidden", None if shown else True)] +
                    tile_opens("edit", ["edit", "reset"]),
                    _tag("h4", [("class", "pfas-hier-card-t")], _esc(title)) +
                    _tag("p", [("class", "pfas-hier-card-cap"), ("data-rf-value", True)], _esc(caption)) +
                    _tag("div", [("class", "pfas-hier-tiles")], "".join(tiles)) + card_acts(*acts))

    key0 = RF_ALL_KEY
    nodes.append(_tag("button", [("type", "button"), ("class", "pfas-hier-node is-selected"), ("data-hier-target", key0),
                                 ("aria-pressed", "true"), ("data-rf-node", key0)],
                      _tag("span", [("class", "pfas-hier-node-t")], _esc(RF_ALL_LABEL)) +
                      _tag("span", [("class", "pfas-hier-node-s")], _esc(MTX_FOLLOWS))))
    tiles = [_tile(c["label"], parent[c["label"]], attrs=[("data-rf-name", c["name"])]) for c in top["cells"]]
    cards.append(card(key0, RF_ALL_LABEL, MTX_FOLLOWS, tiles,
                      [card_act("edit", "Edit", [("data-rf-act", "edit"), ("data-rf-of", key0)])], top, True))
    for i, row in enumerate(kids):
        key = "rf-{0}".format(i)
        set_here = [c for c in row["cells"] if _text(c.get("value"))]
        follows = [c["label"] for c in row["cells"] if not _text(c.get("value"))]
        menu = row_menu.actions(("Edit", "event", "rf-edit"),
                                (RF_RESET_WORDS, "event", "rf-reset", {"danger": True}))
        value = RF_SET_HERE.format(len(set_here)) if set_here else RF_FOLLOWS
        nodes.append(_tag("button", [("type", "button"), ("class", "pfas-hier-node is-sub"), ("data-hier-target", key),
                                     ("aria-pressed", "false"), ("data-rf-node", key), ("data-row-actions", menu)],
                          _tag("span", [("class", "pfas-hier-node-t")], _esc(row["label"])) +
                          _tag("span", [("class", "pfas-hier-node-v"), ("data-rf-value", True)], _esc(value))) +
                     _dots(row["label"], [("data-rf-node", key)]))
        # every setting has its tile, shown only while the matrix sets it
        tiles = []
        for c in row["cells"]:
            own = _text(c.get("value"))
            tiles.append(_tile(c["label"], _rf_words(c) if own else "",
                               note=RF_PARENT_NOTE.format(parent.get(c["label"], "")),
                               attrs=[("data-rf-name", c["name"]), ("hidden", None if own else True)]))
        tiles.append(_tile(RF_FOLLOWS, ", ".join(follows),
                           attrs=[("data-rf-follows", True), ("hidden", None if follows else True)] +
                           tile_opens("all", ["all", "edit", "reset"])))
        cards.append(card(key, row["label"], value, tiles,
                          [card_act("edit", "Edit", [("data-rf-act", "edit"), ("data-rf-of", key)]),
                           card_act("all", RF_OPEN_ALL_WORDS, [("data-go-node", key0)]),
                           card_act("reset", RF_RESET_WORDS, [("data-rf-act", "reset"), ("data-rf-of", key)],
                                    danger=True)], row, False))
    return _tag("div", [("id", RF_LIST_ID), ("class", "pfas-hier"), ("data-hier", "report-format")],
                _tag("div", [("class", "pfas-hier-list"), ("role", "group"), ("aria-label", "Certificate format")],
                     "".join(nodes)) +
                _tag("div", [("class", "pfas-hier-cards")], "".join(cards)))


# ── Integration as a list: the method defaults, then the compounds that ────
# ── set their own, and every compound's transitions and windows ───────────

INTG_LIST_ID = "integration-list"
INTG_TRANS_ID = "integration-transitions"
INTG_METHOD = "intg-method"
INTG_METHOD_LABEL = "Method defaults"
INTG_EVERY = "Every compound follows these"
INTG_FOLLOWS = "Follows method defaults"
INTG_METHOD_NOTE = "Method: {0}"
INTG_DEFAULT = "Default"
INTG_RESET_WORDS = "Reset to method defaults"
INTG_OPEN_METHOD_WORDS = "Edit method defaults"
INTG_ADD_WORDS = "+ Override a compound"
INTG_TRANS_HEAD = "Transitions and windows"


PLAIN_NUMBER = re.compile(r"^-?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$")


def _intg_words(kind, value, choices, unit):
    """A setting as it reads: a choice's label, a number with its unit,
    words (auto) as typed; "" for blank."""
    v = _text(value).strip()
    if not v:
        return ""
    if kind == "choice":
        return _label_of(choices, v)
    return "{0} {1}".format(v, unit) if unit and PLAIN_NUMBER.match(v) else v


def _intg_choices(kind, choices):
    return json.dumps([[_text(v), _text(l)] for v, l in choices or ()]) if kind == "choice" else None


# the retention time tolerance reads in the unit its own switch holds: one
# tile, the switch's tile kept hidden for the card's Edit
INTG_RT_TOL, INTG_RT_UNIT = "f__rt_window_tol", "f__rt_window_unit"


def _intg_rt_unit(fields):
    """{"unit-from": the switch's name, "words": {value: unit}, "value":
    the unit it holds} for the tolerance tile; None without the switch."""
    unit = [f for f in fields if f["name"] == INTG_RT_UNIT]
    if not unit:
        return None
    words = dict((_text(v), _text(l)) for v, l in unit[0].get("choices") or ())
    words[""] = words.get(_text(unit[0].get("default")) or "pct", "")
    return {"unit-from": INTG_RT_UNIT, "words": words, "value": words.get(_text(unit[0].get("value")), words[""])}


def _intg_method_tile(fld, rt_unit=None):
    """A method default as its tile: its value, else what a blank resolves
    to (noted Default), else Not set; shown only while the field it hangs
    on shows it (the field's own show-if, which the page applies). The
    retention time tolerance reads in the unit its switch holds (`rt_unit`),
    whose own tile is hidden."""
    unit = _text(fld.get("unit"))
    extra = []
    if rt_unit and fld["name"] == INTG_RT_TOL:
        unit = rt_unit["value"]
        extra = [("data-intg-unit-from", rt_unit["unit-from"]),
                 ("data-intg-unit-words", json.dumps(rt_unit["words"], sort_keys=True))]
    elif rt_unit and fld["name"] == INTG_RT_UNIT:
        extra = [("hidden", True)]
    own = _intg_words(fld["kind"], fld["value"], fld.get("choices"), unit)
    said = _intg_words(fld["kind"], fld.get("resolved"), fld.get("choices"), unit)
    show_if = fld.get("show_if")
    attrs = [("data-intg-name", fld["name"]), ("data-intg-kind", fld["kind"]), ("data-intg-unit", unit or None),
             ("data-intg-resolved", _text(fld.get("resolved")) or None),
             ("data-intg-choices", _intg_choices(fld["kind"], fld.get("choices"))),
             ("data-show-if", show_if[0] if show_if else None),
             ("data-show-value", _text(show_if[1]) if show_if and not fld.get("show_values") else None),
             ("data-show-values", fld.get("show_values") or None)] + extra
    return _tile(fld["label"], own or said or NOT_SET_WORDS, note=INTG_DEFAULT if not own and said else "",
                 attrs=attrs)


def integration_parts(profile, intg_groups, an_groups):
    """(defaults, compounds, overrides, transitions): the method default
    fields by group [(title, [field])]; each compound row of the table with
    its cells; the column indexes that override a method default (a blank
    resolves to it) with the method field each one follows, if the tab draws
    one ({index: field name or None}); the indexes that are the compound's
    own (transitions, retention time, window, peak, partner, ratio)."""
    cf, mps, _pf, _iso, _ls = _tab_modules()
    defaults = [(g.get("title") or "", list(g.get("shown") or ())) for g in intg_groups[1:]]
    method_names = set(f["name"] for _t, fs in defaults for f in fs)
    keys = [c.path[0] for c in cf._bound(mps.SECTIONS["intg_an"], profile).columns]
    rows = [r for g in an_groups for r in g["rows"]]
    cells = rows[0]["cells"] if rows else []
    overrides, own = OrderedDict(), []
    for i, c in enumerate(cells):
        if c.get("resolves"):
            name = "f__" + keys[i]
            overrides[i] = name if name in method_names else None
        else:
            own.append(i)
    return defaults, rows, overrides, own


def _intg_parent_words(defaults):
    """{method field name: what it reads}, a blank as what it resolves to."""
    out = {}
    for _t, fs in defaults:
        for f in fs:
            unit = _text(f.get("unit"))
            out[f["name"]] = (_intg_words(f["kind"], f["value"], f.get("choices"), unit) or
                              _intg_words(f["kind"], f.get("resolved"), f.get("choices"), unit) or NOT_SET_WORDS)
    return out


def _intg_trans_words(c):
    return _intg_words(c["kind"], c["value"], c.get("choices"), "") or EM_DASH


def render_integration_list(profile, env=None, intg_groups=None, an_groups=None):
    """Integration's List view: <div id="integration-list">, the method
    defaults first, the parent every compound follows, then each compound
    that sets its own (smoothing, area, S/N and the review limits), its card
    showing only what it sets, each beside the method's value, the rest
    named once as following the method; then every compound's transitions
    and windows (its own, with no parent), a row each. Drawn from the
    sections as the Table view draws them (`intg_groups`, `an_groups`); it
    posts nothing: the Table view holds every input, and a click on a card's
    tile writes them through nameless copies in the shared drawer (no Edit
    button; Reset to method defaults in the menu only); the tile naming what
    follows the method defaults opens their window."""
    from senaite.pfas import row_menu
    cf, mps, _pf, _iso, _ls = _tab_modules()
    profile = profile or {}
    env = env or {}
    intg_groups = intg_groups if intg_groups is not None else cf.render(mps.SECTIONS["intg"], profile, env)
    an_groups = an_groups if an_groups is not None else cf.render(mps.SECTIONS["intg_an"], profile, env)
    defaults, rows, overrides, own = integration_parts(profile, intg_groups, an_groups)
    columns = (an_groups[0]["columns"] if an_groups else [])
    parent = _intg_parent_words(defaults)
    nodes, cards = [], []

    def unit_of(j):
        return _text(columns[j].get("unit")) if j < len(columns) else ""

    def card(key, title, caption, body, acts, names, shown):
        return _tag("section", [("class", "pfas-hier-card"), ("data-hier-card", key), ("data-intg-of", key),
                                ("data-intg-names", json.dumps(names) if names is not None else None),
                                ("aria-label", title), ("hidden", None if shown else True)] +
                    tile_opens("edit", ["edit", "reset"]),
                    _tag("h4", [("class", "pfas-hier-card-t")], _esc(title)) +
                    _tag("p", [("class", "pfas-hier-card-cap"), ("data-intg-value", True)], _esc(caption)) + body +
                    card_acts(*acts))

    nodes.append(_tag("button", [("type", "button"), ("class", "pfas-hier-node is-selected"),
                                 ("data-hier-target", INTG_METHOD), ("aria-pressed", "true"),
                                 ("data-intg-node", INTG_METHOD)],
                      _tag("span", [("class", "pfas-hier-node-t")], _esc(INTG_METHOD_LABEL)) +
                      _tag("span", [("class", "pfas-hier-node-s")], _esc(INTG_EVERY))))
    rt_unit = _intg_rt_unit([f for _t, fs in defaults for f in fs])
    body = "".join(_tag("h5", [("class", "pfas-hier-h")], _esc(title)) +
                   _tag("div", [("class", "pfas-hier-tiles")], "".join(_intg_method_tile(f, rt_unit) for f in fs))
                   for title, fs in defaults if fs)
    cards.append(card(INTG_METHOD, INTG_METHOD_LABEL, INTG_EVERY, body,
                      [card_act("edit", "Edit", [("data-intg-act", "edit"), ("data-intg-of", INTG_METHOD)])],
                      [f["name"] for _t, fs in defaults for f in fs], True))
    following = 0
    for i, row in enumerate(rows):
        key = "intg-{0}".format(i)
        cells = row["cells"]
        mine = [(j, cells[j]) for j in overrides]
        set_here = [(j, c) for j, c in mine if _text(c.get("value"))]
        follows = [c["label"] for j, c in mine if not _text(c.get("value"))]
        following += 0 if set_here else 1
        value = RF_SET_HERE.format(len(set_here)) if set_here else INTG_FOLLOWS
        menu = row_menu.actions(("Edit", "event", "intg-edit"),
                                (INTG_RESET_WORDS, "event", "intg-reset", {"danger": True}))
        note = _tag("span", [("class", "pfas-hier-node-s")], _esc(row["note"])) if row.get("note") else ""
        nodes.append(_tag("button", [("type", "button"), ("class", "pfas-hier-node is-sub"), ("data-hier-target", key),
                                     ("aria-pressed", "false"), ("data-intg-node", key), ("data-row-actions", menu),
                                     ("title", row.get("sublabel") or None), ("hidden", None if set_here else True)],
                          _tag("span", [("class", "pfas-hier-node-t")], _esc(row["label"])) +
                          _tag("span", [("class", "pfas-hier-node-v"), ("data-intg-value", True)], _esc(value)) + note) +
                     _dots(row["label"], [("data-intg-node", key), ("hidden", None if set_here else True)]))
        # what the method holds where no method field is on the tab (the
        # qualifier S/N, from QC criteria): as the table's blank cell reads it
        method = [None if overrides[j] else
                  (_intg_words(c["kind"], c.get("resolved"), c.get("choices"), unit_of(j)) or NOT_SET_WORDS)
                  for j, c in mine]
        tiles = []
        if set_here:
            for (j, c), static in zip(mine, method):
                words = _intg_words(c["kind"], c["value"], c.get("choices"), unit_of(j))
                if words:
                    tiles.append(_tile(c["label"], words,
                                       note=INTG_METHOD_NOTE.format(parent.get(overrides[j]) if overrides[j] else static)))
            if follows:
                tiles.append(_tile(INTG_FOLLOWS, ", ".join(follows),
                                   attrs=[("data-intg-follows", True)] + tile_opens("all", ["all", "edit", "reset"])))
        body = _tag("div", [("class", "pfas-hier-tiles"), ("data-intg-tiles", True),
                            ("data-intg-method", json.dumps(method))], "".join(tiles))
        cards.append(card(key, row["label"], value, body,
                          [card_act("edit", "Edit", [("data-intg-act", "edit"), ("data-intg-of", key)]),
                           card_act("all", INTG_OPEN_METHOD_WORDS, [("data-go-node", INTG_METHOD)]),
                           card_act("reset", INTG_RESET_WORDS, [("data-intg-act", "reset"), ("data-intg-of", key)],
                                    danger=True)],
                          None, False))
    add = _tag("div", [("class", "pfas-hier-actions")],
               _list_button(INTG_ADD_WORDS, [("data-intg-add", True)], hidden=not following))
    # what each override column is, once: [label, kind, unit, the method
    # field it follows or null, its choices or null]
    cols = [[_text(c["label"]), c["kind"], unit_of(j), overrides[j],
             json.loads(_intg_choices(c["kind"], c.get("choices"))) if c["kind"] == "choice" else None]
            for j, c in ((j, rows[0]["cells"][j]) for j in overrides)] if rows else []
    hier = _tag("div", [("class", "pfas-hier"), ("data-hier", "integration")],
                _tag("div", [("class", "pfas-hier-list"), ("role", "group"), ("aria-label", "Integration")],
                     "".join(nodes) + add) +
                _tag("div", [("class", "pfas-hier-cards")], "".join(cards)))
    return _tag("div", [("id", INTG_LIST_ID), ("data-intg-cols", json.dumps(cols)),
                        ("data-intg-at", json.dumps([list(overrides), own]))] + _intg_names(rows),
                hier + _intg_transitions(rows, columns, own))


def _intg_names(rows):
    """Every compound row's input names, once for the list, as each row's
    prefix and each column's suffix (data-intg-prefix, data-intg-suffix);
    a row whose names do not split so is listed whole (data-intg-whole)."""
    if not rows:
        return []
    first = [c["name"] for c in rows[0]["cells"]]
    suffix = ["__" + n.rsplit("__", 1)[-1] for n in first]
    prefix, whole = [], {}
    for i, row in enumerate(rows):
        names = [c["name"] for c in row["cells"]]
        head = names[0][:len(names[0]) - len(suffix[0])] if names[0].endswith(suffix[0]) else None
        if head is not None and names == [head + s for s in suffix]:
            prefix.append(head)
        else:
            prefix.append(None)
            whole["intg-{0}".format(i)] = names
    return [("data-intg-prefix", json.dumps(prefix)), ("data-intg-suffix", json.dumps(suffix)),
            ("data-intg-whole", json.dumps(whole) if whole else None)]


def _intg_trans_row(cls, attrs, label_cell, words, own, columns):
    tds = []
    for j, w in zip(own, words):
        right = columns[j].get("align") == "right" if j < len(columns) else False
        tds.append(_tag("td", [("class", "is-num" if right else None)], _esc(w)))
    return _tag("tr", [("class", cls), ("tabindex", "0")] + attrs, label_cell + "".join(tds))


def _intg_transitions(rows, columns, own):
    """Every compound's transitions and windows, its own values with no
    parent: a row each. A row opens its editor (its menu: Edit); it names
    no input."""
    from senaite.pfas import row_menu
    if not rows or not own:
        return ""
    heads = []
    for j in own:
        col = columns[j]
        unit = _tag("span", [("class", "pfas-hier-unit")], _esc(col["unit"])) if col.get("unit") else ""
        heads.append(_tag("th", [("class", "is-right" if col.get("align") == "right" else None)],
                          _esc(col["label"]) + (" " + unit if unit else "")))
    menu = row_menu.actions(("Edit", "event", "intg-trans-edit"))
    full = []
    for i, row in enumerate(rows):
        key = "intg-{0}".format(i)
        words = [_intg_trans_words(row["cells"][j]) for j in own]
        full.append(_intg_trans_row(None, [("data-intg-keys", json.dumps([key])), ("data-row-actions", menu)],
                                    _tag("td", [], _esc(row["label"])), words, own, columns))
    head = _tag("thead", [], _tag("tr", [], _tag("th", [], "Compound") + "".join(heads)))
    table = _tag("table", [("id", INTG_TRANS_ID), ("class", "pfas-table pfas-hier-table"),
                           ("data-intg-labels", json.dumps([_text(r["label"]) for r in rows])),
                           ("data-intg-right", json.dumps([columns[j].get("align") == "right" for j in own]))],
                 head + _tag("tbody", [], "".join(full)))
    return _tag("h4", [("class", "pfas-hier-h")], _esc(INTG_TRANS_HEAD)) + _scroll(table)


# ── the QC criteria tab ─────────────────────────────────────────────────────

QC_FORM = "section-qc"
# The LFSMD row's sub-label: the one basis every method's RPD has.
LFSMD_SUB = u"RPD of the two measured concentrations"
# the window grid's QC types, in this order, with their short names
QC_TYPES = [("LFB", "LFB"), ("LFSM", "LFSM"), ("LFSMD", "LFSMD RPD"), ("Dup", "SD RPD")]
QC_LEVELS = [("ordinary", "Ordinary spike"), ("low", "Low level")]
# each QC type's tiers: the declared collection that holds them
TIER_SECTIONS = [("LFSM", "tiers"), ("LFB", "tiers_lfb"), ("LFSMD", "lfsmd"), ("Dup", "dup")]
# the settings on one analyte's cell (method_profile_sections.QC_CELLS)
CELLS_SECTION = "qc_cells"
# the sections the tab draws whatever QC types the method runs
# (the run rules, the new calibration curve and the worksheet size shape a
# run: Run & reporting's form saves them, RUN_TAB_SECTIONS)
QC_FIXED_SECTIONS = ["blk", "mxb", "cal", "cal_levels", "cal_scale", "flags_qc"]
RUN_TAB_SECTIONS = ("run_rules", "xbatch")
# The rules the Isotope standards tab holds with their limits, by its list
# group: their states, the IS response windows (cal_is), its Required
# criteria and flag note post with that tab's form, never with QC criteria's
STANDARD_RULE_GROUPS = [("sur", ("surrogate_recovery",)), ("is", ("is_response", "is_vs_ccv"))]
STANDARD_RULES = tuple(k for _g, keys in STANDARD_RULE_GROUPS for k in keys)
STANDARD_SECTIONS = ("cal_is", "flags_std")
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
# the window grid's fold, under the Rules section in the Table view alone;
# a rule whose limits are the grid's reads IN_THE_GRID in the rule table
# (the grid is below it) and GRID_IN_TABLE in the List view
WINDOWS_TITLE = "Window per analyte and matrix"
IN_THE_GRID = "In the window grid below"
GRID_IN_TABLE = "In the Table view"
# the QC types whose tier boxes, in the List view, hold the window grid's
# values: a Matrices tile and a tile per analyte the tier sets. LFB is left
# out (it applies to drinking-water methods only); LFSMD's tiers follow
# LFSM's
GRID_TIER_TYPES = ("LFSM", "Dup")
WINDOWS_REGION = "qc-ed-windows"
BLANK_REGION = "qc-ed-blank"


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
    # a type the method may add (addable_qc_types) has its collection drawn
    # empty, so + Add QC type has rows to fill; posted empty it creates nothing
    near = set(qca) | set(addable_qc_types(profile))
    return (ids + (["tiers_lfb"] if "LFB" in near else []) + (["dup"] if "Dup" in near else []) +
            (["lfsmd"] if "LFSMD" in near else []) + [CELLS_SECTION])


def qc_section_ids(profile):
    """Every section the QC criteria tab's form saves, in order."""
    return recovery_section_ids(profile) + list(QC_FIXED_SECTIONS)


def _runs(profile, qc):
    """Whether the method runs `qc`, as the engine reads it (an entry
    without the flag runs)."""
    entry = ((profile or {}).get("qc_acceptance") or {}).get(qc)
    return isinstance(entry, dict) and bool(entry.get("enabled", True))


def qc_is_off(profile, qc):
    """A QC type the method holds whose rule row is Off (its run flag
    follows the row): judged by nothing, its tiers and windows kept."""
    held = isinstance(((profile or {}).get("qc_acceptance") or {}).get(qc), dict)
    return held and (not _runs(profile, qc) or qc_row_state(profile, qc) == "off")


def drawn_as_run(profile, qc):
    """What the tab draws for an Off QC type: a copy whose entry runs, so the
    kept tiers and windows show, greyed. Drawn only: never saved, never
    judged; the engine reads the stored profile."""
    if not qc_is_off(profile, qc):
        return profile
    rules, _qct = _qc_modules()
    p = copy.deepcopy(profile)
    p["qc_acceptance"][qc]["enabled"] = True
    rules.set_qc_row_state(p, qc, "enforced")
    return p


def mute_attrs(profile, env, qc):
    """A QC type's windows and tiers grey while its rule row is Off: drawn
    greyed when the stored row is, and following the row as it is set on the
    page (data-mute-if on its posted state). A type with no row drawn keeps
    the class it is drawn with."""
    rules, _qct = _qc_modules()
    key = rules.qc_row_key(qc)
    follow = [] if not key or key in unused_rules(profile, env) else [
        ("data-mute-if", "rulestate." + key), ("data-mute-values", "off")]
    return [("class", "is-muted" if qc_is_off(profile, qc) else None)] + follow


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


def _qc_type_label(mps, code):
    """A QC type's row label from its kind: "LFSM recovery", "SD RPD"."""
    kind = mps.QC_KIND.get(code, "other")
    name = RUN_LABELS.get(code, code)
    return {"recovery": name + " recovery", "rpd": name + " RPD"}.get(kind, name)


def addable_qc_types(profile):
    """The QC types + Add QC type offers: the extraction worksheet's QC types
    (extraction_batch.QC_ROLES) the method does not hold, each one this tab
    can give its limit -- a tier collection (TIER_SECTIONS) or a blank
    limit (BLANK_TYPES); LFSMD only beside LFSM, whose tiers it follows.
    A type with a stored state but no entry is drawn already (unused_rules)."""
    from senaite.pfas.extraction_batch import QC_ROLES
    _cf, mps, _pf, _iso, _ls = _tab_modules()
    rules, _qct = _qc_modules()
    profile = profile or {}
    qca = profile.get("qc_acceptance") or {}
    stored = profile.get("rule_states") or {}
    blanks = set(code for code, _l in mps.BLANK_TYPES)
    gridded = dict(TIER_SECTIONS)
    out = []
    for code in QC_ROLES:
        key = rules.qc_row_key(code)
        if code in qca or not key or key in stored or not (code in gridded or code in blanks):
            continue
        if code == "LFSMD" and not isinstance(qca.get("LFSM"), dict):
            continue
        out.append(code)
    return out


def qc_row_state(profile, code):
    """A QC type's or blank's row as the tab draws it: the state the worker
    reads (rules.rule_state; a type the method does not hold is Enforced).
    Drawn set, never inherited, so the state posts as shown: the Show
    picker reads it, and the writer stores only a state that differs."""
    rules, _qct = _qc_modules()
    return rules.rule_state(profile, None, rules.qc_row_key(code))


def shown_qc_type(profile, qc_type="LFSM"):
    """The QC type the window grid shows: the one asked for, LFSM if none.
    A type whose row is Off is shown too, greyed (mute_attrs)."""
    return qc_type if qc_type in dict(QC_TYPES) else "LFSM"


def _region_id(sid, group):
    return "qc-ed-" + re.sub(r"[^a-z0-9]+", "-", "{0} {1}".format(sid, group).lower()).strip("-")


def _group_parts(mps, pf, sid, group):
    """A section group's parts: the group, then the
    flag notes it carries (profile_form.CAL_GROUP_PARTS, by its first
    field), then what the region shows beside it."""
    parts = [{"kind": "section", "sid": sid, "group": group}]
    fields = dict(mps.SECTIONS[sid].groups).get(group) or []
    extra = pf.CAL_GROUP_PARTS.get(fields[0].name) if fields else None
    # no Required chips: an Enforced limit box with no limit refuses the run
    if extra and extra.get("notes"):
        parts.append({"kind": "table", "sid": extra["notes"]})
    if (sid, group) == ("cal", "Calibration"):
        parts += [{"kind": "collection", "sid": "cal_levels", "title": "Calibration levels"},
                  {"kind": "table", "sid": "cal_scale", "title": "Per-analyte calibration range"}]
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
        if sid not in ids:
            continue                # its limits post with another tab's form
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
    # each QC type's tiers, beside their cards, are drawn under the type in
    # the Rules list (tier_branch); this region is the grid that edits them
    colls = [{"kind": "collection", "sid": tier_sections[qc], "qc": qc, "title": "Tiers: " + label,
              "preview": True} for qc, label in QC_TYPES if tier_sections[qc] in ids]
    parts = list(colls)
    parts += [{"kind": "lists", "title": mps.GROUPS_TITLE,
               "lists": [{"qc": x["qc"], "sid": x["sid"]} for x in colls]},
              {"kind": "section", "sid": "groups", "group": None, "preview": True, "bare": True},
              {"kind": "collection", "sid": CELLS_SECTION, "title": mps.QC_CELLS.title, "preview": True}]
    spikes = [sid for sid in ids if sid.startswith("spk_")]
    parts += [{"kind": "spike_hint"}] if spikes else []
    # a spike level edited redraws the tier cards' spike levels (preview)
    parts += [{"kind": "collection", "sid": sid, "title": "Spike levels: " + mps.SPIKE_LABELS[sid[4:]],
               "preview": True} for sid in spikes]
    gridded = dict(QC_TYPES)
    regions[WINDOWS_REGION] = {"id": WINDOWS_REGION, "title": WINDOWS_TITLE, "sec": "windows",
                               "rules": [r["key"] for r in qc_rows(profile, env) if r["code"] in gridded] +
                                        [rules.qc_row_key(c) for c in addable_qc_types(profile) if c in gridded] +
                                        [LOW_LEVEL_RULE[0]],
                               "parts": parts, "open": True}
    regions[BLANK_REGION] = {"id": BLANK_REGION, "title": "Blank limits", "sec": None,
                             "rules": [rules.BLANK_KEY(code) for code, _l in mps.BLANK_TYPES],
                             "parts": [{"kind": "table", "sid": "blk"},
                                       {"kind": "section", "sid": "mxb", "group": None}], "open": False}
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
    return "{0} {1:.3g} \u00d7 RL".format("<" if vals.get("fails_at_limit") else "\u2264", float(v))


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


# The Calibration & CCV criteria each rule judges on: (the Engine's
# required-criteria group, the group's keys). A rule not named here has no
# criteria the Engine can require, so the table cannot tell that a method
# leaves it out, and always draws it.
RULE_CRITERIA = {
    "is_response": ("is_response", ("vs_ical_avg_min", "vs_ical_avg_max")),
    "is_vs_ccv": ("is_response", ("vs_last_ccv_min", "vs_last_ccv_max")),
    "rrt_deviation": ("confirmation", ("rrt_tol_pct", "rt_tol_abs_min")),
    "ion_ratio": ("confirmation", ("ion_ratio_tol_pct",)),
    "sn_min": ("confirmation", ("sn_quan_min", "sn_confirm_min")),
    "cal_r2": ("calibration", ("r2_min",)),
}


def unused_rules(profile, env=None):
    """{row key}: the rule table's rows the method does not use, which the
    table does not draw. Read from the profile's own settings, never from
    which method it is:

    - a rule of RULE_CRITERIA whose limit boxes are all Off
      (limit_states.rule_state) and none of whose criteria holds a value,
      while a drawn rule opens the same limits: a limit set there, or a box
      set Enforced or Evaluate, brings the row back;
    - a QC type's row for a type the method does not hold (no
      qc_acceptance entry) and has stored no state for;
    - a blank's row for a type the method has no entry for, no stored
      state for and no limit for (any one of the three draws it).

    Every other row is drawn: a rule with no such criteria, a blank's row,
    a rule that is on or holds a limit."""
    _cf, mps, _pf, _iso, _ls = _tab_modules()
    rules, _qct = _qc_modules()
    profile = profile or {}
    iv = profile.get("instrument_verification") or {}
    from senaite.pfas import limit_states
    idle = []
    for rule in rules.RULE_LIBRARY:
        key = rule["key"]
        if key in STANDARD_RULES:
            continue                # on Isotope standards, where every one is drawn
        if key not in RULE_CRITERIA or limit_states.rule_state(profile, key) != "off":
            continue
        group, criteria = RULE_CRITERIA[key]
        held = iv.get(group) if isinstance(iv.get(group), dict) else {}
        if any(held.get(c) not in (None, "") for c in criteria):
            continue
        idle.append(key)
    out = set()
    for rule in rules.RULE_LIBRARY:
        if rule["key"] in idle and any(r.get("editor") == rule.get("editor") and r["key"] not in idle
                                       for r in rules.RULE_LIBRARY):
            out.add(rule["key"])
    qca = profile.get("qc_acceptance") or {}
    stored = profile.get("rule_states") or {}
    for r in qc_rows(profile, env):
        if not isinstance(qca.get(r["code"]), dict) and r["key"] not in stored:
            out.add(r["key"])
    limits = mps.read_blank_limits(profile)
    for code, _label in mps.BLANK_TYPES:
        key = rules.BLANK_KEY(code)
        if not isinstance(qca.get(code), dict) and key not in stored and (code,) not in limits:
            out.add(key)
    return out


MDL_WORDS = "Each analyte's MDL, set on Analytes"


def _library_rows(profile, keys, edit=None):
    """One rule table row per rule of the library named in `keys`, in the
    library's order: its state (rulestate.<key>; a state the profile does
    not hold is inherited from the method's default and posts blank, so an
    untouched tab writes nothing), its scope and its effective limits,
    read-only; `edit(key)` gives the row's Limits cell, where a tab has one."""
    _cf, mps, _pf, _iso, _ls = _tab_modules()
    rules, _qct = _qc_modules()
    mid = profile.get("method_id") or ""
    words = _rule_limits(mps, profile)
    states = profile.get("rule_states") if isinstance(profile.get("rule_states"), dict) else None
    toggles = profile.get("rule_toggles") or {}
    bare = dict((k, v) for k, v in profile.items() if k not in ("rule_states", "rule_toggles"))
    names = dict((st, st.capitalize()) for st in rules.STATES)
    from senaite.pfas import limit_placard, limit_states
    rows = []
    for rule in rules.RULE_LIBRARY:
        key = rule["key"]
        if key not in keys:
            continue
        # the rule's state over its limit boxes (limit_states.rule_state):
        # each box carries its own, on its Limits cell
        value = limit_states.rule_state(profile, key)
        name = "rulestate." + key
        default = rules.rule_state(bare, mid, key)
        if key in (states if states is not None else toggles) or \
                any(limit_states.is_stored(profile, b["key"]) for b in limit_states.boxes_of(key)):
            # set here; the edge marks only a state that differs from the default
            state = Cell(value, name=name,
                         source="the default, {0}".format(names[default]) if value != default else None)
        else:
            source = "the rule switch" if states is not None and key in toggles else "the method default"
            state = Cell(value, state="inherited", name=name, source=source)
        if key == "surrogate_recovery":
            # each standard's window, on the Isotope standards tab that draws this row
            limits = Cell(_surrogate_windows(mps, profile), state="readonly")
        elif key == "mdl_check":
            # its card's Edit MDLs; the table draws no button in the cell
            # (its words and placard win): the row opens each analyte's MDL
            # in a window, on the Analytes grid's inputs
            limits = Cell(MDL_WORDS, state="readonly", links=[("Analytes", "#pane-analytes")],
                          title="Each analyte's MDL, on the Analytes tab")
        elif key in NOT_A_LIMIT:
            limits = Cell(words.get(key) or EM_DASH, state="readonly")
        else:
            limits = _limits_cell(words.get(key), value)
        scope = rule["scope"]
        if key == "surrogate_recovery" and window_in_grid(profile):
            scope = rules.SCOPE_STANDARDS      # one window: no matrix classes to vary by
        # each box of the rule, its words and its placard (a rule with no
        # limit of its own: its words, the rule's own box)
        boxes = [b["key"] for b in limit_states.boxes_of(key)]
        if boxes:
            own = {}
            if not any(limit_states.BOX[b]["fields"] for b in boxes) or key in NOT_A_LIMIT:
                own = {boxes[0]: _text(limits.value) or EM_DASH}
            if key == "surrogate_recovery":
                own = {"surrogate_recovery": _text(limits.value) or NOT_SET_WORDS}
            limits.html = limit_placard.cell_html(profile, boxes, own)
        scope_cell = Cell(scope, state="readonly",
                          flags=(DEFAULT_ASIDE,) if state.state == "inherited" else ())
        cells = {"state": state, "scope": scope_cell, "limits": limits}
        if edit is not None:
            cells["edit"] = edit(key)
        rows.append(Row(key, rule["label"], cells))
    return rows


def rules_table(profile, env=None):
    """The QC criteria tab's rule table: one row per rule of the library in
    its order, but the rules Isotope standards holds (STANDARD_RULES, drawn
    and posted there alone), then one per QC type the tab offers (qc_rows, under
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
    limits are on this tab opens their region (rule_editors). A row the
    method does not use (unused_rules) is not drawn and posts nothing, so
    its state stays as stored."""
    _cf, mps, _pf, _iso, _ls = _tab_modules()
    rules, _qct = _qc_modules()
    profile = profile or {}
    env = env or {}
    region_of = {}
    for region in rule_editors(profile, env):
        for key in region["rules"]:
            region_of.setdefault(key, region["id"])

    def edit(key):
        rid = region_of.get(key)
        return Cell("Edit", state="readonly", expands=rid) if rid else None

    # no State column: each limit box carries its own state, on its Limits
    # cell (limit_placard); a QC type's or blank's row posts its presence
    # (Remove, Restore) as a hidden input. No Edit column: the row is the
    # button (rule_row_opens), its region kept on the row's "edit" cell for
    # the List view's cards
    columns = [Column("scope", "Scope", "text"), Column("limits", "Effective limits", "text")]
    unused = unused_rules(profile, env)
    # the rules Isotope standards holds are drawn, and post, there alone
    rows = _library_rows(profile, [r["key"] for r in rules.RULE_LIBRARY
                                   if r["key"] not in unused and r["key"] not in STANDARD_RULES], edit)

    scope = rules.SCOPE_WINDOWS
    gridded = dict(QC_TYPES)
    qc = [r for r in qc_rows(profile, env) if r["key"] not in unused]
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

    # a QC type the method may add: drawn hidden, Enforced as it reads, so it
    # posts what it reads and writes nothing until + Add QC type shows it
    addable = addable_qc_types(profile)
    blank_codes = set(code for code, _l in mps.BLANK_TYPES)
    for code in [c for c in addable if c not in blank_codes]:
        key = rules.qc_row_key(code)
        rows.append(Row(key, _qc_type_label(mps, code), {
            "state": Cell(qc_row_state(profile, code), name="rulestate." + key),
            "scope": Cell(scope, state="readonly"), "limits": Cell(IN_THE_GRID, state="readonly"),
            "edit": edit(key)}, sub=LFSMD_SUB if code == "LFSMD" else QC_ROW_SUB, hidden=True,
            data={"addable": code}))

    rows.append(Row(LOW_LEVEL_RULE[0], LOW_LEVEL_RULE[1], {
        "state": Cell(rules.rule_state(profile, None, rules.LOW_LEVEL_ROW), name=LOW_LEVEL_STATE),
        "scope": Cell(scope, state="readonly"), "limits": Cell(IN_THE_GRID, state="readonly"),
        "edit": edit(LOW_LEVEL_RULE[0])}))

    blank_vals = mps.read_blank_limits(profile)
    for code, label in mps.BLANK_TYPES:
        key = rules.BLANK_KEY(code)
        new = code in addable
        if key in unused and not new:
            continue
        value = qc_row_state(profile, code)
        rows.append(Row(key, label, {"state": Cell(value, name="rulestate." + key),
                                     "scope": Cell(rules.SCOPE_METHOD, state="readonly"),
                                     "limits": _limits_cell(_blank_words(blank_vals.get((code,))), value),
                                     "edit": edit(key)},
                        sub=BLANK_SUB, hidden=new, data={"addable": code} if new else None))
    offered = [r["code"] for r in qc] + [c for c in addable if c not in blank_codes] + \
        [code for code, _l in mps.BLANK_TYPES if rules.BLANK_KEY(code) not in unused or code in addable]
    hidden = [Cell(",".join(offered), name="qc_offered")]
    from senaite.pfas import limit_placard, limit_states
    # a QC type's or blank's presence (its row's state as stored: Off is
    # Removed), written by Remove and Restore
    for r in rows:
        code = rules.qc_row_code(r.key)
        if code is not None:
            hidden.append(Cell(_text(r.cells["state"].value), name="rulestate." + r.key, data={"kind": "rule"}))
            tier_keys = [limit_states.tier_key(code, t) for t in limit_states.tiers(profile, code) if t.get("name")]
            if tier_keys:
                r.cells["limits"].html = limit_placard.cell_html(profile, tier_keys)
    for r in rows:
        _open_row(r)
    _tail_applies(rows, profile)
    # every limit box this tab holds posts its state once, here
    std_boxes = set(b["key"] for k in STANDARD_RULES for b in limit_states.boxes_of(k)) | \
        set(limit_states.RUN_BOXES)
    hidden += [Cell(v, name=n, data={"kind": "rule"}) for n, v in limit_placard.hidden_values(
        profile, limit_placard.keys(profile, boxes=[b["key"] for b in limit_states.BOXES if b["key"] not in std_boxes]))]
    return Sheet("rules", columns, rows, selection=False, picker=False, form=QC_FORM, hidden=hidden)


EDIT_LIMITS_WORDS = "Edit limits"


def rule_row_opens(key, region):
    """What a rule table row opens on a click, Enter or Space: (the card of
    the List view holding the trigger, that trigger's key), whose window
    gives the focus back to the row; or None, where no window edits the
    rule's limits, and the row opens its region in place. The Calibration
    group's rules open the Calibration window, a group card's rule its
    limits window, MDL Check the window of each analyte's MDL (the Analytes
    grid's own inputs)."""
    if key == "mdl_check":
        return key, "link0"
    group = rule_group(key)
    if group == CAL_GROUP:
        return CAL_GROUP_KEY, "cal"
    if region and QC_GROUP_KEYS.get(group) and region != WINDOWS_REGION:
        return key, "limits"
    return None


def _open_row(row):
    """A rule table row made the button: what it opens (rule_row_opens),
    its region, and its one menu entry, which opens the same."""
    e = row.cells.get("edit")
    region = e.expands if e is not None else None
    opens = rule_row_opens(row.key, region)
    if opens is None and not region:
        return
    from senaite.pfas import row_menu
    words = MDL_EDIT_WORDS if row.key == "mdl_check" else EDIT_LIMITS_WORDS
    data = dict(row.data or {})
    data.update({"rule-open": row.key, "row-region": region,
                 "rule-card": opens[0] if opens else None, "rule-act": opens[1] if opens else None,
                 "row-actions": row_menu.actions((words, "event", "rule-open"))})
    row.data = dict((k, v) for k, v in data.items() if v is not None)


def _surrogate_windows(mps, profile):
    """The surrogate windows the Isotope standards tab holds, in words: one
    per standard where the Engine judges standards on their own limits,
    else the method's one surrogate window when it is set."""
    if mps._engine_module().engine(profile)["eis_recovery_limits"]:
        n = len(mps.EIS_GRID.read(profile))
    else:
        # the window the worker judges with: the profile's own, else the method text's
        n = 0 if mps._engine_module().surrogate_window(profile) is None else 1
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
                    said.append((mps.window_text(c["window"], qc_type), c["index"], c.get("set_by"),
                                 tuple(_blank_offs(mps, profile, kw, m))))
        alike.setdefault(tuple(said), []).append(m)
    shared = max(alike.values(), key=len) if alike else []
    if len(shared) < 2:
        return [(m, [m]) for m in matrices]
    return [("All {0} matrices".format(len(shared)), shared)] + [(m, [m]) for m in matrices if m not in shared]


def _blank_types(mps, profile):
    """[(QC type, name)]: the extracted blanks the method holds, each of
    which a cell may switch off for one analyte in one matrix."""
    return [(q, label) for q, label in mps.cell_qc_choices(profile) if q in mps.CELL_BLANK_TYPES]


def _blank_offs(mps, profile, kw, matrix):
    """The blank types switched off for `kw` in `matrix`."""
    qt = mps._qc_tiers()
    return [q for q, _l in _blank_types(mps, profile)
            if (qt.cell_setting(profile, q, kw, matrix) or {}).get("off")]


def _tier_words(mps, cells, qc_type):
    """What a group row says it takes, from its cells in every matrix, each
    tier by its name in words (_tier_label): "· X lo – hi"; where a tier for listed
    matrices sets some, "· A lo – hi where listed, else B lo – hi"; "· no
    tier" where none applies."""
    seen = OrderedDict()
    for c in cells:
        seen.setdefault(c["index"], c)

    def said(c):
        if c["index"] is None:
            return "no tier"
        window = mps.window_text(c["window"], qc_type) if c["window"] is not None else "no window"
        return "{0} {1}".format(_tier_label(c["tier"]), window)

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
OFF_WORDS = "off"            # a cell set off: that analyte is not judged there
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
    """{collection id: {row name: row index}}: where each tier sits in the
    tier collections a page posted, and each spike level (by its label) in
    the spike level collections. A preview resolves them as edited (a
    cleared name removes a row, so later rows move up), while the page's
    rows keep their own indices: the drawer must edit the row that holds
    the tier or level it names."""
    cf, mps, _pf, _iso, _ls = _tab_modules()
    out = {}
    colls = [(sid, mps.SECTIONS[sid]) for _qc, sid in TIER_SECTIONS]
    colls += [("spk_" + q, mps.SPIKE_LEVELS[q]) for q in sorted(mps.SPIKE_LEVELS)]
    for sid, coll in colls:
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


def _box_key(mps, profile, qc_type, c, kw, matrix):
    """What two window cells must share to be drawn as one box: the window,
    the tier that sets it and how (a box never stands for cells that open
    different tiers), whether it is off there, and the blanks switched off
    there, as _matrix_columns compares matrices."""
    return (mps.window_text(c["window"], qc_type), c["index"], c.get("set_by"), bool(c.get("off")),
            tuple(_blank_offs(mps, profile, kw, matrix)))


def _mark_boxes(members, keys, prefix):
    """Each cell of a group's rows inside a box of equal neighbours
    (merge_boxes) names its box (data-box), the box's sides it draws
    (data-box-edge: t, r, b, l) and, on the box's first cell, data-box-lead:
    the one cell whose words show. Every cell keeps its own data and
    drawer."""
    for (r, c), (top, first, last, end) in merge_boxes(keys).items():
        cell = members[r].get("m-{0}".format(c))
        if cell is None:
            continue
        data = dict(cell.data or {})
        data["box"] = "box-{0}-{1}-{2}".format(prefix, top, first)
        data["box-edge"] = " ".join(e for e, on in (("t", r == top), ("r", c == end), ("b", r == last),
                                                    ("l", c == first)) if on)
        if (r, c) == (top, first):
            data["box-lead"] = "1"
        cell.data = data


def windows_sheet(profile, env=None, qc_type="LFSM", level="ordinary", posted=None, kept=False, order=None):
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
    A tier that applies but sets no window is still the cell's tier.
    `kept`: a QC type whose rule row is Off draws the windows it keeps (the
    QC criteria tab greys them, windows_box); elsewhere it draws none."""
    cf, mps, _pf, _iso, _ls = _tab_modules()
    profile = profile or {}
    qc_type = shown_qc_type(profile, qc_type)
    if kept:
        profile = drawn_as_run(profile, qc_type)    # Off: its kept windows, greyed
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

    blanks = _blank_types(mps, profile)

    def own_data(kw, m, ms):
        """What the drawer sets on this cell: the analyte, the matrices the
        cell stands for, its own setting ("window", "off" or none) and each
        blank the method holds, judged here or off."""
        own = mps._qc_tiers().cell_setting(profile, qc_type, kw, m) or {}
        offs = _blank_offs(mps, profile, kw, m)
        lo, hi = ends(mps.tier_window(mps._qc_tiers().cell_tier(None, own), qc_type)) if own and not own.get("off") \
            else ("", "")
        return {"analyte": kw, "matrices": json.dumps(list(ms)), "own-kind": "rpd" if rpd else "window",
                "own": "off" if own.get("off") else (
                    "window" if own else ""), "own-lo": lo, "own-hi": hi,
                "blanks": json.dumps([{"qc": q, "label": label, "off": q in offs} for q, label in blanks])}

    def cell(c, kw, m, column, ms):
        label = " \u00b7 ".join([titles.get(kw, kw), column, qc_label])
        if c.get("set_by") == "own":
            under = ends(c["fallback_window"])
            data = {"title": label, "qc": qc_type, "coll": coll_id, "prefix": "", "set-kind": "own",
                    "lo": ends(c["window"])[0], "hi": ends(c["window"])[1],
                    "window": "Not judged" if c.get("off") else mps.window_text(c["window"], qc_type) + unit,
                    "set-by": "This cell", "tier": "", "tier-name": _tier_label(c.get("fallback_tier") or ""),
                    "tier-lo": under[0], "tier-hi": under[1],
                    "fallback-is-default": "1" if c.get("fallback_default") else "",
                    "method-lo": method_ends[0], "method-hi": method_ends[1], "new-group": ""}
            data.update(own_data(kw, m, ms))
            if c.get("off"):
                return Cell(OFF_WORDS, state="set", source="This cell", data=data,
                            title="Not judged for {0} in {1}: set on this cell".format(titles.get(kw, kw), column))
            return Cell(value(c["window"]), state="set", source="This cell", data=data,
                        title="Set on this cell for {0}".format(titles.get(kw, kw)))
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
                     "tier-name": _tier_label(c.get("fallback_tier") or ""), "tier-lo": under[0], "tier-hi": under[1],
                     "method-lo": method_ends[0], "method-hi": method_ends[1]})
        if new:
            sets, lost = proposal(len(tiers) if c["index"] is None else c["index"], new[0], new[1], listed)
            data["new-covers"] = sets
            data["new-shadows"] = "; ".join("{0} would no longer set any cell".format(n) for n in lost)
        data.update(own_data(kw, m, ms))
        if winner is None:
            data.update({"window": "No window", "set-by": "No tier", "fallback": "No window", "default": "",
                         "tier": "", "tier-group": "", "tier-scope": "", "covers": ""})
            return Cell(value(None), state="off",
                        title="No window" if runs else "{0} is not run".format(qc_label), data=data)
        if c["window"] is None:          # a tier that sets no window still sets the cell
            data.update({"window": "No window", "set-by": "{0}, no window".format(c["source"]),
                         "fallback": "No window" if c["fallback_window"] is None else "{0} {1}".format(
                             c["fallback"], mps.window_text(c["fallback_window"], qc_type)),
                         "default": "1" if c["default"] else "", "tier": _tier_label(winner.get("name")),
                         "tier-group": group_words.get(winner.get("analyte_group") or "all", ""),
                         "tier-scope": scope_words.get(winner.get("matrix_scope") or "all", ""),
                         "covers": covered(c["index"])})
            return Cell(value(None), state="off", title="No window", data=data)
        data.update({
            "window": mps.window_text(c["window"], qc_type) + unit, "set-by": c["source"],
            "fallback": "No window" if c["fallback_window"] is None else "{0} {1}".format(
                c["fallback"], mps.window_text(c["fallback_window"], qc_type)),
            "default": "1" if c["default"] else "", "tier": _tier_label(winner.get("name")),
            "tier-group": group_words.get(winner.get("analyte_group") or "all", ""),
            "tier-scope": scope_words.get(winner.get("matrix_scope") or "all", ""),
            "covers": covered(c["index"])})
        if c.get("set_by") == "cell":
            return Cell(value(c["window"]), state="set", source=c["source"], data=data,
                        title="Set on this cell by {0}".format(c["source"]))
        return Cell(value(c["window"]), state="inherited", source=c["source"], data=data)

    def words(window, c=None):
        if (c or {}).get("off"):
            return OFF_WORDS
        return mps.window_text(window, qc_type) if window is not None else NO_WINDOW_WORDS

    # the rows of each group: alphabetical; `order` "quant" sorts them by
    # what quantifies each analyte first (its Quantified by's label)
    by = None
    if order == "quant":
        by = dict((r.get("analyte"), titles.get(r.get("surrogate_is"), r.get("surrogate_is")))
                  for r in profile.get("surrogate_map") or () if isinstance(r, dict))
    groups, rows, box_keys, tier_of = [], [], [], {}
    for g in grid["rows"]:
        gcells = {}
        for j, i, _label, _ms in firsts:
            c = g["cells"][i]
            gcells["m-{0}".format(j)] = Cell(value(c["window"]), state="readonly" if c["window"] is not None
                                              else "off", title=c["source"])
        held, flagged, members, keys = [], False, [], []
        for kw in analyte_order(g["keys"], titles, by=by):
            cells, off, said, row_keys = {}, False, [], []
            for j, i, label, ms in firsts:
                m = matrices[i]
                if not included(kw, m):
                    # not reported in this column's matrices: said so, never blank
                    cells["m-{0}".format(j)] = Cell(None, state="na", title="{0} is not reported in {1}".format(
                        titles.get(kw, kw), ", ".join(ms)))
                    said.append(None)
                    row_keys.append(None)
                    continue
                c = g["analytes"][kw][i]
                cells["m-{0}".format(j)] = cell(c, kw, m, label, ms)
                # the tier the cell falls to: the one that sets it, or under
                # its own setting the tier it falls back to (tier_tree)
                own_of = c.get("fallback_tier") if c.get("set_by") == "own" else None
                tier_of[(kw, "m-{0}".format(j))] = (c["index"] if c.get("set_by") != "own" else
                                                    next((x for x, t in enumerate(tiers)
                                                          if own_of and t.get("name") == own_of), None))
                off = off or (c["window"] is None and not c.get("off"))
                said.append(words(c["window"], c))
                row_keys.append(_box_key(mps, profile, qc_type, c, kw, m))
            held.append((titles.get(kw, kw), said))
            flagged = flagged or (off and runs)
            keys.append(row_keys)
            members.append(cells)
            rows.append(Row(kw, titles.get(kw, kw), cells, group=g["key"],
                            flags=("no_window",) if off and runs else ()))
        _mark_boxes(members, keys, "{0}-{1}".format(qc_type, g["key"]))
        box_keys.append((g["key"], keys))
        summary = group_summary(held, spans, [words(g["cells"][i]["window"]) for _j, i, _l, _m in firsts]) \
            if held else None
        # a member flagged NO WINDOW flags its group row too: folding never hides it
        groups.append(Row(g["key"], g["title"], gcells, selectable=False,
                          sub=_tier_words(mps, g["cells"], qc_type), summary=summary,
                          flags=("no_window",) if flagged else ()))
    # every group folds to its row; the page remembers the open ones per
    # QC type shown
    sheet = Sheet("windows", columns, rows, groups=groups, selection=False, picker=False, form=QC_FORM,
                  fold=qc_type)
    # each group's cell keys, as merge_boxes drew them (merge_counts)
    sheet.box_keys = box_keys
    # (analyte, column) -> the index of the tier the cell falls to, for the
    # tier boxes of the List view (tier_analytes)
    sheet.tier_of = tier_of
    return sheet


def preview_windows(stored, form, env=None):
    """The window grid for a QC criteria form AS EDITED, not saved: the
    groups and the tier collections parsed and applied as a save does, then
    drawn for the QC type and spike level the form asks for, each cell
    naming the row the page posted its tier in.
    (html, errors); nothing is written."""
    cf, mps, _pf, _iso, _ls = _tab_modules()
    ids = qc_section_ids(stored)
    profile = stored
    for sid in ["groups"] + [t for _q, t in TIER_SECTIONS if t in ids] + [CELLS_SECTION]:
        updates, errors = cf.parse(mps.SECTIONS[sid], form, stored, env)
        if errors:
            return "", errors
        profile = cf.apply(mps.SECTIONS[sid], profile, updates, env)
    qc_type = (form or {}).get("qc_type") or "LFSM"
    level = (form or {}).get("level") or "ordinary"
    # each low-level tier carries its own state (limit_placard): the low
    # level's windows grey with no row of their own
    sheet = windows_sheet(profile, env, qc_type, level, posted=posted_tier_rows(form), kept=True)
    return render_sheet(None, sheet), []


def windows_box(profile, env, qc_type, inner):
    """The grid's region, <div id="qc-windows">, greyed while the QC type it
    shows is Off (mute_attrs), as the page draws it and the preview redraws it."""
    qc_type = shown_qc_type(profile, qc_type)
    mute = dict(mute_attrs(profile, env, qc_type))
    note = _tag("p", [("class", "pfas-hier-note mp-qc-off-note")],
                _esc(OFF_WINDOWS_NOTE.format(dict(QC_TYPES)[qc_type])))
    return _tag("div", [("id", "qc-windows"), ("class", mute.pop("class", None))] + sorted(mute.items()),
                note + inner)


def preview_tree(stored, form, env=None):
    """The tiers as the rules list draws them (tier_trees) for a QC criteria
    form AS EDITED, not saved: the groups, the tier collections, the cell
    settings and the spike levels parsed and applied as a save does -- a
    section that does not parse is drawn as stored --, each tier naming the
    row the page posted it in. Nothing is written."""
    cf, mps, _pf, _iso, _ls = _tab_modules()
    ids = qc_section_ids(stored)
    profile = stored
    for sid in (["groups"] + [t for _q, t in TIER_SECTIONS if t in ids] + [CELLS_SECTION] +
                [sid for sid in ids if sid.startswith("spk_")]):
        updates, errors = cf.parse(mps.SECTIONS[sid], form, stored, env)
        if not errors:
            profile = cf.apply(mps.SECTIONS[sid], profile, updates, env)
    return tier_trees(profile, env, posted=posted_tier_rows(form))

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
    windows the grid shows, shown_qc_type) and the spike-level segment.
    Every QC type is offered; one whose rule row is Off is greyed, its
    windows drawn greyed too (data-mute-if on the row's posted state).
    The Low level choice is off while no QC type the method runs has a
    low-level tier; each low-level tier carries its own state (its placard,
    limit_placard), so the choice greys with no row. Show switches on the
    page without a redraw, so it writes its value into a field of its own
    that posts nothing (qc-show). The legend line follows the pickers."""
    _cf, mps, _pf, _iso, _ls = _tab_modules()
    rules, _qct = _qc_modules()
    profile = profile or {}
    qc_type = shown_qc_type(profile, qc_type)
    has_low = any(t.get(mps.LOW_LEVEL_KEY) for q, _l in QC_TYPES if _runs(profile, q) for t in mps._tiers(profile, q))
    level = level if level in dict(QC_LEVELS) and (has_low or level == "ordinary") else "ordinary"
    unused = unused_rules(profile, env)

    def follows_row(q):
        if rules.QC_TYPE_KEY(q) in unused:
            return []                      # no row drawn to follow: the choice stays as drawn
        return [("data-mute-if", "rulestate." + rules.QC_TYPE_KEY(q)), ("data-mute-values", "off")]

    def follows_low_level(v):
        # each low-level tier carries its own state (limit_placard): the
        # choice follows no row
        return []
    shown = _tag("input", [("type", "hidden"), ("id", SHOW_FIELD), ("name", SHOW_FIELD),
                           ("form", "pfas-no-form"), ("value", qc_type)])
    segs = _segment([("data-qc-seg", True), ("aria-label", "QC type"), ("data-field", True),
                     ("data-input", SHOW_FIELD)], QC_TYPES, qc_type, item_attrs=follows_row)
    segs += _segment([("data-level-seg", True), ("aria-label", "Spike level")], QC_LEVELS, level,
                     disabled=() if has_low else ("low",), item_attrs=follows_low_level)
    return _tag("div", [("class", "pfas-pill-row")], shown + segs) + WINDOWS_LEGEND



# ── the tier view: each tier of a QC type, as a list beside its card ────────
# Drawn from the engine's own selection (qc_tiers.base_tier, cell_setting,
# low_level_candidates), never a second resolver; read-only: it posts nothing.

TREE_ID = "qc-tree"
# the fields a tier of another QC type may share with a tier of the same name
PAIR_FIELDS = (("analyte_group", "Applies to"), ("matrix_scope", "Matrices"), ("matrices", "Matrix list"),
               ("low_level_x_rl", "Low level"), ("recovery_min", "Recovery min"),
               ("recovery_max", "Recovery max"), ("rsd_max", "RSD max"), ("rpd_max", "Max RPD"))
# what an LFSMD tier takes from the LFSM tier of its name: the tier head
# both collections store (LFSMD stores no window of its own)
FOLLOW_FIELDS = (("analyte_group", "Applies to"), ("matrix_scope", "Matrices"), ("matrices", "Matrix list"),
                 ("low_level_x_rl", "Low level"))
# the QC types whose spike levels a QC type uses (LFSMD shares the LFSM levels)
SPIKES_OF = {"LFSM": "LFSM", "LFSMD": "LFSM", "LFB": "LFB"}
CATEGORIES = 6                       # the tier palette, --tier-c0..5
NOT_JUDGED = "Not judged"
NOT_SET = "not set"
# a sub-group set off is drawn as a muted dash with a notation mark; its
# footnote, once under the list and once under its card, says why
OWN_CELLS = "Own cells"
OFF_MARK = '<span class="pfas-sheet-val is-empty">\u2014</span><sup>1</sup>'
OFF_NOTE = "Not judged in these cells: each is set off on its own."
# a QC type whose rule row is Off: its tiers and windows kept, greyed
OFF_WINDOWS_NOTE = "{0} is Off in the rules: these windows are kept and judge nothing until it is set to Evaluate or Enforced."
OFF_TYPE_NOTE = "{0} is Off in the rules: these tiers are kept and judge nothing until it is set to Evaluate or Enforced."


def _stores(tier, key):
    """Does `tier` store `key` with a value (None and "" are not one)?"""
    return key in tier and tier.get(key) not in (None, "")


def _same_fields(a, b):
    """The fields two tiers both store with one value: what a paired tier
    shares, and nothing it does not store itself."""
    return [k for k, _l in PAIR_FIELDS if _stores(a, k) and _stores(b, k) and a.get(k) == b.get(k)]


def _index_of(tiers, tier):
    """`tier`'s row in its stored list, by identity (two rows may hold equal values)."""
    return next(i for i, t in enumerate(tiers) if t is tier)


def _limit_words(mps, window, qc_type):
    """A window or RPD limit in words, with its unit; "" for none."""
    if window is None:
        return ""
    return mps.window_text(window, qc_type) + " %"


def _ends(window, rpd):
    """(lo, hi) of a window for its bar: an RPD limit runs from 0."""
    if window is None:
        return None
    if rpd:
        return (0.0, float(window))
    lo, hi = window
    if lo is None or hi is None:
        return None
    return (float(lo), float(hi))


def _spike_rows(mps, profile, qc_type, matrices, posted=None):
    """[{label, row, values: [(matrix, words, unit, set)]}]: the spike levels
    of the matrices `matrices` the QC type uses, as stored, each with the row
    of the spike level collection that holds it (`posted` maps a level's
    label to the row a page posted it in, as posted_tier_rows)."""
    from senaite.pfas import calibration_levels as cl
    spk = SPIKES_OF.get(qc_type)
    if not spk or "spk_" + spk not in qc_section_ids(profile):
        return []
    at = (posted or {}).get("spk_" + spk) or {}
    rows = []
    for i, r in enumerate(mps.SPIKE_LEVELS[spk].read(profile)):
        values = []
        for m in matrices:
            v = r.get(m)
            values.append({"matrix": m, "value": _g(v) if v is not None else NOT_SET,
                           "unit": cl.matrix_unit(profile, m), "set": v is not None})
        label = _text(r.get("label"))
        rows.append({"label": label, "row": at.get(label.strip(), i), "values": values})
    return rows


def spikes_of(profile, qc_type):
    """The spike level collection a QC type's spikes are set in, where the
    page draws it ("spk_LFSM" for LFSM and LFSMD), else ""."""
    spk = SPIKES_OF.get(qc_type)
    sid = "spk_" + spk if spk else ""
    return sid if sid and sid in qc_section_ids(profile or {}) else ""


def _pairs(mps, profile, qc_type, tier):
    """The tiers of the other QC types the method holds stored under
    `tier`'s name (an ordinary tier with an ordinary one, a low-level tier
    with a low-level one), each with its own limit and the fields both store
    alike: a pairing by name alone, never by position or by values."""
    qca = (profile or {}).get("qc_acceptance") or {}
    low = bool(tier.get(mps.LOW_LEVEL_KEY))
    out = []
    for q, label in QC_TYPES:
        if q == qc_type or q not in qca:
            continue
        for y in mps._tiers(profile, q):
            if _text(y.get("name")) != _text(tier.get("name")) or bool(y.get(mps.LOW_LEVEL_KEY)) != low:
                continue
            yw = mps.tier_window(y, q)
            same = _same_fields(tier, y)
            out.append({"qc": q, "label": label, "name": _text(y.get("name")), "window": yw,
                        "ends": _ends(yw, q in mps.RPD_QC_TYPES),
                        "text": _limit_words(mps, yw, q) or "no window",
                        "same": same, "same_labels": [l for k, l in PAIR_FIELDS if k in same],
                        "differs": [l for k, l in FOLLOW_FIELDS if _held(tier.get(k)) != _held(y.get(k))]})
    return out


def _held(value):
    """A tier field as compared for following: unset is one value, a list
    compared whatever its order."""
    if value in (None, "", []):
        return None
    return sorted(value) if isinstance(value, (list, tuple)) else value


# an LFSMD tier as the engine judges it: its own RPD; its recovery against
# the window of the LFSM tier of its name, at the LFSM's spike level
AS_LFSM = "As LFSM: analytes, matrices, low level, recovery window"


def _follows_pair(qc, pair):
    """Whether `pair` is the LFSM / LFSMD partner of a `qc` tier: an LFSMD
    tier takes its same-named LFSM tier's analytes, matrices and low level."""
    return set([qc, pair["qc"]]) == set(["LFSM", "LFSMD"])


def _pair_words(qc, pair):
    """What a paired tier's tile says under it: for LFSM and LFSMD whether
    the LFSMD tier follows (or which of its fields do not yet); for any other
    pair what both store alike."""
    if not _follows_pair(qc, pair):
        return _same_words(pair)
    if pair["differs"]:
        return "Not as LFSM yet: " + ", ".join(l[0].lower() + l[1:] for l in pair["differs"])
    return "Follows this tier" if qc == "LFSM" else AS_LFSM


def every_tier_limits(profile):
    """[words]: the limits that apply under every tier, where the method
    stores one tier for all analytes and matrices: the sample duplicate's RPD
    and each blank's limit. A QC type or blank whose rule row is Off judges
    nothing and is not named."""
    _cf, mps, _pf, _iso, _ls = _tab_modules()
    rules, _qct = _qc_modules()
    qca = (profile or {}).get("qc_acceptance") or {}
    out = []

    def single(code):
        entry = qca.get(code)
        if not isinstance(entry, dict) or not entry.get("enabled", True):
            return None
        key = rules.qc_row_key(code)
        if key and rules.rule_state(profile, None, key) == "off":
            return None
        tiers = [t for t in entry.get("tiers") or [] if isinstance(t, dict)]
        if len(tiers) != 1:
            return None
        t = tiers[0]
        if (t.get("analyte_group") or "all") != "all" or (t.get("matrix_scope") or "all") != "all" \
                or t.get(mps.LOW_LEVEL_KEY):
            return None
        return t
    dup = single("Dup")
    if dup is not None and dup.get("rpd_max") is not None:
        out.append("{0} RPD \u2264 {1} %".format(RUN_LABELS.get("Dup", "Dup"), _g(dup["rpd_max"])))
    for code, label in mps.BLANK_TYPES:
        t = single(code)
        words = _blank_words(t) if t is not None else ""
        if words:
            out.append("{0} {1}".format(label, words))
    return out


# the analyte groups a core tier may apply to: those the engine falls back on
def core_tier(ordinary):
    """The QC type's core tier (method_profile_sections.core_tier)."""
    return _tab_modules()[1].core_tier(ordinary)


def adds_with(profile, qc_type):
    """The QC type whose tiers this type's are added and removed with: LFSM
    for LFSMD while the method holds LFSM tiers (an LFSMD tier follows the
    LFSM tier of its name), else ""."""
    _cf, mps, _pf, _iso, _ls = _tab_modules()
    return "LFSM" if qc_type == "LFSMD" and mps._tiers(profile or {}, "LFSM") else ""


def tier_tree(profile, env=None, qc_type="LFSM", posted=None):
    """The tier view of `qc_type`: its ordinary tiers in stored order, each
    with its row's name prefix in the page's tier collection (`posted` maps a
    tier name to the row a page posted it in, as windows_sheet), its window,
    spread limit, analyte group and matrices, its colour (its row, as the
    grid's swatch), the low-level tiers that may replace it, the tiers of the
    other QC types the method holds that share its stored name (with the
    fields both store alike), the analytes it covers in each matrix the panel
    reports them in -- the engine's own choice, base_tier with the flags the
    engine selects by --, the cells set on their own that fall back to it,
    grouped by setting, and the spike levels of its matrices. A tier the
    engine cannot resolve is a problem in words, never a guess. Plain data:
    no input names."""
    cf, mps, _pf, _iso, _ls = _tab_modules()
    qt = mps._qc_tiers()
    stored = profile or {}
    qc_type = qc_type if qc_type in dict(QC_TYPES) else "LFSM"
    profile = drawn_as_run(stored, qc_type)         # Off: its kept tiers, greyed
    rpd = qc_type in mps.RPD_QC_TYPES
    qca = profile.get("qc_acceptance") or {}
    tiers = mps._tiers(profile, qc_type)
    sid = dict(TIER_SECTIONS)[qc_type]
    coll_id = sid if sid in qc_section_ids(profile) else ""
    at = (posted or {}).get(coll_id) or {}
    group_words = dict(mps.GROUP_CHOICES)
    titles = mps._analyte_titles(profile)
    matrices = list(profile.get("supported_matrices") or [])
    inclusion = profile.get("analyte_matrix_inclusion") or {}
    flags = mps.engine_flags(profile)
    ordinary = [t for t in tiers if not t.get(mps.LOW_LEVEL_KEY)]
    core = core_tier(ordinary)

    def prefix(index):
        if not coll_id:
            return ""
        row = at.get(_text(tiers[index].get("name")).strip(), index)
        return "__".join(["c", cf._enc(coll_id), _text(row)]) + "__"

    # what the engine gives each analyte in each matrix it is reported in
    covers = OrderedDict((id(t), OrderedDict()) for t in ordinary)
    subs = OrderedDict((id(t), OrderedDict()) for t in ordinary)
    problems = []
    for kw in profile.get("master_analyte_set") or []:
        k, n = flags.get(kw, (False, False))
        for m in matrices:
            if not _reported(inclusion, kw, m):
                continue
            try:
                chosen = qt.base_tier(profile, qc_type, m, k, n)
            except qt.Unconfigured as e:
                if _text(e) not in problems:
                    problems.append(_text(e))
                continue
            if chosen is None:
                continue                      # the QC type is off: nothing is judged
            base = chosen[0]
            if id(base) not in covers:        # the only tiers are low-level ones
                continue
            own = qt.cell_setting(profile, qc_type, kw, m)
            if own is None:
                covers[id(base)].setdefault(kw, []).append(m)
                continue
            if own.get("off"):
                key = ("off",)
            else:
                key = ("window", mps.tier_window(qt.cell_tier(None, own), qc_type))
            subs[id(base)].setdefault(key, OrderedDict()).setdefault(kw, []).append(m)

    def covered(by):
        return [{"analyte": kw, "title": _text(titles.get(kw, kw)), "matrices": ms} for kw, ms in by.items()]

    out_tiers = []
    for n_, t in enumerate(ordinary):
        i = _index_of(tiers, t)
        window = mps.tier_window(t, qc_type)
        own_ms = [m for m in qt.tier_matrices(profile, t) if m in matrices] if qt.is_listed(t) else list(matrices)
        # the low-level tiers that may replace it, in any matrix it applies in
        lows = OrderedDict()
        for m in own_ms:
            for x in qt.low_level_candidates(profile, qc_type, t, m):
                lows.setdefault(id(x), (x, []))[1].append(m)
        low_out = []
        for x, ms in lows.values():
            j = _index_of(tiers, x)
            lw = mps.tier_window(x, qc_type)
            low_out.append({"index": j, "prefix": prefix(j), "name": _text(x.get("name")),
                            "label": _tier_label(x.get("name")),
                            "box": _tier_box(profile, qc_type, x),
                            "x_rl": _g(x.get(mps.LOW_LEVEL_KEY)), "window": lw, "ends": _ends(lw, rpd),
                            "text": _limit_words(mps, lw, qc_type) or "no window", "matrices": ms,
                            "category": j % CATEGORIES, "pairs": _pairs(mps, profile, qc_type, x)})
        pairs = _pairs(mps, profile, qc_type, t)
        sub_out = []
        for j, (key, by) in enumerate(subs[id(t)].items()):
            off = key[0] == "off"
            w = None if off else key[1]
            sub_out.append({"key": j, "off": off, "window": w, "ends": None if off else _ends(w, rpd),
                            "text": NOT_JUDGED if off else (_limit_words(mps, w, qc_type) or "no window"),
                            "covers": covered(by)})
        spread = None if rpd else qt.spread_limit(t)
        out_tiers.append({
            "index": i, "prefix": prefix(i), "name": _text(t.get("name")), "position": n_ + 1,
            "label": _tier_label(t.get("name")),
            "category": i % CATEGORIES, "core": t is core, "box": _tier_box(profile, qc_type, t),
            "analyte_group": t.get("analyte_group") or "all",
            "group_label": _text(group_words.get(t.get("analyte_group") or "all", t.get("analyte_group"))),
            "listed": qt.is_listed(t), "matrices": own_ms,
            "recovery_min": None if rpd else t.get("recovery_min"),
            "recovery_max": None if rpd else t.get("recovery_max"),
            "rpd_max": t.get("rpd_max") if rpd else None,
            "window": window, "ends": _ends(window, rpd),
            "text": _limit_words(mps, window, qc_type) or "no window",
            "spread": spread, "spread_text": "{0} \u2264 {1} %".format("RSD", _g(spread)) if spread is not None else "",
            "low_level": low_out, "pairs": pairs, "covers": covered(covers[id(t)]), "subs": sub_out,
            "spikes": _spike_rows(mps, profile, qc_type, own_ms, posted),
            # the tier's own Flag tile, last on its card
            "flag_tile": render_flag_tile(_owner(qc_type), stored, env,
                                          tier=(qc_type, rule_flags_name(t, i)),
                                          title="{0} {1}".format(dict(QC_TYPES)[qc_type], _tier_label(t.get("name"))))})
    if qc_type in GRID_TIER_TYPES and qc_type in qca:
        # the window grid as the Table view draws it, each cell under the
        # tier it falls to: what the tier's box shows in the List view
        sheet = windows_sheet(stored, env, qc_type, "ordinary", posted=posted, kept=True)
        for t in out_tiers:
            t["analytes"] = tier_analytes(sheet, t["index"], titles, t["matrices"])
    return {"qc": qc_type, "label": dict(QC_TYPES)[qc_type], "rpd": rpd, "held": qc_type in qca,
            "runs": _runs(stored, qc_type), "off": qc_is_off(stored, qc_type),
            "mute": mute_attrs(stored, env, qc_type), "tiers": out_tiers, "problems": problems,
            "collection": bool(coll_id) and qc_type in qca, "adds_with": adds_with(stored, qc_type),
            "matrix_count": len(matrices), "spikes_of": spikes_of(stored, qc_type),
            "every": every_tier_limits(stored)}


def _band(ends, thin=False, attrs=(), scale=None):
    """A range on the 0 - 200 % axis (PCT_SCALE), or on `scale` (lo, hi), an
    axis of its own (a temperature's, below zero too: its zero marked): the
    page sets the bar's ends from data-lo / data-hi (PFAS.components.hier
    .band). With `attrs` (a part the page redraws) a missing range is a
    hidden, empty bar, so the part is always there to be replaced."""
    _cf, mps, _pf, _iso, _ls = _tab_modules()
    axis = [("data-min", _g(scale[0]) if scale else None), ("data-scale", _g(scale[1] if scale else mps.PCT_SCALE[1]))]
    bar = _tag("span", [("class", "pfas-band-bar")], "")
    if ends is None:
        if not attrs:
            return ""
        if scale:
            return _tag("span", [("class", "pfas-band is-axis"), ("aria-hidden", "true")] + axis +
                        [("hidden", True)] + list(attrs), bar)
        return _tag("span", [("class", "pfas-band"), ("hidden", True)] + list(attrs), "")
    return _tag("span", [("class", _cls("pfas-band", "is-axis" if scale else None, "is-thin" if thin else None)),
                         ("aria-hidden", "true"), ("data-lo", _g(ends[0])), ("data-hi", _g(ends[1]))] +
                axis + list(attrs), bar)


def _matrices_cell(ms, total):
    """A covered analyte's matrices in one cell that never wraps: the name of
    one, "All N matrices" when it is every matrix the method holds, else a
    count that opens the list (the grid's links popover), the list on hover."""
    ms = list(ms)
    listed = ", ".join(ms)
    if len(ms) == 1:
        return _tag("td", [], _esc(ms[0]))
    if total and len(ms) == total:
        return _tag("td", [("title", listed)], _esc("All {0} matrices".format(total)))
    items = "".join("<li><span>{0}</span></li>".format(_esc(m)) for m in ms)
    opener = _tag("a", [("class", "btn-sm btn-secondary pfas-sheet-links"), ("href", "#"), ("role", "button"),
                        ("aria-expanded", "false"), ("title", listed)], _esc("{0} matrices".format(len(ms))))
    return _tag("td", [], opener + '<div class="pfas-sheet-pop" hidden="hidden"><ul>{0}</ul></div>'.format(items))


def _fold_rows(covers, total=0):
    """The covered analytes as table rows: each analyte with its matrices."""
    return [_tag("tr", [], _tag("td", [], _esc(c["title"])) + _matrices_cell(c["matrices"], total)) for c in covers]


def rule_flags_name(tier, index):
    """A tier's name as its flag's row is keyed (rule_flags.tier_name)."""
    from senaite.pfas import rule_flags
    return rule_flags.tier_name(tier, index)


def _tile(label, value, band="", note="", attrs=(), cls=None):
    return _tag("div", [("class", _cls("pfas-hier-tile", cls))] + list(attrs),
                _tag("span", [("class", "pfas-hier-tile-l")], _esc(label)) +
                _tag("span", [("class", "pfas-hier-tile-v")], _esc(value)) + band +
                (_tag("span", [("class", "pfas-hier-tile-s")], _esc(note)) if note else ""))


# ── a rule's Flag tile ─────────────────────────────────────────────────────
# Every rule card carries one, last on the card: the code the rule prints
# when it fails (a QC Qualifiers entry, its wording read only), where the
# code attaches, and the internal note reviewers see beside the flag. Read
# from the flags table's posted inputs by name, so it follows the Table
# view; a click on Attaches to or Internal note opens the centred window on
# copies of them, a click on Code goes to QC Qualifiers, where the code is
# edited (method_profile_edit.js); no Edit button.
FLAG_HEAD = "Flag"
FLAG_CODE_LABEL = "Code"
FLAG_ATTACH_LABEL = "Attaches to"
FLAG_NOTE_LABEL = "Internal note"
FLAG_NO_CODE = "No code"
FLAG_NO_NOTE = "No note"
FLAG_PRINTS_NOTHING = "Nothing prints"
FLAG_NO_LETTER = "Its QC Qualifiers entry has no code: nothing prints."
FLAG_CODE_HELP = "From QC Qualifiers, where the QAO writes its wording."
FLAG_NOTE_HELP = "For reviewers. Shown with the flag in Data Review; never printed."
FLAG_EDIT_WORDS = "Edit flag"
FLAG_LIBRARY_WORDS = "Go to QC Qualifiers"
FLAG_JOINS_LEGEND = "When {0} prints, its wording joins the legend on the certificate and in the EDD."
# the kind of exceedance the rule raises (flag_kinds): its code is set once
# for every rule of the kind, in QC Qualifiers
FLAG_KIND_LABEL = "Raises"
FLAG_KIND_HELP = "Its code and wording are set once for the kind, in QC Qualifiers."
FLAG_NO_KIND_HELP = "No kind covers this rule: only its own code prints."
FLAG_OUTPUT_LABEL = "Output"
FLAG_MORE_LABEL = "Further flags"
FLAG_SHARED_NOTE = "Shared note, on the group card"
SHARED_NOTE_HEAD = "Internal note, for {0}:"
QUALIFIERS_PAGE = "@@pfas-qc-qualifiers"
# the Low-level recoveries note may name each low-level tier's N (in
# "\u2264 N \u00d7 RL"), written {0:g}: the tile reads it as N
LOW_LEVEL_N = re.compile(r"\{0(?::[^}]*)?\}")
LOW_LEVEL_NOTE_HELP = ("Write {0:g} where the note names N, the multiple of the RL: "
                       "each low-level tier fills in its own.")


def _kind_tile(rule_key, profile, library):
    """The Flag tile's first: the kind of exceedance the rule raises and
    its code from QC Qualifiers ("No code" until the lab sets one), or "No
    kind" for a rule no kind covers."""
    from senaite.pfas import flag_kinds as fk
    kind = fk.kind_of(profile, rule_key)
    if not kind:
        return _tile(FLAG_KIND_LABEL, fk.NO_KIND, note=FLAG_NO_KIND_HELP,
                     attrs=[("data-flag-part", "kind")], cls="is-none")
    letter, _wording = fk.kind_flag(library, kind)
    return _tile(FLAG_KIND_LABEL, "{0} \u00b7 {1}".format(fk.name(kind), letter or FLAG_NO_CODE),
                 note=FLAG_KIND_HELP, attrs=[("data-flag-part", "kind"), ("data-flag-kind", kind)])


def shared_note_block(profile, rows):
    """(html, {rule key}) of a group card: each note two or more of its
    rules carry word for word, written once ("Internal note, for LFB
    recovery and LFSM recovery: ..."), and the rules whose tiles then
    point to it. `rows`: [(rule key, label)]."""
    from senaite.pfas import rule_flags as rf
    labels = dict(rows)
    html, keys = "", set()
    for note, rules in rf.shared_notes(profile, [k for k, _l in rows]):
        names = [labels.get(k, k) for k in rules]
        who = " and ".join([", ".join(names[:-1]), names[-1]]) if len(names) > 1 else names[0]
        html += _tag("p", [("class", "pfas-hier-note"), ("data-shared-note", ",".join(rules))],
                     _tag("strong", [], _esc(SHARED_NOTE_HEAD.format(who))) + " " + _esc(note))
        keys.update(rules)
    return html, keys


def render_flag_tile(rule_key, profile, env=None, tier=None, title=None, named=False, shared=False):
    """The Flag tile of rule `rule_key` (a tier's: `tier` = (QC type, tier
    name), `rule_key` its QC type's row): Code with the library's wording,
    Attaches to and Internal note, read only, and Edit. Empty, it reads No
    code and No note. The one function every rule card calls; it names the
    inputs of the flags table its tab posts (method_profile_sections
    FLAGS_QC, or FLAGS_STD for the Isotope standards tab's rules).
    `named`: a card holding several rules heads each tile with its rule
    ("Flag: IS Response"). A rule's tile opens with the kind it raises;
    `shared`: its note is one the group card writes once
    (shared_note_block), so the tile points there."""
    cf, mps, _pf, _iso, _ls = _tab_modules()
    from senaite.pfas import rule_flags as rf
    profile = profile or {}
    standard = tier is None and rule_key in STANDARD_RULES
    low = tier is None and rule_key == rf.LOW_LEVEL_RULE
    table = mps.FLAGS_STD if standard else mps.FLAGS_QC
    row_key = mps.tier_flag_key(tier[0], tier[1]) if tier else (rule_key,)
    names = OrderedDict((c.path[0], cf.cell_name(table, row_key, c)) for c in mps.FLAG_COLUMNS)
    flag = rf.tier_flag_in(profile, tier[0], tier[1]) if tier else rf.flag_of(profile, rule_key)
    library = mps.qualifier_library(env)
    letter, wording = rf.printed(library, flag)
    has_code = bool(flag["code"])
    if not has_code:
        code_words, code_note = FLAG_NO_CODE, FLAG_CODE_HELP
    elif letter:
        code_words, code_note = letter, wording or FLAG_CODE_HELP
    else:
        code_words, code_note = FLAG_NO_CODE, FLAG_NO_LETTER
    # the place holds for the rule's own code and for its kind's
    from senaite.pfas import flag_kinds
    placed = bool(letter) or bool(tier is None and flag_kinds.kind_of(profile, rule_key))
    attach = (rf.ATTACH_WORDS[flag["attach"]], rf.ATTACH_HELP[flag["attach"]]) if placed else \
        (FLAG_PRINTS_NOTHING, "")
    label = title or rule_key
    head = _tag("div", [("class", "pfas-hier-flag-head")],
                _tag("h5", [("class", "pfas-hier-h")],
                     _esc("{0}: {1}".format(FLAG_HEAD, label) if named else FLAG_HEAD)))
    # every tile opens the flag's window, its Code too: the window chooses
    # the code and reads its wording, with a Go to QC Qualifiers inside it
    acts = card_acts(card_act("flag", FLAG_EDIT_WORDS, [("data-flag-edit", True)]))
    note_words = (LOW_LEVEL_N.sub("N", flag["note"]) if low else flag["note"]) or FLAG_NO_NOTE
    more = [] if tier else rf.more_flags(profile, rule_key)
    is_shared = bool(shared and flag["note"])
    tiles = ((_kind_tile(rule_key, profile, library) if tier is None else "") +
             _tile(FLAG_CODE_LABEL, code_words, note=code_note, attrs=[("data-flag-part", "code")]) +
             _tile(FLAG_ATTACH_LABEL, attach[0], note=attach[1], attrs=[("data-flag-part", "attach")],
                   cls=None if placed else "is-none") +
             _tile(FLAG_OUTPUT_LABEL, rf.OUTPUT_WORDS[flag["output"]], attrs=[("data-flag-part", "output")]) +
             _tile(FLAG_NOTE_LABEL, FLAG_SHARED_NOTE if is_shared else note_words,
                   note=FLAG_NOTE_HELP, attrs=[("data-flag-part", "note")] +
                   ([("data-flag-shared", True)] if is_shared else [])) +
             (_tile(FLAG_MORE_LABEL, ", ".join("{0} \u00b7 {1} \u00b7 {2}".format(
                 rf.printed(library, f)[0] or FLAG_NO_CODE, rf.ATTACH_WORDS[f["attach"]],
                 rf.OUTPUT_WORDS[f["output"]]) for f in more), attrs=TILE_READ) if more else ""))
    return _tag("div", [("class", "pfas-hier-flag"), ("data-flag-tile", rule_key),
                        ("data-flag-names", json.dumps(names)),
                        ("data-flag-form", "section-standards" if standard else QC_FORM),
                        ("data-flag-title", "{0}: {1}".format(FLAG_HEAD, label)),
                        ("data-flag-note-help", LOW_LEVEL_NOTE_HELP if low else None),
                        ] + tile_opens("flag"),
                head + _tag("div", [("class", "pfas-hier-tiles")], tiles) + acts)


def flag_choices_json(env=None, library_url=QUALIFIERS_PAGE):
    """What every Flag tile's window offers, once per page (the page's
    #pfas-flag-choices): {"codes": [[entry key, code, the failure it was
    written for, wording]], "places": [[place, words, what it means]]}."""
    _cf, mps, _pf, _iso, _ls = _tab_modules()
    from senaite.pfas import rule_flags as rf
    entries = rf.code_entries(mps.qualifier_library(env))
    return json.dumps({"library": library_url,
                       "codes": [[e["key"], e["code"], e["label"], e["statement"]] for e in entries],
                       "places": [[k, w, rf.ATTACH_HELP[k]] for k, w in rf.ATTACH],
                       "outputs": [[k, w] for k, w in rf.OUTPUTS],
                       "words": {"no_code": FLAG_NO_CODE, "no_note": FLAG_NO_NOTE,
                                 "nothing": FLAG_PRINTS_NOTHING, "no_letter": FLAG_NO_LETTER,
                                 "code_help": FLAG_CODE_HELP, "note_help": FLAG_NOTE_HELP,
                                 "joins": FLAG_JOINS_LEGEND}}).replace("</", "<\\/")


def _scroll(table):
    """A table in its own sideways scroll, so a cell that never wraps never
    widens the page."""
    return _tag("div", [("class", "pfas-scroll-x")], table)


# what each mark of a window says, in words, as the grid's legend says it
CELL_MARK_WORDS = {"is-set": "set on this cell", "is-inherited": "from its tier", "is-off": "no window"}
LOCKED_WORDS = "fixed by a rule"
# the one line above a tier's analyte tiles: how each mark is drawn
ANALYTE_LEGEND = ('<p class="pfas-legend">'
                  '<span class="pfas-legend-val is-set">40 \u2013 160</span> set on this cell \u00b7 '
                  '<span class="pfas-legend-val is-inherited">40 \u2013 130</span> from its tier \u00b7 '
                  '<span class="pfas-legend-val is-off">\u2014</span> no window \u00b7 '
                  + LOCK_MARK + ' fixed by a rule</p>')
NOT_REPORTED_IN = "Not reported in {0}"
EDIT_WINDOW_WORDS = "Edit window"


def tier_analytes(sheet, index, titles, tier_matrices):
    """[{analyte, title, lines, absent}]: the analytes whose window grid
    cell falls to the tier at `index` (sheet.tier_of), alphabetical, each
    with its windows as the grid draws them: a line per window, naming its
    matrices, the words and the mark of its cells (set on this cell, from
    its tier, no window, fixed by a rule); each cell keeps the data the
    grid cell opens its window with. `absent`: the tier's matrices the
    analyte is not reported in. Plain data: no input names."""
    cols = [c for c in sheet.columns if c.key.startswith("m-")]
    rows = dict((r.key, r) for r in sheet.rows)
    found = OrderedDict()
    for (kw, ck), i in sorted(sheet.tier_of.items(), key=lambda x: x[0][0]):
        if i == index and kw in rows:
            found.setdefault(kw, set()).add(ck)
    out = []
    for kw in analyte_order(list(found), titles):
        row = rows[kw]
        lines = OrderedDict()
        absent = []
        for col in cols:
            cell = row.cells.get(col.key)
            if cell is None:
                continue
            if cell.state == "na":
                absent += [m for m in col.matrices if m in tier_matrices]
                continue
            if col.key not in found[kw]:
                continue
            shown = _shown(col, cell)
            mark = _state_class(col, cell, shown == "")
            words = shown or EM_DASH
            # the cell's own data, as the grid cell carries it, but its box
            data = [(k, v) for k, v in _data_attrs(cell) if k[len("data-"):] not in BOX_KEYS]
            line = lines.setdefault((words, mark, cell.state == "locked"),
                                    {"words": words, "mark": mark, "locked": cell.state == "locked",
                                     "matrices": [], "cells": []})
            line["matrices"] += list(col.matrices)
            line["cells"].append({"key": "{0}|{1}|{2}".format(sheet.fold, kw, col.key), "column": col.label,
                                  "attrs": data})
        if lines:
            out.append({"analyte": kw, "title": _text(titles.get(kw, kw)), "lines": list(lines.values()),
                        "absent": absent})
    return out


def _analyte_tiles(tree, t):
    """A tier's analytes as tiles (tier_analytes), under the legend: each
    tile its analyte's windows, a line per matrix set where they differ;
    a click opens the grid cell's own window (data-cell-open, the cell's
    data), its menu each of its cells' windows, then the tier's Edit."""
    analytes = t.get("analytes") or []
    if not analytes:
        return _tag("p", [("class", "pfas-hier-empty")], _esc(NO_COVERS))
    every = set(t["matrices"])
    acts, tiles, n = [], [], 0
    for a in analytes:
        keys, body = [], []
        reported = every - set(a["absent"])
        lines = a["lines"]
        cells = sum(len(l["cells"]) for l in lines)
        for line in lines:
            for c in line["cells"]:
                key = "win{0}".format(n)
                n += 1
                keys.append(key)
                words = EDIT_WINDOW_WORDS + (", " + c["column"] if cells > 1 else "")
                acts.append(card_act(key, words, [("data-cell-open", True), ("data-cell-key", c["key"]),
                                                  ("data-row", a["analyte"])] + c["attrs"]))
            said = LOCKED_WORDS if line["locked"] else CELL_MARK_WORDS.get(line["mark"], "")
            value = _tag("span", [("class", _cls("pfas-legend-val", line["mark"])), ("data-cell-word", True),
                                  ("data-line-matrices", json.dumps(line["matrices"])),
                                  ("title", said or None)], _esc(line["words"]))
            value += (LOCK_MARK if line["locked"] else "")
            value += _tag("span", [("class", "pfas-sr-hide")], _esc(", " + said)) if said else ""
            named = len(lines) > 1 or set(line["matrices"]) != reported
            head = _tag("span", [("class", "pfas-hier-tile-m")], _esc(", ".join(line["matrices"]))) + " " \
                if named else ""
            body.append(_tag("span", [("class", "pfas-hier-tile-line")], head + value))
        note = NOT_REPORTED_IN.format(", ".join(a["absent"])) if a["absent"] else ""
        menu = keys + (["edit"] if t["prefix"] else [])
        tiles.append(_tag("div", [("class", "pfas-hier-tile pfas-hier-analyte"), ("data-analyte-tile", a["analyte"])] +
                          tile_opens(keys[0], menu),
                          _tag("span", [("class", "pfas-hier-tile-l")], _esc(a["title"])) +
                          _tag("span", [("class", "pfas-hier-tile-v pfas-hier-tile-lines")], "".join(body)) +
                          (_tag("span", [("class", "pfas-hier-tile-s")], _esc(note)) if note else "")))
    return ANALYTE_LEGEND + _tag("div", [("class", "pfas-hier-tiles"), ("data-analyte-tiles", tree["qc"])],
                                 "".join(tiles) + card_acts(*acts))


def _covers_table(covers, empty, total=0):
    if not covers:
        return _tag("p", [("class", "pfas-hier-empty")], _esc(empty))
    head = _tag("thead", [], _tag("tr", [], _tag("th", [], "Analyte") + _tag("th", [], "Matrices")))
    return _scroll(_tag("table", [("class", "pfas-table pfas-hier-table"), ("data-covers-table", True)],
                        head + _tag("tbody", [], "".join(_fold_rows(covers, total)))))


def spike_input(sid, row, matrix):
    """The posted name of one spike level: row `row` of the collection
    `sid`, the column of `matrix` (config_forms.collection_name)."""
    cf = _tab_modules()[0]
    return "__".join(["c", cf._enc(sid), _text(row), cf._enc(matrix)])


def _spike_table(rows, matrices, sid="", title="Spike levels"):
    """The spike levels of a tier's matrices: a matrix per row, a level per
    column, so every matrix shows without scrolling sideways and a new
    matrix adds a row. With `sid` (the collection the page draws) each
    value is a cell that opens the shared cell editor on the one spike
    level input it shows (data-spike names it), as a cell of the analyte
    grid opens its editor: a cell, never a button in the row."""
    if not rows or not matrices:
        return ""
    head = _tag("tr", [], _tag("th", [], "Matrix") +
                "".join(_tag("th", [("class", "is-right")], _esc(r["label"])) for r in rows))

    def opens(r, v):
        if not sid:
            return []
        return [("data-spike", spike_input(sid, r["row"], v["matrix"])), ("tabindex", "0"), ("role", "button"),
                ("aria-label", "Spike level {0}, {1}: {2}. Edit".format(r["label"], v["matrix"], v["value"]))]
    body = ""
    for i, m in enumerate(matrices):
        cells = "".join(_tag("td", [("class", _cls("is-right", None if v["set"] else "is-warn"))] + opens(r, v),
                             _esc(v["value"]) + (_tag("span", [("class", "pfas-hier-unit")], " " + _esc(v["unit"]))
                                                 if v["set"] and v["unit"] else ""))
                        for r in rows for v in [r["values"][i]])
        body += _tag("tr", [], _tag("td", [], _esc(m)) + cells)
    return (_tag("h5", [("class", "pfas-hier-h")], _esc(title)) +
            _scroll(_tag("table", [("class", "pfas-table pfas-hier-table")],
                         _tag("thead", [], head) + _tag("tbody", [], body))))


def _same_words(pair):
    """What a paired tier stores alike, in words."""
    if not pair["same_labels"]:
        return "Same name, nothing else stored alike"
    return "Same " + ", ".join(l[0].lower() + l[1:] for l in pair["same_labels"])


def _tier_card(tree, t, key, total, first=False, attrs=(), muted=False):
    qc = tree["label"]
    where = ", ".join(t["matrices"]) if t["listed"] else "All matrices"
    if t["listed"] and not t["matrices"]:
        where = "No matrices listed"
    caption = " \u00b7 ".join(["Tier {0} of {1}".format(t["position"], total), t["group_label"], where])
    tiles = [_tile("RPD" if tree["rpd"] else "Recovery", t["text"], _band(t["ends"]))]
    if "analytes" in t:
        # the matrices the tier applies in, as the grid's tier box reads them
        tiles.append(_tile("Matrices", where, attrs=[("data-tier-matrices", True)]))
    if not tree["rpd"]:
        tiles.append(_tile("Precision (RSD)", t["spread_text"] or "RSD " + NOT_SET))
    for p in t["pairs"]:
        tiles.append(_tile(p["label"], p["text"], _band(p["ends"], thin=True), note=_pair_words(tree["qc"], p)))
    for j, x in enumerate(t["low_level"]):
        low = "Low level \u2264 {0} \u00d7 RL".format(x["x_rl"])
        # a low-level tier's tiles open its own editor
        opens = tile_opens("low{0}".format(j), ["low{0}".format(j), "spikes", "remove-low{0}".format(j)]) \
            if x["prefix"] else TILE_READ
        tiles.append(_tile(low, x["text"], _band(x["ends"], thin=True), note=x["name"], attrs=opens))
        for p in x["pairs"]:
            tiles.append(_tile("{0}, {1}".format(p["label"], low[0].lower() + low[1:]), p["text"],
                               _band(p["ends"], thin=True), note=_pair_words(tree["qc"], p), attrs=opens))
    head = (_tag("h4", [("class", "pfas-hier-card-t")], _esc(t["label"])) +
            _tag("p", [("class", "pfas-hier-card-cap")], _esc(caption)) + _off_type_note(tree))
    opens = tile_opens("edit", ["edit", "spikes", "remove"]) if t["prefix"] else TILE_READ
    body = (_tag("div", [("class", "pfas-hier-tiles")] + opens, "".join(tiles)) + _core_note(tree, t) +
            _tag("h5", [("class", "pfas-hier-h")], "Analytes it covers") +
            (_analyte_tiles(tree, t) if "analytes" in t else
             _covers_table(t["covers"], NO_COVERS, tree.get("matrix_count", 0))))
    if t["subs"]:
        n = sum(len(s["covers"]) for s in t["subs"])
        body += _tag("p", [("class", "pfas-hier-note")],
                     _esc("Set on their own cells: {0} analyte{1}, listed under this tier.".format(
                         n, "" if n == 1 else "s")))
    body += _spike_table(t["spikes"], t["matrices"], tree.get("spikes_of", ""))
    if tree["every"]:
        body += _tag("p", [("class", "pfas-hier-note")], _esc("Under every tier: " + " \u00b7 ".join(tree["every"])))
    body += (t.get("flag_tile") or "") + _edit_buttons(tree, t)
    cells = []
    if _edits(tree, t):
        lo, hi = _window_ends(t["window"], tree["rpd"])
        cells = [("data-cells-of", json.dumps(_tier_cells(t))), ("data-cells-qc", tree["qc"]),
                 ("data-cells-kind", "rpd" if tree["rpd"] else "window"), ("data-cells-lo", lo), ("data-cells-hi", hi),
                 ("data-cells-head", "Sub-group \u00b7 {0} {1}".format(qc, t["label"]))]
    return _tag("section", [("class", _cls("pfas-hier-card", "is-c{0}".format(t["category"]),
                                           "is-muted" if muted else None)),
                            ("data-hier-card", key),
                            ("aria-label", "{0} tier {1}".format(qc, t["label"])), ("hidden", None if first else True)]
                + cells + list(attrs), head + body)


def _edits(tree, t):
    """Whether the page draws the tier collection that holds `t` (so its
    card and node may edit it)."""
    return bool(t["prefix"]) and bool(tree.get("collection"))


def _window_ends(window, rpd):
    """(lo, hi) of a window as a dialog starts its copies: "" for an end not
    set; an RPD limit is a maximum alone."""
    if window is None:
        return "", ""
    if rpd:
        return "", _g(window)
    lo, hi = window
    return ("" if lo is None else _g(lo)), ("" if hi is None else _g(hi))


def _tier_cells(t):
    """[[analyte, title, [matrices]]]: every cell whose window falls back to
    tier `t`, as the engine resolves it (tier_tree): those the tier judges
    and those set on their own under it. What a sub-group of the tier may
    hold; the page chooses among these and never works them out."""
    by = OrderedDict()
    for c in list(t["covers"]) + [c for s in t["subs"] for c in s["covers"]]:
        by.setdefault(c["analyte"], [c["title"], []])[1].extend(c["matrices"])
    order = list(t["matrices"])

    def at(m):
        return (order.index(m) if m in order else len(order), m)
    return [[kw, title, sorted(set(ms), key=at)] for kw, (title, ms) in by.items()]


def _cells_of(s):
    """[[analyte, title, [matrices]]]: the cells of one sub-group."""
    return [[c["analyte"], c["title"], list(c["matrices"])] for c in s["covers"]]


def _off_type_note(tree):
    """The one note an Off QC type's tier cards carry, shown while the card
    is greyed (.is-muted > .mp-qc-off-note)."""
    if not tree["held"]:
        return ""
    return _tag("p", [("class", "pfas-hier-note mp-qc-off-note")], _esc(OFF_TYPE_NOTE.format(tree["label"])))


def _edit_button(tree, tier, words, attr="data-tier-edit", key="edit", danger=False):
    """A tier's action, as its card's trigger `key` (card_act)."""
    head = "{0} \u00b7 {1} {2}".format(words, tree["label"], tier["label"])
    return card_act(key, words, [(attr, tier["prefix"]), ("data-tier-title", tier["label"]),
                                 ("data-tier-head", head), ("data-tier-core", "1" if tier.get("core") else None)],
                    danger=danger)


CORE_WORDS = "Core tier: kept"
ADDS_WITH_NOTE = "{0} tiers are added and removed with the {1} tier of their name."
CORE_HELP = ("Every analyte no other tier takes falls back to this tier, so it is never removed "
             "and applies to all or other analytes. Add a tier to set others apart.")


def _edit_words(tree, tier, low=False):
    """What Edit says on a tier: Edit RPD on an LFSMD tier that follows the
    LFSM tier of its name (its RPD is all it edits), the low-level tier's
    name on a low-level one, else Edit tier."""
    follows = tree["qc"] == "LFSMD" and any(p["qc"] == "LFSM" for p in tier["pairs"])
    if follows:
        return "Edit RPD" + (", " + tier["name"] if low else "")
    return "Edit " + tier["name"] if low else "Edit tier"


def _remove_refused(tree, t):
    """Why a tier has no Remove tier, or "": the core tier is kept, and a
    tier added with another type's goes with the tier of its name there."""
    if t.get("core"):
        return CORE_HELP
    if tree.get("adds_with"):
        return ADDS_WITH_NOTE.format(tree["qc"], tree["adds_with"])
    return ""


NO_COVERS = "No analyte takes this tier in any matrix."
NO_OWN_CELLS = "No cell under this tier is set on its own."


def _tier_menu(tree, t):
    """The tier node's row menu (data-row-actions; pfas:row-action events the
    page acts on): Edit tier, + Sub-group, Edit cells, Remove tier. An entry
    that cannot act says why. None where the page draws no tier collection."""
    from senaite.pfas import row_menu
    if not _edits(tree, t):
        return None
    refused = _remove_refused(tree, t)
    return row_menu.actions(
        (_edit_words(tree, t), "event", "tier-edit"),
        ("+ Sub-group", "event", "tier-sub", {"off": "" if _tier_cells(t) else NO_COVERS}),
        ("Edit cells", "event", "tier-cells", {"off": "" if t["subs"] else NO_OWN_CELLS}),
        ("Remove tier", "event", "tier-remove", {"danger": True, "off": refused}))


def _sub_menu(tree, t):
    """A sub-group node's row menu: Edit cells, and Remove sub-group (its
    cells go back to the tier)."""
    from senaite.pfas import row_menu
    if not _edits(tree, t):
        return None
    return row_menu.actions(("Edit cells", "event", "cells-edit"),
                            ("Remove sub-group", "event", "cells-remove", {"danger": True}))


def _dots(label, attrs, muted=False):
    """The touch screen's quiet menu button beside a node that has a row menu
    (a node is itself a button, so it sits after it, never inside); hidden
    with a mouse, where the right click is the menu."""
    return _tag("button", [("type", "button"), ("class", _cls("pfas-rowmenu", "pfas-hier-dots",
                                                                "is-muted" if muted else None)),
                           ("tabindex", "-1"), ("aria-haspopup", "menu"),
                           ("aria-label", "Actions for {0}".format(label))] + list(attrs), icons.svg("more", hidden=True))


def _spike_button(tree):
    """Spike levels: the spike level collection the card's levels are set
    in, its rows in a window (a level is added in the Table view)."""
    sid = tree.get("spikes_of")
    if not sid or not tree.get("collection"):
        return ""
    return card_act("spikes", "Edit spike levels", [inplace("Spike levels", tables=[
        {"sel": 'table.cf-coll[data-sheet="{0}"]'.format(sid)}])])


def _edit_buttons(tree, t):
    """The card's own actions, as its triggers (no button on the card): Edit
    tier opens the tier's editor in the shared drawer (on an LFSM tier it
    writes the LFSMD tier of its name too; an LFSMD tier that follows an
    LFSM tier edits its RPD alone), one for the tier and one for each
    low-level tier it shows; Spike levels goes to where its spike levels
    are set; Remove tier in the menu only. No Edit where the page draws no
    tier collection to write."""
    buttons = [_edit_button(tree, t, _edit_words(tree, t))] if t["prefix"] else []
    buttons += [_edit_button(tree, x, _edit_words(tree, x, True), key="low{0}".format(j))
                for j, x in enumerate(t["low_level"]) if x["prefix"]]
    buttons.append(_spike_button(tree))
    if t["prefix"] and not t.get("core") and not tree.get("adds_with"):
        buttons.append(_edit_button(tree, t, "Remove tier", "data-tier-remove", key="remove", danger=True))
    buttons += [_edit_button(tree, x, "Remove " + x["name"], "data-tier-remove", key="remove-low{0}".format(j),
                             danger=True)
                for j, x in enumerate(t["low_level"]) if x["prefix"] and not tree.get("adds_with")]
    return card_acts(*buttons)


def _core_note(tree, t):
    """The core tier's word that it is kept (it has no Remove tier)."""
    if t["prefix"] and t.get("core"):
        return _tag("p", [("class", "pfas-hier-note pfas-hier-core"), ("title", CORE_HELP)], _esc(CORE_WORDS))
    return ""


def _off_note():
    return _tag("p", [("class", "pfas-hier-note")], "<sup>1</sup> " + _esc(OFF_NOTE))


def _sub_card(tree, t, s, key, attrs=(), muted=False, tier_key=None):
    caption = "Set on its own cells \u00b7 under tier {0}".format(t["name"])
    label = "RPD" if tree["rpd"] else "Recovery"
    if s["off"]:
        tile = _tag("div", [("class", "pfas-hier-tile")],
                    _tag("span", [("class", "pfas-hier-tile-l")], _esc(label)) +
                    _tag("span", [("class", "pfas-hier-tile-v")], OFF_MARK))
    else:
        tile = _tile(label, s["text"], _band(s["ends"]))
    head = (_tag("h4", [("class", "pfas-hier-card-t")], _esc(OWN_CELLS)) +
            _tag("p", [("class", "pfas-hier-card-cap")], _esc(caption)) + _off_type_note(tree))
    body = _tag("div", [("class", "pfas-hier-tiles")] + (tile_opens("edit") if _edits(tree, t) else TILE_READ), tile)
    cells = []
    if _edits(tree, t):
        # Edit cells: the sub-group's own dialog (the page's cell settings), its tile's click
        body += card_acts(card_act("edit", "Edit cells", [("data-cells-edit", key)]))
        lo, hi = _window_ends(t["window"] if s["off"] else s["window"], tree["rpd"])
        cells = [("data-cells", json.dumps(_cells_of(s))), ("data-cells-qc", tree["qc"]),
                 ("data-cells-kind", "rpd" if tree["rpd"] else "window"), ("data-cells-off", "1" if s["off"] else None),
                 ("data-cells-lo", lo), ("data-cells-hi", hi), ("data-sub-of", tier_key),
                 ("data-cells-head", "Edit cells \u00b7 {0} {1}".format(tree["label"], t["label"]))]
    body += _tag("h5", [("class", "pfas-hier-h")], "Analytes set so") + \
        _covers_table(s["covers"], "", tree.get("matrix_count", 0)) + (_off_note() if s["off"] else "")
    return _tag("section", [("class", _cls("pfas-hier-card", "is-c{0}".format(t["category"]),
                                           "is-muted" if muted else None)),
                            ("data-hier-card", key), ("hidden", True)] + cells + list(attrs), head + body)


def _node(key, title, value, ends, sub_line, category, sub=False, lows=(), pressed=False, value_html=None,
          attrs=(), muted=False):
    inner = (_tag("span", [("class", "pfas-hier-node-t")], _esc(title)) +
             _tag("span", [("class", "pfas-hier-node-v")], value_html if value_html else _esc(value)) + _band(ends) +
             "".join(_band(e, thin=True) for e in lows if e) +
             (_tag("span", [("class", "pfas-hier-node-s")], _esc(sub_line)) if sub_line else ""))
    return _tag("button", [("type", "button"), ("class", _cls("pfas-hier-node", "is-sub" if sub else None,
                                                                "is-c{0}".format(category),
                                                                "is-selected" if pressed else None,
                                                                "is-muted" if muted else None)),
                           ("data-hier-target", key), ("aria-pressed", "true" if pressed else "false")] + list(attrs),
                inner)


def _owner(qc):
    """The rules list node a QC type's tiers sit under: its rule row's key."""
    rules, _qct = _qc_modules()
    return rules.qc_row_key(qc)


def tier_branch(tree, owner=None):
    """(children, cards): one QC type's tiers as the rules list draws them
    under the type's node `owner` (its rule row's key). The children are the
    tier nodes, each tier's own-cell groups after it, indented and in the
    tier palette, then what belongs to the type's tiers as a whole: + Add
    tier, or that its tiers come with another type's; a tier the engine
    cannot resolve, in words; the footnote of a cell set off. The cards are
    each tier's and each group's, hidden until chosen. Every part carries
    data-tier-of / data-tier-card-of naming `owner`, and greys while the
    type's row is Off (tree["mute"], following the row on the page).
    Read-only: no input, no name."""
    qc = tree["qc"]
    owner = owner or _owner(qc)
    total = len(tree["tiers"])
    mute = dict(tree.get("mute") or [])
    muted = bool(mute.pop("class", None))
    kid = [("data-tier-of", owner)] + sorted(mute.items())
    held = [("data-tier-card-of", owner)] + sorted(mute.items())

    def tail(html, cls="pfas-hier-note", tag="p"):
        return _tag(tag, [("class", _cls(cls, "pfas-hier-kid", "is-muted" if muted else None))] + kid, html)
    nodes, cards = [], []
    for t in tree["tiers"]:
        key = "{0}-{1}".format(qc, t["index"])
        n_cov = len(t["covers"])
        line = " · ".join([t["group_label"], "{0} analyte{1}".format(n_cov, "" if n_cov == 1 else "s")])
        menu = _tier_menu(tree, t)
        nodes.append(_node(key, t["label"], t["text"], t["ends"], line, t["category"], sub=True,
                           lows=[x["ends"] for x in t["low_level"]],
                           attrs=kid + [("data-row-actions", menu)], muted=muted))
        if menu:
            nodes.append(_dots("{0} tier {1}".format(tree["label"], t["label"]), kid, muted))
        cards.append(_tier_card(tree, t, key, total, attrs=held, muted=muted))
        for s in t["subs"]:
            skey = "{0}-s{1}".format(key, s["key"])
            n_s = len(s["covers"])
            smenu = _sub_menu(tree, t)
            nodes.append(_node(skey, OWN_CELLS, "" if s["off"] else s["text"],
                               s["ends"], "{0} analyte{1}".format(n_s, "" if n_s == 1 else "s"), t["category"],
                               sub=True, value_html=OFF_MARK if s["off"] else None,
                               attrs=kid + [("data-row-actions", smenu)], muted=muted))
            if smenu:
                nodes.append(_dots("{0} under {1}".format(OWN_CELLS, t["name"]), kid, muted))
            cards.append(_sub_card(tree, t, s, skey, attrs=held, muted=muted, tier_key=key))
    if tree.get("adds_with"):
        nodes.append(tail(_esc(ADDS_WITH_NOTE.format(qc, tree["adds_with"]))))
    elif tree.get("collection"):
        nodes.append(tail(_tag("button", [("type", "button"), ("class", "btn btn-sm btn-secondary"),
                                          ("data-tier-add", qc)], "+ Add tier"), "pfas-hier-actions", "div"))
    nodes += [tail(_esc(p), "pfas-banner is-warn") for p in tree["problems"]]
    if any(s["off"] for t in tree["tiers"] for s in t["subs"]):
        nodes.append(tail("<sup>1</sup> " + _esc(OFF_NOTE)))
    return nodes, cards


def tier_summary(tree):
    """(value, ends): what a QC type's node says of its tiers -- the one
    tier's limit, or how many --, and the range to draw beside it."""
    if tree["held"]:
        n = len(tree["tiers"])
        value = tree["tiers"][0]["text"] if n == 1 else counted(n, "tier")
    else:
        value = "no tiers yet"
    m = WINDOW_WORDS.match(value or "")
    return value, ((float(m.group(1)), float(m.group(2))) if m else None)


def _tier_label(name):
    """A tier's name as the editor shows it (limit_placard.tier_words)."""
    from senaite.pfas import limit_placard
    return limit_placard.tier_words(_text(name))


def _tier_box(profile, qc_type, tier):
    """A tier's limit box: (its key, its row's attributes, its placard)
    (limit_placard), or None for a tier with no name."""
    from senaite.pfas import limit_placard, limit_states
    if not isinstance(tier, dict) or not tier.get("name"):
        return None
    key = limit_states.tier_key(qc_type, tier)
    return {"key": key, "attrs": limit_placard.box_attrs(profile, key),
            "off": (limit_states.state_of(profile, key) == "off"),
            "placard": limit_placard.placard(profile, key, variant=limit_placard.CARD_PLACARD)}


def _tier_tr(cells, box, attrs=()):
    """A tier's row (a tile: `attrs` say what its click opens): the box
    itself (a right click changes its state), its State cell the placard."""
    attrs = list(attrs)
    if not box:
        return _tag("tr", [("class", "pfas-hier-tilebox")] + attrs, cells + _tag("td", [], ""))
    taken = set(k for k, _v in attrs)
    return _tag("tr", [("class", _cls("pfas-hier-tilebox", "is-muted" if box["off"] else None))] + attrs +
                [(k, v) for k, v in box["attrs"] if k not in taken], cells + _tag("td", [], box["placard"]))


def _tier_table(tree, owner):
    """The QC type card's list of its tiers, in the order the engine tries
    them, each its own limit box with its placard (a low-level tier too):
    a part the preview redraws (data-tier-part)."""
    body = ""
    if tree["held"]:
        rpd = tree["rpd"]
        heads = _tag("tr", [], _tag("th", [], "Tier") + _tag("th", [("class", "is-right")], "RPD" if rpd else "Window") +
                     ("" if rpd else _tag("th", [("class", "is-right")], "RSD")) + _tag("th", [], "State"))
        # a tier's row opens the tier's window (its card, where the page
        # draws no tier collection to write); each tier is its own limit
        # box, its state's placard in its State cell (a low-level tier too)
        acts = [_edit_button(tree, t, _edit_words(tree, t), key="tier{0}".format(i)) if t["prefix"] else
                card_act("tier{0}".format(i), "Edit tier " + _text(t["label"]),
                         [("data-go-node", "{0}-{1}".format(tree["qc"], t["index"]))])
                for i, t in enumerate(tree["tiers"])]
        trs = "".join(_tier_tr(_tag("td", [], _esc("{0} \u00b7 {1}".format(t["position"], t["label"]))) +
                               _tag("td", [("class", "is-right")], _esc(t["text"])) +
                               ("" if rpd else _tag("td", [("class", "is-right")], _esc(t["spread_text"] or NOT_SET))),
                               t.get("box"), [("aria-label", _text(t["label"]))] + tile_opens("tier{0}".format(i)))
                      for i, t in enumerate(tree["tiers"]))
        lows = OrderedDict()
        for t in tree["tiers"]:
            for x in t.get("low_level") or ():
                lows.setdefault(x["name"], x)
        trs += "".join(_tier_tr(_tag("td", [], _esc(x["label"])) +
                                _tag("td", [("class", "is-right")], _esc(x["text"])) +
                                ("" if rpd else _tag("td", [("class", "is-right")], "")),
                                x.get("box"), [("aria-label", _text(x["label"]))] + TILE_READ)
                       for x in lows.values())
        body = (_tag("h5", [("class", "pfas-hier-h")], "Tiers, in the order the engine tries them") +
                _scroll(_tag("table", [("class", "pfas-table pfas-hier-table")],
                             _tag("thead", [], heads) + _tag("tbody", [], trs))) + card_acts(*acts))
    return _tag("div", [("data-tier-part", "table:" + owner)], body)


def tier_parts(tree, owner=None):
    """{part: html}: what a QC type's node and card draw from its tiers, each
    marked data-tier-part so the preview puts a fresh one in its place: the
    node's value and its bar, the card's Tiers tile, the card's tier table."""
    owner = owner or _owner(tree["qc"])
    value, ends = tier_summary(tree)
    return OrderedDict([
        ("value", _tag("span", [("class", "pfas-hier-node-v"), ("data-tier-part", "value:" + owner)], _esc(value))),
        ("band", _band(ends, attrs=[("data-tier-part", "band:" + owner)])),
        ("tile", _tile("Tiers", value or "none", attrs=[("data-tier-part", "tile:" + owner)])),
        ("table", _tier_table(tree, owner))])


def render_tier_tree(tree, shown=True):
    """One QC type's tiers as the rules list draws them (tier_branch,
    tier_parts), in the carrier the preview answers with: <div data-qc-tree>
    holding the children in a list, the cards beside them, then the type's
    parts. The page takes each piece out and puts it under the type's node
    in #rules-list. Read-only: no input, no name."""
    owner = _owner(tree["qc"])
    nodes, cards = tier_branch(tree, owner)
    parts = tier_parts(tree, owner)
    return _tag("div", [("class", "mp-qc-tree-qc"), ("data-qc-tree", tree["qc"]), ("data-tier-owner", owner),
                        ("hidden", None if shown else True)],
                _tag("div", [("class", "pfas-hier-list")], "".join(nodes)) +
                _tag("div", [("class", "pfas-hier-cards")], "".join(cards)) +
                _tag("div", [("class", "mp-qc-tree-parts")], "".join(parts.values())))


def tier_trees(profile, env=None, qc_type="LFSM", posted=None):
    """The tiers of every QC type the window grid shows, as the rules list
    draws them: <div id="qc-tree">, one carrier each (render_tier_tree), as
    the preview answers with them."""
    profile = profile or {}
    inner = "".join(render_tier_tree(tier_tree(profile, env, q, posted)) for q, _l in QC_TYPES)
    return _tag("div", [("id", TREE_ID), ("class", "mp-qc-tree")], inner)


# ── the rules as one list: the Rules section's List view ────────────────────
# The rule table drawn as a list grouped by what each rule judges, beside the
# chosen rule's card. The table stays as the section's Table view and holds
# every posted field: a card's state is a nameless copy of its row's segment
# writing that row's input (PFAS.components seg, data-input), so a change
# made in either posts once. A QC type or blank set Off folds under Removed
# in its group (still greyed and open, its values kept); + Add QC type shows
# a type the table draws hidden (addable_qc_types).

RULE_GROUPS = [("Calibration", ("cal_r2", "over_range")),
               ("CCV", ("ccv_recovery", "ccv_frequency")),
               # held by the Isotope standards tab: never drawn on QC criteria
               ("Isotope standards", STANDARD_RULES),
               ("Confirmation and signal", ("rrt_deviation", "ion_ratio", "sn_min", "single_transition_confirm")),
               ("Detection", ("mdl_check",))]
RECOVERIES_GROUP = "Analyte recoveries"
# the Calibration group's own node and card: its rules' states, the
# calibration settings QC criteria saves (section cal, group Calibration)
# as tiles, and where each is overridden
CAL_GROUP = RULE_GROUPS[0][0]
CAL_GROUP_KEY = "group-cal"
CAL_TILE_FIELDS = ("r2_min", "point_pct_dev_max", "low_point_pct_dev_max", "max_cal_dropped", "origin",
                   "weighting", "fit")
CAL_GROUP_CAP = "Method-wide: every curve starts from these"
LEVELS_LABEL = "Levels"
LEVELS_NOTE = "Calibration levels"
RANGE_LABEL = "Per-analyte range"
RANGE_NONE = "None set"
RANGE_NOTE = "A multiple of the levels and a top level"
CAL_SETTINGS_HEAD = "Settings"
CAL_OVERRIDES_HEAD = "Overrides"
# each level a row that opens where that level is set: (level, what it can
# change, where, the trigger it presses)
CAL_OVERRIDES = (("Per analyte", "Its calibration range", "Here, the Per-analyte range", "levels"),
                 ("Per project", "R\u00b2 and point deviation", "Projects, each project's specs", "projects"),
                 ("Per curve", "Fit, weighting and origin", "Data Review, Calibration", "curves"))
# what the method profile does not hold, read in a window with its Go to
CAL_ELSEWHERE = {
    "projects": ("Projects", "A project may set its own R\u00b2 and point deviation in its specs. They are kept "
                             "with the project, not in this method profile."),
    "curves": ("Data Review", "Each curve's fit, weighting and origin are chosen in Data Review, Calibration, for "
                              "its worksheet. They are kept with the worksheet, not in this method profile."),
}
CAL_LEVELS_TITLE = "Calibration levels and ranges"
PROJECTS_PAGE = "@@pfas-projects"
DATA_REVIEW_PAGE = "@@pfas-data-review-home"
CHEVRON_WORDS = "\u203a"
EDIT_CAL_WORDS = "Edit calibration"
EDIT_LEVELS_WORDS = "Edit levels and ranges"
BLANKS_GROUP = "Blanks"
# the groups drawn as the Calibration group is, a group node heading its
# rules and opening the group's card (profile_cards.qc_group_entry): their
# rules' nodes sit under it
QC_GROUP_KEYS = OrderedDict([("CCV", "group-ccv"), ("Confirmation and signal", "group-conf"),
                             (RECOVERIES_GROUP, "group-rec"), (BLANKS_GROUP, "group-blk")])
GROUP_CARDED = (CAL_GROUP,) + tuple(QC_GROUP_KEYS)
GROUP_KEYS = dict([(CAL_GROUP, CAL_GROUP_KEY)] + list(QC_GROUP_KEYS.items()))
# a group's title is its key in the code (the Calibration group's is the
# calibration section group's title); the list labels it by GROUP_LABELS
CAL_GROUP_LABEL = "Calibration curve"
GROUP_LABELS = {CAL_GROUP: CAL_GROUP_LABEL}
# a parent heading groups in the Rules list: (its key, its label, the titles
# of the groups under it, in order). A group under a parent sits one step
# in, its rules two
CAL_PARENT_KEY = "group-calp"
XQC_PARENT_KEY = "group-xqc"
RULE_PARENTS = [(CAL_PARENT_KEY, "Calibration", (CAL_GROUP, "CCV", "Confirmation and signal")),
                # every QC sample extracted with the batch
                (XQC_PARENT_KEY, "Extracted QC", (RECOVERIES_GROUP, BLANKS_GROUP))]
PARENT_OF = dict((g, key) for key, _l, gs in RULE_PARENTS for g in gs)
PARENT_CAP = "Choose a group in the list to see its rules"
PARENT_HEADS = ("Group", "Rules")
# a group node is active (green) while any limit box of its rules is
# Enforced or Evaluate, idle (grey) while every one is Off; said in words too
ACTIVE_WORDS = "Something in it is judged"
IDLE_WORDS = "Nothing in it is judged"


def group_label(title):
    """A group's name in the list."""
    return GROUP_LABELS.get(title, title)
OTHER_GROUP = "Other rules"
MOVED_GROUP = "Isotope standards"
LIST_ID = "rules-list"
STATE_WORDS = {"enforced": "Enforced", "evaluate": "Evaluate", "off": "Off"}
REMOVED_WORDS = "Removed"
ADD_QC_WORDS = "+ Add QC type"
REMOVE_QC_WORDS = "Remove QC type"
RESTORE_WORDS = "Restore"
REMOVE_QC_HELP = "Remove sets it Off and folds it under Removed: nothing stored is deleted, and Restore brings back every value."
ADDED_HELP = "Added on this page: nothing regulatory is filled in, so Save waits until its limit is typed."
OPEN_TIERS_WORDS = "Show its tiers"
COMPOSITION_WORDS = "Edit QC composition"


def composition_window(code):
    """The window of QC type `code`'s part of the QC composition: the inputs
    Run & reporting posts (how many per worksheet; the LFSM's frequency, the
    duplicate of every field sample)."""
    _cf, mps, _pf, _iso, _ls = _tab_modules()
    names = [[f.name, _text(f.label)] for _t, fields in mps.QC_COMPOSITION.groups for f in fields
             if f.path[0] == code]
    return inplace("{0}: {1}".format(_text(mps.QC_COMPOSITION.title), code), names=names)
FOLLOWS_LFSM_CAP = "Its tiers are LFSM's, by name: each keeps its own RPD"
QC_TYPE_CAP = "QC type × analyte group × matrix"
BLANK_CAP = "Blank limit · method-wide"
# words the page writes in a node's state line, by the state its input holds
INHERITED_WORDS = "{0}, the method default"
WINDOW_WORDS = re.compile(u"^(\\d+(?:\\.\\d+)?) – (\\d+(?:\\.\\d+)?) %")


def rule_group(key):
    """The list group a rule table row sits in, by its key."""
    rules, _qct = _qc_modules()
    if key.startswith(rules.BLANK_PREFIX):
        return BLANKS_GROUP
    if rules.is_profile_row_key(key):
        return RECOVERIES_GROUP
    for title, keys in RULE_GROUPS:
        if key in keys:
            return title
    return OTHER_GROUP


def per_worksheet_words(profile, code):
    """How many of `code` a worksheet gets, as extraction_batch.plan_qc reads
    the method: its typed per_batch, else what a blank box gives (one for a
    type switched on, none for the sample duplicate); a type the method does
    not hold yet gets what a type switched on gets."""
    from senaite.pfas.extraction_batch import blank_count
    qca = (profile or {}).get("qc_acceptance") or {}
    conf = qca.get(code) if isinstance(qca.get(code), dict) else {}
    try:
        typed = int(conf.get("per_batch")) if conf.get("per_batch") not in (None, "") else None
    except (TypeError, ValueError):
        typed = None
    if code == "Dup" and (conf.get("duplicate_all_samples") or "") == "yes":
        return "every field sample"
    if typed is not None:
        return "{0} per worksheet".format(typed)
    n = blank_count(profile, code) if code in qca else (0 if code == "Dup" else 1)
    return "{0} per worksheet".format(n) if n else "none unless set"


def _frequency_words(profile):
    conf = (((profile or {}).get("qc_acceptance") or {}).get("LFSM") or {})
    v = conf.get("frequency")
    return "every {0} field samples".format(_g(v)) if v not in (None, "") else NOT_SET


def _state_line(cell):
    value = _text(cell.value)
    word = STATE_WORDS.get(value, value.capitalize())
    return INHERITED_WORDS.format(word) if cell.state == "inherited" else word


def state_glyph(cell, dom_id, rule_key, profile=None):
    """A list row's state: the placard's glyph in the placard's colour in
    place of the word, the word kept as visually hidden text so the row's
    name still says it. It follows the rule's state input (data-state-of);
    a rule with limit boxes names their posted inputs (data-glyph-inputs)
    and the page draws a glyph for each state they hold
    (pfas-components.js, stateLine): the boxes the method judges, as the
    rule's own state counts them (limit_states.applies)."""
    from senaite.pfas import limit_placard
    from senaite.pfas import limit_states as ls
    value = _text(cell.value)
    inputs = " ".join(limit_placard.input_name(b["key"]) for b in ls.boxes_of(rule_key)
                      if ls.applies(profile or {}, b))
    glyph = limit_placard.GLYPHS.get(value)
    mark = _tag("span", [("class", "pfas-state-m is-" + value), ("aria-hidden", "true")], glyph) if glyph else ""
    return _tag("span", [("class", "pfas-state-g"), ("data-state-of", dom_id), ("data-state", value or None),
                         ("data-inherited", _state_line(cell) if cell.state == "inherited" else None),
                         ("data-glyph-inputs", inputs or None)],
                mark + _tag("span", [("class", "pfas-sr-hide")], _esc(_state_line(cell))))


def _list_button(words, attrs, hidden=False):
    return _tag("button", [("type", "button"), ("class", "btn btn-sm btn-secondary")] + attrs +
                [("hidden", True if hidden else None)], _esc(words))


# ── A card's actions: no Edit button, a tile opens its window ───────────────
# A card draws no Edit, Remove, Reset or Restore button. Each is drawn once
# as a trigger (data-act) in the card's or a block's hidden .pfas-hier-acts,
# keeping the attributes the page's script hears; a tile names the trigger
# its click presses (data-tile-open) and those its right-click menu offers
# (data-tile-menu), on itself or on the block or card holding it
# (pfas-components.js, tiles). A trigger hidden itself is not offered at
# present; data-danger draws it last in a menu. A trigger never leaves the
# page: data-inplace opens a window on the inputs the value is posted in
# (inplace below), data-go-node presses another card's own window.
ACTS_CLASS = "pfas-hier-acts"


def card_head(title, help_html=""):
    """A card's title, its help ? beside it at the buttons' height (no other
    button sits in a heading)."""
    h4 = _tag("h4", [("class", "pfas-hier-card-t")], _esc(title))
    return _tag("div", [("class", "pfas-hier-card-head")], h4 + help_html) if help_html else h4


def group_head(words, help_id=None):
    """A list's group heading; with `help_id`, the group's one help ? at the
    heading's right end (the top right of the group), in place of a ? on
    each of its cards."""
    if not help_id:
        return _tag("p", [("class", "pfas-hier-group")], _esc(words))
    return _tag("p", [("class", "pfas-hier-group has-help")],
                _tag("span", [("class", "pfas-hier-group-t")], _esc(words)) + help_dictionary.help_button(help_id))


def card_act(key, words, attrs=(), danger=False, hidden=False):
    """One of a card's actions, as its trigger."""
    return _tag("button", [("type", "button"), ("data-act", key)] + list(attrs) +
                [("data-danger", True if danger else None), ("hidden", True if hidden else None)], _esc(words))


def card_acts(*acts):
    """A card's (or a block's) triggers, drawn hidden: "" when there is none."""
    inner = "".join(a for a in acts if a)
    return _tag("div", [("class", ACTS_CLASS), ("hidden", True)], inner) if inner else ""


def tile_opens(key, menu=None):
    """The attributes of a tile (or a block, or a card) whose click presses
    trigger `key`, its menu offering `menu` (else `key` alone)."""
    out = [("data-tile-open", key)] if key else []
    if menu:
        out.append(("data-tile-menu", json.dumps(list(menu))))
    return out


TILE_READ = [("data-tile-read", True)]


# ── A note opens its window in place ────────────────────────────────────────
# A tile, row or note never takes the page to another tab, view or page: the
# trigger it presses carries data-inplace, the window that edits the values
# it is about, on nameless copies of the inputs the page already posts (one
# source of truth: Done writes each change into its own input, whichever tab
# posts it). What the method profile does not hold is read in the window,
# with one "Go to ..." button inside it (method_profile_edit.js, in place).
def inplace(title, names=None, tables=None, read=None, note=None, goto=None):
    """The data-inplace attribute of a trigger: `names` [[input name, label]
    or [name, label, [[value, words], ...]] for a hidden field drawn as a
    segment], `tables` [{"sel": a table's selector, "head": words, "cols":
    [data-col prefixes], "rows": [data-row keys]}], `read` words, `note`,
    `goto` [href, words]."""
    spec = {"title": _text(title)}
    for k, v in (("names", names), ("tables", tables), ("read", read), ("note", note), ("goto", goto)):
        if v:
            spec[k] = v
    return ("data-inplace", json.dumps(spec, sort_keys=True))


def go_to(base, page, words):
    """[href, words] of a window's Go to button: a page outside the method
    profile."""
    return [(base + "/" + page) if base else page, "Go to " + words]


def actions_row(*buttons):
    """A card's one row of buttons, its last child: what makes something new
    (+ Add, Copy, Combine, Confirm again), never Edit."""
    inner = "".join(b for b in buttons if b)
    return _tag("div", [("class", "pfas-hier-actions")], inner) if inner else ""


def _rule_entry(sheet, row, profile, trees, order=0, env=None):
    """One row of the rule table as the list draws it: {key, group, node,
    card, removable, off}; the card ends with the rule's Flag tile."""
    rules, _qct = _qc_modules()
    state = row.cells["state"]
    name = _state_name(row, state)
    dom_id = _dom_id(sheet, name)
    value = _text(state.value)
    limits = row.cells.get("limits")
    edit = row.cells.get("edit")
    code = rules.qc_row_code(row.key)
    blank = row.key.startswith(rules.BLANK_PREFIX)
    held = code is not None and isinstance(((profile or {}).get("qc_acceptance") or {}).get(code), dict)
    removable = code is not None and (held or bool(row.hidden))
    words = _text(limits.value) if limits is not None else ""
    if not words and limits is not None and limits.flags:
        words = limits.flags[0][0]
    tree = trees.get(code) if code else None
    parts = tier_parts(tree, row.key) if tree is not None else None
    if tree is not None:
        node_value = tier_summary(tree)[0]
    elif code and not blank:
        node_value = words if words not in (IN_THE_GRID, EM_DASH) else ""
    else:
        node_value = words if words != EM_DASH else ""
    # the List view has no grid below: it says where the grid is
    in_grid = words == IN_THE_GRID
    if in_grid:
        words = GRID_IN_TABLE
        node_value = GRID_IN_TABLE if node_value == IN_THE_GRID else node_value
    m = WINDOW_WORDS.match(node_value or "")
    ends = (float(m.group(1)), float(m.group(2))) if m else None
    inherited = state.state == "inherited"
    # a QC type or blank greys while its presence input reads Off (Removed);
    # a rule's boxes grey themselves (limit_placard)
    mute = [("data-mute-if", name), ("data-mute-values", "off")] if code is not None else []
    if mute and inherited and value == "off":
        mute.append(("data-mute-blank", "1"))
    off = value == "off"
    line = state_glyph(state, dom_id, row.key, profile)
    node = _tag("button", [("type", "button"),
                           ("class", _cls("pfas-hier-node", "is-rule",
                                          "is-sub" if rule_group(row.key) in GROUP_CARDED else None,
                                          "is-deep" if rule_group(row.key) in PARENT_OF else None,
                                          "is-muted" if off else None)),
                           ("data-hier-target", row.key), ("aria-pressed", "false"),
                           ("data-rule-code", code), ("data-rule-state", dom_id), ("data-rule-group", rule_group(row.key)),
                           ("data-rule-order", _text(order)),
                           ("data-removable", "1" if removable else None),
                           ("data-addable", code if row.hidden else None), ("hidden", True if row.hidden else None)]
                + mute,
                _tag("span", [("class", "pfas-hier-node-t")], _esc(row.label) + line) +
                (parts["value"] + parts["band"] if parts else
                 _tag("span", [("class", "pfas-hier-node-v")], _esc(node_value)) + _band(ends)))

    # the card: the state, then what the rule judges and where its limits are set
    caption = [_text(row.cells["scope"].value)] if row.cells.get("scope") is not None else []
    if code == "LFSMD":
        caption = [FOLLOWS_LFSM_CAP]
    elif code and not blank:
        caption = [QC_TYPE_CAP]
    elif blank:
        caption = [BLANK_CAP]
    flags = [f[0] if isinstance(f, tuple) else f for f in (state.flags or ())]
    head = (_tag("h4", [("class", "pfas-hier-card-t")], _esc(row.label)) +
            _tag("p", [("class", "pfas-hier-card-cap")], _esc(" · ".join(caption + flags))))
    # no state segment: each limit box carries its own placard
    # (limit_placard); a rule with no limit of its own carries it on its
    # Effective limits tile, a blank on its limit's tile
    from senaite.pfas import limit_placard, limit_states
    seg = ""
    own_box = None
    more_boxes = []
    if code is None and limit_states.boxes_of(row.key) and \
            not any(b["fields"] for b in limit_states.boxes_of(row.key)):
        own_box = row.key
    elif code is None and limit_states.boxes_of(row.key):
        # a rule's limits: its Effective limits tile is its first box, the
        # box its group card's tile shows; each other box a tile of its own,
        # so every limit on the card carries its placard
        boxes = [b["key"] for b in limit_states.boxes_of(row.key) if limit_states.applies(profile, b)]
        own_box, more_boxes = boxes[0], boxes[1:]
        if more_boxes and words not in (None, "", EM_DASH):
            words = limit_placard.box_words(profile, own_box) or words
            m = WINDOW_WORDS.match(words or "")
            ends = (float(m.group(1)), float(m.group(2))) if m else None
    elif blank:
        first = (limit_states.tiers(profile, code) or [None])[0]
        own_box = limit_states.tier_key(code, first) if first and first.get("name") else None
    # no Edit button: the limits tile opens the limits (a QC type's, its
    # tiers), a QC composition count goes to QC composition; Remove and
    # Restore in the menu only
    acts = []
    if edit is not None and edit.expands and tree is None:
        # a group drawn as a card holds the region's limits as tiles: its
        # window opens on them; the others open the region
        gkey = QC_GROUP_KEYS.get(rule_group(row.key))
        if gkey and edit.expands != WINDOWS_REGION:
            acts.append(card_act("limits", "Edit limits", [("data-qc-edit", edit.expands), ("data-qc-card-of", gkey)]))
        elif rule_group(row.key) == CAL_GROUP:
            # the Calibration window, as the rule's table row opens it
            acts.append(card_act("limits", "Edit limits", [("data-cal-settings", True)]))
        else:
            # the region's own inputs in a window, never the Table view
            acts.append(card_act("limits", "Edit limits", [inplace(row.label, tables=[{"sel": "#" + edit.expands}])]))
    if tree is not None:
        acts.append(card_act("limits", OPEN_TIERS_WORDS, [("data-qc-open", code)]))
    links = []
    if limits is not None and limits.links:
        for i, (label, href) in enumerate(limits.links):
            # the values another tab holds, edited here on its own inputs
            links.append("link{0}".format(i))
            acts.append(card_act(links[-1], MDL_EDIT_WORDS,
                                 [inplace(MDL_TITLE, tables=[{"sel": ANALYTES_SHEET, "cols": ["mdl-"]}])]))
    counts = code in ("MB", "LRB", "MxB", "LFB", "LCS", "LFSM", "LFSMD", "Dup")
    if counts:
        acts.append(card_act("comp", COMPOSITION_WORDS, [composition_window(code)]))
    if removable:
        acts.append(card_act("remove", REMOVE_QC_WORDS, [("data-qc-remove", dom_id), ("title", REMOVE_QC_HELP)],
                             danger=True, hidden=off))
        acts.append(card_act("restore", RESTORE_WORDS, [("data-qc-restore", dom_id)], hidden=not off))
    limit_act = "limits" if any('data-act="limits"' in a for a in acts) else (links[0] if links else None)
    tile_menu = [k for k in [limit_act] + links + ["remove", "restore"] if k]
    tiles = []
    if parts:
        tiles.append(parts["tile"])
    elif words and not (code and not blank and in_grid):
        tile = _tile("Effective limits", words, _band(ends),
                     attrs=tile_opens(limit_act, tile_menu) if limit_act else TILE_READ)
        tiles.append(limit_placard.boxed(tile, profile, own_box) if own_box else tile)
        for k in more_boxes:
            more = _tile(limit_placard.label_of(profile, k), limit_placard.box_words(profile, k),
                         attrs=tile_opens(limit_act, tile_menu) if limit_act else TILE_READ)
            tiles.append(limit_placard.boxed(more, profile, k, limit_placard.uses_words(k)))
    if counts:
        tiles.append(_tile("Per worksheet", per_worksheet_words(profile, code),
                           note="QC composition, on Run & reporting", attrs=tile_opens("comp")))
    if code == "LFSM":
        tiles.append(_tile("One more LFSM", _frequency_words(profile), note="QC composition, on Run & reporting",
                           attrs=tile_opens("comp")))
    # the Tiers tile is drawn again by the preview: its block names what it opens
    block = tile_opens(limit_act, tile_menu) if parts and limit_act else []
    body = seg + (_tag("div", [("class", "pfas-hier-tiles")] + block, "".join(tiles)) if tiles else "")
    if parts:
        body += parts["table"]
    if removable:
        body += _tag("p", [("class", "pfas-hier-note")], _esc(REMOVE_QC_HELP))
    if row.hidden:
        body += _tag("p", [("class", "pfas-hier-note")], _esc(ADDED_HELP))
    body += render_flag_tile(row.key, profile, env, title=row.label) + card_acts(*acts)
    card = _tag("section", [("class", _cls("pfas-hier-card", "is-rule", "is-muted" if off else None)),
                            ("data-hier-card", row.key), ("hidden", True), ("aria-label", row.label)] + mute,
                head + applies_row(row.key, profile, off) + body)
    # a QC type's tiers open under its node; a type drawn hidden for + Add
    # QC type holds none until it is added (the preview draws them then)
    kids, tier_cards = tier_branch(tree, row.key) if tree is not None and not row.hidden else ([], [])
    return {"key": row.key, "group": rule_group(row.key), "node": node, "card": card,
            "kids": kids, "tier_cards": tier_cards,
            "removable": removable, "off": off, "code": code, "hidden": bool(row.hidden)}


def cal_settings(profile, env=None):
    """[setting]: the calibration settings the Calibration card shows as
    tiles (CAL_TILE_FIELDS of section cal's Calibration group, as the
    region draws them), each naming the input QC criteria posts."""
    cf, mps, _pf, _iso, _ls = _tab_modules()
    out = []
    for g in cf.render(mps.SECTIONS["cal"], profile or {}, env or {}):
        if g["title"] != CAL_GROUP:
            continue
        out += [_setting(f["label"], f) for f in g["shown"] if f["name"].rsplit("__", 1)[-1] in CAL_TILE_FIELDS]
    # an Average RF passes through the origin by definition: under that fit
    # the Origin tile reads Force and is not edited
    by = dict((s["names"][0].rsplit("__", 1)[-1], s) for s in out)
    if "origin" in by and "fit" in by:
        from senaite.pfas import calibration_fit as _cfit
        fixed = {"name": by["fit"]["names"][0], "value": _cfit.FIXED_ORIGIN_FIT,
                 "words": dict(_cfit.ORIGINS)[_cfit.FIXED_ORIGIN], "note": _cfit.FIXED_ORIGIN_WORDS}
        by["origin"]["fixed"] = fixed
        cal = ((profile or {}).get("instrument_verification") or {}).get("calibration") or {}
        if _cfit.fit(cal) == _cfit.FIXED_ORIGIN_FIT:
            by["origin"].update(words=fixed["words"], note=fixed["note"])
    return out


def _levels_words(profile):
    """"10 levels · 0.039 to 20 ng/mL", or Not set."""
    from senaite.pfas import calibration_levels as cl
    lv = cl.levels(profile or {})
    if not lv:
        return NOT_SET_WORDS
    unit = _text((((profile or {}).get("instrument_verification") or {}).get("calibration") or {})
                 .get("level_unit") or "")
    return "{0}{1}{2:.3g} to {3:.3g} {4}".format(counted(len(lv), "level"), MIDDOT, lv[0], lv[-1], unit).strip()


def _range_words(profile):
    """How many analytes have a calibration range of their own, or None set."""
    scale = ((((profile or {}).get("instrument_verification") or {}).get("calibration") or {})
             .get("analyte_scale") or {})
    n = len([k for k, v in scale.items() if isinstance(v, dict) and any(x not in (None, "") for x in v.values())])
    return counted(n, "analyte") if n else RANGE_NONE


def _limit_words_of(row):
    limits = row.cells.get("limits")
    words = _text(limits.value) if limits is not None else ""
    return words if words != EM_DASH else ""


def row_is_off(row):
    """A rule table row read Off as drawn: its rule judges nothing."""
    return _text(row.cells["state"].value) == "off"


def applies_row(key, profile, off=False):
    """A rule's Applies to row (sample_type_icons.row): each group of sample
    types lit where the engine judges a type of it on this method, pale
    where it judges none, all pale while the rule is Off; in a block naming
    the rule (data-applies-of)."""
    from senaite.pfas import sample_type_icons as sti
    return _tag("div", [("class", "pfas-hier-applies"), ("data-applies-of", key)], sti.row(key, profile or {}, off))


def applies_lines(items, profile):
    """A group card's Applies to rows, one line per rule: its name, then its
    row. `items`: [(rule key, label, Off)]."""
    from senaite.pfas import sample_type_icons as sti
    if not items:
        return ""
    return _tag("div", [("class", "pfas-hier-applies-list")],
                "".join(_tag("div", [("class", "pfas-hier-applies is-named"), ("data-applies-of", key)],
                             _tag("span", [("class", "pfas-hier-applies-l")], _esc(label)) +
                             sti.row(key, profile or {}, off))
                        for key, label, off in items))


def _tail_applies(rows, profile):
    """Each rule table row's Applies to row, under its label."""
    from senaite.pfas import sample_type_icons as sti
    for r in rows:
        r.tail = sti.row(r.key, profile or {}, row_is_off(r))


def rule_lines(sheet, rows, words_of=None, profile=None):
    """(lines, states, mute_of) of a group's rules, as its node and card
    draw them: a line each for the node (its label, its state over its limit
    boxes, its limits in words: `words_of(row)`, else the row's Limits
    cell), no state segments (`states` is empty: each limit box carries its
    own placard, limit_placard), and {row key: (mute attributes, Off)} for
    what greys with it: a QC type's or blank's row by its presence input
    (Removed), a rule by none (its boxes grey themselves). A rule whose
    boxes are all Off greys its own line, never the node."""
    rules, _qct = _qc_modules()
    words_of = words_of or _limit_words_of
    lines, states, mute_of = [], [], {}
    for r in rows:
        cell = r.cells["state"]
        name = _state_name(r, cell)
        dom_id = _dom_id(sheet, name)
        roff = _text(cell.value) == "off"
        rmute = _rule_mute(cell, name) if rules.qc_row_code(r.key) is not None else []
        mute_of[r.key] = (rmute, roff)
        line = state_glyph(cell, dom_id, r.key, profile)
        lines.append(_tag("span", [("class", _cls("pfas-hier-rule", "is-muted" if roff else None))] + rmute,
                          _tag("span", [("class", "pfas-hier-rule-l")], _esc(r.label) + line) +
                          _tag("span", [("class", "pfas-hier-node-v")], _esc(words_of(r)))))
    return lines, states, mute_of


def _cal_group_entry(sheet, profile, env, first):
    """(node, card) of the Calibration group: the node carries its rules,
    each with its state and limits; the card each rule's state (nameless
    segments writing the rule table's inputs), the calibration settings as
    tiles (cal_settings, read from and edited through the inputs QC
    criteria posts: Edit calibration), the levels and per-analyte range in
    words (Edit levels and ranges opens their region), and where each is
    overridden. A rule set Off greys its own line
    and the tile it judges by, never the card."""
    rules, _qct = _qc_modules()
    keys = dict(RULE_GROUPS)[CAL_GROUP]
    rows = [r for r in sheet.rows if r.key in keys and not r.hidden]
    lines, states, mute_of = rule_lines(sheet, rows, profile=profile)
    editor = next((r.get("editor") or "" for r in rules.RULE_LIBRARY
                   if r["key"] in keys and (r.get("editor") or "").startswith("drawer:")), "")
    region_id = _region_id(*editor.split(":", 2)[1:]) if editor else None
    from senaite.pfas import limit_placard
    tiles = []
    for st in cal_settings(profile, env):
        # a limit (the R\u00b2 minimum, each point deviation, the most
        # calibrators dropped) is its own box, with its placard
        box = limit_placard.box_of_names(st["names"])
        tile = _setting_tile(st, form=QC_FORM)
        tiles.append(limit_placard.boxed(tile, profile, box) if box else tile)
    # a rule with no limit box of its own (Above the Calibration Range)
    # carries its placard on its own tile
    for r in rows:
        if r.key == "over_range":
            tiles.append(limit_placard.boxed(_tile(r.label, _limit_words_of(r) or EM_DASH, attrs=TILE_READ),
                                             profile, r.key))
    # the levels and ranges open their region; with none, a window that reads them
    levels = tile_opens("levels") if region_id else TILE_READ
    tiles.append(_tile(LEVELS_LABEL, _levels_words(profile), note=LEVELS_NOTE, attrs=levels))
    tiles.append(_tile(RANGE_LABEL, _range_words(profile), note=RANGE_NOTE, attrs=levels))
    head = "".join(_tag("th", [("scope", "col")], _esc(h)) for h in ("Level", "What it can change", "Where"))
    # each row opens its window in place: the range here, or what Projects
    # and Data Review hold, read, with a Go to inside the window
    body_rows = "".join(
        _tag("tr", [("class", "pfas-hier-tilebox")] +
             (tile_opens(act) if act != "levels" or region_id else TILE_READ),
             "".join(_tag("td", [], _esc(c)) for c in (level, what, where)))
        for level, what, where, act in CAL_OVERRIDES)
    overrides = _scroll(_tag("table", [("class", "pfas-table pfas-hier-table")],
                             _tag("thead", [], _tag("tr", [], head)) + _tag("tbody", [], body_rows)))
    base = (env or {}).get("portal_url") or ""
    # no Edit button: a setting tile opens the calibration window
    acts = card_acts(card_act("cal", EDIT_CAL_WORDS, [("data-cal-settings", True)]),
                     card_act("levels", EDIT_LEVELS_WORDS, [inplace(CAL_LEVELS_TITLE, tables=[
                         {"sel": "#{0} table.cf-coll".format(region_id), "head": LEVELS_LABEL},
                         {"sel": "#{0} table.cf-table".format(region_id), "head": RANGE_LABEL}])])
                     if region_id else "",
                     *[card_act(act, level, [inplace("{0}: {1}".format(group_label(CAL_GROUP), level), read=CAL_ELSEWHERE[act][1],
                                                     goto=go_to(base, page, CAL_ELSEWHERE[act][0]))])
                       for level, act, page in (("Per project", "projects", PROJECTS_PAGE),
                                                ("Per curve", "curves", DATA_REVIEW_PAGE))])
    label = group_label(CAL_GROUP)
    node = _tag("button", [("type", "button"),
                           ("class", _cls("pfas-hier-node", "is-group", "is-selected" if first else None)),
                           ("data-hier-target", CAL_GROUP_KEY), ("aria-pressed", "true" if first else "false"),
                           ("data-rule-group-node", CAL_GROUP)],
                _tag("span", [("class", "pfas-hier-node-t")], _esc(label)) +
                _tag("span", [("class", "pfas-hier-node-v")], _esc(counted(len(rows), "rule"))) +
                "".join(lines))
    card = _tag("section", [("class", "pfas-hier-card is-group"), ("data-hier-card", CAL_GROUP_KEY),
                            ("data-cal-card", True), ("aria-label", label),
                            ("hidden", None if first else True)],
                _tag("h4", [("class", "pfas-hier-card-t")], _esc(label)) +
                _tag("p", [("class", "pfas-hier-card-cap")], _esc(CAL_GROUP_CAP)) +
                applies_lines([(r.key, r.label, mute_of[r.key][1]) for r in rows], profile) +
                _tag("h5", [("class", "pfas-hier-h")], _esc(CAL_SETTINGS_HEAD)) +
                _tag("div", [("class", "pfas-hier-tiles"), ("data-cal-settings-of", True)] + tile_opens("cal"),
                     "".join(tiles)) +
                _tag("h5", [("class", "pfas-hier-h")], _esc(CAL_OVERRIDES_HEAD)) + overrides + acts)
    return node, card


def rules_list(profile, env=None, sheet=None):
    """[{title, entries, removed, add}]: the rule table's rows by list group,
    in the table's order; a removable QC type or blank set Off under its
    group's removed; `add` the QC types + Add QC type offers there."""
    profile = profile or {}
    sheet = sheet or rules_table(profile, env)
    trees = dict((q, tier_tree(profile, env, q)) for q, _l in QC_TYPES)
    order = [g for g, _k in RULE_GROUPS] + [OTHER_GROUP, RECOVERIES_GROUP, BLANKS_GROUP]
    groups = OrderedDict((g, {"title": g, "entries": [], "removed": [], "add": []}) for g in order)
    for i, row in enumerate(sheet.rows):
        e = _rule_entry(sheet, row, profile, trees, i, env)
        g = groups[e["group"]]
        (g["removed"] if e["removable"] and e["off"] and not e["hidden"] else g["entries"]).append(e)
        if e["hidden"]:
            g["add"].append(e["code"])
    return [g for g in groups.values() if g["entries"] or g["removed"] or g["add"]]


# a group's rules in the Rules list, folded under its node: the container
# its node opens and closes (aria-controls)
NEST_ID = "rules-nest-{0}"


def _disclose(node, nest_id, open_=False):
    """A group node as the disclosure of its nest: aria-expanded and
    aria-controls on its button."""
    attrs = _attrs([("aria-expanded", "true" if open_ else "false"), ("aria-controls", nest_id)])
    if not node.startswith("<button"):
        raise ValueError("a group node is a button")
    return "<button" + attrs + node[len("<button"):]


def _group_state(node, active, sub=False):
    """A group node marked active (green) or idle (grey), and one step in
    under its parent (`sub`); its state said in words too, as the page
    redraws it (pfas-components.js, groupStates)."""
    m = re.match(r'^<button([^>]*) class="pfas-hier-node is-group', node)
    if not m:
        raise ValueError("a group node is a button of class pfas-hier-node is-group")
    extra = " {0}{1}".format("is-active" if active else "is-idle", " is-sub" if sub else "")
    node = node.replace('class="pfas-hier-node is-group', 'class="pfas-hier-node is-group' + extra, 1)
    words = _tag("span", [("class", "pfas-sr-hide"), ("data-group-words", True), ("data-on-words", ACTIVE_WORDS),
                          ("data-off-words", IDLE_WORDS)], _esc(ACTIVE_WORDS if active else IDLE_WORDS))
    return node[:-len("</button>")] + words + "</button>"


def _nest(nest_id, title, inner, label=None):
    """A group's (or a parent's) nest: closed until its node opens it; its
    one inner box opens by grid rows, 0fr to 1fr. data-nest-of: the group's
    title (its key in the code); its label read aloud."""
    return _tag("div", [("class", "pfas-hier-nest"), ("id", nest_id), ("data-nest-of", title),
                        ("role", "group"), ("aria-label", label or title), ("hidden", True)],
                _tag("div", [("class", "pfas-hier-nest-in")], inner))


def _parent_entry(pkey, label, children):
    """(node, card) of a parent: its node counts its groups and greens while
    any of them is active; its card lists its groups, each with how many
    rules it holds. Read only: a group
    is opened from its own node in the tree (a tile never moves the page).
    `children`: [(group key, label, rules counted, active)]."""
    active = any(c[3] for c in children)
    node = _tag("button", [("type", "button"), ("class", "pfas-hier-node is-group is-parent"),
                           ("data-hier-target", pkey), ("aria-pressed", "false"),
                           ("data-group-of", " ".join(c[0] for c in children))],
                _tag("span", [("class", "pfas-hier-node-t")], _esc(label)) +
                _tag("span", [("class", "pfas-hier-node-v")], _esc(counted(len(children), "group"))))
    head = "".join(_tag("th", [("scope", "col")], _esc(h)) for h in PARENT_HEADS)
    rows = "".join(_tag("tr", [("data-group-row", c[0])],
                        _tag("td", [], _esc(c[1])) + _tag("td", [], _esc(counted(c[2], "rule"))))
                   for c in children)
    card = _tag("section", [("class", "pfas-hier-card is-group"), ("data-hier-card", pkey), ("aria-label", label),
                            ("hidden", True)],
                _tag("h4", [("class", "pfas-hier-card-t")], _esc(label)) +
                _tag("p", [("class", "pfas-hier-card-cap")], _esc(PARENT_CAP)) +
                _scroll(_tag("table", [("class", "pfas-table pfas-hier-table")],
                             _tag("thead", [], _tag("tr", [], head)) + _tag("tbody", [], rows))))
    return _group_state(node, active), card


def render_rules_list(profile, env=None, sheet=None, groups_of=None, copy_methods=""):
    """The Rules section's List view: <div id="rules-list">, read from the
    table it mirrors; it posts nothing. The Calibration curve, CCV,
    Confirmation and signal, Analyte recoveries and Blanks groups each open
    with the group's node and card, their rules under it; Detection has no
    card (its MDLs are on Analytes). A parent (RULE_PARENTS: Calibration)
    heads its groups. Each node that heads something folds it into one
    container (.pfas-hier-nest) under the node, drawn closed: a parent its
    groups, a group its rules (their tiers, its Removed, its + Add QC type);
    the node opens and closes it (aria-expanded), and choosing a node in it
    opens every nest above it (pfas-components.js). A group node is green
    while anything in it is judged, grey while nothing is.
    `groups_of(sid)`: a section as the Table view draws it (the view's
    section_groups); `copy_methods`: the other methods Copy tiers from
    method offers, as JSON."""
    from senaite.pfas import profile_cards
    profile = profile or {}
    env = env or {}
    sheet = sheet or rules_table(profile, env)
    groups = rules_list(profile, env, sheet)
    drawn = profile_cards._groups_of(profile, env, groups_of)
    regions = rule_editors(profile, env)
    cards = []
    blocks = OrderedDict()          # group title -> [html]
    states = {}                     # group title -> (key, label, rules, active)
    lead = False
    for g in groups:
        carded = g["title"] in GROUP_CARDED
        block = []
        if g["title"] == CAL_GROUP:
            # chosen first when it heads the list
            lead = not blocks
            gnode, gcard = _cal_group_entry(sheet, profile, env, lead)
        elif g["title"] in QC_GROUP_KEYS:
            gnode, gcard = profile_cards.qc_group_entry(g["title"], sheet, profile, env, drawn, regions,
                                                        copy_methods)
        else:
            gnode, gcard = None, None
        if gnode:
            shown = [e for e in g["entries"] + g["removed"] if not e["hidden"]]
            active = any(not e["off"] for e in shown)
            n_rules = len(shown)
            states[g["title"]] = (GROUP_KEYS[g["title"]], group_label(g["title"]), n_rules, active)
            block.append(_group_state(gnode, active, sub=g["title"] in PARENT_OF))
            cards.append(gcard)
        else:
            block.append(_tag("p", [("class", "pfas-hier-group")], _esc(g["title"])))
        # a QC type's tiers follow its node, in the list or under Removed
        members = [e["node"] + "".join(e["kids"]) for e in g["entries"]]
        removed = "".join(e["node"] + "".join(e["kids"]) for e in g["removed"])
        members.append(_tag("div", [("class", "pfas-hier-removed"), ("data-removed-of", g["title"]),
                                    ("hidden", None if removed else True)],
                            _tag("p", [("class", "pfas-hier-group is-sub")], _esc(REMOVED_WORDS)) + removed))
        if g["add"]:
            members.append(_tag("div", [("class", "pfas-hier-actions")],
                                _list_button(ADD_QC_WORDS, [("data-qc-add", ",".join(g["add"])),
                                                            ("data-qc-group", g["title"])])))
        if carded:
            # under the group's node, closed until the node opens it
            block[0] = _disclose(block[0], NEST_ID.format(GROUP_KEYS[g["title"]]))
            block.append(_nest(NEST_ID.format(GROUP_KEYS[g["title"]]), g["title"], "".join(members),
                               group_label(g["title"])))
        else:
            block += members
        blocks[g["title"]] = block
        cards += [e["card"] + "".join(e["tier_cards"]) for e in g["entries"] + g["removed"]]
    # each parent heads its groups, where its first group would stand
    nodes = []
    done = set()
    for title, block in blocks.items():
        pkey = PARENT_OF.get(title)
        if not pkey:
            nodes.append("".join(block))
            continue
        if pkey in done:
            continue
        done.add(pkey)
        _k, plabel, kids = next(p for p in RULE_PARENTS if p[0] == pkey)
        kids = [t for t in kids if t in blocks]
        pnode, pcard = _parent_entry(pkey, plabel, [states[t] for t in kids if t in states])
        nodes.append(_disclose(pnode, NEST_ID.format(pkey)) +
                     _nest(NEST_ID.format(pkey), plabel, "".join("".join(blocks[t]) for t in kids)))
        cards.insert(0, pcard)
    html = "".join(nodes)
    # the Calibration curve group chosen when it heads its parent and the
    # parent the list, else the first rule drawn, as a page with no script
    # shows it
    first = CAL_GROUP_KEY if lead else next((e["key"] for g in groups for e in g["entries"] + g["removed"]
                                             if not e["hidden"]), None)
    if first and not lead:
        mark = _esc(first)
        html = html.replace('data-hier-target="{0}" aria-pressed="false"'.format(mark),
                            'data-hier-target="{0}" aria-pressed="true"'.format(mark), 1)
        cards = [c.replace('data-hier-card="{0}" hidden="hidden"'.format(mark),
                           'data-hier-card="{0}"'.format(mark), 1) for c in cards]
    if first:
        html = _open_nests_to(html, first)
    from senaite.pfas import limit_placard
    # the seeded tiers' names in words, for what the page writes of a tier
    return _tag("div", [("id", LIST_ID), ("class", "pfas-hier"), ("data-hier", "rules"),
                        ("data-tier-words", json.dumps(limit_placard.TIER_WORDS, sort_keys=True))],
                _tag("div", [("class", "pfas-hier-list"), ("role", "group"), ("aria-label", "Rules")], html) +
                _tag("div", [("class", "pfas-hier-cards")], "".join(cards)))


def _open_nests_to(html, key):
    """`html` with every nest that holds node `key` drawn open and its
    node's aria-expanded true, as the page opens them for a node chosen."""
    at = html.find('data-hier-target="{0}"'.format(_esc(key)))
    if at < 0:
        return html
    # the nests still open at the node: those begun before it and not closed
    stack = []
    for m in re.finditer(r'<div class="pfas-hier-nest" id="([^"]+)"|<div\b|</div>', html[:at]):
        tok = m.group(0)
        if m.group(1):
            stack.append(m.group(1))
        elif tok.startswith("<div"):
            stack.append(None)
        elif stack:
            stack.pop()
    for nid in [n for n in stack if n]:
        html = re.sub(r'(<div class="pfas-hier-nest" id="{0}"[^>]*?) hidden="hidden"'.format(re.escape(nid)),
                      r"\1", html, count=1)
        html = html.replace('aria-expanded="false" aria-controls="{0}"'.format(nid),
                            'aria-expanded="true" aria-controls="{0}"'.format(nid), 1)
    return html


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
            elif col.kind == "switch" and "tri" in (cell.data or {}):
                names.add(cell.data["tri"])         # its own value, the switch nameless
            elif col.kind in ("switch", "flag"):
                names.update((cell.name, _present_name(cell.name)))
                names.update(n for n, _v in (cell.data or {}).get("kept") or ())
            else:
                names.add(cell.name)
    return names


# ── what a grid holds, by the name each value posts under ──────────────────

def sheet_values(sheet):
    """OrderedDict {posted name: value as the grid's input holds it} for the
    number, window, text and choice cells a person types or picks (an
    inherited cell holds "": blank means inherit). Two methods' grids name
    the same analyte, matrix and column alike, so the names match one
    method's values to another's (Copy from method)."""
    out = OrderedDict()
    for row in sheet.rows:
        for col in sheet.columns:
            cell = row.cells.get(col.key)
            if cell is None or not _editable(col, cell) or cell.state in ("na", "off"):
                continue
            if col.kind == "pair":
                for n, v in zip(cell.name, _pair(cell.value)):
                    out[n] = "" if cell.state == "inherited" or v is None else _text(v)
            elif col.kind in ("num", "text", "select") and cell.name:
                v = cell.value
                out[cell.name] = "" if cell.state == "inherited" or v is None else _text(v)
    return out


# the grids "Copy from method" offers, by tab
COPY_TABS = ("analytes", "standards", "matrices")


def copy_values(profile, env, tab):
    """The values `profile`'s grid on `tab` holds (sheet_values), for another
    method's page to take from; {} for a tab with no such grid."""
    builders = {"analytes": analytes_sheet, "standards": standards_sheet, "matrices": matrices_sheet}
    if tab not in builders:
        return OrderedDict()
    # a collection's row is named by its place ("c__<id>__<n>__"), which is
    # another row in another method: never matched
    return OrderedDict((n, v) for n, v in sheet_values(builders[tab](profile or {}, env)).items()
                       if not n.startswith("c__"))


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
    if not isinstance(sec, (cf.Collection, cf.Table)):
        drawn = fold_groups(sid, drawn, profile)
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


_BOX_ATTR = re.compile(r'data-limit-box="([^"]+)"')


def rule_table_boxes(rows):
    """The limit boxes the rule table's Limits cells draw, each once, in
    their order: what the Rules counts count."""
    out = []
    for r in rows:
        cell = r.cells.get("limits")
        for k in _BOX_ATTR.findall((cell.html if cell is not None else None) or ""):
            for a, b in (("&quot;", '"'), ("&#39;", "'"), ("&#x27;", "'"), ("&lt;", "<"), ("&gt;", ">"),
                         ("&amp;", "&")):
                k = k.replace(a, b)
            if k not in out:
                out.append(k)
    return out


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
        # a QC type drawn hidden, for + Add QC type, is one of the not used;
        # the states count the limit boxes, as their placards show them
        shown = [r for r in rules_table(profile, env).rows if not r.hidden]
        from senaite.pfas import limit_states
        boxes = rule_table_boxes(shown)
        states = [limit_states.state_of(profile, k) or "enforced" for k in boxes]
        unused = len(unused_rules(profile, env))
        return MIDDOT.join([counted(len(shown), "rule"), counted(len(boxes), "limit")] +
                           ["{0} {1}".format(states.count(st), st) for st in rules.STATES] +
                           (["{0} not used".format(unused)] if unused else []))
    if sid == "windows":
        return _windows_summary(mps, profile, env)
    if sid == "xbatch":
        most = cf.current(mps.SECTIONS["xbatch"], profile).get("f__max_size")
        return "No limit" if most in (None, "") else "{0} per worksheet".format(_g(most))
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
    if sid == "dilrec":
        v = mps.dilution_recovery(profile)
        return dict(mps.DILUTION_RECOVERIES)[v] if v else DILREC_UNSET
    if sid == "lrr":
        return "{0}: {1}".format(RATIO_LABEL, dict(mps.LINKED_RATIOS)[mps.linked_response_ratio(profile)])
    if sid == "engine_rec":
        from senaite.pfas import method_engine
        places = method_engine.recovery_decimals(profile)
        return "Whole percent" if not places else counted(places, "decimal place")
    parts = [(NAME_FIELDS, "setting")] if sid == "names" else []
    for part in SUMMARY_PARTS.get(sid, (sid,)):
        parts += _counts(cf, mps, profile, env, part)
    return _joined(parts)
