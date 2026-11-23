# -*- coding: utf-8 -*-
"""Starting layouts for the two label kinds, one per stock size.

    label_starter(width, height)             a reagent / standard label
    extraction_label_starter(width, height)  an extraction batch member's label
    uses_qr(width)           stock too narrow for a Code 128 of the longest code
    fit(field, value)        how pdfme draws a value in a text field: the
                             font size it settles on, the lines, whether it
                             stays inside the box
    code128_symbols(value)   the symbol characters a Code 128 of a value has
    bar_width(field, value)  the narrowest bar a code128 field draws, in mm
    longest_code(field)      the longest value of capitals and digits whose
                             bars stay MIN_BAR wide in that field
    qr_modules(value)        the modules across a QR code of a value
    module_size(field, value) one QR module, in mm

Every size has the same zones in the same reading order: the identity line
(the lot, or the injection name, large and bold, with the expiry beside it
on the reagent label), a rule, the code, then the other fields as small
grey captions over their values on one grid whose columns share their left
edges. Stock too small for a field leaves the field out rather than print
it small: nothing is set under 5 pt. The code is a Code 128 across the
label where its bars keep MIN_BAR with the quiet zones, else a QR code of
the same value whose modules keep MIN_MODULE with a quiet zone of
QR_QUIET modules. Every value shrinks to its box (pdfme's dynamic font
size) and a long one wraps, so nothing is cut.

A starting layout is a DRAFT the designer offers: nothing prints from it
until the laboratory issues it under Document Templates. Pure: Python 2.7
and 3.
"""
from __future__ import absolute_import, division, unicode_literals

from senaite.pfas import doc_fields as _df
from senaite.pfas import pdf_layout as _pl

BOLD = "Nunito Sans Bold"
# the narrowest bar a label printer and a hand scanner both handle
MIN_BAR = 0.25
# pdfme changes a dynamic font size in steps of this many points
STEP = 0.25
# of a font size: the room under a line's baseline box for its descenders
DESCENT = 0.3
# mm kept clear above the bars, and half as much again under them
BAR_GAP = 0.6
# the longest code (lot or injection name) a label is drawn for, in characters
CODE_LENGTH = 15
# Code 128 keeps a clear zone of this many bars each side
BAR_QUIET = 10
# the smallest QR module a label printer and a phone camera both handle, and
# the clear zone each side in modules
MIN_MODULE = 0.33
QR_QUIET = 4
# data bytes a QR code holds at error level M, by version 1, 2, 3 ...
QR_BYTES = (14, 26, 42, 62, 84, 106, 122, 152, 180, 213)
# the margin kept clear on every side but the top and bottom, and those
SIDE = 3.0
SIDE_XS = 2.5
VERTICAL = 2.0
# the widest bars a Code 128 is drawn with, so that the margin stays a clear
# zone of BAR_QUIET bars on wide stock
MAX_BAR = 0.3
GREY = "#555555"



# ── measuring, as pdfme does ───────────────────────────────────────────────

def _line_mm(size, font_name=None):
    """The height of a one-line text box at a font size."""
    return _pl.pt2mm(_pl.height_of_font(_pl.font(font_name), size))


def _extent(field, value, size):
    """(widest line mm, total height mm, lines) of a value at a font size."""
    fnt = _pl.font(field.get("fontName"))
    spacing = field.get("characterSpacing") or 0
    lh = field.get("lineHeight") or 1
    lines = _pl.wrap_lines(value, fnt, size, spacing, _pl.mm2pt(field["width"]))
    fit_to = (field.get("dynamicFontSize") or {}).get("fit") or "vertical"
    measured = value.split("\n") if fit_to == "horizontal" else lines
    wide = max([_pl.pt2mm(_pl.width_of_text(t, fnt, size, spacing)) if t else 0 for t in measured] or [0])
    high = sum(_pl.pt2mm((_pl.height_of_font(fnt, size) if i == 0 else size) * lh)
               for i in range(len(lines)))
    return wide, high, lines


