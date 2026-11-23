# -*- coding: utf-8 -*-
"""@@pfas-worksheet-samples on a Worksheet: its method and matrix, and the
received samples of both, added through core.

While the worksheet holds no analyses its method and matrix are chosen here
(the method into core's worksheet Method field, the matrix as the one value
worksheet_samples stores); afterwards they are shown and stay. The list
holds the received samples of that method and matrix whose analyses wait
for a worksheet; samples whose method cannot be identified are listed apart
and cannot be ticked. Add puts every waiting analysis of each ticked sample
on the worksheet through core's addAnalyses, then core's setMethod, reads
each analysis back and says "N of N added" per sample.

PFASAddAnalysesRedirect replaces core's add_analyses on a worksheet (core's
create, the type's Add Analyses tab): it opens this page.
Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import logging

from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.pfas import worksheet_samples as wsm
from senaite.pfas.browser.view_helpers import ViewHelpers

logger = logging.getLogger("senaite.pfas.worksheet_samples")

PAGE = u"@@pfas-worksheet-samples"


def _quote(text):
    try:
        from urllib import quote_plus
    except ImportError:                                     # pragma: no cover
        from urllib.parse import quote_plus
    text = text or u""
    return quote_plus(text if isinstance(text, bytes) else text.encode("utf-8"))


def _text(value):
    """A posted or queried value as text (a byte string under Python 2)."""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value if isinstance(value, type(u"")) else u""


def may_edit(ws):
    """What core's add_analyses asks: edit the worksheet and manage worksheets."""
    from senaite.core.permissions.worksheet import can_edit_worksheet, can_manage_worksheets
    return can_edit_worksheet(ws) and can_manage_worksheets(ws)


class PFASAddAnalysesRedirect(BrowserView):
    """Core's add_analyses on a worksheet opens the samples page."""

    def __call__(self):
        self.request.response.redirect(u"%s/%s" % (self.context.absolute_url(), PAGE))
        return u""


