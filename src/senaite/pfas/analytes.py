# -*- coding: utf-8 -*-
"""
PFAS Analyte Registry
Extracted from FDA_Sample_Calculator_V13.xlsm shared strings and DATA table.
Contains every analyte, its MRM transitions, linked IS, and per-matrix QC criteria.
"""

# ── Target analytes ──────────────────────────────────────────────────────────
# (name, quan_mrm, qual_mrm_list)
PFAS_ANALYTES = [
    ("10:2 FTS",         "626.83>81.03",  ["626.83>606.92"]),
    ("11Cl-PF3OUdS",     "630.92>450.92", ["630.92>83.06"]),
    ("4:2 FTS",          "326.94>81.10",  ["326.94>306.97"]),
    ("6:2FTS",           "426.92>81.02",  ["426.92>406.99"]),
    ("8:2 FTS",          "527.03>81.06",  ["527.03>507.07"]),
    ("9Cl-PF3ONS",       "530.93>350.89", ["530.93>82.96"]),
    ("GenX (HFPO-DA)",   "285.00>169.00", ["285.00>119.00", "285.00>185.00"]),
    ("PFBA",             "213.04>168.98", ["213.04>18.99"]),
    ("PFBS",             "299.00>80.02",  ["299.00>98.99"]),
    ("PFDA",             "512.96>469.01", ["512.96>268.98", "512.96>168.99"]),
    ("PFDoA",            "612.94>569.04", ["612.94>168.97"]),
    ("PFDoS",            "698.86>80.00",  ["698.86>98.96"]),
    ("PFDS",             "598.99>80.03",  ["598.99>98.92"]),
    ("PFHpA",            "362.90>319.00", ["362.90>169.02"]),
    ("PFHpS",            "448.90>80.03",  ["448.90>98.96"]),
    ("PFHxA",            "312.97>268.98", ["312.97>119.03"]),
    ("PFHxDA",           "812.96>768.93", ["812.96>168.88"]),
    ("PFHxS",            "398.85>79.98",  ["398.85>98.97"]),   # key analyte
    ("PFNA",             "462.86>418.93", ["462.86>269.02", "462.86>218.98"]),  # key
    ("PFNS",             "549.01>80.00",  ["549.01>98.92"]),
    ("PFOA",             "376.86>251.00", ["376.86>85.02"]),   # key analyte
    ("PFODA",            "912.93>868.89", ["912.93>218.94", "912.93>169.01"]),
    ("PFOS",             "498.92>80.02",  ["498.92>98.94"]),   # key analyte
    ("PFPeA",            "263.01>218.97", ["263.01>18.99"]),
    ("PFPeS",            "348.94>80.01",  ["348.94>98.92"]),
    ("PFTeDA",           "712.75>668.90", ["712.75>218.91", "712.75>169.01"]),
    ("PFTrDA",           "662.79>618.98", ["662.79>218.93", "662.79>169.02"]),
    ("PFTrDS",           "748.73>80.00",  ["748.73>98.94"]),
    ("PFUnDS",           "562.85>518.94", ["562.85>269.00", "562.85>169.02"]),
    ("PFUDA",            "648.82>80.04",  ["648.82>98.91"]),
    ("DONA",             "412.91>368.99", ["412.91>219.01"]),
    ("FOSA",             "498.92>80.02",  ["498.92>98.94"]),
    ("br-PFHxS",         "398.85>79.98",  ["398.85>98.97"]),
    ("br-PFOS",          "498.92>80.02",  ["498.92>98.94"]),
    ("lr-PFHxS",         "398.85>79.98",  ["398.85>98.97"]),
    ("lr-PFOS",          "498.92>80.02",  ["498.92>98.94"]),
]

# Key analytes with tighter criteria (PFOS, PFNA, PFHxS, PFOA in certain matrices)
KEY_ANALYTES = {"PFOS", "PFNA", "PFHxS", "PFOA"}

# Non-isotopically linked analytes (looser QQ criteria)
NON_ISO_ANALYTES = {
    "9Cl-PF3ONS", "11Cl-PF3OUdS", "PFDoS", "PFDS", "PFNS",
    "PFODA", "PFPeS", "PFTrDA", "PFTrDS", "PFUnDS"
}

# ── Internal standards ────────────────────────────────────────────────────────
INTERNAL_STANDARDS = [
    "13C2,D4-10:2FTS",
    "13C3-PFHxS",
    "13C2,D4-4:2FTS",
    "13C2,D4-6:2FTS",
    "13C2,D4-8:2FTS",
    "13C2-PFDA",
    "13C2-PFDoA",
    "13C2-PFHxDA",
    "13C2-PFTeDA",
    "13C2-PFUDA",
    "13C3-GenX (HFPO-DA)",
    "13C3-PFBA",
    "13C3-PFBS",
    "13C3-PFPeA",
    "13C4-PFHpA",
    "13C4-PFOA",
    "13C5-PFHxA",
    "13C5-PFNA",
    "13C8-FOSA",
    "13C8-PFOA",
    "13C8-PFOS",
]

