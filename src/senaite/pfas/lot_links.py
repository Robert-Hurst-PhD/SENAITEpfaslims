# -*- coding: utf-8 -*-
"""Where a lot opens from Data Review's Traceability: each row's + menu
opens the lot -- a purchased lot in Reagent Inventory, a prepared lot in
Prepared Standards -- and, when one is on file, its certificate (the
supplier's CoA, or the preparation certificate the LIMS made).

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

try:
    from urllib import quote            # Python 2
except ImportError:                     # Python 3
    from urllib.parse import quote

_PAGES = {
    "purchased": (u"@@pfas-reagents", u"Open in Reagent Inventory", u"Open the supplier's CoA"),
    "prepared": (u"@@pfas-prep-standards", u"Open in Prepared Standards", u"Open the preparation certificate"),
}


def lot_menu(kind, lot, portal_url, cert_url=u""):
    """[{"label", "url"}] for a traced lot; [] for one not in the inventory."""
    page = _PAGES.get(kind)
    if not page or not (lot or u"").strip():
        return []
    q = quote((u"%s" % lot).strip().encode("utf-8"))
    out = [{"label": page[1], "url": u"%s/%s?q=%s&status=all" % (portal_url, page[0], q)}]
    if cert_url:
        out.append({"label": page[2], "url": cert_url})
    return out
