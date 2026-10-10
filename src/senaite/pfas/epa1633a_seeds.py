# -*- coding: utf-8 -*-
"""What EPA 1633A itself states, applied once to its method profile.

EPA 1633A (EPA 820-R-24-007, Dec 2024) verifies calibration with a CV
standard at 70-130 % recovery (§14.3.3) and has no separate second-source
ICV criterion: the ICV is judged with the CCV's window (lab, 2026-10-10).
Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

ICV_KEY = "icv_as_ccv_1633a_v"
LAB_SPIKE_KEY = "spike_dup_lab_values_1633a_v"
# EPA 1633A sets no matrix-spike or duplicate criterion (§9.7, §9.9); the
# lab keeps its own (lab, 2026-10-10)
LAB_NOTE = (u"The lab's value: EPA 1633A sets no matrix-spike or duplicate "
            u"criterion (§9.7, §9.9).")


def seed_lab_spike_values(profile, method_id):
    """Once, for EPA 1633A: the LFSM / LFSMD / Dup tiers are the lab's own
    values, not placeholders awaiting the method."""
    if method_id != "EPA_1633A" or profile.get(LAB_SPIKE_KEY) == 1:
        return False
    qca = profile.get("qc_acceptance") or {}
    for qc in ("LFSM", "LFSMD", "Dup"):
        for tier in (qca.get(qc) or {}).get("tiers") or []:
            tier.pop("verify_against_method", None)
            tier["citation"] = LAB_NOTE
    profile[LAB_SPIKE_KEY] = 1
    return True


def seed_icv_as_ccv(profile, method_id):
    """Once, for EPA 1633A: the ICV is judged with the CCV's window."""
    if method_id != "EPA_1633A" or profile.get(ICV_KEY) == 1:
        return False
    iv = profile.setdefault("instrument_verification", {})
    icv = iv.setdefault("icv", {})
    icv["criteria"] = "ccv"
    icv.pop("pct_dev_max", None)
    profile[ICV_KEY] = 1
    return True
