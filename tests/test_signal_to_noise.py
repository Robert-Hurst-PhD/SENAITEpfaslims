"""Two signal-to-noise thresholds, two questions, two verdicts.

  * `sn_quan_min`    — minimum S/N to QUANTITATE. Below it the peak is real but
                       the number is an estimate. That is what the `sn` failure
                       type means: code **J**, statement "the affected results
                       are estimated".
  * `sn_confirm_min` — minimum S/N on the CONFIRMATION (qualifier) ion. Below it
                       the identification itself is not confirmed: **N.C.**

Until 2026-08-07 only the first reached the engine — `constants.py` wrote it
into a key called `sn_min` — and BOTH branches of `signal_to_noise_check`
compared against it, reporting "(N.C.)" for both. So:

  * a low quantitation ion was labelled "not confirmed" when the taxonomy,
    the qualifier code and the certificate statement all say "estimated"; and
  * the qualifier ion was judged against the QUANTITATION limit. On EPA 1633A —
    the one method with this check enabled — that is 3.0 against a configured
    confirmation limit of **1.0**, so qualifier ions between 1 and 3 were failed
    by a criterion the method does not apply to them. `sn_confirm_min` was
    configured and read by nothing.

The rule these tests defend: an unconfigured `sn_confirm_min` means the
qualifier ion is NOT judged. Borrowing the other threshold is the bug.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("PFAS_ALLOW_LEGACY_VENDOR_MAP", "1")

from pfas_pipeline.constants import CRITERIA
from pfas_pipeline.models import InstrumentRow
from pfas_pipeline.qc_engine import signal_to_noise_check


def _row(sn=None, qual_sn=None, name="Sample-1", analyte="PFOA"):
    """An InstrumentRow with only the fields this check reads.

    It is a dataclass with ~30 required fields; filling them by hand here would
    be noise, and a default for each would silently drift from the real model.
    """
    import dataclasses
    values = {}
    for field in dataclasses.fields(InstrumentRow):
        values[field.name] = "" if field.type is str else None
    values.update(injection_name=name, compound_name=analyte,
                  signal_to_noise=sn, qual_sn=qual_sn)
    return InstrumentRow(**values)


def _with(quan=None, confirm=None):
    """Temporarily set the two thresholds, restoring them afterwards."""
    saved = (CRITERIA.get("sn_quan_min"), CRITERIA.get("sn_confirm_min"),
             CRITERIA.get("sn_min"))
    CRITERIA["sn_quan_min"] = quan
    CRITERIA["sn_confirm_min"] = confirm
    CRITERIA["sn_min"] = quan
    return saved


def _restore(saved):
    CRITERIA["sn_quan_min"], CRITERIA["sn_confirm_min"], CRITERIA["sn_min"] = saved


def test_a_low_quantitation_ion_is_estimated_not_unconfirmed():
    saved = _with(quan=3.0, confirm=1.0)
    try:
        flags = signal_to_noise_check([_row(sn=2.0)], "PFOA")
        assert len(flags) == 1, flags
        assert flags[0].issue == "(J)", (
            "a quantitation ion below the limit means the RESULT is estimated; "
            "'(N.C.)' claims the identification failed, which is a different "
            "finding and contradicts the J code on the certificate")
    finally:
        _restore(saved)


def test_a_good_quantitation_ion_raises_nothing():
    saved = _with(quan=3.0, confirm=1.0)
    try:
        assert signal_to_noise_check([_row(sn=25.0, qual_sn=8.0)], "PFOA") == []
    finally:
        _restore(saved)


def test_the_qualifier_ion_is_judged_on_the_confirmation_limit():
    """The EPA 1633A case: confirm=1.0, quan=3.0. A qualifier ion at 2.0 is
    ABOVE the method's confirmation limit and must not be flagged — it used to
    be, against the quantitation limit."""
    saved = _with(quan=3.0, confirm=1.0)
    try:
        assert signal_to_noise_check([_row(sn=25.0, qual_sn=2.0)], "PFOA") == [], (
            "qualifier ion at 2.0 with a confirmation limit of 1.0 was flagged "
            "-- it is being judged against the quantitation threshold again")
        flags = signal_to_noise_check([_row(sn=25.0, qual_sn=0.5)], "PFOA")
        assert len(flags) == 1 and flags[0].issue == "(N.C.)", flags
    finally:
        _restore(saved)


def test_an_unconfigured_confirmation_limit_does_not_borrow_the_other_one():
    """Refuse to judge. EPA 537.1 has no sn_confirm_min configured."""
    saved = _with(quan=3.0, confirm=None)
    try:
        assert signal_to_noise_check([_row(sn=25.0, qual_sn=0.1)], "PFOA") == [], (
            "with no confirmation limit configured the qualifier ion must not "
            "be judged at all")
        # the quantitation ion is still judged on its own limit
        assert len(signal_to_noise_check([_row(sn=1.0)], "PFOA")) == 1
    finally:
        _restore(saved)


def test_the_two_limits_reach_the_engine_separately():
    """`constants.py` used to map only sn_quan_min, into a key named sn_min."""
    from pfas_pipeline.constants import _build_criteria_from_profile
    crit = _build_criteria_from_profile({
        "instrument_verification": {
            "confirmation": {"sn_quan_min": 3.0, "sn_confirm_min": 1.0}}})
    assert crit.get("sn_quan_min") == 3.0, crit.get("sn_quan_min")
    assert crit.get("sn_confirm_min") == 1.0, (
        "sn_confirm_min still never reaches the engine")
    assert crit.get("sn_min") == 3.0, "the back-compat alias changed meaning"


def test_the_live_1633a_profile_is_the_case_this_protects():
    """Recorded so the numbers in the docstring stay checkable."""
    import json
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "data", "qc", "method_profiles.json")) as fh:
        conf = (json.load(fh)["EPA_1633A"]["instrument_verification"]
                ["confirmation"])
    assert conf.get("sn_confirm_min") == 1.0, conf.get("sn_confirm_min")
    assert conf.get("sn_quan_min") == 3.0, conf.get("sn_quan_min")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
