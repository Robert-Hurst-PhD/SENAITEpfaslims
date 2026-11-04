# -*- coding: utf-8 -*-
"""Declarative configuration sections.

A section of a settings page is DECLARED once -- its fields, their kinds,
units, limits, whether they are required, and where they live in the stored
value -- and this module does the rest the same way for every page:

  render   the stored value as the field's value; a default is only a
           placeholder, never a value (a value is saved as a choice);
           a choice field always offers the stored value, even when it is
           not among the usual options;
  parse    only the section that was submitted (a field of another section
           is never touched); a blank number is UNSET (None), never 0, and
           blank text is empty;
           a required field left blank, a non-number, or a value outside its
           limits is REFUSED with the field named -- nothing is coerced;
  stamp    a version stamp of this section's own values, so a save made from
           a page opened before someone else changed THIS section is refused,
           while edits to other sections do not collide;
  save     through the store's own save function, so the change history
           (config_history) and every side effect of a normal save apply.

These rules are written once, here, for every page. Pure; no Zope imports.
Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function

import copy
import json
import re

try:
    _STR = basestring              # noqa: F821  (Py2.7)
except NameError:                  # pragma: no cover  (Py3 tests)
    _STR = str

from senaite.pfas import config_history as _history

REMOVE = object()          # a parsed value meaning "delete this key"
CLEARED = object()         # a parsed value meaning "store None: deliberately none"

# the placeholder of a table cell whose blank takes the row above's value
# (a matrix row of Certificate format inherits the All matrices row): a
# text box shows it, a choice's blank option reads it and its select is
# drawn muted (is-inherited) while that option is chosen
INHERITED = u"\u00b7"

NUMBER, INT, BOOL, TEXT, TEXTAREA, CHOICE, MULTI = (
    "number", "int", "bool", "text", "textarea", "choice", "multi")


# What one changed control counts as in a page's unsaved-changes note ("2
# cells, 1 tier"): a section's field is a setting, a table's cell a cell, a
# collection's row a row, unless its section's rows are named here; a spike
# level collection (spk_<QC type>) holds levels.
COLLECTION_KIND = {"tiers": "tier", "tiers_lfb": "tier", "lfsmd": "tier", "dup": "tier",
                   "cal_levels": "level", "mtx": "matrix", "ls": "standard", "eis_grid": "cell",
                   "lbl": "label"}
SPIKE_PREFIX = "spk_"
# every kind, in the order a note lists them (the method profile editor's
# footer script lists the same, in this order)
CHANGE_KINDS = ("cell", "flag", "tier", "level", "row", "rule", "setting", "standard", "matrix", "label")


def change_kind(name):
    """The kind a control posting `name` counts as: "setting" for a section
    field (f__...), the section's kind for a table cell (t__<id>__...) or a
    collection row (c__<id>__...), None for a name no declared section posts."""
    name = u"%s" % (name or u"")
    if name.startswith(u"f__"):
        return u"setting"
    head, _sep, rest = name.partition(u"__")
    if head not in (u"t", u"c") or not rest:
        return None
    token = rest.partition(u"__")[0]
    for sid, kind in COLLECTION_KIND.items():
        if token == _enc(sid):
            return u"%s" % kind
    if token.startswith(_enc(SPIKE_PREFIX)):
        return u"level"
    return u"cell" if head == u"t" else u"row"


def option_name(f, value):
    """One checkbox per option (MULTI): a list-valued field would be collapsed
    to its first value by flatten_form."""
    return u"%s__opt__%s" % (f.name, _enc(value))


PICKER = u"picker"


def is_picker(f):
    """A MULTI drawn as the search picker: ONE hidden field posting the
    chosen list as JSON under the field's own name (a field posted once per
    choice would reach the save as its first value only, flatten_form)."""
    return f.kind == MULTI and f.widget in (PICKER, "picker")


def _multi_json(values):
    return json.dumps(list(values or []))


def _offered_json(choices, chosen):
    """The picker's options as JSON [[value, label], ...]: the field's
    choices, then any chosen value no longer among them (kept as stored)."""
    out = [[c[0], c[1]] for c in choices]
    out += [[x, u"%s (stored value)" % x] for x in (chosen or []) if x not in [c[0] for c in choices]]
    return json.dumps(out)


def _picked(f, raw, saved, label, choices):
    """(list | _SKIP, error) for a picker's posted JSON list: only offered
    choices or what is stored already, each once, in the posted order."""
    try:
        values = json.loads(_text(raw) or u"[]")
    except ValueError:
        values = None
    if not isinstance(values, list) or not all(isinstance(v, _STR) for v in values):
        return _SKIP, u"%s: not a list of choices." % label
    allowed = [c[0] for c in choices] + list(saved or [])
    out = []
    for v in values:
        if v not in allowed:
            return _SKIP, u"%s: %r is not one of the options." % (label, v)
        if v not in out:
            out.append(v)
    return out, None


def _shown(v, decimals=None):
    """A stored value as the form shows it. A float is shown in full
    (repr), so an unchanged save keeps it: "%s" would cut 1/3 (EPA 537.1
    LRB) to 0.333333333333. A field drawn to `decimals` shows it rounded;
    _value keeps the stored value when that text comes back."""
    if isinstance(v, float):
        return u"%r" % (round(v, decimals) if decimals is not None else v)
    return u"%s" % v


class Field(object):

    def __init__(self, path, label, kind=NUMBER, unit=u"", help=u"",
                 placeholder=u"", required=False, minimum=None, maximum=None,
                 choices=None, blank=u"unset", greater_than=None,
                 range_hi=None, scale=None, step=None, widget=None, options=None,
                 empty=None, show_if=None, rule=None, decimals=None, default=None, noun=None, words=None,
                 choice_help=None, align=None, resolved=None, range_label=None):
        self.path = (tuple(int(x) if x.isdigit() else x for x in path.split("."))
                     if isinstance(path, _STR) else tuple(path))
        self.name = u"f__" + u"__".join(u"%s" % p for p in self.path)
        self.label = label
        self.kind = kind
        self.unit = unit
        self.help = help
        self.placeholder = placeholder
        self.required = required
        self.minimum = minimum
        self.maximum = maximum
        # a list of (value, label), or callable(stored) -> that list when the
        # options depend on the stored value (e.g. every unit already in use)
        self.choices = choices if callable(choices) else list(choices or [])
        self.greater_than = greater_than  # a strict lower bound (0 < days)
        self.blank = blank          # "unset" -> None, "remove" -> key deleted,
                                    # "none" -> None stored, the key created
        # How the page DRAWS the field; what is saved never changes.
        #   range_hi  the key of the sibling field that is this one's upper end
        #             (declared on the lower end): the pair is drawn as one
        #             two-handle slider, or as one value in a table row
        #   scale     (lo, hi) the slider's display range: never a limit
        #   step      the number input's step; default 1 for INT, else "any"
        #   widget    "chips" (a comma list) or "pairs" ("A=B, C=D") on a TEXT field;
        #             "seg" on a CHOICE: a segmented control instead of a select
        #   empty     what a range drawn as a slider shows for an unset end
        #             (default "none"; u"" shows nothing)
        #   show_if   (path of a field in the same section, value): the field
        #             is shown only while that one holds the value, or one
        #             of the values when a tuple of them is given. Hidden,
        #             never disabled: its value still posts, so a save never
        #             clears it
        #   options   [value | (value, label)], or callable(profile, env) of
        #             that; with a widget, the only values a chip may take
        #   widget    "picker" on a MULTI: the search picker (is_picker)
        #   choice_help  {value: a line} explaining each choice of a CHOICE, drawn
        #             under it, one line per choice
        #   words     the words a NUMBER may hold instead of a number ("none"),
        #             stored as the word; a table's check says where one applies.
        #             The config-form macros draw it as a text box (a number
        #             box drops a word), a blank cell showing what it resolves
        #             to as its placeholder
        #   noun      what a picker's options are ("matrices"), in its search
        #             box and its empty text
        #   default   a MULTI's options, or a CHOICE's value, shown chosen
        #             while nothing is stored; posted back as drawn, nothing
        #             is stored
        #   decimals  a number shown rounded to this many places; posted
        #             back unchanged, the stored value is kept
        #   rule      a rule switch key (Rule Toggles & QC Run): while the
        #             method has it off the field reads N/A, greyed and
        #             read-only, so its value still posts and is kept
        #   align     a table or collection column's alignment, "left" or
        #             "right"; its heading is aligned as its cells are. By
        #             default a number ends at the right, anything else
        #             starts at the left
        #   resolved  the number an empty box resolves to (or
        #             callable(profile, env) -> it, None for none): drawn
        #             muted in the empty box, never posted; the help line
        #             says the rule
        #   range_label  a pair's one name (on its lower end): its heading
        #             and its value's name; default the lower end's label
        #             without "min"
        self.range_hi = range_hi
        self.range_hi_name = None
        if range_hi:
            hi = tuple(int(x) if x.isdigit() else x for x in range_hi.split(".")) \
                if isinstance(range_hi, _STR) and u"." in range_hi else (range_hi,)
            self.range_hi_name = u"f__" + u"__".join(
                u"%s" % q for q in (self.path[:-1] + hi if len(hi) == 1 else hi))
        self.scale = tuple(scale) if scale else None
        self.step = step
        self.widget = widget
        self.options = options if callable(options) else (list(options) if options is not None else None)
        self.empty = empty
        self.decimals = decimals
        self.default = default
        self.noun = noun
        self.words = tuple(w.lower() for w in words or ())
        self.choice_help = dict(choice_help or {})
        if align not in (None, u"left", u"right"):
            raise ValueError("unknown alignment: {0}".format(align))
        self.align = align or (u"right" if kind in (NUMBER, INT) else u"left")
        self.rule = rule
        self.resolved = resolved
        self.range_label = range_label
        self.show_if = None
        # a collection column's show_if names a column of the same row
        self.show_if_column = tuple(show_if) if show_if else None
        if show_if:
            path, value = show_if
            self.show_if = (u"f__" + u"__".join(u"%s" % p for p in path.split(".")), value)


class Section(object):

    def __init__(self, id, title, base, groups, intro=u"", group_help=None):
        self.id = id
        self.title = title
        self.base = tuple(base)     # path of the section inside the stored value
        self.groups = groups        # [(group title, [Field, ...]), ...]
        self.intro = intro
        # {group title: a line}: a rule every field of the group follows,
        # said once above the group's fields, never under each of them
        self.group_help = dict(group_help or {})

    def fields(self):
        return [f for _title, fields in self.groups for f in fields]


# ── reading the stored value ─────────────────────────────────────────────────

def _get(value, path):
    """Walk dict keys -- and list positions, for an int segment (e.g. the
    first tier of a QC type: ("tiers", 0, "rpd_max"))."""
    for p in path:
        if isinstance(value, list) and isinstance(p, int):
            if p >= len(value):
                return None
            value = value[p]
        elif isinstance(value, dict) and p in value:
            value = value[p]
        else:
            return None
    return value


def _descend(node, p):
    """The child at `p`, created if missing (a dict, or a list slot)."""
    if isinstance(node, list) and isinstance(p, int):
        while len(node) <= p:
            node.append({})
        if not isinstance(node[p], dict):
            node[p] = {}
        return node[p]
    return node.setdefault(p, {})


def _bound(obj, stored):
    """A table / collection whose columns depend on the stored value (e.g.
    one column per matrix) resolved for this value; others returned as is."""
    if callable(getattr(obj, "columns", None)):
        bound = copy.copy(obj)
        bound.columns = obj.columns(stored or {})
        return bound
    return obj


def current(section, stored):
    """{field.name: stored value (or None)} for the section's fields."""
    base = _get(stored or {}, section.base) or {}
    return dict((f.name, _get(base, f.path)) for f in section.fields())


