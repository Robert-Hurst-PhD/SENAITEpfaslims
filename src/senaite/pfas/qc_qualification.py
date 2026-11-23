# -*- coding: utf-8 -*-
"""
Qualified release — publishing a result that failed a QC criterion.

ISO 17025 §7.8.4 permits releasing non-conforming work when the deviation is
authorised, justified and recorded. A matrix that suppresses a surrogate is a
property of the sample, not a laboratory error: the client gets the result
with a caveat.

What this module owns:

  * the LIBRARY of approved wordings, lab-wide and QAO-editable, keyed by
    (failure type, cause). No certificate wording is hardcoded (§1.1), and it
    stays under QA control rather than being retyped per case.
  * the CAUSE taxonomy — LABORATORY vs MATRIX — and a proposal for each failure
    type, which the QAO confirms or overrides.
  * SCOPING: which analytes on which samples a given failure actually touches.

Scope is deliberately narrow. A surrogate failure qualifies only the analytes
that surrogate quantifies, on the sample it failed in — a blanket qualification
devalues the warning it exists to make.

Python 2.7 (in-Plone add-on).
"""
from __future__ import absolute_import

import json
import logging

try:
    from zope.annotation.interfaces import IAnnotations
except ImportError:         # the library's seeds (library_from) read without Zope
    IAnnotations = None

logger = logging.getLogger("senaite.pfas.qc_qualification")

LIBRARY_KEY = "senaite.pfas.qc_qualification.library"

# Shown when a QC failure has no qualifier configured; names the page to fix it.
UNMAPPED_PROMPT = (
    u"This worksheet failed a quality control check ({failure}) for which no "
    u"certificate qualifier has been configured. The certificate cannot be "
    u"issued until the QAO defines the wording for this failure type under "
    u"Reporting Setup \u2192 QC Qualifiers, or records a "
    u"decision to hold the worksheet."
)

# What the system does with a failure, decided without a human in the loop.
# QUALIFY  attributable to the sample: released with a qualifier and standard
#          wording; re-analysis would give the same answer.
# BLOCK    on material the laboratory prepared and controls (a blank, a
#          calibration standard, a CCV): a laboratory problem, never caveated
#          onto a certificate; the batch is held.
QUALIFY = "qualify"
BLOCK = "block"

# A qualified release stamps each affected analysis with its codes, so the code
# travels with the value. The format is defined here once, its writer
# (format_remark_codes) beside its reader (parse_remark_codes, used by
# browser/reportview.py): SENAITE core prints no per-analysis remarks.
REMARK_PREFIX = u"QC: "


def format_remark_codes(codes):
    """Render qualifier codes as the remark line stamped onto an analysis."""
    clean = sorted({(c or u"").strip() for c in (codes or ()) if (c or u"").strip()})
    if not clean:
        return u""
    return u"{0}{1}".format(REMARK_PREFIX, u", ".join(clean))


def remarks_text(remarks):
    """An analysis' remarks as text. SENAITE hands them back as UTF-8 bytes,
    and the worker's own notes carry non-ASCII (\u00b1): decode before
    joining or splitting, or UnicodeDecodeError drops the qualifier stamp."""
    if remarks is None:
        return u""
    if isinstance(remarks, bytes):
        return remarks.decode("utf-8", "replace")
    return u"%s" % remarks


# A recovery check biased HIGH (above its upper limit) matters only for a
# result at or above the reporting limit: when every result it covers is
# below the reporting limit (a non-detect, or a J value, which counts as
# detected), that failure releases, qualified on the affected analyte by
# the QC Qualifiers library's high-bias entry: its code and its wording,
# under the QAO's control, the note naming the QC type explained once. A
# low bias, or one result at or above the reporting limit, still holds the
# batch, and so does every high bias while the entry holds or has no code.
# The entry ships with a code and a wording, both the QAO's to change; a
# code the QAO clears holds the release again.
HIGH_BIAS = "high_bias"
HIGH_BIAS_STATEMENT = u"Recovery biased high; result below the reporting limit"
HIGH_BIAS_NOTE = u"{qc_type} " + HIGH_BIAS_STATEMENT


