# -*- coding: utf-8 -*-
"""Three method profile tabs drawn as the house list + card (.pfas-hier):
the Matrices tab's Correction group, Run & reporting, and Engine.

Each list is read from the inputs its tab's Table view posts and posts
nothing itself:
  - a tile names the inputs it reads (data-set-names) and the page draws it
    again from them on every change;
  - a choice drawn as a segment is a nameless .pfas-seg[data-field] writing
    the real input by its id (data-input), as config_form_macros draws one;
  - a switch is a nameless box writing the real one by name and form
    (data-switch-for, data-switch-form); it names no form of its own
    (form="pfas-no-form"), so it is never posted nor counted as a change;
  - a tile opens the shared centred window on nameless copies of its
    card's inputs (or its block's), through the card's Edit trigger
    (profile_grids.card_act); a node's actions are the shared row menu.
A per-worksheet count of a QC type whose rule row is Off is greyed
(data-mute-if), never hidden, and stays editable.

Pure; no Zope imports. Python 2.7 compatible.
"""
from __future__ import absolute_import, unicode_literals

import json
import re

from senaite.pfas import help_dictionary
from senaite.pfas import profile_grids as pg

_tag, _esc, _text, _cls, _tile = pg._tag, pg._esc, pg._text, pg._cls, pg._tile

MATRICES_FORM = "section-matrices"
RUN_FORM = "section-run"
ENGINE_FORM = "section-engine"
NO_FORM = "pfas-no-form"

NOT_SET = pg.NOT_SET_WORDS
DEFAULT_NOTE = "Default"
NONE_WORDS = "None"

# the short words a segment drawn on a card reads (the board's), by field
SHORT_CHOICES = {
    "f__sample_correction": [("instrument", "MS software"), ("lims", "LIMS")],
    "f__fold_rule": [("", "Always"), ("added", "Standard added")],
    "f__blank_role_name": [("", "First run"), ("MB", "MB"), ("LRB", "LRB")],
}
# a choice of two values the board draws as the house switch, acting at
# once: (the value it posts on, off, its word on, off)
SWITCH_CHOICES = {"f__Dup__duplicate_all_samples": ("yes", "", "Yes", "No")}
# what each segment's words mean, one line under it
SHORT_HELP = {
    "f__sample_correction": "MS software: results arrive per sample, no factor applied. "
                            "LIMS: final volume / sample amount, back-calculated per sample.",
    "f__blank_role_name": "First run: the first of MB and LRB this method runs.",
}


# ── shared pieces ───────────────────────────────────────────────────────────

def _span(cls, text, attrs=()):
    return _tag("span", [("class", cls)] + list(attrs), _esc(text))


def count_words(n, total):
    """"Not set" while nothing is set, else "n of m set"."""
    return NOT_SET if not n else "{0} of {1} set".format(n, total)


def _is_set(f):
    """Whether a drawn field (config_forms.render) holds a value: a switch
    ticked, a list with an option ticked, else a value typed or chosen."""
    if f["kind"] == "bool":
        return bool(f.get("checked"))
    if f["kind"] == "multi":
        return any(o.get("checked") for o in f.get("options") or ())
    return bool(_text(f.get("value")).strip())


def _count_names(f):
    """What the page counts a field by: its input's name, or a list's
    option names (set while any is ticked)."""
    if f["kind"] == "multi":
        return [o["name"] for o in f.get("options") or ()]
    return f["name"]


def _count_attrs(fields):
    """The node value's attributes: the inputs it counts (data-set-count)."""
    return [("data-set-count", json.dumps([_count_names(f) for f in fields]))]


def _node(key, title, value="", sub="", first=False, menu=None, attrs=(), value_attrs=()):
    """One row of the list: a button showing its card, its value and its
    line under; its row menu (and the touch screen's dots) when it has one."""
    node = _tag("button", [("type", "button"), ("class", _cls("pfas-hier-node", "is-selected" if first else None)),
                           ("data-hier-target", key), ("aria-pressed", "true" if first else "false"),
                           ("data-card-node", key), ("data-row-actions", menu)] + list(attrs),
                _span("pfas-hier-node-t", title) +
                _span("pfas-hier-node-v", value, [("data-set-value", True)] + list(value_attrs)) +
                (_span("pfas-hier-node-s", sub, [("data-set-sub", True)]) if sub else ""))
    return node + (pg._dots(title, [("data-card-node", key)]) if menu else "")


def _group_node(key, title, lines, first=False):
    """A group's one node, as QC criteria draws its Calibration group: the
    group's name, then a line per section with what it holds."""
    body = "".join(_tag("span", [("class", "pfas-hier-rule")],
                        _span("pfas-hier-rule-l", label) +
                        _span("pfas-hier-node-v", value, [("data-set-value", True)] + list(attrs)))
                   for label, value, attrs in lines)
    return _tag("button", [("type", "button"), ("class", _cls("pfas-hier-node", "is-group",
                                                              "is-selected" if first else None)),
                           ("data-hier-target", key), ("aria-pressed", "true" if first else "false"),
                           ("data-card-node", key)],
                _span("pfas-hier-node-t", title) + body)


def _card(key, title, caption, body, acts="", shown=False, attrs=(), triggers="", help_sec=None):
    """A card: its tiles, its triggers (`triggers`, a tile opening the
    one keyed edit) and its one button row, last (`acts`: + Add). A card
    that is one section (`help_sec`) ends its title row in that section's
    help ?, at the right."""
    opens = pg.tile_opens("edit") if 'data-act="edit"' in triggers else []
    h4 = _tag("h4", [("class", "pfas-hier-card-t")], _esc(title))
    if help_sec:
        h4 = _tag("div", [("class", "pfas-hier-card-head has-help")],
                  h4 + help_dictionary.help_button(help_dictionary.SECTION_HELP[help_sec]))
    return _tag("section", [("class", "pfas-hier-card"), ("data-hier-card", key), ("data-card", key),
                            ("aria-label", title), ("hidden", None if shown else True)] + opens + list(attrs),
                h4 +
                (_tag("p", [("class", "pfas-hier-card-cap"), ("data-set-cap", True)], _esc(caption)) if caption else "") +
                body + pg.card_acts(triggers) + pg.actions_row(acts))


def _head(text, help_sec=None):
    """A heading inside a card; a section's own heading (`help_sec`) ends
    in that section's help ?, at the right."""
    h5 = _tag("h5", [("class", "pfas-hier-h")], _esc(text))
    if not help_sec:
        return h5
    return _tag("div", [("class", "pfas-hier-hrow has-help")],
                h5 + help_dictionary.help_button(help_dictionary.SECTION_HELP[help_sec]))


def _edit_button(words, scope=None):
    """Edit, as the card's trigger (keyed edit, or the block's name): the
    shared window on nameless copies of the card's inputs, or of one
    block's (data-set-edit names the block)."""
    return pg.card_act(scope or "edit", words, [("data-set-edit", scope or True)])


def _setting(label, f):
    """A drawn field as its tile reads it (profile_grids._setting), a list
    of switches too: the ticked options' words, else None."""
    if f["kind"] == "multi":
        opts = f.get("options") or []
        on = [_text(o["label"]) for o in opts if o.get("checked")]
        return {"label": label, "kind": "multi", "names": [o["name"] for o in opts],
                "labels": [_text(o["label"]) for o in opts], "choices": None, "ends": None, "note": "",
                "unit": "", "words": ", ".join(on) or NONE_WORDS}
    return pg._setting(label, f)


