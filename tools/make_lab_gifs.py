#!/usr/bin/env python3
"""
Generate the built-in 8/16-bit style animated GIFs for guided logbook steps.

Each animation is drawn on a small logical canvas (LOGICAL px) with hard-edged
primitives, then scaled up with NEAREST so it stays crisp and unmistakably
pixel-art — matching the sample tracker, which renders its stage art with
`image-rendering: pixelated`.

Run from the repo root:

    python3 tools/make_lab_gifs.py

Writes into src/senaite/pfas/browser/static/labgifs/ so the files ship with
the add-on and are served via ++resource++senaite.pfas/labgifs/<name>.gif.
They are *library* art: a lab that photographs its own bench still uploads
through @@pfas-logbook-media as before.
"""
import os
from PIL import Image, ImageDraw

LOGICAL = 48          # logical pixel grid
SCALE = 4             # -> 192x192 output
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "..", "src", "senaite", "pfas", "browser", "static", "labgifs")

# Muted lab palette that reads on both light and dark page backgrounds.
BG      = (247, 249, 250)
INK     = (38, 50, 56)      # outlines
STEEL   = (120, 144, 156)   # instrument body
STEEL_D = (84, 110, 122)
GLASS   = (176, 216, 230)
LIQUID  = (33, 150, 243)
LIQUID2 = (0, 188, 212)
AMBER   = (255, 179, 0)
RED     = (229, 57, 53)
GREEN   = (67, 160, 71)
WHITE   = (255, 255, 255)
GREY    = (189, 195, 199)
PURPLE  = (156, 39, 176)


def new_frame():
    img = Image.new("RGB", (LOGICAL, LOGICAL), BG)
    return img, ImageDraw.Draw(img)


def save(name, frames, durations=120):
    os.makedirs(OUT, exist_ok=True)
    big = [f.resize((LOGICAL * SCALE, LOGICAL * SCALE), Image.NEAREST)
           .quantize(colors=32, method=Image.MEDIANCUT) for f in frames]
    path = os.path.join(OUT, name + ".gif")
    big[0].save(path, save_all=True, append_images=big[1:],
                duration=durations, loop=0, optimize=True, disposal=2)
    print("  %-22s %2d frames  %5d bytes" % (name + ".gif", len(big),
                                             os.path.getsize(path)))


def bench(d, y=40):
    """Common bench surface."""
    d.rectangle([0, y, LOGICAL, LOGICAL], fill=(222, 226, 230))
    d.line([0, y, LOGICAL, y], fill=INK)


