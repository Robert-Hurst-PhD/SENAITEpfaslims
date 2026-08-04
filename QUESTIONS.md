# QUESTIONS.md — open questions awaiting lab answer

---

## Q-014  Spike level concentrations (LFB and LFSM) — per matrix, all three methods

- **Question:** The Method Profile `spike_levels` section is now per-matrix
  (each matrix in the method has its own LFB/LFSM concentration table). The
  lab confirmed spike concentrations vary by matrix when backcalculating to
  sample size. The UI shows one section per matrix (from the method's
  `supported_matrices`), each with LFB and LFSM sub-tables for Low/Mid/High.
  - What are the spike concentrations (ppt) for each level × matrix combination?
    - FDA 32-PFAS: Aquatic Tissue, Meat / Muscle, Eggs, Fish / Seafood, Milk, Animal Feed
    - EPA 537.1: Drinking Water, Groundwater, Surface Water
    - EPA 1633A: Groundwater, Drinking Water, Surface Water, Wastewater, Landfill Leachate, Sediment, Soil, Aquatic Tissue, Biosolid
  - Once answered, enter via Method Profile UI → Spike Levels section.
- **Status:** open — spike concentrations must be entered by the lab. UI is ready.
- **Raised:** 2026-06-18 / restructured to per-matrix 2026-06-19 / 1633A matrices corrected 2026-06-19

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
- **Superseded in part — 2026-08-03.** "Flat CRITERIA values remain for
  `LFSMResult.passes`" is no longer true, and the reasoning is worth keeping:
  a flat fallback beside a profile-driven path is the shape that produced the
  CCV defect. An unconfigured criterion now raises `UnconfiguredCriterion`
  rather than falling back to a plausible number, and the legacy
  `recovery_tiers` branch — a second, divergent copy of the tier logic — was
  deleted. See `docs/ISO17025_DESIGN.md` §3.
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

## Q-007  MRM transitions for linear/branched isomers — export compound names

- **Confirmed pairs:** PFOA, PFNA, PFOS, PFHxS (FDA + 537.1 + 1633A), plus NEtFOSAA
  and NMeFOSAA (1633A only). All six pairs are now wired in `isomer_summation` in
  each method profile.
- **MRM transitions from EPA 1633A Table 10** (verified 2026-06-19, negative ESI):
  - PFOS branched/linear isomers: 499→80 (quant), 499→99 (qual), ratio 2.3
  - PFHxS branched/linear: 399→80 (quant), 399→99 (qual), ratio 1.9
  - PFOA branched/linear: 413→369 (quant), 413→169 (qual), ratio 3.0
  - PFNA branched/linear: 463→419 (quant), 463→219 (qual), ratio 4.9
  - NMeFOSAA branched/linear: 570→419 (quant), 570→483 (qual), ratio 2.0
  - NEtFOSAA branched/linear: 584→419 (quant), 584→526 (qual), ratio 1.2
  (Same MRM transition for lr- and br- peaks; they differ by chromatographic RT only.)
- **Still needed:** The EXACT compound names as MassLynx exports them for the lr-/br-
  peaks (e.g. "lr-PFOS" vs "Linear-PFOS" vs "PFOS-Linear"). The pipeline matches on
  `compounds.get("lr-PFOS")` — if MassLynx uses a different spelling, recovery checks
  will silently miss the peak.
- **Status:** open — MRM values confirmed from EPA method; blocked on lab MassLynx export names.
- **Raised:** 2026-06-13 / updated 2026-06-19

---

## Q-006  QAO and Lab Director roles — define in SENAITE or use existing?

- **Status:** closed — LabManager covers QAO and Lab Director (2026-06-18). QAO and LabDirector removed from all `_ALLOWED_ROLES` sets in `method_profiles.py`, `egad_config.py`, `logbooks.py`.
- **Raised:** 2026-06-11

---

## Q-005  cal_r2_min — per-method value

- **Status:** closed — confirmed per-method (2026-06-18). Already implemented: each method profile has its own `cal_r2_min` field, editable via the Method Profile UI. No global default. The lab sets each method's value through the UI.
- **Raised:** 2026-06-11

---

## Q-004  EPA 1633A EIS/OPR limits — implemented from official PDF

- **Source:** EPA 1633A, December 2024 (EPA 820-R-24-007), Tables 6 and 8.
  Fetched from EPA website 2026-06-18.
- **Implemented (2026-06-19):**
  - `eis_overrides` in `method_profile_store.py` now contains all 24 EIS compounds
    with actual Table 6 aqueous limits (not placeholders). Ranges match the method
    exactly, including low-recovery compounds (¹³C₄-PFBA 5–130%, ¹³C₇-PFUnA 30–130%,
    FTS compounds up to 300%).
  - `eis_matrix_overrides` dict added with per-matrix-class limits for leachate,
    solid, tissue, and biosolid (Tables 6 col 2 and Table 8 cols 1–3).
  - Pipeline `EPA1633AProfile.qc_rules()` now selects EIS limits by matrix class
    derived from the batch matrix name at runtime.
  - `verify_against_method` flag removed (data is now verified from the official PDF).
- **Status:** closed — EIS limits implemented from EPA 820-R-24-007.
- **Raised:** 2026-06-11 / closed 2026-06-19

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

- **Confirmed (2026-06-19):** Waters MassLynx exports compound names using
  the **13C prefix format** (e.g. `13C8-PFOS`, `13C3-PFBA`, `13C4-PFOA`).
  The M-prefix keywords (M8PFOS, M3PFBA, M4PFOA) are internal SENAITE
  keywords only and are never seen in MassLynx output.
  The pipeline's `get_is_list()` already returns `_FDA_IS_DISPLAY_NAMES`
  which uses 13C names — correct as-is.
  The `internal_standards.csv` has `Keyword=M-prefix, Title=13C-name`; the
  pipeline uses the Title column for all IS compound lookups.
  The surrogate_map in the Method Profile UI should store 13C display names
  (e.g. `13C8-PFOS`) as the surrogate_is field values.
- **Status:** closed — 2026-06-19
- **Raised:** 2026-06-11
- **REOPENED AND RE-CLOSED — 2026-08-03.** The 2026-06-19 resolution was
  correct about the instrument and wrong about the system. It concluded "the
  pipeline uses the Title column, correct as-is" and recommended that the
  surrogate map store 13C display names. In practice the Method Profile stores
  the **M-prefix keywords** (`M8PFOA`, `M8PFOS`), the instrument exports the
  **13C names**, and `COMPOUND_NAME_TO_KEYWORD` was built by walking only
  `NATIVE_ANALYTES` — so **nothing in the system could tell that `M8PFOA` and
  `13C8-PFOA` are the same compound.** Both spellings had been sitting in
  `INTERNAL_STANDARDS` the whole time, unused.

  This is why the question mattered more than it looked: as long as the
  surrogate map was decorative (nothing read it), the ambiguity was harmless.
  The moment the method profile became authoritative for the surrogate → IS
  link, a raw name comparison reported **all 20 surrogates as disagreements**.

  Resolution: neither spelling is canonical at the boundary. Both are keyed,
  and every comparison normalises through `analyte_alias.keyword_for()` first.
  A resolution that depends on everyone agreeing to use one spelling is not a
  resolution — it is an assumption with no enforcement.
  See `docs/ISO17025_DESIGN.md` §5.
