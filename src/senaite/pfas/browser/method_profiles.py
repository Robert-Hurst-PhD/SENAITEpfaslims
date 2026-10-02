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
        from senaite.pfas import method_revisions as mr
        from senaite.pfas.method_profile_store import raw_profile
        from senaite.pfas.qc.rules import method_toggles
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
                # issued revisions (DECISIONS 2026-10-02)
                "revision": mr.status(mr.records(portal, mid), mr.fingerprint(
                    raw_profile(portal, mid) or {},
                    method_toggles(raw_profile(portal, mid) or {}, mid))),
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

        if self.request.form.get("_preview") == "rt":
            return self._preview_recovery_grid()
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

    def per_analyte_json(self):
        from senaite.pfas.method_profile_store import DEFAULT_PROFILES
        per_a = self.profile().get("per_analyte") or []
        if not per_a:
            # Stored profile has explicit [] (old seeded profile); back-fill from defaults.
            per_a = DEFAULT_PROFILES.get(self.method_id(), {}).get("per_analyte", [])
        return json.dumps(per_a, indent=2)

    def per_analyte_labels_json(self):
        """{stored row name: label to SHOW}. Rows are stored under the global
        display name, which spec_sync reads, so the key stays; the page shows
        the method's label (an isomer group's reported name)."""
        from senaite.pfas.analyte_reference import NATIVE_ANALYTES
        from senaite.pfas.method_profile_sections import _analyte_titles
        labels = _analyte_titles(self.profile())
        out = {}
        for row in NATIVE_ANALYTES:
            out[row[1]] = labels.get(row[0])
            out[row[0]] = labels.get(row[0])
        return json.dumps(out)

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

    def qc_type_toggles(self):
        """Per-method QC-type enable toggles — one row per qc_acceptance key.
        Enabling/disabling here gates the QC engine AND spec_sync (which now
        derives its QC types from these keys, not a hardcoded tuple).

        Display names come from the tagged core Reference Definitions (the
        single UI-editable source), not a hardcoded map."""
        from senaite.pfas.qc_labels import get_qc_label_map
        from senaite.pfas.method_profile_sections import qc_type_rows
        from bika.lims import api
        return qc_type_rows(self.profile(), get_qc_label_map(api.get_portal()))

    def rule_qc_type_rows(self):
        """Extraction / matrix QC on the Rule Toggles tab: the SAME switch as
        the QC Types tab (same form field, qc_enabled_<key>), for the types
        this method can run (DECISIONS 2026-10-01)."""
        from senaite.pfas.qc.rules import QC_TYPE_SWITCHES
        labels = dict(QC_TYPE_SWITCHES)
        by_code = dict((q["code"], q) for q in self.qc_type_toggles() if q.get("toggle"))
        return [dict(by_code[code], rule_label=labels[code])
                for code, _l in QC_TYPE_SWITCHES if code in by_code]

    # ── Rule switches: on the profile itself (QC consolidation P2) ─────────

    def rule_toggle_rows(self):
        """Per selected-method rule rows: each = enable toggle + its param
        overrides. Merges the old QC-Rules 'Rule Toggles' + 'Method Limits'
        tabs into one (a method's limits ARE the params of its rules)."""
        try:
            from senaite.pfas.qc.rules import RULE_LIBRARY
        except Exception:
            return []
        from senaite.pfas.qc.rules import method_toggles
        toggles = method_toggles(self.profile(), self.method_id())
        # a rule is a switch; its limits are this profile's Calibration & CCV
        # fields (QC consolidation P2)
        return [{"key": rule["key"], "label": rule["label"],
                 "enabled": bool(toggles.get(rule["key"], True)),
                 "has_params": False, "params": [],
                 "note": rule.get("note") or u""}
                for rule in RULE_LIBRARY]

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
        from senaite.pfas.method_profile_store import service_index
        return service_index()

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
        """What this editor saves for one method: the stored profile (its rule
        switches included since QC consolidation P2), so any colleague's save
        makes an open page stale."""
        from senaite.pfas.method_profile_store import raw_profile
        from senaite.pfas.config_history import IGNORED_KEYS
        profile = dict((k, v) for k, v in raw_profile(portal, mid).items()
                       if k not in IGNORED_KEYS and k not in ("updated_at", "updated_by", "_seeded"))
        return {"profile": profile}

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

    def spike_sections(self):
        """[(section id, label)] for the spiked QC types this method runs."""
        from senaite.pfas.method_profile_sections import SPIKE_LEVELS, SPIKE_LABELS
        from senaite.pfas.qc.qc_types import enabled_qc_types
        on = set(enabled_qc_types(self.profile()))
        if "LFSMD" in on:
            on.add("LFSM")                       # LFSMD shares the LFSM levels
        return [(SPIKE_LEVELS[q].id, SPIKE_LABELS[q]) for q in ("LFSM", "LFB", "LCS") if q in on]

    def has_dup(self):
        return "Dup" in ((self.profile().get("qc_acceptance") or {}))

    rt_grid_template = ViewPageTemplateFile("templates/rt_grid.pt")

    def rt_grid_html(self):
        return self.rt_grid_template(grid=self.recovery_grid())

    def _preview_recovery_grid(self):
        """The applied-window grid for the Recovery Tiers form AS EDITED, not
        saved: the same parse + apply a save runs, then the same resolver the
        page draws with. Nothing is written."""
        from senaite.pfas import config_forms
        from senaite.pfas.method_profile_sections import SECTIONS, recovery_grid
        from senaite.pfas.method_profile_store import raw_profile
        stored = raw_profile(_portal(self.context), self.method_id())
        profile = stored
        for sid in ("groups", "tiers"):
            updates, errors = config_forms.parse(SECTIONS[sid], self.request.form, stored)
            if errors:
                self.request.response.setHeader("X-Preview-Errors", "1")
                return u'<div id="rt-grid"><p class="alert alert-error">%s</p></div>' % (
                    u" ".join(errors).replace(u"<", u"&lt;"))
            profile = config_forms.apply(SECTIONS[sid], profile, updates)
        self.request.response.setHeader("Content-Type", "text/html; charset=utf-8")
        return self.rt_grid_template(grid=recovery_grid(profile))

    def rt_section_ids(self):
        ids = ["groups", "tiers"] + [sid for sid, _l in self.spike_sections()]
        return (ids + (["tiers_lfb"] if self.has_lfb() else []) +
                (["dup"] if self.has_dup() else []) +
                (["lfsmd"] if self.has_lfsmd() else []))

    def has_lfsmd(self):
        return "LFSMD" in ((self.profile().get("qc_acceptance") or {}))

    def calibration_level_unit(self):
        from senaite.pfas import calibration_levels as cl
        return cl.unit(self.profile())

    def calibration_levels_source(self):
        from senaite.pfas import calibration_levels as cl
        return cl._calib(self.profile()).get("levels_source") or u""

    def recommended_spikes(self):
        """Low / Mid / High from this method's calibration levels: in the
        level unit, and as sample ppt per matrix (the spike grids' unit);
        None without at least two levels."""
        import json
        from senaite.pfas import calibration_levels as cl
        profile = self.profile()
        base = cl.recommended_spikes(profile)
        if not base:
            return None
        fmt = cl.fmt
        per = []
        for m in profile.get("supported_matrices") or []:
            ppt = cl.recommended_spikes_ppt(profile, m)
            per.append({"matrix": m, "low": fmt(ppt.get("Low")), "mid": fmt(ppt.get("Mid")),
                        "high": fmt(ppt.get("High")), "ok": bool(ppt)})
        return {"unit": cl.unit(profile), "low": fmt(base["Low"]), "mid": fmt(base["Mid"]),
                "high": fmt(base["High"]), "matrices": per,
                "missing": [p["matrix"] for p in per if not p["ok"]],
                "any": any(p["ok"] for p in per),
                "json": json.dumps([[p["low"], p["mid"], p["high"]] for p in per])}

    def has_lfb(self):
        return "LFB" in ((self.profile().get("qc_acceptance") or {}))

    def grouped_tiers(self):
        from senaite.pfas.method_profile_sections import GROUPED_TIER_METHODS
        return self.method_id() in GROUPED_TIER_METHODS

    def recovery_grid(self):
        from senaite.pfas.method_profile_sections import recovery_grid
        from senaite.pfas.method_profile_store import raw_profile
        return recovery_grid(raw_profile(_portal(self.context), self.method_id()))

    def section_env(self):
        """What a declared section needs from the site that the profile does
        not hold: the reagent inventory's standard lots (salt CoA lots), the
        services, and the regulatory limits (Reporting tab)."""
        if getattr(self, "_section_env", None) is None:
            from senaite.pfas import regulatory_limits
            self._section_env = {"standard_lots": self.standard_lot_options(),
                                 "services": self._pfas_service_index(),
                                 "regulatory": regulatory_limits.get_store(_portal(self.context))}
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
                                  raw_profile(_portal(self.context), self.method_id()),
                                  self.section_env())

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
            if sent != config_forms.stamp(section, stored, env):
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
                candidates = [e for e in (config_history.last_change(portal, "method_profile", mid),) if e]
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

        self._apply_rule_toggles(profile)
        save_profile(portal, mid, profile)

        # The surrogate map is saved above, as submitted, on THIS method only
        # (DECISIONS 2026-09-30, superseding D58's write-back): it is no longer
        # copied to the analysis services nor rebuilt from them, which is what
        # made one method's edit change the link for every method.

        return self._redirect_saved(mid)

    def _apply_rule_toggles(self, profile):
        """Write the Rule Toggles tab's switches INTO the profile (QC
        consolidation P2) -- only when the tab was submitted (marker)."""
        f = self.request.form
        if not f.get("qc_rules_present"):
            return
        from senaite.pfas.qc.rules import RULE_LIBRARY
        profile["rule_toggles"] = dict(
            (rule["key"], bool(f.get("ruletoggle." + rule["key"]))) for rule in RULE_LIBRARY)

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

        # Recovery tiers, spike levels and the Dup RPD are NOT parsed here: the
        # Recovery Tiers tab is its own form (declared grids, R2).

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
            from senaite.pfas.method_profile_sections import apply_qc_toggles
            offered = [k for k in (f.get("qc_offered") or "").split(",") if k]
            enabled = set(k for k in offered if f.get("qc_enabled_%s" % k))
            apply_qc_toggles(profile, offered, enabled)

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
