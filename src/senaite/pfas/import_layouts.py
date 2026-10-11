# -*- coding: utf-8 -*-
"""Import layouts: how an instrument export is laid out, read the same way by
Import Studio (its preview and saved profile) and by the pipeline worker.

A layout profile is the lab's description of one export layout, made with
Import Studio's form controls:

    {"id": "layout-3", "name": "...", "instrument_uid": "" | uid,
     "reader": {"layout": "long" | "wide" | "blocks", "delimiter": "auto" |
                "comma" | "tab" | "semicolon" | "pipe", "encoding": "utf-8" |
                "latin-1", "header_row": 1, "skip_column": "", "skip_values":
                "", "missing": "", "group_pattern": "", "attach_pattern": "",
                "strip_pattern": "", "block_pattern": ""},
     "signature": [the column names the file was read with],
     "match": "within" (default) | "exact", "required": [fields also required],
     "map": {column: canonical field}, "calc_mode": "final" | "raw",
     "manual_markers": "", "date_format": "", "value_maps": {field: {from: to}},
     "scales": {field: factor}, "qualifier_suffix": "",
     "labelled_from_columns": False, "notes": "", "software": "", "retired": False}

    long    one header row (the header_row-th record), one row per injection x
            compound below it
    wide    two header rows: the first names a group of columns (a compound,
            by group_pattern's named group "compound"; a group matching
            attach_pattern belongs to the compound before it; any other group
            is the injection's own columns), the second names each column
    blocks  one block per compound: a line matching block_pattern (its named
            group "compound") starts it, the next line with several cells is
            its header, its rows run to a blank line or the next block; lines
            before the first block (a report preamble) are not read

The compound a group or block names becomes the column COMPOUND, which the
analyst maps like any other. A row whose `skip_column` holds one of
`skip_values` (statistics rows) is dropped; a cell holding one of `missing`
(e.g. "-----, N/A, N/F") reads as empty.

A file is matched to a profile by its columns -- the names the profile's
reader options give it, compared without case, punctuation, spacing or a
bracketed unit -- and the instrument (match). "within" (the default) asks
only for the columns of the fields the layout needs (injection, compound, a
result, any it marks required); "exact" for the same columns. The best fit
wins (the run's instrument, then the most columns matched, then the fewest
unmatched); a tie, or no fit, is refused, never guessed -- naming each
missing column and the nearest headers the file has.

Pure: Python 2.7 and 3, no Zope imports (the worker loads this file from the
add-on, pfas_pipeline.addon).
"""
from __future__ import absolute_import, division, unicode_literals

import json
import re

COMPOUND = "[compound]"          # the column a group / block heading becomes
LAYOUTS = (("long", "Long: one header row, a row per injection and compound"),
           ("wide", "Wide: two header rows, a block of columns per compound"),
           ("blocks", "Blocks: one block of rows per compound, after any preamble"))
DELIMITERS = (("auto", "Detect"), ("comma", "Comma"), ("tab", "Tab"),
              ("semicolon", "Semicolon"), ("pipe", "Vertical bar"))
_DELIM_CHAR = {"comma": ",", "tab": "\t", "semicolon": ";", "pipe": "|"}
ENCODINGS = (("utf-8", "UTF-8 (a byte-order mark is removed)"), ("latin-1", "Latin-1"))
MATCH_MODES = (("within", "The columns it needs (others may be added or left out)"),
               ("exact", "Exactly these columns"))
READER_DEFAULTS = {"layout": "long", "delimiter": "auto", "encoding": "utf-8", "header_row": 1,
                   "skip_column": "", "skip_values": "", "missing": "", "group_pattern": "",
                   "attach_pattern": "", "strip_pattern": "", "block_pattern": ""}
# the fields an import cannot do without: which injection, which compound,
# and a result (the calculated or the measured concentration)
NEED = ("injection_name", "compound_name")
RESULT_FIELDS = ("calculated_conc", "measured_conc")
HEAD_LINES = 200                 # the lines of a file its layout is matched on


class LayoutRefused(Exception):
    """No profile, or more than one, matches a file: the import is refused."""


# ── text ─────────────────────────────────────────────────────────────────────

def decode(raw, encoding="utf-8"):
    """Bytes as text; a UTF-8 byte-order mark is removed (both readers alike)."""
    if not isinstance(raw, bytes):
        text = raw
    elif (encoding or "utf-8").lower().replace("_", "-") in ("latin-1", "latin1", "iso-8859-1"):
        text = raw.decode("latin-1")
    else:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
    return text[1:] if text[:1] == "﻿" else text


