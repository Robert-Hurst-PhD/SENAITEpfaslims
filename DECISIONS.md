# DECISIONS.md — senaite.pfas design decisions

Append an entry every time a design decision is confirmed.  Keep entries
in reverse-chronological order (newest first).

---

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
