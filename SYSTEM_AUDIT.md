# senaite.pfas — Relational Wiring Audit

**Date:** 2026-07-01
**Scope:** Verify that variables/modules are properly connected along the §3
relational spine (Method → … → Sample Report), with no dead-ends or duplicated
facts. Audit is grounded in code reads, not assumptions. Companion artifact:
`system_diagram.png` (entity/data-flow spider diagram).

**Acceptance test (CLAUDE.md §0/§3):** *"a relational database that builds into
our final product of a sample report."* Verdict below.

---

## 1. Verdict

**The relational spine is intact and does build end-to-end into the EDD/report.**
The output path resolves to spine owners and the CAS-blocks-EDD gate exists.
Two genuine defects violate §1.3 "single source of truth," and there is one
disconnected module to resolve. None break the report today, but **D2 (CAS
duplication) is a live correctness risk** for the regulated output.

| # | Type | Item | Severity | Status |
|---|------|------|----------|--------|
| D1 | **Cross-runtime duplication** (re-diagnosed) | `qc/control_chart.py` is a **Python-3** Westgard engine (out-of-process worker, §7); the Py2.7 view reimplements the *same* rules because it **cannot import** it | Medium (DRY across runtimes, not a compliance gap) | Open — plan below |
| D6 | Exact duplicate vocab | `STANDARD_TYPES`, `REAGENT_CATEGORIES` copied in `browser/` and `content/` | Low | **RESOLVED 2026-07-01** |
| D7 | Duplicated method-ID list | Method identity list repeated across ~6 modules | Low–Medium | **PARTIAL 2026-07-01** (qc.rules now derives from master) |
| D2 | **Duplicate fact (SSOT)** | CAS was hardcoded in `egad_store` **and** `analyte_reference`; EDD used the egad copy | **High (regulated output could drift)** | **RESOLVED 2026-07-01** |
| D3 | Dead code | `ingest/data_importer.py` — worker has its own importer (`pfas_pipeline/importer.py`); nothing referenced it | — | **RESOLVED 2026-07-02** (deleted; §7 refusal enforced in live importer) |
| D4 | Loose coupling | Matrix identity referenced by string title across `supported_matrices` / `egad_sample_type`, not by SampleType UID | Low–Medium | Open |
| D5 | **Silent seeding bug** (found while fixing D2) | `setuphandlers` called non-existent `svc.setCASNumber()` in a silent `try/except`, which also blocked `setPrecision()` | Medium | **RESOLVED 2026-07-01** |

---

## 2. Storage anchors (the single-source-of-truth map)

Every fact should live in exactly one of these and be referenced elsewhere.

| Fact / entity | Owner (storage) | Kind |
|---|---|---|
| Analyte identity, CAS, IS link, key/no-labeled flags | `analyte_reference.NATIVE_ANALYTES` / `INTERNAL_STANDARDS` | Python constant (master) |
| MRM transitions / confirm ions | `analytes.PFAS_ANALYTES` | Python constant |
| Method profile (master set, matrix inclusion, surrogate map, tiers, qc_acceptance, eis_overrides, unit_map) | `senaite.pfas.method_profiles` → Dexterity `MethodProfile.profile_json`; mirrored to `/data/qc/method_profiles.json` | annotation/Dexterity + file |
| Method ↔ core Method/AnalysisService bridge | `senaite.pfas.method_associations` (`method_wizard`) | annotation |
| Reagent lots + CoA | `senaite.pfas.reagents`, `reagent.coa` | annotation |
| Prepared-standard **parent reagents** (3-level chain) | `senaite.pfas.prepstd.parent_reagents` | annotation |
| QC result sets | `qc.store` → `/data/qc/pfas_qc_results.db` | SQLite |
| QC rule toggles/limits | `senaite.pfas.qc.rules` | annotation |
| Facility QC readings | `/data/qc/facility_monitoring.db` | SQLite |
| Data-review 5-item checklist | `senaite.pfas.data_review.checklist` (per worksheet) | annotation |
| **AnalysisSpec sync (NEW)** | core `AnalysisSpec` objects + `senaite.pfas.spec_sync_audit` | core object + annotation |
| EGAD CAS/DEP map + EDD | `egad_store` (`analyte_cas_json`, `DEFAULT_ANALYTE_CAS`) | annotation + Python constant |

---

## 3. Spine — link-by-link verification

1. **Analyte master → Method profile** — `method_profile_store` imports
   `NATIVE_ANALYTES`, `INTERNAL_STANDARDS`, `get_surrogate_map_by_name` from
   `analyte_reference` (references, does not re-list). ✔ `spec_sync` also imports
   `NATIVE_ANALYTES` (single source). ✔
2. **Method profile = the config hub** — imported 20× (highest). Owns
   `master_analyte_set`, `analyte_matrix_inclusion`, `surrogate_map`,
   `qc_acceptance`, `eis_overrides`, `unit_map`. ✔
3. **Method profile → core AnalysisSpec (NEW bridge)** —
   `save_profile()` → `spec_sync.sync_analysis_specs()` → core `AnalysisSpec` +
   native snapshot + `spec_sync_audit`. Verified live earlier. ✔
