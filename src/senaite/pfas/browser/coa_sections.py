# -*- coding: utf-8 -*-
"""Compact Certificate of Analysis sections (part A).

Replaces core impress's header, info, summary, results, discreeter and footer
sections on the PFAS certificate with a conventional lab report layout:

  header   lab identity from Print Settings (the one place the lab maintains
           it; core's Laboratory record was empty, so certificates printed
           "Laboratory Information * * *")
  sample   one compact block of sample facts, not a page of its own
  results  one table: Analyte | CAS | Result | Qual | RL | MDL | Units [| Dil]
           in the method's analyte order, with the method stated once
  legend   what U, RL and MDL mean, and the QC codes in use

Formatting rules live in coa_format.py; limits and units in report_limits.py.
Core sections replaced here are listed in (§6C).
Python 2.7 compatible.
"""
from __future__ import absolute_import

import logging

from bika.lims import api
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.pfas import coa_format
from senaite.pfas import coa_qc_standards
from senaite.pfas import regulatory_limits
from senaite.pfas import report_limits

logger = logging.getLogger("senaite.pfas.coa_sections")

# Analyses in these states never appear on a certificate.
_EXCLUDED_STATES = ("retracted", "rejected", "cancelled", "invalid")


def _fmt_date(value):
    if not value:
        return u""
    try:
        return value.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return u"%s" % value


def injection_rows(sample):
    """(rows, client sample id): the injection rows the sub-table chooses
    from, on the worksheets the sample's analyses were on (a replaced,
    retested analysis's included: injection_results is keyed by worksheet id).
    Also read by the publish guard (guards.QCStandardsGuard)."""
    from senaite.pfas.qc.store import DEFAULT_DB_PATH, QCResultStore
    sid = (sample.getClientSampleID() or u"").strip()
    worksheets = set()
    for an in sample.getAnalyses(full_objects=True):
        ws = an.getWorksheet() if hasattr(an, "getWorksheet") else None
        if ws is not None:
            worksheets.add(ws.getId())
    if not sid or not worksheets:
        return [], sid
    return QCResultStore(DEFAULT_DB_PATH).get_injection_rows(sorted(worksheets), [sid]), sid


def qc_standards_state(sample):
    """The sub-table state the sample's certificate would print with: its
    method x matrix format from the issued revision (else the method's, with
    the batch's project specs applied), so the rounding rule a run was judged
    with is compared with the one the certificate uses. One answer for the
    publish guard (guards.QCStandardsGuard) and the manager's landing queue;
    the certificate itself resolves the same inputs (_sample). Raises when
    the sample's method cannot be identified."""
    from senaite.pfas import report_format
    from senaite.pfas.labelled_standards import ROLE_LABELS
    from senaite.pfas.method_profile_store import get_profile
    from senaite.pfas.project_specs import profile_for_batch
    from senaite.pfas.report_templates import issued_snapshot
    from senaite.pfas.sample_method import identify
    method, problem = identify(sample)
    if problem or method is None:
        raise ValueError(problem or u"no method")
    portal = api.get_portal()
    mid = method.getMethodID()
    bare = get_profile(portal, mid) or {}
    matrix = report_limits.canonical_matrix(bare, sample.getSampleTypeTitle())
    snap, _rev = issued_snapshot(portal)
    src = ({report_format.KEY: (snap.get("report_formats") or {}).get(mid) or {}}
           if snap is not None else (profile_for_batch(portal, sample.getBatch(), mid, matrix) or bare))
    fmt = report_format.resolve(src, matrix)
    rows, sid = injection_rows(sample)
    return coa_qc_standards.build(rows, sid, int(fmt.get("coa_sig_figs") or 3),
                                  fmt.get("coa_rounding") or u"epa", ROLE_LABELS)["state"]