def _value_tile(f, form, label=None, attrs=(), cls=None):
    """A field as its tile: a blank that resolves to a number reads that
    number, noted Default (data-set-blank, data-set-blank-note)."""
    s = _setting(label or f["label"], f)
    resolved = _text(f.get("resolved"))
    extra = list(attrs)
    if resolved and f["kind"] not in ("bool", "multi", "choice"):
        extra += [("data-set-blank", resolved), ("data-set-blank-note", DEFAULT_NOTE)]
        if not _text(f.get("value")).strip():
            s["words"], s["note"] = resolved, DEFAULT_NOTE
    return pg._setting_tile(s, form=form, attrs=extra, cls=cls)


def _seg_tile(f, form, attrs=(), cls=None):
    """A choice the board draws as a segment: a nameless segment writing the
    field's own input (its id is its name, config_form_macros), the short
    words, the line saying what each means; nothing pressed while blank."""
    value = _text(f.get("value"))
    items = "".join(_tag("button", [("type", "button"), ("class", "pfas-seg-item"), ("data-value", v),
                                    ("aria-pressed", "true" if v == value else "false")], _esc(w))
                    for v, w in SHORT_CHOICES[f["name"]])
    seg = _tag("div", [("class", "pfas-seg pfas-seg-sm is-fit"), ("role", "group"), ("data-field", True),
                       ("data-quiet", True), ("data-input", f["name"]), ("aria-label", f["label"])], items)
    note = SHORT_HELP.get(f["name"]) or ""
    s = _setting(f["label"], f)
    attrs = [("class", _cls("pfas-hier-tile", "pfas-hier-amount", cls)), ("data-set-names", json.dumps(s["names"])),
             ("data-set-form", form), ("data-set-kind", "choice"), ("data-set-labels", json.dumps(s["labels"])),
             ("data-set-control", True)] + list(attrs)
    return _tag("div", attrs, _span("pfas-hier-tile-l", f["label"]) + seg +
                (_span("pfas-hier-tile-s", note) if note else ""))


def _choice_switch_tile(f, form, attrs=(), cls=None):
    """A choice of two values as the house switch, writing the field's own
    input (its id is its name) at once; the tile names it for Edit."""
    on, off, word_on, word_off = SWITCH_CHOICES[f["name"]]
    s = _setting(f["label"], f)
    attrs = [("class", _cls("pfas-hier-tile", "pfas-hier-amount", "pfas-hier-switches", cls)),
             ("data-set-names", json.dumps(s["names"])), ("data-set-form", form), ("data-set-kind", "choice"),
             ("data-set-labels", json.dumps(s["labels"])), ("data-set-control", True)] + list(attrs)
    return _tag("div", attrs, _span("pfas-hier-tile-l", f["label"]) +
                pg.value_switch(f["name"], f.get("value"), on, off, f["label"], word_on, word_off))


def _switch(name, form, label, checked):
    """A nameless switch writing the box `name` of `form` at once."""
    box = _tag("input", [("type", "checkbox"), ("form", NO_FORM), ("data-switch-for", name),
                         ("data-switch-form", form), ("checked", True if checked else None)])
    return _tag("label", [("class", "pfas-switch pfas-hier-switch")],
                box + _tag("span", [("class", "pfas-switch-track")], "") + _tag("span", [], _esc(label)))


def _switch_tile(f, form, attrs=(), cls=None):
    """A switch, or a list of switches, the board draws on the card: each
    writes its real box; the tile names them for Edit."""
    s = _setting(f["label"], f)
    if f["kind"] == "multi":
        boxes = "".join(_switch(o["name"], form, o["label"], o.get("checked")) for o in f.get("options") or ())
    else:
        boxes = _switch(f["name"], form, f["label"], f.get("checked"))
    attrs = [("class", _cls("pfas-hier-tile", "pfas-hier-amount", "pfas-hier-switches", cls)),
             ("data-set-names", json.dumps(s["names"])), ("data-set-form", form), ("data-set-kind", s["kind"]),
             ("data-set-labels", json.dumps(s["labels"])), ("data-set-control", True)] + list(attrs)
    label = _span("pfas-hier-tile-l", f["label"]) if f["kind"] == "multi" else ""
    return _tag("div", attrs, label + boxes)


def _field_tile(f, form, attrs=(), cls=None):
    """A section field on a card as the board draws it: a switch for a
    switch or a list, a segment for a choice it gives short words, else its
    tile."""
    if f["kind"] in ("bool", "multi"):
        return _switch_tile(f, form, attrs, cls)
    if f["kind"] == "choice" and f["name"] in SWITCH_CHOICES:
        return _choice_switch_tile(f, form, attrs, cls)
    if f["kind"] == "choice" and f["name"] in SHORT_CHOICES:
        return _seg_tile(f, form, attrs, cls)
    return _value_tile(f, form, attrs=attrs, cls=cls)


def _fields(groups):
    return [f for g in groups for f in g.get("shown") or ()]


def _list(list_id, kind, label, nodes, cards, attrs=()):
    return _tag("div", [("id", list_id), ("class", "pfas-hier"), ("data-hier", kind), ("data-set-list", True)]
                + list(attrs),
                _tag("div", [("class", "pfas-hier-list"), ("role", "group"), ("aria-label", label)], "".join(nodes)) +
                _tag("div", [("class", "pfas-hier-cards")], "".join(cards)))


def _mark_first(nodes, cards):
    """The first card's node chosen and its card shown, as a page with no
    script draws it (the list remembers another once one is chosen)."""
    for i, n in enumerate(nodes):
        m = re.search(r'data-hier-target="([^"]+)" aria-pressed="false"', n)
        if not m:
            continue
        key = m.group(1)
        nodes[i] = n.replace('class="pfas-hier-node', 'class="pfas-hier-node is-selected', 1).replace(
            m.group(0), 'data-hier-target="{0}" aria-pressed="true"'.format(key), 1)
        for j, c in enumerate(cards):
            mark = 'data-hier-card="{0}"'.format(key)
            if mark in c:
                cards[j] = c.replace(' hidden="hidden"', "", 1)
        return


def _group(title, help_id=None):
    """A group's heading; with `help_id`, its one help ? at the right end."""
    return pg.group_head(title, help_id)


def _groups_of(profile, env, groups_of):
    if groups_of is not None:
        return groups_of
    cf, mps, _pf, _iso, _ls = pg._tab_modules()

    def drawn(sid):
        sec = mps.SECTIONS[sid]
        out = cf.render(sec, profile, env or {})
        return out if isinstance(sec, cf.Collection) else pg.fold_groups(sid, out, profile)
    return drawn


def _edit_menu():
    from senaite.pfas import row_menu
    return row_menu.actions(("Edit", "event", "set-edit"))


# ── Matrices: the Correction group ─────────────────────────────────────────

CORRECTION_GROUP = "Correction"
MATRICES_GROUP = "Matrices"
BASIS_KEY, BLANK_KEY = "corr-basis", "corr-blank"
BASIS_TITLE, BLANK_TITLE = "Sample basis", "Method blank"
SUBTRACTED = "Subtracted"
NOT_SUBTRACTED = "Not subtracted"
ONE_OPTION = "The one option: {0}"


