"""
EGAD EDD v6.0 Generator — Maine DEP regulatory submission.

Python 3 standalone module.  Used for:
  1. Format validation spike (run __main__ to compare against Appendix 2 examples)
  2. Standalone pre-import preview / CLI generation

The Plone/Python 2.7 twin is src/senaite/pfas/egad_builder.py.
Both share the same row-dict schema and column ordering; keep them in sync.

53 EDD columns (exact order from the Appendix 1 EDD template sheet):
  PROJECT/SITE  SAMPLE_POINT_NAME  SAMPLE_ID  LAB_SAMPLE_ID  ANALYSIS_LAB
  SAMPLE_DATE  SAMPLE_TIME  SAMPLE_TYPE  QC_TYPE  RESULT_TYPE_CODE
  CAS_NO  PARAMETER_NAME  CONCENTRATION  LAB_QUALIFIER  REPORTING_LIMIT
  PARAMETER_UNITS  % RECOVERY  RPD  TEST  PARAMETER_QUALIFIER
  PARAMETER_FILTERED  SAMPLE_COLLECTION_METHOD  SAMPLE_LOCATION
  TREATMENT_STATUS  SAMPLED_BY  IDL  MDL  DILUTION_FACTOR  BATCH_ID
  SAMPLE_DELIVERY_GROUP  ANALYSIS_DATE  ANALYSIS_TIME  PREP_METHOD
  PREP_DATE  PREP_TIME  PREP_METHOD2  PREP_DATE2  PREP_TIME2
  WEIGHT_BASIS  LAB_COMMENT  VALIDATION_QUALIFIER  VALIDATION_LEVEL
  VALIDATION_COMMENT  VALIDATION_COMMENT_TYPE  VALIDATION_SQL
  SAMPLE_DEPTH  SAMPLE_DEPTH_UNIT  SAMPLE_DEPTH_INTERVAL_TOP
  SAMPLE_DEPTH_INTERVAL_BOTTOM  SAMPLE_DEPTH_INTERVAL_UNIT
  RADIOLOGICAL_COUNTING_ERROR  SAMPLE_TYPE_QUALIFIER  SAMPLE_COMMENT
"""

import csv
import io
from datetime import datetime, date, time

# ── Column order (must match Appendix 1 EDD template sheet exactly) ───────────

EDD_COLUMNS = [
    "PROJECT/SITE",
    "SAMPLE_POINT_NAME",
    "SAMPLE_ID",
    "LAB_SAMPLE_ID",
    "ANALYSIS_LAB",
    "SAMPLE_DATE",
    "SAMPLE_TIME",
    "SAMPLE_TYPE",
    "QC_TYPE",
    "RESULT_TYPE_CODE",
    "CAS_NO",
    "PARAMETER_NAME",
    "CONCENTRATION",
    "LAB_QUALIFIER",
    "REPORTING_LIMIT",
    "PARAMETER_UNITS",
    "% RECOVERY",
    "RPD",
    "TEST",
    "PARAMETER_QUALIFIER",
    "PARAMETER_FILTERED",
    "SAMPLE_COLLECTION_METHOD",
    "SAMPLE_LOCATION",
    "TREATMENT_STATUS",
    "SAMPLED_BY",
    "IDL",
    "MDL",
    "DILUTION_FACTOR",
    "BATCH_ID",
    "SAMPLE_DELIVERY_GROUP",
    "ANALYSIS_DATE",
    "ANALYSIS_TIME",
    "PREP_METHOD",
    "PREP_DATE",
    "PREP_TIME",
    "PREP_METHOD2",
    "PREP_DATE2",
    "PREP_TIME2",
    "WEIGHT_BASIS",
    "LAB_COMMENT",
    "VALIDATION_QUALIFIER",
    "VALIDATION_LEVEL",
    "VALIDATION_COMMENT",
    "VALIDATION_COMMENT_TYPE",
    "VALIDATION_SQL",
    "SAMPLE_DEPTH",
    "SAMPLE_DEPTH_UNIT",
    "SAMPLE_DEPTH_INTERVAL_TOP",
    "SAMPLE_DEPTH_INTERVAL_BOTTOM",
    "SAMPLE_DEPTH_INTERVAL_UNIT",
    "RADIOLOGICAL_COUNTING_ERROR",
    "SAMPLE_TYPE_QUALIFIER",
    "SAMPLE_COMMENT",
]

