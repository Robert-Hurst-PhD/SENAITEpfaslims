# -*- coding: utf-8 -*-
"""Low-level QC tiers from the published method text.

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
  §9.3.7.2 field duplicate RPD "should" be <= 30%; within a factor of 2 of
           the MRL <= 50% (judged with the duplicate RPD check).

Pure; Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

LOW_LEVEL_KEY = "low_level_x_rl"


