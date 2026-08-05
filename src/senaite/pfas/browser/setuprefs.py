# -*- coding: utf-8 -*-
"""
PFAS Reference Definition setup view.

Registered at @@pfas-setup-references on the SENAITE portal.
Creates or updates one SENAITE ReferenceDefinition per QC type,
with per-analyte expected values, ranges, and error tolerances
derived from the QC rules store.

Also stamps each definition with the three PFAS pool metadata fields
(pfas_qc_code, pfas_category, pfas_acceptance_schema) added by the
schema extender, so the Reference Definitions area in SENAITE Setup
acts as the live QC Type Pool.

Requires Manager role.
Python 2.7-compatible (runs inside Zope/Plone).
"""
from __future__ import absolute_import, print_function, unicode_literals

import logging

from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from senaite.pfas.browser.formutil import flatten_form

logger = logging.getLogger("senaite.pfas.browser.setuprefs")

# ── QC type pool definitions ─────────────────────────────────────────────────
#
# code: (title, is_blank, ref_strategy, category, acceptance_schema)
#
#   ref_strategy      — how to build the SENAITE ReferenceResults entries
#   category          — blank | extraction | instrument
#   acceptance_schema — parameter schema used in Method Profile QC Acceptance
#                       blank_threshold | recovery_tiered | tiered_recovery_rpd
#                       rpd_tiered | instrument_cal | instrument_ccv
#
# Titles carry NO "PFAS " prefix — these are the user-facing QC-type labels
# (control-chart dropdown/legend, method-profile toggles). The prefix was
# stripped from both the seed here and the live Reference Definitions; the
# stable identity is the QC code (the dict key / pfas_qc_code field), never
# the editable Title.
QC_REF_SPEC = {
    # ── Blank QC types ──────────────────────────────────────────────────────
    "MB":    ("Method Blank",
              True,  "blank",
              "blank", "blank_threshold"),
    "LRB":   ("Lab Reagent Blank",
              True,  "blank",
              "blank", "blank_threshold"),
    "MxB":   ("Matrix Blank",
              True,  "blank",
              "blank", "blank_threshold"),

    # ── Calibration / instrument verification ────────────────────────────────
    "CAL":   ("Calibration Standard",
              False, "cal_dev",
              "instrument", "instrument_cal"),
    "ICV":   ("Initial Calibration Verification",
              False, "cal_dev_tight",
              "instrument", "instrument_cal"),
    "CCV":   ("Continuing Calibration Verification",
              False, "cal_dev_tight",
              "instrument", "instrument_ccv"),

    # ── Extraction / matrix QC types ────────────────────────────────────────
    "LFB":   ("Laboratory Fortified Blank",
              False, "recovery",
              "extraction", "recovery_tiered"),
    "LCS":   ("Laboratory Control Sample",
              False, "recovery",
              "extraction", "recovery_tiered"),
    "LFSM":  ("Lab Fortified Sample Matrix",
              False, "recovery",
              "extraction", "recovery_tiered"),
    "LFSMD": ("LFSM Duplicate",
              False, "recovery_dup",
              "extraction", "tiered_recovery_rpd"),
    "Dup":   ("Sample Duplicate",
              False, "rpd",
              "extraction", "rpd_tiered"),
}


def _is_manager(context):
    try:
        from AccessControl import getSecurityManager
        user = getSecurityManager().getUser()
        return "Manager" in user.getRolesInContext(context) or \
               "LabManager" in user.getRolesInContext(context)
    except Exception:
        return False


def _ref_def_code(obj):
    """The QC code an existing ReferenceDefinition carries, if any."""
    try:
        code = obj.getField("pfas_qc_code").get(obj)
        if code:
            return code
    except Exception:
        pass
    return None


def _get_or_create_ref_def(folder, code, title, is_blank=False):
    """
    Idempotently get or create a ReferenceDefinition for a QC type.

    Identity is the STABLE QC code (pfas_qc_code), so the Title stays freely
    UI-editable without this setup ever recreating a duplicate. Falls back to
    a title match only for legacy defs created before the code field existed.
    Returns (obj, created_bool).
    """
    from bika.lims import api
    for obj in folder.objectValues():
        try:
            if _ref_def_code(obj) == code:
                return obj, False
        except Exception:
            pass
    for obj in folder.objectValues():
        try:
            if obj.Title() == title:
                return obj, False
        except Exception:
            pass
    obj = api.create(folder, "ReferenceDefinition", title=title)
    obj.setBlank(is_blank)
    return obj, True