def head(text, lines=HEAD_LINES):
    """The first `lines` lines of a text (what a file's layout is matched on)."""
    out = []
    for line in text.splitlines(True):
        out.append(line)
        if len(out) >= lines:
            break
    return "".join(out)


def records(text, delimiter):
    """[[cell, ...]] per record: fields split on the delimiter, a quoted field
    may hold the delimiter, a doubled quote or a line break; CRLF, LF and CR
    all end a record."""
    out, row, cell = [], [], []
    quoted, i, n = False, 0, len(text)
    at_start = True
    while i < n:
        c = text[i]
        if quoted:
            if c == '"':
                if i + 1 < n and text[i + 1] == '"':
                    cell.append('"')
                    i += 2
                    continue
                quoted = False
            else:
                cell.append(c)
            i += 1
            continue
        if c == '"' and at_start:
            quoted = True
            at_start = False
        elif c == delimiter:
            row.append("".join(cell))
            cell = []
            at_start = True
        elif c in "\r\n":
            row.append("".join(cell))
            out.append(row)
            row, cell = [], []
            at_start = True
            if c == "\r" and i + 1 < n and text[i + 1] == "\n":
                i += 1
        else:
            cell.append(c)
            at_start = False
        i += 1
    if cell or row:
        row.append("".join(cell))
        out.append(row)
    return out


def sniff(text):
    """The delimiter a text uses: of comma, tab, semicolon and vertical bar,
    the one most lines carry (ties: tab, comma, semicolon, bar)."""
    lines = [l for l in text.splitlines()[:40] if l.strip()]
    best, best_n = ",", -1
    for name in ("tab", "comma", "semicolon", "pipe"):
        ch = _DELIM_CHAR[name]
        n = sum(1 for l in lines if ch in l)
        if n > best_n:
            best, best_n = ch, n
    return best


def delimiter_of(text, opts):
    name = (opts or {}).get("delimiter") or "auto"
    return sniff(text) if name == "auto" else _DELIM_CHAR.get(name, ",")


def _markers(text):
    return set(m.strip() for m in re.split(r"[,;]", text or "") if m.strip())


def _unique(names):
    """Header names made unique the way pandas does ("X", "X.1", "X.2"); an
    empty name is "Unnamed: <index>"."""
    seen, out = {}, []
    for i, n in enumerate(names):
        n = (n or "").strip() or "Unnamed: %d" % i
        if n in seen:
            seen[n] += 1
            k = "%s.%d" % (n, seen[n])
            while k in seen:
                seen[n] += 1
                k = "%s.%d" % (n, seen[n])
            seen[k] = 0
            out.append(k)
        else:
            seen[n] = 0
            out.append(n)
    return out


def _compile(pattern, what):
    try:
        return re.compile(pattern) if pattern else None
    except re.error as exc:
        raise ValueError("%s is not a valid pattern (%s)" % (what, exc))


# ── reading ──────────────────────────────────────────────────────────────────

def options(opts):
    out = dict(READER_DEFAULTS)
    out.update(dict((k, v) for k, v in (opts or {}).items() if k in READER_DEFAULTS))
    try:
        out["header_row"] = max(1, int(out.get("header_row") or 1))
    except (TypeError, ValueError):
        out["header_row"] = 1
    return out


def read(text, opts=None):
    """{"headers", "rows" [{column: cell}], "signature", "delimiter"} for a
    text read with the reader options. Raises ValueError on an invalid
    pattern or a layout the text does not have."""
    o = options(opts)
    delim = delimiter_of(text, o)
    recs = records(text, delim)
    missing = _markers(o["missing"])
    layout = o["layout"]
    if layout == "wide":
        headers, rows = _read_wide(recs, o)
    elif layout == "blocks":
        headers, rows = _read_blocks(recs, o, delim)
    else:
        headers, rows = _read_long(recs, o)
    skip_col, skip = o["skip_column"].strip(), _markers(o["skip_values"])
    out = []
    for r in rows:
        if skip_col and (r.get(skip_col) or "").strip() in skip:
            continue
        if missing:
            r = dict((k, "" if (v or "").strip() in missing else v) for k, v in r.items())
        out.append(r)
    return {"headers": headers, "rows": out, "delimiter": delim,
            "signature": sorted(set(headers))}