# ── MRM transitions for IS ────────────────────────────────────────────────────
IS_MRM = {
    "13C2,D4-10:2FTS":      ("632.92>81.99",  ["632.92>612.11"]),
    "13C3-PFHxS":           ("401.91>80.00",  ["401.91>98.97"]),
    "13C2,D4-4:2FTS":       ("332.95>82.01",  ["332.95>311.97"]),
    "13C2,D4-6:2FTS":       ("432.90>82.02",  ["432.90>412.00"]),
    "13C2,D4-8:2FTS":       ("532.94>82.05",  ["532.94>512.00"]),
    "13C2-PFDA":            ("514.96>469.97", ["514.96>270.00"]),
    "13C2-PFDoA":           ("614.94>570.03", ["614.94>169.03"]),
    "13C2-PFHxDA":          ("814.85>769.99", ["814.85>218.91", "814.85>169.08"]),
    "13C2-PFTeDA":          ("714.86>670.00", ["714.86>169.10"]),
    "13C2-PFUDA":           ("564.94>520.02", ["564.94>269.00", "564.94>169.05"]),
    "13C3-GenX (HFPO-DA)":  ("287.02>168.97", ["287.02>185.31"]),
    "13C3-PFBA":            ("215.90>171.98", ["215.90>18.99"]),
    "13C3-PFBS":            ("302.01>80.05",  ["302.01>99.00"]),
    "13C3-PFPeA":           ("265.98>221.99", ["265.98>18.99"]),
    "13C4-PFHpA":           ("366.90>321.90", ["366.90>169.00"]),
    "13C4-PFOA":            ("380.87>336.01", ["380.87>169.01"]),
    "13C5-PFHxA":           ("317.94>272.99", ["317.94>120.04"]),
    "13C5-PFNA":            ("467.94>422.99", ["467.94>222.98", "467.94>219.00"]),
    "13C8-FOSA":            ("505.96>78.05",  ["505.96>171.99"]),
    "13C8-PFOA":            ("420.95>376.00", ["420.95>171.98"]),
    "13C8-PFOS":            ("506.97>79.98",  ["506.97>98.94"]),
}

# ── QC Acceptance Criteria ─────────────────────────────────────────────────────
# From workbook strings: "65 - 135 %", "40 - 140 %", "80 - 120 %", "≤ 25 %", "≤ 30 %"
# Calibration % deviation: ≤ 20%, ≤ 25%, ≤ 30% depending on analyte/level

class QCCriteria:
    """
    FDA PFAS in Food and Feed acceptance criteria.
    From workbook QC Criteria table (strings 91-112).
    """

    # ── Calibration ────────────────────────────────────────────────────────────
    CAL_PCT_DEVIATION = {
        "default":  25.0,   # ≤ 25 % deviation from curve
        "tight":    20.0,   # ≤ 20 % (first/last cal level)
        "loose":    30.0,   # ≤ 30 % (BLoQ levels)
    }
    CAL_R2_MIN = 0.995      # minimum R² for calibration curve

    # ── IS Response ────────────────────────────────────────────────────────────
    IS_RESPONSE_PCT = 50.0  # ± 50 % of batch average triggers IS flag

    # ── RT Deviation ───────────────────────────────────────────────────────────
    RT_TOLERANCE_MIN = 0.10  # ± 0.10 min absolute
    RT_TOLERANCE_PCT = 5.0   # ± 5 % relative (use whichever is wider)

    # ── Qual/Quan Ion Ratio ─────────────────────────────────────────────────────
    # Matching mass-label (isotopically linked) analytes: tighter
    QQ_RATIO_MATCHING_PCT = 20.0    # ≤ 20 % deviation from expected (** analytes)
    # Key analytes (PFOS/PFNA/PFHxS/PFOA) in Egg, Muscle, Fish
    QQ_RATIO_KEY_PCT = 25.0         # ≤ 25 %
    # Non-isotopically linked analytes (*** group)
    QQ_RATIO_NON_ISO_PCT = 30.0     # ≤ 30 %

    # ── Signal to Noise ────────────────────────────────────────────────────────
    SN_MIN = 3.0            # minimum S/N for detection
    SN_QUAN_MIN = 10.0      # minimum S/N for quantitation (above RL)

    # ── LFSM/LFSMD Recovery ────────────────────────────────────────────────────
    # Two-tier: depends on analyte group and matrix
    # Key analytes (PFOS, PFNA, PFHxS, PFOA) in Egg/Muscle/Fish
    LFSM_RECOVERY_KEY_MATRIX = (65.0, 135.0)   # "65 - 135 %"
    # All other isotopically linked analytes
    LFSM_RECOVERY_MATCHING = (40.0, 140.0)     # "40 - 140 %"
    # Surrogate/IS internal recovery criteria
    LFSM_RECOVERY_SUR = (80.0, 120.0)          # "80 - 120 %"

    # ── RPD (LFSMD duplicate, sample duplicate) ─────────────────────────────
    RPD_MAX = 30.0          # ≤ 30 % relative percent difference

    # ── MDL ───────────────────────────────────────────────────────────────────
    MDL_MIN_REPS = 7        # minimum replicates for MDL study
    MDL_T_CONFIDENCE = 0.99 # one-tailed t at 99 % (EPA MDL procedure)

    # ── Method Blank ──────────────────────────────────────────────────────────
    # If blank ≥ sample → flag <LOD
    # If blank > RL → flag contamination

    @classmethod
    def lfsm_criteria(cls, analyte, matrix):
        """Return (low, high) acceptance window for LFSM recovery."""
        matrix_upper = matrix.upper()
        is_key = analyte in KEY_ANALYTES
        is_bio_matrix = any(m in matrix_upper for m in ("EGG", "MUSCLE", "FISH", "MEAT"))
        if is_key and is_bio_matrix:
            return cls.LFSM_RECOVERY_KEY_MATRIX
        return cls.LFSM_RECOVERY_MATCHING

    @classmethod
    def qq_criteria(cls, analyte):
        """Return max % deviation for qual/quan ion ratio."""
        if analyte in NON_ISO_ANALYTES:
            return cls.QQ_RATIO_NON_ISO_PCT
        if analyte in KEY_ANALYTES:
            return cls.QQ_RATIO_KEY_PCT
        return cls.QQ_RATIO_MATCHING_PCT


