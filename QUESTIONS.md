# QUESTIONS.md — open questions awaiting lab answer

---

## Q-010  Plan B — How does a dropped file get identified with an instrument + software version?

- **Question:** Round 8 Item 2 says the importer must "look up the saved Studio
  profile for the file's instrument + software version." But `run_pipeline()` today
  receives only a CSV file path — no instrument identity. For the REST bridge to
  work, the pipeline must know WHICH instrument's profile to fetch. Four options:
  1. **Filename/path convention** — e.g. `SCIEX-001_v1.2.3_batch001.csv`; pipeline
     parses instrument ID and version from the filename.
  2. **Sidecar file** — a `.json` or `.ini` dropped alongside the CSV containing
     `{"instrument_id": "SCIEX-001", "software_version": "1.2.3"}`.
  3. **CLI argument** — `--instrument SCIEX-001 --version 1.2.3` passed to the
     watcher/pipeline when it submits the file for processing.
  4. **Vendor-key only (no per-instrument)** — auto-detect vendor from CSV headers
     → look up portal-level vendor profile (sciex/agilent/waters/native). Sacrifices
     per-instrument differentiation: two SCIEX instruments can't have different profiles.
  The answer determines the store key, the bridge URL parameters, the connector
  signature, and the importer call site.
- **Status:** closed — decided: vendor-key only (auto-detect from CSV headers);
  lookup key is `"vendor_key:version"` (no instrument UID)
- **Raised:** 2026-06-16

---

## Q-011  Plan B — Does "refuse if no profile" fire at vendor-key level or instrument+version level?

- **Question:** Round 8 specifies: if no saved Import Studio profile exists for the
  file's instrument/version, the importer must refuse and tell the user to open
  Import Studio. Two interpretations:
  1. **Instrument+version level** — strict. Every instrument physical box + every
     software version must have an explicit saved profile in Import Studio before
     it can process. Seeding sciex/agilent/waters defaults in the portal does NOT
     satisfy this; a new instrument needs its own profile.
  2. **Vendor-key level** — relaxed. Portal-level defaults seeded for sciex, agilent,
     waters, native satisfy the check; refuse only fires for unknown/unmapped vendors.
     In practice this means the check almost never fires for the three known platforms.
  The strict version catches misconfigured instruments; the relaxed version means
  existing files "just work" after add-on install.
- **Status:** closed — decided: instrument+version strict. Seeded templates ≠ working
  profiles. Every new version file must go through Import Studio once.
- **Raised:** 2026-06-16

---

## Q-012  Plan B — Should the pipeline fall back to vendor_profiles.py if SENAITE is offline?

- **Question:** The pipeline is a separate Docker service. If SENAITE is down (restart,
  migration, etc.) and the pipeline receives a file, should it:
  1. **Fail fast** — refuse to process; "SENAITE unavailable, cannot fetch import
     profile". No fallback. Enforces single source of truth; matches Round 8 intent
     ("retire the hardcoded code path").
  2. **Fall back to vendor_profiles.py** — continue processing using the hardcoded
     SCIEX_OS/WATERS_MASSLYNX/AGILENT_MASSHUNTER maps. Keeps the pipeline
     operational during SENAITE downtime, but re-introduces the duplication Round 8
     exists to kill.
  Note: option 1 means any SENAITE outage also halts instrument file processing.
- **Status:** closed — decided: fail fast. No fallback. SENAITE downtime halts
  processing. vendor_profiles.py active code path retired (still present for
  `detect_vendor()` and standalone testing without a senaite connector).
- **Raised:** 2026-06-16

---

## Q-007  Item 5 — MRM transitions for additional linear/branched isomers

- **Question:** The lab confirmed (2026-06-13) that isomer summation should be
  extensible to cover NEtFOSAA, NMeFOSAA, PFOA, PFNA, FOSA and any other analytes
  with separate linear/branched peaks.  However, `analytes.py` only defines
  `lr-PFOS`, `br-PFOS`, `lr-PFHxS`, `br-PFHxS`.  Before adding the other analyte
  variants, provide the following for each new compound:
    - Compound name (exactly as it appears in the MassLynx export)
    - Quantifier MRM transition (precursor > product, negative ion mode)
    - Qualifier MRM transition(s) if any
    - Which method(s) it appears in (FDA_32PFAS / EPA_537_1 / EPA_1633A)
    - Which reported analyte it sums into (e.g., lr-NEtFOSAA + br-NEtFOSAA → NEtFOSAA)
  The two existing pairs (lr-PFOS+br-PFOS→PFOS, lr-PFHxS+br-PFHxS→PFHxS) are
  implemented.  The UI is already extensible — new pairs can be added via the
  isomer summation table in the Method Profile editor once the analyte definitions
  are confirmed.
- **Status:** open — blocked on lab MRM data
- **Raised:** 2026-06-13

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