assert len(EDD_COLUMNS) == 53, "EDD column count must be exactly 53"

# ── Required fields (from DATA_ELEMENT_DICTIONARY, Lab Data column) ───────────
# R = required, C = conditional (required if relevant), O = optional

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

# ── Seeded CAS mapping (analyte keyword → EGAD CAS_NO, PARAMETER_NAME) ───────
# CAS_NO format: digits only (no dashes) or DEP##### code — as in CAS_LUP.
# Source: CAS_LUP VALUE and CAS_NO columns, CATEGORY = PFC.
# _A suffix in VALUE = acid form (reported in water/food matrices).
# Missing entries require manual entry in the config panel.

ANALYTE_CAS_DEFAULTS = {
    # keyword          CAS_NO         PARAMETER_NAME (EGAD VALUE column)
    "9ClPF3ONS":     ("756426581",   "9CL-PF3ONS_A"),
    "11ClPF3OUdS":   ("763051929",   "11CL-PF3OUDS_A"),
    "FOSA":          ("754916",      "PFOSA"),
    "4:2FTS":        ("757124724",   "4:2 FTS_A"),
    "6:2FTS":        ("27619972",    "6:2 FTS_A"),
    "8:2FTS":        ("39108344",    "8:2 FTS_A"),
    "10:2FTS":       ("120226600",   "10:2 FTS_A"),
    "PFBA":          ("375224",      "PFBA_A"),
    "PFPeA":         ("2706903",     "PFPEA_A"),
    "PFHxA":         ("307244",      "PFHXA_A"),
    "PFHpA":         ("375859",      "PFHPA_A"),
    "PFOA":          ("335671",      "PFOA_A"),
    "PFNA":          ("375951",      "PFNA_A"),
    "PFDA":          ("335762",      "PFDA_A"),
    "PFUDA":         ("2058948",     "PFUNDA_A"),
    "PFDoA":         ("307551",      "PFDOA_A"),
    "PFTrDA":        ("72629948",    "PFTRIA_A"),
    "PFTeDA":        ("376067",      "PFTEA_A"),
    "PFHxDA":        ("67905195",    "PFHXDA_A"),
    "PFODA":         ("16517116",    "PFODA_A"),
    "GenX":          ("13252136",    "HFPO-DA_A"),
    "DONA":          ("919005144",   "ADONA_A"),
    "PFBS":          ("375735",      "PFBS_A"),
    "PFPeS":         ("2706914",     "PFPES_A"),
    "PFHxS":         ("DEP18024",    "PFHXS_A_L"),    # lr-PFHxS = linear
    "br-PFHxS":      ("DEP18023",    "PFHXS_A_BR"),   # branched isomer
    "PFHpS":         ("375928",      "PFHPS_A"),
    "PFOS":          ("DEP18026",    "PFOS_A_L"),     # lr-PFOS = linear
    "br-PFOS":       ("DEP18025",    "PFOS_A_BR"),    # branched isomer
    "PFNS":          ("68259121",    "PFNS_A"),
    "PFDS":          ("335773",      "PFDS_A"),
    # PFUnDS: real CAS 749786-16-1 not in EGAD CAS_LUP — manual entry required
    "PFUnDS":        ("",            ""),
    "PFDoS":         ("79780395",    "PFDOS_A"),
    # PFTrDS: CAS is PLACEHOLDER — BLOCKING validation error until resolved
    "PFTrDS":        ("PLACEHOLDER", ""),
}

