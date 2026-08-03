# DECISIONS.md — senaite.pfas design decisions

Append an entry every time a design decision is confirmed.  Keep entries
in reverse-chronological order (newest first).

---

## 2026-06-22 — Calibration page redesign

**Status:** Confirmed

**D22 — Calibration page uses per-analyte card layout with 3 stacked Chart.js plots.**
Each run date produces a section with one card per analyte. Cards contain:
- Plot 1: Response ratio (Y) vs expected concentration (X) + regression line; falls back
  to calculated vs expected when response_ratio is not yet stored (pre-migration batches).
- Plot 2: % deviation per calibration level (bar chart, ±acceptance lines).
- Plot 3: ICV/CCV/CCB instrument check values overlaid on calibration curve axis —
  shows where check standards fall relative to the fit line.

**D23 — Fit type overrides stored to SQLite `calibrations` table.**
Reviewer changes (fit_type_override, weight_override, origin_override) written back to
`calibrations` row via AJAX POST (action=override). Stored alongside original pipeline values.
Original values preserved; override is additive, not destructive. Future pipeline re-import
of the same batch can use stored override. Approved_by + approved_at set on run-level approve.

**D24 — Run-level approval: one Approve button per run date group, all analytes together.**
Confirmed design (user confirmed "approval should be dependent on the calibration as a whole
for all of the analyte not on a by analyte basis"). Stores approved_by + approved_at on all
calibration rows for that run_date.

**D25 — response_ratio stored per calibration level and per QC result.**
New columns added via `_MIGRATION_STMTS` (idempotent ALTER TABLE):
- `calibration_levels.response_ratio REAL`
- `qc_results.expected_value REAL`
- `qc_results.response_ratio REAL`
Pipeline importer should populate response_ratio from InstrumentRow.response_ratio
and expected_value from InstrumentRow.expected_conc when writing QC check results.
Existing rows without response_ratio fall back to calculated concentration on Plot 1.

**D26 — Three calibration plots per analyte card (user clarification).**
1. Response vs expected concentration (the actual calibration curve + regression fit).
2. % deviation of all calibration levels from expected (bar chart).
3. Instrument checks (ICV/CCV/CCB) overlaid on calibration curve axes to show tracking.
Concentration units used throughout (not raw responses where avoidable), per user preference.

---

## 2026-06-22 — Audit log integration across all modules

**Status:** Confirmed

**D13 — Fire `notify(ObjectModifiedEvent(obj))` after every Dexterity content save.**
SENAITE's auditlog subscriber for Dexterity listens for `IObjectModifiedEvent`; our CRUD views were
calling `reindexObject()` without firing this event so edits were invisible to the audit log.
Fix applied to `reagents.py` (`_save_reagent`), `prepared_standards.py` (`_save`),
`prep_logbooks.py` (`_save` and `_archive_slug`). Verified: edit produces a second snapshot with
`action=edit` and correct field values. Import: `zope.lifecycleevent.ObjectModifiedEvent` (available in this env).
Note: the initial `IObjectAddedEvent` snapshot captures near-empty fields (fires before `_populate_obj`);
the subsequent `IObjectModifiedEvent` captures the real data.

**D14 — Logbook execution data (IAnnotations on Batch): force `take_snapshot(batch)` on each save (B1).**
Logbook rows are JSON blobs in `IAnnotations(batch)` — invisible to `SuperModel.to_dict()`.
Converting entries to Dexterity content is disproportionate (B2). Instead, call `take_snapshot(batch)`
from `bika.lims.api.snapshot` after every `_save_logbook()` call. Records who touched the batch's logbook
data and when; the diff shows Batch schema fields, not row diffs. Accepted as sufficient — the
PrepLogbookDef audit already shows which template was in use.

**D15 — PrepLogbookDefs: existing draft/active/archived versioning IS the audit trail (C2). No soft-delete.**
PrepLogbookDefs already use a slug+revision model where archiving a revision is permanent and revision
history is browsable. This is richer than the reagent soft-delete pattern and is the right model for
documents and procedures. Hard delete is structurally prevented by the version model.

**D16 — Method profiles (portal annotation store): pending decision.**
Method profiles live in `IAnnotations(portal)["senaite.pfas.method_profiles"]` — no content object, so
SENAITE cannot snapshot them. Options: A1 (convert to Dexterity content) or A2 (internal version history
list in annotation store). Deferred — to be decided before the Method & Analyte Setup workspace is built.

---

## 2026-06-22 — Archive system + production mode gate (reagent inventory)

**Status:** Confirmed

**D8 — Production mode = SENAITE global audit log (`getEnableGlobalAuditlog()`), not a parallel flag.**
User said "make that dependent on the global auditing being toggled on." Confirmed that `senaite.core 2.6.0`
has a real `bika_setup.getEnableGlobalAuditlog()` field. Gate is read from this; not duplicated.

**D9 — Soft-delete via IAnnotations (`senaite.pfas.reagent.archived`) when in production mode; hard delete in test mode.**
`_ANN_ARCHIVED_KEY` stores `{archived_by, archived_at}` JSON. `_restore_reagent()` deletes the annotation.
Archived rows hidden by default; "Show Archived" toggle reveals them in the toolbar (production mode only).

**D10 — Test reagents identified by creation timestamp vs. `production_since`.**
First request where `getEnableGlobalAuditlog()` is True stamps `production_since` in
`IAnnotations(portal)["senaite.pfas.lab_settings"]`. Any reagent with `obj.created() < production_since`
is "test." This correctly identifies ALL pre-production reagents without needing per-reagent annotation.

**D11 — Test reagent purge is manual (UI button), not automatic on audit enable.**
CLAUDE.md §1.1: "If a person in the lab might ever want to change a value, it lives in the UI."
Automatic deletion on a toggle is too destructive. Banner in production mode shows count + "Purge test entries" button.

**D12 — Autofill suggestions are non-test, non-archived reagents (production mode only).**
`reagent_suggestions` GET endpoint returns deduplicated `{name, supplier, cat_number, category, storage_location}`
for autofill. Returns `[]` when audit is off. Fills all fields except lot_number (lot is unique per bottle).

---

## 2026-06-22 — Reagent scanner: per-reagent scan log (Phase 1 — inventory page)

**Status:** Confirmed

**D5 — Scan log is per-reagent (IAnnotations), not a batch logbook entry.**
The `barcode_lookup` endpoint does exact-match lookup on `barcode`, `lot_number`,
and `cat_number` fields. On match: a `log_scan` POST appends a timestamped entry
(`timestamp`, `scanned_by`, `scanned_value`, `notes`) to `IAnnotations` key
`senaite.pfas.reagent.scan_log` and increments `scan_count` on the object.
On no match: scanner modal pre-fills the lot# field and opens the Add Reagent
form (existing behaviour unchanged).

**Why not a batch logbook entry?** The user confirmed context-specific behaviour:
"if it's a reagent scanned during reagent preparation then it should scan for
the existing inventories." The prep/extraction-logbook integration is Phase 2
(to be built when logbook views receive scanner widgets). The per-reagent log
is an independent, always-available audit trail that does not require a batch
context.

**Scan count badge:** `scan_count` (existing integer field on Reagent, previously
unused) is now incremented on every `log_scan` call and displayed as a small
badge under the reagent name in the inventory table. JS `updateScanCountBadge()`
updates the badge live after each scan without a page reload.

**Note — barcode field not in Add form:** The `barcode` field is stored on Reagent
objects and returned by `barcode_lookup`, but the Add/Edit form does not yet
have a barcode input field. Barcode-field lookup will be a no-op until a form
field is added (Phase 2 improvement).

**Files changed:**
- `browser/reagents.py` — `_SCAN_LOG_KEY`, `_get_scan_log()`, `_append_scan_log()`,
  `scan_log_count()`, `_handle_barcode_lookup()`, `_handle_log_scan()`; routing
  in `__call__`
- `browser/templates/reagents.pt` — scan modal split into Phase-1 camera panel
  and Phase-2 match panel; scan count badge in table; JS `useScanResult()`,
  `showScanMatchPanel()`, `logAndClose()`, `logAndContinue()`, `submitScanLog()`,
  `backToCamera()`, `updateScanCountBadge()`; `_SELF_URL` injected via TAL
- `DECISIONS.md` — this entry

---

## 2026-06-22 — Prepared Standards & Reagent CoA system

**Status:** Confirmed

**D1 — Separate PreparedStandard content type** (not extending Reagent).
`Reagent` stays for procured lots. New `PreparedStandard` Dexterity type
stored in `/pfas_prepared_standards/`. Separate view `@@pfas-prep-standards`.

**D2 — Prep logbook is a separate revisionable entity.** `PrepLogbookDef`
content type stored in `/pfas_prep_logbooks/`. Each revision = new object with
same `logbook_slug` and incremented `revision` int. Only one revision per
slug is "active". A prepared standard records `logbook_slug` + `revision` at
time of preparation. Issuing a new revision archives the current one and can
spawn a new associated `PreparedStandard`. Each `PreparedStandard` stores
analyte concentrations (per-analyte table) in annotations as JSON.

**D3 — CoA: manual upload only.** Stored on filesystem at
`/data/coa/{reagent_uid}.{ext}`. Annotation on Reagent stores metadata
(filename, content_type, uploaded_by, uploaded_date). No scraper in first build.

**D4 — Expiry: configurable per logbook, default 1 year.** `PrepLogbookDef`
carries `default_expiry_days` (default 365). The prep form auto-fills
`expiry_date = prepared_date + default_expiry_days` but the user can change it.
Extension of expiry on existing `PreparedStandard` allowed only with a note
(stored in `expiry_notes`). For procured `Reagent`, existing 7-day mobile-phase
/ 1-year-on-open logic is UNCHANGED.

**Filesystem layout:**
```
/data/coa/       — CoA files for procured reagents ({uid}.pdf etc.)
/data/coa/certs/ — Internal certificates for prepared standards ({uid}.html)
```

---

## 2026-06-21  Phase 2 — Wireframe redesign (Tier 1 nav + Tier 2 tabs)

**Source of truth:** Opus-generated wireframe establishes:
- Single "PFAS TOOLS" section, flat nav list (no multi-section grouping)
- No overview landing page — nav items go directly to tools
- `@@pfas-home` for managers → `@@pfas-method-profiles` (not `@@pfas-qc-management`)
- Method Profile edit uses tab strip (7 tabs), not collapsible accordions
- Pinned action bar (Save / Cancel) always visible below tabs

**Tier 1 — Nav structure:**
- `get_nav_items()` rewritten: single "PFAS Tools" section, flat role-filtered
  item list. Manager/LabManager sees 9 tools; Analyst/Verifier sees subset;
  LabClerk sees Batch Status + Reagent Inventory + Sample Tracker.
- `PFASWorkspaceHomeView` updated: Manager → `@@pfas-method-profiles`
- `PFASQCManagementView` replaced with a simple redirect to `@@pfas-method-profiles`

**Tier 2 — Method Profile Edit tabs:**
- `method_profile_edit.pt` rewritten: `<details>` collapsibles replaced by
  `<div class="tab-pane">` wrappers, grouped into 7 tabs via the `tabs` slot.
- Save & Export + Cancel moved from inline `.save-bar` to `action-bar` slot;
  button uses `form="profile-form"` HTML5 attribute to submit the form.
- `form` element given `id="profile-form"`.
- Tab groupings:
  - **Analyte × Matrix**: Method Info + A×M Inclusion + Per-Analyte Assignments + Isomer Summation
  - **Surrogate Map**: Surrogate Map
  - **Recovery Tiers**: Recovery Tiers + Spike Levels + Salt Factors + Matrix Factors
  - **EIS Limits**: EIS Recovery Overrides (pane always present; content conditional on `show_eis_overrides()`)
  - **Calibration**: Calibration + Chromatographic Confirmation
  - **CCV**: CCV + Duplicate/LFSMD RPD
  - **SI Response**: IS Response + Extraction Stages
- Client-side JS `pfasTabSwitch()` inline in content slot; hash-based tab
  persistence (`#pane-ami` etc.). All hidden inputs stay inside `<form>` —
  only visibility toggled via `.active` class.
- `header-title` changed from "Edit — {display_name}" to just `{display_name}`.

**Files changed:**
- `browser/pfas_macros.py` — `get_nav_items()` rewritten (flat single-section list)
- `browser/workspace_home.py` — redirect target updated; `PFASQCManagementView` simplified
- `browser/templates/method_profile_edit.pt` — full rewrite (tabs, action-bar)
- `DECISIONS.md` — this entry

---

## 2026-06-21  Phase 2 — Decision #4 (workspace launcher URL) + Decision #5 (first workspace)

- **Decision #4 — Workspace launcher URL:** `@@pfas-home` registered at the
  portal root. Reads the current user's SENAITE role and redirects to their
  default workspace. Does not override any SENAITE native URL. Linked from the
  existing SENAITE dashboard tile (`senaite.pfas.dashboard.tiles` viewlet).

- **Decision #5 — First workspace to build in panel frame:** QC Management.
  Rationale: all five sub-views already exist
  (`@@pfas-method-profiles`, `@@pfas-qc-type-grid`, `@@pfas-qc-rules`,
  `@@pfas-control-chart`, `@@pfas-method-wizard`); the current default
  left-panel nav already approximates it; LabManager/QAO is the primary
  power-user role that configures everything else.

- **Role routing in `@@pfas-home`:**
  - LabManager / Manager → `@@pfas-qc-management`
  - Analyst / Verifier → `@@pfas-sample-status` (placeholder until Data Review
    workspace is built)
  - LabClerk → `@@pfas-reagents` (placeholder until Bench workspace is built)
  - Client / default → `@@pfas-track`

- **Left-panel nav:** Default slot in `pfas_macros.pt` replaced with a TAL
  loop over `context/@@pfas-macros/get_nav_items` — returns role-scoped items.
  The `left-panel` METAL slot remains overrideable by individual workspace pages.
  Uses `context/@@pfas-macros` (explicit traversal) to avoid binding to the
  calling view's `view` variable under Chameleon METAL expansion.

- **Files changed:**
  - `browser/pfas_macros.py` — added `get_nav_items()` method
  - `browser/templates/pfas_macros.pt` — replaced hardcoded nav; added
    workspace card CSS (`.pfas-ws-grid`, `.pfas-ws-card`)
  - `browser/workspace_home.py` — NEW: `PFASWorkspaceHomeView` (redirect) +
    `PFASQCManagementView` (landing page)
  - `browser/templates/pfas_qc_management.pt` — NEW: QC Management landing
  - `browser/configure.zcml` — registered `pfas-home` + `pfas-qc-management`
  - `browser/pfas_nav.py` — added `@@pfas-home` entry to dashboard tiles

---

## 2026-06-21  Migration Unit 5 — Tracking Store: no migration (confirmed)

- **Decision:** Leave `tracking_store.py` on portal annotations. No Dexterity
  content type, no catalog registration, no schema change.

- **Rationale:** The tracking store is a bidirectional runtime index
  (`tracking_number ↔ ar_uid`) — not configurable content. It has none of
  the properties that justified Units 1–4: no audit trail needed (assignment
  is automatic on AR receive), no ACL needed (the public tracker view reads
  it), no catalog search needed (all access is by exact key lookup). Wrapping
  each `(tracking_number, ar_uid)` pair in a Dexterity object would add
  catalog overhead to what is currently an O(1) `PersistentMapping` lookup.

- **Alternative considered:** Re-home the tracking number as an attribute on
  the AR itself + catalog index (Option C). This is the single-source-of-truth-
  pure answer, but it requires a data-model change, a migration of existing
  annotation data onto AR objects, a new catalog index, and touching the receive
  subscriber and both browser views. Not justified by a current forcing function.

- **`PF-YYMMDD-XXXX` is not a duplicate:** `instance.getId()` in the receive
  subscriber is the SENAITE-internal Plone ID (e.g., `H-2024-001234`).
  The tracking number is a separate client-facing identifier stored only in
  the annotation index — there is no overlap to consolidate.

- **Closes migration series:** Units 1–5 are the complete set of annotation
  stores in `senaite.pfas`. Unit 5 required no code change. The migration
  series is done.

- **Files changed:** None.

---

## 2026-06-21  Migration Unit 4 — EGADConfig Dexterity singleton

- **Scope:** `egad_store.py` CRUD migrated from a six-key `PersistentMapping`
  in portal annotations (`PFAS_EGAD_KEY`) to one `EGADConfig` Dexterity singleton
  object at `portal/pfas_egad_config/egad_config`.

- **Strategy (confirmed):** Singleton blob — one `EGADConfig` object for the entire
  lab; six `schema.Text()` fields (`lab_json`, `method_egad_json`, `analyte_cas_json`,
  `qualifier_map_json`, `qc_type_map_json`, `lookups_json`), one per config section.
  No field decomposition.  Per-client settings (`get/save_client_egad`,
  `is_egad_enabled`) remain on Client object annotations — unchanged and untouched.

- **No file bridge:** `analyte_cas.json` is mentioned only in a docstring.
  All callers (`egad_builder.py`, `egad_config.py`, `egad_publish.py`) are in-process
  via the public API.  No file export calls added to `save_*` functions.

- **Files changed:**
  - `content/egad_config.py` — NEW: `IEGADConfig` schema (6 Text fields) + `EGADConfig(Item)` class
  - `profiles/default/types/EGADConfig.xml` — NEW: Dexterity FTI
  - `profiles/default/types.xml` — added `EGADConfig` entry
  - `content.zcml` — added `<allow attributes>` for all 6 blob fields
  - `egad_store.py` — ZODB section rewritten (lines 215–end):
    - Kept `_get_store`, `_load`, `_save` for annotation fallback
    - Added `_get_egad_singleton(portal)` private helper (returns Dexterity object or None)
    - All `get_X` / `save_X` pairs: Dexterity-first + annotation fallback
    - Back-fill logic (new keys from `DEFAULT_*`) preserved inside each `get_X`
    - `refresh_lookups_from_xlsx` unchanged (transparent: calls rewired `get/save_lookups`)
    - Per-client trio (`get_client_egad`, `save_client_egad`, `is_egad_enabled`) unchanged
    - `seed_defaults` rewired: seeds Dexterity object when present, annotation store as fallback
    - `DEFAULT_ANALYTE_CAS`, `DEFAULT_QC_TYPE_MAP`, `DEFAULT_LOOKUPS` stay module-level
  - `setuphandlers.py` — `setup_egad_config_catalog(portal)` +
    `migrate_egad_config_from_annotations(portal)` added; both wired into `post_install()`
  - `DECISIONS.md` — this entry

- **Migration constraints honoured:**
  1. Verbatim copy: each annotation sub-key raw JSON string copied directly to the blob
     field — no deserialise/reserialise.  Preserves all user edits exactly.
  2. Any sub-key absent from the annotation store is seeded from `DEFAULT_*` (fresh install).
  3. Idempotent: if `pfas_egad_config/egad_config` already exists, migration returns `(0, 1)`.
  4. `seed_defaults` continues to be called from `setup_handler`; on a fresh install it seeds
     the annotation store first, then `post_install` migrates it to Dexterity.

- **Flag (not in scope):** `analyte_cas` maps analytes globally (all methods share one
  table); CLAUDE.md §3 places CAS codes under Method.  Noted as a single-source-of-truth
  question; re-homing it is a separate architecture decision, not part of this storage migration.

- **Verification (run after container restart + profile reapply):**
  1. `post_install` log: "EGADConfig registered in senaite_catalog_setup",
     "EGADConfig migration: 1 migrated, 0 already present"
  2. `portal.pfas_egad_config["egad_config"]` exists
  3. `json.loads(portal.pfas_egad_config["egad_config"].analyte_cas_json)` is a dict
     with ~35 keys (one per PFAS analyte keyword)
  4. EGAD Config UI (`@@pfas-egad-config`) renders with existing lab settings intact
  5. Edit a CAS code and save → re-read `analyte_cas_json` from Dexterity object confirms
     the value changed; annotations store may still hold the old value (that is correct)
  6. Object existence is the discriminating test — the config page renders even with an
     empty annotation store because `get_X()` falls back to `DEFAULT_*`

---

## 2026-06-21  Migration Unit 3 — MethodProfile Dexterity content

- **Scope:** `method_profile_store.py` CRUD migrated from `PersistentMapping`
  in portal annotations to `MethodProfile` Dexterity objects in
  `portal/pfas_method_profiles/`.

- **Strategy (User Decision 2 — confirmed):** Blob — one `MethodProfile`
  Dexterity object per method_id; full JSON stored in a single
  `profile_json = schema.Text()` field.  No field decomposition.

- **Files changed:**
  - `content/method_profile.py` — NEW: `IMethodProfile` schema + `MethodProfile(Item)` class
  - `profiles/default/types/MethodProfile.xml` — NEW: Dexterity FTI
  - `profiles/default/types.xml` — added `MethodProfile` entry
  - `method_profile_store.py` — rewritten ZODB section (lines 998–end):
    - Added `_get_profiles_folder(portal)` private helper
    - `get_profile()` / `save_profile()` / `list_method_ids()` / `export_profiles_to_file()` /
      `seed_default_profiles()` all Dexterity-first with annotation fallback
    - `get_profile_store()` retained for backward compatibility
      (`migrate_profile_structure.py` imports it)
    - `DEFAULT_PROFILES`, `PFAS_METHOD_PROFILES_KEY`, and all helper functions
      (lines 1–997) unchanged
  - `setuphandlers.py` — added `setup_method_profiles_catalog(portal)` +
    `migrate_method_profiles_from_annotations(portal)`; wired both into `post_install()`

- **Migration constraints honoured:**
  1. Verbatim JSON copy in migration — raw annotation string assigned directly
     to `obj.profile_json`; NOT routed through `get_profile()`.  Preserves
     `_seeded` flags and any manager edits.
  2. `save_profile()` create-on-demand: if the Dexterity object does not exist
     yet (e.g. wizard creating a novel method_id), `invokeFactory` is called.
  3. File bridge preserved: `export_profiles_to_file()` reads from Dexterity
     folder (if present) or annotation store, and always writes
     `PROFILES_EXPORT_PATH` atomically.
  4. Back-fill logic (`get_profile()`) and `_migrate_spike_levels()` preserved.
  5. `migrate_profile_structure.py` is a one-time migration script that
     directly accesses `get_profile_store()` (the annotation mapping).  After
     this migration it reads an empty store and is a no-op.  If it ever needs
     re-running, update it to use `save_profile()` instead.

- **Ordering:** `setup_handler` calls `seed_default_profiles()` before
  `post_install` creates the folder.  Fresh install: seeds annotation store →
  `post_install` migrates to Dexterity.  Re-install: folder present → seeds
  missing objects directly into folder; migration is idempotent.

- **Verification (run after container restart + profile reapply):**
  1. `post_install` log: "MethodProfile registered in senaite_catalog_setup",
     "MethodProfile migration: N migrated, 0 already present"
  2. `len(portal.pfas_method_profiles.objectIds()) == 3`
     (FDA_32PFAS, EPA_537_1, EPA_1633A)
  3. `portal.pfas_method_profiles["FDA_32PFAS"].profile_json` is non-empty JSON
  4. `@@pfas-method-profiles` renders with 3 profile rows
  5. Edit a profile value and save → `/data/qc/method_profiles.json` updated;
     diff before/after shows only the edited field changed
  6. Object count check is the discriminating test — fallback path means page
     renders correctly even with zero objects (do not use page render as proof)

## 2026-06-21  Integration gaps B, D, E wired

- **Gap B (Wizard step 5 → QC Type Grid):** Added "Open QC Type Grid →" link to
  wizard step 5 (`method_wizard.pt`), shown after the Method Profile Editor link.
  Both links open in a new tab; user clicks "Profile Confirmed" to advance.

- **Gap D (Batch Status Stage 5 → Export EDD):** Added conditional "Export EDD →"
  button to Stage 5 batch cards in `sample_status.pt`, linking to
  `@@pfas-egad-batches?batch_id=${b/batch_id}`.

- **Gap E (Batch Status Stage 4 → Charts):** Added conditional "Charts →" button
  to Stage 4 batch cards in `sample_status.pt`, linking to
  `@@pfas-control-chart?method=${b/method}`.

- **Gap C (EGAD Config "Generate Test EDD") deferred:** `@@pfas-egad-export`
  requires a real `batch_id`; a test/preview-without-batch path doesn't exist.
  Will address when a backend endpoint for dry-run EDD generation is added.

- **Status:** confirmed — `method_wizard.pt`, `sample_status.pt` updated;
  verified 200 on both pages with no TAL errors.

## 2026-06-20  Migration Unit 1 — Reagent catalog wire-up

- **Architecture (Option A confirmed):** PFAS data becomes first-class SENAITE
  content. No fork of senaite.core. Reagent and all future PFAS types are
  Dexterity content objects indexed in `senaite_catalog_setup`, participating in
  the audit trail and permission model.

- **Reagent identifier strategy:** The canonical CRUD identifier for Reagent is
  the **Zope object ID** (UUID hex, e.g. `"a3f1c..."`) stored as `obj.getId()`.
  `IReferenceable` provides a second SENAITE UID for cross-content references
  (`api.get_uid(obj)`), but forms, URLs, barcode lookup, and logbook records use
  the object ID.  Rationale: migration requires keeping old annotation UUIDs
  intact for logbook referential integrity; URL/form CRUD on object ID is
  simpler and avoids catalog round-trips.  Future types that have no migration
  legacy (PFASMethodProfile, SurrogateMap, QCRuleSet) MAY use `IAutoGenerateID`
  for user-friendly LIMS IDs — that is a per-type decision.

- **`IAutoGenerateID` excluded from Reagent.xml:** SENAITE's ID generator fires
  on `IObjectAddedEvent` and would overwrite our explicit UUID hex IDs with a
  sequence like `RD-00001`, breaking the migration.  All other SENAITE behaviors
  (`IReferenceable`, `IMultiCatalogBehavior`) are retained.

- **`set_catalogs` called programmatically (not via catalog.xml):** Called from
  `post_install` via `setup_reagents_catalog()`.  This writes to
  `portal_registry["catalog_mappings"]` at install time.  A `catalog.xml` step
  would also work but is unnecessary given the runtime API.

- **Write-on-read expiry:** `_list_reagents` mutates the transient dict only
  (display-time expiry promotion to STATUS_EXPIRED); the persistent write
  happens only on the next explicit save.  This avoids ZODB conflicts and
  plone.protect friction on GET requests.

- **`quantity` and `unit` fields:** Added to `IReagent` schema as `TextLine`
  fields; they exist in the legacy annotation store and the `reagents.pt`
  template reads and renders them.  Added to `content.zcml` allow attributes
  and to `_obj_to_dict` / `_populate_obj`.

- **Status:** implemented — `content/reagent.py`, `profiles/default/types/Reagent.xml`,
  `content.zcml`, `setuphandlers.py` (new `setup_reagents_catalog` +
  `migrate_reagents_from_annotations` functions), `browser/reagents.py` (CRUD
  switched from annotation JSON to content objects).  Not yet verified in running
  SENAITE — see verification checklist below.

  **Verification checklist (run after container restart + profile reapply):**
  1. `post_install` log lines visible: "Reagent registered in senaite_catalog_setup", "migrated=N"
  2. `pfas_reagents/<uuid>` objects exist with `obj.getId() == old_annotation_uid`
  3. `senaite_catalog_setup(portal_type="Reagent")` returns results
  4. `@@pfas-reagents` renders with existing reagent rows intact
  5. Add/edit/delete a reagent → changes persist via content objects

## 2026-06-20  Panel shell — Phase 1 complete (Decision #1 executed)

- **Decision #1 executed:** Subnav strip (`.pfas-subnav`) removed.  Replaced by
  §6 panel shell in `pfas_macros.pt`: header bar + collapsible left panel +
  tabbed content area + pinned action bar.
- New slots: `left-panel`, `tabs`, `action-bar`.  Old slots preserved: `title`,
  `head-extra`, `header-title`, `header-right`, `content`, `body-extra`,
  `scripts`.
- **Status:** implemented — `browser/templates/pfas_macros.pt` rewritten.
  Not yet browser-verified (requires container restart).

## 2026-06-20  QC type grid, per-spike RPD, analyte reference expansion

- **Decision:** QC type selection is managed via `@@pfas-qc-type-grid` — a methods × QC types checkbox matrix.  Checking/unchecking a cell creates/removes the corresponding `qc_acceptance` key in the method profile.  No `enabled: False` placeholders remain; key presence = enabled.
- **Decision:** Per-spike-level RPD criteria are modelled as an optional `spike_level` field on existing `qc_acceptance` tiers (values: "Low" / "Mid" / "High" / null = all levels).  Tiers without `spike_level` apply to all spike levels.  Resolution is `(analyte_group, matrix_scope, spike_level)`.
- **Decision:** Spike level tables in the Method Profile editor are driven by `associated_qc_types`; LCS is now included alongside LFB/LFSM as a spike-level-aware QC type.  LFSMD shares the LFSM spike level table.
- **Decision:** `analyte_reference.py` expanded from 34 native + 21 IS to 47 native + 27 IS.  The 13 new natives and 6 new IS are EPA 1633A-specific (FOSA precursors, PFECA novel compounds, FTCAs, FOSA-surrogate IS).  New class "FTCA" added to taxonomy.
- **Status:** confirmed — implemented in `analyte_reference.py`, `method_profile_store.py`, `qc/rules.py` (`enabled` fix in pfas_pipeline/method_profiles.py), `browser/qc_grid.py`, `browser/templates/qc_grid.pt`, `browser/configure.zcml`, `browser/static/method_profile_edit.js`.

## 2026-06-19  pfas_role field on AnalysisService

- **Decision:** Add `pfas_role` schema-extender field (`analyte` / `surrogate` / `injection_is`) to every SENAITE AnalysisService.  This is the single authoritative source for the IS/surrogate/analyte distinction.  All derivations of IS lists, surrogate maps, and analyte panels must read this field — not category names, not private per-profile copies.
- **Decision:** Method Profile IS list = services linked to the method whose `pfas_role` is `surrogate` or `injection_is`.  Surrogate map = derived from `analyte_reference.NATIVE_ANALYTES[].surrogate_is` keyed to surrogate services.  Neither is stored as a separate copy in the profile.
- **Decision:** `is_key_analyte` and `no_labeled_std` (used by FDA tier resolution) remain in `analyte_reference.py` for now; they are service-level identity properties that could later be added as extender fields, but scope is deferred until the lab requests UI control over them.
- **Status:** confirmed — implemented in `extenders/analysisservice.py`, `extenders/configure.zcml`, `setuphandlers.py`, `migrations/stamp_pfas_roles.py`.

## 2026-06-19  Architecture consolidation — one profile store, no globals

- **Decision (Option A):** One profile object per method contains `instrument_verification` + `qc_acceptance` + `extraction_corrections`.  `qc/rules.py` is scoped to instrument-only (toggle/engine-check registry; no limits, no global fallbacks).  Global fallback layer removed — every criterion must be explicitly defined per method.
- **Decision:** QC acceptance keys in the profile exist only for QC types actually associated via wizard Step 5.  No `enabled: False` placeholder keys.  The wizard association creates the key; removing the association removes the key.
- **Decision:** `per_analyte` block removed from Method Profile — derivable from `analyte_reference.py` and `surrogate_map`.
- **Status:** confirmed — implemented across prior sessions.

## 2026-06-19  Q-001 — MassLynx IS naming confirmed as 13C prefix

- **Decision:** Waters MassLynx exports IS/surrogate compound names using the **13C prefix** format (e.g. `13C8-PFOS`, `13C3-PFBA`, `13C4-PFOA`). The M-prefix identifiers (M8PFOS, M3PFBA) are internal SENAITE keywords only. The pipeline's `get_is_list()` already returns `_FDA_IS_DISPLAY_NAMES` in 13C format — no code change required.
- **Decision:** `internal_standards.csv` stores `Keyword=M-prefix, Title=13C-name`. All pipeline IS lookups and surrogate_map field values must use the 13C Title names.
- **Status:** confirmed — closed Q-001.

## 2026-06-19  PFTrDS CAS number resolved

- **Decision:** PFTrDS (perfluorotridecane-1-sulfonic acid) CAS registry number is **791563-89-8** (Restek compound database; molecular formula C13HF27O3S). Updated in `setupdata/analysis_services.csv`. EGAD EDD export no longer blocked on this analyte.
- **Status:** confirmed — PLACEHOLDER replaced.

## 2026-06-19  EPA 1633A matrix alignment — removed phantom matrices

- **Decision:** `_EPA1633A_MATRICES` corrected to exactly match SENAITE SampleType titles. Removed `"Aqueous"` (no matching SampleType — Groundwater batches were silently getting no spike_levels) and `"Solid"` (no SampleType; Sediment/Soil already listed). Added `"Groundwater"`, `"Wastewater"`, `"Landfill Leachate"` which ARE SampleTypes associated with EPA_1633A.
- **Decision:** `export_profiles_to_file()` bug fixed — it previously exported stored profiles without back-filling absent keys from DEFAULT_PROFILES, so any ZODB-deleted key was absent from the worker JSON. Now back-fills before export.
- **Decision:** `sample_types.csv` updated to link Groundwater and Surface Water to EPA_537_1 (they were already in `_EPA537_MATRICES` but not in the CSV method association).
- **Status:** confirmed — pipeline matrix lookups for Groundwater/Wastewater/Landfill Leachate now resolve correctly.

## 2026-06-19  Method Profile UI redesign (session 4)

- **Decision:** Surrogate Map replaced drag-and-drop chip UI (which was broken/non-functional) with a simple per-analyte dropdown table. Each native analyte gets one `<select>` for its labeled IS. Injection IS field moved into the Surrogate Map section.
- **Decision:** Matrix Adjustment Factor changed from a single integer field to a per-sample-type table (matching the `matrix_factors` list format the pipeline already reads). Batch matrix substring-matched against table entries.
- **Decision:** Per-Analyte table streamlined — removed Surrogate IS, Key Analyte, and Recovery Tier columns (these were duplicates of Surrogate Map and Recovery Tiers sections; pipeline never read them from per_analyte). Remaining columns: Analyte, No IS, Confirm Ion, Notes.
- **Decision:** Form sections regrouped with visible dividers: Analyte Configuration / Instrument QC Criteria / Sample Prep & Corrections / Lab Workflow. All sections start collapsed except Method Information.
- **Status:** confirmed — deployed and verified in container.

---

## 2026-06-19  Q-014 — Spike levels restructured to per-matrix

- **Decision:** `spike_levels` data structure changed from flat `{"LFB":[...], "LFSM":[...]}` to per-matrix `{"Matrix Name": {"LFB":[...], "LFSM":[...]}}`. Matrix keys come from the method's `supported_matrices`. Lab confirmed spike concentrations vary by matrix when backcalculating to sample size (ppt = mass / sample_size per matrix).
- **Decision:** Storing ppt directly per matrix (not spike mass + per-matrix sample size). Simple, explicit, matches what goes on the report.
- **Shape migration:** `_migrate_spike_levels()` in `method_profile_store.py` auto-upgrades stored old-format profiles on read (`get_profile()`) and on export (`export_profiles_to_file()`). No manual ZODB migration required.
- **Status:** confirmed — implemented in `method_profile_store.py`, `browser/method_profiles.py`, `method_profile_edit.pt`, `method_profile_edit.js`, `method_profiles.py` (pipeline), `run_queue.py`.
- **Context:** Q-014 lab directive: "will this be changeable by matrix? When backcalculating to sample size the spikes vary by matrix."

## 2026-06-19  Q-004 — 1633A EIS limits implemented from EPA 820-R-24-007

- **Decision:** `eis_overrides` in DEFAULT_PROFILES for EPA_1633A replaced with actual per-analyte limits from EPA 1633A Table 6 (aqueous, 24 EIS compounds). `eis_matrix_overrides` dict added for per-matrix-class limits (leachate, solid, tissue, biosolid) from Tables 6 and 8.
- **Decision:** Pipeline `EPA1633AProfile.qc_rules()` selects the EIS limit for the analyte × matrix-class combination at runtime. Matrix class is derived from the batch matrix name via `_1633a_matrix_class()`.
- **Status:** confirmed — implemented in `method_profile_store.py` and `method_profiles.py` (pipeline).
- **Context:** Q-004 lab directive: "1633 is available on the EPA website and the pdf can be used."

## 2026-06-18  Q-011 — LFSM/LFSMD per-analyte tiered recovery wiring

- **Decision:** LFSM recovery and LFSMD RPD are evaluated automatically by the pipeline engine using per-analyte tiered limits from the method profile. Spike concentration is resolved from the method profile's `spike_levels` section using the level label encoded in the injection name (e.g. `"; LFSM High"` → `"High"` → configured ppt). No spike → check stays PENDING. Flat `CRITERIA` values remain for `LFSMResult.passes` / `LFSMDResult.passes` only.
- **Decision:** LFSM/LFSMD checks no longer silently AUTO_PASS when no QC engine runs them (the previous regulatory defect). They now stay PENDING until spike levels are configured.
- **Decision:** Spike level values are lab-specific and must be entered via the Method Profile UI (`spike_levels` JSON field). Seed values are empty lists; see Q-014 for values outstanding.
- **Status:** confirmed — implemented in `run_queue.py::auto_evaluate()`, `method_profiles.py::resolve_spike_ppt()`, and all three method profile seeds.
- **Context:** Q-011 answer from lab: per-analyte tiered limits; spikes rotate through configured options defined in method profile.

## 2026-06-18  Q-013 + Q-005 confirmed

- **Q-013 (Milk unit):** FDA 32-PFAS Milk matrix reports in **ng/mL** (per-volume, liquid). All other FDA matrices report in ng/kg. Unit map is per-matrix and editable via the Method Profile UI. Seed updated in `method_profile_store.py`.
- **Q-005 (cal_r2_min):** R² minimum is per-method (the profile system already supports this — each method profile has its own `cal_r2_min` field). Values are editable via the Method Profile UI. Status: confirmed and closed.

## 2026-06-18  Item 8 — Parentage audit findings

- **Decision (gap fixed):** `pfas_pipeline.models.Batch` now carries `method_id: str`. Previously `run_pipeline()` accepted `method_id` but never stored it on `Batch`, so result sets could not name their method parent (§9.3 rule 3). Fixed in `models.py` + `pipeline.py`. Report header updated to surface `Method:` on every PDF.
- **Decision (deferred):** `LFSMResult.passes` / `LFSMDResult.passes` in `models.py` and the recovery/RPD checks in `qc_engine.py` still use the flat `CRITERIA` dict (constants.py `_build_criteria_from_profile` explicitly defers recovery_min/max and rpd_max mapping). These are Decision-C violations, not parentage gaps. To be addressed as a separate item after the lab confirms which profile JSON fields to map.
- **Status:** Gap 1 confirmed. Deferred gaps noted in QUESTIONS.md.
- **Context:** Item 8 "Verify parentage end-to-end" — systematic audit of result → analyte → method × matrix → batch traceability.

## 2026-06-17  Round 9 — Relational data model schema (pre-build sign-off)

- **Decision (schema):** Consolidate to two canonical layers:
  1. **Analyte Library** (`analyte_reference.py`) — single source for keyword, name,
     CAS (standard format), EGAD CAS/parameter_name, full_name, class, chain,
     is_native, no_labeled_std, is_key_analyte, quan_mrm, qual_mrm_list, surrogate_is.
     All duplicate declarations in `analytes.py`, `constants.py`, `method_profiles.py`,
     and `method_profile_store.py` are retired. MRM data absorbed from `analytes.py`.
  2. **Method Profile ZODB store** (`method_profile_store.py`) — owns all
     method-level config: master_analyte_set, supported_matrices,
     analyte_matrix_inclusion (the checkbox grid), surrogate_map, recovery_tiers
     (per analyte × matrix, stored explicitly — NOT computed invisibly in Python),
     eis_limits (1633A only), unit_map, cas_map, QC ruleset, salt factors,
     matrix adjustment, isomer summation, logbook templates. Exported to
     `/data/qc/method_profiles.json` for the pipeline.

- **Decision (Q2 — UI editing):** `analyte_reference.py` seeds the analyte library
  on first install, but ALL fields (including MRMs, CAS, flags) must be editable
  through a UI tool so the lab can extend or correct them without code changes.

- **Decision (Q3 — method_profiles.py fallback):** Keep `pfas_pipeline/method_profiles.py`
  Python dataclasses as factory-default seeds AND offline fallback (Option A).
  Regulatory reason: all QC tolerances must be readable by auditors through the UI.
  Values hidden in code do not satisfy ISO 17025 / regulatory audit requirements.
  Consequence: the resolution logic (e.g. "big-four in eggs/meat → 80–120%") must
  be stored explicitly as a visible table in ZODB, not computed invisibly by a
  Python method. The Python dataclasses seed those explicit table rows on first
  install and serve as the fallback only when the JSON export is absent.

- **Retirements (pending build):** duplicate NON_ISO_ANALYTES / KEY_ANALYTES /
  _FDA_BIG4 / _FDA_NO_LABELED_STD sets across 4 files → derived from library flags.
  `QCCriteria` class in `analytes.py` → retired. `ANALYTE_CAS_DEFAULTS` in
  `egad_edd.py` → absorbed into method profile `cas_map`. `METHOD_MATRIX_UNIT_MAP`
  in `qc/rules.py` → absorbed into method profile `unit_map`.
- **Status:** confirmed — schema approved, build not yet started
- **Context:** Round 9 item 0 schema audit; §9 relational data model.

---

## 2026-06-16  Plan B — Import Studio REST bridge design

- **Decision (Q-010):** Pipeline identifies a file's instrument by auto-detecting
  the vendor from CSV headers (sciex/agilent/waters/native). No instrument UID
  or CLI argument needed. The software version is auto-detected from the first
  20 lines of the file. The lookup key is `"vendor_key:version"`.
- **Decision (Q-011):** Strict — the importer requires an explicitly saved profile
  in `IAnnotations(portal)["senaite.pfas.vendor_profiles"]["vendor_key:version"]`.
  Seeded default templates (`senaite.pfas.vendor_templates`) pre-fill the Import
  Studio UI but do NOT satisfy the importer's profile check. First use of any
  instrument/version requires a lab trip to Import Studio.
- **Decision (Q-012):** Fail fast — if SENAITE is offline, the pipeline refuses to
  process the file. No fallback to `vendor_profiles.py`. SENAITE downtime halts
  instrument file processing; this enforces single source of truth.
- **Implementation:** `@@pfas-instrument-profile` REST bridge view added to
  `import_studio.py`. Portal-level stores: `senaite.pfas.vendor_profiles`
  (pipeline reads), `senaite.pfas.vendor_templates` (Import Studio UI pre-fill).
  `senaite_connector.get_instrument_profile()` fetches from SENAITE.
  `load_instrument_csv(profile=...)` uses profile map; raises ImportError on error.
  `run_pipeline()` detects vendor+version from CSV, fetches profile, refuses if
  `{"error": ...}` returned. `vendor_profiles.py` maps still used when no senaite
  connector (standalone mode for testing).
- **Status:** confirmed — implemented and tested
- **Context:** Round 8 Item 2 — Import Studio must be the single source of truth
  for column mappings.

---

## 2026-06-16  Calibrations pane bug — request.get() picks up HTTP method

- **Decision:** Use `self.request.form.get(key)` (not `self.request.get(key)`)
  for all form parameter reads in browser views. In Zope 2's BaseRequest,
  `request.get("method", "")` returns the HTTP verb ("GET") when there is no
  form field named "method" — it searches env/headers before returning the
  default. This silently injected `AND method='GET'` into the calibration
  query, filtering out all 686 records.
- **Status:** confirmed — fix applied to `calibrations.py`; root cause extends to
  any view that reads form params with `request.get()`. Existing views use
  `request.form.get()` for most params and have been audited.
- **Context:** Discovered while seeding synthetic calibration data (Round 8
  Item 4). Same class of bug as the METAL slot boundary issue (Round 8 Item 3)
  — a silent null result.

## 2026-06-16  Synthetic calibration seed data

- **Decision:** Seed data lives in `pfas_pipeline/seed_calibrations.py`. All
  synthetic records use `batch_id LIKE 'SYNTHETIC_%'` for easy identification
  and purge. Script is idempotent (skips existing batch_id+analyte pairs).
  One-command purge: `python seed_calibrations.py --purge` (in pfas-worker
  container) or direct SQL via sqlite3.
- **Status:** confirmed — 14 synthetic records inserted (3 methods: FDA_32PFAS,
  EPA_537_1, EPA_1633A; mix of approved/pending/rejected; 2 intentional failures).
- **Context:** Round 8 Item 4 — seed data needed to evaluate calibrations pane.

---

## 2026-06-16  Round 8 — Integration Consolidation

- **Decision (A) — Analyte list canonical source:** `pfas_pipeline/constants.py` is the
  canonical Python definition of ANALYTES and INTERNAL_STANDARDS. `src/.../analytes.py`
  is simplified to import/derive from the setupdata CSVs rather than re-declaring.
  Status: confirmed.

- **Decision (B) — Import Studio REST bridge:** Add `@@pfas-instrument-profile` browser
  view that serves saved ZODB profiles as JSON to the Python 3 pipeline worker. Portal-level
  fallback store keyed by `vendor_key:version`. Importer reads profile via REST; refuses
  with clear error if no profile found. `vendor_profiles.py` becomes seed-only reference.
  Status: confirmed.

- **Decision (C) — QC criteria single source:** Retire hardcoded limits in
  `pfas_pipeline/method_profiles.py`; pipeline reads from `/data/qc/qc_rules.json`
  (already written by `@@pfas-qc-rules`). `reload_criteria()` in `constants.py` already
  does this; method_profiles.py dataclass defaults replaced with `get_rules()` lookups.
  Status: confirmed.

- **Decision (D) — Dormant in-Plone QC engine:** Delete `src/.../qc/engine.py` (duplicate
  of pipeline engine, nothing calls it). `src/.../report/__init__.py` is empty, also removed.
  `src/.../ingest/data_importer.py` is orphan — deleted in favour of Plan B REST bridge.
  Status: confirmed.

- **Decision — Reagents buttons root cause:** All PFAS templates with `<script>` blocks
  after `</div><!-- /content slot -->` had their JS silently discarded by METAL macro
  processing. Fixed in reagents.pt + 6 other templates by moving content slot close div
  to after script blocks.
  Status: confirmed.

---

## 2026-06-15  Round 7 — Maine EGAD EDD Exporter

- **Decision (a):** Four-scope config model: lab-global → per-method → per-client →
  per-sample override. Lab-global and method settings live in PFAS_EGAD_KEY portal
  annotations; per-client settings live in IAnnotations(client)["senaite.pfas.egad_client"].
- **Decision (b):** CAS_NO stored per-analyte (not per-method), because all 34 analytes
  run on all three methods. View scope filtered by method for display only.
- **Decision (c):** SAMPLE_TYPE default = GW (groundwater); configurable per-client and
  overridable per-sample at intake via IAnnotations(ar)["senaite.pfas.egad_sample_type"].
- **Decision (d):** Food/solid units = NG/KG; water units = NG/L. Configurable per-method.
- **Decision (e):** SDG (Sample Delivery Group) is configurable: prefix + format template
  in lab-global settings. Default format: {prefix}{batch_id}.
- **Decision (f):** SAMPLE_COLLECTION_METHOD configurable in lab-global settings; default LFS.
  QC samples always use NA automatically.
- **Decision (g):** NC_Flag analytes → RESULT_TYPE_CODE = TIC (Tentatively Identified
  Compound), sourced from RESULT_TYPE_LUP. This covers 9Cl-PF3ONS, 11Cl-PF3OUdS,
  PFTrDA, PFODA, DONA, PFPeS, PFHpS, PFNS, PFDS, PFUnDS, PFDoS, PFTrDS.
- **Decision (h):** PREP_METHOD = SW3535 (SW846: Solid Phase Extraction) as default.
  Configurable per-method and lab-global.
- **Decision (i):** ANALYSIS_LAB code is configurable in lab-global EGAD settings.
  Override available per-client. Must match ANALYSIS_LAB_LUP exactly.
- **Decision (j):** PFUnDS (CAS 749786-16-1): not in Maine EGAD CAS_LUP. Manual entry
  required in EGAD Config. CAS_NO field left blank until DEP code assigned.
  PFTrDS (CAS PLACEHOLDER): BLOCKING validation error until real CAS assigned.
- **Decision (k):** EDD delivery: attached to client report email. No auto-send to
  dep.edd@maine.gov. Client submits to DEP themselves.
- **Decision (l):** Filename convention: {CLIENT_ID}_{SDG}_{YYYYMMDD}_EDD.csv
- **Decision (m):** Lookups refreshable via manager upload of EGAD_Lookup_Tables.xlsx.
  User mappings (qualifier_map, qc_type_map, analyte_cas) survive lookup refresh.
- **Decision (n):** Per-report override toggle: default ON for gov clients; manager can
  suppress EDD for a specific report at publish time.
- **Decision (o):** QC type mapping (our → EGAD): MB→LB, LFSM→MS, LFSMD→MSD,
  CCV→CCC, LCS→LCS, Dup→L, FD→D, Normal/NA→NA.
- **Decision (p):** WEIGHT_BASIS = NA for water samples; DW (dry weight) for solid/food
  matrices by default. No WEIGHT_BASIS_LUP exists in EGAD — free text field.
- **Status:** confirmed (all answers provided by lab; Opus advisor review completed)
- **Context:** Round 7 EGAD EDD exporter spec (REFINEMENT_PROMPT_7_EGAD_EDD.txt).
  Advisor confirmed four-scope design is sound. Build sequence: format spike first,
  then config UI, then wire config to generator.


---

## 2026-06-14  Extraction stages editor — Method Profile UI

- **Decision:** Extraction stages are editable in `@@pfas-method-profile-edit` via
  a drag-to-reorder card UI (one card per stage) with fields: order, id, name,
  description, reagent_roles (CSV), equipment (CSV), creates_solution checkbox,
  capture_pedigree checkbox.  The card list syncs to a hidden `extraction_stages_json`
  field on form submit.  `get_profile()` backfills new default keys (including
  `extraction_stages`) into previously-saved profiles so upgrades are seamless.
- **Status:** confirmed
- **Context:** Round 5 item 10 — extraction guide requires method-specific stage
  definitions to be configurable in the Method Profile control panel.

## 2026-06-14  ReportLab — optional dependency, not in install_requires

- **Decision:** `reportlab` is commented out of `setup.py` `install_requires`.
  It requires `gcc` and network access to download T1 fonts, neither of which
  are available in the SENAITE Docker container.  The `@@pfas-extraction-pdf`
  view handles `ImportError` gracefully.  Install manually if PDF export is needed.
- **Status:** confirmed
- **Context:** `reportlab` in `install_requires` caused buildout to crash during
  container startup, preventing `zope.conf` from being generated.

## 2026-06-14  Chameleon XML parser — `<` in JavaScript

- **Decision:** All `<` characters inside JavaScript string literals and regex
  patterns in `.pt` templates must be written as the `<` unicode escape.
  JavaScript runtime decodes `<` → `<` transparently.  Chameleon's XML
  parser treats literal `<` as tag-start, causing `ParseError` on patterns like
  `</option>` or `/</g` in scripts.
- **Status:** confirmed
- **Context:** `@@pfas-import-studio` and `@@pfas-method-profile-edit` crashed
  with `PTRuntimeError` when loaded; fixed by replacing all HTML-in-JS `<` with
  `<` across all affected templates (import_studio, method_profile_edit,
  extraction_guide, logbook_250/251/252/253).

---

## 2026-06-14  Round 5 item 7 — Per-batch logbooks data model

- **Decision:** Four logbooks (FM-ENV-250/251/252/253) stored as JSON blobs in
  ZODB annotations on the SENAITE Batch object. Annotation keys:
  `senaite.pfas.logbook.250` / `.251` / `.252` / `.253`. Browser views
  registered on `for="*"` context; CMF action `pfas_batch_logbooks` adds a
  "Logbooks" sub-tab to Batch objects in SENAITE navigation.
  FM-ENV-251 (Cal Curve) exports cal level data to
  `/data/qc/batches/{batch_uid}/cal_251.json` for the pipeline injection builder,
  and provides a "Download Cal Ladder CSV" button. Full sequence generation
  (with QC bracketing) remains a pipeline worker function
  (`pfas-pipeline build-sequence --batch-id ...`).
  Storage in annotations chosen over Dexterity content types because SENAITE
  Batch is not a folderish container; annotations pattern is consistent with
  how method profiles are stored.
- **Status:** confirmed
- **Context:** User confirmed data model and injection builder link (2026-06-14).

---

## 2026-06-14  Round 5 item 6 — New-Method Wizard redesign

- **Decision:** Redesigned wizard from pure "checklist + links" to 9-step
  association-driven flow. Each step has an inline form for selecting/associating
  existing SENAITE objects to the new method. Inline create for Method object in
  Step 1. Sessions persisted in ZODB portal annotations under
  `senaite.pfas.wizard_sessions`. Real SENAITE associations written:
  `svc.setMethods([method])` in Step 3, `instr.setMethods([method])` in Step 9.
  Other associations (dept, category, sample types, storage, containers) stored
  in `senaite.pfas.method_associations` annotations keyed by method_id.
  Step 5 (Profile) and Step 8 (QC Rules) open their respective editors in a
  new tab; user confirms when done.
- **Status:** confirmed
- **Context:** User confirmed step list (9 steps as listed in DECISIONS above) and
  inline-create for Step 1. Design: association-driven means wizard records
  which items are associated with each method, not just that the items exist.

---

## 2026-06-14  Round 5 items 4–5 — sample tracker + analysis categories

- **Decision (item 4):** Sample Tracker de-branded from "PFAS Lab" to generic "Laboratory"
  branding. Tracker moved out of the PFAS Tools tile group and into the SENAITE top navigation
  bar via a `portal_tabs` action registered in `profiles/default/actions.xml`. Works for any
  received sample (not PFAS-specific). Accessible at `@@pfas-track` by any user with View.
- **Decision (item 5):** Collapse the six chemical-class analysis categories
  (`PFAS - PFCA`, `PFAS - PFSA`, `PFAS - FTS`, `PFAS - FOSA`, `PFAS - PFECA`,
  `PFAS - Cl-PFAES`, `PFAS - other`) into a single **`PFAS`** category.
  Internal standards remain in **`PFAS - Internal Standards`** (separate — analysts need
  to distinguish IS from target analytes). `setuphandlers.py` calls `svc.setCategory()`
  on every get-or-create to migrate existing services on profile re-run.
- **Status:** confirmed

---

## 2026-06-13  Round 4 items 1–4 — design decisions

- **Decision (item 1):** Glyph bug fixed by replacing non-ASCII chars in CSS `content:` properties with
  CSS Unicode escapes (`\25B6`, `\25BC`, `\2713`). Root cause: Zope HTML-escapes non-ASCII text in
  `<style>` blocks; HTML5 browsers don't parse `&#NNNN;` entities inside CSS. Rule going forward:
  never put non-ASCII chars in CSS `content:` inside `.pt` files.
- **Decision (item 2):** Unified chrome via METAL macro in `pfas_macros.pt`; all 7 PFAS page
  templates use `metal:use-macro` to inherit the shared header/card/button skeleton.
- **Decision (item 3):** Override `@@lims-setup` in-place via a Plone browser layer override
  registered in `senaite.pfas`'s ZCML. The core view remains untouched; only the PFAS browser
  layer shadows it. **Upgrade risk**: if `senaite.core` renames or restructures `@@lims-setup`,
  the override will need updating. User accepted this risk explicitly.
- **Decision (item 4):** Wizard step order corrected to match SENAITE dependency chain:
  Storage → Containers → Lab Dept → Analysis Category → Sample Types → Analysis Services →
  Method → Method Profile → Analysis Specs → QC Rules → Instruments. Lab Dept/Category
  moved before Sample Types (services require a category; specs tie services to sample types).
  Implementation: `@@pfas-method-wizard` view in `browser/method_wizard.py` / `templates/method_wizard.pt`.
  Orchestrator pattern: links to existing SENAITE pages, does not reimplement forms.
  Completion detected live from `senaite_catalog_setup` (not `portal_catalog` — setup items
  are only indexed in the SENAITE-specific catalog). Wizard tile added to the "3. Method &
  Analyte Setup" group in `@@lims-setup` via inline TAL in `lims_setup.pt`.
  ZCML override mechanism: `ISenaitePFASLayer(ISenaiteCore)` browser layer defined in
  `interfaces.py`; layer registered via `profiles/default/browserlayer.xml`;
  `@@lims-setup` registered on `ISenaitePFASLayer` — more-specific adapter wins without
  `ConfigurationConflictError`.
- **Status:** confirmed

---

## 2026-06-13  Round 3 items 9+10 — seed script + Levey-Jennings verification

- **Decision:** Synthetic QC test data seeded via `seed_test_data.py` (standalone Python 3 script).
  Inserts 1,344 QC rows (CCV + LFB, 32 weeks, 7 analytes, 3 methods) and 672 calibration rows
  into the shared `pfas-qc` Docker volume.  All records tagged `flag='TEST_DATA'` or
  `flag='TEST_DATA_OUTLIER'`; `--purge` removes them before go-live.  Root bug fixed:
  `self.request.get("method")` returns the HTTP request method ("GET") in Zope 2 — must use
  `self.request.form.get("method", "")` for URL query parameters.  Levey-Jennings spec
  confirmed: ±1/2/3SD lines rendered, point colors per violation severity, Westgard rules
  fire correctly on seeded outliers.
- **Status:** confirmed
- **Context:** Items 9 (seed data) and 10 (Levey-Jennings verification) from Round 3 refinement.
  LFB Recovery selected as the primary QC type (user does not recognize "LCS" as a QC type).

---

## 2026-06-13  Round 3 item 7 — PFAS tiles hidden for unauthenticated users

- **Decision:** `PFASDashboardTilesViewlet.tiles()` checks `'Authenticated' not in user.getRoles()`
  and returns an empty list for anonymous/unauthenticated requests.  The template's
  `tal:condition="tiles"` naturally hides the entire section when the list is empty.
  The viewlet ZCML registration retains `zope2.View` (available to everyone) — the
  auth gate is applied at the Python level, not by changing the ZCML permission.
- **Status:** confirmed
- **Context:** PFAS tool tiles were appearing on the SENAITE login page because
  `zope2.View` is granted to anonymous users.  The fix is a Python-level role check
  rather than a ZCML permission change, so the viewlet remains installable without
  CMF permission setup overhead.

## 2026-06-13  Round 3 item 3 — Method × Matrix → unit map (confirmed)

- **Decision:** A `METHOD_MATRIX_UNIT_MAP` dict in `rules.py` defines the concentration unit
  for each method × matrix combination.  Confirmed values:
  EPA_537_1 (any water matrix) → ng/L;
  EPA_1633A (aqueous) → ng/L, (solid/sediment/soil) → ng/g dry wt, (tissue/fish tissue) → ng/g wet wt;
  FDA_32PFAS (meat/fish/egg/feed) → ng/kg wet wt, (milk) → ng/mL.
  Helper `get_unit_for_context(method, matrix)` retrieves the unit at runtime.
  The unit is used for QC type field labels and result reporting.
- **Status:** confirmed
- **Context:** User confirmed 2026-06-13: "FDA 32 PFAS should be ng/kg except for milk
  which is ng/mL."  Previous proposal used ng/g for FDA solids — corrected to ng/kg.

## 2026-06-13  Round 3 item 2 — Control chart type selector

- **Decision:** A "Chart Type" dropdown added to the control chart sidebar with options:
  `auto` (empty — derives chart type from QC type as before), `levey_jennings`, `threshold`.
  Stored as `chart_type_override` GET parameter.  The `selected_qc_type()` default changed
  from `"CCV"` to `""` so no QC type is forced on page load — user must explicitly select.
  When no QC type is selected, `chart_data()` returns an empty chart
  (same as no analyte selected).
- **Status:** confirmed
- **Context:** User (2026-06-13): "Enable the option to choose the type of control chart
  displayed — levy jennings vs threshold etc."  The selector is additive to the existing
  auto-derived behavior; it does not replace it.

## 2026-06-13  Round 3 items 1+6+8 — QC Rules page: SENAITE tokens, labels+units, slider toggles

- **Decision:** Three changes applied together to `qcrules.pt` / `qcrules.py`:
  1. (Item 8) Inline `<style>` block replaced with a `:root` CSS custom-property block
     using actual SENAITE 2.6 palette tokens pulled from
     `senaite.core-2.6.0/browser/static/bundles/senaite.core.css`.  Primary: `#428aaf`,
     dark: `#343a40`, body text: `#293333`, borders: `#dee2e6`, input border: `#ced4da`.
     All prior Material Design hand-picked colors (`#37474f`, `#1565c0`, `#eceff1`) removed.
  2. (Item 1) `GLOBAL_PARAM_META` and `QC_TYPE_FIELD_META` dicts added to `qcrules.py`.
     `global_fields()` and `qc_type_fields()` now return `label` and `unit` per field.
     Templates use `item/label` (human-readable string) and a `<span class="unit-label">`
     adjacent to each input.
  3. (Item 6) Checkbox + text-label toggles replaced with a pure-CSS slider toggle
     (`.toggle-switch` / `.toggle-track` — no JS for the visual state).  Client-side JS
     (`updateRuleVisibility`) auto-enables/disables the corresponding method-specific
     limit group when a toggle is flipped, with no page reload.
- **Status:** confirmed
- **Context:** qcrules.pt is the "one view" before/after for item 8; other standalone
  views (controlchart.pt, calibrations.pt, tracker.pt, pfas_dashboard_tiles.pt) will be
  restyled after the approach is confirmed.

---

## 2026-06-12  Round 2 item 4 — QC ruleset toggle grid

- **Decision:** The `@@pfas-qc-rules` page gains a "Rule Toggle Grid" section (rows = 14
  rules, columns = 3 methods, checkboxes) and a "Method-Specific Limits" section (tabbed
  by method, shows param editors for each rule with per-method override capability).
  Toggle state persists in `method_rule_toggles` inside `qc_rules.json`; param overrides
  persist in `method_overrides` (sparse — only keys that differ from global are stored,
  preserving the global→method inheritance chain).  The pipeline worker (`run_queue.py`)
  reads toggles at `auto_evaluate()` time and gates each engine check block by the
  corresponding `RULE_LIBRARY` key; the `LIBRARY_KEY_TO_ENGINE_CHECKS` mapping table in
  `rules.py` is the canonical cross-reference.  Rules with no automated engine check
  (ccv_frequency, mb_blank, surrogate_recovery, mdl_check) are UI-toggle-only: they
  control whether the check appears in the analyst review queue but have no engine flag
  block yet.  `run_pipeline()` accepts a new `method_id` parameter that flows to
  `RunQueue`.
- **Status:** confirmed
- **Context:** User confirmed (Round 2): "grid is an off toggle and then further qc is
  editable depending on method selected."  The starting toggle defaults in
  `DEFAULT_METHOD_RULE_TOGGLES` (e.g. `sn_min` off for FDA/537.1, `mdl_check` on for
  1633A) are *proposed defaults only* — all are UI-editable.  They are NOT based on
  previously-existing hardcoded behavior and must be verified by the lab before relying
  on them.

## 2026-06-12  Round 2 item 3 — Control chart method-type filter

- **Decision:** A "Method" dropdown is added as the first filter in the control chart
  sidebar, above QC Type.  Selecting a method scopes the analyte list to analytes
  with results under that method; the chart data query also filters by method.
  "All methods" (empty selection) shows combined data from all methods — existing
  behavior.  Method label is shown in the chart subtitle when a method is selected.
  The `QCResultStore.get_analytes()` now accepts a `method` parameter; a new
  `get_methods()` method returns distinct method IDs.
- **Status:** confirmed
- **Context:** User confirmed "selector that swaps method" approach.  Same analyte
  (e.g. PFOA) has different QC limits per method; separate per-method series is the
  correct scope for Levey-Jennings statistics.

## 2026-06-12  Round 2 item 2 — PFAS navigation tiles and sub-tabs

- **Decision:** 7 PFAS dashboard tiles (Batch Status, Control Charts, Calibrations,
  Method Profiles, QC Rules, Sample Tracker, Setup Ref Defs) rendered via a
  `IBelowContent` viewlet on `IPloneSiteRoot`.  Appears below the standard SENAITE
  dashboard panels without modifying SENAITE core code.  Sub-tabs: "PFAS Stage" on
  Worksheet and "Tracker" on AnalysisRequest, registered via `portal_actions` `object`
  category in `profiles/default/actions.xml` (purge=False, condition on portal_type).
- **Status:** confirmed
- **Context:** Viewlet uses `metal:use-macro="here/main_template/macros/master"` in
  the dashboard which includes `IBelowContent`.  Portal actions applied via
  `runImportStepFromProfile` probe script (must be re-applied after reinstall).

## 2026-06-12  Round 2 item 1 — UI rendering bugs found and fixed

- **Decision:** Two rendering bugs corrected:
  1. `@@pfas-sample-status` showed "No worksheets found" because `sort_on="created"`
     is incompatible with `senaite_catalog_worksheet` in SENAITE 2.6 (raises
     "an integer is required").  Fixed by removing the catalog-level sort and
     sorting the result list in Python by `created` string (ISO date, so
     lexicographic order is correct) after building it.
  2. `controlchart.pt` line 374 used `tal:content` (not `tal:content="structure"`)
     to embed JSON into a `<script>` tag.  Fixed to `structure` to prevent
     HTML-escaping of characters like `<`, `>`, `&` that could appear in
     future JSON payloads and would silently break the chart JavaScript.
- **Status:** confirmed
- **Context:** All 9 browser-view templates and the method-profile-edit view were
  inspected via HTTP — no raw TAL/template expression leakage found elsewhere.
  The `sort_on` bug is the root cause of the empty batch-status page.

## 2026-06-12  Stage 3 — anonymous access model for public tracker

- **Decision:** All SENAITE object reads in `@@pfas-track` are performed under
  an elevated security context (`AccessControl.User.UnrestrictedUser`) obtained
  via `newSecurityManager()`.  The security manager is always restored in a
  `finally` block.  Only a minimal public-safe dict (stage, stage_label, method,
  steps, estimate_text) is returned to the template — analyst names, sample IDs,
  and QC data are never included.
- **Status:** confirmed
- **Context:** `zope2.Public` on the view only makes the view class reachable;
  SENAITE objects are still ACL-protected.  Elevation is necessary because
  extraction-log stage transitions fire outside Zope (on the tablet) so full
  denormalization-at-event-time is insufficient to compute live stage.

## 2026-06-12  Stage 3 — tracking number format and assignment trigger

- **Decision:** Format `PF-YYMMDD-XXXX` (e.g. `PF-260611-A3K9`).  PF = lab
  prefix; YYMMDD = receipt date; XXXX = 4-char random uppercase alphanumeric
  (A-Z, 0-9).  Generated by a `DCWorkflow IAfterTransitionEvent` subscriber on
  the `receive` transition of `AnalysisRequest` objects.  Assignment is
  idempotent: a retract/re-receive cycle returns the existing number.  Stored in
  `IAnnotations(portal)[u'senaite.pfas.tracking']` (forward) and
  `IAnnotations(portal)[u'senaite.pfas.tracking.by_uid']` (reverse).
- **Status:** confirmed
- **Context:** User confirmed format (2026-06-12).  QR code on receipt links to
  `@@pfas-track?t={tracking_number}`.  Unicode literal keys used (as with Stage 1)
  to avoid Python 2 vs `instance run` key mismatch.

## 2026-06-12  Stage 3 — QR code generation (server-side, no external services)

- **Decision:** QR code is generated server-side using the `qrcode==6.1` Python
  package (Python 2.7 compatible) with the SVG path image factory.  Added to
  `setup.py install_requires`.  The generated SVG is embedded directly in the
  receipt HTML via `tal:content="structure view/qr_svg"`.  No external QR
  web services are used.
- **Status:** confirmed
- **Context:** `qrcode` was not pre-installed; added to setup.py and installed
  in the running container via `pip install qrcode==6.1`.

## 2026-06-12  Stage 3 — time estimates (historical averages, n=3 minimum)

- **Decision:** Per-method per-stage estimates computed from completed
  (state=verified) worksheets.  Stage 4 duration: WS submit→verify from
  workflow_history.  Stages 2/3 additionally use extraction log timestamps.
  Minimum 3 data points required before an estimate is emitted; below this
  threshold "estimate not available" is shown instead of a misleading number.
  Stage 1 and Stage 5 are not estimated (no reliable start time for Stage 1;
  per-AR variation in Stage 5 makes aggregation non-obvious).
- **Status:** confirmed
- **Context:** Graceful degradation required: the instance starts with zero
  worksheets so n=0 is expected for a period after launch.

## 2026-06-12  Stage 3 — 16-bit scientist animations (5 scenes, CSS animated SVG)

- **Decision:** Each of the five stages displays a distinct inline SVG scene
  featuring a pixel-art style lab scientist character with a stage-appropriate
  prop (sample box, Erlenmeyer flask, mass spec instrument, laptop+chart,
  report document).  CSS `@keyframes` animations run in the browser (no JS).
  User confirmed the "16-bit style scientist that changes each stage" design
  (2026-06-12).
- **Status:** confirmed
- **Context:** All five SVG scenes are embedded as Python string constants in
  `browser/tracker.py` and output via `tal:content="structure ..."` in the
  template.  No external assets required.

---

## 2026-06-11  Stage 2 — batch status view design

- **Decision:** Primary unit is the SENAITE Worksheet (instrument run batch).
  Stage is a pure function of worksheet workflow state + extraction log;
  never stored as a separate field.  Mixed analysis states use least-advanced
  wins (the worksheet FSM enforces this naturally).  Extraction log matching:
  the `batch_id` used in POST /log/start must equal the SENAITE Worksheet ID
  (e.g. WS-001); the log file is `{EXTRACTION_LOG_DIR}/{batch_id}_extraction.json`.
- **Status:** confirmed
- **Context:** User confirmed (2026-06-11): per-batch view, extraction log for
  stage detection, least-advanced wins for mixed states.

## 2026-06-11  Extraction log ↔ Worksheet ID coupling

- **Decision:** The `batch_id` the analyst enters on the prep-room tablet (POST
  /log/start) must equal the SENAITE Worksheet ID (e.g. `WS-001`).  The log
  file is stored as `{EXTRACTION_LOG_DIR}/{worksheet_id}_extraction.json`.
  No mapping table is needed.  Analyst looks up the WS ID in SENAITE before
  starting extraction.
- **Status:** confirmed
- **Context:** Confirmed by lab 2026-06-11.  This is a process convention, not
  enforced by code — if the wrong ID is entered, the batch stays at Stage 1
  (Received) until the log file name matches.

## 2026-06-11  Stage detection algorithm (five stages → workflow state)

- **Decision:**
  - Stage 1 Received:      ws state `open` + no extraction log in `/data/extraction_logs/`
  - Stage 2 Extraction:    ws state `open` + log exists, `completed` field is null
  - Stage 3 On Instrument: ws state `open` + log exists, `completed` field is set
  - Stage 4 QC Review:     ws state `to_be_verified`; OR ws state `verified` but no AR published
  - Stage 5 Report Pub.:   ws state `verified` + at least one linked AR in `published` state
  Responsible person for Stages 1–3: extraction log `analyst` (or ws analyst if no log).
  Responsible person for Stage 4: actor who performed the `submit` worksheet transition.
  Responsible person for Stage 5: worksheet analyst.
- **Status:** confirmed
- **Context:** SENAITE has no native extraction stage; file-based log is the signal.

---

## 2026-06-11  confirm-ion toggle per method

- **Decision:** `require_confirm_ion_check` is a method-level toggle stored in
  each Method Profile's `confirmation` section.  Default: ON for FDA 32-PFAS
  and EPA 1633A; OFF for EPA 537.1.
- **Status:** confirmed
- **Context:** User confirmed the qualifier-ion check is required for FDA and
  1633A but not 537.1.  Implemented as a boolean field in the profile so the
  lab can flip it per method without code changes.

---

## 2026-06-11  PFBA/PFPeA confirmation — no HRMS needed

- **Decision:** PFBA (213.04>18.99) and PFPeA (263.01>18.99) have the m/z 18.99
  fluoride fragment as their qualifier transition and are confirmed on the
  standard QqQ.  No LC-HRMS instrument is required.  The `single_transition_analytes`
  field in the FDA_32PFAS profile is empty (these analytes do have qualifier MRMs).
- **Status:** confirmed
- **Context:** Verified by user and from analytes.py qual_mrm lists.  Corrects
  an earlier inventory error (items #52-53) and a bug in
  pfas_pipeline/method_profiles.py FDA32PFASProfile.confirmation_rule() which
  listed PFBA/PFPeA as needing HRMS confirmation.  The correct values will be
  served from the Method Profile once the UI is live.

---

## 2026-06-11  ZODB PersistentMapping (Option 2) for Method Profile storage

- **Decision:** Store per-method QC profiles as JSON strings in a
  PersistentMapping attached to the portal via IAnnotations.
  Key: `senaite.pfas.method_profiles`.  Each entry: `method_id → json_string`.
  On every save, also export `/data/qc/method_profiles.json` for the pipeline worker.
- **Status:** confirmed
- **Context:** Avoids Archetypes/RecordsField complexity in Python 2.7.
  Replacing the entire JSON string on save avoids nested-persistence dirty-marking.
  Worker reads from the exported file; falls back to hardcoded defaults if absent.

---

## 2026-06-11  Reference Definitions are one-way synced FROM Method Profile

- **Decision:** SENAITE Reference Definitions are populated from the Method
  Profile (source of truth).  Direct edits to a RefDef in SENAITE's native UI
  are overwritten on the next sync.  Managers who want to change a criterion
  must edit the Method Profile, not the RefDef directly.
- **Status:** confirmed
- **Context:** Necessary to maintain a single source of truth.  The one-way
  sync property is documented here so it is a known design property, not a
  future surprise.

---

## 2026-06-11  MDL constants stay in code

- **Decision:** `MDL_MIN_REPS = 7`, `MDL_T_CONFIDENCE = 0.99`, and the pre-computed
  t-table values (EPA 40 CFR Part 136 Appendix B) remain hardcoded in
  `pfas_pipeline/constants.py`.  They are EPA statistical constants, not lab
  choices, so there is no value in making them UI-editable.
- **Status:** confirmed
- **Context:** User agreed: "MDL assessment table should stay, although this is
  a simple t-test and the values are based off number of samples."

---

## 2026-06-11  All reference data (surrogate maps, analyte classifications,
              MRM assignments) must be UI-editable

- **Decision:** Even "reference" data — surrogate maps, analyte-to-tier
  assignments, IS MRM transitions, confirmatory ion assignments — must be
  editable via the Method Profile control panel.  The system must support
  adding entirely new test methods without code changes.
- **Status:** confirmed
- **Context:** User: "if I wanted to add more test methods I want to be able to
  add more or configure for different tests.  The idea is to make a truly
  buildable system."

---

## 2026-06-11  Live production QC engine identified

- **Decision:** The live production QC engine is `pfas_pipeline/qc_engine.py`,
  not `src/senaite/pfas/qc/engine.py`.  The execution path is:
  `run_worker.py → pfas_pipeline/pipeline.py → pfas_pipeline/run_queue.py →
  pfas_pipeline/qc_engine.py`.  The engine reads from `CRITERIA` dict in
  `pfas_pipeline/constants.py`.  Config changes must reach that dict.
- **Status:** confirmed
- **Context:** Traced from run_worker.py; verified that run_queue.py imports
  from `.qc_engine`, not from `senaite.pfas.qc.engine`.
  `src/senaite/pfas/qc/engine.py` uses Python 3 syntax (dataclasses, f-strings)
  and is never imported by the Plone add-on — it is either dead code or an
  earlier draft superseded by `pfas_pipeline/qc_engine.py`.

---

## 2026-06-14  Item 8 — Guided Import Studio design (three decisions)

- **Decision (a):** Instrument mapping profiles stored as JSON blobs in ZODB
  annotations on the SENAITE Instrument object
  (`IAnnotations(instrument)["senaite.pfas.instrument_profiles"]`), keyed by
  software version string.
- **Decision (b):** Software version auto-detected by scanning the first 20 lines
  of the uploaded file for a version string (`X.Y.Z`); the detected value is
  pre-populated but analyst-editable before saving the profile.
- **Decision (c):** Pipeline worker writes results back to SENAITE via the REST
  API (`senaite_connector.py`), not via direct `AnalysisResultsImporter` import.
  The mapping profile is fetched by the pipeline from the Instrument object
  via REST.
- **Status:** confirmed
- **Context:** Separates the Python 3 pipeline from the Python 2.7 Plone add-on;
  keeps all UI in SENAITE; avoids Plone's AT import infrastructure.

---

## 2026-06-14  Item 9 — Reagent Inventory design

- **Decision (a):** Reagent records stored in ZODB portal annotations
  (`IAnnotations(portal)["senaite.pfas.reagents"]`) as a `PersistentMapping
  {uid_hex: json_string}`. Multiple records per catalog number are supported:
  each lot number is a distinct record sharing the same `cat_number` field.
- **Decision (b):** Barcode scanning uses ZXing-js (browser-only webcam).
  USB HID scanners work natively by typing into the Lot Number text field.
- **Decision (c):** OCR fallback uses Tesseract.js (browser-only). The analyst
  captures a still frame from the webcam; Tesseract extracts the text for
  copy-paste into the form.
- **Decision (d):** Expiry calculation from open date: 7 days for mobile phases
  (name matches `/methanol|meoh|acetonitrile|acn|water|h2o|mobile.?phase|mph|formic/i`),
  1 year for all others. Manufacturer expiry takes precedence when provided.
- **Decision (e):** FM-ENV-250 Chemicals table gains a "From Inventory" button
  that calls `@@pfas-reagents?action=lookup_json&q=...` and pre-fills rows.
- **Status:** confirmed
- **Context:** ISO 17025 / MLAB lot and expiry tracking requirement; eliminates
  manual re-entry of catalog/lot/expiry data across logbooks.

---

## 2026-06-14  Item 10 — Guided Extraction Interface design

- **Decision (a):** Extraction stages are configurable per method in the Method
  Profile (`extraction_stages` array in the profile JSON). Default stages are
  seeded for FDA_32PFAS (8 stages), EPA_537_1 (8 stages), and EPA_1633A
  (7 stages). Managers can add/edit/reorder stages without code changes.
- **Decision (b):** Session state (stage progress, reagent lots confirmed,
  solutions prepared, pedigree) stored in ZODB annotations on the Batch:
  `IAnnotations(batch)["senaite.pfas.extraction_session"]` as a JSON string.
- **Decision (c):** PDF generated server-side by ReportLab (`reportlab>=3.0,<3.4`,
  last series with Python 2.7 support). Added to `setup.py install_requires`.
  Graceful error message if not yet installed in Docker image.
- **Decision (d):** Label printer (`@@pfas-label`) is a standalone HTML page
  with selectable or fully custom size (width × height in mm). JsBarcode renders
  CODE128 barcodes client-side. Analyst uses browser Ctrl+P to send to label
  printer.
- **Decision (e):** Label generator accessed from within the extraction guide
  (per solution prepared) and standalone from the reagent inventory. Labels are
  printable on any standard label printer via browser print dialog.
- **Status:** confirmed
- **Context:** ISO 17025 / MLAB traceability requirements; guided workflow
  replaces paper-based FM-ENV-252 with an auto-populated, PDF-exportable record.

---

## 2026-06-17  Round 9 Decision A — MRM transitions excluded from analyte library

- **Decision:** MRM transitions (quantifier m/z and qualifier m/z list) are NOT
  stored in `analyte_reference.py`. They belong to instrument acquisition methods
  and are managed separately. `analyte_reference.py` gains an `is_key_analyte`
  boolean as its 9th tuple field to identify the four regulatory priority analytes
  (PFOS, PFOA, PFHxS, PFNA) and their branched isomers. `analytes.py` retains MRM
  data for now; `KEY_ANALYTES` and `NON_ISO_ANALYTES` are derived from
  `analyte_reference.py` is_key_analyte / no_labeled fields.
- **Status:** confirmed
- **Context:** Audit of data duplication across analyte library files (Round 9
  schema audit). MRM values are method/instrument-specific parameters, not intrinsic
  analyte identity.

---

## 2026-06-17  Round 9 Decision B — EPA 537.1/1633A analyte sets remain UI-editable placeholders

- **Decision:** EPA 537.1 and EPA 1633A analyte sets in `method_profile_store.py`
  are seeded from the FDA 32-analyte set as placeholders, clearly flagged
  `NEEDS_LAB_VERIFICATION`. The UI allows managers to edit these sets without code
  changes. The placeholder warning is visible in the profile editor.
- **Status:** confirmed
- **Context:** Lab has not yet confirmed the exact EPA 537.1/1633A reportable analyte
  lists from their purchased method copies. Conservative default is to include all 32
  FDA analytes until verified.

---

## 2026-06-17  Round 9 Decision C — All QC rule logic data-driven from stored profile JSON

- **Decision:** ALL recovery tier logic, matrix-conditional thresholds, CCV
  frequency, r² values, and IS limits for ALL three methods (FDA 32-PFAS, EPA 537.1,
  EPA 1633A) are read from the stored profile JSON at batch start. Python
  `MethodProfile` classes in `pfas_pipeline/method_profiles.py` are rule-engine
  interpreters, not sources of hardcoded values. Module-level constants `_FDA_BIG4`,
  `_FDA_NO_LABELED_STD`, `_FDA_TIGHT_MATRICES` are removed and replaced with
  lookups into `_profile_data_cache` loaded from `/data/qc/method_profiles.json`.
  The QCCriteria class in `analytes.py` (already dead code — engine.py uses
  `_LiveCriteria()`) is removed.
- **Status:** confirmed
- **Context:** Core requirement of Round 9. Hardcoded thresholds are the #1 defect
  per CLAUDE.md §0. This decision applies to ALL methods, not just FDA 32-PFAS.

---

## 2026-06-20  Integration architecture — Option A confirmed

- **Decision — Option A (deep integration, add-on stays as add-on):** PFAS components
  become first-class SENAITE citizens via SENAITE's own extension mechanisms (Dexterity
  content types + catalog registration + audit behaviors + workflow guards). We do NOT fork
  `senaite.core` source. Rationale: CLAUDE.md §1 Rule 2 ("Build ON the existing
  architecture"); forking would require manual merge of every upstream SENAITE security
  patch forever. The "one unified database" goal is achieved by migrating PFAS data from
  portal annotations and flat files into proper SENAITE content objects indexed in
  `senaite_catalog_setup` and participating in the audit trail.
- **Finding:** Existing Dexterity types (`Reagent`, `EnvironmentalReading`) are NOT
  currently catalog-indexed — no `catalog.xml` in GenericSetup profile, no SENAITE
  audit behaviors. The Dexterity class exists but `reagents.py` stores data in
  `IAnnotations(portal)["senaite.pfas.reagents"]`, bypassing the content type entirely.
  Same pattern holds for ALL PFAS data stores. This confirms the migration scope.
- **Migration Unit 1 (approved):** Wire the existing `Reagent` Dexterity type into
  SENAITE's infrastructure as a proof-of-pattern: add SENAITE catalog behaviors, register
  in `catalog.xml`, migrate existing annotation records to actual content objects, update
  `reagents.py` to CRUD Dexterity content objects. Verify Reagent appears in SENAITE
  search and audit log before extending pattern to `PFASMethodProfile` etc.
- **Status:** confirmed — architectural direction approved; Migration Unit 1 approved;
  panel shell built simultaneously (see panel shell decision below)

## 2026-06-20  Panel layout — Phase 1 panel shell built (Decision #1 executed)

- **Decision #1 (executed):** Subnav strip (`.pfas-subnav`, the horizontal 6-link nav
  below the header in `pfas_macros.pt`) removed and superseded by a persistent left
  panel. Confirmed by user: "yes delete it & superseded with the left panel."
