# -*- coding: utf-8 -*-
"""
PFAS Method Profile browser views.

@@pfas-method-profiles
    List all configured methods; links to edit each one.

@@pfas-method-profile-edit?method_id=FDA_32PFAS
    Edit a single method profile; POST saves to ZODB and exports
    /data/qc/method_profiles.json for the pipeline worker.

Both views require Manager, LabManager, or Owner role.
Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import logging
import urllib

from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.method_profile_store import (
    DEFAULT_PROFILES,
    get_profile,
    list_method_ids,
    save_profile,
)

logger = logging.getLogger("senaite.pfas.browser.method_profiles")


# Roles that may edit Method Profiles (Q-006: LabManager covers QAO/Lab Director).
_ALLOWED_ROLES = frozenset(("Manager", "LabManager", "Owner"))


def _require_manager(context, request):
    try:
        from AccessControl import getSecurityManager
        user = getSecurityManager().getUser()
        roles = user.getRolesInContext(context)
        return bool(_ALLOWED_ROLES.intersection(roles))
    except Exception:
        return False


def _portal(context):
    return context.portal_url.getPortalObject()


# ── List view ─────────────────────────────────────────────────────────────────

class PFASMethodProfilesView(BrowserView):
    """List all PFAS method profiles."""

    template = ViewPageTemplateFile("templates/method_profiles.pt")

    def __call__(self):
        flatten_form(self.request)
        if not _require_manager(self.context, self.request):
            self.request.response.setStatus(403)
            return "Forbidden: Manager, LabManager, or Owner role required"
        return self.template()

    def portal_url(self):
        return _portal(self.context).absolute_url()

    def methods(self):
        portal = _portal(self.context)
        try:
            from senaite.pfas.method_bridge import get_association, get_core_method
        except Exception:
            get_association = get_core_method = None
        saved_ids = set(list_method_ids(portal))
        all_ids = sorted(set(list(DEFAULT_PROFILES.keys())) | saved_ids)
        result = []
        for mid in all_ids:
            p = get_profile(portal, mid)
            # _seeded=True means the profile was written by seed_default_profiles
            # and has not yet been edited by a user.
            # User-saved profiles don't include _seeded, so it defaults to False.
            is_customised = not p.get("_seeded", False)
            row = {
                "method_id": mid,
                "display_name": p.get("display_name", mid),
                "description": p.get("description", ""),
                "is_customised": is_customised,
                # profile ⇄ core SENAITE Method bridge (method_associations)
                "core_method_title": "",
                "core_method_url": "",
                "linked_services": 0,
                "linked_sampletypes": 0,
            }
            if get_association is not None:
                assoc = get_association(portal, mid)
                if assoc.get("method_uid"):
                    core = get_core_method(portal, mid)
                    row["core_method_title"] = assoc.get("method_title", "")
                    row["core_method_url"] = core.absolute_url() if core is not None else ""
                    row["linked_services"] = len(assoc.get("service_uids", []))
                    row["linked_sampletypes"] = len(assoc.get("sampletype_uids", []))
            result.append(row)
        return result


# ── Edit view ─────────────────────────────────────────────────────────────────

class PFASMethodProfileEditView(BrowserView):
    """Edit a single PFAS method profile."""

    template = ViewPageTemplateFile("templates/method_profile_edit.pt")

    def __call__(self):
        flatten_form(self.request)
        if not _require_manager(self.context, self.request):
            self.request.response.setStatus(403)
            return "Forbidden: Manager, LabManager, or Owner role required"

        if self.request.method == "POST":
            return self._handle_post()
        return self.template()

    # ── Template helpers ──────────────────────────────────────────────────────

    def method_id(self):
        return self.request.form.get("method_id", "").strip()

    def profile(self):
        mid = self.method_id()
        if not mid:
            return {}
        return get_profile(_portal(self.context), mid)

    def saved(self):
        return self.request.form.get("saved", "") == "1"

    def error(self):
        return self.request.form.get("error", "")

    def portal_url(self):
        return _portal(self.context).absolute_url()

    # Convenience accessors for individual profile sections.
    #
    # These read the NESTED instrument_verification structure, which is what
    # the engine enforces. They used to read the retired flat keys, so the
    # editor showed — and saved — values nothing applied: the CCV window said
    # 72-128% here while every run was judged against the nested 70-130%.
    def _iv_section(self, nested, legacy):
        profile = self.profile()
        section = (profile.get("instrument_verification") or {}).get(nested)
        if section:
            return section
        return profile.get(legacy, {})

    def cal(self):
        return self._iv_section("calibration", "calibration")

    def ccv(self):
        return self._iv_section("ccv", "ccv")

    def is_section(self):
        return self._iv_section("is_response", "is")

    def confirmation(self):
        return self._iv_section("confirmation", "confirmation")

    # The QC type whose tiers the Recovery Tiers grid edits. Recovery tiers are
    # an LFSM concept: LFSMD carries RPD as well, Dup carries only RPD, and MB
    # is judged against the reporting limit.
    RECOVERY_TIER_QC_TYPE = "LFSM"

    def recovery_tiers_json(self):
        """The tiers the ENGINE enforces, not the retired flat key.

        This read the retired flat recovery-tiers key, which
        migrate_profile_structure superseded and which is empty in every live
        profile -- so the Recovery Tiers
        tab rendered EMPTY while 80-120 / 65-135 / 40-140 sat in
        `qc_acceptance.LFSM.tiers`, and any tier a manager added there was
        written to a key nothing reads.

        Same shape as the CCV defect, in the one editor where it matters most:
        the recovery window is the pass/fail gate on a certificate.
        """
        qca = self.profile().get("qc_acceptance", {}) or {}
        entry = qca.get(self.RECOVERY_TIER_QC_TYPE, {}) or {}
        return json.dumps(entry.get("tiers", []), indent=2)

    def matrix_factors_json(self):
        return json.dumps(self.profile().get("matrix_factors", []), indent=2)

    def surrogate_map_json(self):
        return json.dumps(self.profile().get("surrogate_map", []), indent=2)

    def per_analyte_json(self):
        from senaite.pfas.method_profile_store import DEFAULT_PROFILES
        per_a = self.profile().get("per_analyte") or []
        if not per_a:
            # Stored profile has explicit [] (old seeded profile); back-fill from defaults.
            per_a = DEFAULT_PROFILES.get(self.method_id(), {}).get("per_analyte", [])
        return json.dumps(per_a, indent=2)

    def eis_overrides_json(self):
        return json.dumps(self.profile().get("eis_overrides", []), indent=2)

    def salt_adjustment_factors_json(self):
        return json.dumps(self.profile().get("salt_adjustment_factors", []), indent=2)

    def salt_adjustment_rows(self):
        """One row per analyte in the method's master set (default factor 1.0),
        merged with any saved factors. Each carries the linked standard/CRM lot
        (traceability, golden rule #6). The factor seldom changes; the CoA lot
        updates with each new standard lot."""
        from senaite.pfas.analyte_reference import NATIVE_ANALYTES
        kw_to_display = {row[0]: row[1] for row in NATIVE_ANALYTES}
        profile = self.profile()
        keywords = profile.get("master_analyte_set", [])
        saved = {}
        for r in (profile.get("salt_adjustment_factors") or []):
            if isinstance(r, dict) and r.get("analyte"):
                saved[r["analyte"]] = r
        rows = []
        for kw in keywords:
            rec = saved.get(kw, {})
            factor = rec.get("factor")
            rows.append({
                "analyte": kw,
                "label": kw_to_display.get(kw, kw),
                "factor": factor if factor is not None else 1.0,
                "lot_uid": rec.get("lot_uid", "") or rec.get("source", ""),
                "lot_number": rec.get("lot_number", ""),
            })
        return rows

    def dup_rpd(self):
        """Sample-duplicate RPD limit, from the structure the engine evaluates.

        The fallback to the legacy flat key is gone, and so is the 20.0 default
        behind it. migrate_profile_structure carries a legacy value into
        qc_acceptance.Dup, and an unmigrated profile now shows an empty field
        rather than a plausible number the engine would not enforce -- with
        UnconfiguredCriterion making the gap loud on the next run instead of
        silently judging duplicates against 20%.
        """
        qca = self.profile().get("qc_acceptance", {}) or {}
        tiers = (qca.get("Dup", {}) or {}).get("tiers", []) or []
        if tiers and tiers[0].get("rpd_max") is not None:
            return tiers[0]["rpd_max"]
        return ""

    def matrix_adjustment_rows(self):
        """One row per SUPPORTED MATRIX (from the Analyte × Matrix map, which
        ties to core SampleTypes via matrix_uid_map), default factor 1.0.
        Legacy free-text/substring matrix_factors are collapsed onto the
        matching supported matrix (D55 — ties matrix factors to core types)."""
        profile = self.profile()
        matrices = profile.get("supported_matrices", []) or []
        uid_map = profile.get("matrix_uid_map", {}) or {}
        saved = profile.get("matrix_factors", []) or []
        rows = []
        for mtx in matrices:
            ml = mtx.lower().strip()
            factor = None
            # exact title match first
            for e in saved:
                if isinstance(e, dict) and (e.get("matrix", "") or "").lower().strip() == ml:
                    factor = e.get("factor")
                    break
            # legacy substring collapse (e.g. "meat"/"deer" -> "Meat / Muscle")
            if factor is None:
                for e in saved:
                    key = (e.get("matrix", "") or "").lower().strip()
                    if key and key in ml:
                        factor = e.get("factor")
                        break
            rows.append({
                "matrix": mtx,
                "sampletype_uid": uid_map.get(mtx, ""),
                "linked": bool(uid_map.get(mtx)),
                "factor": factor if factor is not None else 1.0,
            })
        return rows

    def matrix_settings_rows(self):
        """One row per supported matrix, carrying every setting keyed BY matrix.

        These four were readable by the engine and writable by nobody:
        supported_matrices, tight_matrices, matrix_aliases and unit_map. A lab
        could not add a matrix, could not say which matrices take the tighter
        80-120% tier, could not teach the system that "deer muscle" is
        Meat / Muscle, and could not set a reporting unit -- all four were seed
        constants or, in the case of the aliases, written by nothing at all.

        They are one table rather than four because they are one fact about one
        matrix, and editing them apart is how they drifted.
        """
        profile = self.profile()
        matrices = profile.get("supported_matrices", []) or []
        uid_map = profile.get("matrix_uid_map", {}) or {}
        tight = set((profile.get("tight_matrices") or []))
        aliases = profile.get("matrix_aliases", {}) or {}
        units = profile.get("unit_map", {}) or {}
        holding = profile.get("holding_times", {}) or {}
        rows = []
        for mtx in matrices:
            # Blank, not 0, when unset: 0 days would read as "extract the same
            # day", and the review must refuse to judge rather than fail.
            days = holding.get(mtx)
            rows.append({
                "matrix": mtx,
                "linked": bool(uid_map.get(mtx)),
                "tight": mtx in tight,
                "aliases": ", ".join(aliases.get(mtx) or []),
                "unit": units.get(mtx, ""),
                "holding_days": "" if days in (None, "") else days,
            })
        return rows

    def _matrix_references(self, profile, removed):
        """What still points at a matrix title that is going away.

        Reported as a refusal rather than cleaned up silently: a matrix factor
        or a spike level is lab data, and deciding it is disposable because a
        title changed is not this form's call.
        """
        removed = set(removed)
        found = []

        factors = [e.get("matrix") for e in (profile.get("matrix_factors") or [])
                   if isinstance(e, dict)]
        hit = sorted(set(f for f in factors if f in removed))
        if hit:
            found.append("matrix factors for {0}".format(", ".join(hit)))

        spikes = profile.get("spike_levels") or {}
        hit = sorted(m for m in spikes if m in removed)
        if hit:
            found.append("spike levels for {0}".format(", ".join(hit)))

        inclusion = profile.get("analyte_matrix_inclusion") or {}
        included = set()
        for per_matrix in inclusion.values():
            if isinstance(per_matrix, dict):
                included.update(m for m in per_matrix if m in removed)
        if included:
            found.append("analyte x matrix inclusion for {0}".format(
                ", ".join(sorted(included))))

        return found

    def unit_options(self):
        """Reporting units offered for a matrix. Every unit already in use is
        included, so an existing choice is never silently dropped from the list
        it was chosen from."""
        common = ["ng/kg", "ug/kg", "ng/L", "ng/mL", "ug/L", "mg/kg", "pg/g"]
        used = [u for u in sorted(
            set((self.profile().get("unit_map", {}) or {}).values()))
            if u and u not in common]
        return common + used

    # The 1633A EIS tables are published per MATRIX CLASS, not per matrix
    # title: Sediment and Soil are both "solid". Mirrors
    # pfas_pipeline.method_profiles._1633a_matrix_class, which is what the
    # engine looks the overrides up by.
    EIS_MATRIX_CLASSES = [
        ("solid", "Solid (soil, sediment)"),
        ("biosolid", "Biosolid"),
        ("leachate", "Landfill leachate"),
        ("tissue", "Tissue"),
    ]

    def eis_matrix_rows(self):
        """Per-analyte EIS recovery limits for each 1633A matrix class.

        `eis_matrix_overrides` was read by the engine and written by nobody:
        seeded from the published tables and then frozen. §3 requires EIS
        recovery to be configurable per analyte x matrix, and a lab that
        verifies a limit against its purchased method copy has to be able to
        record what it found.
        """
        profile = self.profile()
        overrides = profile.get("eis_matrix_overrides", {}) or {}
        groups = []
        for key, label in self.EIS_MATRIX_CLASSES:
            entries = overrides.get(key, {}) or {}
            rows = [{"analyte": analyte,
                     "recovery_min": (entries[analyte] or {}).get("recovery_min", ""),
                     "recovery_max": (entries[analyte] or {}).get("recovery_max", "")}
                    for analyte in sorted(entries)]
            groups.append({"key": key, "label": label, "rows": rows,
                           "count": len(rows), "blank_start": len(rows)})
        return groups

    def standard_lot_options(self):
        """Standard / Reference-Material lots from the reagent inventory, for
        the CoA-lot dropdown. Expired lots are flagged so they aren't picked."""
        try:
            from senaite.pfas.browser.reagents import _list_reagents
            portal = _portal(self.context)
            recs = _list_reagents(portal,
                                  category_filter=u"Standard / Reference Material")
        except Exception as exc:
            logger.warning("standard_lot_options: %s", exc)
            return []
        out = []
        for d in recs:
            lot = d.get("lot_number", "") or ""
            name = d.get("name", "") or ""
            expired = d.get("status") == "expired"
            label = u"{0} — lot {1}".format(name, lot) if lot else name
            if expired:
                label += u" (EXPIRED)"
            out.append({
                "uid": d.get("uid", ""), "lot_number": lot,
                "name": name, "label": label, "expired": expired,
            })
        return sorted(out, key=lambda x: x["label"].lower())

    def isomer_summation_json(self):
        return json.dumps(self.profile().get("isomer_summation", []), indent=2)

    def spike_levels_json(self):
        return json.dumps(self.profile().get("spike_levels", {}), indent=2)

    def associated_qc_types_json(self):
        return json.dumps(self.profile().get("associated_qc_types", []))

    def qc_type_toggles(self):
        """Per-method QC-type enable toggles — one row per qc_acceptance key.
        Enabling/disabling here gates the QC engine AND spec_sync (which now
        derives its QC types from these keys, not a hardcoded tuple).

        Display names come from the tagged core Reference Definitions (the
        single UI-editable source), not a hardcoded map."""
        from senaite.pfas.qc_labels import get_qc_label_map, qc_label
        from bika.lims import api
        label_map = get_qc_label_map(api.get_portal())
        qca = self.profile().get("qc_acceptance", {}) or {}
        out = []
        for key in sorted(qca.keys()):
            cfg = qca[key] or {}
            has_recovery = any(
                t.get("recovery_min") is not None or t.get("recovery_max") is not None
                for t in cfg.get("tiers", []))
            out.append({
                "key": key,
                "label": qc_label(None, key, label_map=label_map),
                "enabled": bool(cfg.get("enabled")),
                "has_recovery": has_recovery,
            })
        return out

    # ── QC engine rules (qc_rules.json) — merged into this console (D52) ─────
    # NOTE: qc_rules.json stays a SEPARATE store from method_profiles.json
    # (the pipeline reads both for different jobs, D50). This console just
    # renders + saves the slice of qc_rules that belongs to the selected method.

    def _qc_rules(self):
        try:
            from senaite.pfas.qc.rules import get_rules
            return get_rules()
        except Exception as exc:
            logger.warning("qc rules load failed: %s", exc)
            return {}

    def rule_toggle_rows(self):
        """Per selected-method rule rows: each = enable toggle + its param
        overrides. Merges the old QC-Rules 'Rule Toggles' + 'Method Limits'
        tabs into one (a method's limits ARE the params of its rules)."""
        try:
            from senaite.pfas.qc.rules import RULE_LIBRARY
        except Exception:
            return []
        mid = self.method_id()
        rules = self._qc_rules()
        toggles = (rules.get("method_rule_toggles", {}) or {}).get(mid, {})
        overrides = (rules.get("method_overrides", {}) or {}).get(mid, {})
        glob = rules.get("global", {}) or {}
        rows = []
        for rule in RULE_LIBRARY:
            rkey = rule["key"]
            params = []
            for p in rule.get("params", []):
                pname = p["name"]
                val = overrides.get(pname, glob.get(pname, p.get("default")))
                params.append({
                    "name": pname, "label": p.get("label", pname),
                    "type": p.get("type", "number"), "value": val,
                    "inherited": pname not in overrides,
                })
            rows.append({
                "key": rkey, "label": rule["label"],
                "enabled": bool(toggles.get(rkey, True)),
                "has_params": bool(params), "params": params,
            })
        return rows

    def global_criteria_fields(self):
        """Cross-method engine defaults (the old 'Global Criteria' tab),
        surfaced in Advanced. Editable; a method param override wins over these."""
        try:
            from senaite.pfas.browser.qcrules import GLOBAL_PARAM_META
        except Exception:
            GLOBAL_PARAM_META = {}
        glob = self._qc_rules().get("global", {}) or {}
        out = []
        for k in sorted(glob.keys()):
            meta = GLOBAL_PARAM_META.get(k, {})
            out.append({"key": k, "value": glob[k],
                        "label": meta.get("label", k), "unit": meta.get("unit", "")})
        return out

    def qc_rules_json(self):
        return json.dumps(self._qc_rules(), indent=2, sort_keys=True)

    def qc_rules_path(self):
        try:
            from senaite.pfas.qc.rules import get_store
            return get_store().path
        except Exception:
            return "/data/qc/qc_rules.json"

    def extraction_stages_json(self):
        stages = self.profile().get("extraction_stages", [])
        return json.dumps(sorted(stages, key=lambda s: s.get("order", 0)), indent=2)

    # ── Analyte × Matrix Inclusion Matrix ────────────────────────────────────

    def analyte_matrix_grid_data(self):
        """JSON for the JS grid builder: ordered analytes, matrices, display labels."""
        from senaite.pfas.analyte_reference import NATIVE_ANALYTES
        kw_to_display = {row[0]: row[1] for row in NATIVE_ANALYTES}
        profile = self.profile()
        keywords = profile.get("master_analyte_set", [])
        return json.dumps({
            "analytes":       keywords,
            "analyte_labels": {kw: kw_to_display.get(kw, kw) for kw in keywords},
            "matrices":       profile.get("supported_matrices", []),
        })

    def analyte_matrix_json(self):
        """JSON of the current analyte × matrix inclusion dict."""
        inclusion = self.profile().get("analyte_matrix_inclusion", {})
        return json.dumps(inclusion)

    def analyte_matrix_needs_verification(self):
        return self.method_id() in ("EPA_537_1", "EPA_1633A")

    def show_eis_overrides(self):
        return self.method_id() == "EPA_1633A"

    def surrogate_chain_rows(self):
        """Which injection IS each labelled SURROGATE is quantified against.

        The second half of the quantification chain: native -> surrogate
        (the drag-and-drop map) -> injection IS. It is what distinguishes a
        surrogate, which is diluted along with the sample, from the injection
        standard, which is added at reconstitution and must not be scaled --
        the distinction that made a dilution's surrogates look like failures.

        Rows come from the surrogate map, so the two halves cannot disagree
        about which compounds are surrogates.
        """
        profile = self.profile()
        chain = profile.get("surrogate_is_chain", {}) or {}
        surrogates = []
        for row in (profile.get("surrogate_map") or []):
            name = (row.get("surrogate_is") or "").strip()
            if name and name not in surrogates:
                surrogates.append(name)
        for name in sorted(chain):
            if name not in surrogates:
                surrogates.append(name)
        return [{"surrogate": name, "injection_is": chain.get(name, "")}
                for name in surrogates]

    def injection_is_options(self):
        """Candidate injection standards: the labelled compounds this method
        knows about, so the choice cannot name something that is not in the run."""
        options = []
        for row in (self.profile().get("surrogate_map") or []):
            name = (row.get("surrogate_is") or "").strip()
            if name and name not in options:
                options.append(name)
        for name in (self.profile().get("surrogate_is_chain") or {}).values():
            if name and name not in options:
                options.append(name)
        current = (self.profile().get("surrogate_is") or "").strip()
        if current and current not in options:
            options.append(current)
        return sorted(options)

    # ── Surrogate IS lane data ────────────────────────────────────────────────

    def _pfas_service_index(self):
        """{keyword: {role, quant_surrogate, name, uid, url}} for every core
        AnalysisService that carries a pfas_role. This is THE source for the
        analyte / surrogate / IS lists and the native→surrogate link (D58) —
        pulled from the services that actually report, not code tables."""
        out = {}
        try:
            from bika.lims import api
            setup_cat = api.get_tool("senaite_catalog_setup")
            for b in setup_cat(portal_type="AnalysisService"):
                o = b.getObject()
                rf = o.getField("pfas_role")
                role = (rf.get(o) if rf is not None else "") or ""
                if not role:
                    continue
                qf = o.getField("pfas_quant_surrogate")
                out[o.getKeyword()] = {
                    "role": role,
                    "quant_surrogate": (qf.get(o) if qf is not None else "") or "",
                    "name": o.Title() or o.getKeyword(),
                    "uid": o.UID(),
                    "url": o.absolute_url(),
                }
        except Exception as exc:
            logger.warning("_pfas_service_index: %s", exc)
        return out

    # back-compat alias
    def _core_service_roles(self):
        idx = self._pfas_service_index()
        return {k: {"role": v["role"], "uid": v["uid"], "url": v["url"]}
                for k, v in idx.items()}

    def surrogate_is_data(self):
        """JSON payload for the surrogate map table. Surrogates are DERIVED
        per method (D57): each native's default labeled surrogate comes from the
        single-source NATIVE_ANALYTES map; the method's surrogate SET is the
        union of those (not the global pool). Overrides in surrogate_map win.
        Each surrogate carries its core-service role marking (pfas_role)."""
        from senaite.pfas.analyte_reference import NATIVE_ANALYTES
        kw_to_display = {row[0]: row[1] for row in NATIVE_ANALYTES}

        # SOURCE OF TRUTH: core AnalysisServices (pfas_role + quant link), D58.
        idx = self._pfas_service_index()
        surrogate_svcs = {k: v for k, v in idx.items() if v["role"] == "surrogate"}
        injection_svcs = {k: v for k, v in idx.items() if v["role"] == "injection_is"}

        profile = self.profile()
        keywords = profile.get("master_analyte_set", [])
        # profile override (rare) still wins over the service link
        override = {}
        for row in profile.get("surrogate_map", []):
            if row.get("analyte"):
                override[row["analyte"]] = row.get("surrogate_is", "")

        map_dict, defaults, used = {}, {}, set()
        for kw in keywords:
            # DEFAULT = the analyte service's own pfas_quant_surrogate link
            svc_link = idx.get(kw, {}).get("quant_surrogate", "")
            defaults[kw] = svc_link
            eff = override.get(kw) or svc_link
            map_dict[kw] = eff
            if eff:
                used.add(eff)

        # the method's surrogate SET (derived from services actually used)
        method_surrogates = []
        for s in sorted(used):
            sv = surrogate_svcs.get(s) or idx.get(s, {})
            method_surrogates.append({
                "keyword": s,
                "name": sv.get("name", s),
                "in_core": bool(sv) and idx.get(s, {}).get("role") == "surrogate",
                "role": idx.get(s, {}).get("role", ""),
                "url": sv.get("url", ""),
            })

        # injection IS — from the core injection_is service(s)
        inj = [{"keyword": k, "name": v["name"]} for k, v in sorted(injection_svcs.items())]
        inj_default = profile.get("surrogate_is", "") or (inj[0]["keyword"] if inj else "")

        return json.dumps({
            "analytes":       keywords,
            "analyte_labels": {kw: kw_to_display.get(kw, kw) for kw in keywords},
            "surrogates":     method_surrogates,
            "map":            map_dict,
            "defaults":       defaults,
            "injection_is":   inj,
            "injection_is_default": inj_default,
            "core_roles":     {k: v["role"] for k, v in idx.items()},
        })

    def display_name(self):
        return self.profile().get("display_name", self.method_id())

    def description(self):
        return self.profile().get("description", "")

    def surrogate_is(self):
        return self.profile().get("surrogate_is", "")

    # ── POST handler ──────────────────────────────────────────────────────────

    def _handle_post(self):
        mid = self.request.form.get("method_id", "").strip()
        if not mid:
            return self._redirect_error("", "method_id is required")

        portal = _portal(self.context)
        profile = get_profile(portal, mid)   # start from existing to preserve unknown keys

        try:
            profile = self._apply_form(profile)
        except ValueError as exc:
            return self._redirect_error(mid, "Validation error: " + str(exc))
        except Exception as exc:
            logger.exception("Error saving method profile %s", mid)
            return self._redirect_error(mid, "Save failed: " + str(exc))

        save_profile(portal, mid, profile)

        # Also persist the QC-engine slice for this method (separate store).
        try:
            self._apply_qc_rules(mid)
        except Exception:
            logger.exception("QC rules save failed for %s", mid)

        # D58: the native→surrogate link lives ON the core analyte services.
        # Write the surrogate-map selections back to pfas_quant_surrogate, then
        # rebuild the profile's surrogate_map FROM the services (the authoritative
        # source) so the pipeline export stays complete + canonical.
        try:
            self._sync_surrogate_links(profile)
            self._rebuild_surrogate_map(profile)
            save_profile(portal, mid, profile)
        except Exception:
            logger.exception("surrogate link sync failed for %s", mid)

        return self._redirect_saved(mid)

    def _rebuild_surrogate_map(self, profile):
        """profile.surrogate_map (the pipeline export) = the pfas_quant_surrogate
        of every master-set analyte service. Services are the source (D58)."""
        idx = self._pfas_service_index()
        rows = []
        for kw in profile.get("master_analyte_set", []):
            sur = idx.get(kw, {}).get("quant_surrogate", "")
            if sur:
                rows.append({"analyte": kw, "surrogate_is": sur})
        profile["surrogate_map"] = rows

    def _sync_surrogate_links(self, profile):
        """Persist each native's chosen surrogate onto its core AnalysisService's
        pfas_quant_surrogate field (the authoritative link, D58)."""
        selections = {}
        for row in (profile.get("surrogate_map") or []):
            a = row.get("analyte")
            if a:
                selections[a] = row.get("surrogate_is", "") or ""
        if not selections:
            return
        from bika.lims import api
        setup_cat = api.get_tool("senaite_catalog_setup")
        by_kw = {}
        for b in setup_cat(portal_type="AnalysisService"):
            svc = b.getObject()
            by_kw[svc.getKeyword()] = svc
        changed = 0
        for kw, sur in selections.items():
            svc = by_kw.get(kw)
            if svc is None:
                continue
            fld = svc.getField("pfas_quant_surrogate")
            if fld is None:
                continue
            if (fld.get(svc) or "") != sur:
                fld.set(svc, sur)
                changed += 1
        if changed:
            logger.info("synced %d surrogate links to core services", changed)

    def _apply_qc_rules(self, mid):
        """Write this method's rule toggles + param overrides (and any global
        edits) back to qc_rules.json — only if the merged console submitted
        them (guarded by hidden markers so other saves don't wipe rules)."""
        f = self.request.form
        if not f.get("qc_rules_present"):
            return
        try:
            from senaite.pfas.qc.rules import get_store, get_rules, RULE_LIBRARY
        except Exception:
            return
        rules = get_rules()

        # toggles: checkbox present = on (marker guarantees a full submit)
        toggles = rules.setdefault("method_rule_toggles", {}).setdefault(mid, {})
        overrides = rules.setdefault("method_overrides", {}).setdefault(mid, {})
        for rule in RULE_LIBRARY:
            rkey = rule["key"]
            toggles[rkey] = bool(f.get("ruletoggle." + rkey))
            for p in rule.get("params", []):
                pname = p["name"]
                raw = (f.get("rulelimit." + pname, "") or "").strip()
                if raw == "":
                    overrides.pop(pname, None)      # revert to inherited
                    continue
                try:
                    overrides[pname] = (int(raw) if p.get("type") == "integer"
                                        else float(raw))
                except ValueError:
                    overrides[pname] = raw

        # global defaults (Advanced tab) — optional
        glob = rules.setdefault("global", {})
        for key in list(glob.keys()):
            raw = (f.get("qcglobal." + key, "") or "").strip()
            if raw != "":
                try:
                    glob[key] = float(raw)
                except ValueError:
                    glob[key] = raw

        try:
            user_id = self.request.get("AUTHENTICATED_USER", "")
            user_id = getattr(user_id, "getId", lambda: str(user_id))()
        except Exception:
            user_id = "unknown"
        get_store().save(rules, updated_by=user_id or "unknown")

    def _apply_form(self, profile):
        f = self.request.form
        # Clear the seed flag — a user-saved profile is no longer factory-default.
        profile.pop("_seeded", None)

        def _float(key, default=None):
            v = f.get(key, "").strip()
            if not v:
                return default
            return float(v)

        def _int(key, default=None):
            v = f.get(key, "").strip()
            if not v:
                return default
            return int(v)

        def _bool(key):
            return f.get(key, "") in ("on", "true", "1", "yes")

        def _json_field(key, default=None):
            raw = f.get(key, "").strip()
            if not raw:
                return default if default is not None else []
            return json.loads(raw)

        profile["display_name"] = f.get("display_name",
                                         profile.get("display_name", "")).strip()
        profile["description"]  = f.get("description",
                                         profile.get("description", "")).strip()
        profile["surrogate_is"] = f.get("surrogate_is",
                                         profile.get("surrogate_is", "")).strip()

        # Instrument verification — calibration, CCV, IS response and
        # chromatographic confirmation. Every value below is assigned
        # UNCONDITIONALLY: `_float` returns None for an absent field and that
        # None is stored, so a POST that omits these inputs does not "leave
        # them alone", it NULLS them.
        #
        # Guarded by a marker field for the same reason as matrix_settings and
        # the recovery tiers below. This was found by doing it: a partial POST
        # carrying only the Matrices & Units pane wiped point_pct_dev_max,
        # ion_ratio_tol_pct, rrt_tol_pct, sn_quan_min, sn_confirm_min,
        # require_confirm_ion_check and the whole IS-response window off the
        # live FDA profile. The full form always submits every pane, so normal
        # use never hit it -- which is exactly why it survived.
        if f.get("instrument_verification_present"):
            # Calibration
            cal = profile.setdefault(
                "instrument_verification", {}).setdefault("calibration", {})
            r2 = _float("cal_r2_min")
            if r2 is not None:
                cal["r2_min"] = r2
            cal["force_origin"]          = _bool("cal_force_origin")
            cal["point_pct_dev_max"]     = _float("cal_point_pct_dev_max")
            cal["low_point_pct_dev_max"] = _float("cal_low_point_pct_dev_max")

            # Every section below is written into instrument_verification, which
            # is the structure the engine reads. Writing the flat keys meant an
            # edit here never reached a QC decision.
            iv = profile.setdefault("instrument_verification", {})

            # CCV
            ccv = iv.setdefault("ccv", {})
            freq = _int("ccv_frequency")
            if freq is not None:
                ccv["frequency"] = freq
            ccv["recovery_min"]  = _float("ccv_recovery_min", ccv.get("recovery_min"))
            ccv["recovery_max"]  = _float("ccv_recovery_max", ccv.get("recovery_max"))
            ccv["low_level_min"] = _float("ccv_low_level_min")
            ccv["low_level_max"] = _float("ccv_low_level_max")

            # IS / surrogate response
            is_ = iv.setdefault("is_response", {})
            is_["vs_ical_avg_min"] = _float("is_vs_ical_avg_min")
            is_["vs_ical_avg_max"] = _float("is_vs_ical_avg_max")
            is_["vs_last_ccv_min"] = _float("is_vs_last_ccv_min")
            is_["vs_last_ccv_max"] = _float("is_vs_last_ccv_max")
            is_["notes"]           = f.get("is_notes", "").strip()

            # Chromatographic confirmation
            conf = iv.setdefault("confirmation", {})
            conf["rrt_tol_pct"]              = _float("conf_rrt_tol_pct")
            conf["rt_tol_abs_min"]           = _float("conf_rt_tol_abs_min")
            conf["ion_ratio_tol_pct"]        = _float("conf_ion_ratio_tol_pct")
            conf["sn_quan_min"]              = _float("conf_sn_quan_min")
            conf["sn_confirm_min"]           = _float("conf_sn_confirm_min")
            conf["require_confirm_ion_check"] = _bool("conf_require_confirm_ion_check")
            # How a single-transition positive is confirmed. FDA §10.2(4) cites
            # LC-HRMS; it is not the only orthogonal route, so the lab names its
            # own and the review prompt quotes it. Blank falls back to the cited
            # default rather than producing a prompt naming no technique.
            conf["confirm_technique"] = (
                f.get("conf_confirm_technique", "").strip() or "LC-HRMS")

        # Recovery tiers are written back to the structure the engine reads.
        # Guarded by the field's presence so a POST from another pane cannot
        # blank the tiers -- which, with refuse-to-judge, would stop every run.
        if "recovery_tiers_json" in f:
            tiers = _json_field("recovery_tiers_json", None)
            if isinstance(tiers, list) and tiers:
                qca = profile.setdefault("qc_acceptance", {})
                entry = qca.setdefault(self.RECOVERY_TIER_QC_TYPE, {})
                entry.setdefault("enabled", True)
                entry["tiers"] = tiers

        # Sample Duplicate (Dup) RPD. D56 fixed a disconnection here by writing
        # BOTH the flat `duplicate` key and qc_acceptance.Dup. Only the latter
        # is read by the engine, so the mirror was two places holding one number
        # and free to diverge — the split-key shape four defects came out of.
        # The value is migrated into the enforced structure and the mirror
        # dropped; dup_rpd() still READS the legacy key so an unmigrated profile
        # keeps its value until its first save.
        rpd = _float("dup_rpd_max")
        if rpd is not None:
            profile.pop("duplicate", None)
            qca = profile.setdefault("qc_acceptance", {})
            dup_qc = qca.setdefault("Dup", {"enabled": True})
            tiers = dup_qc.setdefault("tiers", [{}])
            if not tiers:
                tiers.append({})
            tiers[0]["rpd_max"] = rpd
            # ensure the tier is a valid catch-all so the engine resolves it
            tiers[0].setdefault("name", "default")
            tiers[0].setdefault("analyte_group", "all")
            tiers[0].setdefault("matrix_scope", "all")

        # Complex JSON sections (textareas)
        # Matrix adjustment is now per-supported-matrix named fields
        # (matrix_factor.<title>), each tied to a core SampleType via
        # matrix_uid_map (D55). Only non-default (!=1.0) rows persist.
        if f.get("matrix_present"):
            uid_map = profile.get("matrix_uid_map", {}) or {}
            mf = []
            for mtx in profile.get("supported_matrices", []):
                raw = (f.get("matrix_factor.%s" % mtx, "") or "").strip()
                try:
                    factor = float(raw) if raw != "" else 1.0
                except ValueError:
                    factor = 1.0
                if factor == 1.0:
                    continue
                mf.append({"matrix": mtx, "factor": factor,
                           "sampletype_uid": uid_map.get(mtx, "")})
            profile["matrix_factors"] = mf
        else:
            profile["matrix_factors"] = _json_field(
                "matrix_factors_json", profile.get("matrix_factors", []))
        profile["surrogate_map"]  = _json_field(
            "surrogate_map_json",  profile.get("surrogate_map", []))
        profile["per_analyte"]    = _json_field(
            "per_analyte_json",    profile.get("per_analyte", []))

        # Matrices & Units — the four settings keyed by matrix, saved together
        # because they are one fact about one matrix. Guarded by the marker
        # field so a POST from another pane, which omits these inputs, cannot
        # wipe the matrix list (an unchecked checkbox submits nothing).
        if f.get("matrix_settings_present"):
            names, tight, aliases, units, holding = [], [], {}, {}, {}
            index = 0
            while True:
                key = "mtx_name.%d" % index
                if key not in f:
                    break
                name = (f.get(key, "") or "").strip()
                index += 1
                if not name:
                    continue  # cleared row = matrix removed
                names.append(name)
                if f.get("mtx_tight.%d" % (index - 1)):
                    tight.append(name)
                raw = (f.get("mtx_aliases.%d" % (index - 1), "") or "").strip()
                parts = [a.strip() for a in raw.split(",") if a.strip()]
                if parts:
                    aliases[name] = parts
                unit = (f.get("mtx_unit.%d" % (index - 1), "") or "").strip()
                if unit:
                    units[name] = unit
                # Holding time, days from collection to extraction. Cleared =
                # None, kept as an explicit key so the matrix still appears in
                # the table as deliberately unset rather than absent. A
                # non-positive or unparseable entry is stored as None: the
                # review must refuse to judge, never judge on a bad number.
                raw_days = (f.get("mtx_holding.%d" % (index - 1), "") or "").strip()
                days = None
                if raw_days:
                    try:
                        days = float(raw_days)
                        days = int(days) if days == int(days) else days
                        if days <= 0:
                            days = None
                    except (TypeError, ValueError):
                        days = None
                holding[name] = days
            if names:
                # §3 rule 4: surface what a rename or delete would orphan
                # rather than dropping it. matrix_factors, spike_levels and
                # the analyte x matrix inclusion map are all keyed by matrix
                # TITLE, so renaming "Meat / Muscle" silently strands them --
                # including the matrix factor that multiplies every native
                # concentration on the certificate.
                removed = [m for m in (profile.get("supported_matrices") or [])
                           if m not in names]
                if removed:
                    orphans = self._matrix_references(profile, removed)
                    if orphans:
                        raise ValueError(
                            "Removing or renaming {0} would orphan {1}. Move "
                            "or clear that data first, or restore the matrix "
                            "name.".format(", ".join(sorted(removed)),
                                           "; ".join(orphans)))
                uid_map = profile.get("matrix_uid_map", {}) or {}
                profile["matrix_uid_map"] = {
                    k: v for k, v in uid_map.items() if k in names}
                profile["supported_matrices"] = names
                profile["tight_matrices"] = tight
                profile["matrix_aliases"] = aliases
                profile["unit_map"] = units
                profile["holding_times"] = holding

        # EIS limits per analyte x matrix class. Named fields rather than a
        # JSON blob, so the value a lab verified against its method copy is
        # edited as a number in a cell.
        if f.get("eis_matrix_present"):
            out = {}
            for key, _label in self.EIS_MATRIX_CLASSES:
                entries = {}
                index = 0
                while True:
                    name_key = "eismtx.%s.%d.analyte" % (key, index)
                    if name_key not in f:
                        break
                    analyte = (f.get(name_key, "") or "").strip()
                    lo = (f.get("eismtx.%s.%d.min" % (key, index), "") or "").strip()
                    hi = (f.get("eismtx.%s.%d.max" % (key, index), "") or "").strip()
                    index += 1
                    if not analyte:
                        continue  # cleared name = row removed
                    entry = {}
                    for field, raw in (("recovery_min", lo), ("recovery_max", hi)):
                        try:
                            entry[field] = float(raw)
                        except (TypeError, ValueError):
                            continue
                    if entry:
                        entries[analyte] = entry
                if entries:
                    out[key] = entries
            profile["eis_matrix_overrides"] = out

        # Surrogate -> injection IS. Saved from named per-surrogate fields so
        # the chain is edited as a choice per row, not as JSON.
        if f.get("surrogate_chain_present"):
            chain = {}
            for row in self.surrogate_chain_rows():
                name = row["surrogate"]
                chosen = (f.get("surchain.%s" % name, "") or "").strip()
                if chosen:
                    chain[name] = chosen
            profile["surrogate_is_chain"] = chain

        raw_eis = f.get("eis_overrides_json", "").strip()
        if raw_eis:
            profile["eis_overrides"] = json.loads(raw_eis)

        # Salt adjustment is now per-analyte named fields (salt_factor.<kw> +
        # salt_lot.<kw>), one row per master-set analyte (default factor 1.0),
        # with the CoA lot referencing an inventory standard lot (traceability).
        # Falls back to the legacy JSON field if the named fields are absent.
        if f.get("salt_present"):
            lot_labels = {o["uid"]: o["lot_number"]
                          for o in self.standard_lot_options()}
            salt_rows = []
            for kw in profile.get("master_analyte_set", []):
                raw = (f.get("salt_factor.%s" % kw, "") or "").strip()
                lot_uid = (f.get("salt_lot.%s" % kw, "") or "").strip()
                try:
                    factor = float(raw) if raw != "" else 1.0
                except ValueError:
                    factor = 1.0
                # store only meaningful rows (non-default factor OR a linked lot)
                if factor == 1.0 and not lot_uid:
                    continue
                salt_rows.append({
                    "analyte": kw, "factor": factor,
                    "lot_uid": lot_uid,
                    "lot_number": lot_labels.get(lot_uid, ""),
                })
            profile["salt_adjustment_factors"] = salt_rows
        else:
            profile["salt_adjustment_factors"] = _json_field(
                "salt_adjustment_factors_json",
                profile.get("salt_adjustment_factors", []))

        profile["isomer_summation"] = _json_field(
            "isomer_summation_json",
            profile.get("isomer_summation", []))

        raw_sl = f.get("spike_levels_json", "").strip()
        if raw_sl:
            profile["spike_levels"] = json.loads(raw_sl)

        profile["extraction_stages"] = _json_field(
            "extraction_stages_json",
            profile.get("extraction_stages", []))

        # Analyte × matrix inclusion grid (serialised by JS before submit)
        raw_ami = f.get("analyte_matrix_inclusion_json", "").strip()
        if raw_ami:
            profile["analyte_matrix_inclusion"] = json.loads(raw_ami)

        # QC-type enable toggles (checkbox per qc_acceptance key). Only applied
        # when the marker field is present, so POSTs from other forms that omit
        # the pane don't mass-disable QC types (unchecked boxes don't submit).
        if f.get("qc_toggles_present"):
            qca = profile.get("qc_acceptance", {}) or {}
            for key in qca.keys():
                qca[key]["enabled"] = bool(f.get("qc_enabled_%s" % key))
            profile["qc_acceptance"] = qca

        # Disabled QC types carry NO spike levels: prune their entries from
        # every matrix (e.g. LFB toggled off -> LFB spike rows removed).
        qca = profile.get("qc_acceptance", {}) or {}
        disabled = set(k for k, v in qca.items() if not (v or {}).get("enabled"))
        if disabled:
            sl = profile.get("spike_levels") or {}
            removed = 0
            for matrix, per_qc in list(sl.items()):
                if not isinstance(per_qc, dict):
                    continue
                for qc in list(per_qc.keys()):
                    if qc in disabled:
                        del per_qc[qc]
                        removed += 1
            if removed:
                profile["spike_levels"] = sl
                logger.info("pruned %d spike-level blocks for disabled QC "
                            "types: %s", removed, sorted(disabled))

        return profile

    def _redirect_saved(self, mid):
        url = "{}/@@pfas-method-profile-edit?method_id={}&saved=1".format(
            self.context.absolute_url(), mid)
        self.request.response.redirect(url)
        return ""

    def _redirect_error(self, mid, msg):
        url = "{}/@@pfas-method-profile-edit?method_id={}&error={}".format(
            self.context.absolute_url(), mid,
            urllib.quote(msg.encode("utf-8")))
        self.request.response.redirect(url)
        return ""
