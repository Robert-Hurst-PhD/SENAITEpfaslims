"""
Typed data models for every entity in the PFAS QC pipeline.
Typed records the worker passes between import, QC, summary and push.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


# ─────────────────────────────────────────────────────────────────────────────
# Raw instrument row  (one row of the DATA table from MassLynx/Analyst export)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class InstrumentRow:
    """One row from the instrument CSV export = one compound × one injection."""
    compound_name:       str
    compound_type:       str            # "Target", "Qualifier", "IS", etc.
    compound_group:      str
    sample_description:  str
    injection_name:      str
    sample_group:        str
    sample_type:         str            # "Standard", "QC", "Unknown", etc.
    included_in_cal:     bool
    level:               Optional[str]
    linked_is:           Optional[str]
    cal_ref_compound:    Optional[str]
    observed_rt:         Optional[float]
    rt_relative_to_is:   Optional[float]
    response:            Optional[float]
    is_response:         Optional[float]
    response_ratio:      Optional[float]   # used by the IS-response and ion-ratio checks
    expected_conc:       Optional[float]
    calculated_conc:     Optional[float]   # col 26 → Calibration %
    pct_deviation:       Optional[float]   # col 27 → % from CAL (IS Raw sheet)
    pct_recovery_is:     Optional[float]
    ion_ratios:          Optional[str]
    expected_ion_ratios: Optional[str]
    r2:                  Optional[float]
    signal_to_noise:     Optional[float]
    qual_sn:             Optional[float]
    quant_status:        Optional[str]
    reporting_limit:     Optional[float]
    measured_conc:       Optional[float]
    acquisition_datetime: Optional[datetime]
    concat_id:           str             # injection_name|yyyymmddHHMMSS  (unique key)
    manual_changes:      Optional[str]   = None
    # the decision (manual_integration.is_manual with the import profile's
    # markers); None = the export carried no manual-integration column
    manual_integration:  Optional[bool]  = None
    injection_volume:    Optional[float] = None
    sample_position:     Optional[str]   = None
    # The instrument's own verdict on the concentration cell: "BLoQ", "ALoQ",
    # "N.D." or "". Distinct from a computed qualifier — "BLoQ" means detected
    # but below quantitation, which is not the same claim as "not detected".
    conc_qualifier:      str             = ""
    # The unit the instrument reports the concentration in ("ng/mL"). Mapped
    # in _COL_MAP all along but never carried onto the row, so nothing could
    # check a spike level or a reporting limit against it.
    conc_units:          str             = ""
    # Ion-ratio redundancy: software versions name the
    # expected ratio differently, and some exports give only the method's;
    # the qualifier responses let the ratio be computed when the ratio
    # column is empty (ratio = qualifier response / quantifier response).
    quan_ref_expected_ion_ratios: Optional[str] = None
    method_expected_ion_ratios:   Optional[str] = None
    qual_ions_responses:          Optional[str] = None


def reported_conc(row) -> "float | None":
    """The ONE definition of an injection row's reportable concentration.

    ``calculated_conc`` is the value after the instrument has applied the
    sample factor (dilution / weight); ``measured_conc`` is the raw reading off
    the calibration curve. The reported result is the corrected one.

    This existed twice with opposite precedence — ``build_summary`` took the
    raw value while ``injection_store`` took the corrected one — so a 1:10
    dilution was reported ten times high on the summary and correctly in the
    review pages. Both now call this.

    The fall-back to ``measured_conc`` covers a genuinely BLANK reported cell.
    It must NOT override a cell the instrument filled in with a verdict: on a
    real export ``br-PFHxS`` carried "Not Detected" as its calculated
    concentration and 0.000188 as its raw curve reading, and falling through
    resurrected a number the instrument had explicitly declined to report.
    """
    if getattr(row, "calculated_conc", None) is not None:
        return row.calculated_conc
    if getattr(row, "conc_qualifier", ""):
        return None
    return getattr(row, "measured_conc", None)


# ─────────────────────────────────────────────────────────────────────────────
# QC Flag  (one row of QCLogTable / Sheet 6)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class QCFlag:
    source:         str     # "IS Raw", "RT Deviation", "Calibration %", etc.
    analyte:        str
    injection_name: str
    value:          str     # displayed value (numeric or N.D. etc.)
    issue:          str     # "(SUR)", "(CAL)", "(REC)", "(N.C.)", etc.
    link:           str = ""
    # WHICH CHECK RAISED THIS, as an identity rather than as display text.
    #
    # `source` is shown to a human and reads better with the method in it
    # ("FDA_32PFAS Calibration"). Control flow used to match on `source`
    # exactly, so the moment the profiled checks started prefixing the method,
    # every calibration / r2 / CCV / RT review check began reporting AUTO_PASS
    # while carrying flags. One field cannot be both a label and a key.
    check_kind:     str = ""

    def as_dict(self) -> dict:
        return {
            "Source":         self.source,
            "Analyte":        self.analyte,
            "Injection Name": self.injection_name,
            "Value":          self.value,
            "Issue":          self.issue,
            "Link":           self.link,
        }


# ─────────────────────────────────────────────────────────────────────────────
# IS Raw result  (one cell of IS Raw sheet)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class ISRawResult:
    is_compound:    str
    injection_name: str
    concat_id:      str
    response:       Optional[float]
    pct_from_cal:   Optional[float]   # response / average_response  (col D formula)
    average_response: Optional[float]
    flag:           Optional[QCFlag]  = None
    # : the window the check applied, whether the METHOD configured
    # it (False = the built-in fallback: reported as "no criterion"), and the
    # standard's role in the method's grid
    window_min:     Optional[float] = None
    window_max:     Optional[float] = None
    configured:     bool = False
    std_role:       str = ""
    # the % as judged: a whole percent by the method's rule
    judged_pct:     Optional[float] = None
    # EPA 537.1 §9.3.4's second condition: % of the bracket's CCV response
    ccv_min:        Optional[float] = None
    ccv_max:        Optional[float] = None


# ─────────────────────────────────────────────────────────────────────────────
# RT Deviation result  (one cell of RT Deviation sheet)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class RTResult:
    analyte:        str
    injection_name: str
    concat_id:      str
    observed_rt:    Optional[float]
    average_rt:     Optional[float]
    pct_deviation:  Optional[float]   # (observed/average) - 1
    flag:           Optional[QCFlag]  = None


# ─────────────────────────────────────────────────────────────────────────────
# Qual-Quan result  (one cell of Qual-Quan sheet)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class QualQuanResult:
    analyte:             str
    injection_name:      str
    concat_id:           str
    response_ratio:      Optional[float]
    avg_response_ratio:  Optional[float]   # average from calibration curve
    pct_of_cal:          Optional[float]   # response_ratio / avg_response_ratio
    flag:                Optional[QCFlag]  = None


# ─────────────────────────────────────────────────────────────────────────────
# Calibration % result  (one cell of Calibration % sheet)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class CalibrationResult:
    analyte:         str
    injection_name:  str
    concat_id:       str
    r2:              Optional[float]
    calculated_conc: Optional[float]
    pct_deviation:   Optional[float]
    flag:            Optional[QCFlag]  = None
    # the ±% this calibrator was judged against (the lowest level's own
    # limit where the method sets one); None = not judged
    limit:           Optional[float]   = None
    r2_min:          Optional[float]   = None
    lowest:          bool              = False    # judged by the lowest level's limit


# ─────────────────────────────────────────────────────────────────────────────
# LFSM Recovery result
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class LFSMResult:
    analyte:          str
    lfsm_injection:   str
    parent_injection: str
    spike_value_ppt:  float
    fortified_conc:   float
    unfortified_conc: float
    recovery_pct:     float
    flag:             Optional[QCFlag] = None
    # the window it was judged in ({lo, hi, basis}; recovery_check_profiled)
    window:           Optional[dict] = None

    @property
    def passes(self) -> bool:
        return self.flag is None


@dataclass
class LFSMDResult:
    analyte:          str
    lfsm_injection:   str
    lfsmd_injection:  str
    recovery_lfsm:    float
    recovery_lfsmd:   float
    rpd_pct:          float
    flag:             Optional[QCFlag] = None
    # the duplicate's own recovery, judged against the LFSM window at the
    # LFSM's spike level; None = not judged
    recovery_flag:    Optional[QCFlag] = None
    recovery_judged:  bool = False
    # the limits applied: the RPD's and the duplicate's own recovery window
    window:           Optional[dict] = None
    recovery_window:  Optional[dict] = None

    @property
    def passes(self) -> bool:
        return self.flag is None and self.recovery_flag is None


# ─────────────────────────────────────────────────────────────────────────────
# MDL result
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class MDLResult:
    analyte:     str
    matrix:      str
    n:           int
    stdev:       float
    t_value:     float
    mdl_s:       float      # standard MDL (t × stdev)
    mdl_b:       Optional[float] = None   # blank-corrected
    blank_max:   Optional[float] = None
    note:        str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Summary result  (one analyte × one sample, with qualifiers and provenance)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class SummaryResult:
    analyte:          str
    sample_injection: str
    result_ppt:       Optional[float]   # None = ND or < LOD
    qualifier:        str               # "N.D.", "< LOD", "BLoQ", "N.C.", ""
    flags:            list[str]         = field(default_factory=list)
    # Provenance. When the neat injection read above the quantitation limit,
    # the reported value comes from the dilution instead — source_injection
    # names which injection it came from, and neat_result keeps the
    # over-range reading beside it so the substitution can be verified.
    # "Sample" for a field sample; "MB" / "LFSM" / "LFSMD" for QC. Reports and
    # the EDD filter on this rather than on a row happening to be empty.
    qc_type:          str               = "Sample"
    source_injection: str               = ""
    neat_result:      Optional[float]   = None
    neat_qualifier:   str               = ""
    dilution_factor:  Optional[float]   = None
    # When each injection was ANALYSED (the instrument's acquisition time).
    # A dilution is appended to the neat result with its own time
    # ("dilutions"): analysed_at is the injection the
    # reported value came from, neat_analysed_at the over-range neat one.
    analysed_at:      str               = ""
    neat_analysed_at: str               = ""
    # The method blank subtracted from result_ppt, when the method subtracts
    # it; None when nothing was subtracted.
    blank_subtracted: Optional[float]   = None
    # A reviewer finding, deliberately NOT in `flags`: flags are folded into
    # the displayed value by display() below and pushed to Analysis Remarks,
    # both of which reach the client certificate. "the method profile named a
    # different surrogate than the instrument used" is a question for the
    # reviewer, which is what the QC Review Report exists to carry.
    is_mismatch:      str               = ""

    def display(self) -> str:
        """The displayed value with its qualifiers, e.g. `8.39 (BLoQ)`.

        ONE parenthesis, semicolon-separated, which is the format
        `build_summary`'s own docstring records from real output:
        `8.39 (BLoQ)`, `0.0537 (BLoQ; N.C.)`, `10.6 (BLoQ; SUR)`.

        This produced neither of the two-code forms. It emitted a SEPARATE
        parenthesis per group -- `0.0537 (BLoQ) (N.C.)` -- and joined multiple
        flags with the empty string, so a result carrying two of them read
        `12 (N.C.HRMS)`: two qualifier codes run together into a third thing that
        is not a code at all, on a document a client reads.

        Found by printing the output rather than by any assertion about the list
        (: for any artefact a person reads, print it and read it).
        Reachable all along with N.C. + SUR; wiring the FDA §10.2(4) HRMS flag
        (§31) simply made a second code common.
        """
        if self.result_ppt is None:
            return self.qualifier
        codes = [c for c in [self.qualifier] + list(self.flags) if c]
        if not codes:
            return f"{self.result_ppt:.3g}"
        return f"{self.result_ppt:.3g} ({'; '.join(codes)})"


# ─────────────────────────────────────────────────────────────────────────────
# Batch  (the top-level container; 18 samples + QC)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Batch:
    batch_id:           str
    analyst:            str
    date:               datetime
    matrix:             str
    method_id:          str
    instrument_file:    str
    injections:         list[InstrumentRow]  = field(default_factory=list)
    qc_flags:           list[QCFlag]         = field(default_factory=list)
    is_results:         list[ISRawResult]    = field(default_factory=list)
    # : every surrogate recovery the run judged (or could not, for
    # want of a criterion): dicts injection_name, compound, value, window_min,
    # window_max, guidance, status, std_role
    surrogate_results:  list                 = field(default_factory=list)
    rt_results:         list[RTResult]       = field(default_factory=list)
    qual_quan_results:  list[QualQuanResult] = field(default_factory=list)
    cal_results:        list[CalibrationResult] = field(default_factory=list)
    # every CCV judged ({analyte, concat_id, calculated, expected, recovery,
    # passed, issue}); written to qc_results so Data Review's gate sees them
    ccv_results:        list = field(default_factory=list)
    # every sample duplicate judged ({analyte, injection_name, parent, rpd,
    # passed, issue}); written to qc_results (Dup)
    dup_results:        list = field(default_factory=list)
    # every LFB / LCS judged ({qc_type, analyte, injection_name, recovery,
    # passed, issue}); written to qc_results
    lcs_results:        list = field(default_factory=list)
    lfsm_results:       list[LFSMResult]     = field(default_factory=list)
    lfsmd_results:      list[LFSMDResult]    = field(default_factory=list)
    mdl_results:        list[MDLResult]      = field(default_factory=list)
    summary:            list[SummaryResult]  = field(default_factory=list)
    # Linked extraction log + reagents (from barcode scan)
    reagents:           list[dict]           = field(default_factory=list)
    extraction_log:     Optional[dict]       = None
    # Dilution map from FM-ENV-003: {dilution_injection: {parent, factor}}.
    # Empty for a batch that recorded none, which is every historical batch.
    dilutions:          dict                 = field(default_factory=dict)
    # Matrix-spike pedigree from the extraction log:
    # {injection: {parent, spike_ppt, level}}. Identifies an LFSM by what the
    # bench recorded rather than by a substring in its name.
    spikes:             dict                 = field(default_factory=dict)
    # Field reagent blanks among the client samples (the sample's Field QC
    # on its CoC): injection names. Still samples -- their results are
    # pushed -- but judged against the blank limit too.
    field_blanks:       list                 = field(default_factory=list)
    # field duplicates (the CoC's Field QC): client samples, left out of a
    # method's CCV interval where it counts field samples only (§10.3)
    field_duplicates:   list                 = field(default_factory=list)
    # trip blanks (the CoC's Field QC): client samples judged against the
    # method's own trip blank limit, never another blank's
    trip_blanks:        list                 = field(default_factory=list)
    # {matrix-blank injection: {"levels": {analyte: value}, "unit"}}: its
    # lot's reference values (Matrix blanks)
    mxb_references:     dict                 = field(default_factory=dict)
    # spike levels entered before the amount adjustment ("before"): each
    # spiked portion's nominal / actual amount (method_profiles.spike_scale)
    spike_basis:        str                  = ""
    spike_scales:       dict                 = field(default_factory=dict)
    # the method blank the extraction batch marks for subtraction and the
    # "< LOD" comparison; "" = none marked
    subtraction_blank:  str                  = ""
    # each blank analyte the run judged: (injection, analyte) -> {limit,
    # unit, x_rl, at_limit}; qc_store writes the verdict against it
    blank_limits:       dict                 = field(default_factory=dict)
    # FDA §10.2(4): analytes with one usable MS/MS transition (PFBA, PFPeA)
    # cannot be identified by ion ratio, so a POSITIVE has to be confirmed by an
    # orthogonal technique. Populated by build_summary, which is the only place
    # that knows whether an analyte was detected, and read by
    # RunQueue.resolve_confirmations() to settle the identity_confirmation check.
    # Each entry: {sample_injection, analyte, qc_type, prompt}.
    confirmations_required: list[dict]       = field(default_factory=list)
    # Injections a "back-calculated in the LIMS" method had to put on the
    # sample basis with the nominal matrix factor: no logged amount and final
    # volume. Flagged for review, never silent.
    correction_fallbacks:   list[str]        = field(default_factory=list)
    # SENAITE IDs once uploaded
    senaite_batch_uid:  Optional[str]        = None


# ─────────────────────────────────────────────────────────────────────────────
# Run queue entry  (what QC the analyst must look for before approving)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class QCRequirement:
    qc_type:      str    # "MB", "LFSM", "CCV", etc.
    min_count:    int    # how many required per batch
    description:  str
    required:     bool = True


BATCH_QC_REQUIREMENTS = [
    QCRequirement("MB",    1, "Method Blank — verify no contamination"),
    QCRequirement("CCV",   2, "Continuing Calibration Verification — ±20% each compound"),
    QCRequirement("LFSM",  1, "Lab Fortified Sample Matrix — 50–150% recovery"),
    QCRequirement("LFSMD", 1, "LFSM Duplicate — RPD ≤ 30%"),
    QCRequirement("CAL",   1, "Calibration curve — R² ≥ 0.995, ±20% each point"),
]