# ── Default qualifier mapping (our label → EGAD CONCENTRATION_QUALIFIER_LUP) ─

DEFAULT_QUALIFIER_MAP = {
    "N.D.":     "U",    # not detected
    "< LOD":    "U",    # below limit of detection
    "BLoQ":     "J",    # below limit of quantitation (estimated)
    "N.C.":     "NC",   # not confirmed
    "EMPC":     "EMPC", # estimated max possible concentration
    "B":        "B",    # found in method blank
    "J":        "J",    # estimated
    "UJ":       "UJ",   # non-detect + estimated RL
    "JB":       "JB",   # estimated + in blank
    "TIC":      "N",    # tentatively identified (N = tentative ID)
}

# ── QC type mapping (our labels → EGAD QA_QC_TYPE_LUP) ───────────────────────

DEFAULT_QC_TYPE_MAP = {
    "MB":      "LB",    # Method Blank → Lab Blank
    "LB":      "LB",    # Lab Blank (already EGAD code)
    "LFSM":    "MS",    # Lab Fortified Sample Matrix → Matrix Spike
    "LFSMD":   "MSD",   # LFSM Duplicate → Matrix Spike Duplicate
    "CCV":     "CCC",   # Continuing Calibration Verification → CCC
    "LCS":     "LCS",   # Lab Control Sample
    "LCSD":    "LCSD",  # LCS Duplicate
    "Dup":     "L",     # Lab Duplicate
    "DUP":     "L",
    "FD":      "D",     # Field Duplicate
    "TB":      "TB",    # Trip Blank
    "FB":      "FB",    # Field Blank
    "EB":      "EB",    # Equipment Blank
    "IB":      "IB",    # Instrument Blank
    "CCB":     "CCB",   # Continuing Calibration Blank
    "Normal":  "NA",    # Normal environmental sample
    "SAMPLE":  "NA",    # Normal environmental sample
    "NA":      "NA",    # Already correct
}

# ── Method → EGAD TEST code ───────────────────────────────────────────────────

METHOD_TEST_CODES = {
    "EPA_537_1":  "E537.1",
    "EPA_1633A":  "E1633_DR",
    "FDA_32PFAS": "USFDA-PFAS",
}

# ── Method × matrix → EGAD units ─────────────────────────────────────────────

def get_units(method_id, sample_type_code):
    """Return EGAD PARAMETER_UNITS for a method × sample type combination."""
    solid_types = {
        "SL", "SD", "SU", "SUL", "SUU", "AS", "BA", "FA",
        "MEA", "MLK", "EG", "FE", "MU", "SF", "SOF", "FI",
        "CP", "CH", "CO", "FR", "GR", "GRS", "LG", "NRV", "RV",
        "V", "GZ", "G", "HT", "HP", "KD", "LV", "MR", "HM",
        "MA", "MPS", "HN", "HR", "O", "TO", "WH", "WWHG", "WS",
        "SK", "MTB", "BC",
    }
    if sample_type_code in solid_types:
        return "NG/KG"
    return "NG/L"


# ── Date/time formatting (mm/dd/yyyy, hh:mm per EGAD spec) ───────────────────

def _fmt_date(d):
    if d is None:
        return ""
    if isinstance(d, (datetime,)):
        return d.strftime("%m/%d/%Y")
    if isinstance(d, date):
        return d.strftime("%m/%d/%Y")
    return str(d)


def _fmt_time(t):
    if t is None:
        return ""
    if isinstance(t, datetime):
        return t.strftime("%H:%M")
    if isinstance(t, time):
        return t.strftime("%H:%M")
    return str(t)


# ── Row builder ───────────────────────────────────────────────────────────────