def correction_parts(profile, env=None, groups_of=None):
    """(nodes, cards) of the Matrices list's Correction group: Sample basis
    (Per-sample correction as a segment, Spike levels are entered as a tile,
    Edit) and Method blank (its switch, acting at once: no Edit), read from
    section scorr as the Table view draws it."""
    groups = _groups_of(profile or {}, env, groups_of)("scorr")
    fields = dict((f["name"], f) for f in _fields(groups))
    basis = [fields[n] for n in ("f__sample_correction", "f__spike_basis") if n in fields]
    blank = fields.get("f__blank_subtraction")
    nodes, cards = [_group(CORRECTION_GROUP, help_dictionary.SECTION_HELP["scorr"])], []
    if basis:
        cap = next((g["title"] for g in groups if any(f in basis for f in g.get("shown") or ())), "")
        tiles = []
        for f in basis:
            if f["kind"] == "choice" and f["name"] in SHORT_CHOICES:
                tiles.append(_seg_tile(f, MATRICES_FORM))
            else:
                choices = f.get("choices") or ()
                only = _text(choices[0][1]).replace(": ", ", ", 1) if len(choices) == 1 else ""
                note = ONE_OPTION.format(only[:1].lower() + only[1:]) if only else ""
                s = _setting(f["label"], f)
                s["note"] = note
                tiles.append(pg._setting_tile(s, form=MATRICES_FORM))
        n = len([f for f in basis if _is_set(f)])
        nodes.append(_node(BASIS_KEY, BASIS_TITLE, count_words(n, len(basis)), menu=_edit_menu(),
                           value_attrs=_count_attrs(basis)))
        cards.append(_card(BASIS_KEY, BASIS_TITLE, cap,
                           _tag("div", [("class", "pfas-hier-tiles")], "".join(tiles)),
                           triggers=_edit_button("Edit"), attrs=[("data-card-sec", "scorr")]))
    if blank is not None:
        on = bool(blank.get("checked"))
        words = json.dumps({"name": blank["name"], "on": SUBTRACTED, "off": NOT_SUBTRACTED})
        nodes.append(_node(BLANK_KEY, BLANK_TITLE, SUBTRACTED if on else NOT_SUBTRACTED,
                           value_attrs=[("data-set-bool", words)]))
        cards.append(_card(BLANK_KEY, BLANK_TITLE, blank.get("help") or "",
                           _tag("div", [("class", "pfas-hier-tiles")], _switch_tile(blank, MATRICES_FORM))))
    return nodes, cards


# ── Run & reporting ─────────────────────────────────────────────────────────

RUN_LIST_ID = "run-list"
RUN_GROUPS = ("Run", "Extraction", "Channels", "Reporting")
TPL_KEY, QCC_KEY, STAGES_KEY, DIL_KEY = "run-template", "run-qc-comp", "run-stages", "run-dilutions"
COLL_KEYS = {"lbl": "run-labels", "solv": "run-lc", "solv_spe": "run-spe"}
COLL_TITLES = {"lbl": "Extraction labels", "solv": "LC channels", "solv_spe": "SPE channels"}
TPL_TITLE = "Run template"
TPL_CAP = "One run sequence; the Run Builder builds every run of this method from it"
SEQ_HEAD = "Sequence"
SEQ_NOTE = "Drag to reorder"
SAMPLES_TITLE = "Samples"
SAMPLES_SUB = "Every sample of the run"
ADD_STEP_WORDS = "+ Add step"
BRACKET_LABEL = "Bracketing check"
CCV_LABEL = "A CCV is inserted every"
CCV_NOTE = "The CCV frequency on QC criteria"
QCC_TITLE = "QC composition"
STAGES_TITLE = "Extraction stages"
STAGES_CAP = "Each worksheet's guided extraction follows them"
ADD_STAGE_WORDS = "+ Add stage"
STAGE_CAPTURE_WORDS = {"amount": "Sample amount", "final_volume": "Final extract volume", "spe_port": "SPE port"}
STAGE_NOTHING = "Nothing"
DIL_TITLE = "Dilutions"
DIL_CAP = "How an over-range sample may be diluted; a project can override these"
REPORTING = (("intg", "Integration"), ("rf", "Certificate format"), ("al", "Action levels & MCLs"))
AS_BUILT = "As built"
QCC_CODES = {"f__LFSM__frequency": "LFSM", "f__Dup__duplicate_all_samples": "Dup"}


def _plural(noun):
    return pg.counted(2, noun).split(" ", 1)[1]


def rows_words(n, noun):
    """"No channels" while there is none, else "2 channels"."""
    return "No {0}".format(_plural(noun)) if not n else pg.counted(n, noun)


def step_type(c):
    """The sample type a run template step's icon draws: the samples step's
    is a Sample, every other its code."""
    return "Sample" if c.get("kind") == "samples" else _text(c.get("code"))


def _type_icon(code):
    """A type's icon beside words that say it (aria-hidden)."""
    from senaite.pfas import sample_type_icons as sti
    return sti.svg(code, hidden=True)


def _typed_label(tile, code):
    """A tile with its type's icon before its label: the label stays words
    alone (the windows read it), the icon beside it."""
    icon = _type_icon(code)
    m = re.search(r'<span class="pfas-hier-tile-l">.*?</span>', tile)
    if not icon or not m:
        return tile
    return tile[:m.start()] + _tag("span", [("class", "pfas-type-cell")], icon + m.group(0)) + tile[m.end():]


def _step_mini(c, i, steps=1):
    """One step of the run template as a mini-card: its place and name, its
    code and how many injections; it opens its step's window, and its menu
    is Edit step, Move up, Move down and Remove step while it may go
    (`steps`: how many steps)."""
    from senaite.pfas import row_menu
    samples = c.get("kind") == "samples"
    title = "{0} · {1}".format(i + 1, SAMPLES_TITLE if samples else _text(c.get("label")))
    n = c.get("injections") or 0
    sub = SAMPLES_SUB if samples else "{0} · {1}".format(_text(c.get("code")), pg.counted(n, "injection"))
    menu = row_menu.actions(("Edit step", "event", "seq-edit"),
                            ("Move up", "event", "seq-up") if i > 0 else None,
                            ("Move down", "event", "seq-down") if i < steps - 1 else None,
                            ("Remove step", "event", "seq-remove", {"danger": True}) if c.get("removable") else None)
    return _tag("div", [("class", "pfas-hier-mini"), ("tabindex", "0"), ("data-seq-mini", i),
                        ("data-seq-code", _text(c.get("code"))), ("data-row-actions", menu)],
                _tag("span", [("class", "pfas-hier-mini-t")], _tag("span", [("class", "grip"), ("aria-hidden", "true")], "") +
                     _type_icon(step_type(c)) + _esc(title)) +
                _span("pfas-hier-mini-s", sub))


def _injections(n):
    """"6 injections", or Not set when the CCV frequency is not a count."""
    try:
        return pg.counted(int(float(_text(n))), "injection")
    except ValueError:
        return NOT_SET


