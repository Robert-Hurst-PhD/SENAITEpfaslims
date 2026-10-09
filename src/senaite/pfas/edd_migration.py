# -*- coding: utf-8 -*-
"""Move the EDD export's settings out of the retired format-named stores
and into the profiles. This is
the only module that names the retired stores.

    migrate(portal) -> summary dict

From the retired portal store and its singleton config object:
    lab settings     -> every profile's `defaults`
    method settings  -> every profile's `method_codes`
    lookup lists     -> `value_lists` of every profile of that format
    lab-wide CAS / qualifier / QC-type maps: already owned per profile; dropped
Code rows keep their code under `code`. Client, sample and batch
annotations move to the new keys. The retired store, the config object, its
folder and its content type are then removed.

Idempotent: with nothing retired left it changes nothing. Values already
moved are never overwritten by a later run, because the old stores are gone.
Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import json
import logging

logger = logging.getLogger("senaite.pfas.edd_migration")

OLD_PORTAL_KEY = "senaite.pfas.egad"
OLD_CLIENT_KEY = "senaite.pfas.egad_client"
OLD_SAMPLE_TYPE_KEY = "senaite.pfas.egad_sample_type"
OLD_EXPORT_KEY = "senaite.pfas.egad_edd"
OLD_FOLDER, OLD_OBJECT, OLD_TYPE = "pfas_egad_config", "egad_config", "EGADConfig"
OLD_ROW_CODE = "egad_code"
OLD_SECTIONS = (("lab", "lab_json"), ("method_egad", "method_egad_json"),
                ("lookups", "lookups_json"))


def _loads(raw):
    try:
        return json.loads(raw) if raw else None
    except (ValueError, TypeError):
        return None


def _old_sections(portal):
    """{lab, method_egad, lookups} from the config object (the live copy),
    else the older portal store."""
    from zope.annotation.interfaces import IAnnotations
    out = {}
    folder = portal.get(OLD_FOLDER) if hasattr(portal, "get") else None
    obj = folder.get(OLD_OBJECT) if folder is not None else None
    store = IAnnotations(portal).get(OLD_PORTAL_KEY) or {}
    for name, attr in OLD_SECTIONS:
        value = _loads(getattr(obj, attr, None)) if obj is not None else None
        if value is None:
            value = _loads(store.get(name))
        if value is not None:
            out[name] = value
    return out


def _recode(rows):
    """Code rows keep their code under `code`."""
    out = []
    for r in rows or []:
        r = dict(r)
        if OLD_ROW_CODE in r:
            r.setdefault("code", r.pop(OLD_ROW_CODE))
        out.append(r)
    return out


def migrate(portal):
    from zope.annotation.interfaces import IAnnotations
    from senaite.pfas import edd_profiles, edd_store
    summary = {"profiles": [], "clients": 0, "samples": 0, "batches": 0, "removed": []}
    old = _old_sections(portal)
    store = edd_store._store(portal)
    # every saved profile, and the default one if the lab never saved it
    raw = dict(store.items())
    for pid, prof in edd_profiles.seed_profiles().items():
        raw.setdefault(pid, json.dumps(prof))
    for pid in sorted(raw):
        prof = _loads(raw[pid])
        if prof is None:
            continue
        before = json.dumps(prof, sort_keys=True)
        fmt = edd_profiles.format_of(prof)
        prof.setdefault("format", fmt.PROFILE_ID)
        if "lab" in old:
            prof["defaults"] = dict(old["lab"])
        if "method_egad" in old:
            prof["method_codes"] = dict(old["method_egad"])
        if "lookups" in old and fmt.PROFILE_ID == prof.get("format"):
            prof["value_lists"] = dict(old["lookups"])
        for name in ("qualifier_map", "qc_type_map"):
            if name in prof:
                prof[name] = _recode(prof[name])
        seed = fmt.seed_profile()
        for name in ("defaults", "method_codes", "value_lists", "client_fields"):
            prof.setdefault(name, seed[name])
        if json.dumps(prof, sort_keys=True) != before or pid not in store:
            store[pid] = json.dumps(prof)
            summary["profiles"].append(pid)

    _move_clients(portal, summary)
    _move_annotations(portal, summary)

    # the retired stores, object, folder and type
    ann = IAnnotations(portal)
    if OLD_PORTAL_KEY in ann:
        del ann[OLD_PORTAL_KEY]
        summary["removed"].append(OLD_PORTAL_KEY)
    if OLD_FOLDER in portal.objectIds():
        portal.manage_delObjects([OLD_FOLDER])
        summary["removed"].append(OLD_FOLDER)
    types = getattr(portal, "portal_types", None)
    if types is not None and OLD_TYPE in types.objectIds():
        types.manage_delObjects([OLD_TYPE])
        summary["removed"].append(OLD_TYPE)
    if _drop_catalog_mapping(OLD_TYPE):
        summary["removed"].append("catalog mapping " + OLD_TYPE)
    if any(summary[k] for k in ("profiles", "clients", "samples", "batches", "removed")):
        logger.info("EDD export settings moved into profiles: %s", summary)
    return summary


def _drop_catalog_mapping(portal_type):
    """Remove a deleted type from core's catalog mappings. Left behind, the
    record no longer validates (its keys must be existing types) and every
    later set_catalogs() write fails."""
    try:
        from senaite.core.catalog import CATALOG_MAPPINGS_REGISTRY_KEY
        from senaite.core.registry import get_registry_record, set_registry_record
    except ImportError:
        return False
    mapping = dict(get_registry_record(CATALOG_MAPPINGS_REGISTRY_KEY) or {})
    if portal_type not in mapping:
        return False
    mapping.pop(portal_type)
    set_registry_record(CATALOG_MAPPINGS_REGISTRY_KEY, mapping)
    return True


def _move_clients(portal, summary):
    from bika.lims import api
    from zope.annotation.interfaces import IAnnotations
    from senaite.pfas import edd_store
    for b in api.search({"portal_type": "Client"}, "senaite_catalog_client"):
        client = b.getObject()
        ann = IAnnotations(client)
        old = _loads(ann.get(OLD_CLIENT_KEY))
        if old is None:
            continue
        new = edd_store.get_client_settings(client) if edd_store.CLIENT_KEY in ann else {}
        fields = dict(new.get("fields") or {})
        for key in ("project_site", "default_sample_type", "analysis_lab_override"):
            if key in old:
                fields[key] = old[key]
        ann[edd_store.CLIENT_KEY] = json.dumps({
            "edd_enabled": bool(old.get("egad_enabled", new.get("edd_enabled", False))),
            "edd_profile": old.get("edd_profile") or new.get("edd_profile") or edd_store.DEFAULT_PROFILE_ID,
            "per_report_override_default": bool(old.get("per_report_override_default",
                                                        new.get("per_report_override_default", True))),
            "fields": fields})
        del ann[OLD_CLIENT_KEY]
        summary["clients"] += 1


def _move_annotations(portal, summary):
    """A sample's code override and a batch's generated export."""
    from bika.lims import api
    from zope.annotation.interfaces import IAnnotations
    from senaite.pfas import edd_store
    samples = (b.getObject() for b in api.search({"portal_type": "AnalysisRequest"},
                                                  "senaite_catalog_sample"))
    # every batch, wherever it lives (a client's batch is in its folder)
    batches = (b.getObject() for b in api.search({"portal_type": str("Batch")}))
    for objs, old_key, new_key, count in (
            (samples, OLD_SAMPLE_TYPE_KEY, edd_store.SAMPLE_TYPE_KEY, "samples"),
            (batches, OLD_EXPORT_KEY, edd_store.EXPORT_KEY, "batches")):
        for obj in objs:
            ann = IAnnotations(obj)
            if old_key in ann:
                ann.setdefault(new_key, ann[old_key])
                del ann[old_key]
                summary[count] += 1
