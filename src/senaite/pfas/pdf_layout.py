# -*- coding: utf-8 -*-
"""pdfme's page flow, computed here as the renderer computes it, so a table
that breaks across pages never prints over what follows it.

pdfme (6.2.2, the version the renderer and the designer run) lays a page out
item by item: each starts where the one above it ends plus the gap the design
leaves between them. A table whose heading repeats after a page break
reserves room for the repeated heading at the rows where IT would break if it
started at its DESIGNED position; when the paragraphs and tables above it
grow, it starts lower, breaks at other rows, and its repeated heading prints
over the paragraph under it.

settle(template, inputs) computes the flow with each table broken where it
really starts, and writes that flow into the template: every item at the
place it will be printed, and an empty table of no height after each item
that grows or shrinks, whose designed height takes the change back, so pdfme
places the next item exactly there. A page pdfme already lays out right is
left as it is. Text is measured with the lab fonts' own metrics and pdfme's
line breaking (pdf_layout_data, generated from the fonts and the vendored
bundle); a page with anything that cannot be measured (another font, a
script beyond U+3000, combining marks) is left to pdfme.

Pure: Python 2.7 and 3.
"""
from __future__ import absolute_import, division, unicode_literals

import bisect
import copy
import functools
import json
import logging
import math
import unicodedata

from senaite.pfas import pdf_layout_data as _data

PT_TO_MM = 0.3528
MM_TO_PT = 2.8346
EPSILON = 0.01
SAFETY_MARGIN = 0.5
SPACER = "__pfas_flow_"
logger = logging.getLogger("senaite.pfas.pdf_layout")


class Unmeasurable(Exception):
    """Something on the page cannot be measured exactly as pdfme would."""


def pt2mm(pt):
    return pt * PT_TO_MM


def mm2pt(mm):
    return float(mm) * MM_TO_PT


# ── fonts ───────────────────────────────────────────────────────────────────

class _Font(object):
    def __init__(self, spec):
        self.upm = spec["upm"]
        self.ascent = spec["ascent"]
        self.descent = spec["descent"]
        self.bbox_max_y = spec["bbox_max_y"]
        self.bbox_min_y = spec["bbox_min_y"]
        self.notdef = spec["notdef"]
        self.widths = {}
        for first, ws in spec["widths"]:
            for i, w in enumerate(ws):
                self.widths[first + i] = w
        self.ligatures = dict(((a, b), w) for a, b, w in spec["ligatures"])


_FONTS = {}


def font(name):
    """A lab font by the name a field gives (none: the fallback)."""
    key = name or _data.FALLBACK
    if key not in _data.FONTS:
        raise Unmeasurable("font %s" % key)
    if key not in _FONTS:
        _FONTS[key] = _Font(_data.FONTS[key])
    return _FONTS[key]


# white space as JavaScript's \s and trim() know it
_JS_SPACE = frozenset(u"\t\n\x0b\x0c\r \xa0        "
                      u"        　﻿")


def _check(text):
    for ch in text:
        cp = ord(ch)
        if cp >= _data.LIMIT or 0xD800 <= cp <= 0xDFFF or 0x1100 <= cp <= 0x11FF:
            raise Unmeasurable("character U+%04X" % cp)
        cat = unicodedata.category(ch)
        # marks join a character before them (one grapheme, other glyphs);
        # sharp s takes a contextual form after capitals
        if cat[0] == "M" or cat == "Cf" or (cat == "Cc" and ch not in _JS_SPACE) or cp == 0xDF:
            raise Unmeasurable("character U+%04X" % cp)


_WIDTHS = {}


def width_of_text(text, fnt, size, spacing):
    """pdfme's widthOfTextAtSize: the advances of the glyphs fontkit lays
    out (its ligatures, no kerning), plus the character spacing."""
    # a cache shared by the server's threads: a lookup, never a test and a get
    key = (id(fnt), size, spacing, text)
    width = _WIDTHS.get(key)
    if width is not None:
        return width
    if len(_WIDTHS) >= 20000:
        _WIDTHS.clear()
    _WIDTHS[key] = width = _width_of_text(text, fnt, size, spacing)
    return width