def _template_entry(rte):
    tpl = (rte or {}).get("tpl") or {}
    seq = tpl.get("sequence_labelled") or []
    minis = "".join(_step_mini(c, i, len(seq)) for i, c in enumerate(seq))
    # read only here: each opens a window that reads it
    tiles = (_typed_label(_tile(BRACKET_LABEL, _text(tpl.get("bracket_qc") or "CCV"), attrs=pg.TILE_READ),
                          _text(tpl.get("bracket_qc") or "CCV")) +
             _tile(CCV_LABEL, _injections((rte or {}).get("ccv")), note=CCV_NOTE, attrs=pg.TILE_READ))
    body = (_head(SEQ_HEAD) + _tag("p", [("class", "pfas-hier-note")], _esc(SEQ_NOTE)) +
            _tag("div", [("class", "pfas-hier-minis"), ("data-seq-minis", True)], minis) +
            _tag("div", [("class", "pfas-hier-tiles")], tiles))
    value_attrs = [("data-set-rows", "#seq-chips .pfas-seqrow"), ("data-set-noun", "step")]
    node = _node(TPL_KEY, TPL_TITLE, pg.counted(len(seq), "step"), value_attrs=value_attrs)
    card = _card(TPL_KEY, TPL_TITLE, TPL_CAP, body, pg._list_button(ADD_STEP_WORDS, [("data-seq-add", True)]),
                 attrs=[("data-card-sec", "run_template")], help_sec="run_template")
    return node, card


def _stage_words(s):
    rec = STAGE_CAPTURE_WORDS.get(_text(s.get("captures_samples")), STAGE_NOTHING)
    parts = ["Records: " + rec]
    if s.get("creates_solution"):
        parts.append("creates solution")
    if s.get("capture_pedigree"):
        parts.append("pedigree")
    return " · ".join(parts)


def _order(s, i):
    """A stage's order as its table row reads it, else its place."""
    try:
        return int(_text(s.get("order")).strip()) or i + 1
    except ValueError:
        return i + 1


def stage_minis(profile):
    """The stages as mini-cards, in their order: "3 · Name" over what each
    records per sample and its two switches; each opens its stage's window."""
    stages = sorted([s for s in (profile or {}).get("extraction_stages") or [] if isinstance(s, dict)],
                    key=lambda s: s.get("order", 0))
    from senaite.pfas import row_menu
    menu = row_menu.actions(("Edit", "event", "stage-edit"))
    return "".join(_tag("div", [("class", "pfas-hier-mini"), ("tabindex", "0"), ("data-stage-mini", i),
                                ("data-row-actions", menu)],
                        _tag("span", [("class", "pfas-hier-mini-t")],
                             _tag("span", [("class", "grip"), ("aria-hidden", "true")], "") +
                             _esc("{0} · {1}".format(_order(s, i), _text(s.get("name"))))) +
                        _span("pfas-hier-mini-s", _stage_words(s)))
                   for i, s in enumerate(stages)), len(stages)


def _stages_entry(profile):
    minis, n = stage_minis(profile)
    body = (_tag("div", [("class", "pfas-hier-minis"), ("data-stage-minis", True)], minis) +
            _tag("p", [("class", "pfas-hier-empty"), ("data-stage-empty", True), ("hidden", True if n else None)],
                 "No stages yet."))
    node = _node(STAGES_KEY, STAGES_TITLE, pg.counted(n, "stage"),
                 value_attrs=[("data-set-rows", "#stage-list tr.mp-stage"), ("data-set-noun", "stage")])
    card = _card(STAGES_KEY, STAGES_TITLE, STAGES_CAP, body, pg._list_button(ADD_STAGE_WORDS, [("data-stage-add", True)]),
                 attrs=[("data-card-sec", "stages")], help_sec="stages")
    return node, card


def _coll_words(cell):
    v = _text(cell.get("value")).strip()
    if cell["kind"] == "choice" and v:
        return pg._label_of(cell.get("choices"), v)
    return v


def coll_minis(rows):
    """A collection's rows (config_forms.render, the template row last) as
    mini-cards: its first cell over the others' words; each opens its
    window. Rows with no first cell are not drawn: the save drops them."""
    from senaite.pfas import row_menu
    menu = row_menu.actions(("Edit", "event", "coll-edit"))
    out = []
    for at, r in enumerate([r for r in rows if not r.get("template")]):
        cells = r["cells"]
        head = _coll_words(cells[0]) if cells else ""
        if not head:
            continue
        sub = " · ".join("{0}: {1}".format(_text(c["label"]), _coll_words(c)) for c in cells[1:] if _coll_words(c))
        out.append(_tag("div", [("class", "pfas-hier-mini"), ("tabindex", "0"), ("data-coll-mini", at),
                                ("data-row-actions", menu)],
                        _span("pfas-hier-mini-t", head) + (_span("pfas-hier-mini-s", sub) if sub else "")))
    return out


def _coll_entry(sid, rows):
    tpl = rows[-1] if rows else {}
    noun = _text(tpl.get("noun") or "row")
    minis = coll_minis(rows)
    key, title = COLL_KEYS[sid], COLL_TITLES[sid]
    body = (_tag("div", [("class", "pfas-hier-minis"), ("data-coll-minis", True)], "".join(minis)) +
            _tag("p", [("class", "pfas-hier-empty"), ("data-coll-empty", True), ("hidden", True if minis else None)],
                 _esc(_text(tpl.get("empty")))))
    node = _node(key, title, rows_words(len(minis), noun),
                 value_attrs=[("data-set-coll", _text(tpl.get("id"))), ("data-set-noun", noun)])
    card = _card(key, title, "", body, pg._list_button("+ Add {0}".format(noun), [("data-coll-add", True)]),
                 attrs=[("data-coll", _text(tpl.get("id"))), ("data-card-sec", sid)], help_sec=sid)
    return node, card


def _qcc_tiles(profile, env, groups):
    """QC composition's tiles under its groups' headings; a QC type's count
    greyed while its rule row is Off (profile_grids.mute_attrs)."""
    out = []
    for g in groups:
        tiles = []
        for f in g.get("shown") or ():
            code = QCC_CODES.get(f["name"]) or (f["name"].split("__")[1] if f["name"].endswith("__per_batch") else None)
            mute = pg.mute_attrs(profile, env, code) if code else []
            cls = dict(mute).get("class")
            attrs = [a for a in mute if a[0] != "class"]
            tile = _field_tile(f, RUN_FORM, attrs=attrs, cls=cls)
            # a count per worksheet names its type: its icon before the label
            tiles.append(_typed_label(tile, code) if code and f["name"].endswith("__per_batch") else tile)
        title = _text(g.get("title"))
        out.append((_head(title) if title and title != QCC_TITLE else "") +
                   _tag("div", [("class", "pfas-hier-tiles")], "".join(tiles)))
    return "".join(out)


def _form_entry(key, title, cap, profile, env, groups, tiles_html=None, sec=None):
    fields = _fields(groups)
    n = len([f for f in fields if _is_set(f)])
    node = _node(key, title, count_words(n, len(fields)), menu=_edit_menu(), value_attrs=_count_attrs(fields))
    if tiles_html is None:
        tiles_html = "".join(_head(g["title"]) + _tag("div", [("class", "pfas-hier-tiles")],
                                                      "".join(_boxed_field(f, profile) for f in g.get("shown") or ()))
                             for g in groups if g.get("shown"))
    card = _card(key, title, cap, tiles_html, triggers=_edit_button("Edit"), attrs=[("data-card-sec", sec)],
                 help_sec=sec)
    return node, card