# ── Calibration levels from batch ─────────────────────────────────────────────
# Concentrations (ng/mL) extracted from sample descriptions
CAL_LEVELS = {
    "FDA-CAL-1":  0.039,
    "FDA-CAL-2":  0.078,
    "FDA-CAL-3":  0.156,
    "FDA-CAL-4":  0.313,
    "FDA-CAL-5":  0.625,
    "FDA-CAL-6":  1.25,
    "FDA-CAL-7":  2.50,
    "FDA-CAL-8":  5.0,
    "FDA-CAL-9":  10.0,
    "FDA-CAL-10": 20.0,
    "FDA-ICV":    1.25,   # Initial Calibration Verification
    "FDA-CCV":    1.25,   # Continuing Calibration Verification
}

# ── Injection name patterns (from VBA ValidateInjectionNames) ─────────────────
import re

INJECTION_PATTERNS = [
    # Pattern 1: FDA-XXX-XX-YYMMDD
    re.compile(r'^FDA-[A-Z0-9]+-[A-Z0-9]+-\d{6}$'),
    # Pattern 2: FDA-XXX-YYMMDD
    re.compile(r'^FDA-[A-Z0-9]+-\d{6}$'),
    # Pattern 3: Initials Type,Matrix YYYY-MM-DD-#######
    # e.g. "KCP Water MB 2026-03-13-01"
    re.compile(r'^[A-Z]{2,4} [A-Za-z\s\"]+ (MB|LCS|CCV|ICV|LFSM|LFSMD|Dup|CAL|Sample)\b.*$'),
    # Pattern 4: Initials Type,Matrix #######  (7-digit StarLIMS)
    re.compile(r'^[A-Z]{2,4} [A-Za-z\s]+ (MB|LCS|CCV|ICV|LFSM|LFSMD|Dup|CAL) \d{7}$'),
]

# Shortcode → human label mapping
# Keys are the canonical shortcodes used throughout the pipeline and UI.
# Full text names are avoided in code to prevent typos.
QC_TYPE_CODES = {
    "CAL":    "Calibration Standard",
    "ICV":    "Initial Calibration Verification",
    "CCV":    "Continuing Calibration Verification",
    "LCS":    "Laboratory Control Sample",
    "MB":     "Method Blank",
    "MxB":    "Matrix Blank",
    "LRB":    "Lab Reagent Blank",
    "LFSM":   "Lab Fortified Sample Matrix",
    "LFSMD":  "Lab Fortified Sample Matrix Duplicate",
    "Dup":    "Sample Duplicate",
    "Sample": "Environmental Sample",
}

# Reverse map: canonical label → shortcode
QC_LABEL_TO_CODE = {v: k for k, v in QC_TYPE_CODES.items()}

STARLIMS_RE = re.compile(r'\b(\d{7})\b')

