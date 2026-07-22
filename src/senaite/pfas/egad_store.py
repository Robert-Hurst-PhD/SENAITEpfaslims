# -*- coding: utf-8 -*-
"""
EGAD EDD Config Store — ZODB-backed, four-scope configuration.

Python 2.7 compatible.  No f-strings, no pathlib, no annotations.

Storage layout (portal annotations):
  PFAS_EGAD_KEY → PersistentMapping
      "lab"           → json_string  (lab-global settings)
      "method_egad"   → json_string  (per-method: TEST code, units, prep)
      "analyte_cas"   → json_string  (analyte keyword → CAS_NO + PARAMETER_NAME)
      "qualifier_map" → json_string  (our qualifier label → EGAD code)
      "qc_type_map"   → json_string  (our QC type label → EGAD code)
      "lookups"       → json_string  (refreshable lookup value lists)

Per-client settings live in IAnnotations(client_object)["senaite.pfas.egad_client"]
as a json_string:
  {"egad_enabled": bool, "project_site": str, "default_sample_type": str,
   "analysis_lab_override": str, "per_report_override": bool}

The Python 3 pipeline worker (pfas_pipeline/egad_edd.py) reads CAS data from
the exported analyte_cas.json when available. Base analyte CAS is owned by
analyte_reference.NATIVE_ANALYTES (single source of truth); DEFAULT_ANALYTE_CAS
is the EGAD *overlay* built over it (Maine DEP codes, parameter names, notes).
"""
from __future__ import absolute_import, print_function, unicode_literals

import copy
import json
import logging

logger = logging.getLogger("senaite.pfas.egad_store")

PFAS_EGAD_KEY = "senaite.pfas.egad"
PFAS_EGAD_CLIENT_KEY = "senaite.pfas.egad_client"


# ── Default lab-global settings ───────────────────────────────────────────────

DEFAULT_LAB = {
    "analysis_lab_code": "",
    "default_prep_method": "SW3535",
    "default_sample_collection_method": "LFS",
    "default_treatment_status": "N",
    "default_parameter_filtered": "U",
    "sdg_prefix": "",
    "sdg_format": "{prefix}{batch_id}",
    "sampled_by": "",
}

# ── Default method-specific settings ─────────────────────────────────────────

DEFAULT_METHOD_EGAD = {
    "EPA_537_1": {
        "method_id": "EPA_537_1",
        "test_code": "E537.1",
        "prep_method": "SW3535",
        "units_water": "NG/L",
        "units_solid": "NG/KG",
    },
    "EPA_1633A": {
        "method_id": "EPA_1633A",
        "test_code": "E1633_DR",
        "prep_method": "SW3535",
        "units_water": "NG/L",
        "units_solid": "NG/KG",
    },
    "FDA_32PFAS": {
        "method_id": "FDA_32PFAS",
        "test_code": "USFDA-PFAS",
        "prep_method": "SW3535",
        "units_water": "NG/L",
        "units_solid": "NG/KG",
    },
}

# ── Analyte CAS: EGAD overlay over the single-source master ───────────────────
# Base CAS is OWNED by analyte_reference.NATIVE_ANALYTES (single source of truth)
# and DERIVED here undashed — it is NOT duplicated. This overlay carries only the
# genuinely EGAD-specific data the master does not hold:
#   * parameter_name — Maine EGAD parameter naming (always local)
#   * override_note  — EGAD submission notes (always local)
#   * cas_override   — where EGAD uses a Maine DEP##### code instead of the CAS,
#                      or the master has no usable CAS (PLACEHOLDER/empty)
# DEFAULT_ANALYTE_CAS is BUILT from overlay + master, preserving the exact
# {keyword: {cas_no, parameter_name, override_note}} shape. SENAITE core's
# AnalysisService has no CAS field in 2.6, so CAS lives here keyed by the core
# service keyword (the join to core).
from senaite.pfas.analyte_reference import get_cas_by_keyword as _get_cas_by_keyword