4. **Method ↔ core Method** — `method_wizard` writes `method_associations`
   (profile ↔ core Method/AnalysisService). ✔ (distinct from batch.Method — not
   a duplicate)
5. **3-level traceability (§6 INPUT)** — reagent lot → prepared standard →
   result: `prepared_standards.py:171` **writes** `parent_reagents`;
   `data_review.py:504` **reads** it for the traceability check. ✔ Chain closed.
6. **QC engine** — `qc.rules` (16×) + `qc.store` → `pfas_qc_results.db`;
   the control-chart **view** reads that DB and computes limits/Westgard. ✔
   (but see D1)
7. **Output → report/EDD** — `egad_builder.generate_from_batch()` reads results
   + `get_analyte_cas(portal)` and emits CAS_NO/PARAMETER_NAME/CONCENTRATION
   rows. ✔
8. **CAS-blocks-EDD gate (§3)** — `egad_builder` flags `CAS_NO == PLACEHOLDER`
   and empty CAS as errors; `egad_config.blocking_cas_count()` surfaces the
   block. ✔ Requirement MET.

---

## 4. Defects (detail)

### D2 — CAS duplicated across sources  *(High)* — **RESOLVED**
Investigation found **four** CAS representations, and — importantly — that
**SENAITE 2.6 core `AnalysisService` has no CAS field at all**, so CAS legitimately
lives in the add-on, keyed by the core service *keyword* (that keyword is the
join to core). A three-way diff (normalized) showed the active copies agreed on
29/34 analytes; the 5 exceptions are 4 Maine-DEP-code isomers (legitimate EGAD
overrides) + `PFTrDS` (a real drift: `analyte_reference` = `PLACEHOLDER`).

**Fix applied:**
- `analyte_reference.get_cas_by_keyword(dashed=False)` — new **single-source**
  CAS accessor (the master owns CAS).
- `egad_store.DEFAULT_ANALYTE_CAS` is now **built** from `_EGAD_ANALYTE_OVERLAY`
  (parameter names, notes, and `cas_override` only for the 5 DEP/placeholder
  cases) layered over the master. The 29 duplicated CAS numbers were removed.
- Docstring corrected (no longer claims to be "the authoritative source").
- **Verified output-safe:** rebuilt `DEFAULT_ANALYTE_CAS` is byte-identical to
  the old hardcoded dict (34/34, 0 mismatches) and live `get_analyte_cas()`
  output is unchanged (3038 bytes, dict-equal). Regulated EDD provably unchanged.

### D5 — Silent CAS-seeding bug  *(Medium)* — **RESOLVED**
`setuphandlers.py` seeded services inside `try: … setCASNumber(...) … except: pass`.
Because core has no `setCASNumber`, that line threw `AttributeError` every run —
silently — and **also prevented `setPrecision()` from running** (it followed on
the next line). Removed the dead CAS call; precision now seeds, and a comment
documents that analyte CAS is owned in the add-on keyed by keyword.

### D1 — Westgard rules duplicated across runtimes  *(Medium)* — re-diagnosed
Deeper analysis corrected the original "dead code" reading:
- `qc/control_chart.py` uses `from typing import …`, `@dataclass`, and PEP-484
  annotations — it is **Python 3**. The Py2.7 Plone process gets a `SyntaxError`
  importing it (verified). It belongs to the **out-of-process Py3 pipeline
  worker** (§7), not the in-Plone add-on.
- The view `browser/controlchart.py` (Py2.7) reimplements the rules because it
  **cannot** import the Py3 engine. The two are **equivalent** — same 6 Westgard
  rules (1-3S, 1-2S, 2-2S, R-4S, 4-1S, 10X) and the **same** limit formula
  (sample `n-1` stdev on the baseline, identical zero-SD fallback). So this is
  **not a compliance gap** and **not** fixable by "wiring it in" (impossible
  across runtimes).
- It is a genuine §7 smell ("no logic duplicated across the two [processes]").
  **Recommended fix (bounded, not yet applied):** extract the 6 rule thresholds
  + baseline-N into a tiny **Py2/3-compatible constants module** that both the
  view and the engine import — single-sourcing the numbers without crossing the
  runtime boundary. Requires the same byte-identical chart-output verification
  used for CAS before landing on the regulated chart path.

---

## 6. Connectivity work applied this pass (2026-07-01)

All verified output-safe with the CAS byte-identical pattern (snapshot → change
→ prove identical).

- **CAS single-source (D2)** + silent-seeding fix (D5) — see §4/§5.
- **`STANDARD_TYPES` / `REAGENT_CATEGORIES` (D6)** — the `content/` type now owns
  each vocabulary; `browser/` imports it. Verified the browser name **is** the
  content object (identity), pages load.
- **Method-ID list (D7, partial)** — new `analyte_reference.get_method_ids()` is
  the single source for "which methods exist." `qc.rules.METHODS` now derives
  from it (short labels kept local as presentation). Verified byte-identical to
  the old hardcoded list; qcrules page loads. *Remaining copies to route through
  the master next: `qc_grid.GRID_METHODS`, `sop_documents.METHOD_LABELS`,
  `egad_store.DEFAULT_METHOD_EGAD`, `method_profile_store.DEFAULT_PROFILES` keys.*

