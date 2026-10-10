# -*- coding: utf-8 -*-
"""The EDD export's stored settings.

The export is one tool; each delivery format is a PROFILE, and a profile
owns everything about its format:

    columns, aliases          the output columns and their headings
    defaults                  the lab's identity and default field values
    method_codes              per method: test code, prep method, unit codes
    value_lists               the format's valid codes (refreshable)
    qualifier_map, qc_type_map our qualifier / QC type -> the format's code
    analyte_naming            the format's analyte names and code overrides
                              (the CAS itself stays in analyte_reference)
    matrix_map                our sample type -> the format's sample-type code
    client_fields             what a client must give for this format

Storage:
    portal annotation  EDD_PROFILES_KEY  {profile id: json}
    client annotation  CLIENT_KEY        {edd_enabled, edd_profile,
                                          per_report_override_default,
                                          fields: {client field: value}}
    sample annotation  SAMPLE_TYPE_KEY   a sample's sample-type code override
    batch annotation   EXPORT_KEY        the export generated for a batch

Format-specific content (the default profile's seed, its forms and its
refresh) is in edd_profiles. Python 2.7.
"""
from __future__ import absolute_import, print_function, unicode_literals

import copy
import json
import logging

from senaite.pfas import edd_profiles
from senaite.pfas.analyte_reference import get_cas_by_keyword as _get_cas_by_keyword

logger = logging.getLogger("senaite.pfas.edd_store")

EDD_PROFILES_KEY = "senaite.pfas.edd_profiles"
CLIENT_KEY = "senaite.pfas.edd_client"
SAMPLE_TYPE_KEY = "senaite.pfas.edd_sample_type"
EXPORT_KEY = "senaite.pfas.edd_export"
DEFAULT_PROFILE_ID = edd_profiles.DEFAULT_PROFILE_ID

DEFAULT_CLIENT = {
    "edd_enabled": False,
    "edd_profile": DEFAULT_PROFILE_ID,
    "per_report_override_default": True,
    "fields": {},
}


# ── Profiles ──────────────────────────────────────────────────────────────────

def _store(portal, key=EDD_PROFILES_KEY):
    from zope.annotation.interfaces import IAnnotations
    from persistent.mapping import PersistentMapping
    ann = IAnnotations(portal)
    if key not in ann:
        ann[key] = PersistentMapping()
    return ann[key]


def get_edd_profiles(portal):
    """{profile id: profile}; the default profile is always present (its
    seed when the lab has none saved)."""
    out = {}
    for k, raw in list(_store(portal).items()):
        try:
            out[k] = json.loads(raw)
        except (ValueError, TypeError):
            continue
    for pid, prof in edd_profiles.seed_profiles().items():
        out.setdefault(pid, prof)
    return out


def get_profile(portal, profile_id):
    profs = get_edd_profiles(portal)
    return profs.get(profile_id) or profs[DEFAULT_PROFILE_ID]


def section(profile, name):
    """A profile's section; one it does not carry comes from its format's
    seed (a profile made before the section existed)."""
    value = (profile or {}).get(name)
    if value is None:
        value = edd_profiles.format_of(profile).seed_profile().get(name)
    return copy.deepcopy(value)


def save_edd_profile(portal, profile_id, data):
    try:   # change history (R1)
        from senaite.pfas import config_history
        config_history.track(portal, 'edd_profile', profile_id,
                             lambda: get_edd_profiles(portal).get(profile_id),
                             label=u"EDD profile %s" % profile_id)
    except Exception:
        pass
    _store(portal)[profile_id] = json.dumps(data)


def save_profile_section(portal, profile_id, name, value):
    prof = get_profile(portal, profile_id)
    prof[name] = value
    save_edd_profile(portal, profile_id, prof)


def clone_edd_profile(portal, source_id, new_id, new_name):
    src = get_profile(portal, source_id)
    new = copy.deepcopy(src)
    new["name"] = new_name or new_id
    new["base"] = source_id
    new["format"] = edd_profiles.format_of(src).PROFILE_ID
    save_edd_profile(portal, new_id, new)
    return new


def get_edd_profile_for_client(portal, client_cfg):
    """(profile id, profile) the client exports with (the default profile
    when it names none or one that no longer exists)."""
    pid = (client_cfg or {}).get("edd_profile") or DEFAULT_PROFILE_ID
    profs = get_edd_profiles(portal)
    if pid not in profs:
        pid = DEFAULT_PROFILE_ID
    return pid, profs[pid]


