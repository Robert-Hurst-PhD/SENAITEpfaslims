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
from senaite.pfas import configured_methods
from senaite.pfas import lab_time
from senaite.pfas import regulatory_limits
from senaite.pfas import report_tiers
from senaite.pfas.print_settings import logo_src
from senaite.pfas import report_limits

logger = logging.getLogger("senaite.pfas.coa_sections")

# Analyses in these states never appear on a certificate.
_EXCLUDED_STATES = ("retracted", "rejected", "cancelled", "invalid")


# the certificate's black-and-white variant: one stylesheet, this class on
# each section (pfas-print.css)
MONO_CLASS = "pfas-coa-mono"


def certificate_mono(collection):
    """True when the certificate prints in black and white: the client of
    its primary sample, the one its register entry is kept on, asks for
    it on Client reporting (edd_store.certificate_mono). A sample or client
    that cannot be read prints in colour."""
    from senaite.pfas.edd_store import certificate_mono as client_mono
    for model in list(collection or [])[:1]:
        try:
            return client_mono(api.get_object(model).getClient())
        except Exception as exc:                            # noqa: BLE001
            logger.warning("coa_sections: client print variant unread: %s", exc)
    return False


def variant_class(collection):
    """The class each certificate section carries: the variant's, or none."""
    return MONO_CLASS if certificate_mono(collection) else ""


def _fmt_date(value):
    """A time on the certificate, on the laboratory's clock. While no zone
    converts it is the DateTime's own strftime, which formats on the
    server's clock, as it always printed."""
    if not value:
        return u""
    if lab_time.active():
        return lab_time.show(value, "utc", u"%Y-%m-%d %H:%M")
    try:
        return value.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return u"%s" % value


def injection_rows(sample):
    """(rows, names): the injection rows the sub-table chooses from, on the
    worksheets the sample's analyses were on (a replaced, retested
    analysis's included: injection_results is keyed by worksheet id), and
    what the sample's injections go by (coa_qc_standards.sample_names): the
    names the LIMS issued for it on those worksheets (the worker binds its
    results by them), and its Client Sample ID.
    Also read by the publish guard (guards.QCStandardsGuard)."""
    from senaite.pfas import extraction_batch
    from senaite.pfas.qc.store import DEFAULT_DB_PATH, QCResultStore
    worksheets = {}
    for an in sample.getAnalyses(full_objects=True):
        ws = an.getWorksheet() if hasattr(an, "getWorksheet") else None
        if ws is not None:
            worksheets[ws.getId()] = ws
    issued = []
    uid = api.get_uid(sample)
    for ws_id in sorted(worksheets):
        issued += extraction_batch.sample_injections(extraction_batch.load(worksheets[ws_id]), uid)
    names = coa_qc_standards.sample_names(issued, api.safe_unicode(sample.getClientSampleID() or u""))
    lookup = coa_qc_standards.lookup(names)
    if not lookup or not worksheets:
        return [], names
    return QCResultStore(DEFAULT_DB_PATH).get_injection_rows(sorted(worksheets), lookup), names


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
    rows, names = injection_rows(sample)
    # the places recoveries were judged at are part of the rule a run is checked against
    from senaite.pfas import method_engine
    return coa_qc_standards.build(rows, names, int(fmt.get("coa_sig_figs") or 3),
                                  fmt.get("coa_rounding") or u"epa", ROLE_LABELS,
                                  method_engine.recovery_decimals(bare))["state"]


def _sample_subtype(sample):
    """The sample's sub-type id (SampleSubtype; sample_subtypes), or None."""
    fld = sample.getField("SampleSubtype") if hasattr(sample, "getField") else None
    return (fld.get(sample) if fld is not None else None) or None


def _sample_type_uid(sample):
    """The sample's core Sample Type UID: a limit names its matrices by it."""
    try:
        st = sample.getSampleType()
        return st.UID() if st is not None else None
    except Exception:                                       # noqa: BLE001
        return None