def high_bias_note(statement, qc_type):
    """The release note: the QC type, then the library's wording (the seed
    wording when it has none)."""
    return u"{0} {1}".format(qc_type or u"", (statement or u"").strip() or HIGH_BIAS_STATEMENT).strip()

# The QC types whose window is a recovery percentage of a known amount: the
# calibration verifications and the spikes. Nothing else is a bias: a blank's
# concentration, an internal standard's response, a calibrator's deviation
# and an RPD are not, and their failures hold.
RECOVERY_QC_TYPES = (u"CCV", u"ICV", u"LFB", u"LCS", u"LFSM", u"LFSMD")


def is_rpd_row(row):
    """True when the row's value is a relative percent difference (a
    duplicate or LFSMD pair) or the RSD of several spikes: imprecision has
    no direction, so it is never a high bias. The row says so itself: a Dup
    type, a qc_level starting "RPD" or "RSD", or units naming RPD."""
    level = (row.get("qc_level") or u"").split(u" ")[0]
    return (row.get("qc_type") == u"Dup" or level in (u"RPD", u"RSD")
            or u"RPD" in (row.get("units") or u""))


def recovery_pct(row, judged=None):
    """The row's result as a percent recovery, read from the row alone, or
    None when it cannot be. With an expected value the stored value is what
    was measured (a CCV's concentration) and the recovery is value / expected
    x 100; without one, the value is the recovery only when its unit is a
    percent. `judged` rounds the percentage as the checks judge it."""
    try:
        value = float(row.get("value"))
        expected = row.get("expected_value")
        expected = float(expected) if expected not in (None, u"") else None
    except (TypeError, ValueError):
        return None
    if expected:
        pct = value / expected * 100.0
    elif (row.get("units") or u"").strip() == u"%":
        pct = value
    else:
        return None
    if judged is None:
        return pct
    try:
        return float(judged(pct))
    except (TypeError, ValueError, OverflowError):
        return None


def high_bias_release(row, sample_results, judged=None, statement=None):
    """The release note for a failed QC row, or None when the failure holds.

    row: a qc_results row (qc_type, value, expected_value, units,
    limit_high); sample_results: the analyte's sample results it covers,
    [{"keyword", "nondetect", "below_rl", "undecidable"}], below_rl when
    the certificate prints the result below its reporting limit (a
    non-detect or a J value; a J value is detected, not a non-detect),
    undecidable when the LIMS records no role for the sample; judged:
    rounds a percentage as the checks judge it; statement: the library's
    wording (high_bias_note). The note is returned only for a recovery
    check whose recovery is above limit_high when every sample result is
    below the reporting limit, of a field sample (no samples, or one of
    undecidable role, is not a release).
    """
    if row.get("qc_type") not in RECOVERY_QC_TYPES or is_rpd_row(row):
        return None
    recovery = recovery_pct(row, judged)
    try:
        high = float(row.get("limit_high"))
    except (TypeError, ValueError):
        return None
    if recovery is None or not (recovery > high) or not sample_results:
        return None
    if not all(r.get("below_rl") and not r.get("undecidable") for r in sample_results):
        return None
    return high_bias_note(statement, row.get("qc_type") or u"")


# A failing per-injection flag on a field sample -> the QC Summary column it
# qualifies under (these qualify, they do not hold).
# Tags are the pipeline's own issue prefixes (pfas_pipeline/qc_engine.py).
# Below the MDL is not a qualifier: the result is reported as < RL, so "(MDL)" maps to nothing.
INJECTION_FLAG_TAGS = (
    (u"(RT)", u"RT"),
    (u"RT dev", u"RT"),
    (u"(QQ)", u"Ion ratio"),
    (u"(J)", u"S/N"),
    (u"(N.C.)", u"S/N"),
    (u"(SUR)", u"Surrogate"),
)
LABELLED_ROLES = (u"internal standard", u"surrogate")


