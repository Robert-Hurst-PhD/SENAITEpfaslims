# -*- coding: utf-8 -*-
"""The notifications bell in the top bar.

"For you": the signed-in person's open notices (notices.py). "Outstanding
actions": what their role acts on -- a manager's attention items
(attention.py) and, for the staff, the equipment checks overdue or with a
required certificate missing. Each entry has a button to where it is fixed;
amber (warn) is a warning, coral (bad) a failure. The count is both lists;
with none the bell shows no badge.

    entries(notices, items, equipment, raw=None) -> {"count", "for_you", "actions"}

notices: [{"title", "ws_id", "text", "raised_at", "url"}], raised_at a stored
UTC stamp, given to the top bar on the laboratory's clock;
items: attention.items with their actions as {"label", "url"};
equipment: [{"name", "status" (equipment_types.due), "url"}];
raw: the import log's raw runs [{"file", "batch_id", "status", "error", "url"}]:
a raw run not pulled, or one the worker could not import, is a failure.
Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

from senaite.pfas import lab_time

_EQUIP = {u"overdue": u"check overdue", u"missing": u"certificate missing"}


def entries(notices, items, equipment, raw=None):
    for_you = [{"level": u"bad", "title": n.get("title") or u"",
                "detail": u"%s: %s" % (n.get("ws_id") or u"", n.get("text") or u""),
                "at": lab_time.show(n.get("raised_at") or u""),
                "actions": [{"label": u"Open", "url": n.get("url") or u""}]} for n in notices or []]
    actions = [{"level": i.get("level") or u"warn", "title": i.get("title") or u"",
                "detail": i.get("detail") or u"", "at": u"", "actions": list(i.get("actions") or [])}
               for i in items or []]
    for e in equipment or []:
        what = _EQUIP.get(e.get("status"))
        if what:
            actions.append({"level": u"bad", "title": u"%s: %s" % (e.get("name") or u"", what),
                            "detail": u"", "at": u"", "actions": [{"label": u"Open", "url": e.get("url") or u""}]})
    for r in raw or []:
        if (r.get("file") or u"").endswith(u".rawrun") and r.get("status") == u"failed":
            actions.append({"level": u"bad", "title": u"%s: raw data not imported" % (r.get("batch_id") or u""),
                            "detail": r.get("error") or u"", "at": u"",
                            "actions": [{"label": u"Instrument Report", "url": r.get("url") or u""}]})
    return {"count": len(for_you) + len(actions), "for_you": for_you, "actions": actions}