class PFASWorksheetSamplesView(ViewHelpers, BrowserView):

    template = ViewPageTemplateFile("templates/worksheet_samples.pt")

    def __call__(self):
        if not may_edit(self.context):
            return self._redirect(self.context.absolute_url())
        if self.request.method == "POST":
            return self._post()
        return self.template()

    # ── the worksheet ───────────────────────────────────────────────────

    def page_url(self):
        return u"%s/%s" % (self.context.absolute_url(), PAGE)

    def is_open(self):
        from bika.lims import api
        return api.get_review_status(self.context) == "open"

    def locked(self):
        """Method and matrix stay once the worksheet holds analyses."""
        return bool(self.context.getRawAnalyses())

    def current_method(self):
        """Core's worksheet Method, as a method id; an older worksheet
        without one reads what the method resolver names."""
        if not hasattr(self, "_current_method"):
            from senaite.pfas.method_bridge import profile_id_for_method
            m = self.context.getMethod()
            mid = profile_id_for_method(m) if m is not None else u""
            if not mid and self.locked():
                from senaite.pfas import batch_method
                mid = batch_method.for_worksheet(self.context)
            self._current_method = mid or u""
        return self._current_method

    def method_ids(self):
        from senaite.pfas import configured_methods
        return configured_methods.ids(self._portal())

    def method(self):
        """The method the page lists for: the worksheet's once it holds
        analyses, else the one chosen (a configured method), else the
        worksheet's."""
        if self.locked():
            return self.current_method()
        asked = _text(self.request.form.get("method"))
        return asked if asked in self.method_ids() else self.current_method()

    def profile(self):
        if not hasattr(self, "_profile"):
            from senaite.pfas.method_profile_store import get_profile
            mid = self.method()
            self._profile = (get_profile(self._portal(), mid) or {}) if mid else {}
        return self._profile

    def canonical(self, title):
        from senaite.pfas.report_limits import canonical_matrix
        return canonical_matrix(self.profile(), title)

    def matrices(self):
        return list(self.profile().get("supported_matrices") or [])

    def current_matrix(self):
        """The stored matrix, else the one most of the worksheet's samples are
        (a worksheet from before the matrix was stored)."""
        stored = wsm.stored_matrix(self.context)
        if stored or not self.locked():
            return self.canonical(stored) if stored else u""
        from senaite.pfas import extraction_batch as eb
        mats = [self.canonical(s["matrix"]) for s in eb.worksheet_samples(self.context) if s.get("matrix")]
        return max(set(mats), key=mats.count) if mats else u""

    def matrix(self):
        if self.locked():
            return self.current_matrix()
        asked = _text(self.request.form.get("matrix"))
        if asked in self.matrices():
            return asked
        current = self.current_matrix()
        return current if current in self.matrices() else u""

    def method_choices(self):
        from senaite.pfas import configured_methods
        mid = self.method()
        return [{"id": c["id"], "label": c["label"], "on": c["id"] == mid,
                 "url": u"%s?method=%s" % (self.page_url(), _quote(c["id"]))}
                for c in configured_methods.choices(self._portal())]

    def matrix_choices(self):
        mid, mx = self.method(), self.matrix()
        return [{"id": m, "label": m, "on": m == mx,
                 "url": u"%s?method=%s&matrix=%s" % (self.page_url(), _quote(mid), _quote(m))}
                for m in self.matrices()]

    # ── the lists ───────────────────────────────────────────────────────

    def _rows(self):
        if not hasattr(self, "_all_rows"):
            from senaite.pfas import lab_time
            portal = self._portal()
            by_profile = wsm.profile_methods(portal)
            rows = []
            for sample, brains in wsm.unassigned(portal):
                mid, reason = wsm.sample_method_of(portal, sample, by_profile)
                received = lab_time.show(sample.getDateReceived()) if sample.getDateReceived() else u""
                rows.append(wsm.sample_row(sample, brains, mid, reason, received))
            self._all_rows = rows
        return self._all_rows

    def lists(self):
        """(tickable rows, rows apart) for the chosen method and matrix."""
        if not hasattr(self, "_lists"):
            if not (self.method() and self.matrix()):
                self._lists = ([], [])
            else:
                self._lists = wsm.pick_rows(self._rows(), self.method(), self.matrix(), self.canonical)
        return self._lists

    def on_worksheet(self):
        """[{"id", "url", "client_sid", "matrix", "tests"}] per sample the
        worksheet holds, from the analysis catalog."""
        from bika.lims import api
        from senaite.pfas import extraction_batch as eb
        uid = api.get_uid(self.context)
        brains = api.get_tool("senaite_catalog_analysis")(portal_type="Analysis", getWorksheetUID=uid)
        counts = {}
        for b in brains:
            path = str(b.getPath().rsplit(str("/"), 1)[0])
            counts[path] = counts.get(path, 0) + 1
        out = []
        for s in eb.samples_on(self.context):
            out.append({"id": s.getId(), "url": s.absolute_url(), "client_sid": s.getClientSampleID() or u"",
                        "matrix": s.getSampleTypeTitle() or u"",
                        "tests": counts.get(str("/".join(s.getPhysicalPath())), 0)})
        return sorted(out, key=lambda r: r["id"])

    def extraction_url(self):
        return u"%s/@@pfas-extraction-batch" % self.context.absolute_url()

    def results_url(self):
        return u"%s/manage_results" % self.context.absolute_url()

    def message(self):
        f = self.request.form
        return _text(f.get("ok")), _text(f.get("error"))

    # ── Add ─────────────────────────────────────────────────────────────

    def _back(self, ok=u"", error=u"", method=u"", matrix=u""):
        q = [u"ok=" + _quote(ok)] if ok else []
        q += [u"error=" + _quote(error)] if error else []
        if method and not self.locked():
            q += [u"method=" + _quote(method), u"matrix=" + _quote(matrix)]
        return self._redirect(u"%s?%s" % (self.page_url(), u"&".join(q)))

    def _clear_stale_methods(self, chosen, method):
        """An added analysis that still carries another method (core gives
        it the worksheet instrument's first) is cleared, so it takes the
        worksheet's method."""
        from bika.lims import api
        ws_uid = api.get_uid(self.context)
        method_uid = api.get_uid(method)
        for r in chosen:
            for uid, _kw in r["analyses"]:
                an = api.get_object_by_uid(uid, None)
                held = an.getWorksheet() if an is not None else None
                if held is None or api.get_uid(held) != ws_uid:
                    continue
                current = an.getMethod()
                if wsm.stale_method(api.get_uid(current) if current is not None else u"", method_uid):
                    try:
                        an.setMethod(None)
                        an.reindexObject()
                    except Exception:                       # noqa: BLE001
                        logger.warning("worksheet samples: method of %s not cleared", uid, exc_info=True)

    def _post(self):
        from plone.protect import CheckAuthenticator
        CheckAuthenticator(self.request)
        from bika.lims import api
        from senaite.pfas.method_bridge import get_core_method
        form = self.request.form
        ws = self.context
        if not self.is_open():
            return self._back(error=u"This worksheet is closed: no sample can be added.")
        portal = self._portal()
        mid, matrix = self.method(), self.matrix()
        asked_mid, asked_matrix = _text(form.get("method")), _text(form.get("matrix"))
        if self.locked() and (asked_mid, asked_matrix) != (mid, matrix):
            return self._back(error=u"This worksheet's method and matrix are set; they cannot change.")
        if not mid or not matrix:
            return self._back(error=u"Choose the method and the matrix first.")
        method = get_core_method(portal, mid)
        if method is None:
            return self._back(error=u"No SENAITE method is linked to %s." % self.method_name(mid),
                              method=mid, matrix=matrix)
        ticked = form.get("samples") or []
        if not isinstance(ticked, (list, tuple)):
            ticked = [ticked]
        ticked = [_text(u) for u in ticked]
        # the server judges each sample again: what was listed may have changed
        tickable = dict((r["uid"], r) for r in self.lists()[0])
        chosen = [tickable[u] for u in ticked if u in tickable]
        refused = [u for u in ticked if u not in tickable]
        if not chosen:
            return self._back(error=u"Tick the samples to add." if not refused else
                              u"None of the ticked samples is a waiting %s %s sample." % (
                                  self.method_name(mid), matrix), method=mid, matrix=matrix)
        if not self.locked():
            ws.setMethod(method)
            wsm.store_matrix(ws, matrix)
        # every waiting analysis of each ticked sample, through core: core's
        # own assign guard and ours decide what goes on
        ws.addAnalyses([uid for r in chosen for uid, _kw in r["analyses"]])
        ws.setMethod(method, True)
        self._clear_stale_methods(chosen, method)
        ws_uid = api.get_uid(ws)
        lines, whole = [], not refused
        for r in chosen:
            wanted = [uid for uid, _kw in r["analyses"]]
            added = []
            for uid in wanted:
                an = api.get_object_by_uid(uid, None)
                held = an.getWorksheet() if an is not None else None
                if held is not None and api.get_uid(held) == ws_uid:
                    added.append(uid)
            whole = whole and len(added) == len(wanted)
            lines.append(wsm.read_back(r["id"], wanted, added, dict(r["analyses"])))
        if refused:
            lines.append(u"%d ticked sample(s) not added: no longer waiting for this method and matrix"
                         % len(refused))
        text = u"; ".join(lines)
        return self._back(ok=text if whole else u"", error=u"" if whole else text, method=mid, matrix=matrix)