def injection_flag_qc_types(flag, role=u"", std_role=u""):
    """The QC Summary types a field sample's injection flag qualifies under,
    in order, each once. A recovery tag on a labelled standard is its
    surrogate recovery. An injection standard's flag is never a surrogate
    one: the engine tags an IS response failure "(SUR)" too, and that
    failure is the QC Summary's IS row, which holds."""
    text = flag or u""
    if std_role == u"injection_is":
        return []
    out = []
    for tag, qc_type in INJECTION_FLAG_TAGS:
        if tag in text and qc_type not in out:
            out.append(qc_type)
    if u"(REC)" in text and role in LABELLED_ROLES and u"Surrogate" not in out:
        out.append(u"Surrogate")
    return out


def reported_keyword(analyte, keyword_of):
    """The reported analyte a QC row is about: an isomer component (lr-/br-)
    qualifies its summed analyte; an instrument name maps to the keyword the
    worker pushed it to (`keyword_of`: {instrument analyte: keyword})."""
    name = analyte or u""
    for prefix in (u"lr-", u"br-"):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    return (keyword_of or {}).get(name) or (keyword_of or {}).get(analyte) or name


# field QC that travels with a CoC's samples: its qualifier belongs on them
COC_BLANKS = ("FRB", "TB")


def applies_to_coc(frb_uids, frb_cocs, sample_uid, sample_coc):
    """Whether a field reagent (or trip) blank's qualifier belongs on this
    sample: the other samples of the blank's CoC. An FRB whose CoC
    is not known qualifies every sample of the run -- the conservative
    reading -- and never itself (its detection is the finding)."""
    if sample_uid in (frb_uids or ()):
        return False
    cocs = set(c for c in (frb_cocs or ()) if c)
    if not cocs:
        return True
    return sample_coc in cocs


def applies_to_sample(applies_to, sample_uid, sample_ids, pushed):
    """Whether a qualifier belongs on this sample.

    applies_to  the injection whose sample the failure qualifies (a
                surrogate's own injection, a matrix spike's parent); empty =
                the whole run
    sample_uid  the sample's UID
    sample_ids  names the sample answers to (its id, its Client Sample ID)
    pushed      {injection: set(sample UIDs)} -- where the worker wrote that
                injection's results, the one link that holds for runs whose
                injections are named by Client Sample ID

    One sample's failure is never stamped on every sample of the worksheet."""
    if not applies_to:
        return True
    uids = (pushed or {}).get(applies_to)
    if uids:
        return sample_uid in uids
    return applies_to in [i for i in (sample_ids or ()) if i]


def parse_remark_codes(remarks):
    """Recover the qualifier codes from an analysis' remarks.

    Remarks are free text and carry other things (`SUR`, `N.C.`, instrument
    notes), so only a line beginning with the prefix is read. Returns [] for
    anything else — an unrecognised remark must never become a qualifier on a
    certificate.
    """
    found = []
    for line in remarks_text(remarks).splitlines():
        line = line.strip()
        if not line.startswith(REMARK_PREFIX):
            continue
        for code in line[len(REMARK_PREFIX):].split(u","):
            code = code.strip()
            if code and code not in found:
                found.append(code)
    return found

DISPOSITIONS = (
    (QUALIFY, u"Qualify",
     u"Attributable to the sample. Released with a qualifier and standard "
     u"wording; re-analysis would not change the outcome."),
    (BLOCK, u"Hold",
     u"Occurred on laboratory control material that should always pass. Held "
     u"for investigation or re-analysis; never qualified onto a certificate."),
)

# Injection roles that are LABORATORY control material. A failure on any of
# these blocks regardless of failure type: the lab made the sample, so the lab
# owns the failure. Client material — samples, and the spikes and duplicates
# prepared FROM them — can carry a matrix qualifier.
CONTROL_ROLES = frozenset([
    "MB", "MxB", "LRB", "LFB", "LCS", "CCB", "CAL", "CCV", "ICV", "Standard",
    "Blank", "Quality Control",
])

