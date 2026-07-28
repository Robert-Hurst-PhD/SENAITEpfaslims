# -*- coding: utf-8 -*-
"""
Wire SENAITE-core Reference Definitions to the control chart as the
UI-editable source of QC-type display names.

Each Reference Definition opts in by carrying a [QC:CODE] tag in its
Description; the control chart maps a stored qc_type code -> that definition's
(editable) Title. Edit the Title in Setup -> Reference Definitions to rename a
QC type on the chart; KEEP the [QC:...] tag so the binding survives.

This script (idempotent):
  * tags the 11 existing PFAS Reference Definitions with their code,
  * leaves the retired LCS definition UNTAGGED (LCS folded into LFB),
  * creates the two live codes that have no definition yet: CCB, SURR,
  * verifies every live qc_type in the DB resolves to a definition.

Run: docker exec -u senaite senaite_pfas-senaite-1 \
     sh -lc 'cd /home/senaite/senaitelims && bin/instance -O senaite run /addon/setup_qc_type_refdefs.py'
"""
from __future__ import absolute_import, print_function

import re

# current Title -> canonical qc_type code (None = leave untagged / retired)
TITLE_TO_CODE = {
    "PFAS Calibration Standard":                 "CAL",
    "PFAS Continuing Calibration Verification":  "CCV",
    "PFAS Sample Duplicate":                     "DUP",
    "PFAS Initial Calibration Verification":     "ICV",
    "PFAS Laboratory Control Sample":            None,   # retired: LCS -> LFB
    "PFAS Lab Fortified Sample Matrix":          "LFSM",
    "PFAS LFSM Duplicate":                       "LFSMD",
    "PFAS Lab Reagent Blank":                    "LRB",
    "PFAS Method Blank":                         "MB",
    "PFAS Matrix Blank":                         "MXB",
    "PFAS Laboratory Fortified Blank":           "LFB",
}

# code -> (title, blank) for definitions that don't exist yet
CREATE = [
    ("CCB",  "PFAS Continuing Calibration Blank", True),
    ("SURR", "PFAS Surrogate Recovery",           False),
]

_TAG = "[QC:{0}]"
_TAG_RE = re.compile(r"\[QC:\s*([A-Za-z0-9_]+)\s*\]")


def _set_tag(rd, code):
    """Ensure the definition's Description carries exactly one [QC:code] tag,
    preserving any human text the user added."""
    desc = rd.Description() or ""
    stripped = _TAG_RE.sub("", desc).strip()
    new = ("{0} {1}".format(_TAG.format(code), stripped)).strip()
    if new != desc:
        rd.setDescription(new)
        rd.reindexObject()
        return True
    return False


def run(app):
    from bika.lims import api
    from senaite.pfas.qc.qc_types import normalize_qc_type
    portal = app.senaite
    folder = portal.bika_setup.bika_referencedefinitions

    by_title = {d.Title(): d for d in folder.objectValues()}
    tagged, created, skipped = [], [], []

    # 1) tag existing definitions
    for title, code in TITLE_TO_CODE.items():
        rd = by_title.get(title)
        if rd is None:
            continue
        if code is None:
            skipped.append(title)
            continue
        if _set_tag(rd, normalize_qc_type(code)):
            tagged.append("%s -> %s" % (code, title))

    # 2) create missing definitions (label-only; empty ReferenceResults is OK)
    existing_codes = set()
    for d in folder.objectValues():
        m = _TAG_RE.search(d.Description() or "")
        if m:
            existing_codes.add(normalize_qc_type(m.group(1)))
    for code, title, blank in CREATE:
        if normalize_qc_type(code) in existing_codes:
            continue
        rd = api.create(folder, "ReferenceDefinition", title=title,
                        Blank=blank, ReferenceResults=[])
        rd.setDescription(_TAG.format(normalize_qc_type(code)))
        rd.reindexObject()
        created.append("%s -> %s (id=%s)" % (code, title, rd.getId()))

    import transaction
    transaction.commit()

    # 3) verify every live qc_type resolves
    label_map = {}
    for d in folder.objectValues():
        m = _TAG_RE.search(d.Description() or "")
        if m:
            label_map[normalize_qc_type(m.group(1))] = d.Title()

    print("=== tagged ===")
    for t in tagged:
        print("  " + t)
    print("=== created ===")
    for c in created:
        print("  " + c)
    print("=== left untagged (retired) ===")
    for s in skipped:
        print("  " + s)

    import sqlite3
    import os
    db = os.environ.get("PFAS_QC_DB", "/data/qc/pfas_qc_results.db")
    live = [normalize_qc_type(r[0]) for r in
            sqlite3.connect(db).execute(
                "SELECT DISTINCT qc_type FROM qc_results")]
    print("=== live qc_type resolution ===")
    for code in sorted(set(live)):
        print("  %-8s -> %s" % (
            code, label_map.get(code, "*** UNRESOLVED (shows raw code) ***")))


if __name__ == "__main__":
    run(app)  # noqa: F821
