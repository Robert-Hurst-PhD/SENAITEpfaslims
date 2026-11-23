# -*- coding: utf-8 -*-
"""Declares the settings the lab already owns, and where each one lives.

Apart from settings_registry so the registry stays dependency-free: these
hooks reach into the surfaces that own the data (the method profile, print
settings, the qualifier library, facility defaults, the expiry panel), and
only the console imports them. Each `describe_hook` asks its owner for the
value in force; no data moves and the console never writes one. Hooks import
lazily, inside the function.

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import logging

from senaite.pfas.settings_registry import (
    GROUP_QC_LIMITS, GROUP_THRESHOLDS, GROUP_VOCABULARY, GROUP_WORDING,
    KIND_BOOL, KIND_CHOICE, KIND_FLOAT, KIND_INT, KIND_LIST, KIND_TEXT,
    TIER_LAB, TIER_STRUCTURAL, register)

logger = logging.getLogger("senaite.pfas.settings_adapters")


def _vocab(name):
    """A vocab_store list: its active terms, customised once the lab saved it."""

    def _hook(portal, setting):
        try:
            from senaite.pfas import vocab_store as vs
            stored = vs.get(portal)
            terms = vs.terms(stored, name)
        except Exception as exc:                            # noqa: BLE001
            logger.warning("vocabulary hook for %s: %s", setting.key, exc)
            return {"value": None, "seed": None, "source": "unknown"}
        active = [t["label"] for t in terms if t["active"]]
        seed = [l for _k, l in vs.LISTS[name][1]]
        return {"value": u", ".join(active), "seed": u", ".join(seed),
                "source": "override" if name in stored else "seed",
                "customised": name in stored}

    return _hook


# ── Generic hook factory: merge-over-seed surfaces ───────────────────────────
# Facility defaults and print settings are both flat "saved over seed" dicts,
# so one factory serves both.

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


def _site_language_hook(portal, setting):
    try:
        from senaite.pfas.browser.time_language import site_language
        code = site_language()
    except Exception as exc:                                # noqa: BLE001
        logger.warning("site language hook: %s", exc)
        return {"value": None, "seed": None, "source": "unknown"}
    return {"value": code, "seed": u"en", "source": "override" if code != u"en" else "seed",
            "customised": code != u"en"}


def _timezone_hook(portal, setting):
    try:
        from senaite.pfas import lab_time
        name = lab_time.zone() or u"UTC"
    except Exception as exc:                                # noqa: BLE001
        logger.warning("time zone hook: %s", exc)
        return {"value": None, "seed": None, "source": "unknown"}
    return {"value": name, "seed": u"UTC", "source": "override" if name != u"UTC" else "seed",
            "customised": name != u"UTC"}


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


def _raw_share(field):
    """The raw-data share (System): unset until entered, no seed; the
    deletion switch is off until turned on."""
    def _hook(portal, setting):
        try:
            from senaite.pfas import raw_share
            value = raw_share.load(portal).get(field)
        except Exception as exc:                            # noqa: BLE001
            logger.warning("settings hook for %s: %s", setting.key, exc)
            return {"value": None, "seed": None, "source": "unknown"}
        given = value not in (None, False)
        return {"value": value, "seed": None, "source": "override" if given else "unset",
                "customised": given}

    return _hook


def _coc_limits(field, seed=None):
    """The client CoC limits (System): unset until entered, or `seed` where
    the setting has a default."""
    def _hook(portal, setting):
        try:
            from senaite.pfas import coc_limits
            value = coc_limits.load(portal).get(field)
        except Exception as exc:                            # noqa: BLE001
            logger.warning("settings hook for %s: %s", setting.key, exc)
            return {"value": None, "seed": seed, "source": "unknown"}
        if value is None and seed is not None:
            return {"value": seed, "seed": seed, "source": "seed", "customised": False}
        return {"value": value, "seed": seed, "source": "override" if value is not None else "unset",
                "customised": value is not None}

    return _hook


def _signing_rules(field):
    """The signing rules (System): seeded, the expiry unset (never)."""
    def _hook(portal, setting):
        from senaite.pfas import signing_rules
        seed = signing_rules.SEEDS.get(field)
        try:
            value = signing_rules.load(portal).get(field)
        except Exception as exc:                            # noqa: BLE001
            logger.warning("settings hook for %s: %s", setting.key, exc)
            return {"value": None, "seed": seed, "source": "unknown"}
        return {"value": value, "seed": seed, "source": "override" if value != seed else "seed",
                "customised": value != seed}

    return _hook


def _qualifier(failure_key, field):
    """One setting per FIELD of the qualifier library, which is keyed by
    failure type; `get_library` reports each entry's `customised`."""

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
    """Judging: `holding_time.limit_for` returns None when the profile says
    nothing, and `evaluate` then reports UNCONFIGURED rather than assuming
    14 days. The console shows it NOT CONFIGURED, the state that makes a
    batch unreleasable.
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
                    describe_hook=hook,
                    owner_view=owner_view, **kw)


def declare_methods(portal):
    """The per-method settings, for every configured method: its holding time
    (Matrices & Units), read for its first supported matrix. A method created
    since the last call is added; one already declared is left alone."""
    from senaite.pfas import configured_methods
    from senaite.pfas.method_profile_store import raw_profile
    from senaite.pfas.settings_registry import get_setting
    for m in configured_methods.choices(portal):
        key = "holding_time.%s" % m["id"].lower()
        if get_setting(key) is not None:
            continue
        matrices = (raw_profile(portal, m["id"]) or {}).get("supported_matrices") or []
        matrix = matrices[0] if matrices else u""
        label = u"Holding time — %s%s" % (m["label"], u", %s" % matrix if matrix else u"")
        _link(key, label, GROUP_QC_LIMITS, KIND_INT, _holding_time(m["id"], matrix),
              "pfas-method-profile-edit", unit=u"days", judging=True,
              anchor="matrices")


def declare_all(portal=None):
    """Register every already-owned setting, and with a portal the per-method
    ones (declare_methods). Idempotent per process: calling it twice would hit
    `register`'s duplicate refusal, so it guards itself."""
    if portal is not None:
        try:
            declare_methods(portal)
        except Exception as exc:                            # noqa: BLE001
            logger.warning("per-method settings not declared: %s", exc)
    if getattr(declare_all, "_done", False):
        return
    declare_all._done = True

    # ── Thresholds & schedules ───────────────────────────────────────────────
    # The site language: Plone's own setting, edited on Time & Language
    _link("site.language", u"Site language", GROUP_WORDING, KIND_CHOICE,
          _site_language_hook, "pfas-time-language")
    _link("site.timezone", u"Laboratory time zone", GROUP_WORDING, KIND_CHOICE,
          _timezone_hook, "pfas-time-language")

    # Where raw data is pulled from (a run integrated by the LIMS itself)
    _link("raw.share_path", u"Raw-data share", GROUP_THRESHOLDS, KIND_TEXT,
          _raw_share("share_path"), "pfas-system",
          tier=TIER_STRUCTURAL)
    _link("raw.settle_minutes", u"Raw data unchanged before it is pulled",
          GROUP_THRESHOLDS, KIND_INT, _raw_share("settle_minutes"), "pfas-system",
          unit=u"minutes", tier=TIER_STRUCTURAL)
    _link("raw.delete_reinjection_files", u"Delete archived re-injection files",
          GROUP_THRESHOLDS, KIND_BOOL, _raw_share("delete_reinjection_files"), "pfas-system",
          tier=TIER_STRUCTURAL)

    # What a client may do with CoC records
    _link("coc.daily_cap", u"New CoCs a client may start in a day",
          GROUP_THRESHOLDS, KIND_INT, _coc_limits("daily_cap"), "pfas-system",
          unit=u"CoCs")
    _link("coc.unsubmitted_days", u"Days an unsubmitted CoC is kept",
          GROUP_THRESHOLDS, KIND_INT, _coc_limits("unsubmitted_days"), "pfas-system",
          unit=u"days")
    from senaite.pfas.coc_limits import PAPER_DAYS_DEFAULT
    _link("coc.unsubmitted_paper_days", u"Days an unsubmitted paper CoC is kept",
          GROUP_THRESHOLDS, KIND_INT, _coc_limits("unsubmitted_paper_days", PAPER_DAYS_DEFAULT),
          "pfas-system", unit=u"days")

    # How a person signs: the PIN, the lock after wrong tries, and when a
    # password and a PIN expire
    _link("signing.pin_min", u"Shortest signing PIN", GROUP_THRESHOLDS, KIND_INT,
          _signing_rules("pin_min"), "pfas-system", unit=u"digits")
    _link("signing.pin_max", u"Longest signing PIN", GROUP_THRESHOLDS, KIND_INT,
          _signing_rules("pin_max"), "pfas-system", unit=u"digits")
    _link("signing.lock_tries", u"Wrong signing tries before a lock", GROUP_THRESHOLDS, KIND_INT,
          _signing_rules("lock_tries"), "pfas-system", unit=u"tries")
    _link("signing.lock_minutes", u"Signing tries counted over, and lock", GROUP_THRESHOLDS, KIND_INT,
          _signing_rules("lock_minutes"), "pfas-system", unit=u"minutes")
    _link("signing.expiry_days", u"Passwords and PINs expire after", GROUP_THRESHOLDS, KIND_INT,
          _signing_rules("expiry_days"), "pfas-system", unit=u"days")

    # Balance acceptance is the balance TYPE's tolerance, % of nominal
    # (equipment_types.py), never a lab-wide value in grams.
    _link("facility.study_tolerance",
          u"Temperature study tolerance",
          GROUP_THRESHOLDS, KIND_FLOAT, _facility("study_tolerance"),
          "pfas-equipment-types", unit=u"°C", judging=True)
    _link("facility.eyewash_temp_min", u"Eye wash minimum temperature",
          GROUP_THRESHOLDS, KIND_FLOAT, _facility("eyewash_temp_min"),
          "pfas-equipment-types", unit=u"°C", judging=True)
    _link("facility.eyewash_temp_max", u"Eye wash maximum temperature",
          GROUP_THRESHOLDS, KIND_FLOAT, _facility("eyewash_temp_max"),
          "pfas-equipment-types", unit=u"°C", judging=True)
    _link("facility.water_conductivity_max",
          u"Type 1 water conductivity maximum",
          GROUP_THRESHOLDS, KIND_FLOAT, _facility("water_conductivity_max"),
          "pfas-equipment-types", unit=u"µS/cm", judging=True)
    _link("facility.water_toc_max", u"Type 1 water TOC maximum",
          GROUP_THRESHOLDS, KIND_FLOAT, _facility("water_toc_max"),
          "pfas-equipment-types", unit=u"ppb", judging=True)

    for field, label, unit in (
            ("reagent_default_days",
             u"Reagent shelf life when the manufacturer states none", u"days"),
            ("mobile_phase_open_days",
             u"Mobile phase life after opening", u"days"),
            ("opened_default_days", u"Other reagent life after opening", u"days"),
            ("prepared_std_default_days",
             u"Prepared standard life from preparation", u"days")):
        _link("expiry." + field, label, GROUP_THRESHOLDS, KIND_INT,
              _expiry(field), "pfas-reagents", unit=unit, anchor="expiry")

    # ── Lists the lab edits (vocab_store) ───────────────────────────────────
    from senaite.pfas.vocab_store import LISTS
    for name in sorted(LISTS):
        _link("vocab." + name, LISTS[name][0], GROUP_VOCABULARY, KIND_LIST,
              _vocab(name), "pfas-vocabularies", anchor=name)

    # ── Wording on documents ────────────────────────────────────────────────
    # the laboratory's identity is edited on the Laboratory page
    for field, label in (("lab_name", u"Laboratory name"),
                         ("lab_address", u"Laboratory address"),
                         ("accreditation", u"Accreditation statement")):
        _link("print." + field, label, GROUP_WORDING, KIND_TEXT, _print(field),
              "pfas-laboratory")
    for field, label, kind in (
            ("show_signoff", u"Print the QA sign-off block", KIND_BOOL),
            # the certificate's columns, non-detect print and significant
            # figures are each method's (Reporting tab, report_format.py),
            # with built-in defaults: not rows here
            ("coa_signature_style", u"Certificate: sign-off layout", KIND_TEXT)):
        _link("print." + field, label, GROUP_WORDING, kind, _print(field),
              "pfas-print-settings")

    # One row per failure type: what the certificate says, and whether the
    # failure qualifies a result or holds the report.
    from senaite.pfas.qc_qualification import FAILURE_TYPES
    for key, label, _disposition, _code in FAILURE_TYPES:
        _link("qualifier.%s.statement" % key,
              u"Certificate wording — %s" % label,
              GROUP_WORDING, KIND_TEXT, _qualifier(key, "statement"),
              "pfas-qc-qualifiers")
        _link("qualifier.%s.disposition" % key,
              u"Disposition — %s" % label,
              GROUP_WORDING, KIND_CHOICE, _qualifier(key, "disposition"),
              "pfas-qc-qualifiers")