_EGAD_ANALYTE_OVERLAY = {
    "9ClPF3ONS":   {"parameter_name": "9CL-PF3ONS_A",   "override_note": ""},
    "11ClPF3OUdS": {"parameter_name": "11CL-PF3OUDS_A",  "override_note": ""},
    "FOSA":        {"parameter_name": "PFOSA",           "override_note": ""},
    "4:2FTS":      {"parameter_name": "4:2 FTS_A",       "override_note": ""},
    "6:2FTS":      {"parameter_name": "6:2 FTS_A",       "override_note": ""},
    "8:2FTS":      {"parameter_name": "8:2 FTS_A",       "override_note": ""},
    "10:2FTS":     {"parameter_name": "10:2 FTS_A",      "override_note": ""},
    "PFBA":        {"parameter_name": "PFBA_A",          "override_note": ""},
    "PFPeA":       {"parameter_name": "PFPEA_A",         "override_note": ""},
    "PFHxA":       {"parameter_name": "PFHXA_A",         "override_note": ""},
    "PFHpA":       {"parameter_name": "PFHPA_A",         "override_note": ""},
    "PFOA":        {"parameter_name": "PFOA_A",          "override_note": ""},
    "PFNA":        {"parameter_name": "PFNA_A",          "override_note": ""},
    "PFDA":        {"parameter_name": "PFDA_A",          "override_note": ""},
    "PFUDA":       {"parameter_name": "PFUNDA_A",        "override_note": ""},
    "PFDoA":       {"parameter_name": "PFDOA_A",         "override_note": ""},
    "PFTrDA":      {"parameter_name": "PFTRIA_A",        "override_note": ""},
    "PFTeDA":      {"parameter_name": "PFTEA_A",         "override_note": ""},
    "PFHxDA":      {"parameter_name": "PFHXDA_A",        "override_note": ""},
    "PFODA":       {"parameter_name": "PFODA_A",         "override_note": ""},
    "GenX":        {"parameter_name": "HFPO-DA_A",       "override_note": ""},
    "DONA":        {"parameter_name": "ADONA_A",         "override_note": ""},
    "PFBS":        {"parameter_name": "PFBS_A",          "override_note": ""},
    "PFPeS":       {"parameter_name": "PFPES_A",         "override_note": ""},
    "PFHxS":       {"parameter_name": "PFHXS_A_L",  "override_note": "linear isomer",   "cas_override": "DEP18024"},
    "br-PFHxS":    {"parameter_name": "PFHXS_A_BR", "override_note": "branched isomer", "cas_override": "DEP18023"},
    "PFHpS":       {"parameter_name": "PFHPS_A",         "override_note": ""},
    "PFOS":        {"parameter_name": "PFOS_A_L",   "override_note": "linear isomer",   "cas_override": "DEP18026"},
    "br-PFOS":     {"parameter_name": "PFOS_A_BR",  "override_note": "branched isomer", "cas_override": "DEP18025"},
    "PFNS":        {"parameter_name": "PFNS_A",          "override_note": ""},
    "PFDS":        {"parameter_name": "PFDS_A",          "override_note": ""},
    "PFUnDS":      {"parameter_name": "PFUNDS_A",        "override_note": "CAS 749-786-16-1; verify against Maine EGAD CAS_LUP before EDD submission"},
    "PFDoS":       {"parameter_name": "PFDOS_A",         "override_note": ""},
    "PFTrDS":      {"parameter_name": "PFTRDS_A",   "override_note": "CAS 791-563-89-8", "cas_override": "791563898"},
}


def _build_default_analyte_cas():
    """Layer the EGAD overlay over the single-source master CAS (undashed),
    preserving the {keyword: {cas_no, parameter_name, override_note}} shape."""
    master = _get_cas_by_keyword(dashed=False)   # {keyword: undashed CAS}
    out = {}
    for kw, ov in _EGAD_ANALYTE_OVERLAY.items():
        cas = ov.get("cas_override") or master.get(kw, "")
        out[kw] = {
            "cas_no": cas,
            "parameter_name": ov["parameter_name"],
            "override_note": ov["override_note"],
        }
    return out


DEFAULT_ANALYTE_CAS = _build_default_analyte_cas()


# ── EDD format profiles ───────────────────────────────────────────────────────
# The EDD engine is no longer Maine-EGAD-only: an EDD PROFILE controls the
# column set/order (a subset of the Maine superset the builder can emit),
# optional column heading aliases, and the SampleType→SAMPLE_TYPE-code map.
# "maine_egad" is the seeded base; clone it into sub-profiles (or other state
# programs) and associate a profile per client (client cfg `edd_profile`).

EDD_PROFILES_KEY = "senaite.pfas.edd_profiles"

# Standard Maine EGAD sample-type codes for the obvious environmental matrices.
# Food/feed matrices have NO Maine code — left unmapped on purpose (per-AR
# override or profile edit; never fabricated).
_DEFAULT_MATRIX_MAP = {
    "Drinking Water": "DW", "Groundwater": "GW", "Surface Water": "SW",
    "Wastewater": "WW", "Soil": "SO", "Sediment": "SE",
    "Landfill Leachate": "LL", "Biosolid": "SO",
}


def _default_analyte_naming():
    """State-specific analyte naming/coding, derived from the Maine EGAD overlay.

    Shape: {keyword: {parameter_name, code_override, note}}.  The REAL CAS stays
    single-sourced in analyte_reference; a state profile only carries its own
    parameter name and (where it uses one) a state-specific code override
    (Maine DEP#####).  Reference, not duplicate — §3."""
    out = {}
    for kw, ov in _EGAD_ANALYTE_OVERLAY.items():
        out[kw] = {
            "parameter_name": ov.get("parameter_name", ""),
            "code_override": ov.get("cas_override", ""),
            "note": ov.get("override_note", ""),
        }
    return out