def _boxed_field(f, profile):
    """A field's tile on Run & reporting; one that is a limit box (the
    lowest EIS recovery in a diluted extract) with its placard."""
    from senaite.pfas import limit_placard
    tile = _field_tile(f, RUN_FORM)
    box = limit_placard.box_of_name(f["name"])
    return limit_placard.boxed(tile, profile, box) if box else tile


# what shapes a run, beside the run template and QC composition: the
# worksheet size, the run rules and the new calibration curve, each its
# section's group (method_profile_sections.EXTRACTION_BATCH, RUN_RULES)
WS_KEY, RUN_RULES_KEY, NEW_CURVE_KEY = "run-ws", "run-rules", "run-new-curve"
WS_TITLE, RUN_RULES_TITLE, NEW_CURVE_TITLE = "Worksheet size", "Run rules", "New calibration curve"
WS_CAP = "How many samples a worksheet may hold"
RUN_RULES_GROUP = "Run rules"
RUN_RULES_CAP = "How the CCVs bracket a run"
NEW_CURVE_CAP = "When a run carries a new curve, and what verifies a reused one"


def _tiles_of(groups, profile):
    return _tag("div", [("class", "pfas-hier-tiles")],
                "".join(_boxed_field(f, profile) for g in groups for f in g.get("shown") or ()))


def run_rule_entries(profile, env, drawn):
    """[(node, card)]: Worksheet size (its most per worksheet with its
    placard, whether the QC samples count), Run rules and New calibration
    curve, each a node with how much of it is set and a card whose tiles
    open its window (Edit); Run & reporting's form posts them."""
    out = []
    ws = drawn("xbatch")
    out.append(_form_entry(WS_KEY, WS_TITLE, WS_CAP, profile, env, ws, tiles_html=_tiles_of(ws, profile), sec="xbatch"))
    groups = drawn("run_rules")
    for key, title, cap, picked in ((RUN_RULES_KEY, RUN_RULES_TITLE, RUN_RULES_CAP,
                                     [g for g in groups if g.get("title") == RUN_RULES_GROUP]),
                                    (NEW_CURVE_KEY, NEW_CURVE_TITLE, NEW_CURVE_CAP,
                                     [g for g in groups if g.get("title") != RUN_RULES_GROUP])):
        if any(g.get("shown") for g in picked):
            out.append(_form_entry(key, title, cap, profile, env, picked, tiles_html=_tiles_of(picked, profile),
                                   sec="run_rules"))
    return out


REPORTING_KEYS = {"intg": "run-intg", "rf": "run-rf", "al": "run-al"}
REPORTING_TILES = {"intg": "Results come from", "rf": "Matrix rows"}
REPORTING_OPEN = {"intg": "Edit where results come from", "rf": "Edit All matrices"}
REGULATORY_PAGE = "@@pfas-regulatory-limits"
REGULATORY_NAME = "Regulatory Limits"
REGULATORY_WORDS = "Regulatory Limits"
AL_EDIT_WORDS = "Edit this action level"
AL_STATE_LABEL = "On this method\u2019s certificates"
AL_HELD_NOTE = "The limit itself is kept in Regulatory Limits, for every method."
# where results come from, as Integration posts it
INTG_MODE_NAME = "f__mode"


def ls_words(state):
    from senaite.pfas import limit_states
    return limit_states.STATE_WORDS[state]


def _reporting_entry(sid, title, summary, profile, env, drawn):
    """(node, card) of a Reporting row: a card on the right, as every other
    row has. Integration and Certificate format read their one value, the
    tile opening its window in place (where results come from; the All
    matrices row); Action levels lists each limit with its placard, Evaluate
    or Off, set by a right click (it writes the Table view's own input), a
    row opening its own window: its state, its limit read, Go to Regulatory
    Limits inside."""
    key = REPORTING_KEYS[sid]
    node = _node(key, title, summary)
    _cf, mps, _pf, _iso, _ls = pg._tab_modules()
    if sid == "intg":
        # where results come from, edited here on Integration's own input
        opens = pg.card_act("open", REPORTING_OPEN[sid], [pg.inplace(
            "{0}: {1}".format(title, REPORTING_TILES[sid]),
            names=[[INTG_MODE_NAME, REPORTING_TILES[sid], [[v, w] for v, w in mps.INTEGRATION_MODES]]])])
    elif sid == "rf":
        # the certificate's matrix rows: the All matrices row each follows
        opens = pg.card_act("open", REPORTING_OPEN[sid], [("data-go-node", pg.RF_ALL_KEY)])
    if sid != "al":
        body = _tag("div", [("class", "pfas-hier-tiles")],
                    _tile(REPORTING_TILES[sid], summary, attrs=pg.tile_opens("open")))
        return node, _card(key, title, "", body, triggers=opens, help_sec=sid)
    from senaite.pfas import limit_placard
    from senaite.pfas import method_profile_sections as mps
    field = mps.ACTION_LEVELS.columns[0]
    rows, acts = [], []
    base = (env or {}).get("portal_url") or ""
    goto = pg.go_to(base, REGULATORY_PAGE, REGULATORY_NAME)
    states = [[v, ls_words(st)] for st, v in field.states]
    for g in drawn(sid):
        for r in g.get("rows") or ():
            cell = r["cells"][0]
            # a limit is a row per matrix it names: the matrix, then its words
            said = pg.MIDDOT.join(_text(x) for x in (r.get("sublabel"), r.get("note")) if x)
            words = _span("pfas-al-l", _text(r.get("label"))) + (_span("pfas-al-s", said) if said else "")
            act = "al{0}".format(len(rows))
            # a row opens its own window: its state, here; its limit, read,
            # held by Regulatory Limits
            acts.append(pg.card_act(act, AL_EDIT_WORDS, [pg.inplace(
                _text(r.get("label")), names=[[cell["name"], AL_STATE_LABEL, states]],
                read=said or None, note=AL_HELD_NOTE, goto=goto)]))
            rows.append(limit_placard.choice_box(cell["name"], _text(r.get("label")), _text(cell.get("value")),
                                                 field.states, tag="div", words=words, cls="pfas-hier-tilebox",
                                                 attrs=pg.tile_opens(act, [act, "reg"]),
                                                 variant=limit_placard.CARD_PLACARD))
    reg = pg.card_act("reg", REGULATORY_WORDS, [pg.inplace(REGULATORY_NAME, read=AL_HELD_NOTE, goto=goto)])
    # a row opens its window; its menu: its states, then that and Regulatory Limits
    body = _tag("div", [("class", "pfas-al-list")], "".join(rows)) if rows \
        else _tag("p", [("class", "pfas-hier-empty")], "No action level names this method's matrices.")
    cap = pg.counted(len([r for r in rows if 'data-limit-state="off"' not in r]), "limit") + \
        " on this method\u2019s certificates"
    return node, _card(key, title, cap, body, triggers="".join(acts) + reg, help_sec=sid)


