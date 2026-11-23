# -*- coding: utf-8 -*-
"""A matrix's own temperature ranges over the method's All matrices ones.

The method's keys are All matrices: `receipt_temperature` {min_c, max_c,
same_day_on_ice} and the storage range of each kept item,
`storage_temperature`, `storage_temperature_processed`,
`storage_temperature_extract` {min_c, max_c}. Beside each, `<key>_by_matrix`
{matrix title: {min_c, max_c[, same_day_on_ice]}} holds only what a matrix
sets for itself:

- a blank end follows All matrices' end, an unset same-day on ice its
  switch; a matrix the map does not name follows All matrices whole;
- a matrix's title is matched as the holding times match it, case and
  spacing aside (the receipt passes the Sample Type's title);
- nothing is ever copied into a map: an absent map is every matrix
  following All matrices.

A fridge or freezer holding several matrices is judged against the
narrowest of the ranges of every matrix it holds: the highest minimum and
the lowest maximum. Ranges that do not overlap leave no temperature that
meets them all, a setting to fix and never a failed reading.

What a unit holds: its entries `MID`, `MID:processed`, `MID:extract` (the
method's samples, processed samples, extracts) and, per method, the
matrices it holds them for (`held_matrices_json` {method id: [titles]}); a
method with no list is all its matrices.

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import json

RECEIPT = "receipt_temperature"
STORAGE = (("sample", "storage_temperature"),
           ("processed", "storage_temperature_processed"),
           ("extract", "storage_temperature_extract"))
KEYS = (RECEIPT,) + tuple(k for _kept, k in STORAGE)
SUFFIX = "_by_matrix"
ENDS = ("min_c", "max_c")
ICE = "same_day_on_ice"
AS_ALL = "As All matrices"
# a range set to no requirement: not judged, and not a gap to fill
NONE = "none"
NO_REQUIREMENT = "No requirement"
NO_REQUIREMENT_TEXT = "No requirement: not judged"
NARROWEST = "Narrowest of {0}"

try:
    _STR = (str, unicode)       # noqa: F821  (Python 2)
except NameError:               # pragma: no cover  (Python 3)
    _STR = (str,)


def by_matrix(key):
    """The map of a method key's per-matrix overrides."""
    return key + SUFFIX


def storage_key(kept):
    """The method key of a kept item's storage range ("sample" when unknown)."""
    return dict(STORAGE).get(kept or "sample", "storage_temperature")


def number(v):
    """A stored end as a float, or None (blank, or not a number)."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, _STR) and not v.strip():
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def text(v):
    """A title as text: core hands titles over as UTF-8 bytes."""
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    return "%s" % (v or "")


def _title(v):
    return text(v).strip().lower()


def own(profile, key, matrix):
    """What the matrix sets for itself under a method key: {} when nothing."""
    mapping = (profile or {}).get(by_matrix(key))
    if not isinstance(mapping, dict) or not matrix:
        return {}
    matrix = text(matrix)
    found = mapping.get(matrix)
    if found is None:
        wanted = _title(matrix)
        for k, v in mapping.items():
            if _title(k) == wanted:
                found = v
                break
    return dict(found) if isinstance(found, dict) else {}


def no_requirement(rng):
    """The range is set to No requirement (stored true, or "on" as a form's
    box posts it): nothing is judged against it."""
    v = (rng or {}).get(NONE) if isinstance(rng, dict) else None
    return v is True or (isinstance(v, _STR) and v.strip().lower() in ("on", "1", "true", "yes"))


def is_set(profile, key, matrix):
    """The matrix sets an end, No requirement, or (receipt) its same-day on ice."""
    mine = own(profile, key, matrix)
    return (any(number(mine.get(e)) is not None for e in ENDS) or isinstance(mine.get(ICE), bool)
            or no_requirement(mine))


def resolve(profile, key, matrix):
    """The range that applies to the matrix: No requirement when it says so;
    else each end it sets, else All matrices' (whose No requirement it
    follows while it sets no end); its same-day on ice when set, else All
    matrices'."""
    base = (profile or {}).get(key)
    out = dict(base) if isinstance(base, dict) else {}
    mine = own(profile, key, matrix)
    if no_requirement(mine):
        return {NONE: True}
    if no_requirement(out):
        out.pop(NONE, None)
        if not any(number(mine.get(e)) is not None for e in ENDS):
            return {NONE: True}
    for end in ENDS:
        v = number(mine.get(end))
        if v is not None:
            out[end] = v
    if isinstance(mine.get(ICE), bool):
        out[ICE] = mine[ICE]
    return out


