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
    # A run template is ONE ordered sequence of injection tokens describing HOW
    # a worklist is assembled. Tokens are: a QC code (MB, LFB, ICV, LFSM, …),
    # the special "CAL" token (the calibration ladder), and exactly one
    # "SAMPLES" token (the batch's field samples). Stored on the method profile
    # (senaite.pfas.method_profiles) so the METHOD owns its sequence (§3). QC
    # codes are the canonical Reference-Definition vocabulary the control charts
    # / method profiles use — the run builder never invents its own QC list.
    #
    # CCV bracketing (2026-07-28 decision, user-confirmed): the CAL token
    # expands to the ladder + one OPENING bracket injection and starts the
    # bracketed BODY; every injection in the body — extracted QC AND field
    # samples alike — counts toward the "CCV every N" interval (N = the method's
    # own CCV frequency); a CLOSING bracket ends the run. Extracted QC therefore
    # sit INSIDE the bracketing simply by being placed after CAL in the
    # sequence. Tokens before CAL (e.g. a system MeOH blank) are pre-bracket.

    SAMPLES_TOKEN = "SAMPLES"

    def _default_run_template(self, profile):
        """Sensible starting sequence derived from the method's own QC types.

        Reproduces the historic order (system MB, calibration, ICV, MB, LFB for
        methods that use it, samples, matrix-spike QC) as a single editable
        sequence. The opening/interval/closing CCVs are inserted automatically
        at build time, so no literal bracket token is seeded."""
        assoc = [str(c).upper() for c in (profile.get("associated_qc_types") or [])]
        seq = ["MB", "CAL", "ICV", "MB"]
        if "LFB" in assoc:
            seq.append("LFB")
        seq.append(self.SAMPLES_TOKEN)
        seq += [q for q in ("LFSM", "LFSMD") if q in assoc]
        return {"sequence": seq, "bracket_qc": "CCV"}

    def run_template(self, method_id):
        """The saved run template for a method, else the derived default.

        Migrates the legacy {opening, closing} shape to a single sequence:
        opening + SAMPLES + closing (a trailing literal CCV in the old closing
        block is harmless — build_sequence de-dupes the auto closing CCV)."""
        prof = self._profile(method_id)
        tpl = prof.get("run_template")
        if isinstance(tpl, dict):
            if tpl.get("sequence"):
                return {
                    "sequence":   [str(c) for c in tpl["sequence"]],
                    "bracket_qc": str(tpl.get("bracket_qc") or "CCV"),
                }
            if tpl.get("opening") or tpl.get("closing"):
                seq = [str(c) for c in (tpl.get("opening") or [])]
                seq.append(self.SAMPLES_TOKEN)
                seq += [str(c) for c in (tpl.get("closing") or [])]
                return {"sequence": seq,
                        "bracket_qc": str(tpl.get("bracket_qc") or "CCV")}
        return self._default_run_template(prof)

    def current_template(self):
        """Run template for the selected batch's method (for the config UI)."""
        method_id = self.batch_method()
        if not method_id:
            return None
        tpl = self.run_template(method_id)
        vocab = {v["code"]: v["label"] for v in self.qc_vocabulary()}
        n = len(self.sample_rows())
        # guarantee exactly one SAMPLES token so the UI always shows the block
        seq = [c for c in tpl["sequence"] if c != self.SAMPLES_TOKEN]
        insert_at = tpl["sequence"].index(self.SAMPLES_TOKEN) \
            if self.SAMPLES_TOKEN in tpl["sequence"] else len(seq)
        seq.insert(min(insert_at, len(seq)), self.SAMPLES_TOKEN)
        tpl["sequence_labelled"] = [self._chip(c, vocab, n) for c in seq]
        tpl["n_samples"] = n
        return tpl

    def _chip(self, code, vocab, n_samples=0):
        """One row descriptor for the sequence editor."""
        if code == self.SAMPLES_TOKEN:
            return {"code": code, "kind": "samples", "removable": False,
                    "label": u"Field samples ({0})".format(n_samples)}
        if code == "CAL":
            return {"code": code, "kind": "cal", "removable": True,
                    "label": u"Calibrator list"}
        kind = "blank" if self.qc_injection_type(code) == "Blank" else "qc"
        return {"code": code, "kind": kind, "removable": True,
                "label": vocab.get(code, code)}

    def add_vocabulary(self):
        """QC types offered in the sequence add-list — the full vocabulary minus
        the bracket QC (CCV), which is inserted automatically from the method's
        CCV frequency, never placed by hand."""
        return [v for v in self.qc_vocabulary() if v["code"] != "CCV"]

    def _noncount_codes(self):
        """QC codes that DON'T advance the CCV interval — the instrument
        calibration/verification injections (the calibrator ladder, ICV, CCV).
        They are counted like calibrators, not like body injections. Sourced
        from the Reference Definition 'instrument' category; constant fallback."""
        cache = getattr(self, "_noncount_cache", None)
        if cache is not None:
            return cache
        out = set()
        try:
            folder = self._portal().bika_setup.bika_referencedefinitions
            tagre = re.compile(r"\[QC:\s*([A-Za-z0-9_]+)\s*\]")
            for d in folder.objectValues():
                cat = u""
                try:
                    cat = d.getField("pfas_category").get(d) or u""
                except Exception:
                    pass
                if cat != "instrument":
                    continue
                code = None
                try:
                    code = d.getField("pfas_qc_code").get(d)
                except Exception:
                    pass
                if not code:
                    m = tagre.search(d.Description() or u"")
                    code = m.group(1) if m else None
                if code:
                    out.add(code.upper())
        except Exception as exc:
            logger.warning("_noncount_codes: %s", exc)
        # CAL/ICV/CCV are instrument-cal; CCB is the solvent/system blank — all
        # ride with the calibration, none advance the sample CCV interval.
        out |= set(["CAL", "ICV", "CCV", "CCB"])
        self._noncount_cache = out
        return out

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
    # QC code → which FM-ENV-251 (cal-prep log) lot field supplies the vial lot.
    # Standards ride the cal lot; matrix/blank spikes ride the analyte spike lot.
    _QC_LOT_FIELD = {
        "CAL": "cal_a_lot", "ICV": "cal_a_lot", "CCV": "cal_a_lot",
        "LFB": "analyte_spike_lot", "LFSM": "analyte_spike_lot",
        "LFSMD": "analyte_spike_lot",
    }

    CAL_PREP_SLUG = "251"   # FM-ENV-251 Calibration Curve Prep Log

    def _std_context(self, batch_id):
        """The batch's cal-prep logbook (FM-ENV-251) dict: prepared-standard lot
        refs + prepared date that LINK each standard injection to its lot.
        Returns {} when the log is not filled."""
        b = self._batch(batch_id)
        if b is None:
            return {}
        return self._extraction_log(b, self.CAL_PREP_SLUG) or {}

    def _qc_lot(self, code, std):
        field = self._QC_LOT_FIELD.get(code.upper())
        return (std.get(field) or u"").strip() if (field and std) else u""

    def _label_map(self):
        cache = getattr(self, "_lbl_cache", None)
        if cache is None:
            try:
                from senaite.pfas.qc_labels import get_qc_label_map
                cache = get_qc_label_map(self._portal())
            except Exception:
                cache = {}
            self._lbl_cache = cache
        return cache

    def _label(self, code):
        m = self._label_map()
        return m.get(code) or m.get(code.upper(), code)

    def _cal_rows(self, method_id, run_date, initials, std):
        """(name, type, description) per calibrator level. Injection name = the
        recorded cal lot + level (else method code); description carries analyst,
        level, lot and the real prep date."""
        from senaite.pfas.analyte_reference import get_cal_ladder
        from senaite.pfas.method_bridge import get_method_cal_code
        cal_lot = (std.get("cal_a_lot") or u"").strip() if std else u""
        prep = (std.get("prepared_date") or u"").strip() if std else u""
        code = get_method_cal_code(self._portal(), method_id)
        ymd = run_date.strftime("%y%m%d")
        out = []
        for i, _c in enumerate(get_cal_ladder(method_id) or []):
            lvl = i + 1
            name = (u"{0}-L{1}".format(cal_lot, lvl) if cal_lot
                    else u"{0}-CAL-{1}-{2}".format(code, lvl, ymd))
            desc = u"{0} · Calibrator L{1}".format(initials, lvl)
            if cal_lot:
                desc += u" · lot {0}".format(cal_lot)
            if prep:
                desc += u" · prep {0}".format(prep)
            out.append((name, "Standard", desc))
        return out

    def _qc_injection(self, code, initials, matrix, run_date, seq, std,
                      method_code):
        """(name, description) for one QC injection. Injection name = the linked
        prepared-standard lot (cal/spike) + type; blanks & no-lot QC fall back to
        the method code. Description surfaces the lot + real prep date so the
        reviewer needn't open the logbook."""
        label = self._label(code)
        lot = self._qc_lot(code, std)
        prep = (std.get("prepared_date") or u"").strip() if std else u""
        ymd = run_date.strftime("%y%m%d")
        cu = code.upper()
        if lot:
            name = u"{0}-{1}".format(lot, cu)
            if seq > 1:
                name = u"{0}-{1:02d}".format(name, seq)
            kind = u"spike lot" if cu in ("LFB", "LFSM", "LFSMD") else u"lot"
            desc = u"{0} · {1} · {2} {3}".format(initials, label, kind, lot)
            if prep:
                desc += u" · prep {0}".format(prep)
        else:
            name = u"{0}-{1}-{2}-{3:02d}".format(method_code, cu, ymd, seq)
            desc = u"{0} · {1} · {2} · {3}".format(
                initials, label, matrix or u"Lab",
                run_date.strftime("%Y-%m-%d"))
        return name, desc

    def build_sequence(self, sample_rows, initials, method_id, ccv_interval,
                       include_cal, std=None):
        """Assemble the injection worklist by walking the method's run sequence.

        Each row carries a lot-code injection NAME (the linked prepared-standard
        lot where one exists — cal lot / spike lot from FM-ENV-251 — else the
        method code) and a human DESCRIPTION (analyst · QC type · lot · prep
        date). CAL opens the CCV-bracketed body; instrument-cal injections
        (CAL/ICV/CCV/CCB) don't advance the interval; extraction QC + samples do;
        a single closing CCV ends the run."""
        from senaite.pfas.method_bridge import get_method_cal_code
        std = std or {}
        run_date = date.today()
        sample_date = run_date.strftime("%Y-%m-%d")
        # QC rows use the run's dominant matrix (from the extraction log)
        matrices = [r.get("matrix") for r in sample_rows if r.get("matrix")]
        dom = max(set(matrices), key=matrices.count) if matrices else "Lab"
        method_code = get_method_cal_code(self._portal(), method_id)
        tpl = self.run_template(method_id)
        bracket = tpl["bracket_qc"] or "CCV"
        seq = list(tpl["sequence"])
        if self.SAMPLES_TOKEN not in seq:
            seq.append(self.SAMPLES_TOKEN)          # samples are never optional
        n = max(1, int(ccv_interval or 1))
        noncount = self._noncount_codes()           # instrument cal ≠ body count

        rows = []
        counters = {}
        state = {"in_body": False, "count": 0, "last_bracket": False}

        def add(name, typ, desc=u""):
            rows.append({"vial": len(rows) + 1, "name": name,
                         "type": typ, "description": desc})
            state["last_bracket"] = False

        def add_qc(code):
            counters[code] = counters.get(code, 0) + 1
            name, desc = self._qc_injection(
                code, initials, dom, run_date, counters[code], std, method_code)
            add(name, self.qc_injection_type(code), desc)

        def emit_bracket():
            add_qc(bracket)
            state["count"] = 0
            state["last_bracket"] = True

        def body_tick():
            state["count"] += 1
            if state["count"] >= n:
                emit_bracket()

        spikes = [r.get("spike") for r in sample_rows if r.get("spike")]

        for tok in seq:
            if tok == "CAL":
                if include_cal:
                    for name, typ, desc in self._cal_rows(
                            method_id, run_date, initials, std):
                        add(name, typ, desc)
                    emit_bracket()              # opening bracket
                    state["in_body"] = True
                continue
            if tok == self.SAMPLES_TOKEN:
                if not state["in_body"]:
                    emit_bracket()              # open body when there is no CAL
                    state["in_body"] = True
                for i, r in enumerate(sample_rows):
                    mtx = r.get("matrix") or dom
                    sid = r["sample_id"]
                    add(u"{0}-{1}".format(method_code, sid), "Sample",
                        u"{0} · Sample {1} · {2} · {3}".format(
                            initials, sid, mtx or u"Lab", sample_date))
                    body_tick()
                continue
            # a QC token
            if tok == bracket and state["in_body"]:
                emit_bracket()       # an explicitly-placed bracket injection
                continue             # resets the interval; never double-counts
            add_qc(tok)
            # instrument-cal injections (CAL/ICV/CCV/CCB) are counted like
            # calibrators — they do NOT advance the CCV interval; extraction QC
            # + field samples do.
            if state["in_body"] and tok.upper() not in noncount:
                body_tick()

        # closing bracket (skip if the run already ended on one)
        if state["in_body"] and not state["last_bracket"]:
            emit_bracket()
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
        std = self._std_context(batch_id)
        rows, dom, spike = self.build_sequence(
            rows_in, initials, method_id, ccv, include_cal, std=std)
        manifest = {
            "built_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            "built_by": initials,
            "batch_id": batch_id,
            "method_id": method_id,
            "extraction_logbook": self.extraction_logbook_slug(method_id),
            "dominant_matrix": dom,
            "ccv_interval": ccv,
            "spike_ppt": spike,
            # linked prepared-standard lots (from FM-ENV-251) recorded on the run
            "cal_lot": (std.get("cal_a_lot") or u""),
            "spike_lot": (std.get("analyte_spike_lot") or u""),
            "prep_date": (std.get("prepared_date") or u""),
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
        w.writerow([b"Vial", b"Sample Name", b"Description", b"Sample Type"])
        for r in m["rows"]:
            w.writerow([r["vial"], r["name"].encode("utf-8"),
                        (r.get("description") or u"").encode("utf-8"),
                        r["type"]])
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

        raw = _first(f.get("sequence_codes")) or u""
        sequence = [c.strip() for c in raw.split(",") if c.strip()]
        if self.SAMPLES_TOKEN not in sequence:
            sequence.append(self.SAMPLES_TOKEN)     # samples are never optional
        bracket = _first(f.get("bracket_qc")).strip() or "CCV"

        portal = self._portal()
        try:
            from senaite.pfas.method_profile_store import (
                get_profile, save_profile)
            prof = get_profile(portal, method_id)
            prof["run_template"] = {
                "sequence": sequence, "bracket_qc": bracket}
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
