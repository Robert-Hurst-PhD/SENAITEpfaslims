# -*- coding: utf-8 -*-
"""Declares the settings the lab already owns, and where each one lives.

WHY A SEPARATE MODULE
---------------------
`settings_registry` must stay dependency-free so a store and a view can both
import it without a cycle (the reasoning `browser/perms.py` records for itself).
Everything here reaches INTO the surfaces that own data, so it lives apart and is
imported only by the console.

WHY EVERYTHING HERE IS `linked`, NOT `registry`
-----------------------------------------------
Rule 2: build on working code, never replace it wholesale. The method-profile
editor, print settings, the qualifier library, facility defaults and the expiry
panel all work; the problem was never that they do not work, it is that a lab
admin must already know which of six sidebar groups owns each one. So this module
makes the registry AWARE of them -- group, tier, unit, judging, owning view -- and
`describe_hook` asks the owner for the current value. **No data moves, and the
console never writes them.**

A `registry`-owned setting is created only when a genuinely code-only value is
migrated, and only together with the consumer that reads it, so the registry can
never accumulate keys nothing consumes. That is the defect this whole layer
exists to make visible -- `profiles/default/registry.xml` ships four
`senaite.pfas.*` records that nothing reads.

Hooks import lazily, inside the function, so this module stays importable by the
Py3 test suite (which cannot import `senaite.pfas.*` as a package).

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import logging

from senaite.pfas.settings_registry import (
    GROUP_QC_LIMITS, GROUP_THRESHOLDS, GROUP_WORDING,
    KIND_BOOL, KIND_CHOICE, KIND_FLOAT, KIND_INT, KIND_TEXT,
    STORAGE_LINKED, TIER_LAB, register)

logger = logging.getLogger("senaite.pfas.settings_adapters")


# ── Generic hook factory: merge-over-seed surfaces ───────────────────────────
# Both facility defaults and print settings are flat "saved over seed" dicts, so
# one factory serves both rather than two near-identical closures.

def _dict_surface_hook(accessor, seeds, field):
    """A hook for a surface exposing get_x(portal) -> flat dict, plus a seed dict.

    `accessor` and `seeds` are ZERO-ARGUMENT callables resolved at call time, so
    an import error surfaces as one unknown row rather than breaking the console.
    """

    def _hook(portal, setting):
        try:
            seed = (seeds() or {}).get(field)
            live = (accessor(portal) or {}).get(field)
        except Exception as exc:                            # noqa: BLE001
            logger.warning("settings hook for %s: %s", setting.key, exc)
            return {"value": None, "seed": None, "source": "unknown"}
        customised = live != seed
        return {"value": live, "seed": seed,
                "source": "override" if customised else "seed",
                "customised": customised}

    return _hook


def _facility(field):
    def _accessor(portal):
        from senaite.pfas import facility_qc
        return facility_qc.get_facility_defaults(portal)

    def _seeds():
        from senaite.pfas import facility_qc
        return facility_qc._defaults_seed()

    return _dict_surface_hook(_accessor, _seeds, field)


def _print(field):
    def _accessor(portal):
        from senaite.pfas import print_settings
        return print_settings.get_print_settings(portal)

    def _seeds():
        from senaite.pfas import print_settings
        return print_settings.DEFAULTS

    return _dict_surface_hook(_accessor, _seeds, field)


def _expiry(field):
    def _accessor(portal):
        from senaite.pfas.browser import reagents
        return reagents.get_expiry_defaults(portal)

    def _seeds():
        from senaite.pfas.browser import reagents
        return reagents.EXPIRY_DEFAULTS

    return _dict_surface_hook(_accessor, _seeds, field)


def _qualifier(failure_key, field):
    """The qualifier library is keyed by failure type, and `get_library` already
    reports per-entry `customised`. Declaring one setting per FIELD gives the
    console per-row truth while leaving that accessor untouched."""

    def _hook(portal, setting):
        try:
            from senaite.pfas import qc_qualification as qq
            entry = (qq.get_library(portal) or {}).get(failure_key) or {}
            seed = (qq.DEFAULT_LIBRARY.get(failure_key) or {}).get(field)
            if seed is None:
                # disposition and code seeds live in the FAILURE_TYPES table.
                for key, _label, disposition, code in qq.FAILURE_TYPES:
                    if key == failure_key:
                        seed = {"disposition": disposition,
                                "code": code}.get(field)
                        break
        except Exception as exc:                            # noqa: BLE001
            logger.warning("qualifier hook for %s: %s", setting.key, exc)
            return {"value": None, "seed": None, "source": "unknown"}
        live = entry.get(field)
        customised = live != seed
        return {"value": live, "seed": seed,
                "source": "override" if customised else "seed",
                "customised": customised}

    return _hook


def _holding_time(method_id, matrix):
    """Judging, and genuinely unset for two of three methods.

    `holding_time.limit_for` returns None when the profile says nothing, and
    `evaluate` then reports UNCONFIGURED rather than assuming 14 days. So this is
    the setting that demonstrates what the console is for: it renders as NOT
    CONFIGURED, which is exactly the state that makes a batch unreleasable.
    """

    def _hook(portal, setting):
        try:
            from senaite.pfas import holding_time
            from senaite.pfas.method_profile_store import get_profile
            profile = get_profile(portal, method_id) or {}
            days = holding_time.limit_for(profile, matrix)
        except Exception as exc:                            # noqa: BLE001
            logger.warning("holding-time hook for %s: %s", setting.key, exc)
            return {"value": None, "seed": None, "source": "unknown"}
        if days is None:
            return {"value": None, "seed": None, "source": "unset",
                    "customised": False}
        return {"value": days, "seed": None, "source": "override",
                "customised": True}

    return _hook


# ── Declarations ─────────────────────────────────────────────────────────────

def _link(key, label, group, kind, hook, owner_view, **kw):
    return register(key=key, label=label, group=group, kind=kind,
                    tier=kw.pop("tier", TIER_LAB),
                    storage=STORAGE_LINKED, describe_hook=hook,
                    owner_view=owner_view, **kw)


def declare_all():
    """Register every already-owned setting. Idempotent per process: calling it
    twice would hit `register`'s duplicate refusal, so it guards itself."""
    if getattr(declare_all, "_done", False):
        return
    declare_all._done = True

    # ── Thresholds & schedules ───────────────────────────────────────────────
    # Balance acceptance is the balance TYPE's tolerance, % of nominal
    # (equipment_types.py, GAPS §100) -- no lab-wide value in grams any more.
    _link("facility.study_tolerance",
          u"Temperature study tolerance",
          GROUP_THRESHOLDS, KIND_FLOAT, _facility("study_tolerance"),
          "pfas-facility-units", unit=u"°C", judging=True,
          reader="senaite.pfas.facility_qc.get_facility_defaults")
    _link("facility.eyewash_temp_min", u"Eye wash minimum temperature",
          GROUP_THRESHOLDS, KIND_FLOAT, _facility("eyewash_temp_min"),
          "pfas-facility-units", unit=u"°C", judging=True,
          reader="senaite.pfas.facility_qc.get_facility_defaults")
    _link("facility.eyewash_temp_max", u"Eye wash maximum temperature",
          GROUP_THRESHOLDS, KIND_FLOAT, _facility("eyewash_temp_max"),
          "pfas-facility-units", unit=u"°C", judging=True,
          reader="senaite.pfas.facility_qc.get_facility_defaults")
    _link("facility.water_conductivity_max",
          u"Type 1 water conductivity maximum",
          GROUP_THRESHOLDS, KIND_FLOAT, _facility("water_conductivity_max"),
          "pfas-facility-units", unit=u"µS/cm", judging=True,
          reader="senaite.pfas.facility_qc.get_facility_defaults")
    _link("facility.water_toc_max", u"Type 1 water TOC maximum",
          GROUP_THRESHOLDS, KIND_FLOAT, _facility("water_toc_max"),
          "pfas-facility-units", unit=u"ppb", judging=True,
          reader="senaite.pfas.facility_qc.get_facility_defaults")

    for field, label, unit in (
            ("reagent_default_days",
             u"Reagent shelf life when the manufacturer states none", u"days"),
            ("mobile_phase_open_days",
             u"Mobile phase life after opening", u"days"),
            ("opened_default_days", u"Other reagent life after opening", u"days"),
            ("prepared_std_default_days",
             u"Prepared standard life from preparation", u"days")):
        _link("expiry." + field, label, GROUP_THRESHOLDS, KIND_INT,
              _expiry(field), "pfas-reagents", unit=unit, anchor="expiry",
              reader="senaite.pfas.browser.reagents.get_expiry_defaults")

    # ── QC limits & acceptance criteria ──────────────────────────────────────
    # Holding time per method, from the method profile. EPA 537.1 is the only one
    # seeded (14 days); the other two report UNCONFIGURED, which is the honest
    # state and blocks their batches.
    for method_id, matrix, label in (
            ("EPA_537_1", "Drinking Water",
             u"Holding time — EPA 537.1, drinking water"),
            ("FDA_32PFAS", "",
             u"Holding time — FDA 32-PFAS"),
            ("EPA_1633A", "",
             u"Holding time — EPA 1633A")):
        _link("holding_time.%s" % method_id.lower(), label,
              GROUP_QC_LIMITS, KIND_INT, _holding_time(method_id, matrix),
              "pfas-method-profile-edit", unit=u"days", judging=True,
              anchor="matrices",
              reader="senaite.pfas.holding_time.limit_for")

    # ── Wording on documents ────────────────────────────────────────────────
    for field, label, kind in (
            ("lab_name", u"Laboratory name", KIND_TEXT),
            ("lab_address", u"Laboratory address", KIND_TEXT),
            ("accreditation", u"Accreditation statement", KIND_TEXT),
            ("footer_text", u"Printed-document footer", KIND_TEXT),
            ("show_signoff", u"Print the QA sign-off block", KIND_BOOL),
            ("coa_show_cas", u"Certificate: CAS number column", KIND_BOOL),
            ("coa_show_mdl", u"Certificate: MDL column", KIND_BOOL),
            ("coa_show_dilution", u"Certificate: dilution column", KIND_BOOL),
            ("coa_nd_format", u"Certificate: how a non-detect prints", KIND_TEXT),
            ("coa_sig_figs", u"Certificate: significant figures", KIND_TEXT),
            ("coa_signature_style", u"Certificate: sign-off layout", KIND_TEXT)):
        _link("print." + field, label, GROUP_WORDING, kind, _print(field),
              "pfas-print-settings",
              reader="senaite.pfas.print_settings.get_print_settings")

    # One row per failure type: what the certificate says, and whether the
    # failure qualifies a result or holds the report.
    try:
        from senaite.pfas.qc_qualification import FAILURE_TYPES
    except Exception:                                       # noqa: BLE001
        FAILURE_TYPES = []
    for key, label, _disposition, _code in FAILURE_TYPES:
        _link("qualifier.%s.statement" % key,
              u"Certificate wording — %s" % label,
              GROUP_WORDING, KIND_TEXT, _qualifier(key, "statement"),
              "pfas-print-settings", anchor="qualifiers",
              reader="senaite.pfas.qc_qualification.get_library")
        _link("qualifier.%s.disposition" % key,
              u"Disposition — %s" % label,
              GROUP_WORDING, KIND_CHOICE, _qualifier(key, "disposition"),
              "pfas-print-settings", anchor="qualifiers",
              reader="senaite.pfas.qc_qualification.get_library")