def stamp(section, stored, env=None):
    """Version stamp of THIS section's values only."""
    if isinstance(section, Table):
        return stamp_table(section, stored, env)
    if isinstance(section, Collection):
        return _history.fingerprint(section.read(stored or {}))
    vals = current(section, stored)
    return _history.fingerprint(dict((k, v) for k, v in vals.items() if v not in (None, u"", "")))


def step_text(f):
    """The step attribute: the declared one, else 1 for a whole number, else any."""
    if f.step is not None:
        return u"%s" % f.step
    return u"1" if f.kind == INT else u"any"


def scale_text(f):
    return u"%s,%s" % (f.scale[0], f.scale[1]) if f.scale else u""


_MIN_WORD = re.compile(r"(?:^|\s+)min(?:imum)?(?=\s|$|\()", re.I)


def pair_label(label, fallback=u""):
    """A pair's one label from its lower end's ("Recovery Min" -> "Recovery");
    `fallback` when nothing but a unit or a symbol is left."""
    out = _MIN_WORD.sub(u"", u"%s" % label, count=1).strip()
    return out if re.search(r"[A-Za-z]{3}", out) else (fallback or out)


def _pair_name(lo, fallback=u""):
    """A pair's one name: the one its lower end declares, else pair_label."""
    return lo.range_label or pair_label(lo.label, fallback)