def receipt_range(profile, matrix):
    return resolve(profile, RECEIPT, matrix)


def storage_range(profile, kept, matrix):
    return resolve(profile, storage_key(kept), matrix)


def _supported(profile, matrices):
    """The method's matrices the list names (title-tolerant), in the
    method's order; every matrix when no list is given."""
    every = list((profile or {}).get("supported_matrices") or [])
    if not matrices:
        return every
    wanted = set(_title(m) for m in matrices)
    return [m for m in every if _title(m) in wanted]


def held_rows(entry, profile, matrices=None, homogenised=None):
    """[(label, lo, hi, [matrices])] a unit holding `entry` ("MID",
    "MID:processed", "MID:extract") is judged against: one row per distinct
    range of the matrices it holds, in the method's order; a range with no
    end set, or No requirement, judges nothing and is left out. Every held
    matrix sharing one range is labelled by the entry alone, as before
    matrices had their own. Processed samples are only of the matrices
    homogenised (`homogenised`, the site's titles; None: unknown, all)."""
    entry = "%s" % entry
    _mid, _sep, kept = entry.partition(":")
    key = storage_key(kept or "sample")
    ms = _supported(profile, matrices)
    if kept == "processed" and homogenised is not None:
        made = set(_title(m) for m in homogenised)
        ms = [m for m in ms if _title(m) in made]
        if not ms:
            return []
    if not ms:
        rng = resolve(profile, key, None)
        lo, hi = number(rng.get("min_c")), number(rng.get("max_c"))
        return [] if lo is None and hi is None else [(entry, lo, hi, [])]
    groups = []
    for m in ms:
        rng = resolve(profile, key, m)
        ends = (number(rng.get("min_c")), number(rng.get("max_c")))
        for g in groups:
            if g[0] == ends:
                g[1].append(m)
                break
        else:
            groups.append((ends, [m]))
    every = len(groups) == 1 and not matrices
    out = []
    for (lo, hi), names in groups:
        if lo is None and hi is None:
            continue
        label = entry if every else "{0}: {1}".format(entry, ", ".join(names))
        out.append((label, lo, hi, names))
    return out


def held_of(unit):
    """{method id: [matrix titles]} a unit holds; {} when it names none."""
    raw = (unit or {}).get("held_matrices_json")
    try:
        got = json.loads(raw) if isinstance(raw, _STR) else (raw or {})
    except (TypeError, ValueError):
        return {}
    if not isinstance(got, dict):
        return {}
    return dict((k, [m for m in v if isinstance(m, _STR) and m.strip()])
                for k, v in got.items() if isinstance(v, list))


def held_from_ticks(every, ticked):
    """The matrices a unit stores for a method, from its switches: the
    ticked ones, in the method's order; None (all of them) when every one
    or none is ticked."""
    wanted = set(_title(m) for m in ticked or [])
    chosen = [m for m in every or [] if _title(m) in wanted]
    return chosen if chosen and len(chosen) < len(every or []) else None


def held_switches(every, chosen):
    """[(title, on)]: a switch per matrix of the method, every one on while
    the unit names none."""
    wanted = set(_title(m) for m in chosen or [])
    return [(m, not wanted or _title(m) in wanted) for m in every or []]


def narrowest(rows, unit_lo=None, unit_hi=None):
    """(lo, hi): the highest minimum and the lowest maximum of the unit's own
    range and each row's; either None when nothing sets it."""
    los = [v for v in [unit_lo] + [r[1] for r in rows or []] if v is not None]
    his = [v for v in [unit_hi] + [r[2] for r in rows or []] if v is not None]
    return (max(los) if los else None), (min(his) if his else None)


def conflict(lo, hi):
    """No temperature meets ranges whose narrowest is reversed."""
    return lo is not None and hi is not None and lo > hi


def applied(rows):
    """Why a unit holding more than one range is judged as it is
    ("Narrowest of Tissue, Solid"), or "" for one range or none. Rows of one
    entry name their matrices; rows of several entries their labels."""
    rows = list(rows or [])
    if len(rows) < 2:
        return ""
    entries = set(r[0].partition(": ")[0] for r in rows)
    if len(entries) == 1 and all(len(r) > 3 and r[3] for r in rows):
        names = []
        for r in rows:
            names.extend(n for n in r[3] if n not in names)
        return NARROWEST.format(", ".join(names))
    return NARROWEST.format("; ".join(r[0] for r in rows))


