# -*- coding: utf-8 -*-
"""A table row's menu, stated once: the value of a row's data-row-actions.

No button or link stands inside a table row. A row names its item's
address in data-row-open and its actions in data-row-actions, which
pfas-components.js (initRowLinks) offers as the row's menu: a right click,
the menu key or Shift+F10 on the focused row, and on a touch screen a long
press or the dots at the row's end. A template writes the attribute with
the @@pfas-row-menu view:

    tal:define="rm context/@@pfas-row-menu"
    tal:attributes="data-row-open item/url;
                    data-row-actions python:rm.actions(
                        (u'Make a stock', 'href', item['make_url']),
                        (u'Withdraw my signature', 'modal', 'esig-withdraw-7') if mine else None,
                        (u'Revert this change', 'form', 'ch-revert-12', {'danger': True}))"

Each action is (label, kind, target[, options]) or a dict, kind one of:
href (an address to go to), modal (the id of a .pfas-modal to open), form
(the id of a form, outside the table, to submit) or event (a name the
page's script hears as "pfas:row-action" on the row; "remove-row" takes an
editable grid's row out). The options:
note (a line under the label), blank (an href in a new tab), danger (it
ends or removes something: drawn last, after a separator), off (the reason
it is refused: drawn disabled, the reason under it), confirm (asked before
a form is sent) and values (fields set on the form before it is sent).
None is skipped, so a template can leave an action out by a condition.
Python 2.7 compatible.
"""
from __future__ import absolute_import, unicode_literals

import json

import six

KINDS = ("href", "modal", "form", "event")
OPTIONS = ("note", "blank", "danger", "off", "confirm", "values")


def _text(value):
    if isinstance(value, six.binary_type):
        return value.decode("utf-8")
    return six.text_type(value)


def action(label, kind, target, options=None):
    """One action as the menu reads it; ValueError for a kind not known or
    an option not known, so a typing slip fails where it is written."""
    if kind not in KINDS:
        raise ValueError("row action kind {0!r} is not one of {1}".format(kind, KINDS))
    out = {"label": _text(label), kind: _text(target)}
    for k, v in sorted((options or {}).items()):
        if k not in OPTIONS:
            raise ValueError("row action option {0!r} is not one of {1}".format(k, OPTIONS))
        if v in (None, "", False):
            continue
        if k == "values":
            out[k] = dict((_text(n), _text(x)) for n, x in v.items())
        elif k in ("blank", "danger"):
            out[k] = True
        else:
            out[k] = _text(v)
    return out


def actions(*items):
    """The JSON for data-row-actions, or None (no attribute drawn) when no
    action is left. A target that is empty leaves its action out: a row
    whose item has no such page offers nothing in its place."""
    out = []
    for it in items:
        if it is None:
            continue
        if isinstance(it, dict):
            it = dict(it)
            kind = [k for k in KINDS if it.get(k) is not None]
            if len(kind) != 1:
                raise ValueError("a row action names one of {0}: {1!r}".format(KINDS, it))
            label, target = it.pop("label"), it.pop(kind[0])
            it = (label, kind[0], target, it)
        label, kind, target = it[0], it[1], it[2]
        if not target:
            continue
        out.append(action(label, kind, target, it[3] if len(it) > 3 else None))
    if not out:
        return None
    return json.dumps(out, sort_keys=True, ensure_ascii=False)
