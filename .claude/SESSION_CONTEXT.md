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

| Commit | Round | What was built |
|--------|-------|----------------|
| e2dd6e9 | 1–2 | Stage 1 de-hardcode QC; Stage 2 analyst status UI; QC rule toggle grid; control chart |
| 63930ae | 3 | Stage 3 tracking numbers, public client tracker, QR receipts |
| f0bd94d | 3-fix | Public tracker stage detection fix |
| 1bab697 | 3–8 | EGAD EDD exporter, reagents, logbooks, import studio, calibrations, REST bridge |
| 1bdf6b3 | 9 | Relational data model schema + data-driven QC rules (see below) |

---

## Round 9 — what the commit actually did vs what is still pending

### DONE in commit 1bdf6b3:
- `analyte_reference.py` is the single source of truth for analyte identity:
  keyword, name, CAS, full_name, class, chain, surrogate_is, no_labeled,
  is_key_analyte (9-field tuple per analyte)
- `analytes.py`: removed dead QCCriteria class; KEY_ANALYTES and NON_ISO_ANALYTES
  now derived from analyte_reference.py (not re-declared)
- `method_profile_store.py`: added `supported_matrices`, `master_analyte_set`,
  `analyte_matrix_inclusion` (the checkbox grid), `unit_map`, `spike_levels`,
  `extraction_stages` to all three method profiles. PFODA × Eggs = False seeded.
  `get_included_analytes(portal, method_id, matrix)` implemented.
  `_FDA_BIG4`, `_FDA_NO_LABELED_STD` derived from analyte_reference.py.
  `_fda_per_analyte()` seeds the per_analyte table from analyte_reference.py.
- `method_profiles.py` (pipeline): Decision C — all QC rule logic reads from
  `_profile_data_cache` loaded from JSON. Module-level constants `_FDA_BIG4`,
  `_FDA_NO_LABELED_STD`, `_FDA_TIGHT_MATRICES` removed. `_DEFAULT_PROFILE_CACHE`
  has full recovery_tier, ccv, calibration, confirmation, is, duplicate data for
  all three methods. `reload_from_profiles()` loads JSON at batch start.
- `CLAUDE.md` §9 added (the relational data model section).
- `pipeline.py`: `Batch.method_id` now stored (parentage gap fixed).
- All regression tests pass.

### PENDING from Round 9 (not yet built):

**Item 1 — Method × Matrix Analyte Inclusion Matrix UI:**
- The data model (analyte_matrix_inclusion) EXISTS in method_profile_store.py
- The query function (get_included_analytes) EXISTS
- **Missing:** checkbox grid UI in method_profile_edit.pt — the manager has no
  way to view or edit the inclusion matrix through the browser
- **Missing:** downstream tools don't call get_included_analytes() yet — they
  still use flat global analyte lists

**Item 2 — Surrogate Map drag-and-drop:**
- Data lives in DEFAULT_PROFILES["FDA_32PFAS"]["surrogate_map"] (list of
  {analyte, surrogate_is} dicts)
- **Missing:** drag-and-drop UI — currently JSON/array text entry only
- Must use get_included_analytes() to populate native analyte list (left column)
  and method's IS set to populate the IS list (right column)

**Item 3 — Recovery Tiers per analyte, matrix-conditional (FDA):**
- Data EXISTS in method_profile_store.py recovery_tiers (tier 1/2/3 with
  key_analytes, tight_matrices, no_std_analytes lists)
- Pipeline reads from _DEFAULT_PROFILE_CACHE correctly
- **Missing:** per-analyte table view in the UI (method_profile_edit.pt)
  showing each analyte's assigned tier, with ability to edit

**Item 4 — Matrix Adjustment (confirm one-per-method):**
- matrix_factors list exists in method_profile_store.py — confirmed correct
- **Missing:** Just needs confirmation it's visible in the UI (it was already
  there in method_profile_edit.pt). Low priority.

**Item 5 — EIS Recovery Overrides (EPA 1633A only):**
- Data EXISTS in DEFAULT_PROFILES["EPA_1633A"]["eis_overrides"] as list of
  {analyte, recovery_min, recovery_max}
