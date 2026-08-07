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
        # is_mismatch, NOT flags: flags are folded into the displayed value and
        # pushed to Analysis Remarks, both of which reach the client CoA. A
        # reviewer finding must not print on the client's certificate.
        return {r.is_mismatch for r in summary if r.is_mismatch}

    assert not ismap_flags(summarise()), "profile and instrument should agree"

    profile = mp._profile_data_cache.get("FDA_32PFAS", {})
    original = profile.get("surrogate_map")
    try:
        profile["surrogate_map"] = [{"analyte": "PFOA",
                                     "surrogate_is": "M5PFNA"}]
        flags = ismap_flags(summarise())
        assert any("M5PFNA" in f for f in flags), flags
        # and never on the client surface
        batch_summary = summarise()
        assert not [f for r in batch_summary for f in r.flags
                    if "ISMAP" in f], "mismatch leaked into the value string"
    finally:
        profile["surrogate_map"] = original




# ── The map's CONTENTS, derived rather than hand-copied (2026-08-06) ─────────
#
# Which labelled compound quantifies a native is a property of the ANALYTE, not
# of the method, and is recorded once in `analyte_reference.NATIVE_ANALYTES`.
# The FDA and 1633A profiles carried hand-maintained copies of it. EPA 537.1
# carried an EMPTY list, so `qc_qualification.analytes_for_failure` had no map
# to reverse and named the LABELLED compound on the certificate -- a compound
# the client never ordered and never sees -- instead of the natives.

def _analyte_reference():
    """Load the add-on's master table without importing the Plone package."""
    import importlib.util
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "src", "senaite", "pfas", "analyte_reference.py")
    spec = importlib.util.spec_from_file_location("pfas_analyte_reference", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_surrogate_link_names_an_IS_KEYWORD_not_a_display_name():
    """Six entries -- the four FTS analytes, FOSA and GenX -- held a DISPLAY
    NAME where the other 21 held a keyword. The single consumer does
    `_IS_KW_TO_NAME.get(value, "")`, so those six resolved to an EMPTY
    surrogate column in the FDA profile's per_analyte table."""
    ar = _analyte_reference()
    keywords = {row[0] for row in ar.INTERNAL_STANDARDS}
    names = {row[1] for row in ar.INTERNAL_STANDARDS}
    wrong = [(row[0], row[6]) for row in ar.NATIVE_ANALYTES
             if row[6] and row[6] not in keywords]
    assert not wrong, (
        "these natives link to something that is not an IS keyword %s "
        "(display names in that column resolve to an empty surrogate): %s"
        % ("-- and they ARE display names" if all(v in names for _, v in wrong)
           else "", wrong))


def test_the_derivation_reproduces_the_hand_maintained_maps():
    """The evidence that deriving EPA 537.1 applies an existing validated
    relation rather than inventing a regulatory value (CLAUDE.md §8): the same
    derivation reproduces the two maps a human already maintained, entry for
    entry AND in the same order."""
    import json
    ar = _analyte_reference()
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "data", "qc", "method_profiles.json")) as fh:
        profiles = json.load(fh)
    for method_id in ("FDA_32PFAS", "EPA_1633A"):
        stored = profiles[method_id].get("surrogate_map") or []
        derived = ar.derive_surrogate_map(
            profiles[method_id].get("master_analyte_set") or [])
        assert stored == derived, (
            "%s's stored surrogate_map no longer matches the derivation -- "
            "either the master table changed or the profile was hand-edited. "
            "stored=%d derived=%d" % (method_id, len(stored), len(derived)))


def test_epa_537_has_a_surrogate_map():
    """It shipped empty. With no map, a surrogate failure named the labelled
    compound on the client's certificate."""
    import json
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "data", "qc", "method_profiles.json")) as fh:
        profiles = json.load(fh)
    mapping = profiles["EPA_537_1"].get("surrogate_map") or []
    assert len(mapping) >= 15, "EPA 537.1 surrogate_map is %d entries" % len(mapping)
    by_analyte = {e["analyte"]: e["surrogate_is"] for e in mapping}
    assert by_analyte.get("PFOA") == "M8PFOA", by_analyte.get("PFOA")
    assert by_analyte.get("PFHpA") == "M4PFHpA", by_analyte.get("PFHpA")
    # one surrogate may quantify several natives -- that is the many-to-one
    # relation CLAUDE.md §3 describes, not a duplicate
    assert by_analyte.get("PFDoA") == by_analyte.get("PFTrDA") == "MPFDoA"


def test_the_defaults_are_derived_not_copied():
    """A hand-copy is free to drift from the table, and did."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    store = os.path.join(root, "src", "senaite", "pfas", "method_profile_store.py")
    with open(store) as fh:
        body = fh.read()
    assert '"surrogate_map": [],' not in body, "a method still ships an empty map"
    assert body.count('"surrogate_map": _derive_surrogate_map(') == 3, (
        "all three methods should derive their surrogate map")


def test_the_epa_is_chain_is_left_unset_on_purpose():
    """`surrogate_is_chain` needs the injection IS each surrogate quantifies
    against. `INTERNAL_STANDARDS` has no such column -- only a prose comment
    that FDA's quantify against M4PFOA per Table 9-1 -- and `surrogate_is` is
    empty on both EPA methods. Asserting one would be fabricating a regulatory
    value (§8); EPA 537.1 quantifies by isotope dilution against the labelled
    analog, not one shared injection standard. This test exists so the gap is
    a decision on record, not an oversight someone 'fixes' by guessing."""
    ar = _analyte_reference()
    assert len(ar.INTERNAL_STANDARDS[0]) == 4, (
        "INTERNAL_STANDARDS gained a column -- if it is a quantitation IS, the "
        "chain can now be derived for the EPA methods; see GAPS.md")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
