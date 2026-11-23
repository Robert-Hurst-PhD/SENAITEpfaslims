# -*- coding: utf-8 -*-
"""Help figures (the main workflows first): a Help entry shows its
page as a screenshot with numbered boxes and a caption naming each.

A figure is data: the Help entry, its title, the page it is captured from
("{ws}": the newest worksheet in the Data Review queue; "{rb}": the
first worksheet the Run Builder lists under "Ready to build") and its marks --
(number, the element as a Playwright locator, the sentence). The capture
tool (tools/help_figures.py) opens each page at a release, finds each
mark's box and saves the screenshot and the boxes in the instance's data
(FIGURES_DIR), never in the code: a screenshot carries the lab's own names.
Until a figure is captured Help shows none.

    figure(entry_id, captured, portal_url) -> {"title", "src", "width",
        "height", "boxes": [{"n", "x", "y", "w", "h"}], "caption": [(n, text)]} or None

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import os

FIGURES_DIR = os.environ.get("PFAS_HELP_FIGURES", "/data/help_figures")
ROW = u"table.pfas-table tbody tr >> nth=0"

FIGURES = [
    {"entry": u"method-profile", "title": u"Figure 1 · Method Profiles & QC",
     "page": u"@@pfas-method-profiles",
     "marks": [(1, u"a:has-text('+ New method')", u"+ New method starts a new method profile in the wizard."),
               (2, ROW + u" >> a.btn-sm >> nth=0", u"The method's name opens its profile."),
               (3, ROW + u" >> td >> nth=3", u"The SENAITE Method the profile is linked to."),
               (4, ROW + u" >> td.mp-rev", u"The issued revision; the row's + menu holds the rest.")]},
    {"entry": u"data-review", "title": u"Figure 1 · Data Review of a worksheet",
     "page": u"worksheets/{ws}/@@pfas-data-review",
     "marks": [(1, u".pfas-seg-item:has-text('Chain of Custody')", u"Chain of Custody: the samples' receipt, checked by the reviewer."),
               (2, u".pfas-seg-item:has-text('Traceability')", u"Traceability: every lot back to its certificate, checked by the system."),
               (3, u".pfas-seg-item:has-text('Spike QC')", u"QC: blanks, calibration and spikes against the method's limits."),
               (4, u".pfas-seg-item:has-text('Final Data')", u"Final Data: the reported results, reviewed by the analyst."),
               (5, u".pfas-seg-item:has-text('Instrument Report')", u"Instrument Report: the raw data file, attached and reviewed."),
               (6, u"button:has-text('Submit for verification')", u"Submit for verification once all five pass; the manager verifies.")]},
    {"entry": u"calibration-decision", "title": u"Figure 1 · Run Builder: a new calibration curve",
     "page": u"@@pfas-run-builder?batch_id={rb}",
     "marks": [(1, u"select[name=batch_id]", u"The worksheet the run follows."),
               (2, u"text=Is a new calibration curve needed?", u"Whether the run builds a new curve: the method's rule, or the analyst's decision with a reason."),
               (3, u"label:has-text('Calibration series')", u"The prep sitting whose levels the curve is made from.")]},
    {"entry": u"extraction-batch", "title": u"Figure 1 · An extraction worksheet",
     "page": u"worksheets/{ws}/@@pfas-extraction-batch",
     "marks": [(1, u"text=1. Samples", u"The worksheet's samples, as the extraction will take them."),
               (2, u"text=2. QC", u"The QC the method asks for and the worksheet's size."),
               (3, u"text=3. Parents and levels", u"Each QC member's parent sample and spiking level, and each spike's lot and volume."),
               (4, u"a:has-text('Guided extraction')", u"The guided extraction records the worksheet stage by stage.")]},
]
BY_ENTRY = dict((f["entry"], f) for f in FIGURES)


def figure(entry_id, captured, portal_url):
    f = BY_ENTRY.get(entry_id)
    cap = (captured or {}).get(entry_id)
    if f is None or not cap:
        return None
    boxes = []
    for n, _loc, _text in f["marks"]:
        b = (cap.get("boxes") or {}).get(u"%d" % n)
        if b:
            boxes.append({"n": n, "x": b[0], "y": b[1], "w": b[2], "h": b[3]})
    return {"title": f["title"], "src": u"%s/@@pfas-help-figure?id=%s" % (portal_url, entry_id),
            "width": cap.get("width"), "height": cap.get("height"), "boxes": boxes,
            "caption": [(n, text) for n, _loc, text in f["marks"]]}
