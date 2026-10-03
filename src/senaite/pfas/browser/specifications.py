# -*- coding: utf-8 -*-
"""@@pfas-specifications: the Analysis Specifications, grouped (GAPS §96).

SENAITE's own list (bika_setup/bika_analysisspecs) shows one row per method x
QC type x matrix -- the same windows repeated per matrix. This reads the very
same core specs (the ids spec_sync writes) and groups matrices whose ranges
are identical; each row opens the core spec. The specs stay a read-only copy
of the method profiles (D4): change a window on the method's Recovery Tiers.
Python 2.7.
"""
from __future__ import absolute_import

from bika.lims import api
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.pfas import spec_groups
from senaite.pfas.spec_sync import spec_id_for


class PFASSpecificationsView(BrowserView):

    template = ViewPageTemplateFile("templates/specifications.pt")

    def __call__(self):
        return self.template()

    def portal_url(self):
        return api.get_portal().absolute_url()

    def _folder(self):
        return getattr(api.get_portal().bika_setup, "bika_analysisspecs", None)

    def methods(self):
        """[{"id", "label", "url", "rows": [{"qc", "qc_label", "matrices",
        "specs", "windows"}]}] -- one row per QC type x group of matrices."""
        from senaite.pfas.method_profile_store import get_profile, list_method_ids
        from senaite.pfas.qc_labels import get_qc_label_map, qc_label
        portal = api.get_portal()
        folder = self._folder()
        labels = get_qc_label_map(portal)
        self._seen = set()
        out = []
        for mid in sorted(list_method_ids(portal)):
            profile = get_profile(portal, mid) or {}
            rows = []
            for qc in sorted((profile.get("qc_acceptance") or {}).keys()):
                entries = []
                for m in profile.get("supported_matrices") or []:
                    sid = spec_id_for(mid, qc, m)
                    spec = folder.get(sid) if folder is not None else None
                    if spec is None:
                        continue
                    self._seen.add(sid)
                    entries.append({"matrix": m, "url": spec.absolute_url(),
                                    "rows": spec.getResultsRange() or []})
                for g in spec_groups.group(entries):
                    g.update(qc=qc, qc_label=qc_label(None, qc, default=qc, label_map=labels))
                    rows.append(g)
            if rows:
                out.append({"id": mid, "label": profile.get("display_name") or mid,
                            "url": "%s/@@pfas-method-profile-edit?method_id=%s#pane-rt"
                                   % (self.portal_url(), mid),
                            "rows": rows})
        return out

    def others(self):
        """Specs no method profile wrote (made by hand in SENAITE)."""
        folder = self._folder()
        if folder is None:
            return []
        seen = getattr(self, "_seen", set())
        return [{"title": o.Title(), "url": o.absolute_url()}
                for o in folder.objectValues() if o.getId() not in seen]
