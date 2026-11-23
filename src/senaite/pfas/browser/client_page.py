# -*- coding: utf-8 -*-
"""What a signed-in client sees above the tracking box on @@pfas-track: their
samples with status, then their issued certificates.

Which samples and certificates are listed is decided by SENAITE alone. Every
catalog search here runs as the signed-in user, so core's own client
permissions filter the rows: a client contact holds Owner on their own client
only, and a sample for internal use has View revoked from Owner. Nothing here
filters by client, searches past the catalog's security filter, or switches
user; a certificate's PDF is core's download_pdf, which checks the client's
own permission when it is opened.

The row building is pure (the searches and object reads are handed in), so it
is tested without Zope. Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

SAMPLE_CATALOG = "senaite_catalog_sample"
REPORT_CATALOG = "senaite_catalog_report"
# the states a sample holds once a certificate was issued for it: issued
# (publish, republish), then invalidated after issue
ISSUED_STATES = ("published", "invalid")
# an interim certificate is issued before the run is verified (prepublish):
# its sample holds a register entry in these states too
INTERIM_STATES = ("to_be_verified", "verified")
INTERIM = u"Interim"
SUPERSEDED = u"Superseded"
# the page's own address keys: the sample list's page, the certificate
# list's page and the tracking number shown in the tracking box
PAGE_KEY, CERT_PAGE_KEY, TRACK_KEY = "page", "cpage", "t"
# the sample states the list leaves out, comma-separated: none when absent
OFF_KEY = "off"


def samples_query():
    """Every sample the user may view, newest first."""
    # ZCatalog reads a sort order only as str: a unicode one is read letter
    # by letter and a short result list then fails to sort
    return {"portal_type": "AnalysisRequest", "sort_on": "created", "sort_order": str("descending")}


def issued_query():
    """The user's samples a certificate was issued for, newest first."""
    query = samples_query()
    query["review_state"] = list(ISSUED_STATES + INTERIM_STATES)
    return query


def report_uids(samples):
    """The uids of the certificates named by the samples' issue logs, each
    once. `samples` as certificate_rows takes them."""
    return sorted(set(e.get("report_uid") for _sid, _csid, log in samples
                      for e in log if e.get("report_uid")))


def certificate_rows(samples, report_urls):
    """One row per issue of a certificate, newest first.

    samples      [(sample id, client sample id, issue log)], the log as
                 controlled_publications.get_publication_log gives it
                 (each entry with its computed "status")
    report_urls  {certificate uid: its address}, as the user's own search
                 of the report catalogue found them: a certificate the
                 user may not open has no address, so no PDF button
    """
    rows = []
    for sid, csid, log in samples:
        for e in log:
            uid = e.get("report_uid")
            url = report_urls.get(uid) if uid else None
            marks = []
            if e.get("interim"):
                marks.append({"label": INTERIM, "cls": "badge badge-info"})
            if e.get("status") == "superseded":
                marks.append({"label": SUPERSEDED, "cls": "badge badge-archived"})
            rows.append({"certificate": e.get("report_id") or sid,
                         "sample_id": sid, "client_sid": csid or u"",
                         "issued_at": e.get("issued_at") or u"",
                         "interim": bool(e.get("interim")), "marks": marks,
                         "pdf_url": (url + "/download_pdf") if url else None})
    rows.sort(key=lambda r: r["issued_at"], reverse=True)
    return rows


def current_report_uid(log):
    """The certificate of the sample's current issue (its newest
    revision), None when it has none. `log` as certificate_rows takes it."""
    for e in log or []:
        if e.get("status") == "current":
            return e.get("report_uid") or None
    return None


def with_packages(rows, report_urls):
    """The sample rows, each with "package_url": its current certificate's
    PDF, the package its tier calls for, when the user's own search of the
    report catalogue found it; else None, and no button."""
    for r in rows:
        uid = r.pop("report_uid", None)
        url = report_urls.get(uid) if uid else None
        r["package_url"] = (url + "/download_pdf") if url else None
    return rows


def page_url(base, page, cpage, tracking=None, off=None):
    """The page's address with its two list pages, the tracking number and
    the sample states left out (a comma-separated string)."""
    from senaite.pfas.browser.list_paging import list_url
    return list_url(base, [(PAGE_KEY, page), (CERT_PAGE_KEY, cpage), (TRACK_KEY, tracking), (OFF_KEY, off)])


def ordered_states(present, workflow_order):
    """The sample states to offer, each once, in the workflow's order; a
    state the workflow does not list follows, alphabetically. `present`:
    [(state id, title)]."""
    titles = dict(present)
    known = [s for s in workflow_order or [] if s in titles]
    return [(s, titles[s]) for s in known + sorted(set(titles) - set(known))]


def off_states(asked, offered):
    """The states switched off: those of the comma-separated `asked` that the
    list offers, in the order offered."""
    wanted = set((asked or u"").split(u","))
    return [s for s, _t in offered if s in wanted]


def state_toggles(offered, off, url_for):
    """One toggle per sample state: {"state", "label", "on", "url", "off"},
    the address (and its `off` value) being the page with that state
    switched the other way. `url_for(off list)` gives an address."""
    out = []
    for state, title in offered:
        flipped = [s for s, _t in offered if (s in off) != (s == state)]
        out.append({"state": state, "label": title, "on": state not in off, "url": url_for(flipped),
                    "off": u",".join(flipped)})
    return out


