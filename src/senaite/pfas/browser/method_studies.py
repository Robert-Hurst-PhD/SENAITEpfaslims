# -*- coding: utf-8 -*-
"""Method studies (@@pfas-method-studies). Python 2.7.

The list of studies and one study at a time (?id=MS-0001): its replicates,
drawn from the QC database (study_data), the calculation per analyte
(method_studies), documented exclusions, and QA approval. Approval freezes
the results, writes the study's MDL / RL to the method profile (recorded in
configuration history with the study as its source) and freezes the packet
PDF under /data/qc/studies/.

Staff create studies and exclude results with a reason; approval and
assigning a study's parts to analysts (study_runs: one worksheet per part)
are manager tier (perms.TIER_CONFIG). A reference sample's receipt is
recorded here by any staff member, beside its CoA.
"""
from __future__ import absolute_import, unicode_literals

import logging
import os
import sqlite3
from datetime import date, datetime, timedelta

from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from senaite.pfas import study_data as sd
from senaite.pfas import study_records as sr
from senaite.pfas import study_runs as sru
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import TIER_CONFIG, GateMixin, deny_gated_action, is_staff, refuse

logger = logging.getLogger("senaite.pfas.browser.method_studies")

GATES = {"approve": TIER_CONFIG, "assign": TIER_CONFIG, "charts": TIER_CONFIG,
         "delete_draft": TIER_CONFIG}
QC_DB = os.environ.get("PFAS_QC_DB", "/data/qc/pfas_qc_results.db")
PDF_DIR = os.path.join(os.path.dirname(QC_DB), "studies")


def _now():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")


def _user():
    from plone import api as papi
    try:
        u = papi.user.get_current()
        return u.getProperty("fullname") or u.getId()
    except Exception:                                       # noqa: BLE001
        return u""


