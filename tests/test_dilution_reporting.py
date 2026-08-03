"""
Dilution reporting rules.

A dilution is the same extract re-injected at a known factor because an analyte
read above the calibration range. The lab's rules, in the order they are
checked here:

  1. a dilution is not a sample of its own — it must not be reported twice;
  2. where the NEAT injection is ALoQ, the reported value comes from the
     dilution, and the over-range neat reading is retained beside it;
  3. where the neat is in range, the neat value stands — a dilution never
     silently overrides a perfectly good result;
  4. quantitation rules are NOT applied to a dilution, EXCEPT the internal
     standard check.

The real training export cannot exercise rule 2: its ALoQ analytes are in
Egg-1/Egg-2, which were never diluted, while Egg-3/Egg-4 were diluted but read
in range. So the cases below are constructed.

    python tests/test_dilution_reporting.py
"""
from __future__ import print_function

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from pfas_pipeline.models import Batch, InstrumentRow           # noqa: E402
from pfas_pipeline.pipeline import build_summary                 # noqa: E402
from pfas_pipeline.importer import classify_injection            # noqa: E402

NEAT = 'KCP Silage "Egg-9" Sample'
DIL = 'KCP Silage "Egg-9"; Dil. 1:10'
DILUTIONS = {DIL: {"parent": NEAT, "factor": 10.0}}

_failures = []


def check(label, got, want):
    ok = got == want
    print("  %-58s %s" % (label, "PASS" if ok else "FAIL  got %r want %r"
                          % (got, want)))
    if not ok:
        _failures.append(label)


def row(injection, compound, calc, qualifier="", rl=0.039):
    return InstrumentRow(
        compound_name=compound, compound_type="Analyte", compound_group="",
        sample_description="", injection_name=injection, sample_group="",
        sample_type="Unknown", included_in_cal=False, level=None,
        linked_is=None, cal_ref_compound=None, observed_rt=10.0,
        rt_relative_to_is=1.0, response=1000.0, is_response=1000.0,
        response_ratio=1.0, expected_conc=None, calculated_conc=calc,
        pct_deviation=None, pct_recovery_is=None, ion_ratios=None,
        expected_ion_ratios=None, r2=None, signal_to_noise=50.0, qual_sn=50.0,
        quant_status="Successful", reporting_limit=rl, measured_conc=calc,
        acquisition_datetime=datetime(2025, 10, 20, 12, 0, 0),
        concat_id=injection, conc_qualifier=qualifier)


def summarise(rows, dilutions):
    batch = Batch(batch_id="T", analyst="T", date=datetime(2025, 10, 20),
                  matrix="Animal Feed", method_id="FDA_32PFAS",
                  instrument_file="t.csv", injections=rows,
                  dilutions=dilutions)
    return {(s.sample_injection, s.analyte): s for s in build_summary(batch)}


print("classification")
check("dilution is classified Dilution when the logbook says so",
      classify_injection(DIL, DILUTIONS), "Dilution")
check("the same name is an ordinary Sample without the logbook",
      classify_injection(DIL, {}), "Sample")

print("\nrule 1 — a dilution is not a sample of its own")
rows = [row(NEAT, "PFOA", 1.0), row(DIL, "PFOA", 0.9)]
summary = summarise(rows, DILUTIONS)
check("dilution does not appear as its own sample",
      any(k[0] == DIL for k in summary), False)
check("neat still appears", (NEAT, "PFOA") in summary, True)

print("\nrule 2 — neat ALoQ reports from the dilution, neat retained")
rows = [row(NEAT, "PFOA", 250.0, qualifier="ALoQ"), row(DIL, "PFOA", 31.4)]
res = summarise(rows, DILUTIONS)[(NEAT, "PFOA")]
check("reported value comes from the dilution", res.result_ppt, 31.4)
check("provenance names the dilution injection", res.source_injection, DIL)
check("over-range neat reading retained", res.neat_result, 250.0)
check("neat qualifier retained", res.neat_qualifier, "ALoQ")
check("dilution factor recorded", res.dilution_factor, 10.0)
check("reported result is no longer flagged ALoQ", res.qualifier, "")

print("\nrule 3 — an in-range neat is never overridden")
rows = [row(NEAT, "PFOA", 1.0), row(DIL, "PFOA", 0.9)]
res = summarise(rows, DILUTIONS)[(NEAT, "PFOA")]
check("neat value stands", res.result_ppt, 1.0)
check("no substitution recorded", res.source_injection, NEAT)
check("nothing retained, because nothing was replaced", res.neat_result, None)

print("\nALoQ with no dilution available stays ALoQ")
rows = [row(NEAT, "PFOA", 250.0, qualifier="ALoQ")]
res = summarise(rows, {})[(NEAT, "PFOA")]
check("qualifier still reports the sample is over-range", res.qualifier, "ALoQ")
check("no false provenance", res.source_injection, NEAT)

# The isomer case needs the method profile's isomer_summation config, which is
# read from the exported /data/qc/method_profiles.json. That file exists in the
# worker container, not necessarily on a developer machine — so report it as
# skipped rather than failing for the wrong reason.
print("\nisomer pair: one isomer ALoQ makes the pair report from the dilution")
from pfas_pipeline.method_profiles import (                      # noqa: E402
    reload_from_profiles, get_isomer_summation)
reload_from_profiles()
if not get_isomer_summation("FDA_32PFAS"):
    print("  SKIPPED — no exported method profile "
          "(set PFAS_PROFILES_PATH to run this case)")
else:
    rows = [row(NEAT, "lr-PFOS", 200.0, qualifier="ALoQ"),
            row(NEAT, "br-PFOS", 50.0),
            row(DIL, "lr-PFOS", 22.0), row(DIL, "br-PFOS", 5.5)]
    res = summarise(rows, DILUTIONS)[(NEAT, "PFOS")]
    check("pair summed from the dilution", round(res.result_ppt, 6), 27.5)
    check("pair provenance names the dilution", res.source_injection, DIL)
    check("over-range neat sum retained", round(res.neat_result, 6), 250.0)

print()
if _failures:
    print("FAILED: %d" % len(_failures))
    for name in _failures:
        print("   -", name)
    sys.exit(1)
print("all dilution reporting rules hold")