def resolved_text(f, stored, env=None):
    """What an empty box of `f` resolves to, as the page shows it (u"" for
    nothing): the declared number, or what its callable gives for this
    profile."""
    r = f.resolved(stored or {}, env) if callable(f.resolved) else f.resolved
    return u"" if r in (None, u"", "") else _shown(r)


def _options(f, stored, env=None, override=None):
    """(widget, JSON of [[value, label], ...] or u"") for a TEXT field drawn as chips.
    `override` is a row's own {"widget", "options"} (one table, rows that differ)."""
    ov = override or {}
    widget = ov.get("widget") or f.widget
    opts = ov["options"] if "options" in ov else f.options
    if callable(opts):
        opts = opts(stored or {}, env)
    if widget not in (u"chips", u"pairs", "chips", "pairs"):
        return None, u""
    if opts is None:
        return widget, u""
    out = [[o, o] if isinstance(o, _STR) else [o[0], o[1] if len(o) > 1 else o[0]] for o in opts]
    return widget, json.dumps(out)


def _pair_ends(fields):
    """{hi name: lo field} for the declared pairs among `fields`."""
    names = dict((f.name, f) for f in fields)
    return dict((f.range_hi_name, f) for f in fields
                if f.range_hi_name and f.range_hi_name in names and names[f.range_hi_name].kind in (NUMBER, INT))


def na_text(f, env):
    """The N/A note of a field whose governing rule switch is off, else "".
    env["rules"] = {rule key: on}, env["rule_labels"] = {rule key: label}."""
    rules = (env or {}).get("rules") if isinstance(env, dict) else None
    if not f.rule or not rules or rules.get(f.rule, True):
        return u""
    label = ((env or {}).get("rule_labels") or {}).get(f.rule, f.rule)
    return u"N/A: %s is off on Rule Toggles & QC Run" % label


def render(section, stored, env=None):
    """What the template draws: one dict per field, grouped."""
    if isinstance(section, Table):
        return render_table(section, stored, env)
    if isinstance(section, Collection):
        return render_collection(section, stored, env)
    vals = current(section, stored)
    groups = []
    by_name = dict((f.name, f) for f in section.fields())
    hi_ends = _pair_ends(section.fields())

    def one(f):
        v = vals[f.name]
        choices = _choices(f, stored, env)
        if f.kind == CHOICE and v not in (None, u"", "") and v not in [c[0] for c in choices]:
            choices.append((v, u"%s (stored value)" % v))
        options = []
        if f.kind == MULTI:
            chosen = set(v if v is not None else (f.default or []))
            options = [{"value": c[0], "label": c[1], "name": option_name(f, c[0]),
                        "checked": c[0] in chosen} for c in choices]
            options += [{"value": x, "label": u"%s (stored value)" % x, "name": option_name(f, x),
                         "checked": True} for x in (v or []) if x not in [c[0] for c in choices]]
        if f.kind == TEXT:
            widget, opts_json = _options(f, stored, env)
        elif is_picker(f):
            widget, opts_json = PICKER, _offered_json(choices, v)
        else:
            widget, opts_json = (u"seg" if f.kind == CHOICE and f.widget in (u"seg", "seg") else None), u""
        return {
            "name": f.name, "label": f.label, "kind": f.kind, "unit": f.unit,
            "options": options,
            "help": f.help, "choice_help": [(c[1], f.choice_help[c[0]]) for c in choices if c[0] in f.choice_help],
            "placeholder": f.placeholder, "required": f.required,
            "min": f.minimum, "max": f.maximum, "choices": choices, "words": list(f.words),
            "step": step_text(f), "scale": scale_text(f),
            "widget": widget, "options_json": opts_json, "pair": None, "pair_label": u"",
            "empty": f.empty,
            "show_if": f.show_if,
            # a field shown for any of several values names them, space-separated
            "show_values": (u" ".join(f.show_if[1]) if f.show_if and isinstance(f.show_if[1], tuple)
                            else None),
            "na": na_text(f, env),
            "noun": f.noun,
            "resolved": resolved_text(f, stored, env),
            "value": (_multi_json(v) if is_picker(f) else
                      (f.default if f.kind == CHOICE and f.default is not None else u"") if v is None
                      else (v if f.kind in (BOOL,) else _shown(v, f.decimals))),
            "checked": bool(v) if f.kind == BOOL else False,
            "counts_as": change_kind(f.name),
        }

    for title, fields in section.groups:
        rows, shown = [], []
        for f in fields:
            row = one(f)
            rows.append(row)
            if f.name in hi_ends:
                continue                  # drawn with its lower end (still listed in "fields")
            shown.append(row)
            hi = by_name.get(f.range_hi_name) if f.range_hi_name in by_name and f.kind in (NUMBER, INT) else None
            if hi is not None and hi.kind in (NUMBER, INT):
                row["pair"] = one(hi)
                row["pair_label"] = _pair_name(f, title)
                row["scale"] = scale_text(f) or scale_text(hi)
        groups.append({"title": title, "fields": rows, "shown": shown,
                       "help": section.group_help.get(title, u"")})
    return groups