def _width_of_text(text, fnt, size, spacing):
    _check(text)
    scale = 1000.0 / fnt.upm
    total = 0
    i, n = 0, len(text)
    while i < n:
        cp = ord(text[i])
        if i + 1 < n and (cp, ord(text[i + 1])) in fnt.ligatures:
            adv = fnt.ligatures[(cp, ord(text[i + 1]))]
            i += 2
        else:
            adv = fnt.widths.get(cp, fnt.notdef)
            i += 1
        total = total + adv * scale
    return total * (size / 1000.0) + (len(text) - 1) * spacing


def height_of_font(fnt, size):
    """pdfme's heightOfFontAtSize (the first line of a text box)."""
    scale = 1000.0 / fnt.upm
    height = (fnt.ascent or fnt.bbox_max_y) * scale - (fnt.descent or fnt.bbox_min_y) * scale
    height -= abs(fnt.descent * scale) or 0
    return height / 1000.0 * size


# ── line breaking (UAX #14 as pdfme implements it) ─────────────────────────

_STARTS = [r[0] for r in _data.LINE_BREAK_RANGES]
DI_BRK, IN_BRK, CI_BRK, CP_BRK, PR_BRK = 0, 1, 2, 3, 4


def _raw_class(cp):
    i = bisect.bisect_right(_STARTS, cp) - 1
    if i >= 0:
        first, last, cls = _data.LINE_BREAK_RANGES[i]
        if first <= cp <= last:
            return cls
    return 42


def _map_class(c):
    if c in (33, 39, 40, 42):
        return 12
    if c == 35:
        return 5
    return c


def _map_first(c):
    if c in (37, 38):
        return 34
    if c == 41:
        return 22
    return c


def uax14_breaks(text):
    """[(position, required)] as pdfme's collectUax14Breaks."""
    if not text:
        return [(0, True)]
    for ch in text:
        if _raw_class(ord(ch)) == 39:
            raise Unmeasurable("a script broken by dictionary")
    breaks = []
    st = {"cur": None, "next": 0, "lb8a": False, "lb21a": False, "lb30a": 0}

    def cls_at(i):
        return _map_class(_raw_class(ord(text[i])))

    def simple():
        nxt = st["next"]
        if nxt == 41:
            return False
        if nxt in (34, 37, 38):
            st["cur"] = 34
            return False
        if nxt == 36:
            st["cur"] = 36
            return False
        return None

    def pair(last):
        if st["cur"] is None:
            return False
        row = _data.PAIR_TABLE[st["cur"]] if st["cur"] < len(_data.PAIR_TABLE) else None
        p = row[st["next"]] if row is not None and st["next"] < len(row) else None
        brk = False
        if p == DI_BRK:
            brk = True
        elif p == IN_BRK:
            brk = last == 41
        elif p == CI_BRK:
            brk = last == 41
            if not brk:
                return False
        elif p == CP_BRK:
            if last != 41:
                return False
        elif p == PR_BRK:
            pass
        else:
            brk = True
        if st["lb8a"]:
            brk = False
        if st["lb21a"] and st["cur"] in (16, 17):
            brk = False
            st["lb21a"] = False
        else:
            st["lb21a"] = st["cur"] == 13
        if st["cur"] == 28:
            st["lb30a"] += 1
            if st["lb30a"] == 2 and st["next"] == 28:
                brk = True
                st["lb30a"] = 0
        else:
            st["lb30a"] = 0
        st["cur"] = st["next"]
        return brk

    first = cls_at(0)
    st["cur"] = _map_first(first)
    st["next"] = first
    st["lb8a"] = first == 31
    i = 1
    while i < len(text):
        last_pos = i
        last = st["next"]
        st["next"] = cls_at(i)
        i += 1
        if st["cur"] == 34 or (st["cur"] == 36 and st["next"] != 37):
            st["cur"] = _map_first(_map_class(st["next"]))
            breaks.append((last_pos, True))
            continue
        brk = simple()
        if brk is None:
            brk = pair(last)
        st["lb8a"] = st["next"] == 31
        if brk:
            breaks.append((last_pos, False))
    breaks.append((len(text), True))
    return breaks


def _atoms(text):
    out, prev = [], 0
    for pos, required in uax14_breaks(text):
        if pos <= prev:
            continue
        out.append((text[prev:pos], required))
        prev = pos
    if prev < len(text):
        out.append((text[prev:], True))
    return out


def _trim_end_index(src, start, end):
    i = end
    while i > start and src[i - 1] in _JS_SPACE:
        i -= 1
    return i


