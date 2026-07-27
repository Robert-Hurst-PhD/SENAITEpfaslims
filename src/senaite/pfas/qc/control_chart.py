# -*- coding: utf-8 -*-
"""
Levey-Jennings Control Charting with Westgard Multi-Rules.

Python 3.  Used by the pipeline layer to:
  - Compute control statistics from historical data in QCResultStore
  - Detect Westgard rule violations
  - Render matplotlib figures (PNG/PDF) for reports
  - Produce JSON-serialisable dicts for Chart.js browser rendering

Westgard rules implemented:
  1-2S  Warning   — one value exceeds mean ± 2SD
  1-3S  Reject    — one value exceeds mean ± 3SD
  2-2S  Reject    — two consecutive values > +2SD or both < -2SD
  R-4S  Reject    — one value > +2SD and previous/next < -2SD (range ≥ 4SD)
  4-1S  Reject    — four consecutive values all > +1SD or all < -1SD
  10X   Reject    — ten consecutive values all on the same side of the mean
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# ── Data structures ───────────────────────────────────────────────────────────


@dataclass
class ControlPoint:
    date: str
    value: float
    batch_id: str
    flag: str = ""
    violations: List[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return math.isfinite(self.value)


@dataclass
class ControlLimits:
    mean: float
    sd: float
    n_baseline: int
    ucl_1: float = 0.0
    lcl_1: float = 0.0
    ucl_2: float = 0.0
    lcl_2: float = 0.0
    ucl_3: float = 0.0
    lcl_3: float = 0.0

    def __post_init__(self):
        self.ucl_1 = self.mean + self.sd
        self.lcl_1 = self.mean - self.sd
        self.ucl_2 = self.mean + 2 * self.sd
        self.lcl_2 = self.mean - 2 * self.sd
        self.ucl_3 = self.mean + 3 * self.sd
        self.lcl_3 = self.mean - 3 * self.sd

    def sigma(self, value: float) -> float:
        """Return how many SDs value is from mean (signed)."""
        return (value - self.mean) / self.sd if self.sd else 0.0


@dataclass
class WestgardViolation:
    rule: str
    description: str
    point_indices: List[int]
    severity: str  # "warning" or "reject"


@dataclass
class ControlChartData:
    analyte: str
    qc_type: str
    qc_level: str
    units: str
    points: List[ControlPoint]
    limits: Optional[ControlLimits]
    violations: List[WestgardViolation] = field(default_factory=list)
    target_value: Optional[float] = None


# ── Statistics ────────────────────────────────────────────────────────────────

MIN_BASELINE = 5
DEFAULT_BASELINE_N = 20


def compute_control_limits(
    points: List[ControlPoint],
    n_baseline: int = DEFAULT_BASELINE_N,
) -> Optional[ControlLimits]:
    """
    Compute Levey-Jennings control limits from the first n_baseline valid points.
    Returns None if fewer than MIN_BASELINE valid values are available.
    """
    valid = [p.value for p in points if p.valid]
    if len(valid) < MIN_BASELINE:
        return None
    baseline = valid[:n_baseline]
    mean = statistics.mean(baseline)
    if len(baseline) < 2:
        return None
    sd = statistics.stdev(baseline)
    if sd == 0.0:
        sd = max(abs(mean) * 0.01, 0.01)
    return ControlLimits(mean=mean, sd=sd, n_baseline=len(baseline))


# ── Westgard rules ────────────────────────────────────────────────────────────


def apply_westgard_rules(
    points: List[ControlPoint],
    limits: ControlLimits,
) -> List[WestgardViolation]:
    """
    Apply Westgard multi-rules to a sequence of control points.
    Rules are evaluated after the baseline period (first n_baseline points).
    Returns list of WestgardViolation objects (may be empty).
    """
    violations: List[WestgardViolation] = []
    n = len(points)
    if n < 2 or limits is None:
        return violations

    sigmas = [
        limits.sigma(p.value) if p.valid else None
        for p in points
    ]

    def _valid(idx: int) -> Optional[float]:
        return sigmas[idx] if 0 <= idx < n else None

    # Evaluate starting from the second point (after at least one baseline value)
    for i in range(1, n):
        s = _valid(i)
        if s is None:
            continue

        # 1-3S: reject — single value beyond ±3SD
        if abs(s) > 3.0:
            violations.append(WestgardViolation(
                rule="1-3S",
                description="Single value beyond ±3SD (reject)",
                point_indices=[i],
                severity="reject",
            ))

        # 1-2S: warning — single value beyond ±2SD (not already 1-3S)
        elif abs(s) > 2.0:
            violations.append(WestgardViolation(
                rule="1-2S",
                description="Single value beyond ±2SD (warning)",
                point_indices=[i],
                severity="warning",
            ))

        # 2-2S: reject — two consecutive values both > +2SD or both < -2SD
        if i >= 1:
            s_prev = _valid(i - 1)
            if s_prev is not None:
                if s > 2.0 and s_prev > 2.0:
                    violations.append(WestgardViolation(
                        rule="2-2S",
                        description="Two consecutive values above +2SD (reject)",
                        point_indices=[i - 1, i],
                        severity="reject",
                    ))
                elif s < -2.0 and s_prev < -2.0:
                    violations.append(WestgardViolation(
                        rule="2-2S",
                        description="Two consecutive values below -2SD (reject)",
                        point_indices=[i - 1, i],
                        severity="reject",
                    ))

        # R-4S: reject — range between adjacent points spans ≥ 4SD
        if i >= 1:
            s_prev = _valid(i - 1)
            if s_prev is not None and abs(s - s_prev) >= 4.0:
                violations.append(WestgardViolation(
                    rule="R-4S",
                    description="Range between adjacent values ≥ 4SD (reject)",
                    point_indices=[i - 1, i],
                    severity="reject",
                ))

        # 4-1S: reject — four consecutive values all > +1SD or all < -1SD
        if i >= 3:
            run_4 = [_valid(j) for j in range(i - 3, i + 1)]
            if all(v is not None for v in run_4):
                if all(v > 1.0 for v in run_4):
                    violations.append(WestgardViolation(
                        rule="4-1S",
                        description="Four consecutive values above +1SD (reject)",
                        point_indices=list(range(i - 3, i + 1)),
                        severity="reject",
                    ))
                elif all(v < -1.0 for v in run_4):
                    violations.append(WestgardViolation(
                        rule="4-1S",
                        description="Four consecutive values below -1SD (reject)",
                        point_indices=list(range(i - 3, i + 1)),
                        severity="reject",
                    ))

        # 10X: reject — ten consecutive values all on same side of mean
        if i >= 9:
            run_10 = [_valid(j) for j in range(i - 9, i + 1)]
            if all(v is not None for v in run_10):
                if all(v > 0 for v in run_10):
                    violations.append(WestgardViolation(
                        rule="10X",
                        description="Ten consecutive values above mean (reject)",
                        point_indices=list(range(i - 9, i + 1)),
                        severity="reject",
                    ))
                elif all(v < 0 for v in run_10):
                    violations.append(WestgardViolation(
                        rule="10X",
                        description="Ten consecutive values below mean (reject)",
                        point_indices=list(range(i - 9, i + 1)),
                        severity="reject",
                    ))

    # De-duplicate: keep only unique (rule, point_indices[-1]) pairs
    seen: set = set()
    deduped = []
    for v in violations:
        key = (v.rule, v.point_indices[-1])
        if key not in seen:
            seen.add(key)
            deduped.append(v)
    return deduped


# ── Build ControlChartData from store rows ────────────────────────────────────


def build_chart_data(
    rows: List[dict],
    analyte: str,
    qc_type: str,
    qc_level: str,
    units: str = "",
    n_baseline: int = DEFAULT_BASELINE_N,
    target_value: Optional[float] = None,
) -> ControlChartData:
    """
    Build ControlChartData from QCResultStore.get_chart_data() rows.
    Computes limits and applies Westgard rules.
    """
    points = []
    for r in rows:
        v = r.get("value")
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        points.append(ControlPoint(
            date=str(r.get("run_date", "")),
            value=fv,
            batch_id=str(r.get("batch_id", "")),
            flag=str(r.get("flag", "")),
        ))

    limits = compute_control_limits(points, n_baseline=n_baseline)
    violations: List[WestgardViolation] = []
    if limits is not None:
        violations = apply_westgard_rules(points, limits)
        # Annotate points with their violations
        violated_indices: dict = {}
        for viol in violations:
            for idx in viol.point_indices:
                violated_indices.setdefault(idx, []).append(viol.rule)
        for idx, rules in violated_indices.items():
            points[idx].violations = rules

    return ControlChartData(
        analyte=analyte,
        qc_type=qc_type,
        qc_level=qc_level,
        units=units,
        points=points,
        limits=limits,
        violations=violations,
        target_value=target_value,
    )


# ── JSON serialisation for Chart.js ──────────────────────────────────────────


def to_chart_js_dict(chart: ControlChartData) -> dict:
    """
    Serialise ControlChartData to a JSON-safe dict for Chart.js rendering.

    The returned dict has the shape expected by the controlchart.pt template:
      {
        "analyte":     str,
        "qc_type":     str,
        "qc_level":    str,
        "units":       str,
        "labels":      [date_str, ...],
        "values":      [float, ...],
        "batch_ids":   [str, ...],
        "flags":       [str, ...],
        "violations":  [str, ...],   # comma-joined rule names per point
        "limits":      {mean, sd, ucl_1..lcl_3} | null,
        "target":      float | null,
        "westgard":    [{rule, description, severity, indices}, ...],
        "has_rejects": bool,
        "has_warnings": bool,
      }
    """
    lim = chart.limits
    limits_dict = None
    if lim is not None:
        limits_dict = {
            "mean":      _r(lim.mean),
            "sd":        _r(lim.sd),
            "n_baseline": lim.n_baseline,
            "ucl_1":     _r(lim.ucl_1),
            "lcl_1":     _r(lim.lcl_1),
            "ucl_2":     _r(lim.ucl_2),
            "lcl_2":     _r(lim.lcl_2),
            "ucl_3":     _r(lim.ucl_3),
            "lcl_3":     _r(lim.lcl_3),
        }

    # Per-point violation annotation
    violated: dict = {}
    for v in chart.violations:
        for idx in v.point_indices:
            violated.setdefault(idx, []).append(v.rule)

    labels, values, batch_ids, flags, point_violations = [], [], [], [], []
    for i, p in enumerate(chart.points):
        labels.append(p.date[:10] if len(p.date) >= 10 else p.date)
        values.append(_r(p.value))
        batch_ids.append(p.batch_id)
        flags.append(p.flag)
        point_violations.append(",".join(violated.get(i, [])))

    westgard_list = [
        {
            "rule":         v.rule,
            "description":  v.description,
            "severity":     v.severity,
            "indices":      v.point_indices,
        }
        for v in chart.violations
    ]

    has_rejects = any(v.severity == "reject" for v in chart.violations)
    has_warnings = any(v.severity == "warning" for v in chart.violations)

    return {
        "analyte":     chart.analyte,
        "qc_type":     chart.qc_type,
        "qc_level":    chart.qc_level,
        "units":       chart.units,
        "labels":      labels,
        "values":      values,
        "batch_ids":   batch_ids,
        "flags":       flags,
        "violations":  point_violations,
        "limits":      limits_dict,
        "target":      (_r(chart.target_value)
                        if chart.target_value is not None else None),
        "westgard":    westgard_list,
        "has_rejects": has_rejects,
        "has_warnings": has_warnings,
        "n_points":    len(chart.points),
    }


def _r(v: float, digits: int = 4) -> float:
    """Round to digits significant figures for JSON output."""
    if v is None or not math.isfinite(v):
        return v
    return round(v, digits)


# ── Matplotlib rendering ──────────────────────────────────────────────────────


def render_to_png_bytes(chart: ControlChartData, title: str = "") -> bytes:
    """
    Render a Levey-Jennings chart to PNG bytes using matplotlib.
    Used by the report pipeline (not the browser view).
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
    except ImportError:
        raise ImportError("matplotlib is required for PNG rendering. "
                          "pip install matplotlib")

    lim = chart.limits
    xs = list(range(len(chart.points)))
    ys = [p.value for p in chart.points]
    dates = [p.date[:10] for p in chart.points]

    # Colour points by violation severity
    violated: dict = {}
    for v in chart.violations:
        for idx in v.point_indices:
            worst = violated.get(idx, "ok")
            if v.severity == "reject":
                violated[idx] = "reject"
            elif worst != "reject" and v.severity == "warning":
                violated[idx] = "warning"

    colours = []
    for i in range(len(chart.points)):
        status = violated.get(i, "ok")
        if status == "reject":
            colours.append("#d32f2f")
        elif status == "warning":
            colours.append("#f57c00")
        else:
            colours.append("#1976d2")

    fig, ax = plt.subplots(figsize=(14, 5))
    ax.plot(xs, ys, color="#90a4ae", linewidth=0.8, zorder=1)
    ax.scatter(xs, ys, c=colours, s=40, zorder=2)

    if lim:
        kw = dict(linewidth=1, alpha=0.85)
        ax.axhline(lim.mean,  color="#212121", linewidth=1.2, linestyle="-",  label="Mean")
        ax.axhline(lim.ucl_1, color="#4caf50", **kw, linestyle="--", label="+1SD")
        ax.axhline(lim.lcl_1, color="#4caf50", **kw, linestyle="--")
        ax.axhline(lim.ucl_2, color="#ff9800", **kw, linestyle="-.", label="+2SD (warn)")
        ax.axhline(lim.lcl_2, color="#ff9800", **kw, linestyle="-.")
        ax.axhline(lim.ucl_3, color="#f44336", **kw, linestyle=":", label="+3SD (reject)")
        ax.axhline(lim.lcl_3, color="#f44336", **kw, linestyle=":")

    if chart.target_value is not None:
        ax.axhline(chart.target_value, color="#9c27b0", linewidth=1.0,
                   linestyle=(0, (5, 10)), label="Target")

    # X-axis labels (show every N-th date)
    step = max(1, len(xs) // 20)
    ax.set_xticks(xs[::step])
    ax.set_xticklabels(dates[::step], rotation=45, ha="right", fontsize=8)

    label = "{} — {} {}".format(
        chart.analyte, chart.qc_type,
        "({})".format(chart.qc_level) if chart.qc_level else ""
    ).strip()
    ax.set_title(title or label, fontsize=11)
    ax.set_xlabel("Run Date")
    ax.set_ylabel(chart.units or "Value")
    ax.legend(fontsize=8, loc="upper left")
    ax.grid(axis="y", alpha=0.3)

    patches = [
        mpatches.Patch(color="#d32f2f", label="Reject violation"),
        mpatches.Patch(color="#f57c00", label="Warning violation"),
        mpatches.Patch(color="#1976d2", label="In-control"),
    ]
    ax.legend(handles=patches, fontsize=8, loc="upper right")

    from io import BytesIO
    buf = BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    return buf.getvalue()


# ── Extraction from BatchQCResult ─────────────────────────────────────────────


def extract_qc_points_from_batch(
    batch_result,  # qc.engine.BatchQCResult
    run_date: str,
    method: str = "",
) -> List[dict]:
    """
    Extract QC data points from a completed BatchQCResult for storage.

    Returns list of dicts suitable for QCResultStore.add_results_bulk().

    QC types extracted:
      CCV   — % deviation from calibration_table (CCV injections)
      LCS   — % deviation from calibration_table (LCS injections)
      MB    — blank concentration from method_blank_table
      LFSM  — % recovery from lfsm_table
      LFSMD — % recovery from lfsm_table (duplicates)
      IS    — % vs batch avg from is_table
    """
    try:
        import pandas as pd
    except ImportError:
        return []

    rows = []
    batch_id = batch_result.batch_id

    def _add(analyte, qc_type, qc_level, value, units, flag, passed):
        if value is None or (hasattr(value, "__float__") and
                             not math.isfinite(float(value))):
            return
        rows.append(dict(
            batch_id=batch_id,
            run_date=run_date,
            analyte=analyte,
            qc_type=qc_type,
            qc_level=str(qc_level),
            method=method,
            value=float(value),
            units=units,
            flag=str(flag) if flag else "",
            passed=int(bool(passed)),
        ))

    # ── CCV / LCS from calibration table ─────────────────────────────────
    cal = batch_result.calibration_table
    if not cal.empty and "Injection Name" in cal.columns:
        for _, row in cal.iterrows():
            inj = str(row.get("Injection Name", "")).upper()
            dev = row.get("% Deviation")
            if pd.isna(dev):
                continue
            analyte = str(row.get("Analyte", ""))
            level = str(row.get("Level", ""))
            flag = str(row.get("Flag", ""))
            passed = row.get("Pass", True)
            if "CCV" in inj or "ICV" in inj:
                _add(analyte, "CCV", level, dev, "pct_deviation", flag, passed)
            elif "LCS" in inj:
                # LCS folds into the canonical LFB code (see qc/qc_types.py).
                _add(analyte, "LFB", level, dev, "pct_deviation", flag, passed)

    # ── Method Blank from method_blank_table ──────────────────────────────
    mb = batch_result.method_blank_table
    if not mb.empty:
        for _, row in mb.iterrows():
            analyte = str(row.get("Analyte", ""))
            conc = row.get("Max Blank (ppt)")
            if pd.isna(conc):
                continue
            flag = str(row.get("Flag", ""))
            contamination = bool(row.get("Contamination Flag", False))
            _add(analyte, "MB", "", conc, "ppt", flag, not contamination)

    # ── LFSM / LFSMD recoveries ───────────────────────────────────────────
    lfsm = batch_result.lfsm_table
    if not lfsm.empty:
        for _, row in lfsm.iterrows():
            analyte = str(row.get("Analyte", ""))
            rec = row.get("Recovery (%)")
            if pd.isna(rec):
                continue
            qc_type = str(row.get("Type", "LFSM"))
            spike = str(row.get("Spike (ppt)", ""))
            flag = str(row.get("Flag", ""))
            passed = row.get("Pass", True)
            _add(analyte, qc_type, spike, rec, "pct_recovery", flag, passed)

    # ── Internal standard responses ───────────────────────────────────────
    is_tbl = batch_result.is_table
    if not is_tbl.empty:
        for _, row in is_tbl.iterrows():
            analyte = str(row.get("Analyte (IS)", ""))
            pct = row.get("% vs Average")
            if pd.isna(pct):
                continue
            flag = str(row.get("Flag", ""))
            passed = row.get("Pass", True)
            _add(analyte, "IS", "", pct, "pct_vs_avg", flag, passed)

    return rows
