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
        if not _require_manager(self.context, self.request):
            self.request.response.setStatus(403)
            return "Forbidden: Manager, LabManager, or Owner role required"
        return self.template()

    def portal_url(self):
        return _portal(self.context).absolute_url()

    def methods(self):
        portal = _portal(self.context)
        saved_ids = set(list_method_ids(portal))
        all_ids = sorted(set(list(DEFAULT_PROFILES.keys())) | saved_ids)
        result = []
        for mid in all_ids:
            p = get_profile(portal, mid)
            # _seeded=True means the profile was written by seed_default_profiles
            # and has not yet been edited by a user.
            # User-saved profiles don't include _seeded, so it defaults to False.
            is_customised = not p.get("_seeded", False)
            result.append({
                "method_id": mid,
                "display_name": p.get("display_name", mid),
                "description": p.get("description", ""),
                "is_customised": is_customised,
            })
        return result


# ── Edit view ─────────────────────────────────────────────────────────────────

class PFASMethodProfileEditView(BrowserView):
    """Edit a single PFAS method profile."""

    template = ViewPageTemplateFile("templates/method_profile_edit.pt")

    def __call__(self):
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

    # Convenience accessors for individual profile sections
    def cal(self):
        return self.profile().get("calibration", {})

    def ccv(self):
        return self.profile().get("ccv", {})

    def is_section(self):
        return self.profile().get("is", {})

    def confirmation(self):
        return self.profile().get("confirmation", {})

    def duplicate(self):
        return self.profile().get("duplicate", {})

    def recovery_tiers_json(self):
        return json.dumps(self.profile().get("recovery_tiers", []), indent=2)

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

    def isomer_summation_json(self):
        return json.dumps(self.profile().get("isomer_summation", []), indent=2)

    def spike_levels_json(self):
        return json.dumps(self.profile().get("spike_levels", {}), indent=2)

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

    # ── Surrogate IS lane data ────────────────────────────────────────────────

    def surrogate_is_data(self):
        """JSON payload for the JS surrogate map table (analyte → labeled IS)."""
        from senaite.pfas.analyte_reference import get_surrogates, NATIVE_ANALYTES
        kw_to_display = {row[0]: row[1] for row in NATIVE_ANALYTES}
        profile = self.profile()
        sur_map = profile.get("surrogate_map", [])
        map_dict = {}
        for row in sur_map:
            map_dict[row.get("analyte", "")] = row.get("surrogate_is", "")
        keywords = profile.get("master_analyte_set", [])
        return json.dumps({
            "analytes":       keywords,
            "analyte_labels": {kw: kw_to_display.get(kw, kw) for kw in keywords},
            "surrogates":     get_surrogates(),
            "map":            map_dict,
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
        return self._redirect_saved(mid)

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

        # Calibration
        cal = profile.setdefault("calibration", {})
        r2 = _float("cal_r2_min")
        if r2 is not None:
            cal["r2_min"] = r2
        cal["force_origin"]          = _bool("cal_force_origin")
        cal["point_pct_dev_max"]     = _float("cal_point_pct_dev_max")
        cal["low_point_pct_dev_max"] = _float("cal_low_point_pct_dev_max")

        # CCV
        ccv = profile.setdefault("ccv", {})
        freq = _int("ccv_frequency")
        if freq is not None:
            ccv["frequency"] = freq
        ccv["recovery_min"]  = _float("ccv_recovery_min", ccv.get("recovery_min"))
        ccv["recovery_max"]  = _float("ccv_recovery_max", ccv.get("recovery_max"))
        ccv["low_level_min"] = _float("ccv_low_level_min")
        ccv["low_level_max"] = _float("ccv_low_level_max")

        # IS / surrogate response
        is_ = profile.setdefault("is", {})
        is_["vs_ical_avg_min"] = _float("is_vs_ical_avg_min")
        is_["vs_ical_avg_max"] = _float("is_vs_ical_avg_max")
        is_["vs_last_ccv_min"] = _float("is_vs_last_ccv_min")
        is_["vs_last_ccv_max"] = _float("is_vs_last_ccv_max")
        is_["notes"]           = f.get("is_notes", "").strip()

        # Chromatographic confirmation
        conf = profile.setdefault("confirmation", {})
        conf["rrt_tol_pct"]              = _float("conf_rrt_tol_pct")
        conf["rt_tol_abs_min"]           = _float("conf_rt_tol_abs_min")
        conf["ion_ratio_tol_pct"]        = _float("conf_ion_ratio_tol_pct")
        conf["sn_quan_min"]              = _float("conf_sn_quan_min")
        conf["sn_confirm_min"]           = _float("conf_sn_confirm_min")
        conf["require_confirm_ion_check"] = _bool("conf_require_confirm_ion_check")

        # Duplicate / LFSMD RPD
        dup = profile.setdefault("duplicate", {})
        rpd = _float("dup_rpd_max")
        if rpd is not None:
            dup["rpd_max"] = rpd

        # Complex JSON sections (textareas)
        profile["recovery_tiers"] = _json_field(
            "recovery_tiers_json", profile.get("recovery_tiers", []))
        profile["matrix_factors"] = _json_field(
            "matrix_factors_json", profile.get("matrix_factors", []))
        profile["surrogate_map"]  = _json_field(
            "surrogate_map_json",  profile.get("surrogate_map", []))
        profile["per_analyte"]    = _json_field(
            "per_analyte_json",    profile.get("per_analyte", []))

        raw_eis = f.get("eis_overrides_json", "").strip()
        if raw_eis:
            profile["eis_overrides"] = json.loads(raw_eis)

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