def _skip_leading_space(src, start, end):
    i = start
    while i < end and src[i] in _JS_SPACE:
        i += 1
    return i


def _js_trim(s):
    a, b = 0, len(s)
    while a < b and s[a] in _JS_SPACE:
        a += 1
    while b > a and s[b - 1] in _JS_SPACE:
        b -= 1
    return s[a:b]


def _wrap_paragraph(src, measure_raw, max_width):
    """pdfme's wrapParagraphRanges: [(start, end, hard)]."""
    if src == "":
        return [(0, 0, True)]

    def measure(start, end):
        t = _trim_end_index(src, start, end)
        if t <= start:
            return 0
        return measure_raw(start, t)

    lines = []
    cur = {"start": 0, "end": 0, "has": False}

    def emit(start, end, hard):
        t = _trim_end_index(src, start, end)
        if t <= start:
            if not hard:
                return
            if not lines:
                lines.append((0, 0, True))
                return
            s0, e0, _h = lines[-1]
            lines[-1] = (s0, e0, True)
            return
        lines.append((start, t, hard))

    def flush(hard):
        if not cur["has"]:
            if not hard:
                return
            if not lines:
                lines.append((0, 0, True))
                return
            s0, e0, _h = lines[-1]
            lines[-1] = (s0, e0, True)
            return
        emit(cur["start"], cur["end"], hard)
        cur["has"] = False

    def split_overflow(start, end):
        pieces = []
        piece_start = position = start
        for ch in src[start:end]:
            nxt = position + 1
            if position != piece_start and measure(piece_start, nxt) > max_width:
                pieces.append((piece_start, position))
                piece_start = position
            position = nxt
        if position > piece_start or not pieces:
            pieces.append((piece_start, position))
        return pieces

    def append_overflow(start, end):
        position = start
        if cur["has"]:
            taken = start
            for ch in src[start:end]:
                nxt = taken + 1
                if measure(cur["start"], nxt) > max_width:
                    break
                taken = nxt
            if taken > start:
                cur["end"] = taken
                flush(False)
                position = taken
            else:
                flush(False)
        if position >= end:
            return
        pieces = split_overflow(position, end)
        for ps, pe in pieces[:-1]:
            t = _trim_end_index(src, ps, pe)
            if t <= ps:
                continue
            lines.append((ps, t, False))
        rs, re_ = pieces[-1]
        if _js_trim(src[rs:re_]) == "":
            cur["has"] = False
            return
        cur["start"], cur["end"], cur["has"] = rs, re_, True

    def start_line(start, end):
        if start >= end:
            cur["has"] = False
            return
        if measure(start, end) <= max_width:
            cur["start"], cur["end"], cur["has"] = start, end, True
        else:
            cur["has"] = False
            append_overflow(start, end)

    cursor = 0
    for atom, required in _atoms(src):
        a_start, a_end = cursor, cursor + len(atom)
        cursor = a_end
        if not cur["has"]:
            start_line(a_start, a_end)
        elif measure(cur["start"], a_end) <= max_width:
            cur["end"] = a_end
        elif measure(a_start, a_end) <= max_width:
            flush(False)
            start_line(_skip_leading_space(src, a_start, a_end), a_end)
        else:
            append_overflow(a_start, a_end)
        if required:
            flush(True)
    if cur["has"]:
        flush(True)
    elif not lines:
        lines.append((0, 0, True))
    else:
        s0, e0, _h = lines[-1]
        lines[-1] = (s0, e0, True)
    return lines


_PARAGRAPH = (u"\r\n", u"\r", u"\n", u"\x0c", u"\x0b")


def _paragraphs(value):
    out, start, i = [], 0, 0
    while i < len(value):
        if value.startswith(u"\r\n", i):
            out.append(value[start:i])
            i += 2
            start = i
            continue
        if value[i] in u"\r\n\x0c\x0b":
            out.append(value[start:i])
            i += 1
            start = i
            continue
        i += 1
    out.append(value[start:])
    return out