def fit(field, value):
    """How pdfme draws `value` in the text field: {"size": the font size it
    settles on, "lines", "width", "height" (mm of text), "fits": the text
    stays inside the box}. A field without a dynamic font size keeps its
    own; one with it shrinks in STEP points until the text fits or the
    floor is reached."""
    value = "%s" % (value if value is not None else "")
    size = field.get("fontSize") or 13
    dyn = field.get("dynamicFontSize")
    if dyn and dyn["max"] >= dyn["min"]:
        size = min(max(size, dyn["min"]), dyn["max"])
        wide, high, lines = _extent(field, value, size)
        while size > dyn["min"] and size > 0 and (wide > field["width"] or high > field["height"]):
            size -= STEP
            wide, high, lines = _extent(field, value, size)
    else:
        wide, high, lines = _extent(field, value, size)
    return {"size": size, "lines": lines, "width": wide, "height": high,
            "fits": wide <= field["width"] + _pl.EPSILON and high <= field["height"] + _pl.EPSILON}


def code128_symbols(value):
    """The symbol characters between the start and the check character of
    the shortest Code 128 of a value: a character is one symbol (code set
    B), two digits are one (code set C), and each change of set costs one."""
    value = "%s" % (value or "")
    far = len(value) + 1
    b, c = 0, 0                      # the fewest symbols so far, ending in each set
    two_back = (0, 0)
    for i, ch in enumerate(value):
        pair = i >= 1 and value[i - 1:i + 1].isdigit() and ord(value[i - 1]) < 128 and ord(ch) < 128
        in_b = min(b, c + 1) + 1
        in_c = (min(two_back[1], two_back[0] + 1 if i > 1 else two_back[0]) + 1) if pair else far * 4
        two_back = (b, c)
        b, c = in_b, in_c
    return min(b, c) if value else 0


def code128_modules(value):
    """The modules across a Code 128 of a value: 11 for each of the start,
    the symbols and the check character, 13 for the stop."""
    return 11 * (code128_symbols(value) + 2) + 13


def bar_width(field, value):
    """The narrowest bar, in mm, of a value in a code128 field: the field's
    width is shared by the modules (the bars are stretched to the box)."""
    return float(field["width"]) / code128_modules(value)


