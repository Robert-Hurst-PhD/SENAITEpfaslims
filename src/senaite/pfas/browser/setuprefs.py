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
QC_REF_SPEC = {
    # ── Blank QC types ──────────────────────────────────────────────────────
    "MB":    ("PFAS Method Blank",
              True,  "blank",
              "blank", "blank_threshold"),
    "LRB":   ("PFAS Lab Reagent Blank",
              True,  "blank",
              "blank", "blank_threshold"),
    "MxB":   ("PFAS Matrix Blank",
              True,  "blank",
              "blank", "blank_threshold"),

    # ── Calibration / instrument verification ────────────────────────────────
    "CAL":   ("PFAS Calibration Standard",
              False, "cal_dev",
              "instrument", "instrument_cal"),
    "ICV":   ("PFAS Initial Calibration Verification",
              False, "cal_dev_tight",
              "instrument", "instrument_cal"),
    "CCV":   ("PFAS Continuing Calibration Verification",
              False, "cal_dev_tight",
              "instrument", "instrument_ccv"),

    # ── Extraction / matrix QC types ────────────────────────────────────────
    "LFB":   ("PFAS Laboratory Fortified Blank",
              False, "recovery",
              "extraction", "recovery_tiered"),
    "LCS":   ("PFAS Laboratory Control Sample",
              False, "recovery",
              "extraction", "recovery_tiered"),
    "LFSM":  ("PFAS Lab Fortified Sample Matrix",
              False, "recovery",
              "extraction", "recovery_tiered"),
    "LFSMD": ("PFAS LFSM Duplicate",
              False, "recovery_dup",
              "extraction", "tiered_recovery_rpd"),
    "Dup":   ("PFAS Sample Duplicate",
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


def _get_or_create_ref_def(folder, title, is_blank=False):
    """
    Idempotently get or create a ReferenceDefinition by title.
    Returns (obj, created_bool).
    """
    from bika.lims import api
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


def _build_reference_results(qc_code, rules, analyte_uids):
    """
    Build the list of ReferenceResults dicts for one QC type.

    Returns a list of {"uid": <uid>, "result": str, "min": str,
                        "max": str, "error": str} dicts.
    """
    from senaite.pfas.analytes import KEY_ANALYTES
    qt = rules.get("qc_types", {}).get(qc_code, {})
    strategy = QC_REF_SPEC.get(qc_code, ("", False, "blank", "", ""))[2]

    records = []
    for uid, keyword in analyte_uids:
        is_key = keyword in KEY_ANALYTES

        if strategy == "blank":
            rec = {"uid": uid, "result": "0", "min": "0",
                   "max": "0", "error": "100"}

        elif strategy in ("cal_dev", "cal_dev_tight"):
            default_pct = 20.0 if strategy == "cal_dev_tight" else 25.0
            pct = qt.get("pct_deviation_max") or default_pct
            rec = {
                "uid": uid,
                "result": "100",
                "min": str(round(100.0 - pct, 2)),
                "max": str(round(100.0 + pct, 2)),
                "error": str(round(pct, 2)),
            }

        elif strategy in ("recovery", "recovery_dup"):
            lo = qt.get("recovery_min", 40.0)
            hi = qt.get("recovery_max", 140.0)
            if is_key:
                lo = qt.get("recovery_min_key_matrix", lo)
                hi = qt.get("recovery_max_key_matrix", hi)
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
            rpd = qt.get("rpd_max") or 30.0
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
    return records


class PFASSetupRefsView(BrowserView):
    """
    Manager browser view that creates/refreshes SENAITE ReferenceDefinitions
    for all PFAS QC types and stamps them with PFAS pool metadata fields.

    GET  — display preview of what will be created/updated.
    POST — execute the setup (idempotent; safe to run repeatedly).
    """

    template = ViewPageTemplateFile("templates/setuprefs.pt")

    def __call__(self):
        flatten_form(self.request)
        if self.request.method == "POST":
            if not _is_manager(self.context):
                self.request.response.setStatus(403)
                return "Forbidden"
            return self._handle_post()
        return self.template()

    # ── Template helpers ──────────────────────────────────────────────────────

    def is_manager(self):
        return _is_manager(self.context)

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
        """Return list of existing PFAS ReferenceDefinition titles."""
        try:
            folder = self.context.bika_setup.bika_referencedefinitions
            return [obj.Title() for obj in folder.objectValues()
                    if "PFAS" in (obj.Title() or "")]
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
                obj, is_new = _get_or_create_ref_def(folder, title,
                                                     is_blank=is_blank)
                records = _build_reference_results(code, rules, analyte_uids)
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