class PFASMethodStudiesView(BrowserView, GateMixin):

    template = ViewPageTemplateFile("templates/method_studies.pt")
    print_template = ViewPageTemplateFile("templates/method_study_pdf.pt")

    def __call__(self):
        flatten_form(self.request)
        if not is_staff(self.portal()):
            return refuse(self.request)
        f = self.request.form
        self.message, self.error = u"", u""
        if f.get("pdf") and self.record() is not None:
            return self._serve_pdf()
        if f.get("certificate") and self.record() is not None:
            return self._serve_certificate()
        if f.get("asymmetry_pdf") and self.record() is not None:
            return self._serve_asymmetry()
        if f.get("evidence_file") and self.record() is not None:
            return self._serve_evidence()
        if self.request.get("REQUEST_METHOD") == "POST":
            action = f.get("action") or u""
            denied = deny_gated_action(self.context, self.request, action, GATES)
            if denied is not None:
                return denied
            try:
                from plone.protect import CheckAuthenticator
                CheckAuthenticator(self.request)
            except ImportError:
                pass
            if action == "create":
                return self._create()
            if action == "exclude":
                self._exclude()
            elif action == "save_pt":
                self._save_pt()
            elif action == "approve":
                self._approve()
            elif action == "assign":
                self._assign()
            elif action == "receipt":
                self._receipt()
            elif action == "charts":
                self._charts()
            elif action == "idc_save":
                self._save_idc()
            elif action == "design_entry":
                self._design_entry()
            elif action == "delete_draft":
                return self._delete_draft()
        return self.template()

    # ── identity ───────────────────────────────────────────────────────────
    def portal(self):
        return getToolByName(self.context, "portal_url").getPortalObject()

    def portal_url(self):
        return self.portal().absolute_url()

    def records(self):
        if not hasattr(self, "_records"):
            self._records = sr.load(self.portal())
        return self._records

    def listed(self):
        return list(reversed(self.records()))

    def mdl_due(self):
        """Annual MDL verification: when each method x matrix is due."""
        from datetime import date
        return sr.mdl_due(self.records(), date.today().isoformat())

    def record(self):
        return sr.find(self.records(), (self.request.form.get("id") or u"").strip())

    def kinds(self):
        """The study kinds, and every template designed in the Study Designer."""
        from senaite.pfas import study_templates as st
        return list(sd.KINDS) + [(u"tpl:%s" % t["id"], t["name"]) for t in st.load(self.portal())]

    def kind_label(self, kind, rec=None):
        if kind == "designed":
            return ((rec or self.record() or {}).get("design") or {}).get("name") or u"Designed study"
        return sd.KIND_LABELS.get(kind, kind)

    def methods(self):
        from senaite.pfas.method_profile_store import list_method_ids
        return list_method_ids(self.portal())

    def profile(self, method_id=None):
        from senaite.pfas.method_profile_store import raw_profile
        rec = self.record()
        return raw_profile(self.portal(), method_id or (rec or {}).get("method")) or {}

    def matrices(self):
        out = []
        for m in self.methods():
            for x in self.profile(m).get("supported_matrices") or []:
                if x not in out:
                    out.append(x)
        return out

    def default_since(self):
        return (date.today() - timedelta(days=365 * sd.MDL_MONTHS // 12)).isoformat()

    # ── the data ───────────────────────────────────────────────────────────
    def _levels(self, batch_ids):
        """{(worksheet, injection): spike level label} from the extraction
        batches' members."""
        from senaite.pfas import extraction_batch as eb
        from bika.lims import api
        out = {}
        cat = api.get_tool("senaite_catalog_worksheet")
        for bid in batch_ids:
            for b in cat(portal_type="Worksheet", id=bid):
                for m in eb.load(b.getObject()):
                    if m.get("injection"):
                        out[(bid, m["injection"])] = m.get("level") or u""
        return out

    left_out = ()
    REVIEWED_STATES = ("verified", "published")

    def _reviewed(self, batch_ids):
        """The worksheets among `batch_ids` that passed technical review: core
        verified or published, or -- a study worksheet, which has no analyses
        -- approved on its Data Review checklist."""
        from bika.lims import api
        if not batch_ids:
            return set()
        cat = api.get_tool("senaite_catalog_worksheet")
        out = set()
        for b in cat(portal_type="Worksheet", id=sorted(batch_ids)):
            if b.review_state in self.REVIEWED_STATES:
                out.add(b.getId)
                continue
            ws = b.getObject()
            if sru.load_run(ws) is not None and sru.checklist_review_state(
                    b.review_state, bool(ws.getAnalyses()), sru.checklist_of(ws)) == u"verified":
                out.add(b.getId)
        return out

    def data(self):
        """(spikes, blanks) for the open study."""
        if hasattr(self, "_data"):
            return self._data
        rec = self.record()
        spikes, blanks = [], []
        if rec is not None and os.path.exists(QC_DB):
            conn = sqlite3.connect(QC_DB)          # read only: nothing is written here
            try:
                if rec["kind"] == "mdl":
                    spikes = sd.injections(conn, rec["method"], ["LFB"], since=rec.get("since") or None,
                                           until=rec.get("until") or None, matrix=rec["matrix"])
                    blanks = sd.injections(conn, rec["method"], [sd.blank_role(rec["method"])],
                                           since=rec.get("since") or None, until=rec.get("until") or None,
                                           matrix=rec["matrix"])
                else:
                    spikes = sd.injections(conn, rec["method"], ["LFB"],
                                           batches=sru.study_worksheets(rec) or [u"-"])
            finally:
                conn.close()
            # runs that passed technical review only: an
            # open run is listed as left out, never pooled
            reviewed = self._reviewed(set(r["batch"] for r in spikes + blanks))
            self.left_out = sorted(set(r["batch"] for r in spikes + blanks) - reviewed)
            spikes = [r for r in spikes if r["batch"] in reviewed]
            blanks = [r for r in blanks if r["batch"] in reviewed]
            levels = self._levels(sorted(set(r["batch"] for r in spikes)))
            spikes = [dict(r, level=levels.get((r["batch"], r["injection"])) or u"") for r in spikes]
            if rec.get("levels"):
                spikes = [r for r in spikes if r["level"] in rec["levels"]]
        self._data = (spikes, blanks)
        return self._data

    def fortified(self, level):
        """The fortified concentration of one level: typed on the study (one
        level), else the method's LFB spike level in the matrix's unit."""
        rec = self.record() or {}
        if rec.get("fortified") not in (None, u"") and len(rec.get("levels") or []) <= 1:
            return float(rec["fortified"])
        from senaite.pfas.calibration_levels import level_value, matrix_unit
        prof = self.profile()
        unit = matrix_unit(prof, rec.get("matrix"))
        levels = ((prof.get("spike_levels") or {}).get(rec.get("matrix")) or {}).get("LFB") or []
        for e in levels:
            if e.get("label") == level:
                return level_value(e, unit)
        return None

    def fortified_by_level(self):
        spikes, _blanks = self.data()
        return dict((lv, self.fortified(lv)) for lv in set(r.get("level") or u"" for r in spikes))

    def level_labels(self):
        """Every LFB spike level label the methods define (the form's choices)."""
        out = []
        for m in self.methods():
            for per in (self.profile(m).get("spike_levels") or {}).values():
                for e in (per or {}).get("LFB") or []:
                    if e.get("label") and e["label"] not in out:
                        out.append(e["label"])
        return out

    def reference_lots(self):
        """Usable reference-material lots (the inventory's own category)."""
        return self.lot_options(sru.REFERENCE_LOT)

    def pt_analytes(self):
        rec = self.record() or {}
        prof = self.profile()
        return list(prof.get("display_analyte_set") or prof.get("master_analyte_set") or [])

    def pt_verdicts(self):
        return sd.PT_VERDICTS

    def pt_problems(self):
        rec = self.record() or {}
        return sd.pt_problems(rec.get("pt"), self._certificate_present(rec))

    def existing(self):
        rec = self.record() or {}
        rls = (self.profile().get("reporting_limits") or {}).get(rec.get("matrix")) or {}
        return dict((kw, v.get("mdl")) for kw, v in rls.items() if isinstance(v, dict) and v.get("mdl"))

    def results(self):
        """{level: {keyword: result}}; a PT study's {"": its per-analyte rows}."""
        rec = self.record()
        if rec is None:
            return {}
        if rec.get("kind") in ("idc", "designed"):
            return {}              # read element by element (idc_elements, design_results)
        if rec.get("status") != sr.DRAFT:
            return rec.get("results") or {}
        if rec["kind"] == "pt":
            rows = (rec.get("pt") or {}).get("results") or {}
            return {u"": dict((kw, dict(r, verdict=r.get("verdict") or u"not evaluated"))
                              for kw, r in rows.items())}
        spikes, blanks = self.data()
        return sd.calculate_levels(rec["kind"], spikes, blanks, self.fortified_by_level(),
                                   rec.get("exclusions"), self.existing())

    # ── initial demonstration of capability (idc.py) ─────────────────────
    def _qc_rows(self, qc_type, batches):
        """[{"passed"}] the runs stored for `qc_type` on `batches`."""
        if not batches or not os.path.exists(QC_DB):
            return []
        conn = sqlite3.connect(QC_DB)          # read only
        try:
            q = ("SELECT passed FROM qc_results WHERE result_status='active' AND qc_type=? "
                 "AND batch_id IN (%s)" % ",".join("?" * len(batches)))
            return [{"passed": p} for (p,) in conn.execute(q, [qc_type] + list(batches))]
        finally:
            conn.close()

    def _part_worksheets(self, element):
        rec = self.record() or {}
        reviewed = self._reviewed(set(w for p in rec.get("parts") or [] if p.get("element") == element
                                      for w in p.get("worksheets") or []))
        return sorted(reviewed)

    def _part_results(self, element, kind):
        rec = self.record() or {}
        ws = self._part_worksheets(element)
        if not ws or not os.path.exists(QC_DB):
            return {}
        conn = sqlite3.connect(QC_DB)
        try:
            spikes = sd.injections(conn, rec["method"], ["LFB"], batches=ws)
        finally:
            conn.close()
        levels = self._levels(ws)
        spikes = [dict(r, level=levels.get((r["batch"], r["injection"])) or u"") for r in spikes]
        fort = dict((lv, self.fortified(lv)) for lv in set(r["level"] for r in spikes))
        out = {}
        for lv, res in sd.calculate_levels(kind, spikes, None, fort, rec.get("exclusions")).items():
            out.update(dict((u"%s %s" % (kw, lv) if lv else kw, r) for kw, r in res.items()))
        return out

    def idc_elements(self):
        """{element: result} for an IDC (frozen at approval)."""
        from senaite.pfas import idc
        rec = self.record() or {}
        if rec.get("kind") != "idc":
            return {}
        if rec.get("status") != sr.DRAFT:
            return (rec.get("results") or {}).get("idc") or {}
        every = sorted(set(w for p in rec.get("parts") or [] for w in p.get("worksheets") or []))
        return {
            "isomers": idc.isomers(self.profile()),
            "lsb": idc.judged_rows(self._qc_rows(sd.blank_role(rec["method"]),
                                                 self._part_worksheets("lsb"))),
            "pa": idc.per_analyte(self._part_results("pa", "pa")),
            "qcs": idc.judged_rows(self._qc_rows("ICV", sorted(self._reviewed(set(every))))),
            "asymmetry": idc.asymmetry((rec.get("idc") or {}).get("asymmetry"),
                                       self._asymmetry_present(rec)),
            "mrl": idc.per_analyte(self._part_results("mrl", "mrl")),
        }

    # ── a designed study (study_templates) ───────────────────────────────
    def _design_injections(self, element_key_prefix, role):
        """[{"source", "level", "values", "batch", "date", "injection"}] of
        the parts whose cell key starts with `element_key_prefix`, from
        their reviewed worksheets."""
        rec = self.record() or {}
        out = []
        if not os.path.exists(QC_DB):
            return out
        for p in rec.get("parts") or []:
            if not (p.get("element") or u"").startswith(element_key_prefix):
                continue
            ws = sorted(self._reviewed(set(p.get("worksheets") or [])))
            if not ws:
                continue
            conn = sqlite3.connect(QC_DB)
            try:
                rows = sd.injections(conn, rec["method"], [p.get("role") or role], batches=ws)
            finally:
                conn.close()
            for r in rows:
                out.append(dict(r, source=p.get("std_source") or u"", level=p.get("level") or u""))
        return out

    def _delete_draft(self):
        """A draft study is removed (an approved one never is); its parts'
        worksheets stay, as any worksheet does."""
        rec = self.record()
        if rec is None or rec.get("status") != sr.DRAFT:
            self.error = u"Only a draft study is deleted."
            return self.template()
        sr.save(self.portal(), [r for r in self.records() if r.get("id") != rec["id"]])
        # its uploaded evidence goes with it (a draft's files are its own)
        import shutil
        d = os.path.join(PDF_DIR, rec["id"])
        if rec["id"] and os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
        self.request.response.redirect("%s/@@pfas-method-studies" % self.portal_url())
        return u""

    def _design_dir(self, rec, eid):
        return os.path.join(PDF_DIR, rec["id"], eid)

    def design_files(self, eid):
        rec = self.record() or {}
        d = self._design_dir(rec, eid) if rec else u""
        return sorted(os.listdir(d)) if d and os.path.isdir(d) else []

    def design_results(self):
        """[(element, result)] in the template's order (frozen at approval)."""
        from senaite.pfas import study_templates as st
        rec = self.record() or {}
        design = rec.get("design") or {}
        if rec.get("status") != sr.DRAFT:
            frozen = (rec.get("results") or {}).get("design") or {}
            return [(el, frozen.get(el["id"]) or {}) for el in design.get("elements") or []]
        entries = rec.get("entries") or {}
        out = []
        for el in design.get("elements") or []:
            eid = el["id"]
            if el["type"] == "replicates":
                res = st.evaluate_replicates(el, self._design_injections(eid + u"|", el.get("role")),
                                             self._design_limits(rec, st.limits_qc(el)))
            elif el["type"] == "mdl":
                spikes = self._design_injections(eid + u"|spiked", el.get("spike_role"))
                blanks = self._design_injections(eid + u"|blanks", el.get("blank_role"))
                res = st.evaluate_mdl(sd.calculate("mdl", spikes, blanks, exclusions=rec.get("exclusions"))
                                      if spikes else {})
            elif el["type"] == "qualitative":
                res = st.evaluate_qualitative(el, entries.get(eid), self.design_files(eid))
            else:
                res = st.evaluate_typed(el, entries.get(eid), bool(self.design_files(eid)))
            out.append((el, res))
        return out

    def limits_qc(self, el):
        from senaite.pfas import study_templates as st
        return st.limits_qc(el)

    def _design_limits(self, rec, qc_type):
        """limits(keyword, level) for a designed element: the method profile's
        tier for that QC type, analyte, matrix and level (qc_tiers) -- a study
        is judged by the method's limits, never by limits of its own."""
        from senaite.pfas import calibration_levels as cl
        from senaite.pfas import method_profile_sections as mps
        from senaite.pfas import qc_tiers
        profile = self.profile(rec.get("method")) or {}
        matrix = rec.get("matrix") or (rec.get("design") or {}).get("matrix") or u""
        keys, no_std = mps.key_analytes(profile), mps.no_std_set(profile)

        def limits(kw, level):
            return qc_tiers.study_limits(profile, qc_type, kw, matrix, level,
                                         cl.reporting_limit(profile, matrix, kw),
                                         kw in keys, kw in no_std)
        return limits

    def design_overall(self):
        from senaite.pfas import study_templates as st
        return st.combine([r.get("verdict") for _el, r in self.design_results()])

    def _design_entry(self):
        """Upload evidence, type values, or (a manager) judge a qualitative
        element: one element at a time (`eid`)."""
        f = self.request.form
        rec = self.record()
        if rec is None or rec.get("status") != sr.DRAFT or not rec.get("design"):
            self.error = u"Only a draft designed study is edited here."
            return
        eid = f.get("eid") or u""
        el = dict((e["id"], e) for e in rec["design"].get("elements") or []).get(eid)
        if el is None:
            self.error = u"No such element."
            return
        entry = dict((rec.get("entries") or {}).get(eid) or {})
        upload = f.get("evidence")
        if upload is not None and getattr(upload, "filename", u""):
            name = os.path.basename(upload.filename).replace(u" ", u"_")
            ext = name.rsplit(u".", 1)[-1].lower() if u"." in name else u""
            allowed = [a.strip().lower().lstrip(u".") for a in (el.get("accept") or u"pdf, png, jpg").split(u",")]
            if ext not in allowed:
                self.error = u"%s: only %s files." % (name, u", ".join(allowed))
                return
            d = self._design_dir(rec, eid)
            if not os.path.isdir(d):
                os.makedirs(d)
            with open(os.path.join(d, name), "wb") as fh:
                fh.write(upload.read())
        if el["type"] == "typed":
            entry["values"] = [(f.get(u"value.%d" % i) or u"").strip() for i in range(int(el.get("count") or 1))]
        if el["type"] == "qualitative" and f.get("verdict") in (u"pass", u"fail"):
            if not self.can_configure():
                self.error = u"A manager judges the evidence."
                return
            entry.update(verdict=f.get("verdict"), note=(f.get("note") or u"").strip(),
                         by=_user(), at=_now())
        rec.setdefault("entries", {})[eid] = entry
        sr.save(self.portal(), self.records())
        self.message = u"Saved."

    def _serve_evidence(self):
        rec = self.record()
        eid, name = self.request.form.get("eid") or u"", os.path.basename(self.request.form.get("file") or u"")
        path = os.path.join(self._design_dir(rec, eid), name)
        if not name or not os.path.exists(path):
            self.request.response.setStatus(404)
            return u"No such file."
        with open(path, "rb") as fh:
            body = fh.read()
        ctype = {"pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg",
                 "jpeg": "image/jpeg"}.get(name.rsplit(".", 1)[-1].lower(), "application/octet-stream")
        self.request.response.setHeader("Content-Type", ctype)
        return body

    def idc_rows(self):
        from senaite.pfas import idc
        el = self.idc_elements()
        return [(k, label, el.get(k) or {}) for k, label in idc.ELEMENTS]

    def idc_overall(self):
        from senaite.pfas import idc
        return idc.overall(self.idc_elements())

    def idc_due(self):
        """Analysts with no approved IDC for each method that has one."""
        from senaite.pfas import idc
        return [(m, idc.due(self.analysts(), self.records(), m)) for m in idc.METHODS]

    def _asymmetry_path(self, rec):
        return os.path.join(PDF_DIR, rec["id"], u"asymmetry.pdf")

    def _asymmetry_present(self, rec):
        return bool((rec.get("idc") or {}).get("pdf")) and os.path.exists(self._asymmetry_path(rec))

    def _save_idc(self):
        """The peak asymmetry factors and the PDF of their calculation."""
        f = self.request.form
        rec = self.record()
        if rec is None or rec.get("kind") != "idc" or rec.get("status") != sr.DRAFT:
            self.error = u"Only a draft IDC is edited here."
            return
        data = dict(rec.get("idc") or {})
        data["asymmetry"] = [(f.get(u"asym.%d" % i) or u"").strip() for i in (1, 2)]
        upload = f.get("asymmetry_file")
        if upload is not None and getattr(upload, "filename", u""):
            body = upload.read()
            if not body.startswith(b"%PDF"):
                self.error = u"The calculation must be a PDF."
                return
            path = self._asymmetry_path(rec)
            if not os.path.isdir(os.path.dirname(path)):
                os.makedirs(os.path.dirname(path))
            with open(path, "wb") as fh:
                fh.write(body)
            data["pdf"] = {"name": upload.filename, "by": _user(), "at": _now()}
        rec["idc"] = data
        sr.save(self.portal(), self.records())
        self.message = u"Saved."

    def _serve_asymmetry(self):
        rec = self.record()
        path = self._asymmetry_path(rec)
        if not os.path.exists(path):
            self.request.response.setStatus(404)
            return u"No calculation."
        with open(path, "rb") as fh:
            body = fh.read()
        self.request.response.setHeader("Content-Type", "application/pdf")
        return body

    def level_rows(self):
        """[(level, [(keyword, result)])] for the results macro."""
        return [(lv, sorted(res.items())) for lv, res in sorted(self.results().items())]

    def applied(self):
        rec = self.record() or {}
        if rec.get("status") != sr.DRAFT:
            return rec.get("applied") or {}
        return sd.applied_by_level(rec.get("kind"), self.results(), self.fortified_by_level())

    def replicate_rows(self):
        spikes, blanks = self.data()
        return [dict(r, role=u"spike") for r in spikes] + [dict(r, role=u"blank") for r in blanks]

    def fmt(self, v):
        if v is None or v == u"":
            return u"—"
        if isinstance(v, float):
            return u"%.4g" % v
        return u"%s" % v

    # ── parts, assigned to analysts ───────────────────────────────────────
    def elements(self):
        rec = self.record() or {}
        return sru.elements_for(rec.get("kind"), rec)

    def element_label(self, element):
        for e in self.elements():
            if e[0] == element:
                return e[1]
        return (sru.ELEMENT.get(element) or (None, element))[1]

    def sources(self):
        return sru.SOURCES

    def source_label(self, kind):
        return sru.SOURCE_LABELS.get(kind, kind)

    def source_text(self, source):
        return sru.source_text(source)

    def analysts(self):
        """[(user id, full name)] -- the people core offers as a worksheet's
        Analyst."""
        if not hasattr(self, "_analysts"):
            from bika.lims.utils import getUsers
            try:
                users = getUsers(self.context, ["Manager", "LabManager", "Analyst"], allow_empty=False)
                self._analysts = [(k, users.getValue(k)) for k in users.keys()]
            except Exception:                                # noqa: BLE001
                logger.exception("analysts")
                self._analysts = []
        return self._analysts

    def _usable(self):
        if not hasattr(self, "_usable_lots"):
            from senaite.pfas.browser.bench_inventory import usable_lots
            try:
                self._usable_lots = usable_lots(self.portal(), date.today().isoformat())
            except Exception:                                # noqa: BLE001
                logger.exception("usable lots")
                self._usable_lots = []
        return self._usable_lots

    def lot_options(self, kind):
        """The usable lots a source of `kind` may name."""
        from senaite.pfas.content.reagent import CATEGORY_PURCHASED_WATER, CATEGORY_REFERENCE
        return sru.lot_choices(self._usable(), kind, CATEGORY_REFERENCE,
                               CATEGORY_PURCHASED_WATER)

    def all_worksheets(self):
        return sru.study_worksheets(self.record() or {})

    def parts(self):
        return (self.record() or {}).get("parts") or []

    def can_assign(self):
        rec = self.record() or {}
        return bool(self.can_configure() and rec.get("status") == sr.DRAFT and self.elements())

    def worksheet_url(self, ws_id):
        from bika.lims import api
        for b in api.get_tool("senaite_catalog_worksheet")(portal_type="Worksheet", id=ws_id):
            return b.getURL()
        return u""

    def _assign(self):
        """One part of the study, given to one analyst, as one worksheet."""
        f = self.request.form
        rec = self.record()
        if rec is None:
            self.error = u"No such study."
            return
        analyst = (f.get("analyst") or u"").strip()
        names = dict(self.analysts())
        if analyst and analyst not in names:
            self.error = u"%s is not one of the lab's analysts." % analyst
            return
        kind = f.get("source_kind") or u""
        source = {"kind": kind}
        if kind and kind != sru.WATER_SYSTEM:
            uid = (f.get("source_lot.%s" % kind) or u"").strip()
            lot = dict((l["uid"], l) for l in self.lot_options(kind)).get(uid)
            if uid and lot is None:
                self.error = u"That lot cannot be used today (expired, quarantined or not this kind)."
                return
            if lot is not None:
                source.update(uid=uid, name=lot.get("name") or u"", lot_number=lot.get("lot_number") or u"")
        part, self.error = sru.new_part(rec, f.get("element") or u"", analyst, names.get(analyst),
                                        f.get("level"), f.get("replicates"), source, _user(), _now())
        if self.error:
            return
        ws = self._make_worksheet(rec, part)
        part["worksheets"].append(ws.getId())
        rec.setdefault("parts", []).append(part)
        sru.add_reference(rec, source)
        sr.save(self.portal(), self.records())
        self.message = u"%s assigned to %s as %s." % (part["id"], part["analyst_name"], ws.getId())

    def _make_worksheet(self, rec, part):
        """The part's worksheet: its Analyst, its method, the study run record
        and the extraction batch holding the part's replicates."""
        from bika.lims import api
        from senaite.pfas import extraction_batch as eb
        from senaite.pfas.method_bridge import get_core_method
        ws = api.create(self.portal().worksheets, "Worksheet")
        ws.setAnalyst(part["analyst"])
        method = get_core_method(self.portal(), rec["method"])
        if method is not None:
            ws.setMethod(method)
        sru.save_run(ws, sru.run_record(rec, part))
        members = eb.populate([], sru.plan(part, rec["method"]), ws.getId(), _user(), _now())
        eb.save(ws, sru.set_levels(members, part))
        ws.reindexObject()
        return ws

    # ── reference samples: receipt and CoA ─────────────────────────────────
    def reference_samples(self):
        """Every usable reference-sample lot with its receipt and CoA."""
        from senaite.pfas.browser.reagents import _get_coa_meta
        out = []
        for l in self.lot_options(sru.REFERENCE_LOT):
            out.append(dict(l, receipt=self._receipt_of(l["uid"]),
                            coa=_get_coa_meta(self.portal(), l["uid"]) or None))
        return out

    def _reagent(self, uid):
        folder = self.portal().get("pfas_reagents")
        obj = folder.get(uid) if folder is not None and uid else None
        return obj if getattr(obj, "portal_type", "") == "Reagent" else None

    def _receipt_of(self, uid):
        obj = self._reagent(uid)
        return sru.load_receipt(obj) if obj is not None else None

    def _receipt(self):
        """Record a reference sample's receipt; its CoA goes where every
        lot's CoA goes (the reagent's own)."""
        f = self.request.form
        uid = (f.get("uid") or u"").strip()
        if uid not in [l["uid"] for l in self.lot_options(sru.REFERENCE_LOT)]:
            self.error = u"Only a usable reference-sample lot takes a receipt here."
            return
        obj = self._reagent(uid)
        receipt, self.error = sru.new_receipt(f, sru.load_receipt(obj), _user(), _now())
        if self.error:
            return
        from senaite.pfas.browser.reagents import _get_reagent, _save_coa, _save_reagent, _str_to_date
        received = _str_to_date((f.get("received_at") or u"").strip()[:10])
        if received is None:
            self.error = u"Give the date it was received as a date."
            return
        upload, data = f.get("coa_file"), None
        if upload is not None and getattr(upload, "filename", u""):
            data = upload.read()
            if not data.startswith(b"%PDF"):
                self.error = u"The CoA must be a PDF."
                return
        # checked first, written after: a refused receipt changes nothing
        if data is not None and not _save_coa(self.portal(), uid, data, upload.filename,
                                              "application/pdf", _user()):
            self.error = u"The CoA was not saved."
            return
        sru.save_receipt(obj, receipt)
        # the lot's own Received Date, through the inventory's save (its
        # derived expiry and its modified event, the audit log's snapshot)
        lot = _get_reagent(self.portal(), uid)
        lot["received_date"] = received.isoformat()
        _save_reagent(self.portal(), lot)
        self.message = u"Receipt recorded."

    # ── actions ────────────────────────────────────────────────────────────
    def _create(self):
        f = self.request.form
        kind, method, matrix = f.get("kind") or u"", f.get("method") or u"", f.get("matrix") or u""
        design = None
        if kind.startswith(u"tpl:"):
            from senaite.pfas import study_templates as st
            design = st.find(st.load(self.portal()), kind[4:])
            if design is None:
                self.error = u"That template no longer exists."
                return self.template()
            probs = st.problems(design)
            if probs:
                self.error = u"The template is not finished: %s" % probs[0]
                return self.template()
            if design.get("method") != method or (design.get("matrix") and design["matrix"] != matrix):
                self.error = u"The template is for %s%s." % (design.get("method"),
                                                            u" / %s" % design["matrix"] if design.get("matrix") else u"")
                return self.template()
            kind = u"designed"
        if kind not in sd.KIND_LABELS and kind != u"designed" or not method or not matrix:
            self.error = u"Choose the kind, method and matrix."
            return self.template()
        if matrix not in (self.profile(method).get("supported_matrices") or []):
            self.error = u"%s is not a matrix of %s." % (matrix, method)    # rule 2
            return self.template()
        analyst = u""
        if kind == "idc":
            from senaite.pfas import idc
            analyst = (f.get("idc_analyst") or u"").strip()
            if method not in idc.METHODS:
                self.error = u"An IDC is defined for %s only so far." % u", ".join(idc.METHODS)
                return self.template()
            if analyst not in dict(self.analysts()):
                self.error = u"Choose the analyst whose capability this demonstrates."
                return self.template()
        recs = self.records()
        ws = [w.strip() for w in (f.get("worksheets") or u"").replace(u",", u" ").split() if w.strip()]
        levels = [l for l in self.level_labels() if f.get(u"level.%s" % l)]
        lots = dict((l.get("uid"), l) for l in self.reference_lots())
        rms = [{"uid": uid, "name": lots[uid].get("name") or u"", "lot_number": lots[uid].get("lot_number") or u""}
               for uid in sorted(lots) if f.get(u"rm.%s" % uid)]
        rec = sr.new(recs, kind, method, matrix, _user(), _now(), levels=levels, reference_materials=rms,
                     worksheets=ws, since=(f.get("since") or u"").strip(),
                     until=(f.get("until") or u"").strip(), title=(f.get("title") or u"").strip(),
                     fortified=(f.get("fortified") or u"").strip() or None, analyst=analyst)
        if design is not None:
            rec["design"] = design                  # a copy: the template may change later
            rec["title"] = design["name"]
        recs.append(rec)
        sr.save(self.portal(), recs)
        self.request.response.redirect("%s/@@pfas-method-studies?id=%s" % (self.portal_url(), rec["id"]))
        return u""

    def _charts(self):
        """Whether the study's runs join the control charts and blank
        history (off until a manager says so)."""
        rec = self.record()
        if rec is None:
            self.error = u"No such study."
            return
        rec["in_charts"] = self.request.form.get("in_charts") == u"1"
        sr.save(self.portal(), self.records())
        self.message = (u"Its runs are in the control charts and blank history."
                        if rec["in_charts"] else
                        u"Its runs are kept out of the control charts and blank history.")

    def _exclude(self):
        f = self.request.form
        rec = self.record()
        if rec is None:
            self.error = u"No such study."
            return
        self.error = sr.exclude(rec, f.get("injection") or u"", f.get("analyte") or u"*",
                                f.get("reason") or u"", _user(), _now())
        if not self.error:
            sr.save(self.portal(), self.records())
            self.message = u"Excluded."

    def _save_pt(self):
        """The PT round, its analytes and the provider's certificate."""
        f = self.request.form
        rec = self.record()
        if rec is None or rec.get("kind") != "pt" or rec.get("status") != sr.DRAFT:
            self.error = u"Only a draft proficiency test is edited here."
            return
        pt = dict(rec.get("pt") or {})
        for k in ("provider", "scheme", "round", "sample", "received"):
            pt[k] = (f.get(u"pt_%s" % k) or u"").strip()
        entries = dict((kw, {"reported": f.get(u"rep.%s" % kw), "assigned": f.get(u"asg.%s" % kw),
                             "verdict": f.get(u"ver.%s" % kw)}) for kw in self.pt_analytes())
        pt["results"] = sd.pt_results(entries)
        upload = self.request.form.get("certificate_file")
        if upload is not None and getattr(upload, "filename", u""):
            data = upload.read()
            if not data.startswith(b"%PDF"):
                self.error = u"The certificate must be a PDF."
                return
            path = self._certificate_path(rec)
            if not os.path.isdir(os.path.dirname(path)):
                os.makedirs(os.path.dirname(path))
            with open(path, "wb") as fh:
                fh.write(data)
            pt["certificate"] = {"file": os.path.basename(path), "name": upload.filename,
                                 "by": _user(), "at": _now()}
        rec["pt"] = pt
        sr.save(self.portal(), self.records())
        self.message = u"Saved."

    def _certificate_path(self, rec):
        return os.path.join(PDF_DIR, rec["id"], u"certificate.pdf")

    def _certificate_present(self, rec):
        return bool((rec.get("pt") or {}).get("certificate")) and os.path.exists(self._certificate_path(rec))

    def _serve_certificate(self):
        rec = self.record()
        path = self._certificate_path(rec)
        if not os.path.exists(path):
            self.request.response.setStatus(404)
            return u"No certificate."
        with open(path, "rb") as fh:
            body = fh.read()
        self.request.response.setHeader("Content-Type", "application/pdf")
        self.request.response.setHeader("Content-Disposition", 'inline; filename="%s-certificate.pdf"' % rec["id"])
        return body

    def _approve(self):
        rec = self.record()
        if rec is None:
            self.error = u"No such study."
            return
        if rec.get("kind") == "pt":
            problems = self.pt_problems()
            if problems:
                self.error = problems[0]
                return
        results, applied = self.results(), self.applied()
        if rec.get("kind") == "idc":
            from senaite.pfas import idc
            elements = self.idc_elements()
            if idc.overall(elements) != idc.PASS:
                self.error = u"Every element of the IDC must pass before it is approved."
                return
            results, applied = {"idc": elements}, {}
        if rec.get("kind") == "designed":
            from senaite.pfas import study_templates as st
            res = self.design_results()
            if st.combine([r.get("verdict") for _el, r in res]) != st.PASS:
                self.error = u"Every element of the study must pass before it is approved."
                return
            results, applied = {"design": dict((el["id"], r) for el, r in res)}, {}
        recs = self.records()
        self.error = sr.approve(recs, rec, results, applied, _user(), _now(),
                                self.request.form.get("statement") or u"",
                                file_name=u"%s.pdf" % rec["id"])
        if self.error:
            return
        if applied:
            from senaite.pfas.config_history import set_actor, set_note
            from senaite.pfas.method_profile_store import save_profile
            set_actor(_user())
            set_note(u"method study %s" % rec["id"])
            save_profile(self.portal(), rec["method"],
                         sr.apply_to_profile(self.profile(rec["method"]), rec["matrix"], applied))
        sr.save(self.portal(), recs)
        self._freeze_pdf(rec)
        self.message = u"Approved."

    # ── the packet ─────────────────────────────────────────────────────────
    def _pdf_path(self, rec):
        return os.path.join(PDF_DIR, rec.get("file") or u"%s.pdf" % rec["id"])

    def _freeze_pdf(self, rec):
        try:
            from weasyprint import HTML
            if not os.path.isdir(PDF_DIR):
                os.makedirs(PDF_DIR)
            HTML(string=self.print_template()).write_pdf(self._pdf_path(rec))
        except Exception as exc:                            # noqa: BLE001
            logger.exception("study packet %s not frozen", rec.get("id"))
            self.error = u"Approved, but the packet PDF was not written: %s" % exc

    def _serve_pdf(self):
        rec = self.record()
        path = self._pdf_path(rec)
        if rec.get("status") == sr.DRAFT or not os.path.exists(path):
            from weasyprint import HTML
            body = HTML(string=self.print_template()).write_pdf()
        else:
            with open(path, "rb") as fh:
                body = fh.read()
        resp = self.request.response
        resp.setHeader("Content-Type", "application/pdf")
        resp.setHeader("Content-Disposition", 'inline; filename="%s.pdf"' % rec["id"])
        return body


class PFASMethodStudyMacrosView(BrowserView):
    """The results macro, shared by the page and its packet PDF."""

    _template = ViewPageTemplateFile("templates/method_study_macros.pt")

    @property
    def macros(self):
        return self._template.macros