def longest_code(field):
    """How many capitals, hyphens or odd digits a value may have before
    its bars in this field fall under MIN_BAR."""
    return int((float(field["width"]) / MIN_BAR - 35) // 11)




def qr_modules(value):
    """The modules across a QR code of a value (the largest data size: a
    byte of each character, error level M)."""
    n = len("%s" % (value or ""))
    for version, room in enumerate(QR_BYTES, 1):
        if n <= room:
            return 17 + 4 * version
    raise ValueError("a QR code of %d characters is not drawn" % n)


def module_size(field, value):
    """One module of a qrcode field, in mm: the box is shared by the modules."""
    return float(field["width"]) / qr_modules(value)


CODE_SAMPLE = "X" * CODE_LENGTH


def uses_qr(width):
    """Whether stock of this width takes a QR code in place of the Code 128:
    the bars of the longest code across the width between the margins would
    be narrower than MIN_BAR."""
    return (float(width) - 2 * SIDE) / code128_modules(CODE_SAMPLE) < MIN_BAR


# ── drawing ────────────────────────────────────────────────────────────────

# the type sizes of a stock class, in pt: the identity line, a caption, a value
TIERS = {
    "xs": {"ident": 8.0, "cap": 5.0, "val": 6.5, "bars": 0, "qr": 13.0},
    "sm": {"ident": 10.0, "cap": 5.0, "val": 7.0, "bars": 7.0, "qr": 12.5},
    "md": {"ident": 12.0, "cap": 5.5, "val": 8.0, "bars": 9.0, "qr": 16.0},
    "lg": {"ident": 16.0, "cap": 6.0, "val": 10.0, "bars": 12.0, "qr": 18.0},
}
FLOOR = 5.5            # the smallest a value is set
LEAST_BARS = 5.0       # the lowest Code 128 a scanner reads, in mm
CAP_GAP = 0.15         # mm between a caption and its value
ROW_GAP = {"xs": 0.8, "sm": 0.8, "md": 1.2, "lg": 1.6}
GAP = 2.0              # mm between the cells of a row

CAPTIONS = {"lot": "Lot", "exp": "Expiry", "name": "Name", "conc": "Concentration", "vol": "Volume",
            "method": "Method", "date": "Prepared", "analyst": "Prepared by", "storage": "Storage",
            "injection": "Injection", "worksheet": "Worksheet", "batch": "Batch",
            "container": "Container", "role": "QC type", "sample_id": "Sample",
            "client_sid": "Client sample ID", "parent": "Made from", "level": "Spike level",
            "matrix": "Matrix"}
EXTRACTION_CAPTIONS = dict(CAPTIONS, date="Issued", analyst="Issued by")

# the other fields, row by row, for a grid of 1, 2 or 3 columns: (key, columns
# spanned, lines). Whole rows are left out from the bottom when they do not fit.
LABEL_ROWS = {
    1: [[("name", 1, 3)], [("conc", 1, 1)], [("vol", 1, 1)], [("method", 1, 1)], [("date", 1, 1)],
        [("analyst", 1, 1)], [("storage", 1, 2)]],
    2: [[("name", 2, 3)], [("conc", 1, 1), ("vol", 1, 1)], [("method", 2, 1)],
        [("date", 1, 1), ("analyst", 1, 1)], [("storage", 2, 2)]],
    3: [[("name", 3, 2)], [("conc", 1, 1), ("vol", 1, 1), ("date", 1, 1)],
        [("method", 2, 1), ("analyst", 1, 1)], [("storage", 3, 2)]],
}
EXTRACTION_ROWS = {
    1: [[("role", 1, 2)], [("container", 1, 1)], [("sample_id", 1, 1)], [("client_sid", 1, 2)],
        [("parent", 1, 1)], [("level", 1, 1)], [("batch", 1, 1)], [("matrix", 1, 1)],
        [("method", 1, 1)], [("date", 1, 1)], [("analyst", 1, 1)]],
    2: [[("role", 2, 2)], [("container", 1, 1), ("sample_id", 1, 1)], [("client_sid", 2, 2)],
        [("parent", 1, 1), ("level", 1, 1)], [("batch", 1, 1), ("matrix", 1, 1)], [("method", 2, 1)],
        [("date", 1, 1), ("analyst", 1, 1)]],
    3: [[("role", 2, 2), ("container", 1, 1)], [("sample_id", 1, 1), ("client_sid", 2, 2)],
        [("parent", 1, 1), ("level", 1, 1), ("batch", 1, 1)], [("matrix", 1, 1), ("method", 2, 1)],
        [("date", 1, 1), ("analyst", 1, 1)]],
}
# what each kind puts beside its identity: the key, the longest value drawn
LABEL_SPEC = {"code": "lot", "second": ("exp", "2027-12-31"), "rows": LABEL_ROWS, "captions": CAPTIONS,
              "ident": "DEMO-LOT-0001-A"}
EXTRACTION_SPEC = {"code": "injection", "second": ("worksheet", "WS-005"), "rows": EXTRACTION_ROWS,
                   "captions": EXTRACTION_CAPTIONS, "ident": "WS-005-LFSMD1"}


def _r(v):
    return round(v, 2)


def _pt(size):
    """A font size on pdfme's own quarter-point steps."""
    return round(size * 4.0) / 4.0


def tier(width, height):
    """The stock class: xs (a square inch), sm (one inch or a little more
    in the short side), md, lg."""
    if width < 30.0:
        return "xs"
    if min(width, height) <= 32.0:
        return "sm"
    if width < 90.0 or min(width, height) < 45.0:
        return "md"
    return "lg"


class _Sheet(object):
    """One label drawn from the top, in the same zones for every size."""

    def __init__(self, width, height, spec):
        self.width, self.height = float(width), float(height)
        self.spec, self.tier = spec, tier(width, height)
        self.t = TIERS[self.tier]
        self.side = SIDE_XS if self.tier == "xs" else SIDE
        self.span = self.width - 2 * self.side
        self.bottom = self.height - VERTICAL
        self.row_gap = ROW_GAP[self.tier]
        self.fields = []

    # cells: a caption over its value
    def cap_h(self):
        return _line_mm(self.t["cap"]) + DESCENT * _pl.pt2mm(self.t["cap"])

    def val_h(self, size, lines=1, bold=False):
        size = _pt(size)
        return (_line_mm(size, BOLD if bold else None) + (lines - 1) * _pl.pt2mm(size)
                + DESCENT * _pl.pt2mm(size))

    def cell_h(self, size, lines=1, bold=False):
        return self.cap_h() + CAP_GAP + self.val_h(size, lines, bold)

    def cell(self, key, x, y, w, size, lines=1, bold=False, floor=FLOOR, high=None, caption=True):
        """A caption over the value of a data field (no caption on a square
        inch's identity line); the height it takes."""
        size = _pt(size)
        h = high or self.val_h(size, lines, bold)
        ch = self.cap_h() if caption else 0.0
        if caption:
            f = _caption(key, self.spec["captions"].get(key, key), x, y, w, ch, _pt(self.t["cap"]))
            f["fontColor"] = GREY
            self.fields.append(f)
        self.fields.append(_value(key, x, y + ch + (CAP_GAP if caption else 0.0), w, h, size, floor,
                                  bold=bold, wrap=lines > 1))
        return ch + (CAP_GAP if caption else 0.0) + h

    def inline_cell(self, key, x, y, w, size):
        """A caption before its bold value on one line, for the row under
        a square inch's code; the height it takes."""
        cap, size = _pt(self.t["cap"]), _pt(size)
        text = self.spec["captions"].get(key, key)
        tw = _pl.pt2mm(_pl.width_of_text(text, _pl.font(None), cap, 0)) + 0.9
        h = self.val_h(size, 1, True)
        f = _caption(key, text, x, y, tw - 0.6, h, cap)
        f["fontColor"] = GREY
        f["verticalAlignment"] = "bottom"
        self.fields.append(f)
        self.fields.append(_value(key, x + tw, y, w - tw, h, size, _pt(size * 0.8), bold=True))
        return h

    def natural(self, text, size):
        return _pl.pt2mm(_pl.width_of_text(text, _pl.font(BOLD), _pt(size), 0))

    # zone 1: the identity line
    def identity(self, second=True):
        key = self.spec["code"]
        skey, sample = self.spec["second"]
        size = self.t["ident"]
        floor = _pt(size * 0.65)
        # the largest identity that leaves the second cell its width at four
        # fifths of the size: on narrow stock both come down together
        while second and size > floor and (
                self.natural(self.spec["ident"], size) + GAP
                + self.natural(sample, _pt(size * 0.8)) + 1.0 > self.span):
            size -= STEP
        ssize = _pt(size * 0.8)
        high = self.val_h(self.t["ident"], 1, True)
        sw = self.natural(sample, ssize) + 1.0 if second else 0.0
        pw = self.span - (sw + GAP if second else 0.0)
        cap = self.tier != "xs"
        h = self.cell(key, self.side, self.y, pw, size, bold=True, floor=_pt(size * 0.65), high=high,
                      caption=cap)
        if second:
            self.cell(skey, self.side + self.span - sw, self.y, sw, ssize, bold=True,
                      floor=_pt(ssize * 0.8), high=high, caption=cap)
        self.y += h

    def rule(self):
        self.y += 0.8
        self.fields.append({"name": "rule", "type": "line", "position": {"x": _r(self.side), "y": _r(self.y)},
                            "width": _r(self.span), "height": 0.3, "readOnly": True, "color": "#000000"})
        self.y += 0.3

    # zone 3: the other fields on one grid
    def grid(self, x, y, w, limit, ncols, measure=False):
        """Whole rows from the top down while they fit above `limit`:
        (height used, the fields drawn). The columns of every row share
        their left edges."""
        gap = GAP
        colw = (w - gap * (ncols - 1)) / ncols
        used, drawn = 0.0, []
        mark = len(self.fields)
        for row in self.spec["rows"][ncols]:
            cells = []
            for key, span, lines in row:
                cells.append((key, span, lines))
            top = y + used + (self.row_gap if used else 0.0)
            col, placed, rh = 0, [], 0.0
            for key, span, lines in cells:
                lines = self._lines(key, lines, limit - top)
                rh = max(rh, self.cell_h(self.t["val"], lines))
                placed.append((key, col, span, lines))
                col += span
            if top + rh > limit + 1e-6:
                break
            for key, c, span, lines in placed:
                self.cell(key, x + c * (colw + gap), top, span * colw + (span - 1) * gap, self.t["val"],
                          lines)
                drawn.append(key)
            used = top + rh - y
        if measure:
            del self.fields[mark:]
        return used, drawn

    def _lines(self, key, lines, room):
        """The lines a value is given: those asked for, fewer when the
        room is short (the name is never left out for want of lines)."""
        while lines > 1 and self.cell_h(self.t["val"], lines) > room:
            lines -= 1
        return lines

    def ncols(self, w):
        return 1 if w < 44.0 and self.width < 60 else (2 if w < 80.0 else 3)

    def template(self):
        return {"basePdf": {"width": self.width, "height": self.height, "padding": [0, 0, 0, 0]},
                "schemas": [self.fields]}


def _value(name, x, y, w, h, size, floor, bold=False, wrap=False, align="left"):
    f = _df.text_field(name, _r(x), _r(y), _r(w), _r(h), size, align,
                       dynamicFontSize={"min": floor, "max": size,
                                        "fit": "vertical" if wrap else "horizontal"},
                       verticalAlignment="top" if wrap else "bottom")
    if bold:
        f["fontName"] = BOLD
    return f


def _caption(key, text, x, y, w, h, size):
    return _df.text_field("label_" + key, _r(x), _r(y), _r(w), _r(h), size, "left",
                          readOnly=True, content=text, verticalAlignment="top")


def _bars(key, x, y, w, h):
    """The Code 128 of a data field, beside the text field of the same
    name: bars only."""
    return {"name": "%s (2)" % key, "type": "code128", "position": {"x": _r(x), "y": _r(y)},
            "width": _r(w), "height": _r(h), "content": "", "includetext": False}


def _qr(key, x, y, s):
    """The QR code of a data field, a square."""
    return {"name": "%s (2)" % key, "type": "qrcode", "position": {"x": _r(x), "y": _r(y)},
            "width": _r(s), "height": _r(s), "content": ""}


def _draw(spec, width, height):
    s = _Sheet(width, height, spec)
    key = spec["code"]
    skey = spec["second"][0]
    # a small square has room for the identity alone: the expiry goes under the code
    below = s.tier == "xs" and skey == "exp"
    narrow = s.span < 40.0
    s.y = VERTICAL
    s.identity(second=not narrow)
    s.rule()
    t = s.t
    if uses_qr(width):
        _draw_qr(s, key, skey, below and narrow)
    else:
        _draw_bars(s, key)
    return s.template()


def _draw_bars(s, key):
    start = s.y
    after = 2.0 * BAR_GAP
    ncols = s.ncols(s.span)
    limit = s.bottom
    # the rows that fit with the lowest bars, then the bars as tall as is left
    room = s.grid(s.side, start + BAR_GAP + LEAST_BARS + after, s.span, limit, ncols, measure=True)[0]
    hb = min(s.t["bars"], limit - start - after - BAR_GAP - room - (s.row_gap if room else 0.0))
    hb = max(hb, LEAST_BARS)
    width = min(s.span, MAX_BAR * code128_modules(CODE_SAMPLE))
    s.fields.append(_bars(key, s.side, start + BAR_GAP, width, hb))
    s.grid(s.side, start + BAR_GAP + hb + after, s.span, limit, ncols)


def _draw_qr(s, key, skey, expiry_below):
    """A QR code under the rule at the left margin, with a quiet zone of
    QR_QUIET modules clear all round; the other fields beside it when the
    stock is wide enough, else under it."""
    n = qr_modules(CODE_SAMPLE)
    yr = s.y
    reserve = s.val_h(s.t["ident"] * 0.8, 1, True) if expiry_below else 0.0
    smallest = MIN_MODULE * n

    def fits(size):
        q = QR_QUIET * size / n
        # clear zone above and, with a row under the code, below; the bottom
        # margin is clear zone enough when nothing is printed there
        end = yr + q + size + (q + reserve if expiry_below else 0.0)
        return q <= s.side + 1e-9 and end <= s.bottom + 1e-9

    size = min(s.t["qr"], s.span)
    while size >= smallest - 1e-9 and not fits(size):
        size -= 0.05
    if size < smallest - 1e-9:
        raise ValueError("stock %.0f x %.0f mm is too small for a QR code whose modules keep %.2f mm"
                         % (s.width, s.height, MIN_MODULE))
    q = QR_QUIET * size / n
    s.fields.append(_qr(key, s.side, yr + q, size))
    if expiry_below:
        s.inline_cell(skey, s.side, yr + q + size + q, s.span, s.t["ident"] * 0.8)
        return
    gx = s.side + size + q + 0.6
    gw = s.width - s.side - gx
    if s.tier != "xs" and gw >= 28.0:
        s.grid(gx, yr + 0.8, gw, s.bottom, 1 if gw < 46.0 else 2)
    elif s.tier != "xs":
        s.grid(s.side, yr + q + size + q, s.span, s.bottom, s.ncols(s.span))


def label_starter(width=50.8, height=25.4):
    """Lot and expiry, the lot's code, then the name, concentration, volume,
    method, preparation and storage, as far as the stock takes them."""
    return _draw(LABEL_SPEC, width, height)


def extraction_label_starter(width=50.8, height=25.4):
    """The injection name and its code, then the worksheet, container, QC
    type, sample, parent, spike level, batch, matrix, method and issue, as
    far as the stock takes them."""
    return _draw(EXTRACTION_SPEC, width, height)