# (key, label, default disposition, qualifier code), keyed to what the QC
# engine emits. The disposition is a proposal the QAO confirms or overrides.
# Codes extend the set the EDD emits (U, J, B, NC, EMPC); they are drafts the
# QAO approves in the library editor.
FAILURE_TYPES = [
    ("calibration",  u"Calibration curve",                   BLOCK,   u""),
    ("ccv",          u"Continuing calibration verification", BLOCK,   u""),
    ("blank",        u"Blank contamination",                 BLOCK,   u"B"),
    # a laboratory fortified blank / control sample outside its recovery
    # window: the lab's own control failed, so it holds release; no code
    ("lcs",          u"Laboratory control spike recovery",   BLOCK,   u""),
    ("is_response",  u"Internal standard response",          BLOCK,   u""),
    ("surrogate",    u"Surrogate recovery",                  QUALIFY, u"M"),
    ("lfsm",         u"Matrix spike recovery",               QUALIFY, u"M"),
    ("lfsmd",        u"Matrix spike duplicate (RPD)",        QUALIFY, u"P"),
    ("duplicate",    u"Sample duplicate (RPD)",              QUALIFY, u"P"),
    ("ion_ratio",    u"Ion ratio / confirmation",            QUALIFY, u"NC"),
    ("sn",           u"Signal to noise",                     QUALIFY, u"J"),
    ("rt",           u"Retention time",                      QUALIFY, u"NC"),
    # a client sample (Field QC on the CoC): it qualifies the samples of its
    # CoC; "B" is the EDD's code for blank contamination
    ("field_blank",  u"Field reagent blank detection",       QUALIFY, u"B"),
    # a trip blank travels with the samples too: the same treatment
    ("trip_blank",   u"Trip blank detection",                QUALIFY, u"B"),
    # a recovery check biased high on results all below the reporting limit
    # (high_bias_release): released under its own code, shipped as BH and
    # the QAO's to change; a cleared code holds the release. Its code is
    # never the receipt's: a certificate tells the two apart by the code.
    ("high_bias",    u"Recovery biased high, results below the RL", QUALIFY, u"BH"),
    # a sample received out of compliance with its method (receipt
    # temperature, holding time, the shipment): every result of that sample
    # (receipt_compliance)
    ("receipt",      u"Sample receipt not compliant",        QUALIFY, u"H"),
    # a result reported from a dilution the EIS was re-spiked into: a method
    # modification, qualified when the method says so (Lab Workflow,
    # Dilutions); its code is the QAO's to set, none is drafted
    ("respike",      u"Re-spiked dilution",                  QUALIFY, u""),
    # a result whose peak the pair fit split from a co-eluting neighbour
    # (the worker's COELUTION mark): an estimate, qualified for matrix bias
    # or co-elution; the code is a draft the QAO approves
    ("coelution",    u"Co-eluting peaks split",              QUALIFY, u"CE"),
    # reporting rules, not QC failures: the certificate applies them to the
    # result itself (coa_format J_CODE, D_CODE). The lab edits the wording;
    # the code and the disposition are the rule's own.
    ("between_mdl_rl", u"Between MDL and RL",                QUALIFY, u"J"),
    ("dilution",     u"Diluted extract",                     QUALIFY, u"D"),
    # a native whose isotope standard's peak was deleted (coa_format NQ_CODE)
    ("not_quantified", u"Not quantified",                    QUALIFY, u"N.Q."),
    # a result above the calibration range reported from no dilution, the
    # reviewer's reason recorded: "> the top of the range" (coa_format E_CODE)
    ("above_range",  u"Above the calibration range",         QUALIFY, u"E"),
]
REPORTING_RULES = ("between_mdl_rl", "dilution", "not_quantified", "above_range")

# The kinds of exceedance (flag_kinds): one entry each, its code and its
# wording the lab's, shipped blank. A kind holds and qualifies nothing by
# itself (the failure's own entry decides that); it is the code every rule
# of that kind attaches when it fails, once the QAO sets one.
from senaite.pfas import flag_kinds as _flag_kinds                   # noqa: E402
KIND_TYPES = [(_flag_kinds.library_key(k), label) for k, label in _flag_kinds.KINDS]
KIND_KEYS = tuple(k for k, _l in KIND_TYPES)