def _blank(rec):
    return not any((c or "").strip() for c in rec)


def _read_long(recs, o):
    start = o["header_row"] - 1
    if start >= len(recs):
        return [], []
    headers = _unique(recs[start])
    rows = []
    for rec in recs[start + 1:]:
        if _blank(rec):
            continue
        rows.append(dict((h, rec[i] if i < len(rec) else "") for i, h in enumerate(headers)))
    return headers, rows


def _read_wide(recs, o):
    """Two header rows: groups (a compound's columns, or the injection's own)
    over field names."""
    start = o["header_row"] - 1
    if start + 1 >= len(recs):
        return [], []
    groups, fields = recs[start], recs[start + 1]
    comp_re = _compile(o["group_pattern"], "The group pattern")
    attach_re = _compile(o["attach_pattern"], "The attached-group pattern")
    strip_re = _compile(o["strip_pattern"], "The name pattern to remove")
    if comp_re is None or "compound" not in comp_re.groupindex:
        raise ValueError('A wide layout needs a group pattern with a (?P<compound>...) group')
    # each column: (compound or None, field name)
    plan, current, compound = [], "", None
    for i in range(max(len(groups), len(fields))):
        g = (groups[i] if i < len(groups) else "").strip()
        f = (fields[i] if i < len(fields) else "").strip()
        if g:
            current = g
            m = comp_re.match(g)
            if attach_re is not None and attach_re.search(g):
                pass                                   # stays with the compound before it
            elif m:
                compound = m.group("compound").strip()
                if strip_re is not None:
                    compound = strip_re.sub("", compound).strip()
            else:
                compound = None                        # the injection's own columns
        plan.append((compound if current else None, f))
    own = [(i, f) for i, (c, f) in enumerate(plan) if c is None and f]
    compounds = []
    for c, _f in plan:
        if c is not None and c not in compounds:
            compounds.append(c)
    own_names = _unique([f for _i, f in own])
    comp_fields = []
    for c, f in plan:
        if c is not None and f and f not in comp_fields:
            comp_fields.append(f)
    headers = own_names + [COMPOUND] + [f for f in comp_fields if f not in own_names]
    rows = []
    for rec in recs[start + 2:]:
        if _blank(rec):
            continue
        base = dict((name, rec[i] if i < len(rec) else "") for (i, _f), name in zip(own, own_names))
        for comp in compounds:
            r = dict(base)
            r[COMPOUND] = comp
            for i, (c, f) in enumerate(plan):
                if c == comp and f:
                    r[f] = rec[i] if i < len(rec) else ""
            rows.append(r)
    return headers, rows


def _read_blocks(recs, o, delim):
    """One block per compound: its start line, its header, its rows."""
    start_re = _compile(o["block_pattern"], "The block pattern")
    if start_re is None or "compound" not in start_re.groupindex:
        raise ValueError('A block layout needs a block pattern with a (?P<compound>...) group')
    headers, rows = [], []
    comp, header = None, None
    for rec in recs:
        line = delim.join(rec)
        m = start_re.match(line)
        if m:
            comp, header = m.group("compound").strip(), None
            continue
        if comp is None:
            continue                                   # the preamble
        if _blank(rec):
            if header is not None:
                comp, header = None, None              # the block has ended
            continue
        if header is None:
            if len(rec) < 2:
                continue
            header = _unique(rec)
            for h in header:
                if h not in headers and not h.startswith("Unnamed: "):
                    headers.append(h)
            continue
        r = dict((h, rec[i] if i < len(rec) else "") for i, h in enumerate(header)
                 if not h.startswith("Unnamed: "))
        r[COMPOUND] = comp
        rows.append(r)
    return [COMPOUND] + headers, rows


def signature(text, opts=None):
    """The column names a text has when read with the reader options; None
    when it cannot be read that way."""
    try:
        got = read(head(text), opts)
    except ValueError:
        return None
    return set(got["headers"]) if got["headers"] else None


# ── matching a file to a profile ─────────────────────────────────────────────

_BRACKET_TAIL = re.compile(r"\s*[\(\[][^\(\)\[\]]*[\)\]]\s*$")


def _base_key(header):
    """A header as it is compared: case, a byte-order mark, punctuation and
    whitespace (around and inside) do not count."""
    s = ("%s" % (header or "")).replace("﻿", "")
    return " ".join(re.sub(r"[\W_]+", " ", s.lower(), flags=re.U).split())