def ranges_words(rows):
    """"Tissue -20 to -10 °C; Solid -20 to 6 °C": the ranges that clash."""
    def end(v):
        return "%g" % v if v is not None else "?"
    return "; ".join("{0} {1} to {2} °C".format(r[0], end(r[1]), end(r[2])) for r in rows)


def migrate(profile):
    """Normalise each stored per-matrix map: an end typed as text read as a
    number, a blank end and a matrix that sets nothing dropped. True if
    anything changed; idempotent. The method's own keys are never touched
    and no override is ever created: an absent map stays absent."""
    if not isinstance(profile, dict):
        return False
    changed = False
    for key in KEYS:
        mapping = profile.get(by_matrix(key))
        if not isinstance(mapping, dict):
            continue
        for m in list(mapping):
            entry = mapping[m]
            if not isinstance(entry, dict):
                continue
            for end in ENDS:
                if end not in entry:
                    continue
                v = number(entry[end])
                if v is None:
                    del entry[end]
                    changed = True
                elif entry[end] != v or isinstance(entry[end], bool) or not isinstance(entry[end], float):
                    entry[end] = v
                    changed = True
            if ICE in entry and not isinstance(entry[ICE], bool):
                del entry[ICE]
                changed = True
            if not entry:
                del mapping[m]
                changed = True
    return changed


def unit_judgement(unit, profile_of, homogenised=None):
    """What a monitored unit is judged against: {"rows": [(label, lo, hi,
    matrices)] for what it holds, "lo", "hi": the narrowest of its own range
    and those, "conflict": True when they do not overlap, "why": how the
    range was reached ("Narrowest of Tissue, Solid", or ""), "clash": the
    ranges in words}. `profile_of(method id)` reads a method's profile."""
    unit = unit or {}
    try:
        entries = json.loads(unit.get("profiles_json") or "[]") or []
    except (TypeError, ValueError):
        entries = []
    held = held_of(unit)
    rows = []
    for entry in entries:
        mid = ("%s" % entry).partition(":")[0]
        rows.extend(held_rows(entry, profile_of(mid) or {}, held.get(mid), homogenised))
    lo, hi = narrowest(rows, number(unit.get("temp_min")), number(unit.get("temp_max")))
    return {"rows": rows, "lo": lo, "hi": hi, "conflict": conflict(lo, hi), "why": applied(rows),
            "clash": ranges_words(rows)}


def method_conflicts(method_id, units, profile_of, homogenised=None):
    """["<unit>: <ranges>"] for each unit holding something of the method
    whose ranges do not overlap: said in the method's own editor."""
    out = []
    for u in units or []:
        try:
            entries = json.loads((u or {}).get("profiles_json") or "[]") or []
        except (TypeError, ValueError):
            continue
        if not any(("%s" % e).partition(":")[0] == method_id for e in entries):
            continue
        got = unit_judgement(u, profile_of, homogenised)
        if got["conflict"]:
            out.append("{0}: {1}".format(u.get("name") or u.get("id") or "", got["clash"]))
    return out


def units_holding(method_id, units):
    """{matrix: [unit names]}: the units whose list of matrices held names
    the matrix for the method (a unit with no list holds every matrix and
    names none)."""
    out = {}
    for u in units or []:
        for m in held_of(u).get(method_id) or []:
            names = out.setdefault(m, [])
            name = (u or {}).get("name") or (u or {}).get("id") or ""
            if name not in names:
                names.append(name)
    return out


def release(item, method_id, matrices):
    """(item, changed): a unit's stored item with the removed matrices taken
    off what it holds for the method. A list left empty would read as every
    matrix, so the unit then holds nothing of the method: its entries for
    the method go with the list."""
    held = held_of(item)
    mine = held.get(method_id)
    if not mine:
        return item, False
    gone = set(_title(m) for m in matrices or [])
    left = [m for m in mine if _title(m) not in gone]
    if len(left) == len(mine):
        return item, False
    out = dict(item)
    if left:
        held[method_id] = left
    else:
        del held[method_id]
        try:
            entries = json.loads(out.get("profiles_json") or "[]") or []
        except (TypeError, ValueError):
            entries = []
        entries = [e for e in entries if ("%s" % e).partition(":")[0] != method_id]
        out["profiles_json"] = json.dumps(entries) if entries else None
    out["held_matrices_json"] = json.dumps(held, sort_keys=True) if held else None
    return out, True
