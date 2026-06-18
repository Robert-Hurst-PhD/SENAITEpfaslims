# SESSION CONTEXT — senaite.pfas
# Keep this file updated at the end of every working session.
# Paste it into the conversation after any reboot/session loss.

Last updated: 2026-06-18

---

## What this project is

PFAS analytical laboratory LIMS — a Plone/SENAITE 2.6.0 add-on (`senaite.pfas`)
plus a Python 3 pipeline worker (`pfas_pipeline/`). Three methods: FDA 32-PFAS in
Food, EPA 537.1, EPA 1633A. All in-Plone code is Python 2.7. Worker is Python 3.

Running on Docker at `/home/robin/Downloads/senaite_pfas/`. See CLAUDE.md for
full architecture, constraints, and environment details. Read RESOURCE_MAP.md for
file index.

---

## Build rounds completed (git log)

| Commit  | Round | What was built |
|---------|-------|----------------|
| e2dd6e9 | 1–2   | Stage 1 de-hardcode QC; Stage 2 analyst status UI; QC rule toggle grid; control chart |
| 63930ae | 3     | Stage 3 tracking numbers, public client tracker, QR receipts |
| f0bd94d | 3-fix | Public tracker stage detection fix |
| 1bab697 | 3–8   | EGAD EDD exporter, reagents, logbooks, import studio, calibrations, REST bridge |
| 1bdf6b3 | 9     | Relational data model schema + data-driven QC rules |
| 5d927b2 | 9     | SESSION_CONTEXT.md + CLAUDE.md pointer |
| 37ced41 | 9 A+B | Phase A (remove duplicate lists) + Phase B (EIS structural fix) + uncommitted Round 9 UI |

---

## Round 9 — what commit 37ced41 did

### Phase A — Duplicate removal (DONE):
- `pfas_pipeline/constants.py`: removed `ANALYTES`, `INTERNAL_STANDARDS`,
  `NON_ISO_ANALYTES`, `ALL_COMPOUNDS`
- `pfas_pipeline/method_profiles.py`: added `_FDA_DISPLAY_ANALYTES`,
  `_FDA_IS_DISPLAY_NAMES` as defaults; added `get_analyte_list()`,
  `get_non_iso_set()`, `get_is_list()` helpers
- `pfas_pipeline/run_queue.py` + `pipeline.py`: use helpers; pass `non_iso_set`
  to `qual_quan_check()`
- `pfas_pipeline/qc_engine.py`: `qual_quan_check()` accepts optional `non_iso_set`
- `src/senaite/pfas/analytes.py`: removed flat `INTERNAL_STANDARDS` list
- `src/senaite/pfas/method_profile_store.py`: removed `_FDA_ANALYTE_ORDER` and
  `_CONFIRM_ION_MZ`; `_fda_per_analyte()` now iterates `NATIVE_ANALYTES` and
  reads confirm ion from `PFAS_ANALYTES`
- `pfas_pipeline/egad_edd.py`: removed `ANALYTE_CAS_DEFAULTS` dict

### Phase B — EIS overrides structural fix (DONE):
- `reload_from_profiles()` converts eis_overrides from store list format to dict
  so `EPA1633AProfile.qc_rules()` dict-access works after JSON round-trip

### Previously uncommitted Round 9 work now committed:
- `models.py`: `Batch.method_id` field added
- `method_profile_store.py`: `supported_matrices`, `master_analyte_set`,
  `analyte_matrix_inclusion`, `unit_map`, `spike_levels` in all 3 method profiles;
  `_FDA_BIG4`/`_FDA_NO_LABELED_STD` derived from `analyte_reference.py`
- `qc/rules.py`: removed `METHOD_MATRIX_UNIT_MAP` (owned by method profiles)
- `browser/method_profiles.py`: inclusion matrix + surrogate IS grid view helpers
- `browser/templates/method_profile_edit.pt`: full edit template with analyte×matrix
  checkbox grid, surrogate IS lane UI, EIS conditional tab, per-analyte recovery
  tiers table, spike levels, extraction stages
- `browser/egad_config.py` + `egad_config.pt`: EDD config tab fixes
- `browser/logbooks.py` + `logbook_*.pt` + `logbook_index.pt`: preview + parentage
- `seed_example_batch.py`: example batch with all 4 logbooks (Item 7)

---

## Round 9 — what is STILL PENDING

### Phase C — Wire get_included_analytes() to downstream consumers
- `pfas_pipeline/pipeline.py` `build_summary()` and `run_queue.py`
  `auto_evaluate()` still iterate `_FDA_DISPLAY_ANALYTES` (34 display names).
  They should call `get_included_analytes(portal, method_id, matrix)` for the
  batch's method × matrix panel — so excluded analytes (e.g. PFODA × Eggs)
  are omitted from the output automatically.
