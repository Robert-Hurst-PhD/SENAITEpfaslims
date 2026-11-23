# -*- coding: utf-8 -*-
"""The extraction record's table on its worksheet: the samples, their
amounts and dilutions, the SPE ports, and the lots the guided extraction
used. One JSON annotation under dilution_ref.LOGBOOK_KEY, the key the
stored records already carry.

    load_table(ws)        the stored table, {} when there is none or it
                          cannot be read
    save_table(ws, data)  replace the table, one event on the worksheet's
                          own trail ("extraction record saved")

Every caller merges onto load_table() before it saves: save_table replaces
the whole table, so a caller that wrote only its own keys would erase the
samples the analyst filled in.

Python 2.7 and 3; the storage needs Zope.
"""
from __future__ import absolute_import, unicode_literals

import json

from senaite.pfas.dilution_ref import LOGBOOK_KEY


def load_table(ws):
    from zope.annotation.interfaces import IAnnotations
    raw = IAnnotations(ws).get(LOGBOOK_KEY)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_table(ws, data):
    from zope.annotation.interfaces import IAnnotations
    from senaite.pfas import records
    IAnnotations(ws)[LOGBOOK_KEY] = json.dumps(data)
    records.log(ws, u"extraction record saved")
