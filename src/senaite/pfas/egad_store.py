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
the exported analyte_cas.json when available; DEFAULT_ANALYTE_CAS here is the
authoritative source.
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

# ── Seeded CAS mapping (32/34 auto-matched; PFUnDS and PFTrDS need manual entry)
# Format: keyword → {"cas_no": str, "parameter_name": str, "override_note": str}
# CAS_NO: digits only (no dashes) for standard CAS; DEP##### for Maine codes.

DEFAULT_ANALYTE_CAS = {
    "9ClPF3ONS":   {"cas_no": "756426581",  "parameter_name": "9CL-PF3ONS_A",      "override_note": ""},
    "11ClPF3OUdS": {"cas_no": "763051929",  "parameter_name": "11CL-PF3OUDS_A",    "override_note": ""},
    "FOSA":        {"cas_no": "754916",     "parameter_name": "PFOSA",              "override_note": ""},
    "4:2FTS":      {"cas_no": "757124724",  "parameter_name": "4:2 FTS_A",          "override_note": ""},
    "6:2FTS":      {"cas_no": "27619972",   "parameter_name": "6:2 FTS_A",          "override_note": ""},
    "8:2FTS":      {"cas_no": "39108344",   "parameter_name": "8:2 FTS_A",          "override_note": ""},
    "10:2FTS":     {"cas_no": "120226600",  "parameter_name": "10:2 FTS_A",         "override_note": ""},
    "PFBA":        {"cas_no": "375224",     "parameter_name": "PFBA_A",             "override_note": ""},
    "PFPeA":       {"cas_no": "2706903",    "parameter_name": "PFPEA_A",            "override_note": ""},
    "PFHxA":       {"cas_no": "307244",     "parameter_name": "PFHXA_A",            "override_note": ""},
    "PFHpA":       {"cas_no": "375859",     "parameter_name": "PFHPA_A",            "override_note": ""},
    "PFOA":        {"cas_no": "335671",     "parameter_name": "PFOA_A",             "override_note": ""},
    "PFNA":        {"cas_no": "375951",     "parameter_name": "PFNA_A",             "override_note": ""},
    "PFDA":        {"cas_no": "335762",     "parameter_name": "PFDA_A",             "override_note": ""},
    "PFUDA":       {"cas_no": "2058948",    "parameter_name": "PFUNDA_A",           "override_note": ""},
    "PFDoA":       {"cas_no": "307551",     "parameter_name": "PFDOA_A",            "override_note": ""},
    "PFTrDA":      {"cas_no": "72629948",   "parameter_name": "PFTRIA_A",           "override_note": ""},
    "PFTeDA":      {"cas_no": "376067",     "parameter_name": "PFTEA_A",            "override_note": ""},
    "PFHxDA":      {"cas_no": "67905195",   "parameter_name": "PFHXDA_A",           "override_note": ""},
    "PFODA":       {"cas_no": "16517116",   "parameter_name": "PFODA_A",            "override_note": ""},
    "GenX":        {"cas_no": "13252136",   "parameter_name": "HFPO-DA_A",          "override_note": ""},
    "DONA":        {"cas_no": "919005144",  "parameter_name": "ADONA_A",            "override_note": ""},
    "PFBS":        {"cas_no": "375735",     "parameter_name": "PFBS_A",             "override_note": ""},
    "PFPeS":       {"cas_no": "2706914",    "parameter_name": "PFPES_A",            "override_note": ""},
    "PFHxS":       {"cas_no": "DEP18024",   "parameter_name": "PFHXS_A_L",         "override_note": "linear isomer"},
    "br-PFHxS":    {"cas_no": "DEP18023",   "parameter_name": "PFHXS_A_BR",        "override_note": "branched isomer"},
    "PFHpS":       {"cas_no": "375928",     "parameter_name": "PFHPS_A",            "override_note": ""},
    "PFOS":        {"cas_no": "DEP18026",   "parameter_name": "PFOS_A_L",          "override_note": "linear isomer"},
    "br-PFOS":     {"cas_no": "DEP18025",   "parameter_name": "PFOS_A_BR",         "override_note": "branched isomer"},
    "PFNS":        {"cas_no": "68259121",   "parameter_name": "PFNS_A",             "override_note": ""},
    "PFDS":        {"cas_no": "335773",     "parameter_name": "PFDS_A",             "override_note": ""},
    "PFUnDS":      {"cas_no": "749786161",   "parameter_name": "PFUNDS_A",           "override_note": "CAS 749-786-16-1; verify against Maine EGAD CAS_LUP before EDD submission"},
    "PFDoS":       {"cas_no": "79780395",   "parameter_name": "PFDOS_A",            "override_note": ""},
    "PFTrDS":      {"cas_no": "791563898",   "parameter_name": "PFTRDS_A",           "override_note": "CAS 791-563-89-8"},
}

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