def reporting_value(profile, env, sid, drawn):
    """A Reporting row's value: where results come from, the certificate's
    matrix rows, the limits on this method's certificates."""
    _cf, mps, _pf, _iso, _ls = pg._tab_modules()
    if sid == "intg":
        modes = dict(mps.INTEGRATION_MODES)
        mode = ((profile or {}).get("integration") or {}).get("mode")
        return modes.get(mode) or modes["vendor"]
    rows = [r for g in drawn(sid) for r in g.get("rows") or ()]
    if sid == "rf":
        return pg.counted(len(rows), "matrix row")
    return pg.counted(len([r for r in rows if _text(r["cells"][0].get("value")) != "off"]), "limit")


def render_run_list(profile, env=None, rte=None, groups_of=None):
    """Run & reporting's List view: <div id="run-list">, four groups. Run:
    the run template (its steps as mini-cards, from the Run Builder's `rte`)
    and QC composition; Extraction: the stages, the labels and dilutions;
    Channels: LC and SPE channels, a row each, empty or not; Reporting:
    Integration, Certificate format and Action levels, whose rows open
    their folds as built. Posts nothing: the Table view holds every input."""
    profile = profile or {}
    env = env or {}
    drawn = _groups_of(profile, env, groups_of)
    parts = {"Run": [], "Extraction": [], "Channels": []}
    if rte and rte.get("tpl"):
        parts["Run"].append(_template_entry(rte))
    qcc = drawn("qc_comp")
    parts["Run"].append(_form_entry(QCC_KEY, QCC_TITLE, "", profile, env, qcc,
                                    tiles_html=_qcc_tiles(profile, env, qcc), sec="qc_comp"))
    parts["Run"] += run_rule_entries(profile, env, drawn)
    parts["Extraction"].append(_stages_entry(profile))
    parts["Extraction"].append(_coll_entry("lbl", drawn("lbl")))
    parts["Extraction"].append(_form_entry(DIL_KEY, DIL_TITLE, DIL_CAP, profile, env, drawn("dil"), sec="dil"))
    parts["Channels"].append(_coll_entry("solv", drawn("solv")))
    parts["Channels"].append(_coll_entry("solv_spe", drawn("solv_spe")))
    nodes, cards = [], []
    for g in RUN_GROUPS[:3]:
        nodes.append(_group(g))
        for node, card in parts[g]:
            nodes.append(node)
            cards.append(card)
    _mark_first(nodes, cards)
    nodes.append(_group(RUN_GROUPS[3]))
    for sid, title in REPORTING:
        node, card = _reporting_entry(sid, title, reporting_value(profile, env, sid, drawn), profile, env, drawn)
        nodes.append(node)
        cards.append(card)
    return _list(RUN_LIST_ID, "run", "Run & reporting", nodes, cards, [("data-set-form", RUN_FORM)])


# ── Engine ──────────────────────────────────────────────────────────────────

ENGINE_LIST_ID = "engine-list"
NAMES_KEY, MCODES_KEY, REC_KEY, STUDIES_KEY = "eng-names", "eng-mcodes", "eng-rec", "eng-studies"
NAMES_HEAD, QCNAMES_HEAD = "Method & names", "Check standard names"
QCNAMES_CAP = "Injection names, naming only"
MCODES_HEAD = "Matrix codes"
MCODES_CAP = "The code each matrix carries in injection names"
MCODE_NOTE = "Injection code"
REC_HEAD = "Recoveries"
WHOLE_PERCENT = "Whole percent"
STUDIES_HEAD = "Studies"
STUDIES_CAP = "Which method studies this method offers"
ENGINE_GROUPS = (("Names", NAMES_KEY), ("Matrices", MCODES_KEY), ("Results", REC_KEY), ("Studies", STUDIES_KEY))
NAME_LABELS = {"display_name": "Display name", "description": "Description"}


def _loose(name, label, value):
    """A field the Engine tab draws by hand (Display name, Description) as a
    drawn text field, so it reads and edits as the section fields do."""
    return {"name": name, "label": label, "kind": "text", "value": value or "", "unit": "", "pair": None,
            "choices": None}


def _cells(groups):
    """A table section's cells, each under its row's label."""
    out = []
    for g in groups:
        for r in g.get("rows") or ():
            for c in r["cells"]:
                f = dict(c)
                f["label"] = r["label"] if len(r["cells"]) == 1 else "{0} {1}".format(r["label"], c["label"])
                out.append(f)
    return out


def render_engine_list(profile, env=None, groups_of=None, names=None):
    """Engine's List view: <div id="engine-list">, four groups, each one
    node (a line per section with how much of it is set) and one card:
    Names (Method & names: Display name, Description, other names, QC types
    judged as another; Check standard names), Matrices (a tile per matrix's
    injection code), Results (decimal places for recoveries) and Studies
    (Blanks from as a segment, the studies offered as switches). Posts
    nothing: the Table view holds every input. `names`: (display name,
    description) as the page draws them."""
    profile = profile or {}
    env = env or {}
    drawn = _groups_of(profile, env, groups_of)
    shown, desc = names if names is not None else (profile.get("display_name") or "", profile.get("description") or "")
    method = [_loose("display_name", NAME_LABELS["display_name"], shown),
              _loose("description", NAME_LABELS["description"], desc)] + _cells(drawn("engine_names"))
    qcn = _fields(drawn("qcnames"))
    codes = _cells(drawn("engine_mcodes"))
    rec = _fields(drawn("engine_rec"))
    studies = _fields(drawn("engine_studies"))

    def tiles(fields, block=None):
        return _tag("div", [("class", "pfas-hier-tiles"), ("data-set-block", block)] + pg.tile_opens(block),
                    "".join(_field_tile(f, ENGINE_FORM) for f in fields))

    def offered(fields):
        opts = [o for f in fields if f["kind"] == "multi" for o in f.get("options") or ()]
        n = len([o for o in opts if o.get("checked")])
        return (offered_words(n, len(opts)), [("data-set-checked", json.dumps([o["name"] for o in opts]))])

    def count(fields):
        return (count_words(len([f for f in fields if _is_set(f)]), len(fields)), _count_attrs(fields))

    cards = {
        NAMES_KEY: _card(NAMES_KEY, "Names", "", _head(NAMES_HEAD, "names") + tiles(method, "names") +
                         _head(QCNAMES_HEAD, "qcnames") + _tag("p", [("class", "pfas-hier-note")], _esc(QCNAMES_CAP)) +
                         tiles(qcn, "qcnames"),
                         triggers=_edit_button("Edit names", "names") + _edit_button("Edit check standard names", "qcnames"),
                         attrs=[("data-card-sec", "names qcnames")]),
        MCODES_KEY: _card(MCODES_KEY, MCODES_HEAD, MCODES_CAP,
                          _tag("div", [("class", "pfas-hier-tiles")],
                               "".join(pg._setting_tile(dict(_setting(f["label"], f), note=MCODE_NOTE), form=ENGINE_FORM)
                                       for f in codes)),
                          triggers=_edit_button("Edit"), attrs=[("data-card-sec", "engine_mcodes")], help_sec="engine_mcodes"),
        REC_KEY: _card(REC_KEY, REC_HEAD, "", _tag("div", [("class", "pfas-hier-tiles")],
                                                   "".join(_rec_tile(f) for f in rec)),
                       triggers=_edit_button("Edit"), attrs=[("data-card-sec", "engine_rec")], help_sec="engine_rec"),
        STUDIES_KEY: _card(STUDIES_KEY, STUDIES_HEAD, STUDIES_CAP, tiles(studies), triggers=_edit_button("Edit"),
                           attrs=[("data-card-sec", "engine_studies")], help_sec="engine_studies"),
    }
    rec_words = pg.section_summary(profile, env, "engine_rec")
    lines = {
        NAMES_KEY: [(NAMES_HEAD,) + count(method), (QCNAMES_HEAD,) + count(qcn)],
        MCODES_KEY: [(MCODES_HEAD,) + count(codes)],
        REC_KEY: [(REC_HEAD, rec_words, [("data-set-places", rec[0]["name"]), ("data-set-blank", WHOLE_PERCENT)]
                   if rec else [])],
        STUDIES_KEY: [(STUDIES_HEAD,) + offered(studies)],
    }
    nodes = [_group_node(key, title, lines[key]) for title, key in ENGINE_GROUPS]
    out = [cards[key] for _t, key in ENGINE_GROUPS]
    _mark_first(nodes, out)
    return _list(ENGINE_LIST_ID, "engine", "Engine", nodes, out, [("data-set-form", ENGINE_FORM)])


