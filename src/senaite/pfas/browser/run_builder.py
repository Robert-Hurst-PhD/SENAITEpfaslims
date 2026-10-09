# -*- coding: utf-8 -*-
"""
@@pfas-run-builder — LC-MS Run Builder (Instruments & Import).

Everything derives from the relational spine — nothing method-specific is
hardcoded here:
  * batch → METHOD via the same resolution logbooks use (extraction session >
    logbook annotations > SENAITE batch method);
  * the method's OWN extraction logbook (the extraction-titled entry of its
    `required_logbooks`) supplies the per-sample
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

try:
    from urllib import quote_plus
except ImportError:                                         # Python 3
    from urllib.parse import quote_plus

from zope.annotation.interfaces import IAnnotations
from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import MANAGER_ROLES, has_role_at_portal

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

# QC made at extraction (the extraction batch's members); the rest of a run
# template's tokens are instrument QC (CAL / ICV / CCV / CCB) the run adds
from senaite.pfas.extraction_batch import QC_ROLES as _QC_ROLES
EXTRACTION_QC = frozenset(r.upper() for r in _QC_ROLES)

# The run files uploaded for an extraction batch ([{file, kind, at}]): a
# supplementary run is processed together with them.
RUN_FILES_KEY = u"senaite.pfas.run_files"
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
        if action == "download_masslynx":
            return self._handle_download_masslynx()
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

    def import_problems(self):
        """The selected worksheet's delivered runs the worker has not
        imported (import_log; "will import it" was promised and a failure
        never shown)."""
        b = self._batch()
        if b is None:
            return []
        try:
            from senaite.pfas.qc.store import QCResultStore, DEFAULT_DB_PATH
            return QCResultStore(DEFAULT_DB_PATH).import_problems(b.getId())
        except Exception as exc:                            # noqa: BLE001
            logger.warning("import_problems: %s", exc)
            return []

    def _batch(self, batch_id=None):
        """The extraction batch: a WORKSHEET by id; a
        client Batch id (an older link) is followed to its worksheet."""
        from bika.lims import api
        from senaite.pfas import extraction_batch
        from senaite.pfas.batch_ref import get_batch
        bid = batch_id or self.selected_batch()
        if not bid:
            return None
        hits = api.search({"portal_type": "Worksheet", "getId": bid}, "senaite_catalog_worksheet")
        if hits:
            return api.get_object(hits[0])
        b = get_batch(self._portal(), bid)
        return extraction_batch.home(b) if b is not None else None

    def _client(self, b):
        """The client Batch of an extraction batch (its prep log and project)."""
        from senaite.pfas import extraction_batch
        if b is not None and extraction_batch.is_worksheet(b):
            return extraction_batch.linked_batch(b)
        return b

    def _members(self, b):
        from senaite.pfas import extraction_batch
        return extraction_batch.load(b) if b is not None and extraction_batch.is_worksheet(b) else []

    def qc_members(self, b):
        """{role: [injection]} of the extraction batch's QC members, in order."""
        out = {}
        for m in self._members(b):
            if m.get("role") and m.get("role") != u"Sample":
                out.setdefault(m["role"].upper(), []).append(m.get("injection"))
        return out

    # ── supplementary runs: what review asked for, made at the bench ──

    def made_requests(self, b=None):
        """Requests made at the bench and not yet run."""
        from senaite.pfas import extraction_batch
        b = b if b is not None else self._batch()
        if b is None or not extraction_batch.is_worksheet(b):
            return []
        return [r for r in extraction_batch.load_requests(b) if r.get("status") == u"made"]

    def run_files(self, b):
        try:
            return json.loads(IAnnotations(b).get(RUN_FILES_KEY) or u"[]")
        except (ValueError, TypeError):
            return []

    def _supplementary_rows(self, b, initials, method_id, include_cal, std, ccv):
        """Opening checks for the curve decision, the made requests under
        their LIMS-issued names, a bracket every `ccv` injections, a closing
        bracket."""
        from senaite.pfas import extraction_batch, run_plan
        from senaite.pfas.method_bridge import get_method_cal_code
        run_date = date.today()
        method_code = get_method_cal_code(self._portal(), method_id)
        tpl = self.run_template(method_id)
        bracket = tpl["bracket_qc"] or "CCV"
        roles = dict((m.get("injection"), m.get("role")) for m in extraction_batch.load(b))
        rows, counters = [], {}

        def add(name, typ, desc):
            rows.append({"vial": len(rows) + 1, "name": name, "type": typ, "description": desc})

        def add_qc(code):
            counters[code] = counters.get(code, 0) + 1
            name, desc = self._qc_injection(code, initials, u"", run_date, counters[code], std, method_code)
            add(name, self.qc_injection_type(code), desc)

        for tok in run_plan.opening([], include_cal, self._profile(method_id)):
            if tok == "CAL":
                for name, typ, desc in self._cal_rows(method_id, run_date, initials, std):
                    add(name, typ, desc)
            else:
                add_qc(tok)
        n = 0
        for r in self.made_requests(b):
            role = roles.get(r["injection"]) or u"Sample"
            what = (u"dilution 1 in %s of %s" % (r["fold"], r["injection"]) if r["kind"] == u"dilution"
                    else u"re-injection of %s" % r["injection"])
            add(r["new_injection"], self.qc_injection_type(role.upper()) if role != u"Sample" else "Sample",
                u"%s · %s · %s" % (initials, what, run_date.isoformat()))
            n += 1
            if n % max(1, int(ccv or 1)) == 0:
                add_qc(bracket)
        if not rows or rows[-1]["name"].find(bracket) < 0:
            add_qc(bracket)
        return rows

    def last_curve(self, method_id):
        """{run_date, status} of the method's most recent calibration on record
        (every analyte's curve of that run; approved only when all are)."""
        try:
            from senaite.pfas.qc.store import QCResultStore, DEFAULT_DB_PATH
            rows = QCResultStore(DEFAULT_DB_PATH).get_calibrations(method=method_id, limit=500) or []
        except Exception:                                   # noqa: BLE001
            return None
        if not rows:
            return None
        last = max(str(r.get("run_date") or "")[:10] for r in rows)

        def state(r):
            # the Calibrations page approves a run by recording who and when
            # (approve_run), leaving `status` as it was
            st = (r.get("status") or u"pending").lower()
            if st == u"rejected":
                return st
            return u"approved" if (st == u"approved" or r.get("approved_by")) else st
        states = set(state(r) for r in rows if str(r.get("run_date") or "")[:10] == last)
        status = u"approved" if states == set([u"approved"]) else sorted(states - set([u"approved"]))[0]
        return {"run_date": last, "status": status}

    def curve_decision(self, b=None):
        from datetime import date
        from senaite.pfas import run_plan
        b = b if b is not None else self._batch()
        mid = self.batch_method(b) if b is not None else u""
        if not mid:
            return None
        d = run_plan.curve_decision(self._profile(mid), self.last_curve(mid), date.today().isoformat())
        d["last"] = self.last_curve(mid)
        return d

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
        """The METHOD'S extraction logbook: the extraction-titled entry among
        its `required_logbooks`.

        An `extraction_logbook` profile override used to be consulted first.
        Nothing could write it -- no editor field, no seed, no migration -- so
        it was a setting the UI offered and could never honour, and every
        method silently took the fallback. The configurability audit found it by
        enumerating the keys this code READS rather than the keys the profile
        data happens to hold.

        It is removed rather than given a producer: `required_logbooks` already
        records which logbooks a method uses and is editable, so a second key
        naming one of them would be a second source of truth for one fact.
        """
        prof = self._profile(method_id)
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

    def ccv_interval(self, method_id, batch=None):
        """CCV frequency: project QAPP -> lab method profile -> published-
        method baseline, resolved via senaite.pfas.ruleset.resolve_for_batch
        -- the SAME three-tier path the numeric QC criteria already use.
        Never a form input.

        A project can tighten this (CCV every 5 samples instead of every
        10); a project-less batch (`batch=None`, or any batch with no linked
        project -- the default, and every batch that predates project
        support) falls straight through to the lab profile's
        instrument_verification.ccv.frequency exactly as this method read it
        directly before this change -- see ruleset.resolve()'s rule 3."""
        resolved = self._resolve_composition(method_id, batch, "ccv_frequency")
        try:
            return max(1, int(resolved))
        except (TypeError, ValueError):
            return 6

    def _resolve_composition(self, method_id, batch, key):
        """Resolve one QC-COMPOSITION key (ccv_frequency / lfsm_frequency /
        duplicate_all_samples) through project -> lab -> baseline via
        senaite.pfas.ruleset.resolve_for_batch -- the identical mechanism
        the numeric QC criteria already use. Returns the resolved value, or
        None if nothing resolves anywhere (a project-less batch with no lab
        value configured either -- both legitimate, never an error).

        Resolved DIRECTLY here, add-on side, because composition decides how
        THIS view builds a run -- never routed through
        senaite.pfas.resolved_criteria_store, which exists for the Py3
        pipeline worker's per-batch evaluation of already-produced results
        (see that module's docstring and); composition is a
        build-time decision that store was never meant to carry.
        """
        try:
            from senaite.pfas import ruleset
            from senaite.pfas import project_ref
            matrix = u""
            if batch is not None:
                try:
                    from senaite.pfas.browser.batch_project_viewlet import (
                        _batch_matrix)
                    matrix = _batch_matrix(self._portal(), batch) or u""
                except Exception:
                    matrix = u""
                if not matrix and project_ref.get_project_uid(batch):
                    # A project IS linked but its matrix can't be derived --
                    # the project tier is being SKIPPED, not "there is no
                    # override"; say so rather than resolving silently.
                    logger.warning(
                        "_resolve_composition(%s): batch %r is linked to a "
                        "project but its matrix could not be derived -- any "
                        "project-tier override for this key is being "
                        "skipped, not applied", key, batch)
            resolved = ruleset.resolve_for_batch(
                self._portal(), batch, method_id, matrix or None, key)
            return resolved.value
        except Exception as exc:
            logger.warning("_resolve_composition(%s) failed: %s", key, exc)
            return None

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
        from senaite.pfas.qc.qc_types import enabled_qc_types
        assoc = [str(c).upper() for c in enabled_qc_types(profile)]
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
        members = self._members(b)
        if members:
            # the extraction batch's samples, under their LIMS-issued names;
            # its QC members are placed by build_sequence
            # role from the record: a blank role sent build_sequence to guess
            # one from the Client Sample ID, and a sample whose id held
            # "CCV" / "ICV" / "LFB" (SYNTH-ccv_high-W1, found 2026-10-07)
            # took that QC's place -- the run lost its CCV
            return [{"sample_id": m.get("sample_id") or m.get("injection"),
                     "injection": m.get("injection"), "matrix": m.get("matrix") or u"",
                     "role": u"Sample", "spike": u"", "client_sample_id": m.get("client_sid") or u""}
                    for m in members if m.get("role") == u"Sample"]
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
        # Also pick up each sample's Client Sample ID. That is the field the
        # importer joins an instrument export on, so a worklist that proposes
        # anything else cannot round-trip: the analyst types the proposed name
        # at the instrument and the result then matches no sample.
        try:
            cat = getToolByName(self._portal(), "senaite_catalog_sample")
            for r in rows:
                # The extraction log names a sample however the bench writes
                # it — usually the Client Sample ID, not the lab id — so match
                # on either. Matching only on getId meant that filling in the
                # log stopped the lookup working and every sample picked up a
                # redundant method-code prefix in the worklist.
                brains = cat.unrestrictedSearchResults(
                    portal_type="AnalysisRequest", getId=r["sample_id"])
                if not brains:
                    brains = cat.unrestrictedSearchResults(
                        portal_type="AnalysisRequest",
                        getClientSampleID=r["sample_id"])
                for br in brains:
                    ar = br.getObject()
                    if not r.get("matrix"):
                        st = ar.getSampleType()
                        if st:
                            r["matrix"] = st.Title()
                    try:
                        r["client_sample_id"] = ar.getClientSampleID() or ""
                    except Exception:
                        r["client_sample_id"] = ""
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
                        "client_sample_id": (ar.getClientSampleID() or ""),
                    })
            except Exception:
                pass
        return rows

    def run_context(self):
        """Everything the form shows read-only, derived from the batch."""
        bid = self.selected_batch()
        if not bid:
            return None
        b = self._batch(bid)
        method_id = self.batch_method(b)
        slug = self.extraction_logbook_slug(method_id) if method_id else ""
        rows = self.sample_rows()
        return {
            "batch_id": bid,
            "method_id": method_id or "(unresolved)",
            "extraction_slug": slug or "(none set on method)",
            "ccv_interval": self.ccv_interval(method_id, batch=b) if method_id else 6,
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
        """The open extraction batches (worksheets)."""
        try:
            from senaite.pfas.browser.extraction_guide import extraction_queue
            return [{"id": r["id"], "title": r["title"]}
                    for r in extraction_queue(self._portal(), self.request)]
        except Exception as exc:                            # noqa: BLE001
            logger.warning("batches: %s", exc)
            return []

    # ── sequence construction ─────────────────────────────────────────────
    # QC code → which FM-ENV-002 (cal-prep log) lot field supplies the vial lot.
    # Standards ride the cal lot; matrix/blank spikes ride the analyte spike lot.
    _QC_LOT_FIELD = {
        "CAL": "cal_a_lot", "ICV": "cal_a_lot", "CCV": "cal_a_lot",
        "LFB": "analyte_spike_lot", "LFSM": "analyte_spike_lot",
        "LFSMD": "analyte_spike_lot",
    }

    CAL_PREP_SLUG = "251"   # FM-ENV-002 Calibration Curve Prep Log

    def _std_context(self, batch_id):
        """The batch's cal-prep logbook (FM-ENV-002) dict: prepared-standard lot
        refs + prepared date that LINK each standard injection to its lot.
        Returns {} when the log is not filled."""
        b = self._client(self._batch(batch_id))      # the prep log is the client Batch's
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
        from senaite.pfas import calibration_levels as cl
        from senaite.pfas.method_bridge import get_method_cal_code
        cal_lot = (std.get("cal_a_lot") or u"").strip() if std else u""
        prep = (std.get("prepared_date") or u"").strip() if std else u""
        code = get_method_cal_code(self._portal(), method_id)
        ymd = run_date.strftime("%y%m%d")
        out = []
        # one calibrator per level of the METHOD PROFILE's curve
        for lvl, _c in cl.calibrators(self._profile(method_id)):
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
                      method_code, name_code=None):
        """(name, description) for one QC injection. Injection name = the linked
        prepared-standard lot (cal/spike) + type; blanks & no-lot QC fall back to
        the method code. Description surfaces the lot + real prep date so the
        reviewer needn't open the logbook."""
        label = self._label(code)
        lot = self._qc_lot(code, std)
        prep = (std.get("prepared_date") or u"").strip() if std else u""
        ymd = run_date.strftime("%y%m%d")
        cu = code.upper()
        # the method's own name for the role (EPA 537.1: CCC, QCS); the role
        # itself is recorded on the row
        nc = name_code or cu
        if lot:
            name = u"{0}-{1}".format(lot, nc)
            if seq > 1:
                name = u"{0}-{1:02d}".format(name, seq)
            kind = u"spike lot" if cu in ("LFB", "LFSM", "LFSMD") else u"lot"
            desc = u"{0} · {1} · {2} {3}".format(initials, label, kind, lot)
            if prep:
                desc += u" · prep {0}".format(prep)
        else:
            name = u"{0}-{1}-{2}-{3:02d}".format(method_code, nc, ymd, seq)
            desc = u"{0} · {1} · {2} · {3}".format(
                initials, label, matrix or u"Lab",
                run_date.strftime("%Y-%m-%d"))
        return name, desc

    def build_sequence(self, sample_rows, initials, method_id, ccv_interval,
                       include_cal, std=None, duplicate_all_samples=None,
                       lfsm_frequency=None, qc_members=None):
        """Assemble the injection worklist by walking the method's run sequence.

        Each row carries a lot-code injection NAME (the linked prepared-standard
        lot where one exists — cal lot / spike lot from FM-ENV-002 — else the
        method code) and a human DESCRIPTION (analyst · QC type · lot · prep
        date). CAL opens the CCV-bracketed body; instrument-cal injections
        (CAL/ICV/CCV/CCB) don't advance the interval; extraction QC + samples do;
        a single closing CCV ends the run.

        `duplicate_all_samples` / `lfsm_frequency` are QC-COMPOSITION
        overrides (senaite.pfas.ruleset / senaite.pfas.run_composition) —
        applied ONLY inside the SAMPLES-token block, via
        run_composition.compose_sample_block(): every field sample optionally
        gets a duplicate injection, and an extra LFSM is optionally inserted
        every N field samples. Both are None by default, which is IDENTITY —
        a project-less batch (the caller's default) builds exactly the
        sequence it always has; see run_composition.py's docstring."""
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
        # the calibration and its verification for this run's curve decision
        # (run_plan.opening; the method profile's rule, else the bench chemist)
        from senaite.pfas import run_plan
        seq = run_plan.opening(seq, include_cal, self._profile(method_id))
        # the extraction batch's QC members play their roles under their own
        # LIMS-issued names; roles the template lacks follow the samples
        placed = run_plan.place_members(seq, dict(qc_members or {}), self.SAMPLES_TOKEN)
        n = max(1, int(ccv_interval or 1))
        noncount = self._noncount_codes()           # instrument cal ≠ body count

        rows = []
        counters = {}
        # pending_open: the ladder has run, but the bracket has NOT opened yet.
        # It opens immediately before the first COUNTING injection, so
        # instrument-cal injections (ICV, solvent blank) placed after the
        # calibrators stay in the calibration block — outside the bracketing.
        state = {"in_body": False, "pending_open": False,
                 "count": 0, "last_bracket": False}

        def add(name, typ, desc=u"", role=u"", level=u""):
            # `role` is what the row IS (CAL, ICV, CCV, CCB, MB, LFB, LFSM,
            # LFSMD, Dup, Sample): the pipeline reads it from this record, so
            # an injection's name may use the method's own terms (EPA 537.1:
            # CCC, QCS) -- 
            rows.append({"vial": len(rows) + 1, "name": name,
                         "type": typ, "description": desc, "role": role, "level": level})
            state["last_bracket"] = False

        from senaite.pfas.method_profile_sections import name_code
        prof = self._profile(method_id)

        def add_qc(code):
            counters[code] = counters.get(code, 0) + 1
            name, desc = self._qc_injection(
                code, initials, dom, run_date, counters[code], std, method_code,
                name_code(prof, code))
            add(name, self.qc_injection_type(code), desc, code.upper())

        def emit_bracket():
            add_qc(bracket)
            state["count"] = 0
            state["last_bracket"] = True
            state["pending_open"] = False

        def open_bracket_if_needed():
            """Open the bracket lazily — right before the first counting row."""
            if state["pending_open"]:
                emit_bracket()

        def body_tick():
            state["count"] += 1
            if state["count"] >= n:
                emit_bracket()

        spikes = [r.get("spike") for r in sample_rows if r.get("spike")]

        # A QC role the batch already holds as a registered sample is NOT
        # generated again: MB, LFSM and LFSMD were each appearing twice, once
        # from the sequence and once from the sample list, giving 27 vial
        # positions for a 20-injection run. An entry with no matching sample
        # still produces its injection, so a batch that does not register its
        # blank as a sample is not silently run without one.
        roles_in_samples = set()
        for r in sample_rows:
            role = (r.get("role") or "").strip().upper()
            if not role:
                role = self._role_from_sample(r)
            if role:
                roles_in_samples.add(role)
        supplied_by_samples = set()

        for tok, member in placed:
            if member is not None:
                counts = state["in_body"] and tok.upper() not in noncount
                if counts:
                    open_bracket_if_needed()
                add(member, self.qc_injection_type(tok.upper()),
                    u"{0} · {1} · {2}".format(initials, tok.upper(), sample_date), tok.upper())
                supplied_by_samples.add(tok.upper())
                if counts:
                    body_tick()
                continue
            if qc_members is not None and tok.upper() in EXTRACTION_QC:
                # a batch with members holds ALL its extraction QC: a template
                # token it has no member for is not invented (2026-10-06:
                # every injection name comes from the batch's record)
                supplied_by_samples.add(tok.upper())
                continue
            if tok == "CAL":
                if include_cal:
                    # each calibrator's level rides on its row: the
                    # instrument's sample list has a LEVEL column
                    for n_cal, (name, typ, desc) in enumerate(self._cal_rows(
                            method_id, run_date, initials, std), 1):
                        add(name, typ, desc, u"CAL", u"%d" % n_cal)
                    # bracket does NOT open here — it opens at the first
                    # counting injection, leaving ICV/solvent blank outside
                    state["in_body"] = True
                    state["pending_open"] = True
                continue
            if tok == self.SAMPLES_TOKEN:
                if not state["in_body"]:
                    state["in_body"] = True     # no CAL: body starts at samples
                    state["pending_open"] = True
                open_bracket_if_needed()        # samples count → open now
                from senaite.pfas import run_composition
                for r, marker in run_composition.compose_sample_block(
                        sample_rows, duplicate_all_samples, lfsm_frequency):
                    if marker == "lfsm":
                        # An interval-driven extra LFSM (QAPP composition
                        # override). Emitted even if the batch also registers
                        # its own LFSM sample elsewhere in the sequence —
                        # more QC than the template calls for is always safe
                        # under the direction rule, so no suppression here.
                        add_qc("LFSM")
                        body_tick()
                        continue
                    mtx = r.get("matrix") or dom
                    sid = r["sample_id"]
                    # Prefer the sample's Client Sample ID: it is what the
                    # importer matches on, so this is the name that makes the
                    # run round-trip. Fall back to the method-prefixed lab id
                    # for samples that have none.
                    csid = (r.get("client_sample_id") or "").strip()
                    # the extraction batch's LIMS-issued name first
                    name = r.get("injection") or csid or u"{0}-{1}".format(method_code, sid)
                    if marker == "duplicate":
                        name = u"{0}-DUP".format(name)
                        desc = u"{0} · Duplicate of {1} · {2} · {3}".format(
                            initials, sid, mtx or u"Lab", sample_date)
                    else:
                        desc = u"{0} · Sample {1} · {2} · {3}".format(
                            initials, sid, mtx or u"Lab", sample_date)
                    add(name, "Sample", desc, u"Dup" if marker == "duplicate" else u"Sample")
                    body_tick()
                continue
            # a QC token
            if tok == bracket and state["in_body"]:
                emit_bracket()       # an explicitly-placed bracket injection
                continue             # resets the interval; never double-counts
            if tok == bracket and not include_cal:
                # a run on a reused curve opens with its bracket check
                # (run_plan.opening): that CCV opens the body, never a second
                emit_bracket()
                state["in_body"] = True
                continue
            # instrument-cal injections (CAL/ICV/CCV/CCB) ride with the
            # calibration: they neither open the bracket nor advance the CCV
            # interval. Extraction QC (MB/LFB/LFSM/LFSMD) and field samples do.
            if tok.upper() in roles_in_samples:
                supplied_by_samples.add(tok.upper())
                continue                 # the registered sample plays this role

            counts = state["in_body"] and tok.upper() not in noncount
            if counts:
                open_bracket_if_needed()    # bracket opens BEFORE this row
            add_qc(tok)
            if counts:
                body_tick()

        # closing bracket (skip if the run already ended on one)
        if state["in_body"] and not state["last_bracket"]:
            emit_bracket()

        # Every QC role the method's sequence asks for must end up with an
        # injection, from the sequence or from a registered sample.
        emitted = {r["name"] for r in rows}
        missing = []
        for tok in seq:
            code = tok.upper()
            if code == self.SAMPLES_TOKEN or code in supplied_by_samples:
                continue
            if not any(code in n.upper() for n in emitted):
                missing.append(tok)
        self._missing_roles = missing
        return rows, dom, (spikes[0] if spikes else "")

    def _role_from_sample(self, row):
        """QC role a registered sample plays, from its id. Only used to decide
        whether a sequence entry is redundant, never to alter a result.

        Delegates to senaite.pfas.run_composition.classify_sample_role, which
        also backs that module's is_field_sample() (duplicate_all_samples /
        lfsm_frequency must only ever touch genuine field samples) — one
        definition, not two copies drifting apart."""
        from senaite.pfas import run_composition
        return run_composition.classify_sample_role(row)

    # ── actions ───────────────────────────────────────────────────────────
    def _handle_build(self):
        f = self.request.form
        batch_id = _first(f.get("batch_id")).strip()
        initials = _first(f.get("initials")).strip().upper()
        if not batch_id:
            return self._redirect_err(batch_id, "Select a batch first")
        if not initials:
            return self._redirect_err(batch_id, "Select the analyst")
        # A new calibration curve or not: the method
        # profile's rule, else the bench chemist's answer; a curve not
        # approved or too old is never reused (run_plan.curve_decision).
        decision = self.curve_decision(self._batch(batch_id)) or {}
        answer = _first(f.get("new_curve")).strip()
        if decision.get("forced"):
            include_cal = decision["forced"] == u"new"
        elif answer in ("yes", "no"):
            include_cal = answer == "yes"
        else:
            return self._redirect_err(batch_id, "Say whether a new calibration curve is needed")
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

        batch_obj = self._batch(batch_id)
        ccv = self.ccv_interval(method_id, batch=batch_obj)
        # QC-COMPOSITION overrides (senaite.pfas.ruleset / run_composition):
        # None for a project-less batch, which is IDENTITY -- see
        # build_sequence()'s docstring and run_composition.py.
        duplicate_all_samples = self._resolve_composition(
            method_id, batch_obj, "duplicate_all_samples")
        lfsm_frequency = self._resolve_composition(
            method_id, batch_obj, "lfsm_frequency")
        if _first(f.get("run_kind")) == "supplementary":
            made = self.made_requests(batch_obj)
            if not made:
                return self._redirect_err(batch_id, "No request made at the bench to run")
            std = self._std_context(batch_id)
            rows = self._supplementary_rows(batch_obj, initials, method_id, include_cal, std, ccv)
            manifest = {"built_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
                        "built_by": initials, "batch_id": batch_id, "method_id": method_id,
                        "kind": "supplementary", "requests": [r["id"] for r in made],
                        "ccv_interval": ccv, "worksheet_id": batch_obj.getId(),
                        "calibration": {"new_curve": bool(include_cal),
                                        "decided_by": (u"method profile" if decision.get("forced") else initials),
                                        "reason": decision.get("reason") or u"",
                                        "last_curve": decision.get("last") or None},
                        "rows": rows}
            IAnnotations(batch_obj)[RUN_MANIFEST_KEY] = json.dumps(manifest)
            self.request.response.redirect("{0}/@@pfas-run-builder?batch_id={1}&built=1".format(
                self.portal_url(), batch_id))
            return u""
        if self._members(batch_obj):
            # the batch's members already hold the plan's duplicates and
            # extra LFSMs (extraction_batch.plan_qc): never added twice
            duplicate_all_samples = lfsm_frequency = None
        std = self._std_context(batch_id)
        rows, dom, spike = self.build_sequence(
            rows_in, initials, method_id, ccv, include_cal, std=std,
            duplicate_all_samples=duplicate_all_samples,
            lfsm_frequency=lfsm_frequency,
            qc_members=self.qc_members(batch_obj) if self._members(batch_obj) else None)
        manifest = {
            "built_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            "built_by": initials,
            "batch_id": batch_id,
            "method_id": method_id,
            "extraction_logbook": self.extraction_logbook_slug(method_id),
            "dominant_matrix": dom,
            "ccv_interval": ccv,
            "spike_ppt": spike,
            # linked prepared-standard lots (from FM-ENV-002) recorded on the run
            "cal_lot": (std.get("cal_a_lot") or u""),
            "spike_lot": (std.get("analyte_spike_lot") or u""),
            "prep_date": (std.get("prepared_date") or u""),
            # QC-composition overrides actually applied to this run, for the
            # same reason cal_lot/spike_lot are recorded here: an output must
            # name its parentage -- a reviewer looking at
            # extra DUP/LFSM rows in `rows` should not have to guess why.
            "duplicate_all_samples": bool(duplicate_all_samples),
            "lfsm_frequency": lfsm_frequency,
            # the calibration decision and who made it (audit)
            "calibration": {"new_curve": bool(include_cal),
                            "decided_by": (u"method profile" if decision.get("forced") else initials),
                            "reason": decision.get("reason") or u"",
                            "last_curve": decision.get("last") or None},
            "worksheet_id": batch_obj.getId() if batch_obj is not None else u"",
            "rows": rows,
        }
        missing = getattr(self, "_missing_roles", []) or []
        if missing:
            manifest["missing_qc_roles"] = missing
            logger.warning("Batch %s: no injection for QC role(s) %s",
                           batch_id, missing)
        try:
            IAnnotations(self._batch(batch_id))[RUN_MANIFEST_KEY] = \
                json.dumps(manifest)
        except Exception as exc:
            logger.warning("manifest save failed: %s", exc)
        self.request.response.redirect(
            "{0}/@@pfas-run-builder?batch_id={1}&built=1{2}".format(
                self.portal_url(), batch_id,
                ("&warn=No+injection+for+" + "+".join(missing)) if missing else ""))
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
        note, error = self.deliver(bid, f.filename, f.read())
        if error:
            return self._redirect_err(bid, error)
        self.request.response.redirect(
            "{0}/@@pfas-run-builder?batch_id={1}&ok={2}".format(
                self.portal_url(), bid, quote_plus(note.encode("utf-8"))))
        return u""

    def deliver(self, bid, filename, data):
        """Hand an instrument export to the pipeline worker for the extraction
        batch `bid` (a worksheet id): its run record first, then the file, in
        the watched folder. The one way an export reaches the pipeline -- the
        Run Builder's upload and core's instrument import (core_instrument.py)
        both come here. Returns (message, error)."""
        self.request.form["batch_id"] = bid
        fname = re.sub(r"[^A-Za-z0-9._-]", "_", filename or u"run.csv")
        if not os.path.isdir(UPLOAD_DIR):
            try:
                os.makedirs(UPLOAD_DIR)
            except OSError:
                return u"", u"Watch directory unavailable"
        # A supplementary run (what review asked for) is processed together
        # with the extraction batch's earlier run files.
        b = self._batch(bid)
        m = self.manifest() or {}
        files = self.run_files(b) if b is not None else []
        # supplementary when the run built last is, unless this file is
        # already on record as the batch's full run (uploaded again)
        supplementary = m.get("kind") == "supplementary" and not any(
            x.get("file") == fname and x.get("kind") == "full" for x in files)
        extra = {}
        # the batch's runs are one record: a supplementary run joins every
        # earlier file; the full run, uploaded again, joins the supplementary
        # runs already recorded
        joins = [x["file"] for x in files if x.get("file") != fname
                 and (supplementary or x.get("kind") == "supplementary")]
        if joins:
            extra["supplementary_of"] = joins
        if supplementary:
            if not joins:
                return u"", (u"No earlier run of this batch is on record: "
                             u"upload its run first, then this one")
        # The run record goes in FIRST: the worker starts on the CSV the
        # moment it appears and reads the record beside it then.
        try:
            note = self._write_sidecar(bid, os.path.splitext(fname)[0], extra=extra)
        except Exception as exc:                            # noqa: BLE001
            logger.error("run_builder: extraction record not written: %s", exc)
            note = u"no extraction record (see log)"
        try:
            with open(os.path.join(UPLOAD_DIR, fname), "wb") as out:
                out.write(data)
        except Exception as exc:
            logger.error("upload failed: %s", exc)
            return u"", u"Upload failed — see log"
        logger.info("run_builder: uploaded %s to watch dir (%s)", fname, note)
        if b is not None:
            from senaite.pfas import extraction_batch
            files = [x for x in files if x.get("file") != fname] + [{
                "file": fname, "kind": "supplementary" if supplementary else "full",
                "at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}]
            IAnnotations(b)[RUN_FILES_KEY] = json.dumps(files)
            if supplementary and extraction_batch.is_worksheet(b):
                reqs = extraction_batch.load_requests(b)
                for r in reqs:
                    if r.get("id") in (m.get("requests") or []) and r.get("status") == u"made":
                        r["status"] = u"run"
                extraction_batch.save_requests(b, reqs)
        return (u"Uploaded {0}, {1}. The pipeline worker will import it.".format(fname, note), u"")

    def _batch_worksheet_id(self, batch):
        """The id of the one worksheet holding this batch's analyses, or ""
        when there is none or more than one (the run cannot be told apart)."""
        from bika.lims import api
        buid = api.get_uid(batch)
        found = []
        cat = getToolByName(self._portal(), "senaite_catalog_worksheet")
        for br in cat(portal_type="Worksheet"):
            ws = br.getObject()
            for an in ws.getAnalyses() or []:
                try:
                    ab = an.getRequest().getBatch()
                except Exception:                           # noqa: BLE001
                    ab = None
                if ab is not None and api.get_uid(ab) == buid:
                    found.append(ws.getId())
                    break
        return found[0] if len(found) == 1 else u""

    def _write_sidecar(self, batch_id, stem, extra=None):
        """Write `{stem}_extraction.json` beside the upload from the batch and
        its guided extraction (senaite.pfas.extraction_sidecar). Returns what
        the run record holds, for the confirmation message."""
        from senaite.pfas.extraction_sidecar import build_sidecar
        from senaite.pfas.browser.extraction_guide import _load_session
        from senaite.pfas.browser.batch_project_viewlet import _batch_matrix
        from senaite.pfas.method_profile_store import get_profile
        from bika.lims import api
        b = self._batch(batch_id)
        if b is None:
            return u"no batch chosen, so no method, matrix or extraction record"
        from senaite.pfas import extraction_batch
        sess = dict(_load_session(extraction_batch.home(b)))   # on the worksheet
        # the batch's one resolver (batch_method.resolve, core first; the
        # session is one of its sources), so the run is judged by the method
        # every other page shows -- the session used to win here
        sess["method_id"] = self.batch_method(b) or sess.get("method_id") or u""
        names = {}
        if sess["method_id"]:
            for st in get_profile(self._portal(), sess["method_id"]).get(
                    "extraction_stages") or []:
                names[u"%s" % st.get("order")] = st.get("name") or u""
        # the extraction batch is the worksheet; its client Batch names
        # the project, the prep log and the client
        cb = self._client(b)
        client = cb.getClient() if cb is not None and hasattr(cb, "getClient") else None
        ws_id = b.getId() if extraction_batch.is_worksheet(b) else self._batch_worksheet_id(b)
        matrix = _batch_matrix(self._portal(), cb) if cb is not None else u""
        if not matrix or client is None:
            # samples entered on a CoC belong to no client Batch: the
            # worksheet's own samples name the matrix (the most common) and
            # the client (found 2026-10-07, synthetic runs: no matrix meant
            # no spike amount was found and no spike was judged)
            ws_samples = extraction_batch.worksheet_samples(b) if extraction_batch.is_worksheet(b) else []
            mats = [s["matrix"] for s in ws_samples if s.get("matrix")]
            if not matrix and mats:
                matrix = max(set(mats), key=mats.count)
            if client is None and ws_samples:
                obj = api.get_object_by_uid(ws_samples[0]["uid"], None)
                client = obj.getClient() if obj is not None else None
        record = build_sidecar(sess, names, worksheet_id=ws_id,
                               senaite_batch_id=cb.getId() if cb is not None else u"",
                               matrix=matrix,
                               client_uid=api.get_uid(client) if client else u"")
        record.update(extra or {})
        path = os.path.join(UPLOAD_DIR, "{0}_extraction.json".format(stem))
        tmp = path + ".part"
        data = json.dumps(record, indent=2, sort_keys=True)
        with open(tmp, "wb") as out:
            out.write(data if isinstance(data, bytes) else data.encode("utf-8"))
        os.rename(tmp, path)
        parts = [u"worksheet {0}".format(ws_id) if ws_id else u"no single worksheet"]
        if cb is not None:
            parts.append(u"batch {0}".format(cb.getId()))
        parts.append(u"extraction finalized" if record["completed"]
                     else u"extraction in progress" if record["started"]
                     else u"no extraction recorded")
        return u", ".join(parts)

    # ── run-template save (Manager only — this is method configuration) ──
    def _is_manager(self):
        # Resolved at the portal via perms.
        return has_role_at_portal(self.context, MANAGER_ROLES)

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
            tpl = {"sequence": sequence, "bracket_qc": bracket}
            prof["run_template"] = tpl
            save_profile(portal, method_id, prof)
        except Exception as exc:
            logger.error("save_template failed: %s", exc)
            return self._redirect_err(batch_id, "Save failed — see log")
        self.request.response.redirect(
            "{0}/@@pfas-run-builder?batch_id={1}&tpl_saved=1".format(
                self.portal_url(), batch_id))
        return u""

    # ── the instrument's sample list (D4: Waters MassLynx) ──────────────────
    # The format is the worksheet's INSTRUMENT's, kept in Import Studio beside
    # its import mapping (instrument_export.py).

    def _instrument(self, b=None):
        b = b if b is not None else self._batch()
        try:
            return b.getInstrument() if b is not None and hasattr(b, "getInstrument") else None
        except Exception:                                   # noqa: BLE001
            return None

    def export_columns(self, b=None):
        from senaite.pfas import instrument_export
        return instrument_export.columns_for(self._instrument(b))[0]

    def export_source(self):
        from senaite.pfas import instrument_export
        return instrument_export.columns_for(self._instrument())[1]

    def masslynx_csv(self, manifest, b=None):
        """The built run as the instrument's sample list (bytes)."""
        from senaite.pfas import run_plan
        buf = io.BytesIO()
        w = csv.writer(buf)
        for line in run_plan.export_rows(manifest["rows"], self.export_columns(b)):
            w.writerow([(u"%s" % v).encode("utf-8") for v in line])
        return buf.getvalue()

    def _handle_download_masslynx(self):
        """The built run as the instrument's sample list (run_plan.export_rows)."""
        m = self.manifest()
        if not m:
            return self._redirect_err(self.selected_batch(), "No built run")
        data = self.masslynx_csv(m)
        resp = self.request.response
        resp.setHeader("Content-Type", "text/csv")
        resp.setHeader("Content-Disposition", "attachment; filename=masslynx_{0}.csv".format(
            re.sub(r"[^A-Za-z0-9_-]", "_", m.get("worksheet_id") or m["batch_id"] or "run")))
        return data

    def _redirect_err(self, batch_id, msg):
        self.request.response.redirect(
            "{0}/@@pfas-run-builder?batch_id={1}&error={2}".format(
                self.portal_url(), batch_id, msg.replace(" ", "+")))
        return u""
