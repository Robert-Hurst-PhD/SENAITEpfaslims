# -*- coding: utf-8 -*-
"""The EGAD EDD v6.0 format, as an EDD export profile
(2026-10-08: EGAD exists only as a profile of
the EDD export). Everything specific to this format lives here and nowhere
else:

  the row format   the 53 columns in template order, the fields required
                   for lab and QC rows, date/time formatting (MM/DD/YYYY,
                   HH:MM) and the per-row checks (a blank required field; a
                   PLACEHOLDER or empty CAS blocks submission)
  the seed         the profile a new install starts from (seed_profile):
                   its defaults, method codes, value lists (EGAD lookup
                   tables), code maps, analyte naming and the client fields
                   it asks for
  the forms        the fields the EDD settings page shows for this format,
                   with this format's labels and hints
  the refresh      re-reading the state's EGAD_Lookup_Tables.xlsx

Codes and names trace to the state agency's EGAD lookup tables
(EGAD_Lookup_Tables.xlsx).
Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

EDD_COLUMNS = [
    "PROJECT/SITE", "SAMPLE_POINT_NAME", "SAMPLE_ID", "LAB_SAMPLE_ID",
    "ANALYSIS_LAB", "SAMPLE_DATE", "SAMPLE_TIME", "SAMPLE_TYPE",
    "QC_TYPE", "RESULT_TYPE_CODE", "CAS_NO", "PARAMETER_NAME",
    "CONCENTRATION", "LAB_QUALIFIER", "REPORTING_LIMIT", "PARAMETER_UNITS",
    "% RECOVERY", "RPD", "TEST", "PARAMETER_QUALIFIER", "PARAMETER_FILTERED",
    "SAMPLE_COLLECTION_METHOD", "SAMPLE_LOCATION", "TREATMENT_STATUS",
    "SAMPLED_BY", "IDL", "MDL", "DILUTION_FACTOR", "BATCH_ID",
    "SAMPLE_DELIVERY_GROUP", "ANALYSIS_DATE", "ANALYSIS_TIME",
    "PREP_METHOD", "PREP_DATE", "PREP_TIME", "PREP_METHOD2",
    "PREP_DATE2", "PREP_TIME2", "WEIGHT_BASIS", "LAB_COMMENT",
    "VALIDATION_QUALIFIER", "VALIDATION_LEVEL", "VALIDATION_COMMENT",
    "VALIDATION_COMMENT_TYPE", "VALIDATION_SQL", "SAMPLE_DEPTH",
    "SAMPLE_DEPTH_UNIT", "SAMPLE_DEPTH_INTERVAL_TOP",
    "SAMPLE_DEPTH_INTERVAL_BOTTOM", "SAMPLE_DEPTH_INTERVAL_UNIT",
    "RADIOLOGICAL_COUNTING_ERROR", "SAMPLE_TYPE_QUALIFIER", "SAMPLE_COMMENT",
]

_LAB_REQUIRED = frozenset([
    "PROJECT/SITE", "SAMPLE_POINT_NAME", "LAB_SAMPLE_ID", "ANALYSIS_LAB",
    "SAMPLE_DATE", "SAMPLE_TIME", "SAMPLE_TYPE", "QC_TYPE",
    "RESULT_TYPE_CODE", "CAS_NO", "PARAMETER_NAME", "CONCENTRATION",
    "REPORTING_LIMIT", "PARAMETER_UNITS", "TEST", "PARAMETER_FILTERED",
    "SAMPLE_COLLECTION_METHOD", "TREATMENT_STATUS", "BATCH_ID",
    "SAMPLE_DELIVERY_GROUP", "ANALYSIS_DATE", "ANALYSIS_TIME",
])

_QC_REQUIRED = frozenset([
    "PROJECT/SITE", "SAMPLE_POINT_NAME", "LAB_SAMPLE_ID", "ANALYSIS_LAB",
    "SAMPLE_DATE", "SAMPLE_TIME", "SAMPLE_TYPE", "QC_TYPE",
    "RESULT_TYPE_CODE", "CAS_NO", "PARAMETER_NAME",
    "PARAMETER_UNITS", "TEST", "PARAMETER_FILTERED",
    "SAMPLE_COLLECTION_METHOD", "TREATMENT_STATUS", "BATCH_ID",
    "SAMPLE_DELIVERY_GROUP", "ANALYSIS_DATE", "ANALYSIS_TIME",
])

# WEIGHT_BASIS valid values: EDD v6 Appendix 1, data element dictionary
# ("WET for wet-weight basis, DRY for dry-weight basis, LIP for lipid-weight
# basis, or NA"). Which one a matrix is reported on is the lab's choice, per
# matrix, in the profile's weight_basis_map; there is no default.
WEIGHT_BASES = ("WET", "DRY", "LIP", "NA")

_SOLID_SAMPLE_TYPES = frozenset([
    "SL", "SD", "SU", "SUL", "SUU", "AS", "BA", "FA",
    "MEA", "MLK", "EG", "FE", "MU", "SF", "SOF", "FI",
    "CP", "CH", "CO", "FR", "GR", "GRS", "LG", "NRV", "RV",
    "V", "GZ", "G", "HT", "HP", "KD", "LV", "MR", "HM",
    "MA", "MPS", "HN", "HR", "O", "TO", "WH", "WWHG", "WS",
    "SK", "MTB", "BC",
])


def _fmt_date(d):
    if d is None:
        return ""
    try:
        return d.strftime("%m/%d/%Y")
    except AttributeError:
        return str(d)


def _fmt_time(d):
    if d is None:
        return ""
    try:
        return d.strftime("%H:%M")
    except AttributeError:
        return str(d)


def _get_units(method_id, sample_type_code, method_cfg):
    if sample_type_code in _SOLID_SAMPLE_TYPES:
        return method_cfg.get("units_solid", "NG/KG")
    return method_cfg.get("units_water", "NG/L")


def _row_to_list(row_dict):
    """Convert row_dict to ordered list of 53 values."""
    g = row_dict.get
    conc = g("concentration")
    return [
        g("project_site", ""),
        g("sample_point_name", ""),
        g("sample_id", ""),
        g("lab_sample_id", ""),
        g("analysis_lab", ""),
        _fmt_date(g("sample_date")),
        _fmt_time(g("sample_time")),
        g("sample_type", ""),
        g("qc_type", "NA"),
        g("result_type_code", "TRG"),
        g("cas_no", ""),
        g("parameter_name", ""),
        "" if conc is None else conc,
        g("lab_qualifier", ""),
        g("reporting_limit", ""),
        g("parameter_units", ""),
        g("pct_recovery", ""),
        g("rpd", ""),
        g("test", ""),
        g("parameter_qualifier", ""),
        g("parameter_filtered", "NA"),
        g("sample_collection_method", ""),
        g("sample_location", "NA"),
        g("treatment_status", "N"),
        g("sampled_by", ""),
        g("idl", ""),
        g("mdl", ""),
        g("dilution_factor", 1),
        g("batch_id", ""),
        g("sdg", ""),
        _fmt_date(g("analysis_date")),
        _fmt_time(g("analysis_time")),
        g("prep_method", ""),
        _fmt_date(g("prep_date")),
        _fmt_time(g("prep_time")),
        g("prep_method2", ""),
        _fmt_date(g("prep_date2")),
        _fmt_time(g("prep_time2")),
        g("weight_basis", "NA"),
        g("lab_comment", ""),
        g("validation_qualifier", ""),
        g("validation_level", ""),
        g("validation_comment", ""),
        g("validation_comment_type", ""),
        g("validation_sql", ""),
        g("sample_depth", ""),
        g("sample_depth_unit", ""),
        g("sample_depth_interval_top", ""),
        g("sample_depth_interval_bottom", ""),
        g("sample_depth_interval_unit", ""),
        g("radiological_counting_error", ""),
        g("sample_type_qualifier", "NA"),
        g("sample_comment", ""),
    ]


def _validate_row(row_values, row_number, is_qc):
    errors = []
    required = _QC_REQUIRED if is_qc else _LAB_REQUIRED
    row_dict = dict(zip(EDD_COLUMNS, row_values))
    qual = str(row_dict.get("LAB_QUALIFIER", "") or "")

    for field in required:
        val = row_dict.get(field)
        if val is None or str(val).strip() == "":
            # Non-detect: blank CONCENTRATION is correct when U-qualified
            if field == "CONCENTRATION" and "U" in qual.upper():
                continue
            errors.append({
                "row": row_number,
                "field": field,
                "message": "Required field is blank",
                "type": "QC" if is_qc else "Lab",
            })

    cas = str(row_dict.get("CAS_NO", "") or "")
    if cas.upper() == "PLACEHOLDER":
        errors.append({
            "row": row_number,
            "field": "CAS_NO",
            "message": (
                "CAS_NO is PLACEHOLDER — assign a real CAS or DEP##### code "
                "in the EDD export settings before submitting"
            ),
            "type": "BLOCKING",
        })
    elif not cas.strip():
        param = str(row_dict.get("PARAMETER_NAME", "") or "")
        errors.append({
            "row": row_number,
            "field": "CAS_NO",
            "message": "CAS_NO is empty for {0} — enter it in the EDD export settings".format(param),
            "type": "BLOCKING",
        })

    return errors


# ── The profile ───────────────────────────────────────────────────────────────

PROFILE_ID = "egad_v6"
NAME = u"EGAD EDD v6.0 (default)"
STATE = ""          # the state the lab reports to: set on the profile

# export defaults (the lab's identity and default field values in this format)
DEFAULTS = {
    "analysis_lab_code": "",
    "default_prep_method": "SW3535",
    "default_sample_collection_method": "LFS",
    "default_treatment_status": "N",
    "default_parameter_filtered": "U",
    "sdg_prefix": "",
    "sdg_format": "{prefix}{batch_id}",
    "sampled_by": "",
}

# per method: this format's TEST code, prep method and unit codes
METHOD_CODES = {
    "EPA_537_1": {"method_id": "EPA_537_1", "test_code": "E537.1", "prep_method": "SW3535",
                  "units_water": "NG/L", "units_solid": "NG/KG"},
    "EPA_1633A": {"method_id": "EPA_1633A", "test_code": "E1633_DR", "prep_method": "SW3535",
                  "units_water": "NG/L", "units_solid": "NG/KG"},
    "FDA_32PFAS": {"method_id": "FDA_32PFAS", "test_code": "USFDA-PFAS", "prep_method": "SW3535",
                   "units_water": "NG/L", "units_solid": "NG/KG"},
}
METHOD_FALLBACK = {"test_code": "E537.1", "prep_method": "SW3535",
                   "units_water": "NG/L", "units_solid": "NG/KG"}

# Analyte naming: EGAD PARAMETER_NAME and, where the state uses its own code, a
# DEP##### code in place of the CAS. The CAS itself stays single-sourced in
# analyte_reference.NATIVE_ANALYTES.
ANALYTE_OVERLAY = {
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
    # PFHxS / PFOS are reported as the SUMMED analyte (:
    # one analyte out). EGAD CAS_LUP lists the plain acid (355464
    # PFHXS_A, 1763231 PFOS_A) besides the -LINEAR / -BRANCHED / "linear and
    # branched" entries; the plain acid matches how the other summed analytes
    # (PFOA_A, PFNA_A, N-EtFOSAA_A, N-MeFOSAA_A) are exported. CAS from the
    # master table.
    "PFHxS":       {"parameter_name": "PFHXS_A",         "override_note": ""},
    "br-PFHxS":    {"parameter_name": "PFHXS_A_BR", "override_note": "branched isomer", "cas_override": "DEP18023"},
    "PFHpS":       {"parameter_name": "PFHPS_A",         "override_note": ""},
    "PFOS":        {"parameter_name": "PFOS_A",          "override_note": ""},
    "br-PFOS":     {"parameter_name": "PFOS_A_BR",  "override_note": "branched isomer", "cas_override": "DEP18025"},
    "PFNS":        {"parameter_name": "PFNS_A",          "override_note": ""},
    "PFDS":        {"parameter_name": "PFDS_A",          "override_note": ""},
    "PFUnDS":      {"parameter_name": "PFUNDS_A",        "override_note": "VERIFY: CAS 749786-16-1 is not in EGAD CAS_LUP (checked 2026-10-01); ask the state agency for the code before an EDD"},
    "PFDoS":       {"parameter_name": "PFDOS_A",         "override_note": ""},
    "PFTrDS":      {"parameter_name": "PFTRDS_A",   "override_note": "VERIFY: CAS 791563-89-8 is not in EGAD CAS_LUP (checked 2026-10-01); ask the state agency for the code before an EDD", "cas_override": "791563898"},
    # Names below were blank. Each is the VALUE EGAD CAS_LUP gives for
    # the CAS the master table already holds (EGAD_Lookup_Tables.xlsx,
    # the state agency's lookup workbook, downloaded 2026-10-01).
    "3:3FTCA":     {"parameter_name": "3:3 FTC_A",       "override_note": ""},
    "5:3FTCA":     {"parameter_name": "5:3 FTC_A",       "override_note": ""},
    "7:3FTCA":     {"parameter_name": "7:3 FTC_A",       "override_note": ""},
    "NEtFOSA":     {"parameter_name": "N-ETFOSA",        "override_note": ""},
    "NEtFOSAA":    {"parameter_name": "N-EtFOSAA_A",     "override_note": ""},
    "NEtFOSE":     {"parameter_name": "N-EtFOSE",        "override_note": ""},
    "NFDHA":       {"parameter_name": "PFDH_A",          "override_note": ""},
    "NMeFOSA":     {"parameter_name": "N-MEFOSA",        "override_note": ""},
    "NMeFOSAA":    {"parameter_name": "N-MeFOSAA_A",     "override_note": ""},
    "NMeFOSE":     {"parameter_name": "N-MEFOSE",        "override_note": ""},
    "PFEESA":      {"parameter_name": "PFEES_A",         "override_note": ""},
    "PFMBA":       {"parameter_name": "PFMB_A",          "override_note": ""},
    "PFMPA":       {"parameter_name": "PFMP_A",          "override_note": ""},
}


# an analyte this format's naming does not cover: named by its title, and
# said so (guessing the state's spelling would fabricate an identifier)
UNNAMED_NOTE = (u"VERIFY the EGAD PARAMETER_NAME for this analyte against the state's "
                u"EGAD parameter list before submission.")


def analyte_naming():
    """{keyword: {parameter_name, code_override, note}} for the seed."""
    return dict((kw, {"parameter_name": ov.get("parameter_name", ""),
                      "code_override": ov.get("cas_override", ""),
                      "note": ov.get("override_note", "")})
                for kw, ov in ANALYTE_OVERLAY.items())


# Standard EGAD sample-type codes for the obvious environmental
# matrices. Food/feed matrices have NO EGAD code -- left unmapped on purpose
# (per-sample override or profile edit; never fabricated).
MATRIX_MAP = {
    "Drinking Water": "DW", "Groundwater": "GW", "Surface Water": "SW",
    "Wastewater": "WW", "Soil": "SO", "Sediment": "SE",
    "Landfill Leachate": "LL", "Biosolid": "SO",
}

QUALIFIER_MAP = [
    {"our_qualifier": "N.D.",   "code": "U",    "description": "Not detected"},
    {"our_qualifier": "< LOD",  "code": "U",    "description": "Below LOD"},
    {"our_qualifier": "BLoQ",   "code": "J",    "description": "Below LOQ — estimated"},
    {"our_qualifier": "N.C.",   "code": "NC",   "description": "Not confirmed"},
    # the QC-qualification library's spelling of the same code
    {"our_qualifier": "NC",     "code": "NC",   "description": "Not confirmed (ion ratio / RT)"},
    {"our_qualifier": "EMPC",   "code": "EMPC", "description": "Estimated max possible conc."},
    {"our_qualifier": "B",      "code": "B",    "description": "Found in method blank"},
    {"our_qualifier": "J",      "code": "J",    "description": "Estimated value"},
    {"our_qualifier": "UJ",     "code": "UJ",   "description": "Non-detect + estimated RL"},
    {"our_qualifier": "JB",     "code": "JB",   "description": "Estimated + in blank"},
    {"our_qualifier": "TIC",    "code": "N",    "description": "Tentatively identified"},
    {"our_qualifier": "*",      "code": "*",    "description": "QC outside control limits"},
    {"our_qualifier": "J*",     "code": "J*",   "description": "Estimated + QC out of limits"},
    # Qualified-release codes (qc_qualification.FAILURE_TYPES). They are OUR
    # vocabulary for the certificate; the EDD carries the nearest EGAD code
    # that already exists rather than a new one invented here. Without these
    # entries `_translate_qualifier` passes an unknown code through unchanged
    # and "M" would land in LAB_QUALIFIER, which is not a valid EGAD value.
    {"our_qualifier": "M",      "code": "*",    "description": "Matrix effect — QC outside control limits"},
    {"our_qualifier": "P",      "code": "*",    "description": "Precision (RPD) outside control limits"},
]

QC_TYPE_MAP = [
    {"our_qc_type": "MB",     "code": "LB",   "description": "Method Blank"},
    {"our_qc_type": "LB",     "code": "LB",   "description": "Lab Blank"},
    {"our_qc_type": "LFSM",   "code": "MS",   "description": "Lab Fortified Sample Matrix"},
    {"our_qc_type": "LFSMD",  "code": "MSD",  "description": "LFSM Duplicate"},
    {"our_qc_type": "CCV",    "code": "CCC",  "description": "Continuing Calibration Verification"},
    {"our_qc_type": "LCS",    "code": "LCS",  "description": "Lab Control Sample"},
    {"our_qc_type": "LCSD",   "code": "LCSD", "description": "LCS Duplicate"},
    {"our_qc_type": "Dup",    "code": "L",    "description": "Lab Duplicate"},
    {"our_qc_type": "DUP",    "code": "L",    "description": "Lab Duplicate"},
    {"our_qc_type": "FD",     "code": "D",    "description": "Field Duplicate"},
    {"our_qc_type": "TB",     "code": "TB",   "description": "Trip Blank"},
    {"our_qc_type": "FB",     "code": "FB",   "description": "Field Blank"},
    {"our_qc_type": "EB",     "code": "EB",   "description": "Equipment Blank"},
    {"our_qc_type": "IB",     "code": "IB",   "description": "Instrument Blank"},
    {"our_qc_type": "CCB",    "code": "CCB",  "description": "Continuing Calibration Blank"},
    {"our_qc_type": "Normal", "code": "NA",   "description": "Normal environmental sample"},
    {"our_qc_type": "NA",     "code": "NA",   "description": "Normal environmental sample"},
]

# the format's valid-value lists (EGAD_Lookup_Tables.xlsx)
VALUE_LISTS = {
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

# which value list a code map's codes come from
QUALIFIER_LIST = "concentration_qualifiers"
QC_TYPE_LIST = "qc_types"

# the client fields this format asks for (on a client's EDD settings)
CLIENT_FIELDS = [
    {"key": "project_site", "label": u"Project / site (PROJECT/SITE)",
     "hint": u"The EGAD project or site name for this client's samples."},
    {"key": "default_sample_type", "label": u"Default sample type (SAMPLE_TYPE)",
     "list": "sample_types", "default": "GW",
     "hint": u"Used when a sample's matrix has no code in the profile's matrix map."},
    {"key": "analysis_lab_override", "label": u"Analysis lab code (ANALYSIS_LAB) override",
     "list": "analysis_labs", "hint": u"Leave blank to use the profile's laboratory code."},
]

# the form the settings page shows for the profile's defaults
DEFAULT_FIELDS = [
    {"key": "analysis_lab_code", "label": u"Laboratory code (ANALYSIS_LAB)", "list": "analysis_labs",
     "hint": u"Assigned by the state agency; must match ANALYSIS_LAB_LUP exactly."},
    {"key": "sampled_by", "label": u"Sampled by (default)", "hint": u"Can be overridden per sample."},
    {"key": "default_prep_method", "label": u"Preparation method (default)", "list": "prep_methods",
     "hint": u"PREP_METHOD_LUP, e.g. SW3535 (solid phase extraction)."},
    {"key": "default_sample_collection_method", "label": u"Collection method (default)",
     "list": "sample_collection_methods", "hint": u"LFS = low-flow sampling; QC rows use NA."},
    {"key": "default_treatment_status", "label": u"Treatment status (default)",
     "list": "treatment_statuses", "hint": u"N = not treated."},
    {"key": "default_parameter_filtered", "label": u"Filtered (default)",
     "options": ["U", "NA", "FL", "FF"], "hint": u"U = unfiltered; QC rows use NA."},
    {"key": "sdg_prefix", "label": u"Sample delivery group prefix"},
    {"key": "sdg_format", "label": u"Sample delivery group format",
     "hint": u"Tokens {prefix} and {batch_id}."},
]

# the form for each method's codes
METHOD_FIELDS = [
    {"key": "test_code", "label": u"Test code (TEST)", "list": "tests"},
    {"key": "prep_method", "label": u"Preparation method", "list": "prep_methods",
     "hint": u"Blank: the profile's default."},
    {"key": "units_water", "label": u"Units, water matrix", "options": ["NG/L", "NG/ML", "PG/L", "UG/L"]},
    {"key": "units_solid", "label": u"Units, solid / food matrix", "options": ["NG/KG", "NG/G", "NG/ML", "PG/G"]},
]

# the analyte table's column headings in this format
ANALYTE_LABELS = {"code": u"CAS_NO", "name": u"PARAMETER_NAME"}

# where the value lists come from, shown beside the upload
VALUE_LIST_SOURCE = {
    "file": u"EGAD_Lookup_Tables.xlsx",
    "label": u"the state agency's EGAD data entry page",
    "url": u"",
}


def analyte_guidance(keyword, code):
    """A note for an analyte whose code the state must issue (shown until a
    DEP##### code is entered)."""
    if keyword == "PFUnDS" and not (code or "").upper().startswith("DEP"):
        return (u"PFUnDS (CAS 749786-16-1) is not in EGAD's CAS_LUP. Ask the state agency "
                u"for a DEP##### code and enter it as the code; the name follows PFUNDS_A.")
    return u""


def seed_profile():
    """The profile a new install starts from."""
    import copy
    return {
        "name": NAME, "base": PROFILE_ID, "format": PROFILE_ID, "state": STATE,
        "columns": list(EDD_COLUMNS), "aliases": {},
        "matrix_map": dict(MATRIX_MAP),
        "weight_basis_map": {},
        "qualifier_map": copy.deepcopy(QUALIFIER_MAP),
        "qc_type_map": copy.deepcopy(QC_TYPE_MAP),
        "analyte_naming": analyte_naming(),
        "defaults": dict(DEFAULTS),
        "method_codes": copy.deepcopy(METHOD_CODES),
        "value_lists": copy.deepcopy(VALUE_LISTS),
        "client_fields": copy.deepcopy(CLIENT_FIELDS),
        "notes": u"Seeded EGAD EDD v6.0 format. Clone to create sub-profiles.",
    }


def refresh_from_upload(current, xlsx_bytes):
    """Re-read the state's lookup workbook into the value lists. Returns
    (lists, {"updated": [...], "errors": [...]}); code maps are untouched."""
    try:
        import openpyxl
        import io as _io
    except ImportError:
        return current, {"updated": [], "errors": ["openpyxl is required for the refresh"]}

    errors = []
    updated = []

    try:
        wb = openpyxl.load_workbook(_io.BytesIO(xlsx_bytes), data_only=True)
    except Exception as exc:
        return current, {"updated": [], "errors": ["Cannot open workbook: " + str(exc)]}

    lookups = dict(current or {})

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
    lookups["last_refresh_filename"] = VALUE_LIST_SOURCE["file"]
    return lookups, {"updated": updated, "errors": errors}