def keys(headers):
    """{header: key} for one set of column names: _base_key, and without a
    trailing bracketed part (a unit, "Amount (ng/mL)") where no other column
    of the same set then reads the same."""
    headers = [h for h in headers or () if h is not None]
    base = dict((h, _base_key(h)) for h in headers)
    short = dict((h, _base_key(_BRACKET_TAIL.sub("", "%s" % h))) for h in headers)
    taken = {}
    for h in headers:
        taken.setdefault(short[h], set()).add(h)
        taken.setdefault(base[h], set()).add(h)
    out = {}
    for h in headers:
        s = short[h]
        out[h] = s if (s and s != base[h] and taken.get(s) == set([h])) else base[h]
    return out


def mapped_columns(profile, fields):
    return set(h for h, f in (profile.get("map") or {}).items() if f in fields)


def required_fields(profile):
    """The fields a file must have a column for to be read with this layout:
    injection and compound, the layout's own "also required" fields, and a
    result (any one of RESULT_FIELDS it maps)."""
    extra = [f for f in (profile.get("required") or []) if f]
    return list(NEED) + [f for f in extra if f not in NEED]


def resolve_map(profile, headers):
    """{file column: field}: the layout's mapping applied to a file's columns,
    each found by its name, else by its key (keys) where exactly one file
    column has it."""
    cmap = profile.get("map") or {}
    fk = keys(headers)
    pk = keys(list(cmap) + list(profile.get("signature") or []))
    by_key = {}
    for h, k in fk.items():
        by_key.setdefault(k, []).append(h)
    out = {}
    for col, field in cmap.items():
        if col in fk:
            out[col] = field
            continue
        hits = by_key.get(pk.get(col, _base_key(col))) or []
        if len(hits) == 1 and hits[0] not in cmap:
            out[hits[0]] = field
    return out


def assess(profile, file_headers):
    """How a file's columns fit a layout: {"fit": bool, "matched": n,
    "unmatched": n, "missing": [(field, the layout's column)]}. A layout
    "within" (the default) fits when every required field and a result
    column it maps are found; extra and other missing columns are
    tolerated. "exact" asks for the same columns (by key)."""
    want = list(profile.get("signature") or [])
    fk = set(keys(file_headers).values())
    pk = set(keys(want).values())
    out = {"fit": False, "matched": len(fk & pk), "unmatched": len(fk - pk) + len(pk - fk), "missing": []}
    if not fk or not pk:
        return out
    if (profile.get("match") or "within") == "exact":
        out["fit"] = fk == pk
        if not out["fit"]:
            out["missing"] = [("", h) for h, k in sorted(keys(want).items()) if k not in fk]
        return out
    got = resolve_map(profile, file_headers)
    have = set(got.values())
    cmap = profile.get("map") or {}
    mapped = set(cmap.values())
    # a field the layout maps no column to is read under its canonical
    # header (an earlier pass-through profile); the worker refuses an export
    # it then reads no row of
    for f in required_fields(profile):
        if f in mapped and f not in have:
            cols = [h for h, v in cmap.items() if v == f]
            out["missing"].append((f, cols[0]))
    results = [f for f in RESULT_FIELDS if f in mapped]
    if results and not have & set(results):
        out["missing"].append((" or ".join(results), ", ".join(
            h for h, v in sorted(cmap.items()) if v in results)))
    out["fit"] = not out["missing"]
    return out


def closest_headers(name, headers, n=3):
    """The file's columns nearest to a layout's column name (by key)."""
    import difflib
    fk = keys(headers)
    by = {}
    for h, k in fk.items():
        by.setdefault(k, h)
    near = difflib.get_close_matches(_base_key(name), list(by), n=n, cutoff=0.4)
    return [by[k] for k in near]


