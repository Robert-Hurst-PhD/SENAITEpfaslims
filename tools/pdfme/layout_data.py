#!/usr/bin/env python3
"""Writes src/senaite/pfas/pdf_layout_data.py: what senaite.pfas.pdf_layout
needs to measure text exactly as the renderer's pdfme does.

    python3 tools/pdfme/layout_data.py          (needs fontTools)

From the lab fonts the renderer registers (tools/pdfme/fonts, the same files
as static/fonts/print): each font's advance widths, its vertical metrics and
its two-letter ligatures (fontkit applies "liga"; pdfme sums the advances of
the glyphs fontkit lays out, without kerning). From the vendored pdfme bundle:
the UAX #14 line-break classes and pair table pdfme wraps text with. Only
code points below U+3000 are kept: a text with anything above is not
measured (pdf_layout leaves that page to pdfme).
"""
import io
import os
import re

from fontTools.ttLib import TTFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
FONT_DIR = os.path.join(HERE, "fonts")
BUNDLE = os.path.join(ROOT, "src", "senaite", "pfas", "browser", "static", "vendor", "pdfme",
                      "pdfme.min.js")
OUT = os.path.join(ROOT, "src", "senaite", "pfas", "pdf_layout_data.py")
LIMIT = 0x3000

# the renderer's names for the fonts (tools/pdfme/server.mjs LAB_FONTS); the
# first is the fallback a field with no font draws in
FONTS = [("Nunito Sans", "NunitoSans-Regular.ttf"),
         ("Nunito Sans SemiBold", "NunitoSans-SemiBold.ttf"),
         ("Nunito Sans Bold", "NunitoSans-Bold.ttf"),
         ("Nunito", "Nunito-Regular.ttf"),
         ("Nunito SemiBold", "Nunito-SemiBold.ttf"),
         ("Nunito Bold", "Nunito-Bold.ttf"),
         ("Nunito ExtraBold", "Nunito-ExtraBold.ttf")]


def _runs(widths):
    """{cp: w} as [(first cp, [w, w, ...]), ...] over consecutive code points."""
    out = []
    for cp in sorted(widths):
        if out and out[-1][0] + len(out[-1][1]) == cp:
            out[-1][1].append(widths[cp])
        else:
            out.append((cp, [widths[cp]]))
    return out


def font_metrics(path):
    f = TTFont(path)
    cmap = f.getBestCmap()
    hmtx = f["hmtx"].metrics
    widths = dict((cp, hmtx[g][0]) for cp, g in cmap.items() if cp < LIMIT)
    by_glyph = {}
    for cp, g in cmap.items():
        if cp < LIMIT:
            by_glyph.setdefault(g, cp)
    ligatures = {}
    gsub = f["GSUB"].table if "GSUB" in f else None
    for fr in (gsub.FeatureList.FeatureRecord if gsub else []):
        if fr.FeatureTag != "liga":
            continue
        for li in fr.Feature.LookupListIndex:
            lk = gsub.LookupList.Lookup[li]
            for st in lk.SubTable:
                st = st.ExtSubTable if lk.LookupType == 7 else st
                for first, ligs in (getattr(st, "ligatures", None) or {}).items():
                    for lig in ligs:
                        parts = [first] + list(lig.Component)
                        if len(parts) == 2 and all(p in by_glyph for p in parts):
                            ligatures[(by_glyph[parts[0]], by_glyph[parts[1]])] = hmtx[lig.LigGlyph][0]
    head, hhea = f["head"], f["hhea"]
    return {"upm": head.unitsPerEm, "ascent": hhea.ascent, "descent": hhea.descent,
            "bbox_max_y": head.yMax, "bbox_min_y": head.yMin,
            "notdef": hmtx[f.getGlyphOrder()[0]][0], "widths": _runs(widths),
            "ligatures": sorted(ligatures.items())}


def _number(token):
    return int(float(token))