- **Panel shell:** `pfas_macros.pt` rebuilt with §6 layout:
  - `.pfas-header` (52px, dark) — hamburger toggle + title + header-right slot
  - `.pfas-left-panel` (220px dark sidebar) — collapses to 48px icon rail on
    `panel-collapsed` class; mobile uses overlay with backdrop
  - `.pfas-main` — flex column containing tabs + content + action bar
  - `.pfas-tabs-wrap` — new `tabs` slot; default renders nothing (no visible bar)
  - `.pfas-content-area` — `flex: 1; overflow-y: auto` — the stable scrollable area
  - `.pfas-action-bar-wrap` — new `action-bar` slot; outside scroll area, always pinned
- **New slots defined:** `left-panel`, `tabs`, `action-bar` (all default to empty/hidden)
- **Backward compat preserved:** All existing slots (`header-title`, `header-right`,
  `head-extra`, `content`) remain with unchanged names. Existing pages still render
  correctly; their `.save-bar` elements continue to work as sticky inside the scroll area.
  New pages should use `action-bar` slot for pinned save/cancel.
- **Default left-panel:** Six existing PFAS tools as nav items (in three section groups:
  QC & Method, Workflow, Reporting). These will be overridden per workspace in Phase 2+.
- **JavaScript:** `pfasTogglePanel()` handles desktop collapse (sessionStorage persisted)
  and mobile overlay open/close. Escape key closes mobile panel. Inline, no external deps.