FAILURE_LABELS = dict((k, label) for k, label, _d, _c in FAILURE_TYPES)
DEFAULT_DISPOSITION = dict((k, d) for k, _l, d, _c in FAILURE_TYPES)
DEFAULT_CODE = dict((k, code) for k, _l, _d, code in FAILURE_TYPES)


def marked_qualifier_rows(items, qual, mark, qc_type, reason):
    """QC Summary qualifier rows for the results whose remarks carry the
    worker's `mark`: that analyte on that sample, with the QAO's code and
    wording. `items` = [{"sample_id", "analyte", "remarks"}]; none while the
    QAO has not set the qualifier."""
    if not qual or qual.get("needs_config"):
        return []
    out = []
    for it in items or []:
        if mark not in (u"%s" % (it.get("remarks") or u"")).split():
            continue
        out.append({"qc_type": qc_type, "applies_to": it.get("sample_id"),
                    "analyte": it.get("analyte"), "reason": reason,
                    "code": qual.get("code") or u"", "statement": qual.get("statement") or u""})
    return out


def respike_qualifier_rows(items, qual):
    """The rows for results the worker marked RESPIKE (reported from a
    re-spiked dilution the method qualifies)."""
    return marked_qualifier_rows(items, qual, u"RESPIKE", u"Re-spiked dilution",
                                 u"reported from a re-spiked dilution")


# the worker's mark on a result whose peak was split from its co-eluting
# partner (pfas_pipeline qc_engine.COELUTION_FLAG, coelution_split)
COELUTION_MARK = u"COELUTION"


def coelution_qualifier_rows(items, qual):
    """The rows for results the worker marked COELUTION: split from a
    co-eluting neighbour by the pair's fit, measured alone where that fit
    failed, or drawn on a drop or skim, so an estimate."""
    return marked_qualifier_rows(items, qual, COELUTION_MARK, u"Co-eluting peaks split",
                                 u"peak split from a co-eluting neighbour")


def disposition_for(failure_type, injection_role=u"", library=None):
    """QUALIFY or BLOCK for a failure, given where it happened.

    Two rules, in order:

    1. A failure on laboratory control material (CONTROL_ROLES) always
       blocks: there is no client matrix to blame.
    2. Otherwise the failure type's configured disposition applies.
    """
    if injection_role and injection_role in CONTROL_ROLES:
        return BLOCK
    if library and failure_type in library:
        configured = (library[failure_type] or {}).get("disposition")
        if configured in (QUALIFY, BLOCK):
            return configured
    return DEFAULT_DISPOSITION.get(failure_type, BLOCK)