# ── parsing a submitted section ──────────────────────────────────────────────

def _text(raw):
    """A submitted value as stripped unicode (Zope hands over UTF-8 bytes)."""
    if raw is None:
        return u""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return (u"%s" % raw).strip()


_SKIP = object()           # a field whose submitted value was refused


def _choices(f, stored, env=None):
    """A field's options; callable choices get the stored value and `env`,
    what the page knows that the store does not (e.g. the inventory's lots)."""
    return list(f.choices(stored or {}, env)) if callable(f.choices) else list(f.choices)


def _value(f, raw, saved, label=None, choices=None):
    """(value | REMOVE | _SKIP, error or None) for one submitted field.

    `saved` is the value stored on the server (a choice accepts it even when
    it is not a listed option). `label` names the field in an error; a table
    cell passes "<row> <column>"."""
    label = label or f.label
    if f.kind == BOOL:
        return raw is True or _text(raw).lower() in (u"1", u"on", u"true", u"yes"), None
    if f.kind == MULTI:
        return raw, None                 # parse() hands over the chosen list
    text = _text(raw)
    if text == u"":
        if f.required:
            return _SKIP, u"%s is required." % label
        if f.blank == u"remove":
            return REMOVE, None
        if f.blank == u"none":
            return CLEARED, None
        if saved in (u"", ""):
            return saved, None            # stored empty stays empty: not "" -> None
        return (u"" if f.kind in (TEXT, TEXTAREA) else None), None
    if f.kind in (NUMBER, INT):
        if text.lower() in f.words:
            return text.lower(), None
        try:
            num = float(text)
            if f.kind == INT:
                if num != int(num):
                    raise ValueError
                num = int(num)
        except ValueError:
            return _SKIP, u"%s must be %s, not %r." % (
                label, u"a whole number" if f.kind == INT else u"a number", text)
        if f.minimum is not None and num < f.minimum:
            return _SKIP, u"%s must be at least %s." % (label, f.minimum)
        if f.maximum is not None and num > f.maximum:
            return _SKIP, u"%s must be at most %s." % (label, f.maximum)
        if f.greater_than is not None and num <= f.greater_than:
            return _SKIP, u"%s must be more than %s." % (label, f.greater_than)
        if (f.decimals is not None and isinstance(saved, float)
                and _shown(saved, f.decimals) == _shown(num)):
            return saved, None            # the rounded display came back: unchanged
        return num, None
    if f.kind == CHOICE:
        allowed = [c[0] for c in (f.choices if choices is None else choices)]
        if allowed and text not in allowed and text != _text(saved):
            return _SKIP, u"%s: %r is not one of the options." % (label, text)
    return text, None


def parse(section, form, stored, env=None):
    """(updates {path: value|REMOVE}, errors [text]) for the submitted section.

    `stored` is the value as saved on the server: a choice field accepts its
    stored value even when it is not a listed option (it was offered on the
    page for that reason), and nothing sent by the browser can widen that.

    Call only when the form says it is this section (form["_section"]). A
    checkbox that is not submitted is False: the section's own form always
    carries all of its fields, so absence can only mean unchecked.
    """
    if isinstance(section, Table):
        return parse_table(section, form, stored, env)
    if isinstance(section, Collection):
        return parse_collection(section, form, stored, env)
    updates, errors = {}, []
    saved = current(section, stored)
    for f in section.fields():
        if is_picker(f):
            if form.get(f.name) is None:
                continue                # not drawn: unchanged
            value, error = _picked(f, form.get(f.name), saved[f.name], f.label, _choices(f, stored, env))
            if error:
                errors.append(error)
            elif not (saved[f.name] is None and not value):
                updates[f.path] = value     # nothing stored, nothing chosen: still unstored
            continue
        if f.kind == MULTI:
            offered = [c[0] for c in _choices(f, stored, env)] + list(saved[f.name] or [])
            ticked = set(v for v in offered if _text(form.get(option_name(f, v))).lower()
                         in (u"1", u"on", u"true", u"yes"))
            if saved[f.name] is None and f.default is not None and ticked == set(f.default):
                continue                # the default, as drawn: still unstored
            if saved[f.name] is None and not ticked:
                continue                # nothing stored, nothing ticked: still unstored
            old = list(saved[f.name] or [])
            # stored order kept; newly ticked ones follow in option order
            updates[f.path] = ([v for v in old if v in ticked] +
                               [v for v in offered if v in ticked and v not in old])
            continue
        if (f.kind == CHOICE and f.default is not None and saved[f.name] is None
                and _text(form.get(f.name)) == f.default):
            continue                    # the default, as drawn: still unstored
        value, error = _value(f, form.get(f.name), saved[f.name],
                              choices=_choices(f, stored, env))
        if error:
            errors.append(error)
        elif f.kind == BOOL and value is False and saved[f.name] is None:
            continue                    # never stored, posted off: still unstored
        elif value is not _SKIP:
            updates[f.path] = value
    return updates, errors