def _stamp_pfas_fields(obj, qc_code, category, acceptance_schema):
    """
    Write pfas_qc_code / pfas_category / pfas_acceptance_schema onto a
    ReferenceDefinition using the schema-extender field mutators.
    Silently skips if the field isn't present (extender not yet loaded).
    """
    for attr, value in (
        ("pfas_qc_code", qc_code),
        ("pfas_category", category),
        ("pfas_acceptance_schema", acceptance_schema),
    ):
        setter = "set" + attr[0].upper() + attr[1:]
        try:
            getattr(obj, setter)(value)
        except AttributeError:
            try:
                obj.getField(attr).set(obj, value)
            except Exception:
                pass
        except Exception as exc:
            logger.warning("_stamp_pfas_fields: %s.%s = %r failed: %s",
                           obj.Title(), attr, value, exc)


def _profile_limits(profile, qc_code):
    """Per-tier recovery limits from the METHOD PROFILE, or None.

    The profile's qc_acceptance is what the QC engine enforces. Reference
    Definitions were built from qc_rules.qc_types instead, which carries its own
    numbers: on this system LFSM reads 40-140 there while the engine judges at
    65-135 (tier 2) and 80-120 (tier 1). A control chart drawn at limits the
    engine does not use misleads the reviewer looking at it.
    """
    if not profile:
        return None, None
    try:
        from senaite.pfas.spec_sync import _tier_limits, _build_kw_to_tier
    except Exception:                                       # noqa: BLE001
        return None, None
    try:
        limits = _tier_limits(profile.get("qc_acceptance") or {}, qc_code)
        return limits, (_build_kw_to_tier(profile) or {})
    except Exception as exc:                                # noqa: BLE001
        logger.warning("could not resolve %s limits from the method profile: "
                       "%s", qc_code, exc)
        return None, None


def _build_reference_results(qc_code, rules, analyte_uids, profile=None):
    """
    Build the list of ReferenceResults dicts for one QC type.

    Returns a list of {"uid": <uid>, "result": str, "min": str,
                        "max": str, "error": str} dicts.
    """
    from senaite.pfas.analytes import KEY_ANALYTES
    qt = rules.get("qc_types", {}).get(qc_code, {})
    strategy = QC_REF_SPEC.get(qc_code, ("", False, "blank", "", ""))[2]
    prof_limits, kw_to_tier = _profile_limits(profile, qc_code)
    skipped = 0

    records = []
    for uid, keyword in analyte_uids:
        is_key = keyword in KEY_ANALYTES

        if strategy == "blank":
            rec = {"uid": uid, "result": "0", "min": "0",
                   "max": "0", "error": "100"}

        elif strategy in ("cal_dev", "cal_dev_tight"):
            # The profile's own calibration tolerance, then the QC rules store.
            pct = None
            if profile:
                cal = ((profile.get("instrument_verification") or {})
                       .get("calibration") or {})
                pct = cal.get("point_pct_dev_max")
            if pct is None:
                pct = qt.get("pct_deviation_max")
            if pct is None:
                skipped += 1
                continue
            rec = {
                "uid": uid,
                "result": "100",
                "min": str(round(100.0 - pct, 2)),
                "max": str(round(100.0 + pct, 2)),
                "error": str(round(pct, 2)),
            }

        elif strategy in ("recovery", "recovery_dup"):
            lo = hi = None
            # The method profile first: it is what the engine enforces, and it
            # resolves per analyte (key / linked / no-labelled-standard) rather
            # than by a single key-vs-not split.
            if prof_limits:
                tier = (kw_to_tier or {}).get(keyword, 2)
                lims = prof_limits.get(tier) or prof_limits.get(2)
                if lims:
                    lo, hi = lims.get("min"), lims.get("max")
            if lo is None or hi is None:
                lo = qt.get("recovery_min")
                hi = qt.get("recovery_max")
                if is_key:
                    lo = qt.get("recovery_min_key_matrix", lo)
                    hi = qt.get("recovery_max_key_matrix", hi)
            if lo is None or hi is None:
                # No configured limits anywhere. Inventing a window here would
                # draw a control chart against a criterion nobody chose --
                # the substitution defect, one layer out.
                skipped += 1
                continue
            mid = (lo + hi) / 2.0
            err = round((hi - mid) / mid * 100.0, 2) if mid else 50.0
            rec = {
                "uid": uid,
                "result": "100",
                "min": str(round(lo, 2)),
                "max": str(round(hi, 2)),
                "error": str(err),
            }

        elif strategy == "rpd":
            rpd = qt.get("rpd_max")
            if rpd is None and profile:
                tiers = ((profile.get("qc_acceptance") or {})
                         .get(qc_code, {}) or {}).get("tiers") or []
                rpd = tiers[0].get("rpd_max") if tiers else None
            if rpd is None:
                skipped += 1
                continue
            rec = {
                "uid": uid,
                "result": "0",
                "min": "0",
                "max": str(round(rpd, 2)),
                "error": str(round(rpd, 2)),
            }

        else:
            rec = {"uid": uid, "result": "", "min": "", "max": "", "error": ""}

        records.append(rec)
    if skipped:
        logger.warning(
            "%s: %d analyte(s) have no configured acceptance limits, so no "
            "reference range was written for them. Set them in Method "
            "Profiles -> QC Types.", qc_code, skipped)
    return records


