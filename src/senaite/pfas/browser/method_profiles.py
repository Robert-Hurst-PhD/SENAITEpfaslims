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

    def per_analyte_json(self):
        from senaite.pfas.method_profile_store import DEFAULT_PROFILES
        per_a = self.profile().get("per_analyte") or []
        if not per_a:
            # Stored profile has explicit [] (old seeded profile); back-fill from defaults.
            per_a = DEFAULT_PROFILES.get(self.method_id(), {}).get("per_analyte", [])
        return json.dumps(per_a, indent=2)

    def per_analyte_labels_json(self):
        """{stored row name: label to SHOW}. Rows are stored under the global
        display name ("lr-PFOS"), which spec_sync reads, so the key stays; the
        page shows the method's label (a summed PFOS is "PFOS")."""
        from senaite.pfas.analyte_reference import NATIVE_ANALYTES
        from senaite.pfas.method_profile_sections import _analyte_titles
        labels = _analyte_titles(self.profile())
        out = {}
        for row in NATIVE_ANALYTES:
            out[row[1]] = labels.get(row[0])
            out[row[0]] = labels.get(row[0])
        return json.dumps(out)

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
        # labels follow the method's isomers (a summed PFOS is "PFOS")
        from senaite.pfas.method_profile_sections import _analyte_titles
        profile = self.profile()
        labels = _analyte_titles(profile)
        keywords = profile.get("master_analyte_set", [])
        return json.dumps({
            "analytes":       keywords,
            "analyte_labels": {kw: labels.get(kw) for kw in keywords},
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

    def display_name(self):
        return self.profile().get("display_name", self.method_id())

    def description(self):
        return self.profile().get("description", "")

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

    def eis_class_sections(self):
        """[(section id, label)] for the four 1633A matrix-class EIS tables."""
        from senaite.pfas.method_profile_sections import EIS_CLASSES
        return [(c.id, label) for c, label in EIS_CLASSES]

    def section_env(self):
        """What a declared section needs from the site that the profile does
        not hold: the reagent inventory's standard lots (salt CoA lots)."""
        if getattr(self, "_section_env", None) is None:
            self._section_env = {"standard_lots": self.standard_lot_options(),
                                 "services": self._pfas_service_index()}
        return self._section_env

    def section_groups(self, section_id):
        from senaite.pfas import config_forms
        from senaite.pfas.method_profile_sections import SECTIONS
        from senaite.pfas.method_profile_store import raw_profile
        return config_forms.render(SECTIONS[section_id],
                                   raw_profile(_portal(self.context), self.method_id()),
                                   self.section_env())

    def section_stamp(self, section_id):
        from senaite.pfas import config_forms
        from senaite.pfas.method_profile_sections import SECTIONS
        from senaite.pfas.method_profile_store import raw_profile
        return config_forms.stamp(SECTIONS[section_id],
                                  raw_profile(_portal(self.context), self.method_id()))

    def _save_section(self, portal, mid, section_ids):
        """Save the declared section(s) one tab's form carries ("_section" is a
        comma-separated list; each carries its own section_stamp__<id>). All
        are checked before any is applied: one stale or refused section saves
        nothing, so a tab is never left half-saved."""
        from senaite.pfas import config_forms, config_history
        from senaite.pfas.method_profile_sections import SECTIONS
        from senaite.pfas.method_profile_store import raw_profile
        form = self.request.form
        pane = (form.get("_pane") or "").strip()
        ids = [i.strip() for i in section_ids.split(",") if i.strip()]
        sections = [SECTIONS.get(i) for i in ids]
        if not ids or None in sections:
            return self._redirect_error(mid, "Unknown section: %s" % section_ids)
        pane = pane or "pane-" + ids[0]
        stored = raw_profile(portal, mid)
        if not stored:
            return self._redirect_error(mid, "No profile for %s" % mid, pane)
        env = self.section_env()
        for section in sections:
            sent = (form.get("section_stamp__" + section.id) or "").strip()
            if sent != config_forms.stamp(section, stored):
                last = config_history.last_change(portal, "method_profile", mid) or {}
                return self._redirect_error(mid, (
                    u"Not saved: {0} was changed by {1} at {2} UTC after you opened "
                    u"it. Reload to see their change, then re-apply yours.").format(
                        section.title, last.get("who", "someone"), last.get("at", "?")), pane)
        parsed, errors = [], []
        for section in sections:
            updates, errs = config_forms.parse(section, form, stored, env)
            parsed.append((section, updates))
            errors.extend(errs)
        if errors:
            return self._redirect_error(mid, u"Not saved: " + u" ".join(errors), pane)
        profile = get_profile(portal, mid)
        for section, updates in parsed:
            profile = config_forms.apply(section, profile, updates, env)
        from senaite.pfas.method_profile_sections import PROFILE_CHECKS
        for watched, check in PROFILE_CHECKS:
            if set(watched) & set(ids):
                problems = check(profile)
                if problems:
                    return self._redirect_error(mid, u"Not saved: " + u" ".join(problems), pane)
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

        # Salt and matrix adjustment factors are NOT parsed here: the Sample
        # Corrections tab is its own form (config_forms tables, R2), saved by
        # _save_section. The old fallbacks that re-read a hidden JSON copy of
        # each on every other save are gone with them -- no field sent either.

        profile["per_analyte"]    = _json_field(
            "per_analyte_json",    profile.get("per_analyte", []))

        # Matrices & Units is NOT parsed here: it is its own form (config_forms
        # collection, R2), saved by _save_section, which refuses a removal or
        # rename that would orphan matrix-keyed data.

        # Reporting limits are NOT parsed here: the Reporting Limits tab is its
        # own form (config_forms table, R2), saved by _save_section.

        # EIS limits (per-analyte and per matrix class) are NOT parsed here:
        # they are declared collections on their own tab form (R2).

        # The injection IS, surrogate map and surrogate chain are NOT parsed
        # here: the Surrogate Map tab is its own form (R2, declared sections).

        # Isomers are NOT parsed here: the Isomers tab is its own form (R2).

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
