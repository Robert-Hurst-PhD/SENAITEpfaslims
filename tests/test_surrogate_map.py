"""The method profile owns the surrogate -> analyte quantification link (§3).

Until 2026-08-03 nothing read it. `surrogate_map`, `surrogate_is` and
`surrogate_is_chain` were all written by the Method Profile editor and never
consulted by the analysis, which took the relationship from the instrument
file's own `linked_is` column instead. A lab editing the drag-and-drop
surrogate map changed no result.

These tests pin the three things that have to hold now that it is wired:
the profile is authoritative, spelling differences are not disagreements, and
a real disagreement is still reported.
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("PFAS_ALLOW_LEGACY_VENDOR_MAP", "1")

from pfas_pipeline import method_profiles as mp
from pfas_pipeline.analyte_alias import keyword_for


def test_labelled_compounds_have_aliases():
    """The alias table used to walk only NATIVE_ANALYTES, so nothing could tell
    that the profile's M8PFOA and the instrument's 13C8-PFOA are one compound."""
    assert keyword_for("13C8-PFOA") == "M8PFOA"
    assert keyword_for("13C4-PFOA") == "M4PFOA"
    assert keyword_for("13C2,D4-8:2FTS") == "M2-8:2FTS"
    # A native is unaffected.
    assert keyword_for("PFOA") == "PFOA"


def test_surrogate_map_is_keyed_both_ways():
    """The profile stores keywords; the instrument exports display names."""
    smap = mp.get_surrogate_map("FDA_32PFAS")
    if not smap:
        print("  (skipped: no method profile export loaded)")
        return
    assert smap.get("PFOA") == "M8PFOA", smap.get("PFOA")
    # Spaced and unspaced spellings of the same analyte both resolve.
    assert smap.get("8:2 FTS") == smap.get("8:2FTS") != None


def test_mismatch_is_detected_not_silently_resolved():
    """A method naming one surrogate while the instrument used another is a
    review finding. Verified by perturbing one entry, so the detector is known
    to fire rather than merely known to be quiet."""
    from pfas_pipeline.importer import load_instrument_csv
    from pfas_pipeline.models import Batch
    from pfas_pipeline import pipeline as P

    csv_path = os.environ.get("PFAS_TEST_RUN_CSV")
    if not csv_path or not os.path.exists(csv_path):
        print("  (skipped: set PFAS_TEST_RUN_CSV to an instrument export)")
        return

    rows = load_instrument_csv(csv_path)

    def summarise():
        batch = Batch(batch_id="T", injections=rows, analyst="t",
                      date=datetime.date(2025, 10, 20), matrix="Animal Feed",
                      method_id="FDA_32PFAS", instrument_file=csv_path)
        return P.build_summary(batch)

    def ismap_flags(summary):
        return {f for r in summary for f in r.flags if f.startswith("ISMAP")}

    assert not ismap_flags(summarise()), "profile and instrument should agree"

    profile = mp._profile_data_cache.get("FDA_32PFAS", {})
    original = profile.get("surrogate_map")
    try:
        profile["surrogate_map"] = [{"analyte": "PFOA",
                                     "surrogate_is": "M5PFNA"}]
        flags = ismap_flags(summarise())
        assert any("M5PFNA" in f for f in flags), flags
    finally:
        profile["surrogate_map"] = original


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