def apply(section, stored, updates, env=None):
    """A copy of `stored` with the section's updates written in."""
    if isinstance(section, Table):
        return apply_table(section, stored, updates, env)
    if isinstance(section, Collection):
        return section.write(copy.deepcopy(stored or {}), updates)
    value = copy.deepcopy(stored or {})
    # A block the profile does not have, saved with nothing in it (blank
    # fields, unticked boxes), stays absent: an unchanged save of a section
    # the lab never filled must store nothing. An existing block is saved as
    # always.
    if section.base and _get(stored or {}, section.base) is None and all(
            v is None or v is REMOVE or v is CLEARED or v is False or v == u""
            for v in updates.values()):
        return value
    base = value
    for p in section.base:
        base = _descend(base, p)
    for path, new in updates.items():
        node = base
        if new is CLEARED:
            # a field whose blank is a decision ("none"): stored as None in
            # the section, creating the key
            for p in path[:-1]:
                node = node.setdefault(p, {})
            node[path[-1]] = None
            continue
        if new is None or new is REMOVE:
            # an unset value never CREATES a missing block: an untouched save
            # of a field the profile has no parent for stores nothing
            for p in path[:-1]:
                node = node.get(p) if isinstance(node, dict) else None
                if node is None:
                    break
            if not isinstance(node, dict):
                continue
        else:
            for p in path[:-1]:
                node = node.setdefault(p, {})
        if new is REMOVE:
            node.pop(path[-1], None)
        elif new is None and path[-1] not in node:
            continue                    # an unset value never creates a key either
        else:
            node[path[-1]] = new
    return value


# ── tables: the same rules, one row per key ──────────────────────────────────
#
# A Table is a grid of the same fields (columns) repeated for a set of rows
# that the stored value itself decides -- e.g. one row per analyte the matrix
# reports, grouped by matrix. Declared with a `rows(stored)` function that
# returns (groups, rows):
#
#     groups  [{"key", "label", "unit"}]         -- e.g. one per matrix
#     rows    [{"key": (k1, k2, ...), "group", "label", "sublabel"}]
#
# Values live at stored[base][k1][k2]...[column path]. Only the rows listed
# are parsed or written: a row not on the page (an analyte excluded from a
# matrix) keeps its stored value. A row whose columns are all unset
# is removed, and an emptied parent with it, so an untouched page stores
# nothing. Row keys travel ENCODED in field names: Zope reads ":<letter>" in a
# name as a type converter, and analyte keywords carry colons.


class Table(object):
    """`read(stored) -> {row key: {column name: value}}` and
    `write(stored, {row key: {column path: value}}, env) -> stored` replace the
    default nested-dict storage under `base` when the store keeps its rows
    another way -- e.g. a list of {"analyte", "factor"} dicts holding only the
    rows that differ from the default.
    A row may carry `defaults` {column key: value}: the row IS the default (a
    choice draws the value selected, with no blank option), and a posted
    default where nothing is stored writes nothing."""

    def __init__(self, id, title, base, columns, rows, check=None, intro=u"",
                 read=None, write=None, rows_take_env=False, row_heading=u"Analyte",
                 info=None):
        self.id = id
        # [(id, heading)]: read-only columns after the inputs, showing what
        # another owner holds (e.g. the regulatory limits beside an RL). A
        # row gives {id: [{"text", "warn", "off"}]}; nothing here is saved.
        self.info = list(info or [])
        self.row_heading = row_heading      # the first column's heading
        # rows(stored, env) when the rows show page data (a suggestion, or
        # site records such as the regulatory limits); the stamp is taken
        # with the same env, so a change to which rows are listed makes an
        # open page stale. rows(stored, None) must still work (tests).
        self.rows_take_env = rows_take_env
        self.title = title
        self.read = read
        self.write = write
        self.base = tuple(base)
        self.columns = columns      # [Field] with paths relative to the row
        self.rows = rows            # callable(stored) -> (groups, rows)
        self.check = check          # callable(row, {column name: value}) -> error | None
        self.intro = intro

    def fields(self):
        # per-profile columns (one per matrix) listed for an empty profile
        return list(self.columns({}) if callable(self.columns) else self.columns)


def _enc(key):
    """A form-name-safe token: letters and digits kept, anything else _hh
    (so "__", the separator, never occurs inside a token)."""
    if isinstance(key, bytes):
        key = key.decode("utf-8")
    out = []
    for ch in u"%s" % key:
        if (u"a" <= ch <= u"z") or (u"A" <= ch <= u"Z") or (u"0" <= ch <= u"9"):
            out.append(ch)
        else:
            out.extend(u"_%02x" % b for b in bytearray(ch.encode("utf-8")))
    return u"".join(out)


def cell_name(table, row_key, column):
    return u"__".join([u"t", _enc(table.id)] + [_enc(k) for k in row_key] +
                      [_enc(p) for p in column.path])


def _row_node(table, stored, row_key):
    return _get(stored or {}, table.base + tuple(row_key)) or {}


def _rows(table, stored, env=None):
    if table.rows_take_env:
        return table.rows(stored or {}, env)
    return table.rows(stored or {})


def _cells(table, stored, row_key):
    if table.read is not None:
        vals = table.read(stored or {}).get(tuple(row_key)) or {}
        return dict((c.name, vals.get(c.path[0])) for c in table.columns)
    node = _row_node(table, stored, row_key)
    return dict((c.name, _get(node, c.path)) for c in table.columns)


def stamp_table(table, stored, env=None):
    """The listed rows' keys AND values: a change to which rows the page shows
    (e.g. the inclusion grid) also makes an open page stale, so no field can
    be read against a row set it was not drawn for."""
    table = _bound(table, stored)
    _groups, rows = _rows(table, stored, env)
    blob = []
    for r in rows:
        vals = dict((k, v) for k, v in _cells(table, stored, r["key"]).items()
                    if v not in (None, u"", ""))
        blob.append([list(r["key"]), vals])
    return _history.fingerprint(blob)