- **Upgrade fragility:** None — `pfas_macros.pt` is a PFAS-owned template; no SENAITE
  core template is overridden by this change.
- **Status:** confirmed and implemented

## 2026-06-20  Architecture cleanup — confirmed decisions executed

- **Decision (E) — Delete `src/senaite/pfas/qc/engine.py`:**  
  File was Python 3 (dataclasses, f-strings, union type syntax) and cannot run inside
  Plone (Python 2.7). Nothing imported it at runtime. Deleted. `qc/__init__.py`
  cleaned up to not reference it. Active engine is `pfas_pipeline/qc_engine.py`.
  Status: **executed**

- **Decision (F) — Remove `global` block from `qc/rules.py`:**  
  `DEFAULT_RULES["global"]` (11 instrument criteria keys) removed. `LiveCriteria`
  class removed (its only consumer was `qc/engine.py` now deleted). `QCRulesStore.get_global()`
  removed. `setuprefs.py` updated to use `qc_types["CAL"/"ICV"]["pct_deviation_max"]` 
  and hardcoded defaults (20.0 tight / 25.0 default) instead of global lookups.
  `calibrations.py` reads of `rules.get("global", {})` now silently return `{}` and
  fall through to hardcoded defaults — behaviorally unchanged; method-aware fix deferred.
  Status: **executed**