class PFASCoASectionsView(BrowserView):
    """Called from templates/reports/CertificateOfAnalysis.pt with the
    impress collection; renders one of: header, samples, footer."""

    template = ViewPageTemplateFile("templates/coa_sections.pt")

    def print_css(self):
        """The lab theme for this section (print_doc.certificate_css), the
        page number in the centre of the foot of each page."""
        from senaite.pfas import print_doc
        return (print_doc.certificate_css(api.get_portal().absolute_url()) + "\n"
                + print_doc.CERTIFICATE_PAGE_CSS)

    def __call__(self, collection=None, report_view=None, section="samples"):
        self.collection = collection or []
        self.report_view = report_view
        self.section = section
        return self.template()

    def variant(self):
        """The black-and-white class when the client asks for it."""
        if not hasattr(self, "_variant"):
            self._variant = variant_class(self.collection)
        return self._variant

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
        """The Print Settings the certificate prints: the revision's, with
        the laboratory's name, address, phone and e-mail from core's
        Laboratory record (report_templates.printed_settings)."""
        if not hasattr(self, "_settings"):
            from senaite.pfas.print_settings import get_print_settings
            from senaite.pfas.report_templates import printed_settings
            snap, _rev = self.template_revision()
            self._settings = printed_settings(snap, get_print_settings(api.get_portal()))
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
                "logo": self._logo(s)}

    def _logo(self, settings):
        """The logo the header prints: the laboratory's as it is, or, on a
        black-and-white certificate, the same picture in greyscale
        (document_templates.grey_image), drawn for the print only. A logo
        that cannot be read keeps its link."""
        src = logo_src(settings, api.get_portal().absolute_url())
        if src and certificate_mono(getattr(self, "collection", [])):
            from senaite.pfas import document_templates as dt
            from senaite.pfas.browser.coa_document import _logo_uri
            uri = _logo_uri(settings)
            return dt.grey_image(uri) if uri else src
        return src

    def doc_meta(self):
        """Report ID (with its prospective revision) and issue date for the
        header -- the same identity the controlled-document stamp prints."""
        from DateTime import DateTime
        meta = {"report_id": u"", "issued": lab_time.today().isoformat(),
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
        # A placeholder CAS on the service must never print as a CAS number;
        # the EDD refuses it separately (REPORT).
        from senaite.pfas import compound_library, compound_library_store
        cas = dict((kw, c if c and "PLACEHOLDER" not in c.upper() else u"\u2014")
                   for kw, c in compound_library.cas_by_keyword(compound_library_store.library(), dashed=True).items())

        data, analysed, dates, times, undated, early, early_at = [], [], {}, {}, [], [], []
        # the codes the batch or report carries (a rule's flag placed there):
        # one line for the report, never a row's
        batch_items = []
        # a flag's output: the codes only the EDD issues, those only the
        # certificate prints, by analyte
        edd_only, coa_only = {}, {}
        received = sample.getDateReceived()
        # when each result was analysed: its injection's acquisition, else
        # its capture in SENAITE (analysed_at, shared with the EDD)
        from senaite.pfas import analysed_at
        acquired = analysed_at.acquired_by_uid([api.get_uid(an) for an in analyses])
        for an in analyses:
            kw = an.getKeyword()
            try:
                stamped = parse_remark_codes(an.getRemarks() or u"")
            except Exception:
                stamped = []
            # the codes stamped at release and those the worksheet's quality
            # control puts on the result now: one list for the row, the
            # qualification text and the EDD; a code the plan places on the
            # batch or report is the report's, never the row's
            planned, batch = self._planned_places(an)
            edd_only[kw], coa_only[kw] = self._edd_output(an)
            for item in batch:
                if item not in batch_items:
                    batch_items.append(item)
            whole = set(c for c, _s in batch) - set(c for c, _s in planned)
            codes = coa_format.carried_codes([c for c in stamped if c not in whole], [c for c, _s in planned])
            statements = {}
            for code, statement in planned:
                if statement and statement not in statements.setdefault(code, []):
                    statements[code].append(statement)
            for code in codes:
                # stamped, and no longer in the summary: the library's wording
                if not statements.get(code):
                    statements[code] = [t for t in (self._library_statement(code),) if t]
            from senaite.pfas.browser.dilution_retests import dilution_fold
            from senaite.pfas.above_range import of as above_range_of
            from senaite.pfas import verified_rl
            from senaite.pfas.browser.run_builder import analysis_acid_basis
            data.append({"keyword": kw, "title": titles.get(kw) or api.safe_unicode(an.Title()),
                         "result": an.getResult(), "codes": codes, "statements": statements,
                         "frozen_rl": verified_rl.frozen_for(an),
                         # above the calibration range with no dilution: its top
                         "above": (above_range_of(an) or {}).get("limit"),
                         # the high-bias note names its QC type: one line each
                         "separate": self._high_bias_codes(),
                         "dilution": dilution_fold(an),
                         # its run's standards stated as the acid: no salt in its default RL
                         "acid_basis": kw.upper() in [a.upper() for a in analysis_acid_basis(
                             an, self.__dict__.setdefault("_acid_basis_cache", {}))]})
            when = analysed_at.shown(acquired.get(api.get_uid(an)), an.getResultCaptureDate(), _fmt_date)
            if when:
                analysed.append(when)
                # analysed before the sample was received, on the laboratory's clock
                if analysed_at.before_receipt(analysed_at.wall(acquired.get(api.get_uid(an)),
                                                               an.getResultCaptureDate()), received):
                    early.append(titles.get(kw) or api.safe_unicode(an.Title()) or kw)
                    early_at.append((titles.get(kw) or api.safe_unicode(an.Title()) or kw, when))
            elif (an.getResult() or u"").strip():
                # a result that is reported (it holds a value) and has no date
                undated.append(titles.get(kw) or api.safe_unicode(an.Title()) or kw)
            # a retest replaces its original in this list, so a diluted
            # result carries the retest's own date
            dates[kw] = when[:10]                       # the row shows the day
            times[kw] = when                            # a dilution's footnote: day and time
        # this sample's certificate format: its method x matrix (Reporting tab)
        # the format comes from the issued reporting-template revision
        # (report_templates.certificate_format, shared with Data Review)
        from senaite.pfas.report_templates import certificate_format
        snap, _rev = self.template_revision()
        merged, fmt = certificate_format(snap, method_id, profile, matrix, self.settings())
        rows = coa_format.build_rows(data, profile, matrix, merged, cas)
        batch_codes = []
        for code, _s in batch_items:
            if code not in batch_codes:
                batch_codes.append(code)
        for r in rows:
            # the EDD issues the report's codes on every row (one placement)
            r["batch_codes"] = list(batch_codes)
            r["edd_codes"] = list(edd_only.get(r["keyword"]) or [])
            r["coa_only_codes"] = list(coa_only.get(r["keyword"]) or [])
        regulatory = (self._regulatory(sample, data, profile, matrix, rows, fmt)
                      if fmt.get("coa_show_regulatory") else None)
        # fields only a DESIGNED certificate prints: a failure here must never
        # cost the standard certificate its sample; it is recorded, and the
        # designed certificate refuses (coa_document.data)
        enrich_error = u""
        try:
            self._enrich_rows(sample, rows, data, profile, matrix, fmt, dates, times)
        except Exception as exc:                            # noqa: BLE001
            logger.exception("coa_sections: designed-certificate fields of %s", api.get_id(sample))
            enrich_error = u"%s" % exc
        # surrogate / internal-standard sub-table: never costs
        # the standard certificate its sample; the designed one refuses
        qc_error = u""
        try:
            qc_standards = self._qc_standards(sample, merged, method_profile)
        except Exception as exc:                            # noqa: BLE001
            logger.exception("coa_sections: QC standards of %s", api.get_id(sample))
            qc_standards = {"state": "error", "rows": [], "injections": 0}
            qc_error = u"%s" % exc
        # a QC type the method requires every run that the run did not hold,
        # with the deviation that released it: never costs the standard
        # certificate its sample; the designed one refuses unread
        qc_not_run, not_run_error = self._qc_not_run(analyses)
        units = sorted(set(r["unit"] for r in rows if r["unit"]))
        # the method x matrix reporting unit: one per sample, the Result heading
        result_unit = ((profile or {}).get("unit_map") or {}).get(matrix) or u", ".join(units)
        contact = sample.getContact()
        batch = sample.getBatch()
        # the tier the sample reports at: its own, else its client's default
        # now; an id the issued catalogue lacks prints blank, never another tier
        _tier, tier_id, tiers, _tiers_rev = report_tiers.resolve(sample, api.get_portal())
        return {
            "id": api.get_id(sample),
            "client": api.safe_unicode(sample.getClient().Title()) if sample.getClient() else u"",
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
            "received": _fmt_date(received),
            # the latest: "YYYY-MM-DD HH:MM" sorts as time
            "analysed": max(analysed) if analysed else u"",
            # the method's one name: its profile's display name
            "method": configured_methods.method_label(method_profile, method_id),
            "report_tier": report_tiers.label(tiers, tier_id),
            "units": u", ".join(units),
            "result_unit": result_unit,
            "rows": rows,
            "rule_codes": self._rule_codes(rows),
            # the legend: a line per code on the page, in the lab's wording
            "legend_codes": self._legend_codes(rows, batch_items),
            # the codes the batch or report carries, beside the results heading
            "batch_codes": batch_codes,
            # the key on a page of its own: a rule of the issued revision
            # (report_format.RULE_DEFAULTS; an older revision keeps it under the table)
            "legend_page": merged.get("coa_legend_page") == "yes",
            "any_rl": any(r["rl"] for r in rows),
            "codes": coa_format.qc_codes(rows),
            # the qualification text, read from the rows that print the codes
            "qualifications": coa_format.qualifications(rows),
            "regulatory": regulatory,
            "fmt": fmt,
            "qs": self._quality_system(batch),
            "departures": loosened,
            "project_label": self._project_label(batch) if loosened else u"",
            # reported results with no analysis date: the certificate is refused
            # (coa_document.data); the EDD does not read this
            "undated": undated,
            # results analysed before the sample was received: refused there too
            "early": early,
            # each with its analysis time as printed, for the refusal page
            "early_at": early_at,
            "enrich_error": enrich_error,
            "qc_standards": qc_standards,
            "qc_note": coa_qc_standards.note(merged, qc_standards["state"]),
            "qc_error": qc_error,
            "qc_not_run": qc_not_run,
            "qc_not_run_error": not_run_error,
        }

    def _review_of(self, ws):
        """The worksheet's Data Review view, one per worksheet and
        certificate: its QC summary is built once for every reading."""
        reviews = self.__dict__.setdefault("_reviews", {})
        key = api.get_uid(ws)
        if key not in reviews:
            reviews[key] = ws.restrictedTraverse(str("@@pfas-data-review"))
        return reviews[key]

    def _qc_not_run(self, analyses):
        """([{"qc_type", "dev_id"}], error): the QC types required every run
        that the runs of the reported analyses did not hold, once per
        worksheet and certificate, each type once; error is u"" or why a
        worksheet's gate could not be read. A worksheet's statement frozen
        at verification (verified_rl) is printed as frozen; one verified
        before the freeze is read live (PFASDataReviewView.qc_types_not_run)."""
        from senaite.pfas import verified_rl
        from senaite.pfas.qc_deviation import merge_not_run
        found = self.__dict__.setdefault("_not_run", {})
        lists, errors, seen = [], [], set()
        for an in analyses:
            try:
                ws = an.getWorksheet()
            except Exception:                               # noqa: BLE001
                ws = None
            if ws is None:
                continue
            key = api.get_uid(ws)
            if key not in found:
                frozen = verified_rl.frozen_not_run_for(ws)
                if frozen is not None:
                    found[key] = (frozen["not_run"], u"")
                else:
                    try:
                        found[key] = (self._review_of(ws).qc_types_not_run(ws), u"")
                    except Exception as exc:                # noqa: BLE001
                        logger.exception("coa_sections: QC types not run of %s", api.get_id(ws))
                        found[key] = ([], u"%s" % exc)
            if key in seen:
                continue
            seen.add(key)
            lines, error = found[key]
            if error:
                errors.append(error)
            lists.append(lines)
        return merge_not_run(lists), u"; ".join(errors)

    def _planned_places(self, analysis):
        """([(code, statement)] for the row, [(code, statement)] for the
        batch or report): the worksheet's plan for the analysis split by
        where each code prints (rule_flags place "batch" the report's)."""
        from senaite.pfas.rule_flags import is_batch, on_certificate
        row, batch = [], []
        for e in self._plan_entries(analysis):
            if not on_certificate(e):
                continue                # an EDD-only flag's code: the EDD's alone
            item = (e.get("code") or u"", e.get("statement") or u"")
            into = batch if is_batch(e) else row
            if item[0] and item not in into:
                into.append(item)
        return row, batch

    def _edd_output(self, analysis):
        """([codes only the EDD issues], [codes only the certificate
        prints]) for the analysis: a flag's output (rule_flags). A code
        another entry issues to both is neither."""
        from senaite.pfas.rule_flags import on_certificate, on_edd
        entries = [e for e in self._plan_entries(analysis) if e.get("code")]
        cert = set(e["code"] for e in entries if on_certificate(e))
        edd = set(e["code"] for e in entries if on_edd(e))
        return sorted(edd - cert), sorted(cert - edd)

    def _planned_qualifiers(self, analysis):
        """[(code, statement)]: the codes the plan puts on the analysis's
        own row (_planned_places)."""
        return self._planned_places(analysis)[0]

    def _plan_entries(self, analysis):
        """[entry]: the qualifiers the analysis' worksheet puts on it now
        (Data Review's plan, the one its release stamps), each with its code,
        the lab's wording and, for a rule's flag, its place. The worksheet's plan is read once per
        certificate. A plan that cannot be read is logged and leaves the
        stamped codes."""
        try:
            ws = analysis.getWorksheet()
        except Exception:                                   # noqa: BLE001
            ws = None
        if ws is None:
            return []
        plans = self.__dict__.setdefault("_qualifier_plans", {})
        key = api.get_uid(ws)
        if key not in plans:
            try:
                plans[key] = self._review_of(ws)._qualifier_entries(ws)
            except Exception:                               # noqa: BLE001
                logger.exception("coa_sections: qualifier plan of %s", api.get_id(ws))
                plans[key] = None
        entries_for = plans[key]
        if entries_for is None:
            return []
        return list(entries_for(analysis))

    def _high_bias_codes(self):
        """[the QC Qualifiers library's high-bias code], [] while it has
        none: its notes name their QC type, so each prints on its own line."""
        code = ((self._library() or {}).get("high_bias") or {}).get("code") or u""
        return [code] if code else []

    def _library(self):
        """The QC Qualifiers library, read once per view; the seed wording
        when it cannot be read."""
        if not hasattr(self, "_qualifier_library"):
            from senaite.pfas import qc_qualification
            try:
                self._qualifier_library = qc_qualification.get_library(api.get_portal())
            except Exception:                               # noqa: BLE001
                logger.warning("coa_sections: qualifier library unreadable; seed wording", exc_info=True)
                self._qualifier_library = qc_qualification.DEFAULT_LIBRARY
        return self._qualifier_library

    def _library_statement(self, code):
        """The QC Qualifiers library's wording for a code it gives one
        wording (coa_format.library_statement)."""
        return coa_format.library_statement(self._library(), code)

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
            return u"Received %s: %s. %s" % (cr.received_in_force(rec), u"; ".join(rc["flags"]),
                                              rc.get("note") or u"")
        except Exception:                                   # noqa: BLE001
            logger.warning("receipt line for %s", api.get_id(sample), exc_info=True)
            return u""

    def _qc_standards(self, sample, fmt, profile=None):
        """The sample's neat injection's surrogate recoveries and internal-
        standard responses, as the worker judged them (coa_qc_standards),
        a recovery to the method's decimal places (method_engine).
        Its runs are the worksheets its analyses were on, a replaced
        (retested) analysis's included: injection_results is keyed by the
        worksheet id."""
        from senaite.pfas.labelled_standards import ROLE_LABELS
        rows, names = injection_rows(sample)
        from senaite.pfas import method_engine
        return coa_qc_standards.build(rows, names, int(fmt.get("coa_sig_figs") or 3),
                                      fmt.get("coa_rounding") or u"epa", ROLE_LABELS,
                                      method_engine.recovery_decimals(profile))

    def _legend_codes(self, rows, batch=None):
        """The legend's lines (coa_format.legend_lines): every code on the
        page in the QC Qualifiers library's wording."""
        return coa_format.legend_lines(rows, self._rule_wording(), batch)

    def _rule_wording(self):
        """{J, D, N.Q., E: the reporting rule's wording in QC Qualifiers}."""
        library = self._library() or {}
        return {coa_format.J_CODE: (library.get("between_mdl_rl") or {}).get("statement"),
                coa_format.D_CODE: (library.get("dilution") or {}).get("statement"),
                coa_format.NQ_CODE: (library.get("not_quantified") or {}).get("statement"),
                coa_format.E_CODE: (library.get("above_range") or {}).get("statement")}

    def _rule_codes(self, rows):
        """The legend's J, D, N.Q. and E lines, in the QC Qualifiers
        library's wording, for the codes the rows carry."""
        from senaite.pfas import qc_qualification
        try:
            library = qc_qualification.get_library(api.get_portal())
        except Exception:                                   # noqa: BLE001
            logger.warning("coa_sections: qualifier library unreadable; seed wording", exc_info=True)
            library = qc_qualification.DEFAULT_LIBRARY
        wording = {coa_format.J_CODE: (library.get("between_mdl_rl") or {}).get("statement"),
                   coa_format.D_CODE: (library.get("dilution") or {}).get("statement"),
                   coa_format.NQ_CODE: (library.get("not_quantified") or {}).get("statement"),
                   coa_format.E_CODE: (library.get("above_range") or {}).get("statement")}
        return coa_format.rule_codes(rows, wording)

    def _enrich_rows(self, sample, rows, data, profile, matrix, fmt, dates, times=None):
        """Each results row's full name (isomer-aware), date of analysis (the
        day, and the date and time for a dilution's footnote) and
        MCL / action level, for designed certificates. The action
        level is the same set of limits the regulatory comparison uses --
        verified, this sample's programs and matrix, switched on for this
        method x matrix -- and only when the format shows the comparison."""
        from senaite.pfas import coa_document, isomers
        from senaite.pfas import report_format
        from senaite.pfas import compound_library, compound_library_store
        names = compound_library.full_names(compound_library_store.library())
        full = dict((d["keyword"], isomers.full_name(profile or {}, d["keyword"], names)) for d in data)
        levels = {}
        if fmt.get("coa_show_regulatory"):
            store = regulatory_limits.get_store(api.get_portal())
            limits = regulatory_limits.applicable(store.get("limits"), self._programs(sample),
                                                  sample.getSampleTypeTitle(), _sample_type_uid(sample),
                                                  subtype=_sample_subtype(sample))
            limits = [l for l in limits if report_format.limit_applies(profile, matrix, l.get("id"))]
            levels = coa_document.action_levels(limits, store.get("programs"))
        coa_document.enrich_rows(rows, full, dates, levels, times)

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
        controlled id, ACTIVE revision) or the lab's internal system (naming
        the document marked as the laboratory's QAM)."""
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
        qam = None
        try:
            from senaite.pfas.browser.sop_documents import lab_qam
            qam = lab_qam(api.get_portal())
        except Exception as exc:                            # noqa: BLE001
            logger.warning("coa_sections: laboratory QAM not resolved: %s", exc)
        return qs_statement.render(self.settings(), qapp, qam)

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
                                              sample.getSampleTypeTitle(), _sample_type_uid(sample),
                                              subtype=_sample_subtype(sample))
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
            lim = report_limits.limits_with_frozen(
                profile, matrix, d["keyword"], d.get("frozen_rl"),
                acid_basis=[d["keyword"]] if d.get("acid_basis") else None)
            lim["rl"] = report_limits.scaled_rl(lim["rl"], d.get("dilution"))
            # a J value (below the RL) is detected: it counts at its value
            results[d["keyword"]] = {
                "value": regulatory_limits.compared_value(row),
                "rl": lim["rl"]}
        n = int((fmt or self.settings()).get("coa_sig_figs") or 3)
        rule = (fmt or self.settings()).get("coa_rounding") or u"epa"
        names = store.get("programs") or {}
        findings, below, compared, test_data = [], 0, 0, False
        for l in limits:
            ev = regulatory_limits.evaluate(l, results, unit)
            if ev is None:
                continue
            compared += 1
            prog = (names.get(l["program"]) or {}).get("name") or l["program"]
            kind = l["kind"]
            if regulatory_limits.is_test_data(l):
                # test data is no programme's limit: it says so instead
                test_data = True
                prog, kind = regulatory_limits.TEST_DATA_MARK, u"limit"
            limit_txt = u"%s %s" % (coa_format.format_limit(l["value"]), l["unit"])
            item = {"label": l["label"], "status": ev["status"], "program": prog,
                    "kind": kind, "limit": limit_txt, "citation": l.get("citation") or u"",
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
            # a program's note is about what it regulates: only on its matrices
            if not regulatory_limits.covers(store.get("limits"), pid, sample.getSampleTypeTitle(),
                                            _sample_type_uid(sample)):
                continue
            for link in (names.get(pid) or {}).get("links") or []:
                links.append(link)
        return {"findings": findings, "below": below, "compared": compared, "links": links,
                "test_data": test_data}