class ClientLists(object):
    """The client's two lists, for the tracker view (a ViewHelpers view:
    self.request, self.portal_url()); times on the laboratory's clock."""

    def client(self):
        """The client of the signed-in contact, else None."""
        if not hasattr(self, "_client"):
            try:
                from bika.lims import api
                self._client = api.get_current_client()
            except Exception:                               # noqa: BLE001
                self._client = None
        return self._client

    def client_name(self):
        from bika.lims import api
        client = self.client()
        return api.get_title(client) if client is not None else u""

    def _pages(self):
        from senaite.pfas.browser.list_paging import page_number
        form = self.request.form
        return page_number(form, PAGE_KEY), page_number(form, CERT_PAGE_KEY)

    def _base(self):
        return self.portal_url() + "/@@pfas-track"

    def _off_param(self, off=None):
        """The states left out, as the address carries them."""
        if off is None:
            if not hasattr(self, "_off"):
                self.client_samples()
            off = self._off
        return u",".join(off) or None

    def client_samples(self):
        """{"rows", "paging", "toggles"}: one page of the user's samples,
        newest first, each with its status as core names the state, those of
        the states switched off left out; the tracking stage is worked out
        only for the sample shown in the tracking box."""
        if not hasattr(self, "_client_samples"):
            from bika.lims import api
            from senaite.pfas.browser.list_paging import paging
            page, cpage = self._pages()
            base = self._base()
            wf = api.get_tool("portal_workflow")
            everything = api.search(samples_query(), SAMPLE_CATALOG)
            offered = ordered_states(
                [(b.review_state, wf.getTitleForStateOnType(b.review_state, "AnalysisRequest") or b.review_state)
                 for b in everything if getattr(b, "review_state", None)], self._workflow_order(wf))
            self._off = off_states(self.request.form.get(OFF_KEY), offered)
            brains = [b for b in everything if getattr(b, "review_state", None) not in self._off]
            pg = paging(len(brains), page,
                        lambda p: page_url(base, p, cpage, self._shown_number(), self._off_param()))
            rows = [self._sample_row(b, wf, base, pg["page"], cpage)
                    for b in brains[pg["start"]:pg["end"]]]
            toggles = state_toggles(offered, self._off, lambda off: page_url(
                base, None, cpage, self._shown_number(), self._off_param(off)))
            self._client_samples = {"rows": with_packages(rows, self._report_urls(
                [r["report_uid"] for r in rows if r.get("report_uid")])), "paging": pg,
                "toggles": toggles, "any": bool(everything)}
        return self._client_samples

    @staticmethod
    def _workflow_order(wf):
        """The sample workflow's states in its own order."""
        try:
            return list(wf.getWorkflowsFor("AnalysisRequest")[0].states.keys())
        except Exception:                                   # noqa: BLE001
            return []

    def _report_urls(self, uids):
        """{report uid: its address} of the reports the user's own search of
        the report catalogue finds among `uids`."""
        if not uids:
            return {}
        from bika.lims import api
        return dict((api.get_uid(b), b.getURL())
                    for b in api.search({"portal_type": "ARReport", "UID": list(uids)}, REPORT_CATALOG))

    def _shown_number(self):
        return (self.request.form.get(TRACK_KEY) or u"").strip().upper() or None

    def _sample_row(self, brain, wf, base, page, cpage):
        from bika.lims import api
        from senaite.pfas import lab_time
        from senaite.pfas.tracking_store import tracking_for
        from senaite.pfas.browser.controlled_publications import get_publication_log
        state = getattr(brain, "review_state", u"") or u""
        received = getattr(brain, "getDateReceived", None)
        obj = api.get_object(brain)
        number = tracking_for(api.get_portal(), obj)[0]
        return {
            "sample_id": api.get_id(brain),
            "client_sid": getattr(brain, "getClientSampleID", u"") or u"",
            "coc": _field(obj, "CoCNumber"),
            "matrix": getattr(brain, "getSampleTypeTitle", u"") or u"",
            "received": lab_time.show(received, fmt=u"%Y-%m-%d") if received else u"",
            "status": wf.getTitleForStateOnType(state, "AnalysisRequest") or state,
            "tracking": number or u"",
            "track_url": (page_url(base, page, cpage, number, self._off_param()) + "#tracking") if number else None,
            # its current certificate, looked up as the user (with_packages)
            "report_uid": current_report_uid(get_publication_log(obj))
            if state in ISSUED_STATES + INTERIM_STATES else None,
        }

    def client_certificates(self):
        """{"rows", "paging"}: one page of every certificate issued for the
        user's samples, newest issue first, interims marked."""
        if not hasattr(self, "_client_certificates"):
            from bika.lims import api
            from senaite.pfas import lab_time
            from senaite.pfas.browser.controlled_publications import get_publication_log
            from senaite.pfas.browser.list_paging import paging
            samples = []
            for brain in api.search(issued_query(), SAMPLE_CATALOG):
                log = get_publication_log(api.get_object(brain))
                if log:
                    samples.append((api.get_id(brain), getattr(brain, "getClientSampleID", u"") or u"", log))
            uids = report_uids(samples)
            urls = {}
            if uids:
                urls = dict((api.get_uid(b), b.getURL())
                            for b in api.search({"portal_type": "ARReport", "UID": uids}, REPORT_CATALOG))
            rows = certificate_rows(samples, urls)
            for r in rows:
                r["issued"] = lab_time.show(r["issued_at"])
            page, cpage = self._pages()
            base = self._base()
            pg = paging(len(rows), cpage, lambda p: page_url(base, page, p, self._shown_number(), self._off_param()))
            self._client_certificates = {"rows": rows[pg["start"]:pg["end"]], "paging": pg}
        return self._client_certificates


def _field(obj, name):
    """A field of the sample as text; empty when it has none."""
    try:
        field = obj.getField(name)
        return u"%s" % (field.get(obj) or u"") if field is not None else u""
    except Exception:                                       # noqa: BLE001
        return u""