def profile_qualifier_dict(profile):
    """{our qualifier: the format's code}."""
    return dict((r["our_qualifier"], r.get("code", "")) for r in section(profile, "qualifier_map") or [])


def profile_qc_type_dict(profile):
    """{our QC type: the format's code}."""
    return dict((r["our_qc_type"], r.get("code", "")) for r in section(profile, "qc_type_map") or [])


def profile_tic_keywords(profile):
    """The analytes this profile reports as tentatively identified (TIC):
    only those the lab ticks (EDD config > Analytes). A hard-coded list coded
    calibrated EPA 537.1 targets TIC."""
    return frozenset(kw for kw, nm in (section(profile, "analyte_naming") or {}).items()
                     if (nm or {}).get("tic"))


def profile_analyte_cas(profile):
    """{keyword: {cas_no, parameter_name, override_note}}: the profile's
    analyte naming over the master CAS. A profile that names analytes covers
    exactly those (an unnamed one exports with no code, which the row check
    blocks); one with no naming at all covers every analyte the library
    knows, each with the format's "verify the name" note."""
    master = _get_cas_by_keyword(dashed=False)
    out = {}
    if not (profile or {}).get("analyte_naming"):
        note = getattr(edd_profiles.format_of(profile), "UNNAMED_NOTE", u"")
        out = dict((kw, {"cas_no": cas or "", "parameter_name": "", "override_note": note})
                   for kw, cas in master.items())
    for kw, nm in (section(profile, "analyte_naming") or {}).items():
        out[kw] = {"cas_no": nm.get("code_override") or master.get(kw, ""),
                   "parameter_name": nm.get("parameter_name", ""),
                   "override_note": nm.get("note", "")}
    return out


def method_codes(profile, method_id):
    """The profile's codes for a method, or None when it has none for it
    (the export then refuses the method; another method's codes would
    report the results under the wrong test)."""
    codes = section(profile, "method_codes") or {}
    return codes.get(method_id) or None


def refresh_value_lists(portal, profile_id, upload_bytes):
    """Re-read the format's value lists from the state's file into one
    profile. {"updated", "errors"}."""
    prof = get_profile(portal, profile_id)
    fmt = edd_profiles.format_of(prof)
    lists, result = fmt.refresh_from_upload(section(prof, "value_lists") or {}, upload_bytes)
    if result.get("updated"):
        prof["value_lists"] = lists
        save_edd_profile(portal, profile_id, prof)
    return result


# ── Clients ───────────────────────────────────────────────────────────────────

def get_client_settings(client_obj):
    """A client's EDD settings ({edd_enabled, edd_profile,
    per_report_override_default, fields})."""
    try:
        from zope.annotation.interfaces import IAnnotations
        raw = IAnnotations(client_obj).get(CLIENT_KEY)
        if raw:
            cfg = dict(copy.deepcopy(DEFAULT_CLIENT), **json.loads(raw))
            cfg["fields"] = dict(cfg.get("fields") or {})
            return cfg
    except Exception:
        pass
    return copy.deepcopy(DEFAULT_CLIENT)


def save_client_settings(client_obj, data):
    try:   # change history (R1)
        from senaite.pfas import config_history
        config_history.track(None, 'client_edd', client_obj.getId(),
                             lambda: get_client_settings(client_obj),
                             label=u"Client EDD settings: %s" % client_obj.Title())
    except Exception:
        pass
    try:
        from zope.annotation.interfaces import IAnnotations
        IAnnotations(client_obj)[CLIENT_KEY] = json.dumps(data)
    except Exception as exc:
        logger.error("Cannot save client EDD settings: %s", exc)


def client_field(cfg, key, default=u""):
    return ((cfg or {}).get("fields") or {}).get(key) or default


def is_edd_enabled(client_obj):
    return bool(get_client_settings(client_obj).get("edd_enabled"))


# ── Seed on install ───────────────────────────────────────────────────────────

def seed_defaults(portal):
    """The default profile saved when the lab has none. Idempotent: never
    overwrites a saved profile."""
    store = _store(portal)
    for pid, prof in edd_profiles.seed_profiles().items():
        if pid not in store:
            store[pid] = json.dumps(prof)
            logger.info("EDD export: seeded profile %s", pid)
