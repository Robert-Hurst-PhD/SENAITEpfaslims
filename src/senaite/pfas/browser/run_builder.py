# -*- coding: utf-8 -*-
"""
@@pfas-run-builder — LC-MS Run Builder (Instruments & Import).

Everything derives from the relational spine — nothing method-specific is
hardcoded here:
  * batch → METHOD via the same resolution logbooks use (extraction session >
    logbook annotations > SENAITE batch method);
  * the method's OWN extraction logbook (profile `extraction_logbook`, else an
    extraction-titled entry of `required_logbooks`) supplies the per-sample
    rows — sample id, MATRIX (varies per sample) and SPIKE — with the batch's
    linked samples (matrix = core SampleType) as fallback;
  * CCV interval comes from the method profile
    (instrument_verification.ccv.frequency);
  * analyst initials come from the laboratory staff pool (LabContacts).

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import csv
import io
import json
import logging
import os
import re
from datetime import date, datetime

from zope.annotation.interfaces import IAnnotations
from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

logger = logging.getLogger("senaite.pfas.browser.run_builder")

RUN_MANIFEST_KEY = u"senaite.pfas.run_manifest"
UPLOAD_DIR = os.environ.get("PFAS_INSTRUMENT_UPLOAD_DIR",
                            "/addon/data/instrument_output")


class PFASRunBuilderView(BrowserView):
    template = ViewPageTemplateFile("templates/run_builder.pt")

    def __call__(self):
        action = self.request.form.get("action", "")
        if self.request.method == "POST":
            # Same CSRF handling as the sibling PFAS form views
            try:
                from plone.protect.interfaces import IDisableCSRFProtection
                from zope.interface import alsoProvides
                alsoProvides(self.request, IDisableCSRFProtection)
            except ImportError:
                pass
            if action == "build":
                return self._handle_build()
            if action == "upload_export":
                return self._handle_upload_export()
        if action == "download_csv":
            return self._handle_download_csv()
        return self.template()

    # ── helpers ───────────────────────────────────────────────────────────
    def _portal(self):
        return getToolByName(self.context, "portal_url").getPortalObject()

    def portal_url(self):
        return self._portal().absolute_url()

    def ok_msg(self):
        return self.request.form.get("ok", "")

    def error_msg(self):
        return self.request.form.get("error", "")

    def selected_batch(self):
        return self.request.form.get("batch_id", "")

    def _batch(self, batch_id=None):
        bid = batch_id or self.selected_batch()
        try:
            return self._portal()["batches"][bid]
        except Exception:
            return None

    # ── method / extraction-log resolution (all dynamic) ─────────────────
    def batch_method(self, batch=None):
        """Method id for the selected batch — same resolution as logbooks."""
        b = batch or self._batch()
        if b is None:
            return ""
        try:
            from senaite.pfas.browser.logbooks import PFASLogbookIndexView
        except Exception:
            PFASLogbookIndexView = None
        if PFASLogbookIndexView is not None:
            try:
                return PFASLogbookIndexView(b, self.request).batch_method() or ""
            except Exception:
                pass
        return ""

    def _profile(self, method_id):
        try:
            from senaite.pfas.method_profile_store import get_profile
            return get_profile(self._portal(), method_id) or {}
        except Exception:
            return {}

    def extraction_logbook_slug(self, method_id):
        """The METHOD'S extraction logbook: explicit profile setting first,
        else the extraction-titled entry among its required_logbooks."""
        prof = self._profile(method_id)
        explicit = prof.get("extraction_logbook")
        if explicit:
            return str(explicit)
        required = [str(s) for s in (prof.get("required_logbooks") or [])]
        try:
            from senaite.pfas.logbook_store import get_active_logbook_defs
            for d in get_active_logbook_defs(self._portal()):
                slug = str(d.get("form_num") or d.get("slug") or "")
                title = (d.get("title") or "").lower()
                if slug in required and "extraction" in title:
                    return slug
        except Exception:
            pass
        # last resort: the conventional extraction form if the method requires it
        return "252" if "252" in required else (required[0] if required else "")

    def ccv_interval(self, method_id):
        """CCV frequency from the method profile (never a form input)."""
        prof = self._profile(method_id)
        try:
            freq = (prof.get("instrument_verification", {})
                        .get("ccv", {}).get("frequency"))
            return max(1, int(freq))
        except (TypeError, ValueError):
            return 6

    def _extraction_log(self, batch, slug):
        raw = IAnnotations(batch).get(u"senaite.pfas.logbook." + str(slug))
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return {}

    def sample_rows(self, batch_id=None):
        """[{sample_id, matrix, spike}] — extraction log of the method's own
        logbook first; batch-linked samples (matrix = core SampleType) as
        fallback. Matrix varies PER SAMPLE; spike is per the extraction log."""
        b = self._batch(batch_id)
        if b is None:
            return []
        method_id = self.batch_method(b)
        slug = self.extraction_logbook_slug(method_id) if method_id else ""
        rows = []
        if slug:
            log = self._extraction_log(b, slug)
            for key in ("samples", "sample_rows", "rows"):
                for r in (log.get(key) or []):
                    if not isinstance(r, dict):
                        continue
                    sid = r.get("sample_id") or r.get("id") or r.get("name")
                    if not sid:
                        continue
                    rows.append({
                        "sample_id": sid,
                        # NOTE: log field `sample_type` is the QC ROLE
                        # (Sample/Dup/MB), NOT the matrix — never use it here.
                        "matrix": r.get("matrix") or "",
                        "role": r.get("sample_type") or r.get("role") or "",
                        "spike": r.get("spike_ppt") or r.get("spike") or "",
                    })
                if rows:
                    break
            if not rows:
                # spike may live at log level even when rows are elsewhere
                pass
        # enrich: rows without a matrix resolve it from the sample's REAL
        # core SampleType (matrix varies per sample — §3 link, not a form input)
        missing = [r for r in rows if not r.get("matrix")]
        if missing:
            try:
                cat = getToolByName(self._portal(), "senaite_catalog_sample")
                for r in missing:
                    for br in cat(portal_type="AnalysisRequest",
                                  getId=r["sample_id"]):
                        st = br.getObject().getSampleType()
                        if st:
                            r["matrix"] = st.Title()
                        break
            except Exception:
                pass
        if not rows:
            # fallback: batch-linked samples; matrix = the REAL SampleType
            try:
                cat = getToolByName(self._portal(), "senaite_catalog_sample")
                for br in cat(portal_type="AnalysisRequest", getBatchUID=b.UID()):
                    ar = br.getObject()
                    st = ar.getSampleType()
                    rows.append({
                        "sample_id": ar.getId(),
                        "matrix": st.Title() if st else "",
                        "spike": "",
                    })
            except Exception:
                pass
        return rows

    def run_context(self):
        """Everything the form shows read-only, derived from the batch."""
        bid = self.selected_batch()
        if not bid:
            return None
        method_id = self.batch_method()
        slug = self.extraction_logbook_slug(method_id) if method_id else ""
        rows = self.sample_rows()
        return {
            "batch_id": bid,
            "method_id": method_id or "(unresolved)",
            "extraction_slug": slug or "(none set on method)",
            "ccv_interval": self.ccv_interval(method_id) if method_id else 6,
            "rows": rows,
            "n_samples": len(rows),
        }

    # ── laboratory staff pool ─────────────────────────────────────────────
    def staff_pool(self):
        """Laboratory staff pool (single source: senaite.pfas.staff)."""
        try:
            from senaite.pfas.staff import list_staff
            return list_staff(self._portal())
        except Exception as exc:
            logger.warning("staff_pool: %s", exc)
            return []

    def batches(self):
        out = []
        try:
            for b in self._portal()["batches"].objectValues():
                out.append({"id": b.getId(), "title": b.Title() or b.getId()})
        except Exception as exc:
            logger.warning("batches: %s", exc)
        return out

    # ── sequence construction ─────────────────────────────────────────────
    def _cal_names(self, method_id, run_date):
        from senaite.pfas.analyte_reference import get_cal_ladder
        ymd = run_date.strftime("%y%m%d")
        return [("FDA-CAL-{0}-{1}".format(i + 1, ymd), "Standard")
                for i, _c in enumerate(get_cal_ladder(method_id) or [])]

    def _qc_name(self, initials, matrix, qc, run_date, seq):
        # validated pattern 3: "KCP Water MB 2026-03-13-01"
        return u"{0} {1} {2} {3}-{4:02d}".format(
            initials, matrix or "Lab", qc, run_date.strftime("%Y-%m-%d"), seq)

    def build_sequence(self, sample_rows, initials, method_id, ccv_interval,
                       include_cal):
        run_date = date.today()
        # QC rows use the run's dominant matrix (from the extraction log)
        matrices = [r.get("matrix") for r in sample_rows if r.get("matrix")]
        dom = max(set(matrices), key=matrices.count) if matrices else "Lab"
        rows = []

        def add(name, typ):
            rows.append({"vial": len(rows) + 1, "name": name, "type": typ})

        add(self._qc_name(initials, dom, "MB", run_date, 0) + " MeOH-Blank",
            "Blank")
        if include_cal:
            for name, typ in self._cal_names(method_id, run_date):
                add(name, typ)
            add(self._qc_name(initials, dom, "CCV", run_date, 0), "QC")
        add(self._qc_name(initials, dom, "ICV", run_date, 0), "QC")
        add(self._qc_name(initials, dom, "MB", run_date, 1), "Blank")
        add(self._qc_name(initials, dom, "LCS", run_date, 1), "QC")

        since_ccv, ccv_n = 0, 1
        spikes = [r.get("spike") for r in sample_rows if r.get("spike")]
        for i, r in enumerate(sample_rows):
            mtx = r.get("matrix") or dom
            add(u"{0} {1} Sample {2}-{3:02d} {4}".format(
                initials, mtx, run_date.strftime("%Y-%m-%d"), i + 1,
                r["sample_id"]), "Sample")
            since_ccv += 1
            if since_ccv >= ccv_interval:
                add(self._qc_name(initials, dom, "CCV", run_date, ccv_n), "QC")
                since_ccv, ccv_n = 0, ccv_n + 1
        if sample_rows:
            add(self._qc_name(initials, dom, "LFSM", run_date, 1), "QC")
            add(self._qc_name(initials, dom, "LFSMD", run_date, 1), "QC")
        add(self._qc_name(initials, dom, "CCV", run_date, ccv_n), "QC")
        return rows, dom, (spikes[0] if spikes else "")

    # ── actions ───────────────────────────────────────────────────────────
    def _handle_build(self):
        f = self.request.form
        batch_id = (f.get("batch_id") or "").strip()
        initials = (f.get("initials") or "").strip().upper()
        include_cal = f.get("include_cal") in ("on", "1", "true")
        if not batch_id:
            return self._redirect_err(batch_id, "Select a batch first")
        if not initials:
            return self._redirect_err(batch_id, "Select the analyst")
        method_id = self.batch_method(self._batch(batch_id))
        if not method_id:
            return self._redirect_err(
                batch_id, "Batch has no method — fill its extraction log first")
        rows_in = self.sample_rows(batch_id)
        # manual additions (one per line) are appended, matrix left blank
        for s in (f.get("extra_samples") or "").splitlines():
            s = s.strip()
            if s:
                rows_in.append({"sample_id": s, "matrix": "", "spike": ""})
        if not rows_in:
            return self._redirect_err(batch_id, "No samples to run")

        ccv = self.ccv_interval(method_id)
        rows, dom, spike = self.build_sequence(
            rows_in, initials, method_id, ccv, include_cal)
        manifest = {
            "built_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            "built_by": initials,
            "batch_id": batch_id,
            "method_id": method_id,
            "extraction_logbook": self.extraction_logbook_slug(method_id),
            "dominant_matrix": dom,
            "ccv_interval": ccv,
            "spike_ppt": spike,
            "rows": rows,
        }
        try:
            IAnnotations(self._batch(batch_id))[RUN_MANIFEST_KEY] = \
                json.dumps(manifest)
        except Exception as exc:
            logger.warning("manifest save failed: %s", exc)
        self.request.response.redirect(
            "{0}/@@pfas-run-builder?batch_id={1}&built=1".format(
                self.portal_url(), batch_id))
        return u""

    def built(self):
        return self.request.form.get("built", "") == "1"

    def manifest(self):
        b = self._batch()
        if b is None:
            return None
        try:
            raw = IAnnotations(b).get(RUN_MANIFEST_KEY)
            return json.loads(raw) if raw else None
        except Exception:
            return None

    def _handle_download_csv(self):
        m = self.manifest()
        if not m:
            return self._redirect_err(self.selected_batch(), "No built run")
        buf = io.BytesIO()
        w = csv.writer(buf)
        w.writerow([b"Vial", b"Sample Name", b"Sample Type"])
        for r in m["rows"]:
            w.writerow([r["vial"], r["name"].encode("utf-8"), r["type"]])
        resp = self.request.response
        resp.setHeader("Content-Type", "text/csv")
        resp.setHeader("Content-Disposition",
                       "attachment; filename=worklist_{0}.csv".format(
                           re.sub(r"[^A-Za-z0-9_-]", "_",
                                  m["batch_id"] or "run")))
        return buf.getvalue()

    def _handle_upload_export(self):
        f = self.request.form.get("export_file")
        bid = (self.request.form.get("batch_id") or "").strip()
        if f is None or not getattr(f, "filename", ""):
            return self._redirect_err(bid, "No file selected")
        fname = re.sub(r"[^A-Za-z0-9._-]", "_", f.filename)
        if not os.path.isdir(UPLOAD_DIR):
            try:
                os.makedirs(UPLOAD_DIR)
            except OSError:
                return self._redirect_err(bid, "Watch directory unavailable")
        try:
            data = f.read()
            with open(os.path.join(UPLOAD_DIR, fname), "wb") as out:
                out.write(data)
        except Exception as exc:
            logger.error("upload failed: %s", exc)
            return self._redirect_err(bid, "Upload failed — see log")
        logger.info("run_builder: uploaded %s to watch dir", fname)
        self.request.response.redirect(
            "{0}/@@pfas-run-builder?batch_id={1}&ok=Uploaded+{2}+—+the+"
            "pipeline+worker+will+import+it".format(
                self.portal_url(), bid, fname))
        return u""

    def _redirect_err(self, batch_id, msg):
        self.request.response.redirect(
            "{0}/@@pfas-run-builder?batch_id={1}&error={2}".format(
                self.portal_url(), batch_id, msg.replace(" ", "+")))
        return u""