class PFASSetupRefsView(BrowserView):
    """
    Manager browser view that creates/refreshes SENAITE ReferenceDefinitions
    for all PFAS QC types and stamps them with PFAS pool metadata fields.

    GET  — display preview of what will be created/updated.
    POST — execute the setup (idempotent; safe to run repeatedly).
    """

    template = ViewPageTemplateFile("templates/setuprefs.pt")

    def _ref_profile(self):
        """Method profile the reference ranges are derived from (see
        setuphandlers._primary_method_profile for why one is chosen)."""
        try:
            from senaite.pfas.setuphandlers import _primary_method_profile
            from bika.lims import api
            return _primary_method_profile(api.get_portal())
        except Exception as exc:                            # noqa: BLE001
            logger.warning("reference ranges falling back to the QC rules "
                           "store: %s", exc)
            return {}

    def __call__(self):
        flatten_form(self.request)
        if self.request.method == "POST":
            if not _is_manager(self.context):
                self.request.response.setStatus(403)
                return "Forbidden"
            if self.request.form.get("action") == "save_ref_method":
                return self._save_ref_method()
            return self._handle_post()
        return self.template()

    # ── Template helpers ──────────────────────────────────────────────────────

    def portal_url(self):
        from bika.lims import api
        return api.get_portal().absolute_url()

    def is_manager(self):
        return _is_manager(self.context)

    # ── Which method supplies the (global) reference ranges ──────────────────

    def reference_method(self):
        from senaite.pfas.setuphandlers import get_reference_method
        from bika.lims import api
        return get_reference_method(api.get_portal())

    def method_options(self):
        from senaite.pfas.method_profile_store import list_method_ids
        from bika.lims import api
        try:
            return sorted(list_method_ids(api.get_portal()) or [])
        except Exception:                                   # noqa: BLE001
            return []

    def _save_ref_method(self):
        from senaite.pfas.setuphandlers import set_reference_method
        from bika.lims import api
        set_reference_method(api.get_portal(),
                             (self.request.form.get("ref_method") or "").strip())
        return self.request.response.redirect(
            "%s/@@pfas-setup-references?saved=1" % api.get_portal().absolute_url())

    def qc_type_specs(self):
        """Return list of dicts for the preview table."""
        rules = self._rules()
        rows = []
        for code, spec in sorted(QC_REF_SPEC.items()):
            title, is_blank, strategy, category, acceptance_schema = spec
            qt = rules.get("qc_types", {}).get(code, {})
            if strategy == "blank":
                spec_desc = "Blank — flag any detection above zero"
            elif strategy in ("cal_dev", "cal_dev_tight"):
                default_pct = 20.0 if strategy == "cal_dev_tight" else 25.0
                pct = qt.get("pct_deviation_max") or default_pct
                spec_desc = "{} +/- {}% deviation from nominal".format(100, pct)
            elif strategy in ("recovery", "recovery_dup"):
                lo = qt.get("recovery_min", 40.0)
                hi = qt.get("recovery_max", 140.0)
                spec_desc = "Recovery {}%–{}%  (key analytes: {}%–{}%)".format(
                    lo, hi,
                    qt.get("recovery_min_key_matrix", lo),
                    qt.get("recovery_max_key_matrix", hi),
                )
            elif strategy == "rpd":
                rpd = qt.get("rpd_max") or 30.0
                spec_desc = "RPD <= {}%".format(rpd)
            else:
                spec_desc = "—"

            rows.append({
                "code":              code,
                "title":             title,
                "is_blank":          is_blank,
                "category":          category,
                "acceptance_schema": acceptance_schema,
                "strategy":          strategy,
                "spec":              spec_desc,
            })
        return rows

    def analyte_count(self):
        return len(self._get_analyte_uids())

    def existing_ref_defs(self):
        """Return titles of ReferenceDefinitions that carry a QC code."""
        try:
            folder = self.context.bika_setup.bika_referencedefinitions
            return [obj.Title() for obj in folder.objectValues()
                    if _ref_def_code(obj)]
        except Exception:
            return []

    def save_message(self):
        return self.request.get("created", "")

    def rules_path(self):
        from senaite.pfas.qc.rules import get_store
        return get_store().path

    # ── Internals ─────────────────────────────────────────────────────────────

    def _rules(self):
        from senaite.pfas.qc.rules import get_rules
        return get_rules()

    def _get_analyte_uids(self):
        """Return list of (uid, keyword) pairs for all PFAS AnalysisServices."""
        try:
            from bika.lims import api
            try:
                catalog = api.get_tool("senaite_catalog_setup")
            except Exception:
                catalog = api.get_tool("bika_setup_catalog")
            brains = catalog(portal_type="AnalysisService")
            results = []
            for brain in brains:
                obj = brain.getObject()
                kw = getattr(obj, "getKeyword", lambda: "")() or ""
                results.append((api.get_uid(obj), kw))
            return results
        except Exception as e:
            logger.error("_get_analyte_uids: %s", e)
            return []

    def _handle_post(self):
        rules = self._rules()
        analyte_uids = self._get_analyte_uids()

        if not analyte_uids:
            self.request.response.setStatus(400)
            return ("No AnalysisServices found — run the GenericSetup profile "
                    "first to create PFAS analysis services.")

        try:
            portal = self.context.portal_url.getPortalObject()
            folder = portal.bika_setup.bika_referencedefinitions
        except Exception as e:
            self.request.response.setStatus(500)
            return "Cannot access ReferenceDefinitions folder: {}".format(e)

        created, updated = [], []

        for code, spec in sorted(QC_REF_SPEC.items()):
            title, is_blank, _strategy, category, acceptance_schema = spec
            try:
                obj, is_new = _get_or_create_ref_def(folder, code, title,
                                                     is_blank=is_blank)
                records = _build_reference_results(
                    code, rules, analyte_uids, profile=self._ref_profile())
                obj.setReferenceResults(records)
                obj.setBlank(is_blank)
                _stamp_pfas_fields(obj, code, category, acceptance_schema)
                try:
                    obj.reindexObject()
                except Exception:
                    pass
                if is_new:
                    created.append(title)
                    logger.info("Created ReferenceDefinition: %s", title)
                else:
                    updated.append(title)
                    logger.info("Updated ReferenceDefinition: %s", title)
            except Exception as e:
                logger.error("Failed for %s: %s", code, e)

        logger.info("pfas-setup-references: created=%d updated=%d analytes=%d",
                    len(created), len(updated), len(analyte_uids))
        url = "{}/@@pfas-setup-references?created={}".format(
            self.context.absolute_url(),
            "{}_created_{}_updated".format(len(created), len(updated)),
        )
        self.request.response.redirect(url)
