"""Salt (counter-ion) correction reaches the reported result.

§3 lists SALT FACTOR as a core method relation, "per analyte x method
(decimal < 1, from CoA)". Until 2026-08-03 it was editable in TWO user
interfaces, stored under THREE keys -- `salt_adjustment_factors` (Method
Profile editor, where the data actually is), `qc_rules.salt_factors` (QC Rules
page, deprecated by D53) and a seeded empty `extraction_corrections.salt_factors`
-- and applied by NONE of them. The string "salt" appeared nowhere in
pfas_pipeline except a shelf-life table.

FDA_32PFAS carries 0.9636 for PFOA against reference lot MXA-2453-A.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("PFAS_ALLOW_LEGACY_VENDOR_MAP", "1")

from pfas_pipeline import method_profiles as mp


def test_salt_factors_read_from_the_key_the_editor_writes():
    factors = mp.get_salt_factors("FDA_32PFAS")
    if not factors:
        print("  (skipped: no method profile export loaded)")
        return
    assert factors.get("PFOA") == 0.9636, factors
    # A recorded 1.0 means "lot linked, no adjustment" and must not be applied
    # as a correction -- it would be a no-op, but it would also claim in the log
    # that a correction happened.
    assert all(f != 1.0 for f in factors.values()), factors


def test_isomer_components_inherit_the_parent_factor():
    """lr-/br- rows come from the same salt-form standard as the analyte they
    sum to. Naming only the reported analyte leaves the sum uncorrected."""
    profile = mp._profile_data_cache.get("FDA_32PFAS", {})
    if not profile:
        print("  (skipped: no method profile export loaded)")
        return
    original = profile.get("salt_adjustment_factors")
    try:
        profile["salt_adjustment_factors"] = [
            {"analyte": "PFOS", "factor": 0.95}]
        factors = mp.get_salt_factors("FDA_32PFAS")
        assert factors.get("PFOS") == 0.95, factors
        assert factors.get("lr-PFOS") == 0.95, factors
        assert factors.get("br-PFOS") == 0.95, factors
    finally:
        profile["salt_adjustment_factors"] = original


def test_correction_is_applied_and_composes_with_the_matrix_factor():
    from pfas_pipeline.importer import load_instrument_csv
    from pfas_pipeline.pipeline import apply_extract_corrections

    csv_path = os.environ.get("PFAS_TEST_RUN_CSV")
    if not csv_path or not os.path.exists(csv_path):
        print("  (skipped: set PFAS_TEST_RUN_CSV to an instrument export)")
        return

    rows = load_instrument_csv(csv_path)
    target = next((r for r in rows
                   if r.compound_name == "PFOA"
                   and r.calculated_conc is not None), None)
    assert target is not None, "no PFOA row with a concentration"
    key = (target.injection_name, target.compound_name)

    def value(rs):
        for r in rs:
            if (r.injection_name, r.compound_name) == key:
                return r.calculated_conc

    before = value(rows)
    apply_extract_corrections(rows, "FDA_32PFAS", "Animal Feed")
    after = value(rows)

    matrix_factor = mp.get_matrix_factor("FDA_32PFAS", "Animal Feed")
    expected = 0.9636 * matrix_factor
    assert abs(after / before - expected) < 1e-9, (before, after, expected)


def test_surrogates_and_internal_standards_are_not_corrected():
    """Both corrections are native-only: an IS is judged on its own response,
    and correcting it would move the very baseline it provides."""
    from pfas_pipeline.importer import load_instrument_csv
    from pfas_pipeline.pipeline import apply_extract_corrections

    csv_path = os.environ.get("PFAS_TEST_RUN_CSV")
    if not csv_path or not os.path.exists(csv_path):
        print("  (skipped: set PFAS_TEST_RUN_CSV to an instrument export)")
        return

    rows = load_instrument_csv(csv_path)
    before = {(r.injection_name, r.compound_name): r.calculated_conc
              for r in rows
              if (r.compound_type or "").strip() != "Analyte"}
    apply_extract_corrections(rows, "FDA_32PFAS", "Animal Feed")
    after = {(r.injection_name, r.compound_name): r.calculated_conc
             for r in rows
             if (r.compound_type or "").strip() != "Analyte"}
    assert before == after, "non-analyte rows were altered"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