def build_row(row_data):
    """
    Convert a row_data dict into an ordered list of 53 cell values.

    row_data keys (all optional except those marked *required*):
      project_site*         — PROJECT/SITE
      sample_point_name*    — SAMPLE_POINT_NAME (use "QC" for QC samples)
      sample_id             — SAMPLE_ID (client-assigned)
      lab_sample_id*        — LAB_SAMPLE_ID (LIMS ID)
      analysis_lab*         — ANALYSIS_LAB (EGAD lab code)
      sample_date*          — datetime or date
      sample_time*          — datetime or time (24h)
      sample_type*          — EGAD SAMPLE_TYPE_LUP code (e.g. GW, MLK)
      qc_type*              — EGAD QA_QC_TYPE_LUP code (e.g. NA, LB, MS)
      result_type_code*     — TRG / TIC / SUR / IS
      cas_no*               — EGAD CAS_NO (digits or DEP#####)
      parameter_name*       — EGAD PARAMETER_NAME
      concentration         — numeric or None (blank = non-detect)
      lab_qualifier         — EGAD CONCENTRATION_QUALIFIER_LUP code
      reporting_limit*      — numeric (RL / MQL)
      parameter_units*      — NG/L, NG/KG, etc.
      pct_recovery          — % RECOVERY (numeric, for QC spikes)
      rpd                   — RPD (numeric, for duplicates)
      test*                 — EGAD TEST_LUP code
      parameter_qualifier   — free text
      parameter_filtered*   — U / NA / FL / FF (default NA)
      sample_collection_method* — EGAD code (LFS / NA for QC)
      sample_location       — EGAD SAMPLE_LOCATION_LUP (NA for QC)
      treatment_status*     — N / T / U / NA
      sampled_by            — text
      idl                   — numeric (Instrument Detection Limit)
      mdl                   — numeric (Method Detection Limit)
      dilution_factor       — numeric (default 1)
      batch_id*             — text/numeric
      sdg*                  — SAMPLE_DELIVERY_GROUP
      analysis_date*        — datetime or date
      analysis_time*        — datetime or time (24h)
      prep_method           — EGAD PREP_METHOD_LUP code (e.g. SW3535)
      prep_date             — datetime or date
      prep_time             — datetime or time
      prep_method2          — second prep (optional)
      prep_date2            — datetime or date
      prep_time2            — datetime or time
      weight_basis          — DW / WW / NA (for solid: DW or WW; water: NA)
      lab_comment           — text
      validation_qualifier  — text
      validation_level      — text
      validation_comment    — text
      validation_comment_type — text
      validation_sql        — numeric
      sample_depth          — numeric
      sample_depth_unit     — text
      sample_depth_interval_top    — numeric
      sample_depth_interval_bottom — numeric
      sample_depth_interval_unit   — text
      radiological_counting_error  — numeric
      sample_type_qualifier        — text or NA
      sample_comment               — text
    """
    g = row_data.get
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
        "" if conc is None else conc,          # blank = non-detect (not zero)
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


# ── Validation ────────────────────────────────────────────────────────────────

def validate_row(row_values, row_number, row_data, data_type="Lab"):
    """
    Check one EDD row against the DATA_ELEMENT_DICTIONARY required fields.
    Returns list of {"row": int, "field": str, "message": str} dicts.
    """
    errors = []
    required = _LAB_REQUIRED if data_type == "Lab" else _QC_REQUIRED
    row_dict = dict(zip(EDD_COLUMNS, row_values))

    qual = str(row_dict.get("LAB_QUALIFIER", "") or "")
    for field in required:
        val = row_dict.get(field)
        if val is None or str(val).strip() == "":
            # CONCENTRATION blank is correct for non-detects (U-qualified)
            if field == "CONCENTRATION" and "U" in qual.upper():
                continue
            errors.append({
                "row": row_number,
                "field": field,
                "message": "Required field is blank",
                "type": data_type,
            })

    # Blocking: PLACEHOLDER CAS
    cas = row_dict.get("CAS_NO", "")
    if str(cas).upper() == "PLACEHOLDER":
        errors.append({
            "row": row_number,
            "field": "CAS_NO",
            "message": (
                "CAS_NO is PLACEHOLDER — this analyte cannot be submitted "
                "until a real CAS or DEP##### code is assigned in EGAD Config"
            ),
            "type": "BLOCKING",
        })

    # Blocking: empty CAS (PFUnDS etc.)
    if not str(cas).strip():
        param = row_dict.get("PARAMETER_NAME", "")
        errors.append({
            "row": row_number,
            "field": "CAS_NO",
            "message": "CAS_NO is empty for {} — enter manually in EGAD Config".format(param),
            "type": "BLOCKING",
        })

    return errors