def _default_edd_profile():
    from senaite.pfas.egad_builder import EDD_COLUMNS
    return {
        "name": "Maine EGAD (default)",
        "base": "maine_egad",
        "state": "ME",
        "columns": list(EDD_COLUMNS),
        "aliases": {},              # {column: replacement heading}
        "matrix_map": dict(_DEFAULT_MATRIX_MAP),
        # State-owned vocabulary (full untie from Maine — D63). Seeded with the
        # historical Maine lab-global maps so Maine output is byte-identical;
        # other state profiles override these.
        "qualifier_map": copy.deepcopy(DEFAULT_QUALIFIER_MAP),
        "qc_type_map": copy.deepcopy(DEFAULT_QC_TYPE_MAP),
        "analyte_naming": _default_analyte_naming(),
        "notes": "Seeded Maine DEP EGAD format. Clone to create sub-profiles "
                 "or other state programs.",
    }


# Keys a state profile must carry; filled onto older saved profiles so
# existing installs gain the state vocabulary without losing edited data.
_PROFILE_VOCAB_KEYS = ("state", "qualifier_map", "qc_type_map",
                       "analyte_naming")


def _analyte_cas_to_naming(portal):
    """Convert the LIVE lab-global analyte_cas into the analyte_naming shape,
    reconstructing code_override faithfully: a stored cas_no that differs from
    the single-source master CAS is a state code override (Maine DEP#####);
    one that equals the master is just the real CAS, so no override."""
    live = get_analyte_cas(portal)
    master = _get_cas_by_keyword(dashed=False)
    naming = {}
    for kw, ent in live.items():
        cas_no = (ent.get("cas_no") or "")
        code_override = "" if cas_no == master.get(kw, "") else cas_no
        naming[kw] = {
            "parameter_name": ent.get("parameter_name", ""),
            "code_override": code_override,
            "note": ent.get("override_note", ""),
        }
    return naming


def _ensure_profile_vocab(portal, profile_id, profile):
    """Fill any missing D63 state-vocab key on a profile from the LIVE lab-global
    maps — so an existing install's customized qualifier/QC/CAS data migrates
    without loss (pre-D63 every profile used the lab-global maps). Returns True
    if anything was filled. Never overwrites keys already present."""
    changed = False
    if "state" not in profile:
        profile["state"] = "ME" if profile_id == "maine_egad" else ""
        changed = True
    if "qualifier_map" not in profile:
        profile["qualifier_map"] = copy.deepcopy(get_qualifier_map(portal))
        changed = True
    if "qc_type_map" not in profile:
        profile["qc_type_map"] = copy.deepcopy(get_qc_type_map(portal))
        changed = True
    if "analyte_naming" not in profile:
        profile["analyte_naming"] = _analyte_cas_to_naming(portal)
        changed = True
    return changed


def get_edd_profiles(portal):
    """{profile_id: profile-dict}; 'maine_egad' is always present.

    Older saved profiles predate the state vocabulary (D63); their missing keys
    are filled from the live lab-global maps on read so callers always see a
    complete state profile even before the upgrade step persists them."""
    store = _get_store_generic(portal, EDD_PROFILES_KEY)
    out = {}
    for k in list(store.keys()):
        try:
            prof = json.loads(store[k])
        except (ValueError, TypeError):
            continue
        _ensure_profile_vocab(portal, k, prof)
        out[k] = prof
    if "maine_egad" not in out:
        prof = _default_edd_profile()
        # Prefer the live lab-global maps (may be customized) over the DEFAULT
        # vocab baked into the profile shape.
        for key in ("state", "qualifier_map", "qc_type_map", "analyte_naming"):
            prof.pop(key, None)
        _ensure_profile_vocab(portal, "maine_egad", prof)
        out["maine_egad"] = prof
    return out


def get_profile_qualifier_dict(profile):
    """{our_qualifier: state_code} for a state profile (D63 profile-scoped)."""
    rows = (profile or {}).get("qualifier_map") or DEFAULT_QUALIFIER_MAP
    return {r["our_qualifier"]: r.get("egad_code", r.get("state_code", ""))
            for r in rows}


def get_profile_qc_type_dict(profile):
    """{our_qc_type: state_code} for a state profile (D63 profile-scoped)."""
    rows = (profile or {}).get("qc_type_map") or DEFAULT_QC_TYPE_MAP
    return {r["our_qc_type"]: r.get("egad_code", r.get("state_code", ""))
            for r in rows}