def g_unit(by_group, row):
    return (by_group.get(row.get("group")) or {}).get("unit")


def _cell_pair(columns, c, unit, fallback):
    """The pair a table cell belongs to ({id, end, scale, unit, label}), or None:
    both cells of a row are marked, and the page draws one value for the pair."""
    names = dict((x.name, x) for x in columns)
    if c.range_hi_name and c.range_hi_name in names and names[c.range_hi_name].kind in (NUMBER, INT):
        lo, hi, end = c, names[c.range_hi_name], u"lo"
    else:
        los = [x for x in columns if x.range_hi_name == c.name and c.kind in (NUMBER, INT)]
        if not los:
            return None
        lo, hi, end = los[0], c, u"hi"
    return {"id": lo.name, "end": end, "scale": scale_text(lo) or scale_text(hi),
            "unit": unit or lo.unit or hi.unit or u"", "label": _pair_name(lo, fallback)}


def render_table(table, stored, env=None):
    table = _bound(table, stored)
    groups, rows = _rows(table, stored, env)
    info_labels = [label for _i, label in getattr(table, "info", [])]
    # what an empty cell of a column resolves to (a choice: its option's words)
    resolved_by_col = dict((c.name, _resolved_words(c, stored, env)) for c in table.columns)
    by_group = dict((g["key"], dict(g, rows=[], set=0, info_labels=info_labels))
                    for g in groups)
    order = [g["key"] for g in groups]
    for r in rows:
        vals = _cells(table, stored, r["key"])
        cells = []
        for c in table.columns:
            v = vals[c.name]
            choices = _choices(c, stored, env)
            if c.kind == CHOICE and v not in (None, u"", "") and v not in [x[0] for x in choices]:
                choices.append((v, u"%s (stored value)" % v))
            widget, opts_json = (_options(c, stored, env, (r.get("widgets") or {}).get(c.path[0]))
                                 if c.kind == TEXT else (None, u""))
            if c.kind == CHOICE and c.widget in (u"seg", "seg"):
                widget = u"seg"           # a choice drawn as a segmented control
            cells.append({"name": cell_name(table, r["key"], c), "kind": c.kind, "words": list(c.words),
                          "resolves": c.resolved is not None, "resolved": resolved_by_col[c.name],
                          "label": c.label, "min": c.minimum, "max": c.maximum,
                          "step": step_text(c), "widget": widget, "options_json": opts_json,
                          "pair": _cell_pair(table.columns, c, g_unit(by_group, r), table.title),
                          # a row may say what blank means for it (e.g. a derived RL)
                          "placeholder": (r.get("placeholders") or {}).get(c.path[0], c.placeholder),
                          "inherited": c.placeholder == INHERITED,
                          "default": (r.get("defaults") or {}).get(c.path[0]),
                          "choices": choices,
                          "value": u"" if v is None else _shown(v, c.decimals),
                          "checked": bool(v) if c.kind == BOOL else False,
                          "align": c.align,
                          "counts_as": change_kind(cell_name(table, r["key"], c))})
        g = by_group.get(r.get("group"))
        if g is None:
            continue
        # a row's note is a coral chip when it says what is wrong (warn), a
        # grey one when it states a status (tag)
        g["rows"].append({"label": r.get("label"), "sublabel": r.get("sublabel"),
                          "note": r.get("note"), "warn": r.get("warn"), "tag": r.get("tag"),
                          "cells": cells,
                          "info": [(r.get("info") or {}).get(i) or []
                                   for i, _l in getattr(table, "info", [])]})
        if any(vals[c.name] not in (None, u"", "") for c in table.columns):
            g["set"] += 1
    out = []
    for i, key in enumerate(order):
        g = by_group[key]
        g["index"] = i
        g["total"] = len(g["rows"])
        g["row_heading"] = table.row_heading
        # a pair is one column named for the pair: its upper end's heading is
        # hidden; a pair end's unit is in its value, so its heading has none
        g["columns"] = [_column_head(table.columns, c, g.get("unit"), table.title) for c in table.columns]
        g["helps"] = column_helps(table.columns)
        out.append(g)
    return out


def _resolved_words(c, stored, env=None):
    """resolved_text, and for a choice the words of the option it names."""
    text = resolved_text(c, stored, env)
    if text and c.kind == CHOICE:
        return dict(_choices(c, stored, env)).get(text, text)
    return text


def _column_head(columns, c, unit, fallback):
    pair = _cell_pair(columns, c, None, fallback)
    end = pair["end"] if pair else None
    return {"label": pair["label"] if end == u"lo" else c.label, "unit": unit or c.unit,
            "align": c.align, "pair": pair is not None, "pair_end": end}


def column_helps(columns):
    """A table's or collection's column help, one line each under it
    ("Highest standard \u00b7 Blank: no cap."): what a blank cell means."""
    return [u"%s \u00b7 %s" % (c.range_label or c.label, c.help) for c in columns if c.help]


def parse_table(table, form, stored, env=None):
    """(updates {row key: {column path: value}}, errors) for the listed rows."""
    table = _bound(table, stored)
    _groups, rows = _rows(table, stored, env)
    updates, errors = {}, []
    for r in rows:
        saved = _cells(table, stored, r["key"])
        vals, ok = {}, True
        for c in table.columns:
            value, error = _value(c, form.get(cell_name(table, r["key"], c)),
                                  saved[c.name], u"%s %s" % (r.get("label"), c.label),
                                  choices=_choices(c, stored, env))
            default = (r.get("defaults") or {}).get(c.path[0])
            if (not error and default is not None and saved[c.name] in (None, u"", "")
                    and _text(value) == _text(default)):
                value = None            # the default drawn selected, posted back: still unset
            if error:
                errors.append(error)
                ok = False
            elif value is not _SKIP:
                vals[c.path] = value
        if ok and table.check is not None:
            error = table.check(r, dict((c.name, vals.get(c.path)) for c in table.columns))
            if error:
                errors.append(error)
        updates[tuple(r["key"])] = vals
    return updates, errors