# ── EDD generation ────────────────────────────────────────────────────────────

def generate_edd(rows_data, config=None):
    """
    Generate EGAD EDD v6.0 CSV from a list of row_data dicts.

    Applies qualifier_map and qc_type_map from config if provided.

    Returns:
        (csv_string, validation_errors)
        validation_errors: list of {"row", "field", "message", "type"} dicts
    """
    if config is None:
        config = {}

    qualifier_map = config.get("qualifier_map", DEFAULT_QUALIFIER_MAP)
    qc_type_map = config.get("qc_type_map", DEFAULT_QC_TYPE_MAP)

    all_errors = []
    csv_rows = [EDD_COLUMNS]  # header row

    for i, rd in enumerate(rows_data, start=1):
        # Translate our qualifier → EGAD code
        our_qual = rd.get("lab_qualifier", "")
        if our_qual and our_qual in qualifier_map:
            rd = dict(rd)
            rd["lab_qualifier"] = qualifier_map[our_qual]

        # Translate our QC type → EGAD code
        our_qc = rd.get("qc_type", "")
        if our_qc and our_qc in qc_type_map:
            rd = dict(rd)
            rd["qc_type"] = qc_type_map[our_qc]

        row_values = build_row(rd)
        csv_rows.append(row_values)

        data_type = "Lab" if rd.get("qc_type", "NA") == "NA" else "QC"
        errors = validate_row(row_values, i, rd, data_type)
        all_errors.extend(errors)

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerows(csv_rows)
    return buf.getvalue(), all_errors


def format_validation_report(errors):
    """Format validation errors as a human-readable text report."""
    if not errors:
        return "Validation PASSED — no errors found.\n"
    lines = ["EGAD EDD Validation Report", "=" * 50, ""]
    blocking = [e for e in errors if e.get("type") == "BLOCKING"]
    regular = [e for e in errors if e.get("type") != "BLOCKING"]
    if blocking:
        lines.append("BLOCKING ERRORS (file cannot be submitted):")
        for e in blocking:
            lines.append("  Row {:3d}  {}: {}".format(e["row"], e["field"], e["message"]))
        lines.append("")
    if regular:
        lines.append("Other errors ({} total):".format(len(regular)))
        for e in regular:
            lines.append("  Row {:3d}  {}: {}".format(e["row"], e["field"], e["message"]))
    return "\n".join(lines) + "\n"


# ── Format spike — validates our output against Appendix 2 examples ──────────