def offered_words(n, total):
    """"None offered", else "n of m offered"."""
    return "None offered" if not n else "{0} of {1} offered".format(n, total)


def _rec_tile(f):
    """Decimal places for recoveries: a blank reads Whole percent, the
    method default."""
    s = _setting(f["label"], f)
    v = _text(f.get("value")).strip()
    if not v:
        s["words"], s["note"] = WHOLE_PERCENT, DEFAULT_NOTE
    return pg._setting_tile(s, form=ENGINE_FORM, attrs=[("data-set-blank", WHOLE_PERCENT),
                                                         ("data-set-blank-note", DEFAULT_NOTE)])


# ── QC criteria: the group cards ────────────────────────────────────────────
# The Rules list's groups whose limits QC criteria holds, each drawn as the
# Calibration group is: a group node heading its rules (a line each, its
# state and limits) and the group's card. The card holds each rule's state
# (a nameless segment writing the rule table's input), the limits of the
# regions its rules open as tiles naming the inputs the Table view posts,
# the Required criteria as switches writing their boxes, each rule's Flag
# tile, then the actions: Edit opens the centred window on nameless copies
# of one region's tiles (data-qc-edit naming its block). A tile greys while
# the rule it judges for is Off (data-mute-if), never hidden, and stays
# editable.

QC_FORM = pg.QC_FORM
QC_GROUP_CAPS = {"CCV": "Continuing calibration verification",
                 pg.BLANKS_GROUP: "The most a blank may hold"}
# a region's block heading, by (section, its group as drawn)
QC_BLOCK_HEADS = {
    ("cal", "Continuing Calibration Verification (CCV)"): "Limits",
    ("cal", "Chromatographic Confirmation & Signal Quality"): "Limits",
    ("cal", "Single-Transition Confirmation"): "Single-transition confirmation",
    ("blk", None): "Limits",
}
# a region's Edit, by its first part (section, group); else Edit limits
QC_EDIT_WORDS = {
    ("cal", "Single-Transition Confirmation"): "Edit single-transition",
}
REQUIRED_HEAD = "Required"
BLANK_UNIT = "× RL"
FAILS_WORDS = "Fails at the limit"
# what a blank's tile says of a result equal to its limit, by its Fails at
# the limit box
AT_LIMIT_WORDS = {True: "A result equal to the limit fails.", False: "A result equal to the limit passes."}
EDIT_TIERS_WORDS = "Edit tiers"
COPY_TIERS_WORDS = "Copy tiers from method"


def _qc_node(key, title, value, lines, attrs=()):
    """A group's node in the Rules list, as the Calibration group's: its
    name, how many rules, a line per rule."""
    return _tag("button", [("type", "button"), ("class", "pfas-hier-node is-group"),
                           ("data-hier-target", key), ("aria-pressed", "false"),
                           ("data-rule-group-node", title)] + list(attrs),
                _span("pfas-hier-node-t", title) + _span("pfas-hier-node-v", value) + "".join(lines))


def _qc_card(key, title, caption, body, acts, attrs=(), triggers=""):
    return _tag("section", [("class", "pfas-hier-card is-group"), ("data-hier-card", key), ("data-qc-card", True),
                            ("aria-label", title), ("hidden", True)] + list(attrs),
                _tag("h4", [("class", "pfas-hier-card-t")], _esc(title)) +
                (_tag("p", [("class", "pfas-hier-card-cap")], _esc(caption)) if caption else "") +
                body + pg.card_acts(triggers) + pg.actions_row(acts))


def _states_words(rows):
    """"Enforced" when every rule is, else each state counted."""
    said = [_text(r.cells["state"].value) for r in rows]
    if not said:
        return ""
    if len(set(said)) == 1:
        return pg.STATE_WORDS.get(said[0], said[0])
    return ", ".join("{0} {1}".format(said.count(st), pg.STATE_WORDS[st]) for st in ("enforced", "evaluate", "off")
                     if st in said)


def _field_rule(name, region):
    """The rule a region's field judges for: the rule whose criteria it is
    (profile_grids.RULE_CRITERIA), else the region's one rule."""
    bits = name.split("__")
    if len(bits) == 3:
        for key in region["rules"]:
            grp, criteria = pg.RULE_CRITERIA.get(key, (None, ()))
            if grp == bits[1] and bits[2] in criteria:
                return key
    return region["rules"][0] if len(region["rules"]) == 1 else None


def _muted(mute_of, key):
    rmute, roff = mute_of.get(key, ([], False))
    return rmute, ("is-muted" if roff else None)


def _qc_field_tile(f, rule, mute_of, profile=None):
    """A limit's tile. A field that is a limit box carries the box's
    placard and greys by its own state (limit_placard); any other greys
    while its rule is Off."""
    from senaite.pfas import limit_placard
    box = limit_placard.box_of_name(f["name"]) if profile is not None else None
    attrs, cls = ([], None) if box else _muted(mute_of, rule)
    if f["kind"] == "multi":
        # a long list of analytes: its ticked ones in words, edited in the window
        return pg._setting_tile(_setting(f["label"], f), form=QC_FORM, attrs=attrs, cls=cls)
    tile = _field_tile(f, QC_FORM, attrs=attrs, cls=cls)
    return limit_placard.boxed(tile, profile, box, limit_placard.uses_words(box)) if box else tile