def get_profile_analyte_cas(profile):
    """Build {keyword: {cas_no, parameter_name, override_note}} for a state
    profile, layering its analyte_naming (state parameter name + state code
    override) over the single-source master CAS.  Same shape as
    get_analyte_cas() so the builder consumes it unchanged."""
    master = _get_cas_by_keyword(dashed=False)
    naming = (profile or {}).get("analyte_naming") or {}
    out = {}
    for kw, nm in naming.items():
        cas = nm.get("code_override") or master.get(kw, "")
        out[kw] = {
            "cas_no": cas,
            "parameter_name": nm.get("parameter_name", ""),
            "override_note": nm.get("note", ""),
        }
    return out


def migrate_state_profile_vocab(portal):
    """Durably fold the historical Maine lab-global maps into saved profiles.

    Idempotent: only fills profiles missing the D63 state-vocab keys; never
    overwrites edited data.  Ensures maine_egad exists and is persisted."""
    store = _get_store_generic(portal, EDD_PROFILES_KEY)
    migrated = []
    for k in list(store.keys()):
        try:
            prof = json.loads(store[k])
        except (ValueError, TypeError):
            continue
        if _ensure_profile_vocab(portal, k, prof):
            store[k] = json.dumps(prof)
            migrated.append(k)
    if "maine_egad" not in store:
        prof = _default_edd_profile()
        for key in ("state", "qualifier_map", "qc_type_map", "analyte_naming"):
            prof.pop(key, None)
        _ensure_profile_vocab(portal, "maine_egad", prof)
        store["maine_egad"] = json.dumps(prof)
        migrated.append("maine_egad")
    if migrated:
        logger.info("D63: state-vocab backfilled onto EDD profiles: %s",
                    ", ".join(migrated))
    return migrated


def save_edd_profile(portal, profile_id, data):
    store = _get_store_generic(portal, EDD_PROFILES_KEY)
    store[profile_id] = json.dumps(data)


def clone_edd_profile(portal, source_id, new_id, new_name):
    profs = get_edd_profiles(portal)
    src = profs.get(source_id) or _default_edd_profile()
    new = copy.deepcopy(src)
    new["name"] = new_name or new_id
    new["base"] = source_id
    save_edd_profile(portal, new_id, new)
    return new


def get_edd_profile_for_client(portal, client_cfg):
    """Resolve the client's EDD profile (falls back to maine_egad)."""
    pid = (client_cfg or {}).get("edd_profile") or "maine_egad"
    profs = get_edd_profiles(portal)
    return pid, (profs.get(pid) or profs["maine_egad"])


def _get_store_generic(portal, key):
    from zope.annotation.interfaces import IAnnotations
    from persistent.mapping import PersistentMapping
    ann = IAnnotations(portal)
    if key not in ann:
        ann[key] = PersistentMapping()
    return ann[key]

# ── Default qualifier mapping ─────────────────────────────────────────────────

DEFAULT_QUALIFIER_MAP = [
    {"our_qualifier": "N.D.",   "egad_code": "U",    "description": "Not detected"},
    {"our_qualifier": "< LOD",  "egad_code": "U",    "description": "Below LOD"},
    {"our_qualifier": "BLoQ",   "egad_code": "J",    "description": "Below LOQ — estimated"},
    {"our_qualifier": "N.C.",   "egad_code": "NC",   "description": "Not confirmed"},
    {"our_qualifier": "EMPC",   "egad_code": "EMPC", "description": "Estimated max possible conc."},
    {"our_qualifier": "B",      "egad_code": "B",    "description": "Found in method blank"},
    {"our_qualifier": "J",      "egad_code": "J",    "description": "Estimated value"},
    {"our_qualifier": "UJ",     "egad_code": "UJ",   "description": "Non-detect + estimated RL"},
    {"our_qualifier": "JB",     "egad_code": "JB",   "description": "Estimated + in blank"},
    {"our_qualifier": "TIC",    "egad_code": "N",    "description": "Tentatively identified"},
    {"our_qualifier": "*",      "egad_code": "*",    "description": "QC outside control limits"},
    {"our_qualifier": "J*",     "egad_code": "J*",   "description": "Estimated + QC out of limits"},
]

# ── Default QC type mapping ───────────────────────────────────────────────────