# Draft wordings, written from certificate convention, not from a standard:
# what failed, which results it affects, what the reader should conclude. The
# QAO's approval in the library editor makes them authoritative. BLOCK entries
# carry an internal note for the analyst; they never reach a certificate.
DEFAULT_LIBRARY = {
    # the certificate's own reporting rules (REPORTING_RULES)
    "between_mdl_rl": {
        "statement": u"Detected at or above the method detection limit and "
                     u"below the reporting limit; the value is estimated.",
    },
    "dilution": {
        "statement": u"Result from a diluted extract",
    },
    "not_quantified": {
        "statement": u"Not quantified: its isotope standard could not be measured",
    },
    "above_range": {
        "statement": u"Above the calibration range: the value is estimated.",
    },
    "high_bias": {
        "statement": HIGH_BIAS_STATEMENT,
    },
    # the lab's wording
    "receipt": {
        "statement": u"The sample was not received in compliance with the "
                     u"requirements set forth by the method; as a result, the "
                     u"accuracy of the analytical results cannot be "
                     u"guaranteed.",
    },
    "field_blank": {
        "statement": u"The affected analytes were detected in the field "
                     u"reagent blank shipped with these samples above the "
                     u"blank limit. Contamination during sampling or "
                     u"transport cannot be excluded, and the affected "
                     u"results may be biased high.",
    },
    "trip_blank": {
        "statement": u"The affected analytes were detected in the trip "
                     u"blank shipped with these samples above the blank "
                     u"limit. Contamination during transport or storage "
                     u"cannot be excluded, and the affected results may be "
                     u"biased high.",
    },
    "surrogate": {
        "statement": u"Surrogate recovery for the affected analytes fell "
                     u"outside the method acceptance window. This is "
                     u"attributable to the sample matrix rather than to the "
                     u"analysis; re-analysis would be expected to give the "
                     u"same outcome. The accuracy of the affected results "
                     u"cannot be guaranteed and they should be treated as "
                     u"indicative.",
    },
    "lfsm": {
        "statement": u"Matrix spike recovery for the affected analytes fell "
                     u"outside the method acceptance window, indicating that "
                     u"the sample matrix suppresses or enhances the response "
                     u"of these analytes. The accuracy of the affected results "
                     u"cannot be guaranteed and they should be treated as "
                     u"indicative.",
    },
    "lfsmd": {
        "statement": u"Agreement between the matrix spike and its duplicate "
                     u"exceeded the method precision limit, consistent with "
                     u"sample heterogeneity. The precision of the affected "
                     u"results cannot be guaranteed.",
    },
    "duplicate": {
        "statement": u"Agreement between duplicate analyses exceeded the "
                     u"method precision limit, consistent with sample "
                     u"heterogeneity. The precision of the affected results "
                     u"cannot be guaranteed.",
    },
    "ion_ratio": {
        "statement": u"The qualifier-to-quantifier ion ratio for the affected "
                     u"analytes fell outside the method tolerance, most "
                     u"commonly caused by co-eluting sample matrix. "
                     u"Identification could not be confirmed and the affected "
                     u"results should be treated as presumptive.",
    },
    "sn": {
        "statement": u"Sample matrix raised the baseline for the affected "
                     u"analytes, reducing the signal-to-noise ratio below the "
                     u"method minimum. The affected results are estimated and "
                     u"their accuracy near the reporting limit cannot be "
                     u"guaranteed.",
    },
    "rt": {
        "statement": u"Retention time for the affected analytes fell outside "
                     u"the method tolerance, consistent with matrix effects on "
                     u"the chromatography. Identification could not be "
                     u"confirmed and the affected results should be treated as "
                     u"presumptive.",
    },
    # the calculation is named as docs/REFERENCES.md cites it
    "coelution": {
        "statement": u"The affected analytes co-eluted with a neighbouring "
                     u"peak. The two peaks were separated by fitting two "
                     u"exponentially modified Gaussian peaks on one baseline "
                     u"by non-linear least squares; where that fit failed, "
                     u"the peak was measured on its own, and where the "
                     u"analyst split the pair by hand, on a perpendicular "
                     u"drop or a tangent skim. The results are estimates and "
                     u"may be biased by the sample matrix or the co-eluting "
                     u"compound.",
    },
    # Held, never issued. The text is for the analyst.
    "calibration": {
        "statement": u"Calibration did not meet method criteria. Held for "
                     u"laboratory resolution: review the curve, recalibrate "
                     u"and re-analyse the affected sequence.",
    },
    "ccv": {
        "statement": u"Continuing calibration verification fell outside the "
                     u"method window. Held for laboratory resolution: "
                     u"recalibrate and re-analyse the samples bracketed by "
                     u"this CCV.",
    },
    "blank": {
        "statement": u"Analytes were detected in a laboratory blank above the "
                     u"reporting limit. Held for laboratory resolution: "
                     u"identify the contamination source and re-extract the "
                     u"affected batch.",
    },
    "lcs": {
        "statement": u"A laboratory control spike recovered outside the method "
                     u"window. Held for laboratory resolution: investigate the "
                     u"preparation and re-extract the affected batch.",
    },
    "is_response": {
        "statement": u"Injection internal standard response fell outside the "
                     u"method window, indicating an instrument or injection "
                     u"problem. Held for laboratory resolution: re-inject and "
                     u"investigate before release.",
    },
}


# ── Library storage (lab-wide, QAO-editable) ─────────────────────────────────

