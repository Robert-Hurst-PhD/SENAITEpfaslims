# -*- coding: utf-8 -*-
"""Maine EGAD EDD v6.0 row format: the 53 columns in template order, the
fields required for lab and QC rows, date/time formatting (MM/DD/YYYY,
HH:MM) and the per-row checks (a blank required field; a PLACEHOLDER or empty
CAS blocks submission). The one copy (docs/REUSE_REVIEW.md U5): egad_builder
builds rows with it; the Python 3 twin that duplicated it is gone. Pure;
Python 2.7 and 3.
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
                "in EGAD Config before submitting"
            ),
            "type": "BLOCKING",
        })
    elif not cas.strip():
        param = str(row_dict.get("PARAMETER_NAME", "") or "")
        errors.append({
            "row": row_number,
            "field": "CAS_NO",
            "message": "CAS_NO is empty for {0} — enter in EGAD Config".format(param),
            "type": "BLOCKING",
        })

    return errors
