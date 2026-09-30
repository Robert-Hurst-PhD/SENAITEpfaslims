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


# Roles that may edit Method Profiles are perms.ALLOWED_ROLES (Q-006:
# LabManager covers QAO/Lab Director).


def _require_manager(context, request):
    # One gate, resolved at the portal (GAPS §46.6). This module kept a private
    # copy that resolved at the context, so a bench user's local Owner role on
    # anything they had created passed it.
    from senaite.pfas.browser.perms import require_manager
    return require_manager(context, request)


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

    def _checked_surrogate_map(self, profile, rows):
        """The submitted map, refused rather than stored when it names
        something this method cannot quantify with. Each method owns its map
        (DECISIONS 2026-09-30); there is no separate per-method set of labelled
        compounds in core, so the checks are: the native is in this method's
        panel, and the surrogate is a service marked pfas_role=surrogate. A row
        with no surrogate is "none chosen" and is not stored."""
        idx = self._pfas_service_index()
        surrogates = set(k for k, v in idx.items() if v["role"] == "surrogate")
        if not surrogates:
            raise ValueError("could not read the surrogate services to check "
                             "the surrogate map; nothing was saved")
        panel = set(profile.get("master_analyte_set") or [])
        out, seen = [], set()
        for row in rows or []:
            analyte = (row.get("analyte") or "").strip()
            sur = (row.get("surrogate_is") or "").strip()
            if not analyte or not sur:
                continue
            if panel and analyte not in panel:
                raise ValueError("surrogate map: %s is not in this method's analyte "
                                 "panel" % analyte)
            if sur not in surrogates:
                raise ValueError("surrogate map: %s -> %s, which is not a surrogate "
                                 "service (pfas_role=surrogate)" % (analyte, sur))
            if analyte in seen:
                raise ValueError("surrogate map: %s is listed twice" % analyte)
            seen.add(analyte)
            out.append({"analyte": analyte, "surrogate_is": sur})
        return out

    def surrogate_is_data(self):
        """JSON payload for the surrogate map table.

        The method's own surrogate_map is the link (DECISIONS 2026-09-30). A
        native with no row yet shows its analysis service's pfas_quant_surrogate
        as a SUGGESTION -- shown, never pre-selected, so it is only saved when
        someone picks it. The dropdown offers every surrogate service, this
        method's own first."""
        from senaite.pfas.analyte_reference import NATIVE_ANALYTES
        kw_to_display = {row[0]: row[1] for row in NATIVE_ANALYTES}

        idx = self._pfas_service_index()
        surrogate_svcs = {k: v for k, v in idx.items() if v["role"] == "surrogate"}
        injection_svcs = {k: v for k, v in idx.items() if v["role"] == "injection_is"}

        profile = self.profile()
        keywords = profile.get("master_analyte_set", [])
        map_dict = {}
        for row in profile.get("surrogate_map", []):
            if row.get("analyte") and row.get("surrogate_is"):
                map_dict[row["analyte"]] = row["surrogate_is"]
        suggested = {}
        for kw in keywords:
            if kw not in map_dict:
                link = idx.get(kw, {}).get("quant_surrogate", "")
                if link:
                    suggested[kw] = link

        own = set(map_dict.values())

        def _entry(s):
            sv = idx.get(s, {})
            return {"keyword": s, "name": sv.get("name", s),
                    "in_core": sv.get("role") == "surrogate",
                    "role": sv.get("role", ""), "url": sv.get("url", ""),
                    "own": s in own}

        method_surrogates = ([_entry(s) for s in sorted(own)] +
                             [_entry(s) for s in sorted(surrogate_svcs) if s not in own])

        inj = [{"keyword": k, "name": v["name"]} for k, v in sorted(injection_svcs.items())]
        inj_default = profile.get("surrogate_is", "") or (inj[0]["keyword"] if inj else "")

        return json.dumps({
            "analytes":       keywords,
            "analyte_labels": {kw: kw_to_display.get(kw, kw) for kw in keywords},
            "surrogates":     method_surrogates,
            "map":            map_dict,
            "suggested":      suggested,
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

    @staticmethod
    def _stamp_value(portal, mid):
        """What this editor saves for one method: the stored profile AND the
        method's slice of qc_rules.json (the Rule Toggles tab saves there from
        the same form), so a colleague's toggle change also makes a save stale."""
        from senaite.pfas.method_profile_store import raw_profile
        try:
            from senaite.pfas.qc.rules import get_rules
            rules = get_rules() or {}
        except Exception:
            rules = {}
        from senaite.pfas.config_history import IGNORED_KEYS
        profile = dict((k, v) for k, v in raw_profile(portal, mid).items()
                       if k not in IGNORED_KEYS and k not in ("updated_at", "updated_by", "_seeded"))
        return {"profile": profile,
                "qc_rules": {"toggles": (rules.get("method_rule_toggles") or {}).get(mid),
                             "overrides": (rules.get("method_overrides") or {}).get(mid)}}

    def config_stamp(self):
        """Version stamp of what this editor saves, carried by the form."""
        from senaite.pfas import config_history
        return config_history.stamp(self._stamp_value(_portal(self.context), self.method_id()))

    def last_change(self):
        from senaite.pfas import config_history
        return config_history.last_change(_portal(self.context), "method_profile",
                                          self.method_id())

    # ── declared sections (R2, config_forms) ─────────────────────────────────
    # A tab migrated to config_forms is its own form and its own save: only its
    # fields are parsed, against its own stamp, and nothing else in the POST
    # chain runs -- the rule-toggle and surrogate-link writers read fields this
    # form does not carry, and would switch every rule off / rewrite the links.

    def section_groups(self, section_id):
        from senaite.pfas import config_forms
        from senaite.pfas.method_profile_sections import SECTIONS
        from senaite.pfas.method_profile_store import raw_profile
        return config_forms.render(SECTIONS[section_id],
                                   raw_profile(_portal(self.context), self.method_id()))

    def section_stamp(self, section_id):
        from senaite.pfas import config_forms
        from senaite.pfas.method_profile_sections import SECTIONS
        from senaite.pfas.method_profile_store import raw_profile
        return config_forms.stamp(SECTIONS[section_id],
                                  raw_profile(_portal(self.context), self.method_id()))

    def _save_section(self, portal, mid, section_id):
        from senaite.pfas import config_forms, config_history
        from senaite.pfas.method_profile_sections import SECTIONS
        from senaite.pfas.method_profile_store import raw_profile
        section = SECTIONS.get(section_id)
        if section is None:
            return self._redirect_error(mid, "Unknown section: %s" % section_id)
        pane = "pane-" + section.id
        stored = raw_profile(portal, mid)
        if not stored:
            return self._redirect_error(mid, "No profile for %s" % mid, pane)
        sent = (self.request.form.get("section_stamp") or "").strip()
        if sent != config_forms.stamp(section, stored):
            last = config_history.last_change(portal, "method_profile", mid) or {}
            return self._redirect_error(mid, (
                u"Not saved: {0} was changed by {1} at {2} UTC after you opened "
                u"it. Reload to see their change, then re-apply yours.").format(
                    section.title, last.get("who", "someone"), last.get("at", "?")), pane)
        updates, errors = config_forms.parse(section, self.request.form, stored)
        if errors:
            return self._redirect_error(mid, u"Not saved: " + u" ".join(errors), pane)
        profile = config_forms.apply(section, get_profile(portal, mid), updates)
        # A user-saved profile is no longer factory-default (the installer
        # re-runs on every start and treats _seeded profiles as its own).
        profile.pop("_seeded", None)
        save_profile(portal, mid, profile)
        return self._redirect_saved(mid, pane)

    def _handle_post(self):
        mid = self.request.form.get("method_id", "").strip()
        if not mid:
            return self._redirect_error("", "method_id is required")

        portal = _portal(self.context)
        section_id = (self.request.form.get("_section") or "").strip()
        if section_id:
            return self._save_section(portal, mid, section_id)
        # Stale-save protection (R1): refuse, before applying anything, a save
        # made from a page opened before someone else changed this profile --
        # the second save used to replace the first without a word.
        sent = (self.request.form.get("config_stamp") or "").strip()
        if sent:
            from senaite.pfas import config_history
            if sent != config_history.stamp(self._stamp_value(portal, mid)):
                candidates = [e for e in (config_history.last_change(portal, "method_profile", mid),
                                          config_history.last_change(portal, "qc_rules", "rules")) if e]
                last = max(candidates, key=lambda e: e.get("at", "")) if candidates else {}
                return self._redirect_error(mid, (
                    "Not saved: this profile was changed by {0} at {1} UTC after "
                    "you opened it. Reload to see their change, then re-apply "
                    "yours.").format(last.get("who", "someone"), last.get("at", "?")))
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

        # The surrogate map is saved above, as submitted, on THIS method only
        # (DECISIONS 2026-09-30, superseding D58's write-back): it is no longer
        # copied to the analysis services nor rebuilt from them, which is what
        # made one method's edit change the link for every method.

        return self._redirect_saved(mid)

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

        # Instrument verification (calibration, CCV, IS response, confirmation)
        # is NOT parsed here any more: the Calibration & CCV tab is its own
        # form, saved by _save_section (R2). This form no longer carries those
        # inputs, and the old handler assigned every one unconditionally --
        # parsing them here would null them on every Save & Export.

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
                    # refused, not coerced: a typo ("0,95") silently became 1.0
                    # and removed the correction from reported results (GAPS §51)
                    raise ValueError("matrix factor for {0} is not a number: "
                                     "{1!r}".format(mtx, raw))
                if factor == 1.0:
                    continue
                mf.append({"matrix": mtx, "factor": factor,
                           "sampletype_uid": uid_map.get(mtx, "")})
            profile["matrix_factors"] = mf
        else:
            profile["matrix_factors"] = _json_field(
                "matrix_factors_json", profile.get("matrix_factors", []))
        if "surrogate_map_json" in f:
            profile["surrogate_map"] = self._checked_surrogate_map(
                profile, _json_field("surrogate_map_json", []))
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

        # Reporting limits are NOT parsed here: the Reporting Limits tab is its
        # own form (config_forms table, R2), saved by _save_section.

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
                    raise ValueError("salt factor for {0} is not a number: "
                                     "{1!r}".format(kw, raw))
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

    def _redirect_saved(self, mid, pane=""):
        url = "{}/@@pfas-method-profile-edit?method_id={}&saved=1{}".format(
            self.context.absolute_url(), mid, "#" + pane if pane else "")
        self.request.response.redirect(url)
        return ""

    def _redirect_error(self, mid, msg, pane=""):
        url = "{}/@@pfas-method-profile-edit?method_id={}&error={}{}".format(
            self.context.absolute_url(), mid,
            urllib.quote(msg.encode("utf-8")), "#" + pane if pane else "")
        self.request.response.redirect(url)
        return ""
