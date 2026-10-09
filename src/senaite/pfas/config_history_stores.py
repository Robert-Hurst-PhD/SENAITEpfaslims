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
    from senaite.pfas import edd_store, facility_qc
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
    # every EDD setting is a profile's; history
    # recorded before the move ("edd_config" rows) stays readable as recorded
    reg("edd_profile", lambda p, k: edd_store.get_edd_profiles(p).get(k),
        lambda p, k, v: edd_store.save_edd_profile(p, k, v), u"EDD profile")
    reg("qc_rules", lambda p, k: get_rules(), lambda p, k, v: qc_rules_store().save(v),
        u"QC rules")
    from senaite.pfas import project_specs
    reg("project_specs", lambda p, k: project_specs.get_specs(project_specs.project_by_id(p, k)),
        lambda p, k, v: project_specs.save_for_project(p, k, v), u"Project specs")

    # The service's pfas_quant_surrogate is only the SUGGESTED surrogate shown
    # when a native first joins a method. Each method's
    # own surrogate_map owns the link and is recorded as method_profile.
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
        fld = svc.getField("pfas_quant_surrogate")
        config_history.track(None, "analyte_service", keyword,
                             lambda: {"pfas_quant_surrogate": fld.get(svc) or ""},
                             label=u"Suggested surrogate: %s" % keyword)
        fld.set(svc, (value or {}).get("pfas_quant_surrogate") or "")

    reg("analyte_service", get_link, set_link, u"Suggested surrogate")
    # Recorded, reverted in their own editor: settings, analyte_service,
    # logbook_definition, logbook_defs, client_edd, reagent_expiry,
    # facility_unit, weight_set, facility_api_key (redacted).
    for name, title in (("settings", u"Lab setting"),
                        ("logbook_definition", u"Logbook definition"),
                        ("logbook_defs", u"Logbook definitions"), ("client_edd", u"Client EDD settings"),
                        ("reagent_expiry", u"Expiry defaults"), ("facility_unit", u"Facility unit"),
                        ("weight_set", u"Weight set"), ("facility_api_key", u"Sensor API key"),
                        # : equipment types and per-instrument settings
                        ("equipment_type", u"Equipment type"), ("equipment", u"Equipment settings"),
                        ("site_language", u"Site language"),
                        # : designed documents (labels first)
                        ("document_template", u"Document template"),
                        # : staff (Lab Contact, title, credentials,
                        # sign rights, signature fingerprint), the Director
                        ("staff", u"Lab staff"), ("lab_director", u"Laboratory Director"),
                        ("badge", u"Badge")):
        config_history.TITLES[name] = title
