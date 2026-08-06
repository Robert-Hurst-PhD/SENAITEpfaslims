#!/usr/bin/env python3
"""
Generate synthetic instrument runs across every method × matrix, with
deviations deliberately injected and their expected outcomes declared.

WHY THIS EXISTS
---------------
The system has only ever processed one configuration: FDA_32PFAS × Animal Feed.
There are 18 method × matrix combinations configured. EPA 537.1 and EPA 1633A
have never run at all. Every QC mechanism has been verified against a single
real export whose failures happen to be the ones it contains.

A generator that only produces clean data proves nothing about detection. Each
run therefore ships a MANIFEST naming the deviations injected into it and what
the system is expected to do about each. The harness
(`tests/test_fault_injection.py`) asserts the flags raised equal that set —
catching misses AND false positives, which a pass/fail check cannot.

WHAT IT READS (never duplicates)
--------------------------------
  matrices, units, methods   src/senaite/pfas/setupdata/sample_types.csv
  calibration ladders        src/senaite/pfas/setupdata/methods.csv  (CalLadder)
  reportable panel           method_profiles.json analyte_matrix_inclusion
                             — the Method × Matrix intersection, never a flat
                             list (CLAUDE.md §3 rule 2; PFODA ∉ FDA × Eggs)
  surrogate map              method_profiles.json surrogate_map
  acceptance limits          method_profiles.json qc_acceptance / instrument_verification
  column vocabulary          senaite.pfas.instrument_columns (via canonical_columns)

Usage
-----
  generate_synthetic_runs.py --out DIR                    # all 18 combinations
  generate_synthetic_runs.py --out DIR --method FDA_32PFAS
  generate_synthetic_runs.py --out DIR --deviations clean
  generate_synthetic_runs.py --out DIR --list             # show the plan only

Each run writes three files:
  <run>.csv                    native-header instrument export
  <run>_extraction.json        sidecar: batch_id, method, matrix, spikes…
  <run>_manifest.json          injected deviations + expected outcomes
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SETUPDATA = os.path.join(ROOT, "src", "senaite", "pfas", "setupdata")
DEFAULT_PROFILES = os.path.join(ROOT, "data", "qc", "method_profiles.json")

# Everything is tagged so `migrations/purge_seed_qc_data.py` — which ARCHIVES
# rather than deletes — can reverse it. Do NOT use cleanup_test_data.py; it
# deletes every worksheet unconditionally.
TAG = "SYNTH"


# ── deviations ───────────────────────────────────────────────────────────────
#
# key -> (where it is injected, what the system must do)
#
# "blocks" means laboratory control material: the qualifier library refuses to
# excuse it whatever it says, because there is no client matrix in a blank.
DEVIATIONS = {
    "clean":              ("nothing", None),
    "ccv_recovery_high":  ("CCV",     "block"),
    "blank_contaminated": ("MB",      "block"),
    "calibration_r2_low": ("CAL",     "block"),
    "surrogate_low":      ("sample",  "qualify"),
    "lfsm_low":           ("LFSM",    "qualify"),
    "lfsmd_rpd_high":     ("LFSMD",   "qualify"),
    "ion_ratio_out":      ("sample",  "qualify"),
    "sn_low":             ("sample",  "qualify"),
}


def _read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def load_matrices():
    """(method_id, matrix_title, unit) for every configured combination."""
    out = []
    for row in _read_csv(os.path.join(SETUPDATA, "sample_types.csv")):
        for method in (row.get("Methods") or "").split(";"):
            method = method.strip()
            if method:
                out.append((method, row["Title"].strip(),
                            (row.get("DefaultUnit") or "").strip()))
    return sorted(out)


def load_ladders():
    out = {}
    for row in _read_csv(os.path.join(SETUPDATA, "methods.csv")):
        levels = [float(x) for x in (row.get("CalLadder") or "").split(";") if x]
        if levels:
            out[row["MethodID"].strip()] = sorted(levels, reverse=True)
    return out


def load_profiles(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def panel_for(profile, matrix):
    """The REPORTABLE analytes for this method × matrix.

    Read from analyte_matrix_inclusion, not from master_analyte_set: an analyte
    in the method is not automatically reportable in every matrix, and taking
    the flat list would silently report analytes the lab excluded.
    """
    inclusion = profile.get("analyte_matrix_inclusion") or {}
    master = profile.get("master_analyte_set") or []
    if not inclusion:
        return list(master)
    out = []
    for keyword in master:
        per_matrix = inclusion.get(keyword) or {}
        if per_matrix.get(matrix, True):
            out.append(keyword)
    return out


def display_names():
    """keyword -> the name an INSTRUMENT exports.

    Profiles store SENAITE keywords ("M2-4:2FTS", "4:2FTS"); an instrument
    exports display names ("13C2,D4-4:2FTS", "4:2 FTS"). Emitting keywords made
    the generator's surrogates invisible to the IS check — zero overlap with
    `run_queue._get_is_list` — so an injected surrogate failure raised nothing
    and looked like a detection gap in the system rather than a fixture bug.
    This is the same keyword/display duality that has bitten this codebase
    repeatedly; resolve it once, here, from the master table.
    """
    import importlib.util
    path = os.path.join(ROOT, "src", "senaite", "pfas", "analyte_reference.py")
    spec = importlib.util.spec_from_file_location("_ar", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = {}
    for row in list(mod.NATIVE_ANALYTES) + list(mod.INTERNAL_STANDARDS):
        out[row[0]] = row[1]
    return out


def surrogate_map_for(profile):
    out = {}
    for row in (profile.get("surrogate_map") or []):
        analyte = (row.get("analyte") or "").strip()
        surrogate = (row.get("surrogate_is") or "").strip()
        if analyte and surrogate:
            out[analyte] = surrogate
    return out


def matrix_factor_for(profile, matrix):
    for entry in (profile.get("matrix_factors") or []):
        if (entry.get("matrix") or "").strip().lower() == matrix.strip().lower():
            try:
                return float(entry.get("factor"))
            except (TypeError, ValueError):
                pass
    return 1.0


def _r2_min(profile):
    cal = (profile.get("instrument_verification") or {}).get("calibration") or {}
    try:
        return float(cal.get("r2_min"))
    except (TypeError, ValueError):
        return 0.99


def _ccv_window(profile):
    ccv = (profile.get("instrument_verification") or {}).get("ccv") or {}
    try:
        return float(ccv.get("recovery_min")), float(ccv.get("recovery_max"))
    except (TypeError, ValueError):
        return 70.0, 130.0


class RunBuilder:
    """One synthetic run: injections × compounds, with deviations applied."""

    def __init__(self, method_id, matrix, unit, profile, ladder, rng,
                 run_date, deviations):
        self.method_id = method_id
        self.matrix = matrix
        self.unit = unit
        self.profile = profile
        self.ladder = ladder
        self.rng = rng
        self.run_date = run_date
        self.deviations = set(deviations or [])
        self._display = display_names()
        # Panel and surrogates in the INSTRUMENT's vocabulary.
        self.panel = [self._display.get(k, k)
                      for k in panel_for(profile, matrix)]
        self.surrogates = {
            self._display.get(a, a): self._display.get(s, s)
            for a, s in surrogate_map_for(profile).items()}
        self.matrix_factor = matrix_factor_for(profile, matrix)
        self.slug = "{0}-{1}".format(
            method_id, matrix.replace(" / ", "-").replace(" ", "-"))
        self.batch_id = "{0}-{1}".format(TAG, self.slug.upper())
        self.rows = []
        self.expected = []
        # A compound elutes at the SAME time in every injection of a run. The
        # first version drew a fresh random RT per row, which made every
        # injection disagree with itself and manufactured ~475 retention-time
        # flags per run. A fault-injection fixture that produces its own false
        # positives cannot be used to prove the absence of false positives.
        self._base_rt = {}
        self._clock = datetime.combine(run_date, datetime.min.time()) \
            .replace(hour=8)

    # ── helpers ─────────────────────────────────────────────────────────────
    def _next_time(self):
        """Each injection gets its own timestamp: concat_id is
        injection_name|yyyymmddHHMMSS, so two injections sharing a name AND a
        timestamp would collapse into one."""
        self._clock += timedelta(minutes=7)
        return self._clock

    def _rt_for(self, compound):
        """Stable per-compound retention time with realistic run-to-run jitter."""
        if compound not in self._base_rt:
            self._base_rt[compound] = 4.0 + self.rng.uniform(0, 6)
        return self._base_rt[compound] + self.rng.gauss(0, 0.004)

    def _response(self, conc):
        return max(0.0, conc * 41000.0 + 250.0 + self.rng.gauss(0, 120))

    def _emit(self, injection, sample_type, compound, compound_type,
              expected=None, calculated=None, response=None, level="",
              ion_ratio=None, expected_ratio=None, sn=None, r2=None,
              linked_is="", reporting_limit=0.05, sample_factor=1.0,
              acquired=None):
        acquired = acquired or self._next_time()
        self.rows.append({
            "Compound Name": compound,
            "Compound Type": compound_type,
            "Sample Description": "{0} {1}".format(self.slug, injection),
            "Injection Name": injection,
            "Sample Type": sample_type,
            "Level": level,
            "Linked Internal Standard": linked_is,
            "Observed RT (min)": round(self._rt_for(compound), 3),
            "Response": "" if response is None else round(response, 2),
            "IS Response": round(52000 + self.rng.gauss(0, 900), 2),
            "Response Ratio": "" if response is None else round(response / 52000.0, 6),
            "Expected Concentration": "" if expected is None else expected,
            "Calculated Concentration": "" if calculated is None else round(calculated, 6),
            "Measured Concentration": "" if calculated is None else round(calculated, 6),
            "Reporting Limit": reporting_limit,
            "Concentration Units": self.unit,
            "% Deviation": "",
            "Ion Ratios": "" if ion_ratio is None else round(ion_ratio, 3),
            "Expected Ion Ratios": "" if expected_ratio is None else round(expected_ratio, 3),
            "R2": "" if r2 is None else r2,
            "Signal to Noise": "" if sn is None else round(sn, 1),
            "Quantitation Status": "Successful",
            "Sample Factor": sample_factor,
            "Acquisition Date": acquired.strftime("%Y-%m-%d"),
            "Acquisition Time": acquired.strftime("%H:%M:%S"),
            "Concat ID": "{0}|{1}".format(injection, acquired.strftime("%Y%m%d%H%M%S")),
        })

    def _expect(self, deviation, check, disposition, injection, analytes):
        self.expected.append({
            "deviation": deviation,
            "check": check,
            "disposition": disposition,
            "injection": injection,
            "analytes": sorted(analytes),
        })

    def _compounds_for(self, injection, sample_type, conc_fn, **kw):
        """One row per reportable analyte plus its surrogate."""
        for analyte in self.panel:
            conc = conc_fn(analyte)
            surrogate = self.surrogates.get(analyte, "")
            self._emit(injection, sample_type, analyte, "Analyte",
                       calculated=conc, response=self._response(conc or 0),
                       linked_is=surrogate,
                       ion_ratio=kw.get("ion_ratio_for", lambda a: 0.45)(analyte),
                       expected_ratio=0.45,
                       sn=kw.get("sn_for", lambda a: 40.0)(analyte),
                       level=kw.get("level", ""),
                       sample_factor=kw.get("sample_factor", 1.0))
        for surrogate in sorted(set(self.surrogates.values())):
            scale = kw.get("surrogate_scale", 1.0)
            self._emit(injection, sample_type, surrogate, "Internal Standard",
                       response=self._response(1.0) * scale,
                       sn=45.0, level=kw.get("level", ""))

    # ── the run ─────────────────────────────────────────────────────────────
    def build(self):
        self._calibration()
        self._ccv()
        self._blank()
        parents = self._samples()
        self._spikes(parents)
        return self.rows

    def _calibration(self):
        r2_min = _r2_min(self.profile)
        bad_r2 = "calibration_r2_low" in self.deviations
        r2 = round(r2_min - 0.02, 4) if bad_r2 else round(r2_min + 0.005, 4)
        for i, level_conc in enumerate(self.ladder, start=1):
            name = "{0}-CAL-{1}-{2}".format(
                self.method_id, i, self.run_date.strftime("%y%m%d"))
            self._compounds_for(
                name, "Standard",
                lambda a, c=level_conc: c,
                level=str(i))
            for row in self.rows[-len(self.panel):]:
                row["R2"] = r2
                row["Expected Concentration"] = level_conc
        if bad_r2:
            self._expect("calibration_r2_low", "calibration", "block",
                         "calibration curve", self.panel)

    def _ccv(self):
        lo, hi = _ccv_window(self.profile)
        target = self.ladder[len(self.ladder) // 2]
        bad = "ccv_recovery_high" in self.deviations
        recovery = (hi + 25.0) if bad else 100.0
        name = "{0}-CCV-{1}".format(self.method_id,
                                    self.run_date.strftime("%y%m%d"))
        self._compounds_for(name, "Quality Control",
                            lambda a, t=target, r=recovery: t * r / 100.0)
        for row in self.rows[-len(self.panel) - len(set(self.surrogates.values())):]:
            if row["Compound Type"] == "Analyte":
                row["Expected Concentration"] = target
        if bad:
            self._expect("ccv_recovery_high", "ccv", "block", name, self.panel)

    def _blank(self):
        name = "{0} MB {1}".format(TAG, self.run_date.strftime("%Y-%m-%d-1"))
        dirty = "blank_contaminated" in self.deviations
        hit = self.panel[:2] if dirty else []
        self._compounds_for(
            name, "Blank",
            lambda a: (0.25 if a in hit else 0.0))
        if dirty:
            self._expect("blank_contaminated", "blank", "block", name, hit)

    def _samples(self, count=3):
        parents = []
        low_sur = "surrogate_low" in self.deviations
        ratio_out = "ion_ratio_out" in self.deviations
        low_sn = "sn_low" in self.deviations
        hit = self.panel[:1]
        for n in range(1, count + 1):
            name = "{0}-{1}-{2:04d}".format(TAG, self.slug.upper(), n)
            parents.append(name)
            first = (n == 1)
            self._compounds_for(
                name, "Unknown",
                lambda a: round(self.rng.uniform(0.4, 4.0), 4),
                surrogate_scale=(0.25 if (low_sur and first) else 1.0),
                ion_ratio_for=(lambda a: 0.90 if (ratio_out and first and a in hit)
                               else 0.45),
                sn_for=(lambda a: 1.5 if (low_sn and first and a in hit) else 40.0))
        first_sample = parents[0]
        if low_sur:
            affected = sorted(a for a in self.panel if a in self.surrogates)
            self._expect("surrogate_low", "surrogate", "qualify",
                         first_sample, affected)
        if ratio_out:
            self._expect("ion_ratio_out", "ion_ratio", "qualify",
                         first_sample, hit)
        if low_sn:
            self._expect("sn_low", "sn", "qualify", first_sample, hit)
        return parents

    def _spikes(self, parents):
        parent = parents[0]
        spike = 100.0 / (self.matrix_factor or 1.0)
        base = {}
        for row in self.rows:
            if row["Injection Name"] == parent and row["Compound Type"] == "Analyte":
                base[row["Compound Name"]] = float(row["Calculated Concentration"])
        low = "lfsm_low" in self.deviations
        rpd = "lfsmd_rpd_high" in self.deviations
        lfsm = "{0} LFSM Mid".format(parent)
        self._compounds_for(lfsm, "Unknown",
                            lambda a: (base.get(a, 0.0)
                                       + spike * (0.35 if low else 1.0)))
        lfsmd = "{0} LFSM Mid Duplicate".format(parent)
        self._compounds_for(lfsmd, "Unknown",
                            lambda a: (base.get(a, 0.0)
                                       + spike * (1.0 * (1.45 if rpd else 1.03))))
        if low:
            self._expect("lfsm_low", "lfsm", "qualify", lfsm, self.panel)
        if rpd:
            self._expect("lfsmd_rpd_high", "lfsmd", "qualify", lfsmd, self.panel)
        return lfsm, lfsmd

    # ── output ──────────────────────────────────────────────────────────────
    def sidecar(self):
        parent = "{0}-{1}-0001".format(TAG, self.slug.upper())
        return {
            "batch_id": self.batch_id,
            "analyst": "SYNTH",
            "matrix": self.matrix,
            "method_id": self.method_id,
            "steps": [], "reagent_scans": [], "signoffs": [],
            "_spikes": {
                "{0} LFSM Mid".format(parent): {
                    "parent": parent, "spike_ppt": 100.0, "level": "Mid"},
                "{0} LFSM Mid Duplicate".format(parent): {
                    "parent": parent, "spike_ppt": 100.0, "level": "Mid"},
            },
        }

    def manifest(self):
        return {
            "batch_id": self.batch_id,
            "method_id": self.method_id,
            "matrix": self.matrix,
            "unit": self.unit,
            "matrix_factor": self.matrix_factor,
            "panel_size": len(self.panel),
            "injected": sorted(self.deviations),
            "expected": self.expected,
        }


def write_run(builder, out_dir):
    rows = builder.build()
    fieldnames = list(rows[0].keys())
    stem = os.path.join(out_dir, builder.batch_id)
    with open(stem + ".csv", "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    with open(stem + "_extraction.json", "w", encoding="utf-8") as fh:
        json.dump(builder.sidecar(), fh, indent=2)
    with open(stem + "_manifest.json", "w", encoding="utf-8") as fh:
        json.dump(builder.manifest(), fh, indent=2)
    return stem + ".csv", len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "synthetic"))
    ap.add_argument("--profiles", default=DEFAULT_PROFILES)
    ap.add_argument("--method", action="append",
                    help="restrict to these method ids")
    ap.add_argument("--matrix", action="append", help="restrict to these matrices")
    ap.add_argument("--deviations", default="all",
                    help="'all', 'clean', or a comma-separated subset")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--list", action="store_true",
                    help="print the plan without writing anything")
    args = ap.parse_args()

    profiles = load_profiles(args.profiles)
    ladders = load_ladders()
    combos = load_matrices()
    if args.method:
        combos = [c for c in combos if c[0] in args.method]
    if args.matrix:
        combos = [c for c in combos if c[1] in args.matrix]

    if args.deviations == "all":
        chosen = [k for k in DEVIATIONS if k != "clean"]
    elif args.deviations == "clean":
        chosen = []
    else:
        chosen = [d.strip() for d in args.deviations.split(",") if d.strip()]
        unknown = [d for d in chosen if d not in DEVIATIONS]
        if unknown:
            ap.error("unknown deviation(s): {0}. Known: {1}".format(
                ", ".join(unknown), ", ".join(sorted(DEVIATIONS))))

    if not args.list:
        os.makedirs(args.out, exist_ok=True)

    rng = random.Random(args.seed)
    written = skipped = 0
    for method_id, matrix, unit in combos:
        profile = profiles.get(method_id)
        if not profile:
            print("  skip {0} × {1}: no method profile".format(method_id, matrix))
            skipped += 1
            continue
        if matrix not in (profile.get("supported_matrices") or []):
            # sample_types.csv and the profile disagree — report it rather than
            # inventing a combination the method does not claim to support.
            print("  skip {0} × {1}: not in the profile's supported_matrices"
                  .format(method_id, matrix))
            skipped += 1
            continue
        ladder = ladders.get(method_id)
        if not ladder:
            print("  skip {0}: no CalLadder in methods.csv".format(method_id))
            skipped += 1
            continue
        builder = RunBuilder(method_id, matrix, unit, profile, ladder, rng,
                             datetime.now().date(), chosen)
        if args.list:
            print("  {0:<12} × {1:<18} panel={2:<3} factor={3:<5} unit={4}".format(
                method_id, matrix, len(builder.panel), builder.matrix_factor, unit))
            written += 1
            continue
        path, n = write_run(builder, args.out)
        print("  {0:<40} {1:>5} rows  deviations={2}".format(
            os.path.basename(path), n, len(builder.expected)))
        written += 1

    print("\n{0} run(s) {1}, {2} skipped".format(
        written, "planned" if args.list else "written", skipped))
    if not args.list and written:
        print("Output: {0}".format(args.out))


if __name__ == "__main__":
    main()
