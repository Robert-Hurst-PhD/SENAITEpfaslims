# -*- coding: utf-8 -*-
"""
Rename the CCB Reference Definition Title to "Solvent Blank".

QC-type labels resolve from the RefDef Title (single UI-editable source). The
lab calls the CCB (continuing calibration blank) a "Solvent Blank", so rename
the Title; the [QC:CCB] Description tag / pfas_qc_code identity is unchanged, so
every consumer (control charts, run builder, method profiles) follows.

Idempotent. Prior title backed up to annotation senaite.pfas.title_backup.
Run:  bin/instance -O senaite run rename_ccb_to_solvent_blank.py
"""
from __future__ import absolute_import, print_function, unicode_literals

import re
import transaction
from bika.lims import api
from zope.annotation.interfaces import IAnnotations

_TAG = re.compile(r"\[QC:\s*([A-Za-z0-9_]+)\s*\]")
NEW_TITLE = u"Solvent Blank"

portal = api.get_portal()
folder = portal.bika_setup.bika_referencedefinitions

changed = 0
for d in folder.objectValues():
    code = u""
    try:
        code = d.getField("pfas_qc_code").get(d) or u""
    except Exception:
        pass
    if not code:
        m = _TAG.search(d.Description() or u"")
        code = m.group(1) if m else u""
    if code.upper() != "CCB":
        continue
    if d.Title() == NEW_TITLE:
        continue
    try:
        IAnnotations(d)[u"senaite.pfas.title_backup"] = d.Title()
    except Exception:
        pass
    print(u"  {0!r} -> {1!r}".format(d.Title(), NEW_TITLE))
    d.setTitle(NEW_TITLE)
    try:
        d.reindexObject()
    except Exception:
        pass
    changed += 1

print(u"Renamed {0} CCB definition(s).".format(changed))
transaction.commit()
print(u"Committed.")