def match(profiles, text_head, instrument_uid=""):
    """The one active profile a file's head fits best (its columns as each
    profile reads them; on the run's instrument, or bound to none). Ranked:
    bound to the run's instrument first, then the most columns matched, then
    the fewest unmatched. Raises LayoutRefused naming why: a tie between
    the best, or none fits -- then naming, for the closest layout, each
    missing column and the nearest headers the file has (the refusal's
    .closest and .headers let Import Studio start from what was found)."""
    fits, near, read_as = [], [], {}
    for p in profiles:
        if p.get("retired"):
            continue
        bound = p.get("instrument_uid") or ""
        if bound and instrument_uid and bound != instrument_uid:
            continue
        sig = signature(text_head, p.get("reader"))
        if not sig:
            continue
        read_as[p.get("name") or p.get("id")] = sig
        a = assess(p, sig)
        rank = 0 if (bound and bound == instrument_uid) else 1
        score = (rank, -a["matched"], a["unmatched"])
        (fits if a["fit"] else near).append((score, p, a, sig))
    if fits:
        fits.sort(key=lambda x: x[0])
        top = [x for x in fits if x[0] == fits[0][0]]
        if len(top) == 1:
            return top[0][1]
        raise LayoutRefused(
            "The file fits %d import layouts equally well (%s): make their columns or "
            "instruments differ in Import Studio." % (
                len(top), ", ".join(x[1].get("name") or x[1].get("id") for x in top)))
    if near:
        near.sort(key=lambda x: (-x[2]["matched"], x[2]["unmatched"], x[0][0]))
        _s, p, a, sig = near[0]
        parts = []
        for field, col in a["missing"]:
            close = closest_headers(col or field, sig)
            parts.append("%s%s (closest in the file: %s)" % (
                field or col, (' -- the layout\'s column "%s"' % col) if (col and field) else "",
                ", ".join(close) or "none"))
        exc = LayoutRefused(
            "No import layout fits this file. The closest, \"%s\", needs: %s. Map the file in "
            "Import Studio." % (p.get("name") or p.get("id"), "; ".join(parts)))
        exc.closest, exc.headers = p, sorted(sig)
        raise exc
    cols = sorted(set().union(*read_as.values())) if read_as else []
    raise LayoutRefused(
        "No import layout matches this file (its columns, as the saved layouts read it: "
        "%s). Set up its layout in Import Studio." % (", ".join(cols[:12]) +
                                                      (" ..." if len(cols) > 12 else "") or "none"))


# ── the profile, from Import Studio's form ───────────────────────────────────

def parse_value_maps(text):
    """"field: from = to" per line -> {field: {from: to}}."""
    out = {}
    for line in (text or "").splitlines():
        m = re.match(r"^\s*([a-z_]+)\s*:\s*(.*?)\s*=\s*(.*?)\s*$", line)
        if m:
            out.setdefault(m.group(1), {})[m.group(2)] = m.group(3)
    return out


def format_value_maps(maps):
    return "\n".join("%s: %s = %s" % (f, a, b) for f in sorted(maps or {})
                     for a, b in sorted((maps or {})[f].items()))


def parse_scales(text):
    """"field = factor" per line ("percent" = 0.01) -> {field: factor}."""
    out = {}
    for line in (text or "").splitlines():
        m = re.match(r"^\s*([a-z_]+)\s*=\s*(\S+)\s*$", line)
        if not m:
            continue
        v = m.group(2).lower()
        if v in ("percent", "%"):
            out[m.group(1)] = 0.01
        else:
            try:
                out[m.group(1)] = float(v)
            except ValueError:
                pass
    return out


def format_scales(scales):
    return "\n".join("%s = %s" % (f, "percent" if v == 0.01 else "%g" % v)
                     for f, v in sorted((scales or {}).items()))


