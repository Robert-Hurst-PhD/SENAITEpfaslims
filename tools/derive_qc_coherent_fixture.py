#!/usr/bin/env python3
"""
Derive a QC-coherent companion fixture from a real instrument export.

The training export is excellent for import, parsing and reporting — it
validates the isomer summation against its own `Total` rows to floating-point
noise. But its QC injections bear no arithmetic relationship to the samples
they refer to, because the file was produced by scaling values rather than by
simulating the chemistry:

    spiking     LFSM higher than its parent for 11 analytes, LOWER for 12
    dilution    median dil/neat ratio 7.18 (should be ~1.0), range 6x to 514x
    injection IS  13C4-PFOA neat/dil ratio 9.71 (should be ~1.0)

So recovery, RPD, dilution agreement and internal-standard stability — the
rules that relate one injection to another — cannot be shown to PASS on it.
This rewrites only those relationships, leaving the chromatography untouched:

  * LFSM        = its parent plus the spike, so recovery lands at 100%
  * LFSM Dup    = the same plus a small offset, so RPD is small but non-zero
  * dilution    = agrees with its neat once the sample factor is applied
  * surrogates  in a dilution fall by the dilution factor (they are diluted)
  * injection IS in a dilution is held constant (added after the dilution)

Retention times, ion ratios, S/N, qualifiers and every calibration injection
are copied through unchanged, so the file still exercises the same import and
confirmation paths.

The SPIKE is expressed in the extract units the file uses. A spike recorded as
100 ppt on the sample basis corresponds to spike/matrix_factor in the extract,
because the pipeline multiplies native analytes by that factor at import.

Usage:
  derive_qc_coherent_fixture.py <in.csv> <out.csv>
      [--spike-ppt 100] [--matrix-factor 2.0] [--dup-bias 0.03]
"""
import argparse
import csv
import io
import re
import sys
from collections import defaultdict

# Relationships to build, by injection name.
PARENT_OF_LFSM = 'KCP Silage "Egg-2" Sample'
LFSM = 'KCP Silage "Egg-2" LFSM Mid'
LFSMD = 'KCP Silage "Egg-2" LFSM Mid Duplicate'
DILUTIONS = {
    'KCP Silage "Egg-3"; Dil. 1:10': 'KCP Silage "Egg-3" Sample',
    'KCP Silage "Egg-4"; Dil. 1:10': 'KCP Silage "Egg-4" Sample',
}
INJECTION_IS = "13C4-PFOA"


_SUFFIXED = re.compile(r"^\s*([-+0-9.eE]+)\s*\([^)]*\)\s*$")


def as_float(value):
    """Parse a concentration cell, including the instrument's qualified form.

    A value may arrive as "20.1268 (ALoQ)". Reading it with a bare float()
    returned None, so the parent contributed nothing and the derived spike
    landed at the spike amount alone — which is why PFBA, PFPeA, PFHxA, PFHpA
    and 8:2 FTS came out with impossible recoveries.
    """
    if value is None:
        return None
    text = str(value).strip()
    match = _SUFFIXED.match(text)
    if match:
        text = match.group(1)
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def fmt(value):
    return "{0:.12g}".format(value)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("output")
    ap.add_argument("--spike-ppt", type=float, default=100.0)
    ap.add_argument("--matrix-factor", type=float, default=2.0)
    ap.add_argument("--dup-bias", type=float, default=0.03,
                    help="fractional offset for the LFSM duplicate (RPD)")
    args = ap.parse_args()

    with io.open(args.source, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames
        rows = list(reader)

    by_injection = defaultdict(dict)
    for row in rows:
        by_injection[row["Injection Name"]][row["Compound Name"]] = row

    # The spike, expressed in the extract units this file reports in.
    spike_extract = args.spike_ppt / args.matrix_factor

    changed = {"lfsm": 0, "lfsmd": 0, "dilution": 0, "surrogate": 0, "is": 0}

    def set_conc(row, value):
        """Write a concentration, keeping the instrument's own arithmetic:
        Calculated = Measured x Sample Factor."""
        factor = as_float(row.get("Sample Factor")) or 1.0
        row["Calculated Concentration"] = fmt(value)
        row["Measured Concentration"] = fmt(value / factor if factor else value)

    # ── matrix spike and its duplicate ──────────────────────────────────────
    parent = by_injection.get(PARENT_OF_LFSM, {})
    for injection, bias in ((LFSM, 0.0), (LFSMD, args.dup_bias)):
        target = by_injection.get(injection, {})
        for compound, row in target.items():
            if row["Compound Type"] != "Analyte":
                continue
            base = as_float((parent.get(compound) or {}).get(
                "Calculated Concentration")) or 0.0
            set_conc(row, (base + spike_extract) * (1.0 + bias))
            row["Quantitation Status"] = "Successful"
            changed["lfsmd" if bias else "lfsm"] += 1

    # ── dilutions ───────────────────────────────────────────────────────────
    for injection, neat_name in DILUTIONS.items():
        neat = by_injection.get(neat_name, {})
        target = by_injection.get(injection, {})
        for compound, row in target.items():
            neat_row = neat.get(compound)
            if neat_row is None:
                continue
            if row["Compound Type"] == "Analyte":
                # After the sample factor is applied the dilution must land on
                # the same reported value as its neat.
                base = as_float(neat_row.get("Calculated Concentration"))
                if base is None:
                    continue
                set_conc(row, base)
                row["Quantitation Status"] = "Successful"
                changed["dilution"] += 1
            elif row["Compound Type"] == "Internal Standard":
                area = as_float(neat_row.get("Response"))
                if area is None:
                    continue
                factor = as_float(row.get("Sample Factor")) or 0.1
                dilution_factor = (1.0 / factor) if factor and factor < 1 else factor
                if compound == INJECTION_IS:
                    # Added at reconstitution, after the dilution — unchanged.
                    row["Response"] = fmt(area)
                    changed["is"] += 1
                else:
                    # A surrogate goes through the dilution with the sample.
                    row["Response"] = fmt(area / dilution_factor)
                    changed["surrogate"] += 1

    with io.open(args.output, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print("spike {0} ppt on the sample basis = {1:.6g} in the extract "
          "(matrix factor {2})".format(args.spike_ppt, spike_extract,
                                       args.matrix_factor))
    print("rewrote: LFSM {lfsm}, LFSMD {lfsmd}, dilution analytes {dilution}, "
          "surrogates {surrogate}, injection IS {is}".format(**changed))
    print("wrote {0} ({1} rows)".format(args.output, len(rows)))


if __name__ == "__main__":
    main()