class PFASCoASectionsView(BrowserView):
    """Called from templates/reports/CertificateOfAnalysis.pt with the
    impress collection; renders one of: header, samples, footer."""

    template = ViewPageTemplateFile("templates/coa_sections.pt")

    def __call__(self, collection=None, report_view=None, section="samples"):
        self.collection = collection or []
        self.report_view = report_view
        self.section = section
        return self.template()

    # ── settings / identity ───────────────────────────────────────────────

    def template_revision(self):
        """(snapshot, rev) the certificate is drawn from: a preview's draft
        when one is set, else the ISSUED reporting-template revision; (None,
        None) before any is issued."""
        if not hasattr(self, "_template"):
            override = getattr(self, "snapshot_override", None)
            if override is not None:
                self._template = (override, getattr(self, "snapshot_rev", None))
            else:
                from senaite.pfas.report_templates import issued_snapshot
                self._template = issued_snapshot(api.get_portal())
        return self._template

    def settings(self):
        if not hasattr(self, "_settings"):
            snap, _rev = self.template_revision()
            if snap is not None:
                self._settings = dict(snap.get("print_settings") or {})
            else:
                from senaite.pfas.print_settings import get_print_settings
                self._settings = get_print_settings(api.get_portal())
        return self._settings

    def show(self, key):
        return bool(self.settings().get(key))

    def lab(self):
        s = self.settings()
        contact = [x for x in (s.get("lab_address"), s.get("lab_phone"),
                               s.get("lab_email")) if x]
        return {"name": s.get("lab_name") or u"",
                "contact": u" · ".join(contact),
                "accreditation": s.get("accreditation") or u"",
                "logo": s.get("logo_url") or u""}

    def doc_meta(self):
        """Report ID (with its prospective revision) and issue date for the
        header -- the same identity the controlled-document stamp prints."""
        from DateTime import DateTime
        meta = {"report_id": u"", "issued": DateTime().strftime("%Y-%m-%d"),
                "template_rev": self.template_revision()[1]}
        try:
            att = api.get_portal().restrictedTraverse("@@pfas-coa-attestation")
            meta["report_id"] = att.controlled_doc_meta(self.collection).get("report_id") or u""
        except Exception as exc:                            # noqa: BLE001
            logger.warning("coa_sections: no report id: %s", exc)
        return meta

    # ── samples ───────────────────────────────────────────────────────────

    def samples(self):
        out = []
        for model in self.collection:
            try:
                sample = api.get_object(model)
            except Exception:
                continue
            try:
                out.append(self._sample(sample))
            except Exception as exc:                        # noqa: BLE001
                # A certificate must never silently lose a sample.
                logger.exception("coa_sections: %s", exc)
                out.append({"id": api.get_id(sample), "error": u"%s" % exc})
        return out

    def _analyses(self, sample):
        found = []
        for an in sample.objectValues():
            if getattr(an, "portal_type", "") != "Analysis":
                continue
            try:
                if an.getHidden():
                    continue
            except Exception:
                pass
            if api.get_review_status(an) in _EXCLUDED_STATES:
                continue
            try:
                # a retested analysis (a neat reading replaced by its dilution)
                # is reported by its retest
                if an.isRetested():
                    continue
            except Exception:                               # noqa: BLE001
                pass
            found.append(an)
        return found

    def _method(self, analyses):
        """The one method the reported analyses carry, or None (see
        sample_method: the publish guard uses the same answer)."""
        from senaite.pfas.sample_method import identify_from
        return identify_from(analyses)[0]

    def _sample(self, sample):
        from senaite.pfas.analyte_reference import NATIVE_ANALYTES
        from senaite.pfas.method_profile_store import get_profile
        from senaite.pfas.qc_qualification import parse_remark_codes

        analyses = self._analyses(sample)
        # No identified method -> no certificate for this sample: it would print
        # without the method's RLs, format and limits.
        from senaite.pfas.sample_method import identify_from, project_added
        method, problem = identify_from(analyses, project_added(sample))
        if problem:
            return {"id": api.get_id(sample), "error": problem}
        method_id = method.getMethodID() if method is not None else u""
        profile = get_profile(api.get_portal(), method_id) if method_id else {}
        matrix = report_limits.canonical_matrix(profile, sample.getSampleTypeTitle())
        # what this sample's batch runs to: its project's specs (added
        # analytes, their RLs, ...) apply on the certificate too
        from senaite.pfas.project_specs import profile_for_batch, departures
        method_profile = profile
        profile = profile_for_batch(api.get_portal(), sample.getBatch(), method_id, matrix) or profile
        # criteria the project loosens relative to the laboratory method, for
        # this sample's matrix
        loosened = departures(method_profile, profile, method_id, [matrix]) if profile is not method_profile else []
        # A summed analyte prints its reported name from the method's Isomers
        # tab: the global table names PFOS by its
        # LINEAR peak, "lr-PFOS", which is not what a summed result is.
        from senaite.pfas.method_profile_sections import _analyte_titles
        titles = _analyte_titles(profile or {})
        # A placeholder CAS in the analyte reference must never print as a
        # CAS number; the EDD refuses it separately (REPORT).
        cas = dict((r[0], r[2] if r[2] and "PLACEHOLDER" not in r[2].upper() else u"\u2014")
                   for r in NATIVE_ANALYTES)

        data, analysed, dates = [], [], {}
        for an in analyses:
            kw = an.getKeyword()
            try:
                codes = parse_remark_codes(an.getRemarks() or u"")
            except Exception:
                codes = []
            from senaite.pfas.browser.dilution_retests import dilution_fold
            data.append({"keyword": kw, "title": titles.get(kw) or an.Title(),
                         "result": an.getResult(), "codes": codes,
                         "dilution": dilution_fold(an)})
            when = an.getResultCaptureDate()
            if when:
                analysed.append(when)
            # a retest replaces its original in this list, so a diluted
            # result carries the retest's own date
            dates[kw] = _fmt_date(when)[:10]            # the row shows the day
        # this sample's certificate format: its method x matrix (Reporting tab)
        from senaite.pfas import report_format
        # the format comes from the issued reporting-template revision
        snap, _rev = self.template_revision()
        fmt = report_format.resolve(
            {report_format.KEY: (snap.get("report_formats") or {}).get(method_id) or {}}
            if snap is not None else profile, matrix)
        merged = dict(self.settings())
        merged.update(fmt)
        rows = coa_format.build_rows(data, profile, matrix, merged, cas)
        regulatory = (self._regulatory(sample, data, profile, matrix, rows, fmt)
                      if fmt.get("coa_show_regulatory") else None)
        # fields only a DESIGNED certificate prints: a failure here must never
        # cost the standard certificate its sample; it is recorded, and the
        # designed certificate refuses (coa_document.data)
        enrich_error = u""
        try:
            self._enrich_rows(sample, rows, data, profile, matrix, fmt, dates)
        except Exception as exc:                            # noqa: BLE001
            logger.exception("coa_sections: designed-certificate fields of %s", api.get_id(sample))
            enrich_error = u"%s" % exc
        # surrogate / internal-standard sub-table: never costs
        # the standard certificate its sample; the designed one refuses
        qc_error = u""
        try:
            qc_standards = self._qc_standards(sample, merged)
        except Exception as exc:                            # noqa: BLE001
            logger.exception("coa_sections: QC standards of %s", api.get_id(sample))
            qc_standards = {"state": "error", "rows": [], "injections": 0}
            qc_error = u"%s" % exc
        units = sorted(set(r["unit"] for r in rows if r["unit"]))
        contact = sample.getContact()
        batch = sample.getBatch()
        return {
            "id": api.get_id(sample),
            "client": sample.getClient().Title() if sample.getClient() else u"",
            "contact": contact.getFullname() if contact else u"",
            "client_sid": sample.getClientSampleID() or u"",
            "matrix": sample.getSampleTypeTitle() or u"",
            # "Composite of 12 units: whole egg, shell removed"
            "composite": self._composite(sample),
            # a non-compliant receipt is stated
            "receipt": self._receipt(sample),
            # the method subtracts the batch's method blank
            "blank_subtracted": bool((method_profile or {}).get("blank_subtraction")),
            "batch": batch.getId() if batch else u"",
            "sampled": _fmt_date(sample.getDateSampled()),
            "received": _fmt_date(sample.getDateReceived()),
            "analysed": _fmt_date(max(analysed)) if analysed else u"",
            "method": method.Title() if method is not None else u"",
            "units": u", ".join(units),
            "rows": rows,
            "any_rl": any(r["rl"] for r in rows),
            "codes": sorted(set(c for d in data for c in d["codes"])),
            "regulatory": regulatory,
            "fmt": fmt,
            "qs": self._quality_system(batch),
            "departures": loosened,
            "project_label": self._project_label(batch) if loosened else u"",
            "enrich_error": enrich_error,
            "qc_standards": qc_standards,
            "qc_note": coa_qc_standards.note(merged, qc_standards["state"]),
            "qc_error": qc_error,
        }

    def _composite(self, sample):
        from senaite.pfas import homogenisation as hg
        try:
            req = hg.sample_request(sample)
            return hg.composite_line(req["composite"], req["units"], req["description"])
        except Exception:                                   # noqa: BLE001
            logger.warning("composite line for %s", api.get_id(sample), exc_info=True)
            return u""

    def _receipt(self, sample):
        from senaite.pfas import coc_records as cr
        try:
            num = sample.getField("CoCNumber").get(sample) if sample.getField("CoCNumber") else u""
            rec = cr.load(api.get_portal(), num) if num else None
            rc = (rec or {}).get("receipt") or {}
            if not rc.get("flags"):
                return u""
            return u"Received %s: %s. %s" % (rc.get("received_at") or u"", u"; ".join(rc["flags"]),
                                              rc.get("note") or u"")
        except Exception:                                   # noqa: BLE001
            logger.warning("receipt line for %s", api.get_id(sample), exc_info=True)
            return u""

    def _qc_standards(self, sample, fmt):
        """The sample's neat injection's surrogate recoveries and internal-
        standard responses, as the worker judged them (coa_qc_standards).
        Its runs are the worksheets its analyses were on, a replaced
        (retested) analysis's included: injection_results is keyed by the
        worksheet id."""
        from senaite.pfas.labelled_standards import ROLE_LABELS
        rows, sid = injection_rows(sample)
        return coa_qc_standards.build(rows, sid, int(fmt.get("coa_sig_figs") or 3),
                                      fmt.get("coa_rounding") or u"epa", ROLE_LABELS)

    def _enrich_rows(self, sample, rows, data, profile, matrix, fmt, dates):
        """Each results row's full name (isomer-aware), date of analysis and
        MCL / action level, for designed certificates. The action
        level is the same set of limits the regulatory comparison uses --
        verified, this sample's programs and matrix, switched on for this
        method x matrix -- and only when the format shows the comparison."""
        from senaite.pfas import coa_document, isomers
        from senaite.pfas import report_format
        from senaite.pfas.analyte_reference import NATIVE_ANALYTES
        names = dict((r[0], r[3]) for r in NATIVE_ANALYTES)
        full = dict((d["keyword"], isomers.full_name(profile or {}, d["keyword"], names)) for d in data)
        levels = {}
        if fmt.get("coa_show_regulatory"):
            store = regulatory_limits.get_store(api.get_portal())
            limits = regulatory_limits.applicable(store.get("limits"), self._programs(sample),
                                                  sample.getSampleTypeTitle())
            limits = [l for l in limits if report_format.limit_applies(profile, matrix, l.get("id"))]
            levels = coa_document.action_levels(limits, store.get("programs"))
        coa_document.enrich_rows(rows, full, dates, levels)

    # ── quality system statement ──────────────────

    def _project_label(self, batch):
        try:
            from senaite.pfas import project_ref
            pj = project_ref.get_project(api.get_portal(), batch)
            return (u"%s %s" % (getattr(pj, "project_code", u"") or u"",
                                getattr(pj, "title", u"") or u"")).strip()
        except Exception:                                   # noqa: BLE001
            return u""

    def _quality_system(self, batch):
        """The statement for a sample in `batch`: the project's QAPP (title,
        controlled id, ACTIVE revision) or the lab's internal system."""
        from senaite.pfas import qs_statement
        qapp = None
        try:
            from senaite.pfas import project_ref, ruleset
            portal = api.get_portal()
            project = project_ref.get_project(portal, batch) if batch is not None else None
            doc_id = getattr(project, "qapp_document_id", None) if project is not None else None
            if doc_id:
                from senaite.pfas.browser.projects import _list_qapp_docs
                title = next((d["title"] for d in _list_qapp_docs(portal) if d["sop_id"] == doc_id), doc_id)
                qapp = {"id": doc_id, "title": title, "rev": ruleset._project_source(portal, project)[1],
                        "project": u"%s %s" % (getattr(project, "project_code", u"") or u"",
                                               getattr(project, "title", u"") or u"")}
                qapp["project"] = qapp["project"].strip()
        except Exception as exc:                            # noqa: BLE001
            logger.warning("coa_sections: quality system not resolved: %s", exc)
        return qs_statement.render(self.settings(), qapp)

    # ── regulatory notes (part B) ─────────────────────────────────────────

    def _programs(self, sample):
        """federal + the client's state program (its EDD profile)."""
        progs = [regulatory_limits.FEDERAL]
        try:
            from senaite.pfas.edd_store import get_client_settings, get_edd_profile_for_client
            client = sample.getClient()
            pid = get_edd_profile_for_client(api.get_portal(),
                                             get_client_settings(client) if client else {})[0]
            if pid and pid not in progs:
                progs.append(pid)
        except Exception as exc:                            # noqa: BLE001
            logger.warning("coa_sections: no state program: %s", exc)
        return progs

    def _regulatory(self, sample, data, profile, matrix, rows, fmt=None):
        """Verified limits for this sample's programs and matrix, evaluated.

        Returns None when no verified limit applies (no box is printed)."""
        store = regulatory_limits.get_store(api.get_portal())
        programs = self._programs(sample)
        limits = regulatory_limits.applicable(store.get("limits"), programs,
                                              sample.getSampleTypeTitle())
        # this method x matrix may switch a limit off (Reporting tab)
        from senaite.pfas import report_format
        limits = [l for l in limits if report_format.limit_applies(profile, matrix, l.get("id"))]
        if not limits:
            return None
        unit = next((r["unit"] for r in rows if r["unit"]), None)
        results = {}
        # the certificate's own rows: a detected value is the ROUNDED reported
        # value, and a sum adds the reported values
        by_kw = dict((r["keyword"], r) for r in rows)
        for d in data:
            row = by_kw.get(d["keyword"])
            if row is None or row["detected"] is None:
                continue                                    # unrecognised text: not compared
            lim = report_limits.limits_for(profile, matrix, d["keyword"])
            lim["rl"] = report_limits.scaled_rl(lim["rl"], d.get("dilution"))
            results[d["keyword"]] = {
                "value": float(row["result"]) if row["detected"] else None,
                "rl": lim["rl"]}
        n = int((fmt or self.settings()).get("coa_sig_figs") or 3)
        rule = (fmt or self.settings()).get("coa_rounding") or u"epa"
        names = store.get("programs") or {}
        findings, below, compared = [], 0, 0
        for l in limits:
            ev = regulatory_limits.evaluate(l, results, unit)
            if ev is None:
                continue
            compared += 1
            prog = (names.get(l["program"]) or {}).get("name") or l["program"]
            limit_txt = u"%s %s" % (coa_format.format_limit(l["value"]), l["unit"])
            item = {"label": l["label"], "status": ev["status"], "program": prog,
                    "kind": l["kind"], "limit": limit_txt, "citation": l.get("citation") or u"",
                    "note": l.get("status_note") or u"", "sum": len(l.get("analytes") or []) > 1,
                    "total": u"" if ev["total"] is None else u"%s %s" % (coa_format.sig_figs(ev["total"], n, rule), unit)}
            if ev["status"] == "below":
                below += 1
            else:
                findings.append(item)
        if not compared:
            return None
        links = []
        for pid in programs:
            for link in (names.get(pid) or {}).get("links") or []:
                links.append(link)
        return {"findings": findings, "below": below, "compared": compared, "links": links}