DEFAULT_QC_TYPE_MAP = [
    {"our_qc_type": "MB",     "egad_code": "LB",   "description": "Method Blank"},
    {"our_qc_type": "LB",     "egad_code": "LB",   "description": "Lab Blank"},
    {"our_qc_type": "LFSM",   "egad_code": "MS",   "description": "Lab Fortified Sample Matrix"},
    {"our_qc_type": "LFSMD",  "egad_code": "MSD",  "description": "LFSM Duplicate"},
    {"our_qc_type": "CCV",    "egad_code": "CCC",  "description": "Continuing Calibration Verification"},
    {"our_qc_type": "LCS",    "egad_code": "LCS",  "description": "Lab Control Sample"},
    {"our_qc_type": "LCSD",   "egad_code": "LCSD", "description": "LCS Duplicate"},
    {"our_qc_type": "Dup",    "egad_code": "L",    "description": "Lab Duplicate"},
    {"our_qc_type": "DUP",    "egad_code": "L",    "description": "Lab Duplicate"},
    {"our_qc_type": "FD",     "egad_code": "D",    "description": "Field Duplicate"},
    {"our_qc_type": "TB",     "egad_code": "TB",   "description": "Trip Blank"},
    {"our_qc_type": "FB",     "egad_code": "FB",   "description": "Field Blank"},
    {"our_qc_type": "EB",     "egad_code": "EB",   "description": "Equipment Blank"},
    {"our_qc_type": "IB",     "egad_code": "IB",   "description": "Instrument Blank"},
    {"our_qc_type": "CCB",    "egad_code": "CCB",  "description": "Continuing Calibration Blank"},
    {"our_qc_type": "Normal", "egad_code": "NA",   "description": "Normal environmental sample"},
    {"our_qc_type": "NA",     "egad_code": "NA",   "description": "Normal environmental sample"},
]

# ── Default refreshable lookups (valid code lists from EGAD_Lookup_Tables.xlsx)

DEFAULT_LOOKUPS = {
    "concentration_qualifiers": [
        "U", "J", "B", "UJ", "JB", "J*", "B*", "BE", "BT", "BL", "BPJ",
        "EMPC", "J/EMPC", "B/EMPC", "T", "T/EMPC", "NC", "NAN", "NQ",
        "N", "E", "E*", "D", "G", "JG", "*", "*/EMPC", "R", "P", "C",
        "MI", "LQV", "UH", "UJH", "UT", "SA", "FAIL", "PASS",
        "UH", "LT", "L", "S", "K", "TR", "EH", "H", "MO", "MH",
        "DQE", "DQG", "PO", "SP", "PK", "MD", "MDO",
    ],
    "qc_types": [
        "NA", "LB", "MS", "MSD", "L", "LCS", "LCSD", "D",
        "CCC", "CCB", "EB", "FB", "IB", "TB", "SWB", "UNK",
    ],
    "sample_types": [
        "GW", "SW", "AQ", "SL", "SD", "SU", "SUL", "SUU",
        "MEA", "MLK", "EG", "FE", "MU", "SF", "SOF",
        "FI", "CP", "CH", "CO", "FR", "GR", "GRS", "LG", "NRV", "RV",
        "V", "GZ", "G", "HT", "HP", "KD", "LV", "MR", "HM",
        "MA", "MPS", "HN", "HR", "O", "TO", "WH", "WWHG", "WS", "SK",
        "MTB", "BC", "A", "OA", "IA", "PO", "PR", "WW", "L",
        "PW", "SR", "SNW", "RN", "U", "W", "WP", "WC",
        "BD", "AL", "EA", "PP", "MI", "FP", "SLD", "TS", "AS", "BA", "FA",
        "N", "ASP", "BM", "CAR", "CON", "FBQ", "FI", "FS", "FHTW",
        "HSG", "LFG", "LD", "LQC", "MC", "AT", "SWS", "SSG", "GS",
        "HM", "HP", "MPS", "HN", "HR",
    ],
    "units": [
        "NG/L", "NG/KG", "NG/G", "NG/ML", "NG/M3", "NG/MG",
        "NG/PUF", "NG/PUF_XAD", "NG/QFF", "UG/L", "UG/KG", "UG/G",
        "MG/KG", "MG/L", "PG/L", "PG/G", "PG/ML", "PG/M3",
    ],
    "analysis_labs": [],  # populated from ANALYSIS_LAB_LUP on import
    "tests": [
        "E537.1", "E537", "E537M", "E1633_DR", "USFDA-PFAS",
        "MLA-060", "MLA-041", "MLA-043", "MLA-076", "VAL-PFAS",
    ],
    "prep_methods": ["SW3535", "METHOD"],
    "sample_collection_methods": ["LFS", "NA", "LFF", "LFP"],
    "sample_locations": ["NA", "PU", "PR"],
    "treatment_statuses": ["N", "T", "U", "NA"],
    "last_refresh": "",
    "last_refresh_filename": "",
}

# ── Default per-client settings ───────────────────────────────────────────────

DEFAULT_CLIENT_EGAD = {
    "egad_enabled": False,
    "project_site": "",
    "default_sample_type": "GW",
    "edd_profile": "maine_egad",   # which EDD format profile this client uses
    "analysis_lab_override": "",
    "per_report_override_default": True,
}


# ── ZODB store helpers ────────────────────────────────────────────────────────

def _get_store(portal):
    from zope.annotation.interfaces import IAnnotations
    from persistent.mapping import PersistentMapping
    annotations = IAnnotations(portal)
    if PFAS_EGAD_KEY not in annotations:
        annotations[PFAS_EGAD_KEY] = PersistentMapping()
    return annotations[PFAS_EGAD_KEY]