def build_profile(form, duplicate_targets=None):
    """(profile, [problems]) from Import Studio's save form (flat values)."""
    f = dict((k, v) for k, v in (form or {}).items())
    problems = []

    def text(k):
        return ("%s" % (f.get(k) or "")).strip()

    reader = options(dict((k, f.get(k)) for k in READER_DEFAULTS if k in f))
    for k, what in (("group_pattern", "The group pattern"), ("attach_pattern", "The attached-group pattern"),
                    ("strip_pattern", "The name pattern to remove"), ("block_pattern", "The block pattern")):
        try:
            _compile(reader.get(k) or "", what)
        except ValueError as exc:
            problems.append("%s" % exc)
    try:
        col_map = json.loads(f.get("col_map_json") or "{}")
    except (TypeError, ValueError):
        col_map = {}
        problems.append("The column mapping could not be read.")
    try:
        sig = json.loads(f.get("signature_json") or "[]")
    except (TypeError, ValueError):
        sig = []
    if not text("layout_name"):
        problems.append("Give the layout a name.")
    if not sig:
        problems.append("The file's columns are not known: upload the export to set up its layout.")
    used = set(v for v in col_map.values() if v and v != "ignore")
    also = [x.strip() for x in re.split(r"[,\n]", text("required_fields")) if x.strip()]
    lacking = [n for n in list(NEED) + also if n not in used]
    if not used & set(RESULT_FIELDS):
        lacking.append(" or ".join(RESULT_FIELDS))
    if lacking:
        problems.append("Assign a column to %s." % ", ".join(lacking))
    if duplicate_targets is not None:
        dupes = duplicate_targets(col_map)
        if dupes:
            problems.append("Two columns assigned to the same field (one would be discarded on "
                            "import): %s." % "; ".join("%s: %s" % (t, ", ".join(c))
                                                       for t, c in sorted(dupes.items())))
    profile = {
        "id": text("layout_id"), "name": text("layout_name"), "instrument_uid": text("instrument_uid"),
        "reader": reader, "signature": sorted(set(sig)),
        "match": text("match") if text("match") in dict(MATCH_MODES) else "within",
        "required": also,
        "map": col_map, "calc_mode": text("calc_mode") or "final",
        "manual_markers": text("manual_markers"), "date_format": text("date_format"),
        "value_maps": parse_value_maps(f.get("value_maps") or ""),
        "scales": parse_scales(f.get("scales") or ""),
        "qualifier_suffix": "%s" % (f.get("qualifier_suffix") or ""),
        "labelled_from_columns": bool(f.get("labelled_from_columns")),
        "notes": text("notes"), "software": text("software"), "retired": False,
    }
    return profile, problems


# ── what the worker applies after the mapping ────────────────────────────────

def apply_values(record, profile):
    """A record keyed by canonical field, with the profile's value maps (a
    word the export uses -> the platform's) and scales (a percent ratio ->
    a fraction) applied. Cells stay text."""
    maps = (profile or {}).get("value_maps") or {}
    scales = (profile or {}).get("scales") or {}
    out = dict(record)
    for field, table in maps.items():
        v = out.get(field)
        if v is not None and v == v and ("%s" % v).strip() in table:
            out[field] = table[("%s" % v).strip()]
    for field, factor in scales.items():
        v = out.get(field)
        if v is None or v != v or not ("%s" % v).strip():
            continue                                   # empty (a NaN is never equal to itself)
        parts = []
        for part in ("%s" % v).split("|"):
            try:
                parts.append(repr(float(part.strip()) * float(factor)))
            except ValueError:
                parts.append(part)
        out[field] = "|".join(parts)
    return out


# ── the profiles saved before layouts existed ────────────────────────────────

def migrate_legacy(saved, known_headers=(), instrument_uid="", where=""):
    """Layout profiles from the "vendor:version" store (json text per key):
    each read as one comma-separated header row, its columns those it mapped
    plus the canonical headers the importer always understood, matched
    "within" (a file with fewer columns of the same layout), bound to no
    instrument; retired stays retired.

    With `instrument_uid`: an instrument's own store (keyed by version),
    which the worker never read; each is kept as a RETIRED layout bound to
    that instrument (`where` names it), so nothing it held is lost and
    nothing it held starts matching files."""
    out = []
    for n, key in enumerate(sorted(saved)):
        try:
            data = json.loads(saved[key])
        except (TypeError, ValueError):
            continue
        vendor, _sep, version = ("%s" % key).partition(":")
        if instrument_uid:
            vendor, version = data.get("vendor_key") or "", "%s" % key
        m = data.get("map") or {}
        out.append({
            "id": "layout-%d" % (n + 1),
            "name": "%s %s (from the earlier profile %s%s)" % (
                data.get("vendor") or vendor, version or "(any version)", key,
                (" of %s" % where) if where else ""),
            "instrument_uid": instrument_uid, "reader": dict(READER_DEFAULTS, delimiter="comma"),
            "signature": sorted(set(m) | set(known_headers)), "match": "within",
            "map": m, "calc_mode": data.get("calc_mode") or "final",
            "manual_markers": data.get("manual_markers") or "", "date_format": "",
            "value_maps": {}, "scales": {}, "qualifier_suffix": "", "labelled_from_columns": False,
            "notes": data.get("notes") or "", "software": "%s %s" % (vendor, version),
            "retired": bool(data.get("retired")) or bool(instrument_uid),
            "migrated_from": ("%s %s" % (where, key)).strip() if instrument_uid else key,
        })
    return out