def get_library(portal):
    """The lab's qualifier library, seeded where it has not been customised.

    One entry per failure type: its disposition, its certificate code and its
    wording. Saved edits win field by field; a field the QAO has not
    overridden follows the seed.
    """
    saved = {}
    raw = IAnnotations(portal).get(LIBRARY_KEY)
    if raw:
        try:
            saved = json.loads(raw)
        except (ValueError, TypeError):
            logger.warning("QC qualifier library unreadable; using defaults")
    return library_from(saved)


def library_from(saved):
    """The library as get_library gives it, from what the QAO saved ({} for
    the seeds alone)."""
    out = {}
    for key, label, disposition, code in FAILURE_TYPES:
        entry = (saved or {}).get(key) or {}
        if key in REPORTING_RULES:
            # a rule's code and disposition are not the lab's to change here
            entry = dict((k, v) for k, v in entry.items() if k == "statement")
        seed = DEFAULT_LIBRARY.get(key) or {}
        out[key] = {
            "key": key,
            "label": label,
            "disposition": entry.get("disposition") or disposition,
            "code": entry.get("code", code),
            "statement": entry.get("statement") or seed.get("statement", u""),
            "customised": bool(entry),
        }
    for key, label in KIND_TYPES:
        entry = (saved or {}).get(key) or {}
        out[key] = {
            "key": key,
            "label": label,
            "disposition": QUALIFY,
            "code": (entry.get("code") or u"").strip(),
            "statement": (entry.get("statement") or u"").strip(),
            "customised": bool(entry),
            "kind": True,
        }
    return out


def save_library(portal, data):
    """Store only what differs from the seed."""
    # a strict store: no history entry, no save
    from senaite.pfas import config_history
    config_history.track(portal, 'qc_qualifiers', "library", lambda: get_library(portal), label=u"QC qualifier wording")
    trimmed = {}
    for key, _label, disposition, code in FAILURE_TYPES:
        entry = (data or {}).get(key) or {}
        if key in REPORTING_RULES:
            entry = {"statement": entry.get("statement")}
        seed_text = (DEFAULT_LIBRARY.get(key) or {}).get("statement", u"")
        diff = {}
        if (entry.get("disposition") or disposition) != disposition:
            diff["disposition"] = entry["disposition"]
        if entry.get("code", code) != code:
            diff["code"] = entry.get("code", code)
        if (entry.get("statement") or u"").strip() != seed_text.strip():
            diff["statement"] = entry.get("statement") or u""
        if diff:
            trimmed[key] = diff
    for key, _label in KIND_TYPES:
        entry = (data or {}).get(key) or {}
        diff = dict((f, (entry.get(f) or u"").strip()) for f in ("code", "statement")
                    if (entry.get(f) or u"").strip())
        if diff:
            trimmed[key] = diff
    IAnnotations(portal)[LIBRARY_KEY] = json.dumps(trimmed)
    return trimmed


# ── A labelled compound's role ───────────────────────────────────────────────

def _labelled_role(analyte, method_id):
    """"surrogate" or "is_response" for a labelled compound, per the METHOD's
    labelled-standards grid."""
    from bika.lims import api
    from senaite.pfas import labelled_standards
    from senaite.pfas.method_profile_store import get_profile
    roles = labelled_standards.roles(get_profile(api.get_portal(), method_id) or {})
    for name, role in roles.items():
        if _same_compound(name, analyte):
            return {"injection_is": "is_response", "surrogate": "surrogate"}.get(role, u"")
    return u""


def qualifier_for(portal, failure_type, injection_role=u""):
    """The qualifier to apply, or None when the failure must be held.

    No human in the loop: the QAO's control is the library, not a per-result
    approval. Returns the code, the wording and why it was chosen, so the
    certificate and the audit trail say the same thing.
    """
    library = get_library(portal)
    entry = library.get(failure_type)

    # A failure nobody has mapped, or one mapped with no wording, is neither
    # released under a qualifier nobody chose nor held unexplained: say what
    # is missing and where to fix it.
    if not entry or (entry.get("disposition") == QUALIFY
                     and not (entry.get("statement") or u"").strip()):
        return {
            "failure_type": failure_type or u"(unrecognised)",
            "label": (entry or {}).get("label")
                     or FAILURE_LABELS.get(failure_type, u"Unmapped QC failure"),
            "code": u"",
            "statement": u"",
            "needs_config": True,
            "prompt": UNMAPPED_PROMPT.format(
                failure=(entry or {}).get("label")
                        or failure_type or u"an unrecognised check"),
        }

    disposition = disposition_for(failure_type, injection_role, library)
    if disposition == BLOCK:
        return None
    return {
        "failure_type": failure_type,
        "label": entry["label"],
        "code": entry["code"],
        "statement": entry["statement"],
        "needs_config": False,
    }