def line_break_tables(bundle):
    """The UAX #14 ranges and pair table from the minified pdfme bundle."""
    s = io.open(bundle, encoding="utf-8").read()
    start = s.index("Uint32Array([0,8,21,") + len("Uint32Array([")
    end = s.index("])", start)
    nums = [_number(x) for x in s[start:end].split(",")]
    ranges = [tuple(nums[i:i + 3]) for i in range(0, len(nums), 3)]
    # ",<count name>=<count>,<DI>=0,<IN>=1,<CI>=2,<CP>=3,<PR>=4,<table>=[[...]]"
    tail = s[end + 2:end + 40000]
    m = re.match(r",[\w$]+=(\d+),", tail)
    if int(m.group(1)) != len(ranges):
        raise SystemExit("line-break range count does not match")
    names = {}
    pos = m.end()
    while True:
        a = re.match(r"([\w$]+)=(\d),", tail[pos:])
        if not a:
            break
        names[a.group(1)] = int(a.group(2))
        pos += a.end()
    t = re.match(r"[\w$]+=\[\[", tail[pos:])
    if not t or sorted(names.values()) != [0, 1, 2, 3, 4]:
        raise SystemExit("pair table not found")
    body_start = pos + t.end() - 2
    depth, i = 0, body_start
    while True:
        if tail[i] == "[":
            depth += 1
        elif tail[i] == "]":
            depth -= 1
            if depth == 0:
                break
        i += 1
    rows = re.findall(r"\[([^\[\]]*)\]", tail[body_start + 1:i])
    table = [[names[x] if x in names else _number(x) for x in r.split(",")] for r in rows]
    return [r for r in ranges if r[0] < LIMIT], table


def render():
    """The data module's text."""
    ranges, pairs = line_break_tables(BUNDLE)
    fonts = [(name, font_metrics(os.path.join(FONT_DIR, fn))) for name, fn in FONTS]
    out = ['# -*- coding: utf-8 -*-',
           '"""Generated by tools/pdfme/layout_data.py from the lab fonts and the',
           'vendored pdfme bundle; do not edit. Used by senaite.pfas.pdf_layout."""',
           '',
           'FALLBACK = %r' % FONTS[0][0],
           '# the renderer\'s names for the font files (static/fonts/print)',
           'FONT_FILES = %r' % [list(f) for f in FONTS],
           '# code points at or above this are not measured',
           'LIMIT = %d' % LIMIT,
           '',
           '# name -> upm, hhea ascent / descent, head bbox, .notdef advance,',
           '# advances as (first code point, [advance, ...]) runs, liga pairs',
           'FONTS = {']
    for name, m in fonts:
        out.append('    %r: {' % name)
        for k in ("upm", "ascent", "descent", "bbox_max_y", "bbox_min_y", "notdef"):
            out.append('        %r: %d,' % (k, m[k]))
        out.append('        "widths": [')
        for cp, ws in m["widths"]:
            out.append('            (%d, %r),' % (cp, ws))
        out.append('        ],')
        out.append('        "ligatures": %r,' % [(a, b, w) for (a, b), w in m["ligatures"]])
        out.append('    },')
    out.append('}')
    out.append('')
    out.append('# UAX #14 line-break classes: (first, last, class), sorted')
    out.append('LINE_BREAK_RANGES = [')
    for i in range(0, len(ranges), 6):
        out.append('    ' + ' '.join('(%d, %d, %d),' % r for r in ranges[i:i + 6]))
    out.append(']')
    out.append('')
    out.append('# pdfme\'s pair table (0 direct, 1 indirect, 2 combining indirect,')
    out.append('# 3 combining prohibited, 4 prohibited)')
    out.append('PAIR_TABLE = [')
    for row in pairs:
        out.append('    %r,' % row)
    out.append(']')
    return "\n".join(out) + "\n"


def main():
    text = render()
    with io.open(OUT, "w", encoding="utf-8") as fh:
        fh.write(text)
    print("wrote %s" % OUT)


if __name__ == "__main__":
    main()