def make_spike_rows():
    """
    Create synthetic PFAS batch rows to validate format against examples.
    One field-sample row (QC_TYPE=NA, RESULT_TYPE_CODE=TRG, non-detect).
    One QC row (QC_TYPE=LB, RESULT_TYPE_CODE=TRG, non-detect).
    One matrix spike row (QC_TYPE=MS, % RECOVERY populated).
    """
    sample_dt = datetime(2026, 6, 15, 9, 0)
    analysis_dt = datetime(2026, 6, 17, 14, 30)
    prep_dt = datetime(2026, 6, 16, 8, 0)

    common = {
        "project_site": "MAIN ST. WATER DEPT.",
        "analysis_lab": "ME001",         # placeholder — set in EGAD Config
        "sample_date": sample_dt,
        "sample_time": sample_dt,
        "sample_type": "GW",
        "analysis_date": analysis_dt,
        "analysis_time": analysis_dt,
        "prep_method": "SW3535",
        "prep_date": prep_dt,
        "prep_time": prep_dt,
        "test": "E537.1",
        "dilution_factor": 1,
        "batch_id": "B20260615-001",
        "sdg": "SDG-2026-001",
        "parameter_filtered": "U",
        "treatment_status": "N",
        "sample_collection_method": "LFS",
        "sample_location": "NA",
        "weight_basis": "NA",
    }

    # Field sample — PFBA, non-detect
    field_row = dict(common)
    field_row.update({
        "sample_point_name": "MW-1",
        "sample_id": "CLIENT-001",
        "lab_sample_id": "PFAS-2026-001",
        "qc_type": "NA",
        "result_type_code": "TRG",
        "cas_no": ANALYTE_CAS_DEFAULTS["PFBA"][0],
        "parameter_name": ANALYTE_CAS_DEFAULTS["PFBA"][1],
        "concentration": None,          # non-detect → blank
        "lab_qualifier": "U",
        "reporting_limit": 2.0,
        "parameter_units": "NG/L",
        "mdl": 0.5,
        "sampled_by": "J. SMITH",
    })

    # Lab blank
    lb_row = dict(common)
    lb_row.update({
        "sample_point_name": "QC",
        "sample_id": "B20260615-001",
        "lab_sample_id": "PFAS-2026-MB01",
        "sample_type": "AQ",
        "qc_type": "LB",
        "result_type_code": "TRG",
        "cas_no": ANALYTE_CAS_DEFAULTS["PFBA"][0],
        "parameter_name": ANALYTE_CAS_DEFAULTS["PFBA"][1],
        "concentration": None,
        "lab_qualifier": "U",
        "reporting_limit": 2.0,
        "parameter_units": "NG/L",
        "mdl": 0.5,
        "sample_collection_method": "NA",
        "sample_location": "NA",
        "treatment_status": "N",
        "sampled_by": "",
    })

    # Matrix spike (LFSM) — detected, with % recovery
    ms_row = dict(common)
    ms_row.update({
        "sample_point_name": "QC",
        "sample_id": "B20260615-001",
        "lab_sample_id": "PFAS-2026-MS01",
        "sample_type": "AQ",
        "qc_type": "MS",
        "result_type_code": "TRG",
        "cas_no": ANALYTE_CAS_DEFAULTS["PFBA"][0],
        "parameter_name": ANALYTE_CAS_DEFAULTS["PFBA"][1],
        "concentration": 10.3,
        "lab_qualifier": "",
        "reporting_limit": 2.0,
        "parameter_units": "NG/L",
        "mdl": 0.5,
        "pct_recovery": 103.0,
        "sample_collection_method": "NA",
        "sample_location": "NA",
        "treatment_status": "N",
        "sampled_by": "",
    })

    return [field_row, lb_row, ms_row]


if __name__ == "__main__":
    print("EGAD EDD v6.0 Format Spike")
    print("=" * 60)

    spike_rows = make_spike_rows()
    csv_str, errors = generate_edd(spike_rows)

    print("\nGenerated CSV (first 3 data rows):")
    print(csv_str)

    report = format_validation_report(errors)
    print("\nValidation report:")
    print(report)

    # Column count check
    lines = csv_str.strip().split("\r\n")
    header = lines[0].split(",")
    print("Column count: {} (expected 53)".format(len(header)))
    assert len(header) == 53, "Column count mismatch!"

    # Verify headers match expected
    for i, (got, want) in enumerate(zip(header, EDD_COLUMNS)):
        if got.strip('"') != want:
            print("  MISMATCH col {}: got {!r}, want {!r}".format(i, got, want))
        else:
            print("  OK col {:2d}: {}".format(i, want))

    print("\nSpike format check complete.")