def _load(store, key, default):
    raw = store.get(key)
    if raw is None:
        return copy.deepcopy(default)
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        logger.warning("Corrupt EGAD config JSON for key %s; using default", key)
        return copy.deepcopy(default)


def _save(store, key, data):
    store[key] = json.dumps(data)


def _get_egad_singleton(portal):
    """Return the EGADConfig Dexterity object, or None if not yet migrated."""
    folder = portal.get("pfas_egad_config")
    if folder is None:
        return None
    return folder.get("egad_config")


# ── Lab-global config ─────────────────────────────────────────────────────────

def get_lab_config(portal):
    obj = _get_egad_singleton(portal)
    if obj is not None:
        raw = getattr(obj, "lab_json", None)
        if raw:
            try:
                saved = json.loads(raw)
                for k, v in DEFAULT_LAB.items():
                    if k not in saved:
                        saved[k] = v
                return saved
            except (ValueError, TypeError):
                logger.warning("Corrupt EGAD lab_json in Dexterity; using default")
        return copy.deepcopy(DEFAULT_LAB)
    # Annotation fallback
    store = _get_store(portal)
    saved = _load(store, "lab", DEFAULT_LAB)
    for k, v in DEFAULT_LAB.items():
        if k not in saved:
            saved[k] = v
    return saved


def save_lab_config(portal, data):
    obj = _get_egad_singleton(portal)
    if obj is not None:
        obj.lab_json = json.dumps(data)
        try:
            obj.reindexObject()
        except Exception:
            pass
        return
    store = _get_store(portal)
    _save(store, "lab", data)


# ── Method EGAD settings ──────────────────────────────────────────────────────

def get_method_egad(portal):
    obj = _get_egad_singleton(portal)
    if obj is not None:
        raw = getattr(obj, "method_egad_json", None)
        if raw:
            try:
                saved = json.loads(raw)
                for mid, defaults in DEFAULT_METHOD_EGAD.items():
                    if mid not in saved:
                        saved[mid] = copy.deepcopy(defaults)
                    else:
                        for k, v in defaults.items():
                            if k not in saved[mid]:
                                saved[mid][k] = v
                return saved
            except (ValueError, TypeError):
                logger.warning("Corrupt EGAD method_egad_json in Dexterity; using default")
        return copy.deepcopy(DEFAULT_METHOD_EGAD)
    # Annotation fallback
    store = _get_store(portal)
    saved = _load(store, "method_egad", DEFAULT_METHOD_EGAD)
    for mid, defaults in DEFAULT_METHOD_EGAD.items():
        if mid not in saved:
            saved[mid] = copy.deepcopy(defaults)
        else:
            for k, v in defaults.items():
                if k not in saved[mid]:
                    saved[mid][k] = v
    return saved


def save_method_egad(portal, data):
    obj = _get_egad_singleton(portal)
    if obj is not None:
        obj.method_egad_json = json.dumps(data)
        try:
            obj.reindexObject()
        except Exception:
            pass
        return
    store = _get_store(portal)
    _save(store, "method_egad", data)


# ── Analyte CAS mapping ───────────────────────────────────────────────────────

def get_analyte_cas(portal):
    obj = _get_egad_singleton(portal)
    if obj is not None:
        raw = getattr(obj, "analyte_cas_json", None)
        if raw:
            try:
                saved = json.loads(raw)
                for kw, defaults in DEFAULT_ANALYTE_CAS.items():
                    if kw not in saved:
                        saved[kw] = copy.deepcopy(defaults)
                    elif not saved[kw].get("cas_no") and defaults.get("cas_no"):
                        # Fill in cas_no if previously blank and now has a default
                        saved[kw]["cas_no"] = defaults["cas_no"]
                        if not saved[kw].get("parameter_name") and defaults.get("parameter_name"):
                            saved[kw]["parameter_name"] = defaults["parameter_name"]
                        if not saved[kw].get("override_note") and defaults.get("override_note"):
                            saved[kw]["override_note"] = defaults["override_note"]
                return saved
            except (ValueError, TypeError):
                logger.warning("Corrupt EGAD analyte_cas_json in Dexterity; using default")
        return copy.deepcopy(DEFAULT_ANALYTE_CAS)
    # Annotation fallback
    store = _get_store(portal)
    saved = _load(store, "analyte_cas", DEFAULT_ANALYTE_CAS)
    for kw, defaults in DEFAULT_ANALYTE_CAS.items():
        if kw not in saved:
            saved[kw] = copy.deepcopy(defaults)
        elif not saved[kw].get("cas_no") and defaults.get("cas_no"):
            # Fill in cas_no if previously blank and now has a default
            saved[kw]["cas_no"] = defaults["cas_no"]
            if not saved[kw].get("parameter_name") and defaults.get("parameter_name"):
                saved[kw]["parameter_name"] = defaults["parameter_name"]
            if not saved[kw].get("override_note") and defaults.get("override_note"):
                saved[kw]["override_note"] = defaults["override_note"]
    return saved


