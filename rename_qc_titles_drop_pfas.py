# -*- coding: utf-8 -*-
"""
Strip the leading "PFAS " prefix from every QC-type Reference Definition Title.

The RefDef Title is the single UI-editable source for QC-type display labels
(control-chart dropdown/legend, method-profile toggles, qc rules). A def counts
as a QC type if it carries a pfas_qc_code field OR a [QC:CODE] Description tag.

Idempotent: only strips when the title actually starts with "PFAS ".
Prints old -> new for every change. Records the prior title in the object
annotation `senaite.pfas.title_backup` so the rename is reversible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import re
import transaction
from bika.lims import api
from zope.annotation.interfaces import IAnnotations

_TAG = re.compile(r"\[QC:\s*([A-Za-z0-9_]+)\s*\]")
_PREFIX = u"PFAS "

portal = api.get_portal()
folder = portal.bika_setup.bika_referencedefinitions

changed = 0
for d in folder.objectValues():
    title = d.Title() or u""
    code_field = u""
    try:
        code_field = d.getField("pfas_qc_code").get(d) or u""
    except Exception:
        pass
    has_tag = bool(_TAG.search(d.Description() or u""))
    is_qc = bool(code_field) or has_tag
    if not is_qc:
        continue
    if not title.startswith(_PREFIX):
        continue
    new_title = title[len(_PREFIX):].strip()
    try:
        IAnnotations(d)[u"senaite.pfas.title_backup"] = title
    except Exception:
        pass
    d.setTitle(new_title)
    try:
        d.reindexObject()
    except Exception:
        pass
    print(u"  {0!r:45} -> {1!r}".format(title, new_title))
    changed += 1

print(u"Renamed {0} QC Reference Definition title(s).".format(changed))
transaction.commit()
print(u"Committed.")