- `pfas_pipeline/egad_edd.py`: EDD generator should respect inclusion matrix
- Report generator: only report analytes in the panel
- Note: `master_analyte_set` in ZODB store uses KEYWORDS; pipeline's display-name
  lists use DISPLAY NAMES. Phase C needs COMPOUND_NAME_TO_KEYWORD translation.

### Phase D — Fix Decision C violations
- `pfas_pipeline/models.py`: `LFSMResult.passes` and `LFSMDResult.passes`
  still read from flat `CRITERIA` dict (recovery_min_pct, rpd_max_pct).
  These should be removed — nothing external calls them.

### Round 9 UI items (browser) — status after 37ced41:
- **Item 1 — Analyte×Matrix checkbox grid:** Template built, JS POST handler
  wired. **VERIFY** that saving the grid persists to ZODB correctly by testing
  in the running SENAITE instance.
- **Item 2 — Surrogate map drag-and-drop:** Lane UI built in template.
  **VERIFY** save/load round-trip.
- **Item 3 — Recovery tiers per-analyte table:** UI present. **VERIFY** it
  correctly shows per-analyte tiers and allows editing.
- **Item 4 — Matrix adjustment confirm:** Should be visible in template.
- **Item 5 — EIS overrides conditional:** `show_eis_overrides()` helper
  implemented; structural mismatch fixed (Phase B). **VERIFY** in UI.
- **Item 6 — EGAD dead config tabs + missing CAS:** `egad_config.pt` changed.
  **VERIFY** tabs now load correctly. PFUnDS/PFTrDS CAS still need inline
  editor — check if the EGAD config UI allows editing them now.
- **Item 7 — Logbooks preview + example batch:** `seed_example_batch.py`
  committed; logbook templates committed. **VERIFY** by running seed script
  against live SENAITE and checking the logbook UI.
- **Item 8 — Parentage end-to-end:** `Batch.method_id` fixed; `LFSMResult.passes`
  deferred. All profiled QC functions in `run_queue.py` wired correctly.

---

## Key design decisions (for continuity)

- **CAS map ownership:** per-analyte in `egad_store.DEFAULT_ANALYTE_CAS`
  (Round 7 Decision b). NOT per-method. The pipeline reads from the exported
  `analyte_cas.json` when available.
- **`master_analyte_set` format:** KEYWORDS in ZODB store; DISPLAY NAMES in
  pipeline `_FDA_DISPLAY_ANALYTES`. These differ for "4:2FTS"/"4:2 FTS",
  "PFHxS"/"lr-PFHxS" etc. Phase C will unify via `COMPOUND_NAME_TO_KEYWORD`.
- **`eis_overrides` format:** list-of-objects in ZODB store (UI-friendly);
  dict in pipeline cache (code-friendly). Phase B added normalization in
  `reload_from_profiles()`.
- **`_fda_per_analyte()` now derives from NATIVE_ANALYTES + PFAS_ANALYTES.**
  No more separate `_FDA_ANALYTE_ORDER` or `_CONFIRM_ION_MZ` dicts.
- **`qual_quan_check()` now accepts `non_iso_set` parameter** (default: lazy
  load from `get_non_iso_set()`). Callers should pass the method's set.

---

## Open questions from QUESTIONS.md

- Q-014: Spike level concentrations for LFB/LFSM all three methods — OPEN
- Q-007: MRM transitions for NEtFOSAA/NMeFOSAA/PFOA-lr-br isomers — OPEN
- Q-004: EPA 1633A per-analyte EIS/OPR limits — OPEN (verify against method)
- Q-003: Rolling MDL from LFB spikes — OPEN (deferred)
- Q-002: Color-coding for Reference Definitions in SENAITE UI — OPEN
- Q-001: Surrogate IS name normalisation (abbreviated vs full names) — OPEN

---

## Infrastructure

- Docker: `docker compose up -d` from `/home/robin/Downloads/senaite_pfas/`
  (if permission denied: `sudo chmod 666 /run/docker.sock` first)
- robin is NOT in docker group — always need socket fix after reboot
- SENAITE at http://localhost:8080/senaite (takes ~60s cold start)
- Cloudflare tunnel: not a service, must be started manually each time:
  `curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /tmp/cloudflared && chmod +x /tmp/cloudflared && /tmp/cloudflared tunnel --url http://localhost:80 --no-autoupdate &`
- Public URL changes on every restart (ephemeral)
- nginx VHM config: must use VirtualHostRoot/senaite/$1 order (see CLAUDE.md §7)

---

## Next build session — recommended order

1. **Verify in browser** that the Round 9 UI items all save/load correctly
   (start Docker stack, test each tab in method profile edit view)
2. **Phase C** — wire `get_included_analytes()` to build_summary, auto_evaluate,
   EDD exporter, and report generator (needs COMPOUND_NAME_TO_KEYWORD mapping)
3. **Phase D** — remove `LFSMResult.passes` / `LFSMDResult.passes` (Decision C)
4. **Item 6** — verify EGAD config tabs + test inline CAS editor for PFUnDS/PFTrDS
