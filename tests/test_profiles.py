"""Pass 5 regression: method profiles, multi-vendor import, sequence templates."""
import sys, os, csv
os.environ.setdefault("PFAS_ALLOW_LEGACY_VENDOR_MAP", "1")  # tests exercise the legacy vendor map
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import date
from pfas_pipeline.method_profiles import get_profile, available_profiles
from pfas_pipeline.qc_engine import recovery_check_profiled, rpd_check_profiled
from pfas_pipeline.injection_builder import InjectionSequenceBuilder
from pfas_pipeline.vendor_profiles import detect_vendor, get_vendor_profile
from pfas_pipeline.importer import load_instrument_csv

def test_fda_three_tier():
    fda = get_profile("FDA")
    # Tier 1: big-four in animal protein → 80-120%
    r = fda.qc_rules("PFOA", "deer muscle", "LFSM")
    assert (r.recovery_min, r.recovery_max) == (80.0, 120.0), r
    # Tier 2: big-four elsewhere → 65-135%
    r = fda.qc_rules("PFOA", "water", "LFSM")
    assert (r.recovery_min, r.recovery_max) == (65.0, 135.0), r
    # Tier 2: ordinary analyte → 65-135%
    r = fda.qc_rules("PFHpA", "deer muscle", "LFSM")
    assert (r.recovery_min, r.recovery_max) == (65.0, 135.0), r
    # Tier 3: no labeled standard → 40-140% + RSDr 30
    r = fda.qc_rules("PFTrDA", "deer muscle", "LFSM")
    assert (r.recovery_min, r.recovery_max, r.rsd_max) == (40.0, 140.0, 30.0), r
    # r2 must be 0.990 not 0.995
    assert fda.calibration_rule("PFOA").r2_min == 0.990
    # CCV every 6
    assert fda.ccv_rule().frequency == 6
    # duplicates 20%
    assert fda.qc_rules("PFOA","deer","Dup").rpd_max == 20.0
    print("✓ FDA three-tier recovery + r²=0.990 + CCV/6 + dup 20%")

def test_recovery_flagging():
    fda = get_profile("FDA")
    # PFOA at 75% in meat → fails tier-1 80-120
    f = recovery_check_profiled(fda, "PFOA", "meat", "LFSM", 75.0, "inj1")
    assert f and "80–120" in f.issue, f
    # same 75% for PFTrDA (40-140) → passes
    f = recovery_check_profiled(fda, "PFTrDA", "meat", "LFSM", 75.0, "inj1")
    assert f is None
    # FDA duplicate RPD 25% → fails 20%
    f = rpd_check_profiled(fda, "PFOA", "meat", "Dup", 25.0, "inj1")
    assert f and "20%" in f.issue
    print("✓ recovery + RPD flagging honors per-analyte/matrix limits")

def test_537_vs_1633():
    e537 = get_profile("537.1")
    assert e537.is_rule().vs_last_ccv_max == 140.0       # 70-140 of CCV
    assert e537.is_rule().vs_ical_avg_min == 50.0        # ±50 ICAL
    assert e537.calibration_rule().force_origin is True
    assert e537.confirmation_rule().rt_tol_abs_min == 0.05
    e1633 = get_profile("1633A")
    r = e1633.qc_rules("M2-6:2FTS", "aqueous", "EIS")
    assert r.verify_against_method is True
    print("✓ 537.1 dual-IS + forced origin; 1633A EIS verify-flag")

def test_sequence_templates():
    # FDA: opens with MeOH blank, blank after curve, CCV/6
    fda_b = InjectionSequenceBuilder(date(2026,2,26), "KCP", "Deer", method="FDA")
    assert fda_b.ccv_interval == 6
    seq = fda_b.build_standard_pfas_run(
        [{"description": f"S{i}"} for i in range(1, 13)],
        lfsm_parent="S6", spike_ppt=80.0)
    qc = [i.qc_type for i in seq]
    assert qc[0] == "SolventBlank", qc[:3]
    assert "SolventBlank" in qc[1:]          # blank after curve too
    assert qc.count("SolventBlank") >= 2
    assert qc[-1] == "CCV"
    # 537.1: no opening solvent blank, CCV/10
    e_b = InjectionSequenceBuilder(date(2026,2,26), "KCP", "Water", method="537")
    assert e_b.ccv_interval == 10
    seq2 = e_b.build_standard_pfas_run(
        [{"description": f"S{i}"} for i in range(1, 13)],
        lfsm_parent="S6", spike_ppt=40.0)
    qc2 = [i.qc_type for i in seq2]
    assert qc2[0] == "CAL", qc2[:3]          # starts with curve, no MeOH blank
    print(f"✓ FDA seq opens MeOH blank+CCV/6 ({qc.count('SolventBlank')} blanks); "
          f"537.1 seq CCV/10")

def test_vendor_detection():
    assert detect_vendor(["Component Name","Area Ratio","Sample Type"]) == "sciex"
    assert detect_vendor(["Data File","ISTD Resp","Final Conc."]) == "agilent"
    assert detect_vendor(["Sample Text","IS Area","Acq.Date"]) == "waters"
    assert detect_vendor(["Injection Name","Compound Name"]) == "native"
    print("✓ vendor auto-detection (SCIEX/Agilent/Waters/native)")

def test_vendor_import():
    # Build a tiny SCIEX OS-style CSV and confirm it maps to canonical fields
    p = "/tmp/sciex_test.csv"
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Component Name","Component Type","Sample Name","Sample Type",
                    "Retention Time","Area","Area Ratio","Calculated Concentration",
                    "R^2","Signal / Noise","Acquisition Date","Acquisition Time"])
        w.writerow(["PFOA","Target","FDA-CAL-5-260226","Standard",
                    "5.20","10000","0.5","1.25","0.998","150",
                    "2026-03-13","17:05:00"])
    rows = load_instrument_csv(p)  # auto-detect
    assert len(rows) == 1
    assert rows[0].compound_name == "PFOA"
    assert rows[0].observed_rt == 5.20
    assert rows[0].response_ratio == 0.5
    assert rows[0].r2 == 0.998
    print("✓ SCIEX OS CSV imported via auto-detected vendor profile")

if __name__ == "__main__":
    print("Profiles available:", list(available_profiles().keys()))
    test_fda_three_tier()
    test_recovery_flagging()
    test_537_vs_1633()
    test_sequence_templates()
    test_vendor_detection()
    test_vendor_import()
    print("\nALL PROFILE REGRESSION TESTS PASSED")