def save_analyte_cas(portal, data):
    obj = _get_egad_singleton(portal)
    if obj is not None:
        obj.analyte_cas_json = json.dumps(data)
        try:
            obj.reindexObject()
        except Exception:
            pass
        return
    store = _get_store(portal)
    _save(store, "analyte_cas", data)


# ── Qualifier mapping ─────────────────────────────────────────────────────────

def get_qualifier_map(portal):
    obj = _get_egad_singleton(portal)
    if obj is not None:
        raw = getattr(obj, "qualifier_map_json", None)
        if raw:
            try:
                return json.loads(raw)
            except (ValueError, TypeError):
                logger.warning("Corrupt EGAD qualifier_map_json in Dexterity; using default")
        return copy.deepcopy(DEFAULT_QUALIFIER_MAP)
    # Annotation fallback
    store = _get_store(portal)
    return _load(store, "qualifier_map", DEFAULT_QUALIFIER_MAP)


def save_qualifier_map(portal, data):
    obj = _get_egad_singleton(portal)
    if obj is not None:
        obj.qualifier_map_json = json.dumps(data)
        try:
            obj.reindexObject()
        except Exception:
            pass
        return
    store = _get_store(portal)
    _save(store, "qualifier_map", data)


def get_qualifier_dict(portal):
    """Return {our_qualifier: egad_code} for fast lookup."""
    mapping = get_qualifier_map(portal)
    return {row["our_qualifier"]: row["egad_code"] for row in mapping}


# ── QC type mapping ───────────────────────────────────────────────────────────

def get_qc_type_map(portal):
    obj = _get_egad_singleton(portal)
    if obj is not None:
        raw = getattr(obj, "qc_type_map_json", None)
        if raw:
            try:
                return json.loads(raw)
            except (ValueError, TypeError):
                logger.warning("Corrupt EGAD qc_type_map_json in Dexterity; using default")
        return copy.deepcopy(DEFAULT_QC_TYPE_MAP)
    # Annotation fallback
    store = _get_store(portal)
    return _load(store, "qc_type_map", DEFAULT_QC_TYPE_MAP)


def save_qc_type_map(portal, data):
    obj = _get_egad_singleton(portal)
    if obj is not None:
        obj.qc_type_map_json = json.dumps(data)
        try:
            obj.reindexObject()
        except Exception:
            pass
        return
    store = _get_store(portal)
    _save(store, "qc_type_map", data)


def get_qc_type_dict(portal):
    """Return {our_qc_type: egad_code} for fast lookup."""
    mapping = get_qc_type_map(portal)
    return {row["our_qc_type"]: row["egad_code"] for row in mapping}


# ── Refreshable lookups ───────────────────────────────────────────────────────

def get_lookups(portal):
    obj = _get_egad_singleton(portal)
    if obj is not None:
        raw = getattr(obj, "lookups_json", None)
        if raw:
            try:
                saved = json.loads(raw)
                for k, v in DEFAULT_LOOKUPS.items():
                    if k not in saved:
                        saved[k] = v
                return saved
            except (ValueError, TypeError):
                logger.warning("Corrupt EGAD lookups_json in Dexterity; using default")
        return copy.deepcopy(DEFAULT_LOOKUPS)
    # Annotation fallback
    store = _get_store(portal)
    saved = _load(store, "lookups", DEFAULT_LOOKUPS)
    for k, v in DEFAULT_LOOKUPS.items():
        if k not in saved:
            saved[k] = v
    return saved


def save_lookups(portal, data):
    obj = _get_egad_singleton(portal)
    if obj is not None:
        obj.lookups_json = json.dumps(data)
        try:
            obj.reindexObject()
        except Exception:
            pass
        return
    store = _get_store(portal)
    _save(store, "lookups", data)