### D4 — Matrix identity by string → SampleType UID  *(foundation delivered; migration staged)*
Matrices are referenced by **title string** (`"Eggs"`, `"Meat / Muscle"`) in
`profile.supported_matrices`, `analyte_matrix_inclusion`, and `egad_sample_type`
— not by core `SampleType` UID. Rename orphans them (§3 rule 4). This is a
data-model change touching stored profiles + the regulated pipeline, so it is
**staged** per §8:

1. **✅ DONE — resolver `matrix_ref.py`** (`resolve` / `title_to_uid` /
   `uid_to_title` / `all_matrices` / `find_profiles_referencing`). Additive,
   backward-compatible (accepts title *or* UID, never raises on a miss).
   Verified against the live instance: resolves "Eggs" → SampleType UID and
   back, lists all 16 core SampleTypes, and `find_profiles_referencing("Eggs")`
   correctly reports `FDA_32PFAS` (the §3 rule-4 rename check). Nothing else
   consumes it yet, so zero risk to existing flows.
2. **✅ DONE — Write path.** `save_profile` now persists a `matrix_uid_map`
   (`{title: SampleType UID}`) on every save; `supported_matrices` stays a list
   of titles (additive, non-breaking). Verified: FDA_32PFAS saves 6 matrix→UID
   entries; real UI save returns 200.
3. **✅ DONE (first consumer) — Read path.** `get_included_analytes` (the §3
   Method×Matrix key relation) now resolves its `matrix` arg (title **or**
   SampleType UID) through `matrix_ref`. Verified **byte-identical** to the old
   logic for title inputs across 3 matrices, and UID inputs now return the same
   result. Remaining consumers (surrogate map, recovery tiers, EGAD unit
   selection) can adopt the same one-line resolve incrementally.
4. **✅ DONE — Backfill migration.** `migrations/backfill_matrix_uid_map.py`
   resolves every profile's `supported_matrices` titles → SampleType UIDs and
   writes `matrix_uid_map`. Idempotent; reports unresolved titles (never
   guesses); persists directly (no `spec_sync`/export side effects). Run result:
   EPA_1633A 9/9, EPA_537_1 3/3, FDA_32PFAS 6/6, **0 unresolved**; second run =
   all "already current". "Aquatic Tissue" resolves to the *same* SampleType UID
   under both EPA_1633A and FDA — confirming the shared core reference.
5. **✅ Referential integrity available now:** `matrix_ref.find_profiles_referencing`
   surfaces profiles that reference a SampleType — wire it into the SampleType
   rename/delete workflow next (§3 rule 4).
6. **Verify:** snapshot the reportable Method×Matrix panel + EDD sample-type
   codes before/after; prove identical. EGAD `egad_sample_type` keeps its DEP
   code but keys on UID.

*Effort: medium; isolated behind the resolver so it can land incrementally.*

### D1 — decision: left as documented (not refactored)
Reading the view confirmed the Westgard thresholds (3.0/2.0/1.0/4.0, baseline
N=20, min 5) are **identical** to the engine's and are **fixed by the Westgard
methodology** — they do not vary per lab. Rewiring the regulated chart view in
~15 places to share a constants module yields no functional benefit for real
risk, so per §8 it is intentionally **not** done; the accurate cross-runtime
diagnosis above stands. Revisit only if the rule set is ever made configurable.

### D3 — `ingest/data_importer.py` has no in-tree caller  *(Verify)*
- 593 lines, not imported, no `__main__`, not an `entry_point`
  (setup.py only declares `z3c.autoinclude`).
- Per §7 the pipeline worker is out-of-process (Py3, via `senaite.jsonapi`), so
  this may be driven by the **external worker repo**. **Action:** confirm the
  worker invokes it; if not, it is dead code.

### D4 — Matrix identity coupled by string, not UID  *(Low–Medium)*
- `supported_matrices` (profile) and `egad_sample_type` reference matrices by
  **title string** ("Eggs", "Meat / Muscle"), while the canonical entity is the
  core `SampleType` object. String matching risks orphaning on rename (§3
  referential-integrity rule 4). **Note**, not a hard duplicate.
- Honesty note: the spec_sync work (this session) created new `SampleType`
  objects for QC specs ("… LFSM"). These are QC-control types, a different axis
  from analytical matrices, but they add to SampleType proliferation — worth a
  future consolidation review.

---

## 5. Cleared (not defects)
- CAS hardcoded **only** in `analyte_reference` (+ the EGAD dup above) — no third
  copy.
- `content.*` types (`envreading`, `prepared_standard`, `prep_logbook_def`) —
  registered in `content.zcml`. Not orphans.
- Views (`lims_setup`, `stage_estimates`, etc.) — wired via ZCML / used by
  `tracker.py`. Not orphans.
- `migrations/*` — one-shot scripts (run by setuphandlers / manually). Expected.