- **STRUCTURAL MISMATCH:** method_profiles.py _DEFAULT_PROFILE_CACHE stores
  eis_overrides as a DICT {analyte: {recovery_min, recovery_max}}; the store
  uses a LIST of objects — these will break on JSON round-trip if not aligned
- **Missing:** method-conditional display in UI (hide EIS tab for FDA/537.1)

**Item 6 — EGAD EDD dead config tabs + missing CAS codes:**
- The main EGAD EDD config TABS don't populate when clicked (dead tab bug)
- Two analytes block EDD export: PFUnDS (CAS not in EGAD CAS_LUP) and
  PFTrDS (CAS = PLACEHOLDER)
- **Missing:** root cause fix for dead tabs; inline editor for missing CAS

**Item 7 — Logbooks preview + parentage + example batch:**
- Logbooks exist (FM-ENV-250/251/252/253) stored as ZODB annotations on Batch
- **Missing:** live preview when configuring columns
- **Missing:** example batch for playing with the extraction logbook
- **Missing:** on-screen explanation of how stages → logbook instance

**Item 8 — Parentage end-to-end:**
- Batch.method_id gap was fixed in commit 1bdf6b3 ✓
- **Remaining gap:** LFSMResult.passes / LFSMDResult.passes in models.py still
  use flat CRITERIA dict (Decision C violation) — proposed: delete these
  convenience properties, nothing external calls them

---

## Remaining duplications identified in schema audit (2026-06-18)

These are the outstanding duplicate-removal tasks approved in schema audit:

1. `pfas_pipeline/constants.py`: still has `ANALYTES` list (34 display names),
   `INTERNAL_STANDARDS` list (21 flat names), `NON_ISO_ANALYTES` frozenset —
   should be removed; pipeline reads analyte set from method profile JSON
2. `src/senaite/pfas/analytes.py`: still has `INTERNAL_STANDARDS` flat name list
   (not derived from analyte_reference.py) — remove
3. `method_profile_store.py` `_FDA_ANALYTE_ORDER` (34 display names) — still
   present; should use master_analyte_set from the profile instead
4. `pfas_pipeline/egad_edd.py` `ANALYTE_CAS_DEFAULTS` — duplicate of
   egad_store.py DEFAULT_ANALYTE_CAS; remove from egad_edd.py
5. `method_profile_store.py` `_CONFIRM_ION_MZ` dict — partial duplicate of
   analytes.py PFAS_ANALYTES qual_mrm_list; remove, seed from analytes.py

---

## Open design question (needs lab answer before building)

**CAS map ownership conflict:**
- CLAUDE.md §9 says CAS MAP is owned by the method
- Round 7 Decision (b) says CAS_NO stored per-analyte (not per-method)
- Current implementation: egad_store.DEFAULT_ANALYTE_CAS owns it per-analyte
- Claude's proposed resolution: KEEP per-analyte in egad_store.py (Round 7 wins)
- **Needs explicit confirmation from lab before implementing**

---

## Open questions from QUESTIONS.md

- Q-014: Spike level concentrations for LFB/LFSM all three methods — OPEN
- Q-007: MRM transitions for NEtFOSAA/NMeFOSAA/PFOA-lr-br isomers — OPEN
- Q-004: EPA 1633A per-analyte EIS/OPR limits — OPEN (verify against method)
- Q-003: Rolling MDL from LFB spikes — OPEN (deferred)
- Q-002: Color-coding for Reference Definitions in SENAITE UI — OPEN
- Q-001: Surrogate IS name normalisation (abbreviated vs full names) — OPEN

---

## What was pending at session end (2026-06-18)

The schema audit was just presented to the lab for sign-off. Lab needs to answer:
1. Approve the 4-phase consolidation plan (Phases A-D above)?
2. CAS map ownership: keep per-analyte in egad_store.py (Claude's proposal)?
3. Build order preference: Phase A (duplicate removal) first, or jump straight
   to the Round 9 UI items (inclusion matrix UI, drag-drop surrogate map)?

Claude has NOT started any Round 9 UI implementation yet — waiting for sign-off.

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