def apply_table(table, stored, updates, env=None):
    table = _bound(table, stored)
    if table.write is not None:
        return table.write(copy.deepcopy(stored or {}), updates, env)
    value = copy.deepcopy(stored or {})
    existed = _get(value, table.base) is not None
    for row_key, vals in updates.items():
        path = table.base + tuple(row_key)
        parent = value
        for p in path[:-1]:
            parent = parent.setdefault(p, {})
        node = dict(parent.get(path[-1]) or {})
        for cpath, new in vals.items():
            leaf = node
            for p in cpath[:-1]:
                leaf = leaf.setdefault(p, {})
            if new is REMOVE:
                leaf.pop(cpath[-1], None)
            elif new is None and cpath[-1] not in leaf:
                continue                # an unset value never creates a key (as apply)
            else:
                leaf[cpath[-1]] = new
        if all(_get(node, c.path) in (None, u"") for c in table.columns):
            for c in table.columns:            # nothing set: no row at all
                node.pop(c.path[0], None)
        if node:
            parent[path[-1]] = node
        else:
            parent.pop(path[-1], None)
    _prune(value, table.base, keep_base=existed)
    return value


def _prune(value, base, keep_base=False):
    """Drop dicts left empty under base (a matrix with no limits), and base
    itself only if this save created it -- an untouched page changes nothing,
    not even an empty map into a missing one."""
    def walk(node):
        if not isinstance(node, dict):
            return
        for k in list(node):
            walk(node[k])
            if isinstance(node[k], dict) and not node[k]:
                node.pop(k)
    top = _get(value, base[:-1]) if len(base) > 1 else value
    if isinstance(top, dict) and base[-1] in top:
        walk(top[base[-1]])
        if isinstance(top[base[-1]], dict) and not top[base[-1]] and not keep_base:
            top.pop(base[-1])


# ── collections: rows the user adds, renames and removes ─────────────────────
#
# A Collection is a list of items edited as rows -- e.g. a method's matrices,
# where one row's settings live under several stored keys. It is declared
# with columns (Fields, one-segment paths; the first is the row's NAME) and
# two functions that map rows onto the stored value and back:
#
#     read(stored)        -> [{column name: value}]   in display order
#     write(stored, rows) -> stored                   (given a deep copy)
#     check(stored, rows) -> [error]                  optional: e.g. what a
#                                                     removal or rename orphans
#
# The page draws every existing row and a "+ Add <noun>" button, no spare
# blank rows. The button clones a template row whose
# index is NEW_INDEX, numbered from len(rows) upward in the browser; the parse
# reads every index the form carries. Clearing a row's name removes it. Rows
# are addressed by POSITION, which is safe because the stamp is the whole
# read() list: if anyone changed the collection after the page was drawn, the
# save is stale.

NEW_INDEX = u"NEW"   # alphanumeric: the page swaps "__NEW__" for "__<n>__"
# a parsed row's stored key before this save (a renamed row's old name), for a
# collection that asks for it (carry_stored_key); never written
STORED_KEY = u"_stored_key"


# what an empty collection says when it declares nothing of its own
EMPTY_COLLECTION = u"Nothing here yet. Add the first row."


class Collection(object):

    def __init__(self, id, title, columns, read, write, check=None,
                 noun=u"row", intro=u"", allow_empty=False, keep_keys=False, carry_stored_key=False,
                 empty=EMPTY_COLLECTION):
        self.id = id
        # the one muted line an empty collection shows under its header,
        # saying what would fill it (the default only says it is empty)
        self.empty = empty or EMPTY_COLLECTION
        # True: each parsed row of a stored one names its stored key
        # (STORED_KEY), so a check can tell a renamed row from a new one
        self.carry_stored_key = carry_stored_key
        # True: a stored row keeps its stored key whatever is posted; the
        # form adds rows but never renames or removes one (that is an
        # action of its own, which can refuse)
        self.keep_keys = keep_keys
        self.title = title
        self.columns = columns
        self.read = read
        self.write = write
        self.check = check
        self.noun = noun
        self.intro = intro
        self.allow_empty = allow_empty    # False: removing every row is refused

    def fields(self):
        # per-profile columns (one per matrix) listed for an empty profile
        return list(self.columns({}) if callable(self.columns) else self.columns)

    @property
    def key(self):
        return self.fields()[0]


def collection_name(coll, index, column):
    return u"__".join([u"c", _enc(coll.id), u"%s" % index] + [_enc(p) for p in column.path])


def _new_indices(coll, form, start):
    """Indices >= start that any field of the form names (rows added with
    "+ Add" -- a row with values but no name must still be seen, and
    refused), in order."""
    head = u"c__%s__" % _enc(coll.id)
    found = set()
    for k in (form or {}).keys():
        k = k.decode("utf-8") if isinstance(k, bytes) else u"%s" % k
        if k.startswith(head):
            mid = k[len(head):].partition(u"__")[0]
            if mid.isdigit() and int(mid) >= start:
                found.add(int(mid))
    return sorted(found)