def refresh_lookups_from_xlsx(portal, xlsx_bytes):
    """
    Re-import EGAD_Lookup_Tables.xlsx and update the refreshable lookup lists.
    User-defined mappings (qualifier_map, qc_type_map, analyte_cas) are untouched.

    xlsx_bytes: bytes of the uploaded Excel file.
    Returns: {"updated": [...keys], "errors": [...messages]}
    """
    try:
        import openpyxl
        import io as _io
    except ImportError:
        return {"updated": [], "errors": ["openpyxl is required for lookup refresh"]}

    errors = []
    updated = []

    try:
        wb = openpyxl.load_workbook(_io.BytesIO(xlsx_bytes), data_only=True)
    except Exception as exc:
        return {"updated": [], "errors": ["Cannot open workbook: " + str(exc)]}

    lookups = get_lookups(portal)

    def _read_lup(sheet_name, col_idx=0):
        if sheet_name not in wb.sheetnames:
            errors.append("{} sheet not found".format(sheet_name))
            return []
        ws = wb[sheet_name]
        vals = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i == 0:
                continue  # skip header
            v = row[col_idx]
            if v is not None and str(v).strip():
                vals.append(str(v).strip())
        return vals

    # CONCENTRATION_QUALIFIER_LUP
    quals = _read_lup("CONCENTRATION_QUALIFIER_LUP", 0)
    if quals:
        lookups["concentration_qualifiers"] = quals
        updated.append("concentration_qualifiers")

    # QA_QC_TYPE_LUP
    qcs = _read_lup("QA_QC_TYPE_LUP", 0)
    if qcs:
        lookups["qc_types"] = qcs
        updated.append("qc_types")

    # PARAMETER_UNITS_LUP
    units = _read_lup("PARAMETER_UNITS_LUP", 0)
    if units:
        lookups["units"] = units
        updated.append("units")

    # SAMPLE_TYPE_LUP
    stypes = _read_lup("SAMPLE_TYPE_LUP", 0)
    if stypes:
        lookups["sample_types"] = stypes
        updated.append("sample_types")

    # ANALYSIS_LAB_LUP
    labs = _read_lup("ANALYSIS_LAB_LUP", 0)
    if labs:
        lookups["analysis_labs"] = labs
        updated.append("analysis_labs")

    # TEST_LUP
    tests = _read_lup("TEST_LUP", 0)
    if tests:
        lookups["tests"] = tests
        updated.append("tests")

    # PREP_METHOD_LUP
    preps = _read_lup("PREP_METHOD_LUP", 0)
    if preps:
        lookups["prep_methods"] = preps
        updated.append("prep_methods")

    # SAMPLE_COLLECTION_METHOD_LUP
    scms = _read_lup("SAMPLE_COLLECTION_METHOD_LUP", 0)
    if scms:
        lookups["sample_collection_methods"] = scms
        updated.append("sample_collection_methods")

    from datetime import date
    lookups["last_refresh"] = date.today().isoformat()
    lookups["last_refresh_filename"] = "EGAD_Lookup_Tables.xlsx"

    save_lookups(portal, lookups)
    return {"updated": updated, "errors": errors}


# ── Per-client settings ───────────────────────────────────────────────────────

def get_client_egad(client_obj):
    """Return EGAD settings dict for a SENAITE Client object."""
    try:
        from zope.annotation.interfaces import IAnnotations
        annotations = IAnnotations(client_obj)
        raw = annotations.get(PFAS_EGAD_CLIENT_KEY)
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return copy.deepcopy(DEFAULT_CLIENT_EGAD)


def save_client_egad(client_obj, data):
    """Persist EGAD settings on a SENAITE Client object."""
    try:
        from zope.annotation.interfaces import IAnnotations
        annotations = IAnnotations(client_obj)
        annotations[PFAS_EGAD_CLIENT_KEY] = json.dumps(data)
    except Exception as exc:
        logger.error("Cannot save client EGAD settings: %s", exc)


def is_egad_enabled(client_obj):
    """Return True if the client has government-agency EGAD flag set."""
    cfg = get_client_egad(client_obj)
    return bool(cfg.get("egad_enabled", False))


# ── Seed on install ───────────────────────────────────────────────────────────

def seed_defaults(portal):
    """Seed all default config.  Idempotent — never overwrites saved data."""
    obj = _get_egad_singleton(portal)
    if obj is not None:
        # Seed into Dexterity object — only write fields that are currently empty
        for attr, default in [
            ("lab_json",           DEFAULT_LAB),
            ("method_egad_json",   DEFAULT_METHOD_EGAD),
            ("analyte_cas_json",   DEFAULT_ANALYTE_CAS),
            ("qualifier_map_json", DEFAULT_QUALIFIER_MAP),
            ("qc_type_map_json",   DEFAULT_QC_TYPE_MAP),
            ("lookups_json",       DEFAULT_LOOKUPS),
        ]:
            if not getattr(obj, attr, None):
                setattr(obj, attr, json.dumps(default))
        try:
            obj.reindexObject()
        except Exception:
            pass
        logger.info("Seeded EGAD defaults into Dexterity EGADConfig object")
        return
    # Annotation fallback (pre-migration / fresh install without migration run)
    store = _get_store(portal)
    seeded = []
    for key, default in [
        ("lab",           DEFAULT_LAB),
        ("method_egad",   DEFAULT_METHOD_EGAD),
        ("analyte_cas",   DEFAULT_ANALYTE_CAS),
        ("qualifier_map", DEFAULT_QUALIFIER_MAP),
        ("qc_type_map",   DEFAULT_QC_TYPE_MAP),
        ("lookups",       DEFAULT_LOOKUPS),
    ]:
        if key not in store:
            store[key] = json.dumps(default)
            seeded.append(key)
    if seeded:
        logger.info("Seeded EGAD defaults for keys: %s", ", ".join(seeded))
