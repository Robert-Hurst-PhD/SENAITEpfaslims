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
from senaite.pfas.browser.formutil import flatten_form

logger = logging.getLogger("senaite.pfas.browser.run_builder")


def _first(value, default=u""):
    """First value if the form field arrived as a list (Zope merges duplicate
    query-string + POST-body params into a list — e.g. batch_id, which is both
    in the page URL from the batch selector and a hidden field in the build/
    upload forms). Returns a string so .strip()/.splitlines() are always safe."""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else default
    return default if value is None else value


RUN_MANIFEST_KEY = u"senaite.pfas.run_manifest"
UPLOAD_DIR = os.environ.get("PFAS_INSTRUMENT_UPLOAD_DIR",
                            "/addon/data/instrument_output")


class PFASRunBuilderView(BrowserView):
    template = ViewPageTemplateFile("templates/run_builder.pt")

    def __call__(self):
        flatten_form(self.request)
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
            if action == "save_template":
                return self._handle_save_template()
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
        return _first(self.request.form.get("batch_id", ""))

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

    # ── run template (per-method, editable) ──────────────────────────────
    #
    # A run template describes HOW a worklist is assembled: an ordered opening
    # QC block, the QC type that BRACKETS the samples (frequency comes from the
    # method's own CCV parameter — single source), and an ordered closing QC
    # block. Stored on the method profile (senaite.pfas.method_profiles) so the
    # METHOD owns its sequence (§3). QC codes are the canonical vocabulary the
    # control charts / method profiles already use — the run builder never
    # invents its own QC list.
    #
    # The special "CAL" token in the opening block expands, at build time, to
    # the method's calibration ladder followed by one bracketing injection —
    # but only when the per-run "include calibration" box is checked.

    def _default_run_template(self, profile):
        """Sensible starting template derived from the method's own QC types.

        Reproduces the historic hardcoded sequence: MB, calibration, ICV, MB,
        (LFB only for methods that use it), samples bracketed by CCV, then the
        matrix-spike QC and a closing CCV. Nothing method-specific is hardcoded
        beyond reading the method's associated_qc_types."""
        assoc = [str(c).upper() for c in (profile.get("associated_qc_types") or [])]
        opening = ["MB", "CAL", "ICV", "MB"]
        if "LFB" in assoc:
            opening.append("LFB")
        closing = [q for q in ("LFSM", "LFSMD") if q in assoc] + ["CCV"]
        return {"opening": opening, "closing": closing, "bracket_qc": "CCV"}

    def run_template(self, method_id):
        """The saved run template for a method, else the derived default."""
        prof = self._profile(method_id)
        tpl = prof.get("run_template")
        if isinstance(tpl, dict) and (tpl.get("opening") or tpl.get("closing")):
            return {
                "opening":    [str(c) for c in (tpl.get("opening") or [])],
                "closing":    [str(c) for c in (tpl.get("closing") or [])],
                "bracket_qc": str(tpl.get("bracket_qc") or "CCV"),
            }
        return self._default_run_template(prof)

    def current_template(self):
        """Run template for the selected batch's method (for the config UI)."""
        method_id = self.batch_method()
        if not method_id:
            return None
        tpl = self.run_template(method_id)
        vocab = {v["code"]: v["label"] for v in self.qc_vocabulary()}
        tpl["opening_labelled"] = [
            {"code": c, "label": self._chip_label(c, vocab)} for c in tpl["opening"]]
        tpl["closing_labelled"] = [
            {"code": c, "label": self._chip_label(c, vocab)} for c in tpl["closing"]]
        return tpl

    def _chip_label(self, code, vocab):
        if code == "CAL":
            return vocab.get("CAL", "Calibration ladder")
        return vocab.get(code, code)

    def qc_vocabulary(self):
        """[{code,label}] of QC types, from the single Reference-Definition
        source the control charts and method profiles use."""
        try:
            from senaite.pfas.qc_labels import get_qc_label_map
            m = get_qc_label_map(self._portal())
        except Exception as exc:
            logger.warning("qc_vocabulary: %s", exc)
            m = {}
        return [{"code": k, "label": m[k]} for k in sorted(m)]

    def _blank_codes(self):
        """QC codes whose injection type is Blank (from the Reference
        Definition blank flag), with a conservative constant fallback."""
        cache = getattr(self, "_blank_cache", None)
        if cache is not None:
            return cache
        out = set()
        try:
            folder = self._portal().bika_setup.bika_referencedefinitions
            tagre = re.compile(r"\[QC:\s*([A-Za-z0-9_]+)\s*\]")
            for d in folder.objectValues():
                code = None
                try:
                    code = d.getField("pfas_qc_code").get(d)
                except Exception:
                    pass
                if not code:
                    m = tagre.search(d.Description() or "")
                    code = m.group(1) if m else None
                if code and d.getBlank():
                    out.add(code.upper())
        except Exception as exc:
            logger.warning("_blank_codes: %s", exc)
        out |= set(["MB", "LRB", "MXB", "CCB"])
        self._blank_cache = out
        return out

    def qc_injection_type(self, code):
        """Worklist 'Sample Type' column for a QC code: Standard for the
        calibration ladder, Blank for blank QC types, QC otherwise."""
        if code == "CAL":
            return "Standard"
        return "Blank" if code.upper() in self._blank_codes() else "QC"

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
        """Assemble the injection worklist from the method's run template.

        Output shape (vial / name / type per row) is identical to the previous
        hardcoded builder — only the ORDER and QC SELECTION now come from the
        editable per-method template instead of literals."""
        run_date = date.today()
        # QC rows use the run's dominant matrix (from the extraction log)
        matrices = [r.get("matrix") for r in sample_rows if r.get("matrix")]
        dom = max(set(matrices), key=matrices.count) if matrices else "Lab"
        tpl = self.run_template(method_id)
        bracket = tpl["bracket_qc"] or "CCV"

        rows = []
        counters = {}
        first_blank = [False]

        def add(name, typ):
            rows.append({"vial": len(rows) + 1, "name": name, "type": typ})

        def add_qc(code):
            counters[code] = counters.get(code, 0) + 1
            typ = self.qc_injection_type(code)
            suffix = u""
            # preserve the historic "first blank is the MeOH system blank" cue
            if typ == "Blank" and not first_blank[0]:
                suffix = u" MeOH-Blank"
                first_blank[0] = True
            add(self._qc_name(initials, dom, code, run_date, counters[code])
                + suffix, typ)

        # ── opening block (CAL token expands to the ladder + one bracket) ──
        for code in tpl["opening"]:
            if code == "CAL":
                if include_cal:
                    for name, typ in self._cal_names(method_id, run_date):
                        add(name, typ)
                    add_qc(bracket)
                continue
            add_qc(code)

        # ── samples, bracketed by the template's bracket QC every N ──
        since_ccv = 0
        spikes = [r.get("spike") for r in sample_rows if r.get("spike")]
        for i, r in enumerate(sample_rows):
            mtx = r.get("matrix") or dom
            add(u"{0} {1} Sample {2}-{3:02d} {4}".format(
                initials, mtx, run_date.strftime("%Y-%m-%d"), i + 1,
                r["sample_id"]), "Sample")
            since_ccv += 1
            if since_ccv >= ccv_interval:
                add_qc(bracket)
                since_ccv = 0

        # ── closing block ──
        for code in tpl["closing"]:
            add_qc(code)
        return rows, dom, (spikes[0] if spikes else "")

    # ── actions ───────────────────────────────────────────────────────────
    def _handle_build(self):
        f = self.request.form
        batch_id = _first(f.get("batch_id")).strip()
        initials = _first(f.get("initials")).strip().upper()
        include_cal = _first(f.get("include_cal")) in ("on", "1", "true")
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
        for s in _first(f.get("extra_samples")).splitlines():
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
        bid = _first(self.request.form.get("batch_id")).strip()
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

    # ── run-template save (Manager only — this is method configuration) ──
    def _is_manager(self):
        try:
            from AccessControl import getSecurityManager
            roles = getSecurityManager().getUser().getRolesInContext(self.context)
            return "Manager" in roles or "LabManager" in roles
        except Exception:
            return False

    def template_saved(self):
        return self.request.form.get("tpl_saved", "") == "1"

    def can_edit_template(self):
        return self._is_manager()

    def _handle_save_template(self):
        f = self.request.form
        batch_id = _first(f.get("batch_id")).strip()
        if not self._is_manager():
            return self._redirect_err(
                batch_id, "Only a Manager may edit the run template")
        method_id = (_first(f.get("method_id")).strip()
                     or self.batch_method(self._batch(batch_id)))
        if not method_id:
            return self._redirect_err(batch_id, "No method to configure")

        def parse(name):
            raw = _first(f.get(name)) or u""
            return [c.strip() for c in raw.split(",") if c.strip()]

        opening = parse("opening_codes")
        closing = parse("closing_codes")
        bracket = _first(f.get("bracket_qc")).strip() or "CCV"

        portal = self._portal()
        try:
            from senaite.pfas.method_profile_store import (
                get_profile, save_profile)
            prof = get_profile(portal, method_id)
            prof["run_template"] = {
                "opening": opening, "closing": closing, "bracket_qc": bracket}
            save_profile(portal, method_id, prof)
        except Exception as exc:
            logger.error("save_template failed: %s", exc)
            return self._redirect_err(batch_id, "Save failed — see log")
        self.request.response.redirect(
            "{0}/@@pfas-run-builder?batch_id={1}&tpl_saved=1".format(
                self.portal_url(), batch_id))
        return u""

    def _redirect_err(self, batch_id, msg):
        self.request.response.redirect(
            "{0}/@@pfas-run-builder?batch_id={1}&error={2}".format(
                self.portal_url(), batch_id, msg.replace(" ", "+")))
        return u""
