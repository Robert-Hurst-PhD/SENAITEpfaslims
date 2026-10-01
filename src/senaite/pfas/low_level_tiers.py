# -*- coding: utf-8 -*-
"""Low-level QC tiers from the published method text (DECISIONS 2026-10-01).

A tier with low_level_x_rl = N applies instead of the ordinary tier when the
fortified concentration is at or below N x the analyte's RL (the engine:
pfas_pipeline.method_profiles._low_level_tier).

EPA 537.1 states its low-level windows in the method text. Read from the
method itself, v2.0 (EPA/600/R-20/006, March 2020); v1.0 (EPA/600/R-18/352)
has the same wording:

  §9.3.3   LFB: low level (no more than two times the MRL) 50-150%;
           medium and high 70-130%.
  §9.3.6.3 LFSM: 70-130%, "except for low-level fortification near or at the
           MRL (within a factor of 2-times the MRL concentration) where
           50-150% recoveries are acceptable".
  §9.3.7.4 LFSMD RPD <= 30%; "within a factor of 2 of the MRL ... <= 50%".

seed_537_1() adds them once (marker SEEDED_KEY), so a tier the lab later
removes on purpose is not re-added. Pure; Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

LOW_LEVEL_KEY = "low_level_x_rl"
SEEDED_KEY = "low_level_tiers_seeded"
_DOC = "EPA 537.1 v2.0 (EPA/600/R-20/006, March 2020)"

SEEDS_537_1 = {
    "LFSM": {"name": "low_level", "analyte_group": "all", "matrix_scope": "all",
             LOW_LEVEL_KEY: 2.0, "recovery_min": 50.0, "recovery_max": 150.0,
             "description": "Within 2 x MRL (§9.3.6.3)",
             "citation": _DOC + " §9.3.6.3"},
    "LFSMD": {"name": "low_level", "analyte_group": "all", "matrix_scope": "all",
              LOW_LEVEL_KEY: 2.0, "rpd_max": 50.0,
              "description": "Within 2 x MRL (§9.3.7.4)",
              "citation": _DOC + " §9.3.7.4"},
    "LFB": {"name": "low_level", "analyte_group": "all", "matrix_scope": "all",
            LOW_LEVEL_KEY: 2.0, "recovery_min": 50.0, "recovery_max": 150.0,
            "description": "Low level, no more than 2 x MRL (§9.3.3)",
            "citation": _DOC + " §9.3.3"},
}


def seed_537_1(profile):
    """True if EPA 537.1's low-level tiers were added (idempotent)."""
    if profile.get("method_id") != "EPA_537_1" or profile.get(SEEDED_KEY):
        return False
    qca = profile.get("qc_acceptance") or {}
    for qc, seed in sorted(SEEDS_537_1.items()):
        entry = qca.get(qc)
        if not isinstance(entry, dict):
            continue                        # the method does not run it here
        tiers = entry.setdefault("tiers", [])
        if any(isinstance(t, dict) and t.get(LOW_LEVEL_KEY) for t in tiers):
            continue
        same = [t for t in tiers if isinstance(t, dict) and t.get("name") == seed["name"]]
        if same:
            # the lab's own "low_level" tier (LFB: described "At or below MRL"
            # and read as the FIRST tier for every LFB): give it the method's
            # condition and wording (the method says up to 2 x MRL), keep its
            # window
            same[0][LOW_LEVEL_KEY] = seed[LOW_LEVEL_KEY]
            same[0]["description"] = seed["description"]
            same[0]["citation"] = seed["citation"]
        else:
            tiers.append(dict(seed))
    profile[SEEDED_KEY] = "2026-10-01"
    return True