- **Decision (G) — Dup spike-level RPD removed:**  
  Field Duplicate (Dup) is unfortified — no spike concentration concept applies.
  `qc_grid.py _apply_rpd_tiers()` now only processes `("LFSMD",)`, not `("LFSMD", "Dup")`.
  Template `qc_grid.pt` spike-level row condition changed from `col['criterion'] == 'rpd'`
  to `col['criterion'] == 'rpd' and col['code'] == 'LFSMD'`. Label updated.
  Status: **executed**

- **Decision (H) — `enabled` flags removed from pipeline bootstrap cache:**  
  `_DEFAULT_PROFILE_CACHE` in `pfas_pipeline/method_profiles.py` cleaned: all `"enabled": True`
  keys removed, all `"enabled": False` entries (LFB/FDA, LCS/537.1, LCS/1633A) removed
  (absence = disabled, consistent with ZODB model). Logic code retains `.get("enabled", True)`
  backward-compat for any existing JSON with old keys.
  Status: **executed**

- **Decision (I) — PFTrDS and PFUnDS CAS numbers assigned:**  
  PFTrDS: CAS 791-563-89-8 → stored as `791563898`, PARAMETER_NAME `PFTRDS_A`.
  PFUnDS: CAS 749-786-16-1 → stored as `749786161`, PARAMETER_NAME `PFUNDS_A`;
  note: verify against Maine EGAD CAS_LUP before EDD submission.
  `egad_store.py DEFAULT_ANALYTE_CAS` updated; `get_analyte_cas()` auto-fills empty
  entries from updated defaults on next read. Lab must click Save CAS Mapping to persist.
  Status: **executed** (pending lab Save CAS Mapping click)

## 2026-06-21  Migration Unit 2 — LogbookDef Dexterity content type

- **Decision:** Migrate logbook definitions from `IAnnotations(portal)["senaite.pfas.logbook_defs"]`
  (a JSON-encoded list) into `LogbookDef` Dexterity content objects living in
  `portal/pfas_logbook_defs/`.  Each definition becomes one `LogbookDef` object
  whose Zope id is the slug (e.g. "250", "custom-abc123").

- **Rationale:** Same as Reagent (Migration Unit 1): first-class content participates
  in the SENAITE audit log, inherits role/permission model, and is indexed in
  `senaite_catalog_setup`.  Ordering is preserved via a `sort_order` Int field;
  built-in slugs (250–253) cannot be deleted by the CRUD layer.

- **Files changed:**
  - `content/logbook_def.py` — `ILogbookDef` schema + `LogbookDef` class (new)
  - `profiles/default/types/LogbookDef.xml` — Dexterity FTI (new)
  - `profiles/default/types.xml` — added LogbookDef entry
  - `logbook_store.py` — CRUD rewritten to use Dexterity objects; falls back to
    annotation store transparently until `pfas_logbook_defs/` folder is created
  - `setuphandlers.py` — `setup_logbook_defs_catalog()` and
    `migrate_logbook_defs_from_annotations()` added; called from `post_install()`

- **Public API unchanged:** `get_logbook_defs`, `get_active_logbook_defs`,
  `save_logbook_defs`, `seed_defaults`, `is_builtin` — same signatures; all
  callers in `browser/logbooks.py` and `setuphandlers.py` continue to work.

- **Status:** implemented

---

## 2026-06-21  Phase 2 — Sidebar architecture (Phase 0 decisions confirmed)

**Decision: Single persistent accordion sidebar on ALL pages (core + PFAS)**
Confirmed answers:
1. CONFIGURATION sub-links use `@@lims-setup#group-id` anchors.
2. Option B — remove PFAS dark sidebar simultaneously in Phase 1; PFAS workspace
   pages call `context/@@pfas-sidebar` from within `pfas_macros.pt` so both
   core and PFAS pages use the same sidebar HTML.
3. Samples URL = `{portal}/@@samples`.

**Override mechanism:** Register `PFASSidebarManager` (subclass of
`SidebarViewletManager`) on `ISenaitePFASLayer` in `overrides.zcml`. Layer
specificity selects our manager over core's on `ISenaiteCore`. The manager's
`render()` wraps `@@pfas-sidebar` inner HTML in `<nav id="sidebar" class="bg-light">`.
`@@pfas-sidebar` is a BrowserView that renders the accordion groups. On PFAS
workspace pages (`pfas_macros.pt`), the left-panel slot calls
`context/@@pfas-sidebar` directly (main_template is bypassed for PFAS pages).

**Core templates wrapped (upgrade-fragility notes):**
- `SidebarViewletManager.render()` and `available()` — document changes on
  senaite.core upgrade.
- No core Python files edited; only a layer-specific viewlet manager registered.

**Phase 1 build sequence:** (1) `sidebar.py` + `pfas_sidebar.pt`, (2) register
in ZCML, (3) update `pfas_macros.pt` to call `@@pfas-sidebar` and remove dark
panel CSS, (4) verify on both core page and a PFAS workspace page.

---

## 2026-06-22  CoA fetching strategy

**Decision: D3 superseded — hybrid UI-helper + workstation automation script**

Original D3 ("Manual upload only") is superseded. Two-part approach:

1. **In-SENAITE UI helper** (`+CoA` modal): opens a modal with the reagent's cat#
   and lot# as one-click copy fields plus direct links to each supplier's CoA
   search page. No server-side HTTP. User finds/downloads in their browser and
   uploads via the modal's Upload tab.

2. **Standalone workstation script** (`scripts/fetch_coa.py`, Python 3 +
   Playwright): automates a real Chromium browser from an admin workstation to
   fill in supplier CoA search forms and download PDFs, then POST them to
   SENAITE via the existing `@@pfas-reagents?action=upload_coa` endpoint.

**Why no server-side scraper:** Both Sigma-Aldrich and Fisher Scientific block
server/datacenter IPs at the network level and use Akamai Bot Manager JS
challenges. Simple urllib2 gets timeouts (Sigma) or 403+JS-challenge (Fisher).
A real browser running from a workstation passes naturally.

**Why not official API keys yet:** Both suppliers offer authenticated REST APIs
(`developer.sigmaaldrich.com`, `connect.thermofisher.com`). When the lab
registers and receives keys, they go in env vars `SIGMA_API_KEY` /
`FISHER_API_KEY`; the `fetch_coa.py` script has stubs for these paths.

**Blocking concern flagged (CLAUDE.md §7):** If/when server-side HTTP fetch is
added (after API key), the call happens inline in a Zope request thread (no
Python 3 out-of-process worker available in the container). This blocks the
worker thread for up to the HTTP timeout. Mitigate with a short timeout (10 s)
and async-style error handling.

---

## D17 — PrepLogbookDef absorbs the logbook registry (2026-06-22)

**Decision:** PrepLogbookDef is the single source of truth for BOTH the
field schema AND the batch logbook index (ordering, active/inactive, form
codes, builtin flag). The parallel LogbookDef content type (`pfas_logbook_defs/`)
is retired. logbook_store.py is now a thin adapter over PrepLogbookDef.

**Fields added to IPrepLogbookDef:** `method_slug`, `logbook_code`,
`field_schema_json`, `sort_order`, `active` (Bool — shows in batch index),
`builtin` (Bool — built-ins cannot be deleted).

**Context:** Two parallel registries (LogbookDef + PrepLogbookDef) created a
two-registry collision. User confirmed "PrepLogbookDef absorbs everything."

---

## D18 — field_schema_json field types (2026-06-22)

**Decision:** Dynamic logbook renderer supports these field types in
`field_schema_json`:

| type | Renders as |
|------|-----------|
| `text` | `<input type="text">` |
| `date` | `<input type="date">` |
| `number` | `<input type="number">` |
| `textarea` | `<textarea>` |
| `lot_ref` | text + autocomplete from PreparedStandards (filtered by `lot_type`) |
| `reagent_ref` | text + autocomplete from Reagent Inventory |
| `checkbox` | `<input type="checkbox">` |
| `table` | add/remove rows; each column typed; `default_rows` pre-populates |

Add `"correctable": true` to any field for GLP correction support
(uses existing `_apply_field_corrections` logic unchanged).

---

## D19 — Dynamic renderer routes via field_schema_json presence (2026-06-22)

**Decision:** `PFASLogbookIndexView.logbooks()` checks whether the
PrepLogbookDef for a slug has a non-empty `field_schema_json`. If yes,
routes to `@@pfas-logbook-dynamic?slug=<slug>`. If no (and builtin),
falls back to hardcoded `@@pfas-logbook-<slug>`. Custom logbooks without
a schema go to `@@pfas-logbook-custom?slug=<slug>`.

This means the four built-in logbooks (250/251/252/253) will begin routing
to the dynamic renderer as soon as `seed_builtin_logbook_defs()` runs and
populates their field_schema_json. The hardcoded PT views are kept as a
fallback until the dynamic renderer is browser-verified for all four.

---

## D20 — FM-ENV-251 side-effect preserved in dynamic renderer (2026-06-22)

**Decision:** `PFASDynamicLogbookView._handle_post()` special-cases
`slug == "251"` to call `_export_cal_to_file(batch, data)` after save,
preserving the pipeline injection builder hook. The CSV download
(`@@pfas-logbook-251` + `?action=download_csv`) remains accessible via the
hardcoded view for backward compatibility until the dynamic renderer has an
equivalent export button.

---

## D21 — Active vs. Status on PrepLogbookDef (2026-06-22)

**Decision:** Two distinct boolean concerns are tracked separately:
- `status` (draft/active/archived) — tracks SOP revision lifecycle for the
  logbook TEMPLATE. "active" = current approved revision.
- `active` (Bool field) — controls whether this logbook SLUG appears in the
  batch logbook index. These are independent: a lab manager can hide a logbook
  from batches (`active=False`) without archiving its SOP revision.

`get_active_logbook_defs()` filters by `d.get("active", True)`; it does NOT
filter by `status`.

## D22 — Core UI unification via CSS overlay + mobile table-scroll (2026-06-30)

**Context:** Two requests: (1) fix mobile so wide objects scroll sideways
inside their own box instead of dragging the whole page; (2) apply the PFAS
look to core SENAITE pages. Chosen mechanism (user sign-off): **global CSS
overlay** targeting core's existing markup. Scope (first pass): **Sample /
Batch / Worksheet listings** (all render as `table.contentstable` via
senaite.app.listing).

**PFAS-page mobile fix (fail-safe, per advisor):**
- Did NOT clamp `.pfas-content-area` to `overflow-x:hidden` (fail-UNSAFE —
  clips any wide object lacking its own scroll box). Instead each wide object
  self-scrolls; once it does, it no longer expands the content area, so the
  page stops dragging without touching `.pfas-content-area`.
- Wrapped the 4 actually-wide tables (verified at 375px via Playwright) in the
  existing `.table-wrap`: `deviations.pt` (.dev-table), `reagents.pt`
  (.rg-table), `sop_documents.pt` (.sop-table), `setuprefs.pt` (.ref-table).
- Generalized the macro mobile rule from `.table-wrap .pfas-table` to
  `.table-wrap table` (nowrap cells + `.col-wrap` opt-out) so any wrapped
  table scrolls cleanly. The other ~19 PFAS pages were already clean.

**Core overlay (NEW, upgrade-safe layer — flag for upgrade checks):**
- `browser/static/pfas-core-overlay.css` — restyles `table.contentstable`
  headers/hover, `.btn-primary`/`.btn-outline-primary`, `.alert-info`/
  `dl.portalMessage.info`, and listing status badges into the PFAS palette;
  and on ≤768px makes `table.contentstable` self-scroll (Bootstrap
  table-responsive pattern: `display:block;overflow-x:auto;white-space:nowrap`
  with `thead/tbody{display:table;width:max-content;min-width:100%}`).
- Worksheets-only: `.worksheet_add_controls .input-group.flex-nowrap`
  (the Create/analyst/template/instrument toolbar, a `d-inline-flex.w-auto`
  Bootstrap input-group) gets `flex-wrap:wrap; max-width:100%` on mobile so it
  stacks instead of forcing page width.
- Token values (`--s-*`) are duplicated into the overlay `:root` because core
  pages do not load `pfas_macros.pt`. **Keep in sync with pfas_macros.pt.**
- Injected via a `plone.htmlhead` viewlet (`name="senaite.pfas.core-overlay-css"`,
  `template=templates/core_overlay_link.pt`) registered on
  `ISenaitePFASLayer` in `browser/configure.zcml`. No core `.pt` is forked;
  reversible by removing the viewlet registration.
- **Upgrade fragility:** depends on core class names `table.contentstable`,
  `.worksheet_add_controls`, Bootstrap utilities (`.flex-nowrap`,
  `.btn-primary`), and the `IHtmlHead` viewlet manager. Re-verify these on any
  senaite.core / Bootstrap bump.
- **Resource caching:** Zope caches the resourceDirectory file; editing the
  CSS requires a container restart to serve the new content.

**Verification:** Playwright at 375px — samples/batches/worksheets all
`doc_drag=False` (docScrollW=375); desktop (1280px) tables remain
`display:table`, worksheet toolbar remains `nowrap`, no regression.

## D23 — Core header dropdowns clipped on mobile (2026-06-30)

**Symptom:** On core SENAITE pages at ≤768px, the top navbar dropdowns (apps /
language / user) were clipped by the bar and/or rendered behind the content
below (e.g. the breadcrumb covered them).

**Root cause:** `pfas_sidebar.pt`'s ≤768px block set `overflow: hidden` on
`#senaite-toolbar` (the core `.navbar.static-top`) to keep the toolbar on a
single row. `overflow:hidden` clips on BOTH axes, so the dropdown menus — which
extend vertically below the bar — were cut off. The navbar also had no stacking
context, so its `z-index:1000` menus lost to page content.

**Fix (in pfas_sidebar.pt, the source — not the overlay):**
```
#senaite-toolbar { overflow-x: clip; overflow-y: visible;
                   position: relative; z-index: 1030; }
```
`overflow-x:clip` keeps the single-row horizontal containment intent;
`overflow-y:visible` lets dropdowns escape downward; `z-index:1030` (Bootstrap's
navbar level) puts the menus above page content.

**Verified (Playwright):** 768px & 1280px — user dropdown opens at top:54 (just
below the bar), `shows:true`, no page drag, toolbar stays single-row.

**Known minor quirk (pre-existing, not fixed):** at 375px the tall user menu is
anchored by Bootstrap Popper slightly over the bar top, clipping the first item
against the viewport edge. This is core SENAITE's Popper positioning (the
`overflow:hidden` previously hid it entirely); the menu now displays over
content. A Popper-offset override would be fragile, so left as-is pending need.

## D24 — CAS single-source + core-connectivity finding (2026-07-01)

**Context:** Audit D2 (CAS duplicated) + user request to "ensure greater
connectivity to the core system."

**Key discovery:** SENAITE 2.6 core `AnalysisService` has **no CAS field** (none
in `bika.lims/content`). So CAS cannot live on the core object; it legitimately
lives in the add-on, and the **join to core is the AnalysisService keyword**.
This reframes "connectivity to core" for CAS: not a shared field, but a shared
key.

**Decision:**
- `analyte_reference.NATIVE_ANALYTES` is the **single source of truth** for
  analyte CAS. New accessor `get_cas_by_keyword(dashed=False)`.
- `egad_store` no longer hardcodes CAS. `DEFAULT_ANALYTE_CAS` is built from
  `_EGAD_ANALYTE_OVERLAY` (EGAD-specific: parameter_name, override_note, and
  `cas_override` only where EGAD uses a Maine DEP##### code or the master has no
  usable CAS) layered over the master. 29/34 CAS values now derive; 5 overrides
  remain (PFHxS/PFOS/br-PFHxS/br-PFOS DEP codes + PFTrDS placeholder-drift).
- **Verification bar:** rebuilt `DEFAULT_ANALYTE_CAS` byte-identical to the old
  hardcoded dict (34/34) and `get_analyte_cas()` output unchanged. Regulated EDD
  output provably identical — this was the safety gate, not a spot check.

**Also fixed (D5):** `setuphandlers` called non-existent `svc.setCASNumber()`
inside a silent `try/except`, which had been failing every install AND blocking
the subsequent `setPrecision()`. Removed; precision now seeds.

**Not changed (scope):** `analyte_reference.cas` is dashed; egad derives undashed.
The setupdata CSV (`analysis_services.csv`) still carries its own CAS column used
only for service identity display — a future cleanup could regenerate it from the
master, but it is not read for the EDD so it is not a live drift risk.

**Upgrade note:** if a future SENAITE core adds a CAS field to AnalysisService,
revisit — core could then become the CAS owner, seeded from the master.

## D25 — Siloed-list consolidation + D1 re-diagnosis + D4 plan (2026-07-01)

**Context:** "Connect the orphaned/siloed lists" + produce a 3-layer system SVG.

**Deliverable:** `senaite_pfas_map.svg` — standalone SVG, three named layers
(user entry points by role → add-on parts → core SENAITE services), legend
inside. Replaces the PNG as the canonical system diagram.

**Facts-vs-presentation rule applied:** consolidated only *facts* (single-source
per §1.3); left view-local enums alone (LABEL_SIZES, RISK_COLOURS, STEP_META,
SETUP_GROUPS, PURPOSES, QC_COLUMNS).

**Applied (all byte-identical verified):**
- D6: `STANDARD_TYPES` / `REAGENT_CATEGORIES` — `content/` owns, `browser/`
  imports (browser name IS the content object).
- D7 (partial): `analyte_reference.get_method_ids()` = single source for method
  IDs; `qc.rules.METHODS` derives from it (labels stay local). Byte-identical.

**D1 re-diagnosed (important):** `qc/control_chart.py` is **Python 3**
(`@dataclass`, `typing`) — the Py2.7 Plone process cannot import it
(SyntaxError, verified). It is the out-of-process worker's engine (§7); the
Py2.7 view reimplements the *same* rules (equivalent: same 6 Westgard rules +
same n-1 limit formula). NOT dead code, NOT a compliance gap, NOT wireable
across runtimes. Fix = extract thresholds to a Py2/3-safe constants module
(deferred; regulated chart path needs byte-identical verification).

**D4 staged (not executed):** matrix-string→SampleType-UID is a data-model
change with a migration; plan recorded in SYSTEM_AUDIT.md §6. Behind a
`matrix_ref` resolver so it lands incrementally, backward-compatible.

**Scope discipline:** did not big-bang the regulated pipeline (D4) or the
regulated chart (D1); both staged with verification gates.

## D26 — matrix_ref resolver (D4 foundation) + method-ID D7 + D1 decision (2026-07-01)

**D7 continued:** `qc_grid.GRID_METHODS` now derives from
`analyte_reference.get_method_ids()` (byte-identical, verified). Remaining
method-keyed items are *data* not duplicated lists (`DEFAULT_METHOD_EGAD`,
`DEFAULT_PROFILES`) or a divergent local slug taxonomy
(`sop_documents.METHOD_LABELS` uses `fda/epa5371/epa1633`, not canonical IDs —
flagged; changing needs SOP-data migration, left as-is).

**D4 foundation (new module `matrix_ref.py`):** single resolver joining matrix
title-strings ↔ core `SampleType` (resolve / title_to_uid / uid_to_title /
all_matrices / find_profiles_referencing). Additive, backward-compatible,
nothing consumes it yet → zero risk. Verified live: "Eggs" round-trips to UID,
16 SampleTypes listed, referential-integrity check finds `FDA_32PFAS`→"Eggs".
Next staged steps (write UID on save, read-path adoption, migration) recorded in
SYSTEM_AUDIT.md §6.