def _blank_tile(r, mute_of, profile=None):
    """One blank's limit, a multiple of the RL, and under it what a result
    equal to the limit does (its Fails at the limit box, in words that
    follow the box); the limit is its default tier's box, with its placard
    (limit_placard). The tile names both inputs, so its window edits the
    limit and the switch."""
    from senaite.pfas import limit_placard, limit_states
    from senaite.pfas.qc import rules
    most, fails = r["cells"][0], r["cells"][1]
    code = most["name"].split("__")[2]
    tier = (limit_states.tiers(profile, code) or [None])[0] if profile is not None else None
    box = limit_states.tier_key(code, tier) if tier and tier.get("name") else None
    attrs, cls = ([], None) if box else _muted(mute_of, rules.BLANK_KEY(code))
    s = pg._setting(_text(r["label"]), dict(most, unit=BLANK_UNIT))
    tile_attrs = [("class", _cls("pfas-hier-tile", "pfas-hier-amount", cls)),
                  ("data-set-names", json.dumps(s["names"] + [fails["name"]])), ("data-set-form", QC_FORM),
                  ("data-set-kind", s["kind"]), ("data-set-labels", json.dumps(s["labels"] + [FAILS_WORDS])),
                  ("data-set-unit", BLANK_UNIT)] + list(attrs)
    at_limit = _span("pfas-hier-tile-s", AT_LIMIT_WORDS[bool(fails.get("checked"))],
                     [("data-at-limit", fails["name"]), ("data-on-words", AT_LIMIT_WORDS[True]),
                      ("data-off-words", AT_LIMIT_WORDS[False])])
    tile = _tag("div", tile_attrs, _span("pfas-hier-tile-l", s["label"]) + _span("pfas-hier-tile-v", s["words"]) +
                at_limit)
    return limit_placard.boxed(tile, profile, box) if box else tile


def _region_body(region, profile, drawn, mute_of):
    """(block, required): a region's limits as tiles under their headings,
    in one block its Edit opens (data-qc-block), each limit box with its
    placard; `required` is always empty: no Required switches are drawn."""
    blocks, required = [], ""
    for part in region["parts"]:
        if part["kind"] == "section":
            groups = drawn(part["sid"])
            if part.get("group"):
                groups = [g for g in groups if g.get("title") == part["group"]]
            for g in groups:
                head = QC_BLOCK_HEADS.get((part["sid"], g.get("title")), g.get("title"))
                tiles = "".join(_qc_field_tile(f, _field_rule(f["name"], region), mute_of, profile)
                                for f in g.get("shown") or ())
                blocks.append(_head(head) + _tag("div", [("class", "pfas-hier-tiles")], tiles))
        elif part["kind"] == "table" and part["sid"] == "blk":
            rows = [r for g in drawn("blk") for r in g.get("rows") or ()]
            blocks.append(_head(QC_BLOCK_HEADS[("blk", None)]) +
                          _tag("div", [("class", "pfas-hier-tiles")], "".join(_blank_tile(r, mute_of, profile)
                                                                             for r in rows)))
    act = "qc-" + region["id"]
    block = _tag("div", [("data-qc-block", region["id"])] + pg.tile_opens(act),
                 "".join(blocks) + pg.card_acts(pg.card_act(act, _edit_words(region), [("data-qc-edit", region["id"])]))) \
        if blocks else ""
    return block, required


def _edit_words(region):
    first = region["parts"][0] if region["parts"] else {}
    return QC_EDIT_WORDS.get((first.get("sid"), first.get("group")), pg.EDIT_LIMITS_WORDS)


def _rec_words(trees):
    def words(row):
        from senaite.pfas.qc import rules
        tree = trees.get(rules.qc_row_code(row.key))
        if tree is not None:
            return pg.tier_summary(tree)[0]
        w = pg._limit_words_of(row)
        return "" if w in (pg.IN_THE_GRID, pg.EM_DASH) else w
    return words


def _recoveries_body(rows, profile, env, trees):
    """Analyte recoveries' card: each QC type's tiers, in the order the
    engine tries them (the table its node's card draws, redrawn with it by
    the preview: data-tier-gpart), greyed while its row is Off; the spike
    levels of every matrix, each a cell the shared cell editor opens."""
    from senaite.pfas.qc import rules
    _cf, mps, _pf, _iso, _ls = pg._tab_modules()
    out = []
    for r in rows:
        tree = trees.get(rules.qc_row_code(r.key))
        if tree is None or not tree["held"]:
            continue
        mute = list(tree.get("mute") or [])
        cls = dict(mute).get("class")
        table = pg._tier_table(tree, r.key).replace('data-tier-part="table:', 'data-tier-gpart="table:', 1)
        out.append(_tag("div", [("class", _cls("mp-qc-gtiers", cls))] + [a for a in mute if a[0] != "class"],
                        _head(r.label) + table))
    matrices = list((profile or {}).get("supported_matrices") or [])
    for sid in [s for s in pg.qc_section_ids(profile) if s.startswith("spk_")]:
        spk = pg._spike_rows(mps, profile, sid[4:], matrices)
        out.append(pg._spike_table(spk, matrices, sid, title="Spike levels, " + mps.SPIKE_LABELS[sid[4:]]))
    return "".join(out)


def qc_group_entry(title, sheet, profile, env, drawn, regions, copy_methods=""):
    """(node, card) of one QC criteria group drawn as a card (CCV,
    Confirmation and signal, Analyte recoveries, Blanks): the group's rules
    drawn in the list (none drawn hidden for + Add QC type), the regions
    their limits are set in (profile_grids.rule_editors), the window grid's
    left in the Table view."""
    from senaite.pfas.qc import rules
    key = pg.QC_GROUP_KEYS[title]
    rows = [r for r in sheet.rows if pg.rule_group(r.key) == title and not r.hidden]
    keys = set(r.key for r in rows)
    trees = {}
    if title == pg.RECOVERIES_GROUP:
        trees = dict((q, pg.tier_tree(profile, env, q)) for q, _l in pg.QC_TYPES)
    lines, states, mute_of = pg.rule_lines(sheet, rows, _rec_words(trees) if trees else None, profile)
    body, acts, triggers, attrs = "", "", "", []
    if title == pg.RECOVERIES_GROUP:
        body = _recoveries_body(rows, profile, env, trees)
        # every tier's window in one window, never the Table view
        triggers = pg.card_act("tiers", EDIT_TIERS_WORDS,
                               [pg.inplace(pg.RECOVERIES_GROUP, tables=[{"sel": "#" + pg.WINDOWS_REGION}])])
        attrs = pg.tile_opens("tiers")
        if copy_methods:
            acts += pg._list_button(COPY_TIERS_WORDS, [("data-copy-tiers", "tiers-copy"), ("data-methods", copy_methods)])
        caption = [" ".join([r.label, pg.tier_summary(trees[rules.qc_row_code(r.key)])[0]])
                   for r in rows if trees.get(rules.qc_row_code(r.key)) is not None]
    else:
        # no rule-level state segments: each limit tile carries its box's
        # own placard (limit_placard)
        body = ""
        for region in regions:
            if region["sec"] or not keys & set(region["rules"]):
                continue
            block, required = _region_body(region, profile, drawn, mute_of)
            body += block + required
        caption = [QC_GROUP_CAPS[title]] if title in QC_GROUP_CAPS else []
    caption += [pg.counted(len(rows), "rule"), _states_words(rows)]
    # a note several of the group's rules share: once, above their tiles
    shared_html, shared = pg.shared_note_block(profile, [(r.key, r.label) for r in rows])
    flags = shared_html + "".join(pg.render_flag_tile(r.key, profile, env, title=r.label, named=len(rows) > 1,
                                                      shared=r.key in shared) for r in rows)
    node = _qc_node(key, title, pg.counted(len(rows), "rule"), lines)
    # what each rule judges, under the caption
    applies = pg.applies_lines([(r.key, r.label, mute_of[r.key][1]) for r in rows], profile)
    card = _qc_card(key, title, pg.MIDDOT.join(c for c in caption if c), applies + body + flags, acts, attrs=attrs,
                    triggers=triggers)
    return node, card
