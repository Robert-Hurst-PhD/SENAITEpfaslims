# -*- coding: utf-8 -*-
"""
@@pfas-system-map — an interactive system map. Renders the 3-layer architecture
diagram (user entry points → add-on parts → core SENAITE services) as inline
SVG whose bubbles are clickable links to the corresponding page, so users can
jump straight to the screen they need to edit.

The SVG is generated with portal-relative <a> links baked in (native SVG
navigation, no JS). Layout mirrors senaite_pfas_map.svg.

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile


# ── Layout constants (match gen_svg / senaite_pfas_map.svg) ───────────────────
W, H = 1660, 980
Y_ENTRY, Y_ADDON, Y_CORE = 150, 470, 800
NH = 62
COLS, X0, GAP = 8, 34, 12
CW = (W - 2 * X0 - (COLS - 1) * GAP) / float(COLS)

C = {
    "entry": "#e8f0fe", "entryS": "#3b6fb0",
    "addon": "#d7ecf3", "addonS": "#387493",
    "master": "#cbe6d3", "masterS": "#2e7d32",
    "new": "#fff8e1", "newS": "#c9a227",
    "core": "#eceff1", "coreS": "#607d8b",
    "defect": "#fdecea", "defectS": "#c62828",
    "body": "#293333", "sub": "#5b6b6b",
}

# id: (col, span, row_offset, band, title, sub, kind, nav)
#   band: e/a/c   row_offset: 0 = main row, 1 = second row
#   nav: portal-relative path (or None = not clickable)
NODES = [
    # ── ENTRY POINTS ──
    ("setup",  0,   1.4, 0, "e", "Method & Analyte Setup", "Manager",            "entry", "@@lims-setup?section=methods"),
    ("bench",  1.5, 1.2, 0, "e", "Bench",                  "Bench Chemist",      "entry", "@@pfas-reagents"),
    ("sample", 2.8, 1.2, 0, "e", "Sample Workflow",        "Manager/Analyst",    "entry", "samples"),
    ("qc",     4.1, 1.2, 0, "e", "QC Management",          "Manager/QAO",        "entry", "@@pfas-qc-management"),
    ("review", 5.4, 1.2, 0, "e", "Data Review",            "Analyst",            "entry", "@@pfas-data-review"),
    ("report", 6.7, 1.3, 0, "e", "Reporting & EDD",        "Manager/Analyst",    "entry", "@@pfas-egad-config"),
    ("facil",  1.5, 1.2, 1, "e", "Facility QC",            "Manager/QAO",        "entry", "@@pfas-facility-qc"),
    ("instr",  2.8, 1.2, 1, "e", "Instrument & Import",    "Manager/Analyst",    "entry", "@@pfas-import-studio"),
    ("client", 6.7, 1.3, 1, "e", "Client Tracker",         "Client (no login)",  "entry", "@@pfas-track"),
    # ── ADD-ON PARTS ──
    ("analyte", 0,   1.4, 0, "a", "analyte_reference  ★", "MASTER: analytes·CAS·IS·matrices", "master", "@@pfas-setup-references"),
    ("mps",     1.5, 1.6, 0, "a", "method_profile_store",  "METHOD PROFILE hub", "addon", "@@pfas-method-profiles"),
    ("reag",    3.2, 1.1, 0, "a", "reagents + prep_std",   "3-level traceability", "addon", "@@pfas-reagents"),
    ("qcs",     4.4, 1.1, 0, "a", "qc.rules + qc.store",   "toggles + results DB", "addon", "@@pfas-qc-rules"),
    ("spec",    5.6, 1.1, 0, "a", "spec_sync  ★",     "→ per-matrix specs + audit", "new", "bika_setup/bika_analysisspecs"),
    ("egad",    6.8, 1.2, 0, "a", "EDD engine",  "profiles · builder · CAS overlay", "addon", "@@pfas-egad-config"),
    ("logbk",   1.5, 1.1, 1, "a", "logbook_store",         "FM-ENV logbooks",    "addon", "@@pfas-logbook-admin"),
    ("facmod",  2.7, 1.1, 1, "a", "facility_qc",           "SQLite readings",    "addon", "@@pfas-facility-qc"),
    ("import",  3.9, 1.1, 1, "a", "import_studio",         "instrument mappings", "addon", "@@pfas-import-studio"),
    ("chart",   5.1, 1.1, 1, "a", "control_chart",         "Westgard control charts", "addon", "@@pfas-control-chart"),
    ("track",   6.8, 1.2, 1, "a", "tracking_store",        "client tracker backend", "addon", "@@pfas-track"),
    # ── CORE SENAITE SERVICES ──
    ("svc",    0,   1.2, 0, "c", "AnalysisService",  "analyte identity·keyword", "core", "bika_setup/bika_analysisservices"),
    ("stype",  1.3, 1.1, 0, "c", "SampleType",       "matrix identity",    "core", "setup/sampletypes"),
    ("batch",  2.5, 1.0, 0, "c", "Batch",            "method × matrix", "core", "batches"),
    ("ws",     3.5, 1.0, 0, "c", "Worksheet",        "analytical unit",    "core", "worksheets"),
    ("aspec",  4.5, 1.1, 0, "c", "AnalysisSpec",     "per QC × matrix · real SampleTypes", "core", "bika_setup/bika_analysisspecs"),
    ("refdef", 5.7, 1.1, 0, "c", "ReferenceDefinition", "QC controls",     "core", "bika_setup/bika_referencedefinitions"),
    ("cat",    6.8, 1.2, 0, "c", "senaite catalogs", "+ snapshot / audit log", "core", None),
]

# edges: (from, to, kind)  kind: e2a / a2c / new / ref
EDGES = [
    ("setup", "analyte", "e2a"), ("setup", "mps", "e2a"),
    ("bench", "reag", "e2a"), ("bench", "logbk", "e2a"),
    ("sample", "mps", "e2a"),
    ("qc", "qcs", "e2a"), ("qc", "mps", "e2a"), ("qc", "chart", "e2a"),
    ("review", "qcs", "e2a"), ("review", "reag", "e2a"),
    ("report", "egad", "e2a"),
    ("facil", "facmod", "e2a"), ("instr", "import", "e2a"), ("client", "track", "e2a"),
    ("mps", "spec", "live2"), ("analyte", "mps", "ref"), ("mps", "egad", "ref"),
    ("qcs", "chart", "ref"),
    ("analyte", "svc", "a2c"), ("analyte", "stype", "a2c"),
    ("mps", "svc", "a2c"), ("mps", "stype", "a2c"),
    ("spec", "aspec", "live2"), ("spec", "cat", "new"),
    ("reag", "batch", "a2c"), ("egad", "batch", "a2c"), ("egad", "cat", "a2c"),
    ("qcs", "refdef", "a2c"), ("track", "ws", "a2c"), ("reag", "ws", "a2c"),
]

_EDGE_STYLE = {
    "e2a":   ("#3b6fb0", "aE", 2.2, ""),
    "a2c":   ("#387493", "aA", 2.2, ""),
    "new":   ("#c9a227", "aN", 2.6, ""),
    "live2": ("#c9a227", "aN", 2.8, ""),   # bidirectional (double-headed)
    "ref":   ("#8a9ba8", "aR", 1.6, ' stroke-dasharray="5 4"'),
}


def _esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


class PFASSystemMapView(BrowserView):
    template = ViewPageTemplateFile("templates/system_map.pt")

    def __call__(self):
        return self.template()

    def portal_url(self):
        return getToolByName(self.context, "portal_url").getPortalObject().absolute_url()

    # ── geometry helpers ──
    def _x(self, col, span):
        x = X0 + col * (CW + GAP)
        return x, x + span * CW + (span - 1) * GAP

    def _layout(self):
        band_y = {"e": Y_ENTRY, "a": Y_ADDON, "c": Y_CORE}
        pos = {}
        for nid, col, span, roff, band, title, sub, kind, nav in NODES:
            x0, x1 = self._x(col, span)
            y = band_y[band] + roff * 86
            pos[nid] = {
                "x": x0, "w": x1 - x0, "y": y, "cx": (x0 + x1) / 2.0,
                "cy": y + NH / 2.0, "title": title, "sub": sub, "kind": kind,
                "nav": nav,
            }
        return pos

    def map_svg(self):
        purl = self.portal_url()
        pos = self._layout()
        out = []
        out.append(
            '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            'viewBox="0 0 %d %d" width="100%%" height="auto" class="pfas-map-svg" '
            'font-family="Segoe UI, Roboto, Helvetica, Arial, sans-serif">' % (W, H))
        for mid, col in [("aE", "#3b6fb0"), ("aA", "#387493"), ("aN", "#c9a227"), ("aR", "#8a9ba8")]:
            # amber marker doubles as a start-arrow (reversed) for two-way edges
            orient = "auto-start-reverse" if mid == "aN" else "auto"
            out.append('<marker id="%s" markerWidth="9" markerHeight="9" refX="7" refY="3" '
                       'orient="%s"><path d="M0,0L7,3L0,6Z" fill="%s"/></marker>' % (mid, orient, col))

        # band labels + separators
        for lbl, y in [("USER ENTRY POINTS  ·  role workspaces", Y_ENTRY - 16),
                       ("SENAITE.PFAS ADD-ON PARTS", Y_ADDON - 16),
                       ("CORE SENAITE SERVICES", Y_CORE - 16)]:
            out.append('<text x="34" y="%d" font-size="12.5" font-weight="700" '
                       'letter-spacing="1.5" fill="#9aa7b0">%s</text>' % (y, lbl))
        for y in (Y_ENTRY - 30, Y_ADDON - 30, Y_CORE - 30):
            out.append('<line x1="30" y1="%d" x2="%d" y2="%d" stroke="#eef1f3" stroke-width="1"/>'
                       % (y, W - 30, y))

        # ── edges: port-spread + vertical-stub routing (declutters crossings) ──
        SAME = 6.0
        # assign a spread-out "port" on each node edge so multiple edges from one
        # node don't stack at its centre; order ports by the other end's x.
        down_out, down_in, up_out, up_in = {}, {}, {}, {}
        for idx, (f, t, kind) in enumerate(EDGES):
            nf, nt = pos[f], pos[t]
            dy = nf["cy"] - nt["cy"]
            if abs(dy) < SAME:
                continue
            if dy < 0:
                down_out.setdefault(f, []).append((nt["cx"], idx))
                down_in.setdefault(t, []).append((nf["cx"], idx))
            else:
                up_out.setdefault(f, []).append((nt["cx"], idx))
                up_in.setdefault(t, []).append((nf["cx"], idx))

        def _port_x(node, sibs, idx):
            order = sorted(sibs)
            n = len(order)
            if n <= 1:
                return node["cx"]
            k = [i for i, (_, ei) in enumerate(order) if ei == idx][0]
            lo, hi = node["x"] + node["w"] * 0.24, node["x"] + node["w"] * 0.76
            return lo + (hi - lo) * k / float(n - 1)

        for idx, (f, t, kind) in enumerate(EDGES):
            col, mk, wdt, dash = _EDGE_STYLE[kind]
            nf, nt = pos[f], pos[t]
            dy = nf["cy"] - nt["cy"]
            if abs(dy) < SAME:
                # same band → connect nearest sides (clean horizontal S)
                if nf["cx"] <= nt["cx"]:
                    x1, y1, x2, y2 = nf["x"] + nf["w"], nf["cy"], nt["x"], nt["cy"]
                else:
                    x1, y1, x2, y2 = nf["x"], nf["cy"], nt["x"] + nt["w"], nt["cy"]
                mx = (x1 + x2) / 2.0
                d = "M%.0f,%.0f C%.0f,%.0f %.0f,%.0f %.0f,%.0f" % (x1, y1, mx, y1, mx, y2, x2, y2)
            elif dy < 0:  # downward: source bottom → target top, vertical stubs
                x1 = _port_x(nf, down_out[f], idx); y1 = nf["y"] + NH
                x2 = _port_x(nt, down_in[t], idx);  y2 = nt["y"]
                my = (y1 + y2) / 2.0
                d = "M%.0f,%.0f C%.0f,%.0f %.0f,%.0f %.0f,%.0f" % (x1, y1, x1, my, x2, my, x2, y2)
            else:  # upward: source top → target bottom
                x1 = _port_x(nf, up_out[f], idx); y1 = nf["y"]
                x2 = _port_x(nt, up_in[t], idx);  y2 = nt["y"] + NH
                my = (y1 + y2) / 2.0
                d = "M%.0f,%.0f C%.0f,%.0f %.0f,%.0f %.0f,%.0f" % (x1, y1, x1, my, x2, my, x2, y2)
            start = ' marker-start="url(#%s)"' % mk if kind == "live2" else ''
            out.append('<path d="%s" stroke="%s" stroke-width="%.1f" fill="none"%s '
                       'marker-end="url(#%s)"%s opacity="0.85"/>' % (d, col, wdt, dash, mk, start))

        # nodes (clickable ones wrapped in <a>)
        kmap = {"entry": ("entry", "entryS"), "addon": ("addon", "addonS"),
                "master": ("master", "masterS"), "new": ("new", "newS"),
                "core": ("core", "coreS"), "defect": ("defect", "defectS")}
        for nid, n in pos.items():
            fill, strk = kmap[n["kind"]]
            sw = "2.4" if n["kind"] in ("master", "new") else "1.7"
            g = []
            g.append('<rect x="%.0f" y="%d" width="%.0f" height="%d" rx="9" fill="%s" '
                     'stroke="%s" stroke-width="%s"/>' % (n["x"], n["y"], n["w"], NH, C[fill], C[strk], sw))
            g.append('<text x="%.0f" y="%d" text-anchor="middle" font-size="13" '
                     'font-weight="700" fill="%s">%s</text>' % (n["cx"], n["y"] + 26, C["body"], _esc(n["title"])))
            if n["sub"]:
                g.append('<text x="%.0f" y="%d" text-anchor="middle" font-size="10" fill="%s">%s</text>'
                         % (n["cx"], n["y"] + 44, C["sub"], _esc(n["sub"])))
            grp = '<g class="node%s">%s</g>' % (" clickable" if n["nav"] else "", "".join(g))
            if n["nav"]:
                href = _esc("%s/%s" % (purl, n["nav"]))
                out.append('<a xlink:href="%s" href="%s" target="_top"><title>Open: %s</title>%s</a>'
                           % (href, href, _esc(n["title"]), grp))
            else:
                out.append(grp)

        out.append('</svg>')
        return "".join(out)