**D1 decision:** NOT refactored. Westgard thresholds are identical across the
Py2.7 view and Py3 engine and are fixed by the methodology (not per-lab
configurable). Rewiring the regulated chart for a shared constants module = risk
without functional benefit. Left as accurately documented (cross-runtime
duplication, equivalent, not a compliance gap).

## D27 — D4 step 2: matrix→SampleType write + read path (2026-07-01)

**Write path:** `method_profile_store.save_profile` now persists
`matrix_uid_map = {title: SampleType UID}` (via `matrix_ref.title_to_uid`) on
every save. Additive — `supported_matrices` stays a list of titles; nothing that
reads titles breaks. Verified: FDA_32PFAS → 6 matrix→UID entries; UI save 200.

**Read path (first consumer):** `get_included_analytes` (the §3 Method×Matrix
key relation) resolves its `matrix` arg (title OR SampleType UID) through
`matrix_ref`. Backward-compatible: a live title resolves to itself (byte-
identical), an unknown/renamed title falls through unchanged (no orphaning), a
UID resolves to the canonical title. Verified byte-identical vs old logic on 3
matrices + UID-equivalence.

**Chose the profile path over EGAD** for the read-path adoption because
`egad_builder` already resolves sample type from the core object
(`ar.getSampleType()`), whereas the profile's `supported_matrices` /
`analyte_matrix_inclusion` was the actual raw-string coupling (§3 key relation).

**Next:** backfill migration for pre-existing profiles; adopt the same
`resolve()` one-liner in the remaining matrix consumers as they're touched.

## D28 — matrix_uid_map backfill migration (2026-07-01)

`migrations/backfill_matrix_uid_map.py` — one-shot, idempotent backfill of
`matrix_uid_map` (title→core SampleType UID) onto profiles saved before D4.

**Design note:** first version called `save_profile`, which triggered
`spec_sync` as a side effect (failed harmlessly in the `bin/instance run`
context — no types tool — and was semantically wrong for a map backfill).
Refactored to a local `_persist_profile` that writes straight to the store
(Dexterity folder or annotation) with no spec-sync/export churn. Reuses
`export_profiles_to_file` once at the end for the worker's JSON.

**Result:** EPA_1633A 9/9, EPA_537_1 3/3, FDA_32PFAS 6/6 matrices mapped, 0
unresolved; re-run = all "already current" (idempotent). Unresolved titles are
reported for manual fix, never guessed.

**D4 status:** foundation (resolver) + write path + first read-path consumer +
backfill migration all landed & verified. Remaining: adopt `matrix_ref.resolve`
in the other matrix consumers (surrogate map, recovery tiers, EGAD units) as
they're next touched — each a one-line change behind the resolver.

## D29 — Interactive System Map navigation page (2026-07-01)

New `@@pfas-system-map` (view `browser/system_map.py` + `templates/system_map.pt`),
linked as the first item in the sidebar **Configuration** group (`ico-sitemap`).

Renders the 3-layer architecture diagram (entry points → add-on parts → core
services) as **inline SVG with portal-relative `<a xlink:href>` baked into each
bubble** — native SVG navigation, no JS. 26 of 27 nodes are clickable and jump
straight to the screen a user edits (e.g. method_profile_store → @@pfas-method-
profiles, SampleType → setup/sampletypes, AnalysisService → bika_setup/...).
Hover highlights the bubble (CSS). Rendered through the shared page macro so it
inherits the sidebar/shell and is responsive (card scrolls on narrow screens).

The view owns the node/edge/nav model (mirrors gen_svg.py / senaite_pfas_map.svg);
the standalone `senaite_pfas_map.svg` remains the static export. Verified: page
200, 26 links resolve, click on a bubble navigates correctly.

## D30 — Two-way tolerance editing: AnalysisSpec ⇄ Method Profile (2026-07-01)

User asked for the Method Profile and Analyte Specification to be mutually
editable. Built as **write-through**, NOT two masters (which would undo this
session's single-source work): the Method Profile stays the one source of truth;
the AnalysisSpec is an editing surface onto it.

**Decision (user):** editing one analyte's spec limit creates a PER-ANALYTE
exception — it does NOT move its tier siblings. Tiers become defaults + per-
analyte exceptions.

**Mechanism:**
- Profile gains `spec_overrides = {qc_type: {analyte_kw: {min, max}}}`.
- Forward (`spec_sync`): override wins over tier default per analyte.
- Reverse (`spec_reverse.on_spec_modified`, subscriber on
  `IAnalysisSpec`+`IObjectModifiedEvent`): a spec edit writes changed analytes
  as overrides into the profile and re-saves it (regenerating the spec).
  Removes an override when the value returns to the tier default.

**Loop safety (verified):**
- `spec_sync.is_forward_syncing()` thread-local guard: reverse no-ops while
  forward writes specs.
- Write-back gated on NUMERICALLY-normalized diff (rounded floats, not the
  "80.0" strings the spec stores) so it can't churn.
- Verified end-to-end: PFOA 80–120→75–125 writes only PFOA override, siblings
  untouched, settles in one pass, idempotent on re-fire, revert removes the
  override, and a normal profile save preserves the override (PFOA 70–130 kept,
  PFOS at tier).

**Map:** the profile↔spec edge is now a double-headed amber "live two-way" link
(`@@pfas-system-map`); edge routing also cleaned up (port spreading + same-band
side routing).

## D31 — Pane control audit: selectors link to existing objects (2026-07-01)

Swept every pane's dropdowns/selectors for "links to an existing object /
creates a new one / hardcoded orphan."

**Fixed (genuine orphans — hardcoded, not linked to real methods):**
- `deviations.available_methods()` — read a non-existent `bika_setup.bika_methods`
  folder (SENAITE 2.6 uses `bika_setup.methods`); the `except` swallowed the
  AttributeError → EMPTY dropdown. Now queries `senaite_catalog_setup` for active
  `Method` objects (method-1/2/3), which is what worksheets are tagged with.
- `sop_documents.method_options()` + `filter_tabs()` — a frozen `fda/epa5371/
  epa1633` list. Now derived from `analyte_reference.get_method_ids()` (single
  source); legacy slug VALUES preserved for stored SOPs. Byte-identical output
  today; a new method now appears automatically.

**Verified OK (already dynamic or legitimate vocab):**
- Dynamic (read live objects): qc_grid, method_profiles, import_studio,
  data_review, reagents, prepared_standards; qc.rules/qc_grid methods derive
  from the single-source registry.
- Config vocabularies (editable, read a saved store): egad_config lookups
  (EGAD SAMPLE_TYPE/test/prep codes — the Maine-DEP vocabulary, correctly
  distinct from core SampleTypes; core→EGAD mapping is in egad_builder via
  ar.getSampleType()).
- Status/workflow vocab: calibrations.status_choices (pending/approved/rejected).

**Flagged (minor, not fixed):** `egad_config._ANALYTE_ORDER`/`_ANALYTE_TITLES` —
a curated 34-analyte EGAD display list that overlaps `egad_store`'s overlay set;
each row still links to the single-sourced CAS (D2). Set-duplication only; order
is EGAD presentation. Could derive the set from egad_store later.

## D32 — Method bridge: profile ⇄ core SENAITE Method, + linked display (2026-07-01)

Populated the empty `senaite.pfas.method_associations` bridge and surfaced it.

**`method_bridge.py`** (new) — maintains + reads the link between a PFAS method
profile (FDA_32PFAS: QC ranges/tiers/matrices) and the core SENAITE Method
object (method-1: what analytes/worksheets reference):
- `get_association / get_core_method / get_profile_id_for_method` (both
  directions), `link_one`, `link_all`.
- Matches by Method TITLE (single-source registry label == Method.Title()),
  matched in Python (some titles contain parentheses that break a Title=
  ZCTextIndex query). Unmatched profiles reported, never guessed.
- Stores method_uid/method_id/method_title + the governed AnalysisService and
  SampleType UIDs (services from master_analyte_set, sampletypes from the D4
  matrix_uid_map).

**Wiring:**
- `save_profile` calls `link_one` (guarded) so the bridge stays fresh.
- `migrations/backfill_method_associations.py` — idempotent backfill for the 3
  seeded methods. Result: FDA→method-1 (32 svc/6 st), EPA_537_1→method-2 (18/3),
  EPA_1633A→method-3 (40/9); 0 unmatched.

**Display add-in (the "improve on core" ask):** the Method Profiles page now has
a "SENAITE Method" column — each profile shows its linked core Method as a
clickable link (resolves to `/methods/method-N`, HTTP 200) with "N analytes ·
M matrices" beneath. The intuitive PFAS profile now sits visibly on top of the
proper core Method record.

**Reverse (future add-in):** a viewlet on the core Method view linking back to
the PFAS profile (QC ranges) — `get_profile_id_for_method` already supports it.

## D33 — Reverse bridge add-in on the core Method view (2026-07-01)

Completes D32's bridge in the UI: a viewlet (`browser/method_viewlet.py` +
`templates/method_profile_viewlet.pt`) on the core SENAITE Method view (registered
for `bika.lims.interfaces.IMethod` in the `IAboveContentBody` manager, on
ISenaitePFASLayer — upgrade-safe, no core fork) shows the linked PFAS profile:
profile name + id, "governs N analytes · M matrices", and a "Configure QC ranges"
button to `@@pfas-method-profile-edit`. Renders nothing for Methods with no PFAS
profile (`get_profile_id_for_method` → None).

So the bridge is now visible from BOTH sides: Method Profiles page → core Method
(forward), core Method view → PFAS profile (reverse). The core Method stays the
proper SENAITE anchor; the PFAS panel is the intuitive add-in on top.

**Gotcha fixed:** the panel template first used `tal:attributes="style string:…"`
with CSS containing semicolons — TAL reads `;` as attribute separators, so it
threw "error while rendering". Moved styles into a scoped `<style>` block with
classes; only `href` stays in `tal:attributes`.

## D34 — Per-matrix AnalysisSpecs on REAL SampleTypes; tight-matrix tiers (2026-07-02)

**User-reported defect:** AnalysisSpec SampleType showed the QC profile name
("FDA 32-PFAS in Food LFSM"), not the real matrices. Root cause: spec_sync
invented synthetic SampleTypes — but SENAITE matches specs to samples BY
SampleType, so those specs could never match a real sample.

**Second (loose-variable) find while fixing:** tier `matrix_scope:"tight"` was
consumed NOWHERE, and no tight-matrix list existed. The flat specs claimed PFOA
80–120 for ALL matrices — wrong per FDA Table 10-1 (tight range applies only in
egg/meat/seafood).

**Fix:**
- spec_sync now builds ONE spec per method × QC type × REAL matrix
  (`spec_id_for()` = `{mid}-{qc}-{matrix-slug}-recovery`), linked to the real
  SampleType via matrix_ref. Synthetic-SampleType creation removed.
- New `tight_matrices` profile key (configurable, golden rule #1; seeded
  Eggs / Meat / Muscle / Fish / Seafood per CLAUDE.md §3).
  `effective_tier()`: tier 1 → tier 2 outside tight matrices.
- `spec_overrides` now nests per matrix: `{qc: {matrix: {kw: {min,max}}}}`
  (legacy flat shape still READ, applied to all matrices; writes are nested).
  spec_reverse identifies specs per-matrix and compares against the
  matrix-effective tier.
- Migration `cleanup_synthetic_qc_sampletypes.py`: removed 2 old flat specs;
  seeded tight_matrices; regenerated 48 per-matrix specs (FDA 12, 537.1 9,
  1633A 27). The 2 synthetic SampleTypes were KEPT — 3 samples each reference
  them (§3 rule 4: surfaced, not orphaned); reassign those samples then delete.

**Verified:** every FDA LFSM spec links to its real matrix SampleType; PFOA
80–120 in Eggs/Meat/Fish vs 65–135 in Milk/Feed/Aquatic (matrix-dependent tier
now enforced); reverse sync writes matrix-scoped overrides (Eggs edit leaves
Milk/Meat untouched), revert removes them; pages load clean.

**Gotcha:** Archetypes `manage_delObjects` fails for the root admin in
`bin/instance run` (portal-member permission check) — use `_delObject`.

## D35 — Loose-variable catalogue sweep + fixes (2026-07-02)

Fork-agent catalogue of all addon constants (classified: hardcoded lab value /
duplicate / legit vocab / editable seed), core empty dirs vs siloed addon data,
and annotation-store liveness. Full tables in the audit; actions taken:

1. **FDA cal ladder was defined 3× with contradictory numbering** (CAL-1 = 20
   in FM-ENV-251 logbook + CAL_LADDERS, but CAL-1 = 0.039 in analytes.CAL_LEVELS,
   which had ZERO consumers). Single-sourced: `analyte_reference.CAL_LADDERS`
   (exact halving values) + `get_cal_ladder()`; logbook FDA_CAL_DEFAULTS derives
   descending (verified byte-identical to old literal); CAL_LEVELS derives
   ASCENDING — its comment says instrument sample descriptions number the ladder
   upward. Both directions now share one value set; direction is explicit.
   **VERIFY with lab** before wiring injection-name consumers.
2. **vendor_templates never populated** (seeding failed: post_install context
   without getSite). Defensive portal resolution added; store seeded now —
   4 vendor templates (agilent/native/sciex/waters) in Import Studio.
3. **Empty core dirs un-siloed** (migrations/seed_empty_core_dirs.py, idempotent):
   5 SamplePoints + 7 ContainerTypes from setupdata CSVs (PLACEHOLDER client
   names NOT fabricated — flagged in descriptions); 1 "PFAS Chemistry"
   Department (method-wizard step 2 previously had an empty selector).
4. **BALANCE_DEFAULTS false alarm**: per-unit weight_points_json override fully
   implemented (form save + read-with-fallback) — legit editable seed.
5. **COLUMN_MAP** (data_importer hardcodes vendor mappings, §7 violation) —
   BLOCKED on D3: module has no in-tree caller; confirm the Py3 worker uses it
   before refactoring (refactoring dead code = waste).
Also noted: spec_sync_audit is write-only (no UI reads it yet); wizard_sessions
grows unbounded; analyte_reference CONTAINERS/STORAGE_LOCATIONS/PRESERVATIONS
constants are dead (CSVs are the real seed source) — candidates for deletion.
System map updated (per-matrix specs labels).

## D36 — Data Review: final-data diagnosis, live qualifier legend, e-sign corrections (2026-07-02)

**Final Data tab empty (user report):** root cause was a data-linking gap, not
rendering — worksheets have 0 assigned analyses, batch links absent, no results
in core (18 ARs × 3 analyses, all resultless), and no pipeline output files.
Fixes: (1) `get_final_data` falls back ws→batch ARs (senaite_catalog_sample,
getBatchUID); (2) `final_data_diagnosis()` renders WHICH link is unpopulated
("no samples linked to batch" vs "samples found but no results imported")
instead of a silent blank table; (3) qualifier legend now rendered LIVE from
`egad_store.get_qualifier_map` (the user's example vocabulary: N.D./BLoQ/J/…,
editable under EGAD Config, with an "edit map →" link) — no hardcoded copy.

**Corrections (user report: date edits not noted, no initial+date):**
e-sign-style corrections implemented:
- `correct_field` action: whitelisted CoC fields (collection date, received
  date), REQUIRED initials, reason optional; write-through to the owning CoC
  annotation; old→new logged to `senaite.pfas.data_review.corrections`.
- Corrections rendered in the CoC tab (strike-through old value, initials,
  date, reason) AND in the Overview/final review.
- All four checklist "Mark Reviewed" sign-offs now REQUIRE typed initials
  ("Sign & Mark Reviewed"), stored and displayed next to reviewer + timestamp.
- New msgs: initials_required / correction_logged / no_change.

**Open (next): print-template system** — user wants consistent printing
(standard forms vs CoC) driven by templates configurable centrally (for audit
copies of SOPs etc.). Design: print-settings store (lab identity, logo, footer,
form-code display) + shared print header/footer macro in pfas_macros applied to
all printable views (logbooks, CoC, extraction PDF, SOPs).

## D37 — Site-wide print template system (2026-07-02)

**Store:** `print_settings.py` — `senaite.pfas.print_settings` annotation
(lab identity, logo, accreditation line, footer text, show flags), editable at
**Configuration → Print Settings** (`@@pfas-print-settings`, ManageBika,
sidebar entry, live preview on the page).

**Application:** a `printhead` macro + fixed page footer defined INSIDE the
shared page macro (pfas_macros.pt) — every page that uses the page macro
(all FM-ENV logbooks, SOPs, every PFAS view) gets the identical print
header/footer automatically, no per-template wiring. Hidden on screen
(`.pfas-printhead{display:none}`), shown under `@media print`. The macro
resolves settings itself via `@@pfas-macros/print_settings()` so it works
from any caller's namespace. Standalone templates reuse it:
`receipt.pt` (CoC/receipt) wired via `metal:use-macro` + minimal local CSS.

