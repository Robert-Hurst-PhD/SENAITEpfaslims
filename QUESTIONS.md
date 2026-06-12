# QUESTIONS.md — open questions awaiting lab answer

---

## Q-006  QAO and Lab Director roles — define in SENAITE or use existing?

- **Question:** CLAUDE.md §3 names four roles that should be able to edit QC
  criteria: Manager, QA Officer (QAO), Lab Director, and Owner.  Only `Manager`,
  `LabManager`, and `Owner` exist in standard SENAITE 2.6 core.  `QAO` and
  `LabDirector` do not exist and would silently never match the permission check
  until added.  Options: (a) use `LabManager` as the stand-in for QAO/Lab Director
  (accept the three built-in roles that cover these responsibilities); or (b) add
  custom roles `QAO` and `LabDirector` via a `rolemap.xml` in the add-on's
  GenericSetup profile and wire them as needed.  Which approach does the lab prefer?
- **Status:** open — current code admits `Manager`, `LabManager`, `Owner`, `QAO`,
  `LabDirector`; the last two are no-ops until defined
- **Raised:** 2026-06-11

---

## Q-005  cal_r2_min 0.995 vs 0.990 — which should be the lab standard?

- **Question:** The live engine currently uses `cal_r2_min = 0.995`.  The FDA
  32-PFAS method document specifies **0.990** as the acceptance criterion.  The
  seeded default deliberately matches the existing value (0.995) so that
  install does not change behaviour.  Once the Method Profile control panel is
  live, a manager must explicitly edit the FDA_32PFAS profile to 0.990 if the
  lab wants to align with the method specification.  Does the lab want to use
  0.990 (FDA specification) or retain 0.995 (more conservative)?  The answer
  should be documented in DECISIONS.md and set via the UI.
- **Status:** open — default preserved at 0.995; manager editable via `@@pfas-method-profile-edit`
- **Raised:** 2026-06-11

---

## Q-004  EPA 1633A per-analyte EIS/OPR limits — VERIFY

- **Question:** EPA 1633A Tables 6 and 8 carry authoritative per-analyte,
  per-matrix EIS recovery limits (some as low as 5%, some to 365% depending
  on matrix).  The defaults in `method_profile_store.py` use the common
  40–130% / 20–150% windows as placeholders.  Before using 1633A in
  production, every EIS override in the `eis_overrides` table must be
  verified against your purchased copy of the method.
- **Status:** open — flagged with `"verify_against_method": true` in defaults
- **Raised:** 2026-06-11

---

## Q-003  Rolling MDL from LFB spikes (StarLIMS approach)

- **Question:** User noted that StarLIMS includes low-level LFB spikes in the
  MDL assessment and builds it as a rolling calculation over time.  Should the
  PFAS LIMS support a "rolling MDL" mode where LFB results with the MDL
  designation are accumulated into the MDL calculation automatically?
  Currently the MDL calculation requires explicit input of replicate spike
  concentrations (minimum 7 replicates in one study).
- **Status:** open — deferred after Stage 1
- **Raised:** 2026-06-11

---

## Q-002  Colour-coding / grouping for Reference Definitions in SENAITE UI

- **Question:** SENAITE's Reference Definitions list can become confusing with
  11 QC type definitions for 3 methods.  User asked for colour-coding or
  grouping to avoid confusion.  SENAITE 2.6 native UI does not support
  per-definition colour badges.  Options: (a) prefix the definition title with
  the method code (e.g., "FDA | CCV — FDA 32-PFAS CCV"), (b) add a custom
  listing column/badge via the browser layer, (c) leave for Stage 2 UI work.
  Which approach does the lab prefer?
- **Status:** open
- **Raised:** 2026-06-11

---

## Q-001  Surrogate IS name normalisation (abbreviated vs. full names)

- **Question:** `pfas_pipeline/method_profiles.py` FDA_NATIVE_SURROGATE_MAP
  uses abbreviated surrogate names (e.g., "M3PFBA", "M8PFOA") while
  `pfas_pipeline/constants.py` INTERNAL_STANDARDS uses full names
  ("13C3-PFBA", "13C8-PFOA").  These must match what the instrument software
  exports for the IS response check to function correctly.  Which naming
  convention does the Waters MassLynx export use?  This determines which
  names to use in the Method Profile surrogate_map.
- **Status:** open — affects the surrogate_map defaults in FDA_32PFAS profile
- **Raised:** 2026-06-11