# Order matters: longer/more-specific codes must be checked before substrings
_QC_PRIORITY = [
    "LFSMD", "LFSM", "CCV", "ICV", "CAL",
    "MxB", "LRB", "MB", "LCS", "Dup",
]


def _scan_for_qc_code(text):
    """Return the first QC shortcode found in text, or None."""
    upper = text.upper()
    for code in _QC_PRIORITY:
        # Require word boundary or end-of-token for short codes (MB, Dup)
        # to avoid matching inside longer words
        if code in ("MB", "LRB", "LCS", "Dup"):
            # Only match if surrounded by non-alpha or at string boundary
            import re as _re
            if _re.search(r'(?<![A-Za-z])' + re.escape(code) + r'(?![A-Za-z])',
                          text, _re.IGNORECASE):
                return code
        else:
            if code.upper() in upper:
                return code
    return None


def parse_sample_description(desc):
    """
    Parse the `Sample Description` field into structured metadata.

    Field format (semicolon-delimited, quoted sections stripped):
      Analyst; Date[-BatchNum]; [Matrix; ][SampleID; ][Spike; ]QC_type [Level]

    Examples:
      "KCP; 2026-02-26; 0.039 ppt; CAL"
      "RH; 2026-02-26-01; CCV"
      "RH; Ext. 2026-04-09-01; Milk; MB"
      "RH; Ext. 2026-04-09-01; Milk; 'FAPAS QC 06162 CRM'; MxB"
      "RH; Ext. 2026-04-09-01; Mik; '87BT1-1310-GS1-11/12/25'; 10 ppt; LFSM Low"

    Returns dict with keys: analyst, run_date, matrix, sample_id,
                             spike_level, qc_type (shortcode), qc_label.
    """
    if not desc or str(desc).strip().lower() in ("", "nan", "none"):
        return {}

    # Split on semicolons; strip whitespace and enclosing quotes/spaces
    parts = [p.strip().strip('"').strip("'").strip() for p in str(desc).split(";")]
    result = {}

    if parts:
        result["analyst"] = parts[0].strip()

    # Extract run date from any part
    for part in parts[1:3]:
        m = re.search(r"(\d{4}-\d{2}-\d{2})", part)
        if m:
            result["run_date"] = m.group(1)
            break

    # Find QC type code — scan each part from the end first
    qc_code = None
    for part in reversed(parts):
        code = _scan_for_qc_code(part)
        if code:
            qc_code = code
            break

    if qc_code:
        result["qc_type"] = qc_code
        result["qc_label"] = QC_TYPE_CODES.get(qc_code, qc_code)
    elif any("sample" in p.lower() for p in parts):
        result["qc_type"] = "Sample"
        result["qc_label"] = "Environmental Sample"

    # Matrix identification
    _matrices = ("milk", "water", "egg", "fish", "meat", "feed", "food",
                 "serum", "urine", "plasma", "soil", "sediment")
    for part in parts:
        if any(m in part.lower() for m in _matrices):
            result["matrix"] = part.strip()
            break

    # Spike level (e.g. "10 ppt")
    for part in parts:
        if "ppt" in part.lower() or "ppb" in part.lower() or "ppm" in part.lower():
            result["spike_level"] = part.strip()
            break

    return result


def classify_injection(name, sample_description=None):
    """
    Return the QC type shortcode for an injection.

    Checks both the Injection Name and Sample Description fields.
    Returns one of: CAL ICV CCV LCS MB MxB LRB LFSM LFSMD Dup Sample
    """
    # Parse Sample Description first — more reliable source
    if sample_description:
        info = parse_sample_description(sample_description)
        code = info.get("qc_type")
        if code and code != "Sample":
            return code

    # Fall back to Injection Name pattern matching
    if name:
        code = _scan_for_qc_code(str(name))
        if code:
            return code

    return "Sample"


def validate_injection_name(name):
    """
    Validate injection name against FDA PFAS naming conventions.
    Returns dict with keys: valid, pattern, qc_type (shortcode), starlims_id, name.
    """
    name = str(name).strip()
    for i, pat in enumerate(INJECTION_PATTERNS, 1):
        if pat.match(name):
            qc_type = _scan_for_qc_code(name) or "Sample"
            starlims_match = STARLIMS_RE.search(name)
            return {
                "valid": True,
                "pattern": i,
                "qc_type": qc_type,
                "qc_label": QC_TYPE_CODES.get(qc_type, qc_type),
                "starlims_id": starlims_match.group(1) if starlims_match else None,
                "name": name,
            }
    return {
        "valid": False,
        "pattern": None,
        "qc_type": None,
        "starlims_id": None,
        "name": name,
        "error": "Does not match any FDA PFAS naming convention: '{}'".format(name),
    }