# ── 1. Analytical balance / weighing ────────────────────────────────────────
def gif_weighing():
    frames = []
    for i, (mass, digits) in enumerate([(0, "0.000"), (3, "1.284"),
                                        (5, "3.410"), (6, "3.854"),
                                        (6, "3.854")]):
        img, d = new_frame()
        bench(d)
        # balance body
        d.rectangle([8, 26, 40, 40], fill=STEEL, outline=INK)
        d.rectangle([11, 30, 37, 36], fill=(30, 40, 45), outline=INK)
        # display digits as little bars
        for k in range(5):
            x = 13 + k * 5
            lit = k <= i
            d.rectangle([x, 32, x + 3, 34], fill=GREEN if lit else STEEL_D)
        # pan + column
        d.rectangle([22, 20, 26, 26], fill=STEEL_D)
        d.rectangle([14, 17, 34, 20], fill=GREY, outline=INK)
        # sample pile grows
        if mass:
            d.rectangle([24 - mass, 17 - mass // 2, 24 + mass, 17],
                        fill=WHITE, outline=INK)
        frames.append(img)
    return frames


# ── 2. Pipetting ────────────────────────────────────────────────────────────
def gif_pipetting():
    frames = []
    for i in range(6):
        img, d = new_frame()
        bench(d)
        # receiving vial
        d.rectangle([28, 26, 38, 40], fill=GLASS, outline=INK)
        fill_h = min(12, 2 + i * 2)
        d.rectangle([29, 40 - fill_h, 37, 39], fill=LIQUID)
        # pipette descends slightly then dispenses
        py = 4 + (i % 3)
        d.rectangle([31, py, 35, py + 14], fill=WHITE, outline=INK)
        d.rectangle([31, py, 35, py + 4], fill=STEEL, outline=INK)
        d.polygon([(32, py + 14), (34, py + 14), (33, py + 21)], fill=AMBER,
                  outline=INK)
        # droplet
        if i % 3 == 2:
            d.rectangle([32, py + 23, 34, py + 25], fill=LIQUID)
        frames.append(img)
    return frames


# ── 3. Vortex mixer ─────────────────────────────────────────────────────────
def gif_vortex():
    frames = []
    for i in range(6):
        img, d = new_frame()
        bench(d)
        d.rectangle([12, 28, 36, 40], fill=STEEL, outline=INK)
        d.rectangle([16, 24, 32, 28], fill=STEEL_D, outline=INK)
        wob = (-2, -1, 0, 1, 2, 1)[i]
        # tube tilts with the wobble
        d.polygon([(22 + wob, 6), (28 + wob, 6), (27, 24), (23, 24)],
                  fill=GLASS, outline=INK)
        # swirling liquid
        d.polygon([(24 + wob, 14), (27 + wob, 14), (26, 23), (24, 23)],
                  fill=PURPLE)
        # motion ticks
        for s in (-1, 1):
            d.line([25 + wob + s * 7, 10, 25 + wob + s * 9, 10], fill=STEEL_D)
        frames.append(img)
    return frames


# ── 4. Centrifuge ───────────────────────────────────────────────────────────
def gif_centrifuge():
    frames = []
    for i in range(6):
        img, d = new_frame()
        bench(d)
        d.ellipse([8, 14, 40, 38], fill=STEEL, outline=INK)
        d.ellipse([13, 18, 35, 34], fill=(30, 40, 45), outline=INK)
        # two rotor tubes spinning
        import math
        ang = i * (math.pi / 3)
        for k in (0, 1):
            a = ang + k * math.pi
            cx = 24 + int(7 * math.cos(a))
            cy = 26 + int(5 * math.sin(a))
            d.rectangle([cx - 2, cy - 2, cx + 2, cy + 2], fill=LIQUID2,
                        outline=INK)
        # lid + running light
        d.rectangle([8, 10, 40, 14], fill=STEEL_D, outline=INK)
        d.rectangle([35, 11, 38, 13], fill=GREEN if i % 2 else (20, 60, 25))
        frames.append(img)
    return frames


# ── 5. Nitrogen blow-down / evaporation ─────────────────────────────────────
def gif_evaporate():
    frames = []
    for i in range(6):
        img, d = new_frame()
        bench(d)
        # manifold
        d.rectangle([6, 6, 42, 10], fill=STEEL, outline=INK)
        for x in (14, 24, 34):
            d.rectangle([x - 1, 10, x + 1, 16], fill=STEEL_D)
        # vials with shrinking volume
        for n, x in enumerate((14, 24, 34)):
            d.rectangle([x - 5, 24, x + 5, 40], fill=GLASS, outline=INK)
            h = max(1, 10 - ((i + n) % 6))
            d.rectangle([x - 4, 39 - h, x + 4, 39], fill=AMBER)
            # gas stream ticks
            if (i + n) % 2 == 0:
                d.line([x, 17, x, 22], fill=(150, 200, 220))
        frames.append(img)
    return frames


# ── 6. SPE / filtration ─────────────────────────────────────────────────────
def gif_spe():
    frames = []
    for i in range(6):
        img, d = new_frame()
        bench(d)
        # cartridge
        d.polygon([(18, 6), (30, 6), (28, 22), (20, 22)], fill=GLASS,
                  outline=INK)
        lvl = 6 + i * 2
        d.polygon([(19, lvl), (29, lvl), (28, 22), (20, 22)], fill=LIQUID2)
        d.rectangle([21, 22, 27, 26], fill=WHITE, outline=INK)   # frit
        d.rectangle([23, 26, 25, 30], fill=STEEL_D)              # stem
        # collection vial filling
        d.rectangle([18, 30, 30, 40], fill=GLASS, outline=INK)
        h = min(9, 1 + i * 2)
        d.rectangle([19, 39 - h, 29, 39], fill=LIQUID)
        if i % 2:
            d.rectangle([23, 30, 25, 32], fill=LIQUID)
        frames.append(img)
    return frames


# ── 7. pH meter ─────────────────────────────────────────────────────────────
def gif_ph():
    frames = []
    for i, val in enumerate(["7.9", "7.2", "6.6", "6.1", "5.9", "5.9"]):
        img, d = new_frame()
        bench(d)
        # meter
        d.rectangle([4, 18, 22, 40], fill=STEEL, outline=INK)
        d.rectangle([7, 22, 19, 30], fill=(30, 40, 45), outline=INK)
        for k in range(3):
            ok = k <= i // 2
            d.rectangle([9 + k * 4, 25, 11 + k * 4, 27],
                        fill=GREEN if ok else STEEL_D)
        # beaker + probe
        d.rectangle([28, 22, 44, 40], fill=GLASS, outline=INK)
        col = (33, 150, 243) if i < 3 else (77, 182, 172)
        d.rectangle([29, 28, 43, 39], fill=col)
        d.rectangle([34, 10, 37, 34], fill=WHITE, outline=INK)
        if i % 2:
            d.rectangle([33, 30 + (i % 3), 38, 31 + (i % 3)], fill=WHITE)
        frames.append(img)
    return frames


# ── 8. Labelling a vial ─────────────────────────────────────────────────────
def gif_label():
    frames = []
    for i in range(6):
        img, d = new_frame()
        bench(d)
        d.rectangle([18, 14, 30, 40], fill=GLASS, outline=INK)
        d.rectangle([19, 30, 29, 39], fill=AMBER)
        d.rectangle([16, 8, 32, 14], fill=STEEL, outline=INK)   # cap
        # label sliding on, then barcode lines appear
        lw = min(10, 2 + i * 2)
        d.rectangle([19, 18, 19 + lw, 28], fill=WHITE, outline=INK)
        if i >= 3:
            for k in range(4):
                if 19 + 2 + k * 2 < 19 + lw:
                    d.line([21 + k * 2, 20, 21 + k * 2, 26], fill=INK)
        frames.append(img)
    return frames


# ── 9. Sign-off / record ────────────────────────────────────────────────────
def gif_signoff():
    frames = []
    for i in range(6):
        img, d = new_frame()
        bench(d)
        d.rectangle([10, 8, 38, 40], fill=WHITE, outline=INK)
        d.rectangle([18, 4, 30, 9], fill=STEEL, outline=INK)     # clip
        for k in range(3):
            d.line([14, 16 + k * 5, 34, 16 + k * 5], fill=GREY)
        # signature stroke draws in, then a green tick
        if i >= 1:
            n = min(i, 4)
            pts = [(14, 33), (18, 30), (22, 34), (26, 29), (32, 33)][:n + 1]
            if len(pts) > 1:
                d.line(pts, fill=LIQUID)
        if i >= 5:
            d.line([(28, 22), (31, 25)], fill=GREEN, width=2)
            d.line([(31, 25), (36, 17)], fill=GREEN, width=2)
        frames.append(img)
    return frames


# ── 10. Sonication / water bath ─────────────────────────────────────────────
def gif_sonicate():
    frames = []
    for i in range(6):
        img, d = new_frame()
        bench(d)
        d.rectangle([6, 20, 42, 40], fill=STEEL, outline=INK)
        d.rectangle([9, 24, 39, 38], fill=LIQUID2, outline=INK)
        # bubbles rise
        for k, x in enumerate((14, 22, 30, 36)):
            y = 36 - ((i * 2 + k * 3) % 12)
            d.rectangle([x, y, x + 1, y + 1], fill=WHITE)
        # tube suspended in the bath
        d.rectangle([21, 14, 27, 34], fill=GLASS, outline=INK)
        d.rectangle([22, 24, 26, 33], fill=PURPLE)
        frames.append(img)
    return frames


# ── 11. LC-MS autosampler injection ─────────────────────────────────────────
def gif_inject():
    frames = []
    for i in range(6):
        img, d = new_frame()
        bench(d)
        # instrument
        d.rectangle([4, 12, 44, 40], fill=STEEL, outline=INK)
        d.rectangle([7, 16, 41, 26], fill=(30, 40, 45), outline=INK)
        # vial tray
        for k, x in enumerate((12, 20, 28, 36)):
            sel = (k == i % 4)
            d.rectangle([x - 3, 30, x + 3, 38],
                        fill=AMBER if sel else GLASS, outline=INK)
        # needle moves to the selected vial
        nx = (12, 20, 28, 36)[i % 4]
        d.rectangle([nx - 1, 26, nx + 1, 30], fill=WHITE, outline=INK)
        # a chromatogram peak scrolls in the display
        base = 24
        for x in range(8, 40):
            import math
            peak = int(6 * math.exp(-((x - (12 + i * 4)) ** 2) / 8.0))
            if peak:
                d.line([x, base, x, base - peak], fill=GREEN)
        frames.append(img)
    return frames


# ── 12. Fume hood / PPE reminder ────────────────────────────────────────────
def gif_hood():
    frames = []
    for i in range(6):
        img, d = new_frame()
        bench(d, y=42)
        d.rectangle([4, 4, 44, 42], fill=STEEL, outline=INK)
        d.rectangle([8, 10, 40, 34], fill=(214, 234, 240), outline=INK)
        # sash slides
        sash = 10 + (i if i < 4 else 6 - i % 4) * 2
        d.rectangle([8, 10, 40, sash], fill=STEEL_D, outline=INK)
        d.line([8, sash, 40, sash], fill=WHITE)
        # beaker inside
        d.rectangle([20, 26, 30, 34], fill=GLASS, outline=INK)
        d.rectangle([21, 30, 29, 33], fill=GREEN)
        # airflow arrows
        if i % 2 == 0:
            for x in (12, 34):
                d.line([x, 36, x, 39], fill=LIQUID2)
        frames.append(img)
    return frames


BUILDERS = [
    ("weighing",    "Weighing on the balance",      gif_weighing),
    ("pipetting",   "Pipetting / dispensing",       gif_pipetting),
    ("vortex",      "Vortex mixing",                gif_vortex),
    ("centrifuge",  "Centrifuging",                 gif_centrifuge),
    ("evaporate",   "Nitrogen blow-down",           gif_evaporate),
    ("spe",         "SPE / filtration",             gif_spe),
    ("ph",          "pH measurement",               gif_ph),
    ("label",       "Labelling a vial",             gif_label),
    ("signoff",     "Sign-off / record",            gif_signoff),
    ("sonicate",    "Sonication / water bath",      gif_sonicate),
    ("inject",      "LC-MS injection",              gif_inject),
    ("hood",        "Fume hood / PPE",              gif_hood),
]


def main():
    print("Generating %d lab-task animations -> %s" % (len(BUILDERS), OUT))
    for name, _label, fn in BUILDERS:
        save(name, fn())
    # emit the catalogue the builder UI reads
    import json
    cat = [{"name": n, "label": l} for n, l, _ in BUILDERS]
    with open(os.path.join(OUT, "catalog.json"), "w") as fh:
        json.dump(cat, fh, indent=2)
    print("  catalog.json          %d entries" % len(cat))


if __name__ == "__main__":
    main()
