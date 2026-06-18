# QUESTIONS.md — open questions awaiting lab answer

---

## Q-014  Spike level concentrations (LFB and LFSM) — all three methods

- **Question:** The Method Profile now has a `spike_levels` section for LFB and
  LFSM injections (editable via the Method Profile UI in Site Setup). The
  pipeline resolves spike concentrations from this profile using the level label
  encoded in the injection name (e.g. `"; LFSM High"` → looks up `"High"` →
  returns the configured ppt). Until these values are entered, LFSM/LFSMD checks
  remain PENDING rather than auto-evaluated.
  - What are the available spike levels and their concentrations (ppt) for:
    - FDA 32-PFAS LFB / LFSM?
    - EPA 537.1 LFB / LFSM (ng/L)?
    - EPA 1633A LFB / LFSM (units per matrix)?
  - Typical format: Low / Mid / High with one concentration per label.
  - Once answered, enter via Method Profile UI → `spike_levels` field. No code
    change needed.
- **Status:** open — spike amounts must come from the lab's SOP / method validation.
- **Raised:** 2026-06-18

## Q-013  FDA_32PFAS Milk unit — ng/kg or ng/mL?

- **Status:** closed — ng/mL confirmed (2026-06-18). Seed updated. Unit is per-matrix and editable in the Method Profile UI.

## Q-011  Item 8 deferred — wire recovery_min/max and rpd_max from profile JSON?

- **Status:** closed (2026-06-18). Per-analyte tiered limits confirmed by lab.
  Implementation: `auto_evaluate()` in `run_queue.py` now calls
  `recovery_check_profiled()` / `rpd_check_profiled()` for every LFSM/LFSMD
  injection. Spike concentration resolved from method profile `spike_levels`
  (level label in injection name → ppt). `lfsm_check`/`lfsmd_check` remain as
  dead code; flat CRITERIA values remain for `LFSMResult.passes` only.
  False AUTO_PASS bug (LFSM always passing silently) also fixed: checks stay
  PENDING until spike levels are configured in the profile.
- **Raised:** 2026-06-18 during Item 8 parentage audit.

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

## Q-007  MRM transitions for additional linear/branched isomers

- **Confirmed pairs (2026-06-18):** NEtFOSAA (lr+br→NEtFOSAA), NMeFOSAA (lr+br→NMeFOSAA), PFOA (lr+br→PFOA), PFNA (lr+br→PFNA).
- **Still needed per pair** before implementation: compound name EXACTLY as MassLynx exports it, quantifier MRM transition (precursor > product, negative mode), qualifier MRM(s) if any, which method(s).
- **Status:** open — confirmed analyte list; blocked on lab MRM data.
- **Raised:** 2026-06-13

---

## Q-006  QAO and Lab Director roles — define in SENAITE or use existing?

- **Status:** closed — LabManager covers QAO and Lab Director (2026-06-18). QAO and LabDirector removed from all `_ALLOWED_ROLES` sets in `method_profiles.py`, `egad_config.py`, `logbooks.py`.
- **Raised:** 2026-06-11

---

## Q-005  cal_r2_min — per-method value

- **Status:** closed — confirmed per-method (2026-06-18). Already implemented: each method profile has its own `cal_r2_min` field, editable via the Method Profile UI. No global default. The lab sets each method's value through the UI.
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
