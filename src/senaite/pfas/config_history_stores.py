# -*- coding: utf-8 -*-
"""Which configuration stores can be reverted from history, and how (R1).

Each registration names the store's getter and its OWN save function, so a
revert keeps every side effect of a normal save (JSON export, spec sync...).
Stores not listed here are recorded in history but reverted in their own
editor. Imported by the History page; method_profile registers itself.
"""
from __future__ import absolute_import

from senaite.pfas import config_history


def register_all():
    from senaite.pfas import method_profile_store               # noqa: F401 (self-registers)
    from senaite.pfas import print_settings, qc_qualification, regulatory_limits
    from senaite.pfas import egad_store, facility_qc
    from senaite.pfas.qc.rules import get_store as qc_rules_store, get_rules

    reg = config_history.register_store
    reg("print_settings", lambda p, k: print_settings.get_print_settings(p),
        lambda p, k, v: print_settings.save_print_settings(p, v), u"Print & certificate settings")
    reg("qc_qualifiers", lambda p, k: qc_qualification.get_library(p),
        lambda p, k, v: qc_qualification.save_library(p, v), u"QC qualifier wording")
    reg("regulatory_limits", lambda p, k: regulatory_limits.get_store(p),
        lambda p, k, v: regulatory_limits.save_store(p, v), u"Regulatory limits")
    reg("facility_defaults", lambda p, k: facility_qc.get_facility_defaults(p),
        lambda p, k, v: facility_qc.save_facility_defaults(p, v), u"Facility QC defaults")
    reg("edd_profile", lambda p, k: egad_store.get_edd_profiles(p).get(k),
        lambda p, k, v: egad_store.save_edd_profile(p, k, v), u"EDD profile")
    sections = {"lab": (egad_store.get_lab_config, egad_store.save_lab_config),
                "methods": (egad_store.get_method_egad, egad_store.save_method_egad),
                "cas": (egad_store.get_analyte_cas, egad_store.save_analyte_cas),
                "qualifiers": (egad_store.get_qualifier_map, egad_store.save_qualifier_map),
                "qc_types": (egad_store.get_qc_type_map, egad_store.save_qc_type_map),
                "lookups": (egad_store.get_lookups, egad_store.save_lookups)}
    reg("edd_config", lambda p, k: sections[k][0](p), lambda p, k, v: sections[k][1](p, v),
        u"EDD configuration")
    reg("qc_rules", lambda p, k: get_rules(), lambda p, k, v: qc_rules_store().save(v),
        u"QC rules")

    # The quantifying-surrogate link lives on the AnalysisService (the source,
    # D58); each method profile carries a derived copy in surrogate_map. A
    # revert sets the source AND every profile's copy, so they cannot drift.
    def _service(portal, keyword):
        for svc in portal.bika_setup.bika_analysisservices.objectValues():
            if svc.getKeyword() == keyword:
                return svc
        return None

    def get_link(portal, keyword):
        svc = _service(portal, keyword)
        fld = svc.getField("pfas_quant_surrogate") if svc is not None else None
        return {"pfas_quant_surrogate": (fld.get(svc) or "") if fld else ""}

    def set_link(portal, keyword, value):
        svc = _service(portal, keyword)
        if svc is None:
            raise ValueError("no analysis service %r" % keyword)
        sur = (value or {}).get("pfas_quant_surrogate") or ""
        fld = svc.getField("pfas_quant_surrogate")
        config_history.track(None, "analyte_service", keyword,
                             lambda: {"pfas_quant_surrogate": fld.get(svc) or ""},
                             label=u"Quantifying surrogate: %s" % keyword)
        fld.set(svc, sur)
        for mid in method_profile_store.list_method_ids(portal):
            prof = method_profile_store.raw_profile(portal, mid)
            rows = prof.get("surrogate_map") or []
            if any(r.get("analyte") == keyword for r in rows):
                for r in rows:
                    if r.get("analyte") == keyword:
                        r["surrogate_is"] = sur
                method_profile_store.save_profile(portal, mid, prof)

    reg("analyte_service", get_link, set_link, u"Quantifying surrogate")
    # Recorded, reverted in their own editor: settings, analyte_service,
    # logbook_definition, logbook_defs, client_edd, reagent_expiry,
    # facility_unit, weight_set, facility_api_key (redacted).
    for name, title in (("settings", u"Lab setting"),
                        ("logbook_definition", u"Logbook definition"),
                        ("logbook_defs", u"Logbook definitions"), ("client_edd", u"Client EDD settings"),
                        ("reagent_expiry", u"Expiry defaults"), ("facility_unit", u"Facility unit"),
                        ("weight_set", u"Weight set"), ("facility_api_key", u"Sensor API key")):
        config_history.TITLES[name] = title