HIGH_BIAS_NO_CODE = (
    u"A recovery check ran high on results below the reporting limit. Its "
    u"release needs a certificate code: the QAO sets one for \u201c{failure}\u201d "
    u"under Reporting Setup \u2192 QC Qualifiers, or holds it there."
)


def high_bias_qualifier(portal):
    """The library's high-bias entry as qualifier_for gives it: None when
    the QAO holds the release, needs_config when it has no wording or no
    code (a release is marked on its results by its code)."""
    found = qualifier_for(portal, HIGH_BIAS)
    if found is None or found.get("needs_config"):
        return found
    if not (found.get("code") or u"").strip():
        return dict(found, needs_config=True, prompt=HIGH_BIAS_NO_CODE.format(failure=found.get("label")))
    return found


# ── Scoping ──────────────────────────────────────────────────────────────────

# the failures recorded against a labelled compound, whose natives the
# method's surrogate map names (analytes_for_failure)
MAPPED_FAILURES = ("surrogate", "is_response")


def surrogate_map(method_id):
    """The method's native -> surrogate map, from the stored profile's rows;
    {} when it has none. A native on a composite standard maps to its
    members' list: a failure of any member reaches it."""
    from bika.lims import api
    from senaite.pfas.method_profile_store import get_profile
    return map_of(get_profile(api.get_portal(), method_id) or {})


def map_of(profile):
    """surrogate_map's reading of one profile (composite_standards.members)."""
    from senaite.pfas import composite_standards as cmp
    out = {}
    for row in (profile.get("surrogate_map") or []):
        analyte = (row.get("analyte") or "").strip()
        surrogate = (row.get("surrogate_is") or "").strip()
        if analyte and surrogate:
            members = cmp.members(profile, surrogate)
            out[analyte] = members if members != [surrogate] else surrogate
    return out


def analytes_for_failure(failure_type, analyte, method_id="", mapping=None):
    """Which reported analytes a failure on `analyte` actually affects.

    An IS or surrogate failure is recorded against the LABELLED compound, but
    what the client reads is the natives that compound quantifies — so the
    method's surrogate map is reversed to find them. Everything else affects
    the analyte it was raised on. `mapping` is the method's map when the
    caller has read it already (surrogate_map); else it is read here.
    """
    if failure_type not in MAPPED_FAILURES:
        return [analyte] if analyte else []
    if mapping is None:
        mapping = surrogate_map(method_id)
    n2k = _name_to_keyword() if mapping else None
    def on(surrogate):
        # a composite's members, each its own compound
        return any(_same_compound(s, analyte, n2k) for s in
                   (surrogate if isinstance(surrogate, (list, tuple)) else [surrogate]) if s)
    natives = sorted(set(native for native, surrogate in mapping.items() if surrogate and on(surrogate)))
    return natives or ([analyte] if analyte else [])


def _name_to_keyword():
    """{compound name: keyword} from the compound library."""
    from senaite.pfas import compound_library, compound_library_store
    return compound_library.name_to_keyword(compound_library_store.library())


def _same_compound(a, b, n2k=None):
    """Compare labelled-compound names across spellings (13C3-HFPO-DA /
    13C3-GenX (HFPO-DA); supplier codes): the compound library's names,
    the services' PFAS tab. `n2k` is the library's
    name -> keyword map when the caller has read it (_name_to_keyword)."""
    if not a or not b:
        return False
    if a == b:
        return True
    if n2k is None:
        n2k = _name_to_keyword()
    if n2k is None:
        return False
    return n2k.get(a, a) == n2k.get(b, b)