def _text(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value if isinstance(value, type(u"")) else u"%s" % (value,)


def wrap_lines(value, fnt, size, spacing, box_width_pt):
    """pdfme's splitTextToSize: the lines a value wraps to in a box."""
    value = _text(value or u"")
    lines = []
    for para in _paragraphs(value):
        src = para
        while src and src[-1] in _JS_SPACE:
            src = src[:-1]

        def measure_raw(start, end, src=src):
            text = src[start:end]
            return 0 if not text else width_of_text(text, fnt, size, spacing)
        for start, end, _hard in _wrap_paragraph(src, measure_raw, box_width_pt):
            lines.append(src[start:end])
    return lines or [u""]


# ── heights ─────────────────────────────────────────────────────────────────

def _box(dim):
    d = dim if isinstance(dim, dict) else {}
    return dict((k, d.get(k) or 0) for k in ("top", "right", "bottom", "left"))


def text_heights(schema, value):
    """pdfme's getDynamicLayoutForText: one height, or one per line when
    an expanding text outgrows its box."""
    if schema.get("type") != "text" or schema.get("overflow") != "expand":
        return [schema["height"]], False
    if schema.get("textFormat") == "inline-markdown" and schema.get("readOnly") is True:
        raise Unmeasurable("markdown text")
    fnt = font(schema.get("fontName"))
    size = schema.get("fontSize")
    size = 13 if size is None else size
    lh = schema.get("lineHeight")
    lh = 1 if lh is None else lh
    spacing = schema.get("characterSpacing") or 0
    bw, pad = _box(schema.get("borderWidth")), _box(schema.get("padding"))
    content_w = max(0, schema["width"] - (bw["left"] + pad["left"]) - (bw["right"] + pad["right"]))
    lines = wrap_lines(value, fnt, size, spacing, mm2pt(content_w))
    heights = [pt2mm((height_of_font(fnt, size) if i == 0 else size) * lh) for i in range(len(lines))]
    n = len(heights)
    boxed = [h + ((bw["top"] if i == 0 else 0) + (bw["bottom"] if i + 1 >= n else 0)
                  + (pad["top"] if i == 0 else 0) + (pad["bottom"] if i + 1 >= n else 0))
             for i, h in enumerate(heights)]
    measured = sum(boxed)
    if measured <= schema["height"] or not heights:
        return [schema["height"]], False
    if n == 1:
        return [max(schema["height"], measured)], False
    return boxed, True


def _cell_style(schema, section):
    st = schema.get("headStyles" if section == "head" else "bodyStyles") or {}
    out = {"fontName": None, "lineHeight": 1, "characterSpacing": 0, "fontSize": 10,
           "padding": {"top": 5, "right": 5, "bottom": 5, "left": 5},
           "borderWidth": {"top": 0, "right": 0, "bottom": 0, "left": 0}}
    for k in ("fontName", "lineHeight", "characterSpacing", "fontSize", "padding", "borderWidth"):
        if st.get(k) is not None:
            out[k] = st[k]
    return out


def _cell_height(raw, width, style):
    fnt = font(style["fontName"])
    bw, pad = _box(style["borderWidth"]), _box(style["padding"])
    content_w = max(0, width - (bw["left"] + pad["left"]) - (bw["right"] + pad["right"]))
    lines = wrap_lines(_text(raw), fnt, style["fontSize"], style["characterSpacing"] or 0, mm2pt(content_w))
    h = len(lines) * (pt2mm(style["fontSize"]) * style["lineHeight"]) \
        + (bw["top"] + bw["bottom"] + pad["top"] + pad["bottom"])
    return max(h, 0)


def table_rows(schema, body):
    """(head row heights, body row heights) of a table as pdfme sizes it."""
    head = schema.get("head") or []
    pcts = schema.get("headWidthPercentages") or []
    if not head or len(pcts) != len(head) or any(not p for p in pcts):
        raise Unmeasurable("table columns")
    if (schema.get("columnStyles") or {}).get("cellWidth"):
        raise Unmeasurable("table column widths")
    widths = [schema["width"] * (p / 100.0) for p in pcts]
    hs, bs = _cell_style(schema, "head"), _cell_style(schema, "body")
    head_h = [max([0] + [_cell_height(head[i], widths[i], hs) for i in range(len(head))])]
    body_h = []
    for row in body:
        if not isinstance(row, (list, tuple)) or len(row) < len(head):
            raise Unmeasurable("table row")
        body_h.append(max([0] + [_cell_height(row[i], widths[i], bs) for i in range(len(head))]))
    return head_h, body_h


def table_heights(schema, body, base, y):
    """pdfme's getDynamicHeightsForTable for a table starting at y (mm from
    the top of its first page, counted on through the following pages)."""
    head_h, body_h = table_rows(schema, body)
    show = bool(schema.get("showHead"))
    base_heights = head_h + body_h if show else [0] + body_h
    header = sum(head_h) if show else 0
    if not (schema.get("repeatHead") and header > 0):
        return base_heights
    pad_top, pad_bottom = base["padding"][0], base["padding"][2]
    page_h = base["height"] - pad_top - pad_bottom

    def page_start(i):
        return i * page_h + pad_top

    first_page = max(0, int(math.floor((y - pad_top) / page_h)))
    head_rows = len(head_h) if show else 0
    page, page_y, on_page = first_page, y, 0
    out = []
    for i, row_h in enumerate(base_heights):
        is_body = i >= head_rows
        while True:
            start = page_start(page)
            remaining = start + page_h - page_y
            total = row_h + (header if (is_body and on_page == 0 and page > first_page) else 0)
            if total > remaining - SAFETY_MARGIN:
                if on_page == 0 and abs(page_y - start) < SAFETY_MARGIN:
                    out.append(total)
                    page_y += total
                    on_page += 1
                    break
                page += 1
                page_y = page_start(page)
                on_page = 0
                continue
            out.append(total)
            page_y += total
            on_page += 1
            if page_y >= start + page_h - SAFETY_MARGIN:
                page += 1
                page_y = page_start(page)
                on_page = 0
            break
    return out


# ── the flow (pdfme's getDynamicTemplate, one designed page) ───────────────

def _value(schema, inputs):
    name = schema.get("name")
    if schema.get("type") == "table":
        raw = inputs.get(name) if not schema.get("readOnly") else inputs.get(name, schema.get("content"))
        if raw is None or raw == "":
            raw = "[]" if not schema.get("readOnly") else (schema.get("content") or "[]")
        try:
            return json.loads(raw) if not isinstance(raw, list) else raw
        except ValueError:
            raise Unmeasurable("table value")
    if not schema.get("readOnly"):
        return inputs.get(name) or u""
    content = schema.get("content") or u""
    if schema.get("type") == "text" and schema.get("overflow") == "expand" and "{" in content:
        raise Unmeasurable("placeholders")
    return content


def _js_mod(a, b):
    return math.fmod(a, b)


class Item(object):
    def __init__(self, schema, index, base_y):
        self.schema = schema
        self.index = index
        self.base_y = base_y
        self.height = schema["height"]
        self.heights = [schema["height"]]
        self.avoid_first = False
        self.start = None        # requested start (global, mm below the top padding)
        self.end = None
        self.chunks = []         # [(page, y on the page, height, first unit, end unit)]


def _cmp(a, b):
    if abs(a.base_y - b.base_y) > EPSILON:
        return -1 if a.base_y < b.base_y else 1
    return -1 if a.index < b.index else (1 if a.index > b.index else 0)


def _items(page, pad_top):
    order = {}
    for i, s in enumerate(page):
        order[s.get("name")] = i
    items = [Item(s, i, max(0, s["position"]["y"] - pad_top)) for i, s in enumerate(page)]
    for it in items:
        it.index = order.get(it.schema.get("name"), it.index)
    return sorted(items, key=functools.cmp_to_key(_cmp))


def _place(item, start, page_h, pad_top):
    """pdfme's placeUnitsOnPages: returns the global end."""
    heights = item.heights
    unit = 0
    page = max(0, int(math.floor(start / page_h)))
    y = _js_mod(start, page_h)
    if y < 0:
        y = 0
    end = 0
    splittable = len(heights) > 1
    while unit < len(heights):
        space = page_h - y
        if heights[unit] > space + EPSILON:
            if not abs(space - page_h) <= EPSILON:
                page += 1
                y = 0
                continue
        chunk, first = 0, unit
        while unit < len(heights):
            h = heights[unit]
            if y + chunk + h <= page_h + EPSILON:
                chunk += h
                unit += 1
            else:
                break
        at_top = y <= EPSILON
        if item.avoid_first and splittable and first == 0 and unit == 1 and len(heights) > 1 and not at_top:
            unit = 0
            page += 1
            y = 0
            continue
        if unit == first:
            chunk += heights[unit]
            unit += 1
        item.chunks.append((page, y + pad_top, chunk, first, unit))
        y += chunk
        if y >= page_h - EPSILON:
            page += 1
            y = 0
        end = page * page_h + y
    return end


def flow(page, base, inputs, where_it_starts=False):
    """The items of one designed page as pdfme lays them out. pdfme sizes a
    repeating-heading table from its designed position; where_it_starts sizes
    it from where the flow really starts it."""
    pad_top = base["padding"][0]
    page_h = base["height"] - pad_top - base["padding"][2]
    items = _items(page, pad_top)
    for it in items:
        s = it.schema
        if s.get("type") == "table":
            it.avoid_first = True
            if not where_it_starts:
                it.heights = table_heights(s, _value(s, inputs), base, s["position"]["y"]) or [0]
        elif s.get("type") == "list" or (s.get("type") == "multiVariableText"
                                         and s.get("overflow") == "expand"):
            raise Unmeasurable("a %s that grows" % s.get("type"))
        else:
            it.heights = text_heights(s, _value(s, inputs))[0] if s.get("type") == "text" else [s["height"]]
    offset = 0
    for it in items:
        it.start = it.base_y + offset
        if where_it_starts and it.schema.get("type") == "table":
            it.heights = table_heights(it.schema, _value(it.schema, inputs), base,
                                       it.start + pad_top) or [0]
        it.end = _place(it, it.start, page_h, pad_top)
        offset = it.end - (it.base_y + it.height)
    return items


def _spacer(n, x, y, height):
    """An empty table: it prints nothing and takes no room, and its designed
    height takes back what the item above it grew or shrank by."""
    return {"name": "%s%d" % (SPACER, n), "type": "table", "readOnly": True,
            "position": {"x": x, "y": y}, "width": 1, "height": height,
            "content": "[]", "showHead": False, "repeatHead": False, "head": [""],
            "headWidthPercentages": [100],
            "tableStyles": {"borderColor": "", "borderWidth": 0},
            "headStyles": {"fontSize": 1, "borderWidth": {"top": 0, "right": 0, "bottom": 0, "left": 0},
                           "padding": {"top": 0, "right": 0, "bottom": 0, "left": 0}},
            "bodyStyles": {"fontSize": 1, "borderWidth": {"top": 0, "right": 0, "bottom": 0, "left": 0},
                           "padding": {"top": 0, "right": 0, "bottom": 0, "left": 0}},
            "columnStyles": {}}


def _chunks(items):
    return dict((it.schema.get("name"), [(p, round(y, 6), round(h, 6), f, e) for p, y, h, f, e in it.chunks])
                for it in items if not (it.schema.get("name") or "").startswith(SPACER))


def settle_page(page, base, inputs):
    """The page with each item where the true flow puts it, when pdfme's own
    flow would print a table over what follows it (or past the bottom
    margin); every other page unchanged. A page that would overprint but
    cannot be settled is logged, never silently left."""
    if not any(s.get("type") == "table" and s.get("repeatHead") and s.get("showHead") for s in page):
        return page
    names = ", ".join(s.get("name") or "" for s in page if s.get("type") == "table" and s.get("repeatHead"))
    try:
        as_designed = flow(page, base, inputs)
    except Unmeasurable as exc:
        logger.warning("page flow of %s not checked, left to pdfme: cannot measure %s", names, exc)
        return page
    over = overprints(as_designed, base, inputs)
    if not over:
        return page
    why = "%s prints %.3f mm over %s on page %d" % (over[0][1], over[0][3], over[0][2], over[0][0] + 1)
    try:
        true = flow(page, base, inputs, where_it_starts=True)
    except Unmeasurable as exc:                             # pragma: no cover (as_designed measured it)
        logger.warning("%s; not settled: cannot measure %s", why, exc)
        return page
    pad_top = base["padding"][0]
    last, placed = None, {}
    for it in true:
        if it.start < 0 or (last is not None and it.start < last - EPSILON):
            logger.warning("%s; not settled: the flow would reorder %s", why, it.schema.get("name"))
            return page
        last = it.start
        placed[id(it.schema)] = (it.start, it.end - (it.start + it.height))
    # the designed order is kept (it is the drawing order); each spacer
    # follows its item
    out, n = [], 0
    for schema in page:
        start, grew = placed[id(schema)]
        s = copy.deepcopy(schema)
        s["position"] = dict(s["position"], y=start + pad_top)
        out.append(s)
        if abs(grew) > 1e-9:
            n += 1
            out.append(_spacer(n, s["position"]["x"], s["position"]["y"], grew))
    check = flow(out, base, inputs)
    designed = dict((sc.get("name"), (sc["position"]["y"], sc.get("height") or 0)) for sc in page)
    if _chunks(check) != _chunks(true) or overprints(check, base, inputs, designed):
        logger.warning("%s; not settled: pdfme would not lay the settled page out as computed", why)
        return page
    return out


def settle(template, inputs):
    """The template with every designed page's flow settled (settle_page);
    only a blank page with padding flows."""
    base = template.get("basePdf")
    if not isinstance(base, dict) or not all(k in base for k in ("width", "height", "padding")):
        return template
    t = dict(template)
    t["schemas"] = [_settle_safely(page or [], base, inputs or {}) for page in template.get("schemas") or []]
    return t


def _settle_safely(page, base, inputs):
    """settle_page; anything unforeseen in a design is logged and the page
    prints as designed: settling never stops a document from printing."""
    try:
        return settle_page(page, base, inputs)
    except Exception:                                       # noqa: BLE001
        logger.exception("page flow of %s not settled, printed as designed",
                         ", ".join(s.get("name") or "" for s in page if s.get("type") == "table"))
        return page


def drawn(items, base, inputs):
    """What pdfme draws for each piece of each item, in flow order: dicts of
    page, name, order (in the flow), table, top, bottom, left, right, first
    and end (the piece's units). A table piece after a break draws its
    heading again even where the flow gave it no room for one."""
    out = []
    for order, it in enumerate(items):
        name = it.schema.get("name") or ""
        if name.startswith(SPACER):
            continue
        s = it.schema
        left = s["position"]["x"]
        right = left + (s.get("width") or 0)
        if s.get("type") == "table":
            head_h, body_h = table_rows(s, _value(s, inputs))
            show = bool(s.get("showHead"))
            for page, y, _h, first, end in it.chunks:
                rows = [body_h[i - 1] for i in range(max(first, 1), end)]
                head = sum(head_h) if show and (first == 0 or s.get("repeatHead")) else 0
                out.append({"page": page, "name": name, "order": order, "table": True, "top": y,
                            "bottom": y + head + sum(rows), "left": left, "right": right,
                            "first": first, "end": end})
        else:
            for page, y, h, first, end in it.chunks:
                out.append({"page": page, "name": name, "order": order, "table": False, "top": y,
                            "bottom": y + h, "left": left, "right": right, "first": first, "end": end})
    return out


def overprints(items, base, inputs, designed=None):
    """[(page, table, what, mm)]: each place a drawn table piece runs over
    an item that follows it on its page (beside it, below its top), or past
    the bottom margin, by more than pdfme's own tolerance. Where the design
    itself draws an item over the table's box (a frame, a watermark), only
    a depth beyond the designed one is an overprint. designed: {name: (y,
    height)} as designed, else the items' own places."""
    pieces = drawn(items, base, inputs)
    if designed is None:
        designed = dict((it.schema.get("name"), (it.schema["position"]["y"], it.schema.get("height") or 0))
                        for it in items)
    limit = base["height"] - base["padding"][2]
    out = []
    for p in pieces:
        if not p["table"]:
            continue
        if p["bottom"] > limit + EPSILON:
            out.append((p["page"], p["name"], "the bottom margin", p["bottom"] - limit))
        ty, th = designed.get(p["name"], (None, 0))
        for o in pieces:
            if not (o["page"] == p["page"] and o["order"] > p["order"] and o["left"] < p["right"] - EPSILON
                    and o["right"] > p["left"] + EPSILON and p["top"] - EPSILON <= o["top"] < p["bottom"]):
                continue
            # what the design itself draws over the table (a frame, a
            # watermark, a note dragged a little into it) is no overprint;
            # only what growth adds to that depth is
            oy, oh = designed.get(o["name"], (None, 0))
            by_design = 0
            if ty is not None and oy is not None and oy < ty + th - EPSILON and oy + oh > ty + EPSILON:
                by_design = ty + th - oy
            depth = p["bottom"] - o["top"]
            if depth > by_design + EPSILON:
                out.append((p["page"], p["name"], o["name"], depth))
    return out