**Verified:** settings save round-trip persists and propagates site-wide
(saved address rendered in another page's printhead); Playwright print-media
emulation shows the header (lab name, address line, "Printed: <ts>") above
content with screen chrome hidden. Test address reset to defaults after QA.

**Remaining printables:** `label_print.pt` intentionally excluded (labels have
their own compact format). `extraction_pdf` is ReportLab-generated — reading
the same store from Python is the follow-up for full parity.

## D38 — D3 resolved: dead importer deleted; §7 refusal enforced (2026-07-02)

**Verdict:** `src/senaite/pfas/ingest/data_importer.py` (593 lines, hardcoded
COLUMN_MAP) was dead code — the Py3 worker builds from `pfas_pipeline/` only
(Dockerfile.worker) and has its own importer; nothing in-tree or in the worker
referenced the addon module. **Deleted** (with its .pyc; ingest/ package kept).

**Live path was already §7-correct** (worker → `@@pfas-instrument-profile` →
Import Studio profile, raises on error), but `load_instrument_csv` silently
fell back to hardcoded `vendor_profiles.py` when called without a profile
(dev/direct calls). Now **refuses by default** with an instructive error;
legacy fallback gated behind `PFAS_ALLOW_LEGACY_VENDOR_MAP=1` (set in the two
tests that exercise it). Verified: refusal raises without env; importer-related
tests pass with it; worker rebuilt + healthy; senaite clean after deletion.

**Pre-existing failure flagged (NOT D3, not fixed):** `tests/test_profiles.py`
`test_fda_three_tier` asserts `qc_rules("M2-6:2FTS","aqueous","EIS").
verify_against_method is True` and fails on worker BUILTIN profiles (host has
no exported json). Worker EIS logic in `pfas_pipeline/method_profiles.py` —
untouched this session; needs its own investigation.

## D39 — Method-pool dynamics + QC-type toggles + inherited expiry system (2026-07-02)

**Method pool (verified):** a newly saved method (wizard or API) appears in the
Method Profiles pool automatically (pool = DEFAULT_PROFILES ∪ saved ids) and
spec_sync creates its per-matrix specs. Live-tested with TEST_NEWM →
`test-newm-lcs-drinking-water-recovery` linked to the real Drinking Water
SampleType.

**QC types now dynamic + toggleable:** spec_sync and spec_reverse derive QC
types from the profile's `qc_acceptance` keys (hardcoded ("LCS","LFSM","LFB",
"LFSMD") tuples removed; static tuple kept only as reverse-sync fallback).
New "QC Types" tab in the profile editor: checkbox per QC type persisting
`qc_acceptance[k]["enabled"]` (guarded by a `qc_toggles_present` marker so
other form posts can't mass-disable). Disabled types are skipped by engine +
sync. NOTE: disabling does not DELETE previously created specs (left in place;
deliberate — deactivation policy TBD).

**Inherited expiry system (reagents/prepared standards):**
- Global defaults (days) in lab settings, editable at Reagent Inventory →
  "Expiry Defaults" card: reagent_default (365), mobile_phase_open (7 — was
  hardcoded), opened_default (365), prepared_std_default (365).
- Manufactured reagent with NO stated expiry → assigned received_date +
  reagent_default at save, with an audit note ("assigned from global default").
  Read-time `_effective_expiry` also falls back the same way.
- In-house prepared standard w/o expiry → prepared_date + prepared_std_default
  at save (note recorded).
- **Parent tightening:** `effective_expiry_info` = min(own expiry, every parent
  reagent lot's effective expiry via `get_reagent_effective_expiry(portal, lot,
  name)`), computed at READ time so later parent changes propagate; UI shows
  "⇣ inherited: <parent>" badge, expiry colouring + expired-status use the
  effective date.
- Verified live: +365 assignment w/ note; PS(+300 own) with CRM parent(+30)
  → effective +30 inherited from "TEST CRM Tight"; PS w/o expiry → +365.

## D40 — Spec retirement w/ audit; control-chart pool purged of seed data (2026-07-02)

**Spec retirement (user decision):** disabling a QC type (or removing a matrix/
tiers) now RETIRES its AnalysisSpecs — spec_sync's post-loop pass deactivates
specs no longer produced (workflow 'deactivate') and REACTIVATES them when
re-enabled. Each transition takes a native snapshot: action "PFAS Retire" /
"PFAS Reactivate" with an explanatory comment → visible in the standard Audit
Log. Verified through the real UI path (QC Types tab POST): disabling LFSMD →
all 6 FDA LFSMD specs inactive, snapshot action='PFAS Retire', actor recorded,
LFSM untouched; re-enable → active + 'PFAS Reactivate'.
GOTCHA: workflow transitions need a real request (`guard_handler` view) — they
fail under bin/instance run; the pass is guarded so a script save degrades to a
logged warning, and the web path (how users save) works.

**Control-chart pool (user report: false entries):** confirmed — 2,107 of
2,207 qc_results rows were seed/synthetic (1,344 TEST_DATA*, 42 SYNTHETIC_,
721 unflagged B0xxx demo batches; only 100 rows belonged to real WS-xxxx
worksheets). Two-layer fix:
1. `QCResultStore.get_chart_data(include_test=False)` — permanently excludes
   TEST_DATA*/SYNTHETIC_ rows from charts (guard against future seeding).
2. `migrations/purge_seed_qc_data.py` — moved every row whose batch_id is not
   a REAL worksheet id into *_archive tables in the same DB (qc_results 2107,
   batches 216, calibrations 686, calibration_levels 4816 archived; fully
   reversible; refuses to run if no real worksheets exist).
Verified: PFOA/LFB chart now returns exactly the WS-0001 row(s); no synthetic
batches; chart/calibrations/qc pages render clean on the reduced pool.

## D41 — Calibration pane guard; Import-Studio retirement; LC-MS Run Builder (2026-07-02)

**Calibrations (same treatment as charts):** legacy synthetic rows were already
archived by the D40 purge (686 cals + 4,816 levels); `get_calibrations` now
also permanently excludes `SYNTHETIC_%` batches. Page renders clean.

**Import-profile retirement (audited):** `set_vendor_profile_retired` +
retire/reactivate actions in Import Studio, a "Saved Import Profiles" card
(status badges, reason field), and a dedicated audit log
(`senaite.pfas.import_studio_audit` — profiles are annotation records, not
content objects, so SENAITE snapshots don't apply; this log is the audit trail
and is displayed as "Profile audit history"). The pipeline REST bridge REFUSES
retired profiles with an explicit error. Verified: REST served the profile →
retired via UI (reason recorded) → REST refuses ("is RETIRED — imports are
refused") → UI shows RETIRED + history entry.

**LC-MS Run Builder (@@pfas-run-builder, Instruments & Import):** new interface
bridging extraction → instrument → import:
- Batch selector auto-populates samples from the extraction session
  (FM-ENV-252) or batch-linked samples; manual add supported.
- User inputs: analyst initials (required), matrix word, method, CCV interval,
  cal-curve toggle, LFSM spike.
- Builds the injection sequence: MeOH blank → CAL ladder (single-source
  `get_cal_ladder`, names `FDA-CAL-n-YYMMDD` = validated pattern 2) → ICV/MB/
  LCS → samples with CCV every N (pattern-3 names `INI Matrix TYPE date-NN`)
  → LFSM/LFSMD → closing CCV. Saved as `senaite.pfas.run_manifest` on the
  batch for import-time cross-check; downloadable worklist CSV
  (Vial/Sample Name/Type) for the instrument's sequence-import tool.
- **Upload point**: writes the finished instrument export into
  `/addon/data/instrument_output` == the worker's WATCH_DIR (compose-shared).

**End-to-end verified:** built a run for example-batch-fda32 (preview + CSV
correct incl. FDA-CAL-1-260702); uploaded a test export → worker detected it
within its 30 s poll, identified vendor=sciex, queried the Import Studio REST
bridge and correctly REFUSED without an active mapping — proving upload→watch→
worker→REST connectivity, §7 strictness, and retirement enforcement in one
pass. Test artifacts removed.

## D42 — Run Builder rework: fully derived inputs; CSRF fix; mobile (2026-07-02)

User-reported issues, all fixed and verified:
1. **Upload/build errors** — the forms lacked CSRF handling; browser POSTs were
   rejected. Now `IDisableCSRFProtection` (same pattern as sibling PFAS form
   views). Tokenless upload + build both 302 and the file lands in the watch dir.
2. **FM-252 no longer an exact parameter** — the extraction logbook is resolved
   PER METHOD: profile `extraction_logbook` if set, else the extraction-titled
   entry of the method's `required_logbooks` (registry lookup), last-resort
   "252" only when the method requires it. Batch→method uses the same
   resolution as logbooks (session > logbook > batch).
3. **Analyst from the laboratory staff pool** — selector reads LabContacts
   (initials derived from full name); when the pool is empty the form says so
   and links to SENAITE setup (pool was flagged empty in the D35 catalogue).
4. **Matrix per sample, from the log** — the single "Matrix" input is GONE.
   Per-sample matrix comes from the extraction-log rows; rows without one
   resolve it from the sample's REAL core SampleType by id (no fabrication —
   unmatched demo ids show "—"). QC injections use the run's dominant matrix.
   GOTCHA fixed: the log field `sample_type` is the QC ROLE (Sample/Dup), NOT
   the matrix — it briefly leaked into the matrix column.
5. **CCV from method parameters** — `instrument_verification.ccv.frequency`
   (shown read-only, "method parameter"); form input removed.
6. **Spike from the extraction logbook** — read from log rows
   (`spike_ppt`/`spike`); form input removed.
7. **Mobile** — Saved Import Profiles + mapping-grid tables wrapped in
   `.table-wrap`; Run Builder inputs full-width/box-sizing; verified at 375px:
   no page drag on Run Builder or Import Studio, tables self-scroll.

## D43 — Staff pool: placeholder contacts, explicit initials, signatures on documents (2026-07-02)

- **Core reuse:** LabContact already carries the Signature ImageField — upload
  on the contact's edit form; nothing reinvented.
- **Initials made explicit:** `extenders/labcontact.py` adds `pfas_initials`
  (declared per person, derived-from-name only as fallback).
- **`staff.py`** — single staff-pool API: `list_staff` / `find_by_initials`
  → {fullname, initials, signature_url, placeholder}. Run Builder selector now
  reads it.
- **Seeded 4 PLACEHOLDER contacts** (Lab Manager LM, Analyst One A1, Analyst
  Two A2, Bench Chemist BC) — names flagged PLACEHOLDER per §8; NO signature
  images fabricated (lab uploads real ones).
- **Signatures appended to documents:** data-review sign-offs and correction
  rows now render the signer's Signature image next to their initials whenever
  the initials match a staff member with an uploaded signature (initials alone
  until then). Verified: sign-off as LM shows "(LM)"; image is conditional on
  signature_url.

## D44 — End-to-end dry run: client → samples → review → EDD (2026-07-02)

Full walkthrough with seeded food/feed data (client "DEMO Food & Feed Producer
Ltd", contact, EGG/MEAT/FEED samples ×4 analytes, batch B-002, worksheet
WS-001, extraction log, CoC, QC rows, results, 5/5 review gates PASS, EDD
generated). Issues found & status:

1. Samples must be RECEIVED before worksheet assignment (process order) — noted.
2. Workflow transitions blocked in scripts (guard_handler needs real request) —
   WORKAROUND: senaite.jsonapi POST update {uid, transition} works.
3. qc_results.created_at NOT NULL — seeding scripts must supply it.
4. Worksheet assignment must precede analysis submit (assign guard); submitted
   analyses can't be assigned retroactively → WS stayed 'open' (checklist gate
   itself passed). PROCESS DOC needed.
5. **FIXED**: data_review batch-fallback joined on the WORKSHEET's uid. The
   missing model link (user's intuition) is Worksheet↔Batch — now closed via
   CoC `batch_id` (the CoC accompanies the worksheet), with SENAITE-native
   assignment as the primary path.
6. Logbook home mismatch: run_builder reads batch annotations, data_review's
   traceability reads WORKSHEET annotations (CLAUDE.md says worksheet). E2E
   seeded both; consolidation to worksheet pending.
7. **FIXED**: EGAD export resolved Batch via portal_catalog (not indexed
   there) → "Batch not found". Direct folder fallback added.
8. **FIXED**: egad_builder dropped EVERY analysis — `analysis.review_state` is
   a catalog-brain attribute; on full objects it raised AttributeError into a
   silent continue. Now api.get_review_status().
9. OPEN: EDD row derivation uses client DEFAULTS (SAMPLE_TYPE=GW, NG/L,
   TEST=E537.1) instead of the batch's method/matrices (FDA food → USFDA-PFAS,
   NG/KG, per-sample EGAD types) — method/matrix mapping into the EDD needs
   wiring to the batch method + matrix_uid_map.
10. OPEN (the "missing section"): no client-facing COA/report step — analyses
    stop at to_be_verified; verify+publish (senaite COA) is unwired in the PFAS
    flow. The EDD is the only end artifact today.

Artifact: DEMO_B-002_EDD.csv (12 result rows, CAS single-sourced).

## D45 — #10 closed: client COA step wired (verify → publish → impress) (2026-07-02)

The missing final section now exists, via core reuse (senaite.impress 2.6 was
installed but unwired):
- Self-verification enabled in setup (demo: submitter==verifier; production
  labs with separate analysts can disable again).
- Analyses verified + samples PUBLISHED (EGG/MEAT/FEED-0001 → 'published' via
  jsonapi transitions — the charts' "published samples" pool is now real).
- **Data Review → "Client Report (COA)" section**: appears when all five
  review gates pass; "Generate COA →" opens senaite.impress's publish view
  pre-loaded with the worksheet's samples (uids resolved via the same
  ws→CoC→batch join from D44#5). Verified: button renders on WS-001 with the
  3 published sample uids; impress UI loads (HTTP 200).

Full lifecycle now demonstrated: client → samples → batch/worksheet →
extraction log → results → 5-gate review → verify → publish → COA + EDD.
Remaining from the D44 ledger: #9 (EDD method/matrix mapping), #4/#6 (process
order + logbook home consolidation).

## D46 — D44#9 fixed: EDD derives from the batch's method (2026-07-02)

- New `EGADBuilder._batch_method_profile(batch)`: core Method → PROFILE id via
  the method bridge; else the batch's run_manifest / extraction-log
  annotations. Passed into every row build.
- Per-AR method: ar.getMethod() (core object) also mapped through the bridge —
  previously its raw id ('method-1') could never match the EGAD method cfg
  keys, so client defaults always won.
- **Units single-sourced**: the profile's UNIT MAP (method × matrix, §3) wins
  per sample (ng/g normalised to NG/KG for EDD); EGAD-code fallback otherwise.
- Verified on B-002: rows now carry TEST=USFDA-PFAS + NG/KG (were E537.1 +
  NG/L from client defaults). Artifact DEMO_B-002_EDD.csv refreshed.
- Gotcha: _ar_to_rows signature patch missed the actual formatting once →
  TypeError 500; fixed.
Remaining ledger: D44 #4/#6 (process order; logbook home) + per-sample EGAD
SAMPLE_TYPE codes for food matrices (needs a configurable matrix→EGAD-code
map; current per-AR override/default retained).

## D47 — EDD generalized: format profiles, client association, Maine sub-profiles (2026-07-02)

The EDD engine is no longer Maine-EGAD-hardcoded:
- **Profile store** (`senaite.pfas.edd_profiles`): each profile = display name,
  column subset/order (of the Maine superset the builder can emit), heading
  ALIASES, and a configurable SampleType→SAMPLE_TYPE-code MATRIX MAP. Seeded
  base `maine_egad` (full 53 columns + standard env codes GW/SW/DW/SO/SE/WW/LL;
  food matrices deliberately unmapped — never fabricated). `clone_edd_profile`
  creates sub-profiles / other state programs.
- **Client association**: client EGAD config gains `edd_profile` (selector on
  the client page); builder resolves it per batch. Validation still runs on the
  full Maine-semantics superset; output is then shaped by the profile.
- **UI**: EGAD Config → "EDD Format Profiles" card (clone form + per-profile
  editors: columns list, matrix-map JSON, aliases JSON, name).
- **Bonus fix (same gap family)**: export resolved client via
  `batch.getClient()` only — batches aren't always client-linked; now falls
  back to the batch's first sample's client.

**Verified end-to-end**: cloned "Maine EGAD — food sub-profile", shrunk to 8
columns, aliased CAS_NO→"CAS Number", mapped Eggs/Meat→FOOD + Feed→FEED,
assigned to the DEMO client → B-002 export emits exactly those 8 aliased
columns with FOOD/FEED sample types (also closing the D46 food-code edge),
method-true NG/KG + USFDA-PFAS retained.

Gotchas: card initially rendered nothing (inserted outside the metal content
slot — silently discarded); LocationError after the move (accessor had landed
on the CLIENT view class, template served by the MAIN view).

## D48 — D44 #4/#6 closed: assign-order action + logbook dual-read (2026-07-02)

**#4 (process order → enforceable action):** Data Review overview shows a
banner when the worksheet has no assigned analyses but its linked batch has
samples, with a "Receive & assign batch samples" button
(`assign_batch_samples` action): receives sample_due ARs and assigns their
UNSUBMITTED analyses (runs in a real request so workflow guards resolve);
already-submitted analyses are counted as skipped with an explanatory message
(SENAITE forbids assignment after submit — reviewed via the batch join
instead). Verified on WS-001: banner + button render; action reports the
skip path correctly; all 5 gates unaffected.

**#6 (logbook home consolidation):** `_logbook_json(ws, key)` dual-read —
worksheet annotation first (CLAUDE.md canonical), else the CoC-linked batch
(where the logbook views historically write). Traceability tree now uses it.
Verified by REMOVING the worksheet's duplicate FM-ENV-252 copy (batch holds
the only copy) — traceability still PASSES via the fallback. Net effect:
single stored copy + resilient readers; a future storage migration to the
worksheet remains optional rather than required.

D44 ledger fully closed (#1–#10).

## D49 — Naming: EGAD (Maine-specific) → EDD (generic) in all chrome (2026-07-02)

User point (correct): EGAD is Maine DEP's system name; other states have their
own (e.g. Massachusetts eDEP). With D47's program profiles, the generic layer
must speak "EDD":
- Page titles/headers: "Maine EGAD EDD Configuration" → **"EDD Configuration"**;
  batches page → **"Delivered EDDs"** (sidebar + lims-setup tiles renamed too;
  tile descriptions mention "program profiles (incl. Maine EGAD)").
- Client page: "EDD Settings — <client>", "Save Client EDD Settings".
- Maine-specific content KEEPS its qualifier ("Maine EGAD" lookup tables /
  CAS mapping / DEP data-entry link) — accuracy over blanket rename.
- Internal ids/URLs/store keys (@@pfas-egad-*, senaite.pfas.egad*) unchanged —
  implementation naming; renaming them would break links/wiring for zero user
  value. System map node relabelled "EDD engine".
Verified rendered: titles, sidebar items and batch page all show the generic
names; zero bare ">EGAD" strings left in chrome.

## D50 — UI consistency, spike-prune on QC toggle, profiles/QC-Rules separation, Lab Workflow tab (2026-07-02)

**Minor:** prep-standards row actions Edit/Certificate unified as `.row-pill`
(pill style matching the status badges). Reagents: "Scan Barcode" + "OCR Label"
merged into ONE "Scan Label" button (the scan modal keeps its barcode/OCR mode
tabs inside).

**Spike prune (major):** saving the profile with a QC type toggled OFF now
prunes that type's spike-level blocks from EVERY matrix (e.g. LFB off → LFB
spike rows removed). Proven live: disabling LFSM emptied spike_levels across
all 6 FDA matrices; re-enable + reseed restored. NOTE: pruning is one-way — a
re-enabled type starts with no spike rows (deliberate: no stale data).

**Profiles vs QC Rules — decision: CLEAN SEPARATION (not consolidation).**
Evidence: the worker consumes BOTH stores for different things —
`qc_rules.json` = per-method instrument-rule TOGGLES (run_queue), the profile's
`instrument_verification` = the acceptance PARAMETERS (method_profiles.py).
So the split is real; the UIs just never said so. Both pages now carry scope
banners with cross-links: QC Rules = global instrument-rule library + per-
method on/off; Method Profiles = method-science acceptance (tiers/QC types/
spikes/matrices) AND the method's instrument-verification parameter values.

**Lab Workflow:** promoted from a buried section to its OWN tab in the profile
editor, with a legend explaining the stage flags — "Creates Solution" records a
new Prepared Standard lot (parents = the stage's reagents; expiry inherits);
"Capture Standard Pedigree" shows the pedigree table in Guided Extraction,
completing the 3-level traceability chain the review gate checks. The tab
states explicitly that these stages BECOME the guided extraction inside the
batch's method-set extraction logbook. FUTURE (user suggestion, agreed):
surface/edit the workflow from within the extraction-log admin itself.

## D51 — UI pass: pills everywhere, QC Rules polish, LJ badge cleanup, review tables (2026-07-02)

- `.btn-sm` had NO css in reagents.pt / prep_logbooks.pt — row buttons rendered
  as unstyled browser defaults (the inconsistency). Defined once per page as the
  status-badge-style pill (+ .btn-danger red / .btn-warn amber tints); zero
  markup changes.
- QC Rules: header-title renamed "QC Rule Configuration" → "QC Rules" (matches
  sidebar/tiles); the scope note moved INSIDE the Global Criteria pane (was a
  floating page-top banner; first landed in a tal:repeat rendering ×10 — fixed
  to single placement).
- Levey-Jennings badge cleanup: removed the per-QC-type row badges (qcrules),
  the control-chart header badge, and reworded three tile descriptions to
  "QC control charts with Westgard rule evaluation". The chart-type SELECT
  (functional) keeps its Levey-Jennings option.
- Data Review tables (fd-table, qc-matrix) had dark primary headers — restyled
  to the system-standard light header (uppercase secondary, border-bottom),
  incl. the worksheet-selection table.

## D52 — QC Rules + Method Profiles consolidated into one per-method console (2026-07-03)

User directive: "integrate it into one page ... two empty pages in qc rules ...
toggles and qc run as one of the first tabs. Method specific recoveries."

**Audit findings:** QC Rules had 6 tabs; two render ZERO editable controls —
Global Criteria (global section unpopulated) and Matrix Factors (salt factors
are per-method, so the global doc holds none). The emptiness is diagnostic: that
data belongs under METHOD (§3). "QC Types" existed in BOTH pages (acceptance
limits in QC Rules; enable toggles in Method Profile) — same concept, split.

**Decision (supersedes D50's UI separation ONLY):** merge into ONE per-method
console = the existing @@pfas-method-profile-edit page (already per-method, has
the method selector), gaining the QC-rule tabs scoped to the selected method.
- **Stores stay SEPARATE** (qc_rules.json + method_profiles.json). This is a UI
  merge, not a data merge — the pipeline reads both for different jobs (D50).
  The merged page's save writes to BOTH stores. Golden Rule #3 preserved.
- Tab order: Rule Toggles & QC Run → QC Types (MERGED: enable toggle + limits)
  → Recovery Tiers → Analyte Inclusion → Surrogate Map → EIS (1633A only) →
  Factors (salt/matrix) → Calibration → CCV → IS Response → Lab Workflow →
  Advanced (Global Defaults + raw JSON, last).
- **Rule Toggles = per selected method** (user chose "Per-method (consistent)"
  over the all-methods matrix), matching every other tab.
- @@pfas-qc-rules retired → redirects to the merged console; sidebar updated.
- Two empty tabs disappear; no data lost.

## D52 (cont.) — Built & verified (2026-07-03)

Merged console live at @@pfas-method-profile-edit. Tab order confirmed:
Rule Toggles & QC Run · QC Types · Recovery Tiers · Analyte × Matrix ·
Surrogate Map · EIS Limits · Calibration · CCV · IS Response · Lab Workflow ·
Advanced. @@pfas-qc-rules now 302-redirects to the console; sidebar shows a
single "Method Profiles & QC" entry (QC Rules item removed).

- Rule Toggles & QC Run merges the old Rule-Toggles + Method-Limits tabs:
  each rule = enable checkbox + inline param overrides (blank = inherit global).
  8 rules/method (matches the old all-methods grid: 24 controls / 3 methods).
- Save writes BOTH stores in one POST (profile → method_profiles.json;
  toggles/overrides/global → qc_rules.json). Verified round-trip: toggled
  cal_r2 off, set ccv_recovery_min override=75, global cal_r2_min 0.995→0.990,
  all landed in qc_rules.json; profile store (spike_levels, matrices, analytes,
  qc_acceptance) untouched by the partial POST. Restored test values after.
- **Store bug fixed (root cause of the "empty Global Criteria" tab):**
  QCRulesStore.load() merged qc_types/method_rule_toggles/method_overrides from
  the saved file but DROPPED `global` and `salt_factors` — so get_rules()
  always returned default/empty global. Now merged; Advanced tab renders all 13
  global fields. The other "empty" tab (Matrix Factors) is gone entirely.
- Worker confirmed still reading qc_rules.json (13 global keys, FDA toggles).
- Stores remain SEPARATE (D50 data-layer separation preserved); only the UI
  was unified.

## D53 — Console UI refinements + Sample Corrections split (2026-07-03)

Six items off the merged console (D52):
1. **Font consistency** — `.json-hint` was `font-family: monospace`, so every
   tab's prose rendered in monospace and clashed with the sans-serif system.
   Changed to the system font; inline field names use `<code>` (still mono).
   New `.pane-intro` class for tab descriptions.
2. **Pill toggles** — the Rule Toggles tab used plain checkboxes; restored the
   original `.toggle-switch` sliding pill (ported from the old QC Rules page).
   `name="ruletoggle.<key>"` unchanged, so save is unaffected.
3. **Grey-out on off** — a rule's param inputs grey (`.rule-off`, opacity/colour)
   when its pill is toggled off. Inputs stay submittable (not `disabled`) so a
   value survives an off→on toggle; JS syncs on load + change.
4. **Mobile tables** — `.section-body { overflow-x:auto }` + wrapped the toggle
   table; verified 0 page-drag at 375px across all panes (tables were bleeding
   past card borders before).
5. **Duplicate criteria → spike info** (confirmed): pane-rt reorganised into a
   "Spike QC Criteria (LFSM / LFB)" group = Spike Levels + Recovery Acceptance
   together (was split). Recovery Tiers relabelled "Recovery Acceptance
   (LFSM / LFB / LCS)".
6. **Salt = core correction** (confirmed): Salt + Matrix adjustment moved OUT of
   the Recovery Tiers (QC) tab into a NEW **Sample Corrections** tab, framed
   "applied to every sample — not just QC". qc_rules.salt_factors deprecated
   (dead — pipeline never read it; salt lives in the profile as a core
   per-method correction, like matrix_factors).

New tab order: Rule Toggles & QC Run · QC Types · Recovery Tiers ·
Sample Corrections · Analyte × Matrix · Surrogate Map · EIS · Calibration ·
CCV · IS Response · Lab Workflow · Advanced.

Verified: full-form save round-trip preserves both stores (matrix_factors=13,
spike_levels=6, qc_acceptance=5; qc_rules FDA toggles=14, global intact); JS
tables (saltAdjBody/matrixFactorsBody) still populate after the move.

## D54 — Salt adjustment: per-analyte, default 1.0, CoA lot → inventory (2026-07-03)

User model: every analyte carries a salt factor (default 1.0); the factor
seldom changes but the CoA lot number updates with each new standard lot.
Confirmed: CoA lot LINKS to the reagent inventory (traceability, not free text).

- Salt table now server-renders ONE row per master-set analyte (32 for FDA),
  each with a factor input (default 1.0) and a CoA-lot <select>.
- CoA lot dropdown = "Standard / Reference Material" lots from the Reagent
  Inventory (name — lot #, EXPIRED flagged red). Empty-inventory warning links
  the analyst to add reference-standard lots. Establishes reagent-lot → result
  traceability (golden rule #6, §10).
- Storage: salt_adjustment_factors = [{analyte, factor, lot_uid, lot_number}].
  Only meaningful rows persist (non-default factor OR a linked lot) — the 30
  untouched default-1.0/no-lot analytes stay out of the file (lean).
- Save is named fields (salt_factor.<kw> + salt_lot.<kw>, guarded by
  salt_present); legacy JSON fallback retained. Salt JS population removed.
- Verified: 32 rows render at default 1.0; seeded a Wellington PFAC-MXA
  (lot MXA-2453-A) standard → dropdown populated → saved PFOA=0.9636 linked +
  PFOS=1.0 linked → both stored with lot_uid + lot_number; others omitted.

## D55 — Matrix Adjustment Factors tied to core SampleTypes (2026-07-03)

**Verification (user asked which representation ties to core SampleTypes):**
- matrix_uid_map {title→core SampleType UID} is AUTHORITATIVE; the method↔core
  association derives sampletype_uids from it. Analyte × Matrix map
  (supported_matrices) == matrix_uid_map.keys() (verified). Spike Levels keyed
  by the same titles. ALL tie to core SampleTypes.
- **matrix_factors did NOT** — free-text lowercase substrings (muscle/deer/beef/
  pork/poultry/fish/egg/milk/feed), matched in the pipeline by fragile substring
  `entry in m`. Half weren't SampleTypes at all. Golden-rule-#3 violation.

**Fix (confirmed):** Matrix Adjustment renders ONE row per supported matrix
(from matrix_uid_map → core SampleType), default 1.0, badged "core type". Save =
named fields matrix_factor.<title>; stores {matrix, factor, sampletype_uid};
non-default rows only. Legacy substring entries collapse onto the matching
supported matrix on render + migrate away on first save (deer/beef/pork/poultry
0.5 → "Meat / Muscle" 0.5). JS population removed.

**Pipeline:** sample_factor() now matches the core SampleType title EXACTLY
(case-insensitive), with legacy substring as fallback. Verified in worker:
Meat / Muscle→0.5, Animal Feed→2.0, case-insensitive, Drinking Water→None.
Both senaite + worker restarted.

## D56 — CCV+IS under Calibration; Sample Duplicate params wired (2026-07-03)

**CCV & IS Response under Calibration (user):** the standalone CCV and IS
Response tabs were folded into the Calibration tab (renamed "Calibration & CCV")
under a "Continuing Verification" group — CCV recovery + IS/surrogate response
are calibration-verification, not separate concerns. The two tabs removed; JS
valid-list + default-tab updated. Verified: fields render once (no dup IDs),
save round-trip persists ccv (72/128), is (vs_ical 50), all from the one tab.

**Duplicate params under Recovery tab (user):** the "Duplicate / LFSMD RPD"
section moved from the (removed) CCV tab into the Recovery Tiers tab.

**Sample Duplicate parameters (user) + disconnection fix:** AUDIT found the
editable dup field (dup_rpd_max) wrote to profile.duplicate.rpd_max, which the
pipeline NEVER reads — it evaluates sample duplicates from qc_acceptance.Dup
(_resolve_fda_tier). So the sample-duplicate limit wasn't actually wired. Fixed:
- Section relabelled "Sample Duplicate (Dup) RPD" (field sample precision;
  RPD = |A−B|/((A+B)/2)×100), placed under Recovery.
- Save now writes BOTH profile.duplicate.rpd_max AND
  qc_acceptance.Dup.tiers[0].rpd_max (with a valid catch-all tier), so the
  field drives the pipeline. Accessor dup_rpd() reads the pipeline-used value.
- Verified end-to-end: set RPD=18 → both stores updated → worker's Dup rule
  returned rpd_max=18.0 (was disconnected). Restored to FDA-standard 20.
- Engine note: the duplicate check evaluates rpd_max ONLY (no RL-threshold /
  low-level branch), so RPD max % is the single wired sample-duplicate param.

## D57 — Surrogate/IS map: per-method, derived, tied to core services (2026-07-03)

**Audit (answers to user's questions):**
- Surrogates stored 3 ways: code master INTERNAL_STANDARDS (27, tagged
  surrogate/injection_is) + NATIVE_ANALYTES.surrogate_is (native→surrogate) +
  per-method surrogate_map (was blank). Core AnalysisServices DO carry the tie:
  pfas_role populated = 47 analyte / 26 surrogate / 1 injection_is (M4PFOA).
- GAP: the surrogate-map dropdown fed from get_surrogates() = the GLOBAL 26
  pool; the method association linked only its 32 analytes (no surrogate/IS).
  So it couldn't show per-method surrogates. master_analyte_set = natives only.

**Decision (confirmed): derive from analyte set + editable overrides.**
- surrogate_is_data() now DERIVES the method's surrogate set = union of each
  native's default surrogate (NATIVE_ANALYTES.surrogate_is), pre-filled;
  dropdown shows ONLY the method's surrogates (20 for FDA), not the global 26.
- Each row shows: default vs override tag + a 🔗core link to the surrogate's
  core AnalysisService (pfas_role) or a ⚠ not-in-core flag.
- Injection IS derived from role=injection_is (M4PFOA), pre-filled.

**Data inconsistency found & fixed (normalization):** 6 natives (4:2/6:2/8:2/
10:2FTS, FOSA, GenX) stored the surrogate NAME ("13C8-FOSA") in surrogate_is
instead of the KEYWORD ("M8FOSA"), breaking the core tie. Added name→keyword
canonicalization (via INTERNAL_STANDARDS) in the accessor — all 20 now resolve
to the core keyword (FOSA→M8FOSA, 6:2FTS→M2-6:2FTS, GenX→M3HFPO). 20/20 tie to
core. (Source-data fix of those 6 rows recommended as follow-up so the pipeline
reads canonical keywords too.)

Bug fixed: _core_service_roles() had a wrong self-import of _portal (it's a
module-level fn) — returned empty, so everything showed not-in-core.

## D58 — Surrogate/IS pulled from core AnalysisServices (source of truth) (2026-07-03)

User principle: core services are required for reporting, so analytes/surrogates/
IS must be pulled FROM the AnalysisServices, not parallel code tables (which
drifted — see the FTS/FOSA keyword mismatch in D57).

Confirmed approach: the native→surrogate quantification link lives ON the core
analyte service (new field).

- **New extender field `pfas_quant_surrogate`** on every AnalysisService (beside
  pfas_role): on an analyte service, the keyword of the surrogate service that
  quantifies it. The authoritative native→surrogate link on core.
- **Migration** stamped 29 analyte services from the canonicalized code map,
  fixing the 6 FTS/FOSA/GenX name→keyword issues AT SOURCE (FOSA→M8FOSA,
  6:2FTS→M2-6:2FTS, GenX→M3HFPO); 0 surrogates missing in core.
- **surrogate_is_data() now sources from services** (`_pfas_service_index`):
  each native's default surrogate = its service's pfas_quant_surrogate; surrogate
  SET = services with pfas_role=surrogate (20 for FDA, all in_core); injection IS
  = pfas_role=injection_is service (M4PFOA). Code tables no longer consulted for
  the link.
- **Save writes back to services** (`_sync_surrogate_links`): editing the map
  sets pfas_quant_surrogate on the core services (the store); then
  `_rebuild_surrogate_map` rebuilds profile.surrogate_map FROM services as the
  pipeline export (complete + canonical). Verified: PFDA→M8PFOA round-trip hit
  the service; empty submit rebuilt 21 entries from services; worker reads
  canonical keywords.

REMAINING (offered): master_analyte_set is still a hardcoded per-method list;
fully deriving the analyte SET from the method's linked analyte services (the
association) is the natural next step to complete "everything from services".

## D59 — master_analyte_set derived from core AnalysisService.Methods (2026-07-21)

Completes D58's remaining step. The per-method native analyte SET is now derived
from the services that actually report, not a hardcoded Python list.

**Source of truth (confirmed):** core SENAITE `AnalysisService.getMethods()` —
the native Method↔Service relation the new-method wizard already maintains
(method_wizard.py:580). The method's native set = AnalysisServices with
`pfas_role == "analyte"` whose `getMethods()` includes the profile's linked core
Method (resolved via method_bridge.get_core_method). No parallel add-on store.

**Accessor (minimal blast radius, confirmed):** new
`get_master_analyte_set(portal, method_id)` in method_profile_store. The canonical
`get_included_analytes()` routes through it (its docstring already mandates all
downstream callers use it, so surrogate map / QC / report / EDD inherit the
derivation). Direct profile["master_analyte_set"] readers are left reading the
stored list, which the backfill keeps identical — no behavior change today.

**Membership vs order:**
- MEMBERSHIP = service-derived (getMethods + pfas_role=analyte).
- ORDER = preserved from the stored profile master_analyte_set sequence, then
  any extra member appended in NATIVE_ANALYTES (analyte library) order.
  Verified: EPA_537_1 and EPA_1633A stored order does NOT match the library
  order (deliberate method-document table order), so ordering MUST come from the
  stored list to avoid reported-column drift. FDA order does match the library.

**Prerequisite backfill (required — default methods are unlinked):** the 3
default seeded methods never had setMethods called (setuphandlers only stamps
pfas_role). `migrations/backfill_method_analyte_links.py` links each core
Method to exactly the services in that profile's stored master_analyte_set,
idempotent, and is also called from post_install. Seed = the stored profile
lists, NOT analysis_services.csv's Method column: the CSV additionally lists
`br-PFHxS`/`br-PFOS` (branched isomer components summed via isomer_summation,
never reported as independent rows — method_profile_store.py:127) which would
silently add 2 analytes to the FDA and 1633A reported panels. Isomer summation
is a self-contained profile config (isomer_summation), independent of getMethods,
so linking only the reported natives does not orphan it.

**Safety fallback:** get_master_analyte_set falls back to the stored list when no
core Method is linked or no method-linked analyte services are found (pre-backfill
robustness). export_profiles_to_file also writes the derived set into
method_profiles.json (byte-identical post-backfill) so the exported SSOT field
reflects the service derivation.

**Consumer-path note (scope boundary):** master_analyte_set is the SSOT consumed
by spec_sync (AnalysisSpec ResultsRange), the config UI, and get_included_analytes.
The pipeline worker's *reported* analyte list, however, comes from a SEPARATE
representation — `display_analyte_set` (display names, derived in the export from
`per_analyte` rows) + `analyte_matrix_inclusion` — and does NOT read
master_analyte_set. So D59 makes the config/spec side service-derived; it does
NOT by itself make the pipeline's reported panel service-derived. Fully unifying
these (deriving per_analyte / display_analyte_set from services too, or collapsing
the two representations into one) is the natural D60 follow-on and was NOT in
D59's approved scope.

**Verification note:** the migration's check counts real getMethods() linkage per
method independently (n>0 and n==len(stored)); comparing get_master_analyte_set()
to the stored list alone is a tautology because its fallback returns the stored
list. The standalone migration sets setSite/setHooks (required for api.get_tool).

**Live status:** code complete + offline-verified (stored lists match the CSV
Method column; order preserved byte-identical). Actual getMethods() service
linkage is CREATED by the backfill and is NOT yet verified live — the container
was down and the docker-socket fix needs the user. Run the backfill + its
self-check to confirm the derivation is active.

**LIVE-VERIFIED 2026-07-21:** ran backfill against the real DB — getMethods()
linkage already present & correct (FDA 32/32, 537 18/18, 1633 40/40); backfill a
clean no-op (committed nothing); br-PFHxS/br-PFOS correctly excluded; export +
get_included_analytes route through the derivation; profile page renders 200; no
regression. Aside (NOT D59): live FDA profile stores PFODA×Eggs=True, so the
documented carve-out is absent in this DB (only seeds on fresh install) — a
regulatory config item for the user, not a code fix.

## D60 — reported analyte panel (display_analyte_set) service-derived too (2026-07-21)

Extends D59 to the pipeline's *reported* panel. The Py3 worker's analyte list
comes from `display_analyte_set` (display names) + `analyte_matrix_inclusion`,
NOT master_analyte_set. Previously export derived display_analyte_set from
`per_analyte` rows, which only FDA has populated — so EPA 537.1 and 1633A
exported an EMPTY display set and the worker reported zero analytes for them.

**Scope (confirmed: minimal / export-only).** In `export_profiles_to_file`,
`display_analyte_set` is now derived for EVERY method from the service-derived
`master_analyte_set` (D59) via the analyte library's keyword→display map
(`NATIVE_ANALYTES`, single source — the same alias per_analyte used). `per_analyte`
stays as the source of per-analyte PARAMETERS (tiers/factors/confirm-ions) only,
no longer doubling as the membership list.

**Verified live end-to-end (2026-07-21):**
- FDA: display=32, BYTE-IDENTICAL to the old per_analyte-derived list (no
  regulated-output drift).
- 537.1: 18, 1633A: 40 — newly populated (were 0). Every keyword maps; no
  unmapped analytes.
- Py3 worker (`get_analyte_list` / `get_included_display_analytes`) now returns
  32 / 18 / 40 — previously 0 for 537.1 and 1633A. Real gap fixed.
- Pipeline tests unchanged (5 pass; test_537_vs_1633 pre-existing unrelated fail).

**Not done (deliberately out of scope, offered as D60b):** the worker's
`get_included_display_analytes` maps display→keyword for the Method×Matrix filter
via an FDA-specific table (`_FDA_DISPLAY_TO_KW`); for 537.1/1633A it falls back to
identity (correct for their analytes, but conservative — an unmapped differing
name defaults to included, never dropped). Making that map method-agnostic
(exported from NATIVE_ANALYTES) is the exact-filter follow-on.

## D61 — reconcile live FDA inclusion with documented carve-out (PFODA×Eggs) (2026-07-21)

The FDA method excludes PFODA from the Eggs matrix (encoded in
`_FDA_MATRIX_EXCLUSIONS = {"PFODA": {"Eggs"}}`; the default seed applies it via
`_fda_analyte_matrix_inclusion()`). The LIVE stored FDA profile had drifted to
`PFODA×Eggs = True` — the panel save is authoritative and persists whatever the
grid submitted, so a save made before the carve-out was reflected clobbered it
back to all-True. Not a save-path bug; a one-time data drift.

**Remedy:** `migrations/reconcile_fda_matrix_exclusions.py` — forces every
DOCUMENTED carve-out cell to False in the stored inclusion, leaves every other
cell exactly as stored, idempotent, commits only on change. This is the home for
any future documented carve-outs (add them to _FDA_MATRIX_EXCLUSIONS, re-run).

**Live-verified 2026-07-21 end-to-end:** store PFODA×Eggs False → Eggs panel 31,
Meat 32; export JSON `PFODA: {Eggs: False, else True}`; Py3 worker
get_included_display_analytes FDA×Eggs = 31 (PFODA excluded), Meat = 32 (PFODA
included); profile page renders 200. Durable: the grid now renders PFODA×Eggs
unchecked, so a subsequent manager save preserves it.

NOTE: only PFODA×Eggs is documented in _FDA_MATRIX_EXCLUSIONS. Other FDA
per-matrix carve-outs from the method document (if any) are NOT yet encoded —
that requires the FDA method doc and is a separate item, not assumed here.

## D62 — 1633A EIS rules carry verify_against_method=True (2026-07-21)

The pipeline module docstring and CLAUDE.md §8 both require 1633A per-analyte EIS
limits (Tables 6/8) to be flagged for verification against the purchased method
copy ("never fabricate a regulatory value"). The `qc_rules` EIS branch in
`pfas_pipeline/method_profiles.py` returned its QCRule WITHOUT
`verify_against_method=True`, contradicting its own docstring and failing the
long-standing `tests/test_profiles.py::test_537_vs_1633`. Code was the bug (the
test/docstring encoded the intent), not a design ambiguity.

**Fix:** EIS branch now returns `verify_against_method=True`. Behaviour impact is
annotation-only: qc_engine consults the flag ONLY after a recovery is already
outside limits (qc_engine.py:531 returns pass BEFORE the flag is read), where it
appends " [VERIFY limits vs method tables]" to the failure message. No change to
pass/fail, limits, or which analytes fail. Scoped to 1633A EIS; FDA/537 rules
unchanged (verified live: 1633A EIS True, FDA LFSM False). Test suite now 6/6.

## D63 — state-specific EDD profiles: full untie from Maine EGAD (2026-07-22)

**Confirmed with lab (four design forks):**
- **(a) Profile model:** state-format-by-reference, NOT a method×state matrix. A
  profile = one STATE program's EDD format+vocabulary; the METHOD is fixed by the
  batch (§3) and supplies analytes/units/test/CAS by reference. A literal
  method×state matrix would duplicate method-owned content into every cell — a §3
  single-source violation. Applicable EDD = f(client's state profile, batch method).
- **(b) Untie scope:** FULL. The state profile now owns the qualifier map, QC-type
  map, and per-analyte parameter naming / state code overrides — previously
  hardcoded lab-global Maine vocabulary (`_EGAD_ANALYTE_OVERLAY`, `DEFAULT_QUALIFIER_MAP`,
  `DEFAULT_QC_TYPE_MAP`). Format-only (D47) left the output Maine-semantic underneath;
  this removes that.
- **(c) Client cardinality:** ONE state per client. The existing single
  `edd_profile` association is retained (now points at a state profile). The
  Maine `egad_enabled` boolean gate is superseded by "client has a state profile."
- **(d) Delivery:** ONE email — the CSV attached to the core report (COA) email.
  Requires overriding senaite.impress's email path (core override, §6C) — built
  in step D after live inspection of the running impress version; documented
  separately. Resolves the standing discrepancy between Round-7 Decision (k)
  ("attached to client report email") and the code (separate email).

**Data model (`senaite.pfas.edd_profiles`):** each profile gains `state`,
`qualifier_map`, `qc_type_map`, `analyte_naming` ({keyword: {parameter_name,
code_override, note}}). REAL CAS stays single-sourced in `analyte_reference`;
`code_override` holds ONLY a state-specific code (Maine DEP#####) where the state
uses one instead of CAS — reference, not duplicate (§3).

**Builder:** `EGADBuilder._apply_profile_vocab(profile)` swaps the lab-global
qualifier/QC/analyte-CAS maps for the resolved state profile's own vocabulary.
Validation still runs on the Maine superset for now (required-field-per-profile
deferred, flagged not built).

**Migration (without loss, §8):** `migrate_state_profile_vocab(portal)` (run from
post_install) folds each pre-D63 profile's missing vocab from the LIVE lab-global
maps — not the DEFAULT constants — so an install that customized the lab-global
qualifier/QC/CAS maps keeps those edits. `_analyte_cas_to_naming` reconstructs
`code_override` faithfully: a stored cas_no differing from the single-source master
is a state override; one equal to master is just the real CAS (no override).
`get_edd_profiles` also fills missing vocab on read so the builder is correct even
before the upgrade step persists.

**Verified (pure-logic harness):** Maine qualifier/QC dicts + 34-analyte CAS map
byte-identical to the prior lab-global overlay; a second (NH) profile translates
N.D.→ND and emits real single-sourced CAS for PFOS (1763231) where Maine emits
DEP18026; migration round-trips lab-global→naming→CAS without loss. Live SENAITE
verification + step D (core email override) still pending.

### D63 step D — EDD CSV rides the report (COA) email (built + live-verified 2026-07-22)

- **Override view** `senaite.pfas.browser.edd_email.PFASEmailView` subclasses
  core `bika.lims.browser.publish.emailview.EmailView`; `email_attachments`
  calls `super()` then appends one state EDD CSV per distinct batch across the
  emailed reports. Try/except so EDD assembly can never break the report email.
- **Registration (no core fork, no global replace):** `@@email` re-registered
  for IAnalysisRequest + IClient on `ISenaitePFASLayer` in `overrides.zcml`
  (plain `<include>`, not includeOverrides). Core registers `@@email` on the
  `IBikaLIMS` layer — which is INDEPENDENT of ISenaiteCore (neither derives from
  the other), so the prior single-base PFAS layer was NOT more specific than it.
  **Fix:** `ISenaitePFASLayer` now extends BOTH `ISenaiteCore` AND `IBikaLIMS`,
  so any PFAS-layer view is strictly more specific than a core view on either —
  our `@@lims-setup`/sidebar (ISenaiteCore) and `@@email` (IBikaLIMS) all win by
  adapter specificity. Permission mirrors core's `ManageAnalysisRequests`
  (keep in sync on upgrade). §6C core-touch — documented, upgrade-fragility noted.
- **Gate:** the CSV attaches only when the client's per-client EDD config has
  `egad_enabled` (the explicit "emit a state EDD for this client" opt-in) — the
  default `edd_profile=maine_egad` would otherwise attach an EDD for every
  ordinary commercial client. STATE = client's `edd_profile`; METHOD = batch's.
  BLOCKING-validation EDDs are NOT attached (bad file); batch-stored EDD +
  export view still surface the errors.
- **No double-send:** the separate publish-transition EDD email in
  `egad_publish.py` is disabled (kept commented for rollback); generation +
  batch-annotation storage retained for audit/download. Resolves the standing
  Round-7 Decision (k) vs code discrepancy — now one email, as decided.
- **Live-verified (running SENAITE 2.6, impress 2.6.0):** clean Zope boot;
  `@@email` on the PFAS layer resolves to `PFASEmailView` for IAnalysisRequest
  AND IClient (core keeps `EmailView` on IBikaLIMS); maine profile byte-identical
  after migration (state ME, N.D.→U, PFOS DEP18026/PFOS_A_L, 34 analytes); a
  cloned NH profile translates N.D.→ND + emits real single-sourced CAS for PFOS;
  EGAD Config page renders the new state-vocabulary editors (HTTP 200, no error).
- **Dev-env note:** `docker compose restart senaite` reruns buildout's
  precompiler (force=True), which needs to (re)write `.pyc` into the bind-mounted
  `/addon` tree as the container user; host-owned files blocked it → boot abort.
  Cleared stale `.pyc` + made the src tree writable to unblock. Pre-existing
  quirk (also: `qc/control_chart.py` carries py3 annotations the py2 precompiler
  warns on — latent, not touched here).
- **Deferred (flagged, not built):** required-field validation is still the
  Maine superset (not yet per-profile); revisit when a non-Maine state needs a
  different required set.

  **Artifact evidence (end-to-end, real objects):** created an egad_enabled demo
  client + batch + received-equivalent sample with PFOS/PFOA/PFNA results, ran
  the real builder + PFASEmailView. Produced `PFAS_Demo_Site_B-###_YYYYMMDD_EDD.csv`
  with 3 real data rows (Maine: PFOS→DEP18026/PFOS_A_L, PFOA→335671, PFNA→375951,
  conc 12.5); `_build_edd_attachment` returned a valid text/csv MIME part
  (non-empty payload); the opt-in gate flipped attachment count 1↔0;
  `email_attachments` = core PDFs (0 here) + our CSV = 1 (property appends via
  super()); switching the client to an NH profile emitted real CAS 1763231 (no
  DEP18026). All changes aborted (not persisted). Harness fed the genuinely-
  existing analyses past the un-received-sample catalog gap — no product code
  altered.

  **BEHAVIORAL CHANGE to confirm with lab:** EDDs now attach to the report
  **Email** action (impress) rather than auto-sending on the publish/
  publish_immediately transition. A sample auto-published WITHOUT going through
  the Email action will send no EDD. Correct if the normal flow is
  "publish → Email report"; revisit if the lab ever auto-publishes.

## D64 — shared QA sign-off attestation on controlled records (2026-07-22)

**Confirmed with lab:** (a) a RENDERED attestation (not a per-document e-sign
workflow); (b) QAO + Laboratory Director resolved from Configuration → Print
Settings (staff-pool selectors; their uploaded LabContact Signature is the
stamp); (c) applied to SOP + reagent/standard prep logs (FM-ENV-250/251/252/253)
+ Prepared Standards.

**Review finding first:** print header/footer was already a solid single source
(`print_settings.py` → shared `printhead`/`printfoot` macros, inherited by ~40
templates). The gap was QA sign-off — fragmented (logbooks had free-text
Prepared/Reviewed; prep-std cert had Prepared/Reviewed; SOP a signer roster),
NO shared 3-tier (Analyst→QAO→Director) block, and Lab Director wasn't seeded.

**Built:**
- Print Settings gains `qao_initials` + `director_initials` (+ `show_signoff`);
  `get_signoff_signers(portal)` resolves them via the staff pool. Seeded
  "Quality Assurance Officer" + "Laboratory Director" LabContacts.
- Shared `signoff` METAL macro in pfas_macros.pt (define-once, §6C/§7): renders
  "This {noun} was prepared by {analyst}" + stamp / "Reviewed and verified by
  {QAO}, Quality Assurance Officer" + stamp / "Authorized by {Director},
  Laboratory Director" + stamp. Missing stamp → ruled line for wet signature.
- Wired into logbooks 250 (reagent) / 251 (standard) / 252 (extraction) / 253
  (sample-processing) via a `tal:define` wrapper; prep-std certificate
  (`_render_cert_html`) upgraded to the 3-tier names.

**Two METAL gotchas fixed (live):** (1) `tal:define` on the `metal:use-macro`
element did NOT reach the macro in Chameleon — must define on a WRAPPING element
around the use-macro. (2) A `define-macro` placed in the page-macro body renders
INLINE on every page (like printhead) — the signoff definition emitted a stray
default "document" block site-wide; fixed by gating the macro on a caller var
(`tal:condition` on `signoff_noun`), so it renders only where explicitly used.

**Live-verified (headless render):** logbook 250 shows exactly one block with
noun "reagent" + resolved QAO/Director; nouns correct on 251/252/253; no stray
block on non-artifact pages (print-settings, data-review); prep-std cert emits
the 3-tier; Print Settings page renders the selectors. Stamps show as ruled
lines until real signatures are uploaded to the LabContacts.

**Not done this pass (flagged):** SOP controlled doc is an uploaded PDF — the
macro can't stamp the PDF itself; the attestation belongs on a rendered SOP
record if desired, or via PDF overlay (separate capability). Prep-std cert is a
saved file, so signature IMAGES are not embedded there (names only); base64
stamp embedding is a follow-up.

## D65 — CoA issuance as a controlled documentation publication (2026-07-23)

Extends D64 (internal-record attestation) to the CLIENT-FACING Certificate of
Analysis. Scope confirmed with lab: FULL controlled-document treatment — the
attestation ON the certificate AND a controlled issue register with
revision/amendment tracking. Build attestation first, register second.

**Audit findings (grounded, this session):**
- CoA today (D45) is only a hand-off link to core senaite.impress
  `/samples/publish` (`data_review.py:1125`). The add-on ships NO custom impress
  report template and does NO controlled-doc handling for the client certificate.
- impress discovers report templates via `plone.resource` directories of type
  `senaite.impress.reports` (`impress/template.py` `TemplateFinder` →
  `iterDirectoriesOfType`). An add-on registers its own `templates/reports/` dir
  under that type; the template appears in the picker as `senaite.pfas:<name>.pt`.
  → upgrade-safe, NO core fork (§6C).
- Core `Default.pt` composes the report by calling `view.render_*` methods (NOT
  METAL macros); `analysisrequest/templates/signatures.pt` ALREADY renders a
  "Responsibles" block (managers + Signature images) + a "Published by" actor
  (`view.current_user`). → the PFAS template must REPLACE the signatures section,
  not append a second block (would duplicate/fight core; violates Golden Rule 3).
- Core `ARReport` (`bika/lims/content/arreport.py`) already stores `DatePublished`,
  publisher, `Recipients`, `SendLog`, `Pdf`, `Html`, `ContainedAnalysisRequests`,
  `Metadata` — it IS the publication record, and it is cataloged. Every publish
  creates a NEW ARReport (`impress/storage.py create_report`).

**Confirmed design decisions:**
- **Signatories = ACTUAL WORKFLOW ACTORS** (not D64's static Print Settings pool):
  prepared-by = analyst who submitted the worksheet (to_be_verified actor from
  review history), verified-by = the manager/QAO who verified, authorized/
  published-by = the publishing user — resolved live from AR/analyses review
  history with real timestamps. Multi-sample CoA may list several analysts.
- **Authorization event = existing verify → publish** (D45); NO new workflow
  state/gate. Publishing by an authorized role IS the authorization.
- **Register storage = ANNOTATION on the core ARReport** (single-object-owned →
  §7 says annotate, NOT SQLite) + a catalog-query "Controlled Publications" view.
  PFAS annotation adds: report ID, revision no., authorizer, amendment reason,
  supersede→prior-ARReport-UID. References core ARReport data, never duplicates it
  (Golden Rule 3).
- **Reissue/amendment** = core's new-ARReport-per-publish is the revision chain
  (ordered by DatePublished); PFAS annotation stamps revision no. + reason +
  supersede link. Original ARReport is NEVER modified (matches deviation rule).

Implementation plan (Phase A attestation, Phase B register) pending build sign-off.

**A1 built + verified (2026-07-23):** `templates/reports/CertificateOfAnalysis.pt`
registered via `plone:static` (name `senaite.pfas`, type `senaite.impress.reports`)
in `configure.zcml`. impress `TemplateFinder` discovers
`senaite.pfas:CertificateOfAnalysis.pt`; clean boot. Template is a verbatim copy
of core `Default.pt`'s `view.render_*` section calls.

**A2 built + LIVE-VERIFIED (2026-07-23):** attestation replaces the
`render_signatures` line with a call to a new `@@pfas-coa-attestation` view
(`browser/coa_attestation.py` + `templates/coa_attestation.pt`, registered
`for="*"`). The view resolves the 3 tiers from live workflow history:
`api.get_review_history(sample [+ analyses])` → `submit` actor = prepared-by,
`verify` actor = verified-by, `api.get_current_user()` = authorized-by. Each
actor → `api.get_user_contact(user, ["LabContact"])` for fullname / job title /
`…/Signature` image; ruled line when no signature on file. Called from the CoA
template via `context.restrictedTraverse('@@pfas-coa-attestation')(collection=
view.collection, report_view=view)` (`context`=portal, `view`=impress
ReportView exposing `.collection`).
- Warm HTTP render of published EGG-0001 (`@@ajax_publish/render_reports`,
  template=`senaite.pfas:CertificateOfAnalysis.pt`): 23.6 KB report; attestation
  present with Prepared/Verified (admin, real submit/verify timestamps) +
  Authorized (publisher); **core `section-signatures`/`Responsibles` ABSENT**
  (replaced, not duplicated); ruled siglines (admin has no signature on file).
- **Dev gotchas:** (1) impress `TemplateFinder`/catalog lookups (`SuperModel(uid)`,
  `sample.getAnalyses()`) read STALE in `bin/instance run` (ZEO cache) → verify via
  HTTP; the sample's OWN review history carries submit/verify rolled up, so it is
  the primary source. (2) ajax dispatch prepends `ajax_` → the path segment is
  `render_reports`, not `ajax_render_reports`. (3) **Run `bin/instance run` as
  `-u senaite`, NOT root** — root-run Chameleon writes `/data/cache/*.py` owned by
  root, then the senaite server hits `Permission denied` compiling new templates
  (chown `/data/cache` back to senaite to recover).

**B1 built + verified (2026-07-23):** publication-log subscriber on the sample
publish transition (see commit c44f7fc). `browser/controlled_publications.py`:
`on_after_transition` (mirrors egad_publish) → `record_publication` appends an
immutable entry to `senaite.pfas.controlled_pub_log` on the sample. Revision =
log length; supersede link; reissue with no captured reason → `reason_missing`
flag (best-effort policy). Status computed (latest = current), never stored.
Verified: guard rejects non-publish transitions; rev1/2/3 numbering + flag +
supersede + status correct; test annotation cleaned up.

**B3 built + verified (2026-07-23):** `@@pfas-controlled-publications` register
view (ManageBika, cross-client, read-only) — report ID, sample, client,
revision, current/superseded, authorizer, issued date, recipients + PDF link
(live from the referenced ARReport), amendment reason / "reason not recorded"
flag. Sidebar link added to REPORTING (manager-gated). Verified over HTTP:
empty-state + seeded rev1/rev2 rows render correctly; cleaned up.

**A3 built + verified (2026-07-23):** CoA carries report ID (`sample-Rn`,
PROSPECTIVE revision computed at render time = prior issues + 1) in the
attestation title + a "Controlled documentation publication … uncontrolled when
printed" footer stamp. `coa_attestation.controlled_doc_meta`. Verified: render
shows stamp + EGG-0001-R1 + attestation.

**Default template (2026-07-23):** `senaite.impress.default_template` set to
`senaite.pfas:CertificateOfAnalysis.pt` (live + profile registry.xml). Prior
default was MultiDefault (combined); PFAS CoA is single-per-sample so each
sample issues its own controlled certificate. **Flagged:** if the lab ever
publishes a batch as ONE combined report, a MultiDefault-based PFAS CoA variant
would be needed (not built).

**B4 amendment-reason capture UI — BUILT + verified (2026-07-23, commit dde9a7a):**
(a) up-front — Data Review "Generate COA" shows a reason field on an amended
reissue (`is_reissue`/`reissue_ars`); `_handle_record_amendment_reason` stashes
it via `set_pending_amendment_reason` on the reissue ARs then redirects to the
publisher; the republish subscriber consumes it. (b) fill-in-later — flagged
register rows carry an inline form; the register view's POST handler (CSRF
disabled like data_review) calls `update_amendment_reason` on that specific
entry, clearing the flag; only the reason is editable, issuance facts stay
immutable. Verified: (b) HTTP POST filled a flagged rev2 (flag cleared, rev1
untouched); (a) stashed reason consumed onto the entry via a REAL jsonapi
republish, pending key cleared; (a) handler runs over HTTP (302, no error);
`batch_url` confirmed present.

**FULL-DATASET END-TO-END VERIFICATION (2026-07-23, commit 9bf64cb):** built
COA-DEMO-0001 (client-1, Eggs/FDA) via `seed_published_coa.py` — all 32 FDA
analyte results + 192 QC rows — and drove it through the REAL workflow:
per-analysis submit (32) → per-analysis verify (32, self-verification enabled) →
sample `publish` (all via jsonapi). Results:
- Real `publish` (verified→published) fired the subscriber → register recorded
  **COA-DEMO-0001-R1, authorizer=admin** (real user, real transition — closes the
  synthetic-event gap definitively).
- CoA renders the full 32-analyte panel + attestation (real prepared/verified
  actors) + report ID + controlled stamp (HTTP render, 54 KB).
- Amend = republish (user's model: "amending simply republishes … minor changes
  like date"): stashed a reason + created a representative ARReport →
  `republish` → **R2 current (report_uid resolved, reason recorded), R1
  superseded**. Register VIEW renders both rows with correct current/superseded
  badges + the reason.
- **Workflow lesson:** `setStatusOf` forces a state but skips the bookkeeping the
  publish/republish guards check, leaving the sample non-firable ("Invalid
  transition"); the sample MUST reach published through real transitions
  (submit→verify→publish) for republish/amend to be available. Sample-level
  submit/verify do NOT cascade — fire per-analysis. Self-verification must be
  enabled for one user to submit+verify (demo seed does this — a global
  bika_setup change to revert for production).

**(a) reachability — the amend path is REPUBLISH, confirmed by the user
("amending simply republishes the data … changes should be minor like date").**
The Data Review up-front branch (`is_reissue`) was still never live-rendered
here because no worksheet joins to a published sample (`_batch_ars()` empty on
all 5 worksheets), so `is_reissue` is False everywhere. Two open questions: (1) whether real amend
flows route through Data Review's "Generate COA" at all vs. re-publishing from
the samples listing (where (a)'s trigger never fires); (2) whether the worksheet
↔ published-sample join (`_batch_ars`) holds at reissue time. **(a)'s machinery
is verified but its live trigger is not** — confirm the lab's actual amend entry
point before relying on (a). **(b) covers the best-effort policy regardless** —
the register captures the issuance, flags a missing reason, and lets the QAO
record it later, independent of (a).

D65 verification env: live Docker Desktop stack, published EGG-0001, warm-HTTP
render via `@@ajax_publish/render_reports` (path segment is `render_reports`,
NOT `ajax_render_reports`). Always run `bin/instance run` as `-u senaite`.

**BUG FOUND + FIXED (2026-07-23) — republish:** core `EmailView.publish()`
maps sample status -> transition `{"verified":"publish","published":
"republish"}`, so an amended REISSUE fires **`republish`**, which the subscriber
did NOT listen for → every revision >= 2 would have been missed (the exact case
the register exists for). `PUBLISH_TRANSITIONS` now = publish / publish_immediately
/ republish. This surfaced only when doing a REAL publish (all prior B checks
used synthetic events).

**Real end-to-end verification (2026-07-23):** fired a REAL `republish` on
EGG-0001 via **senaite.jsonapi** (`POST @@API/senaite/v1/update/<uid>`
`{"transition":"republish"}` — D45's path; `content_status_modify` GET is a
CSRF no-op, and `bin/instance run` doActionFor fails on the guard's
`guard_handler`). Result: review_history gained a real `republish` by admin;
the subscriber recorded EGG-0001-R1 with **`authorizer=admin`** (real user; was
`None` in every synthetic test). Multi-sample render under the new default
template produced **2 individual CoAs**, each with its own attestation + report
ID + stamp (no broken multi-render).

**LIMITATION (documented):** on the jsonapi publish path `report_uid` is None
(that path creates no ARReport) → the register row has no PDF link / recipients,
only the issuance + authorizer + revision. On the impress **email** path the
ARReport is created by `ajax_save_reports` BEFORE `EmailView` fires the publish
transition, so `report_uid` resolves. If the lab issues CoAs via jsonapi, add an
ARReport-creation step (or accept link-less register rows).

---

## 2026-07-28 — QC-type labels: drop "PFAS" prefix (single source = RefDef Title)

**Context:** User: 'The QC Types should not be labelled "PFAS...". We don't need
to include "PFAS" denotations on everything.' The QC-type display labels resolve
from SENAITE core Reference Definition Titles (single UI-editable source, tagged
`[QC:CODE]` / stamped `pfas_qc_code`), consumed by the control-chart
dropdown/legend, method-profile toggles and QC rules.

**Decision (executed):** Strip the leading `"PFAS "` from all 13 QC-type
Reference Definition Titles on the live DB (`rename_qc_titles_drop_pfas.py`;
prior title backed up to annotation `senaite.pfas.title_backup`). Because the
label source IS the Title, this propagates to every surface — including core
SENAITE reference-sample pickers, which is desired.

**Orphan fix (§3.4):** `setuprefs.py` matched existing defs *by Title string*
(`_get_or_create_ref_def`) and filtered `existing_ref_defs()` on `"PFAS" in
Title` — a live rename would have made `@@pfas-setup-references` recreate
"PFAS …" duplicates. Changed to match by the STABLE `pfas_qc_code` (title
fallback) and de-prefixed the seed titles, so the Title is now freely
UI-editable without ever breaking setup idempotency. `setup_qc_type_refdefs.py`
title keys de-prefixed and made prefix-tolerant.

## 2026-07-28 — Configurable per-method Run Builder template

**Context:** User asked for a UI-interactive way to determine how runs are
submitted onto the LC-MS. `run_builder.py:build_sequence()` hardcoded the
injection order (and still emitted a stale `LCS` from before the LCS→LFB merge).
Chosen configurability level (AskUserQuestion): **"Ordered QC blocks."**

**Decision (executed):** A per-method **run template** — `{opening:[codes],
bracket_qc:code, closing:[codes]}` — stored ON the method profile
(`senaite.pfas.method_profiles`; §3 the METHOD owns its bracketing). Editable
on the Run Builder page (Manager-only POST `action=save_template`) as
add/remove/reorder QC chips. QC vocabulary is drawn from the same Reference
Definition source as the control charts (no re-hardcoded QC list). Bracketing
FREQUENCY stays sourced from `instrument_verification.ccv.frequency` (single
source). The `CAL` chip expands at build time to the method's calibration ladder
+ one bracketing injection, only when the per-run "include calibration" box is
ticked. Default template is DERIVED from each method's `associated_qc_types`
(FDA has no LFB → matrix-spike QC only; EPA methods include LFB) — no template
literals duplicated into DEFAULT_PROFILES. Output manifest/CSV shape unchanged;
stale `LCS` removed. The pipeline worker does not consume the template
(worklist-generation concern only).

**Gotcha:** SENAITE renders these templates via **Chameleon**, which parses
inline `<script>` content and chokes on any bare `<` / `</` / `&` (e.g. `</g` in
a regex, `</span>` in an innerHTML string, `&&`). The chip editor JS is written
purely with DOM APIs (createElement/textContent) and nested ifs — no literal
markup, no `&&` — to keep the block parseable.

## 2026-07-28 — Run Builder template: single drag-and-drop sequence (revises the 3-block model)

**Context:** User: "I need to be able to move the extracted QC inside the CCV
bracketing. Ideally … a drag and drop system vs up/down arrows." The 3-block
model (opening → samples → closing) structurally forced extracted QC (MB/LFB/
LFSM/LFSMD) to sit fully before or after the samples — never inside the
bracketed body.

**Decisions (AskUserQuestion, user-confirmed):**
- **Placement = "Grouped inside the bracket."** Extracted QC are dragged into
  the bracketed body (typically just before the field samples), not interleaved
  on an every-M-samples interval.
- **Bracket counting = "Yes, they count."** Every injection in the bracketed
  body — extracted QC AND field samples — advances the "CCV every N" counter.

**Executed:** The run template is now ONE ordered `sequence` of tokens (QC
codes, the `CAL` ladder token, and exactly one `SAMPLES` block) plus `bracket_qc`
— replacing `{opening, closing}`. `run_template()` migrates legacy saved
templates (`opening + SAMPLES + closing`; a trailing literal CCV is de-duped by
the builder). `build_sequence()` walks the sequence: tokens before `CAL` are
pre-bracket (e.g. the system MeOH blank); `CAL` emits the ladder + an opening
bracket and starts the body; thereafter each injection ticks the interval and a
CCV is inserted every N; an explicitly-placed bracket-QC token resets the
interval and suppresses the auto-closing CCV (fixes a double-CCV at the run
end); a single closing CCV ends the run if it didn't already. Editor UI is a
vertical **HTML5 drag-and-drop** list (grip + drag to reorder; Field-samples row
is movable but not removable); bracket selector filtered to non-blank QC types.
Same manifest/CSV output shape. Stale test templates cleared so all three
methods show the clean derived default.

**Reconfirmed Chameleon rule:** the DnD JS is pure-DOM with NO bare `<`, `&`, or
`&&` (used `0 > offset` instead of `offset < 0`, nested ifs instead of `&&`) so
the inline `<script>` parses.

## 2026-07-29 — Run Builder tweaks: CCV auto-only, ICV non-counting, label fixes

Follow-ups on the drag-and-drop run sequence (all user-directed):
- **CCV removed from the editor's choices.** The bracket QC is always CCV and
  its interval comes from the method profile, so the bracket-QC selector is gone
  and CCV is excluded from the sequence add-list (`add_vocabulary()` = QC vocab
  minus CCV). `_handle_save_template` defaults `bracket_qc` to "CCV" (no field
  posted).
- **ICV no longer advances the CCV interval** — "counted like a calibrator."
  `build_sequence` skips `body_tick()` for codes in `_noncount_codes()`, sourced
  from the RefDef `pfas_category == "instrument"` (CAL, ICV, CCV; constant
  fallback). Extraction QC (MB/LFB/LFSM/LFSMD) and field samples still count.
- **Label changes (single source = RefDef Title / run-builder token):** CCB
  RefDef Title renamed "Continuing Calibration Blank" → **"Solvent Blank"**
  (`rename_ccb_to_solvent_blank.py`; setup_qc_type_refdefs CREATE seed updated;
  identity stays the [QC:CCB] tag). The CAL sequence token label changed
  "Calibration ladder" → **"Calibrator list"** (run_builder `_chip` + the
  add-list option).

Stale test run_templates cleared so all three methods show the clean derived
default.

## 2026-07-29 — Calibrator naming: method-specific, sourced from core Method.MethodID

**Context:** the calibrator injection prefix was hardcoded "FDA-CAL-" on EVERY
method (so EPA worklists wrongly read "FDA-CAL-1"). User: make it method-specific
and tied to the internal code stored in senaite core services; "interconnected …
impacts overall usability and quality."

**Decisions (AskUserQuestion, user-confirmed):** (1) Calibrator code = the core
SENAITE **Method.MethodID** (FDA_32PFAS / EPA_537_1 / EPA_1633A) — already stored
in core, resolved via `method_bridge.get_core_method`; verbose but no new
storage. (2) **Unify everywhere + migrate.**

**Executed — single source `method_bridge.get_method_cal_code(portal, method_id)`**
(returns Method.MethodID; falls back to profile id, then "CAL"). Routed through:
- `run_builder._cal_names` → live worklist names `{MethodID}-CAL-{n}-{ymd}`.
- FDA seeds updated to `FDA_32PFAS-CAL-` (FDA's fixed MethodID): `analytes.CAL_LEVELS`,
  `logbooks.FDA_CAL_DEFAULTS`, `prep_logbooks` default `field_schema_json`.
- **Migration** `migrate_cal_names_method_code.py`: stored PrepLogbookDef (FDA
  Cal Curve Prep Log, slug 251 / FM-ENV-002) cal-point names FDA-CAL- →
  FDA_32PFAS-CAL-, so a logged standard traces to its worklist injection.

**Interconnection verified (why it's safe):**
- `get_core_method` resolves by UID/Title, NOT MethodID → editing/using MethodID
  doesn't break resolution. MethodID is coupled to the profile id (wizard/setup
  key on it) so it's an internal identifier, not a freely-editable label.
- Pipeline worker: `pipeline.py` imports only `REVIEW_CHECKS` from
  `injection_builder` — its hardcoded `FDA_CAL_LEVELS`/`InjectionSequenceBuilder`
  (VBA port) are NOT in the import/QC path (pre-existing §7 duplication, left
  as-is). `importer.classify_qc_type` keys on the `-CAL-` substring (new names
  still classify as CAL); the QC engine reads `expected_conc` FROM the instrument
  file, not by name lookup — so renaming injections breaks neither import nor
  calibration % dev.

Live-verified: FDA build worklist shows FDA_32PFAS-CAL-1..10; headless EPA_537_1
/ EPA_1633A show their own codes; migrated FDA prep-logbook CAL-1 = FDA_32PFAS-CAL-1.

## 2026-07-29 — Injection names = linked lot codes + Description column; ICV/Solvent-blank non-counting

Three user-directed run-builder fixes (AskUserQuestion-confirmed):
- **Injection Name = the linked prepared-standard lot** (user chose "literal lot"
  over a fabricated method-code string). Read from the batch's FM-ENV-251
  cal-prep log: `cal_a_lot` → CAL(`-L{n}`)/ICV/CCV; `analyte_spike_lot` →
  LFB/LFSM/LFSMD. Blanks (MB/CCB) and field samples have no prepared-standard
  lot, so they fall back to `{MethodID}-{TYPE}-{yymmdd}-{nn}` / `{MethodID}-{sampleID}`.
  `_QC_LOT_FIELD` maps QC code → 251 lot field. The used lots are also stored on
  the run manifest (the link).
- **Description column** (new, on the worklist table + CSV): `analyst · QC type ·
  lot · prep date` for standards/spikes (real prep date from FM-ENV-251, NOT the
  run date); `analyst · QC type · matrix · run date` for blanks/samples. Lets a
  reviewer read the run without opening the logbooks.
- **ICV + Solvent Blank (CCB) no longer advance the CCV interval.** `_noncount_codes`
  already had CAL/ICV/CCV (RefDef `pfas_category == "instrument"`); CCB was empty-
  category so it counted. Stamped CCB `pfas_category = instrument` live and added
  CCB to the constant fallback set — both instrument-side, ride with the
  calibration, don't count. Extraction QC (MB/LFB/LFSM/LFSMD) + samples still count.
- Dropped the legacy " MeOH-Blank" name suffix (the dedicated Solvent Blank type
  supersedes it).

Live-verified on example-batch-fda32: cal/spike lots + real prep date flow into
names and descriptions; CSV gains the Description column; counting unchanged
except ICV/CCB now excluded.

## 2026-07-29 — CCV bracket opens LAZILY (ICV / solvent blank sit outside it)

**Correction to the previous entry.** Making ICV/CCB non-COUNTING was not the
issue the user reported — the complaint was POSITIONAL: the opening CCV was
emitted the instant the calibrator ladder ended, so an ICV or solvent blank
placed after the calibrators landed *inside* the bracketed region:

    10 CAL-L10 | 11 CCV (bracket) | 12 ICV | 13 CCB | 14 MB …   <-- wrong

**Fix:** the CAL token no longer emits the opening bracket. It sets
`pending_open`, and `open_bracket_if_needed()` fires the bracket immediately
before the FIRST COUNTING injection (extraction QC or field sample). Because
instrument-cal codes (CAL/ICV/CCV/CCB) never count, they stay in the calibration
block, outside the bracketing:

    10 CAL-L10 | 11 ICV | 12 CCB | 13 CCV (bracket) | 14 MB | 15+ samples

Rule: **the calibration block runs to the last instrument-cal injection; the CCV
bracket opens at the first injection that counts toward the interval.** Sequences
with no CAL still open the bracket at the samples. Live-verified on
example-batch-fda32 for both the derived default and a sequence with the solvent
blank placed after the ICV.

---

## 2026-07-30 — Visual logbook builder + guided (training) / concise runtime

**Context:** logbook definitions were authored by hand-typing minified JSON into
one 8-row textarea (no validation, no type list — bad JSON was stored verbatim
and degraded to an empty form), and at runtime every logbook was a single flat
form. Only the extraction log (252) was step-by-step, and nothing in the add-on
had any media. User asked for a visual builder plus a step-by-step training view
with a GIF per step, and a concise view for experienced analysts.

**Confirmed decisions (AskUserQuestion):** guided IS the real entry and doubles
as training (no separate practice mode); mode is a page toggle remembered per
user; media = GIF + stills only; EVERY logbook can be guided; steps live on the
logbook template (PrepLogbookDef); extraction 252 keeps its method-driven guide
and gains GIFs rather than being migrated.

**Shipped, in phases that each left the system working:**
- `logbook_schema.py` — the canonical field vocabulary. `FIELD_TYPES` carries a
  per-type `caps` list mirroring what the renderer ACTUALLY honours, and drives
  the builder UI, the server validator and the help text alike. Also
  `build_steps()`, which guarantees no field is ever lost: unclaimed fields land
  in a trailing synthetic step, a doubly-claimed field belongs to the first
  step, a stale name is dropped.
- Three-tab builder (Fields / Steps / JSON escape hatch) in the prep-logbook
  modal, serialising to hidden inputs so the save path was untouched. Lives in
  `static/logbook_builder.js` — Chameleon parses inline `<script>` and chokes on
  bare `<`, `&`, `&&`.
- `@@pfas-logbook-media` — images on disk under immutable uuid tokens, matching
  the SOP/CoA convention. Tokens are never overwritten, so a new revision shares
  its parent's imagery and an archived revision stays byte-identical, which is
  what `PreparedStandard` (slug, revision) pinning needs.
- Guided runtime as a TEMPLATE choice on the existing view (not a second class),
  reusing the data/save/corrections path. Shared `logbook_field` macro so the
  concise and guided renderers cannot drift; shared `stepper` macro so this did
  not become a third bespoke stepper.
- Extraction stages gained `media`/`media_alt`, rendered in the guide.

**Deliberate choices worth recording:**
- **Free step navigation**, not linear. A logbook is not a procedural interlock;
  forcing linearity would make guided strictly worse than concise for anyone but
  a trainee, killing adoption of the mode we want used.
- **Mode in a server-read cookie**, not sessionStorage. The two modes are
  different templates, so the choice must be known before HTML is produced; web
  storage is readable only after load, costing a flicker or a redirect.

**Bugs found and fixed on the way:**
- `@@pfas-prep-logbooks` was `zope2.View` with NO role check and disabled CSRF
  on every POST — any authenticated user could rewrite logbook definitions.
- The `PrepLogbookDef` `<allow>` list omitted `field_schema_json` and five other
  D17 fields, so restricted/TAL access failed silently.
- The edit form could set status active directly, bypassing `_archive_slug` and
  leaving two active revisions for one slug.
- Each Edit button embedded a full `json.dumps()` in its `onclick`; a quote in
  any value broke it (step instructions certainly would).
- Submitting the modal with Enter bypassed the Save button's onclick, so nothing
  serialised — which would now have posted an empty schema.
- `logbook_dynamic.pt` never invoked the shared `signoff` macro, so 250/251/253
  printed with no QA attestation.

**MERGE-ON-SAVE (the load-bearing change).** `_save_logbook` replaces the batch
annotation wholesale and `_extract_data_from_schema` defaults every schema field
to `""`, so a per-step POST would have zeroed every other step's fields. Fixed at
the caller (five other views pass complete dicts, so making the sink merge would
mask real bugs): seed from `dict(existing)`, then apply an `only_fields`-filtered
extract, and restrict corrections to the submitted step. Shipped and verified
BEFORE any guided UI existed.

**Py2 gotchas recorded:** this codebase uses `unicode_literals`, and waitress
asserts response headers are native `str` — a unicode cookie value raises in
`start_response`, i.e. AFTER the view frame, where try/except cannot catch it.
And `syncStageJson()` rebuilds each stage from an 8-key whitelist, so a new stage
key without a matching `[data-field]` input is silently dropped on the next save.

**Data note:** the live FDA_32PFAS profile was found storing
`extraction_stages: []` — an empty list, which (unlike an absent key) masks
`get_profile`'s top-level backfill, so the method had no stages at all. Restored
the 8 documented stages from `DEFAULT_PROFILES`. EPA_537_1 (8) and EPA_1633A (7)
were intact. Likely caused by an earlier profile save while the stage list was
empty — worth watching for.

---

## 2026-07-31 — Guided logbook: presentation fixes, row strike-out, lot defaulting

**Context:** the user reported guided entry was *"confusing on what or how to enter"*.
Screenshotting the running system (Playwright) showed it was not a layout problem — it
was two defects plus one missing lab capability. **Layout confirmed fine and left alone.**

**Presentation (the actual complaint):**
- Instruction bullets rendered literal `&#8250;` over the text. The glyph was raw
  non-ASCII inside a `<style>` block, and Chameleon charref-encodes non-ASCII when it
  serialises a text node, so CSS received an entity it could not read. Fixed with the CSS
  escape `\203A`. **Rule: keep `<style>` blocks in .pt files ASCII-only.**
- Guided rendered every field with browser defaults: extracting the `logbook_field` macro
  left its 21 CSS rule groups behind in `logbook_dynamic.pt`. Moved to
  `static/logbook_fields.css`, linked from both templates. NOT inside the macro (Chameleon
  expands `metal:use-macro` per call, so a `<style>` there emits once per field) and NOT
  in `pfas_macros.pt` (inlined into every page). It sits beside `logbook_runtime.js`,
  which injects half the markup it styles.
- `.btn-save`/`.btn-sm` were referenced app-wide, and by the global print block, but never
  defined globally. Promoted to `pfas_macros.pt` as fallbacks.
- A step with no image no longer renders an empty placeholder box that ate 60% of the
  width while truncating table values to `FDA-!`.
- Verified concise mode is **pixel-identical** before/after the CSS move.

**Row strike-out (new).** A table row can be struck as N/A — recorded, struck through,
never deleted. Stored as a reserved `_na` key IN the row dict with `_na_by`/`_na_at`.
In-row rather than a parallel index list because `dynDelRow` splices the array, which
would silently re-point an index-based structure. Collision-safe because `NAME_RE` forces
a column name to start with a lowercase letter. Attribution is stamped **server-side** so
it cannot be forged and the analyst types nothing; un-striking scrubs all three keys, or a
later re-strike would carry a stale date. New `logbook_schema.active_rows()` is the single
definition of "a row that counts" and is applied in `data_review._build_traceability_tree`,
where a struck row with a half-typed lot would otherwise read as unresolved and block
worksheet release. Nothing is created in inventory from a struck row because nothing is
created from logbook table rows at all — `invokeFactory("PreparedStandard")` occurs once
in the add-on, on the Prepared Standards page.

**Lot defaulting (new + bug fixes).** `usable_lots()` is now the single definition of a
usable lot, delegating to `prepared_standards._list` (which resolves parent-tightened
expiry and sorts by recency). The picker previously skipped only `expired`, so **emptied
lots stayed selectable**. Defaults are computed server-side and applied client-side to
EMPTY boxes only — writing them into `view.data()` would make a never-saved default
indistinguishable from a record, and `data()` feeds the traceability gate.

**Scope correction (user-confirmed):** FM-ENV-250 `solutions.lot_number` is the lot of the
solution being CREATED, so defaulting it would stamp a new solution with an old
identifier. It stays hand-entered; defaulting applies to CONSUMED lots (FM-ENV-251's five
`lot_ref` fields).

**Mark-as-emptied was not merely unexposed, it was not durable:** nothing invoked
`_handle_status`; it accepted any string while `_populate_obj` assigns `obj.status`
directly, bypassing the `schema.Choice` vocabulary; and because the edit modal posts no
status while `_populate_obj` assigned it unconditionally, **editing an exhausted standard
silently resurrected it**. All three fixed.

**Data note:** the seeded prepared standards carried no Standard Type — which is what the
picker filters on — so the FM-ENV-251 lot fields had never matched anything. Typed per the
seeder's own `ps_type` values.

**Deferred:** `lot_ref`/`reagent_ref` as a table COLUMN type (would let FM-ENV-250
`chemicals.lot_num` use the reagent picker). Not needed for the reported case and it
touches the table renderer every logbook uses. Note `logbook_builder.js` hardcodes
`COLUMN_TYPES`, duplicating the Python list — fix that by serving it like `FIELD_TYPES`
when this is picked up.

---

## 2026-08-02 — End-to-end acceptance test on a real instrument run

**Context.** Every module so far had been verified against seeded demo data. A real
FDA 32-PFAS export (`Test Sample.csv` — 1254 rows, 20 injections, 4 silage samples,
2 × 1:10 dilutions, MB, LFSM/LFSMD, 10-point ladder, CCV) was driven end to end:
client → samples → reagents → prepared standards → logbooks → guided extraction →
Run Builder → import → QC → Data Review → report/CoA/EDD. Full write-up in
`E2E_TEST_2026-08-02.md`.

**Decisions taken before starting** (asked, not guessed):
- Matrix: **FDA_32PFAS × Animal Feed** (silage is feed; `Egg-N` is a sample label).
- Posture: **test as-found** — log defects, fix only hard blockers, flag each fix.
- Analyte name mismatches: resolve in `analyte_reference.py`, one canonical alias
  resolver (§1.3). *Superseded by evidence* — see below.

**Only code change made.** `pfas_pipeline/method_profiles.py:940` —
`_DEFAULT_PROFILE_CACHE["FDA_32PFAS"]["recovery_tiers"]` raised `KeyError` (the
default cache has no such key) whenever the loaded profile's `recovery_tiers` is
empty, which the shipped FDA profile's is. This aborted **every** import. Changed to
`.get("recovery_tiers", [])`. Open question this exposes: why is `recovery_tiers`
empty in a profile whose `qc_acceptance` tiers are fully populated? The `N.C.`
("no labeled standard") analyte set now silently resolves to the empty set.

**Test-only unblock, not a product fix.** A `native:0.039` import profile with an
empty pass-through map was registered so the run could proceed past the vendor-key
mismatch. It proves the importer works on *this* file only — the version key is
scraped from sample data, so the next export gets a different key.

**Assumption retired by evidence.** The predicted analyte display-name/keyword
mismatch in `build_summary` does **not** occur: the profile store exports
`display_analyte_set`, so summary matching is correct. No alias resolver was
written. The keyword/display split does bite, but at a different boundary — the two
Data Review pages label the same analyte `10:2 FTS` and `10:2FTS`.

**Headline findings** (17 total, ranked in the report):
- Two vendor detectors that are documented as mirrors disagree, so **no profile
  saved through Import Studio is reachable by the importer**.
- **Dilution results are reported 10× high** — `build_summary` prefers the raw
  `Measured Concentration` over the factor-corrected `Calculated Concentration`,
  while `injection_store` prefers the opposite. Proven against the instrument's own
  `Total` rows. Isomer summation itself is exact.
- **`BLoQ` is silently reported as `N.D.`** (72 rows) — a different regulatory
  statement.
- The **traceability gate and the QC Summary gate cannot pass**: the CoC schema has
  no `batch_id` field so `_linked_batch()` is always `None`; the guided extraction's
  logbook-252 stub omits the reagents/standards it collected; and nothing in the
  pipeline writes `qc_results` or `calibrations`.
- `data_review.batch_method()` returns the Zope id (`method-1`) while profiles are
  keyed by `MethodID` (`FDA_32PFAS`), and `get_profile` returns a **truthy empty
  stub** for an unknown id — so every profile-driven QC criterion silently
  evaporates. `method_bridge.get_method_cal_code` already does this correctly.
- The **Run Builder emits a worklist the LIMS's own validator rejects** (27/27), and
  the **EDD exports 288 rows with empty concentrations without blocking**.

**Test data.** Client `kcp-feed-forage`, batch `kcp-b-001`, worksheet `WS-0005`,
prefix `KCP` / `PS-KCP-`. Pre-test volume snapshots in `/home/robin/pfas_e2e_backup/`.
