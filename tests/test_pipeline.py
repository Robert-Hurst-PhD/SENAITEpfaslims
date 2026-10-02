"""End-to-end smoke test with a synthetic batch matching the real
FDA-CAL-x-260226 / KCP Deer Sample structure from the actual xlsm data."""
import csv, sys, os
os.environ.setdefault("PFAS_ALLOW_LEGACY_VENDOR_MAP", "1")  # tests exercise the legacy vendor map
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
from pfas_pipeline.pipeline import run_pipeline
from pfas_pipeline.importer import validate_injection_name
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "src", "senaite", "pfas"))
import extraction_sidecar  # noqa: E402  (pure add-on module, the Run Builder's writer)

def make_test_csv(path):
    """Synthetic instrument export: CALs + MB + 3 samples + LFSM pair."""
    compounds = ["PFOA", "PFOS", "PFNA", "13C8-PFOA", "13C8-PFOS"]
    injections = [
        ("FDA-CAL-1-260226",   "Standard", 20.0),
        ("FDA-CAL-5-260226",   "Standard", 1.25),
        ("FDA-CAL-10-260226",  "Standard", 0.039),
        ("FDA-ICV-260226",     "QC", 1.25),
        ("FDA-CCV-260226-01",  "QC", 1.25),
        ('KCP Water MB 2026-03-13-01', "QC", None),
        ('KCP Deer Sample "Deer Hamburger"', "Unknown", None),
        ('KCP Deer Sample "Deer Hamburger"; LFSM High', "QC", None),
        ('KCP Deer Sample "Deer Hamburger"; LFSM High Dup.', "QC", None),
        ("FDA-CCV-260226-02",  "QC", 1.25),
    ]
    headers = ["Compound Name","Compound Type","Sample Description",
               "Injection Name","Sample Type","Observed RT (min)","Response",
               "IS Response","Response Ratio","Expected Concentration",
               "Calculated Concentration","Measured Concentration",
               "% Deviation","R2","Signal to Noise",
               "Reporting Limit","Linked Internal Standard",
               "Acquisition Date","Acquisition Time","Concat ID"]
    rows = []
    t = 170500
    for inj, stype, conc in injections:
        for cmp_i, cmp in enumerate(compounds):
            is_IS = cmp.startswith("13C")
            rt = 5.2 + cmp_i*0.5
            # introduce one RT outlier and one IS dropout
            if inj.endswith("Dup.") and cmp == "PFOA":
                rt += 0.25  # RT flag
            rr = 0.5
            if "MB" in inj and cmp == "13C8-PFOS":
                rr = 0.1    # IS drift flag (< 50% of avg)
            meas = (conc or 25.0) if not is_IS else ""
            if "MB" in inj and not is_IS:
                meas = 0.05  # tiny blank level
            rows.append([
                cmp, "IS" if is_IS else "Target", inj, inj, stype,
                f"{rt:.3f}", "10000", "9500", f"{rr}",
                conc or "", meas, meas,
                "0.05" if stype=="Standard" else "",
                "0.998" if stype=="Standard" else "",
                "150", "0.5",
                "" if is_IS else "13C8-PFOA",
                "2026-03-13", f"{t//10000:02d}:{(t//100)%100:02d}:00",
                f"{inj}|20260313{t}",
            ])
        t += 2100
    with open(path, "w", newline="") as f:
        w = csv.writer(f); w.writerow(headers); w.writerows(rows)

def main():
    import shutil; shutil.rmtree("/tmp/pfas_test", ignore_errors=True); os.makedirs("/tmp/pfas_test")
    csv_path = "/tmp/pfas_test/batch_260226.csv"
    make_test_csv(csv_path)

    # 1. Injection name validation
    v = validate_injection_name('KCP Water MB 2026-03-13-01')
    assert v["valid"], v
    v = validate_injection_name("FDA-CAL-10-260226")
    assert v["valid"], v
    print("✓ injection name validation")

    # 2-3. The extraction record, as the Run Builder writes it from the
    # SENAITE guided extraction (the tablet catalogue is retired, DB1)
    session = {"method_id": "FDA_32PFAS", "analyst": "KCP",
               "started_at": "2026-02-26T13:00:00Z", "finalized": True,
               "finalized_at": "2026-02-26T16:30:00Z", "finalized_by": "KCP",
               "stages": {"1": {"completed_at": "2026-02-26T13:40:00Z", "analyst": "KCP",
                                "deviations": "",
                                "reagents": [{"role": "Methanol", "name": "Methanol LC-MS",
                                              "lot": "LOT24A77", "expiry": "2027-01-31",
                                              "inventory_uid": "abc"},
                                             {"role": "Water", "name": "Water", "lot": ""}]}}}
    record = extraction_sidecar.build_sidecar(
        session, {"1": "Sample Weighing"}, worksheet_id="batch_260226", matrix="Deer")
    assert [s["lot_number"] for s in record["reagent_scans"]] == ["LOT24A77"]
    with open("/tmp/pfas_test/batch_260226_extraction.json", "w") as fh:
        json.dump(record, fh)
    print("✓ extraction record from the guided extraction")

    # 4. Full pipeline
    batch, queue, pdf = run_pipeline(
        csv_path, analyst="KCP", matrix="Deer",
        extraction_log_path="/tmp/pfas_test/batch_260226_extraction.json",
        output_dir="/tmp/pfas_test/out")
    assert pdf.exists() and pdf.stat().st_size > 1000
    assert batch.extraction_log["reagent_scans"][0]["lot_number"] == "LOT24A77"
    print(f"✓ pipeline: {len(batch.qc_flags)} QC flags, "
          f"{len(queue.pending())} pending checks, report={pdf.stat().st_size}B")

    # 5. Queue persistence (review from home)
    from pfas_pipeline.run_queue import RunQueue
    q2 = RunQueue.load(batch, "/tmp/pfas_test/out/batch_260226_queue.json")
    assert len(q2.checks) == len(queue.checks)
    p = queue.pending()
    if p:
        queue.accept(p[0]["injection"], p[0]["check"], "KCP", "reviewed ok")
    print("✓ run queue persistence + accept")

    print("\nALL TESTS PASSED")

if __name__ == "__main__":
    main()