def render_collection(coll, stored, env=None):
    coll = _bound(coll, stored)
    rows = coll.read(stored or {})
    out = []
    for i in list(range(len(rows))) + [NEW_INDEX]:
        vals = rows[i] if i != NEW_INDEX else {}
        cells = []
        for c in coll.columns:
            v = vals.get(c.path[0])
            choices = _choices(c, stored, env)
            if c.kind == CHOICE and v not in (None, u"", "") and v not in [x[0] for x in choices]:
                choices.append((v, u"%s (stored value)" % v))
            widget, opts_json = _options(c, stored, env) if c.kind == TEXT else (None, u"")
            show = None
            if is_picker(c):
                widget, opts_json = PICKER, _offered_json(choices, v)
                v = _multi_json(v)
                if c.show_if_column:
                    by = [x for x in coll.columns if x.path[0] == c.show_if_column[0]][0]
                    show = (collection_name(coll, i, by), c.show_if_column[1])
            cells.append({"name": collection_name(coll, i, c), "kind": c.kind,
                          "noun": c.noun, "show_if": show,
                          "label": c.label, "unit": c.unit or u"", "min": c.minimum, "max": c.maximum,
                          "step": step_text(c), "widget": widget, "options_json": opts_json,
                          "pair": _cell_pair(coll.columns, c, None, coll.title),
                          "placeholder": c.placeholder if i != NEW_INDEX or c is coll.key
                                         else u"",
                          "choices": choices,
                          "value": u"" if v is None else _shown(v, c.decimals),
                          "checked": bool(v) if c.kind == BOOL else False,
                          "align": c.align,
                          "counts_as": change_kind(collection_name(coll, i, c))})
        out.append({"index": i, "new": i == NEW_INDEX, "template": i == NEW_INDEX,
                    "noun": coll.noun, "next": len(rows), "cells": cells, "empty": coll.empty,
                    "id": coll.id})
    out[-1]["pickers"] = collection_pickers(out)    # the template entry carries the search pickers
    out[-1]["helps"] = column_helps(coll.columns)
    return out


def parse_collection(coll, form, stored, env=None):
    """(rows [{column: value}], errors) -- the collection as submitted."""
    coll = _bound(coll, stored)
    before = coll.read(stored or {})
    rows, errors, seen = [], [], set()
    added = _new_indices(coll, form, len(before))
    for i in list(range(len(before))) + added:
        old = before[i] if i < len(before) else {}
        if coll.keep_keys and i < len(before):
            name, error = old.get(coll.key.path[0]), None
        else:
            name, error = _value(coll.key, form.get(collection_name(coll, i, coll.key)),
                                 old.get(coll.key.path[0]),
                                 choices=_choices(coll.key, stored, env))
        if name in (None, u"", REMOVE, _SKIP):
            if error:
                errors.append(error)
            elif i >= len(before):
                filled = [c.label for c in coll.columns[1:] if c.kind != BOOL and
                          _text(form.get(collection_name(coll, i, c)))]
                if filled:
                    errors.append(u"New %s %d: give it a name, or clear %s." % (
                        coll.noun, added.index(i) + 1, u", ".join(filled)))
            continue                    # cleared name: removed (or an unused blank row)
        label = name
        if name.lower() in seen:
            errors.append(u"%s is listed twice." % name)
            continue
        seen.add(name.lower())
        row = {coll.key.path[0]: name}
        if coll.carry_stored_key and i < len(before):
            row[STORED_KEY] = old.get(coll.key.path[0])
        for c in coll.columns[1:]:
            if is_picker(c):
                raw = form.get(collection_name(coll, i, c))
                if raw is None:                 # not drawn: as stored
                    row[c.path[0]] = list(old.get(c.path[0]) or [])
                    continue
                value, error = _picked(c, raw, old.get(c.path[0]), u"%s: %s" % (label, c.label),
                                       _choices(c, stored, env))
                if error:
                    errors.append(error)
                else:
                    row[c.path[0]] = value
                continue
            value, error = _value(c, form.get(collection_name(coll, i, c)),
                                  old.get(c.path[0]), u"%s: %s" % (label, c.label),
                                  choices=_choices(c, stored, env))
            if error:
                errors.append(error)
            elif value is not _SKIP:
                row[c.path[0]] = None if value is REMOVE else value
        rows.append(row)
    if not errors and not rows and not coll.allow_empty:
        errors.append(u"At least one %s is needed; nothing was removed." % coll.noun)
    if not errors and coll.check is not None:
        errors.extend(coll.check(stored or {}, rows) or [])
    return rows, errors


def collection_pickers(rows):
    """What a collection's search pickers draw, from its rendered rows
    (render_collection), or None when it has none: one list per stored row,
    named after the row ("<row> <column>"), hidden while the row's show_if
    column does not hold its value. The page keeps them with the rows: a
    row added (even to a collection with none yet), renamed or rescoped
    redraws its list (pfas-components.js, .pfas-picker-lists)."""
    rows = list(rows or [])
    if not rows:
        return None
    picks = [j for j, c in enumerate(rows[-1]["cells"]) if c.get("widget") == PICKER]
    if not picks:
        return None
    j = picks[0]
    first = rows[-1]["cells"][j]                       # the + Add template row's: always drawn
    prefix, column = first["name"].rsplit(u"__", 2)[0] + u"__", first["name"].rsplit(u"__", 1)[1]
    show = first["show_if"]
    out = {"prefix": prefix, "column": column, "label": first["label"].lower(), "noun": first["noun"],
           "options_json": first["options_json"],
           "key": rows[-1]["cells"][0]["name"].rsplit(u"__", 1)[1],
           "show": show[0].rsplit(u"__", 1)[1] if show else u"", "show_value": show[1] if show else u"",
           "rows": []}
    for r in rows:
        if r["template"]:
            continue
        cell = r["cells"][j]
        name = r["cells"][0]["value"]
        shown = cell["show_if"] is None or dict((c["name"], c["value"]) for c in r["cells"]).get(
            cell["show_if"][0]) == cell["show_if"][1]
        out["rows"].append({"name": cell["name"], "title": name, "label": u"%s %s" % (name, out["label"]),
                            "value": cell["value"], "options_json": cell["options_json"],
                            "hidden": not shown})
    return out
